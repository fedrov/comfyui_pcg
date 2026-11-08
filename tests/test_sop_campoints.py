"""
pcg78: Camera To Points, Camera from Points.

Checks do not rely on the implementation itself:
  To Points     point = camera position, point number = frame number; the matrix from orient has +Z = view direction, +Y = up;
                Copy to Points with orient and with only N + up produce the same matrix (same convention);
                the frustum's four corners projected with render.project -> exactly the frame corners (both perspective and ortho)
  Round trip    To Points -> from Points: all camera parameters match; depth maps rendered by both cameras match
                (negative control: flipping up renders differently)
  from Points   auto priority; normal mode roll follows the up attribute; target mode looks at the attribute / parameter;
                path mode looks along +X on a straight line, along the angle bisector at corners, interpolation within a segment is continuous; uniform arc-length sampling
                (uniform even with uneven point spacing and duplicate points); loop's last frame doesn't repeat the first; look ahead looks at a point ahead,
                an open path running past its end extends the last segment; orient sampling uses slerp (negative control: nlerp is off by 0.9°),
                quaternion sign flips don't matter; point attribute interpolation / nearest; groups; errors
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

from comfyui_pcg.geo import campoints as CP             # noqa: E402
from comfyui_pcg.geo import render as R                 # noqa: E402
from comfyui_pcg.geo import sequence as SQ              # noqa: E402
from comfyui_pcg.geo import build                       # noqa: E402
from comfyui_pcg.geo.xform import quat_to_mat, point_matrices  # noqa: E402
from comfyui_pcg.geo.cop.pixel import getn              # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, PRIM  # noqa: E402
from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP      # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def pts_geo(P, **attrs):
    g = Geometry.from_points(np.asarray(P, np.float32))
    for k, v in attrs.items():
        v = np.asarray(v)
        if v.dtype.kind == "U":
            g.set_string(POINT, k, v)
        else:
            g.set(POINT, k, v)
    return g


def fwd(c):
    return np.asarray(c["forward"], np.float64)


def ang(a, b):
    a = np.asarray(a, np.float64)
    b = np.asarray(b, np.float64)
    c = a @ b / (np.linalg.norm(a) * np.linalg.norm(b))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


# ══════════════════════════════════════════════════════ Camera To Points
print("═" * 28, "Camera To Points")
bx = build.box()
cams = SQ.camera_path(bx, frames=8, mode="orbit", elev=15, elev_end=55,
                      xres=320, yres=200, fov=40)
g, fr, rep = CP.cameras_to_points(cams, path=True, frustum_depth=0.7)
P = np.asarray(g.get(POINT, "P"), np.float64)
check("one point per camera, the point is the camera position",
      g.npoints == 8 and np.abs(P - np.stack([c["eye"] for c in cams])).max() < 1e-5)
check("  frame = point number", (np.asarray(g.get(POINT, "frame"))[:, 0] == np.arange(8)).all())
check("  Path: one open polyline connected in frame order",
      g.nprims == 1 and not g.prim_closed[0]
      and list(g.vertex_point) == list(range(8)))
g0, _, _ = CP.cameras_to_points(cams, path=False, frustum_depth=0)
check("  with Path off there are no prims", g0.nprims == 0)
check("  two cameras are also connected by a line; a single one is not",
      CP.cameras_to_points(cams[:2])[0].nprims == 1
      and CP.cameras_to_points(cams[:1])[0].nprims == 0)
M = quat_to_mat(np.asarray(g.get(POINT, "orient"), np.float64))
F = np.stack([fwd(c) for c in cams])
U = np.stack([c["up"] for c in cams])
Rr = np.stack([c["right"] for c in cams])
check("orient: +Z = view direction, +Y = up, +X = left of frame (−right)",
      np.abs(M[:, :, 2] - F).max() < 1e-6 and np.abs(M[:, :, 1] - U).max() < 1e-6
      and np.abs(M[:, :, 0] + Rr).max() < 1e-6,
      float(np.abs(M[:, :, 2] - F).max()))
Mo, _, _ = point_matrices(g)
gn = g.copy()
gn.remove(POINT, "orient")
Mn, _, _ = point_matrices(gn)
check("  Copy to Points with orient and with only N + up gives the same result (same convention)",
      np.abs(Mo - Mn).max() < 1e-5, float(np.abs(Mo - Mn).max()))
check("  N = view direction, up = camera up",
      np.abs(np.asarray(g.get(POINT, "N")) - F).max() < 1e-6
      and np.abs(np.asarray(g.get(POINT, "up")) - U).max() < 1e-6)
tg = np.asarray(g.get(POINT, "target"), np.float64)
check("  target / distance / fov / resolution / projection all carried over",
      np.abs(tg - np.stack([c["target"] for c in cams])).max() < 1e-5
      and np.abs(np.asarray(g.get(POINT, "distance"))[:, 0]
                 - np.linalg.norm(tg - P, axis=1)).max() < 1e-5
      and np.allclose(np.asarray(g.get(POINT, "fov"))[:, 0], 40)
      and (np.asarray(g.get(POINT, "resx"))[:, 0] == 320).all()
      and (np.asarray(g.get(POINT, "resy"))[:, 0] == 200).all()
      and (np.asarray(g.get(POINT, "projection"))[:, 0] == "perspective").all())

# Frustum: the four corners project exactly onto the frame corners
want_sx = np.array([-0.5, 319.5, 319.5, -0.5])
want_sy = np.array([-0.5, -0.5, 199.5, 199.5])
FP = np.asarray(fr.get(POINT, "P"), np.float64)
worst = 0.0
for i, c in enumerate(cams):
    corners = FP[i * 5 + 1:i * 5 + 5]
    sx, sy, z = R.project(c, corners)
    worst = max(worst, np.abs(sx - want_sx).max(), np.abs(sy - want_sy).max(),
                np.abs(z - 0.7).max() * 100)
    worst = max(worst, np.abs(FP[i * 5] - c["eye"]).max() * 100)
check("frustum (perspective): apex at the camera position, base corners project = frame corners, depth = Frustum Depth",
      worst < 1e-3, worst)
base = fr.prim_points(4)
check("  the base frame is a closed loop (first and last are the same point, all 4 edges drawn)",
      len(base) == 5 and base[0] == base[-1] and len(set(base)) == 4)
check("  5 polylines per camera (4 edges + base frame), frame on the prims",
      fr.nprims == 40 and not fr.prim_closed.any()
      and (np.asarray(fr.get(PRIM, "frame"))[:, 0] == np.repeat(np.arange(8), 5)).all())
oc = R.camera(bx, projection="orthographic", frame_geometry=True, xres=256,
              yres=128, elev=30, azim=20)
_, fro, _ = CP.cameras_to_points([oc], frustum_depth=2.0)
FO = np.asarray(fro.get(POINT, "P"), np.float64)
sx, sy, z = R.project(oc, FO)
check("frustum (ortho): a box, both front and back frames project onto the frame corners",
      fro.nprims == 6 and fro.npoints == 8
      and np.abs(sx - np.tile([-0.5, 255.5, 255.5, -0.5], 2)).max() < 1e-3
      and np.abs(sy - np.tile([-0.5, -0.5, 127.5, 127.5], 2)).max() < 1e-3
      and np.abs(z - np.repeat([0.0, 2.0], 4)).max() < 1e-4,
      float(max(np.abs(sx - np.tile([-0.5, 255.5, 255.5, -0.5], 2)).max(),
                np.abs(sy - np.tile([-0.5, -0.5, 127.5, 127.5], 2)).max())))
_, fr0, _ = CP.cameras_to_points(cams, frustum_depth=0)
check("  Frustum Depth = 0 outputs no frustum", fr0.npoints == 0 and fr0.nprims == 0)

# ═════════════════════════════════════════════════════════════ Round trip
print("═" * 28, "Round trip")
look = R.camera(projection="perspective", eye=(3, 2, 4), target=(0.3, 0.1, -0.2),
                up=(0.4, 1, 0), fov=32, xres=300, yres=180, near=0.2, far=40)
orth = R.camera(bx, projection="orthographic", frame_geometry=True, elev=-20,
                azim=130, xres=200, yres=260)
allc = cams + [look, orth]
gp, _, _ = CP.cameras_to_points(allc)
back, rp = CP.cameras_from_points(gp)
worst = 0.0
same_scalar = True
for a, b in zip(allc, back):
    for k in ("eye", "right", "up", "forward", "target"):
        worst = max(worst, float(np.abs(np.asarray(a[k]) - np.asarray(b[k])).max()))
    for k in ("fov", "ortho_size", "near", "far", "radius", "distance"):
        same_scalar &= abs(float(a[k]) - float(b[k])) < 1e-5 * max(1, abs(a[k]))
    same_scalar &= (a["xres"], a["yres"], a["projection"]) == \
        (b["xres"], b["yres"], b["projection"])
check("To Points -> from Points: position / basis / target match (float32 storage)",
      len(back) == 10 and worst < 2e-5 and rp["orientation"] == "orient", worst)
check("  fov / ortho / near / far / radius / distance / resolution / projection match",
      same_scalar)
sph = build.sphere(1.0, 24, 16)
dmax = 0.0
for a, b in ((cams[3], back[3]), (look, back[8]), (orth, back[9])):
    da = getn(R.render(sph, a, passes=("depth",)), "depth")
    db = getn(R.render(sph, b, passes=("depth",)), "depth")
    dmax = max(dmax, float(np.abs(da - db).max()))
check("  a look_at camera's distance is the real camera-to-target distance (not the unused Distance parameter)",
      abs(look["distance"] - np.linalg.norm(np.subtract(look["target"], look["eye"])))
      < 1e-12, look["distance"])
check("  depth maps rendered by both cameras match (perspective / with roll / ortho)", dmax < 1e-4, dmax)
flip = dict(look)
flip["up"] = -np.asarray(look["up"])
flip["right"] = -np.asarray(look["right"])
dn = float(np.abs(getn(R.render(sph, look, passes=("depth",)), "depth")
                  - getn(R.render(sph, flip, passes=("depth",)), "depth")).max())
check("  negative control: flipping up renders clearly differently (this criterion detects orientation)", dn > 0.1, dn)

# ═══════════════════════════════════════════════════ Camera from Points
print("═" * 28, "Camera from Points")
line = pts_geo([[0, 0, 0], [1, 0, 0], [3, 0, 0], [3.5, 0, 0]])
cs, r = CP.cameras_from_points(line)
check("auto with no orientation attributes -> path; all look along +X on a straight line",
      r["orientation"] == "path" and max(ang(fwd(c), [1, 0, 0]) for c in cs) < 1e-9)
check("  position = point, up ⟂ view direction and pointing up",
      np.abs(np.stack([c["eye"] for c in cs]) - [[0, 0, 0], [1, 0, 0], [3, 0, 0],
                                                  [3.5, 0, 0]]).max() < 1e-9
      and all(abs(np.dot(c["up"], fwd(c))) < 1e-9 and c["up"][1] > 0.99 for c in cs))
g_all = pts_geo([[0, 0, 0], [1, 0, 0]], orient=[[0, 0, 0, 1]] * 2,
                N=[[0, 1, 0]] * 2, target=[[0, 0, 5]] * 2)
g3 = pts_geo([[0, 0, 0], [1, 0, 0]], orient=[[0, 0, 1], [0, 0, 1]])
check("  an attribute named orient with only 3 components is not used as a quaternion (auto falls back to path)",
      CP.cameras_from_points(g3)[1]["orientation"] == "path")
check("auto priority: orient > N > target > path",
      CP.cameras_from_points(g_all)[1]["orientation"] == "orient")
g_all.remove(POINT, "orient")
c1, r1 = CP.cameras_from_points(g_all, up=(0, 0, 1))
check("  without orient use N", r1["orientation"] == "normal"
      and ang(fwd(c1[0]), [0, 1, 0]) < 1e-9)
g_all.remove(POINT, "N")
check("  without N use target", CP.cameras_from_points(g_all)[1]["orientation"] == "target")

# normal mode: roll follows the up attribute
gN = pts_geo([[0, 0, 0]], N=[[0, 0, -1]], up=[[1, 1, 0]])
cN = CP.cameras_from_points(gN, orientation="normal")[0][0]
check("normal: view direction = N; the up attribute sets roll (camera up lies in the (up attribute, N) plane, 45°)",
      ang(fwd(cN), [0, 0, -1]) < 1e-9
      and ang(cN["up"], [1, 1, 0]) < 1e-6, cN["up"])
cN2 = CP.cameras_from_points(pts_geo([[0, 0, 0]], N=[[0, 0, -3]]),
                             orientation="normal", up=(0, 1, 0))[0][0]
check("  without an up attribute use the Up parameter", ang(cN2["up"], [0, 1, 0]) < 1e-9)
check("  target = position + unit view direction × Focus Distance (also when N is not unit length)",
      np.abs(cN2["target"] - [0, 0, -5]).max() < 1e-9 and abs(cN2["distance"] - 5) < 1e-9)

# target mode
gT = pts_geo([[0, 0, 0], [4, 0, 0]], target=[[0, 3, 0], [4, 0, 3]])
cT = CP.cameras_from_points(gT, orientation="target")[0]
check("target: each camera looks at its own target attribute",
      ang(fwd(cT[0]), [0, 1, 0]) < 1e-9 and ang(fwd(cT[1]), [0, 0, 1]) < 1e-9)
check("  distance = real distance to target (not Focus Distance)",
      abs(cT[0]["distance"] - 3) < 1e-9 and abs(cT[1]["distance"] - 3) < 1e-9)
cT2 = CP.cameras_from_points(pts_geo([[5, 0, 0], [0, 0, 5]]), orientation="target",
                             target=(1, 0, 1))[0]
check("  no target attribute: all look at the Target parameter",
      ang(fwd(cT2[0]), [-4, 0, 1]) < 1e-9 and ang(fwd(cT2[1]), [1, 0, -4]) < 1e-9)

# path: corner = angle bisector; interpolation within a segment is continuous
L = pts_geo([[0, 0, 0], [2, 0, 0], [2, 0, 2]])
cL = CP.cameras_from_points(L, orientation="path")[0]
check("path: looks along the angle bisector at corners (sum of the unit directions of the two segments)",
      ang(fwd(cL[1]), [1, 0, 1]) < 1e-9 and ang(fwd(cL[0]), [1, 0, 0]) < 1e-9
      and ang(fwd(cL[2]), [0, 0, 1]) < 1e-9)
cR = CP.cameras_from_points(L, orientation="path", frames=41)[0]
steps = [ang(fwd(cR[i]), fwd(cR[i + 1])) for i in range(40)]
check("  the view direction turns continuously between samples (no sudden 45° turn at the corner)", max(steps) < 5.0,
      round(max(steps), 3))
t_mid = np.array([1, 0, 0]) + np.array([1, 0, 1]) / math.sqrt(2)
check("  interpolation at a segment midpoint = halfway between the endpoint tangents (between 0° and 45° -> 22.5°)",
      ang(fwd(cR[10]), t_mid) < 1e-6 and abs(ang(fwd(cR[10]), [1, 0, 0]) - 22.5) < 1e-6,
      fwd(cR[10]))

# Uniform arc-length sampling, uneven point spacing, duplicate points
U4 = pts_geo([[0, 0, 0], [0.3, 0, 0], [0.3, 0, 0], [4, 0, 0], [5, 0, 0]])
cU = CP.cameras_from_points(U4, orientation="path", frames=6)[0]
ex = np.array([c["eye"][0] for c in cU])
check("Frames: uniform by arc length (uneven spacing + duplicate points)",
      np.abs(ex - np.linspace(0, 5, 6)).max() < 1e-9
      and all(np.isfinite(fwd(c)).all() for c in cU), ex)
sq = pts_geo([[0, 0, 0], [2, 0, 0], [2, 0, 2], [0, 0, 2]])
cS = CP.cameras_from_points(sq, orientation="path", frames=8, loop=True)[0]
E = np.stack([c["eye"] for c in cS])
dd = np.linalg.norm(np.diff(np.vstack([E, E[:1]]), axis=0), axis=1)
check("Loop: 8 cameras evenly on a closed path, last frame doesn't repeat the first (last to first is also one step)",
      len(cS) == 8 and np.abs(dd - 1.0).max() < 1e-9, dd)
cS0 = CP.cameras_from_points(sq, orientation="path", loop=True)[0]
check("  with Loop the start tangent is also a bisector (the closing segment is included)",
      ang(fwd(cS0[0]), [1, 0, -1]) < 1e-9, fwd(cS0[0]))
cO = CP.cameras_from_points(sq, orientation="path", frames=8, loop=False)[0]
check("  without Loop: closed interval, last frame on the last point",
      np.abs(cO[-1]["eye"] - [0, 0, 2]).max() < 1e-9)

# look ahead
n = 64
th = np.linspace(0, 2 * np.pi, n, endpoint=False)
circ = pts_geo(np.stack([np.cos(th), np.zeros(n), np.sin(th)], 1))
cA = CP.cameras_from_points(circ, orientation="path", loop=True, look_ahead=0.8)[0]
arc = 2 * n * math.sin(math.pi / n)                 # polygon perimeter
a_ahead = 0.8 / arc * 2 * math.pi
tgt_ok = max(np.linalg.norm(c["target"] - [math.cos(t + a_ahead), 0,
                                            math.sin(t + a_ahead)])
             for c, t in zip(cA, th))
check("Look Ahead: looks at the point that far ahead on the path (points on a circle, error only from polyline approximation)",
      tgt_ok < 5e-3, tgt_ok)
cE = CP.cameras_from_points(line, orientation="path", look_ahead=2.0)[0]
check("  open path running past the end: extends the last segment, the last camera still looks along +X (not degenerate)",
      ang(fwd(cE[-1]), [1, 0, 0]) < 1e-9
      and np.abs(cE[-1]["target"] - [5.5, 0, 0]).max() < 1e-9)

# orient slerp
q0 = [0, 0, 0, 1]
q1 = [0, math.sin(math.radians(45)), 0, math.cos(math.radians(45))]   # 90° about Y
gq = pts_geo([[0, 0, 0], [1, 0, 0]], orient=[q0, q1])
cq = CP.cameras_from_points(gq, orientation="orient", frames=5)[0]
yaw = [math.degrees(math.atan2(fwd(c)[0], fwd(c)[2])) for c in cq]
check("orient sampling uses slerp: a quarter of the way from 0° to 90° is exactly 22.5°",
      abs(yaw[1] - 22.5) < 1e-6 and abs(yaw[2] - 45) < 1e-6 and abs(yaw[4] - 90) < 1e-6,
      [round(y, 4) for y in yaw])
nl = np.array(q0) * 0.75 + np.array(q1) * 0.25
nl /= np.linalg.norm(nl)
Mn = quat_to_mat(nl)[0]
check("  negative control: nlerp is off by nearly 1° at the same spot (the criterion tells them apart)",
      abs(math.degrees(math.atan2(Mn[0, 2], Mn[2, 2])) - 22.5) > 0.5)
gq2 = pts_geo([[0, 0, 0], [1, 0, 0]], orient=[q0, [-v for v in q1]])
cq2 = CP.cameras_from_points(gq2, orientation="orient", frames=5)[0]
check("  q and −q are the same rotation: flipping the sign of the second doesn't change the result (no long way round)",
      max(ang(fwd(a), fwd(b)) for a, b in zip(cq, cq2)) < 1e-6)

gs = pts_geo([[0, 0, 0], [1, 0, 0]], orient=[q1, q1])
cs_ = CP.cameras_from_points(gs, orientation="orient", frames=3)[0]
check("  identical orient at both ends: no NaN (slerp's sin θ = 0)",
      all(np.isfinite(fwd(c)).all() and ang(fwd(c), [1, 0, 0]) < 1e-6 for c in cs_))

# Degenerate tangent cases
T3 = pts_geo([[0, 0, 0], [1, 0, 0], [1, 0, 0], [1, 0, 0], [2, 0, 1]])
cT3 = CP.cameras_from_points(T3, orientation="path")[0]
check("path: three consecutive duplicate points, the middle one has no nonzero-length neighbouring segment -> uses the direction of the first segment after",
      ang(fwd(cT3[2]), [1, 0, 1]) < 1e-9, fwd(cT3[2]))
T4 = pts_geo([[0, 0, 0], [1, 0, 0], [1, 0, 1], [1, 0, 1]])
cT4 = CP.cameras_from_points(T4, orientation="path")[0]
check("  duplicate points at the tail of an open path (no segment after) -> uses the direction of the **last** segment before",
      ang(fwd(cT4[3]), [0, 0, 1]) < 1e-9, fwd(cT4[3]))
cT5 = CP.cameras_from_points(T4, orientation="path", look_ahead=1.0)[0]
check("  Look Ahead running past the end when the tail is duplicate points: extends along the last **nonzero-length** segment",
      ang(fwd(cT5[3]), [0, 0, 1]) < 1e-9, fwd(cT5[3]))
Rv = pts_geo([[0, 0, 0], [1, 0, 0], [0, 0, 0.5]])
cRv = CP.cameras_from_points(Rv, orientation="path")[0]
check("  near doubling back (angle > 90°) is still a bisector, not NaN",
      all(np.isfinite(fwd(c)).all() for c in cRv))
Rv2 = pts_geo([[0, 0, 0], [1, 0, 0], [-1, 0, 0], [-1, 0, 2]])
cRv2 = CP.cameras_from_points(Rv2, orientation="path")[0]
check("  exact 180° reversal (sum of the two directions = 0) -> looks along the returning segment (not the one after)",
      ang(fwd(cRv2[1]), [-1, 0, 0]) < 1e-9, fwd(cRv2[1]))
one = CP.cameras_from_points(pts_geo([[1, 2, 3]], N=[[0, 0, 1]]), frames=3)[0]
check("only one point, Frames = 3: three identical cameras",
      len(one) == 3 and all(np.abs(c["eye"] - [1, 2, 3]).max() < 1e-9 for c in one))
same = CP.cameras_from_points(pts_geo([[1, 0, 0], [1, 0, 0]]), orientation="target",
                              frames=3, loop=True)[0]
check("  all points coincide + Loop + Frames: no NaN (no modulo by 0 when path length is 0)",
      all(np.isfinite(c["eye"]).all() for c in same))

# Point attributes
gA = pts_geo([[0, 0, 0], [1, 0, 0]], fov=[[30.0], [60.0]],
             resx=np.array([[100], [200]], np.int32),
             projection=np.array(["perspective", "orthographic"]))
cF = CP.cameras_from_points(gA, orientation="path", frames=5, fov=45)[0]
check("point attributes: fov interpolated linearly, resolution / projection from the nearer point",
      [round(c["fov"], 6) for c in cF] == [30, 37.5, 45, 52.5, 60]
      and [c["xres"] for c in cF] == [100, 100, 100, 200, 200]
      and [c["projection"] for c in cF][1:4] == ["perspective", "perspective",
                                                 "orthographic"],
      [(c["fov"], c["xres"], c["projection"]) for c in cF])
gBad = pts_geo([[0, 0, 0], [1, 0, 0]], projection=np.array(["fisheye", "fisheye"]))
check("  unrecognized projection attribute -> use the parameter",
      all(c["projection"] == "orthographic" for c in
          CP.cameras_from_points(gBad, projection="orthographic")[0]))
cF0 = CP.cameras_from_points(gA, orientation="path", fov=45, xres=64,
                             use_point_attributes=False)[0]
check("  with Use Point Attributes off, use the parameters",
      all(c["fov"] == 45 and c["xres"] == 64 and c["projection"] == "perspective"
          for c in cF0))

# Groups, vertical path, errors
gG = pts_geo([[0, 0, 0], [1, 0, 0], [9, 9, 9], [2, 0, 0]])
gG.groups[POINT]["keep"] = np.array([True, True, False, True])
cG = CP.cameras_from_points(gG, group="keep")[0]
check("group: only points in the group are used", len(cG) == 3
      and max(ang(fwd(c), [1, 0, 0]) for c in cG) < 1e-9)
cV = CP.cameras_from_points(pts_geo([[0, 0, 0], [0, 1, 0]]), orientation="path")[0]
check("vertical path (view direction ∥ Up): no NaN, basis still orthogonal",
      all(np.isfinite(c["up"]).all() and abs(np.dot(c["up"], fwd(c))) < 1e-9
          for c in cV))
errs = []
for kw in (dict(geo=pts_geo([[0, 0, 0]]), orientation="orient"),
           dict(geo=pts_geo([[0, 0, 0]]), orientation="normal"),
           dict(geo=pts_geo([[1, 0, 0], [1, 0, 0]]), orientation="path"),
           dict(geo=pts_geo([[0, 0, 0]]), orientation="bad"),
           dict(geo=pts_geo([[0, 0, 0]]), projection="fisheye")):
    try:
        CP.cameras_from_points(**kw)
        errs.append(kw)
    except (KeyError, ValueError):
        pass
try:
    CP.cameras_to_points([])
    errs.append("empty")
except ValueError:
    pass
check("errors: missing orient / N, zero path length, bad option, no cameras", not errs, errs)

# ═════════════════════════════════════════════════════════════ Nodes
print("═" * 28, "Nodes")


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


N2P = MAP["PCG_CameraToPoints"]
r2 = unwrap(N2P().run(**defaults(N2P, cams=cams, cam=look)))
check("Camera To Points node: cams + cam combined (cam last)",
      r2[0].npoints == 9
      and np.abs(np.asarray(r2[0].get(POINT, "P"))[-1] - look["eye"]).max() < 1e-5)
try:
    N2P().run(**defaults(N2P))
    check("  nothing connected -> raises", False)
except ValueError as ex:
    check("  nothing connected -> raises, with a long enough message", len(str(ex)) >= 8, str(ex))
P2C = MAP["PCG_CameraFromPoints"]
r3 = unwrap(P2C().run(**defaults(P2C, geo=r2[0])))
check("Camera from Points node: round trip with default parameters, frames output = camera count",
      len(r3[0]) == 9 and r3[1] == 9
      and np.abs(r3[0][-1]["forward"] - look["forward"]).max() < 1e-5)
seq = SQ.render_sequence(sph, r3[0][:3], passes=("depth",))
seq = seq[0] if isinstance(seq, tuple) else seq
check("  the output cameras can feed Render Sequence directly",
      len(seq) == 3 and getn(seq[0], "depth").shape[:2] == (200, 320))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
