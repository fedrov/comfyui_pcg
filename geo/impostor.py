"""
Impostor Textures (after SideFX Labs Impostor Texture / Impostor Baker): render an object from a grid of
directions into one atlas, so a far-away copy can be a single card that shows the frame nearest the view.

Every frame is an orthographic view of the whole object (framed on its bounding sphere, so all frames share one
scale), looking at its centre from one direction:

    octahedron        XY Frames x XY Frames directions over the whole sphere: frame (i, j) of n is the octahedral
                      map's point (i, j) / (n - 1) (both ends included, as game engines' octahedral impostors
                      sample it), so neighbouring frames are neighbouring directions and can be blended
    hemi_octahedron   the same over the upper hemisphere only (trees, buildings: never seen from below)
    fixed_axis        frames x * frames y views round the up axis at one Elevation (billboards that turn about Y)
    3d                frames x azimuths x frames y elevations (a latitude / longitude grid)

Frames are laid out row by row; frame (0, 0) is the lower-left sprite (row 0 = the smallest v, as everywhere in
COP). `frame_directions` gives the direction from the object toward the camera for every frame.

Layers of the atlas:
    C        base colour: the geometry's Cd (vertex, point or prim; 0.8 grey without), unlit
    alpha    1 on the object
    N        normal, in World space or View space (x right, y up, z toward the camera), signed
    depth    0..1 across the bounding sphere along the view (0.5 = the centre's plane, 1 = nearest), 0 off the object
    beauty   the base colour lit by a fixed sun and sky fill, for engines that use a pre-lit atlas

The second output is the card: one quad the size of the bounding sphere, centred on the object, facing +Z, uv
0..1, with the impostor's settings as detail attributes (impostor_type, frames_x, frames_y, radius, center).
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL

TYPES = ("octahedron", "hemi_octahedron", "fixed_axis", "3d")
NORMAL_SPACES = ("world", "view")
MAX_ATLAS = 8192


def frame_directions(kind="octahedron", frames_x=8, frames_y=8, elevation=0.0):
    """Unit vectors from the object toward the camera, (frames_y, frames_x, 3); +Y is up."""
    if kind not in TYPES:
        raise ValueError(f"Impostor Type must be one of {TYPES}")
    nx, ny = int(frames_x), int(frames_y)
    if nx < 1 or ny < 1:
        raise ValueError("XY Frames must be at least 1")
    if kind in ("octahedron", "hemi_octahedron"):
        ny = nx
        t = np.linspace(-1.0, 1.0, nx) if nx > 1 else np.zeros(1)
        fx, fy = np.meshgrid(t, t)
        if kind == "octahedron":
            z = 1.0 - np.abs(fx) - np.abs(fy)
            neg = z < 0
            x = np.where(neg, (1.0 - np.abs(fy)) * np.where(fx >= 0, 1.0, -1.0), fx)
            y = np.where(neg, (1.0 - np.abs(fx)) * np.where(fy >= 0, 1.0, -1.0), fy)
        else:
            x, y = (fx + fy) * 0.5, (fx - fy) * 0.5
            z = 1.0 - np.abs(x) - np.abs(y)
        d = np.stack([x, z, y], -1)                                 # the map's pole is world up
    elif kind == "fixed_axis":
        k = np.arange(nx * ny).reshape(ny, nx)
        az = 2 * np.pi * k / (nx * ny)
        el = np.radians(float(elevation))
        d = np.stack([np.sin(az) * np.cos(el), np.full(az.shape, np.sin(el)), np.cos(az) * np.cos(el)], -1)
    else:
        az = 2 * np.pi * np.arange(nx) / nx
        el = np.radians(-90.0 + 180.0 * (np.arange(ny) + 0.5) / ny)
        A, E = np.meshgrid(az, el)
        d = np.stack([np.sin(A) * np.cos(E), np.sin(E), np.cos(A) * np.cos(E)], -1)
    return d / np.maximum(np.linalg.norm(d, axis=-1, keepdims=True), 1e-12)


def _colour(geo, rast):
    from .render import _interp, _interp_corner
    hit = rast["hit"]
    H, W = hit.shape
    m = hit >= 0
    for cls in (VERTEX, POINT, PRIM):
        a = geo.get(cls, "Cd")
        if a is None or np.asarray(a).shape[1] < 3:
            continue
        a = np.asarray(a, np.float64)[:, :3]
        if cls == VERTEX:
            return _interp_corner(rast, a)
        if cls == POINT:
            return _interp(rast, a)
        out = np.zeros((H, W, 3))
        out[m] = a[rast["src"][hit[m]]]
        return out
    return np.where(m[:, :, None], 0.8, 0.0) * np.ones(3)


def impostor_textures(geo, kind="octahedron", sprite_res=128, frames_x=8, frames_y=8, elevation=0.0, zoom=1.0,
                      normal_space="world", sun="0.4 0.8 0.45"):
    """Render the impostor atlas of geo; see the module docstring. -> CopImage, card Geometry, report dict."""
    from .render import look_at, rasterize, _interp, _face_normals
    from .spatial import tri_soup
    from .cop.core import CopImage
    from .cop.pixel import put, _vec
    if normal_space not in NORMAL_SPACES:
        raise ValueError(f"Normal Space must be one of {NORMAL_SPACES}")
    if geo is None or geo.nprims == 0:
        raise ValueError("Impostor Textures needs geometry with faces")
    D = frame_directions(kind, frames_x, frames_y, elevation)
    ny, nx = D.shape[:2]
    s = int(sprite_res)
    if s < 4 or nx * s > MAX_ATLAS or ny * s > MAX_ATLAS:
        raise ValueError(f"Atlas {nx * s} x {ny * s} is out of range (sprite at least 4, atlas at most {MAX_ATLAS})")
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    ctr = (P.min(0) + P.max(0)) * 0.5
    radius = max(float(np.linalg.norm(P - ctr, axis=1).max()), 1e-9)
    size = 2.0 * radius / max(float(zoom), 1e-6)
    soup = tri_soup(geo, "")
    pn = geo.get(POINT, "N")
    pn = np.asarray(pn, np.float64)[:, :3] if pn is not None and np.asarray(pn).shape[1] >= 3 else None
    sv = _vec(sun, 3)
    sv = sv / max(float(np.linalg.norm(sv)), 1e-12)
    Hh, Ww = ny * s, nx * s
    C = np.zeros((Hh, Ww, 3))
    A = np.zeros((Hh, Ww))
    Nn = np.zeros((Hh, Ww, 3))
    Z = np.zeros((Hh, Ww))
    Bt = np.zeros((Hh, Ww, 3))
    for j in range(ny):
        for i in range(nx):
            d = D[j, i]
            eye = ctr + d * radius * 3.0
            up = (0.0, 1.0, 0.0) if abs(d[1]) < 0.999 else (0.0, 0.0, -1.0 if d[1] > 0 else 1.0)
            ey, r, u, f = look_at(eye, ctr, up)
            cam = {"projection": "orthographic", "eye": ey, "right": r, "up": u, "forward": f, "fov": 45.0,
                   "ortho_size": size, "xres": s, "yres": s, "near": 0.01, "far": 0.0, "radius": radius,
                   "target": ctr, "distance": radius * 3.0}
            rast = rasterize(geo, cam, "", "none", soup=soup)
            m = rast["hit"] >= 0
            col = np.where(m[:, :, None], _colour(geo, rast), 0.0)
            nw = _interp(rast, pn) if pn is not None else _face_normals(geo, rast)
            ln = np.linalg.norm(nw, axis=-1, keepdims=True)
            nw = nw / np.where(ln < 1e-12, 1.0, ln)
            nw = np.where((nw @ f > 0)[:, :, None], -nw, nw)        # two-sided: the normal faces the camera
            lit = 0.35 + 0.65 * np.clip(nw @ sv, 0.0, 1.0)
            nv = nw @ np.stack([r, u, -f], 0).T if normal_space == "view" else nw
            sl = (slice(j * s, (j + 1) * s), slice(i * s, (i + 1) * s))
            C[sl] = col
            A[sl] = m
            Nn[sl] = np.where(m[:, :, None], nv, 0.0)
            Z[sl] = np.where(m, np.clip(0.5 + (radius * 3.0 - rast["z"]) / (2.0 * radius), 0.0, 1.0), 0.0)
            Bt[sl] = col * lit[:, :, None]
    img = CopImage(Ww, Hh)
    put(img, "C", C)
    put(img, "alpha", A)
    put(img, "N", Nn)
    put(img, "depth", Z)
    put(img, "beauty", Bt)
    q = radius
    card = Geometry.from_mesh(np.array([[-q, -q, 0], [q, -q, 0], [q, q, 0], [-q, q, 0]], np.float64) + ctr,
                              [[0, 1, 2, 3]])
    card.set(VERTEX, "uv", np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], np.float32))
    card.set_string(DETAIL, "impostor_type", np.array([kind]))
    card.set(DETAIL, "frames_x", np.array([nx], np.int32))
    card.set(DETAIL, "frames_y", np.array([ny], np.int32))
    card.set(DETAIL, "radius", np.array([radius], np.float32))
    card.set(DETAIL, "center", ctr.astype(np.float32))
    return img, card, {"type": kind, "frames": [nx, ny], "atlas": [Ww, Hh], "radius": radius,
                       "center": ctr.tolist(), "coverage": float(A.mean())}
