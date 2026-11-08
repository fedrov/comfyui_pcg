"""
Trace SOP -- image iso-contours -> curves.

Mirrors Houdini's Trace. Use: turn AI line art / masks / silhouettes into **editable geometry**
(extrude into solids, sweep into tubes, use as cutting curves), instead of only applying them as textures. This is the one step on the "image ->
geometry" path that brings **topology** back too -- Attribute from Map only brings values.

The algorithm is **Marching Squares**: interpolate by threshold on the lattice formed by pixel centers; each 2x2
cell looks up 0/1/2 segments in a table, the segments are chained end to end into polylines, and finally simplified with RDP.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Two places that are easy to get wrong
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1) **Saddles (case 5 / 10) are ambiguous.** When two diagonal corners are above the threshold and the other two below,
   the two segments can connect as "\\\\ //" or as "// \\\\" -- the former connects the two corners, the latter
   separates them. Picking one at random is not "slightly off", it is **topologically wrong**: two blobs that should be apart get stuck
   together, or one closed loop splits into two.

   Here the cell center value (average of the four corners) decides: if the center is also above the threshold, the two diagonal blobs are
   connected. This is a simplified asymptotic decider, exact for bilinear fields.

2) **Orientation must be consistent.** Convention: walking along the curve, **the side above the threshold is on the left**. So outer outlines
   are counter-clockwise (positive signed area), holes clockwise (negative), and the signed areas of all loops add up
   to exactly the area of the "above threshold" region. Downstream extrusion, inside/outside tests and face filling all rely on
   this; with random orientation PolyFill / PolyExtrude come out inside out.

   The in/out edge table for the 16 cases was derived case by case from "left side is inside", and is verified in the tests with an annulus:
   the signed areas of the two loops must be +πR² and −πr².

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Why chaining can rely on a single table
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Iso points only land on **cell edges**, with at most one point per cell edge. So number every cell edge, and a
directed segment is "from cell edge a to cell edge b"; neighbouring cells share that cell edge, so the `next[a] = b`
table is itself the linked list of the whole curve. No geometric "find the nearest point" is needed -- that is the main source of bugs
in implementations of this kind (float equality, tolerances, duplicate points).

Open curves (touching the image border) and closed loops are told apart by "has a predecessor or not": cell edges with no predecessor start open curves,
and the remaining unvisited ones belong to closed loops.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Performance
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Table lookup and interpolation are fully vectorized; the chaining step is a Python while loop. The number of iso points is O(perimeter)
not O(pixels); complex 1024² line art gives a few tens of thousands of points, measured at around 0.1 s. Going faster would need
a parallel prefix (pointer jumping), which would make a simple thing complicated, not worth it.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM
from .cop.core import CopImage, DEFAULT_LAYER

PLANES = ("xy", "xz", "zx")

# ── Marching Squares lookup table ───────────────────────────────────────────────
# corners: c0=(y,x) c1=(y,x+1) c2=(y+1,x+1) c3=(y+1,x)
# edges: 0=bottom(c0-c1) 1=right(c1-c2) 2=top(c2-c3) 3=left(c3-c0)
# case = b0 | b1<<1 | b2<<2 | b3<<3, b_i = (corner value >= threshold)
# each entry is a number of (in edge, out edge) pairs, oriented so that "the side above the threshold is on the left"
_CASES = {
    0:  [],
    1:  [(0, 3)],
    2:  [(1, 0)],
    3:  [(1, 3)],
    4:  [(2, 1)],
    6:  [(2, 0)],
    7:  [(2, 3)],
    8:  [(3, 2)],
    9:  [(0, 2)],
    11: [(1, 2)],
    12: [(3, 1)],
    13: [(0, 1)],
    14: [(3, 0)],
    15: [],
}
# saddle: center above threshold -> diagonals connected, otherwise separated
_SADDLE_5_JOIN = [(0, 1), (2, 3)]
_SADDLE_5_SPLIT = [(0, 3), (2, 1)]
_SADDLE_10_JOIN = [(3, 0), (1, 2)]
_SADDLE_10_SPLIT = [(1, 0), (3, 2)]


def _layer_numpy(image, layer, channel):
    if isinstance(image, CopImage):
        a = image.need(layer)
        if not isinstance(a, np.ndarray):
            a = image.to_device("numpy").need(layer)
    else:
        a = np.asarray(image)
        if a.ndim == 2:
            a = a[:, :, None]
    a = np.asarray(a, np.float64)
    return a[:, :, int(channel) % a.shape[2]]


def _edge_points(f, thr):
    """
    Position of the iso point on each cell edge (lattice coordinates, unit = 1 pixel).

    Returns (hx, hy, vx, vy, hcross, vcross). Horizontal edge h[y,x] joins (y,x)-(y,x+1),
    vertical edge v[y,x] joins (y,x)-(y+1,x).
    """
    H, W = f.shape
    a, b = f[:, :-1], f[:, 1:]                       # both ends of horizontal edges
    den = b - a
    t = np.where(np.abs(den) > 0, (thr - a) / np.where(den == 0, 1.0, den), 0.5)
    hx = np.arange(W - 1)[None, :] + np.clip(t, 0.0, 1.0)
    hy = np.broadcast_to(np.arange(H)[:, None].astype(np.float64),
                         (H, W - 1)).copy()
    hcross = (a >= thr) != (b >= thr)

    a2, b2 = f[:-1, :], f[1:, :]                     # both ends of vertical edges
    den2 = b2 - a2
    t2 = np.where(np.abs(den2) > 0,
                  (thr - a2) / np.where(den2 == 0, 1.0, den2), 0.5)
    vy = np.arange(H - 1)[:, None] + np.clip(t2, 0.0, 1.0)
    vx = np.broadcast_to(np.arange(W)[None, :].astype(np.float64),
                         (H - 1, W)).copy()
    vcross = (a2 >= thr) != (b2 >= thr)
    return hx, hy, vx, vy, hcross, vcross


def contours(f, threshold=0.5):
    """
    Marching Squares. Returns (point coordinates (M,2) in lattice units, chains list[(list[int], closed)]).

    The x coordinate is along columns and y along rows, **y up** (COP row 0 is at the bottom), so
    the derivation of "left side is inside" matches the orientation seen on screen.
    """
    f = np.asarray(f, np.float64)
    H, W = f.shape
    if H < 2 or W < 2:
        return np.zeros((0, 2)), []
    thr = float(threshold)
    hx, hy, vx, vy, hcross, vcross = _edge_points(f, thr)

    nh = H * (W - 1)                                  # horizontal edges numbered 0..nh-1
    # vertical edges numbered nh + y*W + x

    b = (f >= thr)
    b0 = b[:-1, :-1]
    b1 = b[:-1, 1:]
    b2 = b[1:, 1:]
    b3 = b[1:, :-1]
    case = (b0.astype(np.int64) | (b1.astype(np.int64) << 1)
            | (b2.astype(np.int64) << 2) | (b3.astype(np.int64) << 3))
    center = 0.25 * (f[:-1, :-1] + f[:-1, 1:] + f[1:, 1:] + f[1:, :-1])
    cin = center >= thr

    ch, cw = case.shape
    yy, xx = np.meshgrid(np.arange(ch), np.arange(cw), indexing="ij")

    def eid(edge, y, x):
        """Global index of edge number `edge` of cell (y,x)."""
        if edge == 0:
            return y * (W - 1) + x
        if edge == 2:
            return (y + 1) * (W - 1) + x
        if edge == 3:
            return nh + y * W + x
        return nh + y * W + (x + 1)

    ins, outs = [], []
    for c in range(16):
        m = (case == c)
        if not m.any():
            continue
        if c == 5:
            groups = [(m & cin, _SADDLE_5_JOIN), (m & ~cin, _SADDLE_5_SPLIT)]
        elif c == 10:
            groups = [(m & cin, _SADDLE_10_JOIN), (m & ~cin, _SADDLE_10_SPLIT)]
        else:
            groups = [(m, _CASES[c])]
        for mm, segs in groups:
            if not segs or not mm.any():
                continue
            y, x = yy[mm], xx[mm]
            for e_in, e_out in segs:
                ins.append(eid(e_in, y, x))
                outs.append(eid(e_out, y, x))
    if not ins:
        return np.zeros((0, 2)), []
    ein = np.concatenate(ins)
    eout = np.concatenate(outs)

    n_edges = nh + (H - 1) * W
    nxt = np.full(n_edges, -1, np.int64)
    nxt[ein] = eout
    has_prev = np.zeros(n_edges, bool)
    has_prev[eout] = True

    # iso point coordinates (indexed by global edge number)
    pts = np.empty((n_edges, 2))
    pts[:nh, 0] = hx.reshape(-1)
    pts[:nh, 1] = hy.reshape(-1)
    pts[nh:, 0] = vx.reshape(-1)
    pts[nh:, 1] = vy.reshape(-1)

    used = np.zeros(n_edges, bool)
    live = nxt >= 0
    paths = []

    def walk(start, closed):
        chain = []
        e = start
        while e >= 0 and not used[e]:
            used[e] = True
            chain.append(e)
            e = nxt[e]
        return chain

    # open curves: have a successor but no predecessor
    for s in np.nonzero(live & ~has_prev)[0]:
        if used[s]:
            continue
        ch_ = walk(int(s), False)
        if len(ch_) >= 2:
            paths.append((ch_, False))
    # everything left is a closed loop
    for s in np.nonzero(live & ~used)[0]:
        if used[s]:
            continue
        ch_ = walk(int(s), True)
        if len(ch_) >= 3:
            paths.append((ch_, True))
    return pts, paths


# ═══════════════════════════════════════════════════════════════ simplification
def _rdp_open(P, tol):
    """RDP, iterative (recursion would blow the stack on long chains of tens of thousands of points). Returns the kept indices."""
    n = len(P)
    if n <= 2 or tol <= 0:
        return np.arange(n)
    keep = np.zeros(n, bool)
    keep[0] = keep[n - 1] = True
    stack = [(0, n - 1)]
    t2 = tol * tol
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = P[i], P[j]
        d = b - a
        L2 = float(d @ d)
        w = P[i + 1:j] - a
        if L2 > 0:
            t = np.clip((w @ d) / L2, 0.0, 1.0)
            perp = w - t[:, None] * d
        else:
            perp = w
        dist2 = (perp * perp).sum(1)
        k = int(np.argmax(dist2))
        if dist2[k] > t2:
            m = i + 1 + k
            keep[m] = True
            stack.append((i, m))
            stack.append((m, j))
    return np.nonzero(keep)[0]


def _rdp_closed(P, tol):
    """
    RDP for closed loops. First fix the "farthest pair" as two anchors, then split the loop into two open chains and run each once.

    Running the open-chain version directly on a closed loop uses the first point as anchor, so the shape near the first point can never be simplified -- a
    perfect circle often keeps a spurious spike at its start point.
    """
    n = len(P)
    if n <= 3 or tol <= 0:
        return np.arange(n)
    d = np.linalg.norm(P - P[0], axis=1)
    a = int(np.argmax(d))
    d2 = np.linalg.norm(P - P[a], axis=1)
    b = int(np.argmax(d2))
    i, j = (a, b) if a < b else (b, a)
    if j - i < 2 or (n - j) + i < 2:
        return np.arange(n)
    k1 = _rdp_open(P[i:j + 1], tol) + i
    tail = np.concatenate([np.arange(j, n), [i]])
    k2 = tail[_rdp_open(P[tail], tol)]
    return np.unique(np.concatenate([k1, k2[k2 != i]]))


# ═══════════════════════════════════════════════════════════════ main function
# ── pcg100 s7: added against Houdini Trace (defaults = old behaviour)
CHANNEL_MODES = ("index", "mono", "red", "green", "blue", "alpha")
BOUNDARIES = ("none", "black", "white", "same_as_00", "custom")


def _channel_field(image, layer, channel, mode):
    """
    index = old behaviour (channel number `channel`); mono = luminance (Rec.709: 0.2126 R + 0.7152 G + 0.0722 B,
    channel 0 when there are fewer than three channels -- the docs only say "brightness", the weights are our choice); red / green / blue = channel 0 / 1 / 2
    (error if missing); alpha = channel 3, all 1 if missing (docs: "alpha, used if present").
    """
    if mode == "index":
        return _layer_numpy(image, layer, channel)
    if isinstance(image, CopImage):
        arr = image.need(layer)
        if not isinstance(arr, np.ndarray):
            arr = image.to_device("numpy").need(layer)
    else:
        arr = np.asarray(image)
    arr = np.asarray(arr, np.float64)
    if arr.ndim == 2:
        arr = arr[:, :, None]
    C = arr.shape[2]
    if mode == "mono":
        if C < 3:
            return arr[:, :, 0]
        return 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]
    if mode == "alpha":
        return arr[:, :, 3] if C >= 4 else np.ones(arr.shape[:2])
    k = {"red": 0, "green": 1, "blue": 2}[mode]
    if k >= C:
        raise ValueError(f"Channel = {mode}, but this layer has only {C} channels")
    return arr[:, :, k]


def trace(image, layer=DEFAULT_LAYER, channel=0, threshold=0.5,
          invert=False, simplify=0.5, min_points=3, min_length=0.0,
          close_open=False, plane="xy", size=2.0, center_x=0.0,
          center_y=0.0, center_z=0.0, keep_aspect=True,
          add_uv=True, uv_attrib="uv", height=0.0,
          channel_mode="index", boundary="none", boundary_value=0.0,
          resample=False, step_size=0.1, rotate=(0.0, 0.0, 0.0),
          scale=(1.0, 1.0, 1.0)):
    """
    Iso-contour tracing. Outputs polyline geometry (closed loops have prim_closed=True).

    simplify is in **pixels** (the RDP tolerance is computed in lattice coordinates), 0 = no simplification. Pixels
    rather than world units, because it means "how far it may deviate from the original image" -- that intent
    should not change with the output size.

    min_length is in world units, used to throw away small fragment loops caused by noise.

    add_uv=True writes each point's original uv (0-1) as a point attribute -- the traced curve still
    knows where on the image it came from, so downstream can sample colors with Attribute from Map.
    """
    if channel_mode not in CHANNEL_MODES:
        raise ValueError(f"Channel must be one of {CHANNEL_MODES}")
    if boundary not in BOUNDARIES:
        raise ValueError(f"Boundary Color must be one of {BOUNDARIES}")
    f = _channel_field(image, layer, channel, channel_mode)
    H, W = f.shape
    pad = boundary != "none"
    if pad:
        # Boundary Color: treat outside the image as this value (pad one ring of pixels). Shapes touching the image border then all close --
        # Houdini's Trace outputs faces, never open curves along the border. "Same as (0,0)" guesses the background from pixel (0,0) (COP
        # row 0 is at the bottom, i.e. the lower-left corner)
        bv = {"black": 0.0, "white": 1.0, "same_as_00": float(f[0, 0]),
              "custom": float(boundary_value)}[boundary]
        f = np.pad(f, 1, constant_values=bv)
    if invert:
        f = -f
        thr = -float(threshold)
    else:
        thr = float(threshold)
    pts, paths = contours(f, thr)
    if pad:
        pts = pts - 1.0                              # shift back by the padded ring: lattice coordinates are still those of the original image
    if not paths:
        return Geometry()

    # lattice coordinates -> uv (0-1). Lattice point (y,x) is at the pixel center, uv = ((x+0.5)/W, (y+0.5)/H)
    uv_all = np.stack([(pts[:, 0] + 0.5) / W, (pts[:, 1] + 0.5) / H], 1)

    sx = sy = float(size)
    if keep_aspect:
        if W >= H:
            sy = float(size) * H / W
        else:
            sx = float(size) * W / H
    tol_uv = float(simplify)      # RDP is done in lattice units

    chains, closed_flags = [], []
    for chain, closed in paths:
        idx = np.asarray(chain, np.int64)
        Q = pts[idx]
        if tol_uv > 0:
            k = _rdp_closed(Q, tol_uv) if closed else _rdp_open(Q, tol_uv)
            idx = idx[k]
        if len(idx) < max(2, int(min_points)):
            continue
        chains.append((idx, closed))
        closed_flags.append(closed)

    if not chains:
        return Geometry()

    # assembly: each chain gets its own points (iso points are shared by neighbouring cells, but a point belongs to only one chain)
    flat = np.concatenate([c for c, _ in chains])
    sizes = np.array([len(c) for c, _ in chains], np.int64)
    uv = uv_all[flat]
    px = (uv[:, 0] - 0.5) * sx
    py = (uv[:, 1] - 0.5) * sy
    z = np.full(len(uv), float(height))
    if plane == "xy":
        P = np.stack([px + center_x, py + center_y, z + center_z], 1)
    elif plane == "xz":
        P = np.stack([px + center_x, z + center_y, -py + center_z], 1)
    else:                                           # zx
        P = np.stack([z + center_x, py + center_y, px + center_z], 1)

    rot = np.asarray(rotate, np.float64)
    scl = np.asarray(scale, np.float64)
    xf = bool(rot.any() or (scl != 1.0).any())
    if xf:
        # Transform tab: scale, then rotate (Rx Ry Rz) around the image center, the center staying at center
        from .ops import euler_matrix
        Rm = euler_matrix(*rot).astype(np.float64)
        ctr = np.array([center_x, center_y, center_z], np.float64)
        P = ((P - ctr) * scl) @ Rm.T + ctr

    g = Geometry.from_points(P.astype(np.float32))
    off = np.concatenate([[0], np.cumsum(sizes)]).astype(np.int32)
    cl = np.array([c for _, c in chains], bool)
    if close_open:
        cl[:] = True
    g.set_topology(np.arange(len(P), dtype=np.int32), off, cl)

    if add_uv and str(uv_attrib).strip():
        g.set(POINT, str(uv_attrib).strip(),
              uv.astype(np.float32), owned=True)

    # prim attributes: perimeter and signed area (only meaningful for closed loops, 0 for open curves)
    L = np.zeros(len(chains))
    A = np.zeros(len(chains))
    for i, (c, closed) in enumerate(chains):
        Q = P[off[i]:off[i + 1], :]
        d = np.diff(Q, axis=0)
        L[i] = float(np.linalg.norm(d, axis=1).sum())
        if closed:
            L[i] += float(np.linalg.norm(Q[0] - Q[-1]))
            u = uv_all[c][:, 0] * sx
            v = uv_all[c][:, 1] * sy
            A[i] = 0.5 * float(np.sum(u * np.roll(v, -1)
                                      - np.roll(u, -1) * v))
    if xf and (scl != 1.0).any():
        # signed area scales too: multiply by the scale of the two axes of the image plane (signed -- mirroring flips orientation);
        # rotation does not change area
        ax = {"xy": (0, 1), "xz": (0, 2), "zx": (1, 2)}[plane]
        A = A * float(scl[ax[0]] * scl[ax[1]])
    g.set(PRIM, "perimeter", L[:, None].astype(np.float32), owned=True)
    g.set(PRIM, "area", A[:, None].astype(np.float32), owned=True)

    if float(min_length) > 0:
        keep = L >= float(min_length)
        if not keep.all():
            g = _keep_prims(g, keep)
    if resample and g.nprims:
        # Resample Shapes: resample at equal lengths by Step Size (world units); perimeter / area keep the original outline's values
        from .ops import resample as _resample
        if float(step_size) <= 0:
            raise ValueError("Step Size must be > 0")
        g = _resample(g, by_length=True, length=float(step_size))
    return g


def _keep_prims(g, keep):
    """Keep only the selected prims (points follow). Small helper, not worth putting in core."""
    idx = np.nonzero(keep)[0]
    if not len(idx):
        return Geometry()
    off = g.prim_offset
    blocks = [np.arange(off[i], off[i + 1]) for i in idx]
    corner = np.concatenate(blocks)
    pt = g.vertex_point[corner]
    out = Geometry(len(pt))
    for k, v in g.attribs[POINT].items():
        out.set(POINT, k, v[pt], owned=True)
    sizes = np.array([len(b) for b in blocks], np.int64)
    out.set_topology(np.arange(len(pt), dtype=np.int32),
                     np.concatenate([[0], np.cumsum(sizes)]).astype(np.int32),
                     g.prim_closed[idx])
    for k, v in g.attribs[PRIM].items():
        out.set(PRIM, k, v[idx], owned=True)
    return out
