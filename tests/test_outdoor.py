"""
pcg123: the Outdoor look of Geometry Preview (geo/outdoor.py), checked against geometry rather than by eye.

  1. Sky: bluer at the zenith than at the horizon; the brightest pixel is where the sun is when the camera looks at it
  2. Camera: the covered pixels of a box equal its analytic projection through the Camera node (IoU > 0.97);
     negative control: the projection through a shifted camera does not match
  3. Sun shadow: on the ground plane the shadow lies on the side away from the sun (sun in +X -> darker at -X), and
     moves with Sun Azimuth; with the ground plane off the ground pixels are sky
  4. Aerial perspective: a far ground pixel moves toward the horizon colour as Haze grows; Haze 0 leaves it alone
  5. Automatic camera frames the geometry (the box spans most of the frame) for any Elevation / Azimuth
  6. The node: look = outdoor with and without a camera, PBR textures from a COP image, a bad Ground Color raises
"""
import os
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (os.path.dirname(_R), os.path.dirname(os.path.dirname(_R))):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy  # noqa: F401,E402
import numpy as np  # noqa: E402

import comfyui_pcg  # noqa: E402,F401
from comfyui_pcg.geo import build, outdoor as O, render as R, Geometry  # noqa: E402
from comfyui_pcg.geo.core import POINT  # noqa: E402

N = comfyui_pcg.NODE_CLASS_MAPPINGS
OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if isinstance(extra, str) and extra == "" else "   " + str(extra)))


W, H = 160, 120
print("\n[1. Sky]")
cam_up = R.camera(None, "perspective", eye=(0, 1, 0), target=(0, 1.6, -1), fov=70)
sky = O.render_outdoor(Geometry(), W, H, cam=cam_up, ssaa=1)
top, low = sky[2].mean(0), sky[-3].mean(0)
check("bluer at the top of the frame (higher up the sky) than lower down", (top[2] - top[0]) > (low[2] - low[0]),
      (np.round(top, 3), np.round(low, 3)))
L = O.sun_dir(30, 160)
cam_sun = R.camera(None, "perspective", eye=(0, 0, 0), target=tuple(L), fov=40)
ss = O.render_outdoor(Geometry(), W, H, cam=cam_sun, ssaa=1, sun_elev=30, sun_azim=160)
lum_ = ss.sum(-1)
ys_, xs_ = np.nonzero(lum_ >= lum_.max() - 1e-3)
iy, ix = ys_.mean(), xs_.mean()
check("looking at the sun: the brightest pixels (the sun disc) are centred in the frame",
      abs(iy - H / 2 + 0.5) <= 1.5 and abs(ix - W / 2 + 0.5) <= 1.5, (round(iy, 1), round(ix, 1)))
cam_away = R.camera(None, "perspective", eye=(0, 0, 0), target=tuple(-L * np.array([1, -1, 1])), fov=40)
sa = O.render_outdoor(Geometry(), W, H, cam=cam_away, ssaa=1, sun_elev=30, sun_azim=160)
check("  negative control: looking away from the sun, no pixel is that bright", sa.sum(-1).max() < ss.sum(-1).max() - 0.3)

print("\n[2. Camera]")
box = build.box(size=(1, 1, 1)) if "size" in build.box.__code__.co_varnames else build.box()
P = np.asarray(box.get(POINT, "P"), np.float64)
cam = R.camera(None, "perspective", eye=(2.2, 1.4, 3.0), target=(0.1, 0.0, -0.1), fov=40)
base = O.render_outdoor(Geometry(), W, H, cam=cam, ssaa=1)
img = O.render_outdoor(box, W, H, cam=cam, ssaa=1, ground=False, haze=0)
cov = np.abs(img - base).sum(-1) > 0.02


def mask_of(c):
    rs = R.rasterize(box, dict(c, xres=W, yres=H))
    return (rs["hit"] >= 0)[::-1]            # rasterizer rows start at the bottom


ref = mask_of(cam)
iou = (cov & ref).sum() / max((cov | ref).sum(), 1)
check("covered pixels = the box's projection through the Camera node (IoU > 0.97)", iou > 0.97, round(float(iou), 4))
sh = dict(cam)
sh["eye"] = cam["eye"] + cam["right"] * 0.4
iou2 = (cov & mask_of(sh)).sum() / max((cov | mask_of(sh)).sum(), 1)
check("  negative control: a camera shifted 0.4 m sideways does not match", iou2 < 0.85, round(float(iou2), 4))

print("\n[3. Sun shadow]")
tall = build.box(size=(0.4, 2.0, 0.4)) if "size" in build.box.__code__.co_varnames else build.box()
Pt = np.asarray(tall.get(POINT, "P"), np.float64)
if "size" not in build.box.__code__.co_varnames:
    Pt = Pt * np.array([0.4, 2.0, 0.4])
Pt[:, 1] -= Pt[:, 1].min()
tall.set(POINT, "P", Pt.astype(np.float32))
topcam = R.camera(None, "perspective", eye=(0.0, 9.0, 0.01), target=(0, 0, 0), fov=60)


def ground_lr(azim):
    im = O.render_outdoor(tall, W, H, cam=topcam, ssaa=1, sun_elev=35, sun_azim=azim, haze=0)
    lum = im.mean(-1)
    # the camera's right is +X in this top view (up = -Z): left half of the frame = -X
    rc = R.camera(None, "perspective", eye=(0.0, 9.0, 0.01), target=(0, 0, 0), fov=60)
    xsgn = np.sign(rc["right"][0])
    row = lum[H // 2]
    left, right = row[W // 2 - 40: W // 2 - 12].mean(), row[W // 2 + 12: W // 2 + 40].mean()
    return (left, right) if xsgn > 0 else (right, left)


lm, lp = ground_lr(90.0)          # sun toward +X
check("sun toward +X: the ground at -X (behind the post) is darker than at +X", lm < lp - 0.05, (round(lm, 3), round(lp, 3)))
lm2, lp2 = ground_lr(-90.0)       # sun toward -X
check("  turning the sun to -X moves the shadow to +X", lp2 < lm2 - 0.05, (round(lm2, 3), round(lp2, 3)))
noground = O.render_outdoor(tall, W, H, cam=topcam, ssaa=1, ground=False, haze=0)
check("  ground plane off: the ground pixels show the sky (below-horizon colour), no shadow",
      abs(noground[H // 2, 20].mean() - noground[H // 2, W - 20].mean()) < 0.01)

print("\n[4. Aerial perspective]")
lowcam = R.camera(None, "perspective", eye=(0, 1.7, 8), target=(0, 1.0, -30), fov=50)
pix = {}
for hz in (0.0, 1.0, 6.0):
    im = O.render_outdoor(tall, W, H, cam=lowcam, ssaa=1, haze=hz)
    pix[hz] = im[H // 2 + 6, 10]                   # far ground just below the horizon
horizon = O.sky_radiance(np.array([[0.0, 0.02, -1.0]]), O.sun_dir(35, 135), sun=False)[0]
from comfyui_pcg.geo import studio as S  # noqa: E402
hz_disp = S.linear_to_srgb(S.filmic(horizon))
d = {k: float(np.abs(v - hz_disp).sum()) for k, v in pix.items()}
check("far ground moves toward the horizon colour as Haze grows (0 > 1 > 6 in distance to it)",
      d[0.0] > d[1.0] > d[6.0], {k: round(v, 3) for k, v in d.items()})
near0 = O.render_outdoor(tall, W, H, cam=lowcam, ssaa=1, haze=0.0)[H - 3, W // 2]
near6 = O.render_outdoor(tall, W, H, cam=lowcam, ssaa=1, haze=6.0)[H - 3, W // 2]
check("  the ground at the camera's feet barely changes", np.abs(near0 - near6).max() < 0.05)

print("\n[5. Automatic camera]")
okf = True
for el, az in ((25, 35), (60, -120), (10, 200)):
    a = O.render_outdoor(box, W, H, elev=el, azim=az, ssaa=1, ground=False, haze=0)
    b = O.render_outdoor(Geometry(), W, H, cam=O.auto_camera(box, W, H, el, az), ssaa=1)
    m = np.abs(a - b).sum(-1) > 0.02
    ys, xs = np.nonzero(m)
    span = max((ys.max() - ys.min() + 1) / H, (xs.max() - xs.min() + 1) / W) if len(ys) else 0
    okf &= 0.8 < span <= 1.0 and ys.min() > 0 and xs.min() > 0 and ys.max() < H - 1 and xs.max() < W - 1
check("the box fills 80-100% of the frame in one direction and never touches the border", okf)

print("\n[6. The node]")
node = N["PCG_PreviewImage"]()
r1 = node.run(box, 96, 64, 25, 35, "color", look="outdoor", supersampling=1)
r1 = r1["result"] if isinstance(r1, dict) else r1
r2 = node.run(box, 96, 64, 25, 35, "color", look="outdoor", supersampling=1, camera=cam, sun_elevation=50,
              sun_azimuth=10, haze=0.5, ground_plane=False, ground_color="0.2 0.3 0.1", exposure=1.3)
r2 = r2["result"] if isinstance(r2, dict) else r2
check("look = outdoor runs with the automatic camera and with a Camera input", tuple(r1[0].shape) == (1, 64, 96, 3)
      and tuple(r2[0].shape) == (1, 64, 96, 3))
try:
    node.run(box, 32, 32, 25, 35, "color", look="outdoor", supersampling=1, ground_color="green")
    bad = False
except ValueError:
    bad = True
check("  a Ground Color that is not three numbers raises", bad)


def nrun(name, **kw):
    c = N["PCG_" + name]
    args = {}
    for sec in ("required", "optional"):
        for k, spec in c.INPUT_TYPES().get(sec, {}).items():
            t = spec[0]
            opt = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            if isinstance(t, list):
                args[k] = t[0]
            elif "default" in opt:
                args[k] = opt["default"]
    args.update(kw)
    out = getattr(c(), c.FUNCTION)(**args)
    return (out["result"] if isinstance(out, dict) else out)[0]


sph = nrun("UVProject", geo=build.sphere(radius=0.8, cols=32, rows=16), mode="box", fit_to_01=False)
ca = nrun("COPConstant", resolution_x=8, resolution_y=8, layer="base", device="numpy")
wa = nrun("COPWrangle", cop=ca, code="@basecolor = set(0.9, 0.9, 0.9)\n@ao = 1\n@roughness = 0.05\n@metallic = 1")
mirror = node.run(sph, 96, 96, 20, 30, "color", look="outdoor", supersampling=1, textures="basecolor = @basecolor\n"
                  "orm = @ao roughness metallic", textures_cop=wa, ground_plane=False, haze=0)
mirror = (mirror["result"] if isinstance(mirror, dict) else mirror)[0].numpy()[0]
diffuse = node.run(sph, 96, 96, 20, 30, "color", look="outdoor", supersampling=1, ground_plane=False, haze=0)
diffuse = (diffuse["result"] if isinstance(diffuse, dict) else diffuse)[0].numpy()[0]
# a polished metal sphere reflects the sky: its upper half is bluer than the plain grey sphere's
cm = mirror[30:45, 40:56].mean((0, 1))
cd = diffuse[30:45, 40:56].mean((0, 1))
check("PBR from textures_cop: a polished metal sphere reflects the blue sky (bluer than the plain sphere)",
      (cm[2] - cm[0]) > (cd[2] - cd[0]) + 0.03, (np.round(cm, 3), np.round(cd, 3)))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
