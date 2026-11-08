"""
Keyframe channels -- every criterion is **analytically provable**; none of them is "looks right".

This has one convenient property: correctness of interpolation can be proven by polynomial reproduction, no eyeballing needed.

    1) Passes through keyframes   evaluating at a keyframe must **equal** the keyframe value (`==`, not approximately)
    2) Cubic Hermite reproduces cubic polynomials
       Given end values and end derivatives, the cubic Hermite basis spans exactly the space of cubic polynomials --
       so keying any cubic curve with its values and derivatives must interpolate to **exactly that curve, point by point**
    3) Auto tangents reproduce quadratic polynomials (arbitrary spacing)
       The module's segment-length-weighted difference is the exact derivative for quadratics; combined with (2):
       given only values and no tangents, cubic reproduces any parabola point by point -- even with unevenly spaced keyframes.
       **Reverse check**: swapping in the textbook Catmull-Rom formula breaks it immediately (measured error 5.08).
    4) quintic reproduces linear polynomials
       Its second derivatives at both ends are pinned to 0, so it is only exact for polynomials with zero second derivative. This is also
       the reverse check for "quintic is not cubic".
    5) Cycling is bit-exactly periodic
       cycle is implemented by folding the frame back into the range, so f(x+T) and f(x) must be `array_equal`,
       not "small error". cycleoffset: the difference is identically one period's rise.
    6) C¹ / C² continuity judged by **convergence order**, not a made-up tolerance
       Take difference quotients on both sides of a keyframe and halve the step: the first difference should drop as O(h) (continuous value),
       cubic's left/right derivative difference should drop to 0 as O(h). Tolerance-based checks have bitten other batches:
       loosen the tolerance a little and the criterion always holds.

Also pins two things that "fail silently":

  · **Vectorized and scalar must be bit-identical**. Evaluation masks points grouped by interpolation type; if the grouping
    is wrong most points are still right, only points of one interpolation type are wrong -- spot checks would miss it.
  · **Text order does not affect the result**. Keyframes are used after sorting; writing them out of order must give a bit-identical
    curve.
"""
import os
import sys
_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
import numpy as np                                      # noqa: E402
import fakecomfy                                        # noqa: F401,E402

from comfyui_pcg.geo import channel as CH               # noqa: E402
from comfyui_pcg import expr as EX                       # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag, kind=Exception):
    try:
        fn()
        check(name, False, "no error raised")
    except kind as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:90]}")


def sec(t):
    print("\n" + "═" * 28 + " " + t)


def spec_of(fr, vals, interp=None, slopes=None):
    """Build channel text from frames and values. .17g guarantees a lossless text round trip."""
    out = []
    for i, (f, v) in enumerate(zip(fr, vals)):
        s = f"{f:.17g}:{v:.17g}"
        if interp:
            s += ":" + interp
        if slopes is not None:
            s += f"@{slopes[i]:.17g}"
        out.append(s)
    return "  ".join(out)


# A deliberately **unevenly spaced** set of keyframes. With even spacing the weighted difference equals Catmull-Rom,
# and the strongest criterion in this suite would test nothing.
FR = np.array([0.0, 3.0, 7.0, 8.0, 15.0, 22.0])
X = np.linspace(-6.0, 28.0, 401)
XIN = np.linspace(0.0, 22.0, 301)         # inside the range only


# ════════════════════════════════════════════════════════════ 1. Parsing
sec("Parsing")
f, v, c, s = CH.parse("12:1  0:0  24:0")
check("out-of-order input is sorted", np.array_equal(f, [0, 12, 24]))
check("  values sorted along with it", np.array_equal(v, [0, 1, 0]))
check("default interpolation is cubic", (c == CH._CODE["cubic"]).all())
f2, v2, c2, s2 = CH.parse("0:0:linear 12:1:ease 24:0")
check("each key can have its own interpolation",
      list(c2) == [CH.LINEAR, CH.EASE, CH.CUBIC])
check("without @slope it is recorded as nan (= auto)", np.isnan(s2).all())
f3, v3, c3, s3 = CH.parse("0:0@2.5  12:1")
check("@slope is parsed", s3[0] == 2.5 and np.isnan(s3[1]))
f4, v4, _, _ = CH.parse("0:0  12:9  12:1")
check("the same frame written twice: **the later one wins**", len(f4) == 2 and v4[1] == 1.0,
      f"{v4}")
f5, v5, _, _ = CH.parse("0:1")
check("a single keyframe is a legal channel", len(f5) == 1)
check("  a single-key channel has that value at every frame",
      np.array_equal(CH.eval_spec("5:1.25", X), np.full(len(X), 1.25)))
check("commas treated as whitespace (as pasted from a spreadsheet)",
      np.array_equal(CH.parse("0:0, 12:1")[0], [0, 12]))

err("empty channel raises", lambda: CH.parse("  "), "channel is empty")
err("missing colon raises", lambda: CH.parse("12"), "frame:value")
err("non-numeric frame raises", lambda: CH.parse("a:1"), "not a frame number")
err("non-numeric value raises", lambda: CH.parse("1:x"), "is not a number")
err("bad interpolation name raises", lambda: CH.parse("1:0:smooth"), "unknown interpolation")
err("non-numeric value after @ raises", lambda: CH.parse("1:0@x"), "slope")
err("bad default interpolation raises", lambda: CH.parse("1:0", "bogus"), "Interpolation must be one of")
err("bad extrapolate raises",
    lambda: CH.eval_spec("0:0 1:1", 0.5, "cubic", "bogus"), "Extrapolation must be one of")


# ══════════════════════════════════════════════════ 2. Passes through keyframes (exact equality)
sec("Passes through keyframes")
for name in CH.INTERPS:
    sp = spec_of(FR, [0.0, 2.0, -1.0, 3.5, 1.0, 0.0], name)
    got = CH.eval_spec(sp, FR)
    want = np.array([0.0, 2.0, -1.0, 3.5, 1.0, 0.0])
    if name == "constant":
        ok = np.array_equal(got, want)      # steps must also take the key value at the key
    else:
        ok = np.array_equal(got, want)
    check(f"{name:9s}**exactly equals** the keyframe value at keyframes", ok,
          f"max difference {np.abs(got - want).max():.3g}")

# reverse check: nudge one key value and this criterion must fail
sp_bad = spec_of(FR, [0.0, 2.0001, -1.0, 3.5, 1.0, 0.0], "cubic")
check("  [reverse check] after changing a key value by 1e-4 this criterion no longer holds",
      not np.array_equal(CH.eval_spec(sp_bad, FR),
                         np.array([0.0, 2.0, -1.0, 3.5, 1.0, 0.0])))


# ═══════════════════════════════════════════════════ 3. Polynomial reproduction
sec("Polynomial reproduction (the hardest criteria in this suite)")

def cubic_poly(x):
    return 1.7 * x ** 3 - 2.3 * x ** 2 + 0.8 * x - 4.0


def cubic_deriv(x):
    return 5.1 * x ** 2 - 4.6 * x + 0.8


def quad_poly(x):
    return 0.7 * x ** 2 - 3.1 * x + 5.0


def lin_poly(x):
    return 2.5 * x - 1.0


# (2) cubic Hermite + exact end derivatives -> reproduces cubic polynomials point by point
sp = spec_of(FR, cubic_poly(FR), "cubic", cubic_deriv(FR))
e = np.abs(CH.eval_spec(sp, XIN) - cubic_poly(XIN)).max()
scale = np.abs(cubic_poly(XIN)).max()
check("cubic + exact tangents reproduces **cubic** polynomials point by point", e < 1e-11 * scale,
      f"relative error {e / scale:.2e}")

# (3) auto tangents -> reproduce quadratic polynomials, keyframes deliberately unevenly spaced
sp = spec_of(FR, quad_poly(FR), "cubic")
e = np.abs(CH.eval_spec(sp, XIN) - quad_poly(XIN)).max()
scale = np.abs(quad_poly(XIN)).max()
check("cubic + **auto** tangents reproduces quadratic polynomials point by point (uneven keyframes)",
      e < 1e-11 * scale, f"relative error {e / scale:.2e}")


def catmull_rom(fr, val):
    """Textbook formula: only the true derivative of a quadratic when evenly spaced."""
    m = np.empty(len(fr))
    m[1:-1] = (val[2:] - val[:-2]) / (fr[2:] - fr[:-2])
    m[0] = (val[1] - val[0]) / (fr[1] - fr[0])
    m[-1] = (val[-1] - val[-2]) / (fr[-1] - fr[-2])
    return m


fp, vp, cp, _ = CH.parse(sp)
got_cr = CH.evaluate(fp, vp, cp, catmull_rom(fp, vp), XIN)
e_cr = np.abs(got_cr - quad_poly(XIN)).max()
check("  [reverse check] swapping in the Catmull-Rom formula breaks it immediately", e_cr > 1.0,
      f"absolute error {e_cr:.3g}")
# with evenly spaced keyframes the two formulas are equivalent in the **interior** -- this shows the reverse check above is not "any
# other formula fails"; the difference comes exactly from "uneven spacing" and "the ends".
#
# The first version wrote this as "fully equivalent when evenly spaced" and failed: Catmull-Rom's **end** tangents are
# one-sided differences, not the true derivative even when evenly spaced (measured -0.3 vs true -3.1). So look at them separately:
# in interior segments both are exact, in end segments only the weighted formula is.
FRE = np.arange(6.0) * 4                 # 0 4 8 12 16 20, evenly spaced
XE = np.linspace(0.0, 20.0, 201)
XMID = XE[(XE >= 4.0) & (XE <= 16.0)]    # interior segments only
sp_e = spec_of(FRE, quad_poly(FRE), "cubic")
fe, ve, ce, _ = CH.parse(sp_e)
got_cr_e = CH.evaluate(fe, ve, ce, catmull_rom(fe, ve), XMID)
check("  [reverse check] evenly spaced, Catmull-Rom is also exact in **interior segments** (the difference only comes from uneven spacing)",
      np.abs(got_cr_e - quad_poly(XMID)).max() < 1e-10,
      f"{np.abs(got_cr_e - quad_poly(XMID)).max():.2e}")
check("  [reverse check] but its **end** tangents are wrong even when evenly spaced (one-sided difference)",
      abs(catmull_rom(fe, ve)[0] - (1.4 * FRE[0] - 3.1)) > 1.0
      and abs(CH.auto_slopes(fe, ve, np.full(len(fe), np.nan))[0]
              - (1.4 * FRE[0] - 3.1)) < 1e-10)
check("  the weighted formula is exact over the whole range (including end segments)",
      np.abs(CH.eval_spec(sp_e, XE) - quad_poly(XE)).max() < 1e-10)

# (4) quintic: second derivatives pinned to 0 at both ends -> only exact for linear
sp = spec_of(FR, lin_poly(FR), "quintic", np.full(len(FR), 2.5))
e = np.abs(CH.eval_spec(sp, XIN) - lin_poly(XIN)).max()
check("quintic + exact tangents reproduces **linear** polynomials point by point",
      e < 1e-11 * np.abs(lin_poly(XIN)).max(), f"absolute error {e:.2e}")
sp_q = spec_of(FR, quad_poly(FR), "quintic")
sp_c = spec_of(FR, quad_poly(FR), "cubic")
check("  [reverse check] quintic is **not** exact for quadratics (it really is not cubic)",
      np.abs(CH.eval_spec(sp_q, XIN) - quad_poly(XIN)).max() > 1e-6)
check("  [reverse check] so the quintic and cubic curves differ",
      not np.allclose(CH.eval_spec(sp_q, XIN), CH.eval_spec(sp_c, XIN)))

# linear is piecewise straight: checked against the closed form of linear interpolation between the segment ends
fp, vp, _, _ = CH.parse(spec_of(FR, quad_poly(FR), "linear"))
i = np.clip(np.searchsorted(fp, XIN, side="right") - 1, 0, len(fp) - 2)
want = vp[i] + (vp[i + 1] - vp[i]) * (XIN - fp[i]) / (fp[i + 1] - fp[i])
check("linear equals the closed form of the piecewise straight line",
      np.abs(CH.eval_spec(spec_of(FR, quad_poly(FR), "linear"), XIN)
             - want).max() < 1e-12)


# ═══════════════════════════════════════════════════ 4. Shape of each mode
sec("The shapes of the seven interpolations")
A, B = 10.0, 20.0                     # one segment: frame 10 -> 20, value 0 -> 1
one = f"{A:g}:0  {B:g}:1"
mid = 15.0
xs = np.linspace(A, B, 201)


def curve(name):
    return CH.eval_spec(f"{A:g}:0:{name}  {B:g}:1", xs)


check("constant holds the left value within the segment, jumps to 1 only at the right end",
      np.array_equal(curve("constant")[:-1], np.zeros(200))
      and curve("constant")[-1] == 1.0)
check("linear midpoint is exactly 0.5",
      abs(CH.eval_spec(f"{one}", mid) * 0 +
          CH.eval_spec(f"{A:g}:0:linear {B:g}:1", mid) - 0.5) < 1e-15)
ease = curve("ease")
check("ease midpoint 0.5, zero tangents at both ends (smoothstep)",
      abs(ease[100] - 0.5) < 1e-12
      and abs(ease[1] - ease[0]) < abs(ease[101] - ease[100]) * 0.1)
ein, eout = curve("easein"), curve("easeout")
check("easein is slow at the **start** (starts slower than constant speed)", ein[100] < 0.5 - 1e-9,
      f"midpoint {ein[100]:.4f}")
check("easeout is slow at the **end** (starts faster than constant speed)", eout[100] > 0.5 + 1e-9,
      f"midpoint {eout[100]:.4f}")
check("  the two mirror each other (easein(t) == 1 - easeout(1-t))",
      np.abs(ein - (1.0 - eout[::-1])).max() < 1e-12)
for name in ("linear", "ease", "easein", "easeout"):
    y = curve(name)
    check(f"  {name:8s}monotonic, stays within [0,1]",
          y.min() >= -1e-12 and y.max() <= 1 + 1e-12
          and (np.diff(y) >= -1e-12).all())
# cubic overshoot is a **known cost**, pinned as a criterion (so nobody "fixes it in passing" and silently changes behaviour)
over = CH.eval_spec("0:0  10:0  20:1  30:1", np.linspace(0, 30, 301))
check("cubic **overshoots** on step data -- the price of auto tangents being exact for quadratics",
      over.max() > 1.0 + 1e-3, f"max {over.max():.4f}")
flat = CH.eval_spec("0:0@0  10:0@0  20:1@0  30:1@0",
                    np.linspace(0, 30, 301))
check("  pinning the tangent flat with @0 suppresses it", flat.max() <= 1.0 + 1e-12,
      f"max {flat.max():.6f}")


# ════════════════════════════════════════════════════ 5. Continuity (convergence order)
sec("Continuity (judged by convergence order, no made-up tolerance)")


def jump(name, h, order=1):
    """Difference of the order-th difference quotients on both sides of keyframe 12."""
    sp = spec_of(FR, [0.0, 2.0, -1.0, 3.5, 1.0, 0.0], name)
    k = 15.0                      # an interior keyframe
    if order == 0:
        return abs(CH.eval_spec(sp, k + h) - CH.eval_spec(sp, k - h))
    L = (CH.eval_spec(sp, k) - CH.eval_spec(sp, k - h)) / h
    Rg = (CH.eval_spec(sp, k + h) - CH.eval_spec(sp, k)) / h
    return abs(Rg - L)


for name in ("linear", "ease", "cubic", "quintic"):
    a, b = jump(name, 1e-2, 0), jump(name, 1e-3, 0)
    check(f"{name:8s}value is continuous (step /10, the jump across the keyframe also about /10)",
          b < a * 0.2 + 1e-14, f"{a:.3e} -> {b:.3e}")
for name in ("cubic", "quintic"):
    a, b = jump(name, 1e-2, 1), jump(name, 1e-3, 1)
    check(f"{name:8s}first derivative is also continuous (C¹)", b < a * 0.2 + 1e-12,
          f"{a:.3e} -> {b:.3e}")
a, b = jump("linear", 1e-2, 1), jump("linear", 1e-3, 1)
check("  [reverse check] linear has a kink at keyframes, the first-derivative difference does **not** shrink with the step",
      b > a * 0.5, f"{a:.3e} -> {b:.3e}")
# quintic's second derivative at keyframes is 0 (by construction), cubic's generally is not.
#
# **The first version wrote this as "|second difference quotient| < 1e-4", and at h=1e-3 it measured 3.6e-4 -- the criterion
# failed while the implementation was right.** Reason: p''(k)=0 but p''' is discontinuous across the keyframe (quintic is
# C², not C³), so the central second difference quotient is h³·Δp'''/6 / h² = O(h), not O(h²).
# So the correct criterion is **convergence**: shrink the step tenfold and the measured second derivative shrinks too;
# cubic converges to a nonzero constant instead. No tolerance needs to be made up.
def d2_at(sp, k, h):
    return (CH.eval_spec(sp, k + h) - 2 * CH.eval_spec(sp, k)
            + CH.eval_spec(sp, k - h)) / h ** 2


VS = [0.0, 2.0, -1.0, 3.5, 1.0, 0.0]
sp_q5 = spec_of(FR, VS, "quintic")
sp_c3 = spec_of(FR, VS, "cubic")
q1, q2 = abs(d2_at(sp_q5, 15.0, 1e-2)), abs(d2_at(sp_q5, 15.0, 1e-3))
c1, c2 = abs(d2_at(sp_c3, 15.0, 1e-2)), abs(d2_at(sp_c3, 15.0, 1e-3))
check("quintic's second derivative at keyframes **converges to 0** (C², by construction)", q2 < q1 * 0.2,
      f"{q1:.3e} -> {q2:.3e}")
check("  [reverse check] cubic's second derivative converges to a nonzero constant (not C²)",
      abs(c2 - c1) < abs(c1) * 0.1 and abs(c2) > 0.1,
      f"{c1:.3e} -> {c2:.3e}")


# ══════════════════════════════════════════════════════ 6. Outside the range
sec("Outside the range (cycling is bit-exact)")
SP = "0:0  6:2  12:1  24:0"
T = 24.0
xo = np.array([-37.3, -24.0, -11.5, -0.25, 3.3, 24.25, 30.0, 61.7])

hold = CH.eval_spec(SP, xo, extrapolate="hold")
check("hold: everything on the left equals the first key value",
      np.array_equal(hold[xo < 0], np.zeros((xo < 0).sum())))
check("  everything on the right equals the last key value",
      np.array_equal(hold[xo > T], np.zeros((xo > T).sum())))

# periodicity is tested at two levels.
#
# **Bit-exact on integer frames**: integer modulo has no rounding, and the timeline gives integer frames --
# in real use this holds strictly, so test it strictly.
# **Fractional frames only up to float rounding**: np.mod(-37.3,24) is 10.700000000000003,
# np.mod(-13.3,24) is 10.7, one ulp apart. The first version made this level bit-exact too; the criterion
# failed while the implementation was right -- folding back into the range guarantees exactly "precise up to the rounding of the modulo".
xi = np.array([-48.0, -37.0, -24.0, -11.0, 0.0, 3.0, 24.0, 30.0, 61.0])
cyc_i = CH.eval_spec(SP, xi, extrapolate="cycle")
check("cycle: on **integer frames** f(x+T) and f(x) are bit-identical",
      np.array_equal(cyc_i, CH.eval_spec(SP, xi + T, extrapolate="cycle")))
check("  also bit-identical three periods back",
      np.array_equal(cyc_i, CH.eval_spec(SP, xi - 3 * T,
                                         extrapolate="cycle")))
cyc = CH.eval_spec(SP, xo, extrapolate="cycle")
check("  on fractional frames exact up to the float rounding of the modulo (not bit-exact)",
      np.abs(cyc - CH.eval_spec(SP, xo + T,
                                extrapolate="cycle")).max() < 1e-12,
      f"max difference {np.abs(cyc - CH.eval_spec(SP, xo + T, extrapolate='cycle')).max():.2e}")
check("  values inside the range are unaffected by cycle",
      np.array_equal(CH.eval_spec(SP, XIN, extrapolate="cycle"),
                     CH.eval_spec(SP, XIN, extrapolate="hold")))

SPO = "0:0  12:5  24:9"            # the rise over one period = 9
d0 = CH.eval_spec(SPO, xo, extrapolate="cycleoffset")
d1 = CH.eval_spec(SPO, xo + T, extrapolate="cycleoffset")
check("cycleoffset: f(x+T) - f(x) is identically one period's rise",
      np.abs((d1 - d0) - 9.0).max() < 1e-12,
      f"max deviation {np.abs((d1 - d0) - 9.0).max():.2e}")
check("  [reverse check] cycle has no such accumulation (difference identically 0)",
      np.abs(CH.eval_spec(SPO, xo + T, extrapolate="cycle")
             - CH.eval_spec(SPO, xo, extrapolate="cycle")).max() < 1e-12)

mir = lambda x: CH.eval_spec(SP, x, extrapolate="mirror")   # noqa: E731
dd = np.array([0.3, 2.7, 5.0, 11.9])
check("mirror: symmetric about the first key",
      np.abs(mir(-dd) - mir(dd)).max() < 1e-12)
check("  also symmetric about the last key",
      np.abs(mir(T + dd) - mir(T - dd)).max() < 1e-12)
check("  the period is 2T", np.abs(mir(xo) - mir(xo + 2 * T)).max() < 1e-12)

# linear extrapolation: uses **the segment function's own** end derivative, so it continues without a kink.
# the criterion is again convergence order: the difference of first difference quotients across the end shrinks with the step
for name in ("linear", "ease", "cubic", "constant"):
    sp = f"0:0:{name}  6:2  12:1  24:0:{name}"

    def jmp(hh, sp=sp):
        L = (CH.eval_spec(sp, 0.0, extrapolate="linear")
             - CH.eval_spec(sp, -hh, extrapolate="linear")) / hh
        Rg = (CH.eval_spec(sp, hh, extrapolate="linear")
              - CH.eval_spec(sp, 0.0, extrapolate="linear")) / hh
        return abs(Rg - L)
    a, b = jmp(1e-2), jmp(1e-3)
    check(f"linear extrapolation continues C¹ at the first key ({name} segment)", b < a * 0.2 + 1e-9,
          f"{a:.3e} -> {b:.3e}")
check("  [reverse check] hold extrapolation **has** a kink at the end",
      abs((CH.eval_spec(SP, 1e-3, extrapolate="hold")
           - CH.eval_spec(SP, 0.0, extrapolate="hold")) / 1e-3) > 0.1)


# ═══════════════════════════════════════════════════ 7. The two silent failures
sec("Vectorization / order independence (the two things that fail silently)")
SPM = ("0:0:linear  4:2:ease  9:1:cubic  13:-1:quintic  "
       "18:2:constant  22:0:easein  26:1:easeout  30:0")
xv = np.linspace(-4, 34, 257)
for ex in CH.EXTRAPS:
    vec = CH.eval_spec(SPM, xv, extrapolate=ex)
    one = np.array([CH.eval_spec(SPM, float(t), extrapolate=ex) for t in xv])
    check(f"{ex:12s}vectorized and per-point calls are **bit-identical**",
          np.array_equal(vec, one),
          f"max difference {np.abs(vec - one).max():.3g}")

toks = SPM.split()
rng = np.random.default_rng(7)
for k in range(3):
    sh = list(toks)
    rng.shuffle(sh)
    check(f"shuffled text order ({k}) gives bit-identical results",
          np.array_equal(CH.eval_spec(SPM, xv),
                         CH.eval_spec("  ".join(sh), xv)))
check("calling twice with the same input is bit-identical (pure function, no hidden state)",
      np.array_equal(CH.eval_spec(SPM, xv), CH.eval_spec(SPM, xv)))
check("scalar in, scalar out (0-d); array in, same shape out",
      np.ndim(CH.eval_spec(SPM, 3.0)) == 0
      and CH.eval_spec(SPM, xv.reshape(-1, 1)).shape == (len(xv), 1))
check("parse is not modified by evaluate (auto_slopes returns a new array)",
      np.isnan(CH.parse(SPM)[3]).all())
f9, v9, c9, s9 = CH.parse(SPM)
s9_before = s9.copy()
CH.evaluate(f9, v9, c9, s9, xv)
check("  evaluate also does not modify the slope array passed in in place",
      np.array_equal(np.isnan(s9), np.isnan(s9_before)))


# ══════════════════════════════════════════════════════ 8. Auto tangents themselves
sec("auto_slopes")
fr = np.array([0.0, 3.0, 7.0, 8.0, 15.0])
va = quad_poly(fr)
m = CH.auto_slopes(fr, va, np.full(len(fr), np.nan))
want = 1.4 * fr - 3.1                       # derivative of quad_poly
check("auto tangents equal the true derivative of the quadratic at **all** keyframes (including both ends)",
      np.abs(m - want).max() < 1e-10, f"max difference {np.abs(m - want).max():.2e}")
check("  [reverse check] Catmull-Rom is wrong both at the ends and in the interior",
      np.abs(catmull_rom(fr, va) - want).max() > 0.1,
      f"max difference {np.abs(catmull_rom(fr, va) - want).max():.3g}")
mix = CH.auto_slopes(fr, va, np.array([np.nan, 99.0, np.nan, np.nan, np.nan]))
check("explicitly given tangents are not overwritten, only the nan ones are filled", mix[1] == 99.0
      and abs(mix[0] - want[0]) < 1e-10)
check("with two keyframes both ends use the slope of that segment",
      np.array_equal(CH.auto_slopes(np.array([0.0, 4.0]),
                                    np.array([1.0, 3.0]),
                                    np.full(2, np.nan)), [0.5, 0.5]))
check("the tangent of a single keyframe is 0",
      CH.auto_slopes(np.array([2.0]), np.array([5.0]),
                     np.array([np.nan]))[0] == 0.0)


# ══════════════════════════════════════════════════════ 9. Nodes
sec("Nodes")
ch1 = EX.PCG_Channel()
val, iv, txt = ch1.run(12.0, "0:0  12:1.5  24:0", "cubic", "hold", 1.0, 0.0)
check("Channel gives the keyframe value at a keyframe", val == 1.5)
check("  the int output is rounded", iv == 2, iv)
check("  info has the key count and range", "3 keys" in txt and "0..24" in txt, txt)
val2, _, _ = ch1.run(12.0, "0:0  12:1.5  24:0", "cubic", "hold", 2.0, 10.0)
check("scale / offset applied at the output: 1.5×2+10", val2 == 13.0, val2)
check("frame can be fractional (the timeline gives frame_f)",
      isinstance(ch1.run(6.5, "0:0  12:1.5  24:0", "linear", "hold",
                         1.0, 0.0)[0], float))
check("the interp widget is the default interpolation, the one written in the text takes priority",
      ch1.run(6.0, "0:0:linear  12:1.5  24:0", "constant", "hold",
              1.0, 0.0)[0] == 0.75)

ch3 = EX.PCG_Channel3()
x, y, z, txt3 = ch3.run(12.0, "0:0  24:6", "0:0  12:2  24:0", "",
                        "linear", "hold", 1.0, 0.0)
check("Channel3 evaluates each of the three separately", (x, y, z) == (3.0, 2.0, 0.0), (x, y, z))
check("  an empty one is 0, no error", z == 0.0)
check("  info lists the three components", "x=3" in txt3 and "y=2" in txt3, txt3)
err("Channel gives a clear error for a malformed channel",
    lambda: ch1.run(0.0, "0-0", "cubic", "hold", 1.0, 0.0), "frame:value")

# chained with the Frame node: timeline -> Frame -> Channel, the way it is actually wired
fr_node = EX.PCG_Frame()
frame, frame_f, t, n, secs = fr_node.run(6, 0, 24, 24.0)
check("Frame's frame_f can feed Channel directly (both FLOAT)",
      CH.value_at("0:0  24:24", frame_f, "linear") == 6.0)
check("  Frame's frame is INT and cannot connect to a FLOAT port -- that is why frame_f must exist",
      isinstance(frame, int) and isinstance(frame_f, float))

spec = EX.PCG_Channel.INPUT_TYPES()["required"]
check("Channel's frame is the first input (the one most often promoted to a port)",
      list(spec)[0] == "frame")
check("  the frame port type is FLOAT", spec["frame"][0] == "FLOAT")
check("  the interp combo items are INTERPS", spec["interp"][0] == list(CH.INTERPS))
check("  the extrapolate combo items are EXTRAPS",
      spec["extrapolate"][0] == list(CH.EXTRAPS))


print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
