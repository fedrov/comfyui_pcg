"""
Grunge maps (geo/cop/grunge.py, the fourteen COP Grunge nodes). The patterns are our own, so what is checked is
what a user relies on: range, determinism, seamless tiling, the Range / Pattern sections' arithmetic, and that
each map's own controls do what their names say (with a negative control where a property could hold by accident).
"""
import os
import sys
_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))), "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import numpy as np
import fakecomfy  # noqa: F401
from comfyui_pcg import nodes as N
from comfyui_pcg.geo.cop import grunge as G
from comfyui_pcg.geo.cop.pixel import getn

OK = []
def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)

def err(name, fn, frag):
    try:
        fn(); check(name, False, "no error raised")
    except Exception as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:110]}")


R = 128
def m(kind, res=R, **kw):
    params = kw.pop("params", None)
    return getn(G.grunge(None, kind, params=params, xres=kw.pop("xres", res), yres=kw.pop("yres", res), **kw),
                kw.get("out_layer", "grunge"))[..., 0]


def seam(a):
    """Step across the wrap, against the typical step inside (1 = as smooth as anywhere else)."""
    inner = max(float(np.abs(np.diff(a, axis=1)).mean()), float(np.abs(np.diff(a, axis=0)).mean()), 1e-9)
    wrap = max(float(np.abs(a[:, 0] - a[:, -1]).mean()), float(np.abs(a[0] - a[-1]).mean()))
    return wrap / inner


print("-- every map")
BASE = {k: m(k) for k in G.KINDS}
check("fourteen maps", len(G.KINDS) == 14)
check("all are 0..1, mono, and not flat",
      all(a.min() >= 0 and a.max() <= 1 and a.std() > 0.03 for a in BASE.values()),
      {k: round(float(a.std()), 3) for k, a in BASE.items() if a.std() <= 0.03})
check("the same inputs give the same map", all(np.array_equal(m(k), BASE[k]) for k in ("rust", "drips", "sheets")))
ds = {k: float(np.abs(m(k, seed=3) - BASE[k]).mean()) for k in G.KINDS}
check("Seed changes every map", min(ds.values()) > 0.01, min(ds, key=ds.get))
sm = {k: seam(a) for k, a in BASE.items()}
check("every map tiles: the step across the wrap is like any other step (< 3x the mean step)",
      max(sm.values()) < 3.0, f"worst {max(sm, key=sm.get)} {max(sm.values()):.2f}")
cut = {k: seam(m(k, tile_size="1.37 1.37")) for k in ("rust", "layered_noise", "moisture", "pine_bark")}
check("negative control: a tile that is not the image does not wrap (step >= 3x)", min(cut.values()) >= 3.0,
      {k: round(v, 1) for k, v in cut.items()})
pair = [(a, b) for i, a in enumerate(G.KINDS) for b in list(G.KINDS)[i + 1:]]
cc = max(abs(float(np.corrcoef(BASE[a].ravel(), BASE[b].ravel())[0, 1])) for a, b in pair)
check("the maps are different patterns (pairwise |correlation| < 0.6)", cc < 0.6, round(cc, 3))

print("-- Range and Pattern")
a = BASE["rust"]
check("out = Amplitude x map + Center", np.allclose(m("rust", amplitude=2.5, center=-0.4), 2.5 * a - 0.4, atol=1e-5))
c = m("rust", mask_contrast=0.6)
check("Mask Contrast = clip((x - c / 2) / (1 - c)): more extreme, still 0..1",
      np.allclose(c, np.clip((a - 0.3) / 0.4, 0, 1), atol=1e-5) and c.std() > a.std())
t2 = m("rust", tile_size="0.5 0.5", element_size=0.125)
check("Tile Size 0.5 repeats the map twice across the image",
      np.allclose(t2[:, :R // 2], t2[:, R // 2:], atol=1e-5) and np.allclose(t2[:R // 2], t2[R // 2:], atol=1e-5))
check("... and each repeat is the whole-tile map at half the size",
      np.allclose(t2[:R // 2, :R // 2], m("rust", res=R // 2, element_size=0.25), atol=1e-5))
o = m("rust", offset="0.25 0")
check("Offset 0.25 rolls the map a quarter of the image", np.allclose(o, np.roll(a, R // 4, axis=1), atol=1e-5))
o = m("rust", offset="0 0.5")
check("... along v too", np.allclose(o, np.roll(a, R // 2, axis=0), atol=1e-5))
def acl(x):                                                          # autocorrelation length (pixels)
    x = x - x.mean()
    f = np.abs(np.fft.fft2(x)) ** 2
    r = np.fft.ifft2(f).real[0]
    r = r / r[0]
    return int(np.argmax(r < 0.5))
big, small = m("layered_noise", element_size=0.5), m("layered_noise", element_size=0.125)
check("Element Size sets the scale: 4x the element, at least twice the correlation length",
      acl(big) >= 2 * acl(small), f"{acl(big)} vs {acl(small)} px")
check("Element Size is rounded to fit the tile: 0.3 gives the same map as 1 / 3",
      np.allclose(m("rust", element_size=0.3), m("rust", element_size=1 / 3), atol=1e-6))
w = m("rust", xres=256, yres=128, tile_size="1 0.5", element_size=0.25)
check("a 2:1 image with Tile Size 1 x 0.5 tiles as well", w.shape == (128, 256) and seam(w) < 3.0, round(seam(w), 2))
pp = getn(G.grunge(None, "rust", post={"complement": True}, xres=R, yres=R), "grunge")[..., 0]
check("Post Processing runs after Range (Complement = 1 - x)", np.allclose(pp, 1 - a, atol=1e-5))

print("-- the maps' own controls")
def aniso(x):                                                        # > 1: varies more across (u) than along (v)
    return float(np.abs(np.diff(x, axis=1)).mean() / max(np.abs(np.diff(x, axis=0)).mean(), 1e-9))
for k in ("leaking_streaks", "bark_strips", "aurora"):
    check(f"{k} runs vertically (it changes {aniso(BASE[k]):.1f}x faster across than along)", aniso(BASE[k]) > 1.5)
check("negative control: rust and moisture have no direction",
      0.7 < aniso(BASE["rust"]) < 1.4 and 0.7 < aniso(BASE["moisture"]) < 1.4,
      f"{aniso(BASE['rust']):.2f} {aniso(BASE['moisture']):.2f}")
d0 = m("drips", res=256, params={"primary_trailing": 0.0, "secondary_mask": 0, "tertiary_mask": 0, "speckle_mask": 0})
d1 = m("drips", res=256, params={"primary_trailing": 1.0, "secondary_mask": 0, "tertiary_mask": 0, "speckle_mask": 0})
check("Drips: Primary Trailing adds trails (more of the image is covered)", (d1 > 0.1).mean() > 1.3 * (d0 > 0.1).mean(),
      f"{(d1 > 0.1).mean():.3f} vs {(d0 > 0.1).mean():.3f}")
# a trail hangs below its drop: row 0 is the smallest v, so below = smaller row index
heads = d1 > 0.95
tr = (d1 > 0.1) & (d1 < 0.9)
below = (np.roll(heads, -6, axis=0) & tr).sum()                      # trail pixels 6 rows under a head
above = (np.roll(heads, 6, axis=0) & tr).sum()
check("Drips: the trails hang below the heads (toward -v), not above", below > 3 * max(above, 1), f"{below} vs {above}")
lo = m("drips", params={"density": 0.0, "secondary_mask": 0, "tertiary_mask": 0, "speckle_mask": 0})
hi = m("drips", params={"density": 1.0, "secondary_mask": 0, "tertiary_mask": 0, "speckle_mask": 0})
check("Drips: Density adds drops", hi.mean() > 2 * lo.mean(), f"{hi.mean():.3f} vs {lo.mean():.3f}")
r0, r1 = m("rust", params={"coverage": 0.1}), m("rust", params={"coverage": 0.9})
check("Rust: Coverage grows the patches", (r1 > 0.3).mean() > 2 * (r0 > 0.3).mean(),
      f"{(r1 > 0.3).mean():.2f} vs {(r0 > 0.3).mean():.2f}")
s0, s1 = m("bark_strips", params={"strips_inflate": 0.0}), m("bark_strips", params={"strips_inflate": 1.0})
check("Bark Strips: Strips Inflate widens the strips (brighter on average)", s1.mean() > s0.mean() + 0.05,
      f"{s1.mean():.2f} vs {s0.mean():.2f}")
c0, c1 = m("rusty_surface", params={"cracks_mask": 0.0}), m("rusty_surface", params={"cracks_mask": 1.0})
check("Rusty Surface: Cracks Mask only darkens, along thin lines",
      (c1 <= c0 + 1e-6).all() and 0.01 < (c0 - c1 > 0.05).mean() < 0.4, round(float((c0 - c1 > 0.05).mean()), 3))
m0 = m("mold_spots", params={"density": 0.1}); m1 = m("mold_spots", params={"density": 0.9})
check("Mold Spots: Density adds spots", m1.mean() > 1.5 * m0.mean(), f"{m1.mean():.3f} vs {m0.mean():.3f}")
f0, f1 = m("pine_bark", params={"furrow_width": 0.0}), m("pine_bark", params={"furrow_width": 1.0})
check("Pine Bark: Furrow Width widens the dark furrows", (f1 < 0.15).mean() > 1.5 * (f0 < 0.15).mean(),
      f"{(f1 < 0.15).mean():.2f} vs {(f0 < 0.15).mean():.2f}")
l1, l6 = m("layered_noise", params={"layers": 1}), m("layered_noise", params={"layers": 6})
def hf(x):                                                           # share of the energy above 16 cycles
    f = np.abs(np.fft.fft2(x - x.mean())) ** 2
    k = np.hypot(*np.meshgrid(np.fft.fftfreq(R) * R, np.fft.fftfreq(R) * R))
    return float(f[k > 16].sum() / f.sum())
check("Layered Noise: more Layers add fine detail (energy above 16 cycles, x 5)", hf(l6) > 5 * hf(l1),
      f"{hf(l6):.4f} vs {hf(l1):.4f}")
err("an unknown kind is refused", lambda: G.grunge(None, "mud"), "one of")
err("an unknown parameter is refused", lambda: G.grunge(None, "rust", params={"nope": 1}), "nope")
err("Element Size 0 is refused", lambda: G.grunge(None, "rust", element_size=0), "above 0")

print("-- nodes")
M = N.NODE_CLASS_MAPPINGS
names = ["PCG_COPGrunge" + "".join(w.title() for w in k.split("_")) for k in G.KINDS]
check("each map has its node", all(n in M for n in names))
from comfyui_pcg import panel_specs as PS
ok = True
for k, n in zip(G.KINDS, names):
    it = M[n].INPUT_TYPES()
    req = it["required"]
    kw = {a: (s[1]["default"] if isinstance(s[1], dict) and "default" in s[1] else s[0][0]) for a, s in req.items()}
    kw.update(resolution_x=64, resolution_y=64)
    out = M[n]().run(**kw)[0]
    ref = getn(G.grunge(None, k, xres=64, yres=64), "grunge")
    own = [p[0] for p in G.KINDS[k][1]]
    order = list(req)
    ok &= np.allclose(getn(out, "grunge"), ref, atol=1e-6) and all(p in req for p in own)
    ok &= order[:6] == ["amplitude", "center", "mask_contrast", "element_size", "offset", "tile_size"]
    ok &= set(PS.SPECS[n]["order"]) == set(req)
check("node defaults = engine defaults, widgets in Houdini's section order, panel spec covers every widget", ok)
nd = M["PCG_COPGrungeDrips"]
req = nd.INPUT_TYPES()["required"]
check("Grunge Drips carries Houdini's parameter names",
      all(p in req for p in ("density", "distortion", "primary_trailing", "secondary_mask", "secondary_trailing",
                             "tertiary_mask", "speckle_mask")))
from comfyui_pcg.geo.cop.core import CopImage
base = CopImage(48, 32, {"C": np.zeros((32, 48, 3), np.float32)})
kw = {a: (s[1]["default"] if isinstance(s[1], dict) and "default" in s[1] else s[0][0]) for a, s in req.items()}
o = nd().run(cop=base, **{**kw, "out_layer": "wet"})[0]
check("with a cop wired the map joins it at its resolution", o.xres == 48 and "C" in o and getn(o, "wet").shape == (32, 48, 1))

n = len(OK)
print(f"\n{sum(OK)} / {n} grunge checks pass")
sys.exit(0 if all(OK) else 1)
