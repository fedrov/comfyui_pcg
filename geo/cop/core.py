"""
Copernicus data model -- an "image" is **a set of named layers**, not a single RGB block.

Mirrors Houdini 20.5's COP (Copernicus) context. This is the plugin's second data type:
everything before is `Geometry` (point/vertex/primitive/detail attribute classes); here it's `CopImage`
(a number of (H,W,C) float layers). The two interoperate through nodes like Rasterize / Attribute from Map
-- that comes later; this batch gets the foundation right first.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Why not just use ComfyUI's IMAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ComfyUI's IMAGE is a (B,H,W,3) 0-1 tensor. Using it as COP's main type makes three things impossible right away:

    · **Multiple layers**. The core of COP is one image carrying several layers C / mask / P / N / depth,
      flowing together down one chain. Squashing it to a single RGB means splitting the chain into N parallel branches,
      which ought to share resolution and coordinate system
    · **Values outside 0-1**. SDFs are signed distances, noise is ±1, height fields are in metres. Clamping to 0-1
      destroys these nodes' output
    · **Arbitrary channel counts**. A mask is 1 channel, normals 3, motion vectors 2. Forcing everything to 3
      is wasteful and means writing "take channel 0" everywhere

So we define our own `COPIMAGE` type, plus two bridge nodes (COP Import / COP Export)
to interoperate with ComfyUI's IMAGE. That way it can take sampler output and feed Preview / Save,
while the stretch in between keeps COP semantics.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Origin at the **bottom-left**, v up -- consistent with UV, opposite to ComfyUI
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This is the easiest landmine in the whole module, so it's fixed here:

    row 0  =  v = 0  =  **bottom** of the image

The reason is that COP ultimately connects to geometry: the uv attribute's v points up, texture sampling `texture(uv)`'s v
points up, and Houdini's COP is v up too. Internally v stays up, and it is flipped once only **at the layer bordering
ComfyUI** (ComfyUI / PIL / most image libraries have row 0 at the top).

Flipping is only written in the two functions `from_comfy` / `to_comfy`. `[::-1]` anywhere else
is a bug -- it means someone flipped again somewhere in the middle.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Values are **linear float32, unclamped**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Intermediate steps never clamp and never do sRGB conversion. Clamping only happens at the export-to-IMAGE step,
and it is **optional** -- to send an SDF straight to Preview for a rough look, turn off clamping and add a
remap.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Layers can be numpy arrays, **or torch tensors (including CUDA)**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`CopImage` doesn't care where its layers live -- numpy arrays, CPU tensors, tensors in VRAM are all fine; resolution
and channel-count semantics are exactly the same. Computation goes through the operator table in `backend.py`; whoever gets
whichever array uses the matching backend.

One consistency requirement: **all layers of one image must be on the same backend**. If mixed, every operator
would have to check and secretly move data, and in the end nobody could say where an operation happened. `set` checks this.

The read-only convention is weakened on torch: numpy can truly lock with `flags.writeable = False`,
torch has no such thing. So the torch backend relies on **convention** (all operators return new tensors, never modify
in place) rather than enforcement. This must be written here, or someday someone adds a `+=` and silently corrupts upstream.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Same conventions as Geometry
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    · layer arrays are always `writeable=False`; copy first to modify -- the same rule as `Geometry`'s attribute
      arrays, so no node secretly modifies upstream data
    · `copy()` is shallow (copies the dict, not the arrays), so ten nodes chained in a row don't produce
      ten copies of the pixels
    · names follow Houdini convention: the colour layer is **C**, mask is **mask**, position **P**,
      normal **N**, depth **depth**
"""
from __future__ import annotations

import numpy as np

from . import backend as bk

# common Houdini COP layer names
LAYER_C = "C"
LAYER_MASK = "mask"
DEFAULT_LAYER = LAYER_C
MAX_RES = 16384


def _frozen(a):
    """
    Normalize to (H,W,C). numpy arrays are conveniently locked read-only; torch tensors are left as is (no such switch).

    dtype: torch is always float32; numpy keeps float64 (the exact backend relies on it to stay "bit-identical to
    the geometry side"), everything else is float32.
    """
    t = bk.torch_module()
    if t is not None and isinstance(a, t.Tensor):
        if a.dtype != t.float32:
            a = a.to(t.float32)
        if a.dim() == 2:
            a = a[:, :, None]
        if a.dim() != 3:
            raise ValueError(
                f"layer must be (H,W) or (H,W,C), got {tuple(a.shape)}")
        return a.contiguous()
    a = np.asarray(a)
    dt = np.float64 if a.dtype == np.float64 else np.float32
    a = np.asarray(a, dt)
    if a.ndim == 2:
        a = a[:, :, None]
    if a.ndim != 3:
        raise ValueError(f"layer must be (H,W) or (H,W,C), got {a.shape}")
    a = np.ascontiguousarray(a)
    a.flags.writeable = False
    return a


def device_of(a):
    """Where a layer lives: 'numpy' / 'cpu' / 'cuda'."""
    t = bk.torch_module()
    if t is not None and isinstance(a, t.Tensor):
        return a.device.type
    return "numpy"


class CopImage:
    """
    A set of named layers at the same resolution. row 0 is the **bottom** (v=0); values are linear float32, unclamped.
    """

    __slots__ = ("_layers", "_xres", "_yres")

    def __init__(self, xres=0, yres=0, layers=None):
        self._xres = int(xres)
        self._yres = int(yres)
        self._layers = {}
        for k, v in (layers or {}).items():
            self.set(k, v)

    # ── basic info ──────────────────────────────────────────────────────
    @property
    def xres(self):
        return self._xres

    @property
    def yres(self):
        return self._yres

    @property
    def res(self):
        return (self._xres, self._yres)

    @property
    def names(self):
        return list(self._layers)

    def __contains__(self, name):
        return name in self._layers

    def __len__(self):
        return len(self._layers)

    def info(self):
        parts = [f"{k}({v.shape[2]})" for k, v in self._layers.items()]
        return (f"CopImage {self._xres}x{self._yres} @{self.device} "
                f"[{', '.join(parts)}]")

    # ── read / write ────────────────────────────────────────────────────
    def get(self, name=DEFAULT_LAYER, default=None):
        return self._layers.get(name, default)

    def need(self, name=DEFAULT_LAYER):
        """Get a layer; if missing, raise an error listing the "existing layer names" -- the most common kind of error."""
        a = self._layers.get(name)
        if a is None:
            raise KeyError(
                f"this image has no '{name}' layer. Existing: "
                f"{self.names or '(empty)'}")
        return a

    def get_w(self, name=DEFAULT_LAYER):
        """A writable copy. Layers themselves are treated as read-only; modification must go through here."""
        a = self.need(name)
        t = bk.torch_module()
        if t is not None and isinstance(a, t.Tensor):
            return a.clone()
        return np.array(a, a.dtype)

    @property
    def device(self):
        """Where the layers live: 'numpy' / 'cpu' / 'cuda'. An empty image counts as 'numpy'."""
        if not self._layers:
            return "numpy"
        return device_of(next(iter(self._layers.values())))

    @property
    def backend(self):
        """The operator table this image should use."""
        if not self._layers:
            return bk.NUMPY
        return bk.backend_of(next(iter(self._layers.values())))

    def to_device(self, device="auto"):
        """Move the whole image to another backend. Returned as is if it's already there."""
        xp = bk.get(device, self._xres * self._yres, max(1, len(self)),
                    max((v.shape[2] for v in self._layers.values()),
                        default=1))
        if not self._layers or self.backend is xp:
            return self.copy()
        out = CopImage(self._xres, self._yres)
        for k, v in self._layers.items():
            src = v if isinstance(v, np.ndarray) else \
                bk.backend_of(v).to_numpy(v)
            out.set(k, xp.asarray(src))
        return out

    def set(self, name, data):
        a = _frozen(data)
        if self._layers:
            cur = device_of(next(iter(self._layers.values())))
            if device_of(a) != cur:
                raise ValueError(
                    f"layer '{name}' is on {device_of(a)}, the other layers of this image are on "
                    f"{cur} -- all layers of one image must be on the same backend. "
                    f"Insert a COP To Device first.")
        if self._xres == 0 and self._yres == 0 and not self._layers:
            self._yres, self._xres = a.shape[0], a.shape[1]
        if (a.shape[1], a.shape[0]) != (self._xres, self._yres):
            raise ValueError(
                f"layer '{name}' is {a.shape[1]}x{a.shape[0]}, "
                f"this image is {self._xres}x{self._yres} -- resolutions must match. "
                f"Insert a COP Resize / COP Transform first.")
        self._layers[name] = a
        return self

    def remove(self, name):
        self._layers.pop(name, None)
        return self

    def rename(self, old, new):
        if old in self._layers:
            self._layers[new] = self._layers.pop(old)
        return self

    def copy(self):
        """Shallow copy: only the dict is copied; pixels are shared (they're read-only anyway)."""
        out = CopImage.__new__(CopImage)
        out._xres, out._yres = self._xres, self._yres
        out._layers = dict(self._layers)
        return out

    # ── construction ────────────────────────────────────────────────────
    @staticmethod
    def blank(xres, yres, value=(0.0, 0.0, 0.0), name=DEFAULT_LAYER,
              device="numpy"):
        xres, yres = check_res(xres, yres)
        v = np.asarray(value, np.float64).reshape(-1)
        xp = bk.get(device, xres * yres, 1, len(v))
        a = xp.broadcast_to(xp.asarray(v).reshape(1, 1, len(v)),
                            (yres, xres, len(v)))
        return CopImage(xres, yres, {name: a})


def check_res(xres, yres):
    x, y = int(xres), int(yres)
    if x < 1 or y < 1:
        raise ValueError(f"resolution must be ≥ 1, got {x}x{y}")
    if x > MAX_RES or y > MAX_RES:
        raise ValueError(f"resolution limit is {MAX_RES}, got {x}x{y}")
    return x, y


def uv_grid(xres, yres, center=True, xp=None):
    """
    (yres, xres, 2) uv, range [0,1]. row 0 is v=0 (bottom).

    center=True takes **pixel centres** (0.5/N, 1.5/N, ...), not evenly spaced endpoints from 0 to 1.
    This is not a detail: endpoint sampling gives 0 and 1 half a pixel each, and periodic noise repeats a column at the seam,
    so tiling shows a visible seam. Pixel-centre sampling tiles seamlessly.
    """
    x, y = check_res(xres, yres)
    xp = xp or bk.NUMPY
    if center:
        u = (xp.arange(x) + 0.5) / x
        v = (xp.arange(y) + 0.5) / y
    else:
        u = xp.arange(x) / max(x - 1, 1)
        v = xp.arange(y) / max(y - 1, 1)
    U = xp.broadcast_to(xp.reshape(u, (1, x)), (y, x))
    V = xp.broadcast_to(xp.reshape(v, (y, 1)), (y, x))
    return xp.stack([U, V], -1)


def match_channels(a, b, xp=None):
    """
    Align the channel counts of two layers; there's only one rule: **1 channel broadcasts, the rest must be equal**.

    1 channel broadcasts because masks, heights and SDFs are naturally single-channel, and copying per component when compositing with RGB
    is exactly what you want. Between 3 and 4 there's **no automatic padding**: it's either wanted alpha or a forgotten connection,
    and guessing wrong costs more than an error.
    """
    xp = xp or bk.backend_of(a)
    ca, cb = a.shape[2], b.shape[2]
    if ca == cb:
        return a, b
    if ca == 1:
        return xp.broadcast_to(a, tuple(b.shape)), b
    if cb == 1:
        return a, xp.broadcast_to(b, tuple(a.shape))
    raise ValueError(
        f"channel counts don't match: {ca} and {cb}. Only 1 channel broadcasts automatically -- "
        f"no guessing between 3 and 4 (alpha may be wanted, or it may be miswired).")


def conform(img, ref, label="second input"):
    """
    Resample img to ref's resolution. Returned as is (no copy) if already the same.

    Houdini's COP also conforms automatically -- erroring when compositing two images of different resolutions would be too
    unfriendly. But it follows the **first input's** resolution, and so does this, bilinear only.
    """
    if img is None or ref is None:
        return img
    if img.res == ref.res:
        return img
    from .filters import resize
    return resize(img, ref.xres, ref.yres)
