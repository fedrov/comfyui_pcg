"""
Building Generator (after SideFX Labs Building Generator 4.0): footprints -> buildings with floors and facades.

Every polygon of the input (a lot, a block: any simple polygon, taken as seen from above; up is +Y) becomes one
building: its walls are split into floors (Full Floor Height) and each floor's wall into bays (Module Width, the
bays stretched evenly to fill the wall, so no gap is left for a sideslop module). A bay holds one module, named by
the Facade Module Pattern.

    Pattern     module names separated by spaces, repeated along the wall: `window window door`.
                `a|b|c` picks one of them at random per bay (seeded).
    Modules     built in: `wall` (blank), `window`, `door`, `shopfront` (a wide low window), `balcony` (a glazed
                door with a slab and a railing standing out from the wall). With a module library
                connected (second input: geometry whose prims carry a string attribute `name`), a name found there
                wins: the library module's bounding box in x (width) and y (height) is fitted to the bay, z = 0
                is the wall plane and +z points out of the building. Its prim attribute `part` (if any) is kept.
    Corners     a strip (Corner Width) at both ends of every wall: a plain pilaster, or the Convex / Concave Corner
                Module from the library, fitted to the strip.
    Ledges      Top: a band along the top of every floor; Bottom: along its foot. Simple extruded ledges (Houdini's
                Simple Ledges), mitred round the corners.
    Roof        flat, with a parapet, or (over a four-cornered footprint) gable or hip: Roof Pitch degrees, the
                ridge along the longer sides, eaves standing out by Roof Overhang; other footprints get a flat roof.
                Roof Attribute (a string prim attribute: flat / parapet / gable / hip) picks it per footprint.
    Front       Front Pattern (if given) is the ground-floor pattern of the wall whose outward normal is nearest the
                footprint's Front Attribute (a vector prim attribute): the door and shopfronts face the street.
                Front Pattern Attribute (a string prim attribute) gives a footprint its own front pattern
                (shopfronts in a town's core, doors elsewhere); empty values fall back to Front Pattern.
    Chimneys    Chimney Chance: the probability (seeded per building) of a chimney on a gable or hip roof, near
                the ridge (part `chimney`).
    Notch       Notch Attribute (a float prim attribute, 0..0.8) cuts that fraction of the depth and the width out of
                the back corner of a four-cornered footprint (the corner at the start of the side opposite the
                front): an L-shaped building, with a flat roof.
    Yard walls  Yard Wall Height > 0 builds a wall of Yard Wall Thickness along the footprint's own outline (the
                lot line, outside the setback), on every side but the front one (part `yardwall`, floor -3).
    Floors      per building: the footprint's prim attribute Height Attribute (metres) / Full Floor Height, else
                its Floors Attribute, else a seeded random number between Floors Min and Max.
    Plinth      Foundation Depth adds a plain band of wall below the base (part `plinth`, floor -2), so a building
                on uneven ground shows no gap under its walls.
    Setback     Footprint Inset moves the walls in from the footprint (lots touching each other leave streets and
                yards); a footprint too small for it gets no building.
    Overrides   one line per floor: `0: height=4.5 pattern=door shopfront shopfront` (0 = the ground floor,
                -1 = the top floor; height and pattern are both optional).

Output prim attributes: `building` (number), `floor` (-1: roof, -2: plinth, -3: yard wall), `part` and `material` (wall, glass,
frame, door, corner, ledge, roof, parapet, plinth, balcony, railing, chimney, yardwall, or the library's), `module`, and the footprint's own prim attributes; a prim group per part; vertex `uv` in metres (u along
the wall, v up), so a tiling texture keeps its scale; `Cd` per part, or per floor with Color Floors.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM
from .groups import resolve

ROOFS = ("parapet", "flat", "gable", "hip")
BUILTIN = ("wall", "window", "door", "shopfront", "balcony")
_COL = {"wall": (0.72, 0.66, 0.58), "glass": (0.16, 0.22, 0.28), "frame": (0.85, 0.83, 0.80),
        "door": (0.30, 0.20, 0.14), "corner": (0.62, 0.58, 0.52), "ledge": (0.80, 0.78, 0.74),
        "roof": (0.33, 0.33, 0.35), "parapet": (0.66, 0.62, 0.56), "plinth": (0.48, 0.45, 0.41),
        "balcony": (0.70, 0.68, 0.64), "railing": (0.20, 0.20, 0.22), "chimney": (0.55, 0.40, 0.33),
        "yardwall": (0.64, 0.60, 0.53)}


class _Mesh:
    def __init__(self):
        self.P, self.uv, self.faces = [], [], []
        self.part, self.module, self.floor, self.bld = [], [], [], []
        self.src = []
        self.n = 0
        self.cur_src = -1

    def face(self, pts, uvs, part, module, floor, bld):
        k = len(pts)
        self.P.append(np.asarray(pts, np.float64))
        self.uv.append(np.asarray(uvs, np.float64))
        self.faces.append(list(range(self.n, self.n + k)))
        self.n += k
        self.part.append(part)
        self.module.append(module)
        self.floor.append(floor)
        self.bld.append(bld)
        self.src.append(self.cur_src)


def _opening(w, h, x0, x1, y0, y1, inset, fill):
    """Local faces of a bay with a recessed opening. -> [(points (k, 3), part)]."""
    out = []
    if y0 > 1e-9:
        out.append(([(0, 0, 0), (w, 0, 0), (w, y0, 0), (0, y0, 0)], "wall"))
    if y1 < h - 1e-9:
        out.append(([(0, y1, 0), (w, y1, 0), (w, h, 0), (0, h, 0)], "wall"))
    out.append(([(0, y0, 0), (x0, y0, 0), (x0, y1, 0), (0, y1, 0)], "wall"))
    out.append(([(x1, y0, 0), (w, y0, 0), (w, y1, 0), (x1, y1, 0)], "wall"))
    z = -float(inset)
    if inset > 1e-9:                                                # the reveal: four faces looking into the opening
        out.append(([(x0, y0, 0), (x1, y0, 0), (x1, y0, z), (x0, y0, z)], "frame"))
        out.append(([(x1, y1, 0), (x0, y1, 0), (x0, y1, z), (x1, y1, z)], "frame"))
        out.append(([(x0, y1, 0), (x0, y0, 0), (x0, y0, z), (x0, y1, z)], "frame"))
        out.append(([(x1, y0, 0), (x1, y1, 0), (x1, y1, z), (x1, y0, z)], "frame"))
    out.append(([(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)], fill))
    return out


def _builtin(name, w, h, o):
    if name == "wall":
        return [([(0, 0, 0), (w, 0, 0), (w, h, 0), (0, h, 0)], "wall")]
    if name == "window":
        ww = w * o["window_width"]
        y0 = h * o["window_sill"]
        y1 = min(h - 0.05, y0 + h * o["window_height"])
        return _opening(w, h, (w - ww) / 2, (w + ww) / 2, y0, y1, o["inset"], "glass")
    if name == "door":
        ww = min(w * 0.9, 1.1)
        return _opening(w, h, (w - ww) / 2, (w + ww) / 2, 0.0, min(h - 0.05, 2.2), o["inset"], "door")
    if name == "shopfront":
        ww = w * 0.86
        return _opening(w, h, (w - ww) / 2, (w + ww) / 2, min(0.4, 0.15 * h), h * 0.82, o["inset"], "glass")
    if name == "balcony":
        ww = min(w * 0.6, 1.6)
        out = _opening(w, h, (w - ww) / 2, (w + ww) / 2, 0.0, min(h - 0.05, 2.3), o["inset"], "glass")
        x0, x1, d, t, r = 0.1 * w, 0.9 * w, 0.9, 0.15, min(1.0, 0.45 * h)
        out += _box(x0, x1, -t, 0.0, 0.0, d, "balcony")
        out.append(([(x0, 0, d), (x1, 0, d), (x1, r, d), (x0, r, d)], "railing"))           # front
        out.append(([(x0, 0, 0), (x0, 0, d), (x0, r, d), (x0, r, 0)], "railing"))           # sides
        out.append(([(x1, 0, d), (x1, 0, 0), (x1, r, 0), (x1, r, d)], "railing"))
        return out
    raise KeyError(name)


def _box(x0, x1, y0, y1, z0, z1, part):
    """The five faces of a box sticking out of the wall (z = 0 plane, +z out): front, top, bottom, sides."""
    return [([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], part),
            ([(x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0)], part),
            ([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], part),
            ([(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)], part),
            ([(x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1)], part)]


def _library(modules):
    """name -> (points (n, 3) normalised to x, y in 0..1, faces, parts)."""
    lib = {}
    if modules is None or not modules.nprims:
        return lib
    nm = modules.get(PRIM, "name")
    if nm is None or np.asarray(nm).dtype.kind != "U":
        raise ValueError("The module library needs a string prim attribute 'name' (one name per module)")
    nm = np.asarray(nm).reshape(-1)
    part = modules.get(PRIM, "part")
    part = np.asarray(part).reshape(-1) if part is not None and np.asarray(part).dtype.kind == "U" else None
    P = np.asarray(modules.get(POINT, "P"), np.float64)
    vp, off = np.asarray(modules.vertex_point), np.asarray(modules.prim_offset)
    for name in np.unique(nm):
        if not str(name):
            continue
        prims = np.nonzero(nm == name)[0]
        faces = [vp[off[i]:off[i + 1]] for i in prims]
        used = np.unique(np.concatenate(faces))
        Q = P[used]
        lo, hi = Q.min(0), Q.max(0)
        ext = np.maximum(hi - lo, 1e-9)
        Q = np.stack([(Q[:, 0] - lo[0]) / ext[0], (Q[:, 1] - lo[1]) / ext[1], Q[:, 2]], 1)
        remap = {int(p): k for k, p in enumerate(used)}
        lib[str(name)] = (Q, [[remap[int(p)] for p in f] for f in faces],
                          [str(part[i]) if part is not None and str(part[i]) else str(name) for i in prims])
    return lib


def _module(name, w, h, o, lib):
    if name in lib:
        Q, faces, parts = lib[name]
        S = Q * np.array([w, h, 1.0])
        return [(S[f], p) for f, p in zip(faces, parts)]
    if name in BUILTIN:
        return _builtin(name, w, h, o)
    raise ValueError(f"Building Generator: no module '{name}' (built in: {', '.join(BUILTIN)}"
                     + (f"; in the library: {', '.join(sorted(lib))}" if lib else "; no module library connected") + ")")


def _pattern(spec):
    toks = [t for t in str(spec).replace(",", " ").split() if t]
    return [t.split("|") for t in toks] or [["wall"]]


def _overrides(spec):
    out = {}
    for ln in str(spec).splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if ":" not in ln:
            raise ValueError(f"Floor Overrides: expected 'index: height=H pattern=...', got '{ln}'")
        idx, rest = ln.split(":", 1)
        e = {}
        rest = rest.strip()
        if "pattern=" in rest:
            rest, pat = rest.split("pattern=", 1)
            e["pattern"] = _pattern(pat)
        for tok in rest.split():
            if tok.startswith("height="):
                e["height"] = float(tok[7:])
            else:
                raise ValueError(f"Floor Overrides: unknown setting '{tok}' (height=, pattern=)")
        out[int(idx)] = e
    return out


def _offset(p, d):
    """Mitred offset of the counter-clockwise polygon p (n, 2) by d (outward > 0)."""
    e = np.roll(p, -1, axis=0) - p
    e = e / np.maximum(np.linalg.norm(e, axis=1, keepdims=True), 1e-12)
    nr = np.stack([e[:, 1], -e[:, 0]], 1)                           # outward normal of edge i (i -> i + 1)
    n0 = np.roll(nr, 1, axis=0)                                     # of the edge arriving at vertex i
    den = np.maximum(1.0 + (n0 * nr).sum(1, keepdims=True), 0.25)   # mitre limit 4
    return p + (n0 + nr) / den * d


def _face_up(M, pts, uvs, part, module, floor, bld, outward=None):
    """A face whose normal points up (or along `outward`, for a wall)."""
    P = np.asarray(pts, np.float64)
    q = P - P.mean(0)
    n = np.cross(q, np.roll(q, -1, axis=0)).sum(0)
    ref = np.array([0.0, 1.0, 0.0]) if outward is None else np.asarray(outward, np.float64)
    if n @ ref < 0:
        P, uvs = P[::-1], np.asarray(uvs)[::-1]
    M.face(P, uvs, part, module, floor, bld)


def _pitched_roof(M, p, y, base, kind, pitch, overhang, nb):
    """
    A gable or hip roof over a four-cornered footprint p (CCW, (x, z)) whose walls end at height y. The ridge runs
    along the longer pair of opposite sides, at tan(pitch) x half the span above the eaves; the eaves stand out by
    overhang (and drop with the slope). Gable ends are walls (part wall); a hip roof slopes on all four sides (a
    pyramid where the ridge would have no length).
    """
    tn = np.tan(np.radians(np.clip(pitch, 5.0, 75.0)))
    e = np.roll(p, -1, axis=0) - p
    Ls = np.linalg.norm(e, axis=1)
    k = 0 if Ls[0] + Ls[2] >= Ls[1] + Ls[3] else 1                 # sides k and k + 2 carry the eaves
    q = _offset(p, overhang) if overhang > 0 else p
    ye = y - overhang * tn
    i0, i1, i2, i3 = k, (k + 1) % 4, (k + 2) % 4, (k + 3) % 4
    span = 0.5 * (Ls[i1] + Ls[i3])
    h = y + tn * span * 0.5                                         # ridge height
    Ra = 0.5 * (q[i3] + q[i0])                                      # ridge ends, over the gable sides
    Rb = 0.5 * (q[i1] + q[i2])
    ax = Rb - Ra
    la = float(np.linalg.norm(ax))
    ax = ax / max(la, 1e-9)
    perp = np.array([-ax[1], ax[0]])

    def v3(xz, yy):
        return (xz[0], yy, xz[1])

    def uvs(pts):
        P = np.asarray(pts, np.float64)
        o = q[i0]
        return [((pp[[0, 2]] - o) @ ax, abs((pp[[0, 2]] - o) @ perp) / max(np.cos(np.arctan(tn)), 1e-6), 0)
                for pp in P]
    if kind == "hip":
        hw = 0.5 * float(np.linalg.norm(q[i1] - q[i2]))             # half the (overhung) span
        if la <= 2 * hw:                                             # a pyramid
            Ra = Rb = 0.5 * (Ra + Rb)
        else:
            Ra, Rb = Ra + ax * hw, Rb - ax * hw
    sl1 = [v3(q[i0], ye), v3(q[i1], ye), v3(Rb, h), v3(Ra, h)]
    sl2 = [v3(q[i2], ye), v3(q[i3], ye), v3(Ra, h), v3(Rb, h)]
    if kind == "hip" and np.allclose(Ra, Rb):
        sl1, sl2 = sl1[:3], sl2[:3]
    _face_up(M, sl1, uvs(sl1), "roof", "roof", -1, nb)
    _face_up(M, sl2, uvs(sl2), "roof", "roof", -1, nb)
    if kind == "hip":
        for a_, b_, r_ in ((i1, i2, Rb), (i3, i0, Ra)):
            t_ = [v3(q[a_], ye), v3(q[b_], ye), v3(r_, h)]
            _face_up(M, t_, uvs(t_), "roof", "roof", -1, nb)
        # the soffit (underside of the eaves) is left open, as in most game roofs seen from the street
        return
    # gable ends: wall triangles over the end walls, facing out
    for a_, b_ in ((i1, i2), (i3, i0)):
        A, B = p[a_], p[b_]
        mid = 0.5 * (A + B)
        out = np.array([(B - A)[1], 0.0, -(B - A)[0]])
        tri = [v3(A, y), v3(B, y), v3(mid, h)]
        wl = float(np.linalg.norm(B - A))
        _face_up(M, tri, [(0, y - base, 0), (wl, y - base, 0), (wl / 2, h - base, 0)], "wall", "gable", -1, nb, out)
    # the overhang under the gable ends: the slopes reach past the end walls, so close the triangle under them
    if overhang > 0:
        for (a_, b_), r_ in (((i1, i2), Rb), ((i3, i0), Ra)):
            out = p[b_] - p[a_]
            out = np.array([out[1], 0.0, -out[0]])
            t_ = [v3(q[a_], ye), v3(q[b_], ye), v3(r_, h)]
            _face_up(M, t_, uvs(t_), "roof", "roof", -1, nb, out)


def _prism(M, ring, y0, y1, part, floor, nb, top=True):
    """A vertical prism over the CCW (x, z) ring: side walls facing out and (optionally) a top."""
    m = len(ring)
    s = 0.0
    for k in range(m):
        A, B = ring[k], ring[(k + 1) % m]
        L = float(np.linalg.norm(B - A))
        M.face([(B[0], y0, B[1]), (A[0], y0, A[1]), (A[0], y1, A[1]), (B[0], y1, B[1])],
               [(s + L, y0, 0), (s, y0, 0), (s, y1, 0), (s + L, y1, 0)], part, part, floor, nb)
        s += L
    if top:
        M.face([(a[0], y1, a[1]) for a in ring[::-1]], [(a[0], a[1], 0) for a in ring[::-1]], part, part, floor, nb)


def _chimney(M, p, y, pitch, rng, nb):
    """A chimney stack on a pitched roof over the four-cornered footprint p: near the ridge, a quarter along it."""
    tn = np.tan(np.radians(np.clip(pitch, 5.0, 75.0)))
    e = np.roll(p, -1, axis=0) - p
    Ls = np.linalg.norm(e, axis=1)
    k = 0 if Ls[0] + Ls[2] >= Ls[1] + Ls[3] else 1
    i0, i1, i2, i3 = k, (k + 1) % 4, (k + 2) % 4, (k + 3) % 4
    span = 0.5 * (Ls[i1] + Ls[i3])
    Ra, Rb = 0.5 * (p[i3] + p[i0]), 0.5 * (p[i1] + p[i2])
    t = 0.25 + 0.5 * float(rng.random() < 0.5)
    c = Ra + (Rb - Ra) * t
    ax = (Rb - Ra) / max(float(np.linalg.norm(Rb - Ra)), 1e-9)
    pr = np.array([-ax[1], ax[0]])
    c = c + pr * (0.18 * span) * (1 if rng.random() < 0.5 else -1)      # just off the ridge, on one slope
    hs = 0.35
    ring = np.array([c - ax * hs - pr * hs, c + ax * hs - pr * hs, c + ax * hs + pr * hs, c - ax * hs + pr * hs])
    x, z = ring[:, 0], ring[:, 1]
    if 0.5 * float(np.sum(x * np.roll(z, -1) - np.roll(x, -1) * z)) < 0:
        ring = ring[::-1]
    _prism(M, ring, y, y + tn * span * 0.5 + 0.9, "chimney", -1, nb)


def _yard_walls(M, p, base, height, thick, front_k, nb):
    """Walls along the lot outline p (CCW), inside it, on every side but front_k."""
    m = len(p)
    q = _offset(p, -float(thick))
    for k in range(m):
        if k == front_k:
            continue
        k1 = (k + 1) % m
        ring = np.array([p[k], p[k1], q[k1], q[k]])
        ring = ring[::-1] if 0.5 * float(np.sum(ring[:, 0] * np.roll(ring[:, 1], -1)
                                                 - np.roll(ring[:, 0], -1) * ring[:, 1])) < 0 else ring
        _prism(M, ring, base - 0.3, base + float(height), "yardwall", -3, nb)


def building_generator(geo, modules=None, group="", floor_height=3.0, floors_min=2, floors_max=6,
                       floors_attribute="floors", height_attribute="height", seed=0,
                       facade_pattern="window", module_width=3.0,
                       window_width=0.5, window_height=0.5, window_sill=0.3, inset=0.15,
                       corners=True, corner_width=0.4, convex_corner_module="", concave_corner_module="",
                       top_ledge=True, top_ledge_height=0.25, bottom_ledge=False, bottom_ledge_height=0.4,
                       ledge_depth=0.15, roof="parapet", parapet_height=0.8, parapet_thickness=0.3,
                       floor_overrides="", color_floors=False, footprint_inset=0.0, foundation_depth=0.0,
                       front_attribute="front", front_pattern="", roof_pitch=35.0, roof_overhang=0.3,
                       roof_attribute="", front_pattern_attribute="", chimney_chance=0.0, yard_wall_height=0.0,
                       yard_wall_thickness=0.25, notch_attribute=""):
    """Footprint polygons -> buildings; see the module docstring. -> Geometry, report dict."""
    if roof not in ROOFS:
        raise ValueError(f"Roof must be one of {ROOFS}")
    if float(floor_height) <= 0 or float(module_width) <= 0:
        raise ValueError("Full Floor Height and Module Width must be above 0")
    o = dict(window_width=float(np.clip(window_width, 0.05, 0.98)), window_height=float(np.clip(window_height, 0.05, 0.95)),
             window_sill=float(np.clip(window_sill, 0.0, 0.9)), inset=max(0.0, float(inset)))
    lib = _library(modules)
    pat0 = _pattern(facade_pattern)
    patf = _pattern(front_pattern) if str(front_pattern).strip() else None
    na = geo.get(PRIM, str(notch_attribute).strip()) if str(notch_attribute).strip() else None
    if na is not None and np.asarray(na).dtype.kind == "U":
        raise ValueError(f"Notch Attribute '{notch_attribute}' must be a number prim attribute (0..0.8)")
    need_front = (patf is not None or str(front_pattern_attribute).strip() or float(yard_wall_height) > 0
                  or na is not None)
    fa = geo.get(PRIM, str(front_attribute).strip()) if (need_front and str(front_attribute).strip()) else None
    if fa is not None and (np.asarray(fa).dtype.kind == "U" or np.asarray(fa).shape[1] < 3):
        raise ValueError(f"Front Attribute '{front_attribute}' must be a vector prim attribute (the front's direction)")
    over = _overrides(floor_overrides)
    fpa = geo.get(PRIM, str(front_pattern_attribute).strip()) if str(front_pattern_attribute).strip() else None
    if fpa is not None:
        if np.asarray(fpa).dtype.kind != "U":
            raise ValueError(f"Front Pattern Attribute '{front_pattern_attribute}' must be a string prim attribute "
                             "(a facade module pattern per footprint)")
        fpa = np.asarray(fpa).reshape(-1).astype(str)
    sel = resolve(geo, PRIM, group)
    ra = geo.get(PRIM, str(roof_attribute).strip()) if str(roof_attribute).strip() else None
    if ra is not None:
        if np.asarray(ra).dtype.kind != "U":
            raise ValueError(f"Roof Attribute '{roof_attribute}' must be a string prim attribute ({', '.join(ROOFS)})")
        ra = np.asarray(ra).reshape(-1).astype(str)
        bad = sorted(set(ra) - set(ROOFS) - {""})
        if bad:
            raise ValueError(f"Roof Attribute: unknown roof {bad[0]!r} (one of {ROOFS}; empty = the Roof menu)")
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    vp, off, closed = np.asarray(geo.vertex_point), np.asarray(geo.prim_offset), np.asarray(geo.prim_closed)
    hattr = geo.get(PRIM, str(height_attribute).strip()) if str(height_attribute).strip() else None
    fattr = geo.get(PRIM, str(floors_attribute).strip()) if str(floors_attribute).strip() else None
    M = _Mesh()
    nb = 0
    tot_floors = 0
    up = np.array([0.0, 1.0, 0.0])
    for i in range(geo.nprims):
        n = int(off[i + 1] - off[i])
        if not sel[i] or not closed[i] or n < 3:
            continue
        Q = P[vp[off[i]:off[i + 1]]]
        p = Q[:, [0, 2]]
        x, z = p[:, 0], p[:, 1]
        if 0.5 * float(np.sum(x * np.roll(z, -1) - np.roll(x, -1) * z)) < 0:
            p = p[::-1]
        keep = np.linalg.norm(np.roll(p, -1, axis=0) - p, axis=1) > 1e-6
        p = p[keep]
        if len(p) < 3:
            continue
        p_lot = p
        if float(footprint_inset) > 0:                              # setback from the lot lines
            q = _offset(p, -float(footprint_inset))
            x2, z2 = q[:, 0], q[:, 1]
            e2 = np.roll(q, -1, axis=0) - q
            e0 = np.roll(p, -1, axis=0) - p
            # a footprint that turns inside out or loses a side (too small for the setback) is left empty
            if (0.5 * float(np.sum(x2 * np.roll(z2, -1) - np.roll(x2, -1) * z2)) < 1.0
                    or ((e2 * e0).sum(1) <= 0).any()):
                continue
            p = q
        nv = float(np.clip(np.asarray(na, np.float64)[i].reshape(-1)[0], 0.0, 0.8)) if na is not None else 0.0
        if nv > 0.01 and len(p) == 4:                               # an L: the back corner cut out
            en = np.roll(p, -1, axis=0) - p
            en = en / np.maximum(np.linalg.norm(en, axis=1, keepdims=True), 1e-12)
            fv0 = np.asarray(fa, np.float64)[i, [0, 2]] if fa is not None else np.zeros(2)
            fk = int(np.argmax(en[:, 1] * fv0[0] - en[:, 0] * fv0[1])) if np.linalg.norm(fv0) > 1e-9 else 0
            r_ = (fk + 2) % 4                                       # the back side starts at vertex r_
            V = p[r_]
            A_ = V + nv * (p[(r_ + 1) % 4] - V)
            C_ = V + nv * (p[(r_ - 1) % 4] - V)
            p = np.array([p[(r_ + 1) % 4], p[(r_ + 2) % 4], p[(r_ + 3) % 4], C_, C_ + (A_ - V), A_])
        base = float(Q[:, 1].min())
        M.cur_src = i
        rng = np.random.default_rng([int(seed), i])
        if hattr is not None and float(np.asarray(hattr)[i].reshape(-1)[0]) > 0:
            nf = max(1, int(round(float(np.asarray(hattr)[i].reshape(-1)[0]) / float(floor_height))))
        elif fattr is not None and float(np.asarray(fattr)[i].reshape(-1)[0]) >= 1:
            nf = int(round(float(np.asarray(fattr)[i].reshape(-1)[0])))
        else:
            lo, hi = int(floors_min), max(int(floors_min), int(floors_max))
            nf = int(rng.integers(lo, hi + 1))
        nf = max(1, nf)
        tint = (0.82 + 0.3 * rng.random()) * (1.0 + 0.08 * (rng.random(3) - 0.5))
        m = len(p)
        e = np.roll(p, -1, axis=0) - p
        L = np.linalg.norm(e, axis=1)
        t2 = e / L[:, None]
        # convex corner (seen from outside) at vertex k: the outline turns left there
        tp = np.roll(t2, 1, axis=0)
        turn = tp[:, 0] * t2[:, 1] - tp[:, 1] * t2[:, 0]
        front_k = -1                                                # the wall whose outward normal is nearest the front
        fv = np.asarray(fa, np.float64)[i, [0, 2]] if fa is not None else np.zeros(2)
        if np.linalg.norm(fv) > 1e-9:
            front_k = int(np.argmax(t2[:, 1] * fv[0] - t2[:, 0] * fv[1]))
        patf_i = _pattern(fpa[i]) if fpa is not None and fpa[i].strip() else patf
        if float(yard_wall_height) > 0 and float(yard_wall_thickness) > 0:
            el = np.roll(p_lot, -1, axis=0) - p_lot
            el = el / np.maximum(np.linalg.norm(el, axis=1, keepdims=True), 1e-12)
            fl = int(np.argmax(el[:, 1] * fv[0] - el[:, 0] * fv[1])) if np.linalg.norm(fv) > 1e-9 else -1
            _yard_walls(M, p_lot, base, float(yard_wall_height), float(yard_wall_thickness), fl, nb)
        if float(foundation_depth) > 0:                             # a plinth below the base, for uneven ground
            fd = float(foundation_depth)
            s0 = 0.0
            for k in range(m):
                A, B = p[k], p[(k + 1) % m]
                M.face([(B[0], base - fd, B[1]), (A[0], base - fd, A[1]), (A[0], base, A[1]), (B[0], base, B[1])],
                       [(s0 + L[k], -fd, 0), (s0, -fd, 0), (s0, 0, 0), (s0 + L[k], 0, 0)], "plinth", "plinth", -2, nb)
                s0 += L[k]
        y = base
        for f in range(nf):
            ov = over.get(f, over.get(f - nf, {}))
            fh = float(ov.get("height", floor_height))
            pat = ov.get("pattern", pat0)
            for k in range(m):
                pat_k = patf_i if (k == front_k and f == 0 and patf_i is not None) else pat
                a, b = p[k], p[(k + 1) % m]
                t3 = np.array([t2[k, 0], 0.0, t2[k, 1]])
                n3 = np.array([t2[k, 1], 0.0, -t2[k, 0]])           # outward
                cw = float(corner_width) if corners and L[k] > 2.5 * float(corner_width) else 0.0
                inner = L[k] - 2 * cw
                nbay = max(1, int(round(inner / float(module_width))))
                bw = inner / nbay
                # local frame of a bay seen from outside: x runs against the edge, y up, z out
                spans = []
                if cw > 0:
                    spans.append((L[k] - cw, cw, "corner", (k + 1) % m))
                for j in range(nbay):
                    spans.append((L[k] - cw - (j + 1) * bw, bw, None, j))
                if cw > 0:
                    spans.append((0.0, cw, "corner", k))
                for s0, w, kind, j in spans:
                    org = np.array([a[0], y, a[1]]) + t3 * (s0 + w)
                    if kind == "corner":
                        cm = str(convex_corner_module if turn[j] >= 0 else concave_corner_module).strip()
                        name = cm or "corner"
                        faces = (_module(cm, w, fh, o, lib) if cm
                                 else [([(0, 0, 0), (w, 0, 0), (w, fh, 0), (0, fh, 0)], "corner")])
                    else:
                        alt = pat_k[(nbay - 1 - j) % len(pat_k)]    # the pattern reads left to right from outside
                        name = alt[int(rng.integers(len(alt)))] if len(alt) > 1 else alt[0]
                        faces = _module(name, w, fh, o, lib)
                    for pts, part in faces:
                        lp = np.asarray(pts, np.float64)
                        wp = org + np.outer(lp[:, 0], -t3) + np.outer(lp[:, 1], up) + np.outer(lp[:, 2], n3)
                        uv = np.stack([s0 + w - lp[:, 0], y - base + lp[:, 1], np.zeros(len(lp))], 1)
                        M.face(wp, uv, part, name, f, nb)
            for on, hh, y0 in ((top_ledge, float(top_ledge_height), y + fh - float(top_ledge_height)),
                               (bottom_ledge, float(bottom_ledge_height), y)):
                if not on or hh <= 0 or float(ledge_depth) <= 0:
                    continue
                q = _offset(p, float(ledge_depth))
                s = 0.0
                for k in range(m):
                    k1 = (k + 1) % m
                    A, B, A0, B0 = q[k], q[k1], p[k], p[k1]
                    Lq = float(np.linalg.norm(B - A))
                    M.face([(B[0], y0, B[1]), (A[0], y0, A[1]), (A[0], y0 + hh, A[1]), (B[0], y0 + hh, B[1])],
                           [(s, y0 - base, 0), (s + Lq, y0 - base, 0), (s + Lq, y0 - base + hh, 0), (s, y0 - base + hh, 0)],
                           "ledge", "ledge", f, nb)
                    M.face([(A0[0], y0 + hh, A0[1]), (B0[0], y0 + hh, B0[1]), (B[0], y0 + hh, B[1]), (A[0], y0 + hh, A[1])],
                           [(A0[0], A0[1], 0), (B0[0], B0[1], 0), (B[0], B[1], 0), (A[0], A[1], 0)], "ledge", "ledge", f, nb)
                    M.face([(B0[0], y0, B0[1]), (A0[0], y0, A0[1]), (A[0], y0, A[1]), (B[0], y0, B[1])],
                           [(B0[0], B0[1], 0), (A0[0], A0[1], 0), (A[0], A[1], 0), (B[0], B[1], 0)], "ledge", "ledge", f, nb)
                    s += Lq
            y += fh
        tot_floors += nf
        rp = p
        roof_i = ra[i] if ra is not None and ra[i] else roof
        if roof_i in ("gable", "hip") and m == 4:
            _pitched_roof(M, p, y, base, roof_i, float(roof_pitch), max(0.0, float(roof_overhang)), nb)
            if float(chimney_chance) > 0 and rng.random() < float(chimney_chance):
                _chimney(M, p, y, float(roof_pitch), rng, nb)
            M.tint = getattr(M, "tint", [])
            M.tint.append(tint)
            nb += 1
            continue
        if roof_i == "parapet" and float(parapet_height) > 0 and float(parapet_thickness) > 0:
            ph = float(parapet_height)
            q = _offset(p, -float(parapet_thickness))
            s = 0.0
            for k in range(m):
                k1 = (k + 1) % m
                A, B, C, D = p[k], p[k1], q[k], q[k1]
                M.face([(B[0], y, B[1]), (A[0], y, A[1]), (A[0], y + ph, A[1]), (B[0], y + ph, B[1])],
                       [(s, y - base, 0), (s + L[k], y - base, 0), (s + L[k], y - base + ph, 0), (s, y - base + ph, 0)],
                       "parapet", "parapet", -1, nb)
                M.face([(C[0], y + ph, C[1]), (D[0], y + ph, D[1]), (B[0], y + ph, B[1]), (A[0], y + ph, A[1])],
                       [(C[0], C[1], 0), (D[0], D[1], 0), (B[0], B[1], 0), (A[0], A[1], 0)], "parapet", "parapet", -1, nb)
                M.face([(C[0], y, C[1]), (D[0], y, D[1]), (D[0], y + ph, D[1]), (C[0], y + ph, C[1])],
                       [(s, 0, 0), (s + L[k], 0, 0), (s + L[k], ph, 0), (s, ph, 0)], "parapet", "parapet", -1, nb)
                s += L[k]
            rp = q
        M.face([(a[0], y, a[1]) for a in rp[::-1]], [(a[0], a[1], 0) for a in rp[::-1]], "roof", "roof", -1, nb)
        M.tint = getattr(M, "tint", [])
        M.tint.append(tint)
        nb += 1
    if not nb:
        return Geometry(), {"buildings": 0, "floors": 0, "faces": 0}
    out = Geometry.from_mesh(np.concatenate(M.P), M.faces)
    out.set(VERTEX, "uv", np.concatenate(M.uv).astype(np.float32))
    part = np.asarray(M.part)
    floor = np.asarray(M.floor, np.int32)
    bld = np.asarray(M.bld, np.int32)
    out.set_string(PRIM, "part", part)
    out.set_string(PRIM, "material", part)
    out.set_string(PRIM, "module", np.asarray(M.module))
    out.set(PRIM, "floor", floor)
    out.set(PRIM, "building", bld)
    for name in np.unique(part):
        out.set_group(PRIM, str(name), part == name)
    # the footprint's own prim attributes go to every face of its building (a lot number, a town name, ...)
    src = np.asarray(M.src, np.int64)
    mine = {"part", "material", "module", "floor", "building", "Cd"}
    for name in geo.names(PRIM):
        if name in mine:
            continue
        a = np.asarray(geo.get(PRIM, name))[src]
        (out.set_string if a.dtype.kind == "U" else out.set)(PRIM, name, a)
    if color_floors:
        hcol = np.array([[0.90, 0.35, 0.30], [0.95, 0.70, 0.25], [0.45, 0.75, 0.40], [0.30, 0.65, 0.85],
                         [0.60, 0.45, 0.85]])
        cd = np.where((floor >= 0)[:, None], hcol[np.maximum(floor, 0) % len(hcol)], 0.4)
    else:
        cd = np.array([_COL.get(str(q), (0.6, 0.6, 0.6)) for q in part])
        wall = np.isin(part, ("wall", "corner", "parapet"))
        cd = np.where(wall[:, None], np.clip(cd * np.asarray(M.tint)[bld], 0, 1), cd)
    out.set(PRIM, "Cd", cd.astype(np.float32))
    return out, {"buildings": nb, "floors": tot_floors, "faces": out.nprims,
                 "parts": {str(k): int((part == k).sum()) for k in np.unique(part)}}
