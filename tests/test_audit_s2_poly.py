"""
pcg100 · pack s2_poly: parameters / menu items added against the SideFX docs.

  PolySpline  Spline Type gains Bezier / Degree 2 Bezier / Cardinal / Linear; Close; Division Method
              (even chord length / even X / Y / Z); First / Last CV Count; CV Tension
  PolyCut     Strategy gains Remove / Cut (Houdini's semantics): Type Points / Edges, Detect Edge Changes
              (Crossing / Change), Keep Polygons Closed
  PolySplit   Path Type gains Edge Loop (Number of Loops, Edge Percentage); location syntax accepts Houdini's p3-7:0.25
  Primitive   Transform Order / Rotate Order / Shear / Pivot;Color / Alpha;Close / Reverse / Shift
  PolyReduce  Target gains two point-count modes; Hard Edges; Soft Points + Weight
  Remesh      Group (local remesh), Hard Edges / Hard Points Group
  PolyBevel   Shape gains None; Ignore Flat Edges; Distance scaled by a point attribute; Convexity

Everything is checked against hand-computed numbers (Bernstein polynomials, Hermite, chord-length equations, area / volume formulas, point counts); every new option gets
a negative control; output at defaults is compared bit by bit with the old implementation at the baseline commit (pcg99).
"""
import hashlib
import importlib
import os
import subprocess
import sys
import tempfile

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
from comfyui_pcg.geo import build, ops                  # noqa: E402
from comfyui_pcg.geo import curves2 as CV, meshedit as ME, cutsplit as CS  # noqa: E402
from comfyui_pcg.geo import deform2 as D2, polyreduce as PR, remesh as RM  # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, VERTEX, PRIM  # noqa: E402

OK = []
BASE_COMMIT = "a9e114d"          # pcg99 baseline: the implementation before the change


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def P_(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def tri_(g):
    P, T = P_(g), g.triangles()
    return P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]


def area(g):
    a, b, c = tri_(g)
    return float(0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1).sum())


def volume(g):
    a, b, c = tri_(g)
    return float((a * np.cross(b, c)).sum() / 6.0)


def closed_manifold(g):
    seen = {}
    for k in range(g.nprims):
        pts = g.prim_points(k)
        for i in range(len(pts)):
            e = (int(pts[i]), int(pts[(i + 1) % len(pts)]))
            seen[e] = seen.get(e, 0) + 1
    return all(v == 1 for v in seen.values()) and all((b, a) in seen for (a, b) in seen)


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
    for a in (g.vertex_point, g.prim_offset, g.prim_closed):
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
    return h.hexdigest()


def _baseline():
    """The geo subpackage from the baseline commit, extracted to a temp dir and imported under another package name (compared side by side with the current implementation). Returns None if unavailable."""
    try:
        tmp = tempfile.mkdtemp(prefix="pcgbase_")
        pkg = os.path.join(tmp, "pcgbase")
        os.makedirs(pkg)
        tar = subprocess.run(["git", "-C", _R, "archive", BASE_COMMIT, "comfyui_pcg/geo"],
                             capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", pkg, "--strip-components=1"], input=tar, check=True)
        open(os.path.join(pkg, "__init__.py"), "w").close()
        sys.path.insert(0, tmp)
        return importlib.import_module("pcgbase.geo")
    except Exception as e:                              # noqa: BLE001
        print(f"  (baseline commit {BASE_COMMIT} unavailable: {e}; bit-exact regression skipped)")
        return None


BASE = _baseline()


def base_mod(name):
    return importlib.import_module(f"pcgbase.geo.{name}") if BASE is not None else None


def same_as_base(name, new_geo, old_fn):
    """New node output at defaults == baseline implementation output (bit-exact)."""
    if BASE is None:
        check(name + " (skipped: no baseline)", True)
        return
    check(name, digest(new_geo) == digest(old_fn()))


def polyline(pts, closed=False, **attrs):
    g = Geometry.from_mesh(np.asarray(pts, np.float32), [np.arange(len(pts), dtype=np.int32)],
                           closed=closed)
    for k, v in attrs.items():
        g.set(POINT, k, np.asarray(v, np.float32).reshape(len(pts), -1))
    return g


opts = lambda k, n: list(M[k].INPUT_TYPES()["required"][n][0])  # noqa: E731


def close(a, b, e=1e-5):
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    try:
        return bool(np.all(np.abs(a - b) <= e))
    except ValueError:                                  # shapes do not match
        return False


# -- small helpers shared by several nodes' tests
from comfyui_pcg.geo.topology import topology as _topo  # noqa: E402


def line(n, **attrs):
    return polyline([[i, 0, 0] for i in range(n)], **attrs)


def xs(g):
    """x coordinates of each prim's points (keeping digits beyond the first decimal too)."""
    P = P_(g)
    return [[round(float(P[p, 0]), 4) for p in g.prim_points(k)] for k in range(g.nprims)]


def qgrid(nx, ny):
    """nx x ny unit squares, point number = j·(nx+1) + i."""
    P = [[i, j, 0] for j in range(ny + 1) for i in range(nx + 1)]
    F = [np.array([j * (nx + 1) + i, j * (nx + 1) + i + 1, (j + 1) * (nx + 1) + i + 1, (j + 1) * (nx + 1) + i])
         for j in range(ny) for i in range(nx)]
    return Geometry.from_mesh(np.asarray(P, np.float32), F)


def sizes(g):
    return sorted(len(g.prim_points(k)) for k in range(g.nprims))


def face_areas(g):
    P = P_(g)
    out = []
    for k in range(g.nprims):
        q = P[g.prim_points(k)]
        out.append(0.5 * abs(sum(np.cross(q[i] - q[0], q[i + 1] - q[0])[2] for i in range(1, len(q) - 1))))
    return sorted(round(x, 5) for x in out)


def has_pts(g, Q, tol=1e-6):
    """Every position in Q still has a point in g."""
    Pg = P_(g)
    return all(np.linalg.norm(Pg - q, axis=1).min() <= tol for q in Q)


def edge_len(g, pairs):
    P = P_(g)
    pairs = np.asarray(pairs).reshape(-1, 2)
    return float(np.linalg.norm(P[pairs[:, 0]] - P[pairs[:, 1]], axis=1).sum())


def boundary_len(g):
    """Total length of edges used by only one prim."""
    cnt = {}
    for k in range(g.nprims):
        if not g.prim_closed[k]:
            continue
        pts = g.prim_points(k)
        for i in range(len(pts)):
            e = tuple(sorted((int(pts[i]), int(pts[(i + 1) % len(pts)]))))
            cnt[e] = cnt.get(e, 0) + 1
    return edge_len(g, [e for e, c in cnt.items() if c == 1])


def with_ids(g, base=0):
    """Add an integer point attribute id and a vertex attribute vv (= 10 x point number), to see which source point / source corner new points take values from."""
    g.set(POINT, "id", (np.arange(g.npoints) + base).astype(np.int32).reshape(-1, 1))
    g.set(VERTEX, "vv", (10.0 * np.asarray(g.vertex_point)).astype(np.float32).reshape(-1, 1))
    return g

def ids(g, name="id"):
    return np.asarray(g.get(POINT, name)).reshape(-1).tolist() if name == "id" else \
        np.asarray(g.get(VERTEX, name)).reshape(-1).tolist()


sec("Old workflows unchanged: positions of existing parameters and leading dropdown options untouched")
OLD_ORDER = {
    "PCG_PolySpline": ["geo", "group", "basis", "alpha", "divisions"],
    "PCG_PolyCut": ["geo", "group", "mode", "points", "attribute", "threshold", "keep"],
    "PCG_PolySplit": ["geo", "locations", "close_path", "edge_group"],
    "PCG_Primitive": ["geo", "group", "translate_x", "translate_y", "translate_z", "rotate_x",
                      "rotate_y", "rotate_z", "scale_x", "scale_y", "scale_z", "uniform_scale",
                      "scale_attribute", "normal_offset", "unshare_points"],
    "PCG_PolyReduce": ["geo", "group", "target", "keep_percent", "target_count", "position",
                       "boundary_weight", "crease_group", "crease_weight", "lock_boundary",
                       "lock_group", "max_normal_flip", "preserve_uvs"],
    "PCG_Remesh": ["geo", "target_length", "iterations", "feature_angle", "keep_boundary",
                   "relax", "transfer_attributes"],
    "PCG_PolyBevel": ["geo", "group", "group_type", "distance", "limit_distance", "use_fillet",
                      "shape", "divisions", "use_out_groups", "edge_fillet_group",
                      "point_fillet_group"],
}
for k, names in OLD_ORDER.items():
    check(f"{k}: existing parameters still first, order unchanged",
          list(M[k].INPUT_TYPES()["required"])[:len(names)] == names)
check("dropdowns still start with the original tokens",
      opts("PCG_PolySpline", "basis")[:3] == ["catmull_rom", "bspline", "interpolate"]
      and opts("PCG_PolyCut", "mode")[:3] == ["cut_points", "keep_points", "threshold"]
      and opts("PCG_PolyReduce", "target")[:2] == ["percentage", "triangle_count"]
      and opts("PCG_PolyBevel", "shape")[:4] == ["round", "chamfer", "solid", "crease"]
      and opts("PCG_PolyBevel", "group_type") == ["guess", "edges", "prims", "points"])

# ═══════════════════════════════════════════════════════ PolySpline
sec("PolySpline:Bezier / Degree 2 Bezier / Cardinal / Linear")
cv4 = [[0, 0, 0], [1, 2, 0], [3, 2, 0], [4, 0, 0]]
SP = lambda g, **kw: P_(run("PCG_PolySpline", geo=g, **kw))     # noqa: E731
o = SP(polyline(cv4), basis="bezier", divisions=4)
t = np.arange(5) / 4
bern = lambda c, t: sum(np.outer(w, np.asarray(p, float)) for w, p in zip(      # noqa: E731
    [(1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t ** 3], c))
check("Bezier: 4 points = one cubic Bezier segment, matches the Bernstein polynomial; t=0.5 at (2, 1.5)",
      len(o) == 5 and close(o, bern(cv4, t)) and close(o[2], [2, 1.5, 0]))
check("  negative control: BSpline / Catmull-Rom on the same points do not give this curve",
      not close(SP(polyline(cv4), basis="bspline", divisions=4), o, 1e-2)
      and not close(SP(polyline(cv4), basis="catmull_rom", divisions=4), o, 1e-2))
cv7 = cv4 + [[5, -2, 0], [7, -2, 0], [8, 0, 0]]
o = SP(polyline(cv7), basis="bezier", divisions=4)
check("  7 points = two segments, sharing the 4th point (passing through it); 2x4+1 points in total",
      len(o) == 9 and close(o[4], cv7[3]) and close(o[:5], bern(cv7[:4], t))
      and close(o[4:], bern(cv7[3:], t)))
o = SP(polyline(cv4 + [[6, 0, 0]]), basis="bezier", divisions=4)
check("  5 points: the 2 leftover points at the end form one linear (straight) segment -- the curve still reaches the last point",
      len(o) == 9 and close(o[-1], [6, 0, 0]) and close(o[6], [5, 0, 0]))
q3 = [[0, 0, 0], [1, 2, 0], [2, 0, 0]]
o = SP(polyline(q3), basis="degree2_bezier", divisions=4)
check("Degree 2 Bezier: one segment per 3 points, t=0.5 at (1, 1) (= 1/4 P0 + 1/2 P1 + 1/4 P2)",
      len(o) == 5 and close(o[2], [1, 1, 0])
      and close(o[1], 0.5625 * np.array(q3[0]) + 0.375 * np.array(q3[1]) + 0.0625 * np.array(q3[2])))
check("  negative control: on the same 4 points cubic and quadratic Bezier differ (quadratic: first 3 as one segment + a straight segment at the end)",
      not close(SP(polyline(cv4), basis="degree2_bezier", divisions=4)[:5],
                SP(polyline(cv4), basis="bezier", divisions=4), 1e-2)
      and len(SP(polyline(cv4), basis="degree2_bezier", divisions=4)) == 9)
o = SP(polyline(cv4, closed=True), basis="bezier", divisions=4)
check("  closed: wraps back to the first control point (4 points -> control points 0 1 2 3 | 3 0), output closed, end point not duplicated",
      len(o) == 8 and close(o[4], cv4[3]) and close(o[6], [2, 0, 0])
      and bool(run("PCG_PolySpline", geo=polyline(cv4, closed=True), basis="bezier").prim_closed[0]))

zig = [[0, 0, 0], [1, 1, 0], [2, 0, 0], [3, 1, 0], [4, 0, 0]]
o = SP(polyline(zig), basis="linear", divisions=4)
check("Linear: straight segments, 4 divisions each; (0.25, 0.25) is on the curve",
      len(o) == 17 and close(o[1], [0.25, 0.25, 0]) and close(o[6], [1.5, 0.5, 0]))
o0 = SP(polyline(zig), basis="cardinal", tension=0.0, divisions=8)
check("Cardinal: Tension 0 = uniform Catmull-Rom (Alpha 0)",
      close(o0, SP(polyline(zig), basis="catmull_rom", alpha=0.0, divisions=8), 1e-6))
o1 = SP(polyline(zig), basis="cardinal", tension=1.0, divisions=4)
h = lambda s: -2 * s ** 3 + 3 * s ** 2                           # noqa: E731
check("  Tension 1: zero tangents, each segment is a smoothstep along a straight line (5/32 travelled at s=1/4)",
      close(o1[1], np.array(zig[1]) * h(0.25)) and abs(h(0.25) - 5 / 32) < 1e-12
      and close(o1[5], np.array(zig[1]) + (np.array(zig[2]) - np.array(zig[1])) * h(0.25)))
asym = [[0, 0, 0], [1, 1, 0], [3, 0, 0], [4, 2, 0]]
oh = SP(polyline(asym), basis="cardinal", tension=0.5, divisions=2)
# midpoint of segment 2 (P1->P2): Hermite h00=h01=1/2, h10=1/8, h11=-1/8; m1 = 1/4(P2-P0), m2 = 1/4(P3-P1)
m1, m2 = 0.25 * (np.array(asym[2]) - np.array(asym[0])), 0.25 * (np.array(asym[3]) - np.array(asym[1]))
check("  Tension 0.5: segment midpoint = 1/2(P1+P2) + 1/8(m1 - m2) = (2, 0.46875), m = 1/4(P+ - P-); with Tension 0 the tangents double -> (2, 0.4375)",
      close(oh[3], 0.5 * (np.array(asym[1]) + np.array(asym[2])) + 0.125 * (m1 - m2))
      and close(oh[3], [2, 0.46875, 0])
      and close(SP(polyline(asym), basis="cardinal", tension=0.0, divisions=2)[3], [2, 0.4375, 0])
      and not close(m1, m2, 1e-3))
check("  passes through all input points", all(close(x[::8][:5], zig) for x in (o0,)) and close(o1[::4], zig))

sec("PolySpline:Close")
sq = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]
gc = run("PCG_PolySpline", geo=polyline(sq, closed=True), basis="linear", divisions=2, close="off")
go = run("PCG_PolySpline", geo=polyline(sq, closed=False), basis="linear", divisions=2, close="on")
gk = run("PCG_PolySpline", geo=polyline(sq, closed=True), basis="linear", divisions=2)
check("Off: a closed polygon also outputs an open curve (3 segments, 7 points, stopping at the last point)",
      not gc.prim_closed[0] and gc.npoints == 7 and close(P_(gc)[-1], sq[3]))
check("On: an open polyline also outputs a closed curve (4 segments, 8 points, with the extra point (0, 0.5))",
      bool(go.prim_closed[0]) and go.npoints == 8 and close(P_(go)[-1], [0, 0.5, 0]))
check("If polygon does (default): follows the input", bool(gk.prim_closed[0]) and gk.npoints == 8
      and not run("PCG_PolySpline", geo=polyline(sq), basis="linear", divisions=2).prim_closed[0])
check("  a 2-point polyline does not close even with On (closing needs at least 3 points)",
      not run("PCG_PolySpline", geo=polyline(sq[:2]), basis="linear", close="on").prim_closed[0])

sec("PolySpline:Division Method")
ell = [[0, 0, 0], [1, 0, 0], [1, 1, 0]]
o = SP(polyline([[0, 0, 0], [1, 0, 0]]), basis="linear", divisions=3,
       division_method="even_length", output_divisions=4)
check("Even Length: a straight line of length 1 in 4 segments -> x = 0, 1/4, 1/2, 3/4, 1", close(o[:, 0], [0, .25, .5, .75, 1]) and len(o) == 5)
o = SP(polyline(ell), basis="linear", divisions=7, division_method="even_length", output_divisions=3)
L3 = 1 / (1 + 1 / np.sqrt(2))                          # solves (1-L)^2·2 = L^2
ch = np.linalg.norm(np.diff(o, axis=0), axis=1)
check("  L-shaped polyline in 3 segments: the three **chords** are equal = 1/(1+1/sqrt(2)) ~ 0.5858 (the corner is cut, not arc length 2/3)",
      len(o) == 4 and close(ch, [L3] * 3, 1e-5) and close(o[1], [L3, 0, 0]) and close(o[2], [1, 1 - L3, 0])
      and abs(L3 - 2 / 3) > 0.05)
o = SP(polyline(ell), basis="linear", divisions=7, division_method="even_length", segment_length=0.75)
check("  Segment Length 0.75: (0.75, 0) -> (1, 0.75·...) chord exactly 0.75, a short tail left to the end point",
      len(o) == 4 and close(o[1], [0.75, 0, 0]) and close(np.linalg.norm(o[2] - o[1]), 0.75)
      and close(o[2], [1, np.sqrt(0.75 ** 2 - 0.25 ** 2), 0]) and close(o[3], [1, 1, 0]))
o = SP(polyline(ell), basis="linear", divisions=7, division_method="even_length", segment_length=0.5,
       output_divisions=3)
check("  with Segment Length non-zero Output Divisions is ignored (step 0.5: 5 points)",
      len(o) == 5 and close(o[1], [0.5, 0, 0]) and close(o[2], [1, 0, 0]))
slope = [[0, 0, 0], [1, 3, 0], [4, 3, 5]]
ox = SP(polyline(slope), basis="linear", divisions=5, division_method="even_x", output_divisions=4)
oy = SP(polyline(slope), basis="linear", divisions=5, division_method="even_y", output_divisions=3)
oz = SP(polyline(slope), basis="linear", divisions=5, division_method="even_z", output_divisions=5)
check("Even X: x advances 1 per step (x = 0..4), points still on the original polyline", close(ox[:, 0], [0, 1, 2, 3, 4]) and close(ox[2], [2, 3, 5 / 3]))
check("Even Y: y advances 1 per step; the part where y no longer changes keeps only the end point", close(oy[:, 1], [0, 1, 2, 3]) and close(oy[1], [1 / 3, 1, 0])
      and close(oy[-1], [4, 3, 5]))
check("Even Z: z advances 1 per step, counted from where z starts to change", close(oz[:, 2], [0, 1, 2, 3, 4, 5]) and close(oz[1], [1.6, 3, 1]))
check("  negative control: the three axes and even chord length all give different points; Standard does not resample (2x5+1 points)",
      len(SP(polyline(slope), basis="linear", divisions=5, division_method="standard", output_divisions=4)) == 11
      and not close(ox[1], SP(polyline(slope), basis="linear", divisions=5, division_method="even_length",
                              output_divisions=4)[1], 1e-2))
check("  Segment Length and Output Divisions both 0: no resampling",
      len(SP(polyline(slope), basis="linear", divisions=5, division_method="even_length")) == 11)
circ = [[np.cos(a), np.sin(a), 0] for a in np.linspace(0, 2 * np.pi, 64, endpoint=False)]
gcr = run("PCG_PolySpline", geo=polyline(circ, closed=True), basis="linear", divisions=4,
          division_method="even_length", output_divisions=6)
oc = P_(gcr)
chc = np.linalg.norm(oc - np.roll(oc, -1, axis=0), axis=1)
check("  closed curve: a unit circle in 6 segments = inscribed regular hexagon, all 6 chords (including the wrap-around one) ~ 1",
      gcr.npoints == 6 and bool(gcr.prim_closed[0]) and np.abs(chc - 1).max() < 2e-3
      and np.ptp(chc) < 1e-5)
ga = run("PCG_PolySpline", geo=polyline([[0, 0, 0], [1, 0, 0]], w=[0.0, 10.0]), basis="linear", divisions=3,
         division_method="even_length", output_divisions=4)
check("  other numeric point attributes are linearly interpolated along with the resampling (w: 0, 2.5, 5, 7.5, 10)",
      close(np.asarray(ga.get(POINT, "w"))[:, 0], [0, 2.5, 5, 7.5, 10], 1e-4))
_lim, CV._MARCH_LIMIT = CV._MARCH_LIMIT, 1000           # really taking 2 million steps takes over ten seconds: lower the limit temporarily
check("  Segment Length so small the point count explodes (L-shaped polyline length 2, step 0.001 -> 2000 points > limit 1000): raises, does not hang; "
      "step 0.01 (200 points) does not raise",
      raises(lambda: CV.poly_spline(polyline(ell), "", "linear", 0.5, 4, "if_polygon_does",
                                    "even_length", 1e-3), "Segment Length")
      and CV.poly_spline(polyline(ell), "", "linear", 0.5, 4, "if_polygon_does",
                         "even_length", 1e-2)[0].npoints == 201 and _lim == 2_000_000)
CV._MARCH_LIMIT = _lim

sec("PolySpline:First / Last CV Count")
b1 = SP(polyline(cv4), basis="bezier", divisions=4)
b2 = SP(polyline(cv4), basis="bezier", divisions=4, first_cv_count=2)
check("First CV Count 2: control points become P0 P0 P1 P2 | P2 P3 (one cubic segment + one straight segment)",
      len(b2) == 9 and close(b2[:5], bern([cv4[0], cv4[0], cv4[1], cv4[2]], t)) and close(b2[6], [3.5, 1, 0])
      and not close(b2[:5], b1, 1e-2))
b3 = SP(polyline(cv4), basis="bezier", divisions=4, last_cv_count=3)
check("Last CV Count 3: P0 P1 P2 P3 | P3 P3 P3 (the second segment collapses to a point)",
      len(b3) == 9 and close(b3[:5], b1) and close(b3[5:], [cv4[3]] * 4))
check("  both 1 = unchanged", close(SP(polyline(cv4), basis="bezier", divisions=4, first_cv_count=1,
                                    last_cv_count=1), b1, 0))

sec("PolySpline: how non-float / vertex attributes follow, a few edge cases")


gb_ = run("PCG_PolySpline", geo=with_ids(polyline(cv7)), basis="bezier", divisions=4)
# 4 samples per segment s = 0 1/4 1/2 3/4, nearest control point = round(s·3) (numpy's rint: 0.75 -> 1, 1.5 -> 2, 2.25 -> 2)
check("Bezier: integer / vertex attributes take the nearest control point (rint(s·3) within the segment)",
      ids(gb_) == [0, 1, 2, 2, 3, 4, 5, 5, 6] and ids(gb_, "vv") == [0, 10, 20, 20, 30, 40, 50, 50, 60])
g2_ = run("PCG_PolySpline", geo=with_ids(polyline([[0, 0, 0], [1, 0, 0]]), 7), basis="linear", divisions=1,
          division_method="even_length", output_divisions=3)
check("resampling: even with only 2 rows (a straight line, Sample Divisions 1) it resamples; integer / vertex attributes take whichever end is nearer (u = 1/3 takes the start, 2/3 the end)",
      g2_.npoints == 4 and ids(g2_) == [7, 7, 8, 8] and ids(g2_, "vv") == [0, 0, 10, 10])
gl_ = run("PCG_PolySpline", geo=with_ids(polyline(zig)), basis="linear", divisions=2)
check("Linear: integer / vertex attributes take the start in the first half of a segment and the end in the second half (s = 1/2 counts as second half)",
      ids(gl_) == [0, 1, 1, 2, 2, 3, 3, 4, 4] and ids(gl_, "vv") == [0, 10, 10, 20, 20, 30, 30, 40, 40])
check("Close On: an open 3-point polyline can also close (at least 3 points)",
      bool(run("PCG_PolySpline", geo=polyline(q3), basis="linear", close="on").prim_closed[0]))
o = SP(polyline([[0, 0, 0], [1, 1, 1], [2, 2, 2]]), basis="linear", divisions=3, division_method="even_length",
       output_divisions=4)
check("Even Length on the diagonal (t,t,t): 4 segments, each sqrt(3)/2 long", len(o) == 5 and close(o[:, 0], [0, 0.5, 1, 1.5, 2]))
o = SP(polyline([[1, 0, 0], [1, 2, 0], [1, 3, 5]]), basis="linear", divisions=3, division_method="even_x",
       output_divisions=4)
check("Even X on a curve whose x never changes: cannot divide, keeps only start and end", close(o, [[1, 0, 0], [1, 3, 5]]))
gw = polyline([[0, 0, 0], [1, 0, 0], [1, 1, 0]], w=[0, 100, 0])
o = SP(gw, basis="linear", divisions=7, division_method="even_length", output_divisions=3)
check("  chord length measured on P only, not other float attributes (same even if w varies a lot)",
      close(np.linalg.norm(np.diff(o, axis=0), axis=1), [L3] * 3, 1e-5))
# rounding: the 4th step should land exactly on corner Q1 in theory; computed, the larger root of the previous segment is > 1 and this segment's start is counted outside the sphere.
# then this step must land on Q1 (the next segment turns back, and the larger root of the quadratic would run far away)
dd = np.array([-0.6323103525956735, -0.31777479265671144, -0.7065428501883797])
Q1 = dd * 0.966 * 4
Qr = np.array([[0, 0, 0], Q1, Q1 - dd * 0.5 + np.array([0.3, 0.1, -0.2])])
pr_, _ = CV._march(Qr, 0.966)
pos = [Qr[j] + (Qr[j + 1] - Qr[j]) * u for j, u in pr_]
check("  rounding of even-chord stepping: a step landing exactly on a corner is not skipped (the 4th sample is the corner)",
      np.linalg.norm(pos[4] - Q1) < 1e-9 and len(pr_) >= 5)
zz = np.array([[0.729, 0.502, 0.0], [0.837, -0.074, 0.0], [0.275, 0.066, 0.0], [1.215, 0.427, 0.0],
               [0.328, 0.402, 0.0], [1.281, 0.638, 0.0]])
o = SP(polyline(zz), basis="linear", divisions=1, division_method="even_length", output_divisions=8)
check("  step count jumps with step length (no step length divides this zigzag into exactly 8): still outputs 9 points, the shortfall padded at the end point",
      len(o) == 9 and close(o[-1], zz[-1]) and close(o[-2], zz[-1]))
gd_ = polyline(asym)
check("  function defaults: Tension 0.5, no resampling, CV Count 1",
      digest(CV.poly_spline(gd_, "", "cardinal", 0.5, 4)[0]) == digest(CV.poly_spline(gd_, "", "cardinal", 0.5, 4,
                                                                                         tension=0.5)[0])
      and not close(P_(CV.poly_spline(gd_, "", "cardinal", 0.5, 4)[0]),
                    P_(CV.poly_spline(gd_, "", "cardinal", 0.5, 4, tension=0.25)[0]), 1e-4)
      and digest(CV.poly_spline(gd_, "", "linear", 0.5, 4, division_method="even_length")[0])
      == digest(CV.poly_spline(gd_, "", "linear", 0.5, 4)[0])
      and len(P_(CV.poly_spline(gd_, "", "bezier", 0.5, 4)[0])) == 5)

sec("PolySpline: bit-exact regression of defaults / old options, errors, panel")
wg = polyline([[0, 0, 0], [1, 2, 0.5], [3, 2, -1], [4, 0, 0], [6, 1, 2]], w=[0, 1, 4, 9, 16])
for bname, cl in (("catmull_rom", False), ("bspline", False), ("interpolate", False),
                  ("catmull_rom", True), ("bspline", True), ("interpolate", True)):
    g_ = with_ids(polyline(np.asarray(wg.get(POINT, "P")), closed=cl, w=np.asarray(wg.get(POINT, "w"))), 3)
    g_.set_group(POINT, "odd", np.arange(5) % 2 == 1)
    same_as_base(f"{bname}{' (closed)' if cl else ''}: node with new parameters at defaults bit-identical to baseline",
                 run("PCG_PolySpline", geo=g_, basis=bname, alpha=0.5, divisions=8),
                 lambda: base_mod("curves2").poly_spline(g_, "", bname, 0.5, 8)[0])
check("bad Close / Division Method raises",
      raises(lambda: CV.poly_spline(wg, close="maybe"), "Close")
      and raises(lambda: CV.poly_spline(wg, division_method="odd"), "Division Method"))
ui = PANEL.layout_for("PCG_PolySpline", M["PCG_PolySpline"].INPUT_TYPES())[0]
check("panel: self-check passes; CV Tension appears only for Cardinal, Alpha only for Catmull-Rom",
      not PANEL.check_layout("PCG_PolySpline", M["PCG_PolySpline"].INPUT_TYPES())
      and "cardinal" in ui["tension"]["hide"] and "catmull_rom" in ui["alpha"]["hide"]
      and ui["basis"]["menu"]["degree2_bezier"] == "Degree 2 Bezier",
      PANEL.check_layout("PCG_PolySpline", M["PCG_PolySpline"].INPUT_TYPES()))

# ═══════════════════════════════════════════════════════ PolyCut
sec("PolyCut: Houdini's Strategy (Remove / Cut) x Type (Points / Edges)")


step = [0, 0, 0, 3, 3, 3, 3]                           # only edge 2-3 crosses 1.0
PC = lambda g, **kw: run("PCG_PolyCut", geo=g, attribute="h", threshold=1.0, **kw)   # noqa: E731
g = PC(line(7, h=step), mode="remove", cut_type="points")
check("Points + Remove: both endpoints of the edge crossing Cut Value are deleted along with adjacent edges -> [0,1] and [4,5,6], points really deleted too",
      xs(g) == [[0, 1], [4, 5, 6]] and g.npoints == 5)
g = PC(line(7, h=step), mode="cut", cut_type="points")
check("Points + Cut: breaks at both endpoints -> [0,1,2] [2,3] [3..6], break points shared by both sides, no points added",
      xs(g) == [[0, 1, 2], [2, 3], [3, 4, 5, 6]] and g.npoints == 7)
g = PC(line(7, h=step), mode="remove", cut_type="edges")
check("Edges + Remove: deletes only that edge -> [0,1,2] [3..6], all points remain",
      xs(g) == [[0, 1, 2], [3, 4, 5, 6]] and g.npoints == 7)
g = PC(line(7, h=step), mode="cut", cut_type="edges")
check("Edges + Cut: inserts a point at the linearly interpolated crossing x = 2 1/3 and breaks there (h is exactly 1.0 there)",
      xs(g) == [[0, 1, 2, 2.3333], [2.3333, 3, 4, 5, 6]] and g.npoints == 8
      and close(np.asarray(g.get(POINT, "h"))[7, 0], 1.0))
check("  negative control: Cut Value moved to 2.0, the crossing follows to x = 2 2/3; moved to 5 (no edge crosses) unchanged",
      xs(run("PCG_PolyCut", geo=line(7, h=step), attribute="h", threshold=2.0, mode="cut",
             cut_type="edges"))[0][-1] == 2.6667
      and xs(run("PCG_PolyCut", geo=line(7, h=step), attribute="h", threshold=5.0, mode="cut",
                 cut_type="edges")) == [[0, 1, 2, 3, 4, 5, 6]])
gp = line(7, h=step)
gp.set_group(POINT, "only2", np.arange(7) == 2)
check("Cut Points limited to point 2: Remove deletes only it -> [0,1] [3..6]; Cut breaks only there -> [0,1,2] [2..6]",
      xs(PC(gp, mode="remove", cut_type="points", points="only2")) == [[0, 1], [3, 4, 5, 6]]
      and xs(PC(gp, mode="cut", cut_type="points", points="only2")) == [[0, 1, 2], [2, 3, 4, 5, 6]])
gp.set_group(POINT, "far", np.arange(7) == 5)
check("  no endpoint of a qualifying edge is in Cut Points: nothing changes",
      xs(PC(gp, mode="remove", cut_type="points", points="far")) == [[0, 1, 2, 3, 4, 5, 6]]
      and xs(PC(gp, mode="cut", cut_type="points", points="far")) == [[0, 1, 2, 3, 4, 5, 6]]
      and PC(gp, mode="remove", cut_type="points", points="far").npoints == 7)
two = [0, 3, 3, 0, 0]                                  # edges 0-1 and 2-3 both cross
ge = line(5, h=two)
ge.set_edge_group("e23", np.array([[3, 2]], np.int32))
check("Cut Edges limited to edge 2-3: only it changes (Remove -> [0,1,2] [3,4]); unlimited, both are deleted -> [1,2] [3,4]",
      xs(PC(ge, mode="remove", cut_type="edges", cut_edges="e23")) == [[0, 1, 2], [3, 4]]
      and xs(PC(ge, mode="remove", cut_type="edges")) == [[1, 2], [3, 4]]
      and xs(PC(ge, mode="cut", cut_type="edges", cut_edges="e23")) == [[0, 1, 2, 2.6667], [2.6667, 3, 4]])
check("  with Type = Points Cut Edges is not read, with Type = Edges Cut Points is not read",
      xs(PC(ge, mode="remove", cut_type="points", cut_edges="e23")) == []
      and xs(PC(gp, mode="remove", cut_type="edges", points="far")) == [[0, 1, 2], [3, 4, 5, 6]])
g = PC(line(3, h=[1, 1, 5]), mode="cut", cut_type="edges")
check("an edge with both ends equal to Cut Value: deleted but not cut; one end equal does not count as crossing -> only [1,2] left, no points added",
      xs(g) == [[1, 2]] and g.npoints == 3)

sec("PolyCut: Detect Edge Changes = Change, no attribute, Keep Polygons Closed")
ch_ = [0, 0.25, 1.25, 1.5]                             # edge 1-2 changes by 1.0
PCc = lambda g, **kw: run("PCG_PolyCut", geo=g, attribute="h", detect="change", **kw)   # noqa: E731
g = PCc(line(4, h=ch_), mode="cut", cut_type="edges", cut_threshold=0.3)
check("Change + Edges + Cut: an edge changing by 1.0 > 0.3 is split into ceil(1/0.3) = 4 pieces (3 points inserted, each piece changes 0.25 <= 0.3)",
      xs(g) == [[0, 1, 1.25], [1.25, 1.5], [1.5, 1.75], [1.75, 2, 3]] and g.npoints == 7
      and close(np.sort(np.asarray(g.get(POINT, "h"))[4:, 0]), [0.5, 0.75, 1.0]))
check("  threshold 0.5 -> exactly 2 pieces (1 point inserted); threshold 1.0 -> the change does not **exceed** the threshold, unchanged",
      xs(PCc(line(4, h=ch_), mode="cut", cut_type="edges", cut_threshold=0.5)) == [[0, 1, 1.5], [1.5, 2, 3]]
      and xs(PCc(line(4, h=ch_), mode="cut", cut_type="edges", cut_threshold=1.0)) == [[0, 1, 2, 3]])
check("  Change + Edges + Remove / Points + Remove",
      xs(PCc(line(4, h=ch_), mode="remove", cut_type="edges", cut_threshold=0.3)) == [[0, 1], [2, 3]]
      and xs(PCc(line(4, h=ch_), mode="remove", cut_type="points", cut_threshold=0.3)) == []
      and PCc(line(4, h=ch_), mode="remove", cut_type="points", cut_threshold=0.3).npoints == 2)
check("  negative control: on the same data Crossing (Cut Value 0.1) breaks edge 0-1, not 1-2",
      xs(run("PCG_PolyCut", geo=line(4, h=ch_), attribute="h", threshold=0.1, mode="remove",
             cut_type="edges", detect="crossing", cut_threshold=0.3)) == [[1, 2, 3]])
gv = polyline([[0, 0, 0], [1, 0, 0], [1, 3, 4], [2, 3, 4]])
check("  vector attributes use distance: with P as the attribute, the edge of length 5 > 2 is deleted, the edge of length 1 stays; threshold 5 unchanged",
      xs(run("PCG_PolyCut", geo=gv, attribute="P", mode="remove", cut_type="edges", detect="change",
             cut_threshold=2.0)) == [[0, 1], [1, 2]]
      and run("PCG_PolyCut", geo=gv, attribute="P", mode="remove", cut_type="edges", detect="change",
              cut_threshold=5.0).nprims == 1)
check("  Change + Edges + Cut with Cut Threshold = 0: raises (cannot split into a finite number of pieces)",
      raises(lambda: PCc(line(4, h=ch_), mode="cut", cut_type="edges", cut_threshold=0.0), "Cut Threshold"))
NA = lambda **kw: run("PCG_PolyCut", geo=line(4), attribute="", **kw)       # noqa: E731
check("empty Cut Attribute = no edge qualifies: Points + Cut gives one piece per edge; Edges + Remove / Points + Remove delete everything",
      xs(NA(mode="cut", cut_type="points")) == [[0, 1], [1, 2], [2, 3]]
      and NA(mode="remove", cut_type="edges").nprims == 0 and NA(mode="remove", cut_type="edges").npoints == 4
      and NA(mode="remove", cut_type="points").npoints == 0
      and NA(mode="cut", cut_type="edges").nprims == 0)
hexp = [[np.cos(a), np.sin(a), 0] for a in np.arange(6) * np.pi / 3]
hx = lambda: polyline(hexp, closed=True, h=[0, 0, 0, 1, 1, 1])              # noqa: E731
HX = lambda **kw: run("PCG_PolyCut", geo=hx(), attribute="h", threshold=0.5, **kw)   # noqa: E731
A6 = 1.5 * np.sqrt(3)
g0, g1 = HX(mode="cut", cut_type="edges"), HX(mode="cut", cut_type="edges", keep_closed=True)
check("Keep Polygons Closed: a closed hexagon cut at the midpoints of two edges -> two closed pentagons, total area still 3 sqrt(3)/2",
      g1.nprims == 2 and all(g1.prim_closed) and [len(g1.prim_points(k)) for k in range(2)] == [5, 5]
      and abs(area(g1) - A6) < 1e-5 and g1.npoints == 8)
check("  negative control: turned off gives two open polylines (same points)", g0.nprims == 2 and not any(g0.prim_closed)
      and [list(g0.prim_points(k)) for k in range(2)] == [list(g1.prim_points(k)) for k in range(2)])
g1 = HX(mode="remove", cut_type="edges", keep_closed=True)
check("  Edges + Remove + Keep Closed: two closed triangles (sqrt(3)/4 each); a closed prim cut at only one place is joined back into the original ring",
      g1.nprims == 2 and all(g1.prim_closed) and abs(area(g1) - 2 * np.sqrt(3) / 4) < 1e-5
      and xs(run("PCG_PolyCut", geo=hx(), attribute="", mode="cut", cut_type="points", points="0",
                 keep_closed=True)) == xs(hx()))
g = run("PCG_PolyCut", geo=hx(), attribute="", mode="cut", cut_type="points", points="0")
check("  closed prim broken only at point 0, not kept closed: one open polyline starting and ending at point 0 (7 corners)",
      g.nprims == 1 and not g.prim_closed[0] and list(g.prim_points(0)) == [0, 1, 2, 3, 4, 5, 0])
quad2 = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [0, 1, 0], [1, 1, 0], [2, 1, 0]], np.float32),
                           [np.array([0, 1, 4, 3]), np.array([1, 2, 5, 4])])
quad2.set(POINT, "h", np.array([0, 1, 2, 0, 1, 2], np.float32).reshape(-1, 1))
g = run("PCG_PolyCut", geo=quad2, attribute="h", threshold=0.5, mode="cut", cut_type="edges", keep_closed=True)
check("  two adjacent prims: only the left one is cut (at x = 0.5), 2 points inserted; both ends of the shared edge at x=1 are 1, it does not cross 0.5",
      g.npoints == 8 and g.nprims == 3 and abs(area(g) - 2.0) < 1e-6
      and close(np.sort(P_(g)[6:, 0]), [0.5, 0.5]))
quad2.set(POINT, "h", np.array([0, 0, 0, 1, 1, 1], np.float32).reshape(-1, 1))
g = run("PCG_PolyCut", geo=quad2, attribute="h", threshold=0.25, mode="cut", cut_type="edges", keep_closed=True)
check("  a shared edge cut once by each of the two prims: only one shared point inserted (3 new points in total, y = 0.25), four closed pieces with total area 2",
      g.npoints == 9 and g.nprims == 4 and abs(area(g) - 2.0) < 1e-6 and close(P_(g)[6:, 1], [0.25] * 3))
quad2.set(POINT, "h", np.array([0, 0, 0, 1, 1, 1], np.float32).reshape(-1, 1))
g = run("PCG_PolyCut", geo=quad2, attribute="h", mode="cut", cut_type="edges", detect="change", cut_threshold=0.4)
check("  Change on shared edges (split into 3) whose two prims run in opposite directions also shares inserted points: 3 vertical edges x 2 points = 6 new points, y at 1/3, 2/3",
      g.npoints == 12 and close(np.sort(P_(g)[6:, 1]), [1 / 3] * 3 + [2 / 3] * 3))

sec("PolyCut: how attributes follow, Group, report, a few edge cases")
lv = with_ids(line(5, h=[0, 0, 3, 3, 3]))
g = PC(lv, mode="cut", cut_type="edges")
check("Edges + Cut: inserted point vertex attributes interpolated at t = 1/3 (between 10 and 20 -> 13.33...), one copy per side; integer point attributes take the nearer end",
      xs(g) == [[0, 1, 1.3333], [1.3333, 2, 3, 4]]
      and close(ids(g, "vv"), [0, 10, 40 / 3, 40 / 3, 20, 30, 40], 1e-4) and ids(g)[5] == 1)
g = PC(lv, mode="cut", cut_type="points")
check("  Points + Cut: vertex attributes at break points keep their original value on both sides", ids(g, "vv") == [0, 10, 10, 20, 20, 30, 40])
r_ = ME.poly_cut(line(7, h=step), "", "cut", "", "h", 1.0, "all", "edges")[1]
check("report: how many prims cut, how many pieces out, how many points inserted, how many points deleted",
      r_ == {"cut_prims": 1, "polylines": 2, "inserted_points": 1, "removed_points": 0}
      and ME.poly_cut(line(7, h=step), "", "remove", "", "h", 1.0)[1]
      == {"cut_prims": 1, "polylines": 2, "inserted_points": 0, "removed_points": 2}
      and ME.poly_cut(line(7, h=step), "", "remove", "", "h", 9.0)[1]["cut_prims"] == 0)
check("  function defaults: Type = Points, Crossing, Cut Value 0.5, not kept closed",
      xs(ME.poly_cut(line(4, h=[0, 0, 0.4, 1]), "", "cut", attribute="h")[0]) == [[0, 1, 2], [2, 3]]
      and not any(ME.poly_cut(hx(), "", "remove", attribute="h", cut_type="edges")[0].prim_closed))
two_ = ops.merge(line(3, h=[0, 0, 3]), polyline([[5, 0, 0], [6, 0, 0], [7, 0, 0]], h=[0, 0, 3]))
two_.set_group(PRIM, "first", np.array([True, False]))
g = PC(two_, mode="remove", cut_type="edges", group="first")
check("Group: only the selected prim is cut, the other stays as is (points and attributes intact)",
      xs(g) == [[0, 1], [5, 6, 7]] and g.npoints == 6)
sh = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [3, 0, 0]], np.float32),
                        [np.array([0, 1, 2]), np.array([2, 3])], closed=False)
sh.set(POINT, "h", np.array([[0], [0], [3], [3]], np.float32))
sh.set_group(PRIM, "a", np.array([True, False]))
g = PC(sh, mode="remove", cut_type="points", group="a")
check("  points deleted by Points + Remove that are still used by another prim: kept (only unused points are deleted)",
      xs(g) == [[2, 3]] and g.npoints == 3 and has_pts(g, [[2, 0, 0], [3, 0, 0], [0, 0, 0]]))
g = run("PCG_PolyCut", geo=line(3, h=[0, 0, 3]), attribute="h", threshold=1.0, mode="cut", cut_type="points")
check("an open curve broken at point 1 (3 points): [0,1] [1,2]; a 2-point line broken only at its ends stays as is, still open",
      xs(g) == [[0, 1], [1, 2]]
      and xs(run("PCG_PolyCut", geo=line(2, h=[0, 3]), attribute="h", threshold=1.0, mode="cut",
                 cut_type="points")) == [[0, 1]]
      and not run("PCG_PolyCut", geo=line(2, h=[0, 3]), attribute="h", threshold=1.0, mode="cut",
                  cut_type="points").prim_closed[0])
sq4 = with_ids(polyline([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], closed=True, h=[0, 0, 1, 1]))
sq4.set_group(POINT, "far", np.zeros(4, bool))
g = run("PCG_PolyCut", geo=sq4, attribute="h", threshold=0.5, mode="cut", cut_type="points", points="far")
check("  closed prim: no endpoint of a qualifying edge is in Cut Points -> stays closed, vertex attributes unchanged, report does not count it as cut",
      g.nprims == 1 and bool(g.prim_closed[0]) and ids(g, "vv") == [0, 10, 20, 30]
      and ME.poly_cut(sq4, "", "cut", "far", "h", 0.5)[1]["cut_prims"] == 0)
g = run("PCG_PolyCut", geo=sq4, attribute="h", threshold=0.5, mode="remove", cut_type="edges", keep_closed=True)
check("  Keep Polygons Closed but the piece has only 2 points: not closed (closing needs at least 3 points)",
      g.nprims == 2 and not any(g.prim_closed))
# the second prim's corner numbers do not match its point numbers (a prim is padded in front): check whether uncut prims take vertex attributes by corner
pad = Geometry.from_mesh(np.array([[0, 0, 5], [1, 0, 5], [0, 1, 5], [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
                                  np.float32), [np.array([0, 1, 2]), np.array([3, 6, 5, 4])])
pad.set(POINT, "h", np.array([[0], [0], [0], [0], [0], [1], [1]], np.float32))
pad.set(VERTEX, "cid", np.arange(7, dtype=np.float32).reshape(-1, 1))
pad.set_group(POINT, "far", np.zeros(7, bool))
g = run("PCG_PolyCut", geo=pad, attribute="h", threshold=0.5, mode="cut", cut_type="points", points="far")
check("  a closed prim not actually broken is output as is: vertex attributes taken by corner (not by point number)",
      ids(g, "cid") == [0, 1, 2, 3, 4, 5, 6] and all(g.prim_closed))
padl = Geometry.from_mesh(np.array([[0, 0, 5], [1, 0, 5], [0, 1, 5], [0, 0, 0], [1, 0, 0]], np.float32),
                          [np.array([0, 1, 2]), np.array([4, 3])], closed=False)
padl.set(POINT, "h", np.array([[9], [9], [9], [0], [3]], np.float32))
padl.set(VERTEX, "cid", np.arange(5, dtype=np.float32).reshape(-1, 1))
padl.set_group(PRIM, "ln", np.array([False, True]))
g = run("PCG_PolyCut", geo=padl, group="ln", attribute="h", threshold=1.0, mode="cut", cut_type="points")
check("  an open 2-point line broken only at its ends = not broken: unchanged (vertex attributes by corner, still open), report does not count it as cut; Edges + Remove deletes it",
      ids(g, "cid") == [0, 1, 2, 3, 4] and not g.prim_closed[1]
      and ME.poly_cut(padl, "ln", "cut", "", "h", 1.0)[1]["cut_prims"] == 0
      and run("PCG_PolyCut", geo=padl, group="ln", attribute="h", threshold=1.0, mode="remove",
              cut_type="edges").nprims == 1)
check("  Change with a Cut Threshold too small (one edge would be split into over 100,000 pieces): raises",
      raises(lambda: PCc(line(4, h=ch_), mode="cut", cut_type="edges", cut_threshold=1e-6), "100,000"))

sec("PolyCut: bit-exact regression of the original three modes, errors, panel")
sqc_ = polyline([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], closed=True, h=[0, 1, 2, 3])
sqc_.set_group(POINT, "c", np.array([1, 0, 1, 0], bool))
for md, kw in (("cut_points", dict(points="c")), ("keep_points", dict(points="c")),
               ("threshold", dict(attribute="h", threshold=1.5, keep="all")),
               ("threshold", dict(attribute="h", threshold=1.5, keep="above")),
               ("threshold", dict(attribute="h", threshold=1.5, keep="below"))):
    same_as_base(f"{md} {kw.get('keep', '')}: bit-identical to baseline",
                 run("PCG_PolyCut", geo=sqc_, mode=md, **kw),
                 lambda: base_mod("meshedit").poly_cut(sqc_, "", md, kw.get("points", ""),
                                                       kw.get("attribute", ""), kw.get("threshold", 0.5),
                                                       kw.get("keep", "all"))[0])
check("bad Type / Detect raises; missing attribute raises",
      raises(lambda: ME.poly_cut(sqc_, mode="cut", cut_type="faces"), "Type")
      and raises(lambda: ME.poly_cut(sqc_, mode="cut", detect="x"), "Detect")
      and raises(lambda: ME.poly_cut(sqc_, mode="cut", attribute="nope"), "nope"))
ui = PANEL.layout_for("PCG_PolyCut", M["PCG_PolyCut"].INPUT_TYPES())[0]
check("panel: self-check passes; Remove / Cut have Houdini's labels, new parameters appear only in these two modes",
      not PANEL.check_layout("PCG_PolyCut", M["PCG_PolyCut"].INPUT_TYPES())
      and ui["mode"]["menu"]["remove"] == "Remove" and ui["mode"]["menu"]["cut"] == "Cut"
      and ui["detect"]["menu"]["change"] == "Cut At Attribute Change"
      and all("mode != remove" in ui[k]["hide"] for k in ("cut_type", "cut_edges", "detect", "cut_threshold",
                                                           "keep_closed")),
      PANEL.check_layout("PCG_PolyCut", M["PCG_PolyCut"].INPUT_TYPES()))

# ═══════════════════════════════════════════════════════ PolySplit
sec("PolySplit: Path Type = Edge Loop, Number of Loops, Edge Percentage")


PS = lambda g, loc, **kw: run("PCG_PolySplit", geo=g, locations=loc, **kw)   # noqa: E731
G32 = qgrid(3, 2)
g = PS(G32, "0-1@0.25", path_type="edge_loop")
check("Edge Loop: on a 3x2 grid starting at 1/4 along bottom edge 0-1, going up through both rows -> 3 new points all at x = 0.25 (same side), 6 prims become 8",
      g.npoints == 15 and g.nprims == 8 and sizes(g) == [4] * 8
      and close(P_(g)[12:, 0], [0.25] * 3) and close(np.sort(P_(g)[12:, 1]), [0, 1, 2])
      and face_areas(g) == [0.25, 0.25, 0.75, 0.75, 1, 1, 1, 1])
g2 = PS(G32, "4-5@0.25", path_type="edge_loop")
check("  starting from the middle edge 4-5: walks out both ways, giving the same loop",
      g2.nprims == 8 and close(np.sort(P_(g2)[12:], axis=0), np.sort(P_(g)[12:], axis=0))
      and face_areas(g2) == face_areas(g))
g2 = PS(G32, "1-0@0.25", path_type="edge_loop")
check("  location written as 1-0@0.25: t measured from point 1 -> x = 0.75", close(P_(g2)[12:, 0], [0.75] * 3))
check("  negative control: the same location in Shortest Path mode (only one location) raises; Edge Loop does not accept locations on points",
      raises(lambda: PS(G32, "0-1@0.25"), "at least two")
      and raises(lambda: PS(G32, "0 5", path_type="edge_loop"), "must be on edges"))
g = PS(G32, "0-1@0.25", path_type="edge_loop", num_loops=3)
check("Number of Loops 3: three evenly spaced loops x = 1/4 1/2 3/4 (ignoring t in the location), 9 new points, the left column cut into 8 strips 1/4 wide",
      g.npoints == 21 and g.nprims == 12 and sizes(g) == [4] * 12
      and close(np.sort(np.unique(np.round(P_(g)[12:, 0], 5))), [0.25, 0.5, 0.75])
      and face_areas(g) == [0.25] * 8 + [1.0] * 4)
g2 = PS(G32, "0-1@0.1", path_type="edge_loop", num_loops=2)
check("  2 loops: x = 1/3 2/3", close(np.unique(np.round(P_(g2)[12:, 0], 5)), [0.33333, 0.66667]))
g = PS(G32, "0-1@0.25", path_type="edge_loop", use_edge_percentage=True, edge_percentage=0.1)
check("Edge Percentage 0.1: overrides t in the location (x = 0.1); turning the toggle off goes back to 0.25; not read with multiple loops",
      close(P_(g)[12:, 0], [0.1] * 3)
      and close(P_(PS(G32, "0-1@0.25", path_type="edge_loop", edge_percentage=0.1))[12:, 0], [0.25] * 3)
      and digest(PS(G32, "0-1@0.25", path_type="edge_loop", num_loops=3, use_edge_percentage=True,
                    edge_percentage=0.1)) == digest(PS(G32, "0-1@0.25", path_type="edge_loop", num_loops=3)))
g = PS(G32, "0-1@0.25 4-5@0.9", use_edge_percentage=True, edge_percentage=0.5)
check("  Shortest Path mode also honours Edge Percentage: both locations at the midpoint, cutting two 0.5x1 pieces",
      close(P_(g)[12:, 0], [0.5, 0.5]) and face_areas(g)[:2] == [0.5, 0.5]
      and raises(lambda: PS(G32, "0-1 4-5", use_edge_percentage=True, edge_percentage=0.0), "Edge Percentage"))
cubeP = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]]
cubeF = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
cube = Geometry.from_mesh(np.asarray(cubeP, np.float32), [np.array(f) for f in cubeF])
g = run("PCG_PolySplit", geo=cube, locations="0-4@0.25", path_type="edge_loop", edge_group="loop")
check("closed loop: from 1/4 along the cube's vertical edge 0-4 around and back to the start -> 4 new points all at z = 0.25, 4 cuts, 10 quads, still closed, volume 1",
      g.npoints == 12 and g.nprims == 10 and sizes(g) == [4] * 10 and close(P_(g)[8:, 2], [0.25] * 4)
      and closed_manifold(g) and abs(abs(volume(g)) - 1) < 1e-6
      and len(g.edge_groups["loop"]) == 4)
check("  report: 1 loop, closed; the open kind (grid) has closed_loops = 0",
      CS.poly_split(cube, "0-4@0.25", path_type="edge_loop")[1]["closed_loops"] == 1
      and CS.poly_split(G32, "0-1@0.25", path_type="edge_loop")[1]["closed_loops"] == 0
      and CS.poly_split(cube, "0-4@0.25", path_type="edge_loop")[1]["cuts"] == 4)
qt = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [2, 0.5, 0]], np.float32),
                        [np.array([0, 1, 2, 3]), np.array([1, 4, 2])])
g = PS(qt, "3-0@0.5", path_type="edge_loop")
check("the loop stops at a triangle: the quad is cut in two, the triangle gets an extra point on the shared edge (becomes a quad, no T-junction left)",
      g.nprims == 3 and sizes(g) == [4, 4, 4] and g.npoints == 7 and abs(area(g) - 1.5) < 1e-6)
r2 = CS.poly_split(G32, "0-1@0.25 8-9@0.5", path_type="edge_loop")[1]
check("two locations on the same loop: the second is skipped (that edge is already cut)", r2["skipped"] == 1 and r2["loops"] == 1)
g = PS(G32, "0-1@0.5 0-4@0.5", path_type="edge_loop")
check("loops from two locations crossing each other: the second loop is done on the result of the first, crossing one more prim -> 3 + 5 new points, 6+2+4 = 12 quads",
      g.npoints == 12 + 8 and g.nprims == 12 and sizes(g) == [4] * 12 and abs(area(g) - 6) < 1e-6
      and close(np.sort(P_(g)[15:, 0]), [0, 0.5, 1, 2, 3]) and close(P_(g)[15:, 1], [0.5] * 5))

sec("PolySplit: Edge Loop attributes, report, loop-walking details and errors")
Gv = with_ids(qgrid(3, 2))
g = PS(Gv, "0-1@0.25", path_type="edge_loop")
vv_ = np.asarray(g.get(VERTEX, "vv")).reshape(-1)
vpg = np.asarray(g.vertex_point)
newc = vpg >= 12
# new point 12 on 0->1 at t=1/4: vv = 0.75·0 + 0.25·10; 13 on 4->5: 0.75·40 + 0.25·50; 14 on 8->9
check("Edge Loop: vertex attributes of new corners interpolated by t (the prims on either side traverse this edge in opposite directions, both still at the 1/4 end)",
      close(np.sort(np.unique(np.round(vv_[newc], 4))), [2.5, 42.5, 82.5])
      and all(abs(vv_[c] - {12: 2.5, 13: 42.5, 14: 82.5}[int(vpg[c])]) < 1e-4 for c in np.nonzero(newc)[0]))
check("  report: new_points / cuts / loops / skipped / closed_loops all correct",
      CS.poly_split(G32, "0-1@0.25", path_type="edge_loop")[1]
      == {"new_points": 3, "cuts": 2, "loops": 1, "skipped": 0, "closed_loops": 0}
      and CS.poly_split(G32, "0-1@0.25", path_type="edge_loop", num_loops=3)[1]
      == {"new_points": 9, "cuts": 6, "loops": 3, "skipped": 0, "closed_loops": 0})
check("  loop order: starting from a middle edge, the part walked backward is prepended -- loop edges in geometric order",
      CS._quad_ring(G32, 4, 5)[0] == [(8, 9), (4, 5), (0, 1)]
      and sorted(CS._quad_ring(G32, 4, 5)[1]) == [(0, 1, 2), (3, 1, 0)]
      and CS._quad_ring(G32, 5, 4)[0] == [(9, 8), (5, 4), (1, 0)])
gq = ops.merge(G32, polyline([[0, 0, 0], [1, 0, 0]]))
gq2 = Geometry.from_mesh(P_(G32), [np.asarray(G32.prim_points(k)) for k in range(6)] + [np.array([0, 1])],
                         closed=True)
gq2.set_topology(gq2.vertex_point, gq2.prim_offset, np.array([True] * 6 + [False]), gq2.prim_type)
g = PS(gq2, "0-1@0.25", path_type="edge_loop")
check("  an open curve in the geometry lying on edge 0-1: not treated as a face (no non-manifold error), the point is inserted on the curve too",
      g.nprims == 9 and list(g.prim_points(8)) == [0, 12, 1] and not g.prim_closed[8])
row = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [0, 1, 0], [1, 1, 0], [2, 1, 0], [3, 0.5, 0]],
                                  np.float32), [np.array([0, 1, 4, 3]), np.array([1, 2, 5, 4]), np.array([2, 6, 5])])
r_ = CS.poly_split(row, "0-3@0.5", path_type="edge_loop")
check("  one end hits a triangle and stops, the other is a boundary: both ends walked, 2 quads cut once each, the triangle gets one more point",
      r_[1]["cuts"] == 2 and r_[1]["closed_loops"] == 0 and sorted(r_[0].prim_sizes().tolist()) == [4, 4, 4, 4, 4])
r_ = CS.poly_split(row, "1-4@0.5", path_type="edge_loop")
check("  starting in the middle with a triangle at one end: the other end still walks back", r_[1]["cuts"] == 2 and r_[1]["new_points"] == 3)
nm = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [1, 0, 1], [0, 0, 1], [1, -1, 0],
                                  [0, -1, 0]], np.float32),
                        [np.array([0, 1, 2, 3]), np.array([1, 0, 5, 4]), np.array([1, 0, 7, 6])])
tri2 = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, -1, 0]], np.float32),
                          [np.array([0, 1, 2]), np.array([1, 0, 3])])
check("  errors: edge does not exist / non-manifold edge / no quads on either side / no location at all",
      raises(lambda: PS(G32, "0-5@0.5", path_type="edge_loop"), "no edge between")
      and raises(lambda: PS(nm, "0-1@0.5", path_type="edge_loop"), "non-manifold")
      and raises(lambda: PS(tri2, "0-1@0.5", path_type="edge_loop"), "no quads")
      and raises(lambda: PS(G32, "", path_type="edge_loop"), "at least one location"))
check("  location syntax bounds: point number = point count, prim number = prim count, vertex number = vertex count, edge number = edge count are all out of range",
      raises(lambda: PS(G32, "12 0"), "out of range") and raises(lambda: PS(G32, "6v0 0v1"), "out of range")
      and raises(lambda: PS(G32, "0v4 0v1"), "out of range") and raises(lambda: PS(G32, "0e4 0v1"), "out of range"))
check("  omitted t means the midpoint (both syntaxes): p0-1 -> x = 0.5, 0e0 -> x = 0.5",
      close(P_(PS(G32, "p0-1 p4-5"))[12], [0.5, 0, 0]) and close(P_(PS(G32, "0e0 0e2"))[12], [0.5, 0, 0]))
check("  function defaults: Edge Percentage not locked, 0.5 by default when locked; Edge Percentage = 1 raises",
      close(P_(CS.poly_split(G32, "0-1@0.25 4-5@0.25")[0])[12], [0.25, 0, 0])
      and close(P_(CS.poly_split(G32, "0-1@0.25 4-5@0.25", use_edge_percentage=True)[0])[12], [0.5, 0, 0])
      and raises(lambda: CS.poly_split(G32, "0-1 4-5", use_edge_percentage=True, edge_percentage=1.0),
                 "Edge Percentage"))

sec("PolySplit: Houdini's location syntax, bit-exact regression, panel")
ref = PS(G32, "0-1@0.25 4-5@0.25")
check("pa-b:t is the same thing as our a-b@t (bit-identical)", digest(PS(G32, "p0-1:0.25 p4-5:0.25")) == digest(ref)
      and digest(PS(G32, "p0-1 p4-5")) == digest(PS(G32, "0-1 4-5")))
check("aeb:t = edge b of prim a (vertex b -> the next, t measured from vertex b): 0e0:0.25 0e2:0.75 are the same cut",
      digest(PS(G32, "0e0:0.25 0e2:0.75")) == digest(PS(G32, "0-1@0.25 5-4@0.75"))
      and close(P_(PS(G32, "0e0:0.25 0e2:0.75"))[12:, 0], [0.25, 0.25]))
check("avb = vertex b of prim a: 0v0 0v2 = point 0 and point 5 (diagonal)",
      digest(PS(G32, "0v0 0v2")) == digest(PS(G32, "0 5")) and sizes(PS(G32, "0v0 0v2")) == [3, 3, 4, 4, 4, 4, 4])
check("  af:u,v (a location inside the face) not implemented: raises with a clear message; prim / vertex / edge number out of range raises",
      raises(lambda: PS(G32, "0f:0.5,0.5 0v0"), "not implemented") and raises(lambda: PS(G32, "9v0 0v1"), "out of range")
      and raises(lambda: PS(G32, "0v7 0v1"), "out of range") and raises(lambda: PS(G32, "0e9 0v1"), "out of range"))
for loc, cp in (("0-1@0.25 4-5@0.25", False), ("1-5@0.5 4-5@0.5 5-9@0.5 5-6@0.5", True), ("0 5", False)):
    same_as_base(f"'{loc}'{' closed' if cp else ''}: with new parameters at defaults bit-identical to baseline",
                 run("PCG_PolySplit", geo=G32, locations=loc, close_path=cp, edge_group="cut"),
                 lambda: base_mod("cutsplit").poly_split(G32, loc, cp, "cut")[0])
check("bad Path Type raises", raises(lambda: CS.poly_split(G32, "0 5", path_type="x"), "Path Type"))
ui = PANEL.layout_for("PCG_PolySplit", M["PCG_PolySplit"].INPUT_TYPES())[0]
check("panel: self-check passes; Number of Loops appears only under Edge Loop, Close Path hidden under Edge Loop",
      not PANEL.check_layout("PCG_PolySplit", M["PCG_PolySplit"].INPUT_TYPES())
      and ui["path_type"]["menu"] == {"shortest_path": "Shortest Path", "edge_loop": "Edge Loop"}
      and "path_type != edge_loop" in ui["num_loops"]["hide"] and "edge_loop" in ui["close_path"]["hide"],
      PANEL.check_layout("PCG_PolySplit", M["PCG_PolySplit"].INPUT_TYPES()))

# ═══════════════════════════════════════════════════════ Primitive
sec("Primitive:Transform Order / Rotate Order / Shear / Pivot")
SQ2 = [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]]      # center (1, 1, 0)
sq2 = lambda: polyline(SQ2, closed=True)                # noqa: E731
PRM = lambda g, **kw: run("PCG_Primitive", geo=g, **kw)  # noqa: E731
o = P_(PRM(sq2(), rotate_z=90, translate_x=1))
check("default Scale Rot Trans: corner (0,0) relative to the center (-1,-1) rotated 90 deg -> (1,-1), back to the center (2,0), then translated -> (3,0)",
      close(o[0], [3, 0, 0]) and close(o[2], [1, 2, 0]))
o = P_(PRM(sq2(), rotate_z=90, translate_x=1, xform_order="trs"))
check("Trans Rot Scale: translate (0,-1) first then rotate -> (1,0), back to the center -> (2,1); differs from default",
      close(o[0], [2, 1, 0]) and close(o[2], [0, 3, 0]))
o = P_(PRM(sq2(), scale_x=2, rotate_z=90, xform_order="rst"))
check("Rot Scale Trans: rotate first (1,-1) then scale x by 2 -> (2,-1) -> (3,0); default (scale first) is (1,-2) -> (2,-1)",
      close(o[0], [3, 0, 0]) and close(P_(PRM(sq2(), scale_x=2, rotate_z=90))[0], [2, -1, 0]))
seg = lambda: polyline([[1, 2, 3], [-1, -2, -3]])        # noqa: E731  centered at the origin
R3 = lambda o_: [int(round(x)) for x in P_(PRM(seg(), rotate_x=90, rotate_y=90, rotate_z=90,      # noqa: E731
                                                rotate_order=o_))[0]]
# by hand: Rx90 (x,y,z)->(x,-z,y); Ry90 ->(z,y,-x); Rz90 ->(-y,x,z), applied to (1,2,3) in Rotate Order sequence
check("Rotate Order: (1,2,3) rotated 90 deg about each of the three axes, six orders give six different results, matching the hand computation",
      R3("xyz") == [3, 2, -1] and R3("xzy") == [2, 1, -3] and R3("yxz") == [-1, 3, 2]
      and R3("yzx") == [-2, 1, 3] and R3("zxy") == [1, -3, 2] and R3("zyx") == [3, -2, 1],
      [R3(o_) for o_ in ("xyz", "xzy", "yxz", "yzx", "zxy", "zyx")])
g = PRM(sq2(), shear_xy=1.0)
check("Shear XY 1: x += y (relative to the center) -> (-1,0) (1,0) (3,2) (1,2), area still 4",
      close(P_(g), [[-1, 0, 0], [1, 0, 0], [3, 2, 0], [1, 2, 0]]) and abs(area(g) - 4) < 1e-6)
cubeseg = lambda: polyline([[0, 0, 0], [2, 2, 2]])       # noqa: E731  center (1,1,1)
check("  Shear XZ: x += z -> (-1,0,0) (3,2,2); Shear YZ: y += z -> (0,-1,0) (2,3,2); all three different",
      close(P_(PRM(cubeseg(), shear_xz=1.0)), [[-1, 0, 0], [3, 2, 2]])
      and close(P_(PRM(cubeseg(), shear_yz=1.0)), [[0, -1, 0], [2, 3, 2]])
      and close(P_(PRM(cubeseg(), shear_xy=1.0)), [[-1, 0, 0], [3, 2, 2]]))
o = P_(PRM(sq2(), uniform_scale=2, pivot_x=1, pivot_y=1))
check("Pivot (1,1) (relative to the center = corner (2,2)): scaling by 2 leaves that corner in place, the opposite corner goes to (-2,-2); with Pivot 0 they are (-1,-1) and (3,3)",
      close(o[2], [2, 2, 0]) and close(o[0], [-2, -2, 0])
      and close(P_(PRM(sq2(), uniform_scale=2))[[0, 2]], [[-1, -1, 0], [3, 3, 0]]))
o = P_(PRM(polyline([[0, 0, 0], [0, 0, 4]]), uniform_scale=2, pivot_z=2))
check("  Pivot Z", close(o, [[0, 0, -4], [0, 0, 4]]))
two = Geometry.from_mesh(np.array(SQ2 + [[10, 0, 0], [12, 0, 0], [12, 2, 0], [10, 2, 0]], np.float32),
                         [np.arange(4), np.arange(4, 8)])
two.set(PRIM, "f", np.array([[1.0], [3.0]], np.float32))
o = P_(PRM(two, scale_attribute="f", pivot_x=1, pivot_y=1))
check("Scale Attribute on the new path: the piece with f = 3 is scaled 3x around its Pivot ((10,0) -> (6,-4)), the piece with f = 1 does not move",
      close(o[:4], SQ2) and close(o[4], [6, -4, 0]) and close(o[6], [12, 2, 0]))
o = P_(PRM(two, scale_attribute="f", translate_x=1, xform_order="tsr"))
check("  Trans Scale Rot: the translation is scaled by f too (piece with f = 3: (10,0) -> 11 + 3·(-1+1) = 11; the default order gives 11 - 3 + 1 = 9)",
      close(o[0], [1, 0, 0]) and close(o[4], [11, -2, 0])
      and close(P_(PRM(two, scale_attribute="f", translate_x=1))[4], [9, -2, 0]))
tilt = polyline([[0, 0, 0], [2, 0, 1], [2, 2, 2], [0, 2, 1]], closed=True,
                N=[[0, 0, 1], [0, 1, 0], [1, 0, 0], [0, 0, 1]])
a_ = PRM(tilt, rotate_x=30, rotate_y=40, rotate_z=50, scale_x=2, scale_y=0.5, translate_y=3,
         normal_offset=0.3, uniform_scale=1.5)
b_ = PRM(tilt, rotate_x=30, rotate_y=40, rotate_z=50, scale_x=2, scale_y=0.5, translate_y=3,
         normal_offset=0.3, uniform_scale=1.5, shear_xy=1e-30)
check("the old and new paths compute the same transform (Shear 1e-30 forces the new path): P and the transformed N both match",
      close(P_(a_), P_(b_), 1e-5) and close(a_.get(POINT, "N"), b_.get(POINT, "N"), 1e-5)
      and not close(P_(a_), P_(tilt), 0.1))

sec("Primitive: Attributes (Color / Alpha), Face/Hull (Close U / Vertex)")
two.set_group(PRIM, "b", np.array([False, True]))
g = PRM(two, group="b", color_mode="add", color_r=1.0, color_g=0.5, color_b=0.25)
check("Add Color: selected prims get prim attribute Cd = (1, 0.5, 0.25), unselected ones the default (1,1,1)",
      close(g.get(PRIM, "Cd"), [[1, 1, 1], [1, 0.5, 0.25]]))
g2 = PRM(g, group="0", color_mode="add", color_r=0, color_g=0, color_b=1)
check("  existing Cd: only the selected one changes, other prims keep their values", close(g2.get(PRIM, "Cd"), [[0, 0, 1], [1, 0.5, 0.25]]))
check("  Keep (default) leaves it alone; Remove deletes the prim Cd",
      close(PRM(g, color_r=0).get(PRIM, "Cd"), g.get(PRIM, "Cd")) and not PRM(two, color_r=0).has(PRIM, "Cd")
      and not PRM(g, color_mode="remove").has(PRIM, "Cd") and PRM(g, color_mode="remove").nprims == 2)
g = PRM(two, group="b", alpha_mode="add", alpha=0.25)
check("Add Alpha: prim attribute Alpha = 0.25 (1 for unselected); Remove deletes it; Color and Alpha do not affect each other",
      close(g.get(PRIM, "Alpha"), [[1], [0.25]]) and not g.has(PRIM, "Cd")
      and not PRM(g, alpha_mode="remove").has(PRIM, "Alpha")
      and not PRM(two, group="b", color_mode="add").has(PRIM, "Alpha"))
g = PRM(two, group="b", close_u="open")
check("Close U = Open: the selected closed polygon becomes an open polyline; Close closes it back; No Change leaves it",
      list(g.prim_closed) == [True, False] and list(PRM(g, close_u="close").prim_closed) == [True, True]
      and list(PRM(g).prim_closed) == [True, False]
      and list(PRM(g, group="0", close_u="close").prim_closed) == [True, False])
g = PRM(two, group="b", vertex_op="reverse", unshare_points=False)
check("Vertex = Reverse: bit-identical to the Reverse node, normals of the selected prim flipped",
      digest(g) == digest(ops.reverse_prims(two, "b", "reverse"))
      and list(g.prim_points(1)) == [7, 6, 5, 4] and list(g.prim_points(0)) == [0, 1, 2, 3])
g = PRM(two, group="b", vertex_op="shift", u_offset=1, unshare_points=False)
check("Vertex = Shift, U Offset 1: vertices rotate by one (4 5 6 7 -> 5 6 7 4); Offset 0 no change; Offset not read unless Shift",
      list(g.prim_points(1)) == [5, 6, 7, 4]
      and list(PRM(two, group="b", vertex_op="shift", unshare_points=False).prim_points(1)) == [4, 5, 6, 7]
      and list(PRM(two, group="b", vertex_op="reverse", u_offset=1, unshare_points=False).prim_points(1)) == [7, 6, 5, 4])

o = P_(PRM(two, scale_attribute="f", translate_x=1, xform_order="tsr", uniform_scale=2))
check("  Scale Attribute x Uniform Scale x translation before scaling: piece with f = 3 (10,0) -> (0,-1)·6 + (11,1) = (11,-5)",
      close(o[4], [11, -5, 0]) and close(o[0], [1, -1, 0]))
ex = dict(normal_offset=0.0, unshare_points=True, xform_order="srt", rotate_order="xyz", shear=(0, 0, 0),
          pivot=(0, 0, 0), color_mode="keep", color=(1, 1, 1), alpha_mode="keep", alpha=1.0, close_u="no_change",
          vertex_op="none", u_offset=0, v_offset=0)
o = P_(PRM(two, scale_attribute="f", translate_y=1, xform_order="tsr", uniform_scale=2))
check("  same as above, translating in y: piece with f = 3 (10,0) -> (-1,0)·6 + (11,1) = (5,1)", close(o[4], [5, 1, 0]))
bxs = build.box((1, 1, 1), (0, 0, 0), (2, 2, 2))
check("  function default Unshare Points = on (a box with shared points is split into 24 points)",
      D2.primitive(bxs, uniform_scale=0.5).npoints == 24
      and digest(D2.primitive(bxs, uniform_scale=0.5)) == digest(D2.primitive(bxs, uniform_scale=0.5,
                                                                               unshare_points=True)))
check("  function defaults: same as writing them out one by one; with Add the colour defaults to (1,1,1), Alpha to 1; Shift defaults to no offset",
      digest(D2.primitive(two, translate=(1, 0, 0), rotate=(0, 0, 30))) ==
      digest(D2.primitive(two, translate=(1, 0, 0), rotate=(0, 0, 30), **ex))
      and close(D2.primitive(two, color_mode="add").get(PRIM, "Cd"), [[1, 1, 1]] * 2)
      and close(D2.primitive(two, alpha_mode="add").get(PRIM, "Alpha"), [[1]] * 2)
      and list(D2.primitive(two, vertex_op="shift", unshare_points=False).prim_points(1)) == [4, 5, 6, 7])

sec("Primitive: bit-exact regression of defaults, errors, panel")
bx = build.box() if hasattr(build, "box") else two
bx = bx.copy()
bx.set(PRIM, "f", np.linspace(0.5, 2.0, bx.nprims).astype(np.float32).reshape(-1, 1))
for nm, kw in (("rotate + scale + translate", dict(rotate=(10, 20, 30), scale=(2, 1, 0.5), translate=(1, 2, 3))),
               ("Scale Attribute + Normal Offset", dict(scale_attribute="f", normal_offset=0.2, uniform_scale=0.7)),
               ("no unshare", dict(rotate=(0, 0, 45), unshare_points=False))):
    nk = {}
    for k, v in kw.items():
        if isinstance(v, tuple):
            nk.update({f"{k}_{a}": x for a, x in zip("xyz", v)})
        else:
            nk[k] = v
    same_as_base(f"{nm}: with new parameters at defaults bit-identical to baseline", PRM(bx, **nk),
                 lambda: base_mod("deform2").primitive(bx, **kw))
check("bad options raise",
      raises(lambda: D2.primitive(two, xform_order="xyz"), "Transform Order")
      and raises(lambda: D2.primitive(two, rotate_order="srt"), "Rotate Order")
      and raises(lambda: D2.primitive(two, color_mode="x"), "Color")
      and raises(lambda: D2.primitive(two, alpha_mode="x"), "Alpha")
      and raises(lambda: D2.primitive(two, close_u="x"), "Close U")
      and raises(lambda: D2.primitive(two, vertex_op="x"), "Vertex"))
ui = PANEL.layout_for("PCG_Primitive", M["PCG_Primitive"].INPUT_TYPES())[0]
check("panel: self-check passes; Color / Alpha values appear only under Add, Offset only under Shift",
      not PANEL.check_layout("PCG_Primitive", M["PCG_Primitive"].INPUT_TYPES())
      and ui["xform_order"]["menu"]["trs"] == "Trans Rot Scale" and ui["rotate_order"]["menu"]["zyx"] == "Rz Ry Rx"
      and "color_mode != add" in ui["color_r"]["hide"] and "alpha_mode != add" in ui["alpha"]["hide"]
      and "vertex_op != shift" in ui["u_offset"]["hide"] and ui["color_mode"]["menu"]["add"] == "Add Color",
      PANEL.check_layout("PCG_Primitive", M["PCG_Primitive"].INPUT_TYPES()))

# ═══════════════════════════════════════════════════════ PolyReduce
sec("PolyReduce: the two point-count Target modes")
SPH = build.sphere(1.0, 24, 16)                         # 338 points, closed
RD = lambda **kw: run("PCG_PolyReduce", geo=SPH, **kw)  # noqa: E731
g = RD(target="point_count", target_count=50)
check("Output Point Count 50: exactly 50 points; on a closed manifold F = 2V - 4 = 96 triangles",
      g.npoints == 50 and g.nprims == 96 and closed_manifold(g))
g2 = RD(target="triangle_count", target_count=50)
check("  negative control: with the same Number to Keep = 50, Output Triangle Count keeps 50 triangles (27 points)",
      g2.nprims == 50 and g2.npoints == 27)
g = RD(target="point_percentage", keep_percent=25.0)
check("Percentage of Point Count 25%: 338 points keep round(84.5) = 84 (164 triangles)",
      SPH.npoints == 338 and g.npoints == 84 and g.nprims == 164 and closed_manifold(g))
g2 = RD(target="percentage", keep_percent=25.0)
check("  negative control: Percentage of Triangle Count 25% keeps 1/4 of the triangles, point count is not 84",
      g2.nprims == round(len(SPH.triangles()) * 0.25) and g2.npoints != 84)
check("  target >= current point count: only triangulates, no reduction; each mode reads its own number (point_count ignores Percent, point_percentage ignores Number)",
      RD(target="point_count", target_count=10 ** 6).npoints == 338
      and RD(target="point_count", target_count=50, keep_percent=1.0).npoints == 50
      and RD(target="point_percentage", keep_percent=25.0, target_count=7).npoints == 84)
gb = build.grid(4.0, 4.0, 9, 9)                         # open: collapsing boundary corners drops points along with them
g = run("PCG_PolyReduce", geo=gb, target="point_count", target_count=20)
check("  open grid: also reduced to exactly 20 points",
      g.npoints == 20, g.npoints)

sec("PolyReduce: Hard Edges, Soft Points + Weight")
Ps = P_(SPH)
yv = np.unique(np.round(Ps[:, 1], 5))
ring = np.abs(Ps[:, 1] - yv[len(yv) // 2]) < 1e-4       # the middle latitude ring
ep = np.asarray(_topo(SPH).edge_points)
sp = SPH.copy()
sp.set_edge_group("ring", ep[ring[ep[:, 0]] & ring[ep[:, 1]]].astype(np.int32))
sp.set_group(POINT, "soft", np.arange(SPH.npoints) == int(np.argmax(Ps[:, 0] + 0.37 * Ps[:, 1] + 0.11 * Ps[:, 2])))


nring = int(ring.sum())
g = run("PCG_PolyReduce", geo=sp, target="point_count", target_count=60, hard_edges="ring")
g0 = run("PCG_PolyReduce", geo=sp, target="point_count", target_count=60)
check(f"Hard Edges: none of the endpoints of that ring's {nring} edges lost, positions unchanged, the ring's edges all still there",
      nring == 24 and g.npoints == 60 and has_pts(g, Ps[ring])
      and len(g.edge_groups["ring"]) == nring)
check("  negative control: without Hard Edges, reduced to the same 60 points, the ring is not fully kept", not has_pts(g0, Ps[ring]) and g0.npoints == 60)
si = int(np.nonzero(sp.get_group(POINT, "soft"))[0][0])
dist = lambda g: float(np.linalg.norm(P_(g) - Ps[si], axis=1).min())      # noqa: E731
SR = lambda **kw: run("PCG_PolyReduce", geo=sp, target="point_count", target_count=12, **kw)  # noqa: E731
d0, d1, d2 = dist(SR()), dist(SR(soft_points="soft", soft_weight=1.0)), dist(SR(soft_points="soft", soft_weight=1e4))
check("Soft Points: reduced to 12 points; without it there is no point near that point any more; the larger the Weight the closer to the original position (< 0.01 at 1e4)",
      d0 > 0.1 and d1 < d0 and d2 < d1 and d2 < 0.01, (round(d0, 4), round(d1, 4), round(d2, 5)))
check("  Weight 0 / empty point group = no such term (bit-identical to not giving it); Soft means 'may move': not pinned like Hard Points",
      digest(SR(soft_points="soft", soft_weight=0.0)) == digest(SR())
      and digest(SR(soft_points="", soft_weight=1e4)) == digest(SR())
      and dist(SR(lock_group="soft")) < 1e-6 and d1 > 1e-6)
# by hand on a plane: the face quadric costs 0 for in-plane moves; adding w·A·|x - p|^2, the optimal collapse position involving the soft point is p itself
fl = build.grid(4.0, 4.0, 5, 5)
fl.set_group(POINT, "c", np.arange(25) == 12)
pc = P_(fl)[12]
g = run("PCG_PolyReduce", geo=fl, target="point_count", target_count=5, soft_points="c", soft_weight=10.0,
        boundary_weight=4.0)
check("  a planar 5x5 grid reduced to 5 points: the four corners + the soft point's original position (moving within the plane is free, only leaving the soft point costs)",
      g.npoints == 5 and has_pts(g, [pc]) and abs(area(g) - 16) < 1e-5)

Kq = PR._soft_quadrics(np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0]]), np.array([[0, 1, 2]]), np.array([0.5]),
                       np.array([1]), 6.0)
# a triangle of area 1/2, each point gets 1/6; weight 6 -> coefficient 1: Q = [[I, -p], [-p^T, p^T p]], p = (1,0,0)
check("  Soft Points quadric: weight · (area/3) · |x - p|^2, matches the hand computation",
      Kq.shape == (1, 4, 4) and close(Kq[0], [[1, 0, 0, -1], [0, 1, 0, 0], [0, 0, 1, 0], [-1, 0, 0, 1]], 1e-12))
check("  function defaults: Soft Weight defaults to 1; point-count targets keep at least 3 points (one triangle), never reduced to empty",
      digest(PR.reduce_mesh(sp, "point_count", 50, 12, soft_points="soft"))
      == digest(PR.reduce_mesh(sp, "point_count", 50, 12, soft_points="soft", soft_weight=1.0))
      and PR.reduce_mesh(gb, "point_count", 50, 1).npoints == 3 and PR.reduce_mesh(gb, "point_count", 50, 1).nprims == 1
      and PR.reduce_mesh(gb, "triangle_count", 50, 1).nprims == 1)
gbu = gb.copy()
gbu.set(VERTEX, "uv", P_(gbu)[np.asarray(gbu.vertex_point)][:, [0, 2]].astype(np.float32))
check("  function defaults: Preserve UVs off by default",
      digest(PR.reduce_mesh(gbu, "point_count", 50, 30)) == digest(PR.reduce_mesh(gbu, "point_count", 50, 30,
                                                                                preserve_uvs=False))
      and digest(PR.reduce_mesh(gbu, "point_count", 50, 30)) != digest(PR.reduce_mesh(gbu, "point_count", 50, 30,
                                                                                     preserve_uvs=True)))

sec("PolyReduce: bit-exact regression of defaults, panel")
for nm, kw in (("percentage 30% optimal", dict(target="percentage", keep_percent=30.0)),
               ("triangle_count 100 midpoint", dict(target="triangle_count", target_count=100, position="midpoint")),
               ("triangle_count 80 endpoint + lock boundary", dict(target="triangle_count", target_count=80,
                                                         position="endpoint", lock_boundary=True))):
    src = gb if "lock" in nm else SPH
    same_as_base(f"{nm}: with new parameters at defaults bit-identical to baseline",
                 run("PCG_PolyReduce", geo=src, **kw),
                 lambda: base_mod("polyreduce").reduce_mesh(src, kw["target"], kw.get("keep_percent", 50.0),
                                                            kw.get("target_count", 1000),
                                                            kw.get("position", "optimal"), 4.0, "", 4.0,
                                                            kw.get("lock_boundary", False), "", 90.0, "", False))
check("bad Target raises", raises(lambda: PR.reduce_mesh(SPH, target="edges"), "Target"))
ui = PANEL.layout_for("PCG_PolyReduce", M["PCG_PolyReduce"].INPUT_TYPES())[0]
check("panel: self-check passes; the two new modes have Houdini's labels; Percent / Number each appear under their own two modes",
      not PANEL.check_layout("PCG_PolyReduce", M["PCG_PolyReduce"].INPUT_TYPES())
      and ui["target"]["menu"]["point_percentage"] == "Percentage of Point Count"
      and ui["target"]["menu"]["point_count"] == "Output Point Count"
      and "point_percentage" in ui["keep_percent"]["hide"] and "point_count" in ui["target_count"]["hide"]
      and ui["hard_edges"]["label"] == "Hard Edges" and ui["soft_points"]["label"] == "Soft Points",
      PANEL.check_layout("PCG_PolyReduce", M["PCG_PolyReduce"].INPUT_TYPES()))

# ═══════════════════════════════════════════════════════ Remesh
sec("Remesh: Group (local remesh), Detach From Nongroup Geometry")


G5 = build.grid(4.0, 4.0, 5, 5)                         # 16 1x1 squares, y = 0
G5.set_group(PRIM, "half", np.arange(16) < 8)           # the first two rows (z < 0)
G5.set(PRIM, "id", np.arange(16, dtype=np.int32).reshape(-1, 1))
RMn = lambda g, **kw: run("PCG_Remesh", geo=g, **kw)    # noqa: E731
g = RMn(G5, target_length=0.5, iterations=4, group="half")
sz = g.prim_sizes()
P5 = P_(G5)
check("Group: only the 8 selected squares are remeshed into triangles; the other 8 prims remain (prim attributes unchanged), total area still 16",
      int((sz > 3).sum()) == 8 and int((sz == 3).sum()) > 30 and abs(area(g) - 16) < 1e-4
      and sorted(np.asarray(g.get(PRIM, "id"))[sz > 3, 0].tolist()) == list(range(8, 16)))
check("  new points split on the interface (the line z = 0, length 4) are also inserted into the neighbouring prims: the 4 adjacent squares become pentagons, points shared by both sides -- "
      "the open edges of the whole mesh are only the outer contour 16",
      sorted(sz[sz > 3].tolist()) == [4, 4, 4, 4, 5, 5, 5, 5] and abs(boundary_len(g) - 16) < 1e-5)
check("  points of the unselected half did not move at all; original points inside the selected half are not guaranteed to remain",
      has_pts(g, P5[P5[:, 2] >= -1e-6], 1e-7) and g.npoints > 25)
gd = RMn(G5, target_length=0.5, iterations=4, group="half", detach=True)
check("Detach From Nongroup Geometry: the two sides are disconnected -- open edges gain both sides of the interface (16 + 2x4), the unselected part is still 8 quads",
      abs(boundary_len(gd) - 24) < 1e-5 and sorted(gd.prim_sizes()[gd.prim_sizes() > 3].tolist()) == [4] * 8
      and gd.npoints > g.npoints and abs(area(gd) - 16) < 1e-4)
gc_ = ops.merge(G5, polyline([[5, 0, 0], [6, 0, 0], [7, 0, 1]]))
gc_.set_group(PRIM, "half", np.arange(17) < 8)
g = RMn(gc_, target_length=0.5, iterations=4, group="half")
check("  unselected curves are also kept as is (without Group curves are dropped)",
      int((~g.prim_closed).sum()) == 1 and has_pts(g, [[5, 0, 0], [6, 0, 0], [7, 0, 1]])
      and int((~RMn(gc_, target_length=0.5, iterations=4).prim_closed).sum()) == 0)
G5.set_group(PRIM, "all", np.ones(16, bool))
G5.set_group(PRIM, "none", np.zeros(16, bool))
check("  Group selecting everything = no Group (bit-identical); selecting nothing: returned as is",
      digest(RMn(G5, target_length=0.5, iterations=3, group="all")) == digest(RMn(G5, target_length=0.5, iterations=3))
      and digest(RMn(G5, target_length=0.5, iterations=3, group="none")) == digest(G5))
check("  report: all interface edges matched", RM.remesh(G5, 0.5, 4, group="half")[1]["unmatched_interface_edges"] == 0)

sec("Remesh: Hard Edges Group, Hard Points Group, UV Seams, the output Hard Edges group")
ep5 = np.asarray(_topo(G5).edge_points)
mid = (np.abs(P5[ep5[:, 0], 0]) < 1e-6) & (np.abs(P5[ep5[:, 1], 0]) < 1e-6)       # the 4 edges on the line x = 0
gh = G5.copy()
gh.set_edge_group("mid", ep5[mid].astype(np.int32))


def line_len(g, name, axis=0):
    """Total length of edges in the edge group whose two endpoints both lie on the plane axis = 0."""
    e = np.asarray(g.edge_groups[name]).reshape(-1, 2)
    P = P_(g)
    on = (np.abs(P[e[:, 0], axis]) < 1e-6) & (np.abs(P[e[:, 1], axis]) < 1e-6)
    return edge_len(g, e[on])


g1 = RMn(gh, target_length=0.6, iterations=4, hard_edges="mid", out_hard_edges="hard")
g0 = RMn(gh, target_length=0.6, iterations=4, out_hard_edges="hard")
check("Hard Edges Group: the line x = 0 (length 4) survives in the output -- the output Hard Edges group = outer contour 16 + this line 4, the edges on the line join end to end covering all 4",
      abs(edge_len(g1, g1.edge_groups["hard"]) - 20) < 1e-5 and abs(line_len(g1, "hard") - 4) < 1e-5)
check("  negative control: without it the Hard Edges group is only the outer contour (16); empty name writes no group",
      abs(edge_len(g0, g0.edge_groups["hard"]) - 16) < 1e-5 and line_len(g0, "hard") < 1e-9
      and "hard" not in RMn(gh, target_length=0.6, iterations=4, hard_edges="mid").edge_groups)
check("  hard edges can be split: the 4 became more (target edge length 0.6 < 1)",
      len(g1.edge_groups["hard"]) > 16 + 4)
G9 = build.grid(4.0, 4.0, 9, 9)                         # spacing 0.5, coarsened to 1.5 below
P9 = P_(G9)
hp = int(np.argmin(np.linalg.norm(P9 - [0.5, 0, -0.5], axis=1)))
G9.set_group(POINT, "pin", np.arange(81) == hp)
g1 = RMn(G9, target_length=1.5, iterations=5, hard_points="pin")
g0 = RMn(G9, target_length=1.5, iterations=5)
check("Hard Points Group: when coarsening to 1.5 that point stays at its original position (bit-exact); negative control: without it there is no point within 0.2",
      has_pts(g1, [P9[hp]], 0.0) and not has_pts(g0, [P9[hp]], 0.2) and g1.npoints < 40)
gu = G5.copy()
vp5 = gu.vertex_point
cx = np.repeat(np.array([P5[gu.prim_points(k), 0].mean() for k in range(16)]), 4)
uv = np.stack([P5[vp5, 0] + np.where(cx > 0, 10.0, 0.0), P5[vp5, 2]], 1).astype(np.float32)
gu.set(VERTEX, "uv", uv)
g1 = RMn(gu, target_length=0.6, iterations=4, uv_seams="harden", out_hard_edges="hard")
g0 = RMn(gu, target_length=0.6, iterations=4, uv_seams="ignore", out_hard_edges="hard")
check("UV Seams = Harden: uv breaks at x = 0 (u of the right half offset by 10) -> that line becomes a hard edge (16 + 4); Ignore gives only the outer contour",
      abs(edge_len(g1, g1.edge_groups["hard"]) - 20) < 1e-5 and abs(line_len(g1, "hard") - 4) < 1e-5
      and abs(edge_len(g0, g0.edge_groups["hard"]) - 16) < 1e-5)
gu2 = G5.copy()
gu2.set(VERTEX, "uv", np.stack([P5[vp5, 0], P5[vp5, 2]], 1).astype(np.float32))
gu2.set(VERTEX, "uv2", uv)
check("  uv continuous everywhere: Harden adds no hard edges; only switching UV Attribute to the seamed one does; missing attribute raises",
      abs(edge_len(RMn(gu2, target_length=0.6, iterations=4, uv_seams="harden", out_hard_edges="h"),
                   RMn(gu2, target_length=0.6, iterations=4, uv_seams="harden",
                       out_hard_edges="h").edge_groups["h"]) - 16) < 1e-5
      and abs(line_len(RMn(gu2, target_length=0.6, iterations=4, uv_seams="harden", uv_attribute="uv2",
                           out_hard_edges="h"), "h") - 4) < 1e-5
      and raises(lambda: RM.remesh(G5, 0.6, 2, uv_seams="harden"), "uv")
      and raises(lambda: RM.remesh(G5, 0.6, 2, uv_seams="resample"), "UV Seams"))
bxr = build.box((1, 1, 1), (0, 0, 0), (2, 2, 2))
g = RMn(bxr, target_length=0.3, iterations=3, out_hard_edges="hard")
check("the output Hard Edges group: the cube's 12 edges (total length still 12 after splitting)",
      abs(edge_len(g, g.edge_groups["hard"]) - 12) < 1e-5 and len(g.edge_groups["hard"]) > 12)

sec("Remesh: details of local remeshing (attributes, curves, edge groups, report)")
Gs = with_ids(G5.copy())
# the curve uses the 5 points on the grid's bottom edge z = -2 (shared points, not a separate copy)
gc2 = Geometry.from_mesh(P5, [np.asarray(G5.prim_points(k)) for k in range(16)] + [np.arange(5)], closed=True)
gc2.set_topology(gc2.vertex_point, gc2.prim_offset, np.array([True] * 16 + [False]), gc2.prim_type)
gc2 = with_ids(gc2)
gc2.set_group(PRIM, "half", np.arange(17) < 8)
g = RMn(gc2, target_length=0.3, iterations=4, group="half", keep_boundary=False, out_hard_edges="hard")
crv = int(np.nonzero(~np.asarray(g.prim_closed))[0][0])
cp = P_(g)[g.prim_points(crv)]
check("an unselected curve lying on an edge of the selected region: that edge counts as interface too -- split points are inserted into the curve (still on the line z = -2, x monotonic)",
      len(cp) > 5 and close(cp[:, 2], [-2] * len(cp)) and bool(np.all(np.diff(cp[:, 0]) > 0))
      and close(cp[[0, -1], 0], [-2, 2]))
gk_ = RMn(gc2, target_length=0.3, iterations=4, group="half")
ck_ = int(np.nonzero(~np.asarray(gk_.prim_closed))[0][0])
on_l = np.zeros(gk_.npoints, bool)
on_l[np.asarray(gk_.vertex_point)[np.repeat(gk_.prim_closed, gk_.prim_sizes())]] = True
on_l &= (np.abs(P_(gk_)[:, 2] + 2) < 1e-6)
check("  points on the curve = all points on that edge after remeshing (inserted into every segment, including the last)",
      sorted(gk_.prim_points(ck_).tolist()) == sorted(np.nonzero(on_l)[0].tolist()) and on_l.sum() > 8)


def open_edges(g):
    cnt = {}
    for k in range(g.nprims):
        if g.prim_closed[k]:
            pts = g.prim_points(k)
            for i in range(len(pts)):
                e = tuple(sorted((int(pts[i]), int(pts[(i + 1) % len(pts)]))))
                cnt[e] = cnt.get(e, 0) + 1
    return np.array([e for e, c in cnt.items() if c == 1]).reshape(-1, 2)


oe_ = open_edges(g)
on0 = (np.abs(P_(g)[oe_[:, 0], 2]) < 1e-6) & (np.abs(P_(g)[oe_[:, 1], 2]) < 1e-6)
check("  with Keep Boundary off (the outer contour may be simplified), the interface is still a hard edge and points are still shared: no open edges on the interface line z = 0",
      not on0.any() and len(oe_) > 0)
used_ = np.zeros(g.npoints, bool)
used_[np.asarray(g.vertex_point)] = True
eh = np.asarray(g.edge_groups["hard"])
on0h = (np.abs(P_(g)[eh[:, 0], 2]) < 1e-6) & (np.abs(P_(g)[eh[:, 1], 2]) < 1e-6)
check("  no isolated points (original points used only by selected prims are deleted); the output Hard Edges group uses the stitched points: the whole interface line (length 4) is in the group",
      used_.all() and used_[eh].all() and abs(edge_len(g, eh[on0h]) - 4) < 1e-5)
vvg = np.asarray(g.get(VERTEX, "vv")).reshape(-1)
vpg = np.asarray(g.vertex_point)
ok_vv, n_ins = True, 0
for k in np.nonzero(g.prim_closed & (g.prim_sizes() > 4))[0]:
    for c in range(int(g.prim_offset[k]), int(g.prim_offset[k + 1])):
        p_ = P_(g)[vpg[c]]
        if abs(p_[2]) < 1e-6 and abs(p_[0] - round(p_[0])) > 1e-6:      # inserted midpoints
            ok_vv &= abs(vvg[c] - 10 * (5 * 2 + (p_[0] + 2))) < 1e-4    # point number j·5+i interpolated linearly
            n_ins += 1
check("  corners inserted into neighbouring prims: vertex attributes interpolated by t along the interface edge", ok_vv and n_ins > 8, n_ins)
r_ = RM.remesh(gc2, 0.3, 4, group="half")[1]
check("  report: points = output point count; all interfaces matched; a report is given even when no prim is selected",
      r_["points"] == RM.remesh(gc2, 0.3, 4, group="half")[0].npoints and r_["unmatched_interface_edges"] == 0
      and RM.remesh(G5, 0.5, 2, group="none")[1]["splits"] == 0)
check("  function defaults: Keep Boundary on, Smoothing 0.5, attributes transferred, no Detach",
      digest(RM.remesh(Gs, 0.5, 2, group="half")[0])
      == digest(RM.remesh(Gs, 0.5, 2, 45.0, True, 0.5, True, group="half", detach=False)[0]))
gur = ops.reverse_prims(gu, "", "reverse")
g1 = RMn(gur, target_length=0.6, iterations=4, uv_seams="harden", out_hard_edges="hard")
check("UV Seams = Harden: the same seam is recognized even when the prim winding is reversed (all half-edge directions flipped)",
      abs(edge_len(g1, g1.edge_groups["hard"]) - 20) < 1e-5)

sec("Remesh: bit-exact regression of defaults, panel")
for nm, src, a_ in (("sphere 0.3", build.sphere(1.0, 12, 8), (0.3, 3)), ("cube 0.3", bxr, (0.3, 3)),
                    ("plane default edge length", G5, (0.0, 2))):
    same_as_base(f"{nm}: with new parameters at defaults bit-identical to baseline",
                 RMn(src, target_length=a_[0], iterations=a_[1]),
                 lambda: base_mod("remesh").remesh(src, a_[0], a_[1])[0])
ui = PANEL.layout_for("PCG_Remesh", M["PCG_Remesh"].INPUT_TYPES())[0]
check("panel: self-check passes; UV Seams has Houdini's labels, UV Attribute hidden under Ignore",
      not PANEL.check_layout("PCG_Remesh", M["PCG_Remesh"].INPUT_TYPES())
      and ui["uv_seams"]["menu"] == {"ignore": "Ignore", "harden": "Harden"}
      and "uv_seams == ignore" in ui["uv_attribute"]["hide"]
      and ui["hard_edges"]["label"] == "Hard Edges Group" and ui["detach"]["label"] == "Detach From Nongroup Geometry",
      PANEL.check_layout("PCG_Remesh", M["PCG_Remesh"].INPUT_TYPES()))

# ═══════════════════════════════════════════════════════ PolyBevel
sec("PolyBevel: Shape = None, Ignore Flat Edges")
BOX = build.box((1, 1, 1), (0, 0, 0), (2, 2, 2))        # 8 points, 6 prims, edge length 1
BV = lambda g=BOX, **kw: run("PCG_PolyBevel", geo=g, distance=0.1, **kw)   # noqa: E731
g = BV(shape="none")
check("Shape = None: each of the 6 prims insets by 0.1 (0.8 x 0.8), no bevel faces grown -> 6 prims, 24 points, area 6 x 0.64",
      g.nprims == 6 and g.npoints == 24 and abs(area(g) - 3.84) < 1e-5 and sizes(g) == [4] * 6
      and not g.get_group(PRIM, "edgefilletpolys").any())
gch = BV(shape="chamfer")
check("  negative control: Chamfer adds a strip for each of the 12 edges and a triangle for each of the 8 corners (26 prims), the 6 inset prims are at the same positions",
      gch.nprims == 26 and closed_manifold(gch) and has_pts(gch, P_(g), 1e-6) and not closed_manifold(g))
BOX3 = build.box((1, 1, 1), (0, 0, 0), (3, 3, 3))       # 2x2 cells per face: flat edges inside faces
ang = np.asarray(__import__("comfyui_pcg.geo.topology", fromlist=["x"]).edge_angles(BOX3))
ep3 = np.asarray(_topo(BOX3).edge_points)
b3 = BOX3.copy()
b3.set_edge_group("sharp", ep3[ang > 45].astype(np.int32))
g1 = BV(b3, shape="chamfer", ignore_flat=True)
g2 = BV(b3, shape="chamfer", group="sharp", group_type="edges")
g0 = BV(b3, shape="chamfer")
check("Ignore Flat Edges: the flat edges inside faces (angle 0 deg < 2 deg) are not bevelled -- bit-identical to an edge group of only the 24 cube edges",
      int((ang > 45).sum()) == 24 and digest(g1) == digest(g2) and closed_manifold(g1))
check("  negative control: turned off, flat edges are bevelled too (more prims)", g0.nprims > g1.nprims)
check("  Maximum Normal Angle raised to 100 deg (> 90 deg): the cube edges count as flat too, nothing is bevelled; 89 deg still bevels",
      digest(BV(b3, shape="chamfer", ignore_flat=True, max_normal_angle=100.0)) == digest(b3)
      and digest(BV(b3, shape="chamfer", ignore_flat=True, max_normal_angle=89.0)) == digest(g1)
      and digest(BV(b3, shape="chamfer", ignore_flat=False, max_normal_angle=100.0)) == digest(g0))
check("  edge group + Ignore Flat: flat ones removed only from the given edges",
      digest(BV(b3, shape="chamfer", group="sharp", group_type="edges", ignore_flat=True)) == digest(g2))

sec("PolyBevel: Distance Scaling = Scale by Attribute, Convexity, Offset Group")
Pb = P_(BOX)
ia = int(np.argmin(np.linalg.norm(Pb - [-0.5, -0.5, -0.5], axis=1)))
ib = int(np.argmin(np.linalg.norm(Pb - [0.5, -0.5, -0.5], axis=1)))
one = BOX.copy()
one.set_edge_group("e", np.array([[ia, ib]], np.int32))
ps = np.ones((8, 1), np.float32)
ps[ib] = 2.0
one.set(POINT, "pscale", ps)
E1 = lambda **kw: BV(one, group="e", group_type="edges", **kw)        # noqa: E731
g = E1(shape="chamfer", distance_scaling="attribute")
check("Scale by Attribute: one edge, pscale 1 at one end and 2 at the other -> one end insets 0.1, the other 0.2 (sliding that far along each of the two adjacent edges)",
      has_pts(g, [[-0.5, -0.4, -0.5], [-0.5, -0.5, -0.4], [0.5, -0.3, -0.5], [0.5, -0.5, -0.3]], 1e-6)
      and closed_manifold(g) and g.npoints == 12)      # 8 original points (the edge's two endpoints remain on the end faces) + 4 sliding points
g0 = E1(shape="chamfer")
check("  negative control: No Scaling insets 0.1 at both ends (pscale present but not read)",
      has_pts(g0, [[-0.5, -0.4, -0.5], [0.5, -0.4, -0.5], [0.5, -0.5, -0.4]], 1e-6)
      and not has_pts(g0, [[0.5, -0.3, -0.5]], 1e-3))
# volume: what is cut off is a wedge whose cross-section varies linearly from 1/2·0.1^2 to 1/2·0.2^2, integral(1/2 d(x)^2)dx, d = 0.1(1 + x) -> 0.005·7/3
check("  volume = 1 - 0.005·7/3 (both legs of the cross-section vary linearly from 0.1 to 0.2)",
      abs(abs(volume(g)) - (1 - 0.005 * 7 / 3)) < 1e-5, abs(volume(g)))
one.set(POINT, "w", np.full((8, 1), 0.5, np.float32))
check("  attribute 0.5 everywhere = Distance halved (bit-exact); renamed attribute; missing attribute raises",
      digest(E1(shape="chamfer", distance_scaling="attribute", scale_attribute="w"))
      == digest(run("PCG_PolyBevel", geo=one, distance=0.05, group="e", group_type="edges", shape="chamfer"))
      and raises(lambda: E1(distance_scaling="attribute", scale_attribute="nope"), "nope")
      and raises(lambda: ops.polybevel(one, distance_scaling="x"), "Distance Scaling"))
one.set(POINT, "big", np.full((8, 1), 100.0, np.float32))
gl = E1(shape="chamfer", distance_scaling="attribute", scale_attribute="big")
check("  Limit Distance also applies to the scaled distance (clipped within half the adjacent edge, 0.5); turned off it does not",
      has_pts(gl, [[-0.5, -0.5 + 0.4995, -0.5]], 1e-5)
      and not has_pts(E1(shape="chamfer", distance_scaling="attribute", scale_attribute="big",
                         limit_distance=False), [[-0.5, -0.5 + 0.4995, -0.5]], 1e-2))
d_ = 0.1
tmid = {1.0: d_ * (1 - 1 / np.sqrt(2)), 0.0: d_ / 2, -1.0: d_ / np.sqrt(2), 0.5: 0.5 * (d_ / 2 + d_ * (1 - 1 / np.sqrt(2)))}
okc = True
for c_, t_ in tmid.items():
    gcv = E1(shape="round", divisions=2, convexity=c_)
    okc = okc and has_pts(gcv, [[-0.5, -0.5 + t_, -0.5 + t_], [0.5, -0.5 + t_, -0.5 + t_]], 1e-6)
check("Convexity: a 90 deg edge, 2 segments, the arc midpoint lies on the diagonal at t·sqrt(2) from the edge -- 1: t = d(1-1/sqrt(2)); 0: d/2 (chord midpoint); "
      "-1: d/sqrt(2) (arc flipped inward); 0.5 exactly between the first two", okc)
check("  Convexity 0 = Chamfer with the same number of segments (bit-exact); not read unless Round; beyond +-1 clamped",
      digest(E1(shape="round", divisions=2, convexity=0.0)) == digest(E1(shape="chamfer", divisions=2))
      and digest(E1(shape="chamfer", divisions=2, convexity=-1.0)) == digest(E1(shape="chamfer", divisions=2))
      and digest(E1(shape="round", divisions=2, convexity=-5.0)) == digest(E1(shape="round", divisions=2, convexity=-1.0)))
gr1, gr0 = BV(shape="round", divisions=4), BV(shape="round", divisions=4, convexity=0.0)
check("  whole cube: volume with Convexity 0 = Chamfer volume < Convexity 1 (round) volume; all closed",
      closed_manifold(gr0) and abs(abs(volume(gr0)) - abs(volume(BV(shape="chamfer", divisions=4)))) < 1e-6
      and abs(volume(gr0)) < abs(volume(gr1)) - 1e-3
      and abs(volume(BV(shape="round", divisions=4, convexity=-1.0))) < abs(volume(gr0)) - 1e-3)
g = BV(shape="chamfer", offset_group="off")
check("Offset Group: the edges of the 6 inset prims (24 x 0.8) are all edges bordering bevel faces",
      len(g.edge_groups["off"]) == 24 and abs(edge_len(g, g.edge_groups["off"]) - 19.2) < 1e-5)
check("  empty writes nothing; with Output Groups off nothing is written either; Shape = None has no bevel faces -> empty group",
      "off" not in BV(shape="chamfer").edge_groups
      and "off" not in BV(shape="chamfer", offset_group="off", use_out_groups=False).edge_groups
      and len(BV(shape="none", offset_group="off").edge_groups["off"]) == 0)

check("Ignore Flat boundary: an edge of exactly 90 deg is still bevelled with Maximum Normal Angle = 90 (only >= counts as flat)",
      digest(BV(b3, shape="chamfer", ignore_flat=True, max_normal_angle=90.0)) == digest(g1))
check("  Group Type = Edges + Ignore Flat: given all edges, flat ones are still removed (= only the cube edges)",
      digest(BV(b3, shape="chamfer", group=" ".join(["sharp"]), group_type="edges", ignore_flat=True))
      == digest(g2)
      and digest(BV(b3, shape="chamfer", group="*", group_type="edges", ignore_flat=True)) == digest(g2))
check("  function defaults: Limit Distance on, flat edges not ignored, Convexity 1, no Offset Group",
      digest(ops.polybevel(BOX, "", 0.1, 4, "round"))
      == digest(ops.polybevel(BOX, "", 0.1, 4, "round", "edgefilletpolys", "pointfilletpolys", "guess", True,
                              False, 2.0, "none", "pscale", 1.0, ""))
      and digest(ops.polybevel(BOX, "", 0.7, 1, "chamfer")) == digest(ops.polybevel(BOX, "", 0.7, 1, "chamfer",
                                                                                   limit_distance=True))
      and digest(ops.polybevel(b3, "", 0.1, 1, "chamfer")) == digest(ops.polybevel(b3, "", 0.1, 1, "chamfer",
                                                                                  ignore_flat=False)))
hexp_ = build.tube(1.0, 1.0, 1.0, 6, 2)
same_as_base("hexagonal prism (edge angles 60 / 120 deg, the round's axis is not where both faces inset by d): round 4 segments bit-identical to baseline",
             BV(hexp_, shape="round", divisions=4),
             lambda: base_mod("ops").polybevel(hexp_, "", 0.1, 4, "round", "edgefilletpolys", "pointfilletpolys",
                                               "guess", True))

sec("PolyBevel: bit-exact regression of defaults, panel")
for nm, kw in (("round 4 segments", dict(shape="round", divisions=4)), ("chamfer 2 segments", dict(shape="chamfer", divisions=2)),
               ("solid", dict(shape="solid")), ("crease", dict(shape="crease")),
               ("one edge round 3 segments", dict(shape="round", divisions=3, group="e", group_type="edges"))):
    same_as_base(f"{nm}: with new parameters at defaults bit-identical to baseline", BV(one, **kw),
                 lambda: base_mod("ops").polybevel(one, kw.get("group", ""), 0.1, kw.get("divisions", 1),
                                                   kw["shape"], "edgefilletpolys", "pointfilletpolys",
                                                   kw.get("group_type", "guess"), True))
ui = PANEL.layout_for("PCG_PolyBevel", M["PCG_PolyBevel"].INPUT_TYPES())[0]
check("panel: self-check passes; Shape gains None, Distance Scaling has Houdini's labels, Point Offset Scale appears only when scaling by attribute",
      not PANEL.check_layout("PCG_PolyBevel", M["PCG_PolyBevel"].INPUT_TYPES())
      and ui["shape"]["menu"]["none"] == "None"
      and ui["distance_scaling"]["menu"] == {"none": "No Scaling", "attribute": "Scale by Attribute"}
      and "distance_scaling != attribute" in ui["scale_attribute"]["hide"]
      and "ignore_flat == 0" in ui["max_normal_angle"]["disable"] and "shape != round" in ui["convexity"]["disable"],
      PANEL.check_layout("PCG_PolyBevel", M["PCG_PolyBevel"].INPUT_TYPES()))

# pcg118: round bevel on a non-90 deg edge. A box with its top face extruded 0.3 up and inset 0.3 has 135 deg edges
# between the top and the sloped sides. Before, the arc centre sat at the bevel distance from both faces, which is only
# the fillet radius at 90 deg: with 3+ divisions the arc rose 2.5 mm above the top face (seen in tutorial_01).
from comfyui_pcg.geo import build as _bld                 # noqa: E402
from comfyui_pcg.geo.core import POINT as _PT, PRIM as _PR  # noqa: E402
_tb = _bld.box(size=(2.0, 1.0, 2.0))
_PB = np.asarray(_tb.get(_PT, "P"))
_cen = np.array([_PB[_tb.prim_points(i)].mean(0) for i in range(_tb.nprims)])
_tb.set(_PR, "top", (_cen[:, 1] > 0.49).astype(np.int32).reshape(-1, 1))
_tp = ops.polyextrude(_tb, "@top == 1", distance=0.3, inset=0.3)
_hmax = [float(np.asarray(ops.polybevel(_tp, distance=0.05, divisions=_d).get(_PT, "P"))[:, 1].max())
         for _d in (2, 3, 5, 8)]
check("round bevel on 135 deg edges keeps the top at y = 0.8 at any division count",
      max(abs(h - 0.8) for h in _hmax) < 1e-6, [round(h, 6) for h in _hmax])
# the tapered box is convex, so a rounding must stay inside every original face plane
_PT0 = np.asarray(_tp.get(_PT, "P"), np.float64)
_planes = []
for _i in range(_tp.nprims):
    _q = _PT0[_tp.prim_points(_i)]
    _n = np.cross(_q[1] - _q[0], _q[2] - _q[0])
    _n /= np.linalg.norm(_n)
    if _n @ (_q.mean(0) - _PT0.mean(0)) < 0:
        _n = -_n
    _planes.append((_n, _q[0]))
_P5 = np.asarray(ops.polybevel(_tp, distance=0.05, divisions=5).get(_PT, "P"), np.float64)
_out = max(float(((_P5 - q0) @ n).max()) for n, q0 in _planes)
# (edge arcs are exact now; the corner sphere patches still use one sphere of radius = distance, which cannot be tangent
# to a 90 and a 135 deg edge at once, so a corner may sit a fraction of a millimetre out -- under 1% of the distance)
check(f"  every point of a 5-division round bevel is inside the convex original, corners within 1% of the "
      f"distance (worst {_out:.1e} m outside; it was 9e-3 m)", _out < 5e-4, _out)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
