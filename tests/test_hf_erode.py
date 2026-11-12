"""
HeightField Erode (grid water: virtual pipes + sediment transport + thermal slumping).

━━ Criteria
  · **material conservation**, from the output layers: Δ(total terrain) = −(sediment carried off the edges); with Tile
    nothing leaves and the total is unchanged
  · flat ground: terrain bit-identical, water depth follows the closed form w_n = r(1−e)(1−(1−e)^n)/e
  · bedrock (hardness 1) unchanged bit for bit (negative control: hardness 0 changes it)
  · a tilted plane: water runs downhill (flow mask grows downslope), the slope is lowered
  · a V valley: the flow mask is higher on the valley floor than on the flanks (negative control: the flanks of a ridge)
  · a bowl: sediment collects on the floor, not on the rim
  · thermal alone (no rain): a tall column slumps until no slope exceeds the talus angle; debris = what slid
  · Rain Layer: total water is the rain that fell on the wet part (closed form), spreading into the dry part
  · Strength and World Size both ×2: identical (everything is in cells); negative control: World Size alone changes it
  · torch agrees with numpy (float32), conservation to float32 precision
  · the node: report, layers, bad parameters raise
"""
import math
import os
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R))):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy                                        # noqa: F401,E402
import numpy as np                                      # noqa: E402

from comfyui_pcg.geo.cop import CopImage                 # noqa: E402
from comfyui_pcg.geo.cop import erode as ER              # noqa: E402
from comfyui_pcg.geo.cop import backend as BK            # noqa: E402
from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP       # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag):
    try:
        fn()
        check(name, False, "no error raised")
    except Exception as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:90]}")


def L(img, name):
    a = img.need(name)
    if not isinstance(a, np.ndarray):
        a = BK.backend_of(a).to_numpy(a)
    return np.asarray(a, np.float64)[:, :, 0]


def himg(h, **more):
    im = CopImage(h.shape[1], h.shape[0])
    im.set("C", np.asarray(h, np.float64)[:, :, None])
    for k, v in more.items():
        im.set(k, np.asarray(v, np.float64)[:, :, None])
    return im


def run(h, **kw):
    kw.setdefault("compute", "cpu")
    return ER.heightfield_erode(h if isinstance(h, CopImage) else himg(h), **kw)


n = 64
yy, xx = np.mgrid[0:n, 0:n].astype(float)
rng = np.random.default_rng(5)
noise = rng.random((n, n))
for _ in range(4):
    noise = (noise + np.roll(noise, 1, 0) + np.roll(noise, 1, 1) + np.roll(noise, -1, 0) + np.roll(noise, -1, 1)) / 5
hills = (noise - noise.min()) / np.ptp(noise) * 0.3 + 0.002 * xx          # ×n cells with world_size = 1

print("\n[conservation]")
for tl in (False, True):
    o, rp = run(hills, strength=1.0, world_size=1.0, iterations=120, tile=tl)
    ws = 1.0 / n
    dv = (L(o, "C").sum() - hills.sum()) * ws * ws          # height values are world units here (strength 1)
    if not tl:
        check("Δ terrain volume = −(sediment carried off the edges), from the output layer",
              abs(dv + rp["sediment_out"]) < 1e-9 * abs(hills.sum() * ws * ws) and rp["sediment_out"] > 0,
              (dv, rp["sediment_out"]))
    else:
        check("  Tile: nothing leaves, total terrain unchanged", rp["sediment_out"] == 0 and abs(dv) < 1e-12, dv)
check("  something actually eroded", np.abs(L(o, "C") - hills).max() > 1e-4)

print("\n[flat ground]")
flat = np.full((24, 24), 0.25)
r_, e_, k_ = 0.03, 0.05, 37
o, _ = run(flat, iterations=k_, rain=r_, evaporation=e_, tile=True)
wf = r_ * (1 - e_) * (1 - (1 - e_) ** k_) / e_
check("terrain bit-identical", np.array_equal(L(o, "C"), flat))
check("  water = r(1−e)(1−(1−e)^n)/e  (in cells; world_size 1, 24 px -> × 1/24)",
      np.allclose(L(o, "water"), wf / 24, rtol=1e-12, atol=0), (L(o, "water")[0, 0] * 24, wf))

print("\n[bedrock]")
o, _ = ER.heightfield_erode(himg(hills, hd=np.ones_like(hills)), iterations=60, hardness_layer="hd", compute="cpu",
                            talus_angle=10.0, thermal_rate=0.5)
check("hardness 1: terrain unchanged bit for bit (water and slumping both)", np.array_equal(L(o, "C"), hills))
o0, _ = ER.heightfield_erode(himg(hills, hd=np.zeros_like(hills)), iterations=60, hardness_layer="hd", compute="cpu",
                             talus_angle=10.0, thermal_rate=0.5)
check("  negative control: hardness 0 changes it", not np.array_equal(L(o0, "C"), hills))

print("\n[tilted plane]")
pl = 0.4 * (1 - xx / (n - 1)) + 0.002 * noise           # downhill toward +x (x = column)
o, _ = run(pl, iterations=150)
fl = L(o, "flow")
cols = fl.mean(0)
check("flow mask grows downslope (mean of the upper third < middle < lower third)",
      cols[5:20].mean() < cols[22:42].mean() < cols[44:60].mean(),
      (round(cols[5:20].mean(), 3), round(cols[22:42].mean(), 3), round(cols[44:60].mean(), 3)))
check("  the slope is lowered (mean height drops)", L(o, "C").mean() < pl.mean() - 1e-4)

print("\n[V valley]")
vv = 0.3 * np.abs(xx - 32) / 32 + 0.15 * (1 - yy / (n - 1)) + 0.002 * noise
o, _ = run(vv, iterations=150)
fl = L(o, "flow")
floor, flank = fl[10:54, 30:35].mean(), np.r_[fl[10:54, 8:14].ravel(), fl[10:54, 50:56].ravel()].mean()
check("flow higher on the valley floor than on the flanks", floor > flank + 0.2, (round(floor, 3), round(flank, 3)))
o, _ = run(-vv + 0.45, iterations=150)
fl = L(o, "flow")
crest = fl[10:54, 30:35].mean()
check("  negative control: on a ridge the crest is the driest", crest < flank, round(crest, 3))

print("\n[bowl]")
r2 = np.hypot(xx - 31.5, yy - 31.5) / 32
bowl = 0.35 * r2 ** 2 + 0.003 * noise
o, _ = run(bowl, iterations=200)
sd = L(o, "sediment")
check("sediment collects on the floor of a bowl, not on the rim",
      sd[r2 < 0.25].mean() > 5 * sd[(r2 > 0.6) & (r2 < 0.9)].mean() and sd[r2 < 0.25].mean() > 0,
      (sd[r2 < 0.25].mean(), sd[(r2 > 0.6) & (r2 < 0.9)].mean()))

print("\n[thermal only]")
col = np.zeros((40, 40))
col[18:22, 18:22] = 0.5                                  # 20 cells tall in a 40-cell world (world_size 1)
o, _ = run(col, iterations=600, rain=0.0, talus_angle=40.0, thermal_rate=0.5, tile=True)
hc = L(o, "C") * 40
sl = max(np.abs(np.diff(hc, axis=0)).max(), np.abs(np.diff(hc, axis=1)).max())
check("a tall column slumps until no 4-neighbour slope exceeds the talus angle (+5 %)",
      sl <= math.tan(math.radians(40)) * 1.05, round(sl, 3))
check("  mass conserved with tile", abs(hc.sum() - col.sum() * 40) < 1e-9)
db = L(o, "debris") * 40
check("  debris = what slid: its total equals the volume removed from the column",
      abs(db.sum() - np.maximum(col * 40 - hc, 0).sum()) < 1e-6 * db.sum(), (db.sum(), np.maximum(col * 40 - hc, 0).sum()))

print("\n[rain layer]")
half = (xx < 32).astype(float)
o, _ = ER.heightfield_erode(himg(np.full((n, n), 0.2), rl=half), iterations=20, rain=0.02, evaporation=0.02,
                            rain_layer="rl", tile=True, compute="cpu")
wl = L(o, "water") * n
wtot = 0.02 * half.sum() * 0.98 * (1 - 0.98 ** 20) / 0.02
check("Rain Layer: total water = rain on the wet half only, closed form with evaporation (tiled, water conserved)",
      abs(wl.sum() - wtot) < 1e-9 * wtot, (wl.sum(), wtot))
check("  it spreads from the wet half into the dry half, deeper where it fell", wl[:, 4:28].mean() > wl[:, 36:60].mean() > 0)

print("\n[scale]")
a, _ = run(hills, strength=1.0, world_size=1.0, iterations=50)
b, _ = run(hills, strength=2.0, world_size=2.0, iterations=50)
check("Strength and World Size both ×2: identical (everything is in cells)",
      np.allclose(L(a, "C") * 1.0, L(b, "C"), rtol=0, atol=1e-12) and np.allclose(L(a, "flow"), L(b, "flow")))
c, _ = run(hills, strength=1.0, world_size=2.0, iterations=50)
check("  negative control: World Size alone (slopes halved) changes it", not np.allclose(L(a, "C"), L(c, "C")))

print("\n[torch]")
if BK.torch_module() is None:
    check("torch not installed: skipped", True)
else:
    t_, rt = run(hills, iterations=80, compute="torch_cpu")
    n_, rn = run(hills, iterations=80)
    d = np.abs(L(t_, "C") - L(n_, "C")).max()
    check("torch (float32) agrees with numpy", d < 2e-4, d)
    dv = (L(t_, "C").sum() - hills.sum()) / n / n
    check("  conservation to float32 precision", abs(dv + rt["sediment_out"]) < 1e-5, (dv, rt["sediment_out"]))

print("\n[node]")
nd = MAP["PCG_COPHeightfieldErode"]()
args = {}
for k, spec in nd.INPUT_TYPES()["required"].items():
    if k == "cop":
        continue
    t = spec[0]
    o = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    args[k] = t[0] if isinstance(t, list) else o.get("default")
args.update(iterations=30, compute="cpu")
out, rep = nd.run(himg(hills), **args)
check("node runs: all five masks written, report mentions the balance",
      all(x in out.names for x in ("C", "flow", "water", "sediment", "debris")) and "carried off the edges" in rep, rep[:80])
check("  defaults: Erosion Layer empty -> not written", "erosion" not in out.names)
err("bad Evaporation raises", lambda: run(hills, evaporation=1.5), "Evaporation")
err("bad Talus Angle raises", lambda: run(hills, talus_angle=90), "Talus")
err("Strength 0 raises", lambda: run(hills, strength=0.0), "Strength")

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
