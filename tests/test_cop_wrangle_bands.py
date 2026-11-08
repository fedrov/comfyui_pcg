"""
pcg110: COP Wrangle "Rows per Pass" (geo/cop/pixel.wrangle chunk_rows): running per-pixel code on bands of rows gives the
same image as running it on the whole image, for every special variable, layer read / write and new layers; whole-image
reductions are where it differs (documented), which the negative control shows.
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

from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP  # noqa: E402
from comfyui_pcg.geo.cop import pixel as PX  # noqa: E402
from comfyui_pcg.geo.cop.core import CopImage  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if isinstance(extra, str) and not extra else "   " + str(extra)))


img = CopImage(37, 23)
r = np.random.default_rng(3)
img.set("C", r.random((23, 37, 3)))
img.set("P", r.random((23, 37, 3)) * 4)
code = """
s = floor(@u * 3)
q = noise(@P * 2.0 + s) + rand(@ix) * 0.1
@C = @C * 0.5 + set(@u, @v, q)
rs = @res
@C.x = @C.x + @y / rs[1] + @x / rs[0]
@extra = q * 2
@vec2 = set(@u, q)
"""
whole = PX.wrangle(img, code, 7)
names = sorted(whole.names)
for rows in (1, 5, 8, 23, 100):
    band = PX.wrangle(img, code, 7, chunk_rows=rows)
    same = sorted(band.names) == names and all(
        np.allclose(PX.getn(band, n), PX.getn(whole, n), atol=1e-12) for n in names)
    check(f"rows per pass = {rows}: identical to the whole-image run (all layers, incl. new ones)", same)
node = MAP["PCG_COPWrangle"]()
a = node.run(img, code, 7)[0]
b = node.run(img, code, 7, "{}", 4)[0]
check("node: Rows per Pass 0 (default) = old behaviour, 4 = same result",
      all(np.allclose(PX.getn(a, n), PX.getn(b, n)) for n in names) and all(
          np.array_equal(PX.getn(a, n), PX.getn(whole, n)) for n in names))
red = "@C = @C * len(@C)     # depends on how many pixels the code sees at once"
check("negative control: a whole-image reduction does differ by band (why it is opt-in)",
      not np.allclose(PX.getn(PX.wrangle(img, red), "C"), PX.getn(PX.wrangle(img, red, chunk_rows=5), "C")))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
