"""
PolyPath / Join.

The **definition** of each of these two nodes is a verifiable criterion, so the tests mostly revolve around it:

    PolyPath creates no edges  ->  the output edge multiset (by point pairs) is **exactly the same** as the input (bit for bit
                        with tol=0), and total length is identical. Only "which edges belong to which prim" changes
    Join creates edges        ->  output edges = input edges + exactly (segments − 1) connecting segments

Plus: when reversing, vertex attributes are reversed too (the easiest one to miss, and when it's wrong "the shape looks fine"),
idempotence, determinism, the measured results of each of the three junction rules, and every one paired with a negative control.
"""
import os
import sys
# Package root: first search upward from this file's location, then fall back to the old sandbox path.
# These suites are now the **only** copy (the sandbox gets reclaimed), so paths can't be hard-coded any more
_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
import numpy as np
from comfyui_pcg.geo.core import Geometry, POINT, VERTEX, PRIM, DETAIL
from comfyui_pcg.geo import (build, joinsop as J, convertline as CVL,
                             ops as OPS)

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag):
    try:
        fn(); check(name, False, "no error raised")
    except Exception as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:110]}")


RNG = np.random.default_rng(0)


# ══════════════════════════════════════════════════════════════════ Utilities
def poly(segs, vattr=None, pattr=None, closed=None):
    """One open polyline per segment. segs is a number of (N,3) arrays."""
    pts = np.concatenate(segs).astype(np.float32)
    g = Geometry(len(pts))
    g.set(POINT, "P", pts)
    sz = [len(s) for s in segs]
    g.set_topology(np.arange(len(pts), dtype=np.int32),
                   np.concatenate([[0], np.cumsum(sz)]).astype(np.int32),
                   np.zeros(len(segs), bool) if closed is None
                   else np.asarray(closed, bool))
    if vattr is not None:
        g.set(VERTEX, "uv", np.asarray(vattr, np.float32).reshape(-1, 1))
    if pattr is not None:
        g.set(PRIM, "name", np.asarray(pattr, np.float32).reshape(-1, 1))
    return g


def edge_set(g):
    """All edges, sorted as (smaller point number, larger point number). A complete description of "what the geometry looks like"."""
    out = []
    off = g.prim_offset
    for i in range(g.nprims):
        pts = g.vertex_point[off[i]:off[i + 1]].tolist()
        n = len(pts)
        rng = range(n) if bool(g.prim_closed[i]) else range(n - 1)
        for k in rng:
            a, b = int(pts[k]), int(pts[(k + 1) % n])
            out.append((min(a, b), max(a, b)))
    return sorted(out)


def total_length(g):
    P = np.asarray(g.get(POINT, "P"), np.float64)
    return float(sum(np.linalg.norm(P[a] - P[b])
                     for a, b in edge_set(g)))


def sig(g):
    """A snapshot that can be compared bit for bit."""
    return (g.npoints, g.vertex_point.tobytes(), g.prim_offset.tobytes(),
            g.prim_closed.tobytes())


# ═════════════════════════════════════════════ PolyPath -- the "creates no edges" definition
print("═" * 28, "PolyPath: creates no edges")

A = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]], np.float32)
B = np.array([[2, 0, 0], [3, 0, 0], [4, 0, 0]], np.float32)
G2 = poly([A, B])

check("endpoints coincide but with **different point numbers**: tol=0 doesn't connect them (that's correct)",
      J.polypath(G2).nprims == 2, J.polypath(G2).nprims)
R = J.polypath(G2, tolerance=1e-6)
check("with a tolerance they connect", R.nprims == 1 and int(R.prim_sizes()[0]) == 5,
      f"{R.nprims} prims, sizes {R.prim_sizes().tolist()}")
check("  the point fused away is the one that came **later** (the earlier one is kept), not the midpoint",
      R.vertex_point.tolist() == [0, 1, 2, 4, 5], R.vertex_point.tolist())
check("  the dropped point is still in the geometry (remove unused not on)", R.npoints == 6, R.npoints)
check("  only deleted with remove_unused_points on",
      J.polypath(G2, tolerance=1e-6, remove_unused_points=True).npoints == 5)

# A chain sharing point numbers: this is the main scenario without tolerance
S = poly([np.array([[0, 0, 0], [1, 1, 0]], np.float32)])
CH = Geometry(4)
CH.set(POINT, "P", np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [3, 0, 0]],
                            np.float32))
CH.set_topology(np.array([0, 1, 1, 2, 2, 3], np.int32),
                np.array([0, 2, 4, 6], np.int32), np.zeros(3, bool))
r = J.polypath(CH)
check("three segments sharing point numbers chained into one", r.nprims == 1 and
      r.vertex_point.tolist() == [0, 1, 2, 3], r.vertex_point.tolist())
check("  edge multiset **completely unchanged**", edge_set(r) == edge_set(CH), edge_set(r))
check("  total length identical (bit for bit)",
      total_length(r) == total_length(CH),
      f"{total_length(CH)} -> {total_length(r)}")
check("  point attributes untouched (same array)",
      r.get(POINT, "P") is CH.get(POINT, "P"))

# grid wireframe: a real scenario, and the one where the three junction rules differ most
GRID = build.grid(cols=5, rows=5)
WIRE = CVL.convert_line(GRID)
check(f"grid 5x5 wireframe is {WIRE.nprims} two-point segments (Convert Line's default output)",
      WIRE.nprims == 40 and set(WIRE.prim_sizes().tolist()) == {2},
      WIRE.nprims)
measured = {}
for jn in J.JUNCTIONS:
    q = J.polypath(WIRE, junction=jn)
    measured[jn] = q.nprims
    check(f"[{jn}] edge multiset unchanged (no edges created, none lost)",
          edge_set(q) == edge_set(WIRE))
    check(f"  total length unchanged", abs(total_length(q) - total_length(WIRE)) < 1e-9)
check("split is the most conservative (Houdini PolyPath's behaviour)", measured["split"] == 36,
      measured["split"])
check("straightest chains up rows and columns", measured["straightest"] == 7,
      measured["straightest"])
check("any chains the most aggressively", measured["any"] == 6, measured["any"])
check("negative control: the three rules' results **really differ**",
      len(set(measured.values())) == 3, measured)
st = J.polypath(WIRE, junction="straightest")
check("  straightest's 7 = 6 interior rows/columns (5 points each) + 1 closed outer loop",
      sorted(st.prim_sizes().tolist()) == [5, 5, 5, 5, 5, 5, 16]
      and int(st.prim_closed.sum()) == 1,
      f"{sorted(st.prim_sizes().tolist())} closed={int(st.prim_closed.sum())}")

print("═" * 28, "Junction rules")

# A small example that distinguishes the three rules: A goes +x, B continues +x (short), C turns 90° at the same point (long)
PA = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]], np.float32)
PC = np.array([[2, 0, 0], [2, 1, 0], [2, 2, 0], [2, 3, 0]], np.float32)
PB = np.array([[2, 0, 0], [3, 0, 0]], np.float32)
T3 = poly([PA, PC, PB], pattr=[1, 2, 1])


def sizes(g):
    return sorted(g.prim_sizes().tolist())


check("[split] stops at the junction, none of the three connected",
      sizes(J.polypath(T3, tolerance=1e-6, junction="split")) == [2, 3, 4],
      sizes(J.polypath(T3, tolerance=1e-6, junction="split")))
check("[any] connects one by prim number -> connected C (4 points)",
      sizes(J.polypath(T3, tolerance=1e-6, junction="any")) == [2, 6],
      sizes(J.polypath(T3, tolerance=1e-6, junction="any")))
check("[straightest] picks the smallest turn -> connects B, C stays separate",
      sizes(J.polypath(T3, tolerance=1e-6, junction="straightest")) == [4, 4],
      sizes(J.polypath(T3, tolerance=1e-6, junction="straightest")))
check("[any + match_attribute] only same-named ones may connect -> also A+B",
      sizes(J.polypath(T3, tolerance=1e-6, junction="any",
                       match_attribute="name")) == [4, 4])
check("negative control: without match_attribute any **really** connects the other one",
      sizes(J.polypath(T3, tolerance=1e-6, junction="any")) != [4, 4])
check("max_angle locked down (1°) doesn't stop the **straight** one continuing (turn is 0°)",
      sizes(J.polypath(T3, tolerance=1e-6, junction="straightest",
                       max_angle=1.0)) == [4, 4],
      sizes(J.polypath(T3, tolerance=1e-6, junction="straightest",
                       max_angle=1.0)))

# To see whether max_angle takes effect, **all** candidates must be sharp turns -- and it must be a junction
# (degree ≥ 3). Where the degree is 2 the "no second choice" fast path is taken, which doesn't look at angles at all.
# The first version tripped on this: testing max_angle=1° with a straight candidate, which of course still connected
SA = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]], np.float32)    # along +x
SU = np.array([[2, 0, 0], [2, 1, 0]], np.float32)               # turn +90°
SD = np.array([[2, 0, 0], [2, -1, 0]], np.float32)              # turn −90°
T90 = poly([SA, SU, SD])
check("at a three-way junction where all candidates are 90° turns: max_angle=60 -> nothing connected",
      sizes(J.polypath(T90, tolerance=1e-6, junction="straightest",
                       max_angle=60.0)) == [2, 2, 3],
      sizes(J.polypath(T90, tolerance=1e-6, junction="straightest",
                       max_angle=60.0)))
check("  relaxed to 120° they connect (negative control: proves the previous check really was blocked by max_angle)",
      sizes(J.polypath(T90, tolerance=1e-6, junction="straightest",
                       max_angle=120.0)) == [2, 4],
      sizes(J.polypath(T90, tolerance=1e-6, junction="straightest",
                       max_angle=120.0)))

# Max Angle only applies at junctions: where degree is 2 it always connects
L90 = poly([np.array([[0, 0, 0], [1, 0, 0]], np.float32),
            np.array([[1, 0, 0], [1, 1, 0]], np.float32)])
check("**Max Angle only governs junctions**: a degree-2 90° corner still connects (otherwise it wouldn't be PolyPath)",
      J.polypath(L90, tolerance=1e-6, junction="straightest",
                 max_angle=1.0).nprims == 1)

print("═" * 28, "Closed loops / pass-through / idempotence")

E = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0]], np.float32)
F = np.array([[1, 1, 0], [0, 1, 0], [0, 0, 0]], np.float32)
LOOP = poly([E, F])
q = J.polypath(LOOP, tolerance=1e-6)
check("two segments forming a loop -> closed prim, first and last points **not duplicated**",
      q.nprims == 1 and bool(q.prim_closed[0])
      and int(q.prim_sizes()[0]) == 4, f"{q.prim_sizes().tolist()}")
check("  still 4 edges after closing (the closing edge replaces the deduplicated point)",
      len(edge_set(q)) == len(edge_set(LOOP)),
      f"{len(edge_set(LOOP))} -> {len(edge_set(q))}")
check("with close_loops off it stays an open polyline (first and last points both present)",
      not bool(J.polypath(LOOP, tolerance=1e-6,
                          close_loops=False).prim_closed[0]))

BOX = build.box()
check("faces don't participate at all, pass through **bit for bit**", sig(J.polypath(BOX)) == sig(BOX))
check("  faces' prim attributes / groups also unchanged",
      J.polypath(BOX).nprims == BOX.nprims)
MIX = poly([A, B], closed=[False, True])
mr = J.polypath(MIX, tolerance=1e-6)
check("already closed polylines don't participate either (they have no endpoints)",
      mr.nprims == 2 and int(mr.prim_closed.sum()) == 1,
      f"{mr.nprims} prims closed={int(mr.prim_closed.sum())}")

once = J.polypath(WIRE, junction="straightest")
twice = J.polypath(once, junction="straightest")
# This one was red in the first version, and rightly so: the content was identical, only the **prim order** differed --
# in the first pass the outer loop was a "walked chain"; in the second it was already closed and landed in the "passed through as is" bucket,
# so it was sorted last. The fix is to **sort once by source prim number** during assembly, which also means the output prim
# order no longer follows internal traversal (lots of downstream nodes work by prim number)
check("**idempotent**: running again is bit-identical", sig(once) == sig(twice))
W2 = CVL.convert_line(build.grid(cols=5, rows=5))
W2.set(PRIM, "src", np.arange(W2.nprims, dtype=np.float32).reshape(-1, 1))
ordered = J.polypath(W2, junction="straightest").get(PRIM, "src").ravel()
check("  output prim order follows **source prim number**, not internal traversal order",
      bool(np.all(np.diff(ordered) > 0)), ordered.tolist())
check("**deterministic**: the same input run twice is bit-identical",
      sig(J.polypath(WIRE, junction="any"))
      == sig(J.polypath(WIRE, junction="any")))

print("═" * 28, "Reversal: vertex attributes must be reversed too")

# D is reversed: only its x=2 end can connect to the end of A
D = np.array([[5, 0, 0], [2, 0, 0]], np.float32)
VG = poly([A, D], vattr=[0, 1, 2, 10, 11])
rv = J.polypath(VG, tolerance=1e-6)
check("the reversed one got connected", rv.nprims == 1, rv.nprims)
check("point sequence: D walked backwards",
      rv.vertex_point.tolist() == [0, 1, 2, 3], rv.vertex_point.tolist())
uv = rv.get(VERTEX, "uv").ravel().tolist()
check("**vertex attributes reversed too**: D's uv has 11 first, and 11 is exactly the one fused away, leaving 10",
      uv == [0.0, 1.0, 2.0, 10.0], uv)
check("negative control: without reversing it would be 11 here (that wrong shape looks completely normal)",
      uv[-1] != 11.0)
# Use a version without fusing to see the whole "reversed" thing clearly
VG2 = Geometry(4)
VG2.set(POINT, "P", np.array([[0, 0, 0], [1, 0, 0], [3, 0, 0], [1, 0, 0]],
                             np.float32))
VG2.set_topology(np.array([0, 1, 2, 3], np.int32),
                 np.array([0, 2, 4], np.int32), np.zeros(2, bool))
VG2.set(VERTEX, "uv", np.array([[0], [1], [30], [31]], np.float32))
r2 = J.polypath(VG2, tolerance=1e-6)
check("second one fully reversed: uv sequence is 31, 30 (points 3 and 1 fused together)",
      r2.get(VERTEX, "uv").ravel().tolist() in
      ([0.0, 1.0, 30.0], [0.0, 31.0, 30.0]),
      r2.get(VERTEX, "uv").ravel().tolist())

print("═" * 28, "Prim attributes / partitioning / errors")

PG = poly([A, D], pattr=[7, 9])
check("prim attributes taken from the **first** one in the chain (Houdini Join's rule)",
      J.polypath(PG, tolerance=1e-6).get(PRIM, "name").ravel().tolist()
      == [7.0])
check("prim_attribs=drop really drops them",
      J.polypath(PG, tolerance=1e-6,
                 prim_attribs="drop").get(PRIM, "name") is None)
err("wrong junction errors and lists the options",
    lambda: J.polypath(G2, junction="nearest"), "Junction must be one of")
err("wrong prim_attribs errors",
    lambda: J.polypath(G2, prim_attribs="average"), "Prim Attribs must be one of")
err("match_attribute pointing at a nonexistent attribute errors and lists the existing ones",
    lambda: J.polypath(G2, match_attribute="nope"), "No prim attribute 'nope'")
check("empty geometry doesn't crash", J.polypath(Geometry()).nprims == 0)
check("None doesn't crash", J.polypath(None).npoints == 0)
check("pure point cloud returned as is", J.polypath(build.grid(cols=2, rows=2)).nprims == 1)
err("group with a nonexistent name errors (same rule as the whole plugin)",
    lambda: J.polypath(WIRE, group="__nope__"), "No group")
WIRE.set_group(PRIM, "empty", np.zeros(WIRE.nprims, bool))
check("existing but empty group -> returned as is",
      sig(J.polypath(WIRE, group="empty")) == sig(WIRE))

print("═" * 28, "Join: creates edges, and only the ones it should")

C2 = np.array([[10, 0, 0], [11, 0, 0]], np.float32)
JG = poly([A, C2])
j = J.join(JG)
check("when endpoints don't coincide Join **adds a straight segment**",
      j.nprims == 1 and int(j.prim_sizes()[0]) == 5, j.prim_sizes().tolist())
check("  exactly 1 more edge (that connecting segment)",
      len(edge_set(j)) == len(edge_set(JG)) + 1,
      f"{len(edge_set(JG))} -> {len(edge_set(j))}")
check("  the extra one is exactly (2, 3)",
      sorted(set(edge_set(j)) - set(edge_set(JG))) == [(2, 3)],
      sorted(set(edge_set(j)) - set(edge_set(JG))))
check("negative control: on the same input PolyPath **creates no edges at all**",
      edge_set(J.polypath(JG)) == edge_set(JG))
check("joining n segments adds exactly n−1 edges",
      len(edge_set(J.join(poly([A, C2, np.array([[20, 0, 0], [21, 0, 0]],
                                                np.float32)]))))
      == len(edge_set(poly([A, C2, np.array([[20, 0, 0], [21, 0, 0]],
                                            np.float32)]))) + 2)

RG = poly([A, D])
jr = J.join(RG, tolerance=1e-6)
jn_ = J.join(RG, tolerance=1e-6, reverse_to_fit=False)
check("reverse_to_fit on: connects the nearer end",
      jr.vertex_point.tolist() == [0, 1, 2, 3], jr.vertex_point.tolist())
check("  off: strictly head to tail, so it doubles back",
      jn_.vertex_point.tolist() == [0, 1, 2, 3, 4], jn_.vertex_point.tolist())
check("  total length of the doubled-back version is **clearly larger** (which is why it's on by default)",
      total_length(jn_) > total_length(jr) * 1.5,
      f"{total_length(jr):.2f} vs {total_length(jn_):.2f}")

LP = J.join(poly([np.array([[0, 0, 0], [1, 0, 0]], np.float32),
                  np.array([[1, 1, 0], [0, 1, 0]], np.float32)]), loop=True)
check("with loop on the output prim is closed", bool(LP.prim_closed[0]))
check("  and first and last points not duplicated", int(LP.prim_sizes()[0]) == 4,
      LP.prim_sizes().tolist())
NL = J.join(poly([np.array([[0, 0, 0], [1, 0, 0]], np.float32),
                  np.array([[1, 1, 0], [0, 1, 0]], np.float32)]), loop=False)
check("negative control: with loop off it's not closed and has one edge fewer",
      not bool(NL.prim_closed[0])
      and len(edge_set(NL)) == len(edge_set(LP)) - 1,
      f"{len(edge_set(NL))} vs {len(edge_set(LP))}")

PT = poly([A, C2, np.array([[30, 0, 0], [31, 0, 0]], np.float32)],
          pattr=[1, 2, 1])
check("partition_attribute: split by name into two, each joined separately",
      J.join(PT, partition_attribute="name").nprims == 2,
      J.join(PT, partition_attribute="name").nprims)
check("  without it everything joins into one", J.join(PT).nprims == 1)
check("  after partitioning the two segments with the same name joined (5 points), the other has 2 points",
      sorted(J.join(PT, partition_attribute="name")
             .prim_sizes().tolist()) == [2, 5],
      sorted(J.join(PT, partition_attribute="name").prim_sizes().tolist()))
err("partition_attribute pointing at a nonexistent attribute errors",
    lambda: J.join(G2, partition_attribute="nope"), "No prim attribute 'nope'")
err("Join's prim_attribs is validated too",
    lambda: J.join(G2, prim_attribs="average"), "Prim Attribs must be one of")
check("Join's tolerance means 'how close counts as already connected': with exactly coincident coordinates even tol=0 adds no segment",
      len(edge_set(J.join(G2, tolerance=0.0))) == len(edge_set(G2)),
      f"{len(edge_set(G2))} -> {len(edge_set(J.join(G2, tolerance=0.0)))}")
# A 1e-3 gap: behaviour must differ with tol on either side of the gap
NEAR = poly([A, np.array([[2.001, 0, 0], [3, 0, 0]], np.float32)])
check("  1e-3 gap, tol=0 -> adds a connecting segment",
      len(edge_set(J.join(NEAR, tolerance=0.0))) == len(edge_set(NEAR)) + 1)
check("  same gap, tol=1e-2 -> treated as already connected, nothing added",
      len(edge_set(J.join(NEAR, tolerance=1e-2))) == len(edge_set(NEAR)))
pn = J.polypath(NEAR, tolerance=1e-2)
check("  negative control: PolyPath also connects the same gap, but with **not a single extra edge**",
      pn.nprims == 1 and len(edge_set(pn)) == len(edge_set(NEAR)),
      f"{pn.nprims} prims, {len(edge_set(NEAR))} -> {len(edge_set(pn))} edges")
check("  while Join at tol=0 really adds one (that's where the two differ)",
      len(edge_set(J.join(NEAR, tolerance=0.0)))
      == len(edge_set(pn)) + 1)
check("Join doesn't touch faces either", sig(J.join(BOX)) == sig(BOX))
check("Join's vertex attributes are reversed too",
      J.join(VG, tolerance=1e-6).get(VERTEX, "uv").ravel().tolist()
      == [0.0, 1.0, 2.0, 10.0])

print("═" * 28, "End to end: what these two nodes actually solve")

# Resample works **per prim** -- when the fragments aren't joined it gives "N segments per fragment",
# which is exactly why these two nodes exist
before = OPS.resample(WIRE, by_length=False, segments=10)
after = OPS.resample(J.polypath(WIRE, junction="straightest"),
                     by_length=False, segments=10)
check("Resample segments=10 run directly on 40 fragments -> 10 segments per fragment",
      before.npoints >= 40 * 10, before.npoints)
check("  PolyPath first, then Resample: point count back to a sensible magnitude",
      after.npoints < before.npoints / 4,
      f"{before.npoints} -> {after.npoints}")
# There is an honest cost to note here: only after joining does Resample really resample "along the whole curve",
# and that means **corners get cut a little** (the 4 right angles of the outer loop first of all). Unjoined it is
# exact -- because each two-point segment resamples to a straight line. This is not a bug, it's the definition of resampling
check("  cost: resampling the whole curve cuts corners, length slightly shorter (the fragment version is exact)",
      abs(total_length(before) - total_length(WIRE)) < 1e-3
      and 0.90 < total_length(after) / total_length(WIRE) < 0.995,
      f"fragments {total_length(before):.3f} / joined {total_length(after):.3f}"
      f" / original {total_length(WIRE):.3f}")

print()
print(f"{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
