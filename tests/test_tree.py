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

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
