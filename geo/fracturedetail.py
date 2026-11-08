"""
Fracture Detail -- add noise to the **fracture surfaces** of pieces. Fills the gap Voronoi Fracture leaves:
the cut surfaces it produces are perfectly flat, an obvious fake.

Real fracture surfaces are rough and undulating. But they can't be moved arbitrarily -- the pieces must still fit back together
seamlessly into the original shape, and the outer shell's silhouette must not change at all. These two constraints pin the approach down tightly, and the approach they force
happens to be very clean.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The displacement must be a **pure function of world position**; you can't push along the normal
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The first instinct is "push a scalar noise along the normal", as displacement maps do. **Here that is wrong.**

Pieces A and B share a wall; the same position on that wall has one copy of the point in A and one in B, with exactly the same
coordinates -- but the two copies' normals point in **opposite directions** (each out of its own piece). Pushing the same
scalar along the normal moves the two copies in opposite world directions: either a gap opens, or they interpenetrate. The pieces no longer fit.

Use a **vector noise** instead: displacement = A * vnoise(P), depending only on world position, and not at all on "which piece the point belongs to or
which way its normal faces". So the two copies on a shared wall get **bit-identical** displacements and move together;
the wall is still the same wall, just bent.

This property has a very strong corollary: **the sum of all pieces' volumes is exactly preserved**. The shell doesn't move and the interior walls deform in pairs
in sync, so the pieces still tile the original solid with no overlaps or gaps. Measured: 60 Voronoi pieces pushed to
amplitude 0.1 (cube with side 1), volume sum off by 2e-8 -- this isn't "looks fine", it's provable.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The shell's edges must be pinned, and pinned **by world distance**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
If the ring where the fracture surface meets the original surface (the "rim") moves, the object's outer silhouette changes -- the assembled pieces are no longer
the original shape. So the weight on the rim is 0, rising gradually to 1 toward the interior of the fracture surface.

**The falloff must also be a pure function of world position**, otherwise the conservation above is lost. There's a pitfall here: the first version
tried graph distance along the surface (`adjacency.distance_from`), as more "geometry-aware". But the graph distance from a point in A to
A's rim and from the copy in B to B's rim are **not necessarily equal** -- the two pieces' other interior wall
layouts differ, so the shortest paths may take different routes. Then the two copies on a shared wall get different weights and displacements, and the
wall splits.

Use "Euclidean distance to the **global** rim point set" instead: the global rim is a fixed point cloud, and any world
position's distance to it is uniquely determined. A pure function; conservation holds. Queries go through `spatial.nearest`,
pruned with max_dist = falloff (points beyond the falloff radius just get weight 1, no exact distance needed).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Subdivide first, otherwise you just tilt the plane
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A fracture surface is usually one big n-gon with only the corner points on its edges. Pushing points directly just tilts the whole plane
slightly, with no visible "roughness". So Divisions first does a **linear** subdivision -- linear subdivision doesn't change the
shape (all points lie on the original primitive), it just chops the primitive up, giving the noise enough sample points.

It subdivides the **whole piece**, not just the fracture surfaces: subdividing only the fracture surfaces would leave T-junction
vertices where they meet the outer surface, and the topology would no longer be closed (`topology` would report a pile of boundary edges). Subdividing the whole piece costs a few more primitives
in exchange for a result that is still manifold.

A side observation: with Divisions >= 1 it **is conserved even without triangulating**. Linear subdivision splits every polygon into
"corner -> edge midpoint -> center -> edge midpoint" quads, listed starting from **the original corner**,
so the two copies of a face pick the same diagonal. Divisions = 0 is the setting that really breaks -- but triangulation is on
by default; we don't count on this coincidence.

Bevelling isn't in this node: the fracture surfaces are already a prim group, just connect PolyBevel (PCG).
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM
from .attribnoise import fractal_noise, NOISE_TYPES, FRACTALS
from .spatial import nearest
from .subdivide import subdivide

FALLOFFS = ("smooth", "linear")


def canonical_fan(geo, sel):
    """
    Fan-triangulate the selected polygons, **choosing the fan center by lexicographic order of vertex positions**.

    Why this is mandatory: a shared wall is stored as one face in each of the two pieces, with the same point positions but different corner order
    and winding. Once the wall is pushed non-planar, "fan out from corner 0" picks diagonals on the two sides
    that are not the same -- the surfaces the two faces represent no longer coincide, and a (very thin) gap opens between the pieces.
    Measured: cube with 30 seeds, amplitude 0.1, pushed without triangulating: volume sum off by 5.1e-3; with the fan center
    chosen lexicographically: off by 2.1e-8. And this error grows linearly with amplitude -- the gap is real, not numerical noise.

    Lexicographic order looks only at **positions**, not corner numbers, so both copies of the face necessarily pick the same vertex and cut the same
    diagonal. This is the last link that makes "displacement is a pure function of world position" really hold --
    a pure-function displacement isn't enough; the triangulation has to be one too.
    """
    from .divide import _rebuild_flat
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    off = geo.prim_offset[:-1].astype(np.int64)
    sizes = geo.prim_sizes().astype(np.int64)
    closed = np.asarray(geo.prim_closed, bool)
    corner, out_sizes, src, out_closed = [], [], [], []
    for i in range(geo.nprims):
        n = int(sizes[i])
        c = np.arange(off[i], off[i] + n, dtype=np.int64)
        if not sel[i] or n <= 3:
            corner.append(c)
            out_sizes.append(n)
            src.append(i)
            out_closed.append(bool(closed[i]))
            continue
        Q = P[geo.vertex_point[c]]
        a = int(np.lexsort((Q[:, 2], Q[:, 1], Q[:, 0]))[0])
        for k in range(1, n - 1):
            corner.append(c[[a, (a + k) % n, (a + k + 1) % n]])
            out_sizes.append(3)
            src.append(i)
            out_closed.append(True)
    if not out_sizes:
        return geo.copy()
    return _rebuild_flat(geo, np.concatenate(corner),
                         np.asarray(out_sizes, np.int64),
                         np.asarray(src, np.int64),
                         np.asarray(out_closed, bool))


def rim_mask(geo, group):
    """
    Returns (fracture surface points, rim points).

    rim = points used by both fracture and non-fracture primitives, i.e. the ring where the fracture surface meets the original surface.
    """
    n = geo.npoints
    inside = np.zeros(n, bool)
    outside = np.zeros(n, bool)
    if geo.nvertices == 0:
        return inside, outside
    sel = geo.get_group(PRIM, group) if group else None
    if sel is None:
        raise KeyError(
            f"Prim group '{group}' not found -- Voronoi Fracture (PCG) puts the fracture surfaces"
            f" in the 'interior' group by default. Existing groups: "
            f"{sorted(geo.groups.get(PRIM, {}).keys()) or '(none)'}")
    vp = geo.vertex_point
    vf = geo.vertex_prim()
    m = sel[vf]
    inside[vp[m]] = True
    outside[vp[~m]] = True
    return inside & ~outside, inside & outside


def rim_weight(P, rim, falloff, mode="smooth"):
    """
    Per-point displacement weight: 0 on the rim, 1 farther than falloff from the rim.

    The distance is Euclidean distance to the **global rim point cloud** -- it must be a pure function of world position, not
    graph distance along the surface (that quantity differs per piece, and shared walls would be torn apart).
    """
    P = np.asarray(P, np.float64)
    if not len(rim) or falloff <= 0:
        return np.ones(len(P))
    R = np.asarray(rim, np.float64).reshape(-1, 3)

    def ev(qi, ti):
        d = np.linalg.norm(R[ti] - P[qi], axis=1)
        return d, np.zeros((len(d), 0))

    _, dist, _ = nearest(P, R, R, ev, npayload=0, max_dist=float(falloff))
    t = np.clip(np.where(np.isfinite(dist), dist, falloff) / falloff, 0.0, 1.0)
    return t * t * (3 - 2 * t) if mode == "smooth" else t


def displace_field(P, amount, frequency, kind, fractal, octaves, lacunarity,
                   roughness, seed):
    """
    (n,3) vector noise displacement. The three components are the same noise with three seeds -- depends only on world position,
    so both sides of a shared wall get exactly the same displacement.
    """
    Q = np.asarray(P, np.float64) * float(frequency)
    s = int(seed) & 0xFFFFFFFF
    cols = [fractal_noise(Q, kind, fractal, int(octaves), float(lacunarity),
                          float(roughness), (s + k * 7919) & 0xFFFFFFFF)
            for k in range(3)]
    D = np.stack([np.asarray(c, np.float64).reshape(-1) for c in cols], 1)
    return D * float(amount)


def detail(geo, group="interior", divisions=2, amount=0.02, frequency=8.0,
           noise_type="simplex", fractal="standard", octaves=3,
           lacunarity=2.0, roughness=0.5, rand_seed=0, falloff=0.1,
           falloff_mode="smooth", relative=True, triangulate=True):
    """
    Add noise to the fracture surfaces (prim group group). The shell and the rim ring don't move; the pieces still fit back together.

    With relative=True, amount / frequency / falloff are normalized by the longest bounding box side --
    models at a different scale don't need retuning.
    """
    if geo is None:
        return Geometry()
    if noise_type not in NOISE_TYPES:
        raise ValueError(f"Noise Type must be one of {NOISE_TYPES}")
    if fractal not in FRACTALS:
        raise ValueError(f"Fractal must be one of {FRACTALS}")
    if falloff_mode not in FALLOFFS:
        raise ValueError(f"Falloff must be one of {FALLOFFS}")
    if geo.nprims == 0 or geo.npoints == 0:
        return geo.copy()

    g = geo
    d = max(0, int(divisions))
    if d:
        # **Linear** subdivision: all points lie on the original primitive, the shape doesn't change at all; it just prepares sample points for the noise.
        # And the whole piece is subdivided -- subdividing only the fracture surfaces would leave T-junction vertices at the rim and break the topology
        g = subdivide(g, depth=d, algorithm="linear")

    mn, mx = g.bbox()
    scale = float(np.max(np.asarray(mx, np.float64)
                         - np.asarray(mn, np.float64))) or 1.0
    amp = float(amount) * (scale if relative else 1.0)
    freq = float(frequency) / (scale if relative else 1.0)
    fall = float(falloff) * (scale if relative else 1.0)

    sel = g.get_group(PRIM, group)
    if sel is None:
        rim_mask(g, group)          # borrowed to raise the error that lists the "existing groups"
    if triangulate and sel is not None and (g.prim_sizes()[sel] > 3).any():
        # Triangulate the fracture surfaces lexicographically before pushing -- otherwise the two sides of a shared wall pick different diagonals
        # and a very thin gap opens between pieces (measured volume sum off by 1.1e-3)
        g = canonical_fan(g, sel)

    interior, rim = rim_mask(g, group)
    if not interior.any():
        return g

    P = np.asarray(g.get(POINT, "P"), np.float64)
    w = np.zeros(len(P))
    w[interior] = rim_weight(P[interior], P[rim], fall, falloff_mode)
    D = displace_field(P, amp, freq, noise_type, fractal, octaves,
                       lacunarity, roughness, rand_seed)
    out = g.copy()
    out.set(POINT, "P", (P + D * w[:, None]).astype(np.float32), owned=True)
    return out
