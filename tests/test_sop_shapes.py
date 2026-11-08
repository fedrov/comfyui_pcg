"""
pcg70: tests for SOP gap batch E (modeling).

None of the checks rely on the implementation itself:
  Platonic Solids   point / edge / face counts, Euler characteristic, all edges equal length, all points on the circumsphere, faces
                    are flat regular polygons, dihedral angles, volume vs the analytic formula; consistent orientation (every directed
                    edge appears reversed exactly once) -- negative control: flip one face and the checker goes red
  L-System          Koch curve 4ⁿ segments, endpoint exactly at (0, 3ⁿ); branches share points; frequencies of random rules
                    within ±4σ; tropism makes horizontal branches droop without passing vertical
  Font              filled area of "O" = outer contour area − inner contour area (shoelace formula); no
                    triangles in the hole; extrusion watertight, consistently oriented, Euler characteristic = Σ(2 − 2·holes), volume =
                    area × thickness; exact relations for Tracking / alignment / line spacing / size
  Lattice           unmoved lattice -> unmoved; affine lattice as a whole -> geometry exactly affine (both interpolations);
                    locality of trilinear; bezier moving the middle control point = δ·8s(1−s)t(1−t)u(1−u)
  Point Deform      rigid transform of the whole low-res mesh -> exact rigid transform of the high-res one (rigid), translate as negative control;
                    continuous when the neighbours change
  Blend Shapes      additive formula, sequential midpoint, id correspondence (point order shuffled)
  Transform Pieces  rest = template -> unmoved; per-piece rigid transforms against hand-computed values
  Poly Bridge       cube tunnelled through: watertight, Euler characteristic 0, consistent orientation, volume = 8 − hole volume;
                    bridge + caps between similar squares = frustum volume formula; two loops with different point counts;
                    ruled surface area between two open polylines; hole boundaries (point groups)
"""
import json
import math
import os
import sys
from collections import Counter

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

from comfyui_pcg.geo import platonic as PL              # noqa: E402
from comfyui_pcg.geo import lsystem as LS               # noqa: E402
from comfyui_pcg.geo import font as FT                  # noqa: E402
from comfyui_pcg.geo import deformers as DF             # noqa: E402
from comfyui_pcg.geo import polybridge as PB            # noqa: E402
from comfyui_pcg.geo import build, ops                  # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, PRIM        # noqa: E402
from comfyui_pcg.geo.topology import topology           # noqa: E402
from comfyui_pcg.geo.spatial import tri_soup           # noqa: E402
from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP      # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag):
    try:
        fn()
        check(name, False, "did not raise")
    except Exception as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:90]}")


def sec(t):
    print("\n" + "═" * 28 + " " + t)


def A(g, cls, name):
    return np.asarray(g.get(cls, name))


def Pd(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def euler(g):
    t = topology(g)
    return g.npoints - t.nedges + g.nprims, bool((t.edge_count == 2).all())


def consistent(g):
    """Every directed edge is used at most once, and interior edges once in each direction (consistently oriented manifold)."""
    c = Counter()
    for i in range(g.nprims):
        v = g.prim_points(i).tolist()
        for a, b in zip(v, v[1:] + v[:1]):
            c[(a, b)] += 1
    return all(n == 1 for n in c.values()) and \
        all(c.get((b, a), 0) == 1 for (a, b) in c)


def volume(g):
    P = Pd(g)
    v = 0.0
    for i in range(g.nprims):
        f = g.prim_points(i)
        for j in range(1, len(f) - 1):
            v += np.dot(P[f[0]], np.cross(P[f[j]], P[f[j + 1]])) / 6
    return v


def area(g):
    T, _, _ = tri_soup(g)
    P = Pd(g)
    return 0.5 * np.linalg.norm(np.cross(P[T[:, 1]] - P[T[:, 0]],
                                         P[T[:, 2]] - P[T[:, 0]]), axis=1).sum()


def shoelace(a):
    x, y = a[:, 0], a[:, 1]
    return 0.5 * (np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


rng = np.random.default_rng(70)

# ═══════════════════════════════════════════════════════ Platonic Solids
sec("Platonic Solids")
phi = (1 + 5 ** 0.5) / 2
# (V, E, F, edges per face, dihedral angle°, volume (circumradius 1))
a_ico = 4 / math.sqrt(10 + 2 * 5 ** 0.5)
a_dod = 4 / (math.sqrt(3) * (1 + 5 ** 0.5))
a_soc = 2 / math.sqrt(1 + 9 * phi ** 2)
EXP = {
    "tetrahedron": (4, 6, 4, {3}, math.degrees(math.acos(1 / 3)),
                    8 / (9 * math.sqrt(3))),
    "cube": (8, 12, 6, {4}, 90.0, (2 / math.sqrt(3)) ** 3),
    "octahedron": (6, 12, 8, {3}, math.degrees(math.acos(-1 / 3)), 4 / 3),
    "dodecahedron": (20, 30, 12, {5}, math.degrees(math.acos(-1 / 5 ** 0.5)),
                     (15 + 7 * 5 ** 0.5) / 4 * a_dod ** 3),
    "icosahedron": (12, 30, 20, {3}, math.degrees(math.acos(-5 ** 0.5 / 3)),
                    5 / 12 * (3 + 5 ** 0.5) * a_ico ** 3),
    "soccer_ball": (60, 90, 32, {5, 6}, None,
                    (125 + 43 * 5 ** 0.5) / 4 * a_soc ** 3),
}
for kind, (nv, ne, nf, sides, dih, vol) in EXP.items():
    g = PL.solid(kind)
    P = Pd(g)
    t = topology(g)
    L = np.linalg.norm(P[t.edge_points[:, 0]] - P[t.edge_points[:, 1]], axis=1)
    x, wt = euler(g)
    fs = [g.prim_points(i) for i in range(g.nprims)]
    planar = max(abs(np.linalg.svd(P[f] - P[f].mean(0))[1][-1]) for f in fs)
    # Regular polygon: points on each face equidistant from the face center
    reg = max(np.ptp(np.linalg.norm(P[f] - P[f].mean(0), axis=1)) for f in fs)
    ok_d = True
    if dih is not None:
        N = ops.prim_normals(g)
        ef = {}
        for i, f in enumerate(fs):
            for a_, b_ in zip(f, np.roll(f, -1)):
                ef.setdefault((min(a_, b_), max(a_, b_)), []).append(i)
        ang = [180 - math.degrees(math.acos(np.clip(N[i] @ N[j], -1, 1)))
               for i, j in ef.values()]
        ok_d = max(abs(a_ - dih) for a_ in ang) < 1e-4
    check(f"{kind}: {nv} points {ne} edges {nf} faces, χ = 2, watertight, consistently oriented, equal edges"
          f"({L.min():.6f}~{L.max():.6f})",
          (g.npoints, t.nedges, g.nprims) == (nv, ne, nf) and x == 2 and wt
          and consistent(g) and np.ptp(L) < 1e-6)
    check(f"  points all on the unit circumsphere, faces flat regular polygons, side counts {sorted(sides)}, "
          f"dihedral angle{'' if dih is None else f' {dih:.3f}°'}",
          np.abs(np.linalg.norm(P, axis=1) - 1).max() < 1e-6 and planar < 1e-6
          and reg < 1e-6 and set(A(g, PRIM, "sides").ravel()) == sides and ok_d)
    check(f"  volume {volume(g):.6f} = analytic {vol:.6f} (positive = normals point outward)",
          abs(volume(g) - vol) < 1e-5)
soc = PL.solid("soccer_ball")
check("soccer ball: 12 pentagons + 20 hexagons",
      np.bincount(A(soc, PRIM, "sides").ravel(), minlength=7)[5:].tolist()
      == [12, 20])
g2 = PL.solid("dodecahedron", 2.5, (1, 2, 3))
check("Radius / Center: all points at distance 2.5 from (1,2,3)",
      np.abs(np.linalg.norm(Pd(g2) - [1, 2, 3], axis=1) - 2.5).max() < 1e-5)
flip = ops.reverse_prims(PL.solid("cube"), group="0") \
    if "group" in ops.reverse_prims.__code__.co_varnames else None
if flip is not None:
    check("negative control: flip one face and the orientation check goes red", not consistent(flip))
err("unknown Type raises", lambda: PL.solid("teapot"), "Type")

# ═══════════════════════════════════════════════════════ L-System
sec("L-System")
for n in (1, 3, 5):
    g, r = LS.lsystem("F", "F=F+F--F+F", n, 60, 1.0)
    P = Pd(g)
    check(f"Koch generation {n}: {4 ** n} segments, one polyline, endpoint exactly at (0, {3 ** n})",
          r["segments"] == 4 ** n and g.nprims == 1 and
          np.abs(P[-1] - [0, 3 ** n, 0]).max() < 1e-3 * 3 ** n)
g, r = LS.lsystem("F", "F=F[+F]F", 1, 30)
check("F[+F]F: 4 points, 2 polylines, the branch **shares** the fork point it starts from",
      g.npoints == 4 and g.nprims == 2 and
      len(set(g.prim_points(0).tolist()) & set(g.prim_points(1).tolist())) == 1)
g, r = LS.lsystem("F[+F]F", "", 0, 90, 1.0)
check("popping returns to the branch point's position **and orientation**: the trunk continues up to (0,2), the branch at (−1,1)",
      np.abs(Pd(g) - [[0, 0, 0], [0, 1, 0], [-1, 1, 0], [0, 2, 0]]).max() < 1e-9)
g, r = LS.lsystem("F", "F=F[+F]F", 3, 30)
check("3 generations: 27 segments; max generation 3, max depth 3",
      r["segments"] == 27 and A(g, POINT, "generation").max() == 3 and
      A(g, POINT, "depth").max() == 3)
s, gens = LS.rewrite("A", LS.parse_rules("A=AB\nB=A"), 4)
check(f"Fibonacci string: length 8, each character remembers which generation produced it ({s})",
      s == "ABAABABA" and len(gens) == 8 and max(gens) == 4)
s, _ = LS.rewrite("A" * 8000, LS.parse_rules("A=(1)B\nA=(3)C"), 1, seed=7)
pB = s.count("B") / 8000
sig = math.sqrt(0.25 * 0.75 / 8000)
check(f"random rule 1:3 -> frequency of B {pB:.4f} within 0.25 ± 4σ",
      abs(pB - 0.25) < 4 * sig)
s2, _ = LS.rewrite("A" * 8000, LS.parse_rules("A=(1)B\nA=(3)C"), 1, seed=7)
s3, _ = LS.rewrite("A" * 8000, LS.parse_rules("A=(1)B\nA=(3)C"), 1, seed=8)
check("same Seed same result, different Seed differs", s == s2 and s != s3)
g, _ = LS.lsystem("-FFFFFFFFFF", "", 0, 90, 1.0, gravity=0.3)
P = Pd(g)
d = np.diff(P, axis=0)
check("Gravity: a branch starting horizontally droops (y decreasing monotonically) but never past vertical (x keeps advancing)",
      (d[1:, 1] < 0).all() and (d[:, 0] > -1e-9).all() and P[-1, 1] < -1)
g0, _ = LS.lsystem("-FFFFFFFFFF", "", 0, 90, 1.0)
check("  negative control: straight when Gravity = 0", np.abs(Pd(g0)[:, 1]).max() < 1e-9)
g, _ = LS.lsystem("F&F^F", "", 0, 90, 1.0)
check("& pitch down: the second step leaves the XY plane (3D turtle)", abs(Pd(g)[2, 2]) > 0.99)
g, r = LS.lsystem("FFJ", "", 0, 30)
lv = A(g, POINT, "orient")
from comfyui_pcg.geo.xform import quat_to_mat   # noqa: E402
Mq = quat_to_mat(lv[-1:].astype(np.float64))[0]
check("leaf points: in the leaves group, name = J, orient turns +Z to N (current heading +Y)",
      g.get_group(POINT, "leaves")[-1] and A(g, POINT, "name")[-1, 0] == "J"
      and np.allclose(Mq @ [0, 0, 1], [0, 1, 0], atol=1e-6))
ga, _ = LS.lsystem("F+F+F", "", 0, 30, angle_variance=10, seed=1)
gb, _ = LS.lsystem("F+F+F", "", 0, 30, angle_variance=10, seed=1)
gc, _ = LS.lsystem("F+F+F", "", 0, 30, angle_variance=10, seed=2)
check("Angle Variance: reproducible, different seed differs",
      np.array_equal(Pd(ga), Pd(gb)) and not np.array_equal(Pd(ga), Pd(gc)))
err("string longer than Max Symbols raises (stating the actual length)",
    lambda: LS.lsystem("F", "F=FFFFF", 10, max_symbols=10000), "Max Symbols")
err("extra ']' raises", lambda: LS.lsystem("F]F", "", 0), "']'")
err("rule without '=' raises", lambda: LS.lsystem("F", "FF", 1), "=")

# ═══════════════════════════════════════════════════════ Font
sec("Font")
DV = FT.find_font("DejaVuSans")
check("DejaVuSans can be found (ships with matplotlib, present on both machines)", DV is not None, DV)
if DV:
    go, _ = FT.font("O", DV, 1.0, "outline")
    cs = [Pd(go)[go.prim_points(i)][:, :2] for i in range(go.nprims)]
    hole = A(go, PRIM, "hole").ravel()
    o_ = np.argsort(hole)                          # outer contour first (order in the font is arbitrary)
    cs = [cs[i] for i in o_]
    ar = [shoelace(c) for c in cs]
    check("outline: \"O\" has two contours, the outer one counter-clockwise (area > 0), the hole clockwise (hole = 1)",
          go.nprims == 2 and sorted(hole.tolist()) == [0, 1] and ar[0] > 0 > ar[1])
    gf, rf = FT.font("O", DV, 1.0, "faces")
    fa = area(gf)
    exp = ar[0] + ar[1]
    check(f"faces: filled area {fa:.6f} = outer contour − hole {exp:.6f}", abs(fa - exp) < 1e-6)
    from fontTools.pens.areaPen import AreaPen    # noqa: E402
    fnt = FT._load(DV)
    ap = AreaPen(fnt.getGlyphSet())
    fnt.getGlyphSet()[fnt.getBestCmap()[ord("O")]].draw(ap)
    exact = abs(ap.value) / fnt["head"].unitsPerEm ** 2
    g32, _ = FT.font("O", DV, 1.0, "faces", curve_segments=32)
    check(f"area with 32 subdivisions {area(g32):.6f} ≈ fontTools' exact Bézier integral "
          f"{exact:.6f} (relative diff {abs(area(g32) / exact - 1):.1e})",
          abs(area(g32) / exact - 1) < 5e-4)
    T, _, _ = tri_soup(gf)
    C = Pd(gf)[T].mean(1)[:, :2]
    inner = cs[1]
    check("  not a single triangle in the hole", not any(FT._inside(c, inner) for c in C))
    ge, re_ = FT.font("OBL8", DV, 1.0, "extrude", 0.3)
    x, wt = euler(ge)
    per = {}
    for ch in "OBL8":
        m = A(ge, PRIM, "char").ravel() == ch
        from comfyui_pcg.geo.ops import delete_prims   # noqa: E402
        sub = delete_prims(ge, m)
        per[ch] = euler(sub)[0]
    check(f"extrude \"OBL8\": watertight, consistently oriented; per glyph χ = 2 − 2·holes {per}",
          wt and consistent(ge) and per == {"O": 0, "B": -2, "L": 2, "8": -2})
    gfa, _ = FT.font("OBL8", DV, 1.0, "faces")
    check(f"  volume {volume(ge):.6f} = area × thickness {area(gfa) * 0.3:.6f}",
          abs(volume(ge) - area(gfa) * 0.3) < 1e-5)
    check("  the front / back / side prim groups cover all faces",
          (ge.get_group(PRIM, "front").astype(int) +
           ge.get_group(PRIM, "back").astype(int) +
           ge.get_group(PRIM, "side").astype(int) == 1).all())
    g1, r1 = FT.font("HH", DV, 1.0, "faces")
    g2_, r2 = FT.font("HH", DV, 1.0, "faces", tracking=0.25)
    check(f"Tracking 0.25: width grows by 0.25 em ({r1['width']:.4f} -> {r2['width']:.4f})",
          abs(r2["width"] - r1["width"] - 0.25) < 1e-9)
    g3, _ = FT.font("HH", DV, 2.5, "faces")
    check("Size ×2.5: all coordinates ×2.5", np.abs(Pd(g3) - 2.5 * Pd(g1)).max() < 1e-5)
    check("baseline: the bottom of H is exactly at y = 0", abs(Pd(g1)[:, 1].min()) < 1e-6)
    gl, _ = FT.font("HH", DV, 1.0, "faces", halign="left")
    gr, _ = FT.font("HH", DV, 1.0, "faces", halign="right")
    gc_, _ = FT.font("HH", DV, 1.0, "faces", halign="center")
    w = r1["width"]
    check("alignment: right = left shifted left by one line width, center by half",
          np.abs(Pd(gr)[:, 0] - (Pd(gl)[:, 0] - w)).max() < 1e-5 and
          np.abs(Pd(gc_)[:, 0] - (Pd(gl)[:, 0] - w / 2)).max() < 1e-5)
    gm, rm = FT.font("H\nH", DV, 1.0, "faces", line_spacing=1.5)
    ln = A(gm, PRIM, "line").ravel()
    y0 = Pd(gm)[np.unique(np.concatenate([gm.prim_points(i) for i in
                                          np.nonzero(ln == 0)[0]]))][:, 1].min()
    y1 = Pd(gm)[np.unique(np.concatenate([gm.prim_points(i) for i in
                                          np.nonzero(ln == 1)[0]]))][:, 1].min()
    hh0 = FT._load(DV)["hhea"]
    lh = (hh0.ascent - hh0.descent + hh0.lineGap) / FT._load(DV)["head"].unitsPerEm
    check(f"two lines: the second is lower by (ascent − descent + lineGap) × 1.5 = {lh * 1.5:.4f}"
          f"({y0 - y1:.4f})",
          abs((y0 - y1) - 1.5 * lh) < 1e-5 and set(ln) == {0, 1})
    gt, _ = FT.font("H", DV, 1.0, "faces", valign="top")
    hh = FT._load(DV)["hhea"]
    upm = FT._load(DV)["head"].unitsPerEm
    check("valign top: the highest point does not go above the ascent line y = 0",
          Pd(gt)[:, 1].max() <= 1e-6 and
          abs(Pd(gt)[:, 1].min() + hh.ascent / upm) < 1e-5)
    prev = None
    errs = []
    for sgm in (2, 4, 8, 16):
        gq, _ = FT.font("O", DV, 1.0, "faces", curve_segments=sgm)
        errs.append(area(gq))
    dif = np.abs(np.diff(errs))
    check(f"doubling Curve Segments shrinks the area change to about 1/4 each time (second-order convergence: "
          f"{np.round(dif, 6).tolist()})",
          dif[1] < dif[0] / 3 and dif[2] < dif[1] / 3)
    gn, rn = FT.font("A͸B", DV, 1.0, "faces", fallback="")
    check("glyphs missing from the font: skipped, listed in the report, other glyphs drawn as usual",
          rn["missing"] == "͸" and set(A(gn, PRIM, "char").ravel()) ==
          {"A", "B"})
    idx = A(gn, PRIM, "char_index").ravel()
    check("  char_index follows the position in the text (missing glyphs also take an index): A=0, B=2",
          set(idx) == {0, 2})
    otf = []
    for f_ in sorted(FT._font_files()):
        if f_.lower().endswith(".otf"):
            try:
                cm_ = FT._load(f_).getBestCmap() or {}
            except Exception:                     # noqa: BLE001
                continue
            if all(ord(ch) in cm_ for ch in "ab8o"):
                otf.append(f_)
                break
    if otf:
        fo = FT._load(otf[0])
        apo = AreaPen(fo.getGlyphSet())
        fo.getGlyphSet()[fo.getBestCmap()[ord("o")]].draw(apo)
        ex_o = abs(apo.value) / fo["head"].unitsPerEm ** 2
        go32, _ = FT.font("o", otf[0], 1.0, "faces", curve_segments=64)
        check(f"CFF cubic Bézier: area with 64 subdivisions ≈ exact integral (relative diff "
              f"{abs(area(go32) / ex_o - 1):.1e})", abs(area(go32) / ex_o - 1) < 5e-4)
        gco, _ = FT.font("ab8", otf[0], 1.0, "extrude", 0.2)
        check(f"CFF (cubic Bézier) font {os.path.basename(otf[0])}: extrusion watertight, consistently oriented",
              euler(gco)[1] and consistent(gco))
    else:
        check("(no .otf found on this machine, CFF font case skipped)", True)
    cjk = FT.find_font("msyh") or FT.find_font("NotoSansCJK")
    if cjk:
        gz, rz = FT.font("中文", cjk, 1.0, "extrude", 0.2)
        check(f"Chinese ({os.path.basename(cjk)}): extrusion watertight, consistently oriented",
              euler(gz)[1] and consistent(gz) and not rz["missing"])
    else:
        check("(no Chinese font found on this machine, skipped)", True)
err("font not found raises (stating the directories searched)",
    lambda: FT.font("A", "no_such_font_xyz"), "not found")
err("extrude with Depth ≤ 0 raises", lambda: FT.font("A", "", 1, "extrude", 0),
    "Depth")

# ═══════════════════════════════════════════════════════ Lattice
sec("Lattice")
geo = build.sphere(1.0, 24, 16)
geo = ops.compute_normals(geo, add_to="point")
P0 = Pd(geo)
for interp in DF.LATTICE_INTERP:
    lat = DF.lattice_from_bound(geo, (3, 2, 4))
    o = DF.lattice(geo, lat, None, interp)
    check(f"{interp}: lattice unmoved -> geometry unmoved (diff {np.abs(Pd(o) - P0).max():.1e})",
          np.abs(Pd(o) - P0).max() < 1e-6)
    M = np.array([[1.2, 0.3, 0.0], [-0.2, 0.9, 0.4], [0.1, 0.0, 1.5]])
    tt = np.array([0.5, -1.0, 2.0])
    lat2 = lat.copy()
    lat2.set(POINT, "P", (Pd(lat) @ M.T + tt).astype(np.float32))
    o = DF.lattice(geo, lat2, None, interp)
    check(f"  affine lattice as a whole -> geometry exactly affine (linear precision, diff "
          f"{np.abs(Pd(o) - (P0 @ M.T + tt)).max():.1e})",
          np.abs(Pd(o) - (P0 @ M.T + tt)).max() < 1e-5)
cloud = Geometry.from_points(rng.random((4000, 3)) * 2 - 1)
P0c = Pd(cloud)
lat = DF.lattice_from_bound(cloud, (4, 4, 4))
Pl = Pd(lat)
k = 2 + 5 * (2 + 5 * 2)                           # the middle control point (2,2,2)
lat3 = lat.copy()
Pm = Pl.copy()
Pm[k] += [0, 0.3, 0]
lat3.set(POINT, "P", Pm.astype(np.float32))
o = DF.lattice(cloud, lat3, None, "trilinear")
moved = np.abs(Pd(o) - P0c).max(1) > 1e-6          # P is float32, 1e-8 is rounding
lo, hi = Pl.min(0), Pl.max(0)
cell = (hi - lo) / 4
near = np.all(np.abs(P0c - Pl[k]) < cell, axis=1)
check(f"trilinear is local: only points in the 8 cells around the middle control point moved ({moved.sum()} of them, all inside)",
      moved.any() and not (moved & ~near).any())
o = DF.lattice(cloud, lat3, None, "bezier")
check("  control: bezier is global, the same change moves almost every point",
      (np.abs(Pd(o) - P0c).max(1) > 1e-6).mean() > 0.9)
lat2 = DF.lattice_from_bound(geo, (2, 2, 2))
Pl2 = Pd(lat2)
Pm = Pl2.copy()
Pm[13] += [0.2, -0.1, 0.4]                        # (1,1,1)
lat4 = lat2.copy()
lat4.set(POINT, "P", Pm.astype(np.float32))
o = DF.lattice(geo, lat4, None, "bezier")
s_ = (P0 - Pl2.min(0)) / (Pl2.max(0) - Pl2.min(0))
b = 8 * np.prod(s_ * (1 - s_), axis=1)
check("bezier 2×2×2: moving the middle point by δ -> displacement exactly = δ·8s(1−s)t(1−t)u(1−u)",
      np.abs(Pd(o) - P0 - b[:, None] * [0.2, -0.1, 0.4]).max() < 1e-5)
big = build.box((3, 3, 3), divisions=(4, 4, 4))
latS = DF.lattice_from_bound(build.box((1, 1, 1)), (2, 2, 2))
latT = latS.copy()
latT.set(POINT, "P", (Pd(latS) + [0, 1, 0]).astype(np.float32))
ok_ = DF.lattice(big, latT, None, "trilinear", "keep")
od_ = DF.lattice(big, latT, None, "trilinear", "deform")
out_ = np.any(np.abs(Pd(big)) > 0.5 + 1e-6, axis=1)
check("Outside = keep: points outside the lattice unmoved; deform: translation extrapolated exactly to outside points",
      np.abs(Pd(ok_)[out_] - Pd(big)[out_]).max() < 1e-9 and
      np.abs(Pd(od_) - (Pd(big) + [0, 1, 0])).max() < 1e-5)
R90 = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float)
latR = lat2.copy()
latR.set(POINT, "P", (Pd(lat2) @ R90.T).astype(np.float32))
o = DF.lattice(geo, latR, None, "trilinear")
check("normals: lattice rotated 90°, N rotates along",
      np.abs(A(o, POINT, "N") - A(geo, POINT, "N") @ R90.T).max() < 1e-4)
err("lattice not made by Lattice From Bound raises",
    lambda: DF.lattice(geo, build.box(), None), "lattice_div")
bad = DF.lattice_from_bound(geo, (2, 2, 2))
bad = ops.delete_points(bad, np.arange(bad.npoints) > 0)
err("lattice with deleted points raises", lambda: DF.lattice(geo, bad, None), "must not be added or removed")

# ═══════════════════════════════════════════════════════ Point Deform
sec("Point Deform")
rest = Geometry.from_points(rng.random((300, 3)) * 2 - 1)
hi_ = ops.compute_normals(build.sphere(0.8, 32, 20), add_to="point")
Ph = Pd(hi_)
ang = 0.7
Rz = np.array([[math.cos(ang), -math.sin(ang), 0], [math.sin(ang),
              math.cos(ang), 0], [0, 0, 1]])
dfm = Geometry.from_points(Pd(rest) @ Rz.T + [0.3, -0.2, 1.0])
o, r = DF.point_deform(hi_, rest, rest)
check("deformed = rest -> unmoved", np.abs(Pd(o) - Ph).max() < 1e-6)
o, r = DF.point_deform(hi_, rest, dfm, 8, "rigid")
e_r = np.abs(Pd(o) - (Ph @ Rz.T + [0.3, -0.2, 1.0])).max()
check(f"rigid: low-res mesh rotated 40° + translated as a whole -> high-res mesh transformed exactly the same (diff {e_r:.1e})",
      e_r < 1e-5)
check("  normals rotate along",
      np.abs(A(o, POINT, "N") - A(hi_, POINT, "N") @ Rz.T).max() < 1e-5)
o, r = DF.point_deform(hi_, rest, dfm, 8, "translate")
e_t = np.abs(Pd(o) - (Ph @ Rz.T + [0.3, -0.2, 1.0])).max()
check(f"  negative control: translate only blends displacements, drifts as soon as it rotates ({e_t:.3f})", e_t > 0.05)
dT = Geometry.from_points(Pd(rest) + [1, 2, 3])
o, _ = DF.point_deform(hi_, rest, dT, 8, "translate")
check("pure translation: translate is exact too", np.abs(Pd(o) - (Ph + [1, 2, 3])).max() < 1e-5)
wob = Geometry.from_points(Pd(rest) + rng.normal(0, 0.1, (300, 3)))
line_ = Geometry.from_points(np.c_[np.linspace(-0.8, 0.8, 4001),
                                   np.full(4001, 0.1), np.full(4001, -0.05)])
o, _ = DF.point_deform(line_, rest, wob, 8, "rigid")
jump = np.linalg.norm(np.diff(Pd(o), axis=0), axis=1).max()
check(f"continuous when neighbours change: 4000 steps along a line (step 4e-4), max jump between adjacent outputs {jump:.1e}"
      f" (only a jump on the order of the 0.1 perturbation would count)", jump < 0.01)
err("rest / deformed with different point counts raises",
    lambda: DF.point_deform(hi_, rest, Geometry.from_points(np.zeros((3, 3)))),
    "correspond one to one")

# ═══════════════════════════════════════════════════════ Blend Shapes
sec("Blend Shapes")
base = ops.compute_normals(build.sphere(1, 16, 10), add_to="point")
Pb = Pd(base)
t1 = base.copy()
t1.set(POINT, "P", (Pb * [1.5, 1, 1]).astype(np.float32))
t2 = base.copy()
t2.set(POINT, "P", (Pb + [0, 0.5, 0]).astype(np.float32))
o, _ = DF.blend_shapes(base, [t1, t2], [0.5, 0.25], "additive", attributes="P")
check("additive:base + 0.5(t1 − base) + 0.25(t2 − base)",
      np.abs(Pd(o) - (Pb + 0.5 * (Pd(t1) - Pb) + 0.25 * (Pd(t2) - Pb))).max()
      < 1e-6)
o0, _ = DF.blend_shapes(base, [t1], [0.0])
o1, _ = DF.blend_shapes(base, [t1], [1.0])
check("weight 0 = base, 1 = target", np.abs(Pd(o0) - Pb).max() < 1e-7 and
      np.abs(Pd(o1) - Pd(t1)).max() < 1e-7)
o, _ = DF.blend_shapes(base, [t1, t2], mode="sequential", blend=1.5)
check("sequential 1.5 = exactly midway between t1 and t2",
      np.abs(Pd(o) - 0.5 * (Pd(t1) + Pd(t2))).max() < 1e-6)
o, _ = DF.blend_shapes(base, [t1, t2], mode="sequential", blend=0.0)
check("sequential 0 = base", np.abs(Pd(o) - Pb).max() < 1e-7)
tn = base.copy()
tn.set(POINT, "N", -A(base, POINT, "N") + 0.3)
o, _ = DF.blend_shapes(base, [tn], [0.4])
check("N is unit length after blending", np.abs(np.linalg.norm(A(o, POINT, "N"), axis=1) - 1).max()
      < 1e-5)
bi = base.copy()
bi.set(POINT, "id", np.arange(base.npoints, dtype=np.int32))
perm = rng.permutation(base.npoints)
tp = ops.sort_geo(t1, point_mode="none") if False else None
tp = Geometry.from_points(Pd(t1)[perm])
tp.set(POINT, "id", perm.astype(np.int32))
op_, _ = DF.blend_shapes(bi, [tp], [0.5], match="id", attributes="P")
check("correspondence by id: still matches when the target's point order is shuffled",
      np.abs(Pd(op_) - (Pb + 0.5 * (Pd(t1) - Pb))).max() < 1e-6)
err("different point counts raise", lambda: DF.blend_shapes(base, [build.box()], [1]), "same topology")

# ═══════════════════════════════════════════════════════ Transform Pieces
sec("Transform Pieces")
pcs = []
cen = np.array([[-3, 0, 0], [0, 0, 0], [3, 0, 0.]])
for i, c in enumerate(cen):
    b_ = ops.compute_normals(build.box((1, 1, 1), center=tuple(c)), add_to="point")
    b_.set_string(PRIM, "name", np.array([f"p{i}"] * b_.nprims))
    pcs.append(b_)
geo3 = ops.merge(*pcs)
rest3 = Geometry.from_points(cen)
rest3.set_string(POINT, "name", np.array(["p0", "p1", "p2"]))
rest3p = rest3.copy()
rest3p.set(POINT, "pivot", np.full((3, 3), 0.4, np.float32))
rest3p.set(POINT, "orient", np.tile([0, 0.6, 0, 0.8], (3, 1)).astype(np.float32))
o, r = DF.transform_pieces(geo3, rest3p, rest3p)
check("rest = template -> unmoved (also with pivot and orient)",
      np.abs(Pd(o) - Pd(geo3)).max() < 1e-5)


def quat_axis(ax, a):
    ax = np.asarray(ax, float) / np.linalg.norm(ax)
    return np.r_[ax * math.sin(a / 2), math.cos(a / 2)]


qs = np.array([quat_axis([0, 1, 0], 0.5), quat_axis([1, 0, 0], 1.0),
               quat_axis([1, 1, 0], -0.8)])
tmpl = Geometry.from_points(cen + [[0, 1, 0], [0, 0, 2], [1, 1, 1]])
tmpl.set_string(POINT, "name", np.array(["p0", "p1", "p2"]))
tmpl.set(POINT, "orient", qs.astype(np.float32))
o, r = DF.transform_pieces(geo3, tmpl, rest3)
Rm = quat_to_mat(qs)
nm_ = A(geo3, PRIM, "name").ravel()
exp = Pd(geo3).copy()
expN = A(geo3, POINT, "N").astype(np.float64).copy()
vp = geo3.vertex_point
vpr = geo3.vertex_prim()
for i in range(3):
    pts_ = np.unique(vp[np.isin(vpr, np.nonzero(nm_ == f"p{i}")[0])])
    exp[pts_] = (Pd(geo3)[pts_] - cen[i]) @ Rm[i].T + Pd(tmpl)[i]
    expN[pts_] = expN[pts_] @ Rm[i].T
check("each piece = template ∘ rest⁻¹: rotates about its own rest point, moved to the template point (against hand-computed values)",
      np.abs(Pd(o) - exp).max() < 1e-5)
check("  normals rotate with their own piece", np.abs(A(o, POINT, "N") - expN).max() < 1e-5)
tsc = rest3.copy()
tsc.set(POINT, "scale", np.tile([1, 3, 1], (3, 1)).astype(np.float32))
o, _ = DF.transform_pieces(geo3, tsc, rest3)
Ns = A(geo3, POINT, "N").astype(np.float64) / [1, 3, 1]
Ns /= np.linalg.norm(Ns, axis=1, keepdims=True)
check("non-uniform scale (1,3,1): point y stretched 3x, normals use the inverse transpose (not stretched along)",
      np.abs(A(o, POINT, "N") - Ns).max() < 1e-5)
tm2 = Geometry.from_points(np.array([[0, 5, 0], [1, 5, 0.]]))
tm2.set_string(POINT, "name", np.array(["p0", "p1"]))
o, r = DF.transform_pieces(geo3, tm2, None)
P2 = Pd(o)
c0 = P2[np.unique(vp[np.isin(vpr, np.nonzero(nm_ == "p0")[0])])]
c2 = P2[np.unique(vp[np.isin(vpr, np.nonzero(nm_ == "p2")[0])])]
check("no rest connected: piece centers placed on template points; p2 with no template point unmoved, listed in the report",
      np.abs(0.5 * (c0.min(0) + c0.max(0)) - [0, 5, 0]).max() < 1e-6 and
      np.abs(c2 - Pd(pcs[2])).max() < 1e-6 and r["unmatched"] == ["p2"])
gpt = Geometry.from_points(cen)
gpt.set_string(POINT, "name", np.array(["p0", "p1", "p2"]))
o, _ = DF.transform_pieces(gpt, tmpl, rest3)
check("name on points works too (each point is a piece)",
      np.abs(Pd(o) - Pd(tmpl)).max() < 1e-6)
err("geometry without name raises", lambda: DF.transform_pieces(build.box(), tmpl), "name")

# ═══════════════════════════════════════════════════════ Poly Bridge
sec("Poly Bridge")
bx = build.box((2, 2, 2), divisions=(4, 2, 4))
Cc = ops.prim_centers(bx)
top = (np.abs(Cc[:, 1] - 1) < 1e-6) & (np.abs(Cc[:, 0]) < 0.6) & \
    (np.abs(Cc[:, 2]) < 0.6)
bot = (np.abs(Cc[:, 1] + 1) < 1e-6) & (np.abs(Cc[:, 0]) < 0.6) & \
    (np.abs(Cc[:, 2]) < 0.6)
bx.set_group(PRIM, "top", top)
bx.set_group(PRIM, "bot", bot)
side = top.nonzero()[0]
fa_ = np.ptp(Pd(bx)[bx.prim_points(int(side[0]))], axis=0)
hole_v = fa_[0] * fa_[2] * 2
for div in (1, 4):
    o, r = PB.poly_bridge(bx, "top", "bot", divisions=div)
    x, wt = euler(o)
    check(f"cube tunnelled top to bottom (divisions {div}): watertight, χ = 0 (one hole), consistently oriented, "
          f"volume {volume(o):.4f} = 8 − hole {8 - hole_v:.4f}",
          wt and x == 0 and consistent(o) and abs(volume(o) - (8 - hole_v))
          < 1e-5 and r["new_points"] == 4 * (div - 1))
oh, _ = PB.poly_bridge(bx, "top", "bot", divisions=6, interpolation="hermite")
check("  hermite tunnel: automatically goes inward along the normal, never shoots outward first (|y| ≤ 1), still watertight"
      " and consistently oriented", np.abs(Pd(oh)[:, 1]).max() <= 1 + 1e-6 and euler(oh)[1]
      and consistent(oh))
check("  new faces in the bridge group, both caps deleted",
      o.get_group(PRIM, "bridge").sum() == 16 and o.nprims == bx.nprims - 2 + 16)
lf = (np.abs(Cc[:, 1] - 1) < 1e-6) & (Cc[:, 0] < -0.6) & (np.abs(Cc[:, 2]) < 0.6)
rt = (np.abs(Cc[:, 1] - 1) < 1e-6) & (Cc[:, 0] > 0.6) & (np.abs(Cc[:, 2]) < 0.6)
bx.set_group(PRIM, "l", lf)
bx.set_group(PRIM, "r", rt)
o, r = PB.poly_bridge(bx, "l", "r", divisions=8, interpolation="hermite")
x, wt = euler(o)
check(f"hermite handle between two faces on the same side: arches outward (max y = {Pd(o)[:, 1].max():.3f} > 1), "
      f"watertight, χ = 0, consistently oriented, volume increases",
      Pd(o)[:, 1].max() > 1.2 and wt and x == 0 and consistent(o) and
      volume(o) > 8)
bb = build.box((2, 2, 2), divisions=(6, 6, 6))
Cb = ops.prim_centers(bb)
nr = lambda v, t_: np.abs(v - t_) < 0.1              # noqa: E731
zf = nr(Cb[:, 2], 1) & nr(Cb[:, 1], 0)
bb.set_group(PRIM, "l", zf & nr(Cb[:, 0], -0.4))
bb.set_group(PRIM, "r", zf & nr(Cb[:, 0], 0.4))
oh2, rh2 = PB.poly_bridge(bb, "l", "r", divisions=8, interpolation="hermite")
Ph2 = Pd(oh2)
mid = Ph2[bb.npoints + 3 * 4: bb.npoints + 4 * 4]    # the 4th intermediate ring (exact middle)
el = np.linalg.norm(mid - np.roll(mid, -1, 0), axis=1)
check(f"handle between small single-cell faces: the middle ring is still a square of side 0.4 (four edges "
      f"{np.round(el, 4).tolist()}) -- the cross-section is transported along the bridge before pairing, no twist",
      np.ptp(el) < 1e-6 and abs(el[0] - 0.4) < 1e-6 and consistent(oh2))
nm_mid = PB._newell(mid)
check(f"  the cross-section at the top ring turned 90°: ring normal along the bridge direction ±x (actual "
      f"{np.round(nm_mid, 4).tolist()}), the cross-section stays perpendicular to the bridge",
      abs(abs(nm_mid[0]) - 1) < 1e-6)
o, _ = PB.poly_bridge(bx, "l", "r", divisions=8, interpolation="linear")
check("  control: the linear bridge hugs the top face (y ≤ 1)", Pd(o)[:, 1].max() <= 1 + 1e-6)


def square(s, y, n=4, rot=0.0):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False) + rot + np.pi / 4
    return np.c_[s * np.cos(a), np.full(n, y), s * np.sin(a)]


Pq = np.vstack([square(1.0, 0), square(0.5, 1.5)])
gq = Geometry.from_mesh(Pq, [[0, 1, 2, 3], [7, 6, 5, 4]], closed=True)
gq.set_group(PRIM, "a", np.array([True, False]))
gq.set_group(PRIM, "b", np.array([False, True]))
o, _ = PB.poly_bridge(gq, "a", "b", remove_caps=False)
A1, A2 = 2.0, 0.5
vf = 1.5 / 3 * (A1 + A2 + math.sqrt(A1 * A2))
x, wt = euler(o)
check(f"two similar squares + bridge (caps kept): closed, consistently oriented, volume = frustum formula {vf:.4f}"
      f"({volume(o):.4f})", wt and x == 2 and consistent(o) and
      abs(volume(o) - vf) < 1e-5)
o, r0 = PB.poly_bridge(gq, "a", "b", remove_caps=False, twist=0)
o1_, r1_ = PB.poly_bridge(gq, "a", "b", remove_caps=False, twist=1)
check("Twist = 1: starting point shifted by one more point", (r1_["offset"] - r0["offset"]) % 4 == 1)
Pu = np.vstack([square(1.0, 0, 8), square(0.6, 1.0, 5)])
gu = Geometry.from_mesh(Pu, [list(range(8)), list(range(12, 7, -1))], closed=True)
gu.set_group(PRIM, "a", np.array([True, False]))
gu.set_group(PRIM, "b", np.array([False, True]))
for div in (1, 3):
    o, r = PB.poly_bridge(gu, "a", "b", divisions=div, remove_caps=False)
    x, wt = euler(o)
    check(f"loops of 8 and 5 points (divisions {div}): zipped into triangles, closed, consistently oriented, "
          f"positive volume", wt and x == 2 and consistent(o) and volume(o) > 0)
Pl_ = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [0, 0, 1], [1, 0, 1], [2, 0, 1],
                [3, 0, 1.]])
gl_ = Geometry.from_mesh(Pl_, [[0, 1, 2], [6, 5, 4, 3]], closed=False)
gl_.set_group(PRIM, "a", np.array([True, False]))
gl_.set_group(PRIM, "b", np.array([False, True]))
o, r = PB.poly_bridge(gl_, "a", "b")
nb = o.get_group(PRIM, "bridge")
sub = ops.delete_prims(o, nb)
check(f"two open polylines (3 points, 4 points, opposite directions): ruled surface area = trapezoid 2.5"
      f"({area(sub):.4f})", abs(area(sub) - 2.5) < 1e-6)


def frame(y, flip):
    o_ = square(1.0, y, 4, 0)
    i_ = square(0.4, y, 4, 0)
    P_ = np.vstack([o_, i_])
    F_ = [[0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    if flip:
        F_ = [f[::-1] for f in F_]
    return P_, F_


P1_, F1 = frame(0.0, False)                      # the lower frame faces −y
P2_, F2 = frame(1.0, True)                       # the upper one faces +y
gh = Geometry.from_mesh(np.vstack([P1_, P2_]), F1 + [[v + 8 for v in f]
                                                    for f in F2], closed=True)
m1 = np.zeros(16, bool)
m1[4:8] = True
m2 = np.zeros(16, bool)
m2[12:16] = True
gh.set_group(POINT, "h1", m1)
gh.set_group(POINT, "h2", m2)
o, r = PB.poly_bridge(gh, "h1", "h2", divisions=2)
t = topology(o)
cnt = Counter()
for i in range(o.nprims):
    v_ = o.prim_points(i).tolist()
    for a_, b_ in zip(v_, v_[1:] + v_[:1]):
        cnt[(a_, b_)] += 1
check("point groups select hole boundaries: a tube bridged between two frames with holes, orientation matches the frames (no edge used twice"
      " in the same direction), only the 8 outer border edges remain as boundary", max(cnt.values()) == 1 and
      int((t.edge_count == 1).sum()) == 8 and int((t.edge_count > 2).sum()) == 0
      and r["new_points"] == 4)
gl2 = Geometry.from_mesh(Pl_, [[0, 1, 2], [3, 4, 5, 6]], closed=False)
gl2.set_group(PRIM, "a", np.array([True, False]))
gl2.set_group(PRIM, "b", np.array([False, True]))
o, r = PB.poly_bridge(gl2, "a", "b")
sub2 = ops.delete_prims(o, o.get_group(PRIM, "bridge"))
ed2 = set()
for i in np.nonzero(o.get_group(PRIM, "bridge"))[0]:
    v_ = o.prim_points(i).tolist()
    ed2 |= {tuple(sorted(e_)) for e_ in zip(v_, v_[1:] + v_[:1])}
check(f"  two polylines in the same direction: also aligned end to end automatically (start to start 0–3, end to end 2–6, area 2.5: "
      f"{area(sub2):.4f})",
      abs(area(sub2) - 2.5) < 1e-6 and (0, 3) in ed2 and (2, 6) in ed2)
err("empty group raises", lambda: PB.poly_bridge(bx, "", "bot"), "Source Group")
err("two loops sharing points raises", lambda: PB.poly_bridge(gq, "a", "a"), "share points")
err("one loop closed and the other open raises",
    lambda: PB.poly_bridge(ops.merge(gq, gl_), "a", "b"), "")

# ═══════════════════════════════════════════════════════ Nodes
sec("Nodes")
NEW = {"PCG_PlatonicSolids": "PCG/generate", "PCG_LSystem": "PCG/generate",
       "PCG_Font": "PCG/generate", "PCG_LatticeFromBound": "PCG/deform",
       "PCG_Lattice": "PCG/deform", "PCG_PointDeform": "PCG/deform",
       "PCG_BlendShapes": "PCG/deform", "PCG_TransformPieces": "PCG/deform",
       "PCG_PolyBridge": "PCG/modify"}
check("all 9 nodes registered, in the right category",
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
    kw.update({k: v for k, v in over.items() if k not in kw})
    return kw


latn = DF.lattice_from_bound(geo, (2, 2, 2))
runs = {
    "PCG_PlatonicSolids": dict(),
    "PCG_LSystem": dict(),
    "PCG_Font": dict(font=DV or ""),
    "PCG_LatticeFromBound": dict(geo=geo),
    "PCG_Lattice": dict(geo=geo, lattice=latn),
    "PCG_PointDeform": dict(geo=hi_, rest=rest, deformed=dfm),
    "PCG_BlendShapes": dict(base=base, target1=t1, target2=t2),
    "PCG_TransformPieces": dict(geo=geo3, template=tmpl, rest=rest3),
    "PCG_PolyBridge": dict(geo=bx, source_group="top", dest_group="bot"),
}
bad = []
for k, kw in runs.items():
    try:
        r = unwrap(MAP[k]().run(**defaults(MAP[k], **kw)))
        if not isinstance(r[0], Geometry) or (len(r) > 1 and isinstance(
                r[-1], str) and not json.loads(r[-1])):
            bad.append(k)
    except Exception as ex:                       # noqa: BLE001
        bad.append(f"{k}: {ex}")
check("all 9 nodes run with default parameters (with the required inputs filled in)", not bad, bad)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
