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

sec("8. Detail maps: tiled colour and normal detail blended by a weights layer")


def detail_run(textures, extra_layers):
    W = 64
    img = CopImage()
    img.set("C", np.zeros((W, W, 1), np.float32))
    img.set("ground_albedo", np.full((W, W, 3), 0.5, np.float32))
    for k, v in extra_layers.items():
        img.set(k, v.astype(np.float32))
    mesh = _ter.to_mesh(img, "C", 1.0, 100.0)
    mesh.set_string(PRIM, "material", ["ground"] * mesh.nprims)
    got = {}
    orig = S._apply_textures

    def spy(geo, rast, alb, N, *a_, **k_):
        orig(geo, rast, alb, N, *a_, **k_)
        got["alb"], got["N"] = alb.copy(), N.copy()
    S._apply_textures = spy
    try:
        _O.render_outdoor(mesh, 96, 96, cam=_R.camera(None, "perspective", eye=[0, 150, 0.01], target=[0, 0, 0],
                                                      fov=20), ssaa=1, haze=0.0, clouds=0.0, sky_samples=0,
                          textures=textures, tex_cop=img)
    finally:
        S._apply_textures = orig
    return got


W_ = 64
Jd, Id = np.meshgrid(np.arange(W_), np.arange(W_))
checker = np.where(((Jd // 8) + (Id // 8)) % 2 == 0, 0.25, 0.75)[..., None].repeat(3, -1)    # 4 x 4 squares
wl = np.zeros((W_, W_, 4))
wl[:, : W_ // 2, 0] = 1.0                                   # detail 1 on the left half (-X) of the uv range
tilted = np.zeros((W_, W_, 3))
tilted[...] = (0.5 * 0.5 + 0.5, 0.5, 0.5 * 0.866 + 0.5)     # tangent normal (0.5, 0, 0.866): 30 degrees toward +u
base_tex = "basecolor = @{material}_albedo\n"
full = detail_run(base_tex + "detail1 = @{material}_d1\ndetail_normal1 = @{material}_n1\n"
                  "detail_weights = @{material}_dw\ndetail_tiling = 1",
                  {"ground_d1": checker, "ground_dw": wl, "ground_n1": tilted})
none = detail_run(base_tex, {})
H_ = full["alb"].shape[0]
row = full["alb"][H_ // 2]
lv = full["alb"][H_ // 2 - 20:H_ // 2 + 20, 18:38, 0]       # inside the left half of the quad on screen
rv = full["alb"][H_ // 2 - 20:H_ // 2 + 20, 58:78, 0]
check("colour detail x2 where the weight is 1: the 0.5 base becomes 0.25 and 0.75 (the checker), "
      "untouched where it is 0", np.allclose(sorted(set(np.round(lv.ravel(), 2)) - {0.5})[:1], [0.25], atol=0.02)
      and np.round(lv.max(), 2) == 0.75 and np.allclose(rv, 0.5, atol=1e-3),
      (round(float(lv.min()), 3), round(float(lv.max()), 3), round(float(rv.mean()), 3)))
nl = full["N"][H_ // 2, 28]
nr = full["N"][H_ // 2, 68]
check("  detail normal: 30 degrees toward +X under weight 1 ((0.5, 0.866, 0) in the world), flat (0, 1, 0) "
      "under weight 0", np.allclose(nl, [0.5, 0.866, 0.0], atol=0.01) and np.allclose(nr, [0, 1, 0], atol=1e-3),
      (np.round(nl, 3), np.round(nr, 3)))
check("  negative control: without detail slots the whole quad is the plain base (0.5) and flat",
      np.allclose(none["alb"][H_ // 2 - 20:H_ // 2 + 20, 18:78], 0.5, atol=1e-3)
      and np.allclose(none["N"][H_ // 2, 28], [0, 1, 0], atol=1e-3))
tiled = detail_run(base_tex + "detail1 = @{material}_d1\ndetail_weights = @{material}_dw\ndetail_tiling = 2",
                   {"ground_d1": checker, "ground_dw": wl})
t1 = np.diff(np.sign(full["alb"][H_ // 2, 10:46, 0] - 0.5)) != 0     # crossings of the base value: checker edges
t2 = np.diff(np.sign(tiled["alb"][H_ // 2, 10:46, 0] - 0.5)) != 0
check("  detail_tiling 2 repeats the detail twice as often (twice the checker edges across the same span)",
      t2.sum() >= 2 * t1.sum() - 1 and t1.sum() >= 1, (int(t1.sum()), int(t2.sum())))
try:
    S.parse_textures("detail_tiling = lots")
    bad = False
except ValueError:
    bad = True
check("  detail_tiling must be a number (a word is an error)", bad)

sec("9. Detail maps projected from the three axes (detail_triplanar)")


def ramp_run(textures, layers, slope=5.0):
    """A heightfield ramp rising along +x at the given slope (100 x 100 units, top-down uv), seen from the -x side."""
    W = 64
    img = CopImage()
    img.set("C", np.repeat((np.arange(W) / (W - 1) * slope)[None, :, None], W, 0).astype(np.float32))
    img.set("ground_albedo", np.full((W, W, 3), 0.5, np.float32))
    for k, v in layers.items():
        img.set(k, v.astype(np.float32))
    mesh = _ter.to_mesh(img, "C", 100.0, 100.0)
    mesh.set_string(PRIM, "material", ["ground"] * mesh.nprims)
    got = {}
    orig = S._apply_textures

    def spy(geo, rast, alb, N, *a_, **k_):
        orig(geo, rast, alb, N, *a_, **k_)
        got["alb"], got["N"] = alb.copy(), N.copy()
    S._apply_textures = spy
    try:
        _O.render_outdoor(mesh, 96, 96, cam=_R.camera(None, "perspective", eye=[-700, 250, 0.01],
                                                      target=[0, 250, 0], fov=40), ssaa=1, haze=0.0, clouds=0.0,
                          sky_samples=0, textures=textures, tex_cop=img)
    finally:
        S._apply_textures = orig
    return got


wall_all = np.zeros((W_, W_, 4))
wall_all[..., 0] = 1.0
dslots = "detail1 = @{material}_d1\ndetail_normal1 = @{material}_n1\ndetail_weights = @{material}_dw\n"
lay = {"ground_d1": checker, "ground_dw": wall_all, "ground_n1": tilted}
uvm = ramp_run(base_tex + dslots + "detail_tiling = 1", lay)
trm = ramp_run(base_tex + dslots + "detail_triplanar = 100", lay)
col_u = uvm["alb"][10:86, 48, 0]
col_t = trm["alb"][10:86, 48, 0]
e_u = int((np.diff(np.sign(col_u - 0.5)) != 0).sum())
e_t = int((np.diff(np.sign(col_t - 0.5)) != 0).sum())
check("on a 1:5 slope the top-down uv stretches a tile 5x up the slope; projected from the side it is one tile "
      "per 100 units of height (5x the checker edges up the screen)", e_u >= 1 and 3.5 <= e_t / max(e_u, 1) <= 6.5,
      (e_u, e_t))
n0 = np.array([-5.0, 1.0, 0.0]) / np.sqrt(26.0)
bw = np.abs(n0) ** 4 / (np.abs(n0) ** 4).sum()
pert = bw[0] * (0.5 / 0.866) * np.array([0.0, 0.0, 1.0])          # the x plane's u axis is +z
pert -= pert.dot(n0) * n0
want = (n0 + pert) / np.linalg.norm(n0 + pert)
nt = trm["N"][48, 48]
nu = uvm["N"][48, 48]
check("  detail normal on the slope: 30 degrees toward the x plane's u axis (+z), as the formula says",
      np.allclose(nt, want, atol=0.02), (np.round(nt, 3), np.round(want, 3)))
check("  negative control: with the uv the same map tilts it along the uv tangent (+x on the slope), not +z",
      abs(nu[2]) < 0.05 and not np.allclose(nu, want, atol=0.1), np.round(nu, 3))
flat_t = detail_run(base_tex + "detail1 = @{material}_d1\ndetail_normal1 = @{material}_n1\n"
                    "detail_weights = @{material}_dw\ndetail_triplanar = 100",
                    {"ground_d1": checker, "ground_dw": wl, "ground_n1": tilted})
check("  on flat ground the top plane is the terrain's uv (u east, v north): same colour and normal as uv mode",
      np.allclose(flat_t["alb"][H_ // 2 - 20:H_ // 2 + 20, 18:78], full["alb"][H_ // 2 - 20:H_ // 2 + 20, 18:78],
                  atol=0.03) and np.allclose(flat_t["N"][H_ // 2, 28], [0.5, 0.866, 0.0], atol=0.02),
      np.round(flat_t["N"][H_ // 2, 28], 3))
S._DETAIL_BLOCK = 97                                     # many blocks: the same pixels, in pieces
try:
    full_b = detail_run(base_tex + "detail1 = @{material}_d1\ndetail_normal1 = @{material}_n1\n"
                        "detail_weights = @{material}_dw\ndetail_tiling = 1",
                        {"ground_d1": checker, "ground_dw": wl, "ground_n1": tilted})
    trm_b = ramp_run(base_tex + dslots + "detail_triplanar = 100", lay)
finally:
    S._DETAIL_BLOCK = 1 << 20
check("  detail mapped in blocks of 97 pixels: the same colour and normals as in one block (uv and triplanar)",
      np.allclose(full_b["alb"], full["alb"], atol=1e-6) and np.allclose(full_b["N"], full["N"], atol=1e-6)
      and np.allclose(trm_b["alb"], trm["alb"], atol=1e-6) and np.allclose(trm_b["N"], trm["N"], atol=1e-6))
try:
    S.parse_textures("detail_triplanar = big")
    bad = False
except ValueError:
    bad = True
check("  detail_triplanar must be a number", bad)


sec("10. Anisotropic texture filtering")


def grazing(aniso):
    """A flat 100 x 100 quad with a fine checker (64 squares across), seen at a grazing angle."""
    W = 256
    img = CopImage()
    img.set("C", np.zeros((W, W, 1), np.float32))
    J, I = np.meshgrid(np.arange(W), np.arange(W))
    img.set("ground_albedo", np.repeat(np.where(((J // 4) + (I // 4)) % 2 == 0, 0.2, 0.8)[..., None], 3, -1)
            .astype(np.float32))
    mesh = _ter.to_mesh(img, "C", 1.0, 100.0)
    mesh.set_string(PRIM, "material", ["ground"] * mesh.nprims)
    got = {}
    orig = S._apply_textures

    def spy(geo, rast, alb, N, *a_, **k_):
        orig(geo, rast, alb, N, *a_, **k_)
        got["alb"] = alb.copy()
    S._apply_textures, old = spy, S._ANISO
    S._ANISO = aniso
    try:
        _O.render_outdoor(mesh, 128, 96, cam=_R.camera(None, "perspective", eye=[0, 6, 60], target=[0, 0, 0], fov=40),
                          ssaa=1, haze=0.0, clouds=0.0, sky_samples=0, textures="basecolor = @{material}_albedo",
                          tex_cop=img)
    finally:
        S._apply_textures, S._ANISO = orig, old
    return got["alb"][..., 0]


iso, ani = grazing(1.0), grazing(8.0)
same = grazing(1.0)
band = slice(30, 40)                                    # a band of the plane well into the distance (row 0 = bottom)
c_iso, c_ani = float(iso[band, 20:108].std()), float(ani[band, 20:108].std())
check("at a grazing angle the footprint takes the short axis (up to 8x): the checker keeps its contrast; "
      "negative control, the long axis (isotropic) blurs it toward grey", c_ani > 1.5 * c_iso and c_ani > 0.05,
      (round(c_iso, 3), round(c_ani, 3)))
far = slice(30, 40)
check("  a dense mesh is filtered in the distance (across face edges): far rows fade toward the mean 0.5 under "
      "isotropic filtering instead of keeping the full checker (the footprint used to be 0 there)",
      float(same[far, 20:108].std()) < 0.15 and abs(float(same[far, 20:108].mean()) - 0.5) < 0.05,
      round(float(same[far, 20:108].std()), 3))


sec("11. Terrain layers: tiled maps blended by masks (an engine's landscape material)")


def layer_run(textures, surf_layers, lib_layers, n=96):
    W = 64
    img = CopImage()
    img.set("C", np.zeros((W, W, 1), np.float32))
    img.set("ground_albedo", np.full((W, W, 3), 0.5, np.float32))
    for k, v in surf_layers.items():
        img.set(k, np.asarray(v, np.float32))
    if "ground_w2" not in surf_layers:                  # a second splat map (layers 5..8), empty
        img.set("ground_w2", np.zeros((W, W, 4), np.float32))
    lib = CopImage()
    for k, v in lib_layers.items():
        lib.set(k, np.asarray(v, np.float32))
    mesh = _ter.to_mesh(img, "C", 1.0, 100.0)
    mesh.set_string(PRIM, "material", ["ground"] * mesh.nprims)
    got = {}
    orig = S._apply_textures

    def spy(geo, rast, alb, N, *a_, **k_):
        orig(geo, rast, alb, N, *a_, **k_)
        got["alb"], got["N"], got["rough"] = alb.copy(), N.copy(), a_[7]["roughness"].copy()
    S._apply_textures = spy
    try:
        _O.render_outdoor(mesh, n, n, cam=_R.camera(None, "perspective", eye=[0, 150, 0.01], target=[0, 0, 0],
                                                    fov=20), ssaa=1, haze=0.0, clouds=0.0, sky_samples=0,
                          textures=textures, tex_cop=img, detail_cop=lib)
    finally:
        S._apply_textures = orig
    return got


def solid(c, R_=32):
    return np.tile(np.asarray(c, np.float32), (R_, R_, 1))


wts = np.zeros((W_, W_, 4))
wts[:, :W_ // 3, 0] = 1.0                       # left third: layer 1
wts[:, W_ // 3:2 * W_ // 3, 1] = 1.0            # middle: layer 2
wts[:, 2 * W_ // 3:, :] = 0.0                    # right third: no layer (the base colour shows)
L2 = ("basecolor = @{material}_albedo\nlayer1 = @red\nlayer2 = @blue\nlayer_weights = @{material}_w @{material}_w2\n")
red, blue = (0.6, 0.2, 0.1), (0.1, 0.2, 0.6)
r1 = layer_run(L2, {"ground_w": wts}, {"red": solid(red), "blue": solid(blue)})
Hn = r1["alb"].shape[0]
row = r1["alb"][Hn // 2]
check("masks pick the layers (two splat maps named, '@a @b'): red where weight 1 is set, blue where weight 2 is, "
      "the base colour (0.5) where none",
      np.allclose(row[8], red, atol=0.01) and np.allclose(row[48], blue, atol=0.01)
      and np.allclose(row[88], 0.5, atol=0.01), (np.round(row[8], 3), np.round(row[48], 3), np.round(row[88], 3)))
half = np.zeros((W_, W_, 4))
half[..., 0] = half[..., 1] = 0.5
r2 = layer_run(L2, {"ground_w": half}, {"red": solid(red), "blue": solid(blue)})
check("  weights 0.5 / 0.5 blend the colours half and half", np.allclose(r2["alb"][Hn // 2, 48],
                                                                      (np.array(red) + blue) / 2, atol=0.01))
w5 = np.zeros((W_, W_, 4))
w5[..., 0] = 1.0
L5 = "basecolor = @{material}_albedo\nlayer5 = @red\nlayer_weights = @{material}_w @{material}_w2\n"
r5 = layer_run(L5, {"ground_w": np.zeros((W_, W_, 4)), "ground_w2": w5}, {"red": solid(red)})
check("  the second splat map's first channel is layer 5", np.allclose(r5["alb"][Hn // 2, 48], red, atol=0.01))
hb = np.zeros((W_, W_, 4))
hb[..., 0], hb[..., 1] = 0.4, 0.6
LH = L2 + "layer1_height = @hi\nlayer2_height = @lo\n"
lib = {"red": solid(red), "blue": solid(blue), "hi": solid((1.0, 1.0, 1.0)), "lo": solid((0.0, 0.0, 0.0))}
rh = layer_run(LH + "layer_blend = 0.2", {"ground_w": hb}, lib)
rl = layer_run(LH, {"ground_w": hb}, lib)
check("  height blend (layer_blend 0.2): the higher layer (red, height 1) covers the lower one even at weight 0.4; "
      "negative control, without it the colour is the 40 / 60 mix",
      np.allclose(rh["alb"][Hn // 2, 48], red, atol=0.01)
      and np.allclose(rl["alb"][Hn // 2, 48], 0.4 * np.array(red) + 0.6 * np.array(blue), atol=0.01))
J2, I2 = np.meshgrid(np.arange(32), np.arange(32))
chk = np.repeat(np.where(((J2 // 8) + (I2 // 8)) % 2 == 0, 0.2, 0.8)[..., None], 3, -1)   # 4 x 4 squares per tile
one = np.zeros((W_, W_, 4))
one[..., 0] = 1.0
LS = "basecolor = @{material}_albedo\nlayer1 = @chk\nlayer_weights = @{material}_w\nlayer1_size = "
s25 = layer_run(LS + "25", {"ground_w": one}, {"chk": chk})
s50 = layer_run(LS + "50", {"ground_w": one}, {"chk": chk})
e25 = int((np.diff(np.sign(s25["alb"][Hn // 2, 10:86, 0] - 0.5)) != 0).sum())
e50 = int((np.diff(np.sign(s50["alb"][Hn // 2, 10:86, 0] - 0.5)) != 0).sum())
check("  layerN_size is metres per tile in world space: 25 m tiles give twice the checker edges of 50 m ones",
      e50 >= 2 and abs(e25 - 2 * e50) <= 2, (e25, e50))
tilted_n = solid((0.5 * 0.5 + 0.5, 0.5, 0.5 * 0.866 + 0.5))
LN = ("basecolor = @{material}_albedo\nlayer1 = @red\nlayer1_normal = @tn\nlayer1_rough = @rg\n"
      "layer_weights = @{material}_w\nlayer_macro = @{material}_mac\nroughness = @{material}_r\n")
rn = layer_run(LN, {"ground_w": wts, "ground_mac": np.full((W_, W_, 3), 0.5), "ground_r": np.full((W_, W_, 1), 0.9)},
               {"red": solid(red), "tn": tilted_n, "rg": solid((0.3, 0.3, 0.3))})
check("  a layer's normal map tilts the surface in world space (30 degrees toward +x on flat ground), its roughness "
      "replaces the base one, the macro multiplies its colour (0.5 -> half); untouched where its weight is 0",
      np.allclose(rn["N"][Hn // 2, 8], [0.5, 0.866, 0], atol=0.02) and abs(rn["rough"][Hn // 2, 8] - 0.3) < 0.01
      and np.allclose(rn["alb"][Hn // 2, 8], np.array(red) * 0.5, atol=0.01)
      and np.allclose(rn["N"][Hn // 2, 88], [0, 1, 0], atol=1e-3) and abs(rn["rough"][Hn // 2, 88] - 0.9) < 0.01,
      (np.round(rn["N"][Hn // 2, 8], 3), round(float(rn["rough"][Hn // 2, 8]), 3)))
try:
    S.parse_textures("layer3_size = wide")
    bad = False
except ValueError:
    bad = True
check("  layerN_size must be a number; layer slots are accepted by the parser",
      bad and set(S.parse_textures("layer12 = @a\nlayer12_normal = @b\nlayer_weights = @w").keys())
      == {"layer12", "layer12_normal", "layer_weights"})

print("-- alpha cutout")
from comfyui_pcg.geo import Geometry as _G, outdoor as _O, render as _R  # noqa: E402
from comfyui_pcg.geo.cop.core import CopImage as _CI  # noqa: E402
# a red card in front of a blue wall; the card's alpha is a disc of radius 28 / 64 of its side
_P = np.array([[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0], [-2, -2, -1], [2, -2, -1], [2, 2, -1], [-2, 2, -1]], float)
AG = _G.from_mesh(_P, [[0, 1, 2, 3], [4, 5, 6, 7]])
AG.set(POINT, "Cd", np.array([[1, 0, 0]] * 4 + [[0, 0, 1]] * 4, float))
AG.set(VERTEX, "uv", np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]] * 2, float))
AG.set_string(PRIM, "material", np.array(["card", "wall"]))
_yy, _xx = np.mgrid[0:64, 0:64]
_disc = ((_xx - 31.5) ** 2 + (_yy - 31.5) ** 2 < 28 ** 2).astype(np.float32)
ACOP = _CI(64, 64, {"card_alpha": _disc[..., None]})
red = lambda im: float((im[..., 0] > im[..., 2] + 0.1).mean())          # noqa: E731
blue = lambda im: float((im[..., 2] > im[..., 0] + 0.1).mean())         # noqa: E731
a0 = S.render_studio(AG, 200, 200, 0, 0, tex_cop=ACOP)
a1 = S.render_studio(AG, 200, 200, 0, 0, textures="alpha = @{material}_alpha", tex_cop=ACOP)
ratio = red(a1) / max(red(a0), 1e-9)
check("alpha cutout: the card keeps only its disc (area ratio pi 28² / 64² = 0.60)", abs(ratio - np.pi * 28 ** 2 / 64 ** 2) < 0.03,
      round(ratio, 3))
check("  and the wall behind shows through where it is cut away (more blue)", blue(a1) > blue(a0) + 0.03,
      (round(blue(a0), 3), round(blue(a1), 3)))
a2 = S.render_studio(AG, 200, 200, 0, 0, textures="alpha = @{material}_alpha\nalpha_cutoff = 1.5", tex_cop=ACOP)
check("  alpha_cutoff above every value removes the card", red(a2) < 0.002 and blue(a2) > blue(a1))
a3 = S.render_studio(AG, 200, 200, 0, 0, textures="alpha = @{material}_missing", tex_cop=ACOP)
check("  negative control: an alpha layer that is not there cuts nothing", abs(red(a3) - red(a0)) < 1e-6)
_cam = _R.camera(None, "perspective", eye=(0, 0, 6), target=(0, 0, 0))
o0 = _O.render_outdoor(AG, 160, 160, cam=_cam, ground=False, sky_samples=4, ssaa=1, tex_cop=ACOP)
o1 = _O.render_outdoor(AG, 160, 160, cam=_cam, ground=False, sky_samples=4, ssaa=1, tex_cop=ACOP,
                       textures="alpha = @{material}_alpha")
r_o = float((o1[..., 0] > o1[..., 2] + 0.05).mean()) / max(float((o0[..., 0] > o0[..., 2] + 0.05).mean()), 1e-9)
check("  the Outdoor look cuts the same way", abs(r_o - 0.60) < 0.05, round(r_o, 3))
SPL = _CI(64, 64, {"card_alpha": _disc[..., None]})
a4 = S.render_studio(AG, 200, 200, 0, 0, textures="alpha = @{material}_alpha", splat_cop=SPL)
check("  an '@layer' not on textures_cop is found on splat_cop", abs(red(a4) - red(a1)) < 1e-6)
g_ = AG.copy()
g_.remove(VERTEX, "uv")
g_.set(POINT, "uv", np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]] * 2, float))
a5 = S.render_studio(g_, 200, 200, 0, 0, textures="alpha = @{material}_alpha", tex_cop=ACOP)
check("  point uv works as well as vertex uv", abs(red(a5) - red(a1)) < 1e-6)

# 'a | b': the first alternative that exists, per material
_P2 = np.array([[-2, -1, 0], [0, -1, 0], [0, 1, 0], [-2, 1, 0], [0, -1, 0], [2, -1, 0], [2, 1, 0], [0, 1, 0]], float)
g2 = _G.from_mesh(_P2, [[0, 1, 2, 3], [4, 5, 6, 7]])
g2.set(VERTEX, "uv", np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]] * 2, float))
g2.set_string(PRIM, "material", np.array(["terrain", "M_Brick"]))
_td = tempfile.mkdtemp()
Image.fromarray(np.full((8, 8, 3), [0, 255, 0], np.uint8)).save(os.path.join(_td, "T_M_Brick.png"))
_tc = _CI(8, 8, {"terrain_albedo": np.tile(np.array([1, 0, 0], np.float32), (8, 8, 1))})
_rp = {}
alt = S.render_studio(g2, 200, 100, 0, 0, textures="basecolor = @{material}_albedo | T_{material}.png", tex_root=_td,
                      tex_cop=_tc, report=_rp, shadows=False, ao=False)
check("'a | b' alternatives: the terrain takes its layer, the brick face its file, nothing reported missing",
      alt[50, 40, 0] > 0.5 > alt[50, 40, 1] and alt[50, 160, 1] > 0.5 > alt[50, 160, 0] and not _rp["missing"], _rp)
alt2 = S.render_studio(g2, 200, 100, 0, 0, textures="basecolor = @{material}_albedo", tex_cop=_tc, shadows=False, ao=False)
check("  negative control: with the layer alone the brick face keeps its grey", abs(float(alt2[50, 160, 0]) - float(alt2[50, 160, 1])) < 0.02)

# shadow_only: a box over a floor is not seen but still shades it
from comfyui_pcg.geo import build as _b  # noqa: E402
flo = _b.grid(6.0, 6.0, 2, 2)
flo.set(PRIM, "shadow_only", np.zeros(flo.nprims, np.int32))
bx = ops.transform(_b.box(size=(1, 1, 1)), translate=(0, 1.5, 0)) if hasattr(ops, "transform") else None
if bx is None:
    bx = _b.box(size=(1, 1, 1))
    bx.set(POINT, "P", np.asarray(bx.get(POINT, "P")) + np.array([0, 1.5, 0], np.float32))
bx.set(PRIM, "shadow_only", np.ones(bx.nprims, np.int32))
scn = ops.merge(flo, bx)
_c2 = _R.camera(None, "perspective", eye=(0, 9, 0.01), target=(0, 0, 0))
s1 = _O.render_outdoor(scn, 120, 120, cam=_c2, ground=False, sky_samples=4, ssaa=1, sun_elev=89.0)
flo2 = flo.copy()
s0 = _O.render_outdoor(flo2, 120, 120, cam=_c2, ground=False, sky_samples=4, ssaa=1, sun_elev=89.0)
bx2 = bx.copy()
bx2.set(PRIM, "shadow_only", np.zeros(bx.nprims, np.int32))
s2 = _O.render_outdoor(ops.merge(flo, bx2), 120, 120, cam=_c2, ground=False, sky_samples=4, ssaa=1, sun_elev=89.0)
cen = (slice(54, 66), slice(54, 66))
check("shadow_only: the box is not seen, yet the floor under it is in its shadow (darker than without the box)",
      s1[cen].mean() < 0.7 * s0[cen].mean() and np.abs(s1[0:20, 0:20] - s0[0:20, 0:20]).max() < 0.05,
      (round(float(s0[cen].mean()), 3), round(float(s1[cen].mean()), 3)))
check("  negative control: seen, the box's top (lit by the high sun) is brighter than its shadow",
      s2[cen].mean() > s1[cen].mean() + 0.05, round(float(s2[cen].mean()), 3))


# the alpha test runs on the cut-out prims' fragments only (test.prims): the same picture as testing every fragment
_t1, _cut1 = S.alpha_tester(AG, S.parse_textures("alpha = @{material}_alpha"), cops=(ACOP,))
_calls = []


def _plain(t, bb, rast):
    _calls.append(len(t))
    return _t1(t, bb, rast)
ra_ = _R.rasterize(AG, _cam, alpha=_t1)
rb_ = _R.rasterize(AG, _cam, alpha=_plain)
_n_all = sum(_calls)
_calls.clear()
_plain.prims = _cut1
rc_ = _R.rasterize(AG, _cam, alpha=_plain)
check("alpha test on the cut-out prims only (test.prims): the same hits as testing every fragment, fewer fragments "
      f"tested ({sum(_calls)} of {_n_all})", np.array_equal(ra_["hit"], rb_["hit"]) and np.array_equal(ra_["hit"], rc_["hit"])
      and 0 < sum(_calls) < _n_all, (sum(_calls), _n_all))
_plain.prims = np.zeros(AG.nprims, bool)
rd_ = _R.rasterize(AG, _cam, alpha=_plain)
check("  negative control: a test that names no prims cuts nothing", np.array_equal(rd_["hit"], _R.rasterize(AG, _cam)["hit"]))

# basecolor_tint: the texture times the colour attribute
_wt = _CI(8, 8, {"card_albedo": np.ones((8, 8, 3), np.float32)})
tg = AG.copy()
tg.set(POINT, "Cd", np.array([[0.5, 1, 1]] * 4 + [[0, 0, 1]] * 4, float))
t0 = S.render_studio(tg, 200, 200, 0, 0, textures="basecolor = @{material}_albedo", tex_cop=_wt, shadows=False, ao=False)
t1 = S.render_studio(tg, 200, 200, 0, 0, textures="basecolor = @{material}_albedo\nbasecolor_tint = 1", tex_cop=_wt,
                     shadows=False, ao=False)
c0, c1 = t0[100, 100], t1[100, 100]
check("basecolor_tint: a white texture tinted by Cd (0.5, 1, 1): red below green and blue; without the tint all equal",
      c1[0] < 0.8 * c1[1] and abs(c1[1] - c1[2]) < 0.02 and abs(c0[0] - c0[1]) < 0.02, (c0.round(3), c1.round(3)))

# uv_blend: two uvs on the two halves of the alpha / colour texture, mixed by per-point weights
_half = np.zeros((8, 8, 1), np.float32)
_half[:, :4] = 1.0
_rb = np.zeros((8, 8, 3), np.float32)
_rb[:, :4] = (1, 0, 0)
_rb[:, 4:] = (0, 0, 1)
BC = _CI(8, 8, {"card_alpha": _half, "card_albedo": _rb})
bg_ = AG.copy()
bg_.remove(VERTEX, "uv")
bg_.set(POINT, "uv", np.tile([0.25, 0.5, 0], (8, 1)).astype(float))
bg_.set(POINT, "uv2", np.tile([0.75, 0.5, 0], (8, 1)).astype(float))
_bt = "alpha = @{material}_alpha\nbasecolor = @{material}_albedo\nuv_blend = uv uv2\nuv_blend_weights = fw"
cov = {}
for w_ in (0.7, 0.3):
    bg_.set(POINT, "fw", np.tile([w_, 1 - w_], (8, 1)).astype(float))
    cov[w_] = S.render_studio(bg_, 200, 200, 0, 0, textures=_bt, tex_cop=BC, shadows=False, ao=False)
bg_.set(POINT, "fw", np.tile([0.55, 0.45], (8, 1)).astype(float))
mix = S.render_studio(bg_, 200, 200, 0, 0, textures=_bt, tex_cop=BC, shadows=False, ao=False)[100, 100]
check("uv_blend: alpha 0.7 x 1 + 0.3 x 0 keeps the card, 0.3 x 1 + 0.7 x 0 cuts it (the wall shows); the colour "
      "of a 0.55 / 0.45 mix is red and blue together",
      abs(cov[0.7][100, 100, 0] - cov[0.7][100, 100, 2]) > 0.1 and red(cov[0.3]) < 0.002 and mix[0] > 0.15
      and mix[2] > 0.1 and mix[1] < 0.1, (cov[0.7][100, 100].round(3), red(cov[0.3]), mix.round(3)))
t2 = S.render_studio(tg, 200, 200, 0, 0, textures="basecolor = @{material}_albedo\nbasecolor_tint = ca*", tex_cop=_wt,
                     shadows=False, ao=False)
t3 = S.render_studio(tg, 200, 200, 0, 0, textures="basecolor = @{material}_albedo\nbasecolor_tint = imp_*", tex_cop=_wt,
                     shadows=False, ao=False)
check("  basecolor_tint by material name: 'ca*' tints the card, 'imp_*' leaves it white",
      abs(t2[100, 100] - c1).max() < 1e-4 and abs(t3[100, 100] - c0).max() < 1e-4)
bz_ = bg_.copy()
bz_.set(POINT, "fw", np.zeros((8, 2)))
z0 = S.render_studio(bz_, 200, 200, 0, 0, textures=_bt, tex_cop=BC, shadows=False, ao=False)
check("  where the blend weights are 0 the plain uv is read (u = 0.25: opaque and red)",
      z0[100, 100, 0] > z0[100, 100, 2] + 0.2 and red(z0) > 0.1)
_rpb = None
try:
    S.render_studio(bg_, 50, 50, 0, 0, textures="alpha = @{material}_alpha\nuv_blend = uv uv2", tex_cop=BC)
except ValueError as e_:
    _rpb = str(e_)
check("  uv_blend without uv_blend_weights is refused, naming it", _rpb is not None and "uv_blend_weights" in _rpb, _rpb)

# Outdoor extra: a second geometry drawn beside the first without merging -- the same picture as the merge
scnA = ops.merge(flo, bx2)
_ex = _b.box(size=(0.6, 0.6, 0.6))
_ex.set(POINT, "P", np.asarray(_ex.get(POINT, "P")) + np.array([1.5, 0.3, 1.0], np.float32))
_ex.set(POINT, "Cd", np.tile([0.9, 0.2, 0.1], (_ex.npoints, 1)).astype(np.float32))
scnA.set(POINT, "Cd", np.full((scnA.npoints, 3), 0.7, np.float32))
_c3 = _R.camera(None, "perspective", eye=(5, 6, 7), target=(0, 0, 0))
mrg = _O.render_outdoor(ops.merge(scnA, _ex), 140, 110, cam=_c3, ground=False, sky_samples=8, ssaa=1, sun_elev=50.0)
sep = _O.render_outdoor(scnA, 140, 110, cam=_c3, ground=False, sky_samples=8, ssaa=1, sun_elev=50.0, extra=_ex)
alone = _O.render_outdoor(scnA, 140, 110, cam=_c3, ground=False, sky_samples=8, ssaa=1, sun_elev=50.0)
dd_ = np.abs(mrg - sep).max(-1)
check("Outdoor extra: drawn beside the scene without a merge, the picture matches the merged one (99% of pixels "
      "within 2/255; the red box and the shadow it casts are there)",
      float((dd_ < 2 / 255).mean()) > 0.99 and float(np.abs(sep - alone).max(-1).mean()) > 0.005,
      (round(float((dd_ < 2 / 255).mean()), 4), round(float(np.abs(sep - alone).max(-1).mean()), 4)))

# normal-map frames from the triangles round the visible ones only: equal to the frames from every triangle at the
# visible pixels (a wavy uv'd grid seen in part: most of it off screen)
from comfyui_pcg.geo import render as _R  # noqa: E402
from comfyui_pcg.geo.meshexport import corner_frames_subset as _cfs  # noqa: E402
_gw = build.grid(size_x=40.0, size_z=40.0, cols=81, rows=81)
_P = np.asarray(_gw.get(POINT, "P"), np.float32).copy()
_P[:, 1] = np.sin(_P[:, 0] * 0.7) * 0.8 + np.cos(_P[:, 2] * 0.5) * 0.6
_gw.set(POINT, "P", _P)
_gw.set(POINT, "uv", np.c_[_P[:, 0] * 0.13, _P[:, 2] * 0.11, np.zeros(len(_P))].astype(np.float32))
_cam = _R.camera(None, "perspective", eye=[-14, 3, -14], target=[-8, 0, -8], fov=30, xres=96, yres=72)
_rs = _R.rasterize(_gw, _cam)
_tg = np.nonzero(_rs["hit"] >= 0)
_Nn, _Tt, _hd = S._material_frames(_gw, _rs, _tg, "uv", None, "")
_vids, _Nc, _T4 = _cfs(_gw, "uv", _rs["tri"], _rs["cor"], np.ones(len(_rs["src"]), bool))
_t = _rs["hit"][_tg]
_w = _rs["bary"][_tg]
_ids = np.searchsorted(_vids, _rs["cor"][_t])
_ref = (_T4[_ids[:, 0], :3] * _w[:, 0:1] + _T4[_ids[:, 1], :3] * _w[:, 1:2] + _T4[_ids[:, 2], :3] * _w[:, 2:3])
_nvis = len(np.unique(_t))
check(f"normal-map frames from the visible triangles' neighbourhood ({_nvis} of {len(_rs['src'])} triangles seen) "
      "= the frames from every triangle", len(_tg[0]) > 500 and _nvis < 0.5 * len(_rs["src"])
      and np.abs(_Tt - _ref).max() < 1e-5 and np.array_equal(_hd, np.where(_T4[_ids[:, 0], 3] == 0, 1.0,
                                                                            _T4[_ids[:, 0], 3]).astype(np.float32)),
      float(np.abs(_Tt - _ref).max()))
_vm = np.zeros(len(_rs["src"]), bool)
_vm[np.unique(_t)] = True
_v2, _N2, _T42 = _cfs(_gw, "uv", _rs["tri"], _rs["cor"], _vm)
_i2 = np.searchsorted(_v2, _rs["cor"][_t])
_r2 = (_T42[_i2[:, 0], :3] * _w[:, 0:1] + _T42[_i2[:, 1], :3] * _w[:, 1:2] + _T42[_i2[:, 2], :3] * _w[:, 2:3])
check("  negative control: the visible triangles alone (no neighbours) give other frames at the edge of the view",
      np.abs(_r2 - _ref).max() > 1e-3, float(np.abs(_r2 - _ref).max()))
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
