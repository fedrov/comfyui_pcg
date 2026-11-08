"""
Attribute Adjust -- a complete processing pipeline for one attribute.

Counterpart of Houdini's Attribute Adjust Float / Integer / Vector SOPs. **Here they are merged into
one node**: those three are separate because Houdini's parameter controls are themselves typed (a float
slider cannot hold three components); here values are always (N, C) float arrays and the component count comes
from the attribute itself, so three nodes would only mean two more names to remember.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Four sections in fixed order: Initialize -> adjustment stack -> Remap -> Post
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    1. Initialize   where the attribute comes from: keep / constant / random / another attribute / noise / expression
    2. Adjust       a stack of operations, one step per line, applied in the order written
    3. Remap        normalize the values to [0,1], pass them through a ramp, then stretch to the output range
    4. Post         clamp / round / normalize length

The four sections are not for looks: **the order matters**. Remap must come after the adjustment stack (it needs the final
distribution to set its range automatically), rounding must come last (rounding then multiplying by 2 gives even numbers). Hard-coding
the order in the node is harder to get wrong than chaining four nodes yourself -- and saves three geometry copies.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Why the adjustment stack is text, not a pile of widgets
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Houdini uses a multiparm (the "+" button) to stack any number of steps. ComfyUI widgets are **statically
declared**: whatever `INPUT_TYPES` returns is what you get, with no way to add/remove at runtime. Three options:
a fixed N sets of controls (too few if N is small, a screen full of greyed-out ones if large), a custom frontend (which means maintaining
serialize/deserialize and the undo stack), or one line of text per step.

Text was chosen, consistent with the ramp / rename specs. Side effects: it can be copy-pasted, put under version control,
and assembled upstream with expressions -- in Houdini, moving a string of multiparms to another node is actually a pain.

    # each line:  <op> <source> [mask=<source>]        # text after a hash is a comment
    mul   2.0                       multiply by a constant
    add   @curvature                add another attribute (broadcast VEX-style if it has too few components)
    mul   rand(0.8, 1.2)            one random number per element
    add   noise(perlin, 2.0, 0.3)   noise: type, element size, amplitude
    max   0.0                       per-component maximum
    mix   1.0 mask=@occlusion       interpolate towards 1.0, by an amount given by occlusion
    set   (@P.y * 0.1)              a wrangle expression in parentheses

    ops:     set add sub mul div min max pow mix
    sources: number / comma-separated vector / @attribute / rand(a,b) / noise(type,size,amplitude) / (expression)

mask is **per step**: within one stack an earlier step can apply globally and a later one only to one region,
meant for needs like "scale everything a bit, then lower only the parts by the road".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
div has no divide-by-zero guard; it **raises an error**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Division by zero silently becomes inf, drifts downstream and turns into a patch of nan, and by the time you see the nan
you are far from the scene of the crime. Here a 0 raises immediately, saying which line and how many elements hit it.
"""
from __future__ import annotations

import re

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, CLASSES, is_string
from .groups import resolve
from . import ramp as _ramp
from . import attribnoise as _an

INIT = ("off", "constant", "random", "attribute", "noise", "expression")
DISTRIBUTIONS = ("uniform", "gaussian", "power")
OPS = ("set", "add", "sub", "mul", "div", "min", "max", "pow", "mix")
ROUND = ("none", "nearest", "down", "up")
RANGE_MODES = ("auto", "manual")
NORMALIZE = ("none", "unit_length", "sum_to_one")
RAMP_MODES = _ramp.MODES
NOISE_TYPES = _an.NOISE_TYPES

_NUM = re.compile(r"^-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$")
_CALL = re.compile(r"^([a-z_]+)\s*\((.*)\)$", re.S)


# ══════════════════════════════════════════════════════════ source evaluation
def _floats(s, what):
    out = []
    for t in str(s).split(","):
        t = t.strip()
        if not t:
            continue
        if not _NUM.match(t):
            raise ValueError(f"{what}: '{t}' is not a number.")
        out.append(float(t))
    if not out:
        raise ValueError(f"{what} is empty.")
    return out


def _fit_comps(v, C, what):
    """(N, k) -> (N, C). k==1 is broadcast VEX-style; otherwise the component counts must match."""
    if v.shape[1] == C:
        return v
    if v.shape[1] == 1:
        return np.repeat(v, C, axis=1)
    raise ValueError(f"{what} has {v.shape[1]} components, the attribute has {C}.")


def _source(geo, cls, spec, n, C, seed, salt, what):
    """Evaluates one source spec into (N, C)."""
    spec = spec.strip()
    if not spec:
        raise ValueError(f"{what} is missing a source.")

    if spec.startswith("(") and spec.endswith(")"):
        from .wrangle import eval_value
        return _fit_comps(eval_value(geo, spec[1:-1], cls, None), C, what)

    if spec.startswith("@"):
        nm = spec[1:].strip()
        a = geo.get(cls, nm)
        if a is None:
            have = sorted(geo.attribs[cls].keys())
            raise KeyError(f"{what}: {cls} has no attribute '{nm}'. "
                           f"Existing: {have or '(none)'}")
        if is_string(a):
            raise ValueError(f"{what}: '{nm}' is a string attribute and cannot be used in arithmetic.")
        return _fit_comps(a.astype(np.float64), C, what)

    m = _CALL.match(spec)
    if m:
        fn, args = m.group(1), m.group(2)
        if fn == "rand":
            from .attribrandomize import _rand01
            a = _floats(args, f"{what}: rand(...)")
            if len(a) == 1:
                a = [0.0, a[0]]
            if len(a) != 2:
                raise ValueError(f"{what}: rand must be written as rand(min, max).")
            keys = np.arange(n, dtype=np.float64)
            # Each step gets a different salt, otherwise two rands in one stack would give identical numbers
            cols = [a[0] + (a[1] - a[0]) * _rand01(keys, seed, salt * 31 + c)
                    for c in range(C)]
            return np.stack(cols, 1)
        if fn == "noise":
            parts = [p.strip() for p in args.split(",")]
            kind = parts[0] if parts and parts[0] else "simplex"
            if kind not in NOISE_TYPES:
                raise ValueError(f"{what}: noise type must be one of {NOISE_TYPES}")
            size = float(parts[1]) if len(parts) > 1 and parts[1] else 1.0
            amp = float(parts[2]) if len(parts) > 2 and parts[2] else 1.0
            P = _an._sample_positions(geo, cls, "P")
            if len(P) == 1 and n > 1:
                P = np.repeat(P, n, axis=0)
            v = _an.noise(P / max(abs(size), 1e-9), kind, seed + salt)
            return np.repeat((v * amp)[:, None], C, axis=1)
        raise ValueError(f"{what}: unknown '{fn}(...)'. "
                         f"Available: rand(a,b) and noise(type, size, amplitude).")

    v = np.asarray(_floats(spec, what), np.float64)
    return _fit_comps(np.tile(v, (n, 1)), C, what)


# ══════════════════════════════════════════════════════════ adjustment stack
def parse_stack(text):
    """Text -> [(line number, original text, op, source, mask or None)]."""
    out = []
    for i, raw in enumerate(str(text or "").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        mask = None
        m = re.search(r"\bmask\s*=\s*(\S.*)$", line)
        if m:
            mask = m.group(1).strip()
            line = line[:m.start()].strip()
        parts = line.split(None, 1)
        op = parts[0].lower()
        if op not in OPS:
            raise ValueError(f"Line {i}: unknown operation '{parts[0]}'. "
                             f"Available: {' '.join(OPS)}.\n  {raw.strip()}")
        if len(parts) < 2 or not parts[1].strip():
            raise ValueError(f"Line {i}: '{op}' is missing a source.\n  {raw.strip()}")
        out.append((i, raw.strip(), op, parts[1].strip(), mask))
    return out


def _step(v, op, s, line, raw):
    if op == "set":
        return s
    if op == "add":
        return v + s
    if op == "sub":
        return v - s
    if op == "mul":
        return v * s
    if op == "div":
        bad = int(np.count_nonzero(s == 0.0))
        if bad:
            # No 1e-12 guard: division by zero silently becomes inf, drifts downstream into a patch of nan,
            # and by the time it is found you are far from the scene. Report it right here, with the line number
            raise ZeroDivisionError(
                f"Line {line}: the divisor of div contains {bad} zeros.\n  {raw}")
        return v / s
    if op == "min":
        return np.minimum(v, s)
    if op == "max":
        return np.maximum(v, s)
    if op == "pow":
        # A negative base with a non-integer exponent is complex; VEX's pow gives nan here, better to say so plainly
        bad = int(np.count_nonzero((v < 0) & (s != np.rint(s))))
        if bad:
            raise ValueError(
                f"Line {line} pow: {bad} elements have a negative base and a non-integer exponent; "
                f"the result would be nan. Apply max 0 first or use an integer exponent.\n  {raw}")
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.power(v, s)
    raise ValueError(f"Line {line}: unknown operation '{op}'.\n  {raw}")


def run_stack(geo, v, cls, text, seed=0):
    """Processes the (N, C) array v through the stack step by step. Returns a new array; the original is not modified."""
    n, C = v.shape
    for salt, (line, raw, op, src, mask) in enumerate(parse_stack(text), 1):
        s = _source(geo, cls, src, n, C, seed, salt, f"Line {line}")
        if op == "mix":
            # The mask of mix is the interpolation factor itself, default 0.5 -- a mix without a mask takes the midpoint
            t = (np.clip(_source(geo, cls, mask, n, C, seed, salt * 7 + 3,
                                 f"mask of line {line}"), 0.0, 1.0)
                 if mask else np.full((n, C), 0.5))
            v = v + (s - v) * t
            continue
        nv = _step(v, op, s, line, raw)
        if mask:
            t = np.clip(_source(geo, cls, mask, n, C, seed, salt * 7 + 3,
                                f"mask of line {line}"), 0.0, 1.0)
            nv = v + (nv - v) * t          # the mask controls how much of this step applies
        v = nv
    return v


# ══════════════════════════════════════════════════════════ remap
def remap(v, spec, mode="linear", range_mode="auto",
          in_min=0.0, in_max=1.0, out_min=0.0, out_max=1.0,
          per_component=False):
    """
    Normalizes v to [0,1], passes it through the ramp, then stretches it to the output range.

    With range_mode=auto the input range is the measured min/max -- this is the "I don't know the range of the curvature,
    but I want to map it to a colour" use case. per_component decides whether auto sets a range per
    component or one shared by all components: when colouring Cd it must be **shared**, otherwise the three channels are each
    stretched to full and an originally grey colour becomes garish.
    """
    v = np.asarray(v, np.float64)
    if range_mode == "auto":
        if per_component:
            lo = v.min(0, keepdims=True)
            hi = v.max(0, keepdims=True)
        else:
            lo = np.full((1, v.shape[1]), v.min() if v.size else 0.0)
            hi = np.full((1, v.shape[1]), v.max() if v.size else 1.0)
    elif range_mode == "manual":
        lo = np.full((1, v.shape[1]), float(in_min))
        hi = np.full((1, v.shape[1]), float(in_max))
    else:
        raise ValueError(f"Input Range must be one of {RANGE_MODES}")
    t = np.clip((v - lo) / np.maximum(hi - lo, 1e-30), 0.0, 1.0)

    pos, val = _ramp.parse(spec, 1)
    out = np.stack([_ramp.apply(t[:, c], pos, val, mode)[:, 0]
                    for c in range(v.shape[1])], 1)
    return float(out_min) + (float(out_max) - float(out_min)) * out


# ══════════════════════════════════════════════════════════ main function
def adjust(geo, name="", cls=POINT, group="",
           initialize="off", size=1, create_if_missing=True,
           constant=(0.0, 0.0, 0.0, 0.0),
           distribution="uniform", rand_min=0.0, rand_max=1.0,
           mean=0.5, stddev=0.25, exponent=2.0,
           source_attrib="", noise_type="simplex", noise_size=1.0,
           noise_amplitude=1.0, expression="",
           adjustments="", use_remap=False, remap_ramp="0:0  1:1",
           ramp_mode="linear", range_mode="auto",
           in_min=0.0, in_max=1.0, out_min=0.0, out_max=1.0,
           remap_per_component=False,
           use_clamp_min=False, clamp_min=0.0,
           use_clamp_max=False, clamp_max=1.0,
           round_mode="none", normalize="none",
           to_int=False, rand_seed=0, id_attrib=""):
    """
    A complete processing pipeline for one attribute; the four sections are described in the module docstring.

    Elements outside group **keep their original values**; the whole pipeline applies only within the group -- including remap's
    auto range, which also looks only at elements in the group, otherwise outliers outside the group would stretch the range.
    """
    if geo is None:
        return Geometry()
    if cls not in CLASSES:
        raise ValueError(f"Class must be one of {CLASSES}")
    if initialize not in INIT:
        raise ValueError(f"Initialize must be one of {INIT}")
    if round_mode not in ROUND:
        raise ValueError(f"Round must be one of {ROUND}")
    if normalize not in NORMALIZE:
        raise ValueError(f"Normalize must be one of {NORMALIZE}")
    nm = str(name or "").strip()
    if not nm:
        raise ValueError("Attribute Name is empty.")
    n = geo.count(cls)
    if n == 0:
        return geo.copy()

    cur = geo.get(cls, nm)
    if cur is not None and is_string(cur):
        raise ValueError(f"'{nm}' is a string attribute; Attribute Adjust only handles numeric values.")
    if cur is None:
        if not create_if_missing:
            have = sorted(geo.attribs[cls].keys())
            raise KeyError(f"{cls} has no attribute '{nm}' (Create If Missing is off). "
                           f"Existing: {have or '(none)'}")
        if initialize == "off":
            raise ValueError(
                f"{cls} has no attribute '{nm}', and Initialize is off -- "
                f"there is no original value to keep. Pick an initialization mode, or create the attribute first.")
        C = int(np.clip(size, 1, 4))
        base = np.zeros((n, C))
        dt = np.dtype(np.int32) if to_int else np.dtype(np.float32)
    else:
        C = cur.shape[1]
        base = cur.astype(np.float64)
        dt = cur.dtype

    seed = int(rand_seed)
    keys = np.arange(n, dtype=np.float64)
    idn = str(id_attrib).strip()
    if idn:
        a = geo.get(cls, idn)
        if a is None:
            have = sorted(geo.attribs[cls].keys())
            raise KeyError(f"{cls} has no id attribute '{idn}'. Existing: {have or '(none)'}")
        keys = a[:, 0].astype(np.float64)

    # ── 1. Initialize
    if initialize == "off":
        v = base.copy()
    elif initialize == "constant":
        c = np.asarray(constant, np.float64).reshape(-1)[:C]
        c = np.concatenate([c, np.zeros(max(0, C - len(c)))])[:C]
        v = np.tile(c, (n, 1))
    elif initialize == "random":
        from .attribrandomize import _rand01, _gauss
        cols = []
        for c in range(C):
            if distribution == "uniform":
                t = _rand01(keys, seed, 211 + c * 13)
            elif distribution == "power":
                t = _rand01(keys, seed, 211 + c * 13) ** max(float(exponent),
                                                             1e-6)
            elif distribution == "gaussian":
                cols.append(float(mean) + float(stddev)
                            * _gauss(keys, seed, 211 + c * 13))
                continue
            else:
                raise ValueError(f"Distribution must be one of {DISTRIBUTIONS}")
            cols.append(float(rand_min)
                        + (float(rand_max) - float(rand_min)) * t)
        v = np.stack(cols, 1)
    elif initialize == "attribute":
        v = _source(geo, cls, "@" + str(source_attrib).strip(), n, C, seed, 0,
                    "Initialize / Source Attribute")
    elif initialize == "noise":
        v = _source(geo, cls,
                    f"noise({noise_type}, {float(noise_size)}, "
                    f"{float(noise_amplitude)})", n, C, seed, 0,
                    "Initialize / Noise")
    else:
        from .wrangle import eval_value
        v = _fit_comps(eval_value(geo, expression, cls, None), C,
                       "Initialize / Expression")

    # ── 2. Adjustment stack
    v = run_stack(geo, v, cls, adjustments, seed)

    sel = resolve(geo, cls, group)

    # ── 3. Remap. The auto range only looks at elements in the group: outliers outside the group would stretch the range
    #      and crush all the contrast inside the group
    if use_remap:
        if sel.all():
            v = remap(v, remap_ramp, ramp_mode, range_mode, in_min, in_max,
                      out_min, out_max, remap_per_component)
        elif sel.any():
            sub = remap(v[sel], remap_ramp, ramp_mode, range_mode,
                        in_min, in_max, out_min, out_max, remap_per_component)
            v = v.copy()
            v[sel] = sub

    # ── 4. Post-processing
    if use_clamp_min:
        v = np.maximum(v, float(clamp_min))
    if use_clamp_max:
        v = np.minimum(v, float(clamp_max))
    if normalize == "unit_length":
        L = np.linalg.norm(v, axis=1, keepdims=True)
        v = v / np.where(L < 1e-12, 1.0, L)
    elif normalize == "sum_to_one":
        s = v.sum(1, keepdims=True)
        v = v / np.where(np.abs(s) < 1e-12, 1.0, s)
    if round_mode == "nearest":
        v = np.rint(v)
    elif round_mode == "down":
        v = np.floor(v)
    elif round_mode == "up":
        v = np.ceil(v)

    out = np.where(sel[:, None], v, base)
    g = geo.copy()
    g.set(cls, nm, (np.rint(out) if dt.kind in "iub" else out).astype(dt),
          owned=True)
    return g
