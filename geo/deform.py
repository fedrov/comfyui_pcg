"""
Deform -- Twist / Bend / Taper / Squash / Shear, plus Soft Transform and Spherify.

In Houdini this whole family is the Twist SOP (several ops in one node). What they have in common:
**pure per-point functions of position**; they touch neither topology nor attributes, so they can be stacked freely.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Outside the capture range is a **rigid extension**; clamping t is not the end of it
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Each point is first converted into a normalized parameter along the main axis `t = (s - s0) / L`, and the deformation is given by t. Outside the range
(t<0 or t>1) is the easiest to get wrong: a plain `clip(t, 0, 1)` is correct for twist / taper / shear
(those deformations are a rotation or scale about the axis on each slice, and the point's axial coordinate doesn't take part), but for **bend
it is wrong** -- the axial coordinate gets clamped too, so the whole stretch outside the range collapses onto the end face, looking
as if a layer had been squashed flat.

The right way is to carry the part outside the range **rigidly along the tangent at the end**:

    excess length extra = (s - s0) - clamp(s - s0, 0, L)
    then translate by extra along the tangent direction at phi=theta

Squash likewise (axial scaling applies only within the range; outside is translated as a whole). This is the easiest place in this module
to get silently wrong, so the tests have a dedicated case: "after bending, the stretch outside the range is still straight and its length
is unchanged".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bend's formula must be written in a form that **doesn't cancel**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bending a stretch of length L into an arc of angle theta gives radius R = L/theta. The textbook formula is

    new lateral coordinate = R - (R - x)*cos phi

For very small theta R is astronomical (at theta=1e-4 deg, R~2.3e6*L), and `R - R*cos phi` subtracts two
huge numbers to get a tiny one -- **catastrophic cancellation**. Measured (L=4, evaluated at phi=theta):

```
    theta      correct         textbook         relative error
    0.01°      3.490658e-04   3.490658e-04    1.0e-09
    0.0001°    3.490659e-06   3.490597e-06    1.8e-05
    1e-06°     3.490659e-08   2.980232e-08    **1.5e-01**
```

The symptom is "the model starts jittering when the angle is tuned very small", and the first instinct is to blame interpolation precision.

Here it is rewritten in an identical but stable form:

    R·sin φ      = L · t · sinc(θt/π)
    R(1 − cos φ) = L · t² · (θ/2) · sinc(θt/2π)²

(`np.sinc(z) = sin(pi*z)/(pi*z)`). The benefit is not just stability: **at theta=0 these two formulas give exactly
t*L and 0**, so "angle 0 = bitwise identity" holds automatically, with no need for an `if abs(theta)<eps`
special case -- and such a special case is itself a discontinuous step.

Measured: bending a 41-point straight line into an arc, with theta tried all the way from 180 deg down to 1e-6 deg, every point's distance to the centre
deviates from the radius by less than 1e-7 (float32 storage precision).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Normals are fixed with a **finite-difference Jacobian**, not recomputed
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
After deformation N is wrong. The usual approach is "connect another Normal SOP to recompute", but that has two problems:
curves and point clouds have no faces to recompute from at all; and recomputing wipes out existing hard edges / custom normals.

Here one trick covers **any** op: treat the deformation function as a black box, do three first-order forward differences at each point
to get the 3x3 Jacobian J, and transform normals by `J^-T n` (the standard treatment of direction attributes; `normal_matrices` in `xform.py`
uses the same rule). The cost is running the deformation three more times (pure per-point arithmetic, cheap),
and in exchange:

    - curves, point clouds and point-only geometry can be fixed just the same
    - under anisotropic deformations (taper / squash) the normals are **correct** -- `J n` and `J^-T n`
      differ clearly in this case, and `J n` is the kind of wrong that "looks right"
    - existing hard-edge relationships are preserved (each vertex normal is transformed on its own, not smoothed out by recomputation)

The step is `1e-4 x bounding box diagonal`: a relative step, so scaling the model up a thousand times doesn't change the result. Measured (comparing
Jacobian normals point by point with normals "recomputed after deformation"):

```
    twist  max 0.0022 deg    taper  0.0000 deg    bend  0.1489 deg
```

(Excluding the top and bottom rings of the tube -- there it is the **recomputed** normals that are wrong: boundary points only have faces on one side, so the computed
average normal is skewed. The Jacobian normals are actually right there, a side benefit of this approach.)

Negative control: the same taper with `J*n` (missing the inverse transpose) gives normals **9.9 deg** off the correct values --
under non-uniform scaling the two differ clearly, and `J*n` is exactly the kind of wrong that "looks right".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Soft Transform: **interpolate the parameters, not the result**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The laziest way to write a falloff transform is `P' = lerp(P, M*P, w)`. For rotation it is **wrong**:
linearly interpolating a rotated position and the original lands the point on the **chord** between them, closer to the centre of rotation --
the radius gets eaten, shrinking most at weight 0.5, which visually looks like "the soft selection collapsed into a ring".

The right way is to interpolate the **parameters**: each point computes its own matrix on the spot from `angle x w`, `translation x w`, `scale lerp(1, s, w)`.
The rotation radius is thus strictly preserved (measured max relative change 4.8e-08), while
the lerp version in the same example (90 deg rotation about an axis) **shrank the radius by 29.3%** in the ring around w~0.5.
Both are in the tests, the latter as a negative control.

Another easy one to miss: when differencing for the Jacobian, the **weights must not be recomputed**. Recomputing would give the joint derivative of "position +
weight field", which is not the linear map we want for transforming normals; and the weight field is not differentiable at group
boundaries, so normals would explode into noise along that ring.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL
from .groups import resolve
from . import adjacency as _adj

AXES = ("x", "y", "z")
OPS = ("twist", "bend", "taper", "squash", "shear")
NORMAL_MODES = ("jacobian", "none")
# pcg100: Houdini's Attribute / Radius with Connectivity appended at the end (old tokens unchanged:
# euclidean = Houdini's Radius, distance = Edge, steps is our hop count)
METRICS = ("euclidean",) + tuple(_adj.METRICS) + ("attribute", "radius_with_connectivity")
# Soft Type: ramp is ours (old behaviour, custom curve); the last four are Houdini's
SOFT_TYPES = ("ramp", "linear", "quadratic", "cubic", "metaball")
# Metaball kernels: the Metaball SOP docs give formulas only for these three (Blinn / Wyvill / Elendt not given, not done)
KERNELS = ("links", "renderman", "hart")
# Relative step of the finite differences. Too small is eaten by float32 rounding, too large distorts at strong curvature;
# 1e-4 x diagonal leaves enough margin in float64 (the deformation itself is computed in float64)
JAC_EPS = 1.0e-4
_AX = {"x": np.array([1.0, 0.0, 0.0]),
       "y": np.array([0.0, 1.0, 0.0]),
       "z": np.array([0.0, 0.0, 1.0])}


# ═══════════════════════════════════════════════════════════════════ tools
def _frame(axis, up):
    """
    (a, b, c): three orthogonal unit vectors. a is the main axis, b the **secondary direction** (where bend bends towards,
    where shear pushes), c = a x b.

    When up is parallel to a another one is picked automatically -- otherwise the cross product is a zero vector and the whole deformation silently becomes nan.
    """
    a = np.asarray(_AX[axis], np.float64)
    u = np.asarray(up, np.float64).reshape(3)
    n = float(np.linalg.norm(u))
    if n < 1e-12 or abs(float(a @ (u / n))) > 1 - 1e-9:
        u = _AX["y"] if axis != "y" else _AX["x"]
    else:
        u = u / n
    b = u - a * float(a @ u)
    b = b / float(np.linalg.norm(b))
    return a, b, np.cross(a, b)


def _capture(q, s0, s1):
    """
    Returns (t, s_in, extra). t in [0,1] is the normalized parameter, s_in is the part within the range,
    extra is the excess (negative before the range, positive after).

    Returned separately because **the outside of the range must be carried rigidly**, rather than clamping the axial coordinate too.
    """
    L = float(s1) - float(s0)
    d = q - float(s0)
    if abs(L) < 1e-12:
        return np.where(d >= 0, 1.0, 0.0), np.zeros_like(d), d
    s_in = np.clip(d, min(0.0, L), max(0.0, L))
    return s_in / L, s_in, d - s_in


def _op_twist(q, t, s_in, extra, p):
    ang = np.radians(float(p["angle"])) * t
    c, s = np.cos(ang), np.sin(ang)
    x, y = q[:, 1], q[:, 2]
    return np.stack([q[:, 0], x * c - y * s, x * s + y * c], -1)


def _op_taper(q, t, s_in, extra, p):
    k = 1.0 + (float(p["amount"]) - 1.0) * t
    return np.stack([q[:, 0], q[:, 1] * k, q[:, 2] * k], -1)


def _op_shear(q, t, s_in, extra, p):
    return np.stack([q[:, 0],
                     q[:, 1] + float(p["shear_b"]) * t,
                     q[:, 2] + float(p["shear_c"]) * t], -1)


def _op_squash(q, t, s_in, extra, p):
    """
    Within the range the axial direction is multiplied by amount (rigidly translated outside); the lateral directions are **always** multiplied by 1/sqrt(amount).

    The lateral term deliberately **does not ramp with t**. I wrote a ramped version first, and the volume was off by 26%
    (amount=0.5) and 47% (amount=2.0) -- because the axial factor is a uniform k while the lateral one ramps from 1 to
    1/sqrt(k), and only the last slice has k*(1/sqrt(k))^2 equal to 1. With a constant lateral factor every slice conserves volume,
    and since it doesn't depend on the axial coordinate, there is no jump at the range boundary either.

    The cost, stated plainly: points **outside** the range also get their cross-section scaled (axially unchanged). The default range is the whole
    span, so such points don't exist; only with a manually given range does it need attention.
    """
    k = float(p["amount"])
    if k <= 0:
        raise ValueError("Squash's Amount must be > 0.")
    perp = 1.0 / np.sqrt(k)
    return np.stack([s_in * k + extra + float(p["s0"]),
                     q[:, 1] * perp, q[:, 2] * perp], -1)


def _op_bend(q, t, s_in, extra, p):
    """
    Bends the range into an arc. Written in sinc form: at theta=0 it degenerates **exactly** to identity, and at small angles
    there is no catastrophic cancellation like `R - R*cos phi`.
    """
    th = np.radians(float(p["angle"]))
    L = float(p["s1"]) - float(p["s0"])
    x = q[:, 1]
    phi = th * t
    cp, sp = np.cos(phi), np.sin(phi)
    # R*sin phi and R(1-cos phi), both expanded with sinc, R = L/theta never appears explicitly
    r_sin = L * t * np.sinc(phi / np.pi)
    r_cos = L * t * t * (th * 0.5) * np.sinc(phi / (2.0 * np.pi)) ** 2
    a_new = r_sin - x * sp + extra * cp
    b_new = r_cos + x * cp + extra * sp
    return np.stack([a_new + float(p["s0"]), b_new, q[:, 2]], -1)


_OPS = {"twist": _op_twist, "bend": _op_bend, "taper": _op_taper,
        "squash": _op_squash, "shear": _op_shear}


def _deformer(op, axis, up, s0, s1, params):
    """Returns a pure (N,3) -> (N,3) function. The Jacobian is computed by differencing it."""
    a, b, c = _frame(axis, up)
    A = np.stack([a, b, c], 0)                 # world -> local (rows are basis vectors)
    p = dict(params)
    p["s0"], p["s1"] = float(s0), float(s1)
    fn = _OPS[op]

    def f(P):
        q = np.asarray(P, np.float64) @ A.T    # local coordinates (s, x, y)
        t, s_in, extra = _capture(q[:, 0], s0, s1)
        return fn(q, t, s_in, extra, p) @ A    # back to world

    return f


def _jacobian_normals(f, P, eps):
    """
    Finite-difference Jacobian -> per-point 3x3 J^-T.

    First-order forward differences are enough: these deformations are analytically smooth, the first-order error is O(eps), and
    with eps as a relative step the absolute error is far smaller than "how much the normal itself should rotate". Central differences would need
    three more runs, and the accuracy gain isn't needed here.
    """
    base = f(P)
    cols = []
    for k in range(3):
        d = np.zeros((1, 3), np.float64)
        d[0, k] = eps
        cols.append((f(P + d) - base) / eps)
    J = np.stack(cols, -1)                     # (N,3,3), columns are df/dx_k
    out = np.empty_like(J)
    # Per-point inverse transpose. Singular points (a patch squashed to zero thickness) fall back to the original matrix -- the normal there
    # is undefined anyway; at least don't turn the whole chain into nan
    try:
        out = np.linalg.inv(J).transpose(0, 2, 1)
    except np.linalg.LinAlgError:
        for i in range(len(J)):
            try:
                out[i] = np.linalg.inv(J[i]).T
            except np.linalg.LinAlgError:
                out[i] = J[i]
    bad = ~np.isfinite(out).all(axis=(1, 2))
    if bad.any():
        out[bad] = J[bad]
    return out


DIR_ATTRIBS = ("N", "up", "tangentu", "tangentv")


def _fix_directions(geo, g, f, P, sel, eps, keep_length=False):
    """
    Transforms direction attributes by J^-T. Both point and vertex classes are needed: normals of hard-edged geometry
    live on vertices, and fixing only points would leave the hard edges unfixed.

    Normalized after transformation by default; with keep_length=True (Soft Transform's Preserve Normal Length)
    the original length is kept instead.
    """
    JT = _jacobian_normals(f, P, eps)
    vp = geo.vertex_point.astype(np.int64)
    for cls, idx in ((POINT, None), (VERTEX, vp)):
        for name in DIR_ATTRIBS:
            v = geo.get(cls, name)
            if v is None or v.shape[1] != 3:
                continue
            m = JT if idx is None else JT[idx]
            s = sel if idx is None else sel[idx]
            r = np.asarray(v, np.float64).copy()
            nv = np.einsum("nij,nj->ni", m[s], r[s])
            ln = np.linalg.norm(nv, axis=1, keepdims=True)
            if keep_length:
                nv = nv * np.linalg.norm(r[s], axis=1, keepdims=True)
            r[s] = np.where(ln > 1e-20, nv / np.maximum(ln, 1e-20), r[s])
            g.set(cls, name, r.astype(v.dtype), owned=True)


def _apply(geo, f, sel, normals="jacobian"):
    """Applies a per-point function to geometry, fixing direction attributes along the way."""
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    out = P.copy()
    out[sel] = f(P[sel])
    g = geo.copy()
    g.set(POINT, "P", out.astype(np.float32), owned=True)
    if normals == "jacobian":
        lo, hi = P.min(0), P.max(0)
        diag = float(np.linalg.norm(hi - lo)) or 1.0
        _fix_directions(geo, g, f, P, sel, JAC_EPS * diag)
    return g


def _axis_range(P, a, sel, use_range, s0, s1):
    """Without a given range, the actual span of the selected points along the main axis is used -- default parameters should mean "deform the whole thing"."""
    if use_range:
        return float(s0), float(s1)
    q = P[sel] @ a if sel.any() else P @ a
    lo, hi = float(q.min()), float(q.max())
    return (lo, hi) if hi > lo else (lo, lo + 1.0)


# ═════════════════════════════════════════════════════════════════ Deform
def deform(geo, op="twist", group="", axis="y", angle=45.0, amount=0.5,
           shear_b=0.0, shear_c=0.0, up=(0.0, 1.0, 0.0),
           use_range=False, range_start=0.0, range_end=1.0,
           normals="jacobian", pivot=(0.0, 0.0, 0.0)):
    """
    Twist / Bend / Taper / Squash / Shear. Counterpart of Houdini's Twist SOP.

    pivot (pcg100, Houdini's Pivot: "the local origin of the deformation"): the deformation axis passes through pivot rather than the world origin
    -- the axis twist / taper rotates about, bend's lateral origin and shear's reference are all relative to pivot. The component along the main axis has no effect:
    the capture range (span taken automatically, or absolute coordinates given by Range) is converted with the same translation, so the range stays the same.

    `axis` is the main axis, `up` decides the **secondary direction** (which way bend bends, which way shear pushes); when up is
    parallel to axis another one is picked automatically, never giving nan.

    With `use_range=False` (default) the capture range is the actual span of the selected points along the main axis -- default parameters
    mean "deform the whole thing once". When on, range_start / range_end give absolute coordinates, and the part outside the range
    is **carried rigidly** (not squashed onto the end face).

    Identity parameters (angle=0 / amount=1 / shear=0) are **bitwise** identity.
    """
    if geo is None:
        return Geometry()
    if op not in OPS:
        raise ValueError(f"Op must be one of {OPS}")
    if axis not in AXES:
        raise ValueError(f"Axis must be one of {AXES}")
    if normals not in NORMAL_MODES:
        raise ValueError(f"Normals must be one of {NORMAL_MODES}")
    if geo.npoints == 0 or geo.get(POINT, "P") is None:
        return geo.copy()
    sel = resolve(geo, POINT, group)
    if not sel.any():
        return geo.copy()
    ident = ((op in ("twist", "bend") and float(angle) == 0.0)
             or (op in ("taper", "squash") and float(amount) == 1.0)
             or (op == "shear" and float(shear_b) == 0.0
                 and float(shear_c) == 0.0))
    if ident:
        return geo.copy()                      # not a single floating-point operation
    a, _, _ = _frame(axis, up)
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    s0, s1 = _axis_range(P, a, sel, use_range, range_start, range_end)
    f = _deformer(op, axis, up, s0, s1,
                  {"angle": angle, "amount": amount,
                   "shear_b": shear_b, "shear_c": shear_c})
    pv = np.asarray(pivot, np.float64).reshape(3)
    if np.any(pv):
        # Deform in coordinates with pivot as origin; the range is in absolute coordinates and translated the same way (so the axial component cancels)
        k = float(a @ pv)
        f0 = _deformer(op, axis, up, s0 - k, s1 - k,
                       {"angle": angle, "amount": amount,
                        "shear_b": shear_b, "shear_c": shear_c})

        def f(Q, f0=f0):
            return f0(Q - pv) + pv
    return _apply(geo, f, sel, normals)


# ═════════════════════════════════════════════════════════ Soft Transform
def _euler_mats(rx, ry, rz):
    """
    (N,) angles (radians) -> (N,3,3) Euler rotations, Houdini's default Rx Ry Rz (X first,
    Z last, M = Rz*Ry*Rx), the same convention as ops.euler_matrix. Before pcg85 this was written
    as Rx*Ry*Rz (Z first), wrong together with Transform.
    """
    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)
    n = len(rx)
    M = np.empty((n, 3, 3), np.float64)
    M[:, 0, 0] = cz * cy
    M[:, 0, 1] = cz * sy * sx - sz * cx
    M[:, 0, 2] = cz * sy * cx + sz * sx
    M[:, 1, 0] = sz * cy
    M[:, 1, 1] = sz * sy * sx + cz * cx
    M[:, 1, 2] = sz * sy * cx - cz * sx
    M[:, 2, 0] = -sy
    M[:, 2, 1] = cy * sx
    M[:, 2, 2] = cy * cx
    return M


MAX_FALLOFF_PAIRS = 200_000_000


def _euclid_distance(P, seed):
    """Euclidean distance to the nearest seed point. Computed in chunks so N x M doesn't eat all memory at once."""
    S = P[seed]
    if not len(S):
        return np.full(len(P), np.inf)
    if len(P) * len(S) > MAX_FALLOFF_PAIRS:
        raise MemoryError(
            f"The soft selection has {len(P)} x {len(S)} candidate pairs -- too many. "
            f"Switch Metric to distance (walks along edges, spreading only within the radius), "
            f"or shrink the handle group.")
    out = np.empty(len(P), np.float64)
    step = max(1, int(4_000_000 // max(len(S), 1)))
    for i in range(0, len(P), step):
        d = P[i:i + step, None, :] - S[None, :, :]
        out[i:i + step] = np.sqrt((d * d).sum(-1)).min(1)
    return out


def rolloff(t, soft_type="ramp", ramp="0:0  1:1", ramp_mode="smooth",
            tangents=(0.0, 0.0), kernel="links"):
    """
    Normalized distance t in [0, 1] (0 = on the handle, 1 = at Soft Radius) -> weight.

    ramp       old behaviour: Ramp(1 - t)
    linear     1 − t
    quadratic  1 - t^2. The docs give no formula, only "falls off more slowly than Cubic, distant points are affected more";
               1 - t^2 is >= Cubic (smoothstep with default tangents) over the whole range, satisfying that sentence
    cubic      cubic Hermite in s = 1 - t: f(0)=0, f(1)=1, slope tan(Tangent Angles[0]) at s=0 (farthest),
               slope tan(Tangent Angles[1]) at s=1 (nearest). With both angles 0 it is smoothstep.
               The docs say "the first value applies to the tangent farthest from the source points, the second to the nearest"; the angle's zero and direction
               are not stated; here they are read as "inclination relative to the horizontal"
    metaball   the three kernels whose formulas the Metaball SOP docs give (t is the normalized distance):
               links      1 - 3t^2 (t < 1/3), 1.5(1 - t)^2 (t < 1)
               renderman  1 − 3t² + 3t⁴ − t⁶
               hart       1 − 6t⁵ + 15t⁴ − 10t³
    """
    t = np.clip(np.asarray(t, np.float64).reshape(-1), 0.0, 1.0)
    if soft_type == "ramp":
        from .ramp import parse as _parse, apply as _apply_ramp
        pos, val = _parse(str(ramp), 1)
        return np.asarray(_apply_ramp(1.0 - t, pos, val, ramp_mode), np.float64).reshape(-1)
    if soft_type == "linear":
        return 1.0 - t
    if soft_type == "quadratic":
        return 1.0 - t * t
    if soft_type == "cubic":
        m0, m1 = (np.tan(np.radians(float(a))) for a in tangents)
        u = 1.0 - t
        u2, u3 = u * u, u * u * u
        return (-2 * u3 + 3 * u2) + m0 * (u3 - 2 * u2 + u) + m1 * (u3 - u2)
    if soft_type == "metaball":
        if kernel == "links":
            return np.where(t < 1.0 / 3.0, 1.0 - 3.0 * t * t, 1.5 * (1.0 - t) ** 2)
        if kernel == "renderman":
            t2 = t * t
            return 1.0 - 3.0 * t2 + 3.0 * t2 * t2 - t2 * t2 * t2
        if kernel == "hart":
            return 1.0 - 6.0 * t ** 5 + 15.0 * t ** 4 - 10.0 * t ** 3
        raise ValueError(f"Kernel Function must be one of {KERNELS}")
    raise ValueError(f"Soft Type must be one of {SOFT_TYPES}")


def _point_attr1(geo, name, what):
    a = geo.get(POINT, str(name or "").strip())
    if a is None or a.dtype.kind not in "fiu":
        raise KeyError(f"{what}: no numeric attribute {name!r} on points")
    return np.asarray(a, np.float64)[:, 0]


def _connected_within(geo, sel, ok):
    """Points reachable from sel along edges passing only through ok points (Radius with Connectivity)."""
    off, nb, _ = _adj.adjacency(geo, POINT)
    reach = sel.copy()
    if not len(nb):
        return reach
    src = np.repeat(np.arange(geo.npoints, dtype=np.int64), np.diff(off))
    while True:
        hit = np.zeros(geo.npoints, bool)
        np.logical_or.at(hit, nb, reach[src])
        new = reach | (hit & ok)
        if np.array_equal(new, reach):
            return reach
        reach = new


def soft_falloff(geo, group="", radius=1.0, metric="euclidean",
                 ramp="0:0  1:1", ramp_mode="smooth", soft_type="ramp",
                 tangents=(0.0, 0.0), kernel="links", distance_attribute="dist",
                 apply_rolloff=True):
    """
    Soft selection weights: 1 inside the group, falling off by the ramp outward to 0 at radius.

    `euclidean` is straight-line distance (works on point clouds too, but **leaks across gaps**); `distance`
    and `steps` walk along edges (spreading only over connected parts, geometrically more correct, but topology is required).

    pcg100:
      radius_with_connectivity  straight-line distance, but there must be a path along edges, entirely within the radius, connecting to the handle
                                (marked deprecated by Houdini, still listed in the docs)
      attribute                 the distance is taken directly from point attribute distance_attribute. apply_rolloff on: used as the raw distance,
                                falling off by Soft Type within the radius; off: the attribute value is used directly as the weight (no truncation).
                                This option has no "handle": the group only limits who can move (empty = all points), and the group isn't forced to 1
      soft_type / tangents / kernel  see rolloff()
    """
    n = geo.npoints
    if metric == "attribute":
        d = _point_attr1(geo, distance_attribute, "Distance Attribute")
        sel = resolve(geo, POINT, group)
        if apply_rolloff:
            r = float(radius)
            t = d / max(r, 1e-12)                          # clipped to [0, 1] in rolloff (negative distance = on the handle)
            w = rolloff(t, soft_type, ramp, ramp_mode, tangents, kernel)
            w[d > r] = 0.0
        else:
            w = d.copy()
        w[~sel] = 0.0
        return w, sel
    sel = resolve(geo, POINT, group) if str(group or "").strip() \
        else np.zeros(n, bool)
    if not sel.any():
        return np.zeros(n, np.float64), sel
    r = float(radius)
    if metric in ("euclidean", "radius_with_connectivity"):
        P = np.asarray(geo.get(POINT, "P"), np.float64)
        d = _euclid_distance(P, sel)
        far = d > r
        if metric == "radius_with_connectivity":
            far = ~_connected_within(geo, sel, ~far)
    elif metric in _adj.METRICS:
        d, far = _adj.distance_from(geo, POINT, sel, metric, r)
    else:
        raise ValueError(f"Metric must be one of {METRICS}")
    t = np.where(far, 1.0, np.clip(d / max(r, 1e-12), 0.0, 1.0))
    w = rolloff(t, soft_type, ramp, ramp_mode, tangents, kernel)
    w[far] = 0.0
    w[sel] = 1.0
    return w, sel


def nearest_handle(geo, sel, metric="euclidean", radius=1.0):
    """
    Point number of each point's "nearest handle point" (unreachable = -1), using the same distance as soft_falloff.
    Used by Soft Peak's Translate Along Lead Normal. On equal distances the lower point number wins.
    """
    n = geo.npoints
    lead = np.full(n, -1, np.int64)
    idx = np.nonzero(sel)[0]
    if not len(idx):
        return lead
    if metric in ("euclidean", "radius_with_connectivity"):
        P = np.asarray(geo.get(POINT, "P"), np.float64)
        S = P[idx]
        step = max(1, int(4_000_000 // max(len(S), 1)))
        for i in range(0, n, step):
            dd = ((P[i:i + step, None, :] - S[None, :, :]) ** 2).sum(-1)
            lead[i:i + step] = idx[np.argmin(dd, 1)]
        return lead
    # Along edges: first compute d with the same distance, then for each point pick an upstream neighbour whose "d[u] + w(u,v) is closest to d[v]"
    # as parent (only from points with smaller d, and with equal d only from lower point numbers -- guaranteeing no cycles), following the parent chain to the root
    if metric == "steps":
        d = _adj.hop_distance(geo, POINT, sel, -1).astype(np.float64)
        off, nb, w = _adj.adjacency(geo, POINT)
    else:
        d = _adj.edge_distance(geo, POINT, sel)
        off, nb, w = _adj.adjacency(geo, POINT, weighted=True)
    lead[idx] = idx
    if not len(nb):
        return lead
    u = np.repeat(np.arange(n, dtype=np.int64), np.diff(off))
    v = nb
    ok = np.isfinite(d[u]) & np.isfinite(d[v]) & ~sel[v] & (
        (d[u] < d[v]) | ((d[u] == d[v]) & (u < v)))
    u, v, err = u[ok], v[ok], np.abs(d[u[ok]] + w[ok] - d[v[ok]])
    order = np.lexsort((u, err, v))
    v, u = v[order], u[order]
    first = np.ones(len(v), bool)
    first[1:] = v[1:] != v[:-1]
    parent = np.arange(n, dtype=np.int64)
    parent[v[first]] = u[first]
    for _ in range(64):
        nxt = parent[parent]
        if np.array_equal(nxt, parent):
            break
        parent = nxt
    # Unreachable points (d = -1 under steps) are their own parent, lead = themselves; their weights are 0 anyway, so it doesn't affect the result
    reach = np.isfinite(d)
    lead[reach] = parent[reach]
    return lead


SOFT_NORMAL_MODES = NORMAL_MODES + ("recompute_point", "recompute_affected")


def _rot_n(ang, order):
    """(n,3) radians -> (n,3,3) Euler rotations in column-vector convention; order is the sequence (same as ops.euler_matrix)."""
    n = len(ang)
    c, s_ = np.cos(ang), np.sin(ang)
    R = {}
    for k, (i, j) in zip("xyz", ((1, 2), (2, 0), (0, 1))):
        a = "xyz".index(k)
        M = np.zeros((n, 3, 3))
        M[:, a, a] = 1.0
        M[:, i, i] = c[:, a]
        M[:, j, j] = c[:, a]
        M[:, i, j] = -s_[:, a]
        M[:, j, i] = s_[:, a]
        R[k] = M
    out = np.broadcast_to(np.eye(3), (n, 3, 3)).copy()
    for k in order:
        out = R[k] @ out
    return out


def soft_transform(geo, group="", translate=(0.0, 0.0, 0.0),
                   rotate=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0),
                   pivot=(0.0, 0.0, 0.0), use_group_center=True,
                   radius=1.0, metric="euclidean", ramp="0:0  1:1",
                   ramp_mode="smooth", normals="jacobian",
                   falloff_attrib="", xform_order="srt", rotate_order="xyz",
                   shear=(0.0, 0.0, 0.0), pivot_rotate=(0.0, 0.0, 0.0),
                   soft_type="ramp", tangents=(0.0, 0.0), kernel="links",
                   distance_attribute="dist", apply_rolloff=True,
                   preserve_normal_length=False):
    """
    Falloff transform (Houdini's Soft Transform / soft selection).

    **What is interpolated is the parameters, not the result.** Each point computes its own matrix on the spot from `angle x w`, `translation x w`,
    `scale lerp(1, s, w)`, rather than `lerp(P, M*P, w)` --
    the latter eats the radius on rotation (worst at weight 0.5), visually the soft selection region collapses into a ring.

    `use_group_center=True` (default) sets pivot to the handle group's centroid, which is also the intuition of dragging by hand.
    If `falloff_attrib` is given a name, the weights are also written as a point attribute, handy for further use.

    pcg100 additions (default = old behaviour):
      xform_order / rotate_order / shear / pivot_rotate
          the same matrix as the Transform SOP (ops.xform_matrix's convention); shear is also interpolated by x w,
          Pivot Rotate is the orientation of the pivot frame and is **not** interpolated by weight
      soft_type / tangents / kernel / distance_attribute / apply_rolloff  see soft_falloff
          (with Metric = attribute there is no handle: the group only limits who can move, empty = all points; Pivot at Group Centroid
          takes the centroid of the points in the group)
      normals  appended at the end: recompute_point (if N exists, recompute it all as point normals, deleting the old vertex N) /
               recompute_affected (recompute only the affected point / vertex N, see topology.recompute_affected_normals)
      preserve_normal_length  keep the original length when the jacobian option transforms N (old behaviour normalizes)
    """
    if geo is None:
        return Geometry()
    if normals not in SOFT_NORMAL_MODES:
        raise ValueError(f"Normals must be one of {SOFT_NORMAL_MODES}")
    from .ops import XFORM_ORDERS, ROTATE_ORDERS, euler_matrix
    if xform_order not in XFORM_ORDERS:
        raise ValueError(f"Transform Order must be one of {XFORM_ORDERS}")
    if rotate_order not in ROTATE_ORDERS:
        raise ValueError(f"Rotate Order must be one of {ROTATE_ORDERS}")
    if geo.npoints == 0 or geo.get(POINT, "P") is None:
        return geo.copy()
    if metric == "attribute" or str(group or "").strip():
        w, sel = soft_falloff(geo, group, radius, metric, ramp, ramp_mode, soft_type,
                              tangents, kernel, distance_attribute, apply_rolloff)
    else:
        # Empty Group = all points (Houdini's rule; before pcg90 empty moved nothing):
        # everything is a handle with weight 1, i.e. a plain transform
        sel = np.ones(geo.npoints, bool)
        w = np.ones(geo.npoints, np.float64)
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    piv = (P[sel].mean(0) if (use_group_center and sel.any())
           else np.asarray(pivot, np.float64).reshape(3))
    T = np.asarray(translate, np.float64).reshape(3)
    R = np.radians(np.asarray(rotate, np.float64).reshape(3))
    S = np.asarray(scale, np.float64).reshape(3)
    SH = np.asarray(shear, np.float64).reshape(3)
    PRa = np.asarray(pivot_rotate, np.float64).reshape(3)
    ident = (not np.any(T) and not np.any(R) and np.all(S == 1.0) and not np.any(SH))
    if ident or not np.any(w):
        g = geo.copy()
        if str(falloff_attrib).strip():
            g.set(POINT, falloff_attrib.strip(),
                  w[:, None].astype(np.float32), owned=True)
        return g

    extra = (xform_order != "srt" or rotate_order != "xyz" or np.any(SH) or np.any(PRa))
    if not extra:
        def f(Q, wq):
            M = _euler_mats(R[0] * wq, R[1] * wq, R[2] * wq)
            k = 1.0 + (S[None, :] - 1.0) * wq[:, None]
            q = (Q - piv) * k
            return np.einsum("nij,nj->ni", M, q) + piv + T[None, :] * wq[:, None]
    else:
        # Row-vector convention (p' = p*L + t), consistent with ops.xform_matrix:
        #   (p - piv)*PR^T -> in Transform Order [S*Sh] / [R^T] / [+T] -> *PR -> + piv
        PR = euler_matrix(*PRa, order=rotate_order).astype(np.float64).T

        def f(Q, wq):
            n = len(Q)
            k = 1.0 + (S[None, :] - 1.0) * wq[:, None]
            Ls = np.zeros((n, 3, 3))
            Ls[:, [0, 1, 2], [0, 1, 2]] = k
            sh = np.broadcast_to(np.eye(3), (n, 3, 3)).copy()
            sh[:, 1, 0], sh[:, 2, 0], sh[:, 2, 1] = (SH[None, :] * wq[:, None]).T
            Ls = Ls @ sh
            Lr = np.transpose(_rot_n(R[None, :] * wq[:, None], rotate_order), (0, 2, 1))
            q = (Q - piv) @ PR.T
            for c in xform_order:
                if c == "s":
                    q = np.einsum("ni,nij->nj", q, Ls)
                elif c == "r":
                    q = np.einsum("ni,nij->nj", q, Lr)
                else:
                    q = q + T[None, :] * wq[:, None]
            return q @ PR + piv

    # The Jacobian needs a function of position only. Weights travel with the points; when differencing **weights are not recomputed** --
    # recomputing would give the joint derivative of "position + weight field", which is not the linear map we want for
    # transforming normals (and the weight field is not differentiable at group boundaries, so normals would explode into a ring of noise there)
    def f_pos(Q):
        return f(Q, w)

    out = f(P, w)
    g = geo.copy()
    g.set(POINT, "P", out.astype(np.float32), owned=True)
    if normals == "jacobian":
        lo, hi = P.min(0), P.max(0)
        diag = float(np.linalg.norm(hi - lo)) or 1.0
        _fix_directions(geo, g, f_pos, P, np.ones(len(P), bool),
                        JAC_EPS * diag, keep_length=preserve_normal_length)
    elif normals == "recompute_point":
        if g.has(POINT, "N") or g.has(VERTEX, "N"):
            from .ops import compute_normals
            g.remove(VERTEX, "N")
            g = compute_normals(g, "point")
    elif normals == "recompute_affected":
        from .topology import recompute_affected_normals
        g = recompute_affected_normals(g, np.any(out.astype(np.float32) != geo.get(POINT, "P"), axis=1))
    if str(falloff_attrib).strip():
        g.set(POINT, falloff_attrib.strip(), w[:, None].astype(np.float32),
              owned=True)
    return g


# ══════════════════════════════════════════════════════════════ Spherify
def spherify(geo, group="", amount=1.0, radius=0.0, center=(0.0, 0.0, 0.0),
             use_center=False, normals="jacobian"):
    """
    Pushes the selected points onto a sphere: `P' = lerp(P, C + normalize(P-C)*R, amount)`.

    radius 0 = the **average** distance of the selected points from the centre (least volume change, and the act of "spherifying"
    shouldn't scale as a side effect). The centre defaults to the centroid of the selected points.

    amount=0 is bitwise identity; at amount=1 all points land exactly on the sphere of radius R.
    """
    if geo is None:
        return Geometry()
    if geo.npoints == 0 or geo.get(POINT, "P") is None:
        return geo.copy()
    if float(amount) == 0.0:
        return geo.copy()
    sel = resolve(geo, POINT, group)
    if not sel.any():
        return geo.copy()
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    C = (np.asarray(center, np.float64).reshape(3) if use_center
         else P[sel].mean(0))
    d = np.linalg.norm(P[sel] - C, axis=1)
    R = float(radius) if float(radius) > 0 else float(d.mean())
    k = float(amount)

    def f(Q):
        v = Q - C
        n = np.linalg.norm(v, axis=1, keepdims=True)
        # Points exactly at the centre have no direction; left as they are (otherwise 0/0)
        tgt = np.where(n > 1e-20, C + v / np.maximum(n, 1e-20) * R, Q)
        return Q + (tgt - Q) * k

    return _apply(geo, f, sel, normals)
