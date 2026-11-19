"""
COP Wrangle on torch (a CUDA GPU; torch's CPU device for the tests): the same translated code, run on tensors.

Every per-pixel value here is a 2-D tensor (pixels, channels) -- a component (@N.z, v.y), a noise value, a length is
(pixels, 1), never (pixels,) -- so the ordinary broadcasting rules give what the numpy path's Vec / Col1 wrappers give
(a (pixels,) next to a (pixels, 1) would broadcast to pixels x pixels). Python numbers stay Python numbers (a loop
over angles, ch() values), so control flow on them works as on numpy.

The library covers what per-pixel COP code uses: arithmetic and comparisons, set / vector, the components, the maths
functions, clamp / fit / lerp / smoothstep, length / dot / cross / normalize, where, noise / pnoise (Perlin's, as
numpy's), worley / pworley / their _dir (the same lattice hash: the same cells), rand (the same bit mixing as numpy's,
so the same numbers). Anything else -- sprintf, astype, numpy calls on a layer,
`if` on a per-pixel value -- raises, and pixel.wrangle runs the whole node on numpy instead (the report says why).

On CUDA the arithmetic is float32 (rand is mixed in 64 bits, as on numpy): results match numpy to float32 rounding.
"""
from __future__ import annotations

import math

import numpy as np

from .. import wrangle as _W
from . import backend as bk


class Unsupported(RuntimeError):
    """The code needs something the torch path does not have: run it on numpy."""


_TV_CLS = None


def _tv_class():
    """torch.Tensor subclass with VEX-style .x .y .z .w (each a (pixels, 1) column)."""
    global _TV_CLS
    if _TV_CLS is None:
        torch = bk.torch_module()

        class TV(torch.Tensor):
            x = property(lambda self: self[..., 0:1])
            y = property(lambda self: self[..., 1:2])
            z = property(lambda self: self[..., 2:3])
            w = property(lambda self: self[..., 3:4])
            r = x
            g = y
            b = z
            a = w

            def __bool__(self):
                if self.numel() == 1:
                    return bool(self.item())
                raise Unsupported("a per-pixel value used as a condition (if / and / or): use where(cond, a, b)")

            def __array__(self, *a, **k):
                raise Unsupported("a numpy function called on a layer")

        _TV_CLS = TV
    return _TV_CLS


class _Lib:
    """The function library on one device / dtype."""

    def __init__(self, device, dtype):
        self.t = bk.torch_module()
        self.dev, self.dt = device, dtype
        self.TV = _tv_class()
        t = self.t
        self.perm = t.as_tensor(_W._P512, dtype=t.int64, device=device)
        self.gx = t.as_tensor(_W._GX, dtype=dtype, device=device)
        self.gy = t.as_tensor(_W._GY, dtype=dtype, device=device)
        self.gz = t.as_tensor(_W._GZ, dtype=dtype, device=device)

    # ── conversion
    def T(self, x):
        """Anything numeric -> a 2-D tensor (rows, channels) of this device / dtype (a number: (1, 1))."""
        t = self.t
        if isinstance(x, t.Tensor):
            if x.dtype == t.bool:
                x = x.to(self.dt)
            elif x.dtype != self.dt:
                x = x.to(self.dt)
            if x.dim() == 0:
                x = x.reshape(1, 1)
            elif x.dim() == 1:
                x = x.reshape(1, -1)         # a vector constant (chv, a tuple): one row
            return x.as_subclass(self.TV)
        if isinstance(x, (bool, int, float, np.floating, np.integer)):
            return t.full((1, 1), float(x), dtype=self.dt, device=self.dev).as_subclass(self.TV)
        a = np.asarray(x, np.float64)
        if a.dtype.kind not in "fiub":
            raise Unsupported(f"a non-numeric value ({a.dtype}) in a per-pixel expression")
        if a.ndim == 0:
            a = a.reshape(1, 1)
        elif a.ndim == 1:
            a = a.reshape(1, -1)
        return t.as_tensor(a, dtype=self.dt, device=self.dev).as_subclass(self.TV)

    def wrap(self, a):
        return a.as_subclass(self.TV) if isinstance(a, self.t.Tensor) else a

    # ── element-wise functions that keep Python numbers as numbers
    def unary(self, fn, pyfn):
        def f(x):
            if isinstance(x, (int, float, np.floating, np.integer)) and not isinstance(x, bool):
                return pyfn(float(x))
            return self.wrap(fn(self.T(x)))
        return f

    def binary(self, fn, pyfn):
        def f(a, b):
            if all(isinstance(v, (int, float, np.floating, np.integer)) for v in (a, b)):
                return pyfn(float(a), float(b))
            return self.wrap(fn(self.T(a), self.T(b)))
        return f

    # ── noise: Perlin's improved noise, as wrangle.perlin3 (0..1)
    def _p3(self, p):
        p = self.T(p)
        if p.shape[-1] == 1:
            p = p.expand(-1, 3)
        return p[..., 0:3]

    def _grad(self, h, x, y, z):
        h = h & 15
        return self.gx[h] * x + self.gy[h] * y + self.gz[h] * z

    def noise(self, p, period=None):
        t = self.t
        p = self._p3(p)
        fl = t.floor(p)
        fr = p - fl
        il = fl.to(t.int64)
        if period is None:
            X0, Y0, Z0 = (il[..., k] & 255 for k in range(3))
            X1, Y1, Z1 = ((il[..., k] + 1) & 255 for k in range(3))
        else:
            per = self._period(period)

            def wrap(i, k):
                return (t.remainder(i, int(per[k])) if per[k] > 0 else i) & 255
            X0, Y0, Z0 = (wrap(il[..., k], k) for k in range(3))
            X1, Y1, Z1 = (wrap(il[..., k] + 1, k) for k in range(3))
        x, y, z = fr[..., 0], fr[..., 1], fr[..., 2]
        fade = lambda v: v * v * v * (v * (v * 6 - 15) + 10)     # noqa: E731
        u, v, w = fade(x), fade(y), fade(z)
        P = self.perm

        def h(X, Y, Z):
            return P[P[P[X] + Y] + Z]
        L = lambda tt, a, b: a + tt * (b - a)                       # noqa: E731
        res = L(w, L(v, L(u, self._grad(h(X0, Y0, Z0), x, y, z), self._grad(h(X1, Y0, Z0), x - 1, y, z)),
                     L(u, self._grad(h(X0, Y1, Z0), x, y - 1, z), self._grad(h(X1, Y1, Z0), x - 1, y - 1, z))),
                L(v, L(u, self._grad(h(X0, Y0, Z1), x, y, z - 1), self._grad(h(X1, Y0, Z1), x - 1, y, z - 1)),
                  L(u, self._grad(h(X0, Y1, Z1), x, y - 1, z - 1), self._grad(h(X1, Y1, Z1), x - 1, y - 1, z - 1))))
        return self.wrap((res * 0.5 + 0.5)[..., None])

    # ── cellular noise: wrangle.worley3_periodic (the same lattice hash, so the same cells and feature points)
    def _lsr(self, v, n):
        return (v >> n) & ((1 << (64 - n)) - 1)

    def _cell_hash(self, X, Y, Z, salt):
        w = bk.wrap64
        k = (X * w(0x9E3779B97F4A7C15)) ^ (Y * w(0xC2B2AE3D27D4EB4F)) ^ (Z * w(0x165667B19E3779F9)) \
            ^ w(salt * 0x27D4EB2F165667C5)
        k = k ^ self._lsr(k, 30)
        k = k * w(0xBF58476D1CE4E5B9)
        k = k ^ self._lsr(k, 27)
        k = k * w(0x94D049BB133111EB)
        k = k ^ self._lsr(k, 31)
        return k

    def _period(self, period):
        if isinstance(period, self.t.Tensor):
            if period.numel() > 4:
                raise Unsupported("a per-pixel period")
            period = period.detach().cpu().numpy()
        per = np.asarray(period, np.float64).reshape(-1)
        per = np.broadcast_to(per if per.size in (1, 3) else per[:1], (3,))
        return np.maximum(np.rint(per), 0).astype(np.int64)

    def worley(self, p, period=0):
        t = self.t
        p = self.T(p)
        if p.shape[-1] == 1:
            p = p.expand(-1, 3)
        dim = 2 if p.shape[-1] == 2 else 3
        p = p[..., :dim]
        per = self._period(period)
        base = t.floor(p).to(t.int64)
        n = p.shape[0]
        f1 = t.full((n,), float("inf"), dtype=self.dt, device=self.dev)
        f2 = f1.clone()
        cid = t.zeros(n, dtype=self.dt, device=self.dev)
        vec = t.zeros((n, dim), dtype=self.dt, device=self.dev)
        zero = t.zeros(n, dtype=t.int64, device=self.dev)
        for dz in ((-1, 0, 1) if dim == 3 else (0,)):
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    c = base + t.as_tensor([dx, dy, dz][:dim], dtype=t.int64, device=self.dev)
                    wv = [t.remainder(c[:, k], int(per[k])) if per[k] > 0 else c[:, k] for k in range(dim)]
                    wv += [] if dim == 3 else [zero]
                    h = self._cell_hash(wv[0], wv[1], wv[2], 1)
                    h2 = self._cell_hash(wv[0], wv[1], wv[2], 2)
                    fp = t.stack([((h2 >> (21 * k)) & 0x1FFFFF).to(self.dt) / 2097152.0 for k in range(dim)], -1)
                    d = c.to(self.dt) + 0.5 + (fp - 0.5) - p
                    dist = t.sqrt((d * d).sum(-1))
                    closer = dist < f1
                    f2 = t.where(closer, f1, t.minimum(f2, dist))
                    f1 = t.where(closer, dist, f1)
                    cid = t.where(closer, self._lsr(h, 11).to(t.float64).mul(1.0 / 2.0 ** 53).to(self.dt), cid)
                    vec = t.where(closer[:, None], d, vec)
        return f1[:, None], f2[:, None], cid[:, None], vec

    def worley_memo(self, p, period, memo):
        """the last two evaluations remembered: pworley(q, n) and pworley_dir(q, n) on the same q cost one"""
        p = self.T(p)
        key = str(self._period(period).tolist())
        for q, k, v in memo:
            if k == key and q.shape == p.shape and self.t.equal(q, p):
                return v
        v = self.worley(p, period)
        memo.insert(0, (p, key, v))
        del memo[2:]
        return v

    # ── rand: wrangle._hash01's bit mixing in int64 (wrapping multiplication = uint64's; the shifts made logical)
    def rand(self, x, salt):
        if isinstance(x, (int, float, np.floating, np.integer)):
            return _W._hash01(x, salt)
        t = self.t
        a = self.T(x).to(t.float64)
        u = (a * 1000003.0).to(t.int64)
        u = u + bk.wrap64((int(salt) & 0xFFFFFFFF) * 0x9E3779B97F4A7C15)
        lsr = lambda v, n: (v >> n) & ((1 << (64 - n)) - 1)          # noqa: E731
        u = u ^ lsr(u, 33)
        u = u * bk.wrap64(0xFF51AFD7ED558CCD)
        u = u ^ lsr(u, 33)
        u = u * bk.wrap64(0xC4CEB9FE1A85EC53)
        u = u ^ lsr(u, 33)
        r = lsr(u, 11).to(t.float64) / float(1 << 53)
        return self.wrap(r.to(self.dt))

    def namespace(self, seed, ch_params):
        t = self.t
        U, B = self.unary, self.binary
        T = self.T

        def vec(*a):
            cols = [T(c) for c in a]
            n = max(c.shape[0] for c in cols)
            cols = [c.expand(n, -1) if c.shape[0] != n else c for c in cols]
            return self.wrap(t.cat(cols, -1))

        def clamp(x, a, b):
            if isinstance(x, (int, float)) and isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return min(max(float(x), a), b)
            x = T(x)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return self.wrap(t.clamp(x, float(a), float(b)))
            return self.wrap(t.minimum(t.maximum(x, T(a)), T(b)))

        def smoothstep(a, b, x):
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                d = (b - a) or 1e-9
                tt = clamp((x - a) / d if not isinstance(x, (int, float)) else (float(x) - a) / d, 0.0, 1.0)
                return tt * tt * (3 - 2 * tt)
            raise Unsupported("smoothstep with per-pixel edges")

        def fit(x, a, b, c, d):
            if not all(isinstance(v, (int, float)) for v in (a, b)):
                raise Unsupported("fit with per-pixel ranges")
            lo, hi = min(a, b), max(a, b)
            span = (b - a) or 1e-9
            return c + (clamp(x, lo, hi) - a) / span * (d - c)

        def length(v):
            return self.wrap(t.linalg.vector_norm(T(v), dim=-1, keepdim=True))

        def dot(a, b):
            return self.wrap((T(a) * T(b)).sum(-1, keepdim=True))

        def normalize(v):
            v = T(v)
            return self.wrap(v / t.clamp(t.linalg.vector_norm(v, dim=-1, keepdim=True), min=1e-9))

        def cross(a, b):
            a, b = t.broadcast_tensors(T(a), T(b))
            return self.wrap(t.linalg.cross(a, b, dim=-1))

        def where(c, a, b):
            c = T(c) != 0
            return self.wrap(t.where(c, T(a), T(b)))

        def mn(a, b, *rest):
            if rest:
                raise Unsupported("min / max of more than two values")
            if all(isinstance(v, (int, float)) for v in (a, b)):
                return min(float(a), float(b))
            return self.wrap(t.minimum(T(a), T(b)))

        def mx(a, b, *rest):
            if rest:
                raise Unsupported("min / max of more than two values")
            if all(isinstance(v, (int, float)) for v in (a, b)):
                return max(float(a), float(b))
            return self.wrap(t.maximum(T(a), T(b)))

        def no(name):
            def f(*a, **k):
                raise Unsupported(f"{name}() is not on the GPU path")
            return f

        def _round(x, nd=0):
            if isinstance(x, (int, float)):
                return _W._namespace()["__builtins__"]["round"](x, nd)
            raise Unsupported("round() on a per-pixel value")

        wm = []                                  # pworley / pworley_dir memo of this namespace
        ns = {"np": np, "math": math, "__builtins__": {
            "abs": U(t.abs, abs), "min": mn, "max": mx, "range": range, "len": len,
            "float": float, "int": int, "bool": bool, "print": print,
            "enumerate": enumerate, "zip": zip, "sum": sum, "round": _round,
            "str": str, "True": True, "False": False, "None": None,
        }}
        ns.update(
            sin=U(t.sin, math.sin), cos=U(t.cos, math.cos), tan=U(t.tan, math.tan),
            asin=U(t.asin, math.asin), acos=U(t.acos, math.acos), atan=U(t.atan, math.atan),
            sinh=U(t.sinh, math.sinh), cosh=U(t.cosh, math.cosh), tanh=U(t.tanh, math.tanh),
            atan2=B(t.atan2, math.atan2),
            sqrt=U(t.sqrt, math.sqrt), cbrt=U(lambda v: t.sign(v) * t.abs(v) ** (1.0 / 3.0), np.cbrt),
            pow=B(t.pow, lambda a, b: a ** b), exp=U(t.exp, math.exp), log=U(t.log, math.log),
            log10=U(t.log10, math.log10),
            floor=U(t.floor, lambda v: float(math.floor(v))), ceil=U(t.ceil, lambda v: float(math.ceil(v))),
            rint=U(t.round, lambda v: float(np.rint(v))), trunc=U(t.trunc, lambda v: float(math.trunc(v))),
            sign=U(t.sign, lambda v: float(np.sign(v))),
            frac=U(lambda v: v - t.floor(v), lambda v: v - math.floor(v)),
            clamp=clamp, fit=fit,
            fit01=lambda x, c, d: c + clamp(x, 0.0, 1.0) * (d - c),
            fit10=lambda x, c, d: d + clamp(x, 0.0, 1.0) * (c - d),
            efit=lambda x, a, b, c, d: c + (x - a) / ((b - a) or 1e-9) * (d - c),
            lerp=lambda a, b, tt: a + (b - a) * tt,
            smooth=smoothstep, smoothstep=smoothstep,
            length=length, length2=lambda v: self.wrap((T(v) ** 2).sum(-1, keepdim=True)),
            distance=lambda a, b: length(T(a) - T(b)),
            distance2=lambda a, b: self.wrap(((T(a) - T(b)) ** 2).sum(-1, keepdim=True)),
            normalize=normalize, cross=cross, dot=dot,
            set=vec, vector=vec, vector2=vec, vector4=vec,
            radians=U(lambda v: v * (math.pi / 180), math.radians),
            degrees=U(lambda v: v * (180 / math.pi), math.degrees),
            where=where, PI=math.pi,
            noise=lambda p: self.noise(p), pnoise=lambda p, period: self.noise(p, period),
            vnoise=lambda p: vec(self.noise(p), self.noise(T(p) + 31.7), self.noise(T(p) + 77.3)),
            worley=lambda p: vec(*self.worley_memo(p, 0, wm)[:3]),
            pworley=lambda p, period: vec(*self.worley_memo(p, period, wm)[:3]),
            worley_dir=lambda p: self.wrap(self.worley_memo(p, 0, wm)[3]),
            pworley_dir=lambda p, period: self.wrap(self.worley_memo(p, period, wm)[3]),
            sprintf=no("sprintf"), itoa=no("itoa"),
        )
        ns.update(_W.ch_funcs(ch_params))
        ns["seed"] = int(seed)
        ns["rand"] = lambda x, _s=int(seed): self.rand(x, _s)
        return ns


_LIBS = {}


def lib(device, dtype):
    k = (str(device), str(dtype))
    if k not in _LIBS:
        _LIBS[k] = _Lib(device, dtype)
    return _LIBS[k]


def translate(code):
    """@layer -> _L["layer"], @layer.x -> _L["layer"][:, 0:1] (a (pixels, 1) column, written in place the same way)."""
    from .pixel import _AT, _CMAP

    def sub(m):
        name, comp = m.group(1), m.group(2)
        if name in ("u", "v", "x", "y", "ix", "res") and comp is None:
            return f"_S['{name}']"
        e = f'_L["{name}"]'
        if comp:
            k = _CMAP[comp]
            e += f"[:, {k}:{k + 1}]"
        return e
    return _AT.sub(sub, str(code))


def band(img, code, seed, ch_params, r0, r1, device, dtype):
    """One band of rows on torch -> (translated code, {layer: numpy (pixels, channels)} written or changed)."""
    from ..wrangle import check_code
    L_ = lib(device, dtype)
    t = L_.t
    W, H = img.xres, img.yres
    N = W * (r1 - r0)
    cache, dirty = {}, set()

    def _rows(name):
        a = img.need(name)
        a = bk.backend_of(a).to_numpy(a)[r0:r1]
        a = np.array(a, np.float32 if dtype == t.float32 else np.float64, order="C").reshape(N, -1)
        return t.from_numpy(a).to(device=device, dtype=dtype)

    class _Lc:
        def __getitem__(self, name):
            name = str(name).strip() or "C"
            if name in cache:
                return cache[name]
            a = (_rows(name).clone() if name in img
                 else t.zeros((N, 1), dtype=dtype, device=device)).as_subclass(L_.TV)
            cache[name] = a
            return a

        def __setitem__(self, name, value):
            name = str(name).strip() or "C"
            v = L_.T(value)
            if v.shape[0] == 1 and N != 1:
                v = v.expand(N, -1)
            if v.shape[0] != N:
                raise RuntimeError(f"@{name} has {v.shape[0]} rows, not the band's {N} pixels")
            cache[name] = v.contiguous().as_subclass(L_.TV)
            dirty.add(name)

    J = t.arange(W, dtype=dtype, device=device).repeat(r1 - r0)
    I = t.arange(r0, r1, dtype=dtype, device=device).repeat_interleave(W)
    special = {"u": L_.wrap(((J + 0.5) / W).reshape(N, 1)), "v": L_.wrap(((I + 0.5) / H).reshape(N, 1)),
               "x": L_.wrap(J.reshape(N, 1)), "y": L_.wrap(I.reshape(N, 1)),
               "ix": L_.wrap(t.arange(r0 * W, r0 * W + N, dtype=dtype, device=device).reshape(N, 1)),
               "res": L_.T(np.array([W, H], np.float64))}
    py = translate(code)
    check_code(py, "COP Wrangle")
    ns = L_.namespace(seed, ch_params)
    ns["_L"] = _Lc()
    ns["_S"] = special
    try:
        exec(compile(py, "<cop wrangle (torch)>", "exec"), ns)
        part = {}
        for k in cache:
            a = cache[k]
            if k in dirty or (k in img and not t.equal(a, _rows(k))):
                if a.shape[0] != N:
                    raise RuntimeError(f"@{k} has shape {tuple(a.shape)}, not (pixel count, channels)")
                if a.shape[1] > 4:
                    raise RuntimeError(f"@{k} has {a.shape[1]} channels; at most 4 allowed")
                part[k] = a.detach().to("cpu", t.float64).numpy()
    finally:
        ns.clear()
        cache.clear()
    return py, part
