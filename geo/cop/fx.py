"""
The filters / effects / distortion batch: depth of field, directional blur, Kuwahara, convolution, TV denoise, glow, drop shadow,
feather, pixelate, chromatic aberration, heat distortion, swirl, lens distortion, derivatives, corners, fill holes, flood fill, contour lines,
dither, mirror, four-corner perspective, lattice deform, planar inflate, copy-transform.

All numpy. Convolution kernels larger than 7 go through FFT (numpy.fft, no scipy dependency -- ComfyUI's
portable build doesn't necessarily have scipy installed).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Borders
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Same three as COP Blur: clamp (edge pixels extend outward) / wrap (tiling) / black (zero padding).
FFT convolution is inherently wrap, so a border half a kernel wide is padded by the border mode first, then FFT, then
cropped back -- without padding, in clamp mode bright pixels on the right would bleed in from the left (circular convolution).
"""
from __future__ import annotations

import math

import numpy as np

from .core import CopImage, DEFAULT_LAYER
from .pixel import getn, put, names_of, _vec
from .filters import BORDERS
from . import accel as AC

BLUR_SHAPES = ("disc", "hexagon", "square")
CONV_BORDERS = BORDERS + ("mirror",)


# ═══════════════════════════════════════════════════════════ Basics
def pad(a, r, border):
    """Pad (H,W,C) by r rings according to the border mode."""
    if r <= 0:
        return a
    # mirror (pcg100, Convolve Filter's Border): reflect at the edge, with the edge pixel repeated once
    mode = {"clamp": "edge", "wrap": "wrap", "black": "constant",
            "mirror": "symmetric"}[border]
    return np.pad(a, ((r, r), (r, r), (0, 0)), mode=mode)


def convolve(a, k, border="clamp"):
    """
    2D convolution (correlation: kernel not flipped, irrelevant for symmetric kernels). a (H,W,C), k (kh,kw), kh/kw odd.
    Small kernels by direct shift-and-add (bitwise predictable), large kernels by FFT.
    """
    if border not in CONV_BORDERS:
        raise ValueError(f"Border must be one of {CONV_BORDERS}")
    k = np.asarray(k, np.float64)
    kh, kw = k.shape
    if kh % 2 == 0 or kw % 2 == 0:
        raise ValueError("Convolution kernel side lengths must be odd")
    ry, rx = kh // 2, kw // 2
    H, W, C = a.shape
    r = max(ry, rx)
    p = pad(a, r, border)
    if kh * kw <= 49:
        out = np.zeros_like(a)
        for i in range(kh):
            for j in range(kw):
                if k[i, j] != 0:
                    out += k[i, j] * p[r - ry + i:r - ry + i + H,
                                       r - rx + j:r - rx + j + W]
        return out
    Hp, Wp = p.shape[:2]
    kk = np.zeros((Hp, Wp))
    kk[:kh, :kw] = k
    kk = np.roll(np.roll(kk, -ry, 0), -rx, 1)
    Fk = np.conj(np.fft.rfft2(kk))
    out = np.empty((Hp, Wp, C))
    for c in range(C):
        out[..., c] = np.fft.irfft2(np.fft.rfft2(p[..., c]) * Fk, s=(Hp, Wp))
    return out[r:r + H, r:r + W]


def kernel_shape(radius, shape="disc", blades=6, rotation=0.0):
    """Normalized shape kernel (for depth of field / bokeh). radius in pixels; < 0.5 gives a unit impulse."""
    R = float(radius)
    if R < 0.5:
        return np.ones((1, 1))
    n = int(math.ceil(R))
    y, x = np.mgrid[-n:n + 1, -n:n + 1].astype(np.float64)
    # 4x4 supersampled coverage, so edges are soft (a hard-edged disk flickers at small radii)
    ss = (np.arange(4) + 0.5) / 4 - 0.5
    cov = np.zeros_like(x)
    for sy in ss:
        for sx in ss:
            px, py = x + sx, y + sy
            if shape == "disc":
                inside = px * px + py * py <= R * R
            elif shape == "square":
                inside = (np.abs(px) <= R) & (np.abs(py) <= R)
            else:
                m = max(3, int(blades))
                th = np.arctan2(py, px) - math.radians(rotation)
                seg = 2 * math.pi / m
                t = (th % seg) - seg / 2
                apothem = R * math.cos(math.pi / m)
                inside = np.hypot(px, py) * np.cos(t) <= apothem
            cov += inside
    cov /= 16.0
    return cov / cov.sum()


def box_sum(a, r):
    """(2r+1)² box sum of (H,W,C), clamp border. Integral image, O(1) per pixel."""
    p = pad(a, r + 1, "clamp")
    s = p.cumsum(0).cumsum(1)
    H, W = a.shape[:2]
    k = 2 * r + 1
    o = r + 1
    return (s[o + r:o + r + H, o + r:o + r + W]
            - s[o - r - 1:o - r - 1 + H, o + r:o + r + W]
            - s[o + r:o + r + H, o - r - 1:o - r - 1 + W]
            + s[o - r - 1:o - r - 1 + H, o - r - 1:o - r - 1 + W]) \
        if k else a


def warp(img, gx, gy, layers="", border="clamp", keep=True):
    """Resample the given layers by a field of **input pixel coordinates** (gx, gy) (other layers unchanged)."""
    from .transform import resample
    xp = img.backend
    names = names_of(img, layers)
    got = resample(img, xp.asarray(gx), xp.asarray(gy), border, "bilinear",
                   names)
    out = img.copy() if keep else CopImage(img.xres, img.yres)
    for n, v in got.items():
        out.set(n, v)
    return out


def _grid(W, H):
    J, I = np.meshgrid(np.arange(W, dtype=np.float64),
                       np.arange(H, dtype=np.float64))
    return J, I


# ═══════════════════════════════════════════════════════════ Depth of field / bokeh
def defocus(img, layers="", radius=6.0, shape="disc", blades=6,
            rotation=0.0, depth_layer="", focus=0.5, focus_range=0.1,
            falloff=0.2, levels=8, highlight_threshold=1.0,
            highlight_gain=0.0, border="clamp"):
    """
    Depth of field / bokeh (Defocus / Bokeh). Convolution with a shape kernel (disk / polygonal aperture / square).

    If depth_layer is given, layers by **circle of confusion** (CoC): |depth - Focus| <= Focus Range
    is sharp; beyond that it grows linearly to Radius over the Falloff distance, quantized into Levels bins, each bin convolved once, and per pixel interpolated between the two
    adjacent bins. If not given, the whole image uses one radius.

    Highlight Gain: the part brighter than the threshold is amplified before blurring and compressed back afterwards -- so bokeh highlights
    come out as distinct aperture shapes rather than being averaged into a gray smear.
    """
    if img is None:
        return CopImage()
    if shape not in BLUR_SHAPES:
        raise ValueError(f"Shape must be one of {BLUR_SHAPES}")
    out = img.copy()
    R = float(radius)
    dl = str(depth_layer).strip()
    coc = None
    if dl:
        d = getn(img, dl)[..., 0]
        coc = np.clip((np.abs(d - float(focus)) - float(focus_range))
                      / max(1e-9, float(falloff)), 0.0, 1.0) * R
    for n in names_of(img, layers):
        if n == dl:
            continue
        a = getn(img, n)
        k = min(a.shape[2], 3)
        g = float(highlight_gain)
        src = a.copy()
        if g > 0:
            lum = src[..., :k].max(-1, keepdims=True)
            boost = 1.0 + g * np.clip(lum - float(highlight_threshold), 0,
                                      None)
            src[..., :k] = src[..., :k] * boost
        if coc is None:
            res = convolve(src, kernel_shape(R, shape, blades, rotation),
                           border)
        else:
            L = max(2, int(levels))
            radii = np.linspace(0.0, R, L)
            stack = [convolve(src, kernel_shape(rr, shape, blades, rotation),
                              border) for rr in radii]
            t = coc / (R if R > 0 else 1.0) * (L - 1)
            i0 = np.clip(np.floor(t).astype(int), 0, L - 2)
            f = (t - i0)[..., None]
            S = np.stack(stack, 0)
            Hh, Ww = a.shape[:2]
            yy, xx = np.mgrid[0:Hh, 0:Ww]
            res = S[i0, yy, xx] * (1 - f) + S[i0 + 1, yy, xx] * f
        if g > 0:
            # the gain map Y = L·(1 + g·max(L - thr, 0)) is monotonic and continuous; solve its inverse:
            # for Y <= thr, L = Y, otherwise take the positive root of gL² + (1 - g·thr)L - Y = 0. Flat
            # bright areas thus return to their original values pixel by pixel; the energy of spread-out bokeh highlights remains, so apertures are
            # brighter than with a plain blur -- exactly the effect Highlight Gain is for.
            thr = float(highlight_threshold)
            Y = res[..., :k].max(-1, keepdims=True)
            b = 1.0 - g * thr
            L = np.where(Y > thr, (-b + np.sqrt(np.maximum(b * b + 4 * g * Y,
                                                           0))) / (2 * g), Y)
            res[..., :k] = res[..., :k] * np.where(np.abs(Y) > 1e-12,
                                                   L / np.where(np.abs(Y) > 1e-12, Y, 1), 1.0)
        put(out, n, res, img)
    return out


def directional_blur(img, layers="", length=20.0, angle=0.0, mode="centered",
                     samples=0, border="clamp", compute="auto"):
    """
    Directional / streak blur (Streak Blur). Averages samples bilinear samples along angle (degrees, 0 = +u, 90 = +v).
    centered = half on each side (motion blur); streak = drag to one side only
    (light streaks, speed lines). samples left at 0 = one sample per pixel.
    Sampling goes through accel's compute engine (with compute = auto, CUDA on large images, float64).
    """
    if img is None:
        return CopImage()
    if mode not in ("centered", "streak"):
        raise ValueError("Mode must be one of centered / streak")
    Lh = float(length)
    n = int(samples) or max(2, int(math.ceil(abs(Lh))) + 1)
    dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    ts = np.linspace(-0.5, 0.5, n) if mode == "centered" \
        else np.linspace(0.0, 1.0, n)
    W, H = img.xres, img.yres
    out = img.copy()
    from .filters import sample
    # VRAM estimate uses the real channel count: two coordinate grids + about 10 temporary images per channel (accumulator, sample coordinates,
    # the four bilinear corners...). It used to hard-code 4 channels, so single-channel 2048² was estimated at 1.6 GB and auto
    # silently fell back to CPU -- found by measurement on real hardware
    ch = max([int(getn(img, n).shape[2]) for n in names_of(img, layers)] or [1])
    X, _ = AC.pick(img, compute, W * H, 2 + 10 * ch)
    J, I = _grid(W, H)
    J, I = X.arr(J), X.arr(I)
    for nm in names_of(img, layers):
        a = X.arr(getn(img, nm))
        acc = X.zeros_like(a)
        for t in ts:
            gx, gy = J - dx * Lh * t, I - dy * Lh * t
            acc = acc + sample(a, (gx + 0.5) / W, (gy + 0.5) / H, border,
                               X.ops)
        put(out, nm, X.np(acc / n), img)
    return out


def kuwahara(img, layers="", radius=4):
    """
    Kuwahara: computes mean and variance of each of four (r+1)² quadrants and takes the mean of the quadrant with the smallest variance --
    edge-preserving smoothing with a "painterly" look. Variance is compared on luminance (mean over channels). Integral-image implementation.
    """
    if img is None:
        return CopImage()
    r = int(radius)
    if r < 1:
        raise ValueError("Radius must be at least 1")
    out = img.copy()
    for n in names_of(img, layers):
        a = getn(img, n)
        H, W, C = a.shape
        lum = a[..., :min(C, 3)].mean(-1, keepdims=True)
        stackA = np.concatenate([a, lum, lum * lum], -1)
        p = pad(stackA, r, "clamp")
        s = np.zeros((p.shape[0] + 1, p.shape[1] + 1, p.shape[2]))
        s[1:, 1:] = p.cumsum(0).cumsum(1)
        best = None
        best_var = None
        k = (r + 1) ** 2
        for oy, ox in ((0, 0), (0, r), (r, 0), (r, r)):
            y0 = np.arange(H) + oy
            x0 = np.arange(W) + ox
            Y0, X0 = np.meshgrid(y0, x0, indexing="ij")
            tot = (s[Y0 + r + 1, X0 + r + 1] - s[Y0, X0 + r + 1]
                   - s[Y0 + r + 1, X0] + s[Y0, X0])
            mean = tot / k
            var = mean[..., C + 1] - mean[..., C] ** 2
            if best is None:
                best, best_var = mean[..., :C], var
            else:
                m = var < best_var
                best = np.where(m[..., None], mean[..., :C], best)
                best_var = np.where(m, var, best_var)
        put(out, n, best, img)
    return out


CONV_PRESETS = {
    "custom": None,
    "box3": [1, 1, 1, 1, 1, 1, 1, 1, 1],
    "gaussian3": [1, 2, 1, 2, 4, 2, 1, 2, 1],
    "sharpen": [0, -1, 0, -1, 5, -1, 0, -1, 0],
    "edge": [-1, -1, -1, -1, 8, -1, -1, -1, -1],
    "emboss": [-2, -1, 0, -1, 1, 1, 0, 1, 2],
    "sobel_x": [-1, 0, 1, -2, 0, 2, -1, 0, 1],
    "sobel_y": [-1, -2, -1, 0, 0, 0, 1, 2, 1],
}


def kernel_from_image(k, centered=True):
    """
    Kernel **image** (one channel, row 0 at the bottom) -> odd-sided correlation kernel for `convolve`.

    Houdini's Convolve Filter takes its second image input as the kernel. Here it's interpreted as a **true convolution**:
    out[p] = Σ_q in[p - (q - o)] · k[q], o being the kernel origin. The criterion is "convolving a single-pixel
    impulse yields the kernel image itself" (origin on the impulse) -- the docs don't say whether it's flipped;
    this is what the word convolution actually means, and also what frequency-domain multiplication gives.

    centered: origin = the kernel image's center pixel (h//2, w//2), the result isn't shifted; when off, origin =
    the bottom-left pixel (0, 0), so the result shifts up-right by half a kernel (docs: when off the origin is the kernel image's
    "corner" and the output shifts by half a kernel; which corner isn't said, so FFT's natural origin = bottom-left is used here).

    `convolve` is a correlation (kernel not flipped), needs odd side lengths and the origin at the center, so here the kernel
    is flipped and embedded in an odd square centered on the origin.
    """
    k = np.asarray(k, np.float64)
    h, w = k.shape
    oy, ox = (h // 2, w // 2) if centered else (0, 0)
    ry, rx = max(oy, h - 1 - oy), max(ox, w - 1 - ox)
    kc = np.zeros((2 * ry + 1, 2 * rx + 1))
    # correlation kernel offset e = -(q - o): kc[r + e] = k[o - e]
    kc[ry + oy - np.arange(h)[:, None], rx + ox - np.arange(w)[None, :]] = k
    return kc


def convolve_layer(img, layers="", preset="custom", kernel="0 0 0 0 1 0 0 0 0",
                   normalize=False, border="clamp", kernel_img=None,
                   kernel_layer=DEFAULT_LAYER, centered=True):
    """
    Convolve 3x3 / Convolve Filter. kernel takes n² numbers (n odd, row-major, **the first row
    is the row with the largest v** -- i.e. it looks on the image the way it's written, top is up).
    normalize scales the kernel to sum to 1 (kernels summing to 0 aren't scaled).

    If kernel_img (pcg100, Houdini Convolve Filter's second input) is connected it **overrides**
    the preset / kernel string: the kernel is taken from its kernel_layer layer. A 1-channel kernel is applied
    to every channel; with the same channel count as the layer being convolved, each channel uses its own; any other combination raises an error.
    normalize divides the kernel image by its own sum per channel.
    """
    if img is None:
        return CopImage()
    if preset not in CONV_PRESETS:
        raise ValueError(f"Preset must be one of {tuple(CONV_PRESETS)}")
    out = img.copy()
    if kernel_img is not None:
        ki = getn(kernel_img, kernel_layer)
        ks = []
        for c in range(ki.shape[2]):
            kc = ki[..., c]
            if normalize and abs(kc.sum()) > 1e-12:
                kc = kc / kc.sum()
            ks.append(kernel_from_image(kc, centered))
        for nm in names_of(img, layers):
            a = getn(img, nm)
            if len(ks) == 1:
                r = convolve(a, ks[0], border)
            elif len(ks) == a.shape[2]:
                r = np.concatenate([convolve(a[..., c:c + 1], ks[c], border)
                                    for c in range(a.shape[2])], -1)
            else:
                raise ValueError(
                    f"The kernel image has {len(ks)} channels, layer '{nm}' has {a.shape[2]} -- "
                    f"the kernel must have either 1 channel or the same channel count as the layer being convolved")
            put(out, nm, r, img)
        return out
    vals = CONV_PRESETS[preset] or [float(x) for x in
                                    str(kernel).replace(",", " ").split()]
    n = int(round(math.sqrt(len(vals))))
    if n * n != len(vals) or n % 2 == 0:
        raise ValueError(f"Kernel needs n² numbers with n odd, got {len(vals)}")
    k = np.asarray(vals, np.float64).reshape(n, n)[::-1]   # the first written row = top
    if normalize and abs(k.sum()) > 1e-12:
        k = k / k.sum()
    for nm in names_of(img, layers):
        put(out, nm, convolve(getn(img, nm), k, border), img)
    return out


def _grad(u, X=None):
    """Forward difference, last column / last row is 0 (Neumann boundary). u is (H,W) or (H,W,C)."""
    X = X or AC.NUMPY
    gx = X.zeros_like(u)
    gy = X.zeros_like(u)
    gx[:, :-1] = u[:, 1:] - u[:, :-1]
    gy[:-1, :] = u[1:, :] - u[:-1, :]
    return gx, gy


def _div(px, py, X=None):
    """
    Divergence -- strictly the adjoint of -_grad (⟨∇u, p⟩ = -⟨u, div p⟩), which Chambolle's convergence
    proof relies on. Boundaries per the paper: the first cell takes p, the last cell takes -p[previous cell].
    """
    X = X or AC.NUMPY
    d = X.zeros_like(px)
    if px.shape[1] > 1:
        d[:, 0] += px[:, 0]
        d[:, 1:-1] += px[:, 1:-1] - px[:, :-2]
        d[:, -1] += -px[:, -2]
    if py.shape[0] > 1:
        d[0, :] += py[0, :]
        d[1:-1, :] += py[1:-1, :] - py[:-2, :]
        d[-1, :] += -py[-2, :]
    return d


def denoise_tv(img, layers="", weight=0.1, iterations=50, compute="auto"):
    """
    Total variation denoising (ROF model: min_u ½||u - f||² + λ·TV(u)), Chambolle 2004's dual
    projection method. Removes noise, keeps edges; larger weight (λ) is flatter. Each channel independent.

        p ← (p + τ∇(div p − f/λ)) / (1 + τ|∇(div p − f/λ)|),  u = f − λ·div p

    τ = 1/8 is the convergence bound given in the paper (squared norm of ∇ <= 8).
    Two properties are used as invariants in the tests: mean is conserved (the sum of div is always 0), and a constant image is returned unchanged.

    pcg65: all channels are computed together (differences on the whole (H,W,C) block; each channel's expressions are independent elementwise, so the result
    is bit-identical to computing channel by channel), and iteration goes through accel's compute engine -- with compute = auto,
    CUDA on large images (float64, matching numpy to 1e-12).
    """
    if img is None:
        return CopImage()
    lam = float(weight)
    if lam < 0:
        raise ValueError("Weight can't be negative")
    out = img.copy()
    if lam == 0:
        return out
    tau = 0.125
    names = names_of(img, layers)
    # VRAM estimate uses the real channel count (about 10 images per channel: f, the two components of p, divergence, gradient temporaries)
    ch = max([int(getn(img, n).shape[2]) for n in names] or [1])
    X, _ = AC.pick(img, compute, img.xres * img.yres, 10 * ch)
    for n in names:
        f = X.arr(getn(img, n))
        px = X.zeros_like(f)
        py = X.zeros_like(f)
        fl = f / lam
        for _ in range(int(iterations)):
            gx, gy = _grad(_div(px, py, X) - fl, X)
            nrm = 1.0 + tau * X.hypot(gx, gy)
            px = (px + tau * gx) / nrm
            py = (py + tau * gy) / nrm
        put(out, n, X.np(f - lam * _div(px, py, X)), img)
    return out


def glow(img, layers="", mode="glow", threshold=0.8, intensity=1.0,
         radius=12.0, rays=4, ray_length=40.0, angle=45.0, border="clamp"):
    """
    Glow (Glow / Star Glow). First takes the part brighter than threshold (soft knee); glow = multi-scale
    Gaussian sum (r, r/2, r/4), star = sum of streak blurs along rays directions; then adds back to the original.
    alpha is unchanged.
    """
    if img is None:
        return CopImage()
    if mode not in ("glow", "star"):
        raise ValueError("Mode must be one of glow / star")
    from .filters import gaussian_kernel
    out = img.copy()
    for n in names_of(img, layers):
        a = getn(img, n)
        k = min(a.shape[2], 3)
        lum = a[..., :k].max(-1, keepdims=True)
        w = np.clip(lum - float(threshold), 0, None) / np.maximum(lum, 1e-9)
        hi = a[..., :k] * w
        acc = np.zeros_like(hi)
        if mode == "glow":
            for s in (radius, radius / 2, radius / 4):
                if s < 0.3:
                    continue
                g = np.asarray(gaussian_kernel(s / 3.0), np.float64)
                acc += convolve(convolve(hi, g[None, :], border),
                                g[:, None], border)
            acc /= 3.0
        else:
            tmp = CopImage(a.shape[1], a.shape[0], {"h": hi})
            m = max(1, int(rays))
            for i in range(m):
                ang = float(angle) + 180.0 * i / m
                acc += getn(directional_blur(tmp, "h", ray_length, ang,
                                             "centered", 0, border), "h")
            acc = acc / m * 2.0
        r = a.copy()
        r[..., :k] = a[..., :k] + float(intensity) * acc
        put(out, n, r, img)
    return out


def drop_shadow(img, layer=DEFAULT_LAYER, alpha_layer="", offset="8 -8",
                blur=6.0, color="0 0 0", opacity=0.7, border="black"):
    """
    Drop shadow: takes alpha (channel 4 or alpha_layer), translates by offset (pixels, +v up),
    blurs, colors it, and places it **under** the original (over). Outputs RGBA; alpha is the union of both.
    """
    if img is None:
        return CopImage()
    from .filters import gaussian_kernel
    a = getn(img, layer)
    if str(alpha_layer).strip():
        al = np.clip(getn(img, alpha_layer)[..., :1], 0, 1)
    elif a.shape[2] >= 4:
        al = np.clip(a[..., 3:4], 0, 1)
    else:
        raise ValueError(f"'{layer}' has no alpha; give an Alpha Layer")
    ox, oy = _vec(offset, 2)
    W, H = img.xres, img.yres
    J, I = _grid(W, H)
    from .filters import sample
    sh = sample(al, (J - ox + 0.5) / W, (I - oy + 0.5) / H, border)
    if float(blur) > 0.3:
        g = np.asarray(gaussian_kernel(float(blur) / 2.0), np.float64)
        sh = convolve(convolve(sh, g[None, :], "black"), g[:, None], "black")
    sa = np.clip(sh * float(opacity), 0, 1)
    col = _vec(color, 3)
    fg = a[..., :3]
    oa = al + sa * (1 - al)
    rgb = (fg * al + col * sa * (1 - al)) / np.maximum(oa, 1e-12)
    out = img.copy()
    return put(out, layer, np.concatenate([rgb, oa], -1), img)


def feather(img, layer="mask", width=8.0, direction="both", out_layer=""):
    """
    Feather mask edges: smoothstep transition by **distance** to the boundary (exact EDT), width width
    pixels. inward softens only inward (no dilation), outward only outward, both half on each side. Unlike a Gaussian
    blur: in both mode the midline of a thin strip is always > 0.5 (the boundary itself is always 0.5), and sharp corners don't
    get rounded off. inward is different: strips narrower than width fade overall -- that's the literal meaning of
    "soften inward only", not a bug.
    """
    if img is None:
        return CopImage()
    if direction not in ("both", "inward", "outward"):
        raise ValueError("Direction must be one of both / inward / outward")
    from .sdf import edt_sq
    m = getn(img, layer)[..., 0] > 0.5
    din = np.sqrt(edt_sq(~m))        # distance from inside pixels to the outside
    dout = np.sqrt(edt_sq(m))        # distance from outside pixels to the inside
    sd = np.where(m, -din + 0.5, dout - 0.5)     # the boundary lies between two pixels
    w = max(float(width), 1e-9)
    if direction == "both":
        t = 0.5 - sd / w
    elif direction == "inward":
        t = -sd / w
    else:
        t = 1.0 - sd / w
    t = np.clip(t, 0, 1)
    r = t * t * (3 - 2 * t)
    out = img.copy()
    return put(out, str(out_layer).strip() or layer, r[..., None], img)


def pixelate(img, layers="", size=8, mode="average"):
    """Mosaic: size x size blocks take the mean (average) or the block's center pixel (sample)."""
    if img is None:
        return CopImage()
    s = int(size)
    if s < 1:
        raise ValueError("Size must be at least 1")
    out = img.copy()
    W, H = img.xres, img.yres
    by, bx = np.arange(H) // s, np.arange(W) // s
    nby, nbx = by.max() + 1, bx.max() + 1
    for n in names_of(img, layers):
        a = getn(img, n)
        if mode == "average":
            sums = np.zeros((nby, nbx, a.shape[2]))
            cnt = np.zeros((nby, nbx, 1))
            np.add.at(sums, (by[:, None], bx[None, :]), a)
            np.add.at(cnt, (by[:, None], bx[None, :]), 1.0)
            blk = sums / cnt
        else:
            cy = np.minimum(np.arange(nby) * s + s // 2, H - 1)
            cx = np.minimum(np.arange(nbx) * s + s // 2, W - 1)
            blk = a[cy][:, cx]
        put(out, n, blk[by][:, bx], img)
    return out


def chromatic_aberration(img, layer=DEFAULT_LAYER, amount=0.01,
                         center="0.5 0.5", border="clamp"):
    """
    Chromatic aberration: R is scaled up by (1 + amount) about the center, B scaled down by (1 - amount), G unchanged --
    a lens refracts different wavelengths differently, giving color fringes at the edges and none at the center.
    """
    if img is None:
        return CopImage()
    a = getn(img, layer)
    if a.shape[2] < 3:
        raise ValueError("Chromatic aberration needs RGB")
    W, H = img.xres, img.yres
    cu, cv = _vec(center, 2)
    J, I = _grid(W, H)
    u, v = (J + 0.5) / W, (I + 0.5) / H
    from .filters import sample
    r = a.copy()
    for c, s in ((0, 1.0 + float(amount)), (2, 1.0 - float(amount))):
        uu, vv = cu + (u - cu) / s, cv + (v - cv) / s
        r[..., c] = sample(a[..., c:c + 1], uu, vv, border)[..., 0]
    out = img.copy()
    return put(out, layer, r, img)


def heat_distort(img, layers="", amount=4.0, scale=0.05, speed=1.0,
                 time=0.0, direction=90.0, field_layer="", seed=0,
                 border="clamp"):
    """
    Heat distortion: pushes pixels with a noise field drifting toward direction over time (Heat Distort). If
    field_layer is given it's used as a mask for distortion strength (Heat Distort by Layer: only distort above the heat source).
    amount in pixels; scale is the noise's characteristic size (uv units).
    """
    if img is None:
        return CopImage()
    from .noise import simplex
    from . import backend as bk
    W, H = img.xres, img.yres
    J, I = _grid(W, H)
    u, v = (J + 0.5) / W, (I + 0.5) / H
    d = math.radians(float(direction))
    t = float(time) * float(speed)
    s = max(float(scale), 1e-6)
    qx = u / s - math.cos(d) * t
    qy = v / s - math.sin(d) * t
    z = np.full_like(qx, float(seed) * 17.3)
    nx = np.asarray(simplex(bk.EXACT, qx, qy, z, seed=int(seed)))
    ny = np.asarray(simplex(bk.EXACT, qx + 31.7, qy - 11.3, z,
                            seed=int(seed) + 1))
    k = float(amount)
    if str(field_layer).strip():
        k = k * getn(img, field_layer)[..., 0]
    return warp(img, J + nx * k, I + ny * k, layers, border)


SWIRL_MODES = ("swirl", "pinch", "bulge", "bend")


def swirl(img, layers="", mode="swirl", amount=90.0, radius=0.4,
          center="0.5 0.5", border="clamp"):
    """
    swirl: rotates by amount degrees within the radius, falling off as (1 - r/R)²; pinch / bulge: within the radius pulls toward the center
    / bulges outward (amount 0-1, clamped beyond); bend: bends the image horizontally into an arc (amount degrees = central angle
    spanned by the full width). All are inverse maps: for each output pixel, compute where in the input to sample.
    """
    if img is None:
        return CopImage()
    if mode not in SWIRL_MODES:
        raise ValueError(f"Mode must be one of {SWIRL_MODES}")
    W, H = img.xres, img.yres
    J, I = _grid(W, H)
    cu, cv = _vec(center, 2)
    asp = W / H
    x = ((J + 0.5) / W - cu) * asp
    y = (I + 0.5) / H - cv
    r = np.hypot(x, y)
    R = max(float(radius), 1e-9)
    if mode == "swirl":
        f = np.clip(1 - r / R, 0, 1) ** 2
        th = -math.radians(float(amount)) * f
        c, s = np.cos(th), np.sin(th)
        sx, sy = c * x - s * y, s * x + c * y
    elif mode in ("pinch", "bulge"):
        # output radius r samples input radius r·k. k > 1 = sample further out = content shrinks toward the center (pinch),
        # k < 1 = sample further in = the center is magnified (bulge). k = 1 ± a(1 - r/R)²: at R it
        # returns continuously to 1; with a <= 1, r·k is monotonic in r (bulge derivative 1 - a >= 0, pinch minimum
        # 1 - a/3 > 0), so it never folds into ghosting.
        a = min(max(float(amount), 0.0), 1.0)
        sg = 1.0 if mode == "pinch" else -1.0
        t = np.clip(r / R, 0, 1)
        k = np.where(r < R, 1.0 + sg * a * (1 - t) ** 2, 1.0)
        sx, sy = x * k, y * k
    else:
        ang = math.radians(float(amount))
        if abs(ang) < 1e-9:
            sx, sy = x, y
        else:
            Rb = asp / ang                   # arc radius: width = central angle x radius
            # polar coordinates of output point (x, y) about the arc center -> input (arc length, radius difference)
            dy = y + Rb
            th = np.arctan2(x, dy)
            sx = th * Rb
            sy = np.hypot(x, dy) - Rb
    gx = (sx / asp + cu) * W - 0.5
    gy = (sy + cv) * H - 0.5
    return warp(img, gx, gy, layers, border)


def lens_distort(img, layers="", k1=-0.1, k2=0.0, mode="distort",
                 center="0.5 0.5", border="black"):
    """
    Lens distortion (Brown-Conrady radial terms): r_d = r·(1 + k1 r² + k2 r⁴), r normalized by the half
    diagonal. k1 < 0 barrel, > 0 pincushion. distort adds distortion to a clean image; undistort does the reverse,
    closing the round trip with distort. Because it's an inverse map, **distort** is the side that must solve an equation: for the output (distorted)
    pixel radius r_d find r_u with f(r_u) = r_d, 8 Newton steps; undistort plugs into f directly.
    When |k1| is large enough that f isn't monotonic (barrel folding back at the corners) Newton stops on the wrong root -- real lenses aren't
    that extreme.
    """
    if img is None:
        return CopImage()
    if mode not in ("distort", "undistort"):
        raise ValueError("Mode must be one of distort / undistort")
    W, H = img.xres, img.yres
    J, I = _grid(W, H)
    cu, cv = _vec(center, 2)
    norm = math.hypot(W, H) / 2
    x = (J + 0.5 - cu * W) / norm
    y = (I + 0.5 - cv * H) / norm
    r = np.hypot(x, y)
    K1, K2 = float(k1), float(k2)

    def f(rr):
        return rr * (1 + K1 * rr ** 2 + K2 * rr ** 4)

    if mode == "undistort":
        # output (clean) pixel r_u -> position r_d = f(r_u) in the input (distorted) image
        sc = np.where(r > 1e-12, f(r) / np.where(r > 1e-12, r, 1), 1.0)
    else:
        # output (distorted) pixel r_d -> find r_u with f(r_u) = r_d
        ru = r.copy()
        for _ in range(8):
            fp = 1 + 3 * K1 * ru ** 2 + 5 * K2 * ru ** 4
            ru = ru - (f(ru) - r) / np.where(np.abs(fp) > 1e-9, fp, 1e-9)
        sc = np.where(r > 1e-12, ru / np.where(r > 1e-12, r, 1), 1.0)
        # barrel distortion's f peaks at r = 1/√(-3k1) (at k1 = -0.35, f's max is 0.65):
        # output pixels beyond that **have no preimage** -- no point in the clean image gets distorted there.
        # Newton bounces around there and lands anywhere in the image, producing a ring of colored snow (the first version's
        # demo image did exactly that). Check the residual and derivative, and send pixels with no preimage off-screen for border to handle
        # (black = black edge, clamp = edge color).
        fp = 1 + 3 * K1 * ru ** 2 + 5 * K2 * ru ** 4
        bad = (np.abs(f(ru) - r) > 1e-7) | (fp <= 0) | (ru < 0)
        sc = np.where(bad, 1e6, sc)
    gx = x * sc * norm + cu * W - 0.5
    gy = y * sc * norm + cv * H - 0.5
    return warp(img, gx, gy, layers, border)


# ═══════════════════════════════════════════════════════ Derivatives / corners
DERIV_MODES = ("dx", "dy", "gradient", "magnitude", "laplacian",
               "divergence", "curl")


def derivative(img, layer=DEFAULT_LAYER, mode="gradient", scale=1.0,
               border="clamp", out_layer=""):
    """
    The central-difference derivative family (Derivative / Laplacian / Curl), in units "per pixel" x scale:
      dx / dy / gradient (2 channels) / magnitude   on channel 0
      laplacian                                 five-point stencil, per channel
      divergence                                2-channel vector field -> scalar
      curl  1 channel: (∂f/∂y, -∂f/∂x), curl of a scalar field -- a divergence-free flow field (use noise
            as the stream function and you get curl noise's velocity field); 2 channels: ∂v/∂x - ∂u/∂y
    """
    if img is None:
        return CopImage()
    if mode not in DERIV_MODES:
        raise ValueError(f"Mode must be one of {DERIV_MODES}")
    a = getn(img, layer)
    p = pad(a, 1, border)
    dx = (p[1:-1, 2:] - p[1:-1, :-2]) * 0.5
    dy = (p[2:, 1:-1] - p[:-2, 1:-1]) * 0.5
    s = float(scale)
    if mode == "dx":
        r = dx[..., :1]
    elif mode == "dy":
        r = dy[..., :1]
    elif mode == "gradient":
        r = np.concatenate([dx[..., :1], dy[..., :1]], -1)
    elif mode == "magnitude":
        r = np.hypot(dx[..., :1], dy[..., :1])
    elif mode == "laplacian":
        r = (p[1:-1, 2:] + p[1:-1, :-2] + p[2:, 1:-1] + p[:-2, 1:-1]
             - 4 * a)
    elif mode == "divergence":
        if a.shape[2] < 2:
            raise ValueError("divergence needs a 2-channel vector field")
        r = dx[..., 0:1] + dy[..., 1:2]
    else:
        if a.shape[2] == 1:
            r = np.concatenate([dy, -dx], -1)
        else:
            r = dx[..., 1:2] - dy[..., 0:1]
    out = img.copy()
    return put(out, str(out_layer).strip() or f"{layer}_{mode}", r * s, img)


def corner_detect(img, layer=DEFAULT_LAYER, k=0.05, sigma=1.5,
                  threshold=0.01, radius=3, out_layer="corners",
                  response_layer=""):
    """
    Harris corners: structure tensor M = G_σ * [Ix² IxIy; IxIy Iy²], R = det - k·tr²;
    R greater than threshold x max(R) and a local maximum within radius radius -> 1. Returns (image, count).
    """
    if img is None:
        return CopImage(), 0
    from .filters import gaussian_kernel
    a = getn(img, layer)[..., :1]
    p = pad(a, 1, "clamp")
    ix = (p[1:-1, 2:] - p[1:-1, :-2]) * 0.5
    iy = (p[2:, 1:-1] - p[:-2, 1:-1]) * 0.5
    g = np.asarray(gaussian_kernel(float(sigma)), np.float64)

    def G(x):
        return convolve(convolve(x, g[None, :], "clamp"), g[:, None], "clamp")

    A, B, C = G(ix * ix), G(iy * iy), G(ix * iy)
    R = (A * B - C * C) - float(k) * (A + B) ** 2
    R = R[..., 0]
    rr = int(radius)
    pm = np.pad(R, rr, mode="constant", constant_values=-np.inf)
    H, W = R.shape
    mx = np.full_like(R, -np.inf)
    for dy in range(-rr, rr + 1):
        for dx in range(-rr, rr + 1):
            mx = np.maximum(mx, pm[rr + dy:rr + dy + H, rr + dx:rr + dx + W])
    top = float(R.max())
    m = (R >= mx) & (R > float(threshold) * max(top, 1e-30)) & (R > 0)
    out = img.copy()
    put(out, out_layer, m.astype(np.float64)[..., None], img)
    if str(response_layer).strip():
        put(out, response_layer, R[..., None], img)
    return out, int(m.sum())


# ═══════════════════════════════════════════════════════ Fill holes / flood fill
FILL_MODES = ("pushpull", "laplace", "nearest")


def smooth_fill(img, layers="", mask_layer="mask", mode="pushpull",
                iterations=200, rings=0):
    """
    Fill holes (Smooth Fill / Extrapolate Boundaries): pixels with mask > 0.5 are **known**,
    the rest are filled in from the known values.
      pushpull  pyramid downsample then upsample (smooth, O(n), fast even for big holes)
      laplace   solves ∇²f = 0 (fixed at known pixels), Jacobi iteration -- the smoothest membrane, slow
      nearest   pushes the nearest value outward ring by ring (rings = 0 fills everything), boundary extension
    Known pixels stay bit-identical.
    """
    if img is None:
        return CopImage()
    if mode not in FILL_MODES:
        raise ValueError(f"Mode must be one of {FILL_MODES}")
    from ..backproject import _push_pull, _dilate
    known = getn(img, mask_layer)[..., 0] > 0.5
    if not known.any():
        raise ValueError(f"'{mask_layer}' has no known pixels (> 0.5)")
    out = img.copy()
    for n in names_of(img, layers):
        if n == str(mask_layer).strip():
            continue
        a = getn(img, n)
        if mode == "pushpull":
            r = _push_pull(a, known)
        elif mode == "nearest":
            ring = int(rings) or (img.xres + img.yres)
            r, _ = _dilate(a, known, ring)
        else:
            r = _push_pull(a, known)          # a good initial guess, fewer iterations
            kn = known[..., None]
            for _ in range(int(iterations)):
                p = pad(r, 1, "clamp")
                avg = (p[1:-1, 2:] + p[1:-1, :-2] + p[2:, 1:-1]
                       + p[:-2, 1:-1]) * 0.25
                r = np.where(kn, a, avg)
        # all three modes preserve known pixels on their own (in mutation testing, deleting this line still passes every test -- an equivalent
        # mutant). It's kept as a safety net: so a later change to _push_pull can't quietly alter known values.
        r = np.where(known[..., None], a, r)
        put(out, n, r, img)
    return out


def flood_fill(img, layer=DEFAULT_LAYER, seed_uv="0.5 0.5", seed_layer="",
               tolerance=0.1, connectivity=4, out_layer="fill_mask"):
    """
    Flood fill (Fill Connected): starting from seeds (uv coordinates, or pixels with seed_layer > 0.5),
    selects connected pixels whose value differs from **the seed's value** by <= tolerance. Multi-channel uses Euclidean distance.
    Returns (image, selected pixel count). Connectivity uses COP Segment's union-find (8- / 4-connected).
    """
    if img is None:
        return CopImage(), 0
    from .analysis import label
    a = getn(img, layer)
    W, H = img.xres, img.yres
    if str(seed_layer).strip():
        sm = getn(img, seed_layer)[..., 0] > 0.5
        if not sm.any():
            raise ValueError("Seed Layer has no seeds")
        ref = a[sm].mean(0)
    else:
        su, sv = _vec(seed_uv, 2)
        j = int(min(max(math.floor(su * W), 0), W - 1))
        i = int(min(max(math.floor(sv * H), 0), H - 1))
        sm = np.zeros((H, W), bool)
        sm[i, j] = True
        ref = a[i, j]
    close = np.linalg.norm(a - ref, axis=-1) <= float(tolerance)
    lab = label(close, int(connectivity))
    ids = np.unique(lab[sm & close])
    ids = ids[ids > 0]
    m = np.isin(lab, ids)
    out = img.copy()
    put(out, out_layer, m.astype(np.float64)[..., None], img)
    return out, int(m.sum())


def contour(img, layer=DEFAULT_LAYER, interval=0.1, offset=0.0, width=1.0,
            out_layer="contour"):
    """
    Contour lines (Edge Detect by Contour): one line every interval in value, line width width pixels.
    The "value distance" to a line, |frac(h/interval) - ½|, is divided by the gradient magnitude to convert to **pixel distance**,
    so lines are equally thick on steep and gentle parts (without this step lines on gentle slopes smear into a big patch).
    """
    if img is None:
        return CopImage()
    iv = float(interval)
    if not iv > 0:
        raise ValueError("Interval must be > 0")
    h = getn(img, layer)[..., 0]
    q = (h - float(offset)) / iv
    dv = np.abs(q - np.round(q)) * iv        # value distance to the nearest line
    p = np.pad(h, 1, mode="edge")
    g = np.hypot((p[1:-1, 2:] - p[1:-1, :-2]) * 0.5,
                 (p[2:, 1:-1] - p[:-2, 1:-1]) * 0.5)
    dpx = dv / np.maximum(g, 1e-12)
    w = max(float(width), 1e-6)
    r = np.clip(1.0 - (dpx - w * 0.5), 0, 1)
    out = img.copy()
    return put(out, out_layer, r[..., None], img)


DITHERS = ("bayer4", "bayer8", "floyd_steinberg", "white_noise")


def _bayer(n):
    m = np.array([[0, 2], [3, 1]], np.float64)
    while m.shape[0] < n:
        m = np.block([[4 * m, 4 * m + 2], [4 * m + 3, 4 * m + 1]])
    return (m + 0.5) / m.size


def dither(img, layers="", method="bayer4", levels=2, seed=0):
    """
    Dither to levels levels (Surface Dither). bayer ordered dither (tileable, no flicker);
    floyd_steinberg error diffusion (row by row, closest to the original's mean brightness); white_noise random threshold.
    Values are assumed in 0-1 (out-of-range values are clamped first).
    """
    if img is None:
        return CopImage()
    if method not in DITHERS:
        raise ValueError(f"Method must be one of {DITHERS}")
    L = int(levels)
    if L < 2:
        raise ValueError("Levels must be at least 2")
    out = img.copy()
    W, H = img.xres, img.yres
    for n in names_of(img, layers):
        a = np.clip(getn(img, n), 0, 1) * (L - 1)
        if method.startswith("bayer"):
            b = _bayer(int(method[5:]))
            t = np.tile(b, (H // b.shape[0] + 1, W // b.shape[1] + 1))[:H, :W]
            r = np.floor(a + t[..., None]) / (L - 1)
        elif method == "white_noise":
            t = np.random.default_rng(int(seed)).random((H, W, 1))
            r = np.floor(a + t) / (L - 1)
        else:
            # error diffusion is inherently serial. Running per channel on lists of Python floats is an order of magnitude faster than
            # slicing small numpy arrays per pixel (about 2 s for single-channel 1024²).
            r = np.empty_like(a)
            for c in range(a.shape[2]):
                e = [list(map(float, a[y, :, c])) for y in range(H)]
                top = L - 1
                for y in range(H - 1, -1, -1):      # top to bottom (larger row = higher)
                    row = e[y]
                    nxt = e[y - 1] if y > 0 else None
                    for x in range(W):
                        old = row[x]
                        new = float(min(max(round(old), 0), top))
                        row[x] = new
                        err_ = old - new
                        if x + 1 < W:
                            row[x + 1] += err_ * 0.4375
                        if nxt is not None:
                            if x > 0:
                                nxt[x - 1] += err_ * 0.1875
                            nxt[x] += err_ * 0.3125
                            if x + 1 < W:
                                nxt[x + 1] += err_ * 0.0625
                r[..., c] = np.asarray(e)
            r = r / (L - 1)
        put(out, n, np.clip(r, 0, 1), img)
    return out


MIRRORS = ("left_to_right", "right_to_left", "bottom_to_top", "top_to_bottom",
           "quad",
           # pcg100: the two Modes of Houdini Mirror -- mirror planes at arbitrary angles
           "number_and_offset", "custom_planes")


def parse_planes(spec):
    """Multi-line text for Custom Mirror Planes: one mirror per line, `angle offset [reverse 0/1]`."""
    rows = []
    for ln in str(spec).replace(";", "\n").splitlines():
        tk = ln.replace(",", " ").split()
        if not tk:
            continue
        if len(tk) > 3:
            raise ValueError(f"A Mirrors line has at most three items (angle offset reverse): '{ln}'")
        rows.append((float(tk[0]), float(tk[1]) if len(tk) > 1 else 0.0,
                     bool(float(tk[2])) if len(tk) > 2 else False))
    return rows


def mirror_planes(img, layers="", planes=()):
    """
    Mirrors through several mirrors in turn. planes = [(angle°, offset, reverse)], from the first mirror to the last.

    A mirror is a line in image space (origin at the image center, -1 ... 1 across the **long side**,
    square pixels): normal n = (cos θ, sin θ), line through offset·n. **The side n points to
    is overwritten by the mirror image**, the other side is the source -- θ = 0, offset = 0 is the vertical midline, left half mirrored to the right,
    bit-identical to the original left_to_right. reverse = use the n side as the source instead (the line stays put).

    Of these conventions only "θ = 180 equals θ = 0 with reverse" and "positive offset moves the mirror right" are stated
    in the docs; which side is the source and where θ = 0 points are vague in the docs, so the choice consistent with the old node is used.

    Multiple mirrors are applied **in turn** (mirror k acts on the result of the first k-1). The implementation composes the
    coordinate maps and samples only once: I_k[p] = I_{k-1}[f_k(p)], so
    I_N[p] = I_0[f_1(f_2(...f_N(p)))] -- coordinates must be folded **from the last mirror backward**. Resampling per mirror
    would blur once per mirror.
    """
    if img is None:
        return CopImage()
    W, H = img.xres, img.yres
    J, I = _grid(W, H)
    half = 0.5 * max(W, H)
    px, py = J + 0.5 - 0.5 * W, I + 0.5 - 0.5 * H      # pixel coordinates with the image center as origin
    from .transform import _cos_sin        # multiples of 90° give exact 0 / ±1
    for ang, off, rev in list(planes)[::-1]:
        c, s = _cos_sin(ang)
        d = px * c + py * s - float(off) * half
        hit = (d < 0) if rev else (d > 0)
        px = np.where(hit, px - 2 * d * c, px)
        py = np.where(hit, py - 2 * d * s, py)
    return warp(img, px - 0.5 + 0.5 * W, py - 0.5 + 0.5 * H, layers, "clamp")


def mirror(img, layers="", mode="left_to_right", position=0.5, planes=1,
           angle=0.0, offset=0.0, reverse=False, plane_list="0 0"):
    """
    Mirrors one half onto the other (position is the mirror's u / v). quad = bottom-left quarter mirrored to the whole image.

    number_and_offset (Houdini's default mode): planes mirrors, mirror k (k = 1 ... N)
    at angle k·angle (docs: Angle accumulates, "20 with 3 mirrors = 20 / 40 / 60 degrees"),
    all with offset offset. custom_planes: plane_list gives them line by line. These two modes don't read position.
    """
    if img is None:
        return CopImage()
    if mode not in MIRRORS:
        raise ValueError(f"Mode must be one of {MIRRORS}")
    if mode == "number_and_offset":
        return mirror_planes(img, layers, [
            (float(angle) * k, float(offset), bool(reverse))
            for k in range(1, int(planes) + 1)])
    if mode == "custom_planes":
        return mirror_planes(img, layers, parse_planes(plane_list))
    W, H = img.xres, img.yres
    J, I = _grid(W, H)
    pu = float(position) * W - 0.5
    pv = float(position) * H - 0.5
    gx, gy = J.copy(), I.copy()
    if mode in ("left_to_right", "quad"):
        gx = np.where(J > pu, 2 * pu - J, J)
    if mode == "right_to_left":
        gx = np.where(J < pu, 2 * pu - J, J)
    if mode in ("bottom_to_top", "quad"):
        gy = np.where(I > pv, 2 * pv - I, I)
    if mode == "top_to_bottom":
        gy = np.where(I < pv, 2 * pv - I, I)
    return warp(img, gx, gy, layers, "clamp")


# ═══════════════════════════════════════════════════════ Perspective / lattice
def homography(src, dst):
    """Homography matrix from 4 point pairs (DLT), H·src ≈ dst. src / dst are (4,2)."""
    A = []
    for (x, y), (u, v) in zip(src, dst):
        A.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        A.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    _, _, Vt = np.linalg.svd(np.asarray(A, np.float64))
    Hm = Vt[-1].reshape(3, 3)
    return Hm / Hm[2, 2]


PIN_MODES = ("corners", "rotate_3d")


def corner_pin(img, layers="", mode="corners", corners="0 0 1 0 1 1 0 1",
               rotate="0 0 0", fov=45.0, distance=0.0, border="black"):
    """
    Four-corner perspective (Corner Pin / Transform 3D). corners gives the uv of the four corners on the output image:
    bottom-left bottom-right top-right top-left (8 numbers). rotate_3d: treats the image as a card rotated in 3D
    (xyz Euler angles, degrees), shot back with a pinhole camera of fov -- computes the four corners, same homography.
    """
    if img is None:
        return CopImage()
    if mode not in PIN_MODES:
        raise ValueError(f"Mode must be one of {PIN_MODES}")
    W, H = img.xres, img.yres
    src = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float64)
    if mode == "corners":
        dst = _vec(corners, 8).reshape(4, 2)
    else:
        from .pixel import _euler
        R = _euler(*_vec(rotate, 3))
        asp = W / H
        f = 0.5 / math.tan(math.radians(float(fov)) / 2)
        D = float(distance) or f
        pts = np.array([[(x - 0.5) * asp, y - 0.5, 0.0] for x, y in src])
        q = pts @ R.T
        z = D + q[:, 2]
        if (z <= 1e-6).any():
            raise ValueError("The card rotated behind the camera -- reduce the angle or increase Distance")
        dst = np.stack([q[:, 0] * f / z / asp + 0.5, q[:, 1] * f / z + 0.5],
                       -1)
    Hm = homography(dst, src)           # output uv -> input uv (inverse map)
    J, I = _grid(W, H)
    u, v = (J + 0.5) / W, (I + 0.5) / H
    den = Hm[2, 0] * u + Hm[2, 1] * v + Hm[2, 2]
    su = (Hm[0, 0] * u + Hm[0, 1] * v + Hm[0, 2]) / den
    sv = (Hm[1, 0] * u + Hm[1, 1] * v + Hm[1, 2]) / den
    return warp(img, su * W - 0.5, sv * H - 0.5, layers, border)


def lattice_deform(img, layers="", divisions="4 4", offsets="",
                   jitter=0.0, seed=0, border="clamp"):
    """
    Lattice deform: (nx+1)x(ny+1) control points; offsets gives each point's uv displacement (row by row, bottom to top,
    two numbers per point; missing ones are 0), or jitter displaces randomly. The displacement field is bilinearly interpolated to each pixel,
    approximated as an **inverse map** (the output pixel takes the input at -displacement) -- matches the forward map for small displacements.
    """
    if img is None:
        return CopImage()
    nx, ny = (max(1, int(v)) for v in _vec(divisions, 2))
    npt = (nx + 1) * (ny + 1)
    vals = [float(x) for x in str(offsets).replace(",", " ").split()]
    off = np.zeros(npt * 2)
    off[:min(len(vals), npt * 2)] = vals[:npt * 2]
    off = off.reshape(ny + 1, nx + 1, 2)
    if float(jitter) > 0:
        off = off + (np.random.default_rng(int(seed)).random(off.shape)
                     * 2 - 1) * float(jitter)
    W, H = img.xres, img.yres
    J, I = _grid(W, H)
    u, v = (J + 0.5) / W, (I + 0.5) / H
    gxf, gyf = u * nx, v * ny
    x0 = np.clip(np.floor(gxf).astype(int), 0, nx - 1)
    y0 = np.clip(np.floor(gyf).astype(int), 0, ny - 1)
    fx, fy = (gxf - x0)[..., None], (gyf - y0)[..., None]
    d = (off[y0, x0] * (1 - fx) * (1 - fy) + off[y0, x0 + 1] * fx * (1 - fy)
         + off[y0 + 1, x0] * (1 - fx) * fy + off[y0 + 1, x0 + 1] * fx * fy)
    return warp(img, (u - d[..., 0]) * W - 0.5, (v - d[..., 1]) * H - 0.5,
                layers, border)


def _poisson_cascade(m, iters):
    """
    ∇²h = -1 (inside the mask), h = 0 (outside the mask). Plain Jacobi needs ~N² iterations on a region N pixels wide
    to converge, so first solve recursively on a half-size mask and upsample as the initial guess (coarse-grid pixels are
    twice as wide as fine-grid ones, so the same solution in pixel units is x4), then Jacobi iters iterations per level -- a poor man's
    multigrid; a 1024² mask settles in a few hundred iterations.
    """
    H, W = m.shape
    if min(H, W) > 16:
        H2, W2 = (H + 1) // 2, (W + 1) // 2
        mp = np.zeros((H2 * 2, W2 * 2), bool)
        mp[:H, :W] = m
        mc = mp.reshape(H2, 2, W2, 2).any((1, 3))
        hc = _poisson_cascade(mc, iters) * 4.0
        h = np.repeat(np.repeat(hc, 2, 0), 2, 1)[:H, :W]
        h = np.where(m, h, 0.0)
    else:
        h = np.zeros(m.shape)
    for _ in range(iters):
        p = np.pad(h, 1)
        h = np.where(m, (p[1:-1, 2:] + p[1:-1, :-2] + p[2:, 1:-1]
                         + p[:-2, 1:-1] + 1.0) * 0.25, 0.0)
    return h


def planar_inflate(img, layer="mask", mode="round", height=1.0,
                   iterations=200, out_layer="height"):
    """
    Planar inflate: mask -> puffed-up height (a starting point for embossing, text bevels, normals).
      round    circular-arc profile h = √(2Rd - d²)/R, d = distance to the boundary, R = max inner distance --
               vertical at the edges, flat on top, like a puffy pillow
      poisson  solves ∇²h = -1 with boundary h = 0 (soap bubble / balloon), coarse-to-fine Jacobi
    Both are normalized so the maximum = height.
    """
    if img is None:
        return CopImage()
    if mode not in ("round", "poisson"):
        raise ValueError("Mode must be one of round / poisson")
    from .sdf import edt_sq
    m = getn(img, layer)[..., 0] > 0.5
    if not m.any():
        raise ValueError(f"'{layer}' is empty")
    if mode == "round":
        d = np.sqrt(edt_sq(~m)) - 0.5
        d = np.where(m, np.maximum(d, 0.0), 0.0)
        R = max(float(d.max()), 1e-9)
        dd = np.minimum(d, R)
        h = np.sqrt(np.maximum(2 * R * dd - dd * dd, 0.0)) / R
    else:
        h = _poisson_cascade(m, int(iterations))
        h = h / max(float(h.max()), 1e-12)
    out = img.copy()
    return put(out, out_layer, (h * float(height))[..., None], img)


COPY_OPS = ("over", "add", "max",
            # pcg100: Over / Under from Houdini's Blend Method (see copy_transform)
            "over_last", "under")


def copy_transform(img, layers="", copies=4, translate="0.1 0", rotate=0.0,
                   scale=1.0, pivot="0.5 0.5", op="over", fade=0.0,
                   scale_xy="1 1"):
    """
    Copy-transform: copy i (i = 0 ... copies-1) is translated by i·translate (uv), rotated by i·rotate degrees,
    scaled by scale^i, and stacked by op (over uses alpha, or copy 0 on top; add sums; max
    takes the larger). fade multiplies each copy by (1 - fade)^i.

    scale_xy (pcg100): Houdini's non-uniform Scale, multiplied with Uniform Scale -- copy i's
    scale is ((sx·scale)^i, (sy·scale)^i).

    over_last / under (pcg100) are Houdini's Over / Under:
      over_last  later copies go over earlier ones (docs: new copies over previous)
      under      later copies go under earlier ones (copy 0 on top)
    The old over is actually "copy 0 on top", the **opposite** direction of Houdini's Over, and it
    interpolates alpha as an ordinary channel (the resulting alpha isn't composited). The behaviour can't change, so
    the two correct modes get new tokens: they use Porter-Duff, alpha is computed, and fade multiplies only alpha, not color (with non-premultiplied
    color, multiplying color again would fade it twice). A layer without alpha is treated as **fully opaque over the whole frame** (Houdini:
    a layer without alpha counts as alpha = 1): each copy's alpha = the area its frame covers (an
    all-ones image put through the same transform) x fade. So under over_last a later copy's whole frame
    (black areas included) covers the earlier ones; under under copy 0 covers the whole image and the result is the original --
    to stack shapes as shapes, give the layer an alpha.
    """
    if img is None:
        return CopImage()
    if op not in COPY_OPS:
        raise ValueError(f"Op must be one of {COPY_OPS}")
    from .transform import transform
    n = int(copies)
    if n < 1:
        raise ValueError("Copies must be at least 1")
    tx, ty = _vec(translate, 2)
    pu, pv = _vec(pivot, 2)
    sx, sy = _vec(scale_xy, 2) * float(scale)
    out = img.copy()
    names = names_of(img, layers)
    if op in ("over_last", "under"):
        from .composite import porter_duff
        from . import backend as bk
        cov_name = "__coverage"
        while cov_name in img:
            cov_name += "_"
        src = img.copy()
        put(src, cov_name, np.ones((img.yres, img.xres, 1)), img)
        accs = {nm: None for nm in names}
        for i in range(n):
            t = transform(src, (tx * i, ty * i), float(rotate) * i,
                          (sx ** i, sy ** i), (pu, pv), "uv", "black",
                          "bilinear", " ".join(names + [cov_name]))
            w = (1.0 - float(fade)) ** i
            cov = getn(t, cov_name)
            for nm in names:
                a = getn(t, nm)
                if a.shape[2] == 4:
                    a = np.concatenate([a[..., :3], a[..., 3:4] * w], -1)
                    if accs[nm] is None:
                        accs[nm] = a
                    elif op == "over_last":
                        accs[nm] = porter_duff(accs[nm], a, "over", bk.NUMPY)
                    else:
                        accs[nm] = porter_duff(a, accs[nm], "over", bk.NUMPY)
                    continue
                # no alpha: copy 0 (untransformed) opaquely covers the whole frame, so under
                # under it hides all later copies -- the result is just copy 0, no more stacking needed.
                # over_last stacks with premultiplied over: colors sampled with the black border are already multiplied by
                # the coverage
                if accs[nm] is None:
                    accs[nm] = a
                elif op == "over_last":
                    accs[nm] = a * w + accs[nm] * (1 - cov * w)
        for nm in names:
            put(out, nm, accs[nm], img)
        return out
    accs = {nm: None for nm in names}
    for i in range(n - 1, -1, -1):
        t = transform(img, (tx * i, ty * i), float(rotate) * i,
                      (sx ** i, sy ** i), (pu, pv),
                      "uv", "black", "bilinear", " ".join(names))
        w = (1.0 - float(fade)) ** i
        for nm in names:
            a = getn(t, nm) * w
            acc = accs[nm]
            if acc is None:
                accs[nm] = a
            elif op == "add":
                accs[nm] = acc + a
            elif op == "max":
                accs[nm] = np.maximum(acc, a)
            else:
                if a.shape[2] >= 4:
                    al = np.clip(a[..., 3:4], 0, 1)
                else:
                    al = (np.abs(a).sum(-1, keepdims=True) > 0).astype(float)
                accs[nm] = a * al + acc * (1 - al)
    for nm in names:
        put(out, nm, accs[nm], img)
    return out
