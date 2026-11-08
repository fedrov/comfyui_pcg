"""
Write the concept diagrams of the docs (docs/images/concepts/*.svg).

Plain SVG with its own white background, so they read the same on GitHub and in the HTML docs, light or dark.
Run after changing a diagram:  python tools/concept_diagrams.py
"""
from __future__ import annotations

import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "docs", "images", "concepts")

FONT = "font-family=\"system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif\""
INK, MUTED, LINE = "#1d2127", "#5d6672", "#c9ced6"
BLUE, ORANGE, GREEN, PURPLE, RED = "#2f7fc1", "#e08a2e", "#3d9a5b", "#8a5cc2", "#c8463d"


def svg(w, h, body, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'role="img" aria-label="{title}">\n<title>{title}</title>\n'
            f'<rect width="{w}" height="{h}" rx="10" fill="#ffffff"/>\n'
            f'<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="{MUTED}"/></marker></defs>\n'
            f'<g {FONT}>\n{body}\n</g>\n</svg>\n')


def text(x, y, s, size=14, fill=INK, anchor="start", weight=400, italic=False):
    st = ' font-style="italic"' if italic else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
            f'font-weight="{weight}"{st}>{s}</text>')


def arrow(x1, y1, x2, y2, color=MUTED, w=1.6, dash=""):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="{w}"'
            f'{d} marker-end="url(#arr)"/>')


def box(x, y, w, h, fill="#f4f6f9", stroke=LINE, r=8, extra=""):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}"{extra}/>'


# ───────────────────────────────────────────── geometry elements
def geometry_elements():
    P = [(80, 230), (230, 250), (380, 225), (60, 90), (215, 70), (370, 95)]
    prims = [[0, 1, 4, 3], [1, 2, 5, 4]]
    b = []
    cols = ["#dbe9f6", "#fbe6d0"]
    for k, pr in enumerate(prims):
        pts = " ".join(f"{P[i][0]},{P[i][1]}" for i in pr)
        b.append(f'<polygon points="{pts}" fill="{cols[k]}" stroke="{INK}" stroke-width="2"/>')
        cx = sum(P[i][0] for i in pr) / 4
        cy = sum(P[i][1] for i in pr) / 4
        b.append(text(cx, cy + 5, f"prim {k}", 15, [BLUE, ORANGE][k], "middle", 650))
    # vertices: a marker pulled inside each corner
    v = 0
    for k, pr in enumerate(prims):
        cx = sum(P[i][0] for i in pr) / 4
        cy = sum(P[i][1] for i in pr) / 4
        for i in pr:
            x = P[i][0] + (cx - P[i][0]) * 0.22
            y = P[i][1] + (cy - P[i][1]) * 0.22
            b.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="#ffffff" stroke="{GREEN}" stroke-width="1.6"/>')
            b.append(text(x, y + 4, str(v), 10.5, GREEN, "middle", 650))
            v += 1
    for i, (x, y) in enumerate(P):
        b.append(f'<circle cx="{x}" cy="{y}" r="6.5" fill="{INK}"/>')
        dy = 22 if y > 150 else -12
        b.append(text(x, y + dy, f"pt {i}", 12.5, INK, "middle", 600))
    # legend
    lx = 460
    b.append(text(lx, 52, "One quad grid, two primitives", 15, INK, weight=650))
    rows = [
        (f'<circle cx="{lx + 8}" cy="82" r="6.5" fill="{INK}"/>', "point: a position (P); shared"),
        (f'<circle cx="{lx + 8}" cy="114" r="9" fill="#fff" stroke="{GREEN}" stroke-width="1.6"/>',
         "vertex: a corner of one primitive,"),
        ("", "  references one point"),
        (f'<rect x="{lx}" y="164" width="17" height="14" fill="#dbe9f6" stroke="{INK}"/>',
         "primitive: ordered list of vertices"),
        (f'<rect x="{lx}" y="196" width="17" height="14" fill="none" stroke="{MUTED}" stroke-dasharray="3 2"/>',
         "detail: one row for the whole geometry"),
    ]
    y = 87
    for shape, label in rows:
        if shape:
            b.append(shape)
        b.append(text(lx + 28, y + (0 if shape else -8), label, 13.5, INK))
        y += 32 if shape else 22
    b.append(text(lx, 252, "pt 1 and pt 4 are shared: 6 points, 8 vertices,", 13, MUTED))
    b.append(text(lx, 270, "2 primitives, 1 detail row.", 13, MUTED))
    b.append(f'<rect x="28" y="30" width="400" height="262" rx="10" fill="none" stroke="{MUTED}" '
             f'stroke-dasharray="5 4"/>')
    b.append(text(40, 50, "detail", 12.5, MUTED, italic=True))
    return svg(760, 310, "\n".join(b), "Points, vertices, primitives and detail")


# ───────────────────────────────────────────── attribute classes
def attribute_classes():
    b = []
    tables = [
        ("Point", 6, ["P", "N", "Cd"], BLUE, 30),
        ("Vertex", 8, ["point", "uv"], GREEN, 220),
        ("Primitive", 2, ["name", "Cd"], ORANGE, 410),
        ("Detail", 1, ["iteration"], PURPLE, 600),
    ]
    for title, n, attrs, col, x in tables:
        w = 160
        b.append(box(x, 40, w, 30, col, col, 6))
        b.append(text(x + w / 2, 60, f"{title} ({n} row{'s' if n > 1 else ''})", 14, "#fff", "middle", 650))
        cw = w / len(attrs)
        for j, a in enumerate(attrs):
            b.append(text(x + cw * j + cw / 2, 90, a, 12.5, MUTED, "middle", 600))
        for r in range(n):
            y = 98 + r * 22
            b.append(box(x, y, w, 20, "#f4f6f9" if r % 2 == 0 else "#ffffff", LINE, 3))
            b.append(text(x - 6, y + 14.5, str(r), 11, MUTED, "end"))
    # promotion arrows
    ys = 300
    pairs = [(110, 300, "Attribute Promote"), (300, 490, "Attribute Promote"), (490, 680, "Attribute Promote")]
    for x1, x2, lab in pairs:
        b.append(f'<path d="M{x1} {ys} C{x1} {ys + 40},{x2} {ys + 40},{x2} {ys}" fill="none" stroke="{MUTED}" '
                 f'stroke-width="1.6" marker-start="url(#arr)" marker-end="url(#arr)"/>')
    b.append(text(395, ys + 62, "Attribute Promote moves values between classes (average, min, max, sum, first ...)",
                  13.5, INK, "middle"))
    b.append(text(395, ys + 82, "A vertex reads the point it references; a point gathers from the vertices that use it.",
                  13, MUTED, "middle"))
    return svg(790, 400, "\n".join(b), "Attribute classes and promotion")


# ───────────────────────────────────────────── VDB slice
def vdb_slice():
    b = []
    nx, ny, cs = 16, 11, 26
    x0, y0 = 30, 40
    cx, cy, rad = 7.6, 5.2, 3.6
    bg = 3.0
    for j in range(ny):
        for i in range(nx):
            d = math.hypot(i - cx, j - cy) - rad
            active = abs(d) <= bg
            if active:
                t = max(-1.0, min(1.0, d / bg))
                # inside (t < 0) blue, outside (t > 0) orange, paler towards the surface
                col = (f"rgb({int(255 - 120 * max(-t, 0))},{int(255 - 90 * abs(t))},{int(255 - 120 * max(t, 0))})")
            else:
                col = "#eef0f3" if d > 0 else "#d5dbe4"
            b.append(f'<rect x="{x0 + i * cs}" y="{y0 + j * cs}" width="{cs}" height="{cs}" fill="{col}" '
                     f'stroke="#ffffff" stroke-width="1"/>')
            if not active:
                b.append(text(x0 + i * cs + cs / 2, y0 + j * cs + cs / 2 + 4, "+bg" if d > 0 else "−bg",
                              8.5, "#9aa2ad", "middle"))
    b.append(f'<circle cx="{x0 + cx * cs + cs / 2}" cy="{y0 + cy * cs + cs / 2}" r="{rad * cs}" fill="none" '
             f'stroke="{INK}" stroke-width="2.2"/>')
    lx = x0 + nx * cs + 30
    b.append(text(lx, 62, "SDF VDB, one slice", 15, INK, weight=650))
    items = [
        ("rgb(135,165,255)", "active, inside (negative distance)"),
        ("rgb(255,165,135)", "active, outside (positive distance)"),
        ("#eef0f3", "inactive outside: holds +background"),
        ("#d5dbe4", "inactive inside: holds −background"),
    ]
    for k, (c, lab) in enumerate(items):
        y = 84 + k * 28
        b.append(f'<rect x="{lx}" y="{y}" width="18" height="18" fill="{c}" stroke="{LINE}"/>')
        b.append(text(lx + 28, y + 14, lab, 13.5))
    b.append(f'<line x1="{lx}" y1="207" x2="{lx + 18}" y2="207" stroke="{INK}" stroke-width="2.2"/>')
    b.append(text(lx + 28, 212, "the surface (distance 0)", 13.5))
    notes = ["The active band is ±background wide (3 voxels",
             "by default). Samples beyond the grid read the",
             "background. A fog VDB is the same with values",
             "0..1 and background 0; dense volumes have every",
             "voxel active and stream their edge values."]
    for k, s in enumerate(notes):
        b.append(text(lx, 252 + k * 19, s, 13, MUTED))
    return svg(lx + 330, y0 + ny * cs + 30, "\n".join(b), "VDB active band and background")


# ───────────────────────────────────────────── For-Each loop
def foreach_loop():
    b = []
    b.append(box(30, 120, 150, 54, "#eaf2fa", BLUE))
    b.append(text(105, 143, "For-Each Begin", 14, INK, "middle", 650))
    b.append(text(105, 162, "split by piece", 12, MUTED, "middle"))
    for k in range(3):
        y = 50 + k * 70
        b.append(box(250, y, 210, 50, "#ffffff", LINE))
        b.append(text(355, y + 21, f"loop body · iteration {k}", 13, INK, "middle", 600))
        b.append(text(355, y + 39, f"piece {k}" + ("" if k < 2 else " …"), 12, MUTED, "middle"))
        b.append(arrow(182, 147, 248, y + 25))
        b.append(arrow(462, y + 25, 528, 147))
    b.append(box(530, 120, 150, 54, "#eaf2fa", BLUE))
    b.append(text(605, 143, "For-Each End", 14, INK, "middle", 650))
    b.append(text(605, 162, "merge (or feedback)", 12, MUTED, "middle"))
    b.append(text(355, 268, "The body runs once per piece / number / count; End gathers the results.", 13, MUTED,
                  "middle"))
    b.append(text(355, 287, "Feedback passes each result to the next iteration instead.", 13, MUTED, "middle"))
    return svg(710, 305, "\n".join(b), "For-Each loop")


# ───────────────────────────────────────────── COP layers
def cop_layers():
    b = []
    layers = [("C", 3, "#e9d2c5"), ("height", 1, "#d8d8d8"), ("N", 3, "#c7cdf3"), ("mask", 1, "#e9e9e9")]
    for k, (name, ch, col) in enumerate(layers):
        x, y = 40 + k * 26, 60 + k * 22
        b.append(f'<rect x="{x}" y="{y}" width="190" height="130" rx="6" fill="{col}" stroke="{INK}" '
                 f'stroke-width="1.2"/>')
        b.append(text(x + 10, y + 20, f"{name}  ({ch} ch)", 13, INK, weight=650))
    b.append(text(150, 40, "COPIMAGE: named layers, one resolution", 14, INK, "middle", 650))
    b.append(arrow(330, 160, 440, 160))
    b.append(text(385, 150, "To Image", 12, MUTED, "middle"))
    b.append(text(385, 182, "From Image", 12, MUTED, "middle"))
    b.append(arrow(440, 172, 330, 172))
    for k in range(3):
        b.append(f'<rect x="{460 + k * 12}" y="{90 + k * 12}" width="170" height="120" rx="4" fill="#f4f6f9" '
                 f'stroke="{MUTED}"/>')
    b.append(text(560, 175, "RGB", 13, INK, "middle", 650))
    b.append(text(560, 70, "ComfyUI IMAGE: a batch of RGB", 14, INK, "middle", 650))
    b.append(text(345, 288, "COP nodes read and write layers by name (C, height, N, mask ...); bridges convert to the",
                  13, MUTED, "middle"))
    b.append(text(345, 306, "IMAGE / MASK types that the rest of ComfyUI uses.", 13, MUTED, "middle"))
    return svg(690, 324, "\n".join(b), "COP image layers and ComfyUI images")


# ───────────────────────────────────────────── data flow
def pipeline():
    b = []
    steps = [("Grid", "generate", BLUE), ("Wrangle", "attributes", BLUE), ("Scatter", "points", BLUE),
             ("Copy to Points", "instances", BLUE), ("Render Pass", "depth / normal / id", ORANGE),
             ("KSampler", "ControlNet · ComfyUI", GREEN), ("UV Backproject", "texture", ORANGE)]
    x, y = 24, 50
    w, h, gap = 150, 58, 26
    for k, (name, sub, col) in enumerate(steps):
        if k == 4:
            x, y = 24 + (w + gap) * 0.5, 160
        b.append(box(x, y, w, h, "#ffffff", col, 8, ' stroke-width="2"'))
        b.append(text(x + w / 2, y + 25, name, 14, INK, "middle", 650))
        b.append(text(x + w / 2, y + 44, sub, 12, MUTED, "middle"))
        nx = x + w + gap
        if k == 3:
            b.append(f'<path d="M{x + w / 2} {y + h} L{x + w / 2} {y + h + 26} L{24 + (w + gap) * 0.5 + w / 2} '
                     f'{y + h + 26} L{24 + (w + gap) * 0.5 + w / 2} {158}" fill="none" stroke="{MUTED}" '
                     f'stroke-width="1.6" marker-end="url(#arr)"/>')
        elif k < len(steps) - 1:
            b.append(arrow(x + w + 2, y + h / 2, nx - 2, y + h / 2))
        x = nx
    b.append(text(24, 32, "Geometry (SOP), images (COP) and diffusion models in one ComfyUI graph", 14, INK,
                  weight=650))
    legend = [(BLUE, "geometry nodes"), (ORANGE, "render / bake nodes"), (GREEN, "ComfyUI nodes")]
    for k, (c, lab) in enumerate(legend):
        lx = 24 + k * 190
        b.append(f'<rect x="{lx}" y="252" width="14" height="14" rx="3" fill="none" stroke="{c}" stroke-width="2"/>')
        b.append(text(lx + 22, 264, lab, 13, MUTED))
    return svg(730, 285, "\n".join(b), "From procedural geometry to AI textures")


# ───────────────────────────────────────────── wires (the geometry is web/pcg_wires.js's, ported)
W_STUB, W_RADIUS = 8, 40


def _elbow(a, b, radius=W_RADIUS):
    """pcg_wires.js elbow(): stub out of the output, a rounded turn, a vertical run near the output, into the input."""
    ax, dy = a[0] + W_STUB, abs(b[1] - a[1])
    room = (b[0] - ax) / 2
    if room >= 0:
        r = max(0, min(radius, room, dy / 2))
        xv = ax + r
        return [a, (ax, a[1]), (xv, a[1]), (xv, b[1]), b], r
    bx = b[0] - W_STUB
    m = (ax + bx) / 2
    r = max(0, min(radius, abs(m - ax), dy / 2))
    return [a, (ax, a[1]), (m, a[1]), (m, b[1]), (bx, b[1]), b], r


def _elbow_path(a, b):
    pts, r = _elbow(a, b)
    d = [f"M{pts[0][0]:.1f} {pts[0][1]:.1f}"]
    for i in range(1, len(pts)):
        if r > 0.01 and i in (2, 3):
            p0, p1, p2 = pts[i - 1], pts[i], pts[i + 1]
            ux, uy = (p0[0] - p1[0]), (p0[1] - p1[1])
            lu = math.hypot(ux, uy) or 1
            vx, vy = (p2[0] - p1[0]), (p2[1] - p1[1])
            lv = math.hypot(vx, vy) or 1
            s = (p1[0] + ux / lu * r, p1[1] + uy / lu * r)
            e = (p1[0] + vx / lv * r, p1[1] + vy / lv * r)
            d.append(f"L{s[0]:.1f} {s[1]:.1f} Q{p1[0]:.1f} {p1[1]:.1f} {e[0]:.1f} {e[1]:.1f}")
        else:
            d.append(f"L{pts[i][0]:.1f} {pts[i][1]:.1f}")
    return " ".join(d)


def _elbow_samples(a, b, n=12):
    """The rounded elbow as a polyline (arcs sampled), for highlighting a part of it by arc length."""
    pts, r = _elbow(a, b)
    out = [pts[0]]
    for i in range(1, len(pts)):
        if r > 0.01 and i in (2, 3):
            p0, p1, p2 = pts[i - 1], pts[i], pts[i + 1]
            u = ((p0[0] - p1[0]), (p0[1] - p1[1]))
            lu = math.hypot(*u) or 1
            v = ((p2[0] - p1[0]), (p2[1] - p1[1]))
            lv = math.hypot(*v) or 1
            u, v = (u[0] / lu, u[1] / lu), (v[0] / lv, v[1] / lv)
            c = (p1[0] + (u[0] + v[0]) * r, p1[1] + (u[1] + v[1]) * r)
            a0 = math.atan2(p1[1] + u[1] * r - c[1], p1[0] + u[0] * r - c[0])
            a1 = math.atan2(p1[1] + v[1] * r - c[1], p1[0] + v[0] * r - c[0])
            da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
            out += [(c[0] + r * math.cos(a0 + da * k / n), c[1] + r * math.sin(a0 + da * k / n)) for k in range(n + 1)]
        else:
            out.append(pts[i])
    return out


def _part(poly, t0, t1):
    """The piece of a polyline between fractions t0..t1 of its length, as an SVG path."""
    seg = [math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(poly, poly[1:])]
    tot = sum(seg)
    out, acc = [], 0.0
    for (p, q), L in zip(zip(poly, poly[1:]), seg):
        for t in (t0 * tot, t1 * tot):
            if acc <= t <= acc + L and L > 0:
                f = (t - acc) / L
                out.append((acc + f * L, (p[0] + f * (q[0] - p[0]), p[1] + f * (q[1] - p[1]))))
        if t0 * tot <= acc + L and acc + L <= t1 * tot:
            out.append((acc + L, q))
        acc += L
    out.sort(key=lambda x: x[0])
    return "M" + " L".join(f"{x:.1f} {y:.1f}" for _, (x, y) in out)


def _spline_path(a, b):
    dd = max(30, math.hypot(b[0] - a[0], b[1] - a[1]) * 0.25)
    return f"M{a[0]} {a[1]} C{a[0] + dd} {a[1]} {b[0] - dd} {b[1]} {b[0]} {b[1]}"


def _straight_path(a, b):
    ax, bx = a[0] + 10, b[0] - 10
    m = (ax + bx) / 2
    return f"M{a[0]} {a[1]} L{ax} {a[1]} L{m} {a[1]} L{m} {b[1]} L{bx} {b[1]} L{b[0]} {b[1]}"


def _node(x, y, w, h, name, outs=1, ins=1, fill="#2b2f36"):
    b = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="{fill}" stroke="#4a505a"/>',
         f'<rect x="{x}" y="{y}" width="{w}" height="22" rx="7" fill="#3a3f48"/>',
         text(x + 10, y + 16, name, 12, "#e8ebef", weight=600)]
    for k in range(ins):
        b.append(f'<circle cx="{x}" cy="{y + 38 + 20 * k}" r="4.5" fill="#7aa8d8"/>')
    for k in range(outs):
        b.append(f'<circle cx="{x + w}" cy="{y + 38 + 20 * k}" r="4.5" fill="#7aa8d8"/>')
    return "\n".join(b)


def _wire(d, color="#7aa8d8", w=2.4, dash=""):
    ds = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{w}"{ds} stroke-linecap="round"/>'


def wire_styles():
    b = []
    panels = [("Houdini rounded polyline (default)", _elbow_path),
              ("ComfyUI: Spline", _spline_path), ("ComfyUI: Straight", _straight_path)]
    for k, (title, fn) in enumerate(panels):
        ox = 20 + k * 300
        b.append(f'<rect x="{ox}" y="40" width="280" height="250" rx="8" fill="#1f2228"/>')
        b.append(text(ox + 140, 28, title, 14, INK, "middle", 650))
        b.append(_node(ox + 14, 62, 90, 56, "Grid"))
        b.append(_node(ox + 176, 168, 90, 56, "Scatter"))
        b.append(_wire(fn((ox + 104, 100), (ox + 176, 206))))
    b.append(text(470, 318, "Settings → PCG → Houdini feel → Link style. The Houdini style turns right after the output, runs",
                  13, MUTED, "middle"))
    b.append(text(470, 336, "vertically near the output and comes into the input in one long horizontal run; corner radius 40.",
                  13, MUTED, "middle"))
    return svg(940, 352, "\n".join(x for x in b if x), "Wire styles")


def wire_editing():
    b = ['<rect x="20" y="20" width="900" height="330" rx="8" fill="#1f2228"/>']
    # ① the three thirds of a wire
    a, e = (150, 90), (420, 170)
    b.append(_node(60, 52, 90, 56, "Box"))
    b.append(_node(420, 132, 100, 56, "Transform"))
    poly = _elbow_samples(a, e)
    b.append(_wire(_elbow_path(a, e), "#7aa8d8", 2.4))
    for t0, t1, col in ((0.0, 1 / 3, ORANGE), (2 / 3, 1.0, GREEN)):
        b.append(f'<path d="{_part(poly, t0, t1)}" fill="none" stroke="{col}" stroke-width="7" '
                 f'stroke-opacity="0.55" stroke-linecap="round" stroke-linejoin="round"/>')
    b.append(text(205, 128, "first third: pull a new", 12, "#f0c38e"))
    b.append(text(205, 144, "upstream for this input", 12, "#f0c38e"))
    b.append(text(300, 196, "last third: move the input end", 12, "#9ad3a8"))
    b.append(text(300, 212, "(drop on empty canvas = disconnect)", 12, "#9ad3a8"))
    b.append(text(70, 40, "① Drag near a wire end to rewire it", 13, "#e8ebef", weight=650))
    # ② cutting with Y
    b.append(text(560, 40, "② Hold Y and drag across wires to cut them", 13, "#e8ebef", weight=650))
    b.append(_node(570, 60, 80, 76, "Grid", outs=2))
    b.append(_node(800, 60, 90, 76, "Merge", ins=2))
    b.append(_wire(_elbow_path((650, 98), (800, 98))))
    b.append(_wire(_elbow_path((650, 118), (800, 118))))
    b.append(f'<line x1="720" y1="70" x2="735" y2="150" stroke="{RED}" stroke-width="2.4" stroke-dasharray="6 4"/>')
    b.append(text(745, 160, "cut line", 12, "#f2a49d"))
    # ③ loop wire colour, ④ reference lines
    b.append(text(70, 252, "③ The For-Each loop wire is orange", 13, "#e8ebef", weight=650))
    b.append(_node(70, 268, 120, 56, "For-Each Begin"))
    b.append(_node(330, 268, 120, 56, "For-Each End"))
    b.append(_wire(_elbow_path((190, 306), (330, 306)), "#f0a63c", 2.4))
    b.append(text(560, 252, "④ Selected node: dashed lines to its references", 13, "#e8ebef", weight=650))
    b.append(_node(580, 268, 110, 56, "CTRL (Params)", fill="#2b3a46"))
    b.append(_node(780, 268, 110, 56, "Tube"))
    b.append('<line x1="690" y1="296" x2="780" y2="296" stroke="rgba(210,214,220,0.6)" stroke-width="1.2" '
             'stroke-dasharray="3 3"/>')
    b.append(text(470, 372, "① and ④ can be switched off in Settings → PCG → Houdini feel; ② and ③ are always on.",
                  13, MUTED, "middle"))
    return svg(940, 388, "\n".join(b), "Editing wires")


DIAGRAMS = {
    "geometry-elements.svg": geometry_elements,
    "attribute-classes.svg": attribute_classes,
    "vdb-slice.svg": vdb_slice,
    "foreach-loop.svg": foreach_loop,
    "cop-layers.svg": cop_layers,
    "pipeline.svg": pipeline,
    "wire-styles.svg": wire_styles,
    "wire-editing.svg": wire_editing,
}


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, fn in DIAGRAMS.items():
        with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(fn())
    print(f"{len(DIAGRAMS)} diagrams -> {OUT}")


if __name__ == "__main__":
    main()
