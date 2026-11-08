"""
pcg100 audit pack s7_attrib_misc: parameters / new nodes completed against the SideFX docs.

  Attribute from Pieces   Weight Method, Piece Filter, Shuffle / Offset, Override Ptnum,
                          Patches / Noise / VEXpression, Map Attribute (Automatic / Explicit /
                          String) + Unmatched Piece / Group, Copy Attributes + Promotion Method
  Attribute Fill          Mode gains Eikonal / Poisson / Diffusion / Extrapolate and their parameters
  Attribute Fade          new node PCG_AttribFadeTime (fade in / hold / fade out over time)
  Attribute Transform Extract  new node PCG_AttribTransformExtractHou (Polar / Crack + Euler filtering)
  Name                    new node PCG_Name
  Camera from Points      no code change, verifies the semantics of the default parameters
  Trace                   Channel combo, Boundary Color, Resample Shapes, Rotate / Scale
  PolyDoctor              new node PCG_PolyDoctor (per-check Ignore / Mark / Repair)

References are all hand-computable numbers. "Bit-identical to before the change at defaults" uses digests computed from the same calls
before the change (commit f210100), hard-coded in GOLDEN; `--digests` prints the current digests.
"""
import hashlib
import os
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))), "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy                                        # noqa: F401,E402
import numpy as np                                      # noqa: E402

from comfyui_pcg import NODE_CLASS_MAPPINGS as M       # noqa: E402
from comfyui_pcg import panel as PANEL                  # noqa: E402
from comfyui_pcg.geo import build, ops                  # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, VERTEX, PRIM, DETAIL  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def defaults(nid):
    kw = {}
    for part in ("required", "optional"):
        for k, spec in M[nid].INPUT_TYPES().get(part, {}).items():
            if isinstance(spec[0], (list, tuple)):
                kw[k] = (spec[1].get("default", spec[0][0])
                         if len(spec) > 1 and isinstance(spec[1], dict) else spec[0][0])
            elif len(spec) > 1 and isinstance(spec[1], dict) and "default" in spec[1]:
                kw[k] = spec[1]["default"]
    return kw


def call(nid, **over):
    """All widgets take their INPUT_TYPES defaults (what ComfyUI actually passes), then overrides. Returns the whole result tuple."""
    kw = defaults(nid)
    kw.update(over)
    r = getattr(M[nid](), M[nid].FUNCTION)(**kw)
    return r["result"] if isinstance(r, dict) else r


def run(nid, **over):
    return call(nid, **over)[0]


def raises(fn, match="", exc=(ValueError, KeyError)):
    """It raised, and it's **our own** human-readable error (match is a fragment of the error text)."""
    try:
        fn()
    except exc as e:
        return match in str(e)
    return False


def names(nid):
    it = M[nid].INPUT_TYPES()
    return [k for part in ("required", "optional") for k in it.get(part, {})]


def P_(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def col(g, name, cls=POINT):
    a = g.get(cls, name)
    if a is None:
        return None
    a = np.asarray(a)
    return a[:, 0].tolist() if a.shape[1] == 1 else a.tolist()


def digest(g):
    h = hashlib.sha1()
    h.update(np.ascontiguousarray(g.vertex_point).tobytes())
    h.update(np.ascontiguousarray(g.prim_offset).tobytes())
    h.update(np.ascontiguousarray(g.prim_closed).tobytes())
    for cls in (POINT, VERTEX, PRIM, DETAIL):
        for k in sorted(g.attribs[cls]):
            v = g.attribs[cls][k]
            h.update(f"{cls}/{k}/{v.dtype}/{v.shape}".encode())
            h.update(np.ascontiguousarray(v).tobytes() if v.dtype.kind != "O"
                     else repr(v.tolist()).encode())
    for cls in (POINT, VERTEX, PRIM):
        for k in sorted(g.groups[cls]):
            h.update(f"g/{cls}/{k}".encode())
            h.update(np.ascontiguousarray(g.groups[cls][k]).tobytes())
    for k in sorted(g.edge_groups):
        h.update(f"e/{k}".encode())
        h.update(np.ascontiguousarray(g.edge_groups[k]).tobytes())
    return h.hexdigest()[:16]


def dg(x):
    """Digest geometry or (geometry, report…). A string report is included too."""
    if isinstance(x, tuple):
        parts = [digest(v) if isinstance(v, Geometry) else
                 hashlib.sha1(str(v).encode()).hexdigest()[:16] for v in x]
        return "/".join(parts)
    return digest(x)


# ═══════════════════════════════════════════════════════════════ Shared geometry
def pts_line(n, dx=1.0):
    """n points along the x axis (points only, no prims)."""
    P = np.zeros((n, 3), np.float32)
    P[:, 0] = np.arange(n) * dx
    return Geometry.from_points(P)


def lib3():
    """A box's 6 faces split into three pieces: a a a b b c (prim string attribute name), val = 3 1 2 4 6 5."""
    lib = build.box((1, 1, 1), (0, 0, 0), (1, 1, 1))
    lib.set_string(PRIM, "name", np.array([["a"], ["a"], ["a"], ["b"], ["b"], ["c"]]))
    lib.set(PRIM, "val", np.array([[3], [1], [2], [4], [6], [5]], np.float32))
    lib.set(PRIM, "ival", np.array([[3], [1], [2], [4], [6], [5]], np.int32))
    lib.set(PRIM, "weight", np.array([[0], [4], [2], [1], [1], [0]], np.float32))
    return lib


def scat(n=400, seed=3):
    """n random points (x, z ∈ [0, 10), y ∈ [0, 1))."""
    rng = np.random.default_rng(seed)
    P = rng.random((n, 3)) * np.array([10.0, 1.0, 10.0])
    return Geometry.from_points(P.astype(np.float32))


from comfyui_pcg.geo.cop.core import CopImage           # noqa: E402


def img_from(a):
    a = np.asarray(a, np.float64)
    if a.ndim == 2:
        a = a[:, :, None]
    return CopImage(a.shape[1], a.shape[0], {"C": a})


def _yx(H=32, W=48):
    return np.mgrid[0:H, 0:W].astype(np.float64)


def img_disk():
    """A 48×32 image with a bright disc centered at (20, 14), radius 9 (not touching the border)."""
    y, x = _yx()
    return img_from(((x - 20) ** 2 + (y - 14) ** 2 <= 81).astype(float))


def img_half():
    """Left half bright (touching the image border)."""
    y, x = _yx()
    return img_from((x < 24).astype(float))


def img_rgba():
    """R: disc at the lower left; G: square at the upper right; B: 0; A: disc in the middle."""
    y, x = _yx()
    R = ((x - 12) ** 2 + (y - 10) ** 2 <= 36).astype(float)
    G = ((np.abs(x - 34) <= 6) & (np.abs(y - 21) <= 5)).astype(float)
    A = ((x - 24) ** 2 + (y - 16) ** 2 <= 49).astype(float)
    return img_from(np.stack([R, G, np.zeros_like(R), A], 2))


# ═══════════════════════════════════════════════════════════════ Old calls (regression)
OLD_NAMES = {
    "PCG_AttribFromPieces": ["geo", "attribute_class", "group", "mode", "count", "weights",
                             "library_attribute", "weight_attribute", "piece_attribute",
                             "input_attribute", "rand_seed", "output", "index_output",
                             "library"],
    "PCG_AttribFill": ["geo", "attribute", "known_group", "method", "weights", "iterations"],
    "PCG_Trace": ["cop", "layer", "channel", "threshold", "invert", "simplify", "min_points",
                  "min_length", "close_open", "plane", "size", "keep_aspect", "height", "center_x",
                  "center_y", "center_z", "add_uv", "uv_attrib"],
}


def old(nid, **kw):
    """Pass only parameters that existed before the change (new widgets use run()'s Python defaults)."""
    base = {k: v for k, v in defaults(nid).items() if k in OLD_NAMES[nid]}
    base.update(kw)
    r = getattr(M[nid](), M[nid].FUNCTION)(**base)
    return r["result"] if isinstance(r, dict) else r


def old_cases(fn=old):
    out = {}
    g, lib = scat(60), lib3()
    g.set(POINT, "u", (np.arange(60, dtype=np.float32) / 59.0)[:, None])
    g.set(POINT, "pc", (np.arange(60, dtype=np.int32) // 7)[:, None])
    gid = scat(30, 5)
    gid.set(POINT, "id", (np.arange(30, dtype=np.int32) * 7 + 3)[:, None])
    grid = build.grid(3.0, 3.0, 4, 4)
    A = "PCG_AttribFromPieces"
    out["afp_rand"] = fn(A, geo=g, rand_seed=4)
    out["afp_rand_w"] = fn(A, geo=g, count=3, weights="1 2 5", index_output="ix")
    out["afp_cycle"] = fn(A, geo=g, mode="cycle", count=5, group="0-20")
    out["afp_attr"] = fn(A, geo=g, mode="by_attribute", input_attribute="u", count=4,
                         weights="1 1 2 4")
    out["afp_piece"] = fn(A, geo=g, piece_attribute="pc", count=3, output="v2")
    out["afp_lib_r"] = fn(A, geo=g, library=lib, index_output="ix")
    out["afp_lib_c"] = fn(A, geo=g, library=lib, mode="cycle", output="name")
    out["afp_lib_a"] = fn(A, geo=g, library=lib, mode="by_attribute", input_attribute="u",
                          weight_attribute="")
    out["afp_id"] = fn(A, geo=gid, count=4, rand_seed=9)
    out["afp_prim"] = fn(A, geo=grid, attribute_class="prim", count=2, mode="cycle")
    out["afp_vtx"] = fn(A, geo=grid, attribute_class="vertex", count=3, library=lib)
    gf = build.grid(4.0, 4.0, 5, 5)
    gf.set(POINT, "v", np.where(np.arange(25)[:, None] % 6 == 0, 1.0 + np.arange(25)[:, None], 0.0).astype(np.float32)
           * np.array([[1.0, 2.0, 0.5]], np.float32))
    for m in ("harmonic", "nearest", "diffuse"):
        out["fill_" + m] = fn("PCG_AttribFill", geo=gf, attribute="v", method=m)
    out["fill_grp"] = fn("PCG_AttribFill", geo=gf, attribute="v", known_group="0-3",
                         weights="inverse_length", method="diffuse", iterations=7)
    T_ = "PCG_Trace"
    out["trace_disk"] = fn(T_, cop=img_disk())
    out["trace_rgb"] = fn(T_, cop=img_rgba(), channel=1, simplify=0.0, plane="xz", center_x=1.0)
    out["trace_half"] = fn(T_, cop=img_half(), invert=True, close_open=True, size=3.0, simplify=0.0,
                           keep_aspect=False, height=0.5, uv_attrib="st")
    out["trace_minlen"] = fn(T_, cop=img_rgba(), channel=3, min_length=0.5, plane="zx")
    return {k: dg(v) for k, v in out.items()}


# digests from running old_cases() before the change (f210100)
GOLDEN = {
    "afp_rand": "54b2b7de92947847/3cb9101799599330",
    "afp_rand_w": "6e052666c0acc0bc/05b0482dd90c2ebc",
    "afp_cycle": "0470fd46530e011c/680d280990ec93b7",
    "afp_attr": "3cdbc4e04cc3dfbb/a31fc5daae99a0bf",
    "afp_piece": "c5b9663369a84978/fc15c199a021ca36",
    "afp_lib_r": "604b722a377e4cff/2915043bcb9e72a1",
    "afp_lib_c": "637b3987ac915bcd/8e5cec2d9faa1b4a",
    "afp_lib_a": "d6c3b2f9460a8d47/8e5cec2d9faa1b4a",
    "afp_id": "4afcb28c9d34ee0d/71813d4d4b2434f9",
    "afp_prim": "4d5d536cc3b2d042/4b674a23fec20e9e",
    "afp_vtx": "eb79442f011f00cb/ea3dea6cdd49640a",
    "fill_harmonic": "5805822b8318f141/dbda13901f811c62",
    "fill_nearest": "42c3cf3635d54e8a/dbda13901f811c62",
    "fill_diffuse": "e78e32a07ab60bff/dbda13901f811c62",
    "fill_grp": "5dfaf1f8fa4c4451/2ac2fa13f0641af2",
    "trace_disk": "42bf0974ed70094a/356a192b7913b04c",
    "trace_rgb": "9a992b2603ce87af/356a192b7913b04c",
    "trace_half": "f5f8426ed8e1f2ca/356a192b7913b04c",
    "trace_minlen": "0baeae6c0cf18ff7/356a192b7913b04c",
}

if "--digests" in sys.argv:
    import json
    print(json.dumps(old_cases(), indent=1))
    sys.exit(0)


# ═══════════════════════════════════════════════════════════════ Regression
sec("Bit-identical to before the change at defaults")
now = old_cases()
check(f"output digests of all {len(GOLDEN)} old calls (old parameters only) unchanged", len(GOLDEN) >= 19 and now == GOLDEN,
      {k: (GOLDEN.get(k), v) for k, v in now.items() if GOLDEN.get(k) != v})
now2 = old_cases(lambda nid, **kw: call(nid, **kw))
check("same calls with new widgets at their panel defaults: digests also unchanged (widget defaults = run() defaults = old behaviour)",
      now2 == GOLDEN, {k: (GOLDEN.get(k), v) for k, v in now2.items() if GOLDEN.get(k) != v})


# ═══════════════════════════════════════════════════════════════ Attribute from Pieces
sec("Attribute from Pieces")
A = "PCG_AttribFromPieces"
lib = lib3()
g9 = pts_line(9)


def afp(geo=g9, **kw):
    return call(A, geo=geo, **kw)


def vv(r, name="variant"):
    return col(r[0], name)


import json                                              # noqa: E402

# ── Weight Method
r = afp(library=lib, geo=scat(600), mode="random")
check("auto (old): weight read from each piece's first prim (a=0, b=1, c=0) → only b",
      set(vv(r)) == {"b"}, json.loads(r[1])["counts"])
r = afp(library=lib, geo=scat(600), weight_method="weight_attribute")
cnt = json.loads(r[1])["counts"]
check("Weight Attribute: average over all prims of each piece (a=(0+4+2)/3=2, b=1, c=0) → a≈2/3, b≈1/3, c=0",
      cnt["c"] == 0 and abs(cnt["a"] / 600 - 2 / 3) < 0.06 and abs(cnt["b"] / 600 - 1 / 3) < 0.06, cnt)
r = afp(library=lib, geo=scat(600), weight_method="uniform")
cnt = json.loads(r[1])["counts"]
check("Uniform Distribution: about 1/3 each for the three pieces (negative control: auto gives only b)",
      all(abs(c / 600 - 1 / 3) < 0.06 for c in cnt.values()), cnt)
r = afp(library=lib, weight_method="piece_weights", weights="a:0 b:0 c:3")
check("Piece Weights name:weight → only c", set(vv(r)) == {"c"})
r = afp(library=lib, weight_method="piece_weights", weights="b:1")
check("Piece Weights: unlisted pieces get weight 0 → only b", set(vv(r)) == {"b"})
r = afp(library=lib, weight_method="piece_weights", weights="1 0 0")
check("Piece Weights numbers in order → only a (read with library connected too; the auto mode doesn't read it with library connected)",
      set(vv(r)) == {"a"} and set(vv(afp(library=lib, weights="1 0 0"))) == {"b"})
cnt = json.loads(afp(library=lib, geo=scat(300), weight_method="piece_weights", weights="")[1])["counts"]
check("Piece Weights empty = all 1 (all three pieces appear)", all(c > 50 for c in cnt.values()), cnt)
r = afp(count=4, weight_method="piece_weights", weights="2:1")
check("without library the piece names are 0..Count−1: '2:1' → all 2", set(vv(r)) == {2})
check("Weight Attribute without library → raises", raises(lambda: afp(weight_method="weight_attribute"),
                                                     "needs library connected"))
check("Piece Weights mixing numbers and name:weight → raises",
      raises(lambda: afp(library=lib, weight_method="piece_weights", weights="1 b:2"), "must be either all numbers"))
check("Piece Weights naming a nonexistent piece → raises",
      raises(lambda: afp(library=lib, weight_method="piece_weights", weights="z:2"), "does not exist"))
check("Weight Attribute missing on the library → raises",
      raises(lambda: afp(library=lib, weight_method="weight_attribute", weight_attribute="nope"),
             "has no numeric attribute"))

# ── Piece Filter / Shuffle / Offset (cycle used to see the order)
r = afp(library=lib, mode="cycle")
check("Cycle (old): a b c a b c …", vv(r) == list("abcabcabc"))
r = afp(library=lib, mode="cycle", piece_filter="c b")
check("Piece Filter 'c b': only b, c are used, in library order (b c b c …)", vv(r) == list("bcbcbcbcb"))
r = afp(count=5, mode="cycle", piece_filter="1 3")
check("without library: Piece Filter '1 3' → 1 3 1 3 …", vv(r) == [1, 3, 1, 3, 1, 3, 1, 3, 1])
lib_num = lib3()
lib_num.set(PRIM, "pid", np.array([[1], [1], [1], [2], [2], [7]], np.float32))
r = afp(library=lib_num, library_attribute="pid", mode="cycle", piece_filter="7 2")
check("numeric piece names compared by value ('7' matches 7.0)", vv(r)[:4] == [2, 7, 2, 7])
check("pieces left by Piece Filter (auto weights a=0, c=0) all have weight 0: random raises, cycle ignores weights and works as usual",
      raises(lambda: afp(library=lib, piece_filter="a c"), "all have weight 0")
      and vv(afp(library=lib, piece_filter="a c", mode="cycle"))[:2] == ["a", "c"])
check("Piece Filter selecting no pieces → raises",
      raises(lambda: afp(library=lib, piece_filter="zz"), "selected no pieces"))
r = afp(library=lib, mode="cycle", offset=1)
check("Offset 1: the last moves to the front → c a b c a b …", vv(r) == list("cabcabcab"))
r = afp(library=lib, mode="cycle", offset=-1)
check("Offset −1 → b c a …", vv(r)[:3] == list("bca"))
r = afp(library=lib, mode="cycle", offset=1, index_output="ix")
check("index output follows the new order (c is item 0)", col(r[0], "ix")[:3] == [0, 1, 2])
shuf = [tuple(vv(afp(library=lib, mode="cycle", shuffle=True, rand_seed=s))[:3]) for s in range(12)]
check("Shuffle: every seed gives a permutation of abc, more than one order appears across 12 seeds (negative control: off gives abc)",
      all(sorted(t) == list("abc") for t in shuf) and len(set(shuf)) > 1, set(shuf))
check("Shuffle with the same seed gives the same result",
      vv(afp(library=lib, mode="cycle", shuffle=True, rand_seed=5))
      == vv(afp(library=lib, mode="cycle", shuffle=True, rand_seed=5)))

# ── Override Ptnum
gi = pts_line(6)
gi.set(POINT, "myid", np.array([[4], [4], [0], [7], [2], [5]], np.int32))
r = afp(geo=gi, library=lib, mode="cycle", use_id_attribute=True, id_attribute="myid")
check("Override Ptnum: cycles by myid mod 3 (4 4 0 7 2 5 → b b a b c c)", vv(r) == list("bbabcc"))
r = afp(geo=gi, library=lib, mode="cycle", use_id_attribute=False, id_attribute="myid")
check("  negative control: with the toggle off it's by point number again (a b c a b c)", vv(r) == list("abcabc"))
g60 = pts_line(60)
g60.set(POINT, "myid", (np.arange(60, dtype=np.int32) // 20)[:, None])
ra = vv(afp(geo=g60, library=lib, weight_method="uniform", use_id_attribute=True,
            id_attribute="myid"))
rb = vv(afp(geo=g60, library=lib, weight_method="uniform"))
check("Random mode also draws random numbers by ID: 20 points with the same id get the same piece (negative control: by point number they all differ)",
      all(len(set(ra[i * 20:(i + 1) * 20])) == 1 for i in range(3))
      and len(set(rb[:20])) > 1)
check("ID Attribute doesn't exist → raises",
      raises(lambda: afp(library=lib, use_id_attribute=True, id_attribute="nope"), "Override Ptnum"))


# ── Patches
def worley_cells_bruteforce(S, seed):
    """Written separately: list the feature points of all nearby cells and find the nearest per point (independent of the implementation's 27 neighbouring cells)."""
    from comfyui_pcg.geo.attribnoise import _cell_hash, _to01
    lo = np.floor(S.min(0)).astype(int) - 2
    hi = np.floor(S.max(0)).astype(int) + 2
    cs = np.stack(np.meshgrid(*[np.arange(a, b + 1) for a, b in zip(lo, hi)], indexing="ij"),
                  -1).reshape(-1, 3)
    fp = cs + np.stack([_to01(_cell_hash(cs, seed, k)) for k in range(1, 4)], 1)
    d = np.linalg.norm(S[:, None, :] - fp[None], axis=2)
    return cs[np.argmin(d, 1)]


gs = scat(500)
r = afp(geo=gs, library=lib, mode="patches", weight_method="uniform", element_size=2.0,
        rand_seed=3)
cells = worley_cells_bruteforce(P_(gs) / 2.0, 3)
v = np.array(vv(r))
ck = [tuple(c) for c in cells]
same = all(len(set(v[[i for i, c in enumerate(ck) if c == u]])) == 1 for u in set(ck))
check("Patches: points in the same Worley cell (same nearest feature point) get the same piece; more than 3 cells, all three pieces appear",
      same and len(set(ck)) > 3 and set(v) == set("abc"), (len(set(ck)), set(v)))
r1 = afp(geo=gs, library=lib, mode="patches", weight_method="uniform", element_size=1e5)
check("  very large Element Size → the whole area in one cell, all the same piece", len(set(vv(r1))) == 1)
gs2 = gs.copy()
gs2.set(POINT, "P", (P_(gs) + np.array([0.37, -1.2, 2.5])).astype(np.float32))
r2 = afp(geo=gs2, library=lib, mode="patches", weight_method="uniform", element_size=2.0,
         rand_seed=3, noise_offset_x=0.37, noise_offset_y=-1.2, noise_offset_z=2.5)
check("  Offset: points and noise field translated together → result unchanged", vv(r2) == vv(r))
r3 = afp(geo=gs2, library=lib, mode="patches", weight_method="uniform", element_size=2.0,
         rand_seed=3)
check("  negative control: translating only the points → result changes", vv(r3) != vv(r))
gc = scat(300)
P = P_(gc)
P[150:, 1] = P[:150, 1] + 5.0
P[150:, [0, 2]] = P[:150, [0, 2]]
gc.set(POINT, "P", P.astype(np.float32))
r4 = afp(geo=gc, library=lib, mode="patches", weight_method="uniform", element_size=1.0,
         element_scale_y=1e5)
v4 = vv(r4)
check("  very large Element Scale y: two points with the same x, z differing only in y get the same piece (columnar blocks)",
      v4[:150] == v4[150:] and len(set(v4)) > 1)
r5 = afp(geo=gc, library=lib, mode="patches", weight_method="uniform", element_size=1.0)
check("  negative control: with Scale all 1 → differences", vv(r5)[:150] != vv(r5)[150:])
gl = scat(300)
gl.set(POINT, "loc", (P_(gl) * 0 + np.array([3.3, 0.2, 7.1])).astype(np.float32))
r6 = afp(geo=gl, library=lib, mode="patches", weight_method="uniform", location_attribute="loc")
check("  Location Attribute: all points have the same loc → all the same piece (negative control: by P more than one piece)",
      len(set(vv(r6))) == 1
      and len(set(vv(afp(geo=gl, library=lib, mode="patches", weight_method="uniform")))) > 1)
r7 = afp(geo=gs, library=lib, mode="patches", weight_method="piece_weights", weights="b:1")
check("  Patches also uses weights: only b weighted → all b", set(vv(r7)) == {"b"})

# ── Noise
from comfyui_pcg.geo import attribnoise as AN            # noqa: E402
r = afp(geo=gs, library=lib, mode="noise", weight_method="uniform", element_size=1.5,
        noise_type="simplex", rand_seed=2)
nv = AN.noise(P_(gs) / 1.5, "simplex", 2)
exp = np.array(list("abc"))[np.minimum(np.floor((nv + 1) / 2 * 3).astype(int), 2)]
check("Noise: noise value (n+1)/2 split evenly into three ranges → a / b / c (matches calling the noise function directly)",
      vv(r) == exp.tolist() and len(set(vv(r))) == 3)
r2 = afp(geo=gs, library=lib, mode="noise", weight_method="uniform", element_size=1.5,
         noise_type="simplex", rand_seed=2, max_octaves=4)
check("  Max Octaves 4 and 1 give different results", vv(r2) != vv(r))
r3 = afp(geo=gs, library=lib, mode="noise", weight_method="uniform", element_size=1.5,
         noise_type="perlin", rand_seed=2)
check("  Noise Type perlin gives a different result", vv(r3) != vv(r))
r4 = afp(geo=gs, library=lib, mode="noise", weight_method="piece_weights", weights="1 1 0",
         element_size=1.5, noise_type="simplex", rand_seed=2)
exp4 = np.where((nv + 1) / 2 < 0.5, "a", "b")
check("  ranges split by weight: 1 1 0 → half a, half b, no c", vv(r4) == exp4.tolist())
r5 = afp(geo=gs, library=lib, mode="noise", weight_method="uniform", element_size=1.5,
         element_scale_x=3.0, noise_type="simplex", rand_seed=2)
nv5 = AN.noise(P_(gs) / (1.5 * np.array([3.0, 1, 1])), "simplex", 2)
check("  Element Scale x 3: sampled at P / (Size × Scale)",
      vv(r5) == np.array(list("abc"))[np.minimum(np.floor((nv5 + 1) / 2 * 3).astype(int), 2)].tolist())
check("  Size × Scale = 0 → raises",
      raises(lambda: afp(library=lib, mode="noise", element_size=1.0, element_scale_z=0.0),
             "cannot be 0"))

# ── Map Attribute
ga = pts_line(25)
ga.set(POINT, "h", np.arange(25, dtype=np.float32)[:, None])
r = afp(geo=ga, library=lib, mode="by_attribute", input_attribute="h", map_from="automatic")
check("Automatic Ranges: h ∈ [0, 24] split evenly into three → 0–7 a, 8–15 b, 16–24 c (weights ignored)",
      vv(r) == ["a"] * 8 + ["b"] * 8 + ["c"] * 9)
r = afp(geo=ga, library=lib, mode="by_attribute", input_attribute="h", map_from="automatic",
        group="0-11")
check("  the value range only considers selected points (0–11 → 0–3 a, 4–7 b, 8–11 c), unselected ones aren't written",
      vv(r)[:12] == ["a"] * 4 + ["b"] * 4 + ["c"] * 4 and vv(r)[12:] == [""] * 13)
r = afp(geo=ga, library=lib, mode="by_attribute", input_attribute="h")
check("  negative control: weighted_unit (old) clamps h to 0..1, almost everything lands in the last piece",
      vv(r)[2:] == ["b"] * 23)
r = afp(geo=ga, library=lib, mode="by_attribute", input_attribute="h", map_from="explicit",
        rules="a : 0 4\nc: 5, 10\n# comment line\n\nb : 10 12", unmatched_piece="", index_output="ix",
        unmatched_group="um")
v = vv(r)
check("Explicit Ranges: both ends inclusive; 10 is on both lines 2 and 3 → the line written first (c)",
      v[:5] == ["a"] * 5 and v[5:11] == ["c"] * 6 and v[11:13] == ["b"] * 2, v[:14])
check("  unmatched ones: empty piece name, index −1, go into Unmatched Group",
      v[13:] == [""] * 12 and col(r[0], "ix")[13:] == [-1] * 12
      and np.nonzero(r[0].groups[POINT]["um"])[0].tolist() == list(range(13, 25)))
check("  the report counts unmatched", json.loads(r[1])["unmatched"] == 12)
r = afp(geo=ga, library=lib, mode="by_attribute", input_attribute="h", map_from="explicit",
        rules="a : 0 4", group="0-9", unmatched_group="um")
check("  Unmatched Group only takes selected elements (Group 0-9 → 5..9)",
      np.nonzero(r[0].groups[POINT]["um"])[0].tolist() == [5, 6, 7, 8, 9])
r = afp(geo=ga, library=lib, mode="by_attribute", input_attribute="h", map_from="explicit",
        rules="a : 0 4", unmatched_piece="c", index_output="ix")
check("  Unmatched Piece = c → the rest are all c, index is c's index 2",
      vv(r) == ["a"] * 5 + ["c"] * 20 and col(r[0], "ix")[5:] == [2] * 20)
r = afp(geo=ga, count=3, mode="by_attribute", input_attribute="h", map_from="explicit",
        rules="2 : 0 4")
check("  integer piece names: unmatched ones write −1", vv(r) == [2] * 5 + [-1] * 20)
gstr = pts_line(6)
gstr.set_string(POINT, "kind", np.array([["rock"], ["tree"], ["rose"], ["bush"], ["tree"], ["x"]]))
r = afp(geo=gstr, library=lib, mode="by_attribute", input_attribute="kind", map_from="string",
        rules="a : r*\nb : tree bush", unmatched_piece="c")
check("String: 'r*' → a, 'tree bush' (either) → b, the rest Unmatched → c", vv(r) == list("ababbc"))
check("  String mode with a non-string attribute → raises",
      raises(lambda: afp(geo=ga, library=lib, mode="by_attribute", input_attribute="h",
                         map_from="string", rules="a : *"), "is not a string attribute"))
check("  Explicit mode with a string attribute → raises",
      raises(lambda: afp(geo=gstr, library=lib, mode="by_attribute", input_attribute="kind",
                         map_from="explicit", rules="a : 0 1"), "needs a numeric attribute"))
check("  Rules missing a colon → raises", raises(lambda: afp(geo=ga, library=lib, mode="by_attribute",
                                                 input_attribute="h", map_from="explicit",
                                                 rules="a 0 4"), "missing a colon"))
check("  Rules naming a nonexistent piece → raises", raises(lambda: afp(geo=ga, library=lib, mode="by_attribute",
                                                   input_attribute="h", map_from="explicit",
                                                   rules="q : 0 4"), "not among the available pieces"))
check("  Rules naming a piece filtered out by Piece Filter → raises",
      raises(lambda: afp(geo=ga, library=lib, mode="by_attribute", input_attribute="h",
                         map_from="explicit", rules="a : 0 4", piece_filter="b c"), "not among the available pieces"))
check("  Explicit line that isn't two numbers → raises",
      raises(lambda: afp(geo=ga, library=lib, mode="by_attribute", input_attribute="h",
                         map_from="explicit", rules="a : 0"), "min max"))
gm = pts_line(400)
gm.set(POINT, "h", np.zeros((400, 1), np.float32))
r = afp(geo=gm, library=lib, mode="by_attribute", input_attribute="h", map_from="explicit",
        rules="a b : -1 1", rand_seed=1)
cnt = json.loads(r[1])["counts"]
check("  two piece names on one line → random choice of the two (about half each, no c)",
      cnt["c"] == 0 and abs(cnt["a"] / 400 - 0.5) < 0.08, cnt)
r2 = afp(geo=gm, library=lib, mode="by_attribute", input_attribute="h", map_from="explicit",
         rules="a b : -1 1", rand_seed=2)
check("  different seed, different result", vv(r2) != vv(r))

# ── VEXpression
r = afp(geo=ga, library=lib, mode="vexpression",
        rules="a : @P.x < 3\nb : @P.x < 10\nc : @ptnum == 20", unmatched_group="none",
        index_output="ix")
v = vv(r)
check("VEXpression: the first true line in line order wins (0–2 a, 3–9 b, 20 c), the rest get no piece",
      v[:3] == ["a"] * 3 and v[3:10] == ["b"] * 7 and v[20] == "c"
      and v[10:20] == [""] * 10 and v[21:] == [""] * 4)
check("  Unmatched Group holds exactly the 14 unmatched points",
      int(r[0].groups[POINT]["none"].sum()) == 14)
r = afp(geo=ga, library=lib, mode="vexpression", rules="a : @P.x < 3", unmatched_piece="b")
check("  Unmatched Piece b", vv(r) == ["a"] * 3 + ["b"] * 22)
r = afp(geo=ga, library=lib, mode="vexpression", rules="b : @P.x < 3",
        input_attribute="h", map_from="explicit")
check("  VEXpression mode ignores Map Pieces From", vv(r)[:3] == ["b"] * 3)
r = afp(geo=ga, library=lib, mode="by_attribute", input_attribute="h", rules="b : 0 3",
        map_from="weighted_unit")
check("  negative control: Map Attribute's weighted_unit mode doesn't read Rules, no piece name error", "b" in vv(r))
gp = pts_line(6)
gp.set(POINT, "pc", np.array([[0], [0], [1], [1], [2], [2]], np.int32))
r = afp(geo=gp, library=lib, mode="vexpression", piece_attribute="pc",
        rules="a : @P.x == 1\nb : @P.x == 2\nc : 1")
check("  with Piece Attribute given: each piece looks at its first element (piece 0's first point x=0 → lands on c; "
      "piece 1's first point x=2 → b)", vv(r) == list("ccbbcc"))

# ── Copy Attributes / Promotion
gc6 = pts_line(6)


def cp(prom, attrs="val", **kw):
    return afp(geo=gc6, library=lib, mode="cycle", copy_attributes=attrs, promotion=prom, **kw)


# a: val 3 1 2;b: 4 6;c: 5
EXP = {"max": (3, 6, 5), "min": (1, 4, 5), "mean": (2, 5, 5), "mode": (1, 4, 5),
       "median": (2, 6, 5), "sum": (6, 10, 5), "sum_squares": (14, 52, 25),
       "rms": (np.sqrt(14 / 3), np.sqrt(26), 5), "first": (3, 4, 5), "last": (2, 6, 5)}
for prom, e in EXP.items():
    got = col(cp(prom)[0], "val")
    check(f"Copy Attributes · {prom}: the three pieces a b c = {np.round(e, 4).tolist()}",
          np.allclose(got, list(e) * 2, atol=1e-5), got[:3])
check("  Median with an even count takes the upper median (b: 4 6 → 6), Mode with all tied takes the smallest (a → 1)",
      col(cp("median")[0], "val")[1] == 6 and col(cp("mode")[0], "val")[0] == 1)
gi_ = cp("max", "ival")[0].get(POINT, "ival")
gm_ = cp("mean", "ival")[0].get(POINT, "ival")
check("  integer attribute: Maximum stays int, Average becomes float",
      gi_.dtype.kind == "i" and gm_.dtype.kind == "f")
r = cp("mode", "name")
check("  Copy Attributes 'name' (string): Mode takes each piece's most common value", col(r[0], "name") == list("abcabc"))
check("  Average on a string → raises", raises(lambda: cp("mean", "name"), "cannot be combined with mean"))
r = cp("first", "*")
check("  '*' without P: P unchanged", np.allclose(P_(r[0]), P_(gc6)))
r = cp("mean", "* ^weight ^name", allow_p=True)
Pl = np.asarray(lib.get(POINT, "P"), np.float64)
vp, vpt = lib.vertex_prim(), lib.vertex_point
cen = [Pl[np.unique(vpt[np.isin(vp, ids)])].mean(0) for ids in ([0, 1, 2], [3, 4], [5])]
check("  Allow P Attribute: P is also combined per piece (Average = mean of the points this piece uses)",
      np.allclose(P_(r[0]), cen * 2, atol=1e-6) and r[0].get(POINT, "weight") is None)
libp = lib3()
libp.set(POINT, "pidx", np.arange(libp.npoints, dtype=np.float32)[:, None])
r = afp(geo=gc6, library=libp, mode="cycle", copy_attributes="pidx", promotion="sum")
expp = [float(np.unique(vpt[np.isin(vp, ids)]).sum()) for ids in ([0, 1, 2], [3, 4], [5])]
check("  point attributes on the library can be copied too: the (deduplicated) points each piece uses, combined by Promotion", col(r[0], "pidx") == expp * 2,
      (col(r[0], "pidx")[:3], expp))
r = afp(geo=ga, library=lib, mode="by_attribute", input_attribute="h", map_from="explicit",
        rules="b : 0 4", copy_attributes="val", promotion="max")
check("  points that matched no piece aren't copied (stay 0)", col(r[0], "val") == [6.0] * 5 + [0.0] * 20)
r = afp(geo=gc6, library=lib, mode="cycle", copy_attributes="val", promotion="max",
        piece_filter="c a", offset=1)
check("  together with Piece Filter / Offset: pieces and attributes line up (c a c a …, val 5 3)",
      vv(r) == list("cacaca") and col(r[0], "val") == [5, 3] * 3)
check("  Copy Attributes without library → raises",
      raises(lambda: afp(copy_attributes="val"), "needs library connected"))
r = afp(geo=gc6, library=lib_num, library_attribute="pid", mode="cycle", output="name",
        copy_attributes="name val", promotion="max")
check("  Copy Attributes matching the output attribute name itself doesn't overwrite the output (output name = pid's value, not overwritten by the library's string name)",
      col(r[0], "name") == [1, 2, 7] * 2 and col(r[0], "val") == [3, 6, 5] * 2)
libt = lib3()
libt.set_string(PRIM, "tag", np.array([["m"], ["z"], ["k"], ["q"], ["b"], ["x"]]))
for prom, e in (("max", "zqx"), ("min", "kbx"), ("median", "mqx"), ("first", "mqx"), ("last", "kbx")):
    r = afp(geo=gc6, library=libt, mode="cycle", copy_attributes="tag", promotion=prom)
    check(f"  string {prom}: a (m z k), b (q b), c (x) → {' '.join(e)} (lexicographic; median with an even count takes the upper one)",
          col(r[0], "tag") == list(e) * 2, col(r[0], "tag"))
check("  unknown Weight Method / Map From / Promotion → raises",
      raises(lambda: afp(weight_method="x"), "Weight Method")
      and raises(lambda: afp(map_from="x"), "Map Pieces From")
      and raises(lambda: afp(promotion="x"), "Promotion"))


# ═══════════════════════════════════════════════════════════════ Attribute Fill
sec("Attribute Fill")
F = "PCG_AttribFill"


def chain(xs, val=None):
    P = np.zeros((len(xs), 3), np.float32)
    P[:, 0] = xs
    g = Geometry.from_mesh(P, [list(range(len(xs)))], closed=False)
    g.set(POINT, "a", (np.zeros(len(xs)) if val is None else np.asarray(val))
          .astype(np.float32)[:, None])
    return g


def fill(geo, **kw):
    return call(F, geo=geo, **kw)


def av(r, name="a"):
    return np.asarray(r[0].get(POINT, name), np.float64)[:, 0]


gch = chain([0, 1, 3, 6], [0, 0, 0, 6])
r = fill(gch, attribute="a", known_group="0 3", method="poisson")
check("Poisson: unevenly spaced chain x = 0 1 3 6, ends 0 / 6 → linear in arc length = 0 1 3 6", np.allclose(av(r), [0, 1, 3, 6], atol=1e-6),
      av(r))
r0 = fill(gch, attribute="a", known_group="0 3", method="harmonic")
check("  negative control: old harmonic (uniform edge weights) → 0 2 4 6", np.allclose(av(r0), [0, 2, 4, 6], atol=1e-6))
gq = chain([0, 1, 2, 3, 4], [0, 0, 0, 0, 16])
gq.set(POINT, "g", (np.arange(5, dtype=np.float32) ** 2)[:, None])
r = fill(gq, attribute="a", known_group="0 4", method="poisson", match_attribute="g")
check("Attribute to Match = x², boundary values also x² → the solution is x² (0 1 4 9 16)",
      np.allclose(av(r), [0, 1, 4, 9, 16], atol=1e-6), av(r))
gq.set(POINT, "wt", np.zeros((5, 1), np.float32))
r = fill(gq, attribute="a", known_group="0 4", method="poisson", match_attribute="g",
         weight_attribute="wt")
check("  Weight Attribute all 0 → doesn't follow the guide, same as not given (linear 0 4 8 12 16)",
      np.allclose(av(r), [0, 4, 8, 12, 16], atol=1e-6))
gq.set(POINT, "wt", np.full((5, 1), 3.0, np.float32))
r = fill(gq, attribute="a", known_group="0 4", method="poisson", match_attribute="g",
         weight_attribute="wt")
check("  Weight clamped to 0..1: all 3 same as all 1 (= x²)", np.allclose(av(r), [0, 1, 4, 9, 16], atol=1e-6))
gq.set(POINT, "wt", np.full((5, 1), 0.5, np.float32))
r = fill(gq, attribute="a", known_group="0 4", method="poisson", match_attribute="g",
         weight_attribute="wt")
exp = 0.5 * np.array([0, 4, 8, 12, 16]) + 0.5 * np.arange(5) ** 2
check("  Weight 0.5: half linear solution, half x² (the difference target is halved; on a 1D chain the solution is the average of the two)",
      np.allclose(av(r), exp, atol=1e-6), av(r))
g2 = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [5, 0, 0], [6, 0, 0]], np.float32),
                        [[0, 1, 2], [3, 4]], closed=False)
g2.set(POINT, "a", np.array([[2], [0], [4], [7], [7]], np.float32))
r = fill(g2, attribute="a", known_group="0 2", method="poisson")
check("  points not connected to the Boundary Group get the default 0 (old harmonic kept the original 7)",
      np.allclose(av(r), [2, 3, 4, 0, 0]) and
      np.allclose(av(fill(g2, attribute="a", known_group="0 2", method="harmonic")), [2, 3, 4, 7, 7]))
gv = chain([0, 1, 2], [0, 0, 0])
gv.set(POINT, "v3", np.array([[0, 0, 0], [0, 0, 0], [2, 4, 6]], np.float32))
gv.set(POINT, "g3", np.array([[0, 0, 0], [1, 0, 0], [0, 0, 0]], np.float32))
r = fill(gv, attribute="v3", known_group="0 2", method="poisson", match_attribute="g3")
check("  vector attributes solved per component; a 3-component Match maps per component (x component midpoint 1 + 1 = 2, y, z linear)",
      np.allclose(np.asarray(r[0].get(POINT, "v3"))[1], [2.0, 2, 3]), r[0].get(POINT, "v3")[1])
check("  Match component count mismatch → raises",
      raises(lambda: fill(gv, attribute="v3", known_group="0 2", method="poisson",
                          match_attribute="uv2"), "Attribute to Match")
      and raises(lambda: (gv.set(POINT, "g2", np.zeros((3, 2), np.float32)),
                          fill(gv, attribute="v3", known_group="0 2", method="poisson",
                               match_attribute="g2")), "components"))
gq.set(POINT, "wt", np.array([[1], [1], [0], [0], [0]], np.float32))
r = fill(gq, attribute="a", known_group="0 4", method="poisson", match_attribute="g",
         weight_attribute="wt")
# written separately: on unknown points 1..3 minimize Σ (x_i − x_j − ω_e (g_i − g_j))², ω_e = average Weight of the two ends
om_e = np.array([1.0, 0.5, 0.0, 0.0])
dgv = om_e * np.diff(np.arange(5.0) ** 2)
Am = np.zeros((4, 3))
bm = dgv.copy()
for e in range(4):
    for node_, sgn in ((e + 1, 1.0), (e, -1.0)):
        if node_ == 4:
            bm[e] -= sgn * 16.0
        elif node_ > 0:
            Am[e, node_ - 1] += sgn
exp = np.linalg.lstsq(Am, bm, rcond=None)[0]
check("  non-uniform Weight (1 1 0 0 0): edges take the average of both ends, matches the independent least-squares solution",
      np.allclose(av(r)[1:4], exp, atol=1e-6), (av(r)[1:4], exp))
glong = chain(np.arange(40.0), np.r_[0.0, np.zeros(38), 39.0])
r = fill(glong, attribute="a", known_group="0 39", method="poisson")
check("  40-point chain (conjugate gradient needs many iterations to converge) → linear to 1e-6",
      np.allclose(av(r), np.arange(40.0), atol=1e-6), np.abs(av(r) - np.arange(40)).max())
g15 = build.grid(3.0, 5.0, 15, 15)
P15 = P_(g15)
bd = (np.isclose(np.abs(P15[:, 0]), 1.5)) | (np.isclose(np.abs(P15[:, 2]), 2.5))
g15.set(POINT, "a", np.where(bd, np.random.default_rng(1).random(225), 0.0).astype(np.float32)[:, None])
g15.set_group(POINT, "bd", bd)
r = fill(g15, attribute="a", known_group="bd", method="poisson")
x = av(r)
from comfyui_pcg.geo.topology import topology            # noqa: E402
E15 = topology(g15).edge_points.astype(int)
w15 = 1.0 / np.linalg.norm(P15[E15[:, 0]] - P15[E15[:, 1]], axis=1)
res = np.zeros(225)
np.add.at(res, E15[:, 0], w15 * (x[E15[:, 0]] - x[E15[:, 1]]))
np.add.at(res, E15[:, 1], w15 * (x[E15[:, 1]] - x[E15[:, 0]]))
check("  15×15 grid, random boundary values: every interior point satisfies Σ w (x_i − x_j) = 0 (w = 1/edge length, residual < 1e-6)",
      np.abs(res[~bd]).max() < 1e-6 and np.allclose(x[bd], np.asarray(g15.get(POINT, "a"))[bd, 0]),
      np.abs(res[~bd]).max())
gmin = chain([0, 1e-4, 1], [0, 0, 1])
r1 = fill(gmin, attribute="a", known_group="0 2", method="poisson", min_edge_length=1e-6)
r2 = fill(gmin, attribute="a", known_group="0 2", method="poisson", min_edge_length=0.5)
check("Minimum Edge Length: the 0→1 edge of 1e-4 is treated as 0.5 → the midpoint goes from 1e-4 to 0.5/(0.5+0.9999)",
      abs(av(r1)[1] - 1e-4) < 1e-6 and abs(av(r2)[1] - 0.5 / (0.5 + 1 - 1e-4)) < 1e-5, (av(r1)[1], av(r2)[1]))

# ── Eikonal
ge = chain([0, 1, 3, 6])
r = fill(ge, attribute="T", known_group="0", method="eikonal")
check("Eikonal: accumulated edge length along edges 0 1 3 6 (attribute didn't exist, created)", np.allclose(av(r, "T"), [0, 1, 3, 6]))
ge.set(POINT, "spd", np.array([[1], [2], [1], [4]], np.float32))
r = fill(ge, attribute="T", known_group="0", method="eikonal", speed_attribute="spd")
check("  Speed is the speed leaving this point: 0→1 1/1, 1→2 2/2, 2→3 3/1 → 0 1 2 5",
      np.allclose(av(r, "T"), [0, 1, 2, 5]), av(r, "T"))
r = fill(ge, attribute="T", known_group="3", method="eikonal", speed_attribute="spd")
check("  reverse direction (source at 3): 3→2 3/4, 2→1 2/1, 1→0 1/2 → 5.25 … 0 (directional)",
      np.allclose(av(r, "T"), [3.25, 2.75, 0.75, 0]), av(r, "T"))
r = fill(g2, attribute="a", known_group="0", method="eikonal", unreachable_time=-5)
check("  unreachable points get Unreachable Time; input values aren't read (sources get 0)",
      np.allclose(av(r), [0, 1, 2, -5, -5]))
gg = build.grid(2.0, 2.0, 3, 3)
r = fill(gg, attribute="T", known_group="0", method="eikonal")
d = av(r, "T")
check("  on a grid it's distance along edges (diagonal point = 2, not √2 -- the combinatorial version, not Fast Marching)",
      np.isclose(d[8], 4.0) and np.isclose(d[4], 2.0), d.tolist())
gsp = chain([0, 1, 2])
gsp.set(POINT, "spd", np.array([[0], [1], [1]], np.float32))
r = fill(gsp, attribute="T", known_group="0", method="eikonal", speed_attribute="spd",
         min_speed=0.5)
check("  Speed 0 clamped to Minimum Speed 0.5 → 0→1 takes 2", np.allclose(av(r, "T"), [0, 2, 3]))
check("  Eikonal without a group → raises", raises(lambda: fill(ge, attribute="T", method="eikonal"),
                                     "Eikonal needs a"))
gvec = chain([0, 1, 2])
gvec.set(POINT, "T", np.zeros((3, 3), np.float32))
r = fill(gvec, attribute="T", known_group="0", method="eikonal")
check("  existing 3-component attribute: the same time written to every component",
      np.asarray(r[0].get(POINT, "T")).shape == (3, 3)
      and np.allclose(np.asarray(r[0].get(POINT, "T")), np.repeat([[0], [1], [2]], 3, 1)))

# ── Diffusion
g2p = chain([0, 1], [1, 0])
for t in (0.5, 2.0):
    r = fill(g2p, attribute="a", method="diffusion", diffusion_time=t)
    d_ = 1.0 / (1.0 + 2.0 * t)
    check(f"Diffusion two points, no source, t = {t}: one implicit step → difference 1/(1+2t), total conserved",
          np.allclose(av(r), [(1 + d_) / 2, (1 - d_) / 2], atol=1e-9), av(r))
r = fill(g2p, attribute="a", method="diffusion", diffusion_time=2.0, known_group="0")
check("  point 0 is a source (fixed): x1 = t/(1+t) = 2/3", np.allclose(av(r), [1, 2 / 3], atol=1e-9))
g2s = chain([0, 2], [1, 0])
r = fill(g2s, attribute="a", method="diffusion", diffusion_time=2.0, known_group="0")
check("  edge length 2: rate / edge length² = 1/4 → x1 = 0.5/1.5", np.allclose(av(r)[1], 0.5 / 1.5, atol=1e-9))
g2p.set(POINT, "spd", np.array([[1], [3]], np.float32))
r = fill(g2p, attribute="a", method="diffusion", diffusion_time=1.0, known_group="0",
         speed_attribute="spd")
check("  Speed: edge rate is the average of both ends 2 → x1 = 2/3", np.allclose(av(r)[1], 2 / 3, atol=1e-9))
g2p.set(POINT, "spd", np.array([[0], [0]], np.float32))
r = fill(g2p, attribute="a", method="diffusion", diffusion_time=1.0, known_group="0",
         speed_attribute="spd", min_speed=0.25)
check("  Speed 0 clamped to Minimum Speed 0.25 → x1 = 0.25/1.25", np.allclose(av(r)[1], 0.2, atol=1e-9))
r = fill(g2p, attribute="a", method="diffusion", diffusion_time=0.0)
check("  Diffusion Time 0 → unchanged", np.allclose(av(r), [1, 0]))

# ── Extrapolate
gf = build.grid(4.0, 4.0, 5, 5)
gf.set(POINT, "v", np.where(np.arange(25)[:, None] % 6 == 0, 1.0 + np.arange(25)[:, None], 0.0).astype(np.float32)
       * np.array([[1.0, 2.0, 0.5]], np.float32))
r = fill(gf, attribute="v", method="extrapolate")
r0 = fill(gf, attribute="v", method="nearest")
check("Extrapolate · Scalar = value of the nearest source point along edges (matches the old nearest)",
      np.allclose(np.asarray(r[0].get(POINT, "v")), np.asarray(r0[0].get(POINT, "v"))))


def folded():
    """A strip folded at a right angle: ground x = −2, −1, fold line x = 0, wall y = 1, 2 (two rows z = 0, 1)."""
    pos = [(-2, 0), (-1, 0), (0, 0), (0, 1), (0, 2)]
    P = np.array([[x, y, z] for (x, y) in pos for z in (0, 1)], np.float32)
    faces = [[2 * i, 2 * i + 1, 2 * i + 3, 2 * i + 2] for i in range(4)]
    g = Geometry.from_mesh(P, faces)
    return ops.compute_normals(g, "point")


gfo = folded()
N = np.asarray(gfo.get(POINT, "N"), np.float64)
V0 = np.zeros((10, 3), np.float32)
V0[:2] = [1, 0, 0]
gfo.set(POINT, "dir", V0)
r = fill(gfo, attribute="dir", known_group="0 1", method="extrapolate",
         extrapolation="parallel_transport")
Vt = np.asarray(r[0].get(POINT, "dir"), np.float64)
check("Parallel Transport: (1,0,0) on the ground pointing at the fold becomes (0,1,0) on the wall after the right-angle fold (up the wall)",
      np.allclose(Vt[6:], [0, 1, 0], atol=1e-6) and np.allclose(Vt[2:4], [1, 0, 0], atol=1e-6),
      Vt.round(3).tolist())
check("  negative control: Scalar is still (1,0,0) on the wall",
      np.allclose(np.asarray(fill(gfo, attribute="dir", known_group="0 1", method="extrapolate")[0]
                             .get(POINT, "dir"))[6:], [1, 0, 0]))
check("  points on the fold (normal is the average of the two faces) rotated halfway: (1,1,0)/√2",
      np.allclose(Vt[4:6], np.array([1, 1, 0]) / np.sqrt(2), atol=1e-6))
V1 = V0.copy()
V1[:2] = [1, 0.5, 0]
gfo.set(POINT, "dir", V1)
r = fill(gfo, attribute="dir", known_group="0 1", method="extrapolate",
         extrapolation="parallel_transport", tangential_only=True)
Vt = np.asarray(r[0].get(POINT, "dir"), np.float64)
check("  Tangential Only: normal component removed (ground (1,0,0), wall (0,1,0)); sources keep their values",
      np.allclose(Vt[2:4], [1, 0, 0], atol=1e-6) and np.allclose(Vt[6:], [0, 1, 0], atol=1e-6)
      and np.allclose(Vt[:2], [1, 0.5, 0]))
r = fill(gfo, attribute="dir", known_group="0 1", method="extrapolate",
         extrapolation="parallel_transport", tangential_only=False)
Vt = np.asarray(r[0].get(POINT, "dir"), np.float64)
nc = float(np.asarray(V1[0], np.float64) @ N[0])
check("  Tangential Only off: normal component copied as Scalar (the source's v·N multiplied onto this point's normal)",
      np.allclose(Vt[6:], np.array([0, 1, 0]) + nc * N[6:], atol=1e-6), Vt[6:].round(3).tolist())
gfo.set(POINT, "dir", V0)
r = fill(gfo, attribute="dir", known_group="0 1", method="extrapolate",
         extrapolation="parallel_transport", global_rotation=90.0)
Vt = np.asarray(r[0].get(POINT, "dir"), np.float64)
check("  Global Rotation 90°: tangent rotated 90° about this point's normal (= N × v); sources not rotated",
      np.allclose(Vt[2:4], np.cross(N[2:4], [1, 0, 0]), atol=1e-6)
      and np.allclose(Vt[6:], np.cross(N[6:], [0, 1, 0]), atol=1e-6) and np.allclose(Vt[:2], [1, 0, 0]))
V2 = V0.copy()
V2[:2] = [1, 0, 1]
gfo.set(POINT, "dir", V2)
r = fill(gfo, attribute="dir", known_group="0 1", method="extrapolate",
         extrapolation="parallel_transport")
Vt = np.asarray(r[0].get(POINT, "dir"), np.float64)
check("  (1,0,1) with a component along the fold: the z component along the fold unchanged → (0,1,1) on the wall",
      np.allclose(Vt[6:], [0, 1, 1], atol=1e-6), Vt[6:].round(3).tolist())


def folded_rev():
    """The same folded strip with point numbers reversed (top of the wall is points 0, 1) -- processing order can't follow point numbers."""
    g = folded()
    P = np.asarray(g.get(POINT, "P"))[::-1].copy()
    faces = [[9 - 2 * i, 9 - (2 * i + 1), 9 - (2 * i + 3), 9 - (2 * i + 2)] for i in range(4)]
    return ops.compute_normals(Geometry.from_mesh(P, faces), "point")


gr_ = folded_rev()
Vr = np.zeros((10, 3), np.float32)
Vr[8:] = [1, 0, 0]                                          # the farthest ground row (8, 9 after reversing)
gr_.set(POINT, "dir", Vr)
r = fill(gr_, attribute="dir", known_group="8 9", method="extrapolate",
         extrapolation="parallel_transport")
Vt = np.asarray(r[0].get(POINT, "dir"), np.float64)
check("  reversed point numbers: sources at 8, 9, wall top 0, 1 is still (0,1,0) (processed by shortest-path tree depth)",
      np.allclose(Vt[:4], [0, 1, 0], atol=1e-6), Vt.round(3).tolist())
gfo.set(POINT, "s1", np.arange(10, dtype=np.float32)[:, None])
check("  Parallel Transport on a scalar → raises",
      raises(lambda: fill(gfo, attribute="s1", known_group="0", method="extrapolate",
                          extrapolation="parallel_transport"), "3-component"))
check("  unknown Extrapolation Type → raises", raises(lambda: fill(gfo, attribute="s1", extrapolation="x"),
                                             "Extrapolation"))


# ═══════════════════════════════════════════════════════════════ Attribute Fade (by time)
sec("Attribute Fade · Time (new node PCG_AttribFadeTime)")
AF = "PCG_AttribFadeTime"


def fd(geo, **kw):
    return call(AF, geo=geo, **kw)


g5 = pts_line(5)
g5.set(POINT, "fadestart", np.array([[0], [5], [10], [20], [100]], np.float32))
r = fd(g5, frame=12, fade_in=4, fade_hold=6, fade_out=4)
check("t = 12 7 2 −8 −88 (in 4, hold 6, out 4) → halfway faded out 0.5, hold 1, halfway faded in 0.5, not started 0, 0; "
      "missing attribute treated as 1", np.allclose(av(r, "fade"), [0.5, 1, 0.5, 0, 0]), av(r, "fade"))
check("  report: 2 fading, 1 full, 2 at 0", json.loads(r[1]) == {"points": 5, "zero": 2, "full": 1, "fading": 2})
g5b = g5.copy()
g5b.set(POINT, "fade", np.array([[2], [2], [2], [2], [2]], np.float32))
r = fd(g5b, frame=12, fade_in=4, fade_hold=6, fade_out=4)
check("  existing attribute: original × fade (2 → 1 2 1 0 0)", np.allclose(av(r, "fade"), [1, 2, 1, 0, 0]))
r = fd(g5, frame=10, fade_in=4, fade_hold=6, fade_out=4)
check("  segment boundaries: t = 10 = in + hold → fade-out start 1; t = 5 → hold; t = 0 → fade-in start 0",
      np.allclose(av(r, "fade")[:3], [1, 1, 0]))
r = fd(g5, frame=14, fade_in=4, fade_hold=6, fade_out=4)
check("  t = 14 = total length → 0 (already faded out)", av(r, "fade")[0] == 0)
r = fd(g5, frame=12, fade_in=4, fade_hold=6, fade_out=4, frame_offset=-4)
check("Frame Offset −4 (= −Fade In): everything 4 frames earlier → t = 16 11 6 −4 → 0 0.75 1 0 0",
      np.allclose(av(r, "fade"), [0, 0.75, 1, 0, 0]), av(r, "fade"))
gs_ = pts_line(3)
gs_.set(POINT, "fadestart", np.array([[0], [0.25], [1]], np.float32))
r = fd(gs_, frame=12, fade_in=12, fade_hold=0, fade_out=12, start_retime=24)
check("Start Frame Retime 24 (attribute in seconds): start frames 0 6 24 → t = 12 6 −12 → 1 0.5 0",
      np.allclose(av(r, "fade"), [1, 0.5, 0]), av(r, "fade"))
g5h = g5.copy()
g5h.set(POINT, "holdscale", np.array([[2], [1], [1], [1], [1]], np.float32))
r = fd(g5h, frame=12, fade_in=4, fade_hold=6, fade_out=4)
check("Hold Frame Scale 2: point 0 holds 12 frames → at t = 12 still holding (1)", np.allclose(av(r, "fade")[:3], [1, 1, 0.5]))
gsrc = pts_line(5)
gsrc.set(POINT, "fadestart", np.array([[12], [12], [12], [12], [12]], np.float32))
r = fd(g5, start_geo=gsrc, frame=12, fade_in=4, fade_hold=6, fade_out=4)
check("second input connected: Fade Start Frame read from it (all 12 → t = 0 → all 0)", np.allclose(av(r, "fade"), 0))
ghs = pts_line(5)
ghs.set(POINT, "holdscale", np.full((5, 1), 0.0, np.float32))
r = fd(g5, hold_geo=ghs, frame=7, fade_in=4, fade_hold=6, fade_out=4, start_attribute="fadestart")
check("third input connected: Hold Frame Scale read from it (0 → no hold segment, t = 7 2 → 3/4 into fade-out 0.25, halfway into fade-in 0.5)",
      np.allclose(av(r, "fade")[:2], [0.25, 0.5]), av(r, "fade"))
g3s = pts_line(3)
g3s.set(POINT, "fadestart", np.zeros((3, 1), np.float32))
check("  second input with a different point count → raises", raises(lambda: fd(g5, start_geo=g3s), "correspond by point number"))
check("  attribute missing on the second input → start frame 0 (docs: 0 if missing; doesn't fall back to the first input)",
      np.allclose(av(fd(g5, start_geo=pts_line(5), frame=2, fade_in=4), "fade"), 0.5))
gstr2 = pts_line(5)
gstr2.set_string(POINT, "fadestart", np.array([["a"]] * 5))
check("  Fade Start Frame is a string → raises", raises(lambda: fd(g5, start_geo=gstr2), "a numeric one is required"))
r = fd(g5, frame=12, fade_in=4, fade_hold=6, fade_out=4, fade_in_ramp_mode="smooth")
check("Fade In Ramp interpolation smooth: t/in = 0.5 → 0.5; at another point t/in = 0.25 → smoothstep = 0.15625",
      np.isclose(av(r, "fade")[2], 0.5)
      and np.isclose(av(fd(g5, frame=11, fade_in=4, fade_in_ramp_mode="smooth"), "fade")[2], 0.15625))
r = fd(g5, frame=12, fade_in=4, fade_hold=6, fade_out=4, fade_in_ramp="0:0 0.5:1 1:1",
       fade_out_ramp="0:1 0.5:0.2 1:0")
check("custom ramp: fade in 0:0 0.5:1 → already 1 at halfway; 0.2 at halfway through fade-out",
      np.allclose(av(r, "fade")[[0, 2]], [0.2, 1.0]))
gb = pts_line(4)
gb.set(POINT, "fadestart", np.array([[0], [-4], [-10], [-14]], np.float32))
r = fd(gb, frame=0, fade_in=4, fade_hold=6, fade_out=4, fade_in_ramp="0:0.3 1:0.8",
       fade_out_ramp="0:0.6 1:0.4")
check("segment boundaries made visible with ramps that don't end at 0/1: t = 0 → fade-in ramp(0) = 0.3; t = in → hold 1; "
      "t = in + hold → fade-out ramp(0) = 0.6; t = total length → 0 (not ramp(1) = 0.4)",
      np.allclose(av(r, "fade"), [0.3, 1.0, 0.6, 0.0]), av(r, "fade"))
gneg = pts_line(1)
gneg.set(POINT, "holdscale", np.array([[-1]], np.float32))
r = fd(gneg, frame=6, fade_in=4, fade_hold=6, fade_out=4)
check("  negative Hold Frame Scale → hold duration counted as 0 (t = 6 → halfway faded out 0.5)", np.isclose(av(r, "fade")[0], 0.5))
r = fd(g5, frame=0.0, fade_in=0, fade_hold=6, fade_out=4)
check("Fade In Frames 0: t = 0 is directly 1 (no fade-in segment)", av(r, "fade")[0] == 1)
r = fd(g5b, frame=12, fade_in=4, fade_hold=6, fade_out=4, group="0 1")
check("Point Group: only points in the group change, the rest keep the original value 2", np.allclose(av(r, "fade"), [1, 2, 2, 2, 2]))
r = fd(g5, frame=12, fade_in=4, fade_hold=6, fade_out=4, group="0-2")
check("  attribute didn't exist: points outside the group are 1", np.allclose(av(r, "fade"), [0.5, 1, 0.5, 1, 1]))
r = fd(g5, frame=12, fade_in=4, fade_hold=6, fade_out=4, visualize=True)
Cd = np.asarray(r[0].get(POINT, "Cd"))
check("Visualize Fade: Cd = (f, f, f); off doesn't write Cd",
      np.allclose(Cd, np.repeat(av(r, "fade")[:, None], 3, 1))
      and fd(g5, frame=12)[0].get(POINT, "Cd") is None)
g5c = g5.copy()
g5c.set(POINT, "Cd", np.tile(np.array([[0.2, 0.4, 0.6]], np.float32), (5, 1)))
r = fd(g5c, frame=12, fade_in=4, fade_hold=6, fade_out=4, visualize=True, group="0 1")
check("  Visualize + Group: points outside the group keep their original Cd",
      np.allclose(np.asarray(r[0].get(POINT, "Cd"))[2:], [0.2, 0.4, 0.6])
      and np.allclose(np.asarray(r[0].get(POINT, "Cd"))[0], 0.5))
gst = pts_line(2)
gst.set_string(POINT, "fade", np.array([["a"], ["b"]]))
check("  string attribute → raises", raises(lambda: fd(gst), "is a string"))
check("  no fadestart attribute → start frame 0", np.allclose(av(fd(pts_line(2), frame=2, fade_in=4), "fade"), 0.5))
check("  unknown interpolation → raises", raises(lambda: fd(g5, fade_out_ramp_mode="x"), "interpolation"))


# ═══════════════════════════════════════════════════════════════ Attribute Transform Extract(KineFX)
sec("Attribute Transform Extract · Houdini (new node PCG_AttribTransformExtractHou)")
XT = "PCG_AttribTransformExtractHou"
from comfyui_pcg.geo import xformextract as XE          # noqa: E402


def xt(geo, **kw):
    return call(XT, geo=geo, **kw)


def plug(H4):
    """
    Houdini row-vector 4×4 → this plugin's storage, 16 components. Since pcg102 this plugin's transform attribute uses the
    Houdini convention (it used to be a mixed layout: 3×3 transposed, translation in row 4), stored as is.
    """
    return np.array(H4, np.float64).reshape(-1)


def mat_pts(Hs, n_comp=16):
    g = pts_line(len(Hs))
    a = np.array([plug(H) for H in Hs])
    if n_comp == 9:
        a = a.reshape(-1, 4, 4)[:, :3, :3].reshape(-1, 9)
    g.set(POINT, "transform", a.astype(np.float32))
    return g


def pv(g, name):
    return np.asarray(g.get(POINT, name), np.float64)


# ── convention: this plugin's Transform by Attribute transforms with this matrix, consistent with Transform SOP with the same parameters
T0, R0, S0, SH0 = (1.0, -2.0, 0.5), (30.0, -20.0, 45.0), (1.5, 0.75, 2.0), (0.2, -0.1, 0.3)
H0 = ops.xform_matrix(T0, R0, S0, SH0, 1.0, (0, 0, 0), (0, 0, 0), "srt", "xyz")
box = build.box((1, 1, 1), (0.3, 0.1, -0.2), (2, 2, 2))
bx = box.copy()
bx.set(POINT, "transform", np.tile(plug(H0), (bx.npoints, 1)).astype(np.float32))
via_attr = run("PCG_TransformByAttrib", geo=bx, attribute="transform", attribute_class="point")
via_xf = ops.transform(box, T0, R0, S0, shear=SH0)
check("matrix convention: Houdini row-vector storage (pcg102), Transform by Attribute result = Transform SOP with the same parameters",
      np.allclose(P_(via_attr), P_(via_xf), atol=1e-5))
r = xt(mat_pts([H0]), decomposition="crack")
check("Crack Transform: decomposes back into Translate / Rotate / Scale / Shear (xyz, srt)",
      np.allclose(pv(r[0], "transform_t")[0], T0, atol=1e-5)
      and np.allclose(pv(r[0], "transform_r")[0], R0, atol=1e-3)
      and np.allclose(pv(r[0], "transform_s")[0], S0, atol=1e-5)
      and np.allclose(pv(r[0], "transform_sh")[0], SH0, atol=1e-5),
      [pv(r[0], k)[0].round(4).tolist() for k in ("transform_t", "transform_r", "transform_s", "transform_sh")])
rng_ = np.random.default_rng(7)
bad = []
for xo in ops.XFORM_ORDERS:
    for ro in ops.ROTATE_ORDERS:
        t_ = rng_.normal(size=3)
        r_ = rng_.uniform(-80, 80, 3)
        s_ = rng_.uniform(0.4, 2.0, 3)
        h_ = rng_.normal(size=3) * 0.3
        H = ops.xform_matrix(t_, r_, s_, h_, 1.0, (0, 0, 0), (0, 0, 0), xo, ro)
        o = xt(mat_pts([H]), decomposition="crack", xform_order=xo, rotate_order=ro)[0]
        got = [pv(o, k)[0] for k in ("transform_t", "transform_r", "transform_s", "transform_sh")]
        if not all(np.allclose(g_, e_, atol=a_) for g_, e_, a_ in
                   zip(got, (t_, r_, s_, h_), (1e-4, 1e-3, 1e-4, 1e-4))):
            bad.append((xo, ro))
check("  6 Transform Orders × 6 Rotation Orders (random parameters): all decompose back to the original parameters", not bad, bad)
Hm = ops.xform_matrix((0, 0, 0), (10, 20, 30), (1, -2, 1), (0, 0, 0), 1.0, (0, 0, 0), (0, 0, 0), "srt", "xyz")
o = xt(mat_pts([Hm]), decomposition="crack")[0]
Hb = ops.xform_matrix(pv(o, "transform_t")[0], pv(o, "transform_r")[0], pv(o, "transform_s")[0],
                      pv(o, "transform_sh")[0], 1.0, (0, 0, 0), (0, 0, 0), "srt", "xyz")
check("  a mirrored matrix (one negative scale): the mirror goes into one scale component, recomposes to the same matrix",
      np.allclose(Hb, Hm, atol=1e-5) and (pv(o, "transform_s")[0] < 0).sum() == 1)
Hm2 = ops.xform_matrix((0, 0, 0), (10, 20, 30), (1, -2, 1), (0.1, 0.2, 0.3), 1.0, (0, 0, 0), (0, 0, 0),
                       "rts", "xyz")
o = xt(mat_pts([Hm2]), decomposition="crack", xform_order="rts")[0]
Hb = ops.xform_matrix(pv(o, "transform_t")[0], pv(o, "transform_r")[0], pv(o, "transform_s")[0],
                      pv(o, "transform_sh")[0], 1.0, (0, 0, 0), (0, 0, 0), "rts", "xyz")
check("  orders with R before S + mirror: also recompose to the original matrix", np.allclose(Hb, Hm2, atol=1e-5))
o = xt(mat_pts([H0]), decomposition="crack", xform_order="trs")[0]
check("  negative control: the wrong Transform Order (trs) gives a different translation", not np.allclose(pv(o, "transform_t")[0], T0, atol=1e-3))

# ── Polar
Rr = ops.euler_matrix(25, -40, 70).astype(np.float64)       # column vectors
St = np.array([[2.0, 0.3, 0.1], [0.3, 1.0, -0.2], [0.1, -0.2, 0.5]])
Hp = np.eye(4)
Hp[:3, :3] = St @ Rr.T                                      # row vectors: stretch first, then rotate
Hp[3, :3] = (4, 5, 6)
o = xt(mat_pts([Hp]))[0]
check("Polar Decomposition: H3 = Stretch · R, gives a symmetric Stretch (9 components), rotation, translation (row 4)",
      np.allclose(pv(o, "transform_stretch")[0].reshape(3, 3), St, atol=1e-5)
      and np.allclose(pv(o, "transform_r")[0], (25, -40, 70), atol=1e-3)
      and np.allclose(pv(o, "transform_t")[0], (4, 5, 6))
      and o.get(POINT, "transform_s") is None)
Hpm = Hp.copy()
Hpm[:3, :3] = np.diag([1.0, 1.0, -1.0]) @ St @ Rr.T
o = xt(mat_pts([Hpm]))[0]
Rb = ops.euler_matrix(*pv(o, "transform_r")[0]).astype(np.float64).T
Sb = pv(o, "transform_stretch")[0].reshape(3, 3)
check("  mirrored matrix: rotation is still a proper rotation, the mirror goes into Stretch (Stretch · R recomposes to the original matrix)",
      np.allclose(Sb @ Rb, Hpm[:3, :3], atol=1e-5) and np.allclose(Sb, Sb.T, atol=1e-6))
o9 = xt(mat_pts([Hp], 9))[0]
check("  9-component matrix: no translation written (docs: translation only for 4×4)", o9.get(POINT, "transform_t") is None
      and np.allclose(pv(o9, "transform_r")[0], (25, -40, 70), atol=1e-3))
o = xt(mat_pts([Hp]), xform_order="trs")[0]
check("  Polar ignores Transform Order (translation still in row 4)", np.allclose(pv(o, "transform_t")[0], (4, 5, 6)))

# ── Euler angles / filtering
bad = []
for ro in ops.ROTATE_ORDERS:
    for _ in range(5):
        a_ = rng_.uniform(-170, 170, 3)
        a_[{"x": 0, "y": 1, "z": 2}[ro[1]]] = rng_.uniform(-85, 85)
        E = ops.euler_matrix(*a_, order=ro).astype(np.float64)[None]
        e = XE.matrix_to_euler(E, ro)[0]
        alt = XE._alt_euler(e[None], ro)[0]
        if not (np.allclose(e, a_, atol=1e-3)
                and np.allclose(ops.euler_matrix(*alt, order=ro), E[0], atol=1e-5)):
            bad.append(ro)
check("matrix_to_euler is the inverse of euler_matrix (middle axis |angle| < 90°); the other solution is the same rotation too", not bad, bad)
Hx = lambda ang, ax="x": ops.xform_matrix((0, 0, 0), [ang if c == ax else 0 for c in "xyz"],  # noqa: E731
                                          (1, 1, 1), (0, 0, 0), 1.0, (0, 0, 0), (0, 0, 0), "srt", "xyz")
o = xt(mat_pts([Hx(350)]))[0]
check("Hint (0,0,0): 350° becomes −10°", np.allclose(pv(o, "transform_r")[0], (-10, 0, 0), atol=1e-3))
o = xt(mat_pts([Hx(350)]), hint_x=300.0)[0]
check("  Hint x = 300: takes 350° (adds multiples of 360° and picks the nearest)", np.allclose(pv(o, "transform_r")[0], (350, 0, 0), atol=1e-3))
Ha = ops.xform_matrix((0, 0, 0), (170, 10, 0), (1, 1, 1), (0, 0, 0), 1.0, (0, 0, 0), (0, 0, 0), "srt", "xyz")
o = xt(mat_pts([Ha]), hint_x=-10.0, hint_y=170.0, hint_z=180.0)[0]
check("  Hint close to the other solution (−10, 170, 180): takes that one", np.allclose(pv(o, "transform_r")[0], (-10, 170, 180), atol=1e-3),
      pv(o, "transform_r")[0])
angs = [0, 100, 200, 300, 400, 500]
gz = mat_pts([Hx(a_, "z") for a_ in angs])
lines = Geometry.from_mesh(P_(gz).astype(np.float32), [list(range(6))], closed=False)
lines.set(POINT, "transform", gz.get(POINT, "transform"))
o = xt(lines, hierarchy="topology")[0]
check("Hierarchy Topology: parent-child filtering along the line, rotation about z 0 100 200 300 400 500 continuous (doesn't jump back to −160)",
      np.allclose(pv(o, "transform_r")[:, 2], angs, atol=1e-3), pv(o, "transform_r")[:, 2].round(2))
o = xt(lines, hierarchy="none")[0]
check("  negative control None: each point nearest the Hint on its own → 0 100 −160 −60 40 140",
      np.allclose(pv(o, "transform_r")[:, 2], [0, 100, -160, -60, 40, 140], atol=1e-3))
lr = Geometry.from_mesh(P_(gz).astype(np.float32), [list(range(6))[::-1]], closed=False)
lr.set(POINT, "transform", gz.get(POINT, "transform"))
o = xt(lr, hierarchy="topology")[0]
check("  line running backwards (point 5 is the root): continuous back from 140 → 500 400 300 200 100 0 minus 360",
      np.allclose(pv(o, "transform_r")[:, 2], np.array(angs) - 360, atol=1e-3), pv(o, "transform_r")[:, 2].round(2))
lc = Geometry.from_mesh(P_(gz).astype(np.float32), [list(range(6))], closed=True)
lc.set(POINT, "transform", gz.get(POINT, "transform"))
o = xt(lc, hierarchy="topology")
check("  closed line: start and end don't form a cycle (point 0 is still the root), same result as an open line",
      np.allclose(pv(o[0], "transform_r")[:, 2], angs, atol=1e-3) and json.loads(o[1])["roots"] == 1)
g4b = mat_pts([Hx(a_, "z") for a_ in (0, 200, 300, 160)])
lsh = Geometry.from_mesh(P_(g4b).astype(np.float32), [[0, 1, 2], [3, 1]], closed=False)
lsh.set(POINT, "transform", g4b.get(POINT, "transform"))
o = xt(lsh, hierarchy="topology")[0]
check("  a point on two lines (1 is on 0-1-2 and 3-1): the parent is the first occurrence (0) → 0 −160 −60 160"
      " (if 3 took it, it would be 200 300)",
      np.allclose(pv(o, "transform_r")[:, 2], [0, -160, -60, 160], atol=1e-3), pv(o, "transform_r")[:, 2])
g4 = mat_pts([Hx(a_, "z") for a_ in (0, 100, 200, 300)])
lcy = Geometry.from_mesh(P_(g4).astype(np.float32), [[0, 1], [1, 0], [2, 3]], closed=False)
lcy.set(POINT, "transform", g4.get(POINT, "transform"))
o = xt(lcy, hierarchy="topology")
check("  two lines 0-1, 1-0 are each other's parents, forming a cycle: broken, no infinite loop (two roots: the chain of 0 + point 2)",
      json.loads(o[1])["roots"] == 2
      and np.allclose(pv(o[0], "transform_r")[:, 2], [0, 100, -160, -60], atol=1e-3),
      (json.loads(o[1]), pv(o[0], "transform_r")[:, 2]))
o = xt(lines, hierarchy="topology", group="0 1 3 4 5")[0]
check("  Topology + Group: 2 not in the group, 3 becomes a root (by Hint → −60), 4, 5 follow it → 0 100 _ −60 40 140",
      np.allclose(pv(o, "transform_r")[[0, 1, 3, 4, 5], 2], [0, 100, -60, 40, 140], atol=1e-3),
      pv(o, "transform_r")[:, 2])
o = xt(gz, hierarchy="topology")[0]
check("  point cloud without lines: Topology finds no hierarchy → same as None",
      np.allclose(pv(o, "transform_r")[:, 2], [0, 100, -160, -60, 40, 140], atol=1e-3))
gpc = mat_pts([Hx(a_, "z") for a_ in (0, 0, 100, 100, 200, 200, 300, 300)])
gpc.set(POINT, "pc", np.array([[0], [1]] * 4, np.int32))
o = xt(gpc, hierarchy="pieces_points", piece_attribute="pc")[0]
check("Pieces or Points: two interleaved pieces, each filtered by point number on its own (0 100 200 300 twice each)",
      np.allclose(pv(o, "transform_r")[:, 2], [0, 0, 100, 100, 200, 200, 300, 300], atol=1e-3))
gpc.set_string(POINT, "nm", np.array([["a"], ["b"]] * 4))
o = xt(gpc, hierarchy="pieces_points", piece_attribute="nm")[0]
check("  string piece attribute works too", np.allclose(pv(o, "transform_r")[:, 2], [0, 0, 100, 100, 200, 200, 300, 300], atol=1e-3))
g1p = mat_pts([Hx(a_, "z") for a_ in (0, 100, 200, 300)])
g1p.set(POINT, "fl", np.array([[0.5], [1.5], [0.5], [1.5]], np.float32))
o = xt(g1p, hierarchy="pieces_points", piece_attribute="fl")[0]
check("  float piece attribute is invalid → all one piece (docs), continuous by point number 0 100 200 300",
      np.allclose(pv(o, "transform_r")[:, 2], [0, 100, 200, 300], atol=1e-3))
o = xt(g1p, hierarchy="pieces_points", piece_attribute="nope")[0]
check("  piece attribute doesn't exist → all one piece", np.allclose(pv(o, "transform_r")[:, 2], [0, 100, 200, 300], atol=1e-3))

# ── Group / names / errors
o = xt(g1p, hierarchy="pieces_points", group="0 1 3", decomposition="crack")
oo = o[0]
check("Group: points outside the group get defaults (rotation 0, scale 1); the hierarchy only links within the group (3's parent is 1 → 300 − 360 = −60 is closer to 100)",
      np.allclose(pv(oo, "transform_r")[:, 2], [0, 100, 0, -60], atol=1e-3)
      and np.allclose(pv(oo, "transform_s")[2], 1.0) and json.loads(o[1])["points"] == 3)
gtwo = mat_pts([H0])
gtwo.set(POINT, "localtransform", np.asarray(gtwo.get(POINT, "transform"))[:, :9].copy())
o = xt(gtwo, attributes="*transform", r_prefix="_", r_suffix="_rot", t_prefix="T_", t_suffix="")
check("Attributes wildcard + prefix / suffix: both matrices decomposed (_localtransform_rot, _transform_rot, T_transform)",
      set(json.loads(o[1])["written"]) == {"_localtransform_rot", "localtransform_stretch",
                                           "T_transform", "_transform_rot", "transform_stretch"},
      json.loads(o[1])["written"])
o = xt(pts_line(2))
check("  no matching matrix attribute → returned as is (Houdini does nothing either), with a warning in the report",
      digest(o[0]) == digest(pts_line(2)) and "matrix attribute" in json.loads(o[1])["warning"])
check("  unknown Hierarchy / Decomposition / Order → raises",
      raises(lambda: xt(gtwo, hierarchy="x"), "Hierarchy") and raises(lambda: xt(gtwo, decomposition="x"), "Decomposition")
      and raises(lambda: xt(gtwo, rotate_order="abc"), "Rotation Order")
      and raises(lambda: xt(gtwo, xform_order="abc"), "Transform Order"))


# ═══════════════════════════════════════════════════════════════ Name
sec("Name (new node PCG_Name)")
NMS = "PCG_Name"


def nmr(geo, **kw):
    return call(NMS, geo=geo, **kw)


gn = build.grid(3.0, 3.0, 4, 4)                         # 9 prims
gn.set_group(PRIM, "left", np.isin(np.arange(9), [0, 3, 6]))
gn.set_group(PRIM, "mid", np.isin(np.arange(9), [1, 4, 7]))
gn.set_group(PRIM, "mat_red", np.isin(np.arange(9), [6, 7, 8]))
r = nmr(gn, namings="left : rock\nmid : tree")
check("Namings: group → name; unnamed prims are empty strings", col(r[0], "name", PRIM) ==
      ["rock", "tree", "", "rock", "tree", "", "rock", "tree", ""])
check("  report: 2 entries, 6 prims", json.loads(r[1]) == {"namings": 2, "named": 6})
r = nmr(gn, namings="left : rock\nmat_red : red")
check("  overlapping groups: later entries overwrite earlier ones (prim 6 = red)", col(r[0], "name", PRIM)[6] == "red"
      and col(r[0], "name", PRIM)[0] == "rock")
r = nmr(gn, namings="left : rock\n# mid : tree\n\n0-1 : x")
check("  leading # = Enable off; groups can be numbers (0-1)", col(r[0], "name", PRIM)[:5] == ["x", "x", "", "rock", ""])
r = nmr(gn, namings=" : all")
check("  empty group = all", set(col(r[0], "name", PRIM)) == {"all"})
gn2 = gn.copy()
gn2.set_string(PRIM, "name", np.array([["old"]] * 9))
r = nmr(gn2, namings="mid : tree")
check("  existing name: unnamed ones keep their original value", col(r[0], "name", PRIM)[:3] == ["old", "tree", "old"])
r = nmr(gn, name_from_group=True, group_mask="left mid")
check("Name from Group: named after the group it belongs to (Group Mask uses only left, mid)",
      col(r[0], "name", PRIM) == ["left", "mid", "", "left", "mid", "", "left", "mid", ""])
r = nmr(gn, name_from_group=True, group_mask="*", namings="left : rock")
check("  Mask *: all three groups used; on overlap, later in lexicographic group-name order wins (left < mat_red < mid)"
      "; when on, Namings isn't read", col(r[0], "name", PRIM) ==
      ["left", "mid", "", "left", "mid", "", "mat_red", "mid", "mat_red"], col(r[0], "name", PRIM))
r = nmr(gn, name_from_group=True, group_mask="mat_*")
check("  Mask wildcard mat_*", col(r[0], "name", PRIM) == [""] * 6 + ["mat_red"] * 3)
gs3 = gn.copy()
gs3.set_string(PRIM, "name", np.array([["piece_a_piece"]] * 9))
r = nmr(gs3, from_="piece", to="chunk")
check("String Editing: Global on → replace all (chunk_a_chunk)", set(col(r[0], "name", PRIM)) == {"chunk_a_chunk"})
r = nmr(gs3, from_="piece", to="chunk", global_replace=False)
check("  Global off → replace only the first occurrence (chunk_a_piece)", set(col(r[0], "name", PRIM)) == {"chunk_a_piece"})
r = nmr(gs3, namings="left : piece_x", from_="piece", to="p")
check("  name first, then replace (left's prims = p_x)", col(r[0], "name", PRIM)[0] == "p_x"
      and col(r[0], "name", PRIM)[1] == "p_a_p")
gp_ = pts_line(4)
gp_.set_group(POINT, "g", np.array([1, 0, 1, 0], bool))
r = nmr(gp_, cls="point", attribute="label", namings="g : on")
check("Class Points + custom attribute name", col(r[0], "label") == ["on", "", "on", ""])
r = nmr(gn, cls="vertex", namings="0-3 : v")
check("Class Vertices", col(r[0], "name", VERTEX)[:5] == ["v", "v", "v", "v", ""])
gnum = gn.copy()
gnum.set(PRIM, "name", np.zeros((9, 1), np.float32))
r = nmr(gnum, namings="left : a")
check("  existing numeric attribute of the same name → replaced by a string attribute (unnamed ones are empty strings), with a warning in the report",
      col(r[0], "name", PRIM)[:2] == ["a", ""] and "numeric attribute" in json.loads(r[1])["warning"])
check("  Namings missing a colon → raises", raises(lambda: nmr(gn, namings="left rock"), "group : name"))
check("  empty attribute name / unknown Class → raises", raises(lambda: nmr(gn, attribute=" "), "cannot be empty")
      and raises(lambda: nmr(gn, cls="detail"), "Class"))


# ═══════════════════════════════════════════════════════════════ Camera from Points (no code change, verification only)
sec("Camera from Points (verify: the default parameters are Houdini's 'one camera per point, parameters read from point attributes')")
gcp = pts_line(3)
gcp.set(POINT, "orient", np.tile(np.array([[0, 0, 0, 1]], np.float32), (3, 1)))
gcp.set(POINT, "fov", np.array([[30], [45], [60]], np.float32))
gcp.set(POINT, "resx", np.array([[640], [320], [100]], np.float32))
r = call("PCG_CameraFromPoints", geo=gcp)
cams = r[0]
check("default parameters: 3 points → 3 cameras, position = P, fov / resx read from point attributes (the attributes Camera To Points unpacks)",
      len(cams) == 3 and r[1] == 3
      and all(np.allclose(c["eye"], p) for c, p in zip(cams, P_(gcp)))
      and [round(float(c["fov"]), 4) for c in cams] == [30, 45, 60]
      and [int(c.get("xres", c.get("resx", 0))) for c in cams] == [640, 320, 100],
      [(round(float(c["fov"]), 2), {k: c[k] for k in c if "res" in k}) for c in cams])


# ═══════════════════════════════════════════════════════════════ Trace
sec("Trace")
TR = "PCG_Trace"


def tr(cop, **kw):
    return call(TR, cop=cop, **kw)[0]


def areas_(g):
    return np.asarray(g.get(PRIM, "area"), np.float64)[:, 0] if g.nprims else np.zeros(0)


def mk(R=0.0, G=0.0, B=0.0, A=None, H=16, W=16):
    ch = [np.full((H, W), R), np.full((H, W), G), np.full((H, W), B)]
    if A is not None:
        ch.append(np.full((H, W), A))
    a = np.stack(ch, 2)
    a[:4, :4] = 0.0                                       # a dark block at the lower left, so there's a contour to trace
    return img_from(a)


def ntr(cop, thr, mode, **kw):
    return tr(cop, threshold=thr, channel_mode=mode, simplify=0.0, boundary="black", **kw).nprims


check("Channel Mono: luminance = 0.2126 R + 0.7152 G + 0.0722 B (pure red 0.2126: traced at threshold 0.2, not at 0.25)",
      ntr(mk(R=1), 0.2, "mono") > 0 and ntr(mk(R=1), 0.25, "mono") == 0
      and ntr(mk(G=1), 0.7, "mono") > 0 and ntr(mk(G=1), 0.72, "mono") == 0
      and ntr(mk(B=1), 0.07, "mono") > 0 and ntr(mk(B=1), 0.075, "mono") == 0)
check("Channel Red / Green / Blue each read their own", ntr(mk(G=1), 0.5, "green") > 0 and ntr(mk(G=1), 0.5, "red") == 0
      and ntr(mk(B=1), 0.5, "blue") > 0 and ntr(mk(R=1), 0.5, "red") > 0)
check("Channel Alpha: read if there's a 4th channel; otherwise treated as all 1 (one big contour around the image)",
      ntr(mk(A=0.0), 0.5, "alpha") == 0 and ntr(mk(), 0.5, "alpha") == 1)
check("  with only one channel Mono = that channel", digest(tr(img_disk(), channel_mode="mono")) == digest(tr(img_disk())))
check("  with only one channel Green → raises", raises(lambda: tr(img_disk(), channel_mode="green"), "has only 1 channel"))
check("  negative control: Channel defaults to By Index, same as the old channel number",
      digest(tr(img_rgba(), channel=1)) == digest(tr(img_rgba(), channel=1, channel_mode="index")))
d_idx = tr(img_rgba(), channel=0, simplify=0.0)
d_red = tr(img_rgba(), channel=3, channel_mode="red", simplify=0.0)
check("  red mode ignores the channel number (channel = 3 still reads red)", digest(d_idx) == digest(d_red))

h_none = tr(img_half(), simplify=0.0, size=1.0, keep_aspect=False)
h_blk = tr(img_half(), simplify=0.0, size=1.0, keep_aspect=False, boundary="black")
check("Boundary None (old): shapes touching the image border are open lines", h_none.nprims == 1 and not bool(h_none.prim_closed[0]))
# left half x < 24 bright: the contour is at x = 23.5; padded with 0 outside the image, top/bottom/left also close at ±0.5 pixels
exp_a = 24 / 48 * 32 / 32 - 4 * 0.125 / (48 * 32)
check("Boundary Black: closes into one prim, area = (24/48) × 1 minus 4 half-pixel corners cut off by Marching Squares"
      " (0.125 pixel² each)",
      h_blk.nprims == 1 and bool(h_blk.prim_closed[0]) and abs(areas_(h_blk)[0] - exp_a) < 1e-6,
      (areas_(h_blk), exp_a))
h_wht = tr(img_half(), simplify=0.0, size=1.0, keep_aspect=False, boundary="white")
check("Boundary White: the dark right half becomes a hole (negative area, = −24/48)",
      h_wht.nprims == 1 and abs(areas_(h_wht)[0] + exp_a) < 1e-6, areas_(h_wht))
h_00 = tr(img_half(), simplify=0.0, size=1.0, keep_aspect=False, boundary="same_as_00")
check("Same as (0,0): (0,0) is bright → same as White", digest(h_00) == digest(h_wht))
h_00r = tr(img_from(1.0 - np.asarray(img_half().need("C"))[:, :, 0]), simplify=0.0, size=1.0,
           keep_aspect=False, boundary="same_as_00")
check("  (0,0) is dark → the bright right half closes into a prim with positive area", h_00r.nprims == 1 and areas_(h_00r)[0] > 0.4)
hc7 = tr(img_half(), simplify=0.0, size=1.0, keep_aspect=False, boundary="custom", boundary_value=0.7)
hc2 = tr(img_half(), simplify=0.0, size=1.0, keep_aspect=False, boundary="custom", boundary_value=0.2)
check("Custom: Boundary Value 0.7 (above threshold 0.5) behaves like White (hole), 0.2 like Black; contour points outside the border shift by interpolation",
      hc7.nprims == 1 and areas_(hc7)[0] < -0.49 and hc2.nprims == 1 and areas_(hc2)[0] > 0.49
      and not np.isclose(areas_(hc7)[0], areas_(h_wht)[0]), (areas_(hc7), areas_(hc2)))
h_inv = tr(img_half(), simplify=0.0, size=1.0, keep_aspect=False, boundary="black", invert=True)
check("  Invert + Black: the padding is the original value 0 (pad first, then invert) → after inverting the padded ring counts as bright, the left half becomes a hole (area −)",
      h_inv.nprims == 1 and abs(areas_(h_inv)[0] + exp_a) < 1e-6, areas_(h_inv))
d0 = tr(img_disk(), simplify=0.0)
check("  shapes not touching the border + Black background: Boundary doesn't change the result (point positions bit-identical); White adds a hole ring along the image border",
      np.allclose(P_(d0), P_(tr(img_disk(), simplify=0.0, boundary="black")))
      and tr(img_disk(), simplify=0.0, boundary="white").nprims == 2)

dr = tr(img_disk(), simplify=0.0, resample=True, step_size=0.05)
seg = np.linalg.norm(np.diff(np.vstack([P_(dr), P_(dr)[:1]]), axis=0), axis=1)
per = float(np.asarray(d0.get(PRIM, "perimeter"))[0, 0])
check("Resample Shapes: Step Size 0.05 → equal lengths along the arc (chord ≤ 0.05, not too short), still closed, point count ≈ perimeter / 0.05",
      dr.nprims == 1 and bool(dr.prim_closed[0]) and seg.max() <= 0.05 + 1e-6 and seg.min() > 0.035
      and abs(seg.mean() - 0.05) < 0.003 and abs(dr.npoints - per / 0.05) <= 2, (seg.min(), seg.max(), dr.npoints, per / 0.05))
check("  negative control: with Resample off the point count differs", d0.npoints != dr.npoints)
check("  Step Size 0 → raises", raises(lambda: tr(img_disk(), resample=True, step_size=0.0), "Step Size"))

c_ = np.array([0.3, -0.2, 0.1])
d1 = tr(img_disk(), simplify=0.0, center_x=0.3, center_y=-0.2, center_z=0.1)
d2 = tr(img_disk(), simplify=0.0, center_x=0.3, center_y=-0.2, center_z=0.1, rotate_z=90.0)
rel = P_(d1) - c_
check("Rotate z 90°: rotates about the image center ((x, y) → (−y, x))",
      np.allclose(P_(d2) - c_, np.stack([-rel[:, 1], rel[:, 0], rel[:, 2]], 1), atol=1e-5))
d3 = tr(img_disk(), simplify=0.0, center_x=0.3, center_y=-0.2, center_z=0.1, scale_x=2.0, scale_y=0.5,
        scale_z=3.0)
check("Scale (2, 0.5, 3): scales about the center; area × 2 × 0.5 (the two axes of the image plane), perimeter recomputed",
      np.allclose(P_(d3) - c_, rel * [2.0, 0.5, 3.0], atol=1e-5)
      and np.isclose(areas_(d3)[0], areas_(d1)[0] * 1.0, rtol=1e-5)
      and not np.isclose(float(np.asarray(d3.get(PRIM, "perimeter"))[0, 0]),
                         float(np.asarray(d1.get(PRIM, "perimeter"))[0, 0])))
d4 = tr(img_disk(), simplify=0.0, plane="xz", scale_x=2.0, scale_z=-1.0)
check("  XZ plane: the area factor is the x, z scale (signed: after mirroring the orientation flips → area changes sign)",
      np.isclose(areas_(d4)[0], -2.0 * areas_(tr(img_disk(), simplify=0.0, plane="xz"))[0], rtol=1e-5))
d5 = tr(img_disk(), simplify=0.0, plane="zx", scale_y=3.0)
check("  ZX plane: the area factor is the y, z scale",
      np.isclose(areas_(d5)[0], 3.0 * areas_(tr(img_disk(), simplify=0.0, plane="zx"))[0], rtol=1e-5))
check("  unknown Channel / Boundary → raises", raises(lambda: tr(img_disk(), channel_mode="x"), "Channel")
      and raises(lambda: tr(img_disk(), boundary="x"), "Boundary"))


# ═══════════════════════════════════════════════════════════════ PolyDoctor
sec("PolyDoctor (new node PCG_PolyDoctor)")
PD = "PCG_PolyDoctor"
OFF = dict(ill_formed="ignore", overlapping="ignore", disconnected="ignore")


def pd(geo, **kw):
    return call(PD, geo=geo, **kw)


def mesh(P, faces, closed=True):
    return Geometry.from_mesh(np.asarray(P, np.float32), faces, closed=closed)


def parea(g):
    from comfyui_pcg.geo.ops import prim_normals
    return np.linalg.norm(prim_normals(g, normalize=False), axis=1)


Pi = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],           # 0-3 a good quad
      [2, 0, 0], [3, 0, 0], [3, 1, 0],                       # 4-6
      [4, 0, 0], [5, 0, 0], [5, 1, 0],                       # 7-9
      [6, 0, 0], [7, 0, 0],                                  # 10-11
      [8, 0, 0], [9, 0, 0], [10, 0, 0]]                      # 12-14 collinear
gi_ = mesh(Pi, [[0, 1, 2, 3], [4, 5, 5, 6], [7, 8, 7, 9], [10, 11], [12, 13, 14]])
r = pd(gi_, ill_formed="mark")
check("Ill-Formed · Mark: adjacent duplicate points, a point used twice, only 2 corners, zero area → valid_poly = 0; prim count unchanged",
      col(r[0], "valid_poly", PRIM) == [1, 0, 0, 0, 0] and r[0].nprims == 5
      and col(r[0], "repaired_poly", PRIM) == [0] * 5)
r = pd(gi_)
check("Ill-Formed · Repair (default): [4 5 5 6] deduplicated into a triangle (repaired), the three unrepairable ones deleted",
      r[0].nprims == 2 and col(r[0], "repaired_poly", PRIM) == [0, 1]
      and r[0].prim_points(1).tolist() == [4, 5, 6] and col(r[0], "valid_poly", PRIM) == [1, 1])
check("  Ignore: nothing changes", pd(gi_, ill_formed="ignore")[0].nprims == 5)
f8 = mesh([[0, 0, 0], [1, 0, 0], [1, 1, 0], [-1, 0, 0], [-1, -1, 0]], [[0, 1, 2, 0, 3, 4]])
check("  the same point used twice (figure eight, nonzero area) → counts; unrepairable → deleted",
      col(pd(f8, ill_formed="mark")[0], "valid_poly", PRIM) == [0] and pd(f8)[0].nprims == 0)
cp_ = mesh([[0, 0, 0], [1, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], [[0, 1, 2, 3, 4]])
r = pd(cp_, disconnected="ignore")
check("  two adjacent different points at the same position → counts; repair = remove the later corner (a quad remains)",
      col(pd(cp_, ill_formed="mark")[0], "valid_poly", PRIM) == [0]
      and r[0].prim_points(0).tolist() == [0, 1, 3, 4])
wr = mesh([[0, 0, 0], [1, 0, 0], [1, 1, 0]], [[0, 1, 2, 0]])
r = pd(wr)
check("  first and last are the same point ([0 1 2 0]) → repaired into a triangle", r[0].nprims == 1 and r[0].prim_points(0).tolist() == [0, 1, 2])

hexa = mesh([[np.cos(a), np.sin(a), 0] for a in np.arange(6) * np.pi / 3], [list(range(6))])
r = pd(hexa, five_plus="repair")
check("5+ Edges · Repair: a convex hexagon fanned from point 0 into two quads, area unchanged",
      r[0].nprims == 2 and list(r[0].prim_sizes()) == [4, 4]
      and np.isclose(parea(r[0]).sum(), parea(hexa).sum()) and col(r[0], "repaired_poly", PRIM) == [1, 1])
cpent = mesh([[np.cos(a), np.sin(a), 0] for a in np.arange(5) * 2 * np.pi / 5], [list(range(5))])
r = pd(cpent, five_plus="repair")
check("  convex pentagon: one quad + one triangle, area unchanged", list(r[0].prim_sizes()) == [4, 3]
      and np.isclose(parea(r[0]).sum(), parea(cpent).sum()))
r = pd(hexa, five_plus="repair", non_uniform="mark", uniformity_threshold=0.95)
check("  repaired prims count as valid (repaired ⊂ valid; even if Non-Uniform marks them in the same pass they're not invalid)",
      col(r[0], "valid_poly", PRIM) == [1, 1] and col(r[0], "repaired_poly", PRIM) == [1, 1])
pent = mesh([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0.5, 0.5, 0], [0, 1, 0]], [[0, 1, 2, 3, 4]])
r = pd(pent, five_plus="repair")
check("  concave pentagon: ear-clipped into 3 triangles, area unchanged", r[0].nprims == 3 and list(r[0].prim_sizes()) == [3, 3, 3]
      and np.isclose(parea(r[0]).sum(), 0.75))
check("  Mark: valid 0; quads don't count", col(pd(mesh(Pi[:4] + [[0.5, 1.5, 0]], [[0, 1, 2, 4, 3], [0, 1, 2, 3]]),
                                         five_plus="mark")[0], "valid_poly", PRIM) == [0, 1])
dart = mesh([[0, 0, 0], [2, 0, 0], [1, 0.4, 0], [1, 2, 0]], [[0, 1, 2, 3]])
r = pd(dart, non_convex="repair")
check("Non-Convex · Repair: a dart-shaped quad split into two triangles (diagonal through the concave point), area unchanged, neither flipped",
      r[0].nprims == 2 and np.isclose(parea(r[0]).sum(), parea(dart).sum())
      and all(np.asarray(__import__("comfyui_pcg.geo.ops", fromlist=["x"]).prim_normals(r[0]))[:, 2] > 0))
check("  convex quads don't count; Mark → valid 0",
      col(pd(mesh(Pi[:4], [[0, 1, 2, 3]]), non_convex="mark")[0], "valid_poly", PRIM) == [1]
      and col(pd(dart, non_convex="mark")[0], "valid_poly", PRIM) == [0])

ov = mesh(Pi[:4] + [[2, 0, 0]], [[0, 1, 2, 3], [2, 1, 0, 3], [1, 4, 2]])
r = pd(ov)
check("Overlapping · Repair (default): with identical point sets (opposite winding counts too) the first is kept", r[0].nprims == 2
      and r[0].prim_points(0).tolist() == [0, 1, 2, 3])
r = pd(ov, pair_overlaps=True, disconnected="ignore")
check("  Pair Overlaps: both deleted", r[0].nprims == 1 and r[0].prim_points(0).tolist() == [1, 4, 2])
check("  Mark: the second has valid 0; with Pair both 0",
      col(pd(ov, overlapping="mark")[0], "valid_poly", PRIM) == [1, 0, 1]
      and col(pd(ov, overlapping="mark", pair_overlaps=True)[0], "valid_poly", PRIM) == [0, 0, 1])

sa = mesh([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [1.05, 0, 0], [1.05, 1, 0]],
          [[0, 1, 2, 3], [1, 4, 5, 2]])
check("Locally Small Areas: 0.05 / 1 < 0.1 → marked; not at threshold 0.01",
      col(pd(sa, local_area="mark")[0], "valid_poly", PRIM) == [1, 0]
      and col(pd(sa, local_area="mark", local_area_threshold=0.01)[0], "valid_poly", PRIM) == [1, 1])
sa3 = mesh([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [1.05, 0, 0], [1.05, 1, 0], [1.35, 0, 0], [1.35, 1, 0]],
           [[0, 1, 2, 3], [1, 4, 5, 2], [4, 6, 7, 5]])
check("  compared against the **largest** edge-sharing neighbour (the small prim's neighbours are 1 and 0.3: 0.05 < 0.1 × 1 → marked; compared only with 0.3 it wouldn't be)",
      col(pd(sa3, local_area="mark")[0], "valid_poly", PRIM) == [1, 0, 1])
r = pd(sa, local_area="repair")
check("  Repair: the small prim collapses to its center (1.025, 0.5), the big quad becomes a triangle (area 0.5 × 1 × 1.025)",
      r[0].nprims == 1 and r[0].prim_sizes()[0] == 3 and np.isclose(parea(r[0])[0], 0.5125, atol=1e-6)
      and col(r[0], "repaired_poly", PRIM) == [1]
      and any(np.allclose(p, [1.025, 0.5, 0], atol=1e-6) for p in P_(r[0])), P_(r[0]).tolist())

nu = mesh([[0, 0, 0], [10, 0, 0], [10, 0.1, 0], [0, 0.1, 0], [0, 1, 0], [1, 1, 0], [1, 2, 0], [0, 2, 0]],
          [[0, 1, 2, 3], [4, 5, 6, 7]])
check("Non-Uniform · Mark: thin strip isoperimetric quotient 4π·1/20.2² ≈ 0.031 < 0.1 → 0; square 0.785 → 1; at threshold 0.8 both marked",
      col(pd(nu, non_uniform="mark")[0], "valid_poly", PRIM) == [0, 1]
      and col(pd(nu, non_uniform="mark", uniformity_threshold=0.8)[0], "valid_poly", PRIM) == [0, 0])
check("  threshold 0.7: square (0.785) not marked", col(pd(nu, non_uniform="mark", uniformity_threshold=0.7)[0],
                                       "valid_poly", PRIM) == [0, 1])
check("  Non-Uniform has no Repair mode → raises", raises(lambda: pd(nu, non_uniform="repair"), "Non-Uniform"))

se = mesh([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0.0005, 1, 0], [0, 1, 0]], [[0, 1, 2, 3, 4]])
r = pd(se, global_edges="repair")
check("Globally Small Edges · Repair: 0.0005 < 0.001 × diagonal √2 → collapsed to the midpoint (0.00025, 1), pentagon becomes a quad",
      r[0].nprims == 1 and r[0].prim_sizes()[0] == 4 and r[0].npoints == 4
      and any(np.allclose(p, [0.00025, 1, 0], atol=1e-6) for p in P_(r[0]))
      and col(r[0], "repaired_pt").count(1) == 1, P_(r[0]).tolist())
check("  Mark: prims with the short edge valid 0; not at threshold 1e-4",
      col(pd(se, global_edges="mark")[0], "valid_poly", PRIM) == [0]
      and col(pd(se, global_edges="mark", global_edge_threshold=1e-4)[0], "valid_poly", PRIM) == [1])
se100 = mesh(np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0.0005, 1, 0], [0, 1, 0]]) * 100, [[0, 1, 2, 3, 4]])
check("  the threshold multiplies the diagonal: scaled up 100× overall (short edge 0.05) still marked",
      col(pd(se100, global_edges="mark")[0], "valid_poly", PRIM) == [0])
le = mesh([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0.05, 1, 0], [0, 1, 0], [0, 3, 0], [1, 3, 0]],
          [[0, 1, 2, 3, 4], [4, 3, 2, 6, 5]])
check("Locally Small Edges: 0.05 < 0.1 × longest edge (in the prims containing this edge, 2.0…) → both prims marked; not at threshold 0.01",
      col(pd(le, local_edges="mark")[0], "valid_poly", PRIM) == [0, 0]
      and col(pd(le, local_edges="mark", local_edge_threshold=0.01)[0], "valid_poly", PRIM) == [1, 1])
r = pd(le, local_edges="repair")
check("  Repair: the short edge collapses to one point, each of the two prims loses a corner (5 → 4)", r[0].npoints == 6
      and list(r[0].prim_sizes()) == [4, 4] and col(r[0], "repaired_poly", PRIM) == [1, 1])
check("  negative control: the Global mode (0.001 × diagonal) doesn't flag this 0.05 edge",
      col(pd(le, global_edges="mark")[0], "valid_poly", PRIM) == [1, 1])

dc = mesh(Pi[:4] + [[5, 5, 5], [6, 6, 6]], [[0, 1, 2, 3]])
r = pd(dc)
check("Disconnected Points · Repair (default): the 2 points not used by any prim deleted", r[0].npoints == 4)
r = pd(dc, disconnected="mark")
check("  Mark: valid_pt = 0; Ignore: unchanged", col(r[0], "valid_pt") == [1, 1, 1, 1, 0, 0]
      and pd(dc, disconnected="ignore")[0].npoints == 6)
dl = mesh(Pi[:4] + [[5, 5, 5], [6, 6, 6]], [[0, 1, 2, 3]])
dl2 = Geometry.from_mesh(np.asarray(Pi[:4] + [[5, 5, 5], [6, 6, 6]], np.float32), [[4, 5]], closed=False)
check("  points used by polylines aren't isolated; the polyline passes through unchanged, valid = 1",
      pd(dl2)[0].npoints == 2 and col(pd(dl2)[0], "valid_poly", PRIM) == [1])

bt = mesh([[0, 0, 0], [1, 0, 0], [0, 1, 0], [-1, 0, 0], [0, -1, 0]], [[0, 1, 2], [0, 3, 4]])
r = pd(bt, nonmanifold="mark")
check("Non-Manifold Points · Mark: the bowtie's center point valid_pt = 0", col(r[0], "valid_pt") == [0, 1, 1, 1, 1])
r = pd(bt, nonmanifold="repair")
check("  Repair: split into two points (one per fan), repaired_pt = 1, valid_pt all 1",
      r[0].npoints == 6 and set(col(r[0], "valid_pt")) == {1} and col(r[0], "repaired_pt").count(1) >= 1)
fin = mesh([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1]], [[0, 1, 2], [1, 0, 3], [0, 1, 4]])
r = pd(fin, nonmanifold="repair")
from comfyui_pcg.geo import polydoctor as PDM           # noqa: E402
check("  3 prims sharing one edge: the two points on that edge duplicated 'one per fan' (all three prims separated), no non-manifold points after repair",
      PDM.nonmanifold_points(fin).tolist() == [True, True, False, False, False]
      and r[0].npoints == 9 and set(col(r[0], "valid_pt")) == {1} and r[0].nprims == 3
      and not PDM.nonmanifold_points(r[0]).any())

r = pd(gi_, valid_poly="ok", repaired_poly="", valid_pt="vp", repaired_pt="rp", create_groups=True)
check("Attributes: renamed / empty means not written; Create Groups creates *_grp",
      r[0].get(PRIM, "ok") is not None and r[0].get(PRIM, "repaired_poly") is None
      and "ok_grp" in r[0].groups[PRIM] and "vp_grp" in r[0].groups[POINT]
      and "rp_grp" in r[0].groups[POINT] and r[0].get(PRIM, "__pd_valid") is None)
rep_ = json.loads(pd(gi_)[1])
check("report: after repairing, stops when the second pass finds nothing (passes = 2); Max Passes 1 → 1 pass; no problems → 1 pass",
      rep_["passes"] == 2 and json.loads(pd(gi_, max_passes=1)[1])["passes"] == 1
      and json.loads(pd(mesh(Pi[:4], [[0, 1, 2, 3]]))[1])["passes"] == 1
      and rep_["found"]["ill_formed"] == 4, rep_)
gattr = gi_.copy()
gattr.set(PRIM, "pid", np.arange(5, dtype=np.int32)[:, None])
gattr.set(VERTEX, "vv", np.arange(gattr.nvertices, dtype=np.float32)[:, None])
r = pd(gattr)
check("  when repairing, prim / vertex attributes follow (remaining pid = 0 1; vertex attributes of the deduplicated triangle = 4 5 7)",
      col(r[0], "pid", PRIM) == [0, 1] and col(r[0], "vv", VERTEX)[4:] == [4.0, 5.0, 7.0])
check("  unknown mode → raises", raises(lambda: pd(gi_, five_plus="x"), "five_plus"))


# ═══════════════════════════════════════════════════════════════ Panel
sec("Panel specs")
import comfyui_pcg.panel_specs as PS                     # noqa: E402
for k in ("PCG_AttribFromPieces", "PCG_AttribFill", "PCG_AttribFadeTime", "PCG_AttribTransformExtractHou",
          "PCG_Name", "PCG_Trace", "PCG_PolyDoctor"):
    check(f"{k}: spec self-check passes", not PANEL.check_layout(k, M[k].INPUT_TYPES()),
          PANEL.check_layout(k, M[k].INPUT_TYPES()))
    sp = PS.SPECS[k]
    ws = [n for n in names(k) if n not in ("geo", "library", "rest", "animated", "start_geo", "hold_geo", "cop")]
    check(f"{k}: every widget is in order, nothing extra", sorted(sp["order"]) == sorted(ws),
          set(sp["order"]) ^ set(ws))
    bad = []
    for n in ws:
        spec = [v[n] for v in M[k].INPUT_TYPES().values() if n in v][0]
        if isinstance(spec[0], (list, tuple)):
            menu = sp["inputs"].get(n, {}).get("menu")
            if menu is None or sorted(menu) != sorted(spec[0]):
                bad.append(n)
    check(f"{k}: every token of every combo has a Houdini label", not bad, bad)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
