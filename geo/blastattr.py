"""
Blast by Attribute SOP -- deletes elements by the value of one attribute (or just collects them into a group).

Writing `@density < 0.5` in Blast's Group does the same, but that is the group-expression way; this node offers
the parameter set from the SideFX docs: attribute name + three criteria Threshold / Range / Width + Invert +
Output: Blast / Group.

The criteria follow the docs verbatim:
    threshold   values **below** the threshold match (strictly less; the docs don't say whether equal counts, equal is kept)
    range       min <= value <= max (the docs only say "within the range" without saying whether endpoints are included;
                following the closed-interval wording of Width, both ends are included)
    width       [center - width/2, center + width/2] (the docs write exactly this closed interval)
Invert negates the matched set. Elements outside Group (the Run Over class) do not take part and stay as they are --
Invert doesn't touch them either.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, is_string
from .groups import resolve
from .ops import delete_points, delete_prims

CLASSES = (POINT, PRIM)
OUTPUTS = ("blast", "group")
MODES = ("threshold", "range", "width")


def condition_mask(values, mode="threshold", threshold=0.5, vmin=0.0, vmax=1.0,
                   center=0.5, width=0.2):
    """(n,) values -> match mask (Invert not applied)."""
    v = np.asarray(values, np.float64).reshape(-1)
    if mode == "threshold":
        return v < float(threshold)
    if mode == "range":
        return (v >= float(vmin)) & (v <= float(vmax))
    if mode == "width":
        h = 0.5 * float(width)
        return (v >= float(center) - h) & (v <= float(center) + h)
    raise ValueError(f"Mode must be one of {MODES}")


def blast_by_attribute(geo, group="", cls=POINT, attribute="", output="blast",
                       mode="threshold", invert=False, threshold=0.5,
                       vmin=0.0, vmax=1.0, center=0.5, width=0.2,
                       output_group="group1", remove_unused_points=True):
    if geo is None:
        return Geometry()
    if cls not in CLASSES:
        raise ValueError(f"Run Over must be one of {CLASSES}")
    if output not in OUTPUTS:
        raise ValueError(f"Output must be one of {OUTPUTS}")
    nm = str(attribute).strip()
    if not nm:
        raise ValueError("Attribute Name is empty.")
    a = geo.get(cls, nm)
    if a is None:
        have = sorted(geo.attribs[cls].keys())
        raise KeyError(f"{cls} has no attribute '{nm}'. Existing: {have or '(none)'}")
    if is_string(a):
        raise ValueError(f"'{nm}' is a string attribute and cannot be compared with numbers.")
    if a.shape[1] != 1:
        # The docs don't say which component of a vector attribute to use / whether to use its length, so we don't guess
        raise ValueError(f"'{nm}' has {a.shape[1]} components; Blast by Attribute only takes single-value attributes"
                         f" (split one component out of a vector first with a Wrangle / Attribute Promote).")
    hit = condition_mask(a[:, 0], mode, threshold, vmin, vmax, center, width)
    if invert:
        hit = ~hit
    hit &= resolve(geo, cls, group)

    if output == "group":
        g = geo.copy()
        g.set_group(cls, str(output_group).strip() or "group1", hit)
        return g
    if cls == POINT:
        return delete_points(geo, ~hit)
    # With Remove Unused Points off, points left behind by deleted primitives are spared
    return delete_prims(geo, ~hit, keep_points=not remove_unused_points)
