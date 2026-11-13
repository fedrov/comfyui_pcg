"""
The per-pixel grab bag: color correction, channel conversion / split / merge / swizzle, vector math, functions, logic,
mask combine, premultiply, illegal pixels, tone mapping, keying, layer management, alignment, Wrangle, fill, vignette,
random, depth conversion.

Copernicus splits these into forty-odd nodes (Mono to RGB, RGB to RGBA, UV to RGB ... one
each; Bright, Contrast, Gamma, HSV Adjust, Color Correct one each). Here they're merged by **what
they do**, with a dropdown choosing the direction -- the mapping table is in tests/copernicus_map.py, and the tests
check one by one that "every Houdini node has a home".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This batch is all numpy (computed in float64, put back at the original backend's precision)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
They're all small per-pixel operations; arithmetic isn't the bottleneck. torch input is moved to the CPU, computed, and moved back (the output stays on the original
device). If one really becomes a bottleneck later it can be moved to the op table individually.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A few conventions that fail silently
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  · gamma > 1 = brighter (t^(1/gamma)), the same direction as Levels; negative values keep their sign
  · saturation interpolates toward Rec.709 luminance (luminance unchanged), HSV adjust goes through HSV -- the two give different results,
    both are provided
  · color operations **don't touch alpha** (channel 4)
  · premultiply / unpremultiply: unpremultiply gives 0 where alpha = 0, not nan
  · logic's == has a tolerance (floating-point equality almost never holds)
"""
from __future__ import annotations

import math
import re

import numpy as np

from ..npcompat import select as _select  # np.select breaks if a node pack rebinds np.bool

from .core import CopImage, DEFAULT_LAYER, conform
from . import backend as bk
from .levels import LUMA_709


# ═══════════════════════════════════════════════════════════════ Read / write
def getn(img, name):
    """Layer -> numpy float64 (H,W,C)."""
    a = img.need(str(name).strip() or DEFAULT_LAYER)
    return np.asarray(bk.backend_of(a).to_numpy(a), np.float64)


def put(out, name, arr, like=None):
    """numpy (H,W,C) or (H,W) -> put back on out's backend."""
    ref = like if like is not None else out
    xp = ref.backend if len(ref) else bk.NUMPY
    a = np.asarray(arr, np.float64)
    if a.ndim == 2:
        a = a[:, :, None]
    if xp is bk.NUMPY:
        a = a.astype(np.float32)
    out.set(str(name).strip() or DEFAULT_LAYER, xp.asarray(a))
    return out


def names_of(img, layers):
    ns = [n for n in str(layers).split() if n]
    for n in ns:
        img.need(n)
    return ns or img.names


def _out(img, keep=True):
    return img.copy() if keep else CopImage(img.xres, img.yres)


def _vec(spec, n):
    """"0 0 1" / "0.5" -> vector of length n (padded with the last value if short)."""
    v = [float(x) for x in str(spec).replace(",", " ").split()] or [0.0]
    while len(v) < n:
        v.append(v[-1])
    return np.asarray(v[:n], np.float64)


def _operand(img, spec, like):
    """Second operand: a layer name, or a string of numbers (constant vector)."""
    s = str(spec).strip()
    if s in img:
        b = getn(img, s)
        return b
    return np.broadcast_to(_vec(s, like.shape[2]).reshape(1, 1, -1),
                           like.shape)


# ═══════════════════════════════════════════════════════════ Color correction
def rgb_to_hsv(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    d = mx - mn
    h = np.zeros_like(mx)
    ok = d > 1e-12
    rr = ok & (mx == r)
    gg = ok & (mx == g) & ~rr
    bb = ok & ~rr & ~gg
    dd = np.where(ok, d, 1.0)
    h = np.where(rr, ((g - b) / dd) % 6.0, h)
    h = np.where(gg, (b - r) / dd + 2.0, h)
    h = np.where(bb, (r - g) / dd + 4.0, h)
    h = h / 6.0
    s = np.where(mx > 1e-12, d / np.where(mx > 1e-12, mx, 1.0), 0.0)
    return np.stack([h, s, mx], -1)


def hsv_to_rgb(hsv):
    h, s, v = hsv[..., 0] % 1.0, hsv[..., 1], hsv[..., 2]
    i = np.floor(h * 6.0)
    f = h * 6.0 - i
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    i = i.astype(np.int64) % 6
    cs = [i == k for k in range(6)]
    r = _select(cs, [v, q, p, p, t, v])
    g = _select(cs, [t, v, v, q, p, p])
    b = _select(cs, [p, p, t, v, v, q])
    return np.stack([r, g, b], -1)


def _pow_signed(t, g):
    return np.sign(t) * np.abs(t) ** g


def color_correct(img, layers="", exposure=0.0, brightness=0.0,
                  contrast=1.0, pivot=0.18, gamma=1.0, saturation=1.0,
                  hue_shift=0.0, hsv_saturation=1.0, hsv_value=1.0,
                  mask_layer=""):
    """
    Exposure (x2^e) -> brightness (+) -> contrast (about pivot) -> gamma (t^(1/g), sign-preserving) -> saturation
    (interpolate toward Rec.709 luminance) -> HSV (hue rotate, Sx, Vx). If mask_layer is given, blends back by it.

    Single-channel layers only get the first four steps (no color). alpha is unchanged.
    """
    if img is None:
        return CopImage()
    out = img.copy()
    m = None
    if str(mask_layer).strip():
        m = np.clip(getn(img, mask_layer)[..., :1], 0, 1)
    for n in names_of(img, layers):
        if n == str(mask_layer).strip():
            continue
        a0 = getn(img, n)
        C = a0.shape[2]
        rgb = a0[..., :min(C, 3)].copy()
        # each step is skipped entirely at its default value -- otherwise an "identity" like (x - p)·1 + p is off by
        # one ulp in floating point, and a node with default parameters wouldn't be a bit-exact identity
        if float(exposure) != 0.0:
            rgb = rgb * (2.0 ** float(exposure))
        if float(brightness) != 0.0:
            rgb = rgb + float(brightness)
        if float(contrast) != 1.0:
            rgb = (rgb - pivot) * float(contrast) + pivot
        if abs(float(gamma) - 1.0) > 1e-12:
            rgb = _pow_signed(rgb, 1.0 / max(float(gamma), 1e-6))
        if C >= 3 and float(saturation) != 1.0:
            y = (rgb * np.asarray(LUMA_709)).sum(-1, keepdims=True)
            rgb = y + (rgb - y) * float(saturation)
        if C >= 3:
            if (abs(float(hue_shift)) > 1e-12 or abs(hsv_saturation - 1) > 1e-12
                    or abs(hsv_value - 1) > 1e-12):
                hsv = rgb_to_hsv(rgb)
                hsv[..., 0] = hsv[..., 0] + float(hue_shift) / 360.0
                hsv[..., 1] = hsv[..., 1] * float(hsv_saturation)
                hsv[..., 2] = hsv[..., 2] * float(hsv_value)
                rgb = hsv_to_rgb(hsv)
        res = a0.copy()
        res[..., :rgb.shape[2]] = rgb
        if m is not None:
            res = a0 + (res - a0) * m
        put(out, n, res, img)
    return out


def invert(img, layers="", pivot=1.0, alpha=False):
    """x -> pivot - x. alpha (channel 4) isn't inverted by default."""
    if img is None:
        return CopImage()
    out = img.copy()
    for n in names_of(img, layers):
        a = getn(img, n)
        r = float(pivot) - a
        if a.shape[2] == 4 and not alpha:
            r[..., 3] = a[..., 3]
        put(out, n, r, img)
    return out


def clamp(img, layers="", lo=0.0, hi=1.0):
    if img is None:
        return CopImage()
    if float(lo) > float(hi):
        raise ValueError("Min can't be greater than Max")
    out = img.copy()
    for n in names_of(img, layers):
        put(out, n, np.clip(getn(img, n), float(lo), float(hi)), img)
    return out


# ═══════════════════════════════════════════════════════════ Channels
CONVERSIONS = ("mono_to_rgb", "mono_to_rgba", "rgb_to_rgba", "rgba_to_rgb",
               "rgb_to_uv", "rgba_to_uv", "uv_to_rgb", "uv_to_rgba",
               "rgb_to_mono_luma", "rgb_to_mono_average", "rgb_to_mono_max")
_NEED_C = {"mono": 1, "rgb": 3, "rgba": 4, "uv": 2}


def channel_convert(img, layer=DEFAULT_LAYER, mode="mono_to_rgb",
                    out_layer="", alpha=1.0, fill=0.0):
    """
    Copernicus's Mono to RGB / RGB to RGBA / UV to RGB ... merged into one dropdown.

    When the input channel count is wrong: extra channels are truncated, too few raise an error -- silently zero-padding would let a miswiring like
    "converting RGB as UV" propagate all the way down. Padded channels: alpha gets Alpha, the rest get Fill (the b channel of
    uv->rgb).
    """
    if img is None:
        return CopImage()
    if mode not in CONVERSIONS:
        raise ValueError(f"Mode must be one of {CONVERSIONS}")
    a = getn(img, layer)
    H, W, C = a.shape
    src = mode.split("_to_")[0]
    dst = mode.split("_to_")[1]
    need = _NEED_C[src]
    if C < need:
        raise ValueError(f"'{layer}' has only {C} channels; {mode} needs at least {need}")
    x = a[..., :need]
    if dst.startswith("mono"):
        kind = dst.split("_", 1)[1]
        if kind == "luma":
            r = (x[..., :3] * np.asarray(LUMA_709)).sum(-1, keepdims=True)
        elif kind == "average":
            r = x[..., :3].mean(-1, keepdims=True)
        else:
            r = x[..., :3].max(-1, keepdims=True)
    else:
        k = _NEED_C[dst]
        if src == "mono":
            r = np.repeat(x, min(k, 3), -1)
        else:
            r = x[..., :min(need, k)]
        while r.shape[2] < k:
            v = float(alpha) if r.shape[2] == 3 else float(fill)
            r = np.concatenate([r, np.full((H, W, 1), v)], -1)
    out = img.copy()
    return put(out, str(out_layer).strip() or layer, r, img)


_CH = {"r": 0, "g": 1, "b": 2, "a": 3, "x": 0, "y": 1, "z": 2, "w": 3,
       "u": 0, "v": 1}


def channel_split(img, layer=DEFAULT_LAYER, names="r g b a", keep=True):
    """Split one layer into one layer per channel, layer name = layer.suffix (suffixes taken in order from names)."""
    if img is None:
        return CopImage()
    a = getn(img, layer)
    suf = str(names).split() or ["r", "g", "b", "a"]
    out = _out(img, keep)
    for c in range(a.shape[2]):
        s = suf[c] if c < len(suf) else str(c)
        put(out, f"{layer}.{s}", a[..., c:c + 1], img)
    return out


def channel_join(img, layers="C.r C.g C.b", out_layer=DEFAULT_LAYER):
    """Concatenate **all** channels of several layers in order into one layer (combining single-channel layers into RGB is the most common use)."""
    if img is None:
        return CopImage()
    ns = [n for n in str(layers).split() if n]
    if not ns:
        raise ValueError("Layers is empty")
    parts = [getn(img, n) for n in ns]
    r = np.concatenate(parts, -1)
    if r.shape[2] > 4:
        raise ValueError(f"The result has {r.shape[2]} channels; at most 4 allowed")
    out = img.copy()
    return put(out, out_layer, r, img)


def swizzle(img, layer=DEFAULT_LAYER, pattern="bgra", out_layer=""):
    """
    Channel swizzle / extract: one output channel per character of pattern. r g b a / x y z w / u v take
    the corresponding channel, 0 and 1 are constants. "bgr" swaps channels, "a" extracts alpha, "rrr1" converts gray to RGBA.
    """
    if img is None:
        return CopImage()
    a = getn(img, layer)
    p = str(pattern).strip().lower()
    if not 1 <= len(p) <= 4:
        raise ValueError("Pattern needs 1-4 characters")
    cols = []
    for ch in p:
        if ch in "01":
            cols.append(np.full(a.shape[:2] + (1,), float(ch)))
            continue
        if ch not in _CH:
            raise ValueError(f"Unrecognized '{ch}' in Pattern (allowed: rgba / xyzw / uv / 0 / 1)")
        k = _CH[ch]
        if k >= a.shape[2]:
            raise ValueError(f"'{layer}' has only {a.shape[2]} channels, can't take '{ch}'")
        cols.append(a[..., k:k + 1])
    out = img.copy()
    return put(out, str(out_layer).strip() or layer, np.concatenate(cols, -1),
               img)


# ═══════════════════════════════════════════════════════════ Vector math
VEC_OPS = ("dot", "cross", "length", "normalize", "add", "subtract",
           "multiply", "divide", "min", "max", "distance", "reflect", "lerp")


def vector_math(img, a=DEFAULT_LAYER, b="0 0 1", op="dot", out_layer="out",
                t=0.5):
    """
    Vector operations. b is a layer name or a constant ("0 0 1"). dot / length / distance output a single channel;
    cross needs 3 channels; divide by zero gives 0; reflect = a - 2(a·n̂)n̂ (b as the normal).
    """
    if img is None:
        return CopImage()
    if op not in VEC_OPS:
        raise ValueError(f"Op must be one of {VEC_OPS}")
    A = getn(img, a)
    B = _operand(img, b, A)
    if B.shape[2] != A.shape[2]:
        if B.shape[2] == 1:
            B = np.broadcast_to(B, A.shape)
        else:
            k = min(A.shape[2], B.shape[2])
            A, B = A[..., :k], B[..., :k]
    if op == "dot":
        r = (A * B).sum(-1, keepdims=True)
    elif op == "cross":
        if A.shape[2] < 3:
            raise ValueError("cross needs 3 channels")
        r = np.cross(A[..., :3], B[..., :3])
    elif op == "length":
        r = np.linalg.norm(A, axis=-1, keepdims=True)
    elif op == "normalize":
        ln = np.linalg.norm(A, axis=-1, keepdims=True)
        r = np.where(ln > 1e-12, A / np.where(ln > 1e-12, ln, 1.0), 0.0)
    elif op == "add":
        r = A + B
    elif op == "subtract":
        r = A - B
    elif op == "multiply":
        r = A * B
    elif op == "divide":
        r = np.where(B != 0, A / np.where(B != 0, B, 1.0), 0.0)
    elif op == "min":
        r = np.minimum(A, B)
    elif op == "max":
        r = np.maximum(A, B)
    elif op == "distance":
        r = np.linalg.norm(A - B, axis=-1, keepdims=True)
    elif op == "reflect":
        ln = np.linalg.norm(B, axis=-1, keepdims=True)
        nn = np.where(ln > 1e-12, B / np.where(ln > 1e-12, ln, 1.0), 0.0)
        r = A - 2.0 * (A * nn).sum(-1, keepdims=True) * nn
    else:
        r = A + (B - A) * float(t)
    out = img.copy()
    return put(out, out_layer, r, img)


XFORM_MODES = ("rotate_2d", "rotate_3d", "scale", "matrix", "tangent_to_world",
               "world_to_tangent")


def _euler(rx, ry, rz):
    x, y, z = (math.radians(float(v)) for v in (rx, ry, rz))
    Rx = np.array([[1, 0, 0], [0, math.cos(x), -math.sin(x)],
                   [0, math.sin(x), math.cos(x)]])
    Ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0],
                   [-math.sin(y), 0, math.cos(y)]])
    Rz = np.array([[math.cos(z), -math.sin(z), 0],
                   [math.sin(z), math.cos(z), 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def vector_transform(img, layer="N", mode="rotate_3d", angle=0.0,
                     rotate="0 0 0", scale="1 1 1", matrix="1 0 0 0 1 0 0 0 1",
                     normal_layer="N", tangent_layer="", out_layer=""):
    """
    Transforms a vector layer (not the image):
      rotate_2d        rotates the first two components about z by angle degrees (Vector Transform 2D)
      rotate_3d        Euler angles xyz (degrees), x first, then y, then z
      scale / matrix   per-component scale / 3x3 matrix (row-major, v' = M v)
      tangent_to_world tangent space -> world (Space Transform): builds an orthonormal basis TBN
      world_to_tangent from normal_layer. When tangent_layer is empty, T is the projection of +x onto the tangent plane
                       (consistent with Height to Normal's +u direction)
    """
    if img is None:
        return CopImage()
    if mode not in XFORM_MODES:
        raise ValueError(f"Mode must be one of {XFORM_MODES}")
    V = getn(img, layer)
    C = V.shape[2]
    if mode == "rotate_2d":
        if C < 2:
            raise ValueError("rotate_2d needs at least 2 channels")
        c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        r = V.copy()
        r[..., 0] = c * V[..., 0] - s * V[..., 1]
        r[..., 1] = s * V[..., 0] + c * V[..., 1]
    else:
        if C < 3:
            raise ValueError(f"{mode} needs 3 channels")
        v3 = V[..., :3]
        if mode == "rotate_3d":
            M = _euler(*_vec(rotate, 3))
            r3 = v3 @ M.T
        elif mode == "scale":
            r3 = v3 * _vec(scale, 3)
        elif mode == "matrix":
            m = _vec(matrix, 9)
            r3 = v3 @ m.reshape(3, 3).T
        else:
            Nn = getn(img, normal_layer)[..., :3]
            Nn = Nn / np.maximum(np.linalg.norm(Nn, axis=-1, keepdims=True),
                                 1e-12)
            if str(tangent_layer).strip():
                T0 = getn(img, tangent_layer)[..., :3]
            else:
                T0 = np.broadcast_to(np.array([1.0, 0, 0]), Nn.shape)
            T = T0 - (T0 * Nn).sum(-1, keepdims=True) * Nn
            ln = np.linalg.norm(T, axis=-1, keepdims=True)
            # when +x is parallel to the normal (surface facing x), switch to another reference axis
            alt = np.broadcast_to(np.array([0, 1.0, 0]), Nn.shape)
            T2 = alt - (alt * Nn).sum(-1, keepdims=True) * Nn
            T = np.where(ln > 1e-6, T, T2)
            T = T / np.maximum(np.linalg.norm(T, axis=-1, keepdims=True),
                               1e-12)
            Bt = np.cross(Nn, T)
            if mode == "tangent_to_world":
                r3 = (v3[..., 0:1] * T + v3[..., 1:2] * Bt
                      + v3[..., 2:3] * Nn)
            else:
                r3 = np.stack([(v3 * T).sum(-1), (v3 * Bt).sum(-1),
                               (v3 * Nn).sum(-1)], -1)
        r = V.copy()
        r[..., :3] = r3
    out = img.copy()
    return put(out, str(out_layer).strip() or layer, r, img)


# ═══════════════════════════════════════════════════════════ Functions / logic
FUNCTIONS = ("abs", "negate", "sqrt", "pow", "exp", "log", "sin", "cos",
             "tan", "floor", "ceil", "round", "frac", "sign", "step",
             "smoothstep", "clamp01", "reciprocal", "mod", "sigmoid")


def function(img, layers="", fn="abs", a=1.0, b=1.0):
    """
    Per-pixel unary functions. pow = x^a (sign-preserving); step = x >= a; smoothstep from a to b;
    mod = x mod a (result has the sign of a); log / sqrt of negatives give 0; reciprocal of 0 gives 0.
    """
    if img is None:
        return CopImage()
    if fn not in FUNCTIONS:
        raise ValueError(f"Function must be one of {FUNCTIONS}")
    a, b = float(a), float(b)
    out = img.copy()
    for n in names_of(img, layers):
        x = getn(img, n)
        if fn == "abs":
            r = np.abs(x)
        elif fn == "negate":
            r = -x
        elif fn == "sqrt":
            r = np.sqrt(np.maximum(x, 0.0))
        elif fn == "pow":
            r = _pow_signed(x, a)
        elif fn == "exp":
            r = np.exp(np.minimum(x, 700.0))
        elif fn == "log":
            r = np.where(x > 0, np.log(np.where(x > 0, x, 1.0)), 0.0)
        elif fn in ("sin", "cos", "tan"):
            r = getattr(np, fn)(x)
        elif fn == "floor":
            r = np.floor(x)
        elif fn == "ceil":
            r = np.ceil(x)
        elif fn == "round":
            r = np.round(x)
        elif fn == "frac":
            r = x - np.floor(x)
        elif fn == "sign":
            r = np.sign(x)
        elif fn == "step":
            r = (x >= a).astype(np.float64)
        elif fn == "smoothstep":
            t = np.clip((x - a) / ((b - a) or 1e-12), 0.0, 1.0)
            r = t * t * (3 - 2 * t)
        elif fn == "clamp01":
            r = np.clip(x, 0.0, 1.0)
        elif fn == "reciprocal":
            r = np.where(x != 0, 1.0 / np.where(x != 0, x, 1.0), 0.0)
        elif fn == "mod":
            r = np.mod(x, a) if a != 0 else x * 0.0
        else:
            r = 1.0 / (1.0 + np.exp(-np.clip(x, -700, 700)))
        put(out, n, r, img)
    return out


LOGIC_OPS = ("greater", "greater_equal", "less", "less_equal", "equal",
             "not_equal", "and", "or", "xor", "not")


def logic(img, a=DEFAULT_LAYER, b="0.5", op="greater", tolerance=1e-6,
          out_layer="mask"):
    """
    Comparison / boolean operations, outputs a 0/1 mask (single channel; with multiple channels, per channel then **all** must hold).
    and / or / xor / not treat > 0.5 as true. equal has a tolerance.
    """
    if img is None:
        return CopImage()
    if op not in LOGIC_OPS:
        raise ValueError(f"Op must be one of {LOGIC_OPS}")
    A = getn(img, a)
    B = _operand(img, b, A)
    if B.shape[2] != A.shape[2]:
        B = np.broadcast_to(B[..., :1], A.shape)
    tol = float(tolerance)
    ta, tb = A > 0.5, B > 0.5
    m = {"greater": A > B, "greater_equal": A >= B - tol, "less": A < B,
         "less_equal": A <= B + tol, "equal": np.abs(A - B) <= tol,
         "not_equal": np.abs(A - B) > tol, "and": ta & tb, "or": ta | tb,
         "xor": ta ^ tb, "not": ~ta}[op]
    r = m.all(-1, keepdims=True).astype(np.float64)
    out = img.copy()
    return put(out, out_layer, r, img)


COMBINE_OPS = ("union", "intersect", "add", "multiply", "subtract",
               "difference", "screen", "average",
               # pcg100: what Houdini Mask Combine really is -- each layer carries its own blend mode,
               # stacked in turn starting from Starting Value. Appended at the end, so the first eight modes behave as before
               "layer_stack")

# Houdini Mask Combine's Blend Mode menu -> composite._blend tokens.
# Sharpen's docs have only one sentence, "increase contrast with this layer as the midpoint", no formula, so it isn't implemented
STACK_MODES = {"blend": "replace", "add": "add", "subtract": "subtract",
               "multiply": "multiply", "divide": "divide", "screen": "screen",
               "hypot": "hypot", "difference": "difference",
               "exclusion": "exclusion", "maximum": "lighten",
               "minimum": "darken", "overlay": "overlay",
               "softlight": "softlight", "hardlight": "hardlight",
               "dodge": "dodge", "burn": "burn"}


def parse_stack(spec):
    """
    Mask Layers multi-line text -> [(layer name, channel index, mode, amount)]. One layer per line, stacked top to bottom:

        layer[.channel]  [mode]  [Mask amount]

    mode defaults to blend (Houdini's default), amount defaults to 1. A leading `#` = this layer's toggle is off
    (the checkbox in front of each layer in Houdini), and the whole line is skipped. Channel is r/g/b/a or x/y/z/w; if omitted, channel 0
    is used (Houdini's Channel Extract; Channel Mix / Light Direction aren't implemented).
    """
    rows = []
    for ln in str(spec).replace(";", "\n").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        tk = ln.replace(",", " ").split()
        if len(tk) > 3:
            raise ValueError(f"A Mask Layers line has at most three items (layer mode amount): '{ln}'")
        name, ch = tk[0], 0
        if "." in name and name.rsplit(".", 1)[1].lower() in _CH:
            name, c = name.rsplit(".", 1)
            ch = _CH[c.lower()]
        mode = tk[1].lower() if len(tk) > 1 else "blend"
        if mode not in STACK_MODES:
            raise ValueError(
                f"Mask Layers blend mode must be one of {tuple(STACK_MODES)}, got '{mode}'")
        rows.append((name, ch, mode, float(tk[2]) if len(tk) > 2 else 1.0))
    return rows


def mask_combine(img, layers="mask", op="union", out_layer="mask",
                 clamp01=True, stack="", start=0.0, fold=False,
                 complement=False, clamp_min=None, clamp_max=None):
    """
    Combines several masks into one. union = max, intersect = min, add sums, multiply multiplies,
    subtract = the first minus the rest, difference = |a - b| accumulated in turn, screen =
    1 - Π(1 - m) (soft union, overlaps don't hard-cap at 1), average averages. Only channel 0 is used.

    layer_stack (pcg100) is Houdini's approach: the result starts from start, and for each layer in stack
    `r = lerp(r, blend(r, layer), amount)`, each layer with its own mode (see parse_stack). This mode
    doesn't read layers.

    Post-processing runs in the order fold -> complement -> clamp_min / clamp_max -> clamp01
    (the order on Houdini's panel; the docs don't state the execution order). Amplitude / Center / Contrast /
    Bias / Gain / Gamma / the two Remaps have no formula in the docs and aren't implemented.
    """
    if img is None:
        return CopImage()
    if op not in COMBINE_OPS:
        raise ValueError(f"Op must be one of {COMBINE_OPS}")
    if op == "layer_stack":
        from .composite import _blend
        rows = parse_stack(stack)
        H, W = img.yres, img.xres
        r = np.full((H, W, 1), float(start), np.float64)
        for name, ch, mode, amt in rows:
            a = getn(img, name)
            if ch >= a.shape[2]:
                raise ValueError(
                    f"Layer '{name}' has only {a.shape[2]} channels, can't take channel {ch}")
            m = a[..., ch:ch + 1]
            r = r + (_blend(r, m, STACK_MODES[mode], bk.NUMPY) - r) * amt
    else:
        ns = [n for n in str(layers).split() if n]
        if not ns:
            raise ValueError("Layers is empty")
        ms = [getn(img, n)[..., :1] for n in ns]
        r = ms[0]
        for m in ms[1:]:
            if op == "union":
                r = np.maximum(r, m)
            elif op == "intersect":
                r = np.minimum(r, m)
            elif op in ("add", "average"):
                r = r + m
            elif op == "multiply":
                r = r * m
            elif op == "subtract":
                r = r - m
            elif op == "difference":
                r = np.abs(r - m)
        if op == "screen":
            r = 1.0 - np.prod([1.0 - np.clip(m, 0, 1) for m in ms], axis=0)
        if op == "average":
            r = r / len(ms)
    if fold:
        r = np.abs(r)
    if complement:
        r = 1.0 - r
    if clamp_min is not None:
        r = np.maximum(r, float(clamp_min))
    if clamp_max is not None:
        r = np.minimum(r, float(clamp_max))
    if clamp01:
        r = np.clip(r, 0.0, 1.0)
    out = img.copy()
    return put(out, out_layer, r, img)


# ═══════════════════════════════════════════════════ Premultiply / illegal pixels / tone
def premultiply(img, layer=DEFAULT_LAYER, mode="premultiply", alpha_layer=""):
    """RGB x alpha (or divide back). alpha defaults to channel 4; unpremultiply gives 0 where alpha = 0."""
    if img is None:
        return CopImage()
    if mode not in ("premultiply", "unpremultiply"):
        raise ValueError("Mode must be one of premultiply / unpremultiply")
    a = getn(img, layer)
    if str(alpha_layer).strip():
        al = getn(img, alpha_layer)[..., :1]
    else:
        if a.shape[2] < 4:
            raise ValueError(f"'{layer}' has no alpha (channel 4); give an Alpha Layer")
        al = a[..., 3:4]
    k = min(a.shape[2], 3)
    r = a.copy()
    if mode == "premultiply":
        r[..., :k] = a[..., :k] * al
    else:
        ok = np.abs(al) > 1e-12
        r[..., :k] = np.where(ok, a[..., :k] / np.where(ok, al, 1.0), 0.0)
    out = img.copy()
    return put(out, layer, r, img)


def illegal_pixel(img, layers="", nan=0.0, posinf=1.0, neginf=0.0,
                  clamp_negative=False, mode="replace", highlight="1 0 0",
                  detect="nan_inf", rule="less", value=0.0):
    """
    Replaces nan / ±inf with given values; optionally clamps negatives to 0. Returns (image, report).

    mode = replace is our original approach (three replacement values, one per kind; Houdini doesn't have it). The other four modes
    are Houdini's Illegal Pixels menu (blend / zero / highlight / isolate), together with
    Detect / Rule, in colorkey.illegal_fix; those four don't read the replacement values or Clamp Negative,
    and the report only has flagged (number of bad **pixels**, not components).
    """
    if img is None:
        return CopImage(), {}
    out = img.copy()
    rep = {}
    if mode != "replace":
        from .colorkey import illegal_fix
        for n in names_of(img, layers):
            r, k = illegal_fix(getn(img, n), mode, highlight, detect, rule,
                               value)
            rep[n] = {"flagged": k}
            put(out, n, r, img)
        return out, rep
    for n in names_of(img, layers):
        a = getn(img, n)
        cnt = {"nan": int(np.isnan(a).sum()),
               "posinf": int(np.isposinf(a).sum()),
               "neginf": int(np.isneginf(a).sum())}
        r = np.nan_to_num(a, nan=float(nan), posinf=float(posinf),
                          neginf=float(neginf))
        if clamp_negative:
            cnt["negative"] = int((r < 0).sum())
            r = np.maximum(r, 0.0)
        rep[n] = cnt
        put(out, n, r, img)
    return out, rep


TONEMAPS = ("reinhard", "reinhard_extended", "aces", "hable", "exposure_only")


def tone_map(img, layers="", op="aces", exposure=0.0, white=4.0, srgb=False):
    """
    HDR -> 0-1. reinhard x/(1+x); extended maps white to 1; aces uses Narkowicz's
    fit; hable is the Uncharted 2 curve (white point white). Only RGB is changed, alpha is untouched.
    With srgb on, sRGB is encoded at the end (on for images to be viewed directly, off for ones going into compositing).
    """
    if img is None:
        return CopImage()
    if op not in TONEMAPS:
        raise ValueError(f"Op must be one of {TONEMAPS}")
    out = img.copy()
    w = float(white)

    def hable(x):
        A, B, C, D, E, F = 0.15, 0.50, 0.10, 0.20, 0.02, 0.30
        return ((x * (A * x + C * B) + D * E) / (x * (A * x + B) + D * F)) \
            - E / F

    for n in names_of(img, layers):
        a = getn(img, n)
        k = min(a.shape[2], 3)
        x = np.maximum(a[..., :k], 0.0) * (2.0 ** float(exposure))
        if op == "reinhard":
            y = x / (1.0 + x)
        elif op == "reinhard_extended":
            y = x * (1.0 + x / (w * w)) / (1.0 + x)
        elif op == "aces":
            y = np.clip((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59)
                                                  + 0.14), 0.0, 1.0)
        elif op == "hable":
            y = hable(x) / hable(w)
        else:
            y = x
        y = np.clip(y, 0.0, 1.0)
        if srgb:
            y = np.where(y <= 0.0031308, y * 12.92,
                         1.055 * np.power(np.maximum(y, 1e-12), 1 / 2.4)
                         - 0.055)
        r = a.copy()
        r[..., :k] = y
        put(out, n, r, img)
    return out


# ═══════════════════════════════════════════════════════════ Keying
def chroma_key(img, layer=DEFAULT_LAYER, key="0 1 0", tolerance=0.15,
               softness=0.1, despill=1.0, out_layer="", alpha_layer="alpha",
               premultiply_out=False, method="distance", invert=False,
               hue=(90.0, 150.0), sat=(0.3, 1.0), lum=(0.0, 1.0),
               rolloff=(10.0, 0.1, 0.1), interpolation="linear",
               threshold=0.5, width=0.0, preview=False,
               preview_color="1 0 1"):
    """
    Measures distance to the key color on YCbCr's **chroma plane** (then normalized by luminance): < tolerance
    is fully transparent, then a linear transition over softness to opaque. Only chroma direction is considered, not luminance, so shadows
    and highlights on a green screen are keyed out together.

    Despill: the part of the key color's main channel (G for a green screen) exceeding the average of the other two channels is reduced
    by despill times -- removes green light reflected onto foreground edges without affecting areas that weren't green to begin with.

    method: distance is the scheme above (our own; Houdini doesn't have it); chromakey /
    channel_separation are Houdini Chroma Key's two Methods, swapping only the matte algorithm
    (colorkey.key_matte); despill, premultiply and output layers are as before. Invert flips the matte (same as
    following the matte with an Invert). Preview fills the keyed-out areas with Preview Color:
    color · matte + Preview Color · (1 - matte) (the docs only say "colors the key result with Preview Color";
    the blend is our own choice).
    """
    if img is None:
        return CopImage()
    a = getn(img, layer)
    if a.shape[2] < 3:
        raise ValueError("Keying needs RGB")
    rgb = a[..., :3]
    kc = _vec(key, 3)

    def cbcr(c):
        # chroma is then **divided by luminance**: dark green (green screen in shadow) and bright green differ in CbCr only by a scale factor,
        # and without dividing, shadows are far from the key color and don't get keyed (caught in tests). +0.02 avoids amplifying noise in dark areas
        y = (c * np.asarray(LUMA_709)).sum(-1, keepdims=True)
        cc = np.concatenate([(c[..., 2:3] - y) / 1.8556,
                             (c[..., 0:1] - y) / 1.5748], -1)
        return cc / (np.maximum(y, 0.0) + 0.02)

    if method == "distance":
        d = np.linalg.norm(cbcr(rgb) - cbcr(kc.reshape(1, 1, 3)), axis=-1,
                           keepdims=True)
        t, s = float(tolerance), max(float(softness), 1e-9)
        alpha = np.clip((d - t) / s, 0.0, 1.0)
    else:
        from .colorkey import key_matte
        alpha = key_matte(rgb, method, key, hue, sat, lum, rolloff,
                          interpolation, threshold, width)
    if invert:
        alpha = 1.0 - alpha
    out_rgb = rgb.copy()
    if float(despill) > 0:
        k = int(np.argmax(kc))
        o = [i for i in range(3) if i != k]
        lim = rgb[..., o].mean(-1)
        exc = np.maximum(rgb[..., k] - lim, 0.0)
        out_rgb[..., k] = rgb[..., k] - float(despill) * exc
    if premultiply_out or preview:
        out_rgb = out_rgb * alpha
    if preview:
        out_rgb = out_rgb + _vec(preview_color, 3) * (1.0 - alpha)
    out = img.copy()
    put(out, str(out_layer).strip() or layer, out_rgb, img)
    if str(alpha_layer).strip():
        put(out, alpha_layer, alpha, img)
    return out


# ═══════════════════════════════════════════════════════════ Layer management
LAYER_OPS = ("rename", "copy", "delete", "keep")


def layer_edit(img, op="rename", spec="C=color"):
    """
    rename / copy: spec is "old=new old2=new2"; delete / keep: spec is layer names (space-separated).
    Renaming to an existing name overwrites it (consistent with Houdini); keep raises an error when nothing would remain.
    """
    if img is None:
        return CopImage()
    if op not in LAYER_OPS:
        raise ValueError(f"Op must be one of {LAYER_OPS}")
    out = img.copy()
    toks = [t for t in str(spec).split() if t]
    if op in ("rename", "copy"):
        for t in toks:
            if "=" not in t:
                raise ValueError(f"'{t}' must be written as old=new")
            old, new = t.split("=", 1)
            a = img.need(old)
            if op == "rename":
                out.remove(old)
            out.set(new, a)
    elif op == "delete":
        for t in toks:
            img.need(t)
            out.remove(t)
    else:
        for t in toks:
            img.need(t)
        for n in img.names:
            if n not in toks:
                out.remove(n)
        if not len(out):
            raise ValueError("No layers left after keep")
    return out


def layer_merge(a, b, layers="", prefix="", overwrite=True):
    """
    Merges b's layers into a. With different resolutions b is resampled to a (by the first input, like Composite);
    with different backends it's moved to a's backend. layers empty = all; prefix adds a prefix to merged layers;
    with overwrite off, a's layer is kept on name clashes.
    """
    if a is None:
        return b.copy() if b is not None else CopImage()
    if b is None:
        return a.copy()
    bb = conform(b, a)
    if bb.device != a.device:
        bb = bb.to_device(a.device if a.device != "numpy" else "numpy")
    out = a.copy()
    for n in names_of(bb, layers):
        name = f"{prefix}{n}"
        if name in out and not overwrite:
            continue
        out.set(name, bb.need(n))
    return out


COMBINE_LAYER_OPS = ("add", "average", "multiply", "min", "max", "over")


def layer_combine(imgs, layer=DEFAULT_LAYER, op="add", out_layer=""):
    """
    Houdini's Layer Merge (its docs page slug is average): composites **the same layer** of N inputs
    pixel by pixel into one -- add / average / multiply / min / max / over.

    Not the same thing as layer_merge above: that one **moves** B's layers into A (merging the set of
    layers), with no pixel arithmetic.

    · resolution and backend follow the first input (the first one connected); the rest are resampled to it
    · only 1-channel layers are broadcast automatically, same rule as Composite
    · over: **earlier inputs go over later ones** (docs: preceding over following), meaningful only for
      RGBA; when not 4 channels, per the docs "copy the last input's pixels"
    Space / Border / Filter / Clip by Data Window / Crop to Content depend on
    the data window and aren't implemented.
    """
    imgs = [im for im in imgs if im is not None]
    if not imgs:
        return CopImage()
    if op not in COMBINE_LAYER_OPS:
        raise ValueError(f"Operation must be one of {COMBINE_LAYER_OPS}")
    from .composite import porter_duff
    from .core import match_channels
    ref = imgs[0]
    name = str(layer).strip() or DEFAULT_LAYER
    xs = []
    for im in imgs:
        a = getn(conform(im, ref), name)
        xs.append(a)
    if op == "over":
        if all(a.shape[2] == 4 for a in xs):
            # stack from the last input forward: each time, put the next earlier input on top
            r = xs[-1]
            for a in xs[-2::-1]:
                r = porter_duff(r, a, "over", bk.NUMPY)
        else:
            r = xs[-1]
    else:
        r = xs[0]
        for a in xs[1:]:
            r, a = match_channels(r, a, bk.NUMPY)
            if op in ("add", "average"):
                r = r + a
            elif op == "multiply":
                r = r * a
            elif op == "min":
                r = np.minimum(r, a)
            else:
                r = np.maximum(r, a)
        if op == "average":
            r = r / len(xs)
    out = ref.copy()
    return put(out, str(out_layer).strip() or name, r, ref)


# ═══════════════════════════════════════════════════════ Mono (convert to single channel)
LUMA_SGI = (0.3086, 0.6094, 0.0820)
LUMA_NTSC = (0.299, 0.587, 0.114)
MONO_OPS = ("hdtv", "sgi", "ntsc", "average", "max", "min", "length", "hue",
            "saturation", "value", "red", "green", "blue", "alpha", "custom")


def _extend_rgb(a):
    """Houdini's channel expansion: Mono -> all three channels are it; UV -> the third is 0."""
    C = a.shape[2]
    if C >= 3:
        return a[..., :3]
    if C == 1:
        return np.repeat(a, 3, -1)
    return np.concatenate([a, np.zeros(a.shape[:2] + (1,))], -1)


def mono(img, layer=DEFAULT_LAYER, out_layer="lum", op="hdtv",
         weights="0.2126 0.7152 0.0722 0", normalize=False):
    """
    Houdini Mono's Operation. hdtv (Rec.709) goes through levels.luminance unchanged -- that was
    this node's only original behaviour and must stay bit-identical.

      sgi / ntsc      two other sets of luminance weights (the docs give the numbers)
      average/max/min over **all existing channels** of this layer (the docs only say "the channels";
                      RGBA's alpha counts too)
      length          existing channels taken as a vector, its length; single channel = absolute value (the docs' own words)
      hue/saturation/value  convert to HSV and take one (hue is 0-1, not degrees)
      red/green/blue/alpha  take one; missing channels are filled by the expansion rule (Mono -> gray,
                      UV's b = 0, alpha = 1)
      custom          Σ wᵢ·cᵢ (existing channels); normalize scales the **used** weights to sum to 1
    """
    if img is None:
        return CopImage()
    if op not in MONO_OPS:
        raise ValueError(f"Operation must be one of {MONO_OPS}")
    from .levels import luminance
    if op == "hdtv":
        return luminance(img, layer, out_layer)
    if op in ("sgi", "ntsc"):
        return luminance(img, layer, out_layer,
                         LUMA_SGI if op == "sgi" else LUMA_NTSC)
    a = getn(img, layer)
    C = a.shape[2]
    if op == "average":
        r = a.mean(-1)
    elif op == "max":
        r = a.max(-1)
    elif op == "min":
        r = a.min(-1)
    elif op == "length":
        r = np.sqrt((a * a).sum(-1))
    elif op in ("hue", "saturation", "value"):
        r = rgb_to_hsv(_extend_rgb(a))[
            ..., ("hue", "saturation", "value").index(op)]
    elif op == "alpha":
        r = a[..., 3] if C >= 4 else np.ones(a.shape[:2])
    elif op in ("red", "green", "blue"):
        r = _extend_rgb(a)[..., ("red", "green", "blue").index(op)]
    else:
        w = _vec(weights, 4)[:min(C, 4)]
        if normalize:
            t = float(w.sum())
            if abs(t) < 1e-12:
                raise ValueError("Normalize Weights: the used weights sum to 0")
            w = w / t
        r = (a[..., :len(w)] * w.reshape(1, 1, -1)).sum(-1)
    out = img.copy()
    return put(out, str(out_layer).strip() or "lum", r, img)


ALIGN_FITS = ("stretch", "fit", "fill", "none")


def align(img, ref, fit="stretch", border="black"):
    """
    Places img on ref's pixel grid (Align / Align Pixels). stretch fills; fit keeps
    proportions and fits inside (with margins); fill keeps proportions and covers (cropped); none doesn't scale, centered.
    """
    if img is None or ref is None:
        return CopImage() if img is None else img.copy()
    if fit not in ALIGN_FITS:
        raise ValueError(f"Fit must be one of {ALIGN_FITS}")
    from .transform import resample
    W, H = ref.xres, ref.yres
    w, h = img.xres, img.yres
    if fit == "stretch":
        sx, sy = w / W, h / H
    else:
        k = {"fit": max(w / W, h / H), "fill": min(w / W, h / H),
             "none": 1.0}[fit]
        sx = sy = k
    xp = img.backend
    J, I = np.meshgrid(np.arange(W, dtype=np.float64),
                       np.arange(H, dtype=np.float64))
    gx = (J + 0.5 - W / 2.0) * sx + w / 2.0 - 0.5
    gy = (I + 0.5 - H / 2.0) * sy + h / 2.0 - 0.5
    res = resample(img, xp.asarray(gx), xp.asarray(gy), border, "bilinear")
    return CopImage(W, H, res)


# ═══════════════════════════════════════════════════════════ Wrangle
_AT = re.compile(r"(?<![\w.])@(\w+)(?:\.([xyzwrgba]))?")
_CMAP = {"x": 0, "y": 1, "z": 2, "w": 3, "r": 0, "g": 1, "b": 2, "a": 3}


def wrangle(img, code="@C = @C * 2", seed=0, ch_params=None, chunk_rows=0):
    """
    Per-pixel VEX-flavored code, computed over the whole image at once (same function library as the geometry Wrangle).

      @C / @mask / @N ...   read/write layers, shape (pixel count, channel count); @C.x / @C.r take a component
      @u @v               0-1 coordinates of the pixel center (v up)
      @x @y               pixel coordinates; @res = (width, height); @ix pixel index
    Newly written layers are created automatically with the assigned shape. Like the geometry Wrangle it is **not executed once per pixel**:
    `if` can't be used; use where(cond, a, b).

    chunk_rows (pcg110): run the code on bands of this many rows at a time instead of the whole image, which bounds the
    memory of the temporaries (a 4096 x 1024 image with a dozen noise() calls needs gigabytes at once). Only for code
    that is truly per pixel: anything that looks at all pixels at once (counts, sums, the image maximum) would see one band. 0 = whole image (default).
    """
    if img is None:
        return CopImage()
    W, H = img.xres, img.yres
    step = int(chunk_rows) if int(chunk_rows or 0) > 0 else H
    bands = [(r, min(r + step, H)) for r in range(0, H, step)]
    py = None
    results = {}
    # on the numpy backend layers are stored as float32 anyway (put): assembling the bands in float32 halves the
    # peak of a big image (a 4096² surface writing six channels held 800 MB of float64 before the conversion)
    rdt = np.float32 if (img.backend if len(img) else bk.NUMPY) is bk.NUMPY else np.float64
    for r0, r1 in bands:
        py, part = _wrangle_band(img, code, seed, ch_params, r0, r1)
        for k, a in part.items():
            if k not in results:
                results[k] = np.zeros((H, W, a.shape[1]), rdt)
            elif results[k].shape[2] != a.shape[1]:
                raise RuntimeError(f"@{k} has {a.shape[1]} channels in one band and {results[k].shape[2]} in another")
            results[k][r0:r1] = a.reshape(r1 - r0, W, -1)
    out = img.copy()
    for k, a in results.items():
        put(out, k, a, img if len(img) else None)
    return out


def _wrangle_band(img, code, seed, ch_params, r0, r1):
    """Runs the wrangle on rows r0..r1; returns (translated code, {layer: (pixels, channels)} written or changed)."""
    from ..wrangle import _namespace, _hash01, _cols, ch_funcs
    W, H = img.xres, img.yres
    N = W * (r1 - r0)
    cache = {}
    dirty = set()

    def _rows(name):
        # only this band's rows go to float64: getn() converted the whole layer on every access, which on a 4096²
        # image run in bands was a 400 MB copy per layer per band (most of the time and the memory of the node)
        a = img.need(str(name).strip() or DEFAULT_LAYER)
        return np.asarray(bk.backend_of(a).to_numpy(a)[r0:r1], np.float64)

    class _L:
        def __getitem__(self, name):
            if name in cache:
                return _cols(cache[name])
            if name in img:
                a = _rows(name).reshape(N, -1).copy()
            else:
                a = np.zeros((N, 1))
            cache[name] = a
            return _cols(a)

        def __setitem__(self, name, value):
            v = np.asarray(value, np.float64)
            if v.ndim == 0:
                v = np.full((N, 1), float(v))
            elif v.ndim == 1:
                v = v.reshape(N, 1) if v.size == N else np.tile(v, (N, 1))
            elif v.ndim == 2 and v.shape[0] == 1 and N != 1:
                v = np.broadcast_to(v, (N, v.shape[1])).copy()   # @C = set(1,0,0)
            cache[name] = v
            dirty.add(name)

    J, I = np.meshgrid(np.arange(W, dtype=np.float64),
                       np.arange(r0, r1, dtype=np.float64))
    special = {"u": ((J + 0.5) / W).reshape(N), "v": ((I + 0.5) / H).reshape(N),
               "x": J.reshape(N), "y": I.reshape(N),
               "ix": np.arange(r0 * W, r0 * W + N, dtype=np.float64),
               "res": np.array([W, H], np.float64)}

    def sub(m):
        name, comp = m.group(1), m.group(2)
        if name in special and comp is None:
            return f"_S['{name}']"
        e = f'_L["{name}"]'
        if comp:
            e += f"[:, {_CMAP[comp]}]"
        return e

    py = _AT.sub(sub, str(code))
    ns = _namespace(int(seed))
    ns["_L"] = _L()
    ns["_S"] = special
    ns["rand"] = lambda x, _s=int(seed): _hash01(x, _s)
    ns.update(ch_funcs(ch_params))          # pcg104: ch("amp") reads custom parameters on the node
    from ..wrangle import check_code
    check_code(py, "COP Wrangle")
    try:
        exec(compile(py, "<cop wrangle>", "exec"), ns)
    except Exception as e:
        raise RuntimeError(f"COP Wrangle failed: {type(e).__name__}: {e}\n"
                           f"--- translated Python ---\n{py}") from e
    part = {}
    for k in cache:
        if k in dirty or k in img and not np.array_equal(
                cache[k], _rows(k).reshape(N, -1)):
            a = cache[k]
            if a.shape[0] != N:
                raise RuntimeError(f"@{k} has shape {a.shape}, not (pixel count, channels)")
            if a.shape[1] > 4:
                raise RuntimeError(f"@{k} has {a.shape[1]} channels; at most 4 allowed")
            part[k] = a
    return py, part


# ═══════════════════════════════════════════════════ Fill / vignette / random
def fill(img, layer=DEFAULT_LAYER, value="0 0 0", mask_layer="",
         invert_mask=False):
    """Fill the layer with a constant; if a mask is given, blend by the mask (soft edges)."""
    if img is None:
        return CopImage()
    a = getn(img, layer)
    v = np.broadcast_to(_vec(value, a.shape[2]).reshape(1, 1, -1), a.shape)
    if str(mask_layer).strip():
        m = np.clip(getn(img, mask_layer)[..., :1], 0, 1)
        if invert_mask:
            m = 1 - m
        r = a + (v - a) * m
    else:
        r = np.array(v)
    out = img.copy()
    return put(out, layer, r, img)


def vignette(img, layers="", amount=0.5, radius=0.75, softness=0.5,
             roundness=1.0, center="0.5 0.5"):
    """
    Vignette: multiplies by 1 - amount·smoothstep(radius-softness ... radius) of the distance to the center.
    roundness = 1 is a circle (by the short side), 0 is an ellipse following the frame. alpha is untouched.
    """
    if img is None:
        return CopImage()
    W, H = img.xres, img.yres
    cx, cy = _vec(center, 2)
    J, I = np.meshgrid((np.arange(W) + 0.5) / W, (np.arange(H) + 0.5) / H)
    asp = W / H
    kx = 1.0 + (asp - 1.0) * float(roundness) if asp >= 1 else 1.0
    ky = 1.0 + (1.0 / asp - 1.0) * float(roundness) if asp < 1 else 1.0
    d = np.hypot((J - cx) * 2 * kx, (I - cy) * 2 * ky) / math.sqrt(2)
    lo = float(radius) - float(softness)
    t = np.clip((d - lo) / max(float(softness), 1e-9), 0, 1)
    f = 1.0 - float(amount) * t * t * (3 - 2 * t)
    out = img.copy()
    for n in names_of(img, layers):
        a = getn(img, n)
        k = min(a.shape[2], 3)
        r = a.copy()
        r[..., :k] = a[..., :k] * f[..., None]
        put(out, n, r, img)
    return out


def _hash64(x, seed):
    """splitmix64, uint64 in, uint64 out."""
    with np.errstate(over="ignore"):
        z = np.asarray(x, np.uint64) + np.uint64(int(seed) & 0xFFFFFFFF) \
            * np.uint64(0x9E3779B97F4A7C15)
        z = z + np.uint64(0x9E3779B97F4A7C15)
        z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        z = z ^ (z >> np.uint64(31))
    return z


RANDOM_RANGES = ("shared", "min_max", "color_ramp", "specific_values")
RANDOM_MODELS = ("rgb", "hsv")


def _color_list(spec):
    """
    "r g b [w]; r g b [w]" -> (colors (K,3), weights (K,)). Separated by semicolons or newlines; the 4th number is
    Weight (omitted = 1); lower weights get picked less (the docs' own words).
    """
    cols, ws = [], []
    for part in str(spec).replace("\n", ";").split(";"):
        v = [float(x) for x in part.replace(",", " ").split()]
        if not v:
            continue
        if len(v) not in (3, 4):
            raise ValueError(f"Each Colors item is r g b or r g b weight, got "
                             f"'{part.strip()}'")
        cols.append(v[:3])
        ws.append(v[3] if len(v) == 4 else 1.0)
    if not cols:
        raise ValueError("Colors is empty. Syntax: 1 0 0; 0 1 0; 0 0 1")
    ws = np.asarray(ws, np.float64)
    if (ws < 0).any() or not ws.sum() > 0:
        raise ValueError("Weight can't be negative, nor all 0")
    return np.asarray(cols, np.float64), ws


def random_layer(img, mode="pixel", id_layer="id", channels=1, seed=0,
                 lo=0.0, hi=1.0, out_layer="random", xres=512, yres=512,
                 range_values="shared", color_model="rgb",
                 range_min="0 0 0", range_max="1 1 1",
                 color_ramp="0:0,0,0  1:1,1,1", color_ramp_mode="linear",
                 colors="1 0 0; 0 1 0; 0 0 1", zero_negative_ids=False):
    """
    Random Mono / Random RGB. pixel: one per pixel (white noise); id: same value for the same id
    (random colors / random brightness per piece of a segmentation image). Hash-based random, independent of resolution and batch, bit-
    reproducible. Without an input image, creates xres x yres (pixel mode only).

    range_values: shared is the original approach (all channels share one lo / hi pair, channel count follows
    channels). The other three are Houdini Random RGB's Range Values, and the output is always RGB
    (with channels = 4 there's an extra alpha, always 1, not random):
        min_max          each component its own [min, max]; with Color Model = hsv the three numbers are
                         hue (degrees) / saturation / value, drawn and then converted to RGB
        color_ramp       one uniform random number through a color ramp (the docs' own words)
        specific_values  drawn from the listed colors by Weight
    Zero Negative IDs: in id mode, pixels with id < 0 come out black (the docs' own words; id mode only).
    """
    if range_values not in RANDOM_RANGES:
        raise ValueError(f"Range Values must be one of {RANDOM_RANGES}")
    if color_model not in RANDOM_MODELS:
        raise ValueError(f"Color Model must be one of {RANDOM_MODELS}")
    if mode not in ("pixel", "id"):
        raise ValueError("Mode must be one of pixel / id")
    ch = int(channels)
    if ch not in (1, 3, 4):
        raise ValueError("Channels must be one of 1 / 3 / 4")
    if img is None or not len(img):
        if mode == "id":
            raise ValueError("id mode needs an image with an id layer connected")
        img = CopImage.blank(xres, yres, (0.0,), "_tmp")
        base = CopImage(img.xres, img.yres)
        like = None
    else:
        base = img.copy()
        like = img
    W, H = base.xres, base.yres
    if mode == "pixel":
        key = np.arange(W * H, dtype=np.uint64)
    else:
        idv = np.rint(getn(img, id_layer)[..., 0]).reshape(-1)
        key = idv.astype(np.int64).view(np.uint64)
    shared = range_values == "shared"
    cols = []
    for c in range(ch if shared else 3):
        z = _hash64(key * np.uint64(4) + np.uint64(c), int(seed))
        cols.append((z >> np.uint64(11)).astype(np.float64) / float(1 << 53))
    if shared:
        r = np.stack(cols, -1).reshape(H, W, ch)
        r = float(lo) + r * (float(hi) - float(lo))
    else:
        u = np.stack(cols, -1)
        if range_values == "min_max":
            a, b = _vec(range_min, 3), _vec(range_max, 3)
            r = a + u * (b - a)
            if color_model == "hsv":
                # Houdini's hue is in degrees; hsv_to_rgb wants one turn as 0-1
                r = hsv_to_rgb(r / np.asarray([360.0, 1.0, 1.0]))
        elif range_values == "color_ramp":
            from ..ramp import parse as _parse, apply as _apply
            pos, val = _parse(str(color_ramp), 3)
            r = _apply(u[:, 0], pos, val, color_ramp_mode)
        else:
            pal, wts = _color_list(colors)
            edge = np.cumsum(wts) / wts.sum()
            r = pal[np.minimum(np.searchsorted(edge, u[:, 0], side="right"),
                               len(pal) - 1)]
        if ch == 4:
            r = np.concatenate([r, np.ones((len(r), 1))], -1)
        r = r.reshape(H, W, -1)
    if zero_negative_ids and mode == "id":
        r = np.where((idv < 0).reshape(H, W, 1), 0.0, r)
    return put(base, out_layer, r, like)


# ═══════════════════════════════════════════════════════════ Depth conversion
DEPTH_KINDS = ("z_depth", "distance", "disparity", "normalized", "position")


def _ray_len(W, H, fov):
    """Per pixel: ray length per unit z, sqrt(1 + x² + y²) (pinhole, vertical FOV, square pixels)."""
    half = math.tan(math.radians(float(fov)) * 0.5)
    J, I = np.meshgrid(np.arange(W, dtype=np.float64),
                       np.arange(H, dtype=np.float64))
    x = ((J + 0.5) / W * 2 - 1) * half * (W / H)
    y = ((I + 0.5) / H * 2 - 1) * half
    return x, y, np.sqrt(1 + x * x + y * y)


def convert_depth(img, layer="depth", src="z_depth", dst="distance",
                  fov=45.0, near=0.0, far=0.0, out_layer="", mask_layer=""):
    """
    Converts between the different notions of depth. Renderers give camera z (along the view axis), ray tracing gives **distance**
    to the camera, depth ControlNet / MiDaS want inverse depth (disparity) -- they differ by a per-pixel
    factor √(1 + x² + y²), off by more than 20% at the frame edges (FOV 60°); getting it wrong
    raises no error, things at the edges just get pushed farther away.

      z_depth    camera-space z        distance  Euclidean distance to the camera
      disparity  1 / z                 normalized (z - near)/(far - near), 0 = near
      position   camera-space point (x, y, z) (output only)
    fov is the **vertical** FOV (the convention of Render Pass's camera). near / far left at 0 use
    the min / max within the mask. Outside the mask (or pixels with value <= 0) the output is 0.
    """
    if img is None:
        return CopImage()
    if src not in DEPTH_KINDS[:4] or dst not in DEPTH_KINDS:
        raise ValueError(f"From must be one of {DEPTH_KINDS[:4]}, To must be one of {DEPTH_KINDS}")
    d = getn(img, layer)[..., 0]
    W, H = img.xres, img.yres
    x, y, L = _ray_len(W, H, fov)
    if str(mask_layer).strip():
        m = getn(img, mask_layer)[..., 0] > 0.5
    else:
        m = np.isfinite(d) & (d > 0) if src != "normalized" else \
            np.isfinite(d)
    lo, hi = float(near), float(far)
    if src == "z_depth":
        z = d
    elif src == "distance":
        z = d / L
    elif src == "disparity":
        z = np.where(d > 0, 1.0 / np.where(d > 0, d, 1.0), 0.0)
    else:
        if not hi > lo:
            raise ValueError("normalized as input needs near < far")
        z = lo + d * (hi - lo)
    if dst == "z_depth":
        r = z[..., None]
    elif dst == "distance":
        r = (z * L)[..., None]
    elif dst == "disparity":
        r = np.where(z > 0, 1.0 / np.where(z > 0, z, 1.0), 0.0)[..., None]
    elif dst == "normalized":
        zz = z[m] if m.any() else z.ravel()
        a = lo if hi > lo else float(zz.min())
        b = hi if hi > lo else float(zz.max())
        r = ((z - a) / ((b - a) or 1e-12))[..., None]
    else:
        r = np.stack([x * z, y * z, z], -1)
    r = np.where(m[..., None], r, 0.0)
    out = img.copy()
    return put(out, str(out_layer).strip() or layer, r, img)
