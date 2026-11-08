"""
pcg73: transforms and correspondence -- Extract Transform, Attribute Transform Extract, Match Axis,
Primitive, Attribute Reorient, Match Topology, Topo Transfer, DeltaMush.

The reference does not rely on the implementation itself:
  Extract Transform   known rotation / similarity / affine transforms recovered exactly; instance points fed to Copy to Points
                      copying reference land exactly on target; with noise it is least-squares optimal (perturbing the rotation
                      a little makes the residual bigger); outliers with weight 0 don't affect the result; mirrored input gives a true rotation
  Match Axis          y -> x: the top vertex goes to +x, points on the z axis stay put; reversed is 180°; with up both axes line up
  Primitive           each face scaled about its own center: center stays, edge length halves; moved 0.2 along the normal
  Attribute Reorient  global rotation: N and orient rotated exactly; after a twist N matches the recomputed normals
  Match Topology      point numbers / prim numbers / starting vertices all shuffled, shape heavily deformed: topology mode matches reference
                      prim by prim; position mode on the same input doesn't match fully (negative control)
  Topo Transfer       target with a dent: all points on the target surface, no flipped faces; pure projection (negative control) flips faces;
                      landmarks land exactly
  DeltaMush           exactly invariant under rigid motion; for a deformation whose detail got smeared, the error to ground truth is clearly smaller after correction
"""
import math
import os
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy                                        # noqa: F401,E402
import numpy as np                                      # noqa: E402

from comfyui_pcg.geo import registration as RG          # noqa: E402
from comfyui_pcg.geo import deform2 as D2               # noqa: E402
from comfyui_pcg.geo import deformers as DF             # noqa: E402
from comfyui_pcg.geo import build, ops, copyto          # noqa: E402
from comfyui_pcg.geo import spatial as SP               # noqa: E402
from comfyui_pcg.geo.deform import deform as twist      # noqa: E402
from comfyui_pcg.geo.xform import quat_to_mat           # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, PRIM          # noqa: E402
from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP      # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag):
    try:
        fn()
        check(name, False, "no error raised")
    except Exception as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:90]}")


def sec(t):
    print("\n" + "═" * 28 + " " + t)


def Pd(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def A(g, cls, name):
    return np.asarray(g.get(cls, name), np.float64)


def rot(axis, deg):
    a = np.asarray(axis, float) / np.linalg.norm(axis)
    t = math.radians(deg)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(t) * K + (1 - math.cos(t)) * K @ K


def with_P(g, P):
    o = g.copy()
    o.set(POINT, "P", np.asarray(P, np.float32))
    return o


rng = np.random.default_rng(73)
R0 = rot([1, 2, 0.5], 37)
t0 = np.array([0.5, -1.0, 2.0])

# ═══════════════════════════════════════════════════════ Extract Transform
sec("Extract Transform")
ref = ops.compute_normals(build.sphere(1, 16, 12), add_to="point")
Pr = Pd(ref)
tgt = with_P(ref, Pr @ R0.T + t0)
pt, out, r = RG.extract_transform(ref, tgt, "rigid")
Rq = quat_to_mat(A(pt, POINT, "orient"))[0]
check(f"rigid: rotation and translation recovered exactly (RMS {r['rms']:.1e})",
      np.abs(Rq - R0).max() < 1e-5 and np.abs(Pd(pt)[0] - t0).max() < 1e-5
      and r["rms"] < 1e-5)
cp = copyto.copy_to_points(ref, pt, target_attribs="")
check("  instance points fed to Copy to Points copying reference: land exactly on target",
      np.abs(Pd(cp) - Pd(tgt)).max() < 1e-5)
check("  normals of the geo output rotated too",
      np.abs(A(out, POINT, "N") - A(ref, POINT, "N") @ R0.T).max() < 1e-5)
ref3 = with_P(ref, Pr * 3 + [1, 0, 0])                 # radius 3, not at the origin
tgs = with_P(ref, 1.7 * Pd(ref3) @ R0.T + t0)
pt, out, r = RG.extract_transform(ref3, tgs, "similarity")
check(f"similarity: scale 1.7 recovered ({r['scale']:.6f}), lands on target after copying",
      abs(r["scale"] - 1.7) < 1e-5 and
      np.abs(Pd(copyto.copy_to_points(ref3, pt, target_attribs="")) - Pd(tgs)).max()
      < 1e-4)
Maff = np.array([[1.2, 0.3, -0.1], [0.0, 0.8, 0.4], [0.2, 0.1, 1.5]])
tga = with_P(ref, Pr @ Maff.T + t0)
pt, out, r = RG.extract_transform(ref, tga, "affine")
check("affine: general linear + translation recovered exactly, lands on target after copying (report / transform attribute follow "
      "Houdini's row-vector convention = Maffᵀ, pcg102)",
      np.abs(np.array(r["matrix"]) - Maff.T).max() < 1e-5 and
      np.abs(A(pt, POINT, "transform")[0].reshape(3, 3) - Maff.T).max() < 1e-5 and
      np.abs(Pd(copyto.copy_to_points(ref, pt, target_attribs="")) - Pd(tga)).max()
      < 1e-4)
noisy = with_P(ref, Pr @ R0.T + t0 + rng.normal(0, 0.02, Pr.shape))
pt, out, r = RG.extract_transform(ref, noisy, "rigid")
Rn = quat_to_mat(A(pt, POINT, "orient"))[0]
tn = Pd(pt)[0]
Pn = Pd(noisy)


def rms_of(R_, t_):
    return math.sqrt(((Pr @ R_.T + t_ - Pn) ** 2).sum(1).mean())


worse = min(rms_of(rot(ax, 0.5) @ Rn, tn) for ax in np.eye(3))
check(f"with noise (σ = 0.02): RMS {r['rms']:.4f}; perturbing the rotation by any 0.5° is worse ({worse:.4f})"
      f" -- least-squares optimal", r["rms"] < worse and abs(r["rms"] - rms_of(Rn, tn)) < 1e-6)
Po = Pr @ R0.T + t0
bad = rng.random(len(Po)) < 0.1
Po[bad] += 5.0
outl = with_P(ref, Po)
wref = ref.copy()
wref.set(POINT, "w", (~bad).astype(np.float32)[:, None])
pt_w, _, rw = RG.extract_transform(wref, outl, "rigid", "w")
pt_n, _, _ = RG.extract_transform(wref, outl, "rigid")
check("10% outliers: exact with weight 0; pulled off without weighting (negative control)",
      np.abs(quat_to_mat(A(pt_w, POINT, "orient"))[0] - R0).max() < 1e-5 and
      np.abs(Pd(pt_n)[0] - t0).max() > 0.1)
mir = with_P(ref, Pr * [-1, 1, 1])
pt, om, rm_ = RG.extract_transform(ref, mir, "rigid")
check(f"mirrored input: rigid gives a true rotation, doesn't sneak into a mirror (residual {rm_['rms']:.3f} > 0, "
      f"transformed geometry not equal to the mirror)",
      rm_["rms"] > 0.1 and np.abs(Pd(om) - Pd(mir)).max() > 0.1)
err("different point counts error", lambda: RG.extract_transform(ref, build.box()), "point numbers")

# ═══════════════════════════════════════════════════════ Attribute Transform Extract
sec("Attribute Transform Extract")
cen = np.array([[-3, 0, 0], [0, 0, 0], [3, 0, 0.]])
parts = []
for i, c in enumerate(cen):
    b = build.box((1, 1, 1), center=tuple(c), divisions=(3, 3, 3))
    b.set_string(PRIM, "name", np.array([f"p{i}"] * b.nprims))
    parts.append(b)
rest = ops.merge(*parts)
Rs = [rot([0, 1, 0], 30), rot([1, 0, 1], -50), rot([1, 1, 1], 90)]
ts = [np.array([0, 1, 0]), np.array([0, 0, 2]), np.array([1, -1, 0])]
Prest = Pd(rest)
nm = np.asarray(rest.get(PRIM, "name")).ravel()
vp, vpr = rest.vertex_point, rest.vertex_prim()
Pan = Prest.copy()
for i in range(3):
    pts = np.unique(vp[np.isin(vpr, np.nonzero(nm == f"p{i}")[0])])
    Pan[pts] = (Prest[pts] - cen[i]) @ Rs[i].T + cen[i] + ts[i]
anim = with_P(rest, Pan)
tm, rp, r = RG.attribute_transform_extract(rest, anim)
tp_, _ = DF.transform_pieces(rest, tm, rp)
check(f"three pieces each rigidly transformed: template + rest points fed to Transform Pieces restore animated"
      f" (diff {np.abs(Pd(tp_) - Pan).max():.1e})",
      np.abs(Pd(tp_) - Pan).max() < 1e-5 and r["pieces"] == 3 and r["max_rms"] < 1e-5)
hi = ops.merge(*[ops.transform(p, scale=(0.9, 0.9, 0.9), translate=tuple(c * 0.1))
                 for p, c in zip(parts, cen)])
thi, _ = DF.transform_pieces(hi, tm, rp)
Phi = Pd(hi)
nmh = np.asarray(hi.get(PRIM, "name")).ravel()
exp = Phi.copy()
for i in range(3):
    pts = np.unique(hi.vertex_point[np.isin(hi.vertex_prim(),
                                            np.nonzero(nmh == f"p{i}")[0])])
    exp[pts] = (Phi[pts] - cen[i]) @ Rs[i].T + cen[i] + ts[i]
check("  another geometry (same-named pieces, shrunk and moved a bit) follows the same rigid motion exactly, piece by piece",
      np.abs(Pd(thi) - exp).max() < 1e-5)

# ═══════════════════════════════════════════════════════ Match Axis
sec("Match Axis")
g = ops.compute_normals(build.sphere(1, 16, 12), add_to="point")
P = Pd(g)
o = RG.match_axis(g, (0, 1, 0), (1, 0, 0))
top = np.argmax(P[:, 1])
zp = Geometry.from_points(np.array([[0, 0, 1.0], [0, 0, -2.0]]))
check("y -> x: the top point goes to +x; points on the z axis stay put (minimal rotation about the z axis)",
      np.abs(Pd(o)[top] - [1, 0, 0]).max() < 1e-5 and
      np.abs(Pd(RG.match_axis(zp, (0, 1, 0), (1, 0, 0))) - Pd(zp)).max() < 1e-6)
o2 = RG.match_axis(g, (0, 1, 0), (0, -1, 0))
tet = Geometry.from_points(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1.]]))


def svol(X):
    return np.linalg.det(X[1:] - X[0])


check("y -> −y: 180°, distances unchanged, top goes to bottom; a rotation, not a mirror (signed tetrahedron volume keeps its sign)",
      np.abs(Pd(o2)[top] - [0, -1, 0]).max() < 1e-5 and
      np.abs(np.linalg.norm(Pd(o2), axis=1) - np.linalg.norm(P, axis=1)).max() < 1e-6
      and svol(Pd(RG.match_axis(tet, (0, 1, 0), (0, -1, 0)))) > 0)
tri = Geometry.from_points(np.array([[0, 1, 0], [1, 0, 0], [0, 0, 0.]]))
o3 = RG.match_axis(tri, (0, 1, 0), (0, 0, 1), up_from=(1, 0, 0), up_to=(0, 1, 0))
check("with up: (0,1,0) -> (0,0,1) and (1,0,0) -> (0,1,0)",
      np.abs(Pd(o3)[0] - [0, 0, 1]).max() < 1e-6 and
      np.abs(Pd(o3)[1] - [0, 1, 0]).max() < 1e-6)
off = ops.transform(g, translate=(2, 3, 4))
o4 = RG.match_axis(off, (1, 1, 0), (0, 0, 1), pivot="centroid")
check("pivot = centroid: centroid stays; normals rotate along",
      np.abs(Pd(o4).mean(0) - Pd(off).mean(0)).max() < 1e-5 and
      np.abs(A(o4, POINT, "N") - A(off, POINT, "N") @
             RG._min_rot(np.array([1., 1, 0]), np.array([0., 0, 1])).T).max() < 1e-5)
err("zero vector errors", lambda: RG.match_axis(g, (0, 0, 0), (1, 0, 0)), "zero vector")

# ═══════════════════════════════════════════════════════ Primitive
sec("Primitive")
bx = build.box((2, 2, 2), divisions=(3, 3, 3))
Cb = ops.prim_centers(bx).astype(np.float64)
o = D2.primitive(bx, uniform_scale=0.5)
Co = ops.prim_centers(o).astype(np.float64)


def edge_len(g_, i):
    p = Pd(g_)[g_.prim_points(i)]
    return np.linalg.norm(p - np.roll(p, -1, 0), axis=1)


check("each face scaled 0.5 about its own center: points split (point count = vertex count), center stays, edge length halves",
      o.npoints == bx.nvertices and np.abs(Co - Cb).max() < 1e-6 and
      all(np.allclose(edge_len(o, i), 0.5 * edge_len(bx, i), atol=1e-6)
          for i in range(bx.nprims)))
o = D2.primitive(bx, rotate=(0, 0, 90))
check("rotated 90° about the center: center stays, edge length unchanged",
      np.abs(ops.prim_centers(o) - Cb).max() < 1e-6 and
      all(np.allclose(edge_len(o, i), edge_len(bx, i), atol=1e-6)
          for i in range(bx.nprims)))
Nb = ops.prim_normals(bx).astype(np.float64)
o = D2.primitive(bx, normal_offset=0.2)
check("Normal Offset 0.2: each face moved 0.2 along its own normal (box 'explodes')",
      np.abs(ops.prim_centers(o) - (Cb + 0.2 * Nb)).max() < 1e-6)
sq = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0.]]),
                        [[0, 1, 2, 3]])
o = D2.primitive(sq, rotate=(0, 0, 90), scale=(2, 1, 1))
c_ = np.array([0.5, 0.5, 0])
exp_ = (Pd(sq) - c_) * [2, 1, 1] @ ops.euler_matrix(0, 0, 90).astype(float).T + c_
check("scale then rotate (same as Transform): stretched 2x in x, then rotated 90°",
      np.abs(Pd(o) - exp_).max() < 1e-6)
bx2 = bx.copy()
f = np.arange(bx.nprims, dtype=np.float32) / bx.nprims + 0.5
bx2.set(PRIM, "f", f[:, None])
o = D2.primitive(bx2, scale_attribute="f")
check("Scale Attribute: each face additionally multiplied by its own f",
      all(np.allclose(edge_len(o, i), f[i] * edge_len(bx, i), atol=1e-5)
          for i in range(bx.nprims)))
bx.set_group(PRIM, "top", Cb[:, 1] > 0.99)
o = D2.primitive(bx, group="top", translate=(0, 1, 0))
check("group: only the top faces move (the other faces' points are still shared and unmoved)",
      np.abs(ops.prim_centers(o)[Cb[:, 1] > 0.99] - (Cb[Cb[:, 1] > 0.99] + [0, 1, 0]))
      .max() < 1e-6 and np.abs(ops.prim_centers(o)[Cb[:, 1] < 0.99] -
                               Cb[Cb[:, 1] < 0.99]).max() < 1e-6)
o = D2.primitive(bx, uniform_scale=0.5, unshare_points=False)
check("Unshare off: point count unchanged (shared points get pulled by the last face -- see the file header)",
      o.npoints == bx.npoints)

# ═══════════════════════════════════════════════════════ Attribute Reorient
sec("Attribute Reorient")
s = ops.compute_normals(build.sphere(1, 24, 16), add_to="point")
q = rng.normal(size=(s.npoints, 4))
q /= np.linalg.norm(q, axis=1, keepdims=True)
s.set(POINT, "orient", q.astype(np.float32))
d = with_P(s, Pd(s) @ R0.T + t0)
o, r = D2.attribute_reorient(d, s)
check("global rotation: N rotated exactly, orient left-multiplied exactly",
      np.abs(A(o, POINT, "N") - A(s, POINT, "N") @ R0.T).max() < 1e-5 and
      np.abs(quat_to_mat(A(o, POINT, "orient")) -
             np.einsum("ij,njk->nik", R0, quat_to_mat(q))).max() < 1e-5)
cyl = ops.compute_normals(build.tube(0.5, 0.5, 3, 24, 30, caps=False), add_to="point")
tw = twist(cyl, "twist", axis="y", angle=120, normals="none")
o, _ = D2.attribute_reorient(tw, cyl)
Ntrue = A(ops.compute_normals(tw, add_to="point"), POINT, "N")
ang_new = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", A(o, POINT, "N"), Ntrue), -1, 1)))
ang_old = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", A(tw, POINT, "N"), Ntrue), -1, 1)))
check(f"cylinder twisted 120°: median diff between rotated N and recomputed normals {np.median(ang_new):.1f}°"
      f" (unrotated: {np.median(ang_old):.1f}°)",
      np.median(ang_new) < 3 and np.median(ang_old) > 20)
crv = Geometry.from_mesh(np.c_[np.linspace(0, 2, 9), np.zeros(9), np.zeros(9)],
                        [list(range(9))], closed=False)
crv.set(POINT, "N", np.tile([0, 1, 0.0], (9, 1)).astype(np.float32))
bent = with_P(crv, np.c_[np.sin(np.linspace(0, 2, 9) * 0.8), 1 - np.cos(
    np.linspace(0, 2, 9) * 0.8), np.zeros(9)] / 0.8)
oc, _ = D2.attribute_reorient(bent, crv)
tang = np.gradient(Pd(bent), axis=0)
tang /= np.linalg.norm(tang, axis=1, keepdims=True)
Qs = rot([0.3, -1.0, 0.7], 63)                       # the whole thing set to a slanted orientation
crv2 = with_P(crv, Pd(crv) @ Qs.T)
N0 = np.array([0, 0, 1.0]) @ Qs.T
crv2.set(POINT, "N", np.tile(N0, (9, 1)).astype(np.float32))
oc2, _ = D2.attribute_reorient(with_P(crv2, Pd(bent) @ Qs.T), crv2)
check("  slanted curve, N perpendicular to the bending plane (binormal): N unchanged after bending (no spurious twist about the tangent -- "
      "on a collinear neighborhood Kabsch gives an arbitrary twist angle)",
      np.abs(A(oc2, POINT, "N") - N0).max() < 1e-6)
check("curve (collinear neighborhood): N rotates with the tangent -- still perpendicular to the curve and in the bending plane",
      np.abs(np.einsum("ij,ij->i", A(oc, POINT, "N"), tang)).max() < 0.05 and
      np.abs(A(oc, POINT, "N")[:, 2]).max() < 1e-6)
err("different point counts error", lambda: D2.attribute_reorient(build.box(), s), "same topology")

# ═══════════════════════════════════════════════════════ Match Topology
sec("Match Topology")
ref = build.sphere(1, 12, 8)
ref.set(POINT, "id", np.arange(ref.npoints, dtype=np.int32)[:, None])
ref.set(PRIM, "pid", np.arange(ref.nprims, dtype=np.int32)[:, None])
P = Pd(ref)
perm = rng.permutation(ref.npoints)
inv = np.argsort(perm)
faces = [inv[ref.prim_points(i)].tolist() for i in range(ref.nprims)]
rot_k = rng.integers(0, 4, len(faces))
rot_k[0] = 2                                          # face 0's starting vertex is definitely rotated
faces = [f_[k:] + f_[:k] for f_, k in zip(faces, rot_k)]
fo = rng.permutation(len(faces))
faces = [faces[i] for i in fo]
warp = lambda X: X * [1, 2, 1] + 0.3 * np.sin(X * 5)      # noqa: E731
sh = Geometry.from_mesh(warp(P[perm]), faces, True)
sh.set(POINT, "id", np.arange(ref.npoints, dtype=np.int32)[perm][:, None])
sh.set(PRIM, "pid", np.arange(ref.nprims, dtype=np.int32)[fo][:, None])
out, r = RG.match_topology(ref, sh, "topology", 0, int(ref.prim_points(0)[0]),
                           int(np.nonzero(fo == 0)[0][0]),
                           int(inv[ref.prim_points(0)[0]]))
check(f"point numbers, prim numbers, starting vertices all shuffled + heavy deformation: topology mode matches "
      f"{r['points_matched']}/{r['points_ref']} points, {r['prims_matched']} faces, 0 conflicts",
      r["points_matched"] == ref.npoints and r["conflicts"] == 0 and
      all(np.array_equal(out.prim_points(i), ref.prim_points(i))
          for i in range(ref.nprims)))
check("  point and prim attributes follow (id / pid back to 0,1,2...), positions are the deformed ones",
      np.array_equal(A(out, POINT, "id").ravel(), np.arange(ref.npoints)) and
      np.array_equal(A(out, PRIM, "pid").ravel(), np.arange(ref.nprims)) and
      np.abs(Pd(out) - warp(P)).max() < 1e-5)
sh2 = Geometry.from_mesh(P[perm] * 1.03, faces, True)
out2, r2 = RG.match_topology(ref, sh2)
check("auto seed (when shapes roughly overlap): also all matched",
      r2["points_matched"] == ref.npoints and r2["conflicts"] == 0 and
      np.abs(Pd(out2) - P * 1.03).max() < 1e-5)
out3, r3 = RG.match_topology(ref, Geometry.from_mesh(P[perm], faces, True),
                             "position", tolerance=1e-4)
check("position mode: shape unchanged, only numbering shuffled -> all matched",
      r3["points_matched"] == ref.npoints and np.abs(Pd(out3) - P).max() < 1e-6)
_, r4 = RG.match_topology(ref, sh, "position", tolerance=1e-3)
check(f"  negative control: same input but deformed, position matches only {r4['points_matched']}",
      r4["points_matched"] < ref.npoints // 4)
gq = build.grid(3, 3, 4, 4)
fq = [gq.prim_points(i).tolist() for i in range(gq.nprims)]
q4 = fq[4]
fq2 = fq[:4] + [[q4[0], q4[1], q4[2]], [q4[0], q4[2], q4[3]]] + fq[5:]
gtri = Geometry.from_mesh(Pd(gq), fq2, True)
_, r6 = RG.match_topology(gq, gtri, "topology", 0, int(fq[0][0]), 0, int(fq[0][0]))
check(f"a quad in the middle cut into two triangles: unmatched faces are not forced (matched {r6['prims_matched']}"
      f"/{gq.nprims} faces, conflicts {r6['conflicts']})",
      r6["prims_matched"] < gq.nprims and r6["conflicts"] > 0)
dupP = np.vstack([Pd(gq), Pd(gq)[:4]])                 # each of the first 4 points has a coincident point
gd = Geometry.from_points(dupP)
gd2 = Geometry.from_points(dupP[rng.permutation(len(dupP))])
od, rd6 = RG.match_topology(gd, gd2, "position")
check(f"position mode with coincident points: each target point matched only once (conflicts {rd6['conflicts']}), "
      f"output point count unchanged, positions matched one by one",
      od.npoints == gd2.npoints and rd6["conflicts"] > 0 and
      np.abs(Pd(od) - dupP).max() < 1e-6)
other = build.sphere(1, 12, 9)
_, r5 = RG.match_topology(ref, other, "topology", 0, int(ref.prim_points(0)[0]), 0,
                          int(other.prim_points(0)[0]))
check(f"different topology (12×8 vs 12×9): report has conflicts ({r5['conflicts']}) or incomplete matching",
      r5["conflicts"] > 0 or r5["points_matched"] < ref.npoints)

# ═══════════════════════════════════════════════════════ Topo Transfer
sec("Topo Transfer")


def flips(o_, tgt_):
    P_ = Pd(o_)
    T_, _, _ = SP.tri_soup(o_)
    fn = np.cross(P_[T_[:, 1]] - P_[T_[:, 0]], P_[T_[:, 2]] - P_[T_[:, 0]])
    Tt, _, _ = SP.tri_soup(tgt_)
    Pt_ = Pd(tgt_)
    ti, _, _, _ = SP.closest_surface(P_[T_].mean(1), Pt_, Tt)
    tn = np.cross(Pt_[Tt[ti, 1]] - Pt_[Tt[ti, 0]], Pt_[Tt[ti, 2]] - Pt_[Tt[ti, 0]])
    a_ = np.linalg.norm(fn, axis=1)
    return int(((fn * tn).sum(1) < 0).sum()), float(a_.min() / a_.mean())


src = build.sphere(1, 32, 24)
tg = build.sphere(1, 64, 48)
Pt = Pd(tg)
dent = np.exp(-((Pt[:, 0] - 1) ** 2 + Pt[:, 1] ** 2 + Pt[:, 2] ** 2) / 0.35)
tg = with_P(tg, Pt - dent[:, None] * [1.3, 0, 0])
tg = ops.transform(tg, translate=(3, 1, 0), rotate=(0, 30, 0))
o, r = RG.topo_transfer(src, tg, 30, 20)
fl, ar = flips(o, tg)
o0, _ = RG.topo_transfer(src, tg, 1, 0)
fl0, ar0 = flips(o0, tg)
check(f"target with a dent: all points on the target surface (farthest {r['max_distance']:.1e}), {fl} flipped faces, "
      f"smallest triangle / mean = {ar:.3f}",
      r["max_distance"] < 1e-6 and fl == 0 and ar > 0.05)
check(f"  negative control: projecting once only (no displacement smoothing): {fl0} flipped faces, smallest triangle / mean = {ar0:.4f}",
      fl0 > 0 and ar0 < ar / 5)
srcL = ops.transform(src, scale=(0.5, 0.5, 0.5), rotate=(40, 0, 70),
                     translate=(-5, 2, 1))
Ps = Pd(srcL)
li = np.array([600, 0, 400, 50, 200])                 # deliberately not in point number order
lt = [int(np.argmin(np.linalg.norm(Pd(tg) - (Pd(src)[k] @ rot([0, 1, 0], 30).T
                                            + [3, 1, 0]), axis=1))) for k in li]
lm_s = np.full(srcL.npoints, -1, np.int32)
lm_s[li] = np.arange(5)
lm_t = np.full(tg.npoints, -1, np.int32)
lm_t[lt] = np.arange(5)
srcL.set(POINT, "landmark", lm_s[:, None])
tg2 = tg.copy()
tg2.set(POINT, "landmark", lm_t[:, None])
o, r = RG.topo_transfer(srcL, tg2, 30, 20, 0.5, "landmark")
check(f"landmarks (integer point attribute pairing): matches even with source shrunk, rotated, moved far; 5 land exactly, "
      f"other points on the surface (farthest {r['max_distance']:.1e})",
      np.abs(Pd(o)[li] - Pd(tg2)[lt]).max() < 1e-6 and r["max_distance"] < 1e-6
      and r["landmarks"] == 5 and flips(o, tg2)[0] == 0)
dup = srcL.copy()
lm_d = lm_s.copy()
lm_d[1] = 0
dup.set(POINT, "landmark", lm_d[:, None])
err("duplicate landmark ids error", lambda: RG.topo_transfer(dup, tg2, 2, 1), "duplicate")
err("landmark on only one side errors", lambda: RG.topo_transfer(srcL, tg, 2, 1), "both sides")

# ═══════════════════════════════════════════════════════ DeltaMush
sec("DeltaMush")
base = build.sphere(1, 48, 32)
Pb = Pd(base)
bumpy = with_P(base, Pb * (1 + 0.04 * (np.sin(Pb[:, 0] * 25) *
                                      np.cos(Pb[:, 1] * 25)))[:, None])
o, r = D2.delta_mush(bumpy, bumpy)
check("deformed = rest: unchanged", np.abs(Pd(o) - Pd(bumpy)).max() < 1e-6)
rig = with_P(bumpy, Pd(bumpy) @ R0.T + t0)
o, _ = D2.delta_mush(rig, bumpy)
check(f"rigid motion: result exactly equals deformed (diff {np.abs(Pd(o) - Pd(rig)).max():.1e})",
      np.abs(Pd(o) - Pd(rig)).max() < 1e-5)
gt = twist(bumpy, "twist", axis="y", angle=90, normals="none")
# The "broken" part of the deformation is simulated with high-frequency noise (bad skin weights, jitter at joints): DeltaMush treats it as
# part of the large shape and smooths it out, and the detail is pasted back the way it was in rest
lossy = with_P(gt, Pd(gt) + rng.normal(0, 0.02, (gt.npoints, 3)))
o, _ = D2.delta_mush(lossy, bumpy, 10, 0.5)


def rms(X):
    return math.sqrt(((X - Pd(gt)) ** 2).sum(1).mean())


e_before, e_after = rms(Pd(lossy)), rms(Pd(o))
check(f"twist + deformation noise: RMS to ground truth after correction {e_after:.4f} (before correction {e_before:.4f})",
      e_after < 0.45 * e_before)
gr = build.grid(2, 2, 15, 15)
grn = with_P(gr, Pd(gr) + rng.normal(0, 0.01, (gr.npoints, 3)))
og, _ = D2.delta_mush(grn, gr, 10, 0.5, pin_boundary=True)
from comfyui_pcg.geo.topology import topology as _topo   # noqa: E402
tb = _topo(gr)
bpts = np.unique(tb.edge_points[tb.boundary])
check("open mesh, boundary pinned: boundary points unchanged (no shrinking inward)",
      np.abs(Pd(og)[bpts] - Pd(grn)[bpts]).max() < 1e-7)
mk = lossy.copy()
mk.set(POINT, "m", np.zeros((lossy.npoints, 1), np.float32))
o, _ = D2.delta_mush(mk, bumpy, mask_attribute="m")
check("Mask = 0: deformed unchanged", np.abs(Pd(o) - Pd(lossy)).max() < 1e-7)

# ═══════════════════════════════════════════════════════ Nodes
sec("Nodes")
NEW = {"PCG_ExtractTransform": "PCG/modify", "PCG_AttribTransformExtract": "PCG/attribute",
       "PCG_MatchAxis": "PCG/modify", "PCG_Primitive": "PCG/modify",
       "PCG_AttribReorient": "PCG/attribute", "PCG_MatchTopology": "PCG/topology",
       "PCG_TopoTransfer": "PCG/deform", "PCG_DeltaMush": "PCG/deform"}
check("all 8 nodes registered, category correct",
      all(k in MAP and MAP[k].CATEGORY == v for k, v in NEW.items()))
bad = [k for k in NEW for nm_ in MAP[k].INPUT_TYPES()["required"]
       if nm_ in ("seed", "class")]
check("no widget named seed / class", not bad, bad)


def unwrap(r):
    return tuple(r["result"]) if isinstance(r, dict) else r


def defaults(cls, **over):
    kw = {}
    for nm_, spec in cls.INPUT_TYPES()["required"].items():
        if nm_ in over:
            kw[nm_] = over[nm_]
        elif isinstance(spec[0], list):
            kw[nm_] = spec[1].get("default", spec[0][0]) if len(spec) > 1 \
                else spec[0][0]
        elif len(spec) > 1 and "default" in spec[1]:
            kw[nm_] = spec[1]["default"]
    return kw


bad = []
for k, kw in {"PCG_ExtractTransform": dict(reference=ref, target=sh2),
              "PCG_AttribTransformExtract": dict(rest=rest, animated=anim),
              "PCG_MatchAxis": dict(geo=g), "PCG_Primitive": dict(geo=bx),
              "PCG_AttribReorient": dict(geo=d, rest=s),
              "PCG_MatchTopology": dict(geo=sh2, reference=ref),
              "PCG_TopoTransfer": dict(geo=src, target=tg),
              "PCG_DeltaMush": dict(geo=lossy, rest=bumpy)}.items():
    try:
        r = unwrap(MAP[k]().run(**defaults(MAP[k], **kw)))
        if not isinstance(r[0], Geometry):
            bad.append(k)
    except Exception as ex:                       # noqa: BLE001
        bad.append(f"{k}: {ex}")
check("all 8 nodes run with default parameters (required inputs connected)", not bad, bad)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
