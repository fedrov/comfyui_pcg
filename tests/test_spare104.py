"""
pcg104: custom parameters on any node -- the backend half (frontend: see test_spare.mjs).

The frontend writes the values of all custom parameters on a node into ch_params (JSON); vectors also get one entry per component. This tests that the ch() family in the three Wrangles
(geometry / volume / COP) reads them correctly:
  ch / chf  number (a vector gives its first component, as in Houdini; a toggle is 1 / 0)   chi  rounded to int
  chv       vector (a scalar is broadcast to all three)                                    chs  string
  ch("posx")  component name of a vector (the per-component entry written by the frontend)
  no such parameter   use ch()'s second argument (the default value)
"""
import json
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
from comfyui_pcg.geo import build                      # noqa: E402
from comfyui_pcg.geo.wrangle import ch_funcs           # noqa: E402
from comfyui_pcg.geo.core import POINT                 # noqa: E402
from comfyui_pcg.geo.cop.core import CopImage          # noqa: E402
from comfyui_pcg.geo.cop.pixel import getn             # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


CH = {"amp": 0.5, "n": 3.6, "pos": [1, 2, 3], "posx": 1, "posy": 2, "posz": 3, "on": True,
      "tag": "hello", "scale": 2}
F = ch_funcs(CH)
print("── ch() family")
check("ch / chf read numbers; missing parameters use the default", F["ch"]("amp") == 0.5 and F["chf"]("amp") == 0.5
      and F["ch"]("nope", 7) == 7.0 and F["ch"]("nope") == 0.0)
check("chi rounds (3.6 -> 4, not truncated to 3)", F["chi"]("n") == 4)
check("chv reads vectors; a scalar is broadcast to three; missing ones use the default",
      np.allclose(F["chv"]("pos"), [1, 2, 3]) and F["chv"]("scale").shape == (3,)
      and np.allclose(F["chv"]("scale"), [2, 2, 2])
      and np.allclose(F["chv"]("nope"), [0, 0, 0]))
check("chv(\"pos\").y takes a component like VEX; arithmetic works as with a normal array (broadcasts with (N,3))",
      F["chv"]("pos").y == 2.0 and np.allclose(np.zeros((4, 3)) + F["chv"]("pos"), [[1, 2, 3]] * 4))
check("ch(\"posy\") reads a component; ch(\"pos\") on a vector takes the first component (same as Houdini)",
      F["ch"]("posy") == 2.0 and F["ch"]("pos") == 1.0)
check("toggle is 1 / 0; chs reads strings", F["ch"]("on") == 1.0 and F["chs"]("tag") == "hello"
      and F["chs"]("nope", "d") == "d")
check("a string read as a number: falls back to the default (does not raise)", F["ch"]("tag", 9) == 9.0)

print("── the three Wrangles")
g = build.grid(2, 2, 3, 3)
r = M["PCG_Wrangle"]().run(g, "point", '@P.y += ch("amp") * chv("pos").y + ch("posz")', "", 0,
                           json.dumps(CH))
out = r["result"][0] if isinstance(r, dict) else r[0]
check("geometry Wrangle: @P.y += amp·pos.y + posz = 0.5·2 + 3 = 4",
      np.allclose(np.asarray(out.get(POINT, "P"))[:, 1], 4.0))
r = M["PCG_Wrangle"]().run(g, "point", 's@t = chs("tag"); i@k = chi("n")', "", 0, json.dumps(CH))
out = r["result"][0] if isinstance(r, dict) else r[0]
check("  string / integer parameters written into attributes", out.get(POINT, "t")[0, 0] == "hello" and int(out.get(POINT, "k")[0, 0]) == 4)
it = M["PCG_COPWrangle"].INPUT_TYPES()["required"]
# ch_params was appended after the pre-pcg104 widgets; later additions (pcg110 rows_per_pass) come after it
check("COP Wrangle gains ch_params (appended after the old widgets, default {}, marked ch_store)",
      list(it)[:4] == ["cop", "code", "rand_seed", "ch_params"] and it["ch_params"][1]["default"] == "{}"
      and it["ch_params"][1]["ch_store"])
img = CopImage(5, 4, {"C": np.zeros((4, 5, 3), np.float32)})
r = M["PCG_COPWrangle"]().run(img, '@C = set(ch("amp"), chv("pos").z, ch("on"))', 0, json.dumps(CH))
o = r["result"][0] if isinstance(r, dict) else r[0]
C = getn(o, "C").reshape(-1, 3)
check("COP Wrangle:@C = (amp, pos.z, on) = (0.5, 3, 1)", np.allclose(C, [0.5, 3, 1]), C[0])
r = M["PCG_COPWrangle"]().run(img, '@C = set(ch("amp", 0.25), 0, 0)', 0)
o = r["result"][0] if isinstance(r, dict) else r[0]
check("  no ch_params (old workflow): use ch()'s default values", np.allclose(getn(o, "C").reshape(-1, 3)[:, 0], 0.25))
r = M["PCG_COPWrangle"]().run(img, '@C = set(ch("amp"), 0, 0)', 0, "{bad json")
o = r["result"][0] if isinstance(r, dict) else r[0]
check("  ch_params malformed: treated as empty (the node does not error)", np.allclose(getn(o, "C").reshape(-1, 3)[:, 0], 0))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
