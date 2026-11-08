"""
pcg109: which Cd the viewport payload carries. Houdini draws Cd in the shaded view with the precedence
vertex > point > primitive > detail; viewport.encode sends that one class as the "color" buffer plus
header["color_class"] (test_viewport_cd.mjs checks how the frontend draws each class).
"""
import json
import os
import struct
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (os.path.dirname(_R), os.path.dirname(os.path.dirname(_R))):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy  # noqa: F401,E402
import numpy as np  # noqa: E402

from comfyui_pcg import viewport as VP  # noqa: E402
from comfyui_pcg.geo import build  # noqa: E402
from comfyui_pcg.geo.core import POINT, VERTEX, PRIM, DETAIL  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if extra == "" else "   " + str(extra)[:300]))


def payload(g):
    b = VP.encode(g)
    assert b[:4] == b"PCGB"
    n = struct.unpack("<I", b[4:8])[0]
    h = json.loads(b[8:8 + n])
    base = 8 + n
    col = None
    if "color" in h["buffers"]:
        m = h["buffers"]["color"]
        col = np.frombuffer(b[base + m["offset"]:base + m["offset"] + m["length"]], np.float32).reshape(-1, 3)
    return h, col


box = build.box()
h, col = payload(box)
check("no Cd: no colour buffer, no colour class", col is None and "color_class" not in h)

cases = {DETAIL: 1, PRIM: box.nprims, POINT: box.npoints, VERTEX: box.nvertices}
g = box.copy()
want = None
for cls in (DETAIL, PRIM, POINT, VERTEX):            # add classes from the lowest precedence up
    n = cases[cls]
    vals = np.random.default_rng(len(cls)).random((n, 3)).astype(np.float32)
    g.set(cls, "Cd", vals)
    h, col = payload(g)
    check(f"with Cd up to {cls}: the {cls} Cd is sent (precedence vertex > point > prim > detail)",
          h.get("color_class") == cls and col is not None and col.shape == (n, 3) and np.allclose(col, vals),
          (h.get("color_class"), None if col is None else col.shape))
g2 = box.copy()
g2.set(POINT, "Cd", np.full((box.npoints, 3), 2.0, np.float32))
check("values are clamped to 0..1 for display", np.allclose(payload(g2)[1], 1.0))
g3 = box.copy()
g3.set(PRIM, "Cd", np.zeros((box.nprims, 3), np.float32))
g3.set(POINT, "Cd", np.ones((box.npoints, 3), np.float32))
check("  negative control: point beats prim (a prim-first order would send zeros)",
      payload(g3)[0]["color_class"] == POINT and payload(g3)[1].max() == 1.0)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
