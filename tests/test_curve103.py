"""
pcg103: Curve (PCG) -- curves clicked out in the viewport (for the frontend drawing tool see test_handles.mjs).

  Points text   two syntaxes (one point per line / Houdini coords), semicolons, missing components padded with 0, malformed input raises
  Polygon       open polyline / Close Curve closes it; fewer than 3 points: not closed; fewer than 2 points: points only
  NURBS/Bezier  points are control points (same scheme as Convert); Order clamped to the point count; closed = back to the start
  Reverse       point order reversed
"""
import os
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))), "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy                                        # noqa: F401,E402
import numpy as np                                      # noqa: E402

from comfyui_pcg import NODE_CLASS_MAPPINGS as M       # noqa: E402
from comfyui_pcg.geo import curvedraw as C              # noqa: E402
from comfyui_pcg.geo import nurbs as NB                 # noqa: E402
from comfyui_pcg.geo.core import POINT, PRIM_POLY, PRIM_NURBS_CURVE, PRIM_BEZIER_CURVE  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def raises(fn, text=""):
    try:
        fn()
    except Exception as e:
        return text in str(e)
    return False


def PP(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


print("── Points text")
A = np.array([[0.5, 0, 1.2], [1, 0, -0.3], [2, 1, 1]])
check("one point per line", np.allclose(C.parse_points("0.5, 0, 1.2\n1, 0, -0.3\n2, 1, 1"), A))
check("Houdini coords (spaces separate points, commas separate components)", np.allclose(C.parse_points("0.5,0,1.2 1,0,-0.3 2,1,1"), A))
check("semicolon acts as newline, spaces separate components, missing ones padded with 0", np.allclose(C.parse_points("1 2 3; 4 5; 6"),
                                                     [[1, 2, 3], [4, 5, 0], [6, 0, 0]]))
check("empty text = no points", C.parse_points("  \n ").shape == (0, 3))
check("malformed point raises and says which one", raises(lambda: C.parse_points("1,2,3\n4,x,6"), "point #2")
      and raises(lambda: C.parse_points("1,2,3,4"), "point #1"))
check("format -> parse round trip unchanged (5 decimals)",
      np.allclose(C.parse_points(C.format_points(A + 1e-7)), A, atol=1e-5)
      and C.format_points([[0.5, -0.0, 3]]) == "0.5, 0, 3")

print("── Polygon")
run = lambda *a: M["PCG_Curve"]().run(*a)["result"][0]   # noqa: E731
g = run("0,0,0\n1,0,0\n1,0,1\n0,0,1", "polygon", False, 4, False)
check("open polyline: one prim, 4 points, not closed, points are the input",
      g.nprims == 1 and g.npoints == 4 and not g.prim_closed[0] and g.prim_type[0] == PRIM_POLY
      and np.allclose(PP(g), [[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]]))
g = run("0,0,0\n1,0,0\n1,0,1\n0,0,1", "polygon", True, 4, False)
check("Close Curve: closed polygon (no extra duplicate point)", g.prim_closed[0] and g.npoints == 4)
g = run("0,0,0\n1,0,0", "polygon", True, 4, False)
check("with two points Close Curve has no effect (a closed two-point polygon is a degenerate face)", not g.prim_closed[0])
g = run("1,2,3", "polygon", False, 4, False)
check("one point: points only, no prim (drawing the first point)", g.npoints == 1 and g.nprims == 0)
g = run("", "polygon", False, 4, False)
check("empty: empty geometry", g.npoints == 0 and g.nprims == 0)
g = run("0,0,0\n1,0,0\n2,1,0", "polygon", False, 4, True)
check("Reverse: point order reversed", np.allclose(PP(g), [[2, 1, 0], [1, 0, 0], [0, 0, 0]]))

print("── NURBS / Bezier")
pts = "0,0,0\n1,0,0\n2,1,0\n3,1,0\n4,0,0"
g = run(pts, "nurbs", False, 4, False)
cps = PP(g)
check("NURBS: one NURBS curve, control points are the input points", g.nprims == 1 and g.prim_type[0] == PRIM_NURBS_CURVE
      and np.allclose(cps, C.parse_points(pts)))
ev = NB.eval_curve(cps, 4, np.array([0.0, 1.0]))
check("  clamped knots: curve passes through the first and last points", np.allclose(ev, cps[[0, -1]], atol=1e-6))
g3 = run("0,0,0\n1,0,0\n2,1,0", "nurbs", False, 9, False)
check("  Order larger than the point count is clamped to it (3 points -> order 3)", g3.nprims == 1)
gc = run(pts, "nurbs", True, 4, False)
check("  closed: wraps back to the start (one extra control point, first and last coincide)",
      gc.npoints == 6 and np.allclose(PP(gc)[0], PP(gc)[-1]))
gb = run(pts, "bezier", False, 4, False)
check("Bezier: one Bezier curve, control point count = segments x 3 + 1 (if not whole segments, resampled by chord length)",
      gb.prim_type[0] == PRIM_BEZIER_CURVE and (gb.npoints - 1) % 3 == 0)
check("malformed Primitive Type raises", raises(lambda: C.curve(pts, "spline"), "Primitive Type"))

print("── Node")
it = M["PCG_Curve"].INPUT_TYPES()["required"]
check("widget: points (multiline) / prim_type / closed / order / reverse, default = empty open polyline",
      list(it) == ["points", "prim_type", "closed", "order", "reverse"]
      and it["points"][1]["multiline"] and it["prim_type"][0][0] == "polygon"
      and it["closed"][1]["default"] is False)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
