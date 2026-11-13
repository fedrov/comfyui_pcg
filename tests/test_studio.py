"""
pcg110: Preview Image (PCG) "studio" look (geo/studio.py) and the bitangent layer of COP Bake Textures.

  1. Basic look is unchanged (bit-identical to convert.render_preview); output size; supersampling
  2. background gradient; framing fills a wide image with a wide subject
  3. shadows: a block over the ground darkens the ground on the side away from the light (negative control: off)
  4. ambient occlusion darkens an inside corner (negative control: off)
  5. textures: basecolor by {material} from files (sRGB decoded), a missing file keeps Cd and is reported,
     '@layer' from a connected COP; mipmapping (a fine checker far away averages instead of sparkling);
     a flat normal map changes nothing, a tilted one changes the shading
  7. PBR (pcg116): orm / roughness / metallic switch to metal-rough shading -- the environment BRDF fit, polished
     vs rough highlights, metals tint their reflection, Fresnel brightens the rim, orm = separate slots,
     ao alone does not switch (and ao = 1 changes nothing)
  6. bake: bitangent = handedness * (N x T), and T / B / N reconstruct the high-poly normal from normal_ts
"""
import os
import sys
import tempfile

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (os.path.dirname(_R), os.path.dirname(os.path.dirname(_R))):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy  # noqa: F401,E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP  # noqa: E402
from comfyui_pcg.geo import build, convert, ops, studio as S  # noqa: E402
from comfyui_pcg.geo.core import POINT, PRIM, VERTEX  # noqa: E402
from comfyui_pcg.geo.cop import geoimg  # noqa: E402
from comfyui_pcg.geo.cop.core import CopImage  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if isinstance(extra, str) and extra == "" else "   " + str(extra)[:300]))


def sec(t):
    print(f"\n── {t}")


def lum(img):
    return img[..., :3].mean(-1)


box = ops.compute_normals(build.box(size=(1, 1, 1)), add_to="point")

sec("1. Basic unchanged, size, supersampling")
node = MAP["PCG_PreviewImage"]()
old = convert.render_preview(box, 96, 64, 25.0, 35.0, "lambert", "Cd")
new = node.run(box, 96, 64, 25.0, 35.0, "lambert")[0]
new = new.numpy()[0] if hasattr(new, "numpy") else np.asarray(new)[0]
check("Basic look (the default) is bit-identical to the old preview", np.array_equal(old, new))
st = S.render_studio(box, 96, 64, 25.0, 35.0, ssaa=2)
st1 = S.render_studio(box, 96, 64, 25.0, 35.0, ssaa=1)
check("studio: output is width x height, float 0..1, for any supersampling",
      st.shape == (64, 96, 3) and st1.shape == (64, 96, 3) and st.dtype == np.float32
      and 0 <= st.min() and st.max() <= 1)
ref = S.render_studio(box, 96, 64, 25.0, 35.0, ssaa=4)
err = float(np.abs(st - ref).mean()), float(np.abs(st1 - ref).mean())
check("  supersampling converges: 2x is closer than 1x to a 4x reference", err[0] < err[1] * 0.8,
      [round(e, 4) for e in err])

sec("2. Background, framing")
emp = S.render_studio(None, 40, 40)
check("empty geometry: a vertical gradient, lighter at the top", lum(emp)[0].mean() > lum(emp)[-1].mean() + 0.05)
row = ops.merge(*[ops.compute_normals(build.box(size=(1, 1, 1), center=(2.0 * i, 0, 0)), add_to="point")
                  for i in range(5)])
wide = S.render_studio(row, 400, 100, 15.0, 0.0, ssaa=1, ground=False, shadows=False, ao=False)
bg = S.render_studio(None, 400, 100, ssaa=1)
cols = np.nonzero((np.abs(wide - bg).sum(-1) > 0.02).any(0))[0]
span = (cols.max() - cols.min()) / 400.0 if len(cols) else 0
check("a row of objects fills a wide image (framed on the projected extent, not the bounding sphere)",
      span > 0.75, round(span, 2))
basic = convert.render_preview(row, 400, 100, 15.0, 0.0, "lambert")
bcols = np.nonzero((basic.sum(-1) > 0.01).any(0))[0]
check("  negative control: the basic preview (bounding sphere) leaves it narrow",
      (bcols.max() - bcols.min()) / 400.0 < 0.5, round((bcols.max() - bcols.min()) / 400.0, 2))

sec("3. Shadows")
block = ops.compute_normals(build.box(size=(1, 1, 1), center=(0, 1.0, 0)), add_to="point")
floor = ops.compute_normals(build.grid(size_x=8, size_z=8, cols=2, rows=2, center=(0, 0, 0)), add_to="point")
scene = ops.merge(block, floor)
# key light comes from azimuth + 50 deg, elevation 55: the shadow falls on the opposite side
az = 0.0
on = S.render_studio(scene, 200, 200, 60.0, az, ssaa=1, ao=False, ground=False)
off = S.render_studio(scene, 200, 200, 60.0, az, ssaa=1, ao=False, ground=False, shadows=False)
diff = lum(off) - lum(on)
check("the block casts a shadow: a region of the floor is clearly darker with shadows on",
      (diff > 0.08).sum() > 200, int((diff > 0.08).sum()))
check("  shadows off: nothing differs beyond rounding when rendered twice the same way",
      np.abs(lum(off) - lum(S.render_studio(scene, 200, 200, 60.0, az, ssaa=1, ao=False, ground=False,
                                            shadows=False))).max() < 1e-6)
check("  no self-shadow acne: the block's lit top is not darkened by its own shadow",
      np.percentile(diff[diff > -1], 50) < 0.01)

sec("4. Ambient occlusion")
# an inside corner: floor + two walls
w1 = ops.compute_normals(build.grid(size_x=4, size_z=4, cols=2, rows=2, center=(0, 2, -2), rotate=(90, 0, 0)),
                         add_to="point")
w2 = ops.compute_normals(build.grid(size_x=4, size_z=4, cols=2, rows=2, center=(-2, 2, 0), rotate=(0, 0, 90)),
                         add_to="point")
fl = ops.compute_normals(build.grid(size_x=4, size_z=4, cols=2, rows=2, center=(0, 0, 0)), add_to="point")
corner = ops.merge(w1, w2, fl)
a_on = S.render_studio(corner, 160, 160, 35.0, 45.0, ssaa=1, shadows=False, ground=False)
a_off = S.render_studio(corner, 160, 160, 35.0, 45.0, ssaa=1, shadows=False, ground=False, ao=False)
d = lum(a_off) - lum(a_on)
check("AO darkens the surfaces near the inside corner", d.max() > 0.05 and (d > 0.03).sum() > 50,
      (round(float(d.max()), 3), int((d > 0.03).sum())))
check("  and leaves open areas alone (median change ~0)", abs(float(np.median(d))) < 0.01)

sec("5. Textures")
tmp = tempfile.mkdtemp()
quad = build.grid(size_x=2, size_z=2, cols=2, rows=2)
quad = ops.compute_normals(quad, add_to="point")
P = np.asarray(quad.get(POINT, "P"))
quad.set(POINT, "uv", np.c_[(P[:, 0] + 1) / 2, (P[:, 2] + 1) / 2].astype(np.float32))
quad.set(PRIM, "material", np.array([["M_Red"]] * quad.nprims))
quad.set(POINT, "Cd", np.tile([[0.0, 0.0, 1.0]], (quad.npoints, 1)).astype(np.float32))
os.makedirs(os.path.join(tmp, "tex"), exist_ok=True)
Image.fromarray(np.tile(np.array([200, 30, 30], np.uint8), (8, 8, 1))).save(os.path.join(tmp, "tex", "T_M_Red_BC.png"))
kw = dict(ssaa=1, shadows=False, ao=False, ground=False)
rep = {}
tx = S.render_studio(quad, 64, 64, 89.0, 0.0, textures="basecolor = tex/T_{material}_BC.png", tex_root=tmp,
                     report=rep, **kw)
c = tx[32, 32]
check("basecolor from a file, path built from the face material ({material})", c[0] > 2 * c[1] and c[0] > 2 * c[2],
      c.round(2))
check("  report lists the file used", rep.get("used") == ["tex/T_M_Red_BC.png"] and not rep.get("missing"), rep)
rep2 = {}
tm = S.render_studio(quad, 64, 64, 89.0, 0.0, textures="basecolor = tex/missing_{material}.png", tex_root=tmp,
                     report=rep2, **kw)
check("a missing file keeps Cd (blue) and is reported", tm[32, 32, 2] > tm[32, 32, 0] + 0.1
      and rep2.get("missing") == ["tex/missing_M_Red.png"], rep2)
cop = CopImage(4, 4)
cop.set("bc", np.tile([0.0, 0.5, 0.0], (4, 4, 1)))
tc = S.render_studio(quad, 64, 64, 89.0, 0.0, textures="basecolor = @bc", tex_cop=cop, **kw)
check("'@layer' reads the connected COP image (green)", tc[32, 32, 1] > 2 * max(tc[32, 32, 0], tc[32, 32, 2]))
try:
    S.render_studio(quad, 32, 32, textures="basecolor = @bc", **kw)
    raised = False
except ValueError:
    raised = True
check("  '@layer' without a COP connected is an error", raised)
# mip: a 1-px checker of 512 px over a 64 px view -> averages to grey with mips; without, it aliases
chk = ((np.indices((512, 512)).sum(0) % 2) * 255).astype(np.uint8)
Image.fromarray(np.repeat(chk[..., None], 3, -1)).save(os.path.join(tmp, "tex", "T_M_Red_CHK.png"))
mt = S.render_studio(quad, 64, 64, 89.0, 0.0, textures="basecolor = tex/T_{material}_CHK.png", tex_root=tmp, **kw)
inner = lum(mt)[16:48, 16:48]
check("mipmapping: a fine checker seen from afar is an even grey, not noise", inner.std() < 0.03,
      round(float(inner.std()), 4))
ch0 = [S.load_texture(os.path.join("tex", "T_M_Red_CHK.png"), tmp)]
uvs = np.random.default_rng(0).random((4096, 2))
check("  negative control: sampling level 0 only at that footprint is noisy",
      S.sample_mip(ch0, uvs, np.full(4096, 8.0)).std() > 0.1)
flat = np.zeros((8, 8, 3), np.uint8) + np.array([128, 128, 255], np.uint8)
Image.fromarray(flat).save(os.path.join(tmp, "tex", "T_M_Red_NF.png"))
tilt = np.zeros((8, 8, 3), np.uint8) + np.array([25, 128, 200], np.uint8)   # leans away from the light
Image.fromarray(tilt).save(os.path.join(tmp, "tex", "T_M_Red_NT.png"))
lit = dict(ssaa=1, shadows=False, ao=False, ground=False)
b0 = S.render_studio(quad, 48, 48, 50.0, 30.0, **lit)
bf = S.render_studio(quad, 48, 48, 50.0, 30.0, textures="normal = tex/T_{material}_NF.png", tex_root=tmp, **lit)
bt = S.render_studio(quad, 48, 48, 50.0, 30.0, textures="normal = tex/T_{material}_NT.png", tex_root=tmp, **lit)
check("a flat normal map (128,128,255) changes nothing", np.abs(b0 - bf).max() < 0.01, float(np.abs(b0 - bf).max()))
check("  a normal map leaning away from the light darkens the surface (blue Cd: blue channel)",
      b0[24, 24, 2] - bt[24, 24, 2] > 0.15, (round(float(b0[24, 24, 2]), 3), round(float(bt[24, 24, 2]), 3)))
try:
    S.parse_textures("emissive = x.png")
    bad = False
except ValueError:
    bad = True
check("unknown texture slots are rejected", bad)

sec("7. PBR")
f0 = np.array([[0.04, 0.04, 0.04]])
eb = lambda r, nv: S.env_brdf(f0, np.array([r]), np.array([nv]))[0, 0]
check(f"env BRDF: polished, head-on = F0 ({eb(0.03, 1.0):.3f}); grazing -> ~1 ({eb(0.03, 0.02):.2f}); rough damps "
      f"the grazing rise ({eb(1.0, 0.02):.2f})", abs(eb(0.03, 1.0) - 0.04) < 0.01 and eb(0.03, 0.02) > 0.75
      and eb(1.0, 0.02) < 0.3)
sph = ops.compute_normals(build.sphere(radius=1.0, cols=64, rows=48), add_to="point")
Ps = np.asarray(sph.get(POINT, "P"))
sph.set(POINT, "uv", np.c_[Ps[:, 0] * 0.5 + 0.5, Ps[:, 1] * 0.5 + 0.5].astype(np.float32))
pc = CopImage(4, 4)
for nm, v in (("bc", [0.02, 0.02, 0.025]), ("red", [0.8, 0.05, 0.05]), ("one", [1.0] * 3), ("zero", [0.0] * 3),
              ("smooth", [0.04] * 3), ("rough", [0.7] * 3)):
    pc.set(nm, np.tile(v, (4, 4, 1)))
pk = dict(ssaa=1, shadows=False, ao=False, ground=False, tex_cop=pc)
R_ = lambda t: S.render_studio(sph, 96, 96, 20.0, 30.0, textures=t, **pk)
plain = R_("basecolor = @bc")
same = R_("basecolor = @bc\nao = @one")
check("ao alone does not switch to PBR, and ao = 1 changes nothing", np.array_equal(plain, same))
pol = R_("basecolor = @bc\nroughness = @smooth\nmetallic = @zero")
rgh = R_("basecolor = @bc\nroughness = @rough\nmetallic = @zero")
check(f"dark polished dielectric (glass): a bright softbox highlight ({lum(pol).max():.2f}) the plain look lacks "
      f"({lum(plain).max():.2f}) and a rough one spreads ({lum(rgh).max():.2f})",
      lum(pol).max() > lum(plain).max() + 0.2 and lum(pol).max() > lum(rgh).max() + 0.2)
yy, xx = np.mgrid[0:96, 0:96]
wht = R_("basecolor = @one")
msk = np.abs(wht - wht[:, :1]).max(-1) > 0.02        # the sphere: the background is a vertical gradient only
cy, cx = yy[msk].mean(), xx[msk].mean()
rr = np.hypot(yy - cy, xx - cx)
rad = rr[msk].max()
# upper half (row 0 is the top): rim and centre both reflect the upper studio, the rim at grazing angles
up = yy < cy
rim = msk & (rr > 0.85 * rad) & up
mid = msk & (rr < 0.35 * rad) & up
check(f"  Fresnel: the rim ({lum(pol)[rim].mean():.3f}) is brighter than the centre ({lum(pol)[mid].mean():.3f})",
      lum(pol)[rim].mean() > lum(pol)[mid].mean() + 0.02)
check("  negative control: the plain look has no such rim", lum(plain)[rim].mean() < lum(plain)[mid].mean() + 0.02)
met = R_("basecolor = @red\nroughness = @smooth\nmetallic = @one")
die = R_("basecolor = @zero\nroughness = @smooth\nmetallic = @zero")      # black dielectric: reflections only
# pixels the tone curve has not clipped to white
gr = lambda im: float(np.median(im[msk & (im.max(-1) < 0.9)][:, 1] / np.maximum(im[msk & (im.max(-1) < 0.9)][:, 0], 1e-6)))
check(f"a red metal reflects in red (G/R over the sphere {gr(met):.2f}); a dielectric reflects white "
      f"(black one, reflections only: G/R {gr(die):.2f})", gr(met) < 0.5 and gr(die) > 0.9)
# key-light Fresnel: light from behind the surface's horizon, viewer opposite -- half vector 80° from both, so
# Schlick gives F = 0.04 + 0.96 (1 - cos 80°)^5 ~ 0.43, ten times F0
th = np.radians(80)
Vv = np.array([np.sin(th), np.cos(th), 0.0])
Lv = np.array([-np.sin(th), np.cos(th), 0.0])
nn = np.array([[0.0, 1.0, 0.0]])
rg = np.array([0.3])
keyc = np.array([1.0, 1.0, 1.0])
nl = float(nn[0] @ Lv)
o = S._shade_pbr(np.zeros((1, 3)), nn, Vv, Lv, keyc, np.array([nl]), np.zeros((1, 3)), np.ones(1), rg, np.zeros(1))
envp = S.env_brdf(np.full((1, 3), 0.04), rg, np.array([float(nn[0] @ Vv)])) * S.env_radiance(
    (2 * float(nn[0] @ Vv) * nn - Vv[None]) / np.linalg.norm(2 * float(nn[0] @ Vv) * nn - Vv[None]), rg, Lv, Vv)
a2 = 0.3 ** 4
nv_ = float(nn[0] @ Vv)
D = 1 / (np.pi * a2)                                  # GGX at n·h = 1
vis = 0.5 / (nl * np.sqrt(nv_ ** 2 * (1 - a2) + a2) + nv_ * np.sqrt(nl ** 2 * (1 - a2) + a2))
Fk = float((o - envp)[0, 0] / (D * vis * nl * np.pi))
check(f"key light: Schlick Fresnel at a grazing half angle, F = {Fk:.3f} (expected "
      f"{0.04 + 0.96 * (1 - np.cos(th)) ** 5:.3f})", abs(Fk - (0.04 + 0.96 * (1 - np.cos(th)) ** 5)) < 1e-6)
orm = R_("basecolor = @red\norm = @one smooth one")
sep = R_("basecolor = @red\nao = @one\nroughness = @smooth\nmetallic = @one")
check("orm = '@ao roughness metallic' equals the three separate slots", np.abs(orm - sep).max() < 1e-6)

sec("8. Memory (pcg118)")
import subprocess  # noqa: E402
_probe = ("import sys, resource; sys.path[:0] = %r\nimport fakecomfy\n"
          "from comfyui_pcg.geo import build, ops, studio\n"
          "g = ops.compute_normals(build.grid(size_x=10, size_z=10, cols=300, rows=300), add_to='point')\n"
          "studio.render_studio(g, 1600, 1066, ssaa=2)\n"
          "print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024)"
          % [os.path.dirname(os.path.dirname(_R)), os.path.dirname(_R), _R])
_o = subprocess.run([sys.executable, "-c", _probe], capture_output=True, text=True)
_mb = int(_o.stdout.strip().splitlines()[-1]) if _o.returncode == 0 and _o.stdout.strip() else -1
check(f"a supersampled 1600 x 1066 studio render peaks at {_mb} MB (float32 buffers in place, chunked shadow and "
      "ground passes; it was 2.8 GB)", 0 < _mb < 1800, _o.stderr[-200:])

sec("6. Bake: bitangent")
low = ops.compute_normals(build.sphere(radius=1.0, cols=24, rows=16), add_to="point")
Pl = np.asarray(low.get(POINT, "P"), np.float64)
uvp = np.c_[np.arctan2(Pl[:, 2], Pl[:, 0]) / (2 * np.pi) + 0.5, Pl[:, 1] * 0.5 + 0.5]
low.set(VERTEX, "uv", uvp[low.vertex_point].astype(np.float32))
# the high poly is an off-centre, slightly bigger sphere: its normals differ from the low poly's in every direction
high = ops.compute_normals(build.sphere(radius=1.1, cols=64, rows=48, center=(0.12, 0.09, -0.07)), add_to="point")
img, _ = geoimg.bake_textures(low, high, 128, 128, "uv", max_distance=0.5, world_normal=True)
m = img.get("mask")[..., 0] > 0.5
N, T, B, HN = (np.asarray(img.get(k))[m] for k in ("N", "tangent", "bitangent", "worldnormal"))
ts = np.asarray(img.get("normal_ts"))[m]
check("bitangent is unit length and perpendicular to N and T",
      np.allclose(np.linalg.norm(B, axis=1), 1, atol=1e-3) and np.abs((B * N).sum(1)).max() < 1e-3
      and np.abs((B * T).sum(1)).max() < 1e-3)


def agree(Bv):
    rec = T * ts[:, 0:1] + Bv * ts[:, 1:2] + N * ts[:, 2:3]
    return float(np.percentile((rec * HN).sum(1) / np.linalg.norm(rec, axis=1), 5))     # the worst 5 %


check("  T, bitangent, N reconstruct the high-poly normal from normal_ts", agree(B) > 0.998, round(agree(B), 5))
check("  negative control: with the bitangent flipped they do not", agree(-B) < agree(B) - 0.005, round(agree(-B), 5))

sec("7. Normal maps on one material: frames of that material's triangles only")
from comfyui_pcg.geo import outdoor as _O, render as _R  # noqa: E402
from comfyui_pcg.geo.cop import heightmap as _hm, terrain as _ter  # noqa: E402
from comfyui_pcg.geo.meshexport import corner_frames, corner_frames_subset  # noqa: E402
from comfyui_pcg.geo.spatial import tri_soup  # noqa: E402
sph = ops.compute_normals(build.sphere(radius=1.0, cols=24, rows=16), add_to="point")
Ps = np.asarray(sph.get(POINT, "P"), np.float64)
sph.set(VERTEX, "uv", (np.c_[np.arctan2(Ps[:, 2], Ps[:, 0]) / (2 * np.pi) + 0.5,
                             Ps[:, 1] * 0.5 + 0.5][sph.vertex_point]).astype(np.float32))
tri_, _, cor_ = tri_soup(sph)
Nf, Tf = corner_frames(sph, "uv", tri_, cor_)
vids, Ns, Ts = corner_frames_subset(sph, "uv", tri_, cor_, np.ones(len(tri_), bool))
check("all triangles: the subset frames are the whole mesh's, corner for corner (float32 for the screen: to 2e-6)",
      len(vids) == sph.nvertices and np.allclose(Ns, Nf[vids], atol=2e-6) and np.allclose(Ts, Tf[vids], atol=2e-6))
two = ops.merge(sph, ops.transform(sph, translate=(5, 0, 0)))
tri2, src2, cor2 = tri_soup(two)
vids2, N2, T2 = corner_frames_subset(two, "uv", tri2, cor2, src2 < sph.nprims)
check("  one of two separate parts: that part's own frames, and only its corners",
      np.array_equal(vids2, np.arange(sph.nvertices)) and np.allclose(T2, Tf, atol=2e-6) and np.allclose(N2, Nf, atol=2e-6))


def ramp_normal(a, b, textured=True):
    """Shaded normal at the frame centre: a flat 100 m Heightfield to Mesh with the normal map of h = a*u + b*v."""
    W = 64
    J, I = np.meshgrid((np.arange(W) + 0.5) / W, (np.arange(W) + 0.5) / W)
    img = CopImage()
    img.set("C", np.zeros((W, W, 1), np.float32))
    img.set("h", (a * J + b * I)[..., None].astype(np.float32))
    img = _hm.height_to_normal(img, "h", 1.0, 100.0, out_layer="ground_nrm")
    mesh = _ter.to_mesh(img, "C", 1.0, 100.0)
    mesh.set_string(PRIM, "material", ["ground"] * mesh.nprims)
    got = {}
    orig = S._apply_textures

    def spy(geo, rast, alb, N, *a_, **k_):
        orig(geo, rast, alb, N, *a_, **k_)
        got["N"] = N[N.shape[0] // 2, N.shape[1] // 2].copy()
    S._apply_textures = spy
    try:
        _O.render_outdoor(mesh, 48, 48, cam=_R.camera(None, "perspective", eye=[0, 150, 0.01], target=[0, 0, 0],
                                                      fov=20), ssaa=1, haze=0.0, clouds=0.0,
                          textures="normal = @{material}_nrm" if textured else "basecolor = @{material}_none",
                          tex_cop=img)
    finally:
        S._apply_textures = orig
    return got["N"]


for a, b in ((30.0, 0.0), (0.0, 30.0), (-20.0, 10.0)):
    want = np.array([-a, 100.0, b]) / np.linalg.norm([-a, 100.0, b])     # h rises along +u = +X and +v = -Z
    n = ramp_normal(a, b)
    check(f"  terrain normal map of the ramp h = {a:g} u + {b:g} v (100 m): the analytic normal {np.round(want, 3)}",
          np.allclose(n, want, atol=2e-3), np.round(n, 4))
n0 = ramp_normal(30.0, 0.0, textured=False)
check("  negative control: without the normal map the flat mesh's (0, 1, 0)", np.allclose(n0, [0, 1, 0], atol=1e-4),
      np.round(n0, 4))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
