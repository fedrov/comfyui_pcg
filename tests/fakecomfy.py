"""
ComfyUI stub for tests: a minimal `comfy_execution.graph_utils` + an evaluator that can run
**node expansion** (`{"result":..., "expand":...}`).

Loop blocks (For-Each / For-Each Frame) are not ordinary nodes: they use ComfyUI's expansion mechanism to
clone themselves back into the graph for tail recursion. Without this stub they could only be clicked through by hand in ComfyUI, not tested.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Scopes instead of id prefixes
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The real `GraphBuilder` adds a prefix to the ids of cloned nodes so that several rounds of expansion do not collide.
Here a simpler and more accurate approach is used: each expansion creates a **child scope**; the cloned nodes live
in the child scope with their ids unchanged.

This also gets another thing right for free: in the expanded graph, links pointing **outside the block** are kept as they are
(if `v[0]` is not in contained it is not changed). Those ids only exist in the parent scope; with prefixes
they point to the unprefixed original nodes, with scopes it is "not found in this level, look upward", and
the parent scope's cache already holds the computed values, which matches ComfyUI's rule that "nodes outside the block
were already computed this round and are not recomputed".

`unique_id` gives the node's id in **its own scope**; End's clone is always called
"Recurse", Begin's clone keeps the original id, so `st.begin_id` can still be found in the next level.
These two are conventions foreach.expand_body relies on; changing them breaks it silently.
"""
from __future__ import annotations

import sys
import types


# ═══════════════════════════════════════════════ comfy_execution.graph_utils
def is_link(obj):
    """ComfyUI's definition: [node id (string), output index (integer)]."""
    return (isinstance(obj, list) and len(obj) == 2
            and isinstance(obj[0], str) and isinstance(obj[1], int))


class _Node:
    __slots__ = ("id", "class_type", "inputs", "display_id")

    def __init__(self, nid, class_type):
        self.id = str(nid)
        self.class_type = class_type
        self.inputs = {}
        self.display_id = None

    def set_input(self, key, value):
        self.inputs[key] = value
        return self

    def set_override_display_id(self, nid):
        # The real implementation uses it to highlight the original node in the frontend progress bar. Here it is only recorded, so tests can check it
        self.display_id = nid
        return self

    def out(self, index):
        return [self.id, int(index)]


class GraphBuilder:
    def __init__(self, prefix=None):
        self.prefix = prefix
        self.nodes = {}
        self._auto = 0

    def node(self, class_type, nid=None):
        if nid is None:
            self._auto += 1
            nid = f"_auto{self._auto}"
        n = _Node(nid, class_type)
        self.nodes[n.id] = n
        return n

    def lookup_node(self, nid):
        return self.nodes.get(str(nid))

    def finalize(self):
        return {k: {"class_type": v.class_type, "inputs": dict(v.inputs)}
                for k, v in self.nodes.items()}


_mod = types.ModuleType("comfy_execution")
_gu = types.ModuleType("comfy_execution.graph_utils")
_gu.GraphBuilder = GraphBuilder
_gu.is_link = is_link
_mod.graph_utils = _gu
sys.modules.setdefault("comfy_execution", _mod)
sys.modules.setdefault("comfy_execution.graph_utils", _gu)


# ═══════════════════════════════════════════════════════════════ Evaluator
class _Scope:
    """One graph level. Ids not found are looked up in the parent scope (an expanded graph points to nodes outside the block)."""

    def __init__(self, prompt, parent=None):
        self.prompt = dict(prompt)
        self.parent = parent
        self.cache = {}

    def owner(self, nid):
        s = self
        while s is not None:
            if nid in s.prompt:
                return s
            s = s.parent
        raise KeyError(f"No node {nid!r} in the graph")

    def get_node(self, nid):
        return self.owner(str(nid)).prompt[str(nid)]


class _DynPrompt:
    """The `DYNPROMPT` hidden input. Only get_node is used."""

    def __init__(self, scope):
        self._scope = scope

    def get_node(self, nid):
        return self._scope.get_node(str(nid))


class Executor:
    """
    Runs a prompt graph. `expansions` records how many expansions happened; tests use it to check the number of tail-recursion rounds.
    """

    def __init__(self, prompt, classes, max_expansions=10000, release=False):
        """
        release: drop a top-level node's outputs once every node reading them has run (like ComfyUI with its cache
        off), and remember the node as done -- a later run() of it returns None instead of computing it again. For
        big pipelines whose checks read the files they wrote, not the outputs: keeping every output of the open-world
        example (4096² texture chain, the full-map meshes) does not fit in 8 GB next to its render.
        """
        self.classes = classes
        self.root = _Scope(prompt)
        self.expansions = 0
        self.max_expansions = max_expansions
        self.calls = []                  # [(class_type, node_id), ...] in execution order
        self.release = bool(release)
        self.done = set()
        self.readers = {}
        if self.release:
            for node in self.root.prompt.values():
                for v in (node.get("inputs") or {}).values():
                    if is_link(v):
                        self.readers[str(v[0])] = self.readers.get(str(v[0]), 0) + 1

    def run(self, node_id):
        if self.release and str(node_id) in self.done:
            return None
        return self._eval(self.root, str(node_id))

    def _consumed(self, nid):
        """A top-level reader of nid has run: when it was the last one, nid's outputs go."""
        n = self.readers.get(nid, 0) - 1
        self.readers[nid] = n
        if n <= 0:
            self.root.cache.pop(nid, None)

    # ── Internals ─────────────────────────────────────────────────────
    def _eval(self, scope, nid):
        own = scope.owner(nid)
        if nid in own.cache:
            return own.cache[nid]
        node = own.prompt[nid]
        ct = node["class_type"]
        if ct not in self.classes:
            raise KeyError(f"Unregistered node type {ct!r} (node {nid})")
        cls = self.classes[ct]

        spec = cls.INPUT_TYPES() if hasattr(cls, "INPUT_TYPES") else {}
        inputs = node.get("inputs") or {}

        # ── Lazy inputs ───────────────────────────────────────────────
        # For inputs declared with {"lazy": True}, ComfyUI does **not compute them first**; it calls
        # check_lazy_status to ask the node "which ones do you actually need" and only computes those it names.
        # Switch relies on it to skip unselected branches, File Cache relies on it to **not touch upstream at all** when reading from disk;
        # the latter is the whole reason the cache saves time: if "reading from disk" alone did not prevent upstream from recomputing,
        # this node would be useless.
        #
        # This was not implemented for a while, so PCG_Switch's laziness was never tested either.
        lazy = {k for sec in ("required", "optional")
                for k, v in (spec.get(sec) or {}).items()
                if isinstance(v, (list, tuple)) and len(v) > 1
                and isinstance(v[1], dict) and v[1].get("lazy")}

        inst = cls()
        kwargs = {}
        for k, v in inputs.items():
            if k in lazy:
                continue                      # skip for now, computed on demand below
            kwargs[k] = (self._eval(own, v[0])[v[1]] if is_link(v) else v)

        for k, v in (spec.get("hidden") or {}).items():
            if v == "UNIQUE_ID":
                kwargs[k] = nid
            elif v == "DYNPROMPT":
                kwargs[k] = _DynPrompt(own)
            elif v == "PROMPT":
                kwargs[k] = own.prompt

        if lazy:
            if hasattr(inst, "check_lazy_status"):
                # Real ComfyUI keeps asking until no new inputs are named. Loop here too.
                for _ in range(len(lazy) + 1):
                    probe = dict(kwargs)
                    for k in inputs:
                        if k in lazy:
                            probe.setdefault(k, None)
                    need = inst.check_lazy_status(**probe) or []
                    fresh = [k for k in need
                             if k in inputs and k not in kwargs]
                    if not fresh:
                        break
                    for k in fresh:
                        v = inputs[k]
                        kwargs[k] = (self._eval(own, v[0])[v[1]]
                                     if is_link(v) else v)
            else:
                # declared lazy but has no check_lazy_status: compute as a normal input
                for k in inputs:
                    if k in lazy and k not in kwargs:
                        v = inputs[k]
                        kwargs[k] = (self._eval(own, v[0])[v[1]]
                                     if is_link(v) else v)
            # a connected lazy input that was not named gets None, per ComfyUI's convention
            for k in inputs:
                if k in lazy and k not in kwargs:
                    kwargs[k] = None

        self.calls.append((ct, nid))
        res = getattr(inst, cls.FUNCTION)(**kwargs)

        if isinstance(res, dict) and "expand" in res:
            self.expansions += 1
            if self.expansions > self.max_expansions:
                raise RuntimeError(
                    f"More than {self.max_expansions} expansions: does the loop have no termination condition?")
            child = _Scope(res["expand"], parent=own)
            out = tuple(self._eval(child, item[0])[item[1]] if is_link(item)
                        else item
                        for item in res.get("result", ()))
        else:
            # Nodes may return {"ui": ..., "result": (...)}; ComfyUI pushes ui
            # to the frontend separately and only passes result downstream. This must be **unwrapped first**.
            #
            # This used to be a plain `tuple(res)`, which for such a return value yields **the dict's keys**,
            # i.e. the two strings ("ui", "result"), which are then fed downstream as outputs;
            # the symptom is downstream reporting `'str' object has no attribute 'get'`,
            # or nodes with more than two outputs reporting `IndexError: tuple index out of range`.
            #
            # It never showed up in the sandbox, because the sandbox's comfyui_pcg/__init__.py is a stub
            # that bypasses the attach_group_reporting / attach_cop_preview wrapper layers;
            # while **in the user's real ComfyUI** every node is wrapped and always returns this kind of
            # dict. So the accurate description of this bug is: "the whole test suite does not pass in the production configuration,
            # and that wrapper layer was never tested".
            if isinstance(res, dict):
                res = res.get("result", ())
            out = tuple(res)

        own.cache[nid] = out
        if self.release and own is self.root:
            self.done.add(nid)
            for v in inputs.values():
                if is_link(v) and str(v[0]) in own.prompt:
                    self._consumed(str(v[0]))
            if self.readers.get(nid, 0) <= 0:
                own.cache.pop(nid, None)          # nothing reads it: only its side effects (files, previews) mattered
        return out

# ══════════════════════════════════════════════════════════════════ Unwrapping
def unwrap(res):
    """
    Normalizes a node execution function's return value into an **output tuple**.

    Why this is needed: the real comfyui_pcg/__init__.py uses
    attach_group_reporting / attach_cop_preview to wrap **every** node's execution function;
    after wrapping it returns {"ui": ..., "result": (...)}; ComfyUI pushes ui
    to the frontend and only passes result downstream.

    If a test does `a, b = node.run(...)` directly, it gets **the dict's key names**,
    the two strings ("ui", "result"), and then an error like `'str' object has no attribute ...`
    that points nowhere near the real cause. Every place that calls run() directly must go through this.
    """
    if isinstance(res, dict):
        return tuple(res.get("result", ()))
    return res
