"""
VDB nodes, part 2: level sets (SDFs) (pcg106).

  VDB from Polygons       exact SDF of a mesh at a voxel size (volume.signed_distance), narrow band of
                          Exterior / Interior Band voxels (Fill Interior keeps the whole inside), unsigned option,
                          optional fog VDB, optional surface attribute VDBs (point attributes interpolated at the
                          closest surface point, prim attributes of the closest face)
  VDB from Particles      SDF union of spheres (radius = pscale × Particle Scale), particles below Minimum Radius
                          (voxels) ignored, optional velocity trails; fog = sdf -> fog
  VDB from Particle Fluid spheres of Influence Scale × separation, then smoothed and eroded back so the surface sits
                          about where the particles' own spheres are (Houdini's particle-fluid surfacing steps)
  VDB Renormalize SDF     restore |∇φ| = 1 (redistance from the zero crossing), keeping the band
  VDB Rebuild SDF         SDF from the Isovalue contour of any scalar grid, with new interior / exterior bands
  VDB Morph SDF           φ advected with speed = target distance (∂φ/∂t + φ_target |∇φ| = 0, upwind), for Timestep,
                          CFL-limited substeps, renormalised; alpha mask blends
  VDB Fracture            cutter SDFs (input 2, polygons or SDF VDBs, optionally instanced on input-3 points) split
                          each SDF: inside = max(φ, φc), residual = max(φ, −φc)
  VDB to Spheres          greedy sphere packing inside the isovalue contour: candidates scattered inside, repeatedly
                          take the one with the largest radius (= depth below the surface), non-overlapping or not
  VDB Platonic            SDF / fog of a sphere or Platonic solid (exact distance to the solid's mesh)
  VDB Noise               fractal noise added to an SDF near its surface (straight / abs / inverse abs), mask modes
  VDB Extrapolate         expand the narrow band, convert fog to SDF, renormalise, or extend fields off the surface
                          (each voxel takes the value at its closest near-surface voxel = the result of fast sweeping
                          along characteristics)
  VDB Occlusion Mask      voxels hidden from a camera behind the SDF (or fog) along the line of sight
  VDB Ray                 move points to the surface: ray intersection along N (sphere tracing) or closest surface point
  Volume SDF              SDF from any volume's iso contour (exact distance to the extracted contour; Houdini uses fast marching)
"""
from __future__ import annotations

import numpy as np

from .core import POINT, PRIM, VERTEX, Geometry, is_string
from . import vdb as _v

PLATONIC = ("sphere", "tetrahedron", "cube", "octahedron", "dodecahedron", "icosahedron")
NOISE_MODES = ("straight", "abs", "invabs")
NOISE_MASK = ("maskless", "maskgreater", "maskgreaternml", "masklessnml", "maskgreaterabs")
EXTRAP_MODES = ("dilate", "convert", "renormalize", "fogext", "sdfext")
RAY_METHODS = ("rayintersection", "closestpoint")


def _nd():
    from .vdbcore import _scipy_ndimage
    return _scipy_ndimage()


def _band_clip(d, ext, inn, fill_interior=False):
    """Clamp an SDF to [−inn, ext] and return (values, active)."""
    act = (d <= ext) & (d >= -inn)
    if fill_interior:
        act |= d < 0
        out = np.where(d < 0, d, np.minimum(d, ext))
    else:
        out = np.clip(d, -inn, ext)
    return out, act


def sdf_to_fog(d, interior):
    """OpenVDB sdfToFogVolume: 0 outside, ramps 0 -> 1 from the surface to the inner band edge, 1 deeper."""
    return np.clip(-np.asarray(d, np.float64) / max(float(interior), 1e-12), 0.0, 1.0)


def _grid_for(lo, hi, vs, pad):
    lo = np.asarray(lo, np.float64) - pad
    hi = np.asarray(hi, np.float64) + pad
    n = np.maximum(np.ceil((hi - lo) / vs - 1e-9).astype(int) + 1, 2)
    return lo, n


# ═══════════════════════════════════════════════════════════ VDB from Polygons
def from_polygons(geo, voxel_size=0.1, ext_band=3.0, int_band=3.0, world_units=False,
                  fill_interior=False, unsigned=False, build_distance=True, distance_name="surface",
                  build_fog=False, fog_name="density", attributes="", reference=None):
    from .volume import signed_distance
    if not geo.nprims:
        raise ValueError("VDB from Polygons needs polygons")
    tri, _ = geo.triangles(with_corners=True)
    if not len(tri):
        raise ValueError("VDB from Polygons: no faces to convert")
    vs = float(voxel_size)
    if reference is not None and _v.volume_prims(reference):
        r = _v.volume_prims(reference)[0]
        rv, ro, rc = _v.grid(reference, r)
        vs = float(np.min(rc))
    if vs <= 0:
        raise ValueError("Voxel Size must be greater than 0")
    ext = float(ext_band) if world_units else float(ext_band) * vs
    inn = float(int_band) if world_units else float(int_band) * vs
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    used = P[np.unique(tri)]
    lo, n = _grid_for(used.min(0), used.max(0), vs, ext + vs)
    origin = lo
    cell = np.full(3, vs)
    bandv = max(ext, inn) / vs + 1.0
    d = signed_distance(P, tri, origin, cell, (int(n[0]), int(n[1]), int(n[2])),
                        band=bandv, unsigned=bool(unsigned),
                        far_field=bool(fill_interior) and not unsigned)   # otherwise everything is clamped to the band
    d = np.asarray(d, np.float64)
    out = []
    vals, act = _band_clip(d, ext, inn, fill_interior and not unsigned)
    if build_distance:
        out.append(_v.from_grid(vals, origin, cell, _v.CLASS_SDF, distance_name, True, ext, act))
    if build_fog and not unsigned:
        fog = sdf_to_fog(d, inn)
        out.append(_v.from_grid(fog, origin, cell, _v.CLASS_FOG, fog_name, True, 0.0, fog > 0))
    names = [a for a in str(attributes).replace(",", " ").split() if a]
    if names:
        out.extend(_surface_attribs(geo, tri, P, names, origin, cell, d.shape, act))
    if not out:
        raise ValueError("Nothing to output: turn on the distance or fog VDB")
    from .ops import merge
    return merge(*out) if len(out) > 1 else out[0]


def _closest_tri(P, tri, Q):
    """For each query point: (triangle index, barycentric (u, v, w)) of the closest point on the mesh."""
    from .spatial import closest_surface
    ti, _, _, uv = closest_surface(Q, P, tri)
    ti = np.maximum(ti, 0)
    bary = np.stack([1 - uv[:, 0] - uv[:, 1], uv[:, 0], uv[:, 1]], 1)
    return ti, bary


def _surface_attribs(geo, tri, P, names, origin, cell, shape, act):
    """One VDB per attribute: value at the closest surface point (point: barycentric, prim: the face's)."""
    tris, corners = geo.triangles(with_corners=True)
    tri_prim = geo.vertex_prim()[corners[:, 0]]
    Q = _v.world_points(origin, cell, shape).reshape(-1, 3)
    sel = act.reshape(-1)
    Qs = Q[sel]
    t, bary = _closest_tri(P, tris, Qs)
    out = []
    for nm in names:
        for cls in (POINT, VERTEX, PRIM):
            a = geo.get(cls, nm)
            if a is not None and not is_string(a):
                break
        else:
            raise ValueError(f"Surface attribute '{nm}' not found (numeric point / vertex / prim attribute)")
        a = np.asarray(a, np.float64)
        if cls == PRIM:
            val = a[tri_prim[t]]
        elif cls == POINT:
            val = sum(bary[:, k:k + 1] * a[tris[t, k]] for k in range(3))
        else:
            val = sum(bary[:, k:k + 1] * a[corners[t, k]] for k in range(3))
        nc = a.shape[1]
        full = np.zeros((len(Q), nc))
        full[sel] = val
        if nc == 1:
            grid = full.reshape(shape)
        else:
            grid = full[:, :3].reshape(shape + (min(nc, 3),))
            if nc == 2:
                grid = np.concatenate([grid, np.zeros(shape + (1,))], -1)
        out.append(_v.from_grid(grid, origin, cell, _v.CLASS_NONE, nm, True, 0.0, act))
    return out


# ═══════════════════════════════════════════════════════════ particles
def _sphere_union(C, R, origin, cell, shape, band):
    """min_i(|x − c_i| − r_i) on the grid, exact within band of each sphere (others: +band)."""
    rz, ry, rx = shape
    D = np.full(shape, band, np.float64)
    if not len(C):
        return D
    try:
        from scipy.spatial import cKDTree
        tree = cKDTree(C)
        Q = _v.world_points(origin, cell, shape).reshape(-1, 3)
        rmax = float(R.max())
        k = int(min(len(C), 24))
        dist, idx = tree.query(Q, k=k, distance_upper_bound=rmax + band)
        dist = np.asarray(dist).reshape(len(Q), k)
        idx = np.asarray(idx).reshape(len(Q), k)
        ok = np.isfinite(dist)
        Rr = np.where(ok, R[np.minimum(idx, len(R) - 1)], 0.0)
        val = np.where(ok, dist - Rr, np.inf).min(1)
        D = np.minimum(D.reshape(-1), val).reshape(shape)
        # very large particles that the k-nearest query may have missed
        big = np.nonzero(R > np.median(R) * 2.0)[0]
        for b in big[:256]:
            D = np.minimum(D, np.linalg.norm(Q - C[b], axis=1).reshape(shape) - R[b])
        return D
    except ImportError:
        Q = _v.world_points(origin, cell, shape).reshape(-1, 3)
        Df = D.reshape(-1)
        for c, r in zip(C, R):
            Df = np.minimum(Df, np.linalg.norm(Q - c, axis=1) - r)
        return Df.reshape(shape)


def _particles(geo, particle_scale, min_radius_vox, vs, trails=False, vel_scale=1.0,
               trail_res=1.0, group=None):
    from . import groups as _grp
    m = _grp.resolve(geo, POINT, group)
    P = np.asarray(geo.get(POINT, "P"), np.float64)[m]
    ps = geo.get(POINT, "pscale")
    R = (np.asarray(ps, np.float64)[m, 0] if ps is not None else np.full(len(P), 1.0))
    R = R * float(particle_scale)
    keep = R >= float(min_radius_vox) * vs
    ignored = int((~keep).sum())
    P, R = P[keep], R[keep]
    if trails:
        v = geo.get(POINT, "v")
        if v is not None:
            V = np.asarray(v, np.float64)[m][keep] * float(vel_scale)
            Cs, Rs = [P], [R]
            L = np.linalg.norm(V, axis=1)
            step = np.maximum(float(trail_res) * R, 1e-6)
            nmax = int(min(64, np.max(np.ceil(L / step)) if len(L) else 0))
            for k in range(1, nmax + 1):
                t = k * step
                on = t <= L
                if not on.any():
                    break
                f = (t / np.maximum(L, 1e-12))[on]
                Cs.append(P[on] - V[on] * f[:, None])
                Rs.append(R[on] * (1.0 - 0.5 * f))          # trail spheres taper to half the radius
            P, R = np.concatenate(Cs), np.concatenate(Rs)
    return P, R, ignored


def from_particles(geo, voxel_size=0.1, half_band=3.0, world_units=False, particle_scale=1.0,
                   min_radius=1.5, trails=False, vel_scale=1.0, trail_res=1.0,
                   build_distance=True, distance_name="surface", build_fog=False,
                   fog_name="density", group=None):
    vs = float(voxel_size)
    if vs <= 0:
        raise ValueError("Voxel Size must be greater than 0")
    hb = float(half_band) if world_units else float(half_band) * vs
    C, R, ignored = _particles(geo, particle_scale, min_radius, vs, trails, vel_scale,
                               trail_res, group)
    if not len(C):
        raise ValueError("No particle is large enough (check pscale, Particle Scale and Minimum Radius)")
    lo, n = _grid_for((C - R[:, None]).min(0), (C + R[:, None]).max(0), vs, hb + vs)
    cell = np.full(3, vs)
    shape = (int(n[2]), int(n[1]), int(n[0]))
    d = _sphere_union(C, R, lo, cell, shape, hb * 4)
    out = []
    vals, act = _band_clip(d, hb, hb)
    if build_distance:
        out.append(_v.from_grid(vals, lo, cell, _v.CLASS_SDF, distance_name, True, hb, act))
    if build_fog:
        fog = sdf_to_fog(d, hb)
        out.append(_v.from_grid(fog, lo, cell, _v.CLASS_FOG, fog_name, True, 0.0, fog > 0))
    if not out:
        raise ValueError("Nothing to output: turn on the distance or fog VDB")
    from .ops import merge
    g = merge(*out) if len(out) > 1 else out[0]
    return g, {"particles": int(len(C)), "ignored_small": ignored}


def from_particle_fluid(geo, separation=0.1, voxel_scale=0.5, influence_scale=3.0,
                        droplet_scale=1.0, dilate=1.0, smooth=1, erode=1.0, name="surface",
                        group=None):
    """
    Particle fluid surfacing: spheres of radius Influence Scale × separation / 2 (droplets: isolated particles get
    Droplet Scale × separation / 2), voxel size = separation × Voxel Scale; then Dilate (world units = that many
    separations / 2), Smooth (mean-value passes + redistance) and Erode back -- the steps Houdini's node applies.
    """
    from .volops import redistance
    sep = float(separation)
    if sep <= 0:
        raise ValueError("Particle Separation must be greater than 0")
    vs = sep * float(voxel_scale)
    from . import groups as _grp
    m = _grp.resolve(geo, POINT, group)
    C = np.asarray(geo.get(POINT, "P"), np.float64)[m]
    if not len(C):
        raise ValueError("No particles")
    r = sep * 0.5
    R = np.full(len(C), r * float(influence_scale))
    try:
        from scipy.spatial import cKDTree
        cnt = np.array([len(x) for x in cKDTree(C).query_ball_point(C, sep * 1.5)])
        R = np.where(cnt <= 1, r * float(droplet_scale), R)
    except ImportError:
        pass
    pad = float(R.max()) + (float(dilate) + 3) * r + 3 * vs
    lo, n = _grid_for(C.min(0), C.max(0), vs, pad)
    cell = np.full(3, vs)
    shape = (int(n[2]), int(n[1]), int(n[0]))
    d = _sphere_union(C, R, lo, cell, shape, pad * 2)
    # min(|x − c| − R) is only the depth below the nearest sphere inside the union; redistance gives the true SDF
    # of the union, which is then pulled back by (influence radius − particle radius) and dilated / smoothed / eroded
    d = redistance(d, lo, cell)
    d = d + (float(R.mean()) - r)
    d = d - float(dilate) * r
    nd = _nd()
    for _ in range(int(smooth)):
        d = nd.uniform_filter(d, 3, mode="nearest")
        d = redistance(d, lo, cell)
    d = d + float(erode) * r
    hb = 3 * vs
    vals, act = _band_clip(d, hb, hb)
    return _v.from_grid(vals, lo, cell, _v.CLASS_SDF, name, True, hb, act)


# ═══════════════════════════════════════════════════════════ renormalize / rebuild / volume SDF
def renormalize(geo, group="", iterations=1):
    from .volops import redistance
    g = geo.copy()
    for i in _v.select_class(geo, group, _v.CLASS_SDF, "VDB Renormalize SDF"):
        vox, origin, cell = _v.grid(geo, i)
        d = np.asarray(vox, np.float64)
        for _ in range(max(1, int(iterations))):
            d = redistance(d, origin, cell)
        bg = abs(_v.background(geo, i)) or 3 * float(np.min(cell))
        if _v.is_vdb(geo, i):
            d = np.clip(d, -bg, bg)
        _v.set_voxels(g, i, d, mask="keep")
    return g


def rebuild(geo, group="", isovalue=0.0, ext_band=3.0, int_band=3.0, world_units=False,
            fill_interior=False):
    from .volops import redistance
    g = geo.copy()
    for i in _v.select(geo, group, allow_vector=False):
        vox, origin, cell = _v.grid(geo, i)
        f = np.asarray(vox, np.float64) - float(isovalue)
        if _v.grid_class(geo, i) == _v.CLASS_FOG:
            f = -f                                   # fog: dense = inside
        d = redistance(f, origin, cell)
        vs = float(np.min(cell))
        ext = float(ext_band) if world_units else float(ext_band) * vs
        inn = float(int_band) if world_units else float(int_band) * vs
        vals, act = _band_clip(d, ext, inn, fill_interior)
        _v.set_class(g, i, _v.CLASS_SDF)
        _v.set_vdb(g, i, True, bg=ext)
        _v.set_voxels(g, i, vals, mask=None)
        _v.set_active(g, i, act)
    return g


def volume_sdf(geo, group="", iso=0.0, invert=False, use_max=False, max_dist=1.0):
    from .volops import redistance
    g = geo.copy()
    for i in _v.select(geo, group, allow_vector=False):
        vox, origin, cell = _v.grid(geo, i)
        f = np.asarray(vox, np.float64) - float(iso)
        if invert:
            f = -f
        d = redistance(f, origin, cell)
        if use_max:
            d = np.clip(d, -float(max_dist), float(max_dist))
        _v.set_class(g, i, _v.CLASS_SDF)
        if _v.is_vdb(g, i):
            # pcg108: a fog VDB has background 0, which as an SDF background puts every inactive voxel on the surface;
            # give the result a proper narrow band instead (3 voxels, or Max Distance when that is smaller)
            _, _, cell = _v.grid(g, i)
            bg = 3.0 * float(np.max(cell))
            _v.store_sdf(g, i, d, min(bg, float(max_dist)) if use_max else bg)
        else:
            _v.set_voxels(g, i, d, mask="keep")
    return g


# ═══════════════════════════════════════════════════════════ upwind |∇φ| (Godunov)
def _godunov_norm(phi, cell, speed_sign):
    """|∇φ| with the Godunov upwind scheme for ∂φ/∂t + F|∇φ| = 0 (speed_sign = sign of F per voxel)."""
    out = np.zeros_like(phi)
    for ax, h in ((2, cell[0]), (1, cell[1]), (0, cell[2])):
        p = np.pad(phi, [(1, 1) if a == ax else (0, 0) for a in range(3)], mode="edge")
        sl = [slice(None)] * 3
        sl[ax] = slice(2, None)
        fwd = (p[tuple(sl)] - phi) / h
        sl[ax] = slice(0, -2)
        bwd = (phi - p[tuple(sl)]) / h
        pos = np.maximum(np.maximum(bwd, 0) ** 2, np.minimum(fwd, 0) ** 2)
        neg = np.maximum(np.minimum(bwd, 0) ** 2, np.maximum(fwd, 0) ** 2)
        out += np.where(speed_sign > 0, pos, neg)
    return np.sqrt(out)


def morph(source, target, src_group="", tgt_group="", timestep=1.0 / 24, renorm_steps=3,
          mask=None, mask_name="", invert_mask=False, min_mask=0.0, max_mask=1.0):
    from .volops import redistance
    ti = _v.select_class(target, tgt_group, _v.CLASS_SDF, "VDB Morph SDF (target)")
    tv, to, tc = _v.grid(target, ti[0])
    g = source.copy()
    alpha_src = None
    if mask is not None and _v.volume_prims(mask):
        mi = _v.select(mask, mask_name, allow_vector=False)[0]
        alpha_src = _v.grid(mask, mi)
    rep = []
    for i in _v.select_class(source, src_group, _v.CLASS_SDF, "VDB Morph SDF"):
        vox, origin, cell = _v.grid(source, i)
        Q = _v.world_points(origin, cell, vox.shape).reshape(-1, 3)
        tgt = _v.sample(tv, to, tc, Q, outside=_v.outside_value(target, ti[0])).reshape(vox.shape)
        phi = np.asarray(vox, np.float64)
        T = float(timestep)
        dx = float(np.min(cell))
        steps = 0
        t = 0.0
        while t < T - 1e-12 and steps < 2000:
            # the surface moves along its normal with speed −φ_target: inward where the target is outside,
            # outward where it is inside (∂φ/∂t = φ_target |∇φ|)
            F = -tgt
            vmax = float(np.max(np.abs(F))) or 1.0
            dt = min(T - t, 0.5 * dx / vmax)
            phi = phi - dt * F * _godunov_norm(phi, cell, np.sign(F))
            t += dt
            steps += 1
            if renorm_steps and steps % max(1, int(renorm_steps)) == 0:
                phi = redistance(phi, origin, cell)
        if alpha_src is not None:
            av, ao, ac = alpha_src
            a = _v.sample(av, ao, ac, Q).reshape(vox.shape)
            a = np.clip((a - float(min_mask)) / max(float(max_mask) - float(min_mask), 1e-12), 0, 1)
            if invert_mask:
                a = 1 - a
            phi = vox + a * (phi - vox)
        bg = abs(_v.background(source, i))
        if _v.is_vdb(source, i) and bg > 0 and steps:
            # the narrow band moved with the surface: re-derive it
            phi = np.clip(redistance(phi, origin, cell), -bg, bg)
            _v.set_voxels(g, i, phi, mask=None)
            _v.set_active(g, i, np.abs(phi) < bg)
        else:
            _v.set_voxels(g, i, phi, mask="keep")
        rep.append(steps)
    return g, {"substeps": rep}


# ═══════════════════════════════════════════════════════════ Fracture
def fracture(geo, cutters, points=None, group="", separate=False, overlap=False,
             center_cutter=True, random_rotation=False, seed=1, segment=False, fragment_group="",
             visualize=True):
    from .volume import signed_distance
    from .ops import merge
    if cutters is None:
        raise ValueError("VDB Fracture needs cutter geometry in the second input")
    rng = np.random.default_rng(int(seed))
    sel = _v.select_class(geo, group, _v.CLASS_SDF, "VDB Fracture")
    keep = np.ones(geo.nprims, bool)
    keep[sel] = False
    from .ops import delete_prims
    base = delete_prims(geo, keep) if not keep.all() else geo
    pieces = []
    rep = []
    for i in sel:
        vox, origin, cell = _v.grid(geo, i)
        bg = abs(_v.background(geo, i)) or 3 * float(np.min(cell))
        shape = vox.shape
        Q = _v.world_points(origin, cell, shape).reshape(-1, 3)

        cutter_fields = []
        csdf = [j for j in _v.volume_prims(cutters)
                if _v.grid_class(cutters, j) == _v.CLASS_SDF and not _v.is_vector(cutters.pdata(j, "voxels"))]
        if csdf:
            for j in csdf:
                cv, co, cc = _v.grid(cutters, j)
                cutter_fields.append(_v.sample(cv, co, cc, Q, outside=bg).reshape(shape))
        else:
            P = np.asarray(cutters.get(POINT, "P"), np.float64)
            tri, _ = cutters.triangles(with_corners=True)
            comps = [(P, tri)]
            if separate:
                from .topology import connectivity
                lab = np.asarray(connectivity(cutters, POINT, "__piece").get(POINT, "__piece"))[:, 0]
                comps = []
                for k in np.unique(lab):
                    tsel = (lab[tri[:, 0]] == k)
                    comps.append((P, tri[tsel]))
            insts = [None]
            if points is not None and points.npoints:
                insts = list(np.asarray(points.get(POINT, "P"), np.float64))
            for Pc, tc in comps:
                ctr = Pc[np.unique(tc)].mean(0)
                for p in insts:
                    Pm = Pc.copy()
                    if p is not None:
                        if center_cutter:
                            Pm = Pm - ctr
                        if random_rotation:
                            from .ops import euler_matrix
                            ang = rng.uniform(0, 360, 3)
                            Pm = Pm @ np.asarray(euler_matrix(*ang), np.float64).T
                        Pm = Pm + p
                    d = signed_distance(Pm, tc, origin, cell, vox.shape[::-1], band=bg / float(np.min(cell)) + 1)
                    cutter_fields.append(np.asarray(d, np.float64))
        frags = [np.asarray(vox, np.float64)]
        made = 0
        for fc in cutter_fields:
            new = []
            targets = frags if overlap else frags[-1:]
            rest = frags[:-1] if not overlap else []
            for f in targets:
                ins = np.maximum(f, fc)
                out = np.maximum(f, -fc)
                for h in (ins, out):
                    if (h < 0).any():
                        new.append(h)
            if not overlap:
                frags = rest + new
            else:
                frags = new
            made += 1
        name = _v.name_of(geo, i)
        for k, f in enumerate(frags):
            f = np.clip(f, -bg, bg)
            act = np.abs(f) < bg
            p = _v.from_grid(f, origin, cell, _v.CLASS_SDF, name, True, bg, act)
            if visualize:
                p.set(PRIM, "Cd", (rng.random((1, 3)) * 0.7 + 0.3).astype(np.float32), owned=True)
            if fragment_group:
                p.set_group(PRIM, fragment_group, np.ones(1, bool))
            pieces.append(p)
        rep.append({"volume": name or f"#{i}", "fragments": len(frags), "cutters": made})
    if segment:
        from .vdbcore import segment as _seg
        allp = [_seg(p)[0] for p in pieces]
        pieces = allp
    parts = ([base] if (base.npoints or base.nprims) else []) + pieces
    if not parts:
        return Geometry(), {"volumes": rep}
    return (merge(*parts) if len(parts) > 1 else parts[0]), {"volumes": rep}


# ═══════════════════════════════════════════════════════════ VDB to Spheres
def to_spheres(geo, group="", isovalue=0.0, world_units=False, use_rmin=True, rmin=1.0,
               use_rmax=False, rmax=100.0, use_nmin=True, nmin=1, use_nmax=True, nmax=50,
               scatter=10000, overlapping=False, add_id=True, add_pscale=True, seed=1):
    """
    Greedy filling. The inside (φ < isovalue) is sampled with Point Count random candidates; a candidate's radius is
    its depth isovalue − φ (trilinear). Repeatedly the deepest candidate becomes a sphere; non-overlapping:
    the others' radii shrink to their distance to its surface (and vanish if inside it); overlapping: candidates
    inside the new sphere are discarded. Stops at Max Spheres, or when no candidate reaches Min Radius
    (but at least Min Spheres are produced, ignoring Min Radius). Radii in voxels unless world units.
    Output: points with pscale (sphere primitives are not a prim type here -- copy a sphere onto the points).
    """
    rng = np.random.default_rng(int(seed))
    outP, outR, outV = [], [], []
    for i in _v.select(geo, group, allow_vector=False):
        vox, origin, cell = _v.grid(geo, i)
        f = np.asarray(vox, np.float64) - float(isovalue)
        if _v.grid_class(geo, i) == _v.CLASS_FOG:
            f = -f
        # a narrow-band SDF holds −background deep inside; the radius needs the true interior depth
        from .volops import redistance
        f = redistance(f, origin, cell)
        vs = float(np.min(cell))
        inside = np.argwhere(f < 0)
        if not len(inside):
            continue
        pick = inside[rng.integers(0, len(inside), int(scatter))]
        cand = origin + (pick[:, ::-1] + rng.uniform(-0.5, 0.5, (len(pick), 3))) * cell
        r = -_v.sample(f, origin, cell, cand)
        ok = r > 0
        cand, r = cand[ok], r[ok]
        lo_r = (float(rmin) if world_units else float(rmin) * vs) if use_rmin else 0.0
        hi_r = (float(rmax) if world_units else float(rmax) * vs) if use_rmax else np.inf
        r = np.minimum(r, hi_r)
        alive = np.ones(len(cand), bool)
        n = 0
        limit = int(nmax) if use_nmax else 10 ** 9
        need = int(nmin) if use_nmin else 0
        while n < limit and alive.any():
            k = int(np.argmax(np.where(alive, r, -np.inf)))
            if r[k] < lo_r and n >= need:
                break
            c, rk = cand[k], r[k]
            outP.append(c)
            outR.append(rk)
            outV.append(i)
            n += 1
            dist = np.linalg.norm(cand - c, axis=1)
            if overlapping:
                alive &= dist > rk
            else:
                r = np.minimum(r, dist - rk)
                alive &= r > 0
            alive[k] = False
    if not outP:
        return Geometry()
    g = Geometry.from_points(np.asarray(outP, np.float32))
    if add_pscale:
        g.set(POINT, "pscale", np.asarray(outR, np.float32)[:, None], owned=True)
    if add_id:
        g.set(POINT, "id", np.arange(len(outP), dtype=np.int32)[:, None], owned=True)
    return g


# ═══════════════════════════════════════════════════════════ Platonic
def platonic(kind="sphere", radius=1.0, center=(0, 0, 0), voxel_size=0.1, half_width=3.0,
             fog=False, name="surface"):
    if kind not in PLATONIC:
        raise ValueError(f"Solid Type must be one of {PLATONIC}")
    vs = float(voxel_size)
    if vs <= 0:
        raise ValueError("Voxel Size must be greater than 0")
    hb = float(half_width) * vs
    c = np.asarray(center, np.float64)
    R = float(radius)
    lo, n = _grid_for(c - R, c + R, vs, hb + vs)
    cell = np.full(3, vs)
    shape = (int(n[2]), int(n[1]), int(n[0]))
    if kind == "sphere":
        Q = _v.world_points(lo, cell, shape)
        d = np.linalg.norm(Q - c, axis=-1) - R
    else:
        from . import platonic as _pl
        from .volume import signed_distance
        m = _pl.solid(kind, R, tuple(c))
        P = np.asarray(m.get(POINT, "P"), np.float64)
        tri, _ = m.triangles(with_corners=True)
        d = np.asarray(signed_distance(P, tri, lo, cell, (shape[2], shape[1], shape[0]),
                                       band=float(half_width) + 1), np.float64)
    if fog:
        f = sdf_to_fog(d, hb)
        return _v.from_grid(f, lo, cell, _v.CLASS_FOG, "density" if name == "surface" else name,
                            True, 0.0, f > 0)
    vals, act = _band_clip(d, hb, hb)
    return _v.from_grid(vals, lo, cell, _v.CLASS_SDF, name, True, hb, act)


# ═══════════════════════════════════════════════════════════ Noise
def _fbm(P, freq, octaves, lac, gain, rough, seed=0):
    from .attribnoise import perlin
    total = np.zeros(len(P))
    amp, f = 1.0, float(freq)
    for _ in range(int(octaves) + 1):
        total += amp * np.asarray(perlin(P * f, seed), np.float64).reshape(-1)
        amp *= float(gain) * float(rough) if int(octaves) else 1.0
        f *= float(lac)
    return total


def noise(geo, group="", amp=1.0, freq=1.0, octaves=0, lac=2.0, gain=1.0, rough=1.0,
          surface_offset=0.0, noise_offset=(0, 0, 0), mode="straight", mask=None,
          mask_group="", mask_mode="maskless", threshold=0.0, falloff=0.0):
    """
    φ' = φ − amp × n(P) near the surface (|φ − Surface Offset| inside the band), n = fractal Perlin noise:
    straight n, abs |n|, inverse abs 1 − |n|. Positive noise pushes the surface outwards.
    Mask modes: no noise where mask < / > threshold, or scale the noise by the mask (…nml = normalised, abs).
    """
    if mode not in NOISE_MODES:
        raise ValueError(f"Noise Mode must be one of {NOISE_MODES}")
    g = geo.copy()
    msrc = None
    if mask is not None and _v.volume_prims(mask):
        mi = _v.select(mask, mask_group, allow_vector=False)[0]
        msrc = _v.grid(mask, mi)
    for i in _v.select(geo, group, allow_vector=False):
        vox, origin, cell = _v.grid(geo, i)
        Q = _v.world_points(origin, cell, vox.shape).reshape(-1, 3)
        n = _fbm(Q + np.asarray(noise_offset, np.float64), freq, octaves, lac, gain, rough)
        if mode == "abs":
            n = np.abs(n)
        elif mode == "invabs":
            n = 1.0 - np.abs(n)
        w = np.ones(len(Q))
        if msrc is not None:
            mv = _v.sample(*msrc, Q)
            t, fo = float(threshold), max(float(falloff), 1e-12)
            if mask_mode == "maskless":
                w = np.clip((mv - t) / fo + 1.0, 0, 1) if float(falloff) > 0 else (mv >= t).astype(float)
            elif mask_mode == "maskgreater":
                w = np.clip((t - mv) / fo + 1.0, 0, 1) if float(falloff) > 0 else (mv <= t).astype(float)
            elif mask_mode == "maskgreaternml":
                w = np.clip(mv, 0, 1)
            elif mask_mode == "masklessnml":
                w = 1 - np.clip(mv, 0, 1)
            else:
                w = np.clip(np.abs(mv), 0, 1)
        d = np.asarray(vox, np.float64).reshape(-1) - float(amp) * n * w
        _v.set_voxels(g, i, d.reshape(vox.shape), mask="keep")
    return g


# ═══════════════════════════════════════════════════════════ Extrapolate
def extrapolate(geo, group="", mode="dilate", dilate=3, fog_iso=0.5, sdf_iso=0.0,
                ext_group="", pattern="face"):
    """
    dilate       widen the SDF narrow band by Dilation voxels (true distances in the new band)
    convert      fog -> SDF at Fog Isovalue
    renormalize  restore |∇φ| = 1 about Sdf Isovalue
    fogext / sdfext  extend the Extension Group fields off the surface of the source (fog at Fog Isovalue,
                 SDF at Sdf Isovalue): every voxel takes the field value at its closest voxel within half a voxel
                 of the surface (Euclidean distance transform with indices) -- what fast sweeping converges to
    """
    from .volops import redistance
    from .vdbcore import dilate_mask
    if mode not in EXTRAP_MODES:
        raise ValueError(f"Operation must be one of {EXTRAP_MODES}")
    g = geo.copy()
    ids = (_v.select_class(geo, group, _v.CLASS_SDF, "Expand SDF Narrowband") if mode in ("dilate", "renormalize", "sdfext")
           else _v.select_class(geo, group, _v.CLASS_FOG, "Fog extrapolation"))
    for i in ids:
        vox, origin, cell = _v.grid(geo, i)
        f = np.asarray(vox, np.float64)
        vs = float(np.min(cell))
        if mode == "dilate":
            d = redistance(f, origin, cell)
            act = dilate_mask(_v.active(geo, i), int(dilate), pattern)
            bg = abs(_v.background(geo, i)) + int(dilate) * vs
            _v.set_vdb(g, i, True, bg=bg)
            _v.set_voxels(g, i, np.clip(d, -bg, bg), mask=None)
            _v.set_active(g, i, act)
        elif mode == "convert":
            d = redistance(-(f - float(fog_iso)), origin, cell)
            _v.set_class(g, i, _v.CLASS_SDF)
            bg = 3 * vs
            _v.set_vdb(g, i, True, bg=bg)
            _v.set_voxels(g, i, np.clip(d, -bg, bg), mask=None)
            _v.set_active(g, i, np.abs(d) <= bg)
        elif mode == "renormalize":
            d = redistance(f - float(sdf_iso), origin, cell) + float(sdf_iso)
            _v.set_voxels(g, i, d, mask="keep")
        else:
            nd = _nd()
            iso = float(fog_iso) if mode == "fogext" else float(sdf_iso)
            src = f - iso
            if mode == "fogext":
                src = -src
            d = redistance(src, origin, cell)
            near = np.abs(d) <= 0.5 * vs * 1.000001
            if not near.any():
                raise ValueError("The source has no surface at that isovalue")
            _, idx = nd.distance_transform_edt(~near, sampling=np.asarray(cell)[::-1],
                                               return_indices=True)
            names = [n for n in str(ext_group).split() if n]
            targets = _v.select(geo, " ".join(names)) if names else []
            for j in targets:
                if j == i:
                    continue
                vj, oj, cj = _v.grid(geo, j)
                if vj.shape[:3] != vox.shape:
                    raise ValueError("Extension fields must be on the same grid as the source")
                ext = vj[idx[0], idx[1], idx[2]]
                _v.set_voxels(g, j, ext, mask="keep")
    return g


# ═══════════════════════════════════════════════════════════ Occlusion Mask
def occlusion_mask(geo, cam, group="", erode=0, steps=64, name_suffix="_occlusion"):
    """
    A fog VDB on each SDF's grid that is 1 where the voxel is hidden from the camera: the segment from the voxel to the
    eye (orthographic: back along the view direction) passes through the inside of the surface before reaching it.
    Erode shrinks the mask by voxels.
    """
    from .ops import merge
    from .vdbcore import erode_mask
    if cam is None:
        raise ValueError("VDB Occlusion Mask needs a camera")
    eye = np.asarray(cam["eye"], np.float64)
    fwd = np.asarray(cam["forward"], np.float64)
    parts = [geo]
    for i in _v.select(geo, group, allow_vector=False):
        vox, origin, cell = _v.grid(geo, i)
        f = np.asarray(vox, np.float64)
        if _v.grid_class(geo, i) == _v.CLASS_FOG:
            f = 0.5 - f
        Q = _v.world_points(origin, cell, vox.shape).reshape(-1, 3)
        if cam.get("projection") == "orthographic":
            dirs = np.tile(-fwd, (len(Q), 1))
            L = np.full(len(Q), float(np.linalg.norm(cell * np.array(vox.shape[::-1]))))
        else:
            dv = eye - Q
            L = np.linalg.norm(dv, axis=1)
            dirs = dv / np.maximum(L, 1e-12)[:, None]
        start = 1.5 * float(np.min(cell))
        hidden = np.zeros(len(Q), bool)
        for k in range(int(steps)):
            t = start + (L - start) * (k + 0.5) / int(steps)
            pts = Q + dirs * t[:, None]
            s = _v.sample(f, origin, cell, pts, outside=1e9)
            hidden |= (s < 0) & (t < L)
        m = hidden.reshape(vox.shape)
        m = erode_mask(m, int(erode))
        parts.append(_v.from_grid(m.astype(np.float32), origin, cell, _v.CLASS_FOG,
                                  (_v.name_of(geo, i) or "mask") + name_suffix, True, 0.0, m))
    return merge(*parts)


# ═══════════════════════════════════════════════════════════ Ray
def ray(points, sdf, group="", method="rayintersection", isovalue=0.0, transform=True,
        scale=1.0, store_dist=False, far=False, reverse=False, bias=0.0, create_group=False,
        hit_group="rayHitGroup", max_steps=256):
    from . import groups as _grp
    vi = _v.select(sdf, "", allow_vector=False)
    if not vi:
        raise ValueError("VDB Ray needs a scalar VDB in the second input")
    vox, origin, cell = _v.grid(sdf, vi[0])
    f = np.asarray(vox, np.float64) - float(isovalue)
    if _v.grid_class(sdf, vi[0]) == _v.CLASS_FOG:
        f = -f
    g = points.copy()
    sel = _grp.resolve(points, POINT, group)
    P = np.asarray(points.get(POINT, "P"), np.float64)
    Ps = P[sel]
    dist = np.zeros(len(Ps))
    hit = np.zeros(len(Ps), bool)
    vs = float(np.min(cell))
    lo = origin
    hi = origin + cell * (np.array(vox.shape[::-1]) - 1)
    if method == "closestpoint":
        # pcg108: the closest point on the extracted iso surface, exact at any distance. Stepping along the gradient
        # only worked inside the narrow band: farther out a VDB holds the constant background, the gradient is 0 and
        # points did not move while being reported as hits.
        from .volume import make_volume, volume_to_polygons
        from .spatial import closest_surface, tri_soup
        rz, ry, rx = f.shape
        size = cell * np.array([rx - 1, ry - 1, rz - 1])
        tmp = make_volume((rx, ry, rz), tuple(size), tuple(origin + size * 0.5))
        tmp.set_pdata(0, "voxels", np.asarray(f, np.float32))
        surf = volume_to_polygons(tmp, 0.0, close=True)
        X = Ps.copy()
        if surf.nprims and len(Ps):
            tri, _, _ = tri_soup(surf)
            ti, dd, cp, _ = closest_surface(Ps, np.asarray(surf.get(POINT, "P"), np.float64), tri)
            hit = ti >= 0
            X[hit] = cp[hit]
        dist = np.linalg.norm(X - Ps, axis=1)
    else:
        N = points.get(POINT, "N")
        if N is None:
            raise ValueError("Ray Intersection needs point normals N (or use Closest Surface Point)")
        D = np.asarray(N, np.float64)[sel]
        D = D / np.maximum(np.linalg.norm(D, axis=1), 1e-12)[:, None]
        if reverse:
            D = -D
        O = Ps + D * float(bias)
        diag = float(np.linalg.norm(hi - lo))
        # sphere tracing; for the far intersection keep marching after a hit and keep the last crossing
        t = np.zeros(len(Ps))
        s0 = _v.sample(f, origin, cell, O, outside=None)
        sign0 = np.sign(s0)
        sign0[sign0 == 0] = 1
        X = O.copy()
        best = np.full(len(Ps), np.nan)
        for _ in range(int(max_steps)):
            X = O + D * t[:, None]
            s = _v.sample(f, origin, cell, X, outside=None)
            crossed = np.sign(s) != sign0
            if far:
                best = np.where(crossed, t, best)
                sign0 = np.where(crossed, -sign0, sign0)
            else:
                newhit = crossed & np.isnan(best)
                best = np.where(newhit, t, best)
            step = np.maximum(np.abs(s), 0.3 * vs)
            t = t + step
            if np.all(t > diag + np.linalg.norm(O - (lo + hi) / 2, axis=1)):
                break
        hit = ~np.isnan(best)
        # refine each hit by bisection over the last step
        tb = np.where(hit, best, 0.0)
        a, b = np.maximum(tb - 0.3 * vs - 1e-9, 0), tb
        for _ in range(20):
            m = (a + b) / 2
            sm = _v.sample(f, origin, cell, O + D * m[:, None], outside=None)
            sa = _v.sample(f, origin, cell, O + D * a[:, None], outside=None)
            same = np.sign(sm) == np.sign(sa)
            a = np.where(same, m, a)
            b = np.where(same, b, m)
        tt = (a + b) / 2
        X = O + D * tt[:, None]
        dist = np.where(hit, tt + float(bias), 0.0)
        X = np.where(hit[:, None], X, Ps)
    if transform:
        newP = Ps + (X - Ps) * float(scale)
        Pall = P.copy()
        Pall[sel] = newP
        g.set(POINT, "P", Pall.astype(np.float32), owned=True)
    if store_dist:
        da = np.zeros((len(P), 1), np.float32)
        da[sel, 0] = dist
        g.set(POINT, "dist", da, owned=True)
    if create_group:
        m = np.zeros(len(P), bool)
        m[np.nonzero(sel)[0][hit]] = True
        g.set_group(POINT, hit_group, m)
    return g, {"points": int(sel.sum()), "hits": int(hit.sum())}
