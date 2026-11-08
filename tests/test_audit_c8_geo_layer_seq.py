"""
pcg100 audit pack c8_geo_layer_seq: the geometry <-> layer and sequence COPs, filled in against the SideFX docs.

References are all hand-computable numbers (point counts, pixel values, coordinates). "Bit-identical to before the change at defaults" uses digests
of the same set of calls from before the change (commit f210100), hard-coded in GOLDEN; `--digests` prints the current digests.
"""
import hashlib
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
from comfyui_pcg import panel as PANEL                  # noqa: E402
from comfyui_pcg.geo.cop import CopImage                # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, VERTEX, PRIM, DETAIL  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def defaults(nid):
    kw = {}
    for part in ("required", "optional"):
        for k, spec in M[nid].INPUT_TYPES().get(part, {}).items():
            if isinstance(spec[0], (list, tuple)):
                kw[k] = (spec[1].get("default", spec[0][0]) if len(spec) > 1
                         and isinstance(spec[1], dict) else spec[0][0])
            elif len(spec) > 1 and isinstance(spec[1], dict) and "default" in spec[1]:
                kw[k] = spec[1]["default"]
    return kw


def run(nid, **over):
    kw = defaults(nid)
    kw.update(over)
    r = getattr(M[nid](), M[nid].FUNCTION)(**kw)
    return r["result"][0] if isinstance(r, dict) else r[0]


def raises(fn, match="", exc=(ValueError, KeyError)):
    try:
        fn()
    except exc as e:
        return match in str(e)
    return False


def names(nid):
    it = M[nid].INPUT_TYPES()
    return [k for part in ("required", "optional") for k in it.get(part, {})]


def near(a, b, tol=1e-6):
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    return a.shape == b.shape and bool(np.allclose(a, b, atol=tol, rtol=0))


def img_with(W, H, **layers):
    im = CopImage(W, H)
    for k, a in layers.items():
        a = np.asarray(a, np.float32)
        if a.ndim == 2:
            a = a[..., None]
        im.set(k, a)
    return im


def L(img, n):
    return np.asarray(img.need(n), np.float64)


def P_(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def A(g, n, cls=POINT):
    a = np.asarray(g.get(cls, n))
    return a[:, 0] if a.ndim == 2 and a.shape[1] == 1 else a


def gdigest(g):
    h = hashlib.sha1()
    h.update(np.ascontiguousarray(g.vertex_point).tobytes())
    h.update(np.ascontiguousarray(g.prim_offset).tobytes())
    for cls in (POINT, VERTEX, PRIM, DETAIL):
        for k in sorted(g.attribs[cls]):
            v = g.attribs[cls][k]
            h.update(f"{cls}/{k}/{v.dtype}/{v.shape}".encode())
            h.update(np.ascontiguousarray(v).tobytes() if v.dtype.kind != "O"
                     else repr(v.tolist()).encode())
    return h.hexdigest()[:16]


# pcg110: COP Bake Textures also writes `bitangent` (tested in test_studio.py); the old layers must stay bit-identical
ADDED_LAYERS = {"bitangent"}


def idigest(img):
    h = hashlib.sha1()
    h.update(f"{img.xres}x{img.yres}".encode())
    for n in sorted(img.names):
        if n in ADDED_LAYERS:              # layers added later on purpose; every layer that existed is still compared
            continue
        a = np.round(L(img, n), 5)
        h.update(f"{n}/{a.shape}".encode())
        h.update(np.ascontiguousarray(a).tobytes())
    return h.hexdigest()[:16]


def json_obj(s_):
    import json
    return json.loads(s_)


def json_get(s_, k):
    return json_obj(s_).get(k)


def digest(x):
    return idigest(x) if isinstance(x, CopImage) else gdigest(x)


# ═══════════════════════════════════════════════════════════════ Shared inputs
_yy, _xx = np.mgrid[0:6, 0:8].astype(np.float64)
RAMP = img_with(8, 6, C=np.stack([_xx / 8, _yy / 6, (_xx + _yy) / 14], -1),
                m=(_xx + 2 * _yy) % 3 == 0, d=_xx / 7.0, h=_yy * 0.25)


# ═══════════════════════════════════════════════════════════════ Old calls
LTP = "PCG_COPLayerToPoints"
BK = "PCG_COPBakeTextures"
from comfyui_pcg.geo.cop import terrain as _TR          # noqa: E402

_bj, _bi = np.meshgrid(np.arange(12) + 0.5, np.arange(12) + 0.5)
BLOW = _TR.to_mesh(img_with(12, 12, h=0.15 * np.exp(-((_bj - 6) ** 2 + (_bi - 6) ** 2) / 12)),
                   "h", 1, 1, 1, True, True)
BLOW.set(POINT, "heat", (np.asarray(BLOW.get(POINT, "P"))[:, 0] * 2).astype(np.float32))
BHIGH = _TR.to_mesh(img_with(20, 20, h=0.05 + 0.02 * np.sin(np.arange(20)[None, :] / 3.0)
                             + np.zeros((20, 1))), "h", 1, 1, 1, True, True)


def bake(**kw):
    r = getattr(M[BK](), M[BK].FUNCTION)(**{**defaults(BK), **kw})
    r = r["result"] if isinstance(r, dict) else r
    return r[0], r[1]


def old_calls():
    """Calls that existed before the change (old parameters only). At defaults the new code must be bit-identical to before."""
    out = {}
    out["ltp_default"] = run(LTP, cop=RAMP)
    out["ltp_mask_jitter"] = run(LTP, cop=RAMP, mask_layer="m", threshold=0.5, jitter=0.7,
                                 rand_seed=3, height_layer="h", height_scale=2.0, attribs="C d")
    out["ltp_stride_xy"] = run(LTP, cop=RAMP, stride=3, plane="xy", world_size=4.0)
    out["ltp_scatter"] = run(LTP, cop=RAMP, mode="scatter", count=50, density_layer="d",
                             rand_seed=9, plane="zy")
    out["bake_low"] = bake(low=BLOW, resolution_x=32, resolution_y=32, attribs="heat")[0]
    out["bake_high"] = bake(low=BLOW, high=BHIGH, resolution_x=32, resolution_y=24,
                            high_attribs="P", dilate=2)[0]
    out["bake_high_md"] = bake(low=BLOW, high=BHIGH, resolution_x=24, resolution_y=24,
                               max_distance=0.08, both_sides=False, dilate=0)[0]
    return out


GOLDEN = {
    "ltp_default": "32a951f98f7db6f5",
    "ltp_mask_jitter": "2f0544d77c5ed3ba",
    "ltp_stride_xy": "ecf7363b33f487e8",
    "ltp_scatter": "15e2a0e08e5eb118",
    "bake_low": "c556056fd53ff24d",
    "bake_high": "ceb8d9d7b700fc3e",
    "bake_high_md": "60b9fbf2d2c0541c",
}

if "--digests" in sys.argv:
    for k, v in old_calls().items():
        print(f'    "{k}": "{digest(v)}",')
    sys.exit(0)


sec("Bit-identical to before the change at defaults")
now = {k: digest(v) for k, v in old_calls().items()}
check(f"output digests of all {len(GOLDEN)} old calls unchanged", len(GOLDEN) >= 7 and now == GOLDEN,
      {k: (GOLDEN.get(k), v) for k, v in now.items() if GOLDEN.get(k) != v})



# ═══════════════════════════════════════════════════════════════ Layer to Points
sec("Layer to Points: each Houdini Method")
# a 4x3 ID layer (row 0 at the bottom): offset = x + y·4
IDV = np.array([[1, 1, 5, 3],
                [23, 3, 5, -1],
                [0, 0, -1, 2]], np.float64)
IDI = img_with(4, 3, id=IDV, C=np.stack([IDV, IDV * 2, IDV * 3], -1),
               two=np.stack([np.zeros_like(IDV), (IDV == 0) * 1.0], -1))
OFF = np.arange(12)
g = run(LTP, cop=IDI, mode="nonzero", mask_layer="id", index_attrib="ix", layer_attrib="v")
check("Non-Zero: one point per pixel with a non-zero value, in ascending offset order",
      A(g, "ix").tolist() == [o for o in OFF if IDV.ravel()[o] != 0])
check("  Layer Attrib = source pixel value (integer)", A(g, "v").dtype.kind == "i"
      and A(g, "v").tolist() == [int(x) for x in IDV.ravel() if x != 0])
check("  position = pixel center (xz, World Size 1: x = (j+0.5)/4 - 0.5, z = -((i+0.5)/3 - 0.5)·0.75)",
      near(P_(g)[:, 0], (A(g, "ix") % 4 + 0.5) / 4 - 0.5, 1e-6)
      and near(P_(g)[:, 2], -((A(g, "ix") // 4 + 0.5) / 3 - 0.5) * 0.75, 1e-6))
g2 = run(LTP, cop=IDI, mode="nonzero", mask_layer="two", index_attrib="ix")
check("Non-Zero looks at all channels: channel 0 all 0, channel 1 non-zero on the two pixels with value 0 -> 2 points",
      A(g2, "ix").tolist() == [8, 9])
check("Non-Zero with empty source layer = C", run(LTP, cop=IDI, mode="nonzero").npoints == 10)

g = run(LTP, cop=IDI, mode="unique_values", mask_layer="id", index_attrib="ix", layer_attrib="v")
check("Unique Values (Ignore Minus One on): 1 5 3 23 0 2 -> 6 points, at the pixel where each value first appears",
      A(g, "ix").tolist() == [0, 2, 3, 4, 8, 11] and A(g, "v").tolist() == [1, 5, 3, 23, 0, 2],
      (A(g, "ix").tolist(), A(g, "v").tolist()))
g = run(LTP, cop=IDI, mode="unique_values", mask_layer="id", index_attrib="ix",
        ignore_minus_one=False)
check("negative control: Ignore Minus One off -> -1 counts too (first at offset 7)",
      A(g, "ix").tolist() == [0, 2, 3, 4, 7, 8, 11])
doc = img_with(7, 1, id=np.array([[1, 1, 5, 3, 23, 3, 5]], np.float64))
check("the docs example 1 1 5 3 23 3 5 -> 4 points",
      run(LTP, cop=doc, mode="unique_values", mask_layer="id", attribs="").npoints == 4)
check("Ignore Minus One does not affect other modes", run(LTP, cop=IDI, mode="nonzero", mask_layer="id",
                                       ignore_minus_one=False).npoints == 10)

CNT = np.array([[0, 2, 1.9], [3, -4, 0]], np.float64)   # 3×2
CI = img_with(3, 2, n=CNT, C=np.zeros((2, 3, 3)))
g = run(LTP, cop=CI, mode="count_per_pixel", mask_layer="n", index_attrib="ix")
check("Count per Pixel: floor(value) points, negatives as 0 (0+2+1+3+0+0 = 6)",
      A(g, "ix").tolist() == [1, 1, 2, 3, 3, 3])
check("  without jitter, points of the same pixel coincide", near(P_(g)[0], P_(g)[1]))
gj = run(LTP, cop=CI, mode="count_per_pixel", mask_layer="n", jitter=1.0, rand_seed=4)
d = np.abs(P_(gj) - P_(g))
check("  Jitter 1: points of the same pixel spread out but stay within the pixel (xz half-width 0.5/3, half-height 0.5/2·(2/3))",
      not near(P_(gj)[0], P_(gj)[1]) and d[:, 0].max() <= 0.5 / 3 + 1e-6
      and d[:, 2].max() <= 0.5 / 2 * (2 / 3) + 1e-6 and d[:, 0].max() > 0.05)
du = (A(gj, "uv") - A(g, "uv")) * np.array([3, 2])
check("  jitter in u and v is independent (not the same random number)", np.abs(du[:, 0] - du[:, 1]).max() > 0.05)
check("multi-channel layer uses channel 0 as the value (C = (n, 2n, 3n))",
      run(LTP, cop=img_with(3, 2, C=np.stack([CNT, 2 * CNT, 3 * CNT], -1)),
          mode="count_per_pixel").npoints == 6)
check("  negative control: Count per Pixel differs from Non-Zero", run(LTP, cop=CI, mode="nonzero",
                                                   mask_layer="n").npoints == 4)
check("  negative control: a different Seed gives different positions", not near(P_(gj), P_(run(LTP, cop=CI, mode="count_per_pixel",
                                                         mask_layer="n", jitter=1.0, rand_seed=5))))

FL = img_with(3, 2, n=np.array([[4.7, 9, 9], [9, 9, 2]], np.float64), C=np.full((2, 3, 3), 0.5))
g = run(LTP, cop=FL, mode="count_first", mask_layer="n", index_attrib="ix", layer_attrib="v")
check("Count from First Pixel: floor(4.7) = 4 points, source pixel offset 0, P all at the origin",
      g.npoints == 4 and A(g, "ix").tolist() == [0] * 4 and near(P_(g), np.zeros((4, 3)))
      and A(g, "v").tolist() == [5] * 4)
g = run(LTP, cop=FL, mode="count_last", mask_layer="n", index_attrib="ix", attribs="C")
check("Count from Last Pixel: 2 points, source pixel offset 5, attributes from that pixel",
      g.npoints == 2 and A(g, "ix").tolist() == [5, 5] and near(A(g, "Cd"), np.full((2, 3), 0.5)))
check("  Count from modes are unaffected by jitter", near(P_(run(LTP, cop=FL, mode="count_last", mask_layer="n",
                                                   jitter=1.0)), np.zeros((2, 3))))
check("  uv is not jittered either (= source pixel center)", near(A(run(LTP, cop=FL, mode="count_last", mask_layer="n",
                                              jitter=1.0), "uv"), [[2.5 / 3, 0.75]] * 2))
check("Count from: negative value -> 0 points", run(LTP, cop=img_with(2, 1, n=[[-3, 1]]), mode="count_first", attribs="",
                                      mask_layer="n").npoints == 0)

sec("Layer to Points:Set Positions / Index Attrib")
g = run(LTP, cop=RAMP, set_positions=False, height_layer="h")
check("Set Positions off: P all 0 (Height Layer not even read), uv still written",
      near(P_(g), np.zeros((48, 3))) and near(A(g, "uv"), A(run(LTP, cop=RAMP), "uv")))
check("negative control: Set Positions on = old behaviour (P not all 0)", np.abs(P_(run(LTP, cop=RAMP))).max() > 0.3)
g = run(LTP, cop=RAMP, mask_layer="m", stride=2, index_attrib="ix", layer_attrib="lv")
ix = A(g, "ix")
check("pixels mode can also write Index Attrib: offsets and uv match (x + y·8)",
      near((ix % 8 + 0.5) / 8, A(g, "uv")[:, 0]) and near((ix // 8 + 0.5) / 6, A(g, "uv")[:, 1])
      and ix.dtype.kind == "i")
check("  Layer Attrib takes the Mask Layer's value (all 1 here)", A(g, "lv").tolist() == [1] * g.npoints)
check("empty attribute name = not written", "ix" not in run(LTP, cop=RAMP).attribs[POINT])
check("panel check_layout is empty", PANEL.check_layout(LTP, M[LTP].INPUT_TYPES()) == [])
check("new parameters appended at the end", names(LTP)[-4:] == ["layer_attrib", "index_attrib", "set_positions",
                                          "ignore_minus_one"])



# ═══════════════════════════════════════════════════════════════ Point Generate
PG = "PCG_COPPointGenerate"
sec("Point Generate (new node)")


def cloud(P, **pt):
    g = Geometry.from_points(np.asarray(P, np.float32))
    for k, v in pt.items():
        g.set(POINT, k, np.asarray(v))
    return g


from comfyui_pcg.geo import build                       # noqa: E402
box = build.grid(2.0, 2.0, 2, 2)                        # 4 points 1 prim
check("Parameters: no input connected -> Number of Points points, all at the origin",
      run(PG, number_of_points=7).npoints == 7 and near(P_(run(PG, number_of_points=7)), np.zeros((7, 3))))
g = run(PG, points=box, number_of_points=3)
check("Append on: the original 4 points + 3, prims all dropped (point cloud)", g.npoints == 7 and g.nprims == 0
      and near(P_(g)[:4], P_(box)) and near(P_(g)[4:], np.zeros((3, 3))))
g = run(PG, points=box, number_of_points=3, append_points=False)
check("negative control: Append off -> only the 3 new points", g.npoints == 3)
# fractional: 2 + 30 x 0.05 = 3.5 -> 3 or 4, decided by Seed; across many seeds both occur, and only these two
ns = {run(PG, number_of_points=2, points_per_second=30.0, time_step=0.05, rand_seed=k).npoints
      for k in range(40)}
check("Points per Second x Time Step is added to Number of Points, the fractional part kept at random (3.5 -> {3, 4})",
      ns == {3, 4}, ns)
check("  no randomness for integers", {run(PG, number_of_points=2, points_per_second=24.0, rand_seed=k).npoints
                     for k in range(10)} == {3})
fr = [run(PG, number_of_points=0, points_per_second=1.0, time_step=0.25, rand_seed=k).npoints
      for k in range(400)]
check("  keep probability ~ fractional part (0.25, 400 seeds)", abs(np.mean(fr) - 0.25) < 0.07, np.mean(fr))

src = cloud([[1, 0, 0], [2, 0, 0], [3, 0, 0]], count=np.array([2, 0, 3], np.int32),
            Cd=np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], np.float32))
g = run(PG, points=src, method="point_attribute", append_points=False)
check("Point Attribute: each source point copied count times (2 + 0 + 3), with Copy * both P / Cd follow",
      g.npoints == 5 and near(P_(g)[:, 0], [1, 1, 3, 3, 3])
      and near(A(g, "Cd")[:, 2], [0, 0, 1, 1, 1]))
g = run(PG, points=src, method="point_attribute", append_points=False, copy_attribs="Cd")
check("Copy Attributes = Cd: P not copied (at the origin), Cd copied", near(P_(g), np.zeros((5, 3)))
      and near(A(g, "Cd")[:, 0], [1, 1, 0, 0, 0]))
g = run(PG, points=src, method="point_attribute", append_points=False, copy_attribs="* ^Cd")
check("  exclusion syntax * ^Cd: Cd is the default 0, P copied", near(A(g, "Cd"), np.zeros((5, 3)))
      and near(P_(g)[:, 0], [1, 1, 3, 3, 3]))
ref = cloud([[9, 9, 9]], n=np.array([4.9], np.float32))
g = run(PG, points=src, ref=ref, method="point_attribute", count_attrib="n")
check("Ref connected: count and copied values come from Ref (floor(4.9) = 4, P = (9,9,9)), appended after points",
      g.npoints == 7 and near(P_(g)[3:], [[9, 9, 9]] * 4) and near(P_(g)[:3, 0], [1, 2, 3]))
check("  attributes the new points have from points but not copied from Ref are defaults (Cd = 0)", near(A(g, "Cd")[3:], np.zeros((4, 3))))
det = Geometry()
det.set(DETAIL, "count", np.array([[6]], np.int32))
check("Detail Attribute:detail count = 6", run(PG, ref=det, method="detail_attribute").npoints == 6)
check("  missing attribute gives a human-readable error", raises(lambda: run(PG, points=box, method="detail_attribute"), "count")
      and raises(lambda: run(PG, points=box, method="point_attribute"), "count"))

ids = cloud([[0, 0, 0], [1, 0, 0]], id=np.array([4, 10], np.int32))
g = run(PG, points=ids, number_of_points=3)
check("id: continues numbering from max(id)+1 (11 12 13)", A(g, "id").tolist() == [4, 10, 11, 12, 13])
ids.set(DETAIL, "nextid", np.array([[100]], np.int32))
ids.set(DETAIL, "idstep", np.array([[5]], np.int32))
g = run(PG, points=ids, number_of_points=3)
check("  nextid / idstep: 100 105 110, nextid updated to 115", A(g, "id").tolist() == [4, 10, 100, 105, 110]
      and int(np.asarray(g.get(DETAIL, "nextid")).ravel()[0]) == 115)
check("  not added when there is no id attribute", "id" not in run(PG, points=box, number_of_points=2).attribs[POINT])
check("  with Append off the new points continue numbering too", A(run(PG, points=ids, number_of_points=2, append_points=False),
                                      "id").tolist() == [100, 105])
det2 = Geometry()
det2.set(DETAIL, "count", np.array([[6.7]], np.float32))
check("Detail Attribute takes floor (6.7 -> 6)",
      run(PG, points=det2, method="detail_attribute").npoints == 6)
det3 = Geometry()
det3.set(DETAIL, "count", np.array([[-2.0]], np.float32))
check("  negative -> 0 points", run(PG, points=det3, method="detail_attribute").npoints == 0)
check("detail attributes go along to the output (Append on, input has only detail)",
      run(PG, points=det2, number_of_points=2).get(DETAIL, "count") is not None)
check("  carried along with Append off too", run(PG, points=det2, number_of_points=2,
                             append_points=False).get(DETAIL, "count") is not None)
grp_g = box.copy()
grp_g.set_group(POINT, "top", np.array([0, 0, 1, 1], bool))
g = run(PG, points=grp_g, number_of_points=2)
check("point groups kept, new points not in the group", g.groups[POINT].get("top") is not None
      and np.asarray(g.groups[POINT]["top"]).tolist() == [0, 0, 1, 1, 0, 0])
check("panel check_layout is empty", PANEL.check_layout(PG, M[PG].INPUT_TYPES()) == [])



# ═══════════════════════════════════════════════════════════════ Layer from Attribute
LFA = "PCG_COPLayerFromAttrib"
sec("Layer from Attribute (new node)")
from comfyui_pcg.geo.cop import geolayer as GL           # noqa: E402
vals = np.arange(1, 11, dtype=np.float32)                 # 10 elements 1..10
gv = cloud(np.zeros((10, 3)), val=vals, Cd=np.stack([vals, -vals, 2 * vals], -1))
o = L(run(LFA, geo=gv, attrib="val", resolution_x=4, resolution_y=3), "attrib")[..., 0]
check("Bottom Left: row 0 (bottom) = 1 2 3 4, row 1 = 5..8, row 2 = 9 10 0 0 (extra pixels are 0)",
      near(o, [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 0, 0]]), o.tolist())
o = L(run(LFA, geo=gv, attrib="val", data_ordering="top_left", resolution_x=4, resolution_y=3),
      "attrib")[..., 0]
check("Top Left: the top row (row 2) = 1 2 3 4, bottom row 0 = 9 10 0 0",
      near(o, [[9, 10, 0, 0], [5, 6, 7, 8], [1, 2, 3, 4]]), o.tolist())
o = L(run(LFA, geo=gv, resolution_x=2, resolution_y=2), "attrib")
check("3-component attribute -> 3 channels; elements beyond the pixel count are dropped", o.shape == (2, 2, 3)
      and near(o[1, 1], [4, -4, 8]))
for shp, wh in (("pow2_square", (4, 4)), ("square", (4, 4)), ("single_row", (10, 1)),
                ("single_column", (1, 10))):
    im = run(LFA, geo=gv, attrib="val", resize_layer=True, resize_shape=shp)
    check(f"Resize {shp}: 10 elements -> {wh[0]}x{wh[1]}", (im.xres, im.yres) == wh)
check("Resize size: Square and Power of 2 differ (5 -> 3x3 vs 4x4; 17 -> 5x5 vs 8x8; 16 -> 4x4 for both)",
      [GL.resize_shape(n, "square") for n in (5, 17, 16, 1, 0)] == [(3, 3), (5, 5), (4, 4), (1, 1), (1, 1)]
      and [GL.resize_shape(n, "pow2_square") for n in (5, 17, 16, 1, 0, 65)]
      == [(4, 4), (8, 8), (4, 4), (1, 1), (1, 1), (16, 16)])
im = run(LFA, geo=gv, attrib="val", resize_layer=True, resize_shape="single_column")
check("  Single Column bottom to top 1..10", near(L(im, "attrib")[:, 0, 0], vals))
ref = img_with(5, 2, C=np.ones((2, 5, 3)))
im = run(LFA, geo=gv, attrib="val", size_ref=ref, out_layer="v")
check("size_ref sets the resolution, layer added on top of it (C still there)", (im.xres, im.yres) == (5, 2) and "C" in im.names
      and near(L(im, "v")[..., 0], [[1, 2, 3, 4, 5], [6, 7, 8, 9, 10]]))
im = run(LFA, geo=gv, attrib="val", size_ref=ref, resize_layer=True, resize_shape="single_row")
check("negative control: with Resize on, size_ref is ignored", (im.xres, im.yres) == (10, 1) and "C" not in im.names)
idx = img_with(3, 2, C=np.array([[9, 0, -1], [1.6, 10, 4]]))
o = L(run(LFA, geo=gv, attrib="val", size_ref=idx, index=idx), "attrib")[..., 0]
check("index: each pixel reads the element given by index (rint); out of range (-1, 10) is 0",
      near(o, [[10, 1, 0], [3, 0, 5]]), o.tolist())
check("  index resolution differing from the output raises", raises(lambda: run(LFA, geo=gv, attrib="val", index=idx,
                                                          resolution_x=4, resolution_y=4), "index"))
from comfyui_pcg.geo import build as _b2                 # noqa: E402


def _strg():
    g = cloud(np.zeros((2, 3)))
    g.set_string(POINT, "name", ["a", "b"])
    return g


gq = _b2.grid(2.0, 2.0, 3, 3)                            # 4 prims
gq.set(PRIM, "pid", np.array([7, 8, 9, 6], np.float32))
gq.set(DETAIL, "dv", np.array([[3, 4]], np.float32))
check("Primitive class", near(L(run(LFA, geo=gq, attrib="pid", attrib_class="prim", resize_layer=True,
                                 resize_shape="single_row"), "attrib")[0, :, 0], [7, 8, 9, 6]))
check("Detail class: one element (2 components)", near(L(run(LFA, geo=gq, attrib="dv", attrib_class="detail",
                                               resize_layer=True), "attrib"), [[[3, 4]]]))
gq.set(VERTEX, "vv", np.arange(gq.nvertices, dtype=np.float32))
im = run(LFA, geo=gq, attrib="vv", attrib_class="vertex", resize_layer=True, resize_shape="square")
check("Vertex class: 16 vertices -> 4x4, value = vertex number", gq.nvertices == 16 and im.xres == 4
      and near(L(im, "attrib")[..., 0].ravel(), np.arange(16)))
check("string attribute raises", raises(lambda: run(LFA, geo=_strg(), attrib="name"), "is a string"))
check("missing attribute gives a human-readable error", raises(lambda: run(LFA, geo=gv, attrib="nope"), "nope"))
check("panel check_layout is empty", PANEL.check_layout(LFA, M[LFA].INPUT_TYPES()) == [])



# ═══════════════════════════════════════════════════════════════ Geometry to Layer
GTL = "PCG_COPGeoToLayer"
sec("Geometry to Layer (new node)")
from comfyui_pcg.geo import volops as VO, ops as GOPS      # noqa: E402
_Z, _Y, _X = np.meshgrid(np.arange(5), np.arange(3), np.arange(4), indexing="ij")


def vol(name, k=0.0):
    """rx 4 x ry 3 x rz 5, voxel size 1, origin (0,0,0); value = x + 10y + 100z + k."""
    g = VO.create_volume(res=(4, 3, 5), size=(3, 2, 4), center=(1.5, 1, 2), name=name)
    g.set_pdata(0, "voxels", (_X + 10 * _Y + 100 * _Z + k).astype(np.float32))
    return g


V1 = vol("density")
o = run(GTL, geo=V1, slice_offset=2.5)
xx, yy = np.meshgrid(np.arange(4), np.arange(3))
check("XY Plane, z = 2.5: 4x3, value = x + 10y + 250 (linear interpolation between two slices), layer name = name",
      o.names == ["density"] and (o.xres, o.yres) == (4, 3) and near(L(o, "density")[..., 0],
                                                                    xx + 10 * yy + 250, 1e-4))
o = run(GTL, geo=V1, slice="yz", slice_offset=1.0)
yv, zv = np.meshgrid(np.arange(3), np.arange(5))
check("YZ Plane, x = 1: horizontal axis y, vertical axis z (3x5), value = 1 + 10y + 100z",
      (o.xres, o.yres) == (3, 5) and near(L(o, "density")[..., 0], 1 + 10 * yv + 100 * zv, 1e-4))
o = run(GTL, geo=V1, slice="zx", slice_offset=0.5)
zz, xv = np.meshgrid(np.arange(5), np.arange(4))
check("ZX Plane, y = 0.5: horizontal axis z, vertical axis x (5x4), value = x + 5 + 100z",
      (o.xres, o.yres) == (5, 4) and near(L(o, "density")[..., 0], xv + 5 + 100 * zz, 1e-4))
check("plane outside the volume -> all 0", near(L(run(GTL, geo=V1, slice_offset=4.5), "density"), np.zeros((3, 4, 1)))
      and near(L(run(GTL, geo=V1, slice_offset=-0.5), "density"), np.zeros((3, 4, 1))))
check("  exactly on the edge (z = 4) takes the last slice", near(L(run(GTL, geo=V1, slice_offset=4.0), "density")[..., 0],
                                       xx + 10 * yy + 400, 1e-4))
check("  z = 0 takes the first slice", near(L(run(GTL, geo=V1), "density")[..., 0], xx + 10 * yy, 1e-4))

VV = GOPS.merge(V1, vol("vel.y", 2000), vol("vel.x", 1000), vol("vel.z", 3000), vol("", 7))
o = run(GTL, geo=VV)
check("empty Outputs = one layer per volume; unnamed ones are called output + (index + 1)",
      sorted(o.names) == sorted(["density", "vel.y", "vel.x", "vel.z", "output5"]), o.names)
o = run(GTL, geo=VV, outputs="vel.*", out_type="rgb")
check("vel.* + RGB: combined into one layer sorted by name (x y z channels), layer name vel",
      o.names == ["vel"] and near(L(o, "vel")[0, 0], [1000, 2000, 3000], 1e-3))
o = run(GTL, geo=VV, outputs="vel.*", out_type="rgba")
check("  RGBA: padded with 0", near(L(o, "vel")[0, 0], [1000, 2000, 3000, 0], 1e-3))
o = run(GTL, geo=VV, outputs="vel.*", out_type="uv")
check("  UV: truncated to 2 channels", L(o, "vel").shape[-1] == 2)
check("  Auto: as many channels as matches", L(run(GTL, geo=VV, outputs="vel.*"), "vel").shape[-1] == 3)
o = run(GTL, geo=VV, outputs="density 4 -1", slice_offset=0.5)
check("both name / index (including negative indices) can select", sorted(o.names) == ["density", "output5"])
VI = vol("ids")
VI.set_pdata(0, "voxels", (_X * 0.4).astype(np.float32))
check("ID: takes rint", near(L(run(GTL, geo=VI, out_type="id"), "ids")[0, :, 0], [0, 0, 1, 1]))
check("  negative control: Mono does not round", near(L(run(GTL, geo=VI, out_type="mono"), "ids")[0, :, 0],
                               [0, 0.4, 0.8, 1.2], 1e-6))
check("not found and Optional off -> raises", raises(lambda: run(GTL, geo=V1, outputs="nope"), "nope"))
o = run(GTL, geo=V1, outputs="density nope", optional=True, default_value="0.25",
        size_ref=img_with(4, 3, C=np.zeros((3, 4))))
check("Optional: missing ones use the size_ref resolution + Default Value", near(L(o, "nope"), np.full((3, 4, 1), 0.25))
      and "density" in o.names)
o = run(GTL, geo=V1, outputs="nope", optional=True, out_type="rgb", default_value="1 2 3",
        size_ref=img_with(2, 2, C=np.zeros((2, 2))))
check("  Default Value follows Type's channel count", near(L(o, "nope")[1, 1], [1, 2, 3]))
check("  Optional without size_ref connected -> raises", raises(lambda: run(GTL, geo=V1, outputs="nope", optional=True),
                                              "size_ref"))
check("different slice resolutions -> raises (layers of one image share a resolution)",
      raises(lambda: run(GTL, geo=GOPS.merge(V1, VO.create_volume(res=(2, 2, 2), name="s"))),
             "convert with two nodes"))
check("  volumes matched by vel.* with different resolutions -> raises",
      raises(lambda: run(GTL, geo=GOPS.merge(vol("vel.x"), VO.create_volume(res=(2, 2, 2), name="vel.y")),
                         outputs="vel.*"), "can't be combined"))
check("no volumes -> raises", raises(lambda: run(GTL, geo=box)))
check("panel check_layout is empty", PANEL.check_layout(GTL, M[GTL].INPUT_TYPES()) == [])



# ═══════════════════════════════════════════════════════════════ Sequence / Time Pack
SQ, TP = "PCG_COPSequenceClips", "PCG_COPTimePack"


def mkseq(n, base=0.0, W=3, H=2):
    return [img_with(W, H, C=np.full((H, W), base + i), m=np.full((H, W), 10 * (base + i)))
            for i in range(n)]


def vals(seq):
    return [float(L(f, "C")[0, 0, 0]) for f in seq]


sec("Sequence (new node)")
A5, B5 = mkseq(5), mkseq(5, 100)
r, n = M[SQ]().run(A5, "", 0)
check("empty Clips = unchanged", vals(r) == vals(A5) and n == 5)
r, n = M[SQ]().run(A5, "1 2; 3 2", 0, B5)
check("two clips two inputs: A[1..2] + B[3..4]", vals(r) == [1, 2, 103, 104] and n == 4, vals(r))
r, _ = M[SQ]().run(A5, "0 1; 4 1; 2 2", 0, B5)
check("more clips than inputs: clip 3 is taken from the last input (B)", vals(r) == [0, 104, 102, 103], vals(r))
r, _ = M[SQ]().run(A5, "0 2\n0 2", 0)
check("only one input: all clips taken from it; newlines also separate", vals(r) == [0, 1, 0, 1])
r, _ = M[SQ]().run(A5, "3 4", 0)
check("out-of-range frames extend the last frame (hold)", vals(r) == [3, 4, 4, 4])
r, _ = M[SQ]().run(A5, "-2 3", 0)
check("  a negative start frame extends the first frame", vals(r) == [0, 0, 0])
r, _ = M[SQ]().run(A5, "1 2", 2)
check("Output Start Frame 2: the first 2 frames repeat the first clip's first frame", vals(r) == [1, 1, 1, 2])
r, _ = M[SQ]().run(A5, "1 3", -1)
check("  -1: drops the first frame", vals(r) == [2, 3])
check("  dropping everything raises", raises(lambda: M[SQ]().run(A5, "1 3", -3), "drops every frame"))
check("frame count < 1 / malformed raises", raises(lambda: M[SQ]().run(A5, "1 0", 0), "frame count >= 1")
      and raises(lambda: M[SQ]().run(A5, "1 2 3", 0), "start_frame frame_count"))
r, _ = M[SQ]().run(A5, "0 1; 0 1; 0 1", 0, None, B5)
check("an unconnected middle input is skipped (seq3 becomes the second input)", vals(r) == [0, 100, 100])
check("empty sequence raises", raises(lambda: M[SQ]().run([], "", 0), "is empty"))
check("panel check_layout is empty", PANEL.check_layout(SQ, M[SQ].INPUT_TYPES()) == [])

sec("Time Pack (new node)")
S6 = mkseq(6)
o = run(TP, seq=S6, frame=2.0)
check("Relative -1 to 1, Step 1, Frame 2: takes frames 1 2 3, layer name suffixes _0 _1 _2",
      sorted(o.names) == sorted(["C_0", "C_1", "C_2", "m_0", "m_1", "m_2"])
      and [L(o, f"C_{k}")[0, 0, 0] for k in range(3)] == [1, 2, 3]
      and L(o, "m_2")[0, 0, 0] == 30)
o = run(TP, seq=S6, frame=2.0, add_time_as="prefix", layers="C")
check("Prefix: '0_C' ...; Layers takes only C", sorted(o.names) == ["0_C", "1_C", "2_C"])
o = run(TP, seq=S6, frame=2.0, mode="absolute", range_start=0.0, range_end=4.0, step=2.0,
        layers="C")
check("negative control: Absolute 0 to 4 step 2 -> frames 0 2 4 (ignores Frame)",
      [L(o, f"C_{k}")[0, 0, 0] for k in range(3)] == [0, 2, 4] and len(o.names) == 3)
o = run(TP, seq=S6, mode="absolute", range_start=1.0, range_end=2.0, step=0.5, layers="C")
check("fractional time 1.5 interpolates linearly between two frames", near([L(o, f"C_{k}")[0, 0, 0] for k in range(3)],
                                         [1, 1.5, 2]))
o = run(TP, seq=S6, mode="absolute", units="seconds", fps=2.0, range_start=0.5, range_end=2.0,
        step=0.5, layers="C")
check("Seconds: FPS 2, 0.5 to 2 seconds step 0.5 seconds -> frames 1 2 3 4",
      [L(o, f"C_{k}")[0, 0, 0] for k in range(4)] == [1, 2, 3, 4] and len(o.names) == 4)
o = run(TP, seq=S6, frame=0.0, layers="C")
check("out of range (frame -1) extends the first frame", [L(o, f"C_{k}")[0, 0, 0] for k in range(3)] == [0, 0, 1])
o = run(TP, seq=S6, mode="absolute", range_start=0.0, range_end=0.9999999999, step=1.0, layers="C")
o2 = run(TP, seq=S6, mode="absolute", range_start=0.0, range_end=0.99, step=1.0, layers="C")
check("the end point has a float tolerance (0 to 1-1e-10 counts as including 1, takes 2; 0 to 0.99 takes 1)",
      len(o.names) == 2 and len(o2.names) == 1)
check("reversed Range / Step <= 0 raises", raises(lambda: run(TP, seq=S6, range_start=2.0, range_end=1.0),
                                           "is empty (the end")
      and raises(lambda: run(TP, seq=S6, step=0.0), "Step"))
check("  too many samples raises", raises(lambda: run(TP, seq=S6, range_end=1e5, step=1.0), "over the limit"))
check("panel check_layout is empty", PANEL.check_layout(TP, M[TP].INPUT_TYPES()) == [])



# ═══════════════════════════════════════════════════════════════ Bake Geometry Textures
sec("Bake Geometry Textures:Tracer")
from comfyui_pcg.geo import ops as _ops                    # noqa: E402


def plane(y=0.0, size=1.0, n=16):
    """A horizontal grid at height y, normals / winding facing +Y."""
    g = _TR.to_mesh(img_with(n, n, h=np.zeros((n, n))), "h", 1, size, 1, True, True)
    g.set(POINT, "P", (np.asarray(g.get(POINT, "P")) + [0, y, 0]).astype(np.float32))
    return g


FLAT = plane()
ext_ = np.abs(np.asarray(FLAT.get(POINT, "P"))[:, 0]).max()


def inner(o, shrink=0.0):
    """Texels within the grid (the outermost ring of conservatively rasterized texels falls outside the grid)."""
    m = L(o, "mask")[..., 0] > 0.5
    Pb = L(o, "P")
    e = ext_ - shrink
    return m & (np.abs(Pb[..., 0]) <= e) & (np.abs(Pb[..., 2]) <= e)


RB = dict(low=FLAT, resolution_x=32, resolution_y=32, dilate=0)
UP = plane(0.05, 1.2)
DN = plane(-0.03, 1.2)
o, r = bake(high=UP, **RB)
mi = inner(o)
check("Face Culling none: high-res 0.05 above -> displacement 0.05", near(L(o, "displacement")[..., 0][mi],
                                                                    np.full(mi.sum(), 0.05)))
o, r = bake(high=UP, face_culling="back", **RB)
check("Back Faces: shooting up from below at upward-facing prims = back faces -> nothing hit", json_get(r, "ray_hits") == 0)
o, r = bake(high=UP, face_culling="front", **RB)
check("  Front Faces: the same scene still hits", json_get(r, "ray_hits") > 0
      and near(L(o, "displacement")[..., 0][mi], np.full(mi.sum(), 0.05)))
o, r = bake(high=DN, face_culling="back", **RB)
check("  high-res below (reverse direction t < 0, forward direction -N, hits front faces): Back does not block, displacement -0.03",
      near(L(o, "displacement")[..., 0][inner(o)], np.full(inner(o).sum(), -0.03)))
o, r = bake(high=DN, face_culling="front", **RB)
check("  same as above, with Front nothing is hit", json_get(r, "ray_hits") == 0)
TWO = _ops.merge(plane(0.05, 1.2), plane(0.2, 1.2))
d0 = L(bake(high=TWO, both_sides=False, **RB)[0], "displacement")[..., 0][mi]
d1 = L(bake(high=TWO, both_sides=False, ray_bias=0.1, **RB)[0], "displacement")[..., 0][mi]
check("Ray Bias 0.1: start moved to 0.1, skips the 0.05 layer and hits 0.2; displacement still measured from the low-res (0.2)",
      near(d0, np.full(mi.sum(), 0.05)) and near(d1, np.full(mi.sum(), 0.2)))
TWO2 = _ops.merge(plane(0.05, 1.2), plane(0.3, 1.2))
CAGE = plane(0.5)
o, r = bake(high=TWO2, cage=CAGE, tracing_mode="cage_mesh", **RB)
check("Cage Mesh: shooting from the cage (0.5) toward the low-res, first hits the 0.3 layer -> displacement 0.3",
      near(L(o, "displacement")[..., 0][mi], np.full(mi.sum(), 0.3), 1e-5))
o, r = bake(high=_ops.merge(TWO2, plane(0.7, 1.2)), cage=CAGE, tracing_mode="cage_mesh", **RB)
check("  with another layer behind the cage (0.7) it does not search backward (one-way rays)",
      near(L(o, "displacement")[..., 0][mi], np.full(mi.sum(), 0.3), 1e-5))
check("  negative control: Surface Normal takes the nearest 0.05",
      near(L(bake(high=TWO2, **RB)[0], "displacement")[..., 0][mi], np.full(mi.sum(), 0.05)))
check("  cage not connected / different point count -> raises", raises(lambda: bake(high=TWO2, tracing_mode="cage_mesh", **RB),
                                            "cage")
      and raises(lambda: bake(high=TWO2, cage=plane(0.5, n=8), tracing_mode="cage_mesh", **RB), "cage"))
o, r = bake(high=UP, tracing_mode="single_mesh", **RB)
check("Single Mesh: no primary rays, no normal_ts / displacement", "normal_ts" not in o.names
      and "displacement" not in o.names and "ray_hits" not in json_obj(r))

from comfyui_pcg.geo.spatial import ray_cast as _rc     # noqa: E402
_n = 262144 + 7                                             # over the chunking threshold, takes the chunked path
_O = np.zeros((_n, 3))
_D = np.stack([np.linspace(-0.3, 0.3, _n), np.ones(_n), np.zeros(_n)], -1)   # varied directions
_TP = np.array([[-1, 1, -1], [1, 1, -1], [0, 1, 2.0]])
_tri = np.array([[0, 2, 1]])                                 # normal facing +Y (same direction as the rays = back face)
check("ray_cast's chunked path also applies cull (260k rays at a back face: Back hits none, no culling hits all)",
      (_rc(_O, _D, _TP, _tri, cull=1)[0] < 0).all() and (_rc(_O, _D, _TP, _tri)[0] >= 0).all())

sec("Bake Geometry Textures:Texture Maps")
o, _ = bake(high=UP, normal_space="offset", **RB)
check("Normal Space Offset: normal_ts of a parallel high-res = (0.5, 0.5, 1)",
      near(L(o, "normal_ts")[mi], np.tile([0.5, 0.5, 1.0], (mi.sum(), 1))))
check("  negative control: Signed = (0, 0, 1)", near(L(bake(high=UP, **RB)[0], "normal_ts")[mi],
                                       np.tile([0, 0, 1.0], (mi.sum(), 1))))
TILT = _TR.to_mesh(img_with(24, 24, h=np.tile(np.arange(24) * (1.2 / 24) * 0.3, (24, 1)) + 0.1),
                   "h", 1, 1.2, 1, True, True)              # a slope climbing along +X, gradient 0.3
o, _ = bake(high=TILT, world_normal=True, **RB)
nw = np.array([-0.3, 1, 0]) / np.hypot(0.3, 1)
mi2 = inner(o, 0.1)
check("World Normal: the high-res world normal at the hit point (slope (-0.3, 1, 0)/|·|)",
      np.abs(L(o, "worldnormal")[mi2] - nw).max() < 0.02, np.abs(L(o, "worldnormal")[mi2] - nw).max())
o, _ = bake(high=TILT, world_normal=True, world_normal_space="offset", **RB)
check("  Offset encoding = 0.5·n + 0.5", np.abs(L(o, "worldnormal")[mi2] - (0.5 * nw + 0.5)).max() < 0.01)
check("  without high-res connected = low-res N", near(L(bake(world_normal=True, **RB)[0], "worldnormal")[mi],
                                  np.tile([0, 1.0, 0], (mi.sum(), 1)), 1e-5))
check("  these layers are not output by default", not {"worldnormal", "position", "occlusion", "height", "alpha"}
      & set(bake(high=UP, **RB)[0].names))
o, _ = bake(high=UP, position=True, **RB)
Pb = L(o, "P")
check("Position Absolute: hit point = low-res point + 0.05·Y", near(L(o, "position")[mi], (Pb + [0, 0.05, 0])[mi]))
o, _ = bake(low=BLOW, resolution_x=24, resolution_y=24, dilate=0, position=True,
            position_space="relative")
mb = L(o, "mask")[..., 0] > 0.5
lo_, hi_ = (np.asarray(x, np.float64) for x in BLOW.bbox())
check("Relative + Fit: (P - min) / (max - min) (low-res bounding box, per axis)",
      near(L(o, "position")[mb], (L(o, "P")[mb] - lo_) / (hi_ - lo_), 1e-5))
o, _ = bake(low=BLOW, resolution_x=24, resolution_y=24, dilate=0, position=True,
            position_space="relative", bounding_box="uniform")
check("  Uniform: (P - center) / longest side + 0.5 (no stretching)",
      near(L(o, "position")[mb], (L(o, "P")[mb] - (lo_ + hi_) / 2) / (hi_ - lo_).max() + 0.5, 1e-5))

# AO: low-res + a large plane h = 0.1 above (merged into one geometry, Single Mesh shoots at itself).
# a cosine-weighted hemisphere ray hits an infinite plane at distance h / cos(theta) <= R <=> cos(theta) >= h/R, probability 1 - (h/R)^2
SM = _ops.merge(FLAT, plane(0.1, 30.0, n=4))
oa, ra = bake(low=SM, tracing_mode="single_mesh", occlusion=True, occlusion_samples=256,
              occlusion_max_distance=0.2, resolution_x=16, resolution_y=16, dilate=0)
ma = inner(oa, 0.05)
ao = L(oa, "occlusion")[..., 0][ma]
check("AO: large plane 0.1 above, Max Distance 0.2 -> brightness (h/R)^2 = 0.25 (mean +-0.02)",
      abs(ao.mean() - 0.25) < 0.02 and np.abs(ao - 0.25).max() < 0.12, (ao.mean(), ao.min(), ao.max()))
ob, _ = bake(low=SM, tracing_mode="single_mesh", occlusion=True, occlusion_samples=64,
             resolution_x=16, resolution_y=16, dilate=0)
check("  Max Distance 0 = unlimited: almost fully occluded (< 0.05)", L(ob, "occlusion")[..., 0][ma].mean() < 0.05)
oc_, _ = bake(low=SM, tracing_mode="single_mesh", occlusion=True, occlusion_samples=64,
              visibility_culling="back", resolution_x=16, resolution_y=16, dilate=0)
check("  Visibility Culling Back: hitting the back of an upward-facing plane when shooting up does not count -> fully lit",
      near(L(oc_, "occlusion")[..., 0][ma], np.ones(ma.sum())))
check("  Front has no effect (what is hit is a back face)", L(bake(low=SM, tracing_mode="single_mesh", occlusion=True,
                                             occlusion_samples=64, visibility_culling="front",
                                             resolution_x=16, resolution_y=16, dilate=0)[0],
                                        "occlusion")[..., 0][ma].mean() < 0.05)
check("  open space (only the low-res plane) is fully lit", near(L(bake(occlusion=True, **RB)[0], "occlusion")[..., 0][mi],
                                     np.ones(mi.sum())))
check("  Sample Multiplier 0.5: 16 -> 8 rays", json_get(bake(occlusion=True, sample_multiplier=0.5,
                                                        **RB)[1], "occlusion_samples") == 8)
od, _ = bake(low=SM, high=UP, occlusion=True, occlusion_samples=32, resolution_x=16,
             resolution_y=16, dilate=0)
check("  with high-res connected, rays start from the high-res hit point and target the high-res (open above UP -> fully lit, not blocked by the low-res large plane)",
      near(L(od, "occlusion")[..., 0][ma], np.ones(ma.sum())))

o, _ = bake(high=UP, height=True, **RB)
check("Height True Displacement = displacement", near(L(o, "height")[..., 0][mi], np.full(mi.sum(), 0.05)))
o, _ = bake(high=UP, height=True, height_space="custom", inner_distance=-0.1, outer_distance=0.1, **RB)
check("  Custom:(0.05 + 0.1) / 0.2 = 0.75", near(L(o, "height")[..., 0][mi], np.full(mi.sum(), 0.75)))
HALF = FLAT.copy()
HALF.set(POINT, "uv", np.asarray(FLAT.get(POINT, "uv")) * 0.5)   # uv covers only the lower-left quarter
oh, _ = bake(high=UP, height=True, height_space="custom", **{**RB, "low": HALF})
mo = L(oh, "mask")[..., 0] < 0.5
check("  texels outside the uv coverage are 0 (not (0 - inner)/span)", mo.sum() > 500 and near(L(oh, "height")[..., 0][mo],
                                                                             np.zeros(mo.sum())))
check("a bad menu value gives a human-readable error", raises(lambda: bake(face_culling="nope", **RB), "Face Culling")
      and raises(lambda: bake(height_space="x", **RB), "Height Space"))
check("  Inner = Outer raises", raises(lambda: bake(high=UP, height=True, height_space="custom",
                                                inner_distance=0.1, **RB), "Inner"))
check("  without high-res height = 0", near(L(bake(height=True, **RB)[0], "height"), np.zeros((32, 32, 1))))
o, r = bake(high=UP, alpha=True, **RB)
m_ = L(o, "mask")[..., 0]
check("Alpha = low-res uv coverage (= mask)", near(L(o, "alpha")[..., 0], m_))
o, r = bake(high=plane(0.05), alpha=True, alpha_mask_high=True, **RB)
al = L(o, "alpha")[..., 0]
check("  Mask Out High: only texels that hit the high-res are 1 (count = ray_hits)", al.sum() == json_get(r, "ray_hits")
      and al.sum() < m_.sum())
check("panel check_layout is empty", PANEL.check_layout(BK, M[BK].INPUT_TYPES()) == [])
check("new parameters appended at the end", names(BK)[:9] == ["low", "resolution_x", "resolution_y", "uv_attrib", "attribs",
                                         "high_attribs", "max_distance", "both_sides", "dilate"])



# ═══════════════════════════════════════════════════════════════ Integrate Volume
IVN = "PCG_COPIntegrateVolume"
sec("Integrate Volume (new node)")


def boxvol(name="density", fn=lambda X, Y, Z: np.full(X.shape, 2.0), res=(6, 6, 11), hz=0.25):
    """A volume with x, y in [-0.5, 0.5], z in [-hz, hz], value = fn(world coordinates of the voxel)."""
    g = VO.create_volume(res=res, size=(1, 1, 2 * hz), center=(0, 0, 0), name=name)
    rx, ry, rz = res
    Z, Y, X = np.meshgrid(np.linspace(-hz, hz, rz), np.linspace(-0.5, 0.5, ry),
                          np.linspace(-0.5, 0.5, rx), indexing="ij")
    g.set_pdata(0, "voxels", fn(X, Y, Z).astype(np.float32))
    return g


IV2 = boxvol()
IVR = dict(resolution_x=8, resolution_y=8, step_size=0.03)
o = L(run(IVN, geo=IV2, **IVR), "result")[..., 0]
cen = np.zeros((8, 8), bool)
cen[2:6, 2:6] = True                                     # the 4x4 block of pixel centers with |x|,|y| <= 0.375
check("Integral: constant 2 x thickness 0.5 = 1 (step 0.03 does not divide evenly, the last slice uses its actual length)",
      near(o[cen], np.ones(16), 1e-6) and near(o[~cen], np.zeros(48)), o[cen][:3])
o = L(run(IVN, geo=IV2, operation="transmittance", **IVR), "result")[..., 0]
check("Transmittance = exp(-1); not touching the volume = 1", near(o[cen], np.full(16, np.exp(-1)))
      and near(o[~cen], np.ones(48)))
check("Density Min / Max:(2 − 1)/(3 − 1) = 0.5 → 0.25",
      near(L(run(IVN, geo=IV2, density_min=1.0, density_max=3.0, **IVR), "result")[..., 0][cen],
           np.full(16, 0.25)))
check("  Ramp Mode (Max 0.8 -> mapped to 2.5): No Ramp 1.25, Clamped clamps to 1 -> 0.5, Periodic takes the fraction 0.5 -> 0.25",
      near(L(run(IVN, geo=IV2, density_max=0.8, **IVR), "result")[..., 0][cen], np.full(16, 1.25))
      and near(L(run(IVN, geo=IV2, density_max=0.8, ramp_mode="clamped", **IVR), "result")[..., 0][cen],
               np.full(16, 0.5))
      and near(L(run(IVN, geo=IV2, density_max=0.8, ramp_mode="periodic", **IVR), "result")[..., 0][cen],
               np.full(16, 0.25), 1e-5))
check("  Density Scale 3 → 3", near(L(run(IVN, geo=IV2, density_scale=3.0, **IVR), "result")
                                    [..., 0][cen], np.full(16, 3.0)))
LIN = boxvol(fn=lambda X, Y, Z: Z + 1)
o = L(run(IVN, geo=LIN, step_size=0.07, resolution_x=8, resolution_y=8), "result")[..., 0]
check("linear field z + 1: integral = 0.5 (midpoint rule is exact for linear functions, step 0.07)", near(o[cen], np.full(16, 0.5), 1e-6))
oj = L(run(IVN, geo=LIN, step_size=0.07, sample_jitter=1.0, rand_seed=3, resolution_x=8,
           resolution_y=8), "result")[..., 0]
check("  Sample Jitter 1: result changes but stays close to 0.5 (+-0.02)", not near(oj[cen], o[cen], 1e-6)
      and np.abs(oj[cen] - 0.5).max() < 0.02)
os_ = L(run(IVN, geo=IV2, stratification_jitter=1.0, rand_seed=5, **IVR), "result")[..., 0]
check("  Stratification Jitter: the integral of a constant field is still exact (front and back of the slices are clipped to the volume, no segment missed)",
      near(os_[cen], np.ones(16), 1e-6))
QD = boxvol(fn=lambda X, Y, Z: 10 * Z ** 2, res=(6, 6, 41))
oq = L(run(IVN, geo=QD, step_size=0.07, resolution_x=8, resolution_y=8), "result")[..., 0]
osl = L(run(IVN, geo=QD, step_size=0.07, stratification_jitter=1.0, rand_seed=5, resolution_x=8,
            resolution_y=8), "result")[..., 0]
check("  negative control: Stratification Jitter changes slice positions (on a 10z^2 field the result changes slightly, still close to 10·2·0.25^3/3)",
      not near(osl[cen], oq[cen], 1e-9) and np.abs(osl[cen] - 10 * 2 * 0.25 ** 3 / 3).max() < 0.01,
      (osl[cen][:2], oq[cen][:2]))
o = L(run(IVN, geo=LIN, operation="maximum", step_size=0.001, **{k: v for k, v in IVR.items()
                                                                   if k != "step_size"}), "result")[..., 0]
check("Maximum: ~ 1.25 (+-0.001); not touching the volume = -inf", np.abs(o[cen] - 1.25).max() < 1e-3
      and np.all(np.isneginf(o[~cen])))
o = L(run(IVN, geo=LIN, operation="minimum", step_size=0.001, resolution_x=8, resolution_y=8),
      "result")[..., 0]
check("Minimum: ~ 0.75; not touching = +inf", np.abs(o[cen] - 0.75).max() < 1e-3 and np.all(np.isposinf(o[~cen])))
IVD = boxvol(fn=lambda X, Y, Z: np.full(X.shape, 20.0))
o = L(run(IVN, geo=IVD, transmittance_cutoff=0.5, step_size=0.01, resolution_x=8, resolution_y=8),
      "result")[..., 0]
check("Transmittance Cutoff 0.5: stops once the accumulation exceeds ln2 ~ 0.693 (<= 0.693 + one slice of 0.2)",
      np.all((o[cen] >= np.log(2)) & (o[cen] < np.log(2) + 0.2 + 1e-9)), o[cen][:2])
check("  negative control: Cutoff -1 does not stop (= 10)", near(L(run(IVN, geo=IVD, step_size=0.01, resolution_x=8,
                                                resolution_y=8), "result")[..., 0][cen], np.full(16, 10.0)))
check("Max Step Count 10, step 0.01: only covers 0.1 -> 2 x 0.1 = 0.2",
      near(L(run(IVN, geo=IV2, step_size=0.01, max_steps=10, resolution_x=8, resolution_y=8),
             "result")[..., 0][cen], np.full(16, 0.2)))
ys = (np.arange(4) + 0.5) / 4 - 0.5
Yg = np.tile(ys[:, None], (1, 4))
rays = img_with(4, 4, o=np.stack([np.full((4, 4), -5.0), Yg * 0.8, np.zeros((4, 4))], -1),
                d=np.tile([2.0, 0, 0], (4, 4, 1)))
o = run(IVN, geo=IV2, layers=rays, origin_layer="o", direction_layer="d", step_size=0.03)
check("View Origin / Direction layers: crossing a volume 1 wide along +X -> 2; direction need not be unit length; the layers' layers remain",
      near(L(o, "result")[..., 0], np.full((4, 4), 2.0)) and "o" in o.names)
rays2 = img_with(4, 4, o=np.stack([np.zeros((4, 4)), np.zeros((4, 4)), np.full((4, 4), 0.1)], -1),
                 d=np.tile([0, 0, 1.0], (4, 4, 1)))
check("  rays start at the origin (t >= 0): origin inside the volume at z = 0.1 -> only 0.15 integrated -> 0.3",
      near(L(run(IVN, geo=IV2, layers=rays2, origin_layer="o", direction_layer="d", step_size=0.03),
             "result")[..., 0], np.full((4, 4), 0.3)))
dl = img_with(8, 8, mn=np.zeros((8, 8)), mx=np.full((8, 8), 0.1))
o = L(run(IVN, geo=IV2, layers=dl, mindepth_layer="mn", step_size=0.03), "result")[..., 0]
check("Min Depth layer: with the default orthographic t = z, z >= 0 leaves only half -> 0.5", near(o[cen], np.full(16, 0.5)))
o = L(run(IVN, geo=IV2, layers=dl, mindepth_layer="mn", maxdepth_layer="mx", step_size=0.03),
      "result")[..., 0]
check("  Max Depth 0.1 → 2 × 0.1 = 0.2", near(o[cen], np.full(16, 0.2)))
VEC = _ops.merge(boxvol("vel.x"), boxvol("vel.y", fn=lambda X, Y, Z: np.full(X.shape, 4.0)))
o = L(run(IVN, geo=VEC, density="vel.*", **IVR), "result")
check("multiple volumes (vel.*) = multiple channels, each accumulated separately (1, 2)", o.shape[-1] == 2 and near(o[cen], np.tile([1, 2.0], (16, 1))))
check("empty Volume = the first volume (1 channel)", near(L(run(IVN, geo=VEC, **IVR), "result"),
                                          L(run(IVN, geo=VEC, density="0", **IVR), "result"))
      and L(run(IVN, geo=VEC, **IVR), "result").shape[-1] == 1)
VEC2 = _ops.merge(boxvol("vel.x"), boxvol("vel.y", fn=lambda X, Y, Z: np.full(X.shape, 4.0), hz=0.1))
o = L(run(IVN, geo=VEC2, density="vel.*", **IVR), "result")
check("  two volumes with different extents: the view ray is clipped to the union, each channel accumulates only inside its own volume (1, 4 x 0.2 = 0.8; a slice crossing the boundary counts "
      "wholly on the side its midpoint falls on, error <= two slices x 4 x 0.03)",
      near(o[cen][:, 0], np.ones(16), 1e-6) and np.abs(o[cen][:, 1] - 0.8).max() <= 0.24 + 1e-9,
      o[cen][0])
o = L(run(IVN, geo=VEC, density="vel.*", transmittance_cutoff=0.5, step_size=0.01, resolution_x=8,
          resolution_y=8), "result")
check("  multi-channel Cutoff: stops only when every channel has dropped below 0.5 (the slow channel is also >= ln2)",
      np.all(o[cen][:, 0] >= np.log(2)) and np.all(o[cen][:, 1] < 1.9))
check("  custom rays + Min Depth -10: still start at the origin (t >= 0 is not relaxed)",
      near(L(run(IVN, geo=IV2, layers=img_with(4, 4, o=rays2.need("o"), d=rays2.need("d"),
                                                 mn=np.full((4, 4), -10.0)),
                 origin_layer="o", direction_layer="d", mindepth_layer="mn", step_size=0.03),
             "result")[..., 0], np.full((4, 4), 0.3)))
check("non-square image: image coordinates -1 to 1 on the long side (16x8: the middle 8 columns in x, y spans only +-0.5 -> all 8 rows)",
      (L(run(IVN, geo=IV2, resolution_x=16, resolution_y=8, step_size=0.03), "result")[..., 0] > 0.5)
      .sum() == 8 * 8)
check("errors: no volume / Step <= 0 / Min = Max / layer names without layers connected",
      raises(lambda: run(IVN, geo=box), "No volume prims") and raises(lambda: run(IVN, geo=IV2, step_size=0.0), "Step")
      and raises(lambda: run(IVN, geo=IV2, density_min=1.0), "Min")
      and raises(lambda: run(IVN, geo=IV2, origin_layer="o"), "layers")
      and raises(lambda: run(IVN, geo=IV2, mindepth_layer="o"), "layers"))
check("panel check_layout is empty", PANEL.check_layout(IVN, M[IVN].INPUT_TYPES()) == [])



# ═══════════════════════════════════════════════════════════════ Configure Stamps
CS = "PCG_COPConfigureStamps"
sec("Configure Stamps (new node)")
NP = 400
_rng = np.random.default_rng(1)
PTS = cloud(np.c_[_rng.uniform(-0.45, 0.45, NP), np.zeros(NP), _rng.uniform(-0.45, 0.45, NP)])
g = run(CS, points=PTS)
check("defaults: spritescale (1,1), spriterot 0, Cd white, blend 1, stamp 0, P unchanged",
      near(A(g, "spritescale"), np.ones((NP, 2))) and near(A(g, "spriterot"), np.zeros(NP))
      and near(A(g, "Cd"), np.ones((NP, 3))) and near(A(g, "blend"), np.ones(NP))
      and A(g, "stamp").tolist() == [0] * NP and near(P_(g), P_(PTS)))
g = run(CS, points=PTS, scale=2.0, stretch="1 3")
check("Scale × Stretch → spritescale = (2, 6)", near(A(g, "spritescale"), np.tile([2, 6.0], (NP, 1))))
g = run(CS, points=PTS, scale=2.0, scale_mode="percent_variance", scale_variance=0.5)
ss = A(g, "spritescale")[:, 0]
check("Percent Variance 0.5: 2 x (1 +- 0.5) in [1, 3), spread out, mean ~ 2",
      ss.min() >= 1 - 1e-6 and ss.max() < 3 and ss.max() - ss.min() > 1.6 and abs(ss.mean() - 2) < 0.1)
check("  negative control: under Uniform Variance has no effect",
      near(A(run(CS, points=PTS, scale=2.0, scale_variance=0.5), "spritescale")[:, 0], np.full(NP, 2.0)))
g = run(CS, points=PTS, scale=2.0, scale_mode="min_max", scale_min=0.5, scale_max=1.5)
ss = A(g, "spritescale")[:, 0]
check("Scale Min/Max 0.5~1.5 × 2 ∈ [1, 3)", ss.min() >= 1 - 1e-6 and ss.max() < 3 and ss.max() - ss.min() > 1.6)
g = run(CS, points=PTS, stretch_mode="variance", stretch_variance=0.5)
sx, sy = A(g, "spritescale")[:, 0], A(g, "spritescale")[:, 1]
check("Stretch Variance: each axis 1 +- 0.5, independent", sx.min() >= 0.5 - 1e-6 and sx.max() < 1.5
      and abs(np.corrcoef(sx, sy)[0, 1]) < 0.2)
g = run(CS, points=PTS, stretch="2 4", stretch_mode="min_max", stretch_min=1.0, stretch_max=2.0)
sx, sy = A(g, "spritescale")[:, 0], A(g, "spritescale")[:, 1]
check("Stretch Min/Max: each axis x [1, 2)", sx.min() >= 2 - 1e-6 and sx.max() < 4 and sy.min() >= 4 - 1e-6
      and sy.max() < 8 and not near(sx * 2, sy))
g = run(CS, points=PTS, angle=30.0, angle_mode="variance", angle_variance=10.0)
an = A(g, "spriterot")
check("Angle Variance 10:30 ± 10", an.min() >= 20 - 1e-4 and an.max() < 40 and an.max() - an.min() > 15)
g = run(CS, points=PTS, angle=90.0, angle_mode="min_max", angle_min=0.0, angle_max=2.0)
an = A(g, "spriterot")
check("Angle Min/Max: 90 x [0, 2) (docs: multiplied onto Angle)", an.min() >= -1e-4 and an.max() < 180
      and an.max() - an.min() > 150)
g = run(CS, points=PTS, angle=90.0, angle_mode="min_max", angle_min=0.0, angle_max=2.0, round_to=45.0)
check("  Round To rounds to nearest (30 -> 45, 20 -> 0)",
      near(A(run(CS, points=PTS, angle=30.0, round_to=45.0), "spriterot"), np.full(NP, 45.0))
      and near(A(run(CS, points=PTS, angle=20.0, round_to=45.0), "spriterot"), np.zeros(NP)))
check("  Round To 45: all multiples of 45", np.allclose(np.mod(A(g, "spriterot"), 45), 0, atol=1e-3)
      and len(set(np.round(A(g, "spriterot")).tolist())) >= 4)
g = run(CS, points=PTS, color="0.8 0.2 0.2", color_mode="variance", hue_variance=0.1, color_seed=3)
from comfyui_pcg.geo.cop.pixel import rgb_to_hsv as _r2h     # noqa: E402
hsv = _r2h(A(g, "Cd").astype(np.float64))
h0 = _r2h(np.array([0.8, 0.2, 0.2]))
dh = (hsv[:, 0] - h0[0] + 0.5) % 1 - 0.5
check("Color Variance (Hue 0.1): only hue varies within +-0.1, s / v unchanged",
      np.abs(dh).max() <= 0.1 + 1e-5 and np.abs(dh).max() > 0.08 and near(hsv[:, 1:], np.tile(h0[1:], (NP, 1)), 1e-5))
g = run(CS, points=PTS, color="0.8 0.2 0.2", color_mode="variance", saturation_variance=0.2, color_seed=3)
hs = _r2h(A(g, "Cd").astype(np.float64))
check("  Saturation 0.2: s = 0.75 +- 0.2, hue / value unchanged", np.abs(hs[:, 1] - 0.75).max() <= 0.2 + 1e-5
      and np.abs(hs[:, 1] - 0.75).max() > 0.15 and near(hs[:, [0, 2]], np.tile(h0[[0, 2]], (NP, 1)), 1e-5))
g = run(CS, points=PTS, color="0.9 0.9 0.9", color_mode="variance", value_variance=0.3, color_seed=3)
check("  Value above 1 clamped to 1", A(g, "Cd")[:, 0].max() <= 1 + 1e-6 and (A(g, "Cd")[:, 0] > 1 - 1e-6).sum() > 20)
g = run(CS, points=PTS, color="0.5 0.5 0.5", color_mode="variance", value_variance=0.2, color_seed=3)
v_ = A(g, "Cd")[:, 0]
check("  Value 0.2: grey 0.5 +- 0.2, three channels equal", v_.min() >= 0.3 - 1e-5 and v_.max() <= 0.7 + 1e-5
      and near(A(g, "Cd")[:, 0], A(g, "Cd")[:, 2], 1e-6))
g = run(CS, points=PTS, alpha=0.9, alpha_mode="variance", alpha_variance=0.3)
al = A(g, "blend")
check("Alpha Variance: 0.9 +- 0.3, clamped to [0, 1] (a batch exactly 1)", al.min() >= 0.6 - 1e-5 and al.max() <= 1
      and (al == 1).sum() > 20)
check("  Color Seed also drives alpha: a different seed differs", not near(al, A(run(CS, points=PTS, alpha=0.9, alpha_mode="variance",
                                                             alpha_variance=0.3, color_seed=4), "blend")))
g = run(CS, points=PTS, stamp_count=3)
check("Stamp Cycle: point number mod 3", A(g, "stamp").tolist() == [k % 3 for k in range(NP)])
g = run(CS, points=PTS, stamp_count=4, select_mode="random", select_seed=2)
st_ = A(g, "stamp")
check("Stamp Random: 0-3 all occur, roughly uniform", set(st_.tolist()) == {0, 1, 2, 3}
      and min(np.bincount(st_)) > 60)
check("  a different Select Seed differs", A(run(CS, points=PTS, stamp_count=4, select_mode="random", select_seed=3),
                                 "stamp").tolist() != st_.tolist())
# layer input: xz plane, World Size 1, u = x + 0.5, v = -z + 0.5
_u = (np.arange(64) + 0.5) / 64
UG, VG = np.meshgrid(_u, _u)
LAY = img_with(64, 64, sel=UG, ang=VG * 0 + 0.25, sc=1 + UG, dirv=np.stack([np.zeros_like(UG), np.ones_like(UG)], -1),
               col=np.stack([UG, VG, np.zeros_like(UG)], -1), al=VG, jit=np.stack([np.full_like(UG, 0.1),
                                                                                    np.full_like(UG, 0.2)], -1),
               srt=np.full_like(UG, 0.3))
Pp = P_(PTS)
uu, vv = Pp[:, 0] + 0.5, -Pp[:, 2] + 0.5
g = run(CS, points=PTS, layers=LAY, stamp_count=5, select_mode="layer_select", select_layer="sel")
check("Layer Select:stamp = round(u × 4)", A(g, "stamp").tolist() == np.clip(np.rint(uu * 4), 0, 4).astype(int).tolist())
g = run(CS, points=PTS, layers=LAY, angle=10.0, angle_layer="ang", angle_mask=0.5)
check("Angle Layer 0.25 × 360 × Mask 0.5 + 10 = 55", near(A(g, "spriterot"), np.full(NP, 55.0), 1e-3))
g = run(CS, points=PTS, layers=LAY, direction_layer="dirv")
check("Direction Layer (0, 1) → +90°", near(A(g, "spriterot"), np.full(NP, 90.0), 1e-3))
g = run(CS, points=PTS, layers=LAY, scale=2.0, scale_layer="sc", scale_mask=1.0)
check("Scale Layer: 2 x (1 + u) (bilinear sampling, exact for linear fields)", near(A(g, "spritescale")[:, 0], 2 * (1 + uu), 1e-4))
g = run(CS, points=PTS, layers=LAY, scale=2.0, scale_layer="sc", scale_mask=0.5)
check("  Mask 0.5:2 × lerp(1, 1 + u, 0.5)", near(A(g, "spritescale")[:, 0], 2 * (1 + 0.5 * uu), 1e-4))
g = run(CS, points=PTS, layers=LAY, stretch_layer="sc")
check("Stretch Layer (1 channel shared by both axes)", near(A(g, "spritescale"), np.stack([1 + uu, 1 + uu], -1), 1e-4))
g = run(CS, points=PTS, layers=LAY, color_layer="col")
check("Color Layer multiplies Color", near(A(g, "Cd"), np.stack([uu, vv, np.zeros(NP)], -1), 1e-4))
g = run(CS, points=PTS, layers=LAY, alpha=0.5, alpha_layer="al")
check("Alpha Layer multiplies Alpha", near(A(g, "blend"), 0.5 * vv, 1e-4))
g = run(CS, points=PTS, layers=LAY, jitter_layer="jit", jitter_mask=2.0)
check("Jitter Layer (0.1, 0.2) x 2: xz plane x += 0.2, z -= 0.4 (b = -z)",
      near(P_(g) - Pp, np.tile([0.2, 0, -0.4], (NP, 1)), 1e-5))
g = run(CS, points=PTS, jitter=0.1, jitter_scale="1 0")
d = P_(g) - Pp
check("Jitter 0.1, Scale (1, 0): only +-0.1 in x, z unchanged", np.abs(d[:, 0]).max() <= 0.1 + 1e-6
      and np.abs(d[:, 0]).max() > 0.09 and near(d[:, 1:], np.zeros((NP, 2))))
g = run(CS, points=PTS, layers=LAY, use_sort_layer=True, sort_layer="srt")
check("Sort Layer: the out-of-plane axis (xz -> Y) + 0.3", near(P_(g) - Pp, np.tile([0, 0.3, 0], (NP, 1)), 1e-6))
check("  negative control: Use Sort Layer off does not move", near(P_(run(CS, points=PTS, layers=LAY, sort_layer="srt")), Pp))
g = run(CS, points=PTS, layers=LAY, plane="xy", angle_layer="al", angle_mask=1.0)
check("Plane xy takes uv from (x, y) (points have y = 0 -> v = 0.5 -> 0.5 x 360 = 180; under xz it varies with z)",
      near(A(g, "spriterot"), np.full(NP, 180.0), 1e-2)
      and near(A(run(CS, points=PTS, layers=LAY, angle_layer="al"), "spriterot"), vv * 360, 1e-2))
check("layer name given without layers connected / Layer Select without a layer -> raises",
      raises(lambda: run(CS, points=PTS, scale_layer="sc"), "layers")
      and raises(lambda: run(CS, points=PTS, select_mode="layer_select"), "Select Layer"))
check("panel check_layout is empty", PANEL.check_layout(CS, M[CS].INPUT_TYPES()) == [])


print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
