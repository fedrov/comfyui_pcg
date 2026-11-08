"""
Compute engine for heavy nodes: numpy float64, or torch **float64** on some device (usually CUDA).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Why this layer exists -- "where the image lives" and "where it's computed" are two different things
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
backend.py manages **where layers live** (numpy / torch:cpu / torch:cuda), and operators follow the image.
That's right for "one-shot" per-pixel operations: moving the data once costs about as much as computing once.

But iterative nodes like reaction-diffusion, TV denoise, ripples and fluids pass the same image through hundreds or thousands
of times in one call. On an RTX 4090 a 1024² Reaction Diffusion with the default 1000 steps takes 70 s -- while the image
itself is only 8 MB, and moving it to the GPU and back takes milliseconds. Here "the image is in numpy so compute in numpy"
is a big loss. So these nodes get an extra Compute switch:

    auto   image already on torch -> compute on that device;
           otherwise CUDA available, pixel count >= backend.AUTO_PIXELS and it fits the VRAM budget -> move to
           CUDA, compute, then move back to the original backend; otherwise numpy
    cpu    always numpy (yield to the diffusion model when VRAM is tight)
    cuda   use it if available; otherwise fall back to numpy and say so in the report

**Output always goes back to the input's original backend** -- downstream sees the image living in numpy as before, rather than
the whole chain's backend changing because one node in the middle took a trip to the GPU.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Why float64 on the GPU too
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
backend.py's noise uses float32, on the grounds that fp64 on consumer GPUs is only 1/64 of fp32. That applies to
**compute-bound** code. The nodes here are all stencil operations (5-point / 9-point Laplacian, differences, FFT),
each pixel reading/writing a dozen-odd bytes for one or two multiply-adds -- the bottleneck is **VRAM bandwidth**; fp64 just moves twice
the bytes, it isn't 64x slower. In return:

    same code, same inputs, numpy and CUDA results differ at the 1e-12 level

i.e. "the image is the same with or without the GPU". 1000 steps of reaction-diffusion drift gradually in float32, and the resulting
spot positions differ from the numpy version, which users would take for a bug. Tests compare torch:cpu float64 against
numpy pixel by pixel, threshold 1e-9.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Same as backend.py: an explicit operator table
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
+ − × ÷, comparisons and slicing (positive step) on arrays are the same on both sides and are written directly. Everything else goes through Engine
methods -- especially these **silently different** ones:

    a[::-1]                    torch doesn't support negative-step slicing -> X.flip
    np.maximum(a, 0.0)         torch.maximum doesn't take scalars -> X.maximum
    np.pad(a, 1, "edge")       F.pad only accepts NCHW and calls it replicate -> X.pad
    np.fft.irfft2(A, s)        torch's parameter is also called s, but fftfreq needs dtype/device

New iterative code may only use what's in this table; tests compare the numpy / torch paths pixel by pixel, so anything missed
errors out on the spot or fails to match.
"""
from __future__ import annotations

import math

import numpy as np

from . import backend as bk

COMPUTES = ("auto", "cpu", "cuda")
# For tests / debugging: run the torch path on the CPU (same code as cuda) to verify both sides agree
_INTERNAL = ("torch_cpu",)


class _TorchOps64(bk.TorchBackend):
    """float64 version of backend.TorchBackend: for functions like filters.sample that go through the operator table."""

    def __init__(self, device="cpu"):
        super().__init__(device)
        self.fdtype = self.t.float64
        self.name = f"torch:{self.device.type}:f64"

    def to_numpy(self, a):
        if isinstance(a, self.t.Tensor):
            return a.detach().to("cpu", self.t.float64).numpy()
        return np.asarray(a, np.float64)


class Engine:
    """
    The array namespace for one computation. X.arr / X.np in and out; in between only the methods and operators below are used.

    ops: the float64 **operator table** on the same device (backend-style), for functions like filters.sample and
    noise.simplex that are already written against the operator table.
    """

    def __init__(self, device=None):
        self.is_torch = device is not None
        if self.is_torch:
            t = bk.torch_module()
            self.t = t
            self.m = t
            self.device = t.device(device)
            self.dt = t.float64
            self.ops = _TorchOps64(device)
            self.name = f"torch:{self.device.type}"
        else:
            self.t = None
            self.m = np
            self.device = "cpu"
            self.dt = np.float64
            self.ops = bk.EXACT
            self.name = "numpy"

    # ── in / out ───────────────────────────────────────────────────────
    def arr(self, a):
        """numpy / scalar / tensor -> this engine's float64 array."""
        if self.is_torch:
            t = self.t
            if isinstance(a, t.Tensor):
                return a.to(device=self.device, dtype=self.dt)
            n = np.array(a, np.float64)          # make a copy: torch warns on read-only arrays
            return t.as_tensor(n, device=self.device)
        if bk.torch_module() is not None and isinstance(
                a, bk.torch_module().Tensor):
            return a.detach().to("cpu", bk.torch_module().float64).numpy()
        return np.asarray(a, np.float64)

    def mask(self, a):
        """bool array -> this engine's bool array."""
        if self.is_torch:
            n = np.array(a, bool)
            return self.t.as_tensor(n, device=self.device)
        return np.asarray(a, bool)

    def np(self, a):
        """-> numpy float64."""
        if self.is_torch and isinstance(a, self.t.Tensor):
            return a.detach().to("cpu", self.t.float64).numpy()
        return np.asarray(a, np.float64)

    def scalar(self, a):
        """0-d array -> Python float (syncs once on the GPU; keep it out of hot loops)."""
        return float(a.item()) if self.is_torch else float(a)

    # ── construction ───────────────────────────────────────────────────
    def zeros(self, shape):
        if self.is_torch:
            return self.t.zeros(tuple(shape), dtype=self.dt, device=self.device)
        return np.zeros(shape)

    def full(self, shape, v):
        if self.is_torch:
            return self.t.full(tuple(shape), float(v), dtype=self.dt,
                               device=self.device)
        return np.full(shape, float(v))

    def zeros_like(self, a):
        return self.t.zeros_like(a) if self.is_torch else np.zeros_like(a)

    def empty(self, shape):
        if self.is_torch:
            return self.t.empty(tuple(shape), dtype=self.dt, device=self.device)
        return np.empty(shape)

    # ── element-wise ───────────────────────────────────────────────────
    def abs(self, a):
        return self.m.abs(a)

    def sqrt(self, a):
        return self.m.sqrt(a)

    def exp(self, a):
        return self.m.exp(a)

    def hypot(self, a, b):
        return self.m.hypot(a, b)

    def floor(self, a):
        return self.m.floor(a)

    def sin(self, a):
        return self.m.sin(a)

    def arctan2(self, a, b):
        # different names: numpy calls it arctan2, torch calls it atan2
        return self.t.atan2(a, b) if self.is_torch else np.arctan2(a, b)

    def iclip(self, a, lo, hi):
        """Clamp an integer array to [lo, hi] (torch.clamp with float bounds promotes ints to float)."""
        if self.is_torch:
            return self.t.clamp(a, int(lo), int(hi))
        return np.clip(a, int(lo), int(hi))

    def _s(self, v):
        """scalar -> 0-d tensor (torch.where / maximum don't take Python scalars in older versions)."""
        if self.is_torch and not isinstance(v, self.t.Tensor):
            return self.t.tensor(float(v), dtype=self.dt, device=self.device)
        return v

    def where(self, c, a, b):
        if self.is_torch:
            return self.t.where(c, self._s(a), self._s(b))
        return np.where(c, a, b)

    def maximum(self, a, b):
        if self.is_torch:
            return self.t.maximum(self._s(a), self._s(b))
        return np.maximum(a, b)

    def minimum(self, a, b):
        if self.is_torch:
            return self.t.minimum(self._s(a), self._s(b))
        return np.minimum(a, b)

    def clip(self, a, lo, hi):
        if self.is_torch:
            return self.t.clamp(a, float(lo), float(hi))
        return np.clip(a, lo, hi)

    # ── reductions (return 0-d arrays, no sync) ────────────────────────
    def amin(self, a):
        return a.min()

    def amax(self, a):
        return a.max()

    def sum(self, a):
        return a.sum()

    # ── shape ──────────────────────────────────────────────────────────
    def flip(self, a, axis):
        if self.is_torch:
            ax = (axis,) if isinstance(axis, int) else tuple(axis)
            return self.t.flip(a, ax)
        return np.flip(a, axis)

    def roll(self, a, shift, axis):
        if self.is_torch:
            return self.t.roll(a, shift, axis)
        return np.roll(a, shift, axis)

    def stack(self, xs, axis=0):
        return self.t.stack(list(xs), axis) if self.is_torch \
            else np.stack(xs, axis)

    def pad(self, a, r, mode):
        """
        Pad the first two dimensions of a 2D (H,W) or 3D (H,W,C) array by r rings each. mode: edge / wrap / zero.
        The torch side builds its own indices instead of F.pad (which only accepts NCHW, so 3D would need two transposes).
        """
        if r <= 0:
            return a
        if mode not in ("edge", "wrap", "zero"):
            raise ValueError(f"pad mode must be edge / wrap / zero, got {mode}")
        if not self.is_torch:
            w = ((r, r), (r, r)) + ((0, 0),) * (a.ndim - 2)
            return np.pad(a, w, mode="constant" if mode == "zero" else mode)
        t = self.t
        if mode == "zero":
            sh = list(a.shape)
            sh[0] += 2 * r
            sh[1] += 2 * r
            out = t.zeros(sh, dtype=a.dtype, device=a.device)
            out[r:-r, r:-r] = a
            return out
        H, W = a.shape[0], a.shape[1]
        iy = t.arange(-r, H + r, device=a.device)
        ix = t.arange(-r, W + r, device=a.device)
        if mode == "wrap":
            iy, ix = iy % H, ix % W
        else:
            iy, ix = iy.clamp(0, H - 1), ix.clamp(0, W - 1)
        return a.index_select(0, iy).index_select(1, ix)

    # ── FFT (real input; 2D, first two dimensions) ─────────────────────
    def rfft2(self, a):
        if self.is_torch:
            return self.t.fft.rfft2(a, dim=(0, 1))
        return np.fft.rfft2(a, axes=(0, 1))

    def irfft2(self, A, shape):
        s = (int(shape[0]), int(shape[1]))
        if self.is_torch:
            return self.t.fft.irfft2(A, s=s, dim=(0, 1))
        return np.fft.irfft2(A, s=s, axes=(0, 1))

    def fftfreq(self, n):
        if self.is_torch:
            return self.t.fft.fftfreq(int(n), dtype=self.dt,
                                      device=self.device)
        return np.fft.fftfreq(int(n))

    def rfftfreq(self, n):
        if self.is_torch:
            return self.t.fft.rfftfreq(int(n), dtype=self.dt,
                                       device=self.device)
        return np.fft.rfftfreq(int(n))

    def cos(self, a):
        return self.m.cos(a)

    def col(self, v):
        """1D -> (n,1)."""
        return v[:, None]

    def row(self, v):
        return v[None, :]

    def __repr__(self):
        return f"Engine({self.name})"


NUMPY = Engine()
_ENGINES = {}


def _torch_engine(dev):
    if bk.torch_module() is None:
        return None
    e = _ENGINES.get(dev)
    if e is None:
        try:
            e = Engine(dev)
        except Exception:
            return None
        _ENGINES[dev] = e
    return e


def pick(img=None, compute="auto", pixels=0, arrays=8):
    """
    Pick an engine by the Compute switch, the input image's backend and the pixel count. Returns (Engine, description).

    arrays: roughly how many (H,W) float64 arrays are alive at once in this step -- only used to estimate VRAM. Above
    backend.VRAM_BUDGET_MB it stays off the GPU (ComfyUI users already run diffusion models right at the VRAM limit).
    """
    c = str(compute or "auto").lower()
    if c not in COMPUTES + _INTERNAL:
        raise ValueError(f"Compute must be one of {COMPUTES}")
    if c == "cpu":
        return NUMPY, "numpy(Compute = cpu)"
    if c == "torch_cpu":
        e = _torch_engine("cpu")
        return (e, "torch:cpu (for tests)") if e else (NUMPY, "numpy (no torch)")
    mb = int(pixels) * max(1, int(arrays)) * 8 / 1e6
    if c == "cuda":
        if not bk.cuda_available():
            return NUMPY, "numpy (Compute = cuda, but no CUDA available)"
        e = _torch_engine("cuda")
        return (e, "torch:cuda") if e else (NUMPY, "numpy (CUDA initialization failed)")
    # auto
    xp = img.backend if img is not None and len(img) else None
    if xp is not None and getattr(xp, "is_torch", False):
        e = _torch_engine(str(xp.device))
        if e is not None:
            return e, f"{e.name} (follows input image)"
    if not bk.cuda_available():
        return NUMPY, "numpy (no CUDA)"
    if int(pixels) < bk.AUTO_PIXELS:
        return NUMPY, f"numpy (fewer than {bk.AUTO_PIXELS} pixels, GPU fixed overhead not worth it)"
    if mb > bk.VRAM_BUDGET_MB:
        return NUMPY, (f"numpy (estimated {mb:.0f} MB VRAM needed, exceeds "
                       f"VRAM_BUDGET_MB = {bk.VRAM_BUDGET_MB})")
    e = _torch_engine("cuda")
    return (e, "torch:cuda (auto)") if e else (NUMPY, "numpy (CUDA initialization failed)")


def pick_backend(img, compute="auto", arrays=16):
    """
    For old nodes **already written against the backend operator table** (thermal erosion, hydraulic erosion): decide whether to
    move the whole image to CUDA for computation. Returns (working image, device name for the return trip or None, description).
    Return trip None = no need to move back (it's already there). These two nodes are still float32 on the GPU
    (their GPU path has always been that way, tested and documented); this only changes "when to go to the GPU".
    """
    c = str(compute or "auto").lower()
    if c not in COMPUTES + _INTERNAL:
        raise ValueError(f"Compute must be one of {COMPUTES}")
    xp = img.backend
    home = "exact" if xp is bk.EXACT else "numpy"
    on_torch = getattr(xp, "is_torch", False)
    if c == "cpu":
        if on_torch:
            return img.to_device("numpy"), str(xp.device.type), "numpy(Compute = cpu)"
        return img, None, "numpy(Compute = cpu)"
    if c == "torch_cpu":
        if bk.torch_module() is None:
            return img, None, "numpy (no torch)"
        return img.to_device("cpu"), (None if on_torch else home), "torch:cpu (for tests)"
    if on_torch:
        return img, None, f"{xp.name} (follows input image)"
    px = img.xres * img.yres
    if not bk.cuda_available():
        return img, None, "numpy (no CUDA)"
    if c == "auto":
        if px < bk.AUTO_PIXELS:
            return img, None, "numpy (image too small, GPU not worth it)"
        mb = px * max(1, int(arrays)) * 4 / 1e6
        if mb > bk.VRAM_BUDGET_MB:
            return img, None, f"numpy (estimated {mb:.0f} MB VRAM needed, over budget)"
    return img.to_device("cuda"), home, "torch:cuda"


def bring_back(orig, work, res, home):
    """
    The return trip of pick_backend: merge results computed on the working backend back into the original image's backend.

    **Untouched layers use the original image's copy directly** -- the whole image can't be to_device'd back: an exact backend
    float64 layer making a trip to CUDA (float32) and back would lose precision even on layers unrelated to this node.
    The test is "this layer in the result is still the same object as in the working image" (CopImage.copy is a shallow copy;
    layers the node didn't write are passed through as is).
    """
    if home is None:
        return res
    from .core import CopImage
    xp = bk.get(home)
    out = CopImage(orig.xres, orig.yres)
    for k in res.names:
        v = res.get(k)
        if k in orig and k in work and work.get(k) is v:
            out.set(k, orig.get(k))
        else:
            out.set(k, xp.asarray(bk.backend_of(v).to_numpy(v)))
    return out
