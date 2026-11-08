"""
Ramp -- gradient curves described as text, shared by Remap Ramp and Measure's color map.

ComfyUI has no draggable ramp widget like Houdini's, and **ramp data cannot be stuffed into a single
float value of a widget**. Rather than building a half-broken frontend widget, the ramp is written as one line of text:

    0:0  0.5:0.25  1:1                 scalar ramp (Remap Ramp)
    0:0,0.1,0.9  0.5:1,1,1  1:0.9,0,0  color ramp (Measure's color map)

The benefit is not just convenience: a line of text can be copied and pasted, put under version control, and assembled by upstream nodes with
expressions. In Houdini, moving a ramp from one node to another is actually rather awkward.

Three interpolation modes:
    linear     straight segments (default)
    smooth     smoothstep on each segment, zero first derivative at the knots, so terrain height curves get no creases
    constant   steps, for discrete classification like "layers by height"
"""
from __future__ import annotations

import numpy as np

MODES = ("linear", "smooth", "constant")


def parse(spec, ncomp=1):
    """
    "pos:v [pos:v ...]" -> (positions (K,), values (K, ncomp)). Positions are sorted and deduplicated.

    With ncomp > 1 each value is written as comma-separated components (0:0.1,0.2,0.3). When only one component is given
    it is broadcast automatically (a grayscale color map can be written 0:0 1:1).
    """
    toks = [t for t in str(spec or "").split() if t]
    if not toks:
        raise ValueError("The ramp is empty. Syntax: 0:0  0.5:0.25  1:1")
    pos, val = [], []
    for t in toks:
        if ":" not in t:
            raise ValueError(
                f"Each ramp entry must be written as position:value; '{t}' is missing the colon. "
                f"e.g. 0:0  0.5:0.25  1:1")
        p, v = t.split(":", 1)
        try:
            pos.append(float(p))
        except ValueError:
            raise ValueError(f"'{p}' in the ramp is not a number (should be a position in 0..1).")
        parts = [x for x in v.split(",") if x != ""]
        try:
            c = [float(x) for x in parts]
        except ValueError:
            raise ValueError(f"'{v}' in the ramp is not a number.")
        if not c:
            raise ValueError(f"Ramp entry '{t}' is missing a value.")
        if len(c) == 1 and ncomp > 1:
            c = c * ncomp
        if len(c) != ncomp:
            raise ValueError(
                f"Ramp entry '{t}' has {len(c)} components, {ncomp} are needed here.")
        val.append(c)
    pos = np.asarray(pos, np.float64)
    val = np.asarray(val, np.float64)
    order = np.argsort(pos, kind="stable")
    pos, val = pos[order], val[order]
    keep = np.ones(len(pos), bool)
    keep[1:] = np.diff(pos) > 1e-12          # when positions coincide keep the earlier one
    return pos[keep], val[keep]


def apply(t, pos, val, mode="linear"):
    """t (N,) in [0,1] -> (N, C). Beyond either end the end value is used (no extrapolation)."""
    t = np.clip(np.asarray(t, np.float64).reshape(-1), 0.0, 1.0)
    if len(pos) == 1:
        return np.repeat(val[:1], len(t), axis=0)
    if mode == "constant":
        i = np.clip(np.searchsorted(pos, t, side="right") - 1, 0, len(pos) - 1)
        return val[i]
    if mode not in ("linear", "smooth"):
        raise ValueError(f"Ramp interpolation must be one of {MODES}")
    i = np.clip(np.searchsorted(pos, t, side="right") - 1, 0, len(pos) - 2)
    span = np.maximum(pos[i + 1] - pos[i], 1e-12)
    a = np.clip((t - pos[i]) / span, 0.0, 1.0)
    if mode == "smooth":
        a = a * a * (3.0 - 2.0 * a)
    return val[i] + (val[i + 1] - val[i]) * a[:, None]


def remap(v, spec, mode="linear"):
    """Scalar ramp: v in [0,1], remapped by the ramp, stays within the range of the ramp values."""
    pos, val = parse(spec, 1)
    return apply(v, pos, val, mode)[:, 0]
