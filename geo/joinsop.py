"""
PolyPath / Join -- reconnect a pile of broken polylines into complete curves.

Resample / Carve / Sweep / PolyExpand2D all work **per prim**: one curve
is one prim, and that's how they know what "walking along the curve" means. But what upstream gives is often not one curve
but a pile:

    - Clip / Delete cuts one line into several segments
    - Convert Line by default emits **a pile of two-point segments** (4x4 grid -> 24 of them)
    - several sources Merged together, endpoints coincident but not the same point
    - hand-drawn road networks, each segment built separately

In that case `Resample segments=10` doesn't give you 10 segments, it gives every fragment 10 segments each.
Sweep is worse -- each fragment sweeps its own tube, with interpenetration at every seam.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Two nodes; the dividing line is "**does it create an edge out of nothing**"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    **PolyPath**  only joins endpoints that **already touch**. The geometric shape doesn't change at all; only
                  "which points belong to which prim" changes. What doesn't touch doesn't touch, and stays as two curves

    **Join**      joins **forcibly** in order: if the endpoints don't coincide, a straight segment is added to bridge them. The geometry **does**
                  change (edges that didn't exist before appear)

This line is drawn firmly because both needs are real and mutually exclusive. Fixing Clip's fragments needs
PolyPath (nothing extra should appear); joining five separately built trajectories into one complete path needs Join
(those connecting segments are exactly what's wanted). Mixed into one node behind a toggle, users would never be sure whether their graph
had quietly had edges added.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Join by **whole prim** (run), not by re-walking edge by edge
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Houdini's PolyPath breaks the input into edges and re-chains them. That has a nasty consequence: an originally
intact long polyline, if some point in its middle **happens** to be crossed by another line, gets split in two there --
the user asked for nothing, yet the input became more fragmented.

Here a different model: each input polyline is an **atomic run**, and only its two **endpoints** take part in
joining. So

    - a long polyline crossing through someone else's middle is kept as is (that intersection is its interior, not an endpoint)
    - for a soup of two-point segments the result is exactly the same as the edge-level approach (each segment only has endpoints anyway)

Simple, predictable, and right for both kinds of input. The cost is that it won't split a badly built polyline for you --
that's Dissolve / Blast's job, not Join's.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Junctions (three or more crowding onto one endpoint)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Degree-2 endpoints are unambiguous; just join them. Degree >= 3 needs a choice, three rules:

    split        stop. Houdini PolyPath's behaviour, the most conservative
    straightest  pick the one with the **smallest turn** (stop beyond Max Angle). A must for road networks --
                 on a 4x4 grid, split gives 20 fragments (mostly two-point),
                 straightest gives 8 (4 rows + 4 columns), and only the latter is something you can Sweep
    any          join any one (by prim number, so deterministic). For when you just want to twist a tangle of lines into
                 as few curves as possible

Plus `match_attribute`: two runs may not be joined if some prim attribute differs. On a road network, splitting
by `name` or road class keeps the arterial road from turning into an alley at a junction.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tolerance welding: **no averaging**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When two endpoints are within tolerance but not the same point, the output keeps **the one that came first**; the later one simply stops being
referenced (the point stays in the geometry unless Remove Unused Points is on).

Not taking the midpoint is deliberate: averaging would move **the endpoints of both lines**, and then "PolyPath doesn't change the geometric
shape" no longer holds -- and that is exactly its dividing line with Join. Deviations within tolerance are
numerical noise anyway; just pick one. If you really want each side to meet halfway, connect a Fuse first; that node exists for exactly this.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When reversing, vertex attributes must be reversed too
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The chain may enter a run **backwards**. Reversing the point number sequence is obvious; what's easy to miss is
its vertex attributes (uv, width, curveu) -- those are stored per corner, and if not reversed the uv
flips along the whole run at the seam, the "looks right" kind of error (shape unchanged, only the texture flow is wrong).

So the implementation doesn't concatenate point numbers directly; it concatenates **source corner indices** and gathers once at the end.
Point numbers are looked up from the corners, and reversing needs just one `[::-1]`, so it can't be missed.

Prim attributes are taken from the **first run** in the chain (Houdini Join's rule too): things like name / material
carry over. To drop them, set Prim Attribs to drop.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL
from .groups import resolve
from .ops import delete_points
from .fusesop import _pairs_within, _labels

JUNCTIONS = ("split", "straightest", "any")
PRIM_ATTRIBS = ("first", "drop")


# ═══════════════════════════════════════════════════════════════════ utilities
def _runs(geo, sel, include_closed=False):
    """
    Selected **open polyline** prims -> list of runs. Returns (list of run corner arrays, prim numbers,
    boolean mask of prims that didn't take part).

    Closed prims (faces, closed loops) and single-point prims don't take part: they have no "endpoints" to join.
    They pass through to the output unchanged -- not dropped; dropping would cause "after connecting a PolyPath all my faces are gone"
    kinds of things.
    """
    off = geo.prim_offset.astype(np.int64)
    sizes = geo.prim_sizes().astype(np.int64)
    take = sel & (~geo.prim_closed if not include_closed
                  else np.ones(geo.nprims, bool)) & (sizes >= 2)
    idx = np.nonzero(take)[0]
    runs = [np.arange(off[i], off[i + 1], dtype=np.int64) for i in idx]
    return runs, idx, ~take


def _weld_nodes(P, ends, tol):
    """
    Weld labels for run endpoints. ends is (2R,) **point numbers** (alternating start/end).

    With tol <= 0 only "already the same point" counts as one node -- then point numbers are used directly as labels,
    no need to run a spatial hash.
    """
    if tol <= 0:
        _, inv = np.unique(ends, return_inverse=True)
        return inv.reshape(-1).astype(np.int64)
    E = np.asarray(P[ends], np.float64)
    ia, ib = _pairs_within(E, E, float(tol), same=True)
    lab, _ = _labels(len(ends), (ia, ib))
    return lab.astype(np.int64)


def _dirs(P, corners_list, vp):
    """
    The **leaving direction** (unit vector) at both ends of each run. (R, 2, 3): [:,0] leaves from the start,
    [:,1] leaves from the end (i.e. walking backwards).

    Only the **one segment** at the end is looked at, not the whole chord -- what a junction needs to decide is "does joining turn",
    which is local. Using the chord, a line that curves round half a circle would give a completely wrong direction.
    """
    out = np.zeros((len(corners_list), 2, 3), np.float64)
    for i, c in enumerate(corners_list):
        p = np.asarray(P[vp[c]], np.float64)
        d0 = p[1] - p[0]
        d1 = p[-2] - p[-1]
        for j, d in ((0, d0), (1, d1)):
            n = float(np.linalg.norm(d))
            out[i, j] = d / n if n > 0 else 0.0
    return out


def _incidence(node, nruns):
    """CSR of node -> [(run, end), ...]. end 0 = start, 1 = end."""
    n = int(node.max()) + 1 if len(node) else 0
    order = np.argsort(node, kind="stable")
    cnt = np.bincount(node, minlength=n)
    off = np.concatenate([[0], np.cumsum(cnt)]).astype(np.int64)
    return off, order            # order holds flat 2R indices: run*2 + end


def _build(geo, chains, pass_idx, prim_attribs, close_loops, vp, nodemap):
    """
    chains is [[(corner array, reversed?), ...], ...]. Concatenate into new geometry.

    What's concatenated is **source corners**, not point numbers -- point numbers are looked up from the corners at the end. That way vertex
    attributes, point numbers and reversal all share a single path and can't be missed.

    Seams and closed loops are both judged by **weld label**, not point number: two endpoints welded by tolerance are different points,
    and comparing point numbers would miss the "should an almost-closed line be closed" case.
    """
    def same(ca, cb):
        a = nodemap.get(int(ca), -1)
        return a >= 0 and a == nodemap.get(int(cb), -2)

    blocks, sizes, closed, src_prim = [], [], [], []
    vprim = geo.vertex_prim()
    for ch in chains:
        seq = []
        for cor, rev in ch:
            s = (cor[::-1] if rev else cor).tolist()
            if seq and same(seq[-1], s[0]):
                s = s[1:]            # of two endpoints welded together, keep only the first
            seq.extend(s)
        if len(seq) < 2:
            continue
        cl = False
        if close_loops and len(seq) > 2 and same(seq[0], seq[-1]):
            seq = seq[:-1]
            cl = True
        blocks.append(np.asarray(seq, np.int64))
        sizes.append(len(seq))
        closed.append(cl)
        src_prim.append(int(vprim[ch[0][0][0]]))

    # prims that didn't take part are carried over unchanged
    keep = np.nonzero(pass_idx)[0]
    off = geo.prim_offset.astype(np.int64)
    for i in keep:
        blocks.append(np.arange(off[i], off[i + 1], dtype=np.int64))
        sizes.append(int(off[i + 1] - off[i]))
        closed.append(bool(geo.prim_closed[i]))
        src_prim.append(int(i))

    return _assemble(geo, blocks, sizes, closed, src_prim, prim_attribs, vp)


def _assemble(geo, blocks, sizes, closed, src_prim, prim_attribs, vp):
    """
    Assemble the output. **Sorted by source prim number** -- output prim order doesn't follow traversal order.

    This isn't fastidiousness: lots of downstream nodes (Join itself, For-Each, number ranges in groups)
    work by prim number; if the order followed internal traversal, changing an unrelated parameter could
    reshuffle everything downstream. Sorting also yields a hard property: **running it again is bit-identical**
    (without sorting, closed prims would move from the "chain" bucket to the "pass through" bucket, changing position).
    """
    g = Geometry()
    g._resize_points(geo.npoints)
    for k, v in geo.attribs[POINT].items():
        g.set(POINT, k, v)
    for k, v in geo.groups[POINT].items():
        g.set_group(POINT, k, v)
    if not blocks:
        g.set_topology(np.zeros(0, np.int32), np.zeros(1, np.int32),
                       np.zeros(0, bool))
        g.attribs[DETAIL] = dict(geo.attribs[DETAIL])
        return g
    sp = np.asarray(src_prim, np.int64)
    order = np.argsort(sp, kind="stable")
    blocks = [blocks[i] for i in order.tolist()]
    sizes = [sizes[i] for i in order.tolist()]
    closed = [closed[i] for i in order.tolist()]
    sp = sp[order]
    cor = np.concatenate(blocks)
    g.set_topology(vp[cor].astype(np.int32),
                   np.concatenate([[0], np.cumsum(sizes)]).astype(np.int32),
                   np.asarray(closed, bool))
    for k, v in geo.attribs[VERTEX].items():
        g.set(VERTEX, k, v[cor], owned=True)
    for k, v in geo.groups[VERTEX].items():
        g.set_group(VERTEX, k, v[cor])
    if prim_attribs == "first":
        for k, v in geo.attribs[PRIM].items():
            g.set(PRIM, k, v[sp], owned=True)
        for k, v in geo.groups[PRIM].items():
            g.set_group(PRIM, k, v[sp])
        g.prim_data = geo.remap_prim_data(sp)
    g.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    return g


# ══════════════════════════════════════════════════════════════ PolyPath
def polypath(geo, group="", tolerance=0.0, junction="split", max_angle=60.0,
             match_attribute="", close_loops=True, prim_attribs="first",
             remove_unused_points=False, include_closed=False):
    """
    Chain polylines whose endpoints touch into curves as long as possible. **No new edges** -- what doesn't touch doesn't touch.

    With tolerance=0 only "already the same point" counts; with >0, endpoints within this distance also count as touching
    (merging keeps the first, no averaging; see the module header for why).
    """
    if geo is None:
        return Geometry()
    if junction not in JUNCTIONS:
        raise ValueError(f"Junction must be one of {JUNCTIONS}")
    if prim_attribs not in PRIM_ATTRIBS:
        raise ValueError(f"Prim Attribs must be one of {PRIM_ATTRIBS}")
    sel = resolve(geo, PRIM, group)
    if geo.nprims == 0 or not sel.any():
        return geo.copy()
    P = geo.get(POINT, "P")
    if P is None:
        return geo.copy()
    vp = geo.vertex_point.astype(np.int64)
    runs, ridx, passthru = _runs(geo, sel, include_closed)
    R = len(runs)
    if R == 0:
        return geo.copy()

    ends = np.array([[vp[c[0]], vp[c[-1]]] for c in runs],
                    np.int64).reshape(-1)
    node = _weld_nodes(P, ends, float(tolerance))
    off, order = _incidence(node, R)
    D = _dirs(P, runs, vp) if junction == "straightest" else None
    cosmax = float(np.cos(np.radians(float(max_angle))))

    mk = str(match_attribute).strip()
    mval = None
    if mk:
        a = geo.get(PRIM, mk)
        if a is None:
            raise KeyError(
                f"No prim attribute '{mk}'. Existing: "
                f"{geo.names(PRIM) or '(none)'}")
        mval = a[ridx]

    deg = np.diff(off)
    used = np.zeros(R, bool)

    def slots(n):
        return order[off[n]:off[n + 1]]

    def pick(n, from_run, from_end):
        """From node n, pick the next run. Returns (run, entry end) or None."""
        cand = [int(s) for s in slots(n)
                if not used[s // 2] and (s // 2) != from_run]
        if mval is not None and from_run >= 0:
            cand = [s for s in cand
                    if np.array_equal(mval[s // 2], mval[from_run])]
        if not cand:
            return None
        if len(cand) == 1 and deg[n] == 2:
            return cand[0] // 2, cand[0] % 2
        if junction == "split":
            return None
        if junction == "any":
            return cand[0] // 2, cand[0] % 2
        # straightest: incoming direction = the negation of the reversed entry end = the negated leaving direction from from_end
        if from_run < 0:
            return cand[0] // 2, cand[0] % 2
        incoming = -D[from_run, from_end]     # the direction we're walking "toward"
        best, bestc = None, cosmax
        for s in cand:
            c = float(np.dot(incoming, D[s // 2, s % 2]))
            if c > bestc:
                best, bestc = s, c
        return None if best is None else (best // 2, best % 2)

    def walk(r0, e0):
        """Enter run r0 at end e0 and keep walking forward."""
        chain = []
        r, e = r0, e0
        while True:
            used[r] = True
            chain.append((runs[r], e == 1))      # entering at end = walking backwards
            far = 1 - e
            nxt = pick(int(node[r * 2 + far]), r, far)
            if nxt is None:
                break
            r, e = nxt
        return chain

    chains = []
    # walk open chains first: start from nodes with degree != 2. Picking up loops first would cut an open chain in the middle
    for n in np.nonzero(deg != 2)[0]:
        for s in slots(int(n)):
            if not used[s // 2]:
                chains.append(walk(int(s) // 2, int(s) % 2))
    for r in range(R):                           # what remains must be closed loops
        if not used[r]:
            chains.append(walk(r, 0))

    nodemap = {int(c): int(node[i]) for i, c in
               enumerate([r[k] for r in runs for k in (0, -1)])}
    g = _build(geo, chains, passthru, prim_attribs, close_loops, vp, nodemap)
    if remove_unused_points and g.npoints:
        keep = np.zeros(g.npoints, bool)
        keep[g.vertex_point] = True
        if not keep.all():
            g = delete_points(g, keep)
    return g


# ══════════════════════════════════════════════════════════════════ Join
def join(geo, group="", loop=False, tolerance=0.0, reverse_to_fit=True,
         partition_attribute="", prim_attribs="first",
         remove_unused_points=False):
    """
    Join the selected polylines into one, **in order**. Where endpoints don't coincide, a straight segment is added to bridge them -- this is its
    only difference from PolyPath, and the reason it exists.

    The order is prim number. With `reverse_to_fit` on (default), before each join it checks which end is
    closer to the current tail and puts that end first -- Houdini's Join doesn't do this, and without it, if upstream
    prim directions are slightly messy, the result is a zigzag folding back and forth. Turning it off gives strictly
    "previous tail joins next head".

    `tolerance`: a gap smaller than this counts as the same point (no bridging segment, no zero-length edge); only larger gaps actually
    get a connecting segment. So tolerance here isn't a "weld radius", it's "**how close counts as already joined**".

    `partition_attribute`: group by a prim attribute, each group joined separately. One trajectory per
    name in a fracture animation is exactly this.
    """
    if geo is None:
        return Geometry()
    if prim_attribs not in PRIM_ATTRIBS:
        raise ValueError(f"Prim Attribs must be one of {PRIM_ATTRIBS}")
    sel = resolve(geo, PRIM, group)
    if geo.nprims == 0 or not sel.any():
        return geo.copy()
    P = geo.get(POINT, "P")
    if P is None:
        return geo.copy()
    vp = geo.vertex_point.astype(np.int64)
    runs, ridx, passthru = _runs(geo, sel, False)
    if not runs:
        return geo.copy()

    pk = str(partition_attribute).strip()
    if pk:
        a = geo.get(PRIM, pk)
        if a is None:
            raise KeyError(
                f"No prim attribute '{pk}'. Existing: {geo.names(PRIM) or '(none)'}")
        vals = a[ridx]
        flat = (vals.reshape(len(vals), -1) if vals.ndim > 1 else
                vals.reshape(-1, 1))
        _, part = np.unique(flat, axis=0, return_inverse=True)
        part = part.reshape(-1)
    else:
        part = np.zeros(len(runs), np.int64)

    tol = float(tolerance)
    chains = []
    for p in np.unique(part):
        members = np.nonzero(part == p)[0]
        chain = []
        tail = None                                   # position of the current tail
        for r in members.tolist():
            c = runs[r]
            a = np.asarray(P[vp[c[0]]], np.float64)
            b = np.asarray(P[vp[c[-1]]], np.float64)
            rev = False
            if tail is not None and reverse_to_fit:
                rev = (np.linalg.norm(b - tail)
                       < np.linalg.norm(a - tail))
            chain.append((c, rev))
            tail = a if rev else b
        if loop and len(chain) > 1:
            # Closing relies solely on "first and last point numbers equal", handled uniformly in _build. If the ends already
            # coincide nothing needs doing; otherwise hang the start point once more to add that closing segment
            # The first run is never reversed (reverse_to_fit only checks once there is a tail),
            # so the chain's start is its first corner
            fp = int(chain[0][0][0])
            if (np.linalg.norm(np.asarray(P[vp[fp]], np.float64) - tail)
                    > tol):
                chain.append((np.asarray([fp], np.int64), False))
        chains.append(chain)

    g = _build_join(geo, chains, passthru, prim_attribs, tol, loop, vp, P)
    if remove_unused_points and g.npoints:
        keep = np.zeros(g.npoints, bool)
        keep[g.vertex_point] = True
        if not keep.all():
            g = delete_points(g, keep)
    return g


def _build_join(geo, chains, pass_idx, prim_attribs, tol, loop, vp, P):
    """
    Join's version of assembly. Differs from PolyPath's in just one place: at seams, whether to deduplicate is judged **by distance**,
    not by "is it the same point".
    """
    out = []
    for ch in chains:
        seq = []
        for cor, rev in ch:
            s = (cor[::-1] if rev else cor).tolist()
            if seq:
                d = float(np.linalg.norm(
                    np.asarray(P[vp[seq[-1]]], np.float64)
                    - np.asarray(P[vp[s[0]]], np.float64)))
                if d <= tol:
                    s = s[1:]
            seq.extend(s)
        out.append(seq)

    blocks, sizes, closed, src_prim = [], [], [], []
    vprim = geo.vertex_prim()
    for ch, seq in zip(chains, out):
        if len(seq) < 2:
            continue
        cl = False
        if loop and len(seq) > 2:
            d = float(np.linalg.norm(
                np.asarray(P[vp[seq[0]]], np.float64)
                - np.asarray(P[vp[seq[-1]]], np.float64)))
            if d <= tol or vp[seq[0]] == vp[seq[-1]]:
                seq = seq[:-1]
            cl = True
        blocks.append(np.asarray(seq, np.int64))
        sizes.append(len(seq))
        closed.append(cl)
        src_prim.append(int(vprim[ch[0][0][0]]))

    keep = np.nonzero(pass_idx)[0]
    off = geo.prim_offset.astype(np.int64)
    for i in keep:
        blocks.append(np.arange(off[i], off[i + 1], dtype=np.int64))
        sizes.append(int(off[i + 1] - off[i]))
        closed.append(bool(geo.prim_closed[i]))
        src_prim.append(int(i))

    return _assemble(geo, blocks, sizes, closed, src_prim, prim_attribs, vp)
