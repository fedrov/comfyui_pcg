"""
Time operators -- Trail / Time Blend / Retime. They take a geometry sequence and output geometry.

These three are what you reach for immediately in Houdini once "geometry is a function of time":

    Time Blend   interpolate **between two frames** -- render a 24 fps sim at 48 fps, or slow motion
    Trail        stack the previous several frames -- motion trails, trajectory lines, computing velocity fields
    Retime       remap time -- speed changes, reverse playback, time warping with a curve

In this plugin a sequence is just a `list[Geometry]` (the output of For-Each Frame End),
so all three operators are list indexing + attribute interpolation; none of them build topology.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Interpolation requires **the same topology**, and must error early
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Interpolating between two frames presumes "point i is the same point in both frames". With equal point counts but different topology (e.g.
a fuse / sort done in between), the result is a tangle of misplaced pieces -- and **no error**,
it just looks like the sim blew up. So point / vertex / prim counts and the vertex_point and
prim_offset arrays are compared one by one, and any mismatch throws immediately, with the message saying which frame is wrong.

Houdini's Time Blend has this restriction too, its error is just more obscure.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Integer and string attributes are **not interpolated**; they take the nearer frame
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Attributes like id / class / name / piece mean nothing once interpolated: 0.5 of a class is not anything,
and rounding back makes it jump inexplicably in a middle frame. So only float attributes are linearly interpolated; integers,
booleans and strings all take "the nearest frame's value" (t < 0.5 takes the earlier, otherwise the later). Same for groups.

This has a cost: integer attributes jump when t crosses 0.5. But the alternative (interpolate then round)
only moves the jump to 0.25 / 0.75, which is no better and adds one more layer of deception.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, CLASSES, is_string
from . import ops as _ops
from . import channel as _ch

TRAIL_MODES = ("preserve", "connect", "velocity", "connect_mesh")
RETIME_MODES = ("speed", "length", "channel")
RETIME_INTERP = ("hold", "blend")


# ═══════════════════════════════════════════════════════════ topology consistency
def _topo_key(g):
    return (g.npoints, g.nvertices, g.nprims)


def check_same_topology(seq, what="Sequence"):
    """All frames must have the same topology. Throws on mismatch, with the message saying which frame and what differs."""
    if not seq:
        raise ValueError(f"{what} is empty")
    g0 = seq[0]
    for i, g in enumerate(seq[1:], 1):
        if _topo_key(g) != _topo_key(g0):
            raise ValueError(
                f"{what}: frame {i} and frame 0 have different topology: "
                f"points {g.npoints} vs {g0.npoints}, "
                f"vertices {g.nvertices} vs {g0.nvertices}, "
                f"prims {g.nprims} vs {g0.nprims}. "
                f"Time interpolation requires point i to be the same point in every frame -- if there is a "
                f"fuse / sort / delete in between, move it after the time operator.")
        if not (np.array_equal(g.vertex_point, g0.vertex_point)
                and np.array_equal(g.prim_offset, g0.prim_offset)):
            raise ValueError(
                f"{what}: frame {i} has the same point count as frame 0 but **different connectivity**. "
                f"Interpolating that gives a mess of misplaced faces that looks like the sim blew up, "
                f"so this errors right away.")
    return g0


# ═══════════════════════════════════════════════════════════════ interpolation
def lerp_geo(a, b, t):
    """
    Linear interpolation between two frames. Topology is taken from a (already confirmed identical for both frames).

    t may go outside [0,1] -- extrapolation is a legitimate need (predicting the next frame), no clamping.
    When t is exactly 0 or 1 it takes the **direct reuse** path: the output arrays are bitwise identical to the input
    (the same object), without going through a multiply-add. This is not only faster; more importantly
    it makes the criterion "an identity retime must return the input unchanged" hold.
    """
    t = float(t)
    if t == 0.0:
        return a.copy()
    if t == 1.0:
        return b.copy()
    g = a.copy()
    for cls in CLASSES:
        for name in list(a.attribs[cls].keys()):
            va = a.attribs[cls][name]
            vb = b.attribs[cls].get(name)
            if vb is None or vb.shape != va.shape:
                continue                       # attribute present in only one frame: keep a's
            if is_string(va) or va.dtype.kind not in "fc":
                # integer / boolean / string: take the nearer frame, see the module header for why
                if t >= 0.5:
                    g.attribs[cls][name] = vb
                continue
            g.set(cls, name, va + (vb.astype(np.float64) - va) * t,
                  dtype=va.dtype, owned=True)
    if t >= 0.5:                               # groups also take the nearest frame
        g.groups = {c: dict(d) for c, d in b.groups.items()}
        g.edge_groups = dict(b.edge_groups)
    return g


def sample(seq, x, interp="blend", loop=False):
    """
    Take one frame of geometry at the **float frame number** x.

    With loop=True x is taken modulo the sequence length (so 23.5 in a 24-frame sequence interpolates back toward frame 0);
    with loop=False it is clamped to [0, n-1] and holds after the last frame.

    With interp="hold" it takes the nearest integer frame (round), no interpolation at all -- sequences whose topology changes
    (fracture, growth) can only use this mode.
    """
    if interp not in RETIME_INTERP:
        raise ValueError(f"interp must be one of {RETIME_INTERP}")
    n = len(seq)
    if n == 0:
        raise ValueError("The sequence is empty")
    if n == 1:
        return seq[0].copy()
    x = float(x)
    if interp == "hold":
        i = int(np.round(x))
        i = i % n if loop else int(np.clip(i, 0, n - 1))
        return seq[i].copy()
    if loop:
        x = x % n
        i = int(np.floor(x))
        t = x - i
        return lerp_geo(seq[i % n], seq[(i + 1) % n], t)
    x = float(np.clip(x, 0.0, n - 1))
    i = min(int(np.floor(x)), n - 2)
    return lerp_geo(seq[i], seq[i + 1], x - i)


def timeblend(seq, frame, loop=False, interp="blend"):
    """Time Blend SOP: float frame number -> one frame of geometry. blend mode requires the same topology."""
    if interp == "blend":
        check_same_topology(seq)
    return sample(seq, frame, interp, loop)


# ═══════════════════════════════════════════════════════════════ Trail
def _trail_indices(n, index, length, step, loop):
    """
    Frame numbers used by the trail, ordered **earliest to latest**, the last one being the current frame.

    With loop=False out-of-range frames are clamped to 0 (rather than dropped): the trail keeps a constant number of segments, otherwise the trail
    length in the first few frames of the sequence would change frame by frame, looking like it is "growing out".
    """
    idx = [index - k * step for k in range(int(length), -1, -1)]
    if loop:
        return [i % n for i in idx]
    return [int(np.clip(i, 0, n - 1)) for i in idx]


def trail(seq, index=0, length=4, step=1, mode="preserve", loop=False,
          velocity_attrib="v"):
    """
    Trail SOP.

    mode:
        preserve   merge every trail frame as is into one geometry (motion blur, afterimages)
        connect    connect each point's trajectory into an **open polyline** (length+1 points).
                   Houdini calls that mode Connect as Mesh -- on a point cloud it is polylines;
                   on geometry with faces Houdini stitches it into patches, here only polylines: stitching faces needs
                   knowing which edges are outlines, and the purpose of a trail (seeing trajectories) does not need that step.
        velocity   current frame geometry + a v attribute (unit: value/frame).
        connect_mesh  each **edge** sweeps a quad between consecutive frames (what Houdini's Connect as Mesh looks like on geometry
                   with prims): a curve drags out a ribbon, a face's outline drags out a tube wall. Edges shared by two faces
                   are swept only once; a point cloud with no prims has no edges to sweep and falls back to connect's polylines.

    Differencing in velocity mode: with a previous frame it uses the **backward difference** (P[i] − P[i−step]) / step;
    the first frame of the sequence (without loop) degrades to a forward difference. Both are exact for uniform motion, so this
    degradation is not masked in the tests -- what is tested is "under uniform motion v equals the analytic velocity point by point".
    """
    if mode not in TRAIL_MODES:
        raise ValueError(f"Trail mode must be one of {TRAIL_MODES}")
    n = len(seq)
    if n == 0:
        raise ValueError("The sequence is empty")
    step = max(1, int(step))
    length = max(0, int(length))
    idx = _trail_indices(n, int(index), length, step, loop)
    cur = seq[idx[-1]]

    if mode == "preserve":
        # also write a trailframe attribute so downstream can fade by it
        parts = []
        for k, i in enumerate(idx):
            g = seq[i].copy()
            if g.npoints:
                g.set(POINT, "trailframe",
                      np.full((g.npoints, 1), float(k - length), np.float32),
                      owned=True)
            parts.append(g)
        return _ops.merge(*parts) if len(parts) > 1 else parts[0]

    if mode in ("connect", "connect_mesh"):
        sub = [seq[i] for i in idx]
        check_same_topology(sub, "Trail frames")
        np0 = cur.npoints
        if np0 == 0:
            return Geometry(0)
        m = len(idx)
        # point layout: trajectory first (m frames of point 0, m frames of point 1 ...), so each polyline's
        # points form a contiguous run and the topology is an arithmetic sequence -- no per-point list building
        P = np.stack([np.asarray(g.get(POINT, "P"), np.float32) for g in sub],
                     axis=1).reshape(np0 * m, 3)
        g = Geometry(np0 * m)
        g.set(POINT, "P", P, owned=True)
        edges = _prim_edges(cur) if mode == "connect_mesh" else np.zeros((0, 2), np.int64)
        if len(edges) and m >= 2:
            # the index of point p at frame f is p·m + f. Quad of edge (a, b) between f -> f+1: a_f, b_f, b_f+1, a_f+1
            a, b = edges[:, 0][:, None] * m, edges[:, 1][:, None] * m
            f = np.arange(m - 1)[None, :]
            quads = np.stack([a + f, b + f, b + f + 1, a + f + 1], -1).reshape(-1, 4)
            g.set_topology(quads.reshape(-1).astype(np.int32),
                           np.arange(len(quads) + 1, dtype=np.int32) * 4)
        else:                              # connect, or no edges / only one frame to sweep: one polyline per point
            g.set_topology(np.arange(np0 * m, dtype=np.int32),
                           np.arange(np0 + 1, dtype=np.int32) * m,
                           prim_closed=np.zeros(np0, bool))
        # normalized parameter along the trajectory: 0 is the earliest frame, 1 the current one. Used for fading / thickening
        u = np.tile(np.linspace(0.0, 1.0, m, dtype=np.float32), np0)
        g.set(POINT, "trailu", u.reshape(-1, 1), owned=True)
        return g

    # velocity
    if len(idx) >= 2 and idx[-2] != idx[-1]:
        a, b = seq[idx[-2]], cur
    elif n > 1 and not loop and idx[-1] == 0:
        a, b = cur, seq[min(step, n - 1)]      # first frame: forward difference
    else:
        a, b = cur, cur
    check_same_topology([a, b], "The two frames used for velocity")
    g = cur.copy()
    if g.npoints:
        Pa = np.asarray(a.get(POINT, "P"), np.float64)
        Pb = np.asarray(b.get(POINT, "P"), np.float64)
        g.set(POINT, velocity_attrib or "v", (Pb - Pa) / float(step),
              dtype=np.float32, owned=True)
    return g


def _prim_edges(geo):
    """Edges of all prims (closed ones include the closing edge), deduplicated as undirected, keeping the direction of first occurrence. (E,2) point numbers."""
    out, seen = [], set()
    for k in range(geo.nprims):
        pts = geo.prim_points(k)
        n = len(pts)
        for i in range(n if geo.prim_closed[k] else n - 1):
            a, b = int(pts[i]), int(pts[(i + 1) % n])
            key = (min(a, b), max(a, b))
            if a != b and key not in seen:
                seen.add(key)
                out.append((a, b))
    return np.asarray(out, np.int64).reshape(-1, 2)


# ══════════════════════════════════════════════════════════════ Retime
def retime_map(n, frames=None, mode="speed", speed=1.0, start=0.0,
               keys=_ch.EXAMPLE, default_interp="cubic",
               extrapolate="hold"):
    """
    Output frame -> **source frame number (float)** mapping table. Returns (frames,) float64.

    Three modes:
        speed    src = start + i·speed. Negative speed plays in reverse, 0.5 is half speed
        length   spread the frames output frames evenly over the whole source sequence (pure duration change)
        channel  src = the value of a keyframe channel at i -- time warping.
                 This is Houdini's "retime with a curve" approach, and the only one of these modes
                 that can "pause and then continue"
    """
    if mode not in RETIME_MODES:
        raise ValueError(f"Retime mode must be one of {RETIME_MODES}")
    if n <= 0:
        raise ValueError("The sequence is empty")
    if mode == "speed":
        cnt = int(frames) if frames else max(
            1, int(np.ceil(n / max(abs(float(speed)), 1e-6))))
        return float(start) + np.arange(cnt, dtype=np.float64) * float(speed)
    if mode == "length":
        cnt = max(1, int(frames) if frames else n)
        if cnt == 1:
            return np.array([float(start)])
        return np.linspace(0.0, n - 1.0, cnt)
    cnt = max(1, int(frames) if frames else n)
    return _ch.eval_spec(keys, np.arange(cnt, dtype=np.float64),
                         default_interp, extrapolate)


def retime(seq, frames=None, mode="speed", speed=1.0, start=0.0,
           keys=_ch.EXAMPLE, default_interp="cubic", extrapolate="hold",
           interp="blend", loop=False):
    """Retime SOP: sequence -> new sequence. interp="blend" mode requires the same topology."""
    if not seq:
        raise ValueError("The sequence is empty")
    if interp == "blend":
        check_same_topology(seq)
    src = retime_map(len(seq), frames, mode, speed, start, keys,
                     default_interp, extrapolate)
    return [sample(seq, x, interp, loop) for x in src]
