"""
pcg100 audit pack s8_uv: UV parameters / nodes completed against the SideFX docs.

  UV Flatten   Flattening Method (Spectral SCP / Angle Based ABF), Group (flatten only these prims),
               Preserve Seams, Vertex Pins (pinned to the original uv), Output Groups (Seams / Constrained Islands)
  UV Layout    Scale: Fixed, Island Rotation Step (No rotation / Rotation step / Custom),
               Scale Islands to Match Surface Areas, Pack into: UDIM Tiles,
               Nonpacked polygons / Island number outputs
  UV Project   3D transform of the projector (Translate / Rotate / Scale / Pivot / Rotate Order),
               U Range / V Range, Inner Radius
  UV Autoseam  Include / Exclude edges, Island attribute, Splitting: Existing Islands
  UV Pelt      new node: Spring Relaxation / Tutte Barycentric / Discrete Harmonic, boundary pulled onto the frame
  UV Unwrap    new node: regions by plane, Strip / Square layout, None / Uniform / Stretch scaling

References are all hand-computable numbers (edge lengths of isometric unwraps, known angles, point counts, area ratios). "Bit-identical to before the change at defaults"
uses digests computed from the same calls before the change (commit f210100), hard-coded in GOLDEN; `--digests` prints the current digests.
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
from comfyui_pcg.geo import uvflatten as UVF, uvlayout as UVL, topology as TOPO, groups as GRP  # noqa: E402
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


def names(nid):
    t = M[nid].INPUT_TYPES()
    return list(t.get("required", {})) + list(t.get("optional", {}))


def digest(g):
    h = hashlib.sha1()
    h.update(np.ascontiguousarray(g.vertex_point).tobytes())
    h.update(np.ascontiguousarray(g.prim_offset).tobytes())
    for cls in (POINT, VERTEX, PRIM, DETAIL):
        for k in sorted(g.attribs[cls]):
            v = g.attribs[cls][k]
            h.update(f"{cls}/{k}/{v.dtype}/{v.shape}".encode())
            # the uv solve is iterative: quantize to 1e-6 before comparing, so different BLAS thread counts don't cause last-digit jitter
            if v.dtype.kind == "f":
                v = np.round(np.asarray(v, np.float64), 6)
            h.update(np.ascontiguousarray(v).tobytes() if v.dtype.kind != "O"
                     else repr(v.tolist()).encode())
    for cls in (POINT, VERTEX, PRIM):
        for k in sorted(g.groups[cls]):
            h.update(f"g/{cls}/{k}".encode())
            h.update(np.ascontiguousarray(g.groups[cls][k]).tobytes())
    for k in sorted(g.edge_groups):
        h.update(f"e/{k}".encode())
        h.update(np.ascontiguousarray(g.edge_groups[k]).tobytes())
    return h.hexdigest()[:16]


# ── fixed input geometry
def G_grid():
    return build.grid(4.0, 2.0, 9, 5)


def G_sphere():
    return build.sphere(1.0, 16, 10)


def G_box():
    return build.box((2, 1, 1), divisions=(3, 2, 2))


def G_tube():
    return build.tube(1.0, 1.0, 2.0, 12, 4)


def G_torus():
    return build.torus(1.0, 0.3, 8, 16)


def old_cases():
    """Calls that existed before the change (old parameters only)."""
    out = {}
    sph = G_sphere()
    seams = run("PCG_UVAutoSeams", geo=sph)
    out["seam_both"] = digest(seams)
    out["seam_angle"] = digest(run("PCG_UVAutoSeams", geo=G_box(), mode="angle", min_angle=30.0))
    out["seam_charts"] = digest(run("PCG_UVAutoSeams", geo=sph, mode="charts", cone_angle=50.0,
                                    output_chart_attribute="chart"))
    out["seam_grp"] = digest(run("PCG_UVAutoSeams", geo=sph, group="0-40", make_disks=False))
    out["flat_grid"] = digest(run("PCG_UVFlatten", geo=G_grid()))
    out["flat_sph"] = digest(run("PCG_UVFlatten", geo=seams, seam_group="seams",
                                 distortion_attribute="dist"))
    out["flat_pack"] = digest(run("PCG_UVFlatten", geo=seams, seam_group="seams", pack=True))
    out["flat_arap"] = digest(run("PCG_UVFlatten", geo=seams, seam_group="seams", arap_iterations=3))
    bx = run("PCG_UVProject", geo=G_box(), mode="box")
    out["proj_box"] = digest(bx)
    for m in ("planar", "cylindrical", "spherical", "toroidal", "plastic_wrap"):
        out[f"proj_{m}"] = digest(run("PCG_UVProject", geo=G_torus() if m == "toroidal" else sph,
                                      mode=m, axis="y"))
    out["proj_xf"] = digest(run("PCG_UVProject", geo=sph, mode="cylindrical", axis="z", fit_to_01=False,
                                translate_u=0.2, rotate=30.0, scale_v=2.0, group="0-20"))
    out["proj_pt"] = digest(run("PCG_UVProject", geo=G_grid(), mode="planar", attribute_class="point"))
    out["lay_shelf"] = digest(run("PCG_UVLayout", geo=bx))
    out["lay_indiv"] = digest(run("PCG_UVLayout", geo=bx, scale_mode="individual", rotate_to_fit=False))
    out["lay_raster"] = digest(run("PCG_UVLayout", geo=bx, method="raster", pack_resolution=64))
    out["lay_grp"] = digest(run("PCG_UVLayout", geo=bx, group="0-3", padding=0.05))
    return out


# digests from running old_cases() before the change (f210100)
GOLDEN = {
    "seam_both": "21b15b2a645e8614",
    "seam_angle": "51e52d100c22cc99",
    "seam_charts": "7c591286b5493425",
    "seam_grp": "f3859f6b708dc0b9",
    "flat_grid": "30a42ebc73110d82",
    "flat_sph": "c4adf6224eb14782",
    "flat_pack": "2363fd4897e44632",
    "flat_arap": "a27c69a3e0848360",
    "proj_box": "395be26ca549ecbe",
    "proj_planar": "44576c487dbb0d52",
    "proj_cylindrical": "d68b7fdd0af894e5",
    "proj_spherical": "45b5e58514e70ace",
    "proj_toroidal": "b69691323a4fdbbb",
    "proj_plastic_wrap": "7b1fc408451a9b20",
    "proj_xf": "e40ad95c07ae9e1b",
    "proj_pt": "0bbf084de9d76448",
    "lay_shelf": "b6e535dd38f5af27",
    "lay_indiv": "89bdf150c9507a8a",
    "lay_raster": "33bde84927c04159",
    "lay_grp": "15ea38aab492d807"
}

if "--digests" in sys.argv:
    import json
    print(json.dumps(old_cases(), indent=1))
    sys.exit(0)


# ═══════════════════════════════════════════════════════════════ Regression
sec("Bit-identical to before the change at defaults")
now = old_cases()
check(f"output digests of all {len(GOLDEN)} old calls unchanged", len(GOLDEN) >= 18 and now == GOLDEN,
      {k: (GOLDEN.get(k), v) for k, v in now.items() if GOLDEN.get(k) != v})
r_ = names("PCG_UVFlatten")
check("UV Flatten: old parameter names and order untouched, new ones appended",
      r_[:12] == ["geo", "seam_group", "attribute_name", "normalize", "pack", "padding", "group",
                  "iterations", "tolerance", "distortion_attribute", "arap_iterations", "method"], r_)


def uvs(g):
    return np.asarray(g.get(VERTEX, "uv"), np.float64)[:, :2]


def edge_lens(g):
    """Each corner to the next corner: 3D edge length, uv edge length."""
    P = np.asarray(g.get(POINT, "P"), np.float64)
    uv = uvs(g)
    nx = g.next_corner()
    vp = g.vertex_point
    return np.linalg.norm(P[vp] - P[vp[nx]], axis=1), np.linalg.norm(uv - uv[nx], axis=1)


def corner_angles_uv(g):
    """Each corner after fan triangulation: 3D angle, uv angle, sign of the uv signed area, the corner's point."""
    P = np.asarray(g.get(POINT, "P"), np.float64)
    uv = uvs(g)
    a3, a2, sg, pt = [], [], [], []
    po = g.prim_offset
    vp = g.vertex_point
    for f in range(g.nprims):
        c = np.arange(po[f], po[f + 1])
        for j in range(1, len(c) - 1):
            t = (c[0], c[j], c[j + 1])
            for k in range(3):
                a, b, d = t[k], t[(k + 1) % 3], t[(k + 2) % 3]
                u, v = P[vp[b]] - P[vp[a]], P[vp[d]] - P[vp[a]]
                a3.append(np.arctan2(np.linalg.norm(np.cross(u, v)), u @ v))
                u, v = uv[b] - uv[a], uv[d] - uv[a]
                a2.append(np.arctan2(abs(u[0] * v[1] - u[1] * v[0]), u @ v))
                pt.append(vp[a])
            A, B = uv[t[1]] - uv[t[0]], uv[t[2]] - uv[t[0]]
            sg.append(np.sign(A[0] * B[1] - A[1] * B[0]))
    return np.array(a3), np.array(a2), np.array(sg), np.array(pt)


def cyl_patch():
    """A piece of a cylinder (developable): the grid's x wrapped into an angle. Isometric unwrap edge length = 3D edge length."""
    g = build.grid(2.0, 1.0, 9, 5)
    P = np.asarray(g.get(POINT, "P"), np.float64)
    g.set(POINT, "P", np.stack([np.sin(P[:, 0]), P[:, 2], np.cos(P[:, 0])], 1).astype(np.float32))
    return g


def saddle():
    g = build.grid(2.0, 2.0, 9, 9, connectivity="triangles")
    P = np.asarray(g.get(POINT, "P"), np.float64)
    P[:, 1] = 0.6 * (P[:, 0] ** 2 - P[:, 2] ** 2) + 0.3 * P[:, 0] ** 2 * P[:, 2]
    g.set(POINT, "P", P.astype(np.float32))
    return g


# ═══════════════════════════════════════════════════════════════ UV Flatten
sec("UV Flatten:Flattening Method")
opts_m = [list(v["method"][0]) for v in M["PCG_UVFlatten"].INPUT_TYPES().values() if "method" in v][0]
check("menu = lscm (original, default) / scp / abf", opts_m == ["lscm", "scp", "abf"], opts_m)
cp = cyl_patch()
for m in ("scp", "abf"):
    l3, l2 = edge_lens(run("PCG_UVFlatten", geo=cp, method=m, normalize=False))
    check(f"{m}: a developable cylinder strip unwraps isometrically (every edge's uv length = 3D length, error < 1e-5)",
          np.abs(l3 - l2).max() < 1e-5, np.abs(l3 - l2).max())
for m in ("scp", "abf"):
    l3, l2 = edge_lens(run("PCG_UVFlatten", geo=G_grid(), method=m, normalize=False))
    check(f"{m}: a flat grid is laid out as is (edge length error < 1e-5)", np.abs(l3 - l2).max() < 1e-5)

sd = saddle()
res = {m: run("PCG_UVFlatten", geo=sd, method=m, normalize=False) for m in ("lscm", "scp", "abf")}
a3, _, _, cpt = corner_angles_uv(res["lscm"])
# ABF ideal angles β: 3D angles, scaled around interior points so they sum to 2π
P_sd = np.asarray(sd.get(POINT, "P"), np.float64)
ii = np.arange(sd.npoints)
gx, gz = ii % 9, ii // 9
interior = (gx > 0) & (gx < 8) & (gz > 0) & (gz < 8)
tot = np.bincount(cpt, weights=a3, minlength=sd.npoints)
beta = np.where(interior[cpt], a3 * 2 * np.pi / tot[cpt], a3)
E = {}
for m, g in res.items():
    _, a2, sg, _ = corner_angles_uv(g)
    E[m] = float((((a2 - beta) / beta) ** 2).sum())
    check(f"{m}: no flips when unwrapping a saddle (all triangle uv signed areas have the same sign)", (sg == sg[0]).all())
check("abf: ABF energy Σ((α−β)/β)² is the smallest of the three (that's what it minimizes)",
      E["abf"] < E["scp"] and E["abf"] < E["lscm"], E)
T_ = sd.nprims
tri_w = sd.vertex_point.reshape(-1, 3).astype(np.int64)
loc = UVF._abf_shape(P_sd, tri_w, 2000, 1e-8)
x2, x3, y3 = loc
alpha0 = np.arctan2(y3, x3)
_, a2, _, _ = corner_angles_uv(res["abf"])
check("abf: solved angles satisfy the constraints, reconstruction exact (angles in uv = ABF angles, error < 1e-6)",
      np.abs(a2.reshape(-1, 3)[:, 0] - alpha0).max() < 1e-6,
      np.abs(a2.reshape(-1, 3)[:, 0] - alpha0).max())
check("negative control: abf and lscm differ on a saddle", np.abs(uvs(res["abf"]) - uvs(res["lscm"])).max() > 1e-3)

# SCP: residual of the generalized eigenproblem A x = λ B x
rows, cols, vals, nrow, ncol = UVF._build(P_sd, tri_w)
xs, _, _ = UVF._solve_scp(P_sd, tri_w, 2000, 1e-10)
x = np.concatenate([xs[:, 0], xs[:, 1]])
Ax = np.bincount(cols, weights=vals * np.bincount(rows, weights=vals * x[cols], minlength=nrow)[rows],
                 minlength=ncol)
uq, cnt, _ = UVF._tri_edges(tri_w)
be = uq[cnt == 1]
Lb = np.linalg.norm(P_sd[be[:, 0]] - P_sd[be[:, 1]], axis=1)
mb = np.bincount(be[:, 0], weights=Lb / 2, minlength=len(P_sd)) + np.bincount(be[:, 1], weights=Lb / 2, minlength=len(P_sd))
Bx = np.concatenate([mb, mb]) * x
lam = float(x @ Ax) / float(x @ Bx)
check("scp: result is an eigenvector of A x = λ B x (relative residual < 1e-4)",
      np.linalg.norm(Ax - lam * Bx) / np.linalg.norm(Ax) < 1e-4, np.linalg.norm(Ax - lam * Bx) / np.linalg.norm(Ax))
check("scp: B-orthogonal to constants (boundary-weighted mean of u, v = 0)",
      abs(float(mb @ xs[:, 0])) < 1e-8 and abs(float(mb @ xs[:, 1])) < 1e-8)
# along random B-orthogonal directions the Rayleigh quotient is never smaller (smallest eigenvalue)
rng = np.random.default_rng(1)
worse = []
for _ in range(20):
    z = x + 0.05 * rng.standard_normal(len(x))
    Bd = np.concatenate([mb, mb])
    for e in (np.r_[np.ones(len(mb)), np.zeros(len(mb))], np.r_[np.zeros(len(mb)), np.ones(len(mb))]):
        z = z - (e @ (Bd * z)) / (e @ (Bd * e)) * e
    Az = np.bincount(cols, weights=vals * np.bincount(rows, weights=vals * z[cols], minlength=nrow)[rows], minlength=ncol)
    worse.append(float(z @ Az) / float(z @ (Bd * z)) >= lam - 1e-12)
check("scp: λ is the smallest (Rayleigh quotients of 20 perturbed directions all >= λ)", all(worse))
check("negative control: scp and lscm differ on a saddle (different edge-length ratios)",
      np.abs(edge_lens(res["scp"])[1] - edge_lens(res["lscm"])[1]).max() > 1e-3)

sec("UV Flatten: Group (flatten only these prims)")
gg = G_grid()                                                   # has its own point uv
fg = run("PCG_UVFlatten", geo=gg, flatten_group="0-7", normalize=False)
sel = np.zeros(gg.nprims, bool)
sel[:8] = True
vsel = np.repeat(sel, gg.prim_sizes())
old_uv = np.asarray(gg.get(POINT, "uv"), np.float64)[gg.vertex_point]
check("unselected prims: uv unchanged (= the original point uv)", np.allclose(uvs(fg)[~vsel], old_uv[~vsel]))
l3, l2 = edge_lens(fg)
check("selected prims: flat, unwrapped isometrically", np.abs(l3 - l2)[vsel].max() < 1e-5)
check("negative control: without Group all prims are re-unwrapped (uv differs from the original)",
      not np.allclose(uvs(run("PCG_UVFlatten", geo=gg, normalize=False))[~vsel], old_uv[~vsel]))
sph = G_sphere()
P_s = np.asarray(sph.get(POINT, "P"))
top = " ".join(str(k) for k in range(sph.nprims) if P_s[sph.prim_points(k)][:, 1].min() > -0.01)
try:
    hs = run("PCG_UVFlatten", geo=sph, flatten_group=top)
    ok_h = True
except ValueError:
    ok_h = False
try:
    run("PCG_UVFlatten", geo=sph)
    ok_full = True
except ValueError:
    ok_full = False
check("closed sphere with only the upper hemisphere: the selection boundary acts as a seam, it unwraps; the whole sphere still raises", ok_h and not ok_full)

sec("UV Flatten: Preserve Seams + Output Seams group")
bxp = run("PCG_UVProject", geo=G_box(), mode="box")              # 6 islands
try:
    run("PCG_UVFlatten", geo=bxp)
    closed_err = False
except ValueError:
    closed_err = True
fb = run("PCG_UVFlatten", geo=bxp, preserve_seams=True, normalize=False, output_seams="cut")
l3, l2 = edge_lens(fb)
check("box + box projection: without Preserve Seams it's a closed piece and raises; with it, cut along the 6 islands, every face isometric",
      closed_err and np.abs(l3 - l2).max() < 1e-5)
check("Output Seams = the box's 12 edges (the 4 along x have 2 segments each) = 16 edges",
      len(fb.edge_groups["cut"]) == 16, len(fb.edge_groups["cut"]))
fs = run("PCG_UVFlatten", geo=run("PCG_UVAutoSeams", geo=sph), seam_group="seams", output_seams="o")
check("Output Seams contains only interior edges from the given seams (on the sphere = the Seams group itself)",
      sorted(map(tuple, np.sort(fs.edge_groups["o"], 1).tolist()))
      == sorted(map(tuple, np.sort(run("PCG_UVAutoSeams", geo=sph).edge_groups["seams"], 1).tolist())))
check("no group written when Output Seams is empty", "cut" not in run("PCG_UVFlatten", geo=bxp, preserve_seams=True).edge_groups)

sec("UV Flatten:Vertex Pins")
pr = run("PCG_UVProject", geo=G_grid(), mode="planar", axis="y")
pr = run("PCG_UVTransform", geo=pr, rotate=30.0, scale_u=0.5, scale_v=0.5, translate_u=0.3)
target = uvs(pr)
corners = "0 44"                                                 # two opposite corners of the 9x5 grid
for m in ("lscm", "scp", "abf"):
    fp = run("PCG_UVFlatten", geo=pr, method=m, pin_group=corners)
    check(f"{m}: two corners pinned, the whole flat grid lands on the similarity transform given by the pins (= original uv, error < 1e-5)",
          np.abs(uvs(fp) - target).max() < 1e-5, np.abs(uvs(fp) - target).max())
f1 = run("PCG_UVFlatten", geo=pr, pin_group="0", normalize=True)
l3, l2 = edge_lens(f1)
pc0 = np.nonzero(pr.vertex_point == 0)[0]
check("one point pinned: unwrapped at world scale (no Normalize), the whole piece translated to the pin",
      np.abs(l3 - l2).max() < 1e-5 and np.abs(uvs(f1)[pc0] - target[pc0]).max() < 1e-6)
check("negative control: without pins it's Normalized to 0..1, different from the original uv",
      np.abs(uvs(run("PCG_UVFlatten", geo=pr)) - target).max() > 1e-2)
two = ops.merge(pr, ops.transform(pr, translate=(10, 0, 0)))
fc = run("PCG_UVFlatten", geo=two, pin_group="0 44", output_constrained="pinned")
gm = np.asarray(fc.groups[PRIM]["pinned"], bool)
check("Constrained Islands group = the 32 prims of the pinned piece (the other piece has no pins, not in the group)",
      gm[:32].all() and not gm[32:].any())
check("  the pinned piece lands on the pins, the other is Normalized as usual (within 0..1)",
      np.abs(uvs(fc)[:pr.nvertices] - target).max() < 1e-5
      and uvs(fc)[pr.nvertices:].min() > -1e-6 and uvs(fc)[pr.nvertices:].max() < 1 + 1e-6)
try:
    run("PCG_UVFlatten", geo=build.grid(1, 1, 3, 3), pin_group="0",
        attribute_name="nouv")
    pin_err = False
except KeyError:
    pin_err = True
check("pinning to a nonexistent uv: raises clearly, doesn't pin blindly", pin_err)

sec("UV Flatten: targeted tests added (survivors of mutation testing)")
# KKT: at the ABF solution the objective gradient W(α−β) must lie in the column space of the constraint gradient Jᵀ (β computed independently here)
Tn = len(tri_w)
xx2, xx3, yy3 = UVF._abf_shape(P_sd, tri_w, 2000, 1e-8)
A0 = np.arctan2(yy3, xx3)
A1 = np.arctan2(yy3, xx2 - xx3)
al = np.stack([A0, A1, np.pi - A0 - A1], 1).reshape(-1)
th3 = UVF._corner_angles(P_sd, tri_w).reshape(-1)
cw_ = tri_w.reshape(-1)
inn = interior[cw_]
tot_ = np.bincount(cw_, weights=th3, minlength=sd.npoints)
bt = np.where(inn, th3 * 2 * np.pi / tot_[cw_], th3)
ivs = np.nonzero(interior)[0]
Jd = np.zeros((Tn + 2 * len(ivs), 3 * Tn))
for t_ in range(Tn):
    Jd[t_, 3 * t_:3 * t_ + 3] = 1
cot_ = 1 / np.tan(al)
for r_i, v in enumerate(ivs):
    for c in np.nonzero(cw_ == v)[0]:
        t_, k_ = divmod(c, 3)
        Jd[Tn + r_i, c] = 1
        Jd[Tn + len(ivs) + r_i, 3 * t_ + (k_ + 1) % 3] += cot_[3 * t_ + (k_ + 1) % 3]
        Jd[Tn + len(ivs) + r_i, 3 * t_ + (k_ + 2) % 3] -= cot_[3 * t_ + (k_ + 2) % 3]
grad = (al - bt) / bt ** 2
lam_, *_ = np.linalg.lstsq(Jd.T, grad, rcond=None)
kkt = np.linalg.norm(Jd.T @ lam_ - grad) / np.linalg.norm(grad)
check("abf: KKT holds -- objective gradient lies in the span of the constraint gradients (relative residual < 1e-5)", kkt < 1e-5, kkt)
# _pcg itself: a small symmetric positive-definite system solved to 1e-12
rng2 = np.random.default_rng(3)
Q_ = rng2.standard_normal((30, 30))
A_ = Q_ @ Q_.T + 30 * np.eye(30)
b_ = rng2.standard_normal(30)
xs_, _ = UVF._pcg(lambda z: A_ @ z, np.diag(A_).copy(), b_, np.zeros(30), 500, 1e-12)
check("_pcg: 30-dim SPD system solved to relative residual 1e-10", np.linalg.norm(A_ @ xs_ - b_) / np.linalg.norm(b_) < 1e-10)
# with two points pinned the initial guess is already the exact solution (plane + similarity transform), CG needs no steps
sq = build.grid(2.0, 2.0, 5, 5)
Pq = np.asarray(sq.get(POINT, "P"), np.float64)
trq = sq.vertex_point.reshape(-1, 4)
trq = np.concatenate([trq[:, [0, 1, 2]], trq[:, [0, 2, 3]]])
wv = np.array([[0.2, 0.1], [0.9, 0.6]])
_, kq, _ = UVF._solve_island(Pq, trq, 2000, 1e-8, pins=(np.array([0, 24]), wv))
check("initial guess with two pins = similarity transform placing the fitted plane onto the pins: on a flat grid CG converges in 0~1 steps", kq <= 1, kq)
# Group + Normalize: normalized by the selected piece only
fgn = run("PCG_UVFlatten", geo=gg, flatten_group="0-7")
check("Group + Normalize: the selected piece fills 0..1 by itself (unselected pieces don't take part in scaling)",
      abs(uvs(fgn)[vsel].max() - 1.0) < 1e-6 and uvs(fgn)[vsel].min() > -1e-6)
# the unselected part is **another closed piece**: shouldn't raise
mix = ops.merge(G_grid(), G_sphere())
try:
    run("PCG_UVFlatten", geo=mix, flatten_group="0-31")
    mix_ok = True
except ValueError:
    mix_ok = False
check("a closed sphere outside the Group (not unwrapped): doesn't raise", mix_ok)
# pinned islands skip ARAP (with it the pins would no longer be in place)
sp = run("PCG_UVProject", geo=saddle(), mode="planar", axis="y")
fa = run("PCG_UVFlatten", geo=sp, pin_group="0 80", arap_iterations=3)
pcs = np.nonzero(np.isin(sp.vertex_point, [0, 80]))[0]
check("saddle + two pins + ARAP Iterations 3: pins still in place", np.abs(uvs(fa)[pcs] - uvs(sp)[pcs]).max() < 1e-6)
# unselected prims: vertex uv unchanged
fgv = run("PCG_UVFlatten", geo=pr, flatten_group="0-7", normalize=False)
check("Group: vertex uv of unselected prims kept as is", np.allclose(uvs(fgv)[~vsel], target[~vsel]))
# Output Seams: geometric boundaries don't count as seams; seams outside the Group aren't output
ga = G_grid()
ga.set_edge_group("all", TOPO.topology(ga).edge_points)
oa = run("PCG_UVFlatten", geo=ga, seam_group="all", output_seams="o")
check("Output Seams: Seams given as all 76 edges, only the 52 interior edges are output", len(oa.edge_groups["o"]) == 52,
      len(oa.edge_groups["o"]))
ob = run("PCG_UVFlatten", geo=ga, seam_group="all", flatten_group="0", output_seams="o")
check("  Group = the cell at corner 0: only the 2 interior edges touching it are output", len(ob.edge_groups["o"]) == 2,
      len(ob.edge_groups["o"]))
oc = run("PCG_UVFlatten", geo=two, flatten_group="0-15", pin_group="0", output_constrained="c")
cm = np.asarray(oc.groups[PRIM]["c"], bool)
check("Constrained Islands contains only prims in the Group", cm[:16].all() and not cm[16:].any(), int(cm.sum()))
# pinned to point uv: the point uv a square grid ships with is a similarity transform of position
sqg = build.grid(2.0, 2.0, 5, 5)
fpp = run("PCG_UVFlatten", geo=sqg, pin_group="0 24")
check("pinned to point uv (point uv read when there is no vertex uv): square grid = its own uv",
      np.abs(uvs(fpp) - np.asarray(sqg.get(POINT, "uv"), np.float64)[sqg.vertex_point]).max() < 1e-5)
check("panel: UV Flatten spec self-check passes", not PANEL.check_layout("PCG_UVFlatten", M["PCG_UVFlatten"].INPUT_TYPES()))


# ═══════════════════════════════════════════════════════════════ UV Layout
sec("UV Layout: old parameters / menus untouched")
r_ = names("PCG_UVLayout")
check("old parameter names and order untouched, new ones appended",
      r_[:10] == ["geo", "group", "attribute_class", "attribute_name", "scale_mode", "padding",
                  "rotate_to_fit", "method", "pack_resolution", "island_rotation"], r_)
it = lambda n, k: [list(v[k][0]) for v in M[n].INPUT_TYPES().values() if k in v][0]   # noqa: E731
check("Scale menu: uniform / individual in place, fixed appended at the end",
      it("PCG_UVLayout", "scale_mode") == ["uniform", "individual", "fixed"])


def isl_boxes(g, cls=VERTEX):
    """uv bounding box (lo, hi) and island number for each island (by uv connectivity)."""
    isl = UVL.islands(g, "uv")
    uv = np.asarray(g.get(cls, "uv"), np.float64)[:, :2]
    own = np.repeat(isl, g.prim_sizes())
    if cls == POINT:
        uv = uv[g.vertex_point]
    out = {}
    for k in np.unique(isl):
        q = uv[own == k]
        out[int(k)] = (q.min(0), q.max(0))
    return out, isl


def overlap_free(boxes, tol=1e-9):
    b = list(boxes.values())
    for i in range(len(b)):
        for j in range(i + 1, len(b)):
            lo = np.maximum(b[i][0], b[j][0])
            hi = np.minimum(b[i][1], b[j][1])
            if (hi - lo > tol).all():
                return False
    return True


sec("UV Layout:Scale = Fixed")
# box 2×1×1, box projection: ±x give two 1×1 islands, ±y, ±z four 2×1 islands (world scale)
bx_ = run("PCG_UVProject", geo=G_box(), mode="box", fit_to_01=False)     # uv = world scale
lf = run("PCG_UVLayout", geo=bx_,
         scale_mode="fixed", fixed_scale=0.2, rotate_to_fit=False, padding=0.0, nonpacked_group="np")
bb, isl_b = isl_boxes(lf)
ext = sorted(tuple(np.round(h - l, 6)) for l, h in bb.values())
check("Fixed 0.2: each island's uv size = world size × 0.2 (two 0.2×0.2, four 0.4×0.2 or transposed)",
      ext[:2] == [(0.2, 0.2)] * 2 and all(sorted(e) == [0.2, 0.4] for e in ext[2:]), ext)
check("  all within 0..1, no overlap, Nonpacked group empty",
      all(l.min() > -1e-9 and h.max() < 1 + 1e-9 for l, h in bb.values()) and overlap_free(bb)
      and not np.asarray(lf.groups[PRIM]["np"]).any())
lu = run("PCG_UVLayout", geo=bx_, rotate_to_fit=False, padding=0.0)
bu, _ = isl_boxes(lu)
check("negative control: uniform finds the largest scale, size isn't 0.2×",
      sorted(tuple(np.round(h - l, 6)) for l, h in bu.values()) != ext)
lf6 = run("PCG_UVLayout", geo=bx_, scale_mode="fixed", fixed_scale=0.6, rotate_to_fit=False,
          padding=0.0, nonpacked_group="np", target_attribute="tgt")
npm = np.asarray(lf6.groups[PRIM]["np"], bool)
b6, _ = isl_boxes(lf6)
inside = [k for k, (l, h) in b6.items() if l.min() > -1e-9 and h.max() < 1 + 1e-9]
check("Fixed 0.6: the four 1.2-wide islands don't fit, only one of the two 0.6 squares fits -- 9 prims go into Nonpacked",
      int(npm.sum()) == 9 and len(inside) == 1, (int(npm.sum()), len(inside)))
uv6 = uvs(lf6)
own6 = np.repeat(npm, lf6.prim_sizes())
check("  islands that don't fit are placed below the target (v < 0), Assigned Target = -1; placed ones = 0",
      uv6[own6][:, 1].max() < 1e-9
      and set(np.asarray(lf6.get(PRIM, "tgt"))[npm, 0].tolist()) == {-1}
      and set(np.asarray(lf6.get(PRIM, "tgt"))[~npm, 0].tolist()) == {0})

sec("UV Layout:Island Rotation Step")
strip = build.grid(1.0, 0.1, 2, 2)
strip = run("PCG_UVProject", geo=strip, mode="planar", axis="y", fit_to_01=False)
strip = run("PCG_UVTransform", geo=strip, rotate=45.0, pivot_u=0.0, pivot_v=0.0)
ls = run("PCG_UVLayout", geo=strip, rotate_to_fit=False, island_rotation="step", rotation_step=45.0)
e = uvs(ls).max(0) - uvs(ls).min(0)
check("a 1×0.1 strip at 45°, Rotation Step 45: straightened, bounding box 10:1",
      abs(max(e) / min(e) - 10.0) < 1e-4, e)
ln = run("PCG_UVLayout", geo=strip, rotate_to_fit=False, island_rotation="none")
e2 = uvs(ln).max(0) - uvs(ln).min(0)
check("negative control: No Rotation doesn't rotate, bounding box is square", abs(e2[0] / e2[1] - 1.0) < 1e-4, e2)
lc = run("PCG_UVLayout", geo=strip, rotate_to_fit=False, island_rotation="custom", rotation_divisions=8)
check("Custom 8 divisions = Step 45°", np.allclose(uvs(lc), uvs(ls)))
lc3 = run("PCG_UVLayout", geo=strip, rotate_to_fit=False, island_rotation="custom", rotation_divisions=3)
e3 = uvs(lc3).max(0) - uvs(lc3).min(0)
check("negative control: Custom 3 divisions (0/120/240°) can't straighten it", abs(max(e3) / min(e3) - 10.0) > 1.0, e3)
lr90 = run("PCG_UVLayout", geo=bx_, method="raster", pack_resolution=64, island_rotation="step",
           rotation_step=90.0)
check("Raster + Step 90° = the original Raster (it already tried 4 × 90°)",
      np.array_equal(uvs(lr90), uvs(run("PCG_UVLayout", geo=bx_, method="raster", pack_resolution=64))))
flat = run("PCG_UVProject", geo=build.grid(1.0, 0.1, 2, 2), mode="planar", axis="y", fit_to_01=False)


def diam(g):
    q = uvs(g)
    return float(np.linalg.norm(q[:, None] - q[None], axis=2).max())


L_none = diam(run("PCG_UVLayout", geo=flat, method="raster", pack_resolution=128, padding=0.0,
                  rotate_to_fit=False, island_rotation="none"))
L_45 = diam(run("PCG_UVLayout", geo=flat, method="raster", pack_resolution=128, padding=0.0,
                rotate_to_fit=False, island_rotation="step", rotation_step=45.0))
check("Raster + Step 45°: a horizontal 1×0.1 strip placed diagonally can be scaled up along the diagonal (diagonal ≈ 1 with No Rotation)",
      L_none < 1.01 and L_45 > 1.2, (L_none, L_45))

sec("UV Layout:Scale Islands to Match Their Surface Areas")
g1 = build.grid(1.0, 1.0, 2, 2)
g2 = build.grid(2.0, 2.0, 2, 2, center=(5, 0, 0))
pair = ops.merge(g1, g2)                                       # both pieces' point uv are the 0..1 square
lm = run("PCG_UVLayout", geo=pair, attribute_class="point", rotate_to_fit=False, match_surface_area=True)
bm, _ = isl_boxes(lm, POINT)
sz = sorted(float((h - l)[0]) for l, h in bm.values())
check("two pieces of world 1×1 and 2×2 with equally sized uv: after matching areas the uv edge ratio = 2", abs(sz[1] / sz[0] - 2.0) < 1e-6, sz)
lm0 = run("PCG_UVLayout", geo=pair, attribute_class="point", rotate_to_fit=False)
bm0, _ = isl_boxes(lm0, POINT)
sz0 = sorted(float((h - l)[0]) for l, h in bm0.values())
check("negative control: without it both pieces are the same size", abs(sz0[1] / sz0[0] - 1.0) < 1e-6, sz0)

sec("UV Layout:Pack Into = UDIM Tiles")
lu2 = run("PCG_UVLayout", geo=bx_, pack_into="udim_tiles", udim_count=2, target_attribute="tgt",
          rotate_to_fit=False)
b2, isl2 = isl_boxes(lu2)
tg = np.asarray(lu2.get(PRIM, "tgt"))[:, 0]
ok_t = True
for k, (l, h) in b2.items():
    tnum = set(tg[isl2 == k].tolist())
    if len(tnum) != 1:
        ok_t = False
        continue
    tl = list(tnum)[0] - 1001
    ok_t &= (l[0] >= tl - 1e-9 and h[0] <= tl + 1 + 1e-9 and l[1] > -1e-9 and h[1] < 1 + 1e-9)
check("2 tiles: every island lands entirely in one tile, Assigned Target = that tile's UDIM number", ok_t)
check("  both tiles used (1001 and 1002), no overlap", set(tg.tolist()) == {1001, 1002} and overlap_free(b2))
a1 = max(float(np.prod(h - l)) for l, h in bu.values())
a2_ = max(float(np.prod(h - l)) for l, h in b2.values())
check("  two tiles pack larger than one (largest island area grows)", a2_ > a1 * 1.2, (a1, a2_))
lu3 = run("PCG_UVLayout", geo=bx_, pack_into="udim_tiles", udim_start=1012, udim_columns=10,
          rotate_to_fit=False)
check("Starting UDIM 1012 (Columns 10): everything lands in u∈[1,2], v∈[1,2]",
      uvs(lu3).min() > 1 - 1e-9 and uvs(lu3).max() < 2 + 1e-9)
lu4 = run("PCG_UVLayout", geo=bx_, pack_into="udim_tiles", udim_start=1003, udim_columns=3,
          udim_count=2, rotate_to_fit=False, target_attribute="t")
check("Columns 3: 1003 at (2,0), 1004 wraps to (0,1)",
      set(np.asarray(lu4.get(PRIM, "t"))[:, 0].tolist()) == {1003, 1004}
      and all((np.asarray(lu4.get(PRIM, "t"))[isl_boxes(lu4)[1] == k, 0][0] == 1003)
              == (l[0] > 2 - 1e-9) for k, (l, h) in isl_boxes(lu4)[0].items()))
lf7 = run("PCG_UVLayout", geo=bx_, pack_into="udim_tiles", scale_mode="fixed", fixed_scale=0.6,
          rotate_to_fit=False, padding=0.0, target_attribute="t", nonpacked_group="np")
t7 = np.asarray(lf7.get(PRIM, "t"))[:, 0]
check("UDIM + Fixed 0.6: tiles opened as needed -- the two 0.6 squares take one tile each (1001, 1002), the 1.2-wide ones don't fit (-1)",
      sorted(set(t7.tolist())) == [-1, 1001, 1002] and int(np.asarray(lf7.groups[PRIM]["np"]).sum()) == 8,
      sorted(set(t7.tolist())))
lr2 = run("PCG_UVLayout", geo=bx_, method="raster", pack_resolution=64, pack_into="udim_tiles",
          udim_count=2, target_attribute="t", rotate_to_fit=False)
br2, ir2 = isl_boxes(lr2)
tr2 = np.asarray(lr2.get(PRIM, "t"))[:, 0]
check("Raster + 2 tiles: islands all within their own tile",
      all(l[0] >= tr2[ir2 == k][0] - 1001 - 1e-6 and h[0] <= tr2[ir2 == k][0] - 1000 + 1e-6
          for k, (l, h) in br2.items()) and set(tr2.tolist()) <= {1001, 1002})
lfr = run("PCG_UVLayout", geo=bx_, method="raster", pack_resolution=64, scale_mode="fixed",
          fixed_scale=0.6, rotate_to_fit=False, nonpacked_group="np")
check("Raster + Fixed 0.6: also 9 prims don't fit", int(np.asarray(lfr.groups[PRIM]["np"]).sum()) == 9,
      int(np.asarray(lfr.groups[PRIM]["np"]).sum()))

sec("UV Layout: outputs")
li = run("PCG_UVLayout", geo=bx_, island_attribute="island")
check("Island Number = island number by uv connectivity (6 islands)",
      np.array_equal(np.asarray(li.get(PRIM, "island"))[:, 0], UVL.islands(bx_, "uv"))
      and len(np.unique(np.asarray(li.get(PRIM, "island")))) == 6)
lg = run("PCG_UVLayout", geo=bx_, group="0", target_attribute="t", pack_into="udim_tiles")
check("islands outside the Group have Assigned Target = -1", int((np.asarray(lg.get(PRIM, "t"))[:, 0] == -1).sum()) == 9)

sec("UV Layout: targeted tests added (survivors of mutation testing)")
lrn = run("PCG_UVLayout", geo=flat, method="raster", pack_resolution=128, rotate_to_fit=False,
          island_rotation="none")
e5 = np.ptp(uvs(lrn), axis=0)
check("Raster + No Rotation: a vertical strip stays vertical (the original Raster would lay it down)",
      e5[1] > 5 * e5[0] and np.ptp(uvs(run("PCG_UVLayout", geo=flat, method="raster", pack_resolution=128,
                                             rotate_to_fit=False)), axis=0)[0] > 5 * e5[0], e5)
qq = np.random.default_rng(5).random((7, 2))
check("_rot_any at integer multiples of 90° is bit-identical to _rot90 (so the original Raster result is unchanged)",
      all(np.array_equal(UVL._rot_any(qq, 90.0 * r), UVL._rot90(qq, r)) for r in range(4)))
check("islands rotated by Rotation Step are still within 0..1", uvs(ls).min() > -1e-9 and uvs(ls).max() < 1 + 1e-9
      and uvs(lc3).min() > -1e-9 and uvs(lc3).max() < 1 + 1e-9)
lpd = run("PCG_UVLayout", geo=bx_, scale_mode="fixed", fixed_scale=0.2, rotate_to_fit=False, padding=0.05)
bpd, _ = isl_boxes(lpd)
bl = list(bpd.values())
gap = min(max(max(bl[j][0] - bl[i][1]), max(bl[i][0] - bl[j][1])) for i in range(len(bl))
          for j in range(i + 1, len(bl)))
check("Fixed + Padding 0.05: any two islands are at least 0.05 apart (both across rows and within a row)", gap > 0.05 - 1e-6, gap)
check("  and it really laid out more than one row", len(set(np.round([b[0][1] for b in bl], 6))) > 1)
check("Raster + 2 tiles: both used, no overlap", set(tr2.tolist()) == {1001, 1002} and overlap_free(br2))
lrf = run("PCG_UVLayout", geo=bx_, method="raster", pack_resolution=128, scale_mode="fixed",
          fixed_scale=0.2, rotate_to_fit=False, padding=0.0)
brf, _ = isl_boxes(lrf)
check("Raster + Fixed 0.2: island size = world × 0.2 (two 0.2×0.2, four 0.4×0.2)",
      sorted(sorted(np.round(h - l, 6).tolist()) for l, h in brf.values())
      == [[0.2, 0.2]] * 2 + [[0.2, 0.4]] * 4)
lr1 = run("PCG_UVLayout", geo=bx_, method="raster", pack_resolution=64, rotate_to_fit=False)
check("Raster: 2 tiles pack larger than 1",
      max(float(np.prod(h - l)) for l, h in br2.values())
      > 1.2 * max(float(np.prod(h - l)) for l, h in isl_boxes(lr1)[0].values()))
lsu = run("PCG_UVLayout", geo=bx_, pack_into="udim_tiles", udim_count=2, rotate_to_fit=False)
lsn = run("PCG_UVLayout", geo=bx_, pack_into="udim_tiles", udim_count=2, rotate_to_fit=False,
          island_rotation="none")
check("Shelf: Default same as No Rotation (90° doesn't change bounding box area)", np.array_equal(uvs(lsu), uvs(lsn)))
eight = ops.merge(*[build.grid(1.0, 1.0, 2, 2, center=(3 * k, 0, 0)) for k in range(8)])
eight = run("PCG_UVProject", geo=eight, mode="box", fit_to_01=False)
le = run("PCG_UVLayout", geo=eight, method="raster", pack_resolution=64, padding=0.0, rotate_to_fit=False,
         pack_into="udim_tiles", udim_count=2)
be8, _ = isl_boxes(le)
s8 = min(float((h - l).max()) for l, h in be8.values())
check("Raster + 2 tiles: 8 identical squares, 4 per tile, side ≈ 0.5 (the area upper bound with only one tile is 0.354)",
      0.45 < s8 <= 0.5 + 1e-6, s8)
lau = run("PCG_UVLayout", geo=flat, method="raster", pack_resolution=128, rotate_to_fit=False,
          pack_into="udim_tiles")
e6 = np.ptp(uvs(lau), axis=0)
check("Raster + UDIM + Default rotation: still tries 4 × 90° (the vertical strip gets laid down)", e6[0] > 5 * e6[1], e6)
check("panel: UV Layout spec self-check passes", not PANEL.check_layout("PCG_UVLayout", M["PCG_UVLayout"].INPUT_TYPES()))


# ═══════════════════════════════════════════════════════════════ UV Project
sec("UV Project: projector transform + U / V Range + Inner Radius")
r_ = names("PCG_UVProject")
check("old parameter names and order untouched, new ones appended",
      r_[:15] == ["geo", "group", "mode", "axis", "attribute_class", "attribute_name", "fit_to_01",
                  "keep_aspect", "fix_seams", "translate_u", "translate_v", "rotate", "scale_u",
                  "scale_v", "use_projector"], r_)
sq1 = build.grid(1.0, 1.0, 3, 3)                       # zx plane, x, z ∈ [−0.5, 0.5]
Pg = np.asarray(sq1.get(POINT, "P"), np.float64)[sq1.vertex_point]
pj = run("PCG_UVProject", geo=sq1, use_projector=True, axis="y")
# with axis = y the projection has u along +Z, v along +X (_frame's right-handed basis); unit square → parameters = local coordinates + 0.5
check("Orthographic, projector untouched: uv = (z + 0.5, x + 0.5), filling exactly 0..1",
      np.abs(uvs(pj) - np.stack([Pg[:, 2] + 0.5, Pg[:, 0] + 0.5], 1)).max() < 1e-6)
moved = ops.transform(sq1, translate=(3, 1, -2))
pjm = run("PCG_UVProject", geo=moved, use_projector=True, axis="y", proj_translate_x=3.0, proj_translate_y=1.0,
          proj_translate_z=-2.0)
check("geometry and projector translated together: uv unchanged", np.abs(uvs(pjm) - uvs(pj)).max() < 1e-6)
check("negative control: translating only the geometry with the projector fixed shifts the uv (no longer centered by bounding box)",
      np.abs(uvs(run("PCG_UVProject", geo=moved, use_projector=True, axis="y"))[:, 0] - (uvs(pj)[:, 0] - 2.0)).max() < 1e-6)
pjs = run("PCG_UVProject", geo=sq1, use_projector=True, axis="y", proj_scale_x=2.0, proj_scale_z=2.0)
check("projector scaled 2×: uv shrinks by half about 0.5", np.abs(uvs(pjs) - (0.5 + 0.5 * (uvs(pj) - 0.5))).max() < 1e-6)
pjr = run("PCG_UVProject", geo=sq1, use_projector=True, axis="y", proj_rotate_y=90.0)
# projector rotated 90° about Y: local z = world x, local x = −world z
check("projector rotated 90° about Y: uv = (x + 0.5, −z + 0.5)",
      np.abs(uvs(pjr) - np.stack([Pg[:, 0] + 0.5, -Pg[:, 2] + 0.5], 1)).max() < 1e-6)
a_ = uvs(run("PCG_UVProject", geo=sq1, use_projector=True, axis="y", proj_rotate_x=30.0, proj_rotate_y=40.0))
b_ = uvs(run("PCG_UVProject", geo=sq1, use_projector=True, axis="y", proj_rotate_x=30.0, proj_rotate_y=40.0,
             rotate_order="yxz"))
check("Rotate Order takes effect (xyz and yxz differ when two axes rotate at once)", np.abs(a_ - b_).max() > 1e-3)
c_ = uvs(run("PCG_UVProject", geo=sq1, use_projector=True, axis="y", proj_translate_z=0.5, proj_scale_z=2.0))
d_ = uvs(run("PCG_UVProject", geo=sq1, use_projector=True, axis="y", proj_translate_z=0.5, proj_scale_z=2.0,
             xform_order="tsr"))
check("Transform Order takes effect (translate first then scale, the translation is scaled too)", np.abs(c_ - d_).max() > 1e-3)
pjp = run("PCG_UVProject", geo=sq1, use_projector=True, axis="y", proj_scale_x=2.0, proj_scale_z=2.0,
          proj_pivot_z=0.5)
check("Pivot: scaling about z = 0.5, u of the z = 0.5 column doesn't move (= 1)",
      np.abs(uvs(pjp)[np.abs(Pg[:, 2] - 0.5) < 1e-6, 0] - 1.0).max() < 1e-6)
pju = run("PCG_UVProject", geo=sq1, use_projector=True, axis="y", u_range_min=0.0, u_range_max=0.5,
          v_range_min=0.25, v_range_max=0.75)
check("U Range 0..0.5: the texture's right edge is halfway across the projector (u doubled); V Range 0.25..0.75 (v shifted then scaled 2×)",
      np.abs(uvs(pju) - np.stack([uvs(pj)[:, 0] * 2, (uvs(pj)[:, 1] - 0.25) * 2], 1)).max() < 1e-6)
cy = build.tube(1.0, 1.0, 1.0, 16, 3)                  # radius 1, height 1, centered at the origin
pc_ = run("PCG_UVProject", geo=cy, mode="cylindrical", use_projector=True, axis="y")
Pc = np.asarray(cy.get(POINT, "P"), np.float64)[cy.vertex_point]
check("Cylindrical: unit cylinder, v = y + 0.5 (no longer Fit, a height-1 cylinder is exactly 0..1)",
      np.abs(uvs(pc_)[:, 1] - (Pc[:, 1] + 0.5)).max() < 1e-6)
pc2 = run("PCG_UVProject", geo=cy, mode="cylindrical", use_projector=True, axis="y", proj_scale_y=2.0)
check("  projector stretched 2× in Y: v range shrinks to 0.25..0.75",
      abs(uvs(pc2)[:, 1].min() - 0.25) < 1e-6 and abs(uvs(pc2)[:, 1].max() - 0.75) < 1e-6)
tor = build.torus(0.375, 0.125, 8, 16)                 # outer radius 0.5, inner radius 0.25
pt_ = run("PCG_UVProject", geo=tor, mode="toroidal", use_projector=True, axis="y", inner_radius=0.25, fix_seams=False)
Pt = np.asarray(tor.get(POINT, "P"), np.float64)[tor.vertex_point]
rr = np.hypot(Pt[:, 0], Pt[:, 2])
outer = np.abs(rr - 0.5) < 1e-5
inner_ = np.abs(rr - 0.25) < 1e-5
vv = uvs(pt_)[:, 1]
check("Toroidal + Inner Radius 0.25: outer equator v = 0, inner equator v = 0.5",
      outer.any() and inner_.any() and np.abs(np.minimum(vv[outer], 1 - vv[outer])).max() < 1e-5
      and np.abs(vv[inner_] - 0.5).max() < 1e-5)
pt2 = run("PCG_UVProject", geo=tor, mode="toroidal", use_projector=True, axis="y", inner_radius=0.1, fix_seams=False)
topc = (np.abs(rr - 0.375) < 1e-5) & (np.abs(Pt[:, 1] - 0.125) < 1e-5)
check("  directly above the tube (0.375 from the axis, height 0.125): v = 0.25", topc.any() and np.abs(vv[topc] - 0.25).max() < 1e-5)
check("negative control: with Inner Radius 0.1 the tube center line changes, directly above is no longer 0.25", np.abs(uvs(pt2)[:, 1][topc] - 0.25).max() > 1e-2)
check("Inner Radius only used when the projector is on (when off, same as before the change: major radius taken from the data)",
      np.array_equal(uvs(run("PCG_UVProject", geo=tor, mode="toroidal", inner_radius=0.1)),
                     uvs(run("PCG_UVProject", geo=tor, mode="toroidal"))))
check("Box mode unaffected by the projector", np.array_equal(
    uvs(run("PCG_UVProject", geo=G_box(), mode="box", use_projector=True, axis="y", proj_scale_x=3.0)),
    uvs(run("PCG_UVProject", geo=G_box(), mode="box"))))
check("Angle rotates about (0.5, 0.5) (in projector mode too)",
      np.abs(uvs(run("PCG_UVProject", geo=sq1, use_projector=True, axis="y", rotate=180.0)) - (1.0 - uvs(pj))).max() < 1e-6)
pa_ = run("PCG_UVProject", geo=sq1, use_projector=True, axis="y", fit_to_01=False, u_range_max=0.5)
pb_ = run("PCG_UVProject", geo=sq1, use_projector=True, axis="y", fit_to_01=False, u_range_max=0.5,
          rotate=180.0)
check("  with Fit off it also rotates about (0.5, 0.5) (visible when the uv center isn't at 0.5)", np.abs(uvs(pb_) - (1.0 - uvs(pa_))).max() < 1e-6)
pzr = run("PCG_UVProject", geo=build.grid(1.0, 1.0, 3, 3, plane="xy"), use_projector=True, axis="z",
          proj_rotate_z=90.0)
e0 = uvs(run("PCG_UVProject", geo=build.grid(1.0, 1.0, 3, 3, plane="xy"), use_projector=True, axis="z"))
check("projector rotated 90° about Z (projecting along Z): uv rotated 90° about (0.5, 0.5)",
      np.abs((uvs(pzr) - 0.5) - np.stack([e0[:, 1] - 0.5, -(e0[:, 0] - 0.5)], 1)).max() < 1e-6
      or np.abs((uvs(pzr) - 0.5) - np.stack([-(e0[:, 1] - 0.5), e0[:, 0] - 0.5], 1)).max() < 1e-6)
check("panel: UV Project spec self-check passes", not PANEL.check_layout("PCG_UVProject", M["PCG_UVProject"].INPUT_TYPES()))


# ═══════════════════════════════════════════════════════════════ UV Autoseam
from comfyui_pcg.geo import uvseams as UVS                # noqa: E402
sec("UV Autoseam:Splitting = Existing Islands / Include / Exclude / Island Attribute")
r_ = names("PCG_UVAutoSeams")
check("old parameter names and order untouched, new ones appended",
      r_[:9] == ["geo", "group", "output_group", "mode", "min_angle", "cone_angle", "make_disks",
                 "output_chart_attribute", "include_edges"], r_)
check("Mode menu: the original three in place, existing_islands appended at the end",
      it("PCG_UVAutoSeams", "mode") == ["angle", "charts", "both", "existing_islands"])


def eset(g, name="seams"):
    return set(map(tuple, np.sort(np.asarray(g.edge_groups[name]), 1).tolist()))


ex = run("PCG_UVAutoSeams", geo=bx_, mode="existing_islands")
check("Existing Islands: box + box projection → seams = boundaries of the 6 islands = 16 box edges", len(eset(ex)) == 16)
check("  matches UV Flatten's Preserve Seams output",
      eset(ex) == set(map(tuple, np.sort(np.asarray(fb.edge_groups["cut"]), 1).tolist())))
check("  already all disks: the Make Disks toggle doesn't change the result",
      eset(ex) == eset(run("PCG_UVAutoSeams", geo=bx_, mode="existing_islands", make_disks=False)))
check("negative control: Crease Angle 100° (box edges are 90°) cuts nothing (Make Disks off)",
      len(eset(run("PCG_UVAutoSeams", geo=bx_, mode="angle", min_angle=100.0, make_disks=False))) == 0)
gq = build.grid(2.0, 2.0, 5, 5)
gq = run("PCG_UVProject", geo=gq, mode="planar", axis="y")
uvq = np.array(gq.get(VERTEX, "uv"), np.float64)
f0 = np.arange(gq.prim_offset[5], gq.prim_offset[6])          # move the 4 corners of prim 5 (interior) by 1e-4
uvq[f0] += 1e-4
gq.set(VERTEX, "uv", uvq.astype(np.float32))
check("Connectivity Tolerance 1e-6: all four edges of the interior prim moved by 1e-4 are seams",
      len(eset(run("PCG_UVAutoSeams", geo=gq, mode="existing_islands", make_disks=False))) == 4)
check("  Tolerance 1e-3: a 1e-4 difference counts as connected, no seams",
      len(eset(run("PCG_UVAutoSeams", geo=gq, mode="existing_islands", make_disks=False,
                   connectivity_tolerance=1e-3))) == 0)
try:
    run("PCG_UVAutoSeams", geo=G_grid(), mode="existing_islands")      # only point uv
    no_uv = False
except KeyError:
    no_uv = True
check("no vertex uv: raises (point uv can't express seams)", no_uv)

gi = G_grid()                                                     # 9×5 points, 8×4 cells, flat
tp = TOPO.topology(gi)
gi.set_edge_group("one", tp.edge_points[[int(np.nonzero(tp.edge_count == 2)[0][3])]])
inc = run("PCG_UVAutoSeams", geo=gi, mode="angle", make_disks=False, include_edges="one")
check("Include Edges: on a plane nothing should be cut, the given edge must be a seam (and only it)",
      eset(inc) == set(map(tuple, np.sort(np.asarray(gi.edge_groups["one"]), 1).tolist())))
check("  negative control: no seams without Include", len(eset(run("PCG_UVAutoSeams", geo=gi, mode="angle", make_disks=False))) == 0)

sp_ = G_sphere()
Psp = np.asarray(sp_.get(POINT, "P"), np.float64)
tps = TOPO.topology(sp_)
upper = (Psp[tps.edge_points[:, 0], 1] > 0.05) & (Psp[tps.edge_points[:, 1], 1] > 0.05)
sp_.set_edge_group("up", tps.edge_points[upper])
up_set = set(map(tuple, np.sort(tps.edge_points[upper], 1).tolist()))
base = run("PCG_UVAutoSeams", geo=sp_)
exc = run("PCG_UVAutoSeams", geo=sp_, exclude_edges="up")
check("negative control: without exclusion the upper hemisphere has seams", len(eset(base) & up_set) > 0)
check("Exclude Edges = upper hemisphere edges: all seams in the lower hemisphere", len(eset(exc) & up_set) == 0, len(eset(exc) & up_set))


def chi_of(g, name="seams"):
    return UVS.euler(g, GRP.edge_mask(g, np.asarray(g.edge_groups[name])))


check("  after cutting every piece is still a disk (χ = 1)", (chi_of(exc) == 1).all(), chi_of(exc))
exb = run("PCG_UVAutoSeams", geo=sp_, mode="both", exclude_edges="up")
check("Mode = Both + Exclude upper hemisphere: normal-partition seams also avoid the upper hemisphere, still disks",
      len(eset(exb) & up_set) == 0 and (chi_of(exb) == 1).all()
      and len(eset(run("PCG_UVAutoSeams", geo=sp_, mode="both")) & up_set) > 0)
tb_ = build.tube(1.0, 1.0, 2.0, 16, 6)                   # open tube (annulus, χ = 0): must be cut from the top opening to the bottom
Ptb = np.asarray(tb_.get(POINT, "P"), np.float64)
ttb = TOPO.topology(tb_)
left = (Ptb[ttb.edge_points[:, 0], 0] < 0.01) & (Ptb[ttb.edge_points[:, 1], 0] < 0.01)
tb_.set_edge_group("left", ttb.edge_points[left])
lset = set(map(tuple, np.sort(ttb.edge_points[left], 1).tolist()))
tb0 = run("PCG_UVAutoSeams", geo=tb_)
tb1 = run("PCG_UVAutoSeams", geo=tb_, exclude_edges="left")
check("negative control: the tube's default vertical seam lies in the x < 0 half", len(eset(tb0) & lset) > 0)
check("Exclude the x < 0 half: the vertical seam moves to the other half, still one disk, seam count unchanged (one vertical seam of 5 edges)",
      len(eset(tb1) & lset) == 0 and (chi_of(tb1) == 1).all() and len(chi_of(tb1)) == 1
      and len(eset(tb1)) == 5, (len(eset(tb1) & lset), chi_of(tb1), len(eset(tb1))))
exa = run("PCG_UVAutoSeams", geo=sp_, exclude_edges="*")
check("Exclude all edges: a closed sphere must be cut -- only the topologically forced edges are cut, still a disk",
      (chi_of(exa) == 1).all() and 0 < len(eset(exa)) <= len(eset(base)), (len(eset(exa)), len(eset(base))))
ga2 = G_grid()
Pc_ = np.asarray(ga2.get(POINT, "P"), np.float64)
cen = np.array([Pc_[ga2.prim_points(k)].mean(0)[0] for k in range(ga2.nprims)])
ga2.set(PRIM, "id", (cen > 0).astype(np.int32)[:, None])
ia = run("PCG_UVAutoSeams", geo=ga2, mode="angle", make_disks=False, island_attribute="id")
mid = {tuple(sorted(e)) for e in eset(ia)}
check("Island Attribute: left and right halves have different values → the 4 vertical edges of the middle column are seams (x = 0)",
      len(mid) == 4 and all(abs(Pc_[a, 0]) < 1e-6 and abs(Pc_[b, 0]) < 1e-6 for a, b in mid))
check("panel: UV Autoseam spec self-check passes",
      not PANEL.check_layout("PCG_UVAutoSeams", M["PCG_UVAutoSeams"].INPUT_TYPES()))


# ═══════════════════════════════════════════════════════════════ UV Pelt (new node)
sec("UV Pelt: new node")
try:                                                      # the device layout may not have sop_map.py
    import sop_map as _SM
    _map_ok = _SM.M["UV Pelt"][1] == "PCG_UVPelt" and _SM.M["UV Unwrap"][1] == "PCG_UVUnwrap"
except ImportError:
    _map_ok = True
check("UV Pelt is in the node table", "PCG_UVPelt" in M)
pg = build.grid(2.0, 2.0, 7, 7)                          # flat square sheet, 6×6 cells
Ppg = np.asarray(pg.get(POINT, "P"), np.float64)
bnd_pt = (np.abs(np.abs(Ppg[:, 0]) - 1) < 1e-6) | (np.abs(np.abs(Ppg[:, 2]) - 1) < 1e-6)


def by_point(g):
    """vertex uv -> point uv (single piece, without seams each point has only one copy)."""
    out = np.zeros((g.npoints, 2))
    out[g.vertex_point] = uvs(g)
    return out


def nb_lists(g):
    nb = [set() for _ in range(g.npoints)]
    for k in range(g.nprims):
        q = g.prim_points(k)
        for i in range(len(q)):
            a, b = int(q[i]), int(q[(i + 1) % len(q)])
            nb[a].add(b)
            nb[b].add(a)
    return nb


tt = run("PCG_UVPelt", geo=pg, method="tutte_barycentric", boundary_springs=1e7)
ut = by_point(tt)
check("Tutte + very stiff boundary springs: boundary points all on the circular frame (distance to (0.5,0.5) = 0.5)",
      np.abs(np.linalg.norm(ut[bnd_pt] - 0.5, axis=1) - 0.5).max() < 1e-5)
# note: on a quad mesh Tutte's neighbours are the neighbours **after fan triangulation** (diagonals are springs too); verified on a triangle mesh here
pgt = build.grid(2.0, 2.0, 7, 7, connectivity="triangles")
tt3 = run("PCG_UVPelt", geo=pgt, method="tutte_barycentric", boundary_springs=1e7)
u3 = by_point(tt3)
nb = nb_lists(pgt)
res = max(np.linalg.norm(u3[i] - u3[list(nb[i])].mean(0)) for i in range(pgt.npoints) if not bnd_pt[i])
check("Tutte: every interior point = centroid of its neighbours (residual < 1e-6)", res < 1e-6, res)
hm = by_point(run("PCG_UVPelt", geo=pgt, method="discrete_harmonic", boundary_springs=1e7))
check("negative control: Discrete Harmonic interior points aren't neighbour centroids (cotangent weights)",
      max(np.linalg.norm(hm[i] - hm[list(nb[i])].mean(0)) for i in range(pgt.npoints) if not bnd_pt[i]) > 1e-4)


def interior_residual(g, u, kind):
    """Compute the weights independently and check the interior equilibrium equation Σ_j w_ij (u_i − u_j) = 0."""
    P = np.asarray(g.get(POINT, "P"), np.float64)
    W = {}
    for k in range(g.nprims):
        q = [int(x) for x in g.prim_points(k)]
        a, b, c = P[q[0]], P[q[1]], P[q[2]]
        area = 0.5 * np.linalg.norm(np.cross(b - a, c - a))
        for t in range(3):
            i0, i1, i2 = q[t], q[(t + 1) % 3], q[(t + 2) % 3]     # corner i0 is opposite edge (i1, i2)
            e1, e2 = P[i1] - P[i0], P[i2] - P[i0]
            cot = (e1 @ e2) / np.linalg.norm(np.cross(e1, e2))
            key = (min(i1, i2), max(i1, i2))
            if kind == "harmonic":
                W[key] = W.get(key, 0.0) + 0.5 * cot
            else:
                W[key] = W.get(key, 0.0) + area / ((P[i1] - P[i2]) @ (P[i1] - P[i2]))
    r = np.zeros_like(u)
    for (a, b), w in W.items():
        r[a] += w * (u[a] - u[b])
        r[b] += w * (u[b] - u[a])
    inner = ~bnd_pt
    return float(np.abs(r[inner]).max()), float(np.abs(r[~inner]).max())


hres, hb = interior_residual(pgt, hm, "harmonic")
check("Discrete Harmonic: interior points satisfy the cotangent-weight equilibrium equation (residual < 1e-5; boundary points are unbalanced > 1e-2, pulled by springs)",
      hres < 1e-5 and hb > 1e-2, (hres, hb))
spm = by_point(run("PCG_UVPelt", geo=pgt, method="spring_relaxation", boundary_springs=1e7))
sres, _ = interior_residual(pgt, spm, "spring")
check("Spring Relaxation: interior points satisfy the equilibrium equation with w = sum of adjacent areas / edge length² (residual < 1e-5)", sres < 1e-5, sres)
check("  negative control: the Spring solution doesn't satisfy the cotangent-weight equation", interior_residual(pgt, spm, "harmonic")[0] > 1e-4)
sqf = Geometry.from_mesh(np.array([[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]], np.float32),
                         [[0, 1, 2, 3]])                  # a square frame in the XY plane (U = P.x, V = P.y)
th = by_point(run("PCG_UVPelt", geo=pgt, method="tutte_barycentric", boundary_springs=1e7, frame=sqf))
check("square frame (second input): boundary points all on the frame's four sides",
      np.abs(np.maximum(np.abs(th[bnd_pt, 0]), np.abs(th[bnd_pt, 1])) - 1).max() < 1e-5)
sqcw = Geometry.from_mesh(np.asarray(sqf.get(POINT, "P")), [[0, 3, 2, 1]])   # frame given clockwise
check("  same when the frame is given clockwise (traversed counterclockwise internally, no mirroring)",
      np.abs(by_point(run("PCG_UVPelt", geo=pgt, method="tutte_barycentric", boundary_springs=1e7,
                          frame=sqcw)) - th).max() < 1e-6)
for m in ("spring_relaxation", "tutte_barycentric", "discrete_harmonic"):
    _, _, sg, _ = corner_angles_uv(run("PCG_UVPelt", geo=saddle(), method=m))
    check(f"{m}: no flips on a saddle (all triangle uv signed areas positive, same handedness as UV Flatten)", (sg > 0).all())
st = int(np.argmin(np.linalg.norm(Ppg - Ppg[pg.prim_points(0)].mean(0), axis=1)))
check("Orientation 0: the boundary point nearest the Hint prim (0) lands at position 0 of the circular frame (1, 0.5)",
      np.abs(ut[st] - [1.0, 0.5]).max() < 1e-5, ut[st])
uo = by_point(run("PCG_UVPelt", geo=pg, method="tutte_barycentric", boundary_springs=1e7, orientation=0.25))
check("Orientation 0.25: that point rotates to (0.5, 1)", np.abs(uo[st] - [0.5, 1.0]).max() < 1e-5, uo[st])
soft = by_point(run("PCG_UVPelt", geo=pg, method="tutte_barycentric", boundary_springs=0.1))
check("small Boundary Springs: the whole piece pulls inward (bounding box smaller than with stiff springs)", np.ptp(soft, axis=0).max() < 0.9 * np.ptp(ut, axis=0).max())
ur = by_point(run("PCG_UVPelt", geo=pg, use_range=True, u_range_min=0.2, u_range_max=0.4,
                  v_range_min=0.5, v_range_max=1.5))
check("Use Range: uv bounding box = U Range × V Range", np.allclose(ur.min(0), [0.2, 0.5], atol=1e-6)
      and np.allclose(ur.max(0), [0.4, 1.5], atol=1e-6))
check("  negative control: without Use Range it's not in that range",
      not np.allclose(by_point(run("PCG_UVPelt", geo=pg)).max(0), [0.4, 1.5], atol=1e-3))
stiffg = pg.copy()
sv = np.where(Ppg[:, 0] > 0, 50.0, 1.0)
stiffg.set(POINT, "k", sv.astype(np.float32)[:, None])
sk = by_point(run("PCG_UVPelt", geo=stiffg, method="tutte_barycentric", stiffness_attribute="k"))
check("Stiffness Attribute: changes the interior distribution (differs from without it)", np.abs(sk - by_point(run("PCG_UVPelt", geo=pg,
      method="tutte_barycentric"))).max() > 1e-3)
two_g = ops.merge(pg, ops.transform(pg, translate=(5, 0, 0)))
pt2 = run("PCG_UVPelt", geo=two_g, hint_prim=40, output_group="pelt")
gm2 = np.asarray(pt2.groups[PRIM]["pelt"], bool)
v2 = np.repeat(gm2, pt2.prim_sizes())
old2 = np.asarray(two_g.get(POINT, "uv"), np.float64)[two_g.vertex_point]
check("two pieces: only the piece with the Hint prim (40, the second piece) is unwrapped; Output Group = its 36 prims; the other piece's uv unchanged",
      gm2[36:].all() and not gm2[:36].any() and np.allclose(uvs(pt2)[~v2], old2[~v2]))
try:
    run("PCG_UVPelt", geo=G_sphere())
    cl = False
except ValueError:
    cl = True
cut = run("PCG_UVPelt", geo=run("PCG_UVAutoSeams", geo=G_sphere()), seam_group="seams")
check("closed sphere: raises; with seams given it unwraps (all inside the circular frame)",
      cl and np.linalg.norm(uvs(cut) - 0.5, axis=1).max() < 0.5 + 1e-6)

sec("UV Pelt: targeted tests added (survivors of mutation testing)")
# flat annulus: outer ring r = 1, inner ring r = 0.4, two boundary loops -- the outer (longer) one is pinned to the frame, the inner one is free
na, nr = 24, 4
ang_ = np.linspace(0, 2 * np.pi, na, endpoint=False)
rad_ = np.linspace(0.4, 1.0, nr)
Pa = np.array([[r * np.cos(a), 0.0, r * np.sin(a)] for r in rad_ for a in ang_], np.float32)
fa_ = [[i * na + j, i * na + (j + 1) % na, (i + 1) * na + (j + 1) % na, (i + 1) * na + j]
       for i in range(nr - 1) for j in range(na)]
ann = Geometry.from_mesh(Pa, fa_)
ua = by_point(run("PCG_UVPelt", geo=ann, method="tutte_barycentric", boundary_springs=1e7))
check("annulus: outer ring (longest boundary) on the circular frame, inner ring not",
      np.abs(np.linalg.norm(ua[-na:] - 0.5, axis=1) - 0.5).max() < 1e-5
      and np.linalg.norm(ua[:na] - 0.5, axis=1).max() < 0.45)
hl = pgt.nprims - 1                                        # triangle: centroid clearly closer to one corner
dd = np.where(bnd_pt, np.linalg.norm(Ppg - Ppg[pgt.prim_points(hl)].mean(0), axis=1), np.inf)
st_l = int(np.argmin(dd))
u35 = by_point(run("PCG_UVPelt", geo=pgt, method="tutte_barycentric", boundary_springs=1e7, hint_prim=hl))
check("Hint set to the last triangle: the (unique) boundary point nearest it lands at position 0 of the frame (1, 0.5)",
      np.sort(dd)[1] - np.sort(dd)[0] > 1e-3 and np.abs(u35[st_l] - [1.0, 0.5]).max() < 1e-5, u35[st_l])
# boundary distributed by arc length: on a 4×1 rectangular mesh, point spacing on the long sides is larger than on the short sides
rg = build.grid(4.0, 1.0, 5, 3, connectivity="triangles")
urg = by_point(run("PCG_UVPelt", geo=rg, method="tutte_barycentric", boundary_springs=1e7))
Prg = np.asarray(rg.get(POINT, "P"), np.float64)
onb = (np.abs(np.abs(Prg[:, 0]) - 2) < 1e-6) | (np.abs(np.abs(Prg[:, 2]) - 0.5) < 1e-6)
thb = np.sort(np.arctan2(urg[onb, 1] - 0.5, urg[onb, 0] - 0.5) % (2 * np.pi))
gaps = np.sort(np.diff(np.r_[thb, thb[0] + 2 * np.pi]))
# perimeter 10: each segment on the long sides is 1 (central angle 2π/10), on the short sides 0.5 (2π/20)
check("boundary spread onto the frame by 3D arc length (long-side segments 2π/10, short-side segments 2π/20)",
      np.allclose(gaps, sorted([2 * np.pi / 20] * 4 + [2 * np.pi / 10] * 8), atol=1e-5), gaps)
# boundary point equilibrium: Σ_j w (u_b − u_j) + k (u_b − f_b) = 0, f_b taken as the stiff-spring position, Tutte w = 1
hard = by_point(run("PCG_UVPelt", geo=pgt, method="tutte_barycentric", boundary_springs=1e9))
k_ = 0.5
sft = by_point(run("PCG_UVPelt", geo=pgt, method="tutte_barycentric", boundary_springs=k_))
rb = max(np.linalg.norm(sum(sft[i] - sft[j] for j in nb[i]) + k_ * (sft[i] - hard[i]))
         for i in range(pgt.npoints) if bnd_pt[i])
check("Tutte + Boundary Springs 0.5: boundary points satisfy Σ(u_b − u_j) + k(u_b − f_b) = 0 (w = 1)", rb < 1e-6, rb)
# flat triangle mesh with obtuse angles: cotangents are negative, weights must not take the absolute value
jg = build.grid(2.0, 2.0, 7, 7, connectivity="triangles")
Pj = np.asarray(jg.get(POINT, "P"), np.float64)
rng3 = np.random.default_rng(7)
Pj[~bnd_pt] += rng3.uniform(-0.12, 0.12, (int((~bnd_pt).sum()), 3)) * [1, 0, 1]
jg.set(POINT, "P", Pj.astype(np.float32))
a3j, _, _, _ = corner_angles_uv(run("PCG_UVPelt", geo=jg))
hj = by_point(run("PCG_UVPelt", geo=jg, method="discrete_harmonic", boundary_springs=1e3))
check("perturbed flat mesh (has obtuse angles, max angle > 95°): the cotangent-weight equilibrium equation still holds (negative cotangents not made absolute)",
      a3j.max() > np.radians(95) and interior_residual(jg, hj, "harmonic")[0] < 1e-6,
      (np.degrees(a3j.max()), interior_residual(jg, hj, "harmonic")[0]))
two_v = run("PCG_UVProject", geo=two_g, mode="planar", axis="y")      # vertex uv
pv2 = run("PCG_UVPelt", geo=two_v, hint_prim=40)
check("existing vertex uv: vertex uv of the piece not unwrapped kept as is", np.allclose(uvs(pv2)[~v2], uvs(two_v)[~v2]))
bu_ = th[bnd_pt]
check("square frame: boundary points interpolated by arc length along the frame sides, all 24 boundary point positions distinct",
      len(np.unique(np.round(bu_, 6), axis=0)) == int(bnd_pt.sum()))
check("panel: UV Pelt spec self-check passes", not PANEL.check_layout("PCG_UVPelt", M["PCG_UVPelt"].INPUT_TYPES()))


# ═══════════════════════════════════════════════════════════════ UV Unwrap (new node)
sec("UV Unwrap: new node")
check("UV Unwrap is in the node table; sop_map's UV Pelt / UV Unwrap point to the new nodes", "PCG_UVUnwrap" in M and _map_ok)


def region_boxes(g):
    b, isl = isl_boxes(g)
    return b


box6 = build.box((2, 1, 1))                                      # 6 faces, one quad each
uw = run("PCG_UVUnwrap", geo=box6, spacing=0.0)
rb6 = region_boxes(uw)
ext6 = sorted(tuple(sorted(np.round(h - l, 6).tolist())) for l, h in rb6.values())
check("box 2×1×1: 6 regions (one per face, front and back separate), size = world size (two 1×1, four 1×2)",
      len(rb6) == 6 and ext6 == [(1.0, 1.0)] * 2 + [(1.0, 2.0)] * 4, ext6)
uu = uvs(uw)
check("Strip + Spacing 0: laid out in a row along U, total length = sum of region widths, all v ∈ [0, height], no overlap",
      overlap_free(rb6) and abs(uu[:, 0].max() - sum(float((h - l)[0]) for l, h in rb6.values())) < 1e-5
      and uu[:, 1].min() > -1e-9)
_, _, sg6, _ = corner_angles_uv(run("PCG_UVUnwrap", geo=build.box((2, 1, 1), divisions=(3, 3, 3))))
check("back-facing prims have u negated: all triangle uv signed areas have the same sign (no mirroring)", (sg6 == sg6[0]).all())
rot_box = ops.transform(box6, rotate=(0, 30, 0))
ur0 = region_boxes(run("PCG_UVUnwrap", geo=rot_box, spacing=0.0))
ur1 = region_boxes(run("PCG_UVUnwrap", geo=rot_box, spacing=0.0, rotate_y=30.0))
a0 = sorted(float(np.prod(h - l)) for l, h in ur0.values())
a1 = sorted(float(np.prod(h - l)) for l, h in ur1.values())
check("box rotated 30°: with Rotate Y = 30 the planes line up, area = world area (1,1,2,2,2,2)",
      np.allclose(a1, [1, 1, 2, 2, 2, 2], atol=1e-5), a1)
check("  negative control: without rotating the planes, side projections shrink by cos30° (smaller area)", min(a0) < 0.9 and not np.allclose(a0, a1, atol=1e-3), a0)
tb6 = build.tube(1.0, 1.0, 2.0, 16, 2)
check("tube (16 faces): normals only in the X and Z planes, front and back each → 4 regions",
      len(region_boxes(run("PCG_UVUnwrap", geo=tb6))) == 4)
eightq = ops.merge(*[build.grid(1.0, 1.0, 2, 2, center=(3 * k, 0, 0)) for k in range(8)])
us_ = uvs(run("PCG_UVUnwrap", geo=eightq, layout="strip", spacing=0.0))
uq_ = uvs(run("PCG_UVUnwrap", geo=eightq, layout="square", spacing=0.0))
check("8 × 1×1: Strip lays out 8×1; Square lays out close to square (S = √8, 2 per row → within 2×4)",
      np.allclose(np.ptp(us_, axis=0), [8, 1]) and np.ptp(uq_, axis=0).max() <= 4 + 1e-9
      and np.ptp(uq_, axis=0).min() >= 2 - 1e-9, (np.ptp(us_, axis=0), np.ptp(uq_, axis=0)))
usp = uvs(run("PCG_UVUnwrap", geo=eightq, layout="strip", spacing=10.0))
check("Spacing 10%: gap = 0.1 × √8, Strip total length = 8 + 7 × 0.1√8",
      abs(np.ptp(usp, axis=0)[0] - (8 + 7 * 0.1 * np.sqrt(8))) < 1e-5, np.ptp(usp, axis=0))
uun = uvs(run("PCG_UVUnwrap", geo=eightq, scale="uniform", spacing=0.0))
ust = uvs(run("PCG_UVUnwrap", geo=eightq, scale="stretch", spacing=0.0))
check("Scale Uniform: long side = 1, ratio unchanged (1 × 1/8); Stretch: both sides stretched to 1",
      np.allclose(np.ptp(uun, axis=0), [1, 0.125]) and np.allclose(np.ptp(ust, axis=0), [1, 1])
      and uun.min() > -1e-9)
tilt = build.grid(2.0, 1.0, 3, 2, rotate=(35, 20, 0))
pl_in = Geometry.from_mesh(np.asarray(build.grid(1.0, 1.0, 2, 2, rotate=(35, 20, 0)).get(POINT, "P")),
                           [[0, 1, 3, 2]])
ut_ = run("PCG_UVUnwrap", geo=tilt, planes=pl_in)
l3, l2 = edge_lens(ut_)
check("second input gives a plane tilted like the mesh: projection is isometric (edge lengths unchanged)", np.abs(l3 - l2).max() < 1e-5)
l3b, l2b = edge_lens(run("PCG_UVUnwrap", geo=tilt))
check("  negative control: with the default coordinate planes the projection is foreshortened", np.abs(l3b - l2b).max() > 1e-2)
ugp = run("PCG_UVUnwrap", geo=gg, group="0-7")
check("prims outside the Group keep their uv (point uv)", np.allclose(uvs(ugp)[~vsel], old_uv[~vsel]))

sec("UV Unwrap: targeted tests added (survivors of mutation testing)")
from comfyui_pcg.geo import uvunwrap as UVW               # noqa: E402
bent = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0.3], [1, 1, 0], [0, 1, 0.2]], np.float32), [[0, 1, 2, 3]])
u_, v_, n_ = UVW._planes(bent, "", (0, 0, 0), "xyz")[0]
check("non-planar quad treated as planar: u is first projected into the plane (u ⟂ n), (u, v, n) right-handed orthogonal",
      abs(u_ @ n_) < 1e-9 and abs(np.linalg.norm(u_) - 1) < 1e-9 and np.allclose(np.cross(u_, v_), n_))
_, _, sgt, _ = corner_angles_uv(ut_)
_, _, sgd, _ = corner_angles_uv(run("PCG_UVUnwrap", geo=tilt))
check("second-input planes have the same handedness as the default coordinate planes (uv signed areas same sign)", (sgt == sgd).all())
mix_r = ops.merge(build.grid(0.1, 10.0, 2, 2), *[build.grid(0.5, 0.5, 2, 2, center=(3 * k, 0, 5)) for k in range(4)])
umr = uvs(run("PCG_UVUnwrap", geo=mix_r, layout="square", spacing=0.0))
check("Square: when a region is wider than S, the row width is the widest region (10): the strip on one row, 4 squares squeezed onto the second, height 0.1 + 0.5",
      np.allclose(np.ptp(umr, axis=0), [10.0, 0.6], atol=1e-6), np.ptp(umr, axis=0))
three = ops.merge(build.grid(1.0, 1.0, 2, 2), build.grid(2.0, 2.0, 2, 2, center=(5, 0, 0)),
                  build.grid(0.5, 0.5, 2, 2, center=(9, 0, 0)))
u3s = run("PCG_UVUnwrap", geo=three, layout="square", spacing=0.0)
check("Square: the largest region (face 2, 2×2) placed first, at the origin", np.allclose(uvs(u3s)[4:8].min(0), [0, 0]))
usq = uvs(run("PCG_UVUnwrap", geo=eightq, layout="square", spacing=10.0))
check("Square + Spacing 10%: 3 gaps between 4 rows, height = 4 + 3 × 0.1√8",
      abs(np.ptp(usq, axis=0)[1] - (4 + 3 * 0.1 * np.sqrt(8))) < 1e-5, np.ptp(usq, axis=0))
ugv = run("PCG_UVUnwrap", geo=pr, group="0-7")
check("prims outside the Group keep their vertex uv", np.allclose(uvs(ugv)[~vsel], target[~vsel]))
two_pl = ops.merge(pl_in, Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], np.float32),
                                             [[0, 1, 2, 3]]))
check("Plane Group: takes only the selected plane from the second input (= the result when only it is given)",
      np.allclose(uvs(run("PCG_UVUnwrap", geo=tilt, planes=two_pl, plane_group="0")), uvs(ut_)))
ro1 = uvs(run("PCG_UVUnwrap", geo=rot_box, rotate_x=20.0, rotate_y=30.0))
ro2 = uvs(run("PCG_UVUnwrap", geo=rot_box, rotate_x=20.0, rotate_y=30.0, rotate_order="yxz"))
check("Rotate Order takes effect (xyz and yxz differ when two axes rotate at once)", np.abs(ro1 - ro2).max() > 1e-3)
check("panel: UV Unwrap spec self-check passes", not PANEL.check_layout("PCG_UVUnwrap", M["PCG_UVUnwrap"].INPUT_TYPES()))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
