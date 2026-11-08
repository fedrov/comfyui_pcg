"""
pcg68: SOP gap batch C (variants and attributes) and batch D (mesh repair), 11 nodes.

━━ Criteria
  Attribute from Pieces
    · weights 3:1:1:1: frequencies over twenty thousand points fall within ±4σ; same seed same result, different seed different
    · per piece: elements of the same piece get the same variant; cycle rotates in turn; by_attribute is monotonic in the attribute
    · with an id attribute, deleting half the points leaves the remaining points' variants unchanged (random by key, not by index)
    · library: variants are piece names, weights read from library's weight (weight 0 never appears)
  Enumerate: index, count from the start within a piece, piece index (first occurrence / sorted), start / step,
    Format zero padding; errors when Format doesn't have exactly one placeholder
  Color: constant / random (reproducible) / random_by_attribute (same value same color, different values different colors)
    / ramp (ends are the ramp's ends) / adjust (red rotated 120° = green, saturation 0 = gray, random per piece:
    same piece same offset); only the selection is changed
  Attribute Fill
    · harmonic: with f = 2x + 3z given on the grid boundary, the interior is filled with **exactly** 2x + 3z (the uniformly weighted
      graph Laplacian preserves linear functions on a regular grid)
    · two known points: filled values all lie between them (maximum principle), each unknown point equals the average of its neighbors
    · nearest: left known 0, right known 1, the left half is all 0; diffuse with enough iterations approaches harmonic
    · disconnected pieces untouched and counted in the report; no known points errors
  Attribute String Edit: substring / wildcard (* captures fill the replacement) / regex (\\1) /
    case-insensitive / group; wrong number of * in the wildcard errors
  Cluster Points: three well-separated blobs of points -> exactly three clusters, 100% purity, centers at the blob centers; reproducible
  Remesh
    · sphere: watertight, Euler characteristic 2, points on the original (faceted) sphere, over 95% of edges within the target range,
      higher fraction of valence-6 points than the original mesh; point attribute f = x interpolated ≈ x of the new points
    · cube: the 8 corners preserved, all points on the cube surface, each of the 12 edges fully covered by mesh edges
      (negative control: with feature_angle = 180 the corners aren't preserved)
    · open mesh: boundary points all on the original square, total boundary length unchanged (= perimeter 8), Euler characteristic 1
  Clean: bowtie points split; duplicate faces (different start, reversed winding) reduced to one; degenerate faces removed; edges shared by three faces
    keep two; consistent orientation; small pieces deleted; points within distance fused; unused points deleted
  Edge Collapse: two connected edges collapse to one point, at the center of the three points; adjacent quads become triangles
  Point Split: only points on uv seams are split (number of split points = points on the seam); empty splits all;
    chained tolerance doesn't bucket; group; after promote the point attribute = each vertex's value
  UV Fuse: tiny uv differences at the same point -> fused to the average; real seams not fused; distance mode stitches
    the touching edges of two islands
"""
import json
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

from comfyui_pcg.geo import variants as VA              # noqa: E402
from comfyui_pcg.geo import meshfix as MF               # noqa: E402
from comfyui_pcg.geo import remesh as RM                # noqa: E402
from comfyui_pcg.geo import build, ops                  # noqa: E402
from comfyui_pcg.geo.spatial import tri_soup           # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, VERTEX, PRIM, DETAIL  # noqa: E402
from comfyui_pcg.geo.topology import topology           # noqa: E402
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


def A(g, cls, name):
    return np.asarray(g.get(cls, name))


rng = np.random.default_rng(68)

# ═══════════════════════════════════════════════════ Attribute from Pieces
sec("Attribute from Pieces")
pts = Geometry.from_points(rng.random((20000, 3)))
o, r = VA.attrib_from_pieces(pts, weights="3 1 1 1", seed=5)
v = A(o, POINT, "variant").ravel()
freq = np.bincount(v, minlength=4) / len(v)
want = np.array([0.5, 1 / 6, 1 / 6, 1 / 6])
sig = np.sqrt(want * (1 - want) / len(v))
check(f"weights 3:1:1:1 frequencies within ±4σ {np.round(freq, 3).tolist()}",
      (np.abs(freq - want) < 4 * sig).all())
o2, _ = VA.attrib_from_pieces(pts, weights="3 1 1 1", seed=5)
o3, _ = VA.attrib_from_pieces(pts, weights="3 1 1 1", seed=6)
check("same seed same result, different seed different",
      np.array_equal(A(o2, POINT, "variant"), A(o, POINT, "variant")) and
      not np.array_equal(A(o3, POINT, "variant"), A(o, POINT, "variant")))
bx = ops.merge(*[ops.transform(build.box(), translate=(i * 2, 0, 0))
                 for i in range(30)])
bx.set(PRIM, "piece", np.repeat(np.arange(30), 6)[:, None].astype(np.int32))
ob, _ = VA.attrib_from_pieces(bx, cls="prim", piece_attribute="piece", count=5)
vb = A(ob, PRIM, "variant").reshape(30, 6)
check("per piece: the 6 faces of a piece get the same variant", (vb == vb[:, :1]).all() and
      len(np.unique(vb[:, 0])) > 1)
oc, _ = VA.attrib_from_pieces(pts, mode="cycle", count=3)
check("cycle:0 1 2 0 1 2 …", np.array_equal(A(oc, POINT, "variant").ravel()[:7],
                                            [0, 1, 2, 0, 1, 2, 0]))
px = pts.copy()
px.set(POINT, "u", A(pts, POINT, "P")[:, :1].astype(np.float32))
oa, _ = VA.attrib_from_pieces(px, mode="by_attribute", input_attribute="u",
                              weights="1 1 1 1")
order = np.argsort(A(px, POINT, "u").ravel())
check("by_attribute: monotonic in the attribute (u ascending, variant 0 -> 3)",
      (np.diff(A(oa, POINT, "variant").ravel()[order]) >= 0).all())
pid = pts.copy()
pid.set(POINT, "id", (np.arange(20000) * 7 + 3)[:, None].astype(np.int32))
oi, _ = VA.attrib_from_pieces(pid, count=6)
half = np.arange(20000) % 2 == 0
from comfyui_pcg.geo.ops import delete_points          # noqa: E402
ph = delete_points(pid, half)
oh, _ = VA.attrib_from_pieces(ph, count=6)
check("with id, deleting half the points leaves the remaining points' variants unchanged",
      np.array_equal(A(oh, POINT, "variant").ravel(),
                     A(oi, POINT, "variant").ravel()[half]))
lib = ops.merge(build.box(), ops.transform(build.sphere(), translate=(3, 0, 0)),
                ops.transform(build.box(), translate=(6, 0, 0)))
names = ["rock"] * 6 + ["pebble"] * (lib.nprims - 12) + ["boulder"] * 6
lib.set_string(PRIM, "name", names)
wts = np.array([1.0 if n == "rock" else (0.0 if n == "boulder" else 1.0)
                for n in names], np.float32)[:, None]
lib.set(PRIM, "weight", wts)
ol, rl = VA.attrib_from_pieces(pts, lib)
vl = A(ol, POINT, "variant").ravel()
check("library: variants are piece names, boulder with weight 0 never appears",
      set(vl.tolist()) == {"rock", "pebble"} and rl["counts"]["boulder"] == 0)
og = VA.attrib_from_pieces(oc, count=9, group="0-9", output="variant")[0]
check("outside group the original values are kept", np.array_equal(A(og, POINT, "variant")[10:],
                                         A(oc, POINT, "variant")[10:]))

# ═══════════════════════════════════════════════════════════ Enumerate
sec("Enumerate")
g5 = Geometry.from_points(rng.random((10, 3)))
g5.set_string(POINT, "name", ["b", "a", "b", "c", "a", "b", "c", "c", "a", "b"])
e = VA.enumerate_(g5, "point")
check("elements:0..9", np.array_equal(A(e, POINT, "index").ravel(), np.arange(10)))
e = VA.enumerate_(g5, "point", piece_attribute="name", name="k")
check("count from the start within a piece", np.array_equal(A(e, POINT, "k").ravel(),
                                   [0, 0, 1, 0, 1, 2, 1, 2, 2, 3]))
e = VA.enumerate_(g5, "point", mode="pieces", piece_attribute="name", name="p")
e2 = VA.enumerate_(g5, "point", mode="pieces", piece_attribute="name", name="p",
                   order="sorted")
check("piece index: first occurrence (b=0 a=1 c=2) / sorted (a=0 b=1 c=2)",
      np.array_equal(A(e, POINT, "p").ravel(), [0, 1, 0, 2, 1, 0, 2, 2, 1, 0])
      and np.array_equal(A(e2, POINT, "p").ravel(),
                         [1, 0, 1, 2, 0, 1, 2, 2, 0, 1]))
e = VA.enumerate_(g5, "point", start=10, step=5, fmt="piece_%03d")
check("start / step + Format zero padding", A(e, POINT, "index").ravel()[:2].tolist()
      == ["piece_010", "piece_015"])
err("Format without %d errors", lambda: VA.enumerate_(g5, fmt="piece"), "%d")
err("Format with two %d errors", lambda: VA.enumerate_(g5, fmt="%d_%d"), "%d")

# ═══════════════════════════════════════════════════════════ Color
sec("Color")
c = VA.color(g5, mode="constant", rgb=(0.2, 0.4, 0.6))
check("constant", np.allclose(A(c, POINT, "Cd"), [0.2, 0.4, 0.6]))
c1 = VA.color(g5, mode="random", seed=3)
c2 = VA.color(g5, mode="random", seed=3)
check("random: reproducible, each element different", np.array_equal(A(c1, POINT, "Cd"),
                                           A(c2, POINT, "Cd")) and
      len(np.unique(A(c1, POINT, "Cd"), axis=0)) == 10)
cb = VA.color(g5, mode="random_by_attribute", attribute="name")
Cb = A(cb, POINT, "Cd")
nm = A(g5, POINT, "name").ravel()
same = all(np.allclose(Cb[nm == k], Cb[nm == k][0]) for k in "abc")
check("random_by_attribute: same name same color, three names three colors", same and
      len(np.unique(Cb, axis=0)) == 3)
gr = g5.copy()
gr.set(POINT, "h", np.arange(10, dtype=np.float32)[:, None])
cr = VA.color(gr, mode="ramp_by_attribute", attribute="h",
              ramp="0:0,0,1 1:1,0,0")
Cr = A(cr, POINT, "Cd")
check("ramp: min = blue, max = red", np.allclose(Cr[0], [0, 0, 1]) and
      np.allclose(Cr[9], [1, 0, 0]))
red = VA.color(g5, mode="constant", rgb=(1, 0, 0))
check("adjust: red rotated 120° = green",
      np.allclose(A(VA.color(red, mode="adjust", hue_shift=120), POINT, "Cd"),
                  [0, 1, 0], atol=1e-6))
check("adjust: saturation 0 = gray",
      np.allclose(A(VA.color(red, mode="adjust", saturation=0), POINT, "Cd"),
                  [1, 1, 1], atol=1e-6))
ca = VA.color(red, mode="adjust", random_hue=90, attribute="name")
Ca = A(ca, POINT, "Cd")
check("adjust + random per piece: same piece same offset, different pieces different",
      all(np.allclose(Ca[nm == k], Ca[nm == k][0]) for k in "abc") and
      len(np.unique(np.round(Ca, 5), axis=0)) == 3)
cg = VA.color(red, mode="constant", rgb=(0, 0, 1), group="0-4")
check("only the selection is changed", np.allclose(A(cg, POINT, "Cd")[:5], [0, 0, 1]) and
      np.allclose(A(cg, POINT, "Cd")[5:], [1, 0, 0]))

# ═══════════════════════════════════════════════════════════ Attribute Fill
sec("Attribute Fill")
G = build.grid(4, 4, 17, 17)
P = A(G, POINT, "P").astype(np.float64)
t = topology(G)
bnd = np.zeros(G.npoints, bool)
bnd[t.edge_points[t.boundary].ravel()] = True
Gf = G.copy()
Gf.set(POINT, "f", np.where(bnd, 2 * P[:, 0] + 3 * P[:, 2], 0)[:, None]
       .astype(np.float32))
Gf.set_group(POINT, "k", bnd)
o, r = VA.attrib_fill(Gf, "f", "k")
check("harmonic: 2x+3z given on the boundary, interior filled with exactly 2x+3z",
      np.abs(A(o, POINT, "f").ravel() - (2 * P[:, 0] + 3 * P[:, 2])).max()
      < 1e-4 and r["filled"] == int((~bnd).sum()))
G2 = G.copy()
f2 = np.zeros((G.npoints, 1), np.float32)
f2[0], f2[-1] = -1, 2
G2.set(POINT, "f", f2)
kk = np.zeros(G.npoints, bool)
kk[[0, G.npoints - 1]] = True
G2.set_group(POINT, "k", kk)
o, _ = VA.attrib_fill(G2, "f", "k")
fv = A(o, POINT, "f").ravel().astype(np.float64)
E = t.edge_points.astype(np.int64)
s_ = np.bincount(E[:, 0], fv[E[:, 1]], G.npoints) + np.bincount(
    E[:, 1], fv[E[:, 0]], G.npoints)
deg = np.bincount(E.ravel(), minlength=G.npoints)
res = np.abs(fv - s_ / deg)[~kk].max()
check(f"two known points: values within [-1, 2], each unknown point = average of its neighbors (residual {res:.1e})",
      fv.min() >= -1 - 1e-6 and fv.max() <= 2 + 1e-6 and res < 1e-5)
G3 = G.copy()
left, right = P[:, 0] < -1.99, P[:, 0] > 1.99
G3.set(POINT, "f", np.where(right, 1.0, 0.0)[:, None].astype(np.float32))
G3.set_group(POINT, "k", left | right)
o, _ = VA.attrib_fill(G3, "f", "k", method="nearest")
fn = A(o, POINT, "f").ravel()
check("nearest: left known 0, right known 1 -> left half 0, right half 1",
      (fn[P[:, 0] < -0.1] == 0).all() and (fn[P[:, 0] > 0.1] == 1).all())
oh_, _ = VA.attrib_fill(G3, "f", "k", method="harmonic")
od, _ = VA.attrib_fill(G3, "f", "k", method="diffuse", iterations=3000)
check("diffuse with enough iterations ≈ harmonic",
      np.abs(A(od, POINT, "f") - A(oh_, POINT, "f")).max() < 1e-3)
two = ops.merge(G2, ops.transform(G, translate=(10, 0, 0)))
kk2 = np.concatenate([kk, np.zeros(G.npoints, bool)])
two.set_group(POINT, "k", kk2)
rnd2 = rng.random((G.npoints, 1)).astype(np.float32)
two.set(POINT, "f", np.concatenate([f2, rnd2]))
o, r = VA.attrib_fill(two, "f", "k")
check("disconnected piece (random values) left untouched and recorded in the report", r["unreachable"] == G.npoints
      and np.array_equal(A(o, POINT, "f")[G.npoints:], rnd2))
Ge = Gf.copy()
Ge.set_group(POINT, "empty", np.zeros(Gf.npoints, bool))
err("empty known point group errors", lambda: VA.attrib_fill(Ge, "f", "empty"), "No known points")

# ═══════════════════════════════════════════════════ Attribute String Edit
sec("Attribute String Edit")
sg = Geometry.from_points(np.zeros((5, 3)))
sg.set_string(POINT, "name", ["piece12_old", "Piece3_old", "rock", "piece7",
                              "piece5_old_v2"])
o, r = VA.string_edit(sg, "point", "name", find="piece", replace="chunk")
check("substring: all occurrences", A(o, POINT, "name").ravel().tolist() ==
      ["chunk12_old", "Piece3_old", "rock", "chunk7", "chunk5_old_v2"])
o, _ = VA.string_edit(sg, "point", "name", find="piece*_old", replace="chunk*",
                      mode="wildcard")
check("wildcard: * captures fill the replacement; whole-string match (piece5_old_v2 doesn't count)",
      A(o, POINT, "name").ravel().tolist() ==
      ["chunk12", "Piece3_old", "rock", "piece7", "piece5_old_v2"])
o, _ = VA.string_edit(sg, "point", "name", find="piece*_old", replace="chunk*",
                      mode="wildcard", case_sensitive=False)
check("case-insensitive", A(o, POINT, "name").ravel()[1] == "chunk3")
o, _ = VA.string_edit(sg, "point", "name", find=r"(\w+?)(\d+)",
                      replace=r"\2_\1", mode="regex")
check("regex backreference", A(o, POINT, "name").ravel()[3] == "7_piece")
o, _ = VA.string_edit(sg, "point", "name", find="piece", replace="X",
                      group="0")
check("outside group untouched", A(o, POINT, "name").ravel()[3] == "piece7")
err("wildcard replacement has more * than the search", lambda: VA.string_edit(
    sg, "point", "name", find="p*", replace="**", mode="wildcard"), "*")
err("no matching string attribute errors", lambda: VA.string_edit(sg, "point", "nope"),
    "string attribute")

# ═══════════════════════════════════════════════════════════ Cluster Points
sec("Cluster Points")
cent = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 5]], float)
blob = np.vstack([c_ + rng.standard_normal((200, 3)) * 0.5 for c_ in cent])
bg = Geometry.from_points(blob)
o, cen, r = VA.cluster_points(bg, 3, seed=1)
lab = A(o, POINT, "cluster").ravel()
pure = all(len(np.unique(lab[i * 200:(i + 1) * 200])) == 1 for i in range(3))
Pc = A(cen, POINT, "P")
near = all(np.linalg.norm(Pc - c_, axis=1).min() < 0.2 for c_ in cent)
check("three blobs: exactly three clusters, 100% purity, centers at blob centers", pure and len(np.unique(lab)) == 3
      and near and (A(cen, POINT, "count").ravel() == 200).all())
o2, _, _ = VA.cluster_points(bg, 3, seed=1)
check("reproducible", np.array_equal(A(o2, POINT, "cluster"), A(o, POINT, "cluster")))
# Move everything to around (10,10,10): if an empty cluster's center isn't refilled and stays at the zero vector, it also can't
# happen to be near some blob and "come back to life by itself"
Xb = np.vstack([rng.standard_normal((100, 3)) * 0.1,
                rng.standard_normal((100, 3)) * 0.1 + [5, 0, 0],
                rng.standard_normal((100, 3)) * 0.1 + [0, 5, 0]]) + 10
lab_, C_, _, _ = VA._lloyd(Xb, np.array([[0, 0, 0], [100, 100, 100], [5, 0, 0.]])
                           + 10, 30)
check("Lloyd: one initial center far from all points (empty cluster) -> a point is taken as the new center, none of the three clusters empty",
      (np.bincount(lab_, minlength=3) > 0).all())
xl = np.linspace(0, 1, 4000)
line_ = Geometry.from_points(np.c_[xl, 0 * xl, 0 * xl])
_, cl4, _ = VA.cluster_points(line_, 4, seed=0, iterations=200)
cx = np.sort(A(cl4, POINT, "P")[:, 0])
check(f"uniform segment into 4 clusters: centers converge to 1/8 3/8 5/8 7/8 ({np.round(cx, 3).tolist()})",
      np.abs(cx - [0.125, 0.375, 0.625, 0.875]).max() < 0.01)
_, _, r = VA.cluster_points(Geometry.from_points(rng.random((5, 3))), 10)
check("more clusters than points: use the point count", r["clusters"] == 5)

# ═══════════════════════════════════════════════════════════ Remesh
sec("Remesh")


def chi(g):
    t_ = topology(g)
    return g.npoints - t_.nedges + g.nprims, bool((t_.edge_count == 2).all())


def val6(g):
    t_ = topology(g)
    v = np.bincount(t_.edge_points.ravel(), minlength=g.npoints)
    b = np.zeros(g.npoints, bool)
    b[t_.edge_points[t_.boundary].ravel()] = True
    return float((v[~b] == 6).mean())


sph = build.sphere(1.0, 24, 16)
sph.set(POINT, "f", A(sph, POINT, "P")[:, :1].copy())
o, r = RM.remesh(sph, 0.15, 6)
x, wt = chi(o)
Pn = A(o, POINT, "P").astype(np.float64)
rad = np.abs(np.linalg.norm(Pn, axis=1) - 1).max()
sag = 1 - math.cos(math.pi / 16)
check(f"sphere: watertight, Euler characteristic 2 (actual {x})", wt and x == 2)
check(f"  points on the original faceted sphere (distance from the unit sphere ≤ facet sagitta {sag:.3f}, actual {rad:.3f})",
      rad <= sag + 1e-4)
check(f"  {r['within_range'] * 100:.1f}% of edges within [L/2, 4L/3]", r["within_range"]
      > 0.95)
check(f"  valence-6 points: {val6(sph):.2f} -> {val6(o):.2f}", val6(o) > val6(sph))
check("  point attribute f = x interpolated ≈ x of the new points",
      np.abs(A(o, POINT, "f").ravel() - Pn[:, 0]).max() < 0.02)
cube = build.box()
o, r = RM.remesh(cube, 0.1, 6)
Pc_ = A(o, POINT, "P").astype(np.float64)
corners = np.array([[a, b, c_] for a in (-.5, .5) for b in (-.5, .5)
                    for c_ in (-.5, .5)])
check("cube: the 8 corners preserved", all((np.linalg.norm(Pc_ - q, axis=1) < 1e-9).any()
                               for q in corners))
check("  all points on the cube surface", np.abs(np.abs(Pc_).max(1) - 0.5).max() < 1e-9)
t_ = topology(o)
Ep = Pc_[t_.edge_points]
on = (np.abs(np.abs(Ep) - 0.5) < 1e-9)                   # (E,2,3)
cov = {}
for ax in range(3):
    others = [k for k in range(3) if k != ax]
    m = on[:, 0, others].all(1) & on[:, 1, others].all(1)
    for e in np.nonzero(m)[0]:
        key = (ax, tuple(np.sign(Ep[e, 0, others]).astype(int)))
        cov[key] = cov.get(key, 0) + abs(Ep[e, 0, ax] - Ep[e, 1, ax])
check("  each of the 12 edges fully covered by mesh edges (total length = 1)",
      len(cov) == 12 and all(abs(v_ - 1) < 1e-9 for v_ in cov.values()))
o180, _ = RM.remesh(cube, 0.1, 6, feature_angle=180)
P180 = A(o180, POINT, "P").astype(np.float64)
check("  negative control: with feature_angle = 180 the corners aren't preserved",
      not all((np.linalg.norm(P180 - q, axis=1) < 1e-9).any() for q in corners))
gd = build.grid(2, 2, 5, 5)
o, r = RM.remesh(gd, 0.1, 6)
x, _ = chi(o)
t_ = topology(o)
Pg = A(o, POINT, "P").astype(np.float64)
be = t_.edge_points[t_.boundary]
blen = np.linalg.norm(Pg[be[:, 0]] - Pg[be[:, 1]], axis=1).sum()
bp = np.unique(be.ravel())
check(f"open mesh: boundary points on the square, total boundary length = 8 ({blen:.6f}), Euler characteristic 1",
      np.abs(np.abs(Pg[bp][:, [0, 2]]).max(1) - 1).max() < 1e-9 and
      abs(blen - 8) < 1e-9 and x == 1)
for Lc in (0.4, 0.7):
    oc_, _ = RM.remesh(build.sphere(1, 24, 16), Lc, 6)
    xc, wc = chi(oc_)
    check(f"very coarse target edge length {Lc} (lots of collapses): still watertight, Euler characteristic 2", wc and xc == 2)
tor_ = build.torus(1.0, 0.3, 12, 24) if hasattr(build, "torus") else None
if tor_ is not None:
    ot_, _ = RM.remesh(tor_, 0.35, 6)
    xt, wt_ = chi(ot_)
    check(f"coarse remesh of a torus: watertight, Euler characteristic 0 (actual {xt})", wt_ and xt == 0)
if tor_ is not None:
    # A thin torus with only 3 segments in cross section, hard edges not respected: the "common neighbors" of two points in a collapse may wrap around the tube
    # to the other side -- without checking the link condition the tube gets pinched into a non-manifold / changes genus
    for Lk in (0.4, 0.6):
        otk, _ = RM.remesh(build.torus(1.0, 0.3, 3, 24), Lk, 6, feature_angle=180)
        xk, wk = chi(otk)
        check(f"thin torus with a triangular cross section (L={Lk}, hard edges not respected): watertight, Euler characteristic 0 (actual {xk})",
              wk and xk == 0)


def ramp_(x):
    return 0.3 * np.clip(x, 0, 0.06)


xs_ = np.unique(np.r_[np.linspace(-1, 1, 21), 0, 0.06])
zs_ = np.linspace(-1, 1, 21)
XX, ZZ = np.meshgrid(xs_, zs_, indexing="ij")
nz_ = len(zs_)
rq = [[i * nz_ + j, i * nz_ + j + 1, (i + 1) * nz_ + j + 1, (i + 1) * nz_ + j]
      for i in range(len(xs_) - 1) for j in range(nz_ - 1)]
rampg = Geometry.from_mesh(np.c_[XX.ravel(), ramp_(XX.ravel()), ZZ.ravel()], rq,
                           closed=True)
orp, _ = RM.remesh(rampg, 0.15, 6, feature_angle=5)
Vr = A(orp, POINT, "P").astype(np.float64)
Tr, _, _ = tri_soup(orp)
Cr = Vr[Tr].mean(1)
dev = np.abs(Cr[:, 1] - ramp_(Cr[:, 0])).max()
check(f"two creases only 0.06 apart (L=0.15 > spacing): ordinary edges with feature points at both ends don't collapse, "
      f"no triangle straddles a crease (triangle centers off the original surface {dev:.1e}, P is float32)", dev < 1e-6)
slab = ops.transform(build.box(), scale=(1, 0.05, 1))
os_, _ = RM.remesh(slab, 0.1, 4)
Psl = A(os_, POINT, "P").astype(np.float64)
check("thin slab (thickness 0.05 < 0.8L): edges across the thickness don't collapse, all points still on the slab surface, all 8 corners present",
      np.abs(np.abs(Psl / [0.5, 0.025, 0.5]).max(1) - 1).max() < 1e-6 and
      all((np.linalg.norm(Psl - q * [1, 0.05, 1], axis=1) < 1e-9).any()
          for q in corners))
tb = build.tube(1, 1, 1, 16, 2)
otb, _ = RM.remesh(tb, 0.35, 4)
Ptb = A(otb, POINT, "P").astype(np.float64)
ang16 = np.linspace(0, 2 * np.pi, 17)
poly16 = np.c_[np.cos(ang16), np.zeros(17), np.sin(ang16)]
rimpt = (np.abs(np.abs(Ptb[:, 1]) - 0.5) < 1e-9) & (np.hypot(Ptb[:, 0], Ptb[:, 2])
                                                     > 0.7)


def dist_poly(q, V_):
    a_, b_ = V_[:-1], V_[1:]
    d_ = b_ - a_
    t_ = np.clip(((q[:, None, [0, 2]] - a_[None, :, [0, 2]]) * d_[None, :, [0, 2]])
                 .sum(2) / (d_[:, [0, 2]] ** 2).sum(1), 0, 1)
    pp = a_[None, :, [0, 2]] + t_[..., None] * d_[None, :, [0, 2]]
    return np.linalg.norm(pp - q[:, None, [0, 2]], axis=2).min(1)


if not ((np.hypot(A(tb, POINT, "P")[:, 0], A(tb, POINT, "P")[:, 2]) - 1) ** 2
        < 1e-10).all():
    poly16 = None
dp = dist_poly(Ptb[rimpt], poly16) if poly16 is not None and rimpt.any() else [0]
check(f"points on the top and bottom rims (hard edges) of the cylinder all land on the original 16-gon (max deviation {np.max(dp):.1e})",
      rimpt.sum() > 0 and np.max(dp) < 1e-6)
err("curve input errors", lambda: RM.remesh(Geometry.from_mesh(
    np.array([[0, 0, 0], [1, 0, 0.]]), [[0, 1]], closed=False)), "polygon")

# ═══════════════════════════════════════════════════════════ Clean
sec("Clean")
Pb = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [-1, 0, 0], [0, -1, 0]], float)
bt = Geometry.from_mesh(Pb, [[0, 1, 2], [0, 3, 4]])
o, r = MF.clean(bt, make_manifold=True)
check("bowtie point split: 5 points -> 6 points, the two faces no longer share a point",
      o.npoints == 6 and not (set(o.prim_points(0)) & set(o.prim_points(1))))
Pd = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], float)
dg = Geometry.from_mesh(Pd, [[0, 1, 2], [1, 2, 0], [2, 1, 0], [1, 3, 2],
                             [0, 0, 1]])
o, r = MF.clean(dg)
check("duplicate faces (different start, reversed winding) reduced to one; degenerate faces removed",
      r["duplicate_prims"] == 2 and r["degenerate_prims"] == 1 and o.nprims == 2)
Pn3 = np.array([[0, 0, 0], [1, 0, 0], [0.5, 2, 0], [0.5, -1, 0],
                [0.5, 0, 0.5]], float)
nm3 = Geometry.from_mesh(Pn3, [[0, 1, 2], [1, 0, 3], [0, 1, 4]])
o, r = MF.clean(nm3, make_manifold=True)
ar = np.linalg.norm(ops.prim_normals(o, normalize=False), axis=1).sum()
check(f"three faces sharing an edge: delete the one with the smallest area (remaining two areas sum to 1.5, actual {ar:.3f})",
      r["nonmanifold_faces_removed"] == 1 and o.nprims == 2 and
      (topology(o).edge_count <= 2).all() and abs(ar - 1.5) < 1e-6)
okg, rk = MF.clean(build.grid(2, 2, 5, 5), make_manifold=True)
okf, rf = MF.clean(gflip if "gflip" in dir() else build.grid(2, 2, 5, 5),
                   make_manifold=True) if False else (None, None)
check("manifold mesh with make_manifold on: not a single point split", rk["bowtie_points_split"] == 0
      and okg.npoints == 25)
gflip = build.grid(2, 2, 4, 4)
vp = gflip.vertex_point.copy()
off = gflip.prim_offset
vp[off[3]:off[4]] = vp[off[3]:off[4]][::-1]
gflip.set_topology(vp, off, gflip.prim_closed)
of_, rf_ = MF.clean(gflip, make_manifold=True)
check("manifold mesh with inconsistent orientation (one face flipped) with make_manifold on: no split either",
      rf_["bowtie_points_split"] == 0 and of_.npoints == gflip.npoints)
o, _ = MF.clean(gflip, orient=True)
nrm = ops.prim_normals(o)
check("consistent orientation: the flipped face flipped back", (nrm[:, 1] * nrm[0, 1] > 0).all())
small = ops.merge(build.grid(2, 2, 6, 6),
                  ops.transform(Geometry.from_mesh(Pd, [[0, 1, 2]]),
                                translate=(5, 0, 0)))
o, r = MF.clean(small, min_piece_prims=2)
check("small piece (1 face) deleted", o.nprims == 25 and r["small_piece_prims"] == 1)
near_ = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0],
                                     [1, 0, 1e-5], [1, 1, 0]], float),
                           [[0, 1, 2], [3, 4, 2]])
o, r = MF.clean(near_, fuse_distance=1e-3)
check("points within distance fused", r["fused_points"] == 1 and o.npoints == 4)
iso = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [9, 9, 9]],
                                  float), [[0, 1, 2]])
o, r = MF.clean(iso)
check("unused points deleted", o.npoints == 3)

# ═══════════════════════════════════════════════════════════ Edge Collapse
sec("Edge Collapse")
g = build.grid(2, 2, 5, 5)
g.set_edge_group("e", np.array([[0, 1], [1, 2]]))
P0 = A(g, POINT, "P").astype(np.float64)
o, r = MF.edge_collapse(g, "e")
Po = A(o, POINT, "P").astype(np.float64)
check("two connected edges collapse to one point, at the center of the three points",
      o.npoints == 23 and r["collapsed_chains"] == 1 and
      (np.linalg.norm(Po - P0[[0, 1, 2]].mean(0), axis=1) < 1e-6).any())
sz = o.prim_sizes()
check("the two adjacent quads become triangles", int((sz == 3).sum()) == 2 and o.nprims == 16)
err("empty Edges errors", lambda: MF.edge_collapse(g, ""), "edge group")

# ═══════════════════════════════════════════════════════════ Point Split
sec("Point Split")
gs = build.grid(2, 2, 5, 5)
Pg = A(gs, POINT, "P").astype(np.float64)
vpg = gs.vertex_point
vprim = gs.vertex_prim()
cen_x = ops.prim_centers(gs)[:, 0]
uv = np.stack([Pg[vpg, 0] + np.where(cen_x[vprim] > 0, 10, 0), Pg[vpg, 2],
               np.zeros(len(vpg))], 1)
gs.set(VERTEX, "uv", uv.astype(np.float32))
o, r = MF.point_split(gs, "uv")
check("only points on the uv seam are split (middle column of 5 points -> 5 more points)", r["split_points"] == 5)
pv = A(o, POINT, "uv")[o.vertex_point]
check("promote: point attribute = each vertex's value",
      np.abs(pv - A(o, VERTEX, "uv")).max() < 1e-6)
o, r = MF.point_split(gs, "")
check("empty splits all: point count = vertex count", o.npoints == gs.nvertices)
gc = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [-1, 0, 0]],
                                 float), [[0, 1, 2], [0, 2, 3], [0, 3, 1]])
gc.set(VERTEX, "a", np.array([0.1, 0, 0, 0.1 + 6e-6, 0, 0, 0.1 + 12e-6, 0, 0],
                             np.float32)[:, None])
o, r = MF.point_split(gc, "a", tolerance=1e-5)
check("chained tolerance: 0.1, +6e-6, +1.2e-5 adjacent differences all ≤ 1e-5 -> no split", r["split_points"]
      == 0)
o, r = MF.point_split(gs, "uv", group="0 1 3 4")
o2, r2 = MF.point_split(gs, "uv", group="2 7")
check("group: no seam points included means no split; only 2 points of the middle column included means only 2 split",
      r["split_points"] == 0 and r2["split_points"] == 2)

# ═══════════════════════════════════════════════════════════ UV Fuse
sec("UV Fuse")
gu = build.grid(2, 2, 5, 5)
Pu = A(gu, POINT, "P").astype(np.float64)
base = np.stack([Pu[gu.vertex_point, 0], Pu[gu.vertex_point, 2],
                 np.zeros(gu.nvertices)], 1)
noisy = base + np.hstack([rng.standard_normal((gu.nvertices, 2)) * 1e-5,
                          np.zeros((gu.nvertices, 1))])
gu.set(VERTEX, "uv", noisy.astype(np.float32))
o, r = MF.uv_fuse(gu, "uv", "shared_points", 1e-3)
U = A(o, VERTEX, "uv").astype(np.float64)
spread = max(np.ptp(U[gu.vertex_point == p][:, :2], axis=0).max()
             for p in range(gu.npoints))
check(f"tiny uv differences at the same point fused to one value (max diff within a point {spread:.1e})",
      spread < 1e-6 and r["fused_groups"] > 0)
seam = gs.copy()
o, r = MF.uv_fuse(seam, "uv", "shared_points", 1e-3)
check("real seam (diff 10) not fused: not a single uv moved",
      r["vertices_moved"] == 0 and np.array_equal(A(o, VERTEX, "uv"),
                                                  A(seam, VERTEX, "uv")))
isl = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                                   [1, 0, 0], [2, 0, 0], [2, 1, 0], [1, 1, 0]],
                                  float), [[0, 1, 2, 3], [4, 5, 6, 7]])
isl.set(VERTEX, "uv", np.array([[0, 0, 0], [0.5, 0, 0], [0.5, 1, 0], [0, 1, 0],
                                [0.5004, 0, 0], [1, 0, 0], [1, 1, 0],
                                [0.5004, 1, 0]], np.float32))
o_s, r_s = MF.uv_fuse(isl, "uv", "shared_points", 1e-3)
check("shared_points: different points aren't fused even if their uvs are close", r_s["vertices_moved"] == 0)
o, r = MF.uv_fuse(isl, "uv", "distance", 1e-3)
U = A(o, VERTEX, "uv")
check("distance: the touching edges of two islands get stitched (different points fused too)",
      r["fused_groups"] == 2 and abs(U[1, 0] - U[4, 0]) < 1e-7)

# ═══════════════════════════════════════════════════════════ Nodes
sec("Nodes")
NEW = {"PCG_AttribFromPieces": "PCG/attribute", "PCG_Enumerate": "PCG/attribute",
       "PCG_Color": "PCG/attribute", "PCG_AttribFill": "PCG/attribute",
       "PCG_AttribStringEdit": "PCG/attribute",
       "PCG_ClusterPoints": "PCG/attribute", "PCG_Remesh": "PCG/modify",
       "PCG_Clean": "PCG/modify", "PCG_EdgeCollapse": "PCG/modify",
       "PCG_PointSplit": "PCG/modify", "PCG_UVFuse": "PCG/uv"}
check("all 11 nodes registered, category correct",
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


gcol = VA.color(g5, mode="constant", rgb=(1, 0, 0))
runs = {
    "PCG_AttribFromPieces": dict(geo=pts),
    "PCG_Enumerate": dict(geo=g5),
    "PCG_Color": dict(geo=g5),
    "PCG_AttribFill": dict(geo=Gf, attribute="f", known_group="k"),
    "PCG_AttribStringEdit": dict(geo=sg, attribute_class="point", find="p",
                                 replace="q"),
    "PCG_ClusterPoints": dict(geo=bg),
    "PCG_Remesh": dict(geo=cube),
    "PCG_Clean": dict(geo=dg),
    "PCG_EdgeCollapse": dict(geo=g, edges="e"),
    "PCG_PointSplit": dict(geo=gs),
    "PCG_UVFuse": dict(geo=gu),
}
bad = []
for k, kw in runs.items():
    try:
        r = unwrap(MAP[k]().run(**defaults(MAP[k], **kw)))
        if not isinstance(r[0], Geometry) or (isinstance(r[-1], str) and
                                              not json.loads(r[-1])):
            bad.append(k)
    except Exception as ex:                       # noqa: BLE001
        bad.append(f"{k}: {ex}")
check("all 11 nodes run with default parameters (required names filled in)", not bad, bad)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
