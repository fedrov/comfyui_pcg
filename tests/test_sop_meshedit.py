"""
pcg74: mesh editing -- Edge Equalize, Edge Straighten, Circle from Edges, Edge Flip,
Tri Divide, Unsubdivide, Rewire Vertices, PolyCut, PolyStitch, Voronoi Split.

The references do not rely on the implementation itself:
  Edge Equalize     points stay on the original polyline; arc length / chord length equal per segment (negative control: input clearly unequal);
                    endpoints and branch points do not move; average displacement around a closed loop is 0 (minimal phase)
  Edge Straighten   points lie on the line between the two ends, ratio = original arc-length ratio / even / perpendicular projection; closed loops skipped
  Circle from Edges distance to center all equal R, coplanar, equal angles, winding unchanged, average rotation 0
  Edge Flip         two triangles flip to the other diagonal, normals same direction; two quads stay quads after rotating the edge,
                    total area unchanged; after delaunay every interior edge's opposite angle sum <= 180 deg (negative control: violations before flipping);
                    flips that would create duplicate edges (tetrahedron) are not done; uv follows the corners
  Tri Divide        edge length / area within limits; conforming (interior edges have two prims, boundary is only the outer contour); points lie on
                    the original surface; linear attributes interpolated exactly; minimum angle not below half the original; unselected prims get
                    midpoints inserted, none missed
  Unsubdivide       Subdivide level 1, 2 and back: point numbers, prims, starting corner identical, positions to float32;
                    uv / prim attributes restored; keep mode (negative control) is far off; a cube is recognized as a cube, not an octahedron;
                    meshes not produced by subdivision raise; boundary rules must match
  Rewire Vertices   two separate quads rewired to share an edge; point-class attributes work too; -1 does not move; degenerate prims removed
  PolyCut           threshold cut: the kept side is entirely on the threshold side, inserted points lie exactly on the threshold, shared by neighbouring prims;
                    cut at points, keep edges of a point group
  PolyStitch        different resolutions + a thin gap: after stitching interior edges have two prims, boundary is only the outer contour, seam points
                    all on one line; tolerance too small (negative control) does nothing
  Voronoi Split     every point of every prim is closest to its own cell point; cut points equidistant to two cell points; area unchanged;
                    shared-point mode keeps the sphere closed; split-point mode connected pieces = cell count; linear attributes interpolated exactly
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

from comfyui_pcg.geo import meshedit as ME              # noqa: E402
from comfyui_pcg.geo import unsubdivide as US           # noqa: E402
from comfyui_pcg.geo import voronoisplit as VS          # noqa: E402
from comfyui_pcg.geo import build, ops, subdivide as SD  # noqa: E402
from comfyui_pcg.geo.topology import topology           # noqa: E402
from comfyui_pcg.geo.convertline import _paths          # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, PRIM, VERTEX  # noqa: E402
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


def polyline(P, closed=False):
    g = Geometry.from_mesh(np.asarray(P, np.float32),
                           [list(range(len(P)))], closed=closed)
    return g


def all_edges(g):
    return np.asarray(topology(g).edge_points)


def seg_dist(Q, X):
    """Distance from Q to polyline X, and arc-length parameter."""
    best_d = np.full(len(Q), np.inf)
    best_u = np.zeros(len(Q))
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(X, axis=0), axis=1))]
    for j in range(len(X) - 1):
        A, B = X[j], X[j + 1]
        d = B - A
        L2 = d @ d
        t = np.clip((Q - A) @ d / L2, 0, 1)
        dist = np.linalg.norm(A + t[:, None] * d - Q, axis=1)
        m = dist < best_d - 1e-12
        best_d[m] = dist[m]
        best_u[m] = s[j] + t[m] * np.sqrt(L2)
    return best_d, best_u


def tri_area(P, f):
    X = P[f]
    return 0.5 * np.linalg.norm(np.cross(X, np.roll(X, -1, 0)).sum(0))


def newell(X):
    return np.cross(X, np.roll(X, -1, 0)).sum(0)


def dist_to_mesh(Q, g):
    from comfyui_pcg.geo.spatial import closest_surface, tri_soup
    tri, _, _ = tri_soup(g)
    _, _, pos, _ = closest_surface(Q, Pd(g), tri)
    return np.linalg.norm(pos - Q, axis=1)


# ═══════════════════════════════════════════════════════ Edge Equalize
sec("Edge Equalize")
x = np.array([0, 0.05, 0.1, 0.5, 0.6, 1.4, 1.5, 2.6, 3.0])
X0 = np.c_[x, np.sin(x * 1.3), 0.2 * x ** 2]
g = polyline(X0)
g.set_edge_group("e", all_edges(g))
seg0 = np.linalg.norm(np.diff(X0, axis=0), axis=1)
check("negative control: input segment lengths are very uneven", seg0.max() / seg0.min() > 10,
      round(seg0.max() / seg0.min(), 1))
o, r = ME.edge_equalize(g, "e", "arc_length")
Q = Pd(o)
d, u = seg_dist(Q, X0.astype(np.float32).astype(float))
L = u.max()
check("arc_length: points stay on the original polyline", d.max() < 1e-6, d.max())
check("arc_length: arc length along the original polyline equal per segment",
      np.abs(np.diff(u) - L / 8).max() < 1e-5, np.abs(np.diff(u) - L / 8).max())
check("endpoints do not move", np.abs(Q[[0, -1]] - X0[[0, -1]]).max() < 1e-6)
o2, _ = ME.edge_equalize(g, "e", "chord")
Q2 = Pd(o2)
ch = np.linalg.norm(np.diff(Q2, axis=0), axis=1)
check("chord: straight-line distance equal per segment", ch.std() / ch.mean() < 1e-6, ch.std() / ch.mean())
d2, _ = seg_dist(Q2, X0.astype(np.float32).astype(float))
check("chord: points also stay on the original polyline", d2.max() < 1e-6, d2.max())
ch_arc = np.linalg.norm(np.diff(Q, axis=0), axis=1)
check("negative control: arc_length chord lengths are unequal (chords are shorter than arcs at bends)",
      ch_arc.std() / ch_arc.mean() > 1e-3, ch_arc.std() / ch_arc.mean())

tb = build.tube(1, 1, 2, cols=16, rows=3)
P0 = Pd(tb)
rng = np.random.default_rng(0)
P0 = P0 + np.c_[np.zeros(len(P0)), np.zeros(len(P0)), np.zeros(len(P0))]
ang = np.arctan2(P0[:, 2], P0[:, 0]) + rng.uniform(-0.15, 0.15, len(P0))
tbj = tb.copy()
tbj.set(POINT, "P", np.c_[np.cos(ang), P0[:, 1], np.sin(ang)].astype(np.float32))
ep = all_edges(tbj)
y = P0[:, 1]
ring = ep[(y[ep[:, 0]] == y.min()) & (y[ep[:, 1]] == y.min())]
tbj.set_edge_group("ring", ring)
loop = _paths(ring.astype(np.int64), tbj.npoints, True)[0][0]
Xl = Pd(tbj)[loop + [loop[0]]]
o, r = ME.edge_equalize(tbj, "ring")
Ql = Pd(o)
dd, uu = seg_dist(Ql[loop], Xl)
_, u_old = seg_dist(Pd(tbj)[loop], Xl)
Lr = np.r_[0, np.cumsum(np.linalg.norm(np.diff(Xl, axis=0), axis=1))][-1]
du = (uu - u_old + Lr / 2) % Lr - Lr / 2
check("closed loop: points stay on the original loop polyline", dd.max() < 1e-6, dd.max())
sp = np.sort(uu)
gaps = np.diff(np.r_[sp, sp[0] + Lr])
check("closed loop: arc length evenly divided (including the last-to-first segment)", np.abs(gaps - Lr / 16).max() < 1e-5,
      np.abs(gaps - Lr / 16).max())
check("closed loop: average displacement around the loop = 0 (phase with least movement)", abs(du.mean()) < 1e-5,
      du.mean())
other = np.setdiff1d(np.arange(tbj.npoints), loop)
check("points not on the chain did not move at all", np.abs(Ql[other] - Pd(tbj)[other]).max() == 0)
# branch: T shape, branch point does not move
T = Geometry.from_mesh(np.array([[0, 0, 0], [0.3, 0.1, 0], [1, 0, 0], [2, 0.2, 0],
                                 [1, 0.2, 0], [1, 1.5, 0]], np.float32),
                       [[0, 1, 2, 3], [2, 4, 5]], closed=False)
T.set_edge_group("e", all_edges(T))
o, r = ME.edge_equalize(T, "e")
check("branch point (degree 3) and endpoints do not move", np.abs(Pd(o)[[0, 2, 3, 5]] -
                                   Pd(T)[[0, 2, 3, 5]]).max() == 0, r)
lp = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [1.5, 0.2, 0.8],
                                  [1.2, 0, 1.6], [0.6, 0.1, 1.4], [-1, 0, 0]],
                                 np.float32), [[0, 1, 2, 3, 4, 0], [0, 5]],
                        closed=False)
lp.set_edge_group("e", all_edges(lp))
o, r = ME.edge_equalize(lp, "e")
Xl2 = Pd(lp)[[0, 1, 2, 3, 4, 0]]
dl, ul = seg_dist(Pd(o)[[1, 2, 3, 4]], Xl2)
Ll = np.r_[0, np.cumsum(np.linalg.norm(np.diff(Xl2, axis=0), axis=1))][-1]
check("loop through a branch point (lollipop): branch point pinned, the rest of the loop evenly divided from it",
      np.abs(Pd(o)[0] - Pd(lp)[0]).max() == 0 and
      np.abs(np.sort(ul) - Ll * np.arange(1, 5) / 5).max() < 1e-5,
      np.sort(ul) - Ll * np.arange(1, 5) / 5)
err("empty Edges raises", lambda: ME.edge_equalize(g, ""), "Edges is empty")

# ═══════════════════════════════════════════════════════ Edge Straighten
sec("Edge Straighten")
o, r = ME.edge_straighten(g, "e", "preserve")
Q = Pd(o)
A_, B_ = X0[0], X0[-1]
dline = np.linalg.norm(np.cross(Q - A_, B_ - A_), axis=1) / np.linalg.norm(B_ - A_)
f = (Q - A_) @ (B_ - A_) / ((B_ - A_) @ (B_ - A_))
s0 = np.r_[0, np.cumsum(seg0)]
check("preserve: points lie on the line between the two ends", dline.max() < 1e-5, dline.max())
check("preserve: position ratio = original arc-length ratio", np.abs(f - s0 / s0[-1]).max() < 1e-6,
      np.abs(f - s0 / s0[-1]).max())
o, _ = ME.edge_straighten(g, "e", "uniform")
f = (Pd(o) - A_) @ (B_ - A_) / ((B_ - A_) @ (B_ - A_))
check("uniform: evenly divided", np.abs(f - np.arange(9) / 8).max() < 1e-6)
o, _ = ME.edge_straighten(g, "e", "project")
f = (Pd(o) - A_) @ (B_ - A_) / ((B_ - A_) @ (B_ - A_))
fp = np.clip((X0 - A_) @ (B_ - A_) / ((B_ - A_) @ (B_ - A_)), 0, 1)
check("project: = original points projected perpendicularly onto the line", np.abs(f - fp).max() < 1e-6)
o, r = ME.edge_straighten(tbj, "ring")
check("closed loops cannot be straightened: skipped, counted in the report, points unmoved",
      r["skipped_loops"] == 1 and np.abs(Pd(o) - Pd(tbj)).max() == 0, r)

# ═══════════════════════════════════════════════════════ Circle from Edges
sec("Circle from Edges")
wob = tbj.copy()
Pw = Pd(tbj).copy()
Pw[loop] += rng.normal(0, 0.08, (len(loop), 3))
wob.set(POINT, "P", Pw.astype(np.float32))
o, r = ME.circle_from_edges(wob, "ring")
Q = Pd(o)[loop]
c0 = Pw[loop].mean(0)
R0 = r["radii"][0]
nrm = newell(Q)
nrm /= np.linalg.norm(nrm)
check("distance to the center (mean of the original loop points) all = R",
      np.abs(np.linalg.norm(Q - c0, axis=1) - R0).max() < 1e-5)
rin = np.linalg.norm((Pw[loop] - c0) - np.outer((Pw[loop] - c0) @ nrm, nrm),
                     axis=1)
check("R = mean of the original distances to the center (projected into the plane)", abs(R0 - rin.mean()) < 1e-5,
      (R0, rin.mean()))
check("coplanar", np.abs((Q - c0) @ nrm).max() < 1e-5)
check("winding unchanged (Newell normal same direction)", newell(Pw[loop]) @ nrm > 0)
u_ = Q[0] - c0
u_ /= np.linalg.norm(u_)
v_ = np.cross(nrm, u_)
th = np.unwrap(np.arctan2((Q - c0) @ v_, (Q - c0) @ u_))
check("equal angular spacing", np.abs(np.diff(th) - 2 * np.pi / 16).max() < 1e-5,
      np.abs(np.diff(th) - 2 * np.pi / 16).max())
Qp = Pw[loop] - c0
th0 = np.arctan2(Qp @ v_, Qp @ u_)
th1 = np.arctan2((Q - c0) @ v_, (Q - c0) @ u_)


def moved(dphi):
    t_ = th1 + dphi
    Y = c0 + R0 * (np.cos(t_)[:, None] * u_ + np.sin(t_)[:, None] * v_)
    return float(((Y - Pw[loop]) ** 2).sum())


check("phase: rotating the whole loop by +-0.01 rad increases the sum of squared displacement (the minimum was taken)",
      moved(0.01) > moved(0) and moved(-0.01) > moved(0),
      (moved(-0.01), moved(0), moved(0.01)))
h_ = 1e-3
off_ = -(moved(h_) - moved(-h_)) / (2 * h_) / \
    ((moved(h_) - 2 * moved(0) + moved(-h_)) / h_ ** 2)
check("  and it is the exact minimum (optimal offset estimated by parabola < 1e-6 rad)", abs(off_) < 1e-6,
      off_)
o, r = ME.circle_from_edges(wob, "ring", even_spacing=False)
Q = Pd(o)[loop]
th2 = np.arctan2((Q - c0) @ v_, (Q - c0) @ u_)
check("even_spacing off: each point keeps its own azimuth", np.abs(
    (th2 - th0 + np.pi) % (2 * np.pi) - np.pi).max() < 1e-5)
rr = np.linalg.norm(Pw[loop] - c0 - np.outer((Pw[loop] - c0) @ nrm, nrm), axis=1)
for mode, want in (("min", rr.min()), ("max", rr.max()), ("custom", 2.5)):
    o, r = ME.circle_from_edges(wob, "ring", mode, 2.5)
    got = np.linalg.norm(Pd(o)[loop] - c0, axis=1)
    check(f"radius {mode}", np.abs(got - want).max() < 1e-5, (got.mean(), want))
o, r = ME.circle_from_edges(wob, "ring", rotate=90)
Q = Pd(o)[loop]
th3 = np.arctan2((Q - c0) @ v_, (Q - c0) @ u_)
check("Rotate 90 deg: the whole thing rotates another 90 deg",
      np.abs((th3 - th1 - np.pi / 2 + np.pi) % (2 * np.pi) - np.pi).max() < 1e-5)
o, r = ME.circle_from_edges(g, "e")
check("open chains skipped", r["skipped_open"] == 1 and np.abs(Pd(o) - Pd(g)).max() == 0)

# ═══════════════════════════════════════════════════════ Edge Flip
sec("Edge Flip")
sq = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]],
                                 np.float32), [[0, 1, 2], [0, 2, 3]])
sq.set(VERTEX, "uv", Pd(sq)[sq.vertex_point][:, [0, 2]].astype(np.float32))
sq.set_edge_group("d", np.array([[0, 2]]))
o, r = ME.edge_flip(sq, "d")
tp = topology(o)
has13 = any(set(e) == {1, 3} for e in tp.edge_points.tolist())
has02 = any(set(e) == {0, 2} for e in tp.edge_points.tolist())
check("two triangles: diagonal 0-2 replaced by 1-3", r["flipped"] == 1 and has13 and not has02, r)
Po = Pd(o)
nn = [newell(Po[o.prim_points(i)]) for i in range(2)]
check("after flipping both prim normals still point the same way (those facing +y still face up)", all(n[1] < 0 for n in nn) ==
      all(newell(Pd(sq)[sq.prim_points(i)])[1] < 0 for i in range(2)) and
      nn[0] @ nn[1] > 0)
check("the old edge in the edge group is replaced by the new edge", {tuple(sorted(e)) for e in
                         o.get_edge_group("d").tolist()} == {(1, 3)})
sqf = sq.copy()
sqf.set(VERTEX, "fid", sqf.vertex_prim().astype(np.int32)[:, None])
of_, _ = ME.edge_flip(sqf, "d")
fid = of_.get(VERTEX, "fid")[:, 0]
check("new prims take corners from their own original prim where possible (each new prim has only 1 corner from the other prim)",
      all(int((fid[of_.prim_offset[i]:of_.prim_offset[i + 1]] != i).sum()) == 1
          for i in range(2)), fid.tolist())
uvo = o.get(VERTEX, "uv")
check("uv follows the corners (each corner's uv = its point's xz)",
      np.abs(uvo - Po[o.vertex_point][:, [0, 2]]).max() < 1e-7)
q2 = build.grid(2, 1, 3, 2)
q2.set_edge_group("m", np.array([[1, 4]]))
Pq = Pd(q2)
mid = [e for e in all_edges(q2).tolist()
       if abs(Pq[e[0], 0]) < 1e-6 and abs(Pq[e[1], 0]) < 1e-6]
q2.set_edge_group("m", np.array(mid))
o, r = ME.edge_flip(q2, "m")
area0 = sum(tri_area(Pq, q2.prim_points(i)) for i in range(2))
area1 = sum(tri_area(Pd(o), o.prim_points(i)) for i in range(2))
check("two quads: after rotating one step they are still two quads, total area unchanged",
      r["flipped"] == 1 and list(o.prim_sizes()) == [4, 4] and
      abs(area0 - area1) < 1e-6, (list(o.prim_sizes()), area0, area1))
e_new = tuple(o.get_edge_group("m")[0])
check("quad edge rotation: the new edge is a diagonal (ends have different x)",
      abs(Pd(o)[e_new[0], 0] - Pd(o)[e_new[1], 0]) > 0.5, e_new)
o2, _ = ME.edge_flip(q2, "m", cycles=-1)
check("Cycles = -1 rotates to the other diagonal", tuple(o2.get_edge_group("m")[0]) != e_new)
o3, r3 = ME.edge_flip(q2, "m", cycles=6)
check("Cycles = loop length (6) is the same as no rotation: skipped", r3["flipped"] == 0 and
      np.array_equal(o3.vertex_point, q2.vertex_point))
tet = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
                                  np.float32),
                         [[0, 2, 1], [0, 1, 3], [1, 2, 3], [0, 3, 2]])
o, r = ME.edge_flip(tet, "")
check("tetrahedron: flipping any edge would create an existing edge -- all skipped", r["flipped"] == 0 and
      r["skipped"] == 6, r)
# delaunay

def viol(gg):
    P = Pd(gg)
    t = topology(gg)
    bad = 0
    for e in np.nonzero(t.edge_count == 2)[0]:
        a, b = t.edge_points[e]
        s_ = 0
        for h in t.edge_he[t.edge_he_off[e]:t.edge_he_off[e + 1]]:
            pr = gg.vertex_prim()[h]
            c = [p for p in gg.prim_points(pr) if p not in (a, b)][0]
            u, v = P[a] - P[c], P[b] - P[c]
            s_ += math.acos(np.clip(u @ v / np.linalg.norm(u) / np.linalg.norm(v),
                                    -1, 1))
        bad += s_ > math.pi + 1e-7
    return bad


pts2 = rng.uniform(-1, 1, (40, 2))
P40 = np.c_[pts2[:, 0], np.zeros(40), pts2[:, 1]]
order = np.argsort(P40[:, 0])
# strip triangulation (a "zigzag" sorted by x) -- very thin, many Delaunay violations
Ps = P40[order]
strip = []
for i in range(38):
    a, b, c = i, i + 1, i + 2
    if np.cross(Ps[b] - Ps[a], Ps[c] - Ps[a])[1] < 0:
        strip.append([a, b, c])
    else:
        strip.append([a, c, b])
sg = Geometry.from_mesh(Ps.astype(np.float32), strip)
v0 = viol(sg)
check("negative control: zigzag strip triangulation has many edges violating Delaunay", v0 > 5, v0)
o, r = ME.edge_flip(sg, "", "delaunay")
check("after delaunay flipping: every interior edge's opposite angle sum <= 180 deg", viol(o) == 0,
      (viol(o), r))
a0 = sum(tri_area(Ps, sg.prim_points(i)) for i in range(sg.nprims))
a1 = sum(tri_area(Pd(o), o.prim_points(i)) for i in range(o.nprims))
check("total area unchanged after flipping (no folds created)", abs(a0 - a1) < 1e-5, (a0, a1))
check("after flipping all normals face the same side", all(newell(Pd(o)[o.prim_points(i)])[1] *
                          newell(Ps[sg.prim_points(0)])[1] > 0
                          for i in range(o.nprims)))
s60 = math.sin(math.radians(60))
fold = Geometry.from_mesh(np.array([[0, 0, 0], [2, 0, 0], [1, 0, 0.3],
                                    [1, 0.3 * s60, -0.15]], np.float32),
                          [[0, 2, 1], [1, 3, 0]])
check("  (this pair of triangles folded by 60 deg has opposite angle sum > 180 deg)",
      ME._angle(Pd(fold), 2, 0, 1) + ME._angle(Pd(fold), 3, 0, 1) > math.pi)
o, r = ME.edge_flip(fold, "", "delaunay", max_angle=10)
check("dihedral angle over Max Angle is not flipped (would change the shape)", r["flipped"] == 0, r)
o, r = ME.edge_flip(fold, "", "delaunay", max_angle=90)
check("  with Max Angle relaxed to 90 deg it flips", r["flipped"] == 1, r)

# ═══════════════════════════════════════════════════════ Tri Divide
sec("Tri Divide")
pl = Geometry.from_mesh(np.array([[0, 0, 0], [3, 0, 0], [0.4, 0, 1.0]],
                                 np.float32), [[0, 2, 1]])
pl.set(POINT, "Cd", Pd(pl).astype(np.float32))
pl.set(VERTEX, "uv", Pd(pl)[pl.vertex_point][:, [0, 2]].astype(np.float32))


def min_angle(P, F):
    m = 180.0
    for f in F:
        for k in range(3):
            a, b, c = P[f[k]], P[f[(k + 1) % 3]], P[f[(k + 2) % 3]]
            u, v = b - a, c - a
            m = min(m, math.degrees(math.acos(np.clip(
                u @ v / np.linalg.norm(u) / np.linalg.norm(v), -1, 1))))
    return m


o, r = ME.tri_divide(pl, "", max_edge_length=0.3, delaunay=False)
P = Pd(o)
F = [o.prim_points(i) for i in range(o.nprims)]
Lmax = max(np.linalg.norm(P[f[k]] - P[f[(k + 1) % 3]]) for f in F
           for k in range(3))
check("longest edge <= 0.3", Lmax <= 0.3 + 1e-6, (Lmax, r))
t = topology(o)
check("conforming: interior edges all have two prims, boundary is only segments of the original three edges",
      set(np.unique(t.edge_count)) <= {1, 2} and
      np.isclose(np.linalg.norm(P[t.edge_points[t.boundary][:, 0]] -
                                P[t.edge_points[t.boundary][:, 1]], axis=1).sum(),
                 3 + np.linalg.norm([2.6, 0, -1]) + np.linalg.norm([0.4, 0, 1])),
      np.bincount(t.edge_count))
check("area unchanged", abs(sum(tri_area(P, f) for f in F) - tri_area(Pd(pl), [0, 2, 1]))
      < 1e-5)
ma0 = min_angle(Pd(pl), [[0, 2, 1]])
ma1 = min_angle(P, F)
check("minimum angle not below half the original (Rivara)", ma1 >= ma0 / 2 - 1e-6,
      (round(ma0, 2), round(ma1, 2)))
check("point attribute Cd = P linear: new points interpolated exactly", np.abs(o.get(POINT, "Cd") - P).max()
      < 1e-6)
check("vertex uv = P.xz interpolated exactly", np.abs(o.get(VERTEX, "uv") -
                                     P[o.vertex_point][:, [0, 2]]).max() < 1e-6)
plg = pl.copy()
plg.set_group(POINT, "ab", np.array([True, True, False]))
og, _ = ME.tri_divide(plg, "", max_edge_length=1.0, delaunay=False)
Pg = Pd(og)
grp = og.get_group(POINT, "ab")
on01 = np.abs(Pg[:, 2]) < 1e-9                     # on the edge between points 0 and 1 (z = 0)
check("point group: new points on edges with both ends in the group are in the group, other new points are not",
      bool(grp[on01].all()) and not grp[~on01].any(), (on01.sum(), grp.sum()))
o, r = ME.tri_divide(pl, "", max_area=0.02)
P = Pd(o)
check("area limit: every triangle <= Max Area", max(tri_area(P, o.prim_points(i))
                                     for i in range(o.nprims)) <= 0.02 + 1e-7)
sph = build.sphere(1, 12, 8)
o, r = ME.tri_divide(sph, "", max_edge_length=0.2)
check("sphere: new points all lie on the original mesh surface (shape unchanged)",
      dist_to_mesh(Pd(o), sph).max() < 1e-6, r)
t = topology(o)
check("sphere is still closed after subdivision (no boundary edges, no T-junctions)", not t.boundary.any())
# select a part: unselected quads next to it get midpoints inserted
gr = build.grid(2, 2, 3, 3)
gr.set_group(PRIM, "L", np.array([True, False, True, False]))
o, r = ME.tri_divide(gr, "L", max_edge_length=0.3)
t = topology(o)
Po = Pd(o)
bl = np.linalg.norm(Po[t.edge_points[t.boundary][:, 0]] -
                    Po[t.edge_points[t.boundary][:, 1]], axis=1).sum()
check("partial subdivision: unselected prims got midpoints, only the outer contour is boundary (perimeter 8)",
      abs(bl - 8) < 1e-6 and set(np.unique(t.edge_count)) <= {1, 2}, bl)
unsel = [i for i in range(o.nprims) if o.prim_sizes()[i] > 3]
check("the two unselected quads are still there (more corners, not cut into triangles)", len(unsel) == 2,
      [int(o.prim_sizes()[i]) for i in unsel])
rng = np.random.default_rng(11)
Pr = np.c_[rng.uniform(0, 1, 30), np.zeros(30), rng.uniform(0, 1, 30)]
strip2 = []
o_ = np.argsort(Pr[:, 0])
Pr = Pr[o_]
for i in range(28):
    a, b, c = i, i + 1, i + 2
    strip2.append([a, b, c] if np.cross(Pr[b] - Pr[a], Pr[c] - Pr[a])[1] < 0
                  else [a, c, b])
sg2 = Geometry.from_mesh(Pr.astype(np.float32), strip2)
o1, _ = ME.tri_divide(sg2, "", max_edge_length=0.4, delaunay=False)
o2, r2 = ME.tri_divide(sg2, "", max_edge_length=0.4, delaunay=True)
check("negative control: without delaunay there are violations", viol(o1) > 0, viol(o1))
check("Delaunay on: no violations on a plane after flipping", viol(o2) == 0, (viol(o2), r2))

# ═══════════════════════════════════════════════════════ Unsubdivide
sec("Unsubdivide")
cases = {
    "box": build.box((1, 2, 3), divisions=(3, 2, 2)),
    "grid": build.grid(4, 3, 5, 4),
    "torus": build.torus(1, 0.3, 6, 8),
    "triangle+pentagon": Geometry.from_mesh(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [2, 0.5, 0.3], [0.5, 2, 0.2],
         [-0.6, 1.5, 0.1]], [[0, 1, 2, 3], [1, 4, 2], [3, 2, 4, 5, 6]]),
}
rng = np.random.default_rng(1)
for nm, cg in cases.items():
    cg = cg.copy()
    cg.set(POINT, "P", (Pd(cg) + rng.normal(0, 0.05, (cg.npoints, 3)))
           .astype(np.float32))
    cg.set(VERTEX, "uv", rng.uniform(0, 1, (cg.nvertices, 2)).astype(np.float32))
    cg.set(PRIM, "id", np.arange(cg.nprims, dtype=np.int32) * 7)
    cg.set(POINT, "Cd", rng.uniform(0, 1, (cg.npoints, 3)).astype(np.float32))
    for lv in (1, 2):
        fg_ = SD.subdivide(cg, lv)
        o, r = US.unsubdivide(fg_, lv)
        same = (o.npoints == cg.npoints and np.array_equal(o.vertex_point,
                                                           cg.vertex_point)
                and np.array_equal(o.prim_offset, cg.prim_offset))
        e = np.abs(Pd(o) - Pd(cg)).max() if same else -1
        ec = np.abs(o.get(POINT, "Cd") - cg.get(POINT, "Cd")).max() \
            if same else -1
        check(f"{nm} subdivided {lv} levels and back: point numbers / prims / starting corner identical, P, Cd to float32",
              same and e < 2e-6 and ec < 2e-6, (e, ec, r.get("cg_iterations")))
        if lv == 1:
            check(f"  {nm}: uv, prim attributes restored",
                  same and np.abs(o.get(VERTEX, "uv") - cg.get(VERTEX, "uv"))
                  .max() < 1e-6 and np.array_equal(o.get(PRIM, "id"),
                                                    cg.get(PRIM, "id")))
bx = build.box((1, 1, 1), divisions=(2, 2, 2))
f1 = SD.subdivide(bx, 1)
o, r = US.unsubdivide(f1, 1)
check("cube subdivided once: back to 8 points 6 quads (not the 6-point 8-triangle octahedron)",
      o.npoints == 8 and list(o.prim_sizes()) == [4] * 6, r)
o, r = US.unsubdivide(f1, 1, "keep")
ek = np.abs(Pd(o) - Pd(bx)).max()
check("negative control: keep mode keeps the subdivided positions of the original vertices -- corners get worn in", ek > 0.05, ek)
of, _ = US.unsubdivide(f1, 1, "fit")
check("fit mode cube corners return to +-0.5", np.abs(np.abs(Pd(of)) - 0.5).max() < 1e-6)
# a sculpted fine mesh: fit is the least-squares optimum (perturbing it increases the residual)
sc = f1.copy()
sc.set(POINT, "P", (Pd(f1) + rng.normal(0, 0.03, (f1.npoints, 3))).astype(np.float32))
o, r = US.unsubdivide(sc, 1)
base = r["fit_rms"]


def rms_of(Pc):
    tmp = o.copy()
    tmp.set(POINT, "P", Pc.astype(np.float64))
    re = SD.subdivide(tmp, 1)
    return float(np.sqrt(np.mean((Pd(re) - Pd(sc)) ** 2)))


check("residual between subdivided-back and the sculpted mesh = fit_rms in the report",
      abs(rms_of(Pd(o)) - base) < 1e-6, (rms_of(Pd(o)), base))
worse = all(rms_of(Pd(o) + d) > base for d in
            (rng.normal(0, 0.01, (8, 3)) for _ in range(5)))
check("perturbing the coarse mesh points at random always increases the residual (least-squares optimum)", worse)
err("a 3x3 quad grid (odd cell count) is not from subdivision: raises",
    lambda: US.unsubdivide(build.grid(3, 3, 4, 4)), "")
err("has triangles: raises", lambda: US.unsubdivide(sph), "all quads")
g_eo = SD.subdivide(cases["grid"], 1, boundary="edge_only")
o_ok, r_ok = US.unsubdivide(g_eo, 1, boundary="edge_only")
o_bad, r_bad = US.unsubdivide(g_eo, 1, boundary="edge_corner")
check("matching boundary rule (edge_only) restores exactly; a mismatch has a clear residual",
      np.abs(Pd(o_ok) - Pd(cases["grid"])).max() < 1e-5 and
      r_bad["fit_rms"] > 100 * max(r_ok["fit_rms"], 1e-9),
      (r_ok["fit_rms"], r_bad["fit_rms"]))

# ═══════════════════════════════════════════════════════ Rewire Vertices
sec("Rewire Vertices")
two = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1],
                                   [1, 0, 0], [2, 0, 0], [2, 0, 1], [1, 0, 1]],
                                  np.float32), [[0, 3, 2, 1], [4, 7, 6, 5]])
rw = np.full(8, -1, np.int32)
rw[4], rw[7] = 1, 2                                  # rewire the two right-hand points to the left
two.set(VERTEX, "rewire_to", rw[two.vertex_point][:, None])
o, r = ME.rewire_vertices(two, "rewire_to", keep_unused_points=False)
t = topology(o)
check("two separate quads rewired to share one edge", (t.edge_count == 2).sum() == 1 and
      o.npoints == 6, (o.npoints, r))
check("report: 2 rewired, the 6 with -1 untouched", r["rewired"] == 2 and r["ignored"] == 6)
two_p = two.copy()
two_p.attribs[VERTEX].pop("rewire_to")
two_p.set(POINT, "to", rw[:, None])
o2, r2 = ME.rewire_vertices(two_p, "to")
check("point-class attributes work too (each vertex takes its point's value)", r2["attribute_class"] ==
      "point" and (topology(o2).edge_count == 2).sum() == 1 and o2.npoints == 8)
tri = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [0, 0, 1]], np.float32),
                         [[0, 1, 2]])
tri.set(VERTEX, "rw", np.array([[-1], [0], [-1]], np.int32))
o3, r3 = ME.rewire_vertices(tri, "rw", remove_degenerate=True)
check("rewired into a degenerate prim (two corners on the same point): removed", o3.nprims == 0 and
      r3["removed_prims"] == 1, r3)
o4, _ = ME.rewire_vertices(tri, "rw", remove_degenerate=False)
check("without removing degenerates: prim stays (two corners on the same point)", o4.nprims == 1 and
      list(o4.vertex_point) == [0, 0, 2])
tri.set(VERTEX, "far", np.array([[99], [-1], [5]], np.int32))
o5, r5 = ME.rewire_vertices(tri, "far")
check("out-of-range point numbers are also left alone (counted in ignored)", list(o5.vertex_point) == [0, 1, 2] and
      r5["ignored"] == 3, r5)
qd = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]],
                                 np.float32), [[0, 1, 2, 3]])
qd.set(VERTEX, "rw", np.array([[-1], [-1], [-1], [0]], np.int32))
o6, r6 = ME.rewire_vertices(qd, "rw", remove_degenerate=True)
check("first and last corners wired to the same point (wrap-around duplicate) also removed: quad becomes triangle",
      o6.nprims == 1 and list(o6.vertex_point) == [0, 1, 2], list(o6.vertex_point))
err("attribute does not exist: raises", lambda: ME.rewire_vertices(tri, "nope"), "No integer attribute")

# ═══════════════════════════════════════════════════════ PolyCut
sec("PolyCut")
cir = build.circle((1, 1), divisions=24) if "divisions" in \
    build.circle.__code__.co_varnames else build.circle()
Pc = Pd(cir)
axis = int(np.argmax(np.ptp(Pc, axis=0)[[1, 2]])) + 1
cir.set(POINT, "h", (Pc[:, axis] + 0.13).astype(np.float32)[:, None])
o, r = ME.poly_cut(cir, "", "threshold", "", "h", 0.0, "above")
P = Pd(o)
h = o.get(POINT, "h")[:, 0]
used = np.unique(o.vertex_point)
check("above: kept points all above the threshold (or exactly on it)", (h[used] >= -1e-6).all() and
      r["polylines"] == 1, r)
newp = np.arange(cir.npoints, o.npoints)
check("inserted points' attribute is exactly = threshold (linear interpolation)", len(newp) == 2 and
      np.abs(h[newp]).max() < 1e-6)
Xc = np.vstack([Pc[cir.prim_points(0)], Pc[cir.prim_points(0)[:1]]])
check("inserted points lie on the original circle polyline", seg_dist(P[newp], Xc)[0].max() < 1e-6)
check("output is open polylines", not o.prim_closed.any())
o_b, r_b = ME.poly_cut(cir, "", "threshold", "", "h", 0.0, "below")
hb = o_b.get(POINT, "h")[:, 0]
check("below: kept points all below the threshold", (hb[np.unique(o_b.vertex_point)] <= 1e-6).all())
o_a, r_a = ME.poly_cut(cir, "", "threshold", "", "h", 0.0, "all")
check("all: breaks only where the threshold is crossed -- two pieces, point count = original + 2 (inserted) + shared",
      r_a["polylines"] == 2 and
      o_a.nvertices == cir.nvertices + 2 * 2, (r_a, o_a.nvertices))
qq = build.grid(2, 2, 2, 3)
qq.set(POINT, "h", Pd(qq)[:, 2:3].astype(np.float32) * 0 +
       Pd(qq)[:, 0:1].astype(np.float32))
o, r = ME.poly_cut(qq, "", "threshold", "", "h", 0.25, "all")
check("an edge shared by two adjacent prims gets only one inserted point (same point number): 3 horizontal edges 3 points",
      r["inserted_points"] == 3 and o.npoints == qq.npoints + 3, r)
sqc = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1],
                                   [0.5, 0, 1.5]], np.float32),
                         [[0, 1, 2, 4, 3]])
sqc.set_group(POINT, "c", np.array([True, False, True, False, False]))
o, r = ME.poly_cut(sqc, "", "cut_points", "c")
pl_ = sorted(list(o.prim_points(i)) for i in range(o.nprims))
check("cut_points: closed prim broken into two pieces at 0 and 2", pl_ == [[0, 1, 2], [2, 4, 3, 0]],
      pl_)
sqc.set_group(POINT, "k", np.array([False, True, True, False, True]))
o, r = ME.poly_cut(sqc, "", "keep_points", "k")
check("keep_points: keep only edges with both ends in the group", [list(o.prim_points(i))
                                    for i in range(o.nprims)] == [[1, 2, 4]])
op = polyline(np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [3, 0, 0]]))
op.set_group(POINT, "c", np.array([False, True, False, False]))
o, r = ME.poly_cut(op, "", "cut_points", "c")
check("open polyline breaks at interior points", [list(o.prim_points(i)) for i in range(o.nprims)]
      == [[0, 1], [1, 2, 3]])
sqc.set_group(POINT, "none", np.zeros(5, bool))
o, r = ME.poly_cut(sqc, "", "cut_points", "none")
check("a closed prim with no cut stays as is (still a polygon)", o.nprims == 1 and o.prim_closed[0] and
      list(o.prim_points(0)) == list(sqc.prim_points(0)))
sqc.set(VERTEX, "uv", Pd(sqc)[sqc.vertex_point][:, [0, 2]].astype(np.float32))
sqc.set(POINT, "h2", Pd(sqc)[:, 0:1].astype(np.float32))
o, r = ME.poly_cut(sqc, "", "threshold", "", "h2", 0.3, "all")
check("vertex uv at inserted points interpolated along the edge", np.abs(o.get(VERTEX, "uv") -
                                    Pd(o)[o.vertex_point][:, [0, 2]]).max()
      < 1e-6)
err("cut_points without a point group: raises", lambda: ME.poly_cut(sqc, "", "cut_points", ""),
    "Points is empty")

# ═══════════════════════════════════════════════════════ PolyStitch
sec("PolyStitch")
a = build.grid(2, 2, 4, 4, center=(0, 0, 0))
b = build.grid(2, 2, 7, 7, center=(2.0004, 0, 0))
m = ops.merge(a, b)
m.set(VERTEX, "uv", Pd(m)[m.vertex_point][:, [0, 2]].astype(np.float32))
t0 = topology(m)
o, r = ME.poly_stitch(m, "", 0.01)
t = topology(o)
P = Pd(o)
bpts = np.unique(t.edge_points[t.boundary])
check("negative control: before stitching both pieces have their own boundary (36 edges)", int(t0.boundary.sum()) == 36)
check("after stitching: only the outer contour is boundary (3x3 + 6x3 = 27 edges)", int(t.boundary.sum()) == 27, r)
check("interior edges have exactly two prims (manifold)", set(np.unique(t.edge_count)) <= {1, 2})
seam = np.nonzero(np.abs(P[:, 0] - 1.0) < 0.01)[0]
check("seam points all on one straight line (same x)", np.ptp(P[seam, 0]) < 1e-6,
      np.ptp(P[seam, 0]))
check("7 seam points, all shared by both sides", len(seam) == 7 and
      all(len(t.prims_of_point(p)) >= 2 for p in seam
          if abs(abs(P[p, 2]) - 1) > 1e-6))
wz = [p for p in seam if min(abs(P[p, 2] - z) for z in (-1, -1 / 3, 1 / 3, 1))
      < 1e-6]
check("coincident points from both sides welded into one, position averaged (x = 1.0002)", len(wz) == 4 and
      np.abs(P[wz, 0] - 1.0002).max() < 1e-6, P[wz, 0] if wz else wz)
o_n, r_n = ME.poly_stitch(m, "", 0.0001)
check("negative control: tolerance smaller than the gap, nothing done", r_n["welded_points"] == 0 and
      r_n["inserted_corners"] == 0 and topology(o_n).boundary.sum() == 36, r_n)
a2 = build.grid(2, 2, 4, 4, center=(0, 0, 0))
b2 = build.grid(2, 2, 7, 7, center=(2, 0, 0))
m2 = ops.merge(a2, b2)
m2.set(VERTEX, "uv", Pd(m2)[m2.vertex_point][:, [0, 2]].astype(np.float32))
o2, r2 = ME.poly_stitch(m2, "", 1e-4)
check("exactly touching (gap = 0): uv of inserted corners interpolated along the edge (= its point's xz)",
      np.abs(o2.get(VERTEX, "uv") - Pd(o2)[o2.vertex_point][:, [0, 2]]).max()
      < 1e-6 and r2["inserted_corners"] == 3, r2)
o0, r0 = ME.poly_stitch(m2, "", 0.0)
check("Tolerance = 0: only inserts points landing exactly mid-edge (coincident endpoints not inserted)",
      r0["inserted_corners"] == 3 and r0["welded_points"] == 0, r0)
a3 = build.grid(2, 2, 3, 3, center=(0, 0, 0))
m3 = ops.merge(a3, b2)
o4, r4 = ME.poly_stitch(m3, "", 1e-4)
t4 = topology(o4)
check("two points inserted on one edge (coarse 2 segments vs fine 6): order correct, manifold after stitching, only outer contour left",
      r4["inserted_corners"] == 4 and int(t4.boundary.sum()) == 2 * 3 + 6 * 3
      and set(np.unique(t4.edge_count)) <= {1, 2}, (r4, int(t4.boundary.sum())))
o3, r3 = ME.poly_stitch(m, "", 0.01, snap=False)
check("snap off: points do not move (seam sides still 0.0004 apart), but are still inserted, none missed",
      r3["snapped_points"] == 0 and topology(o3).boundary.sum() == 27, r3)

# ═══════════════════════════════════════════════════════ Voronoi Split
sec("Voronoi Split")
sph = build.sphere(1, 24, 16)
sph.set(POINT, "Cd", Pd(sph).astype(np.float32))
sph.set(VERTEX, "uv", Pd(sph)[sph.vertex_point][:, [0, 1]].astype(np.float32))
rng = np.random.default_rng(3)
S = rng.normal(size=(12, 3))
S /= np.linalg.norm(S, axis=1)[:, None]
sites = Geometry.from_points(S)
o, r = VS.voronoi_split(sph, sites, split_points=False, cut_group="cut")
P = Pd(o)
cell = o.get(PRIM, "cell")[:, 0]
D = ((P[:, None, :] - S[None]) ** 2).sum(-1)
worst = 0.0
for i in range(o.nprims):
    pts = o.prim_points(i)
    worst = max(worst, float((D[pts, cell[i]] - D[pts].min(1)).max()))
check("every point of every prim is closest to its own cell point (tolerance 1e-5)", worst < 1e-5, worst)
newp = np.arange(sph.npoints, o.npoints)
Ds = np.sort(D[newp], axis=1)
check("cut points are equidistant to the two nearest cell points", np.abs(Ds[:, 1] - Ds[:, 0]).max() < 1e-5,
      np.abs(Ds[:, 1] - Ds[:, 0]).max())
area = sum(tri_area(P, o.prim_points(i)) for i in range(o.nprims))
area0 = sum(tri_area(Pd(sph), sph.prim_points(i)) for i in range(sph.nprims))
check("area unchanged", abs(area - area0) < 1e-5, (area, area0))
check("new points all lie on the original sphere mesh", dist_to_mesh(P[newp], sph).max() < 1e-6)
check("shared-point mode: sphere still closed after cutting", not topology(o).boundary.any(), r)
check("all 12 cells used", r["cells_used"] == 12)
check("linear point attribute Cd = P interpolated exactly", np.abs(o.get(POINT, "Cd") - P).max() < 1e-6)
check("vertex uv interpolated exactly", np.abs(o.get(VERTEX, "uv") -
                               P[o.vertex_point][:, [0, 1]]).max() < 1e-6)
cut = o.get_edge_group("cut")
Dc = np.sort(D[cut.reshape(-1)], axis=1)
check("cut edge group: both ends on the bisector plane", len(cut) > 0 and
      np.abs(Dc[:, 1] - Dc[:, 0]).max() < 1e-5)
Dsph = ((Pd(sph)[:, None, :] - S[None]) ** 2).sum(-1).argmin(1)
exp_whole = sum(1 for i in range(sph.nprims)
                if len(set(Dsph[sph.prim_points(i)].tolist())) == 1)
whole = r["whole_prims"]
check("number of prims entirely inside one cell matches (computed independently)", whole == exp_whole,
      (whole, exp_whole))
same_faces = sum(1 for i in range(o.nprims) if
                 any(np.array_equal(o.prim_points(i), sph.prim_points(j))
                     for j in range(sph.nprims)))
check("prims entirely inside one cell kept as is (same point numbers)", same_faces >= whole, (same_faces,
                                                          whole))
check("cut quads reassembled into polygons (fragment count > number of output cut prims)",
      o.nprims - whole < r["fragments"], (o.nprims - whole, r["fragments"]))
o2, r2 = VS.voronoi_split(sph, sites, split_points=True)
from comfyui_pcg.geo.topology import connectivity  # noqa: E402
cls_ = connectivity(o2, PRIM, "piece")
ncomp = len(np.unique(cls_.get(PRIM, "piece")))
check("split-point mode: connected pieces = cell count (pieces really separated)", ncomp == 12, ncomp)
names = o2.get(PRIM, "name")
check("name attribute = piece<k>", all(names[i, 0] == f"piece{o2.get(PRIM, 'cell')[i, 0]}"
                                  for i in range(o2.nprims)))
gp = build.grid(2, 2, 5, 5)
site2 = Geometry.from_points(np.array([[-0.37, 0, 0.1], [0.53, 0, -0.2]]))
o3, r3 = VS.voronoi_split(gp, site2, split_points=False)
Pp = Pd(o3)
mid = (np.array([-0.37, 0, 0.1]) + np.array([0.53, 0, -0.2])) / 2
nrm = np.array([0.53 + 0.37, 0, -0.3])
onp = np.abs((Pp[gp.npoints:] - mid) @ nrm) / np.linalg.norm(nrm)
check("plane + two cell points: the cut lies exactly on the bisector", len(onp) > 0 and onp.max() < 1e-6,
      (len(onp), onp.max() if len(onp) else None))
big = Geometry.from_mesh(np.array([[0, 0, 0], [10, 0, 0], [5, 0, 9]],
                                  np.float32), [[0, 2, 1]])
s4 = Geometry.from_points(np.array([[0, 0, 0], [10, 0, 0], [5, 0, 9],
                                    [5, 0, 3.2]]))
o7, r7 = VS.voronoi_split(big, s4, split_points=False)
c7 = o7.get(PRIM, "cell")[:, 0]
a7 = sum(tri_area(Pd(o7), o7.prim_points(i)) for i in range(o7.nprims))
check("a cell lying entirely inside a triangle (owning no vertex) is still cut out",
      3 in c7.tolist() and abs(a7 - 45.0) < 1e-4 and r7["cells_used"] == 4,
      (c7.tolist(), a7))
val = Geometry.from_mesh(np.array([[-1, -1, 1], [-1, 1, 1], [0, 1, 0], [0, -1, 0],
                                   [1, 1, 1], [1, -1, 1]], np.float32),
                         [[0, 3, 2, 1], [3, 5, 4, 2]])
s3 = np.array([[0, 1.3, 0.5], [0, -0.2, 0.5 + 0.75 ** 0.5],
               [0, -0.2, 0.5 - 0.75 ** 0.5]])
o8, r8 = VS.voronoi_split(val, Geometry.from_points(s3), split_points=False)
P8 = Pd(o8)
hit = [np.linalg.norm(P8 - q, axis=1).min() for q in ([0.5, 0.3, 0.5],
                                                       [-0.5, 0.3, 0.5])]
check("V-shaped valley: the three cells' equidistant lines cross two walls -- the two intersections are separate (not shared)",
      max(hit) < 1e-5, hit)
err("no cell points: raises", lambda: VS.voronoi_split(sph, Geometry()), "has no points")

# ═══════════════════════════════════════════════════════ Nodes
sec("Nodes")
NEW = {"PCG_EdgeEqualize": "PCG/modify", "PCG_EdgeStraighten": "PCG/modify",
       "PCG_CircleFromEdges": "PCG/modify", "PCG_EdgeFlip": "PCG/topology",
       "PCG_TriDivide": "PCG/topology", "PCG_Unsubdivide": "PCG/topology",
       "PCG_RewireVertices": "PCG/topology", "PCG_PolyCut": "PCG/topology",
       "PCG_PolyStitch": "PCG/topology", "PCG_VoronoiSplit": "PCG/modify"}
check("all 10 nodes registered, correct category",
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
for k, kw in {"PCG_EdgeEqualize": dict(geo=tbj, edges="ring"),
              "PCG_EdgeStraighten": dict(geo=g, edges="e"),
              "PCG_CircleFromEdges": dict(geo=wob, edges="ring"),
              "PCG_EdgeFlip": dict(geo=sg), "PCG_TriDivide": dict(geo=sph),
              "PCG_Unsubdivide": dict(geo=f1),
              "PCG_RewireVertices": dict(geo=two),
              "PCG_PolyCut": dict(geo=sqc, points="c"),
              "PCG_PolyStitch": dict(geo=m),
              "PCG_VoronoiSplit": dict(geo=sph, cell_points=sites)}.items():
    try:
        r = unwrap(MAP[k]().run(**defaults(MAP[k], **kw)))
        if not isinstance(r[0], Geometry):
            bad.append(k)
    except Exception as ex:                       # noqa: BLE001
        bad.append(f"{k}: {ex}")
check("all 10 nodes run with default parameters (with the needed inputs connected)", not bad, bad)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
