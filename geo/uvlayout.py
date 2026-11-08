"""
UV Layout / UV Transform -- find UV islands, lay them out into 0-1, and transform in UV space.

Mirrors Houdini's UV Layout and UV Transform. Projected UVs are usually several overlapping islands or
islands scattered outside the range; they must be packed before they are really usable for baking.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"UV islands" must be split by **UV connectivity**, not by geometric connectivity
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Two faces sharing an edge geometrically does not mean they are connected in UV space -- the definition of a seam is "connected
geometrically but split in UV". So the criterion is: **do the uv values of the two corners on the shared edge match**. Only if they match
are they the same island.

That is also why a box projection naturally yields 6 islands: adjacent faces of a cube choose different axes by normal,
so the uvs on either side of the shared edge are completely different.

Splitting islands by geometric connectivity is a very common mistake, the symptom being "after packing a six-sided projection it is still one blob": the six faces are
geometrically connected and get moved away as one island.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Packing uses **shelves + an outer bisection on scale**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Optimal rectangle packing is NP-hard. The practical approach is the decision problem "given a scale, does it fit",
wrapped in a bisection to find the largest feasible scale:

    1. compute each island's bounding box (optionally rotating to its minimum-area orientation first)
    2. sort by height, descending -- tall ones go first, so shelf heights are not wasted by short pieces later
    3. fill a row (shelf) from left to right, start a new row when it does not fit
    4. total height over 1 means this scale does not fit

A few dozen bisection rounds reach floating-point precision, and each round is just one O(n) shelf fill. **This is more robust than "guess a scale
and pray"**, and "the largest scale that fits" is exactly the desired answer: maximum texel density.

Pitfall noted here: bisection needs a **[feasible, infeasible]** pair of bounds. The first version only probed downward until feasible and
started bisecting right away, so the upper bound itself was feasible and it always converged to that upper bound -- 6 squares used only
0.79 x 0.52 of the image. You must first go down to feasible, then double upward to find the infeasible end.

Scale Mode:
    uniform     all islands share one scale -- relative sizes unchanged, consistent texel density, which is what baking wants
    individual  first normalize every island to the same **area**, then pack them together -- small islands get as much
                image space as large ones (density no longer consistent, but small islands do not blur). Normalizing by the long edge is not
                enough: a 4x1 strip and a 1x1 square both normalized to long edge 1 still differ 4x in area

Method = raster (pcg84): the shelf approach above only looks at bounding boxes, and triangular or L-shaped islands waste half of their
bounding box -- a decimated rock measured using only 40% of the image. raster rasterizes each island (with Padding) into
a mask, and on an occupancy grid finds the first non-overlapping position by "lowest top edge, then leftmost", trying all four 90° orientations;
the non-overlap test is the cross-correlation of the occupancy map and the mask (FFT, all positions computed at once). Islands can interlock
with each other, the same rock reaching over 60%. Scale is still bisected for the largest fit. Rasterization is **conservative**
(triangle interiors + sampling along edges + dilated by one ring), so quantization can only leave a bit more space between islands, never overlap them.

Minimum-area orientation uses **rotating calipers**: the minimum-area bounding rectangle always has one side flush with some edge of the convex hull, so
trying each hull edge suffices, no need to sweep 180 degrees. An unrotated thin diagonal strip has a big square bounding box;
straightened it saves more than half the space.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM
from .groups import resolve
from .topology import topology

SCALE_MODES = ("uniform", "individual", "fixed")
PACK_METHODS = ("shelf", "raster")
# pcg100: Houdini's Island Rotation Step. auto = the original behaviour (shelf does not rotate, raster tries 4 x 90°)
ROTATIONS = ("auto", "none", "step", "custom")
# pcg100: Houdini's Pack into (Rectangles only implements the default unit square; Islands from second input is not implemented)
PACK_INTO = ("unit_square", "udim_tiles")
CLASSES = (VERTEX, POINT)


def _get_uv(geo, name, cls):
    a = geo.get(cls, name)
    if a is None:
        have = sorted(geo.attribs[cls].keys())
        raise KeyError(f"No {cls} UV attribute '{name}'. Existing: {have or '(none)'}"
                       f"\n  Connect a UV Project (PCG) first.")
    if a.shape[1] < 2:
        raise ValueError(f"'{name}' has only {a.shape[1]} components, it is not a UV.")
    return a.astype(np.float64)[:, :2]


def islands(geo, name="uv", tol=1e-6):
    """
    (nprims,) island numbers. The criterion is **whether the uvs on the two sides of a shared edge match**, not geometric connectivity.

    When uv is a point attribute a point has only one value, so seams cannot be expressed at all -- in that case islands
    degrade to geometric connected pieces, and that is returned honestly, without pretending.
    """
    n = geo.nprims
    if n == 0 or geo.nvertices == 0:
        return np.zeros(n, np.int64)
    t = topology(geo)
    lab = np.arange(n, dtype=np.int64)
    two = np.nonzero(t.edge_count == 2)[0]
    if not len(two):
        return lab
    vprim = geo.vertex_prim().astype(np.int64)
    h1 = t.edge_he[t.edge_he_off[two]].astype(np.int64)
    h2 = t.edge_he[t.edge_he_off[two] + 1].astype(np.int64)

    same = _uv_same(geo, name, h1, h2, tol)

    a, b = vprim[h1][same], vprim[h2][same]
    for _ in range(64):
        prev = lab
        m = np.minimum(lab[a], lab[b])
        lab = lab.copy()
        np.minimum.at(lab, a, m)
        np.minimum.at(lab, b, m)
        lab = lab[lab]
        if np.array_equal(lab, prev):
            break
    _, inv = np.unique(lab, return_inverse=True)
    return inv.reshape(-1).astype(np.int64)


def _uv_same(geo, name, h1, h2, tol):
    """
    (len(h1),) bool: whether the uvs on both sides of the edge of half-edge pair (h1, h2) match.

    When uv is not a vertex attribute (point / none) it always counts as "matching" -- a point attribute has only one value per point
    and cannot express seams.
    """
    uvv = geo.get(VERTEX, name)
    if uvv is not None and uvv.shape[1] >= 2:
        uv = uvv.astype(np.float64)[:, :2]
        vp = geo.vertex_point
        nxt = geo.next_corner().astype(np.int64)
        # the two end corners of half-edge h are h and nxt[h]; the opposite edge h2 runs the other way, so compare crosswise
        same = (_close(uv[h1], uv[nxt[h2]], tol)
                & _close(uv[nxt[h1]], uv[h2], tol))
        # some meshes have two half-edges in the same direction (inconsistent normals); compare once more in the same order
        same |= (_close(uv[h1], uv[h2], tol)
                 & _close(uv[nxt[h1]], uv[nxt[h2]], tol))
        # the endpoints must really be the same geometric point, otherwise the uvs just happen to be equal
        same &= (vp[h1] == vp[nxt[h2]]) | (vp[h1] == vp[h2])
    else:
        same = np.ones(len(h1), bool)      # point uv: cannot express seams, degrades to geometric connectivity
    return same


def uv_seam_edges(geo, name="uv", tol=1e-6):
    """
    (nedges,) bool: **existing** UV seams -- edges connected geometrically (shared by exactly two faces) whose uvs on the two sides do not match.

    Used by UV Flatten's Preserve Seams and UV Autoseam's Splitting = Existing Islands.
    Same criterion as islands() (the same _uv_same), so the islands both produce are guaranteed consistent.
    Boundary and non-manifold edges do not count: they are already boundaries of the unwrap and need no further "cutting".
    """
    t = topology(geo)
    out = np.zeros(t.nedges, bool)
    two = np.nonzero(t.edge_count == 2)[0]
    if not len(two) or geo.nvertices == 0:
        return out
    h1 = t.edge_he[t.edge_he_off[two]].astype(np.int64)
    h2 = t.edge_he[t.edge_he_off[two] + 1].astype(np.int64)
    out[two] = ~_uv_same(geo, name, h1, h2, tol)
    return out


def _close(x, y, tol):
    return (np.abs(x - y) <= tol).all(1)


def _hull(pts):
    """2D convex hull (Andrew monotone chain). Returns the vertices counter-clockwise."""
    p = np.unique(np.round(pts, 12), axis=0)
    if len(p) < 3:
        return p
    p = p[np.lexsort((p[:, 1], p[:, 0]))]

    def half(seq):
        out = []
        for q in seq:
            while len(out) >= 2:
                a, b = out[-2], out[-1]
                if (b[0] - a[0]) * (q[1] - a[1]) \
                        - (b[1] - a[1]) * (q[0] - a[0]) > 1e-15:
                    break
                out.pop()
            out.append(q)
        return out
    return np.array(half(p)[:-1] + half(p[::-1])[:-1])


def best_angle(pts):
    """
    Orientation (radians) of the minimum-area bounding rectangle. Rotating calipers: the minimum-area rectangle always has one side flush with
    some hull edge, so trying only the hull edges suffices, no need to sweep 180 degrees.
    """
    h = _hull(np.asarray(pts, np.float64))
    if len(h) < 3:
        return 0.0
    e = np.roll(h, -1, axis=0) - h
    ang = np.arctan2(e[:, 1], e[:, 0])
    best, ba = np.inf, 0.0
    for a in ang:
        # try "rotating this hull edge flat" -- i.e. rotating everything by -a
        c, s = np.cos(-a), np.sin(-a)
        x = h[:, 0] * c - h[:, 1] * s
        y = h[:, 0] * s + h[:, 1] * c
        area = (x.max() - x.min()) * (y.max() - y.min())
        if area < best:
            best, ba = area, float(a)
    # What is returned is "the angle to be rotated flat"; callers always rotate with cos(-a)/sin(-a).
    # There used to be an extra negation here -- the result rotated the wrong way, and on symmetric shapes it **still made the
    # bounding box smaller**, so the tests still passed. What really caught it was a unit test with a rectangle at a known angle
    return ba


def _shelf(sizes, limit, padding):
    """
    Shelf packing: tall ones first, fill a row from left to right, start a new row when it does not fit.

    Returns (lower-left corner of each piece, total height, width of the widest row). **Both dimensions must be checked** --
    looking only at height, a piece wider than limit still gets placed because of the "no line break at row start" rule,
    the height comes out perfectly acceptable, and bisection pushes the scale to absurd values (measured: a 1:8 strip
    blown up to 8x the width). Not breaking at row start is itself right, otherwise an over-wide piece loops forever.
    """
    order = np.argsort(-sizes[:, 1], kind="stable")
    pos = np.zeros_like(sizes)
    x = y = row_h = 0.0
    wide = 0.0
    for i in order:
        w, h = sizes[i]
        if x > 0.0 and x + w + padding > limit:
            wide = max(wide, x - padding)
            x = 0.0
            y += row_h + padding
            row_h = 0.0
        pos[i] = (x, y)
        x += w + padding
        row_h = max(row_h, h)
    return pos, y + row_h, max(wide, x - padding if x > 0 else 0.0)


def _angles(rotation, method, step, divisions):
    """Island Rotation Step -> angles to try (degrees)."""
    if rotation == "auto":
        # the original raster tries 4 x 90°; shelf only looks at bounding boxes, rotating by 90° keeps the bounding-box area the same and _best_rot breaks the tie by taking
        # the first (0°), so shelf also gets 4 -- with the same result as "no rotation"
        return [0.0, 90.0, 180.0, 270.0]
    if rotation == "none":
        return [0.0]
    if rotation == "step":
        st = float(np.clip(abs(float(step)), 1.0, 360.0))
        return [float(a) for a in np.arange(0.0, 360.0 - 1e-9, st)]
    n = int(np.clip(int(divisions), 1, 360))
    return [360.0 * k / n for k in range(n)]


def _rot_any(q, ang):
    """
    Rotate local coordinates (lower-left at the origin) by ang degrees, keeping the lower-left at the origin afterwards. Integer multiples of 90° go through _rot90
    (exact, bitwise identical to the original raster), other angles through a general rotation.
    """
    a = float(ang) % 360.0
    if abs(a - 90.0 * round(a / 90.0)) < 1e-9:
        return _rot90(q, int(round(a / 90.0)) % 4)
    q = np.asarray(q, np.float64)
    c, s = np.cos(np.radians(a)), np.sin(np.radians(a))
    r = np.stack([q[:, 0] * c - q[:, 1] * s, q[:, 0] * s + q[:, 1] * c], 1)
    return r - r.min(0)


def _udim_offset(num, columns):
    """UDIM number -> (u, v) of the lower-left corner of that tile. 1001 + u + columns·v."""
    k = int(num) - 1001
    c = max(int(columns), 1)
    return np.array([float(k % c), float(k // c)])


def layout(geo, name="uv", cls=VERTEX, scale_mode="uniform", padding=0.01,
           rotate_to_fit=True, group="", method="shelf", resolution=256,
           rotation="auto", step_angle=90.0, divisions=4, fixed_scale=1.0,
           match_area=False, pack_into="unit_square", udim_start=1001,
           udim_columns=10, udim_count=1, nonpacked_group="", island_attrib="",
           target_attrib=""):
    """
    Find UV islands and lay them out into [0,1]².

    With scale_mode=uniform all islands share one scale (consistent texel density, which is what baking wants),
    found by bisecting for "the largest scale that fits".

    Added in pcg100 (Houdini UV Layout 3.0):
      scale_mode=fixed    all islands scaled by Fixed Scale, no search for a maximum; islands that do not fit are placed outside the target area
                          (in a row below it), recorded in the Nonpacked Polygons group
      rotation            Island Rotation Step: none / step (one notch every Step degrees) / custom (360° split into N)
      match_area          Scale Islands to Match Their Surface Areas: first scale each island's uv area to be
                          proportional to its 3D area
      pack_into           unit_square (the original) / udim_tiles (Count tiles starting at Starting UDIM, Columns per row)
      island_attrib / target_attrib / nonpacked_group   outputs
    """
    if geo is None:
        return Geometry()
    if cls not in CLASSES:
        raise ValueError(f"Class must be one of {CLASSES}")
    if scale_mode not in SCALE_MODES:
        raise ValueError(f"Scale Mode must be one of {SCALE_MODES}")
    if method not in PACK_METHODS:
        raise ValueError(f"Method must be one of {PACK_METHODS}")
    if rotation not in ROTATIONS:
        raise ValueError(f"Island Rotation Step must be one of {ROTATIONS}")
    if pack_into not in PACK_INTO:
        raise ValueError(f"Pack Into must be one of {PACK_INTO}")
    if geo.nprims == 0 or geo.nvertices == 0:
        return geo.copy()
    uv = _get_uv(geo, name, cls)
    pad = float(np.clip(padding, 0.0, 0.25))

    isl = islands(geo, name)
    sel_p = resolve(geo, PRIM, group)
    keep = np.unique(isl[sel_p]) if not sel_p.all() else np.unique(isl)
    if not len(keep):
        return geo.copy()

    # element indices of each island: vertex attributes split directly by corner, point attributes by the points on the faces
    sizes_p = geo.prim_sizes()
    if cls == VERTEX:
        owner = np.repeat(isl, sizes_p)
        idx_all = np.arange(geo.nvertices)
    else:
        owner = np.full(geo.npoints, -1, np.int64)
        owner[geo.vertex_point] = np.repeat(isl, sizes_p)
        idx_all = np.arange(geo.npoints)

    fac = _area_match(geo, uv, cls, isl) if match_area else None
    boxes, locals_, angles = [], [], []
    kept = []
    for k in keep:
        idx = idx_all[owner == k]
        if not len(idx):
            continue
        pts = uv[idx]
        a = best_angle(pts) if rotate_to_fit else 0.0
        c, s = np.cos(-a), np.sin(-a)
        r = np.stack([pts[:, 0] * c - pts[:, 1] * s,
                      pts[:, 0] * s + pts[:, 1] * c], 1)
        if fac is not None:
            r = r * fac[k]
        lo = r.min(0)
        boxes.append(r.max(0) - lo)
        locals_.append((idx, r - lo))
        angles.append(a)
        kept.append(k)
    if not boxes:
        return geo.copy()
    boxes = np.asarray(boxes)
    boxes = np.maximum(boxes, 1e-9)

    # individual: first normalize every island to **the same area**, then pack together -- small islands get as much
    # image space as large ones (texel density no longer consistent, but small islands do not blur).
    # Normalizing by "long edge" is not enough: a 4x1 strip and a 1x1 square, both normalized to long edge 1,
    # still differ 4x in area, so nothing is evened out
    pre = (1.0 / np.sqrt(np.maximum(boxes.prod(1, keepdims=True), 1e-24))
           if scale_mode == "individual" else np.ones((len(boxes), 1)))
    sized = boxes * pre
    out = uv.copy()
    legacy = (rotation == "auto" and pack_into == "unit_square"
              and scale_mode != "fixed")
    tile_of = np.zeros(len(locals_), np.int64)          # tile index; -1 = not placed
    if legacy and method == "raster":
        tris = _island_tris(geo, isl, keep, cls, locals_)
        place = _raster_layout([(loc * k, t) for (idx, loc), k, t
                                in zip(locals_, pre[:, 0], tris)],
                               pad, int(resolution))
        for (idx, loc), k, (off, rot, sc, _) in zip(locals_, pre[:, 0], place):
            q = _rot_any(loc * k, rot) * sc
            out[idx] = off + q
    elif legacy:
        s = _fit_scale(sized, pad)
        pos, _, _ = _shelf(sized * s, 1.0, pad)
        for (idx, loc), p, k in zip(locals_, pos, pre[:, 0]):
            out[idx] = p + loc * (k * s)
    else:
        angs = _angles(rotation, method, step_angle, divisions)
        fixed = scale_mode == "fixed"
        if pack_into == "udim_tiles":
            # Fixed + UDIM: docs "fill as many tiles as needed to hold the scaled islands" -- the number of tiles is unlimited, opened on demand
            ntiles = None if fixed else max(int(udim_count), 1)
        else:
            ntiles = 1
        locs = [loc * k for (idx, loc), k in zip(locals_, pre[:, 0])]
        if method == "raster":
            tris = _island_tris(geo, isl, keep, cls, locals_)
            place = _raster_layout([(lc, t) for lc, t in zip(locs, tris)], pad,
                                   int(resolution), angles=angs, ntiles=ntiles,
                                   fixed=float(fixed_scale) if fixed else None,
                                   ext_by_angle=True)
        else:
            place = _shelf_layout(locs, pad, angs, ntiles,
                                  float(fixed_scale) if fixed else None)
        miss = []
        for i, ((idx, _), lc, pl) in enumerate(zip(locals_, locs, place)):
            if pl is None:
                miss.append(i)
                tile_of[i] = -1
                continue
            off, rot, sc, tile = pl
            tile_of[i] = tile
            base = (_udim_offset(int(udim_start) + tile, udim_columns)
                    if pack_into == "udim_tiles" else np.zeros(2))
            out[idx] = base + off + _rot_any(lc, rot) * sc
        if miss:
            # islands that do not fit: laid out at Fixed Scale as is in a row **below** the target area (Houdini: placed outside the target
            # bounding box; the docs do not say exactly where)
            sc = float(fixed_scale)
            x = 0.0
            base = (_udim_offset(int(udim_start), udim_columns)
                    if pack_into == "udim_tiles" else np.zeros(2))
            for i in miss:
                idx = locals_[i][0]
                q = locs[i] * sc
                ext = q.max(0)
                out[idx] = base + np.array([x, -pad - ext[1]]) + q
                x += ext[0] + pad

    g = geo.copy()
    a = geo.get(cls, name)
    col = np.array(a, np.float64)
    col[:, :2] = out
    g.set(cls, name, col.astype(a.dtype), owned=True)

    if str(island_attrib).strip():
        g.set(PRIM, str(island_attrib).strip(), isl.astype(np.int32)[:, None], owned=True)
    if str(target_attrib).strip() or str(nonpacked_group).strip():
        # which tile each face lands in: UDIM number (udim_tiles) / 0 (unit square); not placed or not in Group = -1
        tgt = np.full(geo.nprims, -1, np.int64)
        for k, tl in zip(kept, tile_of):
            if tl >= 0:
                tgt[isl == k] = (int(udim_start) + int(tl)
                                 if pack_into == "udim_tiles" else 0)
        if str(target_attrib).strip():
            g.set(PRIM, str(target_attrib).strip(), tgt.astype(np.int32)[:, None], owned=True)
        if str(nonpacked_group).strip():
            miss_k = [k for k, tl in zip(kept, tile_of) if tl < 0]
            g.set_group(PRIM, str(nonpacked_group).strip(), np.isin(isl, miss_k))
    return g


def _area_match(geo, uv, cls, isl):
    """
    Per-island scale factor √(3D area / uv area) -- after scaling, uv area and 3D area are in the same ratio.
    Houdini's Scale Islands to Match Their Surface Areas. Islands with zero uv area get factor 1.
    """
    from .measure import prim_areas
    sizes = geo.prim_sizes()
    src = np.repeat(np.arange(geo.nprims), sizes)
    q = uv if cls == VERTEX else uv[geo.vertex_point]
    nx = geo.next_corner().astype(np.int64)
    cr = q[:, 0] * q[nx, 1] - q[nx, 0] * q[:, 1]
    a2p = 0.5 * np.abs(np.bincount(src, weights=cr, minlength=geo.nprims))
    a3p = np.asarray(prim_areas(geo), np.float64)
    n = int(isl.max()) + 1
    a2 = np.bincount(isl, weights=a2p, minlength=n)
    a3 = np.bincount(isl, weights=a3p, minlength=n)
    return np.where(a2 > 1e-30, np.sqrt(a3 / np.maximum(a2, 1e-30)), 1.0)


def _best_rot(lc, angs):
    """Shelf only looks at bounding boxes: among the angles to try pick the smallest bounding-box area (ties go to the first)."""
    best, ba = np.inf, 0.0
    for a in angs:
        q = _rot_any(lc, a)
        e = q.max(0)
        ar = float(e[0] * e[1])
        if ar < best - 1e-12:
            best, ba = ar, a
    return ba


def _shelf_bins(sizes, pad, ntiles):
    """
    Multi-tile shelves: tall ones first, start a new row when one does not fit, move to the next tile when a tile is not tall enough.
    Returns (lower-left corners, tile index; -1 = does not fit). With ntiles=None the number of tiles is unlimited.
    One rule more than the single-tile _shelf: each piece must fit inside a tile (width and height both <= 1); those that do not are flagged separately,
    since Fixed Scale needs to know which islands were not placed.
    """
    order = np.argsort(-sizes[:, 1], kind="stable")
    pos = np.zeros_like(sizes)
    tile = np.full(len(sizes), -1, np.int64)
    b, x, y, row_h = 0, 0.0, 0.0, 0.0
    for i in order:
        w, h = sizes[i]
        if w > 1.0 + 1e-12 or h > 1.0 + 1e-12:
            continue
        if x > 0.0 and x + w > 1.0 + 1e-12:
            x, y, row_h = 0.0, y + row_h + pad, 0.0
        if y + h > 1.0 + 1e-12:
            b, x, y, row_h = b + 1, 0.0, 0.0, 0.0
        if ntiles is not None and b >= ntiles:
            continue
        pos[i] = (x, y)
        tile[i] = b
        x += w + pad
        row_h = max(row_h, h)
    return pos, tile


def _shelf_layout(locs, pad, angs, ntiles, fixed):
    """
    General version of shelf packing (used for UDIM / Fixed / Rotation Step). Each island first picks the orientation with the smallest bounding box among angs;
    with fixed=None bisect for the largest scale at which all fit, otherwise place at fixed and return None for those that do not fit.
    Returns (lower-left offset, angle, scale, tile) or None per island.
    """
    rots = [_best_rot(lc, angs) for lc in locs]
    sizes = np.maximum(np.array([_rot_any(lc, a).max(0) for lc, a in zip(locs, rots)]), 1e-9)
    if fixed is None:
        def fits(s):
            return bool((_shelf_bins(sizes * s, pad, ntiles)[1] >= 0).all())
        s = 1.0 / max(float(sizes.max()), 1e-12)
        for _ in range(80):
            if fits(s):
                break
            s *= 0.5
        else:
            return [None] * len(locs)
        lo, hi = s, s * 2.0
        for _ in range(80):
            if not fits(hi):
                break
            lo, hi = hi, hi * 2.0
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            if fits(mid):
                lo = mid
            else:
                hi = mid
        s = lo
    else:
        s = float(fixed)
    pos, tile = _shelf_bins(sizes * s, pad, ntiles)
    return [(pos[i], rots[i], s, int(tile[i])) if tile[i] >= 0 else None
            for i in range(len(locs))]


def _island_tris(geo, isl, keep, cls, locals_):
    """Triangles of each island, expressed as local-coordinate indices into locals_ (t, 3)."""
    nv = geo.nvertices
    vpos = np.full(nv if cls == VERTEX else geo.npoints, -1, np.int64)
    out = []
    po = geo.prim_offset
    sizes = geo.prim_sizes()
    for (idx, _), k in zip(locals_, keep):
        vpos[idx] = np.arange(len(idx))
        tl = []
        for f in np.nonzero(isl == k)[0]:
            if sizes[f] < 3:
                continue
            c = np.arange(po[f], po[f + 1])
            if cls == POINT:
                c = geo.vertex_point[c]
            li = vpos[c]
            for j in range(1, len(li) - 1):
                tl.append((li[0], li[j], li[j + 1]))
        out.append(np.asarray(tl, np.int64).reshape(-1, 3))
        vpos[idx] = -1
    return out


def _rot90(q, r):
    """Rotate local coordinates (lower-left at the origin) by r x 90°, keeping the lower-left at the origin afterwards."""
    q = np.asarray(q, np.float64)
    for _ in range(r % 4):
        q = np.stack([-q[:, 1], q[:, 0]], 1)
        q = q - q.min(0)
    return q


def _island_samples(loc, tris, step):
    """
    Conservative sample points of an island (local coordinates): lattice points at spacing step inside triangles + one every step/2 along edges + the vertices.
    Computed only once; changing scale or orientation just multiplies and rotates these points before binning, no re-rasterization.
    """
    out = [loc]
    for a, b in ((0, 1), (1, 2), (2, 0)):
        A, B = loc[tris[:, a]], loc[tris[:, b]]
        L = np.linalg.norm(B - A, axis=1)
        n = np.maximum(np.ceil(L / step * 2).astype(np.int64), 1)
        for t in np.unique(n):
            sel = n == t
            u = np.linspace(0.0, 1.0, int(t) + 1)
            out.append((A[sel][:, None] + (B[sel] - A[sel])[:, None]
                        * u[None, :, None]).reshape(-1, 2))
    for t in tris:
        a, b, c = loc[t]
        lo = np.minimum(np.minimum(a, b), c)
        hi = np.maximum(np.maximum(a, b), c)
        xs = np.arange(lo[0], hi[0] + step, step)
        ys = np.arange(lo[1], hi[1] + step, step)
        if len(xs) * len(ys) <= 4:
            continue
        X, Y = np.meshgrid(xs, ys)
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-18:
            continue
        l1 = ((b[1] - c[1]) * (X - c[0]) + (c[0] - b[0]) * (Y - c[1])) / d
        l2 = ((c[1] - a[1]) * (X - c[0]) + (a[0] - c[0]) * (Y - c[1])) / d
        ins = (l1 >= 0) & (l2 >= 0) & (l1 + l2 <= 1)
        out.append(np.stack([X[ins], Y[ins]], 1))
    return np.concatenate(out)


def _mask_from_samples(q, dil):
    """Sample points (already converted to pixel coordinates) -> mask, dilated by dil pixels (disk)."""
    ij = np.floor(q).astype(np.int64)
    ij -= ij.min(0)
    W, H = int(ij[:, 0].max()) + 1, int(ij[:, 1].max()) + 1
    m = np.zeros((H, W), bool)
    m[ij[:, 1], ij[:, 0]] = True
    k = int(dil)
    if k > 0:
        m = np.pad(m, k)
        out = m.copy()
        for dy in range(-k, k + 1):
            for dx in range(-k, k + 1):
                if 0 < dx * dx + dy * dy <= k * k:
                    out |= np.roll(np.roll(m, dy, 0), dx, 1)
        m = out
    return m


def _raster_try(isls, samples, scale, G, dil, angles=(0.0, 90.0, 180.0, 270.0),
                ntiles=1, skip=False):
    """
    Lay out once on the GxG occupancy grid at the given scale; returns None if it does not fit.

    pcg100: angles = orientations to try (degrees; originally fixed at 4 x 90°); ntiles = number of tiles (None = unlimited,
    open a new one when it does not fit); with skip=True islands that do not fit are recorded as None and the rest continue (used by Fixed Scale),
    otherwise the whole call returns None. Returns (offset, angle, scale, tile) per island.
    """
    occs = [np.zeros((G, G), np.float64)]
    S = (2 * G + 4 * dil, 2 * G + 4 * dil)
    order = sorted(range(len(isls)),
                   key=lambda i: -float(np.ptp(isls[i][0][:, 0]) * np.ptp(isls[i][0][:, 1])))
    place = [None] * len(isls)
    for i in order:
        best = None
        tile = 0
        while True:
            if tile >= len(occs):        # only reached with ntiles=None (the break below enforces the limit)
                occs.append(np.zeros((G, G), np.float64))
            best = _raster_best(occs[tile], samples[i], scale, G, dil, S, angles)
            if best is not None:
                break
            if ntiles is None and not occs[tile].any():
                break                    # it does not even fit on an empty tile: opening new ones will not help (also the loop's termination condition)
            tile += 1
            if ntiles is not None and tile >= ntiles:
                break
        if best is None:
            if skip:
                continue
            return None
        _, r, y, x, m = best
        occ = occs[tile]
        h, w = m.shape
        y0, x0 = max(y, 0), max(x, 0)
        y1, x1 = min(y + h, G), min(x + w, G)
        occ[y0:y1, x0:x1] += m[y0 - y:y1 - y, x0 - x:x1 - x]
        # mask origin: the minimum sample point lands on pixel number dil (the dilated ring comes before it)
        q = _rot_any(samples[i], r) * (scale * G)
        base = np.floor(q).min(0)
        place[i] = (np.array([x + dil - base[0], y + dil - base[1]]) / G, r, scale, tile)
    return place


def _raster_best(occ, sample, scale, G, dil, S, angles):
    """On one tile, across all orientations to try, the non-overlapping position with "lowest top edge, then leftmost"."""
    F = np.fft.rfft2(occ, s=S)
    best = None
    for r in angles:
        q = _rot_any(sample, r) * (scale * G)
        m = _mask_from_samples(q, dil)
        h, w = m.shape
        if h > G + 2 * dil or w > G + 2 * dil:
            continue
        K = np.fft.rfft2(m[::-1, ::-1].astype(np.float64), s=S)
        corr = np.fft.irfft2(F * K, s=S)
        # overlap when the mask's lower-left is placed at (y, x) = corr[y + h - 1, x + w - 1];
        # the dilated ring may stick out of the image (y, x can go down to -dil), the island body may not
        ys = np.arange(-dil, G - h + dil + 1)
        xs = np.arange(-dil, G - w + dil + 1)
        if not len(ys) or not len(xs):
            continue
        sub = corr[(ys + h - 1) % S[0]][:, (xs + w - 1) % S[1]]
        free = sub < 0.5
        if not free.any():
            continue
        fy, fx = np.nonzero(free)
        score = (ys[fy] + h) * (G + 1) + xs[fx]
        j = int(np.argmin(score))
        cand = (float(score[j]), r, int(ys[fy[j]]), int(xs[fx[j]]), m)
        if best is None or cand[0] < best[0]:
            best = cand
    return best


def _raster_layout(isls, pad, G, angles=(0.0, 90.0, 180.0, 270.0), ntiles=1,
                   fixed=None, ext_by_angle=False):
    """
    Raster packing: bisect on scale (upper bound = total area completely filled), trying a layout each time.
    Returns (lower-left offset, angle, scale, tile) per island. When fixed is given, lay out once at that scale only; islands that do not fit are None.

    ext_by_angle: the "longest edge" in the scale upper bound is computed for the **most favourable orientation** (under Rotation Step a strip placed diagonally can be
    larger than placed horizontally). The original callers do not pass it -- the longest edge is the same for all 4 x 90° orientations, results unchanged bit for bit.
    """
    G = int(np.clip(G, 32, 2048))
    dil = max(1, int(np.ceil(pad * G)))
    area = 0.0
    for loc, tris in isls:
        if len(tris):
            a, b, c = loc[tris[:, 0]], loc[tris[:, 1]], loc[tris[:, 2]]
            area += 0.5 * float(np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
                                       - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])).sum())
    if ext_by_angle:
        ext = max(float(max(min(np.ptp(_rot_any(l, a), axis=0).max() for a in angles)
                            for l, _ in isls)), 1e-12)
    else:
        ext = max(float(max(np.ptp(l, axis=0).max() for l, _ in isls)), 1e-12)
    if fixed is not None:
        step = 0.5 / (float(fixed) * G)
        samples = [_island_samples(loc, tris, step) for loc, tris in isls]
        return _raster_try(isls, samples, float(fixed), G, dil, angles, ntiles, skip=True)
    # with multiple tiles the total area is split across the tiles
    nt = 1 if ntiles is None else max(int(ntiles), 1)
    hi = min(1.0 / np.sqrt(max(area / nt, 1e-24)), (1.0 - 2 * pad) / ext) * 1.001
    # sample spacing = half a pixel at the maximum scale: scale only gets smaller, binning only denser, nothing missed
    step = 0.5 / (hi * G)
    samples = [_island_samples(loc, tris, step) for loc, tris in isls]
    lo = hi
    best = None
    for _ in range(40):                 # first go down until it fits
        best = _raster_try(isls, samples, lo, G, dil, angles, ntiles)
        if best is not None:
            break
        hi = lo
        lo *= 0.9
    if best is None:
        raise RuntimeError("UV packing failed: too many islands / Pack Resolution too low")
    if lo == hi:
        return best
    for _ in range(5):                  # then bisect a few rounds between [feasible, infeasible]
        mid = 0.5 * (lo + hi)
        p = _raster_try(isls, samples, mid, G, dil, angles, ntiles)
        if p is None:
            hi = mid
        else:
            lo, best = mid, p
    return best


def _fit_scale(boxes, pad):
    """
    Bisect for "the largest scale that fits into the unit square".

    Packing itself is NP-hard, but **"does it fit at a given scale" is a cheap decision** -- one shelf
    fill gives the answer. Wrapped in bisection, 30 rounds to 1e-9, still O(30n) in total.
    """
    def fits(s):
        _, h, w = _shelf(boxes * s, 1.0, pad)
        return h <= 1.0 and w <= 1.0

    # Bisection needs a [feasible, infeasible] pair of bounds. The first version only probed downward until feasible and then
    # bisected, so the upper bound itself was feasible -- it always converged to that upper bound, needlessly losing half the
    # image (measured: 6 squares used only 0.79 x 0.52). You must first go down to feasible, then double upward
    # to find the infeasible end
    s = 1.0 / max(float(boxes.max()), 1e-12)
    for _ in range(80):
        if fits(s):
            break
        s *= 0.5
    else:
        return 0.0
    lo, hi = s, s * 2.0
    for _ in range(80):
        if not fits(hi):
            break
        lo, hi = hi, hi * 2.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if fits(mid):
            lo = mid
        else:
            hi = mid
    return lo


def transform(geo, name="uv", cls=VERTEX, translate=(0.0, 0.0), rotate=0.0,
              scale=(1.0, 1.0), pivot=(0.5, 0.5), per_island=False,
              group=""):
    """
    Translate / rotate / scale in UV space.

    With per_island=True each island rotates around **its own center** -- use this when you want to rotate scattered islands by 90 degrees each
    rather than have them orbit around the atlas center.
    """
    if geo is None:
        return Geometry()
    if cls not in CLASSES:
        raise ValueError(f"Class must be one of {CLASSES}")
    if geo.count(cls) == 0:
        return geo.copy()
    uv = _get_uv(geo, name, cls)
    if not len(uv):
        return geo.copy()
    ang = np.radians(float(rotate))
    c, s = np.cos(ang), np.sin(ang)
    sc = np.asarray(scale, np.float64).reshape(2)
    tr = np.asarray(translate, np.float64).reshape(2)

    sel_e = resolve(geo, cls, group)
    out = uv.copy()
    if per_island:
        isl = islands(geo, name)
        sizes_p = geo.prim_sizes()
        if cls == VERTEX:
            owner = np.repeat(isl, sizes_p)
        else:
            owner = np.full(geo.npoints, -1, np.int64)
            owner[geo.vertex_point] = np.repeat(isl, sizes_p)
        for k in np.unique(owner[owner >= 0]):
            m = (owner == k) & sel_e
            if not m.any():
                continue
            piv = 0.5 * (uv[m].min(0) + uv[m].max(0))
            out[m] = _xf(uv[m], piv, c, s, sc, tr)
    else:
        piv = np.asarray(pivot, np.float64).reshape(2)
        out[sel_e] = _xf(uv[sel_e], piv, c, s, sc, tr)

    g = geo.copy()
    a = geo.get(cls, name)
    col = np.array(a, np.float64)
    col[:, :2] = out
    g.set(cls, name, col.astype(a.dtype), owned=True)
    return g


def _xf(p, piv, c, s, sc, tr):
    d = (p - piv) * sc
    return np.stack([d[:, 0] * c - d[:, 1] * s,
                     d[:, 0] * s + d[:, 1] * c], 1) + piv + tr
