"""
Keyframe channels -- the **backbone** of Houdini animation, described in one line of text.

In Houdini the foundation of animation is not some SOP but the **channel**: keyframes on parameters,
each keyframe carrying an interpolation function, read with `ch("../cam/tx")`. Time operators like Trail / Time Blend /
Retime are all built on "a parameter is a function of time". Until now this plugin only had
a timeline (Frame node + playbar) and expressions, **no keyframes** -- to make a camera "push in over the first 12 frames,
hold for 6, then pull out" you had to hand-write a piecewise expression, unreadable even if you managed to write it.

    0:0  12:1.5:ease  18:1.5  24:0        <- this is the motion described above

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Why text, rather than a draggable curve editor like Houdini's
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Same reason as `ramp.py`, only stronger: litegraph's `widgets_values` is a list of **flat
scalars**, and a curve doesn't fit in it. A real control would mean managing serialization, undo and copy-paste ourselves --
all that trouble for a half-broken control. A line of text can be copy-pasted, put under version control, assembled by upstream nodes
with expressions, and its diffs are readable. The price is that the curve can't be dragged; you have to work it out as you write.

To actually see the curve: connect the Channel output to the parameter that needs it; dragging the playbar is looking at the curve.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Syntax
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    frame:value[:interp][@slope]      space-separated, any order (gets sorted)

    0:0  24:360                       one full turn at constant speed
    0:0  12:1:ease  24:0              an ease-in/ease-out round trip
    0:0  10:1:constant  20:1          jumps to 1 at frame 10 (step)
    0:0@0  12:1  24:0@0               forces horizontal tangents at start / end

**The interpolation written on a keyframe governs the segment to its right.** The interpolation on the last keyframe has no
segment to govern; writing it has no effect (no error -- writing it out of habit is more intuitive). In Houdini each key
has two functions, in / out; here there is only out: the behaviour when two functions on one key conflict
(who wins) is one of the easiest pitfalls in Houdini, and one function is enough to express all common curves.

`@slope` is the tangent at this keyframe, in **value / frame**. Only the cubic / quintic
interpolations use it; if omitted it is computed automatically (see below).

Interpolation:
    constant  step, holds the left value until the next key
    linear    straight line
    ease      zero tangents at both ends (smoothstep), the most common "ease in/out"
    easein    eases at the **start** (t^2, accelerating away)
    easeout   eases at the **end** (decelerating into place)
    cubic     cubic Hermite, tangents automatic or given with @ -- the default
    quintic   quintic Hermite, zero second derivatives at both ends, C^2 continuous

    The meanings of easein / easeout have always been confused between packages, so here they are fixed:
    the name says **which end eases**. easein eases at the start, easeout at the end.

Outside the range (extrapolate):
    hold         hold the end values (default)
    linear       extend along the **actual tangent** at the end (C^1 continuation, no kink)
    cycle        loop the whole range
    cycleoffset  loop and accumulate one period's offset each cycle (this is what makes a walk cycle move forward)
    mirror       ping-pong back and forth

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Automatic tangents use a **non-uniformly weighted difference**, not Catmull-Rom
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The textbook Catmull-Rom tangent is (v[i+1] - v[i-1]) / (f[i+1] - f[i-1]). It is the true derivative of a quadratic only
when **keyframes are evenly spaced**; as soon as the spacing changes (and hand-set keyframes are almost never evenly spaced)
it is off, showing up as "I only added a key in the middle that doesn't change the path, yet the motion changed".

Here a three-point difference weighted by segment length is used:

    m[i] = (h[i]·d[i−1] + h[i−1]·d[i]) / (h[i−1] + h[i])

where d is each segment's slope and h is the segment length. These weights exactly extrapolate d[i-1] (= derivative at the left segment's midpoint) and
d[i] (= derivative at the right segment's midpoint) linearly onto f[i] -- so for a quadratic with **arbitrary spacing**
it is the exact derivative. The ends use a one-sided formula that is likewise exact up to quadratics.

The tests use this as the criterion: take any parabola and any set of unevenly spaced keyframes; the cubic interpolation
must **equal the parabola point by point** (to 1e-12). Switching to the Catmull-Rom formula breaks it immediately
-- that is the negative control for this criterion.

The cost, as usual, stated plainly: being exact for quadratics means it **overshoots**. Step data like 0 0 1 1 with cubic
bulges out past the corners; to hold it down, write `@0` to pin the tangents of those two keys horizontal, or use ease.
"""
from __future__ import annotations

import numpy as np

INTERPS = ("constant", "linear", "ease", "easein", "easeout",
           "cubic", "quintic")
EXTRAPS = ("hold", "linear", "cycle", "cycleoffset", "mirror")

# Interpolation -> internal code. Codes are used for vectorized evaluation: group by code into masks
# and compute a large batch at once, instead of if/else per keyframe.
_CODE = {name: i for i, name in enumerate(INTERPS)}
CONSTANT, LINEAR, EASE, EASEIN, EASEOUT, CUBIC, QUINTIC = range(7)

EXAMPLE = "0:0  12:1:ease  24:0"


# ══════════════════════════════════════════════════════════════════ parsing
def parse(spec, default_interp="cubic"):
    """
    "frame:value[:interp][@slope] ..." -> (f, v, code, slope)

    f is strictly increasing (sorted + deduplicated); nan in slope means "automatic".

    When the same frame is written twice **the later one wins**: text is edited left to right, and appending an override at the end
    is the most natural way to write it. (ramp.py keeps the earlier one -- those are colour stops, where at a coincident position the earlier one
    feels more like the "main" stop; this is a timeline, where the later one feels more like "the edited one".)
    """
    if default_interp not in _CODE:
        raise ValueError(f"Interpolation must be one of {INTERPS}, got '{default_interp}'")
    toks = [t for t in str(spec or "").replace(",", " ").split() if t]
    if not toks:
        raise ValueError(f"The channel is empty. Syntax: {EXAMPLE}")
    fs, vs, cs, ss = [], [], [], []
    for t in toks:
        body, slope = t, np.nan
        if "@" in body:
            body, _, sl = body.partition("@")
            try:
                slope = float(sl)
            except ValueError:
                raise ValueError(
                    f"Channel item '{t}': what follows @ must be a slope (value/frame); '{sl}' is not a number. "
                    f"Example: 12:1@0")
        parts = body.split(":")
        if len(parts) < 2 or len(parts) > 3:
            raise ValueError(
                f"Each channel item is written frame:value[:interp][@slope]; '{t}' is invalid. "
                f"Example: {EXAMPLE}")
        try:
            fs.append(float(parts[0]))
        except ValueError:
            raise ValueError(f"'{parts[0]}' in the channel is not a frame number (must be a number).")
        try:
            vs.append(float(parts[1]))
        except ValueError:
            raise ValueError(f"'{parts[1]}' in the channel is not a number (should be the keyframe value).")
        if len(parts) == 3:
            name = parts[2].strip().lower()
            if name not in _CODE:
                raise ValueError(
                    f"Channel item '{t}': unknown interpolation '{parts[2]}'. "
                    f"Must be one of {INTERPS}")
            cs.append(_CODE[name])
        else:
            cs.append(_CODE[default_interp])
        ss.append(slope)
    f = np.asarray(fs, np.float64)
    v = np.asarray(vs, np.float64)
    c = np.asarray(cs, np.int64)
    s = np.asarray(ss, np.float64)
    # Stable sort + "later one wins": stable sort by frame number, keeping the **last** of a run with the same frame.
    # Only a stable sort guarantees that "last" means the one later in the text.
    order = np.argsort(f, kind="stable")
    f, v, c, s = f[order], v[order], c[order], s[order]
    if len(f) > 1:
        keep = np.ones(len(f), bool)
        keep[:-1] = np.abs(np.diff(f)) > 1e-9
        f, v, c, s = f[keep], v[keep], c[keep], s[keep]
    return f, v, c, s


# ══════════════════════════════════════════════════════════════ automatic tangents
def auto_slopes(f, v, slope):
    """
    Fills nan in slope with automatic tangents. See the "non-uniformly weighted difference" section of the module header.

    Returns a new array without modifying the input (the input may be parse's result, which the caller may still use).
    """
    f = np.asarray(f, np.float64)
    v = np.asarray(v, np.float64)
    m = np.array(slope, np.float64, copy=True)
    k = len(f)
    if k == 0:
        return m
    if k == 1:
        return np.where(np.isnan(m), 0.0, m)
    h = np.diff(f)                              # (k-1,) segment lengths, strictly > 0
    d = np.diff(v) / h                          # (k-1,) slope of each segment
    auto = np.empty(k, np.float64)
    if k == 2:
        # Only one segment: both ends use its slope. Exact for linear functions (quadratics are out of the question)
        auto[:] = d[0]
    else:
        # Interior: three-point difference weighted by segment length -- exact for quadratics with arbitrary spacing
        auto[1:-1] = (h[1:] * d[:-1] + h[:-1] * d[1:]) / (h[:-1] + h[1:])
        # Ends: back out the end derivative from p''~2(d1-d0)/(h0+h1), likewise exact up to quadratics.
        # Using d[0] directly as the end derivative (the most common implementation) is off by a second-order term of half a segment length
        # at the ends -- showing up as "the curve starts at the wrong speed at both ends" while everything in the middle is fine.
        auto[0] = d[0] - h[0] * (d[1] - d[0]) / (h[0] + h[1])
        auto[-1] = d[-1] + h[-1] * (d[-1] - d[-2]) / (h[-2] + h[-1])
    return np.where(np.isnan(m), auto, m)


# ══════════════════════════════════════════════════════════════ in-segment evaluation
def _seg(code, t, p0, p1, m0, m1, h):
    """Value within one segment. t, p0... are arrays of equal length; code is a scalar."""
    dv = p1 - p0
    if code == CONSTANT:
        return p0.copy()
    if code == LINEAR:
        return p0 + dv * t
    if code == EASE:
        return p0 + dv * (t * t * (3.0 - 2.0 * t))
    if code == EASEIN:
        return p0 + dv * (t * t)
    if code == EASEOUT:
        return p0 + dv * (t * (2.0 - t))
    t2 = t * t
    t3 = t2 * t
    if code == CUBIC:
        # Standard cubic Hermite. Tangents are multiplied by h because t is the normalized in-segment parameter
        # while m is in value/frame -- miss this h and segments whose spacing isn't 1 are wrong,
        # yet evenly spaced tests all pass (with h==1 it can't be seen)
        return ((2 * t3 - 3 * t2 + 1) * p0
                + (t3 - 2 * t2 + t) * h * m0
                + (-2 * t3 + 3 * t2) * p1
                + (t3 - t2) * h * m1)
    if code == QUINTIC:
        t4 = t3 * t
        t5 = t4 * t
        return ((1 - 10 * t3 + 15 * t4 - 6 * t5) * p0
                + (t - 6 * t3 + 8 * t4 - 3 * t5) * h * m0
                + (10 * t3 - 15 * t4 + 6 * t5) * p1
                + (-4 * t3 + 7 * t4 - 3 * t5) * h * m1)
    raise ValueError(f"Unknown interpolation code {code}")


def _end_deriv(code, d, m, at_start):
    """
    The **actual** first derivative (value/frame) of a segment at its ends. Needed by extrapolate=linear.

    Uses the segment function's own derivative rather than the keyframe m: constant / ease segments have zero end derivatives,
    and extending with m would create a kink at the end -- "extend" means carrying on,
    and a kink means it was joined wrong.
    """
    if code == CONSTANT:
        return 0.0
    if code == LINEAR:
        return d
    if code == EASE:
        return 0.0
    if code == EASEIN:
        return 0.0 if at_start else 2.0 * d
    if code == EASEOUT:
        return 2.0 * d if at_start else 0.0
    return m                                   # cubic / quintic


# ══════════════════════════════════════════════════════════════════ evaluation
def evaluate(f, v, code, slope, x, extrapolate="hold"):
    """
    Evaluates at x (scalar or array). Returns a float64 array shaped like x (0-d for a scalar).

    Everything outside the range is handled by "folding x back into the range" (cycle / mirror) or "end value +
    linear term" (hold / linear). So cycle's periodicity is bit-exact on **integer frames**
    (integer modulo has no rounding), which is also the actual use -- the playbar gives integer frames.

    On fractional frames it is exact only up to float rounding: `np.mod(-37.3, 24)` gives 10.700000000000003,
    `np.mod(-13.3, 24)` gives 10.7, one ulp apart. This is written here because
    "cycling is exact" is easily taken to mean bitwise identity, which only holds on integers.
    """
    if extrapolate not in EXTRAPS:
        raise ValueError(f"Extrapolation must be one of {EXTRAPS}, got '{extrapolate}'")
    f = np.asarray(f, np.float64)
    v = np.asarray(v, np.float64)
    code = np.asarray(code, np.int64)
    xin = np.asarray(x, np.float64)
    xs = xin.reshape(-1)
    k = len(f)
    if k == 0:
        raise ValueError("The channel has no keyframes")
    if k == 1:
        return np.full(xin.shape, v[0], np.float64)

    m = auto_slopes(f, v, slope)
    f0, f1 = f[0], f[-1]
    period = f1 - f0
    xr = xs
    off = 0.0
    lo = xs < f0
    hi = xs > f1
    if extrapolate == "cycle":
        xr = f0 + np.mod(xs - f0, period)
    elif extrapolate == "cycleoffset":
        n = np.floor((xs - f0) / period)
        xr = xs - n * period
        off = n * (v[-1] - v[0])
    elif extrapolate == "mirror":
        q = np.mod(xs - f0, 2.0 * period)
        xr = f0 + np.where(q <= period, q, 2.0 * period - q)
    else:
        xr = np.clip(xs, f0, f1)

    # Segment index: searchsorted right - 1, clamped to [0, k-2]. x == f[-1] lands on the last segment's
    # t == 1, which is exactly v[-1]
    i = np.clip(np.searchsorted(f, xr, side="right") - 1, 0, k - 2)
    h = f[i + 1] - f[i]
    t = (xr - f[i]) / h
    out = np.empty(xs.shape, np.float64)
    # Group by interpolation, computing each group in one go
    for c in np.unique(code[i]):
        sel = code[i] == c
        j = i[sel]
        out[sel] = _seg(int(c), t[sel], v[j], v[j + 1], m[j], m[j + 1], h[sel])
    # **The last keyframe has to be pinned separately.** Segment indices are clamped to [0, k-2], so x == f[-1] lands on
    # the last segment's t == 1; except for constant, every mode gives exactly v[-1] at t == 1,
    # but constant gives v[-2] -- so "the value at the last frame equals the last keyframe's value"
    # doesn't hold for step channels, and it is off only on the last frame, nearly invisible when dragging the playbar.
    # For the other modes this is a no-op (the coefficients at t==1 are exactly 0 and 1), so all are pinned uniformly.
    out[xr >= f1] = v[-1]
    out = out + off

    if extrapolate == "linear":
        d = np.diff(v) / np.diff(f)
        if lo.any():
            g = _end_deriv(int(code[0]), d[0], m[0], True)
            out[lo] = v[0] + g * (xs[lo] - f0)
        if hi.any():
            g = _end_deriv(int(code[k - 2]), d[-1], m[-1], False)
            out[hi] = v[-1] + g * (xs[hi] - f1)
    return out.reshape(xin.shape)


def eval_spec(spec, x, default_interp="cubic", extrapolate="hold"):
    """Text -> values at x. Use this for one-off calls."""
    f, v, c, s = parse(spec, default_interp)
    return evaluate(f, v, c, s, x, extrapolate)


def value_at(spec, frame, default_interp="cubic", extrapolate="hold"):
    """Scalar value at a single frame. This is what the node uses."""
    return float(eval_spec(spec, float(frame), default_interp, extrapolate))


def info(spec, default_interp="cubic"):
    """For the node's info output: keyframe count, frame range, value range."""
    f, v, c, s = parse(spec, default_interp)
    names = "/".join(dict.fromkeys(INTERPS[int(x)] for x in c))
    return (f"{len(f)} keys  frame {f[0]:g}..{f[-1]:g}  "
            f"value {v.min():g}..{v.max():g}  [{names}]")
