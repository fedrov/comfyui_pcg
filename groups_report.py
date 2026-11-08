"""
Reports the group names in each node's output geometry to the frontend.

Why this step is needed: group names live in the Geometry object on the Python side; the frontend cannot see them at all.
For a downstream node to list choices on its group parameter, someone has to send those names over first.

The approach wraps each node's execution function: whenever the output contains a Geometry, its group names go into
{"ui": {"pcg_groups": [...]}}. ComfyUI sends an executed message for **any** node that returns ui,
not just OUTPUT_NODE ones, so the frontend gets them by listening to that event.

The wrapping is idempotent; calling it again does not stack.
"""
from __future__ import annotations

from .geo import Geometry, POINT, VERTEX, PRIM, DETAIL

_MARK = "_pcg_group_reporting"


def _add(acc, cls, names):
    if not names:
        return
    acc.setdefault(cls, [])
    for n in names:
        if n not in acc[cls]:
            acc[cls].append(n)


def _collect(value, groups, attribs):
    """Find Geometry in the return value and collect group names and attribute names."""
    if isinstance(value, Geometry):
        for cls in (POINT, VERTEX, PRIM):
            _add(groups, cls, sorted(value.groups.get(cls, {}).keys()))
        _add(groups, "edge", sorted(value.edge_groups.keys()))
        for cls in (POINT, VERTEX, PRIM, DETAIL):
            _add(attribs, cls, sorted(value.attribs.get(cls, {}).keys()))
    elif isinstance(value, (tuple, list)):
        for v in value:
            _collect(v, groups, attribs)


def attach_group_reporting(mappings):
    for cls in mappings.values():
        fn_name = getattr(cls, "FUNCTION", None)
        fn = getattr(cls, fn_name, None) if fn_name else None
        if fn is None or getattr(fn, _MARK, False):
            continue

        def make(orig):
            def wrapped(self, *args, **kwargs):
                out = orig(self, *args, **kwargs)
                g, a = {}, {}
                _collect(out.get("result") if isinstance(out, dict) else out, g, a)
                if not g and not a:
                    return out
                payload = {}
                if g:
                    payload["pcg_groups"] = [g]
                if a:
                    payload["pcg_attribs"] = [a]
                if isinstance(out, dict):
                    return {**out, "ui": {**(out.get("ui") or {}), **payload}}
                # Nodes that originally return a tuple get wrapped into the form with ui. ComfyUI allows any node
                # to return this; result is passed downstream as usual.
                return {"ui": payload, "result": out}
            wrapped.__dict__.update(getattr(orig, "__dict__", {}))   # carry out the markers of the inner layers
            setattr(wrapped, _MARK, True)
            # Let inspect.signature see through this layer -- it follows __wrapped__
            # to the original function automatically. Without it the signature is (*args, **kwargs), so
            # the check in test_nodes.py that "run() accepts every input declared in INPUT_TYPES"
            # is **skipped entirely** because of "has **kwargs", and not one of the 151 nodes gets checked.
            wrapped.__wrapped__ = orig
            wrapped.__name__ = getattr(orig, "__name__", "run")
            wrapped.__doc__ = getattr(orig, "__doc__", None)
            return wrapped

        setattr(cls, fn_name, make(fn))
