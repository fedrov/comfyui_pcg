"""
Render the "input -> output" pictures of the node reference: docs/images/nodes/<NODE_ID>.png.

Each recipe below runs the real node (the same classes ComfyUI calls) on a small input. Geometry is drawn by the
plugin's own viewport (web/pcg_viewport.js + three.js) in headless Chromium, so the pictures show exactly what the
viewport shows; image (COP) nodes are written straight from their layers. docs/build_docs.py puts a picture under a
node's heading when the file exists, and docs/build_html.py shows it in the HTML docs.

Needs: numpy etc. (as the plugin), Pillow, and for geometry Node.js with the `playwright` package and its Chromium
(npm i -D playwright && npx playwright install chromium). Without playwright only the COP pictures are written.

    python tools/doc_images.py                 all recipes
    python tools/doc_images.py VDBNoise Box    only these (with or without the PCG_ prefix)
    python tools/doc_images.py --concepts      only the concept pictures (docs/images/concepts/*.png)
    python tools/doc_images.py --list          list the recipes

Then run `python docs/build_docs.py` and `python docs/build_html.py`.
"""
from __future__ import annotations

import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.dirname(REPO))           # the repo folder is the comfyui_pcg package
sys.path.append(os.path.join(REPO, "tests"))        # fakecomfy: stand-in for ComfyUI outside it
import fakecomfy  # noqa: E402,F401
from comfyui_pcg import nodes as N, viewport as VP  # noqa: E402
from comfyui_pcg.geo import build, ops, vdb as V  # noqa: E402
from comfyui_pcg.geo.core import POINT, Geometry  # noqa: E402
from comfyui_pcg.geo.cop import bridge  # noqa: E402

OUT = os.path.join(REPO, "docs", "images", "nodes")
PANEL_W, PANEL_H = 320, 240          # one viewport panel
ARROW_W = 44
BG = (34, 34, 34)

MAP = N.NODE_CLASS_MAPPINGS


# ───────────────────────────────────────────────────────────── running nodes
def _default(spec):
    ty = spec[0]
    o = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    if not isinstance(ty, str):
        return o.get("default", ty[0] if len(ty) else "")
    if "default" in o:
        return o["default"]
    return {"INT": 0, "FLOAT": 0.0, "STRING": "", "BOOLEAN": False}.get(ty)


def run(node, **kw):
    """Run node `PCG_<node>` with its defaults overridden by kw; returns the tuple of outputs."""
    c = MAP[node if node.startswith("PCG_") else "PCG_" + node]
    args = {n: _default(s) for n, s in (c.INPUT_TYPES().get("required") or {}).items()
            if not (isinstance(s[0], str) and s[0] in ("GEOMETRY", "COPIMAGE"))}
    args.update(kw)
    out = getattr(c(), c.FUNCTION)(**args)
    return out["result"] if isinstance(out, dict) else out   # nodes with a UI part return {"ui", "result"}


def g(node, **kw):
    """First output of a node."""
    return run(node, **kw)[0]


def points(xyz, **attrs):
    p = build.points_from_array(np.asarray(xyz, np.float32))
    for k, v in attrs.items():
        v = np.asarray(v, np.float32)
        p.set(POINT, k, v.reshape(len(xyz), -1))
    return p


def rng(seed=1):
    return np.random.default_rng(seed)


def polyline(xyz):
    xyz = np.asarray(xyz, np.float32)
    return Geometry.from_mesh(xyz, [np.arange(len(xyz), dtype=np.int32)], closed=False)


def helix(turns=3, n=120, r=0.6, h=1.6):
    t = np.linspace(0, turns * 2 * np.pi, n)
    return polyline(np.stack([r * np.cos(t), np.linspace(-h / 2, h / 2, n), r * np.sin(t)], 1))


def sdf_sphere(r=0.7, vs=0.05, name="surface"):
    return g("VDBPlatonic", solid="sphere", radius=r, voxel_size=vs, name=name)


def fog_sphere(r=0.7, vs=0.04):
    return g("VDBPlatonic", solid="sphere", radius=r, voxel_size=vs, fog=True, name="density")


def swirl_velocity(res=16, size=2.0):
    vel = V.make((res, res, res), (size, size, size), (0, 0, 0), (0.0, 0.0, 0.0), V.CLASS_NONE, "vel",
                 True, 0.0, True)
    vox, o, c = V.grid(vel, 0)
    P = V.world_points(o, c, vox.shape[:3])
    v = np.stack([-P[..., 2], 0.3 * np.ones_like(P[..., 0]), P[..., 0]], -1) * 2.0
    V.set_voxels(vel, 0, v.astype(np.float32))
    return vel


# ───────────────────────────────────────────────────────────── recipes
# name -> function returning {"in": [geometry...] or [cop...], "out": geometry or cop, optional
# "view": (theta, phi), "layer_in" / "layer_out": COP layer names}. A missing "in" means a generator.
RECIPES: dict[str, callable] = {}
COP_RECIPES: set[str] = set()


def recipe(node, cop=False):
    def deco(fn):
        RECIPES["PCG_" + node] = fn
        if cop:
            COP_RECIPES.add("PCG_" + node)
        return fn
    return deco


TORUS = lambda: g("Torus", radius=0.7, section_radius=0.28, rows=24, cols=48)  # noqa: E731
BOX = lambda: g("Box", div_x=4, div_y=4, div_z=4)  # noqa: E731
SPHERE = lambda: g("Sphere", radius=0.8)  # noqa: E731


# ── Volumes & VDB
@recipe("VDBFromPolygons")
def _():
    t = TORUS()
    return {"in": [t], "out": g("VDBFromPolygons", geo=t, voxel_size=0.04)}


@recipe("VDBPlatonic")
def _():
    return {"out": g("VDBPlatonic", solid="dodecahedron", radius=0.8, voxel_size=0.03)}


@recipe("VDBFromParticles")
def _():
    r = rng(2)
    p = points(r.normal(0, 0.45, (60, 3)), pscale=r.uniform(0.08, 0.22, 60))
    return {"in": [p], "out": g("VDBFromParticles", geo=p, voxel_size=0.03)}


@recipe("VDBFromParticleFluid")
def _():
    r = rng(3)
    xyz = r.uniform(-0.6, 0.6, (2500, 3)) * [1, 0.35, 1]
    xyz[:, 1] -= 0.4
    xyz = np.concatenate([xyz, r.normal([0.1, 0.25, 0], 0.12, (300, 3))])
    p = points(xyz)
    return {"in": [p], "out": g("VDBFromParticleFluid", geo=p, separation=0.05)}


@recipe("VDBNoise")
def _():
    s = sdf_sphere(0.7, 0.03)
    return {"in": [s], "out": g("VDBNoise", geo=s, amp=0.04, freq=2.0, octaves=1)}


@recipe("VDBSmooth")
def _():
    s = g("VDBNoise", geo=sdf_sphere(0.7, 0.03), amp=0.05, freq=4.0, octaves=1)
    return {"in": [s], "out": g("VDBSmooth", geo=s, operation="gauss", radius=2, iterations=6)}


@recipe("VDBCombine")
def _():
    a = sdf_sphere(0.6, 0.03)
    b = g("VDBTransform", geo=g("VDBPlatonic", solid="cube", radius=0.55, voxel_size=0.03),
          t_x=0.45, t_y=0.3)
    return {"in": [a, b], "out": g("VDBCombine", a=a, b=b, operation="sdfdifference")}


@recipe("VDBFracture")
def _():
    s = sdf_sphere(0.75, 0.03)
    cut = g("VDBTransform", geo=g("VDBPlatonic", solid="cube", radius=0.5, voxel_size=0.03),
            t_x=0.45, t_y=0.45, r_y=30)
    fr = g("VDBFracture", geo=s, cutters=cut)
    polys = g("ConvertVDB", geo=fr, convert_to="polygons")
    return {"in": [s, cut], "out": g("ExplodedView", geo=polys, piece_from="connectivity", distance=0.25)}


@recipe("VDBToSpheres")
def _():
    t = g("VDBFromPolygons", geo=TORUS(), voxel_size=0.03, fill_interior=True)
    sp = g("VDBToSpheres", geo=t, spheres_max=120, radius_min=0.5)
    shown = g("CopyToPoints", source=g("Sphere", radius=1.0, cols=16, rows=10), points=sp)
    return {"in": [t], "out": shown}


@recipe("VDBAdvect")
def _():
    f = g("VolumeAdjustFog", geo=fog_sphere(0.45, 0.04), operation="multiply", pattern="noise",
          element_size=0.25)
    f = g("VDBTransform", geo=f, t_x=0.4)
    return {"in": [f], "out": g("VDBAdvect", geo=f, velocity=swirl_velocity(), timestep=0.15, substeps=4)}


@recipe("VDBScatter")
def _():
    f = fog_sphere(0.7)
    return {"in": [f], "out": g("VDBScatter", geo=f, count=3000)}


@recipe("VDBVisualizeTree")
def _():
    s = sdf_sphere(0.7, 0.03)
    return {"in": [s], "out": g("VDBVisualizeTree", geo=s, leaves="boxes")}


@recipe("VDBMorphSDF")
def _():
    a = sdf_sphere(0.7, 0.04)
    b = g("VDBPlatonic", solid="cube", radius=0.7, voxel_size=0.04)
    return {"in": [a, b], "out": g("VDBMorphSDF", source=a, target=b, timestep=2.0, renorm_steps=3)}


@recipe("VDBResample")
def _():
    t = g("VDBFromPolygons", geo=TORUS(), voxel_size=0.03)
    return {"in": [t], "out": g("VDBResample", geo=t, voxel_size=0.2)}


@recipe("ConvertVDB")
def _():
    t = g("VDBFromPolygons", geo=TORUS(), voxel_size=0.04)
    return {"in": [t], "out": g("ConvertVDB", geo=t, convert_to="fog")}


@recipe("VDBClip")
def _():
    t = g("VDBFromPolygons", geo=TORUS(), voxel_size=0.03)
    box = g("Box", size_x=2, size_y=1, size_z=1, cy=0.3, cz=0.5)
    return {"in": [t], "out": g("VDBClip", geo=t, clip=box)}


@recipe("VDBTransform")
def _():
    t = g("VDBFromPolygons", geo=TORUS(), voxel_size=0.04)
    return {"in": [t], "out": g("VDBTransform", geo=t, r_x=60, s_y=1.5)}


@recipe("VDBPotentialFlow")
def _():
    s = sdf_sphere(0.4, 0.05)
    vel = g("VDBPotentialFlow", geo=s)
    yy, zz = np.meshgrid(np.linspace(-0.6, 0.6, 5), np.linspace(-0.6, 0.6, 5))
    seeds = points(np.stack([np.full(25, -0.85), yy.ravel(), zz.ravel()], -1))
    tr = g("VolumeTrail", geo=seeds, velocity=vel, length=2.0, steps=40)
    return {"in": [s], "out": ops.merge(s, tr)}


@recipe("VDBRay")
def _():
    t = g("VDBFromPolygons", geo=TORUS(), voxel_size=0.04)
    p = g("Scatter", geo=g("Sphere", radius=1.3), count=1500)
    return {"in": [p, t], "out": g("VDBRay", geo=p, vdb=t, method="closestpoint")}


@recipe("VolumeAdjustFog")
def _():
    f = fog_sphere(0.75)
    return {"in": [f], "out": g("VolumeAdjustFog", geo=f, operation="multiply", pattern="noise",
                                element_size=0.3)}


@recipe("VolumeBound")
def _():
    f = g("VDBTransform", geo=fog_sphere(0.5), t_x=0.3, s_y=1.4)
    return {"in": [f], "out": ops.merge(f, g("VolumeBound", geo=f, value=0.01))}


@recipe("VolumeBreak")
def _():
    b = BOX()
    s = g("VDBTransform", geo=sdf_sphere(0.6, 0.04), t_x=0.5, t_y=0.5, t_z=0.5)
    return {"in": [b, s], "out": g("VolumeBreak", geo=b, volume=s, keep="outside")}


@recipe("VolumeRasterizeCurve")
def _():
    c = helix()
    return {"in": [c], "out": g("VolumeRasterizeCurve", geo=c, voxel_size=0.03, density_scale=3)}


@recipe("VolumeRasterizePoints")
def _():
    r = rng(5)
    p = points(r.normal(0, 0.4, (40, 3)), pscale=r.uniform(0.1, 0.25, 40))
    return {"in": [p], "out": g("VolumeRasterizePoints", points=p, voxel_size=0.03, density_scale=4.0)}


@recipe("VolumeRasterizeParticles")
def _():
    r = rng(6)
    p = points(r.normal(0, 0.4, (400, 3)), pscale=np.full(400, 0.06))
    return {"in": [p], "out": g("VolumeRasterizeParticles", points=p, voxel_size=0.03, coverage_scale=6.0)}


@recipe("VolumeSlice")
def _():
    t = g("VDBFromPolygons", geo=TORUS(), voxel_size=0.04)
    return {"in": [t], "out": g("VolumeSlice", geo=t, plane="xy", vis_min=-0.12, vis_max=0.12)}


@recipe("VolumeTrail")
def _():
    vel = swirl_velocity()
    p = points(rng(7).uniform(-0.6, 0.6, (40, 3)))
    return {"in": [p], "out": g("VolumeTrail", geo=p, velocity=vel, length=1.0, steps=30)}


@recipe("VolumeVisualization")
def _():
    f = g("VolumeAdjustFog", geo=fog_sphere(0.75), operation="multiply", pattern="noise",
          element_size=0.3)
    return {"in": [f], "out": g("VolumeVisualization", geo=f, mode="rainbow")}


@recipe("VolumeSDF")
def _():
    f = g("VolumeAdjustFog", geo=fog_sphere(0.75), operation="multiply", pattern="noise",
          element_size=0.4)
    return {"in": [f], "out": g("VolumeSDF", geo=f, iso=0.5, invert=True)}


@recipe("VolumeReshapeSDF")
def _():
    t = g("VDBFromPolygons", geo=TORUS(), voxel_size=0.03)
    return {"in": [t], "out": g("VolumeReshapeSDF", geo=t, operation="dilate", distance=0.12)}


@recipe("VolumeBlur")
def _():
    c = g("VolumeRasterizeCurve", geo=helix(), voxel_size=0.04, density_scale=3)
    return {"in": [c], "out": g("VolumeBlur", geo=c, radius=0.12)}


@recipe("IsoOffset")
def _():
    t = TORUS()
    return {"in": [t], "out": g("IsoOffset", geo=t, output="fog", uniform_divs=50)}


@recipe("ScatterVolume")
def _():
    t = TORUS()
    return {"in": [t], "out": g("ScatterVolume", geo=t, count=2000)}


@recipe("VDBFill")
def _():
    f = fog_sphere(0.7)
    return {"in": [f], "out": g("VDBFill", geo=f, mode="world", wmin_x=0, wmin_y=0, wmin_z=-1,
                                wmax_x=1, wmax_y=1, wmax_z=1, value_x=0.0)}


def noisy_fog(r=0.75, es=0.3):
    return g("VolumeAdjustFog", geo=fog_sphere(r), operation="multiply", pattern="noise", element_size=es)


def trails(vel, n=6, span=0.7, x=None, length=1.5, steps=40, seeds=None):
    """Seed a lattice of points and trace them through a velocity volume (to make velocity visible)."""
    a = np.linspace(-span, span, n)
    if seeds is not None:
        return g("VolumeTrail", geo=seeds, velocity=vel, length=length, steps=steps)
    if x is None:
        P = np.stack(np.meshgrid(a, a, a), -1).reshape(-1, 3)
    else:
        yy, zz = np.meshgrid(a, a)
        P = np.stack([np.full(yy.size, x), yy.ravel(), zz.ravel()], -1)
    return g("VolumeTrail", geo=points(P), velocity=vel, length=length, steps=steps)


@recipe("VDBLOD")
def _():
    t = g("VDBFromPolygons", geo=TORUS(), voxel_size=0.03)
    return {"in": [t], "out": g("VDBLOD", geo=t, lod="single", level=3.0)}


@recipe("VDBRebuildSDF")
def _():
    f = g("ConvertVDB", geo=g("VDBFromPolygons", geo=TORUS(), voxel_size=0.04), convert_to="fog")
    return {"in": [f], "out": g("VDBRebuildSDF", geo=f, isovalue=0.5)}


@recipe("VDBTopologyToSDF")
def _():
    f = noisy_fog(0.75, 0.35)
    return {"in": [f], "out": g("VDBTopologyToSDF", geo=f, smoothing=2)}


@recipe("VDBSegment")
def _():
    a = sdf_sphere(0.35, 0.03)
    b = g("VDBTransform", geo=g("VDBPlatonic", solid="cube", radius=0.3, voxel_size=0.03), t_x=0.75)
    c = g("VDBTransform", geo=g("VDBPlatonic", solid="octahedron", radius=0.4, voxel_size=0.03), t_x=-0.8)
    u = g("VDBCombine", a=g("VDBCombine", a=a, b=b, operation="sdfunion"), b=c, operation="sdfunion")
    seg = run("VDBSegment", geo=u)[0]
    polys = g("Connectivity", geo=g("ConvertVDB", geo=seg, convert_to="polygons"), cls="prim")
    return colored({"in": [u], "out": g("Color", geo=polys, attribute_class="prim", mode="random_by_attribute",
                                        attribute="class")})


@recipe("VolumeFeather")
def _():
    f = g("VDBPlatonic", solid="cube", radius=0.6, voxel_size=0.03, fog=True, name="density")
    return {"in": [f], "out": g("VolumeFeather", geo=f, mode="change_per_distance", amount=3.0)}


@recipe("VolumeMix")
def _():
    a = fog_sphere(0.65)
    b = g("VDBTransform", geo=fog_sphere(0.45), t_x=0.45, t_y=0.3)
    return {"in": [a, b], "out": run("VolumeMix", geo_a=a, geo_b=b, operation="subtract")[0]}


@recipe("VolumeRamp")
def _():
    f = noisy_fog()
    return {"in": [f], "out": g("VolumeRamp", geo=f, ramp="0:0 0.45:0 0.55:1 1:1")}


@recipe("VolumeResample")
def _():
    f = noisy_fog()
    return {"in": [f], "out": run("VolumeResample", geo=f, mode="voxel_size", voxel_size=0.12)[0]}


@recipe("VolumeSmoothSDF")
def _():
    s = g("VDBNoise", geo=sdf_sphere(0.7, 0.03), amp=0.05, freq=4.0, octaves=1)
    return {"in": [s], "out": g("VolumeSmoothSDF", geo=s, operation="mean_curvature_flow", iterations=12)}


@recipe("VolumeStamp")
def _():
    dst = g("Volume", res_x=64, res_y=64, res_z=64, size_x=2, size_y=2, size_z=2, fog=True, name="density")
    pts = g("Scatter", geo=g("Sphere", radius=0.6), count=12)
    stamp = fog_sphere(0.22, 0.03)
    return {"in": [pts, stamp], "out": g("VolumeStamp", geo=dst, points=pts, stamps=stamp)}


@recipe("VolumeWrangle")
def _():
    f = fog_sphere(0.75)
    return {"in": [f], "out": run("VolumeWrangle", geo=f,
                                  code="@value = @value * (0.5 + 0.5 * sin(@P.y * 24))")[0]}


@recipe("VolumeFromAttrib")
def _():
    dst = g("Volume", res_x=48, res_y=48, res_z=48, size_x=2, size_y=2, size_z=2, fog=True, name="density")
    p = g("Scatter", geo=TORUS(), count=3000)
    p = g("Wrangle", geo=p, code="f@density = 1.0")
    return {"in": [p], "out": g("VolumeFromAttrib", geo=dst, points=p, attribute="density")}


@recipe("VolumeVelocityFromCurves")
def _():
    cs = helix(r=0.6, h=1.6, turns=1.5)
    vel = g("VolumeVelocityFromCurves", curves=cs, voxel_size=0.06, radius=0.5)
    return {"in": [cs], "out": ops.merge(cs, trails(vel, n=5, span=0.6, length=1.2))}


@recipe("VolumeVelocity")
def _():
    v = g("VDB", name="vel", vdb_class="none", vector=True, voxel_size=0.08, size_x=2, size_y=2, size_z=2,
          fill_active=True)
    out = g("VolumeVelocity", geo=v, vortex=True, angular=2.0)
    return {"in": [v], "out": trails(out, n=5, span=0.7, length=1.5)}


@recipe("VDBAdvectPoints")
def _():
    p = points(rng(9).uniform(-0.6, 0.6, (60, 3)))
    return {"in": [p], "out": g("VDBAdvectPoints", geo=p, velocity=swirl_velocity(), timestep=0.4, substeps=8,
                                streamlines=True)}


# ── Geometry
@recipe("Box")
def _():
    return {"out": BOX()}


@recipe("Torus")
def _():
    return {"out": TORUS()}


@recipe("Sphere")
def _():
    return {"out": g("Sphere", prim_type="polygon", frequency=3)}


@recipe("Tube")
def _():
    return {"out": g("Tube", radius2=0.5, rows=4)}


@recipe("Font")
def _():
    return {"out": g("Font", text="PCG", mode="extrude", halign="center", valign="center")}


@recipe("LSystem")
def _():
    return {"out": g("LSystem", generations=4)}


@recipe("PolyExtrude")
def _():
    gr = g("Grid", size_x=2, size_z=2, cols=5, rows=5)
    return {"in": [gr], "out": g("PolyExtrude", geo=gr, divide_into="individual", distance=0.3, inset=0.08)}


@recipe("PolyBevel")
def _():
    b = g("Box")
    return {"in": [b], "out": g("PolyBevel", geo=b, distance=0.12, divisions=4)}


@recipe("Boolean")
def _():
    a = g("Box")
    b = g("Sphere", radius=0.65, cols=32, rows=24, center_x=0.4, center_y=0.4, center_z=0.4)
    return {"in": [a, b], "out": g("Boolean", a=a, b=b)}


@recipe("Clip")
def _():
    s = SPHERE()
    return {"in": [s], "out": g("Clip", geo=s, dir_x=0.3, dir_y=1.0)}


@recipe("Subdivide")
def _():
    b = g("Box")
    return {"in": [b], "out": g("Subdivide", geo=b, depth=2), "wire": True}


@recipe("Smooth")
def _():
    s = g("PointJitter", geo=g("Sphere", radius=0.8, cols=48, rows=32), scale=0.08)
    return {"in": [s], "out": g("Smooth", geo=s, strength=1.0, iterations=20)}


@recipe("Mirror")
def _():
    t = g("Tube", radius1=0.4, radius2=0.1, center_x=0.6, rz=40)
    return {"in": [t], "out": g("Mirror", geo=t, mode="append")}


@recipe("PolyReduce")
def _():
    t = TORUS()
    return {"in": [t], "out": g("PolyReduce", geo=t, keep_percent=12), "wire": True}


@recipe("Remesh")
def _():
    t = g("Tube", rows=2, cols=12)
    return {"in": [t], "out": g("Remesh", geo=t, target_length=0.15), "wire": True}


@recipe("VoronoiFracture")
def _():
    s = SPHERE()
    p = g("Scatter", geo=s, count=12)
    out = g("VoronoiFracture", geo=s, points=p)
    return {"in": [s, p], "out": g("ExplodedView", geo=out, distance=0.3)}


@recipe("ConvexHull")
def _():
    p = points(rng(9).normal(0, 0.5, (60, 3)))
    return {"in": [p], "out": g("ConvexHull", geo=p)}


@recipe("Sweep")
def _():
    c = helix(turns=2, n=80)
    return {"in": [c], "out": g("Sweep", backbone=c, radius=0.08, cols=12)}


@recipe("Revolve")
def _():
    prof = polyline([[0.2, -0.8, 0], [0.6, -0.6, 0], [0.4, 0.0, 0], [0.25, 0.5, 0], [0.45, 0.8, 0]])
    return {"in": [prof], "out": g("Revolve", geo=prof, divisions=32)}


@recipe("Deform")
def _():
    b = g("Box", size_x=2, size_y=0.4, size_z=0.4, div_x=20, div_y=3, div_z=3)
    return {"in": [b], "out": g("Deform", geo=b, op="twist", angle=180)}


@recipe("Spherify")
def _():
    b = g("Box", div_x=8, div_y=8, div_z=8)
    return {"in": [b], "out": g("Spherify", geo=b, amount=0.8)}


@recipe("Scatter")
def _():
    t = TORUS()
    return {"in": [t], "out": g("Scatter", geo=t, count=2000)}


@recipe("CopyToPoints")
def _():
    p = g("Scatter", geo=SPHERE(), count=80)
    src = g("Box", size_x=0.1, size_y=0.1, size_z=0.25)
    return {"in": [p], "out": g("CopyToPoints", source=src, points=p)}


@recipe("Connectivity")
def _():
    s = g("VoronoiFracture", geo=SPHERE(), points=g("Scatter", geo=SPHERE(), count=10))
    s = g("ExplodedView", geo=s, distance=0.2)
    c = g("Connectivity", geo=s, cls="point")       # (the viewport shows point colours)
    return {"in": [s], "out": g("Color", geo=c, mode="random_by_attribute", attribute="class")}


@recipe("AttribNoise")
def _():
    s = g("Normal", geo=g("Sphere", radius=0.8, cols=64, rows=48))
    return {"in": [s], "out": g("AttribNoise", geo=s, noise_along_vector=True, amplitude=0.3)}


@recipe("Color")
def _():
    t = TORUS()
    return {"in": [t], "out": g("Color", geo=t, mode="random")}


@recipe("Measure")
def _():
    s = g("AttribNoise", geo=g("Normal", geo=g("Sphere", radius=0.8, cols=64, rows=48)),
          noise_along_vector=True, amplitude=0.3)
    return {"in": [s], "out": g("Measure", geo=s, element_type="points", measurement="curvature",
                                color_attribute="Cd")}


@recipe("PointJitter")
def _():
    gr = g("Grid", size_x=2, size_z=2, cols=12, rows=12)
    return {"in": [gr], "out": g("PointJitter", geo=gr, scale=0.15)}


@recipe("ExplodedView")
def _():
    s = g("VoronoiFracture", geo=SPHERE(), points=g("Scatter", geo=SPHERE(), count=14))
    return {"in": [s], "out": g("ExplodedView", geo=s, distance=0.35)}


@recipe("Fractal")
def _():
    gr = g("Grid", size_x=2, size_z=2, cols=3, rows=3)
    return {"in": [gr], "out": g("Fractal", geo=gr, divisions=5, scale=0.4)}


@recipe("Peak")
def _():
    t = TORUS()
    return {"in": [t], "out": g("Peak", geo=t, distance=0.15)}


@recipe("Divide")
def _():
    s = g("Sphere", prim_type="polygon", frequency=2)
    return {"in": [s], "out": g("Divide", geo=s, compute_dual=True), "wire": True}


@recipe("Triangulate2D")
def _():
    p = points(np.c_[rng(4).uniform(-1, 1, (80, 2)), np.zeros(80)][:, [0, 2, 1]])
    return {"in": [p], "out": g("Triangulate2D", geo=p), "wire": True}



# ── More geometry (pcg119): one picture for every node whose result can be seen
def paint(geo, group, cls="prim", rgb=(0.95, 0.55, 0.15), base=(0.72, 0.74, 0.78)):
    """Grey geometry with `group` in orange (the viewport's color shading shows Cd)."""
    a = g("Color", geo=geo, attribute_class=cls, r=base[0], g=base[1], b=base[2])
    return g("Color", geo=a, attribute_class=cls, group=group, r=rgb[0], g=rgb[1], b=rgb[2])


def mark(geo, expr, name="sel"):
    """Prim attribute `name` = expr evaluated per face (in prim context @P is the face centre); group "@sel == 1"."""
    return g("Wrangle", geo=geo, run_over="prim", code=f"i@{name} = {expr}")


def edges_of(geo, expr, name="e"):
    """Edge group `name`: the edges of the faces where expr holds."""
    m = g("GroupCreate", geo=mark(geo, expr, "_m"), name="_f", cls="prim", base="@_m == 1")
    return g("GroupPromote", geo=m, name="_f", direction="prim_to_edge", new_name=name)


def grid(n=10, size=2.0):
    return g("Grid", size_x=size, size_z=size, cols=n, rows=n)


def wavy(n=40):
    gr = grid(n)
    return g("Wrangle", geo=gr, code="@P.y = 0.25 * sin(@P.x * 3) * cos(@P.z * 2.5)")


def curve(pts, **kw):
    return g("Curve", points=" ".join(f"{x},{y},{z}" for x, y, z in pts), **kw)


S_CURVE = [(-1, 0, -0.6), (-0.4, 0.3, 0.4), (0.3, -0.2, -0.4), (1, 0.2, 0.5)]


def colored(r, color=True):
    r["color"] = color
    return r


@recipe("Grid")
def _():
    return {"out": grid(12), "wire": True}


@recipe("Circle")
def _():
    return {"out": g("Circle", orientation="zx", divisions=24, use_arc=True, arc_type="sliced_arc", arc_end=280.0)}


@recipe("Line")
def _():
    return {"out": g("Line", dx=1.0, dy=0.6, dz=0.3, length=2.0, points=12), "wire": True}


@recipe("Curve")
def _():
    return {"out": curve(S_CURVE, prim_type="nurbs")}


@recipe("PlatonicSolids")
def _():
    return {"out": g("PlatonicSolids", solid="soccer_ball", radius=0.9)}


@recipe("IsoSurface")
def _():
    return {"out": g("IsoSurface", expression="length(@P) - 1 + 0.25 * sin(@P.x * 5) * sin(@P.y * 5) * sin(@P.z * 5)",
                      divisions_x=64, divisions_y=64, divisions_z=64)}


@recipe("Transform")
def _():
    t = TORUS()
    return {"in": [t], "out": g("Transform", geo=t, rx=60, sy=1.6, tx=0.3)}


@recipe("Merge")
def _():
    a, b = TORUS(), g("Sphere", radius=0.35, center_y=0.45)
    return {"in": [a, b], "out": g("Merge", geo1=a, geo2=b)}


@recipe("Blast")
def _():
    s = SPHERE()
    return {"in": [s], "out": g("Blast", geo=mark(s, "@P.y > 0.2"), group="@sel == 1", cls="prim")}


@recipe("Delete")
def _():
    t = TORUS()
    return {"in": [t], "out": g("Delete", geo=t, entity="prim", use_number=True, number_mode="every_nth",
                                number_step=3)}


@recipe("Split")
def _():
    s = SPHERE()
    a, b = run("Split", geo=mark(s, "@P.x > 0"), group="@sel == 1")[:2]
    return {"in": [s], "out": ops.merge(g("Transform", geo=a, tx=0.25), g("Transform", geo=b, tx=-0.25))}


@recipe("Bound")
def _():
    t = g("Transform", geo=TORUS(), rx=35, rz=20)
    return {"in": [t], "out": ops.merge(t, g("Bound", geo=t, mode="oriented")), "opts": {"shading": "wire"}}


@recipe("Normal")
def _():
    b = g("Box")
    return {"in": [b], "out": g("Normal", geo=b, add_to="vertex", cusp_angle=30.0), "opts": {"show_normals": "vertex"}}


@recipe("Facet")
def _():
    s = g("Sphere", radius=0.8, cols=12, rows=8)
    return {"in": [s], "out": g("Facet", geo=s, unique_points=True, post_normals=True)}


@recipe("Fuse")
def _():
    pts = g("PointJitter", geo=g("Facet", geo=grid(8), unique_points=True), scale=0.12)
    return {"in": [pts], "out": g("Fuse", geo=pts, snap_distance=0.15), "wire": True}


@recipe("MatchSize")
def _():
    t = g("Transform", geo=TORUS(), tx=0.8, ty=0.6, sx=0.5, sy=0.5, sz=0.5)
    ref = g("Box", size_x=1.6, size_y=0.2, size_z=1.6, cy=-0.1)
    return {"in": [t], "out": ops.merge(ref, g("MatchSize", geo=t, justify_y="min"))}


@recipe("CopyAndTransform")
def _():
    b = g("Box", size_x=0.5, size_y=0.12, size_z=0.3)
    return {"in": [b], "out": g("CopyAndTransform", geo=b, copies=12, ty=0.12, ry=15.0)}


@recipe("PointReplicate")
def _():
    p = points([[-0.6, 0, 0], [0, 0.3, 0], [0.6, 0, 0]])
    return {"in": [p], "out": g("PointReplicate", geo=p, count=300, radius=0.25)}


@recipe("PointRelax")
def _():
    p = g("Scatter", geo=grid(2), count=300, rand_seed=3)
    return {"in": [p], "out": g("PointRelax", geo=p, iterations=30, radius=0.12, use_pscale=False)}


@recipe("ScatterAlign")
def _():
    gr = wavy()
    return {"in": [gr], "out": ops.merge(gr, g("CopyToPoints", source=g("Box", size_x=1, size_y=2, size_z=1),
                                                points=g("ScatterAlign", geo=gr, count=120, scale_min=0.04,
                                                         scale_max=0.1, avoid_overlap=True)))}


@recipe("Sort")
def _():
    gr = grid(14)
    code = "t = @primnum / 169.0\n@Cd = set(t, 0.3 + 0.4 * t, 1 - t)"     # colour = face number
    s = g("Sort", geo=gr, prim_sort="random")
    return colored({"in": [g("Wrangle", geo=gr, run_over="prim", code=code)],
                    "out": g("Wrangle", geo=s, run_over="prim", code=code)})


@recipe("Partition")
def _():
    s = g("VoronoiFracture", geo=SPHERE(), points=g("Scatter", geo=SPHERE(), count=8))
    return colored({"in": [s], "out": g("Color", geo=g("ExplodedView", geo=s, distance=0.2),
                                        attribute_class="prim", mode="random_by_attribute", attribute="name")})


@recipe("GroupCreate")
def _():
    s = SPHERE()
    gc = g("GroupCreate", geo=s, name="up", cls="prim", base="", use_normal=True, dir_x=0, dir_y=1, dir_z=0,
           spread=50.0)
    return colored({"in": [s], "out": paint(gc, "up")})


@recipe("GroupExpand")
def _():
    gr = grid(20)
    gc = g("GroupCreate", geo=gr, name="seed", cls="prim", base="@primnum == 180")
    ex = g("GroupExpand", geo=gc, cls="prim", group="seed", radius=4.0)
    return colored({"in": [paint(gc, "seed")], "out": paint(ex, "seed")})


@recipe("GroupFindPath")
def _():
    gr = wavy(16)
    fp = g("GroupFindPath", geo=gr, points="0 255", group_name="path")
    return colored({"in": [paint(gr, "@ptnum == 0 | @ptnum == 255", cls="point")],
                    "out": paint(fp, "path", cls="point")})


@recipe("FindShortestPath")
def _():
    gr = wavy(16)
    gc = g("GroupCreate", geo=g("GroupCreate", geo=gr, name="s", cls="point", base="@ptnum == 0"),
           name="e", cls="point", base="@ptnum == 255")
    fp = g("FindShortestPath", geo=gc, start_group="s", end_group="e", output="group", group_name="path")
    return colored({"in": [paint(gr, "@ptnum == 0 | @ptnum == 255", cls="point")], "out": paint(fp, "path", cls="point")})


@recipe("Dissolve")
def _():
    s = grid(9)
    e = g("GroupEdges", geo=s, name="e", use_angle=False, use_random=True, percent=30.0, rand_seed=2)
    return {"in": [s], "out": g("Dissolve", geo=e, edge_group="e"), "view": (0.0, 0.05), "opts": {"shading": "wire"}}


@recipe("EdgeDivide")
def _():
    b = g("Box")
    return {"in": [b], "out": g("EdgeDivide", geo=b, edge_group="*", cuts=3), "wire": True, "opts": {"show_points": True}}


@recipe("LoopCut")
def _():
    b = g("Tube", rows=2, cols=12)
    pg = g("GroupCreate", geo=b, name="p", cls="point", base="@ptnum == 0 | @ptnum == 12")
    e = g("GroupPromote", geo=pg, name="p", direction="point_to_edge", new_name="seed")   # one vertical edge
    return {"in": [b], "out": g("LoopCut", geo=e, edge_group="seed", cuts=4), "wire": True}


@recipe("EdgeFlip")
def _():
    gr = g("Grid", size_x=2, size_z=2, cols=7, rows=7, connectivity="triangles")
    gr = g("Wrangle", geo=gr, code="@P.x += 0.12 * (rand(@ptnum) - 0.5)\n@P.z += 0.12 * (rand(@ptnum + 7.1) - 0.5)")
    return {"in": [gr], "out": run("EdgeFlip", geo=gr, mode="delaunay", cycles=3)[0], "view": (0.0, 0.05),
            "opts": {"shading": "wire"}}


@recipe("EdgeCollapse")
def _():
    s = g("Sphere", radius=0.8, cols=16, rows=12)
    return {"in": [s], "out": run("EdgeCollapse", geo=edges_of(s, "@P.y > 0.2"), edges="e")[0], "wire": True}


@recipe("TriDivide")
def _():
    s = g("Sphere", prim_type="polygon", frequency=1)
    return {"in": [s], "out": g("TriDivide", geo=s, max_edge_length=0.3), "wire": True}


@recipe("PolyFill")
def _():
    s = g("Blast", geo=mark(SPHERE(), "@P.y > 0.5"), group="@sel == 1", cls="prim")
    return {"in": [s], "out": g("PolyFill", geo=s, mode="quad_grid"), "wire": True}


@recipe("PolyBridge")
def _():
    a = g("Grid", size_x=0.6, size_z=0.6, cols=4, rows=4, center_y=-0.6)
    b = g("Transform", geo=g("Grid", size_x=0.6, size_z=0.6, cols=4, rows=4), ty=0.6, rz=180, ry=30)
    m = g("Merge", geo1=a, geo2=b)
    m = mark(m, "@P.y > 0")
    m = g("GroupCreate", geo=g("GroupCreate", geo=m, name="a", cls="prim", base="@sel == 0"),
          name="b", cls="prim", base="@sel == 1")
    return {"in": [m], "out": g("PolyBridge", geo=m, source_group="a", dest_group="b", divisions=8,
                                interpolation="hermite")}


@recipe("PolyExpand2D")
def _():
    c = g("Circle", orientation="zx", divisions=6, radius_x=0.6, radius_y=0.6)
    return {"in": [c], "out": ops.merge(c, g("PolyExpand2D", geo=c, offset=0.08, divisions=4)), "view": (0.0, 0.05),
            "opts": {"shading": "wire"}}


@recipe("PolySpline")
def _():
    c = curve(S_CURVE)
    return {"in": [c], "out": g("PolySpline", geo=c, divisions=16)}


@recipe("PolyLoft")
def _():
    cs = [g("Transform", geo=g("Circle", orientation="zx", divisions=16), ty=y, sx=s, sz=s)
          for y, s in ((-0.8, 0.6), (0.0, 0.3), (0.8, 0.7))]
    m = g("Merge", geo1=cs[0], geo2=cs[1], geo3=cs[2])
    return {"in": [m], "out": run("PolyLoft", geo=m, form="faces")[0]}


@recipe("Skin")
def _():
    cs = [g("Transform", geo=g("Circle", orientation="zx", divisions=16, radius_x=r, radius_y=r), ty=y, ry=y * 40)
          for y, r in ((-0.8, 0.7), (-0.3, 0.35), (0.3, 0.5), (0.8, 0.25))]
    m = g("Merge", geo1=cs[0], geo2=cs[1], geo3=cs[2], geo4=cs[3])
    return {"in": [m], "out": g("Skin", geo=m)}


@recipe("Resample")
def _():
    c = curve(S_CURVE)
    return {"in": [c], "out": g("Resample", geo=c, length=0.12), "opts": {"show_points": True}}


@recipe("Carve")
def _():
    c = g("PolySpline", geo=curve(S_CURVE), divisions=16)
    return {"in": [c], "out": g("Carve", geo=c, first_u=0.2, use_second_u=True, second_u=0.7)}


@recipe("Ends")
def _():
    c = g("Circle", orientation="zx", divisions=12)
    return {"in": [c], "out": g("Ends", geo=c, op="unroll"), "opts": {"show_points": True}}


@recipe("CircleSpline")
def _():
    p = curve([(-0.8, 0, 0), (0, 0.6, 0), (0.8, 0, 0), (0.2, -0.5, 0.4)])
    return {"in": [p], "out": g("CircleSpline", geo=p, divisions=12)}


@recipe("ConvertLine")
def _():
    b = g("Box")
    return {"in": [b], "out": g("ConvertLine", geo=b)}


@recipe("CopyToCurves")
def _():
    c = g("PolySpline", geo=curve(S_CURVE), divisions=16)
    return {"in": [c], "out": g("CopyToCurves", source=g("Box", size_x=0.08, size_y=0.25, size_z=0.08),
                                curves=c, count=14)}


@recipe("CrossSectionSurface")
def _():
    cs = [g("Transform", geo=g("Circle", orientation="xy", divisions=10, radius_x=0.6 - 0.15 * k,
                               radius_y=0.4 + 0.1 * k), tz=-0.8 + 0.55 * k, ry=10 * k) for k in range(4)]
    m = g("Merge", geo1=cs[0], geo2=cs[1], geo3=cs[2], geo4=cs[3])
    return {"in": [m], "out": run("CrossSectionSurface", sections=m, divisions_t=12)[0]}


@recipe("CurveIntersect")
def _():
    a = g("PolySpline", geo=curve(S_CURVE), divisions=16)
    b = g("Transform", geo=a, ry=90)
    m = g("Merge", geo1=a, geo2=b)
    hits = run("CurveIntersect", geo=m, output="points")[0]
    dots = g("CopyToPoints", source=g("Sphere", radius=0.1, cols=12, rows=8), points=hits)
    return {"in": [m], "out": ops.merge(m, dots)}


@recipe("OrientAlongCurve")
def _():
    c = helix(turns=1.5, n=24)
    o = g("OrientAlongCurve", geo=c)
    return {"in": [c], "out": g("CopyToPoints", source=g("Box", size_x=0.25, size_y=0.04, size_z=0.08),
                                points=o)}


@recipe("Lattice")
def _():
    s = g("Sphere", radius=0.6, cols=32, rows=24)
    lat = g("LatticeFromBound", geo=s, divisions_x=2, divisions_y=2, divisions_z=2)
    bent = g("Wrangle", geo=lat, code="@P.x += 0.5 * @P.y * @P.y\n@P.z *= 1 + 0.6 * @P.y")
    return {"in": [s, bent], "out": g("Lattice", geo=s, lattice=bent, rest_lattice=lat)}


@recipe("LatticeFromBound")
def _():
    t = TORUS()
    return {"in": [t], "out": ops.merge(t, g("LatticeFromBound", geo=t, divisions_x=4, divisions_y=2, divisions_z=4)),
            "wire": True}


@recipe("Magnet")
def _():
    gr = grid(70)
    m = points([[0.0, 0.0, 0.0]], pscale=[0.6])
    return {"in": [gr], "out": g("Magnet", geo=gr, magnet=m, translate_y=0.5, radius=1.0)}


@recipe("SoftTransform")
def _():
    gr = grid(40)
    gc = g("GroupCreate", geo=gr, name="h", cls="point", base="length(@P - set(0.4, 0, 0.2)) < 0.12")
    return {"in": [gr], "out": g("SoftTransform", geo=gc, group="h", ty=0.6, radius=0.8, ramp_mode="smooth")}


@recipe("SoftPeak")
def _():
    s = g("Sphere", radius=0.7, cols=48, rows=32)
    gc = g("GroupCreate", geo=s, name="h", cls="point", base="@P.y > 0.68")
    return {"in": [s], "out": g("SoftPeak", geo=gc, group="h", distance=0.5, radius=0.6)}


@recipe("Bulge")
def _():
    s = g("Normal", geo=g("Sphere", radius=0.7, cols=48, rows=32))
    m = points([[0.5, 0.4, 0.3]], pscale=[0.5])
    return {"in": [s], "out": run("Bulge", geo=s, magnet=m, magnitude=0.35, radius=1.0)[0]}


@recipe("DeltaMush")
def _():
    s = g("Sphere", radius=0.7, cols=48, rows=32)
    d = g("PointJitter", geo=s, scale=0.06)
    return {"in": [d], "out": run("DeltaMush", geo=d, rest=s, iterations=20)[0]}


@recipe("PointDeform")
def _():
    s = g("Sphere", radius=0.6, cols=32, rows=24)
    rest = g("Scatter", geo=g("Box", size_x=1.4, size_y=1.4, size_z=1.4), count=60)
    dfm = g("Wrangle", geo=rest, code="a = @P.y * 1.2\n@P = set(@P.x * cos(a) - @P.z * sin(a), @P.y * 1.3, @P.x * sin(a) + @P.z * cos(a))")
    return {"in": [s, dfm], "out": run("PointDeform", geo=s, rest=rest, deformed=dfm)[0]}



def uv_space(geo, attr="uv"):
    """The uv layout as geometry: every face on its own points, laid flat at P = (u, 0, -v)."""
    f = g("Facet", geo=geo, unique_points=True)
    f = g("AttribPromote", geo=f, original_name=attr, original_class="vertex", new_class="point",
          method="average", delete_original=False)
    return g("Wrangle", geo=f, code=f"@P = set(@{attr}.x, 0, -@{attr}.y)")


UV_VIEW = (0.0, 0.03)          # straight down for uv layouts


@recipe("UVProject")
def _():
    s = SPHERE()
    return {"in": [s], "out": g("UVProject", geo=s, mode="box", fit_to_01=False, scale_u=3.0, scale_v=3.0),
            "opts": {"shading": "uv"}}


@recipe("UVTransform")
def _():
    s = g("UVProject", geo=SPHERE(), mode="spherical")
    return {"in": [s], "out": g("UVTransform", geo=s, rotate=30.0, scale_u=3.0, scale_v=3.0),
            "opts": {"shading": "uv"}}


@recipe("UVAutoSeams")
def _():
    a = g("UVAutoSeams", geo=g("Box", div_x=6, div_y=6, div_z=6), mode="angle", min_angle=45.0)
    gc = g("GroupPromote", geo=a, name="seams", direction="edge_to_point", new_name="sp")
    return colored({"in": [g("Box", div_x=6, div_y=6, div_z=6)], "out": paint(gc, "sp", cls="point")})


@recipe("UVFlatten")
def _():
    b = g("UVAutoSeams", geo=TORUS(), mode="charts")
    f = g("UVFlatten", geo=b, seam_group="seams", pack=True)
    return {"in": [f], "out": uv_space(f), "view": UV_VIEW, "opts": {"shading": "wire"}}


@recipe("UVUnwrap")
def _():
    s = g("PointJitter", geo=g("Sphere", radius=0.8, cols=12, rows=8), scale=0.1)
    u = g("UVUnwrap", geo=s)
    return {"in": [s], "out": uv_space(u), "view": UV_VIEW, "opts": {"shading": "wire"}}


@recipe("UVLayout")
def _():
    pieces = g("VoronoiFracture", geo=SPHERE(), points=g("Scatter", geo=SPHERE(), count=6))
    u = g("UVProject", geo=pieces, mode="box")
    lay = g("UVLayout", geo=u)
    return {"in": [uv_space(u)], "out": uv_space(lay), "view": UV_VIEW, "opts": {"shading": "wire"}}


@recipe("UVPelt")
def _():
    s = g("Blast", geo=mark(g("Sphere", radius=0.8, cols=24, rows=16), "@P.y < -0.5"), group="@sel == 1", cls="prim")
    u = g("UVPelt", geo=s)
    return {"in": [s], "out": uv_space(u), "view": UV_VIEW, "opts": {"shading": "wire"}}


@recipe("UVSmooth")
def _():
    s = g("UVProject", geo=g("Blast", geo=mark(SPHERE(), "@P.y < 0"), group="@sel == 1", cls="prim"),
          mode="planar", axis="y")
    s = g("Wrangle", geo=s, run_over="vertex", code=(
        "k = @P.x * 13.1 + @P.z * 7.3\n@uv = @uv + set(rand(k) - 0.5, rand(k + 5.5) - 0.5) * 0.06"))
    sm = run("UVSmooth", geo=s, iterations=60, strength=0.8)[0]
    return {"in": [uv_space(s)], "out": uv_space(sm), "view": UV_VIEW, "opts": {"shading": "wire"}}


@recipe("Voronoi2D")
def _():
    p = points(np.c_[rng(5).uniform(-1, 1, (40, 2)), np.zeros(40)][:, [0, 2, 1]])
    v = run("Voronoi2D", geo=p, plane="zx")[0]
    return colored({"in": [p], "out": g("Color", geo=v, attribute_class="prim", mode="random")})


@recipe("VoronoiSplit")
def _():
    s = SPHERE()
    cells = g("Scatter", geo=s, count=10)
    v = run("VoronoiSplit", geo=s, cell_points=cells)[0]
    return colored({"in": [s, cells], "out": g("Color", geo=g("ExplodedView", geo=v, distance=0.15),
                                                attribute_class="prim", mode="random_by_attribute",
                                                attribute="name")})


@recipe("VoronoiCluster")
def _():
    f = g("VoronoiFracture", geo=SPHERE(), points=g("Scatter", geo=SPHERE(), count=40))
    c = g("VoronoiCluster", geo=f, cluster_count=5, merge_pieces=True)
    return colored({"in": [g("Color", geo=g("ExplodedView", geo=f, distance=0.15), attribute_class="prim",
                             mode="random_by_attribute", attribute="name")],
                    "out": g("Color", geo=g("ExplodedView", geo=c, distance=0.15), attribute_class="prim",
                             mode="random_by_attribute", attribute="name")})


@recipe("Wrangle")
def _():
    gr = grid(60)
    return colored({"in": [gr], "out": g("Wrangle", geo=gr, code=(
        "d = length(@P)\n@P.y = 0.15 * sin(d * 14) * exp(-d)\n@Cd = set(0.5 + @P.y * 3, 0.6, 0.9 - @P.y * 3)"))})


@recipe("BallisticPath")
def _():
    p = points([[0, 0, 0]] * 7, v=[[np.cos(a) * 3, 6, np.sin(a) * 3] for a in np.linspace(0, 2 * np.pi, 8)[:7]])
    return {"in": [p], "out": run("BallisticPath", geo=p, duration=1.2, samples=32)[0]}


@recipe("HeightfieldFromImage")
def _():
    import torch
    n = _noise(resolution_x=128, resolution_y=128, octaves=4, frequency=3.0)
    a = np.asarray(bridge.to_preview_float(n, "C", flip=True), np.float32)
    a = a.reshape(a.shape[0], a.shape[1], -1)[..., :1].repeat(3, -1)
    img = torch.from_numpy(a[None].copy())
    return {"out": g("HeightfieldFromImage", image=img, size_x=2, size_z=2, height=0.4, resolution=128)}


@recipe("DisplaceFromMap")
def _():
    s = g("UVProject", geo=g("Sphere", radius=0.7, cols=96, rows=64), mode="spherical")
    n = _noise(resolution_x=256, resolution_y=256, octaves=4, frequency=6.0)
    return {"in": [s], "out": g("DisplaceFromMap", geo=g("Normal", geo=s), cop=n, layer="C", amount=0.25)}


@recipe("ScatterFromMap")
def _():
    gr = g("UVProject", geo=grid(2), mode="planar", axis="y")
    shp = g("COPShape", shape="star", resolution_x=256, resolution_y=256)
    return {"in": [gr], "out": g("ScatterFromMap", geo=gr, cop=shp, layer="mask", count=2500), "view": (0.0, 0.05)}


@recipe("Unsubdivide")
def _():
    s = g("Subdivide", geo=g("Box"), depth=2)
    return {"in": [s], "out": run("Unsubdivide", geo=s, levels=2)[0], "wire": True}


@recipe("RemeshToGrid")
def _():
    t = TORUS()
    return {"in": [t], "out": run("RemeshToGrid", geo=t, voxel_size=0.08)[0], "wire": True}


@recipe("Shrinkwrap")
def _():
    p = g("CopyToPoints", source=g("Sphere", radius=0.2), points=points([[-0.5, 0, 0], [0.2, 0.3, 0], [0.4, -0.3, 0.2]]))
    return {"in": [p], "out": run("Shrinkwrap", geo=p, voxel_size=0.04, radius=0.3)[0]}


@recipe("Refine")
def _():
    c = curve(S_CURVE)
    return {"in": [c], "out": g("Refine", geo=c, mode="subdivide", u_divisions=4), "opts": {"show_points": True}}


@recipe("PolySplit")
def _():
    b = g("Box")
    return {"in": [b], "out": run("PolySplit", geo=b)[0], "opts": {"shading": "wire"}}


@recipe("PolyFrame")
def _():
    s = g("Sphere", radius=0.8, cols=16, rows=12)
    return {"in": [s], "out": g("PolyFrame", geo=s, entity="prim"),
            "opts": {"show_normals": "prim", "normal_scale": 0.15}}


@recipe("Ray")
def _():
    gr = g("Grid", size_x=1.1, size_z=1.1, cols=30, rows=30, center_y=1.0)
    tgt = g("Sphere", radius=0.8, cols=32, rows=24)
    return {"in": [gr, tgt], "out": g("Ray", geo=gr, collision=tgt, method="project_rays")}


@recipe("ExtractCentroid")
def _():
    f = g("ExplodedView", geo=g("VoronoiFracture", geo=SPHERE(), points=g("Scatter", geo=SPHERE(), count=10)),
          distance=0.25)
    c = g("ExtractCentroid", geo=f, run_over="pieces")
    return {"in": [f], "out": ops.merge(f, g("CopyToPoints", source=g("Sphere", radius=0.06), points=c)),
            "opts": {"shading": "wire"}}


@recipe("ExtractSilhouette")
def _():
    t = g("Transform", geo=g("Font", text="PCG", mode="extrude", halign="center", valign="center"), rx=-90)
    return {"in": [t], "out": run("ExtractSilhouette", geo=t)[0]}


@recipe("FractureDetail")
def _():
    f = g("VoronoiFracture", geo=SPHERE(), points=g("Scatter", geo=SPHERE(), count=8))
    return {"in": [g("ExplodedView", geo=f, distance=0.3)],
            "out": g("ExplodedView", geo=g("FractureDetail", geo=f, divisions=3, amount=0.04), distance=0.3)}


@recipe("IntersectionAnalysis")
def _():
    a = TORUS()
    b = g("Sphere", radius=0.45, cols=32, rows=24, center_x=0.95, center_y=0.15)
    m = g("Merge", geo1=a, geo2=b)
    pts = run("IntersectionAnalysis", geo=a, geo_b=b)[0]
    dots = g("Color", geo=g("CopyToPoints", source=g("Sphere", radius=0.03, cols=8, rows=6), points=pts),
             r=0.95, g=0.45, b=0.1)
    return {"in": [m], "out": ops.merge(g("Color", geo=m, r=0.55, g=0.57, b=0.62), dots), "color": True}


@recipe("ConvexDecompose")
def _():
    t = g("Font", text="S", mode="extrude", halign="center", valign="center")
    return colored({"in": [t], "out": g("Color", geo=g("ExplodedView", geo=g("ConvexDecompose", geo=t), piece_from="attribute",
                                                        piece_attribute="piece", distance=0.15),
                                        attribute_class="prim", mode="random_by_attribute", attribute="piece")})


@recipe("BooleanFracture")
def _():
    s = SPHERE()
    cut = g("Grid", size_x=2.5, size_z=2.5, cols=12, rows=12, rz=25)
    cut = g("AttribNoise", geo=cut, amplitude=0.15, use_x=False, use_z=False)
    fr = run("BooleanFracture", geo=s, cutter=cut)[0]
    return colored({"in": [s, cut], "out": g("Color", geo=g("ExplodedView", geo=fr, distance=0.3), attribute_class="prim",
                                              mode="random_by_attribute", attribute="name")})


@recipe("ClusterPoints")
def _():
    p = g("Scatter", geo=grid(2), count=1200)
    c = run("ClusterPoints", geo=p, clusters=9)[0]
    return colored({"in": [p], "out": g("Color", geo=c, attribute_class="point", mode="random_by_attribute",
                                        attribute="cluster"), "view": (0.0, 0.05)})


@recipe("ConnectAdjacentPieces")
def _():
    f = g("VoronoiFracture", geo=SPHERE(), points=g("Scatter", geo=SPHERE(), count=14))
    lines = run("ConnectAdjacentPieces", geo=f, mode="piece_centroids", radius=1.0)[0]
    tubes = g("Color", geo=g("Sweep", backbone=lines, radius=0.025, cols=6), r=0.95, g=0.45, b=0.1)
    ex = g("ExplodedView", geo=f, distance=0.3)
    lines = run("ConnectAdjacentPieces", geo=ex, mode="piece_centroids", radius=1.6)[0]
    tubes = g("Color", geo=g("Sweep", backbone=lines, radius=0.02, cols=6), r=0.95, g=0.45, b=0.1)
    return {"in": [ex], "out": ops.merge(g("Color", geo=ex, r=0.5, g=0.52, b=0.56), tubes), "color": True}


@recipe("AttribBlur")
def _():
    gr = g("Color", geo=grid(40), mode="random", attribute_class="point")
    return colored({"in": [gr], "out": g("AttribBlur", geo=gr, iterations=20), "view": (0.0, 0.05)})


@recipe("AttribPromote")
def _():
    gr = g("Color", geo=grid(12), mode="random", attribute_class="prim")
    return colored({"in": [gr], "out": g("AttribPromote", geo=gr, original_class="prim", new_class="point"),
                    "view": (0.0, 0.05)})


@recipe("AttribRandomize")
def _():
    gr = grid(12)
    return colored({"in": [gr], "out": g("AttribRandomize", geo=gr, attribute_class="prim", name="Cd", dimensions=3),
                    "view": (0.0, 0.05)})


@recipe("AttribTransfer")
def _():
    gr = grid(60)
    src = g("Color", geo=g("Scatter", geo=grid(2), count=8), attribute_class="point", mode="random")
    return colored({"in": [gr, src], "out": g("AttribTransfer", dest=gr, source=src, distance_threshold=3.0,
                                              blend_width=0.4), "view": (0.0, 0.05)})


@recipe("AttribAdjustColor")
def _():
    gr = grid(60)
    return colored({"in": [gr], "out": g("AttribAdjustColor", geo=gr, pattern_type="noise", range_values="color_ramp",
                                         color_ramp="0:0.1,0.2,0.6 0.5:0.2,0.7,0.5 1:1,0.8,0.2",
                                         element_size=0.6, fractal_type="standard"), "view": (0.0, 0.05)})


@recipe("AttribAdjustFloat")
def _():
    p = g("Scatter", geo=grid(2), count=400)
    q = g("AttribAdjustFloat", geo=p, attribute_name="pscale", pattern_type="noise", min_value=0.01, max_value=0.07,
          element_size=0.7)
    sph = g("Sphere", radius=1.0, cols=12, rows=8)
    return {"in": [g("CopyToPoints", source=g("Sphere", radius=0.03, cols=12, rows=8), points=p)],
            "out": g("CopyToPoints", source=sph, points=q)}


@recipe("AttribFromMap")
def _():
    s = g("UVProject", geo=g("Sphere", radius=0.8, cols=64, rows=48), mode="spherical")
    m = _colorful()
    return colored({"in": [s], "out": run("AttribFromMap", geo=s, cop=m)[0]})


@recipe("AttribFromVolume")
def _():
    gr = grid(60)
    f = noisy_fog(0.9, 0.35)
    a = run("AttribFromVolume", geo=gr, volume=f)[0]
    return colored({"in": [gr, f], "out": g("Wrangle", geo=a, code="@Cd = set(@density, @density * 0.6, 0.2)"),
                    "view": (0.0, 0.05)})


@recipe("AttribMirror")
def _():
    s = g("AttribAdjustColor", geo=grid(60), pattern_type="noise", range_values="color_ramp",
          color_ramp="0:0.1,0.2,0.6 0.5:0.2,0.7,0.5 1:1,0.8,0.2", element_size=0.6, fractal_type="standard")
    return colored({"in": [s], "out": run("AttribMirror", geo=s)[0], "view": (0.0, 0.05)})


def _square_sel():
    return mark(grid(20), "max(abs(@P.x), abs(@P.z)) < 0.5")


@recipe("GroupFromAttribBoundary")
def _():
    gr = _square_sel()
    bd = g("GroupFromAttribBoundary", geo=gr, attribute="sel", group_type="points")
    return colored({"in": [paint(gr, "@sel == 1")], "out": paint(bd, "boundary", cls="point"),
                    "view": (0.0, 0.05)})


@recipe("CircleFromEdges")
def _():
    bd = g("GroupFromAttribBoundary", geo=_square_sel(), attribute="sel", group_type="edges")
    return {"in": [bd], "out": run("CircleFromEdges", geo=bd, edges="boundary")[0], "view": (0.0, 0.05),
            "opts": {"shading": "wire"}}


@recipe("PolyCut")
def _():
    c = g("Wrangle", geo=g("Resample", geo=curve(S_CURVE), length=0.02), code="f@h = @P.y")
    return {"in": [c], "out": run("PolyCut", geo=c, mode="threshold", attribute="h", threshold=0.0, keep="above")[0]}


@recipe("GroupInside")
def _():
    t = TORUS()
    p = points(rng(11).uniform(-1, 1, (3000, 3)) * [1.1, 0.45, 1.1])
    gi = g("GroupInside", geo=p, volume=t)
    return colored({"in": [p, t], "out": g("Blast", geo=paint(gi, "inside", cls="point"), group="inside",
                                                cls="point", keep_selected=True)})


@recipe("AttribFade")
def _():
    gr = grid(40)
    f = g("AttribFade", geo=gr, group="@ptnum == 820", metric="distance", radius=0.8)
    return colored({"in": [paint(gr, "@ptnum == 820", cls="point")],
                    "out": g("Wrangle", geo=f, code="@Cd = set(@fade, 0.4 * @fade, 1 - @fade)"),
                    "view": (0.0, 0.05)})


# ── pcg121 (review additions)
def _bands(geo, attr="dist", freq=12.0):
    return g("Wrangle", geo=geo, code=(
        f"t = @{attr}\nb = 0.5 + 0.5 * sin(t * {freq})\n"
        "@Cd = set(0.15 + 0.8 * b, 0.35 + 0.3 * b, 0.9 - 0.6 * b)"))


@recipe("DistanceFromGeometry")
def _():
    gr = grid(80, 3.0)
    ref = g("Transform", geo=TORUS(), ty=0.4, rx=90)
    d = run("DistanceFromGeometry", geo=gr, reference=ref)[0]
    return colored({"in": [gr, ref], "out": ops.merge(_bands(d, freq=14.0), g("Color", geo=ref, r=0.8, g=0.8, b=0.82))})


@recipe("DistanceAlongGeometry")
def _():
    s = g("Sphere", radius=0.8, cols=96, rows=48)
    d = run("DistanceAlongGeometry", geo=s, start_points="0")[0]
    return colored({"in": [paint(s, "0", cls="point")], "out": _bands(d, freq=16.0)})


@recipe("PathDeform")
def _():
    strip = g("Box", size_x=0.25, size_y=0.08, size_z=2.0, div_x=2, div_y=2, div_z=40)
    c = g("Resample", geo=g("PolySpline", geo=curve([(-1, 0, -0.8), (-0.6, 0.4, 0.6), (0.4, -0.3, -0.5),
                                                     (1, 0.3, 0.7)]), divisions=24), length=0.02)
    return {"in": [strip, c], "out": ops.merge(run("PathDeform", geo=strip, curve=c)[0], c)}


@recipe("PolyWire")
def _():
    t = g("Transform", geo=g("LSystem"), sx=0.02, sy=0.02, sz=0.02)          # the stock tree is 81 units tall
    return {"in": [t], "out": run("PolyWire", geo=t, radius=0.012, divisions=8)[0]}


@recipe("Thicken")
def _():
    # an open half-sphere shell, cut in half afterwards so the thickness shows in the section
    s = g("Blast", geo=mark(g("Sphere", radius=0.8, cols=48, rows=24), "@P.y < 0"), group="@sel == 1", cls="prim")
    t = run("Thicken", geo=s, thickness=0.12)[0]
    cut = lambda x: g("Clip", geo=x, dir_x=0.0, dir_y=0.0, dir_z=1.0, keep="below")  # noqa: E731
    return {"in": [cut(s)], "out": cut(t), "view": (0.35, 1.2)}


@recipe("CurveFillet")
def _():
    z = curve([(-1, 0, -0.5), (-0.5, 0, 0.5), (0, 0, -0.5), (0.5, 0, 0.5), (1, 0, -0.5)])
    return {"in": [z], "out": run("CurveFillet", geo=z, radius=0.2, divisions=8)[0], "view": (0.0, 0.05),
            "opts": {"show_points": True}}


@recipe("Pack")
def _():
    f = g("VoronoiFracture", geo=SPHERE(), points=g("Scatter", geo=SPHERE(), count=12))
    f = g("ExplodedView", geo=f, distance=0.25)
    p = run("Pack", geo=f, pack_by="piece_attribute", piece_attribute="name")[0]
    # the packed pieces are drawn as instances; the dots are the packed points (one per piece, at its centroid)
    return colored({"in": [g("Color", geo=f, attribute_class="prim", mode="random_by_attribute", attribute="name")],
                    "out": g("Color", geo=p, attribute_class="point", mode="random")})


@recipe("Unpack")
def _():
    rock = g("AttribNoise", geo=g("Sphere", radius=0.1, cols=16, rows=8), amplitude=0.04)
    pts = g("Scatter", geo=grid(2, 2.0), count=150)
    p = g("CopyToPoints", source=rock, points=pts, pack_and_instance=True)
    u = run("Unpack", geo=p)[0]
    # packed copies are drawn as GPU instances; unpacked they are real polygons (coloured per copy here)
    return colored({"in": [p], "out": g("Color", geo=u, attribute_class="prim", mode="random_by_attribute",
                                        attribute="copynum"), "view": (0.5, 0.9)})


@recipe("BlendShapes")
def _():
    s = g("Sphere", radius=0.8, cols=32, rows=24)
    t = g("Wrangle", geo=s, code="@P = @P * set(1.4, 0.5, 1.0)")
    return {"in": [s, t], "out": run("BlendShapes", base=s, target1=t, weight1=0.6)[0]}


# ── Concept pictures (docs/images/concepts/<name>.png): labelled panels side by side
def _vol_display():
    f = g("VolumeAdjustFog", geo=fog_sphere(0.75), operation="multiply", pattern="noise", element_size=0.3)
    t = g("VDBFromPolygons", geo=TORUS(), voxel_size=0.04)
    return [("Fog: smoke", f), ("Fog: rainbow", g("VolumeVisualization", geo=f, mode="rainbow")),
            ("Fog: iso surface", g("VolumeVisualization", geo=f, mode="iso", iso=0.3)),
            ("SDF: closed surface", g("VDBClip", geo=t, clip=g("Box", size_x=2, size_y=1, size_z=1, cz=0.5)))]


CONCEPTS = {"volume-display": _vol_display}


# ── Images (COP): layer C unless the recipe names another
def _noise(**kw):
    a = dict(resolution_x=256, resolution_y=256, noise_type="perlin", fractal="standard", frequency=4.0,
             octaves=5, amplitude=0.5, bias=0.5)
    a.update(kw)
    return g("COPNoise", **a)


def cop_recipe(node, fn):
    recipe(node, cop=True)(fn)


cop_recipe("COPNoise", lambda: {"out": _noise()})
cop_recipe("COPWorleyNoise", lambda: {"out": g("COPWorleyNoise", resolution_x=256, resolution_y=256,
                                                     element_size=0.15)})
cop_recipe("COPCellularNoise", lambda: {"out": g("COPCellularNoise", resolution_x=256,
                                                       resolution_y=256, element_size=0.15)})
cop_recipe("COPPattern", lambda: {"out": g("COPPattern", kind="tile", resolution_x=256, resolution_y=256),
                                  "layer_out": "pattern"})
cop_recipe("COPShape", lambda: {"out": g("COPShape", shape="star", resolution_x=256, resolution_y=256),
                                "layer_out": "mask"})
cop_recipe("COPReactionDiffusion", lambda: {"out": g("COPReactionDiffusion", resolution_x=192,
                                                           resolution_y=192, steps=2500),
                                            "layer_out": "rd"})
cop_recipe("COPOcean", lambda: {"out": g("COPOcean", resolution_x=256, resolution_y=256),
                                "layer_out": "ocean"})


def _filter(node, layer_out="C", src=None, **kw):
    def fn():
        a = src() if src else _noise()
        return {"in": [a], "out": g(node, cop=a, **kw), "layer_out": layer_out,
                "layer_in": "mask" if src is _shape else "C"}
    cop_recipe(node, fn)


_smooth = lambda: _noise(octaves=2, frequency=3.0)  # noqa: E731  (height-like input for the terrain nodes)
_shape = lambda: g("COPShape", shape="star", resolution_x=256, resolution_y=256)  # noqa: E731
_filter("COPBlur", sigma_pixels=6.0)
_filter("COPEdge", layer_out="edge")
_filter("COPHeightToNormal", src=_smooth, layer_out="N", strength=4.0)
_filter("COPHeightToAO", src=_smooth, layer_out="ao", radius=24.0)
_filter("COPErosion", src=_smooth, strength=2.0, amplitude=0.06, wavelength=24.0)
_filter("COPTerrace", step=0.15)
_filter("COPSwirl", amount=240.0)
_filter("COPPixelate", size=16)
_filter("COPSlope", src=_smooth, layer_out="slope")
_filter("COPVisualize", layer_out="vis")
_filter("COPSDFFromMask", src=_shape, layer="mask", layer_out="sdf")
_filter("COPKuwahara", radius=6)
_filter("COPLevels", in_black=0.3, in_white=0.7)


def _cop(node, src, layer_in="C", layer_out="C", inputs=None, **kw):
    """Generic COP filter recipe: src() feeds `cop`; `inputs` adds extra named COP inputs (shown too)."""
    def fn():
        a = src()
        extra = {k: f() for k, f in (inputs or {}).items()}
        out = run(node, cop=a, **extra, **kw)[0]
        return {"in": [a, *extra.values()], "out": out, "layer_in": layer_in, "layer_out": layer_out}
    cop_recipe(node, fn)


_colorful = lambda: g("COPMonoToRGB", cop=_noise(octaves=4, frequency=3.0),  # noqa: E731
                      ramp="0:0.08,0.15,0.45  0.45:0.2,0.6,0.55  0.7:0.95,0.7,0.25  1:1,0.95,0.85")
_fine = lambda: _noise(octaves=7, frequency=12.0)  # noqa: E731
_normals = lambda: g("COPHeightToNormal", cop=_smooth(), strength=4.0)  # noqa: E731
_sdf = lambda: g("COPSDFFromMask", cop=_shape(), layer="mask", units="uv")  # noqa: E731

# colour & tone
_cop("COPMonoToRGB", _noise, ramp="0:0.08,0.15,0.45  0.45:0.2,0.6,0.55  0.7:0.95,0.7,0.25  1:1,0.95,0.85")
_cop("COPColorCorrect", _colorful, hue_shift=0.35, saturation=1.6, contrast=1.3)
_cop("COPQuantize", _noise, steps=6, lo=0.3, hi=0.7)
_cop("COPRemap", _noise, ramp="0:0  0.5:1  1:0")
_cop("COPLuminance", _colorful, layer_out="lum")
_cop("COPHistogramPlot", _colorful, layer_out="histogram")
# filters
_cop("COPDenoiseTV", _fine, weight=0.4, iterations=80)
_cop("COPMedian", _fine, radius=5, shape="disc")
_cop("COPSharpen", _smooth, amount=4.0, sigma_pixels=4.0)
_cop("COPMorph", _shape, layer_in="mask", layer_out="mask", op="erode", radius=10, shape="disc")
_cop("COPFeatherSlope", _shape, layer_in="mask", layer_out="mask", distance=0.15)
_cop("COPTuringPatterns", _noise, iterations=25, radius=5.0)
_cop("COPSegment", lambda: _noise(octaves=2, frequency=6.0), layer_out="id", layer="C", threshold=0.55)
_cop("COPSDFOps", _sdf, layer_in="sdf", layer_out="sdf_out", op="onion", width=0.03)
# transform
_cop("COPFlip", _colorful, horizontal=True)
_cop("COPTile", _colorful, tiles_x=3, tiles_y=3)
_cop("COPTransform", _colorful, rotate=30.0, scale_x=0.6, scale_y=0.6, border="wrap")
_cop("COPCrop", _colorful, x=64, y=64, resolution_x=128, resolution_y=128)
_cop("COPDistort", _colorful, inputs={"field": lambda: _noise(channels=2, bias=0.0)}, amount=0.4)
cop_recipe("COPBend", lambda: (lambda a: {"in": [a], "out": g("COPBend", source=a, mode="angle", bend_angle=60.0)})(
    _colorful()))
cop_recipe("COPComposite", lambda: (lambda a, b: {"in": [a, b], "out": g("COPComposite", background=a, foreground=b,
                                                                          foreground_layer="C", mode="multiply"),
                                                  "layer_in": "C"})(
    _colorful(), g("COPMonoToRGB", cop=_shape(), layer="mask", out_layer="C")))
# terrain
_cop("COPCurvature", _smooth, layer_out="curvature", strength=4.0)
_cop("COPHeightToShadow", _smooth, layer_out="shadow", strength=4.0, elevation=25.0, softness=4.0)
_cop("COPHeightToCaustics", _smooth, layer_out="caustics", strength=0.5)
_cop("COPHydraulicErosion", _smooth, strength=4.0, droplets_per_pixel=2.0)


def _erode_view():
    # a dome of hills draining to the edges (few pits), so the water runs off and carves instead of pooling
    a = g("COPWrangle", cop=_noise(octaves=6, frequency=3.0),
          code="r = length(set(@u - 0.5, @v - 0.5, 0))\n@C = (@C - 0.5) * 0.35 + 0.45 * (1 - smoothstep(0.0, 0.7, r))")
    out = g("COPHeightfieldErode", cop=a, strength=60.0, world_size=256.0, iterations=250)
    return {"in": [a], "out": out, "layer_in": "C", "layer_out": "flow"}


cop_recipe("COPHeightfieldErode", _erode_view)
_cop("COPMaskByFeature", _smooth, layer_out="mask", use_slope=False, use_height=True,
     height_min=0.55, height_falloff=0.05)
_cop("COPNormalToHeight", _normals, layer_in="N", layer_out="height")
_cop("COPCombineNormals", _normals, layer_in="N", layer_out="N",
     inputs={"detail": lambda: g("COPHeightToNormal", cop=_fine(), strength=2.0)})
# generators
cop_recipe("COPGradient", lambda: {"out": g("COPGradient", resolution_x=256, resolution_y=256, direction="angular")})
cop_recipe("COPSurfaceDither", lambda: {"out": g("COPSurfaceDither", resolution_x=256, resolution_y=256),
                                        "layer_out": "dither"})


# ── pcg122: more image nodes
_cop("COPInvert", _colorful)
_cop("COPMirror", _colorful, mode="left_to_right")
_cop("COPGlow", _colorful, threshold=0.7, intensity=2.0, radius=18.0)
_cop("COPVignette", _colorful, amount=0.9, radius=0.6)
_cop("COPDither", _smooth, method="floyd_steinberg")
_cop("COPChromaticAberration", _colorful, amount=0.04)
_cop("COPDirectionalBlur", _colorful, length=40.0, angle=30.0)
_cop("COPPolar", _colorful, direction="to_polar")
_cop("COPDefocus", _colorful, radius=16.0, shape="hexagon")
_cop("COPHeatDistort", _colorful, amount=12.0, scale=0.03)
_cop("COPSwizzle", _colorful, pattern="brg")
_cop("COPToneMap", _colorful, exposure=1.5)
_cop("COPHexTile", _colorful, tiles=4.0, layer_out="hex")
_cop("COPRetile", lambda: g("COPPattern", kind="tile", resolution_x=256, resolution_y=256),
     layer_in="pattern", layer_out="pattern", counts="4 4")
_cop("COPLensDistort", lambda: g("COPPattern", kind="tile", resolution_x=256, resolution_y=256),
     layer_in="pattern", layer_out="pattern", k1=-0.35)
_cop("COPContour", _smooth, layer_out="contour", interval=0.05)
_cop("COPDerivative", _smooth, layer_out="C_magnitude", mode="magnitude")
_cop("COPThermalErosion", _smooth, layer_out="debris", strength=3.0, iterations=120)
_cop("COPStreamPower", _smooth, strength=3.0, iterations=200)
def _flow_view():
    a = _smooth()
    fa = g("COPFlowAccumulation", cop=a)
    # rivers white, filled lakes grey (the river mask is 0 inside lakes)
    out = g("COPWrangle", cop=fa, code="@view = max(@river, 0.3 * smoothstep(0.0, 0.004, @lake))")
    return {"in": [a], "out": out, "layer_in": "C", "layer_out": "view"}


cop_recipe("COPFlowAccumulation", _flow_view)
_cop("COPFeather", _shape, layer_in="mask", layer_out="mask", width=18.0)
_cop("COPEikonal", _shape, layer_in="mask", layer_out="arrival")
cop_recipe("COPText", lambda: {"out": g("COPText", text="PCG", size=110, align="center",
                                                 resolution_x=256, resolution_y=256),
                               "layer_out": "text"})
cop_recipe("COPScatterShapes", lambda: {"out": g("COPScatterShapes", count=60, shape="star", size=0.07,
                                                 mapping="fit", resolution_x=256, resolution_y=256),
                                        "layer_out": "shapes"})


# ── pcg122: more geometry nodes
@recipe("Assemble")
def _():
    f = g("VoronoiFracture", geo=SPHERE(), points=g("Scatter", geo=SPHERE(), count=10))
    f = g("ExplodedView", geo=f, distance=0.25)
    a = run("Assemble", geo=f, name_prefix="piece")[0]          # the loose pieces get piece0, piece1 ...
    return colored({"in": [f], "out": g("Color", geo=a, attribute_class="prim", mode="random_by_attribute",
                                        attribute="name")})


@recipe("PolyDoctor")
def _():
    # a torus and a sphere pushed through it: the faces that cross are marked (red)
    m = g("Merge", geo1=g("Torus", radius=0.7, section_radius=0.25, rows=24, cols=48),
          geo2=g("Sphere", radius=0.45, cols=32, rows=16, center_x=0.7))
    d = run("PolyDoctor", geo=m, self_intersecting="mark")[0]
    return colored({"in": [m], "out": g("Wrangle", geo=d, run_over="prim",
                                        code="v = i@valid_poly\n@Cd = set(0.55, 0.6, 0.7) * v + set(1.0, 0.3, 0.15) * (1 - v)")})


@recipe("AttribFill")
def _():
    s = g("Sphere", radius=0.8, cols=48, rows=24)
    # three coloured caps are known; Attribute Fill spreads them over the black rest
    s = g("Wrangle", geo=s, code=("a = @P.y > 0.7\nb = @P.y < -0.7\nc = @P.x > 0.75\n"
                                  "i@known = max(max(a, b), c)\n@Cd = set(a + c, 0.3 * a + 0.9 * c, b)"))
    s = g("GroupCreate", geo=s, name="known", cls="point", base="@known == 1")
    return colored({"in": [s], "out": g("AttribFill", geo=s, attribute="Cd", known_group="known")})


@recipe("Enumerate")
def _():
    f = g("VoronoiFracture", geo=SPHERE(), points=g("Scatter", geo=SPHERE(), count=14))
    e = run("Enumerate", geo=f, attribute_class="prim", mode="pieces", piece_attribute="name", name="index")[0]
    return colored({"in": [f], "out": g("Wrangle", geo=e, run_over="prim",
                                        code="t = i@index / 13.0\n@Cd = set(t, 0.3 + 0.4 * t, 1.0 - t)")})


@recipe("AdaptivePrune")
def _():
    p = g("Scatter", geo=grid(2, 2.0), count=1500)
    return {"in": [p], "out": run("AdaptivePrune", geo=p, radius=0.12)[0], "opts": {"show_points": True},
            "view": (0.0, 0.03)}


@recipe("EdgeStraighten")
def _():
    x = np.linspace(-1, 1, 24)
    c = polyline(np.c_[x, 0.25 * np.sin(x * 7.0) + 0.1 * np.sin(x * 19.0), np.zeros_like(x)])
    return {"in": [c], "out": run("EdgeStraighten", geo=c, edges="*", spacing="uniform")[0],
            "opts": {"show_points": True}, "view": (0.0, 1.5707)}


@recipe("Convert")
def _():
    t = g("Torus", radius=0.7, section_radius=0.28, rows=8, cols=16)
    return {"in": [t], "out": run("Convert", geo=t, convert_to="triangles")[0], "wire": True}


@recipe("Primitive")
def _():
    b = g("Box", div_x=3, div_y=3, div_z=3)
    return {"in": [b], "out": run("Primitive", geo=b, uniform_scale=0.7, rotate_y=20.0)[0]}


@recipe("VolumeResize")
def _():
    f = fog_sphere(0.75)
    return {"in": [f], "out": run("VolumeResize", geo=f, size_x=1.6, size_y=0.8, size_z=1.6)[0]}


@recipe("VDBActivate")
def _():
    s = fog_sphere(0.75)
    return {"in": [s], "out": run("VDBActivate", geo=s, operation="intersect", region="position",
                                  size_x=2.0, size_y=0.8, size_z=2.0)[0]}


@recipe("Chain")
def _():
    link = g("Torus", radius=0.06, section_radius=0.015, rows=8, cols=16)
    c = helix(1.5, 80, 0.6, 1.0)
    return {"in": [c], "out": run("Chain", source=link, curves=c, roll_step=90.0)[0]}


# ───────────────────────────────────────────────────────────── drawing
def _rgb8(a):
    a = np.asarray(a, np.float32)
    if a.ndim == 2:
        a = a[..., None]
    if a.shape[-1] == 1:
        lo, hi = float(np.nanmin(a)), float(np.nanmax(a))
        if lo < 0 or hi > 1 or hi - lo < 0.35:    # signed, unbounded or faint data (SDF, slope, edges): stretch
            a = (a - lo) / max(hi - lo, 1e-8)
        a = np.repeat(a, 3, -1)
    elif a.shape[-1] == 2:
        a = np.concatenate([a, np.zeros_like(a[..., :1])], -1)
    elif a.shape[-1] > 3:
        a = a[..., :3]
    if a.min() < -1e-3:                           # normals etc.: -1..1 -> 0..1
        a = a * 0.5 + 0.5
    return (np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8)


def cop_panel(img, layer):
    from PIL import Image
    if layer not in img:
        layer = img.names[0]
    a = bridge.to_preview_float(img, layer, flip=True)
    im = Image.fromarray(_rgb8(a)).resize((PANEL_H, PANEL_H), Image.LANCZOS)
    p = Image.new("RGB", (PANEL_W, PANEL_H), BG)
    p.paste(im, ((PANEL_W - PANEL_H) // 2, 0))
    return p


def labelled(panels):
    """[(label, image)] -> one row with a caption under each panel."""
    from PIL import Image, ImageDraw
    cap = 30
    sheet = Image.new("RGB", (PANEL_W * len(panels) + 8 * (len(panels) - 1), PANEL_H + cap), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    for k, (lab, im) in enumerate(panels):
        x = k * (PANEL_W + 8)
        sheet.paste(im, (x, 0))
        try:
            from PIL import ImageFont
            font = ImageFont.load_default(size=16)
        except (TypeError, OSError):
            font = None
        w = d.textlength(lab, font=font)
        d.text((x + (PANEL_W - w) / 2, PANEL_H + 7), lab, fill=(29, 33, 39), font=font)
    return sheet


def compose(inputs, output):
    """[input panels...] -> output panel, with an arrow between them."""
    from PIL import Image, ImageDraw
    panels = list(inputs)
    w = PANEL_W * (len(panels) + 1) + (ARROW_W if panels else 0)
    sheet = Image.new("RGB", (w, PANEL_H), (24, 24, 24))
    x = 0
    for p in panels:
        sheet.paste(p, (x, 0))
        x += PANEL_W
    if panels:
        d = ImageDraw.Draw(sheet)
        cy, x0, x1 = PANEL_H // 2, x + 10, x + ARROW_W - 10
        d.line([(x0, cy), (x1, cy)], fill=(200, 200, 200), width=3)
        d.polygon([(x1 + 2, cy), (x1 - 8, cy - 7), (x1 - 8, cy + 7)], fill=(200, 200, 200))
        x += ARROW_W
    sheet.paste(output, (x, 0))
    return sheet


VIEW_HTML = """<!doctype html><html><body style="margin:0;background:#222">
<div id="c" style="position:relative;width:%dpx;height:%dpx"></div>
<script type="module">
import { Viewport, decode } from "./extensions/x/pcg_viewport.js";
const vp = new Viewport(document.getElementById("c"), {});
while (!vp.T) await new Promise(r => setTimeout(r, 50));
vp.overlay.style.display = "none";           // no HUD text / axis gizmo in the pictures
window.show = async (name, theta, phi, opts) => {
  const buf = await (await fetch(`./${name}.bin`)).arrayBuffer();
  // every option a recipe may set is reset here: setOptions patches, so one shot's show_points would leak into the next
  vp.setOptions(Object.assign({ wireframe: false, shading: "phong", show_points: false, show_normals: "none" }, opts || {}));
  vp.setGeometry(decode(buf));
  vp.setView(theta, phi);
  vp.frameAll();
  for (let i = 0; i < 6; i++) await new Promise(r => requestAnimationFrame(r));
  return true;
};
window.ready = true;
</script></body></html>"""

SHOT_JS = r"""
const { chromium } = require("playwright");
const fs = require("fs");
(async () => {
  const [url, listFile, outDir] = process.argv.slice(2);
  const jobs = JSON.parse(fs.readFileSync(listFile, "utf8"));
  const br = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader",
                                            "--enable-unsafe-swiftshader"] });
  const p = await br.newPage({ viewport: { width: %d, height: %d } });
  p.on("pageerror", (e) => console.log("pageerror", e.message));
  await p.goto(url, { waitUntil: "domcontentloaded", timeout: 120000 });
  await p.waitForFunction("window.ready === true", null, { timeout: 120000 });
  for (const [name, theta, phi, opts] of jobs) {
    if (fs.existsSync(`${outDir}/${name}.png`)) continue;
    // SwiftShader now and then stalls for good; the caller then kills this process and starts again
    // with the shots still missing, so a stall costs one restart, not the run
    const t = setTimeout(() => { console.log("stalled", name); process.exit(3); }, 60000);
    await p.evaluate(([n, a, b, o]) => window.show(n, a, b, o), [name, theta, phi, opts]);
    await p.waitForTimeout(150);
    await (await p.$("#c")).screenshot({ path: `${outDir}/${name}.png` });
    clearTimeout(t);
    console.log("shot", name);
  }
  await br.close();
  process.exit(0);
})();
"""


def render_3d(jobs, work):
    """jobs: {name: (geometry, theta, phi)} -> {name: PIL image}. Empty if playwright is missing."""
    from PIL import Image
    srv = os.path.join(work, "srv")
    os.makedirs(os.path.join(srv, "scripts"), exist_ok=True)
    shutil.copytree(os.path.join(REPO, "web"), os.path.join(srv, "extensions", "x"))
    with open(os.path.join(srv, "scripts", "app.js"), "w") as f:
        f.write("export const app = { registerExtension() {}, graph: null, canvas: null };\n")
    with open(os.path.join(srv, "index.html"), "w") as f:
        f.write(VIEW_HTML % (PANEL_W, PANEL_H))
    lst = []
    for name, (geo, th, ph, *opts) in jobs.items():
        with open(os.path.join(srv, name + ".bin"), "wb") as f:
            f.write(VP.encode(geo))
        lst.append([name, th, ph, opts[0] if opts else {}])
    with open(os.path.join(work, "jobs.json"), "w") as f:
        json.dump(lst, f)
    with open(os.path.join(work, "shot.cjs"), "w") as f:
        f.write(SHOT_JS % (PANEL_W, PANEL_H))
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=srv)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    shots = os.path.join(work, "shots")
    os.makedirs(shots, exist_ok=True)
    env = dict(os.environ)
    try:
        for attempt in range(6):
            todo = [n for n in jobs if not os.path.exists(os.path.join(shots, n + ".png"))]
            if not todo:
                break
            # own process group, so a stalled run can be killed with its browser
            pr = subprocess.Popen(["node", os.path.join(work, "shot.cjs"),
                                   f"http://127.0.0.1:{httpd.server_port}/index.html",
                                   os.path.join(work, "jobs.json"), shots],
                                  env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                  start_new_session=True)
            try:
                out, _ = pr.communicate(timeout=60 * 30)
            except subprocess.TimeoutExpired:
                out = "timeout"
            if hasattr(os, "killpg"):
                try:
                    os.killpg(pr.pid, 9)
                except OSError:
                    pass
            for line in out.splitlines():
                if not line.startswith("shot "):
                    print("  [viewport]", line)
            if pr.returncode not in (0, 3, -9, None):
                break
    except OSError as e:
        print("  viewport rendering unavailable:", e)
    finally:
        httpd.shutdown()
    return {n: Image.open(os.path.join(shots, n + ".png")).convert("RGB")
            for n in jobs if os.path.exists(os.path.join(shots, n + ".png"))}


# ── pcg126: more geometry nodes
@recipe("Add")
def _():
    return {"out": g("Add", points="0 0 0\n1 0 0\n1.3 0 0.8\n0.5 0 1.4\n-0.3 0 0.8", use_pattern=True, pattern="0-4",
                     pattern_closed=True), "wire": True}


@recipe("MatchAxis")
def _():
    t = g("Tube", radius1=0.3, radius2=0.1, height=1.4)
    return {"in": [t], "out": g("MatchAxis", geo=t, from_x=0, from_y=1, from_z=0, to_x=1, to_y=0, to_z=1)}


@recipe("BlastByAttribute")
def _():
    s_ = g("Wrangle", geo=g("Sphere", radius=0.8, cols=32, rows=16), code="@pscale = noise(@P * 2.5)")
    return {"in": [s_], "out": g("BlastByAttribute", geo=s_, cls="point", attribute="pscale", threshold=0.5)}


@recipe("PrimitiveSplit")
def _():
    f = g("VoronoiFracture", geo=SPHERE(), points=g("Scatter", geo=SPHERE(), count=8))
    c = g("Color", geo=f, attribute_class="prim", mode="random_by_attribute", attribute="name")
    sp = g("PrimitiveSplit", geo=c, attribute="name")
    return colored({"in": [c], "out": g("ExplodedView", geo=sp, distance=0.3)})


# ── pcg126: more image (COP) nodes
_cop("COPBoundingRect", _shape, layer_in="mask", layer_out="rect", padding=6)
_cop("COPChromaKey", _colorful, layer_out="alpha", key_color="0.2 0.6 0.55", tolerance=0.25, softness=0.15)
_cop("COPConvertNormal", _normals, layer_in="N", layer_out="N", layer="N", decode="signed", encode="packed")
_cop("COPCopyTransform", _shape, layer_in="mask", layer_out="mask", copies=6, translate="0.05 0.02", rotate=20.0,
     scale=0.85, op="max")
_cop("COPEqualize", lambda: _noise(octaves=3, amplitude=0.15, bias=0.35))
_cop("COPFit", lambda: _noise(octaves=3, amplitude=0.15, bias=0.35))
_cop("COPFloodFill", lambda: g("COPPattern", kind="tile", resolution_x=256, resolution_y=256), layer_in="pattern",
     layer_out="fill_mask", layer="pattern", seed_uv="0.3 0.3")
_cop("COPFractalSample", _shape, layer_in="mask", layer_out="fractal", source_layer="mask", max_octaves=5)
_cop("COPFunction", _sdf, layer_in="sdf", layer_out="sdf", layers="sdf", function="abs")
_cop("COPHFClip", _smooth, mode="both", min=0.35, max=0.6, softness=0.03)
_cop("COPLogic", _smooth, layer_out="mask", a="C", b="0.5", op="greater")
_cop("COPPlanarInflate", _shape, layer_in="mask", layer_out="height")
_cop("COPPrefixSum", _shape, layer_in="mask", layer_out="mask", layers="mask", direction="u")
_cop("COPSegmentByValue", _smooth, layer_out="id", mode="bins", bins=6)
_cop("COPSplatMap", _smooth, layer_out="splat_rgba", strength=0.4)
_cop("COPStrata", _smooth, spacing=0.05, strength=1.0, sharpness=0.95, tilt="0.3 0.1", noise_amount=0.02)
_cop("COPWrangle", _smooth, code="@C = set(@u, @v, 0.5) * smoothstep(0.4, 0.6, @C)")
_cop("COPDropShadow", _shape, layer_in="mask", layer_out="mask", layer="mask", alpha_layer="mask", offset="10 -10",
     blur=5.0)
_cop("COPFFT", _fine, mode="filter", filter="lowpass", cutoff=10.0)
_cop("COPConvolve", _colorful, preset="emboss")
_cop("COPCornerPin", _colorful, corners="0.1 0.05 0.9 0.2 0.8 0.95 0.05 0.8")
_cop("COPLatticeDeform", _colorful, divisions="4 4", jitter=0.12, rand_seed=3)
_cop("COPTransform3D", _colorful, rotate="35 25 0", perspective=True, border="constant")
_cop("COPCompareMask", _smooth, layer_out="mask", value=0.5, tolerance=0.05, true_if="equal", falloff="linear")
_cop("COPResize", _colorful, resolution_x=48, resolution_y=48)
_cop("COPLight", _normals, layer_in="N", layer_out="lit", azimuth=135.0, elevation=40.0, specular=0.4)
_cop("COPRefractFromHeight", _smooth, layer_out="refract", strength=0.3, depth=0.3)
_cop("COPIDConvert", lambda: g("COPSegmentByValue", cop=_smooth(), mode="bins", bins=6), layer_in="id",
     layer_out="id_mask", ids="2 4", mode="mask")
_cop("COPStereogram", lambda: g("COPWrangle", cop=_shape(), code="@depth = @mask"), layer_in="depth",
     layer_out="stereogram")
_cop("COPPremultiply", lambda: g("COPWrangle", cop=_colorful(), code=(
    "a = smoothstep(0.45, 0.2, length(set(@u - 0.5, @v - 0.5, 0)))\n@C = set(@C.x, @C.y, @C.z, a)")))
cop_recipe("COPNoiseExtra", lambda: {"out": g("COPNoiseExtra", kind="phasor", frequency=10.0, resolution_x=256,
                                               resolution_y=256), "layer_out": "noise"})
cop_recipe("COPRandom", lambda: {"out": g("COPRandom", mode="pixel", channels="3", resolution_x=64, resolution_y=64),
                                  "layer_out": "random"})
cop_recipe("COPUVShape", lambda: {"out": g("COPUVShape", shape="disk", disk_mode="polar", uv_range="unit",
                                            resolution_x=256, resolution_y=256), "layer_out": "uv"})
cop_recipe("COPUVMap", lambda: {"out": g("COPUVMap", resolution_x=256, resolution_y=256), "layer_out": "uv"})
cop_recipe("COPRipple", lambda: {"in": [_shape()], "out": g("COPRipple", cop=_shape(), source_layer="mask", steps=140,
                                                           resolution_x=256, resolution_y=256),
                                  "layer_in": "mask", "layer_out": "ripple"})


def main(argv):
    if "--list" in argv:
        print("\n".join(sorted(RECIPES)))
        return 0
    want = ["PCG_" + a if not a.startswith("PCG_") else a for a in argv if not a.startswith("-")]
    names = [n for n in sorted(RECIPES) if (not want and "--concepts" not in argv) or n in want]
    os.makedirs(OUT, exist_ok=True)
    built, jobs, fails = {}, {}, []
    for n in names:
        try:
            r = RECIPES[n]()
        except Exception as e:  # noqa: BLE001 -- report and keep going
            fails.append(n)
            print(f"  FAIL {n}: {e}")
            traceback.print_exc(limit=2)
            continue
        built[n] = r
        if n in COP_RECIPES:
            continue
        th, ph = r.get("view", (0.7, 1.1))
        # viewport options: "wire" draws the wireframe, "color" shades with Cd (the default Phong shading ignores it)
        opts = {"wireframe": bool(r.get("wire"))}
        if r.get("color"):
            opts["shading"] = "color"
        opts.update(r.get("opts", {}))      # any other viewport option (show_points, show_normals, shading ...)
        for i, gi in enumerate(r.get("in", [])):
            jobs[f"{n}__in{i}"] = (gi, th, ph, opts)
        jobs[f"{n}__out"] = (r["out"], th, ph, opts)
    concepts = {}
    if not want or "--concepts" in argv:
        for cname, fn in CONCEPTS.items():
            try:
                concepts[cname] = fn()
                for k, (_, geo) in enumerate(concepts[cname]):
                    jobs[f"concept__{cname}__{k}"] = (geo, 0.7, 1.1, {})
            except Exception as e:  # noqa: BLE001
                fails.append(cname)
                print(f"  FAIL concept {cname}: {e}")
    work = tempfile.mkdtemp(prefix="pcgdocimg-")
    shots = render_3d(jobs, work) if jobs else {}
    done = 0
    for n, r in built.items():
        if n in COP_RECIPES:
            ins = [cop_panel(c, r.get("layer_in", "C")) for c in r.get("in", [])]
            out = cop_panel(r["out"], r.get("layer_out", "C"))
        else:
            # one panel per input (at most two), then the output
            k = [f"{n}__in{i}" for i in range(len(r.get("in", [])))]
            if any(x not in shots for x in k) or f"{n}__out" not in shots:
                continue
            ins = [shots[x] for x in k]
            out = shots[f"{n}__out"]
        compose(ins[:2], out).save(os.path.join(OUT, n + ".png"), optimize=True)
        done += 1
    cdir = os.path.join(REPO, "docs", "images", "concepts")
    for cname, panels in concepts.items():
        keys = [f"concept__{cname}__{k}" for k in range(len(panels))]
        if all(k in shots for k in keys):
            os.makedirs(cdir, exist_ok=True)
            labelled([(lab, shots[k]) for (lab, _), k in zip(panels, keys)]).save(
                os.path.join(cdir, cname + ".png"), optimize=True)
            done += 1
    shutil.rmtree(work, ignore_errors=True)
    print(f"{done} pictures -> {OUT}" + (f"; failed: {', '.join(fails)}" if fails else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
