"""
UV Auto Seams -- find seams automatically, so UV Flatten really becomes one-click.

After LSCM was done last round, UV unwrapping was still missing a step: seams had to be given by hand as an edge group. In Houdini you can
click edges in the viewport; ComfyUI has no such interaction -- so generating seams automatically is not icing on the cake, but the piece that makes
the whole chain usable.

The output is an **edge group**, connected to UV Flatten's Seam Group. It is split into two nodes rather than one because
seams deserve a separate look (you can connect Group Edges first to add or remove a few by hand before unwrapping).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Seams must satisfy two things of **completely different nature** at once
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    1. look good  -- cut along creases, separate high-curvature areas, low distortion after unwrapping
    2. unwrappable  -- after cutting every piece **must be a disk**, otherwise LSCM has no solution at all

The first is heuristic (any cut works, just better or worse), the second is a **hard constraint** (topology;
not satisfied means no solution). The two must be handled separately; a single threshold cannot control both: cutting by dihedral angle
may leave some piece still a closed shell, or cut a piece into a surface with a handle.

So the process is: first pick candidate seams heuristically, then **complete** them topologically until every piece is a disk. The completed part
does not look good, but without it the whole thing does not work.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The criterion is the Euler characteristic, not "does it look right"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Whether a piece is a disk after cutting has an exact criterion:

    χ = V - E + F = 1        (disk)
    χ = 0                    (annulus: has a hole, or a tube)
    χ = 2 - 2g               (closed, g being the genus)

Here V is the number of **wedges** (two on the two sides of a seam), and each seam edge counts twice in E (after cutting
it becomes two boundary edges). Computing this number tells you whether it is enough, no eyeballing -- the tests check it after every step.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Completing to disks uses tree-cotree
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The classic construction, three steps:

    1. on the **dual graph** (faces are nodes, edges are edges) build a spanning tree T*. Tree edges are not cut
    2. the remaining edges C = all interior edges − T*. **Cutting all of C, the faces become a tree** --
       a tree of polygons joined edge to edge laid out flat is a disk, so χ is necessarily 1
    3. C is too large (on a sphere C is the whole original spanning tree, almost every edge would be cut). Prune:
       repeatedly delete edges "one of whose endpoints has only one edge in C". What remains is loops and
       paths connecting to the boundary -- cutting it still gives disks, but with most of the cuts removed

**On a sphere pruning reduces C to nothing**, and an empty cut cannot give a disk (a sphere is not a disk). This is not
a flaw in the algorithm; a sphere really does need at least one cut: the fix is to first find the longest path in C,
mark its two endpoints "do not prune", so after pruning exactly that path remains -- in effect automatically cutting a meridian.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM
from .groups import resolve, resolve_edges, edge_mask
from .topology import topology, edge_angles
from .ops import prim_normals

MODES = ("angle", "charts", "both", "existing_islands")


# ══════════════════════════════════════════════════════════ heuristic candidates
def angle_seams(geo, min_angle=45.0):
    """(E,) bool: edges whose dihedral angle exceeds the threshold. Cutting at creases gives the least unwrap distortion."""
    t = topology(geo)
    if t.nedges == 0:
        return np.zeros(0, bool)
    return edge_angles(geo) >= float(min_angle)


def normal_charts(geo, cone_angle=66.0, seam=None):
    """
    Split faces into charts by normal cone -- the approach of Blender's Smart UV Project.

    Start from the face with the largest area and grow outward by BFS: a neighbour joins if the angle between its normal and the **seed normal** is within the cone.
    The seed normal rather than a running average is used so a chart's orientation is predictable -- a running average lets a chart
    slowly "drift" along a curved surface, ending up 90 degrees apart from end to end, while every step in between stays within the threshold.
    """
    nf = geo.nprims
    if nf == 0:
        return np.zeros(0, np.int64)
    t = topology(geo)
    N = prim_normals(geo, normalize=True).astype(np.float64)
    lim = float(np.cos(np.radians(float(np.clip(cone_angle, 0.0, 180.0)))))

    two = np.nonzero(t.edge_count == 2)[0]
    if seam is not None and len(two):
        two = two[~np.asarray(seam, bool)[two]]
    if len(two):
        vprim = geo.vertex_prim().astype(np.int64)
        a = vprim[t.edge_he[t.edge_he_off[two]]]
        b = vprim[t.edge_he[t.edge_he_off[two] + 1]]
        keys = np.concatenate([a, b])
        vals = np.concatenate([b, a])
        order = np.argsort(keys, kind="stable")
        off = np.concatenate(
            [[0], np.cumsum(np.bincount(keys, minlength=nf))]).astype(np.int64)
        nb = vals[order]
    else:
        off, nb = np.zeros(nf + 1, np.int64), np.zeros(0, np.int64)

    from .measure import prim_areas
    order_f = np.argsort(-np.asarray(prim_areas(geo), np.float64),
                         kind="stable")
    chart = np.full(nf, -1, np.int64)
    cnt = np.diff(off)
    k = 0
    for f0 in order_f:
        if chart[f0] >= 0:
            continue
        seed = N[f0]
        chart[f0] = k
        frontier = np.array([f0], np.int64)
        while len(frontier):
            c = cnt[frontier]
            if not c.sum():
                break
            idx = (np.repeat(off[frontier], c) + np.arange(c.sum())
                   - np.repeat(np.cumsum(c) - c, c))
            cand = np.unique(nb[idx])
            cand = cand[(chart[cand] < 0) & (N[cand] @ seed >= lim)]
            if not len(cand):
                break
            chart[cand] = k
            frontier = cand
        k += 1
    return chart


def chart_seams(geo, chart):
    """(E,) bool: edges whose two sides belong to different charts."""
    t = topology(geo)
    out = np.zeros(t.nedges, bool)
    two = np.nonzero(t.edge_count == 2)[0]
    if not len(two):
        return out
    vprim = geo.vertex_prim().astype(np.int64)
    a = vprim[t.edge_he[t.edge_he_off[two]]]
    b = vprim[t.edge_he[t.edge_he_off[two] + 1]]
    out[two] = chart[a] != chart[b]
    return out


# ══════════════════════════════════════════════════════════ topology: complete to disks
def euler(geo, seam):
    """
    χ of each connected piece after cutting = V_wedge − E_cut + F. A disk is 1.

    E_cut: interior non-seam edges count 1, seam edges count 2 (cut into two boundary edges), original boundary edges count 1.
    """
    from .uvflatten import wedges
    t = topology(geo)
    pairs = t.edge_points[np.asarray(seam, bool)]
    wid, comp = wedges(geo, pairs)
    nc = int(comp.max()) + 1 if len(comp) else 0
    if nc == 0:
        return np.zeros(0, np.int64)

    sizes = geo.prim_sizes()
    # V: number of wedges occurring in each piece
    wcomp = np.repeat(comp, sizes)
    V = np.array([len(np.unique(wid[wcomp == c])) for c in range(nc)])
    F = np.bincount(comp, minlength=nc)
    # E: after cutting, a seam edge **becomes two boundary edges, one belonging to the piece on each side**.
    # The first version booked both on one side's account: the total was right, the per-piece split completely wrong (on a cube
    # χ came out as -7 / 1 / 9) -- looking only at the total cannot catch this kind of error
    vprim = geo.vertex_prim().astype(np.int64)
    sm = np.asarray(seam, bool)
    manifold = t.edge_count == 2
    inner = manifold & ~sm
    E = np.zeros(nc, np.int64)
    if inner.any():                       # interior non-seam edges: same piece on both sides, counted once
        first = t.edge_he[t.edge_he_off[:t.nedges][inner]]
        E += np.bincount(comp[vprim[first]], minlength=nc)
    rest = ~inner                         # seam / boundary / non-manifold edges: counted once per half-edge
    if rest.any():
        he = t.edge_he[np.repeat(rest, t.edge_count)]
        E += np.bincount(comp[vprim[he]], minlength=nc)
    return V - E + F


def _prune(pairs, protect, npoints):
    """
    Repeatedly delete edges "one of whose endpoints has only one edge". What remains is loops + paths connecting protected points.

    Protected points are not leaves -- points on the boundary, and the two endpoints specially picked in closed pieces.
    """
    alive = np.ones(len(pairs), bool)
    a, b = pairs[:, 0], pairs[:, 1]
    for _ in range(10000):
        deg = np.bincount(np.concatenate([a[alive], b[alive]]),
                          minlength=npoints)
        leaf = (deg == 1) & ~protect
        kill = alive & (leaf[a] | leaf[b])
        if not kill.any():
            break
        alive &= ~kill
    return alive


def _longest_path(pairs, npoints):
    """
    Edge mask of the longest path in a tree (two BFS passes). Used to open the first cut in a closed piece.

    Cutting one arc turns a sphere into a disk -- the longer the arc, the more relaxed the unwrap, so the tree's diameter is used.
    """
    if not len(pairs):
        return np.zeros(0, bool)
    a, b = pairs[:, 0].astype(np.int64), pairs[:, 1].astype(np.int64)
    keys = np.concatenate([a, b])
    vals = np.concatenate([b, a])
    eid = np.concatenate([np.arange(len(a)), np.arange(len(a))])
    order = np.argsort(keys, kind="stable")
    off = np.concatenate(
        [[0], np.cumsum(np.bincount(keys, minlength=npoints))]).astype(np.int64)
    nb, ne = vals[order], eid[order]
    cnt = np.diff(off)

    def bfs(src):
        prev = np.full(npoints, -1, np.int64)
        pedge = np.full(npoints, -1, np.int64)
        seen = np.zeros(npoints, bool)
        seen[src] = True
        frontier = np.array([src], np.int64)
        last = src
        while len(frontier):
            c = cnt[frontier]
            if not c.sum():
                break
            idx = (np.repeat(off[frontier], c) + np.arange(c.sum())
                   - np.repeat(np.cumsum(c) - c, c))
            nxt, ee = nb[idx], ne[idx]
            src_v = np.repeat(frontier, c)
            keep = ~seen[nxt]
            nxt, ee, src_v = nxt[keep], ee[keep], src_v[keep]
            if not len(nxt):
                break
            u, first = np.unique(nxt, return_index=True)
            prev[u] = src_v[first]
            pedge[u] = ee[first]
            seen[u] = True
            frontier = u
            last = int(u[-1])
        return last, prev, pedge

    s, _, _ = bfs(int(a[0]))
    e, prev, pedge = bfs(s)
    mask = np.zeros(len(a), bool)
    v = e
    while prev[v] >= 0:
        mask[pedge[v]] = True
        v = int(prev[v])
    return mask


def ensure_disk(geo, seam, keep=None):
    """
    Complete seam until "every connected piece is a disk after cutting". Returns a new (E,) bool.

    tree-cotree: cutting all edges outside a dual spanning tree guarantees disks; pruning then gives most of them back.

    keep (pcg100, Houdini's Exclude edges): edges to avoid cutting where possible. The dual tree takes them first (_dual_tree_avoiding);
    when opening a cut in a closed piece, only non-excluded edges are chosen. If all are excluded a few must still be cut (otherwise it is not a disk), which topology forces.
    """
    t = topology(geo)
    if t.nedges == 0 or geo.nprims == 0:
        return np.asarray(seam, bool).copy()
    seam = np.asarray(seam, bool).copy()
    chi = euler(geo, seam)
    if len(chi) and (chi == 1).all():
        return seam

    from .uvflatten import wedges
    _, comp = wedges(geo, t.edge_points[seam])
    vprim = geo.vertex_prim().astype(np.int64)
    two = np.nonzero((t.edge_count == 2) & ~seam)[0]
    if not len(two):
        return seam
    fa = vprim[t.edge_he[t.edge_he_off[two]]]
    fb = vprim[t.edge_he[t.edge_he_off[two] + 1]]

    for c in np.nonzero(chi != 1)[0]:
        sel = (comp[fa] == c)
        eids = two[sel]
        if not len(eids):
            continue
        # points on the boundary (original boundary + existing seams) are protected: pruning does not remove them
        protect = np.zeros(geo.npoints, bool)
        bnd = seam | (t.edge_count != 2)
        if bnd.any():
            protect[t.edge_points[bnd].reshape(-1)] = True
        # ── 1. dual spanning tree: BFS, recording the edges used
        if keep is not None and np.asarray(keep, bool)[eids].any():
            used = _dual_tree_avoiding(fa[sel], fb[sel], geo.nprims,
                                       np.asarray(keep, bool)[eids])
        else:
            used = _dual_tree(fa[sel], fb[sel], geo.nprims)
        cut = eids[~used]
        if not len(cut):
            continue
        pairs = t.edge_points[cut].astype(np.int64)
        # ── 2. pruning
        if not protect[pairs.reshape(-1)].any():
            # closed piece: no boundary to attach to -- open a cut of its own, using the tree's diameter
            sub = (np.ones(len(cut), bool) if keep is None
                   else ~np.asarray(keep, bool)[cut])
            if keep is not None and sub.any():
                # with Exclude edges: the cut is chosen only among non-excluded edges (the path between two points in a tree is unique, both endpoints are in
                # the same component of this sub-forest, so the path left after pruning does not pass through the excluded region)
                lp = _longest_path(pairs[sub], geo.npoints)
                ends = pairs[sub][lp]
            else:
                lp = _longest_path(pairs, geo.npoints)
                ends = pairs[lp]
            if len(ends):
                deg = np.bincount(ends.reshape(-1), minlength=geo.npoints)
                protect[np.nonzero(deg == 1)[0]] = True
        seam[cut[_prune(pairs, protect, geo.npoints)]] = True
    return seam


def _dual_tree_avoiding(fa, fb, nf, avoid):
    """
    Dual spanning tree for Exclude edges: Kruskal + union-find, with excluded edges **taken first**. Returns (len(fa),) bool.

    Edges on the dual tree are never cut; the cut set C = edges outside the dual tree, so taking excluded edges first = fewest excluded edges in C. The remaining
    excluded edges that must be cut are forced by topology (the ring of faces around an interior point of the excluded region forms a cycle in the dual graph and one must break) --
    in C these edges are branches hanging into the excluded region, and pruning removes the whole branch, unless the excluded region itself is the only passage.
    A per-edge Python loop -- only taken when Exclude edges are given; otherwise BFS as before (_dual_tree).

    (Tried the two-step approach of "first take a spanning tree on the primal graph avoiding excluded edges, then the dual tree of its complement"; on spheres / tubes /
    boxes the result was no different from this step -- mutation testing proved that step redundant, so it was deleted.)
    """
    parent = np.arange(nf, dtype=np.int64)

    def find(x):
        r = x
        while parent[r] != r:
            r = parent[r]
        while parent[x] != r:                 # path compression: only affects speed
            parent[x], x = r, parent[x]
        return r

    used = np.zeros(len(fa), bool)
    for i in np.concatenate([np.nonzero(avoid)[0], np.nonzero(~avoid)[0]]):
        a, b = find(int(fa[i])), find(int(fb[i]))
        if a != b:
            parent[a] = b
            used[i] = True
    return used


def _dual_tree(fa, fb, nf):
    """Dual-graph BFS spanning tree. Returns (len(fa),) bool: which edges are tree edges."""
    keys = np.concatenate([fa, fb])
    vals = np.concatenate([fb, fa])
    eid = np.concatenate([np.arange(len(fa)), np.arange(len(fa))])
    order = np.argsort(keys, kind="stable")
    off = np.concatenate(
        [[0], np.cumsum(np.bincount(keys, minlength=nf))]).astype(np.int64)
    nb, ne = vals[order], eid[order]
    cnt = np.diff(off)

    used = np.zeros(len(fa), bool)
    seen = np.zeros(nf, bool)
    for start in np.unique(np.concatenate([fa, fb])):
        if seen[start]:
            continue
        seen[start] = True
        frontier = np.array([start], np.int64)
        while len(frontier):
            c = cnt[frontier]
            if not c.sum():
                break
            idx = (np.repeat(off[frontier], c) + np.arange(c.sum())
                   - np.repeat(np.cumsum(c) - c, c))
            nxt, ee = nb[idx], ne[idx]
            keep = ~seen[nxt]
            if not keep.any():
                break
            u, first = np.unique(nxt[keep], return_index=True)
            used[ee[keep][first]] = True
            seen[u] = True
            frontier = u
    return used


# ══════════════════════════════════════════════════════════ entry
def auto_seams(geo, name="seams", mode="both", min_angle=45.0,
               cone_angle=66.0, make_disks=True, group="",
               output_chart_attrib="", include_edges="", exclude_edges="",
               island_attrib="", uv_attrib="uv", tolerance=1e-6):
    """
    Generate seams automatically, written as an edge group.

    mode=angle only cuts creases; charts splits by normal cone and cuts chart borders; both first cuts creases, then splits by normal
    where the creases do not separate. With make_disks on, every piece is **guaranteed** to be a disk after cutting.

    Added in pcg100 (Houdini UV Autoseam):
      mode=existing_islands   Splitting = Existing Islands: edges split in the existing uvs are the starting point
                              (uv_attrib, tolerance = Connectivity Tolerance)
      include_edges           these edges are always seams
      exclude_edges           these edges are not seams (Make Disks also avoids them where possible when completing, see ensure_disk)
      island_attrib           integer prim attribute: cut between adjacent faces with different values
    """
    if geo is None:
        return Geometry()
    if mode not in MODES:
        raise ValueError(f"Mode must be one of {MODES}")
    nm = str(name or "").strip()
    if not nm:
        raise ValueError("Output Group is empty.")
    if geo.nprims == 0 or geo.nvertices == 0:
        g = geo.copy()
        g.set_edge_group(nm, np.zeros((0, 2), np.int32))
        return g

    t = topology(geo)
    seam = np.zeros(t.nedges, bool)
    if mode in ("angle", "both"):
        seam |= angle_seams(geo, min_angle)
    chart = None
    if mode in ("charts", "both"):
        chart = normal_charts(geo, cone_angle, seam)
        seam |= chart_seams(geo, chart)
    if mode == "existing_islands":
        from .uvlayout import uv_seam_edges
        if geo.get(VERTEX, str(uv_attrib).strip()) is None:
            raise KeyError(f"Splitting = Existing Islands reads the vertex uv '{uv_attrib}', which the geometry does not have. "
                           f"(point uv cannot express seams)")
        seam |= uv_seam_edges(geo, str(uv_attrib).strip(), float(tolerance))
    if str(island_attrib).strip():
        a = geo.get(PRIM, str(island_attrib).strip())
        if a is None:
            raise KeyError(f"No prim attribute '{island_attrib}'.")
        two = np.nonzero(t.edge_count == 2)[0]
        if len(two):
            vprim = geo.vertex_prim().astype(np.int64)
            v = np.asarray(a)[:, 0]
            seam[two] |= (v[vprim[t.edge_he[t.edge_he_off[two]]]]
                          != v[vprim[t.edge_he[t.edge_he_off[two] + 1]]])
    if str(group).strip():
        # restricted to the selected faces: edges with neither side in the selection may not become seams
        sel = resolve(geo, PRIM, group)
        vprim = geo.vertex_prim().astype(np.int64)
        touch = np.zeros(t.nedges, bool)
        he = t.edge_he
        np.logical_or.at(touch, np.repeat(np.arange(t.nedges), t.edge_count),
                         sel[vprim[he]])
        seam &= touch
    if str(include_edges).strip():
        seam |= edge_mask(geo, resolve_edges(geo, include_edges))
    excl = None
    if str(exclude_edges).strip():
        excl = edge_mask(geo, resolve_edges(geo, exclude_edges))
        seam &= ~excl
    if make_disks:
        seam = ensure_disk(geo, seam, excl)

    g = geo.copy()
    g.set_edge_group(nm, t.edge_points[seam])
    if str(output_chart_attrib).strip():
        if chart is None:
            from .uvflatten import wedges
            _, chart = wedges(geo, t.edge_points[seam])
        g.set(PRIM, str(output_chart_attrib).strip(),
              np.asarray(chart, np.int32)[:, None], owned=True)
    return g
