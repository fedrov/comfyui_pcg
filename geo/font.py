"""
Font SOP -- text -> outlines / filled faces / extruded solids.

━━ Where glyphs come from
fontTools reads the **vector outlines** in the font file (TrueType quadratic Bezier and CFF/OTF cubic
Bezier both work; for .ttc the first font is used). It used to be only COP Text rasterization followed by Trace, giving jagged
polyline edges whose shape changed with resolution; here the curves are exact, subdivided evenly into polylines by Curve Segments.

Font accepts:
  - a file path (D:/fonts/xxx.otf)
  - a file name (arial, msyh, DejaVuSans -- case-insensitive, extension optional)
  - a family name (Arial, Microsoft YaHei)
searched in the system font directories (Windows Fonts, the user font directory; common locations on macOS / Linux) and
matplotlib's bundled DejaVu. Empty = the first available in the order arial -> DejaVuSans.

Characters missing from the main font (e.g. CJK characters in Arial) are looked up font by font in the Fallback list
(default msyh / simhei / simsun / Noto Sans CJK / PingFang / DejaVuSans); the report
lists which characters used which font and which were found nowhere (skipped, no tofu boxes drawn).

━━ Layout
Size is the em height (the length corresponding to the font design units unitsPerEm), consistent with the Font Size of Houdini's Font.
Advance widths are read from hmtx; Tracking adds letter spacing as a fraction of the em; if the font has an old-style kern table its
pair kerning is used (kerning in OpenType GPOS is **not implemented** -- most modern fonts only put it in GPOS,
so spacing comes out a little looser than in layout software). Line breaks use \\n, line height = (ascent - descent + lineGap) *
Line Spacing. Alignment: horizontal left / center / right (each line aligned separately), vertical baseline (first line's
baseline at y = 0) / top / center / bottom. Text lies in the XY plane, facing +Z.

━━ Three outputs
  outline   one closed polygon per contour, prim attribute hole (hole = 1)
  faces     filled with triangles (constrained Delaunay, even-odd rule: holes cut out of outer contours, islands inside holes filled again)
  extrude   front (z = 0, facing +Z) + back (z = -Depth, facing -Z) + side walls, watertight, normals facing outwards

Contour directions are unified first: even nesting depth (outer contours) counter-clockwise, odd (holes) clockwise -- TrueType
puts outer contours clockwise, CFF counter-clockwise; without unifying, half of the side walls would face inwards.

prim attributes: char (which character the face belongs to), char_index (index of the character in the text, spaces and line breaks
counted too), line (line number). extrude also adds the prim groups front / back / side.

Not implemented: fonts whose contours overlap themselves (some static instances of variable fonts do this) are filled by the even-odd rule, so overlapping
parts become holes -- that needs a contour union first (skia-pathops), which is not a dependency here.
"""
from __future__ import annotations

import os
import sys

import numpy as np

from .core import Geometry, POINT, PRIM

MODES = ("outline", "faces", "extrude")
HALIGN = ("left", "center", "right")
VALIGN = ("baseline", "top", "center", "bottom")
DEFAULT_FALLBACK = "msyh simhei simsun NotoSansCJK NotoSerifCJK PingFang DejaVuSans"

_CACHE = {}          # path -> TTFont
_NAMES = None        # family name index (lower-case family name -> path), built the first time a family name is looked up


def font_dirs():
    d = []
    if sys.platform.startswith("win"):
        win = os.environ.get("WINDIR", r"C:\Windows")
        d.append(os.path.join(win, "Fonts"))
        la = os.environ.get("LOCALAPPDATA")
        if la:
            d.append(os.path.join(la, "Microsoft", "Windows", "Fonts"))
    elif sys.platform == "darwin":
        d += ["/System/Library/Fonts", "/Library/Fonts",
              os.path.expanduser("~/Library/Fonts")]
    else:
        d += ["/usr/share/fonts", "/usr/local/share/fonts",
              os.path.expanduser("~/.fonts"),
              os.path.expanduser("~/.local/share/fonts")]
    try:
        import matplotlib
        d.append(os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data",
                              "fonts", "ttf"))
    except Exception:
        pass
    return [x for x in d if os.path.isdir(x)]


def _font_files():
    out = []
    for root in font_dirs():
        for dp, _, fs in os.walk(root):
            for f in fs:
                if f.lower().endswith((".ttf", ".otf", ".ttc")):
                    out.append(os.path.join(dp, f))
    return out


def find_font(name):
    """Name / file name / family name -> path; None if not found."""
    global _NAMES
    name = str(name).strip()
    if not name:
        return None
    if os.path.isfile(name):
        return name
    key = name.lower().replace(" ", "")
    key0 = os.path.splitext(key)[0] if key.endswith((".ttf", ".otf", ".ttc")) \
        else key
    files = _font_files()
    for f in files:                                   # exact file name match
        if os.path.splitext(os.path.basename(f))[0].lower().replace(" ", "") \
                == key0:
            return f
    for f in sorted(files, key=len):                  # file name prefix (NotoSansCJK-*)
        if os.path.basename(f).lower().replace(" ", "").startswith(key0):
            return f
    if _NAMES is None:                                # family name (reads the name table, slow, cached)
        _NAMES = {}
        from fontTools.ttLib import TTFont
        for f in files:
            try:
                t = TTFont(f, fontNumber=0, lazy=True)
                for rec in t["name"].names:
                    if rec.nameID in (1, 4):
                        try:
                            nm = rec.toUnicode().lower().replace(" ", "")
                        except Exception:
                            continue
                        _NAMES.setdefault(nm, f)
                t.close()
            except Exception:
                continue
    return _NAMES.get(key0)


def _load(path):
    if path not in _CACHE:
        from fontTools.ttLib import TTFont
        _CACHE[path] = TTFont(path, fontNumber=0, lazy=True)
    return _CACHE[path]


def _require_fonttools():
    try:
        import fontTools  # noqa: F401
    except ImportError:
        raise ImportError("The Font node needs fontTools (pip install fonttools). "
                          "It is usually already in ComfyUI's environment (matplotlib depends on it)")


class _Flatten:
    """fontTools pen: subdivides Beziers evenly into polylines and collects closed contours."""

    def __init__(self, glyphset, seg):
        from fontTools.pens.basePen import BasePen

        outer = self

        class Pen(BasePen):
            def _moveTo(self, p):
                outer.cur = [p]

            def _lineTo(self, p):
                outer.cur.append(p)

            def _curveToOne(self, p1, p2, p3):
                p0 = outer.cur[-1]
                for t in np.linspace(0, 1, outer.seg + 1)[1:]:
                    u = 1 - t
                    outer.cur.append(tuple(
                        u ** 3 * np.array(p0) + 3 * u * u * t * np.array(p1)
                        + 3 * u * t * t * np.array(p2) + t ** 3 * np.array(p3)))

            def _qCurveToOne(self, p1, p2):
                p0 = outer.cur[-1]
                for t in np.linspace(0, 1, outer.seg + 1)[1:]:
                    u = 1 - t
                    outer.cur.append(tuple(u * u * np.array(p0) + 2 * u * t *
                                           np.array(p1) + t * t * np.array(p2)))

            def _closePath(self):
                outer.contours.append(outer.cur)
                outer.cur = []

            def _endPath(self):
                outer.contours.append(outer.cur)
                outer.cur = []

        self.seg = max(1, int(seg))
        self.contours = []
        self.cur = []
        self.pen = Pen(glyphset)


def _clean(c):
    """Removes consecutive duplicate points and the duplicated closing point; contours with < 3 points or zero area are dropped."""
    a = np.asarray(c, np.float64).reshape(-1, 2)
    if len(a) == 0:
        return None
    keep = np.r_[True, np.any(np.abs(np.diff(a, axis=0)) > 1e-9, axis=1)]
    a = a[keep]
    while len(a) > 1 and np.allclose(a[0], a[-1], atol=1e-9):
        a = a[:-1]
    if len(a) < 3:
        return None
    if abs(_area(a)) < 1e-12:
        return None
    return a


def _area(a):
    x, y = a[:, 0], a[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _inside(pt, poly):
    x, y = pt
    xs, ys = poly[:, 0], poly[:, 1]
    xs2, ys2 = np.roll(xs, -1), np.roll(ys, -1)
    cond = (ys > y) != (ys2 > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xi = xs + (y - ys) * (xs2 - xs) / (ys2 - ys)
    return int(np.count_nonzero(cond & (x < xi))) % 2 == 1


def _orient(contours):
    """Even nesting depth -> counter-clockwise, odd -> clockwise. Returns (contour list, depth list)."""
    out, dep = [], []
    for i, c in enumerate(contours):
        # Use edge midpoints as probes (avoids vertices shared with other contours)
        probe = 0.5 * (c[0] + c[1])
        d = sum(_inside(probe, o) for j, o in enumerate(contours) if j != i)
        ccw = _area(c) > 0
        if (d % 2 == 0) != ccw:
            c = c[::-1]
        out.append(c)
        dep.append(d)
    return out, dep


def _glyph_contours(font, gname, seg):
    gs = font.getGlyphSet()
    fl = _Flatten(gs, seg)
    gs[gname].draw(fl.pen)
    cs = [_clean(c) for c in fl.contours]
    return [c for c in cs if c is not None]


def _kern_table(font):
    try:
        k = font["kern"]
    except Exception:
        return {}
    out = {}
    for t in getattr(k, "kernTables", []):
        if getattr(t, "coverage", 1) & 1 and hasattr(t, "kernTable"):
            out.update(t.kernTable)
    return out


def _fill(contours):
    """Even-odd fill: constrained Delaunay; returns triangles (indices into the concatenated points of contours)."""
    from .triangulate2d import triangulate2d
    P = np.vstack(contours)
    off = np.cumsum([0] + [len(c) for c in contours])
    F = [list(range(off[i], off[i + 1])) for i in range(len(contours))]
    g = Geometry.from_mesh(np.c_[P, np.zeros(len(P))], F, closed=True)
    Pq = np.asarray(g.get(POINT, "P"))[:, :2]            # coordinates after float32 quantization
    o = triangulate2d(g, plane="xy", region="remove_outside", fuse_tol=0.0)
    Po = np.asarray(o.get(POINT, "P"))[:, :2]
    look = {(float(x), float(y)): i for i, (x, y) in enumerate(Pq)}
    idx = np.array([look.get((float(x), float(y)), -1) for x, y in Po])
    T = []
    for p in range(o.nprims):
        v = o.prim_points(p)
        if len(v) != 3:
            continue
        t = idx[v]
        if (t < 0).any():
            raise ValueError("Triangulation added new points (self-intersecting contours?); this character can't be filled")
        # No need to check winding: triangulate2d always outputs counter-clockwise triangles in the xy plane (guaranteed
        # by its _ccw), so the front faces +Z. The extrude orientation consistency test watches this
        T.append(t)
    return np.array(T, np.int64).reshape(-1, 3)


def font(text="Hello", font_name="", size=1.0, mode="faces", depth=0.2,
         curve_segments=6, tracking=0.0, line_spacing=1.0, halign="left",
         valign="baseline", fallback=DEFAULT_FALLBACK):
    """Returns (geo, report)."""
    _require_fonttools()
    if mode not in MODES:
        raise ValueError(f"Mode must be one of {MODES}")
    if halign not in HALIGN or valign not in VALIGN:
        raise ValueError(f"Alignment must be one of {HALIGN} / {VALIGN}")
    if float(size) <= 0:
        raise ValueError("Size must be greater than 0")
    if mode == "extrude" and float(depth) <= 0:
        raise ValueError("Depth must be greater than 0 in extrude mode")
    path = None
    if str(font_name).strip():
        path = find_font(font_name)
        if path is None:
            raise ValueError(f"Font '{font_name}' not found. Enter a file path, a file name "
                             f"(arial / msyh) or a family name; directories searched: {font_dirs()}")
    else:
        for cand in ("arial", "DejaVuSans"):
            path = find_font(cand)
            if path:
                break
        if path is None:
            raise ValueError(f"No default font (arial / DejaVuSans) found on the system; "
                             f"enter a font file path in Font. Searched: {font_dirs()}")
    fonts = [path] + [p for p in (find_font(n) for n in str(fallback).split())
                      if p and p != path]
    loaded = [_load(p) for p in fonts]
    cmaps = [f.getBestCmap() or {} for f in loaded]

    size = float(size)
    prim_font = loaded[0]
    upm0 = prim_font["head"].unitsPerEm
    hh = prim_font["hhea"]
    line_h = (hh.ascent - hh.descent + hh.lineGap) / upm0 * size * \
        float(line_spacing)
    asc = hh.ascent / upm0 * size
    desc = hh.descent / upm0 * size

    glyphs = []           # (character, index, line, x0, font index, glyph name, scale)
    used, missing = {}, []
    lines = str(text).split("\n")
    widths = []
    ci = 0
    for li, line in enumerate(lines):
        x = 0.0
        prev = None
        row = []
        for ch in line:
            fi = next((k for k, cm in enumerate(cmaps) if ord(ch) in cm), None)
            if fi is None:
                missing.append(ch)
                ci += 1
                prev = None
                continue
            f = loaded[fi]
            gname = cmaps[fi][ord(ch)]
            sc = size / f["head"].unitsPerEm
            if prev is not None and prev[0] == fi:
                x += _kern_table(f).get((prev[1], gname), 0) * sc
            row.append((ch, ci, li, x, fi, gname, sc))
            used.setdefault(os.path.basename(fonts[fi]), []).append(ch)
            x += f["hmtx"][gname][0] * sc + float(tracking) * size
            prev = (fi, gname)
            ci += 1
        ci += 1                                        # line breaks also take an index
        w = x - float(tracking) * size if row else 0.0
        widths.append(w)
        glyphs.append(row)
    nlines = len(lines)
    # Vertical: first line's baseline at y = 0, each following line line_h lower
    top = asc
    bottom = -(nlines - 1) * line_h + desc
    dy = {"baseline": 0.0, "top": -top, "bottom": -bottom,
          "center": -(top + bottom) / 2}[valign]

    pts, polys, attrs = [], [], {"char": [], "char_index": [], "line": [],
                                 "hole": [], "part": []}
    npt = 0
    for li, row in enumerate(glyphs):
        dx = {"left": 0.0, "center": -widths[li] / 2,
              "right": -widths[li]}[halign]
        base_y = -li * line_h + dy
        for ch, cidx, _, x0, fi, gname, sc in row:
            cs = _glyph_contours(loaded[fi], gname, curve_segments)
            if not cs:
                continue
            cs = [c * sc + [x0 + dx, base_y] for c in cs]
            cs, dep = _orient(cs)
            P2 = np.vstack(cs)
            off = np.cumsum([0] + [len(c) for c in cs])
            meta = (ch, cidx, li)
            if mode == "outline":
                pts.append(np.c_[P2, np.zeros(len(P2))])
                for k in range(len(cs)):
                    polys.append(list(range(npt + off[k], npt + off[k + 1])))
                    _add(attrs, meta, dep[k] % 2, "outline")
                npt += len(P2)
                continue
            try:
                T = _fill(cs)
            except Exception as e:
                raise ValueError(f"Character '{ch}' (#{cidx}) failed to fill: {e}")
            if mode == "faces":
                pts.append(np.c_[P2, np.zeros(len(P2))])
                for t in T:
                    polys.append(list(npt + t))
                    _add(attrs, meta, 0, "front")
                npt += len(P2)
                continue
            n = len(P2)
            d = float(depth)
            pts.append(np.vstack([np.c_[P2, np.zeros(n)],
                                  np.c_[P2, np.full(n, -d)]]))
            for t in T:
                polys.append(list(npt + t))
                _add(attrs, meta, 0, "front")
            for t in T:
                polys.append(list(npt + n + t[::-1]))
                _add(attrs, meta, 0, "back")
            for k in range(len(cs)):
                a, b = off[k], off[k + 1]
                for i in range(a, b):
                    j = i + 1 if i + 1 < b else a
                    polys.append([npt + i, npt + n + i, npt + n + j, npt + j])
                    _add(attrs, meta, 0, "side")
            npt += 2 * n
    if pts:
        g = Geometry.from_mesh(np.vstack(pts), polys, closed=True)
    else:
        g = Geometry()
    if g.nprims:
        g.set_string(PRIM, "char", np.array(attrs["char"]))
        g.set(PRIM, "char_index", np.array(attrs["char_index"], np.int32)[:, None],
              owned=True)
        g.set(PRIM, "line", np.array(attrs["line"], np.int32)[:, None], owned=True)
        if mode == "outline":
            g.set(PRIM, "hole", np.array(attrs["hole"], np.int32)[:, None],
                  owned=True)
        if mode == "extrude":
            part = np.array(attrs["part"])
            for nm in ("front", "back", "side"):
                g.set_group(PRIM, nm, part == nm)
    rep = {"font": os.path.basename(path), "fonts_used": {k: "".join(v)[:40]
           for k, v in used.items()}, "missing": "".join(missing),
           "lines": nlines, "prims": g.nprims, "points": g.npoints,
           "width": float(max(widths) if widths else 0.0), "line_height": line_h}
    return g, rep


def _add(attrs, meta, hole, part):
    attrs["char"].append(meta[0])
    attrs["char_index"].append(meta[1])
    attrs["line"].append(meta[2])
    attrs["hole"].append(hole)
    attrs["part"].append(part)
