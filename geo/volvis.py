"""
How volumes are drawn in the viewport (pcg106), and the Volume Visualization SOP.

Before pcg106 every volume was shown as its 0 iso-surface. That is right for an SDF and wrong for everything else:
a fog volume whose density is positive everywhere (blurred, noise-filled, a constant box) has no 0 crossing and
showed nothing at all; a splatted point cloud showed as a bloated shell at its outermost tail; and an SDF cut by
the grid boundary showed open holes. Houdini draws fog as smoke. Now:

  mode       what is drawn
  smoke      ray-marched in the browser (web/pcg_volume.js): the density field is optical thickness per unit length
             (density 1 over 1 unit lets e^-1 ≈ 37 % of the light through, independent of resolution), lit by the
             headlight with self-shadowing, coloured by Exposed Color, a diffuse field, or a ramp
  rainbow    smoke coloured by a rainbow ramp of the (remapped) density
  iso        the iso-surface at Iso Value, closed at the grid boundary (volume.volume_to_polygons(close=True))
  invisible  only the bounding box

Default per volume (no Volume Visualization upstream): SDF (fog class 0) -> iso at 0; fog / none -> smoke;
vector grids -> invisible (draw them with Volume Trail / VDB Visualize Tree / Volume Slice).

Volume Visualization writes detail attributes (Houdini writes volvis_* detail attributes too):
  volvis_mode, volvis_densityfield, volvis_diffusefield, volvis_emitfield (name patterns),
  volvis_densityscale, volvis_shadowscale, volvis_min, volvis_max, volvis_iso,
  volvis_color (Exposed Color), volvis_shadowcolor, volvis_diffuseramp_mode (none / clamp / periodic), volvis_diffuseramp,
  volvis_emitscale, volvis_emitcolor, volvis_maxres.
Volumes the density field pattern does not match, and the diffuse / emission fields themselves, are not drawn.

The viewport gets at most `max_res` samples per axis (default 128): larger grids are resampled for display only.
"""
from __future__ import annotations

import numpy as np

from .core import DETAIL, PRIM, PRIM_VOLUME
from . import vdb as _v

MODES = ("smoke", "rainbow", "iso", "invisible")
RAMP_MODES = ("none", "clamp", "periodic")
MAX_RES = 128
HALF_MAX = 6.0e4


def _detail(geo, name, default):
    a = geo.get(DETAIL, name)
    if a is None or not len(a):
        return default
    v = a[0]
    if np.ndim(v) and len(v) == 1:
        v = v[0]
    return v


def settings(geo):
    """The visualization settings in effect (None when there is no Volume Visualization upstream)."""
    mode = _detail(geo, "volvis_mode", None)
    if mode is None:
        return None
    col = geo.get(DETAIL, "volvis_color")
    scol = geo.get(DETAIL, "volvis_shadowcolor")
    ecol = geo.get(DETAIL, "volvis_emitcolor")
    return {
        "mode": str(mode),
        "density": str(_detail(geo, "volvis_densityfield", "") or ""),
        "diffuse": str(_detail(geo, "volvis_diffusefield", "") or ""),
        "emit": str(_detail(geo, "volvis_emitfield", "") or ""),
        "scale": float(_detail(geo, "volvis_densityscale", 1.0)),
        "shadow": float(_detail(geo, "volvis_shadowscale", 1.0)),
        "min": float(_detail(geo, "volvis_min", 0.0)),
        "max": float(_detail(geo, "volvis_max", 1.0)),
        "iso": float(_detail(geo, "volvis_iso", 0.0)),
        "color": [float(c) for c in (col[0] if col is not None else (1, 1, 1))],
        "shadowcolor": [float(c) for c in (scol[0] if scol is not None else (0, 0, 0))],
        "ramp_mode": str(_detail(geo, "volvis_diffuseramp_mode", "none") or "none"),
        "ramp": str(_detail(geo, "volvis_diffuseramp", "") or ""),
        "emitscale": float(_detail(geo, "volvis_emitscale", 0.0)),
        "emitcolor": [float(c) for c in (ecol[0] if ecol is not None else (1, 1, 1))],
        "maxres": int(_detail(geo, "volvis_maxres", MAX_RES)),
    }


def _match(geo, prims, pattern):
    if not str(pattern).strip():
        return list(prims)
    from .ops import match_names
    names = [_v.name_of(geo, i) for i in prims]
    hit = set(match_names(names, str(pattern)))
    return [i for i, n in zip(prims, names) if n in hit]


def _display_grid(vox, origin, cell, maxres):
    """Resample to at most maxres samples per axis over the same box (display only)."""
    rx, ry, rz = _v.res_of(vox)
    m = max(rx, ry, rz)
    if m <= maxres:
        return np.asarray(vox, np.float32), origin, cell
    f = m / float(maxres)
    nr = [max(2, int(round((r - 1) / f)) + 1) for r in (rx, ry, rz)]
    size = cell * (np.array([rx, ry, rz]) - 1)
    ncell = size / (np.array(nr) - 1)
    Q = _v.world_points(origin, ncell, (nr[2], nr[1], nr[0])).reshape(-1, 3)
    out = _v.sample(vox, origin, cell, Q)
    shp = (nr[2], nr[1], nr[0]) + ((3,) if _v.is_vector(vox) else ())
    return out.reshape(shp).astype(np.float32), origin, ncell


def _half(a):
    return np.clip(np.nan_to_num(np.asarray(a, np.float32), nan=0.0, posinf=HALF_MAX,
                                 neginf=-HALF_MAX), -HALF_MAX, HALF_MAX).astype(np.float16).view(np.uint16)


def ramp_lut(ramp, n=256):
    """Ramp string -> (n, 3) uint8. Empty -> greyscale."""
    t = np.linspace(0, 1, n)
    if not str(ramp).strip():
        c = np.stack([t, t, t], 1)
    else:
        from . import ramp as _rmp
        pos, val = _rmp.parse(str(ramp), 3)
        c = _rmp.apply(t, pos, val)
    return np.clip(np.round(c * 255), 0, 255).astype(np.uint8)


def _rainbow_lut(n=256):
    t = np.linspace(0, 1, n)
    keys = np.array([[0, 0, 0, 1], [0.25, 0, 1, 1], [0.5, 0, 1, 0], [0.75, 1, 1, 0], [1, 1, 0, 0]])
    c = np.stack([np.interp(t, keys[:, 0], keys[:, k]) for k in (1, 2, 3)], 1)
    return np.round(c * 255).astype(np.uint8)


def prepare(geo):
    """
    Split a geometry for display. Returns (mesh_geo, volumes):
      mesh_geo  the non-volume prims plus the iso-surfaces (closed) of iso-mode volumes
      volumes   list of dicts for the frontend; arrays are in "arrays" (name -> (array, dtype))
    """
    from . import volume as _vol
    from .ops import delete_prims
    vp = [i for i in range(geo.nprims) if geo.prim_type[i] == PRIM_VOLUME
          and geo.pdata(i, "voxels") is not None]
    if not vp:
        return geo, []
    st = settings(geo)
    plan = {}                                 # prim -> mode
    fields = {}                               # prim -> (diffuse prims, emit prims)
    if st is None:
        for i in vp:
            vox = geo.pdata(i, "voxels")
            if _v.is_vector(vox):
                plan[i] = "invisible"
            elif _v.grid_class(geo, i) == _v.CLASS_SDF:
                plan[i] = "iso"
            else:
                plan[i] = "smoke"
    else:
        mode = st["mode"] if st["mode"] in MODES else "smoke"
        dens = _match(geo, vp, st["density"])
        diff = _match(geo, vp, st["diffuse"]) if st["diffuse"].strip() else []
        emit = _match(geo, vp, st["emit"]) if st["emit"].strip() else []
        used = set(diff) | set(emit)
        for i in vp:
            if i in dens and i not in used and not _v.is_vector(geo.pdata(i, "voxels")):
                plan[i] = mode
                fields[i] = (diff, emit)
            else:
                plan[i] = "hidden"

    iso_prims = [i for i, m in plan.items() if m == "iso"]
    keep_mask = np.ones(geo.nprims, bool)
    keep_mask[vp] = False
    parts = []
    if keep_mask.any():
        parts.append(delete_prims(geo, keep_mask))
    from .ops import merge, compute_normals
    iso_val = st["iso"] if st is not None else 0.0
    if iso_prims:
        only = np.zeros(geo.nprims, bool)
        only[iso_prims] = True
        surf = _vol.volume_to_polygons(delete_prims(geo, only), iso_val, None, close=True)
        if surf.nprims:
            parts.append(compute_normals(surf, "point"))
    from .core import Geometry
    mesh = merge(*parts) if len(parts) > 1 else (parts[0] if parts else Geometry())

    vols = []
    maxres = max(8, int(st["maxres"])) if st is not None else MAX_RES
    for k, i in enumerate(vp):
        m = plan[i]
        if m == "hidden":
            continue
        vox, origin, cell = _v.grid(geo, i)
        rx, ry, rz = _v.res_of(vox)
        lo = origin
        hi = origin + cell * (np.array([rx, ry, rz]) - 1)
        item = {"prim": int(i), "name": _v.name_of(geo, i), "mode": m,
                "box": [lo.tolist(), hi.tolist()], "res_full": [rx, ry, rz]}
        if m in ("smoke", "rainbow"):
            d, o, c = _display_grid(vox, origin, cell, maxres)
            lo_r, hi_r = (st["min"], st["max"]) if st is not None else (0.0, 1.0)
            span = (hi_r - lo_r) if abs(hi_r - lo_r) > 1e-12 else 1.0
            dn = np.maximum((d - lo_r) / span, 0.0)
            # an SDF / "none" grid shown as smoke: show where it is inside / positive only
            item.update({
                "res": [int(d.shape[2]), int(d.shape[1]), int(d.shape[0])],
                "density_buf": f"vol{k}_d",
                "scale": float(st["scale"]) if st is not None else 1.0,
                "shadow": float(st["shadow"]) if st is not None else 1.0,
                "color": st["color"] if st is not None else [1.0, 1.0, 1.0],
                "shadowcolor": st["shadowcolor"] if st is not None else [0.0, 0.0, 0.0],
                "dmax": float(dn.max()) if dn.size else 0.0,
            })
            item["arrays"] = {f"vol{k}_d": (_half(dn), np.uint16)}
            # colour: rainbow, diffuse field (scalar via ramp, vector = rgb), emission field
            rgba = None
            if m == "rainbow":
                lut = _rainbow_lut()
                idx = np.clip(np.round(np.clip(dn, 0, 1) * 255), 0, 255).astype(np.int64)
                rgba = np.zeros(dn.shape + (4,), np.uint8)
                rgba[..., :3] = lut[idx]
            diff, emit = fields.get(i, ([], []))
            Q = None
            if diff:
                Q = _v.world_points(o, c, dn.shape).reshape(-1, 3)
                if len(diff) == 1:
                    dv, do, dc = _v.grid(geo, diff[0])
                    cv = _v.sample(dv, do, dc, Q)
                else:
                    cv = np.stack([_v.sample(*_v.grid(geo, j), Q) for j in diff[:3]], -1)
                    if cv.shape[1] < 3:
                        cv = np.concatenate([cv, np.repeat(cv[:, -1:], 3 - cv.shape[1], 1)], 1)
                if cv.ndim == 1:
                    t = (cv - st["min"]) / span
                    rm = st["ramp_mode"]
                    if rm == "periodic":
                        t = np.mod(t, 1.0)
                    if rm in ("clamp", "periodic"):
                        lut = ramp_lut(st["ramp"])
                        col = lut[np.clip(np.round(np.clip(t, 0, 1) * 255), 0, 255).astype(np.int64)]
                    else:
                        g = np.clip(np.round(np.clip(cv, 0, 1) * 255), 0, 255).astype(np.uint8)
                        col = np.stack([g, g, g], 1)
                else:
                    col = np.clip(np.round(np.clip(cv, 0, 1) * 255), 0, 255).astype(np.uint8)
                rgba = np.zeros(dn.shape + (4,), np.uint8)
                rgba[..., :3] = col.reshape(dn.shape + (3,))
            if emit and st is not None and st["emitscale"] > 0:
                if Q is None:
                    Q = _v.world_points(o, c, dn.shape).reshape(-1, 3)
                ev = np.maximum(_v.sample(*_v.grid(geo, emit[0]), Q), 0.0)
                emax = float(ev.max()) if ev.size else 0.0
                if rgba is None:
                    rgba = np.zeros(dn.shape + (4,), np.uint8)
                    rgba[..., :3] = 255
                if emax > 0:
                    rgba[..., 3] = np.round(ev.reshape(dn.shape) / emax * 255).astype(np.uint8)
                item["emit_max"] = emax
                item["emit_scale"] = float(st["emitscale"])
                item["emit_color"] = st["emitcolor"]
            if rgba is not None:
                item["color_buf"] = f"vol{k}_c"
                item["arrays"][f"vol{k}_c"] = (np.ascontiguousarray(rgba), np.uint8)
                if m == "rainbow":
                    item["color"] = [1.0, 1.0, 1.0]
        vols.append(item)
    return mesh, vols


def visualize(geo, mode="smoke", density_field="", diffuse_field="", emit_field="",
              range_min=0.0, range_max=1.0, density_scale=1.0, shadow_scale=1.0,
              color=(1.0, 1.0, 1.0), shadow_color=(0.0, 0.0, 0.0),
              ramp_mode="none", ramp="", emit_scale=0.0, emit_color=(1.0, 1.0, 1.0),
              iso=0.0, max_res=MAX_RES):
    """Volume Visualization: writes the volvis_* detail attributes. Geometry is unchanged."""
    if mode not in MODES:
        raise ValueError(f"Visualization Mode must be one of {MODES}")
    if ramp_mode not in RAMP_MODES:
        raise ValueError(f"Diffuse ramp mode must be one of {RAMP_MODES}")
    g = geo.copy()

    def put_s(name, v):
        g.set_string(DETAIL, name, np.array([str(v)]))

    def put_f(name, v):
        g.set(DETAIL, name, np.array([[float(v)]], np.float32), owned=True)

    def put_v(name, v):
        g.set(DETAIL, name, np.array([list(map(float, v))], np.float32), owned=True)

    put_s("volvis_mode", mode)
    put_s("volvis_densityfield", density_field)
    put_s("volvis_diffusefield", diffuse_field)
    put_s("volvis_emitfield", emit_field)
    put_s("volvis_diffuseramp_mode", ramp_mode)
    put_s("volvis_diffuseramp", ramp)
    put_f("volvis_min", range_min)
    put_f("volvis_max", range_max)
    put_f("volvis_densityscale", density_scale)
    put_f("volvis_shadowscale", shadow_scale)
    put_f("volvis_iso", iso)
    put_f("volvis_emitscale", emit_scale)
    put_f("volvis_maxres", max(8, int(max_res)))
    put_v("volvis_color", color)
    put_v("volvis_shadowcolor", shadow_color)
    put_v("volvis_emitcolor", emit_color)
    return g
