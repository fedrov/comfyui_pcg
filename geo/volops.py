"""
Dense volume editing: create an empty volume, blur, mix two volumes, resample, per-voxel expressions, SDF
dilate / erode / open / close / redistance. For how volumes are stored see volume.py (grid-point sampled, voxels in
prim_data["voxels"], shape (rz, ry, rx)).

━━ Which volumes (Volumes parameter)
Empty = all volume prims; numbers (space-separated) = the n-th volume (counting volumes only); names (may use * ?
wildcards, ^ to exclude) = matched against the prim attribute name.

━━ Blur
Gaussian: sigma = Radius / 2 (Radius is roughly "the visibly blurred range"); the kernel is cut at +-4 sigma on each axis
(cutting at +-3 sigma loses 2.7% of the variance, measurable in tests),
converted with each axis's own voxel size -- an anisotropic grid still gets a round blur in world space. Separable:
one 1D convolution per direction. Borders extend the edge value (no 0 is pulled in from outside, so SDF edges are not
dragged down). box: mean over +-Radius per axis. Iterations repeats it.
A blurred SDF is no longer a distance field (|∇| < 1); to use it as an SDF, follow with Reshape SDF's
redistance.
pcg100 s9: Houdini's Reduction (Maximum / Minimum / absolute Max/Min / Average / Median /
Sum / Sum of Absolute / Sum of Squares / RMS); the window is a cube of +-r voxels per axis, done axis by axis
(Median is also a per-axis approximation, per the docs); Override Border (Use Volume = Streak / Constant / Repeat)
and Blending (original × a + result × b). Reduction = filter is the two old modes above.

━━ Mix
B is first trilinearly sampled in world space onto A's grid (different grids are fine; points of A's grid outside B take
B's edge value). Operations:
  add / subtract / multiply / maximum / minimum / blend (linear interpolation by Factor) / copy_b
  union = min, intersect = max, difference = max(a, −b)  -- SDF booleans
  smooth_union / smooth_intersect / smooth_difference -- Quilez's polynomial smooth
      min: h = clamp(½ + ½(b − a)/k, 0, 1), smin = lerp(b, a, h) − k·h(1 − h).
      k is the transition width in world units; k -> 0 falls back to the hard boolean
The result is written on A's grid.

━━ Resample
Bounding box unchanged, new resolution: give a target resolution, or a voxel size (resolution computed from the bounding box), or
an overall scale factor. New grid points sample the old field trilinearly (or nearest) -- same bounding box, same grid-point
alignment (the end grid points sit on the bounding box corners).

━━ Wrangle
Reuses the full syntax of the geometry Wrangle (numpy vectorised; noise, sin, clamp... all available): each voxel
is treated as a point, @P is the grid point's world position, @value is the voxel value (read/write), @ix @iy @iz are integer indices.
@value / @ix... read as 1D (N,) (same as @P.x), so @value * sin(@P.x) works directly;
the other way round, multiplying with a vector is written @P * @value[:, None].
There is one extra function volsample(k, pos): trilinear sampling in world space on the k-th volume (or by name) in the same geometry
-- for bringing other volumes into the computation. Runs once per selected volume.

━━ Reshape SDF
  dilate  f − d (pushes the surface out by d)       erode  f + d (pulls it in)
  open    erode then dilate, redistance in between -- removes bumps and thin rods thinner than 2d
  close   dilate then erode, redistance in between -- fills gaps and small pits narrower than 2d
  redistance  only recompute the distance (restores |∇f| = 1 after blur, mix, wrangle)
Redistance: surface nets extracts the 0 isosurface, and the exact unsigned distance to that surface is computed on the same grid
(volume.signed_distance, same code as Convert); the sign is kept from the original field. Isosurface vertices are
averages of the edge crossings in a cell, not exactly on the true zero, so the redistanced field differs slightly from the true SDF (on a sphere
measured 0.11 voxel, measured in tests).
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, PRIM_VOLUME, is_string
from .volume import make_volume, volume_info, signed_distance, volume_to_polygons

BLUR_MODES = ("gaussian", "box")
# pcg100 s9: Houdini Volume Blur's Reduction (filter = the old Mode menu) and Override Border
BLUR_REDUCTIONS = ("filter", "maximum", "minimum", "max_abs", "min_abs", "average",
                   "median", "sum", "sum_abs", "sum_squares", "rms")
BLUR_BORDERS = ("use_volume", "constant", "repeat", "streak")
MIX_OPS = ("add", "subtract", "multiply", "maximum", "minimum", "blend",
           "copy_b", "union", "intersect", "difference", "smooth_union",
           "smooth_intersect", "smooth_difference",
           # pcg100 s9: the Houdini Volume Mix modes we were missing (may only be appended at the end)
           "diff", "divide", "invert", "clamp", "user")
RESAMPLE_MODES = ("resolution", "voxel_size", "scale")
INTERP = ("trilinear", "nearest")
RESHAPE_OPS = ("dilate", "erode", "open", "close", "redistance")
# pcg100 s9: VDB Smooth SDF's Operation
SMOOTH_SDF_OPS = ("mean_value", "median_value", "mean_curvature_flow", "laplacian_flow")


# ═══════════════════════════════════════════════════════════ common
def volume_prims(geo):
    return [i for i in range(geo.nprims) if geo.prim_type[i] == PRIM_VOLUME
            and geo.pdata(i, "voxels") is not None]


def select_volumes(geo, spec=""):
    """Volumes parameter -> list of volume prim indices."""
    from .ops import match_names
    vp = volume_prims(geo)
    if not vp:
        raise ValueError("Input has no volume prim (create one with Volume, or Convert to "
                         "volume_sdf / volume_fog)")
    s = str(spec).strip()
    if not s:
        return vp
    toks = s.split()
    if all(t.lstrip("-").isdigit() for t in toks):
        out = []
        for t in toks:
            k = int(t)
            if not -len(vp) <= k < len(vp):
                raise ValueError(f"Only {len(vp)} volumes, {k} is out of range")
            out.append(vp[k])
        return out
    nm = geo.get(PRIM, "name")
    if nm is None:
        raise ValueError(f"Volumes have no name attribute, cannot select by name '{s}'; use an index")
    names = [str(nm[i, 0]) for i in vp]
    hit = set(match_names(names, s))
    out = [i for i, n in zip(vp, names) if n in hit]
    if not out:
        raise ValueError(f"No volume matches the name '{s}'; existing: {names}")
    return out


def _grid(geo, i):
    from . import vdb as _v
    return _v.grid(geo, i)


def _grid_points(vox, origin, cell):
    rz, ry, rx = vox.shape[:3]
    Z, Y, X = np.meshgrid(np.arange(rz), np.arange(ry), np.arange(rx),
                          indexing="ij")
    return origin + np.stack([X, Y, Z], -1).reshape(-1, 3) * cell, (X, Y, Z)


def _sample(vox, origin, cell, Q, interp="trilinear"):
    from .attribsample import sample_volume
    v, _ = sample_volume(vox, origin, cell, Q, interp, "clamp")
    return v


def _set_vox(g, i, arr):
    # pcg106: through vdb.set_voxels, so a VDB's inactive voxels are reset to its background and a mask that no
    # longer fits the grid is dropped
    from . import vdb as _v
    _v.set_voxels(g, i, arr, mask="keep")


def _per_comp(fn, vox, *a, **kw):
    """Run a scalar-grid function on each component of a vector grid (pcg106)."""
    if np.ndim(vox) == 4:
        return np.stack([fn(np.asarray(vox[..., k]), *a, **kw) for k in range(vox.shape[3])], -1)
    return fn(vox, *a, **kw)


# ═══════════════════════════════════════════════════════════ create volume
def create_volume(res=(32, 32, 32), size=(1.0, 1.0, 1.0), center=(0, 0, 0),
                  value=0.0, fog=False, name="", bound=None, padding=0.0,
                  voxel_size=0.0):
    """
    Create a constant volume. With bound connected, its bounding box (expanded by padding) is the extent; when voxel_size > 0
    the resolution is extent / voxel size (end grid points on the box corners).
    """
    size = np.asarray(size, np.float64)
    center = np.asarray(center, np.float64)
    if bound is not None and bound.npoints:
        P = np.asarray(bound.get(POINT, "P"), np.float64)
        lo, hi = P.min(0) - float(padding), P.max(0) + float(padding)
        size = np.maximum(hi - lo, 1e-6)
        center = 0.5 * (lo + hi)
    if float(voxel_size) > 0:
        res = np.maximum(np.round(size / float(voxel_size)).astype(int) + 1, 2)
        size = (res - 1) * float(voxel_size)             # voxels are cubes
    g = make_volume(tuple(int(r) for r in res), tuple(size), tuple(center),
                    float(value), bool(fog))
    if str(name).strip():
        g.set_string(PRIM, "name", np.array([str(name).strip()]))
    return g


# ═══════════════════════════════════════════════════════════ Blur
def _pad(a, pad, border="streak", border_value=0.0):
    """
    Pad borders per Override Border: streak = extend the edge value, repeat = wrap to the other side,
    constant = everything outside is Border Value. Anything else (use_volume) uses streak (see blur's notes).
    """
    if border == "constant":
        return np.pad(a, pad, mode="constant", constant_values=float(border_value))
    if border == "repeat":
        return np.pad(a, pad, mode="wrap")
    return np.pad(a, pad, mode="edge")


def _conv1d(a, w, axis, border="streak", border_value=0.0):
    """1D convolution along axis, borders padded per border (default extends the edge value). w has odd length."""
    r = len(w) // 2
    if r == 0:
        return a * w[0]
    pad = [(0, 0)] * 3
    pad[axis] = (r, r)
    ap = _pad(a, pad, border, border_value)
    out = np.zeros_like(a)
    n = a.shape[axis]
    for k, wk in enumerate(w):
        sl = [slice(None)] * 3
        sl[axis] = slice(k, k + n)
        out += wk * ap[tuple(sl)]
    return out


def _reduce1d(a, r, axis, how, border, border_value):
    """
    Apply one reduction over the [−r, r] window along axis (Houdini Volume Blur's Reduction).
    The window is taken on the padded array, so with a constant border Sum also adds in Border Value --
    consistent with the docs' "voxels outside are treated as this value".
    """
    pad = [(0, 0)] * 3
    pad[axis] = (r, r)
    ap = _pad(a, pad, border, border_value)
    win = np.lib.stride_tricks.sliding_window_view(ap, 2 * r + 1, axis=axis)
    if how in ("maximum", "max_abs"):
        return win.max(-1)
    if how in ("minimum", "min_abs"):
        return win.min(-1)
    if how == "median":
        return np.median(win, -1)
    if how in ("sum", "sum_abs", "sum_squares"):
        return win.sum(-1)
    return win.mean(-1)                            # average, and rms's "mean of squares"


def _reduce_pass(a, rv, how, border, border_value):
    """
    One pass = one 1D reduction per axis (separable).
    · max / min / sum / average are separable by nature: three 1D passes = the result over a cube window;
    · the docs say Median "is not a true median, taken along each axis in turn" -- that is what is done here;
    · the Absolute / Squares variants transform values first and then reduce (the outside Border Value is transformed too),
      the last two axes just sum / take extrema of the partial results -- otherwise sum_squares would become a fourth power;
      rms = sqrt of the cube mean of squares.
    max_abs / min_abs output the absolute value itself (docs: "the largest absolute value"), without restoring the sign.
    rv is the integer voxel radius in array-axis order (z, y, x).
    """
    pre = {"max_abs": np.abs, "min_abs": np.abs, "sum_abs": np.abs,
           "sum_squares": np.square, "rms": np.square}.get(how)
    if pre is not None:
        border_value = float(pre(np.float64(border_value)))
        a = pre(a)
    for ax in range(3):
        a = _reduce1d(a, int(rv[ax]), ax, how, border, border_value)
    return np.sqrt(a) if how == "rms" else a


def blur(geo, radius=0.1, mode="gaussian", iterations=1, volumes="",
         reduction="filter", use_voxel_radius=False, voxel_radius=(1, 1, 1),
         border="use_volume", border_value=0.0, blend=False,
         original_amount=0.0, blurred_amount=1.0):
    """
    reduction = "filter": the pre-change behaviour (Mode gaussian / box). The rest is Houdini Volume
    Blur's Reduction menu; the window is a cube of +-r voxels per axis: r = round(Radius / that axis's voxel size)
    (capped at 5x the resolution, as the docs say), or with Use Voxel Radius the (x, y, z) voxel counts are given directly.
    Houdini's Average supports non-integer radii (with OpenCL off); here they are always rounded -- same as the old box.
    Iterations is Houdini's Passes.
    Override Border / Enable Blending also apply to filter. use_volume = use the volume's own border:
    our volumes have no per-volume border setting and sampling always clamps to the edge, so it equals streak (the pre-change behaviour).
    Blending: out = Original Amount × original + Blurred Amount × blurred.
    """
    if mode not in BLUR_MODES:
        raise ValueError(f"Mode must be one of {BLUR_MODES}")
    if reduction not in BLUR_REDUCTIONS:
        raise ValueError(f"Reduction must be one of {BLUR_REDUCTIONS}")
    if border not in BLUR_BORDERS:
        raise ValueError(f"Override Border must be one of {BLUR_BORDERS}")
    g = geo.copy()
    sel = select_volumes(geo, volumes)
    for i in sel:
        vox, origin, cell = _grid(geo, i)

        def one(comp):
            return _blur_one(comp, cell, radius, mode, iterations, reduction, use_voxel_radius,
                             voxel_radius, border, border_value, blend, original_amount,
                             blurred_amount)
        _set_vox(g, i, _per_comp(one, vox))
    return g


def _blur_one(vox, cell, radius, mode, iterations, reduction, use_voxel_radius, voxel_radius,
              border, border_value, blend, original_amount, blurred_amount):
    if True:
        a0 = a = np.asarray(vox, np.float64)
        if reduction != "filter":
            if use_voxel_radius:
                rv = [int(voxel_radius[2 - ax]) for ax in range(3)]
            else:
                rv = [int(np.round(float(radius) / float(cell[2 - ax]))) for ax in range(3)]
            rv = [min(max(r, 0), 5 * a.shape[ax]) for ax, r in enumerate(rv)]
            for _ in range(max(0, int(iterations))):
                a = _reduce_pass(a, rv, reduction, border, border_value)
        else:
            for _ in range(max(0, int(iterations))):
                for ax in range(3):                       # array axis: 0=z 1=y 2=x
                    c = float(cell[2 - ax])
                    if mode == "gaussian":
                        sig = float(radius) / 2.0 / c
                        r = int(np.ceil(4 * sig))   # cut at +-4 sigma: only 0.1% of the variance is lost
                        if r == 0 or sig <= 0:
                            continue
                        x = np.arange(-r, r + 1)
                        w = np.exp(-0.5 * (x / sig) ** 2)
                    else:
                        r = int(np.round(float(radius) / c))
                        if r == 0:
                            continue
                        w = np.ones(2 * r + 1)
                    a = _conv1d(a, w / w.sum(), ax, border, border_value)
        if blend:
            a = float(original_amount) * a0 + float(blurred_amount) * a
        return a


# ═══════════════════════════════════════════════════════════ Mix
def _smin(a, b, k):
    if k <= 0:
        return np.minimum(a, b)
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b * (1 - h) + a * h - k * h * (1 - h)


def _pair_volumes(geo_a, ia, geo_b, ib):
    """
    Which volume of B each volume of A pairs with (Houdini's Volume Mix pairs one to one, it does not just mix the first):
    if B has one with the same name, pair by name; if B has only one, pair everything with it; otherwise the j-th pairs with the j-th.
    Unpaired ones (B has fewer than A, and names do not match) return None, are left as they are and noted in the report.
    """
    def names(g, ids):
        nm = g.get(PRIM, "name")
        return [str(nm[i, 0]) if nm is not None else "" for i in ids]
    na, nb = names(geo_a, ia), names(geo_b, ib)
    out = []
    for j, (i, n) in enumerate(zip(ia, na)):
        if n and n in nb:
            out.append((i, ib[nb.index(n)]))
        elif len(ib) == 1:
            out.append((i, ib[0]))
        elif j < len(ib):
            out.append((i, ib[j]))
        else:
            out.append((i, None))
    return out


def _user_value(expr, a, b, oa, ca, ob, cb, bshape):
    """
    Mix Method = User: the Value expression is evaluated per voxel. Houdini's Value is an HScript expression using
    local variables X Y Z / IX IY IZ / V V2 / BBX... BBX2...; here the plugin's Wrangle syntax is used, mapped as:
        @P(= X Y Z)  @ix @iy @iz  @value(= V)  @value2(= V2)
        @bb (= BBX BBY BBZ, 0-1 position in A's bounding box)  @bb2 (in B's bounding box)
    V / V2 are A′ / B′ after Pre-Add / Pre-Mul (the docs say "A in the computation is set to A′").
    """
    from .wrangle import run_wrangle
    Q, (X, Y, Z) = _grid_points(a, oa, ca)
    tmp = Geometry.from_points(Q)
    tmp.set(POINT, "P", Q.astype(np.float64))
    tmp.set(POINT, "value", a.reshape(-1, 1))
    tmp.set(POINT, "value2", b.reshape(-1, 1))
    tmp.set(POINT, "ix", X.reshape(-1, 1).astype(np.int32))
    tmp.set(POINT, "iy", Y.reshape(-1, 1).astype(np.int32))
    tmp.set(POINT, "iz", Z.reshape(-1, 1).astype(np.int32))
    for nm, o, c, sh in (("bb", oa, ca, a.shape), ("bb2", ob, cb, bshape)):
        ext = np.asarray(c, np.float64) * (np.array(sh[::-1]) - 1)
        tmp.set(POINT, nm, (Q - o) / ext)         # resolution >= 2, size > 0, so ext is never 0
    out = run_wrangle(tmp, f"f@__mixv__ = ({str(expr).strip()});", POINT,
                      squeeze=("value", "value2", "ix", "iy", "iz"))
    v = out.get(POINT, "__mixv__")
    if v is None or is_string(v):
        raise ValueError("The User mode Value expression must produce a number")
    return np.asarray(v, np.float64).reshape(a.shape)


def _mix_one(va, oa, ca, vb, ob, cb, op, f, kk, adj=None):
    """
    adj (pcg100 s9): Houdini's Range / Value / Pre-Add·Mul / Post-Add·Mul / Clamp.
    Order per the docs: A′ = A·m + a, B′ = B·m + a -> Mix Method -> result·m + a -> Clamp.
    Each step runs only when it is not the identity (m = 1, a = 0 / toggle off) -- with defaults not even the bits of −0.0 are touched,
    bit-identical to the pre-change behaviour.
    """
    adj = adj or {}
    a = np.asarray(va, np.float64)
    if va.shape == vb.shape and np.allclose(oa, ob) and np.allclose(ca, cb):
        b = np.asarray(vb, np.float64)                    # same grid: no resampling needed
        same = True
    else:
        Q, _ = _grid_points(va, oa, ca)
        b = _sample(vb, ob, cb, Q).reshape(a.shape)
        same = False
    a = _affine(a, adj.get("dest_mul", 1.0), adj.get("dest_add", 0.0))
    b = _affine(b, adj.get("src_mul", 1.0), adj.get("src_add", 0.0))
    if op == "user":
        out = _user_value(adj.get("value", "0"), a, b, oa, ca, ob, cb, vb.shape)
    else:
        out = _mix_formula(op, a, b, f, kk, adj)
    out = _affine(out, adj.get("post_mul", 1.0), adj.get("post_add", 0.0))
    if adj.get("use_min"):
        out = np.maximum(out, float(adj["clamp_min"]))
    if adj.get("use_max"):
        out = np.minimum(out, float(adj["clamp_max"]))
    return out, same


def _affine(x, m, a):
    m, a = float(m), float(a)
    if m == 1.0 and a == 0.0:
        return x
    return x * m + a


def _mix_formula(op, a, b, f, kk, adj):
    if op == "divide":
        # the docs only say A / B; where B = 0 give 0 (no inf / nan; not specified by the docs)
        return np.divide(a, b, out=np.zeros_like(a), where=b != 0)
    if op == "clamp":
        return np.clip(a, float(adj.get("range_min", 0.0)), float(adj.get("range_max", 1.0)))
    out = {
        "add": lambda: a + b, "subtract": lambda: a - b,
        "multiply": lambda: a * b, "maximum": lambda: np.maximum(a, b),
        "minimum": lambda: np.minimum(a, b),
        "blend": lambda: a * (1 - f) + b * f, "copy_b": lambda: b,
        "union": lambda: np.minimum(a, b), "intersect": lambda: np.maximum(a, b),
        "difference": lambda: np.maximum(a, -b),
        "smooth_union": lambda: _smin(a, b, kk),
        "smooth_intersect": lambda: -_smin(-a, -b, kk),
        "smooth_difference": lambda: -_smin(-a, b, kk),
        "diff": lambda: np.abs(a - b), "invert": lambda: -a,
    }[op]()
    return out


def mix(geo_a, geo_b, op="add", factor=0.5, k=0.1, volume_a="", volume_b="",
        adjust=None):
    """
    **Every** selected volume in A is mixed with its paired volume in B; the result is on A's grid (pairing rules in
    _pair_volumes). Before pcg90 both sides only took the first match and the other volumes in A were left untouched.
    adjust (pcg100 s9): see _mix_one; None = old behaviour.
    """
    if op not in MIX_OPS:
        raise ValueError(f"Operation must be one of {MIX_OPS}")
    ia = select_volumes(geo_a, volume_a)
    ib = select_volumes(geo_b, volume_b)
    f, kk = float(factor), float(k)
    g = geo_a.copy()
    pairs, unmatched, resampled = [], [], []
    for i, j in _pair_volumes(geo_a, ia, geo_b, ib):
        if j is None:
            unmatched.append(int(i))
            continue
        va, oa, ca = _grid(geo_a, i)
        vb, ob, cb = _grid(geo_b, j)
        if np.ndim(va) == 4 or np.ndim(vb) == 4:
            # vector grids: component by component (a scalar B is used for every component of A)
            va4 = va if np.ndim(va) == 4 else va[..., None]
            vb4 = vb if np.ndim(vb) == 4 else np.repeat(vb[..., None], va4.shape[3], -1)
            comps = [_mix_one(va4[..., c], oa, ca, vb4[..., min(c, vb4.shape[3] - 1)], ob, cb,
                              op, f, kk, adjust) for c in range(va4.shape[3])]
            out = np.stack([c[0] for c in comps], -1)
            if np.ndim(va) == 3:
                out = out[..., 0]
            same = comps[0][1]
        else:
            out, same = _mix_one(va, oa, ca, vb, ob, cb, op, f, kk, adjust)
        _set_vox(g, i, out)
        pairs.append([int(i), int(j)])
        resampled.append(not same)
    if not pairs:
        raise ValueError("None of A's volumes can be paired with B (names do not match and B has more than one)")
    return g, {"volume_a": pairs[0][0], "volume_b": pairs[0][1],
               "resampled_b": resampled[0], "pairs": pairs,
               "unmatched_a": unmatched, "op": op}


# ═══════════════════════════════════════════════════════════ Resample
def resample(geo, mode="resolution", res=(32, 32, 32), voxel_size=0.1,
             scale=1.0, interpolation="trilinear", volumes=""):
    if mode not in RESAMPLE_MODES:
        raise ValueError(f"Mode must be one of {RESAMPLE_MODES}")
    if interpolation not in INTERP:
        raise ValueError(f"Interpolation must be one of {INTERP}")
    g = geo.copy()
    rep = []
    from . import vdb as _v
    for i in select_volumes(geo, volumes):
        vox, origin, cell = _grid(geo, i)
        size = np.asarray(geo.get(PRIM, "vsize")[i], np.float64)
        old = np.array(vox.shape[:3][::-1])
        if mode == "resolution":
            new = np.maximum(np.asarray(res, int), 2)
        elif mode == "voxel_size":
            if float(voxel_size) <= 0:
                raise ValueError("Voxel Size must be greater than 0")
            new = np.maximum(np.round(size / float(voxel_size)).astype(int) + 1, 2)
        else:
            if float(scale) <= 0:
                raise ValueError("Scale must be greater than 0")
            new = np.maximum(np.round((old - 1) * float(scale)).astype(int) + 1, 2)
        ncell = size / np.maximum(new - 1, 1)
        rz, ry, rx = int(new[2]), int(new[1]), int(new[0])
        Z, Y, X = np.meshgrid(np.arange(rz), np.arange(ry), np.arange(rx),
                              indexing="ij")
        Q = origin + np.stack([X, Y, Z], -1).reshape(-1, 3) * ncell
        a = _v.sample(vox, origin, cell, Q, interpolation).reshape((rz, ry, rx) + vox.shape[3:])
        had = _v.has_mask(geo, i)
        mask = None
        if had:
            # the active region follows the resample (nearest)
            mask = _v.sample(_v.active(geo, i).astype(np.float32), origin, cell, Q,
                             "nearest").reshape(rz, ry, rx) > 0.5
        _set_vox(g, i, a)
        r = np.array(g.get(PRIM, "res"))
        r[i] = new
        g.set(PRIM, "res", r.astype(np.int32), owned=True)
        if had:
            _v.set_active(g, i, mask)
        rep.append([int(v) for v in new])
    return g, {"resolutions": rep}


# ═══════════════════════════════════════════════════════════ Wrangle
def wrangle(geo, code, volumes="", seed=0, ch_params=None):
    from .wrangle import run_wrangle
    g = geo.copy()
    vp = volume_prims(geo)
    nm = geo.get(PRIM, "name")
    infos = {i: _grid(geo, i) for i in vp}

    def volsample(which, pos):
        if isinstance(which, str):
            if nm is None:
                raise ValueError("Volumes have no name attribute; use an index for volsample")
            cand = [i for i in vp if str(nm[i, 0]) == which]
            if not cand:
                raise ValueError(f"volsample: no volume named '{which}'")
            i = cand[0]
        else:
            i = vp[int(which)]
        vx, o, c = infos[i]
        Q = np.asarray(pos, np.float64).reshape(-1, 3)
        from . import vdb as _v
        return _v.sample(vx, o, c, Q)

    done = []
    for i in select_volumes(geo, volumes):
        vox, origin, cell = infos[i]
        Q, (X, Y, Z) = _grid_points(vox, origin, cell)
        tmp = Geometry.from_points(Q)
        tmp.set(POINT, "P", Q.astype(np.float64))
        nc = vox.shape[3] if np.ndim(vox) == 4 else 1
        tmp.set(POINT, "value", np.asarray(vox, np.float64).reshape(-1, nc))
        tmp.set(POINT, "ix", X.reshape(-1, 1).astype(np.int32))
        tmp.set(POINT, "iy", Y.reshape(-1, 1).astype(np.int32))
        tmp.set(POINT, "iz", Z.reshape(-1, 1).astype(np.int32))
        out = run_wrangle(tmp, code, POINT, seed, extra={"volsample": volsample},
                          ch_params=ch_params,
                          squeeze=("value", "ix", "iy", "iz"))
        v = out.get(POINT, "value")
        if v is None or is_string(v):
            raise ValueError("@value was changed into something that is not a number")
        v = np.asarray(v, np.float64)
        if v.ndim == 1:
            v = v[:, None]
        if v.shape[1] != nc:
            if v.shape[1] == 1:
                v = np.repeat(v, nc, 1)
            else:
                raise ValueError(f"@value has {v.shape[1]} components, this volume has {nc}")
        _set_vox(g, i, np.asarray(v, np.float64).reshape(vox.shape))
        done.append(int(i))
    return g, {"volumes": done, "voxels": int(sum(infos[i][0].size for i in done))}


# ═══════════════════════════════════════════════════════════ Reshape SDF
def redistance(vox, origin, cell, band=2.5):
    """Keep the sign, recompute the distance from the 0 isosurface."""
    rz, ry, rx = vox.shape
    size = cell * np.array([rx - 1, ry - 1, rz - 1])
    tmp = make_volume((rx, ry, rz), tuple(size), tuple(origin + size * 0.5))
    tmp.set_pdata(0, "voxels", np.asarray(vox, np.float32))
    surf = volume_to_polygons(tmp, 0.0)
    if surf.nprims == 0:
        return np.asarray(vox, np.float64)               # no surface: unchanged
    from .spatial import tri_soup
    tri, _, _ = tri_soup(surf)
    P = np.asarray(surf.get(POINT, "P"), np.float64)
    d = np.abs(signed_distance(P, tri.astype(np.int64), origin, cell,
                               (rx, ry, rz), band, unsigned=True))
    return np.where(np.asarray(vox) < 0, -d, d)


def reshape_sdf(geo, op="dilate", distance=0.05, volumes=""):
    if op not in RESHAPE_OPS:
        raise ValueError(f"Operation must be one of {RESHAPE_OPS}")
    d = float(distance)
    if d < 0:
        raise ValueError("Distance cannot be negative (choose the direction with dilate / erode)")
    from . import vdb as _v
    g = geo.copy()
    fog = geo.get(PRIM, "fog")
    for i in select_volumes(geo, volumes):
        if fog is not None and int(fog[i, 0]):
            raise ValueError("Reshape SDF only makes sense on SDF volumes (this one is fog density)")
        if _v.is_vdb(g, i):
            # pcg108: a narrow-band VDB only holds distances up to ±background. Offsetting those values by more than
            # the band turned the whole grid inside (or outside). Grow the grid by the distance, rebuild true distances
            # over all of it, apply the operation, then re-derive the band.
            bg = abs(_v.background(g, i))
            vox, origin, cell = _v.grid(g, i)
            if op in ("dilate", "close") and d > 0:
                rz, ry, rx = vox.shape[:3]
                top = origin + cell * (np.array([rx, ry, rz]) - 1)
                _v.grow(g, i, origin - d - bg, top + d + bg)
                vox, origin, cell = _v.grid(g, i)
            f = redistance(np.asarray(vox, np.float64), origin, cell)
        else:
            vox, origin, cell = volume_info(geo, i)
            f = np.asarray(vox, np.float64)
        if op == "dilate":
            f = f - d
        elif op == "erode":
            f = f + d
        elif op == "open":
            f = redistance(f + d, origin, cell) - d
        elif op == "close":
            f = redistance(f - d, origin, cell) + d
        else:
            f = redistance(f, origin, cell)
        if _v.is_vdb(g, i):
            _v.store_sdf(g, i, f, bg)
        else:
            _set_vox(g, i, f)
    return g


# ═══════════════════════════════════════════════════════════ Smooth SDF(pcg100 s9)
def _median_cube(a, r):
    """
    **True** median over the (2r+1)³ cube window (not the per-axis approximation of Volume Blur -- OpenVDB's
    LevelSetFilter::median takes the whole cube). Borders extend the edge value.
    Computed one z slice at a time; memory is voxels per slice × (2r+1)³, the whole window view is never expanded at once.
    """
    ap = np.pad(a, r, mode="edge")
    k = 2 * r + 1
    out = np.empty_like(a)
    for z in range(a.shape[0]):
        win = np.lib.stride_tricks.sliding_window_view(ap[z:z + k], (k, k), axis=(1, 2))
        # win: (k, ry, rx, k, k) -- dimension 0 is the k slices in z
        win = np.moveaxis(win, 0, 2).reshape(a.shape[1], a.shape[2], -1)
        out[z] = np.median(win, -1)
    return out


def _grads(f, cell):
    """Central-difference first and second derivatives (borders extend the edge value). cell is (x, y, z), array axes are (z, y, x)."""
    fp = np.pad(f, 1, mode="edge")
    c = fp[1:-1, 1:-1, 1:-1]
    h = [float(cell[2 - ax]) for ax in range(3)]          # voxel size of array axis 0=z 1=y 2=x

    def sh(dz, dy, dx):
        return fp[1 + dz:fp.shape[0] - 1 + dz, 1 + dy:fp.shape[1] - 1 + dy,
                  1 + dx:fp.shape[2] - 1 + dx]
    unit = [(1, 0, 0), (0, 1, 0), (0, 0, 1)]
    d1, d2 = [], []
    for ax in range(3):
        p, m = sh(*unit[ax]), sh(*[-v for v in unit[ax]])
        d1.append((p - m) / (2 * h[ax]))
        d2.append((p - 2 * c + m) / (h[ax] ** 2))
    dx2 = {}
    for a_ in range(3):
        for b_ in range(a_ + 1, 3):
            u, v = np.array(unit[a_]), np.array(unit[b_])
            dx2[(a_, b_)] = (sh(*(u + v)) - sh(*(u - v)) - sh(*(v - u)) + sh(*(-u - v))) \
                / (4 * h[a_] * h[b_])
    return d1, d2, dx2


def _mean_curvature_norm_grad(f, cell):
    """
    H·|∇φ|, H = ½ div(∇φ / |∇φ|) (mean of the two principal curvatures, as defined by OpenVDB CurvatureStencil):
        H|∇φ| = [φx²(φyy+φzz) + φy²(φxx+φzz) + φz²(φxx+φyy)
                 − 2(φxφyφxy + φxφzφxz + φyφzφyz)] / (2|∇φ|²)
    """
    (fz, fy, fx), (fzz, fyy, fxx), m = _grads(f, cell)
    fzy, fzx, fyx = m[(0, 1)], m[(0, 2)], m[(1, 2)]
    alpha = (fx * fx * (fyy + fzz) + fy * fy * (fxx + fzz) + fz * fz * (fxx + fyy)
             - 2 * (fx * fy * fyx + fx * fz * fzx + fy * fz * fzy))
    n2 = fx * fx + fy * fy + fz * fz
    return alpha / (2 * np.maximum(n2, 1e-20))     # where ∇φ = 0, alpha is 0 too


def smooth_sdf(geo, op="mean_value", radius=1, iterations=1, volumes="",
               mask=None, use_mask=False, invert_mask=False, min_cutoff=0.0,
               max_cutoff=1.0):
    """
    Corresponds to VDB Smooth SDF. Four Operations (the docs give only a one-sentence definition; the implementation follows OpenVDB's
    LevelSetFilter):
      mean_value            mean over the (2r+1)³ cube (separable box, once per axis)
      median_value          true median over the (2r+1)³ cube
      mean_curvature_flow   φ ← φ + dt·H|∇φ|, dt = h²/3 (h = smallest voxel size), H see above
      laplacian_flow        φ ← φ + dt·Δφ,   dt = h²/6
    The docs do not give the step size of the two flows; the values from the OpenVDB source are used; Filter Voxel Radius only affects mean / median
    (OpenVDB's two flows also only look at neighbouring voxels).
    Alpha Mask: the first volume of the second input is trilinearly sampled in world space onto the grid, (a − Min) / (Max − Min)
    clamped to [0, 1] (1 − that with Invert), and each iteration does φ = lerp(original φ, filtered φ, a).
    Unlike Houdini: OpenVDB redistances in the narrow band after each iteration (track), which the docs do not mention; this is
    not done here (redistancing a dense grid is expensive); to restore |∇φ| = 1 follow with Reshape SDF's redistance.
    Trim (setting voxels outside the narrow band to the background value) is meaningless on a dense grid and is not done.
    """
    if op not in SMOOTH_SDF_OPS:
        raise ValueError(f"Operation must be one of {SMOOTH_SDF_OPS}")
    r = max(0, int(radius))
    g = geo.copy()
    fog = geo.get(PRIM, "fog")
    mvol = None
    if use_mask:
        if mask is None or not volume_prims(mask):
            raise ValueError("Alpha Mask is on but the second input has no volume")
        mvol = volume_info(mask, volume_prims(mask)[0])
        lo, hi = float(min_cutoff), float(max_cutoff)
        if hi <= lo:
            raise ValueError("Max Mask Cutoff must be greater than Min Mask Cutoff")
    for i in select_volumes(geo, volumes):
        if fog is not None and int(fog[i, 0]):
            raise ValueError("Smooth SDF only makes sense on SDF volumes (this one is fog density); "
                             "use Volume Blur for fog")
        vox, origin, cell = volume_info(geo, i)
        f = np.asarray(vox, np.float64)
        alpha = None
        if mvol is not None:
            Q, _ = _grid_points(vox, origin, cell)
            av = _sample(mvol[0], mvol[1], mvol[2], Q).reshape(f.shape)
            alpha = np.clip((av - lo) / (hi - lo), 0.0, 1.0)
            if invert_mask:
                alpha = 1.0 - alpha
        h = float(np.min(cell))
        for _ in range(max(0, int(iterations))):
            if op == "mean_value":
                nf = f
                for ax in range(3):
                    nf = _conv1d(nf, np.full(2 * r + 1, 1.0 / (2 * r + 1)), ax)
            elif op == "median_value":
                nf = _median_cube(f, r)
            elif op == "mean_curvature_flow":
                nf = f + h * h / 3.0 * _mean_curvature_norm_grad(f, cell)
            else:
                d2 = _grads(f, cell)[1]
                nf = f + h * h / 6.0 * (d2[0] + d2[1] + d2[2])
            f = nf if alpha is None else f + alpha * (nf - f)
        _set_vox(g, i, f)
    return g
