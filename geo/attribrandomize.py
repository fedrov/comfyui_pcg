"""
Attribute Randomize -- gives attributes random values.

After scattering, pscale needs size variation and orient needs orientation variation, or a field of copies looks like a parade.
That is what this node is for; it lines up directly with the instance attributes Copy to Points reads.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The random stream is taken by **id attribute**, same as Point Jitter
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Point numbers change: delete a point upstream, Sort, or Fuse two points, and every later point's number shifts,
so every tree's size and orientation get reshuffled. With an id attached values are drawn by id, unaffected by additions, deletions or sorting.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Three modes, producing completely different things
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    value      each component drawn independently from a range (pscale / Cd / any scalar)
    direction  unit directions, optionally restricted to the sphere / a cone / a perpendicular plane / an axis
    orient     quaternions. A random angle about a given axis, or a fully random orientation

**direction is not "randomize three components and normalize"**: that makes directions denser towards the cube's corners,
and a field of orientations shows a diagonal bias. Uniform on the sphere needs uniform z + uniform azimuth (Archimedes' projection);
uniform in a cone likewise -- uniform in cos, not in angle.

orient's "fully random orientation" uses Shoemake's method of building a quaternion directly from three uniform numbers, strictly uniform
on SO(3); "three random Euler angles" is not uniform and clusters near the poles.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, CLASSES
from .groups import resolve
from .attribnoise import _mix, _to01

MODES = ("value", "direction", "orient")
# pcg100 s6: the later entries are the Distribution / Operation of Houdini's Attribute Randomize; only append at the end
DISTRIBUTIONS = ("uniform", "gaussian", "power",
                 "constant", "two_values", "uniform_discrete", "exponential",
                 "lognormal", "cauchy", "custom_discrete", "inside_sphere")
SHAPES = ("sphere", "cone", "disc", "line")
COMBINE = ("set", "add", "multiply", "minimum", "maximum")


def _rand01(keys, seed, salt):
    """(N,) seeds -> (N,) [0,1). Stateless, vectorizable, same input same output."""
    k = np.asarray(keys, np.float64)
    with np.errstate(over="ignore"):
        x = ((k * 1000003.0).astype(np.int64).astype(np.uint64)
             + np.uint64((int(seed) * 0x9E3779B1 + int(salt) * 0x85EBCA77)
                         & 0xFFFFFFFFFFFFFFFF))
    return _to01(_mix(x))


def _gauss(keys, seed, salt):
    """Box-Muller. Two uniform numbers become one standard normal."""
    u1 = np.clip(_rand01(keys, seed, salt), 1e-12, 1.0)
    u2 = _rand01(keys, seed, salt + 977)
    return np.sqrt(-2.0 * np.log(u1)) * np.cos(2.0 * np.pi * u2)


def _basis(d):
    """Builds an orthonormal basis for a direction, returns (u, v, w), w is the normalized d."""
    w = np.asarray(d, np.float64).reshape(3)
    ln = np.linalg.norm(w)
    w = np.array([0.0, 1.0, 0.0]) if ln < 1e-12 else w / ln
    a = np.array([1.0, 0, 0]) if abs(w[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(a, w)
    u /= max(np.linalg.norm(u), 1e-12)
    return u, np.cross(w, u), w


def directions(keys, seed, shape="sphere", axis=(0, 1, 0), angle=45.0):
    """(N,3) unit directions."""
    n = len(keys)
    u1 = _rand01(keys, seed, 11)
    u2 = _rand01(keys, seed, 23)
    ex, ey, ez = _basis(axis)
    phi = 2.0 * np.pi * u2
    if shape == "sphere":
        # z uniform on [-1,1] -- every latitude band of equal width on the sphere has the same area (Archimedes)
        cz = 2.0 * u1 - 1.0
    elif shape == "cone":
        # Uniform in a cone likewise: uniform in cos, not in angle
        cmin = np.cos(np.radians(float(angle)))
        cz = cmin + (1.0 - cmin) * u1
    elif shape == "disc":
        cz = np.zeros(n)
    elif shape == "line":
        s = np.where(u1 < 0.5, -1.0, 1.0)
        return ez[None, :] * s[:, None]
    else:
        raise ValueError(f"Shape must be one of {SHAPES}")
    r = np.sqrt(np.maximum(1.0 - cz * cz, 0.0))
    return (ex[None, :] * (r * np.cos(phi))[:, None]
            + ey[None, :] * (r * np.sin(phi))[:, None]
            + ez[None, :] * cz[:, None])


def quaternions(keys, seed, shape="sphere", axis=(0, 1, 0),
                angle_min=0.0, angle_max=360.0):
    """(N,4) quaternions (x,y,z,w)."""
    if shape == "sphere":
        # Shoemake: built directly from three uniform numbers, strictly uniform on SO(3).
        # Three random Euler angles are not uniform and cluster near the poles.
        u1 = _rand01(keys, seed, 31)
        u2 = 2.0 * np.pi * _rand01(keys, seed, 37)
        u3 = 2.0 * np.pi * _rand01(keys, seed, 41)
        s1, s2 = np.sqrt(1.0 - u1), np.sqrt(u1)
        return np.stack([s1 * np.sin(u2), s1 * np.cos(u2),
                         s2 * np.sin(u3), s2 * np.cos(u3)], 1)
    _, _, w = _basis(axis)
    a = np.radians(float(angle_min) + (float(angle_max) - float(angle_min))
                   * _rand01(keys, seed, 53))
    h = 0.5 * a
    return np.concatenate([w[None, :] * np.sin(h)[:, None],
                           np.cos(h)[:, None]], 1)


def randomize(geo, name="pscale", cls=POINT, mode="value",
              distribution="uniform", dimensions=1,
              min_value=(0.0, 0.0, 0.0, 0.0),
              max_value=(1.0, 1.0, 1.0, 1.0),
              mean=0.5, stddev=0.25, exponent=2.0,
              shape="sphere", axis=(0.0, 1.0, 0.0), cone_angle=45.0,
              angle_min=0.0, angle_max=360.0,
              length_min=1.0, length_max=1.0,
              combine="set", rand_seed=0, id_attrib="", group="",
              prob_b=0.5, step_size=1.0, global_scale=1.0, value_list="0\n1"):
    """
    Gives attributes random values. mode decides what is produced; see the module notes.

    With combine=multiply a missing attribute counts as 1 (not 0), otherwise multiplying gives all zeros -- this is
    the easiest trap when stacking randomness onto pscale. minimum / maximum take the generated value directly when the attribute is missing
    (comparing with 0 makes no sense; the Houdini docs say Set Value should be used when the attribute doesn't exist).

    Distributions added in pcg100 (Houdini parameter name -> the parameter we reuse):
        constant          Value              -> Min (per component)
        two_values        Value A / B, Probability of Value B -> Min / Max / prob_b
        uniform_discrete  Min / Max / Step Size (both ends inclusive, grid starts at Min)
        exponential       Middle Value (median) -> mean; mean = median / ln2
        lognormal         Middle Value / Spread Around Middle -> mean / stddev:
                          median * exp(stddev*z), values strictly positive
        cauchy            Middle Value / Scale Around Middle (gamma) -> mean / stddev
        custom_discrete   value table (one tuple per line + w=weight, same syntax as Attribute Adjust's value table)
        inside_sphere     uniform inside the unit ball (of Dimensions dimensions): uniform direction * radius u^(1/dims)
    Global Scale multiplies the generated value before Operation (orient quaternions aren't multiplied -- a scaled quaternion
    is not a rotation).
    """
    if geo is None:
        return Geometry()
    if cls not in CLASSES:
        raise ValueError(f"Class must be one of {CLASSES}")
    if mode not in MODES:
        raise ValueError(f"Mode must be one of {MODES}")
    if distribution not in DISTRIBUTIONS:
        raise ValueError(f"Distribution must be one of {DISTRIBUTIONS}")
    if combine not in COMBINE:
        raise ValueError(f"Combine must be one of {COMBINE}")
    nm = str(name or "").strip()
    if not nm:
        raise ValueError("Name is empty.")
    n = geo.count(cls)
    if n == 0:
        return geo.copy()

    keys = np.arange(n, dtype=np.float64)
    idn = str(id_attrib).strip()
    if idn:
        a = geo.get(cls, idn)
        if a is None:
            have = sorted(geo.attribs[cls].keys())
            raise KeyError(f"{cls} has no id attribute '{idn}'. Existing: {have or '(none)'}")
        keys = a[:, 0].astype(np.float64)

    seed = int(rand_seed)
    if mode == "value":
        C = int(np.clip(dimensions, 1, 4))
        lo = np.asarray(min_value, np.float64).reshape(-1)[:4]
        hi = np.asarray(max_value, np.float64).reshape(-1)[:4]
        lo = np.concatenate([lo, np.zeros(4 - len(lo))])[:C]
        hi = np.concatenate([hi, np.ones(4 - len(hi))])[:C]
        cols = []
        table = None
        if distribution == "custom_discrete":
            from .attribadjust2 import parse_value_list, pick_specific
            table = parse_value_list(value_list)
        if distribution == "inside_sphere":
            # Independent normals per component, normalized = uniform directions on the C-dim sphere; radius u^(1/C) makes it uniform in volume
            z = np.stack([_gauss(keys, seed, 101 + c * 17) for c in range(C)], 1)
            d = z / np.maximum(np.linalg.norm(z, axis=1, keepdims=True), 1e-300)
            r = _rand01(keys, seed, 89) ** (1.0 / C)
            cols = list((d * r[:, None]).T)
        for c in range(C if distribution != "inside_sphere" else 0):
            u = _rand01(keys, seed, 101 + c * 17)
            if distribution == "constant":
                cols.append(np.full(n, lo[c]))
                continue
            if distribution == "two_values":
                cols.append(np.where(u < float(prob_b), hi[c], lo[c]))
                continue
            if distribution == "uniform_discrete":
                st = abs(float(step_size))
                if st <= 0:
                    raise ValueError("Step Size of Uniform (Discrete) cannot be 0.")
                m = max(int(np.floor((hi[c] - lo[c]) / st + 1e-9)), 0)
                cols.append(lo[c] + st * np.minimum(np.floor(u * (m + 1)), m))
                continue
            if distribution == "exponential":
                cols.append(-np.log1p(-u) * float(mean) / np.log(2.0))
                continue
            if distribution == "lognormal":
                if float(mean) <= 0:
                    raise ValueError("Middle Value (median) of Log-Normal must be greater than 0.")
                cols.append(float(mean) * np.exp(float(stddev)
                                                 * _gauss(keys, seed, 101 + c * 17)))
                continue
            if distribution == "cauchy":
                cols.append(float(mean) + float(stddev) * np.tan(np.pi * (u - 0.5)))
                continue
            if distribution == "custom_discrete":
                cols.append(pick_specific(u, table))
                continue
            if distribution == "uniform":
                t = _rand01(keys, seed, 101 + c * 17)
            elif distribution == "power":
                # u^exponent: exponent > 1 pushes towards the lower bound, for "mostly small, the occasional big tree"
                t = _rand01(keys, seed, 101 + c * 17) ** max(float(exponent),
                                                             1e-6)
            elif distribution == "gaussian":
                cols.append(float(mean) + float(stddev)
                            * _gauss(keys, seed, 101 + c * 17))
                continue
            cols.append(lo[c] + (hi[c] - lo[c]) * t)
        val = np.stack(cols, 1)
    elif mode == "direction":
        d = directions(keys, seed, shape, axis, cone_angle)
        L = (float(length_min) + (float(length_max) - float(length_min))
             * _rand01(keys, seed, 71))
        val = d * L[:, None]
    else:
        val = quaternions(keys, seed, shape, axis, angle_min, angle_max)

    if mode != "orient":
        val = val * float(global_scale)
    C = val.shape[1]
    sel = resolve(geo, cls, group)
    cur = geo.get(cls, nm)
    if cur is not None and cur.shape[1] == C:
        base = cur.astype(np.float64)
        dt = cur.dtype
    else:
        base = np.full((n, C), 1.0 if combine == "multiply" else 0.0)
        dt = np.dtype(np.float32)
    if combine in ("minimum", "maximum") and not (cur is not None and cur.shape[1] == C):
        out = val
    elif combine in ("minimum", "maximum"):
        out = (np.minimum if combine == "minimum" else np.maximum)(base, val)
    else:
        out = (val if combine == "set" else
               base + val if combine == "add" else base * val)
    out = np.where(sel[:, None], out, base)
    g = geo.copy()
    g.set(cls, nm, (np.rint(out) if dt.kind in "iub" else out).astype(dt),
          owned=True)
    return g
