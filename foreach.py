"""
Houdini's For-Each Block implemented in ComfyUI: two nodes, Block Begin / Block End,
with any node chain between them, and the whole chain is executed repeatedly.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Why this is not trivial in ComfyUI
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A ComfyUI graph is a DAG; each node runs only once per execution, and there are no loops. To run a
subgraph N times there is only one proper way: **node expansion**. A node's execution function
can return

    {"result": (...), "expand": <a new subgraph>}

The executor splices this subgraph into the current prompt and keeps running; elements of result can be links pointing to
an output of some node in the subgraph. The mechanism came with ComfyUI's execution model inversion,
and the official while-loop example relies on it.

So Block End uses **tail-recursive expansion**: each execution clones the loop body only once, and puts
a copy of itself into the clone; that copy decides whether to expand once more.

    1st run:  the chain the user drew runs once  = iteration 0
    Block End gets iteration 0's result -> clones [Begin..body..End], sets the cloned Begin's
    state to "iteration 1", returns expand
    The End in the clone gets iteration 1's result -> clones again ... until the iterations are done

Why not expand N copies at once: N depends on geometry data (how many pieces), and at expansion time we only
have links, not upstream values; also N clones would blow up the graph. The price of one step at a time
is a prefix added to node ids at each level; with thousands of iterations the id strings grow long -- max_iterations
is the safety net for that.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
One deliberate deviation from Houdini
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Houdini puts parameters like Iteration Method / Piece Attribute on **Block End**,
and Block Begin looks up the paired End to read them. Here they are on **Block Begin**, and End keeps only
gather.

The reason is execution order: in ComfyUI Begin always executes before End (it is End's upstream),
and iteration 0's piece must be computed by Begin itself. Having Begin look up End's parameters in the prompt
is certainly possible, but then changes to End's parameters would not enter Begin's cache signature --
change iterate_over, and Begin hits the old cache and is silently wrong. Whoever holds a parameter, its cache
governs it; that is not worth breaking for the sake of parameter panel placement.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Wiring
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    source ──> [Block Begin] ──geo──> ...any node chain... ──> [Block End] ──> result
                     └─────────────loop─────────────────────┘

The loop wire is not decoration: End uses it to know which Begin it is paired with (the state object carries
Begin's node id), and cloning the loop body starts collecting nodes from that Begin downwards. Without this wire
there is no loop.
"""
from __future__ import annotations

import numpy as np

from .geo import Geometry, DETAIL, ops, pieces
from .nodes_common import GEO, CAT, _i, _group, _names, _sec

LOOP = "PCG_LOOP"          # socket type for passing loop state between nodes
ACC = "PCG_LOOPACC"        # accumulator, only appears in expanded subgraphs, not shown in the frontend

BEGIN_CLASS = "PCG_ForEachBegin"
END_CLASS = "PCG_ForEachEnd"
# The per-frame loop's End also counts as an "inner End"; nesting detection must recognise it. The class name is hardcoded here
# rather than import framefor -- that would become a circular import
FRAME_END_CLASS = "PCG_ForEachFrameEnd"


# ═══════════════════════════════════════════════════════════ loop state
class LoopState:
    """
    Object flowing between Begin -> body -> End -> (cloned Begin).

    It is not "data for the user" but a cursor: splitting scheme + current iteration number + feedback geometry.
    The splitting scheme (order/starts) stays the same through the whole loop and is always a reference to the same arrays;
    advancing one step only creates a shallow copy with a different index.
    """
    __slots__ = ("begin_id", "source", "elem", "order", "starts", "values",
                 "n", "index", "feedback", "single", "max_iter")

    def __init__(self, begin_id, source, elem, order, starts, values,
                 index=0, feedback=None, single=False, max_iter=1000):
        self.begin_id = begin_id
        self.source = source
        self.elem = elem
        self.order = order
        self.starts = starts
        self.values = values
        self.n = len(values)
        self.index = int(index)
        self.feedback = feedback
        self.single = bool(single)
        self.max_iter = int(max_iter)

    def copy(self) -> "LoopState":
        s = LoopState.__new__(LoopState)
        for k in LoopState.__slots__:
            setattr(s, k, getattr(self, k))
        return s

    def advance(self, feedback) -> "LoopState":
        s = self.copy()
        s.index = self.index + 1
        s.feedback = feedback
        return s

    def piece(self) -> Geometry:
        if self.n == 0:
            return empty_like(self.source)
        return pieces.extract(self.source, self.elem, self.order,
                              self.starts, self.index)

    def value(self):
        """Value for piece number index. In pieces mode it is the attribute value; in other modes, element number / index."""
        if not self.n:
            return 0
        return self.values[min(self.index, self.n - 1)]

    def done(self) -> bool:
        """Whether this step is the last."""
        return (self.single or self.n == 0
                or self.index + 1 >= self.n
                or self.index + 1 >= self.max_iter)


def empty_like(geo: Geometry) -> Geometry:
    """
    Empty geometry isomorphic to the input: 0 points 0 primitives, but **the attribute table structure is kept as is**.

    Used when the iteration count is 0. A ComfyUI graph is static, and the loop body's chain is executed
    once no matter what -- in Houdini 0 iterations means the loop body never runs; that cannot be done here.
    The next best thing: make the geometry flowing through the loop body a "valid empty", not a bare Geometry()
    without even P, otherwise the first transform downstream raises KeyError.
    """
    out = ops.delete_prims(geo, np.zeros(geo.nprims, bool))
    if not out.has("point", "P"):
        out.set("point", "P", np.zeros((0, 3), np.float32), owned=True)
    return out


def _stamp(geo: Geometry, st: LoopState) -> Geometry:
    """
    Write iteration metadata as detail attributes.

    Houdini's Block Begin has a "Fetch Metadata" method that outputs a geometry with only detail
    attributes. Here they are attached directly to the output geometry instead -- a Wrangle in the loop body can read
    detail("iteration") without pulling another wire for one number.
    """
    g = geo.copy()
    v = st.value()
    g.set(DETAIL, "iteration", np.int32(st.index))
    g.set(DETAIL, "numiterations", np.int32(st.n))
    try:
        g.set(DETAIL, "ivalue", np.int32(int(v)))
    except (TypeError, ValueError):
        g.set(DETAIL, "ivalue", np.int32(st.index))
    g.set_string(DETAIL, "value", str(v))
    return g


# ═══════════════════════════════════════════════════════════ Block Begin
class PCG_ForEachBegin:
    """
    Mirrors Houdini's Block Begin.

    method decides what the geo output gives:
        fetch_piece     the current piece (split according to iterate_over)
        fetch_feedback  the previous iteration's result; the original input on the first iteration
        fetch_input     always the original input (equivalent to the input output; kept to match Houdini)

    The input output is always the whole unsplit input -- in Houdini this needs another Begin node with fetch input;
    here it is just one more port.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "geo": (GEO,),
                "method": (["fetch_piece", "fetch_feedback", "fetch_input"],),
                "iterate_over": (["pieces", "primitives", "points",
                                  "connectivity", "count"],),
                "piece_elements": (["primitives", "points"],),
                "piece_attribute": _names(
                    "attrib", "prim", "name",
                    "with iterate_over=pieces, split by the values of this attribute; commonly name / class"),
                "iterations": _i(10, 0, 1 << 20),
                "group": _group("Only split within these elements; empty = all"),

                **{k: _sec("Debug", v, gate=(k == "use_single_pass"))
                   for k, v in {
                       "use_single_pass": ("BOOLEAN", {"default": False}),
                       "single_pass": _i(0, 0, 1 << 20),
                   }.items()},

                "max_iterations": _i(1000, 1, 1 << 20),
            },
            # _state is injected by Block End when it expands the subgraph; not shown in the frontend (see web/pcg_foreach.js)
            "optional": {"_state": (LOOP,)},
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = (LOOP, GEO, GEO, "INT", "INT", "STRING", "INT")
    RETURN_NAMES = ("loop", "geo", "input", "iteration", "numiterations",
                    "value", "ivalue")
    FUNCTION = "run"
    CATEGORY = CAT + "/loop"

    def run(self, geo, method, iterate_over, piece_elements, piece_attribute,
            iterations, group, use_single_pass, single_pass, max_iterations,
            _state=None, unique_id=None):

        if _state is None:
            # Cold start: this is the chain the user drew, i.e. iteration 0. The splitting scheme is computed once here,
            # and the whole loop reuses the same order/starts afterwards.
            elem, order, starts, values = pieces.plan(
                geo, iterate_over, piece_attribute, piece_elements,
                iterations, group)
            n = len(values)
            start_at = 0
            if use_single_pass and n:
                start_at = min(int(single_pass), n - 1)
            st = LoopState(str(unique_id), geo, elem, order, starts, values,
                           index=start_at, feedback=None,
                           single=bool(use_single_pass),
                           max_iter=int(max_iterations))
        else:
            # An expanded clone: the state was inserted by End; no re-splitting.
            # begin_id must become **this clone's own** id -- when End collects the loop body in the next round
            # it walks down from there; writing the original id would collect the outer level's nodes.
            st = _state.copy()
            st.begin_id = str(unique_id)

        if st.n == 0:
            cur = empty_like(geo)
        elif method == "fetch_input":
            cur = st.source
        elif method == "fetch_feedback":
            # The first iteration has no "previous iteration"; per Houdini's rule, fall back to the original input
            cur = st.feedback if st.feedback is not None else st.source
        else:
            cur = st.piece()

        v = st.value()
        try:
            iv = int(v)
        except (TypeError, ValueError):
            iv = st.index
        return (st, _stamp(cur, st), st.source, st.index, st.n, str(v), iv)


# ═══════════════════════════════════════════════════════════ graph traversal
def _explore(node_id, dynprompt, is_link):
    """
    Walk upstream from node_id, building a parent -> [children] reverse table.
    Only covers the ancestors of node_id -- the loop body is certainly among them; nodes outside do not matter.

    Written iteratively rather than recursively: a deeper graph would blow Python's recursion limit, and such a crash
    only shows up in ComfyUI as a single RecursionError line, which is very hard to investigate.
    """
    upstream = {}
    seen = {node_id}
    stack = [node_id]
    while stack:
        nid = stack.pop()
        node = dynprompt.get_node(nid)
        for v in (node.get("inputs") or {}).values():
            if not is_link(v):
                continue
            p = v[0]
            kids = upstream.setdefault(p, [])
            if nid not in kids:
                kids.append(nid)
            if p not in seen:
                seen.add(p)
                stack.append(p)
    return upstream


def _contained(begin_id, upstream):
    """Nodes reachable downstream from Begin = the loop body (already limited by upstream to End's ancestors)."""
    out = {}
    stack = [begin_id]
    while stack:
        nid = stack.pop()
        for kid in upstream.get(nid, ()):
            if kid not in out:
                out[kid] = True
                stack.append(kid)
    return out



# ═══════════════════════════════════════════════════ expand loop body (shared)
def expand_body(end_id, dynprompt, begin_id, next_state, begin_class,
                end_class, body_keys=("geo",)):
    """
    Clone the loop body once and put a copy of End itself into the clone (fixed id "Recurse").
    Returns (GraphBuilder, that copy node); the caller inserts the accumulator and result itself.

    **The per-frame and per-piece loops share this.** The two loops differ only in "how to compute the next step's state"
    and "what to accumulate"; the expansion step is word for word the same -- and every rule in it was learned the hard way: when nesting,
    state must not be inserted into an inner Begin, links pointing outside the block must be kept as is, the loop body must really sit between
    Begin and End. Copying it a second time would surely miss one, and the missed one is a **silent** error
    (every iteration computes the same result, or the inner loop runs only once).

    body_keys are the input names that "must be in the loop body". If these inputs of End are wired directly from outside the block,
    the cloned subgraph does not contain them, and the loop silently computes the same result every iteration -- so this checks once
    and raises an error. Optional inputs that are not connected are skipped.
    """
    try:
        from comfy_execution.graph_utils import GraphBuilder, is_link
    except ImportError as e:                 # old ComfyUI versions have no expansion mechanism
        raise RuntimeError(
            "This ComfyUI version does not support node expansion (comfy_execution.graph_utils "
            "does not exist); loop blocks need a newer ComfyUI.") from e
    if dynprompt is None:
        raise RuntimeError(
            "Cannot get DYNPROMPT; this ComfyUI version does not support loop blocks.")

    upstream = _explore(end_id, dynprompt, is_link)
    contained = _contained(begin_id, upstream)
    contained[end_id] = True
    contained[begin_id] = True

    my_inputs = (dynprompt.get_node(end_id).get("inputs") or {})
    for k in body_keys:
        lk = my_inputs.get(k)
        if is_link(lk) and lk[0] not in contained:
            raise ValueError(
                f"Loop End's {k} is not in the loop body -- its upstream chain does not pass through the paired "
                f"Begin. Check that Begin's output is wired into this chain.")

    # Nesting: an inner block's Begin is also in contained, but its state belongs to the inner End,
    # and the outer level must not insert into it. The criterion is "some End in contained points to it with loop".
    inner = set()
    for nid in contained:
        if nid == end_id:
            continue
        nd = dynprompt.get_node(nid)
        if nd.get("class_type") in (END_CLASS, FRAME_END_CLASS):
            lk = (nd.get("inputs") or {}).get("loop")
            if is_link(lk):
                inner.add(lk[0])

    graph = GraphBuilder()
    # 1) Create all nodes first. Our own copy uses the fixed id "Recurse", so when wiring below
    #    references to End can be redirected to the cloned End.
    for nid in contained:
        orig = dynprompt.get_node(nid)
        node = graph.node(orig["class_type"],
                          "Recurse" if nid == end_id else nid)
        node.set_override_display_id(nid)    # the frontend progress bar still highlights the original node

    # 2) Then wire. Links pointing to nodes inside the block are redirected to the clone; links pointing outside are kept as is --
    #    outputs of nodes outside the block were already computed this round and are in the cache, so they are not recomputed.
    for nid in contained:
        orig = dynprompt.get_node(nid)
        node = graph.lookup_node("Recurse" if nid == end_id else nid)
        for k, v in (orig.get("inputs") or {}).items():
            if is_link(v) and v[0] in contained:
                src = graph.lookup_node(
                    "Recurse" if v[0] == end_id else v[0])
                node.set_input(k, src.out(v[1]))
            else:
                node.set_input(k, v)

    # 3) Inject the next step's state. One block can have several Begins (one fetching the piece, one fetching the whole
    #    input); all of them must advance; inner blocks' Begins are skipped.
    for nid in contained:
        if (dynprompt.get_node(nid).get("class_type") == begin_class
                and nid not in inner):
            graph.lookup_node(nid).set_input("_state", next_state)

    return graph, graph.lookup_node("Recurse")


# ═══════════════════════════════════════════════════════════ Block End
class PCG_ForEachEnd:
    """
    Mirrors Houdini's Block End.

    gather:
        merge     merge every iteration's result together (Houdini's Merge Each Iteration)
        feedback  keep only the last result; together with Begin's fetch_feedback this is a feedback loop
                  (Houdini's Feedback Each Iteration)

    Iteration count and splitting method are set on Begin; see the module header for why.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "geo": (GEO,),
                "loop": (LOOP,),
                "gather": (["merge", "feedback"],),
            },
            # _accum is injected by this node itself when expanding; not shown in the frontend
            "optional": {"_accum": (ACC,)},
            "hidden": {"dynprompt": "DYNPROMPT", "unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = (GEO,)
    RETURN_NAMES = ("geo",)
    FUNCTION = "run"
    CATEGORY = CAT + "/loop"

    def run(self, geo, loop, gather, _accum=None, dynprompt=None,
            unique_id=None):
        if not isinstance(loop, LoopState):
            raise ValueError(
                "The loop input must come directly from the loop port of For-Each Begin (PCG).")
        st: LoopState = loop

        # ---- take this iteration's result ----
        acc = list(_accum) if _accum else []
        if st.n:
            if gather == "merge":
                acc.append(geo)
            else:
                acc = [geo]                      # feedback mode keeps only the last one

        if st.done():
            if not acc:                          # 0 iterations
                return (empty_like(st.source),)
            return (ops.merge(*acc) if gather == "merge" else acc[-1],)

        # ---- there is another step: clone the loop body and put a copy of itself inside ----
        graph, me = expand_body(str(unique_id), dynprompt, st.begin_id,
                                st.advance(geo), BEGIN_CLASS, END_CLASS)
        me.set_input("_accum", acc)              # the accumulator is passed to the clone as a literal
        return {"result": (me.out(0),), "expand": graph.finalize()}


NODE_CLASS_MAPPINGS = {
    BEGIN_CLASS: PCG_ForEachBegin,
    END_CLASS: PCG_ForEachEnd,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    BEGIN_CLASS: "For-Each Begin (PCG)",
    END_CLASS: "For-Each End (PCG)",
}
