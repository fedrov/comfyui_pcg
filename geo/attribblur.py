"""
Attribute Blur -- spreads attributes along the topology.

Uses: feathering scatter density maps, soft transitions at mask edges, turning hard Connectivity blocks into soft
gradients, removing high frequencies from noise masks. **It is not a spatial blur, it propagates along edges** -- two
pieces of geometry, however close, don't affect each other unless connected, which is exactly what we want (masks on the two sides of a wall shouldn't bleed into each other).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Iterations + step size, not a "radius"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Each pass:  v += step * mask * (neighbour average - v)

This is explicit heat diffusion. step above 1 **diverges** (values oscillate with growing amplitude), so it is clamped to [0,1];
to blur further add iterations, not step size. The diffusion reach is roughly sqrt(iterations * step)
edge lengths -- which is also why there is no "radius" parameter: on a mesh with uneven edge lengths the same radius is
one step in sparse areas and ten steps in dense ones, so the number would lie.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Elements outside the group are **frozen but still take part in the average**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When blurring only a region, points on the boundary need to read values from outside it; otherwise the boundary is
"pinned" by its own values and a bright rim appears. So outside elements are read as usual, just never written. Same for Mask: where mask=0
nothing changes, but its value still bleeds into neighbours.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, is_string
from .groups import resolve
from .ops import match_names
from .topology import topology, point_neighbours

MODES = ("uniform", "edge_length")


def _point_csr(geo, mode):
    """(offsets, neighbours, weights)."""
    off, nb = point_neighbours(geo)
    if not len(nb):
        return off, nb, np.zeros(0)
    w = np.ones(len(nb))
    if mode == "edge_length":
        P = geo.get(POINT, "P")
        if P is not None:
            src = np.repeat(np.arange(geo.npoints), np.diff(off))
            d = np.linalg.norm(P[src].astype(np.float64)
                               - P[nb].astype(np.float64), axis=1)
            # Closer neighbours speak louder. On meshes with very uneven edge lengths, uniform weights let the long-edge side
            # drag everything along, so it looks as if the attribute flows towards the sparse side
            w = 1.0 / np.maximum(d, 1e-12)
    return off, nb, w


def _prim_csr(geo):
    """Primitive adjacency: two primitives sharing an edge."""
    t = topology(geo)
    if t.nedges == 0 or geo.nvertices == 0:
        return (np.zeros(geo.nprims + 1, np.int64), np.zeros(0, np.int64),
                np.zeros(0))
    vp = geo.vertex_prim().astype(np.int64)
    two = np.nonzero(t.edge_count == 2)[0]
    if not len(two):
        return (np.zeros(geo.nprims + 1, np.int64), np.zeros(0, np.int64),
                np.zeros(0))
    a = vp[t.edge_he[t.edge_he_off[two]]]
    b = vp[t.edge_he[t.edge_he_off[two] + 1]]
    keys = np.concatenate([a, b])
    vals = np.concatenate([b, a])
    order = np.argsort(keys, kind="stable")
    cnt = np.bincount(keys, minlength=geo.nprims)
    off = np.concatenate([[0], np.cumsum(cnt)]).astype(np.int64)
    return off, vals[order], np.ones(len(vals))


def blur(geo, names="Cd", cls=POINT, iterations=5, step=0.5, mode="uniform",
         mask_attrib="", invert_mask=False, group=""):
    """
    Diffuses attributes along the topology. names supports wildcards (`uv*`, `* ^P`).

    cls=point uses edge adjacency, cls=prim uses primitive adjacency via shared edges. String attributes are skipped.
    """
    if geo is None:
        return Geometry()
    if cls not in (POINT, PRIM):
        raise ValueError("Attribute Blur only supports point / prim -- "
                         "vertex and detail have no adjacency to diffuse along.")
    if mode not in MODES:
        raise ValueError(f"Mode must be one of {MODES}")
    picked = [n for n in match_names(list(geo.attribs[cls].keys()), names)
              if not is_string(geo.attribs[cls][n])]
    if not picked:
        have = sorted(geo.attribs[cls].keys())
        raise KeyError(f"{cls} has no numeric attribute matching '{names}'. "
                       f"Existing: {have or '(none)'}")
    it = max(0, int(iterations))
    st = float(np.clip(step, 0.0, 1.0))
    if it == 0 or st <= 0:
        return geo.copy()

    off, nb, w = (_point_csr(geo, mode) if cls == POINT else _prim_csr(geo))
    n = geo.count(cls)
    if not len(nb):
        return geo.copy()
    src = np.repeat(np.arange(n, dtype=np.int64), np.diff(off))
    wsum = np.bincount(src, weights=w, minlength=n)
    inv = 1.0 / np.where(wsum <= 0, 1.0, wsum)
    has_nb = wsum > 0

    amt = np.full(n, st)
    if str(mask_attrib).strip():
        mn = str(mask_attrib).strip()
        a = geo.get(cls, mn)
        if a is None:
            have = sorted(geo.attribs[cls].keys())
            raise KeyError(f"{cls} has no mask attribute '{mn}'. Existing: {have or '(none)'}")
        m = np.clip(a[:, 0].astype(np.float64), 0.0, 1.0)
        amt = amt * (1.0 - m if invert_mask else m)
    amt = np.where(resolve(geo, cls, group) & has_nb, amt, 0.0)[:, None]

    g = geo.copy()
    for nm in picked:
        a = geo.attribs[cls][nm]
        v = a.astype(np.float64)
        C = v.shape[1]
        for _ in range(it):
            avg = np.stack([np.bincount(src, weights=w * v[nb, c],
                                        minlength=n) * inv
                            for c in range(C)], 1)
            v = v + amt * (avg - v)
        g.set(cls, nm, (np.rint(v) if a.dtype.kind in "iub" else v
                        ).astype(a.dtype), owned=True)
    return g
