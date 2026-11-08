"""
pcg80: near-plane clipping for rasterization.

The reference does not rely on the implementation itself -- spatial.ray_cast is used per pixel as the reference (two independent implementations: screen-space scan conversion
vs 3D ray intersection):
  standing on a large ground plane, looking level   the ground is there as a whole (before, it was dropped entirely); each pixel's hit face, depth, interpolated
                        position / uv all match the rays; depth also matches the analytic solution h / (−ndy·tan)
  looking out from inside a box   four of the six faces cross the near plane; full coverage, no holes; hits and depth match per pixel
  backface culling             clipped sub-triangles are still culled by the original triangle's winding
  orthographic camera            parallel-ray reference
  negative control                 fraction of pixels whose hit is a "triangle crossing the near plane" -- without clipping all of these pixels would be holes
  scene not crossing the near plane      matches the rays; when the near plane cuts into a sphere you see the inner wall (rays start at the near plane)
  downstream                 Render channels and motion vectors are finite on a shot passing through the ground
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

from comfyui_pcg.geo import render as R                 # noqa: E402
from comfyui_pcg.geo import sequence as SQ              # noqa: E402
from comfyui_pcg.geo import build, ops                  # noqa: E402
from comfyui_pcg.geo.spatial import ray_cast, tri_soup  # noqa: E402
from comfyui_pcg.geo.cop.pixel import getn              # noqa: E402
from comfyui_pcg.geo.core import POINT, VERTEX          # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def rays(cam):
    """A ray through each pixel center (same pixel convention as render.project)."""
    W, H = cam["xres"], cam["yres"]
    px, py = np.meshgrid(np.arange(W), np.arange(H))
    ndx = (px + 0.5) * 2.0 / W - 1.0
    ndy = (py + 0.5) * 2.0 / H - 1.0
    r, u, f = cam["right"], cam["up"], cam["forward"]
    if cam["projection"] == "perspective":
        h = math.tan(math.radians(cam["fov"]) / 2)
        a = W / H
        D = f + (ndx * h * a)[..., None] * r + (ndy * h)[..., None] * u
        O = np.broadcast_to(cam["eye"], D.shape)
    else:
        h = cam["ortho_size"] / 2
        a = W / H
        O = cam["eye"] + (ndx * h * a)[..., None] * r + (ndy * h)[..., None] * u
        D = np.broadcast_to(f, O.shape)
    return O.reshape(-1, 3), D.reshape(-1, 3), ndy


def compare(geo, cam):
    """Rasterization vs rays: returns (coverage matches, hit prim match rate, max depth error, raster result, ray hits)."""
    rast = R.rasterize(geo, cam)
    tri, src, _ = tri_soup(geo)
    O, D, _ = rays(cam)
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    Dn = D / np.linalg.norm(D, axis=1, keepdims=True)
    near = cam["near"]
    # Rays start on the near plane: the part cut away in front of the near plane should not be visible anyway
    t0 = near / (Dn @ cam["forward"])
    ti, t, _ = ray_cast(O + Dn * t0[:, None], Dn, P, tri)
    t = t + t0
    zr = t * (Dn @ cam["forward"])
    ok_ray = ti >= 0
    hit = rast["hit"].reshape(-1)
    cov = np.array_equal(hit >= 0, ok_ray)
    both = (hit >= 0) & ok_ray
    same = float((rast["src"][hit[both]] == src[ti[both]]).mean()) if both.any() else 1.0
    dz = float(np.abs(rast["z"].reshape(-1)[both] - zr[both]).max()) if both.any() else 0.0
    return cov, same, dz, rast, (ti, t, O, Dn)


# ═══════════════════════════════════════════════════ Standing on the ground
print("═" * 28, "Standing on the ground")
ground = build.grid(40, 40, 2, 2)                       # one quad = two triangles
uv = np.asarray(ground.get(POINT, "P"))[np.asarray(ground.vertex_point)][:, [0, 2]] / 40 + 0.5
ground.set(VERTEX, "uv", uv.astype(np.float32))
cam = R.camera(projection="perspective", eye=(0.3, 1.0, 0.2), target=(5, 1.0, 1.0),
               fov=60, xres=96, yres=64, near=0.05)
P = np.asarray(ground.get(POINT, "P"), np.float64)
zt = R.project(cam, P)[2]
check("precondition: some ground corners are behind the camera (both triangles cross the near plane)",
      (zt < 0).any() and (zt > 0).any())
cov, same, dz, rast, (ti, t, O, Dn) = compare(ground, cam)
m = rast["hit"] >= 0
check("ground still there: below the horizon (rows a bit away from the horizon) all ground, above all empty",
      m[:20].all() and not m[32:].any(), (int(m[:20].sum()), int(m[32:].sum())))
check("  coverage matches the rays per pixel, same face hit, depth diff < 1e-9", cov and same == 1.0 and dz < 1e-9,
      (cov, same, dz))
_, _, ndy = rays(cam)
h = math.tan(math.radians(60) / 2)
za = 1.0 / (-ndy * h)
check("  depth = analytic solution h / (−ndy·tan(fov/2))",
      np.abs(rast["z"][m] - za[m]).max() < 1e-9, float(np.abs(rast["z"][m] - za[m]).max()))
img = R.render(ground, cam, passes=("position", "uv"))
Pr = getn(img, "P")
hitp = (O + Dn * t[:, None]).reshape(64, 96, 3)
# COP layers are float32, so the tolerance here is on the order of float32 (scene scale 20)
check("  interpolated position = point hit by the ray (barycentrics mapped back to the original triangle correctly)",
      np.abs(Pr[m] - hitp[m]).max() < 5e-6, float(np.abs(Pr[m] - hitp[m]).max()))
U = getn(img, "uv")
check("  uv (vertex attribute) = analytic uv at that point",
      np.abs(U[m] - (hitp[m][:, [0, 2]] / 40 + 0.5)).max() < 1e-6)
Bx = rast["bary"][m]
tri_g, _, _ = tri_soup(ground)
Pb = np.einsum("nk,nkj->nj", Bx, P[tri_g[rast["hit"][m]]])
check("  interpolating directly with bary (float64) differs from the ray hit point by < 1e-9",
      np.abs(Pb - hitp[m]).max() < 1e-9, float(np.abs(Pb - hitp[m]).max()))
check("  each bary row sums to 1, all within [0,1]",
      np.abs(rast["bary"][m].sum(1) - 1).max() < 1e-12
      and rast["bary"][m].min() > -1e-9 and rast["bary"][m].max() < 1 + 1e-9)

# ═══════════════════════════════════════════════════ Inside the box
print("═" * 28, "Inside the box")
room = build.box((4, 3, 5))
cam2 = R.camera(projection="perspective", eye=(0.5, 0.2, -0.3), target=(2, 0.6, 1.5),
                up=(0.1, 1, 0), fov=80, xres=80, yres=60, near=0.1)
cov, same, dz, rast2, (ti2, _, _, _) = compare(room, cam2)
check("looking out from inside the box: full coverage, no holes", (rast2["hit"] >= 0).all(), int((rast2["hit"] < 0).sum()))
check("  hit faces and depth match the rays per pixel", cov and same == 1.0 and dz < 1e-9, (same, dz))
Pm = np.asarray(room.get(POINT, "P"), np.float64)
tri_r, _, _ = tri_soup(room)
O2, D2, _ = rays(cam2)
D2 = D2 / np.linalg.norm(D2, axis=1, keepdims=True)
_, t2, _ = ray_cast(O2, D2, Pm, tri_r)
Pb2 = np.einsum("nk,nkj->nj", rast2["bary"].reshape(-1, 3), Pm[tri_r[rast2["hit"].reshape(-1)]])
e2 = float(np.abs(Pb2 - (O2 + D2 * t2[:, None])).max())
check("  point interpolated with bary = ray hit point (both sub-triangles split from the quad are correct)", e2 < 1e-9, e2)
tri, src, _ = tri_soup(room)
zr = R.project(cam2, np.asarray(room.get(POINT, "P"), np.float64))[2][tri]
crossing = ((zr > cam2["near"]).sum(1) % 3) != 0
frac = float(crossing[rast2["hit"].reshape(-1)].mean())
check("  negative control: pixels hitting triangles that cross the near plane are a majority (without clipping all would be holes)", frac > 0.5, round(frac, 3))
# Backface culling: box normals point outward, so from inside everything is a back face
rb = R.rasterize(room, cam2, cull="back")
rf = R.rasterize(room, cam2, cull="front")
check("backface culling uses the original triangle's winding: inside, cull=back shows nothing, cull=front full coverage",
      (rb["hit"] < 0).all() and np.array_equal(rf["hit"], rast2["hit"]))

# Far plane: a triangle is dropped only if all three vertices are beyond the far plane (old rule, unchanged; still applies after clipping)
fine = build.grid(40, 40, 21, 21)
camf = dict(cam)
camf["far"] = 8.0
rf0 = R.rasterize(fine, cam)
rf8 = R.rasterize(fine, camf)
trf, _, _ = tri_soup(fine)
zf = R.project(cam, np.asarray(fine.get(POINT, "P"), np.float64))[2][trf]
beyond = (zf >= 8.0).all(1)
h0 = rf0["hit"]
gone = (h0 >= 0) & (rf8["hit"] < 0)
check("far plane: the missing pixels are exactly those on triangles with 'all three vertices beyond the far plane'",
      gone.any() and np.array_equal(gone, (h0 >= 0) & beyond[np.maximum(h0, 0)]),
      int(gone.sum()))

# ═══════════════════════════════════════════════════ Orthographic
print("═" * 28, "Orthographic")
cam3 = R.camera(projection="orthographic", eye=(0, 0.5, 0), target=(0, 0.5, 3),
                ortho_size=2.0, xres=48, yres=48, near=0.2)
cov, same, dz, rast3, _ = compare(room, cam3)
check("orthographic camera inside the box: coverage / hits / depth match parallel rays",
      cov and same == 1.0 and dz < 1e-9 and (rast3["hit"] >= 0).all(), (cov, same, dz))

# ═══════════════════════════════════════════════════ Not crossing the near plane
print("═" * 28, "Not crossing the near plane")
sph = build.sphere(1.0, 32, 20)
cam4 = R.camera(sph, frame_geometry=True, xres=64, yres=64)
r4 = R.rasterize(sph, cam4)
cov, same, dz, _, _ = compare(sph, cam4)
check("ordinary camera position (no triangle crosses the near plane): matches the rays", cov and same == 1.0 and dz < 1e-9, (same, dz))
tri4, _, _ = tri_soup(sph)
zz4 = R.project(cam4, np.asarray(sph.get(POINT, "P"), np.float64))[2][tri4]
check("  precondition: really none cross", (zz4 > cam4["near"]).all())
cam5 = dict(cam4)
cam5["near"] = float(np.sort(zz4.reshape(-1))[len(zz4) * 3 // 2])      # near plane cuts into the sphere
r5 = R.rasterize(sph, cam5)
cov, same, dz, _, _ = compare(sph, cam5)
check("  near plane cuts into the sphere: inner wall of the sphere visible, matches the rays", cov and same == 1.0 and dz < 1e-9, (same, dz))

# ═══════════════════════════════════════════════════ Downstream
print("═" * 28, "Downstream")
scene = ops.merge(build.grid(30, 30, 2, 2), build.box((1, 1, 1), (3, 0.5, 0)))
cams = SQ.camera_path(scene, frames=3, mode="interpolate", eye=(-2, 1, 0),
                      eye_end=(1, 1, 0), target=(5, 0.8, 0), target_end=(8, 0.8, 0),
                      frame_geometry=False, loop=False, xres=64, yres=48)
mv = SQ.motion_vectors(scene, cams[0], cam_next=cams[1])
M = getn(mv, "motion")
mk = getn(mv, "mask")[..., 0] > 0
check("dolly shot through the ground: motion vectors finite, the ground has motion vectors too (not a hole)",
      np.isfinite(M).all() and mk.mean() > 0.4, float(mk.mean()))
img = R.render(scene, cams[0], passes=("depth", "normal", "mask"))
check("  Render depth / normal are all finite", all(np.isfinite(getn(img, k)).all()
                                                for k in ("depth", "N", "mask")))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
