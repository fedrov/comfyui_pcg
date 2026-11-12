"""
pcg126: progress bar and Cancel for long-running nodes (geo/progress.py).

  1. Outside ComfyUI everything is a no-op (no comfy package, nothing raised, results unchanged)
  2. Progress: updates are monotone, end exactly at the total, and are throttled to about a hundred
  3. With ComfyUI present (a stub of comfy.utils.ProgressBar and comfy.model_management): the bar receives exactly
     `total` in all, and the interruption check is called
  4. Cancel: when the check raises, the loop stops right there -- HeightField Erode, Stream Power, Thermal Erosion,
     Hydraulic Erosion, the reaction-diffusion / ripple solvers and the sky light of the Outdoor look all stop early
     with ComfyUI's exception (negative control: without a cancel they run to the end)
"""
import os
import sys
import types

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (os.path.dirname(_R), os.path.dirname(os.path.dirname(_R))):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy  # noqa: F401,E402
import numpy as np  # noqa: E402

import comfyui_pcg  # noqa: E402,F401
from comfyui_pcg.geo import progress as PG, build, outdoor as O  # noqa: E402
from comfyui_pcg.geo.cop import CopImage, erode as ER, flow as FL  # noqa: E402

N = comfyui_pcg.NODE_CLASS_MAPPINGS
OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if isinstance(extra, str) and extra == "" else "   " + str(extra)))


def himg(n=48):
    rng = np.random.default_rng(1)
    h = rng.random((n, n))
    for _ in range(4):
        h = (h + np.roll(h, 1, 0) + np.roll(h, 1, 1) + np.roll(h, -1, 0) + np.roll(h, -1, 1)) / 5
    im = CopImage(n, n)
    im.set("C", (h * 0.3 + 0.002 * np.arange(n)[None, :])[:, :, None])
    return im


print("\n[1. Outside ComfyUI]")
PG._comfy = None
PG.sink = None
p = PG.Progress(10)
for _ in range(10):
    p.step()
PG.check()
check("no comfy package: Progress and check() do nothing and raise nothing", p.done == 10 and PG._comfy == (None, None))

print("\n[2. Updates]")
seen = []
PG.sink = lambda d, t: seen.append((d, t))
p = PG.Progress(100000)
for _ in range(100000):
    p.step()
d = [x[0] for x in seen]
check("monotone, ends exactly at the total, throttled to about a hundred updates (not 100 000)",
      d == sorted(d) and d[-1] == 100000 and 90 <= len(d) <= 101 and all(x[1] == 100000 for x in seen), len(d))
seen.clear()
p = PG.Progress(7)
for _ in range(7):
    p.step()
check("  a short loop reports every step", [x[0] for x in seen] == [1, 2, 3, 4, 5, 6, 7])
seen.clear()
p = PG.Progress(10)
p.step(4)
p.step(4)
p.step(4)
check("  step(n) counts n and never passes the total", [x[0] for x in seen] == [4, 8, 10])
PG.sink = None

print("\n[3. With ComfyUI]")


class Stop(Exception):
    pass


class _Bar:
    made = []

    def __init__(self, total):
        self.total, self.got = total, 0
        _Bar.made.append(self)

    def update(self, n):
        self.got += n


state = {"calls": 0, "cancel_at": None}


def _interrupted():
    state["calls"] += 1
    if state["cancel_at"] is not None and state["calls"] >= state["cancel_at"]:
        raise Stop("cancelled")


comfy = types.ModuleType("comfy")
cu = types.ModuleType("comfy.utils")
cu.ProgressBar = _Bar
cm = types.ModuleType("comfy.model_management")
cm.throw_exception_if_processing_interrupted = _interrupted
comfy.utils, comfy.model_management = cu, cm
sys.modules.update({"comfy": comfy, "comfy.utils": cu, "comfy.model_management": cm})
PG._comfy = None
out, rep = ER.heightfield_erode(himg(), iterations=37, compute="cpu")
bar = _Bar.made[-1]
check("HeightField Erode: the node's bar is created with the step count and receives exactly that many",
      bar.total == 37 and bar.got == 37, (bar.total, bar.got))
check("  the interruption check is called while it runs", state["calls"] >= 37, state["calls"])

print("\n[4. Cancel]")


def cancelled(fn, at=3):
    state["calls"], state["cancel_at"] = 0, at
    try:
        fn()
        return False
    except Stop:
        return True
    finally:
        state["cancel_at"] = None


trace = []
ok = cancelled(lambda: ER.heightfield_erode(himg(), iterations=500, compute="cpu", trace=trace))
check("HeightField Erode stops at the cancel (third check: checks come every 5 steps of 500, so under 20 done)", ok and len(trace) < 20, len(trace))
tr2 = []
ER.heightfield_erode(himg(), iterations=12, compute="cpu", trace=tr2)
check("  negative control: without a cancel it runs all its steps", len(tr2) == 12)
tr3 = []
ok = cancelled(lambda: FL.stream_power(himg(), iterations=400, trace=tr3))
check("Stream Power stops (under 20 of 400 steps done)", ok and len(tr3) < 20, len(tr3))


def nrun(name, **kw):
    c = N["PCG_" + name]
    args = {}
    for sec in ("required", "optional"):
        for k, spec in (c.INPUT_TYPES().get(sec) or {}).items():
            t = spec[0]
            o = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            if isinstance(t, list):
                args[k] = t[0]
            elif "default" in o:
                args[k] = o["default"]
    args.update(kw)
    return getattr(c(), c.FUNCTION)(**args)


for nm, kw in (("COPThermalErosion", dict(iterations=400, talus_angle=5.0, compute="cpu")),
               ("COPHydraulicErosion", dict(droplets_per_pixel=20.0, batch=64, compute="cpu"))):
    ok = cancelled(lambda: nrun(nm, cop=himg(), **kw))
    check(f"{nm[3:]} (through the node) stops", ok)
import time  # noqa: E402
box = build.box()
t0 = time.time()
ok = cancelled(lambda: O.render_outdoor(box, 96, 64, ssaa=1, sky_samples=64), at=6)
t_cancel = time.time() - t0
t0 = time.time()
O.render_outdoor(box, 96, 64, ssaa=1, sky_samples=64)
t_full = time.time() - t0
check("Outdoor look: the render stops during the sky light, well before a full render would finish",
      ok and t_cancel < t_full * 0.8, (round(t_cancel, 2), round(t_full, 2)))
for k in ("comfy", "comfy.utils", "comfy.model_management"):
    sys.modules.pop(k, None)
PG._comfy = None

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
