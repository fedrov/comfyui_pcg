"""
Tree Generator (geo/tree.py), checked against the parameters rather than by eye.

  1. Size: a conifer's top is exactly Height; a broadleaf stays under it; the trunk stands at the origin with the
     root flare (1.25 x Trunk Radius); Leaves leaf cards, each a quad of part leaf / material M_Leaf, the rest bark
  2. Form: a conifer's branches reach farther low than high (a cone); a broadleaf's leaves are all in the crown
     (above the crown base), spread about Crown Width; negative control: the conifer's leaves start lower
  3. Attributes: unit normals; bark uv v in metres along the trunk; Normal Bend 1 turns every leaf normal out of the
     crown (negative control: 0 leaves them random); leaves darker inside the crown than at its rim
  4. Seed: the same seed gives the same tree, another seed another; more Branch Levels -> more bark
  5. As an asset: a coarse variant of the same seed is LOD Create's custom LOD1; bad colours and kinds raise
  6. Leaf cards: Leaf Material names the cards' material; Leaf Card Texture draws a twig / a needle spray rooted at
     uv (0.5, 0) (alpha 1 there, 0 in the top corners), antialiased, the colour bled past the cutout, the same seed the
     same card; with it as a cutout the cards render as leaves (an alpha-tested quad lets the sky through), cast
     shadows whole with alpha_shadow (negative control: without it they cast none), and Impostor Textures cuts them
     out too (less coverage than the bare quads, the texture's colour)
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
from comfyui_pcg.geo import tree as T  # noqa: E402
from comfyui_pcg.geo.core import POINT, PRIM  # noqa: E402

N = comfyui_pcg.NODE_CLASS_MAPPINGS
OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if isinstance(extra, str) and extra == "" else "   " + str(extra)))


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
    return out["result"] if isinstance(out, dict) else out


def parts(g):
    P = np.asarray(g.get(POINT, "P"), np.float64)
    vp, off = np.asarray(g.vertex_point), np.asarray(g.prim_offset)
    part = np.asarray(g.get(PRIM, "part")).reshape(-1)
    return P, vp, off, part


print("\n[1. Size]")
con, rc = nrun("TreeGenerator", kind="conifer", height=12.0, crown_base=0.2, crown_width=4.5, leaves=600,
               leaf_size=0.5, branch_levels=1, rand_seed=4)
brd, rb = nrun("TreeGenerator", kind="broadleaf", height=10.0, crown_base=0.35, crown_width=6.0, leaves=400, rand_seed=3)
Pc, vpc, offc, partc = parts(con)
Pb, vpb, offb, partb = parts(brd)
check("conifer: the top at exactly Height (12 m); broadleaf under its 10 m", abs(Pc[:, 1].max() - 12.0) < 0.05
      and 5.0 < Pb[:, 1].max() <= 10.5, (round(float(Pc[:, 1].max()), 3), round(float(Pb[:, 1].max()), 3)))
root = np.unique(np.round(Pb[np.abs(Pb[:, 1]) < 1e-6], 6), axis=0)   # the root ring (its seam point is doubled)
check("the trunk at the origin with the root flare (radius 1.25 x 0.25)", len(root) > 0
      and np.allclose(root[:, [0, 2]].mean(0), 0, atol=1e-6)
      and abs(np.linalg.norm(root[:, [0, 2]], axis=1).max() - 0.3125) < 1e-3)
check("Leaves leaf cards (quads, part leaf, material M_Leaf), the rest bark (M_Bark)",
      (partc == "leaf").sum() == 600 and (partb == "leaf").sum() == 400 and (np.diff(offb) == 4).all()
      and set(np.asarray(brd.get(PRIM, "material")).reshape(-1)[partb == "leaf"]) == {"M_Leaf"}
      and set(np.asarray(brd.get(PRIM, "material")).reshape(-1)[partb == "bark"]) == {"M_Bark"})

print("\n[2. Form]")
barkc = np.unique(vpc[np.repeat(partc == "bark", np.diff(offc))])
pb_ = Pc[barkc]
r_ = np.linalg.norm(pb_[:, [0, 2]], axis=1)
low, high = r_[(pb_[:, 1] > 3) & (pb_[:, 1] < 6)].max(), r_[pb_[:, 1] > 9].max()
check(f"conifer: a cone -- the branches reach {low:.1f} m low (3-6 m) and {high:.1f} m high (above 9 m)",
      low > 1.6 * high and low > 1.5)
lfb = np.repeat(partb == "leaf", np.diff(offb))
lp = Pb[vpb[lfb]]
lfc = np.repeat(partc == "leaf", np.diff(offc))
check(f"broadleaf: the leaves in the crown (lowest {lp[:, 1].min():.1f} m, the crown base at 3.5 m), "
      f"{np.ptp(lp[:, 0]):.1f} m across (Crown Width 6); negative control, the conifer's start at "
      f"{Pc[vpc[lfc]][:, 1].min():.1f} m", lp[:, 1].min() > 2.5 and 3.5 < np.ptp(lp[:, 0]) < 10.0
      and Pc[vpc[lfc]][:, 1].min() < lp[:, 1].min())

print("\n[3. Attributes]")
Nn = np.asarray(brd.get(POINT, "N"), np.float64)
uv = np.asarray(brd.get(POINT, "uv"), np.float64)
trunk_pts = np.unique(vpb[np.repeat(np.asarray(brd.get(PRIM, "level")).reshape(-1) == 0, np.diff(offb))])
check("unit normals; the trunk's uv v in metres along it (0 at the root, its length at the top)",
      np.allclose(np.linalg.norm(Nn, axis=1), 1, atol=1e-4) and abs(uv[trunk_pts, 1].min()) < 1e-6
      and abs(uv[trunk_pts, 1].max() - Pb[trunk_pts, 1].max()) < 0.3,
      (round(float(uv[trunk_pts, 1].max()), 2), round(float(Pb[trunk_pts, 1].max()), 2)))
b1, _ = nrun("TreeGenerator", kind="broadleaf", leaves=200, normal_bend=1.0, rand_seed=7)
b0, _ = nrun("TreeGenerator", kind="broadleaf", leaves=200, normal_bend=0.0, rand_seed=7)
P1, vp1, off1, part1 = parts(b1)
lv = vp1[np.repeat(part1 == "leaf", np.diff(off1))]
cc = np.array([0.0, 10.0 * (0.5 + 0.5 * 0.35), 0.0])
outw = P1[lv] - cc
outw = outw / np.linalg.norm(outw, axis=1, keepdims=True) + [0, 0.6, 0]
outw /= np.linalg.norm(outw, axis=1, keepdims=True)
d1 = (np.asarray(b1.get(POINT, "N"))[lv] * outw).sum(1)
d0 = (np.asarray(b0.get(POINT, "N"))[lv] * outw).sum(1)
check(f"Normal Bend 1: the leaf normals point out of the crown (median cos {np.median(d1):.2f}); negative control, "
      f"Bend 0: {np.median(d0):.2f}", np.median(d1) > 0.9 and np.median(d0) < np.median(d1) - 0.15)
cd = np.asarray(brd.get(POINT, "Cd"), np.float64)[vpb[lfb]].mean(1)
dist = np.linalg.norm((lp - cc) * [1, 0.8, 1], axis=1)
check("leaves darker inside the crown than at its rim", cd[dist < np.percentile(dist, 25)].mean()
      < cd[dist > np.percentile(dist, 75)].mean() - 0.02)

print("\n[4. Seed]")
s1, _ = nrun("TreeGenerator", rand_seed=11)
s2, _ = nrun("TreeGenerator", rand_seed=11)
s3, _ = nrun("TreeGenerator", rand_seed=12)
l3, _ = nrun("TreeGenerator", rand_seed=11, branch_levels=3)
check("the same seed the same tree, another seed another; three branch levels more bark than two",
      np.array_equal(np.asarray(s1.get(POINT, "P")), np.asarray(s2.get(POINT, "P")))
      and (s1.npoints != s3.npoints or not np.allclose(np.asarray(s1.get(POINT, "P")), np.asarray(s3.get(POINT, "P"))))
      and (np.asarray(l3.get(PRIM, "part")) == "bark").sum() > (np.asarray(s1.get(PRIM, "part")) == "bark").sum())

print("\n[5. As an asset]")
# leaf cards are islands of four points: a decimator cannot merge them, so the lower level is a coarser tree of the
# same seed (fewer, larger leaves, three-sided branches) handed to LOD Create as its custom level
coarse, _ = nrun("TreeGenerator", rand_seed=11, leaves=90, leaf_size=1.3, sides=3, branch_levels=1)
coarse.set(PRIM, "lod", np.ones(coarse.nprims, np.int32))
Ps1, Pco = np.asarray(s1.get(POINT, "P")), np.asarray(coarse.get(POINT, "P"))
check(f"the coarse variant (one branch level, 90 leaves, 3 sides): {coarse.nprims} faces vs {s1.nprims}, the same height and spread",
      coarse.nprims < 0.45 * s1.nprims and abs(Pco[:, 1].max() - Ps1[:, 1].max()) < 0.1 * Ps1[:, 1].max()
      and abs(np.ptp(Pco[:, 0]) - np.ptp(Ps1[:, 0])) < 0.25 * np.ptp(Ps1[:, 0]))
s1.set_string(PRIM, "name", np.full(s1.nprims, "SM_Tree"))
coarse.set_string(PRIM, "name", np.full(coarse.nprims, "SM_Tree"))
lc = nrun("LODCreate", geo=s1, percents="100 100 10", distances="0 80 300", last_lod_impostor=True,
          custom=coarse)[0]
lv_ = np.asarray(lc.get(PRIM, "lod")).reshape(-1)
check("LOD Create: LOD0 the tree, LOD1 the coarse variant (its custom level), LOD2 the impostor cards",
      (lv_ == 0).sum() == s1.nprims and (lv_ == 1).sum() == coarse.nprims and 0 < (lv_ == 2).sum() <= 4,
      ((lv_ == 0).sum(), (lv_ == 1).sum(), (lv_ == 2).sum()))


def raises(**kw):
    try:
        nrun("TreeGenerator", **kw)
        return False
    except ValueError:
        return True


check("a bad Leaf Color, a bad Bark Color raise", raises(leaf_color="green") and raises(bark_color="0.1 0.2"))
try:
    T.tree("palm")
    bad = False
except ValueError:
    bad = True
check("  an unknown kind raises", bad)

# 6. Leaf cards
g6, _ = T.tree("conifer", leaves=40, seed=2, leaf_material="M_Needle")
mat6 = np.asarray(g6.get(PRIM, "material")).reshape(-1).astype(str)
part6 = np.asarray(g6.get(PRIM, "part")).reshape(-1).astype(str)
check("Leaf Material: the leaf cards carry it, the bark stays M_Bark",
      set(mat6[part6 == "leaf"]) == {"M_Needle"} and set(mat6[part6 == "bark"]) == {"M_Bark"})
from comfyui_pcg.geo.cop.leafcard import leaf_card  # noqa: E402
for kind_ in ("broadleaf", "conifer"):
    c_, a_ = leaf_card(kind_, 128, 9, (0.3, 0.5, 0.1), seed=5)
    c2_, a2_ = leaf_card(kind_, 128, 9, (0.3, 0.5, 0.1), seed=5)
    c3_, a3_ = leaf_card(kind_, 128, 9, (0.3, 0.5, 0.1), seed=6)
    root = a_[1:4, 61:67].max()
    corners = max(a_[-6:, :6].max(), a_[-6:, -6:].max())
    soft = float(((a_ > 0.05) & (a_ < 0.95)).mean())
    bleed = c_[(a_ < 0.02)].mean(0)
    check(f"Leaf Card Texture {kind_}: rooted at uv (0.5, 0) (alpha {root:.2f}), the top corners empty ({corners:.2f}), "
          f"coverage {a_.mean():.2f}, antialiased edge ({soft:.1%} partial), the colour bled past the cutout (green "
          f"{np.round(bleed, 2)}); same seed same card, another seed another",
          root > 0.9 and corners < 0.05 and 0.12 < a_.mean() < 0.6 and soft > 0.01 and bleed[1] > bleed[2] > 0
          and np.array_equal(a_, a2_) and not np.array_equal(a_, a3_))
lc_ = nrun("LeafCardTexture", kind="broadleaf", resolution=64, prefix="M_Leaf")[0]
check("  the node: layers <Prefix>_C and <Prefix>_alpha", "M_Leaf_C" in lc_ and "M_Leaf_alpha" in lc_, lc_.names)
for bad_ in (dict(kind="palm"), dict(prefix=" "), dict(leaf_color="green")):
    try:
        nrun("LeafCardTexture", resolution=32, **bad_)
        ok_ = False
    except (ValueError, KeyError):
        ok_ = True
    check(f"  bad input raises: {bad_}", ok_)

from comfyui_pcg.geo import outdoor as O, render as R, build  # noqa: E402
from comfyui_pcg.geo.cop.core import CopImage  # noqa: E402
from comfyui_pcg.geo.cop.pixel import put  # noqa: E402
from comfyui_pcg.geo.ops import merge  # noqa: E402
# a 4 m card standing 3 m up over a ground plate, cut out entirely except for a disc in its middle
card = build.grid(size_x=4.0, size_z=4.0, cols=2, rows=2)
Pc = np.asarray(card.get(POINT, "P"), np.float32)
card.set(POINT, "P", np.c_[Pc[:, 0], np.full(len(Pc), 3.0, np.float32), Pc[:, 2]])
card.set(POINT, "uv", np.c_[(Pc[:, 0] + 2) / 4, (Pc[:, 2] + 2) / 4, np.zeros(len(Pc))].astype(np.float32))
card.set_string(PRIM, "material", np.full(card.nprims, "M_Leaf"))
plate = build.grid(size_x=30.0, size_z=30.0, cols=2, rows=2)
plate.set(POINT, "uv", np.zeros((plate.npoints, 3), np.float32))
plate.set_string(PRIM, "material", np.full(plate.nprims, "M_Ground"))
scene = merge(card, plate)
yy, xx = np.mgrid[0:64, 0:64]
disc = (((xx - 31.5) ** 2 + (yy - 31.5) ** 2) < 12 ** 2).astype(np.float32)
lcop = CopImage(64, 64)
put(lcop, "M_Leaf_alpha", disc)
cam6 = R.camera(None, "perspective", eye=[0, 22, 0.01], target=[0, 0, 0], fov=40)
k6 = dict(cam=cam6, ssaa=1, haze=0.0, clouds=0.0, sky_samples=0, ground=False, sun_elev=90.0, tex_cop=lcop)
TX = "alpha = @{material}_alpha"
img0 = O.render_outdoor(scene, 96, 96, textures=TX, **k6)
img1 = O.render_outdoor(scene, 96, 96, textures=TX + "\nalpha_shadow = M_Leaf", **k6)
ring = (lambda a: a[(np.hypot(*np.mgrid[0:96, 0:96] - 47.5) > 7) & (np.hypot(*np.mgrid[0:96, 0:96] - 47.5) < 10.5)])
# the card spans 4 m at 19 m from the camera: about 28 px across, the disc about 10; its shadow on the plate 22 m away
# about 24 px. The ring 7..10.5 px from the centre is outside the disc, on the cut-away part of the card: ground seen
# through it, in the card's shadow or not
check("alpha_shadow: a cut-out card casts its shadow whole (the ground seen through the cut-away part is darker "
      "with it than without: without, cut-out faces cast no shadow)",
      ring(img1).mean() < 0.8 * ring(img0).mean(), (round(float(ring(img1).mean()), 3), round(float(ring(img0).mean()), 3)))
from comfyui_pcg.geo import impostor as I  # noqa: E402
gt_, _ = T.tree("broadleaf", leaves=120, seed=3, leaf_color=(1, 1, 1))
lc2 = nrun("LeafCardTexture", kind="broadleaf", resolution=128, prefix="M_Leaf", leaf_color="0.2 0.6 0.1")[0]
i0, _, r0 = I.impostor_textures(gt_, "hemi_octahedron", 32, 4, 4)
i1, _, r1 = I.impostor_textures(gt_, "hemi_octahedron", 32, 4, 4, textures="basecolor = @{material}_C\n"
                                "alpha = @{material}_alpha\nbasecolor_tint = M_Leaf", textures_cop=lc2)
C1 = np.asarray(i1.get("C"))
A1 = np.asarray(i1.get("alpha"))[..., 0] > 0.5
leafc = C1[A1].mean(0)
check(f"Impostor Textures with the leaf texture: the cards cut out (coverage {r1['coverage']:.3f} vs "
      f"{r0['coverage']:.3f} as quads), the colour the texture's green ({np.round(leafc, 3)}; Cd alone is grey)",
      r1["coverage"] < 0.8 * r0["coverage"] and leafc[1] > 1.5 * leafc[2] and leafc[1] > leafc[0]
      and "@M_Leaf_C" in r1.get("textures_used", []) and "@M_Leaf_alpha" in r1.get("textures_used", []),
      r1.get("textures_used"))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
