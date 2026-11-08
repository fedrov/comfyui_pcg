"""
pcg100 · pack c1_composite: COP options completed against the SideFX docs.

  Composite (Blend)      Mode gains Under / Hypot / Exclusion / HardLight / Dodge / Burn;
                         Swap FG and BG, Compare Lengths, Red / Green / Blue / Alpha toggles
  Mask Combine           layer_stack: each layer with its own blend mode and amount, stacked starting from Starting Value;
                         Fold / Complement / Clamp Minimum / Clamp Maximum
  Crop                   Mode (Discard Cropped), Units, Method, Border Mirror, Pixel Padding
  Convolve Filter        kernel image input, Centered Kernel, Border Mirror
  Copy and Transform     non-uniform Scale, Houdini's Over / Under
  Mono (Luminance)       Operation menu with 15 entries, Weights, Normalize Weights
  Mirror                 Number and Offset / Custom Mirror Planes (mirror planes at arbitrary angles)
  Layer Merge            new node PCG_COPLayerCombine: per-pixel compositing of N inputs

Criteria are all hand-computed numbers (moving whole pixels, closed-form blend formulas, impulse response = the kernel itself), every new option
has a negative control; the last section runs the same inputs with the code of baseline commit a9e114d and compares bit-for-bit under old parameters.
"""
import os
import pickle
import shutil
import subprocess
import sys
import tempfile

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
from comfyui_pcg.geo.cop import CopImage                 # noqa: E402
from comfyui_pcg.geo.cop import composite as CMP         # noqa: E402
from comfyui_pcg.geo.cop import fx as FX                 # noqa: E402
from comfyui_pcg.geo.cop import pixel as PX              # noqa: E402
from comfyui_pcg.geo.cop import transform as T           # noqa: E402
from comfyui_pcg.geo.cop import levels as LV             # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag):
    try:
        fn()
        check(name, False, "did not raise")
    except Exception as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:90]}")


def sec(t):
    print(f"\n── {t}")


def L(img, name="C"):
    return PX.getn(img, name)


def mk(**lay):
    first = next(iter(lay.values()))
    H, W = np.asarray(first).shape[:2]
    return CopImage(W, H, {k: np.asarray(v, np.float64) for k, v in lay.items()})


def run(key, *a, **kw):
    """Go through the real node class (wrapped in production, returns a dict)."""
    return fakecomfy.unwrap(getattr(M[key](), M[key].FUNCTION)(*a, **kw))[0]


def close(a, b, tol=1e-6):
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    return a.shape == b.shape and bool(np.abs(a - b).max() < tol)


rng = np.random.default_rng(100)

# ═══════════════════════════════════════════════════════ Composite / Blend
sec("Composite: Houdini Blend's new Modes")
H, W = 6, 8
a3, b3 = rng.random((H, W, 3)), rng.random((H, W, 3))
A3, B3 = mk(C=a3), mk(C=b3)


def cmp_(mode, bg=A3, fg=B3, **kw):
    return L(CMP.composite(bg, fg, mode, **kw))


check("hypot = sqrt(bg² + fg²)(3-4-5)",
      close(cmp_("hypot", mk(C=np.full((2, 2, 3), 3.0)),
                 mk(C=np.full((2, 2, 3), 4.0))), np.full((2, 2, 3), 5.0)))
check("  per-channel length on a random image too", close(cmp_("hypot"), np.sqrt(a3 * a3 + b3 * b3)))
check("exclusion = sum − 2 × product", close(cmp_("exclusion"), a3 + b3 - 2 * a3 * b3))
check("  docs: blending with 1 inverts, with 0 leaves unchanged",
      close(cmp_("exclusion", A3, mk(C=np.ones((H, W, 3)))), 1 - a3)
      and close(cmp_("exclusion", A3, mk(C=np.zeros((H, W, 3)))), a3))
check("  negative control: exclusion ≠ difference", not close(cmp_("exclusion"), cmp_("difference"), 1e-3))
hl = np.where(b3 < 0.5, 2 * a3 * b3, 1 - 2 * (1 - a3) * (1 - b3))
check("hardlight: multiply where the **foreground** < 0.5, otherwise screen", close(cmp_("hardlight"), hl))
check("  negative control: hardlight ≠ overlay (overlay decides by the background)",
      not close(cmp_("hardlight"), cmp_("overlay"), 1e-3))
check("  hardlight(bg, fg) == overlay(fg, bg)", close(cmp_("hardlight"), cmp_("overlay", B3, A3)))
# criterion on the boundary: fg exactly 0.5 goes to the screen branch, the two branches are equal at 0.5 (= bg)
check("  with fg = 0.5 the result = bg (the two branches meet here)",
      close(cmp_("hardlight", A3, mk(C=np.full((H, W, 3), 0.5))), a3))
check("dodge = bg / (1 − fg)", close(cmp_("dodge"), a3 / (1 - b3), 1e-5))
check("  bg 0.2, fg 0.6 → 0.5",
      close(cmp_("dodge", mk(C=np.full((1, 1, 3), 0.2)), mk(C=np.full((1, 1, 3), 0.6))),
            np.full((1, 1, 3), 0.5)))
d1 = cmp_("dodge", A3, mk(C=np.ones((H, W, 3))))
check("  fg = 1 gives no inf / nan (denominator padded with 1e-8)", bool(np.isfinite(d1).all()) and d1.min() > 1e4,
      float(d1.min()))
check("burn = 1 − (1 − bg) / fg", close(cmp_("burn"), 1 - (1 - a3) / b3, 1e-4))
check("  bg 0.8, fg 0.5 → 0.6",
      close(cmp_("burn", mk(C=np.full((1, 1, 3), 0.8)), mk(C=np.full((1, 1, 3), 0.5))),
            np.full((1, 1, 3), 0.6)))
b0 = cmp_("burn", A3, mk(C=np.zeros((H, W, 3))))
check("  fg = 0 gives no inf / nan", bool(np.isfinite(b0).all()) and b0.max() < -1e5)
check("  negative control: dodge ≠ burn ≠ divide",
      not close(cmp_("dodge"), cmp_("burn"), 1e-3) and not close(cmp_("dodge"), cmp_("divide"), 1e-3))

a4, b4 = rng.random((H, W, 4)), rng.random((H, W, 4))
A4, B4 = mk(C=a4), mk(C=b4)
un = cmp_("under", A4, B4)
al = a4[..., 3:] + b4[..., 3:] * (1 - a4[..., 3:])
col = (a4[..., :3] * a4[..., 3:] + b4[..., :3] * b4[..., 3:] * (1 - a4[..., 3:])) / al
check("under: background laid over the foreground (alpha = αb + αf(1 − αb), color normalized by it)",
      close(un[..., 3:], al) and close(un[..., :3], col))
check("  under(bg, fg) == over(fg, bg)", close(un, cmp_("over", B4, A4)))
check("  negative control: under ≠ over", not close(un, cmp_("over", A4, B4), 1e-3))
op_bg = a4.copy(); op_bg[..., 3] = 1.0
check("  with an opaque background under changes nothing", close(cmp_("under", mk(C=op_bg), B4), op_bg))
check("  under on a 3-channel background still outputs 3 channels", cmp_("under", A3, B4).shape == (H, W, 3))
err("unknown Mode raises", lambda: cmp_("sharpen"), "Mode must be one of")
check("the old 14 tokens keep their order (new entries only appended at the end)",
      CMP.MODES[:14] == ("over", "add", "subtract", "difference", "multiply", "divide",
                         "screen", "overlay", "softlight", "darken", "lighten", "atop",
                         "xor", "replace")
      and CMP.MODES[14:] == ("under", "hypot", "exclusion", "hardlight", "dodge", "burn"))

sec("Composite: Swap FG and BG / Compare Lengths / channel toggles")
check("swap + subtract = fg − bg", close(cmp_("subtract", swap=True), b3 - a3))
check("  negative control: without swap it's bg − fg", close(cmp_("subtract"), a3 - b3))
check("  commutative operations unaffected by swap (docs)", np.array_equal(cmp_("add", swap=True), cmp_("add")))
check("  after swap, Mask < 1 interpolates toward the **swapped background** (the original foreground)",
      close(cmp_("subtract", swap=True, opacity=0.25), b3 + (b3 - a3 - b3) * 0.25))
check("  swap + over == over with the two inputs swapped", close(cmp_("over", A4, B4, swap=True), cmp_("over", B4, A4)))
pa = mk(C=np.array([[[0.9, 0.0, 0.0], [0.3, 0.3, 0.3], [0.6, 0.0, 0.8]]]))
pb = mk(C=np.array([[[0.5, 0.5, 0.5], [0.3, 0.3, 0.3], [1.0, 0.0, 0.0]]]))
# |a| = 0.9, 0.52, 1.0; |b| = 0.866, 0.52, 1.0 -- element 0 has a longer, the last two tie
check("lighten takes the larger per channel (Compare Lengths off)",
      close(cmp_("lighten", pa, pb), [[[0.9, 0.5, 0.5], [0.3, 0.3, 0.3], [1.0, 0.0, 0.8]]]))
check("lighten + Compare Lengths: takes the longer whole element; ties keep the background",
      close(cmp_("lighten", pa, pb, compare_lengths=True),
            [[[0.9, 0.0, 0.0], [0.3, 0.3, 0.3], [0.6, 0.0, 0.8]]]))
check("darken + Compare Lengths: takes the shorter whole element; ties keep the background",
      close(cmp_("darken", pa, pb, compare_lengths=True),
            [[[0.5, 0.5, 0.5], [0.3, 0.3, 0.3], [0.6, 0.0, 0.8]]]))
check("  negative control: darken without it takes the smaller per channel",
      close(cmp_("darken", pa, pb), [[[0.5, 0.0, 0.0], [0.3, 0.3, 0.3], [0.6, 0.0, 0.0]]]))
check("  when the foreground is longer, lighten takes the foreground, darken the background",
      close(cmp_("lighten", pb, pa, compare_lengths=True)[0, 0], [0.9, 0, 0])
      and close(cmp_("darken", pb, pa, compare_lengths=True)[0, 0], [0.5, 0.5, 0.5]))
check("  Compare Lengths has no effect on other Modes",
      np.array_equal(cmp_("add", compare_lengths=True), cmp_("add"))
      and np.array_equal(cmp_("over", A4, B4, compare_lengths=True), cmp_("over", A4, B4)))
check("  random image: the length criterion holds per pixel",
      close(cmp_("lighten", compare_lengths=True),
            np.where(((b3 ** 2).sum(-1) > (a3 ** 2).sum(-1))[..., None], b3, a3)))

g_off = cmp_("add", channels=(True, False, True, True))
check("Green off: g keeps the background, r / b blend as usual",
      close(g_off[..., 1], a3[..., 1]) and close(g_off[..., [0, 2]], (a3 + b3)[..., [0, 2]]))
for i, nm in enumerate("RGB"):
    ch = [True] * 4; ch[i] = False
    r = cmp_("multiply", channels=tuple(ch))
    want = a3 * b3; want[..., i] = a3[..., i]
    check(f"  {nm} off keeps only channel {i}", close(r, want))
a_off = cmp_("add", A4, B4, channels=(True, True, True, False))
check("Alpha off: alpha keeps the background, rgb as usual",
      close(a_off[..., 3], a4[..., 3]) and close(a_off[..., :3], (a4 + b4)[..., :3]))
check("  Alpha off has no effect on an RGB layer (no 4th channel)",
      np.array_equal(cmp_("add", channels=(True, True, True, False)), cmp_("add")))
check("  all off = background unchanged", close(cmp_("add", channels=(False,) * 4), a3))
check("  channel toggles multiply with the Mask",
      close(cmp_("add", opacity=0.5, channels=(False, True, True, True)),
            np.concatenate([a3[..., :1], (a3 + 0.5 * b3)[..., 1:]], -1)))
a5, b5 = rng.random((H, W, 5)), rng.random((H, W, 5))
check("  channels from the 5th on have no toggle, always on",
      close(cmp_("add", mk(C=a5), mk(C=b5), channels=(False, True, True, False)),
            np.concatenate([a5[..., :1], (a5 + b5)[..., 1:3], a5[..., 3:4], (a5 + b5)[..., 4:]], -1)))
m1, n1 = rng.random((H, W, 1)), rng.random((H, W, 1))
check("  single-channel layers only look at Red",
      close(cmp_("add", mk(C=m1), mk(C=n1), channels=(False, True, True, True)), m1)
      and close(cmp_("add", mk(C=m1), mk(C=n1), channels=(True, False, False, False)), m1 + n1))
ov = cmp_("over", A3, B4, channels=(True, False, True, True))
ovf = cmp_("over", A3, B4)
check("  over onto an RGB background: with Green off still 3 channels, g keeps the background",
      ov.shape == (H, W, 3) and close(ov[..., 1], a3[..., 1]) and close(ov[..., 0], ovf[..., 0]))
nd = run("PCG_COPComposite", A3, B3, "subtract", 1.0, "C", "", "mask", "", True,
         swap=True, channel_b=False)
check("node: swap / channel_b passed all the way through",
      close(L(nd), np.concatenate([(b3 - a3)[..., :2], b3[..., 2:]], -1)))
nd = run("PCG_COPComposite", pa, pb, "lighten", 1.0, "C", "", "mask", "", True,
         compare_lengths=True, channel_r=False)
check("node: compare_lengths / channel_r passed all the way through",
      close(L(nd)[0, 0], [0.9, 0, 0]) and close(L(nd)[0, 2], [0.6, 0, 0.8]))
nd = run("PCG_COPComposite", A4, B4, "add", 1.0, "C", "", "mask", "", True,
         channel_g=False, channel_a=False)
check("node: channel_g / channel_a each control their own channel",
      close(L(nd), np.stack([(a4 + b4)[..., 0], a4[..., 1], (a4 + b4)[..., 2], a4[..., 3]], -1)))

# ═══════════════════════════════════════════════════════ Mask Combine
sec("Mask Combine: layer_stack (per-layer blend modes)")
ma, mb = rng.random((H, W, 1)), rng.random((H, W, 1))
mc = rng.random((H, W, 3))
MM = mk(a=ma, b=mb, c=mc)


def stk(spec, start=0.0, **kw):
    kw.setdefault("clamp01", False)
    return L(PX.mask_combine(MM, "", "layer_stack", "o", stack=spec, start=start, **kw), "o")


check("one add layer: Starting Value + a", close(stk("a add 1", 0.25), 0.25 + ma))
check("  negative control: changing Starting Value changes the result", close(stk("a add 1", 0.5), 0.5 + ma))
r1 = 0.25 + ma
check("two layers stacked top to bottom, amount 0.5 = halfway toward the blend result",
      close(stk("a add 1\nb multiply 0.5", 0.25), r1 + (r1 * mb - r1) * 0.5))
check("  negative control: swapping the two lines gives a different result (order matters)",
      not close(stk("b multiply 0.5\na add 1", 0.25), stk("a add 1\nb multiply 0.5", 0.25), 1e-3))
check("  a layer with amount = 0 has no effect", close(stk("a add 1\nb multiply 0", 0.25), r1))
check("default mode = blend, default amount = 1: writing just the layer name replaces with it", close(stk("a", 0.7), ma))
check("  blend amount 0.3 = lerp from Starting Value toward it", close(stk("a blend 0.3", 0.7), 0.7 + (ma - 0.7) * 0.3))
s0 = 0.6
want = {
    "blend": ma, "add": s0 + ma, "subtract": s0 - ma, "multiply": s0 * ma,
    "divide": s0 / ma, "screen": s0 + ma - s0 * ma, "hypot": np.sqrt(s0 * s0 + ma * ma),
    "difference": np.abs(s0 - ma), "exclusion": s0 + ma - 2 * s0 * ma,
    "maximum": np.maximum(s0, ma), "minimum": np.minimum(s0, ma),
    # overlay decides by the **running result** (0.6 ≥ 0.5 -> the screen branch)
    "overlay": 1 - 2 * (1 - s0) * (1 - ma),
    "softlight": np.where(ma < 0.5, s0 - (1 - 2 * ma) * s0 * (1 - s0),
                          s0 + (2 * ma - 1) * (np.sqrt(s0) - s0)),
    "hardlight": np.where(ma < 0.5, 2 * s0 * ma, 1 - 2 * (1 - s0) * (1 - ma)),
    "dodge": s0 / (1 - ma), "burn": 1 - (1 - s0) / ma,
}
bad = [m for m, w in want.items() if not close(stk(f"a {m} 1", s0), w, 1e-3)]
check("all 16 modes checked against their formulas (running result is the background, this layer the foreground)", not bad, bad)
check("  all 16 entries of the Houdini menu present (Sharpen not implemented)", set(PX.STACK_MODES) == set(want), sorted(PX.STACK_MODES))
check("a leading # = this layer is off, the whole line is skipped", close(stk("a add 1\n# b multiply 1", 0.25), r1))
check("  semicolons also separate lines", close(stk("a add 1; b multiply 0.5", 0.25), stk("a add 1\nb multiply 0.5", 0.25)))
check("layer.channel: c.g takes channel 1, c.z takes channel 2, none takes channel 0",
      close(stk("c.g"), mc[..., 1:2]) and close(stk("c.z"), mc[..., 2:3])
      and close(stk("c"), mc[..., :1]) and close(stk("c.r"), mc[..., :1]))
check("  mode names are case-insensitive", close(stk("a ADD 1", 0.25), r1))
err("  a channel that can't be taken raises", lambda: stk("a.g"), "has only 1 channel")
err("  unknown mode raises (sharpen not implemented)", lambda: stk("a sharpen 1"), "blend mode must be one of")
err("  a line with more than three items raises", lambda: stk("a add 1 2"), "at most three items")
check("empty stack = the whole image at Starting Value", close(stk("", 0.4), np.full((H, W, 1), 0.4)))
check("layer_stack doesn't read layers (no error when empty), the other modes still require it",
      close(L(PX.mask_combine(MM, "nope_not_read", "layer_stack", "o", False, "a"), "o"), ma))
err("  the old modes still raise when layers is empty", lambda: PX.mask_combine(MM, "", "union"), "Layers is empty")
check("the old 8 tokens keep their order",
      PX.COMBINE_OPS == ("union", "intersect", "add", "multiply", "subtract", "difference",
                         "screen", "average", "layer_stack"))

sec("Mask Combine: post-processing (Fold → Complement → Clamp Min / Max → Clamp 0-1)")
sg = mk(s=np.array([[[-0.3], [0.9], [0.5], [-2.0]]]))


def post(**kw):
    kw.setdefault("clamp01", False)
    return L(PX.mask_combine(sg, "s", "union", "o", **kw), "o").reshape(-1)


check("all off = original values", close(post(), [-0.3, 0.9, 0.5, -2.0]))
check("Fold = absolute value (docs: −2 → 2)", close(post(fold=True), [0.3, 0.9, 0.5, 2.0]))
check("Complement = 1 − x", close(post(complement=True), [1.3, 0.1, 0.5, 3.0]))
check("Fold before Complement: −0.3 → 0.3 → 0.7 (the other way round gives 1.3)",
      close(post(fold=True, complement=True), [0.7, 0.1, 0.5, -1.0]))
check("Clamp Minimum only affects the bottom", close(post(clamp_min=0.0), [0.0, 0.9, 0.5, 0.0]))
check("Clamp Maximum only affects the top", close(post(clamp_max=0.6), [-0.3, 0.6, 0.5, -2.0]))
check("both together", close(post(clamp_min=-1.0, clamp_max=0.6), [-0.3, 0.6, 0.5, -1.0]))
check("Clamp after Complement: 0.9 → 0.1 → lower bound 0.2 (the other way round gives 0.1)",
      close(post(complement=True, clamp_min=0.2), [1.3, 0.2, 0.5, 3.0]))
check("  upper bound likewise: −0.3 → 1.3 → upper bound 1.0", close(post(complement=True, clamp_max=1.0), [1.0, 0.1, 0.5, 1.0]))
check("Clamp 0-1 clamps last", close(post(clamp_min=-1.0, clamp01=True), [0.0, 0.9, 0.5, 0.0]))
check("post-processing applies to layer_stack too",
      close(L(PX.mask_combine(MM, "", "layer_stack", "o", False, "a subtract 1", 0.0, True), "o"), ma))
nd = run("PCG_COPMaskCombine", sg, "s", "union", "o", False, clamp_min=0.0, clamp_max=0.6)
check("node: with use_clamp_min / use_clamp_max unchecked the values have no effect",
      close(L(nd, "o").reshape(-1), [-0.3, 0.9, 0.5, -2.0]))
nd = run("PCG_COPMaskCombine", sg, "s", "union", "o", False, use_clamp_min=True,
         clamp_min=0.0, clamp_max=0.6)
check("  only the lower bound checked", close(L(nd, "o").reshape(-1), [0.0, 0.9, 0.5, 0.0]))
nd = run("PCG_COPMaskCombine", sg, "s", "union", "o", False, use_clamp_max=True,
         clamp_min=0.0, clamp_max=0.6)
check("  only the upper bound checked", close(L(nd, "o").reshape(-1), [-0.3, 0.6, 0.5, -2.0]))
nd = run("PCG_COPMaskCombine", MM, "", "layer_stack", "o", False, stack="a add 1\nb multiply 0.5",
         starting_value=0.25, fold=True, complement=True)
check("node: stack / starting_value / fold / complement passed all the way through",
      close(L(nd, "o"), 1 - np.abs(r1 + (r1 * mb - r1) * 0.5)))

# ═══════════════════════════════════════════════════════ Crop
sec("Crop: Units × Method -> pixel window")
cw = T.crop_window
check("pixels + lower-left and size: as is", cw(8, 4, "pixels", "lower_left_size", (1, 2), (3, 2)) == (1, 2, 3, 2))
check("pixels + lower-left and upper-right: size = upper-right − lower-left",
      cw(8, 4, "pixels", "lower_left_upper_right", (1, 1), (5, 3)) == (1, 1, 4, 2))
check("texture: 0-1 spans the whole image, a square size crops 4×2 on 8×4",
      cw(8, 4, "texture", "lower_left_size", (0.25, 0.5), (0.5, 0.5)) == (2, 2, 4, 2))
check("  texture + upper-right", cw(8, 4, "texture", "lower_left_upper_right", (0.25, 0.25), (0.75, 1.0)) == (2, 1, 4, 3))
check("image: −1…1 spans the long side, origin at the image center, a square size crops a square",
      cw(8, 4, "image", "lower_left_size", (-0.5, -0.5), (1.0, 1.0)) == (2, 0, 4, 4))
check("  image + upper-right; the short side is also converted by half the long side",
      cw(8, 4, "image", "lower_left_upper_right", (-1.0, -0.25), (0.5, 0.5)) == (0, 1, 6, 3))
check("  portrait (4×8): long side is y", cw(4, 8, "image", "lower_left_size", (-0.5, -1.0), (1.0, 2.0)) == (0, 0, 4, 8))
check("  whole image = image [−1,1] × [−H/W, H/W]",
      cw(8, 4, "image", "lower_left_upper_right", (-1, -0.5), (1, 0.5)) == (0, 0, 8, 4))
check("values not on a pixel edge are rounded (0.3 × 8 = 2.4 → 2; 0.33 × 8 = 2.64 → 3)",
      cw(8, 4, "texture", "lower_left_size", (0.3, 0), (0.5, 1))[0] == 2
      and cw(8, 4, "texture", "lower_left_size", (0.33, 0), (0.5, 1))[0] == 3)
check("  exact halves round up (2.5 → 3), negatives in the same direction (−2.5 → −2)",
      cw(8, 4, "pixels", "lower_left_upper_right", (2.5, 0), (7, 4))[0] == 3
      and cw(8, 4, "pixels", "lower_left_upper_right", (-2.5, 0), (7, 4))[0] == -2)
err("empty window raises", lambda: cw(8, 4, "pixels", "lower_left_upper_right", (3, 0), (3, 4)), "crop window is empty")
err("  empty in y raises too", lambda: cw(8, 4, "pixels", "lower_left_size", (0, 0), (2, 0)), "crop window is empty")
err("unknown Units / Method raises", lambda: cw(8, 4, "world"), "Units must be one of")
err("  ", lambda: cw(8, 4, "pixels", "center_size"), "Method must be one of")

sec("Crop:Mode = Discard Cropped / Border = Mirror / Pixel Padding")
ca = rng.random((6, 8, 3))
CA = mk(C=ca, m=rng.random((6, 8, 1)))
dc = T.crop(CA, 2, 1, 4, 3, "black", "discard")
want = np.zeros_like(ca); want[1:4, 2:6] = ca[1:4, 2:6]
check("discard: resolution unchanged, inside the window bit-exact in place, outside the window 0",
      dc.res == (8, 6) and np.array_equal(L(dc), want))
check("  other layers cropped too", np.array_equal(L(dc, "m")[1:4, 2:6], L(CA, "m")[1:4, 2:6]) and L(dc, "m")[0].max() == 0)
check("  negative control: discard_reframe resolution = the window", T.crop(CA, 2, 1, 4, 3, "black").res == (4, 3))
dcl = L(T.crop(CA, 2, 1, 4, 3, "clamp", "discard"))
iy = np.clip(np.arange(6), 1, 3); ix = np.clip(np.arange(8), 2, 5)
check("discard + clamp: outside the window extends from the edge of **the kept part**", np.array_equal(dcl, ca[iy][:, ix]))
dwr = L(T.crop(CA, 2, 1, 4, 3, "wrap", "discard"))
check("discard + wrap: the kept part extended periodically",
      np.array_equal(dwr, ca[(np.arange(6) - 1) % 3 + 1][:, (np.arange(8) - 2) % 4 + 2]))
dmi = L(T.crop(CA, 2, 1, 4, 3, "mirror", "discard"))


def refl(i, lo, n):
    t = (i - lo) % (2 * n)
    return np.where(t >= n, 2 * n - 1 - t, t) + lo


check("discard + mirror: reflection at the edge (edge pixel repeated once)",
      np.array_equal(dmi, ca[refl(np.arange(6), 1, 3)][:, refl(np.arange(8), 2, 4)]))
check("  the two specific columns: column 1 left of the window = window column 0, column 2 = window column 1",
      np.array_equal(dmi[2, 1], ca[2, 2]) and np.array_equal(dmi[2, 0], ca[2, 3]))
check("  the four Borders all differ outside the window",
      len({arr.tobytes() for arr in (L(dc), dcl, dwr, dmi)}) == 4)
do = T.crop(CA, -3, -2, 6, 5, "clamp", "discard")
check("discard window extending outside the image: kept = window ∩ original image",
      np.array_equal(L(do), ca[np.clip(np.arange(6), 0, 2)][:, np.clip(np.arange(8), 0, 2)]))
dz = T.crop(CA, 20, 20, 4, 4, "clamp", "discard")
check("discard window entirely outside the image: all 0, resolution unchanged", dz.res == (8, 6) and L(dz).max() == 0 and L(dz).min() == 0)
check("  touching (the window's left edge exactly at the image's right edge) also counts as entirely outside",
      L(T.crop(CA, 8, 0, 4, 6, "clamp", "discard")).max() == 0
      and L(T.crop(CA, -4, 0, 4, 6, "clamp", "discard")).max() == 0
      and L(T.crop(CA, 0, 6, 8, 2, "clamp", "discard")).max() == 0
      and L(T.crop(CA, 0, -2, 8, 2, "clamp", "discard")).max() == 0)
check("  overlapping just one column is not entirely outside", L(T.crop(CA, 7, 0, 4, 6, "black", "discard"))[:, 7].max() > 0)
df = T.crop(CA, 0, 0, 8, 6, "black", "discard")
check("discard window = whole image: as is", np.array_equal(L(df), ca))
# pixels outside the window are read by **folding back** into the kept part and then zeroed, so it takes an inf at the window corner to test it
inf = ca.copy(); inf[1, 2] = np.inf
ri = L(T.crop(mk(C=inf), 2, 1, 4, 3, "black", "discard"))
check("discard + black: zeroing outside the window uses where, not multiply by 0 (an inf at the window corner doesn't become nan outside)",
      not np.isnan(ri).any() and np.isinf(ri[1, 2]).all() and ri[0].max() == 0 and ri[:, :2].max() == 0)
mr = L(T.crop(CA, -3, -2, 14, 10, "mirror"))
check("discard_reframe + mirror: outward padding = np.pad(symmetric)",
      np.array_equal(mr, np.pad(ca, ((2, 2), (3, 3), (0, 0)), mode="symmetric")))
check("  negative control: differs from the clamp / wrap padding",
      not np.array_equal(mr, L(T.crop(CA, -3, -2, 14, 10, "clamp")))
      and not np.array_equal(mr, L(T.crop(CA, -3, -2, 14, 10, "wrap"))))
far = L(T.crop(CA, -20, 0, 8, 6, "mirror"))
check("  mirror extending beyond a whole image is also right (period 2W)",
      np.array_equal(far, ca[:, refl(np.arange(8) - 20, 0, 8)]))
from comfyui_pcg.geo.cop.core import MAX_RES           # noqa: E402
err("  the mirror path also checks the resolution limit", lambda: T.crop(CA, 0, 0, MAX_RES + 1, 4, "mirror"), "resolution limit")
err("unknown Mode / Border raises", lambda: T.crop(CA, 0, 0, 4, 4, "black", "reframe"), "Mode must be one of")
err("  ", lambda: T.crop(CA, 0, 0, 4, 4, "clip"), "Border must be one of")
pp = T.crop(CA, 2, 1, 4, 3, "black", "discard_reframe", (1, 2, 3, 4))
check("Pixel Padding (left 1 right 2 top 3 bottom 4): window becomes 7×10, lower-left corner moves 1 left and 4 down",
      pp.res == (7, 10) and np.array_equal(L(pp), L(T.crop(CA, 1, -3, 7, 10, "black"))))
check("  position of the original window in the padded image: x offset 1, y offset 4",
      np.array_equal(L(pp)[4:7, 1:5], ca[1:4, 2:6]))
for i, nm in enumerate(("left", "right", "top", "bottom")):
    pd = [0, 0, 0, 0]; pd[i] = 2
    r = T.crop(CA, 2, 1, 4, 3, "black", "discard_reframe", tuple(pd))
    wres = (6, 3) if i < 2 else (4, 5)
    off = {0: (0, 2), 1: (0, 0), 2: (0, 0), 3: (2, 0)}[i]
    check(f"  padding only {nm}: resolution {wres}, original window at (row {off[0]}, column {off[1]})",
          r.res == wres and np.array_equal(L(r)[off[0]:off[0] + 3, off[1]:off[1] + 4], ca[1:4, 2:6]))
check("  in discard mode padding extends the kept area outward",
      np.array_equal(L(T.crop(CA, 2, 1, 4, 3, "black", "discard", (1, 0, 0, 1))),
                     L(T.crop(CA, 1, 0, 5, 4, "black", "discard"))))

CROP = ("PCG_COPCrop",)
nd = run("PCG_COPCrop", CA, 2, 1, 4, 3, "black", units="pixels", method="lower_left_size",
         corner="0 0", extent="0.5 0.5")
check("node: pixels + lower-left and size reads integer X / Y / Resolution, not Corner / Extent",
      nd.res == (4, 3) and np.array_equal(L(nd), ca[1:4, 2:6]))
nd = run("PCG_COPCrop", CA, 2, 1, 4, 3, "black", units="texture", corner="0.25 0.5", extent="0.5 0.5")
check("node: texture reads Corner / Extent (0.25,0.5 + 0.5,0.5 on 8×6 -> columns 2-5, rows 3-5)",
      nd.res == (4, 3) and np.array_equal(L(nd), ca[3:6, 2:6]))
nd = run("PCG_COPCrop", CA, 2, 1, 4, 3, "black", units="pixels", method="lower_left_upper_right",
         corner="1 2", extent="7 5")
check("node: pixels + lower-left and upper-right also reads Corner / Extent", nd.res == (6, 3) and np.array_equal(L(nd), ca[2:5, 1:7]))
nd = run("PCG_COPCrop", CA, 0, 0, 4, 3, "black", units="image", corner="-0.5 -0.5", extent="1 1")
check("node: a square image size crops 4×4 on 8×6 (columns 2-5, rows 1-4)",
      nd.res == (4, 4) and np.array_equal(L(nd), ca[1:5, 2:6]))
nd = run("PCG_COPCrop", CA, 2, 1, 4, 3, "mirror", mode="discard", pad_left=1, pad_bottom=1)
check("node: mode / border / pad_left / pad_bottom passed all the way through",
      np.array_equal(L(nd), L(T.crop(CA, 2, 1, 4, 3, "mirror", "discard", (1, 0, 0, 1)))))
nd = run("PCG_COPCrop", CA, 2, 1, 4, 3, "black", pad_right=2, pad_top=1)
check("node: pad_right / pad_top", nd.res == (6, 4) and np.array_equal(L(nd)[:3, :4], ca[1:4, 2:6]))
check("node: doesn't crash with no image connected (doesn't read cop.xres)",
      len(run("PCG_COPCrop", None, 0, 0, 4, 4, "black", units="texture")) == 0)

# ═══════════════════════════════════════════════════════ Convolve Filter
sec("Convolve Filter: kernel image input")
imp = np.zeros((11, 13, 1)); imp[5, 6, 0] = 1.0
IMP = mk(C=imp)
k35 = rng.random((3, 5, 1))
r = L(FX.convolve_layer(IMP, "C", kernel_img=mk(C=k35)))
want = np.zeros((11, 13, 1)); want[4:7, 4:9] = k35
check("convolving a single-pixel impulse = the kernel image itself, centered on the impulse (3×5 kernel)", close(r, want))
check("  negative control: not the flipped kernel (that would be correlation)", not close(r[4:7, 4:9], k35[::-1, ::-1], 1e-3))
r = L(FX.convolve_layer(IMP, "C", kernel_img=mk(C=k35), centered=False))
want = np.zeros((11, 13, 1)); want[5:8, 6:11] = k35
check("Centered Kernel off: origin = the kernel's bottom-left pixel, result shifted to the upper right", close(r, want))
k44 = rng.random((4, 4, 1))
r = L(FX.convolve_layer(IMP, "C", kernel_img=mk(C=k44)))
want = np.zeros((11, 13, 1)); want[3:7, 4:8] = k44
check("even-sized kernel: center taken at (h//2, w//2) = (2, 2)", close(r, want))
r = L(FX.convolve_layer(IMP, "C", kernel_img=mk(C=k44), centered=False))
want = np.zeros((11, 13, 1)); want[5:9, 6:10] = k44
check("  even kernel not centered: k[0,0] at the impulse", close(r, want))
kf = FX.kernel_from_image
check("  the embedded correlation kernel isn't padded by an extra ring: centered odd kernels keep their size, even kernels +1, uncentered ones are (2h−1, 2w−1)",
      kf(k35[..., 0]).shape == (3, 5) and kf(k44[..., 0]).shape == (5, 5)
      and kf(k35[..., 0], False).shape == (5, 9) and kf(np.ones((1, 1))).shape == (1, 1))
k1 = rng.random((1, 1, 1))
check("a 1×1 kernel = multiply by a number", close(L(FX.convolve_layer(A3, "C", kernel_img=mk(C=k1))), a3 * k1[0, 0, 0]))
k99 = rng.random((9, 9, 1))
r = L(FX.convolve_layer(IMP, "C", kernel_img=mk(C=k99), border="black"))
want = np.zeros((11, 13, 1)); want[1:10, 2:11] = k99
check("large kernel (9×9, via FFT), same criterion", close(r, want, 1e-9))
k97 = rng.random((9, 7, 1))
r = L(FX.convolve_layer(IMP, "C", kernel_img=mk(C=k97), border="black", centered=False))
want = np.zeros((11, 13, 1)); want[5:11, 6:13] = k97[:6]
check("  large kernel not centered (the part extending outside the frame is cropped)", close(r, want, 1e-9))
# relation to string kernels: string kernels are correlation with the first row on top; image kernels are convolution with row 0 at the bottom.
# the "read the pixel above" string kernel "0 1 0 / 0 0 0 / 0 0 0" is equivalent to an impulse in the **bottom** row of an image kernel
ki = np.zeros((3, 3, 1)); ki[0, 1, 0] = 1.0
nz = rng.random((7, 9, 2))
NZ = mk(C=nz)
r_img = L(FX.convolve_layer(NZ, "C", kernel_img=mk(C=ki)))
check("an impulse in the bottom row of an image kernel == an impulse in the top row of a string kernel (both read the pixel above)",
      close(r_img, L(FX.convolve_layer(NZ, "C", kernel="0 1 0 0 0 0 0 0 0")))
      and close(r_img[:-1], nz[1:]))
check("both paths agree for a symmetric kernel (box3)",
      close(L(FX.convolve_layer(NZ, "C", kernel_img=mk(C=np.full((3, 3, 1), 1 / 9)))),
            L(FX.convolve_layer(NZ, "C", preset="box3", normalize=True))))
check("with a kernel image connected, the Preset / Kernel string isn't read",
      close(L(FX.convolve_layer(NZ, "C", "sobel_x", "9 9 9 9", kernel_img=mk(C=ki))), r_img))
k2 = np.full((3, 3, 1), 2.0)
cst = mk(C=np.full((5, 5, 3), 0.25))
check("Normalize Kernel: kernel divided by its own sum, constant image unchanged",
      close(L(FX.convolve_layer(cst, "C", normalize=True, kernel_img=mk(C=k2))), np.full((5, 5, 3), 0.25)))
check("  negative control: without normalizing it's × the kernel sum (18)",
      close(L(FX.convolve_layer(cst, "C", kernel_img=mk(C=k2))), np.full((5, 5, 3), 4.5)))
kz = np.zeros((3, 3, 1)); kz[1, 0, 0], kz[1, 2, 0] = 1.0, -1.0
check("  a kernel summing to 0 isn't scaled (no division by 0)",
      close(L(FX.convolve_layer(NZ, "C", normalize=True, kernel_img=mk(C=kz))),
            L(FX.convolve_layer(NZ, "C", kernel_img=mk(C=kz)))))
k3c = np.zeros((1, 1, 3)); k3c[0, 0] = (1.0, 2.0, 4.0)
check("3-channel kernel on a 3-channel layer: each channel uses its own",
      close(L(FX.convolve_layer(A3, "C", kernel_img=mk(C=k3c))), a3 * np.array([1.0, 2.0, 4.0])))
check("  each channel normalized separately",
      close(L(FX.convolve_layer(A3, "C", normalize=True, kernel_img=mk(C=k3c))), a3))
check("  a 1-channel kernel is used for every channel",
      close(L(FX.convolve_layer(A3, "C", kernel_img=mk(C=np.full((1, 1, 1), 3.0)))), a3 * 3))
err("  mismatched channel counts (3-channel kernel, 2-channel layer) raise",
    lambda: FX.convolve_layer(NZ, "C", kernel_img=mk(C=k3c)), "kernel must have either 1 channel")
check("Kernel Layer selects which layer of the kernel image to use",
      close(L(FX.convolve_layer(A3, "C", kernel_img=mk(C=k3c, k=np.full((1, 1, 1), 5.0)),
                                kernel_layer="k")), a3 * 5))
both = FX.convolve_layer(mk(C=a3, m=ma), "C", kernel_img=mk(C=np.full((1, 1, 1), 3.0)))
check("only the layers listed in Layers are convolved, the others are unchanged", close(L(both), a3 * 3) and close(L(both, "m"), ma))

sec("Convolve:Border = Mirror")
ramp = np.tile(np.arange(8, dtype=np.float64)[None, :, None] ** 2, (3, 1, 1))
RP = mk(C=ramp)
left2 = "0 0 0 0 0  0 0 0 0 0  1 0 0 0 0  0 0 0 0 0  0 0 0 0 0"      # reads the 2nd pixel to the left
r = L(FX.convolve_layer(RP, "C", kernel=left2, border="mirror"))[0, :, 0]
check("mirror: the 1st / 2nd pixel outside the left border = column 0 / 1 (reflection at the edge, edge pixel repeated)",
      close(r, [1, 0, 0, 1, 4, 9, 16, 25]))
check("  negative control: clamp is [0,0,0,…], wrap is [36,49,…], black is [0,0,…] and the right side likewise",
      close(L(FX.convolve_layer(RP, "C", kernel=left2, border="clamp"))[0, :3, 0], [0, 0, 0])
      and close(L(FX.convolve_layer(RP, "C", kernel=left2, border="wrap"))[0, :3, 0], [36, 49, 0]))
right2 = "0 0 0 0 0  0 0 0 0 0  0 0 0 0 1  0 0 0 0 0  0 0 0 0 0"
check("  right border likewise", close(L(FX.convolve_layer(RP, "C", kernel=right2, border="mirror"))[0, :, 0],
                           [4, 9, 16, 25, 36, 49, 49, 36]))
err("unknown Border raises", lambda: FX.convolve_layer(RP, "C", border="clip"), "Border must be one of")
nd = run("PCG_COPConvolve", IMP, "C", "custom", "0 0 0 0 1 0 0 0 0", False, "black",
         kernel_layer="k", centered=False, kernel_cop=mk(k=k35))
want = np.zeros((11, 13, 1)); want[5:8, 6:11] = k35
check("node: kernel_cop / kernel_layer / centered passed all the way through", close(L(nd), want))
nd = run("PCG_COPConvolve", RP, "C", "custom", left2, False, "mirror")
check("node: Border menu gains mirror at the end, still reads the string when no kernel is connected",
      close(L(nd)[0, :, 0], [1, 0, 0, 1, 4, 9, 16, 25])
      and M["PCG_COPConvolve"].INPUT_TYPES()["required"]["border"][0] == ["clamp", "wrap", "black", "mirror"])

# ═══════════════════════════════════════════════════════ Mirror
sec("Mirror:Number and Offset / Custom Mirror Planes")
MW, MH = 16, 8
mi = rng.random((MH, MW, 2))
MI = mk(P=mi)
jj, ii = np.arange(MW), np.arange(MH)


def mir(mode="number_and_offset", **kw):
    return L(FX.mirror(MI, "P", mode, **kw), "P")


check("angle 0, offset 0 == the old left_to_right (position 0.5), bit-exact",
      np.array_equal(mir(planes=1, angle=0.0, offset=0.0), mir("left_to_right", position=0.5)))
check("  it's the left half mirrored onto the right half: out[j] = in[W−1−j] (j ≥ W/2)",
      close(mir(), mi[:, np.where(jj >= 8, 15 - jj, jj)]))
# image space: −1…1 spans the long side (16 px), offset 0.25 = 2 px, mirror at pixel edge 10
check("offset 0.25 = mirror moved right by 2 px (half the long side × 0.25): j ≥ 10 takes 19 − j",
      close(mir(offset=0.25), mi[:, np.where(jj >= 10, 19 - jj, jj)]))
check("  offset −0.25 moves left: j ≥ 6 takes 11 − j (out of reach clamps to the edge)",
      close(mir(offset=-0.25), mi[:, np.where(jj >= 6, np.clip(11 - jj, 0, 15), jj)]))
check("Reverse: the normal side becomes the source (mirror doesn't move): j < 10 takes 19 − j, out of reach clamps to the edge",
      close(mir(offset=0.25, reverse=True), mi[:, np.where(jj < 10, np.clip(19 - jj, 0, 15), jj)]))
check("  negative control: Reverse on and off differ", not close(mir(reverse=True), mir(), 1e-3))
check("docs: angle 180 + Reverse == angle 0", close(mir(angle=180.0, reverse=True), mir(), 1e-9))
check("  angle 180 = right half mirrored onto the left half", close(mir(angle=180.0), mi[:, np.where(jj < 8, 15 - jj, jj)], 1e-9))
check("angle 90: bottom half mirrored onto the top half (normal pointing up)", close(mir(angle=90.0), mi[np.where(ii >= 4, 7 - ii, ii)], 1e-9))
check("  angle −90: top half mirrored onto the bottom half", close(mir(angle=-90.0), mi[np.where(ii < 4, 7 - ii, ii)], 1e-9))
# vertical offsets are also converted by half the **long side** (8 px): 0.25 -> 2 px, mirror at row edge 6
check("  the angle 90 offset is also converted by the long side: 0.25 -> 2 rows (i ≥ 6 takes 11 − i)",
      close(mir(angle=90.0, offset=0.25), mi[np.where(ii >= 6, 11 - ii, ii)], 1e-9))
sq = rng.random((8, 8, 1))
SQ = mk(P=sq)
r45 = L(FX.mirror(SQ, "P", "number_and_offset", angle=45.0), "P")
I8, J8 = np.meshgrid(np.arange(8), np.arange(8), indexing="ij")
want = np.where((I8 + J8 > 7)[..., None], sq[7 - J8, 7 - I8], sq)
check("angle 45 (square image): upper-right triangle = lower-left triangle flipped across the anti-diagonal", close(r45, want, 1e-9))
check("Number of Planes = 2, Angle 90: the two planes at 90° and 180° (docs: 20 × 3 -> 20/40/60)",
      close(mir(planes=2, angle=90.0), mir("custom_planes", plane_list="90 0\n180 0"), 1e-12))
check("  negative control: not 0° and 90°", not close(mir(planes=2, angle=90.0), mir("custom_planes", plane_list="0 0\n90 0"), 1e-3))
check("  negative control: 1 plane and 2 planes differ", not close(mir(planes=2, angle=90.0), mir(planes=1, angle=90.0), 1e-3))
seq = FX.mirror(FX.mirror(MI, "P", "number_and_offset", angle=90.0), "P", "number_and_offset", angle=180.0)
check("  multiple planes = applied in turn (first 90° then 180°), same as chaining them one at a time",
      close(mir(planes=2, angle=90.0), L(seq, "P"), 1e-9))
check("  Number and Offset uses the same Offset / Reverse for every plane",
      close(mir(planes=2, angle=90.0, offset=0.25, reverse=True),
            mir("custom_planes", plane_list="90 0.25 1\n180 0.25 1"), 1e-12))
# order matters: A = 0° offset 0.25 (j ≥ 10 takes 19 − j), B = 0° offset −0.25 reversed (j < 6 takes 11 − j)
fa = np.where(jj >= 10, 19 - jj, jj)
fb = np.where(jj < 6, 11 - jj, jj)
check("Custom: one plane per line, applied in line order (A then B: out = in[fa[fb]])",
      close(mir("custom_planes", plane_list="0 0.25\n0 -0.25 1"), mi[:, fa[fb]]))
check("  swapping the two lines: out = in[fb[fa]], result differs",
      close(mir("custom_planes", plane_list="0 -0.25 1\n0 0.25"), mi[:, fb[fa]])
      and not np.array_equal(fa[fb], fb[fa]))
check("  angle only: offset 0, not reversed; a nonzero third item = reversed",
      close(mir("custom_planes", plane_list="0"), mir())
      and close(mir("custom_planes", plane_list="0 0.25 1"), mir(offset=0.25, reverse=True))
      and close(mir("custom_planes", plane_list="0 0.25 0"), mir(offset=0.25)))
check("  blank lines skipped, semicolons also separate lines, empty table = original image",
      close(mir("custom_planes", plane_list="\n0 0.25;\n\n0 -0.25 1\n"), mi[:, fa[fb]])
      and close(mir("custom_planes", plane_list=""), mi))
err("  a line with more than three items raises", lambda: mir("custom_planes", plane_list="0 0 0 0"), "at most three items")
check("these two modes don't read Position", np.array_equal(mir(position=0.1), mir(position=0.9))
      and np.array_equal(mir("custom_planes", plane_list="0", position=0.1), mir()))
check("  the old five modes still read Position", not np.array_equal(mir("left_to_right", position=0.25), mir("left_to_right", position=0.5)))
two = FX.mirror(mk(P=mi, Q=mi), "P", "number_and_offset")
check("only the layers listed in Layers move", np.array_equal(L(two, "Q"), mi) and not np.array_equal(L(two, "P"), mi))
check("the old five tokens keep their order",
      FX.MIRRORS == ("left_to_right", "right_to_left", "bottom_to_top", "top_to_bottom", "quad",
                     "number_and_offset", "custom_planes"))
nd = run("PCG_COPMirror", MI, "P", "number_and_offset", 0.5, planes=2, angle=90.0, offset=0.25, reverse=True)
check("node: planes / angle / offset / reverse passed all the way through",
      close(L(nd, "P"), mir(planes=2, angle=90.0, offset=0.25, reverse=True), 1e-12)
      and not close(L(nd, "P"), mir(planes=2, angle=90.0), 1e-3))
nd = run("PCG_COPMirror", MI, "P", "custom_planes", 0.5, plane_list="0 0.25\n0 -0.25 1")
check("node: plane_list passed all the way through", close(L(nd, "P"), mi[:, fa[fb]]))

# ═══════════════════════════════════════════════════════ Copy and Transform
sec("Copy and Transform: non-uniform Scale")
box = np.zeros((16, 16, 1)); box[6:10, 6:10] = 1.0
BX = mk(C=box)


def ext(a):
    """(row count, column count) of the pixels > 0.5."""
    m = a[..., 0] > 0.5
    return int(m.any(1).sum()), int(m.any(0).sum())


check("baseline: max with two copies, no scaling, the square is still 4×4", ext(L(FX.copy_transform(BX, "C", 2, "0 0", op="max"))) == (4, 4))
check("Scale XY '2 1': copy 1 is doubled only in x (4 rows × 8 columns)",
      ext(L(FX.copy_transform(BX, "C", 2, "0 0", op="max", scale_xy="2 1"))) == (4, 8))
check("  '1 2': only in y (8 rows × 4 columns)",
      ext(L(FX.copy_transform(BX, "C", 2, "0 0", op="max", scale_xy="1 2"))) == (8, 4))
check("  multiplied with Uniform Scale: scale 2 × '0.5 1' = (1, 2)",
      np.array_equal(L(FX.copy_transform(BX, "C", 2, "0 0", scale=2.0, op="max", scale_xy="0.5 1")),
                     L(FX.copy_transform(BX, "C", 2, "0 0", op="max", scale_xy="1 2"))))
check("  '2 2' == Uniform Scale 2, bit-exact",
      np.array_equal(L(FX.copy_transform(BX, "C", 3, "0 0", op="max", scale_xy="2 2")),
                     L(FX.copy_transform(BX, "C", 3, "0 0", scale=2.0, op="max"))))
check("  copy i is s^i: 3 copies, '2 1' -> widest is 16 columns",
      ext(L(FX.copy_transform(BX, "C", 3, "0 0", op="max", scale_xy="2 1"))) == (4, 16))
check("  a single number = used for both directions",
      np.array_equal(L(FX.copy_transform(BX, "C", 2, "0 0", op="max", scale_xy="2")),
                     L(FX.copy_transform(BX, "C", 2, "0 0", op="max", scale_xy="2 2"))))

sec("Copy and Transform: Houdini's Over / Under")
CW_, CH_ = 20, 4
st4 = np.zeros((CH_, CW_, 4))
st4[:, 4:10, :3] = np.arange(4, 10, dtype=np.float64)[None, :, None]
st4[:, 4:10, 3] = 1.0
ST4 = mk(C=st4)
tr4 = f"{4 / CW_} 0"          # each copy shifted right 4 px: copy 0 at 4-9, copy 1 at 8-13, overlap 8-9


def cp(op, img=ST4, n=2, **kw):
    return L(FX.copy_transform(img, "C", n, tr4, op=op, **kw))


ol, ud = cp("over_last"), cp("under")
check("over_last: the overlap shows the copy made **later** (columns 8-9 have values 4, 5)",
      close(ol[0, :, 0], [0, 0, 0, 0, 4, 5, 6, 7, 4, 5, 6, 7, 8, 9, 0, 0, 0, 0, 0, 0]))
check("under: the overlap shows the copy made **earlier** (columns 8-9 have values 8, 9)",
      close(ud[0, :, 0], [0, 0, 0, 0, 4, 5, 6, 7, 8, 9, 6, 7, 8, 9, 0, 0, 0, 0, 0, 0]))
cov = np.zeros(CW_); cov[4:14] = 1
check("  alpha is the union of the two copies (columns 4-13 are 1, 0 elsewhere)", close(ol[0, :, 3], cov) and close(ud[0, :, 3], cov))
check("  three copies: over_last has copy 2 on top",
      close(cp("over_last", n=3)[0, :, 0], [0, 0, 0, 0, 4, 5, 6, 7, 4, 5, 6, 7, 4, 5, 6, 7, 8, 9, 0, 0]))
check("  three copies: under has copy 0 on top",
      close(cp("under", n=3)[0, :, 0], [0, 0, 0, 0, 4, 5, 6, 7, 8, 9, 6, 7, 8, 9, 6, 7, 8, 9, 0, 0]))
half = st4.copy(); half[..., 3] *= 0.5
oh, uh = cp("over_last", mk(C=half)), cp("under", mk(C=half))
check("semi-transparent: overlap alpha = 0.5 + 0.5 × 0.5 = 0.75 (Porter–Duff, not interpolation)",
      close(oh[0, 8:10, 3], [0.75, 0.75]) and close(oh[0, [5, 12], 3], [0.5, 0.5])
      and close(uh[0, 8:10, 3], [0.75, 0.75]))
check("  color (unpremultiplied): over_last = (new × 0.5 + old × 0.25) / 0.75",
      close(oh[0, 8:10, 0], [(4 * 0.5 + 8 * 0.25) / 0.75, (5 * 0.5 + 9 * 0.25) / 0.75]))
check("  under = (old × 0.5 + new × 0.25) / 0.75",
      close(uh[0, 8:10, 0], [(8 * 0.5 + 4 * 0.25) / 0.75, (9 * 0.5 + 5 * 0.25) / 0.75]))
fo = cp("over_last", fade=0.5)
check("Fade only multiplies alpha: in columns only copy 1 covers, color unchanged, alpha = 0.5",
      close(fo[0, 10:14, 0], [6, 7, 8, 9]) and close(fo[0, 10:14, 3], [0.5] * 4))
check("  overlap: the new alpha 0.5 over the opaque old one -> alpha 1, color half and half",
      close(fo[0, 8:10, 3], [1, 1]) and close(fo[0, 8:10, 0], [6, 7]))
check("  copy 0 unaffected by Fade", close(fo[0, 4:8, 3], [1] * 4) and close(fo[0, 4:8, 0], [4, 5, 6, 7]))
fu = cp("under", fade=0.5)
check("  under + Fade: in the overlap copy 0 is opaque and covers it, where alone alpha 0.5",
      close(fu[0, 8:10, 0], [8, 9]) and close(fu[0, 10:14, 3], [0.5] * 4))
# a layer without alpha = the whole frame is opaque: the later copy's **frame** (covering columns 4-19 after shifting right 4 px) is laid over entirely
cj = np.arange(CW_, dtype=np.float64)
st3 = np.tile((cj + 1)[None, :, None], (CH_, 1, 3))
ST3 = mk(C=st3)
o3, u3 = cp("over_last", ST3), cp("under", ST3)
check("layer without alpha: with over_last the later copy's whole frame covers the earlier one (columns ≥ 4 are the shifted copy)",
      o3.shape == (CH_, CW_, 3) and close(o3[0, :, 0], np.where(cj >= 4, cj - 3, cj + 1)))
check("  under: copy 0 is opaque and covers the whole image, result = original image", close(u3, st3) and close(cp("under", ST3, n=3, fade=0.5), st3))
check("  negative control: over_last ≠ under", not close(o3, u3, 1e-3))
f3 = cp("over_last", ST3, fade=0.5)
check("  Fade: the later copy's alpha = 0.5, inside the frame = new × 0.5 + old × 0.5, outside the frame = old",
      close(f3[0, :, 0], np.where(cj >= 4, (cj - 3) * 0.5 + (cj + 1) * 0.5, cj + 1)))
f3o = cp("over_last", ST3, n=3, fade=0.5)
check("  three copies: columns ≥ 8 = copy 2 × 0.25 + (copy 1 × 0.5 + copy 0 × 0.5) × 0.75",
      close(f3o[0, 8:, 0], (cj[8:] - 7) * 0.25 + ((cj[8:] - 3) * 0.5 + (cj[8:] + 1) * 0.5) * 0.75)
      and close(f3o[0, 4:8, 0], (cj[4:8] - 3) * 0.5 + (cj[4:8] + 1) * 0.5))
res = FX.copy_transform(ST3, "C", 2, tr4, op="over_last")
check("  the internal coverage layer doesn't leak into the output", res.names == ["C"], res.names)
res = FX.copy_transform(mk(C=st3, __coverage=st3), "", 2, tr4, op="over_last")
check("  an input that happens to have a layer called __coverage: treated as a normal layer, doesn't clash with the internal coverage layer",
      close(L(res, "__coverage"), o3) and close(L(res), o3)
      and sorted(res.names) == ["C", "__coverage"])
bx4 = np.concatenate([box, box], -1)[..., [0, 0, 0, 1]]
check("  over_last / under also take non-uniform Scale ('2 1': alpha extent 4 rows × 8 columns)",
      ext(L(FX.copy_transform(mk(C=bx4), "C", 2, "0 0", op="over_last", scale_xy="2 1"))[..., 3:]) == (4, 8)
      and ext(L(FX.copy_transform(mk(C=bx4), "C", 2, "0 0", op="under", scale_xy="1 2"))[..., 3:]) == (8, 4))
check("the old over is untouched: copy 0 on top (opposite of Houdini's Over)",
      close(cp("over")[0, 8:10, 0], [8, 9]) and FX.COPY_OPS[:3] == ("over", "add", "max"))
check("1 copy = original image", close(cp("over_last", n=1), st4) and close(cp("under", ST3, n=1), st3))
err("unknown Op raises", lambda: cp("minimum"), "Op must be one of")
nd = run("PCG_COPCopyTransform", BX, "C", 2, "0 0", 0.0, 1.0, "0.5 0.5", "max", 0.0, scale_xy="2 1")
check("node: scale_xy passed all the way through", ext(L(nd)) == (4, 8))
nd = run("PCG_COPCopyTransform", ST4, "C", 2, tr4, 0.0, 1.0, "0.5 0.5", "over_last", 0.0)
check("node: Op menu gains over_last / under at the end", close(L(nd)[0, 8:10, 0], [4, 5])
      and M["PCG_COPCopyTransform"].INPUT_TYPES()["required"]["op"][0] == ["over", "add", "max", "over_last", "under"])

# ═══════════════════════════════════════════════════════ Mono
sec("Mono (the Luminance node's Operation)")
px = np.array([[[0.2, 0.4, 0.6, 0.5], [1.0, 0.0, 0.0, 1.0], [0.0, 1.0, 0.0, 0.25],
                [0.2, 0.4, 0.4, 0.0], [-0.3, 0.1, 0.9, 2.0]]])
RGBA = mk(C=px)
RGB = mk(C=px[..., :3])


def mono(op, img=RGBA, **kw):
    return L(PX.mono(img, "C", "o", op, **kw), "o").reshape(-1)


check("hdtv == the original luminance, bit-exact",
      np.array_equal(L(PX.mono(RGBA, "C", "o", "hdtv"), "o"), L(LV.luminance(RGBA, "C", "o"), "o")))
check("  = 0.2126 r + 0.7152 g + 0.0722 b", close(mono("hdtv"), px[0, :, :3] @ [0.2126, 0.7152, 0.0722]))
check("sgi = 0.3086 r + 0.6094 g + 0.0820 b", close(mono("sgi"), px[0, :, :3] @ [0.3086, 0.6094, 0.0820]))
check("ntsc = 0.299 r + 0.587 g + 0.114 b", close(mono("ntsc"), px[0, :, :3] @ [0.299, 0.587, 0.114]))
check("  on pure red / pure green the three weight sets give their own coefficients",
      close([mono(o)[1] for o in ("sgi", "ntsc", "hdtv")], [0.3086, 0.299, 0.2126])
      and close([mono(o)[2] for o in ("sgi", "ntsc", "hdtv")], [0.6094, 0.587, 0.7152]))
check("average: all existing channels (RGBA including alpha)", close(mono("average"), px[0].mean(-1))
      and close(mono("average")[0], 0.425))
check("  an RGB layer is the mean of the three", close(mono("average", RGB)[0], 0.4))
check("max / min: largest / smallest of the existing channels", close(mono("max"), px[0].max(-1)) and close(mono("min"), px[0].min(-1))
      and close(mono("max")[4], 2.0) and close(mono("min")[4], -0.3))
check("length: channels treated as a vector, take its length", close(mono("length"), np.sqrt((px[0] ** 2).sum(-1)))
      and close(mono("length", mk(C=np.array([[[3.0, 4.0, 12.0]]]))), [13.0]))
check("  single channel = absolute value (docs verbatim)", close(mono("length", mk(C=np.array([[[-0.7]]]))), [0.7]))
check("hue: red 0, green 1/3, (0.2,0.4,0.4) is cyan 0.5 (0-1, not degrees)",
      close(mono("hue")[[1, 2, 3]], [0.0, 1 / 3, 0.5]))
check("saturation: (0.2,0.4,0.6) -> (0.6 − 0.2) / 0.6; pure colors 1",
      close(mono("saturation")[[0, 1, 3]], [2 / 3, 1.0, 0.5]))
check("value: the largest rgb (alpha ignored)", close(mono("value")[[0, 1, 3]], [0.6, 1.0, 0.4]))
check("red / green / blue / alpha take one channel",
      close(mono("red"), px[0, :, 0]) and close(mono("green"), px[0, :, 1])
      and close(mono("blue"), px[0, :, 2]) and close(mono("alpha"), px[0, :, 3]))
check("  alpha of an RGB layer = 1 (channel expansion)", close(mono("alpha", RGB), [1.0] * 5))
M1 = mk(C=np.array([[[0.3], [0.8]]]))
check("  single-channel layer: red / green / blue are all it (Mono -> gray), alpha = 1",
      all(close(mono(o, M1), [0.3, 0.8]) for o in ("red", "green", "blue"))
      and close(mono("alpha", M1), [1, 1]))
UV = mk(C=np.array([[[0.3, 0.8]]]))
check("  two-channel layer: red / green are u / v, blue padded with 0, alpha = 1",
      close(mono("red", UV), [0.3]) and close(mono("green", UV), [0.8])
      and close(mono("blue", UV), [0.0]) and close(mono("alpha", UV), [1.0]))
check("  single-channel layer hue / saturation = 0, value = itself (gray)",
      close(mono("saturation", M1), [0, 0]) and close(mono("value", M1), [0.3, 0.8])
      and close(mono("hue", M1), [0, 0]))
check("  two-channel layer value = max(u, v, 0)", close(mono("value", UV), [0.8]))
check("  single-channel layer: all three luminance sets take channel 0 (old rule)",
      all(close(mono(o, M1), [0.3, 0.8]) for o in ("sgi", "ntsc", "hdtv")))
check("custom: Σ wᵢcᵢ, all four weights used", close(mono("custom", weights="1 2 3 4"), px[0] @ [1.0, 2.0, 3.0, 4.0]))
check("  RGB layer uses only the first three weights", close(mono("custom", RGB, weights="1 2 3 4"), px[0, :, :3] @ [1.0, 2.0, 3.0]))
check("  Normalize Weights: divided by the sum of the weights used (10 for RGBA, 6 for RGB)",
      close(mono("custom", weights="1 2 3 4", normalize=True), px[0] @ [0.1, 0.2, 0.3, 0.4])
      and close(mono("custom", RGB, weights="1 2 3 4", normalize=True), px[0, :, :3] @ [1 / 6, 2 / 6, 3 / 6]))
check("  negative control: not divided without normalizing", not close(mono("custom", weights="1 2 3 4"), mono("custom", weights="1 2 3 4", normalize=True), 1e-3))
check("  other modes don't read Weights / Normalize", np.array_equal(mono("average", weights="9 9 9 9", normalize=True), mono("average")))
check("  the default Weights are Rec.709 (custom + defaults == hdtv)", close(mono("custom"), mono("hdtv")))
err("  Normalize raises when the weights sum to 0", lambda: mono("custom", weights="1 -1 0 0", normalize=True), "sum to 0")
check("  sum 0 without Normalize still computes", close(mono("custom", weights="1 -1 0 0"), px[0, :, 0] - px[0, :, 1]))
err("unknown Operation raises", lambda: mono("luma"), "Operation must be one of")
check("all 15 modes differ (each is its own algorithm)",
      len({tuple(np.round(mono(o, weights="1 2 3 4"), 6)) for o in PX.MONO_OPS}) == 15)
check("empty Out Layer falls back to lum", "lum" in PX.mono(RGBA, "C", "", "average"))
it = M["PCG_COPLuminance"].INPUT_TYPES()["required"]["operation"]
check("node: menu order follows Houdini (SGI / NTSC / HDTV …), default hdtv",
      it[0] == ["sgi", "ntsc", "hdtv", "average", "max", "min", "length", "hue", "saturation",
                "value", "red", "green", "blue", "alpha", "custom"]
      and it[1]["default"] == "hdtv" and set(it[0]) == set(PX.MONO_OPS))
check("node: no operation given = the original Rec.709",
      np.array_equal(L(run("PCG_COPLuminance", RGBA, "C", "o"), "o"), L(LV.luminance(RGBA, "C", "o"), "o")))
nd = run("PCG_COPLuminance", RGBA, "C", "o", operation="custom", weights="1 2 3 4", normalize_weights=True)
check("node: operation / weights / normalize_weights passed all the way through",
      close(L(nd, "o").reshape(-1), px[0] @ [0.1, 0.2, 0.3, 0.4]))

# ═══════════════════════════════════════════════════════ Layer Merge (new node)
sec("Layer Merge: PCG_COPLayerCombine (per-pixel compositing of N inputs)")
x1, x2, x3 = rng.random((H, W, 3)), rng.random((H, W, 3)), rng.random((H, W, 3))
X1, X2, X3 = mk(C=x1, keep=ma), mk(C=x2), mk(C=x3)


def lc(op, imgs=(X1, X2, X3), **kw):
    return L(PX.layer_combine(list(imgs), "C", op, **kw))


check("add: the three inputs summed", close(lc("add"), x1 + x2 + x3))
check("average: divided by the input count", close(lc("average"), (x1 + x2 + x3) / 3))
check("  divided by 2 with two inputs", close(lc("average", (X1, X2)), (x1 + x2) / 2))
check("multiply: multiplied", close(lc("multiply"), x1 * x2 * x3))
check("min / max: smaller / larger per channel",
      close(lc("min"), np.minimum(np.minimum(x1, x2), x3)) and close(lc("max"), np.maximum(np.maximum(x1, x2), x3)))
check("  all six modes differ", len({lc(o).tobytes() for o in PX.COMBINE_LAYER_OPS}) == 6)
y1, y2, y3 = rng.random((H, W, 4)), rng.random((H, W, 4)), rng.random((H, W, 4))
Y1, Y2, Y3 = mk(C=y1), mk(C=y2), mk(C=y3)


def over2(top, bot):
    at, ab_ = top[..., 3:], bot[..., 3:]
    oa = at + ab_ * (1 - at)
    return np.concatenate([(top[..., :3] * at + bot[..., :3] * ab_ * (1 - at)) / oa, oa], -1)


check("over (RGBA): earlier inputs laid over later ones (two inputs)", close(lc("over", (Y1, Y2)), over2(y1, y2)))
check("  three inputs = 1 over (2 over 3)", close(lc("over", (Y1, Y2, Y3)), over2(y1, over2(y2, y3)), 1e-5))
check("  negative control: reversed order gives a different result", not close(lc("over", (Y1, Y2)), lc("over", (Y2, Y1)), 1e-3))
yo = y1.copy(); yo[..., 3] = 1.0
check("  opaque first input = the first input", close(lc("over", (mk(C=yo), Y2, Y3)), yo))
check("  over on non-RGBA: copies the last input, per the docs", close(lc("over"), x3) and close(lc("over", (X1, X2)), x2))
check("  a mix of RGB / RGBA also counts as non-RGBA: copies the last input", close(lc("over", (Y1, X2)), x2))
check("empty inputs skipped (None)", close(lc("add", (None, X1, None, X2)), x1 + x2))
check("  only one input connected = itself", close(lc("add", (None, X2)), x2) and close(lc("average", (X2,)), x2)
      and close(lc("over", (Y2,)), y2))
check("  no inputs connected = empty image", len(PX.layer_combine([None, None], "C", "add")) == 0)
big = rng.random((H * 2, W * 2, 3))
r = PX.layer_combine([X1, mk(C=big)], "C", "add")
check("resolution follows the first input (the first one connected), the rest are resampled to it", r.res == (W, H))
r = PX.layer_combine([None, mk(C=big), X1], "C", "add")
check("  when the first input is empty, the next one is used", r.res == (W * 2, H * 2))
check("1 channel broadcasts automatically", close(lc("multiply", (X1, mk(C=ma))), x1 * ma) and close(lc("add", (mk(C=ma), X1)), x1 + ma))
err("3 and 4 channels: no guessing", lambda: lc("add", (X1, Y1)), "channel counts don't match")
r = PX.layer_combine([X1, X2], "C", "add", "sum")
check("Output Layer: writes to a new layer, the original layer and the first input's other layers kept",
      close(L(r, "sum"), x1 + x2) and close(L(r), x1) and close(L(r, "keep"), ma))
r = PX.layer_combine([X1, X2], "C", "add")
check("  empty = overwrite Layer; the first input's other layers kept", close(L(r), x1 + x2) and close(L(r, "keep"), ma))
r = PX.layer_combine([mk(C=x1, h=ma), mk(C=x2, h=mb)], "h", "max")
check("Layer selects which layer of each input (other layers don't take part)", close(L(r, "h"), np.maximum(ma, mb)) and close(L(r), x1))
check("  empty Layer = C", close(L(PX.layer_combine([X1, X2], " ", "add")), x1 + x2))
err("unknown Operation raises", lambda: lc("subtract"), "Operation must be one of")
nd = run("PCG_COPLayerCombine", "C", "max", "", source2=X2, source5=X3)
check("node: all six inputs optional, empty ones skipped", close(L(nd), np.maximum(x2, x3)))
nd = run("PCG_COPLayerCombine", "C", "over", "o", source1=Y1, source2=Y2, source3=Y3, source4=None,
         source6=mk(C=yo))
check("node: input order = stacking order (1 on top, 6 at the bottom)",
      close(L(nd, "o"), over2(y1, over2(y2, over2(y3, yo))), 1e-5))
nd = run("PCG_COPLayerCombine", "C", "over", "", source4=Y1, source5=Y2, source6=Y3)
check("  inputs 4 / 5 / 6 also stack by number", close(L(nd), over2(y1, over2(y2, y3)), 1e-5))
nd = run("PCG_COPLayerCombine", "C", "add", "", source1=X1, source2=X2, source3=X3, source4=X1,
         source5=X2, source6=X3)
check("node: all six inputs connected", close(L(nd), 2 * (x1 + x2 + x3), 1e-5))
it = M["PCG_COPLayerCombine"].INPUT_TYPES()
check("node: Operation menu in Houdini's order, six optional inputs",
      it["required"]["operation"][0] == ["add", "average", "multiply", "min", "max", "over"]
      and list(it["optional"]) == [f"source{i}" for i in range(1, 7)])
import copernicus_map as CM                              # noqa: E402
check("mapping table: Layer Merge points to the new node; the old PCG_COPLayerMerge still exists, behaviour untouched",
      CM.M["Layer Merge"] == ("new", "PCG_COPLayerCombine") and "PCG_COPLayerMerge" in M
      and "x" in PX.layer_merge(mk(C=x1), mk(x=x2)))
icons = open(os.path.join(os.path.dirname(sys.modules["comfyui_pcg"].__file__), "web", "pcg_icons.js"), encoding="utf-8").read()
check("icon: COPLayerCombine has one, and its drawing function exists",
      'COPLayerCombine: "layer_combine"' in icons and "layer_combine(c)" in icons)

# ═══════════════════════════════════════════════════════ Panel
sec("Panel specs")
NODES = ("PCG_COPComposite", "PCG_COPMaskCombine", "PCG_COPCrop", "PCG_COPConvolve",
         "PCG_COPCopyTransform", "PCG_COPLuminance", "PCG_COPMirror", "PCG_COPLayerCombine")
for k in NODES:
    bad = PANEL.check_layout(k, M[k].INPUT_TYPES())
    check(f"{k}: spec self-check passes", not bad, bad)
from comfyui_pcg.panel_specs import SPECS                 # noqa: E402
for k in NODES:
    it = M[k].INPUT_TYPES()
    wid = [n for n, s in it["required"].items()
           if not (isinstance(s[0], str) and s[0] in ("COPIMAGE",))]
    sp = SPECS[k]
    miss = [n for n in wid if n not in sp["order"]]
    check(f"{k}: every widget is in order", not miss, miss)
    bad = []
    for n, s in it["required"].items():
        if isinstance(s[0], list) and "menu" in sp["inputs"].get(n, {}):
            if set(sp["inputs"][n]["menu"]) != set(s[0]):
                bad.append((n, sorted(set(sp["inputs"][n]["menu"]) ^ set(s[0]))))
    check(f"  every combo token has a Houdini label, no more, no less", not bad, bad)

# ═══════════════════════════════════════════════════════ Regression: old parameters bit-identical
sec("Regression: bit-identical to baseline commit (a9e114d) under old parameters")
DRIVER = r'''
import sys, pickle
sys.path.insert(0, sys.argv[1])
import fakecomfy
import numpy as np
from comfyui_pcg import NODE_CLASS_MAPPINGS as M
from comfyui_pcg.geo.cop import CopImage
rng = np.random.default_rng(7)
def im(**lay):
    f = next(iter(lay.values()))
    return CopImage(f.shape[1], f.shape[0], dict(lay))
H, W = 12, 16
A = im(C=rng.random((H, W, 3)), mask=rng.random((H, W, 1)), m2=rng.random((H, W, 1)) - 0.3)
B = im(C=rng.random((H, W, 3)), mask=rng.random((H, W, 1)))
A4 = im(C=rng.random((H, W, 4)))
B4 = im(C=rng.random((H, W, 4)))
def go(key, *a, **kw):
    r = fakecomfy.unwrap(getattr(M[key](), M[key].FUNCTION)(*a, **kw))[0]
    return {n: np.asarray(r.need(n)).copy() for n in r.names}
out = {}
for md in ("over", "add", "subtract", "difference", "multiply", "divide", "screen", "overlay",
           "softlight", "darken", "lighten", "replace"):
    out["cmp_" + md] = go("PCG_COPComposite", A, B, md, 0.7, "C", "", "mask", "", True, mask=B)
for md in ("over", "atop", "xor"):
    out["cmp4_" + md] = go("PCG_COPComposite", A4, B4, md, 1.0, "C", "", "mask", "o", False)
for op in ("union", "intersect", "add", "multiply", "subtract", "difference", "screen", "average"):
    for cl in (True, False):
        out[f"mc_{op}_{cl}"] = go("PCG_COPMaskCombine", A, "mask m2", op, "o", cl)
for bd in ("clamp", "wrap", "black"):
    out["crop_" + bd] = go("PCG_COPCrop", A, -3, 2, 14, 13, bd)
out["crop_in"] = go("PCG_COPCrop", A, 2, 1, 5, 4, "black")
for ps in ("custom", "box3", "gaussian3", "sharpen", "edge", "emboss", "sobel_x", "sobel_y"):
    for bd in ("clamp", "wrap", "black"):
        out[f"conv_{ps}_{bd}"] = go("PCG_COPConvolve", A, "C", ps, "0 1 0\n1 -4 1\n0 1 0", True, bd)
big = " ".join(str(v) for v in rng.random(81))
out["conv_fft"] = go("PCG_COPConvolve", A, "", "custom", big, False, "clamp")
for op in ("over", "add", "max"):
    out["ct_" + op] = go("PCG_COPCopyTransform", A4, "", 4, "0.1 0.05", 17.0, 0.9, "0.4 0.6", op, 0.2)
out["ct3"] = go("PCG_COPCopyTransform", A, "C", 3, "0.1 0", 0.0, 1.0, "0.5 0.5", "over", 0.0)
out["lum"] = go("PCG_COPLuminance", A, "C", "lum")
out["lum1"] = go("PCG_COPLuminance", A, "mask", "l")
for md in ("left_to_right", "right_to_left", "bottom_to_top", "top_to_bottom", "quad"):
    out["mir_" + md] = go("PCG_COPMirror", A, "", md, 0.37)
out["lm"] = go("PCG_COPLayerMerge", A, B4, "", "b_", True)
pickle.dump(out, open(sys.argv[2], "wb"))
'''
BASE = "a9e114d"
# during mutation testing it runs in parallel in copies without .git, where this section can't get the baseline -- skipped via an environment variable
# (normally unset; when skipped it isn't counted as passed, so no false green)
with tempfile.TemporaryDirectory() as td:
    _git = subprocess.run(["git", "-C", _R, "cat-file", "-e", BASE + "^{commit}"],
                          capture_output=True) if shutil.which("git") else None
    if _git is None or _git.returncode != 0:
        # the device layout has no git repo: baseline unavailable, this section is skipped (not counted as passed); runs as usual in the sandbox
        print(f"  (skipped: baseline commit {BASE} unavailable, no git repo)")
        print(f"\n{sum(OK)}/{len(OK)} passed")
        sys.exit(0 if all(OK) else 1)
    if os.environ.get("PCG_AUDIT_NO_BASELINE"):
        print("  (skipped: PCG_AUDIT_NO_BASELINE)")
        print(f"\n{sum(OK)}/{len(OK)} passed")
        sys.exit(0 if all(OK) else 1)
    old = os.path.join(td, "old")
    os.makedirs(old)
    ar = subprocess.run(f"git archive {BASE} comfyui_pcg fakecomfy.py | tar -x -C '{old}'",
                        shell=True, cwd=_R, capture_output=True, text=True)
    drv = os.path.join(td, "driver.py")
    open(drv, "w", encoding="utf-8").write(DRIVER)
    res = {}
    for tag, root in (("old", old), ("new", _R)):
        p = subprocess.run([sys.executable, "-B", drv, root, os.path.join(td, tag + ".pkl")],
                           capture_output=True, text=True, cwd=td,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        if p.returncode == 0:
            res[tag] = pickle.load(open(os.path.join(td, tag + ".pkl"), "rb"))
        else:
            print(p.stderr[-600:])
    check(f"baseline code obtained, both sides run (git archive {BASE})",
          ar.returncode == 0 and len(res) == 2, ar.stderr[:200])
    if len(res) == 2:
        o, n = res["old"], res["new"]
        diff = [k for k in o if k not in n or list(o[k]) != list(n[k])
                or any(not np.array_equal(o[k][l], n[k][l], equal_nan=True) for l in o[k])]
        check(f"output of {len(o)} sets of old parameters (layer set + every layer) bit-identical", len(o) >= 70 and not diff, diff[:8])

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
