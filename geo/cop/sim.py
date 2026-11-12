"""
Simulation (second half of batch D): reaction-diffusion / Turing patterns, water waves (Ripple), 2D fluid (Flow),
ocean (Ocean Spectrum + Evaluate).

In Houdini these are a piece of network wrapped in "Block Begin / Block End", iterated each frame. ComfyUI has no
state between frames, so here **one node runs N steps** and the state lives in the output's layers: connect the output back in (or
use the plugin's Frame For loop) and it continues from that step -- each simulation recognizes its own state layer names, continuing if present,
starting from the initial conditions if not.

Boundaries are uniformly one of three: wrap (tiling) / clamp (wall, reflecting) / plus a few simulation-specific ones (water waves'
absorb).

━━ Where it computes (pcg65)
The iteration loops of reaction-diffusion, water waves and fluid go through accel's compute engine: with Compute = auto, if CUDA is available
and the image is large enough it is moved to the GPU and computed in **float64**, then put back on the original backend. One code path, two routes; the tests
compare numpy and torch pixel by pixel to 1e-9. The ocean is a one-shot FFT, not iterated, and stays numpy.
"""
from __future__ import annotations

import math

import numpy as np

from ..progress import Progress

from .core import CopImage
from .pattern import _base, rnd
from .pixel import getn, put
from . import solve as SV
from . import accel as AC

RD_PRESETS = {
    # (F, k) -- common values from Pearson 1993 / Sims
    "coral": (0.0545, 0.062),
    "mitosis": (0.0367, 0.0649),
    "spots": (0.030, 0.062),
    "worms": (0.078, 0.061),
    "maze": (0.029, 0.057),
    "custom": None,
}
# pcg100 c7: added the second Model of Houdini Reaction-Diffusion Block End (Kenjiro Maginu)
RD_MODES = ("gray_scott", "turing", "maginu")
EDGES = ("wrap", "clamp")


def _lap9(X, a, edge):
    """
    Sims's 3x3 Laplacian: neighbors 0.2, corners 0.05, center -1 (more isotropic than five-point).

    First add the rows above and below (v); the four corners = v's left and right columns, the two vertical neighbors = v's middle
    column -- 8 additions become 5. Stencil operations are bandwidth-bound, so reading the whole image one fewer time is noticeably faster.
    """
    p = X.pad(a, 1, "wrap" if edge == "wrap" else "edge")
    v = p[:-2] + p[2:]
    return (0.2 * (v[:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:])
            + 0.05 * (v[:, :-2] + v[:, 2:]) - a)


def _gauss_hat(X, H, W, sigma):
    """Frequency response of a periodic Gaussian (rfft2 half-spectrum layout). Strictly commutes with np.roll."""
    fy = X.fftfreq(H)[:, None]
    fx = X.rfftfreq(W)[None, :]
    return X.exp(-2 * (math.pi * sigma) ** 2 * (fx * fx + fy * fy))


def _blur_fft(a, sigma):
    """Periodic Gaussian (frequency-domain multiply). numpy version, kept for other callers and tests."""
    H, W = a.shape
    X = AC.NUMPY
    return X.irfft2(X.rfft2(a) * _gauss_hat(X, H, W, sigma), (H, W))


def reaction_diffusion(img=None, mode="gray_scott", preset="coral",
                       feed=0.055, kill=0.062, du=1.0, dv=0.5, dt=1.0,
                       steps=1000, seed_layer="", spots=20, spot_radius=4.0,
                       feed_layer="", kill_layer="", edge="wrap",
                       scales="32 16 8 4", step_size=0.02, seed=0,
                       out_layer="rd", xres=256, yres=256, compute="auto",
                       maginu_alpha=1.0, maginu_beta=0.5, maginu_gamma=1.5,
                       scale_multiplier=1.0, boundary_layer="",
                       invert_boundary=False, boundary_threshold=0.0,
                       boundary_smoothing=0.0, invert_output=False,
                       normalize_model=False, use_clamp_min=False, clamp_min=0.0,
                       use_clamp_max=False, clamp_max=1.0):
    """
    Reaction-Diffusion / Turing Patterns.

    gray_scott: two substances U, V,
        ∂U/∂t = Du∇²U − UV² + F(1 − U)
        ∂V/∂t = Dv∇²V + UV² − (F + k)V
      initial state U = 1, V = 0, then at the seeds (Seed Layer > 0.5; if not given, Spots circles of radius
      Spot Radius are scattered) set V = 1, U = 0.5. Preset picks (F, k), custom uses Feed /
      Kill; if Feed / Kill Layer is given the values are taken per pixel (for "different textures in different regions").
      Explicit Euler; dt = 1 with Sims's 9-point Laplacian is stable (Du·dt <= 1).
      Output out_layer = V (the pattern); out_layer_u / _v are the state -- connect them back to continue.

    turing: McCabe 2010 multi-scale Turing patterns. Scales is a list of activator radii (inhibitor radius
      = 2x); each step each pixel picks the scale with the smallest "activator - inhibitor" difference (averaged over a 1-pixel
      neighborhood), moves step_size toward its sign, then renormalizes to [-1, 1]. Output is mapped to 0-1.
      State is in _g.

      Since pcg65 each step's FFTs dropped from 24 complex transforms to 1 + 3 x scale-count real transforms:
        · g's spectrum is computed only once per step, shared by all scales
        · Gaussians are linear: activator - inhibitor = one inverse transform (subtracted kernels), no need to do each and subtract;
          "activator > inhibitor" is just "difference > 0"
        · all real images, using rfft2 (half spectrum)
      Mathematically the same as before, rounding differs -- so it isn't pixel-identical to outputs before pcg64
      (the pattern looks the same, details differ).

    maginu (pcg100 c7, the Kenjiro Maginu model of Houdini Reaction-Diffusion Block End,
      equations per the docs):
        ∂A/∂t = Da∇²A + α(A − A³) − B
        ∂B/∂t = Db∇²B + β(A − γB)
      Da / Db use Du / Dv. Initial state A = ±0.05 random noise (Rand Seed), B = 0, at the seeds
      (Seed Layer / Spots) A = 1. State is in out_layer_a / _b, out_layer = A. The docs give no defaults for α β γ:
      we use 1.0 / 0.5 / 1.5 (αγ > 1, so A = 0 is unstable and noise separates into two phases A ≈ ±0.86;
      with Du less than Dv it forms spots / mazes); stable at dt = 1. Tried 0.6 / 1.0 / 1.2 (the classic
      Turing instability range): at dt = 1 B's reaction term is too fast and explicit Euler diverges, needing dt <= 0.5.

    Added in pcg100 c7 (Houdini Block End parameters; used by gray_scott / maginu, not read by turing):
      scale_multiplier  the whole reaction term ÷ S (docs: "changes the reaction rate relative to diffusion; larger = slower reaction =
                        larger pattern"). At S = 1 it is bit-identical to before (x1.0 is exact).
      boundary_layer    SDF layer: where SDF <= Threshold is the reaction region (Invert flips it);
                        with Smoothing > 0 this 0/1 region is Gaussian-blurred (σ pixels) into a weight w;
                        after each step state = rest state + w·(state - rest state) (rest state:
                        Gray-Scott U = 1, V = 0; Maginu A = B = 0) -- nothing grows outside, and it pulls back at the edge.
                        The docs only say "connect an SDF to grow the reaction into that shape"; the method is our own.
      output correction applies only to out_layer (the pattern), state layers are untouched: Normalize Model maps
                        each model's natural range to 0-1 (Gray-Scott's V is already in 0-1, unchanged;
                        Maginu's A is between the two stable roots ±1 -> (A + 1)/2), then Invert
                        (1 - x), then Clamp Min / Max. The order is our own choice.

    compute: auto / cpu / cuda (see accel). On GPU it's float64, differing from numpy's result
      on the order of 1e-12 (tests compare 1000 steps to 1e-9).

    Returns (image, report).
    """
    if mode not in RD_MODES:
        raise ValueError(f"Mode must be one of {RD_MODES}")
    if edge not in EDGES:
        raise ValueError(f"Edge must be one of {EDGES}")
    out, like = _base(img, xres, yres)
    W, H = out.xres, out.yres
    name = str(out_layer).strip() or "rd"
    n = int(steps)
    X, why = AC.pick(img, compute, H * W, 12)
    if mode == "turing":
        gname = name + "_g"
        if gname in out:
            g = getn(out, gname)[..., 0]
            cont = True
        else:
            k = np.arange(H * W).reshape(H, W)
            g = rnd(k, seed, 1) * 2 - 1
            cont = False
        sc = [float(x) for x in str(scales).replace(",", " ").split()]
        if not sc:
            raise ValueError("Scales needs at least one radius")
        amt = [float(step_size) * (0.5 + 0.5 * i / max(len(sc) - 1, 1))
               for i in range(len(sc))][::-1]       # large scales move a bit faster
        g = X.arr(g)
        # frequency-domain kernels of activator (σ = r/2) minus inhibitor (σ = r), one per scale, computed outside the loop
        kd = [_gauss_hat(X, H, W, r / 2) - _gauss_hat(X, H, W, r) for r in sc]
        k1 = _gauss_hat(X, H, W, 1.0)
        prog = Progress(n)
        for _ in range(n):
            prog.step()
            G = X.rfft2(g)
            best = bi = None
            for kdi, st in zip(kd, amt):
                d = X.irfft2(G * kdi, (H, W))              # activator - inhibitor
                # the change is averaged over a small neighborhood (that's what McCabe's original does). Without averaging
                # the smallest scale flips back and forth pixel by pixel where act ≈ inh, and the image is covered with one-pixel-wide
                # contour-like hairlines (the first demo version did exactly that)
                var = X.irfft2(X.rfft2(X.abs(d)) * k1, (H, W))
                inc = X.where(d > 0, st, -st)
                if best is None:
                    best, bi = var, inc
                else:
                    m = var < best
                    best = X.where(m, var, best)
                    bi = X.where(m, inc, bi)
            g = g + bi
            lo, hi = X.amin(g), X.amax(g)
            g = (g - lo) / X.maximum(hi - lo, 1e-12) * 2 - 1
        g = X.np(g)
        put(out, name, (g + 1) * 0.5, like)
        put(out, gname, g, like)
        return out, {"steps": n, "continued": cont, "compute": why}

    S = float(scale_multiplier)
    if not S > 0:
        raise ValueError("Scale Multiplier must be > 0")
    inv = 1.0 / S
    bw = None
    if str(boundary_layer).strip():
        sd = getn(out, boundary_layer)[..., 0]
        reg = (sd >= float(boundary_threshold)) if invert_boundary else \
            (sd <= float(boundary_threshold))
        bw = reg.astype(np.float64)
        if float(boundary_smoothing) > 0:
            from .filters import gaussian_kernel
            from .fx import convolve
            g = np.asarray(gaussian_kernel(float(boundary_smoothing)))
            bw = convolve(convolve(bw[..., None], g[None, :], "clamp"),
                          g[:, None], "clamp")[..., 0]

    def _correct(P, lo, hi):
        """Output Correction (only for out_layer)."""
        if normalize_model:
            P = (P - lo) / (hi - lo)
        if invert_output:
            P = 1.0 - P
        if use_clamp_min:
            P = np.maximum(P, float(clamp_min))
        if use_clamp_max:
            P = np.minimum(P, float(clamp_max))
        return P

    if mode == "maginu":
        an, bn = name + "_a", name + "_b"
        if an in out and bn in out:
            A = getn(out, an)[..., 0]
            B = getn(out, bn)[..., 0]
            cont = True
        else:
            k = np.arange(H * W).reshape(H, W)
            A = (rnd(k, seed, 3) * 2 - 1) * 0.05
            B = np.zeros((H, W))
            m = _rd_seed_mask(out, seed_layer, spots, spot_radius, edge, seed,
                              W, H)
            A = np.where(m, 1.0, A)
            cont = False
        Da, Db, h = float(du), float(dv), float(dt)
        if max(Da, Db) * h > 1.0:
            raise ValueError(f"Unstable: max(Du, Dv)·dt = {max(Da, Db) * h:g} > 1 "
                             "(explicit Euler with the 9-point Laplacian)")
        al, be, ga = float(maginu_alpha), float(maginu_beta), \
            float(maginu_gamma)
        A, B = X.arr(A), X.arr(B)
        wb = X.arr(bw) if bw is not None else None
        prog = Progress(n)
        for _ in range(n):
            prog.step()
            A2 = A + h * (Da * _lap9(X, A, edge)
                          + (al * (A - A * A * A) - B) * inv)
            B = B + h * (Db * _lap9(X, B, edge) + be * (A - ga * B) * inv)
            A = A2
            if wb is not None:
                A = A * wb
                B = B * wb
        A, B = X.np(A), X.np(B)
        put(out, name, _correct(A, -1.0, 1.0), like)
        put(out, an, A, like)
        put(out, bn, B, like)
        return out, {"steps": n, "continued": cont, "compute": why}

    if preset not in RD_PRESETS:
        raise ValueError(f"Preset must be one of {tuple(RD_PRESETS)}")
    F, K = RD_PRESETS[preset] or (float(feed), float(kill))
    Fm = getn(out, feed_layer)[..., 0] if str(feed_layer).strip() else F
    Km = getn(out, kill_layer)[..., 0] if str(kill_layer).strip() else K
    un, vn = name + "_u", name + "_v"
    if un in out and vn in out:
        U = getn(out, un)[..., 0]
        V = getn(out, vn)[..., 0]
        cont = True
    else:
        U = np.ones((H, W))
        V = np.zeros((H, W))
        m = _rd_seed_mask(out, seed_layer, spots, spot_radius, edge, seed,
                          W, H)
        U = np.where(m, 0.5, U)
        V = np.where(m, 1.0, V)
        cont = False
    Du, Dv, h = float(du), float(dv), float(dt)
    if max(Du, Dv) * h > 1.0:
        raise ValueError(f"Unstable: max(Du, Dv)·dt = {max(Du, Dv) * h:g} > 1 "
                         "(explicit Euler with the 9-point Laplacian)")
    U, V = X.arr(U), X.arr(V)
    Fm = X.arr(Fm) if isinstance(Fm, np.ndarray) else Fm
    Km = X.arr(Km) if isinstance(Km, np.ndarray) else Km
    FK = Fm + Km
    wb = X.arr(bw) if bw is not None else None
    prog = Progress(n)
    for _ in range(n):
        prog.step()
        uvv = U * V * V
        # inv = 1/Scale Multiplier; at S = 1, x1.0 is exact and the addition order matches the original too
        U = U + h * (Du * _lap9(X, U, edge) - uvv * inv + Fm * (1 - U) * inv)
        V = V + h * (Dv * _lap9(X, V, edge) + uvv * inv - FK * V * inv)
        if wb is not None:
            U = 1.0 + wb * (U - 1.0)
            V = V * wb
    U, V = X.np(U), X.np(V)
    put(out, name, _correct(V, 0.0, 1.0), like)
    put(out, un, U, like)
    put(out, vn, V, like)
    return out, {"steps": n, "continued": cont, "feed": F, "kill": K,
                 "compute": why}


def _rd_seed_mask(out, seed_layer, spots, spot_radius, edge, seed, W, H):
    """Initial seeds: Seed Layer > 0.5; if not given, scatter Spots circles of radius Spot Radius."""
    if str(seed_layer).strip():
        return getn(out, seed_layer)[..., 0] > 0.5
    J, I = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
    m = np.zeros((H, W), bool)
    k = np.arange(int(spots))
    for x0, y0 in zip(rnd(k, seed, 1) * W, rnd(k, seed, 2) * H):
        dx = np.abs(J - x0)
        dy = np.abs(I - y0)
        if edge == "wrap":
            dx = np.minimum(dx, W - dx)
            dy = np.minimum(dy, H - dy)
        m |= dx * dx + dy * dy <= float(spot_radius) ** 2
    return m


# ═══════════════════════════════════════════════════════════ Water waves
RIPPLE_EDGES = ("reflect", "wrap", "absorb")


def ripple(img=None, source_layer="", obstacle_layer="", speed=0.5,
           damping=0.0, steps=100, drive_frequency=0.0, drive_amplitude=1.0,
           edge="reflect", absorb_width=16, out_layer="ripple", xres=256,
           yres=256, compute="auto"):
    """
    Ripple Block: 2D wave equation h_tt = c²∇²h - damping·h_t, leapfrog scheme

        h⁺ = (2 − d)h − (1 − d)h⁻ + c²∇²h

    c = Speed (pixels / step). The five-point Laplacian's CFL condition is c <= 1/√2; beyond that it raises an error.
    Source Layer: used as the initial displacement on the first run (not added again when continuing); with Drive Frequency > 0
    it becomes a continuous drive instead: each step forces h = A·sin(2π f t) at the source (f is cycles per step).
    Pixels with Obstacle Layer > 0.5 are walls (h stays 0, waves reflect off walls).
    edge: reflect (image edge is a free edge), wrap, absorb (a sponge layer of Absorb Width pixels at the edge
    absorbs, approximating "open water").

    State: out_layer (h), out_layer_prev (h⁻), out_layer_t (steps taken).
    compute: auto / cpu / cuda (see accel; float64 on GPU, matching numpy to 1e-12).
    Returns (image, report: steps, energy, where it computed).
    """
    if edge not in RIPPLE_EDGES:
        raise ValueError(f"Edge must be one of {RIPPLE_EDGES}")
    c = float(speed)
    if c > 1 / math.sqrt(2) + 1e-12:
        raise ValueError(f"Speed = {c:g} exceeds the CFL limit 1/√2 ≈ 0.707 and would diverge")
    out, like = _base(img, xres, yres)
    W, H = out.xres, out.yres
    name = str(out_layer).strip() or "ripple"
    pn, tn = name + "_prev", name + "_t"
    src = getn(out, source_layer)[..., 0] if str(source_layer).strip() \
        else None
    if name in out and pn in out:
        h = getn(out, name)[..., 0]
        hp = getn(out, pn)[..., 0]
        t0 = int(round(float(getn(out, tn)[0, 0, 0]))) if tn in out else 0
        cont = True
    else:
        h = np.zeros((H, W)) if (src is None or drive_frequency > 0) \
            else src.copy()
        hp = h.copy()
        t0 = 0
        cont = False
    wall = getn(out, obstacle_layer)[..., 0] > 0.5 \
        if str(obstacle_layer).strip() else np.zeros((H, W), bool)
    d = float(damping)
    sponge = np.zeros((H, W))
    if edge == "absorb":
        wdt = max(int(absorb_width), 1)
        J, I = np.meshgrid(np.arange(W), np.arange(H))
        dist = np.minimum(np.minimum(J, W - 1 - J), np.minimum(I, H - 1 - I))
        sponge = np.clip(1 - dist / wdt, 0, 1) ** 2 * 0.3
    dd = d + sponge
    bnd = "periodic" if edge == "wrap" else "neumann"
    drive = float(drive_frequency) > 0 and src is not None
    X, why = AC.pick(img, compute, H * W, 8)
    h, hp = X.arr(h), X.arr(hp)
    a2 = X.arr(2 - dd)
    a1 = X.arr(1 - dd)
    has_wall = bool(wall.any())
    wall = X.mask(wall)
    smask = X.mask(src > 0.5) if drive else None
    prog = Progress(steps)
    for s in range(int(steps)):
        prog.step()
        hn = a2 * h - a1 * hp + c * c * SV.laplacian(h, bnd, X)
        if has_wall:
            hn = X.where(wall, 0.0, hn)
        if drive:
            hn = X.where(smask, float(drive_amplitude) * math.sin(
                2 * math.pi * float(drive_frequency) * (t0 + s + 1)), hn)
        hp, h = h, hn
    h, hp = X.np(h), X.np(hp)
    # discrete energy. What the leapfrog scheme conserves isn't "kinetic + potential energy" itself but, at staggered times,
    #   E = ‖hⁿ⁺¹ − hⁿ‖² + c²·⟨∇hⁿ⁺¹, ∇hⁿ⟩
    # (∇ forward difference, ∇² = -∇ᵀ∇). Without damping it is strictly unchanged step by step -- the first draft reported
    # ||Δh||² + c²||∇h||², which swung 14% over 150 steps; after the tests caught it, it was switched to this
    gx, gy = SV.grad_fwd(h, bnd)
    px_, py_ = SV.grad_fwd(hp, bnd)
    energy = float(((h - hp) ** 2).sum() + c * c * (gx * px_ + gy * py_)
                   .sum())
    put(out, name, h, like)
    put(out, pn, hp, like)
    put(out, tn, np.full((H, W), float(t0 + int(steps))), like)
    return out, {"steps": t0 + int(steps), "continued": cont,
                 "energy": energy, "compute": why}


# ═══════════════════════════════════════════════════════════ Fluid
FLOW_MODES = ("simulate", "project")


def project(vx, vy, edge="wrap", tol=1e-10, maxit=4000, X=None):
    """
    Helmholtz projection: v ← v - ∇p, ∇²p = div v. div uses backward differences, ∇ forward differences,
    and div∘∇ is exactly the five-point Laplacian, so the div after projection (by the same backward difference) is 0 in the discrete
    sense (wrap is solved exactly by FFT; walls by mirror extension + FFT exact solve; both to 1e-12).
    tol / maxit are no longer used (both boundaries are direct solves); kept so callers don't need to change.
    X: compute engine, numpy by default.
    """
    X = X or AC.NUMPY
    bnd = "periodic" if edge == "wrap" else "neumann"
    if bnd == "neumann":
        # how to read the staggered grid: vx[i, j] is the flux through the face between column j and column j+1. The last
        # column's vx and the last row's vy are fluxes **through the wall** and must be 0 -- if not zeroed,
        # total divergence = what flows out the right / top ≠ 0, the pure neumann Poisson equation has no solution, and after projection
        # 5e-3 of divergence remains (as in the first draft)
        vx = vx.clone() if X.is_torch else vx.copy()
        vy = vy.clone() if X.is_torch else vy.copy()
        vx[:, -1] = 0.0
        vy[-1, :] = 0.0
    dv = SV.divergence(vx, vy, bnd, X)
    if bnd == "periodic":
        p = SV._solve_periodic(dv, X)
    else:
        # walls: neumann Poisson equation, mirror extension + FFT direct solve (see solve._solve_neumann).
        # it used to be conjugate gradient, which on large images hit the iteration limit without converging
        p = SV._solve_neumann(dv, X)
    gx, gy = SV.grad_fwd(p, bnd, X)
    return vx - gx, vy - gy


def _advect(q, vx, vy, dt, edge, X=None):
    """
    Semi-Lagrangian: q_new(x) = q(x - v·dt), bilinear. q is (H,W,C).
    Sampling goes through filters.sample's op table (X.ops: numpy float64 or torch float64).
    """
    from .filters import sample
    X = X or AC.NUMPY
    H, W = vx.shape[0], vx.shape[1]
    ops = X.ops
    J = X.row(X.arr(np.arange(W, dtype=np.float64)))
    I = X.col(X.arr(np.arange(H, dtype=np.float64)))
    gx = J - vx * dt
    gy = I - vy * dt
    return sample(q, (gx + 0.5) / W, (gy + 0.5) / H,
                  "wrap" if edge == "wrap" else "clamp", ops)


def flow(img, velocity_layer="vel", density_layers="density", mode="simulate",
         steps=10, dt=1.0, force_layer="", force_scale=1.0,
         dissipation=0.0, edge="wrap", tolerance=1e-8, compute="auto"):
    """
    Flow Block / Flow Project Non-Divergent Multigrid. The velocity layer has 2 channels, in units of
    pixels / step (v up, consistent with COP).

      project   only one Helmholtz projection, outputs divergence-free velocity (twists any vector field
                into an incompressible flow field)
      simulate  Stam 1999 stable fluids, each step: add force (Force Layer x Force
                Scale) -> advect velocity -> project -> advect Density Layers (space-separated,
                any channel count) -> multiply by (1 - Dissipation)

    edge: wrap uses exact FFT projection; clamp is walls, mirror extension + exact FFT projection. Both are
    direct solves, so Tolerance is no longer used (before pcg64 walls used CG iteration); the parameter is kept only so
    saved workflows don't get misaligned.
    compute: auto / cpu / cuda (see accel). float64 on GPU, matching numpy to 1e-12.
    Velocity and density layers are written back under their original names -- connect them back for the next segment. Returns (image, report: max divergence, where it computed).
    """
    if img is None:
        return CopImage(), {}
    if mode not in FLOW_MODES:
        raise ValueError(f"Mode must be one of {FLOW_MODES}")
    if edge not in EDGES:
        raise ValueError(f"Edge must be one of {EDGES}")
    v = getn(img, velocity_layer)
    if v.shape[2] < 2:
        raise ValueError("The velocity layer needs 2 channels")
    out = img.copy()
    dens = [n for n in str(density_layers).split() if n]
    H, W = img.yres, img.xres
    X, why = AC.pick(img, compute, H * W, 16 + 4 * len(dens))
    vx, vy = X.arr(v[..., 0]), X.arr(v[..., 1])
    if mode == "project":
        vx, vy = project(vx, vy, edge, float(tolerance), X=X)
    else:
        D = {n: X.arr(getn(img, n)) for n in dens}
        fl = str(force_layer).strip()
        Fv = X.arr(getn(img, fl)[..., :2] * float(force_scale)) if fl else None
        prog = Progress(steps)
        for _ in range(int(steps)):
            prog.step()
            if Fv is not None:
                vx = vx + Fv[..., 0] * float(dt)
                vy = vy + Fv[..., 1] * float(dt)
            adv = _advect(X.stack([vx, vy], -1), vx, vy, float(dt), edge, X)
            vx, vy = adv[..., 0], adv[..., 1]
            vx, vy = project(vx, vy, edge, float(tolerance), X=X)
            for n in dens:
                D[n] = _advect(D[n], vx, vy, float(dt), edge, X) * (
                    1.0 - float(dissipation))
        for n in dens:
            put(out, n, X.np(D[n]), img)
    bnd = "periodic" if edge == "wrap" else "neumann"
    div = SV.divergence(vx, vy, bnd, X)
    mdiv = X.scalar(X.amax(X.abs(div)))
    put(out, velocity_layer, np.stack([X.np(vx), X.np(vy)], -1), img)
    return out, {"max_divergence": mdiv, "compute": why}


# ═══════════════════════════════════════════════════════════ Ocean
G = 9.81


OCEAN_SPECTRA = ("phillips", "tma")
OCEAN_DISTRIBUTIONS = ("none", "uniform", "gaussian", "log_normal")


def _dispersion(k, depth, g):
    """ω(k): deep water √(gk); finite depth √(gk·tanh(kh)) (depth <= 0 = deep water, bit-identical to the old version)."""
    if depth > 0:
        return np.sqrt(g * k * np.tanh(k * depth))
    return np.sqrt(g * k)


def _lgamma(x):
    return np.frompyfunc(math.lgamma, 1, 1)(x).astype(np.float64)


def tma_spectrum(w, wind_speed, fetch_m, depth, g):
    """
    TMA spectrum S(ω) (m²·s): JONSWAP x Kitaigorodskii depth attenuation (as written by Horvath 2015):
      α = 0.076·(U²/(F g))^0.22,ωp = 22·(g²/(U F))^(1/3),γ = 3.3,
      σ = 0.07(ω ≤ ωp)/ 0.09,r = exp(−(ω−ωp)²/(2σ²ωp²))
      S_J = α g²/ω⁵ · exp(−5/4 (ωp/ω)⁴) · γ^r
      Φ(ωh = ω√(h/g)) = ½ωh² (ωh <= 1) / 1 - ½(2 - ωh)² (1 < ωh < 2) / 1; deep water Φ = 1
    Returns (S, ωp).
    """
    U, F = float(wind_speed), float(fetch_m)
    a = 0.076 * (U * U / (F * g)) ** 0.22
    wp = 22.0 * (g * g / (U * F)) ** (1.0 / 3.0)
    ws = np.where(w > 0, w, 1.0)
    sg = np.where(ws <= wp, 0.07, 0.09)
    r = np.exp(-((ws - wp) ** 2) / (2 * sg * sg * wp * wp))
    S = a * g * g / ws ** 5 * np.exp(-1.25 * (wp / ws) ** 4) * 3.3 ** r
    if depth > 0:
        wh = ws * math.sqrt(depth / g)
        phi = np.where(wh <= 1, 0.5 * wh * wh,
                       np.where(wh < 2, 1 - 0.5 * (2 - wh) ** 2, 1.0))
        S = S * phi
    return np.where(w > 0, S, 0.0), wp


def hasselmann_spread(theta, w, wp, wind_speed, swell, g):
    """
    Directional spreading D(θ) (integrates to 1 over θ ∈ [-π, π)): Hasselmann's cos^{2s}(θ/2),
      s = 6.97(ω/ωp)^4.06(ω ≤ ωp)/ 9.77(ω/ωp)^(−2.33 − 1.45(U ωp/g − 1.17))
    plus Swell (Horvath 2015): s += 16·tanh(ωp/ω)·ξ·|ξ| -- Horvath's original is ξ² (only ever more concentrated);
    the docs say "negative values reduce directionality and add waves against the wind", so it adds or subtracts by the sign of ξ, then clamps to >= 0 (our own choice).
      Q(s) = 2^{2s−1}/π · Γ(s+1)² / Γ(2s+1)
    """
    ws = np.where(w > 0, w, 1.0)
    rr = ws / wp
    s = np.where(rr <= 1, 6.97 * rr ** 4.06,
                 9.77 * rr ** (-2.33 - 1.45 * (wind_speed * wp / g - 1.17)))
    xi = float(swell)
    s = np.maximum(s + 16.0 * np.tanh(wp / ws) * xi * abs(xi), 0.0)
    lq = (2 * s - 1) * math.log(2) - math.log(math.pi) + 2 * _lgamma(s + 1) \
        - _lgamma(2 * s + 1)
    return np.exp(lq) * np.abs(np.cos(theta / 2)) ** (2 * s)


def ocean_spectrum(N, M, size, wind_speed, wind_dir, amplitude, align,
                   small_cut, seed, depth=0.0, gravity=G, spectrum="phillips",
                   swell=0.0, fetch_km=100.0, directional_movement=0.0,
                   distribution="gaussian"):
    """
    Initial complex amplitudes h0(k) of the Phillips spectrum (Tessendorf 2001):

        P(k) = A · exp(−1/(kL)²)/k⁴ · |k̂·ŵ|^align · exp(−k²l²),L = V²/g

    align = 2 is the original; larger makes waves follow the wind more. small_cut l suppresses waves shorter than it (meters).
    Returns (h0, kx, ky, ω). kx along u (+x), ky along v.

    Added in pcg100 c7 (Houdini Ocean Spectrum; defaults = old behaviour, bit-identical):
      depth     > 0 gives finite-depth dispersion ω = √(gk·tanh(kh)); 0 = deep water (old)
      gravity   g (hard-coded 9.81 in the old version)
      spectrum  tma: TMA spectrum (tma_spectrum) x Hasselmann directional spreading (hasselmann_spread),
                converted to the wavenumber spectrum P(k) = S(ω)·D(θ)·(dω/dk)/k, θ = angle between the wave's **propagation direction** and the wind;
                Amplitude / Align aren't read (those are Phillips constants), Small Cut still multiplies by
                exp(-k²l²). Normalization: makes height variance = ∫S dω (see below)
      directional_movement (Phillips) waves propagating against the wind are multiplied by (1 - dm). The h0(q) term evolves in time as
                e^{i(q·x + ωt)}, propagating toward **-q**, so "against the wind" is q̂·ŵ > 0
      distribution  amplitude random distribution (phases are all uniform random): gaussian = old (complex Gaussian, Rayleigh amplitude);
                none = amplitude always 1; uniform = U(0, √3); log_normal = exp(z - 1) (z standard normal).
                All four have E[r²] = 1, so the mean wave height is the same, only the distribution differs (log_normal's σ = 1
                is our own choice).
    Variance convention: height h(x) = Σ_k h̃_k e^{ikx}, time-averaged variance = 2·Σ E|h0|². Phillips keeps the old
    E|h0|² = P·Δk; TMA uses E|h0|² = P·Δk / 2, so variance = Σ P Δk ≈ ∫S(ω)dω (checked in tests).
    """
    if spectrum not in OCEAN_SPECTRA:
        raise ValueError(f"Spectrum Type must be one of {OCEAN_SPECTRA}")
    if distribution not in OCEAN_DISTRIBUTIONS:
        raise ValueError(f"Distribution must be one of {OCEAN_DISTRIBUTIONS}")
    g = float(gravity)
    if not g > 0:
        raise ValueError("Gravity must be > 0")
    dpt = float(depth)
    fx = np.fft.fftfreq(M) * M
    fy = np.fft.fftfreq(N) * N
    KX, KY = np.meshgrid(2 * math.pi * fx / float(size),
                         2 * math.pi * fy / float(size) * M / N)
    k = np.hypot(KX, KY)
    Lw = float(wind_speed) ** 2 / g
    th = math.radians(float(wind_dir))
    wx, wy = math.cos(th), math.sin(th)
    ks = np.where(k > 0, k, 1.0)
    dot = (KX * wx + KY * wy) / ks
    if spectrum == "phillips":
        P = float(amplitude) * np.exp(-1.0 / (ks * Lw) ** 2) / ks ** 4 \
            * np.abs(dot) ** float(align) * np.exp(-(ks * float(small_cut)) ** 2)
        dm = float(directional_movement)
        if dm != 0.0:
            P = np.where(dot > 0, P * (1.0 - dm), P)
    else:
        if not float(fetch_km) > 0:
            raise ValueError("Fetch must be > 0")
        wk = _dispersion(ks, dpt, g)
        S, wp = tma_spectrum(wk, wind_speed, float(fetch_km) * 1000.0, dpt, g)
        # propagation direction = -q̂, angle against the wind direction
        # no need to fold back into [-π, π): D only depends on |cos(θ/2)|, unchanged by a 2π difference
        thw = np.arctan2(-KY, -KX) - th
        D = hasselmann_spread(thw, wk, wp, float(wind_speed), swell, g)
        if dpt > 0:
            th_ = np.tanh(ks * dpt)
            dwdk = g * (th_ + ks * dpt * (1 - th_ * th_)) / (2 * wk)
        else:
            dwdk = 0.5 * np.sqrt(g / ks)
        # divide by 2 again: E|h0|² = P·Δk/2 (see the variance convention in the docstring)
        P = S * D * dwdk / ks * np.exp(-(ks * float(small_cut)) ** 2) * 0.5
    # discrete spectrum = continuous spectrum x Δk_x·Δk_y: so with the same parameters, changing resolution / Size keeps wave height unchanged.
    # then σ² = A·π·L² (align = 2, no short-wave cut), and A = 8.8e-4 gives significant wave height
    # Hs = 4σ ≈ 0.21·V²/g -- the Pierson-Moskowitz value for a fully developed sea
    dk2 = (2 * math.pi / float(size)) * (2 * math.pi / (float(size) * N / M))
    P = np.where(k > 0, P, 0.0) * dk2
    # the Nyquist row / column: -k is itself, but the sign of kx is asymmetric, so the inverse transforms of displacement and slope
    # would bring out an imaginary part (first draft's residual 0.02 m). Standard practice: set it to zero
    if N % 2 == 0:
        P[N // 2, :] = 0.0
    if M % 2 == 0:
        P[:, M // 2] = 0.0
    rng = np.random.default_rng(int(seed))
    if distribution == "gaussian":
        xi = rng.standard_normal((N, M)) + 1j * rng.standard_normal((N, M))
        h0 = xi * np.sqrt(P / 2.0)
    else:
        ph = np.exp(1j * rng.uniform(0.0, 2 * math.pi, (N, M)))
        if distribution == "none":
            r = np.ones((N, M))
        elif distribution == "uniform":
            r = rng.uniform(0.0, math.sqrt(3.0), (N, M))
        else:
            r = np.exp(rng.standard_normal((N, M)) - 1.0)
        h0 = r * ph * np.sqrt(P)
    w = _dispersion(k, dpt, g)
    return h0, KX, KY, w


def ocean_fields(h0, KX, KY, w, t, chop):
    """
    At time t: h(k,t) = h0(k)e^{iωt} + conj(h0(-k))e^{-iωt} (by construction h(-k) =
    conj(h(k)), so the inverse transform is real); horizontal displacement D = -i·k̂·h·chop; gradient = i·k·h.
    ifft2 x N·M keeps the same scale as "summing the modes directly" (no division by point count).
    Returns a dict: height, dx, dy (along u, v, meters), sx, sy (slopes), jacobian,
    and the residual imag beyond the real part (should be 0).
    """
    N, M = h0.shape
    # h0(-k): negating the indices is a flip followed by a one-cell shift
    hm = np.conj(np.roll(np.flip(h0, (0, 1)), 1, (0, 1)))
    e = np.exp(1j * w * float(t))
    hk = h0 * e + hm * np.conj(e)
    k = np.hypot(KX, KY)
    ks = np.where(k > 0, k, 1.0)
    sc = N * M

    def inv(X):
        return np.fft.ifft2(X) * sc
    Hc = inv(hk)
    Dx = inv(-1j * KX / ks * hk) * float(chop)
    Dy = inv(-1j * KY / ks * hk) * float(chop)
    Sx = inv(1j * KX * hk)
    Sy = inv(1j * KY * hk)
    # Jacobian of the displacement (in meters): J = (1 + ∂Dx/∂x)(1 + ∂Dy/∂y) - ∂Dx/∂y·∂Dy/∂x
    dxx = inv(-1j * KX / ks * hk * 1j * KX).real * float(chop)
    dyy = inv(-1j * KY / ks * hk * 1j * KY).real * float(chop)
    dxy = inv(-1j * KX / ks * hk * 1j * KY).real * float(chop)
    J = (1 + dxx) * (1 + dyy) - dxy * dxy
    imag = max(float(np.abs(Hc.imag).max()), float(np.abs(Dx.imag).max()))
    return {"height": Hc.real, "dx": Dx.real, "dy": Dy.real, "sx": Sx.real,
            "sy": Sy.real, "jacobian": J, "imag": imag}


def ocean(img=None, size=100.0, wind_speed=12.0, wind_direction=0.0,
          amplitude=8.8e-4, align=2.0, small_cut=0.1, time=0.0,
          choppiness=1.0, foam_threshold=0.3, seed=0, out_layer="ocean",
          xres=256, yres=256, depth=0.0, gravity=G, spectrum="phillips",
          swell=0.0, fetch_km=100.0, directional_movement=0.0,
          distribution="gaussian", loop_period=0.0):
    """
    Ocean Spectrum + Ocean Evaluate (Tessendorf's FFT ocean surface). Size is how many meters the whole image
    covers (width; height by aspect ratio), deep-water dispersion ω = √(gk), Time in seconds. Outputs (meters):

      out_layer          height
      out_layer_disp     3-channel displacement (du, height, dv) -- horizontal displacement (choppy) along the image's u, v
                         and vertical displacement, for pushing a mesh
      out_layer_N        normal, tangent space (u, v, up), same convention as other COP normals
      out_layer_foam     foam: where J < 1 - Foam Threshold (crests being compressed),
                         mapped linearly to 0-1

    Naturally seamless tiling (FFT periodicity). Same seed with changing Time gives animation; changing Amplitude
    only scales everything (height ∝ √A). With the default A = 8.8e-4 the significant wave height ≈ 0.21·V²/g
    (Size should be an order of magnitude larger than V²/g, otherwise long waves are cut off by the image extent and waves come out low). Returns (image, report: max wave height, imaginary residual).
    """
    out, like = _base(img, xres, yres)
    W, H = out.xres, out.yres
    h0, KX, KY, w = ocean_spectrum(H, W, size, wind_speed, wind_direction,
                                   amplitude, align, small_cut, seed, depth,
                                   gravity, spectrum, swell, fetch_km,
                                   directional_movement, distribution)
    T = float(loop_period)
    if T > 0:
        # Loop Period (pcg100 c7): ω quantized to integer multiples of 2π/T (rounded down, Tessendorf's
        # approach) -> every mode returns to its original phase after T seconds, so the animation loops seamlessly
        w0 = 2 * math.pi / T
        w = np.floor(w / w0) * w0
    f = ocean_fields(h0, KX, KY, w, time, choppiness)
    name = str(out_layer).strip() or "ocean"
    n = np.stack([-f["sx"], -f["sy"], np.ones_like(f["sx"])], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    foam = np.clip((1 - float(foam_threshold) - f["jacobian"])
                   / max(float(foam_threshold), 1e-6), 0, 1)
    put(out, name, f["height"], like)
    put(out, name + "_disp", np.stack([f["dx"], f["height"], f["dy"]], -1),
        like)
    put(out, name + "_N", n, like)
    put(out, name + "_foam", foam, like)
    return out, {"max_height": float(np.abs(f["height"]).max()),
                 "imag_residual": f["imag"]}
