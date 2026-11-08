"""
Code guard (geo/wrangle.check_code): code from a workflow -- Wrangle, COP Wrangle, Volume Wrangle, group expressions
and Expression / Switch formulas -- runs as Python on the server, so the obvious ways to reach files, programs and
Python internals are rejected before anything runs. The everyday code of all example workflows still passes, and
PCG_ALLOW_UNSAFE_CODE=1 lifts the guard (negative control: then the file really is written).
"""
import glob
import json
import os
import sys
import tempfile

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (os.path.dirname(_R), os.path.dirname(os.path.dirname(_R))):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy  # noqa: F401,E402
import numpy as np  # noqa: E402

from comfyui_pcg import expr as EX  # noqa: E402
from comfyui_pcg.geo import build  # noqa: E402
from comfyui_pcg.geo import groups as GR  # noqa: E402
from comfyui_pcg.geo import wrangle as WR  # noqa: E402
from comfyui_pcg.geo.cop import pixel as PX  # noqa: E402
from comfyui_pcg.geo.cop.core import CopImage  # noqa: E402
from comfyui_pcg.geo.core import POINT  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if isinstance(extra, str) and not extra else "   " + str(extra)))


g = build.grid(size_x=2, size_z=2, cols=3, rows=3)
img = CopImage(8, 8)
img.set("C", np.zeros((8, 8, 3)))
target = os.path.join(tempfile.mkdtemp(), "written.txt")
T = target.replace("\\", "/")


def blocked(fn):
    try:
        fn()
        return False
    except Exception as e:
        return "not allowed" in str(e)


print("\n[blocked in Wrangle]")
attacks = {
    "numpy file write": f'np.savetxt("{T}", [1])',
    "numpy file read": f'f@a = np.loadtxt("{T}")',
    "import": "import os",
    "from-import": "from os import system",
    "dunder attribute": "x = ().__class__.__base__.__subclasses__()",
    "dunder name": "__import__('os')",
    "generator frame": "x = (i for i in [1]).gi_frame.f_back",
    "getattr": 'x = getattr(np, "save")',
    "str.format traversal": 'x = "{0.__class__}".format(1)',
    "np.lib": "x = np.lib",
    "ndarray.tofile": f'@P.tofile("{T}")',
    "global": "def f():\n    global np\nf()",
}
for name, code in attacks.items():
    check(f"{name}: {code.splitlines()[0][:40]!r}", blocked(lambda c=code: WR.run_wrangle(g, c, POINT)))
check("  nothing was written", not os.path.exists(target))

print("\n[blocked on the other entry points]")
check("COP Wrangle", blocked(lambda: PX.wrangle(img, f'np.savetxt("{T}", [1])', 0, {})))
check("group expression", blocked(lambda: GR.resolve(g, POINT, "@P.__class__ > 0")))
check("Expression node formula", blocked(lambda: EX._eval("().__class__", {})))
check("Switch select formula", blocked(lambda: EX.eval_select("(1).__class__")))

print("\n[everyday code passes]")
code = ("s = seed * 17.31\nd = -1e9\nfor k in range(3):\n    d = max(d, @P.x * k)\n"
        "def sm(a, b):\n    return lerp(a, b, 0.5)\n@Cd = set(sm(@P.x, 1), 0, 0)\nf@m = @P.y.max()\n"
        "i@k = (@P.x * 10).astype(int)\ns@n = sprintf('p%02d', @ptnum)\n@group_top = @P.z > 0\ndel s")
r = WR.run_wrangle(g, code, POINT)
check("loops, def, del, .max(), .astype(), sprintf, @group_", r.get(POINT, "Cd") is not None)
check("COP Wrangle with pnoise and layers", PX.wrangle(img, "@n = pnoise(set(@u * 4, @v * 4, 0), 4)", 0, {}) is not None)
check("Expression node: fit(a, 0, 1, 0, 360)", EX._eval("fit(a, 0, 1, 0, 360)", {"a": 0.5}) == 180)
checked = bad = 0
for f in sorted(glob.glob(os.path.join(os.path.dirname(_R), "example_workflows", "*.json"))):
    for n in json.load(open(f, encoding="utf-8"))["nodes"]:
        if n["type"] in ("PCG_Wrangle", "PCG_COPWrangle", "PCG_VolumeWrangle"):
            for v in n.get("widgets_values") or []:
                if isinstance(v, str) and "@" in v:
                    checked += 1
                    try:
                        WR.check_code(WR._transpile(v)[0])
                    except WR.UnsafeCodeError:
                        bad += 1
check("the code of every Wrangle in the example workflows passes the guard", checked > 20 and bad == 0,
      (checked, bad))

print("\n[numpy's own lazy imports]")
import subprocess  # noqa: E402
probe = ("import sys; sys.path[:0] = %r\nimport fakecomfy\nfrom comfyui_pcg.geo import wrangle as WR, build\n"
         "from comfyui_pcg.geo.core import POINT\n"
         "r = WR.run_wrangle(build.grid(), 'f@m = @P.y.max()', POINT)\nprint(float(r.get(POINT, 'm')[0, 0]))"
         % [os.path.dirname(os.path.dirname(_R)), os.path.dirname(_R), _R])
out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
check("the first @P.y.max() in a fresh process works (numpy imports a module from C on first use)",
      out.returncode == 0 and out.stdout.strip() == "0.0", (out.stdout.strip() or out.stderr.strip()[-120:]))

print("\n[PCG_ALLOW_UNSAFE_CODE]")
os.environ["PCG_ALLOW_UNSAFE_CODE"] = "1"
try:
    WR.run_wrangle(g, f'np.savetxt("{T}", [1])', POINT)
finally:
    del os.environ["PCG_ALLOW_UNSAFE_CODE"]
check("negative control: with the guard lifted the same code writes the file", os.path.exists(target))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
