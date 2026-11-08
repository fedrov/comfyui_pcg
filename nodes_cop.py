"""
COP nodes (the batch made before pcg57): generators (Noise / Shape / Gradient / Constant),
composite / blur / transform / levels / morphology / SDF, the height-map family (normal / AO / projection / caustics),
analysis (slope / curvature / statistics / segmentation), the terrain chain (masks by feature / terraces / erosion / flow /
hydraulic erosion / splat), the bridge to AI (Render Pass / Control Image / ID Masks / regional prompts
/ depth -> height field), and sequence import/export.

Moved out of nodes.py as is (not a single character of code changed, only the file), selected by CATEGORY =
PCG/cop. Registration still happens in nodes.py's main table; nodes.py imports every class here back into its own
namespace, so old spellings like `nodes.PCG_COPNoise` keep working.
"""
from __future__ import annotations

from .nodes_common import (  # noqa: F401
    CAM, CAT, COP, COPSEQ, GEO, _can, _cbk, _cbrg, _ccmp, _cctl, _cero, _cflt,
    _cflw, _cgen, _chm, _chyd, _clev, _clift, _cmrp, _cop, _creg, _csdf,
    _compute, _cspl, _ctr, _ctrn, _dev, _f, _fmp, _group, _i, _names, _rmp,
    _rnd, _sec, _seq, convert, math, np,
)
from .geo.cop import noisepost as _cpost


# ════════════════════════════════════════════════════ Copernicus (COP)
#
# The second data type. Everything before was Geometry (point/vertex/prim/detail attributes); here it is
# CopImage: a set of **named layers** at the same resolution, each (H,W,C) linear float32, unclamped.
#
# Three fixed conventions, written at the top of geo/cop/core.py:
#   · row 0 is the **bottom** (v points up, consistent with uv / Houdini). Flipping only happens in
#     COP Import / COP Export -- a flip anywhere else is a bug
#   · no clamping and no sRGB in intermediate steps. Clamping happens only at export, and can be turned off
#   · layer arrays are read-only and copy() is shallow, same rule as Geometry


class PCG_COPNoise:
    """
    Noise image. Mirrors Copernicus's Noise.

    **Uses the same `attribnoise.fractal_noise` as the geometry side.** Each image pixel is given a
    3D coordinate (uv×Frequency on the plane z=Offset), so the same world coordinate sampled on the image
    and on geometry gives **bit-identical** noise values (measured: float32 identical at 4096 positions).

    This isn't about saving effort, it's about **alignment**: with the same parameters, bake a displacement map on one side and actually
    push the geometry out on the other, and they match exactly. Just fill Attribute Noise (PCG) with the same parameters as this node.

    Tile wraps the u direction into a circle, so **horizontal** tiling is seamless. Seamless in both directions needs 4D noise, which
    isn't installed here -- saying so clearly beats offering a half-right switch.

    With Channels > 1 each channel uses a different seed (seed + k×7919), to generate RGB noise
    or a 2D flow field in one go. (This is Houdini's Per Component.)

    pcg100: Tile V together with Tile U gives **bidirectional** seamless tiling (u and v each wrapped into a circle, 4D,
    a flat torus); Noise Type = Torus equals simplex + bidirectional tiling, matching Houdini's
    Torus. The two Worley modes gain Metric / Jitter; a Post Processing section at the end.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "resolution_x": _i(512, 1, _cop.MAX_RES),
            "resolution_y": _i(512, 1, _cop.MAX_RES),
            "noise_type": (list(_cgen.NOISE_TYPES),),
            "fractal": (list(_cgen.FRACTALS),),
            "frequency": _f(4.0, 0.0, 1e5, 0.1),
            "octaves": _i(3, 1, 16),
            "lacunarity": _sec("Fractal", _f(2.0, 0.0, 16.0, 0.05)),
            "roughness": _sec("Fractal", _f(0.5, 0.0, 1.0, 0.01)),
            "amplitude": _f(1.0, -1e5, 1e5, 0.01),
            "bias": _f(0.0, -1e5, 1e5, 0.01),
            "channels": _i(1, 1, 4),
            "tile_u": ("BOOLEAN", {"default": False}),
            "offset_x": _sec("Offset", _f(0.0, -1e5, 1e5, 0.05)),
            "offset_y": _sec("Offset", _f(0.0, -1e5, 1e5, 0.05)),
            "offset_z": _sec("Offset", _f(0.0, -1e5, 1e5, 0.05)),
            "layer": ("STRING", {"default": "C"}),
            "rand_seed": _i(0, 0, 1 << 31),
            "device": _dev(),
            # **New widgets always go at the end.** litegraph stores widgets_values as
            # a flat ordered list; inserting in the middle shifts layer / rand_seed / device
            # in already-saved workflows by three slots as a block -- you open an old graph and the seed has
            # become "C". Sections are regrouped by the frontend via options.section, independent of the order here
            "time_scale": _sec("Time", _f(0.0, 0.0, 1e4, 0.01), gate=True),
            "time": _sec("Time", _f(0.0, -1e6, 1e6, 1.0)),
            "loop_frames": _sec("Time", _i(0, 0, 1 << 16)),
            # pcg100 c3_noise (all appended at the end, defaults = old behaviour):
            #   metric / jitter  specific to the two Worley modes of Houdini Fractal Noise
            #   tile_v           tiling in v; together with tile_u = flat torus (4D)
            #   Post Processing  Fold … Clamp Maximum, see geo/cop/noisepost.py
            "metric": _sec("Pattern", (list(_cgen.METRICS),)),
            "jitter": _sec("Pattern", _f(1.0, 0.0, 2.0, 0.01)),
            "tile_v": ("BOOLEAN", {"default": False}),
            **_cpost.widgets(_f, _sec),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, resolution_x, resolution_y, noise_type, fractal, frequency,
            octaves, lacunarity, roughness, amplitude, bias, channels,
            tile_u, offset_x, offset_y, offset_z, layer, rand_seed, device,
            time_scale=0.0, time=0.0, loop_frames=0, metric="euclidean",
            jitter=1.0, tile_v=False, **post):
        return (_cgen.noise(resolution_x, resolution_y, noise_type, fractal,
                            frequency, octaves, lacunarity, roughness,
                            rand_seed, (offset_x, offset_y, offset_z),
                            amplitude, bias, channels, tile_u, layer,
                            device, time, time_scale, loop_frames, metric,
                            jitter, tile_v, _cpost.pick(post)),)


class PCG_COPShape:
    """
    Draws a shape. Mirrors Copernicus's Shape.

    **The main output is an SDF (negative inside, positive outside), not a black-and-white image.** The mask is smoothstepped from the SDF.
    The reverse order looks similar but differs a lot in practice:

      · an SDF directly gives outlines (|d| < w), dilate/erode (d − r) and bevels; a black-and-white image can't
      · anti-aliasing is **analytic**: edge width is given in pixel size, so visual softness doesn't change with resolution.
        Drawing black-and-white then blurring ties the blur radius to the resolution
      · min of two SDFs is the union, max the intersection, −min(−a,−b) the difference, **and the edge is still
        a correct SDF**

    Coordinates are centred and **normalised by the short side**: short side [−0.5, 0.5], the long side extends by the aspect ratio.
    So a radius=0.5 circle is inscribed in the short side at any aspect ratio and never squashed into an ellipse --
    which is what computing distance directly in 0-1 uv would do.

    The rectangle uses the standard SDF (`‖max(|q|−b,0)‖ + min(max(dx,dy),0)`). The exterior term can't
    be shortened to `max(dx,dy)`: that's Chebyshev distance, too small outside the four corners, so outlines get thinner at the corners.

    The star is **not an exact SDF** (polar folding gives an approximation); good enough for outlines and masks, but large dilations
    show deformation -- that's not a bug.

    Compared with SideFX SDF Shape (pcg100): the Shape menu adds Polygon / Squircle / Trapezoid /
    Triangle / Diamond (Basic) and Egg / Moon / Vesica / Cross / Arch / Arrow
    (Compound); Circle adds Arc / Thickness / Round Ends, Rectangle adds separate per-corner
    rounding, Line adds different widths at each end, Transform adds Shear / Uniform Scale. There is no Shape
    Class level (we list everything in one menu). Spiral / Wave / Fishscale / Octagon-dot /
    Horseshoe / Quadratic Circle and the whole Marker class have no reproducible definition in the docs; not done,
    see audit_notes/c4_pattern_shape.md.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "resolution_x": _i(512, 1, _cop.MAX_RES),
            "resolution_y": _i(512, 1, _cop.MAX_RES),
            "shape": (list(_cgen.SHAPES),),
            "radius": _f(0.35, -1e4, 1e4, 0.01),
            "size_x": _sec("Box", _f(0.35, 0.0, 1e4, 0.01)),
            "size_y": _sec("Box", _f(0.25, 0.0, 1e4, 0.01)),
            "corner": _sec("Box", _f(0.05, 0.0, 1e4, 0.005)),
            "center_x": _f(0.0, -1e4, 1e4, 0.01),
            "center_y": _f(0.0, -1e4, 1e4, 0.01),
            "angle": _f(0.0, -3600.0, 3600.0, 1.0),
            "points": _sec("Star", _i(5, 3, 64)),
            "inner": _sec("Star", _f(0.5, 0.0, 1.0, 0.01)),
            "line_ax": _sec("Line", _f(-0.3, -1e4, 1e4, 0.01)),
            "line_ay": _sec("Line", _f(0.0, -1e4, 1e4, 0.01)),
            "line_bx": _sec("Line", _f(0.3, -1e4, 1e4, 0.01)),
            "line_by": _sec("Line", _f(0.0, -1e4, 1e4, 0.01)),
            "softness_pixels": _f(1.5, 0.0, 1e4, 0.1),
            "invert": ("BOOLEAN", {"default": False}),
            "sdf_layer": ("STRING", {"default": "sdf"}),
            "mask_layer": ("STRING", {"default": "mask"}),
            "color_layer": ("STRING", {"default": ""}),
            "device": _dev(),
            # ── pcg100 c4: added to match SideFX SDF Shape, all appended at the end, defaults = old behaviour
            "arc": _sec("Circle", _f(1.0, 0.0, 1.0, 0.01)),
            "thickness": _sec("Circle", _f(1.0, 0.0, 1.0, 0.01)),
            "round_ends": _sec("Circle", ("BOOLEAN", {"default": False})),
            "separate_corners": _sec("Box", ("BOOLEAN", {"default": False})),
            "corner_tl": _sec("Box", _f(0.0, 0.0, 1.0, 0.01)),
            "corner_tr": _sec("Box", _f(0.0, 0.0, 1.0, 0.01)),
            "corner_bl": _sec("Box", _f(0.0, 0.0, 1.0, 0.01)),
            "corner_br": _sec("Box", _f(0.0, 0.0, 1.0, 0.01)),
            "separate_thickness": _sec("Line", ("BOOLEAN", {"default": False})),
            "start_thickness": _sec("Line", _f(0.1, 0.0, 1e4, 0.005)),
            "end_thickness": _sec("Line", _f(0.02, 0.0, 1e4, 0.005)),
            "squircle_blend": _f(4.0, 0.25, 1e3, 0.05),
            "trap_top": _f(0.15, 0.0, 1e4, 0.01),
            "use_points": ("BOOLEAN", {"default": False}),
            "tri_p0": ("STRING", {"default": "-0.3 -0.25"}),
            "tri_p1": ("STRING", {"default": "0 0.3"}),
            "tri_p2": ("STRING", {"default": "0.3 -0.25"}),
            "roundness": _f(0.5, 0.0, 1.0, 0.01),
            "moon_inner": _f(0.3, 0.0, 1e4, 0.01),
            "moon_offset": _f(0.15, -1e4, 1e4, 0.01),
            "cross_inset": _f(0.15, 0.0, 1e4, 0.01),
            "cross_bevel": _f(0.0, 0.0, 1e4, 0.005),
            "arrow_shaft": _f(0.06, 0.0, 1e4, 0.005),
            "arrow_head": _f(0.2, 0.0, 1e4, 0.005),
            "arrow_head_ratio": _f(0.3, 0.0, 1.0, 0.01),
            "shear": _f(0.0, -1e4, 1e4, 0.01),
            "uniform_scale": _f(1.0, -1e4, 1e4, 0.01),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, resolution_x, resolution_y, shape, radius, size_x, size_y,
            corner, center_x, center_y, angle, points, inner, line_ax,
            line_ay, line_bx, line_by, softness_pixels, invert, sdf_layer,
            mask_layer, color_layer, device, arc=1.0, thickness=1.0,
            round_ends=False, separate_corners=False, corner_tl=0.0,
            corner_tr=0.0, corner_bl=0.0, corner_br=0.0,
            separate_thickness=False, start_thickness=0.1,
            end_thickness=0.02, squircle_blend=4.0, trap_top=0.15,
            use_points=False, tri_p0="-0.3 -0.25", tri_p1="0 0.3",
            tri_p2="0.3 -0.25", roundness=0.5, moon_inner=0.3,
            moon_offset=0.15, cross_inset=0.15, cross_bevel=0.0,
            arrow_shaft=0.06, arrow_head=0.2, arrow_head_ratio=0.3,
            shear=0.0, uniform_scale=1.0):
        return (_cgen.shape(resolution_x, resolution_y, shape, radius,
                            (size_x, size_y), corner, (center_x, center_y),
                            angle, points, inner, (line_ax, line_ay),
                            (line_bx, line_by), softness_pixels, invert,
                            sdf_layer, mask_layer, color_layer, device,
                            arc, thickness, round_ends, separate_corners,
                            (corner_tl, corner_tr, corner_bl, corner_br),
                            separate_thickness,
                            (start_thickness, end_thickness),
                            squircle_blend, trap_top, use_points,
                            (tri_p0, tri_p1, tri_p2), roundness, moon_inner,
                            moon_offset, cross_inset, cross_bevel,
                            arrow_shaft, arrow_head, arrow_head_ratio,
                            shear, uniform_scale),)


class PCG_COPGradient:
    """
    Gradient. Five kinds: u / v / diagonal / radial / angular.

    Colour lookup reuses the geometry side's `ramp` module, so the ramp syntax of Attribute Fade / Measure
    (`0:0  0.5:1  1:0`, or multi-component `0:0,0,0  1:1,0.5,0`) works here as is
    -- learn one syntax once.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "resolution_x": _i(512, 1, _cop.MAX_RES),
            "resolution_y": _i(512, 1, _cop.MAX_RES),
            "direction": (["v", "u", "diagonal", "radial", "angular"],),
            "ramp": ("STRING", {"default": "0:0  1:1", "multiline": False}),
            "ramp_mode": (["linear", "smooth", "constant"],),
            "angle": _f(0.0, -3600.0, 3600.0, 1.0),
            "center_x": _f(0.0, -1e4, 1e4, 0.01),
            "center_y": _f(0.0, -1e4, 1e4, 0.01),
            "layer": ("STRING", {"default": "C"}),
            "device": _dev(),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, resolution_x, resolution_y, direction, ramp, ramp_mode,
            angle, center_x, center_y, layer, device):
        return (_cgen.gradient(resolution_x, resolution_y, direction, ramp,
                               ramp_mode, angle, (center_x, center_y),
                               layer, device),)


class PCG_COPConstant:
    """A solid-colour image. A base for compositing, or a backplate for masks. Check Alpha to make it 4 channels."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "resolution_x": _i(512, 1, _cop.MAX_RES),
            "resolution_y": _i(512, 1, _cop.MAX_RES),
            "red": _f(0.0, -1e5, 1e5, 0.01),
            "green": _f(0.0, -1e5, 1e5, 0.01),
            "blue": _f(0.0, -1e5, 1e5, 0.01),
            "use_alpha": ("BOOLEAN", {"default": False}),
            "alpha": _f(1.0, -1e5, 1e5, 0.01),
            "layer": ("STRING", {"default": "C"}),
            "device": _dev(),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, resolution_x, resolution_y, red, green, blue, use_alpha,
            alpha, layer, device):
        return (_cgen.constant(resolution_x, resolution_y,
                               (red, green, blue),
                               alpha if use_alpha else None, layer, device),)


class PCG_COPComposite:
    """
    Composites the second input over the first. Mirrors Copernicus's Layer / Composite.

    **`over` is not the same kind of thing as the other blend modes.** add / multiply / screen are per-component
    functions f(a,b), with alpha only interpolated at the end; over is Porter–Duff compositing, which also computes
    **a new alpha**:

        C = (Cf·αf + Cb·αb·(1−αf)) / α ,  α = αf + αb·(1−αf)

    Writing over as "interpolate by alpha" is wrong when both layers are semi-transparent: the result's alpha stays at the lower layer's
    alpha, so stacking three layers of fog gives the wrong density. So over / atop / xor take a separate path.

    Uses **non-premultiplied** alpha (consistent with ComfyUI's IMAGE); the formulas multiply it themselves.

    When resolutions differ, the **second input** is resampled to the first (Houdini's COP also conforms to the first
    input). For channel counts only **1 channel is auto-broadcast** -- compositing a mask with RGB naturally needs broadcasting;
    between 3 and 4 no guessing: either you want alpha or it's wired wrong.

    **No clamping.** add giving 1.7 stays 1.7. Clamping intermediates destroys HDR / SDF / normals,
    and what's been clamped can't be recovered. Clamping only happens in COP Export.

    Compared with Houdini's Blend (pcg100): Mode adds Under / Hypot / Exclusion /
    HardLight / Dodge / Burn; Houdini's Blend is our replace, Maximum /
    Minimum are lighten / darken (Compare Lengths applies to those two). Sharpen and
    Hue / Saturation / Luminosity / Color have no formula in the docs, **not done**. Space /
    Border / Filter / Clip by Data Window / Crop to Content depend on the data window,
    a concept our images don't have; not done either.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "background": (COP,), "foreground": (COP,),
            "mode": (list(_ccmp.MODES),),
            "opacity": _f(1.0, -1e4, 1e4, 0.01),
            "layer": ("STRING", {"default": "C"}),
            "foreground_layer": ("STRING", {"default": ""}),
            "mask_layer": ("STRING", {"default": "mask"}),
            "output_layer": ("STRING", {"default": ""}),
            "keep_other_layers": ("BOOLEAN", {"default": True}),
            # pcg100: Houdini Blend's Swap FG and BG / Compare Lengths /
            # per-channel toggles. Defaults = the original behaviour
            "swap": ("BOOLEAN", {"default": False}),
            "compare_lengths": ("BOOLEAN", {"default": False}),
            "channel_r": ("BOOLEAN", {"default": True}),
            "channel_g": ("BOOLEAN", {"default": True}),
            "channel_b": ("BOOLEAN", {"default": True}),
            "channel_a": ("BOOLEAN", {"default": True}),
        }, "optional": {"mask": (COP,)}}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, background, foreground, mode, opacity, layer,
            foreground_layer, mask_layer, output_layer, keep_other_layers,
            swap=False, compare_lengths=False, channel_r=True, channel_g=True,
            channel_b=True, channel_a=True, mask=None):
        return (_ccmp.composite(background, foreground, mode, opacity, layer,
                                foreground_layer, mask, mask_layer,
                                output_layer, keep_other_layers, swap,
                                compare_lengths,
                                (channel_r, channel_g, channel_b, channel_a)),)


class PCG_COPBlur:
    """
    Gaussian blur. **Separable**: horizontal then vertical, O(N·k) instead of O(N·k²), 31 times faster at k=31.

    Kernel radius is **ceil(3σ)** (losing 0.3% of the energy), renormalised after truncation. Truncating at 2σ loses
    4.6%, and a hard ring is visible in large-sigma glows.

    "Blur doesn't change mean brightness" is the best criterion for this node, but it **only holds with a wrap border**:

        wrap    sigma 1/4/12 -> mean difference -2.8e-9 / 0 / -1.9e-9
        clamp   same sigma -> -1.4e-6 / +4.7e-4 / +5.0e-3

    clamp and black both **invent** data outside the image (copying edges / padding black), so of course the mean changes --
    that's the definition of the border condition, not a bug.

    Empty Layers blurs all layers; list layer names if you only want to blur colour and not the SDF.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "sigma_pixels": _f(2.0, 0.0, 4096.0, 0.5),
            "border": (list(_cflt.BORDERS),),
            "layers": ("STRING", {"default": "",
                                  "tooltip": "Empty = all layers, space separated"}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, sigma_pixels, border, layers):
        return (_cflt.blur(cop, sigma_pixels, border, layers),)


class PCG_COPResize:
    """
    Bilinear resampling.

    Coordinates are converted by **pixel centre**: `x = (i+0.5)·W/W' − 0.5`, not endpoint-aligned
    `i·(W−1)/(W'−1)`. Pixels are cells with width, not points -- shrinking 2 columns to 1, endpoint alignment gives
    x=0 (only the left pixel), centre alignment gives x=0.5 (half of each).

    `uv_grid` and `sample` use the same convention, so "generate noise then resize" and "directly generate
    resized noise" match.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "resolution_x": _i(512, 1, _cop.MAX_RES),
            "resolution_y": _i(512, 1, _cop.MAX_RES),
            "border": (list(_cflt.BORDERS),),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, resolution_x, resolution_y, border):
        return (_cflt.resize(cop, resolution_x, resolution_y, border),)


class PCG_COPImport:
    """
    ComfyUI IMAGE -> COP. Feeds the output of a sampler / LoadImage into the COP chain.

    **v is flipped once here**: ComfyUI / PIL row 0 is the top, COP row 0 is the bottom
    (v points up, consistent with uv / Houdini). In the whole plugin only Import / Export may flip --
    if flips were scattered elsewhere, "how many times was it flipped" could never be answered, and the symptom (upside-down image) is too easily
    papered over with "just flip it once more".
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "layer": ("STRING", {"default": "C"}),
            "batch_index": _i(0, 0, 4096),
            "device": _dev(),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, image, layer, batch_index, device):
        return (_cbrg.from_comfy(image, layer, batch_index, True, device),)


def _mask_or_ones(cop, mask_layer, hw):
    """
    MASK output of COP Export / Sequence Export (same rule for both nodes, unified in pcg90):

    - layer present: take channel 0, **clamped to 0-1**. A mask is 0-1 coverage and doesn't follow Range Mode --
      COP Export used to map the mask by Range Mode too, so in Signed mode the background's 0 became 0.5
    - layer missing (or not filled in): **all 1** = "the whole image counts". COP Export used to give all 0
      (fed into Set Latent Noise Mask that means nothing gets repainted), Sequence Export gave all 1, and
      if a single frame lacked the layer the whole batch was all 1; now it's per frame: missing frames are all 1, the rest are used as is
    """
    nm = str(mask_layer).strip()
    if nm and cop is not None and len(cop) and nm in cop:
        return np.asarray(_cbrg.to_mask(cop, nm), np.float32)   # to_mask clamps by default
    return np.ones((1,) + tuple(int(v) for v in hw), np.float32)


class PCG_COPExport:
    """
    COP -> ComfyUI IMAGE + MASK. Connect to Preview / Save / any node that takes IMAGE.

    **Clamping can be turned off.** IMAGE's convention is 0-1, so it clamps by default; but SDFs, normals and displacements
    naturally have negative values and values above 1, and clamping makes them all black/all white:

        clamp       plain clamp to 0-1 (normal colour layers)
        raw         output as is (downstream handles it)
        signed      [−1,1] -> [0,1] (viewing normals / signed noise)
        normalize   stretch by this image's min/max (viewing SDFs / height fields)

    `normalize` is a **data-dependent** mapping: a different input frame changes the mapping. Good for viewing, not for
    exporting assets -- just know that before using it.

    Channel count: 1 channel is copied to grey (the only sensible interpretation), 4 channels drop alpha (ComfyUI's
    alpha goes through the separate MASK), 2 channels are padded with 0. The MASK output takes channel 0 of mask_layer, clamped to 0-1;
    without that layer it's all 1 (see _mask_or_ones).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            "mode": (list(_cbrg.EXPORT_MODES),),
            "mask_layer": ("STRING", {"default": "mask"}),
        }}
    RETURN_TYPES = ("IMAGE", "MASK"); RETURN_NAMES = ("image", "mask")
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, mode, mask_layer):
        img = _cbrg.to_comfy(cop, layer, mode)
        return (_cbrg.as_torch(img),
                _cbrg.as_torch(_mask_or_ones(cop, mask_layer, img.shape[1:3])))


class PCG_COPToDevice:
    """
    Moves a COP image to a given backend (numpy / torch CPU / CUDA / exact float64).

    Usually not needed -- the Device on the generator decides where the whole chain runs, and filters and composites follow their inputs.
    You need it in these cases:

      · the first half of the chain flies on the GPU, but some node in the second half only has a CPU implementation
      · you want to compare two backends' results in the same workflow (which is what the tests do)
      · VRAM is tight, so move intermediate results back to RAM first

    **Moving has a cost**: one H×W×C×4-byte PCIe transfer. A 2048² four-channel image is
    67 MB; a round trip on PCIe 3.0 takes about 10 ms -- more than most per-pixel operators themselves.
    So don't hop back and forth in the middle of the chain.

    Composite-type nodes **automatically** move the second input to the first's backend; no need to wire this manually.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cop": (COP,), "device": _dev("numpy")}}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, device):
        return (cop.to_device(device) if cop is not None else _cop.CopImage(),)


class PCG_COPInfo:
    """
    Reports one line of COP status: torch version, whether CUDA is available, the GPU model, and (if an image is connected)
    the image's resolution, its layers and which backend it lives on.

    The reason it exists is practical: "is my COP actually running on the GPU" is the most common question about this system,
    and **guessing** is the worst way to answer it. auto silently falls back to CPU when the image is too small, the CUDA build of torch isn't installed, or the VRAM
    budget isn't enough -- all three are reasonable, but you need to be able to see it.

    The cop input is optional; without it only the environment is reported.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}, "optional": {"cop": (COP,)}}
    RETURN_TYPES = ("STRING",); RETURN_NAMES = ("info",)
    OUTPUT_NODE = True
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop=None):
        lines = [_cbk.describe(),
                 f"auto threshold: {_cbk.AUTO_PIXELS} pixels"
                 f"({int(_cbk.AUTO_PIXELS ** 0.5)}²),"
                 f"VRAM budget {_cbk.VRAM_BUDGET_MB} MB"]
        if cop is not None and len(cop):
            lines.append(cop.info())
            n = cop.xres * cop.yres * sum(
                int(cop.need(k).shape[2]) for k in cop.names) * 4 / 1e6
            lines.append(f"in use: approx. {n:.1f} MB")
        txt = "\n".join(lines)
        print("[PCG COP] " + txt.replace("\n", " | "))
        return (txt,)


# ──────────────────────────────────────────────────────── COP: geometric transforms
class PCG_COPTransform:
    """
    Translate / rotate / scale. Resolution unchanged; what goes outside the frame is handled by Border.

    The order is **scale first, then rotate, then translate**, all about Pivot (given in uv).

    **Rotation is done in aspect-corrected space.** Multiplying a rotation matrix directly in uv **shears** on non-square
    images -- rotating a 1024x512 image by 45° turns squares in the frame into parallelograms,
    because one uv unit is 1024 pixels in x but only 512 in y. Here it first converts to the
    "normalised by the short side" coordinates COP Shape uses, then rotates, so "draw a circle then rotate 30°" and
    "directly draw an ellipse rotated by 30°" match.

    **Multiples of 90° are bit-exact moves.** `cos(radians(90))` = 6.12e-17, not 0; left
    alone, "rotate 90°" would become a resample with a 6e-17 shear -- every pixel touched by bilinear
    interpolation, invisible to the eye forever, only exposed by tests like "rotate four times to get back the original". Here
    multiples of 90° are snapped to exact 0/±1, and the output is bit-identical to `np.rot90`. Pure translation (no rotation,
    no scale) likewise takes the fast path; integer-pixel translation is equivalent to `np.roll`.

    Rotate is in **counter-clockwise** degrees -- COP's v points up, so this is the mathematically positive direction; it looks opposite to ComfyUI nodes
    with v pointing down, which is the definition of the coordinate system, not a bug.

    **Shrinking aliases, and this node doesn't pretend to solve that.** At scale=0.25 one output pixel covers
    4x4 input pixels, bilinear only looks at 2x2 of them, giving moiré. Suggest adding a COP Blur first
    (sigma ≈ 0.5/scale) before shrinking -- about as good as mip, and the parameters are in your hands.

    Empty Layers = all layers. Layers not listed are **carried through as is** without resampling. Mind SDF layers: translation
    and rotation don't change distance values, **scaling does** -- after scaling that layer is no longer a correct SDF.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "translate_x": _f(0.0, -1e4, 1e4, 0.01),
            "translate_y": _f(0.0, -1e4, 1e4, 0.01),
            "rotate": _f(0.0, -1e6, 1e6, 1.0),
            "scale_x": _f(1.0, -1e4, 1e4, 0.01),
            "scale_y": _f(1.0, -1e4, 1e4, 0.01),
            "units": (list(_ctrn.UNITS),),
            "border": (list(_cflt.BORDERS),),
            "filter": (list(_ctrn.FILTERS),),
            "pivot_u": _sec("Pivot", _f(0.5, -10.0, 10.0, 0.01)),
            "pivot_v": _sec("Pivot", _f(0.5, -10.0, 10.0, 0.01)),
            "layers": ("STRING", {"default": "",
                                  "tooltip": "Empty = all layers, space separated"}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, translate_x, translate_y, rotate, scale_x, scale_y,
            units, border, filter, pivot_u, pivot_v, layers):
        return (_ctrn.transform(cop, (translate_x, translate_y), rotate,
                                (scale_x, scale_y), (pivot_u, pivot_v),
                                units, border, filter, layers),)


class PCG_COPFlip:
    """
    Flip. **No sampling**, indices are reversed directly, so it is bit-exact lossless.

    Vertical flips v -- COP row 0 is the **bottom**, so this is "upside down". Both
    on equals rotating 180° (and cheaper than COP Transform rotating 180°, though that's lossless too).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "horizontal": ("BOOLEAN", {"default": True}),
            "vertical": ("BOOLEAN", {"default": False}),
            "layers": ("STRING", {"default": ""}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, horizontal, vertical, layers):
        return (_ctrn.flip(cop, horizontal, vertical, layers),)


class PCG_COPCrop:
    """
    Crop, **and also pad**. The origin is at the **lower left** (consistent with all of COP).

    The window may extend outside the image; the outside is filled by Border -- so a negative X / Y plus a larger
    resolution pads outward, no extra node needed. The part inside the image is a bit-exact move.

    Typical uses: crop a 1024² composition to 832x1216 before SD generation; or the other way round, expand a render
    by a ring of black as an outpaint canvas.

    Compared with Houdini's Crop (pcg100): Mode has Discard and Reframe to Crop (the original
    behaviour) and Discard Cropped (resolution unchanged, outside the window discarded); Reframe to Crop needs
    a data window larger than the frame, which we can't represent. Units are Pixels / Texture / Image,
    Method is lower-left + size / lower-left + upper-right; Border gains Mirror. Aspect Ratio /
    Extract Tile / Min-Max Resolution / Reset Pixel Origin / geometry input not done.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "x": _i(0, -_cop.MAX_RES, _cop.MAX_RES),
            "y": _i(0, -_cop.MAX_RES, _cop.MAX_RES),
            "resolution_x": _i(512, 1, _cop.MAX_RES),
            "resolution_y": _i(512, 1, _cop.MAX_RES),
            # mirror appended at the end of Border (pcg100)
            "border": (list(_ctrn.CROP_BORDERS),),
            # pcg100: Houdini Crop's Mode / Units / Method / Pixel Padding.
            # Defaults (discard_reframe + pixels + lower_left_size + 0) = the original behaviour
            "mode": (list(_ctrn.CROP_MODES),),
            "units": (list(_ctrn.CROP_UNITS),),
            "method": (list(_ctrn.CROP_METHODS),),
            "corner": ("STRING", {"default": "0 0"}),
            "extent": ("STRING", {"default": "1 1"}),
            "pad_left": _i(0, 0, _cop.MAX_RES),
            "pad_right": _i(0, 0, _cop.MAX_RES),
            "pad_top": _i(0, 0, _cop.MAX_RES),
            "pad_bottom": _i(0, 0, _cop.MAX_RES),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, x, y, resolution_x, resolution_y, border,
            mode="discard_reframe", units="pixels", method="lower_left_size",
            corner="0 0", extent="1 1", pad_left=0, pad_right=0, pad_top=0,
            pad_bottom=0):
        if cop is not None and not (units == "pixels"
                                    and method == "lower_left_size"):
            # The four integer widgets X / Y / Resolution only cover "pixels + lower-left corner and size"
            # (which is what old workflows saved); other units / methods need fractions and read
            # the two vectors Corner / Extent
            from .geo.cop.pixel import _vec
            x, y, resolution_x, resolution_y = _ctrn.crop_window(
                cop.xres, cop.yres, units, method, _vec(corner, 2),
                _vec(extent, 2))
        return (_ctrn.crop(cop, x, y, resolution_x, resolution_y, border,
                           mode, (pad_left, pad_right, pad_top, pad_bottom)),)


class PCG_COPTile:
    """
    Tiles nx × ny copies; the output resolution becomes (W·nx, H·ny). Bit-exact copies, no resampling.

    With Mirror on, odd-numbered copies are mirrored -- the cheapest way to make any image tile seamlessly,
    at the cost of mirror symmetry in the frame; directional content (text, faces) gives it away.

    Different from COP Noise's Tile U: that makes the noise **function** periodic, resolution unchanged;
    this copies the image several times and the resolution grows.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "tiles_x": _i(2, 1, 64),
            "tiles_y": _i(2, 1, 64),
            "mirror_u": ("BOOLEAN", {"default": False}),
            "mirror_v": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, tiles_x, tiles_y, mirror_u, mirror_v):
        return (_ctrn.tile(cop, tiles_x, tiles_y, mirror_u, mirror_v),)


class PCG_COPDistort:
    """
    Distorts per pixel by a **vector image**: `out[p] = cop[p + amount · field[p]]`.

    This is the general form of "Distort by Noise" -- connect a Channels=2 COP Noise to the second input
    for noise distortion, a hand-drawn flow field for directional dragging, motion_bwd for an inter-frame warp.

    The direction is **inverse**: field says "where in the input this output position should fetch from", so the visual
    effect is **opposite** to "where pixels are pushed". The inverse mapping has no holes; for the forward look use a negative
    Amount (equivalent for small displacements, not for large ones; you can't have both).

    When Field's resolution differs it is first resampled to the main input, same rule as Composite.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,), "field": (COP,),
            "amount": _f(0.05, -1e4, 1e4, 0.005),
            "field_layer": ("STRING", {"default": "C"}),
            "units": (list(_ctrn.UNITS),),
            "border": (list(_cflt.BORDERS),),
            "filter": (list(_ctrn.FILTERS),),
            "layers": ("STRING", {"default": ""}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, field, amount, field_layer, units, border, filter,
            layers):
        return (_ctrn.distort(cop, field, amount, field_layer, units,
                              border, filter, layers),)


# ──────────────────────────────────────────────────────────── COP: value adjustment
class PCG_COPLevels:
    """
    Classic Levels. Default parameters are a **bit-exact identity**.

        t = (x − In Black) / (In White − In Black)
        t = t ^ (1 / Gamma)                    ← note it's 1/gamma
        out = Out Black + t · (Out White − Out Black)

    The exponent is inverted so that "dragging Gamma right = brighter" -- opposite to the intuition of `pow(x, gamma)`,
    but this is the established convention of Photoshop / Nuke / Houdini COP; written the other way, everyone would adjust it backwards
    the first time.

    **Clamp Input is on by default; turn it off for SDF / normals / HDR.** With it off t can be
    negative, and `(-0.3) ** 0.4545` gives **nan** in both numpy and torch -- a whole chain
    silently turns into a nan image, downstream blurs smear the nan around, and in the end you see all black and can't find the source. So
    when unclamped it uses `sign(t)·|t|^g`: continuous at 0, monotonic, odd-symmetric, which for an SDF is exactly "compress/stretch inside and outside
    symmetrically".

    Out Black 1 and Out White 0 is **invert**; for SDF processing,
    Out Black=0 / Out White=-1 negates (swaps inside and outside).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "in_black": _f(0.0, -1e6, 1e6, 0.01),
            "in_white": _f(1.0, -1e6, 1e6, 0.01),
            "gamma": _f(1.0, 0.001, 100.0, 0.01),
            "out_black": _f(0.0, -1e6, 1e6, 0.01),
            "out_white": _f(1.0, -1e6, 1e6, 0.01),
            "clamp_input": ("BOOLEAN", {"default": True}),
            "clamp_output": ("BOOLEAN", {"default": False}),
            "layers": ("STRING", {"default": ""}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, in_black, in_white, gamma, out_black, out_white,
            clamp_input, clamp_output, layers):
        return (_clev.levels(cop, in_black, in_white, gamma, out_black,
                             out_white, clamp_input, clamp_output, layers),)


class PCG_COPRemap:
    """
    Feeds values through a **ramp lookup table**. The syntax is exactly the same as COP Gradient / Attribute Fade
    (`"0:0  0.5:1  1:0"`; the right side of the colon can be `r,g,b`).

    Two behaviours, **chosen automatically by the Ramp's component count**, no switch:

      · Ramp has 1 component -> **per-channel** lookup, channel count unchanged. Grey curves, contrast,
        level compression all take this path
      · Ramp has multiple components -> the image is first reduced to a scalar t (T From: channel 0 / Rec.709 luminance),
        then N channels are looked up. **Grey to false colour** takes this path -- colouring SDFs, depth, noise,
        and "turning a distance field into rings of contour lines" are all this

    In Min / In Max are the range of t. For viewing an SDF use something like -20 / 20; values outside the range
    are clamped to the end colours.

    The lookup is done in numpy (the table has at most a few dozen points, not worth moving to VRAM); when the image is on CUDA there is
    a round trip here -- don't put it in a per-frame hot spot.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "ramp": ("STRING", {"default": "0:0  1:1", "multiline": False,
                                "tooltip": "position:value, space separated; value may be r,g,b"}),
            "ramp_mode": (list(_rmp.MODES),),
            "in_min": _f(0.0, -1e6, 1e6, 0.01),
            "in_max": _f(1.0, -1e6, 1e6, 0.01),
            "t_from": (list(_clev.T_FROM),),
            "layers": ("STRING", {"default": ""}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, ramp, ramp_mode, in_min, in_max, t_from, layers):
        return (_clev.remap(cop, ramp, ramp_mode, in_min, in_max, t_from,
                            layers),)


class PCG_COPQuantize:
    """
    Posterises into Steps discrete values. Cel shading, contour lines, the step before level dithering.

    `round(x·(N−1))/(N−1)`, so Steps=2 gives {0,1} and Steps=4 gives {0,⅓,⅔,1} --
    **both ends are kept**. Written as `floor(x·N)/N`, Steps=4 gives {0,¼,½,¾}, 1.0 can never
    be reached, and the brightest areas drop a level.

    Values outside Lo / Hi are **not clamped** and keep being quantised on the same grid -- so a quantised SDF gives
    equally spaced concentric bands, exactly what contour lines need.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "steps": _i(4, 1, 4096),
            "mode": (list(_clev.QUANT_MODES),),
            "lo": _f(0.0, -1e6, 1e6, 0.01),
            "hi": _f(1.0, -1e6, 1e6, 0.01),
            "layers": ("STRING", {"default": ""}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, steps, mode, lo, hi, layers):
        return (_clev.quantize(cop, steps, mode, lo, hi, layers),)


class PCG_COPFit:
    """
    Stretches the **measured** min/max to [Out Min, Out Max], and reports a line of statistics along the way.

    COP doesn't clamp, so "what range is my image actually in" is the question most worth asking before connecting Preview --
    noise is ±1, an SDF is ± a few hundred pixels, depth is in metres. Fit is the easiest way to take a look without
    knowing the range first.

    **Per Channel is off by default.** Off, all three channels share one range (keeping hue);
    on, each channel is stretched on its own and **colour relationships change** -- very useful when you want it, a disaster
    when you don't.

    A constant layer (min == max) outputs Out Min as is, no division by 0.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "out_min": _f(0.0, -1e6, 1e6, 0.01),
            "out_max": _f(1.0, -1e6, 1e6, 0.01),
            "per_channel": ("BOOLEAN", {"default": False}),
            "layers": ("STRING", {"default": ""}),
            "stats_layer": ("STRING", {"default": "C",
                                       "tooltip": "Which layer the statistics report looks at"}),
        }}
    RETURN_TYPES = (COP, "STRING"); RETURN_NAMES = ("cop", "stats")
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, out_min, out_max, per_channel, layers, stats_layer):
        name = stats_layer if stats_layer in cop else (
            cop.names[0] if len(cop) else "")
        txt = ""
        if name:
            s = _clev.stats(cop, name)
            txt = (f"{name}({s['channels']}ch)  min {s['min']:.6g}  "
                   f"max {s['max']:.6g}  mean {s['mean']:.6g}")
            if s["channels"] > 1:
                txt += ("\n  per-channel min " +
                        ", ".join(f"{v:.4g}" for v in s["cmin"]) +
                        "\n  per-channel max " +
                        ", ".join(f"{v:.4g}" for v in s["cmax"]))
            print("[PCG COP] " + txt.replace("\n", " | "))
        return (_clev.fit(cop, out_min, out_max, per_channel, layers), txt)


class PCG_COPLuminance:
    """
    RGB -> single-channel luminance (Rec.709: 0.2126 / 0.7152 / 0.0722), stored as a new layer.

    COP is **linear** internally, so plain weighting is right. Using the same weights on sRGB-encoded values is
    the most common mistake (they must be decoded first) -- which is also why it's worth remembering that COP Import doesn't do sRGB decoding
    by default.

    With fewer than 3 channels it takes channel 0 without error -- masks and SDFs connected here should just work.

    Compared with Houdini's Mono (pcg100): the Operation menu -- three sets of luminance weights, Average /
    Maximum / Minimum Channel, Magnitude, Hue / Saturation / Value, a single
    channel, Custom (Weights + Normalize Weights). Details in geo/cop/pixel.mono.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            "out_layer": ("STRING", {"default": "lum"}),
            # pcg100: Houdini Mono's Operation. Menu order follows Houdini (SGI / NTSC /
            # HDTV …); default hdtv = the previously hard-coded Rec.709
            "operation": (["sgi", "ntsc", "hdtv", "average", "max", "min",
                           "length", "hue", "saturation", "value", "red",
                           "green", "blue", "alpha", "custom"],
                          {"default": "hdtv"}),
            "weights": ("STRING", {"default": "0.2126 0.7152 0.0722 0"}),
            "normalize_weights": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, out_layer, operation="hdtv",
            weights="0.2126 0.7152 0.0722 0", normalize_weights=False):
        from .geo.cop.pixel import mono
        return (mono(cop, layer, out_layer, operation, weights,
                     normalize_weights),)


# ──────────────────────────────────────────────────────── COP: neighbourhood operators
class PCG_COPMorph:
    """
    Morphology: erode / dilate / open / close / gradient. Radius is in **pixels**.

    **Box is separable, Disc is not -- that's not implementation laziness, it's maths.** The minimum over a rectangular window
    equals "the minimum of the per-row minima", so it splits into two 1D passes, O(N·r); a disc is not a Cartesian product of row intervals
    and can't be split, so every offset in the window has to be enumerated: r=8 is 197 full-image mins,
    r=20 is 1257. That's the real cost of Disc.

    **For large radii don't use this node, use an SDF.** `COP SDF from Mask` followed by one
    `d − r` (Levels' In Black set to r) is a dilation of any radius, at a cost independent of the radius.
    The two are not "about the same" but **identical**: dilating a binary image by a disc of radius r is exactly
    `EDT ≤ r` -- the tests compare this bit by bit. The morphology node suits small fixes with r ≤ 8
    (removing burrs, filling small holes, extracting a ring of outline).

    Gradient is `dilate − erode`, giving an outline of thickness 2r on a binary mask.

    **Border has real consequences**: clamp (copy edges, default) keeps the image edges out of erosion;
    black treats outside as 0, so erosion **eats inward from all four edges**. Which is right depends on "is the outside of the image
    background"; there's no universal answer, so it's a parameter, not hard-coded.

    These operators hold on greyscale images too: erode is a local minimum, dilate a local maximum; on a height field
    that's flattening peaks / filling valleys.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "op": (list(_cmrp.OPS),),
            "radius": _i(2, 0, 64),
            "shape": (list(_cmrp.SHAPES),),
            "border": (list(_cflt.BORDERS),),
            "layers": ("STRING", {"default": ""}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, op, radius, shape, border, layers):
        return (_cmrp.morph(cop, op, radius, shape, border, layers),)


class PCG_COPEdge:
    """
    Edge detection. The main output is the **gradient magnitude**; with Components on, gx / gy / direction angle are added.

    **Kernels are normalised into true derivatives.** The Sobel kernel copied everywhere is integer, and its output is
    **8 times** the true gradient (Prewitt 6, Scharr 32). Without dividing that out, switching kernels changes the same image's
    edge strength by 4x, all thresholds need retuning, and the word "gradient" loses its meaning. Here it is always
    divided out; the cost is smaller values (integer-kernel edges look "brighter"), and the gain is: on an analytic slope
    `f = a·x + b·y`, gx is **exactly** a and gy exactly b (measured error 1e-16).

    Laplacian is not normalised -- it is `∂²f/∂x² + ∂²f/∂y²` to begin with; on `f = a·x²`
    it gives exactly 2a (measured error 0).

    **Multi-channel images get per-channel gradients**; the magnitude is the root of the sum of squares over all channels, not grey conversion first.
    At a red-green border luminance may barely change, and converting to grey first would lose that edge. If you want it by luminance, add
    COP Luminance first.

    Scale is a final multiplier. The default 1 gives the true per-pixel gradient; set 4~10 to see it directly.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            "method": (list(_cmrp.EDGE_METHODS),),
            "scale": _f(1.0, -1e4, 1e4, 0.1),
            "border": (list(_cflt.BORDERS),),
            "out_layer": ("STRING", {"default": "edge"}),
            "components": ("BOOLEAN", {"default": False}),
            "keep_layers": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, method, scale, border, out_layer, components,
            keep_layers):
        return (_cmrp.edge(cop, layer, method, border, scale, out_layer,
                           components, keep_layers),)


class PCG_COPSharpen:
    """
    Unsharp mask: `out = a + Amount · (a − blur(a, Sigma))`.

    Amount=0 is a **bit-exact** identity (skipped outright). A constant image is unchanged under any parameters --
    the blur of a constant is itself. Those two are this node's criteria.

    Sigma decides the scale of detail being sharpened: 0.5~1 brings out texture, 3~5 brings out outlines and volume.
    Amount above 2 produces halos on both sides of strong edges (overshoot) -- inherent to the algorithm, not a bug.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "amount": _f(1.0, -100.0, 100.0, 0.05),
            "sigma_pixels": _f(1.0, 0.0, 512.0, 0.1),
            "border": (list(_cflt.BORDERS),),
            "layers": ("STRING", {"default": ""}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, amount, sigma_pixels, border, layers):
        return (_cmrp.sharpen(cop, amount, sigma_pixels, border, layers),)


class PCG_COPMedian:
    """
    Median filter. Removes salt-and-pepper noise and specks on AI masks, and **doesn't smear edges like a blur does**.

    numpy-only (it needs sorting, and the backend operator table has no sort); when the image is on CUDA there's a round trip.
    And it is O(N·k²·log k): r=2 (13 samples) is already noticeably slower than blur, r=4 (49) much
    slower. **Don't use it as a blur**; the cap is locked at 8.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "radius": _i(1, 0, 8),
            "shape": (list(_cmrp.SHAPES),),
            "border": (list(_cflt.BORDERS),),
            "layers": ("STRING", {"default": ""}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, radius, shape, border, layers):
        return (_cmrp.median(cop, radius, shape, border, layers),)


class PCG_COPSDFFromMask:
    """
    Mask -> **signed distance field** (negative inside, positive outside, consistent with COP Shape). The most useful
    node in COP, because everything a distance field can do a black-and-white image can't:

        outline       |d| < w            width exact to sub-pixel, and resolution independent
        dilate/erode  d − r             r is in **pixels**, not "how much blur"
        feather       smoothstep(-w,w,d) edge width given directly, no guessing blur radii
        union/int/diff min / max          the result **is still** a correct distance field
        equal bands   Quantize(d)        contour lines, terrain layers, cel outlines

    In the SD pipeline it is the step that "turns an AI mask into a controllable geometric quantity": connect a segmentation mask,
    dilate by 8 pixels for an inpaint transition band, or take |d|<2 for a clean ring of outline
    to feed ControlNet.

    **Two implementations, with genuinely different trade-offs.**

      · **exact** (default) Felzenszwalb's lower envelope algorithm, two 1D scans, the result is
        **exact** Euclidean distance -- the tests compare point by point against brute-force O(N²), error 0.0.
        numpy-only (the algorithm is sequential and can't be turned into a chain of gathers)
      · **jfa** Jump Flooding, pure gathers, runs on numpy / torch / CUDA.
        The cost is that it is **inexact**. Compared per pixel with exact at 256²:

            sparse random seeds   plus=0 max 1.63 px / 0.028%, plus≥1 no error measured
            solid disc r=70       plus=0 0.263 px, plus=2 **0.189 px / 0.085%**

        The difference between the two rows is the thing to look at here: looking only at the sparse row you'd think JFA+1 is exact,
        but really the propagation distance from point seeds is too short to reach the range where JFA goes wrong. A solid shape immediately
        exposes an inherent 0.19 px miss, and raising plus to 4 doesn't improve it further. Good enough for outlines and
        dilation; for correctness use exact. Default plus is 2

      Counter-intuitive: **on numpy jfa is slower than exact** (a 1024² disc: 0.33 s vs
      3.1 s). JFA trades O(N log N) memory accesses for O(1) parallel depth, a deal that only pays off with
      thousands of cores. There's no reason to choose it on CPU.

    **Half Pixel (on by default).** Distance is measured per pixel centre, so pixels hugging the border measure
    1.0 on both sides, while the true border is at 0.5. The fix is subtracting 0.5 from each. For an analytic r=140 circle at 512²,
    the bias of the ring hugging the edge (0–1 px) drops from **+0.5464 to +0.0464**; the far field (40–100 px)
    overshoots slightly instead (+0.185 → −0.315), but distance field precision matters near the border anyway.

    Note: **the fix doesn't move the zero level set** (it is symmetric inside/outside, ±1 becomes ±0.5, the zero crossing
    doesn't move -- the interpolated radius is exactly 140.0000 under both settings). So for **thresholding** an SDF
    it makes no difference; it affects the **values**, and those are the reason to use an SDF.

    Units uv **divides by the short side**, same as COP Shape / aspect_coords -- so
    a circle drawn by Shape, baked into a mask and turned back, gives comparable values.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "mask"}),
            "threshold": _f(0.5, -1e6, 1e6, 0.01),
            "mode": (list(_csdf.MODES),),
            "sign": (list(_csdf.SIGNS),),
            "units": (list(_csdf.UNITS),),
            "half_pixel": ("BOOLEAN", {"default": True}),
            "out_layer": ("STRING", {"default": "sdf"}),
            "keep_layers": ("BOOLEAN", {"default": True}),
            "jfa_plus": _i(2, 0, 8),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, threshold, mode, sign, units, half_pixel,
            out_layer, keep_layers, jfa_plus):
        return (_csdf.sdf_from_mask(cop, layer, threshold, mode, sign, units,
                                    half_pixel, jfa_plus, out_layer,
                                    keep_layers),)


class PCG_RenderPass:
    """
    Camera + rasterisation, rendering geometry into COP layers. **The most important piece between PCG and diffusion models.**

    The ControlNet side relies entirely on depth, normals, line art and region maps as conditions, and PCG
    **computes these analytically**, not guessed by MiDaS. Having exact 3D information yet only feeding a shaded preview
    throws away the biggest advantage.

    **Why rasterisation rather than reusing ray_cast.** It was first written with the existing `spatial.ray_cast`
    (one ray per pixel, returning hit face + distance + barycentric coordinates, just enough for interpolation), but measured on
    a 5888-triangle sphere at 512²: perspective 0.58s, orthographic 4.41s. Ray intersection is O(pixels × acceleration
    structure), rasterisation is **O(covered pixels)**. Rendering should use rasterisation anyway, all the more so for per-frame video.
    After switching, 512² with six channels takes 0.17s, 1024² 0.7s.

    This doesn't violate the "don't write intersection twice" principle: rasterisation is a different class of algorithm (screen-space scan conversion).
    And with two independent implementations, the tests **use ray_cast as a per-pixel reference** -- coverage agrees to
    1.00000, perspective depth differs by 3e-14.

    Channels are all **raw, unclamped**: depth is camera-space distance (metres), normal is a signed unit vector,
    uv is the raw uv. Packing into 0-1 is Control Image's job -- that step is bound to ControlNet's
    conventions and shouldn't be mixed into rendering.

    **The camera-space third axis is −forward**, i.e. +Z points towards the viewer. The common normal-map convention is
    "facing the lens = (0,0,1) = that classic light blue after packing"; using +forward flips the whole image's blue channel,
    without an error, only the bumps in the output all point the wrong way.

    With Camera = frame, distance / orthographic size are set automatically from the geometry's bounding sphere -- "frame this object to fill the image
    and render a depth map" is the most common mode.

    **No near-plane clipping**; triangles crossing the near plane are just dropped whole. With the camera inside the object (panoramas,
    interiors) clipping must be added first; the frame mode normally never hits this.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "resolution_x": _i(512, 8, _cop.MAX_RES),
            "resolution_y": _i(512, 8, _cop.MAX_RES),
            "projection": (list(_rnd.PROJECTIONS),),
            "camera": (["frame", "orbit", "look_at"],),
            "fov": _f(45.0, 1.0, 179.0, 1.0),
            "ortho_size": _f(2.0, 1e-4, 1e6, 0.1),
            "elev": _f(25.0, -89.9, 89.9, 1.0),
            "azim": _f(35.0, -3600.0, 3600.0, 1.0),
            "distance": _f(5.0, 1e-4, 1e6, 0.1),
            "margin": _f(1.15, 0.5, 10.0, 0.01),
            "pass_depth": ("BOOLEAN", {"default": True}),
            "pass_mask": ("BOOLEAN", {"default": True}),
            "pass_normal": ("BOOLEAN", {"default": True}),
            "pass_shade": ("BOOLEAN", {"default": False}),
            "pass_position": _sec("More Passes",
                                  ("BOOLEAN", {"default": False})),
            "pass_uv": _sec("More Passes", ("BOOLEAN", {"default": False})),
            "pass_id": _sec("More Passes", ("BOOLEAN", {"default": False})),
            "pass_facing": _sec("More Passes",
                                ("BOOLEAN", {"default": False})),
            "target_x": _sec("Camera", _f(0.0, -1e6, 1e6, 0.1)),
            "target_y": _sec("Camera", _f(0.0, -1e6, 1e6, 0.1)),
            "target_z": _sec("Camera", _f(0.0, -1e6, 1e6, 0.1)),
            "eye_x": _sec("Camera", _f(0.0, -1e6, 1e6, 0.1)),
            "eye_y": _sec("Camera", _f(0.0, -1e6, 1e6, 0.1)),
            "eye_z": _sec("Camera", _f(5.0, -1e6, 1e6, 0.1)),
            "near": _sec("Camera", _f(0.01, 1e-6, 1e6, 0.01)),
            "far": _sec("Camera", _f(0.0, 0.0, 1e6, 0.1)),
            "normal_space": (list(_rnd.NORMAL_SPACES),),
            "normal_source": _sec("Attributes",
                                  (list(_rnd.NORMAL_SOURCES),)),
            "id_attribute": _sec("Attributes",
                                 _names("attrib", "prim", "name")),
            "uv_attribute": _sec("Attributes",
                                 _names("attrib", "vertex", "uv")),
            "cull": _sec("Attributes", (["none", "back", "front"],)),
            "group": _group(),
            "device": _dev("numpy"),
        }, "optional": {"cam": (CAM,)}}
    RETURN_TYPES = (COP, CAM); RETURN_NAMES = ("cop", "cam")
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, geo, resolution_x, resolution_y, projection, camera, fov,
            ortho_size, elev, azim, distance, margin, pass_depth, pass_mask,
            pass_normal, pass_shade, pass_position, pass_uv, pass_id,
            pass_facing, target_x, target_y, target_z, eye_x, eye_y, eye_z,
            near, far, normal_space, normal_source, id_attribute,
            uv_attribute, cull, group, device, cam=None):
        # If a Camera node is connected, use it, and all of our own parameters give way -- back-projection requires both sides
        # to use the same camera, and relying on "remember to change both sides" can never hold up long term
        if cam is None:
            cam = _rnd.camera(
                geo, projection=projection, eye=(eye_x, eye_y, eye_z),
                target=(target_x, target_y, target_z), fov=fov,
                ortho_size=ortho_size, xres=resolution_x, yres=resolution_y,
                near=near, far=far, orbit=(camera == "orbit"), elev=elev,
                azim=azim, distance=distance,
                frame_geometry=(camera == "frame"), margin=margin)
        want = [n for n, on in (("depth", pass_depth), ("mask", pass_mask),
                                ("normal", pass_normal),
                                ("position", pass_position),
                                ("uv", pass_uv), ("id", pass_id),
                                ("facing", pass_facing),
                                ("shade", pass_shade)) if on]
        if not want:
            want = ["mask"]
        return (_rnd.render(geo, cam, group, tuple(want), normal_space,
                            normal_source, id_attribute, uv_attribute,
                            cull, device), cam)


# ──────────────────────────────────────────────────── COP: the height-map family
def _hscale():
    """The pair of scale parameters shared by this family. **All eight nodes have the same defaults**, reasons in heightmap.py."""
    return {
        "strength": ("FLOAT", {"default": 1.0, "min": -1e4, "max": 1e4,
                               "step": 0.01, "tooltip":
                               "height value × strength = world height"}),
        "world_size": ("FLOAT", {"default": 1.0, "min": 1e-6, "max": 1e6,
                                 "step": 0.01, "tooltip":
                                 "World width of the whole image. Pixel spacing = world_size / width"}),
    }


class PCG_COPHeightToNormal:
    """
    Height map -> tangent-space normal (N layer, signed [-1,1], +Y = +v, OpenGL convention).

    With a grey height from a diffusion model / a height converted from albedo, this step gives a normal map;
    then feed COP Convert Normal (signed → packed) to export it, or connect it directly to ControlImage's
    normal mode for ControlNet.

    **Scale**: height value × Strength = world height, World Size = world width of the whole image. All eight nodes
    of this family share this pair of parameters with the same defaults -- once normals are tuned, using the same numbers for AO / shadows / caustics
    gives the same world.

    **Criterion**: on a slope `h = a·x + b·y`, the normal at **every** pixel (border ring included) is
    exactly normalize(−a, −b, 1). The border uses one-sided differences: central differences with clamp padding
    give only half the slope on the outermost ring, so a sloped tile would have a seam ring on each of its four edges.

    Tile on = periodic handling; turn it on for seamless textures. Sobel adds a smoothing pass, more stable on noisy AI
    heights; Central is sharper and exactly inverse to Normal to Height's exact mode.

    Multi-channel layers only use channel 0 -- convert colour images with COP Luminance first.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            **_hscale(),
            "method": (list(_chm.GRADIENTS),),
            "tile": ("BOOLEAN", {"default": False}),
            "out_layer": ("STRING", {"default": "N"}),
            "keep_layers": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, strength, world_size, method, tile, out_layer,
            keep_layers):
        return (_chm.height_to_normal(cop, layer, strength, world_size,
                                      method, tile, out_layer, keep_layers),)


class PCG_COPNormalToHeight:
    """
    Normal -> height (output mean 0). The inverse of Height to Normal -- with the same Strength /
    World Size the recovered height differs from the original only by a constant.

    Typical use: you only have a normal map (scanned, baked, AI-generated) and need a height for
    displacement / parallax / terrain.

    **Two integration modes, a real trade-off:**
      · spectral (default) Frankot–Chellappa. Robust on **inconsistent** normal maps (AI-generated,
        hand-painted -- they often correspond to no real surface). The cost is reduced detail amplitude:
        ripples with a 16-pixel period recover to 97.5%, 4-pixel ones only 64% (sin ω / ω, analytic)
      · exact is **exactly inverse per pixel** to Height to Normal (central, tile), but inconsistent
        input gets checkerboard patterns at high frequencies. Use it for round trips within your own chain

    With Tile off, mirror extension is used (equivalent to zero slope at the border), so a few pixels at the edges are approximate --
    **and then exact is actually worse**: on a slope spectral has 0.2% error, only at the edges, exact
    0.8% spread over the whole image (the mirror seam is inconsistent and amplified by exact's high-frequency weakness). Use exact with tile,
    spectral without.
    **Pixels with normal z ≤ 0.01 get clamped** (otherwise the slope explodes); how many is written in the report.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "N"}),
            **_hscale(),
            "method": (list(_chm.INTEGRATORS),),
            "tile": ("BOOLEAN", {"default": False}),
            "out_layer": ("STRING", {"default": "height"}),
            "keep_layers": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES = (COP, "STRING"); RETURN_NAMES = ("cop", "report")
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, strength, world_size, method, tile, out_layer,
            keep_layers):
        out, rep = _chm.normal_to_height(cop, layer, strength, world_size,
                                         method, tile, out_layer,
                                         keep_layers)
        n, tot = rep["clamped_nz"], rep["pixels"]
        msg = (f"{method}  {'tile' if tile else 'mirror extension'}  "
               f"z clamped on {n}/{tot} pixels"
               + ("" if n == 0 else " -- the slope of these pixels was capped at ±100. "
                  "Common causes: not a tangent-space normal (world / object-space z doesn't necessarily point up), "
                  "or Flip applied to a channel that shouldn't be flipped"))
        return (out, msg)


class PCG_COPHeightToAO:
    """
    Ambient occlusion on a height map. 1 = unoccluded, 0 = fully black.

    **Elevation is measured relative to the tangent plane**, not the horizontal. Relative to the horizontal, a whole slope looking uphill
    would be "blocked", while an infinite slope physically has no occlusion anywhere. So:
      · any slope (including very steep) has AO exactly 1
      · convex areas (peaks) have AO exactly 1
      · concave areas (pits, gullies) < 1, darker with higher curvature
    Scaling height and World Size together doesn't change AO by a single pixel (it only depends on angles).

    Radius is in **pixels**. The cost is Directions × Steps full-image operations (64 by default);
    with Tile off, samples outside the image don't participate, so no spurious dark ring appears at downhill edges.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            **_hscale(),
            "radius": _f(16.0, 0.5, 4096.0, 0.5),
            "directions": ("INT", {"default": 8, "min": 1, "max": 64}),
            "steps": ("INT", {"default": 8, "min": 1, "max": 64}),
            "intensity": _f(1.0, 0.0, 16.0, 0.05),
            "tile": ("BOOLEAN", {"default": False}),
            "out_layer": ("STRING", {"default": "ao"}),
            "keep_layers": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, strength, world_size, radius, directions,
            steps, intensity, tile, out_layer, keep_layers):
        return (_chm.height_to_ao(cop, layer, strength, world_size, radius,
                                  directions, steps, intensity, tile,
                                  out_layer, keep_layers),)


class PCG_COPHeightToShadow:
    """
    Shadows on a height map. **1 = in shadow** (mask semantics); turn on Invert to get 1 = lit,
    ready to multiply onto colour.

    Azimuth is the direction the light comes **from** (0° = from +u, 90° = from +v), Elevation is the
    sun's altitude angle. Criterion: for a wall of height H, the shadow length is exactly H / tan(elevation) (world
    scale), counted per pixel in the tests; at elevation = 90° there is not a single shadow pixel.

    Softness is the sun's angular radius (degrees), 0 = hard shadow. This is a first-order approximation of "the sun is a disk",
    not an area-light integral. Max Distance / Step are in pixels; each step is one full-image sample.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            **_hscale(),
            "azimuth": _f(45.0, -360.0, 360.0, 1.0),
            "elevation": _f(30.0, 0.1, 90.0, 0.5),
            "softness": _f(0.0, 0.0, 30.0, 0.1),
            "max_distance": _f(64.0, 1.0, 4096.0, 1.0),
            "step": _f(1.0, 0.1, 64.0, 0.1),
            "invert": ("BOOLEAN", {"default": False}),
            "tile": ("BOOLEAN", {"default": False}),
            "out_layer": ("STRING", {"default": "shadow"}),
            "keep_layers": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, strength, world_size, azimuth, elevation,
            softness, max_distance, step, invert, tile, out_layer,
            keep_layers):
        return (_chm.height_to_shadow(cop, layer, strength, world_size,
                                      azimuth, elevation, softness,
                                      max_distance, step, tile, invert,
                                      out_layer, keep_layers),)


class PCG_COPRefractFromHeight:
    """
    Looking straight down through a "water surface", how far things on the bottom appear to move -> a 2-channel **uv offset**.

    Feed COP Distort (Units = uv, Amount = 1, Field Layer = refract) for underwater
    distortion -- the offset is "where on the bottom the line of sight lands"; Distort already samples inversely, so no need to
    negate.

    Criteria: a calm surface gives exactly 0 offset; with IOR = 1 the offset is 0 however rough the surface; the offset is linear in Depth.
    No Fresnel, no absorption -- this is a distortion field, not a render.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            **_hscale(),
            "depth": _f(0.1, 0.0, 1e4, 0.01),
            "ior": _f(1.33, 1.0, 4.0, 0.01),
            "tile": ("BOOLEAN", {"default": False}),
            "out_layer": ("STRING", {"default": "refract"}),
            "keep_layers": ("BOOLEAN", {"default": True}),
            # pcg100 c7: Houdini Refract from Height's view / surface / bottom / sampling (defaults = old behaviour)
            "directional": ("BOOLEAN", {"default": True}),
            "view_azimuth": _f(0.0, -3600, 3600, 1),
            "view_altitude": _f(90.0, 0.01, 90.0, 1),
            "view_position": ("STRING", {"default": "0 0 10"}),
            "height_offset": _f(0.0, -1e6, 1e6, 0.01),
            "normal_layer": ("STRING", {"default": ""}),
            "normal_type": (list(_chm.REFRACT_NORMAL_TYPES),),
            "ground_layer": ("STRING", {"default": ""}),
            "ground_offset": _f(0.0, -1e6, 1e6, 0.01),
            "ground_scale": _f(1.0, -1e6, 1e6, 0.01),
            "ray_iterations": _i(8, 0, 256),
            "source_layer": ("STRING", {"default": ""}),
            "refract_out_layer": ("STRING", {"default": "refracted"}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, strength, world_size, depth, ior, tile,
            out_layer, keep_layers, directional=True, view_azimuth=0.0,
            view_altitude=90.0, view_position="0 0 10", height_offset=0.0,
            normal_layer="", normal_type="signed", ground_layer="",
            ground_offset=0.0, ground_scale=1.0, ray_iterations=8,
            source_layer="", refract_out_layer="refracted"):
        return (_chm.refract_from_height(cop, layer, strength, world_size,
                                         depth, ior, tile, out_layer,
                                         keep_layers, directional,
                                         view_azimuth, view_altitude,
                                         view_position, height_offset,
                                         normal_layer, normal_type,
                                         ground_layer, ground_offset,
                                         ground_scale, ray_iterations,
                                         source_layer, refract_out_layer),)


class PCG_COPHeightToCaustics:
    """
    Light spots focused onto the bottom by the water surface. **1 = brightness under a calm surface**, > 1 where light focuses.

    Photon tracing: each pixel emits Supersample² photons, refracted by the normal, landing on a bottom at Depth,
    splatted bilinearly into the four pixels around the landing point. More stable than "inverting the Jacobian" -- caustic lines are exactly where the Jacobian is 0,
    and the analytic approach divides by 0 there.

    Criteria: a calm surface gives exactly 1; with Tile, **energy is conserved** (the sum over all pixels is exactly the pixel count);
    a bump in the surface is a converging lens (> 1 directly below), a dimple a diverging lens (< 1).

    With oblique light, the calm-surface shift is subtracted as a whole so the light spots line up with the surface above. Tile is on by default:
    caustics are almost always used on seamless textures; with it off, photons landing outside the image are lost and the edges are darker.

    numpy-only (photon accumulation needs a deterministic bincount; atomic adds on the GPU have undefined order, so running the same
    image twice differs in the last digit).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            **_hscale(),
            "depth": _f(0.1, 0.0, 1e4, 0.01),
            "ior": _f(1.33, 1.0, 4.0, 0.01),
            "azimuth": _f(0.0, -360.0, 360.0, 1.0),
            "elevation": _f(90.0, 0.1, 90.0, 0.5),
            "supersample": ("INT", {"default": 2, "min": 1, "max": 8}),
            "tile": ("BOOLEAN", {"default": True}),
            "out_layer": ("STRING", {"default": "caustics"}),
            "keep_layers": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, strength, world_size, depth, ior, azimuth,
            elevation, supersample, tile, out_layer, keep_layers):
        return (_chm.height_to_caustics(cop, layer, strength, world_size,
                                        depth, ior, azimuth, elevation,
                                        supersample, tile, out_layer,
                                        keep_layers),)


class PCG_COPCombineNormals:
    """
    Stacks two normals: the large form (cop's Base Layer) + detail (the Detail Layer of the detail input;
    without a detail input it's taken from the same image). Both must be **signed** normals.

      rnm       Reoriented Normal Mapping. **Rotates** the detail into the large form's frame,
                so detail on steep slopes turns with the slope instead of being flattened. Default
      whiteout  add xy, multiply z. Cheap, detail is weaker on steep slopes
      udn       add xy, take z from the large form. Even cheaper
      linear    add directly and normalise. Kept only for comparison -- even a flat detail pulls the large form towards
                +z (weakening the slope), which is exactly why it is the worst

    Criteria: with flat detail rnm / whiteout / udn return the large form unchanged (linear doesn't); with a flat large form
    rnm returns the detail unchanged; the result is always a unit vector. Amount scales the detail (0 = no
    detail).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "base_layer": ("STRING", {"default": "N"}),
            "detail_layer": ("STRING", {"default": "N"}),
            "method": (list(_chm.BLENDS),),
            "amount": _f(1.0, 0.0, 16.0, 0.05),
            "out_layer": ("STRING", {"default": "N"}),
            "keep_layers": ("BOOLEAN", {"default": True}),
        }, "optional": {"detail": (COP,)}}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, base_layer, detail_layer, method, amount, out_layer,
            keep_layers, detail=None):
        return (_chm.combine_normals(cop, base_layer, detail, detail_layer,
                                     method, amount, out_layer,
                                     keep_layers),)


class PCG_COPConvertNormal:
    """
    Conversion between normal-map conventions. Fixed order: decode → reconstruct z → flip → normalise → encode.

      packed ↔ signed   texture files hold 0-1 colours, this plugin uses [-1,1] vectors internally.
                        Normal maps read from ComfyUI go packed → signed first
      Flip Green        OpenGL (+Y up, this plugin) ↔ DirectX (+Y down). Get it backwards and
                        the bumps invert in one direction, with no error
      Reconstruct Z     rebuild z = √(1 − x² − y²) from xy only (two-channel normal maps like BC5)

    Criteria: packed → signed → packed is the identity; flipping twice is a bit-exact identity. No tangent ↔ world space
    -- that needs a per-pixel tangent frame, which the height-map chain doesn't have.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            "decode": (list(_chm.ENCODINGS), {"default": "packed"}),
            "encode": (list(_chm.ENCODINGS), {"default": "signed"}),
            "flip_red": ("BOOLEAN", {"default": False}),
            "flip_green": ("BOOLEAN", {"default": False}),
            "reconstruct_z": ("BOOLEAN", {"default": False}),
            "normalize": ("BOOLEAN", {"default": True}),
            "out_layer": ("STRING", {"default": "N"}),
            "keep_layers": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, decode, encode, flip_red, flip_green,
            reconstruct_z, normalize, out_layer, keep_layers):
        return (_chm.convert_normal(cop, layer, decode, encode, flip_red,
                                    flip_green, reconstruct_z, normalize,
                                    out_layer, keep_layers),)


class PCG_COPErosion:
    """
    Erosion filter -- **not a simulation**. One pass, independent per pixel, looks as if washed by water:
    gullies and ridges running downhill, fine gullies branching along the walls of coarse ones. Runs on the GPU when there is one.

    The idea comes from Rune Skovbo Johansen's Advanced Terrain Erosion
    Filter (March 2026), **reimplemented from the description** (the original code is MPL-2.0 and was not copied).

    ━━ Compared with a real simulation, what's missing
    No continuous river network (a gully may stop halfway down a slope), no deposition, gully depth only looks at local slope, not
    upstream catchment. Those need flow accumulation, which is another (much slower) node.

    ━━ Parameters (scale consistent with the height-map family: height value × Strength = world height)
      Amplitude   depth of the coarsest gully layer (world units). × Gain per finer layer
      Wavelength  spacing of the coarsest gully layer (pixels). ÷ Lacunarity per finer layer
      Gain        default 0.35. 0.5 looks like the fractal-noise convention, but with Lacunarity 2 every layer's
                  gullies are equally steep and stack into fine cracks all over the screen
      Steepness   slope × this through an ease-out as the mask: larger means gentler slopes get gullies too
      Flow Blur   before each layer decides flow direction, the **input** slope is blurred to Flow Blur × that layer's wavelength.
                  When the input has fine noise (AI height maps almost always do), without blurring the fine noise
                  makes big gullies zigzag within one gully width, curling into "worms". Has almost no effect on
                  smooth input. 0 = the original's behaviour
      Fade        altitude: flat areas fade into ridges (high) / gullies (low) by height; none: flat areas
                  untouched
      Height Min/Max  the height range altitude uses. When equal, the image's own is used -- for tiled generation
                  give explicit ones, otherwise each tile uses its own

    Output: overwrites the input layer (no parameter changes needed for Height to Normal), plus an `erosion` layer
    ([-1,1], ridges > 0, gullies < 0) for texture layering.

    Seamless with Tile on; with it off, combined with Origin X/Y (world coordinate of this image's lower-left corner) it can generate
    in tiles that join without seams.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            **_hscale(),
            "amplitude": _f(0.01, 0.0, 1e4, 0.001),
            "wavelength": _f(48.0, 1.0, 4096.0, 1.0),
            "octaves": ("INT", {"default": 5, "min": 0, "max": 12}),
            "lacunarity": _f(2.0, 1.05, 8.0, 0.05),
            "gain": _f(0.35, 0.0, 2.0, 0.01),
            "steepness": _f(2.0, 0.0, 1e4, 0.1),
            "flow_blur": _f(0.25, 0.0, 4.0, 0.01),
            "fade": (list(_cero.FADES),),
            "height_min": _f(0.0, -1e6, 1e6, 0.01),
            "height_max": _f(0.0, -1e6, 1e6, 0.01),
            "rand_seed": ("INT", {"default": 0, "min": 0, "max": 1 << 31}),
            "tile": ("BOOLEAN", {"default": False}),
            "origin_x": _f(0.0, -1e6, 1e6, 0.01),
            "origin_y": _f(0.0, -1e6, 1e6, 0.01),
            "out_layer": ("STRING", {"default": "C"}),
            "mask_layer": ("STRING", {"default": "erosion"}),
            "keep_layers": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, strength, world_size, amplitude, wavelength,
            octaves, lacunarity, gain, steepness, flow_blur, fade,
            height_min, height_max, rand_seed, tile, origin_x, origin_y,
            out_layer, mask_layer, keep_layers):
        return (_cero.erode(cop, layer, strength, world_size, amplitude,
                            wavelength, octaves, lacunarity, gain, steepness,
                            flow_blur, fade, height_min, height_max,
                            rand_seed, tile, origin_x, origin_y, out_layer,
                            mask_layer, keep_layers),)


# ─────────────────────────────────────────────────────── COP: image analysis
class PCG_COPSlope:
    """
    Slope, aspect and downhill direction, three layers at once (leave a layer name empty to skip that layer).

      slope      degrees(0~90°)/ tangent(|∇h|)/ normalized(0~1)
      aspect     **downhill** direction in degrees, 0° = +u, 90° = +v. 0 on flat areas
      slope_dir  the downhill unit vector (u, v). Feed COP Distort for "drag downhill a bit"

    Slope and aspect are **exact per pixel** on slopes; derivatives pad the border by quadratic extrapolation, so even the border is
    exact on quadratic surfaces. Scale parameters are consistent with the height-map family.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            **_hscale(),
            "units": (list(_can.SLOPE_UNITS),),
            "tile": ("BOOLEAN", {"default": False}),
            "slope_layer": ("STRING", {"default": "slope"}),
            "aspect_layer": ("STRING", {"default": "aspect"}),
            "dir_layer": ("STRING", {"default": "slope_dir"}),
            "keep_layers": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, strength, world_size, units, tile,
            slope_layer, aspect_layer, dir_layer, keep_layers):
        return (_can.slope_aspect(cop, layer, strength, world_size, units,
                                  tile, slope_layer, aspect_layer, dir_layer,
                                  keep_layers),)


class PCG_COPCurvature:
    """
    Curvature, in 1/world units, **convex positive** (peaks, ridges > 0; pits, gullies < 0).

      mean        mean curvature
      gaussian    Gaussian curvature (saddles < 0, independent of convex/concave)
      profile     along the aspect: slope getting steeper (< 0) or gentler (> 0)
      tangential  perpendicular to the aspect: across, a ridge (> 0) or a gully (< 0)
      plan        bending of contour lines: water spreading (> 0) or converging (< 0)

    **Separate ridges and gullies with tangential / plan, not elevation** -- the elevation criterion flips on "gullies up high"
    and "ridges down low". Scale is a final multiplier: curvature changes with scale (1/R); multiplying by a
    characteristic length makes it dimensionless, good for masks.

    Criteria: on quadratic surfaces all five curvatures equal the analytic values per pixel (border included, quadratic extrapolation padding); a spherical cap's
    mean curvature converges to 1/R at second order; (profile + tangential)/2 is identically mean.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            **_hscale(),
            "kind": (list(_can.CURVATURES),),
            "tile": ("BOOLEAN", {"default": False}),
            "scale": _f(1.0, -1e6, 1e6, 0.001),
            "out_layer": ("STRING", {"default": "curvature"}),
            "keep_layers": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, strength, world_size, kind, tile, scale,
            out_layer, keep_layers):
        return (_can.curvature(cop, layer, strength, world_size, kind, tile,
                               scale, out_layer, keep_layers),)


class PCG_COPStatistics:
    """
    Per-layer, per-channel statistics: min / max / mean / std / percentiles, plus the **count of non-finite values**.

    nan / inf are excluded from the statistics but always reported -- a nan reaching downstream shows up as "some pixel
    turns black" or "the whole image turns nan", far from the source.

    Outputs: json (all numbers), report (human-readable), value (pick one number to feed straight into another node,
    e.g. as the score for Select Best, or into Param Pick). If Mask Layer is given, only pixels inside
    the mask are counted. std is the population standard deviation (÷N).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layers": ("STRING", {"default": "", "tooltip":
                       "Space separated; empty = all layers"}),
            "mask_layer": ("STRING", {"default": ""}),
            "percentiles": ("STRING", {"default": "1 50 99"}),
            "value_layer": ("STRING", {"default": "C"}),
            "value_channel": ("INT", {"default": 0, "min": 0, "max": 64}),
            "value_stat": (["mean", "std", "min", "max", "p50"],),
        }}
    RETURN_TYPES = (COP, "STRING", "STRING", "FLOAT")
    RETURN_NAMES = ("cop", "json", "report", "value")
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layers, mask_layer, percentiles, value_layer,
            value_channel, value_stat):
        try:
            pc = [float(x) for x in str(percentiles).replace(",", " ").split()]
        except ValueError as e:
            raise ValueError(f"Percentiles must be a list of numbers, e.g. '1 50 99': {e}")
        if "50" not in [f"{p:g}" for p in pc]:
            pc.append(50.0)
        res = _can.statistics(cop, layers, mask_layer, pc)
        st = res["layers"].get(str(value_layer).strip())
        if st is None:
            raise KeyError(f"Value Layer '{value_layer}' is not among the layers in the statistics: "
                           f"{list(res['layers'])}")
        ch = int(value_channel)
        if ch >= st["channels"]:
            raise ValueError(f"'{value_layer}' only has {st['channels']} channels")
        v = (st["percentiles"]["50.0"][ch] if value_stat == "p50"
             else st[value_stat][ch])
        return (cop, _can.dumps(res), _can.stats_report(res),
                float("nan") if v is None else float(v))


class PCG_COPHistogram:
    """
    Histogram equalisation / matching, done **by rank** (exact, no binning).

      equalize  each channel's values spread evenly by rank over its original [min, max]
      match     each channel replaced by the reference image's value **at the same percentile** -- when a batch of AI textures has
                inconsistent colours, match them all to the same reference

    The mapping preserves order; matching to itself is the identity; with equal pixel counts, the sorted output equals the sorted reference element by element.
    Flat-colour regions aren't stretched into gradients (ties get the average rank -- not doing this is the most classic pitfall of histogram equalisation).

    Channels are independent: matching RGB separately makes hue follow the reference too. To match only brightness, convert to luminance first.
    If Mask Layer is given, only pixels inside the mask are changed. numpy-only (needs sorting).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "mode": (list(_can.HIST_MODES),),
            "layers": ("STRING", {"default": "C"}),
            "ref_layer": ("STRING", {"default": "", "tooltip":
                          "Which layer to use on the reference image; empty = the layer with the same name"}),
            "mask_layer": ("STRING", {"default": ""}),
            "amount": _f(1.0, 0.0, 1.0, 0.01),
        }, "optional": {"reference": (COP,)}}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, mode, layers, ref_layer, mask_layer, amount,
            reference=None):
        return (_can.histogram(cop, mode, reference, layers, ref_layer,
                               mask_layer, amount),)


class PCG_COPSegment:
    """
    Mask -> an **id layer** of connected regions (0 = background, 1..K by area, largest first).

    Feed ID Masks for "one mask per piece" -> regional prompts: an AI-segmented black-and-white image contains
    several pieces, and this step separates and numbers them. The id order is deterministic (area descending, then by position),
    so the same mask always gets the same set of ids.

    Pieces below Min Area (pixels) are merged into the background -- AI masks always have stray dots at the edges. With Tile on,
    left/right and top/bottom edges are connected (a piece crossing the seam of a seamless texture counts as one).

    Done with "runs + union-find": the Python loop count is the **number of runs**, not pixels. numpy-only.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "mask"}),
            "threshold": _f(0.5, -1e6, 1e6, 0.01),
            "connectivity": (["8", "4"],),
            "min_area": _i(0, 0, 1 << 30),
            "tile": ("BOOLEAN", {"default": False}),
            "out_layer": ("STRING", {"default": "id"}),
            "keep_layers": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES = (COP, "INT", "STRING")
    RETURN_NAMES = ("cop", "count", "report")
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, threshold, connectivity, min_area, tile,
            out_layer, keep_layers):
        out, rep = _can.segment(cop, layer, threshold, int(connectivity),
                                min_area, tile, out_layer, keep_layers)
        top = ", ".join(str(a) for a in rep["areas"][:8])
        msg = (f"{rep['count']} pieces ({connectivity}-connected)"
               + (f", merged {rep['removed']} fragments < {min_area} pixels"
                  if rep["removed"] else "")
               + (f". Largest areas: {top}" if rep["count"] else ""))
        return (out, int(rep["count"]), msg)


class PCG_COPCompare:
    """
    Differences between two images: MAE / RMSE / PSNR / SSIM, plus a per-pixel diff layer and an SSIM map.

    Uses: comparing AI output with a reference, comparing the same flow before and after a parameter change, a score for automatic selection. SSIM looks at
    local structure (less sensitive to an overall brightness shift), PSNR / RMSE look at per-pixel values.

    SSIM uses the paper's standard settings (Gaussian window σ=1.5 → 11×11, K1=0.01, K2=0.03); Data Range
    is the width of the value range (1 for a 0-1 image). **The border is clamp** -- many implementations only average over the region where the window lies fully
    inside the image, so small differences when comparing numbers across tools are normal.

    When b's resolution differs it is first resampled to a; empty Layer B = same name as Layer A.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "a": (COP,), "b": (COP,),
            "layer_a": ("STRING", {"default": "C"}),
            "layer_b": ("STRING", {"default": ""}),
            "data_range": _f(1.0, 1e-9, 1e9, 0.01),
            "out_diff": ("STRING", {"default": "diff"}),
            "out_ssim": ("STRING", {"default": "ssim"}),
            "keep_layers": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES = (COP, "STRING", "FLOAT", "FLOAT", "STRING")
    RETURN_NAMES = ("cop", "report", "ssim", "psnr", "json")
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, a, b, layer_a, layer_b, data_range, out_diff, out_ssim,
            keep_layers):
        out, m = _can.compare(a, b, layer_a, layer_b, data_range, 1.5,
                              out_diff, out_ssim, keep_layers)
        ps = "∞" if math.isinf(m["psnr"]) else f"{m['psnr']:.2f} dB"
        msg = (f"SSIM {m['ssim']:.4f}  PSNR {ps}  RMSE {m['rmse']:.4g}  "
               f"MAE {m['mae']:.4g}  max diff {m['max_abs']:.4g}")
        # PSNR is inf when identical -- ComfyUI's FLOAT can carry it, but downstream math on it
        # goes wrong, so the FLOAT output is clamped to 999 dB, and json honestly says "inf"
        return (out, msg, float(m["ssim"]),
                999.0 if math.isinf(m["psnr"]) else float(m["psnr"]),
                _can.dumps(m))


# ─────────────────────────────────────────────────── COP: the HeightField family
class PCG_COPMaskByFeature:
    """
    Masks by terrain feature: height, slope, curvature (ridges / gullies), aspect, occlusion. Enabled criteria are combined by
    Blend Mode (default **multiply**; Add / Average / Minimum / Maximum as in Houdini).
    Smooth Radius (world units) blurs the height first, before measuring all features.

    Typical uses: rock on slopes ≥ 35°, gravel in gullies, snow on north slopes (Aspect Dir = 90° means
    downhill towards +v). Soft edges are all smoothstep; Falloff = 0 is a hard edge.

    **Separate ridges and gullies by curvature, not elevation** -- the elevation criterion flips on "gullies up high, ridges down low".
    Curvature is computed after blurring by Curv Blur pixels (pixel-level curvature is all noise), then normalised: when Curv
    Reference > 0 it is used (1/world units; required for tiled generation), otherwise the 90th percentile of this image's |curvature|
    -- threshold 0 exactly separates ridges and gullies, raise it for sharper ridges only.

    Scale parameters are consistent with the height-map family.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            **_hscale(),
            "tile": ("BOOLEAN", {"default": False}),
            "use_height": _sec("Height", ("BOOLEAN", {"default": False})),
            "height_min": _sec("Height", _f(0.0, -1e6, 1e6, 0.01)),
            "height_max": _sec("Height", _f(1.0, -1e6, 1e6, 0.01)),
            "height_falloff": _sec("Height", _f(0.0, 0.0, 1e6, 0.01)),
            "use_slope": _sec("Slope", ("BOOLEAN", {"default": True})),
            "slope_min": _sec("Slope", _f(20.0, 0.0, 90.0, 0.5)),
            "slope_max": _sec("Slope", _f(90.0, 0.0, 90.0, 0.5)),
            "slope_falloff": _sec("Slope", _f(5.0, 0.0, 90.0, 0.5)),
            "curvature": _sec("Curvature", (list(_ctr.CURV_MODES),)),
            "curv_threshold": _sec("Curvature", _f(0.0, -100.0, 100.0, 0.05)),
            "curv_falloff": _sec("Curvature", _f(0.3, 0.0, 100.0, 0.05)),
            "curv_blur": _sec("Curvature", _f(2.0, 0.0, 256.0, 0.5)),
            "curv_reference": _sec("Curvature", _f(0.0, 0.0, 1e9, 0.1)),
            "use_aspect": _sec("Aspect", ("BOOLEAN", {"default": False})),
            "aspect_dir": _sec("Aspect", _f(90.0, -360.0, 360.0, 1.0)),
            "aspect_spread": _sec("Aspect", _f(45.0, 0.0, 180.0, 1.0)),
            "aspect_falloff": _sec("Aspect", _f(15.0, 0.0, 180.0, 1.0)),
            "invert": ("BOOLEAN", {"default": False}),
            "out_layer": ("STRING", {"default": "mask"}),
            "keep_layers": ("BOOLEAN", {"default": True}),
            # pcg100: Houdini Mask by Feature's Blend Mode / Smooth Radius /
            # Mask by Occlusion section. Defaults = old behaviour
            "blend_mode": (list(_ctr.MASK_BLENDS),),
            "smooth_radius": _f(0.0, 0.0, 1e6, 0.01),
            "use_occlusion": _sec("Occlusion", ("BOOLEAN", {"default": False})),
            "occ_min": _sec("Occlusion", _f(0.2, 0.0, 1.0, 0.01)),
            "occ_max": _sec("Occlusion", _f(1.0, 0.0, 1.0, 0.01)),
            "occ_falloff": _sec("Occlusion", _f(0.0, 0.0, 1.0, 0.01)),
            "occ_height_scale": _sec("Occlusion", _f(1.0, 0.0, 1e6, 0.1)),
            "occ_radius": _sec("Occlusion", _f(0.1, 1e-6, 1e6, 0.01)),
            "occ_step_scale": _sec("Occlusion", _f(1.0, 0.01, 1e6, 0.1)),
            "occ_samples": _sec("Occlusion", _i(8, 1, 64)),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, strength, world_size, tile, use_height,
            height_min, height_max, height_falloff, use_slope, slope_min,
            slope_max, slope_falloff, curvature, curv_threshold,
            curv_falloff, curv_blur, curv_reference, use_aspect, aspect_dir,
            aspect_spread, aspect_falloff, invert, out_layer, keep_layers,
            blend_mode="multiply", smooth_radius=0.0, use_occlusion=False,
            occ_min=0.2, occ_max=1.0, occ_falloff=0.0, occ_height_scale=1.0,
            occ_radius=0.1, occ_step_scale=1.0, occ_samples=8):
        return (_ctr.mask_by_feature(
            cop, layer, strength, world_size, tile, use_height, height_min,
            height_max, height_falloff, use_slope, slope_min, slope_max,
            slope_falloff, curvature, curv_threshold, curv_falloff,
            curv_blur, curv_reference, use_aspect, aspect_dir, aspect_spread,
            aspect_falloff, invert, out_layer, keep_layers, blend_mode,
            smooth_radius, use_occlusion, occ_min, occ_max, occ_falloff,
            occ_height_scale, occ_radius, occ_step_scale, occ_samples),)


class PCG_COPTerrace:
    """
    Terraces: flat treads + steep risers (rice terraces, river terraces, layered rock). Done on the **height values**.

    The relative position within each step goes through a power function f^p, p = 1/(1 − Sharpness): 0 = identity,
    closer to 1 gives flatter treads and steeper risers, 1 is a pure staircase.

    Monotonically non-decreasing (high areas never end up lower than low ones); the step boundaries Offset + k·Step stay put;
    only cuts, never fills. If Mask Layer is given it blends by it (e.g. terraces only on steep slopes -- put a
    Mask by Feature in front).

    Houdini's Method: Number of Terraces = Terraces steps spread evenly over [Min, Max];
    Limit Range makes Step Size work only within that interval too. Random Step randomly moves each step's boundary
    (set by Seed). Mask is the blend amount (multiplied onto Mask Layer). Sharpness is our extension.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            "step": _f(0.1, 1e-6, 1e6, 0.01),
            "offset": _f(0.0, -1e6, 1e6, 0.01),
            "sharpness": _f(0.7, 0.0, 1.0, 0.01),
            "mask_layer": ("STRING", {"default": ""}),
            "out_layer": ("STRING", {"default": "C"}),
            "keep_layers": ("BOOLEAN", {"default": True}),
            # pcg100: Houdini HeightField Terrace's Method / Terraces / Min·Max
            # Height / Random Step / Step Seed / Mask. Defaults = old behaviour
            "method": (list(_ctr.TERRACE_METHODS),),
            "terraces": _i(10, 1, 100000),
            "limit_range": ("BOOLEAN", {"default": False}),
            "min_height": _f(0.0, -1e6, 1e6, 0.01),
            "max_height": _f(1.0, -1e6, 1e6, 0.01),
            "random_step": _f(0.0, 0.0, 1.0, 0.01),
            "rand_seed": _i(0, 0, 2 ** 31 - 1),
            "mask": _f(1.0, 0.0, 1.0, 0.01),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, step, offset, sharpness, mask_layer, out_layer,
            keep_layers, method="step_size", terraces=10, limit_range=False,
            min_height=0.0, max_height=1.0, random_step=0.0, rand_seed=0,
            mask=1.0):
        return (_ctr.terrace(cop, layer, step, offset, sharpness, mask_layer,
                             out_layer, keep_layers, method, terraces,
                             limit_range, min_height, max_height,
                             random_step, rand_seed, mask),)


class PCG_COPThermalErosion:
    """
    Thermal erosion / slumping: where steeper than the **angle of repose**, loose material slides down until it is back at the angle of repose.

    Different from the erosion filter: that one carves gullies, this one "slumps" over-steep slopes flat and piles talus at the foot.
    A common order is erosion filter → thermal erosion (slumping the over-steep gully walls the filter carved).

    **Mass is conserved** (total height unchanged at every step); terrain gentler than the angle of repose everywhere stays bit-exact; a tall column
    slumps into a cone whose face slope converges to the angle of repose.

    Hardness Layer (0~1) = bedrock, 1 doesn't move at all. Debris Layer outputs net deposition (scree
    slopes, talus), for texturing. The cost is Iterations × neighbour count full-image operations.
    With Compute = auto, runs on the GPU (float32) when there is a GPU and the image is large enough; the output goes back to the original backend.

    Houdini Slump's semantics are in Debris Source = layer / constant: the height is immovable bedrock,
    only the debris layer on top slides (bedrock shows once it has slid away); Debris Layer then outputs the remaining debris thickness.
    With Slump Mode = granular the amount moved per cell per step is randomised (set by Seed).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            **_hscale(),
            "talus_angle": _f(35.0, 0.0, 89.9, 0.5),
            "iterations": _i(50, 0, 100000),
            "rate": _f(0.5, 0.0, 1.0, 0.01),
            "neighbours": (["8", "4"],),
            "tile": ("BOOLEAN", {"default": False}),
            "hardness_layer": ("STRING", {"default": ""}),
            "out_layer": ("STRING", {"default": "C"}),
            "debris_layer": ("STRING", {"default": "debris"}),
            "keep_layers": ("BOOLEAN", {"default": True}),
            "compute": _compute(),
            # pcg100: Houdini HeightField Slump's Slump Mode / Random Seed /
            # debris input / Debris Scale / Remove·Add Debris. Defaults = old behaviour
            "slump_mode": (list(_ctr.SLUMP_MODES),),
            "rand_seed": _i(0, 0, 2 ** 31 - 1),
            "debris_source": (list(_ctr.DEBRIS_SOURCES),),
            "debris_input": ("STRING", {"default": "debris"}),
            "debris_scale": _f(1.0, 0.0, 1e6, 0.01),
            "remove_debris": ("BOOLEAN", {"default": False}),
            "add_debris": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, strength, world_size, talus_angle, iterations,
            rate, neighbours, tile, hardness_layer, out_layer, debris_layer,
            keep_layers, compute="auto", slump_mode="smooth", rand_seed=0,
            debris_source="height", debris_input="debris", debris_scale=1.0,
            remove_debris=False, add_debris=True):
        return (_ctr.thermal_erode(cop, layer, strength, world_size,
                                   talus_angle, iterations, rate,
                                   int(neighbours), tile, hardness_layer,
                                   out_layer, debris_layer, keep_layers,
                                   compute, slump_mode, rand_seed,
                                   debris_source, debris_input, debris_scale,
                                   remove_debris, add_debris),)


class PCG_COPHeightfieldToMesh:
    """
    Height field (COP) -> Y-up mesh. One point per **pixel centre**; Step decimates (no resampling).

    **v points to −Z (north)** -- in a Houdini-style top view (X right, Z down) the height map is upright.
    The `build.grid` / Heightfield from Image path used to have v towards +Z (the handedness
    issue recorded in pcg49); since pcg56 it is also unified to v towards −Z. Sampling the COP with the points' uv gets back the corresponding pixel's value **bit-exactly**,
    so with Scatter from Map / Attribute from Map the masks and terrain match exactly.

    Point normals come from the height-map gradient (the same operator as COP Height to Normal). Attribs carries other
    layers over as point attributes, space separated; `Cd=C`-style entries rename. Scale parameters are consistent with the height-map family:
    mesh width = World Size, height = height value × Strength.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            **_hscale(),
            "step": _i(1, 1, 1024),
            "center": ("BOOLEAN", {"default": True}),
            "normals": ("BOOLEAN", {"default": True}),
            "attribs": ("STRING", {"default": "", "tooltip":
                        "Space-separated layer names; dst=src renames, e.g. Cd=C erosion"}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, strength, world_size, step, center, normals,
            attribs):
        return (_ctr.to_mesh(cop, layer, strength, world_size, step, center,
                             normals, attribs),)


class PCG_COPFlowAccumulation:
    """
    Flow accumulation: how large an upstream area each pixel has (world units²). River networks, lakes and flow directions all come from this.

    Pits are filled first (Priority-Flood + ε): pits become lakes, every pixel is guaranteed a lower receiver, and water
    always reaches an outlet (the four edges by default; with tile, the global lowest point; with a Base Layer only that).
    Then water is passed downstream by D8 (the single steepest neighbour; rivers are one-pixel-wide lines at 0° / 45° only), Rho8 (randomised
    D8, unbiased mean direction, randomness set by Rand Seed) or MFD (split among all lower neighbours by slope^Exponent,
    sheet flow on slopes).

    Output layers: flow = catchment area (resolution independent in channels), river = a river-network mask with a soft logarithmic transition around River Area,
    lake = how deep it was filled, flow_dir = downstream direction (u, v). Leave a layer name empty to skip it.
    If Rain Layer is given, rain falls by its values (e.g. more on windward slopes).

    **Water is conserved**: the total leaving the outlets exactly equals total rainfall, as written in the report. 1024² takes about 3 s (pit filling is
    a sequential heap, pure CPU).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            **_hscale(),
            "method": (list(_cflw.METHODS),),
            "exponent": _f(1.1, 0.1, 20.0, 0.1),
            "fill_pits": ("BOOLEAN", {"default": True}),
            "tile": ("BOOLEAN", {"default": False}),
            "base_layer": ("STRING", {"default": ""}),
            "rain_layer": ("STRING", {"default": ""}),
            "river_area": _f(0.002, 1e-9, 1e6, 0.0001),
            "river_softness": _f(0.5, 0.01, 5.0, 0.05),
            "flow_layer": ("STRING", {"default": "flow"}),
            "river_layer": ("STRING", {"default": "river"}),
            "lake_layer": ("STRING", {"default": "lake"}),
            "dir_layer": ("STRING", {"default": "flow_dir"}),
            "keep_layers": ("BOOLEAN", {"default": True}),
            "rand_seed": _i(0, 0, 2 ** 31 - 1),
        }}
    RETURN_TYPES = (COP, "STRING")
    RETURN_NAMES = ("cop", "report")
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, strength, world_size, method, exponent,
            fill_pits, tile, base_layer, rain_layer, river_area,
            river_softness, flow_layer, river_layer, lake_layer, dir_layer,
            keep_layers, rand_seed=0):
        out, rep = _cflw.flow_accumulation(
            cop, layer, strength, world_size, method, exponent, fill_pits,
            tile, base_layer, rain_layer, river_area, river_softness,
            flow_layer, river_layer, lake_layer, dir_layer, keep_layers,
            rand_seed)
        if not rep:
            return (out, "")
        msg = (f"{method.upper()}: {rep['outlets']} outlet pixels, topological batches "
               f"{rep['batches']}; max catchment area {rep['max_flow']:.6g}")
        if fill_pits:
            msg += (f"; lakes {rep['lake_pixels']} pixels; rainfall "
                    f"{rep['rain_total']:.6g} → outlets {rep['outlet_total']:.6g}")
        else:
            msg += "; pits not filled, water in pit bottoms doesn't reach an outlet"
        return (out, msg)


class PCG_COPStreamPower:
    """
    Fluvial erosion (stream power law, FastScape-style implicit solve). ∂h/∂t = U − K·A^m·S.

    Difference from the erosion filter: this is a **simulation**, flow is recomputed every step -- big rivers cut deep, slopes barely
    move, and what grows is a continuous, hierarchical river network that reaches the outlets. The filter can't do this.

    Two uses: Uplift = 0 carves river valleys into existing terrain (tens of steps); Uplift > 0 "builds mountains" from
    noise, with uplift and erosion in balance (hundreds of steps). Uplift Layer multiplies the uplift (uplift only the middle →
    a mountain range). Diffusion rounds slopes and blunts divides.

    The implicit scheme is stable for any step size and never creates new pits (pits are filled once at the start, lakes filled flat as deposition).
    Outlets are a fixed base level. Routing defaults to rho8: D8 pulls the river network into straight 0° / 45° lines, rho8
    picks diagonals randomly each step with unbiased mean direction (reproducible with a fixed Rand Seed). Large flats left by filled lakes
    still get straight lines -- that's the ε slope of pit filling pointing to the nearest outlet, unrelated to routing.
    512² takes about 0.2 s per step, pure CPU. Flow Layer outputs the catchment area of the last step.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            **_hscale(),
            "iterations": _i(100, 0, 100000),
            "routing": (list(_cflw.ROUTINGS), {"default": "rho8"}),
            "erodibility": _f(0.02, 0.0, 10.0, 0.001),
            "area_exponent": _f(0.5, 0.0, 2.0, 0.05),
            "uplift": _f(0.0, 0.0, 10.0, 0.0001),
            "uplift_layer": ("STRING", {"default": ""}),
            "diffusion": _f(0.0, 0.0, 0.25, 0.005),
            "tile": ("BOOLEAN", {"default": False}),
            "base_layer": ("STRING", {"default": ""}),
            "out_layer": ("STRING", {"default": "C"}),
            "flow_layer": ("STRING", {"default": "flow"}),
            "rand_seed": _i(0, 0, 2 ** 31 - 1),
        }}
    RETURN_TYPES = (COP, "STRING")
    RETURN_NAMES = ("cop", "report")
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, strength, world_size, iterations, routing,
            erodibility, area_exponent, uplift, uplift_layer, diffusion,
            tile, base_layer, out_layer, flow_layer, rand_seed=0):
        out, rep = _cflw.stream_power(
            cop, layer, strength, world_size, iterations, erodibility,
            area_exponent, uplift, uplift_layer, diffusion, tile, base_layer,
            out_layer, flow_layer, routing, rand_seed)
        if not rep:
            return (out, "")
        msg = (f"{rep['iterations']} steps; topological batches in the last step {rep['batches']}; "
               f"pit refills {rep['refills']}")
        return (out, msg)


class PCG_COPHydraulicErosion:
    """
    Hydraulic erosion (with deposition): batches of droplets run downhill, speeding up on steep ground and picking up material, then dropping it where the slope eases,
    water evaporates and speed falls so they can no longer carry it -- gullies, alluvial fans and flat basin floors all
    grow this way. It is the only node in the terrain chain that **transports sediment**: the erosion filter carves without moving, thermal erosion only
    slumps to the angle of repose, stream power cuts without depositing.

    Beyer 2015's droplet model (parameter names follow Sebastian Lague's implementation). A Batch of droplets
    walks **simultaneously**, scatter-added and written back; hundreds of droplets merging into one gully in the same step would dig down together, so each cell
    can dig at most as low as its lowest neighbour and pile at most a little above its highest neighbour per step -- no pits dug, no spikes piled.
    The excess stays on the droplet, so **the material accounts balance droplet by droplet**: change in total terrain = −(material flowing out of the image edges),
    as written in the report.

    Droplets per Pixel 1 ≈ Lague's default amount. Deposit Layer (default debris) **accumulates** onto
    an existing debris layer -- placed after thermal erosion, talus and alluvium combine into one layer, and Splat Map's
    sediment reads it by default. Wetness is where more water passed than the baseline (a river / gully mask).
    Hardness Layer (0~1) = bedrock. With Compute = auto, when there is a GPU and the image is large enough (≥ 256²) it runs on the
    GPU (float32; results differ from CPU at rounding level, droplet paths are sensitive to rounding); on real hardware
    at 1024², numpy takes 160 s, CUDA 12 s. The output goes back to the original backend.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            **_hscale(),
            "droplets_per_pixel": _f(1.0, 0.0, 100.0, 0.05),
            "lifetime": _i(30, 1, 10000),
            "erode_rate": _f(0.3, 0.0, 1.0, 0.01),
            "deposit_rate": _f(0.3, 0.0, 1.0, 0.01),
            "capacity": _sec("Droplet", _f(4.0, 0.0, 1000.0, 0.1)),
            "inertia": _sec("Droplet", _f(0.05, 0.0, 0.99, 0.01)),
            "min_slope": _sec("Droplet", _f(0.01, 0.0, 10.0, 0.001)),
            "evaporate": _sec("Droplet", _f(0.01, 0.0, 0.99, 0.001)),
            "gravity": _sec("Droplet", _f(4.0, 0.0, 1000.0, 0.1)),
            "radius": _sec("Brush", _f(3.0, 1.0, 32.0, 0.5)),
            "deposit_radius": _sec("Brush", _f(0.0, 0.0, 32.0, 0.5)),
            "end_mode": _sec("Brush", (list(_chyd.END_MODES),)),
            "batch": _sec("Advanced", _i(16384, 1, 1 << 22)),
            "tile": ("BOOLEAN", {"default": False}),
            "hardness_layer": ("STRING", {"default": ""}),
            "rand_seed": _i(0, 0, 2 ** 31 - 1),
            "out_layer": ("STRING", {"default": "C"}),
            "deposit_layer": ("STRING", {"default": "debris"}),
            "accumulate_deposit": ("BOOLEAN", {"default": True}),
            "erosion_layer": ("STRING", {"default": ""}),
            "wet_layer": ("STRING", {"default": "wetness"}),
            "keep_layers": ("BOOLEAN", {"default": True}),
            "compute": _compute(),
        }}
    RETURN_TYPES = (COP, "STRING")
    RETURN_NAMES = ("cop", "report")
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, strength, world_size, droplets_per_pixel,
            lifetime, erode_rate, deposit_rate, capacity, inertia, min_slope,
            evaporate, gravity, radius, deposit_radius, end_mode, batch,
            tile, hardness_layer, rand_seed, out_layer, deposit_layer,
            accumulate_deposit, erosion_layer, wet_layer, keep_layers,
            compute="auto"):
        out, rep = _chyd.hydraulic_erode(
            cop, layer, strength, world_size, droplets_per_pixel, lifetime,
            inertia, capacity, min_slope, erode_rate, deposit_rate, evaporate,
            gravity, radius, deposit_radius, end_mode, batch, tile,
            hardness_layer, rand_seed, out_layer, deposit_layer,
            erosion_layer, wet_layer, accumulate_deposit, keep_layers,
            compute)
        if not rep:
            return (out, "")
        bal = rep["mass_after"] - rep["mass_before"] + rep["outflow"] \
            + rep["lost"]
        msg = (f"{rep['droplets']} droplets × up to {lifetime} steps; eroded "
               f"{rep['eroded']:.4g}, deposited en route {rep['deposited']:.4g}, at end of life "
               f"{'lost' if end_mode == 'lose' else 'spread'} "
               f"{rep['lost'] if end_mode == 'lose' else rep['dropped_at_end']:.4g},"
               f"outflow at image edges {rep['outflow']:.4g} (world volume); mass balance error {bal:.2e}; "
               f"computed on {rep.get('compute', '?')}")
        return (out, msg)


class PCG_COPSplatMap:
    """
    Terrain -> a full set of material masks that **sum to 1 everywhere**: grass / sediment / rock /
    snow / water. Engine terrain layering, Regional Prompt's regional prompts, and segmentation
    ControlNet (splat_id layer into Control Image's id mode) all use this set.

    Layered compositing, later layers cover earlier ones (water > snow > rock > sediment > grass); the five layers sum to exactly 1.
    Rock = steep slopes; snow = above the snow line and not too steep (snow doesn't stick on very steep ground); sediment = the debris layer (thermal
    erosion's output) or "low flat ground"; water = lake / river layers (Flow Accumulation's output).

    Height is normalised to this image by default (snow line 0.75 = the top quarter); for tiled generation that has to join, switch to
    absolute. Also outputs splat_id (index of the dominant material) and splat_rgba (rock / snow /
    sediment / water in four channels, grass implied).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            **_hscale(),
            "tile": ("BOOLEAN", {"default": False}),
            "height_mode": (list(_cspl.HEIGHT_MODES),),
            "rock_angle": _sec("Rock", _f(38.0, 0.0, 90.0, 0.5)),
            "rock_falloff": _sec("Rock", _f(6.0, 0.0, 45.0, 0.5)),
            "snow_line": _sec("Snow", _f(0.75, -1e6, 1e6, 0.01)),
            "snow_falloff": _sec("Snow", _f(0.08, 0.0, 1e6, 0.01)),
            "snow_max_slope": _sec("Snow", _f(50.0, 0.0, 90.0, 0.5)),
            "sediment_layer": _sec("Sediment", ("STRING",
                                                {"default": "debris"})),
            "sediment_ref": _sec("Sediment", _f(0.0, 0.0, 1e6, 0.001)),
            "flat_angle": _sec("Sediment", _f(8.0, 0.0, 90.0, 0.5)),
            "sediment_height": _sec("Sediment", _f(0.3, -1e6, 1e6, 0.01)),
            "water_layers": _sec("Water", ("STRING",
                                           {"default": "lake river"})),
            "lake_min": _sec("Water", _f(1e-4, 0.0, 1e6, 1e-5)),
            "lake_falloff": _sec("Water", _f(0.0, 0.0, 1e6, 1e-4)),
            "prefix": ("STRING", {"default": "splat"}),
            "keep_layers": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES = (COP, "STRING")
    RETURN_NAMES = ("cop", "report")
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, strength, world_size, tile, height_mode,
            rock_angle, rock_falloff, snow_line, snow_falloff, snow_max_slope,
            sediment_layer, sediment_ref, flat_angle, sediment_height,
            water_layers, lake_min, lake_falloff, prefix, keep_layers):
        out, rep = _cspl.splat_map(
            cop, layer, strength, world_size, tile, height_mode, rock_angle,
            rock_falloff, snow_line, snow_falloff, snow_max_slope,
            sediment_layer, sediment_ref, flat_angle, sediment_height,
            water_layers, lake_min, lake_falloff, prefix, keep_layers)
        if not rep:
            return (out, "")
        msg = "  ".join(f"{k} {rep[k] * 100:.1f}%" for k in _cspl.MATERIALS)
        msg += f" (sediment from {rep['_sediment_source']}; water from " \
            f"{' '.join(rep['_water_layers']) or 'none'})"
        return (out, msg)


def _encode_text(clip, text):
    """Same path as core CLIPTextEncode; older ComfyUI versions fall back to encode_from_tokens."""
    if clip is None:
        raise RuntimeError("clip is empty -- does the checkpoint have no text encoder?")
    tokens = clip.tokenize(text)
    if hasattr(clip, "encode_from_tokens_scheduled"):
        return clip.encode_from_tokens_scheduled(tokens)
    cond, pooled = clip.encode_from_tokens(tokens, return_pooled=True)
    return [[cond, {"pooled_output": pooled}]]


def _cond_with_mask(cond, mask, strength):
    """= core ConditioningSetMask (set_cond_area = default)."""
    out = []
    for t in cond:
        d = t[1].copy()
        d["mask"] = mask
        d["set_area_to_bounds"] = False
        d["mask_strength"] = float(strength)
        out.append([t[0], d])
    return out


class PCG_RegionalPrompt:
    """
    Writes prompts per region by COP layer: one node replaces "N CLIP Text Encode + N
    Conditioning Set Mask + N−1 Conditioning Combine".

    Regions: one `layer name: prompt` per line. Mode: normalized (default) = these layers **are already a
    partition** (Splat Map's output), used as is, and normalised wherever they happen to sum above 1;
    layered = independent masks (several Mask by Feature), layered in writing order,
    **later entries cover earlier ones**. Base by default only covers "what's left" (remainder), so all masks
    sum to exactly 1 everywhere.

    Why this matters: when ComfyUI samples, masked conditionings are **averaged weighted by mask value**.
    A pixel covered by none of them gets a prediction of 0 there -- a blurred-out hole in the output, without an error;
    with an unmasked Base (global) it takes part in the average everywhere, diluting the regional prompts' strength by half.

    Masks are composited in COP orientation and v is flipped at the exit (the same boundary as Control Image), so they
    align per pixel with depth / normal control images from the same COP. The masks output is each region's effective mask
    (one batch, order = writing order); preview is a coloured partition image.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "clip": ("CLIP",),
            "cop": (COP,),
            "base_prompt": ("STRING", {"multiline": True, "default":
                                       "aerial orthographic view of a "
                                       "landscape, highly detailed terrain "
                                       "texture, satellite photo"}),
            "regions": ("STRING", {"multiline": True, "default":
                                   "splat_sediment: gravel riverbed, sand, "
                                   "alluvial deposits\n"
                                   "splat_rock: bare granite cliffs, scree\n"
                                   "splat_snow: fresh snow, glacier ice\n"
                                   "splat_water: clear blue river water"}),
            "strength": _f(1.0, 0.0, 10.0, 0.01),
            "mode": (list(_creg.MODES),),
            "base": (list(_creg.BASE_MODES),),
            "feather": _f(1.0, 0.0, 64.0, 0.5),
        }}
    RETURN_TYPES = ("CONDITIONING", "IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("conditioning", "preview", "masks", "report")
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, clip, cop, base_prompt, regions, strength, mode, base,
            feather):
        torch = convert.need("torch", "Regional Prompt (to hand out CONDITIONING)")
        entries = _creg.parse(regions)
        effs, rest = _creg.region_masks(cop, entries, mode, feather)
        def _m(a):
            return torch.from_numpy(np.ascontiguousarray(
                a[::-1], np.float32))[None]

        cond = []
        lines = []
        for (name, prompt), e in zip(entries, effs):
            cov = float(e.mean())
            if float(e.max()) <= 1e-6:
                lines.append(f"  {name}: empty, skipped")
                continue
            cond += _cond_with_mask(_encode_text(clip, prompt), _m(e),
                                    strength)
            lines.append(f"  {name}: {cov * 100:.1f}%")
        if base == "global":
            cond = _encode_text(clip, base_prompt) + cond
            lines.append("  base: whole image (global)")
        elif float(rest.max()) > 1e-6:
            cond = _cond_with_mask(_encode_text(clip, base_prompt), _m(rest),
                                   strength) + cond
            lines.append(f"  base: remainder {float(rest.mean()) * 100:.1f}%")
        else:
            lines.append("  base: remainder is empty, unused")
        if not cond:
            cond = _encode_text(clip, base_prompt)
        tot = rest + (sum(effs) if effs else 0.0)
        lines.insert(0, f"{len(entries)} regions, {mode}; mask sum "
                     f"{float(np.min(tot)):.3f}~{float(np.max(tot)):.3f}")
        pv = _creg.preview(effs, rest)
        masks = np.stack([e for e in effs], 0) if effs else rest[None]
        return (cond,
                torch.from_numpy(np.ascontiguousarray(pv[::-1][None],
                                                      np.float32)),
                torch.from_numpy(np.ascontiguousarray(masks[:, ::-1],
                                                      np.float32)),
                "\n".join(lines))


class PCG_COPHeightfieldFromDepth:
    """
    Depth of an image -> a top-down height field. AI paints a valley -> MoGe / Depth Anything estimates
    depth -> spread into a height field here -> the whole terrain chain follows: erosion, river networks, Splat Map, conversion to mesh.

    **perspective** (landscape photos, AI-painted perspective images):
      · connect moge_geometry (the output of core MoGeInference, **recommended**): camera-space points,
        metric scale and the sky mask are all ready-made, nothing to guess
      · or connect depth (an IMAGE like Depth Anything's): relative inverse depth is only determined up to scale and
        shift, z = 1/(d + Shift) is a guess; FOV has to be filled in by hand too. Guess wrong and the terrain gets bent, not
        uniformly scaled
      An 8-bit depth map (Depth Anything through comfyui_controlnet_aux is one) is first smoothed back to continuous values
      within its 256 levels (Dequantize) -- otherwise every level lands as one arc and the far field turns into streaks.
      A ground plane is fitted weighted by ground area (z²), and the camera pitch is solved automatically; top-down rasterisation takes the
      mean height per cell, and unseen areas (behind hills, sparse in the distance) are filled by push-pull -- the mask layer marks which were
      actually measured; **the filled parts are guesses**
    **top_down** (satellite images, AI-painted orthographic maps): depth is used directly as height, normalised to Relief ×
    World Size.

    Connect the original to image to also get an albedo layer (colour projected top-down; MoGe carries the original, so it can be left unconnected).
    Connect the world_size output to the world_size of the HeightField family and the scales match.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "mode": (list(_clift.MODES),),
            "resolution": _i(512, 8, 8192),
            "depth_kind": (list(_clift.DEPTH_KINDS),),
            "fov_x": _f(60.0, 1.0, 170.0, 0.5),
            "shift": _sec("Disparity", _f(0.05, 0.0, 10.0, 0.005)),
            "sky": _sec("Disparity", _f(0.02, 0.0, 1.0, 0.005)),
            "up": (list(_clift.UP_MODES),),
            "far_quantile": _f(0.95, 0.05, 1.0, 0.01),
            "fill_holes": ("BOOLEAN", {"default": True}),
            "relief": _sec("Top Down", _f(0.25, 0.0, 100.0, 0.01)),
            "world_size": _sec("Top Down", _f(1.0, 1e-6, 1e9, 0.01)),
            "batch_index": _i(0, 0, 4096),
            "dequantize": ("BOOLEAN", {"default": True}),
        }, "optional": {
            "depth": ("IMAGE",),
            "moge_geometry": ("MOGE_GEOMETRY",),
            "image": ("IMAGE",),
        }}
    RETURN_TYPES = (COP, "FLOAT", "STRING")
    RETURN_NAMES = ("cop", "world_size", "report")
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, mode, resolution, depth_kind, fov_x, shift, sky, up,
            far_quantile, fill_holes, relief, world_size, batch_index,
            dequantize=True, depth=None, moge_geometry=None, image=None):
        out, L, rep = _clift.lift(depth, moge_geometry, image, mode,
                                  resolution, depth_kind, fov_x, shift, sky,
                                  up, far_quantile, fill_holes, relief,
                                  world_size, batch_index, dequantize)
        if mode == "top_down":
            msg = f"top_down: world width {L:.4g}"
        else:
            msg = (f"{rep['source']}: {rep['points']} points, coverage "
                   f"{rep['coverage'] * 100:.1f}% (the rest is filled in); world width "
                   f"{L:.4g}, height range {rep['height_range']:.4g}; "
                   f"{rep['up_mode']}")
            if "camera_pitch_deg" in rep:
                msg += f", camera pitch {rep['camera_pitch_deg']:.1f}°"
            if rep.get("dequantized"):
                msg += "; 8-bit depth dequantized"
            if rep["coverage"] < 0.3:
                # Far fewer points than cells -- most heights are guessed by push-pull.
                # The example workflow on a 320×240 test image only measures 10% at 512²
                msg += (f". Coverage too low: {rep['points']} points spread over "
                        f"{resolution}² cells; lower Resolution or raise the "
                        "depth map resolution")
        return (out, float(L), msg)


class PCG_ControlImage:
    """
    COP layers -> IMAGE + MASK, packed by ControlNet conventions. **A semantic conversion layer.**

    The type conversion is mechanical (ten lines in COP Export); the hard part is the **conventions** -- the same depth map with
    the direction reversed, the wrong space, or one extra transfer curve makes the output ignore you completely, and **without an error**.
    So these conventions are concentrated in one node.

    **depth: near = white, and it's inverse depth.** Depth ControlNets were trained on MiDaS-style outputs,
    which are relative **inverse** depth: near bright, far dark. The camera-space z a renderer gives is larger far away --
    sent directly it's exactly reversed, and the model reads front and back the wrong way round. The normalisation range defaults to the min/max of pixels **inside the mask**
    (equivalent to "relative depth", automatically fitting the object's thickness); for animation, to avoid per-frame flicker, fill in
    near/far by hand. The background gets **0** (farthest = black); with 1 the model would think something is right against the lens around the frame.

    **height (pcg56): top-down depth map of a height field, high = white.** Seen from straight above, what's close to the camera
    is high. Putting a height layer into the depth mode gets it **reversed** (mountains become pits, no error), hence a separate mode.
    near/far in this mode are the height range filled in by hand (leave 0 = auto). For top-down use the normal mode directly with
    Height to Normal's N layer: a tangent-space normal is the camera-space normal of a top-down camera.

    **normal: packed n*0.5+0.5, background (0.5,0.5,1).** The space must be camera space
    (Render Pass default). Whether green points up or down is historical (OpenGL +Y up /
    DirectX +Y down), and normal ControlNets disagree, so there's a switch instead of pretending there's a
    universal default. **The symptom is bumps inverted as a whole**, not a crash.

    **lineart: extracted from depth and normal discontinuities, not image edge detection.** The mask gradient = outer
    silhouette (a clean 0/1 step, strength independent of object distance), depth gradient = internal occlusion edges, normal
    gradient = creases. Much cleaner than "render an image then Canny" -- Canny treats materials, noise and shading
    gradients all as edges. And silhouettes and creases can be weighted separately: architecture wants creases, characters want silhouettes.

    **id: hues spread by the golden angle.** Random spreading collides (birthday problem), and equal hue division needs the total in advance.

    **Linear vs sRGB.** COP is linear internally, while the VAE saw sRGB-style 0-1 in training:
    depth / normal / lineart / id are **data**; ControlNet was trained in this packed space,
    so **don't** add a curve; only color for img2img needs it (without it linear 0.5 would be taken as a much darker
    mid-grey). So srgb is on by default only in the color mode.

    **Resolution aligned to 8.** The latent is downsampled /8, and a non-multiple of 8 gets silently rescaled somewhere.
    Here it is actively resized to the **nearest** multiple of 8 (moving at most 4 pixels); align=0 turns it off.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "kind": (list(_cctl.KINDS),),
            "layer": ("STRING", {"default": "",
                                 "tooltip": "Empty = default layer for the kind"}),
            "mask_layer": ("STRING", {"default": "mask"}),
            "invert": ("BOOLEAN", {"default": False}),
            "align": _i(8, 0, 256),
            "near": _sec("Depth", _f(0.0, 0.0, 1e6, 0.01)),
            "far": _sec("Depth", _f(0.0, 0.0, 1e6, 0.01)),
            "gamma": _sec("Depth", _f(1.0, 0.05, 20.0, 0.05)),
            "background": _sec("Depth", _f(0.0, -1e4, 1e4, 0.01)),
            "flip_r": _sec("Normal", ("BOOLEAN", {"default": False})),
            "flip_g": _sec("Normal", ("BOOLEAN", {"default": False})),
            "flip_b": _sec("Normal", ("BOOLEAN", {"default": False})),
            "silhouette": _sec("Lineart", _f(1.0, 0.0, 100.0, 0.05)),
            "crease": _sec("Lineart", _f(1.0, 0.0, 100.0, 0.05)),
            "threshold": _sec("Lineart", _f(0.2, 1e-4, 100.0, 0.005)),
            "softness": _sec("Lineart", _f(0.5, 0.0, 10.0, 0.05)),
            "thickness": _sec("Lineart", _i(1, 1, 32)),
            "saturation": _sec("ID", _f(0.65, 0.0, 1.0, 0.01)),
            "value": _sec("ID", _f(0.95, 0.0, 1.0, 0.01)),
            "srgb": ("BOOLEAN", {"default": False,
                                 "tooltip": "Off for control images; on for colour images going to img2img"}),
            # pcg90 addition (placed last, old workflow indices unchanged):
            # the color mode used to encode regardless of whether srgb was on, so the switch did nothing. The color mode gets its own switch, on by default --
            # old workflows don't have this item, so it takes the default and the result is the same as before
            "color_srgb": ("BOOLEAN", {"default": True,
                                       "tooltip": "Color mode: encode to sRGB (on for img2img)"}),
            # lineart's normal layer used to be hard-coded "N"
            "normal_layer": _sec("Lineart", ("STRING", {"default": "N"})),
        }}
    RETURN_TYPES = ("IMAGE", "MASK"); RETURN_NAMES = ("image", "mask")
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, kind, layer, mask_layer, invert, align, near, far,
            gamma, background, flip_r, flip_g, flip_b, silhouette, crease,
            threshold, softness, thickness, saturation, value, srgb,
            color_srgb=True, normal_layer="N"):
        img, msk = _cctl.control_image(
            cop, kind, layer, mask_layer, near, far, invert, gamma,
            background, flip_r, flip_g, flip_b, silhouette, crease,
            threshold, softness, thickness, saturation, value,
            bool(color_srgb if kind == "color" else srgb), align,
            normal_layer=normal_layer)
        return (_cbrg.as_torch(img), _cbrg.as_torch(msk))


class PCG_IDMasks:
    """
    id image -> **a batch** of MASKs, one per region.

    ComfyUI's MASK is (B,H,W), so "one mask per region" is naturally a batch. Feed
    ConditioningSetMask for **regional prompts**: "this brick fragment is terracotta, that one is moss", with
    geometrically exact borders, not brush-painted -- something image methods simply can't do.

    ids come from Render Pass's id channel, which reads prim attributes (`name` / `piece` /
    `cluster`) -- Voronoi Fracture, Voronoi Cluster, Convex Decompose and
    Connectivity all write these.

    Above Max Regions, the largest by **area** are kept, not by id value -- truncating by id
    would cut off the main subject.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "id"}),
            "mask_layer": ("STRING", {"default": "mask"}),
            "max_regions": _i(64, 1, 4096),
        }}
    RETURN_TYPES = ("MASK", "INT", "STRING")
    RETURN_NAMES = ("masks", "count", "ids")
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, layer, mask_layer, max_regions):
        m, ids = _cctl.id_masks(cop, layer, mask_layer, max_regions)
        return (_cbrg.as_torch(m), int(len(ids)),
                " ".join(str(int(v)) for v in ids))


class PCG_COPWarp:
    """
    Warps one frame to another frame's position by motion vectors (**backward** warp).

        out[p] = image[p + motion[p]]

    So it must take `motion_bwd`. Passing forward vectors gives an image warped the wrong way -- at small displacements
    it looks "about right"; only in motion do you see the smear goes the wrong way, so the default layer name is hard-coded to
    motion_bwd to block this up front.

    The most direct use: warp the previous frame's AI output to this frame's position, as the img2img init or
    ControlNet reference, with the `disocclusion` layer serving as the repaint mask. Measured with a sphere rotating 10°/frame,
    the reconstruction error after warping is **49 times** smaller than using the previous frame unwarped (0.0028 vs 0.137).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "motion": (COP,),
            "layer": ("STRING", {"default": "C"}),
            "motion_layer": ("STRING", {"default": _seq.MOTION_BWD_LAYER}),
            "units": (list(_seq.UNITS),),
            "edge": (list(_seq.EDGES),),
            "filter": (list(_fmp.FILTERS),),
            "device": _dev("numpy"),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, cop, motion, layer, motion_layer, units, edge, filter,
            device):
        return (_seq.warp(cop, motion, layer, motion_layer, units, edge,
                          filter, device),)


class PCG_SequenceExport:
    """
    COP sequence -> ComfyUI IMAGE (B,H,W,3) + MASK (B,H,W). B is the frames.

    **The normalize mode computes min/max over the whole sequence, not per frame.** Per-frame normalisation makes brightness
    jump frame to frame -- static objects seem to breathe, and since each frame looks "fine" on its own, this
    bug is especially hard to pin down. Depth sequences fall into it most easily: per-frame normalisation squashes an approaching object back to its original look.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "seq": (COPSEQ,),
            "layer": ("STRING", {"default": "C"}),
            "mode": (list(_cbrg.EXPORT_MODES),),
            "mask_layer": ("STRING", {"default": "mask"}),
        }}
    RETURN_TYPES = ("IMAGE", "MASK", "INT")
    RETURN_NAMES = ("images", "masks", "frames")
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, seq, layer, mode, mask_layer):
        img = _seq.to_batch(seq, layer, mode)
        m = np.concatenate([_mask_or_ones(im, mask_layer, img.shape[1:3])
                            for im in seq], 0)
        return (_cbrg.as_torch(img), _cbrg.as_torch(m), len(seq))


class PCG_SequenceImport:
    """ComfyUI IMAGE (B,H,W,C) -> COP sequence. B is the frames. v is still flipped only at this layer."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "images": ("IMAGE",),
            "layer": ("STRING", {"default": "C"}),
            "device": _dev("numpy"),
        }}
    RETURN_TYPES = (COPSEQ, "INT"); RETURN_NAMES = ("seq", "frames")
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, images, layer, device):
        seq = _seq.from_batch(images, layer, True, device)
        return (seq, len(seq))


class PCG_SequencePick:
    """
    Takes one frame from a sequence. Out-of-range indices **wrap around** without error -- going out of range while dragging index to view previews
    is normal, and an error would break the whole chain.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "seq": (COPSEQ,),
            "index": _i(0, 0, 1 << 20),
        }}
    RETURN_TYPES = (COP, "INT"); RETURN_NAMES = ("cop", "frames")
    FUNCTION = "run"; CATEGORY = CAT + "/cop"

    def run(self, seq, index):
        if not seq:
            raise ValueError("The sequence is empty")
        return (seq[int(index) % len(seq)], len(seq))
