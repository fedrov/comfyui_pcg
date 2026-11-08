"""
pcg100 · pack s5_deform_paths: parameters / menu items added against the SideFX docs.

  Smooth             Method (Uniform / Scale-Dominant / Curvature-Dominant), Pin Group Boundary,
                     Constrained Points, Attributes (point / vertex attributes, uv seams smoothed separately),
                     Weight Attribute, Recompute Affected Normals
  (sections for the other nodes are in the sec() calls below)

Everything is checked against hand-computed numbers (coordinates, weights, point counts); every new option gets a negative control; output at defaults is compared bit by bit with
before the change (commit 9e3fb92) -- digests hard-coded in GOLDEN, `--digests` prints the current digests (independent of git).
"""
import hashlib
import json
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
from comfyui_pcg.geo import build, ops                  # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, VERTEX, PRIM, DETAIL  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def P_(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def A_(g, k, cls=POINT):
    return np.asarray(g.get(cls, k), np.float64)


def defaults(nid):
    kw = {}
    for part in ("required", "optional"):
        for k, spec in M[nid].INPUT_TYPES().get(part, {}).items():
            if isinstance(spec[0], (list, tuple)):
                kw[k] = spec[1]["default"] if len(spec) > 1 and "default" in spec[1] else spec[0][0]
            elif len(spec) > 1 and isinstance(spec[1], dict) and "default" in spec[1]:
                kw[k] = spec[1]["default"]
    return kw


def run_all(nid, **over):
    kw = defaults(nid)
    kw.update(over)
    r = getattr(M[nid](), M[nid].FUNCTION)(**kw)
    return r["result"] if isinstance(r, dict) else r


def run(nid, **over):
    return run_all(nid, **over)[0]


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
    for cls in (POINT, VERTEX, PRIM, DETAIL):
        for k in sorted(g.attribs[cls]):
            v = np.asarray(g.attribs[cls][k])
            h.update(k.encode())
            h.update(str(v.tolist()).encode() if v.dtype.kind in "OUS"
                     else np.ascontiguousarray(v).tobytes())
        for k in sorted(g.groups.get(cls, {})):
            h.update(k.encode())
            h.update(np.ascontiguousarray(g.groups[cls][k]).tobytes())
    for k in sorted(getattr(g, "edge_groups", {}) or {}):
        h.update(("e/" + k).encode())
        h.update(np.ascontiguousarray(g.edge_groups[k]).tobytes())
    return h.hexdigest()


CASES = {}


def case(key, nid, **kw):
    CASES[key] = (nid, kw)


def case_digest(nid, kw):
    """_out selects which output (default output 0); non-geometry outputs are digested by repr."""
    kw = dict(kw)
    i = kw.pop("_out", 0)
    o = run_all(nid, **kw)[i]
    if isinstance(o, Geometry):
        return digest(o)[:16]
    return hashlib.sha1(repr(o).encode()).hexdigest()[:16]


def golden_check(prefix, golden):
    keys = [k for k in CASES if k.startswith(prefix)]
    golden = {k: v for k, v in golden.items() if k.startswith(prefix)}
    now = {k: case_digest(*CASES[k]) for k in keys}
    bad = {k: (golden.get(k), v) for k, v in now.items() if golden.get(k) != v}
    check(f"{prefix}: output digests of {len(keys)} old calls match before the change",
          len(keys) == len(golden) and len(keys) > 0 and not bad, bad or "")


def close(a, b, e=1e-5):
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    try:
        return bool(np.all(np.abs(a - b) <= e))
    except ValueError:
        return False


def panel_ok(nid):
    bad = PANEL.check_layout(nid, M[nid].INPUT_TYPES())
    check(f"{nid} panel check_layout is empty", not bad, bad or "")


def opts(nid, k):
    return list(M[nid].INPUT_TYPES()["required"][k][0])


def with_P(g, P):
    g = g.copy()
    g.set(POINT, "P", np.asarray(P, np.float32))
    return g


def bumpy(n=6, seed=3):
    """n x n grid with a deterministic undulation in y -- for regression."""
    g = build.grid(4.0, 4.0, n, n)
    P = P_(g)
    rng = np.random.default_rng(seed)
    P[:, 1] = rng.uniform(-0.3, 0.3, len(P))
    g = with_P(g, P)
    g.set(POINT, "Cd", rng.uniform(0, 1, (len(P), 3)).astype(np.float32))
    g.set(VERTEX, "uvv", rng.uniform(0, 1, (g.nvertices, 2)).astype(np.float32))
    return ops.compute_normals(g, "point")


# ═══════════════════════════════════════════════════════════ Old calls (bit-exact regression)
# old calls of all nodes are registered here; --digests exits before running any new feature -- so the same file
# can produce GOLDEN when run against the code from before the change.
B6 = bumpy()
LINE = Geometry.from_mesh([[0, 0, 0], [1, 1, 0], [3, 0, 0], [4, 1, 0]], [[0, 1, 2, 3]], closed=False)
case("smooth_default", "PCG_Smooth", geo=B6)
case("smooth_free", "PCG_Smooth", geo=B6, pin_boundary=False, strength=0.8, iterations=7)
case("smooth_grp", "PCG_Smooth", geo=B6, group="7-20", iterations=3)
case("smooth_line", "PCG_Smooth", geo=LINE, pin_boundary=False, iterations=2)
case("smooth_box", "PCG_Smooth", geo=build.box((1, 2, 1), (0, 0, 0), (3, 3, 3)), iterations=10)

SPH = ops.compute_normals(build.sphere(1.0, 16, 10), "point")
for m in ("euclidean", "steps", "distance"):
    case("speak_" + m, "PCG_SoftPeak", geo=SPH, group="0-3", radius=0.8, metric=m, _out=0)
    case("sxf_" + m, "PCG_SoftTransform", geo=SPH, group="0-3", radius=0.8, metric=m, ty=0.5,
         rx=20.0, sz=1.3)
case("speak_rep", "PCG_SoftPeak", geo=SPH, group="5", _out=1)
case("speak_ramp", "PCG_SoftPeak", geo=B6, group="14", ramp="0:0 0.3:0.8 1:1", ramp_mode="linear",
     weight_attribute="ww", update_normals=False)
case("sxf_empty", "PCG_SoftTransform", geo=B6, tx=1.0, rz=30.0)
case("sxf_pivot", "PCG_SoftTransform", geo=B6, group="3 4", use_group_center=False, pivot_x=1.0,
     ry=45.0, falloff_ramp="0:0 0.5:0.2 1:1", ramp_mode="smooth", normals="none",
     falloff_attribute="fa")
TUBE = ops.compute_normals(build.tube(0.5, 0.5, 2.0, 12, 6), "point")
for op_ in ("twist", "bend", "taper", "squash", "shear"):
    case("dfm_" + op_, "PCG_Deform", geo=TUBE, op=op_, angle=70.0, amount=0.6, shear_b=0.3,
         shear_c=-0.2)
case("dfm_range", "PCG_Deform", geo=TUBE, op="bend", axis="y", up_x=1.0, up_y=0.0, use_range=True,
     range_start=-0.2, range_end=0.6, group="0-40")
case("dfm_x", "PCG_Deform", geo=B6, op="twist", axis="x", angle=-120.0, normals="none")
ETL = Geometry.from_mesh([[0, 0, 0], [1, 0, 0], [3, 0, 0], [6, 0, 0]], [[0, 1, 2, 3]], closed=False)
ETL.set(POINT, "a", np.float32([[10], [20], [30], [40]]))
ETL.set_group(POINT, "r", np.array([False, False, False, True]))
ETG = build.grid(3.0, 3.0, 4, 4)
ETG.set(POINT, "v", np.arange(16, dtype=np.float32)[:, None] * 0.5)
ETG.set_group(POINT, "root", np.arange(16) == 5)
for op_ in ("distance", "copy", "sum", "average"):
    case("et_c_" + op_, "PCG_EdgeTransport", geo=ETL, attribute="a", operation=op_, method="curves")
    case("et_n_" + op_, "PCG_EdgeTransport", geo=ETG, attribute="v", operation=op_, method="network",
         root_group="root")
case("et_c_r", "PCG_EdgeTransport", geo=ETL, attribute="a", operation="sum", method="curves",
     root_group="r", output="o", unreached_group="")
case("et_rep", "PCG_EdgeTransport", geo=ETG, operation="distance", root_group="root", _out=1)
FG = build.grid(4.0, 4.0, 5, 5)
FG.set(POINT, "c", (np.arange(25) % 3).astype(np.float32)[:, None])
for md in ("nearest_end", "each_pair", "sequence"):
    for outp in ("paths", "merge", "group"):
        case(f"fsp_{md}_{outp}", "PCG_FindShortestPath", geo=FG, start_group="0 4",
             end_group="20 12", mode=md, output=outp)
case("fsp_cost", "PCG_FindShortestPath", geo=FG, start_group="0", end_group="24",
     cost_attribute="c", cost_weight=0.5, slope_weight=1.0, use_length=False)
case("fsp_rep", "PCG_FindShortestPath", geo=FG, start_group="0 3", end_group="24", mode="each_pair",
     _out=1)
case("gfp_seq", "PCG_GroupFindPath", geo=FG, points="0 24 4")
case("gfp_close", "PCG_GroupFindPath", geo=FG, points="0 24 4", close=True, cost_attribute="c")
case("gfp_two_close", "PCG_GroupFindPath", geo=FG, points="0 24", close=True)
case("gfp_bnd", "PCG_GroupFindPath", geo=FG, points="0", mode="boundary_loop", group_name="b")
case("gfp_rep", "PCG_GroupFindPath", geo=FG, points="3 21", use_length=False, _out=1)

if "--digests" in sys.argv:
    print(json.dumps({k: case_digest(n, kw) for k, (n, kw) in CASES.items()}, indent=1))
    sys.exit(0)

GOLDEN = {  # digests from running the CASES above before the change (9e3fb92)
    "smooth_default": "0d6bafa921f7f1e3",
    "smooth_free": "ce905eb3788ab46b",
    "smooth_grp": "7cf95dd5b2845c8a",
    "smooth_line": "4c6c376d4d971a57",
    "smooth_box": "d7dc23ee620c6a01",
    "speak_euclidean": "6fd95a18f409e1c8",
    "sxf_euclidean": "725aec55cc6ce5d4",
    "speak_steps": "46455b35cf0b7f35",
    "sxf_steps": "1be6ffaec0687e30",
    "speak_distance": "3b5a2483f1153b76",
    "sxf_distance": "4f0fb9472bce8f68",
    "speak_rep": "d47ad2f58cd757a6",
    "speak_ramp": "2a3306c3bc1d0460",
    "sxf_empty": "e3b7001f40aae5eb",
    "sxf_pivot": "ef170e3e1bee1c76",
    "dfm_twist": "9d4485fad5768988",
    "dfm_bend": "59013563edd7ef75",
    "dfm_taper": "76aaa21d7952b449",
    "dfm_squash": "2835b135be5755b0",
    "dfm_shear": "63e7c0c364ad6679",
    "dfm_range": "1d309d6dbf1374a1",
    "dfm_x": "519998c62cad72d9",
    "et_c_distance": "9415bc8a23118827",
    "et_n_distance": "0f4d932c9c1de2a0",
    "et_c_copy": "888be4585f2f028d",
    "et_n_copy": "75369c73ebecc580",
    "et_c_sum": "f060ec76763aebbc",
    "et_n_sum": "b213ecce3ef3ffc5",
    "et_c_average": "2af71fe577989d16",
    "et_n_average": "00947280e9bb556d",
    "et_c_r": "c94c2259737415c4",
    "et_rep": "f73bc5f422f31158",
    "fsp_nearest_end_paths": "b4085a986aa436b5",
    "fsp_nearest_end_merge": "c001f7845036c1b7",
    "fsp_nearest_end_group": "9bc5174f8c742013",
    "fsp_each_pair_paths": "ea0238174318c046",
    "fsp_each_pair_merge": "770826eb90912ed0",
    "fsp_each_pair_group": "37d0a4cfb2a4e484",
    "fsp_sequence_paths": "a3f0c248a1cb8a7d",
    "fsp_sequence_merge": "aeaee6faf46b4d87",
    "fsp_sequence_group": "0e59a462d19064ac",
    "fsp_cost": "b08691d0c43fac9c",
    "fsp_rep": "998b8035c22ece5e",
    "gfp_seq": "0a272f70fddcbfb4",
    "gfp_close": "fde4b231961fea44",
    "gfp_two_close": "0a272f70fddcbfb4",
    "gfp_bnd": "612e26f3c26b3197",
    "gfp_rep": "7696304718c6265c",
}


# ═══════════════════════════════════════════════════════════ Smooth
sec("Smooth: default regression")
golden_check("smooth_", GOLDEN)
check("Method menu: uniform first (old behaviour)", opts("PCG_Smooth", "method") ==
      ["uniform", "scale_dominant", "curvature_dominant"])

G3 = build.grid(2.0, 2.0, 3, 3)
P = P_(G3)
P[4, 1] = 1.0
G3U = with_P(G3, P)
sec("Smooth:Method")
s_ = run("PCG_Smooth", geo=G3U, iterations=1)
check("Uniform: center point y 1 -> 0.5 (four neighbours at y=0, strength 0.5), boundary unchanged",
      close(P_(s_)[4], [0, 0.5, 0]) and close(np.delete(P_(s_), 4, 0), np.delete(P, 4, 0)))
# polyline 0-1-2-3, endpoints pinned: point 1's neighbours are 0 (0,0,0) and 2 (3,0,0)
L3 = Geometry.from_mesh([[0, 0, 0], [1, 1, 0], [3, 0, 0], [4, 1, 0]], [[0, 1, 2, 3]], closed=False)
kw = dict(geo=L3, pin_boundary=False, constrained_points="0 3", strength=1.0, iterations=1)
p_u = P_(run("PCG_Smooth", method="uniform", **kw))
p_s = P_(run("PCG_Smooth", method="scale_dominant", **kw))
w1, w2 = 1 / np.sqrt(2), 1 / np.sqrt(5)               # |1-0| = √2,|1-2| = √5
check("Uniform: point 1 -> neighbour average (1.5, 0, 0)", close(p_u[1], [1.5, 0, 0]))
check("Scale-Dominant: point 1 -> weighted by 1/|e| = (3·w2/(w1+w2), 0, 0)",
      close(p_s[1], [3 * w2 / (w1 + w2), 0, 0]), p_s[1])
check("Scale-Dominant point 2: neighbour 1 (1,1,0) at sqrt(5), 3 (4,1,0) at sqrt(2)",
      close(p_s[2], [(1 * w2 + 4 * w1) / (w1 + w2), 1, 0]), p_s[2])
p_c = P_(run("PCG_Smooth", method="curvature_dominant", **kw))
check("Curvature-Dominant on a curve (no triangles) = 1/|e| weights", close(p_c, p_s))
# planar triangle fan: the cotangent Laplacian is exact for linear functions, an interior point on a plane does not move; uniform weights pull it to the ring's centroid
ang = np.radians(np.arange(6) * 60.0 + 10.0)
ring = np.stack([np.cos(ang), np.zeros(6), np.sin(ang)], 1)
FAN = Geometry.from_mesh(np.vstack([[[0.25, 0.0, 0.1]], ring]),
                         [[0, 1 + k, 1 + (k + 1) % 6] for k in range(6)])
pc = P_(run("PCG_Smooth", geo=FAN, method="curvature_dominant", strength=1.0, iterations=3))
pu = P_(run("PCG_Smooth", geo=FAN, method="uniform", strength=1.0, iterations=1))
check("Curvature-Dominant: the interior point of a planar triangle fan stays in place (linear exactness of cotangent weights)",
      close(pc[0], [0.25, 0, 0.1], 1e-5), pc[0])
check("negative control: Uniform pulls the interior point to the ring's centroid (0,0,0)", close(pu[0], [0, 0, 0], 1e-6))
check("negative control: Scale-Dominant moves it too (1/|e| weights are not linearly exact)",
      not close(P_(run("PCG_Smooth", geo=FAN, method="scale_dominant", strength=1.0,
                       iterations=1))[0], [0.25, 0, 0.1], 1e-3))
# lift the interior point: under cotangent weights it falls back mainly along the normal, tangential drift far smaller than with uniform weights
F2 = with_P(FAN, np.vstack([[[0.25, 0.4, 0.1]], ring]))
pc = P_(run("PCG_Smooth", geo=F2, method="curvature_dominant", strength=1.0, iterations=1))
pu = P_(run("PCG_Smooth", geo=F2, method="uniform", strength=1.0, iterations=1))
tc = np.hypot(pc[0, 0] - 0.25, pc[0, 2] - 0.1)
tu = np.hypot(pu[0, 0] - 0.25, pu[0, 2] - 0.1)
check("Curvature-Dominant: the lifted interior point returns to y=0, tangential drift < 1/2 of uniform weights",
      close(pc[0, 1], 0.0, 1e-6) and tc < 0.5 * tu, (tc, tu))
# obtuse angles: edge weights with negative cotangents are clamped to 0. With the interior point very close to one ring edge, the two angles opposite that edge are obtuse
FANO = Geometry.from_mesh([[0, 0.2, 0], [-1, 0, -0.05], [1, 0, -0.05], [1, 0, 1], [-1, 0, 1]],
                          [[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1]])
po = P_(run("PCG_Smooth", geo=FANO, method="curvature_dominant", strength=1.0, iterations=1))
check("Curvature-Dominant: result finite, interior point y falls back (still a convex combination after clamping negative weights to 0)",
      np.isfinite(po).all() and 0.0 - 1e-6 <= po[0, 1] < 0.2 and
      -1 <= po[0, 0] <= 1 and -0.05 <= po[0, 2] <= 1, po[0])
# zero-length edges: weight 0 (a neighbour coinciding with itself does not participate). Point 1's neighbours are 0 (at sqrt(2)) and 2 (coinciding with 1)
LZ = Geometry.from_mesh([[0, 0, 0], [1, 1, 0], [1, 1, 0], [3, 0, 0]], [[0, 1, 2, 3]], closed=False)
pz = P_(run("PCG_Smooth", geo=LZ, method="scale_dominant", pin_boundary=False,
            constrained_points="0 2 3", strength=1.0, iterations=1))
check("Scale-Dominant: coincident neighbour weight 0 -> point 1 goes to point 0 in one step", close(pz[1], [0, 0, 0]), pz[1])
# cotangents of zero-area triangles are 0; a point whose edge weights are all 0 stays in place
DG = Geometry.from_mesh([[0, 0, 0], [-1, 0, -1], [1, 0, -1], [1, 0, 1], [-1, 0, 1], [-0.5, 0, -1]],
                        [[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1], [1, 5, 2]])
pd = P_(run("PCG_Smooth", geo=DG, method="curvature_dominant", pin_boundary=False,
            constrained_points="0-4", strength=1.0, iterations=1))
check("Curvature-Dominant: a point only on zero-area triangles (all weights 0) does not move", close(pd[5], [-0.5, 0, -1]), pd[5])


def ref_cot_step(g, strength, free):
    """Per-face, per-corner reference implementation of one cotangent-weight step (pure Python loops; diagonals dropped, negatives clamped to 0, 1/|e| for edges with no triangle)."""
    P = P_(g)
    edges = set()
    for k in range(g.nprims):
        pts = [int(x) for x in g.prim_points(k)]
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            edges.add((min(a, b), max(a, b)))
    cot, neg = {}, 0
    for k in range(g.nprims):
        pts = [int(x) for x in g.prim_points(k)]
        for t in range(1, len(pts) - 1):
            tri = (pts[0], pts[t], pts[t + 1])
            for c in range(3):
                o, i, j = tri[c], tri[(c + 1) % 3], tri[(c + 2) % 3]
                u, v = P[i] - P[o], P[j] - P[o]
                e = (min(i, j), max(i, j))
                if e in edges:
                    cot[e] = cot.get(e, 0.0) + np.dot(u, v) / np.linalg.norm(np.cross(u, v))
    out = P.copy()
    for p in free:
        num, den = np.zeros(3), 0.0
        for (a, b) in edges:
            if p in (a, b):
                q = b if p == a else a
                w = cot[(a, b)] if (a, b) in cot else 1 / np.linalg.norm(P[q] - P[p])
                neg += w < 0
                w = max(w, 0.0)
                num += w * P[q]
                den += w
        if den > 0:
            out[p] = P[p] + (num / den - P[p]) * strength
    return out, neg


# quad grid (fan-triangulated with diagonals) + undulation + lateral jitter to create obtuse angles
GQ = build.grid(4.0, 4.0, 5, 5)
PQ = P_(GQ)
rq = np.random.default_rng(11)
PQ[:, 1] = rq.uniform(-0.5, 0.5, 25)
PQ[:, [0, 2]] += rq.uniform(-0.45, 0.45, (25, 2))
GQ = with_P(GQ, PQ)
ref, nneg = ref_cot_step(GQ, 0.7, [6, 7, 8, 11, 12, 13, 16, 17, 18])
got = P_(run("PCG_Smooth", geo=GQ, method="curvature_dominant", strength=0.7, iterations=1))
check(f"Curvature-Dominant on a jittered quad grid = the per-corner reference implementation ({nneg} negative weights clamped to 0)",
      close(got, ref, 1e-5) and nneg > 0, np.abs(got - ref).max())
check("invalid method raises", raises(lambda: run("PCG_Smooth", geo=G3U, method="x"), "method must be"))

sec("Smooth:Constrained Boundary / Constrained Points")
G5 = build.grid(4.0, 4.0, 5, 5)
rng = np.random.default_rng(1)
P5 = P_(G5)
P5[:, 1] = rng.uniform(-1, 1, 25)
G5B = with_P(G5, P5)
P5 = P_(G5B)                                    # values after storing as float32
inner = "6 7 8 11 12 13 16 17 18"
d0 = np.abs(P_(run("PCG_Smooth", geo=G5B, group=inner, iterations=1)) - P5).sum(1) > 0
d1 = np.abs(P_(run("PCG_Smooth", geo=G5B, group=inner, iterations=1,
                   pin_group_boundary=True)) - P5).sum(1) > 0
check("negative control: with only Pin Border Points all 9 points of the 3x3 selection move", d0.sum() == 9)
check("Pin Group Boundary: the 8 points on the selection's outer edge are pinned, only center point 12 moves", np.nonzero(d1)[0].tolist() == [12])
d2 = np.abs(P_(run("PCG_Smooth", geo=G5B, iterations=1, pin_boundary=False,
                   pin_group_boundary=True)) - P5).sum(1) > 0
check("with Group empty (everything selected) Pin Group Boundary pins nothing", d2.all())
d3 = np.abs(P_(run("PCG_Smooth", geo=G5B, group=inner, iterations=2,
                   constrained_points="12 6")) - P5).sum(1) > 0
check("Constrained Points '12 6': these two points do not move, the other 7 selected points do",
      not d3[12] and not d3[6] and d3.sum() == 7)
G5B.set_group(POINT, "pin", np.arange(25) == 7)
d4 = np.abs(P_(run("PCG_Smooth", geo=G5B, group=inner, constrained_points="pin")) - P5).sum(1) > 0
check("Constrained Points accepts group names", not d4[7] and d4.sum() == 8)

sec("Smooth:Attributes")
G3C = G3.copy()
cd = np.zeros((9, 3), np.float32)
cd[4] = 1.0
G3C.set(POINT, "Cd", cd)
s_ = run("PCG_Smooth", geo=G3C, iterations=1, attributes="Cd")
check("Attributes 'Cd': center Cd 1 -> 0.5, P unchanged", close(A_(s_, "Cd")[4], [0.5] * 3) and
      close(P_(s_), P_(G3)))
s2 = run("PCG_Smooth", geo=with_P(G3C, P), iterations=1, attributes="C*")
check("wildcard 'C*' matches only Cd: P not smoothed (center y still 1)",
      close(A_(s2, "Cd")[4], [0.5] * 3) and close(P_(s2)[4], [0, 1, 0]))
s3 = run("PCG_Smooth", geo=with_P(G3C, P), iterations=1, attributes="P Cd")
check("'P Cd': both smoothed", close(A_(s3, "Cd")[4], [0.5] * 3) and close(P_(s3)[4], [0, 0.5, 0]))
check("nonexistent attribute name raises", raises(lambda: run("PCG_Smooth", geo=G3C, attributes="foo"), "foo"))
G3I = G3C.copy()
G3I.set(POINT, "ii", np.arange(9)[:, None].astype(np.int32))
check("int attributes are not smoothable (raises)", raises(lambda: run("PCG_Smooth", geo=G3I, attributes="ii"), "ii"))
# vertex uv: continuous uv, the center node -> average of the four neighbouring nodes
GV = G3.copy()
uvv = np.asarray(G3.get(POINT, "uv"))[G3.vertex_point].copy()
uvv[G3.vertex_point == 4] = [0.9, 0.2]
GV.set(VERTEX, "uvv", uvv)
s_ = run("PCG_Smooth", geo=GV, attributes="uvv", strength=1.0, iterations=1)
o = A_(s_, "uvv", VERTEX)
check("vertex uv: the 4 vertices of the center point move together to the neighbour-node average (0.5, 0.5), boundary nodes unchanged",
      close(o[G3.vertex_point == 4], [0.5, 0.5]) and
      close(o[G3.vertex_point != 4], uvv[G3.vertex_point != 4]))
# seam: uv of the two faces in the right half offset by +10 -> each point of the middle column (1,4,7) has two nodes
GS = G3.copy()
uvs = np.asarray(G3.get(POINT, "uv"))[G3.vertex_point].copy()
vprim = GS.vertex_prim()
uvs[(vprim == 1) | (vprim == 3)] += 10.0
uvs[(GS.vertex_point == 4) & ((vprim == 0) | (vprim == 2))] = [0.3, 0.9]
GS.set(VERTEX, "uvv", uvs)
o = A_(run("PCG_Smooth", geo=GS, attributes="uvv", strength=1.0, iterations=1,
           pin_boundary=False, constrained_points="0 1 2 3 5 6 7 8"), "uvv", VERTEX)
left4 = (GS.vertex_point == 4) & ((vprim == 0) | (vprim == 2))
right4 = (GS.vertex_point == 4) & ((vprim == 1) | (vprim == 3))
# neighbour nodes of the left node: 3 (0, .5), 1 left (.5, 1), 7 left (.5, 0) -> average (1/3, .5)
check("uv seam sides smoothed separately: left node = average of 3 neighbouring nodes on the left island, not pulled away by the +10 right island",
      close(o[left4], [1 / 3, 0.5]), o[left4][0])
check("right node: average of neighbouring nodes 5, 1 right, 7 right = (10+2/3, 10.5)",
      close(o[right4], [10 + (1 + 0.5 + 0.5) / 3, 10 + (0.5 + 1 + 0) / 3]), o[right4][0])
o2 = A_(run("PCG_Smooth", geo=GS, attributes="uvv", strength=1.0, iterations=1,
            constrained_points="0 1 2 3 5 6 7 8"), "uvv", VERTEX)
check("Pin Border Points on: nodes on uv island borders (seams) are pinned too", close(o2, uvs))

# vertex attributes under non-uniform weights reuse the point-edge weights: point 3 moved to x=-0.5 (0.5 from the center, the other neighbours at 1)
P3 = P_(G3)
P3[3, 0] = -0.5
GVS = with_P(GV, P3)
uv0 = np.asarray(G3.get(POINT, "uv"))[G3.vertex_point]
GVS.set(VERTEX, "uvv", uv0)
o = A_(run("PCG_Smooth", geo=GVS, attributes="uvv", method="scale_dominant", strength=1.0,
           iterations=1), "uvv", VERTEX)
# neighbour node uv: 1 (.5,1) w1, 3 (0,.5) w2, 5 (1,.5) w1, 7 (.5,0) w1 -> (0.4, 0.5)
check("Scale-Dominant smoothing of vertex uv: weighted by point edge length -> (0.4, 0.5)",
      close(o[G3.vertex_point == 4], [0.4, 0.5]), o[G3.vertex_point == 4][0])
check("negative control: with Uniform -> (0.5, 0.5)", close(A_(run(
    "PCG_Smooth", geo=GVS, attributes="uvv", strength=1.0, iterations=1), "uvv", VERTEX)
    [G3.vertex_point == 4], [0.5, 0.5]))

sec("Smooth:Weight Attribute")
GW = G3U.copy()
GW.set(POINT, "weight", np.full((9, 1), 2.0, np.float32))
s_ = run("PCG_Smooth", geo=GW, iterations=1, use_weight_attribute=True)
check("weight 2 x strength 0.5 = 1: center goes to the neighbour average y=0 in one step", close(P_(s_)[4], [0, 0, 0]))
GW.set(POINT, "weight", np.full((9, 1), 0.5, np.float32))
s_ = run("PCG_Smooth", geo=GW, iterations=1, use_weight_attribute=True)
check("weight 0.5: step 0.25 -> y = 0.75", close(P_(s_)[4], [0, 0.75, 0]))
GW.set(POINT, "weight", np.full((9, 1), 7.0, np.float32))
s_ = run("PCG_Smooth", geo=GW, iterations=1, use_weight_attribute=True)
check("very large weight: step clamped to 1 (does not overshoot the target)", close(P_(s_)[4], [0, 0, 0]))
check("negative control: toggle off, weights not read -> y = 0.5", close(P_(run("PCG_Smooth", geo=GW, iterations=1))[4],
                                             [0, 0.5, 0]))
GW.set(POINT, "w2", np.full((9, 1), 0.0, np.float32))
check("Weight Attribute renamed: w2 = 0 -> no movement", close(P_(run(
    "PCG_Smooth", geo=GW, iterations=1, use_weight_attribute=True, weight_attribute="w2")), P))
GW.set_string(POINT, "ws", np.array(["a"] * 9))
check("weight attribute is a string: our own error is raised", raises(lambda: run(
    "PCG_Smooth", geo=GW, use_weight_attribute=True, weight_attribute="ws"), "numeric point attribute"))
check("nonexistent weight attribute raises", raises(lambda: run("PCG_Smooth", geo=GW, use_weight_attribute=True,
                                             weight_attribute="nope"), "nope"))

sec("Smooth:Recompute Affected Normals")
GN = ops.compute_normals(G3U, "point")
GNV = ops.compute_normals(G3U, "vertex", cusp_angle=180.0)
s_ = run("PCG_Smooth", geo=GN, iterations=1, strength=1.0, recompute_normals=True)
check("point N: after smoothing the grid is flat -> all N = (0,1,0)", close(A_(s_, "N"), [0, 1, 0], 1e-6))
s_ = run("PCG_Smooth", geo=GN, iterations=1, strength=1.0)
check("negative control: not enabled -> N still the original (tilted)", close(A_(s_, "N"), A_(GN, "N")) and
      not close(A_(GN, "N"), [0, 1, 0], 1e-3))
s_ = run("PCG_Smooth", geo=GNV, iterations=1, strength=1.0, recompute_normals=True)
check("vertex N recomputed too", close(A_(s_, "N", VERTEX), [0, 1, 0], 1e-6))
# affected = points sharing a face with a moved point: on a 4x4 grid only corner point 0 moves (boundary not pinned); input N deliberately all set to +X
G4 = build.grid(3.0, 3.0, 4, 4)
P4 = P_(G4)
P4[0, 1] = 1.0
G4N = with_P(G4, P4)
G4N.set(POINT, "N", np.tile(np.float32([1, 0, 0]), (16, 1)))
s_ = run("PCG_Smooth", geo=G4N, iterations=1, strength=1.0, pin_boundary=False,
         constrained_points="1-15", recompute_normals=True)
ref = A_(ops.compute_normals(s_, "point"), "N")
aff = [0, 1, 4, 5]
check("only affected points recomputed (the 4 points of the face containing point 0), other points keep the original +X",
      close(A_(s_, "N")[aff], ref[aff]) and close(np.delete(A_(s_, "N"), aff, 0), [1, 0, 0]))
s_ = run("PCG_Smooth", geo=GN, iterations=1, strength=1.0, recompute_normals=True,
         attributes="P N")
check("N itself in Attributes: not recomputed (smoothed instead)", not close(A_(s_, "N"), [0, 1, 0], 1e-3))
panel_ok("PCG_Smooth")



# ═══════════════════════════════════════════════════════════ Soft Peak
def polyline(P, N=None):
    g = Geometry.from_mesh(np.asarray(P, np.float64), [list(range(len(P)))], closed=False)
    if N is not None:
        g.set(POINT, "N", np.asarray(N, np.float32))
    return g


XL = polyline([[x, 0, 0] for x in range(11)], [[0, 1, 0]] * 11)   # x = 0..10,N = +Y
T10 = np.arange(11) / 10.0


def peak_y(**kw):
    base = dict(geo=XL, group="0", distance=1.0, radius=10.0, update_normals=False)
    base.update(kw)
    return P_(run("PCG_SoftPeak", **base))[:, 1]


sec("Soft Peak: default regression / menus")
golden_check("speak_", GOLDEN)
check("Soft Type menu: ramp (old) first", opts("PCG_SoftPeak", "soft_type") ==
      ["ramp", "linear", "quadratic", "cubic", "metaball"])
check("Distance Metric menu: the old three items unchanged, attribute / radius_with_connectivity appended at the end",
      opts("PCG_SoftPeak", "metric") == ["euclidean", "steps", "distance", "attribute",
                                         "radius_with_connectivity"])

sec("Soft Peak: Soft Type (t = distance / Soft Radius, x = 0..10, handle at x=0, radius 10)")
check("Linear:1 − t", close(peak_y(soft_type="linear"), 1 - T10))
check("Quadratic:1 − t²(t=0.5 → 0.75)", close(peak_y(soft_type="quadratic"), 1 - T10 ** 2))
u = 1 - T10
check("Cubic default tangents 0/0 = smoothstep(1 - t) (t=0.2 -> 0.896)",
      close(peak_y(soft_type="cubic"), 3 * u ** 2 - 2 * u ** 3) and
      close(peak_y(soft_type="cubic")[2], 0.896))
check("Cubic far tangent 45 deg: adds tan45·(u^3 - 2u^2 + u)",
      close(peak_y(soft_type="cubic", tangent_far=45.0),
            3 * u ** 2 - 2 * u ** 3 + (u ** 3 - 2 * u ** 2 + u), 1e-5))
check("Cubic near tangent -30 deg: adds tan(-30 deg)·(u^3 - u^2)",
      close(peak_y(soft_type="cubic", tangent_near=-30.0),
            3 * u ** 2 - 2 * u ** 3 + np.tan(np.radians(-30)) * (u ** 3 - u ** 2), 1e-5))
check("Metaball Links: t=0.2 -> 0.88, t=0.5 -> 0.375, t=1 -> 0",
      close(peak_y(soft_type="metaball", kernel="links")[[2, 5, 10]], [0.88, 0.375, 0.0]))
check("Metaball RenderMan: (1 - t^2)^3 (t=0.2 -> 0.884736, t=0.5 -> 0.421875)",
      close(peak_y(soft_type="metaball", kernel="renderman")[[2, 5]], [0.884736, 0.421875]))
check("Metaball Hart: 1 - 6t^5 + 15t^4 - 10t^3 (t=0.2 -> 0.94208, t=0.5 -> 0.5)",
      close(peak_y(soft_type="metaball", kernel="hart")[[2, 5]], [0.94208, 0.5]))
check("negative control: with Soft Type = ramp (old), Ramp 0:0 1:1 smooth = smoothstep(1 - t)",
      close(peak_y(), 3 * u ** 2 - 2 * u ** 3) and
      not close(peak_y(), peak_y(soft_type="linear"), 1e-3))
check("0 outside the radius: radius 4 -> x >= 4 do not move", close(peak_y(soft_type="linear", radius=4.0)[4:], 0))
check("invalid Soft Type / Kernel raises", raises(lambda: peak_y(soft_type="x"), "Soft Type") and
      raises(lambda: peak_y(soft_type="metaball", kernel="wyvill"), "Kernel"))

sec("Soft Peak:Distance Metric = Attribute")
XA = XL.copy()
XA.set(POINT, "dist", (np.arange(11) * 0.5)[:, None].astype(np.float32))   # distance = x/2
check("Apply Rolloff on: distance taken from the attribute (x/2), falloff by Soft Type; empty group = everything",
      close(peak_y(geo=XA, group="", metric="attribute", soft_type="linear", radius=5.0),
            1 - np.arange(11) * 0.5 / 5.0))
check("Apply Rolloff off: attribute value used directly as the weight (not clamped)",
      close(peak_y(geo=XA, group="", metric="attribute", apply_rolloff=False, distance=2.0),
            2.0 * np.arange(11) * 0.5))
check("Group only limits who can move: 0 outside group '3-5', not forced to 1 inside",
      close(peak_y(geo=XA, group="3-5", metric="attribute", soft_type="linear", radius=5.0),
            np.where((np.arange(11) >= 3) & (np.arange(11) <= 5), 1 - np.arange(11) * 0.1, 0)))
XA.set(POINT, "dd", (10 - np.arange(11))[:, None].astype(np.float32))
check("Distance Attribute renamed dd (= 10 - x)", close(peak_y(
    geo=XA, group="", metric="attribute", soft_type="linear", distance_attribute="dd"), T10))
check("points with distance > radius have weight 0 (radius 2, dd >= 3 do not move)", close(peak_y(
    geo=XA, group="", metric="attribute", soft_type="linear", distance_attribute="dd",
    radius=2.0), np.where(10 - np.arange(11) <= 2, 1 - (10 - np.arange(11)) / 2, 0)))
XA.set(POINT, "neg", np.full((11, 1), -2.0, np.float32))
check("negative distance attribute counts as 0 (on the handle): linear weight 1, not above 1", close(peak_y(
    geo=XA, group="", metric="attribute", soft_type="linear", distance_attribute="neg"), 1.0))
check("Soft Type = ramp with the Ramp non-zero at 0: still 0 outside the radius (dd > 2 do not move)", close(peak_y(
    geo=XA, group="", metric="attribute", distance_attribute="dd", radius=2.0,
    ramp="0:0.3 1:1", ramp_mode="linear"),
    np.where(10 - np.arange(11) <= 2, 0.3 + 0.7 * (1 - (10 - np.arange(11)) / 2), 0)))
check("negative control: when Metric is not attribute the attribute is not read (empty group raises asking for a group)",
      raises(lambda: peak_y(geo=XA, group=""), "point group"))
check("nonexistent attribute raises", raises(lambda: peak_y(geo=XL, group="", metric="attribute"), "dist"))

sec("Soft Peak:Radius with Connectivity")
# U-shaped polyline: first along +z to z=5, then back to z=0 on the x=1 side; handle = point 0 (0,0,0)
U = polyline([[0, 0, z] for z in range(6)] + [[1, 0, z] for z in range(5, -1, -1)], [[0, 1, 0]] * 12)
ye = P_(run("PCG_SoftPeak", geo=U, group="0", distance=1.0, radius=3.0, soft_type="linear",
            update_normals=False))[:, 1]
yc = P_(run("PCG_SoftPeak", geo=U, group="0", distance=1.0, radius=3.0, soft_type="linear",
            update_normals=False, metric="radius_with_connectivity"))[:, 1]
# the return side (1,0,0)/(1,0,1)/(1,0,2) is 1 / sqrt(2) / sqrt(5) from the handle, all within 3 in straight-line distance, but along edges the path goes through z=5
check("negative control: Radius (euclidean) drags the near points of the return side", close(ye[11], 1 - 1 / 3) and ye[10] > 0)
check("Radius with Connectivity: the return side is not connected (the path leaves the radius) -> does not move; the outward side as usual",
      close(yc[6:], 0) and close(yc[:4], 1 - np.arange(4) / 3) and close(yc[4:6], 0))

sec("Soft Peak:Translate Along Lead Normal")
ang = np.radians(np.arange(11) * 9.0)
NL = np.stack([np.sin(ang), np.cos(ang), np.zeros(11)], 1)          # a different normal per point
XN = polyline([[x, 0, 0] for x in range(11)], NL)
d_own = P_(run("PCG_SoftPeak", geo=XN, group="0", radius=10.0, distance=1.0, soft_type="linear",
               update_normals=False)) - P_(XN)
d_lead = P_(run("PCG_SoftPeak", geo=XN, group="0", radius=10.0, distance=1.0, soft_type="linear",
                update_normals=False, translate_along_lead_normal=True)) - P_(XN)
check("Lead: every point is pushed w along point 0's normal (0,1,0)", close(d_lead, np.outer(1 - T10, [0, 1, 0])))
check("negative control: turned off, each along its own normal (mushroom shape)", close(d_own, NL * (1 - T10)[:, None]))
for m in ("distance", "steps"):
    d2 = P_(run("PCG_SoftPeak", geo=XN, group="0 10", radius=10.0, distance=1.0, metric=m,
                soft_type="linear", update_normals=False, translate_along_lead_normal=True)) - P_(XN)
    dirs = d2 / np.maximum(np.linalg.norm(d2, axis=1, keepdims=True), 1e-12)
    want = np.where((np.arange(11) <= 5)[:, None], NL[0], NL[10])   # point 5 is equidistant, takes the lower point number 0
    check(f"Lead + {m}: two handles 0 / 10, points 1-5 along N0, 6-9 along N10", close(dirs, want, 1e-5))
# the nearest handle along edges differs from straight-line: U-shaped polyline, handles 0 (0,0,0) and 6 (1,0,5); point 6's normal is +X.
# point 11 (1,0,0): straight-line 1 from point 0, 5 from point 6 -> N0; along edges 5 from point 6, 11 from point 0 -> N6
NU = np.tile(np.float32([0, 1, 0]), (12, 1))
NU[6] = [1, 0, 0]
UN = polyline(P_(U).tolist(), NU)
kw = dict(geo=UN, group="0 6", radius=20.0, distance=1.0, soft_type="linear", update_normals=False,
          translate_along_lead_normal=True)
dz = P_(run("PCG_SoftPeak", metric="distance", **kw)) - P_(UN)
de = P_(run("PCG_SoftPeak", metric="euclidean", **kw)) - P_(UN)
check("Lead's nearest handle is computed with the selected Metric: point 11 along edges -> N6 (+X), straight-line -> N0 (+Y)",
      dz[11, 0] > 0 and close(dz[11, [1, 2]], 0) and de[11, 1] > 0 and close(de[11, [0, 2]], 0))
# two adjacent handles 0, 1: a handle moves along its own normal (must not take the other handle as parent)
d4 = P_(run("PCG_SoftPeak", geo=XN, group="0 1", radius=10.0, distance=1.0, metric="distance",
            soft_type="linear", update_normals=False, translate_along_lead_normal=True)) - P_(XN)
check("adjacent handles 0 / 1: point 1 along its own N1", close(d4[1], NL[1]))
# the parent is the one whose "d[u] + edge length" is closest to d[v]: point 4's two upstream neighbours 1 (1.2 via it, exact) and 3 (2.5 via it)
QP = polyline([[0, 0, 0], [1, 0, 0], [3.7, 0, 0], [3.2, 0, 0], [1.2, 0, 0]])
QP = Geometry.from_mesh(P_(QP), [[0, 1, 4, 3, 2]], closed=False)
NQ = np.tile(np.float32([0, 1, 0]), (5, 1))
NQ[2] = [1, 0, 0]
QP.set(POINT, "N", NQ)
d5 = P_(run("PCG_SoftPeak", geo=QP, group="0 2", radius=10.0, distance=1.0, metric="distance",
            soft_type="linear", update_normals=False, translate_along_lead_normal=True)) - P_(QP)
check("nearest handle along edges: point 4 (1.2 to point 0 via point 1, 2.5 to point 2 via point 3) along N0", close(d5[4, [0, 2]], 0) and
      d5[4, 1] > 0)
# zero-length edge: points 1, 2 coincide, point order puts "the lower point number downstream"; must not form a cycle
CY = Geometry.from_mesh([[2, 0, 0], [1, 0, 0], [1, 0, 0], [0, 0, 0]], [[3, 1, 2, 0]], closed=False)
NC = np.tile(np.float32([0, 1, 0]), (4, 1))
NC[3] = [0, 0, 1]
CY.set(POINT, "N", NC)
d6 = P_(run("PCG_SoftPeak", geo=CY, group="3", radius=10.0, distance=1.0, metric="distance",
            soft_type="linear", update_normals=False, translate_along_lead_normal=True)) - P_(CY)
check("zero-length edge does not form a cycle: points 0, 1, 2 all along handle 3's N (+Z)",
      close(d6[:3, :2], 0) and (d6[:3, 2] > 0).all())
XLA = XN.copy()
XLA.set(POINT, "dist", np.arange(11)[:, None].astype(np.float32))
lead = np.full(11, 3, np.int32)
lead[7] = -1
XLA.set(POINT, "lead", lead[:, None])
d3 = P_(run("PCG_SoftPeak", geo=XLA, group="", metric="attribute", radius=10.0, distance=1.0,
            soft_type="linear", update_normals=False, translate_along_lead_normal=True)) - P_(XLA)
check("Metric = Attribute: Lead Point Attribute gives point numbers (all 3, point 7 = -1 uses its own)",
      close(np.delete(d3, 7, 0), np.outer(np.delete(1 - T10, 7), NL[3])) and
      close(d3[7], NL[7] * 0.3))
XLA.set(POINT, "lead", np.full((11, 1), 11, np.int32))
XLF = XLA.copy()
XLF.set(POINT, "lead", np.zeros((11, 1), np.float32))
check("Lead attribute is not an integer: our own error is raised", raises(lambda: run(
    "PCG_SoftPeak", geo=XLF, group="", metric="attribute", translate_along_lead_normal=True),
    "integer point attribute"))
check("Lead point number out of range raises", raises(lambda: run(
    "PCG_SoftPeak", geo=XLA, group="", metric="attribute", translate_along_lead_normal=True),
    "out-of-range"))

sec("Soft Peak:Mask")
XM = XL.copy()
XM.set(POINT, "mask", np.linspace(0, 1, 11)[:, None].astype(np.float32))
check("Mask: Scale by Attribute: displacement x mask", close(peak_y(geo=XM, soft_type="linear", use_mask=True),
                                                 (1 - T10) * np.linspace(0, 1, 11)))
check("negative control: turned off, not multiplied", close(peak_y(geo=XM, soft_type="linear"), 1 - T10))
XS = XL.copy()
XS.set_string(POINT, "mask", np.array(["a"] * 11))
check("Mask attribute is a string: our own error is raised", raises(lambda: peak_y(geo=XS, use_mask=True), "numeric attribute"))
check("nonexistent Mask attribute raises", raises(lambda: peak_y(use_mask=True), "mask"))
panel_ok("PCG_SoftPeak")


# ═══════════════════════════════════════════════════════════ Soft Transform
def sxf(**kw):
    return run("PCG_SoftTransform", **kw)


def xform_ref(geo, **kw):
    """Reference: the Transform node (ops.xform_matrix, pinned by existing tests) applying the same transform to all points."""
    return P_(run("PCG_Transform", geo=geo, **kw))


sec("Soft Transform: default regression / menus")
golden_check("sxf_", GOLDEN)
check("Transform Order / Rotate Order default to srt / xyz (old behaviour)",
      opts("PCG_SoftTransform", "xform_order")[0] == "srt" and
      opts("PCG_SoftTransform", "rotate_order")[0] == "xyz")
check("Normals menu: the old two items unchanged, recompute_point / recompute_affected appended at the end",
      opts("PCG_SoftTransform", "normals") == ["jacobian", "none", "recompute_point",
                                               "recompute_affected"])

sec("Soft Transform: Transform Order / Rotate Order / Shear / Pivot Rotate (empty group = plain transform)")
P1 = polyline([[1, 0, 0], [0, 0, 1]])
p_ = P_(sxf(geo=P1, tx=1.0, rz=90.0, use_group_center=False))
check("SRT: (1,0,0) rotated 90 deg about Z first, then +X -> (1,1,0)", close(p_[0], [1, 1, 0]))
p_ = P_(sxf(geo=P1, tx=1.0, rz=90.0, use_group_center=False, xform_order="trs"))
check("TRS: first +X to (2,0,0), then rotate -> (0,2,0)", close(p_[0], [0, 2, 0]))
p_ = P_(sxf(geo=P1, rx=90.0, ry=90.0, use_group_center=False))
p2 = P_(sxf(geo=P1, rx=90.0, ry=90.0, use_group_center=False, rotate_order="zyx"))
check("Rotate Order xyz: (0,0,1) with rx=ry=90 -> (0,-1,0); zyx differs", close(p_[1], [0, -1, 0]) and
      not close(p2[1], [0, -1, 0], 1e-3))
GB = build.box((1, 2, 3), (0.3, -0.2, 0.5), (2, 2, 2))
prm = dict(tx=0.4, ty=-1.0, tz=2.0, rx=20.0, ry=-35.0, rz=50.0, sx=1.5, sy=0.7, sz=2.0)
allok = True
for xo in ("srt", "str", "rst", "rts", "tsr", "trs"):
    for ro in ("xyz", "xzy", "yxz", "yzx", "zxy", "zyx"):
        a = P_(sxf(geo=GB, use_group_center=False, pivot_x=0.2, pivot_y=0.1, pivot_z=-0.3,
                   xform_order=xo, rotate_order=ro, shear_xy=0.3, shear_xz=-0.2, shear_yz=0.5,
                   prx=10.0, pry=20.0, prz=-30.0, normals="none", **prm))
        b = xform_ref(GB, xform_order=xo, rotate_order=ro, shear_xy=0.3, shear_xz=-0.2,
                      shear_yz=0.5, px=0.2, py=0.1, pz=-0.3, prx=10.0, pry=20.0, prz=-30.0, **prm)
        allok &= close(a, b, 2e-5)
check("36 Transform Order x Rotate Order combinations (with shear, pivot, Pivot Rotate) = Transform node", allok)
a = P_(sxf(geo=GB, use_group_center=False, pivot_x=0.2, prx=40.0, normals="none", **prm))
check("negative control: Pivot Rotate changes the result (with non-uniform scale)", not close(
    a, P_(sxf(geo=GB, use_group_center=False, pivot_x=0.2, normals="none", **prm)), 1e-3))
a = P_(sxf(geo=GB, use_group_center=False, pivot_x=0.2, normals="none", **prm))
check("negative control: the extra path and the old path agree at defaults (SRT / xyz compared directly with the Transform node)",
      close(a, xform_ref(GB, px=0.2, **prm), 2e-5))
check("Pivot Rotate alone non-zero, everything else identity: no movement", close(P_(sxf(geo=GB, prx=30.0)), P_(GB)))

sec("Soft Transform: shear interpolated by weight / Soft Type / Metric")
LY = polyline([[k, 1, 0] for k in range(11)])
p_ = P_(sxf(geo=LY, group="0", radius=10.0, soft_type="linear", shear_xy=2.0,
            use_group_center=False))
check("Shear xy=2 × w:x' = x + 2·w·y(w = 1 − x/10)", close(p_[:, 0], np.arange(11) + 2 * (1 - T10)) and
      close(p_[:, 1], 1.0))
p_ = P_(sxf(geo=LY, group="0", radius=10.0, soft_type="quadratic", ty=1.0))
check("Soft Type passed through: with Quadratic the y displacement = 1 - t^2", close(p_[:, 1] - 1, 1 - T10 ** 2))
check("negative control: default ramp (0:0 1:1, linear) = 1 - t", close(P_(sxf(geo=LY, group="0", radius=10.0, ty=1.0))[:, 1] - 1,
                                                    1 - T10))
LA = LY.copy()
LA.set(POINT, "dist", np.arange(11)[:, None].astype(np.float32))
p_ = P_(sxf(geo=LA, metric="attribute", soft_type="linear", radius=5.0, ty=1.0))
check("Metric = Attribute, empty group: all points fall off by the attribute distance (not weight 1 for everyone)",
      close(p_[:, 1] - 1, np.clip(1 - np.arange(11) / 5.0, 0, None)))
p_ = P_(sxf(geo=LA, metric="attribute", apply_rolloff=False, ty=0.5, group="2-4"))
check("Apply Rolloff off: attribute value multiplied directly; outside the group no movement", close(p_[:, 1] - 1, np.where(
    (np.arange(11) >= 2) & (np.arange(11) <= 4), 0.5 * np.arange(11), 0)))
a = P_(sxf(geo=LY, group="0", radius=10.0, sx=2.0, ty=1.0, tz=0.5, use_group_center=False,
           pivot_x=3.0))
b = P_(sxf(geo=LY, group="0", radius=10.0, sx=2.0, ty=1.0, tz=0.5, use_group_center=False,
           pivot_x=3.0, rotate_order="zyx"))
check("with weights the general matrix path (Rotate Order switched to zyx, no rotation) = the old path: scale lerp(1,s,w), translation x w",
      close(a, b, 1e-5) and close(a[:, 0], 3 + (np.arange(11) - 3) * (1 + (1 - T10))) and
      close(a[:, 1] - 1, 1 - T10) and close(a[:, 2], 0.5 * (1 - T10)))
LA.set(POINT, "d2", (10 - np.arange(11))[:, None].astype(np.float32))
p_ = P_(sxf(geo=LA, metric="attribute", soft_type="linear", radius=10.0, ty=1.0,
            distance_attribute="d2"))
check("Distance Attribute renamed d2 passed through", close(p_[:, 1] - 1, T10))
p_ = P_(sxf(geo=LY, group="0", radius=10.0, soft_type="metaball", kernel="hart", ty=1.0))
check("Metaball Hart passed through", close(p_[5, 1] - 1, 0.5))
p_ = P_(sxf(geo=LY, group="0", radius=10.0, soft_type="cubic", tangent_far=45.0, ty=1.0))
check("Cubic tangents passed through (far / near not swapped)", close(p_[:, 1] - 1, 3 * u ** 2 - 2 * u ** 3 +
                                                (u ** 3 - 2 * u ** 2 + u), 1e-5))

sec("Soft Transform: normals")
GN2 = G4.copy()
P4b = P_(G4)
GN2 = ops.compute_normals(GN2, "point")
GN2.set(POINT, "N", A_(GN2, "N") * 2.0)
o = sxf(geo=GN2, rx=90.0)
check("jacobian (old): N transformed and normalized", close(A_(o, "N"), [0, 0, 1], 1e-5))
o = sxf(geo=GN2, rx=90.0, preserve_normal_length=True)
check("Preserve Normal Length: length stays 2", close(A_(o, "N"), [0, 0, 2], 1e-5))
GV2 = ops.compute_normals(G4, "vertex")
GV2.set(POINT, "N", np.tile(np.float32([1, 0, 0]), (16, 1)))
o = sxf(geo=GV2, group="0", radius=1.5, ty=1.0, normals="recompute_point")
ref = A_(ops.compute_normals(with_P(G4, P_(o)), "point"), "N")
check("Recompute Point Normals: vertex N deleted, all point N recomputed", not o.has(VERTEX, "N") and
      close(A_(o, "N"), ref, 1e-5))
GP2 = G4.copy()
GP2.set(POINT, "N", np.tile(np.float32([1, 0, 0]), (16, 1)))
o = sxf(geo=GP2, group="0", radius=0.5, ty=1.0, normals="recompute_affected")
ref = A_(ops.compute_normals(o, "point"), "N")
check("Recompute Affected Normals: only the 4 points of the face containing point 0 recomputed, others keep +X",
      close(A_(o, "N")[[0, 1, 4, 5]], ref[[0, 1, 4, 5]]) and
      close(np.delete(A_(o, "N"), [0, 1, 4, 5], 0), [1, 0, 0]))
o = sxf(geo=GP2, group="0", radius=0.5, ty=1.0, normals="none")
check("negative control: none leaves N alone", close(A_(o, "N"), [1, 0, 0]))
check("without N, recompute_point does not add N", not sxf(geo=G4, ty=1.0, group="0",
                                                normals="recompute_point").has(POINT, "N"))
check("invalid Transform Order / Rotate Order / Normals raises",
      raises(lambda: sxf(geo=G4, xform_order="x"), "Transform Order") and
      raises(lambda: sxf(geo=G4, rotate_order="x"), "Rotate Order") and
      raises(lambda: sxf(geo=G4, normals="x"), "Normals"))
panel_ok("PCG_SoftTransform")


# ═══════════════════════════════════════════════════════════ Twist(PCG_Deform)
sec("Twist (PCG_Deform): default regression")
golden_check("dfm_", GOLDEN)

sec("Twist:Pivot")
L2 = polyline([[2, 0, 0], [2, 1, 0]])
p0 = P_(run("PCG_Deform", geo=L2, op="twist", axis="y", angle=180.0, normals="none"))
p1 = P_(run("PCG_Deform", geo=L2, op="twist", axis="y", angle=180.0, normals="none",
            pivot_x=1.0))
check("negative control: without Pivot, rotating 180 deg about the world Y axis -> top point (-2,1,0)", close(p0[1], [-2, 1, 0], 1e-5))
check("Pivot (1,0,0): rotates about the axis through the pivot -> top point (0,1,0), bottom point unchanged",
      close(p1[1], [0, 1, 0], 1e-5) and close(p1[0], [2, 0, 0], 1e-6))
PV = np.array([0.7, -0.4, 1.3])
allok = True
for op_ in ("twist", "bend", "taper", "squash", "shear"):
    for ur in (False, True):
        kw = dict(op=op_, axis="y", angle=70.0, amount=0.6, shear_b=0.3, shear_c=-0.2,
                  up_x=1.0, up_y=0.0, use_range=ur, range_start=-0.3, range_end=0.8)
        a = run("PCG_Deform", geo=TUBE, pivot_x=PV[0], pivot_y=PV[1], pivot_z=PV[2], **kw)
        sh = with_P(TUBE, P_(TUBE) - PV)
        kw2 = dict(kw, range_start=-0.3 - PV[1], range_end=0.8 - PV[1])
        b = run("PCG_Deform", geo=sh, **kw2)
        allok &= close(P_(a), P_(b) + PV, 1e-5) and close(A_(a, "N"), A_(b, "N"), 1e-4)
check("5 ops x automatic / manual range: Pivot = translate into pivot coordinates, deform, translate back (P and Jacobian normals both correct)", allok)
a = run("PCG_Deform", geo=TUBE, op="bend", axis="y", angle=70.0, up_x=1.0, up_y=0.0, pivot_y=5.0)
b = run("PCG_Deform", geo=TUBE, op="bend", axis="y", angle=70.0, up_x=1.0, up_y=0.0)
check("the Pivot component along the main axis has no effect (the range is converted accordingly)", close(P_(a), P_(b), 1e-5))
panel_ok("PCG_Deform")


# ═══════════════════════════════════════════════════════════ Edge Transport
def et(geo=ETL, **kw):
    base = dict(geo=geo, attribute="a", method="curves")
    base.update(kw)
    return run("PCG_EdgeTransport", **base)


def etv(name="a", **kw):
    return A_(et(**kw), name)[:, 0]


sec("Edge Transport: default regression / menus")
golden_check("et_", GOLDEN)
check("Operation menu: the old four items unchanged, Houdini's five modes appended at the end", opts("PCG_EdgeTransport", "operation") ==
      ["distance", "copy", "sum", "average", "transport", "transport_from_root", "total",
       "maximum", "minimum"])
check("Method menu has parent_attribute appended at the end", opts("PCG_EdgeTransport", "method") ==
      ["network", "curves", "parent_attribute"])

sec("Edge Transport: Operation (polyline x = 0,1,3,6; a = 10,20,30,40)")
check("Transport + Zero: takes the parent's original value, root 0 -> [0,10,20,30]", close(etv(operation="transport"),
                                                                [0, 10, 20, 30]))
check("Transport + Hold: root kept -> [10,10,20,30]", close(etv(operation="transport",
                                                          new_root_value="hold"), [10, 10, 20, 30]))
check("Transport from Root + Hold: all equal to the root's value 10", close(etv(operation="transport_from_root",
                                                           new_root_value="hold"), 10))
check("Transport from Root + Zero: all 0", close(etv(operation="transport_from_root"), 0))
check("Total: sum of ancestors excluding self -> [0,10,30,60]", close(etv(operation="total"), [0, 10, 30, 60]))
check("negative control: the old sum includes self -> [10,30,60,100]", close(etv(operation="sum"), [10, 30, 60, 100]))
check("Total + Integrate: edge count [0,1,2,3]", close(etv(operation="total", integrate_constant=True),
                                               [0, 1, 2, 3]))
check("Total + Integrate + Scale by Edge Length: distance along the line [0,1,3,6]", close(etv(
    operation="total", integrate_constant=True, scale_by_edge_length=True), [0, 1, 3, 6]))
check("Total + Scale (no Integrate): [0, 10·1, 10+20·2, 50+30·3]", close(etv(
    operation="total", scale_by_edge_length=True), [0, 10, 50, 140]))
EM = ETL.copy()
EM.set(POINT, "a", np.float32([[5], [1], [7], [3]]))
check("Maximum:[5,5,7,7]", close(etv(geo=EM, operation="maximum"), [5, 5, 7, 7]))
check("Minimum:[5,1,1,1]", close(etv(geo=EM, operation="minimum"), [5, 1, 1, 1]))
check("with Integrate a missing attribute is created (written under the Attribute name)", close(etv(
    name="cnt", attribute="cnt", operation="total", integrate_constant=True), [0, 1, 2, 3]))
check("without Integrate, missing attribute: raises", raises(lambda: et(attribute="nope", operation="total"),
                                             "nope"))

check("Total + Hold: root is still 0 (New Root Value only applies to the two Transport modes)", close(etv(
    operation="total", new_root_value="hold"), [0, 10, 30, 60]))
check("Integrate only applies to Total: Transport with Integrate on still uses the attribute value", close(etv(
    operation="transport", integrate_constant=True), [0, 10, 20, 30]))
E64 = ETL.copy()
E64.set(POINT, "a", np.float64([[10], [20], [30], [40]]))
check("float attributes keep their precision (float64 in, float64 out)", et(geo=E64, operation="total").get(POINT, "a").dtype
      == np.float64)
sec("Edge Transport:Direction = Backward")
check("Transport backward: tip starts at 0, the rest take the child's original value -> [20,30,40,0]", close(etv(
    operation="transport", direction="backward"), [20, 30, 40, 0]))
check("Transport backward + Hold: tip kept at 40", close(etv(operation="transport", direction="backward",
                                                      new_root_value="hold"), [20, 30, 40, 40]))
check("Transport from Root backward + Hold: all equal to the tip's value 40", close(etv(
    operation="transport_from_root", direction="backward", new_root_value="hold"), 40))
check("Total backward: sum of descendants -> [90,70,40,0]", close(etv(operation="total", direction="backward"),
                                                     [90, 70, 40, 0]))
check("Maximum backward:[7,7,7,3]", close(etv(geo=EM, operation="maximum", direction="backward"),
                                          [7, 7, 7, 3]))
check("Minimum backward:[1,1,3,3]", close(etv(geo=EM, operation="minimum", direction="backward"),
                                          [1, 1, 3, 3]))

check("Total backward + Hold: tip is still 0", close(etv(operation="total", direction="backward",
                                                new_root_value="hold"), [90, 70, 40, 0]))
check("Total backward + Integrate + Scale: distance to the tip [6,5,3,0]", close(etv(
    operation="total", direction="backward", integrate_constant=True, scale_by_edge_length=True),
    [6, 5, 3, 0]))
sec("Edge Transport:Split / Merge(Edge Network)")
# tree: 0 at the origin, two children 1 (1,0,0), 2 (0,0,1); 1 has another child 3 (2,0,0)
ST = Geometry.from_mesh([[0, 0, 0], [1, 0, 0], [0, 0, 1], [2, 0, 0]], [[0, 1, 3], [0, 2]], closed=False)
ST.set(POINT, "a", np.float32([[12], [1], [1], [1]]))
ST.set_group(POINT, "r", np.arange(4) == 0)
stv = lambda **kw: A_(run("PCG_EdgeTransport", geo=ST, attribute="a", method="network",  # noqa: E731
                         root_group="r", **kw), "a")[:, 0]
check("Transport from Root + Hold + Split: 12 split evenly between the two children as 6, point 3 has only one child and is still 6",
      close(stv(operation="transport_from_root", new_root_value="hold", split_method="split"),
            [12, 6, 6, 6]))
check("negative control: with Copy all 12", close(stv(operation="transport_from_root", new_root_value="hold"), 12))
check("Total + Integrate + Split: children (0+1)/2 = 0.5, point 3 0.5+1 = 1.5",
      close(stv(operation="total", integrate_constant=True, split_method="split"), [0, 0.5, 0.5, 1.5]))
check("Transport + Split: children take the parent's original value / number of children -> points 1, 2 get 6, point 3 gets 1",
      close(stv(operation="transport", split_method="split"), [0, 6, 6, 1]))
for mm, want in (("add", 3.0), ("maximum", 2.0), ("minimum", 1.0)):
    check(f"Total backward + Integrate, Merge = {mm}: root = {want} (two branches 1+1 / 0+1)",
          close(stv(operation="total", integrate_constant=True, direction="backward",
                    merge_method=mm)[0], want))

sec("Edge Transport:Normalization")
L2C = Geometry.from_mesh([[0, 0, 0], [1, 0, 0], [3, 0, 0], [0, 0, 5], [4, 0, 5]],
                         [[0, 1, 2], [3, 4]], closed=False)
nv = lambda nm: A_(run("PCG_EdgeTransport", geo=L2C, attribute="d", method="curves",  # noqa: E731
                       operation="total", integrate_constant=True, scale_by_edge_length=True,
                       use_normalization=True, normalization=nm), "d")[:, 0]
check("Per-Component: each line 0-1 on its own -> [0,1/3,1,0,1]", close(nv("per_component"), [0, 1 / 3, 1, 0, 1]))
check("Global: 0-1 over everything (max 4) -> [0,.25,.75,0,1]", close(nv("global"), [0, 0.25, 0.75, 0, 1]))
check("negative control: not enabled -> raw distances", close(A_(run("PCG_EdgeTransport", geo=L2C, attribute="d", method="curves",
                                         operation="total", integrate_constant=True,
                                         scale_by_edge_length=True), "d")[:, 0], [0, 1, 3, 0, 4]))
check("Normalization also applies to the old modes (distance / global)", close(A_(run(
    "PCG_EdgeTransport", geo=L2C, method="curves", use_normalization=True,
    normalization="global"), "transport")[:, 0], [0, 0.25, 0.75, 0, 1]))

L2C.set(POINT, "k", np.float32([[3], [9], [9], [4], [4]]))
check("normalizing a constant block gives 0 (the second line is all 4; after transport_from_root + hold each line is constant)", close(A_(run(
    "PCG_EdgeTransport", geo=L2C, attribute="k", method="curves", operation="transport_from_root",
    new_root_value="hold", use_normalization=True), "k")[:, 0], 0))
check("normalization subtracts the minimum: Maximum [5,5,7,7] global -> [0,0,1,1]", close(etv(
    geo=EM, operation="maximum", use_normalization=True, normalization="global"), [0, 0, 1, 1]))
sec("Edge Transport:Root Choice / Point Group / Curve Group")
NP = Geometry.from_mesh([[0, 0, 0], [1, 0, 0], [2, 0, 0], [0, 0, 5], [1, 0, 5]], [[1, 0, 2], [4, 3]],
                        closed=False)
o = run("PCG_EdgeTransport", geo=NP, method="network", root_choice="first_point")
check("First Point: starts from point 0; in the other piece the lowest point number 3 becomes the new root", close(A_(o, "transport")[:, 0],
      [0, 1, 2, 0, 1]) and A_(o, "transport_root")[:, 0].tolist() == [0, 0, 0, 3, 3])
o = run("PCG_EdgeTransport", geo=NP, method="network", root_choice="last_point")
check("Last Point: starts from point 4; in the other piece the highest, 2, becomes the new root (chain 1-0-2, edge lengths 1 / 2)",
      close(A_(o, "transport")[:, 0], [2, 3, 0, 1, 0]) and A_(o, "transport_root")[:, 0].tolist() == [2, 2, 2, 4, 4])
check("negative control: Root Choice = group without a Root Group raises", raises(lambda: run(
    "PCG_EdgeTransport", geo=NP, method="network"), "Root Group"))
o = run("PCG_EdgeTransport", geo=ETL, method="network", root_group="0", point_group="0 1 3")
check("Point Group '0 1 3': point 2 is not walked -> point 3 cannot be reached either, goes into unreached", close(A_(o, "transport")[:2, 0], [0, 1])
      and np.nonzero(np.asarray(o.groups[POINT]["unreached"]))[0].tolist() == [2, 3])
o = run("PCG_EdgeTransport", geo=NP, method="network", root_choice="first_point", point_group="0-2 4")
check("First Point + Point Group: point 3 outside the group is not processed, point 4 becomes its own root", A_(o, "transport_root")[:, 0].tolist()
      == [0, 0, 0, -1, 4])
L2C.set_group(PRIM, "c2", np.array([False, True]))
o = run("PCG_EdgeTransport", geo=L2C, method="curves", curve_group="c2")
check("Curve Group: only the second line is walked", close(A_(o, "transport")[:, 0], [0, 0, 0, 0, 4]) and
      np.nonzero(np.asarray(o.groups[POINT]["unreached"]))[0].tolist() == [0, 1, 2])

# zero-length edge: chain 0-2-1-3, points 1, 2 coincide. Before the change sorting by distance put point 1 ahead of its parent point 2, sum gave [1,2,4,6]
ZL = Geometry.from_mesh([[0, 0, 0], [1, 0, 0], [1, 0, 0], [2, 0, 0]], [[0, 2, 1, 3]], closed=False)
ZL.set(POINT, "a", np.float32([[1], [2], [3], [4]]))
check("on a zero-length edge the parent still comes before the child: sum = [1,6,4,10]", close(A_(run(
    "PCG_EdgeTransport", geo=ZL, attribute="a", operation="sum", root_group="0"), "a")[:, 0],
    [1, 6, 4, 10]))
sec("Edge Transport:Method = Parent Attribute")
PA = Geometry.from_points([[0, 0, 0], [1, 0, 0], [1, 1, 0], [2, 0, 0], [5, 0, 0], [6, 0, 0],
                           [7, 0, 0], [8, 0, 0]])
PA.set(POINT, "parent", np.int32([[-1], [0], [1], [1], [99], [5], [7], [6]]))
o = run("PCG_EdgeTransport", geo=PA, method="parent_attribute", attribute="c", operation="total",
        integrate_constant=True, scale_by_edge_length=True)
c = A_(o, "c")[:, 0]
check("parent chain 0<-1<-2, 1<-3: distance along the parent chain [0,1,2,2]; out of range 99 / pointing at itself -> root 0",
      close(c[:6], [0, 1, 2, 2, 0, 0]))
check("the cycle 6 <-> 7 cannot be reached -> unreached", np.nonzero(np.asarray(o.groups[POINT]["unreached"]))[0].tolist()
      == [6, 7])
o = run("PCG_EdgeTransport", geo=PA, method="parent_attribute", attribute="c", operation="total",
        integrate_constant=True, point_group="0 1 3")
check("Point Group: point 2 not in the group, not processed; point 3 still hangs under 1", close(A_(o, "c")[[0, 1, 3], 0], [0, 1, 2]) and
      2 in np.nonzero(np.asarray(o.groups[POINT]["unreached"]))[0].tolist())
o = run("PCG_EdgeTransport", geo=PA, method="parent_attribute", attribute="c", operation="total",
        integrate_constant=True, point_group="0 2 3")
check("Point Group '0 2 3': parent 1 not in the group -> 2, 3 become their own roots (value 0, processed)",
      close(A_(o, "c")[[0, 2, 3], 0], 0) and
      np.nonzero(np.asarray(o.groups[POINT]["unreached"]))[0].tolist() == [1, 4, 5, 6, 7])
o = run("PCG_EdgeTransport", geo=PA, method="parent_attribute", attribute="c", operation="total",
        integrate_constant=True, scale_by_edge_length=True, use_normalization=True)
check("Parent Attribute + Per-Component: blocks by tree (the tree of point 0 [0,.5,1,1])",
      close(A_(o, "c")[:4, 0], [0, 0.5, 1, 1]))
PA2 = PA.copy()
PA2.set(POINT, "par2", np.int32([[3], [3], [1], [-1], [0], [0], [0], [0]]))
check("Parent Attribute renamed par2", close(A_(run(
    "PCG_EdgeTransport", geo=PA2, method="parent_attribute", parent_attribute="par2", attribute="c",
    operation="total", integrate_constant=True), "c")[[3, 0, 1, 2], 0], [0, 1, 1, 2]))
check("Parent Attribute is not an integer attribute: raises", raises(lambda: run(
    "PCG_EdgeTransport", geo=PA, method="parent_attribute", parent_attribute="P"), "integer point attribute"))
# the recipe from the docs: write point numbers into parent, Edge Network + Transport + Hold -> each point gets its parent's point number (integer kept)
RC = ETL.copy()
RC.set(POINT, "parent", np.arange(4, dtype=np.int32)[:, None])
o = run("PCG_EdgeTransport", geo=RC, method="network", root_group="0", attribute="parent",
        operation="transport", new_root_value="hold")
check("recipe: Transport + Hold turns point numbers into parent numbers [0,0,1,2], type still integer",
      A_(o, "parent")[:, 0].tolist() == [0, 0, 1, 2] and o.get(POINT, "parent").dtype.kind == "i")
check("invalid Direction / Split / Merge / Root Choice raises", all(raises(lambda kw=kw: et(**kw), "must be one of")
      for kw in ({"direction": "x"}, {"split_method": "x"}, {"merge_method": "x"},
                 {"root_choice": "x"}, {"new_root_value": "x"})))
panel_ok("PCG_EdgeTransport")


# ═══════════════════════════════════════════════════════════ Find Shortest Path
def fsp(**kw):
    return run_all("PCG_FindShortestPath", **kw)


def srcpaths(g):
    if g.nprims == 0:
        return []
    sp = A_(g, "srcpt")[:, 0].astype(int)
    return [sp[g.prim_points(k)].tolist() for k in range(g.nprims)]


sec("Find Shortest Path: default regression / menus")
golden_check("fsp_", GOLDEN)
check("Output Paths menu: the old three items unchanged, three modes appended at the end", opts("PCG_FindShortestPath", "mode") ==
      ["nearest_end", "each_pair", "sequence", "any_to_any", "any_start_to_each_end", "corresponding"])

sec("Find Shortest Path: Output Paths (5x5 grid, edge length 1; point number = row x 5 + column)")
g_, r_ = fsp(geo=FG, start_group="0 1", end_group="23 4", mode="any_to_any")
check("From Any Start to Any End: only one path, 1 -> 4 cost 3", g_.nprims == 1 and
      srcpaths(g_)[0][0] == 1 and srcpaths(g_)[0][-1] == 4 and close(A_(g_, "cost", PRIM), [3]))
g_, r_ = fsp(geo=FG, start_group="0 4", end_group="20 9", mode="any_start_to_each_end")
check("From Any Start to Each End: one path per end point, 20 comes from 0 (4), 9 from 4 (1)",
      A_(g_, "endpt", PRIM)[:, 0].tolist() == [20, 9] and
      A_(g_, "startpt", PRIM)[:, 0].tolist() == [0, 4] and close(A_(g_, "cost", PRIM)[:, 0], [4, 1]))
check("path direction: from start to end", [p[0] for p in srcpaths(g_)] == [0, 4] and
      [p[-1] for p in srcpaths(g_)] == [20, 9])
g_, r_ = fsp(geo=FG, start_group="0 4", end_group="24 20", mode="corresponding")
check("From Each Start to Corresponding End: 0->24, 4->20, cost 8 each",
      A_(g_, "startpt", PRIM)[:, 0].tolist() == [0, 4] and A_(g_, "endpt", PRIM)[:, 0].tolist() == [24, 20]
      and close(A_(g_, "cost", PRIM)[:, 0], [8, 8]))
check("negative control: each_pair gives 4 paths", fsp(geo=FG, start_group="0 4", end_group="24 20",
                                   mode="each_pair")[0].nprims == 4)
check("negative control: nearest_end (= From Each Start to Any End) gives 2 paths", fsp(
    geo=FG, start_group="0 4", end_group="24 20")[0].nprims == 2)
check("corresponding with unequal counts raises", raises(lambda: fsp(geo=FG, start_group="0 4", end_group="24",
                                                     mode="corresponding"), "end count"))
GU = Geometry.from_mesh([[0, 0, 0], [1, 0, 0], [5, 0, 0]], [[0, 1]], closed=False)
g_, r_ = fsp(geo=GU, start_group="0", end_group="2", mode="any_to_any")
check("any_to_any unreachable: no path output", g_.nprims == 0)

sec("Find Shortest Path:Max Search Path Cost")
g_, r_ = fsp(geo=FG, start_group="0", end_group="1 24", mode="each_pair", use_max_cost=True,
             max_cost=5.0)
check("Max 5: 0->1 (1) kept, 0->24 (8) counts as unreachable", A_(g_, "endpt", PRIM)[:, 0].tolist() == [1])
check("negative control: not enabled, two paths", fsp(geo=FG, start_group="0", end_group="1 24", mode="each_pair",
                            max_cost=5.0)[0].nprims == 2)
check("Max exactly equal to the cost: kept (only > counts as exceeding)", fsp(geo=FG, start_group="0", end_group="24",
                                         use_max_cost=True, max_cost=8.0)[0].nprims == 1)

sec("Find Shortest Path: Point / Primitive Cost, Omit Distance")
# 0 (0,0,0) -> 1 (1,0,0): direct (prim 0, length 1) or around via 2 (0.5,0,1) (prim 1, length 2·sqrt(1.25)); prim 2 duplicates the direct edge
D2 = 2 * np.sqrt(1.25)
TRI = Geometry.from_mesh([[0, 0, 0], [1, 0, 0], [0.5, 0, 1]], [[0, 1], [0, 2, 1], [0, 1]], closed=False)
TRI.set(PRIM, "pc", np.float32([[5], [0], [0]]))
cost1 = lambda **kw: float(A_(fsp(geo=TRI, start_group="0", end_group="1", **kw)[0], "cost", PRIM)[0, 0])  # noqa: E731
check("negative control: no cost attribute -> direct, cost 1", close(cost1(), 1.0))
check("Primitive Cost: the direct edge takes the lowest-numbered prim 0 (cost 5) -> detour 2·sqrt(1.25)",
      close(cost1(prim_cost_attribute="pc"), D2, 1e-5))
TRI.set(POINT, "ptc", np.float32([[100], [0], [0.5]]))
check("Point Cost: entering point 2 adds 0.5; the start point 0's 100 is not added", close(
    cost1(prim_cost_attribute="pc", point_cost_attribute="ptc"), D2 + 0.5, 1e-5))
check("Omit Distance: only the cost attribute remains -> detour cost 0 (direct 5)", close(
    cost1(prim_cost_attribute="pc", omit_distance=True), 0.0))
check("Primitive Cost takes the lowest number only within Surface Primitives: with group '1 2' the direct edge takes prim 2 (0) -> direct 1",
      close(cost1(prim_cost_attribute="pc", surface_prims="1 2"), 1.0))
check("Omit Distance alone (no cost attribute): all edges 0 -> cost 0", close(cost1(omit_distance=True), 0.0))
TRI.set(POINT, "neg", np.float32([[0], [-5], [0]]))
check("negative Point Cost raises", raises(lambda: cost1(point_cost_attribute="neg"), "cost < 0"))

sec("Find Shortest Path:Surface Primitives / Directed Primitives / Edges to Avoid")
check("Surface Primitives '1': can only use prim 1's edges -> detour", close(cost1(surface_prims="1"), D2, 1e-5))
DI = Geometry.from_mesh([[0, 0, 0], [1, 0, 0], [0.5, 0, 1]], [[0, 1], [1, 2, 0]], closed=False)
DI.set_edge_group("direct", [(0, 1)])
DI.set_group(PRIM, "d", np.array([False, True]))
f01 = lambda **kw: fsp(geo=DI, edges_to_avoid="direct", directed_prims="d", **kw)[0]  # noqa: E731
check("Directed + avoiding the direct edge: 0->1 against prim 1 (1->2->0) is unreachable", f01(start_group="0", end_group="1").nprims == 0)
g_ = f01(start_group="1", end_group="0")
check("1->0 following the direction: path [1,2,0]", srcpaths(g_) == [[1, 2, 0]])
g_ = f01(start_group="1", end_group="0", mode="each_pair")
check("each_pair also follows the direction", srcpaths(g_) == [[1, 2, 0]])
check("any_start_to_each_end also respects direction: 0->1 unreachable, 1->0 reachable",
      f01(start_group="0", end_group="1", mode="any_start_to_each_end").nprims == 0 and
      srcpaths(f01(start_group="1", end_group="0", mode="any_start_to_each_end")) == [[1, 2, 0]])
check("negative control: not avoiding the direct edge (undirected prim 0) -> 0->1 direct", srcpaths(fsp(
    geo=DI, directed_prims="d", start_group="0", end_group="1")[0]) == [[0, 1]])
check("negative control: undirected -> 0->1 detour [0,2,1]", srcpaths(fsp(
    geo=DI, edges_to_avoid="direct", start_group="0", end_group="1")[0]) == [[0, 2, 1]])
DI2 = Geometry.from_mesh([[0, 0, 0], [1, 0, 0], [0.5, 0, 1]], [[1, 2, 0], [0, 2]], closed=False)
DI2.set_group(PRIM, "d", np.array([True, False]))
check("an edge that is also in an undirected prim: both directions allowed (0->2 via prim 1)", srcpaths(fsp(
    geo=DI2, directed_prims="d", start_group="0", end_group="1")[0]) == [] and srcpaths(fsp(
        geo=DI2, directed_prims="d", start_group="0", end_group="2")[0]) == [[0, 2]])
check("nonexistent Edges to Avoid group name raises", raises(lambda: fsp(geo=DI, start_group="0", end_group="1",
                                                       edges_to_avoid="nope"), "nope"))
panel_ok("PCG_FindShortestPath")


# ═══════════════════════════════════════════════════════════ Group Find Path
def gfp(**kw):
    return run("PCG_GroupFindPath", geo=FG, **kw)


def gedges(g, name="path"):
    return sorted(map(tuple, np.sort(np.asarray(g.edge_groups[name]), 1).tolist()))


def gpts(g, name="path"):
    return np.nonzero(np.asarray(g.groups[POINT][name]))[0].tolist()


sec("Group Find Path: default regression / menus")
golden_check("gfp_", GOLDEN)
check("Path Type menu has start_end_pairs appended at the end", opts("PCG_GroupFindPath", "mode") ==
      ["shortest_path", "boundary_loop", "start_end_pairs"])

sec("Group Find Path:Paths between Start/End Pairs")
g_ = gfp(points="0 4 20 24", mode="start_end_pairs")
check("two pairs: 0->4 (row 0), 20->24 (row 4), 8 edges in total", gpts(g_) == [0, 1, 2, 3, 4, 20, 21, 22, 23, 24]
      and len(gedges(g_)) == 8)
check("negative control: shortest_path also connects 4 -> 20 (extra points outside rows 0 / 4)",
      bool(set(gpts(gfp(points="0 4 20 24"))) - {0, 1, 2, 3, 4, 20, 21, 22, 23, 24}))
check("odd number of points raises", raises(lambda: gfp(points="0 4 20", mode="start_end_pairs"), "even number"))
g_ = gfp(points="0 24", mode="start_end_pairs", close=True, avoid_self_intersection=True)
E_ = gedges(g_)
deg = np.bincount(np.asarray(E_).reshape(-1), minlength=25)
check("Pairs + Close + Avoid: one pair forms a loop (16 edges, every point degree 2)", len(E_) == 16 and
      set(deg[deg > 0].tolist()) == {2})

sec("Group Find Path:Avoid Self Intersection / Close Path")
g_ = gfp(points="0 24", close=True, avoid_self_intersection=True)
E_ = gedges(g_)
deg = np.bincount(np.asarray(E_).reshape(-1), minlength=25)
check("two points + Close + Avoid: the return avoids the outward path -> one loop (16 edges, all degree 2)", len(E_) == 16 and
      set(deg[deg > 0].tolist()) == {2})
check("negative control: without Avoid two points do not close (old behaviour), 8 edges", len(gedges(gfp(points="0 24", close=True))) == 8)
# 0 -> 12 -> 4: the interior points of the first segment must not be passed again by the second
seg1 = run_all("PCG_FindShortestPath", geo=FG, start_group="0", end_group="12", mode="each_pair")[0]
inner1 = sorted(set(A_(seg1, "srcpt")[:, 0].astype(int).tolist()) - {0, 12})
seg2 = run_all("PCG_FindShortestPath", geo=FG, start_group="12", end_group="4", mode="each_pair")[0]
inner2 = set(A_(seg2, "srcpt")[:, 0].astype(int).tolist())
g2 = gfp(points="0 12 4", avoid_self_intersection=True)
deg = np.bincount(np.asarray(gedges(g2)).reshape(-1), minlength=25)
check("premise: without avoiding, the second segment's shortest path really passes through the first segment's interior points", bool(inner2 & set(inner1)), (inner1, inner2))
check("Avoid: the first segment's interior points are only on the first segment (degree 2), the second detours; total edges 8 + 4 = 12 or more",
      all(deg[p] == 2 for p in inner1) and len(gedges(g2)) >= 8)
check("negative control: without Avoid some interior point has degree > 2 or edges overlap", any(
    np.bincount(np.asarray(gedges(gfp(points="0 12 4"))).reshape(-1), minlength=25)[p] != 2
    for p in inner1))
g_, r_ = run_all("PCG_GroupFindPath", geo=FG, points="0 4 2", avoid_self_intersection=True)
check("a segment blocked by the previous one detours: 0->4 takes row 0, 4->2 has to go around (still reachable)", len(gedges(g_)) > 4)

check("negative control: Pairs without Avoid, the second pair 1->3 runs along row 0 (overlapping the first pair), 4 edges in total",
      len(gedges(gfp(points="0 4 1 3", mode="start_end_pairs"))) == 4)
check("Pairs + Avoid: the second pair detours around point 2 -> 1->6->7->8->3, 8 edges in total",
      len(gedges(gfp(points="0 4 1 3", mode="start_end_pairs", avoid_self_intersection=True))) == 8)

sec("Group Find Path:Collision Group")
g_ = gfp(points="10 14", collision_group="11-13")
check("Collision '11-13': detours around the middle of row 2 -> 6 edges, not passing 11-13", len(gedges(g_)) == 6 and
      not (set(gpts(g_)) & {11, 12, 13}))
check("negative control: without Collision -> straight, 4 edges", len(gedges(gfp(points="10 14"))) == 4)
g_ = gfp(points="10 14", collision_group="10-14")
check("end points inside Collision still count as end points: detours around 11-13", len(gedges(g_)) == 6)
g_ = gfp(points="10 14", collision_group="0-9 10 14", contain_within_collision=True)
check("Contain within: only rows 0, 1 + the two ends -> via row 1, 6 edges", len(gedges(g_)) == 6 and
      set(gpts(g_)) == {10, 5, 6, 7, 8, 9, 14})
g_, r_ = run_all("PCG_GroupFindPath", geo=FG, points="0 24", collision_group="10-14")
check("whole row blocked: unreachable, no edges and no points written", len(gedges(g_)) == 0 and gpts(g_) == [])
panel_ok("PCG_GroupFindPath")

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
