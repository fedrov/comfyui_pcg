"""
Curve (pcg103): corresponds to Houdini's Curve SOP -- a curve clicked out in the viewport.

The point list lives in the node's Points text box (a parameter, like the Coordinates of Houdini's old Curve SOP,
not cached geometry), so saving the workflow, undo and copying the node all work as usual, and it can be edited by hand.
The viewport drawing tool (CurveTool in web/pcg_handles.js) reads and writes exactly this box.

━━ Text format (both are accepted; written back in the first one)
    one point per line   0.5, 0, 1.2
                         1, 0, -0.3
    Houdini coords       0.5,0,1.2 1,0,-0.3      (spaces separate points, commas separate components)
  Semicolons also count as line breaks. Each point has 1-3 numbers; missing components are filled with 0 ("1, 2" = (1, 2, 0)).

━━ Primitive Type
    polygon  polyline (open) / closed polygon (with Close Curve)
    nurbs    points are control points, uniform clamped knots (same as Convert), Order defaults to 4
    bezier   points are control points, piecewise Bezier (if the point count doesn't fill whole segments it is resampled by chord length, same as Convert)
"""
from __future__ import annotations

import re

import numpy as np

from .core import Geometry, POINT, PRIM

PRIM_TYPES = ("polygon", "nurbs", "bezier")

_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def parse_points(text) -> np.ndarray:
    """Text -> (n,3). See the format in the file header. A malformed point raises an error saying which one."""
    s = str(text or "").strip()
    if not s:
        return np.zeros((0, 3))
    s = s.replace(";", "\n")
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if len(lines) == 1 and "," in lines[0] and re.search(r"\d\s+[-+.\d]", lines[0]) \
            and not re.search(r",\s", lines[0]):
        toks = lines[0].split()                  # Houdini coords: spaces separate points
    else:
        toks = lines
    out = []
    for i, t in enumerate(toks):
        parts = [p for p in re.split(r"[,\s]+", t.strip()) if p]
        if not 1 <= len(parts) <= 3 or not all(_NUM.fullmatch(p) for p in parts):
            raise ValueError(f"Points: point #{i + 1} is malformed: '{t}' (expected x, y, z)")
        v = [float(p) for p in parts] + [0.0] * (3 - len(parts))
        out.append(v)
    return np.asarray(out, np.float64)


def _fmt(x):
    s = f"{float(x):.5f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def format_points(P) -> str:
    """(n,3) -> one-point-per-line text (same format as formatPoints in the frontend)."""
    return "\n".join(", ".join(_fmt(c) for c in p) for p in np.asarray(P).reshape(-1, 3))


def curve(points, prim_type="polygon", closed=False, order=4, reverse=False):
    """Returns the Geometry of one curve. With fewer than 2 points only points are output (while the first point is still being drawn)."""
    if prim_type not in PRIM_TYPES:
        raise ValueError(f"Primitive Type must be one of {PRIM_TYPES}")
    P = parse_points(points) if isinstance(points, str) else \
        np.asarray(points, np.float64).reshape(-1, 3)
    if reverse:
        P = P[::-1]
    n = len(P)
    if n < 2:
        g = Geometry.from_points(P.astype(np.float32)) if n else Geometry()
        return g
    closed = bool(closed) and n >= 3
    g = Geometry.from_mesh(P.astype(np.float32), [np.arange(n, dtype=np.int32)],
                           closed=closed)
    if prim_type == "polygon":
        return g
    from .ops import to_spline
    k = int(max(2, min(int(order), n)))
    out = to_spline(g, shape="curve", basis=prim_type, uorder=k)
    if closed:
        # Spline "closed" follows Houdini: a periodic curve. Splines here only have clamped knots, so closed = the
        # first point appended again (the curve returns to its start), not periodic knots
        P2 = np.concatenate([P, P[:1]])
        g2 = Geometry.from_mesh(P2.astype(np.float32), [np.arange(n + 1, dtype=np.int32)],
                                closed=False)
        out = to_spline(g2, shape="curve", basis=prim_type, uorder=k)
    return out
