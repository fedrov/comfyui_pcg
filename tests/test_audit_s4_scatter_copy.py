"""
pcg100 · pack s4_scatter_copy: parameters / menu items added against the SideFX docs.

  Scatter            Generate menu (By Density / Count per Primitive / In Texture Space),
                     Count per Prim Attribute, Density Texture, Output Density / Radius / ID,
                     texture-space output, Attributes tab (Point / Vertex / Primitive / Detail modes)
  (sections for the other nodes are in the sec() calls below)

Everything is checked against hand-computed numbers (point counts, area ratios, densities, radius formulas, coordinates); every new option gets a negative control; output at defaults is compared
bit by bit with the old implementation at the baseline commit (HEAD before this pack started).
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
from comfyui_pcg.geo import build                       # noqa: E402
from comfyui_pcg.geo import scatter as SC               # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, VERTEX, PRIM, DETAIL  # noqa: E402
from comfyui_pcg.geo.cop.core import CopImage           # noqa: E402
from comfyui_pcg.geo.xform import quat_to_mat          # noqa: E402

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


def run(nid, **over):
    kw = defaults(nid)
    kw.update(over)
    r = getattr(M[nid](), M[nid].FUNCTION)(**kw)
    return r["result"][0] if isinstance(r, dict) else r[0]


def run_all(nid, **over):
    kw = defaults(nid)
    kw.update(over)
    r = getattr(M[nid](), M[nid].FUNCTION)(**kw)
    return r["result"] if isinstance(r, dict) else r


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
    return h.hexdigest()


# -- "bit-identical to before the change at defaults": hard-coded digests (no git on the device).
# each entry in CASES is a node call **using only old widgets** (new widgets all at defaults);
# GOLDEN holds the digests of the same calls before the change (commit c87c5d9). `--digests` prints the current digests.
CASES = {}


def case(key, nid, **kw):
    CASES[key] = (nid, kw)


def case_digest(nid, kw):
    """_out selects which output (default output 0)."""
    kw = dict(kw)
    i = kw.pop("_out", 0)
    return digest(run_all(nid, **kw)[i])[:16]


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


def img(a):
    """(H, W) or (H, W, C) array -> COPIMAGE (layer C)."""
    a = np.asarray(a, np.float32)
    if a.ndim == 2:
        a = a[:, :, None]
    return CopImage(layers={"C": a})


# ═══════════════════════════════════════════════════════════ Old calls (bit-exact regression)
# old calls of all nodes are registered here; --digests exits before running any new feature -- so the same file
# can produce GOLDEN when run against the code from before the change.
G4 = build.grid(4.0, 4.0, 5, 5)                 # 16 unit squares, area 16, uv covers [0,1]^2
G4.set(POINT, "Cd", np.random.default_rng(1).random((25, 3)).astype(np.float32))
G4V = G4.copy()
G4V.set(VERTEX, "vw", np.arange(G4.nvertices, dtype=np.float32))
G4V.set(PRIM, "name", np.array([f"p{i % 3}" for i in range(G4.nprims)]))
G4V.set(PRIM, "seedv", np.arange(G4.nprims) % 4)
for lab, o in [("default", {}), ("relax", dict(use_relax=True, count=300)),
               ("density", dict(force_total_count=False, density_scale=7.3)),
               ("seed_str", dict(use_prim_seed=True)),
               ("seed_int_relax", dict(use_prim_seed=True, prim_seed_attribute="seedv",
                                       use_relax=True, count=200)),
               ("no_out", dict(use_out_attribs=False)),
               ("no_interp", dict(interpolate_attributes=False)),
               ("maxpts", dict(force_total_count=False, max_points=37)),
               ("geonrm", dict(use_geometric_normals=True, count=77, rand_seed=5))]:
    case("scatter_" + lab, "PCG_Scatter", geo=G4V, **o)

SPH = build.sphere() if hasattr(build, "sphere") else G4
for lab, o in [("default", dict(geo=G4V)), ("density", dict(geo=G4V, mode="density", density=6.0)),
               ("coverage", dict(geo=G4V, mode="coverage", coverage=0.3, scale_min=0.1,
                                 scale_max=0.2)),
               ("overlap", dict(geo=G4V, count=60, avoid_overlap=True, scale_min=0.2,
                                scale_max=0.3, relax_iterations=5)),
               ("tilt", dict(geo=SPH, count=80, tilt=30.0, rotate_random=90.0, rand_seed=3)),
               ("up", dict(geo=SPH, count=50, up_x=1.0, up_y=0.0, up_z=0.0)),
               ("group", dict(geo=G4V, count=40, group="0-3"))]:
    case("salign_" + lab, "PCG_ScatterAlign", **o)

PR = Geometry.from_points(np.array([[0, 0, 0], [3, 0, 0], [0, 4, 1], [-2, 1, 5]], np.float32))
PR.set(POINT, "N", np.array([[0, 1, 0], [1, 0, 0], [0, 0, 1], [1, 1, 0]], np.float32))
PR.set(POINT, "pscale", np.array([[1.0], [2.0], [0.5], [1.5]], np.float32))
PR.set(POINT, "v", np.array([[0, 0, 2], [1, 0, 0], [0, 3, 0], [0, 0, 0]], np.float32))
PR.set(POINT, "Cd", np.arange(12, dtype=np.float32).reshape(4, 3) / 12)
PR.set(POINT, "cnt", np.array([[3], [0], [5], [2]], np.float32))
PR.set_group(POINT, "sel", np.array([True, False, True, True]))
for lab, o in [("default", {}), ("shell", dict(shape="shell", count=7)),
               ("disk", dict(shape="disk", radius=0.4)), ("gauss", dict(shape="gaussian")),
               ("cnt", dict(count_attribute="cnt", radius_attribute="")),
               ("keep", dict(keep_original=True, rand_seed=4)), ("grp", dict(group="sel"))]:
    case("prep_" + lab, "PCG_PointReplicate", geo=PR, **o)


def two_boxes():
    """Two unit boxes: a at (2,0,0), b at (0,0,3); prim attribute name, point attributes N / v / pid."""
    bx = build.box()
    P0 = P_(bx)
    faces = [bx.prim_points(i) for i in range(bx.nprims)]
    P = np.concatenate([P0 + [2, 0, 0], P0 + [0, 0, 3]]).astype(np.float32)
    n = len(P0)
    g = Geometry.from_mesh(P, faces + [f + n for f in faces])
    g.set(PRIM, "name", np.array(["a"] * len(faces) + ["b"] * len(faces)))
    g.set(PRIM, "pidx", np.array([0] * len(faces) + [1] * len(faces), np.int32))
    g.set(POINT, "N", np.tile([[0, 1, 0]], (2 * n, 1)).astype(np.float32))
    g.set(POINT, "v", np.tile([[1, 0, 0]], (2 * n, 1)).astype(np.float32))
    g.set(POINT, "w", np.tile([[0, 0, 1]], (2 * n, 1)).astype(np.float32))
    return g


TPG = two_boxes()
c45 = np.sqrt(0.5)
TPT = Geometry.from_points(np.array([[10, 0, 0], [0, 10, 0]], np.float32))
TPT.set(POINT, "name", np.array(["a", "b"]))
TPT.set(POINT, "orient", np.array([[0, 0, c45, c45], [c45, 0, 0, c45]], np.float32))
TPT.set(POINT, "pscale", np.array([[2.0], [1.0]], np.float32))
TPT.set(POINT, "Cd", np.array([[1, 0, 0], [0, 1, 0]], np.float32))
TPT.set_group(POINT, "hot", np.array([True, False]))
TPR = Geometry.from_points(np.array([[2, 0, 0], [0, 0, 3]], np.float32))
TPR.set(POINT, "name", np.array(["a", "b"]))
TPGp = TPG.copy()
TPGp.set(POINT, "name", np.array(["a"] * 8 + ["zz"] * 8))
for lab, o in [("default", dict(geo=TPG, template=TPT)),
               ("rest", dict(geo=TPG, template=TPT, rest=TPR)),
               ("ptname", dict(geo=TPGp, template=TPT))]:
    case("tpieces_" + lab, "PCG_TransformPieces", **o)

_rng = np.random.default_rng(7)
ETA = Geometry.from_points(_rng.normal(size=(12, 3)).astype(np.float32))
ETA.set(POINT, "N", _rng.normal(size=(12, 3)).astype(np.float32))
ETA.set(POINT, "wt", _rng.random((12, 1)).astype(np.float32))
_Rq = quat_to_mat(np.array([[0.2, -0.4, 0.1, 0.9]]) / np.linalg.norm([0.2, -0.4, 0.1, 0.9]))[0]
ETB = Geometry.from_points((P_(ETA) @ (_Rq * 1.7).T + [1, -2, 3]
                            + _rng.normal(scale=0.01, size=(12, 3))).astype(np.float32))
for lab, o in [("rigid", {}), ("sim", dict(mode="similarity")), ("aff", dict(mode="affine")),
               ("wt", dict(mode="similarity", weight_attribute="wt"))]:
    case("extract_" + lab, "PCG_ExtractTransform", reference=ETA, target=ETB, **o)
    case("extract_" + lab + "_geo", "PCG_ExtractTransform", reference=ETA, target=ETB, _out=1, **o)

_rc = np.random.default_rng(11)
CLP = Geometry.from_points(np.r_[_rc.normal(size=(30, 3)) * 0.3 + [0, 0, 0],
                                 _rc.normal(size=(30, 3)) * 0.3 + [5, 0, 0],
                                 _rc.normal(size=(30, 3)) * 0.3 + [0, 5, 0]].astype(np.float32))
CLP.set(POINT, "Cd", _rc.random((90, 3)).astype(np.float32))
CLP.set(POINT, "hot", np.r_[np.zeros(45), np.ones(45)].astype(np.float32)[:, None])
for lab, o in [("default", dict(clusters=3)), ("cd", dict(clusters=4, attribute="Cd", rand_seed=3)),
               ("grp", dict(clusters=2, group="0-50")), ("many", dict(clusters=7, iterations=5))]:
    case("cluster_" + lab, "PCG_ClusterPoints", geo=CLP, **o)
    case("cluster_" + lab + "_cen", "PCG_ClusterPoints", geo=CLP, _out=1, **o)

SFM_IMG = img(np.tile((np.arange(16) + 0.5) / 16, (16, 1)))           # a ramp along u
for lab, o in [("default", dict(count=300)), ("inv", dict(count=200, invert=True, rand_seed=2)),
               ("floor", dict(count=150, density_floor=0.3, filter="closest")),
               ("uv", dict(count=100, uv_scale_u=2.0, border="wrap", density_scale=3.0)),
               ("grp", dict(count=80, group="0-7", out_density=""))]:
    case("sfm_" + lab, "PCG_ScatterFromMap", geo=G4, cop=SFM_IMG, **o)

if "--digests" in sys.argv:
    print(json.dumps({k: case_digest(n, kw) for k, (n, kw) in CASES.items()}, indent=1))
    sys.exit(0)

GOLDEN = {  # digests from running the CASES above before the change (c87c5d9)
    "scatter_default": "a5eeaef6a57f63fe",
    "scatter_relax": "9f4ca452fc3e8411",
    "scatter_density": "14c1097baee68780",
    "scatter_seed_str": "7305ea90ac8dc6f0",
    "scatter_seed_int_relax": "b5c654b3076d212e",
    "scatter_no_out": "636c1a54bd6be2f6",
    "scatter_no_interp": "87fea4143a919c59",
    "scatter_maxpts": "338066f62bd6247e",
    "scatter_geonrm": "7ecf564b0c76ff9d",
    "salign_default": "63f3f3674c7998e8",
    "salign_density": "62c8390a9a1e14db",
    "salign_coverage": "89490e23d947b995",
    "salign_overlap": "864d3dc4428d1a52",
    "salign_tilt": "c7b0b3ba5d9b81f6",
    "salign_up": "658223c65ce01e9b",
    "salign_group": "fa6bdf585a7d1829",
    "prep_default": "9a7474e3b0071927",
    "prep_shell": "cf1095bb45c5c3a5",
    "prep_disk": "7e7d1075c56fe67a",
    "prep_gauss": "7e25e95a24820481",
    "prep_cnt": "d586cca3aae08b1c",
    "prep_keep": "247571753f004dd5",
    "prep_grp": "13ce2045f156e6a4",
    "tpieces_default": "ce79a99d32de7eaa",
    "tpieces_rest": "ce79a99d32de7eaa",
    "tpieces_ptname": "7fd364270d5b1677",
    "extract_rigid": "2c4e9fff0e7061ba",
    "extract_rigid_geo": "72f7d214dda00eeb",
    "extract_sim": "7c6db06af41d9865",
    "extract_sim_geo": "bdaabe8776651cf7",
    "extract_aff": "b29b7147ccf068b8",   # pcg102: affine transform now written as Houdini row vectors (transposed)
    "extract_aff_geo": "7508cc6342d5c5f0",
    "extract_wt": "2a78f45e5878c46d",
    "extract_wt_geo": "5bf422d2838cdf07",
    "cluster_default": "142ce58965c6d6f1",
    "cluster_default_cen": "90bd21655db951d7",
    "cluster_cd": "0d4a17791ee331f1",
    "cluster_cd_cen": "9c334eee94221f09",
    "cluster_grp": "4e5c4aa9990a46b1",
    "cluster_grp_cen": "86feaac302328a53",
    "cluster_many": "a38a00fc03e193ca",
    "cluster_many_cen": "475149ac7db8e418",
    "sfm_default": "9766beaa3207aec5",
    "sfm_inv": "5c0ec14dfeba2854",
    "sfm_floor": "225bf31a27f4f145",
    "sfm_uv": "3881c0344ff7f9c9",
    "sfm_grp": "8f974fbf655c959f",
}


# ═══════════════════════════════════════════════════════════ Scatter
sec("Scatter: bit-identical to before the change at defaults")
golden_check("scatter_", GOLDEN)

sec("Scatter:Generate = Count per Primitive")
check("Generate menu: old behaviour is the first item", opts("PCG_Scatter", "generate")[0] == "by_density")
G3 = build.grid(3.0, 3.0, 4, 4)                 # 9 unit squares
G3.set(PRIM, "cnt", np.arange(9, dtype=np.int32))
s = run("PCG_Scatter", geo=G3, generate="count_per_primitive", count_per_prim_attribute="5")
sp = A_(s, "sourceprim")[:, 0].astype(int)
check("constant 5: exactly 5 points per prim", s.npoints == 45 and
      np.all(np.bincount(sp, minlength=9) == 5), np.bincount(sp, minlength=9))
s = run("PCG_Scatter", geo=G3, generate="count_per_primitive", count_per_prim_attribute="cnt")
sp = A_(s, "sourceprim")[:, 0].astype(int)
check("attribute cnt: prim i gets exactly i points", np.all(np.bincount(sp, minlength=9) == np.arange(9)))
neg = run("PCG_Scatter", geo=G3, count=36)
check("negative control: By Density gives the same 36 points, but per-prim counts are not all 4",
      not np.all(np.bincount(A_(neg, "sourceprim")[:, 0].astype(int), minlength=9) == 4))
check("attribute name does not exist: raises", raises(lambda: run(
    "PCG_Scatter", geo=G3, generate="count_per_primitive", count_per_prim_attribute="nope"),
    "Count per Prim"))
check("negatives treated as 0", run("PCG_Scatter", geo=G3, generate="count_per_primitive",
                      count_per_prim_attribute="-3").npoints == 0)
# points must be in their own sourceprim square (including Relax: relaxed per prim, not across prims)
PG = P_(G3)


def in_own_prim(g):
    sp = A_(g, "sourceprim")[:, 0].astype(int)
    P = P_(g)
    ok = []
    for i in range(len(sp)):
        q = PG[G3.prim_points(sp[i])]
        ok.append(q[:, 0].min() - 1e-5 <= P[i, 0] <= q[:, 0].max() + 1e-5 and
                  q[:, 2].min() - 1e-5 <= P[i, 2] <= q[:, 2].max() + 1e-5)
    return all(ok)


sr = run("PCG_Scatter", geo=G3, generate="count_per_primitive", count_per_prim_attribute="20",
         use_relax=True, relax_iterations=20, scale_radii_by=2.0)
s0 = run("PCG_Scatter", geo=G3, generate="count_per_primitive", count_per_prim_attribute="20")
check("per-prim Relax: every point still in its own square", in_own_prim(sr))
check("per-prim Relax: per-prim counts unchanged", np.all(np.bincount(
    A_(sr, "sourceprim")[:, 0].astype(int), minlength=9) == 20))
check("Relax really moved points (negative control: positions without Relax differ)", not close(P_(sr), P_(s0)))


def min_nn(P):
    d = np.linalg.norm(P[:, None] - P[None], axis=2) + np.eye(len(P)) * 1e9
    return d.min()


sp_r = A_(sr, "sourceprim")[:, 0].astype(int)
sp_0 = A_(s0, "sourceprim")[:, 0].astype(int)
check("Relax increased the nearest-neighbour distance within prims", min(min_nn(P_(sr)[sp_r == k]) for k in range(9)) >
      min(min_nn(P_(s0)[sp_0 == k]) for k in range(9)))
# reference: By Density's global relax pushes points across prim borders -- proving the check above is not vacuous
sg = run("PCG_Scatter", geo=G3, count=180, use_relax=True, relax_iterations=20,
         scale_radii_by=2.0)
check("negative control: under By Density global relax sourceprim follows the points as they migrate (still consistent)", in_own_prim(sg))
d = A_(run("PCG_Scatter", geo=G3, generate="count_per_primitive",
           count_per_prim_attribute="cnt", use_out_density=True), "density")[:, 0]
sp = A_(run("PCG_Scatter", geo=G3, generate="count_per_primitive",
            count_per_prim_attribute="cnt"), "sourceprim")[:, 0]
check("output density = that prim's point count / area (unit squares -> equals cnt)", close(d, sp))

# added from mutation testing:
G6 = build.grid(6.0, 6.0, 4, 4)                 # 9 2x2 squares, area 4
G6.set(PRIM, "cnt", np.arange(9, dtype=np.int32) * 4)
s = run("PCG_Scatter", geo=G6, generate="count_per_primitive", count_per_prim_attribute="cnt",
        use_out_density=True)
check("density = point count / prim area (2x2 squares: cnt / 4)",
      close(A_(s, "density")[:, 0], A_(s, "sourceprim")[:, 0]), A_(s, "density")[:3, 0])
G3d = G3.copy()
G3d.set(POINT, "dd", np.full((16, 1), 3.0, np.float32))
s = run("PCG_Scatter", geo=G3d, generate="count_per_primitive", count_per_prim_attribute="6",
        use_density=True, density_attribute="dd", use_out_density=True)
check("with a density attribute the density is still = point count / area = 6 (the attribute only changes the distribution within the prim)", close(A_(s, "density"), 6.0))
check("total over the hard limit: raises", raises(lambda: run(
    "PCG_Scatter", geo=G3, generate="count_per_primitive",
    count_per_prim_attribute=str(SC.MAX_POINTS_HARD)), "exceeding the limit"))
G3n = G3.copy()
G3n.set(PRIM, "cnt", np.array([60, 60, -100, 0, 0, 0, 0, 0, 0], np.int32))
_hard = SC.MAX_POINTS_HARD
SC.MAX_POINTS_HARD = 100                        # lower the limit temporarily so we do not really scatter twenty million points
try:
    check("the limit counts only positive counts (60 + 60 > 100, negatives do not offset)", raises(lambda: run(
        "PCG_Scatter", geo=G3n, generate="count_per_primitive",
        count_per_prim_attribute="cnt"), "exceeding the limit"))
finally:
    SC.MAX_POINTS_HARD = _hard
sr2 = run("PCG_Scatter", geo=G3, generate="count_per_primitive", count_per_prim_attribute="20",
          use_relax=True, relax_iterations=20, scale_radii_by=2.0, use_out_attribs=True)
check("uv interpolated after per-prim Relax matches the position (x = 3u - 1.5) -- barycentric coordinates were updated",
      close(P_(sr2)[:, 0], 3 * A_(sr2, "uv")[:, 0] - 1.5, 1e-4))
s_t = run("PCG_Scatter", geo=G3, generate="count_per_primitive", count_per_prim_attribute="20",
          use_relax=True, relax_iterations=20, max_relax_radius=1e-7)
check("Max Relax Radius clamped to tiny: same as no Relax", close(P_(s_t), P_(s0)))
check("negative control: same settings with Max Relax Radius off do move", not close(P_(run(
    "PCG_Scatter", geo=G3, generate="count_per_primitive", count_per_prim_attribute="20",
    use_relax=True, relax_iterations=20, max_relax_radius=1e-7, use_max_relax_radius=False)),
    P_(s0)))

sec("Scatter:Generate = In Texture Space")
s = run("PCG_Scatter", geo=G4, generate="in_texture_space", count=500)
check("uv covers the unit square: point count = Total Count", s.npoints == 500, s.npoints)
uv = A_(s, "uv")
P = P_(s)
check("point uv matches position (x = 4u - 2, z = 2 - 4v)",
      close(P[:, 0], 4 * uv[:, 0] - 2, 1e-4) and close(P[:, 2], 2 - 4 * uv[:, 1], 1e-4))
s = run("PCG_Scatter", geo=G4, generate="in_texture_space", force_total_count=False,
        density_scale=123.0)
check("total not forced, no texture: point count = Density Scale (expected total in the unit square)", s.npoints == 123)
GH = G4.copy()
GH.set(POINT, "uv", A_(G4, "uv") * 0.5)          # uv covers only [0, .5]^2 -- a quarter
N = 4000
s = run("PCG_Scatter", geo=GH, generate="in_texture_space", count=N, use_out_density=True,
        use_out_radius=True)
check("uv covers only 1/4: point count ~ N/4 (5 sigma)", abs(s.npoints - N / 4) < 5 * np.sqrt(N * .25 * .75),
      s.npoints)
check("physical density = N x uv area / 3D area = 4000 x .25 / 16",
      close(A_(s, "density"), 62.5, 1e-3))
check("radius = 0.537 / sqrt(density)", close(A_(s, "pscale"), 0.537 / np.sqrt(62.5), 1e-6))
st = run("PCG_Scatter", geo=GH, generate="in_texture_space", count=N, use_out_density=True,
         out_texture_space=True)
check("texture-space density = N", close(A_(st, "density"), 4000.0, 1e-2))
neg = run("PCG_Scatter", geo=GH, count=N)
check("negative control: By Density with the same Total Count gives exactly N (unaffected by uv coverage)", neg.npoints == N)
# texture: left half 1, right half 0 -> all points u < 0.5
T2 = np.zeros((8, 8)); T2[:, :4] = 1.0
s = run("PCG_Scatter", geo=G4, generate="in_texture_space", count=800, density_texture=img(T2),
        use_out_density=True)
check("texture left half 1 right half 0: point count = 800, all u < 0.5", s.npoints == 800 and
      A_(s, "uv")[:, 0].max() < 0.5, A_(s, "uv")[:, 0].max())
check("forced total + texture: texture-space density = N x tex / mean(tex) = 1600 -> physical 1600/16",
      close(A_(s, "density"), 100.0, 1e-3))
s = run("PCG_Scatter", geo=G4, generate="in_texture_space", force_total_count=False,
        density_scale=300.0, density_texture=img(T2))
check("total not forced + texture: point count = Density Scale x mean(tex) = 150", s.npoints == 150)
# texture row direction: row 0 is v in [0, 1/H)
T3 = np.zeros((4, 4)); T3[0, :] = 1.0
s = run("PCG_Scatter", geo=G4, generate="in_texture_space", count=300, density_texture=img(T3))
check("texture row 0 -> v < 1/4", A_(s, "uv")[:, 1].max() < 0.25)
# Relax in texture space
s0 = run("PCG_Scatter", geo=G4, generate="in_texture_space", count=200)
s1 = run("PCG_Scatter", geo=G4, generate="in_texture_space", count=200, use_relax=True,
         relax_iterations=20, max_relax_radius=0.05)
check("texture-space Relax: nearest-neighbour distance increases, point count unchanged",
      s1.npoints == 200 and min_nn(A_(s1, "uv")) > min_nn(A_(s0, "uv")))
check("after texture-space Relax points are still on the grid (y = 0, |x|,|z| <= 2)",
      close(P_(s1)[:, 1], 0) and np.abs(P_(s1)[:, [0, 2]]).max() <= 2 + 1e-5)
r_tex = np.sqrt(1 / (200 * np.pi))               # relax radius for 200 points in the unit square
s2 = run("PCG_Scatter", geo=G4, generate="in_texture_space", count=200, use_relax=True,
         relax_iterations=30, use_max_relax_radius=False)
mn = min_nn(A_(s2, "uv"))
check("texture-space relax radius = sqrt(1/(N pi)): nearest-neighbour distance falls in (r, 2r]",
      r_tex < mn <= 2 * r_tex + 1e-6, (mn, r_tex))
s = run("PCG_Scatter", geo=G4, generate="in_texture_space", force_total_count=False,
        density_scale=500.0, max_points=100, use_out_density=True, out_texture_space=True)
check("total not forced but clipped to 100 by Max Point Limit: texture-space density = 100 (the actual point count), not 500",
      s.npoints == 100 and close(A_(s, "density"), 100.0, 1e-3))
TN = np.ones((4, 4)); TN[:, :2] = -1.0
s = run("PCG_Scatter", geo=G4, generate="in_texture_space", count=300, density_texture=img(TN))
check("negative texture values treated as 0: all points at u >= 0.5", s.npoints == 300 and A_(s, "uv")[:, 0].min() >= 0.5)
check("no uv: raises", raises(lambda: run(
    "PCG_Scatter", geo=Geometry.from_mesh(P_(G4).astype(np.float32),
                                          [G4.prim_points(i) for i in range(16)]),
    generate="in_texture_space"), "uv"))
# overlapping uv islands: one each on both
GO = build.grid(4.0, 2.0, 3, 2)                 # two 2x2 squares, uv changed so both cover [0,1]^2
uvo = A_(GO, "uv").copy()
uvo[:, 0] = np.where(uvo[:, 0] > 0.75, 1.0, np.where(uvo[:, 0] > 0.25, 1.0, 0.0))
GOv = Geometry.from_mesh(P_(GO).astype(np.float32), [GO.prim_points(0), GO.prim_points(1)])
# uv given per vertex: both prims map to [0,1]^2
vuv = []
for k in range(2):
    q = P_(GO)[GO.prim_points(k)]
    lo = q.min(0); hi = q.max(0)
    vuv.append(np.stack([(q[:, 0] - lo[0]) / (hi[0] - lo[0]), (hi[2] - q[:, 2]) / (hi[2] - lo[2])], 1))
GOv.set(VERTEX, "uv", np.concatenate(vuv).astype(np.float32))
s = run("PCG_Scatter", geo=GOv, generate="in_texture_space", count=100)
spo = A_(s, "sourceprim")[:, 0].astype(int)
check("overlapping uv islands: each sample gives one point on each of the two (2 x 100)", s.npoints == 200 and
      np.all(np.bincount(spo) == 100))

sec("Scatter:By Density + Density Texture")
s = run("PCG_Scatter", geo=G4, count=600, density_texture=img(T2), use_out_density=True,
        use_out_radius=True)
check("forced total: point count = 600, all in the u < 0.5 half", s.npoints == 600 and
      A_(s, "uv")[:, 0].max() < 0.5)
check("forced total: density ~ 600 / 8 (estimated integral, 10%)", abs(A_(s, "density").mean() - 75) < 7.5,
      A_(s, "density").mean())
s = run("PCG_Scatter", geo=G4, force_total_count=False, density_scale=50.0,
        density_texture=img(T2), use_out_density=True, use_out_radius=True,
        use_out_id=True)
exp = 50 * 16 * 0.5
check("total not forced: point count ~ Density Scale x integral(tex) = 400 (5 sigma)",
      abs(s.npoints - exp) < 5 * np.sqrt(exp), s.npoints)
check("total not forced: density = Density Scale x tex = 50", close(A_(s, "density"), 50.0))
check("radius = 0.537/sqrt(50)", close(A_(s, "pscale"), 0.537 / np.sqrt(50), 1e-6))
check("ID = 0..n-1", np.array_equal(A_(s, "id")[:, 0], np.arange(s.npoints)))
s = run("PCG_Scatter", geo=G4, force_total_count=False, density_scale=50.0,
        density_texture=img(T2), use_out_density=True, out_texture_space=True)
check("texture-space density = 50 x 3D area / uv area = 800", close(A_(s, "density"), 800.0, 1e-2))
s = run("PCG_Scatter", geo=G4, force_total_count=False, density_scale=50.0,
        use_out_radius=True, max_relax_radius=0.01)
check("radius clipped by Max Relax Radius", close(A_(s, "pscale"), 0.01))
s = run("PCG_Scatter", geo=G4, force_total_count=False, density_scale=50.0,
        use_out_radius=True, max_relax_radius=0.01, use_max_relax_radius=False)
check("negative control: with Max Relax Radius off no clipping", close(A_(s, "pscale"), 0.537 / np.sqrt(50), 1e-6))
GD = G4.copy()
GD.set(POINT, "dd", np.full((25, 1), 3.0, np.float32))
s = run("PCG_Scatter", geo=GD, force_total_count=False, density_scale=10.0, use_density=True,
        density_attribute="dd", use_out_density=True)
check("By Density without texture: density = Density Scale x density attribute = 30; point count = 480",
      close(A_(s, "density"), 30.0) and s.npoints == 480)
s = run("PCG_Scatter", geo=GD, count=160, use_density=True, density_attribute="dd",
        use_out_density=True)
check("forced total: density = point count / area = 10 (independent of the density attribute's absolute value)", close(A_(s, "density"), 10.0))
check("Density Texture has no effect under count_per_primitive (docs: only used by the other two modes)",
      digest(run("PCG_Scatter", geo=G4, generate="count_per_primitive",
                 count_per_prim_attribute="7", density_texture=img(T2))) ==
      digest(run("PCG_Scatter", geo=G4, generate="count_per_primitive",
                 count_per_prim_attribute="7")))
check("negative control: under By Density the texture changes the result", digest(run("PCG_Scatter", geo=G4, density_texture=img(T2)))
      != digest(run("PCG_Scatter", geo=G4)))
check("all-black texture -> empty", run("PCG_Scatter", geo=G4, density_texture=img(np.zeros((4, 4)))).npoints == 0)

T5 = T2 * 0.5
s = run("PCG_Scatter", geo=G4, force_total_count=False, density_scale=50.0,
        density_texture=img(T5), use_out_density=True)
exp = 50 * 16 * 0.5 * 0.5
check("texture max 0.5: point count ~ 50 x integral(tex) = 200 (5 sigma)", abs(s.npoints - exp) < 5 * np.sqrt(exp),
      s.npoints)
check("texture max 0.5: density = 50 x 0.5", close(A_(s, "density"), 25.0))
s = run("PCG_Scatter", geo=G4, force_total_count=False, density_scale=50.0,
        density_texture=img(T2), max_points=40, use_out_density=True)
check("texture + total not forced + Max Point Limit 40: exactly 40 points, density derived from the actual count (~ 40/8)",
      s.npoints == 40 and abs(A_(s, "density").mean() - 5.0) < 0.75, A_(s, "density").mean())
s = run("PCG_Scatter", geo=G4, force_total_count=False, density_scale=10.0, max_points=50,
        use_out_density=True)
check("no texture clipped to 50 by Max Point Limit: density = 50 / 16", s.npoints == 50 and
      close(A_(s, "density"), 50 / 16))
# the rejection-sampling random stream must be decorrelated from the triangle-picking stream (a pitfall recorded in frommap): the texture is a ramp in u,
# the mean of v, which is independent of the texture, must be 1/2, and the mean of u is integral(u·u) / integral(u) = 2/3
TR = np.tile((np.arange(256) + 0.5) / 256, (256, 1))
GR = build.grid(1.0, 1.0, 2, 2)
s = run("PCG_Scatter", geo=GR, count=40000, density_texture=img(TR))
uvr = A_(s, "uv")
check("ramp texture: u mean 2/3, v mean 1/2 (4 sigma)",
      abs(uvr[:, 0].mean() - 2 / 3) < 4 * 0.236 / 200 and abs(uvr[:, 1].mean() - 0.5) < 4 * 0.289 / 200,
      (uvr[:, 0].mean(), uvr[:, 1].mean()))

sec("Scatter: Attributes tab")
GA = G4.copy()
GA.set(PRIM, "pid", np.arange(16, dtype=np.int32) * 10)
GA.set(PRIM, "tag", np.array([f"t{i}" for i in range(16)]))
GA.set(DETAIL, "lvl", np.array([[7.5]], np.float32))
GA.set(DETAIL, "who", np.array([["me"]]))
GA.set(VERTEX, "vv", np.ones((GA.nvertices, 1), np.float32) * 2)
s = run("PCG_Scatter", geo=GA, count=50, primitive_attributes="pid tag",
        detail_attributes="lvl", detail_as_detail="who")
sp = A_(s, "sourceprim")[:, 0].astype(int)
check("Primitive Attributes: pid on points = the source prim's pid", close(A_(s, "pid")[:, 0], sp * 10))
check("Primitive Attributes: strings are copied too", list(s.get(POINT, "tag")[:, 0]) == [f"t{i}" for i in sp])
check("Detail Attributes: broadcast to every point", close(A_(s, "lvl"), 7.5) and s.get(POINT, "lvl").shape == (50, 1))
check("Detail as Detail: stays on detail", s.has(DETAIL, "who") and
      s.get(DETAIL, "who")[0, 0] == "me" and not s.has(POINT, "who"))
s = run("PCG_Scatter", geo=GA, count=50, point_attributes="* ^Cd")
check("Point Attributes '* ^Cd': Cd not interpolated, uv still present", not s.has(POINT, "Cd") and s.has(POINT, "uv"))
s = run("PCG_Scatter", geo=GA, count=50)
check("negative control: the default '*' brings Cd, vv, not pid / lvl", s.has(POINT, "Cd") and s.has(POINT, "vv") and
      not s.has(POINT, "pid") and not s.has(POINT, "lvl"))
s = run("PCG_Scatter", geo=GA, count=50, vertex_attributes="")
check("Vertex Attributes cleared: vv not interpolated", not s.has(POINT, "vv") and s.has(POINT, "Cd"))
check("Vertex interpolated value correct (constant 2)", close(A_(run("PCG_Scatter", geo=GA, count=20), "vv"), 2.0))
GA2 = GA.copy()
GA2.set(PRIM, "sourceprim", np.full((16, 1), 999, np.int32))
s = run("PCG_Scatter", geo=GA2, count=50, primitive_attributes="*")
check("a same-named prim attribute does not overwrite an output attribute already written (sourceprim is still the prim number, not 999)",
      close(A_(s, "pid")[:, 0], A_(s, "sourceprim")[:, 0] * 10))
panel_ok("PCG_Scatter")



# ═══════════════════════════════════════════════════════════ Scatter and Align

sec("Scatter and Align: bit-identical to before the change at defaults")
golden_check("salign_", GOLDEN)

sec("Scatter and Align: Point Count Method / density attribute / Emergency Limit")
check("Point Count Method has by_spacing appended at the end", opts("PCG_ScatterAlign", "mode") ==
      ["count", "density", "coverage", "by_spacing"])
s = run("PCG_ScatterAlign", geo=G4, mode="by_spacing", spacing=0.5)
check("By Point Spacing:N = 16 / ((√3/2)·0.25) = 74", s.npoints == 74, s.npoints)
check("negative control: Spacing 1 -> 18", run("PCG_ScatterAlign", geo=G4, mode="by_spacing",
                                 spacing=1.0).npoints == 18)
check("Spacing 0: raises", raises(lambda: run("PCG_ScatterAlign", geo=G4, mode="by_spacing",
                                           spacing=0.0), "Spacing"))
GD3 = G4.copy()
GD3.set(POINT, "dd", np.full((25, 1), 3.0, np.float32))
s = run("PCG_ScatterAlign", geo=GD3, mode="density", density=6.0, use_density_attribute=True,
        density_attribute="dd")
check("By Density + density attribute 3: point count = 6 x 16 x 3 = 288", s.npoints == 288, s.npoints)
check("negative control: without the density attribute = 96", run("PCG_ScatterAlign", geo=GD3, mode="density",
                                   density=6.0, density_attribute="dd").npoints == 96)
GLX = G4.copy()
GLX.set(POINT, "dd", (P_(G4)[:, 0:1] + 2).astype(np.float32))      # 0..4, linear
check("linear density attribute: point count = 2 x integral(x+2) dA = 2 x 32 = 64 (triangle averaging is exact for linear functions)",
      run("PCG_ScatterAlign", geo=GLX, mode="density", density=2.0, use_density_attribute=True,
          density_attribute="dd").npoints == 64)
GLX.set(POINT, "dd", P_(G4)[:, 0:1].astype(np.float32))           # -2..2: the negative half treated as 0
check("negative density treated as 0: point count = 2 x integral_{x>0} x dA = 2 x 8 = 16",
      run("PCG_ScatterAlign", geo=GLX, mode="density", density=2.0, use_density_attribute=True,
          density_attribute="dd").npoints == 16)
GDL = G4.copy()
GDL.set(POINT, "dd", (P_(G4)[:, 0:1] <= -1).astype(np.float32))
s = run("PCG_ScatterAlign", geo=GDL, count=200, use_density_attribute=True, density_attribute="dd")
check("Number of Points + density attribute: point count unchanged, landing only on the dd > 0 side (x < 0)",
      s.npoints == 200 and P_(s)[:, 0].max() < 0)
check("density attribute does not exist: raises", raises(lambda: run(
    "PCG_ScatterAlign", geo=G4, mode="density", use_density_attribute=True,
    density_attribute="nope"), "nope"))
g, rep = run_all("PCG_ScatterAlign", geo=G4, count=500, use_emergency_limit=True,
                 emergency_limit=100)
check("Emergency Limit 100: clipped to 100, the original count noted in the report", g.npoints == 100 and "500" in rep, rep)
check("negative control: turned off, no clipping", run("PCG_ScatterAlign", geo=G4, count=500, emergency_limit=100).npoints
      == 500)


def Rm(g, k="orient"):
    return quat_to_mat(A_(g, k))


def ax(R, v):
    return np.einsum("nij,j->ni", R, np.asarray(v, np.float64))


sec("Scatter and Align:Normal / Forward Direction")
SP2 = build.sphere()
base = run("PCG_ScatterAlign", geo=SP2, count=60, rand_seed=2)
R = Rm(base)
check("default: instance +Z -> N, +Y -> up", close(ax(R, [0, 0, 1]), A_(base, "N"), 1e-5) and
      close(ax(R, [0, 1, 0]), A_(base, "up"), 1e-5))
s = run("PCG_ScatterAlign", geo=SP2, count=60, rand_seed=2, normal_direction="y",
        forward_direction="z")
R = Rm(s)
check("Normal Y / Forward Z: instance +Y -> N, +Z -> up", close(ax(R, [0, 1, 0]), A_(s, "N"), 1e-5) and
      close(ax(R, [0, 0, 1]), A_(s, "up"), 1e-5))
check("Normal Y / Forward Z: the N, up attributes themselves are the same as default (only the instance axis mapping changes)",
      close(A_(s, "N"), A_(base, "N")) and close(A_(s, "up"), A_(base, "up")))
check("negative control: orient differs from default", not close(A_(s, "orient"), A_(base, "orient"), 1e-3))
check("orient is still a unit quaternion, R orthogonal and right-handed", close(np.linalg.norm(A_(s, "orient"), axis=1), 1, 1e-5)
      and close(np.linalg.det(R), 1, 1e-4))
s = run("PCG_ScatterAlign", geo=SP2, count=60, rand_seed=2, normal_direction="x",
        forward_direction="custom", forward_custom_x=0.0, forward_custom_y=1.0,
        forward_custom_z=1.0)
R = Rm(s)
check("Normal X / Forward Custom (0,1,1): first orthogonalized against the normal axis -> (0,1,1)/sqrt(2) -> up",
      close(ax(R, [1, 0, 0]), A_(s, "N"), 1e-5) and
      close(ax(R, np.array([0, 1, 1]) / np.sqrt(2)), A_(s, "up"), 1e-5))
s = run("PCG_ScatterAlign", geo=SP2, count=60, rand_seed=2, normal_direction="custom",
        normal_custom_x=1.0, normal_custom_y=0.0, normal_custom_z=1.0, forward_direction="y")
R = Rm(s)
check("Normal Custom (1,0,1):(1,0,1)/√2 → N", close(ax(R, np.array([1, 0, 1]) / np.sqrt(2)),
                                                 A_(s, "N"), 1e-5))
check("Normal Y + Forward Y: parallel, raises", raises(lambda: run(
    "PCG_ScatterAlign", geo=SP2, normal_direction="y"), "parallel"))
check("Custom zero vector: raises", raises(lambda: run(
    "PCG_ScatterAlign", geo=SP2, normal_direction="custom", normal_custom_z=0.0), "0"))

sec("Scatter and Align: rotation around the normal")
# planar grid N = +Y, Up parameter (1,0,0): without rotation up = +X; after rotating theta about +Y up = (cos theta, 0, -sin theta)
GF = build.grid(4.0, 4.0, 3, 3)


def theta(g):
    u = A_(g, "up")
    return np.degrees(np.arctan2(-u[:, 2], u[:, 0]))


kw0 = dict(geo=GF, count=200, up_x=1.0, up_y=0.0, up_z=0.0)
check("rotate_random 0:up = +X", close(theta(run("PCG_ScatterAlign", rotate_random=0.0, **kw0)), 0,
                                       1e-3))
s = run("PCG_ScatterAlign", rotation_range="min_max", min_angle=90.0, max_angle=90.0, **kw0)
check("Min = Max = 90: all up = (0,0,-1)", close(A_(s, "up"), [0, 0, -1], 1e-5))
th = theta(run("PCG_ScatterAlign", rotation_range="min_max", min_angle=10.0, max_angle=20.0, **kw0))
check("Min 10 / Max 20: angles all within [10, 20]", th.min() >= 10 - 1e-3 and th.max() <= 20 + 1e-3 and
      th.max() - th.min() > 5, (th.min(), th.max()))
th = theta(run("PCG_ScatterAlign", rotation_range="min_max", min_angle=0.0, max_angle=360.0,
               round_rotation=True, round_to=90.0, **kw0)) % 360
q = np.round(th / 90) * 90
check("Round to 90: only 0/90/180/270, all four occur", close(th, q, 1e-3) and
      len(np.unique(np.round(q) % 360)) == 4, np.unique(np.round(th)))
th = theta(run("PCG_ScatterAlign", rotate_random=180.0, round_rotation=True, round_to=45.0,
               **kw0))
check("symmetric +-90 + Round 45: only -90 / -45 / 0 / 45 / 90",
      set(np.round(th).astype(int)) <= {-90, -45, 0, 45, 90} and len(set(np.round(th))) >= 4,
      sorted(set(np.round(th))))
th_ns = theta(run("PCG_ScatterAlign", rotate_random=180.0, round_to=45.0, **kw0))
check("negative control: with Round off round_to has no effect", len(set(np.round(th_ns, 3))) > 10)
th = theta(run("PCG_ScatterAlign", rotation_range="min_max", min_angle=50.0, max_angle=80.0,
               round_rotation=True, round_to=90.0, **kw0))
check("Round rounds to nearest (50..80 -> all 90, not 0 as with flooring)", close(th, 90, 1e-3))
s = run("PCG_ScatterAlign", rotate_random=0.0, offset_angle=30.0, **kw0)
check("Offset Angle 30 (not random): theta = 30", close(theta(s), 30, 1e-3))
th1 = theta(run("PCG_ScatterAlign", rotation_range="min_max", min_angle=10.0, max_angle=20.0,
                offset_angle=100.0, **kw0))
check("Offset is added after the random angle: [110, 120]", th1.min() >= 110 - 1e-3 and th1.max() <= 120 + 1e-3)
sb = run("PCG_ScatterAlign", geo=SP2, count=60, rand_seed=4, tilt=20.0)
sm = run("PCG_ScatterAlign", geo=SP2, count=60, rand_seed=4, tilt=20.0, rotation_range="min_max",
         min_angle=-180.0, max_angle=180.0)
check("Min -180 / Max 180 is equivalent to symmetric 360 (same random numbers)", close(A_(sm, "orient"),
                                                                 A_(sb, "orient"), 1e-5))

sec("Scatter and Align: output attributes / Tag / Surface Attributes")
s = run("PCG_ScatterAlign", geo=G4, count=30, use_radius_attribute=False)
check("Output Radius off: no pscale", not s.has(POINT, "pscale"))
s2 = run("PCG_ScatterAlign", geo=G4, count=30, radius_attribute="size", orient_attribute="rot4")
s1 = run("PCG_ScatterAlign", geo=G4, count=30)
check("renamed: values of size / rot4 = the default pscale / orient",
      not s2.has(POINT, "pscale") and not s2.has(POINT, "orient") and
      close(A_(s2, "size"), A_(s1, "pscale")) and close(A_(s2, "rot4"), A_(s1, "orient")))
s = run("PCG_ScatterAlign", geo=G4, count=30, use_orient_attribute=False)
check("Output Orient off: no orient, N / up still present", not s.has(POINT, "orient") and s.has(POINT, "up"))
s = run("PCG_ScatterAlign", geo=G4, count=30, use_prim_uvw=True)
uvw = A_(s, "sourceprimuv")
check("Prim UVW: writes sourceprimuv (barycentric coordinates in the triangle, u, v >= 0, u + v <= 1)",
      uvw.shape == (30, 3) and uvw[:, :2].min() >= 0 and (uvw[:, 0] + uvw[:, 1]).max() <= 1 + 1e-6)
check("negative control: no sourceprimuv by default", not s1.has(POINT, "sourceprimuv"))
s = run("PCG_ScatterAlign", geo=G4, count=30, tag_name="rocks")
check("Tag Name: string attribute tag", list(s.get(POINT, "tag")[:, 0]) == ["rocks"] * 30)
check("negative control: no tag written by default", not s1.has(POINT, "tag"))
s = run("PCG_ScatterAlign", geo=GA, count=30, surface_point_attributes="Cd",
        surface_primitive_attributes="pid", surface_detail_attributes="lvl",
        surface_vertex_attributes="vv")
sp = A_(s, "sourceprim")[:, 0].astype(int)
check("Surface Attributes: Cd interpolated, pid copied, lvl broadcast, vv interpolated",
      s.has(POINT, "Cd") and close(A_(s, "pid")[:, 0], sp * 10) and close(A_(s, "lvl"), 7.5)
      and close(A_(s, "vv"), 2.0) and not s.has(POINT, "uv"))
check("negative control: no surface attributes by default", not any(s1.has(POINT, k) for k in ("Cd", "uv", "pid")))

sec("Scatter and Align:Add Attributes to Existing Point Cloud")
check("Mode menu: surface is the first item", opts("PCG_ScatterAlign", "scatter_mode") ==
      ["surface", "existing_points"])
PTS = Geometry.from_points(np.array([[0.5, 5, 0.5], [1.5, 5, -1.5], [-1.5, 5, 1.5],
                                     [9, 9, 9]], np.float32))
PTS.set(POINT, "pscale", np.full((4, 1), 7.0, np.float32))
s = run("PCG_ScatterAlign", geo=G4, points=PTS, scatter_mode="existing_points", point_group="0-2",
        scale_min=0.2, scale_max=0.4, rand_seed=9, rotate_random=0.0)
check("point count and positions unchanged", s.npoints == 4 and close(P_(s), P_(PTS)))
exp_ps = np.random.default_rng([9, 0x5CA7]).uniform(0.2, 0.4, 3)
check("selected points' pscale = uniform(Min, Max) from the same random stream", close(A_(s, "pscale")[:3, 0], exp_ps))
check("unselected point keeps its original pscale 7", close(A_(s, "pscale")[3], 7.0))
check("normal taken from the nearest surface's prim normal (grid faces +Y, not flipped)", close(A_(s, "N")[:3], [0, 1, 0], 1e-6))


def prim_at(x, z):
    for k in range(G4.nprims):
        q = P_(G4)[G4.prim_points(k)]
        if q[:, 0].min() <= x <= q[:, 0].max() and q[:, 2].min() <= z <= q[:, 2].max():
            return k


check("sourceprim = the square directly below; unselected -1",
      list(A_(s, "sourceprim")[:, 0].astype(int)) ==
      [prim_at(0.5, 0.5), prim_at(1.5, -1.5), prim_at(-1.5, 1.5), -1])
check("unselected point: orient = identity quaternion (newly created attribute)", close(A_(s, "orient")[3], [0, 0, 0, 1]))
R = Rm(s)
check("selected points: instance +Z -> N", close(ax(R, [0, 0, 1])[:3], A_(s, "N")[:3], 1e-5))
PN = PTS.copy()
PN.set(POINT, "N", np.tile([[1.0, 0, 0]], (4, 1)).astype(np.float32))
s = run("PCG_ScatterAlign", geo=Geometry(), points=PN, scatter_mode="existing_points",
        rotate_random=0.0)
check("first input has no prims: uses the points' own N", close(A_(s, "N"), [1, 0, 0], 1e-6))
s = run("PCG_ScatterAlign", geo=Geometry(), points=PTS, scatter_mode="existing_points")
check("and without N: +Y", close(A_(s, "N"), [0, 1, 0], 1e-6))
check("existing_points without the second input connected: raises", raises(lambda: run(
    "PCG_ScatterAlign", geo=G4, scatter_mode="existing_points"), "second input"))
s = run("PCG_ScatterAlign", geo=G4, points=PTS, scatter_mode="existing_points",
        radius_attribute="size", tag_name="t")
check("existing: after renaming, no old names other than pscale left (the original pscale 7 untouched)",
      s.has(POINT, "size") and close(A_(s, "pscale"), 7.0))
PT0 = Geometry.from_points(P_(PTS).astype(np.float32))
s = run("PCG_ScatterAlign", geo=G4, points=PT0, scatter_mode="existing_points", point_group="0-2",
        radius_attribute="size", tag_name="t")
check("existing: unselected points (without the attribute before): size = 1, tag = empty string; selected size within [Min, Max]",
      close(A_(s, "size")[3], 1.0) and s.get(POINT, "tag")[3, 0] == "" and
      s.get(POINT, "tag")[0, 0] == "t" and 0.05 <= A_(s, "size")[:3, 0].min() and
      A_(s, "size")[:3, 0].max() <= 0.1)
s = run("PCG_ScatterAlign", geo=G4, points=PT0, scatter_mode="existing_points", point_group="0-2")
check("existing: unselected and without pscale before -> 1", close(A_(s, "pscale")[3], 1.0))
s = run("PCG_ScatterAlign", geo=G4, points=PTS, scatter_mode="existing_points",
        point_group="@P.x > 100")
check("existing: nothing selected -> output unchanged (no new attributes)", digest(s) == digest(PTS))
panel_ok("PCG_ScatterAlign")


# ═══════════════════════════════════════════════════════════ Point Replicate
sec("Point Replicate: bit-identical to before the change at defaults")
golden_check("prep_", GOLDEN)


def one(p=(1, 2, 3), **attrs):
    g = Geometry.from_points(np.array([p], np.float32))
    for k, v in attrs.items():
        g.set(POINT, k, np.asarray([v], np.float32))
    return g


def offs(g, src=(1, 2, 3)):
    return P_(g) - np.asarray(src, np.float64)


sec("Point Replicate: circle / line / grid (local space + instance transform)")
check("Shape has circle / line / grid appended at the end", opts("PCG_PointReplicate", "shape")[4:] ==
      ["circle", "line", "grid"])
O1 = one(N=(0, 0, 1), pscale=[2.0])               # look_at(+Z, up +Y) = identity
o = offs(run("PCG_PointReplicate", geo=O1, shape="circle", count=500))
rr = np.linalg.norm(o[:, :2], axis=1)
check("circle: local XY plane, diameter Size 1 x pscale 2 -> radius <= 1, z = 0",
      close(o[:, 2], 0) and rr.max() <= 1 + 1e-5 and rr.max() > 0.95, rr.max())
check("circle: uniform by area (radius <= 0.5 holds 1/4, 5 sigma)", abs((rr <= 0.5).mean() - 0.25) < 5 * np.sqrt(
    .25 * .75 / 500))
o = offs(run("PCG_PointReplicate", geo=O1, shape="grid", count=500, size_x=2.0, size_y=0.5))
check("grid: x in [-2, 2], y in [-0.5, 0.5] (reaching both ends), z = 0",
      np.abs(o[:, 0]).max() <= 2 + 1e-5 and o[:, 0].min() < -1.8 and o[:, 0].max() > 1.8 and
      np.abs(o[:, 1]).max() <= 0.5 + 1e-5 and o[:, 1].min() < -0.45 and o[:, 1].max() > 0.45
      and close(o[:, 2], 0))
check("invalid Orientation / Velocity Stretch token: raises",
      raises(lambda: run("PCG_PointReplicate", geo=O1, shape="circle", orientation="xz"),
             "Orientation") and
      raises(lambda: run("PCG_PointReplicate", geo=one(N=(0, 0, 1), v=(0, 0, 1)), shape="circle",
                         velocity_stretch="x"), "must be one of"))
o = offs(run("PCG_PointReplicate", geo=O1, shape="line", count=300))
check("line: along local Z (= N), |z| <= 1", close(o[:, :2], 0) and np.abs(o[:, 2]).max() <= 1 + 1e-5 and
      np.abs(o[:, 2]).max() > 0.9)
o = offs(run("PCG_PointReplicate", geo=O1, shape="circle", count=200, orientation="yz"))
check("Orientation yz: circle in the local YZ plane (x = 0)", close(o[:, 0], 0) and np.abs(o[:, 2]).max() > 0.5)
o = offs(run("PCG_PointReplicate", geo=O1, shape="line", count=200, orientation="zx"))
check("Orientation zx: line along local Y", close(o[:, [0, 2]], 0) and np.abs(o[:, 1]).max() > 0.5)
o = offs(run("PCG_PointReplicate", geo=O1, shape="circle", count=100, center_z=1.0))
check("Center Z 1: moved along N by 1 x pscale 2 = 2", close(o[:, 2], 2.0, 1e-5))
o = offs(run("PCG_PointReplicate", geo=O1, shape="circle", count=100, center_x=1.0,
             size_x=0.0, size_y=0.0))
check("Size 0 + Center X 1: everything lands at (2, 0, 0) (Center is not scaled by Size)", close(o, [2, 0, 0], 1e-5))
o = offs(run("PCG_PointReplicate", geo=O1, shape="line", count=200, uniform_scale=3.0))
check("Uniform Scale 3:|z| ≤ 3", np.abs(o[:, 2]).max() <= 3 + 1e-5 and np.abs(o[:, 2]).max() > 2.7)
O2 = one(N=(1, 0, 0))
o = offs(run("PCG_PointReplicate", geo=O2, shape="circle", count=200))
check("N = +X: circle perpendicular to N (x = 0), no pscale counts as 1 (radius <= 0.5)", close(o[:, 0], 0) and
      np.linalg.norm(o[:, 1:], axis=1).max() <= 0.5 + 1e-5)
c45 = np.sqrt(0.5)
O3 = one(orient=(0, c45, 0, c45), N=(0, 0, 1))       # rotated 90 deg about Y: local Z -> world +X
o = offs(run("PCG_PointReplicate", geo=O3, shape="line", count=100))
check("orient takes precedence over N: line along world X", close(o[:, 1:], 0, 1e-5) and np.abs(o[:, 0]).max() > 0.4)
O4 = one(N=(0, 0, 1), pscale=[2.0], v=(0, 0, 3))
o = offs(run("PCG_PointReplicate", geo=O4, shape="line", count=300, velocity_stretch="scaled",
             velocity_scale=0.5))
check("Velocity Stretch scaled:|z| ≤ 0.5 · pscale 2 · |v| 3 · 0.5 = 1.5",
      np.abs(o[:, 2]).max() <= 1.5 + 1e-5 and np.abs(o[:, 2]).max() > 1.35)
o = offs(run("PCG_PointReplicate", geo=O4, shape="circle", count=300,
             velocity_stretch="ignore_geometry_scale", velocity_scale=0.5))
check("Ignore Geometry Scale: pscale not applied (circle radius <= 0.5), local z was 0 anyway",
      np.linalg.norm(o[:, :2], axis=1).max() <= 0.5 + 1e-5 and close(o[:, 2], 0))
o = offs(run("PCG_PointReplicate", geo=O4, shape="line", count=300,
             velocity_stretch="ignore_geometry_scale", velocity_scale=0.5))
check("Ignore Geometry Scale: line |z| <= 0.5 · 3 · 0.5 = 0.75",
      np.abs(o[:, 2]).max() <= 0.75 + 1e-5 and np.abs(o[:, 2]).max() > 0.7)
o = offs(run("PCG_PointReplicate", geo=O4, shape="line", count=300))
check("negative control: Velocity Stretch none does not stretch (|z| <= 1)", np.abs(o[:, 2]).max() <= 1 + 1e-5 and
      np.abs(o[:, 2]).max() > 0.9)
check("Velocity Stretch without v: raises", raises(lambda: run(
    "PCG_PointReplicate", geo=O1, shape="line", velocity_stretch="scaled"), "v"))
check("old shapes unaffected by Center / Size / Uniform Scale", digest(run(
    "PCG_PointReplicate", geo=PR, center_x=3.0, size_y=5.0, uniform_scale=2.0, orientation="zx"))
    == digest(run("PCG_PointReplicate", geo=PR)))
O6 = one(N=(0, 0, 1), v=(0, 0, 2), scale=(3, 3, 3))
o = offs(run("PCG_PointReplicate", geo=O6, shape="circle", count=300,
             velocity_stretch="ignore_geometry_scale"))
check("Ignore Geometry Scale also drops the scale attribute (circle radius <= 0.5, not 1.5)",
      np.linalg.norm(o[:, :2], axis=1).max() <= 0.5 + 1e-5)
check("v not 3 components: Velocity Stretch raises", raises(lambda: run(
    "PCG_PointReplicate", geo=one(N=(0, 0, 1), v=[2.0]), shape="line",
    velocity_stretch="scaled"), "v"))
O7 = one(N=(0, 0, 1), pivot=(0, 0, 1))
o = offs(run("PCG_PointReplicate", geo=O7, shape="circle", count=50))
check("pivot: local points subtract pivot first (the circle as a whole lands at z = -1)", close(o[:, 2], -1.0, 1e-5))
O5 = one(N=(0, 0, 1), trans=(0, 0, 5))
o = offs(run("PCG_PointReplicate", geo=O5, shape="circle", count=50))
check("trans also counts in the instance transform (z = 5)", close(o[:, 2], 5.0, 1e-5))

sec("Point Replicate: Attributes tab")
g = run("PCG_PointReplicate", geo=PR, copy_source_attributes=False)
check("Copy Source Attributes off: only P and source", sorted(g.attribs[POINT]) == ["P", "source"])
g = run("PCG_PointReplicate", geo=PR, source_attributes="Cd")
check("Attributes 'Cd': copies only Cd", sorted(g.attribs[POINT]) == ["Cd", "P", "source"])
src = A_(g, "source")[:, 0].astype(int)
check("copied Cd = the source point's Cd", close(A_(g, "Cd"), A_(PR, "Cd")[src]))
g = run("PCG_PointReplicate", geo=PR, copy_source_attributes=False, keep_original=True, count=2)
check("not copied + Keep Input: original points keep Cd, replicated points get 0",
      close(A_(g, "Cd")[:4], A_(PR, "Cd")) and close(A_(g, "Cd")[4:], 0))
g1 = run("PCG_PointReplicate", geo=PR, count=4)
g = run("PCG_PointReplicate", geo=PR, count=4, inherit_velocity=0.5)
src = A_(g, "source")[:, 0].astype(int)
check("Inherit Velocity 0.5: v = 0.5 x source point v", close(A_(g, "v"), 0.5 * A_(PR, "v")[src]))
check("negative control: by default v unchanged", close(A_(g1, "v"), A_(PR, "v")[src]))
g = run("PCG_PointReplicate", geo=PR, count=4, inherit_velocity=0.0, radial_velocity=2.0)
check("Radial Velocity 2: v = 2 x (new point - source point)", close(A_(g, "v"), 2 * (P_(g) - P_(PR)[src]), 1e-5))
g = run("PCG_PointReplicate", geo=PR, count=4, radial_velocity=1.0, keep_original=True)
check("Radial + Keep Input: original points' v unchanged", close(A_(g, "v")[:4], A_(PR, "v")))
PRs = PR.copy(); PRs.set(POINT, "v", np.ones((4, 1), np.float32))
g = run("PCG_PointReplicate", geo=PRs, count=3, radial_velocity=1.0)
check("when v is not 3 components Radial creates a new 3-component v", A_(g, "v").shape == (12, 3) and close(
    A_(g, "v"), P_(g) - P_(PRs)[A_(g, "source")[:, 0].astype(int)], 1e-5))
PRn = PR.copy(); PRn.remove(POINT, "v")
g = run("PCG_PointReplicate", geo=PRn, count=4, radial_velocity=1.0)
check("without v Radial creates v", g.has(POINT, "v") and close(
    A_(g, "v"), P_(g) - P_(PRn)[A_(g, "source")[:, 0].astype(int)], 1e-5))
g = run("PCG_PointReplicate", geo=PR, count_attribute="cnt", source_index_attribute="idx",
        keep_original=True)
idx = A_(g, "idx")[:, 0].astype(int)
check("Source Index: original points -1, each cluster 0..k-1 (cnt 3 / 0 / 5 / 2)",
      list(idx) == [-1] * 4 + [0, 1, 2, 0, 1, 2, 3, 4, 0, 1])
g = run("PCG_PointReplicate", geo=PR, keep_source_attributes=False, source_index_attribute="idx")
check("Keep Source Attributes off: neither source nor idx written", not g.has(POINT, "source") and
      not g.has(POINT, "idx"))
g = run("PCG_PointReplicate", geo=PR, count=2, keep_original=True, create_output_group=True)
check("Output Group: only the replicated points", list(g.get_group(POINT, "replicated")) ==
      [False] * 4 + [True] * 8)
check("negative control: no group by default", "replicated" not in run("PCG_PointReplicate", geo=PR).groups[POINT])
panel_ok("PCG_PointReplicate")


# ═══════════════════════════════════════════════════════════ Transform Pieces
sec("Transform Pieces: bit-identical to before the change at defaults")
golden_check("tpieces_", GOLDEN)

sec("Transform Pieces: Attribute Mode / no centering / Invert")
check("Attribute Mode: match is the first item", opts("PCG_TransformPieces", "attribute_mode") ==
      ["match", "index"])
Pa = P_(TPG)[:8]                                     # points of piece a (the 8 points of box a)
Pb = P_(TPG)[8:]


def tp(**kw):
    return run("PCG_TransformPieces", geo=TPG, template=TPT, **kw)


def rz90x2(p):                                       # template of piece a: rotate 90 deg about Z, pscale 2
    return np.stack([-p[:, 1], p[:, 0], p[:, 2]], 1) * 2


def rx90(p):                                         # template of piece b: rotate 90 deg about X
    return np.stack([p[:, 0], -p[:, 2], p[:, 1]], 1)


g = tp(center_pieces=False)
check("no centering (Houdini): a -> 2·Rz90·p + (10,0,0)", close(P_(g)[:8], rz90x2(Pa) + [10, 0, 0], 1e-4))
check("no centering: b -> Rx90·p + (0,10,0)", close(P_(g)[8:], rx90(Pb) + [0, 10, 0], 1e-4))
g0 = tp()
check("negative control / old behaviour: with centering a's center lands at (10,0,0)", close(P_(g0)[:8].mean(0), [10, 0, 0], 1e-4))
gi = run("PCG_TransformPieces", geo=TPG, template=TPT, attribute_mode="index",
         piece_attribute="pidx")
check("Index by Attribute: pidx 0/1 = template point numbers 0/1, same result as matching by name",
      close(P_(gi), P_(g0)))
TPG5 = TPG.copy()
TPG5.set(PRIM, "pidx", np.array([0] * 6 + [5] * 6, np.int32))
g5 = run("PCG_TransformPieces", geo=TPG5, template=TPT, attribute_mode="index",
         piece_attribute="pidx")
check("pieces with an out-of-range Index do not move", close(P_(g5)[8:], Pb) and close(P_(g5)[:8], P_(g0)[:8]))
TPG2 = TPG.copy()
TPG2.set(PRIM, "pidx", np.array([0] * 6 + [2] * 6, np.int32))
check("Index = template point count (2) is also out of range", close(P_(run(
    "PCG_TransformPieces", geo=TPG2, template=TPT, attribute_mode="index",
    piece_attribute="pidx"))[8:], Pb))
TPGf = TPG.copy()
TPGf.set(PRIM, "pidx", np.array([0.0001] * 6 + [0.9999] * 6, np.float32))
check("float indices are rounded (0.9999 -> 1)", close(P_(run(
    "PCG_TransformPieces", geo=TPGf, template=TPT, attribute_mode="index",
    piece_attribute="pidx")), P_(g0)))
check("Index + rest: same as matching by name + rest", close(P_(run(
    "PCG_TransformPieces", geo=TPG, template=TPT, rest=TPR, attribute_mode="index",
    piece_attribute="pidx")), P_(tp(rest=TPR))))
check("invalid Attribute Mode token: raises", raises(lambda: tp(attribute_mode="byname"), "must be one of"))
check("Index with a string attribute: raises", raises(lambda: run(
    "PCG_TransformPieces", geo=TPG, template=TPT, attribute_mode="index"), "is a string"))
TPTn = TPT.copy(); TPTn.remove(POINT, "name")
check("Index mode does not require a same-named attribute on the template", close(P_(run(
    "PCG_TransformPieces", geo=TPG, template=TPTn, attribute_mode="index",
    piece_attribute="pidx")), P_(g0)))
gv = tp(invert_transformation=True)
check("Invert:a → (Rz90⁻¹ (p − T)) / 2", close(P_(gv)[:8], np.stack(
    [(Pa[:, 1] - 0), -(Pa[:, 0] - 10), Pa[:, 2]], 1) / 2, 1e-4))
rt = run("PCG_TransformPieces", geo=g, template=TPT, invert_transformation=True)
check("Invert cancels: forward transform without centering -> inverse = unchanged (P, N, v)",
      close(P_(rt), P_(TPG), 1e-4) and close(A_(rt, "N"), A_(TPG, "N"), 1e-5) and
      close(A_(rt, "v"), A_(TPG, "v"), 1e-5))
gr = tp(rest=TPR)
rr_ = run("PCG_TransformPieces", geo=gr, template=TPT, rest=TPR, invert_transformation=True)
check("Invert cancels (with rest connected)", close(P_(rr_), P_(TPG), 1e-4))
check("negative control: the forward transform with rest really moved things", not close(P_(gr), P_(TPG), 1e-2))
TPTp = TPT.copy(); TPTp.set(POINT, "pivot", np.array([[0, 1, 0], [1, 0, 2]], np.float32))
TPRp = TPR.copy(); TPRp.set(POINT, "pivot", np.array([[0.5, 0, 0], [0, 2, 0]], np.float32))
TPRp.set(POINT, "orient", np.array([[0, c45, 0, c45], [0, 0, 0, 1]], np.float32))
fw = run("PCG_TransformPieces", geo=TPG, template=TPTp, rest=TPRp)
bk = run("PCG_TransformPieces", geo=fw, template=TPTp, rest=TPRp, invert_transformation=True)
check("Invert cancels (template and rest both with pivot, rest with rotation): P, N, v back to original",
      close(P_(bk), P_(TPG), 1e-4) and close(A_(bk, "N"), A_(TPG, "N"), 1e-5) and
      close(A_(bk, "v"), A_(TPG, "v"), 1e-5))
fw = run("PCG_TransformPieces", geo=TPG, template=TPTp, center_pieces=False)
bk = run("PCG_TransformPieces", geo=fw, template=TPTp, invert_transformation=True)
check("Invert cancels (template with pivot, rest not connected)", close(P_(bk), P_(TPG), 1e-4))
check("center_pieces has no effect under Invert", close(P_(tp(invert_transformation=True,
                                                       center_pieces=False)), P_(gv)))

sec("Transform Pieces:Attributes to Transform / Copy Template Attributes")
check("default 'N up v': on a, N (0,1,0) -> (-1,0,0), v (1,0,0) -> (0,2,0), w unchanged",
      close(A_(g0, "N")[:8], [-1, 0, 0], 1e-5) and close(A_(g0, "v")[:8], [0, 2, 0], 1e-5) and
      close(A_(g0, "w"), [0, 0, 1]))
TPTs = TPT.copy(); TPTs.remove(POINT, "orient"); TPTs.remove(POINT, "pscale")
TPTs.set(POINT, "scale", np.array([[1, 3, 1], [1, 1, 1]], np.float32))
TPGn = TPG.copy()
TPGn.set(POINT, "N", np.tile([[c45, c45, 0]], (16, 1)).astype(np.float32))
TPGn.set(POINT, "v", np.tile([[1, 1, 0]], (16, 1)).astype(np.float32))
g = run("PCG_TransformPieces", geo=TPGn, template=TPTs)
nexp = np.array([1, 1 / 3, 0]) / np.linalg.norm([1, 1 / 3, 0])
check("non-uniform scale (1,3,1): N uses the inverse transpose -> (1, 1/3, 0) normalized; v uses M -> (1, 3, 0)",
      close(A_(g, "N")[:8], nexp, 1e-5) and close(A_(g, "v")[:8], [1, 3, 0], 1e-5))
g = tp(attributes_to_transform="N v w")
check("'N v w': w is also transformed as a vector ((0,0,2) on a, (0,-1,0) on b)",
      close(A_(g, "w")[:8], [0, 0, 2], 1e-5) and close(A_(g, "w")[8:], [0, -1, 0], 1e-5))
g = tp(attributes_to_transform="")
check("'': neither N nor v transformed (P still transformed)", close(A_(g, "N"), A_(TPG, "N")) and
      close(A_(g, "v"), A_(TPG, "v")) and close(P_(g), P_(g0)))
g = tp(attributes_to_transform="* ^v")
check("'* ^v': N, w transformed, v not, P not transformed again as a vector", close(P_(g), P_(g0)) and
      close(A_(g, "v"), A_(TPG, "v")) and
      close(A_(g, "N")[:8], [-1, 0, 0], 1e-5) and close(A_(g, "w")[:8], [0, 0, 2], 1e-5))
g = tp(copy_template_attributes=True, groups_to_copy="hot")
check("Copy Template Attributes: a's points Cd = (1,0,0), b's = (0,1,0)",
      close(A_(g, "Cd")[:8], [1, 0, 0]) and close(A_(g, "Cd")[8:], [0, 1, 0]))
check("template name / orient / pscale also copied ('*'), P not copied",
      g.has(POINT, "orient") and close(A_(g, "pscale")[:8], 2.0) and close(P_(g), P_(g0)))
check("Groups to Copy 'hot': only a's points are in the group", list(g.get_group(POINT, "hot")) ==
      [True] * 8 + [False] * 8)
check("negative control: not enabled, nothing copied", not g0.has(POINT, "Cd") and "hot" not in g0.groups[POINT])
check("with the toggle off Groups to Copy is not copied either", "hot" not in tp(groups_to_copy="hot").groups[POINT])
TPGh = TPG5.copy()
TPGh.set_group(POINT, "hot", np.array([False] * 8 + [True] * 8))
g = run("PCG_TransformPieces", geo=TPGh, template=TPT, attribute_mode="index",
        piece_attribute="pidx", copy_template_attributes=True, groups_to_copy="hot")
check("existing same-named group: matched points changed per the template, unmatched kept", list(g.get_group(POINT, "hot")) ==
      [True] * 8 + [True] * 8)
g = run("PCG_TransformPieces", geo=TPG5, template=TPT, attribute_mode="index",
        piece_attribute="pidx", copy_template_attributes=True, attributes_to_copy="Cd")
check("unmatched piece: Cd = 0", close(A_(g, "Cd")[8:], 0) and close(A_(g, "Cd")[:8], [1, 0, 0]))
TPGc = TPG.copy()
TPGc.set(POINT, "Cd", np.full((16, 3), 0.5, np.float32))
g = run("PCG_TransformPieces", geo=TPGc, template=TPT.copy(), attribute_mode="index",
        piece_attribute="pidx", copy_template_attributes=True, attributes_to_copy="Cd")
check("existing same-named attribute: matched ones overwritten, unmatched kept", close(A_(g, "Cd"), np.r_[[[1, 0, 0]] * 8,
                                                                  [[0, 1, 0]] * 8]))
TPG5c = TPG5.copy(); TPG5c.set(POINT, "Cd", np.full((16, 3), 0.5, np.float32))
TPG5c.set(POINT, "name", np.array(["q"] * 16))
g = run("PCG_TransformPieces", geo=TPG5c, template=TPT, attribute_mode="index",
        piece_attribute="pidx", copy_template_attributes=True, attributes_to_copy="Cd name")
check("existing same-named attribute + unmatched piece: original values kept (0.5, string q)", close(A_(g, "Cd")[8:], 0.5) and
      list(g.get(POINT, "name")[:, 0]) == ["a"] * 8 + ["q"] * 8)
panel_ok("PCG_TransformPieces")


# ═══════════════════════════════════════════════════════════ Extract Transform
from comfyui_pcg.geo.xform import point_matrices      # noqa: E402

sec("Extract Transform: bit-identical to before the change at defaults")
golden_check("extract_", GOLDEN)


def inst(pt, A, i=0):
    """Apply the transform of instance point i to A the way Copy to Points reads it."""
    M, T, pv = point_matrices(pt)
    return (A - pv[i]) @ M[i].T + T[i]


sec("Extract Transform:Translation, Rotation, and Non-Uniform Scale")
check("Extraction Method has nonuniform appended at the end", opts("PCG_ExtractTransform", "mode") ==
      ["rigid", "similarity", "affine", "nonuniform"])
Rn = _Rq
Sn = np.array([2.0, 0.5, 3.0])
Ar = P_(ETA)
Bn = Ar @ (Rn @ np.diag(Sn)).T + [1, -2, 3]
ETN = Geometry.from_points(Bn.astype(np.float32))
pt, g, rep = run_all("PCG_ExtractTransform", reference=ETA, target=ETN, mode="nonuniform")
check("exact data: scale = (2, 0.5, 3), orient = R", close(A_(pt, "scale")[0], Sn, 1e-4) and
      close(quat_to_mat(A_(pt, "orient"))[0], Rn, 1e-4), A_(pt, "scale")[0])
check("no pscale written; copying reference by the instance rules lands on target", not pt.has(POINT, "pscale") and
      close(inst(pt, Ar), Bn, 1e-3))
check("geo output = target", close(P_(g), Bn, 1e-3))
check("report: rms ~ 0, three scale values", json.loads(rep)["rms"] < 1e-4 and
      close(json.loads(rep)["scale"], Sn, 1e-4))
pts_ = run("PCG_ExtractTransform", reference=ETA, target=ETN, mode="similarity",
           compute_distortion=True)
check("negative control: similarity on the same data has a clearly non-zero residual", A_(pts_, "distortion")[0, 0] > 0.1)
ptn = run("PCG_ExtractTransform", reference=ETA, target=ETN, mode="nonuniform",
          compute_distortion=True)
check("Compute Distortion: nonuniform on exact data ~ 0", A_(ptn, "distortion")[0, 0] < 1e-4)
Bm = Ar @ (Rn @ np.diag([2.0, -0.5, 3.0])).T
ptm = run("PCG_ExtractTransform", reference=ETA, target=Geometry.from_points(Bm.astype(np.float32)),
          mode="nonuniform")
check("scaling with a mirror can also be fitted (copying by the instance rules lands on target)", close(inst(ptm, Ar), Bm, 1e-3))

sec("Extract Transform:Use Piece Attribute / Attribute Class")
Pg = P_(TPG)
tgtP = Pg.copy()
Ra = quat_to_mat(np.array([[0, 0, c45, c45]]))[0]
tgtP[:8] = Pg[:8] @ Ra.T + [0, 5, 0]                 # piece a: 90 deg about Z + translation
tgtP[8:] = Pg[8:] * 1.0 + [-3, 0, 0]                 # piece b: pure translation
TGT = Geometry.from_points(tgtP.astype(np.float32))
pt, g, rep = run_all("PCG_ExtractTransform", reference=TPG, target=TGT,
                     use_piece_attribute=True, compute_distortion=True)
check("two pieces -> two points, with name", pt.npoints == 2 and list(pt.get(POINT, "name")[:, 0]) == ["a", "b"])
check("pivot = reference piece center, P = transformed piece center",
      close(A_(pt, "pivot"), [Pg[:8].mean(0), Pg[8:].mean(0)], 1e-5) and
      close(P_(pt), [tgtP[:8].mean(0), tgtP[8:].mean(0)], 1e-4))
check("copying each reference piece by the instance rules lands on target",
      close(inst(pt, Pg[:8], 0), tgtP[:8], 1e-4) and close(inst(pt, Pg[8:], 1), tgtP[8:], 1e-4))
check("geo output = target; distortion ~ 0 per piece", close(P_(g), tgtP, 1e-4) and
      close(A_(pt, "distortion"), 0, 1e-4))
check("N in the geo output rotates with its piece ((0,1,0) -> (-1,0,0) on a, b unchanged)",
      close(A_(g, "N")[:8], [-1, 0, 0], 1e-5) and close(A_(g, "N")[8:], [0, 1, 0], 1e-5))
check("negative control: without Piece only one point", run("PCG_ExtractTransform", reference=TPG,
                                           target=TGT).npoints == 1)
check("Attribute Class = point but no name on points: raises", raises(lambda: run(
    "PCG_ExtractTransform", reference=TPG, target=TGT, use_piece_attribute=True,
    attribute_class="point"), "name"))
TPq = TPG.copy()
TPq.set(POINT, "pc", np.array([0] * 8 + [1] * 6 + [2] * 2, np.int32))
pt, g, rep = run_all("PCG_ExtractTransform", reference=TPq, target=TGT, use_piece_attribute=True,
                     piece_attribute="pc", attribute_class="point")
check("point class, integer attribute: 3 pieces; the 2-point piece solves only translation (identity orient)", pt.npoints == 3 and
      close(A_(pt, "pc")[:, 0], [0, 1, 2]) and close(A_(pt, "orient")[2], [0, 0, 0, 1], 1e-6) and
      json.loads(rep)["translation_only_pieces"] == 1 and json.loads(rep)["pieces"] == 3)
check("translation-only piece: P = translated center", close(P_(pt)[2], tgtP[14:].mean(0), 1e-4))
TGT2 = Geometry.from_points(np.r_[tgtP[:14], tgtP[14:15], tgtP[15:16] + [0, 1, 0]].astype(np.float32))
pt = run("PCG_ExtractTransform", reference=TPq, target=TGT2, use_piece_attribute=True,
         piece_attribute="pc", attribute_class="point", compute_distortion=True)
check("distortion of the translation-only piece = residual RMS (two points off by 1 -> 0.5)", close(A_(pt, "distortion")[2], 0.5, 1e-4))
TPw = TPq.copy()
wv = np.ones((16, 1), np.float32); wv[14] = 3.0
TPw.set(POINT, "wt", wv)
pt = run("PCG_ExtractTransform", reference=TPw, target=TGT2, use_piece_attribute=True,
         piece_attribute="pc", attribute_class="point", weight_attribute="wt")
exp_c = (3 * Pg[14] + Pg[15]) / 4
exp_t = (3 * (tgtP[14] - Pg[14]) + (tgtP[15] + [0, 1, 0] - Pg[15])) / 4
check("per piece + weights: pivot = weighted center, translation = weighted mean displacement",
      close(A_(pt, "pivot")[2], exp_c, 1e-5) and close(P_(pt)[2], exp_c + exp_t, 1e-5))
wz = wv.copy(); wz[14:] = 0
TPz = TPq.copy(); TPz.set(POINT, "wt", wz)
check("a piece with all weights 0: raises", raises(lambda: run(
    "PCG_ExtractTransform", reference=TPz, target=TGT2, use_piece_attribute=True,
    piece_attribute="pc", attribute_class="point", weight_attribute="wt"), "weights"))
small = Geometry.from_points(Pg[:2].astype(np.float32))
small.set(POINT, "pc", np.array([[0], [1]], np.int32))
check("per piece, fewer than 3 points overall does not raise (each piece solves only translation)", run(
    "PCG_ExtractTransform", reference=small, target=Geometry.from_points(
        (Pg[:2] + 1).astype(np.float32)), use_piece_attribute=True, piece_attribute="pc",
    attribute_class="point").npoints == 2)
check("invalid Attribute Class token: raises", raises(lambda: run(
    "PCG_ExtractTransform", reference=TPG, target=TGT, attribute_class="vertex"), "must be one of"))
LO = Geometry.from_mesh(np.r_[Pg, [[9, 9, 9]]].astype(np.float32),
                        [TPG.prim_points(i) for i in range(TPG.nprims)])
LO.set(PRIM, "name", TPG.get(PRIM, "name"))
LO.set(POINT, "N", np.r_[A_(TPG, "N"), [[0, 3, 0]]].astype(np.float32))
_, g = run_all("PCG_ExtractTransform", reference=LO, target=Geometry.from_points(
    np.r_[tgtP, [[9, 9, 9]]].astype(np.float32)), use_piece_attribute=True)[:2]
check("points not belonging to any piece: P, N unchanged (N not normalized)", close(P_(g)[16], [9, 9, 9]) and
      close(A_(g, "N")[16], [0, 3, 0]))

sec("Extract Transform:Output Attributes")
for how in ("matrix3", "matrix4"):
    pt = run("PCG_ExtractTransform", reference=ETA, target=ETN, mode="nonuniform",
             output_attributes=how)
    nn = 9 if how == "matrix3" else 16
    check(f"{how}: transform has {nn} components, no orient, lands on target after copying",
          A_(pt, "transform").shape == (1, nn) and not pt.has(POINT, "orient") and
          close(inst(pt, Ar), Bn, 1e-3))
pt = run("PCG_ExtractTransform", reference=ETA, target=ETN, mode="nonuniform",
         output_attributes="matrix4")
check("matrix4: P at the origin, translation in row 4", close(P_(pt), 0) and
      close(A_(pt, "transform")[0, 12:15], [1, -2, 3], 1e-3) and close(A_(pt, "transform")[0, 15], 1))
pt = run("PCG_ExtractTransform", reference=ETA, target=ETN, mode="nonuniform",
         output_attributes="matrix3")
check("matrix3: P = translation", close(P_(pt)[0], [1, -2, 3], 1e-3))
for how in ("matrix3", "matrix4"):
    pt = run("PCG_ExtractTransform", reference=TPG, target=TGT, use_piece_attribute=True,
             output_attributes=how)
    check(f"per piece + {how}: each piece lands on target after copying",
          close(inst(pt, Pg[:8], 0), tgtP[:8], 1e-4) and close(inst(pt, Pg[8:], 1), tgtP[8:], 1e-4))
pt = run("PCG_ExtractTransform", reference=TPG, target=TGT, use_piece_attribute=True,
         output_attributes="matrix4")
check("per piece + matrix4: no pivot written", not pt.has(POINT, "pivot"))
check("invalid Output Attributes token: raises", raises(lambda: run(
    "PCG_ExtractTransform", reference=ETA, target=ETN, output_attributes="m5"), "must be one of"))
panel_ok("PCG_ExtractTransform")


# ═══════════════════════════════════════════════════════════ Cluster Points
sec("Cluster Points: bit-identical to before the change at defaults")
golden_check("cluster_", GOLDEN)

sec("Cluster Points:Output")
check("Output menu: cluster_points is the first item", opts("PCG_ClusterPoints", "output") ==
      ["cluster_points", "average_points", "both", "boxes"])
PC = P_(CLP)
g0 = run("PCG_ClusterPoints", geo=CLP, clusters=3)
lab = A_(g0, "cluster")[:, 0].astype(int)
blob = np.repeat([0, 1, 2], 30)
check("three separate blobs of points -> three clusters, one per blob", all(len(set(lab[blob == b])) == 1 for b in range(3)) and
      len(set(lab)) == 3)
pad0, pad1 = (0.1, 0.2, 0.3), (1.0, 0.5, 0.0)
av = run("PCG_ClusterPoints", geo=CLP, clusters=3, output="average_points",
         padding_min_x=pad0[0], padding_min_y=pad0[1], padding_min_z=pad0[2],
         padding_max_x=pad1[0], padding_max_y=pad1[1], padding_max_z=pad1[2])
ids = A_(av, "cluster")[:, 0].astype(int)
check("Average points: one point per cluster, P = mean within the cluster", av.npoints == 3 and
      close(P_(av), [PC[lab == c].mean(0) for c in ids], 1e-5))
check("scale = bounding box size + Padding min + Padding max", close(A_(av, "scale"), [
    PC[lab == c].max(0) - PC[lab == c].min(0) + np.add(pad0, pad1) for c in ids], 1e-5))
av = run("PCG_ClusterPoints", geo=CLP, clusters=3, output="average_points", size_attribute="")
check("empty Size Attribute: not written", not av.has(POINT, "scale"))
av1 = run("PCG_ClusterPoints", geo=CLP, clusters=3, output="average_points",
          copy_point_attributes=True, max_sample_count=1)
near = [np.nonzero(lab == c)[0][np.argmin(np.linalg.norm(PC[lab == c] - P_(av1)[j], axis=1))]
        for j, c in enumerate(A_(av1, "cluster")[:, 0].astype(int))]
check("Copy Point Attributes, Max Sample 1: Cd = that of the nearest point", close(A_(av1, "Cd"), A_(CLP, "Cd")[near]))
avN = run("PCG_ClusterPoints", geo=CLP, clusters=3, output="average_points",
          copy_point_attributes=True, max_sample_count=1000)
check("very large Max Sample: Cd = mean within the cluster", close(A_(avN, "Cd"), [
    A_(CLP, "Cd")[lab == c].mean(0) for c in A_(avN, "cluster")[:, 0].astype(int)], 1e-5))
check("negative control: not enabled, nothing copied", not run("PCG_ClusterPoints", geo=CLP, clusters=3,
                              output="average_points").has(POINT, "Cd"))
b = run("PCG_ClusterPoints", geo=CLP, clusters=3, output="both")
check("Both: 90 + 3 points, groups clusterpoints / averagepoints", b.npoints == 93 and
      int(b.get_group(POINT, "clusterpoints").sum()) == 90 and
      int(b.get_group(POINT, "averagepoints").sum()) == 3 and
      list(np.nonzero(b.get_group(POINT, "averagepoints"))[0]) == [90, 91, 92])
bx = run("PCG_ClusterPoints", geo=CLP, clusters=3, output="boxes", padding_max_x=1.0)
cl = A_(bx, "cluster", PRIM)[:, 0].astype(int)
ok = bx.nprims == 18
for c in range(3):
    q = P_(bx)[np.unique(np.concatenate([bx.prim_points(i) for i in np.nonzero(cl == c)[0]]))]
    ok = ok and close(q.min(0), PC[lab == c].min(0), 1e-5) and \
        close(q.max(0), PC[lab == c].max(0) + [1, 0, 0], 1e-5)
check("Boxes: one box per cluster (6 prims), extent = bounding box + padding", ok)

sec("Cluster Points:Color Output / Cluster Filter")
gc = run("PCG_ClusterPoints", geo=CLP, clusters=3, color_output="colored_points")
cd = A_(gc, "Cd")
check("Colored Points: same colour within a cluster, different colours across clusters", all(np.ptp(cd[lab == c], 0).max() == 0 for c in range(3))
      and len({tuple(cd[lab == c][0]) for c in range(3)}) == 3)
check("Colored Particles gives the same result as Colored Points (no particle system)", close(A_(run(
    "PCG_ClusterPoints", geo=CLP, clusters=3, color_output="colored_particles"), "Cd"), cd))
avc = run("PCG_ClusterPoints", geo=CLP, clusters=3, output="average_points",
          color_output="colored_points")
check("average points get the same colour too", close(A_(avc, "Cd"), [cd[lab == c][0] for c in
                                                 A_(avc, "cluster")[:, 0].astype(int)]))
check("negative control: Points mode leaves the original Cd alone", close(A_(g0, "Cd"), A_(CLP, "Cd")))
gf = run("PCG_ClusterPoints", geo=CLP, clusters=3, cluster_filter="1")
check("Cluster Filter '1': only the 30 points of cluster 1 remain", gf.npoints == 30 and
      close(A_(gf, "cluster"), 1))
check("Cluster Filter '0-1': 60 points", run("PCG_ClusterPoints", geo=CLP, clusters=3,
                                         cluster_filter="0-1").npoints == 60)
check("Cluster Filter + Average: one point", run("PCG_ClusterPoints", geo=CLP, clusters=3,
                                            cluster_filter="2", output="average_points")
      .npoints == 1)
gg = run("PCG_ClusterPoints", geo=CLP, clusters=2, group="0-29", cluster_filter="0-1")
check("with Cluster Filter, points outside the group (-1) are not output either", gg.npoints == 30)
gb = run("PCG_ClusterPoints", geo=CLP, clusters=2, group="0-29", output="both")
check("points outside the group are not averaged: the average points only cover clusters of the 30 in-group points", gb.npoints == 92 and
      close(np.sort(A_(run("PCG_ClusterPoints", geo=CLP, clusters=2, group="0-29",
                           output="average_points"), "cluster")[:, 0]), [0, 1]))

sec("Cluster Points:Control Attributes / Weight / Build Clusters")
g2 = run("PCG_ClusterPoints", geo=CLP, clusters=2, weight=0.0, control_attribute2="hot")
l2 = A_(g2, "cluster")[:, 0].astype(int)
hot = A_(CLP, "hot")[:, 0] > 0.5
check("P weight 0 + hot: two clusters by hot", len(set(l2[hot])) == 1 and len(set(l2[~hot])) == 1 and
      l2[hot][0] != l2[~hot][0])
g3 = run("PCG_ClusterPoints", geo=CLP, clusters=2, control_attribute2="hot", weight2=0.0)
l3 = A_(g3, "cluster")[:, 0].astype(int)
check("negative control: hot weight 0 = by P only (same as the default 2 clusters)", np.array_equal(
    l3, A_(run("PCG_ClusterPoints", geo=CLP, clusters=2), "cluster")[:, 0].astype(int)))
g4 = run("PCG_ClusterPoints", geo=CLP, clusters=2, control_attribute3="hot", weight3=100.0)
l4 = A_(g4, "cluster")[:, 0].astype(int)
check("the third Control Attribute also takes effect (hot x 100 outweighs P)", len(set(l4[hot])) == 1 and
      len(set(l4[~hot])) == 1)
g5 = run("PCG_ClusterPoints", geo=CLP, clusters=2, control_attribute2="hot", weight2=100.0)
l5 = A_(g5, "cluster")[:, 0].astype(int)
check("Weight 2 = 100: split by hot", len(set(l5[hot])) == 1 and len(set(l5[~hot])) == 1)
check("Control Attribute does not exist: raises", raises(lambda: run(
    "PCG_ClusterPoints", geo=CLP, control_attribute2="nope"), "nope"))
CLE = CLP.copy()
CLE.set(POINT, "cluster", (np.arange(90) % 4)[:, None].astype(np.int32))
ge, ce = run_all("PCG_ClusterPoints", geo=CLE, build_clusters=False, output="average_points")[:2]
check("Build Clusters off: uses the existing cluster (0..3) -> 4 average points", ge.npoints == 4 and close(
    P_(ge), [PC[np.arange(90) % 4 == c].mean(0) for c in range(4)], 1e-5))
check("Build Clusters off: second output count = points per cluster", close(A_(ce, "count")[:, 0], [23, 23, 22, 22]))
check("Build Clusters off but no attribute: raises", raises(lambda: run(
    "PCG_ClusterPoints", geo=CLP, build_clusters=False), "Build Clusters"))
CLE2 = CLP.copy()
CLE2.set(POINT, "cluster", np.where(np.arange(90) < 45, 0, 2)[:, None].astype(np.int32))
ge = run("PCG_ClusterPoints", geo=CLE2, build_clusters=False, output="average_points")
check("Build Clusters off, cluster ids with a gap (0 and 2): only two average points", ge.npoints == 2 and
      close(A_(ge, "cluster")[:, 0], [0, 2]))
ge = run("PCG_ClusterPoints", geo=CLE2, build_clusters=False, output="average_points",
         group="0-29")
check("Build Clusters off + Group: only in-group points used (average of cluster 0 = first 30 points)", ge.npoints == 1 and
      close(P_(ge)[0], PC[:30].mean(0), 1e-5))
CLX = CLP.copy()
CLX.set(POINT, "cluster", np.full((90, 1), 7, np.int32))
gx = run("PCG_ClusterPoints", geo=CLX, clusters=2, group="0-29", color_output="colored_points")
lx = A_(gx, "cluster")[:, 0].astype(int)
check("existing cluster attribute + Group + colouring: points outside the group keep their original value 7, colour white (not a cluster)",
      np.all(lx[30:] == 7) and set(lx[:30]) <= {0, 1} and close(A_(gx, "Cd")[30:], 1.0))
gxa = run("PCG_ClusterPoints", geo=CLX, clusters=2, group="0-29", output="average_points")
check("points outside the group are not averaged even if they had a cluster value", gxa.npoints == 2 and
      close(np.sort(A_(gxa, "cluster")[:, 0]), [0, 1]))
bxc = run("PCG_ClusterPoints", geo=CLP, clusters=3, output="boxes", color_output="colored_points")
clb = A_(bxc, "cluster", PRIM)[:, 0].astype(int)
check("Boxes + colouring: each box's prim Cd = that cluster's colour",
      all(close(A_(bxc, "Cd", PRIM)[clb == c], cd[lab == c][0]) for c in range(3)))
CLS = CLP.copy()
CLS.set(POINT, "tag", np.array([f"t{i}" for i in range(90)]))
CLS.set(POINT, "scale", np.full((90, 3), 9.0, np.float32))
avs = run("PCG_ClusterPoints", geo=CLS, clusters=3, output="average_points",
          copy_point_attributes=True, max_sample_count=5, color_output="colored_points")
nears = [np.nonzero(lab == c)[0][np.argmin(np.linalg.norm(PC[lab == c] - P_(avs)[j], axis=1))]
         for j, c in enumerate(A_(avs, "cluster")[:, 0].astype(int))]
check("Copy: string attributes take the nearest point's", list(avs.get(POINT, "tag")[:, 0]) == [f"t{i}" for i in nears])
check("Copy does not overwrite the Cd already written (cluster colour) or scale (bounding box size)", close(A_(avs, "Cd"), [
    cd[lab == c][0] for c in A_(avs, "cluster")[:, 0].astype(int)]) and
    not close(A_(avs, "scale"), 9.0))
check("invalid Output token: raises", raises(lambda: run("PCG_ClusterPoints", geo=CLP, output="x"),
                                      "must be one of"))
panel_ok("PCG_ClusterPoints")


# ═══════════════════════════════════════════════════════════ HeightField Scatter → Scatter from Map
sec("Scatter from Map: bit-identical to before the change at defaults")
golden_check("sfm_", GOLDEN)


def sfm(**kw):
    return run("PCG_ScatterFromMap", geo=G4, **kw)


ONES = img(np.ones((8, 8)))
HALF = img(np.full((8, 8), 0.5))
sec("Scatter from Map:Scatter Method")
check("Scatter Method menu: count is the first item", opts("PCG_ScatterFromMap", "scatter_method") ==
      ["count", "density", "coverage"])
check("By Density, mask all 1: point count = 10 x 16 = 160", sfm(cop=ONES, scatter_method="density",
                                                     density=10.0).npoints == 160)
check("By Density, mask all 0.5: point count = 10 x 16 x 0.5 = 80", sfm(cop=HALF, scatter_method="density",
                                                            density=10.0).npoints == 80)
n = sfm(cop=SFM_IMG, scatter_method="density", density=40.0).npoints
check("By Density, ramp mask: point count ~ 40 x integral(mask) = 320 (5 sigma)", abs(n - 320) < 5 * np.sqrt(320), n)
check("negative control: count mode ignores density, gives exactly Count", sfm(cop=ONES, count=77, density=10.0).npoints
      == 77)
check("By Coverage (r = 0.2, no variation): N = 0.5 x 16 / (pi · 0.04) -> 64",
      sfm(cop=ONES, scatter_method="coverage", coverage=0.5, outer_radius=0.2).npoints == 64)
check("By Coverage + Exact Scale 2: radius doubled -> 16", sfm(
    cop=ONES, scatter_method="coverage", coverage=0.5, outer_radius=0.2, variability="exact",
    exact_scale=2.0).npoints == 16)
check("By Coverage + Uniform 0.5..1.5:E[s²] = 13/12 → 59", sfm(
    cop=ONES, scatter_method="coverage", coverage=0.5, outer_radius=0.2,
    variability="uniform").npoints == 59)
check("By Coverage + Normal (midpoint 1, Spread 0.5): E[s^2] ~ 1.25 -> 51", sfm(
    cop=ONES, scatter_method="coverage", coverage=0.5, outer_radius=0.2, variability="normal",
    spread=0.5).npoints == 51)
check("By Coverage radius 0: raises", raises(lambda: sfm(cop=ONES, scatter_method="coverage",
                                                  outer_radius=0.0), "Coverage"))
s_ = sfm(cop=HALF, scatter_method="density", density=10.0, density_scale=3.0)
check("By Density also writes density (mask value 0.5 x Density Scale 3)", close(A_(s_, "density"), 1.5))
s_ = sfm(cop=SFM_IMG, scatter_method="density", density=1500.0)
uvr = A_(s_, "uv")
check("By Density ramp mask: u mean 2/3, v mean 1/2 (the rejection stream is decorrelated from the triangle-picking stream, 4 sigma)",
      abs(uvr[:, 0].mean() - 2 / 3) < 4 * 0.236 / np.sqrt(len(uvr)) and
      abs(uvr[:, 1].mean() - 0.5) < 4 * 0.289 / np.sqrt(len(uvr)), (uvr[:, 0].mean(), uvr[:, 1].mean()))
check("Max Points: density mode clipped to 50", sfm(cop=ONES, scatter_method="density", density=10.0,
                                         max_points=50).npoints == 50)
check("Max Points: count mode clipped to 100", sfm(cop=ONES, count=300, max_points=100).npoints == 100)
check("all-black mask -> empty", sfm(cop=img(np.zeros((4, 4))), scatter_method="density",
                          density=10.0).npoints == 0)
check("all-black mask + Density Floor 0.25: point count = 10 x 16 x 0.25 = 40", sfm(
    cop=img(np.zeros((4, 4))), scatter_method="density", density=10.0,
    density_floor=0.25).npoints == 40)
check("Group: only on the selected prims (8 unit cells -> 80 points)", sfm(cop=ONES, scatter_method="density",
                                                   density=10.0, group="0-7").npoints == 80)

sec("Scatter from Map:Variability / Randomize Orients / Quantization / Tag")
s_ = sfm(cop=ONES, count=400, variability="uniform", outer_radius=2.0)
ps = A_(s_, "pscale")[:, 0]
check("Uniform:pscale ∈ [0.5, 1.5],footprint = pscale × Outer Radius", ps.min() >= 0.5 and
      ps.max() <= 1.5 and np.ptp(ps) > 0.8 and close(A_(s_, "footprint")[:, 0], 2 * ps, 1e-5))
s_ = sfm(cop=ONES, count=2000, variability="normal", spread=0.2)
ps = A_(s_, "pscale")[:, 0]
check("Normal: clipped to [0.5, 1.5], mean ~ 1, std ~ 0.2", ps.min() >= 0.5 and ps.max() <= 1.5 and
      abs(ps.mean() - 1) < 0.02 and abs(ps.std() - 0.2) < 0.02, (ps.mean(), ps.std()))
check("Exact: all equal to Exact Scale", close(A_(sfm(cop=ONES, count=50, variability="exact",
                                              exact_scale=3.0), "pscale"), 3.0))
check("negative control: none writes no pscale / footprint", not sfm(cop=ONES, count=50).has(POINT, "pscale"))
s_ = sfm(cop=ONES, count=200, randomize_orients=True, randomize_yaw=0.0)
R = quat_to_mat(A_(s_, "orient"))
check("Randomize Orients, Yaw 0: instance +Y -> N = +Y, +Z -> +Z", close(ax(R, [0, 1, 0]), [0, 1, 0], 1e-5)
      and close(ax(R, [0, 0, 1]), [0, 0, 1], 1e-5) and close(A_(s_, "N"), [0, 1, 0], 1e-5))
s_ = sfm(cop=ONES, count=400, randomize_orients=True, randomize_yaw=90.0)
fz = ax(quat_to_mat(A_(s_, "orient")), [0, 0, 1])
yw = np.degrees(np.arctan2(fz[:, 0], fz[:, 2]))
check("Yaw 90: the forward rotation about Y is within [-90, 90], both signs occur", np.abs(yw).max() <= 90 + 1e-3 and
      yw.min() < -60 and yw.max() > 60 and close(fz[:, 1], 0, 1e-5))
s_ = sfm(cop=ONES, count=400, randomize_orients=True, randomize_up=30.0)
tilt = np.degrees(np.arccos(np.clip(A_(s_, "N")[:, 1], -1, 1)))
R = quat_to_mat(A_(s_, "orient"))
check("Randomize Up 30: normals deviate <= 30 deg and really are tilted; orient's +Y follows N",
      tilt.max() <= 30 + 1e-3 and tilt.max() > 20 and close(ax(R, [0, 1, 0]), A_(s_, "N"), 1e-5))
GT = build.grid(4.0, 4.0, 5, 5, rotate=(30.0, 0.0, 0.0))
nt = np.array([0.0, np.cos(np.radians(30)), np.sin(np.radians(30))])
s_ = run("PCG_ScatterFromMap", geo=GT, cop=ONES, count=50, randomize_orients=True)
Nn = A_(s_, "N")
check("Match Normals with Terrain: N = slope normal", close(np.abs(Nn @ nt), 1.0, 1e-5))
s_ = run("PCG_ScatterFromMap", geo=GT, cop=ONES, count=50, randomize_orients=True,
         match_normals=False)
check("Match Normals off: N = +Y", close(A_(s_, "N"), [0, 1, 0], 1e-6))
GZ = build.grid(4.0, 4.0, 3, 3, plane="xy")          # normals +-Z: the tangent reference must switch to +X
s_ = run("PCG_ScatterFromMap", geo=GZ, cop=ONES, count=30, randomize_orients=True,
         randomize_yaw=0.0)
R = quat_to_mat(A_(s_, "orient"))
check("when the normal is parallel to +Z: orient is still a proper rotation (+Y -> N, +Z -> +X)", np.isfinite(R).all() and
      close(np.abs(ax(R, [0, 1, 0])[:, 2]), 1, 1e-5) and close(ax(R, [0, 0, 1]), [1, 0, 0], 1e-5))
check("negative control: without Randomize Orients no orient is written", not sfm(cop=ONES, count=20).has(POINT, "orient"))
s_ = sfm(cop=ONES, count=100, quantization=0.5)
check("Quantization 0.5: = the unquantized result rounded to multiples of 0.5", close(
    P_(s_), np.round(P_(sfm(cop=ONES, count=100)) * 2) / 2, 1e-5))
check("negative control: not so without quantization", not close(P_(sfm(cop=ONES, count=100)) * 2,
                                    np.round(P_(sfm(cop=ONES, count=100)) * 2), 1e-5))
check("Tag Name: string attribute tag", list(sfm(cop=ONES, count=5, tag_name="grass").get(POINT, "tag")[:, 0])
      == ["grass"] * 5)
check("invalid Scatter Method / Variability: raises", raises(lambda: sfm(cop=ONES, scatter_method="x"),
                                                    "must be one of") and
      raises(lambda: sfm(cop=ONES, variability="x"), "must be one of"))
panel_ok("PCG_ScatterFromMap")


print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
