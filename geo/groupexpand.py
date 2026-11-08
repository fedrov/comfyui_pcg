"""
Group Expand / Shrink and Attribute Fade -- two uses of "how far from this group".

Group Expand uses the distance as a **threshold** (everything <= N is included), Attribute Fade uses it as a **gradient**
(a curve interpolated by distance). How distance is computed: see `adjacency.py`.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Shrink = Expand the complement, then invert
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
In morphology, erosion is "dilate the complement and invert"; copied here, saving a separate shrink implementation.
Does that mean **the outer boundary of the geometry counts as complement**? -- No: the complement contains only elements that are really
outside the group, and outside the geometry there is nothing, so the ring along the geometry's boundary isn't eroded. This
matches Houdini's Group Expand but differs from image-processing dilate/erode (outside an image's border
is "nothing", usually treated as 0); worth noting.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Fade is 1 inside the group and falls to 0 outside along a curve
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    inside the group          inside_value (default 1)
    outside, d steps/metres   ramp(1 - d/radius) * inside_value
    beyond the radius         0

The most common use of this attribute is as a mask for Transform / Attribute Adjust / Noise --
"raise only this patch, with a smooth transition at the edge". So the default ramp is smooth rather than linear:
linear has a first-derivative crease at the group boundary, and a visible ridge appears when pushed.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM
from .groups import resolve, to_point_mask, to_prim_mask
from . import ramp as _ramp
from .adjacency import distance_from, METRICS

MODES = ("expand", "shrink")
COMBINE = ("set", "add", "multiply", "max", "min")
CLASSES = (POINT, PRIM)
RAMP_MODES = _ramp.MODES


def _sel(geo, cls, group):
    """An empty group means "the empty set" here rather than "select all" -- expanding an all-selecting group is a no-op."""
    if not str(group or "").strip():
        return np.zeros(geo.count(cls), bool)
    return resolve(geo, cls, group)


def expand_mask(geo, cls, seed, mode="expand", metric="steps", radius=1.0):
    """(N,) mask after expanding or shrinking."""
    if mode not in MODES:
        raise ValueError(f"Mode must be one of {MODES}")
    seed = np.asarray(seed, bool)
    if mode == "shrink":
        # Erosion = dilate the complement and invert
        if not (~seed).any():
            return seed.copy()
        _, far = distance_from(geo, cls, ~seed, metric, radius)
        return seed & far
    if not seed.any():
        return seed.copy()
    _, far = distance_from(geo, cls, seed, metric, radius)
    return ~far


def group_expand(geo, cls=POINT, group="", name="", mode="expand",
                 metric="steps", radius=1.0, output_falloff=False,
                 falloff_attrib="falloff"):
    """
    Expands / shrinks a group, writing it back to the same group or a new one.

    Empty name = modify the group that group refers to in place (requires group to be a plain group name); with a name
    the result is written to a new group and the original is left alone.
    """
    if geo is None:
        return Geometry()
    if cls not in CLASSES:
        raise ValueError(f"Class must be one of {CLASSES} -- "
                         f"vertex and detail have no adjacency to walk.")
    if metric not in METRICS:
        raise ValueError(f"Metric must be one of {METRICS}")
    n = geo.count(cls)
    if n == 0:
        return geo.copy()

    seed = _sel(geo, cls, group)
    out = expand_mask(geo, cls, seed, mode, metric, radius)

    nm = str(name or "").strip()
    if not nm:
        nm = str(group or "").strip()
        # Must be a group **name**: starts with a letter or underscore, the rest only letters, digits, _ and -.
        # isalnum alone isn't enough -- "0-5" becomes "05" once the dash is removed and would pass
        if (not nm or not (nm[0].isalpha() or nm[0] == "_")
                or not all(c.isalnum() or c in "_-" for c in nm)):
            raise ValueError(
                "An empty Output Group means rewriting the group Group refers to in place, so Group "
                "must be a plain group name (not a number range or an @ expression). "
                f"Group is currently '{group}' -- enter an Output Group name.")
    g = geo.copy()
    g.set_group(cls, nm, out)
    if output_falloff:
        d, far = distance_from(geo, cls, seed, metric, radius)
        f = np.where(seed, 1.0,
                     np.where(far, 0.0,
                              1.0 - d / max(float(radius), 1e-12)))
        g.set(cls, str(falloff_attrib).strip() or "falloff",
              f[:, None].astype(np.float32), owned=True)
    return g


def fade(geo, name="fade", cls=POINT, group="", metric="steps", radius=3.0,
         falloff_ramp="0:0  1:1", ramp_mode="smooth", inside_value=1.0,
         outside_value=0.0, invert=False, combine="set",
         from_boundary=False):
    """
    Writes a fade attribute starting from a group. Matches Houdini's Attribute Fade.

    With from_boundary=True the falloff happens **inside the group**: the ring along the boundary is 0, rising towards
    1 further in, and everything outside the group is 0 -- a soft selection that is full in the middle of a region and closes smoothly at its edges.
    The default (False) is the reverse: full value throughout the group, falling off outwards from its outer edge.
    """
    if geo is None:
        return Geometry()
    if cls not in CLASSES:
        raise ValueError(f"Class must be one of {CLASSES}")
    if metric not in METRICS:
        raise ValueError(f"Metric must be one of {METRICS}")
    if combine not in COMBINE:
        raise ValueError(f"Combine must be one of {COMBINE}")
    nm = str(name or "").strip()
    if not nm:
        raise ValueError("Attribute Name is empty.")
    n = geo.count(cls)
    if n == 0:
        return geo.copy()

    seed = _sel(geo, cls, group)
    if not seed.any():
        raise ValueError(
            f"Group '{group}' selects no elements on {cls} -- "
            f"without a starting set there is no gradient.")

    if from_boundary:
        # Elements of the group along the boundary get 0, approaching 1 further into the group; everything outside is 0.
        # This is a "soft selection": full in the middle of a region, closing smoothly at the edges, usable directly as a mask.
        # Note **the deep interior must get 1, not 0** -- anything farther than radius from the boundary is fully inside,
        # and distance_from marks everything beyond the radius as far, so it has to be interpreted the other way round here
        ring = seed & ~expand_mask(geo, cls, seed, "shrink", "steps", 1)
        src = ring if ring.any() else seed
        d, far = distance_from(geo, cls, src, metric, radius)
        t = np.where(seed,
                     np.where(far, 1.0, d / max(float(radius), 1e-12)),
                     0.0)
    else:
        d, far = distance_from(geo, cls, seed, metric, radius)
        t = np.where(seed, 1.0,
                     np.where(far, 0.0,
                              1.0 - d / max(float(radius), 1e-12)))

    v = _ramp.remap(np.clip(t, 0.0, 1.0), falloff_ramp, ramp_mode)
    if invert:
        v = 1.0 - v
    v = float(outside_value) + (float(inside_value)
                                - float(outside_value)) * v

    cur = geo.get(cls, nm)
    if cur is not None and cur.shape[1] == 1:
        base = cur[:, 0].astype(np.float64)
        dt = cur.dtype
    else:
        base = np.full(n, 1.0 if combine == "multiply" else 0.0)
        dt = np.dtype(np.float32)
    out = (v if combine == "set" else
           base + v if combine == "add" else
           base * v if combine == "multiply" else
           np.maximum(base, v) if combine == "max" else
           np.minimum(base, v))
    g = geo.copy()
    g.set(cls, nm, (np.rint(out) if dt.kind in "iub" else out
                    )[:, None].astype(dt), owned=True)
    return g
