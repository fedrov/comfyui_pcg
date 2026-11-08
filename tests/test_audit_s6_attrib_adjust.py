"""
pcg100 audit pack s6_attrib_adjust: the Attribute Adjust family completed against the SideFX docs.

  Attribute Adjust Float / Integer   new nodes (Houdini semantics): Operation × Pattern Type,
                                     Range Values, Distribution (Remap / Outliers), Stepping,
                                     Specific Values table, Attribute mode Scale/Offset,
                                     Randomization By, Noise Pattern (+ Manhattan / Chebyshev),
                                     Blend, Post-Process Min/Max, component / length
  Attribute Adjust Vector / Color    see their own sections
  Attribute Randomize / Noise        appended to the existing nodes (optional, default = old behaviour)

References are all hand-computable numbers. "Bit-identical to before the change at defaults" uses digests computed from the same calls
before the change (commit 9e3fb92), hard-coded in GOLDEN; `--digests` prints the current digests.
"""
import hashlib
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
from comfyui_pcg import panel as PANEL                  # noqa: E402
from comfyui_pcg.geo import build, ops                  # noqa: E402
from comfyui_pcg.geo import attribnoise as AN           # noqa: E402
from comfyui_pcg.geo import attribadjust2 as AA2        # noqa: E402
from comfyui_pcg.geo.attribrandomize import _rand01     # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, VERTEX, PRIM, DETAIL  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def defaults(nid):
    kw = {}
    for part in ("required", "optional"):
        for k, spec in M[nid].INPUT_TYPES().get(part, {}).items():
            if isinstance(spec[0], (list, tuple)):
                kw[k] = (spec[1].get("default", spec[0][0])
                         if len(spec) > 1 and isinstance(spec[1], dict) else spec[0][0])
            elif len(spec) > 1 and isinstance(spec[1], dict) and "default" in spec[1]:
                kw[k] = spec[1]["default"]
    return kw


def run(nid, **over):
    kw = defaults(nid)
    kw.update(over)
    r = getattr(M[nid](), M[nid].FUNCTION)(**kw)
    return r["result"][0] if isinstance(r, dict) else r[0]


def raises(fn, exc=Exception):
    try:
        fn()
    except exc:
        return True
    return False


def digest(g):
    h = hashlib.sha1()
    h.update(np.ascontiguousarray(g.vertex_point).tobytes())
    h.update(np.ascontiguousarray(g.prim_offset).tobytes())
    for cls in (POINT, VERTEX, PRIM, DETAIL):
        for k in sorted(g.attribs[cls]):
            v = g.attribs[cls][k]
            h.update(f"{cls}/{k}/{v.dtype}/{v.shape}".encode())
            h.update(np.ascontiguousarray(v).tobytes() if v.dtype.kind != "O"
                     else repr(v.tolist()).encode())
    return h.hexdigest()[:16]


def A(g, nm, cls=POINT):
    return np.asarray(g.get(cls, nm), np.float64)


# ═══════════════════════════════════════════════════════════════ Shared geometry
def grid(n=5):
    """2×2 grid of n×n points (XZ plane), with N, pscale = point number, v = (1,2,2) (length 3)."""
    g = build.grid(2.0, 2.0, n, n)
    g = ops.compute_normals(g, "point")
    k = np.arange(g.npoints, dtype=np.float32)
    g.set(POINT, "pscale", k[:, None])
    g.set(POINT, "v", np.tile(np.array([[1.0, 2.0, 2.0]], np.float32), (g.npoints, 1)))
    g.set(POINT, "mask", (k / max(len(k) - 1, 1))[:, None])
    g.set(POINT, "id", (k[::-1] * 3).astype(np.int32)[:, None])
    g.set(POINT, "Cd", np.stack([k / len(k), 0.5 + 0 * k, 1 - k / len(k)], 1).astype(np.float32))
    return g


def cloud(n=4000):
    P = np.random.default_rng(1).uniform(-5, 5, (n, 3))
    return Geometry.from_points(P)


# ═══════════════════════════════════════════════════════════════ Regression digests
OLD_NAMES = {
    "PCG_AttribAdjust": ['geo', 'group', 'attribute_class', 'attribute_name', 'create_if_missing', 'size',
                         'to_int', 'initialize', 'constant_x', 'constant_y', 'constant_z', 'constant_w',
                         'source_attribute', 'distribution', 'rand_min', 'rand_max', 'gaussian_mean',
                         'gaussian_stddev', 'power_exponent', 'noise_type', 'noise_size', 'noise_amplitude',
                         'expression', 'rand_seed', 'id_attribute', 'adjustments', 'use_remap', 'remap_ramp',
                         'ramp_mode', 'input_range', 'in_min', 'in_max', 'out_min', 'out_max',
                         'range_per_component', 'use_clamp_min', 'clamp_min', 'use_clamp_max', 'clamp_max',
                         'normalize', 'round_mode'],
    "PCG_AttribNoise": ['geo', 'group', 'attribute_class', 'attribute_names', 'use_x', 'use_y', 'use_z',
                        'noise_along_vector', 'vector_attribute', 'blend', 'operation', 'range_values',
                        'amplitude', 'use_value_correction', 'bias', 'gain', 'use_remap_ramp', 'remap_ramp',
                        'ramp_mode', 'use_clamp_min', 'clamp_min', 'use_clamp_max', 'clamp_max', 'noise_type',
                        'location_attribute', 'element_size_x', 'element_size_y', 'element_size_z',
                        'offset_x', 'offset_y', 'offset_z', 'rand_seed', 'use_vexpression', 'vexpression',
                        'use_animation', 'noise_time', 'time_element_size', 'fractal', 'octaves',
                        'lacunarity', 'roughness', 'fractal_offset', 'warp', 'warp_element_size',
                        'warp_octaves', 'post_absolute', 'post_invert', 'use_normalize', 'normalize_min',
                        'normalize_max'],
    "PCG_AttribRandomize": ['geo', 'group', 'attribute_class', 'name', 'mode', 'combine', 'rand_seed',
                            'id_attribute', 'distribution', 'dimensions', 'min_x', 'min_y', 'min_z', 'min_w',
                            'max_x', 'max_y', 'max_z', 'max_w', 'mean', 'stddev', 'exponent', 'shape',
                            'axis_x', 'axis_y', 'axis_z', 'cone_angle', 'angle_min', 'angle_max',
                            'length_min', 'length_max'],
    "PCG_Color": ['geo', 'attribute_class', 'group', 'mode', 'r', 'g', 'b', 'rand_seed', 'attribute', 'ramp',
                  'ramp_mode', 'auto_range', 'in_min', 'in_max', 'hue_shift', 'saturation', 'value',
                  'random_hue', 'random_saturation', 'random_value', 'name'],
}


def old(nid, **kw):
    """Pass only old parameters (explicit ones + defaults of old parameters): independent of whether new widgets exist."""
    base = {k: v for k, v in defaults(nid).items() if k in OLD_NAMES[nid]}
    base.update(kw)
    r = getattr(M[nid](), M[nid].FUNCTION)(**base)
    return r["result"][0] if isinstance(r, dict) else r[0]


def old_cases():
    g = grid(6)
    out = {}
    out["aa_rand"] = old("PCG_AttribAdjust", geo=g, initialize="random", rand_seed=3)
    out["aa_noise"] = old("PCG_AttribAdjust", geo=g, initialize="noise", noise_type="worley")
    out["aa_stack"] = old("PCG_AttribAdjust", geo=g, attribute_name="Cd",
                          adjustments="mul 2\nadd noise(perlin, 0.7, 0.3)\nmix 1 mask=@mask",
                          use_remap=True)
    for nt in AN.NOISE_TYPES:
        out["an_" + nt] = old("PCG_AttribNoise", geo=g, attribute_names="P Cd", noise_type=nt)
    out["an_frac"] = old("PCG_AttribNoise", geo=g, fractal="terrain", operation="multiply",
                         range_values="one_centered", warp=0.3, blend=0.6, use_clamp_min=True)
    out["an_vec"] = old("PCG_AttribNoise", geo=g, noise_along_vector=True, fractal="hybrid_terrain",
                        use_value_correction=True, bias=0.3, use_normalize=True, operation="set")
    out["ar_val"] = old("PCG_AttribRandomize", geo=g, dimensions=3, combine="add")
    out["ar_gauss"] = old("PCG_AttribRandomize", geo=g, distribution="gaussian", combine="multiply",
                          id_attribute="id")
    out["ar_pow"] = old("PCG_AttribRandomize", geo=g, distribution="power", group="0-10")
    out["ar_dir"] = old("PCG_AttribRandomize", geo=g, name="N", mode="direction", shape="cone",
                        length_min=0.5, length_max=2.0)
    out["ar_ori"] = old("PCG_AttribRandomize", geo=g, name="orient", mode="orient", shape="disc")
    for mode in ("constant", "random", "random_by_attribute", "ramp_by_attribute", "adjust"):
        out["co_" + mode] = old("PCG_Color", geo=g, mode=mode, attribute="pscale", random_hue=30.0,
                                hue_shift=40.0, saturation=0.5)
    return {k: digest(v) for k, v in out.items()}


# digests from running old_cases() before the change (9e3fb92)
GOLDEN = {
    "aa_rand": "aa41253be276c7df",
    "aa_noise": "0ba436ecea0e6a39",
    "aa_stack": "ad9cc660dc94c1a9",
    "an_value": "7c9bf4bb55de4775",
    "an_perlin": "0227010ea1b8c9fe",
    "an_simplex": "11c484aa97475166",
    "an_worley": "97373e0741764e2a",
    "an_worley_f2f1": "b7bce0f48a5733f8",
    "an_frac": "a5bace1f7450e92a",
    "an_vec": "e21f9191ba2fc4dc",
    "ar_val": "1191aaa92e398b01",
    "ar_gauss": "77a4c0ee5621d3ec",
    "ar_pow": "8918417e0104322d",
    "ar_dir": "eeedbfcc2821d74a",
    "ar_ori": "3232c12c608e49d0",
    "co_constant": "495e151363867ffb",
    "co_random": "081ec2191fc7d526",
    "co_random_by_attribute": "429dc8c56631ed87",
    "co_ramp_by_attribute": "8d70560deb55c7f2",
    "co_adjust": "b05a5b3eea4d52ae",
}

if "--digests" in sys.argv:
    import json
    print(json.dumps(old_cases(), indent=1))
    sys.exit(0)


# ═══════════════════════════════════════════════════════════════ Regression
sec("Bit-identical to before the change at defaults")
now = old_cases()
check(f"output digests of all {len(GOLDEN)} old calls unchanged", len(GOLDEN) >= 20 and now == GOLDEN,
      {k: (GOLDEN.get(k), v) for k, v in now.items() if GOLDEN.get(k) != v})
P = np.random.default_rng(5).uniform(-3, 3, (500, 3))
check("noise library: the old five noises unchanged after adding the metric parameter (Euclidean = original formula)",
      np.array_equal(AN.worley(P, 3, "f1"), AN.worley(P, 3, "f1", "euclidean"))
      and np.array_equal(AN.noise(P, "worley_f2f1", 2), AN.worley(P, 2, "f2f1")))


# ═══════════════════════════════════════════════════════════════ Float
FL = "PCG_AttribAdjustFloat"
IN = "PCG_AttribAdjustInteger"
sec("Attribute Adjust Float:Operation")
g = grid()
n = g.npoints
k = np.arange(n, dtype=np.float64)
ops_ref = {"set_always": np.full(n, 4.0), "set_initial": k, "add": k + 4, "subtract": k - 4,
           "multiply": k * 4, "minimum": np.minimum(k, 4), "maximum": np.maximum(k, 4)}
for op, ref in ops_ref.items():
    o = A(run(FL, geo=g, operation=op, constant_value=4.0), "pscale")[:, 0]
    check(f"  {op}: original value = point number, Constant 4", np.allclose(o, ref), o[:6])
o = A(run(FL, geo=g, attribute_name="fresh", operation="set_initial", constant_value=4.0), "fresh")
check("  Set Initial: still writes when the attribute doesn't exist (docs: when it doesn't exist all operations behave the same)",
      np.allclose(o, 4.0) and run(FL, geo=g, attribute_name="fresh").get(POINT, "fresh").dtype == np.float32)
o = A(run(FL, geo=g, attribute_name="fresh", operation="multiply", constant_value=4.0), "fresh")
check("  Multiply on a nonexistent attribute = writes the adjustment value directly (not 0×4)", np.allclose(o, 4.0))
o = A(run(FL, geo=g, operation="add", constant_value=1.0, group="0-4"), "pscale")[:, 0]
check("  outside the group the original value is kept", np.allclose(o[:5], k[:5] + 1) and np.allclose(o[5:], k[5:]))
o = A(run(FL, geo=g, operation="add", constant_value=10.0, adjust_value=False,
          use_maximum=True, maximum=3.0), "pscale")[:, 0]
check("  Adjust Value off: only post-processing (Maximum 3)", np.allclose(o, np.minimum(k, 3)))
o = A(run(FL, geo=g, operation="add", constant_value=10.0, use_minimum=True, minimum=12.0,
          use_maximum=True, maximum=20.0), "pscale")[:, 0]
check("  Post-Process Minimum / Maximum", np.allclose(o, np.clip(k + 10, 12, 20)))

sec("Float:Blend")
o = A(run(FL, geo=g, constant_value=100.0, blend=0.25), "pscale")[:, 0]
check("  Blend 0.25: original + 0.25×(new − original)", np.allclose(o, k + 0.25 * (100 - k)))
m = A(g, "mask")[:, 0]
o = A(run(FL, geo=g, constant_value=100.0, blend=0.25, blend_mode="attribute",
          blend_attribute="mask"), "pscale")[:, 0]
check("  Use Attribute: blends per element by mask (the Blend constant has no effect)", np.allclose(o, k + m * (100 - k)))
g2 = g.copy()
g2.set(POINT, "mask", (m * 4 - 1)[:, None].astype(np.float32))
o = A(run(FL, geo=g2, constant_value=100.0, blend_mode="attribute", blend_attribute="mask"), "pscale")[:, 0]
check("  Blend attribute outside 0..1 is clamped", np.allclose(o, k + np.clip(m * 4 - 1, 0, 1) * (100 - k), atol=1e-4))
check("  Blend attribute doesn't exist → raises",
      raises(lambda: run(FL, geo=g, blend_mode="attribute", blend_attribute="nope"), KeyError))

sec("Float:Random × Range Values")
c = cloud()
kk = np.arange(c.npoints, dtype=np.float64)
u = _rand01(kk, 7, 401)
o = A(run(FL, geo=c, pattern_type="random", rand_seed=7, min_value=2.0, max_value=5.0), "pscale")[:, 0]
check("  Min/Max: = 2 + 3·u (u is _rand01(element number, seed, 401))", np.allclose(o, 2 + 3 * u, atol=1e-6))
o2 = A(run(FL, geo=c, pattern_type="random", rand_seed=7, range_values="min_range",
           min_value=2.0, range_length=3.0), "pscale")[:, 0]
check("  Min + Range Length 2 / 3 → the same [2, 5]", np.allclose(o2, o))
o3 = A(run(FL, geo=c, pattern_type="random", rand_seed=7, range_values="middle_range",
           middle_value=3.5, range_length=3.0), "pscale")[:, 0]
check("  Middle ± Range Length: 3.5 ± 1.5 (half width = half the length) → the same [2, 5]",
      np.allclose(o3, o, atol=1e-6), (o3.min(), o3.max()))
o4 = A(run(FL, geo=c, pattern_type="random", rand_seed=8, min_value=2.0, max_value=5.0), "pscale")[:, 0]
check("  different Seed gives a different result (negative control)", not np.allclose(o4, o))
gi = c.copy()
gi.set(POINT, "id", (np.arange(c.npoints)[::-1] * 7).astype(np.int32)[:, None])
o5 = A(run(FL, geo=gi, pattern_type="random", randomization_by="custom_attribute",
           custom_attribute="id"), "pscale")[:, 0]
check("  Randomization By = Custom Attribute: u taken by id",
      np.allclose(o5, _rand01(A(gi, "id")[:, 0], 0, 401), atol=1e-6)
      and not np.allclose(o5, A(run(FL, geo=gi, pattern_type="random"), "pscale")[:, 0]))
check("  Custom Attribute doesn't exist → raises",
      raises(lambda: run(FL, geo=c, pattern_type="random", randomization_by="custom_attribute",
                         custom_attribute="nope"), KeyError))

sec("Float:Specific Values")
o = A(run(FL, geo=c, pattern_type="random", range_values="specific", value_list="1\n2 w=3"),
      "pscale")[:, 0]
f2 = float(np.mean(o == 2))
check("  two groups 1 / 2, weights 1 : 3 → 2 takes about 75%", set(np.unique(o)) == {1.0, 2.0} and 0.72 < f2 < 0.78, f2)
o = A(run(FL, geo=c, pattern_type="random", range_values="specific", value_list="0-10:5; 20 w=1\n7 w=2"),
      "pscale")[:, 0]
fr = {v: float(np.mean(o == v)) for v in (0, 5, 10, 20, 7)}
check("  min-max: step expansion, split evenly within a group: {0,5,10,20} take 1/3 together, 1/12 each; 7 takes 2/3",
      set(np.unique(o)) == {0, 5, 10, 20, 7} and abs(fr[7] - 2 / 3) < 0.03
      and all(abs(fr[v] - 1 / 12) < 0.02 for v in (0, 5, 10, 20)), fr)
check("  parse_value_list: negative range -3--1 → -3 -2 -1; descending 4-0:2 → 4 2 0",
      AA2.parse_value_list("-3--1")[0][0].tolist() == [-3, -2, -1]
      and AA2.parse_value_list("4-0:2")[0][0].tolist() == [4, 2, 0])
check("  empty value table / non-numeric / all-zero weights / negative weights → raises",
      raises(lambda: AA2.parse_value_list("# x")) and raises(lambda: AA2.parse_value_list("a"))
      and raises(lambda: AA2.parse_value_list("1 w=0"))
      and raises(lambda: AA2.parse_value_list("1 w=-0.5\n2 w=3")))
check("  pick_specific: u on a cumulative weight boundary takes the next group (right-closed)",
      AA2.pick_specific(np.array([0.0, 0.2499, 0.25, 0.999]), [(np.array([1.0]), 1), (np.array([2.0]), 3)]).tolist()
      == [1.0, 1.0, 2.0, 2.0])

sec("Float:Distribution / Stepping")
o = A(run(FL, geo=c, pattern_type="random", value_distribution="uniform_remap",
          remap_ramp="0:1 1:1", min_value=2.0, max_value=5.0), "pscale")[:, 0]
check("  Remap Ramp constant 1 → all Max", np.allclose(o, 5.0))
o = A(run(FL, geo=c, pattern_type="random", value_distribution="uniform_remap",
          remap_ramp="0:1 1:0", rand_seed=7, min_value=2.0, max_value=5.0), "pscale")[:, 0]
check("  Remap Ramp reversed slope → 2 + 3·(1−u)", np.allclose(o, 2 + 3 * (1 - u), atol=1e-6))
o = A(run(FL, geo=c, pattern_type="random", use_stepping=True, step_size=0.25), "pscale")[:, 0]
cnt = {v: float(np.mean(np.isclose(o, v))) for v in (0, .25, .5, .75, 1)}
check("  Stepping 0.25 on [0,1]: only 0 .25 .5 .75 1, each of the five cells about 1/5 (endpoints not halved)",
      np.allclose(sum(cnt.values()), 1) and all(abs(x - 0.2) < 0.03 for x in cnt.values()), cnt)
o = A(run(FL, geo=c, pattern_type="random", use_stepping=True, step_size=0.4, min_value=1.0,
          max_value=2.0), "pscale")[:, 0]
check("  Stepping counts from Min: [1,2] step 0.4 → 1 1.4 1.8", np.allclose(np.unique(o), [1, 1.4, 1.8]))
o = A(run(FL, geo=c, pattern_type="random", use_stepping=True, step_size=0.1, min_value=0.0,
          max_value=0.3), "pscale")[:, 0]
check("  [0, 0.3] step 0.1: still 4 cells under floating-point error (0.3/0.1 = 2.999…)", len(np.unique(np.round(o, 9))) == 4)
o = A(run(FL, geo=c, pattern_type="random", use_stepping=False, step_size=0.4), "pscale")[:, 0]
check("  Stepping off: continuous values (negative control)", len(np.unique(o)) > 1000)

sec("Float:Uniform with Outliers")
og = run(FL, geo=c, pattern_type="random", value_distribution="uniform_outliers",
         outlier_percent=20.0, outlier_range=1.0, outlier_attribute="outlier")
o, fl = A(og, "pscale")[:, 0], A(og, "outlier")[:, 0] > 0
check("  20% fall into (1, 2], the rest in [0, 1]; Outlier Attribute matches the positions",
      0.17 < fl.mean() < 0.23 and np.all(o[fl] >= 1) and np.all(o[fl] <= 2)
      and np.all((o[~fl] >= 0) & (o[~fl] <= 1)) and og.get(POINT, "outlier").dtype == np.int32, fl.mean())
o = A(run(FL, geo=c, pattern_type="random", value_distribution="uniform_outliers",
          outlier_percent=20.0, outlier_range=1.0, outlier_extent="below_min",
          outlier_attribute="outlier"), "pscale")[:, 0]
check("  Below Min Value: outliers fall into [-1, 0]", np.all(o[fl] <= 0) and np.all(o[fl] >= -1))
o = A(run(FL, geo=c, pattern_type="random", value_distribution="uniform_outliers",
          outlier_percent=20.0, outlier_range=1.0, outlier_extent="both"), "pscale")[:, 0]
lo_, hi_ = np.mean(o[fl] < 0), np.mean(o[fl] > 1)
check("  Both: about half on each side", 0.4 < lo_ < 0.6 and abs(lo_ + hi_ - 1) < 1e-9, (lo_, hi_))
o = A(run(FL, geo=c, pattern_type="random", value_distribution="uniform_outliers",
          outlier_percent=20.0, outlier_range=3.0, outlier_range_mode="multiplicative",
          min_value=1.0, max_value=2.0), "pscale")[:, 0]
check("  Multiplicative 3 on [1,2]: extends outward by (3−1)×1 → (2, 4]",
      np.all(o[fl] > 2) and np.all(o[fl] <= 4) and o[fl].max() > 3.5)
o = A(run(FL, geo=c, pattern_type="random", value_distribution="uniform_outliers",
          outlier_percent=20.0, outlier_range=3.0, outlier_range_mode="additive",
          min_value=1.0, max_value=2.0), "pscale")[:, 0]
check("  Additive 3 on [1,2] → (2, 5]", np.all(o[fl] <= 5) and o[fl].max() > 4.5)
o = A(run(FL, geo=c, pattern_type="random", value_distribution="uniform_outliers",
          outlier_percent=20.0, outlier_range=0.5, outlier_range_mode="multiplicative",
          min_value=1.0, max_value=2.0), "pscale")[:, 0]
check("  Multiplicative < 1: extension width clamped to 0 (outliers stick to Max, they don't shrink back)", np.allclose(o[fl], 2.0))
o = A(run(FL, geo=c, pattern_type="random", value_distribution="uniform_outliers",
          outlier_percent=20.0, outlier_range=1.0, use_stepping=True, step_size=0.25), "pscale")[:, 0]
check("  Stepping also applies to outliers: all multiples of 0.25",
      np.allclose(o * 4, np.rint(o * 4)) and np.all(o[fl] >= 1) and len(np.unique(o[fl])) > 1)
o = A(run(FL, geo=c, pattern_type="random", value_distribution="uniform_outliers",
          outlier_percent=0.0, outlier_attribute="outlier"), "outlier")[:, 0]
check("  Outlier Percent 0: no outliers at all", not o.any())
o = A(run(FL, geo=c, pattern_type="random", value_distribution="uniform_outliers",
          outlier_percent=20.0, outlier_seed=9, outlier_attribute="outlier"), "outlier")[:, 0] > 0
check("  different Outlier Seed, a different set of outliers (negative control)", not np.array_equal(o, fl))

sec("Float:Attribute / Noise")
o = A(run(FL, geo=g, pattern_type="attribute", adjustment_attribute="mask", attribute_scale=3.0,
          attribute_offset=1.0), "pscale")[:, 0]
check("  Scale 3: mask × 3 (Offset has no effect)", np.allclose(o, m * 3))
o = A(run(FL, geo=g, pattern_type="attribute", adjustment_attribute="mask", attribute_scale=3.0,
          attribute_offset=1.0, attribute_adjustment="offset"), "pscale")[:, 0]
check("  Offset 1:mask + 1", np.allclose(o, m + 1))
o = A(run(FL, geo=g, pattern_type="attribute", adjustment_attribute="mask", attribute_scale=3.0,
          attribute_offset=1.0, attribute_adjustment="both", operation="add"), "pscale")[:, 0]
check("  Apply Both + Add: original + mask × 3 + 1", np.allclose(o, k + m * 3 + 1))
o = A(run(FL, geo=g, pattern_type="attribute", adjustment_attribute="v.z"), "pscale")[:, 0]
check("  adjustment attribute with component v.z → 2", np.allclose(o, 2.0))
check("  adjustment attribute doesn't exist → raises",
      raises(lambda: run(FL, geo=g, pattern_type="attribute", adjustment_attribute="zz"), KeyError))
Pc = A(c, "P")
ref = np.clip(0.5 * (AN.fractal_noise(Pc / np.array([2.0, 1.0, 1.0]), "perlin", "none", 3, 2, .5, 4) + 1), 0, 1)
o = A(run(FL, geo=c, pattern_type="noise", rand_seed=4, element_size=1.0, element_scale_x=2.0,
          min_value=-1.0, max_value=1.0), "pscale")[:, 0]
check("  Noise: u = (perlin(P / Element Size·Scale) + 1)/2, value = -1 + 2u", np.allclose(o, -1 + 2 * ref, atol=1e-6))
o_off = A(run(FL, geo=c, pattern_type="noise", rand_seed=4, element_size=1.5, element_scale_x=2.0,
              noise_offset_y=0.37, min_value=-1.0, max_value=1.0), "pscale")[:, 0]
ref2 = np.clip(0.5 * (AN.fractal_noise((Pc + [0, .37, 0]) / np.array([3.0, 1.5, 1.5]), "perlin", "none",
                                       3, 2, .5, 4) + 1), 0, 1)
check("  Element Size × Element Scale; Offset added before dividing by the size", np.allclose(o_off, -1 + 2 * ref2, atol=1e-6))
for ft, fr_ in (("standard", "standard"), ("terrain", "terrain"), ("hybrid", "hybrid_terrain")):
    o = A(run(FL, geo=c, pattern_type="noise", fractal_type=ft, max_octaves=4, lacunarity=2.5,
              roughness=0.6, noise_type="simplex"), "pscale")[:, 0]
    ref = np.clip(0.5 * (AN.fractal_noise(Pc, "simplex", fr_, 4, 2.5, .6, 0) + 1), 0, 1)
    check(f"  Fractal {ft} → attribnoise's {fr_}", np.allclose(o, ref, atol=1e-6))
outs = {nt: A(run(FL, geo=c, pattern_type="noise", noise_type=nt), "pscale")[:, 0]
        for nt in ("worley", "manhattan", "chebyshev", "worley_f2f1", "manhattan_f2f1", "chebyshev_f2f1")}
check("  Manhattan / Chebyshev Cellular and Worley all differ, values all in [0,1]",
      all(not np.allclose(outs[a], outs[b]) for a, b in
          (("worley", "manhattan"), ("worley", "chebyshev"), ("manhattan", "chebyshev"),
           ("worley_f2f1", "manhattan_f2f1"), ("worley_f2f1", "chebyshev_f2f1")))
      and all(v.min() >= 0 and v.max() <= 1 for v in outs.values()))
def worley_ref(Q, seed, metric):
    """Brute-force reference: feature points of the 27 neighbouring cells, nearest / second nearest under the given metric."""
    out1, out2 = [], []
    for q in Q:
        i = np.floor(q).astype(np.int64)
        ds = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    cc = (i + [dx, dy, dz])[None, :]
                    fp = cc[0] + np.array([AN._to01(AN._cell_hash(cc, seed, kq))[0] for kq in (1, 2, 3)])
                    d = q - fp
                    ds.append(np.abs(d).sum() if metric == "manhattan" else np.abs(d).max())
        ds = sorted(ds)
        out1.append(ds[0])
        out2.append(ds[1])
    return np.array(out1), np.array(out2)


Q = np.random.default_rng(3).uniform(-4, 4, (40, 3))
okm = True
for met, kf in (("manhattan", 0.70), ("chebyshev", 1.24)):
    d1, d2 = worley_ref(Q, 5, met)
    okm &= np.allclose(AN.worley(Q, 5, "f1", met), np.clip(1 - 2 * kf * d1, -1, 1))
    okm &= np.allclose(AN.worley(Q, 5, "f2f1", met), np.clip((d2 - d1) * kf * 2 - 1, -1, 1))
check("  Manhattan / Chebyshev F1, F2-F1 = brute-force reference (Σ|Δ| / max|Δ| × factor)", okm)
check("  menu token → worley(…, f1/f2f1, metric)",
      all(np.array_equal(AN.noise(Q, f"{mt}{suf}", 2), AN.worley(Q, 2, f or "f1", mt))
          for mt in ("manhattan", "chebyshev") for suf, f in (("", ""), ("_f2f1", "f2f1"))))
o = A(run(FL, geo=c, pattern_type="noise", range_values="specific", value_list="1\n2"), "pscale")[:, 0]
check("  Noise + Specific Values: only values from the table, in patches (neighbouring points mostly share a value)",
      set(np.unique(o)) == {1.0, 2.0})

sec("Float: component and length")
o = A(run(FL, geo=g, attribute_name="v.y", constant_value=7.0), "v")
check("  v.y: only y changes", np.allclose(o, [1, 7, 2]))
o = A(run(FL, geo=g, attribute_name="v[2]", operation="add", constant_value=1.0), "v")
check("  v[2] + 1", np.allclose(o, [1, 2, 3]))
o = A(run(FL, geo=g, attribute_name="v", constant_value=6.0), "v")
check("  vector attribute without a component = adjust length: (1,2,2)·2", np.allclose(o, [2, 4, 4]))
gz = g.copy()
gz.set(POINT, "v", np.zeros((n, 3), np.float32))
check("  zero vector stays zero when adjusting length", np.allclose(A(run(FL, geo=gz, attribute_name="v", constant_value=6.0), "v"), 0))
check("  component out of range → raises", raises(lambda: run(FL, geo=g, attribute_name="pscale.y")))
o = run(FL, geo=g, attribute_name="foo.z", constant_value=3.0)
check("  writing a component of a nonexistent attribute: created with 3 components, only z has a value", np.allclose(A(o, "foo"), [0, 0, 3]))
for cl in (PRIM, VERTEX, DETAIL):
    o = run(FL, geo=g, attribute_class=cl, attribute_name="q", constant_value=2.0)
    check(f"  Attribute Class = {cl}", o.get(cl, "q") is not None and np.allclose(A(o, "q", cl), 2))

sec("Attribute Adjust Integer")
o = run(IN, geo=c, attribute_name="k", pattern_type="random", min_value=1, max_value=9,
        use_stepping=True, step_size=2)
kv = A(o, "k")[:, 0]
cnt = {v: float(np.mean(kv == v)) for v in (1, 3, 5, 7, 9)}
check("  docs example: 1..9 step 2 → 1 3 5 7 9, about 1/5 each; created as int32",
      o.get(POINT, "k").dtype == np.int32 and abs(sum(cnt.values()) - 1) < 1e-9
      and all(abs(x - 0.2) < 0.03 for x in cnt.values()), cnt)
kv = A(run(IN, geo=c, attribute_name="k", pattern_type="random", min_value=0, max_value=3), "k")[:, 0]
check("  without Stepping: the four integers of [0,3] incl. both ends are equally likely",
      set(np.unique(kv)) == {0, 1, 2, 3} and all(abs(np.mean(kv == v) - .25) < .03 for v in range(4)))
kv = A(run(IN, geo=c, attribute_name="k", pattern_type="random", range_values="middle_range",
           middle_value=0, range_length=2), "k")[:, 0]
check("  Middle ± Range Length 0 / 2 → -1 0 1 (docs example)", set(np.unique(kv)) == {-1, 0, 1})
kv = A(run(IN, geo=c, attribute_name="k", pattern_type="random", range_values="middle_range",
           middle_value=0, range_length=3), "k")[:, 0]
check("  length 3: ±1.5 shrinks inward to -1..1", set(np.unique(kv)) == {-1, 0, 1})
og = run(IN, geo=c, attribute_name="k", pattern_type="random", min_value=0, max_value=3,
         value_distribution="uniform_outliers", outlier_percent=30.0, outlier_range=0,
         outlier_attribute="o")
kv, fl = A(og, "k")[:, 0], A(og, "o")[:, 0] > 0
check("  integer outliers leave the range by at least 1 (Outlier Range 0 also gives 4)", fl.any() and np.all(kv[fl] == 4))
kv = A(run(IN, geo=c, attribute_name="k", pattern_type="random", min_value=0, max_value=3,
           value_distribution="uniform_outliers", outlier_percent=30.0, outlier_range=0,
           outlier_extent="below_min"), "k")[:, 0]
check("  Below Min likewise → -1", np.all(kv[fl] == -1))
kv = A(run(IN, geo=g, attribute_name="pscale", operation="multiply", constant_value=3), "pscale")[:, 0]
check("  Multiply: the original pscale is float32, stays float32 (only int when newly created)",
      np.allclose(kv, k * 3) and run(IN, geo=g, attribute_name="pscale").get(POINT, "pscale").dtype == np.float32)
gi2 = g.copy()
gi2.set(POINT, "cnt", np.arange(n, dtype=np.int32)[:, None])
kv = A(run(IN, geo=gi2, attribute_name="cnt", pattern_type="attribute", adjustment_attribute="mask",
           attribute_scale=2.5, operation="add"), "cnt")[:, 0]
check("  Attribute × 2.5 added to an integer: result rounded", np.allclose(kv, np.rint(k + m * 2.5)))
kv = A(run(IN, geo=g, attribute_name="pscale", pattern_type="attribute", adjustment_attribute="mask",
           attribute_scale=2.5, operation="add"), "pscale")[:, 0]
check("  rounded on a float attribute too (the Integer node's result is always an integer)", np.allclose(kv, np.rint(k + m * 2.5)))
check("  Integer has no Blend parameter", "blend" not in M[IN].INPUT_TYPES()["required"])


# ═══════════════════════════════════════════════════════════════ Vector
VE = "PCG_AttribAdjustVector"


def vrun(**kw):
    return A(run(VE, **kw), kw.get("attribute_name", "v"))


def cv(x, y, z, p="constant_vector"):
    return {p + "_x": x, p + "_y": y, p + "_z": z}


sec("Attribute Adjust Vector:Direction & Length")
g = grid()
n = g.npoints
V = np.array([1.0, 2.0, 2.0])
for op, ref in (("set_always", [3, -1, 0.5]), ("set", [3, -1, 0.5]), ("set_initial", V),
                ("add", V + [3, -1, .5]), ("subtract", V - [3, -1, .5]),
                ("multiply", V * [3, -1, .5]), ("minimum", np.minimum(V, [3, -1, .5])),
                ("maximum", np.maximum(V, [3, -1, .5]))):
    check(f"  {op}:(1,2,2) ⊕ (3,-1,0.5)", np.allclose(vrun(geo=g, operation=op, **cv(3, -1, .5)), ref))
check("  Set Initial still writes on a nonexistent attribute",
      np.allclose(vrun(geo=g, attribute_name="w", operation="set_initial", **cv(3, -1, .5)), [3, -1, .5]))
o = vrun(geo=g, operation="add", group="0-4", **cv(1, 1, 1))
check("  outside the group the original value is kept", np.allclose(o[:5], V + 1) and np.allclose(o[5:], V))
kk = np.arange(n, dtype=np.float64)
U3 = np.stack([_rand01(kk, 0, 401 + 17 * c_) for c_ in range(3)], 1)
o = vrun(geo=g, adjust_with="random", vector_range="positive", amplitude=2.0, **cv(1, 2, 3, "amplitude_scale"))
check("  Random · Positive: u_c × Amplitude × Scale_c (three components independent)",
      np.allclose(o, U3 * 2 * [1, 2, 3], atol=1e-6) and not np.allclose(o[:, 0] / 2, o[:, 1] / 4))
o = vrun(geo=g, adjust_with="random", vector_range="zero_centered", amplitude=2.0)
check("  Zero Centered: (u − 0.5) × Amplitude (amplitude 2 → ±1)", np.allclose(o, (U3 - .5) * 2, atol=1e-6))
o = vrun(geo=g, adjust_with="random", vector_range="min_max", **cv(-1, 0, 2, "min_vector"),
         **cv(1, 4, 2, "max_vector"))
check("  Min/Max per component", np.allclose(o, [-1, 0, 2] + U3 * [2, 4, 0], atol=1e-6))
o = vrun(geo=cloud(2000), adjust_with="random", vector_range="specific", vector_list="1 0 0\n0 0 1 w=3")
fz = float(np.mean(np.all(np.isclose(o, [0, 0, 1]), 1)))
check("  Specific Values: one vector per line, weights 1 : 3", 0.71 < fz < 0.79 and
      np.all(np.isclose(o, [1, 0, 0]).all(1) | np.isclose(o, [0, 0, 1]).all(1)), fz)
check("  a vector table line without 3 numbers → raises",
      raises(lambda: vrun(geo=g, adjust_with="random", vector_range="specific", vector_list="1 0")))
c = cloud(500)
ns = AA2.NoiseSpec()
o = vrun(geo=c, attribute_name="w", adjust_with="noise", vector_range="positive")
check("  Noise: one noise field per component (salt 0 / 7919 / 15838)",
      all(np.allclose(o[:, i], ns.u(c, POINT, 0, 7919 * i), atol=1e-6) for i in range(3))
      and not np.allclose(o[:, 0], o[:, 1]))
ga = g.copy()
ga.set(POINT, "adj", np.tile([[0.0, 5.0, 0.0]], (n, 1)).astype(np.float32))
check("  Length Only + Attribute (single-component mask)", np.allclose(
    vrun(geo=g, adjustment_for="length_only", operation="add", adjust_with="attribute",
         adjustment_attribute="mask"), V / 3 * (3 + A(g, "mask"))))
check("  Attribute: a vector attribute used directly as the adjustment value",
      np.allclose(vrun(geo=ga, adjust_with="attribute", adjustment_attribute="adj", operation="add"), V + [0, 5, 0]))

sec("Vector:Length Only")
for op, L in (("add", 4.0), ("subtract", 2.0), ("multiply", 3.0), ("minimum", 1.0), ("maximum", 3.0)):
    o = vrun(geo=g, adjustment_for="length_only", operation=op, scalar_value=1.0)
    check(f"  {op} 1: length 3 → {L}, direction unchanged", np.allclose(o, V / 3 * L))
gz = g.copy()
gz.set(POINT, "v", np.zeros((n, 3), np.float32))
check("  zero vector stays zero", np.allclose(vrun(geo=gz, adjustment_for="length_only", operation="add"), 0))
o = vrun(geo=c, attribute_name="w", operation="set_always", **cv(1, 0, 0))
c2 = run(VE, geo=c, attribute_name="w", operation="set_always", **cv(1, 0, 0))
o = A(run(VE, geo=c2, attribute_name="w", adjustment_for="length_only", operation="multiply",
          adjust_with="random", min_value=2.0, max_value=4.0), "w")
check("  Random length: uses the Float set of Range Values (u with the same salt 401)",
      np.allclose(o[:, 0], 2 + 2 * _rand01(np.arange(500.0), 0, 401), atol=1e-6))
check("  Length Only with Set Always → raises (docs: Set is only for Direction & Length)",
      raises(lambda: vrun(geo=g, adjustment_for="length_only", operation="set_always")))
check("  Direction & Length with Rotate → raises",
      raises(lambda: vrun(geo=g, operation="rotate")))
check("  Direction Only with Multiply → raises",
      raises(lambda: vrun(geo=g, adjustment_for="direction_only", operation="multiply")))
check("  combination not checked when Adjust Value is off", np.allclose(vrun(geo=g, adjust_value=False, operation="rotate"), V))

sec("Vector:Direction Only")
o = vrun(geo=g, adjustment_for="direction_only", operation="add", **cv(0, 0, -10))
check("  Add (0,0,-10): direction = (1,2,-8) normalized, length still 3", np.allclose(o, np.array([1, 2, -8]) / np.sqrt(69) * 3))
o = vrun(geo=g, adjustment_for="direction_only", operation="subtract", **cv(0, 0, 10))
check("  Subtract likewise", np.allclose(o, np.array([1, 2, -8]) / np.sqrt(69) * 3))
check("  zero vector stays zero",
      np.allclose(vrun(geo=gz, adjustment_for="direction_only", operation="add", **cv(1, 0, 0)), 0))
gx = g.copy()
gx.set(POINT, "v", np.tile([[2.0, 0.0, 0.0]], (n, 1)).astype(np.float32))
o = vrun(geo=gx, adjustment_for="direction_only", operation="rotate", scalar_value=90.0)
check("  Rotate 90° about +Y: (2,0,0) → (0,0,-2)", np.allclose(o, [0, 0, -2], atol=1e-9))
gx.set(POINT, "up", np.tile([[0.0, 0.0, 1.0]], (n, 1)).astype(np.float32))
o = vrun(geo=gx, adjustment_for="direction_only", operation="rotate", scalar_value=90.0, axis_from="attribute")
check("  Axis of Rotation = From Attribute(up = +Z):(2,0,0) → (0,2,0)", np.allclose(o, [0, 2, 0], atol=1e-9))
o = vrun(geo=gx, adjustment_for="direction_only", operation="spread", scalar_value=30.0)
ang = np.degrees(np.arccos(np.clip(o[:, 0] / np.linalg.norm(o, axis=1), -1, 1)))
az = np.arctan2(o[:, 2], o[:, 1])
check("  Spread 30°: 30° from the original direction, length unchanged, azimuths all different",
      np.allclose(ang, 30) and np.allclose(np.linalg.norm(o, axis=1), 2) and np.std(az) > 0.5)
o2 = vrun(geo=gx, adjustment_for="direction_only", operation="spread", scalar_value=30.0, rand_seed=3)
check("  Spread with a different Seed changes the azimuths (negative control)", not np.allclose(o, o2))
o = vrun(geo=gx, adjustment_for="direction_only", operation="interpolate", scalar_value=0.5)
check("  Interpolate 0.5 toward +Y: (1,1,0)/√2 × 2", np.allclose(o, np.array([1, 1, 0]) / np.sqrt(2) * 2))
o = vrun(geo=gx, adjustment_for="direction_only", operation="interpolate", scalar_value=1.0 / 3)
check("  Interpolate 1/3 is spherical interpolation (30°), not linear", np.allclose(o, [2 * np.cos(np.pi / 6), 2 * np.sin(np.pi / 6), 0]))
o = vrun(geo=gx, adjustment_for="direction_only", operation="interpolate", scalar_value=2.0)
check("  Bias clamped to 1", np.allclose(o, [0, 2, 0]))
gx.set(POINT, "N", np.tile([[0.0, 0.0, -1.0]], (n, 1)).astype(np.float32))
o = vrun(geo=gx, adjustment_for="direction_only", operation="interpolate", scalar_value=1.0, goal_from="attribute")
check("  Goal Direction = From Attribute(N)", np.allclose(o, [0, 0, -2]))
check("  slerp: opposite directions degrade to linear then normalize (0.7x − 0.3x → x), no nan",
      np.allclose(AA2.slerp_dirs(np.array([[1.0, 0, 0]]), np.array([[-1.0, 0, 0]]), [0.3]), [[1, 0, 0]]))
o = vrun(geo=g, adjustment_for="direction_only", operation="rotate", scalar_value=90.0)
check("  Rotate 90° about +Y: (1,2,2) → (2,2,-1) (the component along the axis is kept)", np.allclose(o, [2, 2, -1]))
gi3 = gx.copy()
gi3.set(POINT, "id", np.arange(n, dtype=np.int32)[::-1, None].copy())
o3 = vrun(geo=gi3, adjustment_for="direction_only", operation="spread", scalar_value=30.0,
          randomization_by="custom_attribute", custom_attribute="id")
o4 = vrun(geo=gx, adjustment_for="direction_only", operation="spread", scalar_value=30.0)
check("  Spread azimuths also honour Randomization By (id reversed → result reversed)", np.allclose(o3, o4[::-1]))

sec("Vector:Pre-Process")
o = vrun(geo=g, enable_preprocess=True, overwrite_initial=True, operation="add", **cv(1, 0, 0),
         **cv(0, 0, 5, "initial_vector"))
check("  Overwrite Initial = Constant, then Add", np.allclose(o, [1, 0, 5]))
o = vrun(geo=g, enable_preprocess=False, overwrite_initial=True, operation="add", **cv(1, 0, 0),
         **cv(0, 0, 5, "initial_vector"))
check("  Enable Pre-Process off: Overwrite has no effect (negative control)", np.allclose(o, V + [1, 0, 0]))
o = vrun(geo=g, attribute_name="w", enable_preprocess=True, overwrite_initial=True, initial_from="normal",
         operation="set_initial", **cv(5, 5, 5))
check("  Initial = Normal Attribute (grid normal +Y); Set Initial no longer overrides it", np.allclose(o, [0, 1, 0]))
o = vrun(geo=g, attribute_name="w", enable_preprocess=True, overwrite_initial=True, initial_from="attribute",
         initial_attribute="Cd", adjust_value=False)
check("  Initial = Vector Attribute(Cd)", np.allclose(o, A(g, "Cd")))
o = vrun(geo=g, enable_preprocess=True, reverse_direction=True, pre_unit_length=True,
         use_pre_length_scale=True, pre_length_scale=6.0, adjust_value=False)
check("  Reverse + Unit + Length Scale 6:(-2,-4,-4)", np.allclose(o, [-2, -4, -4]))

sec("Vector:Post-Process")
o = vrun(geo=gx, operation="set_always", **cv(0, 2, 0), blend=0.5)
check("  Blend Linear 0.5:(1,1,0)", np.allclose(o, [1, 1, 0]))
o = vrun(geo=gx, operation="set_always", **cv(0, 2, 0), blend=0.5, blend_type="spherical")
check("  Blend Spherical 0.5: direction 45°, length 2", np.allclose(o, np.array([1, 1, 0]) / np.sqrt(2) * 2))
o = vrun(geo=gx, operation="set_always", **cv(0, 4, 0), blend=0.5, blend_type="spherical")
check("  Spherical length interpolated linearly: halfway from 2 → 4 is 3", np.allclose(np.linalg.norm(o, axis=1), 3))
o = vrun(geo=gx, operation="set_always", **cv(0, 0, 0), blend=0.5, blend_type="spherical")
check("  Spherical with a zero vector at one end: falls back to linear", np.allclose(o, [1, 0, 0]))
o = vrun(geo=g, blend_mode="attribute", blend_attribute="mask", operation="set_always", **cv(0, 0, 0))
check("  Blend Attribute", np.allclose(o, V * (1 - A(g, "mask"))))
o = vrun(geo=g, adjust_value=False, use_post_length_scale=True, post_length_scale=2.0)
check("  Length Scale 2", np.allclose(o, V * 2))
o = vrun(geo=g, adjust_value=False, use_min_length=True, min_length=6.0)
check("  Minimum Length 6", np.allclose(o, V * 2))
o = vrun(geo=g, adjust_value=False, use_max_length=True, max_length=1.5)
check("  Maximum Length 1.5", np.allclose(o, V / 2))
o = vrun(geo=g, adjust_value=False, use_min_length=True, min_length=1.0, use_max_length=True, max_length=1.5)
check("  Min 1 + Max 1.5 both on (Max wins)", np.allclose(o, V / 2))
check("  Minimum Length keeps zero vectors zero",
      np.allclose(vrun(geo=gz, adjust_value=False, use_min_length=True, min_length=1.0), 0))
o = run(VE, geo=g, adjust_value=False, post_unit_length=True, length_attribute="len")
check("  Make Vectors Unit Length + Length attribute", np.allclose(A(o, "v"), V / 3) and np.allclose(A(o, "len"), 1))
check("  Length attribute left empty is not written", run(VE, geo=g).get(POINT, "") is None and "len" not in run(VE, geo=g).attribs[POINT])
check("  attribute without three components → raises", raises(lambda: vrun(geo=g, attribute_name="pscale")))


# ═══════════════════════════════════════════════════════════════ Color
CO = "PCG_AttribAdjustColor"


def crun(**kw):
    return A(run(CO, **kw), kw.get("attribute_name", "Cd"))


def rgb(p, r, g_, b):
    return {p + "_r": r, p + "_g": g_, p + "_b": b}


def hsv2rgb(h, s_, v):
    import colorsys
    return np.array(colorsys.hsv_to_rgb(h % 1.0, s_, v))


sec("Attribute Adjust Color:Operation")
g = grid()
n = g.npoints
a0 = A(g, "Cd")
b0 = np.array([0.25, 0.5, 0.75])
refs = {"set_always": np.tile(b0, (n, 1)), "set_initial": a0, "add": a0 + b0, "subtract": a0 - b0,
        "multiply": a0 * b0, "screen": 1 - (1 - a0) * (1 - b0),
        "overlay": np.where(a0 < .5, 2 * a0 * b0, 1 - 2 * (1 - a0) * (1 - b0)),
        "hard_mix": (a0 + b0 >= 1).astype(float), "difference": b0 - a0,
        "minimum": np.minimum(a0, b0), "maximum": np.maximum(a0, b0)}
for op, ref in refs.items():
    check(f"  {op}", np.allclose(crun(geo=g, operation=op, **rgb("color", *b0)), ref, atol=1e-6))
check("  both Overlay branches occur (original colors have both <0.5 and ≥0.5)", (a0 < .5).any() and (a0 >= .5).any())
check("  Hard Mix produces both 0 and 1", set(np.unique(refs["hard_mix"])) == {0.0, 1.0})
check("  when the attribute doesn't exist, Screen / Overlay also write the adjustment color directly",
      np.allclose(crun(geo=g, attribute_name="C2", operation="screen", **rgb("color", *b0)), b0)
      and np.allclose(crun(geo=g, attribute_name="C2", operation="overlay", **rgb("color", *b0)), b0))
o = crun(geo=g, operation="add", group="0-4", **rgb("color", *b0))
check("  outside the group the original value is kept", np.allclose(o[:5], a0[:5] + b0) and np.allclose(o[5:], a0[5:]))

sec("Color:Random / Noise × Range Values")
kk = np.arange(n, dtype=np.float64)
U3 = np.stack([_rand01(kk, 0, 401 + 17 * c_) for c_ in range(3)], 1)
o = crun(geo=g, pattern_type="random", **rgb("min_color", .2, 0, .5), **rgb("max_color", .4, 1, .5))
check("  Min/Max RGB: per channel lo + (hi−lo)·u_c", np.allclose(o, [.2, 0, .5] + U3 * [.2, 1, 0], atol=1e-6))
o = crun(geo=g, pattern_type="random", color_space="hsv", **rgb("min_color", 0, 1, 1), **rgb("max_color", 1, 1, 1))
check("  Min/Max HSV: interpolated in HSV (fully saturated → each color's max channel 1, min channel 0)",
      np.allclose(o.max(1), 1) and np.allclose(o.min(1), 0)
      and np.allclose(o, np.stack([hsv2rgb(u_, 1, 1) for u_ in U3[:, 0]]), atol=1e-6))
o = crun(geo=g, pattern_type="random", range_values="color_ramp", color_ramp="0:1,0,0 1:0,0,1")
check("  Color Ramp: red → blue, taken by u_0", np.allclose(o, np.stack([1 - U3[:, 0], 0 * U3[:, 0], U3[:, 0]], 1), atol=1e-6))
c = cloud(3000)
o = crun(geo=c, attribute_name="C", pattern_type="random", range_values="specific",
         color_list="1 0 0\n0 0 1 w=3")
fb = float(np.mean(np.isclose(o, [0, 0, 1]).all(1)))
check("  Specific Colors (Custom list) weights 1 : 3", 0.71 < fb < 0.79, fb)
check("  a color table line without 3 numbers → raises",
      raises(lambda: crun(geo=g, pattern_type="random", range_values="specific", color_list="1 0")))
SC = {"constant": [[1, 0, 0]], "complementary": [[1, 0, 0], [0, 1, 1]],
      "analogous2": [hsv2rgb(-1 / 12, 1, 1), [1, 0, 0], hsv2rgb(1 / 12, 1, 1)],
      "analogous4": [hsv2rgb(k_ / 12, 1, 1) for k_ in (-2, -1, 0, 1, 2)],
      "triadic": [[0, 0, 1], [1, 0, 0], [0, 1, 0]],
      "tetradic": [[1, 0, 0], hsv2rgb(1 / 12, 1, 1), [0, 1, 1], hsv2rgb(.5 + 1 / 12, 1, 1)],
      "shades5": [[f_, 0, 0] for f_ in (1, .8, .6, .4, .2)],
      "tints5": [[1, 1 - f_, 1 - f_] for f_ in (1, .8, .6, .4, .2)]}
for sch, ref in SC.items():
    got = AA2.color_scheme(sch, (1, 0, 0), 30.0)
    check(f"  Color Scheme {sch} (base pure red, Distance 30°)", np.allclose(got, np.array(ref, float), atol=1e-9))
o = crun(geo=c, attribute_name="C", pattern_type="random", range_values="specific", color_scheme="complementary")
check("  Complementary chosen in the node: only red and cyan, about half each",
      np.all(np.isclose(o, [1, 0, 0]).all(1) | np.isclose(o, [0, 1, 1]).all(1))
      and 0.45 < np.mean(np.isclose(o, [1, 0, 0]).all(1)) < 0.55)
ns = AA2.NoiseSpec()
o = crun(geo=c, attribute_name="C", pattern_type="noise")
check("  Noise: one noise field per channel (salt 0 / 7919 / 15838)",
      all(np.allclose(o[:, i], ns.u(c, POINT, 0, 7919 * i), atol=1e-6) for i in range(3)))

sec("Color:Attribute / Remap / Bounding Box")
o = crun(geo=g, attribute_name="C2", pattern_type="color_attribute", adjustment_attribute="Cd")
check("  Color Attribute", np.allclose(o, a0))
o = crun(geo=g, attribute_name="C2", pattern_type="color_attribute", adjustment_attribute="mask")
check("  single-channel attribute spread into gray", np.allclose(o, np.repeat(A(g, "mask"), 3, 1)))
ps = A(g, "pscale")[:, 0]
o = crun(geo=g, pattern_type="remap_attribute", source_attribute="pscale", color_ramp="0:0,0,0 1:1,0.5,0")
t = ps / ps.max()
check("  Remap Attribute: Compute Range = measured min/max, then through the ramp", np.allclose(o, np.stack([t, t / 2, 0 * t], 1)))
o = crun(geo=g, pattern_type="remap_attribute", source_attribute="pscale", compute_range=False,
         source_min=0.0, source_max=10.0)
check("  manual Source Range 0..10 (values beyond clamp to 1)", np.allclose(o[:, 0], np.clip(ps / 10, 0, 1)))
o = crun(geo=g, pattern_type="remap_attribute", source_attribute="pscale", group="0-9")
check("  Compute Range looks only at elements in the group (0..9 → 9 is 1)", np.isclose(o[9, 0], 1) and np.isclose(o[4, 0], 4 / 9))
x = A(g, "P")[:, 0]
o = crun(geo=g, pattern_type="bounding_box", **{"bbox_direction_x": 2.0, "bbox_direction_y": 0.0})
check("  Bounding Box along +X: t = (x − min)/(max − min)", np.allclose(o[:, 0], (x - x.min()) / np.ptp(x)))
o = crun(geo=g, pattern_type="bounding_box", **{"bbox_direction_x": -1.0, "bbox_direction_y": 0.0})
check("  reversed direction → gradient reversed", np.allclose(o[:, 0], (x.max() - x) / np.ptp(x)))
o = crun(geo=g, pattern_type="remap_attribute", source_attribute="pscale", group="3",
         color_ramp="0:0.2,0.2,0.2 1:1,1,1")
check("  zero-width range (only one element in the group): takes the left end of the ramp, no nan", np.allclose(o[3], .2))
check("  Source Attribute doesn't exist → raises",
      raises(lambda: crun(geo=g, pattern_type="remap_attribute", source_attribute="zz"), KeyError))

sec("Color:Color Correction")
red = {"pattern_type": "constant", **rgb("color", 1, 0, 0)}
check("  all defaults: no bits changed (no HSV round trip)", np.array_equal(AA2.color_correct(a0), a0))
check("  Hue Shift 120: red → green", np.allclose(crun(geo=g, hue_shift=120.0, **red), [0, 1, 0]))
check("  Saturation 0: red → white (value 1)", np.allclose(crun(geo=g, saturation=0.0, **red), [1, 1, 1]))
check("  Saturation boosted then clamped to 1: (1,.6,.6) × 3 → pure red (no negatives)",
      np.allclose(crun(geo=g, saturation=3.0, **rgb("color", 1, .6, .6)), [1, 0, 0]))
check("  Value 0.5 then Brightness +0.25: value 0.75 (multiply first, then add)",
      np.allclose(crun(geo=g, value=0.5, brightness=0.25, **red), [.75, 0, 0]))
check("  Value 0.5: red → dark red", np.allclose(crun(geo=g, value=0.5, **red), [.5, 0, 0]))
check("  Brightness −0.25 added to the value", np.allclose(crun(geo=g, brightness=-0.25, **red), [.75, 0, 0]))
check("  Gain 0.5:RGB × 0.5", np.allclose(crun(geo=g, gain=0.5, **rgb("color", .2, .4, .6)), [.1, .2, .3]))
check("  Contrast 2:(c − 0.5)·2 + 0.5", np.allclose(crun(geo=g, contrast=2.0, **rgb("color", .2, .4, .6)),
                                                     [-.1, .3, .7]))
check("  Gamma 2: c^(1/2) (brighter)", np.allclose(crun(geo=g, gamma=2.0, **rgb("color", .25, .04, 1)), [.5, .2, 1]))
check("  correction still applied when Adjust Value is off", np.allclose(crun(geo=g, adjust_value=False, gain=2.0), a0 * 2))

sec("Color: Pre / Post-Process, Blend")
check("  Minimum / Maximum clamp", np.allclose(crun(geo=g, use_minimum=True, minimum=.3, use_maximum=True,
                                                   maximum=.6, **rgb("color", .1, .5, .9)), [.3, .5, .6]))
check("  Complement:1 − c", np.allclose(crun(geo=g, complement=True, **rgb("color", .1, .5, .9)), [.9, .5, .1]))
check("  Blend 0.5: half and half with the input (the correction gets blended too)",
      np.allclose(crun(geo=g, blend=0.5, gain=2.0, **rgb("color", .1, .5, .9)), (a0 + [.2, 1, 1.8]) / 2))
m = A(g, "mask")
check("  Blend Attribute", np.allclose(crun(geo=g, blend_mode="attribute", blend_attribute="mask",
                                             **rgb("color", 0, 0, 0)), a0 * (1 - m)))
o = crun(geo=g, overwrite_initial=True, operation="multiply", **rgb("initial_color", .5, .5, .5),
         **rgb("color", .2, .4, 1))
check("  Overwrite Initial = Constant, then Multiply", np.allclose(o, [.1, .2, .5]))
o = crun(geo=g, attribute_name="C2", overwrite_initial=True, initial_from="color_attribute",
         initial_attribute="Cd", operation="set_initial", **rgb("color", .2, .4, 1))
check("  Initial = Color Attribute; once the initial value is written, Set Initial no longer overrides", np.allclose(o, a0))
o = crun(geo=g, attribute_name="C2", overwrite_initial=True, initial_from="float_attribute",
         initial_attribute="mask", adjust_value=False)
check("  Initial = Float Attribute (spread into gray)", np.allclose(o, np.repeat(m, 3, 1)))
o = crun(geo=g, attribute_name="C2", overwrite_initial=True, initial_from="float_attribute",
         initial_attribute="v", adjust_value=False)
check("  Float Attribute given a vector attribute: takes the first component", np.allclose(o, 1.0))
o = crun(geo=g, overwrite_initial=True, **rgb("initial_color", .5, .5, .5), blend=0.0)
check("  Blend 0: back to the **input** (not even Overwrite Initial counts)", np.allclose(o, a0))
gp = g.copy()
gp.set(PRIM, "Cd", np.ones((g.nprims, 3), np.float32))
o = run(CO, geo=gp, delete_other_colors=True)
o2 = run(CO, geo=gp)
check("  Delete All Existing Color Attributes: Cd on prims deleted; kept when off (negative control)",
      o.get(PRIM, "Cd") is None and o2.get(PRIM, "Cd") is not None)
check("  attribute without three components → raises", raises(lambda: crun(geo=g, attribute_name="pscale")))
for cl in (PRIM, VERTEX, DETAIL):
    o = run(CO, geo=g, attribute_class=cl, attribute_name="Cq", **rgb("color", .1, .2, .3))
    check(f"  Attribute Class = {cl}", np.allclose(A(o, "Cq", cl), [.1, .2, .3]))


# ═══════════════════════════════════════════════════════════════ Randomize
RA = "PCG_AttribRandomize"
sec("Attribute Randomize: appended Distribution / Operation / Global Scale")
c = cloud(4000)
N_ = c.npoints
kk = np.arange(N_, dtype=np.float64)
u = _rand01(kk, 0, 101)


def rr(**kw):
    return A(run(RA, geo=c, name="r", **kw), "r")[:, 0]


check("  Constant Value: all Min (= Value)", np.allclose(rr(distribution="constant", min_x=2.5), 2.5))
o = rr(distribution="two_values", min_x=1.0, max_x=7.0, prob_b=0.3)
check("  Two Values: only A / B, the B fraction = Probability of Value B",
      set(np.unique(o)) == {1.0, 7.0} and abs(np.mean(o == 7) - 0.3) < 0.03 and np.allclose(o == 7, u < 0.3))
o = rr(distribution="uniform_discrete", min_x=1.0, max_x=2.0, step_size=0.25)
check("  Uniform (Discrete): 1..2 step 0.25 incl. both ends, five cells equally likely",
      np.allclose(np.unique(o), [1, 1.25, 1.5, 1.75, 2])
      and all(abs(np.mean(np.isclose(o, v)) - .2) < .03 for v in (1, 1.25, 1.5, 1.75, 2)))
o = rr(distribution="uniform_discrete", min_x=0.0, max_x=0.3, step_size=0.1)
check("  Uniform (Discrete) 0..0.3 step 0.1: still 4 cells under floating-point error", len(np.unique(np.round(o, 9))) == 4)
check("  Step Size 0 → raises (ValueError, with a clear reason)", raises(lambda: rr(distribution="uniform_discrete", step_size=0.0), ValueError))
o = rr(distribution="exponential", mean=2.0)
check("  Exponential: median = Middle Value, mean = median / ln2, all positive",
      np.allclose(o, -np.log1p(-u) * 2 / np.log(2)) and abs(np.median(o) - 2) < 0.15
      and abs(o.mean() - 2 / np.log(2)) < 0.15 and o.min() >= 0)
o = rr(distribution="lognormal", mean=3.0, stddev=0.5)
check("  Log-Normal: median 3, std of log 0.5, all positive",
      o.min() > 0 and abs(np.median(o) - 3) < 0.1 and abs(np.std(np.log(o)) - 0.5) < 0.03)
check("  Log-Normal median ≤ 0 → raises", raises(lambda: rr(distribution="lognormal", mean=0.0)))
o = rr(distribution="cauchy", mean=1.0, stddev=0.5)
q1, q3 = np.percentile(o, [25, 75])
check("  Cauchy-Lorentz: median 1, quartiles = 1 ± γ (γ = 0.5)",
      np.allclose(o, 1 + 0.5 * np.tan(np.pi * (u - 0.5))) and abs(q1 - 0.5) < 0.06 and abs(q3 - 1.5) < 0.06)
o = rr(distribution="custom_discrete", value_list="1\n5 6 w=3")
check("  Custom Discrete: groups by weight, split evenly within a group (1 takes 1/4, 5 and 6 3/8 each)",
      set(np.unique(o)) == {1, 5, 6} and abs(np.mean(o == 1) - .25) < .03 and abs(np.mean(o == 5) - .375) < .03)
o3 = A(run(RA, geo=c, name="s", distribution="inside_sphere", dimensions=3), "s")
r3 = np.linalg.norm(o3, axis=1)
check("  Inside Sphere (3D): all inside the unit sphere, radius³ uniform (uniform in volume), direction unbiased",
      r3.max() <= 1 + 1e-9 and abs(np.mean(r3 ** 3) - 0.5) < 0.03 and np.all(np.abs(o3.mean(0)) < 0.05))
o2 = A(run(RA, geo=c, name="s", distribution="inside_sphere", dimensions=2), "s")
check("  Inside Sphere (2D): inside the unit disc, r² uniform", np.linalg.norm(o2, axis=1).max() <= 1 + 1e-9
      and abs(np.mean(np.linalg.norm(o2, axis=1) ** 2) - 0.5) < 0.03)
g = grid()
ps = A(g, "pscale")[:, 0]
o = A(run(RA, geo=g, combine="minimum", min_x=3.0, max_x=3.0), "pscale")[:, 0]
check("  Operation Minimum: min(original, 3)", np.allclose(o, np.minimum(ps, 3)))
o = A(run(RA, geo=g, combine="maximum", min_x=3.0, max_x=3.0), "pscale")[:, 0]
check("  Operation Maximum: max(original, 3)", np.allclose(o, np.maximum(ps, 3)))
o = A(run(RA, geo=g, name="fresh", combine="minimum", min_x=3.0, max_x=3.0), "fresh")[:, 0]
check("  Minimum on a nonexistent attribute: takes the generated value directly (not compared with 0)", np.allclose(o, 3))
o = A(run(RA, geo=g, combine="add", min_x=1.0, max_x=1.0, global_scale=2.5), "pscale")[:, 0]
check("  Global Scale multiplied before Operation: original + 1×2.5", np.allclose(o, ps + 2.5))
o = A(run(RA, geo=g, name="N", mode="direction", global_scale=3.0), "N")
check("  Global Scale on direction: length × 3", np.allclose(np.linalg.norm(o, axis=1), 3))
o = A(run(RA, geo=g, name="orient", mode="orient", global_scale=3.0), "orient")
check("  Global Scale doesn't multiply orient (quaternions stay unit length)", np.allclose(np.linalg.norm(o, axis=1), 1, atol=1e-6))


# ═══════════════════════════════════════════════════════════════ Attribute Noise
NO = "PCG_AttribNoise"
sec("Attribute Noise: appended Range Values / Operation / correction / post-processing")
g = grid(9)
c = cloud(800)


def nz(geo=c, nm="h", **kw):
    return A(run(NO, geo=geo, attribute_names=nm, **kw), nm)


raw = nz(operation="set", amplitude=1.0)[:, 0]            # zero_centered × 1 = raw [-1,1]
t01 = 0.5 * (raw + 1)
check("  reference: raw values in [-1,1] and varying", raw.min() >= -1 and raw.max() <= 1 and np.ptp(raw) > 0.5)
check("  Negative:−Amp·(v+1)/2 ∈ [−Amp, 0]",
      np.allclose(nz(operation="set", range_values="negative", amplitude=2.0)[:, 0], -2 * t01, atol=1e-6))
check("  Min/Max 2..5", np.allclose(nz(operation="set", range_values="min_max", min_value=2.0, max_value=5.0)[:, 0],
                                    2 + 3 * t01, atol=1e-6))
check("  Min + Range Length 2 / 3 → 2..5",
      np.allclose(nz(operation="set", range_values="min_range", min_value=2.0, range_length=3.0)[:, 0],
                  2 + 3 * t01, atol=1e-6))
check("  Middle ± Range Length 3.5 / 1.5 → 2..5 (full width, not Adjust's half width)",
      np.allclose(nz(operation="set", range_values="middle_range", middle_value=3.5, range_length=1.5)[:, 0],
                  2 + 3 * t01, atol=1e-6))
gh = c.copy()
gh.set(POINT, "h", np.full((c.npoints, 1), 0.1, np.float32))
check("  Set Initial: attribute already exists → untouched", np.allclose(nz(geo=gh, operation="set_initial")[:, 0], 0.1))
check("  Set Initial: attribute doesn't exist → writes noise", np.allclose(nz(operation="set_initial", amplitude=1.0)[:, 0], raw, atol=1e-6))
check("  Minimum / Maximum compared with the original 0.1",
      np.allclose(nz(geo=gh, operation="minimum", amplitude=1.0)[:, 0], np.minimum(raw, .1), atol=1e-6)
      and np.allclose(nz(geo=gh, operation="maximum", amplitude=1.0)[:, 0], np.maximum(raw, .1), atol=1e-6))
check("  Minimum on a nonexistent attribute: writes noise directly (not compared with 0)",
      np.allclose(nz(operation="minimum", amplitude=1.0)[:, 0], raw, atol=1e-6))
gv = c.copy()
gv.set(POINT, "w", np.full((c.npoints, 3), 0.1, np.float32))
o = A(run(NO, geo=gv, attribute_names="w", operation="minimum", use_y=False, amplitude=1.0), "w")
check("  Minimum honours Component Scope (y, which is off, keeps its original value, not min(0.1, 0))", np.allclose(o[:, 1], 0.1) and not np.allclose(o[:, 0], .1))
check("  Gamma 2:t^(1/2)", np.allclose(nz(operation="set", range_values="zero_to_one", amplitude=1.0, gamma=2.0)[:, 0],
                                       np.sqrt(np.clip(t01, 0, 1)), atol=1e-6))
rt = nz(operation="set", fractal="terrain", octaves=6, amplitude=1.0)[:, 0]
o = nz(operation="set", fractal="terrain", octaves=6, gamma=2.0, amplitude=1.0)[:, 0]
check("  Terrain fractal goes beyond [-1,1]; clamped to 0..1 before Gamma, no nan",
      (np.abs(rt) > 1).any() and np.all(np.isfinite(o)) and o.max() <= 1 + 1e-9)
check("  Contrast 2:(t − 0.5)·2 + 0.5", np.allclose(
    nz(operation="set", range_values="zero_to_one", amplitude=1.0, contrast=2.0)[:, 0], (t01 - .5) * 2 + .5, atol=1e-6))
check("  Gamma 2 + Contrast 2: Gamma first, then Contrast", np.allclose(
    nz(operation="set", range_values="zero_to_one", amplitude=1.0, gamma=2.0, contrast=2.0)[:, 0],
    (np.sqrt(np.clip(t01, 0, 1)) - .5) * 2 + .5, atol=1e-6))
ref_n = nz(nm="nn", operation="set", attribute_type="vector")
check("  Attribute Type = Vector: newly created attribute gets 3 components, each independent", ref_n.shape[1] == 3
      and not np.allclose(ref_n[:, 0], ref_n[:, 1]))
check("  Attribute Type = Auto: a new attribute of the same name has 1 component (old behaviour, negative control)", nz(nm="nn", operation="set").shape[1] == 1)
o = A(run(NO, geo=gv, attribute_names="w", operation="set", attribute_type="float", amplitude=1.0), "w")
check("  Attribute Type = Float: one noise spread over three components", np.allclose(o[:, 0], o[:, 1]) and np.allclose(o[:, 0], raw, atol=1e-6))
o = A(run(NO, geo=gv, attribute_names="w", make_unit_length=True), "w")
check("  Make Vectors Unit Length", np.allclose(np.linalg.norm(o, axis=1), 1))
gm = c.copy()
gm.set(POINT, "h", np.zeros((c.npoints, 1), np.float32))
gm.set(POINT, "m", np.linspace(-1, 2, c.npoints, dtype=np.float32)[:, None])
o = nz(geo=gm, operation="set", amplitude=1.0, blend_attribute="m", blend=0.3)[:, 0]
check("  Blend Attribute (clamped 0..1; the constant Blend has no effect)",
      np.allclose(o, raw * np.clip(np.linspace(-1, 2, c.npoints), 0, 1), atol=1e-5))
check("  Blend Attribute doesn't exist → raises", raises(lambda: nz(blend_attribute="zz"), KeyError))
gn = ops.compute_normals(g, "point")
o = run(NO, geo=gn, attribute_names="P", recompute_normals=True, amplitude=0.5, use_x=False, use_z=False)
o2 = run(NO, geo=gn, attribute_names="P", amplitude=0.5, use_x=False, use_z=False)
check("  Recompute Normals: N recomputed after changing P (= Normal SOP); when off N is still flat (negative control)",
      np.allclose(A(o, "N"), A(ops.compute_normals(o2, "point"), "N"))
      and np.allclose(A(o2, "N"), [0, 1, 0]) and not np.allclose(A(o, "N"), [0, 1, 0]))
gp = ops.compute_normals(build.grid(2.0, 2.0, 9, 9), "prim")
o = run(NO, geo=gp, attribute_names="P", recompute_normals=True, amplitude=0.5, use_x=False, use_z=False)
check("  N on prims recomputes prim normals",
      o.get(POINT, "N") is None and not np.allclose(A(o, "N", PRIM), [0, 1, 0]))
o = nz(operation="set", noise_type="manhattan", amplitude=1.0)[:, 0]
check("  Manhattan appended at the end of the Noise Type menu: = worley(…, manhattan)",
      np.allclose(o, AN.worley(A(c, "P"), 0, "f1", "manhattan"), atol=1e-6))


# ═══════════════════════════════════════════════════════════════ Panel
sec("Panel specs")
import comfyui_pcg.panel_specs as PS                     # noqa: E402
NEW = [FL, IN, VE, CO, RA, NO]
for k_ in NEW:
    check(f"{k_}: check_layout is empty", not PANEL.check_layout(k_, M[k_].INPUT_TYPES()),
          PANEL.check_layout(k_, M[k_].INPUT_TYPES()))
    sp = PS.SPECS[k_]
    ws = [nm for p in ("required", "optional") for nm in M[k_].INPUT_TYPES().get(p, {}) if nm != "geo"]
    check(f"{k_}: every widget is in order", sorted(sp["order"]) == sorted(ws), set(sp["order"]) ^ set(ws))
    bad = []
    # for the existing nodes (Randomize / Noise) only the combos this pack touched are checked; interpolation combos claimed by a ramp, like ramp_mode,
    # never had a menu written, they don't belong to this pack
    touched = {RA: {"combine", "distribution"},
               NO: {"operation", "range_values", "noise_type", "attribute_type"}}.get(k_)
    for nm in ws:
        if touched is not None and nm not in touched:
            continue
        spec = [v[nm] for v in M[k_].INPUT_TYPES().values() if nm in v][0]
        if isinstance(spec[0], (list, tuple)):
            menu = sp["inputs"].get(nm, {}).get("menu")
            if menu is None or sorted(menu) != sorted(spec[0]):
                bad.append(nm)
    check(f"{k_}: every token of every combo has a Houdini label", not bad, bad)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
