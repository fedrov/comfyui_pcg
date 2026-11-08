"""
Split geometry into "pieces" -- the iteration source for For-Each Block.

Matches the Iteration Method of Houdini's Block End:

    pieces        split by an attribute like name / class (one piece per distinct value)
    primitives    one piece per primitive
    points        one piece per point
    connectivity  split by connected components (saves wiring a Connectivity by hand)
    count         no split, loop over the whole geometry N times

* Key design: **the split is computed once, each piece's geometry is generated on demand**.

What is stored is a compact index of "which elements belong to piece i" (order + starts, i.e. CSR),
not N Geometry objects. Looping over the faces of a 100k-face mesh: the former is 400KB, the latter eats all memory on the spot.
And the loop advances one step at a time, so only one piece is needed at any moment; pre-generating all of them is pure waste.

order  : (M,) int32   element numbers sorted by piece number
starts : (N+1,) int64 piece i occupies order[starts[i]:starts[i+1]]
values : list         the "value" of piece i (attribute value / element number / component number), for Block Begin's
                      value / ivalue outputs
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, is_string
from .ops import delete_points, delete_prims
from .groups import resolve
from .topology import connectivity

KINDS = ("pieces", "primitives", "points", "connectivity", "count")


def _cls_of(elem: str) -> str:
    return POINT if elem == "points" else PRIM


def plan(geo: Geometry, kind="pieces", attrib="name", elem="primitives",
         count=10, group=""):
    """
    Returns (elem, order, starts, values).

    elem is the element class the pieces are attached to ("primitives" / "points") -- it decides whether extract uses
    delete_prims or delete_points, and which class piece_attribute is read from.
    count mode returns order=None, meaning "no split"; every iteration gets the whole input.
    """
    if kind == "count":
        n = max(0, int(count))
        return "primitives", None, None, list(range(n))

    if kind == "primitives":
        elem = "primitives"
    elif kind == "points":
        elem = "points"

    cls = _cls_of(elem)
    n_el = geo.count(cls)
    # group first narrows the iteration source to the selected elements. Empty = all.
    sel = (np.nonzero(resolve(geo, cls, group))[0].astype(np.int64)
           if str(group).strip() else np.arange(n_el, dtype=np.int64))
    if len(sel) == 0:
        return elem, np.zeros(0, np.int32), np.zeros(1, np.int64), []

    # Each element is its own piece: the piece number is the element's position in sel, no sorting needed
    if kind in ("primitives", "points"):
        return (elem, sel.astype(np.int32),
                np.arange(len(sel) + 1, dtype=np.int64), sel.tolist())

    # ---- split by value ----
    if kind == "connectivity":
        # Borrow the Connectivity SOP implementation instead of rewriting label propagation
        tmp = connectivity(geo, cls, "__piece__")
        key = tmp.get(cls, "__piece__")[:, 0]
    else:
        name = str(attrib).strip() or "name"
        a = geo.get(cls, name)
        if a is None:
            have = sorted(geo.attribs[cls].keys())
            raise KeyError(
                f"No attribute '{name}' on {cls}, cannot split by it. "
                f"Existing attributes: {have or '(none)'}. "
                f"Hint: add a Connectivity (PCG) first to generate class, "
                f"or change iterate_over to connectivity.")
        if a.shape[1] != 1 and not is_string(a):
            # Multi-component attributes have no natural "piece" semantics; say so clearly rather than fudging with the first component
            raise ValueError(
                f"Attribute '{name}' has {a.shape[1]} components; splitting only supports scalar or string attributes.")
        key = a[:, 0]

    key = key[sel]
    uniq, inv = np.unique(key, return_inverse=True)
    inv = inv.reshape(-1)
    # A stable sort keeps the original element order within each piece -- so the output numbering of downstream delete_*
    # is reproducible, and results do not change on another machine
    order = sel[np.argsort(inv, kind="stable")].astype(np.int32)
    counts = np.bincount(inv, minlength=len(uniq)).astype(np.int64)
    starts = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)
    return elem, order, starts, uniq.tolist()


def extract(geo: Geometry, elem, order, starts, i: int) -> Geometry:
    """Get piece i. order None means count mode; returns the whole thing."""
    if order is None:
        return geo
    cls = _cls_of(elem)
    idx = order[int(starts[i]):int(starts[i + 1])]
    mask = np.zeros(geo.count(cls), bool)
    mask[idx] = True
    # When splitting by points use delete_points: it keeps orphan points and keeps only faces with "all points in the piece"
    # -- exactly the semantics of looping over points in Houdini
    return delete_points(geo, mask) if cls == POINT else delete_prims(geo, mask)
