"""
Adjacency (geo/cop/adjacency.py): reading a texture across its uv seams. Analytic: two unit quads that share the
3D edge x = 1, on two uv islands, the second turned a quarter turn (and, in one case, twice the size), so every
across-seam read has a closed form. Negative controls: the same reads without the adjacency.
"""
import os
import sys
_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))), "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
import numpy as np
from comfyui_pcg.geo import Geometry, POINT, VERTEX, PRIM
from comfyui_pcg.geo.cop import adjacency as A
from comfyui_pcg.geo.cop.core import CopImage
from comfyui_pcg.geo.cop.pixel import getn

OK = []
def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)

def err(name, fn, frag):
    try:
        fn(); check(name, False, "no error raised")
    except Exception as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:110]}")


def quads(split=False, k=1.0):
    """Quad A: x 0..1, z 0..1 -> u 0.1..0.4, v 0.1..0.4 (u along x, v along z).
    Quad B: x 1..2, z 0..1 -> a quarter turn: v = 0.5 + 0.3 k (x - 1), u = 0.9 - 0.3 k z  (k = its uv scale)."""
    if split:
        P = np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1], [1, 0, 0], [2, 0, 0], [2, 0, 1], [1, 0, 1]], float)
        faces = [[0, 1, 2, 3], [4, 5, 6, 7]]
    else:
        P = np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1], [2, 0, 0], [2, 0, 1]], float)
        faces = [[0, 1, 2, 3], [1, 4, 5, 2]]
    g = Geometry.from_mesh(P, faces)
    uv = []
    for f in faces:
        for p in f:
            x, _, z = P[p]
            uv.append([0.1 + 0.3 * x, 0.1 + 0.3 * z, 0.0])
    uv = np.array(uv)
    for c in range(4, 8):                                           # the second quad's corners
        p = faces[1][c - 4]
        x, _, z = P[p]
        uv[c] = [0.9 - 0.3 * k * z, 0.5 + 0.3 * k * (x - 1), 0.0]
    g.set(VERTEX, "uv", uv)
    g.set(POINT, "N", np.tile([0.0, 1.0, 0.0], (len(P), 1)))
    g.set(POINT, "hx", P[:, 0].copy())
    g.set(PRIM, "tag", np.array([3.0, 7.0]))
    return g


R = 200
G = quads()
ADJ = A.geometry_to_adjacency(G, R, R, padding=12)
m = getn(ADJ, "adj_mask")[..., 0] > 0.5
auv = getn(ADJ, "adj_uv")
val = getn(ADJ, "adj_valid")[..., 0] > 0.5
jac = getn(ADJ, "adj_jac")
uc = (np.arange(R) + 0.5) / R                                       # texel centres

print("-- layers")
names = set(ADJ.names)
check("all adjacency layers are written", {"adj_" + n for n in (
    "mask", "uv", "valid", "jac", "near", "tri", "bary", "primid", "P", "N", "tanU", "tanV", "uvscale")} <= names)
area = m.mean()
check("the mask covers the two islands (2 x 0.09 of the image, plus the half-texel margin)",
      0.18 <= area < 0.18 + 8 * 0.3 / R, round(float(area), 4))
i0, j0 = 50, 50                                                     # inside A: u = v = 0.2525
check("inside an island adj_uv is the texel's own uv, jacobian identity",
      np.allclose(auv[i0, j0], [uc[j0], uc[i0]], atol=1e-6) and np.allclose(jac[i0, j0], [1, 0, 0, 1]) and not val[i0, j0])
Pl = getn(ADJ, "adj_P")
check("adj_P is the surface position (x = (u - 0.1) / 0.3, z = (v - 0.1) / 0.3)",
      np.allclose(Pl[i0, j0], [(uc[j0] - 0.1) / 0.3, 0, (uc[i0] - 0.1) / 0.3], atol=1e-5), Pl[i0, j0].round(4))
check("adj_N is the normal, adj_tanU = dP/du, adj_tanV = dP/dv",
      np.allclose(getn(ADJ, "adj_N")[i0, j0], [0, 1, 0], atol=1e-6)
      and np.allclose(getn(ADJ, "adj_tanU")[i0, j0], [1 / 0.3, 0, 0], atol=1e-4)
      and np.allclose(getn(ADJ, "adj_tanV")[i0, j0], [0, 0, 1 / 0.3], atol=1e-4))
ib, jb = 120, 150                                                   # inside B
check("on the turned island tanU = -z / 0.3, tanV = +x / 0.3",
      np.allclose(getn(ADJ, "adj_tanU")[ib, jb], [0, 0, -1 / 0.3], atol=1e-4)
      and np.allclose(getn(ADJ, "adj_tanV")[ib, jb], [1 / 0.3, 0, 0], atol=1e-4))
check("adj_uvscale = world units per uv unit (1 / 0.3)",
      abs(getn(ADJ, "adj_uvscale")[i0, j0, 0] - 1 / 0.3) < 1e-4)
check("adj_primid tells the islands apart, -1 outside",
      getn(ADJ, "adj_primid")[i0, j0, 0] == 0 and getn(ADJ, "adj_primid")[ib, jb, 0] == 1
      and getn(ADJ, "adj_primid")[5, 5, 0] == -1)

print("-- the seam")
# right of A's edge u = 0.4: texel (i, j) with u = 0.4 + d  ->  B at (0.9 - (v - 0.1), 0.5 + d)
i1, j1 = 50, 83                                                     # u = 0.4175, v = 0.2525
d = uc[j1] - 0.4
exp = [0.9 - (uc[i1] - 0.1), 0.5 + d]
check("a texel beyond the seam points at the continuation on the other island",
      (not m[i1, j1]) and val[i1, j1] and np.allclose(auv[i1, j1], exp, atol=2e-6),
      f"{auv[i1, j1].round(5)} vs {np.round(exp, 5)}")
check("its jacobian is the quarter turn between the islands", np.allclose(jac[i1, j1], [0, -1, 1, 0], atol=1e-6),
      jac[i1, j1].round(4))
# below B's edge v = 0.5: texel with v = 0.5 - d2 at u  ->  A at (0.4 - d2, 0.1 + (0.9 - u))
i2, j2 = 97, 150
d2 = 0.5 - uc[i2]
exp2 = [0.4 - d2, 0.1 + (0.9 - uc[j2])]
check("and the other way round (B's seam texels point into A)",
      (not m[i2, j2]) and val[i2, j2] and np.allclose(auv[i2, j2], exp2, atol=2e-6),
      f"{auv[i2, j2].round(5)} vs {np.round(exp2, 5)}")
check("... with the inverse turn", np.allclose(jac[i2, j2], [0, 1, -1, 0], atol=1e-6))
# left of A's edge u = 0.1: a mesh border
i3, j3 = 50, 16
check("at a mesh border adj_uv clamps to the edge and adj_valid is 0",
      (not m[i3, j3]) and (not val[i3, j3]) and np.allclose(auv[i3, j3], [0.1, uc[i3]], atol=2e-6)
      and np.allclose(jac[i3, j3], 0), auv[i3, j3].round(5))
check("beyond Padding nothing is recorded (own uv, not valid)",
      (not val[50, 0]) and np.allclose(auv[50, 0], [uc[0], uc[50]], atol=1e-6))
big = A.geometry_to_adjacency(G, R, R, padding=40)
check("Padding sets the reach", (getn(big, "adj_valid") > 0.5).sum() > 2.5 * val.sum(),
      f"{int((getn(big, 'adj_valid') > 0.5).sum())} vs {int(val.sum())}")
S = A.geometry_to_adjacency(quads(split=True), R, R, padding=12)
check("unwelded points (a split seam) pair up by position: same layers",
      np.allclose(getn(S, "adj_uv"), auv, atol=1e-6) and np.array_equal(getn(S, "adj_valid")[..., 0] > 0.5, val))
K = A.geometry_to_adjacency(quads(k=2.0), R, R, padding=12)   # B twice as large in uv: u 0.3..0.9, v 0.5..1.1
kuv, kj = getn(K, "adj_uv"), getn(K, "adj_jac")
expk = [0.9 - 2 * (uc[i1] - 0.1), 0.5 + 2 * d]
check("islands of different texel density: distances scale by the ratio (x 2)",
      np.allclose(kuv[i1, j1], expk, atol=4e-6) and np.allclose(kj[i1, j1], [0, -2, 2, 0], atol=1e-5),
      f"{kuv[i1, j1].round(5)} vs {np.round(expk, 5)}")

print("-- attribute sample")
T = A.attribute_sample(ADJ, G, "P", extrapolate_seams=False)
Pt = getn(T, "P")
check("Attribute Sample bakes a point attribute through tri / bary", np.allclose(Pt[m], Pl[m], atol=1e-6)
      and np.allclose(Pt[~m], 0))
check("... a primitive attribute", np.allclose(getn(A.attribute_sample(ADJ, G, "tag", extrapolate_seams=False),
                                                    "tag")[[i0, ib], [j0, jb], 0], [3, 7]))
G2 = G.copy()
G2.set(POINT, "P", np.asarray(G.get(POINT, "P")) * 2.0 + 1.0)
check("... from a second geometry of the same topology (a deformed copy)",
      np.allclose(getn(A.attribute_sample(ADJ, G, "P", attrib_geo=G2, extrapolate_seams=False), "P")[m],
                  Pl[m] * 2 + 1, atol=1e-5))
TE = getn(A.attribute_sample(ADJ, G, "P", out_layer="Pe"), "Pe")
xe = 1 + d / 0.3
check("with Extrapolate the seam texel holds the continued surface (x = 1 + d / 0.3), not the edge",
      abs(TE[i1, j1, 0] - xe) < 1e-4 and abs(TE[i1, j1, 2] - (uc[i1] - 0.1) / 0.3) < 1e-4,
      f"{TE[i1, j1].round(4)} vs x {xe:.4f}")
err("a missing attribute is named", lambda: A.attribute_sample(ADJ, G, "nope"), "nope")
err("a geometry with fewer triangles is refused",
    lambda: A.attribute_sample(ADJ, Geometry.from_mesh(np.eye(3), [[0, 1, 2]]), "P"), "does not match")

print("-- extrapolate")
X = getn(A.extrapolate(T, "P"), "P")
check("Extrapolate leaves the islands alone", np.allclose(X[m], Pt[m]))
check("across the seam it continues the surface: x = 1 + d / 0.3 (negative control: the edge value 1)",
      abs(X[i1, j1, 0] - xe) < 1e-4 and abs(xe - 1.0) > 0.05, f"{X[i1, j1, 0]:.4f} vs {xe:.4f}")
check("... from B into A: x = 1 - d2 / 0.3", abs(X[i2, j2, 0] - (1 - d2 / 0.3)) < 1e-4, round(float(X[i2, j2, 0]), 4))
check("at a mesh border it repeats the edge (x = 0)", abs(X[i3, j3, 0]) < 1e-4 and abs(X[i3, j3, 2] - Pt[i3, 20, 2]) < 1e-3)
check("beyond Padding the texel is left as it was", np.allclose(X[50, 0], Pt[50, 0]))
out_sel = (~m) & val
lin = np.abs(X[..., 0][out_sel] - 1.0).max()
check("every seam texel is within Padding of the edge on the other side (|x - 1| <= 12 texels / 0.3)",
      lin <= 12 / R / 0.3 + 1e-3, round(float(lin), 4))
# a direction field in texture space: "+x of the world" is (1, 0) on A and (0, 1) on the turned island B
F = np.zeros((R, R, 2))
pid = getn(ADJ, "adj_primid")[..., 0]
F[pid == 0] = [1, 0]
F[pid == 1] = [0, 1]
FI = ADJ.copy()
FI.set("flow", F.astype(np.float32))
plain = getn(A.extrapolate(FI, "flow"), "flow")
turned = getn(A.extrapolate(FI, "flow", transform_vectors=True), "flow")
check("Transform Vectors turns a texture-space direction into this island's frame: (1, 0) both sides",
      np.allclose(turned[i1, j1], [1, 0], atol=1e-5) and np.allclose(turned[i2, j2], [0, 1], atol=1e-5),
      turned[i1, j1].round(3))
check("negative control: without it the neighbour's raw (0, 1) arrives", np.allclose(plain[i1, j1], [0, 1], atol=1e-5))
E2 = A.extrapolate(T, "")
check("an empty layer list takes every layer but the adjacency's own",
      np.allclose(getn(E2, "P"), X) and np.allclose(getn(E2, "adj_uv"), auv))
err("a missing layer is named", lambda: A.extrapolate(T, "nope"), "nope")
err("without adjacency layers the node says what to connect",
    lambda: A.extrapolate(CopImage(8, 8, {"C": np.zeros((8, 8, 3), np.float32)})), "Geometry to Adjacency")

print("-- distort")
sh = 0.05
D = getn(A.distort(T, "P", f"{sh} 0"), "P")
ii, jj = 50, 60                                                     # inside A, 0.05 from here is still inside
check("inside an island Distort is a plain shifted read (x + 0.05 / 0.3)",
      abs(D[ii, jj, 0] - (Pt[ii, jj, 0] + sh / 0.3)) < 1e-4)
ii, jj = 50, 76                                                     # u = 0.3825 -> 0.4325: across the seam
xs = (uc[jj] + sh - 0.1) / 0.3
check("a read that crosses the seam lands on the other island: x keeps growing past 1",
      xs > 1.05 and abs(D[ii, jj, 0] - xs) < 1e-4 and abs(D[ii, jj, 2] - Pt[ii, jj, 2]) < 1e-4,
      f"{D[ii, jj, 0]:.4f} vs {xs:.4f}")
raw = Pt[ii, jj + int(round(sh * R)), 0]
check("negative control: the same shift without adjacency reads the empty texture", abs(raw) < 1e-6)
DL = T.copy()
dirl = np.zeros((R, R, 2), np.float32)
dirl[..., 0] = 1.0
DL.set("dir", dirl)
check("Dir Layer x Scale gives the same as the constant Direction",
      np.allclose(getn(A.distort(DL, "P", "0 0", "dir", sh), "P"), D, atol=1e-6))
check("Direction 0 changes nothing inside the islands", np.allclose(getn(A.distort(T, "P", "0 0"), "P")[m], Pt[m], atol=1e-6))
check("Out Layer keeps the source", np.allclose(getn(A.distort(T, "P", f"{sh} 0", out_layer="Q"), "P"), Pt))

print("-- space transform")
V = ADJ.copy()
wv = np.zeros((R, R, 3), np.float32)
wv[..., 0], wv[..., 1] = 1.0, 0.5
V.set("v", wv)
tg = getn(A.space_transform(V, "v", "world_to_tangent", out_layer="t"), "t")
check("world +x is tangent +u on A and +v on the turned B; world +y is the normal (z)",
      np.allclose(tg[i0, j0], [1, 0, 0.5], atol=1e-5) and np.allclose(tg[ib, jb], [0, 1, 0.5], atol=1e-5),
      f"{tg[i0, j0].round(3)} {tg[ib, jb].round(3)}")
back = getn(A.space_transform(A.space_transform(V, "v", "world_to_tangent", out_layer="t"), "t",
                              "tangent_to_world", out_layer="w"), "w")
check("tangent -> world undoes it", np.allclose(back[m], wv[m], atol=1e-5))
check("outside the islands the result is 0", np.allclose(tg[~m], 0))
check("signature uv keeps two channels",
      getn(A.space_transform(V, "v", signature="uv", out_layer="t2"), "t2").shape[2] == 2)
err("an unknown transformation is refused", lambda: A.space_transform(V, "v", "sideways"), "one of")

print("-- nodes")
sys.path.insert(0, _R)
import fakecomfy  # noqa: E402,F401
from comfyui_pcg import nodes as N  # noqa: E402
from comfyui_pcg import panel_specs as PS  # noqa: E402
M = N.NODE_CLASS_MAPPINGS
NODES = ("PCG_COPGeometryToAdjacency", "PCG_COPExtrapolateWithAdjacency", "PCG_COPDistortWithAdjacency",
         "PCG_COPAttributeSampleWithAdjacency", "PCG_COPSpaceTransformWithAdjacency")
check("the five nodes are registered, each with a panel spec that covers its widgets",
      all(n in M and set(PS.SPECS[n]["order"]) == {k for k, v in M[n].INPUT_TYPES()["required"].items()
                                                    if v[0] not in ("COPIMAGE", "GEOMETRY")} for n in NODES))
na = M["PCG_COPGeometryToAdjacency"]().run(G, "uv", 12, "adj_", R, R)[0]
check("Geometry to Adjacency (node) = the engine", np.allclose(getn(na, "adj_uv"), auv))
nt = M["PCG_COPAttributeSampleWithAdjacency"]().run(na, G, "P", "", False, "adj_")[0]
nx_ = M["PCG_COPExtrapolateWithAdjacency"]().run(nt, "P", False, "adj_")[0]
check("Attribute Sample -> Extrapolate (nodes) continue the surface across the seam",
      abs(getn(nx_, "P")[i1, j1, 0] - xe) < 1e-4)
nd = M["PCG_COPDistortWithAdjacency"]().run(nt, "P", f"{sh} 0", "", 1.0, False, "", "adj_")[0]
check("Distort (node) = the engine", np.allclose(getn(nd, "P"), D))
ns = M["PCG_COPSpaceTransformWithAdjacency"]().run(V, "v", "world_to_tangent", "rgb", "t", "adj_")[0]
check("Space Transform (node) = the engine", np.allclose(getn(ns, "t"), tg))
P2 = A.geometry_to_adjacency(G, R, R, padding=12, prefix="seam_")
check("a custom Prefix names the layers, and the readers follow it",
      "seam_uv" in P2 and "adj_uv" not in P2
      and np.allclose(getn(A.attribute_sample(P2, G, "P", prefix="seam_"), "P"), TE))

n = len(OK)
print(f"\n{sum(OK)} / {n} adjacency checks pass")
sys.exit(0 if all(OK) else 1)
