"""
The **Post Processing** section shared by Copernicus noise nodes (pcg100 c3_noise).

Houdini's Fractal / Worley / Cellular / Crystal / Bubble / Cloud / Phasor / Fractal
Sample COP family all end with the same post-processing section; the order in the docs is:

    Fold → Complement → Bias → Gain → Gamma → Contrast → Clamp Min → Clamp Max

The docs only say "what it does", without formulas. The formula for each step below is our own; the reasoning is in the functions:

  · Fold        |x|                                 (docs: -2 becomes 2)
  · Complement  1 − x                               (docs, verbatim)
  · Bias        Perlin bias: x^(ln b / ln 0.5)        b = 0.5 is a no-op (docs: 0.5 has no effect)
  · Gain        Perlin gain: bias applied to each half    g = 0.5 is a no-op (docs: 0.5 has no effect)
  · Gamma       x^γ                                  docs: γ > 1 **darkens** (opposite of Color
                                                    Correct's gamma direction; following the docs)
  · Contrast    (x − 0.5)·c + 0.5                   docs: expand / contract around mid-grey
  · Clamp       one toggle + threshold each

**The docs contradict themselves on Bias**: "below 1 pulls toward 0, above 1 pulls toward 1", but also "0.5 has no effect".
Only one can be trusted -- we take the "0.5 has no effect" one (the standard Perlin bias definition, b ∈ (0,1)):
b < 0.5 pulls toward 0, b > 0.5 pulls toward 1. The parameter range is limited to (0, 1).

**Out-of-range values**: Perlin bias / gain / gamma are only defined on [0,1]; non-integer powers of negatives
are NaN. Here everything uses the **odd extension** sign(x)·|x|^p (continuous, monotonic, fixed at 0). Noise after
Amplitude / Center is often [-1, 1]; the docs don't say how Houdini handles negatives -- this is our own choice.

All steps are backend-neutral (xp only uses abs / where / maximum / minimum / full), so
COP Noise's torch path still works. Each step only runs when its parameter differs from the default; with all defaults
the input is returned as is, and the output is **bit-identical** to before this section was added.
"""
from __future__ import annotations

import math

# Defaults of the section's parameters (= no effect). Callers take kwargs according to this dict
DEFAULTS = dict(fold=False, complement=False, pp_bias=0.5, gain=0.5,
                gamma=1.0, contrast=1.0, use_clamp_min=False, clamp_min=0.0,
                use_clamp_max=False, clamp_max=1.0)
KEYS = tuple(DEFAULTS)


def _spow(xp, x, p):
    """Odd-extended power: sign(x)·|x|^p. No NaN for negatives."""
    a = xp.abs(x) ** float(p)
    return xp.where(x < 0, -a, a)


def _bexp(b):
    """Perlin bias exponent ln b / ln 0.5. b is clamped to the open interval (0,1) -- 0 and 1 are singular."""
    b = min(max(float(b), 1e-6), 1.0 - 1e-6)
    return math.log(b) / math.log(0.5)


def bias_fn(xp, x, b):
    return _spow(xp, x, _bexp(b))


def gain_fn(xp, x, g):
    """
    Perlin gain: bias(2x, 1−g)/2 for x < 0.5, otherwise 1 − bias(2−2x, 1−g)/2.
    g > 0.5 steepens around mid-grey (pushes both ends apart), g < 0.5 flattens the middle.
    """
    p = _bexp(1.0 - float(g))
    lo = _spow(xp, 2.0 * x, p) * 0.5
    hi = 1.0 - _spow(xp, 2.0 - 2.0 * x, p) * 0.5
    return xp.where(x < 0.5, lo, hi)


def apply(xp, a, fold=False, complement=False, pp_bias=0.5, gain=0.5,
          gamma=1.0, contrast=1.0, use_clamp_min=False, clamp_min=0.0,
          use_clamp_max=False, clamp_max=1.0):
    """Run once in the docs' order."""
    g = float(gain)
    if fold:
        a = xp.abs(a)
    if complement:
        a = 1.0 - a
    if float(pp_bias) != 0.5:
        a = bias_fn(xp, a, pp_bias)
    if g != 0.5:
        a = gain_fn(xp, a, g)
    if float(gamma) != 1.0:
        a = _spow(xp, a, max(float(gamma), 1e-6))
    if float(contrast) != 1.0:
        a = (a - 0.5) * float(contrast) + 0.5
    if use_clamp_min:
        a = xp.maximum(a, xp.full(tuple(a.shape), float(clamp_min)))
    if use_clamp_max:
        a = xp.minimum(a, xp.full(tuple(a.shape), float(clamp_max)))
    return a


def pick(kw):
    """kwargs received by a node's run(**post) -> dict containing only KEYS. Extra names raise
    (a misspelled parameter name won't be silently swallowed)."""
    bad = set(kw) - set(KEYS)
    if bad:
        raise TypeError(f"unknown parameters {sorted(bad)}")
    return dict(kw)


def run(xp, a, kw):
    """
    kw is a dict containing only KEYS. With all defaults every step in apply is skipped by its own condition, and the
    same array is returned (bit-identical) -- there used to be a separate is_identity check up front; mutation testing showed it
    fully duplicated these conditions, so it was removed.
    """
    kw = {k: kw.get(k, DEFAULTS[k]) for k in KEYS}
    return apply(xp, a, **kw)


def widgets(f, sec):
    """
    Widget definitions for the node's INPUT_TYPES (in docs order). f / sec are supplied by the caller
    (_f / _sec in each node file), so this geometry module doesn't depend back on the node layer.
    """
    B = lambda d: ("BOOLEAN", {"default": d})            # noqa: E731
    return {
        "fold": sec("Post Processing", B(False)),
        "complement": sec("Post Processing", B(False)),
        "pp_bias": sec("Post Processing", f(0.5, 0.0, 1.0, 0.01)),
        "gain": sec("Post Processing", f(0.5, 0.0, 1.0, 0.01)),
        "gamma": sec("Post Processing", f(1.0, 0.001, 100.0, 0.01)),
        "contrast": sec("Post Processing", f(1.0, -100.0, 100.0, 0.01)),
        "use_clamp_min": sec("Post Processing", B(False)),
        "clamp_min": sec("Post Processing", f(0.0, -1e5, 1e5, 0.01)),
        "use_clamp_max": sec("Post Processing", B(False)),
        "clamp_max": sec("Post Processing", f(1.0, -1e5, 1e5, 0.01)),
    }


def panel():
    """This section's inputs for the panel spec (labels follow Houdini)."""
    return {
        "fold": {"label": "Fold", "section": "Post Processing", "sep": True},
        "complement": {"label": "Complement"},
        "pp_bias": {"label": "Bias",
                    "help": "Perlin bias; 0.5 = no change; < 0.5 pulls toward 0, > 0.5 pulls toward 1"},
        "gain": {"label": "Gain", "help": "Perlin gain; 0.5 = no change"},
        "gamma": {"label": "Gamma", "help": "x^γ: > 1 darkens (per the Houdini noise docs)"},
        "contrast": {"label": "Contrast", "help": "scale around 0.5"},
        # use_clamp_min directly follows clamp_min, so panel.derive itself infers a single "☑ label [value]" row
        "clamp_min": {"label": "Clamp Minimum"},
        "clamp_max": {"label": "Clamp Maximum"},
    }
