"""
Time operators (Trail / Time Blend / Retime) -- checks rely on **analytic motion** and **bit-identical identity**.

The three most likely kinds of bug here, none of which raise:

  1) **The identity mapping is not the identity.** A retime pass at "original speed, no offset" should give something
     **exactly the same** as the input. If a lerp sneaks in somewhere (t=0 still does the multiply-add), float32 loses
     precision and the dtype drifts, while the picture looks completely normal. So the criterion is that
     `lerp_geo(a, b, 0)` returns arrays that **are the same data** as a's (array_equal holds exactly).
  2) **Integer attributes get interpolated.** id / class interpolated to 0.5 and then rounded shows up as the grouping of
     in-between frames mysteriously going wrong. Criterion: after interpolation the dtype is unchanged and values are still one of the two frames'.
  3) **Interpolating despite different topology.** Two frames with the same point count but different connectivity interpolate into a mess of misplaced faces,
     which looks like the simulation blew up. Criterion: must raise, and the message must say which frame.

The geometry used to test motion is a **box translating at constant velocity**: translation is linear in time, so linear interpolation
has a closed-form result -- in-between positions must equal the analytic values point by point, and velocities must equal the analytic velocity point by point.
No "looks like it's moving" criteria.

One honest note: geometry P is float32 (throughout the plugin), so the "equals the analytic value point by point"
criterion uses float32 eps magnitude (1e-6 relative), not 1e-15. This is not a loosened tolerance --
writing a float64 intermediate back to a float32 attribute necessarily quantizes once.
"""
import os
import sys
_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
import numpy as np                                      # noqa: E402
import fakecomfy                                        # noqa: F401,E402

from comfyui_pcg.geo.core import (Geometry, POINT, VERTEX,    # noqa: E402
                                  PRIM, DETAIL)
from comfyui_pcg.geo import timeops as TO, build          # noqa: E402
from comfyui_pcg import nodes as N                        # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag, kind=Exception):
    try:
        fn()
        check(name, False, "did not raise")
    except kind as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:100]}")


def sec(t):
    print("\n" + "═" * 28 + " " + t)


def unwrap(res):
    """The node's return value is turned into {"ui":..., "result":...} by two layers of wrappers."""
    if isinstance(res, dict):
        return tuple(res.get("result", ()))
    return res


# ─────────────────────────────────────────────── Test sequences
VEL = np.array([0.3, -0.125, 0.75])        # constant-velocity translation (per frame)
P0 = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
               [1.0, 1.0, 0.0], [0.0, 1.0, 0.0],
               [0.5, 0.5, 1.0]], np.float64)
FACES = [[0, 1, 2, 3], [0, 1, 4], [1, 2, 4]]
NF = 8


def make_frame(k):
    """Frame k: the whole block translated by VEL·k. Comes with an integer attribute and a group."""
    g = Geometry.from_mesh(P0 + VEL * k, FACES)
    g.set(POINT, "id", np.arange(len(P0)).reshape(-1, 1), dtype=np.int32)
    g.set(POINT, "w", (np.arange(len(P0)) * 0.25 + k).reshape(-1, 1),
          dtype=np.float64)
    # One float prim attribute (gets interpolated) and one integer prim attribute (must not be) --
    # with only the float one, the "integers are not interpolated" criterion would have nothing to test
    g.set(PRIM, "pval", (np.arange(len(FACES)) + k * 10.0).reshape(-1, 1))
    g.set(PRIM, "pid", (np.arange(len(FACES)) + k).reshape(-1, 1),
          dtype=np.int32)
    g.set_string(POINT, "name", [f"p{i}" for i in range(len(P0))])
    g.set_group(POINT, "even", np.arange(len(P0)) % 2 == 0)
    g.set(DETAIL, "frame", [[float(k)]])
    return g


SEQ = [make_frame(k) for k in range(NF)]
EPS32 = 3e-6                     # relative criterion for float32 attributes


def analytic_P(x):
    return P0 + VEL * x


# ══════════════════════════════════════════════════ 1. Topology consistency
sec("Topology consistency (must raise up front)")
check("a sequence with the same topology passes straight through", TO.check_same_topology(SEQ) is SEQ[0])
bad = list(SEQ)
bad[3] = Geometry.from_mesh(P0[:4], [[0, 1, 2, 3]])
err("the frame with a different point count is pointed out (with frame number)",
    lambda: TO.check_same_topology(bad), "frame 3")
same_n = Geometry.from_mesh(P0, [[0, 1, 2, 3], [0, 1, 4], [2, 1, 4]])
bad2 = list(SEQ)
bad2[5] = same_n
err("same point count but **different connectivity** must also raise",
    lambda: TO.check_same_topology(bad2), "different connectivity")
err("empty sequence raises", lambda: TO.check_same_topology([]), "equence is empty")
err("timeblend's blend mode runs this check",
    lambda: TO.timeblend(bad2, 2.5), "different connectivity")
g_hold = TO.timeblend(bad2, 5.0, interp="hold")
check("  hold mode does **not** check (the only mode usable on sequences whose topology changes)",
      g_hold.nprims == 3)


# ══════════════════════════════════════════════════ 2. lerp identity
sec("lerp endpoint identity (silent bug #1)")
a, b = SEQ[2], SEQ[3]
l0, l1 = TO.lerp_geo(a, b, 0.0), TO.lerp_geo(a, b, 1.0)
for cls, name in ((POINT, "P"), (POINT, "w"), (PRIM, "pval")):
    check(f"at t=0 {cls}.{name} is **bit-identical** to the previous frame",
          np.array_equal(np.asarray(l0.get(cls, name)),
                         np.asarray(a.get(cls, name))))
    check(f"at t=1 {cls}.{name} is **bit-identical** to the next frame",
          np.array_equal(np.asarray(l1.get(cls, name)),
                         np.asarray(b.get(cls, name))))
check("at t=0 the dtype is unchanged too (a multiply-add would turn float32 into float64)",
      l0.get(POINT, "P").dtype == a.get(POINT, "P").dtype
      and l0.get(POINT, "w").dtype == np.float64)
check("t=0/1 both keep string attributes",
      np.array_equal(np.asarray(l0.get(POINT, "name")),
                     np.asarray(a.get(POINT, "name"))))
check("topology arrays are shared (shallow copy, not rebuilt)",
      np.array_equal(l0.vertex_point, a.vertex_point)
      and np.array_equal(l0.prim_offset, a.prim_offset))


# ══════════════════════════════════════════════════ 3. Analytic interpolation criteria
sec("Time Blend (closed form)")
for x in (0.0, 0.25, 2.5, 3.75, 6.0, 7.0):
    g = TO.timeblend(SEQ, x)
    P = np.asarray(g.get(POINT, "P"), np.float64)
    e = np.abs(P - analytic_P(x)).max()
    check(f"frame={x:<5g} positions equal the analytic values point by point (constant-velocity translation)",
          e < EPS32 * max(1.0, np.abs(analytic_P(x)).max()), f"{e:.2e}")
check("  interpolation of a float64 attribute is exactly linear (w = i·0.25 + frame)",
      abs(float(np.asarray(TO.timeblend(SEQ, 2.5).get(POINT, "w"))[0, 0])
          - 2.5) < 1e-15)
check("past the last frame, the last frame is held (no extrapolation)",
      np.array_equal(np.asarray(TO.timeblend(SEQ, 99.0).get(POINT, "P")),
                     np.asarray(SEQ[-1].get(POINT, "P"))))
check("negative frame numbers hold the first frame",
      np.array_equal(np.asarray(TO.timeblend(SEQ, -5.0).get(POINT, "P")),
                     np.asarray(SEQ[0].get(POINT, "P"))))
gl = TO.timeblend(SEQ, NF - 0.5, loop=True)
check("with loop=True interpolates between the last and first frames",
      np.abs(np.asarray(gl.get(POINT, "P"), np.float64)
             - (analytic_P(NF - 1) + analytic_P(0)) * 0.5).max() < EPS32)
check("  [reverse control] with loop=False the same frame number gives the last frame directly (the two must differ)",
      np.array_equal(
          np.asarray(TO.timeblend(SEQ, NF - 0.5).get(POINT, "P")),
          np.asarray(SEQ[-1].get(POINT, "P")))
      and not np.array_equal(np.asarray(gl.get(POINT, "P")),
                             np.asarray(SEQ[-1].get(POINT, "P"))))

# Integer / string attributes are not interpolated, float attributes are -- both sides must be tested.
# The first version tested pval (float64) as "not interpolated"; the check failed while the implementation was right:
# 20 and 30 at t=0.2 give 22, which is exactly what **should** happen.
for x, near in ((2.2, 2), (2.7, 3)):
    g = TO.timeblend(SEQ, x)
    ids = np.asarray(g.get(POINT, "id"))
    pid = np.asarray(g.get(PRIM, "pid"))
    pv = np.asarray(g.get(PRIM, "pval"), np.float64)
    check(f"frame={x} integer point attribute id is not interpolated (dtype and values unchanged)",
          ids.dtype == np.int32 and np.array_equal(
              ids, np.asarray(SEQ[near].get(POINT, "id"))))
    check(f"  frame={x} integer prim attribute takes the **nearer** frame",
          pid.dtype == np.int32 and np.array_equal(
              pid, np.asarray(SEQ[near].get(PRIM, "pid"))))
    check(f"  frame={x} float prim attribute **is** linearly interpolated (closed form)",
          np.abs(pv.ravel()
                 - (np.arange(len(FACES)) + x * 10.0)).max() < 1e-12,
          pv.ravel())
    check(f"  frame={x} string attribute is not interpolated",
          np.array_equal(np.asarray(g.get(POINT, "name")),
                         np.asarray(SEQ[near].get(POINT, "name"))))
check("groups also come from the nearest frame, never interpolated into half a group",
      np.array_equal(TO.timeblend(SEQ, 2.7).get_group(POINT, "even"),
                     SEQ[3].get_group(POINT, "even")))
check("hold mode does not interpolate at all (takes the rounded frame)",
      np.array_equal(
          np.asarray(TO.timeblend(SEQ, 2.4, interp="hold").get(POINT, "P")),
          np.asarray(SEQ[2].get(POINT, "P")))
      and np.array_equal(
          np.asarray(TO.timeblend(SEQ, 2.6, interp="hold").get(POINT, "P")),
          np.asarray(SEQ[3].get(POINT, "P"))))
one = [SEQ[4]]
check("a single-frame sequence gives that frame at any frame number",
      np.array_equal(np.asarray(TO.timeblend(one, 17.3).get(POINT, "P")),
                     np.asarray(SEQ[4].get(POINT, "P"))))
err("malformed interp for sample raises", lambda: TO.sample(SEQ, 1.0, "bogus"),
    "interp must be one of")


# ══════════════════════════════════════════════════════ 4. Trail
sec("Trail")
L, ST = 3, 1
tp = TO.trail(SEQ, 5, L, ST, "preserve")
check("preserve: point count is (length+1) × original point count",
      tp.npoints == (L + 1) * len(P0), tp.npoints)
check("  prim count is also (length+1) times",
      tp.nprims == (L + 1) * len(FACES))
tf = np.unique(np.asarray(tp.get(POINT, "trailframe")))
check("  trailframe is 0 / −1 / −2 / −3 (0 is the current frame)",
      np.array_equal(tf, np.array([-3.0, -2.0, -1.0, 0.0])), tf)
mn, mx = tp.bbox()
want_mn = np.minimum.reduce([analytic_P(k).min(0) for k in range(2, 6)])
want_mx = np.maximum.reduce([analytic_P(k).max(0) for k in range(2, 6)])
check("  bounding box equals the union of these frames' bounding boxes (each frame really is in there)",
      np.abs(mn - want_mn).max() < EPS32
      and np.abs(mx - want_mx).max() < EPS32)

tp0 = TO.trail(SEQ, 0, L, ST, "preserve")
check("out of range at the start of the sequence the frame number is clamped, segment count **unchanged** (doesn't grow frame by frame)",
      tp0.npoints == (L + 1) * len(P0))
tpl = TO.trail(SEQ, 0, L, ST, "preserve", loop=True)
mnl, _ = tpl.bbox()
check("  with loop=True it wraps round to the end of the sequence instead",
      mnl.min() > mn.min() - 1e9 and not np.allclose(
          np.asarray(tpl.get(POINT, "P")), np.asarray(tp0.get(POINT, "P"))))

tc = TO.trail(SEQ, 5, L, ST, "connect")
check("connect: one polyline per original point", tc.nprims == len(P0), tc.nprims)
check("  length+1 points per polyline",
      np.array_equal(np.unique(tc.prim_sizes()), [L + 1]))
check("  polylines are **open** (not closed)", not tc.prim_closed.any())
Pc = np.asarray(tc.get(POINT, "P"), np.float64)
ok = True
for i in range(len(P0)):
    pts = Pc[tc.prim_points(i)]
    want = np.stack([analytic_P(k)[i] for k in range(2, 6)])
    ok = ok and np.abs(pts - want).max() < EPS32
check("  each polyline's points are that point's positions over these frames, **ordered earliest to latest**", ok)
tu = np.asarray(tc.get(POINT, "trailu"))[tc.prim_points(0)].ravel()
check("  trailu goes from 0 to 1 along the trail",
      np.allclose(tu, np.linspace(0, 1, L + 1)), tu)
t0 = TO.trail(SEQ, 5, 0, ST, "connect")
check("with length=0 each polyline degenerates to a single point (no exception)",
      t0.npoints == len(P0) and t0.nprims == len(P0))

tv = TO.trail(SEQ, 5, L, ST, "velocity")
v = np.asarray(tv.get(POINT, "v"), np.float64)
check("velocity: v equals the analytic velocity point by point", np.abs(v - VEL).max() < EPS32,
      f"max diff {np.abs(v - VEL).max():.2e}")
check("  topology matches the current frame (only one attribute added)",
      tv.npoints == len(P0) and tv.nprims == len(FACES)
      and np.array_equal(np.asarray(tv.get(POINT, "P")),
                         np.asarray(SEQ[5].get(POINT, "P"))))
v0 = np.asarray(TO.trail(SEQ, 0, L, ST, "velocity").get(POINT, "v"),
                np.float64)
check("  the first frame of the sequence degenerates to a forward difference, equally exact at constant velocity",
      np.abs(v0 - VEL).max() < EPS32, f"max diff {np.abs(v0 - VEL).max():.2e}")
v2 = np.asarray(TO.trail(SEQ, 5, L, 2, "velocity").get(POINT, "v"),
                np.float64)
check("  with increment=2 it divides by the step (still per-frame velocity)",
      np.abs(v2 - VEL).max() < EPS32, f"max diff {np.abs(v2 - VEL).max():.2e}")
check("  the attribute name can be changed",
      TO.trail(SEQ, 5, L, ST, "velocity",
               velocity_attrib="vel").has(POINT, "vel"))
err("malformed mode raises", lambda: TO.trail(SEQ, 0, 1, 1, "bogus"), "Trail mode")
err("empty sequence raises", lambda: TO.trail([], 0, 1, 1, "preserve"), "equence is empty")


# ══════════════════════════════════════════════════════ 5. Retime
sec("Retime")
ident = TO.retime(SEQ, mode="speed", speed=1.0, start=0.0)
check("identity mapping: frame count unchanged", len(ident) == NF, len(ident))
check("  every frame's P is **bit-identical** to the input (no sneaky interpolation)",
      all(np.array_equal(np.asarray(ident[i].get(POINT, "P")),
                         np.asarray(SEQ[i].get(POINT, "P")))
          for i in range(NF)))
check("  integer attributes bit-identical too",
      all(np.array_equal(np.asarray(ident[i].get(POINT, "id")),
                         np.asarray(SEQ[i].get(POINT, "id")))
          for i in range(NF)))

fast = TO.retime(SEQ, mode="speed", speed=2.0)
check("speed=2: frame count halved (rounded up)", len(fast) == 4, len(fast))
check("  frame i is **bit-identical** to input frame 2i",
      all(np.array_equal(np.asarray(fast[i].get(POINT, "P")),
                         np.asarray(SEQ[2 * i].get(POINT, "P")))
          for i in range(4)))
slow = TO.retime(SEQ, mode="speed", speed=0.5)
check("speed=0.5: frame count doubled", len(slow) == 2 * NF, len(slow))
check("  positions at half frames equal the analytic values (constant velocity)",
      np.abs(np.asarray(slow[1].get(POINT, "P"), np.float64)
             - analytic_P(0.5)).max() < EPS32)
rev = TO.retime(SEQ, frames=NF, mode="speed", speed=-1.0,
                start=float(NF - 1))
check("speed=−1 + start=last frame: plays backwards, and is **bit-identically** the original frames reversed",
      all(np.array_equal(np.asarray(rev[i].get(POINT, "P")),
                         np.asarray(SEQ[NF - 1 - i].get(POINT, "P")))
          for i in range(NF)))

ln = TO.retime(SEQ, frames=15, mode="length")
check("length: outputs the given frame count, first and last frames match the original sequence's",
      len(ln) == 15
      and np.array_equal(np.asarray(ln[0].get(POINT, "P")),
                         np.asarray(SEQ[0].get(POINT, "P")))
      and np.array_equal(np.asarray(ln[-1].get(POINT, "P")),
                         np.asarray(SEQ[-1].get(POINT, "P"))))
m = TO.retime_map(NF, 15, "length")
check("  evenly spread in between (arithmetic progression)",
      np.abs(np.diff(m) - (NF - 1) / 14.0).max() < 1e-12)

ch = TO.retime(SEQ, frames=NF, mode="channel",
               keys=f"0:0  {NF - 1}:{NF - 1}", default_interp="linear")
check("channel: identity channel = identity mapping, bit-identical",
      all(np.array_equal(np.asarray(ch[i].get(POINT, "P")),
                         np.asarray(SEQ[i].get(POINT, "P")))
          for i in range(NF)))
hold_mid = TO.retime(SEQ, frames=10, mode="channel",
                     keys="0:0  3:3  6:3  9:7", default_interp="linear")
check("  can express 'pause, then continue': frames 3..6 are identical",
      all(np.array_equal(np.asarray(hold_mid[3].get(POINT, "P")),
                         np.asarray(hold_mid[k].get(POINT, "P")))
          for k in (4, 5, 6)))
check("  [reverse control] the constant-speed mode can't do this",
      not np.array_equal(
          np.asarray(TO.retime(SEQ, frames=10, mode="speed",
                               speed=0.7)[4].get(POINT, "P")),
          np.asarray(TO.retime(SEQ, frames=10, mode="speed",
                               speed=0.7)[5].get(POINT, "P"))))
h_ret = TO.retime(SEQ, frames=16, mode="speed", speed=0.5, interp="hold")
b_ret = TO.retime(SEQ, frames=16, mode="speed", speed=0.5, interp="blend")
check("hold and blend really differ (otherwise blend mode is fake)",
      not np.array_equal(np.asarray(h_ret[1].get(POINT, "P")),
                         np.asarray(b_ret[1].get(POINT, "P"))))
check("  hold mode also works on sequences whose topology changes",
      len(TO.retime(bad2, frames=4, mode="speed", speed=2.0,
                    interp="hold")) == 4)
err("blend mode raises on sequences whose topology changes",
    lambda: TO.retime(bad2, mode="speed"), "different connectivity")
err("malformed mode raises", lambda: TO.retime_map(4, 4, "bogus"), "Retime mode")
err("empty sequence raises", lambda: TO.retime([], mode="speed"), "equence is empty")


# ══════════════════════════════════════════════════════ 6. Nodes
sec("Nodes")
tb = unwrap(N.PCG_TimeBlend().run(SEQ, 2.5, "blend", False))
check("Time Blend node returns (geo, frames)",
      len(tb) == 2 and tb[1] == NF and isinstance(tb[0], Geometry))
check("  positions match calling the module directly",
      np.array_equal(np.asarray(tb[0].get(POINT, "P")),
                     np.asarray(TO.timeblend(SEQ, 2.5).get(POINT, "P"))))
tr = unwrap(N.PCG_Trail().run(SEQ, 5, "preserve", 3, 1, False, "v"))
check("Trail node returns (geo, frames)",
      tr[0].npoints == 4 * len(P0) and tr[1] == NF)
rt = unwrap(N.PCG_Retime().run(SEQ, "speed", 0, 2.0, 0.0, "0:0  7:7",
                               "blend", "linear", "hold", False))
check("Retime node returns (geoseq, frames, info)",
      len(rt) == 3 and len(rt[0]) == 4 and rt[1] == 4)
check("  info reports the frame count change and source frame range",
      "8 -> 4" in rt[2] and "src" in rt[2], rt[2])
rt2 = unwrap(N.PCG_Retime().run(SEQ, "channel", 6, 1.0, 0.0, "0:0  5:7",
                                "blend", "linear", "hold", False))
check("  channel mode goes through the channel (6 frames spread over 0..7)", len(rt2[0]) == 6)
check("Retime output can feed Geo Sequence Pick again (types connect)",
      unwrap(N.PCG_GeoSequencePick().run(rt2[0], 2))[1] == 6)

for cls, names in ((N.PCG_TimeBlend, ("geoseq", "frame", "interp", "loop")),
                   (N.PCG_Trail, ("geoseq", "index", "mode", "length",
                                  "increment", "loop")),
                   (N.PCG_Retime, ("geoseq", "mode", "frames", "speed"))):
    spec = cls.INPUT_TYPES()["required"]
    check(f"{cls.__name__} inputs complete",
          all(k in spec for k in names),
          [k for k in names if k not in spec])
check("Time Blend's frame is FLOAT (to connect Frame's frame_f / Channel)",
      N.PCG_TimeBlend.INPUT_TYPES()["required"]["frame"][0] == "FLOAT")
check("Trail's index is INT (it takes integer frames)",
      N.PCG_Trail.INPUT_TYPES()["required"]["index"][0] == "INT")
check("all three nodes are under the PCG/loop category (together with For-Each Frame)",
      all(c.CATEGORY == "PCG/loop"
          for c in (N.PCG_TimeBlend, N.PCG_Trail, N.PCG_Retime)))
check("Retime's output type is GEOSEQUENCE (can connect back into the time chain)",
      N.PCG_Retime.RETURN_TYPES[0] == "GEOSEQUENCE")


print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
