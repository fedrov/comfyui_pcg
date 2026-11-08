"""
Per-frame loop -- For-Each Frame Block. **Geometry can finally deform per frame.**

Before this, the plugin's whole timeline only covered "viewing" and "cameras": `Camera Path` loops the camera internally,
`Render Sequence` renders N frames of one **static** geometry, and the playbar lets you scrub through them. To make the geometry
itself change per frame (deformation, growth, falling pieces), the whole geometry subgraph has to be re-evaluated per frame -- and
a ComfyUI graph is a DAG; a node runs only once per execution.

So this takes the same road as For-Each Block: **node expansion**. The expansion code is
shared (`foreach.expand_body`); this file only handles the two things that differ --
"how to compute the next step's state" and "what to accumulate".

    source ──> [Frame Begin] ──geo──> ...any node chain... ──> [Frame End] ──> sequence
                    │   └─frame/t────> Expression ──> any parameter
                    └──────────────loop──────────────────┘

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Two fetch methods: input and feedback
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    input       Every frame starts from the original input. Frame N's result depends only on frame --
                keyframe animation, procedural deformation and camera animation all fall here
    feedback    Every frame starts from **the previous frame's result**; frame 0 uses the original input.
                This is Houdini's SOP Solver: growth, accumulation, progressive fracturing,
                anything where "this frame depends on the previous one"

One thing to be clear about with feedback: it is **truly serial**; frame N must wait for the first N−1 frames.
This is not implementation laziness, it is the semantics -- to parallelize, use input, so that every frame is
a pure function of frame.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Wire in a camera sequence, and the cam output is this frame's camera
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`Camera Path` -> Begin's `cams`, and Begin's `cam` output is camera number index. So
placing a `Render Pass` in the loop body gets **moving geometry** and **a moving camera** at the same time --
the last missing piece of the whole chain.

When the camera count and frame count differ it **raises an error** instead of silently wrapping: 1 camera means "fixed camera" (valid,
used for every frame); any other mismatch is a wiring mistake, and the symptom is picture and geometry being one frame apart, which looks like
"frames got mixed up" and is extremely hard to track down.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The accumulator is a **literal**, so memory needs a safety net
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The expansion mechanism can only put the accumulated result into the cloned subgraph as a literal, which means N frames of geometry and images
stay resident in memory the whole time. 240 frames of 1024² with five layers is 4.7 GB -- going over is not an error, the
OOM killer simply kills the ComfyUI process, and nothing is left on the console.

So it keeps count here: once the accumulated floats exceed `ACC_FLOAT_BUDGET`, it raises an error that says clearly what to do
(lower resolution / fewer frames / keep fewer layers), instead of waiting for the system to kill it.
"""
from __future__ import annotations

import numpy as np

from .geo import Geometry, POINT, DETAIL, ops
from .geo.cop.core import CopImage
from .nodes_common import (GEO, COP, CAM, CAMSEQ, COPSEQ, GEOSEQ, CAT,
                    _i, _f, _group)
from .foreach import expand_body

FRAME_BEGIN_CLASS = "PCG_ForEachFrameBegin"
FRAME_END_CLASS = "PCG_ForEachFrameEnd"

FLOOP = "PCG_FRAMELOOP"     # state of the frame loop
FACC = "PCG_FRAMEACC"       # accumulator, only appears in the expanded subgraph

# Memory cap of the accumulator, in number of float32s. 250 million ≈ 1 GB.
# Error out when exceeded, rather than waiting for the OOM killer -- a kill leaves no clue on the console
ACC_FLOAT_BUDGET = 250_000_000


# ═══════════════════════════════════════════════════════════ state
class FrameState:
    """
    Cursor flowing between Begin -> body -> End -> (cloned Begin).

    Parallel to foreach.LoopState, but much simpler: the frame loop's count comes from a widget and does not depend on
    geometry data, so there is no such thing as a "splitting scheme".
    """
    __slots__ = ("begin_id", "source", "frames", "start", "fps", "cams",
                 "index", "feedback", "single", "max_iter")

    def __init__(self, begin_id, source, frames, start, fps, cams,
                 index=0, feedback=None, single=False, max_iter=1000):
        self.begin_id = begin_id
        self.source = source
        self.frames = int(frames)
        self.start = int(start)
        self.fps = float(fps)
        self.cams = cams
        self.index = int(index)
        self.feedback = feedback
        self.single = bool(single)
        self.max_iter = int(max_iter)

    def copy(self):
        s = FrameState.__new__(FrameState)
        for k in FrameState.__slots__:
            setattr(s, k, getattr(self, k))
        return s

    def advance(self, feedback):
        s = self.copy()
        s.index = self.index + 1
        s.feedback = feedback
        return s

    @property
    def frame(self):
        return self.start + self.index

    @property
    def t(self):
        n = self.frames
        return 0.0 if n <= 1 else self.index / float(n - 1)

    def cam(self):
        if not self.cams:
            return None
        if len(self.cams) == 1:
            return self.cams[0]
        return self.cams[self.index]

    def done(self):
        return (self.single or self.frames <= 0
                or self.index + 1 >= self.frames
                or self.index + 1 >= self.max_iter)


def _blank():
    """Placeholder when no geometry is wired: 0 points 0 primitives, but with P -- the first transform downstream will not blow up."""
    g = Geometry()
    g.set(POINT, "P", np.zeros((0, 3), np.float32), owned=True)
    return g


def _stamp(geo, st):
    """
    Write frame metadata as detail attributes. A Wrangle in the loop body can read it with `detail("frame")`,
    without pulling another wire for one number -- same treatment as For-Each Block's iteration.
    """
    g = geo.copy()
    g.set(DETAIL, "frame", np.int32(st.frame))
    g.set(DETAIL, "frameindex", np.int32(st.index))
    g.set(DETAIL, "numframes", np.int32(st.frames))
    g.set(DETAIL, "t", np.float32(st.t))
    g.set(DETAIL, "time", np.float32((st.frame - st.start)
                                     / max(st.fps, 1e-6)))
    return g


def _acc_floats(acc):
    """How many floats the accumulator holds so far. Geometry estimated as points×3, images as pixels×channels."""
    n = 0
    for g in acc.get("geo", ()):
        if isinstance(g, Geometry):
            n += g.npoints * 3 + len(g.vertex_point)
    for im in acc.get("cop", ()):
        if isinstance(im, CopImage):
            for k in im.names:
                a = im.get(k)
                n += int(a.shape[0]) * int(a.shape[1]) * int(a.shape[2])
    return n


# ═══════════════════════════════════════════════════════════ Frame Begin
class PCG_ForEachFrameBegin:
    """
    Start of the per-frame loop. **Per-frame geometry deformation relies on this.**

    Wire Begin's `frame` / `frame_f` / `t` / `seconds` outputs into any parameter in the loop body
    (right-click Convert widget to input; put an Expression in between for a curve), and the geometry
    changes per frame. The whole loop body is re-evaluated once per frame; nodes outside the block are cooked only once and hit the cache as usual.

    ━━ method
        input       Every frame starts from the original input -- frame N depends only on frame (keyframe animation,
                    procedural deformation). Frames are independent of each other
        feedback    Every frame starts from **the previous frame's result**; frame 0 uses the original input --
                    this is Houdini's SOP Solver (growth, accumulation, progressive fracturing)

    ━━ cams
    Wire in `Camera Path`, and the `cam` output is this frame's camera. Placing a `Render Pass` in the loop body
    gets moving geometry and a moving camera at the same time. A camera count different from the frame count raises an error (except 1, which is
    a fixed camera) -- the symptom of being one frame off is "frames got mixed up", extremely hard to track down.

    ━━ Frame metadata is also attached to the geometry's detail
    `detail("frame")` / `t` / `numframes` / `time`; a Wrangle in the loop body reads them directly,
    without pulling another wire for one number.

    single_pass is a debug mode: only the given frame runs; once the chain is set up correctly, let it run the whole range.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "frames": _i(24, 0, 1 << 16),
                "start": ("INT", {"default": 0, "min": -1 << 20,
                                  "max": 1 << 20}),
                "fps": _f(24.0, 0.01, 1000.0, 0.01),
                "method": (["input", "feedback"],),
                "use_single_pass": ("BOOLEAN", {"default": False}),
                "single_pass": _i(0, 0, 1 << 16),
                "max_iterations": _i(1000, 1, 1 << 16),
            },
            "optional": {"geo": (GEO,), "cams": (CAMSEQ,),
                         "_state": (FLOOP,)},
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = (FLOOP, GEO, "INT", "FLOAT", "FLOAT", "INT", "FLOAT", CAM)
    RETURN_NAMES = ("loop", "geo", "frame", "frame_f", "t", "frames",
                    "seconds", "cam")
    FUNCTION = "run"
    CATEGORY = CAT + "/loop"

    def run(self, frames, start, fps, method, use_single_pass, single_pass,
            max_iterations, geo=None, cams=None, _state=None,
            unique_id=None):
        if _state is None:
            # Cold start: the chain the user drew, i.e. frame 0
            src = geo if geo is not None else _blank()
            n = max(0, int(frames))
            if cams:
                if len(cams) != 1 and len(cams) != n:
                    raise ValueError(
                        f"The camera sequence has {len(cams)} cameras, but the loop runs {n} frames. "
                        f"1 camera = fixed camera (used for every frame); otherwise the camera count must equal the frame count "
                        f"-- if they do not match, picture and geometry are frames apart, which looks like frames got mixed up. "
                        f"Set Camera Path's frames and this one to the same number.")
            idx = 0
            if use_single_pass and n:
                idx = min(int(single_pass), n - 1)
            st = FrameState(str(unique_id), src, n, int(start), float(fps),
                            list(cams) if cams else None, index=idx,
                            feedback=None, single=bool(use_single_pass),
                            max_iter=int(max_iterations))
        else:
            st = _state.copy()
            # begin_id must become **this clone's own** id -- when End collects the loop body in the next round
            # it walks down from there; writing the original id would collect the outer level's nodes
            st.begin_id = str(unique_id)

        if method == "feedback" and st.feedback is not None:
            cur = st.feedback
        else:
            cur = st.source

        return (st, _stamp(cur, st), st.frame, float(st.frame), st.t,
                st.frames, (st.frame - st.start) / max(st.fps, 1e-6),
                st.cam())


# ═══════════════════════════════════════════════════════════ Frame End
class PCG_ForEachFrameEnd:
    """
    End of the per-frame loop. Accumulates each frame's result into a **sequence**.

    Outputs:
        geoseq   one geometry per frame (into Geo Sequence Pick / Sequence Motion)
        seq      one COP per frame (into Sequence Export -> IMAGE batch = video)
        merged   all frames merged together (onion skin / see the whole range at a glance; not computed by default)
        frames   how many frames actually ran

    At least one of the `geo` and `cop` inputs must be wired; whichever is wired gets accumulated. Wire both and both are accumulated --
    the typical use is `cop` for exporting video and `geoseq` for computing motion vectors.

    ━━ The accumulator is a literal, so there is a memory cap
    The expansion mechanism can only put the accumulated result into the cloned subgraph as a literal; N frames of data stay resident in memory.
    240 frames of 1024² with five layers = 4.7 GB; going over is not an error, the OOM killer kills the whole
    ComfyUI and nothing is left on the console. So it keeps count here, and above about 1 GB raises an error that says clearly
    what to do. For really long sequences: lower resolution, fewer layers, or run in several segments.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "loop": (FLOOP,),
                "merge_output": ("BOOLEAN", {"default": False}),
            },
            "optional": {"geo": (GEO,), "cop": (COP,), "_accum": (FACC,)},
            "hidden": {"dynprompt": "DYNPROMPT", "unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = (GEOSEQ, COPSEQ, GEO, "INT")
    RETURN_NAMES = ("geoseq", "seq", "merged", "frames")
    FUNCTION = "run"
    CATEGORY = CAT + "/loop"

    def run(self, loop, merge_output, geo=None, cop=None, _accum=None,
            dynprompt=None, unique_id=None):
        if not isinstance(loop, FrameState):
            raise ValueError(
                "The loop input must come directly from the loop port of For-Each Frame Begin (PCG)"
                ".")
        if geo is None and cop is None:
            raise ValueError(
                "For-Each Frame End needs at least one of geo and cop wired -- "
                "otherwise nobody collects the loop body's result and the whole loop runs for nothing.")
        st: FrameState = loop

        acc = {"geo": list((_accum or {}).get("geo", [])),
               "cop": list((_accum or {}).get("cop", []))}
        if st.frames:
            if geo is not None:
                acc["geo"].append(geo)
            if cop is not None:
                acc["cop"].append(cop)

        used = _acc_floats(acc)
        if used > ACC_FLOAT_BUDGET:
            raise MemoryError(
                f"The data accumulated by the frame loop has reached {used / 2.5e8:.2f} GB (frame "
                f"{st.index + 1}/{st.frames}), over the 1 GB cap. "
                f"The accumulator can only be passed to the expanded subgraph as a literal, so N frames of data stay "
                f"resident in memory the whole time -- growing further would get the ComfyUI process killed by the system, "
                f"leaving no clue on the console. Fixes: lower resolution, keep fewer layers, "
                f"fewer frames, or run in several segments.")

        if st.done():
            n = len(acc["geo"]) or len(acc["cop"])
            merged = _blank()
            if merge_output and acc["geo"]:
                merged = ops.merge(*acc["geo"])
            elif acc["geo"]:
                merged = acc["geo"][-1]
            return (acc["geo"], acc["cop"], merged, int(n))

        # There is another frame: clone the loop body and put a copy of itself inside
        keys = tuple(k for k, v in (("geo", geo), ("cop", cop))
                     if v is not None)
        graph, me = expand_body(str(unique_id), dynprompt, st.begin_id,
                                st.advance(geo), FRAME_BEGIN_CLASS,
                                FRAME_END_CLASS, keys)
        me.set_input("_accum", acc)
        return {"result": (me.out(0), me.out(1), me.out(2), me.out(3)),
                "expand": graph.finalize()}


NODE_CLASS_MAPPINGS = {
    FRAME_BEGIN_CLASS: PCG_ForEachFrameBegin,
    FRAME_END_CLASS: PCG_ForEachFrameEnd,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    FRAME_BEGIN_CLASS: "For-Each Frame Begin (PCG)",
    FRAME_END_CLASS: "For-Each Frame End (PCG)",
}
