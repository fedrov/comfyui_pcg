"""
COP compute backends: numpy or torch (CPU / CUDA).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
torch is **not a new dependency**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This plugin has always refused scipy / trimesh, on the grounds that "every extra dependency is one more install that can fail". torch
is a different matter entirely: **ComfyUI itself runs on torch**; it's already loaded in the process and the GPU is already
initialized. Using it adds no install burden at all, it just hooks up compute that's already there.

The geometry side stays put -- it's irregular topology, dicts and hot Python loops; moving it to the GPU gains little and
risks a lot. COP is the exact opposite: all regular (H,W,C) per-pixel operations, a natural fit for the GPU.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Why an explicit operator table instead of "swap np for torch"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Most torch functions share names and arguments with numpy, so it looks like `xp = torch if gpu else np` would do.
In fact a few places are **silently different**, and all of them are fatal:

    np.max(a, axis=-1)      -> values
    torch.max(a, dim=-1)    -> **a named tuple (values, indices)**       ← silently wrong

    np.pad(a, w, "wrap")    -> any number of dimensions
    F.pad(a, w, "circular") -> only accepts NCHW, and 3D must be reshaped first

    np.ix_(iy, ix)          -> outer-product indexing
    torch                   -> doesn't exist; must write a[iy][:, ix]

    uint64 bitwise ops      -> torch **simply doesn't have them** (see the hash below)

"Silently giving a different result" is the worst kind of bug. So there's an explicit operator table here, implemented once for each
backend, and new operators must be written for both -- an error up front beats wrong images at run time.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Hashing: torch has no uint64, so int64 is used to emulate it **exactly**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The noise's splitmix64 needs uint64 multiplication and **logical** right shift. torch's uint64 is just a placeholder
type, with no bitwise or multiplication kernels.

But int64 is enough, and exact:

    · multiplication: two's-complement wrap-around multiplication is bit-identical to uint64, only interpreted differently. Constants above 2^63
      are written as negatives (`0xFF51AFD7ED558CCD - 2**64`)
    · right shift: int64's `>>` is an **arithmetic** shift (sign-filling), uint64 needs a **logical**
      shift. Adding a mask fixes it: `(x >> n) & ((1 << (64-n)) - 1)`

So the hash is **bit-identical** on both backends. The interpolation after it runs in float32 (fp64 on consumer GPUs
is only 1/32 to 1/64 the speed of fp32; float64 on the GPU defeats the purpose), so the final values
differ from numpy's float64 path at float32 rounding magnitude (measured ~1e-6), not bit-exact.

**This is the only thing lost in moving to the GPU**: the previous batch's "COP noise is bit-identical to the geometry side".
So an `exact` backend (numpy + float64) is kept specifically to preserve that; `COP Noise` has a toggle for it.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
auto policy: small images should **not** go to the GPU
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Kernel launch + host/device transfer is a fixed overhead, tens of microseconds and up. 256×256 is only 65k pixels;
one clip on the CPU is tens of microseconds -- the GPU has lost before it starts computing, and a chain of
ten nodes is ten round trips.

So `auto` decides by **pixel count**: below a threshold (default 256² = 65536) it uses the CPU. The threshold lives in
`AUTO_PIXELS` and can be changed -- it depends on GPU model and PCIe bandwidth; the default is labelled as "a number measured on my machine"
rather than pretending there's a universally correct value.

VRAM deserves some deference too: ComfyUI users already run diffusion models right at the VRAM limit. 4096² with four float32 layers
is 268 MB; above `VRAM_BUDGET_MB` it falls back to the CPU and **says so**, rather than squeezing the sampler into OOM.
"""
from __future__ import annotations

import numpy as np

DEVICES = ("auto", "cpu", "cuda", "numpy", "exact")
# auto threshold: below this pixel count use the CPU. The GPU's fixed overhead eats all the gain on small images
AUTO_PIXELS = 256 * 256
# VRAM allowed per image (MB). Above it fall back to the CPU -- don't fight the diffusion model into OOM
VRAM_BUDGET_MB = 1024

_TORCH = None
_TORCH_TRIED = False


def wrap64(v):
    """Fold constants >2^63 into the equivalent negative int64 -- same bit pattern, shared by both backends."""
    v = int(v) & ((1 << 64) - 1)
    return v - (1 << 64) if v >= (1 << 63) else v


def torch_module():
    """Get torch (None if unavailable). Imported only once; a failure is also only tried once."""
    global _TORCH, _TORCH_TRIED
    if not _TORCH_TRIED:
        _TORCH_TRIED = True
        try:
            import torch
            _TORCH = torch
        except Exception:
            _TORCH = None
    return _TORCH


def cuda_available():
    t = torch_module()
    try:
        return bool(t is not None and t.cuda.is_available())
    except Exception:
        return False


# ════════════════════════════════════════════════════════════ numpy backend
class NumpyBackend:
    name = "numpy"
    device = "cpu"
    is_torch = False

    def __init__(self, fdtype=np.float32):
        self.fdtype = fdtype

    # ── construction / conversion ──────────────────────────────────────
    def asarray(self, a, dtype=None):
        return np.asarray(a, dtype or self.fdtype)

    def to_numpy(self, a):
        return np.asarray(a, self.fdtype)

    def zeros(self, shape, dtype=None):
        return np.zeros(shape, dtype or self.fdtype)

    def ones(self, shape, dtype=None):
        return np.ones(shape, dtype or self.fdtype)

    def full(self, shape, v, dtype=None):
        return np.full(shape, v, dtype or self.fdtype)

    def arange(self, n, dtype=None):
        return np.arange(n, dtype=dtype or self.fdtype)

    def iarange(self, n):
        return np.arange(n, dtype=np.int64)

    def empty_like(self, a):
        return np.empty_like(a)

    # ── shape ──────────────────────────────────────────────────────────
    def stack(self, xs, axis=0):
        return np.stack(xs, axis)

    def concat(self, xs, axis=0):
        return np.concatenate(xs, axis)

    def broadcast_to(self, a, shape):
        return np.broadcast_to(a, shape)

    def repeat_last(self, a, n):
        return np.repeat(a, n, axis=-1)

    def reshape(self, a, shape):
        return np.reshape(a, shape)

    def flip(self, a, axis):
        return np.flip(a, axis)

    def contiguous(self, a):
        return np.ascontiguousarray(a)

    # ── math ───────────────────────────────────────────────────────────
    def abs(self, a):
        return np.abs(a)

    def floor(self, a):
        return np.floor(a)

    def sqrt(self, a):
        return np.sqrt(a)

    def exp(self, a):
        return np.exp(a)

    def cos(self, a):
        return np.cos(a)

    def sin(self, a):
        return np.sin(a)

    def arctan2(self, a, b):
        return np.arctan2(a, b)

    def clip(self, a, lo, hi):
        return np.clip(a, lo, hi)

    def where(self, c, a, b):
        return np.where(c, a, b)

    def minimum(self, a, b):
        return np.minimum(a, b)

    def maximum(self, a, b):
        return np.maximum(a, b)

    def amax(self, a, axis):
        """Note: torch.max(dim=) returns (values, indices), so both sides use amax."""
        return np.max(a, axis=axis)

    def amin(self, a, axis):
        return np.min(a, axis=axis)

    def sum(self, a, axis=None):
        return np.sum(a, axis=axis)

    def norm(self, a, axis=-1):
        return np.sqrt(np.sum(a * a, axis=axis))

    def fmin_scalar(self, a):
        return float(np.min(a))

    def fmax_scalar(self, a):
        return float(np.max(a))

    def fmean_scalar(self, a):
        return float(np.mean(a))

    # ── indexing ───────────────────────────────────────────────────────
    def outer_index(self, a, iy, ix):
        """a[np.ix_(iy, ix)] -- outer-product row/column indexing."""
        return a[np.ix_(iy, ix)]

    def gather_rows(self, table, idx):
        """table[(idx,)] -- take rows by integer index."""
        return table[idx]

    def index2(self, a, iy, ix):
        """a[iy, ix], iy/ix are integer arrays of the same shape."""
        return a[iy, ix]

    def pad_axis(self, a, r, axis, mode):
        w = [(0, 0)] * a.ndim
        w[axis] = (r, r)
        m = {"clamp": "edge", "wrap": "wrap", "black": "constant"}[mode]
        return np.pad(a, w, mode=m)

    # ── integers / hashing ─────────────────────────────────────────────
    def to_i64(self, a):
        return np.asarray(a, np.int64)

    def i64(self, v):
        return np.int64(wrap64(v))

    def mul_i64(self, a, b):
        with np.errstate(over="ignore"):
            return np.asarray(a, np.int64) * np.int64(wrap64(b))

    def add_i64(self, a, b):
        with np.errstate(over="ignore"):
            return np.asarray(a, np.int64) + (
                b if isinstance(b, np.ndarray) else np.int64(wrap64(b)))

    def xor_i64(self, a, b):
        return np.bitwise_xor(a, b if isinstance(b, np.ndarray)
                              else np.int64(wrap64(b)))

    def and_i64(self, a, b):
        return np.bitwise_and(a, b if isinstance(b, np.ndarray)
                              else np.int64(wrap64(b)))

    def lshr_i64(self, a, n):
        """**Logical** right shift (zero-filling), not arithmetic."""
        return np.bitwise_and(np.right_shift(a, n),
                              np.int64(wrap64((1 << (64 - n)) - 1)))

    def mod_i64(self, a, m):
        return np.mod(a, np.int64(m))

    def umod_i64(self, a, m):
        """
        Modulo under the **uint64 interpretation** -- a negative int64 must first be treated as +2^64 before the modulo.

        This is the nastiest spot in porting the hash: the original is `h_uint64 % 12`; replacing it with
        `h_int64 % 12` looks the same, but for half the hash values (those with the sign bit set) it
        gives different gradient indices. 2^64 mod 12 = 4, so the negative branch needs +4 before the modulo.
        Measured without it: whole perlin / simplex images are wrong (max difference 3.2), while value
        and worley still "pass" because they don't look up the gradient table -- a classic half-right.
        """
        r = np.mod(a, np.int64(m))
        k = np.int64((1 << 64) % int(m))
        return np.where(a < 0, np.mod(r + k, np.int64(m)), r)


# ════════════════════════════════════════════════════════════ torch backend
class TorchBackend:
    is_torch = True

    def __init__(self, device="cpu"):
        t = torch_module()
        if t is None:
            raise RuntimeError("torch is not available")
        self.t = t
        self.device = t.device(device)
        self.name = f"torch:{self.device.type}"
        self.fdtype = t.float32

    def asarray(self, a, dtype=None):
        t = self.t
        dt = dtype or self.fdtype
        if isinstance(a, t.Tensor):
            return a.to(device=self.device, dtype=dt)
        n = np.asarray(a)
        # as_tensor warns on read-only numpy arrays (torch has no read-only tensors), so make a copy
        if not n.flags.writeable:
            n = np.array(n)
        return t.as_tensor(n, device=self.device).to(dt)

    def to_numpy(self, a):
        if isinstance(a, self.t.Tensor):
            return a.detach().to("cpu", self.t.float32).numpy()
        return np.asarray(a, np.float32)

    def zeros(self, shape, dtype=None):
        return self.t.zeros(shape, dtype=dtype or self.fdtype,
                            device=self.device)

    def ones(self, shape, dtype=None):
        return self.t.ones(shape, dtype=dtype or self.fdtype,
                           device=self.device)

    def full(self, shape, v, dtype=None):
        return self.t.full(tuple(shape), float(v),
                           dtype=dtype or self.fdtype, device=self.device)

    def arange(self, n, dtype=None):
        return self.t.arange(n, dtype=dtype or self.fdtype,
                             device=self.device)

    def iarange(self, n):
        return self.t.arange(n, dtype=self.t.int64, device=self.device)

    def empty_like(self, a):
        return self.t.empty_like(a)

    def stack(self, xs, axis=0):
        return self.t.stack([self._t(x) for x in xs], dim=axis)

    def concat(self, xs, axis=0):
        return self.t.cat([self._t(x) for x in xs], dim=axis)

    def broadcast_to(self, a, shape):
        return self._t(a).expand(tuple(shape))

    def repeat_last(self, a, n):
        return self._t(a).repeat_interleave(n, dim=-1)

    def reshape(self, a, shape):
        return self._t(a).reshape(tuple(shape))

    def flip(self, a, axis):
        return self.t.flip(self._t(a), dims=(axis,))

    def contiguous(self, a):
        return self._t(a).contiguous()

    def _t(self, a):
        if isinstance(a, self.t.Tensor):
            return a
        return self.asarray(a)

    def abs(self, a):
        return self.t.abs(self._t(a))

    def floor(self, a):
        return self.t.floor(self._t(a))

    def sqrt(self, a):
        return self.t.sqrt(self._t(a))

    def exp(self, a):
        return self.t.exp(self._t(a))

    def cos(self, a):
        return self.t.cos(self._t(a))

    def sin(self, a):
        return self.t.sin(self._t(a))

    def arctan2(self, a, b):
        return self.t.atan2(self._t(a), self._t(b))

    def clip(self, a, lo, hi):
        return self.t.clamp(self._t(a), float(lo), float(hi))

    def where(self, c, a, b):
        return self.t.where(self._t2(c), self._t(a), self._t(b))

    def _t2(self, c):
        if isinstance(c, self.t.Tensor):
            return c
        n = np.asarray(c)
        if not n.flags.writeable:
            n = np.array(n)
        return self.t.as_tensor(n, device=self.device)

    def minimum(self, a, b):
        return self.t.minimum(self._t(a), self._t(b))

    def maximum(self, a, b):
        return self.t.maximum(self._t(a), self._t(b))

    def amax(self, a, axis):
        # torch.max(dim=) returns a named tuple (values, indices); using it directly silently gives a tuple
        return self.t.amax(self._t(a), dim=axis)

    def amin(self, a, axis):
        return self.t.amin(self._t(a), dim=axis)

    def sum(self, a, axis=None):
        x = self._t(a)
        return self.t.sum(x) if axis is None else self.t.sum(x, dim=axis)

    def norm(self, a, axis=-1):
        x = self._t(a)
        return self.t.sqrt(self.t.sum(x * x, dim=axis))

    def fmin_scalar(self, a):
        return float(self.t.min(self._t(a)).item())

    def fmax_scalar(self, a):
        return float(self.t.max(self._t(a)).item())

    def fmean_scalar(self, a):
        return float(self.t.mean(self._t(a)).item())

    def outer_index(self, a, iy, ix):
        # torch has no np.ix_; index rows then columns, equivalent and with no extra memory
        return a.index_select(0, self._i(iy)).index_select(1, self._i(ix))

    def _i(self, a):
        if isinstance(a, self.t.Tensor):
            return a.to(self.device, self.t.int64)
        n = np.asarray(a, np.int64)
        if not n.flags.writeable:
            n = np.array(n)
        return self.t.as_tensor(n, device=self.device)

    def gather_rows(self, table, idx):
        return table.index_select(0, self._i(idx).reshape(-1)).reshape(
            tuple(self._i(idx).shape) + (table.shape[-1],))

    def index2(self, a, iy, ix):
        return a[self._i(iy), self._i(ix)]

    def pad_axis(self, a, r, axis, mode):
        # F.pad only accepts NCHW and uses different mode names; assembling it ourselves is shorter and more controllable
        t = self.t
        if mode == "black":
            sh = list(a.shape)
            sh[axis] = r
            z = t.zeros(sh, dtype=a.dtype, device=a.device)
            return t.cat([z, a, z], dim=axis)
        n = a.shape[axis]
        if mode == "wrap":
            idx = (t.arange(-r, n + r, device=a.device) % n)
        else:                                   # clamp
            idx = t.clamp(t.arange(-r, n + r, device=a.device), 0, n - 1)
        return a.index_select(axis, idx)

    def to_i64(self, a):
        return self._t2(a).to(self.t.int64) if not isinstance(
            a, self.t.Tensor) else a.to(self.t.int64)

    def i64(self, v):
        return int(v)

    _wrap64 = staticmethod(wrap64)

    def mul_i64(self, a, b):
        return self.to_i64(a) * self._wrap64(b)

    def add_i64(self, a, b):
        return self.to_i64(a) + (b if isinstance(b, self.t.Tensor)
                                 else self._wrap64(b))

    def xor_i64(self, a, b):
        return self.t.bitwise_xor(self.to_i64(a),
                                  b if isinstance(b, self.t.Tensor)
                                  else self._wrap64(b))

    def and_i64(self, a, b):
        return self.t.bitwise_and(self.to_i64(a),
                                  b if isinstance(b, self.t.Tensor)
                                  else self._wrap64(b))

    def lshr_i64(self, a, n):
        """int64's >> is an **arithmetic** shift (sign-filling); uint64 needs a logical shift. Add a mask."""
        return self.t.bitwise_and(
            self.t.bitwise_right_shift(self.to_i64(a), int(n)),
            self._wrap64((1 << (64 - int(n))) - 1))

    def mod_i64(self, a, m):
        return self.t.remainder(self.to_i64(a), int(m))

    def umod_i64(self, a, m):
        """Modulo under the uint64 interpretation (negatives get 2^64 mod m added). See the numpy backend's note."""
        a = self.to_i64(a)
        r = self.t.remainder(a, int(m))
        k = int((1 << 64) % int(m))
        return self.t.where(a < 0, self.t.remainder(r + k, int(m)), r)


NUMPY = NumpyBackend()
EXACT = NumpyBackend(np.float64)
_CACHE = {}


def get(device="auto", pixels=0, layers=1, channels=4):
    """
    Pick a backend by device and image size.

    auto: CUDA available, enough pixels, fits in VRAM -> cuda, otherwise numpy. Missing any one of the three
    falls back to the CPU, rather than "use the GPU whenever there is one" -- small images are a net loss on the GPU.
    """
    d = str(device or "auto").lower()
    if d not in DEVICES:
        raise ValueError(f"Device must be one of {DEVICES}")
    if d == "numpy":
        return NUMPY
    if d == "exact":
        return EXACT
    if d == "cpu":
        return _torch_backend("cpu") or NUMPY
    if d == "cuda":
        b = _torch_backend("cuda") if cuda_available() else None
        return b or NUMPY
    # auto
    if not cuda_available() or int(pixels) < AUTO_PIXELS:
        return NUMPY
    mb = int(pixels) * max(1, int(layers)) * max(1, int(channels)) * 4 / 1e6
    if mb > VRAM_BUDGET_MB:
        return NUMPY
    return _torch_backend("cuda") or NUMPY


def _torch_backend(dev):
    if torch_module() is None:
        return None
    b = _CACHE.get(dev)
    if b is None:
        try:
            b = TorchBackend(dev)
        except Exception:
            return None
        _CACHE[dev] = b
    return b


def backend_of(a):
    """Which backend an array belongs to."""
    t = torch_module()
    if t is not None and isinstance(a, t.Tensor):
        return _torch_backend(a.device.type) or NUMPY
    if isinstance(a, np.ndarray) and a.dtype == np.float64:
        return EXACT
    return NUMPY


def describe():
    """One-line status for node errors and logs."""
    t = torch_module()
    if t is None:
        return "torch is not installed -- COP can only use numpy (shouldn't normally happen in ComfyUI)"
    if not cuda_available():
        return f"torch {t.__version__}, no CUDA device available -- using CPU"
    return (f"torch {t.__version__}, CUDA available: "
            f"{t.cuda.get_device_name(0)}")
