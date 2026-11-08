"""
The rest of Houdini's Volume SOPs (pcg106). Volumes are the dense grids of volume.py (samples on the bounding-box
corners); "voxel size" is the sample spacing.

  Volume Adjust Fog        pre-process (overwrite / complement), adjust by a pattern (constant / random / noise /
                           line / radial / bounding box, remapped by Range + ramp) with an operation, post-process
                           (scale, add, clamp, complement), blended by a constant or a mask volume
  Volume Bound             the box around voxels meeting the condition (≥, >, ≤, <, = value), padded by voxels
  Volume Break             cut polygons with an SDF's zero surface (linear along edges), keep inside / outside / both,
                           with inside / outside groups
  Volume Compress          tiles of 16³ collapsed to constants within a tolerance, values quantised, half floats,
                           mask by a second volume (voxels outside are zeroed)
  Volume Convolve 3×3×3    27 coefficients, optional normalisation, combine Add or Add Absolute
  Volume Feather           one-sided blur that caps the rate of change: high-to-low v = max(v, w − rate·d),
                           low-to-high v = min(v, w + rate·d), iterated to convergence over the 26 neighbours
  Volume FFT               numpy FFT of real / imaginary pairs, inverse, normalisation, centred DC, 2D slices
  Volume from Attrib       point attribute into the volume: accumulated (trilinear splat, normalised above Threshold)
                           or extrapolated (nearest point within a distance), combined with the destination
  Volume Merge             flatten B volumes into A with copy / add / multiply / max / min / average and pre/post
  Volume Optical Flow      displacement from source to goal: Horn–Schunck on a pyramid with warping
  Volume Patch             fill the masked region from the foreground while matching the background on its border
                           (Poisson blending: ∇²u = ∇²foreground inside, u = background outside)
  Volume Ramp              remap through a scalar ramp or a colour ramp (colour -> name.x / .y / .z)
  Volume Rasterize Curve   curves -> density (smooth tube of radius width / 2 × pressure), mask, or SDF
  Volume Rasterize Particles  points splatted with gaussian / box / cubic spline kernels of radius pscale × scale
  Volume Rasterize Points  points as spheres of pscale with a solid core and (smooth) linear falloff, plus attributes
  Volume Reduce            max / min / average / sum / median (percentile) / RMS ... to a detail attribute or a
                           constant volume, optionally scaled by voxel length / area / volume
  Volume Resize            new bounds (reference geometry or size / centre, replace / intersect / union, padding)
                           on the same lattice -- values are not filtered; new voxels repeat the edge
  Volume Slice             a plane through the volumes as a mesh grid / points with the values as an attribute
  Volume Splice            same-named volumes on the same lattice joined into one; overlaps take the voxel nearest
                           its own volume's centre
  Volume Stamp             volumes of input 3 copied onto the points of input 2 (translate, pscale, orient) and
                           composited into the destination
  Volume Trail             streamlines from points through a velocity field (RK2), fixed steps or CFL-limited
  Volume Velocity          uniform + vortex + curl noise + velocity extrapolated from points, masked
  Volume Velocity from Curves   curve tangents within a radius (inverse-distance weighted), optionally smoothed
  Volume Velocity from Surface  flow inside a closed surface driven by a divergence attribute on it
                           (pressure projection: ∇²p = divergence near the surface, v = ∇p)
"""
from __future__ import annotations

import numpy as np

from .core import DETAIL, POINT, PRIM, Geometry, is_string
from . import vdb as _v

ADJUST_OPS = ("set", "add", "subtract", "multiply", "minimum", "maximum")
ADJUST_PATTERNS = ("constant", "random", "noise", "line", "radial", "bbox")
BOUND_REGIONS = ("greaterequal", "greater", "lessequal", "less", "equal")
BREAK_KEEP = ("inside", "outside", "both")
COMPRESS_DITHER = ("none", "ordered")
CONVOLVE_OPS = ("add", "addabs")
FEATHER_MODES = ("change_per_distance", "change_per_voxel", "distance_for_unit",
                 "voxels_for_unit", "slope_angle")
FROM_ATTRIB_OPS = ("copy", "add", "subtract", "multiply", "divide", "maximum", "minimum")
MERGE_OPS = ("copy", "add", "multiply", "maximum", "minimum", "average")
REDUCE_OPS = ("maximum", "minimum", "average", "sum", "median", "rms", "sum_abs", "max_abs",
              "min_abs", "sum_squares")
REDUCE_SCALE = ("none", "length", "area", "volume")
REDUCE_STORE = ("detail", "prim", "volume")
RESIZE_COMBINE = ("replace", "intersect", "union")
SLICE_METHODS = ("mesh", "points", "volume")
SLICE_PLANES = ("xy", "yz", "zx")
RASTER_CURVE_OUT = ("color", "mask", "sdf")
PARTICLE_FILTERS = ("gaussian", "box", "cubic")
STAMP_MERGE = ("maximum", "add", "minimum", "copy", "average")


def _nd():
    from .vdbcore import _scipy_ndimage
    return _scipy_ndimage()


def _sel(geo, group, allow_vector=True):
    return _v.select(geo, group, allow_vector=allow_vector)


def _mask_from(maskgeo, name, origin, cell, shape):
    if maskgeo is None or not _v.volume_prims(maskgeo):
        return None
    mi = _v.select(maskgeo, name)[0] if str(name).strip() else _v.volume_prims(maskgeo)[0]
    mv, mo, mc = _v.grid(maskgeo, mi)
    Q = _v.world_points(origin, cell, shape).reshape(-1, 3)
    return _v.sample(mv, mo, mc, Q).reshape(shape)


# ═══════════════════════════════════════════════════════════ Adjust Fog
def adjust_fog(geo, group="", operation="add", value=1.0, pattern="constant", range_min=0.0,
               range_max=1.0, ramp="", element_size=1.0, offset=(0, 0, 0), seed=0,
               line_origin=(0, 0, 0), line_dir=(0, 1, 0), radial_center=(0, 0, 0),
               radial_radius=1.0, pre_overwrite=False, initial_value=0.0, pre_complement=False,
               post=False, post_scale=1.0, post_add=0.0, post_clamp_min=False, clamp_min=0.0,
               post_clamp_max=False, clamp_max=1.0, post_complement=False, blend="constant",
               blend_amount=1.0, blend_mask=None, blend_name=""):
    """
    pattern t in [0, 1]: constant 1, random (per voxel), noise (Perlin, element size, offset), line (position along
    Line Direction across the volume), radial (distance from the centre / radius), bbox (1 at the bounding-box
    centre falling to 0 at the faces). t is remapped through the ramp (if any) and then to [Range Min, Range Max];
    the adjustment is Adjust Value × that.
    """
    if operation not in ADJUST_OPS:
        raise ValueError(f"Operation must be one of {ADJUST_OPS}")
    if pattern not in ADJUST_PATTERNS:
        raise ValueError(f"Pattern Type must be one of {ADJUST_PATTERNS}")
    g = geo.copy()
    rng = np.random.default_rng(int(seed))
    for i in _sel(geo, group, False):
        vox, origin, cell = _v.grid(geo, i)
        f0 = np.asarray(vox, np.float64)
        f = f0.copy()
        if pre_overwrite:
            f = np.full_like(f, float(initial_value))
        if pre_complement:
            f = 1.0 - f
        P = _v.world_points(origin, cell, f.shape)
        if pattern == "constant":
            t = np.ones(f.shape)
        elif pattern == "random":
            t = rng.random(f.shape)
        elif pattern == "noise":
            from .attribnoise import perlin
            Q = (P.reshape(-1, 3) + np.asarray(offset, np.float64)) / max(float(element_size), 1e-9)
            t = 0.5 + 0.5 * np.asarray(perlin(Q, int(seed)), np.float64).reshape(f.shape)
        elif pattern == "line":
            dvec = np.asarray(line_dir, np.float64)
            dvec = dvec / max(np.linalg.norm(dvec), 1e-12)
            s = (P - np.asarray(line_origin, np.float64)) @ dvec
            t = (s - s.min()) / max(float(s.max() - s.min()), 1e-12)
        elif pattern == "radial":
            r = np.linalg.norm(P - np.asarray(radial_center, np.float64), axis=-1)
            t = np.clip(r / max(float(radial_radius), 1e-12), 0, 1)
        else:
            lo = origin
            hi = origin + cell * (np.array(f.shape[::-1]) - 1)
            c, h = (lo + hi) / 2, np.maximum((hi - lo) / 2, 1e-12)
            t = 1.0 - np.max(np.abs(P - c) / h, axis=-1)
        if str(ramp).strip():
            from . import ramp as _rmp
            t = _rmp.remap(t.reshape(-1), ramp).reshape(f.shape)
        adj = float(value) * (float(range_min) + t * (float(range_max) - float(range_min)))
        if operation == "set":
            r = adj
        elif operation == "add":
            r = f + adj
        elif operation == "subtract":
            r = f - adj
        elif operation == "multiply":
            r = f * adj
        elif operation == "minimum":
            r = np.minimum(f, adj)
        else:
            r = np.maximum(f, adj)
        if post:
            r = r * float(post_scale) + float(post_add)
            if post_clamp_min:
                r = np.maximum(r, float(clamp_min))
            if post_clamp_max:
                r = np.minimum(r, float(clamp_max))
            if post_complement:
                r = 1.0 - r
        if blend == "volume":
            b = _mask_from(blend_mask, blend_name, origin, cell, f.shape)
            b = np.ones(f.shape) if b is None else np.clip(b, 0, 1)
        else:
            b = float(blend_amount)
        _v.set_voxels(g, i, f0 + b * (r - f0), mask="keep")
    return g


# ═══════════════════════════════════════════════════════════ Bound
def bound(geo, group="", region="greaterequal", value=0.0, padding=(0, 0, 0)):
    from .build import box as _box
    from .ops import merge
    parts = []
    rep = []
    for i in _sel(geo, group, False):
        vox, origin, cell = _v.grid(geo, i)
        f = np.asarray(vox)
        v = float(value)
        m = {"greaterequal": f >= v, "greater": f > v, "lessequal": f <= v, "less": f < v,
             "equal": np.isclose(f, v)}[region]
        if not m.any():
            rep.append(None)
            continue
        idx = np.argwhere(m)
        k0 = idx.min(0)[::-1]
        k1 = idx.max(0)[::-1]
        pad = np.asarray(padding, np.float64)
        # bound on the voxel edges (±½ voxel) by default, like Houdini
        lo = origin + (k0 - 0.5 - pad) * cell
        hi = origin + (k1 + 0.5 + pad) * cell
        parts.append(_box(size=tuple(hi - lo), center=tuple((lo + hi) / 2)))
        rep.append([lo.tolist(), hi.tolist()])
    if not parts:
        return Geometry(), {"bounds": rep}
    return (merge(*parts) if len(parts) > 1 else parts[0]), {"bounds": rep}


# ═══════════════════════════════════════════════════════════ Break
def volume_break(geo, vol, vol_group="", keep="both", create_groups=True, inside_group="inside",
                 outside_group="outside", snap=0.0):
    from .clip import clip_plane
    if keep not in BREAK_KEEP:
        raise ValueError(f"Geometry to Keep must be one of {BREAK_KEEP}")
    vi = _sel(vol, vol_group, False)
    vv, vo, vc = _v.grid(vol, vi[0])
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    d = _v.sample(vv, vo, vc, P, outside=_v.outside_value(vol, vi[0]))
    if _v.grid_class(vol, vi[0]) == _v.CLASS_FOG:
        d = 0.5 - d
    if float(snap) > 0:
        d = np.where(np.abs(d) < float(snap), 0.0, d)
    kmap = {"inside": "below", "outside": "above", "both": "both"}
    out, side = clip_plane(geo, (0, 0, 1), (0, 0, 0), None, kmap[keep], dpt=d)
    if create_groups and out.nprims:
        side = np.asarray(side)
        if keep in ("inside", "both"):
            out.set_group(PRIM, inside_group, side <= 0 if keep == "both" else np.ones(out.nprims, bool))
        if keep in ("outside", "both"):
            out.set_group(PRIM, outside_group, side > 0 if keep == "both" else np.ones(out.nprims, bool))
    return out


# ═══════════════════════════════════════════════════════════ Compress
def compress(geo, group="", constant_tol=0.0, quant_tol=0.0, dither="none", half=False,
             mask=None, mask_group="", use_min=False, mask_min=0.0, use_max=False, mask_max=1.0,
             invert=False, tile=16):
    g = geo.copy()
    rep = []
    bayer = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) + 0.5) / 16 - 0.5
    for i in _sel(geo, group, False):
        vox, origin, cell = _v.grid(geo, i)
        f = np.array(vox, np.float64)
        if mask is not None and (use_min or use_max):
            m = _mask_from(mask, mask_group, origin, cell, f.shape)
            if m is not None:
                keep = np.ones(f.shape, bool)
                if use_min:
                    keep &= m > float(mask_min)
                if use_max:
                    keep &= m < float(mask_max)
                if invert:
                    keep = ~keep
                f = np.where(keep, f, 0.0)
        const = 0
        if float(constant_tol) > 0 or (float(constant_tol) == 0 and True):
            T = int(tile)
            rz, ry, rx = f.shape
            for z in range(0, rz, T):
                for y in range(0, ry, T):
                    for x in range(0, rx, T):
                        b = f[z:z + T, y:y + T, x:x + T]
                        if float(b.max() - b.min()) <= float(constant_tol):
                            f[z:z + T, y:y + T, x:x + T] = b.mean() if constant_tol > 0 else b.flat[0]
                            const += 1
        if float(quant_tol) > 0:
            q = float(quant_tol)
            if dither == "ordered":
                rz, ry, rx = f.shape
                d = np.tile(bayer, (ry // 4 + 1, rx // 4 + 1))[:ry, :rx]
                f = np.round(f / q + d[None]) * q
            else:
                f = np.round(f / q) * q
        if half:
            f = f.astype(np.float16).astype(np.float64)
        _v.set_voxels(g, i, f, mask="keep")
        rep.append(const)
    return g, {"constant_tiles": rep}


# ═══════════════════════════════════════════════════════════ Convolve
def convolve3(geo, group="", kernel=None, normalize=False, op="add"):
    """kernel: 27 numbers, three z planes (z−1, z, z+1), each row-major in y then x."""
    nd = _nd()
    k = np.asarray(kernel if kernel is not None else [0] * 13 + [1] + [0] * 13, np.float64).reshape(3, 3, 3)
    if normalize:
        s = float(np.abs(k).sum() if op == "addabs" else k.sum())
        if abs(s) > 1e-12:
            k = k / s
    g = geo.copy()
    for i in _sel(geo, group, False):
        f = np.asarray(g.pdata(i, "voxels"), np.float64)
        if op == "addabs":
            out = np.zeros_like(f)
            p = np.pad(f, 1, mode="edge")
            for dz in range(3):
                for dy in range(3):
                    for dx in range(3):
                        c = k[dz, dy, dx]
                        if c:
                            out += np.abs(c * p[dz:dz + f.shape[0], dy:dy + f.shape[1], dx:dx + f.shape[2]])
        else:
            out = nd.correlate(f, k, mode="nearest")
        _v.set_voxels(g, i, out, mask="keep")
    return g


# ═══════════════════════════════════════════════════════════ Feather
def feather(geo, group="", mode="change_per_distance", amount=1.0, high_to_low=True,
            border="use_volume", border_value=0.0, max_iter=1000):
    if mode not in FEATHER_MODES:
        raise ValueError(f"Feather Mode must be one of {FEATHER_MODES}")
    g = geo.copy()
    for i in _sel(geo, group, False):
        vox, origin, cell = _v.grid(geo, i)
        f = np.asarray(vox, np.float64)
        h = float(np.min(cell))
        a = float(amount)
        rate = {"change_per_distance": a, "change_per_voxel": a / h,
                "distance_for_unit": 1.0 / max(a, 1e-12), "voxels_for_unit": 1.0 / max(a * h, 1e-12),
                "slope_angle": np.tan(np.radians(a))}[mode]
        offs = [(dz, dy, dx) for dz in (-1, 0, 1) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                if (dz, dy, dx) != (0, 0, 0)]
        for _ in range(int(max_iter)):
            if border == "constant":
                p = np.pad(f, 1, constant_values=float(border_value))
            elif border == "repeat":
                p = np.pad(f, 1, mode="wrap")
            else:
                p = np.pad(f, 1, mode="edge")
            new = f.copy()
            for dz, dy, dx in offs:
                w = p[1 + dz:1 + dz + f.shape[0], 1 + dy:1 + dy + f.shape[1], 1 + dx:1 + dx + f.shape[2]]
                dist = float(np.linalg.norm(np.array([dx, dy, dz]) * cell))
                if high_to_low:
                    new = np.maximum(new, w - rate * dist)
                else:
                    new = np.minimum(new, w + rate * dist)
            if np.allclose(new, f, atol=1e-12, rtol=0):
                break
            f = new
        _v.set_voxels(g, i, f, mask="keep")
    return g


# ═══════════════════════════════════════════════════════════ FFT
def fft(geo, group="", center_dc=False, invert=False, normalize=True, slices=False, axis="z"):
    """Volumes in pairs (real, imaginary) in order; one volume = real with zero imaginary (a new _imag volume is added)."""
    from .ops import merge
    sel = _sel(geo, group, False)
    if not sel:
        raise ValueError("Volume FFT: no volumes")
    g = geo.copy()
    extra = []
    pairs = [(sel[k], sel[k + 1] if k + 1 < len(sel) else None) for k in range(0, len(sel), 2)]
    for ir, ii in pairs:
        vr, o, c = _v.grid(geo, ir)
        z = np.asarray(vr, np.float64) + 1j * (np.asarray(_v.grid(geo, ii)[0], np.float64) if ii is not None
                                               else 0.0)
        axes = (0, 1, 2)
        if slices:
            a = {"x": 2, "y": 1, "z": 0}[axis]
            axes = tuple(k for k in (0, 1, 2) if k != a)
        norm = "ortho" if normalize else "backward"
        if invert:
            if center_dc:
                z = np.fft.ifftshift(z, axes=axes)
            out = np.fft.ifftn(z, axes=axes, norm=norm)
        else:
            out = np.fft.fftn(z, axes=axes, norm=norm)
            if center_dc:
                out = np.fft.fftshift(out, axes=axes)
        _v.set_voxels(g, ir, out.real, mask="keep")
        if ii is not None:
            _v.set_voxels(g, ii, out.imag, mask="keep")
        else:
            extra.append(_v.from_grid(out.imag, o, c, _v.CLASS_NONE,
                                      (_v.name_of(geo, ir) or "fft") + "_imag", False))
    return merge(g, *extra) if extra else g


# ═══════════════════════════════════════════════════════════ from Attrib
def from_attrib(geo, points, group="", point_group="", attribute="density", use_attrib=True,
                accumulated=True, extrapolate=False, max_cells=1, max_dist=0.0, threshold=1.0,
                bandwidth=0.0, scale_by_volume=False, op="copy", dest_add=0.0, dest_mul=1.0,
                src_add=0.0, src_mul=1.0, post_add=0.0, post_mul=1.0):
    from . import groups as _grp
    if op not in FROM_ATTRIB_OPS:
        raise ValueError(f"Calculation must be one of {FROM_ATTRIB_OPS}")
    m = _grp.resolve(points, POINT, point_group)
    P = np.asarray(points.get(POINT, "P"), np.float64)[m]
    a = points.get(POINT, attribute) if use_attrib else None
    if use_attrib and a is None:
        raise ValueError(f"Points have no attribute '{attribute}'")
    vals = np.asarray(a, np.float64)[m] if a is not None else np.ones((len(P), 1))
    g = geo.copy()
    for i in _sel(geo, group):
        vox, origin, cell = _v.grid(geo, i)
        shp = vox.shape[:3]
        nc = vox.shape[3] if vox.ndim == 4 else 1
        V = vals[:, :nc] if vals.shape[1] >= nc else np.repeat(vals[:, :1], nc, 1)
        acc = np.zeros(shp + (nc,))
        wsum = np.zeros(shp)
        u = _v.to_index(origin, cell, P)
        if accumulated and not extrapolate:
            r = int(np.ceil(float(bandwidth)))
            i0 = np.floor(u).astype(int)
            t = u - i0
            for dz in range(-r, 2 + r):
                for dy in range(-r, 2 + r):
                    for dx in range(-r, 2 + r):
                        k = i0 + np.array([dx, dy, dz])
                        if r == 0:
                            w = ((t[:, 0] if dx else 1 - t[:, 0]) * (t[:, 1] if dy else 1 - t[:, 1])
                                 * (t[:, 2] if dz else 1 - t[:, 2]))
                        else:
                            dd = np.linalg.norm((k - u), axis=1)
                            w = np.maximum(0.0, 1.0 - dd / (r + 1.0))
                        ok = ((k >= 0) & (k < np.array(shp[::-1]))).all(1) & (w > 0)
                        np.add.at(wsum, (k[ok, 2], k[ok, 1], k[ok, 0]), w[ok])
                        for c in range(nc):
                            np.add.at(acc[..., c], (k[ok, 2], k[ok, 1], k[ok, 0]), w[ok] * V[ok, c])
            norm = np.where(wsum > float(threshold), wsum, np.maximum(float(threshold), 1e-12))
            src = acc / norm[..., None]
        else:
            from scipy.spatial import cKDTree
            Q = _v.world_points(origin, cell, shp).reshape(-1, 3)
            lim = max(float(max_dist), int(max_cells) * float(np.max(cell)))
            dist, idx = cKDTree(P).query(Q, distance_upper_bound=lim if lim > 0 else np.inf)
            ok = np.isfinite(dist)
            src = np.zeros((len(Q), nc))
            src[ok] = V[idx[ok]]
            src = src.reshape(shp + (nc,))
        if scale_by_volume:
            src = src / float(np.prod(cell))
        A = np.asarray(vox, np.float64).reshape(shp + (nc,)) * float(dest_mul) + float(dest_add)
        B = src * float(src_mul) + float(src_add)
        R = {"copy": B, "add": A + B, "subtract": A - B, "multiply": A * B,
             "divide": np.where(B != 0, A / np.where(B == 0, 1, B), A),
             "maximum": np.maximum(A, B), "minimum": np.minimum(A, B)}[op]
        R = R * float(post_mul) + float(post_add)
        _v.set_voxels(g, i, R[..., 0] if nc == 1 else R, mask="keep")
    return g


# ═══════════════════════════════════════════════════════════ Merge
def merge_volumes(geo_a, geo_b=None, group="", merge_group="", method="add", clamp_boundary=True,
                  dest_add=0.0, dest_mul=1.0, src_add=0.0, src_mul=1.0, post_add=0.0, post_mul=1.0,
                  use_min=False, vmin=0.0, use_max=False, vmax=1.0):
    if method not in MERGE_OPS:
        raise ValueError(f"Merge Method must be one of {MERGE_OPS}")
    src_geo = geo_b if geo_b is not None else geo_a
    ia = _sel(geo_a, group)
    ib = _sel(src_geo, merge_group)
    if geo_b is None:
        ib = [j for j in ib if j not in ia[:1]]
        ia = ia[:1]
    g = geo_a.copy()
    for i in ia:
        vox, origin, cell = _v.grid(geo_a, i)
        A = np.asarray(vox, np.float64) * float(dest_mul) + float(dest_add)
        Q = _v.world_points(origin, cell, vox.shape[:3]).reshape(-1, 3)
        Bs = []
        for j in ib:
            vb, ob, cb = _v.grid(src_geo, j)
            if np.ndim(vb) != np.ndim(vox):
                continue                              # scalar and vector volumes are not merged together
            b = _v.sample(vb, ob, cb, Q, outside=(0.0 if clamp_boundary else None))
            Bs.append(b.reshape(A.shape) * float(src_mul) + float(src_add))
        if not Bs:
            continue
        if method == "copy":
            R = Bs[-1]
        elif method == "add":
            R = A + sum(Bs)
        elif method == "multiply":
            R = A * np.prod(Bs, axis=0)
        elif method == "maximum":
            R = np.maximum(A, np.max(Bs, axis=0))
        elif method == "minimum":
            R = np.minimum(A, np.min(Bs, axis=0))
        else:
            R = (A + sum(Bs)) / (len(Bs) + 1)
        if use_max:
            R = np.minimum(R, float(vmax))
        R = R * float(post_mul) + float(post_add)
        if use_min:
            R = np.maximum(R, float(vmin))
        _v.set_voxels(g, i, R, mask="keep")
    return g


# ═══════════════════════════════════════════════════════════ Optical Flow
def _hs_level(I0, I1, cell, alpha, iters, blur, gaussian, init):
    nd = _nd()
    u = init.copy()
    for _ in range(int(iters)):
        P = _v.world_points(np.zeros(3), cell, I0.shape).reshape(-1, 3)
        warped = _v.sample(I1, np.zeros(3), cell, P + u.reshape(-1, 3)).reshape(I0.shape)
        It = warped - I0
        gx = np.stack([np.gradient(warped, float(cell[a]), axis=2 - a) for a in range(3)], -1)
        du = np.zeros_like(u)
        for _k in range(8):
            ub = np.stack([nd.uniform_filter(du[..., a], 3, mode="nearest") for a in range(3)], -1)
            num = (gx * ub).sum(-1) + It
            den = alpha ** 2 + (gx ** 2).sum(-1)
            du = ub - gx * (num / den)[..., None]
        u = u + du
        if blur > 0:
            if gaussian:
                u = np.stack([nd.gaussian_filter(u[..., a], blur / 2.0, mode="nearest") for a in range(3)], -1)
            else:
                u = np.stack([nd.uniform_filter(u[..., a], 2 * int(blur) + 1, mode="nearest") for a in range(3)], -1)
    return u


def optical_flow(src, goal, group="", goal_group="", tolerance=0.0, blur_radius=1, gaussian=False,
                 levels=3, pyr_scale=0.5, iterations=4, approx_radius=2):
    """
    Displacement d per source voxel such that goal(x + d) ≈ source(x), estimated by Horn–Schunck with warping on a
    coarse-to-fine pyramid. Tolerance: differences below it give no displacement (regularisation α).
    Output: three scalar volumes <source name>.x / .y / .z (world units), like Houdini.
    """
    from .ops import merge
    ia, ib = _sel(src, group, False), _sel(goal, goal_group, False)
    if len(ia) != len(ib):
        raise ValueError("Source and goal must have the same number of volumes")
    out = []
    nd = _nd()
    for i, j in zip(ia, ib):
        v0, o0, c0 = _v.grid(src, i)
        v1, o1, c1 = _v.grid(goal, j)
        Q = _v.world_points(o0, c0, v0.shape).reshape(-1, 3)
        I0 = np.asarray(v0, np.float64)
        I1 = _v.sample(v1, o1, c1, Q).reshape(I0.shape)
        alpha = max(float(tolerance), 1e-3) * max(float(np.abs(I0).max()), 1e-6) * 10
        u = None
        L = max(1, int(levels))
        for lev in range(L - 1, -1, -1):
            s = float(pyr_scale) ** lev
            shp = tuple(max(4, int(round(n * s))) for n in I0.shape)
            zoom = [shp[k] / I0.shape[k] for k in range(3)]
            a0 = nd.zoom(nd.gaussian_filter(I0, max(approx_radius, 0) / 2.0 / max(s, 1e-3) * s), zoom, order=1)
            a1 = nd.zoom(nd.gaussian_filter(I1, max(approx_radius, 0) / 2.0 / max(s, 1e-3) * s), zoom, order=1)
            cl = c0 * (np.array(I0.shape[::-1]) - 1) / (np.array(a0.shape[::-1]) - 1)
            if u is None:
                init = np.zeros(a0.shape + (3,))
            else:
                init = np.stack([nd.zoom(u[..., k], [a0.shape[m] / u.shape[m] for m in range(3)], order=1)
                                 for k in range(3)], -1)
            u = _hs_level(a0, a1, cl, alpha, iterations, blur_radius, gaussian, init)
        if u.shape[:3] != I0.shape:
            u = np.stack([nd.zoom(u[..., k], [I0.shape[m] / u.shape[m] for m in range(3)], order=1)
                          for k in range(3)], -1)
        nm = _v.name_of(src, i) or "flow"
        for k, s in enumerate("xyz"):
            out.append(_v.from_grid(u[..., k], o0, c0, _v.CLASS_NONE, f"{nm}.{s}", False))
    return merge(*out) if len(out) > 1 else out[0]


# ═══════════════════════════════════════════════════════════ Patch
def patch(geo, background="", foreground="", mask_name="", cutoff=0.5, fg_is_laplacian=False,
          iterations=2000, tolerance=1e-6):
    from .vdbfield import _cg, laplacian
    ib = _sel(geo, background, False)[0]
    ifg = _sel(geo, foreground, False)[0]
    im = _sel(geo, mask_name, False)[0]
    vb, ob, cb = _v.grid(geo, ib)
    Q = _v.world_points(ob, cb, vb.shape).reshape(-1, 3)
    fgv = _v.sample(*_v.grid(geo, ifg), Q).reshape(vb.shape)
    m = _v.sample(*_v.grid(geo, im), Q).reshape(vb.shape) >= float(cutoff)
    bgv = np.asarray(vb, np.float64)
    rhs_lap = fgv if fg_is_laplacian else laplacian(fgv, cb)
    if not m.any():
        return geo.copy()
    # unknowns inside the mask; u = background elsewhere. −∇²u = −lap inside.
    known = np.where(m, 0.0, bgv)

    def A(x):
        x = np.where(m, x, 0.0)
        return np.where(m, -laplacian(x, cb), 0.0)
    b = np.where(m, -rhs_lap + laplacian(known, cb), 0.0)
    x, its, res = _cg(b, A, iterations, tolerance)
    out = np.where(m, x, bgv)
    g = geo.copy()
    _v.set_voxels(g, ib, out, mask="keep")
    return g


# ═══════════════════════════════════════════════════════════ Ramp
def volume_ramp(geo, group="", new_name="", src_min=0.0, src_max=1.0, dest_min=0.0, dest_max=1.0,
                use_color=False, ramp="", color_ramp=""):
    from . import ramp as _rmp
    from .ops import merge, delete_prims
    g = geo.copy()
    extra = []
    drop = []
    for i in _sel(geo, group, False):
        vox, origin, cell = _v.grid(geo, i)
        t = (np.asarray(vox, np.float64) - float(src_min)) / max(float(src_max) - float(src_min), 1e-12)
        t = np.clip(t, 0, 1).reshape(-1)
        if use_color:
            spec = color_ramp if str(color_ramp).strip() else "0:0,0,0 1:1,1,1"
            pos, val = _rmp.parse(spec, 3)
            c = np.clip(_rmp.apply(t, pos, val), 0, 1)
            c = float(dest_min) + c * (float(dest_max) - float(dest_min))
            base = str(new_name).strip() or _v.name_of(geo, i) or "Cd"
            for k, s in enumerate("xyz"):
                extra.append(_v.from_grid(c[:, k].reshape(vox.shape), origin, cell, _v.CLASS_NONE,
                                          f"{base}.{s}", _v.is_vdb(geo, i)))
            drop.append(i)
        else:
            spec = ramp if str(ramp).strip() else "0:0 1:1"
            r = np.clip(_rmp.remap(t, spec), 0, 1)
            r = float(dest_min) + r * (float(dest_max) - float(dest_min))
            _v.set_voxels(g, i, r.reshape(vox.shape), mask="keep")
            if str(new_name).strip():
                _v.set_name(g, i, str(new_name).strip())
    if drop:
        keep = np.ones(g.nprims, bool)
        keep[drop] = False
        g = delete_prims(g, keep)
    parts = ([g] if (g.npoints or g.nprims) else []) + extra
    return merge(*parts) if len(parts) > 1 else parts[0]


# ═══════════════════════════════════════════════════════════ rasterize
def _dest_grid(dest, voxel_size, lo, hi):
    if dest is not None and _v.volume_prims(dest):
        i = _v.volume_prims(dest)[0]
        return _v.grid(dest, i)
    vs = float(voxel_size)
    if vs <= 0:
        raise ValueError("Voxel Size must be greater than 0")
    n = np.maximum(np.ceil((hi - lo) / vs - 1e-9).astype(int) + 1, 2)
    return np.zeros((n[2], n[1], n[0]), np.float32), lo, np.full(3, vs)


def _seg_dist(Q, A, B):
    """Distance from points Q (n,3) to segments A->B (m,3): returns (n, m) and parameter t."""
    AB = B - A
    L2 = np.maximum((AB * AB).sum(1), 1e-18)
    t = np.clip(((Q[:, None, :] - A[None]) * AB[None]).sum(-1) / L2[None], 0, 1)
    X = A[None] + t[..., None] * AB[None]
    return np.linalg.norm(Q[:, None, :] - X, axis=-1), t


def rasterize_curve(curves, output="mask", voxel_size=0.05, density_scale=1.0, fade=0.0,
                    flow_rate=1.0, name="density"):
    """
    Each polyline is a tube of radius width / 2 × stroke_pressure (both default 1 when missing; width / pscale
    attributes on points). mask: density = density_scale × smoothstep(1 − d / r) (1 on the axis, 0 at the tube
    surface); fade: density along the stroke × (1 − fade · s) with s the normalised arc length; color: also a vector
    Cd volume (density-weighted average of the curve colour); sdf: d − r, union of the tubes.
    """
    from .ops import merge
    if output not in RASTER_CURVE_OUT:
        raise ValueError(f"Output must be one of {RASTER_CURVE_OUT}")
    P = np.asarray(curves.get(POINT, "P"), np.float64)
    wa = curves.get(POINT, "width")
    pa = curves.get(POINT, "stroke_pressure")
    ps = curves.get(POINT, "pscale")
    W = (np.asarray(wa, np.float64)[:, 0] if wa is not None else
         (2 * np.asarray(ps, np.float64)[:, 0] if ps is not None else np.full(len(P), 0.1)))
    W = W * (np.asarray(pa, np.float64)[:, 0] if pa is not None else 1.0)
    Cd = curves.get(POINT, "Cd")
    segA, segB, rA, rB, sA, sB, cA, cB = [], [], [], [], [], [], [], []
    for i in range(curves.nprims):
        idx = curves.prim_points(i)
        if len(idx) < 2:
            continue
        if curves.prim_closed[i]:
            idx = np.append(idx, idx[0])
        L = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(P[idx], axis=0), axis=1))])
        s = L / max(L[-1], 1e-12)
        segA.append(P[idx[:-1]])
        segB.append(P[idx[1:]])
        rA.append(W[idx[:-1]] / 2)
        rB.append(W[idx[1:]] / 2)
        sA.append(s[:-1])
        sB.append(s[1:])
        if Cd is not None:
            cA.append(np.asarray(Cd, np.float64)[idx[:-1]])
            cB.append(np.asarray(Cd, np.float64)[idx[1:]])
    if not segA:
        raise ValueError("Volume Rasterize Curve needs polylines with at least two points")
    A, B = np.concatenate(segA), np.concatenate(segB)
    RA, RB = np.concatenate(rA), np.concatenate(rB)
    SA, SB = np.concatenate(sA), np.concatenate(sB)
    rmax = float(max(RA.max(), RB.max()))
    lo = np.minimum(A, B).min(0) - rmax - 2 * float(voxel_size)
    hi = np.maximum(A, B).max(0) + rmax + 2 * float(voxel_size)
    _, origin, cell = _dest_grid(None, voxel_size, lo, hi)
    shp = tuple(int(x) for x in np.ceil((hi - lo) / cell - 1e-9).astype(int)[::-1] + 1)
    Q = _v.world_points(origin, cell, shp).reshape(-1, 3)
    dens = np.zeros(len(Q))
    sdf = np.full(len(Q), np.inf)
    col = np.zeros((len(Q), 3))
    wsum = np.zeros(len(Q))
    chunk = max(1, int(2e6 // max(len(A), 1)))
    for s0 in range(0, len(Q), chunk):
        q = Q[s0:s0 + chunk]
        d, t = _seg_dist(q, A, B)
        r = RA[None] + (RB - RA)[None] * t
        sd = d - r
        sdf[s0:s0 + chunk] = sd.min(1)
        x = np.clip(1.0 - d / np.maximum(r, 1e-12), 0, 1)
        x = x * x * (3 - 2 * x)
        sarc = SA[None] + (SB - SA)[None] * t
        x = x * np.clip(1.0 - float(fade) * sarc, 0, 1) * float(flow_rate)
        k = np.argmax(x, 1)
        dens[s0:s0 + chunk] = x[np.arange(len(q)), k]
        if cA:
            CA, CB = np.concatenate(cA), np.concatenate(cB)
            tk = t[np.arange(len(q)), k]
            col[s0:s0 + chunk] = CA[k] + (CB[k] - CA[k]) * tk[:, None]
            wsum[s0:s0 + chunk] = dens[s0:s0 + chunk]
    if output == "sdf":
        return _v.from_grid(sdf.reshape(shp), origin, cell, _v.CLASS_SDF,
                            name if name != "density" else "surface", False)
    dv = _v.from_grid((dens * float(density_scale)).reshape(shp), origin, cell, _v.CLASS_FOG, name, False)
    if output == "color":
        c = col if cA else np.ones((len(Q), 3))
        cv = _v.from_grid(c.reshape(shp + (3,)), origin, cell, _v.CLASS_NONE, "Cd", False)
        return merge(dv, cv)
    return dv


def _kernel(d, r, kind):
    x = d / np.maximum(r, 1e-12)
    if kind == "box":
        return (x <= 1.0).astype(np.float64)
    if kind == "cubic":
        q = 2.0 * x
        return np.where(q < 1, 1 - 1.5 * q ** 2 + 0.75 * q ** 3, np.where(q < 2, 0.25 * (2 - q) ** 3, 0.0))
    return np.where(x <= 1.0, np.exp(-4.5 * x * x), 0.0)        # gaussian, σ = r / 3


def rasterize_particles(dest, points, point_group="", filt="gaussian", coverage_attrib="",
                        coverage_scale=1.0, particle_scale=1.0, min_filter=1.0, attributes="",
                        voxel_size=0.1):
    """
    Each point contributes kernel(|x − p| / r) × coverage to `density` (accumulated); r = max(pscale × Particle
    Scale, Minimum Filter Size voxels). Other attributes (Attributes, by name) are coverage-weighted averages into
    same-named volumes (vector attributes -> vector volumes).
    """
    from . import groups as _grp
    from .ops import merge
    if filt not in PARTICLE_FILTERS:
        raise ValueError(f"Filter must be one of {PARTICLE_FILTERS}")
    m = _grp.resolve(points, POINT, point_group)
    P = np.asarray(points.get(POINT, "P"), np.float64)[m]
    if not len(P):
        raise ValueError("No points to rasterize")
    ps = points.get(POINT, "pscale")
    R = (np.asarray(ps, np.float64)[m, 0] if ps is not None else np.ones(len(P))) * float(particle_scale)
    cov = (np.asarray(points.get(POINT, coverage_attrib), np.float64)[m, 0]
           if coverage_attrib and points.get(POINT, coverage_attrib) is not None else np.ones(len(P)))
    cov = cov * float(coverage_scale)
    vox, origin, cell = _dest_grid(dest, voxel_size, P.min(0) - R.max() - voxel_size,
                                   P.max(0) + R.max() + voxel_size)
    R = np.maximum(R, float(min_filter) * float(np.min(cell)))
    shp = vox.shape[:3]
    dens = np.zeros(shp)
    names = [a for a in str(attributes).replace(",", " ").split() if a]
    accs = {n: np.zeros(shp + (np.asarray(points.get(POINT, n)).shape[1],)) for n in names
            if points.get(POINT, n) is not None and not is_string(points.get(POINT, n))}
    wts = np.zeros(shp)
    # All (particle, voxel) pairs at once, chunked by pair count, accumulated with bincount. It used to be a Python
    # loop per particle (10k particles: 5.6 s); the sums are the same up to the order of floating-point additions.
    rz, ry, rx = shp
    N = rx * ry * rz
    top = np.array([rx, ry, rz]) - 1
    k0 = np.maximum(np.floor((P - R[:, None] - origin) / cell).astype(np.int64), 0)
    k1 = np.minimum(np.ceil((P + R[:, None] - origin) / cell).astype(np.int64), top)
    ok = np.all(k1 >= k0, axis=1)
    span = np.where(ok[:, None], k1 - k0 + 1, 0)
    cnt = span.prod(1)
    vals = {n: np.asarray(points.get(POINT, n), np.float64)[m] for n in accs}
    flat_d, flat_w, flat_a = dens.reshape(-1), wts.reshape(-1), {n: a.reshape(N, -1) for n, a in accs.items()}
    # Large kernels (thousands of voxels each) are already vectorized enough one particle at a time, on a slice of
    # the grid; the batched path is for the many-small-particles case where the per-particle overhead dominated.
    big = cnt > 2048
    for k in np.nonzero(big)[0]:
        sl = (slice(k0[k, 2], k1[k, 2] + 1), slice(k0[k, 1], k1[k, 1] + 1), slice(k0[k, 0], k1[k, 0] + 1))
        X = _v.world_points(origin + k0[k] * cell, cell, (span[k, 2], span[k, 1], span[k, 0]))
        w = _kernel(np.linalg.norm(X - P[k], axis=-1), R[k], filt) * cov[k]
        dens[sl] += w
        wts[sl] += w
        for n, acc in accs.items():
            acc[sl] += w[..., None] * vals[n][k]
    ids = np.nonzero((cnt > 0) & ~big)[0]
    lim, s0 = 4_000_000, 0
    csum = np.cumsum(cnt[ids])
    while s0 < len(ids):
        base = csum[s0 - 1] if s0 else 0
        e0 = max(int(np.searchsorted(csum, base + lim, side="right")), s0 + 1)
        sel = ids[s0:e0]
        s0 = e0
        c = cnt[sel]
        owner = np.repeat(sel, c)
        off = np.concatenate([[0], np.cumsum(c)])
        local = np.arange(int(c.sum())) - np.repeat(off[:-1], c)
        sx, sy = span[owner, 0], span[owner, 1]
        ix = k0[owner, 0] + local % sx
        iy = k0[owner, 1] + (local // sx) % sy
        iz = k0[owner, 2] + local // (sx * sy)
        X = origin + np.stack([ix, iy, iz], 1) * cell
        w = _kernel(np.linalg.norm(X - P[owner], axis=1), R[owner], filt) * cov[owner]
        flat = (iz * ry + iy) * rx + ix
        acc = np.bincount(flat, weights=w, minlength=N)
        flat_d += acc
        flat_w += acc
        for n, a in flat_a.items():
            v = vals[n][owner]
            for ch in range(a.shape[1]):
                a[:, ch] += np.bincount(flat, weights=w * v[:, ch], minlength=N)
    out = [_v.from_grid(dens, origin, cell, _v.CLASS_FOG, "density", False)]
    for n, acc in accs.items():
        avg = acc / np.maximum(wts, 1e-12)[..., None]
        out.append(_v.from_grid(avg[..., 0] if avg.shape[-1] == 1 else avg[..., :3], origin, cell,
                                _v.CLASS_NONE, n, False))
    if dest is not None and _v.volume_prims(dest):
        from .ops import delete_prims
        g = dest.copy()
        for o in out:
            nm = _v.name_of(o, 0)
            hit = [i for i in _v.volume_prims(g) if _v.name_of(g, i) == nm or
                   (nm == "density" and not _v.name_of(g, i))]
            if hit and g.pdata(hit[0], "voxels").shape == o.pdata(0, "voxels").shape:
                _v.set_voxels(g, hit[0], np.asarray(g.pdata(hit[0], "voxels")) + o.pdata(0, "voxels")
                              if nm == "density" else o.pdata(0, "voxels"), mask="keep")
            else:
                g = merge(g, o)
        return g
    return merge(*out) if len(out) > 1 else out[0]


def rasterize_points(dest, points, point_group="", density_scale=1.0, solid_ratio=0.0,
                     smooth=True, exterior_pad=0.0, attributes="", voxel_size=0.1,
                     merge_method="maximum", noise_amp=0.0, noise_size=1.0, seed=0):
    """
    Points as spheres of radius pscale + Exterior Pad. Inside Solid Ratio × r the density is 1; from there to r it
    falls to 0 (linear, or smooth = smoothstep). Density × Density Scale (× point `density` if present),
    merged per voxel by Merge Method (maximum / add). Noise (optional) multiplies the density by
    (1 + amplitude × Perlin(P / element size)). Attributes go into same-named volumes, density-weighted.
    """
    from . import groups as _grp
    from .ops import merge
    m = _grp.resolve(points, POINT, point_group)
    P = np.asarray(points.get(POINT, "P"), np.float64)[m]
    if not len(P):
        raise ValueError("No points to rasterize")
    ps = points.get(POINT, "pscale")
    R = (np.asarray(ps, np.float64)[m, 0] if ps is not None else np.full(len(P), 0.1)) + float(exterior_pad)
    da = points.get(POINT, "density")
    D = (np.asarray(da, np.float64)[m, 0] if da is not None else np.ones(len(P))) * float(density_scale)
    vox, origin, cell = _dest_grid(dest, voxel_size, P.min(0) - R.max() - voxel_size,
                                   P.max(0) + R.max() + voxel_size)
    shp = vox.shape[:3]
    dens = np.zeros(shp)
    names = [a for a in str(attributes).replace(",", " ").split() if a]
    accs = {n: np.zeros(shp + (np.asarray(points.get(POINT, n)).shape[1],)) for n in names
            if points.get(POINT, n) is not None and not is_string(points.get(POINT, n))}
    wts = np.zeros(shp)
    sr = float(np.clip(solid_ratio, 0, 0.999))
    for k, (p, r, dd) in enumerate(zip(P, R, D)):
        k0 = np.maximum(np.floor((p - r - origin) / cell).astype(int), 0)
        k1 = np.minimum(np.ceil((p + r - origin) / cell).astype(int), np.array(shp[::-1]) - 1)
        if np.any(k1 < k0):
            continue
        sl = (slice(k0[2], k1[2] + 1), slice(k0[1], k1[1] + 1), slice(k0[0], k1[0] + 1))
        X = _v.world_points(origin + k0 * cell, cell, (k1[2] - k0[2] + 1, k1[1] - k0[1] + 1, k1[0] - k0[0] + 1))
        x = np.linalg.norm(X - p, axis=-1) / max(r, 1e-12)
        w = np.clip((1.0 - x) / (1.0 - sr), 0, 1)
        if smooth:
            w = w * w * (3 - 2 * w)
        w = w * dd
        if float(noise_amp):
            from .attribnoise import perlin
            nz = np.asarray(perlin(X.reshape(-1, 3) / max(float(noise_size), 1e-9), int(seed)),
                            np.float64).reshape(w.shape)
            w = np.maximum(w * (1 + float(noise_amp) * nz), 0)
        if merge_method == "add":
            dens[sl] += w
        else:
            dens[sl] = np.maximum(dens[sl], w)
        wts[sl] += w
        for n, acc in accs.items():
            acc[sl] += w[..., None] * np.asarray(points.get(POINT, n), np.float64)[m][k]
    out = [_v.from_grid(dens, origin, cell, _v.CLASS_FOG, "density", False)]
    for n, acc in accs.items():
        avg = acc / np.maximum(wts, 1e-12)[..., None]
        out.append(_v.from_grid(avg[..., 0] if avg.shape[-1] == 1 else avg[..., :3], origin, cell,
                                _v.CLASS_NONE, n, False))
    if dest is not None and _v.volume_prims(dest):
        g = dest.copy()
        for o in out:
            nm = _v.name_of(o, 0)
            hit = [i for i in _v.volume_prims(g) if _v.name_of(g, i) == nm or
                   (nm == "density" and not _v.name_of(g, i))]
            if hit and g.pdata(hit[0], "voxels").shape == o.pdata(0, "voxels").shape:
                old = np.asarray(g.pdata(hit[0], "voxels"), np.float64)
                new = o.pdata(0, "voxels")
                if nm == "density":
                    new = old + new if merge_method == "add" else np.maximum(old, new)
                _v.set_voxels(g, hit[0], new, mask="keep")
            else:
                g = merge(g, o)
        return g
    return merge(*out) if len(out) > 1 else out[0]


# ═══════════════════════════════════════════════════════════ Reduce
def reduce(geo, group="", reduction="maximum", percentile=50.0, scale_by="none", store="detail",
           attribute="", active_only=True):
    if reduction not in REDUCE_OPS:
        raise ValueError(f"Reduction must be one of {REDUCE_OPS}")
    g = geo.copy()
    vals = []
    for i in _sel(geo, group, False):
        vox, origin, cell = _v.grid(geo, i)
        f = np.asarray(vox, np.float64)
        if active_only and _v.has_mask(geo, i):
            f = f[_v.active(geo, i)]
        f = f.reshape(-1)
        r = {"maximum": lambda: f.max(), "minimum": lambda: f.min(), "average": lambda: f.mean(),
             "sum": lambda: f.sum(), "median": lambda: np.percentile(f, float(percentile)),
             "rms": lambda: np.sqrt((f * f).mean()), "sum_abs": lambda: np.abs(f).sum(),
             "max_abs": lambda: np.abs(f).max(), "min_abs": lambda: np.abs(f).min(),
             "sum_squares": lambda: (f * f).sum()}[reduction]()
        vv = float(np.prod(cell))
        r *= {"none": 1.0, "length": vv ** (1 / 3), "area": vv ** (2 / 3), "volume": vv}[scale_by]
        vals.append(float(r))
        if store == "volume":
            _v.set_voxels(g, i, np.full(vox.shape, r), mask="keep")
    name = str(attribute).strip() or reduction
    if store == "detail":
        g.set(DETAIL, name, np.array([[vals[0] if len(vals) == 1 else vals[0]]], np.float32), owned=True)
        if len(vals) > 1:
            for k, v in enumerate(vals):
                g.set(DETAIL, f"{name}{k}", np.array([[v]], np.float32), owned=True)
    elif store == "prim":
        a = g.get(PRIM, name)
        a = np.zeros((g.nprims, 1), np.float32) if a is None else np.array(a, np.float32, copy=True)
        for v, i in zip(vals, _sel(geo, group, False)):
            a[i, 0] = v
        g.set(PRIM, name, a, owned=True)
    return g, {"values": vals}


# ═══════════════════════════════════════════════════════════ Resize
def resize(geo, reference=None, group="", combine="replace", size=(1, 1, 1), center=(0, 0, 0),
           padding=(0, 0, 0), keep_data=True, limit_res=False, max_res=512):
    if combine not in RESIZE_COMBINE:
        raise ValueError(f"Combine Mode must be one of {RESIZE_COMBINE}")
    g = geo.copy()
    for i in _sel(geo, group):
        vox, origin, cell = _v.grid(geo, i)
        top = origin + cell * (np.array(_v.res_of(vox)) - 1)
        if reference is not None and (reference.npoints or reference.nprims):
            rlo, rhi = _v.bounds(reference)
        else:
            c, s = np.asarray(center, np.float64), np.abs(np.asarray(size, np.float64))
            rlo, rhi = c - s / 2, c + s / 2
        if combine == "replace":
            lo, hi = rlo, rhi
        elif combine == "union":
            lo, hi = np.minimum(origin, rlo), np.maximum(top, rhi)
        else:
            lo, hi = np.maximum(origin, rlo), np.minimum(top, rhi)
        pad = np.asarray(padding, np.float64) * cell
        lo, hi = lo - pad, hi + pad
        k0 = np.floor((lo - origin) / cell + 1e-6).astype(int)
        k1 = np.ceil((hi - origin) / cell - 1e-6).astype(int)
        k1 = np.maximum(k1, k0 + 1)
        if limit_res:
            k1 = np.minimum(k1, k0 + int(max_res) - 1)
        n = k1 - k0 + 1
        old = np.asarray(vox, np.float32)
        idx = [np.clip(np.arange(k0[a], k1[a] + 1), 0, old.shape[2 - a] - 1) for a in range(3)]
        new = old[np.ix_(idx[2], idx[1], idx[0])] if keep_data else np.zeros((n[2], n[1], n[0]) + old.shape[3:],
                                                                                np.float32)
        _v.set_grid(g, i, origin + k0 * cell, cell, new)
    return g


# ═══════════════════════════════════════════════════════════ Slice
def slice_volumes(geo, group="", method="mesh", plane="xy", relative=True, position=(0, 0, 0),
                  offset=0.0, snap=False, attribute="", visualize=True, vis_min=0.0, vis_max=1.0,
                  ramp="", keep=False):
    from .ops import merge
    if method not in SLICE_METHODS:
        raise ValueError(f"Method must be one of {SLICE_METHODS}")
    sel = _sel(geo, group, False)
    if not sel:
        raise ValueError("Volume Slice: no scalar volume")
    vox, origin, cell = _v.grid(geo, sel[0])
    rx, ry, rz = _v.res_of(vox)
    top = origin + cell * (np.array([rx, ry, rz]) - 1)
    ax = {"xy": 2, "yz": 0, "zx": 1}[plane]
    u_ax, v_ax = {"xy": (0, 1), "yz": (1, 2), "zx": (2, 0)}[plane]
    if relative:
        w = origin[ax] + (top[ax] - origin[ax]) * (0.5 + 0.5 * float(offset))
    else:
        w = float(position[ax]) + float(offset)
    if snap:
        w = origin[ax] + np.round((w - origin[ax]) / cell[ax]) * cell[ax]
    nu = [rx, ry, rz][u_ax]
    nv = [rx, ry, rz][v_ax]
    U = origin[u_ax] + np.arange(nu) * cell[u_ax]
    Vv = origin[v_ax] + np.arange(nv) * cell[v_ax]
    UU, VV = np.meshgrid(U, Vv, indexing="xy")
    Q = np.zeros((UU.size, 3))
    Q[:, u_ax] = UU.reshape(-1)
    Q[:, v_ax] = VV.reshape(-1)
    Q[:, ax] = w
    vals = np.stack([_v.sample(*_v.grid(geo, i)[:3], Q) for i in sel], 1)
    if method == "volume":
        outs = []
        for k, i in enumerate(sel):
            shp = [rx, ry, rz]
            shp[ax] = 2
            arr = np.repeat(vals[:, k].reshape(nv, nu)[..., None], 2, -1)
            # (nv, nu, 2) -> (rz, ry, rx) order
            dims = {u_ax: nu, v_ax: nv, ax: 2}
            full = np.zeros((dims[2], dims[1], dims[0]))
            for c in range(2):
                sl = [slice(None)] * 3
                sl[2 - ax] = c
                plane_arr = vals[:, k].reshape(nv, nu)
                # place plane_arr indexed [v, u] into the remaining axes
                order = sorted([u_ax, v_ax], reverse=True)       # array axes go z, y, x
                if order == [v_ax, u_ax]:
                    full[tuple(sl)] = plane_arr
                else:
                    full[tuple(sl)] = plane_arr.T
            o2 = origin.copy()
            o2[ax] = w - cell[ax] * 0.5
            outs.append(_v.from_grid(full, o2, cell, _v.grid_class(geo, i), _v.name_of(geo, i), False))
            del arr
        res = merge(*outs) if len(outs) > 1 else outs[0]
    else:
        if method == "mesh":
            from .core import Geometry as G
            ii, jj = np.meshgrid(np.arange(nu - 1), np.arange(nv - 1), indexing="xy")
            a = (jj * nu + ii).reshape(-1)
            faces = np.stack([a, a + 1, a + nu + 1, a + nu], 1)
            res = G.from_mesh(Q.astype(np.float32), faces)
        else:
            res = Geometry.from_points(Q.astype(np.float32))
        an = str(attribute).strip() or (_v.name_of(geo, sel[0]) if len(sel) == 1 else "value") or "value"
        res.set(POINT, an, vals.astype(np.float32), owned=True)
        if visualize:
            t = (vals - float(vis_min)) / max(float(vis_max) - float(vis_min), 1e-12)
            if vals.shape[1] == 1:
                from .volvis import ramp_lut
                lut = ramp_lut(ramp if str(ramp).strip() else "0:0,0,0.5 0.25:0,0.6,1 0.5:0.2,1,0.2 0.75:1,0.9,0 1:1,0,0")
                c = lut[np.clip(np.round(np.clip(t[:, 0], 0, 1) * 255), 0, 255).astype(int)] / 255.0
            else:
                c = np.zeros((len(t), 3))
                c[:, :min(3, t.shape[1])] = np.clip(t[:, :3], 0, 1)
            res.set(POINT, "Cd", c.astype(np.float32), owned=True)
    if keep:
        return merge(geo, res)
    return res


# ═══════════════════════════════════════════════════════════ Splice
def splice(geo, group="", delete_original=True):
    from .ops import merge, delete_prims
    sel = _sel(geo, group)
    by = {}
    for i in sel:
        by.setdefault(_v.name_of(geo, i), []).append(i)
    parts, used = [], []
    for nm, ids in by.items():
        if len(ids) < 2 and delete_original:
            continue
        v0, o0, c0 = _v.grid(geo, ids[0])
        los, his, ctrs = [], [], []
        for j in ids:
            vj, oj, cj = _v.grid(geo, j)
            if not np.allclose(cj, c0, rtol=1e-5):
                raise ValueError("Volume Splice: the volumes must have the same voxel size")
            los.append(oj)
            his.append(oj + cj * (np.array(_v.res_of(vj)) - 1))
            ctrs.append((los[-1] + his[-1]) / 2)
        lo, hi = np.min(los, 0), np.max(his, 0)
        k0 = np.round((lo - o0) / c0).astype(int)
        k1 = np.round((hi - o0) / c0).astype(int)
        n = k1 - k0 + 1
        origin = o0 + k0 * c0
        shp = (n[2], n[1], n[0]) + v0.shape[3:]
        out = np.zeros(shp)
        best = np.full(shp[:3], np.inf)
        Q = _v.world_points(origin, c0, shp[:3])
        for j, ctr in zip(ids, ctrs):
            vj, oj, cj = _v.grid(geo, j)
            off = np.round((oj - origin) / c0).astype(int)
            rxj, ryj, rzj = _v.res_of(vj)
            sl = (slice(off[2], off[2] + rzj), slice(off[1], off[1] + ryj), slice(off[0], off[0] + rxj))
            d = np.linalg.norm(Q[sl] - ctr, axis=-1)
            better = d < best[sl]
            region = out[sl]
            region[better] = np.asarray(vj)[better]
            out[sl] = region
            b = best[sl]
            b[better] = d[better]
            best[sl] = b
        parts.append(_v.from_grid(out, origin, c0, _v.grid_class(geo, ids[0]), nm, _v.is_vdb(geo, ids[0])))
        used.extend(ids)
    keep = np.ones(geo.nprims, bool)
    if delete_original:
        keep[used] = False
    base = delete_prims(geo, keep) if not keep.all() else geo
    allp = ([base] if (base.npoints or base.nprims) else []) + parts
    return merge(*allp) if len(allp) > 1 else (allp[0] if allp else Geometry())


# ═══════════════════════════════════════════════════════════ Stamp
def stamp(dest, points, stamps, group="", point_group="", merge_method="maximum"):
    """Each stamp volume (input 3, matched to the destination by name) is copied to every point (translate by P,
    scale by pscale, rotate by orient) and composited into the destination."""
    from . import groups as _grp
    if merge_method not in STAMP_MERGE:
        raise ValueError(f"Merge Method must be one of {STAMP_MERGE}")
    if stamps is None or not _v.volume_prims(stamps):
        raise ValueError("Volume Stamp needs the volumes to stamp in the third input")
    m = _grp.resolve(points, POINT, point_group)
    P = np.asarray(points.get(POINT, "P"), np.float64)[m]
    ps = points.get(POINT, "pscale")
    S = np.asarray(ps, np.float64)[m, 0] if ps is not None else np.ones(len(P))
    orient = points.get(POINT, "orient")
    g = dest.copy()
    for i in _sel(dest, group):
        vox, origin, cell = _v.grid(dest, i)
        nm = _v.name_of(dest, i)
        si = [j for j in _v.volume_prims(stamps) if _v.name_of(stamps, j) == nm] or _v.volume_prims(stamps)[:1]
        sv, so, sc = _v.grid(stamps, si[0])
        Q = _v.world_points(origin, cell, vox.shape[:3]).reshape(-1, 3)
        A = np.asarray(vox, np.float64).reshape(len(Q), -1)
        acc = A.copy()
        cnt = np.ones(len(Q))
        for k, (p, s) in enumerate(zip(P, S)):
            L = Q - p
            if orient is not None:
                from .xform import quat_to_mat
                R = np.asarray(quat_to_mat(np.asarray(orient, np.float64)[m][k:k + 1]), np.float64)
                R = R.reshape(-1, 3, 3)[0]
                # quat_to_mat is column form (p_world = R p_local), so in rows p_local = p_world @ R
                L = L @ R
            L = L / max(float(s), 1e-12)
            b = _v.sample(sv, so, sc, L, outside=0.0).reshape(len(Q), -1)
            u = _v.to_index(so, sc, L)
            inside = ((u >= 0) & (u <= np.array(_v.res_of(sv)) - 1)).all(1)
            if merge_method == "maximum":
                acc = np.where(inside[:, None], np.maximum(acc, b), acc)
            elif merge_method == "minimum":
                acc = np.where(inside[:, None], np.minimum(acc, b), acc)
            elif merge_method == "add":
                acc = acc + np.where(inside[:, None], b, 0.0)
            elif merge_method == "copy":
                acc = np.where(inside[:, None], b, acc)
            else:
                acc = acc + np.where(inside[:, None], b, 0.0)
                cnt = cnt + inside
        if merge_method == "average":
            acc = acc / cnt[:, None]
        _v.set_voxels(g, i, acc.reshape(vox.shape), mask="keep")
    return g


# ═══════════════════════════════════════════════════════════ Trail
def trail(points, vel_geo, point_group="", vel_name="", method="time", length=1.0, use_cfl=False,
          cfl=1.0, steps=10, max_steps=1000, keep=False, visualize=True, detect_range=True,
          vmax=1.0, ramp=""):
    """
    One polyline per point: RK2 through the velocity. method time: Trail Length is seconds; distance: Trail Length
    is the path length. Fixed Number of Steps, or with Use CFL steps of CFL × voxel size / |v| (capped at Max Steps).
    traillen point attribute scales the length. Visualize: Cd from the speed through a ramp (0 .. Maximum).
    """
    from . import groups as _grp
    from .vdbfield import _velocity
    from .ops import merge
    vel = _velocity(vel_geo, vel_name)
    vi = _v.volume_prims(vel_geo)
    vs = float(np.min(_v.grid(vel_geo, vi[0])[2])) if vi else 0.1
    m = _grp.resolve(points, POINT, point_group)
    P0 = np.asarray(points.get(POINT, "P"), np.float64)[m]
    tl = points.get(POINT, "traillen")
    Ls = (np.asarray(tl, np.float64)[m, 0] if tl is not None else np.ones(len(P0))) * float(length)
    paths, speeds = [], []
    for p, L in zip(P0, Ls):
        X = [p.copy()]
        sp = [float(np.linalg.norm(vel(p[None])[0]))]
        done = 0.0
        x = p.copy()
        nmax = int(max_steps) if use_cfl else int(steps)
        for _ in range(max(1, nmax)):
            v1 = vel(x[None])[0]
            s1 = float(np.linalg.norm(v1))
            if s1 < 1e-12:
                break
            if use_cfl:
                dt = float(cfl) * vs / s1
            else:
                dt = (L / int(steps)) if method == "time" else (L / int(steps)) / s1
            if method == "time":
                dt = min(dt, L - done)
            else:
                dt = min(dt, (L - done) / s1)
            if dt <= 1e-12:
                break
            v2 = vel((x + 0.5 * dt * v1)[None])[0]
            x = x + dt * v2
            done += dt if method == "time" else dt * float(np.linalg.norm(v2))
            X.append(x.copy())
            sp.append(float(np.linalg.norm(v2)))
            if done >= L - 1e-9:
                break
        paths.append(np.asarray(X))
        speeds.append(np.asarray(sp))
    pts = np.concatenate(paths) if paths else np.zeros((0, 3))
    g = Geometry.from_points(pts.astype(np.float32))
    sizes = np.array([len(p) for p in paths], np.int32)
    off = np.concatenate([[0], np.cumsum(sizes)]).astype(np.int32)
    g.set_topology(np.arange(len(pts), dtype=np.int32), off, np.zeros(len(paths), bool),
                   np.zeros(len(paths), np.uint8))
    if visualize and len(pts):
        sp = np.concatenate(speeds)
        top = float(sp.max()) * float(vmax) if detect_range else float(vmax)
        from .volvis import ramp_lut
        lut = ramp_lut(ramp if str(ramp).strip() else "0:0,0,0.5 0.25:0,0.6,1 0.5:0.2,1,0.2 0.75:1,0.9,0 1:1,0,0")
        c = lut[np.clip(np.round(np.clip(sp / max(top, 1e-12), 0, 1) * 255), 0, 255).astype(int)] / 255.0
        g.set(POINT, "Cd", c.astype(np.float32), owned=True)
    if keep:
        return merge(points, g)
    return g


# ═══════════════════════════════════════════════════════════ Velocity
def _curl_noise(Q, size, scale, octaves, grain, offset, attenuation, seed=0):
    from .attribnoise import perlin
    h = 1e-3 * max(float(size), 1e-6)
    out = np.zeros_like(Q)
    amp = 1.0
    freq = 1.0 / max(float(size), 1e-9)
    for _ in range(max(1, int(octaves))):
        def pot(X, k):
            return np.asarray(perlin((X + np.asarray(offset)) * freq + 31.7 * k, int(seed)), np.float64).reshape(-1)
        dpot = []
        for k in range(3):
            dpot.append([(pot(Q + e, k) - pot(Q - e, k)) / (2 * h)
                         for e in (np.array([h, 0, 0]), np.array([0, h, 0]), np.array([0, 0, h]))])
        # curl of the potential (p0, p1, p2): (∂p2/∂y − ∂p1/∂z, ∂p0/∂z − ∂p2/∂x, ∂p1/∂x − ∂p0/∂y)
        c = np.stack([dpot[2][1] - dpot[1][2], dpot[0][2] - dpot[2][0], dpot[1][0] - dpot[0][1]], 1)
        out += amp ** float(attenuation) * c / freq
        amp *= float(grain)
        freq *= 2.0
    return out * float(scale)


def velocity(geo, points=None, mask=None, group="", uniform=False, constant=(0, 0, 0),
             vortex=False, center=(0, 0, 0), direction=(0, 1, 0), angular=1.0, vortex_radius=0.0,
             curl=False, curl_scale=1.0, swirl_size=1.0, grain=0.5, curl_offset=(0, 0, 0),
             attenuation=1.0, turbulence=3, seed=0, point_vel=False, attribute="v", point_scale=1.0,
             extrap_dist=1.0, apply_mask=False, mask_group="", expansion=0.0, comparison="greater",
             cutoff=0.0):
    sel = _sel(geo, group)
    vecs = [i for i in sel if _v.is_vector(geo.pdata(i, "voxels"))]
    sca = [i for i in sel if not _v.is_vector(geo.pdata(i, "voxels"))]
    if vecs:
        targets = [("vec", vecs[0])]
        vox, origin, cell = _v.grid(geo, vecs[0])
        base = np.asarray(vox, np.float64)
    elif len(sca) >= 3:
        targets = [("sca", sca[:3])]
        vox, origin, cell = _v.grid(geo, sca[0])
        base = np.stack([np.asarray(_v.sample(*_v.grid(geo, j), _v.world_points(origin, cell, vox.shape).reshape(-1, 3)),
                                    np.float64).reshape(vox.shape) for j in sca[:3]], -1)
    else:
        raise ValueError("Volume Velocity needs a vector volume or three scalar volumes (vel.x, vel.y, vel.z)")
    shp = base.shape[:3]
    Q = _v.world_points(origin, cell, shp).reshape(-1, 3)
    add = np.zeros((len(Q), 3))
    if uniform:
        add += np.asarray(constant, np.float64)
    if vortex:
        a = np.asarray(direction, np.float64)
        a = a / max(np.linalg.norm(a), 1e-12)
        r = Q - np.asarray(center, np.float64)
        rp = r - (r @ a)[:, None] * a
        v = np.cross(a, rp) * float(angular)
        if float(vortex_radius) > 0:
            dist = np.linalg.norm(rp, axis=1)
            v = np.where((dist <= float(vortex_radius))[:, None], v, 0)
        add += v
    if curl:
        add += _curl_noise(Q, swirl_size, curl_scale, turbulence, grain, curl_offset, attenuation, seed)
    if point_vel and points is not None and points.npoints:
        from scipy.spatial import cKDTree
        Pp = np.asarray(points.get(POINT, "P"), np.float64)
        va = points.get(POINT, attribute)
        if va is None:
            raise ValueError(f"Points have no '{attribute}' attribute")
        dist, idx = cKDTree(Pp).query(Q, distance_upper_bound=float(extrap_dist))
        ok = np.isfinite(dist)
        pv = np.zeros((len(Q), 3))
        pv[ok] = np.asarray(va, np.float64)[idx[ok], :3]
        add += pv * float(point_scale)
    out = base.reshape(-1, 3) + add
    if apply_mask and mask is not None:
        mk = _mask_from(mask, mask_group, origin, cell, shp)
        if mk is not None:
            if float(expansion) > 0:
                nd = _nd()
                r = max(1, int(np.ceil(float(expansion) / float(np.min(cell)))))
                mk = nd.maximum_filter(mk, 2 * r + 1, mode="nearest")
            keepm = {"greater": mk > float(cutoff), "less": mk < float(cutoff),
                     "greaterequal": mk >= float(cutoff), "lessequal": mk <= float(cutoff)}[comparison]
            out = np.where(keepm.reshape(-1)[:, None], out, 0.0)
    out = out.reshape(shp + (3,))
    g = geo.copy()
    kind, t = targets[0]
    if kind == "vec":
        _v.set_voxels(g, t, out, mask="keep")
    else:
        for k, j in enumerate(t):
            vj, oj, cj = _v.grid(geo, j)
            if vj.shape == shp:
                _v.set_voxels(g, j, out[..., k], mask="keep")
            else:
                Qj = _v.world_points(oj, cj, vj.shape).reshape(-1, 3)
                _v.set_voxels(g, j, _v.sample(out[..., k], origin, cell, Qj).reshape(vj.shape), mask="keep")
    return g


def velocity_from_curves(curves, surface=None, reference=None, voxel_size=0.1, radius=0.5,
                         radius_mode="constant", min_curves=3, radius_mult=1.0, smooth=False,
                         voxel_radius=1, blur_iters=1, use_weight=False, weight_attrib="",
                         name="vel"):
    """For each voxel: tangent average of curve segments within Radius, weighted by (1 − d / R)² (× curve weight)."""
    P = np.asarray(curves.get(POINT, "P"), np.float64)
    A, B, Wt = [], [], []
    wa = curves.get(PRIM, weight_attrib) if use_weight and weight_attrib else None
    for i in range(curves.nprims):
        idx = curves.prim_points(i)
        if len(idx) < 2:
            continue
        A.append(P[idx[:-1]])
        B.append(P[idx[1:]])
        Wt.append(np.full(len(idx) - 1, float(wa[i, 0]) if wa is not None else 1.0))
    if not A:
        raise ValueError("Volume Velocity from Curves needs curves")
    A, B, Wt = np.concatenate(A), np.concatenate(B), np.concatenate(Wt)
    T = B - A
    T = T / np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-12)
    if reference is not None and _v.volume_prims(reference):
        vox, origin, cell = _v.grid(reference, _v.volume_prims(reference)[0])
        shp = vox.shape[:3]
    else:
        lo = np.minimum(A, B).min(0) - float(radius) * float(radius_mult)
        hi = np.maximum(A, B).max(0) + float(radius) * float(radius_mult)
        if surface is not None and surface.npoints:
            slo, shi = _v.bounds(surface)
            lo, hi = np.minimum(lo, slo), np.maximum(hi, shi)
        vs = float(voxel_size)
        n = np.maximum(np.ceil((hi - lo) / vs - 1e-9).astype(int) + 1, 2)
        origin, cell, shp = lo, np.full(3, vs), (n[2], n[1], n[0])
    Q = _v.world_points(origin, cell, shp).reshape(-1, 3)
    vel = np.zeros((len(Q), 3))
    chunk = max(1, int(2e6 // max(len(A), 1)))
    for s0 in range(0, len(Q), chunk):
        d, _ = _seg_dist(Q[s0:s0 + chunk], A, B)
        if radius_mode == "minimum":
            k = min(int(min_curves), d.shape[1])
            R = np.partition(d, k - 1, axis=1)[:, k - 1:k] * float(radius_mult) + 1e-9
        else:
            R = float(radius) * float(radius_mult)
        w = np.clip(1.0 - d / R, 0, 1) ** 2 * Wt[None]
        s = w.sum(1, keepdims=True)
        vel[s0:s0 + chunk] = (w @ T) / np.maximum(s, 1e-12)
    vel = vel.reshape(shp + (3,))
    if smooth:
        nd = _nd()
        for _ in range(int(blur_iters)):
            vel = np.stack([nd.uniform_filter(vel[..., k], 2 * int(voxel_radius) + 1, mode="nearest")
                            for k in range(3)], -1)
    return _v.from_grid(vel, origin, cell, _v.CLASS_NONE, name, True, 0.0)


def velocity_from_surface(surface, voxel_size=0.1, ext_band=0.2, iterations=500,
                          div_attrib="divergence", name="vel", collision=False,
                          collision_name="collision"):
    """
    Inside a closed surface: the divergence attribute on the surface (point or prim, nearest face) is a source near
    the surface; solve ∇²p = d inside with zero flux at the surface, v = ∇p -- flow leaves high-divergence regions
    for low ones and stays tangential at the surface. Optional collision SDF.
    """
    from .vdbsdf import from_polygons
    from .vdbfield import _cg, _lap_apply, gradient
    from .ops import merge
    sdfg = from_polygons(surface, voxel_size, ext_band / float(voxel_size) + 1, 1000, False, True)
    vox, origin, cell = _v.grid(sdfg, 0)
    phi = np.asarray(vox, np.float64)
    inside = phi < 0
    if not inside.any():
        raise ValueError("Volume Velocity from Surface needs a closed surface")
    P = np.asarray(surface.get(POINT, "P"), np.float64)
    tri, corners = surface.triangles(with_corners=True)
    near = inside & (phi > -1.5 * float(voxel_size))
    Q = _v.world_points(origin, cell, phi.shape)[near]
    from .vdbsdf import _closest_tri
    t, bary = _closest_tri(P, tri, Q)
    da = surface.get(POINT, div_attrib)
    if da is not None:
        dv = sum(bary[:, k] * np.asarray(da, np.float64)[tri[t, k], 0] for k in range(3))
    else:
        pa = surface.get(PRIM, div_attrib)
        if pa is None:
            raise ValueError(f"The surface has no '{div_attrib}' attribute (point or prim)")
        dv = np.asarray(pa, np.float64)[surface.vertex_prim()[corners[t, 0]], 0]
    rhs = np.zeros(phi.shape)
    rhs[near] = dv
    rhs[inside] -= rhs[inside].mean()                 # compatibility for the pure Neumann problem
    p, its, res = _cg(-rhs, lambda x: _lap_apply(x, cell, ~inside, False), iterations, 1e-5)
    vel = np.where(inside[..., None], gradient(p, cell), 0.0)
    out = [_v.from_grid(vel, origin, cell, _v.CLASS_NONE, name, True, 0.0, inside)]
    if collision:
        c = sdfg.copy()
        _v.set_name(c, 0, collision_name)
        out.append(c)
    return merge(*out) if len(out) > 1 else out[0]
