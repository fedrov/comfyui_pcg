"""
Group Combine (pcg79): combines several groups into a new group with set operations.

The expression is plain set algebra, with the same precedence as Python sets (high to low):
    !a  ~a       complement (universe minus a)
    a - b        difference
    a & b        intersection
    a ^ b        symmetric difference (in only one side)
    a | b        union
Parentheses nest freely. Group names may contain wildcards (`piece*` = union of all groups whose name matches); `*` is the universe.
Examples: (top & selected) - border,  !(a | b),  piece* ^ keep

Group Type = point / prim / vertex / edge. The universe for edge groups is every edge of the current topology (edge groups store
point pairs; they are mapped onto edges first, combined, and the result written back as point pairs).
Group specifiers (the Group field) can already express union and difference ("a b !c"); what is missing is intersection and symmetric difference -- that is why this node exists.
"""
from __future__ import annotations

import fnmatch
import re

import numpy as np

from .core import POINT, PRIM, VERTEX

COMBINE_CLASSES = ("point", "prim", "vertex", "edge")
_NAME = re.compile(r"[A-Za-z0-9_.*?\[\]:]+")
_OPS = set("|&^-~!() \t\n")


class _S:
    """Boolean mask wrapper: lets Python's | & ^ - ~ act directly as set operations."""
    __slots__ = ("m",)

    def __init__(self, m):
        self.m = m

    def __or__(self, o):
        return _S(self.m | o.m)

    def __and__(self, o):
        return _S(self.m & o.m)

    def __xor__(self, o):
        return _S(self.m ^ o.m)

    def __sub__(self, o):
        return _S(self.m & ~o.m)

    def __invert__(self):
        return _S(~self.m)


def _universe(geo, cls):
    """(element count, function returning a mask by name, existing group names)."""
    if cls == "edge":
        from .groups import edge_mask
        from .topology import topology
        n = topology(geo).nedges
        names = sorted(geo.edge_groups.keys())

        def get(name):
            return edge_mask(geo, geo.edge_groups[name])
        return n, get, names
    names = sorted(geo.groups[cls].keys())

    def get(name):
        return np.asarray(geo.get_group(cls, name), bool).reshape(-1)
    return geo.count(cls), get, names


def combine_mask(geo, cls, expression):
    """Expression -> (n,) bool."""
    if cls not in COMBINE_CLASSES:
        raise ValueError(f"Group Type must be one of {COMBINE_CLASSES}")
    expr = str(expression).strip()      # an empty one raises a syntax error in eval
    n, get, names = _universe(geo, cls)
    slots = []
    out, i = [], 0
    while i < len(expr):
        m = _NAME.match(expr, i)
        if m:
            tok = m.group(0)
            if tok == "*":
                mask = np.ones(n, bool)
            else:
                hit = [k for k in names if fnmatch.fnmatchcase(k, tok)]
                if not hit:
                    raise KeyError(f"{cls} has no group matching '{tok}'. Existing: "
                                   f"{names or '(none)'}")
                mask = np.zeros(n, bool)
                for k in hit:
                    mask |= get(k)
            out.append(f"_g[{len(slots)}]")
            slots.append(_S(mask))
            i = m.end()
            continue
        ch = expr[i]
        if ch not in _OPS:
            raise ValueError(f"Unrecognized character '{ch}' in expression (position {i}): "
                             f"only group names, | & ^ - ! ~ and parentheses are allowed")
        out.append("~" if ch == "!" else ch)
        i += 1
    try:
        r = eval("".join(out), {"__builtins__": {}}, {"_g": slots})
    except (SyntaxError, TypeError) as ex:
        # TypeError: things like a - - b (_S has no unary minus). After the character whitelist only group names, these
        # operators and parentheses remain, so any result that evaluates must be an _S -- no type check needed
        raise ValueError(f"Malformed expression: {expression}") from ex
    return r.m


def group_combine(geo, cls="point", expression="a & b", output="combined"):
    """Returns (geometry, report)."""
    name = str(output).strip()
    if not name:
        raise ValueError("Output Group needs a name")
    m = combine_mask(geo, cls, expression)
    g = geo.copy()
    if cls == "edge":
        from .topology import topology
        g.set_edge_group(name, np.asarray(topology(geo).edge_points[m],
                                          np.int32))
    else:
        g.set_group(cls, name, m)
    return g, {"class": cls, "members": int(m.sum()), "total": int(len(m))}
