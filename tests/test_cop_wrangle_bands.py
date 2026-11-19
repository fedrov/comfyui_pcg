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

# the bands on threads (PCG_THREADS): the same numbers as one thread, in row order
os.environ["PCG_THREADS"] = "1"
one = PX.wrangle(img, code, 7, chunk_rows=5)
os.environ["PCG_THREADS"] = "3"
three = PX.wrangle(img, code, 7, chunk_rows=5)
del os.environ["PCG_THREADS"]
check("bands on 3 threads = on 1 thread, bit for bit (every layer)",
      sorted(three.names) == sorted(one.names) and all(np.array_equal(PX.getn(three, n), PX.getn(one, n))
                                                       for n in one.names))
# noise(): Perlin's gradient as a lookup table gives the same numbers as his selects
from comfyui_pcg.geo import wrangle as WG  # noqa: E402
rng_ = np.random.default_rng(3)
h_ = rng_.integers(0, 1 << 20, 200000)
x_, y_, z_ = (rng_.normal(size=200000) * 5 for _ in range(3))
check("noise's gradient table = Perlin's selects, bit for bit (all 16 gradients)",
      np.array_equal(WG._grad3(h_, x_, y_, z_), WG._grad3_ref(h_, x_, y_, z_))
      and set(np.unique(h_ & 15)) == set(range(16)))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
