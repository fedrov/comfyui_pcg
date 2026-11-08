"""
pcg100 · package s3_curves: parameters / menu items filled in against the SideFX docs.

  Resample    Method (Even Length / X / Y / Z), Measure (Along Arc / Along Chord), Maintain Primitive
              Order, Resample by Polygon Edge, Allow Primitive Attributes to Override, Maintain Last
              Vertex, Randomize First Segment Length, Output as Polygon Curves to be Subdivided Later
  Cross Section Surface  new node PCG_CrossSectionSurfaceHou (Houdini semantics): four end cap modes, eight Surface Types, UV, row/column attributes
  Curve Intersect  Output gains Cut / Extract (left × right, second input, Find All, odd/even pieces, Affect, Keep Original)
  Circle Spline    Spline Type = Helix (three axis modes), splinetype attribute, Pseudo-Arclength, curveu / tangent
  Copy to Curves   Sample By gains Curve Points (Houdini's Frame / Rotations / Scales / Attributes), Source Group
  Chain            Chain Mode gains Deform Along Curve (Houdini's pieces, pattern, mapping, end behaviour, deformation, alignment, output)
  Edge Equalize    Method gains Average / Longest / Shortest, Group Type, Output Edge Group

All checked against hand-computed numbers (coordinates, point counts, chord-length equations, B-spline limit positions); every new option has a negative control.
"Bit-identical to before the change at default values": digests computed before the change (commit c87c5d9) from the same set of calls passing only old parameters,
hard-coded in GOLDEN (no git dependency, runs on the device too); `--digests` prints the current digests.
"""
import hashlib
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
from comfyui_pcg import panel as PANEL                  # noqa: E402
from comfyui_pcg.geo import ops                         # noqa: E402
from comfyui_pcg.geo import curves2 as CV               # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, VERTEX, PRIM, DETAIL, PRIM_NURBS_CURVE  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def P_(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def run(nid, **over):
    kw = {}
    for part in ("required", "optional"):
        for k, spec in M[nid].INPUT_TYPES().get(part, {}).items():
            if isinstance(spec[0], (list, tuple)):
                kw[k] = spec[1]["default"] if len(spec) > 1 and "default" in spec[1] else spec[0][0]
            elif len(spec) > 1 and isinstance(spec[1], dict) and "default" in spec[1]:
                kw[k] = spec[1]["default"]
    kw.update(over)
    r = getattr(M[nid](), M[nid].FUNCTION)(**kw)
    return r["result"][0] if isinstance(r, dict) else r[0]


def raises(fn, word=""):
    try:
        fn()
    except Exception as e:                              # noqa: BLE001
        return word in str(e)
    return False


def digest(g):
    """Bit-exact fingerprint of a geometry: topology + all attributes + groups."""
    h = hashlib.sha1()
    for a in (g.vertex_point, g.prim_offset, g.prim_closed, g.prim_type):
        h.update(np.ascontiguousarray(a).tobytes())
    for cls in (POINT, VERTEX, PRIM):
        for k in sorted(g.attribs[cls]):
            v = np.asarray(g.attribs[cls][k])
            h.update(k.encode())
            h.update(str(v.tolist()).encode() if v.dtype.kind in "OUS"
                     else np.ascontiguousarray(v).tobytes())
        for k in sorted(g.groups[cls]):
            h.update(k.encode())
            h.update(np.ascontiguousarray(g.groups[cls][k]).tobytes())
    for k in sorted(g.edge_groups):
        h.update(k.encode())
        h.update(np.ascontiguousarray(np.sort(np.sort(np.asarray(g.edge_groups[k]).reshape(-1, 2), 1), 0)).tobytes())
    return h.hexdigest()[:16]


def polyline(pts, closed=False, **attrs):
    g = Geometry.from_mesh(np.asarray(pts, np.float32), [np.arange(len(pts), dtype=np.int32)],
                           closed=closed)
    for k, v in attrs.items():
        g.set(POINT, k, np.asarray(v, np.float32).reshape(len(pts), -1))
    return g


def polylines(lines, closed=False):
    return ops.merge(*[polyline(p, closed) for p in lines])


opts = lambda k, n: list(M[k].INPUT_TYPES()["required"][n][0])  # noqa: E731


def close(a, b, e=1e-5):
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    try:
        return bool(np.all(np.abs(a - b) <= e))
    except ValueError:                                  # shapes don't match
        return False


def prim_P(g, i):
    return P_(g)[g.prim_points(i)]


def chords(Q):
    return np.linalg.norm(np.diff(Q, axis=0), axis=1)


# ════════════════════════════════════════════════════════ digests from before the change
def fixtures():
    from comfyui_pcg.geo import build
    F = {}
    La = polyline([(0, 0, 0), (1, 0, 0), (1, 1, 0), (3, 1, 2)], Cd=np.random.default_rng(3).random((4, 3)))
    La.set_string(POINT, "name", np.array(["a", "b", "c", "d"], object))
    sqr = polyline([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], closed=True)
    thr = polylines([[(0, 0, 0), (1, 0, 0)], [(0, 1, 0), (1, 1, 0)], [(0, 2, 0), (1, 2, 0)]])
    mix = ops.merge(La, sqr, thr)
    mix.set_group(PRIM, "sel", np.arange(mix.nprims) % 2 == 0)
    F["mix"] = mix
    ang = np.linspace(0, 2 * np.pi, 9)[:-1]
    secs = ops.merge(*[polyline([(np.cos(a) * r, np.sin(a) * r, z) for a in ang], closed=True)
                       for r, z in ((1, 0), (1.5, 1), (0.8, 2))])
    F["secs"] = secs
    F["guides"] = ops.merge(*[polyline([(np.cos(a) * r, np.sin(a) * r, z) for r, z in ((1, 0), (1.5, 1), (0.8, 2))])
                              for a in ang[::2]])
    F["opensecs"] = polylines([[(0, 0, z), (1, 0.3 * z, z), (2, 0, z), (3, 0.2, z)] for z in (0, 1, 2.5)])
    F["cross"] = polylines([[(0, 0, 0), (2, 0, 2)], [(0, 0, 2), (2, 0, 0)], [(1, 0, -1), (1, 0, 3), (0.2, 0, 1.5), (1.8, 0, 1.0)]])
    F["zig"] = polyline([(0, 0, 0), (1, 1, 0), (2, 0, 0), (3, 1, 0.5), (4, 0, 0)])
    F["ring"] = polyline([(np.cos(a), 0, np.sin(a)) for a in np.linspace(0, 2 * np.pi, 7)[:-1]], closed=True)
    F["box"] = build.box(size=(0.2, 0.1, 0.4))
    F["curve"] = polyline([(0, 0, 0), (2, 0, 0), (3, 0, 1), (3, 1, 3)])
    gr = build.grid(size_x=2, size_z=2, cols=5, rows=5)
    P = P_(gr)
    row = sorted([i for i in range(gr.npoints) if abs(P[i, 0]) < 1e-6], key=lambda i: P[i, 2])
    P[:, 0] += 0.3 * np.sin(3 * P[:, 2]) * (1 + P[:, 2])
    gr.set(POINT, "P", P.astype(np.float32))
    gr.set_edge_group("e", [(row[k], row[k + 1]) for k in range(len(row) - 1)])
    F["grid"] = gr
    return F


def old_cases():
    """Pass only parameters that existed before the change (new widgets take their defaults)."""
    F = fixtures()
    out = {}
    mix = F["mix"]
    for nm, kw in (("rs_len", {}), ("rs_len03", dict(length=0.3, even_last_segment=False)),
                   ("rs_seg7", dict(method="segment_count", segments=7)),
                   ("rs_cap", dict(length=0.05, use_max_segments=True, max_segments=5)),
                   ("rs_pts", dict(group="sel", create_only_points=True)),
                   ("rs_attr", dict(group="sel", use_out_attribs=True)),
                   ("rs_subd", dict(treat_polygons_as="subdivision_curves")),
                   ("rs_interp", dict(group="sel", treat_polygons_as="interpolating_curves"))):
        out[nm] = run("PCG_Resample", geo=mix, **kw)
    out["css_cubic"] = run("PCG_CrossSectionSurface", sections=F["secs"], guides=F["guides"])
    out["css_lin"] = run("PCG_CrossSectionSurface", sections=F["secs"], interpolation="linear",
                         divisions_s=3, divisions_t=2)
    out["css_open"] = run("PCG_CrossSectionSurface", sections=F["opensecs"])
    for pl in ("xz", "3d", "xy"):
        for o in ("split", "points"):
            out[f"ci_{pl}_{o}"] = run("PCG_CurveIntersect", geo=F["cross"], plane=pl, output=o, tolerance=0.01)
    out["ci_noself"] = run("PCG_CurveIntersect", geo=F["cross"], self_intersect=False)
    out["cs_zig"] = run("PCG_CircleSpline", geo=F["zig"])
    out["cs_ring"] = run("PCG_CircleSpline", geo=F["ring"], divisions=5)
    out["ctc_count"] = run("PCG_CopyToCurves", source=F["box"], curves=F["curve"], count=5)
    out["ctc_spacing"] = run("PCG_CopyToCurves", source=F["box"], curves=F["curve"], mode="spacing", spacing=0.7,
                             start_offset=0.2, end_offset=0.3, roll=10, roll_step=15)
    out["ctc_ring"] = run("PCG_CopyToCurves", source=F["box"], curves=F["ring"], count=7, up_x=1.0, up_y=0.0)
    out["ch_fit"] = run("PCG_Chain", source=F["box"], curves=F["curve"])
    out["ch_nofit"] = run("PCG_Chain", source=F["box"], curves=F["ring"], spacing=0.05, fit=False, roll=20)
    for m in ("arc_length", "chord"):
        out["ee_" + m] = run("PCG_EdgeEqualize", geo=F["grid"], edges="e", measure=m)
    return {k: digest(v) for k, v in out.items()}


# digests from running old_cases() before the change (c87c5d9)
GOLDEN = {
    "rs_len": "0eeda2fe95136597",
    "rs_len03": "4df0df37246f528b",
    "rs_seg7": "f35622d8c96e140b",
    "rs_cap": "7af6c23edc01cfe7",
    "rs_pts": "64e5ad5e92711c4a",
    "rs_attr": "f6e7e13d059103e0",
    "rs_subd": "c9a27f14df85e29b",
    "rs_interp": "6cd52bee717fa0ce",
    "css_cubic": "031067c8217fa59a",
    "css_lin": "40d1d4a857efb223",
    "css_open": "eeafad8c1a109c94",
    "ci_xz_split": "0e2815a828287c00",
    "ci_xz_points": "8ac1b9a1ed7771bc",
    "ci_3d_split": "0e2815a828287c00",
    "ci_3d_points": "8ac1b9a1ed7771bc",
    "ci_xy_split": "d19d1c5e27576253",
    "ci_xy_points": "be9acab5340b6e0b",
    "ci_noself": "f951b8a4a3543269",
    "cs_zig": "13b7c1e271ad063e",
    "cs_ring": "25f01222be0c470a",
    "ctc_count": "c7d044b4e83438e1",
    "ctc_spacing": "811fd8d9621a2a88",
    "ctc_ring": "2e47bc4f9fffc584",
    "ch_fit": "19204b15118f5fc8",
    "ch_nofit": "8c3e494cfea68900",
    "ee_arc_length": "c6e9a07488601828",
    "ee_chord": "7f576f7782c3344f",
}

if "--digests" in sys.argv:
    import json
    print(json.dumps(old_cases(), indent=1))
    sys.exit(0)


# ════════════════════════════════════════════════════════════════ Resample
RS = lambda g, **kw: run("PCG_Resample", geo=g, **kw)  # noqa: E731
Lsh = polyline([(0, 0, 0), (1, 0, 0), (1, 1, 0)])                  # L shape, both edges length 1
Lsh2 = polyline([(0, 0, 0), (1, 0, 0), (1, 0.5, 0)])               # second edge length 0.5

sec("Resample: Method (Even X / Y / Z measure only that axis)")
check("menu tokens and order", opts("PCG_Resample", "measure_method") == ["even_length", "even_x", "even_y", "even_z"])
g = RS(Lsh, method="segment_count", segments=4, measure_method="even_x")
check("Even X, 4 segments: x = 0, .25, .5, .75 on the first edge, end point (1,1,0) (the tail with constant x is not lost)",
      close(P_(g), [(0, 0, 0), (.25, 0, 0), (.5, 0, 0), (.75, 0, 0), (1, 1, 0)]), P_(g).round(3).tolist())
g = RS(Lsh, method="segment_count", segments=4, measure_method="even_y")
check("Even Y, 4 segments: the first edge with constant y is skipped entirely, corner (1,0,0) does not appear",
      close(P_(g), [(0, 0, 0), (1, .25, 0), (1, .5, 0), (1, .75, 0), (1, 1, 0)]), P_(g).round(3).tolist())
g = RS(Lsh, method="segment_count", segments=4)
check("negative control: Even Length, 4 segments: steps of .5 by arc length -> corner (1,0,0) is the 2nd",
      close(P_(g), [(0, 0, 0), (.5, 0, 0), (1, 0, 0), (1, .5, 0), (1, 1, 0)]))
g = RS(polyline([(0, 0, 0), (0, 0, 2)]), method="segment_count", segments=3, measure_method="even_x")
check("no extent along that axis (Even X with constant x): only start and end points", close(P_(g), [(0, 0, 0), (0, 0, 2)]))
g = RS(polyline([(0, 0, 0), (0, 0, 3)]), length=1.0, measure_method="even_z")
check("Even Z, Length 1, z extent 3: 4 points z = 0,1,2,3", close(P_(g)[:, 2], [0, 1, 2, 3]))
zig = polyline([(0, 0, 0), (1, 1, 0), (2, 0, 0), (3, 1, 0)])
g = RS(zig, length=0.5, measure_method="even_x")
check("Even X, zigzag, Length .5: neighbouring x differ by exactly .5 (true chord length is not .5)",
      close(np.diff(P_(g)[:, 0]), 0.5) and not close(chords(P_(g)), 0.5), P_(g).round(3).tolist())
check("Even X points have y on the polyline (x = .5 -> y = .5, x = 1.5 -> y = .5)", close(P_(g)[[1, 3], 1], [.5, .5]))
check("bad Method raises", raises(lambda: ops.resample(Lsh, measure_method="even_w"), "Method"))

sec("Resample:Measure(Along Arc / Along Chord)")
check("menu tokens", opts("PCG_Resample", "measure") == ["along_arc", "along_chord"])
g = RS(Lsh, length=1.2, even_last_segment=False, measure="along_chord")
y = np.sqrt(1.2 ** 2 - 1)
check("Along Chord, Length 1.2, not even: the second point is at (1, √(1.44-1)) = (1, .6633), then the end point",
      close(P_(g), [(0, 0, 0), (1, y, 0), (1, 1, 0)]), P_(g).round(4).tolist())
g = RS(Lsh, length=1.2, even_last_segment=False)
check("negative control: Along Arc with the same parameters -> arc length 1.2 is at (1, .2)", close(P_(g), [(0, 0, 0), (1, .2, 0), (1, 1, 0)]))
g = RS(Lsh, length=0.8, measure="along_chord")
check("Along Chord, Length .8, even: 2 steps + tail .2254/.8 -> rounds to 2 segments; the midpoint with equal chords is exactly the corner (1,0,0)",
      close(P_(g), [(0, 0, 0), (1, 0, 0), (1, 1, 0)]), P_(g).round(4).tolist())
g = RS(Lsh, length=0.7, measure="along_chord")
ch = chords(P_(g))
check("Along Chord, Length .7, even: 3 chords all equal, from start to end", len(ch) == 3 and close(ch, ch[0], 1e-6)
      and close(P_(g)[[0, -1]], [(0, 0, 0), (1, 1, 0)]), ch.round(5).tolist())
ga = RS(Lsh, length=0.7)
check("negative control: Along Arc with 3 segments has unequal chords (.667, .471, .667)", close(chords(P_(ga)), [2 / 3, np.sqrt(2) / 3, 2 / 3]))
g = RS(Lsh, method="segment_count", segments=2, measure="along_chord")
check("Along Chord, exactly 2 segments: chords both 1 (the corner)", close(P_(g), [(0, 0, 0), (1, 0, 0), (1, 1, 0)]))
g = RS(Lsh, length=0.8, use_max_segments=True, max_segments=1, measure="along_chord")
check("Along Chord + Maximum Segments capped at 1: only the ends remain", close(P_(g), [(0, 0, 0), (1, 1, 0)]))
circ = polyline([(np.cos(a), np.sin(a), 0) for a in np.linspace(0, 2 * np.pi, 721)[:-1]], closed=True)
g = RS(circ, method="segment_count", segments=6, measure="along_chord")
ch = chords(np.concatenate([P_(g), P_(g)[:1]]))
check("closed circle (720 edges) Along Chord 6 segments: 6 points, all 6 chords equal (≈ 1, regular hexagon side)",
      g.npoints == 6 and close(ch, ch[0], 1e-6) and abs(ch[0] - 1) < 1e-3 and bool(g.prim_closed[0]), ch.round(5).tolist())
g = RS(zig, length=0.5, measure_method="even_x", measure="along_chord", even_last_segment=False)
check("Along Chord + Even X: neighbouring x differ by .5", close(np.diff(P_(g)[:, 0]), 0.5), P_(g).round(3).tolist())
check("bad Measure raises", raises(lambda: ops.resample(Lsh, measure="along_x"), "Measure"))

sec("Resample: Resample by Polygon Edge (corners are all kept)")
g = RS(Lsh2, length=0.3, resample_by_edge=True)
check("edges of length 1 and .5, Length .3: rounded to 3 / 2 segments each -> 6 points, corner (1,0,0) included",
      close(P_(g), [(0, 0, 0), (1 / 3, 0, 0), (2 / 3, 0, 0), (1, 0, 0), (1, .25, 0), (1, .5, 0)]), P_(g).round(3).tolist())
g = RS(Lsh2, length=0.3)
check("negative control: off -> total length 1.5 / .3 = 5 even segments, no corner", close(P_(g)[:, 0], [0, .3, .6, .9, 1, 1])
      and not any(close(p, (1, 0, 0)) for p in P_(g)))
g = RS(Lsh2, method="segment_count", segments=2, resample_by_edge=True)
check("by segment count 2: 2 segments per edge -> 5 points", close(P_(g), [(0, 0, 0), (.5, 0, 0), (1, 0, 0), (1, .25, 0), (1, .5, 0)]))
g = RS(Lsh2, length=0.25, resample_by_edge=True, measure_method="even_y")
check("Even Y + by edge: the edge with constant y keeps only its ends, second edge .5/.25 = 2 segments", close(P_(g), [(0, 0, 0), (1, 0, 0), (1, .25, 0), (1, .5, 0)]))
sq = polyline([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], closed=True)
g = RS(sq, method="segment_count", segments=2, resample_by_edge=True)
check("closed square, 2 segments per edge: 8 points, all 4 corners present, still closed",
      g.npoints == 8 and bool(g.prim_closed[0]) and close(P_(g)[::2], [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]))
g = RS(Lsh2, length=0.3, even_last_segment=False, resample_by_edge=True)
check("by edge, not even: each edge steps by .3, short tails kept, corners present",
      close(P_(g)[:, 0], [0, .3, .6, .9, 1, 1, 1]) and close(P_(g)[4:, 1], [0, .3, .5]), P_(g).round(3).tolist())
g = RS(Lsh2, length=0.3, resample_by_edge=True, treat_polygons_as="interpolating_curves")
gb = RS(Lsh2, length=0.3, treat_polygons_as="interpolating_curves")
check("by edge has no effect when Treat Polygons As is not straight edges (the densified polyline has no 'edges' to speak of)", digest(g) == digest(gb))

sec("Resample:Allow Primitive Attributes to Override Parameters")
two = polylines([[(0, 0, 0), (1, 0, 0)], [(0, 1, 0), (1, 1, 0)], [(0, 2, 0), (1, 2, 0)], [(0, 3, 0), (1, 3, 0)]])
two.set(PRIM, "segment_length", np.array([[0.5], [0.25], [0.0], [0.0]], np.float32))
two.set(PRIM, "num_segments", np.array([[0], [2], [0], [4]], np.int32))
g = RS(two, length=0.1, attrib_override=True)
cnt = [len(g.prim_points(i)) for i in range(g.nprims)]
# prim 2: both ≤ 0 -> not resampled, unchanged (placed first: untouched prims come first)
check("prim attribute override: untouched (both toggles turned off) kept as-is and first; .5 -> 3 points; .25 but capped at 2 segments -> 3 points; only segment count 4 -> 5 points",
      cnt == [2, 3, 3, 5] and close(prim_P(g, 0), [(0, 2, 0), (1, 2, 0)])
      and close(prim_P(g, 2)[:, 0], [0, .5, 1]) and close(prim_P(g, 3)[:, 0], [0, .25, .5, .75, 1]), cnt)
g = RS(two, length=0.1)
check("negative control: off -> attributes ignored, all four use .1 -> 11 points each", [len(g.prim_points(i)) for i in range(g.nprims)] == [11] * 4)
one = polyline([(0, 0, 0), (1, 0, 0)])
one.set(PRIM, "num_segments", np.array([[3]], np.int32))
g = RS(one, method="segment_count", segments=5, attrib_override=True)
check("in Segment Count mode num_segments overrides Segments (5 -> 3)", g.npoints == 4)
one.set(PRIM, "segment_length", np.array([[0.5]], np.float32))
g = RS(one, method="segment_count", segments=5, attrib_override=True)
check("in Segment Count mode segment_length > 0 turns the length toggle on: steps of .5 -> 3 points (segment count 3 does not cap)", g.npoints == 3)

sec("Resample:Maintain Last Vertex")
line = polyline([(0, 0, 0), (1, 0, 0)])
g = RS(line, length=0.3, even_last_segment=False)
check("on (default): 0, .3, .6, .9, 1", close(P_(g)[:, 0], [0, .3, .6, .9, 1]))
g = RS(line, length=0.3, even_last_segment=False, maintain_last_vertex=False)
check("off: tail shorter than one step, end point dropped -> 0, .3, .6, .9", close(P_(g)[:, 0], [0, .3, .6, .9]))
g = RS(line, length=0.25, even_last_segment=False, maintain_last_vertex=False)
check("off but divides exactly: the end point is a step position, still there", close(P_(g)[:, 0], [0, .25, .5, .75, 1]))
g = RS(Lsh, length=1.2, even_last_segment=False, maintain_last_vertex=False, measure="along_chord")
check("Along Chord off: only (0,0,0), (1,.6633,0) remain", close(P_(g), [(0, 0, 0), (1, y, 0)]))
g1 = RS(sq, length=0.3, even_last_segment=False, maintain_last_vertex=False)
g2 = RS(sq, length=0.3, even_last_segment=False)
check("closed curves are unaffected (the end point is the start point)", digest(g1) == digest(g2) and g1.npoints == 14)

sec("Resample:Randomize First Segment Length")
lines2 = polylines([[(0, 0, 0), (1, 0, 0)], [(0, 1, 0), (1, 1, 0)]])
g = RS(lines2, length=0.25, even_last_segment=False, randomize_first=True)
r = [0.25 * (1 - np.random.default_rng(k).random()) for k in (0, 1)]
a, b = prim_P(g, 0)[:, 0], prim_P(g, 1)[:, 0]
check("first segment length = .25 × a (0,1] random number (seed = prim number), then steps of .25, end point present",
      close(a[1], r[0]) and close(b[1], r[1]) and close(np.diff(a)[1:-1], .25) and close(a[-1], 1), (a.round(4).tolist(), r))
check("the first segments of the two curves differ in length (seeded by prim number)", abs(a[1] - b[1]) > 1e-4 and 0 < a[1] <= .25 and 0 < b[1] <= .25)
g = RS(lines2, length=0.25, randomize_first=True)
a = prim_P(g, 0)[:, 0]
n_rest = max(1, round((1 - r[0]) / .25))
check("even: the length left after the first segment is divided evenly", close(a[1], r[0]) and len(a) == n_rest + 2 and close(np.diff(a)[1:], (1 - r[0]) / n_rest))
g = RS(lines2, length=0.25, even_last_segment=False)
check("negative control: off -> the first segment is .25", close(prim_P(g, 0)[1, 0], .25))
g = RS(lines2, method="segment_count", segments=4, randomize_first=True)
check("no effect when only by segment count", close(prim_P(g, 0)[:, 0], [0, .25, .5, .75, 1]))
g = RS(Lsh, length=0.5, even_last_segment=False, randomize_first=True, measure="along_chord")
Q = P_(g)
r0 = 0.5 * (1 - np.random.default_rng(0).random())
check("Along Chord: first chord = the random length, then each chord .5 (except a short last one)",
      close(np.linalg.norm(Q[1] - Q[0]), r0) and close(chords(Q)[1:-1], .5) and close(Q[-1], (1, 1, 0)), chords(Q).round(4).tolist())
lines2b = polylines([[(0, 0, 0), (0.1, 0, 0)]])
g = RS(lines2b, length=0.5, randomize_first=True)
check("curve shorter than the random first segment: only the ends remain", close(P_(g)[:, 0], [0, .1]))
g = RS(lines2b, length=0.5, randomize_first=True, measure="along_chord", even_last_segment=False)
check("Along Chord, whole curve inside the sphere of the random first segment: only the ends remain", close(P_(g)[:, 0], [0, .1]))
g = RS(lines2, group="0", length=0.25, even_last_segment=False, randomize_first=True,
       treat_polygons_as="interpolating_curves")
check("the seed is the input prim number (same even when Treat Polygons As densification reorders internally): prim 0 first segment = r₀",
      close(prim_P(g, 1)[1, 0], r[0]), prim_P(g, 1)[:2].round(4).tolist())

sec("Resample:Output as Polygon Curves to be Subdivided Later")
zz = polyline([(0, 0, 0), (1, 0, 0), (1, 1, 0), (2, 1, 0), (2, 2, 0)])
gs = RS(zz, length=0.5)
g = RS(zz, length=0.5, subdivide_later=True)
Qs, C = P_(gs), P_(g)
lim = (C[:-2] + 4 * C[1:-1] + C[2:]) / 6
check("output points c satisfy (c₋ + 4c + c₊)/6 = sample point (interior), the two end points unmoved",
      close(lim, Qs[1:-1], 1e-5) and close(C[[0, -1]], Qs[[0, -1]]) and not close(C, Qs), np.abs(lim - Qs[1:-1]).max())
sub = CV.poly_spline(g, "", "bspline", 0.5, 4)[0]
check("then subdivided 4× with PolySpline (BSpline): every 4th point is exactly a sample point (the curve passes through the samples)",
      close(P_(sub)[::4], Qs, 1e-5), np.abs(P_(sub)[::4] - Qs).max())
subo = CV.poly_spline(gs, "", "bspline", 0.5, 4)[0]
check("negative control: subdividing without adjusting -> the curve is pulled inwards, misses the samples", not close(P_(subo)[::4], Qs, 1e-3))
gc = RS(sq, method="segment_count", segments=8, subdivide_later=True)
gc0 = RS(sq, method="segment_count", segments=8)
C, Qs = P_(gc), P_(gc0)
check("closed: the cyclic equation (c₋ + 4c + c₊)/6 = q holds at every point",
      close((np.roll(C, 1, 0) + 4 * C + np.roll(C, -1, 0)) / 6, Qs, 1e-5))
g = RS(zz, length=0.5, subdivide_later=True, create_only_points=True)
check("no adjustment with Create Only Points (points only, no curve to subdivide)", close(P_(g), P_(RS(zz, length=0.5, create_only_points=True))))

sec("Resample:Maintain Primitive Order")
three = polylines([[(0, 0, 0), (1, 0, 0)], [(0, 1, 0), (1, 1, 0)], [(0, 2, 0), (1, 2, 0)]])
three.set_group(PRIM, "g", np.array([True, False, True]))
g = RS(three, group="g", length=0.5)
ys = [float(prim_P(g, i)[0, 1]) for i in range(3)]
check("off (default): the unselected prim (y=1) comes first", ys == [1, 0, 2], ys)
g = RS(three, group="g", length=0.5, maintain_prim_order=True)
ys = [float(prim_P(g, i)[0, 1]) for i in range(3)]
cnt = [len(g.prim_points(i)) for i in range(3)]
check("on: input order y = 0, 1, 2; 3 points resampled, 2 points untouched", ys == [0, 1, 2] and cnt == [3, 2, 3], (ys, cnt))
g = RS(three, group="g", length=0.5, maintain_prim_order=True, treat_polygons_as="interpolating_curves")
ys = [float(prim_P(g, i)[0, 1]) for i in range(3)]
check("densified first by Treat Polygons As (which reorders prims internally), still sorted back; no temporary attribute left",
      ys == [0, 1, 2] and "__resample_orig" not in g.attribs[PRIM], ys)

def nurbs_curve(pts, order=4):
    g = polyline(pts)
    g.set_topology(g.vertex_point, g.prim_offset, np.zeros(1, bool), np.array([PRIM_NURBS_CURVE], np.uint8))
    g.set(PRIM, "uorder", np.array([[order]], np.int32))
    return g


g = RS(three, group="g", length=0.5, maintain_prim_order=True, create_only_points=True)
check("nothing to sort with Create Only Points: same as off", digest(g) == digest(RS(three, group="g", length=0.5, create_only_points=True)))
pn = ops.merge(polyline([(0, 0, 0), (1, 0, 0), (2, 1, 0)]), nurbs_curve([(0, 5, 0), (1, 6, 0), (2, 5, 0), (3, 6, 0)]))
g = RS(pn, length=0.5, treat_polygons_as="subdivision_curves")
g2 = RS(pn, length=0.5, treat_polygons_as="subdivision_curves", maintain_prim_order=True)
check("all selected, Treat As densify: by default the NURBS is moved to the front (old behaviour); Maintain Primitive Order restores polygon, NURBS",
      prim_P(g, 0)[0, 1] == 5 and prim_P(g2, 0)[0, 1] == 0 and prim_P(g2, 1)[0, 1] == 5)

sec("Resample: bit-exact regression at default values, panel")
NOW = old_cases()
bad = {k: (GOLDEN.get(k), v) for k, v in NOW.items() if k.startswith("rs_") and GOLDEN.get(k) != v}
check("output digests of 8 old calls (by length / not even / segment count / capped / points only / output attributes / both Treat As) match before the change",
      sum(k.startswith("rs_") for k in GOLDEN) == 8 and not bad, bad)
check("panel: self-check clean; Method / Measure have Houdini labels; Measure greyed out when by edge",
      not PANEL.check_layout("PCG_Resample", M["PCG_Resample"].INPUT_TYPES()), PANEL.check_layout("PCG_Resample", M["PCG_Resample"].INPUT_TYPES()))
ui = PANEL.layout_for("PCG_Resample", M["PCG_Resample"].INPUT_TYPES())[0]
check("panel labels", ui["measure_method"]["menu"]["even_x"] == "Even X Segments" and ui["measure"]["menu"]["along_chord"] == "Along Chord"
      and "resample_by_edge == 1" in ui["measure"]["disable"])


# ════════════════════════════════════════════════ Cross Section Surface(Houdini)
XS = lambda g, **kw: run("PCG_CrossSectionSurfaceHou", geo=g, **kw)  # noqa: E731
SQ = [(1, -1), (1, 1), (-1, 1), (-1, -1)]                              # counter-clockwise about +z


def squares(zs=(0, 1, 2), half=(1, 1, 1), closed=True):
    return ops.merge(*[polyline([(x * h, y * h, z) for x, y in SQ], closed) for z, h in zip(zs, half)])


def fnormal(g, i):
    Q = P_(g)[g.prim_points(i)]
    n = np.zeros(3)
    for k in range(len(Q)):
        n += np.cross(Q[k], Q[(k + 1) % len(Q)])
    return n


def closed_manifold(g):
    seen = {}
    for k in range(g.nprims):
        pts = g.prim_points(k)
        for i in range(len(pts)):
            e = (int(pts[i]), int(pts[(i + 1) % len(pts)]))
            seen[e] = seen.get(e, 0) + 1
    return all(v == 1 for v in seen.values()) and all((b, a) in seen for (a, b) in seen)


def vuv(g, prim):
    o = int(g.prim_offset[prim])
    return np.asarray(g.get(VERTEX, "uv"), np.float64)[o:o + len(g.prim_points(prim))]


S3 = squares()
sec("Cross Section Surface (Houdini): topology")
g = XS(S3)
check("3 closed square cross sections: the 12 points are the cross-section points (same order), 2 rows × 4 columns = 8 quads",
      g.npoints == 12 and g.nprims == 8 and close(P_(g), P_(S3)))
out_ok = all(float(fnormal(g, i) @ (P_(g)[g.prim_points(i)].mean(0) * [1, 1, 0])) > 0 for i in range(g.nprims))
check("normals point outwards (U × V: cross sections counter-clockwise, stacked towards +z)", out_ok)
check("first quad = (0,0) (0,1) (1,1) (1,0)", list(g.prim_points(0)) == [0, 1, 5, 4])
g = XS(S3, reverse_cross_sections=True)
check("Reverse Cross Sections: normals all point inwards", all(float(fnormal(g, i) @ (P_(g)[g.prim_points(i)].mean(0) * [1, 1, 0])) < 0
                                               for i in range(g.nprims)))
g = XS(S3, surface_type="triangles")
check("Triangles: 16 triangles, diagonal (r,c)-(r+1,c+1)", g.nprims == 16 and list(g.prim_points(0)) == [0, 1, 5]
      and list(g.prim_points(1)) == [0, 5, 4])
g = XS(S3, surface_type="reverse_triangles")
check("Reverse Triangles: diagonal becomes (r,c+1)-(r+1,c)", g.nprims == 16 and list(g.prim_points(0)) == [0, 1, 4]
      and list(g.prim_points(1)) == [1, 5, 4])
g = XS(S3, surface_type="alt_triangles")
check("Alternating Triangles: cell (0,0) as Triangles, cell (0,1) as Reverse",
      list(g.prim_points(0)) == [0, 1, 5] and list(g.prim_points(2)) == [1, 2, 5] and list(g.prim_points(3)) == [2, 6, 5])
g = XS(S3, surface_type="points")
check("Points: 12 points, no prims", g.npoints == 12 and g.nprims == 0)
g = XS(S3, surface_type="rows")
check("Rows: one closed curve per cross section (3 × 4 points)", g.nprims == 3 and all(len(g.prim_points(i)) == 4 and g.prim_closed[i] for i in range(3)))
g = XS(S3, surface_type="columns")
check("Columns: one open curve per column (4 × 3 points)", g.nprims == 4 and all(len(g.prim_points(i)) == 3 and not g.prim_closed[i]
                                                                  for i in range(4)) and list(g.prim_points(1)) == [1, 5, 9])
g = XS(S3, surface_type="rows_and_columns")
check("Rows and Columns: 3 + 4 curves", g.nprims == 7)
g = XS(S3, close_backbone=True)
check("Close Implicit Backbone Curve: 3 rows × 4 columns = 12 quads (the last connects back to the first), closed manifold",
      g.nprims == 12 and list(g.prim_points(8)) == [8, 9, 1, 0] and closed_manifold(g))
g = XS(S3, close_backbone=True, surface_type="columns")
check("with a closed backbone the column curves are closed", all(bool(g.prim_closed[i]) for i in range(g.nprims)))
g = XS(S3, swap_rows_cols=True)
check("Swap Rows and Columns: points column-major (the first three points lie on the three cross sections of column 0), normals point inwards",
      close(P_(g)[:3], P_(S3)[[0, 4, 8]]) and all(float(fnormal(g, i) @ (P_(g)[g.prim_points(i)].mean(0) * [1, 1, 0])) < 0
                                                for i in range(g.nprims)))
g = XS(S3, swap_rows_cols=True, prim_row_attrib="qr", prim_col_attrib="qc")
check("Swap: faces column-major ((0,0) (1,0) (0,1) ...), row/column attributes keep their original meaning",
      np.asarray(g.get(PRIM, "qr"))[:4, 0].tolist() == [0, 1, 0, 1] and np.asarray(g.get(PRIM, "qc"))[:4, 0].tolist() == [0, 0, 1, 1])
g = XS(S3, swap_rows_cols=True, surface_type="rows")
check("Swap + Rows: still one curve per cross section, vertex order reversed", g.nprims == 3 and close(P_(g)[g.prim_points(0)], P_(S3)[[3, 2, 1, 0]]))
g = XS(S3, swap_rows_cols=True, compute_uvs=True)
g0 = XS(S3, compute_uvs=True)
check("Swap does not change the meaning of uv: the first face is the old (0,0) cell, vertices reversed", close(vuv(g, 0), vuv(g0, 0)[::-1]))
check("cross sections with different point counts: the error says so clearly", raises(lambda: XS(ops.merge(S3, polyline([(0, 0, 5), (1, 0, 5), (0, 1, 5)], True))), "point counts"))
op3 = squares(closed=False)
g = XS(op3)
check("open cross sections: no wrap-around, 2 × 3 = 6 quads", g.nprims == 6)

sec("Cross Section Surface (Houdini): end caps")
g = XS(S3, end_cap_type="single_polygon", end_caps_group="caps")
cg = np.asarray(g.groups[PRIM]["caps"], bool)
check("Single Polygon: 8 + 2 faces, closed manifold; both end caps in the group, bottom facing -z, top facing +z",
      g.nprims == 10 and closed_manifold(g) and cg.sum() == 2 and cg[-2:].all()
      and fnormal(g, 8)[2] < 0 and fnormal(g, 9)[2] > 0)
g = XS(op3, end_cap_type="single_polygon")
check("Single Polygon has no effect with open cross sections", g.nprims == 6)
g = XS(S3, end_cap_type="grid", cap_divisions=3, end_caps_group="caps")
r2 = np.sqrt(2)
check("Grid, 3 rings, Scale 1, Roundness 1: points 12 + 2 × (2 rings × 4 + pole) = 30; faces 8 rows × 4 = 32, 24 in the end cap group",
      g.npoints == 30 and g.nprims == 32 and int(np.asarray(g.groups[PRIM]["caps"]).sum()) == 24)
P = P_(g)
top = P[np.argmax(P[:, 2])]
check("pole at (0,0, 2 + √2) (bounding circle radius √2 × Scale 1)", close(top, (0, 0, 2 + r2)))
ring = P[np.abs(P[:, 2] - (2 + r2 * 0.5)) < 1e-4]
check("ring 1: θ = 30°, shrunk by a factor of cos 30° and raised √2·sin 30°", len(ring) == 4 and close(np.abs(ring[:, :2]), np.cos(np.pi / 6)))
bot = P[np.argmin(P[:, 2])]
check("the bottom pole faces -z: (0,0, -√2)", close(bot, (0, 0, -r2)))
g = XS(S3, end_cap_type="grid", cap_divisions=3, end_cap_roundness=0.0)
ring = P_(g)[np.abs(P_(g)[:, 2] - (2 + r2 / 3)) < 1e-4]
check("Roundness 0 (cone): ring 1 shrunk to 2/3, raised √2/3", len(ring) == 4 and close(np.abs(ring[:, :2]), 2 / 3))
g = XS(S3, end_cap_type="grid", cap_divisions=2, end_cap_scale=0.0)
check("Scale 0: the end caps are flat (all at z = 0 and z = 2)", set(np.round(P_(g)[:, 2], 6)) == {0.0, 1.0, 2.0})
g = XS(S3, end_cap_type="grid", cap_divisions=2, end_cap_scale=-1.0)
check("Scale -1: concave (top pole at z = 2 - √2)", close(P_(g)[:, 2].min(), -0.0) and close(P_(g)[np.argmin(np.abs(P_(g)[:, 2] - (2 - r2))), 2], 2 - r2))
g = XS(S3, end_cap_type="grid", cap_divisions=3)
dup = [i for i in range(g.nprims) if len(set(g.prim_points(i))) == 3]
check("Triangular Poles unticked: around the pole are quads with two duplicate vertices (8)", len(dup) == 8 and all(len(g.prim_points(i)) == 4 for i in dup))
g = XS(S3, end_cap_type="grid", cap_divisions=3, triangular_poles=True)
check("Triangular Poles: 8 triangles around the pole, closed manifold overall", sum(len(g.prim_points(i)) == 3 for i in range(g.nprims)) == 8
      and closed_manifold(g))
cyl = ops.merge(*[polyline([(np.cos(a), 0, np.sin(a)), (np.cos(a), 1, np.sin(a))])
                  for a in np.linspace(0, 2 * np.pi, 7)[:-1]])
g = XS(cyl, close_backbone=True, end_cap_type="side_single_polygon", end_caps_group="caps")
check("Side Single Polygon (closed backbone, open cross sections): 6 side faces + 2 hexagons, closed manifold",
      g.nprims == 8 and closed_manifold(g) and len(g.prim_points(6)) == 6 and int(np.asarray(g.groups[PRIM]["caps"]).sum()) == 2)
g = XS(cyl, close_backbone=True)
check("negative control: no end caps, 6 faces", g.nprims == 6)
g = XS(cyl, end_cap_type="side_single_polygon")
check("Side Single Polygon has no effect when the backbone is not closed (5 faces)", g.nprims == 5)
g = XS(op3, end_cap_type="grid")
check("Grid has no effect with open cross sections", g.nprims == 6)
g = XS(S3, end_cap_type="grid", cap_divisions=3, triangular_poles=True)
P = P_(g)
tri = [i for i in range(g.nprims) if len(g.prim_points(i)) == 3 and P[g.prim_points(i)][:, 2].min() < -1.4]
zs = sorted(set(np.round(P[np.concatenate([g.prim_points(i) for i in tri])][:, 2], 5)))
check("start end: next to the pole is the outermost ring (z = -√2·sin 60°)", len(tri) == 4 and close(zs, [-r2, -r2 * np.sin(np.pi / 3)]), zs)
g = XS(S3, end_cap_type="grid", cap_divisions=3, surface_type="triangles")
check("Grid + Triangles: degenerate triangles next to the pole dropped: 16 + 2 × (4 + 8 + 8) = 56, no duplicate vertices",
      g.nprims == 56 and all(len(set(g.prim_points(i))) == 3 for i in range(g.nprims)))
one = polyline([(x, y, 0) for x, y in SQ], True)
g = XS(one, end_cap_type="grid", cap_divisions=2)
check("only one cross section: the two poles face opposite directions (z = ±√2)", close(sorted(P_(g)[:, 2])[0], -r2) and close(sorted(P_(g)[:, 2])[-1], r2))
kite = ops.merge(*[polyline([(1, 0, z), (0, 1, z), (-2, 0, z), (0, -1, z)], True) for z in (0, 1)])
g = XS(kite, end_cap_type="grid", cap_divisions=2)
check("bounding circle radius uses the farthest point (kite: center (-.25, 0), farthest 1.75)", close(P_(g)[:, 2].max(), 1 + 1.75))
flat = ops.merge(*[polyline([(0, 0, z), (1, 0, z), (2, 0, z)], True) for z in (0, 1)])
g = XS(flat, end_cap_type="grid", cap_divisions=2)
check("cross section degenerates to a line (no normal): end caps raised away from the neighbouring cross section (poles z = 1 + 1, z = 0 - 1)",
      close(P_(g)[:, 2].max(), 2) and close(P_(g)[:, 2].min(), -1))
mixc = ops.merge(polyline([(x, y, 0) for x, y in SQ], False), squares(zs=(1, 2)))
check("one cross section open: no wrap-around (2 × 3 = 6 faces)", XS(mixc).nprims == 6)
check("with two cross sections Close Implicit Backbone does not wrap (4 faces, not a duplicated 8)", XS(squares(zs=(0, 1)), close_backbone=True).nprims == 4)
g = XS(S3, end_cap_type="single_polygon", swap_rows_cols=True)
check("with Swap the end caps flip too, still a closed manifold", closed_manifold(g))

sec("Cross Section Surface(Houdini):UV")
g = XS(S3, compute_uvs=True)
check("default (length weighted, normalized U, V proportional to U, V rounded, U flipped): first face uv = (1,0) (.75,0) (.75,.5) (1,.5)",
      close(vuv(g, 0), [(1, 0), (.75, 0), (.75, .5), (1, .5)]), vuv(g, 0).round(4).tolist())
check("the seam face (row 0 column 3): u from .25 to 0 (separate vertices, not mixed with 1)", close(vuv(g, 3)[:, 0], [.25, 0, 0, .25]))
g = XS(S3, compute_uvs=False)
check("negative control: Compute UVs off -> no uv", g.get(VERTEX, "uv") is None)
g = XS(S3, compute_uvs=True, normalize_u=False, wrap_u=False, wrap_v=False, flip_u=False)
check("not normalized, not rounded, not flipped: u = arc length 0, 2; v = cross-section spacing 0, 1", close(vuv(g, 1), [(2, 0), (4, 0), (4, 1), (2, 1)]))
g = XS(S3, compute_uvs=True, normalize_u=False, normalize_v=True, wrap_u=False, flip_u=False)
check("only V normalized: v = 0, .5; u proportional to V = arc length / 2", close(vuv(g, 1), [(1, 0), (2, 0), (2, .5), (1, .5)]))
S3w = squares(zs=(0, 2, 4))
g = XS(S3w, compute_uvs=True, length_weighted_uvs=False, flip_u=False, wrap_v=False)
check("not length weighted (cross-section spacing 2): u = column / 4; v = row / 4 (proportional to U: cross section is 4 units long)",
      close(vuv(g, 1), [(.25, 0), (.5, 0), (.5, .25), (.25, .25)]))
g = XS(S3w, compute_uvs=True, flip_u=False, wrap_v=False)
check("negative control: length weighted -> v₁ = 2 / 8", close(vuv(g, 1)[2, 1], .25))
S9 = squares(half=(0.9, 0.9, 0.9))
g = XS(S9, compute_uvs=True, normalize_u=False, flip_u=False, wrap_v=False)
check("Wrap U: perimeter 7.2 -> rounded to 7, u multiplied by 7/7.2", close(vuv(g, 0)[1, 0], 1.8 * 7 / 7.2))
g = XS(S9, compute_uvs=True, normalize_u=False, wrap_u=False, flip_u=False, wrap_v=False)
check("negative control: Wrap U off -> u = 1.8", close(vuv(g, 0)[1, 0], 1.8))
g = XS(S9, compute_uvs=True, normalize_u=False, wrap_u=False, flip_u=True, wrap_v=False)
check("Flip when not normalized: u = perimeter - arc length = 7.2 - 1.8", close(vuv(g, 0)[1, 0], 7.2 - 1.8))
g = XS(S3, compute_uvs=True, end_cap_type="single_polygon")
check("Single Polygon end caps get uv 0", close(vuv(g, 8), 0) and close(vuv(g, 9), 0))
g = XS(S3, compute_uvs=True, end_cap_type="grid", cap_divisions=3)
check("the Grid end cap pole ring has length 0: U falls back to column ratio (after flipping 1, .75)", close(vuv(g, 0)[:2, 0], [1, .75]), vuv(g, 0).round(3).tolist())
g = XS(S3, compute_uvs=True, end_cap_type="grid", cap_divisions=3, wrap_u=False)
check("same as above, Wrap U off (rounding no longer pulls the range back to 1)", close(vuv(g, 0)[:2, 0], [1, .75]), vuv(g, 0).round(3).tolist())
Sb = squares(half=(1, 2, 1))
g = XS(Sb, compute_uvs=True, flip_u=False, wrap_v=False)
dz = np.sqrt(1 + 2)                                                    # distance between points on neighbouring cross sections per column: √(1² + 1² + 1²)
check("V proportional to U (average length of neighbouring cross sections): v₁ = √3 / ((8 + 16)/2)", close(vuv(g, 0)[3, 1], dz / 12))
g = XS(Sb, compute_uvs=True, flip_u=False, wrap_v=False, use_max_length=True)
check("Use Max Cross Section Length:v₁ = √3 / 16", close(vuv(g, 0)[3, 1], dz / 16))
g = XS(S3, compute_uvs=True, uv_scale_u=2.0, uv_scale_v=3.0)
check("UV Scale (2, 3)", close(vuv(g, 0), np.array([(1, 0), (.75, 0), (.75, .5), (1, .5)]) * [2, 3]))
g = XS(S3, compute_uvs=True, surface_type="points")
check("Points output: uv is a point attribute", g.get(POINT, "uv") is not None and close(np.asarray(g.get(POINT, "uv"))[5], (.75, .5)))
g = XS(S3, compute_uvs=True, surface_type="rows", unique_seam_vertices=True)
check("Ensure Unique Seam Vertices (Rows): curve open, 5 vertices, the last vertex references the first point, u is 0 (first vertex 1)",
      g.nprims == 3 and not g.prim_closed[0] and len(g.prim_points(0)) == 5 and g.prim_points(0)[4] == g.prim_points(0)[0]
      and close(vuv(g, 0)[[0, 4], 0], [1, 0]))
g = XS(S3, compute_uvs=True, surface_type="rows")
check("negative control: unticked -> closed, 4 vertices", bool(g.prim_closed[0]) and len(g.prim_points(0)) == 4)
opu = squares(closed=False)
opu.set(POINT, "uv", np.tile(np.array([[0.1, 0], [0.2, 0], [0.4, 0], [0.8, 0]], np.float32), (3, 1)))
g = XS(opu, compute_uvs=True)
check("open cross sections with existing uv, Override unticked: U copied", close(vuv(g, 0)[:, 0], [.1, .2, .2, .1]))
g = XS(opu, compute_uvs=True, override_uvs=True, flip_u=False)
check("Override ticked: U recomputed (normalized arc length 0, 1/3)", close(vuv(g, 0)[:, 0], [0, 1 / 3, 1 / 3, 0]))

sec("Cross Section Surface (Houdini): attributes")
Sa = ops.merge(polyline([(5, 5, 5), (6, 5, 5), (5, 6, 5)], True), S3)        # prim 0 is not a cross section
Sa.set(POINT, "Cd", np.arange(Sa.npoints * 3, dtype=np.float32).reshape(-1, 3))
Sa.set(PRIM, "id", np.array([[10], [11], [12], [13]], np.int32))
g = XS(Sa, group="1-3", point_row_attrib="prow", point_col_attrib="pcol", prim_row_attrib="qrow",
       prim_col_attrib="qcol", cross_section_num_attrib="xsec")
check("point attribute Cd copied from source points", close(np.asarray(g.get(POINT, "Cd")), np.asarray(Sa.get(POINT, "Cd"))[3:]))
check("prim attribute id taken from that row's cross section (row 0 11, row 1 12)",
      np.asarray(g.get(PRIM, "id"))[:, 0].tolist() == [11] * 4 + [12] * 4)
check("point / face row and column numbers, cross-section number (input prim numbers 1, 2, 3)",
      np.asarray(g.get(POINT, "prow"))[:, 0].tolist() == [0] * 4 + [1] * 4 + [2] * 4
      and np.asarray(g.get(POINT, "pcol"))[:, 0].tolist() == [0, 1, 2, 3] * 3
      and np.asarray(g.get(PRIM, "qrow"))[:, 0].tolist() == [0] * 4 + [1] * 4
      and np.asarray(g.get(PRIM, "qcol"))[:, 0].tolist() == [0, 1, 2, 3] * 2
      and np.asarray(g.get(POINT, "xsec"))[:, 0].tolist() == [1] * 4 + [2] * 4 + [3] * 4)
Sa.set_string(POINT, "nm", np.array([f"p{i}" for i in range(Sa.npoints)], object))
g = XS(Sa, group="1-3")
check("string point attributes are also copied from source points", list(np.asarray(g.attribs[POINT]["nm"])[:3, 0]) == ["p3", "p4", "p5"])
g = XS(Sa, group="1-3", from_cross_sections="* ^Cd")
check("From Cross Sections = '* ^Cd': Cd not carried, id carried", g.get(POINT, "Cd") is None and g.get(PRIM, "id") is not None)
g = XS(Sa, group="1-3")
check("negative control: attribute names empty -> row/column numbers not written", all(g.get(POINT, k) is None for k in ("prow", "pcol", "xsec")))

sec("Cross Section Surface: old node unchanged, mapping, panel")
bad = {k: (GOLDEN.get(k), NOW.get(k)) for k in GOLDEN if k.startswith("css_") and GOLDEN[k] != NOW.get(k)}
check("output digests of three calls of the old PCG_CrossSectionSurface (Gordon) match before the change", not bad, bad)
try:
    import sop_map as _sm                                               # noqa: E402  only exists in the repo root (not in the device layout)
except ImportError:
    _sm = None
if _sm is None:
    print("  (no sop_map.py -- device layout; this check is skipped and not counted)")
else:
    row = [v for k, v in vars(_sm).items() if isinstance(v, dict) and "Cross Section Surface" in v]
    check("sop_map: Cross Section Surface points to the new node", row and row[0]["Cross Section Surface"][1] == "PCG_CrossSectionSurfaceHou")
check("panel self-check", not PANEL.check_layout("PCG_CrossSectionSurfaceHou", M["PCG_CrossSectionSurfaceHou"].INPUT_TYPES()),
      PANEL.check_layout("PCG_CrossSectionSurfaceHou", M["PCG_CrossSectionSurfaceHou"].INPUT_TYPES()))


# ════════════════════════════════════════════════════════════════ Curve Intersect
CI = lambda g, **kw: run("PCG_CurveIntersect", geo=g, **kw)  # noqa: E731
left = polyline([(0, 0, 0), (4, 0, 0)], f=[[0], [4]])
left.set(PRIM, "id", np.array([[7]], np.int32))
cut3 = polylines([[(x, 0, -1), (x, 0, 1)] for x in (1, 2, 3)])


def spans(g, axis=0):
    return sorted(tuple(np.round(sorted(P_(g)[g.prim_points(i)][[0, -1], axis]), 6)) for i in range(g.nprims))


sec("Curve Intersect:Cut(Houdini Method)")
check("Output menu gains cut / extract at the end, the old two modes unchanged", opts("PCG_CurveIntersect", "output") == ["points", "split", "cut", "extract"])
g = CI(left, cutter=cut3, output="cut")
xs = [s_ for s_ in spans(g) if s_[0] != s_[1]]
check("the left line cut by three vertical lines into 4 pieces [0,1] [1,2] [2,3] [3,4]; each vertical line cut into 2 -> 10 curves, 20 points (pieces share no points)",
      g.nprims == 10 and g.npoints == 20 and xs == [(0, 1), (1, 2), (2, 3), (3, 4)], spans(g))
lp = lambda g: [s_ for s_ in spans(g) if s_[0] != s_[1]]  # noqa: E731  pieces of the left line (vertical pieces have constant x)
check("Keep Odd-numbered: left keeps pieces 1, 3", lp(CI(left, cutter=cut3, output="cut", left_pieces="keep_odd")) == [(1, 2), (3, 4)])
check("Keep Even-numbered: left keeps pieces 0, 2", lp(CI(left, cutter=cut3, output="cut", left_pieces="keep_even")) == [(0, 1), (2, 3)])
g = CI(left, cutter=cut3, output="cut", left_pieces="keep_none")
check("Keep None: the whole left line removed, only the 6 vertical pieces remain", g.nprims == 6 and not lp(g))
g = CI(left, cutter=cut3, output="cut", right_pieces="keep_none")
check("right Keep None: only the 4 left pieces remain", g.nprims == 4)
g = CI(left, cutter=cut3, output="cut", right_pieces="keep_even", left_pieces="keep_none")
check("right Keep Even: each vertical line keeps piece 0 (z from -1 to 0)", g.nprims == 3 and spans(g, 2) == [(-1, 0)] * 3)
g = CI(left, cutter=cut3, output="cut", left_pieces="keep_odd")
f = np.asarray(g.get(POINT, "f"))[:, 0]
pid = [i for i in range(g.nprims) if g.get(PRIM, "id")[i, 0] == 7]
check("float point attributes interpolated by arc length (piece end f = x of the cut point), prim attributes copied",
      len(pid) == 2 and sorted(np.round(f[np.concatenate([g.prim_points(i) for i in pid])], 6)) == [1, 2, 3, 4])
both = ops.merge(left, cut3)
g = CI(both, output="cut", group="0", cutter_group="1-3")
check("no second input: Cutter Group selects from geo, result same as with the second input (10 curves)", g.nprims == 10 and lp(g) == [(0, 1), (1, 2), (2, 3), (3, 4)])
g = CI(both, output="cut", group="0", cutter_group="2")
check("Cutter Group selects one: the left is cut into 2, the selected vertical line into 2, the two unselected kept as-is", g.nprims == 6 and lp(g) == [(0, 2), (2, 4)])
g = CI(both, output="cut", group="0-1", cutter_group="1")
check("a prim in both groups: treated as left (prim 1 no longer cuts -> nothing cuts the left)", g.nprims == 4)
g = CI(left, cutter=polyline([(4, 0, -1), (4, 0, 1)]), output="cut", right_pieces="keep_none")
check("intersection at the end point of the left line: nothing cut, left line unchanged", g.nprims == 1 and lp(g) == [(0, 4)])
sqr = polyline([(-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1)], True)
g = CI(sqr, cutter=polyline([(0, 0, -2), (0, 0, 2)]), output="cut", left_pieces="keep_even", right_pieces="keep_none")
check("closed square cut twice by x = 0: 2 pieces, piece 0 starts at the first cut point: (0,-1) (1,-1) (1,1) (0,1)",
      g.nprims == 1 and not g.prim_closed[0] and close(P_(g)[g.prim_points(0)], [(0, 0, -1), (1, 0, -1), (1, 0, 1), (0, 0, 1)]),
      P_(g)[g.prim_points(0)].tolist())
g = CI(sqr, cutter=polyline([(0, 0, -2), (0, 0, 2)]), output="cut", right_pieces="keep_none")
check("Keep All: two pieces, 8 points in total", g.nprims == 2 and g.npoints == 8)

sec("Curve Intersect: Find All Intersections, Tolerance")
zig = polyline([(0, 0, 0), (2, 0, 2), (4, 0, 0)])
hl = polyline([(-1, 0, 1), (5, 0, 1)])
check("left line hit twice: Find All on -> 3 pieces", len(lp(CI(zig, cutter=hl, output="cut", right_pieces="keep_none"))) == 3)
g = CI(zig, cutter=hl, output="cut", right_pieces="keep_none", find_all=False)
check("Find All off: one hit per curve pair (all at distance 0, takes the smaller left arc length, x = 1) -> 2 pieces", g.nprims == 2
      and close(sorted(P_(g)[g.prim_points(0)][[0, -1], 0]), [0, 1]))
above = polyline([(2, 1, -1), (2, 1, 1)])
g = CI(left, cutter=above, output="cut", plane="3d", right_pieces="keep_none")
check("3d, vertical line 1 above the left line (no hit): Find All on -> no cut", g.nprims == 1)
g = CI(left, cutter=above, output="cut", plane="3d", find_all=False)
check("Find All off: cuts at the closest point (x = 2) no matter how far -> left 2 pieces + right 2 pieces", g.nprims == 4 and lp(g) == [(0, 2), (2, 4)])
near = polyline([(2, 0.005, -1), (2, 0.005, 1)])
check("3d, Tolerance .01: .005 away counts as a hit", CI(left, cutter=near, output="cut", plane="3d", tolerance=0.01, right_pieces="keep_none").nprims == 2)
check("negative control: Tolerance .001 does not count", CI(left, cutter=near, output="cut", plane="3d", tolerance=0.001, right_pieces="keep_none").nprims == 1)

check("XZ plane (node default): vertical line 1 above the left line, intersects in top view -> cut", CI(left, cutter=above, output="cut", right_pieces="keep_none").nprims == 2)
check("Tolerance 0, plane mode: an exact intersection still counts (distance 0 ≤ 0)",
      CI(left, cutter=cut3, output="cut", tolerance=0.0, right_pieces="keep_none").nprims == 4)
g = CI(polyline([(1, 0, 0), (1.9, 0, 0)]), cutter=polyline([(2.2, 0, -1), (2.2, 0, 1)]), output="extract",
       plane="3d", tolerance=0.5, keep_original=True)
check("3d, Tolerance .5: two segments .3 apart (the bounding boxes must be enlarged by Tolerance to find them) count as a hit: left line 2 points + 1 intersection", g.npoints == 3, g.npoints)
vtx = polyline([(0, 0, 0), (0.1, 0, 0.3), (0.7, 0, 0.1)])
dvec = np.array([0.37, 0, -0.11])
cv = polyline([np.array([0.1, 0, 0.3]) - dvec, np.array([0.1, 0, 0.3]) + dvec])
g = CI(vtx, cutter=cv, output="extract", tolerance=1e-6)
check("intersection at a vertex of the left line: the two adjacent segments each report it, counted once", g.npoints == 1, g.npoints)
two = polylines([[(2, 0, -1), (2, 0, 1)], [(1, 0, -1), (3, 0, 1)]])
g = CI(left, cutter=two, output="cut", right_pieces="keep_none")
check("two cutters hit the left line at the same point: merged into one cut -> 2 pieces (no zero-length piece)", g.nprims == 2 and lp(g) == [(0, 2), (2, 4)])
g = CI(sqr, cutter=polyline([(-1.5, 0, -1.5), (1.5, 0, 1.5)]), output="cut", right_pieces="keep_none")
check("closed square cut by a diagonal at two corners (arc length 0 and 8 are the same cut): 2 pieces", g.nprims == 2 and g.npoints == 6, g.nprims)
tri3 = np.array([[1.2267393024237425, 0.0, 1.2270757933913436], [-1.5068447212958485, 0.0, 0.8798244841459618],
                 [-1.0047872771685766, 0.0, -0.5273800606776503]])
mid = (tri3[1] + tri3[2]) / 2
g = CI(polyline(tri3, True), cutter=polyline([tri3[0] + (tri3[0] - mid) * 0.5, mid + (mid - tri3[0]) * 0.5]),
       output="cut", right_pieces="keep_none", tolerance=1e-7)
check("closed triangle cut by a line through vertex 0: arc length 0 and ≈T (off by float error) are the same cut -> 2 pieces", g.nprims == 2, g.nprims)
g = CI(sqr, cutter=polyline([(5, 0, -1), (5, 0, 1)]), output="cut", right_pieces="keep_none")
check("closed curve not cut: unchanged, still closed", g.nprims == 1 and bool(g.prim_closed[0]) and g.npoints == 4)
import comfyui_pcg.geo.paths as _paths                                  # noqa: E402
_old = _paths._HIT_PAIR_LIMIT
_paths._HIT_PAIR_LIMIT = 2
check("Find All off, segment pairs over the limit: raises (does not eat all memory)",
      raises(lambda: CI(left, cutter=cut3, output="cut", find_all=False), "Find All"))
_paths._HIT_PAIR_LIMIT = _old
li = polyline([(0, 0, 0), (4, 0, 0)])
li.set(POINT, "n", np.array([[0], [1]], np.int32))
li.set_group(POINT, "pg", np.array([True, False]))
li.set_group(PRIM, "qg", np.array([True]))
g = CI(li, cutter=cut3, output="cut", right_pieces="keep_none")
order = np.argsort(P_(g)[:, 0], kind="stable")
check("integer point attributes and point groups take the nearer source point (x < 2 takes point 0, exactly half takes the later one), prim groups copied",
      np.asarray(g.get(POINT, "n"))[order, 0].tolist() == [0, 0, 0, 1, 1, 1, 1, 1]
      and np.asarray(g.groups[POINT]["pg"])[order].tolist() == [True] * 3 + [False] * 5
      and np.asarray(g.groups[PRIM]["qg"]).all())

sec("Curve Intersect:Extract")
g = CI(left, cutter=near, output="extract", plane="3d", tolerance=0.01)
check("Affect Left, no Keep Original: only 1 point, on the left line (2, 0, 0)", g.nprims == 0 and g.npoints == 1 and close(P_(g), [(2, 0, 0)]))
g = CI(left, cutter=near, output="extract", plane="3d", tolerance=0.01, affect="right")
check("Affect Right: the point is on the right line (2, .005, 0)", close(P_(g), [(2, 0.005, 0)]))
g = CI(left, cutter=near, output="extract", plane="3d", tolerance=0.01, affect="both", keep_original=True)
check("Affect Both + Keep Original: left line kept + 2 points", g.nprims == 1 and g.npoints == 4)
g = CI(both, output="extract", group="0", cutter_group="1-3")
check("same geometry: left line removed, vertical lines kept + 3 intersections (x = 1, 2, 3)", g.nprims == 3 and g.npoints == 6 + 3
      and close(sorted(P_(g)[6:, 0]), [1, 2, 3]))

sec("Curve Intersect: the old two modes, panel")
bad = {k: (GOLDEN.get(k), NOW.get(k)) for k in GOLDEN if k.startswith("ci_") and GOLDEN[k] != NOW.get(k)}
check("output digests of 7 calls of the old points / split (incl. self-intersection, three planes) match before the change", not bad, bad)
check("the old two modes do not read new parameters: split with cutter / Cutter Group given is the same",
      digest(CI(both, cutter=cut3, cutter_group="1", left_pieces="keep_none")) == digest(CI(both)))
ui = PANEL.layout_for("PCG_CurveIntersect", M["PCG_CurveIntersect"].INPUT_TYPES())[0]
check("panel self-check; Left-face Pieces only shown for Cut, Affect only for Extract",
      not PANEL.check_layout("PCG_CurveIntersect", M["PCG_CurveIntersect"].INPUT_TYPES())
      and "output != cut" in ui["left_pieces"]["hide"] and "output != extract" in ui["affect"]["hide"]
      and ui["left_pieces"]["menu"]["keep_odd"] == "Keep Odd-numbered Ones")


# ════════════════════════════════════════════════════════════════ Circle Spline
CS = lambda g, **kw: run("PCG_CircleSpline", geo=g, **kw)  # noqa: E731
cc = 0.3
hel = lambda th: np.stack([np.cos(th), np.sin(th), cc * th], -1)  # noqa: E731  right-handed helix about +z
H3 = polyline(hel(np.array([-np.pi, 0, np.pi])))

sec("Circle Spline:Spline Type = Helix")
check("Spline Type menu (default Circle = old behaviour)", opts("PCG_CircleSpline", "spline_type") == ["circle", "helix"])
g = CS(H3, spline_type="helix", divisions=8)
th = -np.pi + np.pi * np.arange(17) / 8
check("three points exactly at -180°, 0°, 180° of a right-handed helix: the 17 points of the Directional output lie on that helix",
      g.npoints == 17 and close(P_(g), hel(th), 1e-6), np.abs(P_(g) - hel(th)).max())
gc = CS(H3, divisions=8)
check("negative control: with Circle the points lie on the circle through the three points (not a helix)", not close(P_(gc), hel(th), 1e-2))
from comfyui_pcg.geo.curves2 import _helix_axis, _helix_half      # noqa: E402
a_, b_, c_ = np.array([-1.0, 0, 0]), np.array([1.0, 0, 1]), np.array([-1.0, 0, 3])
dd = _helix_axis(a_, b_, c_, "directional")
db = _helix_axis(a_, b_, c_, "balanced")
check("Directional axis = direction a->c (0,0,1)", close(dd, (0, 0, 1)))
check("Balanced axis: a->b and b->c have equal length along the axis, hand-computed (1,0,4)/√17", close(db @ (b_ - a_), db @ (c_ - b_))
      and close(db, np.array([1, 0, 4]) / np.sqrt(17)), db)
ang = np.arccos((a_ - b_) @ (c_ - b_) / np.linalg.norm(a_ - b_) / np.linalg.norm(c_ - b_))
wb = ang / np.pi
exp = (1 - wb) * db + wb * dd
check("Blended: blends between Balanced and Directional by ∠abc/180°", close(_helix_axis(a_, b_, c_, "blended"), exp / np.linalg.norm(exp)))
a2, b2, c2 = np.array([1.0, 0, 0]), np.array([0.0, 0, 0]), np.array([1.0, 0.002, 0.3])
check("Blended: close to Balanced when ∠abc ≈ 0°", close(_helix_axis(a2, b2, c2, "blended"), _helix_axis(a2, b2, c2, "balanced"), 2e-2))
G3 = polyline([a_, b_, c_])
for ht in ("directional", "balanced"):
    g = CS(G3, spline_type="helix", helix_type=ht, divisions=2)
    d_ = dd if ht == "directional" else db
    Pq = P_(g)
    radii, pitch = [], []
    for p0, m, p1 in ((Pq[0], Pq[1], Pq[2]), (Pq[2], Pq[3], Pq[4])):
        pp0, pp1, pm = p0 - (p0 @ d_) * d_, p1 - (p1 @ d_) * d_, m - (m @ d_) * d_
        ctr = (pp0 + pp1) / 2
        radii.append((np.linalg.norm(pp1 - pp0) / 2, np.linalg.norm(pm - ctr)))
        pitch.append(((m @ d_) - (p0 @ d_) / 2 - (p1 @ d_) / 2, (p1 - p0) @ d_))
    ok = all(abs(r1 - r2) < 1e-6 for r1, r2 in radii) and all(abs(x) < 1e-6 for x, _ in pitch)   # output is float32
    if ht == "directional":
        ok = ok and abs(radii[0][0] - radii[1][0]) < 1e-6 and abs(pitch[0][1] - pitch[1][1]) > 0.5
        nm = "Directional: the two half turns have equal radius, different length along the axis (1 and 2)"
    else:
        ok = ok and abs(pitch[0][1] - pitch[1][1]) < 1e-6 and abs(radii[0][0] - radii[1][0]) > 1e-3
        nm = "Balanced: the two half turns have equal length along the axis, different radius"
    check(nm + "; the midpoint of each half turn is exactly one radius from the axis, halfway between the ends along the axis", ok, (radii, pitch))
deg = polyline([(0, 0, 0), (1, 0, 0), (0, 0, 0)])
check("degenerate helix (a, c coincide, no axis): falls back to the circle algorithm", digest(CS(deg, spline_type="helix")) == digest(CS(deg)))
for ht in ("balanced", "blended"):
    check(f"degenerate helix (a, c coincide) + {ht}: no error, falls back to a circle", digest(CS(deg, spline_type="helix", helix_type=ht)) == digest(CS(deg)))
col = polyline([(0, 0, 0), (1, 0, 0), (3, 0, 0)])
check("three collinear points, unequal spacing (Balanced projection direction degenerates): Blended does not raise, outputs a straight line",
      close(P_(CS(col, spline_type="helix", helix_type="blended", divisions=2))[:, 1:], 0))
check("a, b coincide: Blended treats it as 180° (no error)", _helix_axis(np.zeros(3), np.zeros(3), np.array([1.0, 0, 1]), "blended") is not None)
seg = _helix_half(np.array([0.0, 0, 0]), np.array([0.0, 0, 2]), np.array([0.0, 0, 1]), np.array([0, .25, .5, 1]))
check("p, q lined up along the axis (projections coincide): the half turn degenerates to a line segment", close(seg, [(0, 0, 0), (0, 0, .5), (0, 0, 1), (0, 0, 2)]))

sec("Circle Spline:Override Spline Type with Attribute")
Ha = polyline(hel(np.array([-np.pi, 0, np.pi])))
Ha.set_string(POINT, "splinetype", np.array(["", "helix", ""], object))
check("middle point splinetype = helix, node is Circle: ticked -> same as Helix", digest(CS(Ha, override_with_attrib=True, divisions=8))
      == digest(CS(Ha, spline_type="helix", divisions=8)))
check("negative control: unticked -> still Circle", digest(CS(Ha, divisions=8)) == digest(CS(Ha, divisions=8, spline_type="circle")) and
      not close(P_(CS(Ha, divisions=8)), hel(th), 1e-2))
Ha.set_string(POINT, "splinetype", np.array(["", "ellipse", ""], object))
check("unimplemented types (ellipse) fall back to the node's Spline Type", digest(CS(Ha, override_with_attrib=True, spline_type="helix", divisions=8))
      == digest(CS(Ha, spline_type="helix", divisions=8)))
Ha.set_string(POINT, "splinetype", np.array(["", "Circle", ""], object))
check("attribute values are case-insensitive (Circle -> circle)", digest(CS(Ha, override_with_attrib=True, spline_type="helix", divisions=8))
      == digest(CS(Ha, divisions=8)))

sec("Circle Spline: Adjust by Pseudo-Arclength, Curveu, Tangent")
uneven = polyline([(0, 0, 0), (0.2, 0.3, 0), (2, 1, 0), (2.4, 0.2, 0), (4, 0, 0)])
g0 = CS(uneven, divisions=8)
g = CS(uneven, divisions=8, adjust_arclength=True, arclength_samples=20)
dd0, dd1 = chords(P_(g0)), chords(P_(g))
dense = P_(CS(uneven, divisions=2000))


def to_polyline(p, Q):
    a, b = Q[:-1], Q[1:]
    t = np.clip(np.einsum("ij,ij->i", p - a, b - a) / np.maximum(np.einsum("ij,ij->i", b - a, b - a), 1e-300), 0, 1)
    return float(np.linalg.norm(a + (b - a) * t[:, None] - p, axis=1).min())


dist = np.array([to_polyline(p, dense) for p in P_(g)])
check("point count unchanged (33), ends unmoved", g.npoints == g0.npoints == 33 and close(P_(g)[[0, -1]], P_(g0)[[0, -1]]))
check("after moving, neighbouring point distances are nearly equal (max / min < 1.02), before they differ a lot (> 2)", dd1.max() / dd1.min() < 1.02 and dd0.max() / dd0.min() > 2,
      (dd1.max() / dd1.min(), dd0.max() / dd0.min()))
check("moved points are still on the curve (< 1e-5 from a dense 2000-sample curve)", dist.max() < 1e-5, dist.max())
g2 = CS(uneven, divisions=8, adjust_arclength=True, arclength_samples=0)
check("Arclength Samples 0: arc length measured on the output points themselves, coarser (differs from 20)", not close(P_(g2), P_(g), 1e-6))
ring = polyline([(np.cos(a) * (1 + 0.3 * np.cos(3 * a)), np.sin(a) * (1 + 0.3 * np.cos(3 * a)), 0)
                 for a in np.linspace(0, 2 * np.pi, 9)[:-1]], True)
g = CS(ring, divisions=6, adjust_arclength=True, arclength_samples=20)
ch = chords(np.concatenate([P_(g), P_(g)[:1]]))
check("closed curve: 48 points, nearly equidistant including the closing segment", g.npoints == 48 and ch.max() / ch.min() < 1.03, ch.max() / ch.min())
g = CS(H3, spline_type="helix", divisions=4, use_curveu=True)
check("Curveu: by segment number + parameter within the segment, 0, 1/8, ..., 1", close(np.asarray(g.get(POINT, "curveu"))[:, 0], np.arange(9) / 8))
g = CS(uneven, divisions=8, adjust_arclength=True, use_curveu=True, curveu_name="cu")
cu = np.asarray(g.get(POINT, "cu"))[:, 0]
check("after moving curveu is monotonic, 0 to 1 (name configurable)", close(cu[[0, -1]], [0, 1]) and np.all(np.diff(cu) > 0))
check("negative control: Curveu unticked, not written", CS(H3).get(POINT, "curveu") is None)
un2 = polyline(np.asarray(P_(uneven)), f=np.arange(5.0))
un2.set(POINT, "k", np.arange(5, dtype=np.int32)[:, None])
g = CS(un2, divisions=8, adjust_arclength=True, use_curveu=True)
gp = np.asarray(g.get(POINT, "curveu"), np.float64)[:, 0] * 4
check("after moving, float point attributes interpolated linearly by parameter (f = segment number + parameter = curveu × segment count), integers take the nearer source point",
      close(np.asarray(g.get(POINT, "f"))[:, 0], gp, 1e-4)
      and np.asarray(g.get(POINT, "k"))[:, 0].tolist() == np.where(gp % 1 < 0.5, np.floor(gp), np.floor(gp) + 1).astype(int).tolist())
un2.set(VERTEX, "vi", np.arange(5, dtype=np.int32)[:, None])
g = CS(un2, divisions=8, adjust_arclength=True)
check("after moving, vertex attributes also take the nearer source corner", np.asarray(g.get(VERTEX, "vi"))[:, 0].tolist()
      == np.where(gp % 1 < 0.5, np.floor(gp), np.floor(gp) + 1).astype(int).tolist())
un2.set(POINT, "splinetype", np.ones((5, 1), np.float32))
check("splinetype not a string attribute: not recognized, treated as absent", digest(CS(un2, override_with_attrib=True)) == digest(CS(un2)))
g = CS(H3, spline_type="helix", divisions=8, use_tangent=True)
T = np.asarray(g.get(POINT, "tangentu"), np.float64)
exp = np.stack([-np.sin(th), np.cos(th), np.full_like(th, cc)], 1)
exp /= np.linalg.norm(exp, axis=1, keepdims=True)
check("Tangent: unit tangent on the helix ∝ (-sin θ, cos θ, c) (correct at the ends too)", close(T, exp, 1e-4), np.abs(T - exp).max())
circ8 = polyline([(np.cos(a), np.sin(a), 0) for a in np.linspace(0, 2 * np.pi, 9)[:-1]], True)
g = CS(circ8, divisions=4, use_tangent=True, tangent_name="T")
T = np.asarray(g.get(POINT, "T"), np.float64)
check("tangents on the circle are perpendicular to the radius, unit length", np.abs(np.einsum("ij,ij->i", T, P_(g))).max() < 1e-4 and close(np.linalg.norm(T, axis=1), 1))

sec("Circle Spline: old behaviour, panel")
bad = {k: (GOLDEN.get(k), NOW.get(k)) for k in GOLDEN if k.startswith("cs_") and GOLDEN[k] != NOW.get(k)}
check("at default values the digests of two old calls (open zigzag, closed hexagon) match before the change", not bad, bad)
check("panel self-check", not PANEL.check_layout("PCG_CircleSpline", M["PCG_CircleSpline"].INPUT_TYPES()),
      PANEL.check_layout("PCG_CircleSpline", M["PCG_CircleSpline"].INPUT_TYPES()))


# ════════════════════════════════════════════════════════════════ Copy to Curves
AX4 = Geometry.from_points(np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)], np.float32))   # origin + three axes


def CTC(curves, **kw):
    kw.setdefault("mode", "curve_points")
    return run("PCG_CopyToCurves", source=kw.pop("source", AX4), curves=curves, **kw)


def frames(g):
    """Per copy (position, 3×3 columns = where local X / Y / Z went). The source is AX4."""
    Pq = P_(g).reshape(-1, 4, 3)
    return Pq[:, 0], np.stack([Pq[:, 1] - Pq[:, 0], Pq[:, 2] - Pq[:, 0], Pq[:, 3] - Pq[:, 0]], 2)


r2_ = np.sqrt(2)


def _unit(v):
    return np.asarray(v, np.float64) / np.linalg.norm(v)


line4 = polyline([(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)])
sec("Copy to Curves: Curve Points (Houdini) -- copy to existing points, frames")
check("Sample By gains curve_points at the end", opts("PCG_CopyToCurves", "mode") == ["count", "spacing", "curve_points"])
g = CTC(line4, target_up="y_axis")
O, F = frames(g)
check("a line with 4 points -> 4 copies, exactly on those 4 points (no resampling)", g.npoints == 16 and close(O, P_(line4)))
check("frame: Z = tangent (1,0,0), Y = up (0,1,0), X = up × tangent (0,0,-1)",
      close(F[:, :, 2], (1, 0, 0)) and close(F[:, :, 1], (0, 1, 0)) and close(F[:, :, 0], (0, 0, -1)))
bend = polyline([(0, 0, 0), (1, 0, 0), (1, 2, 0)])
for tt_, exp in (("average", (1 / r2_, 1 / r2_, 0)), ("central_difference", np.array([1, 2, 0]) / np.sqrt(5)),
                 ("previous", (1, 0, 0)), ("next", (0, 1, 0)), ("z_axis", (0, 0, 1))):
    _, F = frames(CTC(bend, tangent_type=tt_, target_up="y_axis"))
    check(f"Tangent Type {tt_}: tangent at the corner = {np.round(exp, 3).tolist()}", close(F[1, :, 2], exp), F[1, :, 2].round(4).tolist())
arc = polyline([(np.cos(a), np.sin(a), 0) for a in np.radians([0, 30, 60, 90])])
_, F = frames(CTC(arc))
_, Fe = frames(CTC(arc, extrapolate_ends=True))
check("Extrapolate End Tangents: arc end tangents become exact (0,1,0) / (-1,0,0) (unticked they follow the chord)",
      close(Fe[0, :, 2], (0, 1, 0)) and close(Fe[-1, :, 2], (-1, 0, 0)) and not close(F[0, :, 2], (0, 1, 0), 1e-3))
_, F = frames(CTC(arc, extrapolate_ends=True, tangent_type="next"))
check("no extrapolation when the tangent type is Next Edge", close(F[0, :, 2], np.array([np.cos(np.radians(30)) - 1, np.sin(np.radians(30)), 0])
                                          / np.linalg.norm([np.cos(np.radians(30)) - 1, np.sin(np.radians(30))])))

sqc = polyline([(0, 0, 0), (2, 0, 0), (2, 1, 0), (0, 1, 0)], True)
_, F = frames(CTC(sqc, tangent_type="central_difference"))
check("Central Difference, closed curve: point 0 = direction of closing edge (0,-1) + first edge (2,0)", close(F[0, :, 2], np.array([2, -1, 0]) / np.sqrt(5)))
hair = polyline([(0, 0, 0), (1, 0, 0), (0, 0, 0.0)])
_, F = frames(CTC(hair, tangent_type="central_difference", target_up="y_axis"))
check("Central Difference at a 180° reversal (the two edges sum to 0): uses the next edge", close(F[1, :, 2], (-1, 0, 0)))
dup = polyline([(0, 0, 0), (0, 0, 0), (1, 0, 0), (2, 1, 0)])
_, F = frames(CTC(dup, extrapolate_ends=True, target_up="custom", up_x=0.0, up_y=0.0, up_z=1.0))
_, F0_ = frames(CTC(dup, target_up="custom", up_x=0.0, up_y=0.0, up_z=1.0))
check("no extrapolation when the first segment has length 0 (no edge to mirror)", close(F[0], F0_[0]))

sec("Copy to Curves:Target Up Vector")
_, F = frames(CTC(arc))
check("Curve Normal (default): counter-clockwise arc in the xy plane -> up = +z", close(F[:, :, 1], (0, 0, 1)))
_, F = frames(CTC(line4))
check("Curve Normal, straight line (no plane): falls back to the Y axis", close(F[:, :, 1], (0, 1, 0)))
lz = polyline([(0, 0, 0), (1, 0, 0), (2, 0, 0)])
lz.set(PRIM, "start_up", np.array([[0, 0, 1]], np.float32))
_, F = frames(CTC(lz, target_up="attribute"))
check("Attribute: prim attribute start_up = (0,0,1)", close(F[:, :, 1], (0, 0, 1)))
lz.set(PRIM, "myup", np.array([[0, 1, 1]], np.float32))
_, F = frames(CTC(lz, target_up="attribute", start_up_attrib="myup"))
check("Attribute: attribute name configurable, projected onto the normal plane (0,1,1)->(0,1,1)/√2", close(F[:, :, 1], np.array([0, 1, 1]) / r2_))
_, F = frames(CTC(lz, target_up="attribute", start_up_attrib="nothere"))
check("Attribute not found: uses the Y axis", close(F[:, :, 1], (0, 1, 0)))
_, F = frames(CTC(lz, target_up="custom", up_x=0.0, up_y=0.0, up_z=-1.0))
check("Custom = the old Up X/Y/Z", close(F[:, :, 1], (0, 0, -1)))
hx = polyline([(np.cos(a), np.sin(a), 0.4 * a) for a in np.linspace(0, 3, 9)])
_, F = frames(CTC(hx, target_up="y_axis"))
check("At Start (default): the start up is exactly the target projected onto the normal plane", close(F[0, :, 1], _unit(np.array([0, 1, 0]) - F[0, :, 2] * F[0, 1, 2])))
_, F2 = frames(CTC(hx, target_up="y_axis", up_at_start=False))
ang = []
for i in range(9):
    t_ = F2[i, :, 2]
    q_ = _unit(np.array([0, 1, 0]) - t_ * t_[1])
    ang.append(np.arctan2(np.cross(F2[i, :, 1], q_) @ t_, F2[i, :, 1] @ q_))
check("Average: the angles between each point's up and the target (around the circle) average to 0; the start is no longer exactly aligned",
      abs(np.arctan2(np.sin(ang).mean(), np.cos(ang).mean())) < 1e-6 and not close(F2[0], F[0], 1e-3))
_, F3 = frames(CTC(hx, target_up="custom", up_x=0.0, up_y=1.0, up_z=0.0, use_end_up=True, end_up_x=1.0, end_up_y=0.0,
                   end_up_z=0.0))
t_ = F3[-1, :, 2]
q_ = _unit(np.array([1.0, 0, 0]) - t_ * t_[0])
check("Use Target End Up Vector: the last point's up matches End Up, start unchanged", close(F3[-1, :, 1], q_) and close(F3[0], F[0]))
_, F4 = frames(CTC(hx, target_up="custom", up_x=0.0, up_y=1.0, up_z=0.0, use_end_up=True, up_at_start=False))
check("End Up requires At Start: with At Start off End Up is ignored (same as only turning At Start off)", close(F4, F2))


tl = polyline([(0.1, 0.2, 0.3), (0.4, 0.9, 0.4), (0.7, 1.6, 0.5), (1.3, 3.0, 0.7)])
_, F = frames(CTC(tl))
check("Curve Normal, slanted straight line (in float, Newell is not exactly 0): still falls back to the Y axis", close(F[0, :, 1], _unit(np.array([0, 1, 0]) - F[0, :, 2] * F[0, 1, 2])))
tlf = polyline(P_(tl) + np.array([1000.0, -500.0, 300.0]))
_, F = frames(CTC(tlf))
check("the same slanted line moved far from the origin (1000, float32 error ~1e-4): the threshold scales with coordinate size, still recognized as a line", close(F[0, :, 1], _unit(np.array([0, 1, 0]) - F[0, :, 2] * F[0, 1, 2]), 1e-4))
ly = polyline([(0, 0, 0), (0, 1, 0), (0, 2, 0)])
_, F = frames(CTC(ly, target_up="y_axis"))
check("target up parallel to the tangent: picks any perpendicular up (no NaN)", np.all(np.isfinite(F)) and close(F[:, :, 1] @ (0, 1, 0), 0))
knot = polyline([(np.cos(a), np.sin(a) * (1 + 0.5 * np.cos(a)), 0.8 * np.sin(2 * a) + 0.5 * np.cos(a))
                 for a in np.linspace(0, 2 * np.pi, 13)[:-1]], True)
_cfm = __import__("comfyui_pcg.geo.curveframe", fromlist=["x"])
Pk = P_(knot)


def wrap_angle(F):
    """How far (in radians) the last point's up, carried back to the start along the RMF, is from the start up."""
    w = _cfm.rmf_double_reflection(np.vstack([Pk[-1:], Pk[:1]]), np.vstack([F[-1:, :, 2], F[:1, :, 2]]), F[-1, :, 1])[1]
    return np.arctan2(np.cross(w, F[0, :, 1]) @ F[0, :, 2], w @ F[0, :, 1])


_, F = frames(CTC(knot, target_up="y_axis"))
_, Fn = frames(CTC(knot, target_up="y_axis", closed_continuous=False))
el = np.linalg.norm(np.diff(np.vstack([Pk, Pk[:1]]), axis=0), axis=1)
check("Make Closed Curve Orientations Continuous: the extra twist around the loop is spread by arc length -- the closing edge keeps only its share"
      " (= total × closing edge length / perimeter); unticked it all lands on the closing edge",
      abs(wrap_angle(Fn)) > 0.1 and close(wrap_angle(F), wrap_angle(Fn) * el[-1] / el.sum(), 1e-4),
      (wrap_angle(F), wrap_angle(Fn)))
lz.set(PRIM, "end_up", np.array([[1, 0, 0]], np.float32))
lzb = polyline([(0, 0, 0), (0, 0, 1), (0, 0, 2)])
lzb.set(PRIM, "start_up", np.array([[0, 1, 0]], np.float32))
lzb.set(PRIM, "end_up", np.array([[1, 0, 0]], np.float32))
_, F = frames(CTC(lzb, target_up="attribute", use_end_up=True))
check("Attribute + End Up: last point up = prim attribute end_up (1,0,0), start = start_up (0,1,0)",
      close(F[-1, :, 1], (1, 0, 0)) and close(F[0, :, 1], (0, 1, 0)))
_, F = frames(CTC(lzb, target_up="custom", up_x=0.0, up_y=1.0, up_z=0.0, use_end_up=True, end_up_x=0.0, end_up_y=0.0,
                  end_up_z=1.0))
check("End Up parallel to the last tangent: not adjusted (no NaN)", np.all(np.isfinite(F)) and close(F[:, :, 1], (0, 1, 0)))

sec("Copy to Curves:Additional Rotations")
_, F0 = frames(CTC(line4, target_up="y_axis"))
_, F = frames(CTC(line4, target_up="y_axis", apply_roll=True, roll=90.0))
check("Roll 90: up rotated 90° about the tangent (Y -> -X = (0,0,1)), tangent unchanged", close(F[:, :, 1], (0, 0, 1)) and close(F[:, :, 2], (1, 0, 0)))
_, F = frames(CTC(line4, target_up="y_axis", roll=90.0))
check("negative control: Apply Roll unticked, Roll has no effect", close(F, F0))


def roll_of(F):
    """Line along +x, up = y: after Roll a, up = (0, cos a, sin a)."""
    return np.degrees(np.arctan2(F[:, 2, 1], F[:, 1, 1]))


def roll_vs(F, F0):
    """How many degrees F's up is rotated about the tangent relative to F0's up (0~360)."""
    a = np.degrees(np.arctan2(np.einsum("ni,ni->n", np.cross(F0[:, :, 1], F[:, :, 1]), F0[:, :, 2]),
                              np.einsum("ni,ni->n", F0[:, :, 1], F[:, :, 1])))
    return np.round(a, 6) % 360


uneq = polyline([(0, 0, 0), (1, 0, 0), (3, 0, 0), (3.5, 0, 0)])
for per, exp in (("per_edge", [0, 10, 20, 30]), ("per_unit_distance", [0, 10, 30, 35]),
                 ("full_curve_by_edges", [0, 10 / 3, 20 / 3, 10]), ("full_curve_by_distance", [0, 10 / 3.5, 30 / 3.5, 10])):
    _, F = frames(CTC(uneq, target_up="y_axis", apply_roll=True, partial_twist=10.0, twist_per=per))
    check(f"Twist Per {per}: per-point angles {np.round(exp, 3).tolist()}°", close(roll_of(F), exp, 1e-3), roll_of(F).round(3).tolist())
_, F = frames(CTC(uneq, target_up="y_axis", apply_roll=True, full_twists=1, partial_twist=-350.0))
check("Full Twists 1 + Partial -350 = 10° per edge", close(roll_of(F), [0, 10, 20, 30], 1e-3))
uneq.set(POINT, "tw", np.array([[0], [2], [-1], [0.5]], np.float32))
_, F = frames(CTC(uneq, target_up="y_axis", apply_roll=True, roll=5.0, partial_twist=10.0, twist_per="scale_by_attribute",
                  twist_ramp_attrib="tw"))
check("Scale by Attribute: Roll + 10° × attribute (not accumulated)", close(roll_of(F), [5, 25, -5, 10], 1e-3))
sqx = polyline([(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)], True)
_, F = frames(CTC(sqx, target_up="y_axis", apply_roll=True, partial_twist=100.0))
_, F0c = frames(CTC(sqx, target_up="y_axis"))
_, Fn = frames(CTC(sqx, target_up="y_axis", apply_roll=True, partial_twist=100.0, closed_continuous=False))
_, F0n = frames(CTC(sqx, target_up="y_axis", closed_continuous=False))
check("closed square with 100° per edge (400° per loop): Continuous rounds to whole turns -> 90° per edge; unticked -> 100°",
      close(roll_vs(F, F0c), [0, 90, 180, 270], 1e-3) and close(roll_vs(Fn, F0n), [0, 100, 200, 300], 1e-3),
      (roll_vs(F, F0c).tolist(), roll_vs(Fn, F0n).tolist()))
_, F = frames(CTC(sqx, target_up="y_axis", apply_roll=True, partial_twist=360.0, twist_per="full_curve_by_edges"))
check("closed curve Per Full Curve by Edges: 4 edges share one full turn -> 90° per point", close(roll_vs(F, F0c), [0, 90, 180, 270], 1e-3))
rect = polyline([(0, 0, 0), (2, 0, 0), (2, 0, 1), (0, 0, 1)], True)
_, Fr0 = frames(CTC(rect, target_up="y_axis"))
_, F = frames(CTC(rect, target_up="y_axis", apply_roll=True, partial_twist=70.0, twist_per="per_unit_distance"))
check("closed 2×1 rectangle with 70° per unit length (420° per loop) -> rounded to 360°: 60° per unit", close(roll_vs(F, Fr0), [0, 120, 180, 300], 1e-3),
      roll_vs(F, Fr0).tolist())
_, F = frames(CTC(rect, target_up="y_axis", apply_roll=True, partial_twist=400.0, twist_per="full_curve_by_distance"))
check("closed Per Full Curve by Distance 400° -> rounded to 360°", close(roll_vs(F, Fr0), [0, 120, 180, 300], 1e-3))
_, F = frames(CTC(uneq, target_up="y_axis", apply_roll=True, roll=5.0, partial_twist=10.0, twist_per="scale_by_attribute",
                  twist_ramp_attrib="nope"))
check("Scale by Attribute, attribute missing: only Roll remains", close(roll_of(F), 5, 1e-3))
uneq.set(PRIM, "ptw", np.array([[3]], np.float32))
_, F = frames(CTC(uneq, target_up="y_axis", apply_roll=True, partial_twist=10.0, twist_per="scale_by_attribute",
                  twist_ramp_attrib="ptw"))
check("Ramp attribute is a prim attribute: 30° for the whole curve", close(roll_of(F), 30, 1e-3))
_, F = frames(CTC(line4, target_up="y_axis", apply_yaw=True, yaw=90.0))
check("Yaw 90: rotates about up, tangent column Z -> X outward (0,0,-1); up unchanged", close(F[:, :, 2], (0, 0, -1)) and close(F[:, :, 1], (0, 1, 0)))
_, F = frames(CTC(line4, target_up="y_axis", apply_yaw=True, incremental_yaw=30.0, yaw_per="per_edge"))
yaw_ang = np.degrees(np.arctan2(-F[:, 2, 2], F[:, 0, 2]))
check("Incremental Yaw 30 per edge", close(yaw_ang, [0, 30, 60, 90], 1e-3), yaw_ang.round(3).tolist())
_, F = frames(CTC(line4, target_up="y_axis", apply_pitch=True, pitch=90.0))
check("Pitch 90: rotates about the outward axis, tangent column Z -> -up (0,-1,0)", close(F[:, :, 2], (0, -1, 0)) and close(F[:, :, 0], (0, 0, -1)))
Ry = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float)                # 90° about local Y
Rx = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float)                # 90° about local X
F0m = F0[0]
for order, R_ in (("pyr", Ry @ Rx), ("ypr", Rx @ Ry)):
    _, F = frames(CTC(line4, target_up="y_axis", apply_yaw=True, yaw=90.0, apply_pitch=True, pitch=90.0, rotate_order=order))
    check(f"Rotate Order {order}: the one listed first rotates first -> frame = curve frame × later × earlier", close(F[0], F0m @ R_))
line4.set(POINT, "pw", np.array([[0], [1], [2], [3]], np.float32))
_, F = frames(CTC(line4, target_up="y_axis", apply_pitch=True, incremental_pitch=10.0, pitch_per="scale_by_attribute",
                  pitch_ramp_attrib="pw"))
pang = np.degrees(np.arctan2(-F[:, 1, 2], F[:, 0, 2]))
check("Pitch Scale By Attribute: 10° × point attribute", close(pang, [0, 10, 20, 30], 1e-3), pang.round(3).tolist())
lz.set(DETAIL, "dw", np.array([[3.0]], np.float32))
_, F = frames(CTC(lz, target_up="y_axis", apply_yaw=True, incremental_yaw=10.0, yaw_per="scale_by_attribute",
                  yaw_ramp_attrib="dw"))
check("Ramp attributes also accept detail attributes: 30° per point", close(np.degrees(np.arctan2(-F[:, 2, 2], F[:, 0, 2])), 30, 1e-3))

sec("Copy to Curves: Scales, Stretch, curve point attributes")
_, F = frames(CTC(line4, target_up="y_axis", uniform_scale=2.0))
check("Uniform Scale 2: all three axes have length 2", close(np.linalg.norm(F, axis=1), 2))
lp_ = polyline([(0, 0, 0), (1, 0, 0), (2, 0, 0)])
lp_.set(POINT, "pscale", np.array([[3], [3], [3]], np.float32))
lp_.set(POINT, "N", np.array([[0, 0, 1]] * 3, np.float32))
lp_.set(POINT, "Cd", np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], np.float32))
_, F = frames(CTC(lp_, target_up="y_axis"))
check("negative control: Transform Using Curve Point Attributes unticked -> pscale / N ignored", close(np.linalg.norm(F, axis=1), 1)
      and close(F[:, :, 2], (1, 0, 0)))
_, F = frames(CTC(lp_, target_up="y_axis", use_point_attribs=True, uniform_scale=2.0))
check("ticked: N used as tangent (0,0,1), pscale 3 × Uniform 2 = 6", close(F[:, :, 2], (0, 0, 6)) and close(np.linalg.norm(F, axis=1), 6))
_, F = frames(CTC(lp_, target_up="y_axis", use_point_attribs=True, normalize_scales=True))
check("Normalize Scales: pscale ignored", close(np.linalg.norm(F, axis=1), 1))
lp2 = polyline([(0, 0, 0), (1, 0, 0), (2, 0, 0)])
lp2.set(POINT, "up", np.array([[0, 0, 1]] * 3, np.float32))
lp2.set(POINT, "trans", np.array([[0, 5, 0]] * 3, np.float32))
O, F = frames(CTC(lp2, target_up="y_axis", use_point_attribs=True))
check("up attribute on curve points overrides the target up; trans translates", close(F[:, :, 1], (0, 0, 1)) and close(O[:, 1], 5))
lp3 = polyline([(0, 0, 0), (1, 0, 0)])
lp3.set(POINT, "orient", np.array([[0, 0, 0, 1], [0, 0, np.sin(np.pi / 4), np.cos(np.pi / 4)]], np.float32))
_, F = frames(CTC(lp3, use_point_attribs=True))
check("orient on curve points: frame = quaternion (second point rotated 90° about z)", close(F[0], np.eye(3)) and close(F[1][:, 0], (0, 1, 0)))
lp3.set(POINT, "rot", np.array([[0, 0, 0, 1], [0, 0, np.sin(np.pi / 4), np.cos(np.pi / 4)]], np.float32))
_, F = frames(CTC(lp3, use_point_attribs=True))
check("rot rotates once more inside orient (180° total at the second point)", close(F[1][:, 0], (-1, 0, 0)))
lp3.set(POINT, "transform", np.tile(np.eye(3, dtype=np.float32).reshape(1, 9) * 2, (2, 1)))
_, F = frames(CTC(lp3, use_point_attribs=True))
check("the transform attribute wins (2 × identity)", close(F, np.eye(3) * 2))
lp4 = polyline([(0, 0, 0), (1, 0, 0)])
q90 = np.array([np.sin(np.pi / 4), 0, 0, np.cos(np.pi / 4)], np.float32)
lp4.set(POINT, "rot", np.tile(q90, (2, 1)))
_, F = frames(CTC(lp4, target_up="y_axis", use_point_attribs=True))
_, F0_ = frames(CTC(lp4, target_up="y_axis"))
Rq = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float)
check("rot inside the curve frame (frame × rot)", close(F[0], F0_[0] @ Rq) and not close(F[0], Rq @ F0_[0]))
corner = polyline([(0, 0, 0), (1, 0, 0), (1, 1, 0)])
_, F = frames(CTC(corner, stretch_around_turns=True))
check("Stretch Around Turns: at a right-angle corner stretched √2 along the miter direction (= outward X), other axes unchanged; ends not stretched",
      close(np.linalg.norm(F[1], axis=0), [r2_, 1, 1]) and close(np.linalg.norm(F[[0, 2]], axis=1), 1))
_, F = frames(CTC(polyline([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], True), stretch_around_turns=True))
check("closed square: all 4 corners stretched √2", close(np.linalg.norm(F[:, :, 0], axis=1), r2_))
_, F = frames(CTC(corner, stretch_around_turns=True, max_stretch=1.2))
check("Max Stretch 1.2 caps it", close(np.linalg.norm(F[1], axis=0), [1.2, 1, 1]))
_, F = frames(CTC(corner))
check("negative control: unticked -> no stretch", close(np.linalg.norm(F[1], axis=0), 1))
g = CTC(lp_, target_up="y_axis", target_attributes="Cd")
check("Attributes from Target: Cd of the curve points copied onto the copy's points", close(np.asarray(g.get(POINT, "Cd")).reshape(3, 4, 3)[:, 0], np.eye(3)))
check("negative control: empty -> not copied", CTC(lp_, target_up="y_axis").get(POINT, "Cd") is None)
check("curvenum / copynum still written", np.asarray(CTC(lp_).get(POINT, "copynum"))[::4, 0].tolist() == [0, 1, 2])

sec("Copy to Curves: Source Group, Piece Attribute")
two_src = ops.merge(polyline([(0, 0, 0), (0.1, 0, 0)]), polyline([(0, 0, 0), (0, 0.1, 0), (0, 0.2, 0)]))
two_src.set_string(PRIM, "name", np.array(["a", "b"], object))
two_src.set_group(PRIM, "pb", np.array([False, True]))
two_src.set_group(POINT, "pt", np.array([True, True, False, False, False]))
check("Source Group (prim group): only piece 2 copied -> 3 points per copy", CTC(lp_, source=two_src, source_group="pb").npoints == 9)
check("Source Group (point group, Guess): only the first 2 points copied -> 2 points per copy", CTC(lp_, source=two_src, source_group="pt").npoints == 6)
check("Source Group Type = Point says by point explicitly", CTC(lp_, source=two_src, source_group="pt", source_group_type="point").npoints == 6)
lp_.set_string(POINT, "name", np.array(["b", "a", "a"], object))
g = CTC(lp_, source=two_src, piece_attribute="name")
cp = np.asarray(g.get(POINT, "copynum"))[:, 0]
check("Piece Attribute on curve points: pieces picked by the point's name (b, a, a -> 3 + 2 + 2 points; copy 0 is the 3-point piece)",
      g.npoints == 7 and g.nprims == 3 and (cp == 0).sum() == 3)
g = CTC(lp_, source=two_src, piece_attribute="name", mode="count", count=3)
check("the Count mode also reads Source Group (defaults of the old two modes unchanged)", CTC(lp_, source=two_src, mode="count", count=2, source_group="pb").npoints == 6)

sec("Copy to Curves: old behaviour, panel")
bad = {k: (GOLDEN.get(k), NOW.get(k)) for k in GOLDEN if k.startswith("ctc_") and GOLDEN[k] != NOW.get(k)}
check("digests of three old count / spacing calls match before the change", not bad, bad)
check("panel self-check", not PANEL.check_layout("PCG_CopyToCurves", M["PCG_CopyToCurves"].INPUT_TYPES()),
      PANEL.check_layout("PCG_CopyToCurves", M["PCG_CopyToCurves"].INPUT_TYPES()))


# ════════════════════════════════════════════════════════════════ Chain(Deform Along Curve)
from comfyui_pcg.geo import build as _build                              # noqa: E402


def CH(curves, src, **kw):
    kw.setdefault("chain_mode", "deform_along_curve")
    return run("PCG_Chain", source=src, curves=curves, **kw)


def boxz(lz=0.4, w=0.2, h=0.1, at=(0, 0, 0), pid=None):
    g = _build.box(size=(w, h, lz), center=at)
    if pid is not None:
        g.set(PRIM, "id", np.full((g.nprims, 1), pid, np.int32))
    return g


B4 = boxz()
L4 = polyline([(0, 0, 0), (4, 0, 0)])
sec("Chain (Deform Along Curve): placement, deformation")
check("Chain Mode menu (default Rigid Links = old behaviour)", opts("PCG_Chain", "chain_mode") == ["rigid_links", "deform_along_curve"])
g = CH(L4, B4, index_attrib="ix")
P = P_(g)
check("a line of length 4, links of length .4: Fit places 10 links, boxes laid end to end along +x filling [0, 4]",
      int(np.asarray(g.get(POINT, "ix")).max()) == 9 and close(P.min(0), (0, -0.05, -0.1)) and close(P.max(0), (4, 0.05, 0.1)))
corner = np.array([0.1, 0.05, 0.2])
gi = np.asarray(g.get(POINT, "ix"))[:, 0]
check("local -> curve: side = source x -> curve frame X = up × tangent = -z; up = source y; forward = source z -> arc length (corner (.1,.05,.2) of link 0 -> (.4,.05,-.1))",
      any(close(p, (0.4, 0.05, -0.1)) for p in P[gi == 0]))
arc = polyline([(2 * np.cos(a), 2 * np.sin(a), 0) for a in np.linspace(0, np.pi / 2, 201)])
rod = polyline([(0, 0, 0), (0, 0, 1)])
rod2 = ops.merge(rod, polyline([(0.1, 0, 0), (0.1, 0, 1)]))
g = CH(arc, rod)
rr = np.linalg.norm(P_(g)[:, :2], axis=1)
check("quarter arc (radius 2, length π), rod of length 1: 3 links placed, stretched to length π -- all rod points lie on the arc (radius 2)",
      g.npoints == 6 and close(rr, 2, 1e-4) and close(P_(g)[:, 2], 0) and close(P_(g)[-1], (0, 2, 0), 1e-4), rr.round(5).tolist())
g = CH(arc, rod2)
rr = np.linalg.norm(P_(g)[:, :2], axis=1)
check("rod offset .1 towards side (source +x): curve frame X = up(+z) × tangent = towards the center -> radius 1.9", sorted(set(np.round(rr, 3))) == [1.9, 2.0])
g = run("PCG_Chain", source=rod, curves=arc, spacing=0.0, roll_step=0.0)
check("negative control: Rigid Links (old) places each link rigidly on the chord, points not on the arc", not close(np.linalg.norm(P_(g)[:, :2], axis=1), 2, 1e-3))
g = CH(L4, B4, enable_deformation=False, index_attrib="ix")
check("Enable Deformation off: laid out in a straight line along world Z (x = side, y = up, z = arc-length coordinate)",
      close(P_(g).min(0), (-0.1, -0.05, 0)) and close(P_(g).max(0), (0.1, 0.05, 4)))

sec("Chain: Number of Pieces, Map Length, Offset")
g = CH(L4, B4, number_of_pieces="explicit", num_pieces=4, index_attrib="ix")
check("Explicit 4 links: stretched to fill (each 1 long)", int(np.asarray(g.get(POINT, "ix")).max()) == 3 and close(P_(g)[:, 0].max(), 4)
      and close(np.ptp(P_(g)[np.asarray(g.get(POINT, "ix"))[:, 0] == 0][:, 0]), 1))
g = CH(L4, B4, fraction_of_curve=0.5, index_attrib="ix")
check("Fraction of Curve .5: only 5 links (2 long), Map Length (whole curve) stretches them to 4", int(np.asarray(g.get(POINT, "ix")).max()) == 4
      and close(P_(g)[:, 0].max(), 4))
g = CH(L4, B4, fraction_of_curve=0.5, map_length_using="fraction_geo")
check("Map Length Using Fraction of Geo Length 1: natural length, occupies [0, 2]", close(P_(g)[:, 0].max(), 2))
g = CH(L4, B4, map_length_using="distance", map_length=3.0)
check("Map Length = Distance 3: 10 links squeezed into [0, 3]", close(P_(g)[:, 0].max(), 3))
g = CH(L4, B4, map_length_using="fraction_geo", map_length=0.5, fraction_of_curve=0.5)
check("Fraction of Geo Length .5: a chain of natural length 2 squeezed to 1", close(P_(g)[:, 0].max(), 1))
g = CH(L4, B4, map_length_using="fraction_geo", fraction_of_curve=0.5, position_offset=0.25)
check("Offset Curve U .25: starts at s = 1 -> [1, 3]", close([P_(g)[:, 0].min(), P_(g)[:, 0].max()], [1, 3]))
g = CH(L4, B4, map_length_using="fraction_geo", fraction_of_curve=0.5, offset_using="distance", position_offset=0.5)
check("Offset Distance .5 → [.5, 2.5]", close([P_(g)[:, 0].min(), P_(g)[:, 0].max()], [0.5, 2.5]))
g = CH(L4, B4, map_length_using="fraction_geo", fraction_of_curve=0.5, offset_using="fraction_geo", position_offset=0.5)
check("Offset Fraction of Geo .5 (chain length 2) -> [1, 3]", close([P_(g)[:, 0].min(), P_(g)[:, 0].max()], [1, 3]))
L4a = polyline([(0, 0, 0), (4, 0, 0)])
L4a.set(PRIM, "pend", np.array([[2.0]], np.float32))
L4a.set(PRIM, "poff", np.array([[1.0]], np.float32))
g = CH(L4a, B4, map_length_using="distance", map_length=3.0, map_length_attrib="pend", offset_using="distance",
       offset_attrib="poff")
check("Pos End / Pos Offset attributes override per curve: Distance 2, starting at 1 -> [1, 3]", close([P_(g)[:, 0].min(), P_(g)[:, 0].max()], [1, 3]))
two = ops.merge(boxz(pid=0), boxz(lz=0.2, at=(1, 0, 0), pid=1))
g = CH(L4, two, only_full_pattern=False, fraction_of_curve=0.25, map_length_using="fraction_geo", index_attrib="ix")
check("two pieces (.4 and .2) alternating, budget 1: .4 + .2 + .4 = 1 -> 3 links", int(np.asarray(g.get(POINT, "ix")).max()) == 2)
g = CH(L4, two, only_full_pattern=True, fraction_of_curve=0.25, map_length_using="fraction_geo", index_attrib="ix")
check("Only Repeat Full Pattern: 3 links cut to 2 (a whole cycle)", int(np.asarray(g.get(POINT, "ix")).max()) == 1)
g = CH(L4, B4, uniform_piece_scale=2.0, index_attrib="ix", map_length_using="fraction_geo")
check("Uniform Piece Scale 2: each link .8 long, width/height doubled too -> 5 links", int(np.asarray(g.get(POINT, "ix")).max()) == 4
      and close(P_(g)[:, 1].max(), 0.1))

sec("Chain:Start / End Behavior")
kw = dict(map_length_using="fraction_geo", offset_using="distance", fraction_of_curve=0.5)
g = CH(L4, B4, position_offset=-1.0, **kw)
check("starting at s = -1, Extend: extended along the start tangent -> x ∈ [-1, 1]", close([P_(g)[:, 0].min(), P_(g)[:, 0].max()], [-1, 1]))
g = CH(L4, B4, position_offset=-1.0, start_behavior="clamp", **kw)
check("Clamp: out-of-range points stop at the start (bunched at x = 0)", close(P_(g)[:, 0].min(), 0) and (np.abs(P_(g)[:, 0]) < 1e-6).sum() > 8)
g = CH(L4, B4, position_offset=-1.0, start_behavior="clip", index_attrib="ix", **kw)
check("Clip: geometry with s < 0 is cut away (the first 2 links gone entirely, link 2 cut at x = 0)",
      close(P_(g)[:, 0].min(), 0) and close(P_(g)[:, 0].max(), 1) and int(np.asarray(g.get(POINT, "ix")).min()) == 2)
g = CH(L4, B4, position_offset=3.0, end_behavior="clip", **kw)
check("End Clip: s > 4 cut away -> x ∈ [3, 4]", close([P_(g)[:, 0].min(), P_(g)[:, 0].max()], [3, 4]))
g = CH(L4, B4, position_offset=3.0, end_behavior="clamp", **kw)
check("End Clamp: stops at the end point x = 4", close(P_(g)[:, 0].max(), 4))
g = CH(L4, B4, position_offset=3.0, **kw)
check("End Extend -> x reaches 5", close(P_(g)[:, 0].max(), 5))
sq4 = polyline([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], True)
rod4 = polyline([(0, 0, 0), (0, 0, 0.4)])
g = CH(sq4, rod4, map_length_using="fraction_geo", offset_using="distance", position_offset=3.5, fraction_of_curve=0.25)
check("closed curves have no ends: s wraps by perimeter (two .4 rods from s = 3.5 to 4.3, wrapping past the start to (.3, 0))",
      close(P_(g), [(0, 0.5, 0), (0, 0.1, 0), (0, 0.1, 0), (0.3, 0, 0)], 1e-5), P_(g).round(4).tolist())

sec("Chain: Repeat Pattern, end pieces")


def piece_ids(g):
    ix = np.asarray(g.get(POINT, "ix"))[:, 0]
    pid = np.asarray(g.get(PRIM, "id"))[:, 0]
    first = g.vertex_point[g.prim_offset[:-1]]
    return [int(pid[np.nonzero(ix[first] == k)[0][0]]) for k in range(int(ix.max()) + 1)]


kw = dict(index_attrib="ix", number_of_pieces="explicit", num_pieces=6)
check("Cycle:0 1 0 1 0 1", piece_ids(CH(L4, two, **kw)) == [0, 1, 0, 1, 0, 1])
check("Offset 1: starts with piece 1", piece_ids(CH(L4, two, pattern_offset=1, **kw)) == [1, 0, 1, 0, 1, 0])
check("Explicit Pattern '0 0 1'", piece_ids(CH(L4, two, repeat_pattern="explicit", class_pattern="0 0 1", **kw)) == [0, 0, 1, 0, 0, 1])
r1 = piece_ids(CH(L4, two, repeat_pattern="random", rand_seed=3, **kw))
r2 = piece_ids(CH(L4, two, repeat_pattern="random", rand_seed=3, **kw))
rs = [tuple(piece_ids(CH(L4, two, repeat_pattern="random", rand_seed=sd, **kw))) for sd in range(6)]
check("Random: same seed same result, different seeds differ", r1 == r2 and len(set(rs)) > 1)
rp = piece_ids(CH(L4, two, repeat_pattern="random", rand_seed=5, repeat_length=2, **kw))
check("Repeat Length 2: two random pieces, then repeated", rp[:2] * 3 == rp)
check("Weighted Random weights '1 0': all piece 0", piece_ids(CH(L4, two, repeat_pattern="weighted_random", piece_weights="1 0", **kw))
      == [0] * 6)
two_w = two.copy()
two_w.set(PRIM, "weight", np.array([[0.0]] * 6 + [[1.0]] * 6, np.float32))
check("Weighted Random from Attribute (prim attribute weight, piece 0 is 0): all piece 1",
      piece_ids(CH(L4, two_w, repeat_pattern="weighted_random_attrib", **kw)) == [1] * 6)
check("start and end pieces = piece 1, not in the pattern: 1 0 0 0 0 1",
      piece_ids(CH(L4, two, use_start_cap=True, start_cap_piece=1, use_end_cap=True, end_cap_piece=1, **kw)) == [1, 0, 0, 0, 0, 1])
check("end pieces also in the pattern: 1 0 1 0 1 1", piece_ids(CH(L4, two, use_start_cap=True, start_cap_piece=1, use_end_cap=True,
                                                end_cap_piece=1, exclude_end_pieces=False, **kw)) == [1, 0, 1, 0, 1, 1])
g = CH(arc, B4, use_start_cap=True, start_cap_piece=0, rigid_end_pieces=True, index_attrib="ix")
g0 = CH(arc, B4, use_start_cap=True, start_cap_piece=0, index_attrib="ix")
cap = P_(g)[np.asarray(g.get(POINT, "ix"))[:, 0] == 0]
cap0 = P_(g0)[np.asarray(g0.get(POINT, "ix"))[:, 0] == 0]
Pb = P_(B4)
dd_ = lambda Q: np.linalg.norm(Q[:, None] - Q[None], axis=2)  # noqa: E731
ratio = np.pi / 2.8                                                       # 7 links × .4 stretched to arc length π
Pb_s = P_(B4) * [1, 1, ratio]
check("Do Not Deform End Pieces: end pieces are rigid (point distances = source distances scaled along Forward by the chain's stretch ratio); unticked they bend",
      close(dd_(cap), dd_(Pb_s), 1e-5) and not close(dd_(cap0), dd_(Pb_s), 1e-4))
check("two pieces: pieces found by connectivity (Find Pieces default)", len(set(piece_ids(CH(L4, two, **kw)))) == 2)
twoa = ops.merge(boxz(pid=0), boxz(lz=0.2, at=(1, 0, 0), pid=1))
twoa.set(PRIM, "pc", np.zeros((12, 1), np.int32))
check("By Piece Attribute: attribute all 0 -> everything is one piece (both boxes together)",
      CH(L4, twoa, find_pieces="piece_attribute", piece_attribute="pc", **kw).nprims == 6 * 12)

sec("Chain: Deformation (Scale / Rotation), Alignment")
g = CH(L4, B4, enable_scale=True, base_scale=2.0)
check("Base Scale 2: offset from the curve doubled (y ±.1, z ±.2), unchanged along the curve", close(P_(g).max(0), (4, 0.1, 0.2)))
L4s = polyline([(0, 0, 0), (4, 0, 0)])
L4s.set(POINT, "w", np.array([[1], [3]], np.float32))
g = CH(L4s, B4, enable_scale=True, scale_attrib="w")
yx = P_(g)[P_(g)[:, 1] > 0]
check("curve point attribute w (1 -> 3) multiplies the scale: .05 at x = 0, .15 at x = 4", close(yx[np.argmin(yx[:, 0]), 1], 0.05)
      and close(yx[np.argmax(yx[:, 0]), 1], 0.15))
g = CH(L4, B4, enable_rotation=True, base_rotation=90.0)
check("Base Rotation 90: rotated 90° about the curve (y range becomes ±.1, z ±.05)", close(P_(g).max(0), (4, 0.1, 0.05)))
rodx = polyline([(0, 0, 0), (1, 0, 0)])
check("Forward Direction X: a rod along x gives the same result as a rod along z (Forward Z)",
      close(P_(CH(arc, rodx, forward_dir="x", up_dir="y")), P_(CH(arc, rod))))
check("Forward Custom (1,0,0) = X", close(P_(CH(arc, rodx, forward_dir="custom", forward_x=1.0, forward_z=0.0)), P_(CH(arc, rod))))
check("Up Direction Z, Forward X: up is the source z", close(P_(CH(arc, rodx, forward_dir="x", up_dir="z")), P_(CH(arc, rod)), 1e-6))
off = boxz(at=(0.5, 0.3, 0))
check("Center Geometry on Curve: a box offset to (.5,.3) is centered", close(P_(CH(L4, off, center_on_curve=True)), P_(CH(L4, B4))))
check("negative control: offset when unticked", not close(P_(CH(L4, off)), P_(CH(L4, B4))))
g = CH(L4, B4, piece_rotation=90.0, index_attrib="ix", number_of_pieces="explicit", num_pieces=2)
p1 = P_(g)[np.asarray(g.get(POINT, "ix"))[:, 0] == 1]
check("Piece Rotation 90: link 1 rotated 90° (y range ±.1)", close(p1[:, 1].max(), 0.1) and close(p1[:, 2].max(), 0.05))
g = CH(L4, B4, curve_up_control="z")
check("Curve Up Control Z: up = z (source y goes to z)", close(P_(g).max(0)[1:], (0.1, 0.05)))
g = CH(L4, B4, curve_up_control="custom", up_x=0.0, up_y=0.0, up_z=-1.0)
check("Custom = the old Up X/Y/Z", close(P_(g).max(0)[1:], (0.1, 0.05)))
check("Curve Normal (default): normal of the arc's plane +z", close(np.ptp(P_(CH(arc, rod2))[:, 2]), 0))

sec("Chain: attributes, groups, closed")
Bn = boxz()
Bn.set(POINT, "N", np.tile(np.array([[0, 1, 0]], np.float32), (Bn.npoints, 1)))
g = CH(L4, Bn, enable_rotation=True, base_rotation=90.0)
check("Attributes to Transform (N): N in the source up direction follows the frame + the rotation about the curve -> (0,0,1)",
      close(np.asarray(g.get(POINT, "N")), (0, 0, 1)))
g = CH(L4, Bn, attribs_to_transform="")
check("negative control: cleared -> N unchanged", close(np.asarray(g.get(POINT, "N")), (0, 1, 0)))
g = CH(L4, B4, position_attrib="pu", index_attrib="ix", curvenum_attrib="cn", number_of_pieces="explicit", num_pieces=2)
pu = np.asarray(g.get(POINT, "pu"))[:, 0]
check("outputs Position Along Curve (s / L), Index, Curve Number, copynum",
      close(pu, P_(g)[:, 0] / 4, 1e-5) and set(np.asarray(g.get(POINT, "ix"))[:, 0]) == {0, 1}
      and set(np.asarray(g.get(POINT, "cn"))[:, 0]) == {0} and np.asarray(g.get(PRIM, "copynum"))[:, 0].tolist() == [0] * 6 + [1] * 6)
check("negative control: empty names not written", CH(L4, B4).get(POINT, "pu") is None)
twog = two.copy()
twog.set_group(PRIM, "only1", np.array([False] * 6 + [True] * 6))
check("Geometry Group: only piece 1 (the short one)", set(piece_ids(CH(L4, twog, geometry_group="only1", **kw))) == {1})
L2c = ops.merge(L4, polyline([(0, 2, 0), (4, 2, 0)]))
g = CH(L2c, B4, group="1", curvenum_attrib="cn")
check("Curve Group: only along curve 1", set(np.asarray(g.get(POINT, "cn"))[:, 0]) == {1} and close(P_(g)[:, 1].min(), 1.95))

sec("Chain: edge cases")
check("By Piece Attribute but empty attribute name: falls back to connectivity", digest(CH(L4, two, find_pieces="piece_attribute", piece_attribute="", **kw))
      == digest(CH(L4, two, **kw)))
cloud = Geometry.from_points(np.array([(0, 0, -0.1), (0, 0, 0.1)], np.float32))
check("source is a point cloud (no faces): one piece per point", CH(L4, cloud, index_attrib="ix", number_of_pieces="explicit", num_pieces=4).npoints == 4)
Lc = polyline([(0, 0, 0), (1, 0, 0), (1, 1, 0)])
ladder = ops.merge(polyline([(0, 0, z) for z in np.linspace(0, 1, 101)]), polyline([(0.1, 0, z) for z in np.linspace(0, 1, 101)]))
ladder.set(PRIM, "pc", np.zeros((2, 1), np.int32))
g = CH(Lc, ladder, find_pieces="piece_attribute", piece_attribute="pc", number_of_pieces="explicit", num_pieces=1)
side = P_(g)[101:]
check("tangents interpolated within segments at corners: a rod offset to one side stays continuous around the corner (neighbouring point distance < .05)", np.linalg.norm(np.diff(side, axis=0), axis=1).max() < 0.05,
      np.linalg.norm(np.diff(side, axis=0), axis=1).max())
hxc = np.array([(np.cos(a), np.sin(a), 0.6 * a) for a in np.linspace(0, 3, 7)])
from comfyui_pcg.geo.chainsop import _sampler                              # noqa: E402
at_, Lh = _sampler(hxc, False, np.array([0.0, 1.0, 0.0]))
_, tt_, uu_ = at_(np.linspace(0, Lh, 97))
check("curve frame sampling: the interpolated up is re-projected onto the tangent's normal plane (on a helix up·T = 0, unit length)",
      np.abs(np.einsum("ij,ij->i", tt_, uu_)).max() < 1e-9 and close(np.linalg.norm(uu_, axis=1), 1, 1e-9))
rs_ = polyline([(0.1, 0, 0), (0.1, 0, 0.4)])
check("Curve Normal of a slanted line (float32 noise) falls back to Y", close(P_(CH(tl, rs_, number_of_pieces="explicit", num_pieces=1)),
                                                  P_(CH(tl, rs_, number_of_pieces="explicit", num_pieces=1, curve_up_control="y"))))
check("Explicit Pattern piece numbers out of range wrap modulo the piece count ('0 3' = 0 1)",
      piece_ids(CH(L4, two, repeat_pattern="explicit", class_pattern="0 3", **kw)) == [0, 1, 0, 1, 0, 1])
check("all weights 0: uniform random (no error)", len(piece_ids(CH(L4, two, repeat_pattern="weighted_random", piece_weights="0 0", **kw))) == 6)
check("Up parallel to Forward: picks any perpendicular direction (with Forward Z it picks Y, same as default)", close(P_(CH(L4, B4, up_dir="z")), P_(CH(L4, B4))))
tri_ = polyline([(0, 0, 0), (1, 0, 0), (1, 0, 0.4)], True)
g = CH(L4, tri_, center_on_curve=True)
check("Center on Curve uses the bounding box center (not the point average): triangle side range [-.5, .5]", close([P_(g)[:, 2].min(), P_(g)[:, 2].max()], [-0.5, 0.5]))
check("start and end pieces + Spacing .6: budget counts end piece + spacing -> 4 links", int(np.asarray(CH(L4, B4, use_start_cap=True, use_end_cap=True, spacing=0.6,
                                                                      index_attrib="ix", map_length_using="fraction_geo")
                                                            .get(POINT, "ix")).max()) == 3)
check("not even the end pieces fit (budget .2 < .4): nothing is output", CH(L4, B4, use_start_cap=True, fraction_of_curve=0.05).npoints == 0)
rodside = polyline([(0.1, 0.1, 0), (0.1, 0.1, 0.4)])
g = CH(L4, rodside, piece_rotation=30.0, index_attrib="ix", number_of_pieces="explicit", num_pieces=2)
p1 = P_(g)[np.asarray(g.get(POINT, "ix"))[:, 0] == 1]
c30, s30 = np.cos(np.pi / 6), np.sin(np.pi / 6)
a_r, b_r = 0.1 * c30 - 0.1 * s30, 0.1 * s30 + 0.1 * c30
check("Piece Rotation 30: link 1's (side, up) offset (.1, .1) rotated 30° counter-clockwise -> world (y = up', z = -side')",
      close(p1[:, 1:], [(b_r, -a_r)] * 2), p1.round(4).tolist())
rodup = polyline([(0, 0.1, 0), (0, 0.1, 0.4)])
g = CH(L4, rodup, enable_rotation=True, base_rotation=90.0)
check("Base Rotation 90: up offset (0, .1) becomes (-.1, 0) -> world z = +.1", close(P_(g)[:, 1:], [(0, 0.1)] * g.npoints))
g = CH(L4, B4, position_offset=-1.0, start_behavior="clip", index_attrib="ix", map_length_using="fraction_geo",
       map_length=2.0, offset_using="distance", fraction_of_curve=0.5)
check("Clip + chain stretched 2×: cut at chain coordinate .5 (= arc length 0), x from 0 to 3", close([P_(g)[:, 0].min(), P_(g)[:, 0].max()], [0, 3]))
g = CH(L4, B4, position_offset=2.0, end_behavior="clip", map_length_using="fraction_geo", map_length=2.0,
       offset_using="distance", fraction_of_curve=0.5)
check("End Clip + stretched 2×: cut at arc length 4 (out-of-range links dropped entirely, not bunched at the end: only the 4 points of the cut face at x = 4)",
      close([P_(g)[:, 0].min(), P_(g)[:, 0].max()], [2, 4]) and (P_(g)[:, 0] > 4 - 1e-5).sum() == 4, (P_(g)[:, 0] > 4 - 1e-5).sum())
Bw = boxz()
Bw.set(POINT, "w", np.ones((Bw.npoints, 1), np.float32))
check("Attributes to Transform matching attributes that are not 3-component: skipped (no error)", CH(L4, Bw, attribs_to_transform="*").npoints == 80)
L4t = polyline([(0, 0, 0), (4, 0, 0)])
L4t.set_string(POINT, "ws", np.array(["a", "b"], object))
check("scale attribute is a string: treated as 1", close(P_(CH(L4t, B4, enable_scale=True, scale_attrib="ws")), P_(CH(L4t, B4))))
sqw = polyline([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], True)
sqw.set(POINT, "w", np.array([[1], [1], [1], [3]], np.float32))
g = CH(sqw, rodup, enable_scale=True, scale_attrib="w", number_of_pieces="explicit", num_pieces=8,
       map_length_using="distance", map_length=4.0)
zz_ = P_(g)[:, 2]
check("closed curve attributes interpolate back to the first point on the closing edge (w drops from 3 to 1)", close(zz_.max(), 0.3) and close(P_(g)[np.argmax(zz_), :2], (0, 1), 1e-5))
g = CH(L4, B4, enable_deformation=False, offset_using="distance", position_offset=1.0, map_length_using="fraction_geo",
       fraction_of_curve=0.5)
check("without deformation z is the arc-length coordinate (incl. Offset): [1, 3]", close([P_(g)[:, 2].min(), P_(g)[:, 2].max()], [1, 3]))

sec("Chain: old behaviour, panel")
bad = {k: (GOLDEN.get(k), NOW.get(k)) for k in GOLDEN if k.startswith("ch_") and GOLDEN[k] != NOW.get(k)}
check("digests of two old Rigid Links calls match before the change", not bad, bad)
check("panel self-check", not PANEL.check_layout("PCG_Chain", M["PCG_Chain"].INPUT_TYPES()),
      PANEL.check_layout("PCG_Chain", M["PCG_Chain"].INPUT_TYPES()))


# ════════════════════════════════════════════════════════════════ Edge Equalize
EE = lambda g, **kw: run("PCG_EdgeEqualize", geo=g, **kw)  # noqa: E731
iso = polylines([[(0, 0, 0), (1, 0, 0)], [(0, 1, 0), (3, 1, 0)]])
sec("Edge Equalize:Method(Houdini)")
check("Method menu: redistribute (old, default) + Houdini's three modes",
      opts("PCG_EdgeEqualize", "method") == ["redistribute", "average", "longest", "shortest"])
g = EE(iso, edges="", method="average")
check("two unconnected edges (length 1, 3), Average -> both become 2, each scaled about its midpoint",
      close(P_(g), [(-0.5, 0, 0), (1.5, 0, 0), (0.5, 1, 0), (2.5, 1, 0)]))
g = EE(iso, edges="", method="longest")
check("Longest → 3", close(P_(g), [(-1, 0, 0), (2, 0, 0), (0, 1, 0), (3, 1, 0)]))
g = EE(iso, edges="", method="shortest")
check("Shortest → 1", close(P_(g), [(0, 0, 0), (1, 0, 0), (1, 1, 0), (2, 1, 0)]))
ch3 = polyline([(0, 0, 0), (1, 0, 0), (3, 0, 0), (3, 2, 0)])
g, r = __import__("comfyui_pcg.geo.meshedit", fromlist=["x"]).edge_equalize_hou(ch3, "", "average")
Lg = chords(P_(g))
check("a chain (edge lengths 1, 2, 2): iterates until every edge has the average length 5/3 (connected edges pull on each other)", close(Lg, 5 / 3, 1e-6) and r["max_error"] < 1e-8,
      (Lg.tolist(), r))
check("the report has the target length and iteration count", close(r["target"], 5 / 3) and r["iterations"] > 1 and r["edges"] == 3)
ch3.set_edge_group("e", [(1, 2)])
g = EE(ch3, edges="e", method="shortest", group_type="edges")
Pg = P_(g)
check("only one edge selected (1-2, length 2), Shortest = itself -> unchanged; unselected points never move", close(Pg, P_(ch3)))
ch3.set_edge_group("e2", [(0, 1), (2, 3)])
g = EE(ch3, edges="e2", method="longest")
check("Guess: name is an edge group -> by edge; selecting 0-1 (1) and 2-3 (2), Longest = 2: 0-1 stretched to 2 about its midpoint, 2-3 unchanged",
      close(P_(g), [(-0.5, 0, 0), (1.5, 0, 0), (3, 0, 0), (3, 2, 0)]))
ch3.set_group(POINT, "pg", np.array([False, True, True, True]))
g = EE(ch3, edges="pg", method="shortest")
check("Guess: name is a point group -> edges with both ends in the group (1-2, 2-3)", close(chords(P_(g))[1:], 2) and close(P_(g)[0], (0, 0, 0)))
g = EE(ch3, edges="1-3", method="shortest", group_type="points")
check("Group Type = Points, by point numbers 1-3", close(P_(g), P_(EE(ch3, edges="pg", method="shortest"))))
sqe = ops.merge(polyline([(0, 0, 0), (2, 0, 0), (2, 1, 0), (0, 1, 0)], True), polyline([(5, 0, 0), (6, 0, 0)]))
sqe.set_group(PRIM, "q", np.array([True, False]))
g = EE(sqe, edges="q", method="longest")
check("Guess: name is a prim group -> all edges of that face (2×1 rectangle -> all four sides become 2), the other line unchanged",
      close(chords(np.vstack([P_(g)[:4], P_(g)[:1]])), 2, 1e-6) and close(P_(g)[4:], P_(sqe)[4:]))
g = EE(sqe, edges="0", method="longest", group_type="prims")
check("Group Type = Primitives, by prim number", close(P_(g), P_(EE(sqe, edges="q", method="longest"))))
sqe.set_group(POINT, "q", np.array([True, True, False, False, False, False]))
g = EE(sqe, edges="q", method="longest")
check("Guess: both a point group and a prim group with the same name -> by point (only edge 0-1, already the longest, unchanged)", close(P_(g), P_(sqe)))
ch3.set_edge_group("bad", [(0, 2), (0, 1)])
g = EE(ch3, edges="bad", method="longest", output_edge_group="o")
check("point pairs in the edge group that are not edges (0-2): ignored", sorted(map(tuple, np.asarray(g.edge_groups["o"]).tolist())) == [(0, 1)])
z0 = polyline([(1, 1, 1), (1, 1, 1)])
check("selected edges all of length 0: returned unchanged (no error)", close(P_(EE(z0, edges="", method="average")), P_(z0)))
star = ops.merge(*[polyline([(0, 0, 0), (np.cos(a) * (1 + k), np.sin(a) * (1 + k), 0)])
                   for k, a in enumerate(np.linspace(0, 2 * np.pi, 7)[:-1])])
star = ops.fuse(star, 1e-6)
g, r = __import__("comfyui_pcg.geo.meshedit", fromlist=["x"]).edge_equalize_hou(star, "", "average")
elen = [float(np.linalg.norm(np.diff(P_(g)[g.prim_points(i)], axis=0))) for i in range(g.nprims)]
check("star (center point pulled by 6 edges, 7 points): averaging the corrections at shared points is needed to converge, all 6 edges reach the average length 3.5",
      star.npoints == 7 and r["max_error"] < 1e-8 and close(elen, 3.5, 1e-6), (star.npoints, r))
dz = polylines([[(0, 0, 0), (0, 0, 0)], [(0, 1, 0), (2, 1, 0)]])
g, r = __import__("comfyui_pcg.geo.meshedit", fromlist=["x"]).edge_equalize_hou(dz, "", "shortest")
check("zero-length edges are not counted in the target length (Shortest = 2, not 0)", close(r["target"], 2) and close(P_(g), P_(dz)))
g = EE(iso, edges="", method="average", output_edge_group="eq")
check("Output Edge Group: written with the processed edges", sorted(map(tuple, np.asarray(g.edge_groups["eq"]).tolist())) == [(0, 1), (2, 3)])
check("negative control: empty -> not written", "eq" not in EE(iso, edges="", method="average").edge_groups)
gr = fixtures()["grid"]
g = EE(gr, edges="e", output_edge_group="moved")
check("the old Redistribute mode also writes Output Edge Group (= the selected edges), points same as old behaviour",
      len(np.asarray(g.edge_groups["moved"])) == 4 and close(P_(g), P_(EE(gr, edges="e"))))

sec("Edge Equalize: old behaviour, panel")
bad = {k: (GOLDEN.get(k), NOW.get(k)) for k in GOLDEN if k.startswith("ee_") and GOLDEN[k] != NOW.get(k)}
check("digests of two old Redistribute calls (arc_length / chord) match before the change", not bad, bad)
check("panel self-check", not PANEL.check_layout("PCG_EdgeEqualize", M["PCG_EdgeEqualize"].INPUT_TYPES()),
      PANEL.check_layout("PCG_EdgeEqualize", M["PCG_EdgeEqualize"].INPUT_TYPES()))


print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
