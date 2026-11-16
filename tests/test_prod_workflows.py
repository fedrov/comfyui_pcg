"""
pcg84: actually runs the four "production" pipelines (rock assets / open-world terrain tiles / modular buildings / material library),
checking the deliverables themselves -- i.e. the files the engine side really reads -- rather than intermediate results inside the nodes.

References do not rely on the implementation under test: images read back with PIL, glb parsed independently (same parser as test_exporters),
CSV read with the csv module; expected values come from the conventions stated in the workflows (or are recomputed with numpy):

  rocks      one glb per rock: LOD0 > LOD1 > LOD2 > collision, every (position, uv) of LOD1 / LOD2 is in LOD0
         (the precondition for sharing one texture set), uv within 0..1, almost no flipped faces; every UCX is convex; one material slot,
         the files the texture uris point to really exist, 1024²; the normal map decodes to unit vectors pointing outwards (z > 0);
         pivot convention (flat bottom at y = -0.5, centered horizontally); Khronos validator (if installed) 0 errors
  terrain    16 tiles of 257² height PNGs, shared edges of neighbouring tiles bit-identical, stitched back = the full r16 image; the six weight layers
         sum to ≈ 255 per pixel; instances all within 0..4096, each tile file only has its own tile's points, the index counts match;
         instance y = terrain height decoded via Height.json (rocks buried 0.25·pscale by convention) --
         negative control: comparing with a one-sample offset does not match; towns: buildings on levelled lots (flat ground
         under every footprint, nothing deeper than the plinth), off the roads, in the town discs, taller toward the centre,
         one glb node per town; fields: every 2 x 2 window of the WFC grid is one of the sample's, the fields cleared of
         woodland; the tree proxies' LOD chains end in impostor cards, their atlases cover every frame
  buildings  kit pivot convention (bottom edge midpoint, facade +Z, wall thickness towards -Z); the instance table's assets are all exported glb names;
         wall count = "footprint outline edge count × floor count" recomputed with numpy by the rules; every wall at the midpoint of a 4 m edge,
         outer normal pointing outwards (the cell in front is not this building, the cell behind is) -- negative control: no wall lands on a grid point
         (before the bug in Extract Centroid's per-face centers was fixed, 24 walls were at the origin and the rest all on corners);
         no duplicate placements; the material library runs first, then the kit's glb are validated and all textures are found
  materials  14 sets × 5 maps, 1024², real-size relief (brick joints, cobble domes, seam height); seamless on all four edges (the jump across the wrapped column is of the same magnitude as between neighbouring columns --
         negative control: crop off 30% and it fails); Normal_DX's G = 255 - Normal_GL's G, R and B identical;
         normals unit length; ORM: brick wall metalness all 0, metalness full where the roof is chipped, the door studs have metalness

Plus one bug fixed along the way (no torch needed): when Extract Centroid extracts centers per face (run over primitives),
points shared by neighbouring faces were only recorded for the last face, so the centers were all wrong -- reference = average of each face's own points.
"""
import csv
import gc
import glob
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time

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

from comfyui_pcg.geo import build, ops                  # noqa: E402
from comfyui_pcg.geo.centroid import extract_centroid   # noqa: E402
from comfyui_pcg.geo.core import POINT, PRIM            # noqa: E402
from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP      # noqa: E402
import make_workflows as MW                             # noqa: E402

try:
    import torch
except ImportError:                                     # pragma: no cover
    torch = None

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


# ═══════════════════════════════════════════════════ 0. Extract Centroid per face
sec("Extract Centroid: per-face centers (neighbouring faces share points)")
g = build.grid(4.0, 2.0, 5, 3)                          # 8 faces, interior points shared by 2~4 faces
e = extract_centroid(g, "primitives", "", "primitives", "average_position", "points")
ref = ops.prim_centers(g)
check("each face's center = average of that face's own points", e.npoints == g.nprims
      and np.allclose(np.asarray(e.get(POINT, "P")), ref, atol=1e-6))
e2 = extract_centroid(g, "primitives", "", "primitives", "bounding_box", "points")
P = np.asarray(g.get(POINT, "P"), np.float64)
bb = np.array([(P[g.prim_points(i)].min(0) + P[g.prim_points(i)].max(0)) / 2
               for i in range(g.nprims)])
check("  bounding_box likewise (center of each face's own bounding box)",
      np.allclose(np.asarray(e2.get(POINT, "P")), bb, atol=1e-6))
# negative control: the old approach -- each point gets only one piece number (the last face written)
ptl = np.full(g.npoints, -1)
ptl[g.vertex_point] = g.vertex_prim()
old = np.array([P[ptl == i].mean(0) if (ptl == i).any() else np.zeros(3)
                for i in range(g.nprims)])
check("  negative control: with each point recorded for only one face, most centers are wrong",
      (np.linalg.norm(old - ref, axis=1) > 0.1).sum() >= g.nprims // 2)
g2 = build.grid(2.0, 2.0, 3, 3)                          # four cells minus one = L shape, asymmetric
g2 = ops.delete_prims(g2, np.arange(g2.nprims) != 3)
g2 = ops.delete_prims(g2, np.ones(g2.nprims, bool))       # remove unused points
e3 = extract_centroid(g2, "connectivity", "", "primitives", "average_position", "points")
check("  per piece: shared points counted once (once per point, not weighted by corner count)",
      np.allclose(np.asarray(e3.get(POINT, "P"))[0],
                  np.asarray(g2.get(POINT, "P"), np.float64).mean(0), atol=1e-6)
      and not np.allclose(np.asarray(g2.get(POINT, "P"), np.float64)[g2.vertex_point].mean(0),
                          np.asarray(g2.get(POINT, "P"), np.float64).mean(0)))
cube = build.box((2, 2, 2), (0, 0, 0), (2, 2, 2))
ec = extract_centroid(cube, "connectivity", "", "primitives", "average_position", "points")
check("  per piece (one box per piece): shared points counted once, center = origin",
      ec.npoints == 1 and np.allclose(np.asarray(ec.get(POINT, "P")), 0, atol=1e-6))


# ═══════════════════════════════════════════════════ helpers
def glb_parse(path):
    d = open(path, "rb").read()
    magic, ver, total = struct.unpack("<III", d[:12])
    assert magic == 0x46546C67 and ver == 2 and total == len(d)
    jl = struct.unpack("<I", d[12:16])[0]
    js = json.loads(d[20:20 + jl])
    bl = struct.unpack("<I", d[20 + jl:24 + jl])[0]
    binb = d[28 + jl:28 + jl + bl]

    def acc(i):
        a = js["accessors"][i]
        v = js["bufferViews"][a["bufferView"]]
        dt = "<f4" if a["componentType"] == 5126 else "<u4"
        k = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
        arr = np.frombuffer(binb[v["byteOffset"]:v["byteOffset"] + v["byteLength"]], dt)
        return (arr.reshape(a["count"], k) if k > 1 else arr).astype(np.float64), a
    return js, acc


def node_meshes(path):
    """{node name: (P, uv, idx, N)}, multiple primitives in one node concatenated."""
    js, acc = glb_parse(path)
    out = {}
    for n in js["nodes"]:
        Ps, Us, Is, Ns, off = [], [], [], [], 0
        for pr in js["meshes"][n["mesh"]]["primitives"]:
            p, _ = acc(pr["attributes"]["POSITION"])
            u = acc(pr["attributes"]["TEXCOORD_0"])[0] if "TEXCOORD_0" in pr["attributes"] \
                else np.zeros((len(p), 2))
            nn, _ = acc(pr["attributes"]["NORMAL"])
            i, _ = acc(pr["indices"])
            Ps.append(p)
            Us.append(u)
            Ns.append(nn)
            Is.append(i.astype(np.int64) + off)
            off += len(p)
        out[n["name"]] = (np.concatenate(Ps), np.concatenate(Us),
                          np.concatenate(Is).reshape(-1, 3), np.concatenate(Ns))
    return js, out


def img(path):
    from PIL import Image
    im = Image.open(path)
    a = np.asarray(im)
    return a if a.ndim == 3 else a[..., None]


VJS = "/tmp/gv/v.mjs"


def validate(path):
    if not (shutil.which("node") and os.path.exists(VJS)):
        return None
    out = subprocess.run(["node", VJS, path], capture_output=True, text=True).stdout
    try:
        return json.loads(out)
    except ValueError:
        return None


IMGS = []


class _Img:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}
    RETURN_TYPES = ()
    FUNCTION = "run"

    def run(self, images, filename_prefix=None):
        IMGS.append((filename_prefix, tuple(getattr(images, "shape", ()))))   # the shape only: the images themselves stayed for the whole run
        return ()


def run(name, cwd, release=False, capture=None):
    """capture: {node title: fn(outputs) -> summary}; the summaries go to capture["got"] (the outputs themselves are
    not kept, so a release run stays released)."""
    wf = MW.WORKFLOWS[name]().to_ui()
    pr = MW.validate_ui(wf)
    api = MW.ui_to_api(wf)
    classes = dict(MAP)
    classes["PreviewImage"] = _Img
    classes["SaveImage"] = _Img
    old = os.getcwd()
    os.chdir(cwd)
    t0 = time.time()
    try:
        ex = fakecomfy.Executor(api, classes, release=release)
        if capture:
            ids = {str(n["id"]): n.get("title") for n in wf["nodes"] if n.get("title") in capture}
            got = capture.setdefault("got", {})
            ev = ex._eval

            def _eval(scope, nid, ev=ev):
                out = ev(scope, nid)
                if nid in ids and ids[nid] not in got:
                    got[ids[nid]] = capture[ids[nid]](out)
                return out
            ex._eval = _eval
        if release:                     # outputs are not collected either: holding them would undo the release
            res = None
            for nid in api:
                ex.run(nid)
        else:
            res = {nid: ex.run(nid) for nid in api}
    finally:
        os.chdir(old)
    return api, res, pr, time.time() - t0


if torch is None or os.environ.get("PCG_TEST_QUICK"):
    print("\n  (no torch / PCG_TEST_QUICK, skipping the real runs of the four pipelines)")
else:
    CWD = tempfile.mkdtemp(prefix="pcg_prod_")
    OUT = os.path.join(CWD, "output")

    # ═══════════════════════════════════════════════ 4. Open-world terrain tiles (run first)
    # runs first, while the process is small: its peak (the 4096² texture chain, then the preview renders) is the
    # highest of the four, and what the other pipelines leave behind would push it over 6 GB
    sec("Open-world terrain tiles")
    gc.collect()
    from comfyui_pcg import memtrim as _mt
    _mt.trim()                          # and give the freed heap back (glibc keeps it otherwise)
    print(f"  (process memory before the run: {int(open('/proc/self/statm').read().split()[1]) * 4096 >> 20} MB)"
          if os.path.exists("/proc/self/statm") else "")
    # the checks read the written files; outputs are let go once read (the 4096² texture chain and the full-map
    # meshes do not all fit in 8 GB beside the preview render)
    def _grass(out):
        g_ = out[0]
        return {"P": np.asarray(g_.get(POINT, "P"), np.float32).copy(), "N": np.asarray(g_.get(POINT, "N"),
                                                                                       np.float32).copy(),
                "prims": g_.nprims}
    def _pts(out):
        return np.asarray(out[0].get(POINT, "P"), np.float32).copy()
    def _bld(out):
        g_ = out[0]
        P_ = np.asarray(g_.get(POINT, "P"), np.float64)
        vp_, off_ = np.asarray(g_.vertex_point), np.asarray(g_.prim_offset)
        cnt_ = np.diff(off_)
        b_ = np.repeat(np.asarray(g_.get(PRIM, "building")).reshape(-1), cnt_)
        part_ = np.repeat(np.asarray(g_.get(PRIM, "part")).reshape(-1), cnt_)
        fl_ = np.asarray(g_.get(PRIM, "floor")).reshape(-1)
        bp_ = np.asarray(g_.get(PRIM, "building")).reshape(-1)
        nb_ = int(bp_.max()) + 1
        up_ = part_ != "plinth"
        base_ = np.full(nb_, np.inf)
        np.minimum.at(base_, b_[up_], P_[vp_[up_], 1])
        feet_ = up_ & (np.abs(P_[vp_, 1] - base_[b_]) < 1e-4)
        first_ = np.searchsorted(bp_, np.arange(nb_))
        attr_ = lambda n: np.asarray(g_.get(PRIM, n)).reshape(-1)[first_]          # noqa: E731
        floors_ = np.zeros(nb_, int)
        np.maximum.at(floors_, bp_, fl_ + 1)
        # each face's centre (x, z), for the doors' and the walls' distance to the road
        fc_ = np.zeros((g_.nprims, 3))
        np.add.at(fc_, np.repeat(np.arange(g_.nprims), cnt_), P_[vp_])
        fc_ = fc_[:, [0, 2]] / cnt_[:, None]
        pp_ = np.asarray(g_.get(PRIM, "part")).reshape(-1)
        rt_ = np.full(nb_, -1e9)
        rv_ = part_ == "roof"
        np.maximum.at(rt_, b_[rv_], P_[vp_[rv_], 1])
        md_ = np.asarray(g_.get(PRIM, "module")).reshape(-1)
        return {"base": base_, "feet": P_[vp_[feet_]][:, [0, 2]], "feet_b": b_[feet_], "name": attr_("name"),
                "floors": floors_, "tc": attr_("tc_avg"), "rf": attr_("rf"), "door_c": fc_[pp_ == "door"], "door_b": bp_[pp_ == "door"],
                "wall_c": fc_[pp_ == "wall"], "wall_b": bp_[pp_ == "wall"], "gable": int((md_ == "gable").sum()),
                "roof_top": rt_,
                "parts": {str(k): int((pp_ == k).sum()) for k in np.unique(pp_)}}

    def _cards(out):
        g_ = out[0]
        uv_ = np.asarray(g_.get(POINT, "uv"), np.float64)
        return {"n": g_.nprims, "uv": (float(uv_[:, :2].min()), float(uv_[:, :2].max())),
                "frames": len(np.unique(np.floor(uv_[:, :2].reshape(-1, 4, 2).mean(1) * 8), axis=0))}

    def _lods(out):
        g_ = out[0]
        lv_ = np.asarray(g_.get(PRIM, "lod")).reshape(-1)
        return {int(k): int((lv_ == k).sum()) for k in np.unique(lv_)}

    def _towns(out):
        return np.asarray(out[0].get(POINT, "P"), np.float64)[:, [0, 2]].copy()

    def _wfc(out):
        from comfyui_pcg.geo.cop.pixel import getn as _g
        return np.rint(_g(out[0], "field_id")[::8, ::8, 0]).astype(int)

    def _eco(out):
        from comfyui_pcg.geo.cop.pixel import getn as _g
        return {k: _g(out[0], k)[..., 0].astype(np.float32) for k in ("farm", "field_id", "town", "ForestFloor", "N", "fieldw")} | {
            "Nz": _g(out[0], "N")[..., 2].astype(np.float32)}
    cap = {"Grass tufts": _grass, "Close range: material terrain": _pts, "Material: terrain": _pts,
           "Terrain: full map + close range": lambda out: out[0].npoints,
           "Buildings (Building Generator)": _bld, "Towns: numbered": _towns, "Valley: cards' uv on their frame": _cards,
           "Valley: the towns at that LOD": _lods, "Fields: WFC over the map (128² cells, tileable)": _wfc,
           "Ecology: seven weight layers + scatter densities": _eco}
    api, res, pr, dt = run("pcg_prod_world_tiles", CWD, release=True, capture=cap)
    check(f"runs ({len(api)} nodes, {dt:.1f} s), UI self-check clean", not pr, pr[:2])
    WD = os.path.join(OUT, "pcg/world")
    tiles = {(i, j): img(os.path.join(WD, f"height/Height_x{i}_y{j}.png"))[..., 0].astype(np.int64)
             for i in range(4) for j in range(4)}
    check("height: 16 tiles of 16-bit PNG, 257² each", len(tiles) == 16
          and all(t.shape == (257, 257) for t in tiles.values())
          and img(os.path.join(WD, "height/Height_x0_y0.png")).dtype == np.uint16)
    check("  shared edges of left/right and top/bottom neighbouring tiles bit-identical",
          all(np.array_equal(tiles[(i, j)][:, -1], tiles[(i + 1, j)][:, 0])
              for i in range(3) for j in range(4))
          and all(np.array_equal(tiles[(i, j)][-1], tiles[(i, j + 1)][0])
                  for i in range(4) for j in range(3)))
    full = np.fromfile(os.path.join(WD, "height/Height_full.r16"), "<u2").reshape(1025, 1025)
    st = np.zeros((1025, 1025), np.int64)
    for (i, j), t in tiles.items():
        st[j * 256:j * 256 + 257, i * 256:i * 256 + 257] = t
    check("  the 16 tiles stitched back = the full r16 image (bit-exact)", np.array_equal(st, full))
    hj = json.load(open(os.path.join(WD, "height/Height.json"), encoding="utf-8"))
    lo_m, hi_m = hj["range_scaled"]
    check("  the sidecar is called Height.json, range_scaled is in metres (= range × 2048)",
          np.allclose([lo_m, hi_m], np.array(hj["range"]) * 2048) and hi_m - lo_m > 100,
          (round(lo_m, 1), round(hi_m, 1)))
    Hm = lo_m + full / 65535.0 * (hi_m - lo_m)
    layers = ("Grass", "ForestFloor", "Sediment", "Rock", "Sand", "Water", "Road")
    okw = True
    for i in range(4):
        for j in range(4):
            s = sum(img(os.path.join(WD, f"weight/{L}_x{i}_y{j}.png"))[..., 0].astype(int)
                    for L in layers)
            okw &= np.abs(s - 255).max() <= 4
    check("weights: the seven layers sum to ≈ 255 per pixel (each 8-bit layer rounded on its own, off by ≤ 4)", okw)
    # 1 m surface textures: 16 BaseColor + 16 normal tiles of 1024²; stitched, they follow the weight maps
    TD = os.path.join(WD, "texture")
    bct = {(i, j): img(os.path.join(TD, f"T_Terrain_BaseColor_x{i}_y{j}.png"))[..., :3] for i in range(4) for j in range(4)}
    nmt = {(i, j): img(os.path.join(TD, f"T_Terrain_Normal_GL_x{i}_y{j}.png"))[..., :3] for i in range(4) for j in range(4)}
    check("textures: 16 BaseColor and 16 Normal_GL tiles, 1024² 8-bit",
          all(t.shape == (1024, 1024, 3) and t.dtype == np.uint8 for t in list(bct.values()) + list(nmt.values())))
    BC = np.zeros((4096, 4096, 3), np.float32)
    NM = np.zeros((4096, 4096, 3), np.float32)
    for (i, j), t in bct.items():
        BC[j * 1024:(j + 1) * 1024, i * 1024:(i + 1) * 1024] = t
        NM[j * 1024:(j + 1) * 1024, i * 1024:(i + 1) * 1024] = nmt[(i, j)]
    nv = NM / np.float32(255.0) * 2 - 1
    lnv = np.linalg.norm(nv, axis=-1)
    check("  the normal map decodes to unit vectors facing out (z > 0), and has relief (not a flat (0, 0, 1))",
          abs(np.median(lnv) - 1) < 0.02 and (nv[..., 2] > 0).mean() > 0.999 and np.percentile(nv[..., 2], 5) < 0.97,
          (round(float(np.median(lnv)), 3), round(float(np.percentile(nv[..., 2], 5)), 3)))
    wfull = {}
    for L in ("Water", "Rock", "Grass", "Road"):
        a = np.zeros((1025, 1025))
        for i in range(4):
            for j in range(4):
                a[j * 256:j * 256 + 257, i * 256:i * 256 + 257] = img(os.path.join(WD, f"weight/{L}_x{i}_y{j}.png"))[..., 0]
        wfull[L] = a / 255.0
    # texel (r, c) of the 4096² set -> nearest weight sample (both cover the map edge to edge, by pixel centre)
    rr = np.minimum(((np.arange(4096) + 0.5) * 1025 / 4096).astype(int), 1024)
    BCs = BC[::8, ::8]
    sub = rr[::8]

    def mean_rgb(L, thr=0.97):
        m = wfull[L][np.ix_(sub, sub)] > thr
        return BCs[m].mean(0), int(m.sum())
    wat, nw = mean_rgb("Water")
    grs, ng = mean_rgb("Grass")
    rck, nr = mean_rgb("Rock", 0.9)
    sat = lambda c: float((c.max() - c.min()) / max(c.max(), 1e-9))     # noqa: E731

    def is_rock(c):
        return c[0] >= c[2] and sat(c) < 0.3            # grey-brown: little colour

    def is_grass(c):
        return c[1] >= c[0] and c[1] > c[2] and sat(c) > 0.35
    check("  BaseColor follows the weights: water blue (b > r), grass green (g highest, saturated), rock grey-brown "
          "(r ≥ b, saturation < 0.3)",
          nw > 100 and ng > 100 and nr > 20 and wat[2] > wat[0] and is_grass(grs) and is_rock(rck),
          (wat.round(), grs.round(), rck.round(), round(sat(grs), 2), round(sat(rck), 2)))
    check("    negative control: the grass texels fail the rock test, the rock texels the grass test",
          not is_rock(grs) and not is_grass(rck))
    idx = json.load(open(os.path.join(WD, "instances/Instances_index.json"), encoding="utf-8"))
    rows, okt = [], True
    for f in idx["files"]:
        tx, ty = f["tile"]
        rr = list(csv.DictReader(open(os.path.join(OUT, f["file"]), encoding="utf-8")))
        okt &= len(rr) == f["count"] and 0 <= tx < 4 and 0 <= ty < 4
        for r in rr:
            x, z = float(r["px"]), float(r["pz"])
            okt &= int(x // 1024) == tx and int(z // 1024) == ty
        rows += rr
    check("instances: the master table is called Instances_index.json, tile numbers all in 0..3, each tile only has its own points, counts match",
          okt and len(rows) == idx["count"] > 1000, len(rows))
    xs = np.array([float(r["px"]) for r in rows])
    zs = np.array([float(r["pz"]) for r in rows])
    check("  all instances within 0..4096 (points half a cell beyond the border removed)",
          xs.min() >= 0 and xs.max() < 4096 and zs.min() >= 0 and zs.max() < 4096)

    def hgt(x, z, off=0.0):
        u, v = x / 4.0 + off, z / 4.0
        i0 = np.clip(np.floor(u).astype(int), 0, 1023)
        j0 = np.clip(np.floor(v).astype(int), 0, 1023)
        fu, fv = u - i0, v - j0
        return (Hm[j0, i0] * (1 - fu) * (1 - fv) + Hm[j0, i0 + 1] * fu * (1 - fv)
                + Hm[j0 + 1, i0] * (1 - fu) * fv + Hm[j0 + 1, i0 + 1] * fu * fv)

    ys = np.array([float(r["py"]) for r in rows])
    rock = np.array([r["asset"].startswith("SM_Rock_") for r in rows])
    sc = np.array([float(r["sx"]) for r in rows])
    exp = hgt(xs, zs) - np.where(rock, 0.25 * sc, 0.0)
    err_ = np.abs(ys - exp)
    check("  instance y = terrain height decoded via Height.json (rocks buried 0.25·pscale by convention), "
          "99% within < 0.5 m", np.percentile(err_, 99) < 0.5,
          (round(float(np.median(err_)), 3), round(float(np.percentile(err_, 99)), 3)))
    err2 = np.abs(ys - (hgt(xs, zs, 3.0) - np.where(rock, 0.25 * sc, 0.0)))
    check("    negative control: offset by 3 samples (12 m) and compared again, much worse", np.median(err2) > 5 * np.median(err_),
          round(float(np.median(err2)), 3))
    assets = {r["asset"] for r in rows}
    check("  rock asset names match the glb exported by the rock pipeline (SM_Rock_00..03)",
          {a for a in assets if a.startswith("SM_Rock_")} == {f"SM_Rock_{k:02d}" for k in range(4)})
    q = np.array([[float(r[c]) for c in ("qx", "qy", "qz", "qw")] for r in rows])
    check("  quaternions unit length", np.allclose(np.linalg.norm(q, axis=1), 1, atol=1e-5))

    # roads: OBJ polylines on the cut road bed, at a drivable grade, under the Road weight
    vs_, ls_ = [], []
    for ln in open(os.path.join(WD, "roads/Roads.obj"), encoding="utf-8"):
        if ln.startswith("v "):
            vs_.append([float(t) for t in ln.split()[1:4]])
        elif ln.startswith("l "):
            ls_.append([int(t) - 1 for t in ln.split()[1:]])
    RV = np.array(vs_)
    rl = [RV[i] for i in ls_]
    rlen = sum(float(np.linalg.norm(np.diff(p[:, [0, 2]], axis=0), axis=1).sum()) for p in rl)
    check(f"roads: {len(rl)} polylines, {rlen / 1000:.1f} km, all inside the map", len(rl) >= 5 and rlen > 5000
          and RV[:, 0].min() >= 0 and RV[:, 0].max() < 4096 and RV[:, 2].min() >= 0 and RV[:, 2].max() < 4096)
    dz = np.abs(RV[:, 1] - hgt(RV[:, 0], RV[:, 2]))
    check("  on the cut bed: the road height matches the height files (median < 0.5 m, 95 % < 2 m)",
          np.median(dz) < 0.5 and np.percentile(dz, 95) < 2.0,
          (round(float(np.median(dz)), 3), round(float(np.percentile(dz, 95)), 3)))
    gr_ = np.concatenate([np.abs(np.diff(p[:, 1])) / np.maximum(np.linalg.norm(np.diff(p[:, [0, 2]], axis=0), axis=1),
                                                                 1e-6) for p in rl])
    longest = max(rl, key=len)
    a_, b_ = longest[0], longest[-1]
    tt = np.linspace(0, 1, 400)[:, None]
    sx = a_[None, [0, 2]] * (1 - tt) + b_[None, [0, 2]] * tt
    sg = hgt(sx[:, 0], sx[:, 1])
    straight = np.abs(np.diff(sg)) / np.maximum(np.linalg.norm(np.diff(sx, axis=0), axis=1), 1e-6)
    check("  at a drivable grade: 95 % of the road under 16 % (planned at 10 % on an 8 m grid)", np.percentile(gr_, 95) < 0.16,
          round(float(np.percentile(gr_, 95)), 3))
    check("    negative control: the straight line between the ends of the longest road is much steeper",
          np.percentile(straight, 95) > 1.5 * np.percentile(gr_, 95), round(float(np.percentile(straight, 95)), 3))
    ci = np.clip((RV[:, 0] / 4.0).astype(int), 0, 1024)
    cj = np.clip((RV[:, 2] / 4.0).astype(int), 0, 1024)
    on = (wfull["Road"][cj, ci] > 0.3).mean()
    off = (wfull["Road"][np.clip(cj + 12, 0, 1024), ci] > 0.3).mean()
    check(f"  under the Road weight: {on:.0%} of the road points; negative control 48 m to the side: {off:.0%}",
          on > 0.8 and off < 0.3)
    from scipy.spatial import cKDTree
    # towns: buildings on levelled lots, in the town discs, off the roads, taller toward the centre
    bq = cap["got"].get("Buildings (Building Generator)")
    if bq is None:
        check("buildings: the Building Generator node ran", False)
    else:
        nb_ = len(bq["base"])
        towns_ = sorted(set(bq["name"].tolist()))
        check(f"buildings: {nb_} in {len(towns_)} towns (Lot Subdivision -> Building Generator), named Town_NN, "
              f"with plinths: {bq['parts']}",
              nb_ > 150 and len(towns_) >= 8 and all(t.startswith("Town_") for t in towns_)
              and bq["parts"].get("plinth", 0) >= 4 * nb_ and bq["parts"].get("glass", 0) > nb_)
        fx, fz = bq["feet"][:, 0], bq["feet"][:, 1]
        gf = hgt(fx + 2048, fz + 2048)
        dz_ = gf - bq["base"][bq["feet_b"]]
        check(f"  on levelled ground: the terrain at the walls' feet is within the 3 m plinth of the base "
              f"(range {dz_.min():.2f} .. {dz_.max():.2f} m, median {np.median(dz_):.2f})",
              dz_.min() > -3.0 and np.median(np.abs(dz_ - 0.2)) < 0.5, np.percentile(dz_, [1, 50, 99]).round(2))
        sp_, spc_ = [], []
        rng_ = np.random.default_rng(5)
        for k in range(nb_):
            f_ = bq["feet"][bq["feet_b"] == k]
            if len(f_) < 3:
                continue
            c_ = f_.mean(0)
            inner = c_ + 0.5 * (f_ - c_)
            sp_.append(np.ptp(hgt(inner[:, 0] + 2048, inner[:, 1] + 2048)))
            a_ = rng_.random() * 2 * np.pi
            mv = inner + 60.0 * np.array([np.cos(a_), np.sin(a_)])
            spc_.append(np.ptp(hgt(mv[:, 0] + 2048, mv[:, 1] + 2048)))
        sp_, spc_ = np.array(sp_), np.array(spc_)
        check(f"  each footprint's ground is flat (the pad): 90% of the buildings with < 0.5 m of fall under them; "
              f"negative control, the same footprints 60 m away: {np.mean(spc_ < 0.5):.0%}",
              np.mean(sp_ < 0.5) > 0.9 and np.mean(spc_ < 0.5) < 0.6,
              (round(float(np.mean(sp_ < 0.5)), 2), round(float(np.mean(spc_ < 0.5)), 2)))
        tp_ = cap["got"].get("Towns: numbered")
        rkd = cKDTree(RV[:, [0, 2]] - 2048.0)
        dr_ = rkd.query(bq["feet"])[0]
        dtc_ = rkd.query(tp_)[0]
        check(f"  off the roads: every wall at least 8 m from a road centre line (min {dr_.min():.1f} m); negative "
              f"control, the town centres: median {np.median(dtc_):.1f} m from a road",
              dr_.min() > 8.0 and np.median(dtc_) < 10.0)
        cen_ = np.array([bq["feet"][bq["feet_b"] == k].mean(0) for k in range(nb_)])
        ti_ = np.array([int(n_[5:]) - 1 for n_ in bq["name"]])
        dcen = np.linalg.norm(cen_ - tp_[ti_], axis=1)
        dcr_ = rkd.query(cen_)[0]
        cr_ = float(np.corrcoef(bq["tc"], bq["floors"])[0, 1])
        check(f"  plots along the roads: every building in its town's disc (within 170 m of the centre, max "
              f"{dcen.max():.0f} m), 90% within 90 m of a road (median {np.median(dcr_):.0f} m); 1-5 floors, taller "
              f"toward the town core (correlation of floors with the core weight {cr_:.2f})",
              dcen.max() < 170 and np.mean(dcr_ < 90) > 0.9 and bq["floors"].min() >= 1 and bq["floors"].max() <= 5
              and cr_ > 0.3)
        # the doors face the road: a door is nearer the road than its building's centre; negative control, the
        # building's walls on average (half of them face away)
        dd_ = rkd.query(bq["door_c"])[0] - dcr_[bq["door_b"]]
        wd_ = rkd.query(bq["wall_c"])[0] - dcr_[bq["wall_b"]]
        hd_ = len(np.unique(bq["door_b"]))
        check(f"  the doors on the street side (Front Pattern): {hd_} buildings with doors, {np.mean(dd_ < 0):.0%} of "
              f"the doors nearer the road than their building's centre; negative control, the walls: "
              f"{np.mean(wd_ < 0):.0%}", hd_ > 0.8 * nb_ and np.mean(dd_ < 0) > 0.9 and np.mean(wd_ < 0) < 0.65,
              (round(float(np.mean(dd_ < 0)), 3), round(float(np.mean(wd_ < 0)), 3)))
        rf_ = bq["rf"]
        ridge_ = bq["roof_top"] - bq["base"] - 3.4 - 3.1 * (bq["floors"] - 1)
        check(f"  pitched roofs: gable on 1-3 floors, hip on 4-5 ({dict(zip(*np.unique(rf_, return_counts=True)))}), "
              f"{bq['gable']} gable-end walls, the ridges above the eaves (median {np.median(ridge_):.1f} m)",
              set(rf_.tolist()) <= {"gable", "hip"} and np.all((rf_ == "hip") == (bq["floors"] >= 4))
              and bq["gable"] > 0 and np.median(ridge_) > 1.5, np.percentile(ridge_, [1, 50, 99]).round(2))
        js_, tn_ = node_meshes(os.path.join(WD, "buildings/Towns.glb"))
        allv = np.concatenate([v[0] for v in tn_.values()])
        want_ = sorted(f"{t}_LOD{k}" for t in towns_ for k in range(3))
        tri_ = {n_: len(v[2]) for n_, v in tn_.items()}
        lodok = all(tri_[f"{t}_LOD1"] < 0.5 * tri_[f"{t}_LOD0"] and tri_[f"{t}_LOD2"] < tri_[f"{t}_LOD1"]
                    for t in towns_) if sorted(tn_) == want_ else False
        mats_ = {m["name"] for m in js_["materials"]}
        check(f"  Towns.glb: a node per town and LOD ({len(tn_)}: the buildings, their massing, the massing reduced), "
              f"in the north-west-origin frame (0..4096), the material library's materials {sorted(mats_)}",
              sorted(tn_) == want_ and lodok and allv[:, [0, 2]].min() > 0 and allv[:, [0, 2]].max() < 4096
              and {"M_Glass", "M_Door", "M_Trim", "M_Roof"} <= mats_ and len(mats_ & {"M_Stucco", "M_BrickBuff", "M_Wall"}) >= 2,
              {t: (tri_.get(f"{t}_LOD0"), tri_.get(f"{t}_LOD1"), tri_.get(f"{t}_LOD2")) for t in towns_[:3]})
    # the fields: a WFC patchwork round the towns, cleared of woodland
    fw = cap["got"].get("Fields: WFC over the map (128² cells, tileable)")
    if fw is None:
        check("fields: the WFC node ran", False)
    else:
        # the sample as the WFC sees it: string 0 is the top row (image row 0 is the bottom), colours numbered in
        # order of first appearance from image row 0
        rows_ = MW.FIELD_SAMPLE[::-1]
        order_ = []
        for r_ in rows_:
            for c_ in r_:
                if c_ not in order_:
                    order_.append(c_)
        smp = np.array([[order_.index(c) for c in r] for r in rows_])
        have = {tuple(np.roll(np.roll(smp, -i, 0), -j, 1)[:2, :2].ravel()) for i in range(len(smp))
                for j in range(len(smp))}
        wn = np.lib.stride_tricks.sliding_window_view(np.pad(fw, ((0, 1), (0, 1)), mode="wrap"), (2, 2)).reshape(-1, 4)
        ok_w = np.mean([tuple(w) in have for w in wn])
        rnd = np.random.default_rng(1).integers(0, 5, fw.shape)
        wr = np.lib.stride_tricks.sliding_window_view(rnd, (2, 2)).reshape(-1, 4)
        check(f"fields: a 128² WFC grid of the 5 field kinds; every 2 x 2 window, across the wrap too, is one of the "
              f"sample's ({ok_w:.1%}); negative control, random cells: {np.mean([tuple(w) in have for w in wr]):.0%}",
              fw.shape == (128, 128) and set(np.unique(fw)) == set(range(5)) and ok_w == 1.0
              and np.mean([tuple(w) in have for w in wr]) < 0.2)
    fwm = None
    ec = cap["got"].get("Ecology: seven weight layers + scatter densities")
    if ec is not None:
        gentle = ec["Nz"] > 0.98
        crop = gentle & (ec["farm"] > 0.6) & (ec["town"] < 0.1) & (np.rint(ec["field_id"]) >= 1)
        marg = gentle & (ec["farm"] > 0.6) & (ec["town"] < 0.1) & (np.rint(ec["field_id"]) == 0)
        ffc, ffm = float(ec["ForestFloor"][crop].mean()), float(ec["ForestFloor"][marg].mean())
        check(f"  the fields are cleared of woodland: ForestFloor {ffc:.3f} on {int(crop.sum())} crop pixels; "
              f"negative control, the margins between them (hedgerows, copses): {ffm:.3f}",
              crop.sum() > 2000 and marg.sum() > 1000 and ffc < 0.02 and ffm > 3 * ffc)
        fwm = ec["fieldw"][::-1].copy()                # image row 0 is the bottom; the stitched tiles start at the top
        del ec
    # the far view: the tree proxies as LOD chains ending in impostor cards, and their impostor atlases
    ad_ = os.path.join(WD, "assets")
    for a_ in ("Pine", "Broadleaf"):
        js_, nm_ = node_meshes(os.path.join(ad_, f"SM_Proxy_{a_}.glb"))
        t_ = [len(nm_[f"SM_Proxy_{a_}_LOD{i}"][2]) if f"SM_Proxy_{a_}_LOD{i}" in nm_ else 0 for i in range(3)]
        bc_ = img(os.path.join(ad_, f"T_Impostor_{a_}_BaseColor.png"))
        al_ = img(os.path.join(ad_, f"T_Impostor_{a_}_Alpha.png"))[..., 0] / 255.0
        nn_ = img(os.path.join(ad_, f"T_Impostor_{a_}_Normal.png"))[..., :3] / 255.0 * 2 - 1
        on_ = al_ > 0.5
        frames = [al_[j * 128:(j + 1) * 128, i * 128:(i + 1) * 128].mean() for i in range(8) for j in range(8)]
        check(f"{a_} proxy: SM_Proxy_{a_}.glb with LOD0 / LOD1 (≈40%) / LOD2 (two crossed cards) {t_}; an 8 x 8 "
              f"impostor atlas of 1024², the tree in every frame (coverage {min(frames):.2f}..{max(frames):.2f}), "
              f"unit normals on it",
              sorted(nm_) == [f"SM_Proxy_{a_}_LOD{i}" for i in range(3)] and t_[2] == 4 and 0.3 < t_[1] / t_[0] < 0.5
              and bc_.shape[:2] == (1024, 1024) and min(frames) > 0.05 and max(frames) < 0.95
              and abs(np.median(np.linalg.norm(nn_[on_], axis=-1)) - 1) < 0.05)
    # the previews' far view: from the valley camera, the trees beyond 500 m as impostor cards on their frames, the
    # towns at the LOD of their distance
    cq_, lq_ = cap["got"].get("Valley: cards' uv on their frame"), cap["got"].get("Valley: the towns at that LOD")
    check(f"preview far view (valley camera): {cq_ and cq_['n']} impostor cards, uv on the atlas "
          f"{cq_ and cq_['uv']} over {cq_ and cq_['frames']} frames; the towns' faces by LOD {lq_}",
          cq_ is not None and cq_["n"] > 5000 and cq_["uv"][0] >= 0 and cq_["uv"][1] <= 1 and cq_["frames"] >= 4
          and lq_ is not None and len(lq_) >= 2 and sum(lq_.values()) > 0)
    # grass (preview only): tufts around the road camera, dense at the camera, on the ground, off the road
    gg_ = cap["got"].get("Grass tufts")
    if gg_ is None:
        check("grass: the Grass tufts node ran", False)
    else:
        GP = gg_["P"].reshape(-1, 18, 3)
        base = GP[:, [0, 1, 3, 4, 6, 7, 9, 10, 12, 13, 15, 16]].mean(1)
        ntuft = len(base)
        rr = np.hypot(base[:, 0] - MW.CAM3[0], base[:, 2] - MW.CAM3[2])
        check(f"grass: {ntuft} tufts of six blades, all within 141 m of the road camera",
              30000 < ntuft < 90000 and gg_["prims"] == 6 * ntuft and rr.max() < 141.0, round(float(rr.max()), 1))
        near = (rr < 10).sum() / (np.pi * 100)
        far = ((rr > 60) & (rr < 100)).sum() / (np.pi * (100 ** 2 - 60 ** 2))
        check(f"  {near:.1f} per m² within 10 m of the camera, {far:.2f} per m² at 60-100 m (1 / distance², floor 2)",
              near > 5 * far and far > 0.2, (round(near, 2), round(far, 3)))
        dP_ = cap["got"].get("Close range: material terrain")
        if dP_ is not None:                        # the camera stands on the close-range terrain (2 m grid)
            x0_, x1_, z0_, z1_ = MW.DETAIL_WINDOW
            o_ = np.lexsort((dP_[:, 0], dP_[:, 2]))
            gh = dP_[o_, 1].reshape(int((z1_ - z0_) / 2) + 1, int((x1_ - x0_) / 2) + 1)
            from scipy.ndimage import map_coordinates
            ground = map_coordinates(gh, [(base[:, 2] - z0_) / 2, (base[:, 0] - x0_) / 2], order=1)
        else:
            ground = hgt(base[:, 0] + 2048, base[:, 2] + 2048)
        gz = np.abs(base[:, 1] + 0.04 - ground)
        check("  on the ground: tuft bases on the terrain they stand on (the close-range mesh; median < 0.15 m)",
              np.median(gz) < 0.15, round(float(np.median(gz)), 3))
        kr = cKDTree(RV[:, [0, 2]] - 2048.0)
        d_on = kr.query(base[:, [0, 2]])[0]
        ang = np.random.default_rng(3).random(ntuft) * 2 * np.pi
        ctrl = np.stack([MW.CAM3[0] + rr * np.cos(ang), MW.CAM3[2] + rr * np.sin(ang)], -1)
        d_ct = kr.query(ctrl)[0]
        check(f"  off the road: {np.mean(d_on < 2):.1%} of the tufts within 2 m of a centre line; negative control, "
              f"the same distances from the camera at random bearings: {np.mean(d_ct < 2):.1%}",
              np.mean(d_on < 2) < 0.01 and np.mean(d_ct < 2) > 0.05)
        check("  every blade carries the ground's up as N", np.allclose(gg_["N"], [0, 1, 0], atol=1e-5))
        del GP, base, gg_
    # close-range terrain: a 2 m mesh over the road view, meeting the 4 m full-map mesh without a crack at its border,
    # with the detail relief inside
    dP, cP = cap["got"].get("Close range: material terrain"), cap["got"].get("Material: terrain")
    if dP is None or cP is None:
        check("close-range terrain: both meshes ran", False)
    else:
        x0_, x1_, z0_, z1_ = MW.DETAIL_WINDOW
        nx, nz = int((x1_ - x0_) / 2) + 1, int((z1_ - z0_) / 2) + 1
        cg = cP[:1025 * 1025].reshape(1025, 1025, 3)          # rows: z = 2048 - 4 r; columns: x = 4 c - 2048

        def coarse(x, z):
            from scipy.ndimage import map_coordinates
            return map_coordinates(cg[..., 1], [(2048 - z) / 4, (x + 2048) / 4], order=1)
        brd = (np.abs(dP[:, 0] - x0_) < 0.01) | (np.abs(dP[:, 0] - x1_) < 0.01) | (np.abs(dP[:, 2] - z0_) < 0.01) \
            | (np.abs(dP[:, 2] - z1_) < 0.01)
        on4 = brd & (np.abs(np.mod(dP[:, 0], 4)) < 0.01) & (np.abs(np.mod(dP[:, 2], 4)) < 0.01)
        dbrd = np.abs(dP[on4, 1] - coarse(dP[on4, 0], dP[on4, 2]))
        inner = (dP[:, 0] > x0_ + 60) & (dP[:, 0] < x1_ - 60) & (dP[:, 2] > z0_ + 60) & (dP[:, 2] < z1_ - 60) \
            & (dP[:, 1] > 1.0)
        din = dP[inner, 1] - coarse(dP[inner, 0], dP[inner, 2])
        check(f"close-range terrain: {nx} x {nz} points on a 2 m grid; on its border it meets the full-map mesh "
              f"(max {dbrd.max():.3f} m); inside, the detail relief (std {din.std():.2f} m off the 4 m surface)",
              len(dP) == nx * nz and dbrd.max() < 0.1 and din.std() > 0.3,
              (len(dP), round(float(dbrd.max()), 3), round(float(din.std()), 3)))
        hole = (cg[..., 0] > x0_ + 0.5) & (cg[..., 0] < x1_ - 0.5) & (cg[..., 2] > z0_ + 0.5) & (cg[..., 2] < z1_ - 0.5)
        nm_ = cap["got"].get("Terrain: full map + close range")
        check("  the full-map mesh is cut where the close-range one lies (no double surface): merged = full map - "
              "its points inside the window + the close-range points", hole.sum() > 0
              and nm_ == 1025 * 1025 - int(hole.sum()) + nx * nz, (nm_, int(hole.sum())))
        del dP, cP, cg, din
    # the terrain layers: the library (seamless tiles), the splat maps (summing to 1 with the water, matching the
    # coarse weights) and the macro map (1x on average)
    LD = os.path.join(WD, "texture/layers")
    names = [n for n, _ in MW.LAYERS]
    lfiles = [f"T_Layer_{n}_{m}.png" for n in names for m in ("Color", "Normal_GL", "Height", "Roughness")]
    col = [img(os.path.join(LD, f"T_Layer_{n}_Color.png"))[..., :3].astype(float) / 255 for n in names]
    hts = [img(os.path.join(LD, f"T_Layer_{n}_Height.png"))[..., 0].astype(float) / 255 for n in names]
    nrm_ = [img(os.path.join(LD, f"T_Layer_{n}_Normal_GL.png"))[..., :2].astype(float) / 255 * 2 - 1 for n in names]

    def wrap_jump(a):
        return max(np.abs(a[:, 0] - a[:, -1]).mean() / max(np.abs(np.diff(a, axis=1)).mean(), 1e-9),
                   np.abs(a[0] - a[-1]).mean() / max(np.abs(np.diff(a, axis=0)).mean(), 1e-9))
    check(f"layer library: {len(names)} materials x 4 maps, 512², seamless when tiled (the wrapped jump within 2x a "
          "neighbour step), heights spanning 0..1, colour and relief in each",
          all(os.path.exists(os.path.join(LD, f)) for f in lfiles) and all(c.shape[:2] == (512, 512) for c in col)
          and all(wrap_jump(c) < 2.0 for c in col) and all(h.min() < 0.05 and h.max() > 0.95 for h in hts)
          and all(c.std() > 0.02 for c in col) and all(np.linalg.norm(n_, axis=-1).mean() > 0.02 for n_ in nrm_),
          [round(float(wrap_jump(c)), 2) for c in col])
    NSP = (len(MW.LAYERS) + 3) // 4
    SP = np.zeros((2048, 2048, 4 * NSP))
    MC = np.zeros((2048, 2048, 3))
    for i in range(4):
        for j in range(4):
            for k in range(NSP):
                t_ = img(os.path.join(WD, f"texture/T_Terrain_Splat{k}_x{i}_y{j}.png"))
                SP[j * 512:(j + 1) * 512, i * 512:(i + 1) * 512, 4 * k:4 * k + 4] = t_[..., :4] / 255.0
            MC[j * 512:(j + 1) * 512, i * 512:(i + 1) * 512] = \
                img(os.path.join(WD, f"texture/T_Terrain_Macro_x{i}_y{j}.png"))[..., :3] / 255.0
    ssum = SP.sum(-1)
    rs = np.minimum(((np.arange(1025) + 0.5) * 2048 / 1025).astype(int), 2047)
    sub_ = SP[np.ix_(rs, rs)]
    land = wfull["Water"] < 0.05
    check(f"splat maps: {NSP} RGBA x 16 tiles of 512², {len(MW.LAYERS)} weights that sum to 1 on land (the water "
          "takes the rest) and never above it", NSP == 4 and len(MW.LAYERS) == 13 and np.median(ssum[np.ix_(rs, rs)][land]) > 0.97
          and np.percentile(ssum, 99.9) < 1.06, (round(float(np.median(ssum[np.ix_(rs, rs)][land])), 3),
                                               round(float(np.percentile(ssum, 99.9)), 3)))
    rk_ = wfull["Rock"] > 0.8
    gr_ = wfull["Grass"] > 0.8
    gsoil = sub_[..., [0, 1, 2, 4]].sum(-1)              # grass, moss and the bare soil between
    check("  they follow the coarse weights: the rock layers where Rock > 0.8, grass / moss / soil where Grass > 0.8; "
          "negative control, each set is low where the other lies",
          sub_[..., 8:11].sum(-1)[rk_].mean() > 0.6 and gsoil[gr_].mean() > 0.6
          and sub_[..., 8:11].sum(-1)[gr_].mean() < 0.15 and gsoil[rk_].mean() < 0.3,
          (round(float(sub_[..., 8:11].sum(-1)[rk_].mean()), 2), round(float(gsoil[gr_].mean()), 2)))
    mland = MC[np.ix_(rs, rs)][land]
    check("  macro map: 1x on average over the land (stored halved: median about 0.5), and varied",
          0.35 < np.median(mland) < 0.65 and mland.std() > 0.03, (round(float(np.median(mland)), 3),
                                                                round(float(mland.std()), 3)))
    ci_ = [n for n, _ in MW.LAYERS].index("Crops")
    if fwm is not None and fwm.shape == sub_.shape[:2]:
        on_, off_ = (fwm > 0.8) & land, (fwm < 0.05) & land
        cf_, co_ = float(sub_[..., ci_][on_].mean()), float(sub_[..., ci_][off_].mean())
        check(f"  Crops (layer {ci_ + 1}): {cf_:.2f} on the fields ({int(on_.sum())} px); negative control, off "
              f"them: {co_:.3f}", on_.sum() > 1000 and cf_ > 0.6 and co_ < 0.02)
    else:
        check("  Crops: the ecology's field weight was captured at the map's size", False,
              None if fwm is None else fwm.shape)
    del SP, MC, ssum, sub_, mland, hts, gsoil
    # the stitched 4096² images and the decoded tiles are a gigabyte or two: let them go before the next pipeline
    del BC, NM, nv, lnv, BCs, bct, nmt, wfull, tiles, full, st, Hm, rows, RV, rl, col, nrm_
    api = res = None
    gc.collect()
    _mt.trim()

    # ═══════════════════════════════════════════════ 1. Material library (before the kit: its textures point to it)
    sec("Material library")
    api, res, pr, dt = run("pcg_prod_material_library", CWD)
    check(f"runs ({len(api)} nodes, {dt:.1f} s), UI self-check clean", not pr, pr[:2])
    MD = os.path.join(OUT, "pcg/materials")
    mats = tuple(m[0] for m in MW.MATERIALS)
    # the facade-bay images (one whole 4 m × 3.5 m bay for the context buildings) repeat by design at the bay edge,
    # where the floor band meets the next bay's wall: they are not part of the seam test
    tileable = tuple(m for m in mats if not m.startswith("M_FacadeFar"))
    maps = ("BaseColor", "Normal_GL", "Normal_DX", "ORM", "Height")
    files = {(m, k): os.path.join(MD, f"T_{m}_{k}.png") for m in mats for k in maps}
    check(f"all {len(mats)} sets × 5 maps written, 1024²", len(mats) == 14 and
          all(os.path.exists(f) and img(f).shape[:2] == (1024, 1024) for f in files.values()))
    check("  every image has a .json next to it (Height's range is in it)",
          all(os.path.exists(f[:-4] + ".json") for f in files.values())
          and json.load(open(files[("M_Wall", "Height")][:-4] + ".json"))["range"] is not None)

    def seam_ratio(a):
        a = a.astype(np.float64)
        inner = np.abs(np.diff(a, axis=1)).mean()
        wrap = np.abs(a[:, 0] - a[:, -1]).mean()
        inner_v = np.abs(np.diff(a, axis=0)).mean()
        wrap_v = np.abs(a[0] - a[-1]).mean()
        return max(wrap / max(inner, 1e-9), wrap_v / max(inner_v, 1e-9))

    rs = {m: max(seam_ratio(img(files[(m, k)])) for k in ("BaseColor", "Height", "ORM"))
          for m in tileable}
    check("seamless on all four edges: the jump across the wrapped column / row ≤ 2× the jump between neighbouring columns / rows",
          all(r < 2.0 for r in rs.values()), {k: round(v, 2) for k, v in rs.items()})
    bc = img(files[("M_Wall", "BaseColor")])
    check("  negative control: cropping off the right 30% and comparing again, the seam shows",
          seam_ratio(bc[:, :700]) > 3.0, round(seam_ratio(bc[:, :700]), 2))
    okdx, okn = True, True
    for m in mats:
        gl = img(files[(m, "Normal_GL")]).astype(int)
        dx = img(files[(m, "Normal_DX")]).astype(int)
        okdx &= (np.abs(dx[..., 1] - (255 - gl[..., 1])) <= 1).all() \
            and np.array_equal(dx[..., 0], gl[..., 0]) and np.array_equal(dx[..., 2], gl[..., 2])
        n = gl / 255.0 * 2 - 1
        ln = np.linalg.norm(n, axis=-1)
        okn &= abs(ln.mean() - 1) < 0.02 and (n[..., 2] > 0).mean() > 0.99
    check("Normal_DX's G = 255 - Normal_GL's G, R and B bit-identical", okdx)
    check("  normals decode to unit length, pointing outwards (z > 0)", okn)
    orm = {m: img(files[(m, "ORM")]) for m in mats}
    check("ORM: metalness 0 in brick, cobbles, trim, glass and sign; full (255) where the roof is chipped and on "
          "the steel's scratches",
          all((orm[m][..., 2] == 0).mean() > 0.99 for m in ("M_Wall", "Ground_Cobble", "M_Trim", "M_Glass", "M_Sign",
                                                            "M_BrickBuff", "M_Stucco", "Ground_Asphalt", "M_RoofFlat"))
          and (orm["M_Roof"][..., 2] >= 250).mean() > 0.02
          and 0.002 < (orm["M_Metal"][..., 2] > 128).mean() < 0.15,
          round(float((orm["M_Metal"][..., 2] > 128).mean()), 4))
    check("  glass is the smoothest material (clean glass roughness ~0.04), cobble joints / brick the roughest",
          np.percentile(orm["M_Glass"][..., 1], 10) < 20
          and orm["M_Glass"][..., 1].mean() < min(orm[m][..., 1].mean() for m in mats if m != "M_Glass")
          and orm["M_Wall"][..., 1].mean() > 200,
          {m: int(orm[m][..., 1].mean()) for m in mats})

    # pcg111: real-size relief. Height is written in metres (Height to Normal / AO at Strength 1, World Size 1 m), so
    # the .json range is the relief in metres; joints are measured on the height map itself
    def hmetres(m):
        h = img(files[(m, "Height")]).astype(np.float64)
        h = h[..., 0] if h.ndim == 3 else h
        lo, hi = json.load(open(files[(m, "Height")][:-4] + ".json"))["range"]
        return lo + h / 65535.0 * (hi - lo)
    hw = hmetres("M_Wall")
    joint = hw < -0.005
    rows_j = joint.mean(1)
    # a horizontal bed joint row is mostly joint; count joint rows per metre and their width
    bed = rows_j > 0.6
    sh = int(np.argmin(bed))                    # roll so the image starts on a brick row: a joint split by the border is whole
    bedr = np.roll(bed, -sh)
    runs = np.diff(np.concatenate([[0], bedr.astype(int), [0]]))
    widths = (np.nonzero(runs == -1)[0] - np.nonzero(runs == 1)[0])
    check("brick: 13 bed joints per metre, each 8-16 mm wide (1024 px = 1 m), struck 6-10 mm back",
          len(widths) == 13 and 8 <= np.median(widths) <= 16
          and 0.006 <= np.median(hw[bed]) * -1 + np.median(hw[~joint]) <= 0.010,
          (len(widths), int(np.median(widths)), round(float(np.median(hw[~joint]) - np.median(hw[bed])), 4)))
    check("  joints take 15-30 % of the wall (the old library's were a third, reading beige from afar)",
          0.15 < joint.mean() < 0.30, round(float(joint.mean()), 3))
    bw = img(files[("M_Wall", "BaseColor")]).astype(np.float64) / 255
    check("  brick faces are saturated red-orange in sRGB (BaseColor is not encoded twice): R − B > 0.25 on bricks",
          (bw[..., 0] - bw[..., 2])[~joint].mean() > 0.25, round(float((bw[..., 0] - bw[..., 2])[~joint].mean()), 3))
    hc = hmetres("Ground_Cobble")
    check("cobbles: domed, 3-6 cm from joint bottom to stone top",
          0.03 <= np.percentile(hc, 99) - np.percentile(hc, 1) <= 0.06,
          round(float(np.percentile(hc, 99) - np.percentile(hc, 1)), 4))
    rng = {m: json.load(open(files[(m, "Height")][:-4] + ".json"))["range"] for m in mats}
    check("  glass is flat to under a millimetre, the roof's standing seams are 2-3 cm tall",
          rng["M_Glass"][1] - rng["M_Glass"][0] < 0.001 and 0.02 < rng["M_Roof"][1] - rng["M_Roof"][0] < 0.03,
          {m: round(rng[m][1] - rng[m][0], 4) for m in ("M_Glass", "M_Roof")})
    check("  the door studs have metalness, but only a little",
          0 < (orm["M_Door"][..., 2] > 128).mean() < 0.02,
          round(float((orm["M_Door"][..., 2] > 128).mean()), 4))
    check("  AO mostly bright, roughness in a sensible range (glass apart: it is meant to be near 0)",
          all(orm[m][..., 0].mean() > 150 and (m == "M_Glass" or 40 < orm[m][..., 1].mean() < 250) for m in mats),
          [(int(orm[m][..., 0].mean()), int(orm[m][..., 1].mean())) for m in mats])

    # ═══════════════════════════════════════════════ 2. Modular buildings
    sec("Modular buildings")
    res = api = None                    # let the previous pipeline's node outputs go before the next one runs
    gc.collect()
    api, res, pr, dt = run("pcg_prod_modular_city", CWD)
    check(f"runs ({len(api)} nodes, {dt:.1f} s), UI self-check clean", not pr, pr[:2])
    KD = os.path.join(OUT, "pcg/assets/kit")
    kit = {os.path.basename(p)[:-4]: p for p in glob.glob(os.path.join(KD, "SM_Kit_*.glb"))}
    names = ["Wall_Plain", "Wall_Window", "Wall_WindowPair", "Wall_Door", "Wall_Balcony", "Wall_Shopfront",
             "Corner_Pillar", "Roof_Cornice", "Roof_Flat", "Roof_Unit", "Roof_Tank"]
    check(f"one glb for each of the {len(names)} kit pieces", sorted(kit) == sorted("SM_Kit_" + n for n in names))
    okp, info = True, {}
    for n in names:
        js, nm = node_meshes(kit["SM_Kit_" + n])
        Pk = np.concatenate([v[0] for v in nm.values()])
        lo, hi = Pk.min(0), Pk.max(0)
        info[n] = (np.round(lo, 2).tolist(), np.round(hi, 2).tolist())
        if n.startswith("Wall_"):
            okp &= abs(lo[0] + 2) < 1e-4 and abs(hi[0] - 2) < 1e-4 and abs(lo[1]) < 1e-4 \
                and abs(hi[1] - 3.5) < 1e-4 and abs(lo[2] + 0.3) < 1e-3 and hi[2] >= -1e-4
        elif n == "Roof_Flat":
            okp &= abs(hi[1]) < 1e-4 and np.allclose([lo[0], lo[2], hi[0], hi[2]], [-2, -2, 2, 2])
        else:
            okp &= abs(lo[1]) < 1e-4 and abs(lo[0] + hi[0]) < 1e-3
    check("pivot convention: wall 4 m wide, 3.5 m high, bottom edge midpoint at the origin, wall thickness towards -Z, facade details on the +Z side",
          okp, "" if okp else info)
    okv = True
    for n in names:
        vr = validate(kit["SM_Kit_" + n])
        if vr is not None:
            okv &= vr["errors"] == 0 and vr["warnings"] == 0
    uris = sorted({i["uri"] for n in names for i in node_meshes(kit["SM_Kit_" + n])[0].get("images", [])})
    check("  every material slot's textures point to the material library (relative paths, files all present)",
          "../../materials/T_M_Door_BaseColor.png" in uris and "../../materials/T_M_Glass_BaseColor.png" in uris
          and all(os.path.exists(os.path.join(KD, u)) for u in uris), uris[:3])
    check(f"  glTF validator (with external textures): all {len(names)} with 0 errors 0 warnings", okv)
    want = {"Wall_Window": {"M_Wall", "M_Trim", "M_Glass"}, "Wall_Door": {"M_Wall", "M_Trim", "M_Door", "M_Metal"},
            "Wall_WindowPair": {"M_Wall", "M_Trim", "M_Glass", "M_Metal"}, "Roof_Flat": {"M_RoofFlat"},
            "Roof_Unit": {"M_Trim", "M_Metal"}, "Roof_Tank": {"M_Roof", "M_Metal"},
            "Wall_Balcony": {"M_Wall", "M_Trim", "M_Glass", "M_Metal"},
            "Wall_Shopfront": {"M_Wall", "M_Trim", "M_Glass", "M_Metal", "M_Sign"}}
    got = {n: {m.get("name") for m in node_meshes(kit["SM_Kit_" + n])[0].get("materials", [])} for n in want}
    check("  kit detail: window frames / door casings / railings / shopfront frames carry their material slots",
          all(got[n] == want[n] for n in want), {n: sorted(got[n]) for n in want if got[n] != want[n]})

    rows = list(csv.DictReader(open(os.path.join(KD, "Block_Instances.csv"), encoding="utf-8")))
    check("the instance table's assets are all exported glb names (SM_Kit_*)",
          rows and all(r["asset"] in kit for r in rows),
          sorted({r["asset"] for r in rows} - set(kit))[:3])
    key = [(r["asset"], *(round(float(r[c]), 3) for c in ("px", "py", "pz", "ry"))) for r in rows]
    check("  no two identical placements", len(set(key)) == len(key), len(key) - len(set(key)))
    # recompute the footprint by the workflow's rules (4 m cells; a cell counts if its center falls within the extent)
    GX, GZ = MW.CITY_GRID["size_x"] / 2, MW.CITY_GRID["size_z"] / 2
    NX, NZ = MW.CITY_GRID["cols"] - 1, MW.CITY_GRID["rows"] - 1
    cx = -GX + 4 * np.arange(NX) + 2.0
    cz = -GZ + 4 * np.arange(NZ) + 2.0
    X, Z = np.meshgrid(cx, cz, indexing="ij")
    B = np.full(X.shape, -1)
    floors = {}
    for b_, x0, x1, z0, z1, fl in MW.CITY_LOTS:
        inside = (X >= x0) & (X <= x1) & (Z >= z0) & (Z <= z1)
        B = np.where(inside, max(b_, -1), B)
        if b_ >= 0:
            floors[b_] = fl

    def occ(x, z):
        i = int(np.floor((x + GX) / 4))
        j = int(np.floor((z + GZ) / 4))
        return B[i, j] if 0 <= i < B.shape[0] and 0 <= j < B.shape[1] else -1

    edges = 0
    for b, f in floors.items():
        for i, j in zip(*np.nonzero(B == b)):
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ii, jj = i + di, j + dj
                if not (0 <= ii < B.shape[0] and 0 <= jj < B.shape[1]) or B[ii, jj] != b:
                    edges += f
    walls = [r for r in rows if r["asset"].startswith("SM_Kit_Wall_")]
    check("wall count = footprint outline edge count × floor count (recomputed with numpy by the rules)", len(walls) == edges,
          (len(walls), edges))
    okw, oncorner = True, 0
    for r in walls:
        x, y, z = float(r["px"]), float(r["py"]), float(r["pz"])
        qx, qy, qz, qw = (float(r[c]) for c in ("qx", "qy", "qz", "qw"))
        # local +Z to world: the x, z components of R·(0, 0, 1)
        n = np.array([2 * (qx * qz + qw * qy), 1 - 2 * (qx * qx + qy * qy)])
        fx, fz = (x + GX) / 4 % 1, (z + GZ) / 4 % 1
        if min(fx, 1 - fx) < 1e-3 and min(fz, 1 - fz) < 1e-3:
            oncorner += 1
        b = int(r["bld"])
        okw &= occ(x - 1.0 * n[0], z - 1.0 * n[1]) == b and occ(x + 1.0 * n[0], z + 1.0 * n[1]) != b
        okw &= abs(y - 3.5 * int(r["floor"])) < 1e-3
    check("  every wall: the cell behind is this building, the cell in front is not (facade faces outwards), y = floor number × 3.5", okw)
    check("  no wall lands on a grid point (corner) -- all at the midpoint of a 4 m edge", oncorner == 0, oncorner)
    eul = np.array([[float(r[c]) for c in ("rx", "ry", "rz")] for r in walls])
    check("  walls only rotate about Y: Euler angles written as (0, ry, 0), 180° rotations not written as (180, 0, 180)",
          np.allclose(eul[:, [0, 2]], 0, atol=1e-4), np.unique(np.round(eul, 1), axis=0)[:4].tolist())
    pil = [r for r in rows if r["asset"] == "SM_Kit_Corner_Pillar"]
    check("corner pillars all on grid points", pil and all(
        min((float(r["px"]) + GX) / 4 % 1, 1 - (float(r["px"]) + GX) / 4 % 1) < 1e-3
        and min((float(r["pz"]) + GZ) / 4 % 1, 1 - (float(r["pz"]) + GZ) / 4 % 1) < 1e-3
        for r in pil))
    roofs = [r for r in rows if r["asset"] == "SM_Kit_Roof_Flat"]
    check("  one roof piece per cell, elevation = floor count × 3.5",
          len(roofs) == int((B >= 0).sum()) and all(
              abs(float(r["py"]) - 3.5 * floors[int(r["bld"])]) < 1e-3 for r in roofs))
    plant = [r for r in rows if r["asset"] in ("SM_Kit_Roof_Unit", "SM_Kit_Roof_Tank")]
    check("  rooftop plant: some, on the roofs (y = floor count × 3.5, inside the building's cells), tanks only on "
          "buildings of 5+ floors",
          0 < len(plant) < len(roofs) * 0.3 and all(
              abs(float(r["py"]) - 3.5 * floors[int(r["bld"])]) < 1e-3 and occ(float(r["px"]), float(r["pz"])) == int(r["bld"])
              for r in plant) and all(floors[int(r["bld"])] >= 5 for r in plant if r["asset"] == "SM_Kit_Roof_Tank"),
          len(plant))
    check("the table's facade column is the building's variant (CITY_FACADE); render facades use paired windows",
          all(int(r["facade"]) == MW.CITY_FACADE.get(int(r["bld"]), 0) for r in walls + roofs)
          and all(r["asset"] != "SM_Kit_Wall_Window" for r in walls if int(r["facade"]) == 2)
          and any(r["asset"] == "SM_Kit_Wall_WindowPair" for r in walls)
          and all(r["asset"] != "SM_Kit_Wall_WindowPair" for r in walls if int(r["facade"]) != 2))

    # ═══════════════════════════════════════════════ 3. Rock assets
    sec("Rock assets")
    res = api = None                    # let the previous pipeline's node outputs go before the next one runs
    gc.collect()
    api, res, pr, dt = run("pcg_prod_rock_assets", CWD)
    check(f"runs ({len(api)} nodes, {dt:.1f} s), UI self-check clean", not pr, pr[:2])
    RD = os.path.join(OUT, "pcg/assets/rocks")
    rocks = sorted(glob.glob(os.path.join(RD, "SM_Rock_*.glb")))
    check("one glb for each of the 4 rocks", [os.path.basename(p) for p in rocks]
          == [f"SM_Rock_{k:02d}.glb" for k in range(4)])
    ok_nodes = ok_lod = ok_share = ok_uv = ok_ucx = ok_piv = ok_tex = ok_nrm = ok_v = True
    tris, flips, ucx_sz = [], [], []
    for k, path in enumerate(rocks):
        a = f"SM_Rock_{k:02d}"
        js, nm = node_meshes(path)
        ucx = [n for n in nm if n.startswith(f"UCX_{a}_")]
        ok_nodes &= all(f"{a}_LOD{i}" in nm for i in range(3)) and 1 <= len(ucx) <= 4 \
            and len(nm) == 3 + len(ucx)
        t = [len(nm[f"{a}_LOD{i}"][2]) for i in range(3)]
        tris.append(t)
        ok_lod &= t[0] > t[1] > t[2] and 0.4 < t[1] / t[0] < 0.6 and 0.12 < t[2] / t[0] < 0.28
        P0, U0, I0, _ = nm[f"{a}_LOD0"]
        w0 = {tuple(x) for x in np.round(np.concatenate([P0, U0], 1), 4)}
        for i in (1, 2):
            Pi, Ui, _, _ = nm[f"{a}_LOD{i}"]
            ok_share &= all(tuple(x) in w0 for x in np.round(np.concatenate([Pi, Ui], 1), 4))
        ok_uv &= U0.min() >= -1e-6 and U0.max() <= 1 + 1e-6
        u = U0[I0]
        sa = (u[:, 1, 0] - u[:, 0, 0]) * (u[:, 2, 1] - u[:, 0, 1]) \
            - (u[:, 2, 0] - u[:, 0, 0]) * (u[:, 1, 1] - u[:, 0, 1])
        flips.append(float(min((sa > 0).mean(), (sa < 0).mean())))
        for n in ucx:
            Pc, _, Ic, _ = nm[n]
            a_, b_, c_ = Pc[Ic[:, 0]], Pc[Ic[:, 1]], Pc[Ic[:, 2]]
            fn = np.cross(b_ - a_, c_ - a_)
            ln = np.linalg.norm(fn, axis=1)
            fn, a_ = fn[ln > 1e-12] / ln[ln > 1e-12, None], a_[ln > 1e-12]
            d = np.einsum("fk,fpk->fp", fn, Pc[None] - a_[:, None])
            ok_ucx &= d.max() < 1e-3 * np.ptp(Pc, 0).max()
            ucx_sz.append((len(np.unique(np.round(Pc, 6), axis=0)), len(Ic)))
        lo, hi = P0.min(0), P0.max(0)
        ok_piv &= abs(lo[1] + 0.5) < 0.05 and abs(lo[0] + hi[0]) < 0.6 and abs(lo[2] + hi[2]) < 0.6
        mt = js["materials"]
        ok_tex &= len(mt) == 1 and mt[0]["name"] == f"Rock_{k:02d}"
        uris = [im["uri"] for im in js.get("images", [])]
        ok_tex &= sorted(uris) == sorted(f"T_Rock_{k:02d}_{s}.png" for s in ("BaseColor", "Normal", "ORM"))
        ok_tex &= all(img(os.path.join(RD, u)).shape[:2] == (1024, 1024) for u in uris)
        nmap = img(os.path.join(RD, f"T_Rock_{k:02d}_Normal.png")) / 255.0 * 2 - 1
        cov = np.abs(nmap - np.array([0, 0, 1])).sum(-1) > 0.02     # the baked area
        ln = np.linalg.norm(nmap[cov], axis=-1)
        ok_nrm &= abs(ln.mean() - 1) < 0.03 and (nmap[cov][:, 2] > 0).mean() > 0.97
        vr = validate(path)
        if vr is not None:
            ok_v &= vr["errors"] == 0 and vr["warnings"] == 0
    check("in every glb: LOD0 / LOD1 / LOD2 + 1~4 UCX_<asset name>_NN", ok_nodes)
    check("  triangle counts LOD0 > LOD1 (≈50%) > LOD2 (≈20%)", ok_lod, tris)
    check("  every (position, uv) of LOD1 / LOD2 is in LOD0 -- the three LODs share one texture set", ok_share)
    check("  uv all within 0..1, flipped triangles < 0.5%", ok_uv and max(flips) < 0.005,
          [round(f, 4) for f in flips])
    check("  every UCX is convex (all points on the inner side of every face)", ok_ucx)
    check("  collision is simplified: every UCX has at most 32 points / 60 triangles (Unity's convex limit is 255)",
          ucx_sz and max(v for v, _ in ucx_sz) <= 32 and max(t for _, t in ucx_sz) <= 60, ucx_sz[:4])
    check("  pivot: flat bottom at y = -0.5, roughly centered horizontally", ok_piv)
    check("  one material slot Rock_NN, its three textures all present, 1024²", ok_tex)
    check("  the normal map decodes to unit length, pointing outwards", ok_nrm)
    check("  glTF validator (with external textures): 0 errors 0 warnings", ok_v)
    hj = json.load(open(os.path.join(RD, "T_Rock_Height.json"), encoding="utf-8"))
    check("the height map sidecar is called T_Rock_Height.json, all four are listed in it, range is the real displacement",
          len(hj["files"]) == 4 and hj["range"][0] < 0 < hj["range"][1])


print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
