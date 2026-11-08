"""
Structured input (JSON -> geometry / geometry -> JSON).

Criteria ranked by "can it be proven":

━━ 1. Round-trip identity
After geometry -> `dumps` -> `from_json`, every attribute must be **bit-identical** (float32
attributes go through a float32 round trip; with enough precision a decimal round trip is lossless). What most often
goes wrong in a round trip is **silent degradation**: vectors split into scalars, strings treated as numbers, missing keys zero-filled. None of these
raise errors; you only find out downstream.

━━ 2. Coordinates have a closed-form solution
Normalized coordinates to world coordinates is a linear map; compared point by point against the analytic formula, error is held at 1e-15.
The two places most prone to silent errors each have a criterion + negative control: **plane axis order** (in xz mode u lands on x,
v lands on z) and **flip_v** (image space y points down; without flipping the whole layout is upside down, and a symmetric
layout would not show it).

━━ 3. Tolerant parsing: each step of the ladder tested separately, and **what was fixed must be said**
Fences, leading prose, trailing commas, extracting a JSON segment. Silent fixes are the hardest kind to track down: it runs today, tomorrow
the model changes its format and you think your own graph broke. So each step checks "parsed correctly" **and** "info
states which step was used".

━━ 4. What should error must error
Arrays of uneven length (zero-padding pushes the error further along), no list of records found, wrong bbox count,
points with fewer than two points. Each one must carry **locatable** information (which record, which key, how many).
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

from comfyui_pcg.geo.core import (Geometry, POINT, PRIM,      # noqa: E402
                                  DETAIL)
from comfyui_pcg.geo import structured as ST, ops as OPS      # noqa: E402
from comfyui_pcg import nodes as N                            # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag, kind=Exception):
    try:
        fn()
        check(name, False, "no error raised")
    except kind as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:110]}")


def sec(t):
    print("\n" + "═" * 28 + " " + t)


def unwrap(res):
    return tuple(res.get("result", ())) if isinstance(res, dict) else res


def P_of(g):
    return np.asarray(g.get(POINT, "P"))


# ══════════════════════════════════════════════════ 1. Round-trip identity
sec("Round trip (geometry -> JSON -> geometry)")
rng = np.random.default_rng(3)
n = 24
src = Geometry(n)
src.set(POINT, "P", rng.normal(0, 3, (n, 3)).astype(np.float32), owned=True)
src.set(POINT, "Cd", rng.random((n, 3)).astype(np.float32), owned=True)
src.set(POINT, "pscale", rng.random((n, 1)).astype(np.float32), owned=True)
src.set_string(POINT, "name",
               [["tree", "rock", "bush"][i % 3] for i in range(n)])

txt = ST.dumps(src, POINT, precision=9)
back, info = ST.from_json(txt, mode="points", normalized=False)
check("same point count after round trip", back.npoints == n, back.npoints)
same = []
for a in ("P", "Cd", "pscale", "name"):
    x, y = np.asarray(src.get(POINT, a)), np.asarray(back.get(POINT, a))
    same.append((a, x.shape == y.shape and np.array_equal(x, y)))
check("all attributes **bit-identical** (vectors not split, strings not treated as numbers)",
      all(v for _, v in same), same)
check("  dimensions unchanged too (3 components stay 3 components)",
      back.get(POINT, "Cd").shape[1] == 3
      and back.get(POINT, "pscale").shape[1] == 1)
check("  info says the parse was clean (a round trip should of course give clean JSON)",
      info["parse"] == "clean", info["parse"])

# Negative control: with too little precision it is no longer bit-identical -- shows this criterion really looks at the values
lossy = ST.dumps(src, POINT, precision=2)
back2, _ = ST.from_json(lossy, mode="points", normalized=False)
check("  [negative control] precision=2 round trip is **not** bit-identical (the criterion really looks at values)",
      not np.array_equal(P_of(back2), P_of(src)),
      f"max diff {np.abs(P_of(back2) - P_of(src)).max():.3g}")

check("limit truncation states truncated and the total",
      json.loads(ST.dumps(src, POINT, limit=5))["total"] == n
      and json.loads(ST.dumps(src, POINT, limit=5))["truncated"] is True
      and len(json.loads(ST.dumps(src, POINT, limit=5))["items"]) == 5)
check("  truncated output can be read back too (list of records is found)",
      ST.from_json(ST.dumps(src, POINT, limit=5), normalized=False)[0]
      .npoints == 5)
check("attribs parameter can pick attributes",
      sorted(json.loads(ST.dumps(src, POINT, attribs="P name"))[0].keys())
      == ["P", "name"])
err("picking a nonexistent attribute lists the existing ones",
    lambda: ST.dumps(src, POINT, attribs="nope"), "Existing:")
check("prim / detail can be exported too",
      len(json.loads(ST.dumps(
          ST.from_json('[{"bbox":[0,0,1,1],"name":"a"}]', mode="boxes")[0],
          PRIM))) == 1)


# ══════════════════════════════════════════════════ 2. Coordinates
sec("Coordinates (closed form)")
SZ, CEN = (10.0, 6.0), (1.0, 2.0, 3.0)
recs = '[{"pos":[0,0]},{"pos":[1,1]},{"pos":[0.5,0.5]},{"pos":[0.25,0.75]}]'
g, _ = ST.from_json(recs, plane="xz", size=SZ, center=CEN)
uv = np.array([[0, 0], [1, 1], [0.5, 0.5], [0.25, 0.75]], np.float64)
want = np.stack([(uv[:, 0] - 0.5) * SZ[0] + CEN[0],
                 np.full(4, CEN[1]),
                 (uv[:, 1] - 0.5) * SZ[1] + CEN[2]], 1)
check("xz mode: u lands on x, v on z, matches the analytic formula point by point",
      np.abs(P_of(g).astype(np.float64) - want).max() < 1e-6,
      f"max diff {np.abs(P_of(g).astype(np.float64) - want).max():.2e}")
check("  [negative control] with axis order swapped (u on z) the diff is O(size)",
      np.abs(P_of(g).astype(np.float64) - want[:, [2, 1, 0]]).max() > 1.0)
gxy, _ = ST.from_json(recs, plane="xy", size=SZ, center=CEN)
check("xy mode: v lands on y, third axis takes center",
      np.allclose(P_of(gxy)[:, 2], CEN[2])
      and abs(float(P_of(gxy)[1, 1]) - ((1 - 0.5) * SZ[1] + CEN[1])) < 1e-6)
gyz, _ = ST.from_json(recs, plane="yz", size=SZ, center=CEN)
check("yz mode: u lands on y, v on z", np.allclose(P_of(gyz)[:, 0], CEN[0]))

gf, _ = ST.from_json(recs, plane="xz", size=SZ, center=CEN, flip_v=True)
check("**flip_v**: image space y points down; after flipping v=0 lands at the other end",
      abs(float(P_of(gf)[0, 2]) - ((1 - 0 - 0.5) * SZ[1] + CEN[2])) < 1e-6)
check("  flipping twice equals not flipping (symmetry)",
      np.allclose(P_of(gf)[:, 2],
                  2 * CEN[2] - P_of(g)[:, 2].astype(np.float64), atol=1e-6))
check("  [negative control] flipped and unflipped really differ (not decorative)",
      not np.allclose(P_of(gf), P_of(g)))

gr, _ = ST.from_json('[{"P":[1,2,3]},{"P":[4,5,6]}]', normalized=False)
check("normalized=False uses world coordinates directly",
      np.array_equal(P_of(gr), np.array([[1, 2, 3], [4, 5, 6]], np.float32)))
g2d, _ = ST.from_json('[{"P":[1,2]}]', normalized=False, plane="xz")
check("  2 components + not normalized: third axis filled in per plane",
      np.allclose(P_of(g2d)[0], [1, 0, 2]))
gnp, _ = ST.from_json('[{"name":"a"},{"name":"b"}]', center=(5, 6, 7))
check("records without coordinates land on center (not the origin)",
      np.allclose(P_of(gnp), [[5, 6, 7], [5, 6, 7]]))
check("bare coordinate arrays are recognized too ([[x,y,z], ...])",
      ST.from_json('[[0,1,2],[3,4,5]]', normalized=False)[0].npoints == 2)


# ══════════════════════════════════════════════════ 3. Tolerant parsing
sec("Tolerant parsing (fixes must be stated)")
CLEAN = '[{"name":"a","pos":[0.1,0.2]},{"name":"b","pos":[0.3,0.4]}]'
base = P_of(ST.from_json(CLEAN)[0])

cases = [
    ("clean", CLEAN, "clean"),
    ("```json fences", "```json\n" + CLEAN + "\n```", "fences"),
    ("``` fences without language", "```\n" + CLEAN + "\n```", "fences"),
    ("leading prose", "Here is the layout you asked for:\n" + CLEAN, "extracted"),
    ("prose before and after", "Sure!\n" + CLEAN + "\nHope this helps.", "extracted"),
    ("trailing comma", CLEAN[:-1] + ",]", "trailing commas"),
    ("fences + prose + trailing comma",
     "Here:\n```json\n" + CLEAN[:-1] + ",]\n```\n done", "trailing commas"),
]
for label, text, note in cases:
    g_c, i_c = ST.from_json(text)
    check(f"{label}: parses to the same geometry", np.array_equal(P_of(g_c), base))
    check(f"  info states it ({note})", note in i_c["parse"],
          i_c["parse"])

check("square brackets inside strings don't end the extraction early",
      ST.from_json('note: [{"name":"a ] b","pos":[0,0]}]')[0]
      .get(POINT, "name")[0][0] == "a ] b")
check("commas inside strings aren't treated as trailing commas",
      ST.from_json('[{"name":"a, b","pos":[0,0]}]')[0]
      .get(POINT, "name")[0][0] == "a, b")
check("escaped quotes don't break the scan either",
      ST.from_json(r'[{"name":"a \" ] b","pos":[0,0]}]')[0].npoints == 1)
err("input that really isn't JSON errors, with line/column and that line",
    lambda: ST.from_json("this is just prose, no json at all"), "not valid JSON")
err("  empty input", lambda: ST.from_json("   "), "input is empty")
err("  unbalanced brackets", lambda: ST.from_json('[{"a":1}'), "not valid JSON")

# Top-level shape
check("top-level object: list of records found automatically",
      ST.from_json('{"objects": ' + CLEAN + '}')[0].npoints == 2)
check("  top-level scalars become detail attributes",
      float(np.asarray(ST.from_json(
          '{"seed": 7, "objects": ' + CLEAN + '}')[0].get(DETAIL, "seed"))[0][0])
      == 7.0)
check("  string details carried too",
      str(np.asarray(ST.from_json(
          '{"style": "gothic", "objects": ' + CLEAN + '}')[0]
          .get(DETAIL, "style"))[0][0]) == "gothic")
check("path can be set manually (when there are several lists)",
      ST.from_json('{"a": [{"pos":[0,0]}], "b": ' + CLEAN + '}',
                   path="b")[0].npoints == 2)
check("  nested path works too",
      ST.from_json('{"data": {"items": ' + CLEAN + '}}',
                   path="data.items")[0].npoints == 2)
check("a single object is treated as one record (when the model generates only one thing)",
      ST.from_json('{"name":"solo","pos":[0.5,0.5]}')[0].npoints == 1)
err("no list of records found: lists the top-level keys",
    lambda: ST.from_json('{"a": {"b": 1}}'), "Top-level keys")
err("wrong path also lists the keys",
    lambda: ST.from_json('{"a": []}', path="zzz"), "Top-level keys")
err("top level is a number: says so clearly", lambda: ST.from_json("42"), "top level must be")
err("a non-object mixed into the records: says which one",
    lambda: ST.from_json('[{"a":1}, "oops"]'), "Record 1")


# ══════════════════════════════════════════════════ 4. Keys -> attributes
sec("Key name alignment / type inference")
for keys in (("pos", "P"), ("position", "P"), ("translate", "P"),
             ("location", "P"), ("xyz", "P")):
    check(f"{keys[0]} -> P",
          ST.canon(keys[0]) == keys[1])
check("label / type / tag / category all -> name",
      all(ST.canon(k) == "name"
          for k in ("label", "type", "tag", "category", "Name", "LABEL")))
check("color / colour / rgb -> Cd", ST.canon("colour") == "Cd")
check("unrecognized keys kept as is",
      ST.canon("my_weird_key") == "my_weird_key")
check("  invalid characters replaced with underscores (attribute names can't contain spaces / dashes)",
      ST.canon("my key-2") == "my_key_2")

g_t, i_t = ST.from_json(
    '[{"pos":[0,0],"w":1.5,"v3":[1,2,3],"lbl":"x","flag":true},'
    ' {"pos":[1,1],"w":2.5,"v3":[4,5,6],"lbl":"y","flag":false}]',
    group_by="")
check("number -> 1-component float attribute", g_t.get(POINT, "w").shape[1] == 1)
check("fixed-length array -> vector attribute", g_t.get(POINT, "v3").shape[1] == 3)
check("string -> string attribute", g_t.get(POINT, "lbl").dtype.kind == "U")
check("bool -> 0/1",
      np.array_equal(np.asarray(g_t.get(POINT, "flag")).ravel(), [1.0, 0.0]))
check("hex color -> Cd (models love writing this)",
      np.allclose(np.asarray(ST.from_json(
          '[{"pos":[0,0],"color":"#ff8000"}]')[0].get(POINT, "Cd"))[0],
          [1.0, 128 / 255, 0.0], atol=1e-6))
check("  three-digit shorthand recognized too (#f80)",
      np.allclose(np.asarray(ST.from_json(
          '[{"pos":[0,0],"color":"#f80"}]')[0].get(POINT, "Cd"))[0],
          [1.0, 136 / 255, 0.0], atol=1e-6))
check("  color_hex=False treats it as a plain string",
      ST.from_json('[{"pos":[0,0],"color":"#ff8000"}]',
                   color_hex=False)[0].get(POINT, "Cd").dtype.kind == "U")
check("nested objects flattened into a.b",
      ST.from_json('[{"pos":[0,0],"meta":{"score":3}}]')[0]
      .has(POINT, "meta.score"))
g_m, i_m = ST.from_json('[{"pos":[0,0],"w":1},{"pos":[1,1]}]')
check("missing keys zero-filled, and **how many were filled is reported**",
      float(np.asarray(g_m.get(POINT, "w"))[1][0]) == 0.0
      and i_m["filled"] == 1, i_m["filled"])
check("  null treated as a missing key",
      ST.from_json('[{"pos":[0,0],"w":1},{"pos":[1,1],"w":null}]')[1]["filled"]
      == 1)
err("**arrays of uneven length are an error** (zero-padding pushes the error further along)",
    lambda: ST.from_json('[{"pos":[0,0],"v":[1,2]},{"pos":[1,1],"v":[1,2,3]}]'),
    "arrays of different lengths")
check("  but a 2-component P is valid (normalized coordinates)",
      ST.from_json('[{"P":[0,0]},{"P":[1,1]}]')[0].npoints == 2)


# ══════════════════════════════════════════════════ 5. Three forms
sec("points / boxes / curves")
ROOMS = ('[{"label":"kitchen","bbox":[0,0,0.5,0.4]},'
         ' {"label":"hall","bbox":[0.5,0,1,1]}]')
gb, ib = ST.from_json(ROOMS, mode="boxes", size=(10, 10), group_by="label")
check("boxes: one quad per record",
      gb.nprims == 2 and np.array_equal(gb.prim_sizes(), [4, 4]))
check("  attributes land on **prim** (each box carries its own label)",
      list(np.asarray(gb.get(PRIM, "name")).ravel()) == ["kitchen", "hall"])
check("  box corners match the bbox (closed form)",
      np.allclose(sorted(P_of(gb)[:4, 0]), [-5, -5, 0, 0])
      and np.allclose(sorted(P_of(gb)[:4, 2]), [-5, -5, -1, -1]))
check("  group_by creates one group per label",
      gb.get_group(PRIM, "kitchen") is not None
      and gb.get_group(PRIM, "hall") is not None and ib["groups"] == 2)
check("  height lifts the whole thing up",
      np.allclose(P_of(ST.from_json(ROOMS, mode="boxes", height=2.0)[0])[:, 1],
                  2.0))
g6, _ = ST.from_json('[{"bbox":[0,0,0,1,1,1],"name":"cube"}]', mode="boxes",
                     normalized=False)
check("  6 numbers -> a real box (6 faces)", g6.nprims == 6, g6.nprims)
check("  min/max written separately recognized too",
      ST.from_json('[{"min":[0,0],"max":[1,1]}]', mode="boxes")[0].nprims == 1)
check("  nested [[x0,y0],[x1,y1]] form recognized too",
      ST.from_json('[{"bbox":[[0,0],[1,1]]}]', mode="boxes")[0].nprims == 1)
check("  box written reversed (x1<x0) still gives a positive box",
      ST.from_json('[{"bbox":[1,1,0,0]}]', mode="boxes",
                   normalized=False)[0].nprims == 1)
err("boxes mode with no record having a bbox: says which keys are needed",
    lambda: ST.from_json('[{"pos":[0,0]}]', mode="boxes"), "bbox")
err("wrong bbox count: says how many are needed",
    lambda: ST.from_json('[{"bbox":[0,0,1]}]', mode="boxes"), "needs 4 numbers")

PATHS = ('[{"points":[[0,0],[0.5,0.5],[1,0]],"name":"road"},'
         ' {"points":[[0,1],[1,1]],"name":"wall","closed":true}]')
gc, ic = ST.from_json(PATHS, mode="curves", size=(10, 10))
check("curves: one polyline per record",
      gc.nprims == 2 and np.array_equal(gc.prim_sizes(), [3, 2]))
check("  closed is recognized",
      list(gc.prim_closed) == [False, True])
check("  attributes land on prim",
      list(np.asarray(gc.get(PRIM, "name")).ravel()) == ["road", "wall"])
check("  3D coordinates work too",
      ST.from_json('[{"points":[[0,0,0],[1,2,3]]}]', mode="curves",
                   normalized=False)[0].npoints == 2)
err("curves mode without points: says which keys are needed",
    lambda: ST.from_json('[{"pos":[0,0]}]', mode="curves"), "points")
err("inconsistent points component counts: says which record",
    lambda: ST.from_json('[{"points":[[0,0],[1,2,3]]}]', mode="curves"),
    "record 0")
err("wrong mode", lambda: ST.from_json(CLEAN, mode="bogus"), "mode must be one of")
err("wrong plane", lambda: ST.from_json(CLEAN, plane="bogus"), "plane must be one of")


# ══════════════════════════════════════════════════ 6. Groups
sec("group_by (classes assigned by the AI -> usable groups)")
LAY = ('[{"name":"tree","pos":[0.1,0.1]},{"name":"rock","pos":[0.5,0.5]},'
       ' {"name":"tree","pos":[0.9,0.9]}]')
gg, ig = ST.from_json(LAY, group_by="name")
check("one group per value", ig["groups"] == 2)
check("  groups contain the right elements",
      np.array_equal(gg.get_group(POINT, "tree"), [True, False, True])
      and np.array_equal(gg.get_group(POINT, "rock"), [False, True, False]))
check("  invalid characters in group names replaced with underscores",
      ST.from_json('[{"name":"a b/c","pos":[0,0]}]', group_by="name")[0]
      .get_group(POINT, "a_b_c") is not None)
check("  group_by uses the aligned name too (label also reaches name)",
      ST.from_json('[{"label":"x","pos":[0,0]}]', group_by="label")[1]
      ["groups"] == 1)
check("  group_by pointing at a nonexistent attribute: no error, no groups",
      ST.from_json(LAY, group_by="zzz")[1]["groups"] == 0)
check("  group_by empty: no groups", ST.from_json(LAY, group_by="")[1]["groups"] == 0)
# delete_points' second argument is a **keep** mask (not a delete mask) -- the first version passed
# the inverted one, which left 1 point while the criterion said 2
check("groups can be fed straight into Blast (really usable downstream)",
      OPS.delete_points(gg, np.asarray(gg.get_group(POINT, "tree"))).npoints
      == 2)


# ══════════════════════════════════════════════════ 7. Nodes
sec("Nodes")
fj = N.PCG_FromJSON()
out = unwrap(fj.run(LAY, "points", "auto", "xz", 10.0, 10.0, 0.0, 0.0, 0.0,
                    True, False, 0.0, "name", True))
check("From JSON returns (geo, records, info)",
      len(out) == 3 and isinstance(out[0], Geometry) and out[1] == 3)
check("  info states record count, parse mode, attributes, groups",
      all(k in out[2] for k in ("3 records", "parse", "groups")), out[2])
out2 = unwrap(fj.run("```json\n" + LAY + ",\n```", "points", "auto", "xz",
                     10.0, 10.0, 0.0, 0.0, 0.0, True, False, 0.0, "", True))
check("  dirty input still runs, and info states what was fixed",
      out2[1] == 3 and "fences" in out2[2], out2[2])

tj = N.PCG_GeoToJSON()
out3 = unwrap(tj.run(gg, "", 0, 6, 0, **{"class": "point"}))
check("Geo to JSON returns (json, count)",
      len(out3) == 2 and out3[1] == 3 and isinstance(out3[0], str))
check("  the two nodes chained form a closed loop (export then import, point count and attributes correct)",
      (lambda r: r[0].npoints == 3
       and list(np.asarray(r[0].get(POINT, "name")).ravel())
       == ["tree", "rock", "tree"])(
          unwrap(fj.run(out3[0], "points", "auto", "xz", 10.0, 10.0, 0.0, 0.0,
                        0.0, False, False, 0.0, "name", True))))

spec = N.PCG_FromJSON.INPUT_TYPES()["required"]
check("json_text is multiline (a large block gets pasted)",
      spec["json_text"][1].get("multiline") is True)
check("combo items are the module's constants",
      spec["mode"][0] == list(ST.MODES) and spec["plane"][0] == list(ST.PLANES))
check("group_by defaults to name (the most common one)",
      spec["group_by"][1]["default"] == "name")
check("both nodes are in PCG/convert (same place as Import / Export Mesh)",
      N.PCG_FromJSON.CATEGORY == "PCG/convert"
      and N.PCG_GeoToJSON.CATEGORY == "PCG/convert")


# ═══════════════════════════ 8. The chain from the pitch: AI layout -> procedural execution
sec("LLM layout -> procedural execution")
PLAN = """Here's a small village layout:
```json
{
  "seed": 42,
  "buildings": [
    {"label": "house", "bbox": [0.05, 0.05, 0.35, 0.30], "floors": 2},
    {"label": "house", "bbox": [0.45, 0.10, 0.70, 0.35], "floors": 1},
    {"label": "barn",  "bbox": [0.55, 0.60, 0.95, 0.90], "floors": 1},
  ]
}
```
"""
plan, ip = ST.from_json(PLAN, mode="boxes", size=(40, 40), group_by="label")
check("dirty LLM output read directly as three lots",
      plan.nprims == 3 and ip["records"] == 3, ip["parse"])
check("  labels become groups: house two lots, barn one",
      int(np.asarray(plan.get_group(PRIM, "house")).sum()) == 2
      and int(np.asarray(plan.get_group(PRIM, "barn")).sum()) == 1)
check("  extra keys (floors) become prim attributes as is -- later they can drive floor height",
      plan.has(PRIM, "floors")
      and np.array_equal(np.asarray(plan.get(PRIM, "floors")).ravel(),
                         [2.0, 1.0, 1.0]))
check("  seed lands on detail",
      float(np.asarray(plan.get(DETAIL, "seed"))[0][0]) == 42.0)
from comfyui_pcg.geo import ops as _o                    # noqa: E402
ex = _o.polyextrude(plan, distance=3.0)
check("PolyExtrude works directly (the box -> wall chain is connected)",
      ex.nprims > plan.nprims, f"{plan.nprims} -> {ex.nprims}")
areas = np.asarray(_o.measure_area(plan).get(PRIM, "area")).ravel()
want_area = [(0.35 - 0.05) * 40 * (0.30 - 0.05) * 40,
             (0.70 - 0.45) * 40 * (0.35 - 0.10) * 40,
             (0.95 - 0.55) * 40 * (0.90 - 0.60) * 40]
check("  each lot's area matches the **analytic value** computed from the bbox",
      np.allclose(areas, want_area, rtol=1e-5), list(zip(areas, want_area)))
back_txt = ST.dumps(plan, PRIM, attribs="name floors")
check("back to JSON for the model to see (closed loop)",
      len(json.loads(back_txt)) == 3
      and json.loads(back_txt)[0]["name"] == "house", back_txt[:60])


print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
