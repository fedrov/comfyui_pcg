"""
COP generators: constant colour, noise, shapes (SDF), gradients.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Noise reuses the geometry-side implementation directly -- not for convenience, but for **alignment**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`attribnoise.fractal_noise` takes (n,3) world coordinates. Each image pixel is also given a
3D coordinate (uv mapped onto a plane, z given by Offset), so:

    **For the same world coordinate, the noise value sampled on the image is identical to the one sampled on geometry.**

This is not a coincidence but the inevitable result of sharing one implementation, and it is the most useful property of this batch: with the same
parameters, bake a displacement map on one side and actually push the geometry out on the other, and the two match seamlessly. The tests compare
4096 positions point by point, max error 0 (not "very small", but 0 -- it is the same function).

Conversely, if someday someone wants to write a "faster image-only noise" for COP, they must first decide whether this property
should be kept.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Shapes output an **SDF**, not a black-and-white image directly
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The main output of `shape` is a signed distance (negative inside, positive outside), and the mask is smoothstepped from it. Doing it in the
reverse order (draw black and white, then blur the edge) looks similar but differs a lot in practice:

    · An SDF can do **strokes** (|d| < w), **dilate/erode** (d − r) and **bevels** directly;
      a black-and-white image can't
    · SDF anti-aliasing is **analytic**: the edge width is a fixed smoothstep sized by the pixel size,
      never blurry or aliased when scaled. Drawing black and white then blurring ties the blur radius to the resolution
    · min of two shapes is the union, max the intersection, −min(−a,−b) the difference, and **the edge
      is still a correct SDF**

This is one of Copernicus's core ideas (its own Shape node also outputs an SDF), worth copying.

The rectangle SDF uses the standard form: `d = |q|−b`, exterior `‖max(d,0)‖`, interior
`min(max(dx,dy),0)`. The exterior term can't be shortened to `max(dx,dy)` -- that underestimates outside the corners
(it gives the Chebyshev distance, not the Euclidean distance), so strokes get narrower at the four corners.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Distances use **normalized coordinates**, but by the short side
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
uv is 0-1; computing distances directly from uv on a non-square image squashes circles into ellipses. Here uv is converted into
**centred coordinates normalized by the short side**: [−0.5, 0.5] along the short side, extending along the long side by the aspect ratio.
So a circle with radius=0.5 is inscribed in the short side at any aspect ratio, and shapes are not distorted.
"""
from __future__ import annotations

import numpy as np

from .core import CopImage, check_res, uv_grid, DEFAULT_LAYER
from . import backend as bk
from .noise import (NOISE_TYPES_COP as _NT, FRACTALS as _FR,
                    METRICS as _MT, fractal_noise as _fnoise)
from . import noisepost as _pp
from . import sdf2d as _s2

SHAPES = ("circle", "box", "rounded_box", "line", "star",
          # pcg100 c4: the SDF Shape Basic / Compound shapes whose definitions can be written down clearly (see sdf2d.py)
          "polygon", "squircle", "trapezoid", "triangle", "diamond",
          "egg", "moon", "vesica", "cross", "arch", "arrow")
# These new shapes are computed in numpy float64 (sdf2d), not through the backend op table
_NEW_SHAPES = SHAPES[5:]
NOISE_TYPES = _NT
FRACTALS = _FR
METRICS = _MT


def constant(xres=512, yres=512, color=(0.0, 0.0, 0.0), alpha=None,
             name=DEFAULT_LAYER, device="numpy"):
    """A constant-colour image. With alpha given it becomes 4 channels."""
    x, y = check_res(xres, yres)
    c = list(np.asarray(color, np.float64).reshape(-1))
    if alpha is not None:
        c = c + [float(alpha)]
    xp = bk.get(device, x * y, 1, len(c))
    a = xp.broadcast_to(xp.reshape(xp.asarray(c), (1, 1, len(c))),
                        (y, x, len(c)))
    return CopImage(x, y, {name: a})


def aspect_coords(xres, yres, xp=None):
    """
    Centred coordinates **normalized by the short side**. Short side [−0.5, 0.5], long side extended by the aspect ratio.

    Computing distances directly from uv squashes circles into ellipses on non-square images. After normalizing by the short side,
    a circle with radius=0.5 is inscribed in the short side at any aspect ratio.
    """
    xp = xp or bk.NUMPY
    uv = uv_grid(xres, yres, xp=xp)
    q = uv - 0.5
    s = min(int(xres), int(yres))
    return xp.stack([q[..., 0] * xres / s, q[..., 1] * yres / s], -1)


def sdf_circle(q, radius, xp=None):
    xp = xp or bk.backend_of(q)
    return xp.norm(q, axis=-1) - float(radius)


def sdf_box(q, half, corner=0.0, xp=None):
    """
    Signed distance of an axis-aligned rectangle (optionally rounded).

    The exterior term is `‖max(d,0)‖` and **cannot** be shortened to `max(dx,dy)`: that gives the Chebyshev
    distance, which is too small outside the four corners, so strokes get narrower at the corners.
    """
    xp = xp or bk.backend_of(q)
    b = np.asarray(half, np.float64).reshape(2) - float(corner)
    d = xp.abs(q) - xp.reshape(xp.asarray(b), (1, 1, 2))
    zero = xp.full(tuple(d.shape), 0.0)
    outside = xp.norm(xp.maximum(d, zero), axis=-1)
    inside = xp.minimum(xp.amax(d, axis=-1),
                        xp.full(tuple(d.shape[:-1]), 0.0))
    return outside + inside - float(corner)


def sdf_line(q, a, b, radius, xp=None):
    """SDF of a line segment (capsule)."""
    xp = xp or bk.backend_of(q)
    a = np.asarray(a, np.float64).reshape(2)
    b = np.asarray(b, np.float64).reshape(2)
    ba = b - a
    denom = float(ba @ ba) or 1.0
    pa = q - xp.reshape(xp.asarray(a), (1, 1, 2))
    h = xp.clip((pa[..., 0] * ba[0] + pa[..., 1] * ba[1]) / denom, 0.0, 1.0)
    dx = pa[..., 0] - h * ba[0]
    dy = pa[..., 1] - h * ba[1]
    return xp.sqrt(dx * dx + dy * dy) - float(radius)


def sdf_star(q, radius, points=5, inner=0.5, xp=None):
    """
    n-pointed star. Not an exact SDF (polar folding gives an approximate distance), but good enough for strokes / masks.

    Stating clearly that "this is not an exact SDF" matters: using it for large-radius dilation shows distortion, and that is not a bug.
    """
    xp = xp or bk.backend_of(q)
    n = max(3, int(points))
    ang = xp.arctan2(q[..., 1], q[..., 0])
    r = xp.norm(q, axis=-1)
    seg = 2.0 * np.pi / n
    a = xp.abs(ang - xp.floor(ang / seg) * seg - seg / 2)
    k = float(radius) * (float(inner) + (1 - float(inner))
                         * xp.cos(a * n / 2.0) ** 2)
    return r - k


def shape(xres=512, yres=512, kind="circle", radius=0.35,
          size=(0.35, 0.25), corner=0.05, center=(0.0, 0.0), angle=0.0,
          points=5, inner=0.5, line_a=(-0.3, 0.0), line_b=(0.3, 0.0),
          softness=1.5, invert=False, sdf_layer="sdf",
          mask_layer="mask", color_layer="", device="numpy",
          arc=1.0, thickness=1.0, round_ends=False,
          separate_corners=False, corners=(0.0, 0.0, 0.0, 0.0),
          separate_thickness=False, line_thickness=(0.1, 0.02),
          squircle_blend=4.0, trap_top=0.15, use_points=False,
          tri_points=("-0.3 -0.25", "0 0.3", "0.3 -0.25"),
          roundness=0.5, moon_inner=0.3, moon_offset=0.15,
          cross_inset=0.15, cross_bevel=0.0, arrow_shaft=0.06,
          arrow_head=0.2, arrow_head_ratio=0.3, shear=0.0,
          uniform_scale=1.0):
    """
    Draws a shape. The main output is an **SDF** (negative inside, positive outside); the mask is smoothstepped from it.

    softness is in **pixels**: edge transition width = softness x the world size of one pixel.
    So the visual softness of the edge is unchanged across resolutions, which is exactly the advantage of SDF anti-aliasing over "draw black and white
    then blur".

    Added in pcg100 c4 (following SideFX SDF Shape; parameters are all appended at the end, defaults = old behaviour):
      · Circle's Arc / Thickness / Round Ends (all equal to 1 / off falls back to the original full circle)
      · Rectangle's Separate Controls: per-corner rounding, 0..1 as a fraction of the short half-side
        (1 with equal sides is a circle, matching the docs); applies to both box and rounded_box
      · Line's Start / End Thickness (full width), a capsule with different thickness at each end
      · New shapes: polygon / squircle / trapezoid / triangle / diamond / egg / moon /
        vesica / cross / arch / arrow (their parameters are in sdf2d.py)
      · Shear / Uniform Scale: in the local coordinates after rotation, first inverse-shear, then divide by the scale,
        and multiply the distance back by the scale -- scaling keeps an exact SDF, shear does not (shear doesn't preserve distance)
    """
    if kind not in SHAPES:
        raise ValueError(f"Shape must be one of {SHAPES}")
    x, y = check_res(xres, yres)
    xp = bk.get(device, x * y, 2, 1)
    q = aspect_coords(x, y, xp)
    ctr = np.asarray(center, np.float64).reshape(2)
    q = q - xp.reshape(xp.asarray(ctr), (1, 1, 2))
    th = np.radians(float(angle))
    if th:
        c, sn = float(np.cos(-th)), float(np.sin(-th))
        q = xp.stack([q[..., 0] * c - q[..., 1] * sn,
                      q[..., 0] * sn + q[..., 1] * c], -1)

    sh = float(shear)
    sc = float(uniform_scale)
    if sh:
        # The forward map is x' = x + Shear·y (horizontal shear in local coordinates); the inverse is applied to pixels
        q = xp.stack([q[..., 0] - sh * q[..., 1], q[..., 1]], -1)
    if sc != 1.0:
        if sc == 0.0:
            raise ValueError("Uniform Scale cannot be 0")
        q = q / sc

    circle_cut = kind == "circle" and (float(arc) < 1.0
                                       or float(thickness) < 1.0)
    box4 = kind in ("box", "rounded_box") and bool(separate_corners)
    line2 = kind == "line" and bool(separate_thickness)
    if kind in _NEW_SHAPES or circle_cut or box4 or line2:
        d = xp.asarray(_shape_np(
            np.asarray(xp.to_numpy(q), np.float64), kind, radius, size,
            points, line_a, line_b, arc, thickness, round_ends, corners,
            line_thickness, squircle_blend, trap_top, use_points,
            tri_points, roundness, moon_inner, moon_offset, cross_inset,
            cross_bevel, arrow_shaft, arrow_head, arrow_head_ratio))
    elif kind == "circle":
        d = sdf_circle(q, radius, xp)
    elif kind == "box":
        d = sdf_box(q, size, 0.0, xp)
    elif kind == "rounded_box":
        d = sdf_box(q, size, corner, xp)
    elif kind == "line":
        d = sdf_line(q, line_a, line_b, radius, xp)
    else:
        d = sdf_star(q, radius, points, inner, xp)
    if sc != 1.0:
        d = d * abs(sc)
    if invert:
        d = -d

    out = CopImage(x, y)
    # How big one pixel is in this coordinate system -- edge width is based on it, so visual softness is unchanged across resolutions
    px = 1.0 / min(x, y)
    if str(sdf_layer).strip():
        out.set(str(sdf_layer).strip(), d)
    if str(mask_layer).strip():
        w = max(float(softness), 0.0) * px
        if w <= 0:
            one = xp.full(tuple(d.shape), 1.0)
            m = xp.where(d <= 0, one, xp.full(tuple(d.shape), 0.0))
        else:
            t = xp.clip(0.5 - d / (2 * w), 0.0, 1.0)
            m = t * t * (3 - 2 * t)
        out.set(str(mask_layer).strip(), m)
        if str(color_layer).strip():
            out.set(str(color_layer).strip(),
                    xp.repeat_last(xp.reshape(m, tuple(m.shape) + (1,)), 3))
    return out


def _vec2(v):
    """"x y" / "x,y" / sequence -> two floats."""
    if isinstance(v, str):
        a = [float(t) for t in v.replace(",", " ").split()]
    else:
        a = [float(t) for t in np.asarray(v, np.float64).reshape(-1)]
    if len(a) != 2:
        raise ValueError(f"Expected two numbers (x y), got {v!r}")
    return a


def _shape_np(q, kind, radius, size, points, line_a, line_b, arc,
              thickness, round_ends, corners, line_thickness, squircle_blend,
              trap_top, use_points, tri_points, roundness, moon_inner,
              moon_offset, cross_inset, cross_bevel, arrow_shaft, arrow_head,
              arrow_head_ratio):
    """Shapes / options added in pcg100 c4: computed in numpy float64 (sdf2d)."""
    sx, sy = (float(v) for v in np.asarray(size, np.float64).reshape(2))
    if kind == "circle":
        return _s2.ring_sector(q, radius, arc, thickness, round_ends)
    if kind in ("box", "rounded_box"):
        # 0..1 roundness is converted by the short half-side; clamped so that 1 is exactly a half-round corner
        m = min(abs(sx), abs(sy))
        tl, tr, bl, br = (float(np.clip(c, 0.0, 1.0)) * m for c in corners)
        return _s2.rounded_box4(q, (sx, sy), (tr, br, tl, bl))
    if kind == "line":
        ta, tb = (max(float(t), 0.0) * 0.5 for t in line_thickness)
        return _s2.uneven_capsule(q, line_a, line_b, ta, tb)
    if kind == "polygon":
        return _s2.regular_polygon(q, radius, points)
    if kind == "squircle":
        return _s2.squircle(q, radius, squircle_blend)
    if kind == "trapezoid":
        return _s2.trapezoid(q, sx, float(trap_top), sy)
    if kind == "triangle":
        if use_points:
            p0, p1, p2 = (_vec2(p) for p in tri_points)
        else:
            p0, p1, p2 = (-sx, -sy), (0.0, sy), (sx, -sy)
        return _s2.triangle(q, p0, p1, p2)
    if kind == "diamond":
        return _s2.diamond(q, sx, sy)
    if kind == "egg":
        return _s2.egg(q, radius, roundness)
    if kind == "moon":
        return _s2.moon(q, radius, moon_inner, moon_offset)
    if kind == "vesica":
        return _s2.vesica(q, radius, roundness)
    if kind == "cross":
        return _s2.cross(q, radius, cross_inset, cross_bevel)
    if kind == "arch":
        return _s2.arch(q, 2.0 * sx, 2.0 * sy)
    return _s2.arrow(q, line_a, line_b, arrow_shaft, arrow_head,
                     arrow_head_ratio)


NOISE_CHUNK = 1 << 18


def noise(xres=512, yres=512, noise_type="simplex", fractal="standard",
          frequency=4.0, octaves=3, lacunarity=2.0, roughness=0.5,
          rand_seed=0, offset=(0.0, 0.0, 0.0), amplitude=1.0, bias=0.0,
          channels=1, tile=False, name=DEFAULT_LAYER, device="numpy",
          time=0.0, time_scale=0.0, loop_frames=0, metric="euclidean",
          jitter=1.0, tile_v=False, post=None):
    """
    Noise. **Uses the same `attribnoise.fractal_noise` as the geometry side** -- for the same world coordinate
    both sides sample bit-identical values.

    Coordinates are uv×frequency on the plane z=offset.z (plus offset.xy). So
    "adding noise to geometry in UV space" and "generating a noise image and sampling it by uv" agree.

    With tile=True the plane coordinates are replaced by **a loop on a 4D torus** (packing the coordinates of two orthogonal circles
    into 3D is impossible, so as a compromise: x uses a circle with period frequency, and y
    uses height directly) -- seamless only in u. True seamlessness in both directions needs 4D noise, which isn't attempted here.

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    Time axis: straight, or **around a circle**
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    With loop_frames=0, `w = time × time_scale`, moving straight along the fourth dimension -- infinitely long, never
    repeating, suited to one-off shots.

    With loop_frames=N, time is mapped onto **a circle in the (z,w) plane**:

        z = offset.z + r·cos(2πt/N)
        w =            r·sin(2πt/N)      r = N·time_scale / 2π

    So frame 0 and frame N have **exactly the same** 4D coordinates and the output is bit-identical -- this is a true
    seamless loop, not "cross-fade the join". The radius N·time_scale/2π makes the arc length travelled per frame
    still time_scale, so the "flow speed" of the image is the same with or without looping.

    Looping uses up both the z and w axes, so **looping can't be enabled with tile=True** -- then x/y are already
    u's circle and z is v, and another circle would need a fifth dimension. This case raises an error rather than silently turning looping
    off: if it were silently turned off, someone exporting 60 frames and finding the ends don't match would never think to look here.
    """
    if noise_type not in NOISE_TYPES:
        raise ValueError(f"Noise Type must be one of {NOISE_TYPES}")
    if fractal not in FRACTALS:
        raise ValueError(f"Fractal must be one of {FRACTALS}")
    if metric not in METRICS:
        raise ValueError(f"Metric must be one of {METRICS}")
    # Torus (pcg100): Houdini says it is "4D simplex on a flat torus, periodic by nature". A flat torus
    # embedded in 4D is (cos 2πu, sin 2πu, cos 2πv, sin 2πv)·r -- exactly the path below where both the u and v
    # directions are rolled into circles, so torus = simplex + tiling in both directions, with no separate basis function
    if noise_type == "torus":
        noise_type, tile, tile_v = "simplex", True, True
    x, y = check_res(xres, yres)
    nc = max(1, int(channels))
    xp = bk.get(device, x * y, 1, nc)
    uv = uv_grid(x, y, xp=xp)
    # **Must be converted to a Python float**: a numpy float64 scalar silently promotes the whole float32 chain
    # to float64 (under NEP 50 numpy scalars are "strong" types), while torch doesn't --
    # so the two backends differed by 1.9e-3. Python scalars are weak types on both sides and don't promote
    off = [float(v) for v in np.asarray(offset, np.float64).reshape(3)]
    f = float(frequency)
    nloop = max(0, int(loop_frames))
    ts = float(time_scale)
    # **time_scale is the switch, not time.** Using "time != 0" as the switch, time=0
    # would take 3D and time=0.001 4D, and only value noise has a 4D w=0 slice equal to 3D --
    # other types would make **the whole image jump** between frame 0 and frame 1, visible only in animation.
    # ts=0 always takes 3D, so existing workflows are bit-identical; ts>0 always takes 4D, including time=0
    if nloop > 0 and ts <= 0:
        raise ValueError("loop_frames > 0 requires time_scale > 0, "
                         "otherwise the circle radius is 0 and every frame is the same.")
    if nloop > 0 and (tile or tile_v):
        raise ValueError(
            "tile=True and loop_frames>0 can't both be on: tiling already rolls x/y into u's circle, "
            "with z as v; looping needs two more axes, five dimensions in total. Pick one.")
    if tile and tile_v and ts > 0:
        raise ValueError(
            "Tiling in both u and v (or Torus) already uses four axes; adding time needs five dimensions -- "
            "time_scale must be 0.")

    px, py, pz, pw = tile_coords(xp, uv, f, off, tile, tile_v)
    if ts > 0 and nloop > 0:
        r = nloop * ts / (2.0 * np.pi)
        # **Take the phase modulo first, then apply trig functions.** Computing 2π·24/24 directly, cos gives 1.0 and
        # sin gives −2.45e-16 -- not 0. And the first step of noise is floor;
        # floor(−2.45e-16) = −1, so the integer lattice coordinate is off by one cell, all hashes change, and frame N
        # doesn't match frame 0 at all. After the modulo, t=24 lands exactly back on a=0
        a = 2.0 * np.pi * (float(time) % nloop) / nloop
        pz = xp.full(tuple(uv.shape[:2]), off[2] + r * float(np.cos(a)))
        pw = xp.full(tuple(uv.shape[:2]), r * float(np.sin(a)))
    elif ts > 0:
        pw = xp.full(tuple(uv.shape[:2]), float(time) * ts)

    # **Chunked by rows**, only on the CPU (both numpy and torch-cpu). Purely a cache issue: 2048² has 4.2 million pixels,
    # and computing it in one go means every octave walks a 100 MB array several times, cache
    # misses the whole way -- after cutting it into chunks of a few hundred thousand pixels (fits in L2/L3), 2048²/4 octaves in numpy went from
    # 17.9 s to 8.0 s and torch-cpu from 16.0 s to 5.6 s. The GPU is the opposite:
    # larger chunks keep the SMs fed better, and chunking only adds kernel launch overhead, so on cuda the whole image is computed
    # in one go. Chunking only changes evaluation order; results on the same backend are **bit-for-bit** identical
    on_gpu = bool(getattr(xp, "is_torch", False)
                  and getattr(xp.device, "type", "cpu") == "cuda")
    rows = y if on_gpu else max(1, int(NOISE_CHUNK // max(x, 1)))
    sd = int(rand_seed) & 0xFFFFFFFF
    cols = []
    for k in range(nc):
        seed_k = (sd + k * 7919) & 0xFFFFFFFF
        if rows >= y:
            cols.append(_fnoise(xp, px, py, pz, noise_type, fractal,
                                int(octaves), float(lacunarity),
                                float(roughness), seed_k, w=pw,
                                metric=metric, jitter=float(jitter)))
            continue
        parts = [_fnoise(xp, px[i:i + rows], py[i:i + rows],
                         pz[i:i + rows], noise_type, fractal, int(octaves),
                         float(lacunarity), float(roughness), seed_k,
                         w=None if pw is None else pw[i:i + rows],
                         metric=metric, jitter=float(jitter))
                 for i in range(0, y, rows)]
        cols.append(xp.concat(parts, 0))
    a = xp.stack(cols, -1) * float(amplitude) + float(bias)
    # The Post Processing section comes after Amplitude / Center (the order in the Houdini docs);
    # with everything at defaults run is returned as-is, bit-for-bit unchanged
    a = _pp.run(xp, a, post or {})
    return CopImage(x, y, {name: a})


def tile_coords(xp, uv, f, off, tile_u=False, tile_v=False):
    """
    uv -> noise-space coordinates (px, py, pz, pw). pw is not None only when tiling in both directions.

    · no tiling: plane (u·F, v·F, offset.z)
    · tile u only: u rolled into a circle of circumference F in the (x,y) plane, z = v·F (the original path, not a character changed)
    · tile v only (pcg100): v rolled into a circle in the (y,z) plane, x = u·F
    · both (pcg100): the u circle in (x,y), the v circle in (z,w) -- this is the flat torus (Clifford
      torus). Both circles have radius F/2π, so the arc length travelled along u and along v is the same as without tiling;
      element size is unchanged and isotropic

    The circle's circumference is F; multiplying by Lacunarity per octave only scales the circle proportionally, which stays closed -- so unlike
    Houdini, tiling here **does not require** rounding Lacunarity to an integer.
    """
    r = f / (2.0 * np.pi) if f else 1.0
    pw = None
    if tile_u and tile_v:
        a = uv[..., 0] * (2.0 * np.pi)
        b = uv[..., 1] * (2.0 * np.pi)
        px = r * xp.cos(a) + off[0]
        py = r * xp.sin(a) + off[1]
        pz = r * xp.cos(b) + off[2]
        pw = r * xp.sin(b)
    elif tile_u:
        # u is rolled into a circle: u=0 and u=1 map to the same point, so horizontal tiling is seamless
        a = uv[..., 0] * (2.0 * np.pi)
        px = r * xp.cos(a) + off[0]
        py = r * xp.sin(a) + off[1]
        pz = uv[..., 1] * f + off[2]
    elif tile_v:
        b = uv[..., 1] * (2.0 * np.pi)
        px = uv[..., 0] * f + off[0]
        py = r * xp.cos(b) + off[1]
        pz = r * xp.sin(b) + off[2]
    else:
        px = uv[..., 0] * f + off[0]
        py = uv[..., 1] * f + off[1]
        pz = xp.full(tuple(uv.shape[:2]), off[2])
    return px, py, pz, pw


def gradient(xres=512, yres=512, direction="v", ramp="0:0  1:1",
             ramp_mode="linear", angle=0.0, center=(0.0, 0.0),
             name=DEFAULT_LAYER, device="numpy"):
    """
    Gradient. direction: u / v / diagonal / radial / angular.

    Colour lookup reuses the geometry-side `ramp` module, so Attribute Fade's ramp syntax
    ("0:0 0.5:1 1:0", multi-component allowed) works here as-is.

    The component count is **counted** from spec: `ramp.parse` needs ncomp given in advance, while the caller
    here only writes a string. Counting the commas of the first entry is enough -- a mixed spec like `0:0 1:1,0.5,0`
    gets parse's own "component count mismatch" error.
    """
    from ..ramp import parse as _parse, apply as _apply
    x, y = check_res(xres, yres)
    # A gradient is "one 1D table lookup per pixel"; the lookup runs in numpy (the table has at most a few dozen points,
    # not worth moving to the GPU), and the result is then put on the target backend by device
    uv = uv_grid(x, y).astype(np.float64)
    if direction == "u":
        t = uv[..., 0]
    elif direction == "v":
        t = uv[..., 1]
    elif direction == "diagonal":
        th = np.radians(float(angle))
        d = np.array([np.cos(th), np.sin(th)])
        p = (uv - 0.5) @ d
        t = p - p.min()
        t = t / (t.max() or 1.0)
    elif direction in ("radial", "angular"):
        q = np.asarray(aspect_coords(x, y), np.float64) \
            - np.asarray(center, np.float64).reshape(2)
        if direction == "radial":
            t = np.clip(np.linalg.norm(q, axis=-1) / 0.5, 0.0, 1.0)
        else:
            t = (np.arctan2(q[..., 1], q[..., 0]) / (2 * np.pi)) % 1.0
    else:
        raise ValueError("Direction must be one of u / v / diagonal / radial / "
                         "angular")
    first = next((tok for tok in str(ramp).split() if ":" in tok), "0:0")
    nc = max(1, len([x for x in first.split(":", 1)[1].split(",") if x != ""]))
    pos, val = _parse(str(ramp), nc)
    v = _apply(np.clip(t, 0.0, 1.0).reshape(-1), pos, val, ramp_mode)
    xp = bk.get(device, x * y, 1, nc)
    return CopImage(x, y, {name: xp.asarray(
        np.asarray(v, np.float64).reshape(y, x, -1))})
