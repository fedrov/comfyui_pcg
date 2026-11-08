"""
Scatter and Align (pcg82): scatter points + write the orientation and scale Copy to Points needs, in one step.

    Mode        count     scatter Count points
                density   Density points per unit area
                coverage  derive the count from "each point is a disk of radius pscale, covering a Coverage fraction of the area":
                          N = Coverage · A / (π · E[pscale²])
    pscale      uniformly random between Scale Min..Max
    N           normal of the source face (interpolated point normals if there are any)
    up          the Up parameter projected onto the tangent plane, then randomly rotated around N by ±Rotate Random / 2 degrees
    Tilt        N is further tilted in a random direction by 0..Tilt degrees (grass and rocks should not all stand perfectly upright)
    orient      quaternion of the same frame (+Z = N, +Y = up; same convention as Copy to Points / Orient Along Curve)
    Avoid Overlap  after scattering, Point Relax pushes points apart on the surface by pscale x Overlap Scale so instances do not interpenetrate
Random numbers depend only on Seed: same input, same result.

Added in pcg100 (compared against Houdini Scatter and Align, defaults = old behaviour):
    Mode            surface (scatter on the surface) / existing_points (Add Attributes to Existing Point Cloud:
                    no scattering, write attributes onto the points of the second input). Scatter Points Around Constraint Points is not implemented
    by_spacing      Point Count Method gains By Point Spacing: N = A / ((√3/2)·Spacing²)
    density attrib  Use Density Attribute of By Density; for the other three modes it only affects the distribution
    Emergency Limit point count limit
    Normal / Forward Direction  which instance axis aligns to the normal / forward (old behaviour = Z to normal, Y to forward)
    Min / Max Angle, Round Rotation, Offset Angle  rotation around the normal
    output names    pscale / orient can be renamed or not written; Prim UVW; Tag Name
    Surface Attributes  pattern of attributes interpolated / copied from the surface
"""
from __future__ import annotations

import math

import numpy as np

from .core import Geometry, POINT

SA_MODES = ("count", "density", "coverage", "by_spacing")
SCATTER_MODES = ("surface", "existing_points")
AXES = ("z", "x", "y", "custom")             # Normal Direction: old behaviour is Z to normal
FWD_AXES = ("y", "x", "z", "custom")         # Forward Direction: old behaviour is Y to forward
ROT_RANGES = ("symmetric", "min_max")
_AX = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}
HEX = math.sqrt(3.0) / 2.0                    # in hexagonal close packing each point occupies (√3/2)·d² of area


def _axis(which, custom, label):
    v = np.asarray(_AX[which] if which != "custom" else custom, np.float64)
    n = float(np.linalg.norm(v))
    if not n > 0:
        raise ValueError(f"The Custom vector of {label} cannot be 0")
    return v / n


def instance_basis(normal_axis="z", forward_axis="y", normal_custom=(0, 0, 1),
                   forward_custom=(0, 1, 0)):
    """
    Instance-space (side, forward, normal) column basis I (3x3). The final rotation R = M · Iᵀ sends the instance's normal axis to
    the surface normal and its forward axis to forward. The forward axis is first orthogonalized against the normal axis (with Custom the user's vectors need not be orthogonal);
    if the two are parallel there is no defined orientation, so it errors. With the default (Z, Y), I = identity.
    """
    if normal_axis not in AXES:
        raise ValueError(f"Normal Direction must be one of {AXES}")
    if forward_axis not in FWD_AXES:
        raise ValueError(f"Forward Direction must be one of {FWD_AXES}")
    an = _axis(normal_axis, normal_custom, "Normal Direction")
    af = _axis(forward_axis, forward_custom, "Forward Direction")
    af = af - an * float(af @ an)
    n = float(np.linalg.norm(af))
    if n < 1e-6:
        raise ValueError("Forward Direction cannot be parallel to Normal Direction (pick another axis)")
    af = af / n
    return np.stack([np.cross(af, an), af, an], 1)


def _rot(axis, ang):
    """Rodrigues: (n,3) unit axes, (n,) radians -> (n,3,3)."""
    x, y, z = axis[:, 0], axis[:, 1], axis[:, 2]
    c, s = np.cos(ang), np.sin(ang)
    C = 1 - c
    return np.stack([
        np.stack([c + x * x * C, x * y * C - z * s, x * z * C + y * s], 1),
        np.stack([y * x * C + z * s, c + y * y * C, y * z * C - x * s], 1),
        np.stack([z * x * C - y * s, z * y * C + x * s, c + z * z * C], 1)], 1)


def scatter_align(geo, mode="count", count=200, density=10.0, coverage=0.5,
                  scale_min=0.05, scale_max=0.1, up=(0.0, 1.0, 0.0),
                  rotate_random=360.0, tilt=0.0, avoid_overlap=False,
                  overlap_scale=1.0, relax_iterations=20, group="", seed=0,
                  scatter_mode="surface", points=None, point_group="",
                  spacing=0.1, density_attrib="", emergency_limit=0,
                  normal_axis="z", normal_custom=(0.0, 0.0, 1.0),
                  forward_axis="y", forward_custom=(0.0, 1.0, 0.0),
                  rotation_range="symmetric", min_angle=0.0, max_angle=360.0,
                  round_to=0.0, offset_angle=0.0,
                  radius_attrib="pscale", orient_attrib="orient", prim_uvw_attrib="",
                  tag_name="", point_attribs="", vertex_attribs="",
                  prim_attribs="", detail_attribs=""):
    """
    Returns (points, report).

    With emergency_limit > 0 the point count is clipped to it (0 = unlimited, old behaviour). With round_to > 0 the random rotation angle is rounded to a multiple of it.
    Empty radius_attrib / orient_attrib means that attribute is not written; a non-empty prim_uvw_attrib writes Scatter's
    sourceprimuv (barycentric coordinates within the containing triangle).
    """
    if scatter_mode not in SCATTER_MODES:
        raise ValueError(f"Mode must be one of {SCATTER_MODES}")
    if rotation_range not in ROT_RANGES:
        raise ValueError(f"Rotation Range must be one of {ROT_RANGES}")
    I = instance_basis(normal_axis, forward_axis, normal_custom, forward_custom)
    if scatter_mode == "existing_points":
        return _existing(geo, points, point_group, scale_min, scale_max, up, rotate_random,
                         tilt, seed, I, rotation_range, min_angle, max_angle, round_to,
                         offset_angle, radius_attrib, orient_attrib, tag_name)
    from .scatter import scatter
    from .spatial import tri_soup
    if mode not in SA_MODES:
        raise ValueError(f"Mode must be one of {SA_MODES}")
    s0, s1 = float(scale_min), float(scale_max)
    if not (0 <= s0 <= s1):
        raise ValueError("Requires 0 ≤ Scale Min ≤ Scale Max")
    tri = tri_soup(geo, group)[0]
    if not len(tri):
        raise ValueError("No primitives to scatter on")
    P0 = np.asarray(geo.get(POINT, "P"), np.float64)
    A, B, C = P0[tri[:, 0]], P0[tri[:, 1]], P0[tri[:, 2]]
    area = 0.5 * float(np.linalg.norm(np.cross(B - A, C - A), axis=1).sum())
    dattr = str(density_attrib).strip()
    if mode == "count":
        n = int(count)
    elif mode == "density":
        if dattr:
            # Use Density Attribute: point count = Density x Σ(triangle area x mean of the attribute at its three corners)
            # -- the same weighting as Scatter's density attribute
            d = geo.get(POINT, dattr)
            if d is None:
                raise KeyError(f"No point attribute '{dattr}'")
            d = np.clip(np.asarray(d, np.float64)[tri, 0].mean(1), 0, None)
            wa = float((0.5 * np.linalg.norm(np.cross(B - A, C - A), axis=1) * d).sum())
            n = int(round(float(density) * wa))
        else:
            n = int(round(float(density) * area))
    elif mode == "by_spacing":
        # The docs give no formula. Use hexagonal close packing (points tend toward this arrangement after relaxing): each point occupies (√3/2)·d²
        sp = float(spacing)
        if not sp > 0:
            raise ValueError("By Point Spacing requires Spacing > 0")
        n = int(round(area / (HEX * sp * sp)))
    else:
        e2 = (s0 * s0 + s0 * s1 + s1 * s1) / 3.0            # E[s²] of a uniform distribution
        if not e2 > 0:
            raise ValueError("coverage mode requires Scale Max > 0")
        n = int(round(float(coverage) * area / (math.pi * e2)))
    n = max(0, n)
    rep = {}
    if int(emergency_limit) > 0 and n > int(emergency_limit):
        rep["emergency_limited_from"] = n
        n = int(emergency_limit)
    pa, va = str(point_attribs).strip(), str(vertex_attribs).strip()
    pts = scatter(geo, group=group, force_total_count=True, count=n, seed=int(seed),
                  randomize_order=False, out_normal="N", out_sourceprim="sourceprim",
                  out_uv=str(prim_uvw_attrib).strip(), density_attrib=dattr,
                  # with an empty pattern match_names selects nothing = the old "no interpolation", no separate toggle needed
                  interpolate_attribs=True, interpolate_vertex_attribs=True,
                  point_attribs=pa, vertex_attribs=va, prim_attribs=prim_attribs,
                  detail_attribs=detail_attribs)
    m = pts.npoints
    rep.update({"points": m, "area": area})
    if m == 0:
        return pts, rep
    rng = np.random.default_rng([int(seed), 0x5CA7])
    ps = rng.uniform(s0, s1, m)                              # constant when Min = Max
    rot = _spin(rng, m, rotate_random, rotation_range, min_angle, max_angle, round_to)
    tdir = rng.random(m) * 2 * np.pi
    tamt = np.radians(float(tilt)) * rng.random(m)
    pts.set(POINT, "pscale", ps[:, None].astype(np.float32), owned=True)
    if avoid_overlap and m > 1:
        from .pointrelax import point_relax
        tmp = pts.copy()
        tmp.set(POINT, "pscale", (ps * float(overlap_scale))[:, None].astype(np.float32))
        tmp, rr = point_relax(tmp, geo, int(relax_iterations), 0.0, True, 1.0, 0.5)
        pts.set(POINT, "P", np.asarray(tmp.get(POINT, "P")), owned=False)
        rep["overlap_after"] = rr["overlap_after"]
        # after pushing, the normal is replaced by the face normal at the new position
        from .spatial import closest_surface
        ti, _, _, _ = closest_surface(np.asarray(pts.get(POINT, "P"), np.float64), P0, tri)
        fn = np.cross(B - A, C - A)
        fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-300)
        Nn = np.asarray(pts.get(POINT, "N"), np.float64)
        # keep the original side (normals interpolated from source point normals may be opposite to the face normal; they should not flip)
        fnp = fn[ti] * np.sign(np.einsum("ij,ij->i", fn[ti], Nn) + 1e-300)[:, None]
        pts.set(POINT, "N", fnp.astype(np.float32), owned=True)
    N = np.asarray(pts.get(POINT, "N"), np.float64)
    _write_frame(pts, N, up, rot, tdir, tamt, tilt, offset_angle, I, orient_attrib)
    _finish(pts, ps, radius_attrib, tag_name)
    covered = float(np.pi * (ps ** 2).sum() / area) if area > 0 else 0.0
    rep["coverage"] = covered
    return pts, rep


def _spin(rng, m, rotate_random, rotation_range, min_angle, max_angle, round_to):
    """
    Random rotation angle around the normal (radians). Both modes share **the same** random number r (random stream consumption is the same as the old version):
        symmetric  old behaviour: ±Random Rotation / 2
        min_max    Houdini's Min Angle .. Max Angle, uniform
    With Round to Multiple Of > 0 the angle (degrees) is rounded to a multiple of it (architectural pieces only rotate by multiples of 90°).
    """
    r = rng.random(m)
    if rotation_range == "symmetric":
        deg = None
        rot = np.radians(float(rotate_random)) * (r - 0.5)
    else:
        deg = float(min_angle) + (float(max_angle) - float(min_angle)) * r
        rot = None
    if float(round_to) > 0:
        if deg is None:
            deg = float(rotate_random) * (r - 0.5)
        deg = np.round(deg / float(round_to)) * float(round_to)
    return np.radians(deg) if deg is not None else rot


def _write_frame(pts, N, up, rot, tdir, tamt, tilt, offset_angle, I, orient_attrib):
    """N / up / orient. M is the world [side, forward, normal] column basis; the instance axis mapping is multiplied in last as Iᵀ."""
    from .xform import look_at
    from .curveframe import mat_to_quat
    N = N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-300)
    M = look_at(N, np.asarray(up, np.float64))                # column basis [x, up⊥, N]
    Rz = _rot(N, rot)                                        # random rotation around N
    M = Rz @ M
    if float(offset_angle) != 0:
        # Offset Angle: after the random rotation, rotate by a fixed amount around the normal. Skipped at 0 (multiplying by identity turns -0 into +0,
        # and with default values the output would no longer be bitwise equal to the old output)
        M = _rot(M[:, :, 2], np.full(len(M), np.radians(float(offset_angle)))) @ M
    if float(tilt) != 0:
        tax = np.cos(tdir)[:, None] * M[:, :, 0] + np.sin(tdir)[:, None] * M[:, :, 1]
        M = _rot(tax, tamt) @ M
    pts.set(POINT, "N", M[:, :, 2].astype(np.float32), owned=True)
    pts.set(POINT, "up", M[:, :, 1].astype(np.float32), owned=True)
    if str(orient_attrib).strip():
        R = M @ I.T                                          # default I = identity
        pts.set(POINT, str(orient_attrib).strip(), mat_to_quat(R).astype(np.float32),
                owned=True)


def _finish(pts, ps, radius_attrib, tag_name):
    """pscale renamed / not written; when Tag Name is non-empty, write the string attribute tag."""
    ra = str(radius_attrib).strip()
    if ra != "pscale":
        pts.remove(POINT, "pscale")
        if ra:
            pts.set(POINT, ra, ps[:, None].astype(np.float32), owned=True)
    if str(tag_name).strip():
        pts.set_string(POINT, "tag", np.full(pts.npoints, str(tag_name).strip()))


def _existing(geo, points, point_group, scale_min, scale_max, up, rotate_random, tilt,
              seed, I, rotation_range, min_angle, max_angle, round_to, offset_angle,
              radius_attrib, orient_attrib, tag_name):
    """
    Add Attributes to Existing Point Cloud: no scattering; write pscale / N / up / orient onto the points of points (second input)
    selected by Point Group (the random rules are exactly the same as when scattering).

    The docs do not say where the normal comes from; our choice: if the first input has faces -> the normal of the triangle containing the nearest surface point (and write sourceprim);
    no faces -> the point's own N; failing that -> +Y. Unselected points: existing attributes keep their values, newly created attributes get the "identity
    instance" values (pscale 1, orient identity quaternion, N = +Z, up = +Y), so Copy to Points does not
    squash or twist them. The Point Generation tab (Relax / Remove Overlapping / Emergency Limit) is not used in this mode
    (docs: that tab is unavailable in this mode).
    """
    from .spatial import tri_soup, closest_surface
    from .groups import resolve
    if points is None:
        raise ValueError("Add Attributes to Existing Point Cloud requires the second input (points)")
    s0, s1 = float(scale_min), float(scale_max)
    if not (0 <= s0 <= s1):
        raise ValueError("Requires 0 ≤ Scale Min ≤ Scale Max")
    out = points.copy()
    sel = np.nonzero(resolve(out, POINT, point_group))[0]
    m = len(sel)
    rep = {"points": m, "area": 0.0}
    if m == 0:
        return out, rep
    Q = np.asarray(out.get(POINT, "P"), np.float64)[sel]
    tri, src = (tri_soup(geo)[:2] if geo is not None and geo.nprims
                else (np.zeros((0, 3), np.int64), np.zeros(0, np.int64)))
    if len(tri):
        P0 = np.asarray(geo.get(POINT, "P"), np.float64)
        ti, _, _, _ = closest_surface(Q, P0, tri)
        A, B, C = P0[tri[:, 0]], P0[tri[:, 1]], P0[tri[:, 2]]
        fn = np.cross(B - A, C - A)
        N = fn[ti]
        sp = np.asarray(src, np.int64)[ti]
    elif out.has(POINT, "N"):
        N, sp = np.asarray(out.get(POINT, "N"), np.float64)[sel], None
    else:
        N, sp = np.tile([0.0, 1.0, 0.0], (m, 1)), None
    rng = np.random.default_rng([int(seed), 0x5CA7])
    ps = rng.uniform(s0, s1, m)
    rot = _spin(rng, m, rotate_random, rotation_range, min_angle, max_angle, round_to)
    tdir = rng.random(m) * 2 * np.pi
    tamt = np.radians(float(tilt)) * rng.random(m)

    tmp = Geometry(m)
    _write_frame(tmp, N, up, rot, tdir, tamt, tilt, offset_angle, I, orient_attrib)
    tmp.set(POINT, "pscale", ps[:, None].astype(np.float32))
    _finish(tmp, ps, radius_attrib, tag_name)
    if sp is not None:
        tmp.set(POINT, "sourceprim", sp[:, None].astype(np.int32))
    unit = {"N": [0.0, 0.0, 1.0], "up": [0.0, 1.0, 0.0],
            "sourceprim": [-1], "tag": [""]}
    if str(orient_attrib).strip():
        unit[str(orient_attrib).strip()] = [0.0, 0.0, 0.0, 1.0]
    if str(radius_attrib).strip():
        unit[str(radius_attrib).strip()] = [1.0]
    for k, v in tmp.attribs[POINT].items():
        if k == "P":                                         # the zero P that Geometry(m) comes with
            continue
        if out.has(POINT, k) and out.get(POINT, k).shape[1] == v.shape[1] \
                and out.get(POINT, k).dtype.kind == v.dtype.kind:
            full = out.get_w(POINT, k)
        else:
            full = np.tile(np.asarray(unit.get(k, [0] * v.shape[1]), v.dtype),
                           (out.npoints, 1))
        full[sel] = v
        out.set(POINT, k, full, owned=True)
    return out, rep
