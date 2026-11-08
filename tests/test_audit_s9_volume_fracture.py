"""
pcg100 audit package s9_volume_fracture: volume / fracture nodes filled in against the SideFX docs.

(What each node does: see the section titles in the file and audit_notes/s9_volume_fracture.md.)

References are all hand-computable numbers (voxel values, face counts, volumes, names). "Bit-identical to before the change at default values" uses
digests computed before the change (commit f210100) from the same set of calls, hard-coded in GOLDEN; `--digests` prints the current digests.
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
from comfyui_pcg.geo import build, ops                  # noqa: E402
from comfyui_pcg.geo import volume as VO                # noqa: E402
from comfyui_pcg.geo import volops as VP                # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, VERTEX, PRIM, DETAIL  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def run(nid, **over):
    kw = {}
    for part in ("required", "optional"):
        for k, spec in M[nid].INPUT_TYPES().get(part, {}).items():
            if isinstance(spec[0], (list, tuple)):
                kw[k] = spec[0][0]
            elif len(spec) > 1 and isinstance(spec[1], dict) and "default" in spec[1]:
                kw[k] = spec[1]["default"]
    kw.update(over)
    r = getattr(M[nid](), M[nid].FUNCTION)(**kw)
    return r["result"][0] if isinstance(r, dict) else r[0]


def raises(fn, match="", exc=(ValueError, KeyError)):
    try:
        fn()
    except exc as e:
        return match in str(e)
    return False


def names(nid):
    it = M[nid].INPUT_TYPES()
    return [k for part in ("required", "optional") for k in it.get(part, {})]


def digest(g):
    h = hashlib.sha1()
    h.update(np.ascontiguousarray(g.vertex_point).tobytes())
    h.update(np.ascontiguousarray(g.prim_offset).tobytes())
    h.update(np.ascontiguousarray(g.prim_closed).tobytes())
    for cls in (POINT, VERTEX, PRIM, DETAIL):
        for k in sorted(g.attribs[cls]):
            v = g.attribs[cls][k]
            h.update(f"{cls}/{k}/{v.dtype}/{v.shape}".encode())
            h.update(np.ascontiguousarray(v).tobytes() if v.dtype.kind != "O"
                     else repr(v.tolist()).encode())
    for cls in (POINT, VERTEX, PRIM):
        for k in sorted(g.groups[cls]):
            h.update(f"g/{cls}/{k}".encode())
            h.update(np.ascontiguousarray(g.groups[cls][k]).tobytes())
    for k in sorted(g.edge_groups):
        h.update(f"e/{k}".encode())
        h.update(np.ascontiguousarray(g.edge_groups[k]).tobytes())
    for i in range(g.nprims):                      # volume voxels live in prim_data
        v = g.pdata(i, "voxels")
        if v is not None:
            h.update(f"vox/{i}".encode())
            h.update(np.ascontiguousarray(np.asarray(v, np.float32)).tobytes())
    return h.hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════ shared geometry
def vinfo(g, i=0):
    v, o, c = VO.volume_info(g, i)
    return np.asarray(v, np.float64), np.asarray(o, np.float64), np.asarray(c, np.float64)


def with_field(res, size, center, fn, name="", fog=False):
    """A volume filled per grid point with fn(world position)."""
    g = VP.create_volume(res, size, center, 0.0, fog, name)
    v, o, c = vinfo(g)
    Q = VP._grid_points(v, o, c)[0]
    g.set_pdata(0, "voxels", np.asarray(fn(Q), np.float64).reshape(v.shape).astype(np.float32))
    return g


def sph_sdf(res=17, r=0.6, size=2.0, name="sdf"):
    return with_field((res, res, res), (size, size, size), (0, 0, 0),
                      lambda Q: np.linalg.norm(Q, axis=1) - r, name)


def noise_vol(res=(7, 6, 5), seed=3, name="density"):
    rng = np.random.default_rng(seed)
    g = VP.create_volume(res, (1.2, 1.0, 0.8), (0.1, 0.0, -0.1), 0.0, True, name)
    v, _, _ = vinfo(g)
    g.set_pdata(0, "voxels", rng.normal(size=v.shape).astype(np.float32))
    return g


def seeds(pts):
    return Geometry.from_points(np.asarray(pts, np.float64))


BOX = build.box()
SEEDS4 = seeds([[-0.25, -0.2, -0.2], [0.25, -0.2, 0.2], [-0.2, 0.25, 0.25], [0.2, 0.2, -0.25]])


def old_cases():
    """Calls using only parameters that **existed before the change**; key -> output geometry."""
    out = {}

    def old(nid, **kw):
        it = M[nid].INPUT_TYPES()
        base = {}
        for part in ("required", "optional"):
            for k, spec in it.get(part, {}).items():
                if k not in OLD_NAMES[nid]:
                    continue
                if isinstance(spec[0], (list, tuple)):
                    base[k] = spec[0][0]
                elif len(spec) > 1 and isinstance(spec[1], dict) and "default" in spec[1]:
                    base[k] = spec[1]["default"]
        base.update(kw)
        res = getattr(M[nid](), M[nid].FUNCTION)(**base)
        return res["result"][0] if isinstance(res, dict) else res[0]

    nv, sd = noise_vol(), sph_sdf()
    out["blur_gauss"] = old("PCG_VolumeBlur", geo=nv, radius=0.3)
    out["blur_box"] = old("PCG_VolumeBlur", geo=nv, radius=0.25, mode="box", iterations=2)
    out["blur_sdf"] = old("PCG_VolumeBlur", geo=sd, radius=0.2)
    nv2 = noise_vol(seed=4)
    for op in ("add", "subtract", "multiply", "maximum", "minimum", "blend", "copy_b",
               "union", "smooth_difference"):
        out["mix_" + op] = old("PCG_VolumeMix", geo_a=nv, geo_b=nv2, operation=op)
    out["mix_resamp"] = old("PCG_VolumeMix", geo_a=sd, geo_b=nv, operation="add")
    out["vf_default"] = old("PCG_VoronoiFracture", geo=BOX, points=SEEDS4)
    out["vf_nocap"] = old("PCG_VoronoiFracture", geo=BOX, points=SEEDS4, cap=False)
    out["vf_grid"] = old("PCG_VoronoiFracture", geo=build.grid(1.0, 1.0, 4, 4), points=SEEDS4,
                         name_prefix="p")
    out["vs_default"] = old("PCG_VoronoiSplit", geo=build.sphere(1.0, 12, 8), cell_points=SEEDS4)
    out["vs_shared"] = old("PCG_VoronoiSplit", geo=build.sphere(1.0, 12, 8), cell_points=SEEDS4,
                           split_points=False, cut_group="cut")
    B2 = build.box((1, 1, 1), (0.5, 0.3, 0.2))
    for op in ("subtract", "union", "intersect", "shatter", "seam"):
        out["bool_" + op] = old("PCG_Boolean", a=BOX, b=B2, operation=op)
    out["bool_shatter_grp"] = old("PCG_Boolean", a=BOX, b=B2, operation="shatter", use_out_groups=True)
    return {k: digest(v) for k, v in out.items()}


OLD_NAMES = {
    "PCG_VolumeBlur": ["geo", "radius", "mode", "iterations", "volumes"],
    "PCG_VolumeMix": ["geo_a", "geo_b", "operation", "factor", "k", "volume_a", "volume_b"],
    "PCG_VoronoiFracture": ["geo", "points", "cap", "cap_mode", "interior_group", "cap_tolerance",
                            "name_attribute", "piece_attribute", "name_prefix", "max_pieces"],
    "PCG_VoronoiSplit": ["geo", "cell_points", "group", "split_points", "piece_attribute", "cut_group"],
    "PCG_Boolean": ["a", "b", "operation", "direction", "treat_a", "treat_b", "use_surface_opts",
                    "shell_thickness", "detriangulate", "coplanar_tolerance", "use_out_groups",
                    "a_inside_b", "a_outside_b", "b_polys", "seam_group", "b_inside_a", "b_outside_a"],
}
# digests from running old_cases() before the change (f210100)
GOLDEN = {
    "blur_gauss": "b8dc30a8ae8ed570",
    "blur_box": "e16c6710a7310cf9",
    "blur_sdf": "4e809e622d5956bd",
    "mix_add": "4303d1cc71278769",
    "mix_subtract": "fd5248ddbadeb502",
    "mix_multiply": "cbb2374faec8d3c0",
    "mix_maximum": "ad05e14b5b91722c",
    "mix_minimum": "28efc17d45513a3a",
    "mix_blend": "71233f73f9bf7bba",
    "mix_copy_b": "29039626efaa2450",
    "mix_union": "28efc17d45513a3a",
    "mix_smooth_difference": "20feca2247104bb2",
    "mix_resamp": "54372ff2ce67b2ea",
    "vf_default": "730a9752823e5295",
    "vf_nocap": "4023e84ac98404d0",
    "vf_grid": "73fd3a8017aa1225",
    "vs_default": "34d7748235143bd9",
    "vs_shared": "358e0f7e6492e9c9",
    "bool_subtract": "4734497dd60b36e9",
    "bool_union": "aaf117273fa1bfdf",
    "bool_intersect": "60682e75ce149ae7",
    "bool_shatter": "5d05aa3bd5381f73",
    "bool_seam": "c9d71bda2f229d77",
    "bool_shatter_grp": "5f5bf542faa08765",
}

if "--digests" in sys.argv:
    import json
    print(json.dumps(old_cases(), indent=1))
    sys.exit(0)


# ═══════════════════════════════════════════════════════════════ regression
sec("bit-identical to before the change at default values")
now = old_cases()
check(f"output digests of all {len(GOLDEN)} old calls unchanged", len(GOLDEN) >= 20 and now == GOLDEN,
      {k: (GOLDEN.get(k), v) for k, v in now.items() if GOLDEN.get(k) != v})


PANEL_NODES = ["PCG_VolumeBlur"]

# ═══════════════════════════════════════════════════════════════ Volume Blur
sec("Volume Blur:Reduction / Voxel Radius / Override Border / Blending")


def vol_of(arr, cell=0.1, name="d"):
    """Array (rz, ry, rx) -> volume with voxel size cell."""
    arr = np.asarray(arr, np.float64)
    rz, ry, rx = arr.shape
    cx, cy, cz = (cell,) * 3 if np.isscalar(cell) else cell
    g = VP.create_volume((rx, ry, rz), ((rx - 1) * cx, (ry - 1) * cy, (rz - 1) * cz),
                         (0, 0, 0), 0.0, True, name)
    g.set_pdata(0, "voxels", arr.astype(np.float32))
    return g


def vb(g, **kw):
    return vinfo(run("PCG_VolumeBlur", geo=g, **kw))[0]


def brute_cube(a, r, fn, border="edge", cval=0.0):
    """Brute-force reference: for each voxel take all values in the cube window (±r[z,y,x] per axis) and pass them to fn."""
    rz, ry, rx = r
    if border == "constant":
        ap = np.pad(a, ((rz, rz), (ry, ry), (rx, rx)), mode="constant", constant_values=cval)
    else:
        ap = np.pad(a, ((rz, rz), (ry, ry), (rx, rx)), mode=border)
    out = np.zeros_like(a)
    for z in range(a.shape[0]):
        for y in range(a.shape[1]):
            for x in range(a.shape[2]):
                out[z, y, x] = fn(ap[z:z + 2 * rz + 1, y:y + 2 * ry + 1, x:x + 2 * rx + 1].ravel())
    return out


rng = np.random.default_rng(9)
A = rng.normal(size=(4, 5, 6))
GA = vol_of(A)
VR = dict(use_voxel_radius=True, voxel_radius_x=2, voxel_radius_y=1, voxel_radius_z=1)
ref_fn = {"maximum": np.max, "minimum": np.min, "max_abs": lambda w: np.abs(w).max(),
          "min_abs": lambda w: np.abs(w).min(), "average": np.mean, "sum": np.sum,
          "sum_abs": lambda w: np.abs(w).sum(), "sum_squares": lambda w: (w ** 2).sum(),
          "rms": lambda w: np.sqrt((w ** 2).mean())}
for red, fn in ref_fn.items():
    got = vb(GA, reduction=red, **VR)
    ref = brute_cube(A, (1, 1, 2), fn)
    check(f"{red}: matches the per-voxel brute force over the cube window (x ±2, y/z ±1, border extended)",
          np.allclose(got, ref, atol=1e-5), float(np.abs(got - ref).max()))
check("  negative control: Maximum ≠ Minimum ≠ Average", not np.allclose(vb(GA, reduction="maximum", **VR),
                                                          vb(GA, reduction="minimum", **VR))
      and not np.allclose(vb(GA, reduction="average", **VR), vb(GA, reduction="sum", **VR)))

# Median: the docs say it is taken axis by axis (separable approximation). 1-D by hand: [1,5,2,8,3], r=1, border extended
L = np.array([1, 5, 2, 8, 3], float)
m1 = vb(vol_of(np.tile(L, (2, 2, 1))), reduction="median", use_voxel_radius=True,
        voxel_radius_x=1, voxel_radius_y=0, voxel_radius_z=0)
check("Median 1-D by hand: [1,5,2,8,3] -> [1,2,5,3,3]", np.allclose(m1[0, 0], [1, 2, 5, 3, 3]), m1[0, 0])
S = np.full((5, 5, 5), 2.0)
S[2, 2, 2] = 50.0
check("Median removes an isolated spike: a single 50 in a constant field goes back to 2 (Average cannot remove it)",
      np.allclose(vb(vol_of(S), reduction="median", **VR), 2.0)
      and vb(vol_of(S), reduction="average", **VR).max() > 2.5)
A1 = rng.normal(size=(3, 4, 5))
sep = A1.copy()
for ax, r in ((0, 1), (1, 1), (2, 2)):
    p = [(0, 0)] * 3
    p[ax] = (r, r)
    sep = np.median(np.lib.stride_tricks.sliding_window_view(np.pad(sep, p, mode="edge"), 2 * r + 1, axis=ax), -1)
check("  Median is a 1-D median along z -> y -> x in turn (not the true cube median)",
      np.allclose(vb(vol_of(A1), reduction="median", **VR), sep)
      and not np.allclose(sep, brute_cube(A1, (1, 1, 2), np.median)))

# world radius to voxels: voxel size 0.1, Radius 0.21 -> 2 voxels per axis
check("world Radius 0.21 / voxel 0.1 -> ±2 voxels per axis (same as Voxel Radius 2,2,2)",
      np.allclose(vb(GA, reduction="sum", radius=0.21),
                  vb(GA, reduction="sum", use_voxel_radius=True, voxel_radius_x=2,
                     voxel_radius_y=2, voxel_radius_z=2))
      and np.allclose(vb(GA, reduction="sum", radius=0.21), brute_cube(A, (2, 2, 2), np.sum)))
check("  negative control: Voxel Radius not read when Use Voxel Radius is off",
      np.allclose(vb(GA, reduction="sum", radius=0.21, voxel_radius_x=7),
                  vb(GA, reduction="sum", radius=0.21)))
Gan = vol_of(rng.normal(size=(3, 4, 5)), cell=(0.05, 0.1, 0.25))
an, _, can = vinfo(Gan)
rr = [int(np.round(0.25 / can[2 - ax])) for ax in range(3)]
check("anisotropic grid: each axis rounds by its own voxel size",
      np.allclose(vb(Gan, reduction="maximum", radius=0.25), brute_cube(an, rr, np.max)) and rr == [1, 2, 5], (rr, can))
big = vb(GA, reduction="maximum", use_voxel_radius=True, voxel_radius_x=200,
         voxel_radius_y=200, voxel_radius_z=200)
check("a huge radius is capped (5× resolution) and still gives the global maximum", np.allclose(big, A.max()))
cap = vb(vol_of(np.tile(np.array([1, 2, 3, 4], float), (2, 2, 1))), reduction="sum", use_voxel_radius=True, voxel_radius_x=1000, voxel_radius_y=0, voxel_radius_z=0)
r20 = np.pad(np.array([1, 2, 3, 4.]), 20, mode="edge")
check("  the cap is 5× resolution (x 4 cells -> ±20): visible with Sum + border extension",
      np.allclose(cap[0, 0], [r20[i:i + 41].sum() for i in range(4)]), cap[0, 0])
check("Voxel Radius 0 = unchanged", np.allclose(vb(GA, reduction="maximum", use_voxel_radius=True,
                                             voxel_radius_x=0, voxel_radius_y=0, voxel_radius_z=0),
                                          A.astype(np.float32)))

# Passes: Sum twice = Sum of the result of one pass
one = brute_cube(A, (1, 1, 2), np.sum)
check("Passes 2 (Sum): equals doing the first pass again", np.allclose(vb(GA, reduction="sum", iterations=2, **VR),
                                                   brute_cube(one, (1, 1, 2), np.sum), atol=1e-4))
check("Passes 0 = original values", np.allclose(vb(GA, reduction="sum", iterations=0, **VR), A.astype(np.float32)))

# Average ≡ box of the same radius (as the docs say)
check("Average matches this plugin's old Box per voxel (docs: Average is equivalent to a box blur of the same radius)",
      np.allclose(vb(GA, reduction="average", radius=0.2), vb(GA, mode="box", radius=0.2)))

# Override Border: 1-D [1,2,3,4], Sum, r=1
L4 = vol_of(np.tile(np.array([1, 2, 3, 4], float), (2, 2, 1)))
X1 = dict(reduction="sum", use_voxel_radius=True, voxel_radius_x=1, voxel_radius_y=0, voxel_radius_z=0)
check("Border Streak:[1,2,3,4] → [4,6,9,11]", np.allclose(vb(L4, override_border="streak", **X1)[0, 0], [4, 6, 9, 11]))
check("Border Repeat:[1,2,3,4] → [7,6,9,8]", np.allclose(vb(L4, override_border="repeat", **X1)[0, 0], [7, 6, 9, 8]))
check("Border Constant 10:[1,2,3,4] → [13,6,9,17]",
      np.allclose(vb(L4, override_border="constant", border_value=10.0, **X1)[0, 0], [13, 6, 9, 17]))
check("  Border Value only read under Constant", np.allclose(vb(L4, override_border="streak", border_value=10.0, **X1),
                                                  vb(L4, override_border="streak", **X1)))
check("Use Volume = Streak (our volumes have no border setting of their own, always clamped to the edge)",
      np.allclose(vb(GA, override_border="use_volume", reduction="sum", **VR),
                  vb(GA, override_border="streak", reduction="sum", **VR))
      and np.allclose(vb(GA, override_border="use_volume"), vb(GA, override_border="streak")))
check("Sum of Squares under Constant: the outside value is squared too (-3 -> 9): [1,2,3,4] -> [14,14,29,34]",
      np.allclose(vb(L4, override_border="constant", border_value=-3.0,
                     **dict(X1, reduction="sum_squares"))[0, 0], [9 + 1 + 4, 1 + 4 + 9, 4 + 9 + 16, 9 + 16 + 9]))
cst = vol_of(np.full((5, 5, 5), 3.0))
check("Filter (Gaussian) also respects Override Border: constant field + border constant 3 unchanged, border 0 pulls the edges down",
      np.allclose(vb(cst, radius=0.2, override_border="constant", border_value=3.0), 3.0)
      and vb(cst, radius=0.2, override_border="constant", border_value=0.0)[0, 0, 0] < 2.0
      and np.allclose(vb(cst, radius=0.2), 3.0))

# Blending
bl = vb(GA, reduction="maximum", enable_blending=True, original_blend=0.5, blurred_blend=2.0, **VR)
check("Blending: 0.5 × original + 2 × result", np.allclose(bl, 0.5 * A + 2 * brute_cube(A, (1, 1, 2), np.max), atol=1e-5))
check("  Blending off does not read the two amounts", np.allclose(vb(GA, reduction="maximum", original_blend=0.5, blurred_blend=2.0, **VR),
                                           brute_cube(A, (1, 1, 2), np.max)))
bg = vb(GA, radius=0.3, enable_blending=True, original_blend=1.0, blurred_blend=-1.0)
check("  the Filter mode can Blend too: original - gaussian = high-pass", np.allclose(bg, A - vb(GA, radius=0.3), atol=1e-5))
check("a bad Reduction raises", raises(lambda: VP.blur(GA, reduction="foo"), "Reduction"))


# ═══════════════════════════════════════════════════════════════ VDB Smooth SDF
sec("VDB Smooth SDF -> new node PCG_VolumeSmoothSDF")
PANEL_NODES.append("PCG_VolumeSmoothSDF")


def ss(g, **kw):
    return vinfo(run("PCG_VolumeSmoothSDF", geo=g, **kw))[0]


def sdfvol(arr, cell=0.1):
    g = vol_of(arr, cell)
    g.set(PRIM, "fog", np.array([[0]], np.int32))
    return g


B = rng.normal(size=(5, 6, 7))
GB = sdfvol(B)
check("Mean Value r=1: (3×3×3) cube mean (border extended), vs brute force",
      np.allclose(ss(GB, operation="mean_value"), brute_cube(B, (1, 1, 1), np.mean), atol=1e-5))
check("Mean Value r=2", np.allclose(ss(GB, operation="mean_value", filter_voxel_radius=2),
                                    brute_cube(B, (2, 2, 2), np.mean), atol=1e-5))
med = ss(GB, operation="median_value")
check("Median Value r=1: the **true** cube median, vs brute force", np.allclose(med, brute_cube(B, (1, 1, 1), np.median), atol=1e-5))
check("  negative control: differs from Volume Blur's per-axis Median",
      not np.allclose(med, vb(GB, reduction="median", use_voxel_radius=True)))
check("Median r=2 vs brute force", np.allclose(ss(GB, operation="median_value", filter_voxel_radius=2),
                                     brute_cube(B, (2, 2, 2), np.median), atol=1e-5))
check("Iterations 2 = two passes", np.allclose(ss(GB, operation="mean_value", iterations=2),
                                       brute_cube(brute_cube(B, (1, 1, 1), np.mean), (1, 1, 1), np.mean), atol=1e-5))
check("Iterations 0 = original values", np.allclose(ss(GB, iterations=0), B.astype(np.float32)))

# planar SDF (linear field): none of the four change it (mean / median symmetric, curvature 0, Laplacian 0)
pl = with_field((9, 9, 9), (0.8, 0.8, 0.8), (0, 0, 0), lambda Q: Q @ np.array([0.6, 0.0, 0.8]) - 0.05)
pa = vinfo(pl)[0]
for op in ("mean_value", "median_value", "mean_curvature_flow", "laplacian_flow"):
    got = ss(pl, operation=op, iterations=2)
    check(f"planar SDF interior unchanged under {op}", np.allclose(got[3:-3, 3:-3, 3:-3], pa[3:-3, 3:-3, 3:-3], atol=1e-5))


def zero_r(arr, o, c):
    """Find the zero crossing along +x (through the center), linearly interpolated."""
    k = arr.shape[0] // 2
    line = arr[k, k, :]
    xs = o[0] + np.arange(len(line)) * c[0]
    j = [i for i in range(len(line) - 1) if line[i] <= 0 < line[i + 1]][-1]
    return xs[j] - line[j] * (xs[j + 1] - xs[j]) / (line[j + 1] - line[j])


sp = sph_sdf(res=41, r=0.6)                 # h = 0.05
_, so, sc = vinfo(sp)
h = 0.05
n = 30
Rc = zero_r(ss(sp, operation="mean_curvature_flow", iterations=n), so, sc)
Rc_ref = np.sqrt(0.36 - 2 * n * h * h / 3)          # dR/dt = −H = −1/R,dt = h²/3
check(f"Mean Curvature Flow: sphere R² = R0² - 2t (t = n·h²/3) -> {Rc_ref:.4f}", abs(Rc - Rc_ref) < 2e-3, Rc)
cf = ss(sp, operation="mean_curvature_flow", iterations=5)
check("  sphere center on a grid point: after the flow the field is still symmetric under any permutation of the x / y / z axes (coefficients consistent)",
      all(np.allclose(cf, np.transpose(cf, pm), atol=1e-6) for pm in ((0, 2, 1), (1, 0, 2), (2, 1, 0))))
n2 = 10
Rl = zero_r(ss(sp, operation="laplacian_flow", iterations=n2), so, sc)
Rl_ref = np.sqrt(0.36 - 4 * n2 * h * h / 6)         # Δ(|x| − R) = 2/r,dR/dt = −2/R,dt = h²/6
check(f"Laplacian Flow: sphere R² ≈ R0² - 4t (t = n·h²/6) -> {Rl_ref:.4f}", abs(Rl - Rl_ref) < 2e-3, Rl)
check("  negative control: with the same 10 steps, Curvature Flow (H = 1/R, step h²/3) shrinks as much as Laplacian; halving the step makes them differ",
      abs(zero_r(ss(sp, operation="mean_curvature_flow", iterations=10), so, sc) - Rl) < 2e-3
      and abs(zero_r(ss(sp, operation="mean_curvature_flow", iterations=5), so, sc) - Rl) > 5e-3)
check("  Filter Voxel Radius has no effect on flows", np.allclose(ss(sp, operation="laplacian_flow", filter_voxel_radius=3),
                                                     ss(sp, operation="laplacian_flow")))

# anisotropic grid: the Laplacian uses each axis's own voxel size
an = with_field((9, 7, 5), (0.8, 0.9, 1.2), (0, 0, 0), lambda Q: Q[:, 0] ** 2 + 2 * Q[:, 1] ** 2 + 3 * Q[:, 2] ** 2)
an.set(PRIM, "fog", np.array([[0]], np.int32))
aa, _, ac = vinfo(an)
got = ss(an, operation="laplacian_flow")
check("Laplacian on an anisotropic grid: Δ of x²+2y²+3z² = 12, interior increases by 12·h²/6 (h = smallest voxel size)",
      np.allclose((got - aa)[1:-1, 1:-1, 1:-1], 12 * ac.min() ** 2 / 6, rtol=1e-4))

# Alpha Mask
mk = VP.create_volume((3, 3, 3), (4, 4, 4), (0, 0, 0), 0.3, True)
mean1 = brute_cube(B, (1, 1, 1), np.mean)
check("Alpha Mask: mask 0.3, Cutoff [0.2, 0.4] -> α = 0.5, result = midpoint of original and mean",
      np.allclose(ss(GB, use_mask=True, mask=mk, min_mask_cutoff=0.2, max_mask_cutoff=0.4),
                  0.5 * (B + mean1), atol=1e-5))
check("  Cutoff [0.2, 0.6] → α = 0.25;Invert → 0.75",
      np.allclose(ss(GB, use_mask=True, mask=mk, min_mask_cutoff=0.2, max_mask_cutoff=0.6),
                  B + 0.25 * (mean1 - B), atol=1e-5)
      and np.allclose(ss(GB, use_mask=True, mask=mk, invert_mask=True, min_mask_cutoff=0.2,
                         max_mask_cutoff=0.6), B + 0.75 * (mean1 - B), atol=1e-5))
check("  mask below Min -> 0 (unchanged), above Max -> 1 (full amount)",
      np.allclose(ss(GB, use_mask=True, mask=mk, min_mask_cutoff=0.5, max_mask_cutoff=0.9), B.astype(np.float32))
      and np.allclose(ss(GB, use_mask=True, mask=mk, min_mask_cutoff=0.0, max_mask_cutoff=0.1), mean1, atol=1e-5))
check("  Alpha Mask off does not read the second input", np.allclose(ss(GB, mask=mk), mean1, atol=1e-5))
# spatially varying mask: only acts on the x > 0 half
mx = with_field((11, 3, 3), (2, 2, 2), (0, 0, 0), lambda Q: (Q[:, 0] > 0.05).astype(float))
got = ss(GB, use_mask=True, mask=mx)
xs = vinfo(GB)[1][0] + np.arange(7) * 0.1
check("  sampled by world position: voxels with x < 0 unchanged, x ≥ 0.25 are the mean",
      np.allclose(got[:, :, xs < -0.01], B[:, :, xs < -0.01]) and
      np.allclose(got[:, :, xs > 0.25], mean1[:, :, xs > 0.25], atol=1e-5))
check("Mask with two iterations: lerp (α = 0.5) each time",
      np.allclose(ss(GB, use_mask=True, mask=mk, min_mask_cutoff=0.2, max_mask_cutoff=0.4, iterations=2),
                  (lambda f1: 0.5 * (f1 + brute_cube(f1, (1, 1, 1), np.mean)))(0.5 * (B + mean1)), atol=1e-5))
check("a fog volume raises", raises(lambda: ss(noise_vol()), "fog"))
check("Alpha Mask on without the second input raises", raises(lambda: ss(GB, use_mask=True), "Alpha Mask"))
check("Max Cutoff ≤ Min raises", raises(lambda: ss(GB, use_mask=True, mask=mk, min_mask_cutoff=0.5,
                                               max_mask_cutoff=0.5), "Cutoff"))


# ═══════════════════════════════════════════════════════════════ Volume Mix
sec("Volume Mix:Diff / Divide / Invert / Clamp / User + Pre / Post / Clamp")
PANEL_NODES.append("PCG_VolumeMix")


def vm(a, b, **kw):
    return vinfo(run("PCG_VolumeMix", geo_a=a, geo_b=b, **kw))[0]


VA, VB = noise_vol(seed=11), noise_vol(seed=12)
a_, b_ = vinfo(VA)[0], vinfo(VB)[0]
b0 = b_.copy()
b0[0, 0, :3] = 0.0
VB0 = VP.create_volume((7, 6, 5), (1.2, 1.0, 0.8), (0.1, 0.0, -0.1), 0.0, True)
VB0.set_pdata(0, "voxels", b0.astype(np.float32))
check("Diff = |A − B|", np.allclose(vm(VA, VB, operation="diff"), np.abs(a_ - b_), atol=1e-6))
dv = vm(VA, VB0, operation="divide")
nz = b0 != 0
check("Divide = A / B; 0 where B = 0 (not specified in the docs)",
      np.allclose(dv[nz], (a_ / np.where(nz, b0, 1))[nz], rtol=1e-5) and np.all(dv[~nz] == 0))
check("Invert = -A (ignores B)", np.allclose(vm(VA, VB, operation="invert"), -a_, atol=1e-6))
check("Clamp = clamp(A, Range)", np.allclose(vm(VA, VB, operation="clamp", range_min=-0.3, range_max=0.5),
                                             np.clip(a_, -0.3, 0.5), atol=1e-6))
check("  Range only read in the Clamp mode", np.allclose(vm(VA, VB, operation="add", range_min=-0.3, range_max=0.5), a_ + b_, atol=1e-6))
check("  negative control: Diff ≠ Subtract", not np.allclose(vm(VA, VB, operation="diff"), vm(VA, VB, operation="subtract")))
ix = np.broadcast_to(np.arange(7), a_.shape)
check("User:Value = @value * 2 + @value2 + @ix", np.allclose(vm(VA, VB, operation="user", value="@value * 2 + @value2 + @ix"),
                                                         2 * a_ + b_ + ix, atol=1e-5))
check("  @bb.x = 0-1 position in A's bounding box (ix / 6), @P.z = world z",
      np.allclose(vm(VA, VB, operation="user", value="@bb.x"), ix / 6.0, atol=1e-6)
      and np.allclose(vm(VA, VB, operation="user", value="@P.z"),
                      np.broadcast_to((-0.5 + np.arange(5) * 0.2)[:, None, None], a_.shape), atol=1e-6))
VBs = VP.create_volume((3, 3, 3), (2.0, 2.0, 2.0), (1.0, 0.0, 0.0), 0.0, True)
check("  @bb2 uses B's own bounding box: B in x ∈ [0, 2], A's x ∈ [-0.5, 0.7] -> bb2.x = (x - 0) / 2",
      np.allclose(vm(VA, VBs, operation="user", value="@bb2.x"),
                  np.broadcast_to((-0.5 + np.arange(7) * 0.2) / 2.0, a_.shape), atol=1e-6))
check("  User's @value / @value2 are A′ / B′ after Pre",
      np.allclose(vm(VA, VB, operation="user", value="@value + @value2", dest_pre_mul=2.0, src_pre_add=1.0),
                  2 * a_ + b_ + 1, atol=1e-5))
check("Pre: Add mode (2A + 1) + (3B - 0.5)",
      np.allclose(vm(VA, VB, dest_pre_mul=2.0, dest_pre_add=1.0, src_pre_mul=3.0, src_pre_add=-0.5),
                  (2 * a_ + 1) + (3 * b_ - 0.5), atol=1e-5))
check("Pre multiplies first, then adds (A·m + a, not (A + a)·m)",
      np.allclose(vm(VA, VB, operation="invert", dest_pre_mul=2.0, dest_pre_add=1.0), -(2 * a_ + 1), atol=1e-5))
check("Post: result·m + a (Multiply mode)", np.allclose(vm(VA, VB, operation="multiply", post_mul=0.5, post_add=-1.0),
                                                   a_ * b_ * 0.5 - 1, atol=1e-5))
check("Post also applies to SDF modes (union + Post-Add 0.2)", np.allclose(vm(VA, VB, operation="union", post_add=0.2),
                                                              np.minimum(a_, b_) + 0.2, atol=1e-5))
check("Clamp Minimum / Maximum applied after Post",
      np.allclose(vm(VA, VB, post_mul=10.0, use_clamp_min=True, clamp_min=-1.0, use_clamp_max=True, clamp_max=2.0),
                  np.clip(10 * (a_ + b_), -1, 2), atol=1e-5))
check("  only Minimum on", np.allclose(vm(VA, VB, use_clamp_min=True, clamp_min=0.0, clamp_max=0.1),
                                   np.maximum(a_ + b_, 0), atol=1e-6))
check("  negative control: clamp values not read while the toggles are off", np.allclose(vm(VA, VB, clamp_min=5.0, clamp_max=-5.0), a_ + b_, atol=1e-6))
# different grids: B is resampled onto A before Pre
lin = with_field((5, 5, 5), (2, 2, 2), (0, 0, 0), lambda Q: Q[:, 0] + 2 * Q[:, 1])
Qa = VP._grid_points(a_, *vinfo(VA)[1:])[0]
check("different grids: B first sampled onto A's grid (exact for a linear field), then Pre-Mul 3",
      np.allclose(vm(VA, lin, operation="copy_b", src_pre_mul=3.0),
                  3 * (Qa[:, 0] + 2 * Qa[:, 1]).reshape(a_.shape), atol=1e-5))
Zm = VP.create_volume((3, 3, 3), (1, 1, 1), (0, 0, 0), 0.0, True)
Zm.set_pdata(0, "voxels", np.full((3, 3, 3), -0.0, np.float32))
Z0 = VP.create_volume((3, 3, 3), (1, 1, 1), (0, 0, 0), 0.0, True)
check("default Pre / Post leave the bits alone: -0.0 - 0.0 stays -0.0 (·1 + 0 would turn it into +0.0)",
      np.all(np.signbit(vm(Zm, Z0, operation="subtract"))))
check("a bad User expression raises", raises(lambda: vm(VA, VB, operation="user", value="@nope +"), "", exc=Exception))


# ═══════════════════════════════════════════════════════════════ Voronoi Fracture
sec("Voronoi Fracture: Group / Name Append / Cell Point / Clip Piece / groups / offset / Partition / normals / Copy")
PANEL_NODES.append("PCG_VoronoiFracture")


def vf(geo, pts, **kw):
    return run("PCG_VoronoiFracture", geo=geo, points=pts, **kw)


def pa(g, k):
    v = g.get(PRIM, k)
    return None if v is None else (v.reshape(-1).tolist())


def gm(g, k, cls=PRIM):
    m = g.get_group(cls, k)
    return None if m is None else np.asarray(m, bool)


TWO = seeds([[0.25, 0.0, 0.0], [-0.25, 0.0, 0.0]])          # after dedup + sort, the -0.25 one is number 0
check("  besides the old parameters, changing one parameter that has no effect (takes the new path) gives output bit-identical to the default",
      digest(vf(BOX, SEEDS4, interior_cusp_angle=41.0)) == GOLDEN["vf_default"]
      and digest(vf(BOX, SEEDS4, cap=False, exterior_cusp_angle=10.0)) == GOLDEN["vf_nocap"])
f2 = vf(BOX, TWO, cell_point_attribute="cellpt", clip_piece_attribute="clippiece",
        exterior_group="outside")
pc = np.array(pa(f2, "piece"))
P2 = f2.get(POINT, "P")
xmax = np.array([P2[f2.prim_points(i)][:, 0].max() for i in range(f2.nprims)])
check("two seeds cut a box: 12 faces (10 exterior + 2 fill), piece 0 is at x < 0", f2.nprims == 12
      and np.all(xmax[pc == 0] <= 1e-6) and np.all(xmax[pc == 1] >= -1e-6))
check("Primitive Cell Point: piece 0 comes from input point 1, piece 1 from point 0",
      np.all(np.array(pa(f2, "cellpt"))[pc == 0] == 1) and np.all(np.array(pa(f2, "cellpt"))[pc == 1] == 0))
inter = gm(f2, "interior")
cp = np.array(pa(f2, "clippiece"))
check("Primitive Clip Piece: fill faces record the piece on the other side (0 ↔ 1), exterior faces -1",
      inter.sum() == 2 and np.all(cp[inter] == 1 - pc[inter]) and np.all(cp[~inter] == -1))
check("Exterior Group = the original faces (10), complementary to Interior",
      gm(f2, "outside").sum() == 10 and np.all(gm(f2, "outside") == ~inter))
check("  negative control: empty attribute names not written", vf(BOX, TWO).get(PRIM, "cellpt") is None
      and vf(BOX, TWO).get_group(PRIM, "outside") is None)

# three pieces: Clip Piece of every fill face points to the piece that really touches it
THREE = seeds([[-0.3, 0, 0], [0.3, 0, 0], [0.0, 0.3, 0.0]])
f3 = vf(BOX, THREE, clip_piece_attribute="cp")
pc3, cp3, in3 = np.array(pa(f3, "piece")), np.array(pa(f3, "cp")), gm(f3, "interior")
S3 = np.unique(THREE.get(POINT, "P").astype(np.float64), axis=0)
ok = True
for i in np.nonzero(in3)[0]:
    c = f3.get(POINT, "P")[f3.prim_points(i)].astype(np.float64).mean(0)
    da, db = np.linalg.norm(c - S3[pc3[i]]), np.linalg.norm(c - S3[cp3[i]])
    ok &= cp3[i] != pc3[i] and abs(da - db) < 1e-5     # centroid equidistant to both seeds = on the bisecting plane of the two pieces
check("  three pieces: the centroid of every fill face is equidistant to the seeds of its own piece and the Clip Piece", ok and in3.sum() >= 3)

OUT = seeds([[0.25, 0, 0], [-5.0, -5.0, -5.0], [-0.25, 0, 0]])   # number 1 (number 0 after dedup + sort) is outside the geometry
fx = vf(BOX, OUT, cell_point_attribute="cellpt")
check("seed outside the geometry: that cell is empty, piece numbers stay compact 0, 1, Cell Point records input points 2 and 0",
      sorted(set(pa(fx, "piece"))) == [0, 1]
      and sorted(set(zip(pa(fx, "piece"), pa(fx, "cellpt")))) == [(0, 2), (1, 0)])

# Merge with Existing Groups
bg = BOX.copy()
bg.set_group(PRIM, "interior", np.arange(6) == 0)
bg.set_group(PRIM, "outside", np.arange(6) == 1)
m_on = vf(bg, TWO, exterior_group="outside")
m_off = vf(bg, TWO, exterior_group="outside", merge_groups=False)
check("Merge on (default): old interior faces still in the interior group (+ 2 new fill faces), old exterior group kept as-is",
      gm(m_on, "interior").sum() == 2 + int(gm(vf(bg, TWO), "interior").sum() - 2)
      and gm(m_on, "interior").sum() > 2 and gm(m_on, "outside").sum() < 10)
check("Merge off: interior has only this run's 2 fill faces, outside = all 10 original faces",
      gm(m_off, "interior").sum() == 2 and gm(m_off, "outside").sum() == 10)
check("  default (new options off) accumulates the old interior group like Merge on", np.all(gm(vf(bg, TWO), "interior") == gm(m_on, "interior")))

# Name Attribute: Append
nb = BOX.copy()
nb.set_string(PRIM, "name", np.array(["rock"] * 6, dtype=object))
check("Name Attribute = Overwrite (default): piece0 / piece1", sorted(set(pa(vf(nb, TWO), "name"))) == ["piece0", "piece1"])
check("Append: original name + '-' + prefix + number -> rock-piece0 (fill faces borrow the name of the piece's original)", sorted(set(pa(vf(nb, TWO, name_mode="append"), "name")))
      == ["rock-piece0", "rock-piece1"])
check("  Append + Fracture Namespace 'f' → rock-fpiece0",
      sorted(set(pa(vf(nb, TWO, name_mode="append", fracture_namespace="f"), "name"))) == ["rock-fpiece0", "rock-fpiece1"])
check("  input without name: Append = Namespace + prefix + number",
      sorted(set(pa(vf(BOX, TWO, name_mode="append", fracture_namespace="f"), "name"))) == ["fpiece0", "fpiece1"])
check("  Overwrite does not read Namespace", sorted(set(pa(vf(nb, TWO, fracture_namespace="f"), "name"))) == ["piece0", "piece1"])

# Cut Plane Offset
fo = vf(BOX, TWO, cut_plane_offset=0.2)
po = np.array(pa(fo, "piece"))
Po = fo.get(POINT, "P")
x0 = [Po[np.concatenate([fo.prim_points(i) for i in np.nonzero(po == k)[0]])][:, 0] for k in (0, 1)]
check("Cut Plane Offset 0.2: a 0.2 gap between the two pieces (x ≤ -0.1 / x ≥ 0.1)",
      abs(x0[0].max() + 0.1) < 1e-6 and abs(x0[1].min() - 0.1) < 1e-6)
far = vf(BOX, seeds([[0, 0, 0], [2.0, 0, 0]]), cut_plane_offset=1.2)
Pf = far.get(POINT, "P")
check("  the offset moves the bisecting plane into the geometry (seeds 2 apart, offset 1.2 -> plane at x = 0.4): pruning also uses the moved distance",
      far.nprims > 0 and abs(Pf[:, 0].max() - 0.4) < 1e-6)
check("  negative control: offset 0 sits at x = 0", abs(np.array([P2[f2.prim_points(i)][:, 0].max() for i in np.nonzero(pc == 0)[0]]).max()) < 1e-6)

# Connectivity Partition: two separate boxes, one cut at z = 0 gives 4 connected parts, 2 cells
bb = ops.merge(build.box((1, 1, 1), (-1, 0, 0)), build.box((1, 1, 1), (1, 0, 0)))
ZS = seeds([[0, 0, -0.25], [0, 0, 0.25]])
p_none = np.array(pa(vf(bb, ZS), "piece"))
p_ow = np.array(pa(vf(bb, ZS, connectivity_partition="overwrite"), "piece"))
fm = vf(bb, ZS, connectivity_partition="maintain")
p_mt = np.array(pa(fm, "piece"))
Pm = fm.get(POINT, "P")
cx = np.array([Pm[fm.prim_points(i)][:, 0].mean() for i in range(fm.nprims)])
cz = np.array([Pm[fm.prim_points(i)][:, 2].mean() for i in range(fm.nprims)])
check("Partition None: 2 pieces (each two disconnected half boxes)", sorted(set(p_none)) == [0, 1])
check("Partition Overwrite: 4 pieces, renumbered 0-3 by (original piece, connected part)",
      sorted(set(p_ow)) == [0, 1, 2, 3] and set(p_ow[p_none == 0]) == {0, 1} and set(p_ow[p_none == 1]) == {2, 3})
check("Partition Maintain: the original 0 and 1 each keep one part, the extra ones appended (2, 3)",
      sorted(set(p_mt)) == [0, 1, 2, 3] and set(p_mt[p_none == 0]) == {0, 2} and set(p_mt[p_none == 1]) == {1, 3}
      and np.all(cz[p_mt == 0] < 1e-9) and np.all(cz[p_mt == 1] > -1e-9))
check("  every new piece is one connected half box (same sign of x, z on one side)",
      all(len(set(np.sign(cx[p_mt == k]))) == 1 and (cz[p_mt == k].max() < 1e-9 or cz[p_mt == k].min() > -1e-9)
          for k in range(4)))
fcp = vf(bb, ZS, connectivity_partition="overwrite", clip_piece_attribute="cp")
pcp_, ccp_, icp_ = np.array(pa(fcp, "piece")), np.array(pa(fcp, "cp")), gm(fcp, "interior")
Pq = fcp.get(POINT, "P")
sx = np.array([np.sign(Pq[fcp.prim_points(i)][:, 0].mean()) for i in range(fcp.nprims)])
ok = icp_.sum() == 4
for i in np.nonzero(icp_)[0]:
    j = ccp_[i]
    ok &= j != pcp_[i] and set(sx[pcp_ == j]) == {sx[i]}         # the piece on the other side is in the same box
check("  after Partition, Clip Piece points to the opposite half in the same box (not the other box of the same cell)", ok)
big = ops.merge(build.box((1, 1, 1), (-1, 0, 0), (3, 3, 3)), build.box((1, 1, 1), (1, 0, 0)))
fb = vf(big, ZS, connectivity_partition="maintain")
pb_ = np.array(pa(fb, "piece"))
Pb = fb.get(POINT, "P")
bx = np.array([Pb[fb.prim_points(i)][:, 0].mean() for i in range(fb.nprims)])
check("  Maintain: the part with more faces (the subdivided box on the left) keeps the original number, the other is appended",
      np.all(bx[pb_ == 0] < 0) and np.all(bx[pb_ == 1] < 0) and np.all(bx[pb_ >= 2] > 0))
check("  names follow the new piece numbers", sorted(set(pa(fm, "name"))) == ["piece0", "piece1", "piece2", "piece3"])

# Group
fg = vf(BOX, TWO, group="0 1")
pg = np.array(pa(fg, "piece"))
check("Group '0 1': the 4 faces outside the group appended unchanged (piece = -1), only faces in the group are cut",
      int((pg == -1).sum()) == 4 and set(pg[pg >= 0]) <= {0, 1} and fg.nprims < 12)

# Copy Cell Point Attributes
TA = seeds([[0.25, 0.0, 0.0], [-0.25, 0.0, 0.0]])
TA.set(POINT, "heat", np.array([[5.0], [7.0]], np.float32))
TA.set(POINT, "Cd", np.array([[1, 0, 0], [0, 1, 0]], np.float32))
fc = vf(BOX, TA, copy_cell_attributes="heat")
pcp = np.array(pa(fc, "piece"))
ptp = np.zeros(fc.npoints, int)
ptp[np.asarray(fc.vertex_point)] = pcp[fc.vertex_prim()]
check("Copy Cell Point Attributes 'heat' -> piece points: piece 0 (seed 1) = 7, piece 1 = 5",
      np.allclose(fc.get(POINT, "heat")[:, 0], np.where(ptp == 0, 7.0, 5.0)) and fc.get(PRIM, "heat") is None)
fc2 = vf(BOX, TA, copy_cell_attributes="*", copy_to_points=False, copy_to_prims=True)
check("  To Piece Primitives + wildcard: heat and Cd both on the faces, not on the points",
      np.allclose(fc2.get(PRIM, "heat")[:, 0], np.where(pcp == 0, 7.0, 5.0))
      and np.allclose(fc2.get(PRIM, "Cd")[pcp == 1], [1, 0, 0]) and fc2.get(POINT, "heat") is None)

# normals
from comfyui_pcg.geo.core import VERTEX as _V        # noqa: E402
fn = vf(BOX, TWO, compute_interior_normals=True)
Nv = fn.get(_V, "N")
inn = gm(fn, "interior")[fn.vertex_prim()]
pcv = np.array(pa(fn, "piece"))[fn.vertex_prim()]
check("Compute Interior Normals: fill face vertex normals = the plane normal facing the other piece (piece 0 +x)",
      Nv is not None and np.allclose(Nv[inn & (pcv == 0)], [1, 0, 0], atol=1e-5)
      and np.allclose(Nv[inn & (pcv == 1)], [-1, 0, 0], atol=1e-5))
check("  Preserve + input without N + interior normals on: exterior computed by Exterior Cusp (box faces flat -> axis aligned)",
      np.allclose(np.abs(Nv[~inn]).max(1), 1.0, atol=1e-5))
check("  negative control: N not written by default", vf(BOX, TWO).get(_V, "N") is None)
fsm = vf(BOX, TWO, compute_interior_normals=True, exterior_normals="none")
check("  Do Not Compute + interior normals on: exterior gets smooth normals (no longer axis aligned at corners)",
      not np.allclose(np.abs(fsm.get(_V, "N")[~inn]).max(1), 1.0, atol=1e-3)
      and np.allclose(fsm.get(_V, "N")[inn & (pcv == 0)], [1, 0, 0], atol=1e-5))
check("  Do Not Compute + interior normals off: nothing written", vf(BOX, TWO, exterior_normals="none").get(_V, "N") is None)
bn = BOX.copy()
bn.set(POINT, "N", np.tile([[0.0, 0.0, 1.0]], (bn.npoints, 1)).astype(np.float32))
fp = vf(bn, TWO, compute_interior_normals=True)
inp = gm(fp, "interior")[fp.vertex_prim()]
check("  Preserve + input has point N: exterior vertices keep (0,0,1), point N becomes vertex N",
      np.allclose(fp.get(_V, "N")[~inp], [0, 0, 1], atol=1e-5) and fp.get(POINT, "N") is None)
fr = vf(bn, TWO, exterior_normals="recompute")
check("  Recompute: ignores input N, always recomputed by Exterior Cusp (axis aligned)",
      np.allclose(np.abs(fr.get(_V, "N")).max(1), 1.0, atol=1e-5)
      and not np.allclose(fr.get(_V, "N"), [0, 0, 1]))
def flat_ok(g):
    """Whether every fill face's vertex normals all equal the face normal (hard edges)."""
    Nn = g.get(_V, "N")
    vpp = g.vertex_prim()
    from comfyui_pcg.geo.ops import prim_normals
    pn = prim_normals(g)
    m = gm(g, "interior")[vpp]
    return np.allclose(Nn[m], pn[vpp][m], atol=1e-4)


check("  Interior Cusp Angle: two fill faces in three pieces meet at 45°; cusp 40 -> hard edge, cusp 60 -> smooth at the shared edge",
      flat_ok(vf(BOX, THREE, compute_interior_normals=True, interior_cusp_angle=40.0))
      and not flat_ok(vf(BOX, THREE, compute_interior_normals=True, interior_cusp_angle=60.0)))
sp_ = build.sphere(0.45, 12, 8)
ic_lo = vf(sp_, TWO, exterior_normals="recompute", exterior_cusp_angle=1.0).get(_V, "N")
ic_hi = vf(sp_, TWO, exterior_normals="recompute", exterior_cusp_angle=90.0).get(_V, "N")
check("  Exterior Cusp Angle has an effect: on a sphere 1° all hard, 90° smooth, results differ", not np.allclose(ic_lo, ic_hi, atol=1e-3))
check("a bad Name Attribute mode raises", raises(lambda: vf(BOX, TWO, name_mode="foo"), "name_mode"))


# ═══════════════════════════════════════════════════════════════ Boolean Fracture
sec("Boolean Fracture -> new node PCG_BooleanFracture")
PANEL_NODES.append("PCG_BooleanFracture")
from comfyui_pcg.geo.measure import prim_volumes, prim_areas   # noqa: E402
from comfyui_pcg.geo.ops import prim_normals                  # noqa: E402


def bf(geo, cut, **kw):
    return run("PCG_BooleanFracture", geo=geo, cutter=cut, **kw)


def piece_vols(g, attr="piece"):
    pc_ = g.get(PRIM, attr)[:, 0]
    v = prim_volumes(g).reshape(-1)
    return {int(k): round(float(v[pc_ == k].sum()), 6) for k in np.unique(pc_)}


GY = build.grid(3.0, 3.0, 4, 4)                          # plane at y = 0, the middle cell exactly covers the box
b1 = bf(BOX, GY)
pb1 = b1.get(PRIM, "piece")[:, 0]
Pb1 = b1.get(POINT, "P")
check("Grid as Surface cuts the box: two pieces, 0.5 volume each, piece 0 at y ≤ 0",
      piece_vols(b1) == {0: 0.5, 1: 0.5}
      and Pb1[np.unique(np.concatenate([b1.prim_points(i) for i in np.nonzero(pb1 == 0)[0]]))][:, 1].max() < 1e-6)
check("  name = piece0 / piece1; interior group 1 face per piece (area 1), exterior group 5 per piece",
      sorted(set(pa(b1, "name"))) == ["piece0", "piece1"]
      and [int(gm(b1, "inside")[pb1 == k].sum()) for k in (0, 1)] == [1, 1]
      and np.allclose(prim_areas(b1)[gm(b1, "inside")], 1.0)
      and [int(gm(b1, "outside")[pb1 == k].sum()) for k in (0, 1)] == [5, 5])
check("Detriangulate All: 12 quads; Only Unchanged: the uncut top / bottom 2 quads + 20 triangles; None: 24 triangles",
      sorted(b1.prim_sizes().tolist()) == [4] * 12
      and sorted(bf(BOX, GY, detriangulate="unchanged").prim_sizes().tolist()) == [3] * 20 + [4] * 2
      and sorted(bf(BOX, GY, detriangulate="none").prim_sizes().tolist()) == [3] * 24)
CB = build.box((1, 1, 1), (0.5, 0.5, 0.5))
b2 = bf(BOX, CB, treat_cutter="solid", pieces_inside="pin", surface_inside="sin")
pv2 = piece_vols(b2)
pin = gm(b2, "pin")
pb2 = b2.get(PRIM, "piece")[:, 0]
kin = int(pb2[pin][0])
check("Solid cutter (a box at the corner): A∩B 0.125 + A-B 0.875",
      sorted(pv2.values()) == [0.125, 0.875] and pv2[kin] == 0.125)
check("  Pieces Inside Cutting Geometry = that whole piece; Surface Inside = its 3 original exterior faces (0.25 each)",
      np.all(pin == (pb2 == kin)) and gm(b2, "sin").sum() == 3
      and np.allclose(prim_areas(b2)[gm(b2, "sin")], 0.25))
check("  negative control: Surface mode does not create these two groups", bf(BOX, GY, pieces_inside="pin").get_group(PRIM, "pin") is None)
# two perpendicular cutting surfaces (two connected pieces) -> 4 pieces, 0.25 each
GX = build.grid(3.0, 3.0, 4, 4)
GX.set(POINT, "P", GX.get(POINT, "P")[:, [1, 0, 2]])          # plane at x = 0
cut2 = ops.merge(GY, GX)
b3 = bf(BOX, cut2, interior_seams="iseam", exterior_seams="eseam")
check("two perpendicular cutting surfaces: 4 pieces, 0.25 each", sorted(piece_vols(b3).values()) == [0.25] * 4, piece_vols(b3))
P3 = b3.get(POINT, "P")
ie = np.asarray(b3.edge_groups.get("iseam"))
ee = np.asarray(b3.edge_groups.get("eseam"))
check("  Interior Seams: the intersection line of the two cutting surfaces (the line x = y = 0, one segment of length 1 per piece)",
      len(ie) >= 4 and np.allclose(P3[ie.reshape(-1)][:, :2], 0, atol=1e-6)
      and abs(np.linalg.norm(P3[ie[:, 0]] - P3[ie[:, 1]], axis=1).sum() - 4.0) < 1e-5)
check("  Exterior Seams: intersection lines of the cuts with the box surface, all on the box surface, total length 4 × (0.5 + 1 + 0.5) × 2 / ... = 16",
      len(ee) > 0 and np.all(np.abs(P3[ee.reshape(-1)]).max(1) > 0.5 - 1e-6)
      and abs(np.linalg.norm(P3[ee[:, 0]] - P3[ee[:, 1]], axis=1).sum() - 16.0) < 1e-5)
from comfyui_pcg.geo import boolfracture as BFM          # noqa: E402
hs = BFM._halfspace(GY, np.arange(GY.nprims), 10.0)
check("half-space solid extruded from the Surface cutter: top 18 + bottom 18 + 12 boundary edges × 2 side triangles = 60; volume = area 9 × 10",
      hs.num_tri() == 60 and abs(hs.volume() - 90.0) < 1e-3)
GYf = build.grid(3.0, 3.0, 7, 7)                    # 0.5 per cell: the cut in the box is made of 4 cutter prims
GXf = build.grid(3.0, 3.0, 7, 7)
GXf.set(POINT, "P", GXf.get(POINT, "P")[:, [1, 0, 2]])
b3f = bf(BOX, ops.merge(GYf, GXf), interior_seams="iseam")
P3f = b3f.get(POINT, "P")
ief = np.asarray(b3f.edge_groups.get("iseam"))
check("  Interior Seams only count intersections between different cutting surfaces (edges between neighbouring prims of the same surface do not count)",
      sorted(piece_vols(b3f).values()) == [0.25] * 4
      and np.allclose(P3f[ief.reshape(-1)][:, :2], 0, atol=1e-6)
      and abs(np.linalg.norm(P3f[ief[:, 0]] - P3f[ief[:, 1]], axis=1).sum() - 4.0) < 1e-5)

# attributes and groups
nb2 = BOX.copy()
nb2.set_string(PRIM, "name", np.array(["rock"] * 6))
nb2.set(PRIM, "id", np.arange(6, dtype=np.int32)[:, None])
nb2.set_group(PRIM, "outside", np.arange(6) == 0)
pnb = prim_normals(nb2)
GYm = GY.copy()
GYm.set(PRIM, "mat", np.full((GY.nprims, 1), 5, np.int32))
b4 = bf(nb2, GYm, name_mode="append", fracture_namespace="f", copy_cutter_attributes="mat")
ext4 = ~gm(b4, "inside")
pn4 = prim_normals(b4)
check("Append: rock-fpiece0 / rock-fpiece1 (whole pieces use the original's name)", sorted(set(pa(b4, "name"))) == ["rock-fpiece0", "rock-fpiece1"])
check("  A's prim attributes carried back onto exterior faces by origin (face normals match the original faces)",
      np.allclose(pn4[ext4], pnb[b4.get(PRIM, "id")[ext4, 0]], atol=1e-5))
nb3 = BOX.copy()
nb3.set(PRIM, "id", np.arange(10, 16, dtype=np.int32)[:, None])
nb3.set_string(PRIM, "tag", np.array([f"t{i}" for i in range(6)]))
b4b = bf(nb3, GY)
in4b = gm(b4b, "inside")
check("  interior faces do not inherit A's attributes: numbers 0, strings empty", np.all(b4b.get(PRIM, "id")[in4b, 0] == 0)
      and np.all(b4b.get(PRIM, "id")[~in4b, 0] >= 10)
      and all(t == "" for t in np.asarray(b4b.get(PRIM, "tag")).reshape(-1)[in4b])
      and all(t.startswith("t") for t in np.asarray(b4b.get(PRIM, "tag")).reshape(-1)[~in4b]))
check("  Copy Cutting Surface Attributes: interior faces mat = 5, exterior faces 0",
      np.all(b4.get(PRIM, "mat")[~ext4, 0] == 5) and np.all(b4.get(PRIM, "mat")[ext4, 0] == 0))
check("  Merge on: the existing outside group kept as-is (only those cut from original face 0)",
      np.all(gm(b4, "outside") == (ext4 & (b4.get(PRIM, "id")[:, 0] == 0))))
check("  Merge off: outside = all exterior faces", np.all(gm(bf(nb2, GY, merge_groups=False), "outside")
                                         == ~gm(bf(nb2, GY, merge_groups=False), "inside")))
withline = ops.merge(BOX, Geometry.from_mesh(np.array([[2, 0, 0], [3, 0, 0], [3, 1, 0]], np.float32),
                                             [[0, 1, 2]], closed=False))
check("open polylines mixed into the input: kept out of the boolean (like Boolean, only closed polygons are triangulated), still cut into two pieces",
      piece_vols(bf(withline, GY)) == {0: 0.5, 1: 0.5})

# multi-level fracture: with Merge on, the previous interior faces are still in the inside group
lv = BOX.copy()
lv.set_group(PRIM, "inside", np.arange(6) == 2)      # pretend face 2 is an interior face from a previous fracture
lv_on, lv_off = bf(lv, GY), bf(lv, GY, merge_groups=False)
check("  Merge on: faces in the existing inside group (cut from original face 2) still in inside; off: only this run's cuts",
      gm(lv_on, "inside").sum() > 2 and gm(lv_off, "inside").sum() == 2
      and np.all(gm(lv_off, "inside") <= gm(lv_on, "inside")))
b5 = bf(BOX, GY, attribute_prefix="f_")
check("Attribute Name Prefix:f_piece / f_inside / f_outside", b5.get(PRIM, "f_piece") is not None
      and b5.get_group(PRIM, "f_inside") is not None and b5.get(PRIM, "piece") is None)
# Group: two separate boxes, only the second is cut
two_b = ops.merge(build.box((1, 1, 1), (-3, 0, 0)), BOX)
b6 = bf(two_b, GY, group="6-11")
p6 = b6.get(PRIM, "piece")[:, 0]
check("Group: only the second box is cut, the first one's 6 faces unchanged (piece = -1)",
      int((p6 == -1).sum()) == 6 and sorted(set(p6[p6 >= 0].tolist())) == [0, 1])
# normals
from comfyui_pcg.geo.core import VERTEX as _V2     # noqa: E402
N7 = b1.get(_V2, "N")
vp7 = b1.vertex_prim()
check("Compute Interior Normals (on by default): every vertex normal = the normal of its face (the box is all right angles)",
      N7 is not None and np.allclose(N7, prim_normals(b1)[vp7], atol=1e-5))
check("  off + Preserve: N not written", bf(BOX, GY, compute_interior_normals=False).get(_V2, "N") is None)
check("cutting with a closed solid as Surface (average normal 0) raises, suggesting Solid", raises(lambda: bf(BOX, CB), "Solid"))


# ═══════════════════════════════════════════════════════════════ Voronoi Split
sec("Voronoi Split: Weight Attribute + Method (Power Distance / Ratio), Offset")
PANEL_NODES.append("PCG_VoronoiSplit")


def vsp(geo, pts, **kw):
    return run("PCG_VoronoiSplit", geo=geo, cell_points=pts, **kw)


def cell_areas(g):
    c = g.get(PRIM, "cell")[:, 0]
    a_ = prim_areas(g).reshape(-1)
    return {int(k): round(float(a_[c == k].sum()), 6) for k in np.unique(c)}


GR = build.grid(2.0, 2.0, 5, 5)                          # y = 0, x, z ∈ [-1, 1], area 4
W2 = seeds([[-0.5, 0, 0], [0.5, 0, 0]])
W2.set(POINT, "weight", np.array([[0.6], [0.2]], np.float32))
W2.set(POINT, "rw", np.array([[1.0], [3.0]], np.float32))
check("default: bisects at x = 0, two pieces of 2 each", cell_areas(vsp(GR, W2)) == {0: 2.0, 1: 2.0})
check("Power Distance (radii 0.6 / 0.2): cut plane x = ½(0.6² - 0.2²) = 0.16 -> piece 0 2 × 1.16",
      cell_areas(vsp(GR, W2, use_weight=True)) == {0: 2.32, 1: 1.68})
check("Ratio (weights 1 / 3): 1/4 of the way from 0 -> x = -0.25, piece 0 1.5",
      cell_areas(vsp(GR, W2, use_weight=True, weight_attribute="rw", method="ratio")) == {0: 1.5, 1: 2.5})
check("  negative control: weights / Method not read when Use Weight is off", cell_areas(vsp(GR, W2, method="ratio")) == {0: 2.0, 1: 2.0})
W2e = seeds([[-0.5, 0, 0], [0.5, 0, 0]])
W2e.set(POINT, "weight", np.array([[0.4], [0.4]], np.float32))
check("  Power with equal weights = ordinary Voronoi", cell_areas(vsp(GR, W2e, use_weight=True)) == {0: 2.0, 1: 2.0})
check("Offset 0.1: moved 0.1 along 0 -> 1, x = 0.1, piece 0 2.2", cell_areas(vsp(GR, W2, offset=0.1)) == {0: 2.2, 1: 1.8})
W2f = seeds([[-1.0, 0, 0], [1.0, 0, 0]])
check("  Offset is a world distance (also moves 0.1 when the points are 2 apart)", cell_areas(vsp(GR, W2f, offset=0.1)) == {0: 2.2, 1: 1.8})
W2r = seeds([[0.5, 0, 0], [-0.5, 0, 0]])
check("  point numbers swapped: the direction flips too (along 0 -> 1 = -x), piece 0 (x = 0.5) is 2.2",
      cell_areas(vsp(GR, W2r, offset=0.1)) == {0: 2.2, 1: 1.8})
rng3 = np.random.default_rng(5)
S5 = np.c_[rng3.uniform(-1, 1, 5), np.zeros(5), rng3.uniform(-1, 1, 5)]
W5 = seeds(S5)
w5 = rng3.uniform(0.0, 0.5, 5)
W5.set(POINT, "weight", w5[:, None].astype(np.float32))
o5 = vsp(GR, W5, use_weight=True)
C5 = np.array([o5.get(POINT, "P")[o5.prim_points(i)].astype(np.float64).mean(0) for i in range(o5.nprims)])
pw = ((C5[:, None, :] - S5[None]) ** 2).sum(-1) - w5[None] ** 2
check("Power: 5 random cell points + random radii, every fragment's centroid lies in the cell with the smallest power, total area 4",
      np.all(pw.argmin(1) == o5.get(PRIM, "cell")[:, 0]) and abs(sum(cell_areas(o5).values()) - 4) < 1e-6)
GRf = build.grid(2.0, 2.0, 21, 21)
Wb = seeds([[-0.9, 0, 0], [0.9, 0, 0]])
Wb.set(POINT, "weight", np.array([[0.0], [1.6]], np.float32))
xb = -1.28 / 1.8
check("Power: a far point with a large radius reaches right up to another point (x > -0.711), nothing missed on a fine mesh (candidates cannot be filtered by nearest distance)",
      cell_areas(vsp(GRf, Wb, use_weight=True)) == {0: round(2 * (xb + 1), 6), 1: round(2 * (1 - xb), 6)})
check("  with split_points off, both sides of a cut share points (fewer points than with it on)",
      vsp(GR, W2, use_weight=True, split_points=False).npoints < vsp(GR, W2, use_weight=True).npoints)
check("missing weight attribute raises", raises(lambda: vsp(GR, W2, use_weight=True, weight_attribute="zz"), "zz"))
W2z = seeds([[-0.5, 0, 0], [0.5, 0, 0]])
W2z.set(POINT, "rw", np.array([[0.0], [1.0]], np.float32))
check("  Ratio with weight 0 raises", raises(lambda: vsp(GR, W2z, use_weight=True, weight_attribute="rw", method="ratio"), "Ratio"))


# ═══════════════════════════════════════════════════════════════ IsoOffset
sec("IsoOffset ([C]) -> new node PCG_IsoOffset")
PANEL_NODES.append("PCG_IsoOffset")


def iso(geo, **kw):
    return run("PCG_IsoOffset", geo=geo, **kw)


def vgrid(g):
    v, o, c = vinfo(g)
    return v, o, c, VP._grid_points(v, o, c)[0]


def box_sdf(Q, lo=-0.5, hi=0.5):
    q = np.abs(Q - 0.5 * (lo + hi)) - 0.5 * (hi - lo)
    return np.linalg.norm(np.maximum(q, 0), axis=1) + np.minimum(q.max(1), 0)


v, o, c, Q = vgrid(iso(BOX, output="sdf", mode="implicit_box", uniform_divs=11))
check("Implicit Box, Max Axis 11 grid points: origin -0.5, voxel 0.1, 11³, values = exact SDF of the box",
      np.allclose(o, -0.5) and np.allclose(c, 0.1) and v.shape == (11, 11, 11)
      and np.allclose(v.reshape(-1), box_sdf(Q), atol=1e-6))
v2_, _, _, Q2 = vgrid(iso(BOX, output="sdf", mode="implicit_sphere", uniform_divs=11))
check("Implicit Sphere: center = bounding box center, radius = √0.75", np.allclose(v2_.reshape(-1), np.linalg.norm(Q2, axis=1) - np.sqrt(0.75), atol=1e-6))
v3, _, c3, Q3 = vgrid(iso(BOX, output="sdf", mode="ray_intersect", uniform_divs=11, offset=0.2))
check("Ray Intersect + Offset 0.2: bounding box expanded by 0.2 (1.4 / 10 cells), values = box SDF - 0.2 (negative inside, positive outside)",
      np.allclose(c3, 0.14) and v3.shape == (11, 11, 11)
      and np.abs(v3.reshape(-1) - (box_sdf(Q3) - 0.2)).max() < 0.02
      and v3[5, 5, 5] < 0 and v3[0, 0, 0] > 0)
v4, _, _, Q4 = vgrid(iso(BOX, output="sdf", mode="minimum", uniform_divs=11, offset=0.2))
check("Minimum: unsigned distance - Offset (box center = 0.5 - 0.2)", abs(v4[5, 5, 5] - 0.3) < 1e-5
      and np.abs(v4.reshape(-1) - (np.abs(box_sdf(Q4)) - 0.2)).max() < 0.02)
check("  negative control: Ray Intersect box center is -0.7", abs(v3[5, 5, 5] + 0.7) < 1e-5)
check("Invert Sign: the whole field negated", np.allclose(vgrid(iso(BOX, output="sdf", mode="implicit_box", uniform_divs=11,
                                                     invert_sign=True))[0], -v, atol=1e-6))
vo, oo, co, _ = vgrid(iso(BOX, output="sdf", mode="implicit_box", override_bounds=True, min_x=-1.0,
                          min_y=-1.0, min_z=0.0, max_x=1.0, max_y=1.0, max_z=1.0, uniform_divs=5))
check("Override Bounds: x/y ∈ [-1, 1], z ∈ [0, 1], Max Axis 5 -> voxel 0.5, 5×5×3",
      np.allclose(oo, [-1, -1, 0]) and np.allclose(co, 0.5) and vo.shape == (3, 5, 5))
ref = build.box((4, 2, 2))
vb_, ob_, cb_, _ = vgrid(iso(BOX, output="sdf", mode="implicit_box", override_bounds=True, bound=ref, uniform_divs=9))
check("  with the second input connected its bounding box is used (4 × 2 × 2, x 9 grid points -> voxel 0.5)",
      np.allclose(ob_, [-2, -1, -1]) and np.allclose(cb_, 0.5) and vb_.shape == (5, 5, 9))
check("  negative control: Bound not read when Override is off", np.allclose(vgrid(iso(BOX, output="sdf", mode="implicit_box", uniform_divs=11,
                                                           bound=ref, min_x=-3.0))[1], -0.5))
vp_, op_, cp_, _ = vgrid(iso(BOX, output="sdf", mode="implicit_box", uniform_divs=11, pad_bounds=True))
check("Pad Bounds: one voxel added on each side (13³, origin -0.6)", vp_.shape == (13, 13, 13) and np.allclose(op_, -0.6))
check("By Size 0.25:5³", vgrid(iso(BOX, output="sdf", mode="implicit_box", uniform_sampling="by_size",
                                   div_size=0.25))[0].shape == (5, 5, 5))
vbs, obs, _, _ = vgrid(iso(BOX, output="sdf", mode="implicit_box", uniform_sampling="by_size", div_size=0.4))
check("  By Size 0.4: 1 / 0.4 is not an integer -> expanded to 3 cells (1.2), symmetric on both sides (origin -0.6)",
      vbs.shape == (4, 4, 4) and np.allclose(obs, -0.6))
vnu, onu, cnu, _ = vgrid(iso(BOX, output="sdf", mode="implicit_box", uniform_sampling="non_uniform",
                             divs_x=3, divs_y=5, divs_z=7))
check("Non Uniform: (3, 5, 7) grid points per axis, voxels (0.5, 0.25, 1/6), origin -0.5",
      vnu.shape == (7, 5, 3) and np.allclose(cnu, [0.5, 0.25, 1 / 6]) and np.allclose(onu, -0.5))
tri_pts = seeds([[-1, 0, 0], [1, 0, 0], [0, 0.2, 0]])
vsp_, _, _, Qsp = vgrid(iso(tri_pts, output="sdf", mode="implicit_sphere", uniform_divs=5))
check("  Implicit Sphere radius uses the largest point distance to the bounding box center (√1.01, not the smallest 0.1)",
      np.allclose(vsp_.reshape(-1), np.linalg.norm(Qsp - [0, 0.1, 0], axis=1) - np.sqrt(1.01), atol=1e-5))
check("  Override Bounds Max ≤ Min raises", raises(lambda: iso(BOX, mode="implicit_box", override_bounds=True,
                                                           max_x=-2.0), "Bound"))
lb = build.box((2, 1, 1))
check("X Axis+Divs 5: voxel 0.5 along x, y / z 3 grid points at the same size; Y Axis+Divs 5: voxel 0.25, x 9 grid points",
      vgrid(iso(lb, output="sdf", mode="implicit_box", uniform_sampling="x_axis", uniform_divs=5))[0].shape == (3, 3, 5)
      and vgrid(iso(lb, output="sdf", mode="implicit_box", uniform_sampling="y_axis", uniform_divs=5))[0].shape == (5, 5, 9))
spc = build.sphere(0.5, 24, 16)
spn = ops.compute_normals(spc, "point")
vpc, _, _, Qpc = vgrid(iso(spn, output="sdf", mode="point_cloud", uniform_divs=11))
vpu = vgrid(iso(spc, output="sdf", mode="point_cloud", uniform_divs=11))[0]
Pn = spc.get(POINT, "P").astype(np.float64)
dmin = np.sqrt(((Qpc[:, None] - Pn[None]) ** 2).sum(-1)).min(1)
check("Point Cloud: |value| = distance to the nearest point; with N the sphere center is negative, without N all positive",
      np.allclose(np.abs(vpc.reshape(-1)), dmin, atol=1e-5) and vpc[5, 5, 5] < 0
      and np.allclose(vpu.reshape(-1), dmin, atol=1e-5))
fg_ = iso(BOX, output="fog", mode="implicit_box", uniform_divs=11)
vf_ = vinfo(fg_)[0]
check("Fog: 1 inside, 0 outside, a one-voxel-wide linear transition at the surface (0.5 on the surface), fog flag = 1",
      vf_[5, 5, 5] == 1.0 and abs(vf_[5, 5, 0] - 0.5) < 1e-6 and int(fg_.get(PRIM, "fog")[0, 0]) == 1
      and vinfo(iso(BOX, output="fog", mode="implicit_box", uniform_divs=11, offset=0.3))[0][0, 0, 0] == 0.0)
srf = iso(BOX, mode="implicit_box", uniform_divs=21, offset=0.2)
Ps = srf.get(POINT, "P").astype(np.float64)
check("Iso Surface (default output): polygons, points all near the surface 0.2 from the box (± half a voxel)",
      srf.nprims > 0 and np.abs(box_sdf(Ps) - 0.2).max() < 0.04)
check("Name is written to the volume's name", pa(iso(BOX, output="sdf", mode="implicit_box", uniform_divs=5, name="surface"), "name") == ["surface"])
check("points only with Ray Intersect raises", raises(lambda: iso(seeds([[0, 0, 0], [1, 1, 1]]), mode="ray_intersect"), "point_cloud"))


# ═══════════════════════════════════════════════════════════════ Intersection Analysis
sec("Intersection Analysis ([C]) -> new node PCG_IntersectionAnalysis")
PANEL_NODES.append("PCG_IntersectionAnalysis")


def ia(geo, **kw):
    return run("PCG_IntersectionAnalysis", geo=geo, **kw)


def fan_point(g, prim, k, u, v):
    pts = g.prim_points(int(prim))
    P_ = g.get(POINT, "P").astype(np.float64)
    a_, b_, c_ = P_[pts[0]], P_[pts[k + 1]], P_[pts[k + 2]]
    return (1 - u - v) * a_ + u * b_ + v * c_


def fan_hit(g, prim, X, u, v):
    """(u, v) on a polygon prim: reconstructed in one of its fan triangles it gives X."""
    n = len(g.prim_points(int(prim)))
    return any(np.allclose(fan_point(g, prim, k, u, v), X, atol=1e-5) for k in range(n - 2))


slant = Geometry.from_mesh(np.array([[-3, 0, -3], [3, 0, -3], [0, 0, 5]], np.float32), [[0, 1, 2]])
Ps_ = slant.get(POINT, "P").copy()
Ps_[:, 1] = 0.1 + 0.1 * Ps_[:, 0]
slant.set(POINT, "P", Ps_)
r1 = ia(BOX, geo_b=slant)
X1 = r1.get(POINT, "P").astype(np.float64)
want = {(-0.5, 0.05, 0.5), (-0.5, 0.05, -0.5), (0.5, 0.15, -0.5), (0.5, 0.15, 0.5)}
check("box × slanted plane y = 0.1 + 0.1x: one intersection per vertical edge (shared edges counted once)",
      r1.npoints == 4 and {tuple(np.round(x, 6)) for x in X1} == want)
inp, spr, suv = r1.get(POINT, "input"), r1.get(POINT, "sourceprim"), r1.get(POINT, "sourceprimuv")
check("  Input Number = [0, 1] (the box edges pierce the second input's triangles), the second Primitive Number is 0",
      np.all(inp == [0, 1]) and np.all(spr[:, 1] == 0))
ok = True
for x, pr, uv in zip(X1, spr, suv):
    ok &= np.allclose(fan_point(slant, 0, 0, uv[3], uv[4]), x, atol=1e-5)    # triangle side
    ok &= fan_hit(BOX, pr[0], x, uv[0], uv[1])                               # edge side
check("  Primitive UVW: the (u, v) on both sides reconstruct the intersection on their own faces", ok)
pl = Geometry.from_mesh(np.array([[0.1, -1, 0.1], [0.1, 1, 0.1], [0.2, -1, -0.1]], np.float32), [[0, 1, 2]], closed=False)
r2 = ia(BOX, geo_b=pl)
check("polyline × box: both segments pierce the bottom and top faces, polyline parameter u = segment number + t -> 0.25 / 0.75 / 1.25 / 1.75",
      sorted(np.round(r2.get(POINT, "sourceprimuv")[:, 0], 6).tolist()) == [0.25, 0.75, 1.25, 1.75])
check("  on the polyline side Input Number = 1 (the second input's edges pierce the first input's triangles)",
      set(map(tuple, r2.get(POINT, "input").tolist())) == {(1, 0)})
short = Geometry.from_mesh(np.array([[0.1, -1, 0.1], [0.1, 0, 0.1]], np.float32), [[0, 1]], closed=False)
check("  segments only count t ∈ [0, 1]: the one stopping in the middle of the box only pierces the bottom face", np.allclose(ia(BOX, geo_b=short).get(POINT, "P"), [[0.1, -0.5, 0.1]]))
seg_s = Geometry.from_mesh(np.array([[0, -0.5, 0], [0, 0, 0]], np.float32), [[0, 1]], closed=False)
seg_l = Geometry.from_mesh(np.array([[0, -0.5, 0], [0, 0.5, 0]], np.float32), [[0, 1]], closed=False)
check("  not counted when only the segment's extension hits the slanted plane (t = 1.2); counted once when long enough",
      ia(slant, geo_b=seg_s).npoints == 0 and ia(slant, geo_b=seg_l).npoints == 1)
quad = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], np.float32), [[0, 1, 2, 3]])
wall = Geometry.from_mesh(np.array([[-1, 0.25, -1], [2, 0.25, -1], [0.5, 0.25, 2]], np.float32), [[0, 1, 2]])
rq = ia(quad, geo_b=wall)
okq = rq.npoints == 2 and {tuple(np.round(x, 6)) for x in rq.get(POINT, "P")} == {(0.0, 0.25, 0.0), (1.0, 0.25, 0.0)}
for x, pr, uv in zip(rq.get(POINT, "P").astype(np.float64), rq.get(POINT, "sourceprim"), rq.get(POINT, "sourceprimuv")):
    okq &= np.allclose(fan_point(quad, 0, 1, uv[0], uv[1]), x, atol=1e-6) if x[0] == 0 else \
        np.allclose(fan_point(quad, 0, 0, uv[0], uv[1]), x, atol=1e-6) or np.allclose(fan_point(quad, 0, 1, uv[0], uv[1]), x, atol=1e-6)
check("  the closing edge of a quad (3 -> 0) is intersected too, uvw reconstructs the intersection on the last fan triangle (0, 2, 3)", okq)
self_one = ia(BOX)
check("only one input: a single box has no self-intersections (neighbouring faces skipped)", self_one.npoints == 0)
two = ops.merge(BOX, build.box((1, 1, 1), (0.3, 0.25, 0.2)))
r3 = ia(two)
r3b = ia(BOX, geo_b=build.box((1, 1, 1), (0.3, 0.25, 0.2)))
check("two overlapping boxes in one input: self-intersection positions match those with two separate inputs",
      r3.npoints == r3b.npoints > 0 and
      {tuple(np.round(x, 6)) for x in r3.get(POINT, "P")} == {tuple(np.round(x, 6)) for x in r3b.get(POINT, "P")}
      and np.all(r3.get(POINT, "input") == 0))
check("  negative control: with two inputs there are both [0,1] and [1,0]",
      set(map(tuple, r3b.get(POINT, "input").tolist())) == {(0, 1), (1, 0)})
check("Group A: only face 0 checked -> only intersections whose edge belongs to face 0 or that pierce face 0 remain",
      all(0 in p_ if i_[0] == 0 else p_[1] == 0 for p_, i_ in
          zip(ia(BOX, geo_b=slant, group_a="0").get(POINT, "sourceprim").tolist(),
              ia(BOX, geo_b=slant, group_a="0").get(POINT, "input").tolist())))
slg = slant.copy()
slg.set_group(PRIM, "none", np.zeros(1, bool))
check("  Group B an empty group -> no face of the second input checked -> no intersections", ia(BOX, geo_b=slg, group_b="none").npoints == 0
      and ia(BOX, geo_b=slg).npoints == 4)
check("empty attribute names are not written", ia(BOX, geo_b=slant, input_attribute="", uvw_attribute="").get(POINT, "input") is None
      and ia(BOX, geo_b=slant, input_attribute="", uvw_attribute="").get(POINT, "sourceprimuv") is None)


# ═══════════════════════════════════════════════════════════════ File Merge
sec("File Merge ([C]) -> new node PCG_FileMerge")
PANEL_NODES.append("PCG_FileMerge")
import shutil, tempfile                                    # noqa: E402,E401
from comfyui_pcg.geo import geocache as GC                 # noqa: E402
from comfyui_pcg.geo.convert import write_obj              # noqa: E402

TMP = tempfile.mkdtemp(prefix="s9_filemerge_")
try:
    for k in range(4):
        pts = np.array([[k, 0, 0], [k, 1, 0], [k, 2, 0]], np.float32)
        g_ = Geometry.from_points(pts)
        g_.set(POINT, "slice", np.array([[k], [k], [(k + 1) % 4]], np.int32))   # the 3rd point "belongs to someone else"
        GC.save(os.path.join(TMP, f"p.{k}.npz"), g_)
    write_obj(build.box(), os.path.join(TMP, "m.7.obj"))
    write_obj(build.box((1, 1, 1), (3, 0, 0)), os.path.join(TMP, "m.9.obj"))

    def fm(**kw):
        return run("PCG_FileMerge", **kw)

    f1 = fm(file=os.path.join(TMP, "p.$SLICE.npz"))
    check("Merge Range 0, 3, 1: reads 4 cache files, 12 points, in order (x = 0,0,0,1,1,1...)",
          f1.npoints == 12 and np.allclose(f1.get(POINT, "P")[:, 0], np.repeat(np.arange(4), 3)))
    f2 = fm(file=os.path.join(TMP, "p.$SLICE.npz"), merge_start=3, merge_end=0, merge_inc=-2)
    check("  walking backwards 3, 1: reads only two, 3 first then 1", np.allclose(f2.get(POINT, "P")[:, 0], [3, 3, 3, 1, 1, 1]))
    f3 = fm(file=os.path.join(TMP, "p.$SLICE.npz"), delete_other=True)
    check("Delete Points from Other Files: each file drops the point whose slice ≠ its number -> 8 points",
          f3.npoints == 8 and np.all(f3.get(POINT, "slice")[:, 0] == np.repeat(np.arange(4), 2)))
    f4 = fm(file=os.path.join(TMP, "m.${N}.obj"), merge_variable="N", merge_start=7, merge_end=9, merge_inc=2)
    check("Merge Variable = N, ${N} syntax, OBJ: two boxes 12 faces", f4.nprims == 12
          and abs(float(f4.get(POINT, "P")[:, 0].max()) - 3.5) < 1e-6)
    check("Missing File = error (default): raises when number 8 is missing",
          raises(lambda: fm(file=os.path.join(TMP, "m.$SLICE.obj"), merge_start=7, merge_end=9), "8"))
    f5 = fm(file=os.path.join(TMP, "m.$SLICE.obj"), merge_start=7, merge_end=9, missing_file="no_geometry")
    check("  No Geometry: skips the missing one, reads the rest", f5.nprims == 12)
    check("file name without $SLICE raises", raises(lambda: fm(file=os.path.join(TMP, "p.0.npz")), "SLICE"))
    check("increment 0 raises", raises(lambda: fm(file=os.path.join(TMP, "p.$SLICE.npz"), merge_inc=0), "increment"))
    ch1 = M["PCG_FileMerge"].IS_CHANGED(file=os.path.join(TMP, "p.$SLICE.npz"))
    GC.save(os.path.join(TMP, "p.2.npz"), Geometry.from_points(np.zeros((5, 3), np.float32)))
    ch2 = M["PCG_FileMerge"].IS_CHANGED(file=os.path.join(TMP, "p.$SLICE.npz"))
    check("IS_CHANGED: the fingerprint changes after a slice file is rewritten", ch1 != ch2 and ch1.count("|") == 4)
finally:
    shutil.rmtree(TMP, ignore_errors=True)

# @@NODES@@

# ═══════════════════════════════════════════════════════════════ panel
sec("Panel specs")
import comfyui_pcg.panel_specs as PS                     # noqa: E402
for k in PANEL_NODES:
    lay = PANEL.check_layout(k, M[k].INPUT_TYPES())
    check(f"{k}: spec self-check clean", not lay, lay)
    sp = PS.SPECS[k]
    it = M[k].INPUT_TYPES()
    ws = [n for part in ("required", "optional") for n, v in it.get(part, {}).items()
          if not (isinstance(v[0], str) and v[0].isupper() and v[0] not in
                  ("INT", "FLOAT", "STRING", "BOOLEAN"))]
    rowm = {m for v in sp["inputs"].values() if isinstance(v.get("row"), dict) for m in v["row"]["members"]}
    miss = [n for n in ws if n not in sp["order"] and n not in rowm]
    check(f"{k}: every widget is in order (or in some row)", not miss, miss)
    bad = []
    for n in ws:
        spec = [v[n] for v in it.values() if n in v][0]
        if isinstance(spec[0], (list, tuple)):
            menu = sp["inputs"].get(n, {}).get("menu")
            if menu is None or sorted(menu) != sorted(spec[0]):
                bad.append(n)
    check(f"{k}: every token of every combo has a Houdini label", not bad, bad)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
