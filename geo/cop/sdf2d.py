"""
2D signed distances added for SDF Shape (pcg100 c4): polygon / squircle / trapezoid / triangle / rhombus /
egg / moon / vesica / cross / arch / arrow, plus the circle's sector / ring / arc,
a rectangle with a separate radius per corner, and a line with different thickness at each end.

Everything is computed in numpy float64. Input q is a (..., 2) array of local coordinates (center already subtracted, rotation applied);
returns distances with the same shape minus the last axis, **negative inside, positive outside**, in the same units as q.

Why a separate file instead of adding to the backend's op table: these formulas have lots of branches and
"pick a formula by region"; writing each one twice (numpy and torch backends) buys little. Shapes are only computed once at
generation time, so they are computed on the CPU and handed to the backend; the cost is one copy.

Which ones are exact SDFs and which aren't is noted on each function. For the non-exact ones the **zero isoline (the shape
itself) is correct**; only distance values far from the edge are off -- strokes / masks are unaffected, large-radius
dilation will show it.

Formula sources: except where marked "derived ourselves", all are Inigo Quilez's published 2D distance functions
(iquilezles.org/articles/distfunctions2d). The parameter names in SideFX's SDF Shape docs
(Roundness = 0 pointed / 1 circle, Moon's Outer / Inner / Offset, Squircle's
Blend = 2 is a circle, 1 is a rhombus) map one to one onto these functions' parameters.
"""
from __future__ import annotations

import numpy as np


def _len(x, y):
    return np.sqrt(x * x + y * y)


# ════════════════════════════════════════════════════════ General: any simple polygon
def polygon(q, verts):
    """
    Exact SDF of any **simple** polygon (convex or concave, any vertex order).

    Distance = min of distances to each edge (segment); sign from ray-crossing count (even outside, odd inside).
    Triangle / trapezoid / rhombus / arrow all go through here -- one implementation, exact, and no need to
    derive a formula per shape.
    """
    v = np.asarray(verts, np.float64).reshape(-1, 2)
    px, py = q[..., 0], q[..., 1]
    d = (px - v[0, 0]) ** 2 + (py - v[0, 1]) ** 2
    s = np.ones(px.shape)
    n = len(v)
    j = n - 1
    for i in range(n):
        ex, ey = v[j, 0] - v[i, 0], v[j, 1] - v[i, 1]
        wx, wy = px - v[i, 0], py - v[i, 1]
        ee = ex * ex + ey * ey
        t = np.clip((wx * ex + wy * ey) / (ee if ee > 0 else 1.0), 0.0, 1.0)
        bx, by = wx - ex * t, wy - ey * t
        d = np.minimum(d, bx * bx + by * by)
        c1 = py >= v[i, 1]
        c2 = py < v[j, 1]
        c3 = ex * wy > ey * wx
        flip = (c1 & c2 & c3) | (~c1 & ~c2 & ~c3)
        s = np.where(flip, -s, s)
        j = i
    return s * np.sqrt(d)


# ════════════════════════════════════════════════════════ Basic
def regular_polygon(q, radius, sides):
    """
    Regular n-gon, radius = circumradius, one vertex pointing +y (same orientation as the star). Exact.
    """
    n = max(3, int(sides))
    r = float(radius)
    an = np.pi / n
    ca, sa = np.cos(an), np.sin(an)
    # angle measured from +y, folded into one sector [-an, an]
    bn = np.mod(np.arctan2(q[..., 0], q[..., 1]), 2.0 * an) - an
    ln = _len(q[..., 0], q[..., 1])
    x = ln * np.cos(bn) - r * ca
    y = ln * np.abs(np.sin(bn)) - r * sa
    y = y + np.clip(-y, 0.0, r * sa)
    return _len(x, y) * np.sign(x)


def squircle(q, radius, blend):
    """
    Squircle |x|^n + |y|^n = r^n, n = Blend (2 circle, 1 rhombus, larger is squarer -- matches the docs).

    **Not an exact SDF**: a superellipse has no closed-form distance. This uses the first-order correction f / |grad f|
    (f = ||q||_n - r); the zero isoline is exact and the distance error near the edge is second order; at n = 2 it reduces to
    the exact circle. The docs don't say what Blend < 1 does; here it is clamped to >= 0.25 (smaller gives the star's
    concave edges and is numerically unstable).
    """
    n = max(float(blend), 0.25)
    ax = np.abs(q[..., 0])
    ay = np.abs(q[..., 1])
    m = np.maximum(np.maximum(ax, ay), 1e-30)
    # divide by the largest component before raising to the power, to prevent overflow at large n
    sx, sy = ax / m, ay / m
    pn = sx ** n + sy ** n
    norm = m * pn ** (1.0 / n)
    f = norm - float(radius)
    # component of grad ||q||_n = (|x|/||q||_n)^(n-1). Undefined at the origin: take the limit along the diagonal
    # sqrt2 * 2^(-(n-1)/n) (sqrt2 at n = 1, so the center is exactly -r/sqrt2; 1 at n = 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        nz = norm > 0
        sn = np.where(nz, norm, 1.0)
        g = _len((ax / sn) ** (n - 1), (ay / sn) ** (n - 1))
    g = np.where(nz, g, np.sqrt(2.0) * 2.0 ** (-(n - 1) / n))
    g = np.maximum(g, 1e-12)
    return f / g


def trapezoid(q, bottom_half, top_half, half_height):
    """Isosceles trapezoid: bottom half-length, top half-length, half-height, centered. Exact (via polygon)."""
    b, t, h = float(bottom_half), float(top_half), float(half_height)
    return polygon(q, [(-b, -h), (b, -h), (t, h), (-t, h)])


def triangle(q, p0, p1, p2):
    """Arbitrary triangle, three vertices. Exact (via polygon)."""
    return polygon(q, [p0, p1, p2])


def diamond(q, half_w, half_h):
    """Rhombus: horizontal / vertical half-diagonals. Exact (via polygon)."""
    w, h = float(half_w), float(half_h)
    return polygon(q, [(0, -h), (w, 0), (0, h), (-w, 0)])


def rounded_box4(q, half, radii):
    """
    Rectangle with a separate rounding per corner. radii = (top-right, bottom-right, top-left, bottom-left) (absolute radii; the caller
    is responsible for clamping to at most the shorter half-side). Exact (Quilez sdRoundedBox).
    """
    rtr, rbr, rtl, rbl = (float(r) for r in radii)
    x, y = q[..., 0], q[..., 1]
    r = np.where(x > 0, np.where(y > 0, rtr, rbr), np.where(y > 0, rtl, rbl))
    bx, by = float(half[0]), float(half[1])
    qx = np.abs(x) - bx + r
    qy = np.abs(y) - by + r
    out = _len(np.maximum(qx, 0.0), np.maximum(qy, 0.0))
    return np.minimum(np.maximum(qx, qy), 0.0) + out - r


def ring_sector(q, radius, arc=1.0, thickness=1.0, round_ends=False):
    """
    Circle's Arc / Thickness / Round Ends.

    · Thickness < 1: hollowed into a ring, ring width = radius x Thickness (outer edge stays at radius)
    · Arc < 1: keeps only a segment with central angle Arc x 360 deg, opening toward -y (the segment is symmetric about the +y axis)
    · Both on and Round Ends: the ends are semicircles (Quilez sdArc), otherwise the ends are flat

    The docs only say "values below 1 turn it into an open arc / hollow ring" and **don't say** how ring width is measured, which way
    the opening faces, or whether Arc is a fraction or an angle -- the three rules above are our own choice. When both equal 1 it's a full circle and the
    caller goes straight to sdf_circle, not here.

    Exact: solid sector, ring and arc (round ends) are all exact SDFs; the flat-ended ring sector is exact outside the ends,
    and inside the ends it is "the nearer of arc and end face", also exact (convex region).
    """
    R = float(radius)
    a = float(np.clip(arc, 0.0, 1.0)) * np.pi           # half aperture angle
    t = float(np.clip(thickness, 0.0, 1.0))
    if t >= 1.0:
        rc, w = R * 0.5, R * 0.5                         # solid: inner radius 0
    else:
        w = R * t * 0.5
        rc = R - w
    x = np.abs(q[..., 0])
    y = q[..., 1]
    ln = _len(x, y)
    if a >= np.pi:
        return np.abs(ln - rc) - w
    sc, cc = np.sin(a), np.cos(a)
    outside_ang = cc * x > sc * y                        # outside the kept segment
    if round_ends and t < 1.0:
        dcap = _len(x - sc * rc, y - cc * rc) - w
        return np.where(outside_ang, dcap, np.abs(ln - rc) - w)
    # flat ends: the end face is a ray segment from (rc-w) to (rc+w)
    r0, r1 = rc - w, rc + w
    proj = np.clip(x * sc + y * cc, r0, r1)
    dseg = _len(x - sc * proj, y - cc * proj)
    radial = np.abs(ln - rc) - w
    inside = (~outside_ang) & (radial <= 0)
    if t >= 1.0:
        # solid sector: there is no inner circle (inner radius 0), so the distance to the "inner circle" can't be used
        radial_in = ln - R
        return np.where(outside_ang, dseg,
                        np.where(radial_in <= 0,
                                 -np.minimum(-radial_in, dseg), radial_in))
    return np.where(outside_ang, dseg,
                    np.where(inside, -np.minimum(-radial, dseg), radial))


def uneven_capsule(q, a, b, ra, rb):
    """
    Capsule with different radii at its two ends (Line's Start / End Thickness). Exact (arbitrary-orientation
    version of Quilez sdUnevenCapsule). When one end's circle fully contains the other (|ra - rb| >=
    length) it degenerates to the larger circle.
    """
    a = np.asarray(a, np.float64).reshape(2)
    b = np.asarray(b, np.float64).reshape(2)
    ra, rb = float(ra), float(rb)
    px, py = q[..., 0] - a[0], q[..., 1] - a[1]
    bx, by = b - a
    h = bx * bx + by * by
    bd = ra - rb
    if h <= bd * bd:                                     # degenerate: one circle contains the other
        if ra >= rb:
            return _len(px, py) - ra
        return _len(px - bx, py - by) - rb
    qx = np.abs(px * by - py * bx) / h
    qy = (px * bx + py * by) / h
    cx, cy = np.sqrt(h - bd * bd), bd
    k = cx * qy - cy * qx
    m = cx * qx + cy * qy
    n = qx * qx + qy * qy
    return np.where(k < 0, np.sqrt(h * n) - ra,
                    np.where(k > cx, np.sqrt(h * (n + 1.0 - 2.0 * qy)) - rb,
                             m - ra))


# ════════════════════════════════════════════════════════ Compound
def egg(q, radius, roundness):
    """
    Egg (Moss egg, Quilez sdEgg). radius = lower circle radius; Roundness = top small circle radius /
    radius: 0 pointed, 1 circle (matches the docs' "0 pointed, 1 round"). The lower circle is centered at the origin, tip toward +y,
    so overall it is **not** centered on its bounding-box center -- the docs don't say where the origin is, so the formula's natural origin is used.
    Exact.
    """
    ra = float(radius)
    rb = float(np.clip(roundness, 0.0, 1.0)) * ra
    k = np.sqrt(3.0)
    x = np.abs(q[..., 0])
    y = q[..., 1]
    r = ra - rb
    return np.where(y < 0, _len(x, y) - r,
                    np.where(k * (x + r) < y, _len(x, y - k * r),
                             _len(x + r, y) - 2.0 * r)) - rb


def vesica(q, radius, roundness):
    """
    Vesica (intersection of two circles, tips up and down, Quilez sdVesica). radius = radius of both circles;
    Roundness sets the distance between centers d = radius x (1 - Roundness): 1 is a circle, smaller is flatter.
    The docs only say Roundness is "the thickness in the vertical direction"; this mapping is our own choice. Exact.
    """
    r = float(radius)
    d = r * (1.0 - float(np.clip(roundness, 0.0, 1.0)))
    x = np.abs(q[..., 0])
    y = np.abs(q[..., 1])
    b = np.sqrt(max(r * r - d * d, 0.0))
    return np.where((y - b) * d > x * b, _len(x, y - b), _len(x + d, y) - r)


def moon(q, outer, inner, offset):
    """
    Moon: a circle of radius outer with a circle of radius inner centered at (offset, 0) cut out (Quilez sdMoon).
    Maps one to one onto the docs' Outer Radius / Inner Radius / Inner Offset. Exact.
    At offset = 0 the formula divides by zero, so a tiny value is nudged in (concentric circles: the result is a ring or empty).
    """
    ra, rb = float(outer), float(inner)
    d = float(offset)
    if abs(d) < 1e-9:
        d = 1e-9
    sgn = 1.0 if d > 0 else -1.0
    d = abs(d)
    x = q[..., 0] * sgn                                  # negative offset = cut on the left, mirror it
    y = np.abs(q[..., 1])
    a = (ra * ra - rb * rb + d * d) / (2.0 * d)
    b = np.sqrt(max(ra * ra - a * a, 0.0))
    cond = d * (x * b - y * a) > d * d * np.maximum(b - y, 0.0)
    return np.where(cond, _len(x - a, y - b),
                    np.maximum(_len(x, y) - ra, -(_len(x - d, y) - rb)))


def cross(q, size, inset, bevel=0.0):
    """
    Cross (plus shape). size = outer half-size (arm end to center); Inset = side length of the square cut from each corner:
    0 is a square (matches the docs' "0 is a box"), larger gives thinner arms. Arm half-width = size - inset.

    Bevel: rounds the inner (concave) corners, radius = Bevel (clamped to at most Inset and the arm half-width).

    Exact: the cross is symmetric about the x and y axes and the diagonals, so fold into the eighth 0 <= y <= x, leaving only
    three boundary pieces -- the arm's top edge y = a (x from a+r to size), the arm end x = size (y from 0 to a), and the
    quarter arc of the concave-corner rounding (center (a+r, a+r)). Unsigned distance is the min over
    the three pieces; inside/outside is decided by region. With Bevel = 0 it's a square-cornered cross.
    """
    s = float(size)
    # arm half-width. When Inset >= Size, a = 0: zero arm width, and the code below still gives "distance to the cross lines"
    # (the interior has measure zero); no separate error -- this is the continuous limit
    # when Inset = 0, a = s and the three pieces naturally reduce to the square's edges, no separate branch needed
    a = float(np.clip(s - float(inset), 0.0, s))
    r = float(np.clip(bevel, 0.0, min(s - a, a)))
    x = np.abs(q[..., 0])
    y = np.abs(q[..., 1])
    x, y = np.maximum(x, y), np.minimum(x, y)            # fold into 0 <= y <= x
    # arm top edge: y = a, x in [a + r, s]
    d1 = _len(x - np.clip(x, a + r, s), y - a)
    # arm end: x = s, y in [0, a]
    d2 = _len(x - s, y - np.clip(y, 0.0, a))
    dist = np.minimum(d1, d2)
    inside = (x <= s) & (y <= a)
    if r > 0.0:
        cx = cy = a + r
        vx, vy = x - cx, y - cy
        lv = _len(vx, vy)
        # the whole quarter arc (from (a+r, a) to (a, a+r)) is boundary, so use all of it: when a folded point
        # lands on the half beyond the diagonal, the distance to that half is the distance to the whole arc, no need to
        # truncate at the eighth (mutation testing showed the truncation is redundant)
        # when the direction is outside the arc's aperture, the nearest point is an arc endpoint: (a+r, a) is already an endpoint of the arm top edge segment,
        # and the folded image of (a, a+r) (y <= x) is never closer than (a+r, a) -- so only the aperture matters
        on = (vy <= 0) & (vx <= 0)
        dist = np.where(on, np.minimum(dist, np.abs(lv - r)), dist)
        # fill the corner: x <= a+r and outside the circle. The y < a part is already inside the arm, so no need to also require y >= a
        inside = inside | ((x <= a + r) & (lv >= r))
    return np.where(inside, -dist, dist)


def arch(q, width, height):
    """
    Arch (doorway shape): a rectangle of width width (height height) topped by a semicircle of diameter width;
    height = 0 is just the semicircle (matches the docs). Centered on its bounding box overall.
    The docs give no shape definition; this is the usual meaning of "arch", our own choice.

    = vertical segment capsule ∩ {y >= bottom edge}; outside the two bottom corners the distance to the corner point is computed separately -> exact.
    """
    r = float(width) * 0.5
    h = max(float(height), 0.0)
    tot = h + r
    x = np.abs(q[..., 0])
    y = q[..., 1] + tot * 0.5 - h                        # move the semicircle center to the origin
    yc = np.clip(y, -h, 0.0)
    dcap = _len(x, y - yc) - r
    dbot = -(y + h)
    d = np.maximum(dcap, dbot)
    corner = (y < -h) & (x > r)
    return np.where(corner, _len(x - r, y + h), d)


def arrow(q, a, b, shaft, head, head_ratio):
    """
    Arrow: points from a to b. Shaft width shaft, widest arrowhead width head (both full widths), arrowhead length = total length x
    head_ratio. A seven-vertex polygon, exact. The docs only give parameter names; making the arrowhead length "a fraction of
    the total length" is our own choice (the literal meaning of Head Ratio).
    """
    a = np.asarray(a, np.float64).reshape(2)
    b = np.asarray(b, np.float64).reshape(2)
    dv = b - a
    L = float(np.hypot(*dv))
    if L <= 0:
        # start and end coincide: the arrow shrinks to a point, give the distance to that point (continuous limit, no inf)
        return _len(q[..., 0] - a[0], q[..., 1] - a[1])
    ux, uy = dv / L
    nx, ny = -uy, ux
    hl = float(np.clip(head_ratio, 0.0, 1.0)) * L
    s, hw = float(shaft) * 0.5, float(head) * 0.5
    loc = [(0, -s), (L - hl, -s), (L - hl, -hw), (L, 0), (L - hl, hw),
           (L - hl, s), (0, s)]
    verts = [(a[0] + t * ux + w * nx, a[1] + t * uy + w * ny) for t, w in loc]
    return polygon(q, verts)
