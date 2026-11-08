"""Conversion to / from external libraries and file formats. trimesh is an optional dependency; core nodes work without it."""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM


def need(mod, what):
    """
    Single entry point for optional dependencies. A bare `import trimesh` raises
    `ModuleNotFoundError: No module named 'trimesh'` -- in the ComfyUI log
    that says neither which node needs it nor **which** python to install it into (the portable build has its own
    python_embeded; installing into the system python does nothing). So it is wrapped, in the same format as the
    manifold3d message in Boolean.
    """
    import importlib
    try:
        return importlib.import_module(mod)
    except ImportError as e:
        raise RuntimeError(
            f"{what} needs {mod}. Run this in ComfyUI's python environment:\n"
            f"  python_embeded\\python.exe -m pip install {mod}\n"
            f"(the portable build has its own python; installing into the system python doesn't count)") from e


def to_trimesh(geo: Geometry):
    trimesh = need("trimesh", "Mesh export")
    P = geo.get(POINT, "P")
    tri = geo.triangles()
    m = trimesh.Trimesh(vertices=np.asarray(P, np.float64),
                        faces=np.asarray(tri, np.int64), process=False)
    if geo.has(POINT, "Cd"):
        cd = np.clip(geo.get(POINT, "Cd"), 0, 1)
        rgba = np.concatenate([cd, np.ones((len(cd), 1))], 1)
        m.visual.vertex_colors = (rgba * 255).astype(np.uint8)
    return m


def from_trimesh(m) -> Geometry:
    g = Geometry.from_mesh(np.asarray(m.vertices, np.float32),
                           np.asarray(m.faces, np.int32))
    return g


def write_obj(geo: Geometry, path: str):
    """
    Pure-python OBJ writer, zero dependencies, supports ngons and polylines.

    Coordinates use `.9g` rather than `.6f`: 9 significant digits are what float32 needs for a **lossless round trip**,
    and P is float32. `.6f` is a fixed 6 **decimal places** -- a model at 1e-3 scale keeps only three
    significant digits (quantized into steps), and at 1e5 scale it writes a pile of useless zeros. Now that Import Mesh exists,
    every pass of "export -> edit in an external tool -> import back" would lose a layer of precision, invisibly.
    """
    P = geo.get(POINT, "P")
    with open(path, "w") as f:
        for p in P:
            f.write(f"v {p[0]:.9g} {p[1]:.9g} {p[2]:.9g}\n")
        for i in range(geo.nprims):
            idx = geo.prim_points(i) + 1
            tag = "f" if geo.prim_closed[i] else "l"
            f.write(tag + " " + " ".join(str(int(x)) for x in idx) + "\n")
    return path


def write_glb(geo: Geometry, path: str):
    """For ComfyUI's Preview3D. Needs trimesh."""
    m = to_trimesh(geo)
    m.export(path)
    return path


SHADINGS = ("normal", "lambert", "color")
_LIGHT = np.array([0.4, 0.8, 0.45]) / np.linalg.norm([0.4, 0.8, 0.45])


def _attrib_image(geo, rast, name):
    """Attribute on any class -> (H,W,C) image. Searched in point / vertex / prim / detail order."""
    from . import render as R
    from .core import VERTEX, DETAIL
    hit = rast["hit"]
    m = hit >= 0
    for cls in (POINT, VERTEX, PRIM, DETAIL):
        a = geo.get(cls, name)
        if a is None:
            continue
        a = np.asarray(a, np.float64)
        if a.ndim == 1:
            a = a[:, None]
        if cls == POINT:
            return R._interp(rast, a)
        if cls == VERTEX:
            return R._interp_corner(rast, a)
        out = np.zeros(hit.shape + (a.shape[1],))
        if cls == PRIM:
            out[m] = a[rast["src"][hit[m]]]
        else:
            out[m] = a[0]
        return out
    return None


def render_preview(geo: Geometry, width=512, height=512, elev=25.0, azim=35.0,
                   shade="normal", color_attrib="Cd"):
    """
    Renders a preview image offscreen, returns (H,W,3) float32 in [0,1], row 0 is the **top**
    (ComfyUI IMAGE convention). Pure numpy, no OpenGL, so it runs on GPU-less servers too.

    shade:
      normal   world-space face normal *0.5+0.5 (to see shape and orientation)
      lambert  grey shading + one directional light
      color    **Cd * lighting**. Cd may live on point / vertex / prim / detail,
               searched in that order; without Cd it is grey shading. Terrain coloured by masks and meshes with AI textures
               projected back show their colours in this mode

    ━━ pcg56 rewrite
    It used to be a per-triangle Python loop that **didn't read Cd** (only normal / lambert): coloured
    meshes showed no colour in the preview, and a 512^2 terrain mesh (520k triangles) took several minutes. Now it
    borrows Render Pass's vectorized rasterizer (candidate pair expansion + two-pass z reduction), with an orthographic camera framing
    the bounding sphere; camera elevation / azimuth work as before (azimuth 0, elevation 0 = looking from +Z).
    """
    from . import render as R
    img = np.zeros((int(height), int(width), 3), np.float32)
    if shade not in SHADINGS:
        raise ValueError(f"Shading must be one of {SHADINGS}")
    if geo is None or geo.npoints == 0 or geo.nprims == 0:
        return img
    cam = R.camera(geo, "orthographic", xres=int(width), yres=int(height),
                   elev=float(elev), azim=float(azim), frame_geometry=True,
                   margin=1.05)
    rast = R.rasterize(geo, cam)
    hit = rast["hit"]
    m = hit >= 0
    if not m.any():
        return img
    n = R._face_normals(geo, rast)
    lam = np.clip(n @ _LIGHT, 0.0, 1.0)
    if shade == "normal":
        col = n * 0.5 + 0.5
    elif shade == "lambert":
        col = np.repeat(np.maximum(lam, 0.1)[..., None], 3, -1)
    else:
        cd = _attrib_image(geo, rast, str(color_attrib).strip() or "Cd")
        if cd is None:
            cd = np.full(hit.shape + (3,), 0.8)
        elif cd.shape[2] == 1:
            cd = np.repeat(cd, 3, -1)
        cd = np.clip(cd[..., :3], 0.0, 1.0)
        col = cd * (0.3 + 0.7 * lam)[..., None]
    img[m] = np.clip(col[m], 0.0, 1.0)
    # Row 0 of the rasterizer is the bottom of the image (COP convention); row 0 of IMAGE is the top
    return np.ascontiguousarray(img[::-1])
