"""
Memory trim after long nodes (memtrim.py).

  1. Every registered node is wrapped once (idempotent), the wrapper is transparent: same result, signature visible
  2. trim() runs after a node that took longer than the threshold and not after a quick one (negative control)
  3. On Linux with glibc it gives memory back: a banded allocation pattern like a 4096² chunked COP Wrangle leaves
     the process hundreds of megabytes larger; after trim() most of it is returned (negative control: without the
     trim it stays)
  4. The test executor's release mode (fakecomfy.Executor(release=True), used for the open-world example): a node's
     outputs are dropped after its last reader ran, nothing is computed twice (negative control: by default all stay)
"""
import inspect
import os
import subprocess
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (os.path.dirname(_R), os.path.dirname(os.path.dirname(_R))):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy  # noqa: F401,E402

import comfyui_pcg  # noqa: E402
from comfyui_pcg import memtrim as MT  # noqa: E402

N = comfyui_pcg.NODE_CLASS_MAPPINGS
OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if isinstance(extra, str) and extra == "" else "   " + str(extra)))


print("── 1. Wrapping")
fns = [getattr(c, c.FUNCTION) for c in N.values() if getattr(c, "FUNCTION", None)]
check(f"all {len(fns)} node functions carry the trim wrapper", all(getattr(f, MT._MARK, False) for f in fns))
before = {k: getattr(c, c.FUNCTION) for k, c in N.items()}
MT.attach_memtrim(N)
check("  attaching again changes nothing (idempotent)", all(getattr(c, c.FUNCTION) is before[k] for k, c in N.items()))
box = N["PCG_Box"]
sig = inspect.signature(getattr(box, box.FUNCTION))
check("  the signature shows through (no *args, **kwargs)", "size" in str(sig) or len(sig.parameters) > 3, str(sig)[:60])

print("── 2. Only after long nodes")
calls = []
real = MT.trim
MT.trim = lambda: calls.append(1) or True


class Slow:
    FUNCTION = "run"

    def run(self, t):
        import time
        time.sleep(t)
        return (t,)


m = {"S": Slow}
MT.attach_memtrim(m)
r = Slow().run(0.6)
check("a node of 0.6 s: result unchanged, trim called once", r == (0.6,) and len(calls) == 1, len(calls))
Slow().run(0.0)
check("  negative control: a quick node does not trim", len(calls) == 1, len(calls))
MT.trim = real

print("── 3. Memory comes back (Linux, glibc)")
if MT._trim is None:
    print("  (no malloc_trim here: skipped)")
else:
    prog = r"""
import sys, numpy as np
sys.path[:0] = %r
from comfyui_pcg import memtrim as MT
def rss(): return int(open('/proc/self/statm').read().split()[1]) * 4096 // 1048576
keep = []
a = np.ones(8 << 20)            # one big block freed first raises glibc's mmap threshold
del a
for i in range(300):            # bands: 4 MB temporaries, one small survivor each
    t = [np.random.rand(1 << 19) for _ in range(6)]
    keep.append(t[-1][:64].copy())
    del t
r0 = rss()
if sys.argv[1] == "trim":
    MT.trim()
print(r0, rss())
""" % (sys.path[:2],)
    out = {}
    for mode in ("trim", "none"):
        o = subprocess.run([sys.executable, "-c", prog, mode], capture_output=True, text=True, timeout=120)
        out[mode] = [int(x) for x in o.stdout.split()] if o.returncode == 0 else None
    t, n = out["trim"], out["none"]
    check("trim: the process gives back most of what the freed bands left behind",
          t is not None and t[1] < t[0] - 0.5 * (t[0] - 60), t)
    check("  negative control: without trim it stays", n is not None and n[1] > n[0] - 5, n)

print("── 4. Test executor: release outputs once read")
COUNT = {}


class Num:
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"v": ("INT", {})}, "optional": {"a": ("INT",), "b": ("INT",)}}

    def run(self, v, a=0, b=0):
        COUNT[v] = COUNT.get(v, 0) + 1
        return (v + a + b,)


prompt = {"1": {"class_type": "Num", "inputs": {"v": 1}},
          "2": {"class_type": "Num", "inputs": {"v": 10, "a": ["1", 0]}},
          "3": {"class_type": "Num", "inputs": {"v": 100, "a": ["1", 0], "b": ["2", 0]}}}
for rel in (True, False):
    COUNT.clear()
    ex = fakecomfy.Executor(prompt, {"Num": Num}, release=rel)
    outs = {n: ex.run(n) for n in ("3", "1", "2")}
    if rel:
        check("release: the result is right, every node ran once, nothing left in the cache",
              outs["3"] == (112,) and COUNT == {1: 1, 10: 1, 100: 1} and not ex.root.cache, (outs, COUNT))
    else:
        check("  negative control: by default every output stays cached", len(ex.root.cache) == 3
              and outs["1"] == (1,) and COUNT == {1: 1, 10: 1, 100: 1})

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
