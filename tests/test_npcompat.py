"""
pcg117: the plugin keeps working when another node pack rebinds `np.bool = bool` (an old-numpy "fix" some packs apply
at import). numpy 2's np.select then rejects boolean conditions ("invalid entry 0 in condlist"), which broke Boolean
(closest_surface) in the modular city workflow. geo/npcompat.select replaces np.select everywhere.

  1. npcompat.select equals np.select (random conditions / choices, scalar choices, default, dtype)
  2. with np.bool rebound: np.select really fails (negative control), and every former np.select caller still works
     and gives the same numbers as before the rebinding
  3. no np.select call is left in the plugin source
"""
import glob
import os
import re
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (os.path.dirname(_R), os.path.dirname(os.path.dirname(_R))):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy  # noqa: F401,E402
import numpy as np  # noqa: E402

from comfyui_pcg.geo import npcompat as NC  # noqa: E402
from comfyui_pcg.geo import spatial, scatter, attribnoise  # noqa: E402
from comfyui_pcg.geo.cop import pixel, control  # noqa: E402

# the reference half of this test needs an intact numpy, also when the whole run simulates a rebinding pack
np.bool = np.bool_

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if extra == "" else "   " + str(extra)))


rng = np.random.default_rng(7)
print("\n[npcompat.select == np.select]")
same = True
for _ in range(50):
    n = int(rng.integers(1, 40))
    k = int(rng.integers(1, 6))
    conds = [rng.random(n) < 0.4 for _ in range(k)]
    choices = [rng.normal(size=n) for _ in range(k)]
    d = float(rng.normal())
    a, b = np.select(conds, choices, d), NC.select(conds, choices, d)
    same &= a.dtype == b.dtype and np.array_equal(a, b)
check("50 random cases: same values and dtype", same)
c2 = [np.array([[True, False], [False, False]]), np.array([[True, True], [False, True]])]
check("scalar choices and default broadcast, first true wins",
      np.array_equal(NC.select(c2, [1.5, 2], -1), np.select(c2, [1.5, 2], -1)))
ci = [np.array([True, False, False]), np.array([False, True, False])]
check("integer choices stay integer, like np.select", NC.select(ci, [1, 2], 0).dtype == np.select(ci, [1, 2], 0).dtype)

# reference results with numpy intact
Q = rng.normal(size=(200, 3)) * 2
P = rng.normal(size=(60, 3))
T = rng.integers(0, 60, size=(40, 3))
ref_cs = spatial.closest_surface(Q, P, T)
hsv = rng.random((16, 16, 3))
ref_hsv = pixel.hsv_to_rgb(hsv)
ref_ctl = control.id_palette(np.arange(40))
xyz = rng.normal(size=(3, 500)) * 3
ref_sx = attribnoise.simplex(xyz.T, seed=3)
A_, B_, C_ = (rng.normal(size=(30, 3)) for _ in range(3))
ci_, ct_ = np.repeat(np.arange(50), 30), np.tile(np.arange(30), 50)
Qs = rng.normal(size=(50, 3))
ref_sc = scatter._closest_on_tris(Qs, A_, B_, C_, ci_, ct_)

print("\n[np.bool rebound to bool]")
orig = np.bool_
np.bool = bool
try:
    try:
        np.select([np.array([True, False])], [np.ones(2)], 0)
        broke = False
    except TypeError as e:
        broke = "condlist" in str(e)
    check("negative control: np.select itself now fails on boolean conditions", broke)
    cs = spatial.closest_surface(Q, P, T)
    check("closest_surface (Boolean's attribute carry) works and matches",
          all(np.array_equal(a, b) for a, b in zip(cs, ref_cs)))
    check("COP hsv_to_rgb works and matches", np.array_equal(pixel.hsv_to_rgb(hsv), ref_hsv))
    check("ID palette (Control Image id) works and matches", np.array_equal(control.id_palette(np.arange(40)), ref_ctl))
    check("simplex noise (Attribute Noise) works and matches", np.array_equal(attribnoise.simplex(xyz.T, seed=3), ref_sx))
    sc = scatter._closest_on_tris(Qs, A_, B_, C_, ci_, ct_)
    check("Scatter relax closest point works and matches",
          all(np.array_equal(np.asarray(a), np.asarray(b)) for a, b in zip(sc, ref_sc)))
finally:
    np.bool = orig

print("\n[source]")
pkg = os.path.dirname(_R)
left = []
for f in glob.glob(os.path.join(pkg, "**", "*.py"), recursive=True):
    if os.sep + "tests" + os.sep in f or f.endswith("npcompat.py"):
        continue
    for i, line in enumerate(open(f, encoding="utf-8"), 1):
        code = line.split("#", 1)[0]
        if re.search(r"\bnp\.select\(", code):
            left.append(f"{os.path.relpath(f, pkg)}:{i}")
check("no np.select call left in the plugin (use geo.npcompat.select)", not left, left[:5])

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
