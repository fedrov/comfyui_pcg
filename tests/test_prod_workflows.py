"""
pcg84: actually runs the four "production" pipelines (rock assets / open-world terrain tiles / modular buildings / material library),
checking the deliverables themselves -- i.e. the files the engine side really reads -- rather than intermediate results inside the nodes.

References do not rely on the implementation under test: images read back with PIL, glb parsed independently (same parser as test_exporters),
CSV read with the csv module; expected values come from the conventions stated in the workflows (or are recomputed with numpy):

  rocks      one glb per rock: LOD0 > LOD1 > LOD2 > collision, every (position, uv) of LOD1 / LOD2 is in LOD0
         (the precondition for sharing one texture set), uv within 0..1, almost no flipped faces; every UCX is convex; one material slot,
         the files the texture uris point to really exist, 1024²; the normal map decodes to unit vectors pointing outwards (z > 0);
         pivot convention (flat bottom at y = -0.5, centered horizontally); Khronos validator (if installed) 0 errors
  terrain    16 tiles of 513² height PNGs (2 m), shared edges of neighbouring tiles bit-identical, stitched back = the full r16 image; the six weight layers
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
         no duplicate placements; the material library runs first, then the kit's glb are validated and all textures are found;
         every glb holds LOD0, a lighter LOD1 and a convex UCX with LOD0's bounds; shops, the podium, one balcony style per
         building and the stair cores recomputed from the rules (negative controls: the far side street has no shops, a mixed
         balcony set is not one style); pcg/city/World.json read by the Unreal importer's own functions, every asset found
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


def obj_lines_pts(path):
    """The vertices an OBJ's polylines use."""
    v_, u_ = [], set()
    for ln in open(path, encoding="utf-8"):
        if ln.startswith("v "):
            v_.append([float(t) for t in ln.split()[1:4]])
        elif ln.startswith("l "):
            u_.update(int(t) - 1 for t in ln.split()[1:])
    return np.array(v_)[sorted(u_)]


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


# the image-model nodes of a workflow's muted AI group, as stubs that record what they were given (no model here)
CONCEPT = {"control": [], "sample": None, "encode": None, "webp": None}


def _stub(fn, returns):
    class _S:
        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {}}
        RETURN_TYPES = returns
        FUNCTION = "run"

        def run(self, **kw):
            return fn(**kw)
    return _S


def _scale(image, upscale_method, width, height, crop):
    import torch.nn.functional as tF
    x = image.permute(0, 3, 1, 2)
    if crop == "center":
        h_, w_ = x.shape[2], x.shape[3]
        r_ = width / height
        if w_ / h_ > r_:
            c_ = int(round(h_ * r_))
            x = x[..., (w_ - c_) // 2:(w_ - c_) // 2 + c_]
        else:
            c_ = int(round(w_ / r_))
            x = x[..., (h_ - c_) // 2:(h_ - c_) // 2 + c_, :]
    return (tF.interpolate(x, size=(height, width), mode="area").permute(0, 2, 3, 1),)


def _apply(positive, negative, control_net, image, strength, start_percent, end_percent, vae=None):
    CONCEPT["control"].append((control_net.get("type"), np.asarray(image[0]).copy(), strength, end_percent))
    return (positive + [control_net.get("type")], negative)


def _sample(model, seed, steps, cfg, sampler_name, scheduler, positive, negative, latent_image, denoise):
    CONCEPT["sample"] = {"denoise": denoise, "conds": positive, "latent": latent_image}
    return ({"from": latent_image},)


def _encode(pixels, vae):
    CONCEPT["encode"] = tuple(pixels.shape)
    return ({"pixels": tuple(pixels.shape)},)


def _decode(samples, vae):
    import torch as _t
    s_ = samples["from"]["pixels"]
    return (_t.zeros(s_),)


CONCEPT_STUBS = {
    "CheckpointLoaderSimple": _stub(lambda ckpt_name: ("MODEL", "CLIP", "VAE"), ("MODEL", "CLIP", "VAE")),
    "CLIPTextEncode": _stub(lambda text, clip: ([text],), ("CONDITIONING",)),
    "ControlNetLoader": _stub(lambda control_net_name: ({"name": control_net_name},), ("CONTROL_NET",)),
    "SetUnionControlNetType": _stub(lambda control_net, type: (dict(control_net, type=type),), ("CONTROL_NET",)),
    "ImageScale": _stub(_scale, ("IMAGE",)),
    "ControlNetApplyAdvanced": _stub(_apply, ("CONDITIONING", "CONDITIONING")),
    "VAEEncode": _stub(_encode, ("LATENT",)),
    "KSampler": _stub(_sample, ("LATENT",)),
    "VAEDecode": _stub(_decode, ("IMAGE",)),
    "SaveAnimatedWEBP": _stub(lambda images, filename_prefix, fps, lossless, quality, method: (
        CONCEPT.__setitem__("webp", (tuple(images.shape), filename_prefix, fps)) or ()), ()),
}


def run(name, cwd, release=False, capture=None, unmute=None, patch=None):
    """capture: {node title: fn(outputs) -> summary}; the summaries go to capture["got"] (the outputs themselves are
    not kept, so a release run stays released). unmute: a title prefix; those (muted) nodes run, image-model nodes
    as recording stubs."""
    wf = MW.WORKFLOWS[name]().to_ui()
    if unmute:
        for n_ in wf["nodes"]:
            if str(n_.get("title") or "").startswith(tuple(unmute) if isinstance(unmute, (list, tuple)) else unmute):
                n_["mode"] = 0
    pr = MW.validate_ui(wf)
    api = MW.ui_to_api(wf)
    for t_, kv_ in (patch or {}).items():            # widget values by node title (the API format names them)
        for n_ in wf["nodes"]:
            if n_.get("title") == t_ and str(n_["id"]) in api:
                api[str(n_["id"])]["inputs"].update(kv_)
    classes = dict(MAP)
    classes.update(CONCEPT_STUBS)
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
        up_ = (part_ != "plinth") & (part_ != "yardwall")       # the walls' feet: not the plinth nor the yard walls
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
                "floors": floors_, "tc": attr_("tc_avg"), "rf": attr_("rf"),
                "street": np.asarray(g_.get(PRIM, "street"), np.float64)[first_][:, [0, 2]],
                "front": np.asarray(g_.get(PRIM, "front"), np.float64)[first_][:, [0, 2]], "door_c": fc_[pp_ == "door"], "door_b": bp_[pp_ == "door"],
                "wall_c": fc_[pp_ == "wall"], "wall_b": bp_[pp_ == "wall"], "gable": int((md_ == "gable").sum()),
                "roof_top": rt_,
                "modules": {str(k): int((md_ == k).sum()) for k in np.unique(md_)},
                "lshape": int((np.bincount(bp_[pp_ == "plinth"], minlength=nb_) == 6).sum()),
                "lflat": int(sum(1 for k_ in np.nonzero(np.bincount(bp_[pp_ == "plinth"], minlength=nb_) == 6)[0]
                                 for i in np.nonzero((pp_ == "roof") & (bp_ == k_))[0]
                                 if np.ptp(P_[vp_[off_[i]:off_[i + 1]], 1]) < 1e-6)),
                "side": np.asarray(g_.get(PRIM, "side"), np.float64)[first_][:, [0, 2]],
                "door_n": np.array([np.cross(P_[vp_[off_[i] + 1]] - P_[vp_[off_[i]]],
                                             P_[vp_[off_[i] + 2]] - P_[vp_[off_[i]]])[[0, 2]]
                                    for i in np.nonzero(pp_ == "door")[0]]).reshape(-1, 2),
                "parts": {str(k): int((pp_ == k).sum()) for k in np.unique(pp_)}}

    def _shot(out):
        a_ = np.asarray(out[0]).astype(np.float32)
        return {"shape": a_.shape, "img": a_[0, ::4, ::4].copy(), "frames": [a_[i, ::4, ::4].copy() for i in range(min(len(a_), 4))]}

    def _cards(out):
        g_ = out[0]
        uv_ = np.asarray(g_.get(POINT, "uv"), np.float64)
        fw_ = g_.get(POINT, "fw")
        return {"n": g_.nprims, "uv": (float(uv_[:, :2].min()), float(uv_[:, :2].max())),
                "fw": None if fw_ is None else (float(np.asarray(fw_).sum(1).min()), float(np.asarray(fw_).sum(1).max()),
                                                 float((np.asarray(fw_).max(1) < 0.999).mean())),
                "frames": len(np.unique(np.floor(uv_[:, :2].reshape(-1, 4, 2).mean(1) * 8), axis=0))}

    def _lods(out):
        g_ = out[0]
        lv_ = np.asarray(g_.get(PRIM, "lod")).reshape(-1)
        return {int(k): int((lv_ == k).sum()) for k in np.unique(lv_)}

    def _lanes(out):
        g_ = out[0]
        P_ = np.asarray(g_.get(POINT, "P"), np.float64)
        vp_, off_ = np.asarray(g_.vertex_point), np.asarray(g_.prim_offset)
        return np.array([[P_[vp_[off_[i]], [0, 2]], P_[vp_[off_[i + 1] - 1], [0, 2]]] for i in range(g_.nprims)])

    def _towns(out):
        return np.asarray(out[0].get(POINT, "P"), np.float64)[:, [0, 2]].copy()

    def _wfc(out):
        from comfyui_pcg.geo.cop.pixel import getn as _g
        return np.rint(_g(out[0], "field_id")[::8, ::8, 0]).astype(int)

    def _eco(out):
        from comfyui_pcg.geo.cop.pixel import getn as _g
        return {k: _g(out[0], k)[..., 0].astype(np.float32) for k in ("farm", "field_id", "town", "ForestFloor", "N", "fieldw", "tring", "upb")} | {
            "Nz": _g(out[0], "N")[..., 2].astype(np.float32)}
    cap = {"Grass tufts": _grass, "Close range: material terrain": _pts, "Material: terrain": _pts,
           "Terrain: full map + close range": lambda out: out[0].npoints,
           "Buildings (Building Generator)": _bld, "Towns: numbered": _towns, "Lanes": lambda out: _lanes(out), "Valley: cards' uv on their frame": _cards,
           "Valley: the towns at that LOD": _lods, "Fields: WFC over the map (128² cells, tileable)": _wfc,
           "Ecology: seven weight layers + scatter densities": _eco,
           "Road: the preview": _shot, "Valley: the preview": _shot, "Dusk: the preview": _shot,
           "Rain: the preview": _shot, "Snow: the preview": _shot, "Flyby: the frames": _shot}
    api, res, pr, dt = run("pcg_prod_world_tiles", CWD, release=True, capture=cap, unmute=("Concept:", "Flyby:"),
                           patch={"Flyby: 240 cameras along it (looking 150 m ahead)": dict(frames=3, resolution_x=160,
                                                                                            resolution_y=90),
                                  "Flyby: the frames": dict(width=160, height=90)})
    check(f"runs ({len(api)} nodes, {dt:.1f} s), UI self-check clean", not pr, pr[:2])
    WD = os.path.join(OUT, "pcg/world")
    # AI: the road view's render, depth and normal saved; the Concept group (unmuted here, the image model stubbed)
    # gets the depth and normal as ControlNet images and the render as the starting image
    svd = {p_: sh_ for p_, sh_ in IMGS if p_ and p_.startswith("pcg/world/concept/")}
    ctl = {t_: (im_, st_, en_) for t_, im_, st_, en_ in CONCEPT["control"]}
    dpt, nrm = (ctl.get("depth") or (None,))[0], (ctl.get("normal") or (None,))[0]
    ok_c = dpt is not None and nrm is not None and dpt.shape == (768, 1344, 3) and nrm.shape == (768, 1344, 3)
    check(f"AI: the road view's render, depth and normal saved at 1600 x 900 ({sorted(svd)}); the concept group: "
          f"depth (strength {ctl.get('depth', (0, 0))[1]}) then normal ({ctl.get('normal', (0, 0))[1]}) ControlNets on "
          f"1344 x 768 crops, the render encoded as the start ({CONCEPT['encode']}), denoise "
          f"{(CONCEPT['sample'] or {}).get('denoise')}, saved",
          all(svd.get(f"pcg/world/concept/{k_}") == (1, 900, 1600, 3) for k_ in ("Road_render", "Road_depth", "Road_normal"))
          and "pcg/world/concept/Concept_Road" in svd and ok_c and CONCEPT["encode"] == (1, 768, 1344, 3)
          and (CONCEPT["sample"] or {}).get("denoise") == 0.7
          and (CONCEPT["sample"] or {}).get("conds", [])[-2:] == ["depth", "normal"])
    if ok_c:
        sky_ = dpt[:60].mean()
        near_, far_ = dpt[-80:].mean(), dpt[300:400].mean()
        check(f"  the depth image: the road at the bottom near (bright {near_:.2f}), the valley farther ({far_:.2f}), "
              f"the sky black ({sky_:.3f}); the normal image facing the camera (mean blue {nrm[..., 2].mean():.2f}), "
              f"the sky flat (0.5, 0.5, 1)", near_ > far_ + 0.2 and sky_ < 0.02 and nrm[..., 2].mean() > 0.55
              and np.allclose(nrm[:30].reshape(-1, 3).mean(0), [0.5, 0.5, 1.0], atol=0.02))
    from scipy.spatial import cKDTree
    # the same world at dusk, in the rain, under snow: saved, and each reads as itself against the day shots
    got_ = cap["got"]
    svv = {p_: sh_ for p_, sh_ in IMGS if p_ and p_.startswith("pcg/world/variants/")}
    sv3 = {k_: svv.get(f"pcg/world/variants/{k_}") for k_ in ("Dusk", "Rain", "Snow")}
    day_, val_ = (got_.get("Road: the preview") or {}).get("img"), (got_.get("Valley: the preview") or {}).get("img")
    dsk_, rn_, snw_ = ((got_.get(k_) or {}).get("img") for k_ in ("Dusk: the preview", "Rain: the preview",
                                                                  "Snow: the preview"))
    if all(a_ is not None for a_ in (day_, val_, dsk_, rn_, snw_)):
        gnd = lambda a_: float(np.median(a_[a_.shape[0] // 2:].mean(-1)))  # noqa: E731  (the lower half)
        # lamps and windows: warm pixels far brighter than the frame (3 x its mean): none in daylight
        hot = lambda a_: int(((a_[..., 0] > 3 * a_.mean()) & (a_[..., 0] > a_[..., 2] + 0.25)).sum())  # noqa: E731
        warm, warm_day = hot(dsk_), hot(day_)
        sat = lambda a_: (a_.max(-1) - a_.min(-1))[:a_.shape[0] // 3].mean()  # noqa: E731  (the sky: overcast)
        def snow(a_):
            """near-white, unsaturated pixels on the mountains (the band below the sky)"""
            b_ = a_[int(a_.shape[0] * 0.3):int(a_.shape[0] * 0.75)]
            return float(((b_.min(-1) > 0.6) & (b_.max(-1) - b_.min(-1) < 0.12)).mean())
        check(f"variants saved at 1280 x 720 ({sv3}); dusk: the ground darker (median {gnd(dsk_):.2f} vs day {gnd(day_):.2f}) "
              f"with {warm} warm, bright pixels (lamps, windows; day {warm_day}); rain: a greyer sky (saturation "
              f"{sat(rn_):.3f} vs {sat(day_):.3f}); snow: white on the mountains ({snow(snw_):.1%} of them, "
              f"{snow(val_):.1%} without snow)",
              all(v_ == (1, 720, 1280, 3) for v_ in sv3.values()) and gnd(dsk_) < 0.7 * gnd(day_)
              and warm >= 10 and warm > 5 * warm_day and sat(rn_) < 0.7 * sat(day_)
              and snow(snw_) > 0.05 and snow(snw_) > 4 * snow(val_))
    else:
        check("variants: the Dusk / Rain / Snow and day previews ran", False)
    fly_ = got_.get("Flyby: the frames")
    wp_ = CONCEPT.get("webp")
    check(f"flyby (unmuted here, 3 frames of 160 x 90): the frames {fly_ and fly_['shape']}, each different, saved as "
          f"an animated WebP {wp_}", fly_ is not None and fly_["shape"] == (3, 90, 160, 3) and wp_ is not None
          and wp_[0] == (3, 90, 160, 3) and wp_[2] == 24.0
          and not np.allclose(fly_["frames"][0], fly_["frames"][2], atol=0.02))
    # the map: 2048², the sea blue in the corners, the main roads red along their centre lines, the legend and title
    mp_ = img(os.path.join(WD, "Map.png"))[..., :3].astype(np.float32) / 255
    MVc = obj_lines_pts(os.path.join(WD, "roads/Roads_Main.obj"))
    rr_, cc_ = (MVc[:, 2] * 2048 / 4100 + 2 * 1024 / 4100).astype(int), (MVc[:, 0] * 2048 / 4100).astype(int)
    pix_ = mp_[np.clip(rr_, 0, 2047), np.clip(cc_, 0, 2047)]
    redf = float(((pix_[:, 0] > pix_[:, 1] + 0.15) & (pix_[:, 0] > pix_[:, 2] + 0.15)).mean())
    corner = mp_[:40, -40:].reshape(-1, 3).mean(0)
    leg_ = mp_[int(2048 * 0.78):int(2048 * 0.97), int(2048 * 0.085):int(2048 * 0.28)]  # right of the swatches
    tit_ = mp_[int(2048 * 0.02):int(2048 * 0.06), int(2048 * 0.03):int(2048 * 0.4)]
    check(f"map: Map.png 2048², the sea blue in a corner {np.round(corner, 2)}, {redf:.0%} of the main road points red, "
          f"text in the legend ({(leg_.max(-1) < 0.6).mean():.1%} dark) and the title ({(tit_.max(-1) < 0.6).mean():.1%})",
          mp_.shape == (2048, 2048, 3) and corner[2] > corner[0] + 0.1 and redf > 0.6
          and (leg_.max(-1) < 0.6).mean() > 0.005 and (tit_.max(-1) < 0.6).mean() > 0.01)
    # the road surfaces: a ribbon per class on its centre lines, level across, as wide as the class
    rjs, rnm = node_meshes(os.path.join(WD, "roads/Roads_Mesh.glb"))
    rok, rinfo = True, {}
    for nm_, fn_, w_, dy_ in (("Road_Main", "Roads_Main", 6.5, 0.12), ("Road_Street", "Streets", 8.0, 0.10),
                              ("Road_Lane", "Lanes", 4.0, 0.08)):
        if nm_ not in rnm:
            rok = False
            continue
        Pm_, _, Im_, Nm_ = rnm[nm_]
        cl_ = obj_lines_pts(os.path.join(WD, f"roads/{fn_}.obj"))
        d_, k_ = cKDTree(cl_[:, [0, 2]]).query(Pm_[:, [0, 2]])
        dyy = Pm_[:, 1] - cl_[k_, 1]
        rinfo[nm_] = (round(float(np.median(d_)), 2), round(float(np.median(dyy)), 3), round(float(Nm_[:, 1].min()), 3))
        rok &= abs(np.median(d_) - w_ / 2) < 0.35 and abs(np.median(dyy) - dy_) < 0.1 and Nm_[:, 1].min() > 0.99
    check(f"road surfaces: Roads_Mesh.glb ({sorted(rnm)}); per class the ribbon's edge from its centre line, its "
          f"height over it, the lowest normal's y: {rinfo}", rok and {"Road_Shoulder_Main", "Pavement_Street"} <= set(rnm))
    tiles = {(i, j): img(os.path.join(WD, f"height/Height_x{i}_y{j}.png"))[..., 0].astype(np.int64)
             for i in range(4) for j in range(4)}
    check("height: 16 tiles of 16-bit PNG, 513² each (2 m: the fine erosion pass)", len(tiles) == 16
          and all(t.shape == (513, 513) for t in tiles.values())
          and img(os.path.join(WD, "height/Height_x0_y0.png")).dtype == np.uint16)
    check("  shared edges of left/right and top/bottom neighbouring tiles bit-identical",
          all(np.array_equal(tiles[(i, j)][:, -1], tiles[(i + 1, j)][:, 0])
              for i in range(3) for j in range(4))
          and all(np.array_equal(tiles[(i, j)][-1], tiles[(i, j + 1)][0])
                  for i in range(4) for j in range(3)))
    full = np.fromfile(os.path.join(WD, "height/Height_full.r16"), "<u2").reshape(2049, 2049)
    st = np.zeros((2049, 2049), np.int64)
    for (i, j), t in tiles.items():
        st[j * 512:j * 512 + 513, i * 512:i * 512 + 513] = t
    check("  the 16 tiles stitched back = the full r16 image (bit-exact)", np.array_equal(st, full))
    hj = json.load(open(os.path.join(WD, "height/Height.json"), encoding="utf-8"))
    lo_m, hi_m = hj["range_scaled"]
    check("  the sidecar is called Height.json, range_scaled is in metres (= range × 2048)",
          np.allclose([lo_m, hi_m], np.array(hj["range"]) * 2048) and hi_m - lo_m > 100,
          (round(lo_m, 1), round(hi_m, 1)))
    Hm2 = lo_m + full / 65535.0 * (hi_m - lo_m)          # 2 m
    Hm = Hm2[::2, ::2]                                     # its 4 m samples (the grid the rest of the chain works on)
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
        """the exported height (2 m) at world x, z, bilinear; off in 4 m samples"""
        u, v = x / 2.0 + 2 * off, z / 2.0
        i0 = np.clip(np.floor(u).astype(int), 0, 2047)
        j0 = np.clip(np.floor(v).astype(int), 0, 2047)
        fu, fv = u - i0, v - j0
        return (Hm2[j0, i0] * (1 - fu) * (1 - fv) + Hm2[j0, i0 + 1] * fu * (1 - fv)
                + Hm2[j0 + 1, i0] * (1 - fu) * fv + Hm2[j0 + 1, i0 + 1] * fu * fv)

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
    for fn_ in ("roads/Roads_Main.obj", "roads/Streets.obj"):          # the main roads and the town streets
        v0_ = len(vs_)
        for ln in open(os.path.join(WD, fn_), encoding="utf-8"):
            if ln.startswith("v "):
                vs_.append([float(t) for t in ln.split()[1:4]])
            elif ln.startswith("l "):
                ls_.append([v0_ + int(t) - 1 for t in ln.split()[1:]])
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
        # the lanes, every 4 m: a building fronts a road or a lane
        lq0 = cap["got"].get("Lanes")
        lpd = (np.concatenate([a_ + (b_ - a_) * t_[:, None] for a_, b_ in lq0
                               for t_ in [np.linspace(0, 1, int(np.linalg.norm(b_ - a_) // 4) + 2)]])
               if lq0 is not None and len(lq0) else np.zeros((0, 2)))
        rlk = cKDTree(np.concatenate([RV[:, [0, 2]] - 2048.0, lpd]))
        dr_ = rkd.query(bq["feet"])[0]
        dtc_ = rkd.query(tp_)[0]
        check(f"  off the roads: every wall at least 8 m from a road centre line (min {dr_.min():.1f} m); negative "
              f"control, the town centres: median {np.median(dtc_):.1f} m from a road",
              dr_.min() > 8.0 and np.median(dtc_) < 10.0)
        cen_ = np.array([bq["feet"][bq["feet_b"] == k].mean(0) for k in range(nb_)])
        ti_ = np.array([int(n_[5:]) - 1 for n_ in bq["name"]])
        dcen = np.linalg.norm(cen_ - tp_[ti_], axis=1)
        dcr_ = rlk.query(cen_)[0]
        cr_ = float(np.corrcoef(bq["tc"], bq["floors"])[0, 1])
        check(f"  plots along the roads: every building in its town's disc (within 170 m of the centre, max "
              f"{dcen.max():.0f} m), 90% within 70 m of a road or a lane (median {np.median(dcr_):.0f} m); 1-5 floors, taller "
              f"toward the town core (correlation of floors with the core weight {cr_:.2f})",
              dcen.max() < 170 and np.mean(dcr_ < 70) > 0.9 and bq["floors"].min() >= 1 and bq["floors"].max() <= 5
              and cr_ > 0.3)
        # the doors face the building's own street (the road or lane point its plot was made from, carried on the
        # faces): along the plot's front direction a door lies nearer that street than the building's centre;
        # negative control, the building's walls (about half face away)
        st_, fr_ = bq["street"], bq["front"]

        def toward(c_, b_):
            return ((c_ - st_[b_]) * fr_[b_]).sum(1) - ((cen_[b_] - st_[b_]) * fr_[b_]).sum(1)
        dd_ = toward(bq["door_c"], bq["door_b"])
        wd_ = toward(bq["wall_c"], bq["wall_b"])
        # a door on a side wall (its offset from the centre mostly across the front direction) of a corner building,
        # on the side of its second street, counts as street-side too
        sdq = bq["side"]

        dn_ = bq["door_n"] / np.maximum(np.linalg.norm(bq["door_n"], axis=1, keepdims=True), 1e-9)
        fu_ = fr_[bq["door_b"]] / np.maximum(np.linalg.norm(fr_[bq["door_b"]], axis=1, keepdims=True), 1e-9)
        sidew = np.abs((dn_ * fu_).sum(1)) < 0.7                            # a door on a side wall (by its facing)
        on_side = sidew & ((dn_ * sdq[bq["door_b"]]).sum(1) > 0.7)
        dd_ = np.where(on_side, 1.0, np.where(sidew, -1.0, dd_))
        ds_ = np.minimum(rkd.query(st_)[0], cKDTree(lpd).query(st_)[0] if len(lpd) else np.inf)
        hd_ = len(np.unique(bq["door_b"]))
        check(f"  the doors on the street side (Front Pattern): {hd_} buildings with doors, {np.mean(dd_ > 0):.1%} of "
              f"the doors on the side toward their own street (the plot's road or lane point, {np.percentile(ds_, 99):.1f} m "
              f"from a centre line at most for 99%); negative control, the walls: {np.mean(wd_ > 0):.0%}",
              hd_ > 0.8 * nb_ and np.mean(dd_ > 0) > 0.98 and np.mean(wd_ > 0) < 0.6 and np.percentile(ds_, 99) < 2.0,
              (round(float(np.mean(dd_ > 0)), 4), round(float(np.mean(wd_ > 0)), 3)))
        rf_ = bq["rf"]
        ridge_ = bq["roof_top"] - bq["base"] - 3.4 - 3.1 * (bq["floors"] - 1)
        check(f"  pitched roofs: gable on 1-3 floors, hip on 4-5 ({dict(zip(*np.unique(rf_, return_counts=True)))}), "
              f"{bq['gable']} gable-end walls, the ridges above the eaves (median {np.median(ridge_):.1f} m); the "
              f"{bq['lshape']} L-shaped buildings under cross gables (flat roof faces among them: {bq['lflat']})",
              set(rf_.tolist()) <= {"gable", "hip"} and np.all((rf_ == "hip") == (bq["floors"] >= 4))
              and bq["gable"] > 0 and np.median(ridge_) > 1.5 and bq["lshape"] >= 3 and bq["lflat"] == 0,
              np.percentile(ridge_, [1, 50, 99]).round(2))
        # corner lots: the second street really is there, the building has a door on it
        cnr = np.linalg.norm(sdq, axis=1) > 0.5
        if cnr.any():
            pr_s = cen_[cnr] + sdq[cnr] * 12.0
            pr_o = cen_[cnr] - sdq[cnr] * 12.0
            near_s = rlk.query(pr_s)[0] < rlk.query(pr_o)[0]
            dside = np.array([((dn_[bq["door_b"] == k] * sdq[k]).sum(1) > 0.7).any() for k in np.nonzero(cnr)[0]])
            dopp = np.array([((dn_[bq["door_b"] == k] * sdq[k]).sum(1) < -0.7).any() for k in np.nonzero(cnr)[0]])
        check(f"  corner lots: {int(cnr.sum())} buildings with a second street (it lies on that side: "
              f"{near_s.mean() if cnr.any() else 0:.0%} nearer a street than the other side), a door on that side "
              f"wall for {dside.mean() if cnr.any() else 0:.0%}; negative control, a door on the opposite side wall: "
              f"{dopp.mean() if cnr.any() else 0:.0%}",
              # (0.85: the generator's street mask has the town squares in it, which have no centre line here)
              cnr.sum() >= 10 and near_s.mean() > 0.85 and dside.mean() > 0.9 and dopp.mean() < 0.1)
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
    ecs = None
    tree_ff = None
    ec = cap["got"].get("Ecology: seven weight layers + scatter densities")
    if ec is not None:
        gentle = ec["upb"] > 0.98                       # the up-ness the ecology classes by (mostly the broad slope)
        crop = gentle & (ec["farm"] > 0.6) & (ec["town"] < 0.1) & (np.rint(ec["field_id"]) >= 1)
        marg = gentle & (ec["farm"] > 0.6) & (ec["town"] < 0.1) & (np.rint(ec["field_id"]) == 0)
        ffc, ffm = float(ec["ForestFloor"][crop].mean()), float(ec["ForestFloor"][marg].mean())
        check(f"  the fields are cleared of woodland: ForestFloor {ffc:.3f} on {int(crop.sum())} crop pixels; "
              f"negative control, the margins between them (hedgerows, copses): {ffm:.3f}",
              crop.sum() > 2000 and marg.sum() > 1000 and ffc < 0.02 and ffm > 3 * ffc)
        fwm = ec["fieldw"][::-1].copy()                # image row 0 is the bottom; the stitched tiles start at the top
        ffi = ec["ForestFloor"][::-1]
        tsel = np.array([r_["asset"].startswith("Tree_Pine") or r_["asset"].startswith("Tree_Broadleaf") for r_ in rows])
        fft = ffi[np.clip((zs[tsel] / 4).astype(int), 0, 1024), np.clip((xs[tsel] / 4).astype(int), 0, 1024)]
        core_ = np.argwhere(ffi > 0.6) * 4.0
        if len(core_) and tsel.any():
            cq_ = cKDTree(core_)
            outs_ = np.stack([zs[tsel][fft < 0.3], xs[tsel][fft < 0.3]], 1)
            # the control: land points that are outside the woodland proper as well (the same population as the
            # trees measured), so woodland covering much of the land does not shrink it
            lpz_ = np.argwhere((Hm > 5.0) & (ffi[:Hm.shape[0], :Hm.shape[1]] < 0.3))[::40] * 4.0
            tree_ff = (float((fft < 0.3).mean()), float(np.median(cq_.query(outs_)[0])) if len(outs_) else 1e9,
                       float(np.median(cq_.query(lpz_)[0])))
        ecs = {k_: ec[k_] for k_ in ("farm", "field_id", "town", "tring")}
        del ec
    # side streets, road furniture, orchards and hedgerows
    an_ = np.array([r["asset"] for r in rows])
    XZ = np.stack([xs - 2048.0, zs - 2048.0], 1)               # the instances in the centred frame
    tpq = cap["got"].get("Towns: numbered")
    rkq = cKDTree(RV[:, [0, 2]] - 2048.0)
    dtw = cKDTree(tpq).query(XZ)[0] if tpq is not None else np.full(len(XZ), np.inf)
    br_, lm_, gr_ = an_ == "SM_Bridge", an_ == "SM_StreetLamp", an_ == "SM_GuardRail"
    dlm = rkq.query(XZ[lm_])[0]
    dgr = rkq.query(XZ[gr_])[0]

    def drop_out(sel, d_=6.5):
        """How far the ground falls d_ metres further out from the nearest road point."""
        _, k_ = rkq.query(XZ[sel])
        v_ = XZ[sel] - (RV[k_][:, [0, 2]] - 2048.0)
        v_ /= np.maximum(np.linalg.norm(v_, axis=1, keepdims=True), 1e-9)
        q_ = XZ[sel] + v_ * d_
        return ys[sel] - hgt(q_[:, 0] + 2048.0, q_[:, 1] + 2048.0)
    dg_, dl_ = drop_out(gr_), drop_out(lm_)
    check(f"road furniture: {int(br_.sum())} bridges, {int(lm_.sum())} street lamps, {int(gr_.sum())} guard rail "
          f"segments; lamps in the towns and 6 m off a road's centre line (median {np.median(dlm):.1f} m), rails 5.5 m "
          f"off (median {np.median(dgr):.1f} m) outside the towns where the ground falls away (median drop 6.5 m "
          f"further out {np.median(dg_):.1f} m; negative control, at the lamps {np.median(dl_):.1f} m)",
          br_.sum() >= 1 and lm_.sum() > 50 and gr_.sum() > 20 and (dtw[lm_] < 175).all()
          and abs(np.median(dlm) - 6.0) < 1.0 and abs(np.median(dgr) - 5.5) < 1.0 and (dtw[gr_] > 150).mean() > 0.95
          and np.median(dg_) > 2.0 and np.median(dl_) < 1.0)
    # bridges: a deck as long as the bed is wide, piers on the bed up to the deck
    pi_ = an_ == "SM_BridgePier"
    sxyz = np.array([[float(r[c]) for c in ("sx", "sy", "sz")] for r in rows])
    span_ = sxyz[br_, 2] * 30.0
    if br_.any() and pi_.any():
        kb_ = cKDTree(XZ[br_])
        db_, ib_ = kb_.query(XZ[pi_])
        under = db_ <= span_[ib_] / 2 + 4.0
        top_ = ys[pi_] + sxyz[pi_, 1]
        dtop = np.abs(top_ - ys[br_][ib_])
        nper = np.bincount(ib_[under], minlength=int(br_.sum()))
    clr = ys[br_] - hgt(xs[br_], zs[br_])
    check(f"bridges: spans {span_.min() if br_.any() else 0:.0f}-{span_.max() if br_.any() else 0:.0f} m (the bed + 8 m, "
          f"at least 16), {int(pi_.sum())} piers, all under a deck ({under.mean() if pi_.any() else 0:.0%}), their tops at "
          f"the deck (median {np.median(dtop) if pi_.any() else 0:.2f} m off; the 0.5 m minimum where the deck lies on the "
          f"bed), every bridge of 24 m or more on piers; the decks at the banks, {np.median(clr) if br_.any() else 0:.1f} m "
          f"over the ground at their middle (median)",
          br_.any() and pi_.any() and span_.min() >= 16 and span_.max() < 140 and under.mean() > 0.95
          and np.median(dtop) < 0.2 and (nper[span_ >= 24] >= 1).all() and (clr > -0.5).all())
    # lanes: on their graded bed, smoother than the ground beside them
    lv_, ll_ = [], []
    for ln in open(os.path.join(WD, "roads/Lanes.obj"), encoding="utf-8"):
        if ln.startswith("v "):
            lv_.append([float(t) for t in ln.split()[1:4]])
        elif ln.startswith("l "):
            ll_.append([int(t) - 1 for t in ln.split()[1:]])
    LV = np.array(lv_)
    lpl = [LV[i] for i in ll_ if len(i) >= 5]
    onb = np.concatenate([np.abs(p_[:, 1] - hgt(p_[:, 0], p_[:, 2])) for p_ in lpl])
    rough_l = np.concatenate([np.abs(np.diff(p_[:, 1], 2)) for p_ in lpl])

    def beside(p_, d_=15.0):
        t_ = np.gradient(p_[:, [0, 2]], axis=0)
        t_ /= np.maximum(np.linalg.norm(t_, axis=1, keepdims=True), 1e-9)
        q_ = p_[:, [0, 2]] + np.stack([t_[:, 1], -t_[:, 0]], 1) * d_
        return hgt(q_[:, 0], q_[:, 1])
    rough_b = np.concatenate([np.abs(np.diff(beside(p_), 2)) for p_ in lpl])
    grd = np.concatenate([np.abs(np.diff(p_[:, 1])) / np.maximum(np.linalg.norm(np.diff(p_[:, [0, 2]], axis=0), axis=1),
                                                                 1e-6) for p_ in lpl])
    check(f"lanes: {len(lpl)} lanes in Lanes.obj, on the ground (the height files under them: median {np.median(onb):.2f} m), "
          f"graded: smoother than the ground 15 m beside them (mean bend {rough_l.mean():.2f} m vs "
          f"{rough_b.mean():.2f} m per 8 m step), grade median {np.median(grd):.0%}, 95% under {np.percentile(grd, 95):.0%}",
          len(lpl) >= 8 and np.median(onb) < 0.3 and rough_l.mean() < 0.7 * rough_b.mean()
          and np.median(grd) < 0.2 and np.percentile(grd, 95) < 0.5)
    # road classes: main roads between the towns, streets inside them, lanes; a lamp of each class at its spacing
    def obj_pts(fn_):
        """The vertices the polylines use (PolyCut leaves the cut-away points in the file, unused)."""
        v__, u__ = [], set()
        for ln in open(os.path.join(WD, fn_), encoding="utf-8"):
            if ln.startswith("v "):
                v__.append([float(t) for t in ln.split()[1:4]])
            elif ln.startswith("l "):
                u__.update(int(t) - 1 for t in ln.split()[1:])
        return np.array(v__)[sorted(u__)]
    MV, SV = obj_pts("roads/Roads_Main.obj"), obj_pts("roads/Streets.obj")
    tkq = cKDTree(tpq) if tpq is not None else None
    dmt = tkq.query(MV[:, [0, 2]] - 2048.0)[0] if tkq else np.zeros(1)
    dst = tkq.query(SV[:, [0, 2]] - 2048.0)[0] if tkq else np.full(1, 1e9)
    check(f"road classes: {len(SV)} street points inside the towns ({(dst < 175).mean():.0%} within 175 m of a town "
          f"centre), {len(MV)} main road points between them ({(dmt > 150).mean():.0%} beyond 150 m; the town discs are "
          "160 m); negative control: the other way round fails", len(SV) > 200 and len(MV) > 500
          and (dst < 175).mean() > 0.95 and (dmt > 150).mean() > 0.85 and (dst > 150).mean() < 0.3
          and (dmt < 175).mean() < 0.3)
    nnd = {}
    for a_ in ("SM_StreetLamp", "SM_RoadLamp", "SM_LaneLamp"):
        m_ = an_ == a_
        nnd[a_] = (int(m_.sum()), float(np.median(cKDTree(XZ[m_]).query(XZ[m_], k=2)[0][:, 1])) if m_.sum() > 2 else 0.0)
    rl_, ll_m = an_ == "SM_RoadLamp", an_ == "SM_LaneLamp"
    mkq = cKDTree(MV[:, [0, 2]] - 2048.0)
    lkq_ = cKDTree(np.concatenate(lpl)[:, [0, 2]] - 2048.0) if lpl else None
    drl = mkq.query(XZ[rl_])[0] if rl_.any() else np.full(1, 1e9)
    dll = lkq_.query(XZ[ll_m])[0] if (ll_m.any() and lkq_ is not None) else np.full(1, 1e9)
    gll = np.abs(ys[ll_m] - hgt(xs[ll_m], zs[ll_m])) if ll_m.any() else np.full(1, 9.0)
    check(f"lamps by class (count, median spacing): street {nnd['SM_StreetLamp']}, road {nnd['SM_RoadLamp']}, lane "
          f"{nnd['SM_LaneLamp']}; road lamps 6 m off a main road (median {np.median(drl):.1f} m) near the towns, lane "
          f"lamps 3.5 m off a lane (median {np.median(dll):.1f} m) on the ground (median {np.median(gll):.2f} m)",
          nnd["SM_RoadLamp"][0] >= 5 and nnd["SM_LaneLamp"][0] >= 5
          and nnd["SM_RoadLamp"][1] > 55 and 32 < nnd["SM_LaneLamp"][1] < 70 and nnd["SM_StreetLamp"][1] < 45
          and abs(np.median(drl) - 6.0) < 1.5 and abs(np.median(dll) - 3.5) < 1.5 and np.median(gll) < 0.3
          and (dtw[rl_] > 120).all() and (dtw[rl_] < 400).mean() > 0.9)
    # water: rivers and the lake as a mesh, a node per tile; the rivers 0.7 m over their bed with the flow downhill,
    # the lake flat
    wjs, wacc = glb_parse(os.path.join(WD, "water/Water.glb"))
    wn_ = [n_["name"] for n_ in wjs["nodes"]]
    WP_, WC_, okn = [], [], True
    for n_ in wjs["nodes"]:
        for pr__ in wjs["meshes"][n_["mesh"]]["primitives"]:
            p__ = wacc(pr__["attributes"]["POSITION"])[0]
            WP_.append(p__)
            WC_.append(wacc(pr__["attributes"]["COLOR_0"])[0][:, :3])
            okn &= n_["name"] == f"Water_x{int(np.median(p__[:, 0]) // 1024)}_y{int(np.median(p__[:, 2]) // 1024)}"
    WP_, WC_ = np.concatenate(WP_), np.concatenate(WC_)
    spd = WC_[:, 2]
    riv_, still_ = spd > 0.15, spd < 0.02
    dzw = WP_[:, 1] - hgt(WP_[:, 0], WP_[:, 2])
    fl_ = np.stack([WC_[:, 0] * 2 - 1, WC_[:, 1] * 2 - 1], 1)
    fn_ = fl_ / np.maximum(np.linalg.norm(fl_, axis=1, keepdims=True), 1e-9)
    q_ = riv_ & (np.linalg.norm(fl_, axis=1) > 0.1)
    Xq, Zq = WP_[q_, 0], WP_[q_, 2]
    down_ = (hgt(Xq + 20 * fn_[q_, 0], Zq + 20 * fn_[q_, 1]) < hgt(Xq - 20 * fn_[q_, 0], Zq - 20 * fn_[q_, 1])).mean()
    rr_ = np.random.default_rng(5).normal(size=(int(q_.sum()), 2))
    rr_ /= np.linalg.norm(rr_, axis=1, keepdims=True)
    rdn_ = (hgt(Xq + 20 * rr_[:, 0], Zq + 20 * rr_[:, 1]) < hgt(Xq - 20 * rr_[:, 0], Zq - 20 * rr_[:, 1])).mean()
    vis_ = riv_ & (dzw > 0)                 # the channels are spread a little: on the banks the water is under ground
    check(f"water: {len(WP_)} vertices in {len(wn_)} tile nodes ({', '.join(wn_[:4])}...); rivers ({int(riv_.sum())}, "
          f"{vis_.sum() / max(riv_.sum(), 1):.0%} above the ground) about 0.7 m over it where seen (median "
          f"{np.median(dzw[vis_]) if vis_.any() else 0:.2f} m), their flow downhill for {down_:.0%} (negative control, "
          f"random directions: {rdn_:.0%}); the lake ({int(still_.sum())} still vertices) flat "
          f"(spread {np.ptp(WP_[still_, 1]) if still_.any() else 0:.3f} m) over a deepened bed",
          okn and riv_.sum() > 500 and vis_.sum() > 0.3 * riv_.sum() and 0.3 < np.median(dzw[vis_]) < 1.3
          and down_ > 0.8 and rdn_ < 0.65
          and still_.sum() > 100 and np.ptp(WP_[still_, 1]) < 0.05 and np.median(dzw[still_]) > 1.0)
    # vegetation: understory under the trees, shrubs round the woodland, fewer and smaller trees up high
    trs = np.array([a_.startswith("Tree_Pine") or a_.startswith("Tree_Broadleaf") for a_ in an_])
    tq_ = cKDTree(XZ[trs])
    und = np.isin(an_, ["Fern_A", "Shrub_Low_A"])
    bsh = np.isin(an_, ["Bush_A", "Bush_B"])
    lp_ = np.argwhere(Hm > 5.0)[::40][:, ::-1] * 4.0 - 2048.0
    d_u, d_b, d_r = (float(np.median(tq_.query(v_)[0])) for v_ in (XZ[und], XZ[bsh], lp_))
    ht_ = ys[trs]
    scl_ = sxyz[trs, 0]
    lo_s, hi_s = float(np.median(scl_[ht_ < 60])), float(np.median(scl_[ht_ > 150])) if (ht_ > 150).any() else 0.0
    area_ = lambda a, b: max(float(((Hm > a) & (Hm < b)).sum()) * 16 / 1e6, 1e-9)     # noqa: E731
    den_lo, den_hi = ((ht_ < 60) & (ht_ > 0)).sum() / area_(0, 60), (ht_ > 150).sum() / area_(150, 1e4)
    check(f"vegetation: {int(und.sum())} ferns and low shrubs under the trees (median {d_u:.1f} m to a tree), "
          f"bushes along the woodland ({d_b:.1f} m); negative control, land points {d_r:.1f} m; trees above 150 m "
          f"smaller (median scale {hi_s:.2f} vs {lo_s:.2f} below 60 m) and sparser ({den_hi:.0f} vs {den_lo:.0f} a km²)",
          und.sum() > 1000 and d_u < 0.6 * d_r and d_b < d_r and hi_s < 0.85 * lo_s and den_hi < 0.4 * den_lo)
    if tree_ff is not None:
        check(f"  the forest edge is feathered: {tree_ff[0]:.0%} of the trees stand outside the woodland proper "
              f"(ForestFloor < 0.3), {tree_ff[1]:.0f} m from it (median); negative control, land points outside it "
              f"{tree_ff[2]:.0f} m", 0.04 < tree_ff[0] < 0.5 and tree_ff[1] < 0.5 * tree_ff[2])
    # World.json: the files, the convention, a manifest per tile
    wj_ = json.load(open(os.path.join(WD, "World.json"), encoding="utf-8"))
    tls_ = [json.load(open(os.path.join(OUT, t_["file"]), encoding="utf-8")) for t_ in wj_["tiles"]]
    nb_t = sum(len(t_["buildings"]) for t_ in tls_)
    ni_t = sum(t_["instances"]["count"] for t_ in tls_)
    ok_b = True
    for r_ in rows[::97]:
        x_, z_ = float(r_["px"]), float(r_["pz"])
        t_ = tls_[[tuple(t["tile"]) for t in wj_["tiles"]].index((int(x_ // 1024), int(z_ // 1024)))]
        ok_b &= t_["bounds"]["min"][0] <= x_ <= t_["bounds"]["max"][0] and t_["bounds"]["min"][1] - 1e-3 <= \
            float(r_["py"]) <= t_["bounds"]["max"][1] + 1e-3
    check(f"World.json: 16 tiles, the terrain (range {wj_['terrain']['range_metres'][0]:.0f}..{wj_['terrain']['range_metres'][1]:.0f} m), "
          f"{len(wj_['images'])} image sets, {wj_['instances']['count']} instances (= the tables, = the tiles' {ni_t}), "
          f"the {nb_t} towns placed once each, the road classes' polylines, the water nodes in their tiles; every "
          "sampled instance inside its tile's bounds",
          len(tls_) == 16 and np.allclose(wj_["terrain"]["range_metres"], [lo_m, hi_m], atol=1e-3)
          and wj_["instances"]["count"] == len(rows) == ni_t and nb_t == len(towns_)
          and {"roads/Roads_Main", "roads/Streets", "roads/Lanes"} <= set(wj_["polylines"])
          and set(wj_["road_classes"]) == {"main", "street", "lane"}
          and sorted({w_["node"] for t_ in tls_ for w_ in t_["water"]}) == sorted(wn_)
          and "height/Height" in tls_[0]["terrain"] and ok_b)
    pr_ = np.array([a_.startswith("Tree_Pine") for a_ in an_])
    bl_ = np.array([a_.startswith("Tree_Broadleaf") for a_ in an_])
    fr_ = an_ == "Tree_Fruit_A"
    hd_ = an_ == "Hedge_A"
    nnf = cKDTree(XZ[fr_]).query(XZ[fr_], k=2)[0][:, 1] if fr_.sum() > 2 else np.zeros(1)
    check(f"orchards: {int(fr_.sum())} fruit trees in the ring round the towns (90% 150-340 m from a centre), in rows "
          f"8 m apart (median nearest neighbour {np.median(nnf):.1f} m); no pines within 200 m of a town "
          f"({int((pr_ & (dtw < 200)).sum())}; negative control, broadleaf there: {int((bl_ & (dtw < 200)).sum())})",
          fr_.sum() > 500 and np.mean((dtw[fr_] > 150) & (dtw[fr_] < 340)) > 0.9 and abs(np.median(nnf) - 8.0) < 0.6
          and (pr_ & (dtw < 200)).sum() == 0 and (bl_ & (dtw < 200)).sum() > 20)
    if ecs is not None:
        Hh, Wh = ecs["farm"].shape

        def eco_at(name, P2):
            u_, v_ = P2[:, 0] / 4100 + 0.5, 0.5 - P2[:, 1] / 4100
            return ecs[name][np.clip((v_ * Hh).astype(int), 0, Hh - 1), np.clip((u_ * Wh).astype(int), 0, Wh - 1)]
        mg_ = (eco_at("farm", XZ[hd_]) > 0.2) & (np.rint(eco_at("field_id", XZ[hd_])) == 0)
        rnd = np.random.default_rng(3).uniform(-2050, 2050, (20000, 2))
        rf_ = eco_at("farm", rnd) > 0.2
        mr_ = (np.rint(eco_at("field_id", rnd[rf_])) == 0).mean() if rf_.any() else 1.0
        check(f"hedgerows: {int(hd_.sum())} hedges, {mg_.mean():.0%} on the field margins (farmland, field_id 0); "
              f"negative control, random farmland points: {mr_:.0%} margins",
              hd_.sum() > 1000 and mg_.mean() > 0.75 and mg_.mean() > 2 * mr_)
    lq = cap["got"].get("Lanes")
    if lq is None or not len(lq):
        check("lanes: the Lanes node ran", False)
    else:
        tq = np.linspace(0.3, 0.95, 12)
        LP = (lq[:, 0, None, :] * (1 - tq)[None, :, None] + lq[:, 1, None, :] * tq[None, :, None]).reshape(-1, 2)
        dirn = (lq[:, 1] - lq[:, 0]) / np.linalg.norm(lq[:, 1] - lq[:, 0], axis=1, keepdims=True)
        sideq = np.repeat(np.stack([dirn[:, 1], -dirn[:, 0]], 1), len(tq), 0) * 20.0

        def road_w(P2):
            i_ = np.clip(((P2[:, 0] + 2048.0) / 4.0).round().astype(int), 0, 1024)
            j_ = np.clip(((P2[:, 1] + 2048.0) / 4.0).round().astype(int), 0, 1024)
            return wfull["Road"][j_, i_]
        on_, off_ = road_w(LP), road_w(LP + sideq)
        cen_b = np.array([bq["feet"][bq["feet_b"] == k].mean(0) for k in range(len(bq["base"]))])
        nlane = cKDTree(LP).query(cen_b)[0]
        lane_b = (rkq.query(cen_b)[0] > 80) & (nlane < 70)
        check(f"lanes: {len(lq)} lanes, painted (Road weight > 0.5 on {np.mean(on_ > 0.5):.0%} of their length; "
              f"negative control 20 m to the side: {np.mean(off_ > 0.5):.0%}), {int(lane_b.sum())} buildings on their plots",
              len(lq) >= 8 and np.mean(on_ > 0.5) > 0.8 and np.mean(off_ > 0.5) < 0.2 and lane_b.sum() >= 5)
        dmin = cKDTree(cen_b).query(cen_b, k=2)[0][:, 1]
        check(f"  buildings never overlap: their centres at least 8 m apart (min {dmin.min():.1f} m)", dmin.min() > 8.0)
    md_b = bq["modules"]
    check(f"  livelier towns: shopfronts {md_b.get('shopfront', 0)}, balconies {md_b.get('balcony', 0)}, chimneys "
          f"{bq['parts'].get('chimney', 0) // 5}, yard walls {bq['parts'].get('yardwall', 0) // 5}, L-shaped buildings "
          f"{bq['lshape']}", md_b.get("shopfront", 0) > 10 and md_b.get("balcony", 0) > 50
          and bq["parts"].get("chimney", 0) >= 5 * 20 and bq["parts"].get("yardwall", 0) >= 5 * len(bq["base"])
          and bq["lshape"] >= 3)
    lj = json.load(open(os.path.join(WD, "buildings/Towns.lods.json"), encoding="utf-8"))
    la_ = {a_["name"]: a_ for a_ in lj["assets"]}
    lok = all([e_["distance"] for e_ in a_["lods"]] == [0.0, 400.0, 1200.0]
              and a_["lods"][0]["screen_size"] == 1.0 > a_["lods"][1]["screen_size"] > a_["lods"][2]["screen_size"] > 0
              and a_["lods"][0]["triangles"] > a_["lods"][1]["triangles"] > a_["lods"][2]["triangles"]
              and a_["lods"][0]["unity_transition"] == a_["lods"][1]["screen_size"] for a_ in lj["assets"])
    check(f"  Towns.lods.json: the LOD chain of every town for an engine (distances, screen sizes, transitions, "
          f"triangles falling)", sorted(la_) == towns_ and lok, lj["assets"][0]["lods"])
    _, pn_ = node_meshes(os.path.join(WD, "assets/SM_Props.glb"))
    check("  SM_Props.glb: the orchard tree, hedge, bridge, pier, the three lamps and guard rail proxies, named as in "
          "the tables", sorted(pn_) == sorted(["SM_Proxy_Fruit", "SM_Proxy_Hedge", "SM_Bridge", "SM_BridgePier",
                                               "SM_StreetLamp", "SM_GuardRail", "SM_RoadLamp", "SM_LaneLamp"]))
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
        check(f"{a_} tree: SM_Proxy_{a_}.glb with LOD0 (Tree Generator) / LOD1 (the coarse tree) / LOD2 (two crossed "
              f"cards) {t_}; an 8 x 8 "
              f"impostor atlas of 1024², the tree in every frame (coverage {min(frames):.2f}..{max(frames):.2f}), "
              f"unit normals on it",
              sorted(nm_) == [f"SM_Proxy_{a_}_LOD{i}" for i in range(3)] and t_[2] == 4 and t_[0] >= 1000
              and 0.05 < t_[1] / t_[0] < 0.45
              and bc_.shape[:2] == (1024, 1024) and min(frames) > 0.05 and max(frames) < 0.95
              and abs(np.median(np.linalg.norm(nn_[on_], axis=-1)) - 1) < 0.05)
        # the impostor atlas baked with the leaf texture: green leaves, not the grey card shading alone
        cfr_ = bc_[..., :3][on_].astype(np.float64).mean(0)
        check(f"  {a_}: the atlas baked with the leaf card texture (mean colour {np.round(cfr_, 1)}: green)",
              cfr_[1] > 1.15 * cfr_[0] and cfr_[1] > 1.3 * cfr_[2])
    # the leaf cards' textures (Leaf Card Texture): a twig rooted at the bottom middle, cut out, green
    for lf_ in ("Leaf", "Needle"):
        la_ = img(os.path.join(ad_, f"T_{lf_}_Alpha.png"))[..., 0] / 255.0
        lb_ = img(os.path.join(ad_, f"T_{lf_}_BaseColor.png"))[..., :3].astype(np.float64)
        root_ = la_[-16:-3, 248:264].max()                     # the PNG's last row is the bottom (v 0)
        lcol_ = lb_[la_ > 0.5].mean(0)
        check(f"leaf card texture T_{lf_}: 512², coverage {la_.mean():.2f}, rooted at the bottom middle "
              f"(alpha {root_:.2f}), the top corners empty, green ({np.round(lcol_, 1)})",
              la_.shape == (512, 512) and 0.12 < la_.mean() < 0.6 and root_ > 0.9
              and max(la_[:8, :8].max(), la_[:8, -8:].max()) < 0.05 and lcol_[1] > 1.2 * max(lcol_[0], lcol_[2]))
    # the previews' far view: from the valley camera, the trees beyond 500 m as impostor cards on their frames, the
    # towns at the LOD of their distance
    cq_, lq_ = cap["got"].get("Valley: cards' uv on their frame"), cap["got"].get("Valley: the towns at that LOD")
    check(f"preview far view (valley camera): {cq_ and cq_['n']} impostor cards, uv on the atlas "
          f"{cq_ and cq_['uv']} over {cq_ and cq_['frames']} frames, four frames blended (weights summing to 1: "
          f"{cq_ and cq_['fw']}); the towns' faces by LOD {lq_}",
          cq_ is not None and cq_["n"] > 5000 and cq_["uv"][0] >= 0 and cq_["uv"][1] <= 1 and cq_["frames"] >= 4
          and cq_["fw"] is not None and abs(cq_["fw"][0] - 1) < 1e-4 and abs(cq_["fw"][1] - 1) < 1e-4
          and cq_["fw"][2] > 0.5 and lq_ is not None and len(lq_) >= 2 and sum(lq_.values()) > 0)
    # grass (preview only): tufts around the road camera, dense at the camera, on the ground, off the road
    gg_ = cap["got"].get("Grass tufts")
    if gg_ is None:
        check("grass: the Grass tufts node ran", False)
    else:
        GP = gg_["P"].reshape(-1, 30, 3)                    # six blades of five points, the first two at the base
        base = GP[:, [5 * b_ + k_ for b_ in range(6) for k_ in (0, 1)]].mean(1)
        ntuft = len(base)
        rr = np.hypot(base[:, 0] - MW.CAM3[0], base[:, 2] - MW.CAM3[2])
        check(f"grass: {ntuft} tufts of six two-segment blades, all within 141 m of the road camera",
              30000 < ntuft < 90000 and gg_["prims"] == 12 * ntuft and rr.max() < 141.0, round(float(rr.max()), 1))
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
              np.mean(d_on < 2) < 0.01 and np.mean(d_ct < 2) > 0.03)
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
          "takes the rest) and never above it", NSP == 4 and len(MW.LAYERS) == 15 and np.median(ssum[np.ix_(rs, rs)][land]) > 0.97
          and np.percentile(ssum, 99.9) < 1.06, (round(float(np.median(ssum[np.ix_(rs, rs)][land])), 3),
                                               round(float(np.percentile(ssum, 99.9)), 3)))
    # the road classes in the splat maps: along each class's polylines (every 2 m) its own layer, not the others
    def along(fn_):
        v__, ls__ = [], []
        for ln in open(os.path.join(WD, fn_), encoding="utf-8"):
            if ln.startswith("v "):
                v__.append([float(t) for t in ln.split()[1:4]])
            elif ln.startswith("l "):
                ls__.append([int(t) - 1 for t in ln.split()[1:]])
        v__ = np.array(v__)
        seg_ = [a_ + (b_ - a_) * (np.arange(max(int(np.linalg.norm(b_ - a_) / 2), 1))[:, None]
                                   / max(int(np.linalg.norm(b_ - a_) / 2), 1))
                for l_ in ls__ for a_, b_ in zip(v__[l_][:-1], v__[l_][1:])]
        return np.concatenate(seg_)
    lnames = [n for n, _ in MW.LAYERS]
    cls_ = {}
    for fn_, nm_ in (("roads/Roads_Main.obj", "Road"), ("roads/Streets.obj", "Setts"), ("roads/Lanes.obj", "Track")):
        p_ = along(fn_)
        w_ = SP[np.clip((p_[:, 2] / 2).astype(int), 0, 2047), np.clip((p_[:, 0] / 2).astype(int), 0, 2047)]
        own_ = lnames.index(nm_)
        oth_ = [lnames.index(o_) for o_ in ("Road", "Setts", "Track") if o_ != nm_]
        cls_[nm_] = (round(float(np.median(w_[:, own_])), 2), round(float(max(np.median(w_[:, o_]) for o_ in oth_)), 2))
    check(f"  the road classes' own splat layers along their polylines (median own, highest other): {cls_}",
          all(v_[0] > 0.6 and v_[1] < 0.1 for v_ in cls_.values()))
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
    del BC, NM, nv, lnv, BCs, bct, nmt, wfull, tiles, full, st, Hm, Hm2, rows, RV, rl, col, nrm_
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
             "Corner_Pillar", "Roof_Cornice", "Roof_Flat", "Roof_Unit", "Roof_Tank", "Roof_Penthouse"]
    check(f"one glb for each of the {len(names)} kit pieces", sorted(kit) == sorted("SM_Kit_" + n for n in names))
    # LODs and collision: LOD0, LOD1 (the small parts stripped) and one convex UCX hull in every glb
    ok_n, ok_l, ok_c, ok_b, bad = True, True, True, True, {}
    for n in names:
        a = "SM_Kit_" + n
        js, nm = node_meshes(kit[a])
        if sorted(nm) != sorted([a + "_LOD0", a + "_LOD1", f"UCX_{a}_00"]):
            ok_n = False
            bad[n] = sorted(nm)
            continue
        t0, t1 = len(nm[a + "_LOD0"][2]), len(nm[a + "_LOD1"][2])
        ok_l &= t1 <= t0 and (t1 < t0 or n in ("Roof_Flat", "Corner_Pillar"))
        Q, _, I, _ = nm[f"UCX_{a}_00"]
        T = Q[I]
        nrm = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
        sd = np.einsum("tk,pk->tp", nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12), Q) \
            - np.einsum("tk,tk->t", nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12), T[:, 0])[:, None]
        ok_c &= bool(np.all((sd.max(1) < 1e-3) | (sd.min(1) > -1e-3)))           # every point on one side of every face
        P0 = nm[a + "_LOD0"][0]
        ok_b &= np.allclose(Q.min(0), P0.min(0), atol=1e-3) and np.allclose(Q.max(0), P0.max(0), atol=1e-3)
    check("  every glb: nodes SM_Kit_<piece>_LOD0, _LOD1 and UCX_SM_Kit_<piece>_00, nothing else", ok_n, bad)
    check("  LOD1 has fewer triangles than LOD0 (the same where nothing is small: the roof panel, the pillar)", ok_l)
    check("  UCX: convex (every point on one side of every face) and exactly the bounds of LOD0", ok_c and ok_b,
          (ok_c, ok_b))
    lj = json.load(open(os.path.join(KD, "SM_Kit_Wall_Window.lods.json")))
    a0 = (lj.get("assets") or [{}])[0]
    check("  SM_Kit_Wall_Window.lods.json: one asset, LOD1 at 40 m, its collision node listed",
          len(lj.get("assets", [])) == 1 and [l_["distance"] for l_ in a0.get("lods", [])] == [0.0, 40.0]
          and a0.get("collision") == ["UCX_SM_Kit_Wall_Window_00"], a0.get("lods"))
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
            "Wall_Shopfront": {"M_Wall", "M_Trim", "M_Glass", "M_Metal", "M_Sign"},
            "Roof_Penthouse": {"M_Wall", "M_Door", "M_Trim", "M_Metal"}}
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
    # the street rules, recomputed from each wall's position and facing
    ST = MW.CITY_STREET

    def facing(r):
        qx, qy, qz, qw = (float(r[c]) for c in ("qx", "qy", "qz", "qw"))
        n = (2 * (qx * qz + qw * qy), 1 - 2 * (qx * qx + qy * qy))
        fx, fz = float(r["px"]) + 2 * n[0], float(r["pz"]) + 2 * n[1]
        main, side = abs(fz) < ST, abs(fx) < ST
        return main, side, main or (side and abs(float(r["pz"])) < 24)

    g0 = [(r, *facing(r)) for r in walls if r["floor"] == "0"]
    far = [r for r, m_, s_, sh in g0 if s_ and not m_ and not sh]
    check("shops: every ground-floor wall on the main street, and on the side street within 24 m of the crossing, "
          "is a shopfront; no other ground floor is",
          all((r["asset"] == "SM_Kit_Wall_Shopfront") == sh for r, m_, s_, sh in g0)
          and any(sh for *_, sh in g0), sum((r["asset"] == "SM_Kit_Wall_Shopfront") != sh for r, m_, s_, sh in g0))
    check("  negative control: the side street away from the crossing has ground floors, none of them shops",
          len(far) > 0 and not any(r["asset"] == "SM_Kit_Wall_Shopfront" for r in far), len(far))
    g1 = [(r, *facing(r)) for r in walls if r["floor"] == "1"]
    check("  towers (9+ floors) stand on a podium: first-floor shopfronts exactly where a 9+ floor building has shops",
          all((r["asset"] == "SM_Kit_Wall_Shopfront") == (sh and floors[int(r["bld"])] >= 9) for r, m_, s_, sh in g1)
          and any(r["asset"] == "SM_Kit_Wall_Shopfront" for r, *_ in g1))
    balf = {}
    for r in walls:
        if r["asset"] == "SM_Kit_Wall_Balcony":
            balf.setdefault(int(r["bld"]), set()).add(int(r["floor"]))

    def one_style(fs):                  # scattered on even floors, or bands on every third floor -- not both
        return all(f % 2 == 0 for f in fs) or all(f % 3 == 2 for f in fs)
    check("  balconies: one style per building (even floors only, or every third floor)",
          balf and all(one_style(fs) for fs in balf.values()), balf)
    check("  negative control: a mixed set (floors 2, 5, 6) is not one style", not one_style({2, 5, 6}))
    pent = [r for r in rows if r["asset"] == "SM_Kit_Roof_Penthouse"]
    check("stair cores: exactly one on each building of 8+ floors, none on lower ones, on its roof, no plant in its cell",
          sorted(int(r["bld"]) for r in pent) == sorted(b for b, f in floors.items() if f >= 8)
          and all(abs(float(r["py"]) - 3.5 * floors[int(r["bld"])]) < 1e-3
                  and occ(float(r["px"]), float(r["pz"])) == int(r["bld"]) for r in pent)
          and not any(abs(float(o["px"]) - float(r["px"])) < 2 and abs(float(o["pz"]) - float(r["pz"])) < 2
                      for r in pent for o in plant), [(r["bld"], r["px"], r["pz"]) for r in pent])
    # the same block for the engine importers: World.json under pcg/city
    wj = os.path.join(OUT, "pcg/city/World.json")
    W = json.load(open(wj)) if os.path.exists(wj) else {}
    ms = W.get("meshes", {})
    import importlib.util as _ilu
    _sp = _ilu.spec_from_file_location("pcg_world_import", os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine", "unreal", "pcg_world_import.py"))
    UE = _ilu.module_from_spec(_sp)
    _sp.loader.exec_module(UE)
    avail = {l_["node"] for m in ms.values() for a in m.get("assets", []) for l_ in a.get("lods", [])}
    ci = {}
    for t in W.get("tiles", []):
        for a, xs in UE.read_instances(W, UE.load(wj)[1], t["tile"]).items():
            ci[a] = ci.get(a, 0) + len(xs)
    check("City world: World.json with the 12 kit glbs as the asset library (role assets), one 1024 m tile, "
          "the facade materials",
          len(ms) == len(names) and all(m.get("role") == "assets" for m in ms.values())
          and [t["tile"] for t in W.get("tiles", [])] == [[0, 0]]
          and W.get("city", {}).get("facade_materials", {}).get("1") == MW.CITY_FACADE_MAT[1], (len(ms), W.get("tiles")))
    check("  the importer reads every row (the block's counts per asset) and finds a mesh for every asset (its LOD0)",
          ci == {a: sum(r["asset"] == a for r in rows) for a in {r["asset"] for r in rows}}
          and all(UE.asset_mesh_name(a, avail) == a + "_LOD0" for a in ci), sorted(ci)[:3])

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
