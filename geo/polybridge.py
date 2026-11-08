"""
Poly Bridge SOP -- build faces between two edge loops (punch through two faces to make a tunnel / handle, fill a tube between two
holes, connect two curves into a ruled surface).

━━ Where the two edge loops come from (Source Group / Destination Group)
  . a prim group selecting faces: the outer outline of those faces together is the loop (a single face is its own edges).
    With Remove Caps on these faces are deleted -- that is how tunnels and handles are made
  . a prim group selecting open curves: the curve itself (both ends open, the bridge is a strip)
  . a point group: the loop of mesh edges whose two ends are both in the group (usually the boundary of a hole)
Group names are looked up as prim groups first, then as point groups.

━━ Direction and alignment: why the bridge is manifold
Each loop is converted to the winding of a "cap": when faces are selected, the faces' own winding; when a hole boundary is selected, the
winding of the imagined face that would fill the hole (= the boundary edges' direction in their original faces, reversed). In the bridge quad
(a_i, a_{i+1}, b_{i+1}, b_i) the a edge runs exactly in the original cap's direction and opposite to the neighbouring face --
so with the cap deleted and the bridge attached, every edge is still used by exactly two faces in opposite directions, normals consistent with the original mesh.
The destination loop must be walked in the **opposite** direction (both caps' normals point outward, so viewed face to face their windings are opposite).

Two loops with the same point count: "carry" the source loop's cross-section (minus its center) along the bridge to the destination end -- the carry is the minimal
rotation from the departure direction to the arrival direction: identity for a straight-through tunnel (translation correspondence), and for a handle on one side a
180 deg rotation about the axis perpendicular to the arch (mirror correspondence) -- then find the start point minimizing the sum of squared distances of corresponding points, plus an offset of Twist
points. Without carrying, comparing distances directly, the two mirror pairings of a square handle have exactly the same distance sum; picking the wrong one
twists it by 90 deg (the first demo did exactly this). Different point counts: each loop is parameterized by arc length and advanced alternately like a zipper
producing triangles (each step advances the side with the smaller parameter). The direction of open curves is not determined by a cap; it is chosen
automatically by end-to-end distance; Flip Direction can force the destination loop to be reversed.

━━ Divisions and shape
Divisions segments; the intermediate rings are interpolated according to Interpolation:
  linear    straight lines between corresponding points of the two loops
  hermite   a cubic curve whose center departs / arrives along the normals of the two caps; the cross-section rotates with the bridge (for a
            one-sided handle it turns 180 deg, the top is still a complete cross-section); Magnitude is the tangent length as a multiple of the distance
            between the two loop centers. Direction is chosen automatically: if a cap normal roughly faces away from the other loop (angle > 120 deg,
            e.g. punching through the top and bottom faces of a cube) it goes inward along the normal; otherwise it arches outward (a handle between two faces
            on the same side). A negative Magnitude reverses it
New points on intermediate rings: (float) point attributes are interpolated between the two ends with the same weights; string attributes take the source end's.
With caps deleted and other faces around them (tunnel / handle / tube between holes): the bridge's direction takes over from the caps,
consistent with neighbouring faces. With caps kept, or caps that are isolated faces (two separate discs): the bridge and the two caps form a closed
shell, with direction opposite to the caps -- in both cases normals point outward. Reverse Normals flips everything once more.
prim attributes of new prims are copied from the source cap (0 if there is no cap); vertex attributes (e.g. uv) are filled with 0 --
the bridge's uv must be unwrapped again afterwards. All new faces are in the prim group Output Group.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, VERTEX, DETAIL, is_string
from .groups import resolve
from .addsop import append_prims
from .ops import delete_prims

INTERP = ("linear", "hermite")


def _directed_edges(geo, prims):
    out = []
    for p in prims:
        v = geo.prim_points(int(p)).tolist()
        n = len(v)
        if n < 2:
            continue
        m = n if geo.prim_closed[p] else n - 1
        for i in range(m):
            out.append((v[i], v[(i + 1) % n]))
    return out


def _chain(edges, what):
    """Directed edges -> one loop (or one chain). Returns (point number list, closed)."""
    nxt, prv = {}, {}
    for a, b in edges:
        if a in nxt or b in prv:
            raise ValueError(f"The edges of {what} are not a simple loop (some point branches)")
        nxt[a] = b
        prv[b] = a
    starts = [a for a in nxt if a not in prv]
    if len(starts) > 1:
        raise ValueError(f"The edges of {what} are broken into {len(starts)} pieces; they must connect into one loop or one chain")
    s = starts[0] if starts else next(iter(nxt))
    loop = [s]
    while loop[-1] in nxt:
        b = nxt[loop[-1]]
        if b == s:
            break
        loop.append(b)
    if len(loop) != len(set(nxt) | set(prv)):
        raise ValueError(f"{what} contains more than one edge loop -- only one pair is bridged at a time")
    return loop, not starts


def _loop_of(geo, spec, what):
    """Returns (point number list, closed?, list of cap prim indices, has direction)."""
    spec = str(spec).strip()
    if not spec:
        raise ValueError(f"{what} is empty -- enter a prim group (faces / curves) or a point group")
    psel = None
    if spec in geo.groups[PRIM] or "@" in spec:
        try:
            psel = resolve(geo, PRIM, spec)
        except Exception:
            psel = None
    if psel is not None and psel.any():
        prims = np.nonzero(psel)[0]
        closed = geo.prim_closed[prims] & (geo.prim_sizes()[prims] >= 3)
        if closed.all():
            E = _directed_edges(geo, prims)
            und = {}
            for a, b in E:
                k = (min(a, b), max(a, b))
                und[k] = und.get(k, 0) + 1
            bnd = [(a, b) for a, b in E if und[(min(a, b), max(a, b))] == 1]
            loop, cl = _chain(bnd, what)
            return loop, cl, prims.tolist(), True
        if len(prims) != 1:
            raise ValueError(f"{what} mixes curves and faces, or has several curves -- one at a time")
        v = geo.prim_points(int(prims[0])).tolist()
        return v, bool(geo.prim_closed[prims[0]]), [], False
    if spec in geo.groups[POINT] or "@" in spec:
        pts = resolve(geo, POINT, spec)
    elif spec in geo.groups[PRIM]:
        raise ValueError(f"{what}: prim group '{spec}' selects no faces")
    else:
        raise KeyError(f"{what}: no prim group or point group named '{spec}'")
    if not pts.any():
        raise ValueError(f"{what} selects 0 points")
    E = _directed_edges(geo, range(geo.nprims))
    und = {}
    for a, b in E:
        k = (min(a, b), max(a, b))
        und[k] = und.get(k, 0) + 1
    ins = [(a, b) for a, b in E if pts[a] and pts[b]]
    bnd = [(b, a) for a, b in ins if und[(min(a, b), max(a, b))] == 1]
    if bnd and len(bnd) == len(ins):
        loop, cl = _chain(bnd, what)                # hole boundary: cap winding = reversed
        return loop, cl, [], True
    seen, uniq = set(), []
    for a, b in ins:
        k = (min(a, b), max(a, b))
        if k not in seen:
            seen.add(k)
            uniq.append((a, b))
    if not uniq:
        raise ValueError(f"There are no edges between the points of {what}")
    # Interior edge loop: direction undetermined, chain by undirected edges
    adj = {}
    for a, b in uniq:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    if any(len(v) > 2 for v in adj.values()):
        raise ValueError(f"The edges of {what} are not a simple loop (some point branches)")
    ends = [a for a, v in adj.items() if len(v) == 1]
    s = ends[0] if ends else uniq[0][0]
    loop, prev = [s], None
    while True:
        nb = [x for x in adj[loop[-1]] if x != prev]
        if not nb or nb[0] == s:
            break
        prev = loop[-1]
        loop.append(nb[0])
    return loop, not ends, [], False


def _params(P, closed):
    seg = np.linalg.norm(np.diff(np.vstack([P, P[:1]]) if closed else P, axis=0),
                         axis=1)
    tot = seg.sum()
    t = np.r_[0.0, np.cumsum(seg)[:-1]] if closed else np.r_[0.0, np.cumsum(seg)]
    return t / tot if tot > 0 else np.linspace(0, 1, len(P), endpoint=not closed)


def _eval(P, t, closed, q):
    """Sample the polyline with arc-length parameters t at q."""
    if closed:
        P2 = np.vstack([P, P[:1]])
        t2 = np.r_[t, 1.0]
    else:
        P2, t2 = P, t
    q = np.clip(q, 0, 1)
    k = np.clip(np.searchsorted(t2, q, side="right") - 1, 0, len(t2) - 2)
    d = t2[k + 1] - t2[k]
    f = np.where(d > 0, (q - t2[k]) / np.where(d > 0, d, 1), 0.0)
    return k, f, P2[k] * (1 - f)[:, None] + P2[np.minimum(k + 1, len(P2) - 1)] \
        * f[:, None]


def _newell(P):
    n = np.zeros(3)
    for i in range(len(P)):
        n += np.cross(P[i], P[(i + 1) % len(P)])
    ln = np.linalg.norm(n)
    return n / ln if ln > 0 else n


def _transport(t0, t1, d):
    """Minimal rotation taking unit vector t0 to t1; when they are opposite, rotate 180 deg about t0 x d."""
    t0 = t0 / (np.linalg.norm(t0) or 1)
    t1 = t1 / (np.linalg.norm(t1) or 1)
    v = np.cross(t0, t1)
    c = float(t0 @ t1)
    if c > 1 - 1e-12:
        return np.eye(3), np.array([0.0, 0.0, 1.0]), 0.0
    if c < -1 + 1e-9:
        ax = np.cross(t0, d)
        if np.linalg.norm(ax) < 1e-9:
            ax = np.cross(t0, [1.0, 0, 0])
            if np.linalg.norm(ax) < 1e-9:
                ax = np.cross(t0, [0, 1.0, 0])
        ax = ax / np.linalg.norm(ax)
        return _rodrigues(ax, np.pi), ax, np.pi
    ax = v / np.linalg.norm(v)
    ang = float(np.arctan2(np.linalg.norm(v), c))
    return _rodrigues(ax, ang), ax, ang


def _rodrigues(ax, ang):
    K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
    return np.eye(3) + np.sin(ang) * K + (1 - np.cos(ang)) * K @ K


def _zip(ta, tb, closed):
    """Two parameter sequences -> triangles (index pairs ('a',i)/('b',j)). Zipper-style alternating advance."""
    na, nb = len(ta), len(tb)
    tris = []
    i = j = 0
    ea = na if closed else na - 1
    eb = nb if closed else nb - 1
    while i < ea or j < eb:
        nta = ta[i + 1] if i + 1 < na else 1.0
        ntb = tb[j + 1] if j + 1 < nb else 1.0
        adv_a = j >= eb or (i < ea and nta <= ntb)
        if adv_a:
            tris.append((("a", i), ("a", (i + 1) % na), ("b", j % nb)))
            i += 1
        else:
            tris.append((("a", i % na), ("b", (j + 1) % nb), ("b", j)))
            j += 1
    return tris


def poly_bridge(geo, source_group, dest_group, divisions=1, twist=0,
                interpolation="linear", magnitude=1.0, flip_direction=False,
                remove_caps=True, reverse_normals=False, output_group="bridge"):
    """Returns (geo, report)."""
    if interpolation not in INTERP:
        raise ValueError(f"Interpolation must be one of {INTERP}")
    A, ca, capA, orA = _loop_of(geo, source_group, "Source Group")
    B, cb, capB, orB = _loop_of(geo, dest_group, "Destination Group")
    if ca != cb:
        raise ValueError("One loop is closed and the other is open, cannot bridge")
    if set(A) & set(B):
        raise ValueError("Source and destination share points -- the two loops must be separate")
    closed = ca
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    PA = P[A]
    nA_ = _newell(PA) if closed else np.zeros(3)
    nB_ = _newell(P[B]) if closed else np.zeros(3)
    B = B[::-1]                                     # the destination loop is walked in reverse
    if not (orA and orB):
        # Direction not determined by caps: pick the walking order that aligns the ends
        PB = P[B]
        if closed:
            vA = _newell(PA)
            vB = _newell(PB)
            if vA @ vB < 0:
                B = B[::-1]
        else:
            d0 = np.linalg.norm(PA[0] - PB[0]) + np.linalg.norm(PA[-1] - PB[-1])
            d1 = np.linalg.norm(PA[0] - PB[-1]) + np.linalg.norm(PA[-1] - PB[0])
            if d1 < d0:
                B = B[::-1]
    if flip_direction:
        B = B[::-1]
    PB = P[B]
    na, nb = len(A), len(B)
    dvec = PB.mean(0) - PA.mean(0)
    dist = float(np.linalg.norm(dvec))
    dh = dvec / dist if dist > 0 else dvec
    # Departure / arrival directions: if a cap normal roughly faces away from the other loop (straight through, angle > 120 deg) go inward,
    # otherwise arch outward along the normal (handle)
    outA = -nA_ if nA_ @ dh < -0.5 else nA_
    outB = -nB_ if nB_ @ (-dh) < -0.5 else nB_
    if closed:
        cA, cB = PA - PA.mean(0), PB - PB.mean(0)
        # Alignment: "carry" the source loop's cross-section along the bridge to the destination end before comparing. Carry = the minimal rotation taking the departure tangent outA to
        # the arrival tangent -outB (straight through: identity = translation correspondence; one-sided handle: 180 deg about the axis perpendicular to
        # the arch = mirror correspondence). Comparing by distance directly, the two mirror pairings of a handle
        # have the same distance sum (measured as a tie on a square), and picking the wrong one gives a handle twisted by 90 deg
        Rt, rax, rang = _transport(outA, -outB, dh) if (orA and orB) else \
            (np.eye(3), np.array([0.0, 0.0, 1.0]), 0.0)
        qA = cA @ Rt.T
        if na == nb:
            cost = [float(((qA - np.roll(cB, -s, 0)) ** 2).sum()) for s in range(nb)]
            s0 = int(np.argmin(cost))
        else:
            dA = qA[0] / (np.linalg.norm(qA[0]) or 1)
            s0 = int(np.argmax(cB @ dA))
        s0 = (s0 + int(twist)) % nb
        B = B[s0:] + B[:s0]
        PB = P[B]
    else:
        Rt, rax, rang = np.eye(3), np.array([0.0, 0.0, 1.0]), 0.0
    tA, tB = _params(PA, closed), _params(PB, closed)
    div = max(1, int(divisions))
    # Parameters of intermediate rings: take those of the loop with more points
    big_t = tA if na >= nb else tB
    rings = [("A", A, tA)]
    newP, newW = [], []                            # new point positions, (source index, weight) interpolation info
    mag = float(magnitude) * dist
    ka, fa, QA = _eval(PA, tA, closed, big_t)
    kb, fb, QB = _eval(PB, tB, closed, big_t)
    base = geo.npoints
    for r in range(1, div):
        s = r / div
        if interpolation == "linear":
            X = (1 - s) * QA + s * QB
        else:
            # The center follows a Hermite curve; the cross-section is blended in the source loop's frame (the source cross-section and the destination cross-section
            # "carried back" interpolated by s), then rotated with the bridge by s of the carry angle. Applying Hermite
            # to each point directly would make the two mirrored points at the top of a handle coincide -- the cross-section collapses to a line
            h00 = 2 * s ** 3 - 3 * s ** 2 + 1
            h10 = s ** 3 - 2 * s ** 2 + s
            h01 = -2 * s ** 3 + 3 * s ** 2
            h11 = s ** 3 - s ** 2
            cA_, cB_ = PA.mean(0), PB.mean(0)
            Cs = h00 * cA_ + h10 * mag * outA + h01 * cB_ + h11 * (-mag * outB)
            loc = (1 - s) * (QA - cA_) + s * ((QB - cB_) @ Rt)
            X = Cs + loc @ _rodrigues(rax, s * rang).T
        start = base + sum(len(x) for x in newP)
        ids = list(range(start, start + len(X)))
        newP.append(X)
        newW.append((s, ka, fa, kb, fb))
        rings.append(("N", ids, big_t))
    rings.append(("B", B, tB))
    faces = []
    for (_, ia, ta), (_, ib, tb) in zip(rings[:-1], rings[1:]):
        if len(ia) == len(ib) and np.allclose(ta, tb):
            m = len(ia) if closed else len(ia) - 1
            for i in range(m):
                j = (i + 1) % len(ia)
                faces.append([ia[i], ia[j], ib[j], ib[i]])
        else:
            for tri in _zip(ta, tb, closed):
                faces.append([(ia if w == "a" else ib)[k] for w, k in tri])
    # Caps kept (or the caps are isolated faces with no other faces around): the bridge must form a
    # closed shell with the caps, so its direction must be opposite to the caps; caps deleted with faces around: the bridge takes over, same direction as the caps
    caps_all = capA + capB
    if caps_all and (not remove_caps or not _attached(geo, A, B, closed, caps_all)):
        faces = [f[::-1] for f in faces]
    if reverse_normals:
        faces = [f[::-1] for f in faces]
    g = _add_points(geo, newP, newW, A, B, closed) if newP else geo.copy()
    nprev = g.nprims
    g = append_prims(g, faces, closed=True)
    # New prims: copy the source cap's prim attributes
    if capA:
        for k, v in geo.attribs[PRIM].items():
            a = np.array(g.get(PRIM, k))
            a[nprev:] = v[capA[0]]
            g.set(PRIM, k, a, owned=True)
    grp = np.zeros(g.nprims, bool)
    grp[nprev:] = True
    if str(output_group).strip():
        g.set_group(PRIM, str(output_group).strip(), grp)
    caps = (capA + capB) if remove_caps else []
    if caps:
        keep = np.ones(g.nprims, bool)
        keep[caps] = False
        g = delete_prims(g, keep, keep_points=True)
    return g, {"source_points": na, "dest_points": nb, "closed": bool(closed),
               "new_prims": len(faces), "new_points": int(sum(len(x) for x in newP)),
               "caps_removed": len(caps), "offset": int(s0) if closed else 0}


def _attached(geo, A, B, closed, caps):
    """Whether the edges of the two loops are used by faces other than the caps."""
    E = set()
    for L in (A, B):
        m = len(L) if closed else len(L) - 1
        for i in range(m):
            a, b = L[i], L[(i + 1) % len(L)]
            E.add((min(a, b), max(a, b)))
    cs = set(caps)
    for p in range(geo.nprims):
        if p in cs:
            continue
        v = geo.prim_points(p).tolist()
        n = len(v)
        m = n if geo.prim_closed[p] else n - 1
        for i in range(m):
            a, b = v[i], v[(i + 1) % n]
            if (min(a, b), max(a, b)) in E:
                return True
    return False


def _add_points(geo, newP, newW, A, B, closed):
    """Append intermediate ring points after the point table; float point attributes interpolated between the two ends."""
    X = np.vstack(newP)
    n0, n1 = geo.npoints, geo.npoints + len(X)
    out = Geometry()
    out._resize_points(n1)
    out.set_topology(geo.vertex_point, geo.prim_offset, geo.prim_closed,
                     geo.prim_type)
    A2 = np.array(A + ([A[0]] if closed else []))
    B2 = np.array(B + ([B[0]] if closed else []))
    for k, v in geo.attribs[POINT].items():
        if k == "P":
            out.set(POINT, "P", np.vstack([v, X.astype(v.dtype)]), owned=True)
            continue
        rows = []
        for s, ka, fa, kb, fb in newW:
            if is_string(v):
                rows.append(v[A2[ka]])
                continue
            vv = np.asarray(v, np.float64)
            va = vv[A2[ka]] * (1 - fa)[:, None] + vv[A2[np.minimum(ka + 1,
                                                                   len(A2) - 1)]] * fa[:, None]
            vb = vv[B2[kb]] * (1 - fb)[:, None] + vv[B2[np.minimum(kb + 1,
                                                                   len(B2) - 1)]] * fb[:, None]
            rows.append(((1 - s) * va + s * vb).astype(v.dtype))
        out.set(POINT, k, np.concatenate([v] + rows), owned=True)
    for k, v in geo.groups[POINT].items():
        out.set_group(POINT, k, np.r_[v, np.zeros(n1 - n0, bool)])
    for k, v in geo.attribs[VERTEX].items():
        out.set(VERTEX, k, v)
    for k, v in geo.attribs[PRIM].items():
        out.set(PRIM, k, v)
    for k, v in geo.groups[VERTEX].items():
        out.set_group(VERTEX, k, v)
    for k, v in geo.groups[PRIM].items():
        out.set_group(PRIM, k, v)
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    out.prim_data = {k: dict(v) for k, v in geo.prim_data.items()}
    out.edge_groups = dict(geo.edge_groups)
    return out
