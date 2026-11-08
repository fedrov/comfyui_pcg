"""
pcg76: points -- Adaptive Prune, Point Replicate, Point Velocity.

━━ Adaptive Prune
Thin points into a set where "every pair is at least some distance apart": each point has its own radius r_i = Radius x
radius attribute (if given), and two points conflict <=> distance < max(r_i, r_j). Greedy from highest to lowest priority: a point
is kept if it does not conflict with any point already kept. The result has two properties (both verified in tests):
  . kept points do not conflict pairwise (spacing >= radius)
  . every deleted point conflicts with some kept point of **higher priority** -- no point "could have been kept but was deleted"
    (a maximal independent set), so density is as high as possible everywhere
Priority: random (reproducible with a fixed Rand Seed) / attribute (larger attribute values kept first, e.g. importance) /
index (lower point numbers kept first). Where the radius attribute is small points are kept dense, where large sparse -- that is the "adaptive".
With Mode = group nothing is deleted; deleted points are only put into a group.

━━ Point Replicate
Scatter a cluster of points around each point: Count of them (or by an integer point attribute), radius Radius x radius attribute (default
pscale, 1 if absent). Shapes: sphere (uniform in the ball), shell (uniform on the sphere), disk (uniform in a disk perpendicular to the point
normal N, +Y if there is no N), gaussian (standard deviation = radius per axis). Each source point seeds its own random numbers with
(Rand Seed, the source point's id) -- when source points have an id attribute, adding, deleting or reordering points does not
change the cluster around other points (stable). New points inherit all attributes of the source point, plus source (source point number).

━━ Point Velocity
Velocity v (and acceleration) from finite differences of positions in the previous / next frames:
  backward  (P − P_prev)/dt          forward  (P_next − P)/dt
  central   (P_next - P_prev)/(2dt)  auto     central if both are present, otherwise whichever side exists
dt = 1/FPS. Points in the previous / next frames are matched to the current frame: index (by point number) or attribute (by id, use this for simulations
where the point count changes). Unmatched points get v = 0 and go into the no_velocity group. When both frames are present, acceleration can also be
computed: accel = (P_next - 2P + P_prev)/dt^2.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, is_string
from .groups import resolve

PRUNE_PRIORITY = ("random", "attribute", "index")
PRUNE_MODES = ("delete", "group")
REPLICATE_SHAPES = ("sphere", "shell", "disk", "gaussian",
                    # pcg100: three with Houdini semantics (generated in local space, then placed on each point by the instancing rules)
                    "circle", "line", "grid")
LOCAL_SHAPES = ("circle", "line", "grid")
REPLICATE_PLANES = ("xy", "yz", "zx")
VELOCITY_STRETCH = ("none", "scaled", "ignore_geometry_scale")
_PLANE_AX = {"xy": (0, 1, 2), "yz": (1, 2, 0), "zx": (2, 0, 1)}   # (in-plane axis a, in-plane axis b, normal axis)
VELOCITY_METHODS = ("auto", "central", "backward", "forward")
VELOCITY_MATCH = ("index", "attribute")


def _P(g):
    return np.asarray(g.get(POINT, "P"), np.float64) if g.npoints else \
        np.zeros((0, 3))


# ═══════════════════════════════════════════════════════════ Adaptive Prune
def adaptive_prune(geo, radius=0.1, radius_attribute="", priority="random",
                   priority_attribute="", rand_seed=0, mode="delete",
                   group_name="pruned", group=""):
    """See the file header. Returns (geometry, report)."""
    from .ops import delete_points
    from .spatial import neighbors_within
    if priority not in PRUNE_PRIORITY:
        raise ValueError(f"Priority must be one of {PRUNE_PRIORITY}")
    if mode not in PRUNE_MODES:
        raise ValueError(f"Mode must be one of {PRUNE_MODES}")
    n = geo.npoints
    P = _P(geo)
    sel = resolve(geo, POINT, group)
    r = np.full(n, float(radius))
    ra = str(radius_attribute).strip()
    if ra:
        a = geo.get(POINT, ra)
        if a is None or is_string(a):
            raise KeyError(f"No numeric attribute '{ra}' on point")
        r = r * np.asarray(a, np.float64)[:, 0]
    if priority == "attribute":
        pa = geo.get(POINT, str(priority_attribute).strip())
        if pa is None or is_string(pa):
            raise KeyError(f"No numeric attribute '{priority_attribute}' on point")
        order = np.lexsort((np.arange(n), -np.asarray(pa, np.float64)[:, 0]))
    elif priority == "random":
        order = np.random.default_rng(int(rand_seed)).permutation(n)
    else:
        order = np.arange(n)
    idx = np.nonzero(sel)[0]
    keep = np.ones(n, bool)
    rmax = float(r[idx].max()) if len(idx) else 0.0
    if len(idx) > 1 and rmax > 0:
        qi, pi, d = neighbors_within(P[idx], P[idx], rmax)
        a, b = idx[qi], idx[pi]
        m = (a != b) & (d < np.maximum(r[a], r[b]))
        a, b = a[m], b[m]
        o = np.argsort(a, kind="stable")
        a, b = a[o], b[o]
        off = np.searchsorted(a, np.arange(n + 1))
        kept = np.zeros(n, bool)
        for i in order.tolist():
            if not sel[i]:
                continue
            nb = b[off[i]:off[i + 1]]
            if kept[nb].any():
                keep[i] = False
            else:
                kept[i] = True
    rep = {"kept": int((keep & sel).sum()), "pruned": int((~keep).sum())}
    if mode == "delete":
        return delete_points(geo, keep), rep
    g = geo.copy()
    g.set_group(POINT, str(group_name).strip() or "pruned", ~keep)
    return g, rep


# ═══════════════════════════════════════════════════════════ Point Replicate
def _local_cloud(shape, k, rng, plane):
    """
    Local point clouds for circle / line / grid (Size = 1, centered at the origin):
        circle  uniform inside a disk of diameter 1 in the plane given by plane
        grid    uniform inside a square of side 1 in the plane given by plane
        line    uniform on a segment of length 1 along plane's **normal axis** (xy -> local Z, i.e. along N / v by default)
    The docs only say Orientation is "the orientation of the 2D / 1D shape in local space", not which axis the line runs along;
    chosen as "the line runs along the alignment vector" (the most common use, for trails, meteors and the like).
    """
    a, b, c = _PLANE_AX[plane]
    q = np.zeros((k, 3))
    if shape == "circle":
        ang = rng.uniform(0, 2 * np.pi, k)
        rad = 0.5 * np.sqrt(rng.uniform(0, 1, k))
        q[:, a], q[:, b] = rad * np.cos(ang), rad * np.sin(ang)
    elif shape == "grid":
        q[:, a], q[:, b] = rng.uniform(-0.5, 0.5, k), rng.uniform(-0.5, 0.5, k)
    else:
        q[:, c] = rng.uniform(-0.5, 0.5, k)
    return q


def point_replicate(geo, count=10, count_attribute="", radius=0.1,
                    radius_attribute="pscale", shape="sphere", rand_seed=0,
                    keep_original=False, group="",
                    orientation="xy", center=(0.0, 0.0, 0.0), size=(1.0, 1.0, 1.0),
                    uniform_scale=1.0, velocity_stretch="none", velocity_scale=1.0,
                    copy_attributes="*", inherit_velocity=1.0, radial_velocity=0.0,
                    source_attribute="source", source_index_attribute="",
                    output_group=""):
    """
    sphere / shell / disk / gaussian are the old behaviour (world-space offsets, radius = Radius x radius attribute).

    circle / line / grid follow Houdini's approach: generated in local space (Center, Size, Uniform Scale,
    Velocity Stretch stretches along local Z), then placed on each source point by Copy to Points' instancing rules (orient / N or v + up /
    pscale / scale / trans / pivot / transform). These three do not read Radius / the radius attribute
    (their counterparts are Size and pscale).

    Attributes (apply to all shapes, defaults = old behaviour):
        copy_attributes        which source point attributes to copy (Houdini's Copy Source Attributes + Attributes),
                               "" = copy none (only P and the source family)
        inherit_velocity       the copies' v is multiplied by this (1 = unchanged)
        radial_velocity        v additionally gets radial x (new point - source point) (created if there is no v)
        source_attribute       source point number (the old behaviour always wrote source; "" = do not write)
        source_index_attribute index within its own cluster (original points that are kept get -1)
        output_group           when non-empty, put the copied points into this group
    """
    if shape not in REPLICATE_SHAPES:
        raise ValueError(f"Shape must be one of {REPLICATE_SHAPES}")
    if orientation not in REPLICATE_PLANES:
        raise ValueError(f"Orientation must be one of {REPLICATE_PLANES}")
    if velocity_stretch not in VELOCITY_STRETCH:
        raise ValueError(f"Velocity Stretch must be one of {VELOCITY_STRETCH}")
    local = shape in LOCAL_SHAPES
    n = geo.npoints
    P = _P(geo)
    sel = np.nonzero(resolve(geo, POINT, group))[0]
    cnt = np.full(n, max(0, int(count)), np.int64)
    ca = str(count_attribute).strip()
    if ca:
        a = geo.get(POINT, ca)
        if a is None or is_string(a):
            raise KeyError(f"No numeric attribute '{ca}' on point")
        cnt = np.maximum(np.rint(np.asarray(a, np.float64)[:, 0]), 0) \
            .astype(np.int64)
    r = np.full(n, float(radius))
    ra = str(radius_attribute).strip()
    if ra and geo.get(POINT, ra) is not None and not is_string(geo.get(POINT, ra)):
        r = r * np.asarray(geo.get(POINT, ra), np.float64)[:, 0]
    ida = geo.get(POINT, "id")
    keys = (np.asarray(ida)[:, 0].astype(np.int64) if ida is not None and
            not is_string(ida) else np.arange(n))
    Nn = geo.get(POINT, "N")
    Nv = (np.asarray(Nn, np.float64)[:, :3] if Nn is not None and
          Nn.shape[1] >= 3 else np.tile([0.0, 1.0, 0.0], (n, 1)))
    src, offs = [], []
    for i in sel.tolist():
        k = int(cnt[i])
        if k <= 0:
            continue
        rng = np.random.default_rng([int(rand_seed) & 0xFFFFFFFF,
                                     int(keys[i]) & 0xFFFFFFFFFFFF])
        if local:
            o = _local_cloud(shape, k, rng, orientation)
        elif shape == "gaussian":
            o = rng.normal(size=(k, 3)) * r[i]
        else:
            if shape == "disk":
                nn = Nv[i] / max(np.linalg.norm(Nv[i]), 1e-300)
                a = np.array([1.0, 0, 0]) if abs(nn[0]) < 0.9 else \
                    np.array([0, 1.0, 0])
                u = np.cross(nn, a)
                u /= np.linalg.norm(u)
                v = np.cross(nn, u)
                ang = rng.uniform(0, 2 * np.pi, k)
                rad = r[i] * np.sqrt(rng.uniform(0, 1, k))
                o = (rad * np.cos(ang))[:, None] * u + \
                    (rad * np.sin(ang))[:, None] * v
            else:
                dvec = rng.normal(size=(k, 3))
                dvec /= np.maximum(np.linalg.norm(dvec, axis=1, keepdims=True),
                                   1e-300)
                rad = r[i] * (rng.uniform(0, 1, k) ** (1 / 3)
                              if shape == "sphere" else np.ones(k))
                o = dvec * rad[:, None]
        src.append(np.full(k, i))
        offs.append(o)
    src = np.concatenate(src) if src else np.zeros(0, np.int64)
    offs = np.concatenate(offs) if offs else np.zeros((0, 3))
    out = Geometry()
    base = np.arange(n) if keep_original else np.zeros(0, np.int64)
    rows = np.concatenate([base, src]).astype(np.int64)
    nb = len(base)
    out._resize_points(len(rows))
    from .ops import match_names
    keep = set(match_names([k for k in geo.attribs[POINT] if k != "P"], copy_attributes))
    for k, v in geo.attribs[POINT].items():
        if k == "P" or k in keep:
            out.set(POINT, k, np.asarray(v)[rows], owned=True)
        elif nb:
            # Attributes not copied: kept original points are still the input geometry and keep their values; copied points get 0 / empty string
            a = np.asarray(v)[rows].copy()
            a[nb:] = "" if is_string(a) else 0
            out.set(POINT, k, a, owned=True)
    for k, m in geo.groups[POINT].items():
        out.set_group(POINT, k, np.asarray(m)[rows])
    if local:
        offs = _place_local(geo, src, offs, center, size, uniform_scale,
                            velocity_stretch, velocity_scale)
    Pn = P[rows].copy()
    Pn[nb:] += offs
    dt = geo.get(POINT, "P").dtype if n else np.float32
    out.set(POINT, "P", Pn.astype(dt), owned=True)
    if float(inherit_velocity) != 1.0 or float(radial_velocity) != 0.0:
        v = out.get(POINT, "v")
        v = (np.asarray(v, np.float64).copy() if v is not None and v.shape[1] == 3
             else np.zeros((len(rows), 3)))
        v[nb:] = v[nb:] * float(inherit_velocity) + float(radial_velocity) * offs
        out.set(POINT, "v", v.astype(np.float32), owned=True)
    sa = str(source_attribute).strip()
    if sa:
        out.set(POINT, sa, rows.astype(np.int32)[:, None], owned=True)
    si = str(source_index_attribute).strip()
    if si:
        idx = np.full(len(rows), -1, np.int32)
        if len(src):                                       # numbered from 0 within each cluster
            st = np.r_[0, np.nonzero(np.diff(src))[0] + 1]
            ln = np.diff(np.r_[st, len(src)])
            idx[nb:] = np.arange(len(src)) - np.repeat(st, ln)
        out.set(POINT, si, idx[:, None], owned=True)
    og = str(output_group).strip()
    if og:
        out.set_group(POINT, og, np.arange(len(rows)) >= nb)
    out.attribs["detail"] = dict(geo.attribs["detail"])
    return out, {"points": int(len(src)), "sources": int(len(sel))}


def _place_local(geo, src, q, center, size, uniform_scale, stretch, vscale):
    """
    Local point cloud -> world offset (relative to source P). Order: x Size -> + Center -> x Uniform Scale ->
    Velocity Stretch (local Z x |v|.Velocity Scale) -> the source point's instance transform (same as Copy to Points).
    ignore_geometry_scale: drop pscale / scale from the instance transform (docs: ignore the input points' scale),
    stretch only by |v|.Velocity Scale. Center is added after Size: the docs say Center is the "local center",
    and it is easier to tune when it does not interfere with Size.
    """
    from .xform import point_matrices
    q = q * np.asarray(size, np.float64) + np.asarray(center, np.float64)
    q = q * float(uniform_scale)
    pts = geo
    if stretch != "none":
        v = geo.get(POINT, "v")
        if v is None or v.shape[1] < 3:
            raise KeyError("Velocity Stretch requires a v attribute on the input points")
        sp = np.linalg.norm(np.asarray(v, np.float64)[:, :3], axis=1)[src]
        q[:, 2] = q[:, 2] * sp * float(vscale)
        if stretch == "ignore_geometry_scale":
            pts = geo.copy()
            pts.remove(POINT, "pscale")
            pts.remove(POINT, "scale")
    M, T, pivot = point_matrices(pts)
    # offset = position after the instance transform - source P (trans / pivot included)
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    world = np.einsum("nij,nj->ni", M[src], q - pivot[src]) + T[src]
    return world - P[src]


# ═══════════════════════════════════════════════════════════ Point Velocity
def _pair(geo, other, how, key):
    if other is None:
        return None
    n, m = geo.npoints, other.npoints
    if how == "index":
        i = np.arange(n)
        return np.where(i < m, i, -1)
    ka, kb = geo.get(POINT, key), other.get(POINT, key)
    if ka is None or kb is None:
        raise KeyError(f"Point attribute '{key}' is required on the current frame and on the previous / next frame")
    first = {}
    for j, k in enumerate(np.asarray(kb)[:, 0].tolist()):
        first.setdefault(k, j)
    return np.array([first.get(k, -1) for k in np.asarray(ka)[:, 0].tolist()],
                    np.int64)


def point_velocity(geo, prev=None, next=None, method="auto", fps=24.0,
                   match="index", id_attribute="id", compute_accel=False,
                   v_attribute="v"):
    if method not in VELOCITY_METHODS:
        raise ValueError(f"Method must be one of {VELOCITY_METHODS}")
    if match not in VELOCITY_MATCH:
        raise ValueError(f"Match must be one of {VELOCITY_MATCH}")
    if not float(fps) > 0:
        raise ValueError("FPS must be > 0")
    dt = 1.0 / float(fps)
    have_p = prev is not None and prev.npoints > 0
    have_n = next is not None and next.npoints > 0
    if method == "auto":
        method = ("central" if have_p and have_n else
                  "backward" if have_p else "forward" if have_n else None)
        if method is None:
            raise ValueError("Connect at least one of the previous frame and the next frame")
    need = {"central": (True, True), "backward": (True, False),
            "forward": (False, True)}[method]
    if (need[0] and not have_p) or (need[1] and not have_n):
        raise ValueError(f"{method} requires connecting " + " and ".join(
            nm for nm, k in (("prev", need[0]), ("next", need[1])) if k))
    P = _P(geo)
    ip = _pair(geo, prev, match, id_attribute) if have_p else None
    inx = _pair(geo, next, match, id_attribute) if have_n else None
    ok = np.ones(len(P), bool)
    Pp = Pn = None
    if ip is not None:
        Pp = _P(prev)[np.maximum(ip, 0)]
        if need[0]:
            ok &= ip >= 0
    if inx is not None:
        Pn = _P(next)[np.maximum(inx, 0)]
        if need[1]:
            ok &= inx >= 0
    if method == "central":
        V = (Pn - Pp) / (2 * dt)
    elif method == "backward":
        V = (P - Pp) / dt
    else:
        V = (Pn - P) / dt
    V[~ok] = 0
    g = geo.copy()
    g.set(POINT, str(v_attribute).strip() or "v", V.astype(np.float32),
          owned=True)
    g.set_group(POINT, "no_velocity", ~ok)
    rep = {"method": method, "matched": int(ok.sum()),
           "unmatched": int((~ok).sum())}
    if compute_accel:
        if ip is None or inx is None:
            raise ValueError("Acceleration requires both the previous and next frames to be connected")
        oka = (ip >= 0) & (inx >= 0)
        Acc = (Pn - 2 * P + Pp) / (dt * dt)
        Acc[~oka] = 0
        g.set(POINT, "accel", Acc.astype(np.float32), owned=True)
    return g, rep
