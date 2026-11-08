"""
Analysis / solve (first half of batch D): FFT and frequency filtering, prefix sum, Poisson equation, eikonal equation,
segment by value, bounding rectangle, compare and blend.

All numpy (computed in float64, put back on the input's backend). Shared conventions:

  · pixel spacing = 1, "per pixel" units. To switch to uv units, multiply by W yourself
  · one of three boundaries (in Poisson / Eikonal it is the edge of the solve region):
      periodic  top/bottom and left/right wrap around (FFT does this naturally)
      neumann   outside the edge mirrors the inside (zero normal derivative)
      dirichlet some pixels are fixed by a "known values" mask
"""
from __future__ import annotations

import json
import math

import numpy as np

from .core import CopImage
from .pixel import getn, put, names_of
from . import accel as _AC

FFT_MODES = ("forward", "inverse", "magnitude", "filter")
FILTERS = ("lowpass", "highpass", "bandpass", "bandstop")
SCAN_DIRS = ("u", "v", "both", "u_reverse", "v_reverse")
BOUNDARIES = ("periodic", "neumann", "dirichlet")
POISSON_SOURCES = ("laplacian", "gradient")
COMPARE_OPS = ("a_greater", "a_less", "brighter", "darker", "closer_to_value",
               "mask")


# ═══════════════════════════════════════════════════════════ FFT
def _freq(H, W):
    """Frequency of each FFT bin (cycles per image), in the same layout as np.fft.fft2."""
    fy = np.fft.fftfreq(H) * H
    fx = np.fft.fftfreq(W) * W
    return np.meshgrid(fx, fy)


def fft(img, layer="C", mode="forward", centered=True, filter="lowpass",
        cutoff=8.0, cutoff_high=32.0, softness=2.0, out_layer=""):
    """
    Fast Fourier Transform / Filter Frequencies.

      forward    channel 0 -> 2 channels (Re, Im). Centered moves DC to the image center
                 (fftshift), for viewing the spectrum; inverse must use the same Centered setting
      inverse    2 channels (Re, Im) -> 1 channel, the real part
      magnitude  log(1 + |F|), for viewing the spectrum, per channel. Centered as in forward (before pcg90
                 this mode always moved it to the center regardless of the toggle)
                 filter mode is image in and image out, so Centered is meaningless for it (hidden on the panel)
      filter     per channel: transform -> multiply by a radial window -> inverse transform. Cutoff is in **cycles per image**
                 (image width = 1 cycle), radial as an ellipse (u and v each by their own size). The window edge uses
                 a cosine transition Softness cycles wide; a hard cutoff rings (Gibbs)

    Normalization: forward doesn't divide, inverse divides by N (numpy's default) -- the DC component = sum of pixels.
    """
    if img is None:
        return CopImage()
    if mode not in FFT_MODES:
        raise ValueError(f"Mode must be one of {FFT_MODES}")
    a = getn(img, layer)
    H, W = a.shape[:2]
    out = img.copy()
    name = str(out_layer).strip() or f"{layer}_{mode}"
    if mode == "forward":
        F = np.fft.fft2(a[..., 0])
        if centered:
            F = np.fft.fftshift(F)
        return put(out, name, np.stack([F.real, F.imag], -1), img)
    if mode == "inverse":
        if a.shape[2] < 2:
            raise ValueError("inverse needs a 2-channel (Re, Im) layer")
        F = a[..., 0] + 1j * a[..., 1]
        if centered:
            F = np.fft.ifftshift(F)
        return put(out, name, np.fft.ifft2(F).real, img)
    if mode == "magnitude":
        sh = np.fft.fftshift if centered else (lambda F: F)
        r = np.stack([np.log1p(np.abs(sh(np.fft.fft2(a[..., c]))))
                      for c in range(a.shape[2])], -1)
        return put(out, name, r, img)
    if filter not in FILTERS:
        raise ValueError(f"Filter must be one of {FILTERS}")
    fx, fy = _freq(H, W)
    rad = np.hypot(fx, fy)
    sw = max(float(softness), 1e-9)

    def step(c0):
        # cosine step from 0 -> 1, centered at c0, width sw
        t = np.clip((rad - c0) / sw + 0.5, 0.0, 1.0)
        return 0.5 - 0.5 * np.cos(math.pi * t)

    lo, hi = float(cutoff), float(cutoff_high)
    if filter == "lowpass":
        win = 1.0 - step(lo)
    elif filter == "highpass":
        win = step(lo)
    elif filter == "bandpass":
        win = step(lo) * (1.0 - step(hi))
    else:
        win = 1.0 - step(lo) * (1.0 - step(hi))
    r = np.stack([np.fft.ifft2(np.fft.fft2(a[..., c]) * win).real
                  for c in range(a.shape[2])], -1)
    return put(out, str(out_layer).strip() or layer, r, img)


# ═══════════════════════════════════════════════════════════ Prefix sum
def prefix_sum(img, layers="", direction="both", integrate=False,
               exclusive=False):
    """
    Prefix Sum / Integrate Volume. u: accumulate along +u (per row); v: along +v; both: 2D
    accumulation (integral image / summed-area table -- any rectangle's sum in four lookups); *_reverse goes backwards.
    exclusive: excludes itself (the first is 0). integrate: multiplies by pixel width (1/W in u, 1/H
    in v), giving the value integrated over uv.
    """
    if img is None:
        return CopImage()
    if direction not in SCAN_DIRS:
        raise ValueError(f"Direction must be one of {SCAN_DIRS}")
    out = img.copy()
    for n in names_of(img, layers):
        a = getn(img, n)
        H, W = a.shape[:2]
        if direction.endswith("reverse"):
            ax = 1 if direction.startswith("u") else 0
            r = np.flip(np.cumsum(np.flip(a, ax), ax), ax)
            if exclusive:
                r = r - a
            sc = (1.0 / W) if ax == 1 else (1.0 / H)
        else:
            axes = {"u": (1,), "v": (0,), "both": (0, 1)}[direction]
            r = a
            for ax in axes:
                r = np.cumsum(r, ax)
            if exclusive:
                for ax in axes:
                    r = np.roll(r, 1, ax)
                    idx = [slice(None)] * 3
                    idx[ax] = 0
                    r[tuple(idx)] = 0.0
            sc = 1.0
            for ax in axes:
                sc *= (1.0 / W) if ax == 1 else (1.0 / H)
        put(out, n, r * sc if integrate else r, img)
    return out


# ═══════════════════════════════════════════════════════════ Poisson
def laplacian(u, boundary="neumann", X=None):
    """
    Five-point Laplacian. periodic uses roll; neumann mirrors outside the edge (= one fewer neighbor on the edge).
    X: accel's compute engine (numpy by default) -- water waves / fluids on GPU use the same function.
    """
    X = X or _AC.NUMPY
    if boundary == "periodic":
        return (X.roll(u, 1, 0) + X.roll(u, -1, 0) + X.roll(u, 1, 1)
                + X.roll(u, -1, 1) - 4 * u)
    p = X.pad(u, 1, "edge")
    return (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:] - 4 * u)


def divergence(gx, gy, boundary="neumann", X=None):
    """
    Backward-difference divergence -- paired with the forward-difference gradient, div∘grad is exactly the five-point Laplacian.
    So "rebuilding height from a gradient" is exact in the discrete sense (recovered to 1e-9 in tests).
    """
    X = X or _AC.NUMPY
    if boundary == "periodic":
        return (gx - X.roll(gx, 1, 1)) + (gy - X.roll(gy, 1, 0))
    dx = X.zeros_like(gx)
    dy = X.zeros_like(gy)
    dx[:, 0] = gx[:, 0]
    dx[:, 1:] = gx[:, 1:] - gx[:, :-1]
    dy[0, :] = gy[0, :]
    dy[1:, :] = gy[1:, :] - gy[:-1, :]
    return dx + dy


def grad_fwd(u, boundary="neumann", X=None):
    """Forward difference; under neumann the last column / row is 0, periodic wraps around."""
    X = X or _AC.NUMPY
    if boundary == "periodic":
        return X.roll(u, -1, 1) - u, X.roll(u, -1, 0) - u
    gx = X.zeros_like(u)
    gy = X.zeros_like(u)
    gx[:, :-1] = u[:, 1:] - u[:, :-1]
    gy[:-1, :] = u[1:, :] - u[:-1, :]
    return gx, gy


def _solve_periodic(f, X=None):
    """
    ∇²u = f on a torus: FFT diagonalizes the five-point Laplacian. Requires Σf = 0 (subtract the mean if not).
    Real FFT (rfft2): f is real, so only half the spectrum is stored -- twice as fast as complex fft2, half the memory.
    """
    X = X or _AC.NUMPY
    H, W = f.shape[0], f.shape[1]
    ky = 2 * X.cos(2 * math.pi * X.fftfreq(H))[:, None]
    kx = 2 * X.cos(2 * math.pi * X.rfftfreq(W))[None, :]
    den = kx + ky - 4.0
    den[0, 0] = 1.0
    F = X.rfft2(f - f.mean())
    U = F / den
    U[0, 0] = 0.0
    return X.irfft2(U, (H, W))


def _solve_neumann(f, X=None):
    """
    ∇²u = f with neumann boundary (five-point, outside = mirror of inside, the same operator as laplacian(..., "neumann")),
    **direct solve**, no iteration: even-extend f to 2H x 2W (mirror once left/right and once top/bottom),
    solve on that big image with periodic boundary by FFT, then take back the top-left block.

    Why it works: after mirror extension, the "left neighbor" the periodic Laplacian sees at column 0 of the original image is exactly
    its own mirror -- identical to neumann's "outside = inside"; uniqueness of the solution guarantees
    the big image's solution is itself mirror-symmetric, and restricted back to the original image it solves the original problem. (Equivalent to DCT-II
    diagonalization; numpy just has no DCT, so we take a detour.)

    Before pcg64 this was conjugate gradient: on real hardware 1024^2 with default parameters ran the full 2000 iterations, 58 s,
    **and still hadn't converged** (512^2 already needed 1975 iterations). Now 1024^2 takes under a second, residual around 1e-12.
    Requires Σf = 0, otherwise the mean is subtracted; the mean of u is set to 0.
    Mirroring uses X.flip, not [::-1]: torch doesn't support negative-stride slicing.
    """
    X = X or _AC.NUMPY
    H, W = f.shape[0], f.shape[1]
    ext = X.empty((2 * H, 2 * W))
    ext[:H, :W] = f
    ext[:H, W:] = X.flip(f, 1)
    ext[H:, :W] = X.flip(f, 0)
    ext[H:, W:] = X.flip(f, (0, 1))
    u = _solve_periodic(ext, X)[:H, :W]
    return u - u.mean()


def _cg(apply, b, x0, tol, maxit, precond=None):
    """
    (Preconditioned) conjugate gradient, A symmetric positive definite. precond(r) ≈ A⁻¹r; if given, it's PCG.
    Returns (x, iteration count, relative residual ||r||/||b||).
    """
    x = x0.copy()
    r = b - apply(x)
    z = precond(r) if precond else r
    p = z.copy()
    rz = float((r * z).sum())
    nb = max(math.sqrt(float((b * b).sum())), 1e-300)
    res = math.sqrt(float((r * r).sum())) / nb
    it = 0
    if res < tol:
        return x, 0, res
    for it in range(1, int(maxit) + 1):
        Ap = apply(p)
        den = float((p * Ap).sum())
        if den == 0:
            break
        al = rz / den
        x += al * p
        r -= al * Ap
        res = math.sqrt(float((r * r).sum())) / nb
        if res < tol:
            break
        z = precond(r) if precond else r
        rz_new = float((r * z).sum())
        p = z + (rz_new / rz) * p
        rz = rz_new
    return x, it, res


def solve_poisson(img, layer="rhs", source="laplacian", boundary="neumann",
                  fixed_layer="", value_layer="", tolerance=1e-8,
                  max_iterations=2000, out_layer="solution"):
    """
    Solve Poisson: ∇²u = f (five-point stencil, pixel spacing 1).

    source:
      laplacian  layer is f
      gradient   layer is a 2-channel gradient field g; solves ∇²u = div g -- in the least-squares sense
                 the u "whose gradient is most like g": normal map -> height (convert normals to slopes
                 -Nx/Nz, -Ny/Nz first), gradient-domain editing and Poisson blending are all this step
    boundary:
      periodic   FFT exact solve (mean of u set to 0)
      neumann    mirror extension + FFT exact solve (mean of u set to 0; a pure neumann solution is defined up to a constant)
      dirichlet  pixels with Fixed Layer > 0.5 are fixed to Value Layer's values (fixed to 0 if not
                 given); the rest is solved by conjugate gradient, preconditioned with neumann's direct FFT solve;
                 neumann outside the image

    Returns (image, report dict: iteration count, relative residual).
    """
    if img is None:
        return CopImage(), {}
    if boundary not in BOUNDARIES:
        raise ValueError(f"Boundary must be one of {BOUNDARIES}")
    if source not in POISSON_SOURCES:
        raise ValueError(f"Source must be one of {POISSON_SOURCES}")
    a = getn(img, layer)
    bnd = "periodic" if boundary == "periodic" else "neumann"
    if source == "gradient":
        if a.shape[2] < 2:
            raise ValueError("gradient mode needs a 2-channel (∂u/∂x, ∂u/∂y) layer")
        f = divergence(a[..., 0], a[..., 1], bnd)
    else:
        f = a[..., 0]
    rep = {}
    if boundary == "periodic":
        u = _solve_periodic(f)
        rep = {"iterations": 0, "residual": float(np.abs(
            laplacian(u, "periodic") - (f - f.mean())).max())}
    elif boundary == "neumann":
        # pure neumann is solvable only if Σf = 0, so project out the mean first; the null space of the solution is the constants
        u = _solve_neumann(f)
        rep = {"iterations": 0, "residual": float(np.abs(
            laplacian(u, "neumann") - (f - f.mean())).max())}
    else:
        fl = str(fixed_layer).strip()
        if not fl:
            raise ValueError("dirichlet needs a Fixed Layer (pixels > 0.5 are known)")
        fixed = getn(img, fl)[..., 0] > 0.5
        if not fixed.any():
            raise ValueError("Fixed Layer has no known pixels")
        vl = str(value_layer).strip()
        val = getn(img, vl)[..., 0] if vl else np.zeros(f.shape)
        free = ~fixed
        base = np.where(fixed, val, 0.0)
        # move the known values to the right-hand side: -∇²(u_free) = -f + ∇²(base), solved only on free
        rhs = np.where(free, -f + laplacian(base, "neumann"), 0.0)

        def A(x):
            return np.where(free, -laplacian(np.where(free, x, 0.0),
                                             "neumann"), 0.0)
        def M(r):
            # preconditioner: (-∇²)⁻¹ approximated by neumann's direct solve, then restricted to free.
            # symmetric positive semidefinite; with few walls (fixed pixels) it's almost the exact inverse and converges in a few iterations
            return np.where(free, -_solve_neumann(np.where(free, r, 0.0)),
                            0.0)
        x, it, res = _cg(A, rhs, np.zeros_like(f), float(tolerance),
                         max_iterations, M)
        u = np.where(fixed, val, x)
        rep = {"iterations": it, "residual": res}
    out = img.copy()
    put(out, str(out_layer).strip() or "solution", u, img)
    return out, rep


# ═══════════════════════════════════════════════════════════ Eikonal equation
def eikonal(img, seed_layer="seed", speed_layer="", speed=1.0, max_sweeps=60,
            tolerance=1e-6, out_layer="arrival", id_layer=""):
    """
    Eikonal: |∇T| = 1 / F, arrival time starting from pixels with Seed Layer > 0.5 (T = 0).
    F is speed (Speed Layer x Speed; 0 = wall, impassable, T = inf is output as -1).
    With F = 1, T is the geodesic distance **walking around obstacles** (pixels).

    Method: Godunov upwind scheme + fast sweeping (Zhao 2005): Gauss-Seidel in the four quadrant orders
    in turn, vectorized by anti-diagonal, until max change < Tolerance (2-3 rounds for a point source).
    First-order scheme; error is largest in diagonal directions near the seed (relative error ~10% within a few pixels), farther away
    the relative error drops to the 1% range; the tests set bounds.

    id_layer: if given, also propagates "which piece is the nearest seed" (connected-component id of the seed mask).
    Returns (image, report: sweep count, converged or not).
    """
    if img is None:
        return CopImage(), {}
    seed = getn(img, seed_layer)[..., 0] > 0.5
    if not seed.any():
        raise ValueError(f"'{seed_layer}' has no seeds (> 0.5)")
    H, W = seed.shape
    Fv = np.full((H, W), float(speed))
    if str(speed_layer).strip():
        Fv = Fv * getn(img, speed_layer)[..., 0]
    inv = np.where(Fv > 1e-12, 1.0 / np.maximum(Fv, 1e-12), np.inf)
    T = np.where(seed, 0.0, np.inf)
    want_id = bool(str(id_layer).strip())
    if want_id:
        from .analysis import label
        sid = label(seed, 8).astype(np.float64)
    else:
        sid = np.zeros((H, W))
    big = np.inf
    # pad one ring: outside is inf (nothing comes from outside the image), frozen
    P = np.pad(np.where(seed, 0.0, big), 1, constant_values=big)
    Ip = np.pad(np.where(seed, sid, 0.0), 1)
    Hp = np.pad(inv, 1, constant_values=big)
    Sp = np.pad(seed, 1, constant_values=True)
    # pixels on anti-diagonal k = i + j depend only on those on k - 1 (in this sweep direction),
    # so a whole anti-diagonal is updated vectorized -- this is the four-quadrant-order Gauss-Seidel
    # fast sweep, just with a different traversal order. The first draft, "row by row, Jacobi within a row", corrected only one pixel
    # per round in diagonal directions; a 101^2 point source hadn't converged after 24 rounds. By anti-diagonal it converges in 2-3
    diags = []
    for k in range(H + W - 1):
        ii = np.arange(max(0, k - W + 1), min(H - 1, k) + 1)
        diags.append((ii + 1, k - ii + 1))

    sweeps = 0
    converged = False
    for sweeps in range(1, int(max_sweeps) + 1):
        T_old = P.copy()
        for fy in (False, True):
            for fx in (False, True):
                V, IV, HV, SV_ = P, Ip, Hp, Sp
                if fy:
                    V, IV, HV, SV_ = V[::-1], IV[::-1], HV[::-1], SV_[::-1]
                if fx:
                    V, IV, HV, SV_ = (V[:, ::-1], IV[:, ::-1], HV[:, ::-1],
                                      SV_[:, ::-1])
                for r, c in diags:
                    lf, rt = V[r, c - 1], V[r, c + 1]
                    up, dn = V[r - 1, c], V[r + 1, c]
                    a = np.minimum(lf, rt)
                    b = np.minimum(up, dn)
                    h = HV[r, c]
                    with np.errstate(invalid="ignore"):
                        lo, hi = np.minimum(a, b), np.maximum(a, b)
                        t1 = lo + h
                        t2 = 0.5 * (a + b + np.sqrt(np.maximum(
                            2 * h * h - (a - b) ** 2, 0.0)))
                        tn = np.where(t1 <= hi, t1, t2)
                    cur = V[r, c]
                    better = (tn < cur) & ~SV_[r, c]
                    if better.any():
                        ida = np.where(lf <= rt, IV[r, c - 1], IV[r, c + 1])
                        idb = np.where(up <= dn, IV[r - 1, c], IV[r + 1, c])
                        V[r, c] = np.where(better, tn, cur)
                        IV[r, c] = np.where(better, np.where(a <= b, ida,
                                                             idb), IV[r, c])
        fin = np.isfinite(P) & np.isfinite(T_old)
        ch = float(np.abs(P[fin] - T_old[fin]).max()) if fin.any() else 0.0
        newly = bool((np.isfinite(P) & ~np.isfinite(T_old)).any())
        if ch < float(tolerance) and not newly:
            converged = True
            break
    T = P[1:-1, 1:-1]
    ID = Ip[1:-1, 1:-1]
    out = img.copy()
    put(out, str(out_layer).strip() or "arrival",
        np.where(np.isfinite(T), T, -1.0), img)
    if want_id:
        put(out, str(id_layer).strip(), np.where(np.isfinite(T), ID, 0.0),
            img)
    return out, {"sweeps": sweeps, "converged": converged}


# ═══════════════════════════════════════════════════════════ Segmentation / bounding box / selection
def segment_by_value(img, layer="C", mode="bins", bins=8, step=0.0,
                     connected=True, connectivity=8, out_layer="id"):
    """
    Segment by Value / Mono to ID. First bin the values: bins = N equal bins over [min, max],
    step = fixed step size (bin = floor(v / step)), unique = one bin per distinct value (Mono to
    ID: an image that already holds integer ids is used directly). With connected, **disconnected** pieces in the same bin are split further
    (numbered by area, largest first); otherwise id = bin number + 1. 0 is reserved for "none".
    Returns (image, piece count).
    """
    if img is None:
        return CopImage(), 0
    if mode not in ("bins", "step", "unique", "cast"):
        raise ValueError("Mode must be one of bins / step / unique / cast")
    v = getn(img, layer)[..., 0]
    if mode == "cast":
        # Houdini's Mono to ID (Conversion = Cast): float converted directly to int, truncating toward 0
        # (C (int) semantics), **no renumbering** and no connectivity -- the old unique bins would
        # squash values to 1..K, so existing ids couldn't be mapped back. count = number of distinct ids
        ids = np.trunc(v)
        out = img.copy()
        put(out, str(out_layer).strip() or "id", ids, img)
        return out, int(len(np.unique(ids)))
    if mode == "bins":
        lo, hi = float(v.min()), float(v.max())
        n = max(1, int(bins))
        q = np.clip(np.floor((v - lo) / max(hi - lo, 1e-300) * n), 0, n - 1)
    elif mode == "step":
        st = float(step)
        if not st > 0:
            raise ValueError("step mode needs Step > 0")
        q = np.floor(v / st)
    else:
        _, q = np.unique(v, return_inverse=True)
        q = q.reshape(v.shape).astype(np.float64)
    if not connected:
        uq, inv = np.unique(q, return_inverse=True)
        ids = inv.reshape(v.shape) + 1
        count = len(uq)
    else:
        from .analysis import label
        ids = np.zeros(v.shape, np.int64)
        nxt = 0
        # connectivity per bin separately, then unified numbering by "area descending, first pixel position" -- stable
        parts = []
        for val in np.unique(q):
            lab = label(q == val, int(connectivity))
            k = int(lab.max())
            for j in range(1, k + 1):
                m = lab == j
                parts.append((-int(m.sum()), int(np.argmax(m.ravel())), m))
        parts.sort(key=lambda t: (t[0], t[1]))
        for nxt, (_, _, m) in enumerate(parts, 1):
            ids[m] = nxt
        count = len(parts)
    out = img.copy()
    put(out, str(out_layer).strip() or "id", ids.astype(np.float64), img)
    return out, int(count)


def bounding_rect(img, layer="mask", threshold=0.5, per_id=False,
                  padding=0, out_layer="rect"):
    """
    Bounding Rectangle: axis-aligned bounding box of the mask (> Threshold). per_id: layer is treated as an id
    image, one box per id (> 0). Output: out_layer is the boxes' fill mask (filled with id when per_id),
    the report is JSON: each box's pixel range [x0, y0, x1, y1] (inclusive, y up) and uv range
    [u0, v0, u1, v1] (pixel edges, not centers).
    """
    if img is None:
        return CopImage(), "[]"
    a = getn(img, layer)[..., 0]
    H, W = a.shape
    pad = int(padding)
    boxes = []
    fill = np.zeros((H, W))
    keys = [None]
    if per_id:
        keys = [int(k) for k in np.unique(np.rint(a)) if k > 0]
    for k in keys:
        m = (np.rint(a) == k) if per_id else (a > float(threshold))
        if not m.any():
            continue
        ys = np.nonzero(m.any(1))[0]
        xs = np.nonzero(m.any(0))[0]
        x0 = max(int(xs[0]) - pad, 0)
        x1 = min(int(xs[-1]) + pad, W - 1)
        y0 = max(int(ys[0]) - pad, 0)
        y1 = min(int(ys[-1]) + pad, H - 1)
        fill[y0:y1 + 1, x0:x1 + 1] = float(k) if per_id else 1.0
        boxes.append({"id": k, "pixels": [x0, y0, x1, y1],
                      "uv": [x0 / W, y0 / H, (x1 + 1) / W, (y1 + 1) / H]})
    out = img.copy()
    put(out, str(out_layer).strip() or "rect", fill, img)
    return out, json.dumps(boxes)


def _luma(a):
    if a.shape[2] >= 3:
        return a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722
    return a[..., 0]


def compare_blend(img, a_layer="A", b_layer="B", op="a_greater", value=0.5,
                  key_layer="", softness=0.0, out_layer="result",
                  mask_layer="select_mask"):
    """
    Compare and Blend: per-pixel comparison, picking A or B (mask = 1 takes A).
      a_greater / a_less     compare channel 0
      brighter / darker      compare luminance (Rec.709), "pick the brighter / darker one"
      closer_to_value        whichever is closer to Value
      mask                   Key Layer > Value takes A
    Softness > 0: smooth transition using difference / Softness (not a hard cut); when the two are close they blend.
    When A and B have different channel counts, the smaller one is used.
    """
    if img is None:
        return CopImage()
    if op not in COMPARE_OPS:
        raise ValueError(f"Op must be one of {COMPARE_OPS}")
    A = getn(img, a_layer)
    B = getn(img, b_layer)
    if A.shape[:2] != B.shape[:2]:
        raise ValueError("A and B have different resolutions")
    C = min(A.shape[2], B.shape[2])
    A, B = A[..., :C], B[..., :C]
    if op == "a_greater":
        d = A[..., 0] - B[..., 0]
    elif op == "a_less":
        d = B[..., 0] - A[..., 0]
    elif op == "brighter":
        d = _luma(A) - _luma(B)
    elif op == "darker":
        d = _luma(B) - _luma(A)
    elif op == "closer_to_value":
        d = np.abs(B[..., 0] - float(value)) - np.abs(A[..., 0] - float(value))
    else:
        kl = str(key_layer).strip()
        if not kl:
            raise ValueError("mask mode needs a Key Layer")
        d = getn(img, kl)[..., 0] - float(value)
    s = float(softness)
    if s > 0:
        m = np.clip(d / s + 0.5, 0.0, 1.0)
    else:
        m = (d > 0).astype(np.float64)
    out = img.copy()
    put(out, str(out_layer).strip() or "result",
        A * m[..., None] + B * (1 - m[..., None]), img)
    if str(mask_layer).strip():
        put(out, mask_layer, m, img)
    return out
