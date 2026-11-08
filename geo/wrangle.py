"""
Wrangle -- emulates VEX with numpy vectorisation.

Key differences from VEX (users must know these, or they will write lots of wrong code):
  * The code is **not run once per point**; it runs once as a whole, and @P is an (N,3) array.
  * So `if` cannot be used; use np.where / boolean masks.
  * Syntactic sugar like @P.y is supported and expands to @P[:,1].
  * @ptnum / @numpt are available.

Supported syntax:
  @P, @N, @Cd, @pscale ...        read/write point attributes (created from the assigned shape if missing)
  @P.x / @P.y / @P.z / @P.w       component access, readable and writable
  @ptnum @numpt @primnum @numprim
  v@name f@name i@name s@name     declare the type (v = 3 floats, f = float, i = int, s = string, p = 4 floats as in
  2@ 3@ 4@ p@                     VEX's quaternion p@orient, 2/3/4 = that many floats); an assigned value is converted to it
  @group_xxx                      read / write the group xxx of the Run Over class (pcg113)

For true per-element VEX semantics (with if / for / recursion), replace exec with
numba.njit or a taichi kernel -- the interface stays the same, see the advanced section of the README.
"""
from __future__ import annotations

import re

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL

# v@name / f@name / i@name / @name  and @name.x
_ATTR_RE = re.compile(r"(?<![\w.])([vfips234])?@(\w+)(?:\.([xyzw]))?")
_COMP = {"x": 0, "y": 1, "z": 2, "w": 3}
_TYPE_C = {"v": 3, "f": 1, "i": 1, "s": 1, "p": 4, "2": 2, "3": 3, "4": 4}
_TYPE_DT = {"v": np.float32, "f": np.float32, "i": np.int32, "s": np.dtype(object),
            "p": np.float32, "2": np.float32, "3": np.float32, "4": np.float32}


# ═══════════════════════════════════════════════════ Code guard (pcg113)
# Wrangle code, group expressions and expression-node formulas come from workflow files, which people share. They are
# run as Python on the ComfyUI server, so a workflow from a stranger could otherwise read or write files or start
# programs. check_code() rejects the obvious ways to do that before anything runs: import statements, names and
# attributes that start with an underscore (Python internals such as __class__ / __globals__), numpy's file
# functions, and the frame / code objects of generators and functions. It is a guard, not a sandbox -- the docs say so
# (docs/concepts/wrangle.md#security). Setting the environment variable PCG_ALLOW_UNSAFE_CODE=1 turns it off.
_BLOCKED = frozenset((
    # numpy / Python file and process access
    "save", "savez", "savez_compressed", "savetxt", "load", "loadtxt", "genfromtxt", "fromfile", "fromregex",
    "tofile", "dump", "dumps", "memmap", "open", "DataSource", "lib", "ctypeslib", "ctypes", "f2py", "distutils",
    "testing", "core", "os", "sys", "system", "popen", "subprocess", "shutil", "pickle", "importlib", "builtins",
    # dynamic code and attribute access
    "exec", "eval", "compile", "getattr", "setattr", "delattr", "globals", "locals", "vars", "breakpoint", "input",
    "help", "exit", "quit", "type", "object", "super", "classmethod", "staticmethod", "property", "memoryview",
    "format", "format_map",
    # frames and code objects (generator / coroutine / traceback / function internals)
    "gi_frame", "gi_code", "gi_yieldfrom", "cr_frame", "cr_code", "ag_frame", "ag_code", "f_globals", "f_locals",
    "f_builtins", "f_back", "f_code", "tb_frame", "tb_next", "co_code", "mro",
))


class UnsafeCodeError(ValueError):
    pass


def check_code(py, what="Wrangle", mode="exec"):
    """Raise UnsafeCodeError if the (translated) code uses something the guard blocks; see the comment above."""
    import os as _os
    if _os.environ.get("PCG_ALLOW_UNSAFE_CODE", "").strip() in ("1", "true", "yes"):
        return
    import ast
    try:
        tree = ast.parse(py, mode=mode)
    except SyntaxError:
        return                       # compile() reports syntax errors with the usual message
    def bad(name, why):
        raise UnsafeCodeError(
            f"{what}: '{name}' is not allowed -- {why}. Code in a workflow runs as Python on the ComfyUI server, so "
            f"file access, imports and Python internals are blocked (see docs/concepts/wrangle.md, Security). "
            f"Set the environment variable PCG_ALLOW_UNSAFE_CODE=1 to lift this for trusted workflows.")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            bad("import", "np and math are already available")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                bad(node.attr, "attributes starting with an underscore are Python internals")
            if node.attr in _BLOCKED:
                bad(node.attr, "this function reaches files, programs or Python internals")
        elif isinstance(node, ast.Name):
            if node.id.startswith("__"):
                bad(node.id, "names starting with two underscores are Python internals")
            if node.id in _BLOCKED:
                bad(node.id, "this function reaches files, programs or Python internals")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bad("global", "use a local variable")


def _ustr(v):
    """object string array -> <U just wide enough (no truncation)."""
    v = np.asarray(v)
    out = np.array(["" if x is None else str(x) for x in v.reshape(-1)], dtype=str)
    if out.dtype.itemsize == 0:
        out = out.astype("<U1")
    return out.reshape(v.shape)


class _Bind:
    """Every @xxx in the code is read/written through this. Copy-on-write on first write."""

    def __init__(self, geo: Geometry, cls: str):
        self.geo = geo
        self.cls = cls
        self.n = geo.count(cls)
        self.cache = {}
        self.hints = {}
        self.dirty = set()
        # Single-component attributes with these names read as 1D (N,) views (still (N,1) when written back).
        # Used by Volume Wrangle: @value * sin(@P.x) would broadcast to N×N with (N,1) × (N,)
        self.squeeze = set()
        self.derived = set()        # computed read-only quantities (prim @P = face centre)
        self.groups = set()         # @group_xxx names (written back as groups, not attributes)

    def __getitem__(self, name):
        a = self._get(name)
        if name in self.squeeze and a.ndim == 2 and a.shape[1] == 1:
            return a[:, 0]
        return _cols(a)

    def _get(self, name):
        if name in self.cache:
            return self.cache[name]
        if name.startswith("group_") and self.cls != DETAIL:
            # pcg113: @group_top reads the group "top" of this class as 0/1 (VEX's @group_ syntax)
            gm = self.geo.get_group(self.cls, name[6:])
            a = (np.zeros((self.n, 1), np.int32) if gm is None
                 else np.asarray(gm, bool).reshape(-1, 1).astype(np.int32))
            self.groups.add(name)
            self.cache[name] = a
            return a
        a = self.geo.get(self.cls, name)
        if a is None and name == "P" and self.cls == VERTEX:
            # pcg113: as in VEX, @P in a vertex wrangle is the position of the vertex's point (read-only here)
            a = np.asarray(self.geo.get(POINT, "P"), np.float64)[np.asarray(self.geo.vertex_point)].reshape(-1, 3)
            self.derived.add(name)
            self.cache[name] = a
            return a
        if a is None and name == "P" and self.cls == PRIM:
            # As in VEX: @P in prim context is the face centre (prims have no P attribute).
            # Read-only -- skipped on write-back (see flush), so no prim attribute called P appears out of nowhere
            from .ops import prim_centers
            a = np.asarray(prim_centers(self.geo), np.float64).reshape(-1, 3)
            self.derived.add(name)
            self.cache[name] = a
            return a
        if a is None:
            c = self.hints.get(name, (3, np.float32))
            a = np.zeros((self.n, c[0]), c[1])
        else:
            a = np.array(a, copy=True)              # COW
            if a.dtype.kind == "U":
                # Strings use object arrays in Wrangle: in-place assignment into fixed-length <U truncates to the old width
                # (it used to be a fixed <U64, cutting anything over 64 chars). Narrowed to the actual longest on write-back
                a = a.astype(object)
        self.cache[name] = a
        return a

    def __setitem__(self, name, value):
        v = np.asarray(value)
        if v.ndim == 0:
            c, dt = self.hints.get(name, (1, np.float32))
            if v.dtype.kind in "UO":           # scalar string, do not convert to float
                c, dt = 1, np.dtype(object)
            v = np.broadcast_to(v, (self.n, c)).astype(dt)
        elif v.ndim == 1:
            v = v.reshape(-1, 1) if len(v) == self.n else \
                np.tile(v, (self.n, 1))
        elif v.ndim == 2 and v.shape[0] == 1 and self.n != 1:
            # @Cd = set(1, 0, 0): a constant vector is (1,3), tiled over every element
            v = np.broadcast_to(v, (self.n, v.shape[1]))
        if v.dtype.kind == "U":
            v = v.astype(object)
        if name in self.hints and v.ndim == 2:
            # pcg113: a typed write (f@ i@ v@ s@ 2@ 3@ 4@ p@) converts the value to the declared type, as in VEX:
            # i@k = @P.x * 10 is an integer attribute (truncated), f@a = @ptnum % 2 a float one, v@c = 0.5 a
            # vector (0.5, 0.5, 0.5). Before, only a missing attribute read through the prefix got the type.
            c, dt = self.hints[name]
            if v.shape[1] != c:
                if v.shape[1] == 1:
                    v = np.repeat(v, c, axis=1)
                else:
                    raise ValueError(f"{name}: declared with {c} component(s) but assigned {v.shape[1]}")
            if np.dtype(dt).kind == "O":
                v = v.astype(object) if v.dtype.kind in "UO" else np.array(
                    [[("%g" % x) if isinstance(x, (float, np.floating)) else str(x) for x in r] for r in v], object)
            elif v.dtype.kind in "UO":
                raise ValueError(f"{name}: declared as a number but assigned text")
            else:
                v = v.astype(dt)
        if name.startswith("group_") and self.cls != DETAIL:
            self.groups.add(name)
        self.cache[name] = np.ascontiguousarray(v)
        self.dirty.add(name)

    def flush(self, geo):
        # Everything in cache is a copy (__getitem__ already did COW); unconditional write-back is safest:
        # the user may have written in-place edits like @P[:, 1] += 1, and __setitem__ cannot be intercepted.
        for k, v in self.cache.items():
            if k in self.derived and k not in self.dirty:
                continue
            if k in self.groups:
                # @group_xxx is a group, not an attribute: non-zero = member. Only written when the code assigned it
                if k in self.dirty:
                    geo.set_group(self.cls, k[6:], np.asarray(v).reshape(len(v), -1)[:, 0].astype(bool))
                continue
            geo.set(self.cls, k, _ustr(v) if v.dtype.kind == "O" else v, owned=True)


def _transpile(src: str):
    """Replace @attr syntax with _A["attr"] and collect type hints."""
    hints = {}

    def sub(m):
        typ, name, comp = m.group(1), m.group(2), m.group(3)
        if name in ("ptnum", "primnum", "vtxnum", "elemnum"):
            return "_ELEMNUM"
        if name in ("numpt", "numprim", "numvtx", "numelem"):
            return "_NUMELEM"
        if typ:
            hints[name] = (_TYPE_C[typ], _TYPE_DT[typ])
        expr = f'_A["{name}"]'
        if comp:
            expr += f"[:, {_COMP[comp]}]"
        return expr

    return _ATTR_RE.sub(sub, src), hints


def _hash01(x, salt=0):
    """
    VEX-style rand: the input is a **seed**, not a count. rand(@ptnum) gives each point a
    deterministic random number; the same input always gives the same output -- exactly the property procedural work needs.

    numpy's rng.random(n) means "generate n random numbers", completely different semantics, and
    rand(@ptnum) would be passed in as a shape and fail outright. This uses splitmix64-style
    bit mixing computed by hand: per element, stateless, vectorisable.
    """
    a = np.asarray(x, np.float64)
    with np.errstate(over="ignore"):
        u = (a * 1000003.0).astype(np.int64).astype(np.uint64)
        # Overflow is part of the bit mixing, not an error -- so the whole block runs inside errstate
        u = u + np.uint64(int(salt) & 0xFFFFFFFF) * np.uint64(0x9E3779B97F4A7C15)
        u ^= u >> np.uint64(33)
        u *= np.uint64(0xFF51AFD7ED558CCD)
        u ^= u >> np.uint64(33)
        u *= np.uint64(0xC4CEB9FE1A85EC53)
        u ^= u >> np.uint64(33)
    r = (u >> np.uint64(11)).astype(np.float64) / float(1 << 53)
    if np.isscalar(x) or a.ndim == 0:
        return float(r)
    # pcg111: keep the input's wrapper class. rand(@id) on an (N,1) attribute column came back as a plain (N,1)
    # array, and plain (N,1) + noise(...)'s (N,) broadcasts to N x N (hundreds of GB on an image) instead of per row.
    return r.view(type(x)) if isinstance(x, (Vec, Col1)) else r


_PERM = np.array([151,160,137,91,90,15,131,13,201,95,96,53,194,233,7,225,140,36,
 103,30,69,142,8,99,37,240,21,10,23,190,6,148,247,120,234,75,0,26,197,62,94,252,
 219,203,117,35,11,32,57,177,33,88,237,149,56,87,174,20,125,136,171,168,68,175,
 74,165,71,134,139,48,27,166,77,146,158,231,83,111,229,122,60,211,133,230,220,
 105,92,41,55,46,245,40,244,102,143,54,65,25,63,161,1,216,80,73,209,76,132,187,
 208,89,18,169,200,196,135,130,116,188,159,86,164,100,109,198,173,186,3,64,52,
 217,226,250,124,123,5,202,38,147,118,126,255,82,85,212,207,206,59,227,47,16,58,
 17,182,189,28,42,223,183,170,213,119,248,152,2,44,154,163,70,221,153,101,155,
 167,43,172,9,129,22,39,253,19,98,108,110,79,113,224,232,178,185,112,104,218,
 246,97,228,251,34,242,193,238,210,144,12,191,179,162,241,81,51,145,235,249,14,
 239,107,49,192,214,31,181,199,106,157,184,84,204,176,115,121,50,45,127,4,150,
 254,138,236,205,93,222,114,67,29,24,72,243,141,128,195,78,66,215,61,156,180],
 np.int64)
_P512 = np.concatenate([_PERM, _PERM])


def _fade(t):
    return t * t * t * (t * (t * 6 - 15) + 10)


def _grad3(h, x, y, z):
    h = h & 15
    u = np.where(h < 8, x, y)
    v = np.where(h < 4, y, np.where((h == 12) | (h == 14), x, z))
    return (np.where(h & 1 == 0, u, -u) + np.where(h & 2 == 0, v, -v))


def perlin3(p):
    """
    Classic Perlin noise, vectorised. Returns [0,1], consistent with VEX's noise()
    (VEX is 0..1, not -1..1 -- taking a standard implementation's output directly would be off by a remap).
    """
    # pcg111: a copy -- the fractional parts below are taken in place, and with asarray noise(@P) in a COP Wrangle
    # overwrote the P layer with its fractional part (the layer cache hands out the array itself)
    p = np.atleast_2d(np.array(p, np.float64))
    if p.shape[-1] == 1:
        p = np.repeat(p, 3, -1)
    x, y, z = p[..., 0], p[..., 1], p[..., 2]
    X = np.floor(x).astype(np.int64) & 255
    Y = np.floor(y).astype(np.int64) & 255
    Z = np.floor(z).astype(np.int64) & 255
    x -= np.floor(x); y -= np.floor(y); z -= np.floor(z)
    u, v, w = _fade(x), _fade(y), _fade(z)
    A = _P512[X] + Y; AA = _P512[A] + Z; AB = _P512[A + 1] + Z
    B = _P512[X + 1] + Y; BA = _P512[B] + Z; BB = _P512[B + 1] + Z
    lerp = lambda t, a, b: a + t * (b - a)          # noqa: E731
    res = lerp(w, lerp(v, lerp(u, _grad3(_P512[AA], x, y, z),
                                  _grad3(_P512[BA], x - 1, y, z)),
                          lerp(u, _grad3(_P512[AB], x, y - 1, z),
                                  _grad3(_P512[BB], x - 1, y - 1, z))),
                  lerp(v, lerp(u, _grad3(_P512[AA + 1], x, y, z - 1),
                                  _grad3(_P512[BA + 1], x - 1, y, z - 1)),
                          lerp(u, _grad3(_P512[AB + 1], x, y - 1, z - 1),
                                  _grad3(_P512[BB + 1], x - 1, y - 1, z - 1))))
    return res * 0.5 + 0.5


def perlin3_periodic(p, period):
    """
    pnoise(p, period): Perlin noise that repeats every `period` units along each axis, like VEX's pnoise().
    period is a number (same on all axes) or a 3-vector of integers; 0 on an axis = not periodic there.
    Lattice corners are wrapped modulo the period before hashing, so with period 4, pnoise(p) == pnoise(p + 4)
    exactly -- the tool for seamless textures: pnoise(set(@u * 8, @v * 8, s), 8) tiles on all four sides.
    Returns [0,1] like noise(); with no wrapping (period 0) it equals noise() bit for bit.
    """
    p = np.atleast_2d(np.asarray(p, np.float64))
    if p.shape[-1] == 1:
        p = np.repeat(p, 3, -1)
    per = np.asarray(period, np.float64).reshape(-1)
    per = np.broadcast_to(per if per.size in (1, 3) else per[:1], (3,))
    per = np.maximum(np.rint(per), 0).astype(np.int64)
    fl = [np.floor(p[..., k]).astype(np.int64) for k in range(3)]
    fr = [p[..., k] - fl[k] for k in range(3)]

    def wrap(i, k):
        return (i % per[k] if per[k] > 0 else i) & 255

    X0, X1 = wrap(fl[0], 0), wrap(fl[0] + 1, 0)
    Y0, Y1 = wrap(fl[1], 1), wrap(fl[1] + 1, 1)
    Z0, Z1 = wrap(fl[2], 2), wrap(fl[2] + 1, 2)
    x, y, z = fr
    u, v, w = _fade(x), _fade(y), _fade(z)

    def h(X, Y, Z):
        return _P512[_P512[_P512[X] + Y] + Z]

    lerp = lambda t, a, b: a + t * (b - a)          # noqa: E731
    res = lerp(w, lerp(v, lerp(u, _grad3(h(X0, Y0, Z0), x, y, z),
                                  _grad3(h(X1, Y0, Z0), x - 1, y, z)),
                          lerp(u, _grad3(h(X0, Y1, Z0), x, y - 1, z),
                                  _grad3(h(X1, Y1, Z0), x - 1, y - 1, z))),
                  lerp(v, lerp(u, _grad3(h(X0, Y0, Z1), x, y, z - 1),
                                  _grad3(h(X1, Y0, Z1), x - 1, y, z - 1)),
                          lerp(u, _grad3(h(X0, Y1, Z1), x, y - 1, z - 1),
                                  _grad3(h(X1, Y1, Z1), x - 1, y - 1, z - 1))))
    return res * 0.5 + 0.5


class Vec(np.ndarray):
    """
    ndarray with .x/.y/.z/.w.

    The translator only expands `@attr.x` into a subscript; it cannot handle `.x` on ordinary expressions --
    yet in VEX forms like getbbox_size().x and point("P", i).z are very common.
    Having vector-returning functions all return this subclass makes `.x` work everywhere,
    without changing the translator's regex (which could easily hit normal attribute access like np.floor).
    """
    x = property(lambda self: np.asarray(self)[..., 0])
    y = property(lambda self: np.asarray(self)[..., 1])
    z = property(lambda self: np.asarray(self)[..., 2])
    w = property(lambda self: np.asarray(self)[..., 3])

    # ── broadcasting per-element scalar × attribute column ───────────────────────────────────
    # Attributes read as (N, C), while @P.y, rand(@ptnum), length(@P) -- "one number per element" --
    # are (N,). numpy broadcasting aligns from the **last dimension**: (N,3) × (N,) fails outright,
    # (N,1) × (N,) is worse -- it silently broadcasts to N×N (80 GB for 100k points).
    # Yet {1,0,0} * @P.y, @pscale * @P.x, lerp(a, b, @P.y) are the most common forms in VEX,
    # so 1D "per-element scalars" are stood up as (N,1) before computing; rules in _bcast.
    def __array_ufunc__(self, ufunc, method, *inputs, out=None, **kw):
        return _bcast(ufunc, method, inputs, out, kw)

    def __getitem__(self, key):
        r = np.ndarray.__getitem__(self, key)
        # taking a component ([:, 1], [..., 0]) gives "one number per element", not a vector
        if isinstance(key, tuple) and key and isinstance(
                key[-1], (int, np.integer)) and isinstance(r, np.ndarray):
            return r.view(Col1) if r.ndim == 1 else r.view(np.ndarray)
        return r

    def __setitem__(self, key, value):
        try:
            np.ndarray.__setitem__(self, key, value)
        except ValueError:
            # @P.y = @pscale * 2: the right side is (N,1), the left component slice is (N,)
            v = np.asarray(value)
            if v.ndim == 2 and v.shape[1] == 1:
                np.ndarray.__setitem__(self, key, v[:, 0])
            else:
                raise


class Col1(np.ndarray):
    """
    1D "one number per element" (a component like @P.x, a flattened single-component attribute). Uses the same
    broadcasting rules as Vec; it is a separate class for **in-place operations**: in @P.y -= @h the left side is an (N,) slice,
    and the right @h is (N,1) -- if neither side is a Vec, numpy gives no chance to step in.
    """
    def __array_ufunc__(self, ufunc, method, *inputs, out=None, **kw):
        return _bcast(ufunc, method, inputs, out, kw)


def _bcast(ufunc, method, inputs, out, kw):
    """
    All ufuncs involving Vec / Col1 go through here.
      · A 1D array that is not a Vec = per-element scalar; against a 2D (R, C) operand, if its length equals R
        (or that 2D array has only one row -- a constant vector made by set(...)) it is stood up as (R,1).
      · A 1D Vec is **one vector** (point("P", 0), getbbox_size()); multiplied with a per-element scalar
        the scalar is stood up the same way: getbbox_size() * @P.x -> (N,3).
      · Writing in place into a 1D slice goes the other way: (N,1) is flattened to (N,).
    """
    R = max((a.shape[0] for a in inputs
             if isinstance(a, np.ndarray) and a.ndim == 2), default=0)
    flat = (out is not None and len(out) == 1
            and isinstance(out[0], np.ndarray) and out[0].ndim == 1)
    vec1 = any(isinstance(a, Vec) and a.ndim == 1 for a in inputs)
    args = []
    for a in inputs:
        if isinstance(a, np.ndarray):
            is_vec1 = isinstance(a, Vec) and a.ndim == 1
            a = a.view(np.ndarray)
            if flat:
                if a.ndim == 2 and a.shape[1] == 1 and a.shape[0] == len(out[0]):
                    a = a[:, 0]
            elif (method == "__call__" and a.ndim == 1 and not is_vec1
                  and len(a) > 1 and ((R and (len(a) == R or R == 1))
                                      or (not R and vec1))):
                a = a.reshape(-1, 1)
        args.append(a)
    if out is not None:
        kw["out"] = tuple(o.view(np.ndarray) if isinstance(o, np.ndarray) else o
                          for o in out)
    r = getattr(ufunc, method)(*args, **kw)
    if out is not None:
        return out[0] if len(out) == 1 else out
    return _wrap(r, vec1)


def _wrap(r, vec1=False):
    if isinstance(r, tuple):
        return tuple(_wrap(x, vec1) for x in r)
    if not isinstance(r, np.ndarray):
        return r
    if r.ndim == 2:
        return r.view(Vec)
    if r.ndim == 1:
        return r.view(Vec if vec1 else Col1)
    return r.view(np.ndarray)


def _V(a):
    a = np.asarray(a, np.float64)
    return a.view(Vec) if a.ndim and a.shape[-1] >= 2 else a


def _cols(a):
    """
    Attribute columns (N, C) are wrapped as Vec (also for C = 1, so @pscale * @P.x does not become N×N).
    The flattened 1D @value of Volume Wrangle need not be wrapped as Col1: when it meets (N,1) the other side is a Vec,
    so the ufunc is still dispatched to Vec's rules (confirmed by mutation testing: same result wrapped or not).
    """
    if isinstance(a, np.ndarray) and a.ndim == 2 and a.dtype.kind in "fiub":
        return a.view(Vec)
    return a


def _where(c, a, b):
    """where(cond, a, b): when cond is (N,) and a / b are (N,3), selects by row (no error, no N×N broadcast)."""
    xs = [np.asanyarray(x) for x in (c, a, b)]
    vec1 = any(isinstance(x, Vec) and x.ndim == 1 for x in xs)
    R = max((x.shape[0] for x in xs if x.ndim == 2), default=0)
    if R:
        xs = [x.reshape(-1, 1) if x.ndim == 1 and len(x) > 1 and
              (len(x) == R or R == 1) and not isinstance(x, Vec) else x
              for x in xs]
    return _wrap(np.where(*[x.view(np.ndarray) for x in xs]), vec1)


def _py(v):
    """numpy scalar -> Python scalar (%d needs an integer: floats with integer values are also converted to int)."""
    v = np.asarray(v)
    if v.dtype.kind in "U S O":
        return str(v)
    x = v.item()
    if isinstance(x, float) and x.is_integer():
        return int(x)
    return x


class _Const(np.ndarray):
    """
    Return value of chv(): a constant vector. Arithmetic is exactly like an ordinary numpy array (@P += chv("off") works as before),
    it just adds VEX-style .x .y .z .w -- chv("dir").y. Not a Vec: a 1D Vec operating with (N,3)
    follows Vec's own rules and raises a dimension error.
    """
    x = property(lambda self: float(np.asarray(self)[0]))
    y = property(lambda self: float(np.asarray(self)[1]))
    z = property(lambda self: float(np.asarray(self)[2]))
    w = property(lambda self: float(np.asarray(self)[3]))


def ch_funcs(ch_params=None):
    """
    The ch() family: reads custom parameters on the node (spare parameters, passed in from the frontend pcg_spare.js via ch_params).
    For a vector parameter pos the frontend also writes components posx posy posz using Houdini naming, so ch("posx") works too;
    ch("pos") on a vector returns the first component (Houdini's ch() on a vector parameter also returns the first).
    Shared by the geometry / volume / COP Wrangles.
    """
    chd = dict(ch_params or {})

    def _ch(name, default=0.0):
        v = chd.get(str(name), default)
        if isinstance(v, (list, tuple)):
            v = v[0] if v else default
        if isinstance(v, bool):
            return float(v)
        try:
            return float(v)
        except (TypeError, ValueError):
            return float(default)

    def _chv(name, d=(0.0, 0.0, 0.0)):
        v = chd.get(str(name), d)
        a = np.asarray(v if isinstance(v, (list, tuple)) else [v] * 3, np.float64).reshape(-1)
        return a.view(_Const)           # ordinary array (operates as before), plus .x .y .z .w

    return {"ch": _ch, "chf": _ch, "chv": _chv,
            "chi": lambda name, default=0: int(round(_ch(name, default))),
            "chs": lambda name, default="": str(chd.get(str(name), default))}


def _namespace(seed=0, ch_params=None, geo=None, inputs=None):
    import math
    ns = {"np": np, "math": math, "__builtins__": {
        "abs": abs, "min": min, "max": max, "range": range, "len": len,
        "float": float, "int": int, "bool": bool, "print": print,
        "enumerate": enumerate, "zip": zip, "sum": sum, "round": round,
        "str": str, "True": True, "False": False, "None": None,
    }}
    # ★ min / max / abs must be overridden with per-element versions. Python's built-in min(a, b) on two
    #   arrays does a **whole-array comparison** and returns one of the arrays unchanged -- no error, completely wrong result,
    #   and min(@P.x, 0) is one of the most common forms in VEX.
    ns["__builtins__"].update(min=np.minimum, max=np.maximum, abs=np.abs)

    # pcg113: numpy imports some of its own modules lazily from C (the first ndarray.max() in a process imports
    # numpy._core._methods), and such an import looks __import__ up in the builtins of the running Python frame --
    # the wrangle's. Without one it failed with "KeyError: '__import__'" on the first @P.y.max() after a restart.
    # Only numpy's own modules can be imported this way; the code guard rejects writing __import__ in the code.
    def _numpy_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0 and (name == "numpy" or name.startswith("numpy.")):
            return __import__(name, globals, locals, fromlist, level)
        raise ImportError(f"import of '{name}' is not available in Wrangle code")
    ns["__builtins__"]["__import__"] = _numpy_import

    # pcg113: round() on a column -- Python's round() has no array version and failed with "Col1 doesn't define
    # __round__". Halves round away from zero, as VEX's rint / round do (numpy's round is to even)
    def _round(x, nd=0):
        f = 10.0 ** nd
        if np.isscalar(x):
            v = math.copysign(math.floor(abs(float(x)) * f + 0.5), float(x)) / f
            return int(v) if nd == 0 else v
        a = np.asanyarray(x, np.float64) * f
        return np.sign(a) * np.floor(np.abs(a) + 0.5) / f
    ns["__builtins__"]["round"] = _round

    def _fit(x, a, b, c, d):
        span = np.where(np.asarray(b) - np.asarray(a) == 0, 1e-9,
                        np.asarray(b) - np.asarray(a))
        lo, hi = np.minimum(a, b), np.maximum(a, b)
        return c + (np.clip(x, lo, hi) - a) / span * (d - c)

    def _smoothstep(a, b, x):
        # asanyarray: keeps Vec / Col1 so the broadcasting rules below apply
        t = np.clip((np.asanyarray(x, np.float64) - a) / ((b - a) or 1e-9), 0, 1)
        return t * t * (3 - 2 * t)

    def _vec(*a):
        """set(x,y,z) / vector(...): combine scalars or array columns into (N,C)."""
        cols = [np.asarray(x, np.float64) for x in a]
        n = max((c.size for c in cols), default=1)
        return _V(np.stack([np.broadcast_to(c, (n,)) if c.ndim <= 1 else c[..., 0]
                            for c in cols], -1))

    srcs = list(inputs) if inputs else [geo]

    def _pick(args):
        """
        The first argument of VEX's read functions is the input index: point(0, "P", i).
        Both forms are accepted here: an integer is taken as the input index, otherwise the first input is used --
        a single input is by far the most common case, and writing 0 every time is too verbose.
        """
        if args and isinstance(args[0], (int, np.integer)) and not \
                isinstance(args[0], bool):
            i = int(args[0])
            g = srcs[i] if 0 <= i < len(srcs) else None
            return g, args[1:]
        return srcs[0] if srcs else None, args

    def _attr(cls_, *args):
        """point(["input",] "P", i) / prim("class", i) / detail("x")."""
        g, rest = _pick(args)
        if g is None or not rest:
            return 0.0
        name = rest[0]
        idx = rest[1] if len(rest) > 1 else None
        a = g.get(cls_, name)
        if a is None:
            return 0.0
        v = np.asarray(a)
        if idx is None:
            if not len(v):
                return 0.0
            return v[0, 0] if v.shape[-1] == 1 else _V(v[0])
        i = np.asarray(idx, np.int64) % max(len(v), 1)
        out = v[i]
        return out[..., 0] if out.shape[-1] == 1 else _V(out)

    def _bbox(*args):
        g, _ = _pick(args)
        if g is None or not g.npoints:
            return np.zeros(3), np.zeros(3)
        mn, mx = g.bbox()
        return np.asarray(mn, np.float64), np.asarray(mx, np.float64)

    def _count(kind):
        def f(*args):
            g, _ = _pick(args)
            return 0 if g is None else getattr(g, kind)
        return f

    def _sprintf(fmt, *args):
        """
        VEX's sprintf: when arguments contain per-element arrays, formats row by row and returns an (N,1) string column
        (s@name = sprintf("UCX_%s_%02d", @asset, @piece) -- one name per element).
        Formatting follows Python's % rules (%d %02d %s %.3f same as VEX / C).
        """
        cols = [np.asarray(a) for a in args]
        n = max((len(c) for c in cols if c.ndim >= 1), default=0)
        if n == 0:
            return str(fmt) % tuple(_py(c) for c in cols)

        def cell(c, i):
            if c.ndim == 0:
                return _py(c)
            v = c[i]
            return _py(v[0] if np.ndim(v) else v)
        out = [str(fmt) % tuple(cell(c, i) for c in cols) for i in range(n)]
        return np.asarray(out, dtype=object).astype(str).reshape(-1, 1)

    ns.update(
        sprintf=_sprintf,
        itoa=lambda x: _sprintf("%d", x),
        # trigonometric / exponential
        sin=np.sin, cos=np.cos, tan=np.tan, atan2=np.arctan2,
        asin=np.arcsin, acos=np.arccos, atan=np.arctan,
        sinh=np.sinh, cosh=np.cosh, tanh=np.tanh,
        sqrt=np.sqrt, cbrt=np.cbrt, pow=np.power, exp=np.exp,
        log=np.log, log10=np.log10,
        # rounding / sign
        floor=np.floor, ceil=np.ceil, rint=np.rint, trunc=np.trunc,
        sign=np.sign, frac=lambda x: x - np.floor(x),
        # range mapping
        clamp=lambda x, a, b: np.clip(x, a, b),
        fit=_fit, fit01=lambda x, c, d: c + np.clip(x, 0, 1) * (d - c),
        fit10=lambda x, c, d: d + np.clip(x, 0, 1) * (c - d),
        efit=lambda x, a, b, c, d: c + (x - a) / ((b - a) or 1e-9) * (d - c),
        lerp=lambda a, b, t: a + (b - a) * t,
        smooth=_smoothstep, smoothstep=_smoothstep,
        # vectors
        length=lambda v: np.linalg.norm(np.atleast_2d(v), axis=-1),
        length2=lambda v: (np.atleast_2d(v) ** 2).sum(-1),
        distance=lambda a, b: np.linalg.norm(
            np.atleast_2d(a) - np.atleast_2d(b), axis=-1),
        distance2=lambda a, b: ((np.atleast_2d(a) - np.atleast_2d(b)) ** 2).sum(-1),
        normalize=lambda v: _V(v / np.maximum(
            np.linalg.norm(v, axis=-1, keepdims=True), 1e-9)),
        cross=lambda a, b: _V(np.cross(a, b)),
        dot=lambda a, b: (np.atleast_2d(a) * np.atleast_2d(b)).sum(-1),
        set=_vec, vector=_vec, vector2=_vec, vector4=_vec,
        radians=np.radians, degrees=np.degrees,
        where=_where, PI=np.pi,
        # noise
        noise=perlin3,
        pnoise=perlin3_periodic,
        vnoise=lambda p: _V(np.stack(
            [perlin3(np.asarray(p, np.float64)),
             perlin3(np.asarray(p, np.float64) + 31.7),
             perlin3(np.asarray(p, np.float64) + 77.3)], -1)),
        # geometry queries
        getbbox_min=lambda *a: _V(_bbox(*a)[0]),
        getbbox_max=lambda *a: _V(_bbox(*a)[1]),
        getbbox_size=lambda *a: _V(_bbox(*a)[1] - _bbox(*a)[0]),
        getbbox_center=lambda *a: _V((_bbox(*a)[1] + _bbox(*a)[0]) * 0.5),
        point=lambda *a: _attr(POINT, *a),
        vertex=lambda *a: _attr(VERTEX, *a),
        prim=lambda *a: _attr(PRIM, *a),
        detail=lambda *a: _attr(DETAIL, *a),
        npoints=_count("npoints"), nprims=_count("nprims"),
        nvertices=_count("nvertices"),
        ninputs=lambda *a: len([g for g in srcs if g is not None]),
    )
    return ns


def run_wrangle(geo: Geometry, code: str, cls: str = POINT, seed: int = 0,
                extra: dict | None = None, group=None,
                ch_params: dict | None = None,
                inputs: list | None = None, squeeze=()) -> Geometry:
    """
    Run wrangle code on the cls elements of geo and return a new Geometry.

    With a non-empty group only selected elements are affected. It is implemented as "compute everything, then restore unselected rows" --
    equivalent for per-element operations, and cleaner than stuffing masks all over the code. Note the cost: unselected elements
    are computed too, so if the code has pitfalls like division by zero, they will still blow up.
    """
    from . import groups as _grp
    g = geo.copy()
    mask = _grp.resolve(geo, cls, group)
    restore = None if mask.all() else ~mask
    py, hints = _transpile(code)

    bind = _Bind(g, cls)
    bind.hints = hints
    bind.squeeze = set(squeeze)
    n = bind.n

    ns = _namespace(seed, ch_params, geo, inputs or [geo])
    ns["_A"] = bind
    ns["_ELEMNUM"] = np.arange(n, dtype=np.int32)
    ns["_NUMELEM"] = n
    # ch("name") reads tweakable parameters on the panel. The frontend scans the code for ch(...) and creates widgets automatically;
    # values come in via a hidden JSON string -- no input ports are added to the node dynamically, which would
    # misalign parameters when a workflow is restored (litegraph refills widgets_values by index).
    ns.update(ch_funcs(ch_params))
    ns["seed"] = int(seed)
    ns["rand"] = lambda x, _s=int(seed): _hash01(x, _s)
    if extra:
        ns.update(extra)

    check_code(py, "Wrangle")
    try:
        exec(compile(py, "<wrangle>", "exec"), ns)
    except Exception as e:
        raise RuntimeError(
            f"Wrangle failed: {type(e).__name__}: {e}\n"
            f"--- translated Python ---\n{py}") from e

    if restore is not None:
        # Restore unselected rows: if they had a value, restore it; if not (the attribute was created this time)
        # fill the default value. The latter is crucial -- the code runs as a whole, so without filling, the new attribute would be written on
        # all elements, and the group would have no effect.
        for k, v in bind.cache.items():
            if k in bind.groups:
                gm = geo.get_group(cls, k[6:])
                old = None if gm is None else np.asarray(gm, bool).reshape(-1, 1).astype(v.dtype)
            else:
                old = geo.get(cls, k)
            if old is not None and old.shape == v.shape:
                v[restore] = old[restore]
            else:
                v[restore] = "" if v.dtype.kind in "UO" else 0
    bind.flush(g)
    return g


def eval_expr(geo, expr: str, cls=POINT):
    """
    Evaluate an expression in wrangle syntax (without writing back to the geometry), for things like Sort keys.

    Implemented as "run a wrangle, write the result to a temporary attribute and read it back". It looks roundabout, but is more reliable than a
    separate evaluation path -- attribute binding, @ translation and group handling all reuse the same code,
    so there is no "works in wrangle, different semantics in the sort expression" divergence.
    """
    if not str(expr or "").strip():
        return None
    tmp = "__sortkey__"
    try:
        g = run_wrangle(geo, f"f@{tmp} = ({str(expr).strip()})", cls)
    except Exception:
        return None
    a = g.get(cls, tmp)
    if a is None:
        return None
    return np.asarray(a, np.float64).reshape(-1)

def eval_value(geo, expr, cls=POINT, ncomp=None, group=None, broadcast=True):
    """
    **Evaluate per element** in wrangle syntax, returning an (N, C) array without writing back to the geometry.

    Implemented by running a wrangle, but the result is caught by an injected _capture and **not written as an attribute**:
    a constant expression like `set(0,0,0)` has only one row, and writing it as an attribute would first hit the attribute row-count check,
    reporting "expected 500 rows, got 1" -- nobody could guess from that what to change.
    Once caught, constants are broadcast to N rows, and only a wrong shape produces an actionable message.

    If ncomp is given the column count is validated (error on mismatch); otherwise the expression's own column count is returned.

    broadcast governs what happens when "a scalar was given but ncomp components are wanted":
        True   spread as (v, v, v) following VEX convention -- when Attribute Create writes a vector,
               a single `@ptnum * 0.1` with three equal components is what is wanted
        False  raise an error -- Attribute Noise's VEXpression wants a **sample position**;
               spreading a scalar to a point on the diagonal would silently sample a degenerate 1D noise,
               so better to fail and say clearly that set(x, y, z) is needed
    """
    n = geo.count(cls)
    got = {}

    def _capture(v):
        got["v"] = v
        return np.zeros((n, 3))

    run_wrangle(geo, f"v@__evaltmp__ = _capture(({str(expr).strip()}));",
                cls, extra={"_capture": _capture}, group=group)
    v = np.asarray(got.get("v"), np.float64)
    if v.ndim == 0:
        v = v.reshape(1, 1)
    elif v.ndim == 1:
        # 1D is ambiguous: length == element count means "one scalar per element", otherwise it is a constant vector
        v = v.reshape(-1, 1) if len(v) == n and n != ncomp else v.reshape(1, -1)
    if ncomp is not None and v.shape[1] != ncomp:
        if v.shape[1] == 1 and broadcast:
            v = np.repeat(v, ncomp, axis=1)
        else:
            hint = ("\n  Scalars are not spread here (spreading to (v, v, v) would degenerate along the diagonal); "
                    "build the components yourself, e.g. set(@P.x, 0, 0)."
                    if v.shape[1] == 1 and ncomp == 3 else "")
            raise ValueError(
                f"The expression gave {v.shape[1]} components, {'three' if ncomp == 3 else ncomp}"
                f" components are needed here.\n  Expression: {expr}{hint}")
    if v.shape[0] == 1:
        v = np.repeat(v, n, axis=0)
    if v.shape[0] != n:
        raise ValueError(
            f"The expression gave {v.shape[0]} rows, but {cls} has {n} elements.\n  Expression: {expr}")
    return v
