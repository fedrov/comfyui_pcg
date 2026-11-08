"""
Point Jitter SOP -- add random perturbation to points.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Random numbers are taken by **id, not point number**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Point numbers change: delete a point upstream, Sort, or Fuse two points, and every following point's number shifts,
so the whole jitter result changes. With an id attribute, random numbers are taken by id, unaffected by any upstream additions, deletions or sorting --
this is exactly Houdini's reason for this parameter, and the precondition for "change one place, leave the rest alone" in procedural pipelines.

Uses Wrangle's splitmix64 bit mixing (`wrangle._hash01`): stateless, vectorizable,
the same input always gives the same output. Not `np.random`: its semantics are "generate N random numbers",
so when the point set changes everything shifts.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The distribution is **uniform in a ball**, not uniform in a cube
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Taking a uniform number in [-1,1] for each of three axes gives a cube -- diagonal displacements are 1.73x longer
than axial ones, and a jittered patch of points shows directionality, especially with grid-like input. Here a Gaussian direction +
radius cbrt(u) is used, strictly uniform in the ball. Axis Scales then stretch anisotropically; supply them yourself when you want directionality.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT
from .groups import resolve
from .wrangle import _hash01

MASK_MODES = ("no_scaling", "scale_by_attribute")


def _rand01(keys, salt):
    return np.asarray(_hash01(keys, salt), np.float64).reshape(-1)


def jitter_vectors(keys, seed=1):
    """(N,) seeds -> (N,3) uniform samples inside the unit ball."""
    n = len(keys)
    if n == 0:
        return np.zeros((0, 3))
    s = int(seed) * 7919
    u1 = np.clip(_rand01(keys, s + 11), 1e-12, 1.0)
    u2 = _rand01(keys, s + 23)
    u3 = np.clip(_rand01(keys, s + 37), 1e-12, 1.0)
    u4 = _rand01(keys, s + 53)
    u5 = _rand01(keys, s + 71)
    # Box-Muller gives three independent Gaussians, so the direction is uniformly distributed on the sphere
    r1, r2 = np.sqrt(-2.0 * np.log(u1)), np.sqrt(-2.0 * np.log(u3))
    g = np.stack([r1 * np.cos(2 * np.pi * u2),
                  r1 * np.sin(2 * np.pi * u2),
                  r2 * np.cos(2 * np.pi * u4)], 1)
    ln = np.linalg.norm(g, axis=1, keepdims=True)
    g = g / np.where(ln < 1e-12, 1.0, ln)
    return g * np.cbrt(np.maximum(u5, 0.0))[:, None]


def point_jitter(geo, group="", mask=1.0, mask_mode="no_scaling",
                 mask_attrib="", id_attrib="", scale=1.0,
                 axis_scales=(1.0, 1.0, 1.0), seed=1,
                 use_point_scale=False, update_normals=True):
    """
    Each point moves a distance along a random direction, at most scale (further multiplied by mask / pscale / per-axis factors).

    When id_attrib names a point attribute that actually exists on the geometry, the random stream is taken by it; otherwise by point number.
    """
    if geo is None or geo.npoints == 0:
        return Geometry() if geo is None else geo.copy()
    P = geo.get(POINT, "P")
    if P is None:
        return geo.copy()
    sel = resolve(geo, POINT, group)
    if not sel.any():
        return geo.copy()

    n = geo.npoints
    keys = np.arange(n, dtype=np.float64)
    nm = str(id_attrib).strip()
    if nm:
        a = geo.get(POINT, nm)
        if a is None:
            have = sorted(geo.attribs[POINT].keys())
            raise KeyError(f"No id attribute '{nm}' on point. Existing: {have or '(none)'}")
        keys = a[:, 0].astype(np.float64)

    amt = np.full(n, float(mask))
    if mask_mode == "scale_by_attribute":
        an = str(mask_attrib).strip()
        if not an:
            raise ValueError("Mask is set to Scale by Attribute, but no attribute name was given.")
        a = geo.get(POINT, an)
        if a is None:
            have = sorted(geo.attribs[POINT].keys())
            raise KeyError(f"No mask attribute '{an}' on point. Existing: {have or '(none)'}")
        amt = amt * a[:, 0].astype(np.float64)
    elif mask_mode not in MASK_MODES:
        raise ValueError(f"mask_mode must be one of {MASK_MODES}")

    amt = amt * float(scale)
    if use_point_scale:
        ps = geo.get(POINT, "pscale")
        if ps is not None:
            amt = amt * ps[:, 0].astype(np.float64)

    d = jitter_vectors(keys, seed) * np.asarray(axis_scales, np.float64
                                                ).reshape(1, 3)
    d = d * amt[:, None]
    d[~sel] = 0.0

    g = geo.copy()
    g.set(POINT, "P", (P.astype(np.float64) + d).astype(P.dtype), owned=True)
    if update_normals and geo.nprims and (
            g.has(POINT, "N") or g.has("vertex", "N") or g.has("prim", "N")):
        from .ops import compute_normals
        cls = POINT if g.has(POINT, "N") else ("prim" if g.has("prim", "N")
                                               else "vertex")
        g = compute_normals(g, add_to=cls)
    return g
