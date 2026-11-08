"""
pcg100 audit pack c4_pattern_shape: COP shapes / patterns added after checking the SideFX docs.

  SDF Shape    PCG_COPShape: new shapes (Polygon / Squircle / Trapezoid / Triangle / Diamond /
               Egg / Moon / Vesica / Cross / Arch / Arrow), Circle's Arc / Thickness /
               Round Ends, Rectangle with separate corner radii, Line with different thickness at each end, Shear / Uniform Scale
  UV Shape     new node PCG_COPUVShape: Disk (Linear / Polar / Equal Area / Squircle /
               Elliptic Arc), Annulus (Polar / Log), Transform, U/V Border, U/V Scale,
               uvscale, mask
  Tile Pattern Bond of PCG_COPPattern (kind = tile): Stack / Stretcher / Header / Flemish /
               English / American
  Chladni      Output Mode (Nodal Lines threshold version / Absolute / Signed), Amplitude, Amplitude Ratio,
               Threshold, Smoothing Width
  Cell Pattern Metric (Euclidean / Manhattan / Chebyshev), Lattice Type (Grid / Hexagonal),
               Density / Density Seed
  UV Grid      Tile Coloring (Uniform / Checker / Gradient), Outlines (toggle / width / color),
               Marker Type (Text / Cross / Arrow), Text Mode, Marker Size, Marker Coloring
  Weave        Weave Type gains Custom (over/under layout from an image layer, Houdini's pattern input),
               separate warp / weft widths (Row / Column Inset)

References are all distances that can be worked out by hand (polygon apothem, circle radius, corner distances …). "Bit-identical
to before the change at defaults" uses digests of the same set of calls before the change (commit c87c5d9), hard-coded in GOLDEN (arrays rounded to
5 decimals before hashing, to dodge last-digit libm differences between machines); `--digests` prints the current digests. Doesn't depend on git.
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
from comfyui_pcg.panel_specs import SPECS               # noqa: E402
from comfyui_pcg.geo.cop import sdf2d as F, generate as G, uvshape as US  # noqa: E402
from comfyui_pcg.geo.cop import pattern as PT                 # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def near(a, b, tol=1e-9):
    return abs(float(a) - float(b)) <= tol


def defaults(n):
    out = {}
    for k, v in M[n].INPUT_TYPES()["required"].items():
        if isinstance(v[0], list):
            out[k] = v[0][0]
        elif len(v) > 1 and isinstance(v[1], dict) and "default" in v[1]:
            out[k] = v[1]["default"]
    return out


def dig(im):
    h = hashlib.sha1()
    for k in sorted(im.names):
        a = np.asarray(im.need(k))
        h.update(f"{k}/{a.dtype}/{a.shape}".encode())
        h.update(np.ascontiguousarray(np.round(a.astype(np.float64), 5)
                                      + 0.0).tobytes())
    return h.hexdigest()[:16]


def at(f, *pts):
    """Evaluate an SDF at a few points (sdf2d functions take (…, 2))."""
    return f(np.asarray(pts, np.float64))


def run_shape(**kw):
    a = defaults("PCG_COPShape")
    a.update(resolution_x=64, resolution_y=64, device="exact")
    a.update(kw)
    return M["PCG_COPShape"]().run(**a)[0]


def sdf_of(**kw):
    return np.asarray(run_shape(**kw).need("sdf"))[..., 0]


def qgrid(n=64):
    """float64 pixel-center coordinates, same as the exact backend (row 0 at the bottom, v up)."""
    c = (np.arange(n, dtype=np.float64) + 0.5) / n - 0.5
    X, Y = np.meshgrid(c, c)
    ref = np.asarray(G.aspect_coords(n, n), np.float64)
    assert np.allclose(np.stack([X, Y], -1), ref, atol=1e-6)
    return np.stack([X, Y], -1)


# ═══════════════════════════════════════════════════ Regression: identical to before the change at defaults
GOLDEN = {
    "shape/circle/numpy": "bbd98ca9d97e8d6a",
    "shape/circle/exact": "a079487a8ed4a3ed",
    "shape/box/numpy": "d572ab4f66337c8d",
    "shape/box/exact": "4ea39dd12857b466",
    "shape/rounded_box/numpy": "68471545599c3278",
    "shape/rounded_box/exact": "9c3ae3eefbc63bb1",
    "shape/line/numpy": "279c9de14a8a0aa6",
    "shape/line/exact": "d35679cb3cc3c372",
    "shape/star/numpy": "cfa07401f9188d16",
    "shape/star/exact": "2708d77a22d10aca",
    "pattern/checker/0": "03d93a74ec804674",
    "pattern/tile/0": "a9509b3c812cd0ab",
    "pattern/cell/0": "dcdf3aa2bae3dd4c",
    "pattern/uv_grid/0": "62ccfea97b8e23e0",
    "pattern/julia/0": "c48d26b7e4801c3a",
    "pattern/chladni/0": "32aa242b596bb4d5",
    "pattern/chladni/1": "77e111a04d8a8478",
    "pattern/knit/0": "393676fa96212f8e",
    "pattern/weave/0": "a5ab6f10ab630cfa",
    "pattern/weave/1": "5d3c3876b3e6d2a4",
    "pattern/weave/2": "52db23e98c465cb0",
}


def current_digests():
    R = {}
    for shp in ["circle", "box", "rounded_box", "line", "star"]:
        for dev in ["numpy", "exact"]:
            kw = defaults("PCG_COPShape")
            kw.update(shape=shp, device=dev, resolution_x=48, resolution_y=40,
                      angle=17.0, color_layer="C")
            R[f"shape/{shp}/{dev}"] = dig(M["PCG_COPShape"]().run(**kw)[0])
    for kind in ["checker", "tile", "cell", "uv_grid", "julia", "chladni",
                 "knit", "weave"]:
        extra = [{}]
        if kind == "weave":
            extra = [{"weave": w} for w in ("plain", "twill", "satin")]
        if kind == "chladni":
            extra = [{}, {"sign": "+"}]
        if kind == "uv_grid":
            extra = [{"labels": False}]       # the mode with text depends on Pillow fonts, kept out of the digests
        for i, e in enumerate(extra):
            kw = defaults("PCG_COPPattern")
            kw.update(kind=kind, resolution_x=64, resolution_y=48, counts="4 3",
                      rand_seed=3, iterations=30)
            kw.update(e)
            R[f"pattern/{kind}/{i}"] = dig(M["PCG_COPPattern"]().run(**kw)[0])
    return R


if "--digests" in sys.argv:
    for k, v in current_digests().items():
        print(f'    "{k}": "{v}",')
    sys.exit(0)

sec("regression: identical to before the change at defaults (hard-coded digests)")
now = current_digests()
check(f"output digests of all {len(GOLDEN)} old calls unchanged", now == GOLDEN,
      {k: (GOLDEN.get(k), v) for k, v in now.items() if GOLDEN.get(k) != v})


# ═══════════════════════════════════════════════════ SDF Shape
sec("SDF Shape: Polygon (regular n-gon, circumradius, vertex towards +y)")
for n in (3, 5, 6):
    r = 0.4
    ap = r * np.cos(np.pi / n)
    # Odd sides: directly below is an edge (at -apothem); even sides: directly below is a vertex (at -r)
    low = ap if n % 2 else r
    d = at(lambda q: F.regular_polygon(q, r, n), (0, 0), (0, r + 0.1),
           (0, -low - 0.05), (0, r))
    check(f"n={n}: center = -apothem, 0.1 outside a vertex, 0.05 outside the edge / vertex directly below, 0 on a vertex",
          near(d[0], -ap, 1e-12) and near(d[1], 0.1, 1e-12)
          and near(d[2], 0.05, 1e-12) and near(d[3], 0, 1e-12), d)
d = sdf_of(shape="polygon", radius=0.4, points=6)
check("node: polygon reads Radius / Number of Sides (changing points changes the result)",
      not np.allclose(d, sdf_of(shape="polygon", radius=0.4, points=5)))
check("node: polygon differs from star (negative control)",
      not np.allclose(d, sdf_of(shape="star", radius=0.4, points=6)))

sec("SDF Shape:Squircle")
q = qgrid()
check("Blend = 2 is a circle (to 1e-12)",
      np.allclose(F.squircle(q, 0.3, 2.0), np.hypot(q[..., 0], q[..., 1]) - 0.3,
                  atol=1e-12))
d = at(lambda q: F.squircle(q, 0.4, 1.0), (0.2, 0.2), (0.4, 0), (0, 0))
check("Blend = 1 is a diamond |x|+|y| = r: (0.2,0.2), (0.4,0) on the edge, center = -r/√2",
      near(d[0], 0, 1e-12) and near(d[1], 0, 1e-12)
      and near(d[2], -0.4 / np.sqrt(2), 1e-12), d)
d = at(lambda q: F.squircle(q, 0.4, 40.0), (0.38, 0.38), (0.4, 0.0))
check("large Blend -> close to a square: (0.38,0.38) inside, (0.4,0) on the edge",
      d[0] < 0 and near(d[1], 0, 1e-12), d)
d = at(lambda q: F.squircle(q, 0.4, 0.5), (0.1, 0.1), (0.4, 0))
check("Blend 0.5 (concave sides, star-like): (0.1,0.1) satisfies √x+√y = √r, on the edge; (0.4,0) on the edge",
      near(d[0], 0, 1e-12) and near(d[1], 0, 1e-12), d)
check("Blend < 0.25 clamps to 0.25", np.array_equal(F.squircle(qgrid(), 0.4, 0.1),
                                             F.squircle(qgrid(), 0.4, 0.25)))
check("node: squircle_blend takes effect",
      not np.allclose(sdf_of(shape="squircle", squircle_blend=2.0),
                      sdf_of(shape="squircle", squircle_blend=6.0)))

sec("SDF Shape: Trapezoid / Triangle / Diamond (polygon SDF)")
d = at(lambda q: F.trapezoid(q, 0.4, 0.1, 0.25), (0, -0.35), (0, 0.3),
       (0.5, -0.25), (0.25, 0))
# The slanted side runs from (0.4,-0.25) to (0.1,0.25), (0.25,0) is its midpoint
check("trapezoid: 0.1 outside the bottom, 0.05 outside the top, 0.1 outside a bottom corner, 0 at the slanted side's midpoint",
      near(d[0], 0.1, 1e-12) and near(d[1], 0.05, 1e-12)
      and near(d[2], 0.1, 1e-12) and near(d[3], 0, 1e-12), d)
d = at(lambda q: F.triangle(q, (-0.3, -0.2), (0, 0.4), (0.3, -0.2)),
       (0, -0.3), (0, 0.5), (0, 0), (0.3, -0.2))
check("triangle: 0.1 outside the bottom, 0.1 above the apex, negative inside, 0 on a vertex",
      near(d[0], 0.1, 1e-12) and near(d[1], 0.1, 1e-12) and d[2] < 0
      and near(d[3], 0, 1e-12), d)
w, h = 0.4, 0.3
d = at(lambda q: F.diamond(q, w, h), (0, 0), (w, 0), (0, h + 0.1))
check("diamond: center = -wh/√(w²+h²), 0 at a vertex, 0.1 outside the top vertex",
      near(d[0], -w * h / np.hypot(w, h), 1e-12) and near(d[1], 0, 1e-12)
      and near(d[2], 0.1, 1e-12), d)
# Node: triangle Use Points
a = sdf_of(shape="triangle")
b = sdf_of(shape="triangle", use_points=True)
c = sdf_of(shape="triangle", use_points=True, tri_p1="0 0.1")
check("node: triangle uses Size by default; Use Points switches to three points (result changes), changing the points changes it too",
      not np.allclose(a, b) and not np.allclose(b, c))
check("node: changing points has no effect when Use Points is off",
      np.array_equal(a, sdf_of(shape="triangle", tri_p1="0 0.1")))
check("node: trap_top takes effect",
      not np.allclose(sdf_of(shape="trapezoid"), sdf_of(shape="trapezoid", trap_top=0.3)))
# Compare on the node at pixel centers: 64×64, pixel center (k+0.5)/64 - 0.5
qq = qgrid()
check("node: diamond's sdf layer = sdf2d.diamond(Size) per pixel (exact backend)",
      np.allclose(sdf_of(shape="diamond", size_x=0.3, size_y=0.2),
                  F.diamond(qq, 0.3, 0.2), atol=1e-12))
check("node: trapezoid = sdf2d.trapezoid(size_x, trap_top, size_y)",
      np.allclose(sdf_of(shape="trapezoid", size_x=0.3, size_y=0.2, trap_top=0.1),
                  F.trapezoid(qq, 0.3, 0.1, 0.2), atol=1e-12))
check("node: default triangle vertices = (-sx,-sy), (0,sy), (sx,-sy)",
      np.allclose(sdf_of(shape="triangle", size_x=0.3, size_y=0.2),
                  F.triangle(qq, (-0.3, -0.2), (0, 0.2), (0.3, -0.2)), atol=1e-12))
check("node: Use Points reads tri_p0/1/2 (both 'x y' and 'x,y' work)",
      np.allclose(sdf_of(shape="triangle", use_points=True, tri_p0="-0.2,-0.1",
                         tri_p1="0 0.3", tri_p2="0.25 -0.2"),
                  F.triangle(qq, (-0.2, -0.1), (0, 0.3), (0.25, -0.2)), atol=1e-12))

sec("SDF Shape: Circle's Arc / Thickness / Round Ends")
R = 0.4
d = at(lambda q: F.ring_sector(q, R, 1.0, 0.5), (0, 0), (0.3, 0), (0, 0.45))
check("Thickness 0.5: ring width 0.2 (inner radius 0.2); center +0.2, ring centerline -0.1, outside 0.05",
      near(d[0], 0.2, 1e-12) and near(d[1], -0.1, 1e-12)
      and near(d[2], 0.05, 1e-12), d)
d = at(lambda q: F.ring_sector(q, R, 0.5, 1.0), (0, 0.1), (0, -0.1), (0.2, -0.1),
       (0.5, 0.0))
check("Arc 0.5 solid = upper half disk: (0,0.1) inside -0.1, (0,-0.1) outside 0.1, (0.2,-0.1) outside 0.1, "
      "(0.5,0) outside 0.1",
      near(d[0], -0.1, 1e-12) and near(d[1], 0.1, 1e-12)
      and near(d[2], 0.1, 1e-12) and near(d[3], 0.1, 1e-12), d)
d = at(lambda q: F.ring_sector(q, R, 0.25, 1.0), (0, 0), (0.0, 0.2))
check("Arc 0.25 (quarter sector, apex at the center): center on the boundary 0, (0,0.2) to both sides 0.2·sin45°",
      near(d[0], 0, 1e-12) and near(d[1], -0.2 * np.sin(np.pi / 4), 1e-12), d)
flat = at(lambda q: F.ring_sector(q, R, 0.5, 0.5, False), (0.3, -0.05))
rnd_ = at(lambda q: F.ring_sector(q, R, 0.5, 0.5, True), (0.3, -0.05))
check("Arc 0.5 + Thickness 0.5: 0.05 below the end face -- flat end 0.05, round end -0.05 (end semicircle radius 0.1)",
      near(flat[0], 0.05, 1e-12) and near(rnd_[0], np.hypot(0, 0.05) - 0.1, 1e-12),
      (flat, rnd_))
t1, t2 = np.radians(44.95), np.radians(45.05)
d = at(lambda q: F.ring_sector(q, R, 0.25, 1.0), (0.3 * np.sin(t1), 0.3 * np.cos(t1)),
       (0.3 * np.sin(t2), 0.3 * np.cos(t2)))
check("Arc 0.25 sector: two points 0.05° from the 45° side, inside -0.3·sin0.05°, outside +0.3·sin0.05°",
      near(d[0], -0.3 * np.sin(np.radians(0.05)), 1e-12)
      and near(d[1], 0.3 * np.sin(np.radians(0.05)), 1e-12), d)
d = at(lambda q: F.ring_sector(q, R, 0.5, 0.5, False), (0.3, 0.02), (0.33, 0.05))
check("flat-ended ring sector: interior points near the end face take the distance to the end face (0.3,0.02) -> -0.02, (0.33,0.05) -> -0.05",
      near(d[0], -0.02, 1e-12) and near(d[1], -0.05, 1e-12), d)
d0 = sdf_of(shape="circle")
check("node: Arc = Thickness = 1 is the original full circle (also with Round Ends on)",
      np.array_equal(d0, sdf_of(shape="circle", round_ends=True)))
check("node: Arc < 1 / Thickness < 1 each change the result",
      not np.allclose(d0, sdf_of(shape="circle", arc=0.5))
      and not np.allclose(d0, sdf_of(shape="circle", thickness=0.5)))
check("node: with only one < 1, Round Ends has no effect (docs: only useful when both are on)",
      np.array_equal(sdf_of(shape="circle", arc=0.5),
                     sdf_of(shape="circle", arc=0.5, round_ends=True))
      and np.array_equal(sdf_of(shape="circle", thickness=0.5),
                         sdf_of(shape="circle", thickness=0.5, round_ends=True)))
check("node: with both < 1, Round Ends takes effect",
      not np.allclose(sdf_of(shape="circle", arc=0.5, thickness=0.5),
                      sdf_of(shape="circle", arc=0.5, thickness=0.5, round_ends=True)))
check("node: circle + arc reads Radius",
      np.allclose(sdf_of(shape="circle", arc=0.6, thickness=0.4, radius=0.3),
                  F.ring_sector(qq, 0.3, 0.6, 0.4), atol=1e-12))

sec("SDF Shape: Rectangle with separate corner radii (Separate Controls)")
b0 = sdf_of(shape="box")
check("node: Separate Controls on, all four corners 0 = the original sharp rectangle (to 1e-12)",
      np.allclose(b0, sdf_of(shape="box", separate_corners=True), atol=1e-12))
k = 0.4
m = min(0.35, 0.25)
check("node: all four corners = k equals rounded_box (corner = k × shorter half side)",
      np.allclose(sdf_of(shape="rounded_box", corner=k * m),
                  sdf_of(shape="box", separate_corners=True, corner_tl=k,
                         corner_tr=k, corner_bl=k, corner_br=k), atol=1e-12))
check("node: rounded_box with Separate Controls on no longer reads corner",
      np.array_equal(sdf_of(shape="rounded_box", separate_corners=True, corner=0.1),
                     sdf_of(shape="rounded_box", separate_corners=True, corner=0.02)))
d = at(lambda q: F.rounded_box4(q, (0.3, 0.2), (0.2, 0, 0, 0)),
       (0.3, 0.2), (-0.3, 0.2), (0.3, -0.2))
check("only top-right r=0.2: the top-right corner point is 0.2(√2-1) outside, the other two corners on the edge",
      near(d[0], 0.2 * (np.sqrt(2) - 1), 1e-12) and near(d[1], 0, 1e-12)
      and near(d[2], 0, 1e-12), d)
# Each corner maps to its own quadrant: with only one corner on, only that quadrant changes
for nm, (sx, sy) in {"corner_tl": (-1, 1), "corner_tr": (1, 1),
                     "corner_bl": (-1, -1), "corner_br": (1, -1)}.items():
    dd = sdf_of(shape="box", separate_corners=True, **{nm: 1.0})
    diff = ~np.isclose(dd, b0, atol=1e-12)
    ys, xs = np.nonzero(diff)
    ok = len(xs) > 0 and np.all(np.sign(qq[ys, xs, 0]) == sx) \
        and np.all(np.sign(qq[ys, xs, 1]) == sy)
    check(f"{nm} only changes its own quadrant", ok)
d = at(lambda q: F.rounded_box4(q, (0.2, 0.2), (0.2, 0.2, 0.2, 0.2)), (0.3, 0.0),
       (0.3, 0.3))
check("square with all four corners 1 -> circle: (0.3,0) outside 0.1, (0.3,0.3) outside 0.3√2 - 0.2",
      near(d[0], 0.1, 1e-12) and near(d[1], 0.3 * np.sqrt(2) - 0.2, 1e-12), d)

sec("SDF Shape: Line with different thickness at each end (Add Thickness)")
d = at(lambda q: F.uneven_capsule(q, (-0.3, 0), (0.3, 0), 0.1, 0.05),
       (-0.5, 0), (0.45, 0), (-0.3, 0.2), (0.3, -0.1))
check("start circle radius 0.1, end 0.05: 0.1 / 0.1 beyond the ends, 0.1 / 0.05 directly above/below the endpoints",
      near(d[0], 0.1, 1e-12) and near(d[1], 0.1, 1e-12)
      and abs(d[2] - 0.1) < 2e-3 and abs(d[3] - 0.05) < 2e-3, d)
d = at(lambda q: F.uneven_capsule(q, (-0.3, 0), (0.3, 0), 0.08, 0.08), (0, 0.2),
       (0.4, 0.1))
check("same thickness at both ends is a capsule: (0,0.2) 0.12, (0.4,0.1) √0.02 - 0.08",
      near(d[0], 0.12, 1e-12) and near(d[1], np.sqrt(0.02) - 0.08, 1e-12), d)
check("degenerate: one end's circle contains the other -> the bigger circle",
      near(at(lambda q: F.uneven_capsule(q, (0, 0), (0.05, 0), 0.2, 0.05), (0.5, 0))[0],
           0.3, 1e-12)
      and near(at(lambda q: F.uneven_capsule(q, (0, 0), (0.05, 0), 0.05, 0.2),
                  (0.55, 0))[0], 0.3, 1e-12))
l0 = sdf_of(shape="line")
check("node: Start/End have no effect when Add Thickness is off",
      np.array_equal(l0, sdf_of(shape="line", start_thickness=0.3)))
check("node: Add Thickness on: full widths 0.16 / 0.16 = the original radius 0.08 capsule",
      np.allclose(sdf_of(shape="line", radius=0.08),
                  sdf_of(shape="line", separate_thickness=True, start_thickness=0.16,
                         end_thickness=0.16), atol=1e-12))
check("node: different ends change the result, and line_a / line_b are read",
      np.allclose(sdf_of(shape="line", separate_thickness=True),
                  F.uneven_capsule(qq, (-0.3, 0), (0.3, 0), 0.05, 0.01), atol=1e-12))

sec("SDF Shape:Egg / Vesica / Moon")
q = qgrid()
check("Egg Roundness = 1 is a circle",
      np.allclose(F.egg(q, 0.3, 1.0), np.hypot(q[..., 0], q[..., 1]) - 0.3,
                  atol=1e-12))
d = at(lambda q: F.egg(q, 0.3, 0.0), (0, 0.3 * np.sqrt(3)), (0, -0.4), (0.4, 0))
check("Egg Roundness = 0: tip at (0, √3·r), below it a semicircle of radius r, side arcs centered (-r,0) with radius 2r",
      near(d[0], 0, 1e-12) and near(d[1], 0.1, 1e-12)
      and near(d[2], 0.7 - 0.6, 1e-12), d)
check("Vesica Roundness = 1 is a circle",
      np.allclose(F.vesica(q, 0.3, 1.0), np.hypot(q[..., 0], q[..., 1]) - 0.3,
                  atol=1e-12))
r_, rd = 0.4, 0.5
dd_ = r_ * (1 - rd)
b_ = np.sqrt(r_ * r_ - dd_ * dd_)
d = at(lambda q: F.vesica(q, r_, rd), (r_ - dd_, 0), (0, b_), (0, b_ + 0.1), (0, 0))
check("Vesica Roundness 0.5: half width = r - d, tip at (0, √(r²-d²)), 0.1 above the tip, center = -(r - d)",
      near(d[0], 0, 1e-12) and near(d[1], 0, 1e-12) and near(d[2], 0.1, 1e-12)
      and near(d[3], -(r_ - dd_), 1e-12), d)
d = at(lambda q: F.moon(q, 0.4, 0.3, 0.2), (-0.4, 0), (-0.5, 0), (0.0, 0), (-0.25, 0))
# (-0.25,0): 0.15 to the outer circle, to the carved-out circle (center 0.2) |-0.45| - 0.3 = 0.15
check("Moon outer 0.4 / inner 0.3 / offset 0.2: left end 0, 0.1 left outside, origin (carved out) +0.1, (-0.25,0) -0.15",
      near(d[0], 0, 1e-12) and near(d[1], 0.1, 1e-12) and near(d[2], 0.1, 1e-12)
      and near(d[3], -0.15, 1e-12), d)
d = at(lambda q: F.moon(q, 0.4, 0.3, -0.2), (0.4, 0), (0.0, 0))
check("Moon negative offset = mirrored (carved to the left): right end 0, origin +0.1", near(d[0], 0, 1e-12)
      and near(d[1], 0.1, 1e-12), d)
q = qgrid()
ln_ = np.hypot(q[..., 0], q[..., 1])
check("Moon offset 0 (concentric): = annulus max(|p| - outer radius, inner radius - |p|)",
      np.allclose(F.moon(q, 0.4, 0.2, 0.0), np.maximum(ln_ - 0.4, 0.2 - ln_), atol=1e-7))
check("node: moon reads Radius / Inner Radius / Inner Offset",
      np.allclose(sdf_of(shape="moon", radius=0.4, moon_inner=0.3, moon_offset=0.2),
                  F.moon(qq, 0.4, 0.3, 0.2), atol=1e-12))
check("node: egg / vesica read Roundness (changing it changes the result)",
      not np.allclose(sdf_of(shape="egg"), sdf_of(shape="egg", roundness=0.9))
      and not np.allclose(sdf_of(shape="vesica"), sdf_of(shape="vesica", roundness=0.9)))
check("node: egg and vesica are two different things (negative control)",
      not np.allclose(sdf_of(shape="egg"), sdf_of(shape="vesica")))

sec("SDF Shape:Cross(Size / Inset / Bevel)")
s, ins = 0.4, 0.25
a_ = s - ins
d = at(lambda q: F.cross(q, s, 0.0), (0.5, 0.5), (0, 0), (0.3, 0.1))
check("Inset 0 = square: (0.5,0.5) outside 0.1√2, center -0.4, (0.3,0.1) -0.1",
      near(d[0], 0.1 * np.sqrt(2), 1e-12) and near(d[1], -0.4, 1e-12)
      and near(d[2], -0.1, 1e-12), d)
check("Inset 0 matches a 0.4×0.4 sharp rectangle pixel for pixel",
      np.allclose(F.cross(qgrid(), s, 0.0), F.rounded_box4(qgrid(), (s, s), (0, 0, 0, 0)),
                  atol=1e-12))
d = at(lambda q: F.cross(q, s, ins), (0.3, 0.3), (0.5, 0), (0, 0), (a_ + 0.01, a_ + 0.01),
       (0.3, 0.0))
# Directly below (0.3,0.3) is the arm's top edge y = 0.15; the closest boundary point to the center is the inner corner (a,a);
# (a+0.01, a+0.01) is 0.01 from both arm edges
check("Inset 0.25 (arm half width 0.15): (0.3,0.3) 0.15 to the arm edge, 0.1 beyond the arm end, center -0.15√2, "
      "0.01 outside the inner corner, inside the arm (0.3,0) -0.1",
      near(d[0], 0.15, 1e-12) and near(d[1], 0.1, 1e-12)
      and near(d[2], -0.15 * np.sqrt(2), 1e-12) and near(d[3], 0.01, 1e-12)
      and near(d[4], -0.1, 1e-12), d)
r = 0.1
pa = a_ + r * (1 - 1 / np.sqrt(2))
d = at(lambda q: F.cross(q, s, ins, r), (pa, pa), (a_ + r, a_ + r), (a_ + 0.01, a_ + 0.01))
check("Bevel 0.1: the inner corner arc's midpoint is on the boundary, arc center (a+r,a+r) outside 0.1, the point outside the original inner corner is now inside",
      near(d[0], 0, 1e-12) and near(d[1], r, 1e-12) and d[2] < 0, d)
d = at(lambda q: F.cross(q, s, ins, r), (0.3, a_), (a_, 0.3), (0.3, a_ + 0.05))
check("Bevel doesn't affect arm edges far from the inner corner: (0.3,a) 0, (a,0.3) 0, (0.3,a+0.05) outside 0.05",
      near(d[0], 0, 1e-12) and near(d[1], 0, 1e-12) and near(d[2], 0.05, 1e-12), d)
check("Bevel clamped to ≤ min(Inset, arm half width): Bevel 10 equals Bevel = 0.15",
      np.allclose(F.cross(q, s, ins, 10.0), F.cross(q, s, ins, 0.15), atol=0))
d = at(lambda q: F.cross(q, s, s), (0.1, 0.2), (0.5, 0.05), (0.2, 0.0))
check("Inset ≥ Size: zero arm width, degenerates to the distance to the cross lines (two segments of length 2·Size)",
      near(d[0], 0.1, 1e-12) and near(d[1], np.hypot(0.1, 0.05), 1e-12)
      and near(d[2], 0, 1e-12), d)
k_ = 1 / np.sqrt(2)
d = at(lambda q: F.cross(q, s, ins, r), (a_ + r - (r + 5e-4) * k_, a_ + r - (r + 5e-4) * k_))
check("Bevel: 0.0005 further outward from the arc midpoint (into the fillet) -> -0.0005", near(d[0], -5e-4, 1e-12), d)
d = at(lambda q: F.cross(q, s, ins, r), (a_ + r, a_ - 0.03), (a_ + 2 * r, a_ + 0.3 * r))
check("Bevel: below the arc endpoint (a+r, a-0.03) inside the arm -0.03; up-right of the arc endpoint (a+2r, a+0.3r) to the arm edge +0.03",
      near(d[0], -0.03, 1e-12) and near(d[1], 0.3 * r, 1e-12), d)
check("node: cross reads Radius / Cross Inset / Cross Bevel",
      np.allclose(sdf_of(shape="cross", radius=0.4, cross_inset=0.25, cross_bevel=0.05),
                  F.cross(qq, 0.4, 0.25, 0.05), atol=1e-12)
      and not np.allclose(sdf_of(shape="cross"), sdf_of(shape="cross", cross_bevel=0.05)))

sec("SDF Shape:Arch / Arrow")
w = 0.5
d = at(lambda q: F.arch(q, w, 0.0), (0, 0.125), (0.25, -0.125), (0, -0.225), (0.35, -0.125))
check("Arch Height 0 = semicircle (centered by bounding box, semicircle center (0,-r/2)): top 0, bottom corners 0, below 0.1, side outside 0.1",
      near(d[0], 0, 1e-12) and near(d[1], 0, 1e-12) and near(d[2], 0.1, 1e-12)
      and near(d[3], 0.1, 1e-12), d)
d = at(lambda q: F.arch(q, 0.4, 0.4), (0, 0.3), (0.2, -0.3), (0.3, -0.4), (0.3, 0.0))
check("Arch width 0.4 height 0.4 (total height 0.6): top 0, bottom corners 0, outside the bottom corner (0.1,0.1) -> 0.1√2, side outside 0.1",
      near(d[0], 0, 1e-12) and near(d[1], 0, 1e-12)
      and near(d[2], 0.1 * np.sqrt(2), 1e-12) and near(d[3], 0.1, 1e-12), d)
d = at(lambda q: F.arrow(q, (-0.3, 0), (0.3, 0), 0.1, 0.3, 0.25), (0.3, 0), (0.4, 0),
       (-0.4, 0), (0.0, 0.1), (0.15, 0.2))
check("Arrow shaft width 0.1, head width 0.3, head length 0.15: tip 0, beyond the tip 0.1, beyond the tail 0.1, on the shaft 0.05, "
      "outside the head root 0.05",
      near(d[0], 0, 1e-12) and near(d[1], 0.1, 1e-12) and near(d[2], 0.1, 1e-12)
      and near(d[3], 0.05, 1e-12) and near(d[4], 0.05, 1e-12), d)
check("Arrow start = end: shrinks to a point, gives the distance to it",
      near(at(lambda q: F.arrow(q, (0.1, 0), (0.1, 0), 0.1, 0.3, 0.3), (0.1, 0.2))[0], 0.2,
           1e-12))
check("node: arch reads Size (width = 2·size_x, rectangle height = 2·size_y)",
      np.allclose(sdf_of(shape="arch", size_x=0.2, size_y=0.1), F.arch(qq, 0.4, 0.2),
                  atol=1e-12))
check("node: arrow reads line_a / line_b and the three arrow parameters",
      np.allclose(sdf_of(shape="arrow", arrow_shaft=0.05, arrow_head=0.2,
                         arrow_head_ratio=0.4),
                  F.arrow(qq, (-0.3, 0), (0.3, 0), 0.05, 0.2, 0.4), atol=1e-12))

sec("SDF Shape:Shear / Uniform Scale")
check("Uniform Scale 2: a circle of radius 0.15 = a circle of radius 0.3 (exact SDF)",
      np.allclose(sdf_of(shape="circle", radius=0.15, uniform_scale=2.0),
                  sdf_of(shape="circle", radius=0.3), atol=1e-12))
check("Uniform Scale also applies to the new shapes (polygon 0.2 × 2 = 0.4)",
      np.allclose(sdf_of(shape="polygon", radius=0.2, uniform_scale=2.0),
                  sdf_of(shape="polygon", radius=0.4), atol=1e-12))
sh = 0.5
ds = sdf_of(shape="box", shear=sh)
qx = qq[..., 0] - sh * qq[..., 1]
ref = F.rounded_box4(np.stack([qx, qq[..., 1]], -1), (0.35, 0.25), (0, 0, 0, 0))
check("Shear 0.5: pixel (x,y) takes the original shape's value at (x - 0.5y, y)", np.allclose(ds, ref, atol=1e-6))
check("order of Shear and Rotate: rotate first, then shear (local coordinates)",
      not np.allclose(sdf_of(shape="box", shear=sh, angle=30),
                      sdf_of(shape="box", shear=sh)))
try:
    run_shape(uniform_scale=0.0)
    check("Uniform Scale 0 raises", False)
except ValueError as e:
    check("Uniform Scale 0 raises", "Uniform Scale" in str(e))

sec("SDF Shape: backends -- new shapes agree between numpy (float32) and exact")
for shp in ("polygon", "egg", "cross", "arrow"):
    a = np.asarray(run_shape(shape=shp, device="numpy").need("sdf"))
    b = np.asarray(run_shape(shape=shp, device="exact").need("sdf"))
    check(f"{shp}: numpy backend is float32, differs from exact by < 1e-6",
          a.dtype == np.float32 and np.abs(a - b).max() < 1e-6)
im = run_shape(shape="moon", color_layer="C")
check("new shapes also output mask / color layers", {"sdf", "mask", "C"} <= set(im.names))

sec("SDF Shape: panel")
it = M["PCG_COPShape"].INPUT_TYPES()
check("PCG_COPShape: check_layout empty", not PANEL.check_layout("PCG_COPShape", it),
      PANEL.check_layout("PCG_COPShape", it))
toks = it["required"]["shape"][0]
check("every shape menu token has a label, the old 5 keep their order",
      list(SPECS["PCG_COPShape"]["inputs"]["shape"]["menu"]) == toks
      and toks[:5] == ["circle", "box", "rounded_box", "line", "star"], toks)
check("every widget is in order",
      set(SPECS["PCG_COPShape"]["order"]) == set(it["required"]))
old = ["resolution_x", "resolution_y", "shape", "radius", "size_x", "size_y", "corner",
       "center_x", "center_y", "angle", "points", "inner", "line_ax", "line_ay",
       "line_bx", "line_by", "softness_pixels", "invert", "sdf_layer", "mask_layer",
       "color_layer", "device"]
check("old widget positions unchanged (new parameters all appended at the end)", list(it["required"])[:22] == old)


# ═══════════════════════════════════════════════════ UV Shape
def run_uv(**kw):
    a = defaults("PCG_COPUVShape")
    a.update(resolution_x=64, resolution_y=64)
    a.update(kw)
    return M["PCG_COPUVShape"]().run(**a)[0]


def L(im, name):
    return np.asarray(im.need(name), np.float64)


sec("UV Shape: the five disk mappings (disk -> [-1,1]²)")
rr = np.array([0.0, 0.3, 0.7, 1.0])
for nm in ("linear", "equal_area", "squircle", "elliptic_arc"):
    f = US._DISK[nm]
    xa, ya = f(rr, np.zeros(4))
    xb, yb = f(np.zeros(4), rr)
    check(f"{nm}: fixed on the axes ((r,0) -> (r,0), (0,r) -> (0,r))",
          np.allclose(xa, rr) and np.allclose(ya, 0) and np.allclose(xb, 0)
          and np.allclose(yb, rr), (xa, yb))
    th = np.radians([10.0, 30.0, 45.0, 60.0, 135.0, 250.0])
    u, v = f(np.cos(th), np.sin(th))
    check(f"{nm}: unit circle maps onto the square's boundary (max(|u|,|v|) = 1)",
          np.allclose(np.maximum(np.abs(u), np.abs(v)), 1.0, atol=1e-12), (u, v))
u, v = US.disk_linear(np.array([0.3 * np.cos(np.radians(20))]),
                      np.array([0.3 * np.sin(np.radians(20))]))
check("linear: a circle of radius 0.3 maps to a square of half side 0.3, v/u = tan 20° (radial stretch)",
      near(u[0], 0.3, 1e-12) and near(v[0] / u[0], np.tan(np.radians(20)), 1e-12), (u, v))
u, v = US.disk_equal_area(np.array([0.5 / np.sqrt(2)]), np.array([0.5 / np.sqrt(2)]))
check("equal_area: on the diagonal (r/√2, r/√2) -> (r, r)", near(u[0], 0.5, 1e-12)
      and near(v[0], 0.5, 1e-12), (u, v))
rng = np.random.default_rng(5)
P_ = rng.uniform(-0.65, 0.65, (400, 2))
P_ = P_[(np.hypot(P_[:, 0], P_[:, 1]) < 0.95) & (np.abs(P_).min(1) > 0.02)
        & (np.abs(np.abs(P_[:, 0]) - np.abs(P_[:, 1])) > 0.02)]
h_ = 1e-6


def jac_det(f, p):
    x, y = p[:, 0], p[:, 1]
    ux1, vx1 = f(x + h_, y)
    ux0, vx0 = f(x - h_, y)
    uy1, vy1 = f(x, y + h_)
    uy0, vy0 = f(x, y - h_)
    return ((ux1 - ux0) * (vy1 - vy0) - (uy1 - uy0) * (vx1 - vx0)) / (4 * h_ * h_)


dj = jac_det(US.disk_equal_area, P_)
check(f"equal_area: Jacobian determinant = 4/π everywhere (area preserving, {len(P_)} random points)",
      np.allclose(dj, 4 / np.pi, rtol=1e-5), (dj.min(), dj.max()))
check("negative control: linear is not area preserving (determinant not constant)",
      np.ptp(jac_det(US.disk_linear, P_)) > 0.1)
u, v = US.disk_polar(np.array([0.0, -0.5, 0.25]), np.array([0.5, 1e-12, 0.0]))
check("polar: U = angle/π ((0,0.5) -> 0.5, (-0.5,0⁺) -> 1), V = 2r - 1 (r 0.5 -> 0, 0.25 -> -0.5)",
      np.allclose(u, [0.5, 1.0, 0.0]) and np.allclose(v, [0.0, 0.0, -0.5]), (u, v))
qd = np.array([[0.3, 0.2], [-0.3, 0.2], [-0.3, -0.2], [0.3, -0.2], [0.2, 0.3],
               [-0.2, 0.3], [-0.2, -0.3], [0.2, -0.3]])
for nm in ("linear", "equal_area", "squircle", "elliptic_arc"):
    u, v = US._DISK[nm](qd[:, 0], qd[:, 1])
    check(f"{nm}: signs kept in all four quadrants (u same sign as x, v same sign as y), and symmetric about both axes",
          np.array_equal(np.sign(u), np.sign(qd[:, 0]))
          and np.array_equal(np.sign(v), np.sign(qd[:, 1]))
          and np.allclose(np.abs(u[:4]), abs(u[0])) and np.allclose(np.abs(v[4:]), abs(v[4])))
xs_, ys_ = np.cos(np.radians(30)) * 0.8, np.sin(np.radians(30)) * 0.8
outs = {nm: np.array(US._DISK[nm](np.array([xs_]), np.array([ys_]))).ravel()
        for nm in US.DISK_MODES}
vals = list(outs.values())
check("the five mappings differ pairwise at the same point (negative control)",
      all(not np.allclose(vals[i], vals[j]) for i in range(5) for j in range(i + 1, 5)),
      outs)

sec("UV Shape: annulus")
ri, ro = 0.1, 0.4
u, v = US.annulus_uv(np.array([ri, ro, 0.25, 0.0]), np.array([0, 0, 0, 0.25]), ri, ro, "polar")
check("polar: inner radius v = -1, outer +1, middle 0; u of (0, r) = 0.5",
      np.allclose(v[:3], [-1, 1, 0]) and near(u[3], 0.5, 1e-12), (u, v))
gm = np.sqrt(ri * ro)
u, v = US.annulus_uv(np.array([ri, ro, gm]), np.zeros(3), ri, ro, "log")
check("log: inner radius -1, outer +1, geometric mean radius √(ri·ro) -> 0",
      np.allclose(v, [-1, 1, 0], atol=1e-12), v)
check("log and polar differ at the middle radius (negative control)",
      not near(US.annulus_uv(np.array([0.25]), np.zeros(1), ri, ro, "log")[1][0],
               US.annulus_uv(np.array([0.25]), np.zeros(1), ri, ro, "polar")[1][0], 1e-3))

sec("UV Shape:Border / Transform / Range")
t = np.array([1.5, -1.25, 0.3, 3.5])
check("clamp: clamped to ±1", np.allclose(US.border(t, "clamp"), [1, -1, 0.3, 1]))
check("mirror: 1.5 -> 0.5, -1.25 -> -0.75, 3.5 -> -0.5 (folds back and forth with period 4)",
      np.allclose(US.border(t, "mirror"), [0.5, -0.75, 0.3, -0.5]), US.border(t, "mirror"))
check("wrap: 1.5 -> -0.5, -1.25 -> 0.75, 3.5 -> -0.5 (period 2)",
      np.allclose(US.border(t, "wrap"), [-0.5, 0.75, 0.3, -0.5]), US.border(t, "wrap"))
check("extend: unchanged", np.array_equal(US.border(t, "extend"), t))
X_, Y_ = US._coords(64, 64)
ext = run_uv(u_border="extend", v_border="extend")
uvx = L(ext, "uv")
ref = np.stack(US.disk_linear(X_ / 0.4, Y_ / 0.4), -1)
check("node: default Disk / Linear / R 0.4 = disk_linear(x/R, y/R) (per pixel with extend)",
      np.allclose(uvx, ref, atol=1e-6))
cl = L(run_uv(), "uv")
check("node: default clamp clamps the uv outside the circle to ±1; inside the circle same as extend",
      np.allclose(cl, np.clip(ref, -1, 1), atol=1e-6) and np.abs(ref).max() > 1.2)
uo = L(run_uv(u_border="extend", v_border="extend", offset="0.2 -0.1"), "uv")
check("Offset is added to the uv", np.allclose(uo, ref + [0.2, -0.1], atol=1e-6))
ua = L(run_uv(u_border="extend", v_border="extend", angle=90), "uv")
check("Angle 90°:(u, v) → (−v, u)",
      np.allclose(ua, np.stack([-ref[..., 1], ref[..., 0]], -1), atol=1e-6))
us_ = L(run_uv(u_border="extend", v_border="extend", shear=0.5), "uv")
check("Shear 0.5:u += 0.5·v",
      np.allclose(us_, np.stack([ref[..., 0] + 0.5 * ref[..., 1], ref[..., 1]], -1), atol=1e-6))
usc = L(run_uv(u_border="extend", v_border="extend", u_scale=2, v_scale=-1,
               offset="0.1 0"), "uv")
check("U/V Scale after Transform: ((u + 0.1)·2, -v)",
      np.allclose(usc, np.stack([(ref[..., 0] + 0.1) * 2, -ref[..., 1]], -1), atol=1e-6))
uw = L(run_uv(u_border="wrap", v_border="mirror"), "uv")
check("U Border wrap / V Border mirror each act on their own component",
      np.allclose(uw[..., 0], US.border(ref[..., 0], "wrap"), atol=1e-6)
      and np.allclose(uw[..., 1], US.border(ref[..., 1], "mirror"), atol=1e-6))
un = L(run_uv(uv_range="unit"), "uv")
check("UV Range unit = (clamped uv + 1)/2, within [0,1]",
      np.allclose(un, (cl + 1) / 2, atol=1e-6) and un.min() >= 0 and un.max() <= 1)
an = L(run_uv(shape="annulus", annulus_mode="log", u_border="extend", v_border="extend",
              inner_radius=0.1, outer_radius=0.4), "uv")
check("node: annulus reads Inner / Outer / Mode",
      np.allclose(an, np.stack(US.annulus_uv(X_, Y_, 0.1, 0.4, "log"), -1), atol=1e-5))
check("node: annulus doesn't read Radius / Disk Mode",
      np.array_equal(L(run_uv(shape="annulus"), "uv"),
                     L(run_uv(shape="annulus", radius=0.2, disk_mode="polar"), "uv")))
check("node: disk doesn't read Inner / Outer / Annulus Mode",
      np.array_equal(cl, L(run_uv(inner_radius=0.05, outer_radius=0.3,
                                  annulus_mode="log"), "uv")))

sec("UV Shape: uvscale and mask")
N_ = 64
im = run_uv()
sc_ = L(im, "uvscale")[..., 0]
# Pixels to the right of the center (x>0, near y=0): in linear mode du/dx = dv/dy = 1/R (in coordinates), 1/(R·N) per pixel
j, i = 40, 31                       # x = (40.5/64 − 0.5) > 0,y = −0.0078
check("uvscale (linear, near the x axis) ≈ 1/(R·N) uv units / pixel",
      abs(sc_[i, j] - 1 / (0.4 * N_)) < 2e-3, sc_[i, j])
check("UV Filter Bound clamps uvscale",
      np.allclose(L(run_uv(uv_filter_bound=0.01), "uvscale"), np.minimum(sc_, 0.01)[..., None]))
check("uvscale grows with U Scale (×3)",
      abs(L(run_uv(u_scale=3.0), "uvscale")[i, j, 0] - 3 / (0.4 * N_)) < 6e-3)
pol = L(run_uv(disk_mode="polar"), "uvscale")[..., 0]
r_ = np.hypot(X_, Y_)
ring = (r_ > 0.15) & (r_ < 0.38)
seam = ring & (X_ < 0) & (np.abs(Y_) < 0.03)
check("polar: the angle jump at ±1 doesn't get into uvscale (at the seam it's the same order of magnitude as elsewhere at the same radius)",
      pol[seam].max() < 2.0 * pol[ring & (X_ > 0) & (np.abs(Y_) < 0.03)].max(),
      (pol[seam].max(), pol[ring].max()))
check("uvscale is rotation invariant (Angle 37° same as 0°, it takes singular values)",
      np.allclose(L(run_uv(angle=37.0), "uvscale")[i, j, 0], sc_[i, j], rtol=1e-6))
check("Shear 1: Jacobian [[1,1],[0,1]]/(R·N), largest singular value = golden ratio φ/(R·N)",
      abs(L(run_uv(shear=1.0), "uvscale")[i, j, 0] - (1 + 5 ** 0.5) / 2 / (0.4 * N_)) < 3e-3)
sw = L(run_uv(resolution_x=81, resolution_y=41), "uvscale")[..., 0]
Xw, Yw = US._coords(81, 41)
jj = int(np.argmin(np.abs(Xw[20] - 0.3)))
# Difference step of half a pixel: the difference of v = y·r/|x| has a second-order error of (h/x)²/2, < 0.1% at x = 0.3
check("non-square image: uvscale measured in short-side pixels (81×41, row y = 0 ≈ 1/(R·41), within 0.1%)",
      abs(sw[20, jj] * 0.4 * 41 - 1) < 1e-3 and Yw[20, 0] == 0.0, sw[20, jj])
pu = L(run_uv(disk_mode="polar", u_scale=2.5), "uvscale")[..., 0]
check("polar + U Scale 2.5: the seam handled with period 2·2.5 (not 2), no spikes at the seam",
      pu[seam].max() < 2.0 * pu[ring & (X_ > 0) & (np.abs(Y_) < 0.03)].max(),
      (pu[seam].max(), pu[ring].max()))
pa = L(run_uv(shape="annulus", inner_radius=0.1, outer_radius=0.4), "uvscale")[..., 0]
check("annulus u is also an angle: no spikes at the seam",
      pa[seam].max() < 2.0 * pa[ring & (X_ > 0) & (np.abs(Y_) < 0.03)].max(),
      (pa[seam].max(), pa[ring].max()))
X65, Y65 = US._coords(65, 65)
R65 = float(np.hypot(X65[32, 42], Y65[32, 42]))
m65 = L(run_uv(resolution_x=65, resolution_y=65, radius=R65), "mask")[..., 0]
check("the mask boundary includes pixels at r = Radius (≤)", m65[32, 42] == 1.0 and m65[32, 43] == 0.0)
for wh in ((80, 40), (40, 80), (33, 33)):
    check(f"pixel coordinates match COP Shape's aspect_coords ({wh[0]}×{wh[1]})",
          np.allclose(np.stack(US._coords(*wh), -1),
                      np.asarray(G.aspect_coords(*wh), np.float64), atol=1e-6))
k_ = L(im, "mask")[..., 0]
check("mask: 1 inside the circle, 0 outside (by pixel center)",
      np.array_equal(k_, (r_ <= 0.4).astype(float)))
ka = L(run_uv(shape="annulus"), "mask")[..., 0]
check("mask: 1 inside the annulus [inner radius, outer radius]",
      np.array_equal(ka, ((r_ >= 0.2) & (r_ <= 0.45)).astype(float)))
e1 = run_uv(uv_layer="", uvscale_layer="", mask_layer="m2")
check("empty layer name = that layer is not output", list(e1.names) == ["m2"])
im2 = run_uv(resolution_x=80, resolution_y=40)
check("non-square image: normalized by the short side, the disk isn't distorted (mask is a true circle)",
      L(im2, "mask").shape == (40, 80, 1)
      and np.array_equal(L(im2, "mask")[..., 0],
                         (np.hypot(*US._coords(80, 40)) <= 0.4).astype(float)))
from comfyui_pcg.geo.cop.core import CopImage  # noqa: E402
base = CopImage(32, 24)
PX_ = __import__("comfyui_pcg.geo.cop.pixel", fromlist=["put"])
PX_.put(base, "C", np.zeros((24, 32, 3)))
ob = run_uv(cop=base)
check("with cop connected, follows its resolution and keeps its existing layers",
      L(ob, "uv").shape == (24, 32, 2) and "C" in ob.names)
for kw_, msg in (({"radius": 0.0}, "Radius"),
                 ({"shape": "annulus", "inner_radius": 0.5}, "Inner Radius")):
    try:
        US.uv_shape(**kw_, xres=8, yres=8)
        check(f"invalid parameter raises ({msg})", False)
    except ValueError as e:
        check(f"invalid parameter raises ({msg})", msg in str(e), e)

sec("UV Shape: round trip through UV Sample")
src = CopImage(64, 64)
from comfyui_pcg.geo.cop import pixel as PX  # noqa: E402
PX.put(src, "C", np.stack([X_ + 0.5, Y_ + 0.5], -1))       # an "its own coordinates" image
g_ = run_uv(uv_range="unit", radius=0.5)
samp = M["PCG_COPUVSample"]().run(g_, "uv", "C", "uv", "clamp", "out", source=src)[0]
o = L(samp, "out")
inside = r_ < 0.45
check("unit mode uv fed directly to UV Sample: samples exactly the position (uv + 1)/2 on the source image (±1 pixel)",
      np.abs(o[inside] - L(g_, "uv")[inside]).max() < 1.5 / 64)

sec("UV Shape: registration / panel / mapping table")
it = M["PCG_COPUVShape"].INPUT_TYPES()
check("check_layout empty", not PANEL.check_layout("PCG_COPUVShape", it),
      PANEL.check_layout("PCG_COPUVShape", it))
sp = SPECS["PCG_COPUVShape"]
check("every widget is in order",
      set(sp["order"]) == {k for k in it["required"]})
for key in ("shape", "disk_mode", "annulus_mode", "u_border", "v_border", "uv_range"):
    check(f"{key}: every menu token has a label",
          list(sp["inputs"][key]["menu"]) == it["required"][key][0])
_cm = {}
for _c in (_R, os.path.dirname(os.path.dirname(os.path.abspath(PANEL.__file__)))):
    _p = os.path.join(_c, "copernicus_map.py")
    if os.path.isfile(_p):
        exec(open(_p, encoding="utf-8").read(), _cm)
        break
if _cm:
    check("copernicus_map: UV Shape -> PCG_COPUVShape, SDF Shape still PCG_COPShape",
          _cm["M"]["UV Shape"][1] == "PCG_COPUVShape"
          and _cm["M"]["SDF Shape"][1] == "PCG_COPShape")
else:
    print("  (no copernicus_map.py in the device layout, skipping this one)")


# ═══════════════════════════════════════════════════ Tile Pattern:Bond
def tile(bond, counts="4 4", W=64, H=64, **kw):
    a = dict(kind="tile", counts=counts, gap=0.0, xres=W, yres=H, bond=bond, seed=1)
    a.update(kw)
    return PT.pattern(**a)


def joints(im, row, nu, nv, W, H):
    """Positions along the middle pixel line of row row (0 at the bottom) where id changes (in stretcher-length units)."""
    idl = np.asarray(im.need("pattern_id"))[..., 0]
    i = int((row + 0.5) * H / nv)
    line = idl[i]
    js = np.nonzero(line[1:] != line[:-1])[0] + 1
    return sorted(round(j / W * nu, 6) for j in js)


sec("Tile Pattern: vertical joint positions of each bond (stretcher length = 1)")
EXP = {
    "stack": ([1, 2, 3], [1, 2, 3]),
    "stretcher": ([1, 2, 3], [0.5, 1.5, 2.5, 3.5]),
    "header": ([0.5, 1, 1.5, 2, 2.5, 3, 3.5], [0.25, 0.75, 1.25, 1.75, 2.25, 2.75, 3.25, 3.75]),
    "english": ([0.75, 1.75, 2.75, 3.75], [0.5, 1, 1.5, 2, 2.5, 3, 3.5]),
}
for b, (r0, r1) in EXP.items():
    im = tile(b)
    j0, j1 = joints(im, 0, 4, 4, 64, 64), joints(im, 1, 4, 4, 64, 64)
    check(f"{b}: row 0 {r0}, row 1 {r1}", j0 == r0 and j1 == r1, (j0, j1))
im = tile("flemish", counts="3 4", W=48)
j0, j1 = joints(im, 0, 3, 4, 48, 64), joints(im, 1, 3, 4, 48, 64)
check("flemish (3 bricks wide): row 0 stretcher[0,1] header[1,1.5] stretcher[1.5,2.5] header[2.5,3]; row 1 shifted right by ¾",
      j0 == [1, 1.5, 2.5] and j1 == [0.25, 0.75, 1.75, 2.25], (j0, j1))
check("flemish: row 1's header [0.25,0.75] sits right in the middle of row 0's stretcher [0,1]",
      (0.25 + 0.75) / 2 == (0 + 1) / 2)
uvl = np.asarray(im.need("pattern_uv"))[..., 0]
i1 = int(1.5 * 64 / 4)
seg = uvl[i1, 4:12]                          # the header brick at x ∈ [0.25, 0.75), 8 pixels
check("flemish: in-brick u inside a header goes from 0 to 1 (by the header's own width)",
      np.allclose(seg, (np.arange(8) + 0.5) / 8, atol=1e-6), seg)
ida = np.asarray(im.need("pattern_id"))[..., 0]
check("flemish 3×4: tiles -- the stretcher of row 1 crossing the right border has the same id at both ends",
      ida[i1, 0] == ida[i1, -1])
check("flemish 3×4: 4 rows × 4 bricks = 16 distinct ids in total", len(np.unique(ida)) == 16)
check("header 4×4: 4 rows × 8 bricks = 32 ids",
      len(np.unique(np.asarray(tile("header").need("pattern_id")))) == 32)
im = tile("american", counts="4 6", H=96, header_interval=3)
rows = [joints(im, r, 4, 6, 64, 96) for r in range(6)]
hd = [0.5, 1, 1.5, 2, 2.5, 3, 3.5]
check("american (interval 3): rows 0, 3 are headers; the rest stretchers, odd rows offset by half a brick",
      rows[0] == hd and rows[3] == hd and rows[1] == [0.5, 1.5, 2.5, 3.5]
      and rows[2] == [1, 2, 3] and rows[4] == [1, 2, 3] and rows[5] == [0.5, 1.5, 2.5, 3.5],
      rows)
check("header_interval only affects american",
      np.array_equal(np.asarray(tile("flemish", header_interval=2).need("pattern")),
                     np.asarray(tile("flemish").need("pattern")))
      and not np.array_equal(np.asarray(tile("american", header_interval=2).need("pattern_id")),
                             np.asarray(tile("american").need("pattern_id"))))

sec("Tile Pattern: Bond agrees with the original Row Offset")
for b, off in (("stack", 0.0), ("stretcher", 0.5)):
    a = tile(b, gap=0.1, bevel=0.2)
    o = tile("offset", gap=0.1, bevel=0.2, offset=off)
    same = all(np.allclose(np.asarray(a.need(k)), np.asarray(o.need(k)), atol=1e-6)
               for k in ("pattern", "pattern_height", "pattern_edge", "pattern_uv",
                         "pattern_id", "pattern_rand"))
    check(f"{b} == offset mode Row Offset = {off} (all six layers identical)", same)
a6 = tile("stack", W=6, H=6)
o6 = tile("offset", W=6, H=6, offset=0.0)
check("pixel centers landing exactly on a vertical joint (6 pixels / 4 bricks): belong to the brick on the right, consistent with offset mode ([start, end) intervals)",
      np.array_equal(np.asarray(a6.need("pattern_id")), np.asarray(o6.need("pattern_id")))
      and np.asarray(a6.need("pattern_uv"))[0, 1, 0] == 0.0)
f9 = tile("flemish", counts="6 2", W=9, H=4)
check("pixels on the joint between two brick types in a row (flemish x = 1, stretcher | header) belong to the header on the right: in-brick u = 0",
      np.asarray(f9.need("pattern_uv"))[0, 1, 0] == 0.0, np.asarray(f9.need("pattern_uv"))[0, :3, 0])
check("Row Offset not read when Bond isn't offset",
      np.array_equal(np.asarray(tile("flemish", offset=0.1).need("pattern")),
                     np.asarray(tile("flemish", offset=0.9).need("pattern"))))
g_ = tile("header", gap=0.25)
e = np.asarray(g_.need("pattern"))[..., 0]
# 64 px / 4 bricks: stretcher cell 16 px, mortar = 0.25 × 16 = 4 px (2 per side). Header 8 px wide, vertical joints also 4 px
i_ = 40
dark = np.nonzero(e[i_] < 0.5)[0]
check("header: header mortar as wide as stretcher mortar (converted by the stretcher cell's short side, each vertical joint 4 pixels)",
      len(dark) == 8 * 4, dark)
try:
    tile("monk")
    check("unknown Bond raises", False)
except ValueError as e_:
    check("unknown Bond raises", "Bond" in str(e_))
check("node: bond defaults to offset, every menu token has a label",
      M["PCG_COPPattern"].INPUT_TYPES()["required"]["bond"][0][0] == "offset"
      and list(SPECS["PCG_COPPattern"]["inputs"]["bond"]["menu"])
      == M["PCG_COPPattern"].INPUT_TYPES()["required"]["bond"][0])


# ═══════════════════════════════════════════════════ Chladni
def chl(**kw):
    a = dict(kind="chladni", xres=48, yres=32, modes="3 5")
    a.update(kw)
    im = PT.pattern(**a)
    return (np.asarray(im.need("pattern"), np.float64)[..., 0],
            np.asarray(im.need("pattern_value"), np.float64)[..., 0])


def chl_ref(n, m, sg, k=1.0, A=1.0, W=48, H=32):
    u, v = PT._pix(W, H)
    s_ = min(W, H)
    x = (u - 0.5) * (W / s_) + 0.5
    y = (v - 0.5) * (H / s_) + 0.5
    a, b = np.pi * n, np.pi * m
    return A * (np.cos(a * x) * np.cos(b * y) + sg * k * np.cos(b * x) * np.cos(a * y))


sec("Chladni:Output Mode / Amplitude / Amplitude Ratio")
m0, v0 = chl(chladni_output="signed")
check("signed: main layer = f = cos(3πx)cos(5πy) - cos(5πx)cos(3πy) (coordinates normalized by the short side)",
      np.allclose(m0, chl_ref(3, 5, -1), atol=1e-6) and np.allclose(m0, v0))
m1, _ = chl(chladni_output="absolute")
check("absolute: main layer = |f|", np.allclose(m1, np.abs(chl_ref(3, 5, -1)), atol=1e-6))
m2, v2 = chl(chladni_output="signed", amplitude=2.5)
check("Amplitude 2.5: f × 2.5 overall", np.allclose(m2, 2.5 * chl_ref(3, 5, -1), atol=1e-5))
m3, _ = chl(chladni_output="signed", amplitude_ratio=0.3, sign="+")
check("Amplitude Ratio 0.3(Sign +):f = a + 0.3·b",
      np.allclose(m3, chl_ref(3, 5, 1, 0.3), atol=1e-6))
check("negative control: Ratio 0.3 differs from 1", not np.allclose(m3, chl(chladni_output="signed",
                                                         sign="+")[0]))
p0, pv0 = chl()
p2, pv2 = chl(amplitude=3.0)
check("pixel_lines (the original mode): Amplitude only scales _value, nodal line thickness unchanged (line width by |f|/|∇f|)",
      np.allclose(p0, p2, atol=1e-6) and np.allclose(pv2, 3 * pv0, atol=1e-5))
pr, _ = chl(amplitude_ratio=0.5)
check("pixel_lines: changing Ratio moves the nodal lines too", not np.allclose(p0, pr))
check("pixel_lines doesn't read Threshold / Smoothing",
      np.array_equal(p0, chl(threshold=0.7, smoothing_width=0.3)[0]))

sec("Chladni: Nodal Lines (threshold version)")
T, w = 0.4, 0.2
nl, nv = chl(chladni_output="nodal_lines", threshold=T, smoothing_width=w)
af = np.abs(nv)
check("1 (white) where |f| ≤ T - W", np.all(nl[af <= T - w - 1e-6] > 1 - 1e-6))
check("0 (black) where |f| ≥ T", np.all(nl[af >= T + 1e-6] < 1e-6))
tt = np.clip((af - (T - w)) / w, 0, 1)
check("smoothstep transition in between (per pixel)", np.allclose(nl, 1 - tt * tt * (3 - 2 * tt), atol=1e-6))
check("transition band midpoint |f| = T - W/2 -> 0.5",
      near(1 - (lambda t: t * t * (3 - 2 * t))(0.5), 0.5))
hb, hv = chl(chladni_output="nodal_lines", threshold=T, smoothing_width=0.0)
check("Smoothing Width 0: hard edge, 1 where |f| < T", np.array_equal(hb, (np.abs(hv) < T).astype(float)))
Te = float(np.abs(chl_ref(3, 5, -1))[7, 9])
he, _ = chl(chladni_output="nodal_lines", threshold=Te, smoothing_width=0.0)
check("with a hard edge, pixels with |f| exactly equal to Threshold are black (≥ T black), no NaN anywhere",
      he[7, 9] == 0.0 and np.isfinite(he).all())
check("nodal_lines doesn't read Line Width",
      np.array_equal(nl, chl(chladni_output="nodal_lines", threshold=T,
                             smoothing_width=w, line_width=9.0)[0]))
check("larger Threshold, more white",
      chl(chladni_output="nodal_lines", threshold=0.8)[0].sum()
      > chl(chladni_output="nodal_lines", threshold=0.2)[0].sum())
try:
    chl(chladni_output="nope")
    check("wrong Output Mode raises", False)
except ValueError as e_:
    check("wrong Output Mode raises", "Output Mode" in str(e_))
toks = M["PCG_COPPattern"].INPUT_TYPES()["required"]["chladni_output"][0]
check("node: chladni_output defaults to pixel_lines (old behavior), every menu item has a label",
      toks[0] == "pixel_lines"
      and list(SPECS["PCG_COPPattern"]["inputs"]["chladni_output"]["menu"]) == toks)


# ═══════════════════════════════════════════════════ Cell Pattern
def cell(**kw):
    a = dict(kind="cell", counts="4 4", xres=64, yres=64, gap=0.0, seed=2)
    a.update(kw)
    im = PT.pattern(**a)
    return {k: np.asarray(im.need(k), np.float64)[..., 0] for k in
            ("pattern", "pattern_id", "pattern_edge", "pattern_dist", "pattern_rand")}


sec("Cell Pattern: Metric / Lattice (computable by hand at Jitter 0)")
u_, v_ = PT._pix(64, 64)
fx_, fy_ = (u_ * 4) % 1, (v_ * 4) % 1
dx_, dy_ = (fx_ - 0.5) * 16, (fy_ - 0.5) * 16          # pixel offset to this cell's center
border = np.minimum(np.minimum(fx_, 1 - fx_), np.minimum(fy_, 1 - fy_)) * 16
for met, dref in (("euclidean", np.hypot(dx_, dy_)),
                  ("manhattan", np.abs(dx_) + np.abs(dy_)),
                  ("chebyshev", np.maximum(np.abs(dx_), np.abs(dy_)))):
    c_ = cell(jitter=0.0, cell_metric=met)
    check(f"{met}: on a square lattice the cells are the squares, _edge = pixel distance to the cell border",
          np.allclose(c_["pattern_edge"], border, atol=1e-6))
    check(f"{met}: _dist = distance to the cell center in this metric / cell side length",
          np.allclose(c_["pattern_dist"], dref / 16, atol=1e-6))
c_ = cell(jitter=0.0, lattice="hexagonal")
idl = c_["pattern_id"]
r0 = np.nonzero(idl[8, 1:] != idl[8, :-1])[0] + 1
r1 = np.nonzero(idl[24, 1:] != idl[24, :-1])[0] + 1
check("hexagonal: row 0 cell borders at x = 0.5, 1.5 … (cell centers at 0.5 …)",
      list(r0) == [16, 32, 48], r0)
check("hexagonal: row 1 feature points shifted right by half a cell (centers at x = 1, 2, 3, 4≡0), cell borders move to x = 0.5, 1.5 …",
      list(r1) == [8, 24, 40, 56], r1)
check("hexagonal 4×4: still 16 cells, seamless (same id at the left and right edges of row 1)",
      len(np.unique(idl)) == 16 and idl[24, 0] == idl[24, 63])

sec("Cell Pattern: nearest point agrees with brute-force search (Jitter 1, three metrics × two lattices)")
nu_, nv_, Wc = 4, 4, 64
ox_, oy_ = PT._cell_points(nu_, nv_, 1.0, 2)
for lat in ("grid", "hexagonal"):
    for met in ("euclidean", "manhattan", "chebyshev"):
        c_ = cell(jitter=1.0, cell_metric=met, lattice=lat)
        assert c_["pattern_id"].shape == (Wc, Wc)
        pts = []
        for j in range(nv_):
            for i in range(nu_):
                sx = i + ox_[j, i] + (0.5 * (j % 2) if lat == "hexagonal" else 0.0)
                for ki in (-1, 0, 1):
                    for kj in (-1, 0, 1):
                        pts.append((sx + ki * nu_, j + oy_[j, i] + kj * nv_, j * nu_ + i))
        pts = np.array(pts)
        X_, Y_ = u_ * nu_, v_ * nv_
        ddx = (pts[None, None, :, 0] - X_[..., None]) * 16
        ddy = (pts[None, None, :, 1] - Y_[..., None]) * 16
        if met == "euclidean":
            D = np.hypot(ddx, ddy)
        elif met == "manhattan":
            D = np.abs(ddx) + np.abs(ddy)
        else:
            D = np.maximum(np.abs(ddx), np.abs(ddy))
        srt = np.sort(D, -1)
        best_id = pts[np.argmin(D, -1), 2]
        clear = (srt[..., 1] - srt[..., 0]) > 1e-6
        check(f"{lat}/{met}: every pixel's id, _dist agree with the brute-force nearest point",
              np.array_equal(c_["pattern_id"][clear], best_id[clear])
              and np.allclose(c_["pattern_dist"], srt[..., 0] / 16, atol=1e-5))
        if met != "euclidean":
            check(f"{lat}/{met}: _edge = (F2 - F1)/2 (brute-force second nearest - nearest)",
                  np.allclose(c_["pattern_edge"], (srt[..., 1] - srt[..., 0]) / 2, atol=1e-5))
        if met == "euclidean":
            k_ = np.argmin(D, -1)[..., None]
            bx_ = np.take_along_axis(ddx, k_, -1)
            by_ = np.take_along_axis(ddy, k_, -1)
            ex, ey = ddx - bx_, ddy - by_
            ll_ = np.hypot(ex, ey)
            ok_ = ll_ > 1e-9
            eb = np.where(ok_, ((bx_ + ddx) * 0.5 * ex + (by_ + ddy) * 0.5 * ey)
                          / np.where(ok_, ll_, 1), np.inf).min(-1)
            check(f"{lat}/euclidean: _edge = distance to the nearest bisector (brute force)",
                  np.allclose(c_["pattern_edge"], eb, atol=1e-5))
e_ = cell(jitter=1.0)
m_ = cell(jitter=1.0, cell_metric="manhattan")
check("negative control: at Jitter 1, Manhattan's cell partition differs from Euclidean's",
      not np.array_equal(e_["pattern_id"], m_["pattern_id"]))

sec("Cell Pattern:Density")
d1 = cell(jitter=1.0)
d5 = cell(jitter=1.0, density=0.5, density_seed=7)
keep = PT.rnd(d1["pattern_id"].astype(np.int64), 7, 3) < 0.5
check("Density 0.5: cells with random value ≥ 0.5 get mask 0, the rest same as without culling",
      np.all(d5["pattern"][~keep] == 0) and np.array_equal(d5["pattern"][keep],
                                                           d1["pattern"][keep])
      and (~keep).any() and keep.any())
big0 = cell(jitter=1.0, counts="16 16")
big = cell(jitter=1.0, counts="16 16", density=0.95, density_seed=3)
cul = PT.rnd(big0["pattern_id"].astype(np.int64), 3, 3) >= 0.95
check("Density 0.95 (16×16 cells): culls exactly those with random value ≥ 0.95 (at least one)",
      cul.any() and np.all(big["pattern"][cul] == 0)
      and np.array_equal(big["pattern"][~cul], big0["pattern"][~cul]))
check("Density only changes the main layer (id / edge / dist / rand unchanged)",
      all(np.array_equal(d5[k], d1[k]) for k in ("pattern_id", "pattern_edge",
                                                  "pattern_dist", "pattern_rand")))
check("Density 0: everything culled", np.all(cell(density=0.0)["pattern"] == 0))
check("Density Seed changed, the culled cells change",
      not np.array_equal(d5["pattern"], cell(jitter=1.0, density=0.5, density_seed=8)["pattern"]))
check("Density Seed not read at Density 1",
      np.array_equal(d1["pattern"], cell(jitter=1.0, density_seed=99)["pattern"]))
for k_, bad in (("cell_metric", "taxicab"), ("lattice", "tri")):
    try:
        cell(**{k_: bad})
        check(f"wrong {k_} raises", False)
    except ValueError:
        check(f"wrong {k_} raises", True)
it = M["PCG_COPPattern"].INPUT_TYPES()["required"]
check("node: cell_metric / lattice default to euclidean / grid (old behavior), every menu item has a label",
      it["cell_metric"][0][0] == "euclidean" and it["lattice"][0][0] == "grid"
      and list(SPECS["PCG_COPPattern"]["inputs"]["cell_metric"]["menu"]) == it["cell_metric"][0]
      and list(SPECS["PCG_COPPattern"]["inputs"]["lattice"]["menu"]) == it["lattice"][0])


# ═══════════════════════════════════════════════════ UV Grid
def uvg(**kw):
    a = dict(kind="uv_grid", counts="4 2", xres=64, yres=32, labels=False)
    a.update(kw)
    return np.asarray(PT.pattern(**a).need("pattern"), np.float64)


C1, C2 = np.array([0.9, 0.2, 0.1]), np.array([0.1, 0.3, 0.8])
kw_ = dict(tile_color1="0.9 0.2 0.1", tile_color2="0.1 0.3 0.8")
sec("UV Grid: tile coloring")
im = uvg(tile_coloring="uniform", **kw_)
check("uniform: middle of a tile is color 1", np.allclose(im[8, 8], C1, atol=1e-6)
      and np.allclose(im[24, 56], C1, atol=1e-6))
im = uvg(tile_coloring="checker", **kw_)
check("checker: (0,0) color 1, (1,0) color 2, (1,1) color 1",
      np.allclose(im[8, 8], C1, atol=1e-6) and np.allclose(im[8, 24], C2, atol=1e-6)
      and np.allclose(im[24, 24], C1, atol=1e-6))
im = uvg(tile_coloring="gradient", **kw_)
ok = all(np.allclose(im[8 + 16 * j, 8 + 16 * i], C1 + (C2 - C1) * (j * 4 + i) / 7, atol=1e-6)
         for i in range(4) for j in range(2))
check("gradient: by tile number (from bottom left, rows first) linearly from color 1 to color 2", ok)
h0 = uvg()
check("hue (default) doesn't read the two colors", np.array_equal(h0, uvg(**kw_)))
check("uniform doesn't read color 2", np.array_equal(uvg(tile_coloring="uniform", **kw_),
                                         uvg(tile_coloring="uniform", tile_color1="0.9 0.2 0.1")))

sec("UV Grid: outlines")
row = uvg(tile_coloring="uniform", tile_color1="1 1 1", outline_color="0 0 0",
          outline_width=3.0)[8, :, 0]
lp_ = np.minimum((np.arange(64) + 0.5) % 16, 16 - (np.arange(64) + 0.5) % 16)
lp_ = np.minimum(lp_, 7.5)                         # row 8 is 7.5 pixels from the top / bottom tile borders
cov = np.clip(0.5 - (lp_ - 1.5), 0, 1)
check("line width 3 pixels: coverage = clip(0.5 - (distance to tile border - 1.5)), black line on white -> 1 - coverage",
      np.allclose(row, 1 - cov, atol=1e-6), row[12:20])
noline = uvg(tile_coloring="uniform", outlines=False, **kw_)
check("outlines off: tile color on the tile border too", np.allclose(noline[8, 15], C1, atol=1e-6)
      and np.allclose(noline[8, 16], C1, atol=1e-6))
oc = uvg(tile_coloring="uniform", tile_color1="1 1 1", outline_color="0 1 0")
check("outline color", np.allclose(oc[8, 0], [0.5, 1.0, 0.5], atol=1e-6), oc[8, 0])
check("with outlines off, line width / line color are not read",
      np.array_equal(noline, uvg(tile_coloring="uniform", outlines=False,
                                 outline_width=5, outline_color="1 0 0", **kw_)))

sec("UV Grid: markers")
S_ = 0.5 * 16
base_ = dict(tile_coloring="uniform", tile_color1="1 1 1", outlines=False, labels=True,
             marker_size=0.5, marker_color="0 0 0")
cr = uvg(marker_type="cross", **base_)[..., 0]
# Tile (0,0)'s center is at the corner of pixel (8,8); cross half length 4, arm half width 4 - (4 - 0.64) = 0.64
check("cross: marker color near the tile center, background color in the tile corners; arms in all four directions",
      cr[7, 7] < 0.5 and cr[1, 1] == 1.0 and cr[7, 10] < 0.5 and cr[7, 4] < 0.5
      and cr[10, 7] < 0.5 and cr[4, 7] < 0.5, cr[4:12, 4:12])
a64 = 0.08 * S_                                    # arm half width 0.64 pixels
check("cross coverage is analytically anti-aliased: on the arm (2.5,-0.5) -> 1 - (0.5 + 0.14), next to the center (-0.5,-0.5) -> "
      "1 - (0.5 + 0.14√2) (to the inner corner)",
      near(cr[7, 10], 1 - (0.5 + (a64 - 0.5)), 1e-6)
      and near(cr[7, 7], 1 - (0.5 + (a64 - 0.5) * np.sqrt(2)), 1e-6), (cr[7, 10], cr[7, 7]))
ar = uvg(marker_type="arrow", **base_)[..., 0]
# Arrow points from y = -4 to +4 (pixels), head in the upper half; (x = +1.5, y = +1.5) in the head, (1.5, -1.5) only shaft (half width 0.64)
yy = lambda dy: int(8 + dy - 0.5)                  # noqa: E731
check("arrow: points towards +v -- marker color inside the wide head in the upper half, background at the same off-center position in the lower half",
      ar[yy(2), yy(2)] < 0.5 and ar[yy(-1), yy(2)] > 0.5, ar[3:13, 7:11])
check("arrow is not vertically symmetric (negative control)", not np.array_equal(ar, ar[::-1]))
check("cross and arrow differ", not np.array_equal(cr, ar))
mk = uvg(marker_type="cross", marker_coloring="checker", marker_color2="0 0 1",
         **dict(base_, marker_size=0.9, marker_color="1 0 0"))
# 0.9 × 16: arm half width 1.15 pixels, pixel (7,7) next to the center fully covered
check("marker checker: tile (0,0)'s marker uses color 1, tile (1,0) color 2, tile (1,1) color 1 again",
      np.allclose(mk[7, 7], [1, 0, 0], atol=1e-6) and np.allclose(mk[7, 23], [0, 0, 1], atol=1e-6)
      and np.allclose(mk[23, 23], [1, 0, 0], atol=1e-6), (mk[7, 7], mk[7, 23]))
mg = uvg(marker_type="cross", marker_coloring="gradient", marker_color2="0 0 1",
         **dict(base_, marker_size=0.9, marker_color="1 0 0"))
check("marker gradient: the last tile's (top right) marker is color 2, tile 1's is at 1/7",
      np.allclose(mg[23, 55], [0, 0, 1], atol=1e-6)
      and np.allclose(mg[7, 23], [6 / 7, 0, 1 / 7], atol=1e-6), mg[7, 23])
check("with Draw Markers off no marker parameter is read",
      np.array_equal(uvg(), uvg(marker_type="arrow", marker_size=0.9, marker_coloring="checker")))
check("cross markers don't read Text Mode / Font",
      np.array_equal(cr, uvg(marker_type="cross", text_mode="coordinates", font="nope", **base_)[..., 0]))
try:
    t1 = uvg(labels=True, outlines=False, tile_coloring="uniform")
    t2 = uvg(labels=True, outlines=False, tile_coloring="uniform", text_mode="coordinates")
    t3 = uvg(labels=True, outlines=False, tile_coloring="uniform", marker_size=0.5)
    check("text: Letters and Coordinates draw differently, Marker Size changes the font size",
          not np.array_equal(t1, t2) and not np.array_equal(t1, t3))
except Exception as e_:                         # noqa: BLE001
    print("  (Pillow on this machine can't draw text, skipping the text marker check)", e_)
for k_, bad in (("tile_coloring", "rainbow"), ("marker_type", "dot"), ("text_mode", "x"),
                ("marker_coloring", "hue")):
    try:
        uvg(**{k_: bad})
        check(f"wrong {k_} raises", False)
    except ValueError:
        check(f"wrong {k_} raises", True)
it = M["PCG_COPPattern"].INPUT_TYPES()["required"]
for k_ in ("tile_coloring", "marker_type", "text_mode", "marker_coloring"):
    check(f"node: every {k_} menu token has a label",
          list(SPECS["PCG_COPPattern"]["inputs"][k_]["menu"]) == it[k_][0])


# ═══════════════════════════════════════════════════ Weave
from comfyui_pcg.geo.cop.core import CopImage as _CI  # noqa: E402
from comfyui_pcg.geo.cop import pixel as _PX          # noqa: E402


def wv(img=None, **kw):
    a = dict(kind="weave", counts="4 4", xres=64, yres=64, seed=1)
    a.update(kw)
    im = PT.pattern(img, **a)
    return {k: np.asarray(im.need(k), np.float64) for k in
            ("pattern", "pattern_mask", "pattern_warp", "pattern_id", "pattern_rand")}


def layer_from(fn, W=64, H=64, nu=4, nv=4):
    im = _CI(W, H)
    J, I = np.meshgrid(np.arange(W), np.arange(H))
    ci, cj = (J * nu) // W, (I * nv) // H
    _PX.put(im, "arr", fn(ci, cj).astype(np.float64))
    return im


sec("Weave: Custom layout")
chk_ = layer_from(lambda i, j: (i + j) % 2 == 0)
pl, cu = wv(weave="plain"), wv(chk_, weave="custom", weave_layer="arr")
check("custom + checkerboard layer = plain (all five layers identical per pixel)",
      all(np.array_equal(pl[k], cu[k]) for k in pl))
tw_ = layer_from(lambda i, j: (i - j) % 4 < 2)
check("custom + twill layer = twill",
      all(np.array_equal(wv(weave="twill")[k], wv(tw_, weave="custom", weave_layer="arr")[k])
          for k in pl))
one = layer_from(lambda i, j: (i == 1) & (j == 2))
o_ = wv(one, weave="custom", weave_layer="arr")
wp = o_["pattern_warp"][..., 0]
cen = {(i, j): wp[int((j + 0.5) * 16), int((i + 0.5) * 16)] for i in range(4) for j in range(4)}
check("only crossing (1,2) has a layer value > 0.5: only at that crossing is the warp on top",
      cen[(1, 2)] == 1.0 and sum(cen.values()) == 1.0, cen)
small = _CI(4, 4)
_PX.put(small, "arr", ((np.arange(4)[None, :] + np.arange(4)[:, None]) % 2 == 0).astype(float))
check("layer resolution needn't match the output (a 4×4 small image sampled at crossing centers) = plain",
      np.array_equal(PT._weave_table(small, "arr", 4, 4),
                     PT._over("plain", np.arange(4)[None, :], np.arange(4)[:, None])))
dot = _CI(64, 64)
arr_ = np.zeros((64, 64))
arr_[40, 24] = 1.0                                   # the single pixel at the center of crossing (1,2)
_PX.put(dot, "arr", arr_)
tb = PT._weave_table(dot, "arr", 4, 4)
check("sampled at crossing **centers**: an image with 1 only at the center pixel of (1,2) -> only (1,2) has the warp on top",
      tb[2, 1] and tb.sum() == 1, np.argwhere(tb))
rect_ = _CI(8, 4)
ar8 = np.zeros((4, 8))
ar8[:, 6:8] = 1.0                                    # right 1/4: crossings of column 3
_PX.put(rect_, "arr", ar8)
tb = PT._weave_table(rect_, "arr", 4, 4)
check("non-square layer (8×4): sampled by image width horizontally and image height vertically",
      tb[:, 3].all() and not tb[:, :3].any(), tb.astype(int))
hf = _CI(4, 4)
_PX.put(hf, "arr", np.full((4, 4), 0.5))
hf2 = _CI(4, 4)
_PX.put(hf2, "arr", np.full((4, 4), 0.501))
check("threshold: warp on top only when > 0.5 (exactly 0.5 = weft on top, 0.501 = warp on top)",
      not PT._weave_table(hf, "arr", 4, 4).any() and PT._weave_table(hf2, "arr", 4, 4).all())
try:
    wv(weave="custom")
    check("custom without a layer name raises", False)
except ValueError as e_:
    check("custom without a layer name raises", "Weave Layer" in str(e_))
try:
    wv(chk_, weave="custom", weave_layer="nope")
    check("custom with a missing layer raises", False)
except KeyError:
    check("custom with a missing layer raises", True)
check("Weave Layer not read when not custom",
      np.array_equal(pl["pattern"], wv(weave="plain", weave_layer="nope")["pattern"]))

sec("Weave: separate warp / weft widths")
d0 = wv()
d1 = wv(separate_widths=True, weft_width=0.4)
# Pixel (row 4, column 0): fy = 0.28 is 0.22 from the weft center (> 0.2 = 0.4/2, < 0.4 = 0.8/2), fx = 0.03 is 0.47 from the warp center
check("weft width 0.4: no thread 0.22 from the weft center (not on a warp); there is one at width 0.8",
      d0["pattern_mask"][4, 0, 0] == 1.0 and d1["pattern_mask"][4, 0, 0] == 0.0)
check("warp width unaffected: mask still 1 on the warp center column",
      np.all(d1["pattern_mask"][:, 8, 0] == 1.0))
check("Weft Width not read when Separate is off",
      np.array_equal(d0["pattern"], wv(weft_width=0.3)["pattern"]))
check("Separate on, weft width = thread width -> same as off",
      np.array_equal(d0["pattern"], wv(separate_widths=True, weft_width=0.8)["pattern"]))
it = M["PCG_COPPattern"].INPUT_TYPES()["required"]
check("node: weave menu's old 3 keep their order, custom appended at the end, each has a label",
      it["weave"][0] == ["plain", "twill", "satin", "custom"]
      and list(SPECS["PCG_COPPattern"]["inputs"]["weave"]["menu"]) == it["weave"][0])

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
