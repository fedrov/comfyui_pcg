"""
VDB nodes, part 3: fields (pcg106).

  VDB Analysis              gradient (scalar -> vector), curvature (mean curvature κ = ∇·(∇φ/|∇φ|)), laplacian,
                            closest point (P − φ∇φ, scalar -> vector), divergence, curl, length, normalize -- central
                            differences in world units; also Volume Analysis
  VDB Smooth                mean / gaussian / median over a cube of ± radius voxels, or offset, for Iterations;
                            alpha mask blends; only active voxels change
  VDB Advect                semi-Lagrangian / mid-point / RK3 / RK4 back-tracing through a velocity VDB for Timestep
                            (Substeps), with a limiter (clamp to the neighbourhood extrema, or revert to first order);
                            SDFs (Respect Grid Class) are renormalised afterwards
  VDB Advect Points         points moved through a velocity field (RK1–4) for Timestep × Substeps; Projection mode
                            moves them to a closest-point field; optional streamlines
  VDB Project Non-Divergent pressure projection: solve ∇²p = ∇·u (conjugate gradient, Neumann at colliders / grid
                            border with the bounding box collider), u − ∇p
  VDB Potential Flow        potential flow around the solid of an SDF in a domain dilated from it: ∇²φ = 0 with
                            ∂φ/∂n = −v_bg·n on the solid, velocity = background + ∇φ
  VDB Combine               the 18 operations of OpenVDB's Combine (A × A Multiplier with B × B Multiplier), B resampled
                            to A's grid; activity union / intersection / difference work on the masks
  VDB Resample              explicit transform (voxel translate / rotate / scale about a pivot), match a reference
                            VDB, voxel size, or voxel scale; SDFs are redistanced (Rebuild SDF)
  VDB Points Group          groups of ordinary points by percentage / count, bounding box or object, SDF range
                            (VDB Points are ordinary points here)
  VDB Scatter               points in the active voxels: total / density / per voxel, Spread, scaled by voxel values;
                            SDF domain interior / iso-surface / narrow band
"""
from __future__ import annotations

import numpy as np

from .core import POINT, PRIM, Geometry
from . import vdb as _v

ANALYSIS_OPS = ("gradient", "curvature", "laplacian", "closestpoint", "divergence", "curl",
                "length", "normalize")
SMOOTH_OPS = ("mean", "gauss", "median", "offset")
ADVECT_SCHEMES = ("semi", "mid", "rk3", "rk4")
LIMITERS = ("none", "clamp", "revert")
COMBINE_OPS = ("copya", "copyb", "inverta", "add", "subtract", "multiply", "divide", "maximum",
               "minimum", "compatimesb", "apluscompatimesb", "sdfunion", "sdfintersect",
               "sdfdifference", "replacewithactive", "topounion", "topointersect",
               "topodifference")
COMBINE_COLLATION = ("pairs", "awithfirstb", "flattena")
RESAMPLE_MODES = ("explicit", "refvdb", "voxelsizeonly", "voxelscaleonly")
SCATTER_MODES = ("count", "density", "pointspervoxel")
SDF_DOMAINS = ("interior", "surface", "band")


def _nd():
    from .vdbcore import _scipy_ndimage
    return _scipy_ndimage()


def _diff(f, cell, ax):
    """∂f/∂(x, y, z)[ax], central differences, world units."""
    return np.gradient(np.asarray(f, np.float64), float(cell[ax]), axis=2 - ax)


def gradient(f, cell):
    return np.stack([_diff(f, cell, a) for a in range(3)], -1)


def divergence(v, cell):
    return sum(_diff(v[..., a], cell, a) for a in range(3))


def curl(v, cell):
    d = lambda c, a: _diff(v[..., c], cell, a)    # noqa: E731
    return np.stack([d(2, 1) - d(1, 2), d(0, 2) - d(2, 0), d(1, 0) - d(0, 1)], -1)


def laplacian(f, cell):
    f = np.asarray(f, np.float64)
    out = np.zeros_like(f)
    for a in range(3):
        p = np.pad(f, [(1, 1) if k == 2 - a else (0, 0) for k in range(3)], mode="edge")
        sl = lambda s: tuple(slice(s, s + f.shape[k]) if k == 2 - a else slice(None)  # noqa: E731
                             for k in range(3))
        out += (p[sl(2)] - 2 * f + p[sl(0)]) / float(cell[a]) ** 2
    return out


def mean_curvature(f, cell):
    g = gradient(f, cell)
    n = g / np.maximum(np.linalg.norm(g, axis=-1, keepdims=True), 1e-12)
    return divergence(n, cell)


# ═══════════════════════════════════════════════════════════ Analysis
def analysis(geo, group="", op="gradient", mask=None, mask_name="", output_name="keep",
             custom_name=""):
    if op not in ANALYSIS_OPS:
        raise ValueError(f"Operator must be one of {ANALYSIS_OPS}")
    g = geo.copy()
    vec_in = op in ("divergence", "curl", "length", "normalize")
    rep = []
    mvol = None
    if mask is not None and _v.volume_prims(mask):
        mi = _v.select(mask, mask_name)[0] if mask_name.strip() else _v.volume_prims(mask)[0]
        mvol = (mask, mi)
    for i in _v.select(geo, group):
        vox, origin, cell = _v.grid(geo, i)
        if vec_in != _v.is_vector(vox):
            continue
        f = np.asarray(vox, np.float64)
        if op == "gradient":
            out = gradient(f, cell)
        elif op == "curvature":
            out = mean_curvature(f, cell)
        elif op == "laplacian":
            out = laplacian(f, cell)
        elif op == "closestpoint":
            P = _v.world_points(origin, cell, f.shape)
            out = P - f[..., None] * gradient(f, cell)
        elif op == "divergence":
            out = divergence(f, cell)
        elif op == "curl":
            out = curl(f, cell)
        elif op == "length":
            out = np.linalg.norm(f, axis=-1)
        else:
            out = f / np.maximum(np.linalg.norm(f, axis=-1, keepdims=True), 1e-12)
        if mvol is not None:
            mg, mi = mvol
            mv, mo, mc = _v.grid(mg, mi)
            Q = _v.world_points(origin, cell, f.shape[:3]).reshape(-1, 3)
            inm = (_v.sample(_v.active(mg, mi).astype(np.float32), mo, mc, Q, "nearest",
                             outside=0.0) > 0.5).reshape(f.shape[:3])
            zero = np.zeros_like(out)
            out = np.where(inm[..., None] if out.ndim == 4 else inm, out, zero)
        nm = _v.name_of(geo, i)
        if output_name == "append":
            nm = f"{nm}_{op}"
        elif output_name == "custom":
            nm = str(custom_name)
        cls = _v.CLASS_NONE
        # replace the prim's voxels (shape may change between scalar and vector)
        g.set_pdata(i, "voxels", np.ascontiguousarray(out, np.float32))
        _v.set_class(g, i, cls)
        _v.set_name(g, i, nm)
        _v.set_background(g, i, 0.0)
        _v.apply_background(g, i)
        rep.append(nm)
    if not rep:
        kind = "vector" if vec_in else "scalar"
        raise ValueError(f"{op} needs a {kind} volume; none selected")
    return g, {"outputs": rep}


# ═══════════════════════════════════════════════════════════ Smooth
def _alpha(mask_src, origin, cell, shape, invert, lo, hi):
    if mask_src is None:
        return None
    mg, mi = mask_src
    mv, mo, mc = _v.grid(mg, mi)
    Q = _v.world_points(origin, cell, shape).reshape(-1, 3)
    a = _v.sample(mv, mo, mc, Q).reshape(shape)
    a = np.clip((a - float(lo)) / max(float(hi) - float(lo), 1e-12), 0, 1)
    return 1 - a if invert else a


def smooth(geo, group="", op="mean", world_units=False, radius=1, world_radius=0.1,
           iterations=4, offset=1.0, mask=None, mask_name="", invert_mask=False, min_mask=0.0,
           max_mask=1.0):
    if op not in SMOOTH_OPS:
        raise ValueError(f"Operation must be one of {SMOOTH_OPS}")
    nd = _nd()
    g = geo.copy()
    msrc = None
    if mask is not None and _v.volume_prims(mask):
        mi = _v.select(mask, mask_name)[0] if mask_name.strip() else _v.volume_prims(mask)[0]
        msrc = (mask, mi)
    for i in _v.select(geo, group):
        vox, origin, cell = _v.grid(geo, i)
        r = int(np.ceil(float(world_radius) / float(np.min(cell)) - 1e-9)) if world_units else int(radius)
        r = max(r, 0)
        act = _v.active(geo, i)
        a0 = np.asarray(vox, np.float64)

        def one(f):
            for _ in range(int(iterations)):
                if op == "offset":
                    f = f + float(offset)
                elif r == 0:
                    break
                elif op == "mean":
                    f = nd.uniform_filter(f, 2 * r + 1, mode="nearest")
                elif op == "gauss":
                    f = nd.gaussian_filter(f, sigma=r / 2.0, truncate=2.0, mode="nearest")
                else:
                    f = nd.median_filter(f, size=2 * r + 1, mode="nearest")
            return f
        if _v.is_vector(a0):
            out = np.stack([one(a0[..., k]) for k in range(3)], -1)
        else:
            out = one(a0)
        al = _alpha(msrc, origin, cell, a0.shape[:3], invert_mask, min_mask, max_mask)
        if al is not None:
            out = a0 + (al[..., None] if out.ndim == 4 else al) * (out - a0)
        am = act[..., None] if out.ndim == 4 else act
        out = np.where(am, out, a0)
        _v.set_voxels(g, i, out, mask="keep")
    return g


# ═══════════════════════════════════════════════════════════ Advect
def _velocity(vel_geo, vel_name):
    vi = _v.volume_prims(vel_geo)
    if vel_name.strip():
        vi = _v.select(vel_geo, vel_name)
    vecs = [i for i in vi if _v.is_vector(vel_geo.pdata(i, "voxels"))]
    if vecs:
        vv, vo, vc = _v.grid(vel_geo, vecs[0])
        return lambda Q: _v.sample(vv, vo, vc, Q, outside=0.0 if _v.is_vdb(vel_geo, vecs[0]) else None)
    # three scalar volumes (vel.x, vel.y, vel.z), Houdini's dense-volume layout
    sc = [i for i in vi if not _v.is_vector(vel_geo.pdata(i, "voxels"))]
    if len(sc) >= 3:
        gs = [_v.grid(vel_geo, i) for i in sc[:3]]
        return lambda Q: np.stack([_v.sample(*gg, Q) for gg in gs], 1)
    raise ValueError("No velocity volume: a vector volume, or three scalar volumes (vel.x / vel.y / vel.z)")


def _trace(Q, vel, dt, scheme):
    """Position dt earlier along the field (dt negative traces forward)."""
    if scheme == "semi":
        return Q - dt * vel(Q)
    if scheme == "mid":
        k1 = vel(Q)
        return Q - dt * vel(Q - 0.5 * dt * k1)
    if scheme == "rk3":
        k1 = vel(Q)
        k2 = vel(Q - 0.5 * dt * k1)
        k3 = vel(Q - dt * (2 * k2 - k1))
        return Q - dt * (k1 + 4 * k2 + k3) / 6
    k1 = vel(Q)
    k2 = vel(Q - 0.5 * dt * k1)
    k3 = vel(Q - 0.5 * dt * k2)
    k4 = vel(Q - dt * k3)
    return Q - dt * (k1 + 2 * k2 + 2 * k3 + k4) / 6


def advect(geo, vel_geo, group="", vel_name="", respect_class=True, timestep=1.0 / 24,
           substeps=1, scheme="semi", limiter="revert"):
    from .volops import redistance
    if scheme not in ADVECT_SCHEMES:
        raise ValueError(f"Advection Scheme must be one of {ADVECT_SCHEMES}")
    if limiter not in LIMITERS:
        raise ValueError(f"Limiter must be one of {LIMITERS}")
    vel = _velocity(vel_geo if vel_geo is not None else geo, vel_name)
    nd = _nd()
    g = geo.copy()
    for i in _v.select(geo, group):
        if _v.is_vdb(geo, i):
            # a VDB's narrow band travels with the flow; the dense grid is enlarged by the largest displacement
            vox, origin, cell = _v.grid(geo, i)
            top = origin + cell * (np.array(_v.res_of(vox)) - 1)
            Qs = _v.world_points(origin, cell, vox.shape[:3]).reshape(-1, 3)[::7]
            disp = float(np.max(np.linalg.norm(vel(Qs), axis=1))) * abs(float(timestep)) if len(Qs) else 0.0
            _v.grow(g, i, origin - disp, top + disp)
        vox, origin, cell = _v.grid(g, i)
        f = np.asarray(vox, np.float64)
        Q = _v.world_points(origin, cell, f.shape[:3]).reshape(-1, 3)
        dt = float(timestep) / max(1, int(substeps))
        out_v = _v.outside_value(g, i)
        moved_mask = _v.has_mask(g, i)
        act = _v.active(g, i).astype(np.float32)
        for _ in range(max(1, int(substeps))):
            src = _trace(Q, vel, dt, scheme)
            if moved_mask:
                # the active region travels with the content (OpenVDB dilates the topology to follow the flow)
                act = _v.sample(act, origin, cell, src, "nearest", outside=0.0).reshape(act.shape)
            new = _v.sample(f, origin, cell, src, outside=out_v).reshape(f.shape)
            if scheme != "semi" and limiter != "none":
                first = _v.sample(f, origin, cell, Q - dt * vel(Q), outside=out_v).reshape(f.shape)
                comps = [new] if new.ndim == 3 else [new[..., k] for k in range(new.shape[3])]
                fc = [f] if f.ndim == 3 else [f[..., k] for k in range(f.shape[3])]
                fs = [first] if first.ndim == 3 else [first[..., k] for k in range(first.shape[3])]
                res = []
                for nv, ff, fi in zip(comps, fc, fs):
                    lo = nd.minimum_filter(ff, 3, mode="nearest")
                    hi = nd.maximum_filter(ff, 3, mode="nearest")
                    # extrema of the source neighbourhood, sampled back at the departure points
                    lo_s = _v.sample(lo, origin, cell, src).reshape(ff.shape)
                    hi_s = _v.sample(hi, origin, cell, src).reshape(ff.shape)
                    bad = (nv < lo_s) | (nv > hi_s)
                    if limiter == "clamp":
                        res.append(np.clip(nv, lo_s, hi_s))
                    else:
                        res.append(np.where(bad, fi, nv))
                new = res[0] if len(res) == 1 else np.stack(res, -1)
            f = new
        if respect_class and _v.grid_class(geo, i) == _v.CLASS_SDF and not _v.is_vector(f):
            f = redistance(f, origin, cell)
            bg = abs(_v.background(geo, i))
            if _v.is_vdb(geo, i) and bg > 0:
                f = np.clip(f, -bg, bg)
                _v.set_voxels(g, i, f, mask=None)
                _v.set_active(g, i, np.abs(f) < bg)
                continue
        if moved_mask:
            _v.set_voxels(g, i, f, mask=None)
            _v.set_active(g, i, act > 0.5)
        else:
            _v.set_voxels(g, i, f, mask="keep")
    return g


def advect_points(points, vel_geo, group="", vel_name="", operation="advection",
                  integration="rk4", timestep=1.0 / 24, steps=1, cpt=None, cpt_name="",
                  iterations=0, streamlines=False):
    """
    advection: RK1–RK4 through the velocity for Timestep, in Substeps steps. projection: move to the closest point
    stored in a closest-point vector field (VDB Analysis → Closest Point), Iterations extra re-projections.
    constrained: advect, then project. Streamlines: polylines of the path.
    """
    from . import groups as _grp
    order = {"rk1": "semi", "rk2": "mid", "rk3": "rk3", "rk4": "rk4"}.get(integration, "rk4")
    sel = _grp.resolve(points, POINT, group)
    P = np.asarray(points.get(POINT, "P"), np.float64)
    X = P[sel].copy()
    path = [X.copy()]
    if operation in ("advection", "constrained"):
        vel = _velocity(vel_geo, vel_name)
        dt = float(timestep) / max(1, int(steps))
        for _ in range(max(1, int(steps))):
            X = _trace(X, vel, -dt, order)
            path.append(X.copy())
    if operation in ("projection", "constrained"):
        src = cpt if cpt is not None else vel_geo
        ci = [j for j in (_v.select(src, cpt_name) if cpt_name.strip() else _v.volume_prims(src))
              if _v.is_vector(src.pdata(j, "voxels"))]
        if not ci:
            raise ValueError("Projection needs a closest-point vector VDB")
        cv, co, cc = _v.grid(src, ci[0])
        for _ in range(1 + max(0, int(iterations))):
            X = _v.sample(cv, co, cc, X)
        path.append(X.copy())
    g = points.copy()
    Pn = P.copy()
    Pn[sel] = X
    g.set(POINT, "P", Pn.astype(np.float32), owned=True)
    if streamlines and len(path) > 1:
        from .ops import merge
        L = np.stack(path, 1)                         # (n, steps, 3)
        n, k = L.shape[0], L.shape[1]
        lines = Geometry.from_points(L.reshape(-1, 3).astype(np.float32))
        vp = np.arange(n * k, dtype=np.int32)
        lines.set_topology(vp, np.arange(0, n * k + 1, k, dtype=np.int32), np.zeros(n, bool),
                           np.zeros(n, np.uint8))
        return merge(g, lines)
    return g


# ═══════════════════════════════════════════════════════════ Poisson (matrix-free CG)
def _lap_apply(p, cell, solid, dirichlet_border=False):
    """
    −∇²p (7-point) on the fluid voxels. Solid neighbours: zero flux (Neumann). Neighbours beyond the grid:
    zero flux, or p = 0 there when dirichlet_border (flow may leave through the border).
    """
    fluid = ~solid
    out = np.zeros_like(p)
    for a in range(3):
        ax = 2 - a
        h2 = float(cell[a]) ** 2
        n = p.shape[ax]
        for s in (1, -1):
            q = np.roll(p, -s, axis=ax)
            nbf = np.roll(fluid, -s, axis=ax)
            edge = np.zeros(p.shape, bool)
            idx = [slice(None)] * 3
            idx[ax] = (n - 1) if s == 1 else 0
            edge[tuple(idx)] = True
            out += np.where(nbf & ~edge, (p - q) / h2, 0.0)
            if dirichlet_border:
                out += np.where(edge, p / h2, 0.0)
    return np.where(fluid, out, 0.0)


def _cg(b, apply, iters, tol):
    x = np.zeros_like(b)
    r = b - apply(x)
    d = r.copy()
    rr = float((r * r).sum())
    b2 = max(float((b * b).sum()), 1e-30)
    k = 0
    for k in range(int(iters)):
        if rr <= tol * tol * b2:
            break
        Ad = apply(d)
        dAd = float((d * Ad).sum())
        if abs(dAd) < 1e-30:
            break
        a = rr / dAd
        x += a * d
        r -= a * Ad
        rn = float((r * r).sum())
        d = r + (rn / rr) * d
        rr = rn
    return x, k, float(np.sqrt(rr / b2))


def project_non_divergent(geo, group="", iterations=1000, tolerance=1e-4, use_collider=False,
                          collider_type="bbox", collider=None, collider_name="",
                          invert_collider=False, output_pressure=False):
    g = geo.copy()
    rep = []
    extra = []
    for i in _v.select(geo, group):
        vox, origin, cell = _v.grid(geo, i)
        if not _v.is_vector(vox):
            continue
        u = np.asarray(vox, np.float64)
        solid = np.zeros(u.shape[:3], bool)
        if use_collider and collider_type != "bbox" and collider is not None:
            ci = _v.select(collider, collider_name) if collider_name.strip() else _v.volume_prims(collider)
            cv, co, cc = _v.grid(collider, ci[0])
            Q = _v.world_points(origin, cell, u.shape[:3]).reshape(-1, 3)
            if _v.grid_class(collider, ci[0]) == _v.CLASS_SDF:
                inside = _v.sample(cv, co, cc, Q, outside=1e9) < 0
            else:
                inside = _v.sample(_v.active(collider, ci[0]).astype(np.float32), co, cc, Q,
                                   "nearest", outside=0.0) > 0.5
            solid = inside.reshape(u.shape[:3])
            if invert_collider:
                solid = ~solid
        div = divergence(u, cell)
        div = np.where(solid, 0, div)
        # bounding box collider: no flow through the grid border; otherwise p = 0 beyond it
        neumann_border = bool(use_collider) and collider_type == "bbox"
        p, its, res = _cg(-div, lambda x: _lap_apply(x, cell, solid, not neumann_border),
                          iterations, tolerance)
        gp = gradient(p, cell)
        un = u - gp
        un = np.where(solid[..., None], 0, un)
        _v.set_voxels(g, i, un, mask="keep")
        rep.append({"volume": _v.name_of(geo, i), "iterations": its, "residual": res,
                    "max_divergence_before": float(np.abs(div).max()),
                    "max_divergence_after": float(np.abs(np.where(solid, 0, divergence(un, cell))[1:-1, 1:-1, 1:-1]).max())
                    if min(u.shape[:3]) > 2 else 0.0})
        if output_pressure:
            extra.append(_v.from_grid(p, origin, cell, _v.CLASS_NONE, "pressure", True, 0.0))
    if not rep:
        raise ValueError("VDB Project Non-Divergent needs a vector (velocity) volume")
    if extra:
        from .ops import merge
        g = merge(g, *extra)
    return g, {"volumes": rep}


def _fluid_gradient(p, cell, fluid):
    """∇p using only fluid samples: central where both neighbours are fluid, one-sided next to the solid."""
    out = np.zeros(p.shape + (3,))
    for a in range(3):
        ax = 2 - a
        h = float(cell[a])
        pp = np.roll(p, -1, axis=ax)
        pm = np.roll(p, 1, axis=ax)
        fp = np.roll(fluid, -1, axis=ax)
        fm = np.roll(fluid, 1, axis=ax)
        last = np.zeros(p.shape, bool)
        first = np.zeros(p.shape, bool)
        il = [slice(None)] * 3
        il[ax] = -1
        last[tuple(il)] = True
        il[ax] = 0
        first[tuple(il)] = True
        fp &= ~last
        fm &= ~first
        g = np.where(fp & fm, (pp - pm) / (2 * h),
                     np.where(fp, (pp - p) / h, np.where(fm, (p - pm) / h, 0.0)))
        out[..., a] = g
    return out


def potential_flow(geo, group="", dilation_voxels=10, iterations=1000, tolerance=1e-4,
                   background=(1.0, 0.0, 0.0), use_background=True, apply_background=True,
                   output_potential=False, name="vel"):
    """
    The solid = inside of the SDF; the domain = the solid dilated by Dilation Voxels. Solve ∇²φ = 0 in the fluid with
    ∂φ/∂n = −v_bg·n at the solid (no flow through it) and φ = 0 at the outer domain border. Output the flow velocity
    ∇φ (+ the background velocity when Apply Background Velocity) as a vector VDB on the SDF's grid, active in the domain.
    """
    from .vdbcore import dilate_mask
    out = []
    for i in _v.select_class(geo, group, _v.CLASS_SDF, "VDB Potential Flow"):
        # the flow domain reaches Dilation Voxels beyond the solid: enlarge the grid so it fits
        work = _v.copy_prim(geo, i)
        v0, o0, c0 = _v.grid(work, 0)
        sol0 = np.asarray(v0) < 0
        if sol0.any():
            idx = np.argwhere(sol0)
            lo = o0 + idx.min(0)[::-1] * c0 - (int(dilation_voxels) + 2) * c0
            hi = o0 + idx.max(0)[::-1] * c0 + (int(dilation_voxels) + 2) * c0
            if not _v.is_vdb(work, 0):
                _v.set_vdb(work, 0, True, bg=float(np.abs(v0).max()))
            _v.grow(work, 0, lo, hi)
        vox, origin, cell = _v.grid(work, 0)
        solid = np.asarray(vox) < 0
        domain = dilate_mask(solid, int(dilation_voxels), "faceedgevertex")
        fluid = domain & ~solid
        vb = np.asarray(background, np.float64) if use_background else np.zeros(3)
        # Neumann boundary on each fluid face that touches the solid: ∂φ/∂n = −v_bg·n with n the face normal
        # pointing from the solid into the fluid; moved to the right-hand side it is −s·v_bg[a] / h for a solid
        # neighbour at +s along axis a.
        b = np.zeros(solid.shape)
        for a in range(3):
            ax = 2 - a
            for sgn in (1, -1):
                nb = np.roll(solid, -sgn, axis=ax)
                edge = np.zeros(solid.shape, bool)
                idx = [slice(None)] * 3
                idx[ax] = -1 if sgn == 1 else 0
                edge[tuple(idx)] = True
                face = fluid & nb & ~edge
                b += np.where(face, -sgn * vb[a] / float(cell[a]), 0.0)
        nonfluid = ~fluid
        phi, its, res = _cg(b, lambda x: _lap_apply(x, cell, nonfluid, True), iterations, tolerance)
        vel = _fluid_gradient(phi, cell, fluid)
        if apply_background:
            vel = vel + vb
        vel = np.where(fluid[..., None], vel, 0.0)
        out.append(_v.from_grid(vel, origin, cell, _v.CLASS_NONE, name, True, 0.0, fluid))
        if output_potential:
            out.append(_v.from_grid(phi, origin, cell, _v.CLASS_NONE, "potential", True, 0.0, fluid))
    from .ops import merge
    return merge(geo, *out)


# ═══════════════════════════════════════════════════════════ Combine
def _combine_one(a, b, op, aact, bact):
    if op == "copya":
        return a, aact
    if op == "copyb":
        return b, bact
    if op == "inverta":
        return 1.0 - a, aact
    if op == "add":
        return a + b, aact | bact
    if op == "subtract":
        return a - b, aact | bact
    if op == "multiply":
        return a * b, aact | bact
    if op == "divide":
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(b != 0, a / np.where(b == 0, 1, b), a), aact | bact
    if op == "maximum":
        return np.maximum(a, b), aact | bact
    if op == "minimum":
        return np.minimum(a, b), aact | bact
    if op == "compatimesb":
        return (1 - a) * b, aact | bact
    if op == "apluscompatimesb":
        return a + (1 - a) * b, aact | bact
    if op == "sdfunion":
        return np.minimum(a, b), aact | bact
    if op == "sdfintersect":
        return np.maximum(a, b), aact | bact
    if op == "sdfdifference":
        return np.maximum(a, -b), aact | bact
    if op == "replacewithactive":
        bm = bact[..., None] if a.ndim == 4 else bact
        return np.where(bm, b, a), aact | bact
    if op == "topounion":
        return a, aact | bact
    if op == "topointersect":
        return a, aact & bact
    return a, aact & ~bact                            # topodifference


def combine(geo_a, geo_b, agroup="", bgroup="", collation="pairs", op="add", amult=1.0,
            bmult=1.0, interp="linear", deactivate=False, bg_tolerance=0.0, prune=False,
            prune_tolerance=0.0):
    if op not in COMBINE_OPS:
        raise ValueError(f"Operation must be one of {COMBINE_OPS}")
    if collation not in COMBINE_COLLATION:
        raise ValueError(f"Collation must be one of {COMBINE_COLLATION}")
    ia = _v.select(geo_a, agroup)
    g = geo_a.copy()
    if collation == "flattena":
        pairs = [(ia[0], [(geo_a, j) for j in ia[1:]])]
    else:
        if geo_b is None:
            if op in ("copya", "inverta"):
                pairs = [(i, []) for i in ia]
            else:
                raise ValueError(f"{op} needs B volumes in the second input")
        else:
            ib = _v.select(geo_b, bgroup)
            if collation == "awithfirstb":
                pairs = [(i, [(geo_b, ib[0])]) for i in ia]
            else:
                pairs = [(i, [(geo_b, ib[k])] if k < len(ib) else []) for k, i in enumerate(ia)]
    from .ops import delete_prims
    drop = []
    for i, bs in pairs:
        if _v.is_vdb(geo_a, i) and bs and not op.startswith("topo") and op not in ("copya", "inverta"):
            # VDB topology is the union of A and B: enlarge A's grid to cover the B grids
            va, oa, ca = _v.grid(g, i)
            los = [oa]
            his = [oa + ca * (np.array(_v.res_of(va)) - 1)]
            for gb, j in bs:
                vb, ob, cb = _v.grid(gb, j)
                los.append(ob)
                his.append(ob + cb * (np.array(_v.res_of(vb)) - 1))
            _v.grow(g, i, np.min(los, 0), np.max(his, 0))
        va, oa, ca = _v.grid(g, i)
        a = np.asarray(va, np.float64) * float(amult)
        aact = _v.active(g, i)
        if not bs:
            if op == "inverta":
                a = 1.0 - a
            _v.set_voxels(g, i, a, mask="keep")
            continue
        Q = _v.world_points(oa, ca, va.shape[:3]).reshape(-1, 3)
        for gb, j in bs:
            vb, ob, cb = _v.grid(gb, j)
            b = _v.sample(vb, ob, cb, Q, "nearest" if interp == "point" else "trilinear",
                          outside=_v.outside_value(gb, j))
            if _v.is_vector(va) and not _v.is_vector(vb):
                b = np.repeat(b[:, None], 3, 1)
            elif _v.is_vector(vb) and not _v.is_vector(va):
                b = np.linalg.norm(b, axis=1)
            b = b.reshape(a.shape) * float(bmult)
            bact = _v.sample(_v.active(gb, j).astype(np.float32), ob, cb, Q, "nearest",
                             outside=0.0).reshape(aact.shape) > 0.5
            a, aact = _combine_one(a, b, op, aact, bact)
            if collation == "flattena":
                drop.append(j)
        _v.set_voxels(g, i, a, mask=None)
        if _v.is_vdb(geo_a, i) or op.startswith("topo") or not aact.all():
            if not _v.is_vdb(g, i):
                _v.set_vdb(g, i, True)
            act = aact
            if deactivate:
                bg = _v.background(g, i)
                near = (np.abs(a - bg) <= float(bg_tolerance))
                if near.ndim == 4:
                    near = near.all(-1)
                act = act & ~near
            _v.set_active(g, i, act)
    if drop:
        keep = np.ones(g.nprims, bool)
        keep[drop] = False
        g = delete_prims(g, keep)
    if prune:
        from .vdbcore import prune_vdb
        g, _ = prune_vdb(g, "", "value", prune_tolerance)
    return g


# ═══════════════════════════════════════════════════════════ Resample
def resample(geo, group="", mode="voxelsizeonly", reference=None, ref_name="", interp="linear",
             translate=(0, 0, 0), rotate=(0, 0, 0), scale=(1, 1, 1), pivot=(0, 0, 0),
             voxel_size=0.1, voxel_scale=1.0, rebuild_sdf=True, xform_vectors=False):
    """
    New grids, same world content. explicit: the new grid is the old one scaled by Scale (voxel size × scale),
    shifted by Translate voxels, rotated about the pivot (the grid stays axis aligned: the content is rotated
    inversely, like resampling into a rotated transform); refvdb: the reference VDB's voxel size and alignment;
    voxelsizeonly / voxelscaleonly: just the voxel size. SDFs are redistanced afterwards (Rebuild SDF).
    """
    from .volops import redistance
    from .ops import euler_matrix
    if mode not in RESAMPLE_MODES:
        raise ValueError(f"Define Transform must be one of {RESAMPLE_MODES}")
    g = geo.copy()
    for i in _v.select(geo, group):
        vox, origin, cell = _v.grid(geo, i)
        rx, ry, rz = _v.res_of(vox)
        hi = origin + cell * (np.array([rx, ry, rz]) - 1)
        Rm = np.eye(3)
        if mode == "voxelsizeonly":
            if float(voxel_size) <= 0:
                raise ValueError("Voxel Size must be greater than 0")
            nc = np.full(3, float(voxel_size))
            lo, up = origin, hi
        elif mode == "voxelscaleonly":
            if float(voxel_scale) <= 0:
                raise ValueError("Voxel Scale must be greater than 0")
            nc = cell * float(voxel_scale)
            lo, up = origin, hi
        elif mode == "refvdb":
            if reference is None or not _v.volume_prims(reference):
                raise ValueError("To Match Reference VDB needs a VDB in the second input")
            j = _v.select(reference, ref_name)[0] if ref_name.strip() else _v.volume_prims(reference)[0]
            rv, ro, rc = _v.grid(reference, j)
            nc = rc
            k0 = np.floor((origin - ro) / rc + 1e-6)
            k1 = np.ceil((hi - ro) / rc - 1e-6)
            lo, up = ro + k0 * rc, ro + k1 * rc
        else:
            S = np.asarray(scale, np.float64)
            if np.any(S <= 0):
                raise ValueError("Scale must be greater than 0")
            nc = cell * S
            lo = origin + np.asarray(translate, np.float64) * nc
            up = lo + (hi - origin)
            if np.any(rotate):
                Rm = np.asarray(euler_matrix(*[float(a) for a in rotate]), np.float64)
        n = np.maximum(np.round((up - lo) / nc).astype(int) + 1, 2)
        Q = _v.world_points(lo, nc, (n[2], n[1], n[0])).reshape(-1, 3)
        if np.any(Rm != np.eye(3)):
            pv = np.asarray(pivot, np.float64)
            Qs = (Q - pv) @ Rm + pv                  # sample the content rotated by R
        else:
            Qs = Q
        out = _v.sample(vox, origin, cell, Qs, "nearest" if interp == "point" else "trilinear",
                        outside=_v.outside_value(geo, i))
        if xform_vectors and _v.is_vector(vox) and np.any(Rm != np.eye(3)):
            out = out @ Rm
        out = out.reshape((n[2], n[1], n[0]) + vox.shape[3:])
        act = None
        if _v.has_mask(geo, i):
            act = _v.sample(_v.active(geo, i).astype(np.float32), origin, cell, Qs, "nearest",
                            outside=0.0).reshape(n[2], n[1], n[0]) > 0.5
        nlo = lo
        if rebuild_sdf and _v.grid_class(geo, i) == _v.CLASS_SDF and not _v.is_vector(out):
            out = redistance(out, nlo, nc)
            bg = abs(_v.background(geo, i))
            if _v.is_vdb(geo, i) and bg > 0:
                out = np.clip(out, -bg, bg)
                act = np.abs(out) < bg
        _v.set_voxels(g, i, out, mask=None)
        _v.set_center_size(g, i, nlo + nc * (n - 1) / 2, nc * (n - 1))
        if act is not None:
            _v.set_active(g, i, act)
    return g


# ═══════════════════════════════════════════════════════════ Points Group / Scatter
def points_group(points, group_name="group1", enable_number=False, number_mode="percentage",
                 percent=10.0, count=5000, seed_attrib="", enable_box=False, bound_mode="boundingbox",
                 bound_geo=None, size=(1, 1, 1), center=(0, 0, 0), enable_sdf=False, sdf=None,
                 sdf_name="", use_min=True, sdf_min=-0.1, use_max=True, sdf_max=0.1, invert=False,
                 seed=0):
    P = np.asarray(points.get(POINT, "P"), np.float64)
    m = np.ones(len(P), bool)
    if enable_box:
        if bound_mode == "boundingobject":
            if bound_geo is None:
                raise ValueError("Bounding Object needs geometry in the second input")
            lo, hi = _v.bounds(bound_geo)
        else:
            c, s = np.asarray(center, np.float64), np.abs(np.asarray(size, np.float64))
            lo, hi = c - s / 2, c + s / 2
        m &= ((P >= lo) & (P <= hi)).all(1)
    if enable_sdf:
        src = sdf if sdf is not None else points
        si = _v.select(src, sdf_name, allow_vector=False)
        if not si:
            raise ValueError("SDF filter: no scalar volume found")
        d = _v.sample(*_v.grid(src, si[0]), P, outside=1e9)
        ok = np.ones(len(P), bool)
        if use_min:
            ok &= d >= float(sdf_min)
        if use_max:
            ok &= d <= float(sdf_max)
        m &= ~ok if invert else ok
    if enable_number:
        idx = np.nonzero(m)[0]
        if seed_attrib and points.get(POINT, seed_attrib) is not None:
            key = np.asarray(points.get(POINT, seed_attrib), np.float64)[idx, 0]
            r = (np.sin(key * 12.9898 + float(seed) * 78.233) * 43758.5453) % 1.0
        else:
            r = np.random.default_rng(int(seed)).random(len(idx))
        if number_mode == "percentage":
            keep = r < float(percent) / 100.0
        else:
            keep = np.zeros(len(idx), bool)
            keep[np.argsort(r)[:max(0, int(count))]] = True
        m[:] = False
        m[idx[keep]] = True
    g = points.copy()
    g.set_group(POINT, group_name, m)
    return g, {"group": group_name, "points": int(m.sum())}


def scatter(geo, group="", keep=False, mode="count", count=5000, ppv=8.0, density=1.0,
            multiply=False, spread=1.0, sdf_domain="band", isovalue=0.0, seed=0, group_name=""):
    rng = np.random.default_rng(int(seed))
    outP = []
    for i in _v.select(geo, group):
        vox, origin, cell = _v.grid(geo, i)
        act = _v.active(geo, i).copy()
        f = np.asarray(vox, np.float64)
        if _v.grid_class(geo, i) == _v.CLASS_SDF and not _v.is_vector(f):
            if sdf_domain == "interior":
                act &= f < float(isovalue)
            elif sdf_domain == "surface":
                act &= np.abs(f - float(isovalue)) <= 0.5 * float(np.min(cell)) * 1.0001
        idx = np.argwhere(act)
        if not len(idx):
            continue
        w = np.ones(len(idx))
        if multiply and not _v.is_vector(f) and _v.grid_class(geo, i) != _v.CLASS_SDF:
            w = np.maximum(f[idx[:, 0], idx[:, 1], idx[:, 2]], 0)
        vvol = float(np.prod(cell))
        if mode == "count":
            n = int(count)
        elif mode == "density":
            n = int(round(float(density) * vvol * float(w.sum())))
        else:
            n = int(round(float(ppv) * float(w.sum())))
        if n <= 0 or w.sum() <= 0:
            continue
        pick = rng.choice(len(idx), size=n, p=w / w.sum())
        jit = rng.uniform(-0.5, 0.5, (n, 3)) * float(spread)
        P = origin + (idx[pick][:, ::-1] + jit) * cell
        if _v.grid_class(geo, i) == _v.CLASS_SDF and sdf_domain == "surface":
            # project onto the iso-surface
            d = _v.sample(f, origin, cell, P) - float(isovalue)
            gr = np.stack([_v.sample(c, origin, cell, P) for c in np.moveaxis(gradient(f, cell), -1, 0)], 1)
            gn = gr / np.maximum(np.linalg.norm(gr, axis=1, keepdims=True), 1e-12)
            P = P - d[:, None] * gn
        outP.append(P)
    from .ops import merge
    pts = Geometry.from_points(np.concatenate(outP).astype(np.float32)) if outP else Geometry()
    if group_name and pts.npoints:
        pts.set_group(POINT, group_name, np.ones(pts.npoints, bool))
    if keep:
        return merge(geo, pts) if pts.npoints else geo.copy()
    return pts
