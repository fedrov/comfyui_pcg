"""
pcg123: the Outdoor look of Geometry Preview (geo/outdoor.py), checked against geometry rather than by eye.

  1. Sky: bluer at the zenith than at the horizon; the brightest pixel is where the sun is when the camera looks at it
  2. Camera: the covered pixels of a box equal its analytic projection through the Camera node (IoU > 0.97);
     negative control: the projection through a shifted camera does not match
  3. Sun shadow: on the ground plane the shadow lies on the side away from the sun (sun in +X -> darker at -X), and
     moves with Sun Azimuth; with the ground plane off the ground pixels are sky
  4. Aerial perspective: a far ground pixel moves toward the horizon colour as Haze grows; Haze 0 leaves it alone;
     Haze is in metres (a 60 km quad out of view does not change it)
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

# Haze is in metres: a wall 6 km away hazes the same whether or not the scene also holds a quad 60 km wide out of
# view (a sea to the horizon used to stretch the haze over the bounding box: 600 km)
from comfyui_pcg.geo import ops as _ops  # noqa: E402
wall = _ops.transform(build.box(), scale=(3000.0, 1500.0, 10.0), translate=(0.0, 750.0, -6000.0))
sea = _ops.transform(build.box(), scale=(60000.0, 1.0, 60000.0), translate=(0.0, -5.0, 40000.0))
fcam = R.camera(None, "perspective", eye=(0, 300, 0), target=(0, 700, -6000), fov=20)
wpix = {}
for name, gg, hz in (("wall", wall, 1.0), ("wall+sea", _ops.merge(wall, sea), 1.0), ("wall, haze 0", wall, 0.0)):
    wpix[name] = O.render_outdoor(gg, 32, 32, cam=fcam, ssaa=1, ground=False, haze=hz, sky_samples=0)[16, 16]
check("Haze in metres: a wall 6 km away hazes the same with a 60 km quad in the scene (out of view)",
      np.abs(wpix["wall"] - wpix["wall+sea"]).max() < 0.02, (wpix["wall"].round(3), wpix["wall+sea"].round(3)))
check("  negative control: with Haze 0 that wall is clearly different (the haze is really there)",
      np.abs(wpix["wall"] - wpix["wall, haze 0"]).max() > 0.05, wpix["wall, haze 0"].round(3))

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


# a face seen from behind (and from a little above) turns its normal to the viewer -- unless an authored N already
# faces the viewer (grass blades carry the ground's up as N and must shade like the ground from both sides)
def back_normal(n_attr):
    tri = Geometry.from_mesh(np.array([[-1, 0, 0], [1, 0, 0], [0, 2, 0]], np.float32), [[0, 1, 2]])
    tri.set(POINT, "uv", np.array([[0, 0], [1, 0], [0.5, 1]], np.float32))
    if n_attr is not None:
        tri.set(POINT, "N", np.tile(np.asarray(n_attr, np.float32), (3, 1)))
    fz = float((O.np.cross(np.array([2.0, 0, 0]), np.array([1.0, 2, 0])))[2])     # the face normal's z
    eye_z = -6.0 * np.sign(fz)                                                       # behind the face
    got = {}
    orig = S._apply_textures

    def spy(geo, rast, alb, N, *a_, **k_):
        got["N"] = N.copy()
    S._apply_textures = spy
    try:
        img = nrun("COPConstant", resolution_x=4, resolution_y=4, layer="base", device="numpy")
        O.render_outdoor(tri, 64, 64, cam=R.camera(None, "perspective", eye=[0, 1.6, eye_z], target=[0, 0.8, 0],
                                                   fov=40), ssaa=1, haze=0.0, clouds=0.0, sky_samples=0,
                         ground=False, textures="basecolor = @base", tex_cop=img)
    finally:
        S._apply_textures = orig
    return got["N"][32, 32], np.sign(fz)


n_up, _ = back_normal([0, 1, 0])
n_none, fs = back_normal(None)
n_away, _ = back_normal([0, 0, fs])
check("seen from behind: an authored N that faces the viewer (the ground's up) is kept",
      np.allclose(n_up, [0, 1, 0], atol=1e-3), np.round(n_up, 3))
check("  without N the face normal turns to the viewer, and an authored N facing away is flipped (as before)",
      np.allclose(n_none, [0, 0, -fs], atol=1e-3) and np.allclose(n_away, [0, 0, -fs], atol=1e-3),
      (np.round(n_none, 3), np.round(n_away, 3)))

print("\n[7. Guide passes: depth and normal]")
# a 200 m ground grid and a 4 m box on it, seen from 6 m up, pitched down 20 degrees
gnd = build.grid(size_x=400.0, size_z=400.0, cols=8, rows=8)
gb = build.box(size=(4.0, 4.0, 4.0), center=(0.0, 2.0, -20.0))
from comfyui_pcg.geo.ops import merge as _mg  # noqa: E402
scene = _mg(gnd, gb)
pitch = np.radians(20.0)
eye_ = np.array([0.0, 6.0, 0.0])
tgt_ = eye_ + np.array([0.0, -np.sin(pitch), -np.cos(pitch)]) * 10
camg = R.camera(None, "perspective", eye=list(eye_), target=list(tgt_), fov=50)
aux = {}
img7 = O.render_outdoor(scene, 96, 72, cam=camg, ssaa=1, haze=0.0, clouds=0.0, sky_samples=0, ground=False, aux=aux)
dep, nrm = aux.get("depth"), aux.get("normal")
check("the passes come back at the image's size, row 0 on top as the image", dep is not None and nrm is not None
      and dep.shape == img7.shape == nrm.shape)
# the ground below the box (rows near the bottom) is nearer than the ground near the horizon: brighter
col = dep[:, 10, 0]
gr_rows = np.nonzero(col > 0)[0]
check("depth: inverse (near white): the ground at the bottom of the frame is brighter than near the horizon, "
      "and it falls monotonically up the frame", len(gr_rows) > 10 and col[gr_rows[-1]] > col[gr_rows[0]] + 0.3
      and np.all(np.diff(col[gr_rows]) >= -1e-3), np.round(col[gr_rows[[0, -1]]], 3))
check("  the sky is black (rows above the horizon)", dep[:5].max() == 0.0, float(dep[:5].max()))
# the ground's normal (world up) in camera space: right 0, up cos(pitch), toward the camera sin(pitch)
exp_ = np.array([0.5, 0.5 + 0.5 * np.cos(pitch), 0.5 + 0.5 * np.sin(pitch)])
gpx = nrm[-3, 5]
check("normal: the ground (world up) is (0.5, 0.5 + cos 20 / 2, 0.5 + sin 20 / 2) in camera space",
      np.allclose(gpx, exp_, atol=0.02), (np.round(gpx, 3), np.round(exp_, 3)))
# the box's face toward the camera (+z in world): pure 'toward the camera' tilted by the pitch
fy, fx = np.nonzero((np.abs(nrm[..., 1] - (0.5 - 0.5 * np.sin(pitch))) < 0.03)
                    & (np.abs(nrm[..., 2] - (0.5 + 0.5 * np.cos(pitch))) < 0.03))
check("  the box's front face reads (0.5, 0.5 - sin 20 / 2, 0.5 + cos 20 / 2); negative control: not the ground's",
      len(fy) > 20 and not np.allclose(exp_, [0.5, 0.5 - 0.5 * np.sin(pitch), 0.5 + 0.5 * np.cos(pitch)], atol=0.05),
      len(fy))
check("  the sky is flat, facing the camera (0.5, 0.5, 1)", np.allclose(nrm[1, 1], [0.5, 0.5, 1.0]))
aux2 = {}
img2 = O.render_outdoor(scene, 96, 72, cam=camg, ssaa=2, haze=0.0, clouds=0.0, sky_samples=0, ground=False, aux=aux2)
check("  supersampled (2x): the passes are block means at the image's size, close to the 1x ones away from edges",
      aux2["depth"].shape == img2.shape == aux2["normal"].shape and np.allclose(aux2["normal"][-3, 5], exp_, atol=0.02)
      and abs(float(np.median(aux2["depth"][-10:, :20])) - float(np.median(dep[-10:, :20]))) < 0.05)
rn = node.run(scene, 96, 72, 0, 0, "color", look="outdoor", supersampling=1, camera=camg, haze=0.0,
              ground_plane=False, sky_samples=0)
rn = rn["result"] if isinstance(rn, dict) else rn
rb = node.run(scene, 48, 36, 25, 35, "color", look="basic")
rb = rb["result"] if isinstance(rb, dict) else rb
check("the node: image, depth, normal; the outdoor passes equal render_outdoor's; other looks give a black depth "
      "and a flat normal", len(rn) == 3 and np.allclose(rn[1][0].numpy(), dep, atol=1e-6)
      and np.allclose(rn[2][0].numpy(), nrm, atol=1e-6) and float(rb[1].max()) == 0.0
      and np.allclose(rb[2][0, 0, 0].numpy(), [0.5, 0.5, 1.0]))

print("\n[8. Weather, emitted light, point lights, camera sequences]")
# a slope rising from 0 m at the near edge to 200 m at the far edge, a vertical wall on it
slope = build.grid(size_x=400.0, size_z=400.0, cols=41, rows=41)
Ps_ = np.asarray(slope.get(POINT, "P"), np.float64)
Ps_[:, 1] = (200.0 - Ps_[:, 2]) * 0.5                      # z = 200 -> 0 m, z = -200 -> 200 m
slope.set(POINT, "P", Ps_.astype(np.float32))
slope.set(POINT, "Cd", np.tile(np.array([[0.2, 0.35, 0.1]], np.float32), (slope.npoints, 1)))   # grass green
cams_ = R.camera(None, "perspective", eye=[0, 150, 380], target=[0, 80, 0], fov=50)
kw_ = dict(cam=cams_, ssaa=1, haze=0.0, clouds=0.0, sky_samples=0, ground=False)
base_ = O.render_outdoor(slope, 96, 72, **kw_)
snow_ = O.render_outdoor(slope, 96, 72, snow_line=100.0, snow_amount=1.0, **kw_)
d_ = snow_.mean(-1) - base_.mean(-1)
hi_r, lo_r = d_[18:30], d_[-12:]                            # the far, high part (above the sky rows), the near low part
check("snow: above the snow line (the far, high slope) much brighter; below it (near, low) unchanged",
      np.median(hi_r) > 0.15 and np.abs(np.median(lo_r)) < 0.01, (round(float(np.median(hi_r)), 3),
                                                                round(float(np.median(lo_r)), 3)))
flat = build.grid(size_x=400.0, size_z=400.0, cols=21, rows=21)
camf = R.camera(None, "perspective", eye=[0, 10, 60], target=[0, 0, 0], fov=50)
kf_ = dict(cam=camf, ssaa=1, haze=0.0, clouds=0.0, sky_samples=0, ground=False)
dry_ = O.render_outdoor(flat, 96, 72, sun_elev=35, sun_azim=180, **kf_)
wet_ = O.render_outdoor(flat, 96, 72, sun_elev=35, sun_azim=180, wetness=1.0, **kf_)
check("wetness: the flat ground darker (and glossier) than dry; the sky unchanged",
      wet_[-20:].mean() < dry_[-20:].mean() - 0.02 and np.allclose(wet_[:3], dry_[:3], atol=1e-4),
      (round(float(wet_[-20:].mean()), 3), round(float(dry_[-20:].mean()), 3)))
# the weather reads the mesh normal 3:1 over the normal-mapped one: ripples in a normal map do not stripe the snow
Pw = np.zeros((8, 8, 3), np.float32)
Pw[..., 1] = 300.0
Nw = np.zeros((8, 8, 3), np.float32)
Nw[..., 0], Nw[..., 1] = 0.866, 0.5                        # the mapped normal: a steep flank of a ripple
alb0 = np.full((8, 8, 3), 0.1, np.float32)
sw_ = {}
for k_, ng_ in (("geo", np.ones((8, 8), np.float32)), ("mapped", None)):
    a_, pb_ = alb0.copy(), {"roughness": np.full((8, 8), 0.8, np.float32)}
    O._weather(Pw, Nw, a_, pb_, np.ones((8, 8), bool), 100.0, 1.0, 0.0, None, ng_)
    sw_[k_] = float(a_.mean())
check("snow on a flat mesh whose normal map tilts (a ripple's flank): covered, as the mesh is flat (0.1 albedo -> "
      "near snow); negative control, the mapped normal alone: much less", sw_["geo"] > 0.6 and sw_["mapped"] < 0.4,
      (round(sw_["geo"], 3), round(sw_["mapped"], 3)))
# ... blurred to the scale of a slope: a fluted face (ny alternating every 4 px) reads as its mean; pixels outside the
# surface (ny -1 there: the sky) do not leak in
fl_ = np.where((np.arange(64) // 4) % 2 == 0, 1.0, 0.5).astype(np.float32)[None].repeat(48, 0)
mk_ = np.ones((48, 64), bool)
mk_[:, 48:] = False
fl_[:, 48:] = -1.0
bl_ = O._blur_masked(fl_, mk_, 6)
check("the weather's slope blur: a fluted face reads as its mean (0.75, spread < 0.05 against 0.5 unblurred); the sky "
      "beside it does not leak in", np.ptp(bl_[:, 10:40]) < 0.05 and abs(bl_[:, 10:40].mean() - 0.75) < 0.03
      and bl_[:, 40:48].min() > 0.6, (round(float(np.ptp(bl_[:, 10:40])), 3), round(float(bl_[:, 40:48].min()), 3)))
flw = flat.copy()
flw.set(POINT, "weather", np.zeros(flw.npoints, np.float32))
dw_ = O.render_outdoor(flw, 96, 72, sun_elev=35, sun_azim=180, wetness=1.0, **kf_)
check("weather_attrib: a surface with weather = 0 stays dry under wetness 1 (as the dry render, not the wet one)",
      abs(dw_[-20:].mean() - dry_[-20:].mean()) < 0.25 * abs(wet_[-20:].mean() - dry_[-20:].mean()),
      (round(float(dw_[-20:].mean()), 3), round(float(dry_[-20:].mean()), 3)))
dn_ = O.render_outdoor(flw, 96, 72, sun_elev=35, sun_azim=180, wetness=1.0, weather_attrib="", **kf_)
check("  with weather_attrib empty the attribute is not read: wet again", np.allclose(dn_, wet_, atol=1e-5))
# translucency_attrib: a thin card (a 4 m square in the x = 0 plane) whose authored normal is up, like a grass blade
def _card(cd=(0.2, 0.6, 0.1)):
    c_ = Geometry.from_mesh(np.array([[0, 0, -2], [0, 0, 2], [0, 4, 2], [0, 4, -2]], np.float32),
                            np.array([[0, 1, 2, 3]], np.int64))
    c_.set(POINT, "N", np.tile(np.array([[0.0, 1.0, 0.0]], np.float32), (4, 1)))
    c_.set(POINT, "Cd", np.tile(np.array([cd], np.float32), (4, 1)))
    return c_
# seen from below (the camera under the card, looking up at it, as up a slope): the up normal points away from the
# viewer; an opaque surface turns it to the viewer (down, into the dark), a translucent one keeps it
camu = R.camera(None, "perspective", eye=[12, -6, 0], target=[0, 2, 0], fov=30)
ku_ = dict(cam=camu, ssaa=1, haze=0.0, clouds=0.0, sky_samples=0, ground=False, sun_elev=40, sun_azim=90)
c0_ = _card()
c1_ = _card()
c1_.set(POINT, "translucency", np.full(4, 0.5, np.float32))
cz_ = _card()
cz_.set(POINT, "translucency", np.zeros(4, np.float32))
u0, u1, uz = (O.render_outdoor(g_, 64, 48, **ku_) for g_ in (c0_, c1_, cz_))
cm_ = (slice(18, 30), slice(26, 38))
check("translucency: a card with an up normal seen from below keeps it (lit like the ground, brighter than the "
      "opaque card, whose normal turns down)", u1[cm_].mean() > u0[cm_].mean() + 0.1,
      (round(float(u1[cm_].mean()), 3), round(float(u0[cm_].mean()), 3)))
check("  translucency 0 on every point = no attribute (bit for bit); translucency_attrib empty = not read",
      np.array_equal(uz, u0) and np.array_equal(O.render_outdoor(c1_, 64, 48, translucency_attrib="", **ku_), u0))
# the sun behind the card (camera on +x, the sun on -x, 60 degrees up), a card whose normal faces the camera: the
# sun is on its back, so no diffuse light and no sheen reach the front; what shows is what comes through
def _cardx(cd=(0.2, 0.6, 0.1), tr=None):
    c_ = _card(cd)
    c_.set(POINT, "N", np.tile(np.array([[1.0, 0.0, 0.0]], np.float32), (4, 1)))
    if tr is not None:
        c_.set(POINT, "translucency", np.full(4, tr, np.float32))
    return c_
camb2 = R.camera(None, "perspective", eye=[12, 2, 0], target=[0, 2, 0], fov=30)
kt_ = dict(cam=camb2, ssaa=1, haze=0.0, clouds=0.0, sky_samples=0, ground=False, sun_elev=60, sun_azim=270)
x0_, x1_ = _cardx(), _cardx(tr=0.5)
b0, b1 = (O.render_outdoor(g_, 64, 48, **kt_) for g_ in (x0_, x1_))
d_ = b1[cm_].mean((0, 1)) - b0[cm_].mean((0, 1))
check("translucency: backlit by the sun the card glows through (brighter than the opaque card), green (its colour) "
      "gaining most", d_[1] > 0.03 and d_[1] > d_[0] and d_[1] > d_[2], np.round(d_, 3))
f0, f1 = (O.render_outdoor(g_, 64, 48, **dict(kt_, sun_azim=90)) for g_ in (x0_, x1_))
_fd = (f1[cm_] - f0[cm_]).mean((0, 1))
check("  negative control: the same sun on the camera's side -- nothing green comes through (only the faint sheen, "
      "the sun's colour: red >= green, under a quarter of the glow)", _fd[1] <= _fd[0] + 1e-3
      and _fd.max() < 0.25 * d_[1], np.round(_fd, 3))
# ... and waxy: a sheen toward the sun, looking toward a low sun the translucent ground is brighter; with the sun
# behind the camera there is none (and nothing shines through ground lit from above): the same as the opaque ground
SUNZ_ = 0 if O.sun_dir(15, 0)[2] < 0 else 180
fl1_ = flat.copy()
fl1_.set(POINT, "translucency", np.full(fl1_.npoints, 0.5, np.float32))
kg_ = dict(kf_, sun_elev=15, sun_azim=SUNZ_)
gp0, gp1 = (O.render_outdoor(g_, 96, 72, **kg_) for g_ in (flat, fl1_))
_gd = (gp1 - gp0).mean(-1)
_gm = np.unravel_index(np.argmax(_gd), _gd.shape)
check("translucency: waxy -- looking toward a low sun the translucent ground has a sheen: brighter, in the sun's "
      "colour (not the ground's)", _gd.max() > 0.015 and (gp1 - gp0)[_gm][0] >= (gp1 - gp0)[_gm][1],
      (round(float(_gd.max()), 3), np.round((gp1 - gp0)[_gm], 3)))
gn0, gn1 = (O.render_outdoor(g_, 96, 72, **dict(kg_, sun_azim=SUNZ_ + 180)) for g_ in (flat, fl1_))
check("  negative control: the sun behind the camera -- no sheen, nothing through: as the opaque ground",
      np.abs(gn1 - gn0).max() < 2 / 255, float(np.abs(gn1 - gn0).max()))
bx_ = build.box(size=(4.0, 4.0, 4.0), center=(0.0, 2.0, 0.0))
bx2 = bx_.copy()
bx2.set(POINT, "emit", np.tile(np.array([[2.0, 1.5, 0.8]], np.float32), (bx2.npoints, 1)))
camb = R.camera(None, "perspective", eye=[0, 3, 14], target=[0, 2, 0], fov=40)
kb_ = dict(cam=camb, ssaa=1, haze=0.0, clouds=0.0, sky_samples=0, ground=False, sun_elev=-5.0)
e0, e1 = O.render_outdoor(bx_, 64, 48, **kb_), O.render_outdoor(bx2, 64, 48, **kb_)
check("emitted light: at dusk (sun 5 degrees below the horizon) a box with emit glows, warm; without it stays dark",
      e1[24, 32].mean() > e0[24, 32].mean() + 0.3 and e1[24, 32, 0] > e1[24, 32, 2], (np.round(e1[24, 32], 2),
                                                                                    np.round(e0[24, 32], 2)))
lt = Geometry.from_points(np.array([[0.0, 6.0, 0.0]], np.float32))
lt.set(POINT, "intensity", np.array([40.0], np.float32))
kl_ = dict(cam=camf, ssaa=1, haze=0.0, clouds=0.0, sky_samples=0, ground=False, sun_elev=-5.0)
l0 = O.render_outdoor(flat, 96, 72, **kl_)
l1 = O.render_outdoor(flat, 96, 72, lights=lt, light_range=30.0, **kl_)
dl_ = l1.mean(-1) - l0.mean(-1)
check("point lights: the ground round the lamp lit (warm), beyond its 30 m range untouched",
      dl_.max() > 0.2 and abs(float(dl_[32:40, :10].mean())) < 1e-3 and (l1 - l0)[dl_ > 0.1].mean(0)[0]
      > (l1 - l0)[dl_ > 0.1].mean(0)[2], (round(float(dl_.max()), 3), round(float(dl_[32:40, :10].mean()), 4)))
cp_ = nrun("CameraPath", frames=3, mode="orbit", resolution_x=48, resolution_y=36, elev=20.0, elev_end=20.0,
           azim=0.0, azim_end=90.0, loop=False)
cseq_ = cp_
rs_ = node.run(bx_, 48, 36, 0, 0, "color", look="outdoor", supersampling=1, cameras=cseq_, haze=0.0, sky_samples=0,
               ground_plane=False)
rs_ = rs_["result"] if isinstance(rs_, dict) else rs_
r0_ = node.run(bx_, 48, 36, 0, 0, "color", look="outdoor", supersampling=1, camera=cseq_[0], haze=0.0, sky_samples=0,
               ground_plane=False)
r0_ = r0_["result"] if isinstance(r0_, dict) else r0_
check("a camera sequence renders a batch of frames (images, depth, normal); frame 0 = the render with camera 0; "
      "the frames differ", tuple(rs_[0].shape) == (3, 36, 48, 3) and tuple(rs_[1].shape) == (3, 36, 48, 3)
      and np.allclose(rs_[0][0].numpy(), r0_[0][0].numpy(), atol=1e-5)
      and not np.allclose(rs_[0][0].numpy(), rs_[0][2].numpy(), atol=1e-2))

print("\n[9. The torch path (Compute auto with CUDA; torch_cpu runs the same code on the CPU)]")
try:
    import torch  # noqa: F401
    _have_torch = True
except Exception:
    _have_torch = False
if _have_torch:
    from comfyui_pcg.geo import studio as S9
    # rasterizing: a box over a plate with one cut-out face (alpha test on), the near plane clipping a face
    bx9 = build.box(size=(2.0, 2.0, 2.0), center=(0.0, 1.0, 0.0))
    pl9 = build.grid(size_x=8.0, size_z=8.0, cols=4, rows=4)
    sc9 = _ops.merge(bx9, pl9)
    cam9 = R.camera(None, "perspective", eye=[0.3, 1.2, 1.6], target=[0, 0.5, 0], fov=70, xres=96, yres=72)

    class _Cut:
        prims = np.zeros(sc9.nprims, bool)
        prims[2] = True

        def __call__(self, t, bb, rast):
            return bb[:, 0] < 0.5
    rn = R.rasterize(sc9, cam9, alpha=_Cut())
    rt = R.rasterize(sc9, cam9, alpha=_Cut(), device=torch.device("cpu"))
    same_hit = float((rn["hit"] == rt["hit"]).mean())
    m9 = rn["hit"] >= 0
    check("rasterize on torch = numpy: the same triangle per pixel, depth and barycentrics (alpha test and near-plane "
          "clipping included)", same_hit > 0.999 and np.allclose(rn["z"][m9], rt["z"][m9], atol=1e-9)
          and np.allclose(rn["bary"][m9], rt["bary"][m9], atol=1e-9), same_hit)
    # texture lookups: trilinear from a mip chain, float and 8-bit chains
    rng9 = np.random.default_rng(9)
    tex9 = rng9.random((64, 48, 3)).astype(np.float32)
    ch9 = S9.mip_chain(tex9)
    uv9 = rng9.random((20000, 2)).astype(np.float32) * 3 - 1
    fp9 = (2.0 ** (rng9.random(20000) * 7 - 1)).astype(np.float32)
    a9 = S9.sample_mip(ch9, uv9, fp9)
    S9.set_texture_device(torch.device("cpu"))
    try:
        b9 = S9.sample_mip(ch9, uv9, fp9)
        u8 = (rng9.random((32, 32, 4)) * 255).astype(np.uint8)
        c8 = [u8, u8[::2, ::2].copy()]
        t8 = S9.sample_mip(c8, uv9, fp9)
    finally:
        S9.set_texture_device(None)
    n8 = S9.sample_mip(c8, uv9, fp9)
    check("texture lookups on torch = numpy (trilinear over the mip levels, wrapping; an 8-bit chain read as its "
          "values)", np.allclose(a9, b9, atol=1e-5) and np.allclose(t8, n8, atol=1e-3),
          (float(np.abs(a9 - b9).max()), float(np.abs(t8 - n8).max())))
    # a whole textured, cut-out render: the leaf card over a plate, numpy and torch
    from comfyui_pcg.geo.cop.core import CopImage as _CI
    from comfyui_pcg.geo.cop.pixel import put as _put
    from comfyui_pcg.geo.cop.leafcard import leaf_card as _lc
    lc9, la9 = _lc("broadleaf", 64, 7, (0.1, 0.3, 0.05), seed=2)
    cop9 = _CI(64, 64)
    _put(cop9, "M_Leaf_C", lc9)
    _put(cop9, "M_Leaf_alpha", la9)
    cd9 = build.grid(size_x=2.0, size_z=2.0, cols=1, rows=1)
    P9 = np.asarray(cd9.get(POINT, "P"), np.float32)
    cd9.set(POINT, "P", np.c_[P9[:, 0], P9[:, 2] + 1.0, np.zeros(len(P9), np.float32)])
    cd9.set(POINT, "uv", np.c_[(P9[:, 0] + 1) / 2, (P9[:, 2] + 1) / 2, np.zeros(len(P9))].astype(np.float32))
    from comfyui_pcg.geo.core import PRIM as _PR
    cd9.set_string(_PR, "material", np.full(cd9.nprims, "M_Leaf"))
    cam9b = R.camera(None, "perspective", eye=[0.0, 1.0, 3.0], target=[0, 1.0, 0], fov=50)
    k9 = dict(cam=cam9b, ssaa=1, haze=0.0, clouds=0.0, sky_samples=4, ground=True, tex_cop=cop9,
              textures="basecolor = @{material}_C\nalpha = @{material}_alpha\nalpha_shadow = M_Leaf")
    i_np = O.render_outdoor(cd9, 64, 64, compute="cpu", **k9)
    i_t = O.render_outdoor(cd9, 64, 64, compute="torch_cpu", **k9)
    check("a textured, cut-out render on torch = numpy (within 1/255 on 99% of the pixels)",
          float((np.abs(i_np - i_t).max(-1) < 1 / 255).mean()) > 0.99, float(np.abs(i_np - i_t).max()))
else:
    print("  (torch not installed: skipped)")

print("\n[10. Shading rate and threads]")
from comfyui_pcg.geo import studio as S10
from comfyui_pcg.geo.cop.core import CopImage as _CI10
from comfyui_pcg.geo.cop.pixel import put as _put10
from comfyui_pcg.geo.core import PRIM as _PR10
# a ground plate textured with fine noise (material A) and a box (material B) on it, supersampled 2x
pl10 = build.grid(size_x=20.0, size_z=20.0, cols=8, rows=8)
P10 = np.asarray(pl10.get(POINT, "P"), np.float32)
pl10.set(POINT, "uv", np.c_[P10[:, 0] / 4, P10[:, 2] / 4, np.zeros(len(P10))].astype(np.float32))
pl10.set_string(_PR10, "material", np.full(pl10.nprims, "A"))
bx10 = build.box(size=(3.0, 3.0, 3.0), center=(0.0, 1.5, 0.0))
bx10.set(POINT, "uv", np.zeros((bx10.npoints, 3), np.float32))
bx10.set_string(_PR10, "material", np.full(bx10.nprims, "B"))
sc10 = _ops.merge(pl10, bx10)
c10 = _CI10(256, 256)
_put10(c10, "A_C", np.random.default_rng(10).random((256, 256, 3)).astype(np.float32))
_put10(c10, "B_C", np.full((256, 256, 3), 0.8, np.float32))
cam10 = R.camera(None, "perspective", eye=[6.0, 4.0, 9.0], target=[0, 0.5, 0], fov=45)
k10 = dict(cam=cam10, ssaa=2, haze=0.0, clouds=0.0, sky_samples=0, ground=False, tex_cop=c10,
           textures="basecolor = @{material}_C", compute="cpu")
reads = []
_orig_sm = S10.sample_mip
S10.sample_mip = lambda ch, uv, fp: (reads.append(len(uv)), _orig_sm(ch, uv, fp))[1]
_orig_at = S10._apply_textures
try:
    img_r = O.render_outdoor(sc10, 96, 72, **k10)
    n_rate = sum(reads)
    reads.clear()
    S10._apply_textures = lambda *a, **kw: _orig_at(*a, **{**kw, "rate": 1})
    img_1 = O.render_outdoor(sc10, 96, 72, **k10)
    n_one = sum(reads)
finally:
    S10.sample_mip = _orig_sm
    S10._apply_textures = _orig_at
dmean = float(np.abs(img_r - img_1).mean())
check("shading rate (supersampling 2): the textures read once per output pixel where one material covers it (under "
      "40% of the per-sample reads), the image within 1% of the per-sample one on average; the edges (plate / box) "
      "still read per sample", n_rate < 0.4 * n_one and n_rate > 0.25 * n_one and dmean < 0.01,
      (n_rate, n_one, round(dmean, 5)))
# texture lookups on threads: the same numbers as one thread
_env = os.environ.get("PCG_THREADS")
ch10 = S10.mip_chain(np.random.default_rng(11).random((128, 128, 3)).astype(np.float32))
uv10 = np.random.default_rng(12).random((1 << 21, 2)).astype(np.float32) * 4
fp10 = (2.0 ** (np.random.default_rng(13).random(1 << 21) * 6)).astype(np.float32)
os.environ["PCG_THREADS"] = "1"
s1 = S10.sample_mip(ch10, uv10, fp10)
os.environ["PCG_THREADS"] = "3"
s3 = S10.sample_mip(ch10, uv10, fp10)
if _env is None:
    del os.environ["PCG_THREADS"]
else:
    os.environ["PCG_THREADS"] = _env
check("texture lookups on 3 threads = on 1, bit for bit", np.array_equal(s1, s3))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
