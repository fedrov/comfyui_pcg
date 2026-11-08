"""
Parameter linkage: value nodes + expression nodes.

Usage: right-click a widget on the target node, "Convert widget to input" to promote it to a socket,
then wire it from here. One value can drive several parameters on several nodes at once.

Compared with Houdini's ch(), the dependency is **a real edge in the graph**: ComfyUI's cache system
knows the upstream/downstream relationship by nature; when upstream changes, downstream is always recooked, no need for our own IS_CHANGED.
The cost is a few more wires on the canvas, in exchange for visible dependencies that you notice immediately when deleting a node.

The expression function library matches Wrangle's, one less set to remember.

Besides these nodes, Switch's Select Input also goes through this evaluator -- that path additionally
has a set of geometry-reading functions (detail / npoints / prim ...), see geo_funcs().
"""
from __future__ import annotations

import math
import random

import numpy as np

from .geo import channel as _chn

_CONST = {"PI": math.pi, "TAU": math.tau, "E": math.e}


def _clamp(x, a, b):
    return a if x < a else (b if x > b else x)


def _fit(x, a, b, c, d):
    if b == a:
        return c
    return c + (_clamp(x, min(a, b), max(a, b)) - a) / (b - a) * (d - c)


def _rand(seed=0):
    """Deterministic random: the same seed always gives the same value, so the cache does not get invalidated."""
    return random.Random(int(seed) & 0x7FFFFFFF).random()


_FUNCS = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "atan2": math.atan2, "sqrt": math.sqrt, "exp": math.exp,
    "log": math.log, "pow": math.pow, "abs": abs,
    "floor": math.floor, "ceil": math.ceil, "round": round,
    "min": min, "max": max, "sign": lambda x: (x > 0) - (x < 0),
    "mod": math.fmod, "frac": lambda x: x - math.floor(x),
    "radians": math.radians, "degrees": math.degrees,
    "clamp": _clamp, "fit": _fit,
    "fit01": lambda x, c, d: c + _clamp(x, 0.0, 1.0) * (d - c),
    "lerp": lambda a, b, t: a + (b - a) * t,
    "rand": _rand,
}

VARS = ("a", "b", "c", "d", "e", "f")


def _eval(expr, values, label="Available variables: {} (unwired ones count as 0)"):
    ns = {"__builtins__": {}}
    ns.update(_CONST)
    ns.update(_FUNCS)
    ns.update(values)
    from .geo.wrangle import check_code
    check_code(str(expr), "Expression", "eval")
    try:
        return float(eval(compile(expr, "<expr>", "eval"), ns))
    except Exception as ex:
        raise RuntimeError(
            f"Expression evaluation failed: {type(ex).__name__}: {ex}\n"
            f"  Expression: {expr}\n"
            f"  {label.format(', '.join(sorted(values)))}\n"
            f"  Available functions: {', '.join(sorted(_FUNCS))}") from ex


# ═══════════════════════════════════════════════ Geometry-reading expression functions
def geo_funcs(geo=None, ninputs=0):
    """
    Geometry-reading functions for expressions. The equivalent of detail() / npoints()
    and friends in Houdini expressions; the function names also match the ones in Wrangle.

    geo is Switch's ctrl input -- it is the Spare Input in Houdini,
    so `detail(-1, "type", 0)` can be copied over verbatim; -1 refers to it.

    **Only ctrl can be read, not the branch inputs**: branches are evaluated lazily (unselected ones don't run),
    and reading them would run them all, defeating the point of Switch.
    """
    def _need():
        if geo is None:
            raise RuntimeError(
                "The expression reads geometry, but the ctrl input is not wired. Wire the geometry "
                "used for the decision into ctrl -- it is the equivalent of Houdini's Spare Input; "
                'the -1 in detail(-1, "x", 0) refers to it.')
        return geo

    def _strip(args):
        """Eat the leading input index of the Houdini syntax. Only -1 is accepted."""
        if args and isinstance(args[0], (int, float)) \
                and not isinstance(args[0], str):
            n = int(args[0])
            if n != -1:
                raise RuntimeError(
                    f"Only input index -1 (= the ctrl input) is supported in expressions, got {n}. "
                    f"Branch inputs are evaluated lazily; reading them would run unselected branches too.")
            return args[1:]
        return args

    def _read(cls, args, needs_index):
        a = _strip(args)
        if len(a) < (2 if needs_index else 1):
            raise RuntimeError(
                f'{cls}() has too few arguments. Syntax: {cls}("attribute name"'
                + (', element index, component index)' if needs_index else ', component index)'))
        g = _need()
        name = str(a[0])
        v = g.get(cls, name)
        if v is None:
            have = sorted(g.attribs[cls].keys())
            raise RuntimeError(f"no attribute '{name}' on {cls}. Existing: "
                               f"{have or '(none)'}")
        row = int(a[1]) if needs_index else 0
        col = int(a[2 if needs_index else 1]) if len(a) > (2 if needs_index else 1) else 0
        if not (0 <= row < len(v)):
            raise RuntimeError(f"{cls} index {row} out of range ({len(v)} total)")
        val = v[row][min(col, v.shape[1] - 1)]
        return str(val) if v.dtype.kind in "US" else float(val)

    def _count(cls, args):
        _strip(args)
        return float(_need().count(cls))

    _CLS = ("point", "prim", "vertex", "detail")

    def _cls(c, allow_edge=False):
        c = str(c)
        ok = _CLS + (("edge",) if allow_edge else ())
        if c not in ok:
            raise RuntimeError(f"class must be one of {ok}, got '{c}'")
        return c

    def _has(args):
        a = _strip(args)
        return float(_need().get(_cls(a[0]), str(a[1])) is not None)

    def _grp(args):
        """Member count of a group; -1 when the group does not exist (hasgroup is just ngroup >= 0)."""
        a = _strip(args)
        c = _cls(a[0], True)
        g = _need()
        if c == "edge":
            v = g.edge_groups.get(str(a[1]))
            return -1.0 if v is None else float(len(v))
        if c == "detail":
            raise RuntimeError("detail has no groups")
        v = g.get_group(c, str(a[1]))
        return -1.0 if v is None else float(np.count_nonzero(v))

    def _agg(fn, args):
        a = _strip(args)
        c, name = _cls(a[0]), str(a[1])
        col = int(a[2]) if len(a) > 2 else 0
        v = _need().get(c, name)
        if v is None:
            raise RuntimeError(f"no attribute '{name}' on {c}")
        if v.dtype.kind in "US":
            raise RuntimeError(f"'{name}' is a string attribute, cannot take min / max / average")
        if not len(v):
            raise RuntimeError(f"{c} has no elements at all, '{name}' has no aggregate value")
        return float(fn(np.asarray(v, np.float64)[:, min(col, v.shape[1] - 1)]))

    return {
        "detail": lambda *a: _read("detail", a, False),
        "point": lambda *a: _read("point", a, True),
        "prim": lambda *a: _read("prim", a, True),
        "vertex": lambda *a: _read("vertex", a, True),
        "hasdetail": lambda *a: float(
            _need().get("detail", str(_strip(a)[0])) is not None),
        "npoints": lambda *a: _count("point", a),
        "nprims": lambda *a: _count("prim", a),
        "nvertices": lambda *a: _count("vertex", a),
        "ninputs": lambda: float(ninputs),
        # pcg79 (the test kinds of Switch-If)
        "hasattrib": lambda *a: _has(a),
        "hasgroup": lambda *a: float(_grp(a) >= 0),
        "ngroup": lambda *a: _grp(a),
        "attribmin": lambda *a: _agg(np.min, a),
        "attribmax": lambda *a: _agg(np.max, a),
        "attribmean": lambda *a: _agg(np.mean, a),
    }


def eval_select(spec, geo=None, ninputs=0):
    """
    Switch's Select Input: read as a number when possible, otherwise evaluate as an expression.
    Houdini's field works the same way -- a plain number is a valid expression anyway.
    """
    s = str(spec).strip()
    if not s:
        return 0
    try:
        return int(s, 10)
    except ValueError:
        pass
    try:
        return int(round(float(s)))
    except ValueError:
        pass
    return int(round(_eval(s, geo_funcs(geo, ninputs),
                           "Available functions (all read the ctrl input): {}")))


SWITCHIF_MERGE = ("all", "any")


def eval_tests(tests, geo=None, merge="all"):
    """
    Switch-If tests: one expression per line (lines starting with # are comments), nonzero counts as true.
    merge = all (true only if all are true) / any (true if any is true). Returns (result, per-line results).
    The functions are the same as Switch's Select Input (detail / npoints / hasattrib / attribmax …),
    reading the geometry under test.
    """
    if merge not in SWITCHIF_MERGE:
        raise ValueError(f"Merge must be one of {SWITCHIF_MERGE}")
    lines = [ln.strip() for ln in str(tests).splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("#")]
    if not lines:
        raise ValueError("Tests is empty: write one condition per line, e.g. npoints() > 0")
    fns = geo_funcs(geo, 1)
    vals = [_eval(ln, fns, "Available functions (reading the test geometry): {}") != 0.0
            for ln in lines]
    return (all(vals) if merge == "all" else any(vals)), vals


def _inputs(expr_widgets: dict):
    """Shared INPUT_TYPES: a number of expression widgets + six optional float sockets."""
    return {
        "required": expr_widgets,
        # forceInput makes it show up directly as a socket rather than a widget. Placed in optional,
        # so when unwired we get None, treated as 0.
        "optional": {v: ("FLOAT", {"default": 0.0, "forceInput": True})
                     for v in VARS},
    }


def _collect(kw):
    return {v: float(kw.get(v) or 0.0) for v in VARS}


class PCG_Value:
    """A float value that can fan out to many parameters. The "global variable" of the graph."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "value": ("FLOAT", {"default": 1.0, "min": -1e9, "max": 1e9,
                                "step": 0.01}),
        }}
    RETURN_TYPES = ("FLOAT", "INT")
    RETURN_NAMES = ("float", "int")
    FUNCTION = "run"
    CATEGORY = "PCG/param"

    def run(self, value):
        return (float(value), int(round(value)))


class PCG_Expr:
    """Single-value expression. a~f are the wired inputs; unwired ones count as 0."""
    @classmethod
    def INPUT_TYPES(cls):
        return _inputs({"expr": ("STRING", {"default": "a * 2 + b",
                                            "multiline": False})})
    RETURN_TYPES = ("FLOAT", "INT")
    RETURN_NAMES = ("float", "int")
    FUNCTION = "run"
    CATEGORY = "PCG/param"

    def run(self, expr, **kw):
        v = _eval(expr, _collect(kw))
        return (v, int(round(v)))


class PCG_Expr3:
    """
    Three expressions sharing the same set of inputs. For driving triplet parameters like tx/ty/tz or rx/ry/rz,
    much cleaner than dragging out three PCG_Expr.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return _inputs({
            "expr_x": ("STRING", {"default": "a", "multiline": False}),
            "expr_y": ("STRING", {"default": "0", "multiline": False}),
            "expr_z": ("STRING", {"default": "a", "multiline": False}),
        })
    RETURN_TYPES = ("FLOAT", "FLOAT", "FLOAT")
    RETURN_NAMES = ("x", "y", "z")
    FUNCTION = "run"
    CATEGORY = "PCG/param"

    def run(self, expr_x, expr_y, expr_z, **kw):
        vals = _collect(kw)
        return tuple(_eval(e, vals) for e in (expr_x, expr_y, expr_z))


class PCG_Frame:
    """
    The **single source of truth** for the timeline. The playbar (web/pcg_playbar.js) drives this node.

    Outputs:
        frame       current frame number (INT)
        frame_f     the same frame number, FLOAT version
        t           normalized 0-1: (frame − start) / (end − start)
        frames      end − start + 1(INT)
        seconds     (frame − start) / fps

    **Giving the frame number twice is necessary, not redundant.** litegraph's type check is string equality,
    "INT" cannot connect to a "FLOAT" socket -- and most downstream parameters to drive (COP Noise's
    time, all kinds of angles and distances) are FLOAT. With only INT the most common wire could not be connected at all,
    and the frontend just "won't connect", without telling you why.

    ━━ Why "one node + one wire" rather than a Houdini-style environment variable `$F`
    ComfyUI's cache is keyed on the **input hash**: when frame changes, this node's hash changes, and
    all nodes downstream of it are automatically invalidated and recooked, while the time-independent half of the graph is reused as is. That is exactly
    the behaviour you want when scrubbing the timeline, without writing a single IS_CHANGED.

    A `$F`-style environment variable actually cannot be done right in this model: without edges the cache system cannot see the dependency,
    so either the whole graph recooks (each scrub stalls for half a minute), or what should recook does not (scrubbing does nothing). So
    the extra wires are **what you pay for it**, not a compromise.

    ━━ A graph can have several Frame nodes
    The playbar writes the same frame into **all** Frame nodes -- there is only one timeline. But each
    node's start/end can differ, so each computes its own `t`: a 0-23 main timeline paired with a
    12-18 "do a secondary action within this segment" is a common setup.

    ━━ How to hook it up
    Wire frame / t directly into the target widget (right-click, Convert widget to input). For curves,
    put an Expression (PCG) in between: `fit(a, 0, 1, 0, 360)` is one full camera turn,
    `sin(a*TAU)*0.5+0.5` is one back-and-forth. The expression function library is the same as Wrangle's.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "frame": ("INT", {"default": 0, "min": -1 << 20, "max": 1 << 20}),
            "start": ("INT", {"default": 0, "min": -1 << 20, "max": 1 << 20}),
            "end": ("INT", {"default": 23, "min": -1 << 20, "max": 1 << 20}),
            "fps": ("FLOAT", {"default": 24.0, "min": 0.01, "max": 1000.0,
                              "step": 0.01}),
        }}
    RETURN_TYPES = ("INT", "FLOAT", "FLOAT", "INT", "FLOAT")
    RETURN_NAMES = ("frame", "frame_f", "t", "frames", "seconds")
    FUNCTION = "run"
    CATEGORY = "PCG/param"

    def run(self, frame, start, end, fps):
        f, a, b = int(frame), int(start), int(end)
        span = b - a
        # span can be 0 (a single frame) or negative (a range in reverse). Division by 0 must be guarded,
        # but **don't** guard against negative ones while at it -- end < start is a valid reversed range
        t = 0.0 if span == 0 else (f - a) / float(span)
        n = abs(span) + 1
        return (f, float(f), float(t), int(n),
                (f - a) / max(float(fps), 1e-6))


def _chan_inputs(keys: dict):
    """Shared INPUT_TYPES of the Channel family. frame comes first, it is the one most often promoted to a socket."""
    return {"required": {
        "frame": ("FLOAT", {"default": 0.0, "min": -1e6, "max": 1e6,
                            "step": 1.0}),
        **keys,
        "interp": (list(_chn.INTERPS), {"default": "cubic"}),
        "extrapolate": (list(_chn.EXTRAPS),),
        "scale": ("FLOAT", {"default": 1.0, "min": -1e9, "max": 1e9,
                            "step": 0.01}),
        "offset": ("FLOAT", {"default": 0.0, "min": -1e9, "max": 1e9,
                             "step": 0.01}),
    }}


class PCG_Channel:
    """
    Keyframe channel -- a curve evaluated per frame. **The backbone of animation.**

    Wire Frame (PCG)'s `frame_f` into frame here, and the output into the parameter to animate
    (right-click, Convert widget to input); scrubbing the playbar animates it.

        0:0  12:1.5:ease  18:1.5  24:0     ease in over the first 12 frames, hold 6 frames, then pull back out

    The syntax, seven interpolations and five out-of-range modes are all in the module docs of geo/channel.py. Key points:

      · `frame:value[:interp][@slope]`, space-separated, in any order (gets sorted)
      · **the key an interpolation is written on governs the segment to its right**
      · without @slope it is computed automatically, using a weighted difference that is exact for quadratics with any spacing
        (the textbook Catmull-Rom is only exact for evenly spaced keys)

    Division of labour with Expression (PCG): expressions suit "computed from other values" (fit / sin /
    geometry reads), channels suit "what the value should be at frame N". To combine them, chain them: channel → a,
    expression `a * 2`.

    scale / offset is the last step at the output: `value = channel value × scale + offset`.
    It exists because the same curve (say a 0→1 ease-in-out) can drive an angle, a distance and an intensity,
    three parameters with completely different units, without copying the curve three times -- in graphs that copy it three times,
    one copy is always missed when the animation is changed.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return _chan_inputs({
            "keys": ("STRING", {"default": _chn.EXAMPLE, "multiline": False}),
        })
    RETURN_TYPES = ("FLOAT", "INT", "STRING")
    RETURN_NAMES = ("value", "int", "info")
    FUNCTION = "run"
    CATEGORY = "PCG/param"

    def run(self, frame, keys, interp, extrapolate, scale, offset):
        v = _chn.value_at(keys, frame, interp, extrapolate)
        v = v * float(scale) + float(offset)
        return (v, int(round(v)), _chn.info(keys, interp))


class PCG_Channel3:
    """
    Three channels sharing the same frame number. For triplet parameters like camera translate and rotate.

    It saves more than three wires: with three curves on one node you can see at a glance whether the x / y / z keyframes
    **are on the same frames**. Offsetting them is fine (that is what gives weight), but it should be deliberate.

    An empty channel equals `0:0` (a curve that is always 0) -- when you only want to animate y you don't need to author one for x / z.
    Exactly the same as writing `0:0`, still × Scale + Offset (before pcg90 an empty one output 0 directly without adding Offset,
    which did not match `0:0`).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return _chan_inputs({
            "keys_x": ("STRING", {"default": "0:0  24:0",
                                  "multiline": False}),
            "keys_y": ("STRING", {"default": "0:0  12:1:ease  24:0",
                                  "multiline": False}),
            "keys_z": ("STRING", {"default": "", "multiline": False}),
        })
    RETURN_TYPES = ("FLOAT", "FLOAT", "FLOAT", "STRING")
    RETURN_NAMES = ("x", "y", "z", "info")
    FUNCTION = "run"
    CATEGORY = "PCG/param"

    def run(self, frame, keys_x, keys_y, keys_z, interp, extrapolate,
            scale, offset):
        out = []
        for spec in (keys_x, keys_y, keys_z):
            v = (_chn.value_at(spec, frame, interp, extrapolate)
                 if str(spec).strip() else 0.0)
            out.append(v * float(scale) + float(offset))
        parts = [f"{ax}={v:.4g}" for ax, v in zip("xyz", out)]
        return (out[0], out[1], out[2],
                f"frame {float(frame):g}  " + "  ".join(parts))


NODE_CLASS_MAPPINGS = {
    "PCG_Value": PCG_Value,
    "PCG_Expr": PCG_Expr,
    "PCG_Expr3": PCG_Expr3,
    "PCG_Frame": PCG_Frame,
    "PCG_Channel": PCG_Channel,
    "PCG_Channel3": PCG_Channel3,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "PCG_Value": "Value (PCG)",
    "PCG_Expr": "Expression (PCG)",
    "PCG_Expr3": "Expression XYZ (PCG)",
    "PCG_Frame": "Frame (PCG)",
    "PCG_Channel": "Channel (PCG)",
    "PCG_Channel3": "Channel XYZ (PCG)",
}
