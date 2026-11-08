import os
import sys
sys.setrecursionlimit(20000)
# Package root: first search upwards from this file's location, otherwise fall back to the old sandbox path
_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break

import fakecomfy                      # noqa: F401  (installs the comfy_execution stub)
import numpy as np

from comfyui_pcg import nodes as N
from comfyui_pcg import foreach as FE
from comfyui_pcg import framefor as FF
from comfyui_pcg import expr as EX
from comfyui_pcg.geo import (Geometry, POINT, PRIM, DETAIL, build, ops,
                             render as R, sequence as SQ, uvproject as U)
from comfyui_pcg.geo.cop.core import CopImage

CLASSES = dict(N.NODE_CLASS_MAPPINGS)
for m in (FE, FF, EX):
    CLASSES.update(m.NODE_CLASS_MAPPINGS)

OK = []
def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("   " + str(extra)) if extra != "" else ""))

def RUN(fn, *a, **k):
    """
    Call a node's execute function and **unpack** the return value.

    In production comfyui_pcg/__init__.py uses attach_group_reporting /
    attach_cop_preview to wrap every node's execute function, so it returns
    {"ui": ..., "result": (...)}. A direct `a, b = node.run(...)` would get the
    two strings that are the **dict keys** ("ui", "result") and then fail with
    something like `'str' object has no attribute ...`, which points nowhere near the real cause.
    """
    return fakecomfy.unwrap(fn(*a, **k))


def err(name, fn, frag):
    try:
        fn(); check(name, False, "did not raise")
    except Exception as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:130]}")


# ───────────────────────────────────────────────── Helper nodes for the tests
SRC = ops.compute_normals(build.box((1, 1, 1), (0, 0, 0), (2, 2, 2), 1.0))


class SrcNode:
    @classmethod
    def INPUT_TYPES(cls): return {"required": {}}
    RETURN_TYPES = ("GEOMETRY",); FUNCTION = "run"; CATEGORY = "t"
    def run(self): return (SRC,)


class Move:
    """Loop body: translate along Y by ty, and record what it receives / emits each time."""
    seen_in = []
    seen_ty = []
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": ("GEOMETRY",),
                             "ty": ("FLOAT", {"default": 0.0})}}
    RETURN_TYPES = ("GEOMETRY",); FUNCTION = "run"; CATEGORY = "t"
    def run(self, geo, ty):
        Move.seen_in.append(geo)
        Move.seen_ty.append(float(ty))
        return (ops.transform(geo, (0, float(ty), 0)),)


class TinyCop:
    """Loop body: turn a number into a 4x4 constant image, to test accumulation of COP sequences."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": ("GEOMETRY",),
                             "v": ("FLOAT", {"default": 0.0}),
                             "res": ("INT", {"default": 4})}}
    RETURN_TYPES = ("COPIMAGE",); FUNCTION = "run"; CATEGORY = "t"
    def run(self, geo, v, res):
        r = int(res)
        return (CopImage(r, r, {"C": np.full((r, r, 1), float(v),
                                            np.float32)}),)


class CamsNode:
    """Output a list of cameras."""
    cams = []
    @classmethod
    def INPUT_TYPES(cls): return {"required": {}}
    RETURN_TYPES = ("PCGCAMSEQ",); FUNCTION = "run"; CATEGORY = "t"
    def run(self): return (CamsNode.cams,)


class SpyCam:
    """Loop body: record the camera received for each frame."""
    seen = []
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": ("GEOMETRY",), "cam": ("PCGCAM",)}}
    RETURN_TYPES = ("GEOMETRY",); FUNCTION = "run"; CATEGORY = "t"
    def run(self, geo, cam):
        SpyCam.seen.append(cam)
        return (geo,)


for k, v in (("__SRC__", SrcNode), ("Move", Move), ("TinyCop", TinyCop),
             ("__CAMS__", CamsNode), ("SpyCam", SpyCam)):
    CLASSES[k] = v


def begin_inputs(**kw):
    d = {"frames": 4, "start": 0, "fps": 24.0, "method": "input",
         "use_single_pass": False, "single_pass": 0, "max_iterations": 1000}
    d.update(kw)
    return d


def graph_move(begin_kw=None, end_kw=None, ty_from=2):
    """source -> Begin -> Move(ty = Begin.frame_f) -> End"""
    return {
        "1": {"class_type": "__SRC__", "inputs": {}},
        "2": {"class_type": FF.FRAME_BEGIN_CLASS,
              "inputs": {"geo": ["1", 0], **begin_inputs(**(begin_kw or {}))}},
        "3": {"class_type": "Move",
              "inputs": {"geo": ["2", 1], "ty": ["2", ty_from]}},
        "4": {"class_type": FF.FRAME_END_CLASS,
              "inputs": {"geo": ["3", 0], "loop": ["2", 0],
                         "merge_output": False, **(end_kw or {})}},
    }


def run_graph(g, out="4"):
    ex = fakecomfy.Executor(g, CLASSES)
    return ex.run(out), ex


def reset():
    Move.seen_in, Move.seen_ty = [], []
    SpyCam.seen = []


print("═" * 28, "Basics: per-frame evaluation")

reset()
res, _ = run_graph(graph_move())
geoseq, copseq, merged, nframes = res
check("the loop body really ran 4 times", len(Move.seen_ty) == 4, len(Move.seen_ty))
check("ty received per frame is 0,1,2,3 (driven by frame_f)",
      Move.seen_ty == [0.0, 1.0, 2.0, 3.0], Move.seen_ty)
check("geoseq accumulated 4 frames", len(geoseq) == 4, len(geoseq))
check("frames output = 4", nframes == 4, nframes)
check("copseq is empty (no cop wired)", copseq == [], copseq)
ys = [float(np.asarray(g.get(POINT, "P"), np.float64)[:, 1].mean())
      for g in geoseq]
check("each frame's geometry really moved to a different position", np.allclose(ys, [0, 1, 2, 3], atol=1e-5),
      [round(v, 4) for v in ys])
check("each frame is a complete copy of the geometry (not sliced)",
      all(g.nprims == SRC.nprims and g.npoints == SRC.npoints
          for g in geoseq))
check("with merge_output=False merged only gives the last frame (doesn't compute N copies for nothing)",
      merged.nprims == SRC.nprims, merged.nprims)

res2, _ = run_graph(graph_move(end_kw={"merge_output": True}))
check("with merge_output=True merged is the 4 frames combined",
      res2[2].nprims == SRC.nprims * 4, res2[2].nprims)

print("═" * 28, "frame / t / seconds outputs")

reset()
res, _ = run_graph(graph_move(begin_kw={"frames": 5, "start": 10},
                              ty_from=2))
check("start offset takes effect: frame is 10..14", Move.seen_ty == [10, 11, 12, 13, 14],
      Move.seen_ty)
reset()
res, _ = run_graph(graph_move(begin_kw={"frames": 5}, ty_from=4))
check("t goes from 0 to 1 (5 frames -> 0,.25,.5,.75,1)",
      np.allclose(Move.seen_ty, [0, .25, .5, .75, 1.0]), Move.seen_ty)
reset()
res, _ = run_graph(graph_move(begin_kw={"frames": 3, "fps": 10.0},
                              ty_from=6))
check("seconds = (frame − start)/fps", np.allclose(Move.seen_ty, [0, .1, .2]),
      Move.seen_ty)
reset()
res, _ = run_graph(graph_move(begin_kw={"frames": 1}, ty_from=4))
check("with a single frame t = 0, no division by zero", Move.seen_ty == [0.0], Move.seen_ty)

# Frame metadata is also attached to the geometry's detail
reset()
run_graph(graph_move(begin_kw={"frames": 3, "start": 5, "fps": 10.0}))
fr = [int(g.get(DETAIL, "frame")[0, 0]) for g in Move.seen_in]
check("detail('frame') attached", fr == [5, 6, 7], fr)
check("detail('numframes') attached",
      [int(g.get(DETAIL, "numframes")[0, 0]) for g in Move.seen_in]
      == [3, 3, 3])
check("detail('t') attached",
      np.allclose([float(g.get(DETAIL, "t")[0, 0]) for g in Move.seen_in],
                  [0, .5, 1.0]))
check("detail('time') converted by fps",
      np.allclose([float(g.get(DETAIL, "time")[0, 0])
                   for g in Move.seen_in], [0, .1, .2]))


print("═" * 28, "feedback: Houdini's SOP Solver")

reset()
res, _ = run_graph(graph_move(begin_kw={"frames": 4, "method": "feedback"},
                              ty_from=3))   # ty fixed at 1.0? use frame_f
# ty uses frame_f (0,1,2,3); under feedback positions should accumulate: 0, 0+1, 1+2, 3+3
ys = [float(np.asarray(g.get(POINT, "P"), np.float64)[:, 1].mean())
      for g in res[0]]
check("feedback: each frame starts from the previous one, displacement **accumulates**",
      np.allclose(ys, [0, 1, 3, 6], atol=1e-4), [round(v, 4) for v in ys])
reset()
res, _ = run_graph(graph_move(begin_kw={"frames": 4, "method": "input"},
                              ty_from=3))
ys2 = [float(np.asarray(g.get(POINT, "P"), np.float64)[:, 1].mean())
       for g in res[0]]
check("counter-example: input mode gives 0,1,2,3 (no accumulation) -- the two modes really differ",
      np.allclose(ys2, [0, 1, 2, 3], atol=1e-4), [round(v, 4) for v in ys2])
reset()
res, _ = run_graph(graph_move(begin_kw={"frames": 3, "method": "feedback"},
                              ty_from=2))
check("feedback frame 0 uses the original input",
      abs(float(np.asarray(Move.seen_in[0].get(POINT, "P"),
                           np.float64)[:, 1].mean())) < 1e-6)


print("═" * 28, "COP sequence + both inputs wired at once")

g = {
    "1": {"class_type": "__SRC__", "inputs": {}},
    "2": {"class_type": FF.FRAME_BEGIN_CLASS,
          "inputs": {"geo": ["1", 0], **begin_inputs(frames=5)}},
    "3": {"class_type": "Move", "inputs": {"geo": ["2", 1], "ty": ["2", 3]}},
    "4": {"class_type": "TinyCop",
          "inputs": {"geo": ["3", 0], "v": ["2", 4], "res": 4}},
    "5": {"class_type": FF.FRAME_END_CLASS,
          "inputs": {"geo": ["3", 0], "cop": ["4", 0], "loop": ["2", 0],
                     "merge_output": False}},
}
reset()
res, _ = run_graph(g, out="5")
check("geo and cop inputs can be wired at the same time", len(res[0]) == 5 and len(res[1]) == 5,
      (len(res[0]), len(res[1])))
vals = [float(np.asarray(im.need("C")).mean()) for im in res[1]]
check("COP sequence values follow t per frame",
      np.allclose(vals, [0, .25, .5, .75, 1.0], atol=1e-6),
      [round(v, 4) for v in vals])
b = SQ.to_batch(res[1], "C", "clamp")
check("the COP sequence can feed to_batch directly (= the B dimension of IMAGE)",
      b.shape == (5, 4, 4, 3), b.shape)

# Wiring only cop also works
g2 = dict(g)
g2["5"] = {"class_type": FF.FRAME_END_CLASS,
           "inputs": {"cop": ["4", 0], "loop": ["2", 0],
                      "merge_output": False}}
res, _ = run_graph(g2, out="5")
check("only cop wired: accumulates a COP sequence, geoseq empty",
      len(res[1]) == 5 and res[0] == [], (len(res[1]), res[0]))


print("═" * 28, "Camera sequence")

CamsNode.cams = SQ.camera_path(SRC, frames=4, xres=32, yres=32)
gc = {
    "1": {"class_type": "__SRC__", "inputs": {}},
    "9": {"class_type": "__CAMS__", "inputs": {}},
    "2": {"class_type": FF.FRAME_BEGIN_CLASS,
          "inputs": {"geo": ["1", 0], "cams": ["9", 0],
                     **begin_inputs(frames=4)}},
    "3": {"class_type": "SpyCam",
          "inputs": {"geo": ["2", 1], "cam": ["2", 7]}},
    "4": {"class_type": FF.FRAME_END_CLASS,
          "inputs": {"geo": ["3", 0], "loop": ["2", 0],
                     "merge_output": False}},
}
reset()
res, _ = run_graph(gc)
check("cam output gives a different camera per frame", len(SpyCam.seen) == 4
      and all(SpyCam.seen[i] is CamsNode.cams[i] for i in range(4)),
      len(SpyCam.seen))

CamsNode.cams = [SQ.camera_path(SRC, frames=1, xres=32, yres=32)[0]]
reset()
res, _ = run_graph(gc)
check("only 1 camera given = fixed camera, used for every frame",
      len(SpyCam.seen) == 4
      and all(c is CamsNode.cams[0] for c in SpyCam.seen))

CamsNode.cams = SQ.camera_path(SRC, frames=3, xres=32, yres=32)
err("camera count not matching the frame count raises right away (an off-by-frames symptom is very hard to track down)",
    lambda: run_graph(gc), "but the loop runs")
CamsNode.cams = SQ.camera_path(SRC, frames=4, xres=32, yres=32)


print("═" * 28, "Edge cases and errors")

reset()
res, _ = run_graph(graph_move(begin_kw={"frames": 1}))
check("frames=1 runs only once", len(Move.seen_ty) == 1 and len(res[0]) == 1)
reset()
res, _ = run_graph(graph_move(begin_kw={"frames": 0}))
check("frames=0: the loop body still runs once (determined by the DAG's static structure)",
      len(Move.seen_ty) == 1, len(Move.seen_ty))
check("but no frame is accumulated, frames output 0", res[0] == [] and res[3] == 0, res[3])

reset()
res, _ = run_graph(graph_move(begin_kw={"frames": 6, "use_single_pass": True,
                                        "single_pass": 4}, ty_from=2))
check("single_pass runs only the given frame (debug mode)",
      len(Move.seen_ty) == 1 and Move.seen_ty == [4.0], Move.seen_ty)
reset()
res, _ = run_graph(graph_move(begin_kw={"frames": 3, "use_single_pass": True,
                                        "single_pass": 99}, ty_from=2))
check("single_pass out of range is clamped to the last frame", Move.seen_ty == [2.0], Move.seen_ty)

reset()
res, _ = run_graph(graph_move(begin_kw={"frames": 50,
                                        "max_iterations": 7}))
check("max_iterations catches a runaway loop", len(Move.seen_ty) == 7,
      len(Move.seen_ty))

gbad = graph_move()
del gbad["4"]["inputs"]["geo"]
err("neither geo nor cop wired raises (the loop would run for nothing)",
    lambda: run_graph(gbad), "needs at least one of geo and cop")

gbad2 = graph_move()
gbad2["4"]["inputs"]["loop"] = ["1", 0]     # loop wired to something else
err("loop not wired to Frame Begin raises",
    lambda: run_graph(gbad2), "must come directly from")

# End's geo pulled from outside the block -> the loop would compute the same result every frame; must be blocked
gout = {
    "1": {"class_type": "__SRC__", "inputs": {}},
    "2": {"class_type": FF.FRAME_BEGIN_CLASS,
          "inputs": {"geo": ["1", 0], **begin_inputs()}},
    "3": {"class_type": "Move",
          "inputs": {"geo": ["2", 1], "ty": ["2", 3]}},
    "4": {"class_type": FF.FRAME_END_CLASS,
          "inputs": {"geo": ["1", 0], "loop": ["2", 0],
                     "merge_output": False}},
}
err("End's geo not in the loop body raises (otherwise every frame computes the same result, silently)",
    lambda: run_graph(gout), "is not in the loop body")


print("═" * 28, "Memory guard")

# Really reaching 1 GB means allocating 1 GB, not worth it in a test -- temporarily lower the cap; what is checked is that
# the condition and its error message actually trigger
_real = FF.ACC_FLOAT_BUDGET
FF.ACC_FLOAT_BUDGET = 100
try:
    err("going over the cap raises proactively instead of waiting for the OOM killer",
        lambda: run_graph(g, out="5"), "over the 1 GB cap")
finally:
    FF.ACC_FLOAT_BUDGET = _real
check("after restoring, the same graph runs to completion (the previous check left no pollution)",
      len(run_graph(g, out="5")[0][1]) == 5)
check("the cap constant is 250 million float32 ≈ 1 GB",
      FF.ACC_FLOAT_BUDGET == 250_000_000)
# The counting function itself: 4 frames 4×4 single channel = 4×16 = 64 floats
check("_acc_floats counts images as pixels × channels",
      FF._acc_floats({"cop": [CopImage(4, 4, {"C": np.zeros((4, 4, 1),
                                                            np.float32)})]
                      * 4}) == 64,
      FF._acc_floats({"cop": [CopImage(4, 4, {"C": np.zeros((4, 4, 1),
                                                            np.float32)})]
                      * 4}))
check("_acc_floats also counts geometry (points×3 + vertices)",
      FF._acc_floats({"geo": [SRC]}) == SRC.npoints * 3
      + len(SRC.vertex_point))


print("═" * 28, "Nested with the per-piece loop")

# Outer by frame, inner by piece: the inner Begin's state must not be pushed in by the outer loop
nested = {
    "1": {"class_type": "__SRC__", "inputs": {}},
    "2": {"class_type": FF.FRAME_BEGIN_CLASS,
          "inputs": {"geo": ["1", 0], **begin_inputs(frames=3)}},
    "5": {"class_type": FE.BEGIN_CLASS,
          "inputs": {"geo": ["2", 1], "method": "fetch_piece",
                     "iterate_over": "primitives",
                     "piece_elements": "primitives",
                     "piece_attribute": "name", "iterations": 10,
                     "group": "", "use_single_pass": False,
                     "single_pass": 0, "max_iterations": 1000}},
    "3": {"class_type": "Move",
          "inputs": {"geo": ["5", 1], "ty": ["2", 3]}},
    "6": {"class_type": FE.END_CLASS,
          "inputs": {"geo": ["3", 0], "loop": ["5", 0], "gather": "merge"}},
    "4": {"class_type": FF.FRAME_END_CLASS,
          "inputs": {"geo": ["6", 0], "loop": ["2", 0],
                     "merge_output": False}},
}
reset()
res, _ = run_graph(nested)
check("frame loop around a piece loop: 3 frames × 6 faces = 18 loop-body runs",
      len(Move.seen_ty) == 3 * SRC.nprims,
      f"{len(Move.seen_ty)} vs {3 * SRC.nprims}")
check("all 3 outer frames collected", len(res[0]) == 3, len(res[0]))
check("each frame's face count restored (inner merge came back)",
      all(g.nprims == SRC.nprims for g in res[0]),
      [g.nprims for g in res[0]])
tys = sorted(set(Move.seen_ty))
check("each inner piece gets the outer loop's current frame", tys == [0.0, 1.0, 2.0], tys)


print("═" * 28, "Sequence Motion: motion vectors of moving geometry")

# A plane translating along X, ortho camera -> per-frame displacement has a closed form
PL = ops.compute_normals(build.grid(2, 2, 3, 3))
Pp = np.asarray(PL.get(POINT, "P"), np.float64)
PL.set(POINT, "P", np.stack([Pp[:, 0], Pp[:, 2],
                             np.zeros(len(Pp))], 1).astype(np.float32),
       owned=True)
PL = ops.compute_normals(PL)
OC = R.camera(projection="orthographic", eye=(0, 0, 5), target=(0, 0, 0),
              ortho_size=4.0, xres=128, yres=128)
dx = 0.25
geos = [ops.transform(PL, (i * dx, 0, 0)) for i in range(4)]
mseq = SQ.motion_sequence(geos, [OC], loop=False)
check("motion_sequence gives 4 frames", len(mseq) == 4)
f0 = np.asarray(mseq[0].need("motion"), np.float64)
m0 = np.asarray(mseq[0].need("mask"), np.float64)[:, :, 0] > 0
exp = dx / 2.0 * 64.0                       # d/(size/2) * (W/2)
check("translation displacement matches the analytic value (ortho, closed form)",
      abs(float(f0[m0][:, 0].mean()) - exp) < 1e-4,
      (float(f0[m0][:, 0].mean()), exp))
check("y component exactly 0", float(np.abs(f0[m0][:, 1]).max()) < 1e-9)
last = np.asarray(mseq[-1].need("motion"), np.float64)
check("with loop=False the last frame's motion is zero (undefined is reported as undefined)",
      float(np.abs(last).max()) == 0.0)
check("and disocclusion is all 1", float(np.asarray(
    mseq[-1].need("disocclusion")).min()) == 1.0)
mloop = SQ.motion_sequence(geos, [OC], loop=True)
check("with loop=True the last frame wraps back to frame 0 (displacement is −3dx)",
      abs(float(np.asarray(mloop[-1].need("motion"), np.float64)[
          np.asarray(mloop[-1].need("mask"), np.float64)[:, :, 0] > 0
      ][:, 0].mean()) + 3 * exp) < 1e-3,
      float(np.asarray(mloop[-1].need("motion"), np.float64).min()))
err("geometry and camera counts not matching raises",
    lambda: SQ.motion_sequence(geos, SQ.camera_path(PL, frames=3, xres=128,
                                                    yres=128)),
    "they must match")
err("no camera given raises",
    lambda: SQ.motion_sequence(geos, []), "need a camera")
check("empty geometry sequence gives an empty result", SQ.motion_sequence([], [OC]) == [])


print("═" * 28, "Node layer")

NM = CLASSES
for k in (FF.FRAME_BEGIN_CLASS, FF.FRAME_END_CLASS, "PCG_GeoSequencePick",
          "PCG_SequenceMotion"):
    check(f"{k} registered and has a display name",
          k in NM and (k in N.NODE_DISPLAY_NAME_MAPPINGS
                       or k in FF.NODE_DISPLAY_NAME_MAPPINGS))
    NM[k].INPUT_TYPES()
check("Frame Begin outputs complete (loop/geo/frame/frame_f/t/frames/seconds/cam)",
      NM[FF.FRAME_BEGIN_CLASS].RETURN_NAMES
      == ("loop", "geo", "frame", "frame_f", "t", "frames", "seconds",
          "cam"), NM[FF.FRAME_BEGIN_CLASS].RETURN_NAMES)
check("frame number available as both INT and FLOAT (litegraph type checks are string equality)",
      NM[FF.FRAME_BEGIN_CLASS].RETURN_TYPES[2:4] == ("INT", "FLOAT"))
check("Frame End outputs geoseq / seq / merged / frames",
      NM[FF.FRAME_END_CLASS].RETURN_NAMES
      == ("geoseq", "seq", "merged", "frames"))

pk = NM["PCG_GeoSequencePick"]()
one, tot = RUN(pk.run, geos, 6)
check("Geo Sequence Pick wraps when out of range", one is geos[2] and tot == 4)
err("Pick on an empty geometry sequence raises", lambda: pk.run([], 0), "sequence is empty")

sm = NM["PCG_SequenceMotion"]()
seq, nf = RUN(sm.run, geos, [OC], "pixels", 0.02, 1, False, "", "numpy")
check("Sequence Motion node runs", nf == 4 and "motion" in seq[0])

print(f"\n{sum(OK)}/{len(OK)} passed")
