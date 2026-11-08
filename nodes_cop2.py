"""
The second COP node file: the batch completing Copernicus (from pcg58).

How node files are split is described in the header of nodes_common.py. The end of nodes.py merges the mappings here into the main table,
so registration, thumbnail previews, the icon table and nodes.json all take the same path as before. Shared types and
widget helpers are imported from nodes_common (not from nodes -- that would be circular).

Which Houdini nodes each node maps to is written in the first line of its docstring, "Maps to:"; the full mapping table is in
tests/copernicus_map.py.
"""
from __future__ import annotations

import json

from .nodes_common import (COP, GEO, COPSEQ, CAT, _f, _i, _sec,  # noqa: F401
                           _compute)
from .geo import cop as _cop

_px = _cop.pixel
_ck = _cop.colorkey

_CATC = CAT + "/cop"
_S = ("STRING", {"default": ""})


def _s(default=""):
    return ("STRING", {"default": default})


def _b(default=False):
    return ("BOOLEAN", {"default": default})


def _node(cls):
    cls.FUNCTION = "run"
    cls.CATEGORY = _CATC
    if not hasattr(cls, "RETURN_TYPES"):
        cls.RETURN_TYPES = (COP,)
        cls.RETURN_NAMES = ("cop",)
    return cls


# ═══════════════════════════════════════════════════════ Batch A: per pixel
@_node
class PCG_COPColorCorrect:
    """
    Maps to: Color Correct / HSV Adjust / Bright / Contrast / Gamma.

    Exposure (×2^EV) → brightness (+) → contrast (about Pivot; in linear space 0.18 is mid-grey) →
    gamma (> 1 brightens, same direction as Levels) → saturation (interpolated towards Rec.709 luminance, luminance unchanged)
    → HSV (hue rotation, S×, V×). If Mask Layer is given it blends back by it. alpha is untouched.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,), "layers": _s(),
            "exposure": _f(0.0, -20, 20, 0.05),
            "brightness": _f(0.0, -10, 10, 0.01),
            "contrast": _f(1.0, 0, 10, 0.01),
            "pivot": _f(0.18, -10, 10, 0.01),
            "gamma": _f(1.0, 0.01, 10, 0.01),
            "saturation": _f(1.0, 0, 10, 0.01),
            "hue_shift": _sec("HSV", _f(0.0, -360, 360, 1.0)),
            "hsv_saturation": _sec("HSV", _f(1.0, 0, 10, 0.01)),
            "hsv_value": _sec("HSV", _f(1.0, 0, 10, 0.01)),
            "mask_layer": _s(),
        }}

    def run(self, cop, layers, exposure, brightness, contrast, pivot, gamma,
            saturation, hue_shift, hsv_saturation, hsv_value, mask_layer):
        return (_px.color_correct(cop, layers, exposure, brightness,
                                  contrast, pivot, gamma, saturation,
                                  hue_shift, hsv_saturation, hsv_value,
                                  mask_layer),)


@_node
class PCG_COPInvert:
    """Maps to: Invert. x → Pivot − x; alpha (channel 4) is not inverted by default."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "pivot": _f(1.0, -1e6, 1e6, 0.01),
                             "invert_alpha": _b()}}

    def run(self, cop, layers, pivot, invert_alpha):
        return (_px.invert(cop, layers, pivot, invert_alpha),)


@_node
class PCG_COPClamp:
    """Maps to: Clamp. Clamps values into [Min, Max]."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "min": _f(0.0), "max": _f(1.0)}}

    def run(self, cop, layers, min, max):   # noqa: A002
        return (_px.clamp(cop, layers, min, max),)


@_node
class PCG_COPChannelConvert:
    """
    Maps to: Mono to RGB / Mono to RGBA / RGB to RGBA / RGBA to RGB / RGB to UV /
    RGBA to UV / UV to RGB / UV to RGBA (the Mono direction is COP Luminance).

    Errors when there aren't enough channels instead of silently padding zeros -- otherwise a miswiring like "converting RGB as UV"
    propagates all the way down. Added channels: alpha gets Alpha, the rest get Fill.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("C"),
                             "mode": (list(_px.CONVERSIONS),),
                             "out_layer": _s(), "alpha": _f(1.0),
                             "fill": _f(0.0)}}

    def run(self, cop, layer, mode, out_layer, alpha, fill):
        return (_px.channel_convert(cop, layer, mode, out_layer, alpha,
                                    fill),)


@_node
class PCG_COPChannelSplit:
    """Maps to: Channel Split. Splits one layer into one layer per channel, layer name = name.suffix (C.r, C.g …)."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("C"),
                             "suffixes": _s("r g b a"),
                             "keep_layers": _b(True)}}

    def run(self, cop, layer, suffixes, keep_layers):
        return (_px.channel_split(cop, layer, suffixes, keep_layers),)


@_node
class PCG_COPChannelJoin:
    """Maps to: Channel Join. Concatenates all channels of several layers in order into one layer (at most 4 channels)."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s("C"),
                             "out_layer": _s("joined")}}

    def run(self, cop, layers, out_layer):
        return (_px.channel_join(cop, layers, out_layer),)


@_node
class PCG_COPSwizzle:
    """
    Maps to: Channel Swap / Channel Extract. Each character of Pattern is one output channel:
    r g b a / x y z w / u v take the corresponding channel, 0 / 1 are constants. "bgr" swaps channels, "a" extracts
    alpha, "rrr1" turns grey into RGBA.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("C"),
                             "pattern": _s("bgr"), "out_layer": _s()}}

    def run(self, cop, layer, pattern, out_layer):
        return (_px.swizzle(cop, layer, pattern, out_layer),)


@_node
class PCG_COPVectorMath:
    """
    Maps to: Dot Product / Cross Product (plus length / normalize / arithmetic / min / max
    / distance / reflect / lerp). B takes a layer name or a constant ("0 0 1").
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "a": _s("N"), "b": _s("0 0 1"),
                             "op": (list(_px.VEC_OPS),),
                             "out_layer": _s("out"),
                             "t": _f(0.5, -1e6, 1e6, 0.01)}}

    def run(self, cop, a, b, op, out_layer, t):
        return (_px.vector_math(cop, a, b, op, out_layer, t),)


@_node
class PCG_COPVectorTransform:
    """
    Maps to: Vector Transform / Vector Transform 2D / Space Transform. What is transformed is
    a **vector layer** (normals, velocity, direction), not the image itself. tangent ↔ world builds the TBN from Normal
    Layer (with an empty Tangent Layer, T = +x projected onto the tangent plane, same direction as Height to Normal's
    +u).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("N"),
                             "mode": (list(_px.XFORM_MODES),),
                             "angle": _f(0.0, -3600, 3600, 1.0),
                             "rotate": _s("0 0 0"), "scale": _s("1 1 1"),
                             "matrix": _s("1 0 0 0 1 0 0 0 1"),
                             "normal_layer": _s("N"),
                             "tangent_layer": _s(), "out_layer": _s()}}

    def run(self, cop, layer, mode, angle, rotate, scale, matrix,
            normal_layer, tangent_layer, out_layer):
        return (_px.vector_transform(cop, layer, mode, angle, rotate, scale,
                                     matrix, normal_layer, tangent_layer,
                                     out_layer),)


@_node
class PCG_COPFunction:
    """
    Maps to: Function. Per-pixel unary functions (abs / pow / exp / log / sin / frac / step /
    smoothstep / mod / sigmoid …). Negative inputs to log and sqrt give 0, 0 into 1/x gives 0 --
    no nan is produced (once downstream blurs smear a nan, the whole image turns black and the source can't be found).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "function": (list(_px.FUNCTIONS),),
                             "a": _f(1.0), "b": _f(1.0)}}

    def run(self, cop, layers, function, a, b):
        return (_px.function(cop, layers, function, a, b),)


@_node
class PCG_COPLogic:
    """
    Maps to: Logic. Comparisons / booleans, outputting a 0/1 mask. B takes a layer name or a constant; and / or / xor /
    not treat > 0.5 as true; equal has a tolerance (floating-point equality almost never holds).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "a": _s("C"), "b": _s("0.5"),
                             "op": (list(_px.LOGIC_OPS),),
                             "tolerance": _f(1e-6, 0, 1e6, 1e-6),
                             "out_layer": _s("mask")}}

    def run(self, cop, a, b, op, tolerance, out_layer):
        return (_px.logic(cop, a, b, op, tolerance, out_layer),)


@_node
class PCG_COPMaskCombine:
    """
    Maps to: Mask Combine. Combines several masks into one: union (max) / intersect (min) / add /
    multiply / subtract (first minus the rest) / difference / screen (soft union 1 − Π(1−m))
    / average.

    layer_stack (pcg100) is how Houdini's node actually works: starting from Starting Value,
    Mask Layers holds one layer per line, each with its own Blend Mode and Mask amount, stacked top to bottom. In Houdini
    it's a multiparm; here it's multi-line text (`layer[.channel] mode amount`, a leading # disables
    that layer). Post-processing does Fold / Complement / Clamp Minimum / Clamp Maximum;
    the per-layer Channel Mix / Light Direction / Blur / Layer Remap and the post-processing
    Remap / Amplitude / Center / Contrast / Bias / Gain / Gamma are not done (the docs give no
    formulas; if needed, add a COP node before or after).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s("C"),
                             "op": (list(_px.COMBINE_OPS),),
                             "out_layer": _s("mask"), "clamp": _b(True),
                             # ── pcg100, defaults = the original behaviour ──
                             "stack": ("STRING", {"default": "mask add 1",
                                                  "multiline": True}),
                             "starting_value": _f(0.0, -1e6, 1e6, 0.01),
                             "fold": _b(False), "complement": _b(False),
                             "use_clamp_min": _b(False),
                             "clamp_min": _f(0.0, -1e6, 1e6, 0.01),
                             "use_clamp_max": _b(False),
                             "clamp_max": _f(1.0, -1e6, 1e6, 0.01)}}

    def run(self, cop, layers, op, out_layer, clamp, stack="mask add 1",
            starting_value=0.0, fold=False, complement=False,
            use_clamp_min=False, clamp_min=0.0, use_clamp_max=False,
            clamp_max=1.0):
        return (_px.mask_combine(cop, layers, op, out_layer, clamp, stack,
                                 starting_value, fold, complement,
                                 clamp_min if use_clamp_min else None,
                                 clamp_max if use_clamp_max else None),)


@_node
class PCG_COPPremultiply:
    """Maps to: Premultiply. RGB × alpha or divided back; where alpha = 0 unpremultiply gives 0, not nan."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("C"),
                             "mode": (["premultiply", "unpremultiply"],),
                             "alpha_layer": _s()}}

    def run(self, cop, layer, mode, alpha_layer):
        return (_px.premultiply(cop, layer, mode, alpha_layer),)


@_node
class PCG_COPIllegalPixel:
    """
    Maps to: Illegal Pixel. Illegal Pixels = replace (default, our original approach): nan /
    ±inf replaced by a given value (optionally clamping negatives away). The other four modes are Houdini's menu: blend fills with the average of surrounding good
    pixels, zero clears, highlight paints Highlight Color, isolate keeps only bad pixels
    (clearing the rest); bad pixels are decided by Detect (NaN / Inf / both / Custom rule), judged per **pixel**
    (any channel hit). The report says how many of each.
    """
    RETURN_TYPES = (COP, "STRING")
    RETURN_NAMES = ("cop", "report")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "nan": _f(0.0), "pos_inf": _f(1.0),
                             "neg_inf": _f(0.0),
                             "clamp_negative": _b(False),
                             # pcg100: Houdini's Illegal Pixels / Detect / Rule
                             "mode": (["replace"] + list(_ck.ILLEGAL_MODES),),
                             "highlight_color": _s("1 0 0"),
                             "detect": (list(_ck.ILLEGAL_DETECT),
                                        {"default": "nan_inf"}),
                             "rule": (list(_ck.ILLEGAL_RULES),),
                             "value": _f(0.0)}}

    def run(self, cop, layers, nan, pos_inf, neg_inf, clamp_negative,
            mode="replace", highlight_color="1 0 0", detect="nan_inf",
            rule="less", value=0.0):
        out, rep = _px.illegal_pixel(cop, layers, nan, pos_inf, neg_inf,
                                     clamp_negative, mode, highlight_color,
                                     detect, rule, value)
        return (out, json.dumps(rep, ensure_ascii=False))


@_node
class PCG_COPToneMap:
    """
    Maps to: Tone Map. HDR → 0~1: reinhard / reinhard_extended (White maps to 1) /
    aces (Narkowicz fit) / hable (Uncharted 2). Only turn on Encode sRGB for images meant to be viewed directly;
    leave it off for images that still go into compositing.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "op": (list(_px.TONEMAPS), {"default": "aces"}),
                             "exposure": _f(0.0, -20, 20, 0.05),
                             "white": _f(4.0, 0.01, 1e4, 0.1),
                             "encode_srgb": _b(False)}}

    def run(self, cop, layers, op, exposure, white, encode_srgb):
        return (_px.tone_map(cop, layers, op, exposure, white,
                             encode_srgb),)


@_node
class PCG_COPChromaKey:
    """
    Maps to: Chroma Key (for despill alone use COP Despill). Method:

      distance            our own (default): measures distance to the key colour in the YCbCr chroma plane
                          (ignoring luminance, so shadows and highlights on a green screen are keyed out together), Tolerance / Softness
      chromakey           Houdini's legacy Chromakey: one range each for hue / saturation / luminance,
                          with Rolloff extending soft edges on both sides
      channel_separation  Houdini's Channel Separation: the screen colour's main channel minus the max of the other
                          two, then through Threshold / Width

    Despill Amount is our extension (Houdini's Chroma Key doesn't have it): subtracts the part of the key colour's main channel exceeding the average of the other
    two channels. The matte goes to Alpha Layer (1 = kept).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("C"),
                             "key_color": _s("0 1 0"),
                             "tolerance": _f(0.15, 0, 10, 0.005),
                             "softness": _f(0.1, 0, 10, 0.005),
                             "despill": _f(1.0, 0, 2, 0.01),
                             "out_layer": _s(), "alpha_layer": _s("alpha"),
                             "premultiply": _b(False),
                             # pcg100: Houdini's Method / Key / Rolloff / Visualize
                             "method": (["distance"] + list(_ck.KEY_METHODS),),
                             "invert": _b(False),
                             "hue_min": _f(90.0, -360, 720, 1.0),
                             "hue_max": _f(150.0, -360, 720, 1.0),
                             "sat_min": _f(0.3, 0, 1, 0.01),
                             "sat_max": _f(1.0, 0, 1, 0.01),
                             "lum_min": _f(0.0, 0, 1e6, 0.01),
                             "lum_max": _f(1.0, 0, 1e6, 0.01),
                             "threshold": _f(0.5, -10, 10, 0.01),
                             "width": _f(0.0, 0, 10, 0.01),
                             "hue_rolloff": _f(10.0, 0, 180, 1.0),
                             "sat_rolloff": _f(0.1, 0, 1, 0.01),
                             "lum_rolloff": _f(0.1, 0, 1e6, 0.01),
                             "interpolation": (list(_ck.ROLLOFFS),),
                             # Can't be called preview: the COP node's thumbnail widget is named preview (pcg_cop_preview.js),
                             # and the same name stops the frontend from recognising the panel (found by e2e tests)
                             "show_matte": _b(False),
                             "preview_color": _s("1 0 1")}}

    def run(self, cop, layer, key_color, tolerance, softness, despill,
            out_layer, alpha_layer, premultiply, method="distance",
            invert=False, hue_min=90.0, hue_max=150.0, sat_min=0.3,
            sat_max=1.0, lum_min=0.0, lum_max=1.0, threshold=0.5, width=0.0,
            hue_rolloff=10.0, sat_rolloff=0.1, lum_rolloff=0.1,
            interpolation="linear", show_matte=False, preview_color="1 0 1"):
        return (_px.chroma_key(cop, layer, key_color, tolerance, softness,
                               despill, out_layer, alpha_layer, premultiply,
                               method, invert, (hue_min, hue_max),
                               (sat_min, sat_max), (lum_min, lum_max),
                               (hue_rolloff, sat_rolloff, lum_rolloff),
                               interpolation, threshold, width, show_matte,
                               preview_color),)


@_node
class PCG_COPDespill:
    """
    Maps to: Despill. Removes spill only, no alpha output (for a matte use COP Chroma Key). The largest channel of Spill Color
    is pushed below a limit mixed from the other two channels by Bias; Luminance adds the removed
    brightness back (1 = as bright as the original). The removed colour is output as a separate Spill Layer.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("C"),
                             "mask": _f(1.0, 0, 1, 0.01),
                             "spill_color": _s("0 1 0"),
                             "bias": _f(0.5, 0, 1, 0.01),
                             "luminance": _f(0.0, 0, 10, 0.01),
                             "bias_layer": _s(), "mask_layer": _s(),
                             "out_layer": _s(), "spill_layer": _s("spill")}}

    def run(self, cop, layer, mask, spill_color, bias, luminance, bias_layer,
            mask_layer, out_layer, spill_layer):
        return (_ck.despill(cop, layer, spill_color, bias, luminance, mask,
                            bias_layer, mask_layer, out_layer, spill_layer),)


@_node
class PCG_COPLayerEdit:
    """
    Maps to: Rename (plus layer management: copy / delete / keep only). rename / copy take
    "old=new old2=new2", delete / keep take layer names.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "op": (list(_px.LAYER_OPS),),
                             "spec": _s("C=color")}}

    def run(self, cop, op, spec):
        return (_px.layer_edit(cop, op, spec),)


@_node
class PCG_COPLayerMerge:
    """
    Maps to: Layer Merge. Merges B's layers into A: when resolutions differ B is resampled to A, when backends differ it is
    moved to A's backend. Prefix adds a prefix to merged layers; with Overwrite off, A's layer wins on name clashes.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"a": (COP,), "b": (COP,), "layers": _s(),
                             "prefix": _s(), "overwrite": _b(True)}}

    def run(self, a, b, layers, prefix, overwrite):
        return (_px.layer_merge(a, b, layers, prefix, overwrite),)


@_node
class PCG_COPLayerCombine:
    """
    Maps to: Layer Merge (Houdini docs page cop/average). Combines **the same layer** of several connected images
    per pixel into one: Add / Average / Multiply / Min / Max / Over.

    Not the same as COP Layer Merge (PCG) -- that one moves B's layers into A (merging layer sets,
    no pixel arithmetic) and is our own node; the one Houdini calls Layer Merge is this.

    Resolution follows the first connected input; the rest are resampled to it; 1 channel is auto-broadcast. Over puts earlier inputs
    over later ones and only makes sense for RGBA (when not RGBA, copies the last input as the docs say). Houdini's
    input count is unlimited; here there are 6 fixed inputs, chain two if not enough. Space / Border / Filter /
    Clip by Data Window / Crop to Content depend on the data window; not done.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"layer": _s("C"),
                             "operation": (list(_px.COMBINE_LAYER_OPS),),
                             "out_layer": _s()},
                "optional": {f"source{i}": (COP,) for i in range(1, 7)}}

    def run(self, layer, operation, out_layer, source1=None, source2=None,
            source3=None, source4=None, source5=None, source6=None):
        return (_px.layer_combine([source1, source2, source3, source4,
                                   source5, source6], layer, operation,
                                  out_layer),)


@_node
class PCG_COPAlign:
    """
    Maps to: Align / Align Pixels. Places cop onto reference's pixel grid: stretch
    fills / fit keeps aspect inside / fill keeps aspect covering / none centres without scaling.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "reference": (COP,),
                             "fit": (list(_px.ALIGN_FITS),),
                             "border": (list(_cop.filters.BORDERS),
                                        {"default": "black"})}}

    def run(self, cop, reference, fit, border):
        return (_px.align(cop, reference, fit, border),)


@_node
class PCG_COPWrangle:
    """
    Maps to: Wrangle / Python Snippet. VEX-flavoured per-pixel code, computing the whole image at once (same function library as the geometry
    Wrangle): @C, @mask, @N.x read/write layers, @u @v are 0~1 coordinates
    (v up), @x @y pixel coordinates, @res the resolution. **It does not run once per pixel**: for if use
    where(cond, a, b). Example: `@mask = smoothstep(0.3, 0.6, @C.x)`.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,),
                             "code": ("STRING", {"multiline": True,
                                                 "default": "@C = @C * 2"}),
                             "rand_seed": _i(0, 0, 2 ** 31 - 1),
                             # pcg104 addition: ch("amp") reads custom parameters on the node (the frontend writes this JSON)
                             "ch_params": ("STRING", {"default": "{}", "ch_store": True}),
                             # pcg110 addition: bound memory by running on bands of rows (0 = whole image, as before)
                             "rows_per_pass": _i(0, 0, 65536)}}

    def run(self, cop, code, rand_seed, ch_params="{}", rows_per_pass=0):
        import json
        try:
            chd = json.loads(ch_params) if str(ch_params).strip() else {}
        except ValueError:
            chd = {}
        return (_px.wrangle(cop, code, rand_seed, chd, rows_per_pass),)


@_node
class PCG_COPFill:
    """Maps to: Fill. Fills a layer with a constant; with a mask, soft-blends by the mask."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("C"),
                             "value": _s("0 0 0"), "mask_layer": _s(),
                             "invert_mask": _b(False)}}

    def run(self, cop, layer, value, mask_layer, invert_mask):
        return (_px.fill(cop, layer, value, mask_layer, invert_mask),)


@_node
class PCG_COPVignette:
    """Maps to: Vignette. Darkens by distance to the centre; Roundness 1 = a circle, 0 = an ellipse following the frame."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "amount": _f(0.5, -10, 10, 0.01),
                             "radius": _f(0.75, 0, 10, 0.01),
                             "softness": _f(0.5, 0, 10, 0.01),
                             "roundness": _f(1.0, 0, 1, 0.01),
                             "center": _s("0.5 0.5")}}

    def run(self, cop, layers, amount, radius, softness, roundness, center):
        return (_px.vignette(cop, layers, amount, radius, softness,
                             roundness, center),)


@_node
class PCG_COPRandom:
    """
    Maps to: Random Mono / Random RGB. pixel = one per pixel (white noise); id = the same value for the same
    id (random colour per piece of a segmentation image). Hash-based random, reproducible bit for bit. Without an input image a new one is created at
    Resolution (pixel only).

    Range Values: shared is the original Min / Max pair (shared by all channels); min_max /
    color_ramp / specific_values are Houdini Random RGB's three modes, outputting fixed RGB
    (alpha always 1 when Channels = 4).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"mode": (["pixel", "id"],),
                             "id_layer": _s("id"),
                             "channels": (["1", "3", "4"],),
                             "rand_seed": _i(0, 0, 2 ** 31 - 1),
                             "min": _f(0.0), "max": _f(1.0),
                             "out_layer": _s("random"),
                             "resolution_x": _i(512, 1, 16384),
                             "resolution_y": _i(512, 1, 16384),
                             # pcg100: the Range section of Houdini's Random RGB
                             "range_values": (list(_px.RANDOM_RANGES),),
                             "color_model": (list(_px.RANDOM_MODELS),),
                             "range_min": _s("0 0 0"),
                             "range_max": _s("1 1 1"),
                             "color_ramp": _s("0:0,0,0  1:1,1,1"),
                             "color_ramp_mode": (["linear", "smooth",
                                                  "constant"],),
                             "colors": _s("1 0 0; 0 1 0; 0 0 1"),
                             "zero_negative_ids": _b(False)},
                "optional": {"cop": (COP,)}}

    def run(self, mode, id_layer, channels, rand_seed, min, max,   # noqa: A002
            out_layer, resolution_x, resolution_y, range_values="shared",
            color_model="rgb", range_min="0 0 0", range_max="1 1 1",
            color_ramp="0:0,0,0  1:1,1,1", color_ramp_mode="linear",
            colors="1 0 0; 0 1 0; 0 0 1", zero_negative_ids=False, cop=None):
        return (_px.random_layer(cop, mode, id_layer, int(channels),
                                 rand_seed, min, max, out_layer,
                                 resolution_x, resolution_y, range_values,
                                 color_model, range_min, range_max,
                                 color_ramp, color_ramp_mode, colors,
                                 zero_negative_ids),)


@_node
class PCG_COPConvertDepth:
    """
    Maps to: Convert Depth. Converts between camera z / distance to camera / inverse depth (disparity) / normalised /
    camera-space position. z and distance differ by a per-pixel factor √(1+x²+y²); at FOV 60° the frame
    edges differ by over 20% -- mixing them up raises no error, things at the edges are just pushed farther. FOV is vertical
    (the Render Pass convention).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("depth"),
                             "from_kind": (list(_px.DEPTH_KINDS[:4]),),
                             "to_kind": (list(_px.DEPTH_KINDS),
                                         {"default": "distance"}),
                             "fov": _f(45.0, 1, 179, 0.5),
                             "near": _f(0.0, 0, 1e9, 0.01),
                             "far": _f(0.0, 0, 1e9, 0.01),
                             "out_layer": _s(), "mask_layer": _s()}}

    def run(self, cop, layer, from_kind, to_kind, fov, near, far, out_layer,
            mask_layer):
        return (_px.convert_depth(cop, layer, from_kind, to_kind, fov, near,
                                  far, out_layer, mask_layer),)


# ─────────────────────────────────── pcg100: a few with Houdini semantics (c2_color_key)
# Nodes the audit found "same name, different meaning": the original node is unchanged, and Houdini's semantics each get a new node.
_LUM_DEFAULT = {"default": "hdtv"}


@_node
class PCG_COPEqualize:
    """
    Maps to: Equalize. Measures the min / max / mean of "luminance" (Luminance Type) and shifts or scales the selected
    channels together onto the target: stretch to Black / White, move min to Black, move max
    to White, move mean to Target, scale max luminance to White. **Not** histogram equalisation
    (that's COP Histogram).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,), "layer": _s("C"),
            "mask": _f(1.0, 0, 1, 0.01),
            "red": _b(True), "green": _b(True), "blue": _b(True),
            "alpha": _b(True),
            "equalize_by": (list(_ck.EQ_BY),),
            "fit_method": (list(_ck.EQ_FIT),),
            "luminance_type": (list(_ck.LUM_TYPES), _LUM_DEFAULT),
            "black": _f(0.0), "white": _f(1.0),
            "target_average": _f(0.5),
            "active_layer": _s(), "mask_layer": _s(), "out_layer": _s()}}

    def run(self, cop, layer, mask, red, green, blue, alpha, equalize_by,
            fit_method, luminance_type, black, white, target_average,
            active_layer, mask_layer, out_layer):
        return (_ck.equalize(cop, layer, equalize_by, fit_method,
                             luminance_type, black, white, target_average,
                             red, green, blue, alpha, mask, mask_layer,
                             active_layer, out_layer),)


@_node
class PCG_COPHistogramPlot:
    """
    Maps to: Histogram. **Draws** a layer's histogram as an image (colour bands / one grey band per channel / bar chart);
    the second output counts holds the raw counts: width = Buckets, height 5, rows R, G, B, A bottom up,
    and column 0 of the top row is the number of pixels counted. To equalise / match histograms use COP Histogram.
    """
    RETURN_TYPES = (COP, COP)
    RETURN_NAMES = ("cop", "counts")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,), "layer": _s("C"),
            "mode": (list(_ck.HIST_PLOT_MODES),),
            "buckets": _i(256, 1, 65536),
            "min": _f(0.0), "max": _f(1.0),
            "outside": (list(_ck.HIST_OUTSIDE),),
            "scale": _f(10.0, 0, 1e6, 0.1),
            "red": _b(True), "green": _b(True), "blue": _b(True),
            "alpha": _b(True),
            "active_layer": _s(), "out_layer": _s("histogram")}}

    def run(self, cop, layer, mode, buckets, min, max, outside,  # noqa: A002
            scale, red, green, blue, alpha, active_layer, out_layer):
        return _ck.histogram_plot(cop, layer, mode, buckets, min, max,
                                  outside, scale, red, green, blue, alpha,
                                  active_layer, out_layer)


@_node
class PCG_COPCompareMask:
    """
    Maps to: Compare. Compares A and B per pixel (empty Layer B compares against Comparison Value), outputting a 0~1
    mask; within Tolerance it transitions softly by Falloff. To measure how different two images are (SSIM / PSNR) use
    COP Compare.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,), "layer_a": _s("C"), "layer_b": _s(),
            "value": _f(0.0),
            "tolerance": _f(0.0, 0, 1e6, 0.001),
            "true_if": (list(_ck.CMP_OPS),),
            "components": (list(_ck.CMP_COMPONENTS),),
            "falloff": (list(_ck.CMP_FALLOFF),),
            "tolerance_layer": _s(), "out_layer": _s("mask")}}

    def run(self, cop, layer_a, layer_b, value, tolerance, true_if,
            components, falloff, tolerance_layer, out_layer):
        return (_ck.compare_mask(cop, layer_a, layer_b, value, true_if,
                                 components, tolerance, tolerance_layer,
                                 falloff, out_layer),)


@_node
class PCG_COPMonoToRGB:
    """
    Maps to: Mono to RGB. Passes single-channel values through a ramp to RGB (false colour). To just copy one channel into
    three use COP Channel Convert. If Ramp Layer is given, colours are taken horizontally along the middle row of that layer.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,), "layer": _s("C"),
            "compute_range": _b(False),
            "in_min": _f(0.0), "in_max": _f(1.0),
            "out_min": _f(0.0), "out_max": _f(1.0),
            "scale_by_value": _b(False),
            "outside": (list(_ck.MONO_OUTSIDE),),
            "ramp": _s("0:0,0,0  1:1,1,1"),
            "ramp_mode": (["linear", "smooth", "constant"],),
            "ramp_layer": _s(), "out_layer": _s()}}

    def run(self, cop, layer, compute_range, in_min, in_max, out_min,
            out_max, scale_by_value, outside, ramp, ramp_mode, ramp_layer,
            out_layer):
        return (_ck.mono_to_rgb(cop, layer, compute_range, in_min, in_max,
                                out_min, out_max, scale_by_value, outside,
                                ramp, ramp_mode, ramp_layer, out_layer),)


@_node
class PCG_COPMonoToHeightField:
    """
    Maps to: Mono to HeightField. Height = value × Height Scale + Height Offset, written to the
    height layer (our layers have no Houdini Type Info; we rely on a layer-name convention).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,), "layer": _s("C"),
            "height_scale": _f(1.0), "height_offset": _f(0.0),
            "out_layer": _s("height")}}

    def run(self, cop, layer, height_scale, height_offset, out_layer):
        return (_ck.mono_to_height(cop, layer, height_scale, height_offset,
                                   out_layer),)


# ═══════════════════════════════════════════════════════ Batch B: filters / effects / distortion
_fx = _cop.fx
_BORDER = list(_cop.filters.BORDERS)


def _bd(default="clamp"):
    return (sorted(_BORDER, key=lambda b: b != default),)


@_node
class PCG_COPDefocus:
    """
    Maps to: Defocus / Bokeh. Convolves with a shaped kernel (disc / polygonal aperture / square) to produce bokeh.

    With Depth Layer connected, layered by circle of confusion: |depth − Focus| ≤ Focus Range is sharp, then beyond that
    it grows to Radius within the Falloff distance (Levels steps, interpolating between adjacent steps). Highlight Gain
    amplifies highlights brighter than the threshold first, then compresses them back with the exact inverse after blurring, so the bokeh comes out as
    distinct aperture shapes.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,), "layers": _s(),
            "radius": _f(6.0, 0, 256, 0.1),
            "shape": (list(_fx.BLUR_SHAPES),),
            "blades": _i(6, 3, 16), "rotation": _f(0.0, -360, 360, 1.0),
            "depth_layer": _sec("Depth", _s()),
            "focus": _sec("Depth", _f(0.5, -1e6, 1e6, 0.01)),
            "focus_range": _sec("Depth", _f(0.1, 0, 1e6, 0.01)),
            "falloff": _sec("Depth", _f(0.2, 0, 1e6, 0.01)),
            "levels": _sec("Depth", _i(8, 2, 32)),
            "highlight_threshold": _sec("Highlights", _f(1.0, 0, 1e6, 0.01)),
            "highlight_gain": _sec("Highlights", _f(0.0, 0, 100, 0.1)),
            "border": _bd(),
        }}

    def run(self, cop, layers, radius, shape, blades, rotation, depth_layer,
            focus, focus_range, falloff, levels, highlight_threshold,
            highlight_gain, border):
        return (_fx.defocus(cop, layers, radius, shape, blades, rotation,
                            depth_layer, focus, focus_range, falloff, levels,
                            highlight_threshold, highlight_gain, border),)


@_node
class PCG_COPDirectionalBlur:
    """
    Maps to: Streak Blur (and motion blur). Averages samples along Angle (degrees, 0 = right, 90 = up).
    centered takes half on each side; streak drags to one side only. Samples 0 = one per pixel.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "length": _f(20.0, -4096, 4096, 0.5),
                             "angle": _f(0.0, -360, 360, 1.0),
                             "mode": (["centered", "streak"],),
                             "samples": _i(0, 0, 1024), "border": _bd(),
                             "compute": _compute()}}

    def run(self, cop, layers, length, angle, mode, samples, border,
            compute="auto"):
        return (_fx.directional_blur(cop, layers, length, angle, mode,
                                     samples, border, compute),)


@_node
class PCG_COPKuwahara:
    """Maps to: Kuwahara Filter. Takes the mean of the quadrant with the smallest variance: edge-preserving smoothing, painterly look."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "radius": _i(4, 1, 64)}}

    def run(self, cop, layers, radius):
        return (_fx.kuwahara(cop, layers, radius),)


@_node
class PCG_COPConvolve:
    """
    Maps to: Convolve 3x3 / Convolve Filter. Kernel takes n² numbers (n odd); **the first row written
    is the topmost row of the image**. Presets: box / gaussian / sharpen / edge / emboss /
    sobel. Kernels larger than 7×7 automatically use FFT.

    kernel_cop (pcg100) is Convolve Filter's second input: when connected, its
    Kernel Layer is used as the kernel (true convolution: convolving a single-pixel impulse gives the kernel image itself), and the Preset /
    Kernel string is no longer read. With Centered Kernel off, the origin is the kernel image's lower-left pixel. Border
    gains Mirror. Houdini's Padding toggle / value isn't done: we always pad by the kernel radius
    (equivalent to Padding on and large enough), so the wrap-around bleeding it has with Padding off never happens.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "preset": (list(_fx.CONV_PRESETS),),
                             "kernel": ("STRING", {"default": "0 0 0\n0 1 0\n0 0 0",
                                                   "multiline": True}),
                             "normalize": _b(False),
                             "border": (_bd()[0] + ["mirror"],),
                             "kernel_layer": _s("C"),
                             "centered": _b(True)},
                "optional": {"kernel_cop": (COP,)}}

    def run(self, cop, layers, preset, kernel, normalize, border,
            kernel_layer="C", centered=True, kernel_cop=None):
        return (_fx.convolve_layer(cop, layers, preset, kernel, normalize,
                                   border, kernel_cop, kernel_layer,
                                   centered),)


@_node
class PCG_COPDenoiseTV:
    """
    Maps to: Denoise TVD. Total variation (ROF) denoising, Chambolle's dual projection: removes noise, keeps
    step edges. Larger Weight is flatter; the mean is strictly conserved.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "weight": _f(0.1, 0, 100, 0.01),
                             "iterations": _i(50, 1, 5000),
                             "compute": _compute()}}

    def run(self, cop, layers, weight, iterations, compute="auto"):
        return (_fx.denoise_tv(cop, layers, weight, iterations, compute),)


@_node
class PCG_COPGlow:
    """
    Maps to: Glow / Star Glow. Takes the part brighter than the threshold: glow = Gaussians at three scales summed,
    star = streaks along Rays directions; added back onto the original, alpha untouched.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "mode": (["glow", "star"],),
                             "threshold": _f(0.8, 0, 1e6, 0.01),
                             "intensity": _f(1.0, 0, 1e3, 0.01),
                             "radius": _f(12.0, 0, 1024, 0.5),
                             "rays": _sec("Star", _i(4, 1, 32)),
                             "ray_length": _sec("Star", _f(40.0, 0, 4096, 1)),
                             "angle": _sec("Star", _f(45.0, -360, 360, 1)),
                             "border": _bd()}}

    def run(self, cop, layers, mode, threshold, intensity, radius, rays,
            ray_length, angle, border):
        return (_fx.glow(cop, layers, mode, threshold, intensity, radius,
                         rays, ray_length, angle, border),)


@_node
class PCG_COPDropShadow:
    """
    Maps to: Drop Shadow. Takes alpha (channel 4 or Alpha Layer), offsets, blurs and colours it,
    placing it under the original, outputting RGBA. Offset is in pixels, +y up. **Errors without alpha**
    -- no guessing.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("C"),
                             "alpha_layer": _s(),
                             "offset": _s("8 -8"),
                             "blur": _f(6.0, 0, 512, 0.1),
                             "color": _s("0 0 0"),
                             "opacity": _f(0.7, 0, 1, 0.01)}}

    def run(self, cop, layer, alpha_layer, offset, blur, color, opacity):
        return (_fx.drop_shadow(cop, layer, alpha_layer, offset, blur, color,
                                opacity),)


@_node
class PCG_COPFeather:
    """
    Maps to: Feather. smoothstep transition by exact distance to the border (Width pixels wide): thin strips
    don't fade as a whole, sharp corners aren't eaten round -- the difference from Gaussian-blurring the mask.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("mask"),
                             "width": _f(8.0, 0, 1024, 0.5),
                             "direction": (["both", "inward", "outward"],),
                             "out_layer": _s()}}

    def run(self, cop, layer, width, direction, out_layer):
        return (_fx.feather(cop, layer, width, direction, out_layer),)


_fsim = _cop.filtersim


@_node
class PCG_COPFeatherSlope:
    """
    Maps to: Feather (Houdini semantics, pcg100 c7). **Limits the maximum rate of change between neighbouring pixels**:
    with High to Low bright pixels stay put and surrounding dark pixels are raised to satisfy the slope (the reverse pushes bright pixels down). The slope is given by
    Feather Method (Distance for Unit Change / Change per Distance, image units);
    island shape is set by the scan directions of Feather Direction (Diamond / Square / Octagon /
    Custom / Circle). The old COP Feather is "smoothstep by distance to the mask border", not
    the same thing, kept unchanged. Details and our own conventions in filtersim.feather_slope.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,), "layer": _s("mask"), "out_layer": _s(),
            "high_to_low": _b(True), "include_border": _b(False),
            "border": (list(_fsim.CONV_BORDERS), {"default": "black"}),
            "direction": (list(_fsim.FEATHER_DIRS),),
            "sweep_nx": _b(False), "sweep_px": _b(True),
            "sweep_ny": _b(False), "sweep_py": _b(False),
            "sweep_nxny": _b(False), "sweep_nxpy": _b(False),
            "sweep_pxny": _b(False), "sweep_pxpy": _b(False),
            "method": (list(_fsim.FEATHER_METHODS),),
            "distance": _f(0.1, 1e-6, 1e6, 0.01),
            "change": _f(10.0, 0, 1e6, 0.1),
            "mask": _f(1.0, 0, 1, 0.01), "mask_layer": _s()}}

    def run(self, cop, layer, out_layer, high_to_low, include_border, border,
            direction, sweep_nx, sweep_px, sweep_ny, sweep_py, sweep_nxny,
            sweep_nxpy, sweep_pxny, sweep_pxpy, method, distance, change,
            mask, mask_layer):
        on = {"nx": sweep_nx, "px": sweep_px, "ny": sweep_ny, "py": sweep_py,
              "nxny": sweep_nxny, "nxpy": sweep_nxpy, "pxny": sweep_pxny,
              "pxpy": sweep_pxpy}
        return (_fsim.feather_slope(cop, layer, out_layer, high_to_low,
                                  include_border, border, direction,
                                  [k for k, v in on.items() if v], method,
                                  distance, change, mask, mask_layer),)


@_node
class PCG_COPPixelate:
    """Maps to: Pixelate. Size×Size blocks take the average (average) or the block centre (sample)."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "size": _i(8, 1, 4096),
                             "mode": (["average", "sample"],)}}

    def run(self, cop, layers, size, mode):
        return (_fx.pixelate(cop, layers, size, mode),)


@_node
class PCG_COPChromaticAberration:
    """Maps to: Chromatic Aberration. R scaled up by 1+Amount about the centre, B scaled down, G unchanged -- colour fringes at the edges."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("C"),
                             "amount": _f(0.01, -1, 1, 0.001),
                             "center": _s("0.5 0.5"), "border": _bd()}}

    def run(self, cop, layer, amount, center, border):
        return (_fx.chromatic_aberration(cop, layer, amount, center,
                                         border),)


@_node
class PCG_COPHeatDistort:
    """
    Maps to: Heat Distort / Heat Distort by Layer. Pushes pixels (Amount pixels) with simplex noise drifting towards Direction
    over time. With Field Layer connected, distorts only where it is > 0 (heat haze above a heat
    source). Connect the frame number to Time for animation.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "amount": _f(4.0, -1024, 1024, 0.1),
                             "scale": _f(0.05, 1e-4, 100, 0.005),
                             "speed": _f(1.0, -1e3, 1e3, 0.01),
                             "time": _f(0.0, -1e6, 1e6, 0.01),
                             "direction": _f(90.0, -360, 360, 1),
                             "field_layer": _s(),
                             "rand_seed": _i(0, 0, 2 ** 31 - 1),
                             "border": _bd()}}

    def run(self, cop, layers, amount, scale, speed, time, direction,
            field_layer, rand_seed, border):
        return (_fx.heat_distort(cop, layers, amount, scale, speed, time,
                                 direction, field_layer, rand_seed, border),)


@_node
class PCG_COPHeatDistortByLayer:
    """
    Maps to: Heat Distort by Layer (Houdini semantics, pcg100 c7). Pushes pixels with the **input's** noise layer (or
    a dir direction layer): displacement = Scale · effect · Rot(Angle) · ∇noise (image units), with optional
    Accurate Distortion (curved paths along the field), Streak Blur, Scale by Timestep, Blur Source /
    Blur Noise, Chromatic Aberration. The old COP Heat Distort generates its own simplex noise drifting over
    time; it maps to Houdini's "Heat Distort" (the procedural one) and is kept unchanged.
    The docs don't give the formula; our definition is in filtersim.heat_distort_by_layer.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,), "layers": _s(), "noise_layer": _s("noise"),
            "effect_layer": _s(), "dir_layer": _s(),
            "scale": _f(0.05, -1e4, 1e4, 0.005),
            "angle": _f(0.0, -3600, 3600, 1),
            "accurate": _b(False), "step_pixels": _f(1.0, 0.05, 1e4, 0.1),
            "streak_blur": _b(False),
            "scale_by_timestep": _b(False),
            "timestep": _f(1.0 / 24, 0, 1e3, 0.001),
            "blur_source": _b(False),
            "blur_source_size": _f(0.01, 0, 100, 0.001),
            "blur_noise": _b(False),
            "blur_noise_size": _f(0.01, 0, 100, 0.001),
            "chromatic": _b(False), "ca_scale": _f(1.0, -100, 100, 0.01),
            "ca_red": _f(1.2, -100, 100, 0.01),
            "ca_green": _f(1.0, -100, 100, 0.01),
            "ca_blue": _f(0.8, -100, 100, 0.01),
            "border": _bd(), "mask": _f(1.0, 0, 1, 0.01), "mask_layer": _s()}}

    def run(self, cop, layers, noise_layer, effect_layer, dir_layer, scale,
            angle, accurate, step_pixels, streak_blur, scale_by_timestep,
            timestep, blur_source, blur_source_size, blur_noise,
            blur_noise_size, chromatic, ca_scale, ca_red, ca_green, ca_blue,
            border, mask, mask_layer):
        return (_fsim.heat_distort_by_layer(
            cop, layers, noise_layer, effect_layer, dir_layer, scale, angle,
            accurate, step_pixels, streak_blur, scale_by_timestep, timestep,
            blur_source, blur_source_size, blur_noise, blur_noise_size,
            chromatic, ca_scale, ca_red, ca_green, ca_blue, border, mask,
            mask_layer),)


@_node
class PCG_COPSwirl:
    """
    Maps to: Swirl / Bend (plus Pinch / Bulge). swirl rotates by Amount degrees within Radius with (1 − r/R)²
    falloff; pinch / bulge pull in / push out (Amount 0~1); bend curves the image
    horizontally into an arc (Amount = the central angle spanned by the full width).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "mode": (list(_fx.SWIRL_MODES),),
                             "amount": _f(90.0, -3600, 3600, 1.0),
                             "radius": _f(0.4, 0, 10, 0.01),
                             "center": _s("0.5 0.5"), "border": _bd()}}

    def run(self, cop, layers, mode, amount, radius, center, border):
        return (_fx.swirl(cop, layers, mode, amount, radius, center, border),)


@_node
class PCG_COPLensDistort:
    """
    Maps to: Lens Distort. Brown–Conrady radial distortion, k1 < 0 barrel, > 0 pincushion;
    distort adds distortion, undistort removes it, and the round trip closes.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "k1": _f(-0.1, -2, 2, 0.005),
                             "k2": _f(0.0, -2, 2, 0.005),
                             "mode": (["distort", "undistort"],),
                             "center": _s("0.5 0.5"), "border": _bd("black")}}

    def run(self, cop, layers, k1, k2, mode, center, border):
        return (_fx.lens_distort(cop, layers, k1, k2, mode, center, border),)


@_node
class PCG_COPDerivative:
    """
    Maps to: Derivative / Laplacian / Curl. Central differences, in units "per pixel" × Scale.
    curl: 1 channel treated as a stream function → divergence-free velocity field (curl noise); 2 channels → scalar curl.
    Empty Out Layer = layername_mode.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("C"),
                             "mode": (list(_fx.DERIV_MODES),),
                             "scale": _f(1.0), "border": _bd(),
                             "out_layer": _s()}}

    def run(self, cop, layer, mode, scale, border, out_layer):
        return (_fx.derivative(cop, layer, mode, scale, border, out_layer),)


@_node
class PCG_COPCornerDetect:
    """
    Maps to: Corner Detect. Harris response det − k·tr²; pixels above Threshold×max that are a
    local maximum within Radius are marked 1. The second output is the corner count.
    """
    RETURN_TYPES = (COP, "INT")
    RETURN_NAMES = ("cop", "count")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("C"),
                             "k": _f(0.05, 0, 0.25, 0.005),
                             "sigma": _f(1.5, 0.1, 64, 0.1),
                             "threshold": _f(0.01, 0, 1, 0.001),
                             "radius": _i(3, 0, 64),
                             "out_layer": _s("corners"),
                             "response_layer": _s()}}

    def run(self, cop, layer, k, sigma, threshold, radius, out_layer,
            response_layer):
        return _fx.corner_detect(cop, layer, k, sigma, threshold, radius,
                                 out_layer, response_layer)


@_node
class PCG_COPSmoothFill:
    """
    Maps to: Smooth Fill / Extrapolate Boundaries. Mask Layer > 0.5 are known pixels,
    the rest are filled: pushpull (pyramid, fast) / laplace (harmonic membrane, smoothest) / nearest
    (extrapolated ring by ring, Rings 0 = fill completely). Known pixels stay bit-exact.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "mask_layer": _s("mask"),
                             "mode": (list(_fx.FILL_MODES),),
                             "iterations": _i(200, 0, 100000),
                             "rings": _i(0, 0, 100000)}}

    def run(self, cop, layers, mask_layer, mode, iterations, rings):
        return (_fx.smooth_fill(cop, layers, mask_layer, mode, iterations,
                                rings),)


@_node
class PCG_COPExtrapolateBoundaries:
    """
    Maps to: Extrapolate Boundaries (Houdini semantics, pcg100 c7). The fillarea layer is split into inside by
    Threshold / Inner Side; outside within Edge Padding (image units) copies the nearest
    inside value (optionally stepping inward by Edge Offset, optionally sampling only inside pixels), and further out it's handled by Exterior
    (as is / black / Diffuse Fill). For texture bleed. The old COP Smooth Fill is "hole filling on a mask
    + three home-made algorithms", not the same thing, kept unchanged. See filtersim.extrapolate_boundaries.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,), "layers": _s(), "fillarea_layer": _s("mask"),
            "exterior": (list(_fsim.EXTRAP_EXTERIOR),),
            "inner_side": (list(_fsim.EXTRAP_SIDES),
                           {"default": "above_threshold"}),
            "threshold": _f(0.5, -1e6, 1e6, 0.01),
            "edge_padding": _f(0.05, 0, 1e6, 0.005),
            "edge_offset": _f(0.0, 0, 1e6, 0.001),
            "sample_only_present": _b(True),
            "diffuse_iterations": _i(50, 0, 100000),
            "mask": _f(1.0, 0, 1, 0.01), "mask_layer": _s()}}

    def run(self, cop, layers, fillarea_layer, exterior, inner_side,
            threshold, edge_padding, edge_offset, sample_only_present,
            diffuse_iterations, mask, mask_layer):
        return (_fsim.extrapolate_boundaries(
            cop, layers, fillarea_layer, inner_side, threshold, exterior,
            edge_padding, edge_offset, sample_only_present,
            diffuse_iterations, mask, mask_layer),)


@_node
class PCG_COPFloodFill:
    """
    Maps to: Fill Connected. Starting from seeds (uv or Seed Layer), selects **connected** pixels differing from the seed value by ≤
    Tolerance as a mask. The second output is the number of selected pixels.
    """
    RETURN_TYPES = (COP, "INT")
    RETURN_NAMES = ("cop", "count")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("C"),
                             "seed_uv": _s("0.5 0.5"), "seed_layer": _s(),
                             "tolerance": _f(0.1, 0, 1e6, 0.01),
                             "connectivity": (["4", "8"],),
                             "out_layer": _s("fill_mask")}}

    def run(self, cop, layer, seed_uv, seed_layer, tolerance, connectivity,
            out_layer):
        return _fx.flood_fill(cop, layer, seed_uv, seed_layer, tolerance,
                              int(connectivity), out_layer)


@_node
class PCG_COPContour:
    """
    Maps to: Edge Detect by Contour. One contour line every Interval, line width computed in pixels
    (value distance ÷ gradient), equally thick on steep and gentle parts.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("C"),
                             "interval": _f(0.1, 1e-6, 1e6, 0.01),
                             "offset": _f(0.0),
                             "width": _f(1.0, 0.01, 64, 0.1),
                             "out_layer": _s("contour")}}

    def run(self, cop, layer, interval, offset, width, out_layer):
        return (_fx.contour(cop, layer, interval, offset, width, out_layer),)


@_node
class PCG_COPEdgeDetectProbe:
    """
    Maps to: Edge Detect by Contour / Edge Detect by Depth / Edge Detect by Normal
    (Houdini semantics, pcg100 c7). Probes neighbours within radius Thickness Scale (× the thickness layer, no less than
    Min Probe Radius): neighbours with a different id / depth difference above tolerance / normal dot product below tolerance
    count as on the line, with Gaussian falloff by distance (Edge Spread). The old COP Contour is "contour lines",
    Control Image's lineart is ControlNet packing; neither is the same thing, both kept unchanged.
    The docs don't give algorithm details; our definition is in filtersim.edge_detect_probe.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,), "kind": (list(_fsim.EDGE_KINDS),),
            "layer": _s("id"), "thickness_scale": _f(2.0, 0, 64, 0.1),
            "thickness_layer": _s(), "edge_spread": _f(0.5, 0, 100, 0.05),
            "blur": _f(0.0, 0, 256, 0.1),
            "contour_tolerance": _f(0.5, 0, 1e6, 0.01),
            "depth_tolerance": _f(0.01, 0, 1e6, 0.001),
            "normal_tolerance": _f(0.9, -1, 1, 0.01),
            "min_probe_radius": _f(1.0, 0, 64, 0.1),
            "out_layer": _s("edges")}}

    def run(self, cop, kind, layer, thickness_scale, thickness_layer,
            edge_spread, blur, contour_tolerance, depth_tolerance,
            normal_tolerance, min_probe_radius, out_layer):
        return (_fsim.edge_detect_probe(
            cop, kind, layer, thickness_scale, thickness_layer, edge_spread,
            blur, contour_tolerance, depth_tolerance, normal_tolerance,
            min_probe_radius, out_layer),)


@_node
class PCG_COPDither:
    """
    Maps to: Surface Dither. Dithers to Levels levels: bayer ordered (tileable, no flicker in animation) /
    floyd_steinberg error diffusion / white_noise. Values are clamped to 0~1 first.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "method": (list(_fx.DITHERS),),
                             "levels": _i(2, 2, 256),
                             "rand_seed": _i(0, 0, 2 ** 31 - 1)}}

    def run(self, cop, layers, method, levels, rand_seed):
        return (_fx.dither(cop, layers, method, levels, rand_seed),)


@_node
class PCG_COPSurfaceDither:
    """
    Maps to: Surface Dither (Houdini semantics, pcg100 c7). Halftone dots attached to uv, levelled automatically by the on-screen
    uv derivatives (dot spacing kept around Density Scale pixels); when changing level, the extra dots shrink away within the Level
    Transition section -- under scaling and perspective the dots neither blur into grey nor pop. Outputs Mask or SDF,
    optionally also uv / level / scale layers. The old COP Dither is screen-space quantisation dithering (bayer / error
    diffusion), not the same thing, kept unchanged. Approach in filtersim.surface_dither.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "uv_layer": _s(), "dotscale_layer": _s(),
            "density_scale": _f(8.0, 0.01, 4096, 0.5),
            "pattern_scale": _f(1.0, 1e-6, 1e6, 0.01),
            "pattern_scale_xy": _s("1 1"), "pattern_offset": _s("0 0"),
            "pattern_rotate": _f(0.0, -3600, 3600, 1),
            "dot_scale": _f(0.5, 0, 100, 0.01),
            "output_type": (list(_fsim.DITHER_OUTPUTS),),
            "iso_offset": _f(0.0, -1e6, 1e6, 0.05),
            "smooth": _f(1.0, 0, 1e6, 0.05),
            "level_transition": _f(0.5, 0, 1, 0.01),
            "out_layer": _s("dither"), "uv_out_layer": _s(),
            "level_layer": _s(), "scale_layer": _s(), **_res()},
            "optional": {"cop": (COP,)}}

    def run(self, uv_layer, dotscale_layer, density_scale, pattern_scale,
            pattern_scale_xy, pattern_offset, pattern_rotate, dot_scale,
            output_type, iso_offset, smooth, level_transition, out_layer,
            uv_out_layer, level_layer, scale_layer, resolution_x,
            resolution_y, cop=None):
        return (_fsim.surface_dither(
            cop, uv_layer, dotscale_layer, density_scale, pattern_scale,
            pattern_scale_xy, pattern_offset, pattern_rotate, dot_scale,
            output_type, iso_offset, smooth, level_transition, out_layer,
            uv_out_layer, level_layer, scale_layer, resolution_x,
            resolution_y),)


@_node
class PCG_COPMirror:
    """
    Maps to: Mirror. Mirrors one half onto the other (Position is the mirror position); quad = mirror the lower-left quarter to fill all four.

    number_and_offset / custom_planes (pcg100) are Houdini's two modes: mirrors at arbitrary angles,
    image space (origin at the image centre, −1 … 1 across the long side). Angle 0 = vertical centre line, left half
    mirrored onto the right half; positive Offset moves the mirror right; Reverse swaps the source side. In Number and Offset mode the k-th mirror's
    angle is k·Angle; in Custom mode Mirrors holds one mirror per line (`angle offset [reverse]`),
    applied in order. Which conventions are from the docs and which are ours: see geo/cop/fx.mirror_planes.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "mode": (list(_fx.MIRRORS),),
                             "position": _f(0.5, 0, 1, 0.01),
                             "planes": _i(1, 1, 64),
                             "angle": _f(0.0, -3600, 3600, 1),
                             "offset": _f(0.0, -10, 10, 0.01),
                             "reverse": _b(False),
                             "plane_list": ("STRING", {"default": "0 0",
                                                       "multiline": True})}}

    def run(self, cop, layers, mode, position, planes=1, angle=0.0,
            offset=0.0, reverse=False, plane_list="0 0"):
        return (_fx.mirror(cop, layers, mode, position, planes, angle, offset,
                           reverse, plane_list),)


@_node
class PCG_COPCornerPin:
    """
    Maps to: Corner Pin / Transform 3D. corners: uv of the four output corners (lower-left lower-right upper-right
    upper-left); rotate_3d: the image as a card rotated in 3D (xyz degrees), shot back with a pinhole camera of FOV.
    Both are one homography; straight lines stay straight.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "mode": (list(_fx.PIN_MODES),),
                             "corners": _s("0 0 1 0 1 1 0 1"),
                             "rotate": _sec("3D", _s("0 0 0")),
                             "fov": _sec("3D", _f(45.0, 1, 179, 1)),
                             "distance": _sec("3D", _f(0.0, 0, 1e6, 0.01)),
                             "border": _bd("black")}}

    def run(self, cop, layers, mode, corners, rotate, fov, distance, border):
        return (_fx.corner_pin(cop, layers, mode, corners, rotate, fov,
                               distance, border),)


@_node
class PCG_COPLatticeDeform:
    """
    Maps to: Lattice Deform. A Divisions grid of control points; Offsets gives uv displacement per point (row by row
    bottom up, two numbers per point) or Jitter randomises; displacement is bilinearly interpolated to every pixel.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "divisions": _s("4 4"),
                             "offsets": ("STRING", {"default": "",
                                                    "multiline": True}),
                             "jitter": _f(0.0, 0, 1, 0.005),
                             "rand_seed": _i(0, 0, 2 ** 31 - 1),
                             "border": _bd()}}

    def run(self, cop, layers, divisions, offsets, jitter, rand_seed,
            border):
        return (_fx.lattice_deform(cop, layers, divisions, offsets, jitter,
                                   rand_seed, border),)


@_node
class PCG_COPPlanarInflate:
    """
    Maps to: Planar Inflate. Inflates a mask into height: round = circular-arc profile (steep edges, flat middle,
    like a pillow); poisson = a soap bubble with ∇²h = −1. Maximum = Height.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("mask"),
                             "mode": (["round", "poisson"],),
                             "height": _f(1.0, -1e6, 1e6, 0.01),
                             "iterations": _i(200, 1, 100000),
                             "out_layer": _s("height")}}

    def run(self, cop, layer, mode, height, iterations, out_layer):
        return (_fx.planar_inflate(cop, layer, mode, height, iterations,
                                   out_layer),)


@_node
class PCG_COPCopyTransform:
    """
    Maps to: Copy and Transform. Copy i is translated by i·Translate (uv), rotated by i·Rotate degrees,
    scaled by Scale^i, stacked by Op (over / add / max); Fade makes later copies progressively fainter.

    pcg100: Op gains over_last / under -- Houdini's Over (later copies on top) and
    Under (later copies below), with alpha computed by Porter–Duff. The old over is "copy 0 on top"
    with incorrect alpha, kept unchanged. Scale XY is non-uniform scaling, multiplied with Scale.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "copies": _i(4, 1, 1024),
                             "translate": _s("0.1 0"),
                             "rotate": _f(0.0, -3600, 3600, 1),
                             "scale": _f(1.0, 0.001, 100, 0.01),
                             "pivot": _s("0.5 0.5"),
                             "op": (list(_fx.COPY_OPS),),
                             "fade": _f(0.0, 0, 1, 0.01),
                             "scale_xy": _s("1 1")}}

    def run(self, cop, layers, copies, translate, rotate, scale, pivot, op,
            fade, scale_xy="1 1"):
        return (_fx.copy_transform(cop, layers, copies, translate, rotate,
                                   scale, pivot, op, fade, scale_xy),)


# ═══════════════════════════════════════════════════════ Batch C: patterns / noise / text / shape scattering
_pt = _cop.pattern
_nx = _cop.noisex
from .geo.cop import noisepost as _cpost               # noqa: E402  Post Processing section
_st = _cop.stamp


def _res():
    return {"resolution_x": _i(512, 1, _cop.MAX_RES),
            "resolution_y": _i(512, 1, _cop.MAX_RES)}


@_node
class PCG_COPPattern:
    """
    Maps to: Checkerboard / Tile Pattern / Cell Pattern / Labs UV Grid Texture /
    Julia Fractal / Chladni Cymatic Patterns / Knit / Weave.

    Main layer Out Layer, auxiliary layers Out Layer_xxx (id, a random number per piece, uv within the piece, pixel distance to the edge,
    bevel height…) -- colouring by id and bevel normals by distance rely on these. With an integer piece count it tiles seamlessly
    in all directions. With cop connected, layers are added on top of it (resolution follows it); otherwise a new one is created at Resolution.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "kind": (list(_pt.PATTERNS),),
            "counts": _s("8 8"),
            "offset": _sec("Tile", _f(0.5, -4, 4, 0.05)),
            "gap": _sec("Tile", _f(0.05, 0, 1, 0.005)),
            "bevel": _sec("Tile", _f(0.1, 0, 1, 0.005)),
            "jitter": _sec("Cell", _f(1.0, 0, 1, 0.01)),
            "weave": _sec("Weave", (list(_pt.WEAVES),)),
            "thread_width": _sec("Weave", _f(0.8, 0.05, 1, 0.01)),
            "fractal": _sec("Julia", (["julia", "mandelbrot"],)),
            "c": _sec("Julia", _s("-0.8 0.156")),
            "center": _sec("Julia", _s("0 0")),
            "zoom": _sec("Julia", _f(1.0, 1e-6, 1e9, 0.1)),
            "iterations": _sec("Julia", _i(100, 1, 5000)),
            "modes": _sec("Chladni", _s("3 5")),
            "sign": _sec("Chladni", (["-", "+"],)),
            "line_width": _sec("Chladni", _f(1.5, 0.1, 64, 0.1)),
            "font": _sec("UV Grid", _s()),
            "labels": _sec("UV Grid", _b(True)),
            "rand_seed": _i(0, 0, 2 ** 31 - 1),
            "out_layer": _s("pattern"),
            **_res(),
            # ── pcg100 c4: added to match SideFX Tile Pattern / Cell / Chladni / UV Grid / Weave,
            #    all appended at the end, defaults = old behaviour
            "bond": _sec("Tile", (list(_pt.BONDS),)),
            "header_interval": _sec("Tile", _i(6, 1, 1000)),
            "chladni_output": _sec("Chladni", (list(_pt.CHLADNI_OUT),)),
            "amplitude": _sec("Chladni", _f(1.0, -1e4, 1e4, 0.01)),
            "amplitude_ratio": _sec("Chladni", _f(1.0, -1e4, 1e4, 0.01)),
            "threshold": _sec("Chladni", _f(0.1, 0.0, 1e4, 0.005)),
            "smoothing_width": _sec("Chladni", _f(0.05, 0.0, 1e4, 0.005)),
            "cell_metric": _sec("Cell", (list(_pt.CELL_METRICS),)),
            "lattice": _sec("Cell", (list(_pt.CELL_LATTICES),)),
            "density": _sec("Cell", _f(1.0, 0.0, 1.0, 0.01)),
            "density_seed": _sec("Cell", _i(0, 0, 2 ** 31 - 1)),
            "tile_coloring": _sec("UV Grid", (list(_pt.UVG_TILE_COLORING),)),
            "tile_color1": _sec("UV Grid", _s("0.85 0.85 0.85")),
            "tile_color2": _sec("UV Grid", _s("0.6 0.6 0.6")),
            "outlines": _sec("UV Grid", _b(True)),
            "outline_width": _sec("UV Grid", _f(1.0, 0.0, 1e3, 0.1)),
            "outline_color": _sec("UV Grid", _s("0.08 0.08 0.08")),
            "marker_type": _sec("UV Grid", (list(_pt.UVG_MARKERS),)),
            "text_mode": _sec("UV Grid", (list(_pt.UVG_TEXT),)),
            "marker_size": _sec("UV Grid", _f(0.32, 0.0, 10.0, 0.01)),
            "marker_coloring": _sec("UV Grid", (list(_pt.UVG_MARKER_COLORING),)),
            "marker_color": _sec("UV Grid", _s("0.05 0.05 0.05")),
            "marker_color2": _sec("UV Grid", _s("1 1 1")),
            "separate_widths": _sec("Weave", _b(False)),
            "weft_width": _sec("Weave", _f(0.8, 0.05, 1, 0.01)),
            "weave_layer": _sec("Weave", _s()),
            },
            "optional": {"cop": (COP,)}}

    def run(self, kind, counts, offset, gap, bevel, jitter, weave,
            thread_width, fractal, c, center, zoom, iterations, modes, sign,
            line_width, font, labels, rand_seed, out_layer, resolution_x,
            resolution_y, cop=None, bond="offset", header_interval=6,
            chladni_output="pixel_lines", amplitude=1.0, amplitude_ratio=1.0,
            threshold=0.1, smoothing_width=0.05, cell_metric="euclidean",
            lattice="grid", density=1.0, density_seed=0, tile_coloring="hue",
            tile_color1="0.85 0.85 0.85", tile_color2="0.6 0.6 0.6",
            outlines=True, outline_width=1.0, outline_color="0.08 0.08 0.08",
            marker_type="text", text_mode="letters", marker_size=0.32,
            marker_coloring="uniform", marker_color="0.05 0.05 0.05",
            marker_color2="1 1 1", separate_widths=False, weft_width=0.8,
            weave_layer=""):
        return (_pt.pattern(cop, kind, counts, offset, gap, bevel, jitter,
                            weave, thread_width, fractal, c, center, zoom,
                            iterations, modes, sign, line_width, font, labels,
                            rand_seed, out_layer, resolution_x,
                            resolution_y, bond, header_interval,
                            chladni_output, amplitude, amplitude_ratio,
                            threshold, smoothing_width, cell_metric, lattice,
                            density, density_seed, tile_coloring, tile_color1,
                            tile_color2, outlines, outline_width,
                            outline_color, marker_type, text_mode,
                            marker_size, marker_coloring, marker_color,
                            marker_color2, separate_widths, weft_width,
                            weave_layer),)


@_node
class PCG_COPUVShape:
    """
    Maps to: UV Shape (new in pcg100 c4). Generates internal coordinates (uv), uv stretch
    (uvscale) and a shape mask (mask) for disks / rings; feed UV Sample to map a square image into the shape.

    Not the same as COP Shape (which outputs an SDF), hence a separate node. Coordinates are centred and normalised by the short side,
    as in COP Shape. uv defaults to Houdini's [−1, 1]; our UV Sample takes 0~1,
    so just choose unit for UV Range. Disk's Conformal and Square / Horseshoe / Spiral /
    Fishscale are not done (see audit_notes/c4_pattern_shape.md).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "shape": (list(_cop.uvshape.SHAPES),),
            "disk_mode": (list(_cop.uvshape.DISK_MODES),),
            "radius": _f(0.4, 1e-6, 1e4, 0.01),
            "annulus_mode": (list(_cop.uvshape.ANNULUS_MODES),),
            "inner_radius": _f(0.2, 1e-6, 1e4, 0.01),
            "outer_radius": _f(0.45, 1e-6, 1e4, 0.01),
            "offset": _s("0 0"),
            "angle": _f(0.0, -3600, 3600, 1),
            "shear": _f(0.0, -1e4, 1e4, 0.01),
            "uv_filter_bound": _f(4.0, 0.0, 1e6, 0.1),
            "u_border": (list(_cop.uvshape.BORDERS),),
            "v_border": (list(_cop.uvshape.BORDERS),),
            "u_scale": _f(1.0, -1e4, 1e4, 0.01),
            "v_scale": _f(1.0, -1e4, 1e4, 0.01),
            "uv_range": (list(_cop.uvshape.RANGES),),
            "uv_layer": _s("uv"),
            "uvscale_layer": _s("uvscale"),
            "mask_layer": _s("mask"),
            **_res()},
            "optional": {"cop": (COP,)}}

    def run(self, shape, disk_mode, radius, annulus_mode, inner_radius,
            outer_radius, offset, angle, shear, uv_filter_bound, u_border,
            v_border, u_scale, v_scale, uv_range, uv_layer, uvscale_layer,
            mask_layer, resolution_x, resolution_y, cop=None):
        return (_cop.uvshape.uv_shape(
            cop, shape, disk_mode, radius, annulus_mode, inner_radius,
            outer_radius, offset, angle, shear, u_scale, v_scale, u_border,
            v_border, uv_filter_bound, uv_range, uv_layer, uvscale_layer,
            mask_layer, resolution_x, resolution_y),)


@_node
class PCG_COPNoiseExtra:
    """
    Maps to: Bubble Noise / Crystal Noise (3D) / Phasor Noise / Curl Noise (3D) /
    Cloud Noise 3D.

    pcg100: the main layer of every kind gains Amplitude / Center / Post Processing (the Range and post-processing sections
    shared by the Houdini nodes); Crystal gains Metric / Jitter; Phasor gains Type (Phasor
    Wave / Gabor Noise / Intensity Field) and Periodic Function. **The core algorithms of Bubble / Cloud / Crystal
    are still our own** (the Houdini docs give no formulas), see audit_notes/c3_noise.md.

    Coordinates are normalised by image width, keeping the aspect ratio (bubbles are round); the 3D ones are sliced at the third number z = Offset,
    and moving z forward animates the volume. Phasor: a Gabor variant with uniform stripe contrast everywhere; connect a
    Direction Layer (2 channels) to make the stripes follow the field. Curl: a divergence-free velocity field.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "kind": (list(_nx.NOISE_KINDS),),
            "frequency": _f(8.0, 0.001, 1e4, 0.1),
            "offset": _s("0 0 0"),
            "octaves": _i(3, 1, 12),
            "radius": _sec("Bubble", _f(0.8, 0, 1, 0.01)),
            "density": _sec("Bubble", _f(0.7, 0, 1, 0.01)),
            "sharpness": _sec("Crystal", _f(1.0, 0, 100, 0.05)),
            "stripe_freq": _sec("Phasor", _f(2.0, 0, 64, 0.05)),
            "angle": _sec("Phasor", _f(0.0, -360, 360, 1)),
            "spread": _sec("Phasor", _f(30.0, 0, 360, 1)),
            "kernels": _sec("Phasor", _i(2, 1, 16)),
            "direction_layer": _sec("Phasor", _s()),
            "coverage": _sec("Cloud", _f(0.5, 0, 1, 0.01)),
            "softness": _sec("Cloud", _f(0.2, 0.001, 1, 0.01)),
            "billow": _sec("Cloud", _b(False)),
            "rand_seed": _i(0, 0, 2 ** 31 - 1),
            "out_layer": _s("noise"),
            **_res(), "compute": _compute(),
            # pcg100 c3_noise (appended at the end, defaults = old behaviour):
            "metric": _sec("Crystal", (list(_nx.METRICS),)),
            "jitter": _sec("Crystal", _f(1.0, 0.0, 2.0, 0.01)),
            "phasor_type": _sec("Phasor", (list(_nx.PHASOR_TYPES),)),
            "periodic_function": _sec("Phasor", (list(_nx.PERIODIC),)),
            "amplitude": _f(1.0, -1e5, 1e5, 0.01),
            "center": _f(0.0, -1e5, 1e5, 0.01),
            **_cpost.widgets(_f, _sec)},
            "optional": {"cop": (COP,)}}

    def run(self, kind, frequency, offset, octaves, radius, density,
            sharpness, stripe_freq, angle, spread, kernels, direction_layer,
            coverage, softness, billow, rand_seed, out_layer, resolution_x,
            resolution_y, compute="auto", metric="euclidean", jitter=1.0,
            phasor_type="phasor_wave", periodic_function="sine",
            amplitude=1.0, center=0.0, cop=None, **post):
        return (_nx.noise_extra(cop, kind, frequency, offset, octaves, radius,
                                density, sharpness, stripe_freq, angle,
                                spread, kernels, direction_layer, coverage,
                                softness, billow, rand_seed, out_layer,
                                resolution_x, resolution_y, compute, metric,
                                jitter, phasor_type, periodic_function,
                                amplitude, center, _cpost.pick(post)),)


# ═══════════════════════════════════════════ pcg100 c3_noise:Worley / Cellular
from .geo.cop import cellnoise as _cn                    # noqa: E402


def _cell_pattern(border_key, border_default=0.0):
    """The Pattern section shared by Worley / Cellular (element size, jitter, grid, metric, offset, tiling)."""
    return {
        "element_size": _f(0.1, 1e-6, 1e4, 0.005),
        "element_scale": _s("1 1 1"),
        "jitter": _f(1.0, 0.0, 2.0, 0.01),
        "jitter_scale": _s("1 1 1"),
        "lattice": (list(_cn.LATTICES),),
        "metric": (list(_cn.METRICS),),
        border_key: _f(border_default, 0.0, 10.0, 0.01),
        "offset": _s("0 0 0"),
        "tile": _b(False),
        "tile_size": _s("1 1 1"),
    }


@_node
class PCG_COPWorleyNoise:
    """
    Maps to: Worley Noise / Worley Noise 3D.

    Outputs five layers (names = Prefix + dist1 / dist2 / border / center / id, the same names as Houdini's five
    outputs): distance to the nearest / second-nearest feature point, exact distance to the cell border (Euclidean; under the other two metrics an
    estimate of (dist2 − dist1)/2), the nearest feature point's coordinates, and the nearest cell's hash. Coordinates are normalised by image width
    (x = u, y = v·H/W); connect cop and give Pos Layer (3 channels) for the 3D version. Post Processing
    only affects dist1 / dist2. The algorithm and our own choices are in the header of geo/cop/cellnoise.py.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            **_cell_pattern("round_border"),
            "pos_layer": _s(),
            "rand_seed": _i(0, 0, 2 ** 31 - 1),
            "prefix": _s(),
            **_cpost.widgets(_f, _sec),
            **_res()},
            "optional": {"cop": (COP,)}}

    def run(self, element_size, element_scale, jitter, jitter_scale, lattice,
            metric, round_border, offset, tile, tile_size, pos_layer,
            rand_seed, prefix, resolution_x, resolution_y, cop=None, **post):
        return (_cn.worley_noise(cop, element_size, element_scale, jitter,
                                 jitter_scale, lattice, metric, round_border,
                                 offset, tile, tile_size, pos_layer,
                                 rand_seed, prefix, _cpost.pick(post),
                                 resolution_x, resolution_y),)


@_node
class PCG_COPCellularNoise:
    """
    Maps to: Cellular Noise / Cellular Noise 3D.

    noise = Amplitude · shaping(border) + Shift: in Absolute mode Gap / Bevel are image coordinates,
    in Relative mode a ratio from 0 (cell border) ~ 1 (feature point). Bevel 0 = hard-edged flat top, larger means a sharper top.
    Also outputs border / center / id layers (same as Worley Noise). Bevel Ramp is not done (linear slope).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "amplitude": _f(1.0, -1e5, 1e5, 0.01),
            "shift": _f(0.0, -1e5, 1e5, 0.01),
            **_cell_pattern("smooth_edge"),
            "shape_mode": (list(_cn.SHAPE_MODES),),
            "gap": _f(0.0, 0.0, 1e4, 0.005),
            "bevel": _f(0.05, 0.0, 1e4, 0.005),
            "pos_layer": _s(),
            "rand_seed": _i(0, 0, 2 ** 31 - 1),
            "prefix": _s(),
            **_cpost.widgets(_f, _sec),
            **_res()},
            "optional": {"cop": (COP,)}}

    def run(self, amplitude, shift, element_size, element_scale, jitter,
            jitter_scale, lattice, metric, smooth_edge, offset, tile,
            tile_size, shape_mode, gap, bevel, pos_layer, rand_seed, prefix,
            resolution_x, resolution_y, cop=None, **post):
        return (_cn.cellular_noise(cop, amplitude, shift, element_size,
                                   element_scale, jitter, jitter_scale,
                                   lattice, metric, smooth_edge, offset, tile,
                                   tile_size, shape_mode, gap, bevel,
                                   pos_layer, rand_seed, prefix,
                                   _cpost.pick(post), resolution_x,
                                   resolution_y),)


from .geo.cop import fractalsample as _fs               # noqa: E402


@_node
class PCG_COPFractalSample:
    """
    Maps to: Fractal Sample.

    Treats the source layer as a "basis function", octave by octave shrinking it (Lacunarity), reducing weight (Roughness), rotating (Angle,
    accumulated Per Octave or Random), jittering (Jitter) and randomly flipping, then stacks them by Blend Mode (Add / Subtract /
    Maximum / Over). With 1 octave and no rotation or jitter the output = the source. Maintain Tileable rounds
    Lacunarity to an integer and angles to multiples of 90°. Formulas and what's not done are in geo/cop/fractalsample.py.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "source_layer": _s("C"),
            "maintain_tileable": _b(False),
            "max_octaves": _i(4, 1, 16),
            "lacunarity": _f(2.0, 0.01, 16.0, 0.05),
            "roughness": _f(0.5, 0.0, 4.0, 0.01),
            "bias": _f(0.5, -1e5, 1e5, 0.01),
            "offset_with_bias": _b(True),
            "blend_mode": (list(_fs.BLEND_MODES),),
            "border": (["wrap", "clamp", "black"],),
            "filter": (list(_fs.FILTERS),),
            "rand_seed": _i(0, 0, 2 ** 31 - 1),
            "jitter": _f(0.0, 0.0, 10.0, 0.01),
            "angle_mode": (list(_fs.ANGLE_MODES),),
            "angle": _f(0.0, -360.0, 360.0, 1.0),
            "random_flip_x": _b(False),
            "random_flip_y": _b(False),
            **_cpost.widgets(_f, _sec),
            "out_layer": _s("fractal"),
        }}

    def run(self, cop, source_layer, maintain_tileable, max_octaves,
            lacunarity, roughness, bias, offset_with_bias, blend_mode, border,
            filter, rand_seed, jitter, angle_mode, angle, random_flip_x,
            random_flip_y, out_layer, **post):
        return (_fs.fractal_sample(cop, source_layer, max_octaves, lacunarity,
                                   roughness, bias, offset_with_bias,
                                   blend_mode, border, filter,
                                   maintain_tileable, jitter, angle,
                                   angle_mode, random_flip_x, random_flip_y,
                                   rand_seed, out_layer, _cpost.pick(post)),)


@_node
class PCG_COPText:
    """
    Maps to: Font. Text -> a coverage mask (FreeType anti-aliasing). Empty Font = Pillow's built-in font
    (Latin characters only); for Chinese give a system font name, e.g. msyh.ttc (Microsoft YaHei), simhei.ttf.
    Position is uv (v up); Align / VAlign decide which point of the text block lines up with it. If
    Composite Layer is given, Color is composited by the mask onto that layer.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "text": ("STRING", {"default": "Text", "multiline": True}),
            "font": _s(), "size": _i(64, 1, 4096),
            "position": _s("0.5 0.5"),
            "align": (list(_pt.ALIGNS),),
            "valign": (["center", "top", "bottom"],),
            "spacing": _f(1.2, 0.1, 10, 0.05),
            "color": _s("1 1 1"), "composite_layer": _s(),
            "out_layer": _s("text"), **_res()},
            "optional": {"cop": (COP,)}}

    def run(self, text, font, size, position, align, valign, spacing, color,
            composite_layer, out_layer, resolution_x, resolution_y,
            cop=None):
        return (_pt.text(cop, text, font, size, position, align, valign,
                         spacing, color, composite_layer, out_layer,
                         resolution_x, resolution_y),)


@_node
class PCG_COPScatterShapes:
    """
    Maps to: Scatter Shapes / Stamp Points / Scatter on Curves / Configure Stamps.

    No geometry connected: Count shapes scattered randomly (Density Layer filters by probability, Min Distance spreads them out, as a fraction
    of image width). Geometry connected: Spacing 0 = one stamp per point (pscale multiplies size, Cd is the colour);
    Spacing > 0 = points taken at equal spacing along curves, Align to Curve rotates along the tangent. For the geometry-to-image mapping see
    Plane / Mapping (xz + world is consistent with HeightField to Mesh).
    With Shape = layer, stamps the Stamp Layer of the Stamp input. The second output is how many were stamped.
    """
    RETURN_TYPES = (COP, "INT")
    RETURN_NAMES = ("cop", "count")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "count": _i(100, 0, 1000000),
            "shape": (list(_st.SHAPES),),
            "size": _f(0.05, 0, 10, 0.005),
            "size_random": _f(0.5, 0, 1, 0.01),
            "aspect": _f(1.0, 0.01, 100, 0.05),
            "rotation": _f(0.0, -3600, 3600, 1),
            "rotation_random": _f(180.0, 0, 360, 1),
            "softness": _f(1.0, 0.01, 64, 0.1),
            "density_layer": _s(),
            "min_distance": _f(0.0, 0, 1, 0.005),
            "blend": (list(_st.BLENDS),),
            "tile": _b(True),
            "rand_seed": _i(0, 0, 2 ** 31 - 1),
            "stamp_layer": _sec("Stamp", _s("C")),
            "plane": _sec("Geometry", (list(_st.PLANES),)),
            "mapping": _sec("Geometry", (list(_st.MAPPINGS),)),
            "world_size": _sec("Geometry", _f(1.0, 1e-6, 1e9, 0.1)),
            "spacing": _sec("Geometry", _f(0.0, 0, 1, 0.005)),
            "align_to_curve": _sec("Geometry", _b(True)),
            "out_layer": _s("shapes"), **_res()},
            "optional": {"cop": (COP,), "stamp": (COP,), "geo": (GEO,)}}

    def run(self, count, shape, size, size_random, aspect, rotation,
            rotation_random, softness, density_layer, min_distance, blend,
            tile, rand_seed, stamp_layer, plane, mapping, world_size,
            spacing, align_to_curve, out_layer, resolution_x, resolution_y,
            cop=None, stamp=None, geo=None):
        return _st.scatter_shapes(cop, count, shape, size, size_random,
                                  aspect, rotation, rotation_random,
                                  softness, density_layer, min_distance,
                                  blend, tile, rand_seed, stamp, stamp_layer,
                                  geo, plane, mapping, world_size, spacing,
                                  align_to_curve, out_layer, resolution_x,
                                  resolution_y)


@_node
class PCG_COPStereogram:
    """
    Maps to: Auto Stereogram. Depth (0 far, 1 near) -> a single-image stereogram: random dots, or connect a
    pattern layer (tiled by Strip width). Parallel viewing; Cross Eyed reverses it. No hidden-surface removal, so edges with abrupt
    depth changes have slight ghosting. Also outputs a _sep layer (per-pixel separation, in pixels).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "depth_layer": _s("depth"),
                             "pattern_layer": _s(),
                             "strip": _i(0, 0, 4096),
                             "depth_scale": _f(0.33, 0, 0.9, 0.01),
                             "cross_eyed": _b(False), "color": _b(True),
                             "rand_seed": _i(0, 0, 2 ** 31 - 1),
                             "out_layer": _s("stereogram")}}

    def run(self, cop, depth_layer, pattern_layer, strip, depth_scale,
            cross_eyed, color, rand_seed, out_layer):
        return (_st.stereogram(cop, depth_layer, pattern_layer, strip,
                               depth_scale, cross_eyed, color, rand_seed,
                               out_layer),)


# ═══════════════════════════════════════════════════════ Batch D: analysis / solvers / simulation
_sv = _cop.solve
_sm = _cop.sim


def _rep(d):
    return json.dumps(d, ensure_ascii=False)


@_node
class PCG_COPFFT:
    """
    Maps to: Fast Fourier Transform / Filter Frequencies. forward: channel 0 → 2 channels
    (Re, Im); inverse the other way; magnitude: log(1 + |F|) to view the spectrum; filter: low-pass /
    high-pass / band-pass / band-stop, Cutoff in "cycles per frame", cosine soft edge (hard truncation rings).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("C"),
                             "mode": (list(_sv.FFT_MODES),),
                             "centered": _b(True),
                             "filter": _sec("Filter", (list(_sv.FILTERS),)),
                             "cutoff": _sec("Filter", _f(8.0, 0, 1e5, 0.5)),
                             "cutoff_high": _sec("Filter",
                                                 _f(32.0, 0, 1e5, 0.5)),
                             "softness": _sec("Filter", _f(2.0, 0, 1e5, 0.5)),
                             "out_layer": _s()}}

    def run(self, cop, layer, mode, centered, filter, cutoff,  # noqa: A002
            cutoff_high, softness, out_layer):
        return (_sv.fft(cop, layer, mode, centered, filter, cutoff,
                        cutoff_high, softness, out_layer),)


@_node
class PCG_COPPrefixSum:
    """
    Maps to: Prefix Sum / Integrate Volume. Accumulates along u / v, or in 2D into an integral image (the sum of any
    rectangle in four lookups). Integrate multiplies by the pixel width, giving an integral in uv.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "direction": (list(_sv.SCAN_DIRS),),
                             "integrate": _b(False), "exclusive": _b(False)}}

    def run(self, cop, layers, direction, integrate, exclusive):
        return (_sv.prefix_sum(cop, layers, direction, integrate,
                               exclusive),)


@_node
class PCG_COPSolvePoisson:
    """
    Maps to: Solve Poisson. ∇²u = f (five-point, pixel spacing 1). With Source = gradient it solves
    ∇²u = div g -- reconstructing height from gradients (e.g. slopes converted from normals), gradient-domain editing, Poisson blending.
    periodic / neumann are both direct FFT solves (neumann uses mirror extension); dirichlet uses conjugate gradients
    preconditioned by the direct neumann solve. The second output is the report.
    """
    RETURN_TYPES = (COP, "STRING")
    RETURN_NAMES = ("cop", "report")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("rhs"),
                             "source": (list(_sv.POISSON_SOURCES),),
                             "boundary": (["neumann", "periodic",
                                           "dirichlet"],),
                             "fixed_layer": _s(), "value_layer": _s(),
                             "tolerance": _f(1e-8, 1e-14, 1, 1e-9),
                             "max_iterations": _i(2000, 1, 1000000),
                             "out_layer": _s("solution")}}

    def run(self, cop, layer, source, boundary, fixed_layer, value_layer,
            tolerance, max_iterations, out_layer):
        o, r = _sv.solve_poisson(cop, layer, source, boundary, fixed_layer,
                                 value_layer, tolerance, max_iterations,
                                 out_layer)
        return (o, _rep(r))


@_node
class PCG_COPEikonal:
    """
    Maps to: Eikonal. |∇T| = 1/F, arrival time from Seed Layer; F = Speed Layer ×
    Speed (0 = wall). With F = 1 it is the geodesic distance around obstacles (pixels). Unreachable places output
    −1. If Id Layer is given a name, "which seed piece is nearest" is output too.
    """
    RETURN_TYPES = (COP, "STRING")
    RETURN_NAMES = ("cop", "report")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "seed_layer": _s("mask"),
                             "speed_layer": _s(),
                             "speed": _f(1.0, 0, 1e6, 0.01),
                             "max_sweeps": _i(60, 1, 10000),
                             "tolerance": _f(1e-6, 0, 1, 1e-6),
                             "out_layer": _s("arrival"), "id_layer": _s()}}

    def run(self, cop, seed_layer, speed_layer, speed, max_sweeps, tolerance,
            out_layer, id_layer):
        o, r = _sv.eikonal(cop, seed_layer, speed_layer, speed, max_sweeps,
                           tolerance, out_layer, id_layer)
        return (o, _rep(r))


@_node
class PCG_COPSegmentByValue:
    """
    Maps to: Segment by Value / Mono to ID. Bins by value (bins equal division / step fixed step size /
    unique one bin per value); with Connected, unconnected parts of the same bin are split further. The second output is the piece count.
    cast is Houdini's Mono to ID (Conversion = Cast): values are truncated directly to integers as ids,
    without renumbering or connectivity.
    """
    RETURN_TYPES = (COP, "INT")
    RETURN_NAMES = ("cop", "count")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("C"),
                             "mode": (["bins", "step", "unique", "cast"],),
                             "bins": _i(8, 1, 65536),
                             "step": _f(0.1, 0, 1e6, 0.01),
                             "connected": _b(True),
                             "connectivity": (["8", "4"],),
                             "out_layer": _s("id")}}

    def run(self, cop, layer, mode, bins, step, connected, connectivity,
            out_layer):
        return _sv.segment_by_value(cop, layer, mode, bins, step, connected,
                                    int(connectivity), out_layer)


@_node
class PCG_COPBoundingRect:
    """
    Maps to: Bounding Rectangle. The bounding rectangle of a mask (Per ID: one per id), outputting a filled
    layer + a JSON report (pixel range and uv range).
    """
    RETURN_TYPES = (COP, "STRING")
    RETURN_NAMES = ("cop", "rects")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("mask"),
                             "threshold": _f(0.5, -1e6, 1e6, 0.01),
                             "per_id": _b(False), "padding": _i(0, 0, 4096),
                             "out_layer": _s("rect")}}

    def run(self, cop, layer, threshold, per_id, padding, out_layer):
        return _sv.bounding_rect(cop, layer, threshold, per_id, padding,
                                 out_layer)


@_node
class PCG_COPSelect:
    """
    Maps to: Compare and Blend. Compares layers A and B per pixel and picks one (or blends smoothly by Softness):
    A larger / A smaller / brighter / darker / closer to Value / Key Layer > Value.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "a_layer": _s("A"),
                             "b_layer": _s("B"),
                             "op": (list(_sv.COMPARE_OPS),),
                             "value": _f(0.5, -1e6, 1e6, 0.01),
                             "key_layer": _s(),
                             "softness": _f(0.0, 0, 1e6, 0.01),
                             "out_layer": _s("result"),
                             "mask_layer": _s("select_mask")}}

    def run(self, cop, a_layer, b_layer, op, value, key_layer, softness,
            out_layer, mask_layer):
        return (_sv.compare_blend(cop, a_layer, b_layer, op, value,
                                  key_layer, softness, out_layer,
                                  mask_layer),)


@_node
class PCG_COPReactionDiffusion:
    """
    Maps to: Reaction-Diffusion Block Begin / End, Turing Patterns. One node runs
    Steps steps; the state is in Out Layer_u / _v (_g for Turing); connect the output back to keep running.
    Gray-Scott Presets are common (F, k) pairs; Feed / Kill Layer can give them per pixel.
    """
    RETURN_TYPES = (COP, "STRING")
    RETURN_NAMES = ("cop", "report")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "mode": (list(_sm.RD_MODES),),
            "preset": (list(_sm.RD_PRESETS),),
            "feed": _f(0.055, 0, 0.2, 0.001), "kill": _f(0.062, 0, 0.2, 0.001),
            "du": _f(1.0, 0, 1, 0.01), "dv": _f(0.5, 0, 1, 0.01),
            "dt": _f(1.0, 0.01, 1, 0.01),
            "steps": _i(1000, 0, 1000000),
            "seed_layer": _s(), "spots": _i(20, 0, 100000),
            "spot_radius": _f(4.0, 0.5, 1000, 0.5),
            "feed_layer": _s(), "kill_layer": _s(),
            "edge": (list(_sm.EDGES),),
            "scales": _sec("Turing", _s("32 16 8 4")),
            "step_size": _sec("Turing", _f(0.02, 0, 1, 0.005)),
            "rand_seed": _i(0, 0, 2 ** 31 - 1),
            "out_layer": _s("rd"), **_res(), "compute": _compute(),
            # pcg100 c7: Houdini Reaction-Diffusion Block End (defaults = old behaviour)
            "maginu_alpha": _f(1.0, -1e3, 1e3, 0.01),
            "maginu_beta": _f(0.5, -1e3, 1e3, 0.01),
            "maginu_gamma": _f(1.5, -1e3, 1e3, 0.01),
            "scale_multiplier": _f(1.0, 1e-4, 1e4, 0.05),
            "boundary_layer": _s(), "invert_boundary": _b(False),
            "boundary_threshold": _f(0.0, -1e6, 1e6, 0.01),
            "boundary_smoothing": _f(0.0, 0, 1024, 0.1),
            "invert_output": _b(False), "normalize_model": _b(False),
            "use_clamp_min": _b(False), "clamp_min": _f(0.0, -1e6, 1e6, 0.01),
            "use_clamp_max": _b(False), "clamp_max": _f(1.0, -1e6, 1e6, 0.01)},
            "optional": {"cop": (COP,)}}

    def run(self, mode, preset, feed, kill, du, dv, dt, steps, seed_layer,
            spots, spot_radius, feed_layer, kill_layer, edge, scales,
            step_size, rand_seed, out_layer, resolution_x, resolution_y,
            compute="auto", maginu_alpha=1.0, maginu_beta=0.5,
            maginu_gamma=1.5, scale_multiplier=1.0, boundary_layer="",
            invert_boundary=False, boundary_threshold=0.0,
            boundary_smoothing=0.0, invert_output=False,
            normalize_model=False, use_clamp_min=False, clamp_min=0.0,
            use_clamp_max=False, clamp_max=1.0, cop=None):
        o, r = _sm.reaction_diffusion(cop, mode, preset, feed, kill, du, dv,
                                      dt, steps, seed_layer, spots,
                                      spot_radius, feed_layer, kill_layer,
                                      edge, scales, step_size, rand_seed,
                                      out_layer, resolution_x, resolution_y,
                                      compute, maginu_alpha, maginu_beta,
                                      maginu_gamma, scale_multiplier,
                                      boundary_layer, invert_boundary,
                                      boundary_threshold, boundary_smoothing,
                                      invert_output, normalize_model,
                                      use_clamp_min, clamp_min,
                                      use_clamp_max, clamp_max)
        return (o, _rep(r))


@_node
class PCG_COPTuringPatterns:
    """
    Maps to: Turing Patterns (Houdini 22 semantics, pcg100 c7). Repeatedly "blurs + sharpens" a layer
    (unsharp mask with the same radius, then clamped to 0~1), growing stripes / spots while keeping the original's large forms. Filter /
    Units / Radius / Scale / Power / Gain / Read Pixels outside Image follow Houdini. The old
    Reaction Diffusion's turing mode is McCabe's multi-scale algorithm (a different thing), kept unchanged.
    The formula is our own, see filtersim.turing_patterns.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,), "layer": _s("C"), "out_layer": _s(),
            "filter": (list(_fsim.TURING_FILTERS), {"default": "gaussian"}),
            "read_outside": _b(False),
            "border": (list(_fsim.CONV_BORDERS),),
            "units": (list(_fsim.TURING_UNITS), {"default": "pixels"}),
            "iterations": _i(10, 0, 10000),
            "radius": _f(4.0, 0, 1e4, 0.1),
            "power": _f(2.0, 0, 1e3, 0.05),
            "gain": _f(1.0, -1e3, 1e3, 0.01),
            "scale": _s("1 1"),
            "mask": _f(1.0, 0, 1, 0.01), "mask_layer": _s()}}

    def run(self, cop, layer, out_layer, filter, read_outside, border,  # noqa: A002
            units, iterations, radius, power, gain, scale, mask, mask_layer):
        return (_fsim.turing_patterns(cop, layer, out_layer, filter,
                                      read_outside, border, units, iterations,
                                      radius, power, gain, scale, mask,
                                      mask_layer),)


@_node
class PCG_COPRipple:
    """
    Maps to: Ripple Block Begin / End. 2D wave equation (leapfrog), Speed ≤ 0.707 pixels/step.
    Source Layer is the initial displacement (or continuously driven with Drive Frequency), Obstacle Layer is walls.
    The state is in Out Layer / _prev / _t; connect it back to continue.
    """
    RETURN_TYPES = (COP, "STRING")
    RETURN_NAMES = ("cop", "report")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "source_layer": _s("mask"), "obstacle_layer": _s(),
            "speed": _f(0.5, 0, 0.707, 0.01),
            "damping": _f(0.0, 0, 1, 0.001),
            "steps": _i(100, 0, 1000000),
            "drive_frequency": _f(0.0, 0, 0.5, 0.005),
            "drive_amplitude": _f(1.0, -1e6, 1e6, 0.01),
            "edge": (list(_sm.RIPPLE_EDGES),),
            "absorb_width": _i(16, 1, 4096),
            "out_layer": _s("ripple"), **_res(), "compute": _compute()},
            "optional": {"cop": (COP,)}}

    def run(self, source_layer, obstacle_layer, speed, damping, steps,
            drive_frequency, drive_amplitude, edge, absorb_width, out_layer,
            resolution_x, resolution_y, compute="auto", cop=None):
        if cop is None and str(source_layer).strip():
            source_layer = ""
        o, r = _sm.ripple(cop, source_layer, obstacle_layer, speed, damping,
                          steps, drive_frequency, drive_amplitude, edge,
                          absorb_width, out_layer, resolution_x, resolution_y,
                          compute)
        return (o, _rep(r))


@_node
class PCG_COPFlowSolve:
    """
    Maps to: Flow Block Begin / End, Flow Project Non-Divergent Multigrid.
    project: projects a 2-channel velocity layer to be divergence-free; simulate: stable fluids (add forces →
    advect → project → advect density). Velocity in pixels/step. wrap uses an exact FFT projection, clamp
    is walls (mirror extension + FFT, also exact; Tolerance no longer has an effect, kept for old workflow compatibility).
    """
    RETURN_TYPES = (COP, "STRING")
    RETURN_NAMES = ("cop", "report")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "velocity_layer": _s("vel"),
                             "density_layers": _s("density"),
                             "mode": (list(_sm.FLOW_MODES),),
                             "steps": _i(10, 0, 100000),
                             "dt": _f(1.0, 0, 100, 0.05),
                             "force_layer": _s(),
                             "force_scale": _f(1.0, -1e6, 1e6, 0.01),
                             "dissipation": _f(0.0, 0, 1, 0.001),
                             "edge": (list(_sm.EDGES),),
                             "tolerance": _f(1e-8, 1e-14, 1, 1e-9),
                             "compute": _compute()}}

    def run(self, cop, velocity_layer, density_layers, mode, steps, dt,
            force_layer, force_scale, dissipation, edge, tolerance,
            compute="auto"):
        o, r = _sm.flow(cop, velocity_layer, density_layers, mode, steps, dt,
                        force_layer, force_scale, dissipation, edge,
                        tolerance, compute)
        return (o, _rep(r))


@_node
class PCG_COPOcean:
    """
    Maps to: Ocean Spectrum / Ocean Evaluate. Tessendorf's FFT ocean surface (Phillips spectrum,
    deep-water dispersion). Size is the image width in metres, Time in seconds. Outputs height, 3-channel displacement, normals, foam;
    naturally tiles seamlessly. The default Amplitude gives significant wave height ≈ 0.21·V²/g (fully developed sea).
    """
    RETURN_TYPES = (COP, "STRING")
    RETURN_NAMES = ("cop", "report")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "size": _f(100.0, 0.01, 1e6, 1),
            "wind_speed": _f(12.0, 0.01, 100, 0.1),
            "wind_direction": _f(0.0, -360, 360, 1),
            "amplitude": _f(8.8e-4, 0, 1, 1e-5),
            "align": _f(2.0, 0, 32, 0.5),
            "small_cut": _f(0.1, 0, 100, 0.01),
            "time": _f(0.0, -1e6, 1e6, 0.04),
            "choppiness": _f(1.0, 0, 10, 0.05),
            "foam_threshold": _f(0.3, 0.001, 2, 0.01),
            "rand_seed": _i(0, 0, 2 ** 31 - 1),
            "out_layer": _s("ocean"), **_res(),
            # pcg100 c7: Houdini Ocean Spectrum (defaults = old behaviour)
            "depth": _f(0.0, 0, 1e5, 0.5),
            "gravity": _f(9.81, 0.01, 1e3, 0.01),
            "spectrum_type": (list(_sm.OCEAN_SPECTRA),),
            "swell": _f(0.0, -10, 10, 0.05),
            "fetch_km": _f(100.0, 0.001, 1e5, 1),
            "directional_movement": _f(0.0, 0, 1, 0.01),
            "distribution": (list(_sm.OCEAN_DISTRIBUTIONS),
                             {"default": "gaussian"}),
            "loop_period": _f(0.0, 0, 1e6, 0.5)},
            "optional": {"cop": (COP,)}}

    def run(self, size, wind_speed, wind_direction, amplitude, align,
            small_cut, time, choppiness, foam_threshold, rand_seed,
            out_layer, resolution_x, resolution_y, depth=0.0, gravity=9.81,
            spectrum_type="phillips", swell=0.0, fetch_km=100.0,
            directional_movement=0.0, distribution="gaussian",
            loop_period=0.0, cop=None):
        o, r = _sm.ocean(cop, size, wind_speed, wind_direction, amplitude,
                         align, small_cut, time, choppiness, foam_threshold,
                         rand_seed, out_layer, resolution_x, resolution_y,
                         depth, gravity, spectrum_type, swell, fetch_km,
                         directional_movement, distribution, loop_period)
        return (o, _rep(r))


# ═══════════════════════════════════════════════════════ Batch E: UV / tiling / SDF / ID
_ux = _cop.uvx


@_node
class PCG_COPUVMap:
    """
    Maps to: UV Map / UV Map by ID. identity: the uv of each pixel centre (scalable, rotatable,
    translatable); by_id: each id's bounding box mapped to 0~1 individually (stretch fills / fit keeps aspect) --
    giving each segmented piece a complete texture of its own.

    pcg100 c6 adds Houdini's UV Space (Texture / Image / Pixel), U/V Border ·
    Shift · Cycles, the uvscale output, and UV Map by ID's Mode (Center / Minimum /
    Maximum / Size), Auto Scale, Zero Negative IDs, islands by connected piece. Defaults are all the old
    behaviour (Border defaults to Extend = no folding); details in uvx.uv_map.
    """
    @classmethod
    def INPUT_TYPES(cls):
        _cs = _cop.coordspace
        return {"required": {"mode": (list(_ux.UV_MAP_MODES),),
                             "id_layer": _s("id"),
                             "fit": (list(_ux.FIT_MODES)[::-1],),
                             "scale": _s("1 1"), "offset": _s("0 0"),
                             "rotate": _f(0.0, -3600, 3600, 1),
                             "out_layer": _s("uv"), **_res(),
                             "uv_space": (list(_cs.SPACES),),
                             "u_border": (list(_cs.BORDERS), {"default": "extend"}),
                             "u_shift": _f(0.0, -1e6, 1e6, 0.01),
                             "u_cycles": _f(1.0, -1e6, 1e6, 0.01),
                             "v_border": (list(_cs.BORDERS), {"default": "extend"}),
                             "v_shift": _f(0.0, -1e6, 1e6, 0.01),
                             "v_cycles": _f(1.0, -1e6, 1e6, 0.01),
                             "uvscale_layer": _s(""),
                             "id_mode": (list(_ux.ID_UV_MODES),),
                             "auto_scale": _b(True),
                             "zero_negative_ids": _b(True),
                             "connected": _b(False)},
                "optional": {"cop": (COP,)}}

    def run(self, mode, id_layer, fit, scale, offset, rotate, out_layer,
            resolution_x, resolution_y, uv_space="texture", u_border="extend",
            u_shift=0.0, u_cycles=1.0, v_border="extend", v_shift=0.0,
            v_cycles=1.0, uvscale_layer="", id_mode="uv_map", auto_scale=True,
            zero_negative_ids=True, connected=False, cop=None):
        return (_ux.uv_map(cop, mode, id_layer, fit, scale, offset, rotate,
                           out_layer, resolution_x, resolution_y, uv_space,
                           u_border, u_shift, u_cycles, v_border, v_shift,
                           v_cycles, uvscale_layer, id_mode, auto_scale,
                           zero_negative_ids, connected),)


@_node
class PCG_COPUVSample:
    """
    Maps to: UV Sample / Sphere Sample. Samples Source by a coordinate layer: uv (2 channels),
    latlong (3-channel direction → equirectangular environment map, Y up), mirror_ball (mirror ball photo).
    Without Source it samples itself.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "uv_layer": _s("uv"),
                             "source_layer": _s("C"),
                             "mode": (list(_ux.SAMPLE_MODES),),
                             "border": _bd("wrap"),
                             "out_layer": _s("sampled")},
                "optional": {"source": (COP,)}}

    def run(self, cop, uv_layer, source_layer, mode, border, out_layer,
            source=None):
        return (_ux.uv_sample(cop, source, uv_layer, source_layer, mode,
                              border, out_layer),)


@_node
class PCG_COPUVTransform:
    """Maps to: UV Transform. Transforms uv values (scale about Pivot → rotate → translate); Wrap takes the fractional part."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("uv"),
                             "translate": _s("0 0"),
                             "rotate": _f(0.0, -3600, 3600, 1),
                             "scale": _s("1 1"), "pivot": _s("0.5 0.5"),
                             "wrap": _b(False), "out_layer": _s()}}

    def run(self, cop, layer, translate, rotate, scale, pivot, wrap,
            out_layer):
        return (_ux.uv_transform(cop, layer, translate, rotate, scale, pivot,
                                 wrap, out_layer),)


@_node
class PCG_COPUVInverse:
    """
    Maps to: UV Inverse. The uv layer is an "output → source uv" mapping; this inverts it to "source → output uv": splatting +
    push-pull hole filling, plus a coverage _mask. Source Res 0 0 = same resolution.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("uv"),
                             "source_res": _s("0 0"), "fill": _b(True),
                             "out_layer": _s("uv_inverse")}}

    def run(self, cop, layer, source_res, fill, out_layer):
        return (_ux.uv_inverse(cop, layer, source_res, fill, out_layer),)


@_node
class PCG_COPPolar:
    """
    Maps to: UV to Polar / Polar to UV. to_polar: unrolls a ring into a horizontal strip (u = angle, v =
    radius); from_polar: rolls the strip back into a ring. The two are inverses, keeping aspect by the short side.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "direction": (list(_ux.POLAR_DIRS),),
                             "center": _s("0.5 0.5"),
                             "radius": _f(0.5, 0.001, 100, 0.01),
                             "angle": _f(0.0, -360, 360, 1),
                             "border": _bd()}}

    def run(self, cop, layers, direction, center, radius, angle, border):
        return (_ux.polar(cop, layers, direction, center, radius, angle,
                          border),)


_csp = _cop.coordspace


@_node
class PCG_COPPolarCoords:
    """
    Maps to: UV to Polar / Polar to UV (new in pcg100 c6). These two Houdini nodes only convert
    the **coordinate values** stored in pixels (Cartesian uv ↔ angle / length) without moving pixels; our original COP
    Polar resamples the whole image in polar coordinates (which is the combined effect of UV Map → this → UV Sample),
    so per [C] it's a separate node and COP Polar is unchanged.

    uv_to_polar: uv layer → two single-channel layers angle and length. polar_to_uv: angle / length
    layers (empty layer name = use the Angle / Length constants) → uv layer. Angle 0 = +u, counter-clockwise; output lies in
    [0, one full turn). Origin is our addition (Houdini fixes it at uv = 0).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,),
                             "direction": (list(_csp.POLAR_DIRS),),
                             "angle_units": (list(_csp.ANGLE_UNITS),
                                             {"default": "circles"}),
                             "uv_layer": _s("uv"),
                             "angle_layer": _s("angle"),
                             "length_layer": _s("length"),
                             "angle": _f(0.0, -1e6, 1e6, 0.01),
                             "length": _f(1.0, -1e6, 1e6, 0.01),
                             "origin": _s("0 0")}}

    def run(self, cop, direction, angle_units, uv_layer, angle_layer,
            length_layer, angle, length, origin):
        return (_csp.polar_coords(cop, direction, angle_units, uv_layer,
                                  angle_layer, length_layer, angle, length,
                                  origin),)


@_node
class PCG_COPSpaceTransform:
    """
    Maps to: Space Transform (new in pcg100 c6). Converts coordinate values stored in a layer between Buffer / Pixel /
    Texture / Image / World; the source space is interpreted at src_ref's resolution, the target at
    dst_ref's (cop's own when not connected). Position is affine, Vector uses only the linear part.

    Not the same as COP Vector Transform (rotate / scale / matrix / tangent space), hence a
    separate node. We have no pixel scale and no camera: Buffer = Pixel, World = Image,
    the 3rd channel is kept as is.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("uv"),
                             "vector_type": (list(_csp.VECTOR_TYPES),),
                             "src_space": (list(_csp.XSPACES),
                                           {"default": "texture"}),
                             "dst_space": (list(_csp.XSPACES),
                                           {"default": "image"}),
                             "out_layer": _s()},
                "optional": {"src_ref": (COP,), "dst_ref": (COP,)}}

    def run(self, cop, layer, vector_type, src_space, dst_space, out_layer,
            src_ref=None, dst_ref=None):
        return (_csp.space_transform(cop, layer, vector_type, src_space,
                                     dst_space, out_layer, src_ref, dst_ref),)


@_node
class PCG_COPPositionMap:
    """
    Maps to: Position Map (new in pcg100 c6). Each pixel stores a 3D position (a rest position for 3D
    noise); per axis (P + Shift) × Cycles is folded back into [−1, 1]³ by Border. We have no
    camera: Position = (image x, image y, 0), View Direction = (0, 0, −1); Camera
    Origin is not done. The Render Pass it used to point to is the geometry render-pass generator, a different thing.
    """
    @classmethod
    def INPUT_TYPES(cls):
        bd = (list(_csp.BORDERS), {"default": "extend"})
        req = {"source_position": (list(_csp.SOURCE_POSITIONS),)}
        for ax in "xyz":
            req[f"{ax}_border"] = bd
            req[f"{ax}_shift"] = _f(0.0, -1e6, 1e6, 0.01)
            req[f"{ax}_cycles"] = _f(1.0, -1e6, 1e6, 0.01)
        req["out_layer"] = _s("pos")
        req.update(_res())
        return {"required": req, "optional": {"size_ref": (COP,)}}

    def run(self, source_position, x_border, x_shift, x_cycles, y_border,
            y_shift, y_cycles, z_border, z_shift, z_cycles, out_layer,
            resolution_x, resolution_y, size_ref=None):
        return (_csp.position_map(size_ref, source_position, x_border, x_shift,
                                  x_cycles, y_border, y_shift, y_cycles,
                                  z_border, z_shift, z_cycles, out_layer,
                                  resolution_x, resolution_y),)


from .geo.cop import warp3d as _w3                      # noqa: E402
from .geo import ops as _gops                            # noqa: E402


def _flt(default="bilinear"):
    return (list(_w3.FILTERS), {"default": default})


@_node
class PCG_COPSphereSample:
    """
    Maps to: Sphere Sample (new in pcg100 c6). Wraps source onto a sphere as a lat-long map and shoots it with the default camera:
    Celestial Sphere on = an infinitely distant celestial sphere (only affected by Rotate, mask all 1); off = a transformable unit
    sphere, mask = rays hitting the sphere. The latlong mode of the old COP UV Sample is "lookup by direction layer", a different thing.
    We have no camera metadata: the camera looks along −Z, and with perspective sits at (0, 0, Camera Distance) (a parameter we added).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"source": (COP,), "source_layer": _s("C"),
                             "filter": _flt(),
                             "xform_order": (list(_gops.XFORM_ORDERS),),
                             "rotate_order": (list(_gops.ROTATE_ORDERS),),
                             "celestial": _b(False),
                             "projection": (list(_w3.PROJECTIONS),),
                             "translate": _s("0 0 0"), "rotate": _s("0 0 0"),
                             "scale": _s("1 1 1"),
                             "uniform_scale": _f(1.0, -1e6, 1e6, 0.01),
                             "camera_distance": _f(2.0, 1e-6, 1e6, 0.1),
                             "out_layer": _s("transform"),
                             "mask_layer": _s("mask"), **_res()},
                "optional": {"size_ref": (COP,)}}

    def run(self, source, source_layer, filter, xform_order, rotate_order,  # noqa: A002
            celestial, projection, translate, rotate, scale, uniform_scale,
            camera_distance, out_layer, mask_layer, resolution_x,
            resolution_y, size_ref=None):
        return (_w3.sphere_sample(size_ref, source, source_layer, filter,
                                  xform_order, rotate_order, celestial,
                                  projection, translate, rotate, scale,
                                  uniform_scale, camera_distance, out_layer,
                                  mask_layer, resolution_x, resolution_y),)


@_node
class PCG_COPTransform3D:
    """
    Maps to: Transform 3D (new in pcg100 c6). The layer is treated as a rectangle on z = 0, placed into 3D by Houdini's full transform
    (Transform / Rotate Order, Translate / Rotate / Scale / Shear / Uniform Scale, Pivot
    Translate / Rotate, Invert), then shot back onto the original raster with the default camera (orthographic; Perspective Camera on = perspective)
    -- i.e. Houdini's mode with Rasterize on. The old COP Corner Pin is a four-corner mapping,
    a different thing. "Change only metadata without producing pixels" and Crop to Content are not done (we have no data window).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "xform_order": (list(_gops.XFORM_ORDERS),),
                             "rotate_order": (list(_gops.ROTATE_ORDERS),),
                             "translate": _s("0 0 0"), "rotate": _s("0 0 0"),
                             "scale": _s("1 1 1"), "shear": _s("0 0 0"),
                             "uniform_scale": _f(1.0, -1e6, 1e6, 0.01),
                             "pivot": _s("0 0 0"), "pivot_rotate": _s("0 0 0"),
                             "invert": _b(False), "perspective": _b(False),
                             "border": (list(_w3.XFORM_BORDERS),),
                             "filter": _flt("box"),
                             "camera_distance": _f(2.0, 1e-6, 1e6, 0.1)}}

    def run(self, cop, layers, xform_order, rotate_order, translate, rotate,
            scale, shear, uniform_scale, pivot, pivot_rotate, invert,
            perspective, border, filter, camera_distance):  # noqa: A002
        return (_w3.transform3d(cop, layers, xform_order, rotate_order,
                                translate, rotate, scale, shear, uniform_scale,
                                pivot, pivot_rotate, invert, perspective,
                                border, filter, camera_distance),)


def _just():
    return (list(_w3.JUSTIFY), {"default": "center"})


@_node
class PCG_COPAlignWindow:
    """
    Maps to: Align (new in pcg100 c6). Aligns source's window by Justify X/Y → Goal X/Y to the reference
    window (size_ref, itself when not connected) or the rectangle given by Target Point / Size, optionally Scale to Fit, then adds
    Offset (image space), rasterised onto the reference image's grid. The old COP Align is "fit the whole image into the reference resolution"
    (stretch / fit / fill), a different thing, kept. We have no data window, so Data / Display are one.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"source": (COP,), "layers": _s(),
                             "justify_with": (list(_w3.ALIGN_TARGETS),),
                             "units": (list(_w3.TARGET_UNITS),),
                             "target_point": _s("0 0"), "target_size": _s("2 2"),
                             "justify_x": _just(), "justify_y": _just(),
                             "goal_x": (list(_w3.GOALS),),
                             "goal_y": (list(_w3.GOALS),),
                             "offset": _s("0 0"), "scale_to_fit": _b(False),
                             "uniform_scale": _b(True),
                             "scale_axis": (list(_w3.SCALE_AXES),),
                             "filter": _flt()},
                "optional": {"size_ref": (COP,)}}

    def run(self, source, layers, justify_with, units, target_point,
            target_size, justify_x, justify_y, goal_x, goal_y, offset,
            scale_to_fit, uniform_scale, scale_axis, filter, size_ref=None):  # noqa: A002
        return (_w3.align_window(source, size_ref, layers, justify_with, units,
                                 target_point, target_size, justify_x,
                                 justify_y, goal_x, goal_y, offset,
                                 scale_to_fit, uniform_scale, scale_axis,
                                 filter),)


@_node
class PCG_COPAlignPixels:
    """
    Maps to: Align Pixels (new in pcg100 c6). First snaps source to the reference image's pixel grid at the Side X/Y point
    (1:1, no interpolation), then translates by whole pixels so the Justify edge lines up with the reference window / original window / Target
    Point. The result is in the reference image's raster. The old COP Align doesn't do this, kept.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"source": (COP,), "layers": _s(),
                             "side_x": (["min", "center", "max"],),
                             "side_y": (["min", "center", "max"],),
                             "justify_with": (list(_w3.PIXEL_TARGETS),),
                             "units": (list(_w3.TARGET_UNITS),
                                       {"default": "pixels"}),
                             "target_point": _s("0 0"),
                             "justify_x": _just(), "justify_y": _just(),
                             "goal_x": (list(_w3.GOALS),),
                             "goal_y": (list(_w3.GOALS),),
                             "offset": _s("0 0")},
                "optional": {"size_ref": (COP,)}}

    def run(self, source, layers, side_x, side_y, justify_with, units,
            target_point, justify_x, justify_y, goal_x, goal_y, offset,
            size_ref=None):
        return (_w3.align_pixels(source, size_ref, layers, side_x, side_y,
                                 justify_with, units, target_point, justify_x,
                                 justify_y, goal_x, goal_y, offset),)


@_node
class PCG_COPBend:
    """
    Maps to: Bend (new in pcg100 c6). Corners (four corners + tangent handles, a cubic-edged Coons patch) / Sides (four corners
    + edge midpoints) / Angle (bent into an arc along the capture direction). Positions are all in image space; each output pixel's
    source coordinate is solved by Newton iteration. The bend mode of the old COP Swirl is a bending distortion about the centre, matching none of these three, kept.
    """
    @classmethod
    def INPUT_TYPES(cls):
        v = _s
        return {"required": {"source": (COP,), "layers": _s(),
                             "mode": (list(_w3.BEND_MODES),),
                             "filter": _flt(),
                             "bottom_left": v("-1 -1"), "bottom_right": v("1 -1"),
                             "top_left": v("-1 1"), "top_right": v("1 1"),
                             "bl_u": v("0.6666667 0"), "bl_v": v("0 0.6666667"),
                             "br_u": v("-0.6666667 0"), "br_v": v("0 0.6666667"),
                             "tl_u": v("0.6666667 0"), "tl_v": v("0 -0.6666667"),
                             "tr_u": v("-0.6666667 0"), "tr_v": v("0 -0.6666667"),
                             "side_bottom": v("0 -1"), "side_top": v("0 1"),
                             "side_left": v("-1 0"), "side_right": v("1 0"),
                             "bend_angle": _f(45.0, -3600, 3600, 1),
                             "capture_origin": v("0 0"),
                             "capture_direction": v("0 1"),
                             "capture_length": _f(1.0, 1e-6, 1e6, 0.01),
                             "both_directions": _b(False),
                             "mask_layer": _s()},
                "optional": {"size_ref": (COP,)}}

    def run(self, source, layers, mode, filter, bottom_left, bottom_right,  # noqa: A002
            top_left, top_right, bl_u, bl_v, br_u, br_v, tl_u, tl_v, tr_u,
            tr_v, side_bottom, side_top, side_left, side_right, bend_angle,
            capture_origin, capture_direction, capture_length,
            both_directions, mask_layer, size_ref=None):
        return (_w3.bend(source, size_ref, layers, mode, filter, bottom_left,
                         bottom_right, top_left, top_right, bl_u, bl_v, br_u,
                         br_v, tl_u, tl_v, tr_u, tr_v, side_bottom, side_top,
                         side_left, side_right, bend_angle, capture_origin,
                         capture_direction, capture_length, both_directions,
                         mask_layer),)


@_node
class PCG_COPHexTile:
    """
    Maps to: Hex Tile. Each cell of a hexagonal grid gets a randomly offset, randomly rotated copy of the texture, three copies blended by barycentric
    weights (Mikkelsen 2022) -- breaking up tiling repetition. Larger Contrast gives narrower seams.
    Without Source it uses its own Layer. X/Y Res 0 = follow the input.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("C"),
                             "tiles": _f(4.0, 0.01, 1000, 0.1),
                             "rotation": _f(180.0, 0, 180, 1),
                             "contrast": _f(0.6, 0, 1, 0.01),
                             "rand_seed": _i(0, 0, 2 ** 31 - 1),
                             "out_layer": _s("hex"),
                             "xres": _i(0, 0, _cop.MAX_RES),
                             "yres": _i(0, 0, _cop.MAX_RES)},
                "optional": {"source": (COP,)}}

    def run(self, cop, layer, tiles, rotation, contrast, rand_seed,
            out_layer, xres, yres, source=None):
        return (_ux.hex_tile(cop, source, layer, tiles, rotation, contrast,
                             rand_seed, out_layer, xres, yres),)


@_node
class PCG_COPTriplanar:
    """
    Maps to: Triplanar / Triplanar UV / Triplanar Hex Tile. Uses per-pixel world position P and
    normal N (those two Render Pass layers) to project the texture along three axes, blended by |N|^Sharpness.
    With Hex on, each projection is also hex-tiled. If UV Layer is given a name, the dominant axis's projected uv is output too.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "p_layer": _s("P"),
                             "n_layer": _s("N"), "layer": _s("C"),
                             "scale": _f(1.0, 1e-6, 1e6, 0.01),
                             "sharpness": _f(4.0, 0, 64, 0.5),
                             "hex": _b(False),
                             "hex_rotation": _f(180.0, 0, 180, 1),
                             "rand_seed": _i(0, 0, 2 ** 31 - 1),
                             "out_layer": _s("triplanar"), "uv_layer": _s()},
                "optional": {"source": (COP,)}}

    def run(self, cop, p_layer, n_layer, layer, scale, sharpness, hex,  # noqa: A002
            hex_rotation, rand_seed, out_layer, uv_layer, source=None):
        return (_ux.triplanar(cop, source, p_layer, n_layer, layer, scale,
                              sharpness, hex, hex_rotation, rand_seed,
                              out_layer, uv_layer),)


@_node
class PCG_COPRetile:
    """
    Maps to: Retile. shuffle: cut into cells and randomly rearranged (optionally random 90° rotations / flips); seamless:
    cross-faded by distance to the edge with itself shifted by half the frame, making it tileable.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layers": _s(),
                             "mode": (list(_ux.RETILE_MODES),),
                             "counts": _s("4 4"), "rotate": _b(True),
                             "flip": _b(False),
                             "blend": _f(0.25, 0.001, 1, 0.01),
                             "rand_seed": _i(0, 0, 2 ** 31 - 1)}}

    def run(self, cop, layers, mode, counts, rotate, flip, blend, rand_seed):
        return (_ux.retile(cop, layers, mode, counts, rotate, flip, blend,
                           rand_seed),)


_SDF_ALL = list(_ux.SDF_OPS) + ["to_" + m for m in _ux.SDF_TO_MONO]


@_node
class PCG_COPSDFOps:
    """
    Maps to: SDF Blend / SDF to Mono. union / intersect / subtract (Smooth > 0 is the
    polynomial-smoothed rounded version), blend (shape morph), offset, onion (shell); to_fill /
    to_outline / to_falloff turn an SDF into a mask (Width by Units).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "a_layer": _s("sdf"),
                             "b_layer": _s(), "op": (_SDF_ALL,),
                             "smooth": _f(0.0, 0, 1e6, 0.005),
                             "t": _f(0.5, -10, 10, 0.01),
                             "amount": _f(0.0, -1e6, 1e6, 0.005),
                             "width": _f(0.01, 0, 1e6, 0.001),
                             "units": (["uv", "pixels"],),
                             "out_layer": _s("sdf_out")}}

    def run(self, cop, a_layer, b_layer, op, smooth, t, amount, width, units,
            out_layer):
        if op.startswith("to_"):
            return (_ux.sdf_to_mono(cop, a_layer, op[3:], width, units,
                                    out_layer),)
        return (_ux.sdf_ops(cop, a_layer, b_layer, op, smooth, t, amount,
                            out_layer),)


@_node
class PCG_COPIDConvert:
    """
    Maps to: ID to Mask / ID to Mono / ID to SDF. Ids takes "1 3 5-8". sdf: with Ids given
    it's the signed distance of the selected region; empty gives an image combining each piece's distance to "other ids".
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("id"),
                             "mode": (list(_ux.ID_MODES),),
                             "ids": _s("1"), "invert": _b(False),
                             "normalize": _b(True), "out_layer": _s()}}

    def run(self, cop, layer, mode, ids, invert, normalize, out_layer):
        return (_ux.id_convert(cop, layer, mode, ids, invert, normalize,
                               out_layer),)


# ═══════════════════════════════════════════════════════ Batch F: geometry ↔ image / height fields / visualisation / sequences
_gi = _cop.geoimg
_hv = _cop.hfvis


@_node
class PCG_COPLayerToPoints:
    """
    Maps to: Layer to Points / Point Generate. pixels: one point per pixel (Stride decimates,
    Mask Layer filters); scatter: Count points scattered by Density Layer. Position is plane +
    world (consistent with HeightField to Mesh); Height Layer gives the axis out of the plane. Layers listed in Attribs
    are sampled into point attributes (C → Cd).
    """
    RETURN_TYPES = (GEO,)
    RETURN_NAMES = ("geo",)

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,),
                             "mode": (list(_gi.POINT_MODES),),
                             "mask_layer": _s(),
                             "threshold": _f(0.5, -1e6, 1e6, 0.01),
                             "stride": _i(1, 1, 4096),
                             "count": _i(1000, 0, 10000000),
                             "density_layer": _s(),
                             "height_layer": _s(),
                             "height_scale": _f(1.0, -1e6, 1e6, 0.01),
                             "attribs": _s("C"),
                             "plane": (list(_cop.stamp.PLANES),),
                             "world_size": _f(1.0, 1e-6, 1e9, 0.1),
                             "jitter": _f(0.0, 0, 1, 0.01),
                             "rand_seed": _i(0, 0, 2 ** 31 - 1),
                             # pcg100: Houdini Layer to Points' output attributes and toggles
                             "layer_attrib": _s(),
                             "index_attrib": _s(),
                             "set_positions": _b(True),
                             "ignore_minus_one": _b(True)}}

    def run(self, cop, mode, mask_layer, threshold, stride, count,
            density_layer, height_layer, height_scale, attribs, plane,
            world_size, jitter, rand_seed, layer_attrib="", index_attrib="",
            set_positions=True, ignore_minus_one=True):
        return (_gi.layer_to_points(cop, mode, mask_layer, threshold, stride,
                                    count, density_layer, height_layer,
                                    height_scale, attribs, plane, world_size,
                                    jitter, rand_seed, layer_attrib,
                                    index_attrib, set_positions,
                                    ignore_minus_one),)


@_node
class PCG_COPPointsFromBlobs:
    """
    Maps to: Points from Blobs. One point (centroid) per connected piece of the mask, with area / world_area /
    radius (equal-area circle radius, usable as pscale) / blob_id / bbox, and the in-piece mean of Value Layer.
    The second output is the piece count.
    """
    RETURN_TYPES = (GEO, "INT")
    RETURN_NAMES = ("geo", "count")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("mask"),
                             "threshold": _f(0.5, -1e6, 1e6, 0.01),
                             "connectivity": (["8", "4"],),
                             "min_area": _i(1, 1, 1 << 30),
                             "value_layer": _s(),
                             "plane": (list(_cop.stamp.PLANES),),
                             "world_size": _f(1.0, 1e-6, 1e9, 0.1),
                             "height_layer": _s(),
                             "height_scale": _f(1.0, -1e6, 1e6, 0.01)}}

    def run(self, cop, layer, threshold, connectivity, min_area, value_layer,
            plane, world_size, height_layer, height_scale):
        return _gi.points_from_blobs(cop, layer, threshold, int(connectivity),
                                     min_area, value_layer, plane, world_size,
                                     height_layer, height_scale)


@_node
class PCG_COPRasterizeCurves:
    """
    Maps to: Rasterize Curves / Layer from Curves / Mask from Curves. Each geometry
    prim is drawn as an anti-aliased polyline (Width pixels, multiplied per point by Width Attrib); Fill fills closed ones
    (even-odd rule); Attrib is interpolated along the lines into a layer.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,),
                             "width": _f(2.0, 0, 4096, 0.1),
                             "width_attrib": _s(), "fill": _b(False),
                             "attrib": _s(),
                             "plane": (list(_cop.stamp.PLANES),),
                             "mapping": (list(_cop.stamp.MAPPINGS),),
                             "world_size": _f(1.0, 1e-6, 1e9, 0.1),
                             "out_layer": _s("curves"), **_res()},
                "optional": {"cop": (COP,)}}

    def run(self, geo, width, width_attrib, fill, attrib, plane, mapping,
            world_size, out_layer, resolution_x, resolution_y, cop=None):
        return (_gi.rasterize_curves(cop, geo, width, width_attrib, fill,
                                     attrib, plane, mapping, world_size,
                                     out_layer, resolution_x,
                                     resolution_y),)


@_node
class PCG_COPRasterizeSplats:
    """
    Maps to: Rasterize GSplats. 3D Gaussian splats (P / scale / orient / Cd / opacity, defaults for missing ones)
    projected orthographically onto plane, alpha-composited front to back. Outputs RGB + _alpha. The second
    output is how many were drawn. No perspective and no SH -- for baking top views / textures.
    """
    RETURN_TYPES = (COP, "INT")
    RETURN_NAMES = ("cop", "count")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,),
                             "plane": (list(_cop.stamp.PLANES),),
                             "mapping": (list(_cop.stamp.MAPPINGS),),
                             "world_size": _f(1.0, 1e-6, 1e9, 0.1),
                             "scale_mult": _f(1.0, 0, 1e6, 0.01),
                             "opacity_mult": _f(1.0, 0, 1e6, 0.01),
                             "cutoff": _f(3.0, 0.5, 10, 0.1),
                             "background": _s("0 0 0"),
                             "out_layer": _s("C"), **_res()},
                "optional": {"cop": (COP,)}}

    def run(self, geo, plane, mapping, world_size, scale_mult, opacity_mult,
            cutoff, background, out_layer, resolution_x, resolution_y,
            cop=None):
        return _gi.rasterize_splats(cop, geo, plane, mapping, world_size,
                                    scale_mult, opacity_mult, cutoff,
                                    background, out_layer, resolution_x,
                                    resolution_y)


@_node
class PCG_COPBakeTextures:
    """
    Maps to: Bake Geometry Textures (2.0) / Bake Pre-Process. Bakes by the low-poly's uv: P, N,
    mask, primid, tangent, and point attributes listed in Attribs; with a high-poly connected, rays are cast along ±N, additionally outputting
    normal_ts (tangent-space normal, −1~1 unencoded), displacement (signed distance along N),
    high_xxx. Dilate is the number of texel rings uv islands are expanded outward. The second output is the report.
    """
    RETURN_TYPES = (COP, "STRING")
    RETURN_NAMES = ("cop", "report")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"low": (GEO,), **_res(),
                             "uv_attrib": _s("uv"), "attribs": _s(),
                             "high_attribs": _s(),
                             "max_distance": _f(0.0, 0, 1e9, 0.01),
                             "both_sides": _b(True),
                             "dilate": _i(4, 0, 1024),
                             # pcg100 c8: parameters of Houdini Bake Geometry Textures (2.0), defaults = old behaviour
                             "tracing_mode": (list(_gi.BAKE_TRACING),),
                             "face_culling": (list(_gi.BAKE_CULL),),
                             "visibility_culling": (list(_gi.BAKE_CULL),),
                             "ray_bias": _f(0.0, -1e6, 1e6, 0.001),
                             "sample_multiplier": _f(1.0, 0, 64, 0.1),
                             "normal_space": (list(_gi.BAKE_NSPACE),),
                             "world_normal": _b(False),
                             "world_normal_space": (list(_gi.BAKE_NSPACE),),
                             "position": _b(False),
                             "position_space": (list(_gi.BAKE_PSPACE),),
                             "bounding_box": (list(_gi.BAKE_BBOX),),
                             "occlusion": _b(False),
                             "occlusion_samples": _i(16, 1, 4096),
                             "occlusion_max_distance": _f(0.0, 0, 1e9, 0.01),
                             "height": _b(False),
                             "height_space": (list(_gi.BAKE_HSPACE),),
                             "inner_distance": _f(-0.1, -1e9, 1e9, 0.01),
                             "outer_distance": _f(0.1, -1e9, 1e9, 0.01),
                             "alpha": _b(False),
                             "alpha_mask_high": _b(False)},
                "optional": {"high": (GEO,), "cage": (GEO,)}}

    def run(self, low, resolution_x, resolution_y, uv_attrib, attribs,
            high_attribs, max_distance, both_sides, dilate,
            tracing_mode="surface_normal", face_culling="none", visibility_culling="none",
            ray_bias=0.0, sample_multiplier=1.0, normal_space="signed", world_normal=False,
            world_normal_space="signed", position=False, position_space="absolute",
            bounding_box="fit", occlusion=False, occlusion_samples=16,
            occlusion_max_distance=0.0, height=False, height_space="true_displacement",
            inner_distance=-0.1, outer_distance=0.1, alpha=False, alpha_mask_high=False,
            high=None, cage=None):
        o, r = _gi.bake_textures(low, high, resolution_x, resolution_y,
                                 uv_attrib, attribs, high_attribs,
                                 max_distance, both_sides, dilate,
                                 tracing_mode, cage, face_culling, visibility_culling,
                                 ray_bias, normal_space, world_normal, world_normal_space,
                                 position, position_space, bounding_box, occlusion,
                                 occlusion_samples, occlusion_max_distance,
                                 sample_multiplier, height, height_space, inner_distance,
                                 outer_distance, alpha, alpha_mask_high)
        return (o, json.dumps(r))


@_node
class PCG_COPLight:
    """
    Maps to: Light. Lights with tangent-space normals: a directional light (Azimuth / Elevation, same convention as Height to
    Shadow) or a point light (at Light Height directly above Position). Lambert +
    Blinn–Phong; with Shadows, Height Layer is used to compute cast shadows.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "normal_layer": _s("N"),
                             "albedo_layer": _s(), "height_layer": _s(),
                             "light_type": (list(_hv.LIGHT_TYPES),),
                             "azimuth": _f(135.0, -360, 360, 1),
                             "elevation": _f(45.0, 0, 90, 1),
                             "position": _s("0.5 0.5"),
                             "light_height": _f(0.5, 0, 100, 0.01),
                             "color": _s("1 1 1"),
                             "intensity": _f(1.0, 0, 1e6, 0.01),
                             "ambient": _f(0.1, 0, 10, 0.01),
                             "specular": _f(0.0, 0, 100, 0.01),
                             "shininess": _f(32.0, 1, 4096, 1),
                             "shadows": _b(False),
                             "strength": _f(1.0, -1e6, 1e6, 0.01),
                             "world_size": _f(1.0, 1e-6, 1e9, 0.1),
                             "out_layer": _s("lit")}}

    def run(self, cop, normal_layer, albedo_layer, height_layer, light_type,
            azimuth, elevation, position, light_height, color, intensity,
            ambient, specular, shininess, shadows, strength, world_size,
            out_layer):
        return (_hv.light(cop, normal_layer, albedo_layer, height_layer,
                          light_type, azimuth, elevation, position,
                          light_height, color, intensity, ambient, specular,
                          shininess, shadows, strength, world_size,
                          out_layer),)


@_node
class PCG_COPHFClip:
    """
    Maps to: HeightField Clip. Clamps height into [Min, Max]; Softness is a C¹ soft knee; also outputs
    _clipped (amount changed). The height layer defaults to C, consistent with the other terrain chain nodes.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("C"),
                             "mode": (list(_hv.CLIP_MODES)[::-1],),
                             "min": _f(0.0, -1e6, 1e6, 0.01),
                             "max": _f(1.0, -1e6, 1e6, 0.01),
                             "softness": _f(0.0, 0, 1e6, 0.005),
                             "mask_layer": _s(), "out_layer": _s()}}

    def run(self, cop, layer, mode, min, max, softness,  # noqa: A002
            mask_layer, out_layer):
        return (_hv.hf_clip(cop, layer, mode, min, max, softness, mask_layer,
                            out_layer),)


@_node
class PCG_COPHFProject:
    """
    Maps to: HeightField Project / HeightField Transform 3D. With geometry connected: casts rays straight down from above
    and projects onto the height field (replace / max / min / add); without: treats the height field itself as a mesh,
    transforms it in 3D and projects it back. The second output is the report.

    Project = Minimum Height projects the lowest surface layer; Max Projection Height > 0 only projects geometry within this
    height range; Mask / Mask Layer blend back to the original height; Output Projection Only outputs just the projection;
    giving Hitmask Layer a name outputs a hit mask.
    """
    RETURN_TYPES = (COP, "STRING")
    RETURN_NAMES = ("cop", "report")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("C"),
                             # Menu order is fixed: the four old items first (max is the default), pcg100 additions appended at the end
                             "mode": (["max", "min", "add", "replace", "blend",
                                       "multiply"],),
                             "strength": _f(1.0, -1e6, 1e6, 0.01),
                             "world_size": _f(1.0, 1e-6, 1e9, 0.1),
                             "translate": _s("0 0 0"), "rotate": _s("0 0 0"),
                             "scale": _s("1 1 1"),
                             "fill_value": _f(0.0, -1e6, 1e6, 0.01),
                             "out_layer": _s(),
                             # pcg100: Houdini HeightField Project's Project menu,
                             # Max Projection Height, Mask, Output Projection Only,
                             # hitmask output; Blend / Multiply appended at the end of the mode menu
                             "project": (list(_hv.PROJECT_PICKS),),
                             "max_height": _f(0.0, 0.0, 1e6, 0.01),
                             "mask": _f(1.0, 0.0, 1.0, 0.01),
                             "mask_layer": _s(),
                             "projection_only": _b(False),
                             "hitmask_layer": _s()},
                "optional": {"geo": (GEO,)}}

    def run(self, cop, layer, mode, strength, world_size, translate, rotate,
            scale, fill_value, out_layer, geo=None, project="maximum",
            max_height=0.0, mask=1.0, mask_layer="", projection_only=False,
            hitmask_layer=""):
        o, r = _hv.hf_project(cop, geo, layer, mode, strength, world_size,
                              translate, rotate, scale, fill_value, out_layer,
                              project, max_height, mask, mask_layer,
                              projection_only, hitmask_layer)
        return (o, json.dumps(r))


@_node
class PCG_COPStrata:
    """
    Maps to: HeightField Strata. Tilted rock strata: bedding plane = height + Tilt·(u, v) + noise, each layer
    with random hardness (hard layers have flat treads and steep risers), blended back by Strength. With Tilt, noise and randomness all 0 it's
    Terrace. Also outputs _id (layer number). Strata Offset shifts layer boundaries; Mask Layer multiplies Strength;
    Output Strata Only outputs just the strata displacement. Houdini's Strata is "1D noise laid out along tilted bedding planes,
    then combined into the height by Blend Mode", a different model from the "tilted terraces" here (see audit_notes).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("C"),
                             "spacing": _f(0.1, 1e-6, 1e6, 0.005),
                             "strength": _f(0.8, 0, 1, 0.01),
                             "sharpness": _f(0.7, 0, 0.999, 0.01),
                             "tilt": _s("0 0"),
                             "noise_amount": _f(0.0, -1e6, 1e6, 0.005),
                             "noise_frequency": _f(4.0, 0, 1e4, 0.1),
                             "hardness_random": _f(0.5, 0, 1, 0.01),
                             "rand_seed": _i(0, 0, 2 ** 31 - 1),
                             "out_layer": _s(),
                             # pcg100: Houdini Strata's Strata Offset / mask input /
                             # Output Strata Only. Defaults = old behaviour
                             "strata_offset": _f(0.0, -1e6, 1e6, 0.005),
                             "mask_layer": _s(),
                             "strata_only": _b(False)}}

    def run(self, cop, layer, spacing, strength, sharpness, tilt,
            noise_amount, noise_frequency, hardness_random, rand_seed,
            out_layer, strata_offset=0.0, mask_layer="", strata_only=False):
        return (_hv.strata(cop, layer, spacing, strength, sharpness, tilt,
                           noise_amount, noise_frequency, hardness_random,
                           rand_seed, out_layer, strata_offset, mask_layer,
                           strata_only),)


@_node
class PCG_COPVisualize:
    """
    Maps to: HeightField Visualize / Visualize Velocity. Height through a ramp (+ hillshade + contour lines);
    velocity: hsv (hue = direction) / lic (line integral convolution streaks) / arrows (arrow grid).
    The height mode also has Houdini's Mode (Clamped / Periodic / No Ramp) and Tint by (Height /
    Color / Mask: colour by another layer, hillshade and contours still by height). Houdini outputs coloured geometry;
    we output an image.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "layer": _s("C"),
                             "mode": (list(_hv.VIS_MODES),),
                             "ramp": (list(_hv.RAMPS),),
                             "lo": _f(0.0, -1e6, 1e6, 0.01),
                             "hi": _f(0.0, -1e6, 1e6, 0.01),
                             "contour_interval": _f(0.0, 0, 1e6, 0.005),
                             "hillshade": _f(0.5, 0, 1, 0.01),
                             "lic_length": _i(20, 1, 1000),
                             "arrow_spacing": _i(16, 2, 4096),
                             "scale": _f(1.0, 0, 1e6, 0.01),
                             "rand_seed": _i(0, 0, 2 ** 31 - 1),
                             "out_layer": _s("vis"),
                             # pcg100: Houdini HeightField Visualize's Mode (No /
                             # Clamped / Periodic Ramp) and Tint by. Defaults = old behaviour
                             "range_mode": (list(_hv.VIS_RANGE_MODES),),
                             "tint_by": (list(_hv.VIS_TINTS),),
                             "tint_layer": _s()}}

    def run(self, cop, layer, mode, ramp, lo, hi, contour_interval,
            hillshade, lic_length, arrow_spacing, scale, rand_seed,
            out_layer, range_mode="clamped", tint_by="height", tint_layer=""):
        return (_hv.visualize(cop, layer, mode, ramp, lo, hi,
                              contour_interval, hillshade, lic_length,
                              arrow_spacing, scale, rand_seed, out_layer,
                              range_mode, tint_by, tint_layer),)


@_node
class PCG_COPContactSheet:
    """Maps to: Contact Sheet. Lays a sequence out in a grid (first frame at the top left), optionally labelling frame numbers."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"seq": (COPSEQ,), "layer": _s("C"),
                             "columns": _i(0, 0, 1024),
                             "padding": _i(4, 0, 1024),
                             "background": _s("0 0 0"), "labels": _b(True),
                             "font": _s(), "label_size": _i(0, 0, 1024),
                             "scale": _f(1.0, 0.01, 16, 0.05)}}

    def run(self, seq, layer, columns, padding, background, labels, font,
            label_size, scale):
        return (_hv.contact_sheet(seq, layer, columns, padding, background,
                                  labels, font, label_size, scale),)


@_node
class PCG_COPWipe:
    """
    Maps to: Wipe. A → B transition (linear / radial / dissolve / crossfade); T 0 is all A,
    1 all B (bit-exact at both ends). When B's resolution differs it is resampled first.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"a": (COP,), "b": (COP,), "layer": _s("C"),
                             "mode": (list(_hv.WIPES),),
                             "t": _f(0.5, 0, 1, 0.01),
                             "angle": _f(0.0, -360, 360, 1),
                             "softness": _f(0.05, 0, 1, 0.005),
                             "center": _s("0.5 0.5"),
                             "rand_seed": _i(0, 0, 2 ** 31 - 1),
                             "out_layer": _s()}}

    def run(self, a, b, layer, mode, t, angle, softness, center, rand_seed,
            out_layer):
        return (_hv.wipe(a, b, layer, mode, t, angle, softness, center,
                         rand_seed, out_layer),)


@_node
class PCG_COPSequenceOps:
    """
    Maps to: Reverse / Time Shift / Time Loop / Time Blend / Sequence Blend. Reverse playback,
    shift all frames (hold / loop), make seamless loops (cross-fading the tail with the head), resample to N frames
    (linear interpolation), blend frame by frame with another sequence.
    """
    RETURN_TYPES = (COPSEQ, "INT")
    RETURN_NAMES = ("seq", "frames")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"seq": (COPSEQ,),
                             "op": (list(_hv.SEQ_OPS),),
                             "offset": _i(0, -100000, 100000),
                             "edge": (["hold", "loop"],),
                             "frames": _i(24, 1, 100000),
                             "blend": _i(4, 1, 100000),
                             "weight": _f(0.5, 0, 1, 0.01)},
                "optional": {"other": (COPSEQ,)}}

    def run(self, seq, op, offset, edge, frames, blend, weight, other=None):
        r = _hv.seq_ops(seq, op, offset, edge, frames, blend, other, weight)
        return (r, len(r))


# ═══════════════════════════════════════════════════════ pcg77 height-field tiling
from .geo.cop import tiles as _tiles                 # noqa: E402


@_node
class PCG_COPTileSplit:
    """
    Maps to: HeightField Tile Split. Splits into Columns × Rows tiles, each carrying Overlap extra pixels on every side
    (not at the image border), output as a sequence (lower-left tile first, horizontal then vertical). Tiles can be processed separately, then joined back with Tile
    Splice.
    """
    RETURN_TYPES = (COPSEQ, "INT")
    RETURN_NAMES = ("seq", "tiles")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "columns": _i(2, 1, 256),
                             "rows": _i(2, 1, 256), "overlap": _i(16, 0, 4096)}}

    def run(self, cop, columns, rows, overlap):
        r = _tiles.tile_split(cop, columns, rows, overlap)
        return (r, len(r))


@_node
class PCG_COPTileSplice:
    """
    Maps to: HeightField Tile Splice. Joins tiles split by Tile Split (possibly processed separately) back with the same
    Columns / Rows / Overlap: smoothly blended in the overlap bands (smoothstep, weights summing to 1 everywhere);
    Feather controls the share of Overlap taken by the transition band, 0 = hard join. Unmodified, the joined result is identical per pixel to the original.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"seq": (COPSEQ,), "columns": _i(2, 1, 256),
                             "rows": _i(2, 1, 256), "overlap": _i(16, 0, 4096),
                             "feather": _f(1.0, 0.0, 1.0, 0.05)}}

    def run(self, seq, columns, rows, overlap, feather):
        return (_tiles.tile_splice(seq, columns, rows, overlap, feather),)


# ═══════════════════════════════════════════════════════════ Registration
# ═══════════════════════════════════════════════════════ pcg100 c8: geometry ↔ layers
from .geo.cop import geolayer as _gl                    # noqa: E402


@_node
class PCG_COPPointGenerate:
    """
    Maps to: Point Generate (new in pcg100 c8). Adds points to a point cloud: count from parameters (Number of Points +
    Points per Second × Time Step, the fractional part kept randomly by Seed) / per-point Count attribute (copies source points,
    attributes matched by Copy Attributes come along) / detail Count attribute. The Layer to Points it used to point to is
    "points from a layer", a different thing. We have no simulation timestep; Time Step is a parameter.
    """
    RETURN_TYPES = (GEO,)
    RETURN_NAMES = ("points",)

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"method": (list(_gl.PG_METHODS),),
                             "number_of_points": _i(10, 0, 100000000),
                             "points_per_second": _f(0.0, 0, 1e9, 1.0),
                             "time_step": _f(1.0 / 24, 0, 1e6, 0.001),
                             "rand_seed": _i(0, 0, 2 ** 31 - 1),
                             "count_attrib": _s("count"),
                             "copy_attribs": _s("*"),
                             "append_points": _b(True)},
                "optional": {"points": (GEO,), "ref": (GEO,)}}

    def run(self, method, number_of_points, points_per_second, time_step, rand_seed,
            count_attrib, copy_attribs, append_points, points=None, ref=None):
        return (_gl.point_generate(points, ref, method, number_of_points,
                                   points_per_second, time_step, rand_seed,
                                   count_attrib, copy_attribs, append_points),)


@_node
class PCG_COPLayerFromAttrib:
    """
    Maps to: Layer from Attribute (new in pcg100 c8). The k-th element of the attribute goes into the k-th pixel (Data
    Ordering sets the order, or connect an index image to specify per pixel which element to read). With Resize Layer on, resolution is set by the element count
    (Power of 2 Square / Square / Single Row / Single Column). The Texture Render it used to point to
    is "render a textured mesh through a camera", a different thing.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,),
                             "attrib": _s("Cd"),
                             "attrib_class": (list(_gl.LFA_CLASSES),),
                             "data_ordering": (list(_gl.LFA_ORDERS),),
                             "resize_layer": _b(False),
                             "resize_shape": (list(_gl.LFA_SHAPES),),
                             "index_layer": _s(),
                             "out_layer": _s("attrib"), **_res()},
                "optional": {"size_ref": (COP,), "index": (COP,)}}

    def run(self, geo, attrib, attrib_class, data_ordering, resize_layer, resize_shape,
            index_layer, out_layer, resolution_x, resolution_y, size_ref=None, index=None):
        return (_gl.layer_from_attrib(geo, attrib, attrib_class, data_ordering,
                                      resize_layer, resize_shape, out_layer, size_ref,
                                      index, index_layer, resolution_x, resolution_y),)


@_node
class PCG_COPGeoToLayer:
    """
    Maps to: Geometry to Layer (new in pcg100 c8). Volume prims → layers: a 3D volume is sliced by Slice (XY / YZ /
    ZX, plane position Slice Offset), one voxel per pixel; Outputs lists which to convert (names / indices /
    composites like vel.* into multiple channels), empty = all. With Optional, missing ones are filled with Default Value at size_ref.
    The Render Pass it used to point to is camera rasterisation, a different thing. No VDB and no camera prims.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,),
                             "outputs": _s(),
                             "out_type": (list(_gl.GTL_TYPES),),
                             "slice": (list(_gl.GTL_SLICES),),
                             "slice_offset": _f(0.0, -1e9, 1e9, 0.01),
                             "optional": _b(False),
                             "default_value": _s("0")},
                "optional": {"size_ref": (COP,)}}

    def run(self, geo, outputs, out_type, slice, slice_offset, optional, default_value,
            size_ref=None):
        return (_gl.geo_to_layer(geo, outputs, out_type, slice, slice_offset, optional,
                                 default_value, size_ref),)


@_node
class PCG_COPSequenceClips:
    """
    Maps to: Sequence (new in pcg100 c8). Clips gives "start frame frame count" per segment (semicolon separated); segment k is taken from input k,
    and when there are more segments than inputs the last input is used; segments are joined end to end, and Output Start Frame moves the overall start. The
    Sequence Import it used to point to is IMAGE → sequence, a different thing.
    """
    RETURN_TYPES = (COPSEQ, "INT")
    RETURN_NAMES = ("seq", "frames")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"seq": (COPSEQ,),
                             "clips": _s(),
                             "output_start_frame": _i(0, -100000, 100000)},
                "optional": {"seq2": (COPSEQ,), "seq3": (COPSEQ,), "seq4": (COPSEQ,)}}

    def run(self, seq, clips, output_start_frame, seq2=None, seq3=None, seq4=None):
        r = _gl.sequence_clips([seq, seq2, seq3, seq4], clips, output_start_frame)
        return (r, len(r))


@_node
class PCG_COPTimePack:
    """
    Maps to: Time Pack (new in pcg100 c8). Takes a time sample every Step within Range (Relative is relative to Frame,
    Absolute is the frame number itself; Frames or Seconds); the frames at those times are combined into one multi-layer image, with layer names getting
    a sample-number prefix / suffix per Add Time As. Linear interpolation between two frames. The Sequence Import it used to point to is a different thing.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"seq": (COPSEQ,),
                             "mode": (list(_gl.TP_MODES),),
                             "units": (list(_gl.TP_UNITS),),
                             "frame": _f(0.0, -1e6, 1e6, 1.0),
                             "range_start": _f(-1.0, -1e6, 1e6, 1.0),
                             "range_end": _f(1.0, -1e6, 1e6, 1.0),
                             "step": _f(1.0, 1e-6, 1e6, 1.0),
                             "fps": _f(24.0, 1e-3, 1e4, 1.0),
                             "add_time_as": (list(_gl.TP_ADD), {"default": "suffix"}),
                             "layers": _s()}}

    def run(self, seq, mode, units, frame, range_start, range_end, step, fps, add_time_as,
            layers):
        return (_gl.time_pack(seq, frame, mode, units, range_start, range_end, step, fps,
                              add_time_as, layers),)


@_node
class PCG_COPIntegrateVolume:
    """
    Maps to: Integrate Volume (new in pcg100 c8). One line of sight per pixel through a volume prim: line integral /
    transmittance / minimum / maximum. Orthographic by default (image coordinates −1~1, the whole line along +Z); if the layers input gives
    View Origin / View Direction layers they're used per pixel, and Min / Max Depth layers limit the range. Houdini takes VDBs,
    we take dense volumes. The Prefix Sum it used to point to is a 2D accumulation, a different thing.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,),
                             "density": _s(),
                             "operation": (list(_gl.IV_OPS),),
                             "density_scale": _f(1.0, 0, 1e9, 0.1),
                             "density_min": _f(0.0, -1e9, 1e9, 0.01),
                             "density_max": _f(1.0, -1e9, 1e9, 0.01),
                             "ramp_mode": (list(_gl.IV_RAMP),),
                             "step_size": _f(0.01, 1e-6, 1e6, 0.001),
                             "max_steps": _i(4096, 1, 1 << 20),
                             "transmittance_cutoff": _f(-1.0, -1, 1, 0.001),
                             "sample_jitter": _f(0.0, 0, 1, 0.01),
                             "stratification_jitter": _f(0.0, 0, 1, 0.01),
                             "rand_seed": _i(0, 0, 2 ** 31 - 1),
                             "origin_layer": _s(), "direction_layer": _s(),
                             "mindepth_layer": _s(), "maxdepth_layer": _s(),
                             "out_layer": _s("result"), **_res()},
                "optional": {"layers": (COP,)}}

    def run(self, geo, density, operation, density_scale, density_min, density_max,
            ramp_mode, step_size, max_steps, transmittance_cutoff, sample_jitter,
            stratification_jitter, rand_seed, origin_layer, direction_layer,
            mindepth_layer, maxdepth_layer, out_layer, resolution_x, resolution_y,
            layers=None):
        return (_gl.integrate_volume(geo, density, operation, density_min, density_max,
                                     ramp_mode, density_scale, step_size, max_steps,
                                     transmittance_cutoff, sample_jitter,
                                     stratification_jitter, rand_seed, layers, origin_layer,
                                     direction_layer, mindepth_layer, maxdepth_layer,
                                     out_layer, resolution_x, resolution_y),)


@_node
class PCG_COPConfigureStamps:
    """
    Maps to: Configure Stamps (new in pcg100 c8). Draws nothing; only writes to points the sprite attributes Stamp Points recognises:
    spritescale / spriterot / Cd / blend / stamp; Jitter moves P. Each item can take a layer (a layer name from the layers input)
    × Mask modulation, with Uniform / Variance / Min-Max randomness. The Scatter Shapes it used to point to is rasterised stamping,
    a different thing. Note: our Scatter Shapes reads pscale / Cd, not spritescale.
    """
    RETURN_TYPES = (GEO,)
    RETURN_NAMES = ("points",)

    @classmethod
    def INPUT_TYPES(cls):
        lm = _f(1.0, -1e6, 1e6, 0.01)
        return {"required": {
            "points": (GEO,),
            "rand_seed": _i(0, 0, 2 ** 31 - 1),
            "jitter": _f(0.0, 0, 1e6, 0.01), "jitter_scale": _s("1 1"),
            "jitter_layer": _s(), "jitter_mask": lm,
            "scale": _f(1.0, 0, 1e6, 0.01), "scale_mode": (list(_gl.CS_SCALE),),
            "scale_variance": _f(0.0, 0, 1e3, 0.01), "scale_min": _f(0.5, -1e6, 1e6, 0.01),
            "scale_max": _f(1.0, -1e6, 1e6, 0.01), "scale_layer": _s(), "scale_mask": lm,
            "stretch": _s("1 1"), "stretch_mode": (list(_gl.CS_VAR),),
            "stretch_variance": _f(0.0, 0, 1e3, 0.01), "stretch_min": _f(0.5, -1e6, 1e6, 0.01),
            "stretch_max": _f(1.0, -1e6, 1e6, 0.01), "stretch_layer": _s(), "stretch_mask": lm,
            "angle": _f(0.0, -1e6, 1e6, 1.0), "angle_mode": (list(_gl.CS_VAR),),
            "angle_variance": _f(0.0, 0, 1e6, 1.0), "angle_min": _f(0.0, -1e6, 1e6, 0.01),
            "angle_max": _f(1.0, -1e6, 1e6, 0.01), "round_to": _f(0.0, 0, 360, 1.0),
            "angle_layer": _s(), "angle_mask": lm, "direction_layer": _s(),
            "direction_mask": lm,
            "color": _s("1 1 1"), "color_mode": (list(_gl.CS_COLOR),),
            "color_seed": _i(0, 0, 2 ** 31 - 1), "hue_variance": _f(0.0, 0, 1, 0.01),
            "saturation_variance": _f(0.0, 0, 1, 0.01), "value_variance": _f(0.0, 0, 1, 0.01),
            "color_layer": _s(), "color_mask": lm,
            "alpha": _f(1.0, 0, 1, 0.01), "alpha_mode": (list(_gl.CS_COLOR),),
            "alpha_variance": _f(0.0, 0, 1, 0.01), "alpha_layer": _s(), "alpha_mask": lm,
            "stamp_count": _i(1, 1, 1 << 20), "select_mode": (list(_gl.CS_SELECT),),
            "select_seed": _i(0, 0, 2 ** 31 - 1), "select_layer": _s(),
            "use_sort_layer": _b(False), "sort_layer": _s(),
            "plane": (list(_cop.stamp.PLANES),), "world_size": _f(1.0, 1e-6, 1e9, 0.1)},
            "optional": {"layers": (COP,)}}

    def run(self, points, rand_seed, jitter, jitter_scale, jitter_layer, jitter_mask, scale,
            scale_mode, scale_variance, scale_min, scale_max, scale_layer, scale_mask,
            stretch, stretch_mode, stretch_variance, stretch_min, stretch_max, stretch_layer,
            stretch_mask, angle, angle_mode, angle_variance, angle_min, angle_max, round_to,
            angle_layer, angle_mask, direction_layer, direction_mask, color, color_mode,
            color_seed, hue_variance, saturation_variance, value_variance, color_layer,
            color_mask, alpha, alpha_mode, alpha_variance, alpha_layer, alpha_mask,
            stamp_count, select_mode, select_seed, select_layer, use_sort_layer, sort_layer,
            plane, world_size, layers=None):
        return (_gl.configure_stamps(
            points, layers, plane, world_size, rand_seed, jitter, jitter_scale, jitter_layer,
            jitter_mask, scale, scale_mode, scale_variance, scale_min, scale_max, scale_layer,
            scale_mask, stretch, stretch_mode, stretch_variance, stretch_min, stretch_max,
            stretch_layer, stretch_mask, angle, angle_mode, angle_variance, angle_min,
            angle_max, round_to, angle_layer, angle_mask, direction_layer, direction_mask,
            color, color_mode, color_seed, hue_variance, saturation_variance, value_variance,
            color_layer, color_mask, alpha, alpha_mode, alpha_variance, alpha_layer,
            alpha_mask, stamp_count, select_mode, select_seed, select_layer, use_sort_layer,
            sort_layer),)


def _display(name):
    base = name[len("PCG_COP"):] if name.startswith("PCG_COP") else name
    out = []
    for i, ch in enumerate(base):
        if ch.isupper() and i and not base[i - 1].isupper():
            out.append(" ")
        out.append(ch)
    return "COP " + "".join(out) + " (PCG)"


# ═══════════════════════════════════════════════════════ pcg82 masks / cutouts by geometry
@_node
class PCG_COPHFMaskByObject:
    """
    Maps to: HeightField Mask by Object. Projects geometry vertically onto the height field to make a mask: footprint (where it covers) /
    intersect (passes through the ground) / above (floating) / below (buried); Feather feathers outward (world units, exact
    distance + smoothstep), Invert inverts. Grid convention as in HeightField Project (centred on xz, width World Size).
    """
    RETURN_TYPES = (COP, "STRING")
    RETURN_NAMES = ("cop", "report")

    @classmethod
    def INPUT_TYPES(cls):
        from .geo.cop import hfobject as _ho
        return {"required": {"cop": (COP,), "geo": (GEO,), "layer": _s("C"),
                             "mode": (list(_ho.MASK_MODES),),
                             "strength": _f(1.0, -1e6, 1e6, 0.01),
                             "world_size": _f(1.0, 1e-6, 1e9, 0.1),
                             "feather": _f(0.0, 0.0, 1e9, 0.01),
                             "invert": _b(False), "out_layer": _s("mask")}}

    def run(self, cop, geo, layer, mode, strength, world_size, feather, invert,
            out_layer):
        from .geo.cop import hfobject as _ho
        o, r = _ho.mask_by_object(cop, geo, layer, mode, strength, world_size,
                                  feather, invert, out_layer)
        return (o, json.dumps(r))


@_node
class PCG_COPHFCutoutByObject:
    """
    Maps to: HeightField Cutout by Object. carve: where geometry passes through the ground, dig down to the geometry's bottom; fill: where geometry presses
    on the ground, raise it to the geometry's top; both: dig first then raise (the ground replaced by the geometry's top surface). Geometry entirely buried / floating
    leaves the ground unchanged. Also writes a _cut layer (modified texels = 1).
    """
    RETURN_TYPES = (COP, "STRING")
    RETURN_NAMES = ("cop", "report")

    @classmethod
    def INPUT_TYPES(cls):
        from .geo.cop import hfobject as _ho
        return {"required": {"cop": (COP,), "geo": (GEO,), "layer": _s("C"),
                             "mode": (list(_ho.CUT_MODES),),
                             "strength": _f(1.0, -1e6, 1e6, 0.01),
                             "world_size": _f(1.0, 1e-6, 1e9, 0.1),
                             "out_layer": _s()}}

    def run(self, cop, geo, layer, mode, strength, world_size, out_layer):
        from .geo.cop import hfobject as _ho
        o, r = _ho.cutout_by_object(cop, geo, layer, mode, strength, world_size,
                                    out_layer)
        return (o, json.dumps(r))



@_node
class PCG_COPWriteFile:
    """
    Maps to: ROP Image Output / File (write). Writes layers under output/ in production formats:
    PNG 8 / 16 bit, EXR half / float, RAW r16 / r32; Channels takes one channel per item (ORM packing is
    `ao roughness metallic`); Encode srgb for albedo; Remap signed for normals, normalize for height
    (the range is written to a .json alongside; when tiling, all tiles share one range); Normal Y -y is the DirectX convention;
    Tiles + Shared Edge cut by the terrain tiling convention (adjacent tiles share the row of pixels on the edge). In file names
    {index} {tx} {ty} {tile} are replaced. The second output is what was written (8-bit preview).
    """
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING", "IMAGE")
    RETURN_NAMES = ("report", "preview")

    @classmethod
    def INPUT_TYPES(cls):
        from .geo.cop import imagefile as _if
        return {"required": {
            "cop": (COP,),
            "filename": _s("pcg/tex/texture_{index}"),
            "channels": _s("C"),
            "format": (list(_if.FORMATS),),
            "bit_depth": (list(_if.DEPTHS), {"default": "8"}),
            "encode": (list(_if.ENCODES),),
            "remap": (list(_if.REMAPS),),
            "in_min": _sec("Range", _f(0.0, -1e9, 1e9, 0.01)),
            "in_max": _sec("Range", _f(1.0, -1e9, 1e9, 0.01)),
            "normal_y": (list(_if.NORMAL_Y),),
            "tiles_x": _sec("Tiles", _i(1, 1, 256)),
            "tiles_y": _sec("Tiles", _i(1, 1, 256)),
            "shared_edge": _sec("Tiles", _b(False)),
            "index": _i(0, 0, 1 << 30),
            "sidecar": _b(True),
            "value_scale": _f(1.0, -1e9, 1e9, 0.01),
        }}

    def run(self, cop, filename, channels, format, bit_depth, encode, remap,
            in_min, in_max, normal_y, tiles_x, tiles_y, shared_edge, index,
            sidecar, value_scale=1.0):
        from .geo.cop import imagefile as _if
        from .nodes import output_dir
        import torch
        rep, pv = _if.write(cop, output_dir(), filename, channels, format,
                            bit_depth, encode, remap, in_min, in_max, normal_y,
                            tiles_x, tiles_y, shared_edge, index, sidecar,
                            value_scale)
        files = [f["file"] for f in rep["files"]]
        return {"ui": {"text": files[:16]},
                "result": (json.dumps(rep, ensure_ascii=False),
                           torch.from_numpy(pv)[None])}


_NAMES = {
    "PCG_COPColorCorrect": "COP Color Correct (PCG)",
    "PCG_COPChannelConvert": "COP Channel Convert (PCG)",
    "PCG_COPIllegalPixel": "COP Illegal Pixel (PCG)",
    "PCG_COPConvertDepth": "COP Convert Depth (PCG)",
    "PCG_COPHistogramPlot": "COP Histogram Plot (PCG)",
    "PCG_COPCompareMask": "COP Compare Mask (PCG)",
    "PCG_COPMonoToRGB": "COP Mono to RGB (PCG)",
    "PCG_COPMonoToHeightField": "COP Mono to HeightField (PCG)",
    "PCG_COPDenoiseTV": "COP Denoise TV (PCG)",
    "PCG_COPFFT": "COP FFT (PCG)",
    "PCG_COPUVMap": "COP UV Map (PCG)",
    "PCG_COPUVSample": "COP UV Sample (PCG)",
    "PCG_COPUVShape": "COP UV Shape (PCG)",
    "PCG_COPPolarCoords": "COP Polar Coords (PCG)",
    "PCG_COPSpaceTransform": "COP Space Transform (PCG)",
    "PCG_COPPositionMap": "COP Position Map (PCG)",
    "PCG_COPSphereSample": "COP Sphere Sample (PCG)",
    "PCG_COPTransform3D": "COP Transform 3D (PCG)",
    "PCG_COPAlignWindow": "COP Align Window (PCG)",
    "PCG_COPAlignPixels": "COP Align Pixels (PCG)",
    "PCG_COPBend": "COP Bend (PCG)",
    "PCG_COPUVTransform": "COP UV Transform (PCG)",
    "PCG_COPUVInverse": "COP UV Inverse (PCG)",
    "PCG_COPSDFOps": "COP SDF Ops (PCG)",
    "PCG_COPIDConvert": "COP ID Convert (PCG)",
    "PCG_COPHFClip": "COP HeightField Clip (PCG)",
    "PCG_COPHFProject": "COP HeightField Project (PCG)",
    "PCG_COPTileSplit": "COP HeightField Tile Split (PCG)",
    "PCG_COPTileSplice": "COP HeightField Tile Splice (PCG)",
    "PCG_COPHFMaskByObject": "COP HeightField Mask by Object (PCG)",
    "PCG_COPHFCutoutByObject": "COP HeightField Cutout by Object (PCG)",
    "PCG_COPWriteFile": "COP Write File (PCG)",
    "PCG_COPWorleyNoise": "COP Worley Noise (PCG)",
    "PCG_COPCellularNoise": "COP Cellular Noise (PCG)",
    "PCG_COPFractalSample": "COP Fractal Sample (PCG)",
    "PCG_COPPointGenerate": "COP Point Generate (PCG)",
    "PCG_COPLayerFromAttrib": "COP Layer from Attribute (PCG)",
    "PCG_COPGeoToLayer": "COP Geometry to Layer (PCG)",
    "PCG_COPSequenceClips": "COP Sequence Clips (PCG)",
    "PCG_COPTimePack": "COP Time Pack (PCG)",
    "PCG_COPIntegrateVolume": "COP Integrate Volume (PCG)",
    "PCG_COPConfigureStamps": "COP Configure Stamps (PCG)",
    "PCG_COPFeatherSlope": "COP Feather Slope (PCG)",
    "PCG_COPExtrapolateBoundaries": "COP Extrapolate Boundaries (PCG)",
    "PCG_COPEdgeDetectProbe": "COP Edge Detect Probe (PCG)",
    "PCG_COPSurfaceDither": "COP Surface Dither (PCG)",
    "PCG_COPTuringPatterns": "COP Turing Patterns (PCG)",
    "PCG_COPHeatDistortByLayer": "COP Heat Distort by Layer (PCG)",
}

NODE_CLASS_MAPPINGS = {k: v for k, v in dict(globals()).items()
                       if k.startswith("PCG_COP") and isinstance(v, type)}
NODE_DISPLAY_NAME_MAPPINGS = {k: _NAMES.get(k, _display(k))
                              for k in NODE_CLASS_MAPPINGS}
