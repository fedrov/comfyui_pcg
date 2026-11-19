"""
COP Wrangle on torch (geo/cop/wrangle_torch.py, Compute auto / cuda): the same translated code on tensors.

Proven here on torch's CPU device, so it runs without a GPU:
  - float64: every COP Wrangle of the example workflows gives numpy's layers (to 1e-6), on random layers of the
    channel counts they use -- the (pixels, 1) column convention reproduces the numpy path's Vec / Col1 broadcasting
  - float32 (the CUDA arithmetic): noise, pnoise and worley within float32 rounding of numpy's; rand on whole
    numbers bit-identical (the same 64-bit mixing)
  - what the GPU path does not cover runs on numpy, with the same result and a reason
  - negative control: a (pixels,) column next to a (pixels, 1) one -- what the convention exists to prevent --
    broadcasts to pixels x pixels
"""
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

from comfyui_pcg.geo.cop import pixel as PX  # noqa: E402
from comfyui_pcg.geo.cop import backend as BK  # noqa: E402
from comfyui_pcg.geo.cop.core import CopImage  # noqa: E402
from comfyui_pcg.geo import wrangle as WG  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


if BK.torch_module() is None:
    print("  (no torch: skipped)")
    sys.exit(0)
torch = BK.torch_module()

VEC3 = {"N", "Nb", "terrain_albedo", "grass_c", "rock_c", "normal_ts", "worldnormal", "tangent", "bitangent",
        "position", "basecolor"}


def random_image(code, res=32, seed=0):
    rng = np.random.default_rng(seed)
    names = set(re.findall(r"@([A-Za-z_]\w*)", code)) - {"u", "v", "x", "y", "res", "ix"}
    comps = {}
    for k, c in re.findall(r"@([A-Za-z_]\w*)\.([xyzwrgba])", code):
        comps[k] = max(comps.get(k, 1), "xyzw".find(c) + 1 if c in "xyzw" else "rgba".find(c) + 1)
    im = CopImage(res, res)
    for k in sorted(names):
        c = 4 if k.startswith("terrain_w") else 3 if (k in VEC3 or comps.get(k, 1) in (2, 3)) else comps.get(k, 1)
        im.set(k, rng.random((res, res, c), dtype=np.float32) if c > 1 else rng.random((res, res), dtype=np.float32))
    return im


def max_diff(a, b):
    d = 0.0
    for k in a.names:
        x, y = np.asarray(a.get(k), np.float64), np.asarray(b.get(k), np.float64)
        if x.shape != y.shape or not np.array_equal(np.isnan(x), np.isnan(y)):
            return np.inf
        if np.isfinite(x).any():
            d = max(d, float(np.nanmax(np.abs(x - y))))
    return d if set(a.names) == set(b.names) else np.inf


print("\n── every COP Wrangle of the example workflows: torch (float64) = numpy")
import make_workflows as MW  # noqa: E402
codes = {}
for name, fn in MW.WORKFLOWS.items():
    for n in fn().to_ui()["nodes"]:
        if n["type"] == "PCG_COPWrangle":
            codes.setdefault(n["widgets_values"][0], f"{name}: {n.get('title') or ''}"[:70])
ran, same, fell = 0, 0, []
for code, where in codes.items():
    im = random_image(code)
    a = PX.wrangle(im, code, 3, {}, 8, compute="cpu")
    b = PX.wrangle(im, code, 3, {}, 8, compute="torch_cpu")
    if PX.LAST_WRANGLE["engine"] == "numpy":
        fell.append((where, PX.LAST_WRANGLE["reason"]))
        continue
    ran += 1
    d = max_diff(a, b)
    if d <= 1e-6:
        same += 1
    else:
        print(f"        differs: {where} ({d:.3g})")
check(f"{len(codes)} distinct codes: {ran} ran on torch, all {same} of them equal to numpy (1e-6); "
      f"{len(fell)} ran on numpy", ran == same and ran >= len(codes) - 2, [w for w, _ in fell])
check("  among them the 4096² surface, the splat weights, the layer library and the rock texel detail",
      not any(k in w for w, _ in fell for k in ("Surface:", "Splat weights", "Terrain layers", "Texture-space")))

print("\n── float32 (the arithmetic of the CUDA path)")
L32 = __import__("comfyui_pcg.geo.cop.wrangle_torch", fromlist=["lib"]).lib("cpu", torch.float32)
rng = np.random.default_rng(5)
P = rng.random((20000, 3)) * 200 - 100
n_np = WG.perlin3(P)
n_t = L32.noise(torch.as_tensor(P, dtype=torch.float32)).numpy()[:, 0]
check("noise() within float32 rounding of numpy's (coordinates up to ±100)", float(np.abs(n_np - n_t).max()) < 2e-4,
      float(np.abs(n_np - n_t).max()))
pn_np = WG.perlin3_periodic(P, 8)
pn_t = L32.noise(torch.as_tensor(P, dtype=torch.float32), 8).numpy()[:, 0]
check("pnoise(p, 8) likewise", float(np.abs(pn_np - pn_t).max()) < 2e-4, float(np.abs(pn_np - pn_t).max()))
f1, f2, cid, vec = WG.worley3_periodic(P[:, :3] * 0.1, 0)
g1, g2, gid, gvec = (v.numpy() for v in L32.worley(torch.as_tensor(P * 0.1, dtype=torch.float32), 0))
same_cell = np.isclose(cid, gid[:, 0], atol=1e-6)
check("worley: the same cells (id) for 99.9% of the points, f1 / f2 within 1e-4 there (the rest sit on a cell "
      "border)", same_cell.mean() > 0.999 and np.abs(f1 - g1[:, 0])[same_cell].max() < 1e-4
      and np.abs(f2 - g2[:, 0])[same_cell].max() < 1e-4, round(float(same_cell.mean()), 5))
iv = np.arange(-5000, 5000, dtype=np.float64)
r_np = WG._hash01(iv, 7)
r_t = L32.rand(torch.as_tensor(iv, dtype=torch.float32), 7).numpy().reshape(-1)
check("rand() on whole numbers: the same numbers as numpy (the same 64-bit mixing)",
      np.allclose(r_np, r_t, atol=1e-7), float(np.abs(r_np - r_t).max()))
r_bad = np.array([WG._hash01(float(x), 8) for x in iv[:50]])
check("  negative control: another salt gives other numbers", not np.allclose(r_bad, r_np[:50]))

print("\n── what the GPU path does not cover runs on numpy")
im = random_image("@C = @C")
for code, why in (('@D = @C * 0 + float(len(sprintf("%d", 3)))', "sprintf"),
                  ("@D = np.clip(@C, 0.2, 0.4)", "a numpy function"),
                  ("if @C > 0.5:\n    @D = @C\n", "an if on a per-pixel value")):
    try:
        a = PX.wrangle(im, code, 0, {}, 0, compute="cpu")
        err_np = None
    except Exception as e:
        err_np = type(e).__name__
    try:
        b = PX.wrangle(im, code, 0, {}, 0, compute="torch_cpu")
        err_t = None
    except Exception as e:
        err_t = type(e).__name__
    ok = (PX.LAST_WRANGLE["engine"] == "numpy" and err_np == err_t
          and (err_np is not None or max_diff(a, b) == 0))
    check(f"  {why}: ran on numpy ({PX.LAST_WRANGLE['reason'][:70]}...), the same result or error", ok)
PX.wrangle(im, "@D = @C", 0, {}, 0)
check("the library default (compute = cpu) stays on numpy", PX.LAST_WRANGLE["engine"] == "numpy")
PX.wrangle(im, "@D = @C", 0, {}, 0, compute="auto")
check("auto without CUDA: numpy", PX.LAST_WRANGLE["engine"] == "numpy" or BK.cuda_available(),
      PX.LAST_WRANGLE["reason"])

print("\n── the column convention")
code = "@D = @N.x * @C + length(@N) * dot(@N, set(1, 2, 3)) + noise(@N * 4) * rand(@x)"
im = random_image(code, res=24)
d = max_diff(PX.wrangle(im, code, 1, {}, 0, compute="cpu"), PX.wrangle(im, code, 1, {}, 0, compute="torch_cpu"))
check("components, lengths, dots, noise and rand mixed with vectors: torch = numpy", d < 1e-9, d)
a1 = torch.zeros(24 * 24)
a2 = torch.zeros((24 * 24, 1))
check("  negative control: a (pixels,) column next to a (pixels, 1) one broadcasts to pixels x pixels",
      tuple((a1 * a2).shape) == (576, 576))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
