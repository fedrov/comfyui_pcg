"""
Generates the example workflows in example_workflows/ (ComfyUI UI format, drag them in and they work).

Why generate them with a script instead of wiring them up in the UI and exporting: in the UI format widgets_values is a
**positional** array; add one input to a node or change the order, and a hand-saved workflow silently shifts (values land on other
parameters, no error). The script reads the order from the **live** INPUT_TYPES, so after changing the plugin just run it again;
test_aiterrain.py then converts the generated files to API format and actually runs the PCG nodes.

The input order of the core nodes (checkpoint, sampler, ControlNet, MoGe, Depth Anything) is copied from
ComfyUI 0.30's /object_info (measured on a ComfyUI 0.30 install) and written into CORE.

Usage: python make_workflows.py [output dir]
"""
from __future__ import annotations

import json
import os
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        _PKG = os.path.join(_c, "comfyui_pcg")
        break

WIDGET_TYPES = ("INT", "FLOAT", "STRING", "BOOLEAN", "COMBO")

# Core nodes: (inputs [(name, type or list of options, default)], outputs [(name, type)])
# A list type means a combo box; upper-case ones like "IMAGE" are sockets
CORE = {
    "CheckpointLoaderSimple": (
        [("ckpt_name", ["SDXL\\RealVisXL_V4.0.safetensors"], None)],
        [("MODEL", "MODEL"), ("CLIP", "CLIP"), ("VAE", "VAE")]),
    "CLIPTextEncode": (
        [("text", "STRING", ""), ("clip", "CLIP", None)],
        [("CONDITIONING", "CONDITIONING")]),
    "ControlNetLoader": (
        [("control_net_name",
          ["SDXL\\controlnet-union-sdxl-1_promax.safetensors"], None)],
        [("CONTROL_NET", "CONTROL_NET")]),
    "SetUnionControlNetType": (
        [("control_net", "CONTROL_NET", None),
         ("type", ["auto", "openpose", "depth", "hed/pidi/scribble/ted",
                   "canny/lineart/anime_lineart/mlsd", "normal", "segment",
                   "tile", "repaint"], "depth")],
        [("CONTROL_NET", "CONTROL_NET")]),
    "ControlNetApplyAdvanced": (
        [("positive", "CONDITIONING", None), ("negative", "CONDITIONING", None),
         ("control_net", "CONTROL_NET", None), ("image", "IMAGE", None),
         ("strength", "FLOAT", 1.0), ("start_percent", "FLOAT", 0.0),
         ("end_percent", "FLOAT", 1.0), ("vae", "VAE", None)],
        [("positive", "CONDITIONING"), ("negative", "CONDITIONING")]),
    "EmptyLatentImage": (
        [("width", "INT", 1024), ("height", "INT", 1024),
         ("batch_size", "INT", 1)],
        [("LATENT", "LATENT")]),
    "KSampler": (
        [("model", "MODEL", None), ("seed", "SEED", 0), ("steps", "INT", 28),
         ("cfg", "FLOAT", 5.0),
         ("sampler_name", ["euler", "dpmpp_2m", "dpmpp_2m_sde"], "dpmpp_2m"),
         ("scheduler", ["simple", "karras", "normal"], "karras"),
         ("positive", "CONDITIONING", None), ("negative", "CONDITIONING", None),
         ("latent_image", "LATENT", None), ("denoise", "FLOAT", 1.0)],
        [("LATENT", "LATENT")]),
    "VAEDecode": (
        [("samples", "LATENT", None), ("vae", "VAE", None)],
        [("IMAGE", "IMAGE")]),
    "SaveImage": (
        [("images", "IMAGE", None), ("filename_prefix", "STRING", "pcg/ai")],
        []),
    "PreviewImage": ([("images", "IMAGE", None)], []),
    "LoadImage": (
        [("image", ["example.png"], "example.png"), ("upload", "UPLOAD",
                                                      "image")],
        [("IMAGE", "IMAGE"), ("MASK", "MASK")]),
    "DepthAnythingV2Preprocessor": (
        [("image", "IMAGE", None),
         ("ckpt_name", ["depth_anything_v2_vitl.pth", "depth_anything_v2_vitb.pth",
                        "depth_anything_v2_vits.pth"],
          "depth_anything_v2_vitl.pth"),
         ("resolution", "INT", 768)],
        [("IMAGE", "IMAGE")]),
    "LoadMoGeModel": (
        [("model_name", ["moge_2_vitl_normal.safetensors"], None)],
        [("MOGE_MODEL", "MOGE_MODEL")]),
    "MoGeInference": (
        [("moge_model", "MOGE_MODEL", None), ("image", "IMAGE", None),
         ("resolution_level", "INT", 9), ("fov_x_degrees", "FLOAT", 0.0),
         ("batch_size", "INT", 4), ("force_projection", "BOOLEAN", True),
         ("apply_mask", "BOOLEAN", True)],
        [("moge_geometry", "MOGE_GEOMETRY")]),
}


def _pcg_spec(cls):
    it = cls.INPUT_TYPES()
    ins = []
    for sect in ("required", "optional"):
        for name, spec in (it.get(sect) or {}).items():
            t = spec[0]
            opt = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) \
                else {}
            if isinstance(t, (list, tuple)):
                ins.append((name, list(t), opt.get("default", t[0])))
            else:
                ins.append((name, t, opt.get("default")))
    outs = list(zip(getattr(cls, "RETURN_NAMES", None)
                    or cls.RETURN_TYPES, cls.RETURN_TYPES))
    return ins, outs


def spec_of(ntype):
    if ntype in CORE:
        return CORE[ntype]
    from comfyui_pcg import NODE_CLASS_MAPPINGS as M
    return _pcg_spec(M[ntype])


def is_widget(t):
    return isinstance(t, list) or t in WIDGET_TYPES or t in ("SEED",
                                                              "UPLOAD")


class Graph:
    def __init__(self):
        self.nodes = []
        self.links = []

    def add(self, ntype, pos, title=None, node_mode=0, size=None, **values):
        ins, outs = spec_of(ntype)
        names = [n for n, _, _ in ins]
        for k in values:
            if k not in names:
                raise KeyError(f"{ntype} has no input {k} (has {names})")
        # node_mode is the node's mute state (0 normal / 2 muted / 4 bypassed), not called mode:
        # several nodes have an input called mode themselves (Composite, HeightField from
        # Depth); the first version swallowed it here and Composite silently used the default over
        n = {"id": len(self.nodes) + 1, "type": ntype, "pos": list(pos),
             "mode": node_mode, "title": title, "values": values, "ins": ins,
             "outs": outs, "in_links": {}, "out_links": {},
             "size": size, "props": {}}
        self.nodes.append(n)
        return n

    def note(self, pos, text, size=(420, 200), title="Note"):
        n = {"id": len(self.nodes) + 1, "type": "Note", "pos": list(pos),
             "mode": 0, "title": title, "text": text, "size": list(size)}
        self.nodes.append(n)
        return n

    def link(self, a, out, b, inp):
        onames = [o for o, _ in a["outs"]]
        if out not in onames:
            raise KeyError(f"{a['type']} has no output {out} (has {onames})")
        slot = onames.index(out)
        otype = a["outs"][slot][1]
        itype = dict((n, t) for n, t, _ in b["ins"]).get(inp)
        if itype is None:
            raise KeyError(f"{b['type']} has no input {inp}")
        want = "FLOAT" if itype == "FLOAT" else itype
        if not isinstance(want, list) and want != otype:
            raise TypeError(f"{a['type']}.{out} ({otype}) cannot connect to "
                            f"{b['type']}.{inp} ({itype})")
        lid = len(self.links) + 1
        self.links.append([lid, a["id"], slot, b["id"], inp, otype])
        b["in_links"][inp] = lid
        a["out_links"].setdefault(slot, []).append(lid)
        return lid

    # ────────────────────────────────────────────────────── UI format
    def to_ui(self):
        nodes = []
        links = []
        for L in self.links:
            lid, src, slot, dst, inp, t = L
            dn = self.nodes[dst - 1]
            socket_names = [n for n, ty, _ in dn["ins"]
                            if not is_widget(ty) or n in dn["in_links"]]
            links.append([lid, src, slot, dst, socket_names.index(inp), t])
        order = self._order()
        for n in self.nodes:
            if n["type"] == "Note":
                nodes.append({"id": n["id"], "type": "Note", "pos": n["pos"],
                              "size": n["size"], "flags": {},
                              "order": order[n["id"]], "mode": 0,
                              "title": n["title"],
                              "properties": {"text": ""},
                              "widgets_values": [n["text"]],
                              "color": "#432", "bgcolor": "#653"})
                continue
            inputs = []
            wv = []
            for name, t, d in n["ins"]:
                if is_widget(t):
                    v = n["values"].get(name, d)
                    if isinstance(t, list) and v is None:
                        v = t[0]
                    if t == "SEED":
                        wv += [v, "fixed"]
                    else:
                        wv.append(v)
                    if name in n["in_links"]:
                        inputs.append({"name": name, "type": "FLOAT"
                                       if t == "FLOAT" else t,
                                       "link": n["in_links"][name],
                                       "widget": {"name": name}})
                else:
                    inputs.append({"name": name, "type": t,
                                   "link": n["in_links"].get(name)})
            outputs = []
            for k, (oname, otype) in enumerate(n["outs"]):
                outputs.append({"name": oname, "type": otype,
                                "links": n["out_links"].get(k, []),
                                "slot_index": k})
            nw = sum(1 for _, t, _ in n["ins"] if is_widget(t))
            size = n["size"] or [340, 46 + 24 * (nw + max(
                len(outputs), len(inputs) - sum(
                    1 for i in inputs if "widget" in i)))]
            d = {"id": n["id"], "type": n["type"], "pos": n["pos"],
                 "size": size, "flags": {}, "order": order[n["id"]],
                 "mode": n["mode"], "inputs": inputs, "outputs": outputs,
                 "properties": {"Node name for S&R": n["type"], **n["props"]},
                 "widgets_values": wv}
            if n["title"]:
                d["title"] = n["title"]
            nodes.append(d)
        return {"last_node_id": len(self.nodes),
                "last_link_id": len(self.links), "nodes": nodes,
                "links": links, "groups": [], "config": {},
                "extra": {"ds": {"scale": 0.55, "offset": [40, 60]}},
                "version": 0.4}

    def _order(self):
        deps = {n["id"]: set() for n in self.nodes}
        for _, src, _, dst, _, _ in self.links:
            deps[dst].add(src)
        order, done = {}, set()
        k = 0
        while len(done) < len(deps):
            ready = sorted(i for i, d in deps.items()
                           if i not in done and d <= done)
            for i in ready:
                order[i] = k
                k += 1
                done.add(i)
        return order


# ═══════════════════════════════════════════════════ Workflow 1: terrain -> AI texture
def terrain_to_ai():
    g = Graph()
    X = [0, 380, 760, 1140, 1520, 1900, 2280]
    # Stack down in columns (height estimated from how tall the frontend actually draws it, see Col); node add order unchanged, ids unchanged
    C0, C1, C2, C3, C4, C5, C6 = (Col(g, x, width=340) for x in X)
    g.note((X[0], -330), size=(740, 290), title="Terrain -> AI texture (read me first)",
           text=(
               "A complete procedural terrain -> diffusion model -> back onto the mesh chain.\n\n"
               "1) The two left columns are the terrain: noise -> stream power erosion (cuts river valleys) -> erosion filter -> "
               "thermal erosion -> hydraulic erosion (gullies + sediment, accumulated into debris) -> flow accumulation (rivers, lakes) "
               "-> Splat Map (grass / sediment / rock / snow / water, "
               "the five layers sum to 1 everywhere).\n"
               "2) Regional Prompt writes prompts per splat-layer region (one per line, later lines "
               "take priority); Control Image's height mode outputs a top-down depth map (high = white).\n"
               "3) SDXL + union ControlNet (depth) produces a top-down texture aligned pixel for pixel "
               "with the height field.\n"
               "4) COP Import reads the texture back into COP, Composite puts it into the terrain's albedo layer, "
               "HeightField to Mesh outputs a mesh with Cd=albedo, Geometry Preview's "
               "color mode shows the colours directly, Export Mesh writes a glb.\n\n"
               "Models: swap the checkpoint and ControlNet for your own (an SDXL union / depth "
               "one works). The erosion runs at 512² and is upsampled to 1024² (with a fine relief on top), the generation size, so the "
               "masks, the control image and the texture line up pixel for pixel."))
    noise = C0("PCG_COPNoise", resolution_x=512,
                  resolution_y=512, noise_type="simplex", fractal="standard",
                  frequency=3.0, octaves=6, roughness=0.5, amplitude=0.06,
                  rand_seed=7)
    sp = C0("PCG_COPStreamPower", iterations=60,
               routing="rho8", erodibility=0.03, uplift=0.0, diffusion=0.02,
               rand_seed=7)
    g.link(noise, "cop", sp, "cop")
    ero = C1("PCG_COPErosion", amplitude=0.003,
                wavelength=40.0, rand_seed=7)
    g.link(sp, "cop", ero, "cop")
    th = C1("PCG_COPThermalErosion", talus_angle=38.0,
               iterations=12)
    g.link(ero, "cop", th, "cop")
    hy = C0("PCG_COPHydraulicErosion", rand_seed=7)
    g.link(th, "cop", hy, "cop")
    upr = C0("PCG_COPResize", title="Upsample to 1024² (the generation size)", resolution_x=1024,
             resolution_y=1024)
    g.link(hy, "cop", upr, "cop")
    fin = C0("PCG_COPWrangle", title="Fine relief", code=(
        "n = noise(set(@u * 140, @v * 140, 3.3)) - 0.5 + 0.5 * (noise(set(@u * 300, @v * 300, 8.1)) - 0.5)\n"
        "@C = @C + 0.0012 * n"))
    g.link(upr, "cop", fin, "cop")
    fa = C1("PCG_COPFlowAccumulation", method="d8",
               river_area=0.004, river_softness=0.4)
    g.link(fin, "cop", fa, "cop")
    spl = C2("PCG_COPSplatMap", rock_angle=42.0,
                snow_line=0.78, lake_min=0.003)
    g.link(fa, "cop", spl, "cop")
    ci = C2("PCG_ControlImage", kind="height", mask_layer="")
    g.link(spl, "cop", ci, "cop")
    pv_c = C2("PreviewImage", title="Control image: height (high = white)")
    g.link(ci, "image", pv_c, "images")

    ck = C3("CheckpointLoaderSimple")
    rp = C3("PCG_RegionalPrompt")
    g.link(ck, "CLIP", rp, "clip")
    g.link(spl, "cop", rp, "cop")
    pv_r = C3("PreviewImage", title="Region preview")
    g.link(rp, "preview", pv_r, "images")
    neg = C3("CLIPTextEncode", title="Negative",
                text="perspective, horizon, sky, clouds, text, watermark, "
                     "people, buildings, blurry, lowres")
    g.link(ck, "CLIP", neg, "clip")

    cn = C4("ControlNetLoader")
    ut = C4("SetUnionControlNetType", type="depth")
    g.link(cn, "CONTROL_NET", ut, "control_net")
    ap = C4("ControlNetApplyAdvanced", strength=0.85,
               end_percent=0.85)
    g.link(rp, "conditioning", ap, "positive")
    g.link(neg, "CONDITIONING", ap, "negative")
    g.link(ut, "CONTROL_NET", ap, "control_net")
    g.link(ci, "image", ap, "image")
    g.link(ck, "VAE", ap, "vae")
    lat = C4("EmptyLatentImage")
    ks = C4("KSampler", seed=7)
    g.link(ck, "MODEL", ks, "model")
    g.link(ap, "positive", ks, "positive")
    g.link(ap, "negative", ks, "negative")
    g.link(lat, "LATENT", ks, "latent_image")
    dec = C4("VAEDecode")
    g.link(ks, "LATENT", dec, "samples")
    g.link(ck, "VAE", dec, "vae")
    sv = C5("SaveImage", filename_prefix="pcg/terrain_albedo",
               size=[340, 400])
    g.link(dec, "IMAGE", sv, "images")

    imp = C5("PCG_COPImport", layer="albedo")
    g.link(dec, "IMAGE", imp, "image")
    cmp_ = C5("PCG_COPComposite", mode="replace", layer="C",
                 foreground_layer="albedo", output_layer="albedo")
    g.link(spl, "cop", cmp_, "background")
    g.link(imp, "cop", cmp_, "foreground")
    msh = C6("PCG_COPHeightfieldToMesh", step=2,
                attribs="Cd=albedo")
    g.link(cmp_, "cop", msh, "cop")
    prv = C6("PCG_PreviewImage", width=1600, height=1200,
                elevation=35.0, azimuth=20.0, shading="color", look="studio")
    g.link(msh, "geo", prv, "geo")
    pvm = C6("PreviewImage", title="Textured terrain mesh",
                size=[420, 460])
    g.link(prv, "image", pvm, "images")
    ex = C6("PCG_ExportMesh", filename="pcg/terrain_ai")
    g.link(msh, "geo", ex, "geo")
    return g


# ═══════════════════════════════════════════════════ Workflow 2: an image -> terrain
def image_to_terrain():
    g = Graph()
    X = [0, 380, 760, 1140, 1520]
    C0, C1, C2, C3, C4 = (Col(g, x, width=340) for x in X)
    g.note((X[0], -360), size=(760, 320), title="An image -> terrain (read me first)",
           text=(
               "Lifts a landscape image (a photo or an AI-painted perspective view) into a top-down height field, then feeds the terrain chain.\n\n"
               "**Pick your own landscape in Load Image first**: it opens on ComfyUI's example.png, a cartoon figure against a flat sky - "
               "lifted, the sky turns into a wall at the back and the figure into a spike. Wanted: ground running into the distance, a "
               "camera looking slightly down, a real horizon.\n\n"
               "By default it uses Depth Anything V2 (comfyui_controlnet_aux, the first run "
               "downloads the weights automatically): it outputs **relative inverse depth**, determined only up to scale and shift; "
               "Shift and FOV X are guesses - guess wrong and the terrain gets bent, not uniformly scaled.\n\n"
               "The more accurate route is MoGe (built into ComfyUI core): camera-space points, metric scale "
               "and a sky mask are all provided. Put the MoGe model into models/geometry_estimation/, "
               "select the two greyed-out MoGe nodes below and press Ctrl+M to unmute them - the wires are already "
               "connected: while muted, the frontend drops inputs connected to muted nodes entirely, "
               "so HeightField from Depth uses depth; after unmuting, moge_geometry "
               "takes priority.\n\n"
               "HeightField from Depth's mask layer marks which cells were actually measured; places behind the mountains "
               "that can't be seen are filled by push-pull, i.e. guessed. The world_size output is already wired "
               "downstream, so the scale matches automatically."))
    li = C0("LoadImage")
    da = C1("DepthAnythingV2Preprocessor", resolution=1024)
    g.link(li, "IMAGE", da, "image")
    pvd = C1("PreviewImage", title="Depth (near = white)")
    g.link(da, "IMAGE", pvd, "images")
    lm = C0("LoadMoGeModel", node_mode=2)
    mi = C1("MoGeInference", node_mode=2)
    g.link(lm, "MOGE_MODEL", mi, "moge_model")
    g.link(li, "IMAGE", mi, "image")
    lf = C2("PCG_COPHeightfieldFromDepth", mode="perspective",
               resolution=640, depth_kind="disparity", fov_x=60.0)
    g.link(da, "IMAGE", lf, "depth")
    g.link(mi, "moge_geometry", lf, "moge_geometry")
    g.link(li, "IMAGE", lf, "image")
    sp = C2("PCG_COPStreamPower", iterations=30,
               erodibility=0.02, diffusion=0.01)
    g.link(lf, "cop", sp, "cop")
    g.link(lf, "world_size", sp, "world_size")
    msh = C3("PCG_COPHeightfieldToMesh", step=1,
                attribs="Cd=albedo mask")
    g.link(sp, "cop", msh, "cop")
    g.link(lf, "world_size", msh, "world_size")
    prv = C3("PCG_PreviewImage", width=1600, height=1200,
                elevation=30.0, azimuth=0.0, shading="color", look="studio")
    g.link(msh, "geo", prv, "geo")
    pvm = C4("PreviewImage", title="Lifted terrain",
                size=[420, 460])
    g.link(prv, "image", pvm, "images")
    ex = C3("PCG_ExportMesh", filename="pcg/terrain_from_image")
    g.link(msh, "geo", ex, "geo")
    return g


# ═══════════════════════════════════════════════════ Layout
# The first two workflows have hand-placed coordinates; the later ones have more nodes, so they stack down in columns, with height estimated
# from "how tall the frontend actually draws it": sections whose toggle is off are collapsed (the web/pcg_sections.js rule: the last gate in a section
# decides), and COP nodes have a thumbnail underneath as wide as the node (pcg_cop_preview.js).
# An inaccurate estimate only makes the gaps between nodes uneven; nodes never overlap.
def _sections(ntype):
    if ntype in CORE:
        return {}
    from comfyui_pcg import NODE_CLASS_MAPPINGS as M
    it = M[ntype].INPUT_TYPES()
    out = {}
    for sect in ("required", "optional"):
        for name, spec in (it.get(sect) or {}).items():
            o = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            if isinstance(o.get("section"), str):
                out[name] = (o["section"], bool(o.get("section_gate")))
    return out


def est_height(n, width):
    """
    How tall a node is. PCG nodes are replaced by a parameter panel in the frontend (web/pcg_panel.js): use panel.py's estimate
    (computed from the panel's tabs / collapsible sections / hidewhen at the current parameter values; coefficients measured in the real frontend, error within 3%);
    other nodes are counted one native widget row at a time.
    """
    if n["type"].startswith("PCG_"):
        from comfyui_pcg import NODE_CLASS_MAPPINGS as M
        from comfyui_pcg.panel import panel_applies, estimate_node_height
        cls = M[n["type"]]
        it = cls.INPUT_TYPES()
        if panel_applies(n["type"], it):
            linked = [name for name, t, _ in n["ins"]
                      if is_widget(t) and name in n["in_links"]]
            return estimate_node_height(
                n["type"], it, len(n["outs"]), n["values"], max(width, 340), linked,
                any(t == "COPIMAGE" for _, t in n["outs"]))
    meta = _sections(n["type"])
    gates, members, cur = {}, [], None
    vis = 0
    for name, t, d in n["ins"]:
        if not is_widget(t) or name in n["in_links"]:
            continue
        info = meta.get(name)
        if info:
            cur = info[0]
        if info and info[1]:
            gates[cur] = n["values"].get(name, d)
            vis += 1
        elif cur is not None and (info or cur in gates):
            members.append(cur)
        else:
            vis += 1
    vis += sum(1 for sec in members if gates.get(sec, True) is not False)
    socks = sum(1 for name, t, _ in n["ins"]
                if not is_widget(t) or name in n["in_links"])
    h = 34 + 22 * max(socks, len(n["outs"])) + 25 * vis
    if any(t == "COPIMAGE" for _, t in n["outs"]):
        h += width + 10
    return h


class Col:
    """A column of nodes, stacked top to bottom."""

    def __init__(self, g, x, y=0, width=340, gap=44):
        self.g, self.x, self.y, self.w, self.gap = g, x, y, width, gap

    def __call__(self, ntype, title=None, size=None, node_mode=0, **values):
        if size is None and ntype in ("PreviewImage", "SaveImage", "LoadImage"):
            size = [self.w, self.w + 60]              # image previews need a square area
        n = self.g.add(ntype, (self.x, self.y), title=title,
                       node_mode=node_mode, size=size, **values)
        if size is None:
            n["size"] = [max(self.w, 340) if ntype.startswith("PCG_") else self.w,
                         est_height(n, self.w)]
        self.y += n["size"][1] + self.gap
        return n

    def note(self, text, h=220, title="Note", w=None):
        n = self.g.note((self.x, self.y), text, size=(w or self.w, h),
                        title=title)
        self.y += h + self.gap
        return n


# ═══════════════════════════════════════════════════ Workflow 3: rock garden (pure SOP)
def rock_garden():
    g = Graph()
    W = 360
    A, B, C, D = (Col(g, x, width=W) for x in (0, 420, 840, 1260))
    E = Col(g, 1680, width=560)
    A.note(size_note := (
        "Purely procedural modelling, no model files at all.\n\n"
        "① Left column: For-Each (count mode) runs 8 times, each pass takes a low-poly sphere; Point Jitter's and "
        "Attribute Noise's rand_seed are both wired to iteration - the same chain produces 8 rocks, each with a "
        "different shape. Match Size puts each rock's bottom on y = 0, Connectivity numbers each piece (class). "
        "Poly Reduce then makes a low-poly set at 20% of the polygons for the small pebbles (LOD).\n\n"
        "② Second column: terrain = grid + terrain fractal noise; a Wrangle colours by slope and computes a "
        "\"gentle + noise patches\" boulder weight, promoted to primitives to act as the scatter group "
        "(the group field just says @boulder > 0.5).\n\n"
        "③ Third column: Scatter and Align scatters the big rocks (Avoid Overlap pushes them apart with Point Relax, "
        "Tilt keeps them from all sitting upright), a Wrangle picks a random class for each point, "
        "Copy to Points with Piece Attribute = class picks rocks by number - one node places all 8 kinds. "
        "Pebbles work the same way, using the low-poly library, no avoidance, more tilt.\n\n"
        "④ Rocks grow moss based on how upward-facing they are plus noise, get merged with the terrain, and output a preview image, a 3D viewport and a glb."),
        h=520, title="Rock garden (read me first)", w=W)
    del size_note

    # ① Rock library
    sph = A("PCG_Sphere", radius=1.0, cols=12, rows=8)
    fb = A("PCG_ForEachBegin", title="Each rock (count × 8)", method="fetch_input",
           iterate_over="count", iterations=8)
    g.link(sph, "geo", fb, "geo")
    jit = A("PCG_PointJitter", scale=0.55)
    g.link(fb, "geo", jit, "geo")
    g.link(fb, "iteration", jit, "rand_seed")
    sq = A("PCG_Transform", title="Squash a bit", sy=0.7)
    g.link(jit, "geo", sq, "geo")
    sd = A("PCG_Subdivide", depth=2)
    g.link(sq, "geo", sd, "geo")
    nm = A("PCG_Normal", cusp_angle=180.0)
    g.link(sd, "geo", nm, "geo")
    ns = B("PCG_AttribNoise", title="Pits on the rock surface (along normal)",
           noise_along_vector=True, amplitude=0.12, noise_type="worley_f2f1",
           fractal="standard", octaves=2, element_size_x=0.35,
           element_size_y=0.35, element_size_z=0.35)
    g.link(nm, "geo", ns, "geo")
    g.link(fb, "iteration", ns, "rand_seed")
    ms = B("PCG_MatchSize", title="Bottom on the ground (sunk 0.15 more)", justify_y="min",
           use_justify_to=True, offset_y=-0.15)
    g.link(ns, "geo", ms, "geo")
    fe = B("PCG_ForEachEnd", gather="merge")
    g.link(ms, "geo", fe, "geo")
    g.link(fb, "loop", fe, "loop")
    cn = B("PCG_Connectivity", title="Number each piece → prim class", cls="prim",
           attribute="class")
    g.link(fe, "geo", cn, "geo")
    lib = B("PCG_Normal", title="Rock library (8 pieces)", cusp_angle=180.0)
    g.link(cn, "geo", lib, "geo")
    low = B("PCG_PolyReduce", title="Low-poly library (for pebbles)", keep_percent=20.0)
    g.link(lib, "geo", low, "geo")

    # ② Terrain
    grd = C("PCG_Grid", size_x=40.0, size_z=40.0, cols=240, rows=240)
    ter = C("PCG_AttribNoise", title="Terrain relief", use_x=False, use_z=False,
            amplitude=2.5, noise_type="perlin", fractal="terrain", octaves=5,
            element_size_x=16.0, element_size_y=16.0, element_size_z=16.0,
            rand_seed=3)
    g.link(grd, "geo", ter, "geo")
    cv = C("PCG_Wrangle", title="Dig a stream", code=(
        "# distance to a sine curve → dig a trench along it (the code is Python syntax + @attributes, whole column computed at once)\n"
        "@dstream = abs(@P.z - 5 * sin(@P.x * 0.16) - 2)\n"
        "@P.y -= 1.2 * (1 - smoothstep(0.0, 3.0, @dstream))"))
    g.link(ter, "geo", cv, "geo")
    tn = C("PCG_Normal")
    g.link(cv, "geo", tn, "geo")
    tw = C("PCG_Wrangle", title="Colour + scatter weights", code=(
        "d = @dstream\n"
        "steep = smoothstep(0.06, 0.22, 1 - @N.y)\n"
        "# flat ground is grass, steep places show soil, the stream banks are gravel, the stream is water\n"
        "# grass varies between lush and dry in broad patches, plus a fine mottle\n"
        "dry = smoothstep(0.35, 0.65, noise(@P * 0.12 + 7.7)) * 0.7 + 0.3 * noise(@P * 1.3)\n"
        "grass = lerp(set(0.20, 0.30, 0.11), set(0.36, 0.37, 0.18), dry)\n"
        "@Cd = lerp(grass, set(0.40, 0.32, 0.23), steep)\n"
        "@Cd = lerp(set(0.50, 0.46, 0.40), @Cd, smoothstep(1.2, 2.2, d))\n"
        "@Cd = lerp(set(0.10, 0.22, 0.30), @Cd, smoothstep(0.7, 1.0, d))\n"
        "# big rocks: gentle slope, inside noise patches, a bit away from the stream (appear in clusters, not scattered uniformly)\n"
        "@boulder = (1 - steep) * smoothstep(0.46, 0.56, noise(@P * 0.09 + 3.1))"
        " * smoothstep(3.0, 4.5, d)\n"
        "# pebbles: stream banks\n"
        "@bank = smoothstep(0.7, 1.2, d) * (1 - smoothstep(1.8, 3.2, d))"))
    g.link(tn, "geo", tw, "geo")
    tp = C("PCG_AttribPromote", title="Weights → primitives (scatter groups need primitives)",
           original_name="boulder bank", original_class="point",
           new_class="prim", method="average", delete_original=False)
    g.link(tw, "geo", tp, "geo")

    # ③ Scatter + copy
    sa = D("PCG_ScatterAlign", title="Big rocks", group="@boulder > 0.5",
           mode="count", count=230, scale_min=0.3, scale_max=1.3,
           rotate_random=360.0, tilt=18.0, avoid_overlap=True,
           overlap_scale=1.1, relax_iterations=20, rand_seed=1)
    g.link(tp, "geo", sa, "geo")
    pk = D("PCG_Wrangle", title="Pick a random piece", code=(
        "i@class = floor(rand(@ptnum + 0.5) * 8)"))
    g.link(sa, "geo", pk, "geo")
    cp = D("PCG_CopyToPoints", title="Place rocks by class", piece_attribute="class")
    g.link(lib, "geo", cp, "source")
    g.link(pk, "geo", cp, "points")
    sb = D("PCG_ScatterAlign", title="Stream-bank pebbles", group="@bank > 0.3",
           mode="count", count=2600, scale_min=0.05, scale_max=0.2, tilt=40.0,
           rand_seed=2)
    g.link(tp, "geo", sb, "geo")
    pk2 = D("PCG_Wrangle", title="Pick a random piece", code=(
        "i@class = floor(rand(@ptnum + 0.25) * 8)"))
    g.link(sb, "geo", pk2, "geo")
    cp2 = D("PCG_CopyToPoints", title="Place pebbles (low-poly)", piece_attribute="class")
    g.link(low, "geo", cp2, "source")
    g.link(pk2, "geo", cp2, "points")
    rk = D("PCG_Merge", title="All rocks")
    g.link(cp, "geo", rk, "geo1")
    g.link(cp2, "geo", rk, "geo2")
    moss = D("PCG_Wrangle", title="Rock colour + moss", code=(
        "rock = set(0.44, 0.42, 0.39) * (0.7 + 0.35 * rand(@class + 7)) * (0.85 + 0.3 * noise(@P * 3.0))\n"
        "# upward-facing faces × noise patches → moss\n"
        "m = smoothstep(0.55, 0.85, @N.y) * smoothstep(0.42, 0.6, noise(@P * 1.5))\n"
        "@Cd = lerp(rock, set(0.22, 0.31, 0.11), m)"))
    g.link(rk, "geo", moss, "geo")

    # ④ Output
    mg = E("PCG_Merge", title="Terrain + rocks")
    g.link(tp, "geo", mg, "geo1")
    g.link(moss, "geo", mg, "geo2")
    vp = E("PCG_Viewport", size=[560, 560])
    g.link(mg, "geo", vp, "geo")
    pr = E("PCG_PreviewImage", width=1600, height=1066, elevation=32.0,
           azimuth=30.0, shading="color", look="studio")
    g.link(mg, "geo", pr, "geo")
    pv = E("PreviewImage", title="Rock garden", size=[560, 460])
    g.link(pr, "image", pv, "images")
    ex = E("PCG_ExportMesh", filename="pcg/rock_garden")
    g.link(mg, "geo", ex, "geo")
    return g


# ═══════════════════════════════════════════════════ Workflow 4: city block (pure SOP)
def city_block():
    g = Graph()
    W = 360
    A, B, C, D = (Col(g, x, width=W) for x in (0, 420, 840, 1260))
    E = Col(g, 1680, width=560)
    A.note((
        "A whole city district, all primitive operations + groups, not a single hand-placed point.\n\n"
        "① Lots: a 9×9 grid of 12 m cells; Poly Extrude only insets without extruding (distance 0) to leave room for streets, "
        "Blast keeps the inset faces = 81 lots; a Wrangle computes heights on the primitives (taller towards the centre, "
        "rand by @primnum, in prim context @P is the face centre), crown heights and numbers; another inset ring "
        "separates the sidewalks.\n\n"
        "② Buildings: extrude by the prim attribute height (Local Control's Distance Attribute); "
        "Group Create's base says @height > 28 to select the tall buildings, Group Combine intersects them with the top faces, "
        "first inset to make a setback terrace, then extrude the tower by crown.\n\n"
        "③ Facades: Divide's Bricker cuts the walls into 1.6 m × 3.2 m window cells (floor lines align automatically), "
        "the ground floor is selected with a bounding box and made into recessed shopfronts, every other cell is inset + pushed in = window frame and glass; "
        "roofs are inset and sunk to make parapets.\n\n"
        "④ Details: AC units scattered on the roofs, street trees scattered on the sidewalks (pushed apart with Point Relax), "
        "each building picks a colour scheme by its number, 12% of windows are lit. All colours are written on prims (Color's Class is also set to "
        "prim): when merging, every part's Cd is on the same class, so you don't get half point colours and half primitive colours."),
        h=560, title="City block (read me first)", w=W)

    # ① Lots
    grd = A("PCG_Grid", title="Street grid (9 × 9 lots of 12 m)", size_x=108.0,
            size_z=108.0, cols=10, rows=10)
    st = A("PCG_PolyExtrude", title="Make room for streets (inset only)",
           divide_into="individual", distance=0.0, inset=1.4,
           output_side=False)
    g.link(grd, "geo", st, "geo")
    lots = A("PCG_Blast", title="Keep the lots", group="extrudeFront", cls="prim",
             keep_selected=True)
    g.link(st, "geo", lots, "geo")
    lw = A("PCG_Wrangle", title="Per lot: height / crown / number", run_over="prim",
           code=(
               "# in prim context @P is the face centre\n"
               "center = 1 - smoothstep(10, 46, length(@P))\n"
               "r = rand(@primnum + 0.37)\n"
               "@height = 6 + 40 * pow(r, 2.2) * (0.35 + 0.65 * center) + 18 * center\n"
               "@crown = 0.35 * @height\n"
               "i@lot = @primnum"))
    g.link(lots, "geo", lw, "geo")
    sw = A("PCG_PolyExtrude", title="Sidewalk ring (inset again)",
           divide_into="individual", distance=0.0, inset=0.9,
           front_group="footprint", side_group="sidewalk")
    g.link(lw, "geo", sw, "geo")

    # ② Buildings
    bd = B("PCG_PolyExtrude", title="Extrude by height", group="footprint",
           divide_into="individual", distance=1.0, use_local=True,
           distance_attrib="height", front_group="roof", side_group="walls")
    g.link(sw, "geo", bd, "geo")
    tall = B("PCG_GroupCreate", title="Tall buildings", name="tall", cls="prim",
             base="@height > 28")
    g.link(bd, "geo", tall, "geo")
    sbk = B("PCG_GroupCombine", title="Top faces of tall buildings", group_type="prim",
            expression="tall & roof", output_group="setback")
    g.link(tall, "geo", sbk, "geo")
    ter = B("PCG_PolyExtrude", title="Setback terrace (inset)", group="setback",
            divide_into="individual", distance=0.0, inset=1.4,
            front_group="setbase", side_group="terrace")
    g.link(sbk, "geo", ter, "geo")
    tw = B("PCG_PolyExtrude", title="Tower (extrude by crown)", group="setbase",
           divide_into="individual", distance=1.0, use_local=True,
           distance_attrib="crown", front_group="roof2", side_group="walls2")
    g.link(ter, "geo", tw, "geo")
    gw = B("PCG_GroupCombine", title="All walls", group_type="prim",
           expression="walls | walls2", output_group="walls")
    g.link(tw, "geo", gw, "geo")
    gr = B("PCG_GroupCombine", title="All roofs", group_type="prim",
           expression="(roof - setback) | roof2", output_group="roof")
    g.link(gw, "geo", gr, "geo")

    # ③ Facades
    br = C("PCG_Divide", title="Cut window cells (1.6 m × 3.2 m)", group="walls",
           convex_polygons=False, brick_polygons=True, brick_size_x=1.6,
           brick_size_y=3.2, brick_size_z=1.6)
    g.link(gr, "geo", br, "geo")
    gnd = C("PCG_GroupCreate", title="Ground floor (bounding box y < 3.3)", name="ground",
            cls="prim", base="walls", use_bbox=True, cy=1.6, sx=500.0,
            sy=3.3, sz=500.0)
    g.link(br, "geo", gnd, "geo")
    up = C("PCG_GroupCombine", title="Upper-floor window cells", group_type="prim",
           expression="walls - ground", output_group="upper")
    g.link(gnd, "geo", up, "geo")
    shop = C("PCG_PolyExtrude", title="Shopfronts (recessed)", group="ground",
             divide_into="individual", inset=0.25, distance=-0.5,
             limit_insetting=True,
             front_group="shop", side_group="shopside")
    g.link(up, "geo", shop, "geo")
    # Limit Insetting: the top row of window cells may be only a few centimetres tall, and an inset of 0.45 would push points
    # outside the cell (window frames poking through the roof). With it on, each cell is clamped to its own size
    win = C("PCG_PolyExtrude", title="Window frame + glass", group="upper",
            divide_into="individual", inset=0.3, distance=-0.2,
            limit_insetting=True,
            front_group="glass", side_group="frame")
    g.link(shop, "geo", win, "geo")
    par = C("PCG_PolyExtrude", title="Parapet (roof inset and sunk)", group="roof",
            divide_into="individual", inset=0.35, distance=-0.8,
            front_group="roofin", side_group="parapet")
    g.link(win, "geo", par, "geo")

    # ④ Colour + details
    cw = D("PCG_Wrangle", title="One colour scheme per building", run_over="prim", code=(
        "r = rand(@lot + 0.1)\n"
        "base = where(r < 0.33, set(0.78, 0.74, 0.66),\n"
        "             where(r < 0.66, set(0.62, 0.66, 0.72), set(0.66, 0.42, 0.34)))\n"
        "@Cd = base * (0.85 + 0.25 * rand(@lot + 0.7))"))
    g.link(par, "geo", cw, "geo")
    cg = D("PCG_Wrangle", title="Glass: 12% lit", run_over="prim", group="glass",
           code=("@Cd = where(rand(@primnum * 0.37 + @lot) > 0.88,\n"
                 "            set(0.95, 0.78, 0.46), set(0.10, 0.14, 0.20))"))
    g.link(cw, "geo", cg, "geo")
    cs = D("PCG_Wrangle", title="Shopfront / roof / sidewalk", run_over="prim",
           group="shop roofin terrace sidewalk", code=(
               "@Cd = set(0.36, 0.36, 0.38)"))
    g.link(cg, "geo", cs, "geo")
    cs2 = D("PCG_Color", title="Warm shopfront light", attribute_class="prim", group="shop",
            mode="constant", r=0.95, g=0.72, b=0.38)
    g.link(cs, "geo", cs2, "geo")
    cs3 = D("PCG_Color", title="Sidewalk", attribute_class="prim",
            group="sidewalk", mode="constant", r=0.62, g=0.61, b=0.58)
    g.link(cs2, "geo", cs3, "geo")

    # Rooftop equipment
    ac = D("PCG_Box", title="AC unit", size_x=1.6, size_y=0.9, size_z=1.2)
    acm = D("PCG_MatchSize", title="Bottom on y = 0", justify_y="min")
    g.link(ac, "geo", acm, "geo")
    acp = D("PCG_Scatter", title="Scatter on roofs", group="roofin", count=300,
            rand_seed=4, use_out_attribs=False)
    g.link(par, "geo", acp, "geo")
    acc = D("PCG_CopyToPoints", title="Place them", transform_using_orientations=False)
    g.link(acm, "geo", acc, "source")
    g.link(acp, "points", acc, "points")
    acc2 = D("PCG_Color", title="Metal grey", attribute_class="prim",
             mode="constant", r=0.55, g=0.57, b=0.6)
    g.link(acc, "geo", acc2, "geo")

    # Street trees
    E2 = Col(g, 2300, width=W)
    trunk = E2("PCG_Tube", title="Trunk", radius1=0.12, radius2=0.08,
               height=2.0, cols=8, rows=2)
    tk = E2("PCG_MatchSize", title="Trunk bottom on the ground", justify_y="min")
    g.link(trunk, "geo", tk, "geo")
    tkc = E2("PCG_Color", attribute_class="prim", mode="constant", r=0.35,
             g=0.25, b=0.18)
    g.link(tk, "geo", tkc, "geo")
    crown = E2("PCG_Sphere", title="Crown", radius=0.9, cols=12, rows=8)
    cr2 = E2("PCG_Transform", ty=2.6, sy=1.2)
    g.link(crown, "geo", cr2, "geo")
    crc = E2("PCG_Color", attribute_class="prim", mode="constant", r=0.22,
             g=0.42, b=0.18)
    g.link(cr2, "geo", crc, "geo")
    tree = E2("PCG_Merge", title="One tree")
    g.link(tkc, "geo", tree, "geo1")
    g.link(crc, "geo", tree, "geo2")
    tp = E2("PCG_Scatter", title="Scatter on sidewalks (pushed apart)", group="sidewalk",
            count=520, rand_seed=9, use_relax=True, relax_iterations=10,
            use_out_attribs=False)
    g.link(cs3, "geo", tp, "geo")
    ts = E2("PCG_AttribRandomize", title="Varying sizes", name="pscale",
            min_x=0.75, max_x=1.3, rand_seed=3)
    g.link(tp, "points", ts, "geo")
    tc = E2("PCG_CopyToPoints", title="Plant trees", transform_using_orientations=False)
    g.link(tree, "geo", tc, "source")
    g.link(ts, "geo", tc, "points")

    # Output
    road = E("PCG_Grid", title="Road surface", size_x=112.0, size_z=112.0, cols=2,
             rows=2)
    rd = E("PCG_Transform", ty=-0.05)
    g.link(road, "geo", rd, "geo")
    rdc = E("PCG_Color", title="Asphalt", attribute_class="prim", mode="constant",
            r=0.16, g=0.16, b=0.17)
    g.link(rd, "geo", rdc, "geo")
    mg = E("PCG_Merge", title="Everything")
    g.link(cs3, "geo", mg, "geo1")
    g.link(acc2, "geo", mg, "geo2")
    g.link(tc, "geo", mg, "geo3")
    g.link(rdc, "geo", mg, "geo4")
    vp = E("PCG_Viewport", size=[560, 560])
    g.link(mg, "geo", vp, "geo")
    pr = E("PCG_PreviewImage", width=1600, height=1066, elevation=32.0,
           azimuth=35.0, shading="color", look="studio")
    g.link(mg, "geo", pr, "geo")
    pv = E("PreviewImage", title="City block", size=[560, 460])
    g.link(pr, "image", pv, "images")
    ex = E("PCG_ExportMesh", filename="pcg/city_block")
    g.link(mg, "geo", ex, "geo")
    return g


# ═══════════════════════════════════════════════════ Workflow 5: brick wall PBR (pure COP)
def brick_material():
    g = Graph()
    W = 360
    A, B, C = (Col(g, x, width=W) for x in (0, 420, 840))
    D = Col(g, 1260, width=W)
    E = Col(g, 1680, width=520)
    A.note((
        "A complete set of tileable brick wall textures using only COP nodes. 2048², seamless on all sides.\n\n"
        "① Noise: a Perlin fractal for brick surface relief and dirt (detail), Crystal Noise for cracks "
        "(pits); both are periodic only in u, so Retile's seamless mode cross-fades them to seamless in both directions.\n\n"
        "② Tile Pattern makes the bricks (4 × 10, offset 0.5) and brings a set of helper layers: a per-brick random number "
        "pattern_rand, pixel distance to the brick edge pattern_edge, bevel height pattern_height. "
        "A COP Wrangle combines them into height: brick-edge distance plus noise perturbation, then thresholded = chipped edges and corners.\n\n"
        "③ Height → normal / AO / curvature (all with Tile on, sampling periodically at the borders, so no discontinuity at the seams). "
        "The second Wrangle picks a brick colour by each brick's random number (10% dark over-fired bricks), brightens worn convex edges, multiplies by AO, "
        "and outputs roughness along the way.\n\n"
        "④ Light lights it with normal + height (with shadows) to check the look, Tile 2×2 checks it is seamless. "
        "On the right each map is saved separately; the normal is exported in signed mode (-1..1 → 0..1)."),
        h=560, title="Brick wall PBR (read me first)", w=W)

    nz = A("PCG_COPNoise", title="Brick relief / dirt", resolution_x=2048,
           resolution_y=2048, noise_type="perlin", fractal="standard",
           frequency=8.0, octaves=6, layer="detail", rand_seed=1)
    ck = A("PCG_COPNoiseExtra", title="Cracks", kind="crystal", frequency=48.0,
           out_layer="pits", rand_seed=3)
    g.link(nz, "cop", ck, "cop")
    sm = B("PCG_COPRetile", title="Make seamless both ways", layers="detail pits",
           mode="seamless")
    g.link(ck, "cop", sm, "cop")
    pt = B("PCG_COPPattern", title="Bricks (4 × 10, offset)", kind="tile",
           counts="4 10", offset=0.5, gap=0.018, bevel=0.12, jitter=1.0,
           rand_seed=5)
    g.link(sm, "cop", pt, "cop")
    ht = C("PCG_COPWrangle", title="Height + chipped edges", code=(
        "d = @detail - 0.5\n"
        "# pixel distance to the brick edge plus noise perturbation; below the threshold counts as chipped off\n"
        "chip = smoothstep(3.0, 12.0, @pattern_edge + d * 36)\n"
        "@brick = chip\n"
        "# Crystal Noise cell borders = cracks (pits is close to 0 on the borders), only on about a third of the bricks\n"
        "# and fading out across each of those, so cracked bricks read as weathered rather than tiled\n"
        "cracked = smoothstep(0.5, 0.7, frac(@pattern_rand * 7.31)) * smoothstep(0.3, 0.5, @detail)\n"
        "face = @pattern_height * (0.85 + 0.15 * @pattern_rand) + d * 0.12 - (1 - @pits) * 0.03 * cracked\n"
        "mortar = 0.08 + d * 0.05\n"
        "@height = lerp(mortar, face, chip)"))
    g.link(pt, "cop", ht, "cop")
    nm = C("PCG_COPHeightToNormal", layer="height", strength=0.03, tile=True,
           out_layer="N")
    g.link(ht, "cop", nm, "cop")
    ao = C("PCG_COPHeightToAO", layer="height", strength=0.03, radius=24.0,
           tile=True, out_layer="ao")
    g.link(nm, "cop", ao, "cop")
    cv = D("PCG_COPCurvature", layer="height", strength=0.03, tile=True,
           scale=0.002, out_layer="curvature")
    g.link(ao, "cop", cv, "cop")
    al = D("PCG_COPWrangle", title="Albedo + roughness", code=(
        "r = @pattern_rand\n"
        "d = @detail - 0.5\n"
        "brick = lerp(set(0.50, 0.20, 0.13), set(0.70, 0.36, 0.22), r)\n"
        "brick = where(r > 0.88, set(0.28, 0.14, 0.10), brick)   # 10% over-fired bricks\n"
        "brick = brick * (0.9 + d * 0.5)\n"
        "brick = brick + set(0.12, 0.10, 0.08) * clamp(@curvature, 0, 1)   # brighten worn convex edges\n"
        "mortar = set(0.60, 0.58, 0.54) * (0.9 + d * 0.4)\n"
        "@albedo = lerp(mortar, brick, @brick) * lerp(0.55, 1.0, @ao)\n"
        "@roughness = lerp(0.95, 0.72 + d * 0.3, @brick)"))
    g.link(cv, "cop", al, "cop")
    lt = D("PCG_COPLight", title="Light to check the look", normal_layer="N",
           albedo_layer="albedo", height_layer="height", azimuth=135.0,
           elevation=58.0, shadows=True, strength=0.03, ambient=0.3,
           specular=0.15, out_layer="lit")
    g.link(al, "cop", lt, "cop")
    tl = D("PCG_COPTile", title="2×2 seamless check", tiles_x=2, tiles_y=2)
    g.link(lt, "cop", tl, "cop")

    hs = D("PCG_COPResize", title="2×2 at half size (2048²)", resolution_x=2048, resolution_y=2048)
    g.link(tl, "cop", hs, "cop")
    ex = E("PCG_COPExport", title="Tiled preview", layer="lit")
    g.link(hs, "cop", ex, "cop")
    pv = E("PreviewImage", title="Lit 2×2", size=[520, 540])
    g.link(ex, "image", pv, "images")
    for layer, mode, name in (("albedo", "clamp", "albedo"),
                              ("N", "signed", "normal"),
                              ("roughness", "clamp", "roughness"),
                              ("height", "clamp", "height"),
                              ("ao", "clamp", "ao")):
        e = E("PCG_COPExport", title=f"Export {name}", layer=layer, mode=mode)
        g.link(lt, "cop", e, "cop")
        sv = E("SaveImage", title=name, filename_prefix=f"pcg/brick_{name}",
               size=[520, 520])
        g.link(e, "image", sv, "images")
    return g


# ═══════════════════════════════════════════════════ Workflow 6: full terrain map set (pure COP)
def terrain_maps():
    g = Graph()
    W = 360
    A, B, C, D = (Col(g, x, width=W) for x in (0, 420, 840, 1260))
    E = Col(g, 1680, width=520)
    F = Col(g, 2240, width=520)
    A.note((
        "From noise to a complete set of terrain maps, all in COP, no AI, no mesh. Erosion is simulated at 512², the maps come out at 1024².\n\n"
        "① Shape: a hybrid terrain fractal + a Wrangle raises the middle into a mountain mass; Stream Power "
        "cuts dendritic river valleys, Strata makes rock-layer terraces, thermal erosion slumps into talus piles (debris), "
        "hydraulic erosion carves gullies and accumulates sediment into debris (this step is the slowest, over ten seconds on numpy; "
        "with CUDA it runs on the GPU automatically).\n\n"
        "② Water: Flow Accumulation computes the drainage area → river network river, filled depressions lake.\n\n"
        "③ Materials: Splat Map splits into five layers grass / sediment / rock / snow / water (summing to 1 everywhere), "
        "and also outputs splat_rgba (for the engine's terrain layers).\n\n"
        "④ Shading: normal, AO, shadows; a Wrangle mixes colours from the five layers (rock gets bands by height, "
        "wet areas are darkened), Light lights it with shadows. Also outputs a contour map.\n\n"
        "The right column is all Save Image: height, normal, splat, albedo, final image."),
        h=560, title="Full terrain map set (read me first)", w=W)

    nz = A("PCG_COPNoise", title="Base relief (simulated at 512²)", resolution_x=512,
           resolution_y=512, noise_type="simplex", fractal="hybrid_terrain",
           frequency=2.5, octaves=7, roughness=0.5, amplitude=0.08,
           rand_seed=11)
    up = A("PCG_COPWrangle", title="Raise the middle into a mountain", code=(
        "r = length(set(@u - 0.5, @v - 0.5))\n"
        "@C = @C + 0.05 * (1 - smoothstep(0.1, 0.55, r)) - 0.02"))
    g.link(nz, "cop", up, "cop")
    sp = B("PCG_COPStreamPower", title="River valleys (Stream Power)", iterations=60,
           erodibility=0.03, diffusion=0.02, rand_seed=11)
    g.link(up, "cop", sp, "cop")
    stt = B("PCG_COPStrata", title="Rock-layer terraces", spacing=0.012, strength=0.5,
            sharpness=0.7, noise_amount=0.3, rand_seed=2)
    g.link(sp, "cop", stt, "cop")
    th = B("PCG_COPThermalErosion", title="Talus (thermal erosion)",
           talus_angle=38.0, iterations=15)
    g.link(stt, "cop", th, "cop")
    hy = C("PCG_COPHydraulicErosion", title="Gullies + sediment (hydraulic erosion)",
           rand_seed=11)
    g.link(th, "cop", hy, "cop")
    # The erosion stack is tuned per pixel (and the droplet solver is the slow part), so it runs at 512²; the result is
    # upsampled and gets a fine relief the coarse grid cannot hold before rivers, splat and lighting run at 1024²
    upr = C("PCG_COPResize", title="Upsample to 1024²", resolution_x=1024, resolution_y=1024)
    g.link(hy, "cop", upr, "cop")
    fin = C("PCG_COPWrangle", title="Fine relief", code=(
        "n = noise(set(@u * 140, @v * 140, 3.3)) - 0.5 + 0.5 * (noise(set(@u * 300, @v * 300, 8.1)) - 0.5)\n"
        "@C = @C + 0.0012 * n"))
    g.link(upr, "cop", fin, "cop")
    fa = C("PCG_COPFlowAccumulation", title="Rivers / lakes", method="d8",
           river_area=0.004, river_softness=0.4)
    g.link(fin, "cop", fa, "cop")
    spl = C("PCG_COPSplatMap", title="Five material layers", rock_angle=40.0,
            snow_line=0.8, lake_min=0.003)
    g.link(fa, "cop", spl, "cop")
    nm = D("PCG_COPHeightToNormal", strength=2.0, out_layer="N")
    g.link(spl, "cop", nm, "cop")
    ao = D("PCG_COPHeightToAO", strength=2.0, radius=20.0, out_layer="ao")
    g.link(nm, "cop", ao, "cop")
    al = D("PCG_COPWrangle", title="Mix colours from five layers", code=(
        "d = @C.x\n"
        "grass = set(0.28, 0.38, 0.14) * (1 - 0.35 * clamp(@wetness, 0, 1))\n"
        "sed = set(0.55, 0.48, 0.36)\n"
        "# rock gets bands by height (sedimentary bedding)\n"
        "band = 0.5 + 0.5 * sin(d * 520)\n"
        "rock = lerp(set(0.42, 0.36, 0.31), set(0.58, 0.52, 0.45), band)\n"
        "snow = set(0.92, 0.93, 0.96)\n"
        "water = set(0.10, 0.22, 0.30)\n"
        "c = grass * @splat_grass + sed * @splat_sediment + rock * @splat_rock"
        " + snow * @splat_snow + water * @splat_water\n"
        "@albedo = c * lerp(0.6, 1.0, @ao)"))
    g.link(ao, "cop", al, "cop")
    lt = D("PCG_COPLight", title="Lighting (with shadows)", normal_layer="N",
           albedo_layer="albedo", height_layer="C", azimuth=135.0,
           elevation=40.0, shadows=True, strength=2.0, ambient=0.4,
           out_layer="lit")
    g.link(al, "cop", lt, "cop")
    vis = D("PCG_COPVisualize", title="Contour map", mode="height_ramp",
            ramp="terrain", contour_interval=0.005, hillshade=0.6,
            out_layer="vis")
    g.link(lt, "cop", vis, "cop")

    for col, layer, mode, name, title in (
            (E, "lit", "clamp", "lit", "Final image"),
            (E, "vis", "clamp", "topo", "Contour map"),
            (E, "albedo", "clamp", "albedo", "Albedo"),
            (F, "C", "normalize", "height", "Height (normalized to this image)"),
            (F, "N", "signed", "normal", "Normal"),
            (F, "splat_rgba", "clamp", "splat", "splat: rock / snow / sediment / water")):
        e = col("PCG_COPExport", title=f"Export {name}", layer=layer, mode=mode)
        g.link(vis, "cop", e, "cop")
        sv = col("SaveImage", title=title,
                 filename_prefix=f"pcg/terrain_{name}", size=[520, 520])
        g.link(e, "image", sv, "images")
    return g




# ═══════════════════════════════════════════════════ Production 1: rock asset pipeline
ROCK_SDF = (
        '# signed distance field of the rock (positive outside, negative inside). seed comes in via rand_seed = which rock\n'
        's = seed * 17.31 + 3.7\n'
        '# smooth max (intersection) with blend radius k: hard edges become small rounded bevels, like weathered stone\n'
        'def smax(a, b, k):\n'
        '    h = clamp(0.5 + 0.5 * (b - a) / k, 0, 1)\n'
        '    return lerp(a, b, h) + k * h * (1 - h)\n'
        '# ① proportions per rock: a boulder, a slab, a block, a tall one... (the field is built in this stretched space)\n'
        'sc = set(0.85 + 0.4 * rand(s + 1), 0.55 + 0.45 * rand(s + 2), 0.75 + 0.35 * rand(s + 3))\n'
        'Q = @P / sc\n'
        '# ② the big faces: 13 random half-spaces (more of them sideways and up than down), 1.5 cm bevels -- the\n'
        '#    faces meet in crisp arrises, which is what makes it read as broken stone and not as a pebble\n'
        'd = -1e9\n'
        'for k in range(13):\n'
        '    n = normalize(set(rand(s + 10 * k) - 0.5, (rand(s + 10 * k + 1) - 0.3) * 1.2, rand(s + 10 * k + 2) - 0.5))\n'
        '    d = smax(d, dot(Q, n) - (0.62 + 0.3 * rand(s + 10 * k + 3)), 0.015)\n'
        '#    one deep split face on most rocks: a whole side sheared off along a joint plane\n'
        'n = normalize(set(rand(s + 300) - 0.5, rand(s + 301) * 0.6, rand(s + 302) - 0.5))\n'
        'd = smax(d, dot(Q, n) - (0.42 + 0.2 * rand(s + 303)), 0.01)\n'
        '# ③ fracture chips: 4 planes that only shave off an edge or a corner (offset just inside the faces), sharper bevel\n'
        'for k in range(4):\n'
        '    n = normalize(set(rand(s + 7 * k + 200) - 0.5, rand(s + 7 * k + 201) - 0.2, rand(s + 7 * k + 202) - 0.5))\n'
        '    d = smax(d, dot(Q, n) - (0.66 + 0.14 * rand(s + 7 * k + 203)), 0.012)\n'
        '# ④ keep it compact: a soft intersection with a sphere trims only the far corners (the faces stay flat)\n'
        'd = smax(d, length(Q) - 1.25, 0.06)\n'
        '# back to metres (the stretch makes distances up to 1/min scale too long; the min keeps it a lower bound)\n'
        'd = d * min(min(sc.x, sc.y), sc.z)\n'
        '# ⑤ broad undulation and shallow weathering hollows only -- grooves, cracks and grain are added per texel after the\n'
        '#    bake (see "Texture-space detail"): at 2.2 cm voxels they would come out as stair-stepped dashes\n'
        'd = d + 0.035 * (noise(@P * 1.7 + s) - 0.5) + 0.012 * (1 - abs(2 * noise(@P * 5.3 + s + 7) - 1))\n'
        '#    (no bedding steps here: a stepped profile in the field is a jump the surface nets turn into a staircase on\n'
        '#    the silhouette; the layers are texel detail, see "Texture-space detail")\n'
        '# ⑥ flat bottom (sits on the ground without wobbling), and never touch the sampling volume\'s walls (an open\n'
        '#    surface there frays the mesh)\n'
        'd = max(d, -@P.y - 0.5)\n'
        'b = abs(@P) - set(1.25, 1.0, 1.15)\n'
        'd = max(d, max(max(b.x, b.y), b.z))\n'
        '@value = d\n')


# Per-texel detail of the rock atlas (pcg110). Runs on COP Bake Textures' layers: position (high-poly hit point),
# worldnormal, tangent / bitangent (the frame of normal_ts), normal_ts, displacement, high_curv.
TEXEL_DETAIL = (
    "# which rock: the atlas cell; the bake had rock N moved by N * 3.5 m in x -- undo it so the detail is the rock's own\n"
    "idx = floor(@u * 4)\n"
    "s = idx * 17.31 + 3.7\n"
    "P = @position - set(3.5, 0, 0) * idx\n"
    "T = normalize(@tangent)\n"
    "B = normalize(@bitangent)\n"
    "tilt = normalize(set(rand(s + 91) - 0.5, 2.0, rand(s + 92) - 0.5))\n"
    "\n"
    "# Detail height in metres (negative = into the rock). The low-frequency parts (layer warp, where grooves and cracks\n"
    "# fade) are evaluated once; only the sharp parts are re-evaluated 3 mm along T and B for the slope.\n"
    "warp = 0.8 * noise(P * 1.1 + s) + 0.25 * noise(P * 3.7 + s + 5)\n"
    "gfade = smoothstep(0.45, 0.7, noise(P * 2.2 + s + 17))\n"
    "cfade = smoothstep(0.45, 0.7, noise(P * 0.8 + s + 60))\n"
    "def sharp(Q):\n"
    "    band = frac(dot(Q, tilt) * 5.5 + warp)\n"
    "    # only every so often a layer joint opens into a groove (not every band), so they don't read as ruled lines\n"
    "    open_ = smoothstep(0.55, 0.75, noise(set(floor(dot(Q, tilt) * 5.5 + warp), s + 0 * band, 3.3 + 0 * band)))\n"
    "    groove = smoothstep(0.86, 0.95, band) * (1 - smoothstep(0.95, 1.0, band)) * gfade * open_\n"
    "    crack = (1 - smoothstep(0.0, 0.012, abs(noise(Q * 1.4 + s + 40) - 0.5))) * cfade\n"
    "    grain = 0.6 * (noise(Q * 14 + s + 11) - 0.5) + 0.4 * (noise(Q * 45 + s + 23) - 0.5)\n"
    "    # weathering: hand-sized lumps and hollows, and pits where softer grains fell out\n"
    "    lump = noise(Q * 4.5 + s + 7) - 0.5\n"
    "    pit = smoothstep(0.64, 0.76, noise(Q * 10 + s + 29))\n"
    "    return -0.007 * groove - 0.018 * crack + 0.006 * grain + 0.014 * lump - 0.007 * pit, groove, crack + 0.15 * pit\n"
    "\n"
    "h, groove, crack = sharp(P)\n"
    "e = 0.003\n"
    "dT = (sharp(P + T * e)[0] - h) / e\n"
    "dB = (sharp(P + B * e)[0] - h) / e\n"
    "del T, B\n"
    "b = @normal_ts\n"
    "# tilt the baked high-poly normal by the detail slope (TS x along tangent, y along bitangent)\n"
    "@normal_ts = normalize(set(b.x - dT, b.y - dB, b.z)) * @mask + set(0, 0, 1) * (1 - @mask)\n"
    "del b, dT, dB\n"
    "@displacement = @displacement + h * @mask\n"
    "@crevice = clamp(groove * 0.6 + crack, 0, 1)\n"
    "\n"
    "# colour per texel: strata on the same warped layers as the grooves (low contrast), mottling, fine speckle, pale\n"
    "# worn edges, dark cavities and crevices, olive moss on the flatter tops\n"
    "cav = clamp(-@high_curv / 20, 0, 1)\n"
    "edge = clamp(@high_curv / 25, 0, 1)\n"
    "strata = 0.5 + 0.5 * sin((dot(P, tilt) * 5.5 + warp) * 6.2832)\n"
    "base = lerp(set(0.36, 0.33, 0.29), set(0.49, 0.46, 0.40), strata)\n"
    "base = base * (0.74 + 0.40 * noise(P * 4.0 + s + 1.7) + 0.22 * (noise(P * 22 + s + 5) - 0.5))\n"
    "# iron staining: rusty washes in broad patches, stronger below (where water runs off)\n"
    "stain = smoothstep(0.52, 0.72, noise(P * 1.6 + s + 44)) * (0.5 + 0.5 * noise(P * 7 + s + 13))\n"
    "base = lerp(base, set(0.46, 0.33, 0.21), 0.38 * stain)\n"
    "base = lerp(base, set(0.66, 0.64, 0.60), edge * 0.55)\n"
    "base = lerp(base, set(0.16, 0.14, 0.12), clamp(cav * 0.6 + @crevice * 0.45, 0, 1))\n"
    "Nw = normalize(@worldnormal)\n"
    "moss = smoothstep(0.75, 0.95, Nw.y) * smoothstep(0.56, 0.7, noise(P * 1.8 + s + 9) + 0.35 * (noise(P * 12 + s) - 0.5))\n"
    "mc = lerp(set(0.20, 0.23, 0.11), set(0.31, 0.33, 0.17), noise(P * 9 + s + 3))\n"
    "# lichen: small pale crusts in loose clusters, on any face that is not overhanging\n"
    "lichen = smoothstep(0.68, 0.72, noise(P * 14 + s + 31)) * smoothstep(0.45, 0.7, noise(P * 1.3 + s + 77))"
    " * smoothstep(-0.3, 0.2, Nw.y)\n"
    "base = lerp(base, set(0.56, 0.56, 0.48), 0.45 * lichen)\n"
    "@moss = moss * @mask\n"
    "# the colours above are picked as display (sRGB) values; the layer is linear -- Write File encodes it to sRGB\n"
    "@basecolor = clamp(lerp(base, mc, moss), 0, 1) ** 2.2\n")


def rock_assets():
    g = Graph()
    W = 360
    A, B, C, D, E = (Col(g, x, width=W) for x in (0, 420, 840, 1260, 1680))
    F = Col(g, 2100, width=W)
    G = Col(g, 2520, width=520)
    A.note((
        "Produces 4 engine-ready rock assets in one go, purely procedural, no source files at all. Each rock:\n"
        "  · high-poly (~35k faces, SDF → voxels → surface nets)\n"
        "  · LOD0 ~4500 triangles (the same SDF lightly blurred and re-extracted at 9 cm voxels, uniform quads), "
        "auto seams + LSCM/ARAP flattening + shape-interlocking packing\n"
        "  · LOD1 / LOD2 reduced from LOD0 (Preserve UVs: half-edge collapse, seams locked, **share textures with LOD0**)\n"
        "  · convex-decomposition collision (UCX_ prefix, one convex hull per piece, ≤ 32 points / 60 triangles each)\n"
        "  · textures: BaseColor (sRGB) / Normal (tangent space, OpenGL +Y) / ORM (AO, roughness, "
        "metallic packed) / Height (16-bit, range in the .json next to it)\n\n"
        "① For-Each runs 4 times, rand_seed wired to iteration: in the SDF an intersection of 13 random half-spaces (the rock's "
        "big faces, crisp 1.5 cm arrises) + a deep split face + edge chips + a soft trim by a sphere + noise + flattened bottom, a different rock each pass.\n"
        "② The high-poly is coloured by curvature / bedding / upward-facing amount (dirt build-up, moss, weathered edges); this colour is later baked into "
        "BaseColor.\n"
        "③ The 4 LOD0s each take one cell of a 4096×1024 atlas that is baked in one go (uv_atlas); when writing files "
        "it is cut by cell - the same idea as UDIM. The baked tangents and the exported TANGENT are the same set, "
        "so if the engine import uses the tangents from the file, the normal map matches pixel for pixel.\n"
        "④ Export: one glb per rock (SM_Rock_0N.glb), containing one "
        "node each for LOD0 / LOD1 / LOD2 / UCX, all four sharing one material slot Rock_0N; the glb already references BaseColor / Normal / "
        "ORM by relative path (T_Rock_0N_*.png, same folder output/pcg/assets/rocks/), so dragged into Blender "
        "or an engine it comes in textured. The pivot is at the ground line: the flat bottom is at y = −0.5, so placing it on the ground buries it half a metre, "
        "and on slopes no floating bottom shows (this is how the open-world pipeline's instance table places them).\n\n"
        "Takes about two to three minutes on a real machine (reduction and baking are the bulk). To make more rocks change iterations, and change three places together: the atlas width "
        "(COP Bake's X resolution), the 4 in uv_atlas, and the file writers' Tiles X."),
        h=760, title="Rock asset pipeline (read me first)", w=W)

    # ① Variant loop: high-poly
    vol = A("PCG_Volume", title="Sampling volume (2.8 × 2.3 × 2.6 m)", res_x=128,
            res_y=104, res_z=120, size_x=2.8, size_y=2.3, size_z=2.6, value=1.0)
    fb = A("PCG_ForEachBegin", title="Each rock (count × 4)", method="fetch_input",
           iterate_over="count", iterations=4)
    g.link(vol, "geo", fb, "geo")
    sdf = B("PCG_VolumeWrangle", title="Rock SDF (seed = which rock)", code=ROCK_SDF)
    g.link(fb, "geo", sdf, "geo")
    g.link(fb, "iteration", sdf, "rand_seed")
    hi = B("PCG_Convert", title="Voxels → high-poly", convert_to="polygons")
    g.link(sdf, "geo", hi, "geo")
    hn = B("PCG_Normal", cusp_angle=180.0)
    g.link(hi, "geo", hn, "geo")
    cu = B("PCG_Measure", title="Curvature (concave < 0 < convex)", element_type="points",
           measurement="curvature", attribute_name="curv")
    g.link(hn, "geo", cu, "geo")
    hc = B("PCG_Wrangle", title="Colour the high-poly (baked into BaseColor)", code=(
        "# curvature (1/m): concave areas collect dirt and darken, convex edges weather and whiten; a bit of bedding colour variation by height; moss on upward-facing areas\n"
        "cav = clamp(-@curv / 20, 0, 1)\n"
        "edge = clamp(@curv / 25, 0, 1)\n"
        "band = 0.5 + 0.5 * sin(@P.y * 11 + 4 * noise(@P * 1.3))\n"
        "base = lerp(set(0.40, 0.37, 0.33), set(0.45, 0.42, 0.37), band)\n"
        "base = base * (0.85 + 0.3 * noise(@P * 4.0 + 1.7))\n"
        "base = lerp(base, set(0.66, 0.64, 0.60), edge * 0.6)\n"
        "base = lerp(base, set(0.14, 0.12, 0.10), cav * 0.7)\n"
        "moss = smoothstep(0.55, 0.9, @N.y) * smoothstep(0.45, 0.65, noise(@P * 1.8 + 9))\n"
        "@Cd = lerp(base, set(0.30, 0.33, 0.16), moss)"))
    g.link(cu, "geo", hc, "geo")
    ht = B("PCG_Wrangle", title="High-poly: tag", run_over="prim", code=(
        's@part = "high"\n'
        's@asset = "SM_Rock_%02d" % seed\n'
        "s@name = @asset"))
    g.link(hc, "geo", ht, "geo")
    g.link(fb, "iteration", ht, "rand_seed")

    # ② Low-poly + UV + LOD + collision
    # LOD0 comes straight from the same SDF: blur away high frequencies → resample at 12 cm voxels → surface nets.
    # All uniform quads, none of the long thin triangles a reduction leaves (those make UV flattening flip and packing overlap)
    vb = C("PCG_VolumeBlur", title="Remove high frequencies from SDF", radius=0.04)
    g.link(sdf, "geo", vb, "geo")
    vr = C("PCG_VolumeResample", title="9 cm voxels", mode="voxel_size",
           voxel_size=0.09)
    g.link(vb, "geo", vr, "geo")
    lo = C("PCG_Convert", title="LOD0 (~4500 triangles, uniform quads)",
           convert_to="polygons")
    g.link(vr, "geo", lo, "geo")
    ln = C("PCG_Normal", title="Smooth normals (detail left to the normal map)")
    g.link(lo, "geo", ln, "geo")
    sm = C("PCG_UVAutoSeams", title="Auto seams", mode="charts", cone_angle=150.0)
    g.link(ln, "geo", sm, "geo")
    fl = C("PCG_UVFlatten", title="LSCM + ARAP flatten (uniform texel density)",
           seam_group="seams", arap_iterations=10)
    g.link(sm, "geo", fl, "geo")
    lay = C("PCG_UVLayout", title="Shape-interlocking packing", padding=0.006, method="raster",
            pack_resolution=256)
    g.link(fl, "geo", lay, "geo")
    at = C("PCG_Wrangle", title="uv_atlas: rock N moves to cell N", run_over="vertex",
           code=("# the 4 rocks are packed into one 4096×1024 atlas and baked together; uv itself stays (used for export)\n"
                 "@uv_atlas = set((@uv.x + seed) / 4.0, @uv.y)"))
    g.link(lay, "geo", at, "geo")
    g.link(fb, "iteration", at, "rand_seed")
    l0 = C("PCG_Wrangle", title="LOD0: tag", run_over="prim", code=(
        's@part = "LOD0"\n'
        's@asset = "SM_Rock_%02d" % seed\n'
        '# material slot: the LODs / collision of one rock share one, textures are looked up by its name (T_Rock_00_*)\n'
        's@material = "Rock_%02d" % seed\n'
        's@name = @asset + "_LOD0"'))
    g.link(at, "geo", l0, "geo")
    g.link(fb, "iteration", l0, "rand_seed")
    r1 = D("PCG_PolyReduce", title="LOD1 (50%, shared UVs)", keep_percent=50.0,
           preserve_uvs=True)
    g.link(at, "geo", r1, "geo")
    l1 = D("PCG_Wrangle", title="LOD1: tag", run_over="prim", code=(
        's@part = "LOD1"\n'
        's@asset = "SM_Rock_%02d" % seed\n'
        '# material slot: the LODs / collision of one rock share one, textures are looked up by its name (T_Rock_00_*)\n'
        's@material = "Rock_%02d" % seed\n'
        's@name = @asset + "_LOD1"'))
    g.link(r1, "geo", l1, "geo")
    g.link(fb, "iteration", l1, "rand_seed")
    r2 = D("PCG_PolyReduce", title="LOD2 (20%, shared UVs)", keep_percent=20.0,
           preserve_uvs=True)
    g.link(at, "geo", r2, "geo")
    l2 = D("PCG_Wrangle", title="LOD2: tag", run_over="prim", code=(
        's@part = "LOD2"\n'
        's@asset = "SM_Rock_%02d" % seed\n'
        '# material slot: the LODs / collision of one rock share one, textures are looked up by its name (T_Rock_00_*)\n'
        's@material = "Rock_%02d" % seed\n'
        's@name = @asset + "_LOD2"'))
    g.link(r2, "geo", l2, "geo")
    g.link(fb, "iteration", l2, "rand_seed")
    cx = D("PCG_ConvexDecompose", title="Collision: ≤ 4 convex pieces, ≤ 32 points each", mode="hull",
           max_pieces=4, name_attribute="", max_hull_points=32)
    g.link(r2, "geo", cx, "geo")
    uc = D("PCG_Wrangle", title="Collision: UCX_ naming", run_over="prim", code=(
        's@part = "UCX"\n'
        's@asset = "SM_Rock_%02d" % seed\n'
        's@material = "Rock_%02d" % seed\n'
        "# one name per convex piece: UCX_assetname_00, _01 ... (the common engine collision naming convention)\n"
        's@name = sprintf("UCX_%s_%02d", @asset, @piece)'))
    g.link(cx, "geo", uc, "geo")
    g.link(fb, "iteration", uc, "rand_seed")
    mg = E("PCG_Merge", title="Everything for this rock")
    for i, n in enumerate((ht, l0, l1, l2, uc)):
        g.link(n, "geo", mg, f"geo{i + 1}")
    off = E("PCG_Wrangle", title="Spread out (so bake rays don't hit other rocks)", code=(
        "i@variant = seed\n"
        "@P.x += seed * 3.5"))
    g.link(mg, "geo", off, "geo")
    g.link(fb, "iteration", off, "rand_seed")
    fe = E("PCG_ForEachEnd", gather="merge")
    g.link(off, "geo", fe, "geo")
    g.link(fb, "loop", fe, "loop")

    # ③ Bake
    bh = E("PCG_Blast", title="High-poly", group='@part == "high"', cls="prim",
           keep_selected=True)
    g.link(fe, "geo", bh, "geo")
    bl = E("PCG_Blast", title="LOD0 (for baking)", group='@part == "LOD0"', cls="prim",
           keep_selected=True)
    g.link(fe, "geo", bl, "geo")
    bk = F("PCG_COPBakeTextures", title="Bake atlas 4096×1024", resolution_x=4096,
           resolution_y=1024, uv_attrib="uv_atlas", high_attribs="curv",
           max_distance=0.25, dilate=8, world_normal=True, position=True)
    g.link(bl, "geo", bk, "low")
    g.link(bh, "geo", bk, "high")
    # Texture-space detail (pcg110): everything finer than the high-poly's 2.2 cm voxels is computed per texel from
    # the baked surface position, so the 1024 px per rock carry real detail instead of interpolated vertex colours
    td = F("PCG_COPWrangle", title="Texture-space detail: grooves, cracks, grain, colour", code=TEXEL_DETAIL,
           rows_per_pass=128)
    g.link(bk, "cop", td, "cop")
    ao = F("PCG_COPHeightToAO", title="AO (height difference along normal)", layer="displacement",
           strength=1.0, world_size=4 * 1.8, radius=10.0, out_layer="ao_disp")
    g.link(td, "cop", ao, "cop")
    mx = F("PCG_COPWrangle", title="BaseColor / ORM", code=(
        "# curvature cavities, grooves and cracks also count as occlusion; take the min with the height-difference AO\n"
        "cav = clamp(-@high_curv / 20, 0, 1)\n"
        "@ao = min(@ao_disp, 1 - 0.55 * cav) * (1 - 0.4 * @crevice) * @mask + (1 - @mask)\n"
        "@basecolor = @basecolor * lerp(0.7, 1.0, @ao)\n"
        "lum = dot(@basecolor, set(0.3, 0.59, 0.11))\n"
        "# worn convex edges are smoother, moss and crevices rougher\n"
        "@roughness = clamp(0.88 - 0.3 * clamp(@high_curv / 30, 0, 1) - 0.1 * lum + 0.08 * @moss + 0.06 * @crevice, 0.4, 1)\n"
        "@metallic = 0"))
    g.link(ao, "cop", mx, "cop")
    lt = F("PCG_COPLight", title="Light to check the normal map", normal_layer="normal_ts",
           albedo_layer="basecolor", azimuth=135.0, elevation=40.0,
           ambient=0.3, out_layer="lit")
    g.link(mx, "cop", lt, "cop")
    for layer, mode, fmt, bits, enc, name in (
            ("basecolor", "clamp", "png", "8", "srgb", "BaseColor"),
            ("normal_ts", "signed", "png", "8", "linear", "Normal"),
            ("ao roughness metallic", "clamp", "png", "8", "linear", "ORM"),
            ("displacement", "normalize", "png", "16", "linear", "Height")):
        w = G("PCG_COPWriteFile", title=f"Write {name} (cut into 4 by cell)",
              filename=f"pcg/assets/rocks/T_Rock_{{tx:02}}_{name}", channels=layer,
              format=fmt, bit_depth=bits, encode=enc, remap=mode, tiles_x=4)
        g.link(lt, "cop", w, "cop")
    # basecolor is linear (Write File encodes it); the lit check image needs the same sRGB encode to look right
    ld = G("PCG_COPWrangle", title="Lit preview to sRGB", code="@lit = clamp(@lit, 0, 1) ** (1 / 2.2)")
    g.link(lt, "cop", ld, "cop")
    pa = G("PCG_COPExport", title="Atlas preview (lit)", layer="lit")
    g.link(ld, "cop", pa, "cop")
    pvt = G("PreviewImage", title="Textures of the 4 rocks (lit)", size=[520, 200])
    g.link(pa, "image", pvt, "images")

    # Final preview: LOD0 with the baked atlas (BaseColor + tangent-space normal map) straight from the COP chain,
    # i.e. how it looks in the engine - low-poly silhouette, high-poly and texel detail
    fp = G("PCG_PreviewImage", title="LOD0 + baked textures (studio)", width=1600, height=420,
           elevation=16.0, azimuth=12.0, shading="color", look="studio", uv_attrib="uv_atlas",
           textures="basecolor = @basecolor\nnormal = @normal_ts\norm = @ao roughness metallic")
    g.link(bl, "geo", fp, "geo")
    g.link(mx, "cop", fp, "textures_cop")
    sv = G("SaveImage", title="LOD0 + baked textures", filename_prefix="pcg/assets/rocks/preview",
           size=[520, 240])
    g.link(fp, "image", sv, "images")

    # ④ Export + preview
    ex_ = F("PCG_Blast", title="Remove high-poly", group='@part == "high"', cls="prim",
            keep_selected=False)
    g.link(fe, "geo", ex_, "geo")
    back = F("PCG_Wrangle", title="Move back to origin", code="@P.x -= @variant * 3.5")
    g.link(ex_, "geo", back, "geo")
    em = F("PCG_ExportMesh", title="Export: one glb per rock (textures attached)",
           filename="pcg/assets/rocks/{name}",
           format="glb", split_attribute="name", file_attribute="asset",
           textures=("basecolor = T_{material}_BaseColor.png\n"
                     "normal = T_{material}_Normal.png\n"
                     "orm = T_{material}_ORM.png"))
    g.link(back, "geo", em, "geo")
    ph = G("PCG_PreviewImage", title="High-poly (with bake colour)", width=1024, height=384,
           elevation=20.0, azimuth=0.0, shading="color", look="studio")
    g.link(bh, "geo", ph, "geo")
    pv1 = G("PreviewImage", title="High-poly", size=[520, 260])
    g.link(ph, "image", pv1, "images")
    lb = G("PCG_Blast", title="LODs only", group='@part == "LOD0" | @part == "LOD1" | @part == "LOD2"',
           cls="prim", keep_selected=True)
    g.link(fe, "geo", lb, "geo")
    t1 = G("PCG_Transform", title="Move LOD1 back one row", tz=3.2, group='@part == "LOD1"')
    g.link(lb, "geo", t1, "geo")
    t2 = G("PCG_Transform", title="Move LOD2 back another row", tz=6.4, group='@part == "LOD2"')
    g.link(t1, "geo", t2, "geo")
    pl = G("PCG_PreviewImage", title="LOD0 / 1 / 2 with the baked textures", width=1024, height=768,
           elevation=35.0, azimuth=0.0, shading="color", look="studio", uv_attrib="uv_atlas",
           textures="basecolor = @basecolor\nnormal = @normal_ts\norm = @ao roughness metallic")
    g.link(t2, "geo", pl, "geo")
    g.link(mx, "cop", pl, "textures_cop")
    pv2 = G("PreviewImage", title="LOD", size=[520, 420])
    g.link(pl, "image", pv2, "images")
    vp = G("PCG_Viewport", size=[520, 520])
    g.link(back, "geo", vp, "geo")
    return g


# ═══════════════════════════════════════════════════ Production 2: open-world terrain tiles
CAM2 = (-1150.0, 230.0, 250.0, 296.0, 150.0, -1080.0)   # a ridge south-west of the main peak


def world_tiles():
    g = Graph()
    W = 360
    A, B, C, D, E = (Col(g, x, width=W) for x in (0, 420, 840, 1260, 1680))
    F = Col(g, 2100, width=W)
    G = Col(g, 2520, width=520)
    A.note((
        "A 4 km × 4 km island for an open world, delivered as 4 × 4 tiles, engine-agnostic:\n"
        "  · Height: 1025² samples, 4 m per cell; each tile a 257² 16-bit PNG, **neighbouring tiles share the row of "
        "pixels on their common edge** (heights at the seams are bit-identical when stitched); metres = minimum + value × range, the range is in "
        "Height.json's range_scaled (one range for the whole map, the same for all tiles; the sea floor is negative). A full-map .r16 is included too.\n"
        "  · Weight maps: six layers Grass / ForestFloor / Sediment / Rock / Sand / Water, one "
        "8-bit greyscale PNG per tile per layer, **summing to 1 everywhere** (usable directly as the engine's terrain layers).\n"
        "  · Instances: trees (3 pine and 2 broadleaf kinds, split by altitude), bushes, rocks (asset names match the "
        "SM_Rock_0N exported by the rock pipeline), written as CSV in 1024 m tiles, plus Instances_index.json listing each tile.\n\n"
        "Coordinate convention (written into every .json): origin at the north-west corner = top left of the height map, x east, z south (matching image "
        "row order), y up, units in metres. Instance transforms are read the same way as Copy to Points, so what the preview places "
        "is what the table says.\n\n"
        "① Terrain, grown by its rivers: an island outline and an uplift map (more under a few massifs) → Stream Power at "
        "513² with the sea as base level: the whole island rises while rivers cut it, so every slope belongs to a "
        "valley and every valley reaches the coast → resize to 1025² → buttresses, rock roughness, gully pattern "
        "(erosion filter) → HeightField Erode (Capacity 4 with the bed change limit; writes the flow, sediment and "
        "debris masks) → flow accumulation → river beds cut 1.5-5 m into the valley floors. About two and a half "
        "minutes on numpy, much less with CUDA.\n"
        "② Ecology and colour from the erosion masks: cliffs above 45°, scree below them, sand on the beach and in the "
        "river beds, water in the sea and the trunk rivers, woodland in the valleys, grass that is lush where water "
        "collects, dry on the ridges and heath-coloured on the high ground, darker along every gully.\n"
        "③ Distribution: each of the three instance kinds scatters by its density map, samples height, picks an asset and sets orientation (trees upright with random rotation, "
        "rocks tilted a bit towards the slope).\n"
        "④ Write files + preview: the full-map mesh with instance proxies and a sea to the horizon, shot from the air "
        "in the Outdoor look (afternoon sun, clouds, haze)."),
        h=800, title="Open-world terrain tiles (read me first)", w=W)

    # ① Terrain: grown by Stream Power at 513² (8 m cells) over the whole island, detailed and eroded at 1025²
    nz = A("PCG_COPNoise", title="Base noise (513²)", resolution_x=513, resolution_y=513,
           noise_type="simplex", fractal="standard", frequency=3.0, octaves=6, roughness=0.5,
           amplitude=0.5, bias=0.5, rand_seed=21)
    mt = A("PCG_COPWrangle", title="Island outline + uplift map", code=(
        "# island outline: distance from the centre, pushed in and out by two scales of noise (bays, headlands)\n"
        "dx = @u - 0.5\n"
        "dy = @v - 0.5\n"
        "r = sqrt(dx * dx + dy * dy) * 2\n"
        "coast = 0.78 + 0.45 * (noise(set(@u * 2.3, @v * 2.3, 1.7)) - 0.5) + 0.16 * (noise(set(@u * 7, @v * 7, 5.2)) - 0.5)\n"
        "land = smoothstep(0.0, 0.10, coast - r)\n"
        "# the sea is the rivers' base level (Stream Power's Outlet Layer)\n"
        "@sea = 1 - smoothstep(0.0, 0.004, coast - r)\n"
        "# uplift: everywhere on the island (no flat interior), more under a few massifs, less toward the coast\n"
        "pk = noise(set(@u * 3.1, @v * 3.1, 9.4))\n"
        "pk2 = noise(set(@u * 6.5, @v * 6.5, 3.3))\n"
        "@up = land * (0.25 + 1.1 * smoothstep(0.35, 0.8, pk) + 0.35 * pk2) * smoothstep(0.0, 0.5, coast - r + 0.15)\n"
        "@land = land\n"
        "@C = lerp(-0.012, 0.004 + 0.01 * @C, land)"))
    g.link(nz, "cop", mt, "cop")
    # Uplift against erosion until they balance: relief ~ Uplift / Erodibility. Diffusion sets how far apart the
    # valleys are (0.04: a finely dissected badland; 0.25: a few smooth domes); 0.12 gives valleys 150-300 m apart
    sp = A("PCG_COPStreamPower", title="Grow the island (uplift + rivers to the sea)", strength=2048.0,
           world_size=4100.0, iterations=300, erodibility=0.05, uplift=0.9, uplift_layer="up", diffusion=0.12,
           base_layer="sea", routing="rho8", rand_seed=21)
    g.link(mt, "cop", sp, "cop")
    bl = B("PCG_COPBlur", title="Soften the one-cell river cuts", sigma_pixels=0.8, border="clamp", layers="C")
    g.link(sp, "cop", bl, "cop")
    r2 = B("PCG_COPResize", title="Upres to 1025²", resolution_x=1025, resolution_y=1025)
    g.link(bl, "cop", r2, "cop")
    dt = B("PCG_COPWrangle", title="Buttresses and rock roughness", code=(
        "# buttresses and hollows (60-150 m), rock roughness (10-50 m), on the land only; and a copy of the height\n"
        "# for the mask blend below\n"
        "n1 = noise(set(@u * 34, @v * 34, 1.1)) - 0.5\n"
        "n2 = noise(set(@u * 90, @v * 90, 2.3)) - 0.5\n"
        "n3 = noise(set(@u * 220, @v * 220, 4.7)) - 0.5\n"
        "@C = @C + (0.006 * n1 + 0.0025 * n2 + 0.001 * n3) * @land\n"
        "@pre = @C"))
    g.link(r2, "cop", dt, "cop")
    ef = B("PCG_COPErosion", title="Gully pattern (erosion filter)", strength=2048.0, world_size=4100.0,
           amplitude=10.0, wavelength=36.0, octaves=5, steepness=3.0, mask_layer="")
    g.link(dt, "cop", ef, "cop")
    em = B("PCG_COPWrangle", title="Gullies on the land only", code="@C = lerp(@pre, @C, @land)")
    g.link(ef, "cop", em, "cop")
    hy = B("PCG_COPHeightfieldErode", title="Erode 1025² (gullies, scree, sediment)", strength=2048.0,
           world_size=4100.0, iterations=160, rain=0.03, capacity=4.0, talus_angle=40.0, thermal_rate=0.1,
           bed_change_limit=0.03)
    g.link(em, "cop", hy, "cop")
    fa = B("PCG_COPFlowAccumulation", title="Rivers (draining to the sea)", method="rho8", river_area=0.0015,
           river_softness=0.4, flow_layer="catchment", base_layer="sea", rand_seed=21)
    g.link(hy, "cop", fa, "cop")
    rb = C("PCG_COPBlur", title="Rivers: from a 1-cell line to a channel", sigma_pixels=1.4, border="clamp",
           layers="river")
    g.link(fa, "cop", rb, "cop")
    cv = C("PCG_COPWrangle", title="Cut the river beds", code=(
        "# river beds: cut 1.5-5 m into the valley floor, deeper and wider for larger catchments, with soft banks\n"
        "big = smoothstep(0.003, 0.05, @catchment)\n"
        "bed = smoothstep(0.05, 0.3, @river + 0.12 * big * @river / (@river + 0.02))\n"
        "@bed = bed * @land\n"
        "@C = @C - (1.5 + 3.5 * big) / 2048 * @bed"))
    g.link(rb, "cop", cv, "cop")
    nm = C("PCG_COPHeightToNormal", title="Normal (slopes, aligning rocks)", strength=2048.0,
           world_size=4100.0, out_layer="N")
    g.link(cv, "cop", nm, "cop")
    bio = C("PCG_COPWrangle", title="Ecology: six weight layers + scatter densities", code=(
        'hm = @C * 2048\n'
        'tn = normalize(set(@N.x, @N.z, -@N.y))\n'
        '@tn = tn\n'
        'steep = 1 - @N.z\n'
        'wet = clamp(@flow, 0, 1) * @land\n'
        'hn = clamp(hm / (@C.max() * 2048), 0, 1)\n'
        '@hn = hn\n'
        '# water: the sea (below 0 m), and the trunk rivers (largest catchments) inside their beds\n'
        'sea = 1 - smoothstep(-0.6, 0.3, hm)\n'
        'big = smoothstep(0.003, 0.05, @catchment)\n'
        'riv = @bed * smoothstep(0.25, 0.7, big)\n'
        'water = clamp(max(sea, riv), 0, 1)\n'
        '# cliffs: above ~45 degrees everywhere; from ~35 degrees on in patches (bare outcrops in the grass)\n'
        'cliff = max(smoothstep(0.27, 0.37, steep), smoothstep(0.17, 0.25, steep)'
        ' * smoothstep(0.5, 0.65, noise(set(@u * 40, @v * 40, 2.2)) + 0.2 * (noise(set(@u * 140, @v * 140, 5.5)) - 0.5)))\n'
        '# sand: the beach (0-4 m above the sea, gentle), dry river beds and gravel bars\n'
        'beach = (1 - smoothstep(2.5, 6.0, hm + 2.0 * (noise(set(@u * 25, @v * 25, 7.1)) - 0.5))) * (1 - smoothstep(0.08, 0.2, steep))\n'
        'sand = clamp(max(beach, @bed * (1 - smoothstep(0.25, 0.7, big))), 0, 1)\n'
        '# scree: what slumped (debris), below the cliffs\n'
        'scree = smoothstep(0.0006, 0.003, @debris) * (1 - cliff)\n'
        '# woodland: valleys and lower slopes where water collects, in clumps; not on cliffs, sand or scree\n'
        'soil = (1 - cliff) * (1 - sand) * (1 - scree) * (1 - smoothstep(0.2, 0.3, steep))\n'
        'clump = smoothstep(0.5, 0.62, 0.55 * noise(set(@u * 6, @v * 6, 1.7)) + 0.25 * noise(set(@u * 26, @v * 26, 4.2)) + 0.45 * wet - 0.35 * hn + 0.06)\n'
        'wood = clamp(soil * clump, 0, 1)\n'
        '# layer the six weights: each takes its share of what the ones above left\n'
        'rem = 1 - water\n'
        '@Water = water\n'
        '@Sand = rem * sand\n'
        'rem = rem * (1 - sand)\n'
        '@Rock = rem * cliff\n'
        'rem = rem * (1 - cliff)\n'
        '@Sediment = rem * scree\n'
        'rem = rem * (1 - scree)\n'
        '@ForestFloor = rem * wood\n'
        '@Grass = rem * (1 - wood)\n'
        '@d_tree = @ForestFloor + 0.03 * @Grass * (1 - smoothstep(0.5, 0.7, hn))\n'
        'edge_ = wood * (1 - wood) * 4\n'
        '@d_bush = @Grass * (0.3 * edge_ + 0.3 * wet + 0.35 * smoothstep(0.55, 0.8, hn)) * smoothstep(0.35, 0.65, noise(set(@u * 23, @v * 23, 5.3)))\n'
        '@d_rock = 0.5 * @Sediment + 0.25 * @Rock * (1 - 0.6 * @Rock) + 0.1 * @Sand * @bed\n'
        '@wet = wet\n'
        '# colour (display values, made linear at the end)\n'
        'rv = noise(set(@u * 9, @v * 9, 2.6))\n'
        'bedd = 0.5 + 0.5 * sin(hm / 7 + 9 * noise(set(@u * 3, @v * 3, 6.1)))\n'
        'rock = lerp(set(0.30, 0.29, 0.26), set(0.52, 0.51, 0.48), rv) * (0.82 + 0.26 * bedd)\n'
        'rock = lerp(rock, rock * set(1.06, 0.98, 0.88), smoothstep(0.55, 0.8, noise(set(@u * 4, hm / 40, 3.3))))\n'
        'rock = rock * (1 - 0.45 * smoothstep(0.3, 0.9, wet))\n'
        'screec = set(0.58, 0.55, 0.50) * (0.88 + 0.24 * noise(set(@u * 80, @v * 80, 3.9)))\n'
        'sandc = lerp(set(0.66, 0.60, 0.47), set(0.50, 0.46, 0.38), @bed) * (0.92 + 0.16 * noise(set(@u * 50, @v * 50, 8.1)))\n'
        'sandc = lerp(sandc, sandc * 0.72, 1 - smoothstep(0.0, 1.2, hm))\n'
        '# grass: lush in the valleys, dry yellow-green on sunny ridges, olive heath on the high ground\n'
        'dry = clamp(0.75 * smoothstep(0.35, 0.75, noise(set(@u * 7, @v * 7, 4.4))) + 0.5 * steep * 4 - 0.9 * wet, 0, 1)\n'
        'grass = lerp(set(0.22, 0.30, 0.13), set(0.42, 0.42, 0.22), dry)\n'
        'grass = lerp(grass, set(0.40, 0.40, 0.24), smoothstep(0.55, 0.85, hn + 0.15 * (noise(set(@u * 12, @v * 12, 9.9)) - 0.5)))\n'
        'grass = grass * (0.86 + 0.28 * noise(set(@u * 45, @v * 45, 7.7)))\n'
        '# darker in the gullies (damp soil, shade-loving plants): the drainage pattern reads in the colour too\n'
        'grass = grass * (1 - 0.28 * smoothstep(0.35, 0.9, wet))\n'
        'woodc = set(0.15, 0.21, 0.09) * (0.85 + 0.3 * noise(set(@u * 60, @v * 60, 1.3)))\n'
        'deep = smoothstep(0.0, -14.0, hm)\n'
        'waterc = lerp(set(0.16, 0.36, 0.38), set(0.03, 0.10, 0.17), deep)\n'
        'waterc = lerp(waterc, set(0.10, 0.19, 0.21), riv)\n'
        'c = grass * @Grass + woodc * @ForestFloor + screec * @Sediment + rock * @Rock + sandc * @Sand + waterc * @Water\n'
        '@albedo = (c * (0.95 + 0.1 * noise(set(@u * 150, @v * 150, 2.2)))) ** 2.2\n'
        '@terrain_orm = set(1 + 0 * hn, lerp(0.92 - 0.2 * wet * @Rock, 0.05, @Water), 0 * hn)\n'
        '@sea_orm = set(1 + 0 * hn, 0.05 + 0 * hn, 0 * hn)\n'))
    g.link(nm, "cop", bio, "cop")

    # ③ Distribution
    def scatter(col, title, count, dens, seed):
        n = col("PCG_COPLayerToPoints", title=title, mode="scatter", count=count,
                density_layer=dens, height_layer="C", height_scale=2048.0,
                attribs="hn tn wet " + dens, plane="xz", world_size=4100.0, rand_seed=seed)
        g.link(bio, "cop", n, "cop")
        return n
    trees = scatter(D, "Trees: scatter by woodland density", 30000, "d_tree", 1)
    tw = D("PCG_Wrangle", title="Trees: asset / orientation / size", code=(
        "r = rand(@ptnum + 0.5)\n"
        'pine = np.array(["Tree_Pine_A", "Tree_Pine_B", "Tree_Pine_C"])\n'
        'broad = np.array(["Tree_Broadleaf_A", "Tree_Broadleaf_B"])\n'
        "# pines up high, broadleaf down low, a mixed band in between (by altitude + random)\n"
        "high = @hn.x + 0.12 * (rand(@ptnum + 7.1) - 0.5) > 0.42\n"
        "s@name = where(high, pine[(r * 3).astype(int)], broad[(r * 2).astype(int)])\n"
        "a = rand(@ptnum + 1.3) * 2 * PI\n"
        "@N = set(sin(a), 0 * a, cos(a))\n"
        "@up = set(0, 1, 0)\n"
        "# big trees deep in the forest and where water collects, smaller at the edges and up toward the tree line\n"
        "d = clamp(@d_tree.x, 0, 1)\n"
        "@pscale = (0.75 + 0.5 * d + 0.4 * @wet.x) * (1 - 0.4 * smoothstep(0.55, 0.8, @hn.x))"
        " * (0.7 + 0.6 * rand(@ptnum + 2.9))"))
    g.link(trees, "geo", tw, "geo")
    bush = scatter(D, "Bushes: woodland edges, wet ground, heath", 14000, "d_bush", 2)
    bw = D("PCG_Wrangle", title="Bushes", code=(
        'names = np.array(["Bush_A", "Bush_B"])\n'
        "s@name = names[(rand(@ptnum + 0.3) * 2).astype(int)]\n"
        "a = rand(@ptnum + 1.7) * 2 * PI\n"
        "@N = set(sin(a), 0 * a, cos(a))\n"
        "@up = normalize(lerp(set(0, 1, 0), @tn, 0.4))\n"
        "@pscale = 0.9 + 1.2 * rand(@ptnum + 4.1)"))
    g.link(bush, "geo", bw, "geo")
    rocks = scatter(E, "Rocks: scree, cliff feet, river beds", 4000, "d_rock", 3)
    rw = E("PCG_Wrangle", title="Rocks (using the 4 from the rock pipeline)", code=(
        "s@name = sprintf(\"SM_Rock_%02d\", (rand(@ptnum + 0.9) * 4).astype(int))\n"
        "# follow the slope (up tilted 70% towards the terrain normal), sunk in a bit\n"
        "@up = normalize(lerp(set(0, 1, 0), @tn, 0.7))\n"
        "a = rand(@ptnum + 3.3) * 2 * PI\n"
        "@N = normalize(cross(@up, set(sin(a), 0 * a, cos(a))))\n"
        "@pscale = 0.8 + 3.0 * pow(rand(@ptnum + 5.5), 2)\n"
        "@P.y -= 0.25 * @pscale"))
    g.link(rocks, "geo", rw, "geo")
    allp = E("PCG_Merge", title="All instances")
    g.link(tw, "geo", allp, "geo1")
    g.link(bw, "geo", allp, "geo2")
    g.link(rw, "geo", allp, "geo3")
    corner = E("PCG_Transform", title="Move origin to the north-west corner", tx=2048.0, tz=2048.0)
    g.link(allp, "geo", corner, "geo")
    # Scatter works by pixel area (each sample covers 4 m square), so the outermost ring scatters half a cell beyond the terrain border -
    # those points land at places like x = −2 / 4098, and tiling then produces extra empty tiles like x−1, y4
    inb = E("PCG_Blast", title="Remove points in the half cell outside the border", cls="point",
            group="(@P.x < 0) | (@P.x >= 4096) | (@P.z < 0) | (@P.z >= 4096)")
    g.link(corner, "geo", inb, "geo")
    ei = E("PCG_ExportInstances", title="Instance table: 1024 m tiles",
           filename="pcg/world/instances/Instances_x{tx}_y{ty}", format="csv",
           asset_attribute="name", tile_size=1024.0)
    g.link(inb, "geo", ei, "points")

    # ④ Write files
    wh = F("PCG_COPWriteFile", title="Height: 16-bit, 4×4 tiles with shared edges",
           filename="pcg/world/height/Height_x{tx}_y{ty}", channels="C",
           format="png", bit_depth="16", remap="normalize", tiles_x=4, tiles_y=4,
           shared_edge=True, value_scale=2048.0)
    g.link(bio, "cop", wh, "cop")
    wr = F("PCG_COPWriteFile", title="Height: full-map r16", filename="pcg/world/height/Height_full",
           channels="C", format="raw", bit_depth="16", remap="normalize",
           value_scale=2048.0)
    g.link(bio, "cop", wr, "cop")
    for layer in ("Grass", "ForestFloor", "Sediment", "Rock", "Sand", "Water"):
        w = F("PCG_COPWriteFile", title=f"Weight: {layer}",
              filename=f"pcg/world/weight/{layer}_x{{tx}}_y{{ty}}", channels=layer,
              format="png", bit_depth="8", tiles_x=4, tiles_y=4, shared_edge=True)
        g.link(bio, "cop", w, "cop")

    # Preview
    lit = G("PCG_COPLight", title="Minimap (with shadows)", normal_layer="N",
            albedo_layer="albedo", height_layer="C", azimuth=135.0, elevation=35.0,
            shadows=True, strength=2048.0, world_size=4100.0, ambient=0.35,
            out_layer="lit")
    g.link(bio, "cop", lit, "cop")
    grid = G("PCG_COPWrangle", title="Draw tile lines", code=(
        "e = min(min(abs(frac(@u * 4 + 0.5) - 0.5), abs(frac(@v * 4 + 0.5) - 0.5)) * 1025, 1.5) / 1.5\n"
        "@lit = lerp(set(1, 0.85, 0.2), @lit, e)"))
    g.link(lit, "cop", grid, "cop")
    wm = G("PCG_COPWriteFile", title="Minimap PNG", filename="pcg/world/Overview",
           channels="lit", format="png", bit_depth="8", encode="srgb")
    g.link(grid, "cop", wm, "cop")
    pv0 = G("PreviewImage", title="Minimap (yellow lines = tiles)", size=[520, 580])
    g.link(wm, "preview", pv0, "images")
    msh0 = G("PCG_COPHeightfieldToMesh", title="Full-map mesh (one point per sample)",
             strength=2048.0, world_size=4100.0, step=1, attribs="Cd=albedo")
    g.link(bio, "cop", msh0, "cop")
    # albedo is linear (for the files); Cd is a display colour (the preview decodes it from sRGB). The material name
    # lets the preview read this mesh's roughness from the image ('@{material}_orm') and leave the proxies alone
    msh1 = G("PCG_Wrangle", title="Cd to display colour; flat sea", code=(
        "@Cd = pow(clamp(@Cd, 0, 1), 1 / 2.2)\n"
        "# the preview shows the sea surface, not the sea floor (the height files keep the floor)\n"
        "uw = @P.y < -0.3\n"
        "@N = where(uw, set(0, 1, 0), @N)\n"
        "@P.y = max(@P.y, -0.3)"))
    g.link(msh0, "geo", msh1, "geo")
    msh = G("PCG_Wrangle", title="Material: terrain", run_over="prim", code='s@material = "terrain"')
    g.link(msh1, "geo", msh, "geo")

    # Preview proxies: stacked-cone pines, clustered broadleaf crowns, bushes and lumpy rocks, so a low camera reads
    # as a landscape; the engine places its real assets from the table. Their colour is a point attribute like the
    # terrain's, darker toward the bottom of the crown (less sky reaches it), and every instance multiplies it by its
    # own tint (Copy to Points, Multiply Attributes = Cd) so a forest is not one flat green
    def tube(col, title, r1, r2, h, y, rgb, cols=6):
        t = col("PCG_Tube", title=title, radius1=r1, radius2=r2, height=h, cols=cols, rows=2, caps=False, center_y=y)
        c = col("PCG_Color", title=title + " colour", attribute_class="point", r=rgb[0], g=rgb[1], b=rgb[2])
        g.link(t, "geo", c, "geo")
        return c

    def merge_n(col, title, nodes):
        m = col("PCG_Merge", title=title)
        for k, n_ in enumerate(nodes):
            g.link(n_, "geo", m, f"geo{k + 1}")
        return m

    def named(col, node, name, top=0.0):
        code = f's@kind = "{name}"'
        n_ = col("PCG_Wrangle", title=f"Proxy: {name}", run_over="prim", code=code)
        g.link(node, "geo", n_, "geo")
        if top <= 0:
            return n_
        sh_ = col("PCG_Wrangle", title=f"{name}: darker low in the crown",
                  code=f"@Cd = @Cd * (0.5 + 0.65 * smoothstep(0.15, 1.0, @P.y / {top}))")
        g.link(n_, "geo", sh_, "geo")
        return sh_
    trunk = (0.20, 0.15, 0.11)
    pine = named(G, merge_n(G, "Pine proxy", [
        tube(G, "Pine trunk", 0.3, 0.2, 3.0, 1.5, trunk, 5),
        tube(G, "Pine tier 1", 2.7, 1.0, 3.4, 3.6, (0.11, 0.19, 0.10), 7),
        tube(G, "Pine tier 2", 2.1, 0.7, 3.4, 6.2, (0.12, 0.21, 0.11), 7),
        tube(G, "Pine tier 3", 1.5, 0.3, 3.4, 8.8, (0.13, 0.23, 0.12), 6),
        tube(G, "Pine tip", 0.8, 0.0, 3.0, 11.4, (0.14, 0.25, 0.13), 5)]), "pine", 13.0)
    blob = G("PCG_Sphere", title="Broadleaf cluster", radius=1.0, cols=6, rows=4)
    blj = G("PCG_PointJitter", title="Lumpy cluster", scale=0.35, rand_seed=3)
    g.link(blob, "geo", blj, "geo")
    bpts = G("PCG_Add", title="Crown cluster centres",
             points="0 6.6 0\n1.7 5.6 0.5\n-1.5 5.9 -0.7\n0.3 5.4 1.7\n-0.5 7.6 -1.0\n0.6 5.2 -1.8")
    bps = G("PCG_Wrangle", title="Cluster sizes", code="@pscale = 1.7 + 0.7 * rand(@ptnum * 3.1)")
    g.link(bpts, "geo", bps, "geo")
    bcr = G("PCG_CopyToPoints", title="Broadleaf crown")
    g.link(blj, "geo", bcr, "source")
    g.link(bps, "geo", bcr, "points")
    bcc = G("PCG_Color", title="Broadleaf green", attribute_class="point", r=0.20, g=0.29, b=0.11)
    g.link(bcr, "geo", bcc, "geo")
    broad = named(G, merge_n(G, "Broadleaf proxy", [tube(G, "Broadleaf trunk", 0.35, 0.22, 4.5, 2.25, trunk, 5),
                                                    bcc]), "broad", 9.5)
    bsh = G("PCG_Sphere", title="Bush", radius=1.0, cols=6, rows=4)
    bsj = G("PCG_PointJitter", title="Bush lumps", scale=0.35, rand_seed=5)
    g.link(bsh, "geo", bsj, "geo")
    bst = G("PCG_Transform", title="Bush on the ground", ty=0.55, sy=0.65)
    g.link(bsj, "geo", bst, "geo")
    bsc = G("PCG_Color", title="Bush green", attribute_class="point", r=0.25, g=0.31, b=0.13)
    g.link(bst, "geo", bsc, "geo")
    bushp = named(G, bsc, "bush", 1.3)
    rk = G("PCG_Sphere", title="Rock", radius=1.0, cols=7, rows=5)
    rkj = G("PCG_PointJitter", title="Rock: angular", scale=0.45, rand_seed=8)
    g.link(rk, "geo", rkj, "geo")
    rkt = G("PCG_Transform", title="Rock: squat", sy=0.62, sx=1.25)
    g.link(rkj, "geo", rkt, "geo")
    rkc = G("PCG_Color", title="Rock grey", attribute_class="point", r=0.44, g=0.42, b=0.39)
    g.link(rkt, "geo", rkc, "geo")
    rockp = named(G, rkc, "rock")
    plib = merge_n(G, "Proxy library", [pine, broad, bushp, rockp])
    kt = G("PCG_Wrangle", title="Trees → pine / broad", code='s@kind = where(np.char.startswith(@name.astype(str), "Tree_Pine"), "pine", "broad")')
    g.link(tw, "geo", kt, "geo")
    kb = G("PCG_Wrangle", title="Bushes → bush", code='s@kind = "bush"')
    g.link(bw, "geo", kb, "geo")
    kr = G("PCG_Wrangle", title="Rocks → rock", code='s@kind = "rock"')
    g.link(rw, "geo", kr, "geo")
    kall = merge_n(G, "Proxy points", [kt, kb, kr])
    tint = G("PCG_Wrangle", title="Per-instance tint", code=(
        "# brightness 0.75..1.2, and a drift toward yellow-green or blue-green\n"
        "b = 0.75 + 0.45 * rand(@ptnum + 11.1)\n"
        "h = rand(@ptnum + 12.7) - 0.5\n"
        "@Cd = set(b * (1 + 0.5 * h), b, b * (1 - 0.4 * h))"))
    g.link(kall, "geo", tint, "geo")
    ct = G("PCG_CopyToPoints", title="Place the proxies", piece_attribute="kind", target_point_attributes="Cd",
           multiply_attributes="Cd")
    g.link(plib, "geo", ct, "source")
    g.link(tint, "geo", ct, "points")
    # the sea beyond the map: one quad to the horizon, with its own roughness layer ('@sea_orm')
    sq = G("PCG_Grid", title="Sea to the horizon", size_x=60000.0, size_z=60000.0, cols=2, rows=2)
    sqt = G("PCG_Transform", title="Just under the map's sea level", ty=-0.35)
    g.link(sq, "geo", sqt, "geo")
    sqc = G("PCG_Color", title="Deep water", attribute_class="point", r=0.03, g=0.10, b=0.17)
    g.link(sqt, "geo", sqc, "geo")
    sqm = G("PCG_Wrangle", title="Material: sea", run_over="prim", code='s@material = "sea"')
    g.link(sqc, "geo", sqm, "geo")
    mg = G("PCG_Merge", title="Terrain + instance proxies + sea")
    g.link(msh, "geo", mg, "geo1")
    g.link(ct, "geo", mg, "geo2")
    g.link(sqm, "geo", mg, "geo3")
    cam = G("PCG_Camera", title="Camera: from the air, south-west of the island", projection="perspective",
            mode="look_at", resolution_x=1600, resolution_y=900, fov=30.0, eye_x=-2300.0, eye_y=1250.0,
            eye_z=2600.0, target_x=0.0, target_y=40.0, target_z=120.0)
    pr = G("PCG_PreviewImage", width=1600, height=900, elevation=38.0, azimuth=25.0, shading="color",
           look="outdoor", textures="orm = @{material}_orm", sun_elevation=32.0, sun_azimuth=235.0, haze=1.2,
           ground_plane=False, clouds=0.3, cloud_seed=3)
    g.link(mg, "geo", pr, "geo")
    g.link(bio, "cop", pr, "textures_cop")
    g.link(cam, "cam", pr, "camera")
    pv = G("PreviewImage", title="Whole world", size=[520, 400])
    g.link(pr, "image", pv, "images")
    cam2 = G("PCG_Camera", title="Camera: low, up a valley toward the peaks", projection="perspective",
             mode="look_at", resolution_x=1600, resolution_y=900, fov=45.0, eye_x=CAM2[0], eye_y=CAM2[1],
             eye_z=CAM2[2], target_x=CAM2[3], target_y=CAM2[4], target_z=CAM2[5])
    pr2 = G("PCG_PreviewImage", width=1600, height=900, elevation=10.0, azimuth=0.0, shading="color",
            look="outdoor", textures="orm = @{material}_orm", sun_elevation=24.0, sun_azimuth=250.0, haze=1.5,
            ground_plane=False, clouds=0.45, cloud_seed=3)
    g.link(mg, "geo", pr2, "geo")
    g.link(bio, "cop", pr2, "textures_cop")
    g.link(cam2, "cam", pr2, "camera")
    pv2 = G("PreviewImage", title="In the valley", size=[520, 400])
    g.link(pr2, "image", pv2, "images")
    return g


# ═══════════════════════════════════════════════════ Production 3: modular building assembly
# Studio preview of the kit / block with the material library's textures (run that workflow first; a material whose files
# are missing keeps its Cd)
CITY_TEXTURES = ("basecolor = pcg/materials/T_{material}_BaseColor.png\n"
                 "normal = pcg/materials/T_{material}_Normal_GL.png\n"
                 "orm = pcg/materials/T_{material}_ORM.png")


# Modular city layout (pcg118): 4 m cells on a 104 m x 88 m grid, two crossing 16 m streets (|x| < 8 and |z| < 8),
# twelve buildings in the four quarters. (building, x0, x1, z0, z1, floors): cell centres in that range belong to the
# building; a building may take several rectangles (L shapes). Outlines stay simple polygons (no courtyards: a hole
# would not survive Divide's shared-edge removal as one polygon).
# test_prod_workflows recomputes the footprint from this table.
CITY_GRID = {"size_x": 104.0, "size_z": 88.0, "cols": 27, "rows": 23}
CITY_STREET = 8.0
CITY_LOTS = [
    (0, -46, -34, -38, -10, 5), (0, -34, -30, -18, -10, 5),        # L along the west edge
    (1, -22, -10, -22, -10, 8),                                     # corner block at the crossing
    (2, -22, -10, -38, -30, 4),
    (3, 10, 18, -38, -10, 14),                                      # tower
    (4, 26, 46, -18, -10, 6),                                       # slab along the main street
    (5, 30, 46, -38, -30, 3),
    (6, -46, -30, 10, 22, 7),
    (7, -22, -10, 10, 18, 3),
    (8, -46, -38, 30, 38, 4),
    (9, -22, -10, 26, 38, 10),
    (10, 10, 30, 10, 18, 5), (10, 10, 18, 22, 30, 5),               # L round the corner
    (11, 38, 46, 10, 38, 9),
]
CITY_MAX_FLOORS = max(f for _, _, _, _, _, f in CITY_LOTS)
# Facade variant per building (pcg123): 0 = red brick, 1 = buff brick, 2 = painted render (with paired windows)
CITY_FACADE = {0: 1, 1: 0, 2: 2, 3: 1, 4: 2, 5: 0, 6: 0, 7: 2, 8: 1, 9: 2, 10: 1, 11: 0}
CITY_FACADE_MAT = ("M_Wall", "M_BrickBuff", "M_Stucco")


def city_rules_code():
    """Wrangle (over prims) that writes i@bld and i@floors from CITY_LOTS."""
    lines = ["x = @P.x", "z = @P.z", "b = 0 * x - 1", "f = 0 * x"]
    for b, x0, x1, z0, z1, fl in CITY_LOTS:
        cond = f"(x >= {x0}) & (x <= {x1}) & (z >= {z0}) & (z <= {z1})"
        lines.append(f"b = where({cond}, {b}, b)")
        lines.append(f"f = where({cond}, {fl}, f)")
    lines += ["i@bld = where(b < 0, -1, b)", "i@floors = where(b < 0, 0, f)"]
    lines.append("fa = 0 * x")
    for b, v in CITY_FACADE.items():
        if v:
            lines.append(f"fa = where(b == {b}, {v}, fa)")
    lines.append("i@facade = fa")
    return "\n".join(lines)


def modular_city():
    g = Graph()
    W = 340
    K1, K2, K3, K4 = (Col(g, x, width=W) for x in (0, 380, 760, 1140))
    A, B, C, D = (Col(g, x, width=W) for x in (1560, 1940, 2320, 2700))
    E = Col(g, 3080, width=520)
    K1.note((
        "Modular buildings: first build a kit (each piece 4 m wide, one storey 3.5 m tall), then place the kit by rules onto "
        "every building's facades - the deliverable is **the kit meshes + an instance table**, not a lump of merged buildings.\n\n"
        "Kit (the four left columns): Wall_Plain / Wall_Window / Wall_WindowPair / Wall_Door / Wall_Shopfront / "
        "Wall_Balcony / Corner_Pillar / Roof_Cornice / Roof_Flat / Roof_Unit / Roof_Tank. Convention: pivot at the midpoint of the bottom edge "
        "(rooftop plant: on the roof surface), outer facade facing +Z, wall thickness towards −Z; each piece's primitives have a material "
        "attribute (M_Wall / M_Trim / M_Glass / M_Door / M_Metal / M_Roof / M_RoofFlat / M_Sign), exported as glTF material slots; "
        "the facade column of the table swaps M_Wall for M_BrickBuff or M_Stucco per building (a material override); UVs are a world-scale "
        "box projection (1 UV = 1 m), the same density as the material library (pcg_prod_material_library, one image = 1 m); "
        "all seven slots point to the material library's images by relative path in the glb - "
        "run the material library first and the kit opens textured.\n\n"
        "Assembly (right side):\n"
        "① On a 4 m grid, rules mark out the footprints of 12 buildings in the four quarters of two crossing 16 m streets (L shapes, "
        "slabs, a 14-storey tower, small houses), merged into outlines, each with its own number of floors.\n"
        "② The outlines are extruded floor by floor, each side face is a 4 m × 3.5 m slot; slot centre → point (with outward normal).\n"
        "③ Rules: street-facing ground floor is shopfronts, other ground floors occasionally get doors; upper floors take a random number per \"column\" (the same column "
        "lines up vertically), even floors on the street side get random balconies, a few are solid walls; a ring of cornice above the top floor, roofs tiled per cell; "
        "pillars stand at the outer wall corners (sharp edges of the extruded mass).\n"
        "④ Instance table (CSV, with bld / floor / facade columns) + one glb per kit piece (SM_Kit_*.glb).\n"
        "⑤ Preview (right column): Copy to Points by name places the kit back; the streets get asphalt, sidewalks, road "
        "paint, lamps, trees and parked cars; low-detail context blocks (extruded footprints with a whole-bay facade "
        "texture) fill the distance; two Camera nodes give a low aerial and an eye-level shot in the Outdoor look "
        "(sun, sky, haze)."),
        h=780, title="Modular building assembly (read me first)", w=W)

    def box(col, title, sx, sy, sz, cx, cy, cz, rx=0.0):
        return col("PCG_Box", title=title, size_x=sx, size_y=sy, size_z=sz,
                   cx=cx, cy=cy, cz=cz, rx=rx)

    def cut(col, title, a, b):
        n = col("PCG_Boolean", title=title, operation="subtract")
        g.link(a, "geo", n, "a")
        g.link(b, "geo", n, "b")
        return n

    def tag(col, node, mat):
        n = col("PCG_Wrangle", title=f"→ {mat}", run_over="prim",
                code=f's@material = "{mat}"')
        g.link(node, "geo", n, "geo")
        return n

    def merge_all(col, title, nodes):
        """Merge any number of inputs (Merge takes 6: chain them)."""
        cur, rest = None, list(nodes)
        if len(rest) == 1:
            return rest[0]
        while rest:
            m = col("PCG_Merge", title=title)
            k = 1
            if cur is not None:
                g.link(cur, "geo", m, "geo1")
                k = 2
            take, rest = rest[:7 - k], rest[7 - k:]
            for i, p_ in enumerate(take):
                g.link(p_, "geo", m, f"geo{k + i}")
            cur = m
        return cur

    def boxes(col, title, mat, specs):
        """Several boxes (sx, sy, sz, cx, cy, cz[, rx]) as one part with one material."""
        bs = [box(col, f"{title} {i + 1}" if len(specs) > 1 else title, *sp) for i, sp in enumerate(specs)]
        return tag(col, merge_all(col, title, bs), mat)

    def repeat(col, title, mat, size, pts):
        """One small box copied onto a row of points (balusters, dentils)."""
        b_ = box(col, title + ": one", *size, 0.0, 0.0, 0.0)
        ad = col("PCG_Add", title=title + ": positions", points="\n".join(f"{x:.3f} {y:.3f} {z:.3f}" for x, y, z in pts))
        cp = col("PCG_CopyToPoints", title=title)
        g.link(b_, "geo", cp, "source")
        g.link(ad, "geo", cp, "points")
        return tag(col, cp, mat)

    def piece(col, name, parts):
        m = merge_all(col, name, parts)
        n = col("PCG_Wrangle", title=f"Name {name}", run_over="prim",
                code=f's@name = "{name}"')
        g.link(m, "geo", n, "geo")
        return n

    # ── Shared parts. Convention: the facade face is z = 0, the wall goes back to z = -0.3; glass and door leaves sit
    #    in the reveal at z = -0.2, so the openings have 20 cm deep reveals
    wall = box(K1, "Wall panel 4 × 3.5 × 0.3", 4.0, 3.5, 0.3, 0.0, 1.75, -0.15)
    band = tag(K1, box(K1, "Floor band", 4.0, 0.22, 0.1, 0.0, 3.39, 0.05), "M_Trim")
    plain = piece(K1, "Wall_Plain", [tag(K1, wall, "M_Wall"), band])
    # Window: 1.6 × 1.9 opening, stone surround, lintel with keystone, sill; a painted frame with a mullion and transom
    wh = box(K1, "Window opening", 1.6, 1.9, 1.0, 0.0, 1.95, -0.15)
    w1 = tag(K1, cut(K1, "Wall − window opening", wall, wh), "M_Wall")
    fr = cut(K2, "Window surround", box(K2, "Window surround outer", 1.8, 2.1, 0.16, 0.0, 1.95, -0.08),
             box(K2, "Window surround inner", 1.6, 1.9, 1.0, 0.0, 1.95, 0.0))
    frt = tag(K2, fr, "M_Trim")
    gl = tag(K2, box(K2, "Glass", 1.6, 1.9, 0.02, 0.0, 1.95, -0.2), "M_Glass")
    sill = tag(K2, box(K2, "Sill", 1.9, 0.08, 0.24, 0.0, 0.97, 0.06), "M_Trim")
    lint = boxes(K2, "Lintel + keystone", "M_Trim", [(2.0, 0.2, 0.08, 0.0, 3.1, 0.04),
                                                      (0.24, 0.26, 0.1, 0.0, 3.08, 0.05)])
    wfr = boxes(K2, "Window frame, mullion, transom (painted)", "M_Trim", [
        (1.6, 0.07, 0.08, 0.0, 2.865, -0.19), (1.6, 0.07, 0.08, 0.0, 1.035, -0.19),
        (0.07, 1.9, 0.08, -0.765, 1.95, -0.19), (0.07, 1.9, 0.08, 0.765, 1.95, -0.19),
        (0.06, 1.76, 0.07, 0.0, 1.95, -0.19), (1.46, 0.06, 0.07, 0.0, 2.35, -0.19)])
    window = piece(K2, "Wall_Window", [w1, band, frt, gl, sill, lint, wfr])
    # Door / balcony door (same 1.4 × 2.6 opening)
    dh = box(K2, "Door opening", 1.4, 2.6, 1.0, 0.0, 1.3, -0.15)
    w2 = tag(K2, cut(K2, "Wall − door opening", wall, dh), "M_Wall")
    leaf = tag(K3, box(K3, "Door leaf", 1.36, 2.56, 0.06, 0.0, 1.28, -0.22), "M_Door")
    panels = boxes(K3, "Door panels (raised 3 cm)", "M_Door", [
        (0.5, 0.9, 0.03, -0.3, 0.75, -0.175), (0.5, 0.9, 0.03, 0.3, 0.75, -0.175),
        (0.5, 1.1, 0.03, -0.3, 1.9, -0.175), (0.5, 1.1, 0.03, 0.3, 1.9, -0.175)])
    casing = boxes(K3, "Door casing", "M_Trim", [
        (0.14, 2.67, 0.08, -0.77, 1.335, 0.04), (0.14, 2.67, 0.08, 0.77, 1.335, 0.04),
        (1.68, 0.14, 0.08, 0.0, 2.67, 0.04)])
    # canopy on two diagonal brackets (wall at y 2.3 → canopy underside 0.65 m out)
    canopy = boxes(K3, "Canopy + brackets", "M_Metal", [
        (2.0, 0.12, 0.8, 0.0, 2.9, 0.4), (0.06, 0.06, 0.82, -0.85, 2.57, 0.32, 40.0),
        (0.06, 0.06, 0.82, 0.85, 2.57, 0.32, 40.0), (0.04, 0.04, 0.16, 0.5, 1.1, -0.11)])
    door = piece(K3, "Wall_Door", [w2, band, leaf, panels, casing, canopy])
    bgl = tag(K3, box(K3, "Balcony door glass", 1.4, 2.6, 0.02, 0.0, 1.3, -0.2), "M_Glass")
    bfr = boxes(K3, "Balcony door frame", "M_Metal", [
        (0.07, 2.6, 0.08, -0.665, 1.3, -0.19), (0.07, 2.6, 0.08, 0.665, 1.3, -0.19),
        (1.4, 0.07, 0.08, 0.0, 2.565, -0.19), (0.06, 2.5, 0.07, 0.0, 1.3, -0.19),
        (1.3, 0.08, 0.07, 0.0, 0.9, -0.19)])
    slab = tag(K3, box(K3, "Balcony slab", 3.0, 0.16, 1.2, 0.0, 0.08, 0.6), "M_Trim")
    # railing 1 m above the slab: rails and corner posts, 12 cm balusters on the front and both sides
    rails = boxes(K3, "Railing: rails and posts", "M_Metal", [
        (3.0, 0.05, 0.06, 0.0, 1.14, 1.15), (3.0, 0.04, 0.04, 0.0, 0.22, 1.15),
        (0.06, 0.05, 1.12, -1.47, 1.14, 0.6), (0.06, 0.05, 1.12, 1.47, 1.14, 0.6),
        (0.04, 0.04, 1.12, -1.47, 0.22, 0.6), (0.04, 0.04, 1.12, 1.47, 0.22, 0.6),
        (0.06, 1.0, 0.06, -1.47, 0.66, 1.15), (0.06, 1.0, 0.06, 1.47, 0.66, 1.15)])
    bal = repeat(K3, "Balusters", "M_Metal", (0.02, 0.9, 0.02),
                 [(-1.38 + 0.12 * i, 0.69, 1.15) for i in range(24)]
                 + [(sx_, 0.69, 0.12 * i + 0.06) for sx_ in (-1.47, 1.47) for i in range(9)])
    balcony = piece(K3, "Wall_Balcony", [w2, band, bgl, bfr, slab, rails, bal])
    # Shopfront: 3.4 × 2.8 opening, stall riser, metal frame in three bays with a transom, sloping awning, sign
    sh = box(K4, "Shopfront opening", 3.4, 2.8, 1.0, 0.0, 1.5, -0.15)
    w3 = tag(K4, cut(K4, "Wall − shopfront opening", wall, sh), "M_Wall")
    sgl = tag(K4, box(K4, "Shop window", 3.4, 2.8, 0.02, 0.0, 1.5, -0.2), "M_Glass")
    riser = tag(K4, box(K4, "Stall riser", 3.4, 0.5, 0.2, 0.0, 0.35, -0.15), "M_Trim")
    sfr = boxes(K4, "Shopfront frame, mullions, transom", "M_Metal", [
        (0.08, 2.8, 0.1, -1.66, 1.5, -0.2), (0.08, 2.8, 0.1, 1.66, 1.5, -0.2),
        (3.4, 0.08, 0.1, 0.0, 2.86, -0.2), (3.4, 0.06, 0.1, 0.0, 0.63, -0.2),
        (0.06, 2.2, 0.08, -0.567, 1.73, -0.2), (0.06, 2.2, 0.08, 0.567, 1.73, -0.2),
        (3.24, 0.06, 0.08, 0.0, 2.3, -0.2)])
    awn = tag(K4, box(K4, "Awning (20° slope)", 3.4, 0.03, 0.9, 0.0, 2.72, 0.42, 20.0), "M_Metal")
    sign = tag(K4, box(K4, "Sign", 3.2, 0.35, 0.12, 0.0, 3.1, 0.06), "M_Sign")
    shop = piece(K4, "Wall_Shopfront", [w3, band, sgl, riser, sfr, awn, sign])
    # Pillar with a plinth and a capital; cornice as fascia + bed moulding + dentils + bevelled crown; roof
    pil = piece(K4, "Corner_Pillar", [boxes(K4, "Corner pillar, plinth, capital", "M_Trim", [
        (0.6, 3.5, 0.6, 0.0, 1.75, 0.0), (0.7, 0.45, 0.7, 0.0, 0.225, 0.0), (0.72, 0.16, 0.72, 0.0, 3.42, 0.0)])])
    crown = K4("PCG_PolyBevel", title="Cornice crown bevel", distance=0.03)
    g.link(box(K4, "Cornice crown", 4.0, 0.12, 0.5, 0.0, 0.44, 0.03), "geo", crown, "geo")
    cor_b = boxes(K4, "Cornice fascia + bed moulding", "M_Trim", [(4.0, 0.3, 0.3, 0.0, 0.15, -0.05),
                                                                  (4.0, 0.08, 0.38, 0.0, 0.34, -0.01)])
    dent = repeat(K4, "Dentils", "M_Trim", (0.08, 0.08, 0.08), [(-1.92 + 0.16 * i, 0.26, 0.14) for i in range(25)])
    cornice = piece(K4, "Roof_Cornice", [tag(K4, crown, "M_Trim"), cor_b, dent])
    roof = piece(K4, "Roof_Flat", [tag(K4, box(K4, "Roof panel", 4.0, 0.3, 4.0, 0.0, -0.15, 0.0),
                                       "M_RoofFlat")])
    # pcg123 ── Paired windows (render facades): two 0.9 × 1.9 openings, plain reveals, one long sill, a head band
    wph = merge_all(K1, "Two window openings", [box(K1, "Window opening L", 0.9, 1.9, 1.0, -0.95, 1.95, -0.15),
                                                box(K1, "Window opening R", 0.9, 1.9, 1.0, 0.95, 1.95, -0.15)])
    wp1 = tag(K1, cut(K1, "Wall − two openings", wall, wph), "M_Wall")
    wpg = boxes(K1, "Paired glass", "M_Glass", [(0.9, 1.9, 0.02, -0.95, 1.95, -0.2),
                                                 (0.9, 1.9, 0.02, 0.95, 1.95, -0.2)])
    wpt = boxes(K1, "Paired sill, head band, jambs", "M_Trim", [
        (3.0, 0.08, 0.22, 0.0, 0.96, 0.05), (3.1, 0.14, 0.06, 0.0, 3.0, 0.03),
        (0.09, 1.9, 0.06, -1.445, 1.95, 0.03), (0.09, 1.9, 0.06, 1.445, 1.95, 0.03),
        (0.14, 1.9, 0.06, 0.0, 1.95, 0.03)])
    wpf = boxes(K1, "Paired frames (painted)", "M_Metal", [
        (0.05, 1.9, 0.06, -0.95, 1.95, -0.19), (0.05, 1.9, 0.06, 0.95, 1.95, -0.19),
        (0.9, 0.05, 0.06, -0.95, 2.4, -0.19), (0.9, 0.05, 0.06, 0.95, 2.4, -0.19)])
    pair = piece(K1, "Wall_WindowPair", [wp1, band, wpg, wpt, wpf])
    # Rooftop plant (pivot on the roof surface): a condenser unit with two fans, and a water tank on legs
    unit = piece(K4, "Roof_Unit", [
        boxes(K4, "Unit casing + base frame", "M_Trim", [(1.7, 0.8, 1.0, 0.0, 0.52, 0.0),
                                                       (1.9, 0.12, 1.15, 0.0, 0.06, 0.0)]),
        boxes(K4, "Fan rings + duct", "M_Metal", [(0.62, 0.06, 0.62, -0.42, 0.95, 0.0),
                                                  (0.62, 0.06, 0.62, 0.42, 0.95, 0.0),
                                                  (0.3, 0.3, 0.9, 0.7, 0.3, -0.85)])])
    tk_b = K4("PCG_Tube", title="Tank body", radius1=0.8, radius2=0.8, height=1.8, cols=20, rows=2, caps=True,
              center_y=1.6)
    tk_t = K4("PCG_Tube", title="Tank lid (cone)", radius1=0.85, radius2=0.08, height=0.45, cols=20, rows=2,
              caps=True, center_y=2.72)
    tank = piece(K4, "Roof_Tank", [tag(K4, merge_all(K4, "Tank", [tk_b, tk_t]), "M_Roof"),
                                   boxes(K4, "Tank legs + ring", "M_Metal", [
                                       (0.1, 0.75, 0.1, 0.5, 0.375, 0.5), (0.1, 0.75, 0.1, -0.5, 0.375, 0.5),
                                       (0.1, 0.75, 0.1, 0.5, 0.375, -0.5), (0.1, 0.75, 0.1, -0.5, 0.375, -0.5),
                                       (1.2, 0.08, 1.2, 0.0, 0.72, 0.0)])])
    lib = A("PCG_Merge", title="Kit library (11 pieces)")
    for i, p in enumerate((plain, window, door, balcony, shop, pil)):
        g.link(p, "geo", lib, f"geo{i + 1}")
    lib2 = A("PCG_Merge", title="Kit library (cont.)")
    g.link(lib, "geo", lib2, "geo1")
    g.link(cornice, "geo", lib2, "geo2")
    g.link(roof, "geo", lib2, "geo3")
    g.link(pair, "geo", lib2, "geo4")
    g.link(unit, "geo", lib2, "geo5")
    g.link(tank, "geo", lib2, "geo6")
    uvp = A("PCG_UVProject", title="World-scale box projection (1 UV = 1 m, same density as the material library)",
            mode="box", fit_to_01=False, scale_u=1.0, scale_v=1.0)
    g.link(lib2, "geo", uvp, "geo")
    kc = A("PCG_Wrangle", title="Preview colour (by material)", run_over="prim", code=(
        'm = @material\n'
        '@Cd = where(m == "M_Wall", set(0.66, 0.46, 0.36),'
        ' where(m == "M_Glass", set(0.16, 0.24, 0.32),'
        ' where(m == "M_Door", set(0.30, 0.20, 0.14),'
        ' where(m == "M_Metal", set(0.22, 0.23, 0.25),'
        ' where(m == "M_Roof", set(0.32, 0.32, 0.34),'
        ' where(m == "M_RoofFlat", set(0.36, 0.36, 0.35),'
        ' where(m == "M_Sign", set(0.80, 0.55, 0.20), set(0.86, 0.84, 0.79))))))))'))
    g.link(uvp, "geo", kc, "geo")
    kx = A("PCG_ExportMesh", title="Export: one glb per kit piece (textures point to the material library)",
           filename="pcg/assets/kit/SM_Kit_{name}", format="glb",
           split_attribute="name", file_attribute="name",
           textures=("basecolor = ../../materials/T_{material}_BaseColor.png\n"
                     "normal = ../../materials/T_{material}_Normal_GL.png\n"
                     "orm = ../../materials/T_{material}_ORM.png"),
           texture_materials="*")
    g.link(kc, "geo", kx, "geo")

    # ① Footprints
    grd = B("PCG_Grid", title="4 m grid (104 m × 88 m)", **CITY_GRID)
    rule = B("PCG_Wrangle", title="Rules: which cells belong to which building, how many floors", run_over="prim",
             code=city_rules_code())
    g.link(grd, "geo", rule, "geo")
    cells = B("PCG_Blast", title="Footprint cells", group="@bld < 0", cls="prim")
    g.link(rule, "geo", cells, "geo")
    fp = B("PCG_Divide", title="Merge into outlines", convex_polygons=False,
           remove_shared_edges=True)
    g.link(cells, "geo", fp, "geo")
    # ② Extrude → slots
    ms = B("PCG_PolyExtrude", title="Extrude to the max floor count, one division per floor", divide_into="individual",
           distance=CITY_MAX_FLOORS * 3.5, divisions=CITY_MAX_FLOORS, output_front=False, side_group="slot")
    g.link(fp, "geo", ms, "geo")
    ab = B("PCG_Wrangle", title="Mark what exceeds the floor count", run_over="prim",
           code="i@above = @P.y > @floors * 3.5")
    g.link(ms, "geo", ab, "geo")
    mass = B("PCG_Blast", title="Mass", group="@above == 1", cls="prim")
    g.link(ab, "geo", mass, "geo")
    mn = B("PCG_Normal", title="Primitive normal = outward normal", add_to="prim")
    g.link(mass, "geo", mn, "geo")
    slots = C("PCG_ExtractCentroid", title="One point per slot", run_over="primitives",
              method="average_position", output="points", use_transfer=True,
              transfer_attributes="N floors bld facade")
    g.link(mn, "geo", slots, "geo")
    rl = C("PCG_Wrangle", title="Rules: which piece goes in each slot", code=(
        "fl = floor(@P.y / 3.5)\n"
        "i@floor = fl\n"
        "@P.y = fl * 3.5                      # pivot at the midpoint of the bottom edge\n"
        "t = normalize(cross(set(0, 1, 0), @N))\n"
        "col = floor(dot(@P, t) / 4 + 0.5)    # which column on the facade (aligned vertically)\n"
        "face = floor(dot(@N, set(1.3, 0, 2.9)) * 10 + 0.5)\n"
        "h = rand(col * 7.31 + @bld * 13.7 + face * 0.37)\n"
        "ox = @P.x + 2 * @N.x                 # 2 m in front of the facade\n"
        "oz = @P.z + 2 * @N.z\n"
        f"street = (abs(ox) < {CITY_STREET:g}) | (abs(oz) < {CITY_STREET:g})   # facing one of the two streets\n"
        "win = where(@facade == 2, \"Wall_WindowPair\", \"Wall_Window\")   # render facades: paired windows\n"
        "up_ = where(street & (h > 0.55) & (fl % 2 == 0), \"Wall_Balcony\",\n"
        "            where(h < 0.12, \"Wall_Plain\", win))\n"
        "ground = where(street, \"Wall_Shopfront\", where(h > 0.78, \"Wall_Door\", \"Wall_Plain\"))\n"
        "s@name = where(fl == 0, ground, up_)\n"
        "@up = set(0, 1, 0)"))
    g.link(slots, "geo", rl, "geo")
    top = C("PCG_Blast", title="Top-floor slots", group="@floor != @floors - 1",
            cls="point")
    g.link(rl, "geo", top, "geo")
    cn = C("PCG_Wrangle", title="→ Cornice (above the top floor)", code=(
        's@name = "Roof_Cornice"\n'
        "@P.y += 3.5"))
    g.link(top, "geo", cn, "geo")
    # Corner pillars: points on edges of the extruded mass whose two side normals differ by > 30° (one per floor), without the top ring
    cg = C("PCG_GroupCreate", title="Points on sharp edges", name="corner", cls="point",
           use_edges=True, min_angle=30.0)
    g.link(mass, "geo", cg, "geo")
    pf = C("PCG_AttribPromote", title="Floor count → points", original_name="floors",
           original_class="prim", new_class="point", method="maximum",
           delete_original=False)
    g.link(cg, "geo", pf, "geo")
    cpt = D("PCG_Blast", title="Keep only corner points", group="corner", cls="point",
            keep_selected=True)
    g.link(pf, "geo", cpt, "geo")
    cp2 = D("PCG_Add", title="→ Point cloud (points only)", keep_points=True)
    g.link(cpt, "geo", cp2, "geo")
    cp3 = D("PCG_Blast", title="Remove the top ring", group="@P.y > @floors * 3.5 - 0.1",
            cls="point")
    g.link(cp2, "geo", cp3, "geo")
    cpn = D("PCG_Wrangle", title="→ Corner_Pillar", code=(
        's@name = "Corner_Pillar"\n'
        "@N = set(0, 0, 1)\n"
        "@up = set(0, 1, 0)"))
    g.link(cp3, "geo", cpn, "geo")
    # Roofs: centres of the footprint cells, raised to the floor height
    rc = D("PCG_ExtractCentroid", title="Roof cell centres", run_over="primitives",
           method="average_position", output="points", use_transfer=True,
           transfer_attributes="floors bld facade")
    g.link(cells, "geo", rc, "geo")
    rf = D("PCG_Wrangle", title="→ Roof_Flat", code=(
        's@name = "Roof_Flat"\n'
        "@P.y = @floors * 3.5\n"
        "@N = set(0, 0, 1)\n"
        "@up = set(0, 1, 0)"))
    g.link(rc, "geo", rf, "geo")
    rp = D("PCG_Wrangle", title="→ Rooftop plant (some roof cells)", code=(
        "h = rand(@ptnum * 3.17 + 0.5)\n"
        "big = @floors >= 5\n"
        's@name = where(big & (h < 0.035), "Roof_Tank", where(h < 0.14, "Roof_Unit", ""))\n'
        "# random quarter turns and a little slack inside the 4 m cell\n"
        "a = floor(rand(@ptnum * 1.91) * 4) * 1.5708\n"
        "@N = set(sin(a), 0, cos(a))\n"
        "@P.x += (rand(@ptnum * 2.3) - 0.5) * 1.2\n"
        "@P.z += (rand(@ptnum * 4.1) - 0.5) * 1.2"))
    g.link(rf, "geo", rp, "geo")
    rpk = D("PCG_Blast", title="Keep the cells that got plant", group='@name == ""', cls="point")
    g.link(rp, "geo", rpk, "geo")
    inst = D("PCG_Merge", title="All instance points")
    for i, p in enumerate((rl, cn, cpn, rf, rpk)):
        g.link(p, "geo", inst, f"geo{i + 1}")
    an = D("PCG_Wrangle", title="Asset name = glb file name", code=(
        "# the table's asset column is exactly the kit's exported file name (SM_Kit_Wall_Window.glb without the extension)\n"
        's@asset = sprintf("SM_Kit_%s", @name)'))
    g.link(inst, "geo", an, "geo")
    ex = D("PCG_ExportInstances", title="Instance table", filename="pcg/assets/kit/Block_Instances",
           format="csv", asset_attribute="asset", extra_attributes="bld floor facade")
    g.link(an, "geo", ex, "points")

    # Preview: place the kit back by name; the facade variant swaps the wall material per building (an engine does
    # the same with a material override from the table's facade column)
    cp = E("PCG_CopyToPoints", title="Copy to Points (pick piece by name)",
           piece_attribute="name", target_prim_attributes="facade")
    g.link(kc, "geo", cp, "source")
    g.link(inst, "geo", cp, "points")
    fv = E("PCG_Wrangle", title="Facade variant → wall material", run_over="prim", code=(
        "w = @material == \"M_Wall\"\n"
        f"m = where(w & (@facade == 1), \"{CITY_FACADE_MAT[1]}\",\n"
        f"          where(w & (@facade == 2), \"{CITY_FACADE_MAT[2]}\", @material))\n"
        "s@material = m\n"
        "@Cd = where(m == \"M_BrickBuff\", set(0.70, 0.62, 0.46), where(m == \"M_Stucco\", set(0.84, 0.77, 0.63), @Cd))"))
    g.link(cp, "geo", fv, "geo")
    hx, hz = CITY_GRID["size_x"] / 2, CITY_GRID["size_z"] / 2
    cw = 5.0                    # curb: 5 m from the street axis (10 m carriageway), 3 m sidewalks behind it
    reach = 300.0               # the two streets run on past the block, between the context buildings
    # Streets: asphalt, 15 cm below the sidewalks, continuing out to the horizon
    road = boxes(E, "Carriageways (both streets, to the horizon)",
                 "Ground_Asphalt", [(2 * reach, 0.1, 2 * cw, 0.0, -0.2, 0.0), (2 * cw, 0.1, 2 * reach, 0.0, -0.2, 0.0)])
    gt = E("PCG_UVProject", title="Road UVs (1 UV = 1 m)", mode="box", fit_to_01=False, scale_u=1.0, scale_v=1.0)
    g.link(road, "geo", gt, "geo")
    yard = boxes(E, "Paved quarters (one slab each)", "Ground_Cobble", [
        (hx - cw, 0.15, hz - cw, sx * (cw + hx) / 2, -0.075, sz * (cw + hz) / 2)
        for sx in (-1, 1) for sz in (-1, 1)])
    # 3 m concrete sidewalks along the curbs, 2 cm proud of the paving; outside the block they follow the streets
    walk = boxes(E, "Sidewalk strips along the curbs", "M_Trim", [
        sp for sx in (-1, 1) for sz in (-1, 1) for sp in (
            (reach - cw, 0.17, 3.0, sx * (cw + reach) / 2, -0.065, sz * (cw + 1.5)),
            (3.0, 0.17, reach - cw, sx * (cw + 1.5), -0.065, sz * (cw + reach) / 2))])
    # the ground the context blocks stand on: one concrete slab (their forecourts and the lanes between them)
    slab = boxes(E, "Context ground", "M_Trim", [(640.0, 0.1, 640.0, 0.0, -0.21, 0.0)])
    swk = merge_all(E, "Paving + sidewalks", [yard, walk, slab])
    swu = E("PCG_UVProject", title="Sidewalk UVs (1 UV = 1 m)", mode="box", fit_to_01=False, scale_u=1.0,
            scale_v=1.0)
    g.link(swk, "geo", swu, "geo")
    swc = E("PCG_Color", title="Sidewalk colour (viewport)", attribute_class="prim", r=0.58, g=0.57, b=0.54)
    g.link(swu, "geo", swc, "geo")
    # Road paint: dashed centre lines, zebra crossings on the four arms of the crossing, stop lines
    paint = []
    for d in range(12, int(reach), 9):
        for sgn in (-1, 1):
            paint += [(3.0, 0.02, 0.14, sgn * (d + 1.5), -0.14, 0.0), (0.14, 0.02, 3.0, 0.0, -0.14, sgn * (d + 1.5))]
    for sgn in (-1, 1):
        for k in range(9):
            o = -4.0 + k
            paint += [(2.8, 0.02, 0.5, sgn * 10.4, -0.14, o), (0.5, 0.02, 2.8, o, -0.14, sgn * 10.4)]
        paint += [(0.35, 0.02, cw - 0.3, sgn * 12.3, -0.14, -sgn * (cw - 0.3) / 2),
                  (cw - 0.3, 0.02, 0.35, sgn * (cw - 0.3) / 2, -0.14, sgn * 12.3)]
    rpaint = E("PCG_Add", title="Road paint positions", points="\n".join(
        f"{cx:g} {cy:g} {cz:g}" for _, _, _, cx, cy, cz in paint))
    rpw = E("PCG_Wrangle", title="Road paint sizes", code=(
        "# one table row per stripe: (size x, size z), in the order of the points\n"
        "sx = np.array([" + ", ".join(f"{a:g}" for a, _, _, _, _, _ in paint) + "])\n"
        "sz = np.array([" + ", ".join(f"{c:g}" for _, _, c, _, _, _ in paint) + "])\n"
        "v@scale = set(sx[@ptnum], 0.02, sz[@ptnum])"))
    g.link(rpaint, "geo", rpw, "geo")
    rpb = E("PCG_Box", title="Unit stripe", size_x=1.0, size_y=1.0, size_z=1.0)
    rpc = E("PCG_CopyToPoints", title="Road paint")
    g.link(rpb, "geo", rpc, "source")
    g.link(rpw, "geo", rpc, "points")
    rpm = E("PCG_Wrangle", title="Paint: white, no texture", run_over="prim",
            code='s@material = "Road_Paint"\n@Cd = set(0.86, 0.86, 0.82)')
    g.link(rpc, "geo", rpm, "geo")
    # Street furniture on the sidewalks, 1.2 m from the curb: lamps and trees alternating every 6 m
    lamp = merge_all(E, "Street lamp", [
        box(E, "Lamp pole", 0.14, 5.0, 0.14, 0.0, 2.5, 0.0), box(E, "Lamp base", 0.3, 0.5, 0.3, 0.0, 0.25, 0.0),
        box(E, "Lamp arm", 0.08, 0.08, 1.3, 0.0, 4.92, 0.62), box(E, "Lamp head", 0.32, 0.14, 0.6, 0.0, 4.85, 1.2)])
    lampn = E("PCG_Wrangle", title="Lamp: metal, name", run_over="prim",
              code='s@material = "M_Metal"\ns@name = "lamp"')
    g.link(lamp, "geo", lampn, "geo")
    # Street tree: a tapering trunk, two limbs, a crown of eighteen lumpy leaf clusters, darker inside and low
    trunk = E("PCG_Tube", title="Tree trunk", radius1=0.17, radius2=0.10, height=3.2, cols=10, rows=2)
    tkm = E("PCG_MatchSize", title="Trunk on the ground", justify_y="min")
    g.link(trunk, "geo", tkm, "geo")
    limbs = boxes(E, "Limbs", "Bark", [(0.12, 1.6, 0.12, 0.35, 3.6, 0.0, 0.0), (0.1, 1.4, 0.1, -0.3, 3.5, 0.2, 0.0)])
    lmb = E("PCG_Transform", title="Limbs lean out", rz=-18.0, py=2.8)
    g.link(limbs, "geo", lmb, "geo")
    tkc = E("PCG_Color", title="Bark", attribute_class="prim", r=0.45, g=0.39, b=0.32)
    g.link(merge_all(E, "Trunk + limbs", [tkm, lmb]), "geo", tkc, "geo")
    blob = E("PCG_Sphere", title="Leaf cluster", radius=1.0, cols=12, rows=8)
    blbn = E("PCG_Normal", title="Cluster normals")
    g.link(blob, "geo", blbn, "geo")
    bln0 = E("PCG_AttribNoise", title="Lumpy cluster", noise_along_vector=True, amplitude=0.3)
    g.link(blbn, "geo", bln0, "geo")
    bln = E("PCG_Normal", title="Normals of the lumpy surface")
    g.link(bln0, "geo", bln, "geo")
    # eighteen clusters on the shell of an ellipsoid crown: small enough to read as foliage masses, not balloons
    cpts = E("PCG_Add", title="Crown: cluster centres", points=(
        "-1.06 5.11 -0.85\n1.14 4.08 -0.72\n0.48 5.70 1.35\n0.65 5.02 -1.22\n1.39 5.14 -0.76\n1.32 5.03 -0.33\n0.38 4.79 -1.29\n-1.13 5.40 -0.85\n-0.55 5.74 -0.68\n0.44 4.21 -0.64\n-0.34 6.33 0.46\n1.21 4.38 -1.17\n-0.52 4.37 -1.53\n-1.44 5.09 1.04\n-0.34 6.46 -0.08\n-0.30 4.25 1.48\n-0.93 4.23 -1.11\n0.59 5.87 0.93"))
    cpw = E("PCG_Wrangle", title="Cluster sizes + greens", code=(
        "@pscale = 0.7 + 0.35 * rand(@ptnum * 3.3)\n"
        "t = rand(@ptnum * 7.7)\n"
        "# darker low and inside the crown, sunlit yellow-greens on top\n"
        "hgt = smoothstep(3.8, 6.3, @P.y)\n"
        "v@leaf = lerp(set(0.13, 0.22, 0.08), set(0.30, 0.42, 0.14), 0.25 * t + 0.75 * hgt)\n"
        "@N = set(sin(@ptnum * 2.1), 0, cos(@ptnum * 2.1))\n"
        "@up = set(0, 1, 0)"))
    g.link(cpts, "geo", cpw, "geo")
    crc = E("PCG_CopyToPoints", title="Crown", target_point_attributes="", target_prim_attributes="leaf")
    g.link(bln, "geo", crc, "source")
    g.link(cpw, "geo", crc, "points")
    crg = E("PCG_Wrangle", title="Leaf colour per cluster", run_over="prim",
            code='@Cd = v@leaf\ns@material = "Leaves"')
    g.link(crc, "geo", crg, "geo")
    tree = merge_all(E, "Street tree", [tkc, crg])
    treen = E("PCG_Wrangle", title="Tree: name", run_over="prim", code='s@name = "tree"')
    g.link(tree, "geo", treen, "geo")
    # Parked car: a body with rounded shoulders, a cabin tapered to a raked windscreen and rear window (glass sides,
    # painted roof), lights, four wheels; the body takes a paint colour per car
    cbt = E("PCG_Wrangle", title="Body: narrower at the shoulders", code=(
        "top = @P.y > 0.8\n"
        "@P.z = where(top, @P.z * 0.94, @P.z)\n"
        "@P.x = where(top, @P.x * 0.97, @P.x)"))
    g.link(box(E, "Car body box", 4.4, 0.66, 1.8, 0.0, 0.6, 0.0), "geo", cbt, "geo")
    cbody = E("PCG_PolyBevel", title="Car body (bevelled)", distance=0.12)
    g.link(cbt, "geo", cbody, "geo")
    cct = E("PCG_Wrangle", title="Cabin: raked screens, tumblehome", code=(
        "top = @P.y > 1.4\n"
        "@P.x = where(top, @P.x * 0.6 - 0.2, @P.x)\n"
        "@P.z = where(top, @P.z * 0.86, @P.z)"))
    g.link(box(E, "Cabin box", 2.7, 0.6, 1.62, -0.15, 1.22, 0.0), "geo", cct, "geo")
    ccab = E("PCG_PolyBevel", title="Cabin (bevelled)", distance=0.05)
    g.link(cct, "geo", ccab, "geo")
    ccn = E("PCG_Normal", title="Cabin normals", add_to="prim")
    g.link(ccab, "geo", ccn, "geo")
    cbm = E("PCG_Wrangle", title="Body paint", run_over="prim", code='s@material = "Car_Paint"')
    g.link(cbody, "geo", cbm, "geo")
    ccm = E("PCG_Wrangle", title="Cabin: glass, painted roof", run_over="prim",
            code='s@material = where(@N.y > 0.8, "Car_Paint", "M_Glass")')
    g.link(ccn, "geo", ccm, "geo")
    clt = E("PCG_Wrangle", title="Lights", run_over="prim",
            code='s@material = "Car_Light"\n@Cd = where(@P.x > 0, set(0.95, 0.93, 0.85), set(0.7, 0.05, 0.04))')
    g.link(merge_all(E, "Head + tail lights", [
        box(E, "Headlight L", 0.06, 0.12, 0.34, 2.19, 0.75, 0.6), box(E, "Headlight R", 0.06, 0.12, 0.34, 2.19, 0.75, -0.6),
        box(E, "Tail light L", 0.06, 0.14, 0.3, -2.19, 0.78, 0.62), box(E, "Tail light R", 0.06, 0.14, 0.3, -2.19, 0.78, -0.62)]),
        "geo", clt, "geo")
    whl = [E("PCG_Tube", title=f"Wheel {i + 1}", radius1=0.34, radius2=0.34, height=0.26, cols=16, rows=2,
             caps=True, rx=90.0, center_x=x, center_y=0.34, center_z=z)
           for i, (x, z) in enumerate(((1.4, 0.78), (1.4, -0.78), (-1.4, 0.78), (-1.4, -0.78)))]
    wm = E("PCG_Wrangle", title="Tyres", run_over="prim", code='s@material = "Tyre"\n@Cd = set(0.06, 0.06, 0.06)')
    g.link(merge_all(E, "Wheels", whl), "geo", wm, "geo")
    car = merge_all(E, "Car", [cbm, ccm, clt, wm])
    carn = E("PCG_Wrangle", title="Car: name", run_over="prim", code='s@name = "car"')
    g.link(car, "geo", carn, "geo")
    props = merge_all(E, "Street furniture library", [lampn, treen, carn])
    off = cw + 1.2
    fpts = ([(sx * off, 0.0, sz * z) for sx in (-1, 1) for sz in (-1, 1) for z in range(10, int(reach * 0.5), 6)]
            + [(sx * x, 0.0, sz * off) for sx in (-1, 1) for sz in (-1, 1) for x in range(10, int(reach * 0.5), 6)])
    fp_ = E("PCG_Add", title="Furniture points along the curbs",
            points="\n".join(f"{x:g} {y:g} {z:g}" for x, y, z in fpts))
    fpn = E("PCG_Wrangle", title="Face the road; lamp / tree alternating; trees vary", code=(
        "along_z = abs(@P.x) < abs(@P.z)       # on a curb that runs along z\n"
        "k = floor(abs(where(along_z, @P.z, @P.x)) / 6)\n"
        's@name = where(k % 2 == 0, "lamp", "tree")\n'
        "tree = k % 2 == 1\n"
        "a = rand(@ptnum * 5.3) * 6.2832\n"
        "face = where(along_z, set(-np.sign(@P.x), 0, 0), set(0, 0, -np.sign(@P.z)))\n"
        "@N = where(tree, set(sin(a), 0, cos(a)), face)\n"
        "@up = set(0, 1, 0)\n"
        "@pscale = where(tree, 0.8 + 0.45 * rand(@ptnum * 1.7), 1.0)"))
    g.link(fp_, "geo", fpn, "geo")
    # parked cars in the 2 m parking lane beside each curb, about two in three slots taken
    cpos = ([(sx * (cw - 1.0), 0.0, sz * z) for sx in (-1, 1) for sz in (-1, 1) for z in range(14, int(reach * 0.6), 6)]
            + [(sx * x, 0.0, sz * (cw - 1.0)) for sx in (-1, 1) for sz in (-1, 1) for x in range(14, int(reach * 0.6), 6)])
    cpa = E("PCG_Add", title="Parking slots", points="\n".join(f"{x:g} {y:g} {z:g}" for x, y, z in cpos))
    cpr = E("PCG_Wrangle", title="Cars: which slots, heading, paint", code=(
        "along_z = abs(@P.x) < abs(@P.z)\n"
        "h = rand(@ptnum * 2.71 + 0.3)\n"
        "@keep = h < 0.62\n"
        "# drive on the right: the car heads along the traffic on its side of the street\n"
        "d = where(along_z, -np.sign(@P.x), np.sign(@P.z))\n"
        "@N = where(along_z, set(0, 0, 1) * d, set(1, 0, 0) * d)\n"
        "@N = set(@N.z, 0, -@N.x)   # the car model is long in x: turn it to face along N\n"
        "@up = set(0, 1, 0)\n"
        "@P += @N * (rand(@ptnum * 9.1) - 0.5) * 0.6\n"
        's@name = "car"\n'
        "@pscale = 1\n"
        "c = rand(@ptnum * 6.13)\n"
        "v@paint = where(c < 0.25, set(0.80, 0.80, 0.78), where(c < 0.45, set(0.06, 0.06, 0.07),"
        " where(c < 0.6, set(0.42, 0.44, 0.46), where(c < 0.72, set(0.55, 0.08, 0.06),"
        " where(c < 0.84, set(0.10, 0.18, 0.38), set(0.25, 0.30, 0.20))))))"))
    g.link(cpa, "geo", cpr, "geo")
    cpk = E("PCG_Blast", title="Taken slots", group="@keep == 0", cls="point")
    g.link(cpr, "geo", cpk, "geo")
    # A green belt west and east of the plot, between it and the first context blocks: lawn with scattered trees
    import random as _rnd
    rr = _rnd.Random(7)
    x0, x1 = hx + 1.0, hx + 24.0
    lawn = boxes(E, "Lawn (green belt)", "Lawn", [
        (x1 - x0, 0.2, hz + 14.0 - cw - 4.0, sx * (x0 + x1) / 2, -0.06, sz * (cw + 4.0 + hz + 14.0) / 2)
        for sx in (-1, 1) for sz in (-1, 1)])
    lawnc = E("PCG_Color", title="Lawn colour", attribute_class="prim", r=0.30, g=0.40, b=0.17)
    g.link(lawn, "geo", lawnc, "geo")
    ppts = []
    while len(ppts) < 110:
        x, z = rr.uniform(x0 + 2, x1 - 2) * rr.choice((-1, 1)), rr.uniform(cw + 7, hz + 12) * rr.choice((-1, 1))
        if all((x - a) ** 2 + (z - b) ** 2 > 20 for a, _, b in ppts):
            ppts.append((x, 0.0, z))
    pk = E("PCG_Add", title="Park trees", points="\n".join(f"{x:.2f} {y:g} {z:.2f}" for x, y, z in ppts))
    pkw = E("PCG_Wrangle", title="Park trees: size, turn", code=(
        's@name = "tree"\n'
        "a = rand(@ptnum * 3.7 + 0.2) * 6.2832\n"
        "@N = set(sin(a), 0, cos(a))\n"
        "@up = set(0, 1, 0)\n"
        "@pscale = 0.9 + 0.8 * rand(@ptnum * 2.3 + 0.7)"))
    g.link(pk, "geo", pkw, "geo")
    fall = merge_all(E, "Furniture + cars", [fpn, cpk, pkw])
    fcp = E("PCG_CopyToPoints", title="Place the street furniture", piece_attribute="name",
            target_prim_attributes="paint")
    g.link(props, "geo", fcp, "source")
    g.link(fall, "geo", fcp, "points")
    fcc = E("PCG_Wrangle", title="Car paint → body colour", run_over="prim",
            code='@Cd = where(@material == "Car_Paint", @paint, @Cd)')
    g.link(fcp, "geo", fcc, "geo")
    # Context: low-detail city blocks around the plot -- extruded footprints with a whole-bay facade texture (one
    # 4 m × 3.5 m bay per image), the way a game fills the distance behind a hero area
    ctx = E("PCG_Grid", title="Context: 32 m blocks (640 m)", size_x=640.0, size_z=640.0, cols=21, rows=21)
    ctw = E("PCG_Wrangle", title="Context: which blocks, how tall", run_over="prim", code=(
        "x = @P.x\n"
        "z = @P.z\n"
        f"inside = (abs(x) < {hx + 14:g}) & (abs(z) < {hz + 14:g})\n"
        "street = (abs(x) < 20) | (abs(z) < 20)\n"
        "i@drop = inside | street\n"
        "d = sqrt(x * x + z * z)\n"
        "# low around the plot so the hero buildings read, taller toward the horizon\n"
        "f = floor(3 + 4 * rand(@primnum * 1.37) + 7 * smoothstep(110, 280, d) * rand(@primnum * 2.9))\n"
        "@h = f * 3.5\n"
        "i@far = where(rand(@primnum * 4.4) < 0.5, 0, 1)"))
    g.link(ctx, "geo", ctw, "geo")
    ctb = E("PCG_Blast", title="Context: keep blocks", group="@drop == 1", cls="prim")
    g.link(ctw, "geo", ctb, "geo")
    cts = E("PCG_Primitive", title="Context: 27 m footprints (lanes between)", uniform_scale=0.88,
            unshare_points=True)
    g.link(ctb, "geo", cts, "geo")
    cte = E("PCG_PolyExtrude", title="Context: extrude by h", distance=1.0, use_local=True, distance_attrib="h",
            output_front=True)
    g.link(cts, "geo", cte, "geo")
    ctn = E("PCG_Normal", title="Context: face normals", add_to="prim")
    g.link(cte, "geo", ctn, "geo")
    ctu = E("PCG_UVProject", title="Context UVs: u = x / 4, v = y / 3.5 (one bay per image)", mode="box",
            fit_to_01=False, scale_u=0.25, scale_v=1.0 / 3.5)
    g.link(ctn, "geo", ctu, "geo")
    ctm = E("PCG_Wrangle", title="Context materials", run_over="prim", code=(
        "top = @N.y > 0.5\n"
        's@material = where(top, "M_RoofFlat", where(@far == 0, "M_FacadeFar", "M_FacadeFarBrick"))\n'
        "@Cd = where(top, set(0.36, 0.36, 0.36), where(@far == 0, set(0.66, 0.60, 0.51), set(0.52, 0.30, 0.22)))"))
    g.link(ctu, "geo", ctm, "geo")
    mg = E("PCG_Merge", title="Block")
    g.link(fv, "geo", mg, "geo1")
    g.link(gt, "geo", mg, "geo2")
    g.link(swc, "geo", mg, "geo3")
    g.link(fcc, "geo", mg, "geo4")
    g.link(rpm, "geo", mg, "geo5")
    g.link(ctm, "geo", mg, "geo6")
    mg0 = mg
    mg = E("PCG_Merge", title="Block + green belt")
    g.link(mg0, "geo", mg, "geo1")
    g.link(lawnc, "geo", mg, "geo2")
    vp = E("PCG_Viewport", size=[520, 520])
    g.link(fv, "geo", vp, "geo")
    # Hero shots: a low aerial over the crossing toward the tower, and one from the sidewalk at eye level
    cam1 = E("PCG_Camera", title="Camera: low aerial over the crossing", projection="perspective", mode="look_at",
             resolution_x=1600, resolution_y=900, fov=38.0, eye_x=-104.0, eye_y=34.0, eye_z=66.0,
             target_x=6.0, target_y=13.0, target_z=-10.0)
    pr = E("PCG_PreviewImage", width=1600, height=900, elevation=32.0, azimuth=30.0, shading="color",
           look="outdoor", textures=CITY_TEXTURES, sun_elevation=30.0, sun_azimuth=250.0, haze=2.5,
           ground_color="0.40 0.39 0.36", clouds=0.35, cloud_seed=5)
    g.link(mg, "geo", pr, "geo")
    g.link(cam1, "cam", pr, "camera")
    pv = E("PreviewImage", title="Assembled block", size=[520, 400])
    g.link(pr, "image", pv, "images")
    cam2 = E("PCG_Camera", title="Camera: eye level in the street", projection="perspective", mode="look_at",
             resolution_x=1600, resolution_y=900, fov=55.0, eye_x=-2.2, eye_y=1.7, eye_z=56.0,
             target_x=-0.5, target_y=8.0, target_z=-20.0)
    pr2 = E("PCG_PreviewImage", width=1600, height=900, elevation=10.0, azimuth=0.0, shading="color",
            look="outdoor", textures=CITY_TEXTURES, sun_elevation=40.0, sun_azimuth=35.0, haze=2.5,
            ground_color="0.40 0.39 0.36", clouds=0.35, cloud_seed=5)
    g.link(mg, "geo", pr2, "geo")
    g.link(cam2, "cam", pr2, "camera")
    pv2 = E("PreviewImage", title="Street level", size=[520, 400])
    g.link(pr2, "image", pv2, "images")
    kpts = E("PCG_Add", title="11 points in three rows (5 m apart)",
             points="\n".join(f"{5 * (i % 4)} 0 {-6 * (i // 4)}" for i in range(11)))
    kn = E("PCG_Wrangle", title="One piece per point", code=(
        'order = np.array(["Wall_Plain", "Wall_Window", "Wall_WindowPair", "Wall_Door", "Wall_Balcony",'
        ' "Wall_Shopfront", "Corner_Pillar", "Roof_Cornice", "Roof_Flat", "Roof_Unit", "Roof_Tank"])\n'
        "s@name = order[@ptnum]\n"
        "@N = set(0, 0, 1)\n"
        "@up = set(0, 1, 0)"))
    g.link(kpts, "geo", kn, "geo")
    kcp = E("PCG_CopyToPoints", title="Kit laid out in a row", piece_attribute="name")
    g.link(kc, "geo", kcp, "source")
    g.link(kn, "geo", kcp, "points")
    kpr = E("PCG_PreviewImage", width=1600, height=1000, elevation=28.0,
            azimuth=-35.0, shading="color", look="studio", textures=CITY_TEXTURES)
    g.link(kcp, "geo", kpr, "geo")
    kpv = E("PreviewImage", title="kit", size=[520, 360])
    g.link(kpr, "image", kpv, "images")
    return g


# ═══════════════════════════════════════════════════ Production 4: material library
# Shared by every material wrangle below: seamless fractal noise. pnoise() wraps the lattice with period = frequency, so
# with integer frequencies per metre every octave tiles on all four sides (noise() would leave a seam at the border).
MAT_FBM = (
    "# fbm(fx, fy, s, o): seamless fractal noise with fx × fy cells per metre (integers; unequal = stretched), seed s,\n"
    "# o octaves; normalized to roughly unit variance (about -2.5..2.5), so thresholds read the same at any octave count\n"
    "def fbm(fx, fy, s, o=4):\n"
    "    t = 0\n"
    "    a = 1.0\n"
    "    n = 0\n"
    "    for i in range(o):\n"
    "        t = t + a * (pnoise(set(@u * fx, @v * fy, s + i * 7.13), set(fx, fy, 0)) - 0.5)\n"
    "        n = n + a * a\n"
    "        fx = fx * 2\n"
    "        fy = fy * 2\n"
    "        a = a * 0.5\n"
    "    return t / (0.135 * sqrt(n))\n\n")

MAT_SRGB = ("# the colours above are picked as display (sRGB) values; the layer is linear -- Write File encodes it to sRGB\n"
            "@basecolor = clamp(c, 0, 1) ** 2.2\n")

# ── M_Wall: brick, 240 × 67 mm with 10 mm recessed joints (Pattern tile 4 × 13 per metre, gap 0.13 of 77 mm)
WALL_HEIGHT = MAT_FBM + (
    "# Height in metres (1024 px = 1 m; Height to Normal / AO use Strength 1, World Size 1, so the relief is real size)\n"
    "e = @pattern_edge / 1024\n"
    "r2 = rand(@pattern_id + 0.37)\n"
    "# chipped, irregular arrises: the brick outline is eaten back 0.5-3 mm by coarse noise, more on some bricks\n"
    "ee = e - clamp(0.0006 + 0.0010 * r2 + 0.0008 * fbm(48, 48, 3.1, 3), 0, 0.004)\n"
    "@brick = smoothstep(-0.0004, 0.0006, ee)\n"
    "# brick face: 3 mm rounded arris (quarter circle), a slight random tilt per brick, undulation, sand-struck pits\n"
    "t = clamp(ee / 0.003, 0, 1)\n"
    "arris = -0.003 * (1 - sqrt(1 - (1 - t) ** 2))\n"
    "tilt = 0.0015 * ((@pattern_uv.x - 0.5) * (rand(@pattern_id + 0.11) - 0.5)"
    " + (@pattern_uv.y - 0.5) * (rand(@pattern_id + 0.23) - 0.5))\n"
    "pits = -0.0012 * smoothstep(2.0, 2.6, fbm(192, 192, 5.5, 2))\n"
    "face = arris + tilt + 0.0005 * fbm(8, 8, 1.7, 4) + 0.00012 * fbm(256, 256, 2.9, 2) + pits\n"
    "@pits = smoothstep(2.0, 2.6, fbm(192, 192, 5.5, 2))\n"
    "# joint: struck 7 mm back from the face, sandy\n"
    "mortar = -0.007 + 0.0003 * fbm(160, 160, 9.1, 3)\n"
    "@height = lerp(mortar, face, @brick)\n")

WALL_COLOR = MAT_FBM + (
    "r = @pattern_rand\n"
    "r2 = rand(@pattern_id + 0.37)\n"
    "r3 = rand(@pattern_id + 0.71)\n"
    "# brick bodies: a spread of reds and oranges, ~12 % dark over-fired (clinker), a few pale buff ones\n"
    "body = lerp(set(0.50, 0.22, 0.14), set(0.68, 0.36, 0.22), r)\n"
    "body = where(r2 > 0.88, lerp(set(0.30, 0.15, 0.11), set(0.40, 0.21, 0.15), r3), body)\n"
    "body = where(r2 < 0.05, set(0.70, 0.52, 0.36), body)\n"
    "# inside each brick: mottling, a darker fire flash towards one end, dark iron specks\n"
    "m = fbm(16, 16, 2.3, 4)\n"
    "body = body * (1 + 0.07 * m)\n"
    "end = where(r3 > 0.5, @pattern_uv.x, 1 - @pattern_uv.x)\n"
    "body = body * (1 - 0.30 * smoothstep(0.55, 1.0, end) * smoothstep(0.4, 0.9, r))\n"
    "body = lerp(body, set(0.16, 0.09, 0.07), 0.7 * smoothstep(2.1, 2.6, fbm(320, 320, 7.7, 2)))\n"
    "body = lerp(body, body * 0.75, @pits)\n"
    "# mortar: lime-grey, sand grains\n"
    "mortar = set(0.60, 0.58, 0.54) * (1 + 0.06 * fbm(96, 96, 8.8, 3))\n"
    "c = lerp(mortar, body, @brick)\n"
    "# efflorescence (pale salt bloom) in large soft patches, and grime that collects in the cavities\n"
    "c = lerp(c, set(0.80, 0.78, 0.74), 0.35 * smoothstep(0.9, 2.0, fbm(3, 3, 4.4, 3)) * smoothstep(0.0, 1.2, fbm(64, 64, 2.2, 3)))\n"
    "c = c * lerp(0.72, 1.0, @ao_h)\n"
    "@ao = @ao_h\n"
    "@roughness = clamp(lerp(0.95, 0.84 + 0.04 * m, @brick) + 0.08 * @pits, 0, 1)\n"
    "@metallic = 0\n") + MAT_SRGB

# ── Ground_Cobble: rounded field cobbles ~12 cm (Voronoi 8 × 8), sand / soil joints, moss
COBBLE_HEIGHT = MAT_FBM + (
    "e = @pattern_edge / 1024\n"
    "r2 = rand(@pattern_id + 0.5)\n"
    "# joint: 8 mm either side of the cell edge, wobbly; stone foot sits 2 cm down in the bedding sand\n"
    "jw = 0.008 + 0.0018 * fbm(24, 24, 1.3, 3)\n"
    "@stone = smoothstep(0.0, 0.0015, e - jw)\n"
    "t = clamp((e - jw) / 0.008, 0, 1)\n"
    "@shoulder = t\n"
    "# the stone's form is a dome from the distance to the cell centre (round, smooth everywhere); the distance to the\n"
    "# joint only gives a narrow 8 mm rounded lip -- a wide ramp on it would show the Voronoi corners as pyramid facets\n"
    "shoulder = sqrt(1 - (1 - t) ** 2)\n"
    "dome = 1 - clamp(@pattern_dist / 0.75, 0, 1.2) ** 2\n"
    "top = 0.008 + 0.026 * clamp(dome, -0.3, 1) + 0.006 * (r2 - 0.5)\n"
    "stone = -0.02 + shoulder * (top + 0.0012 * fbm(24, 24, 4.2, 3))"
    " + 0.00015 * fbm(256, 256, 6.1, 2) - 0.0008 * smoothstep(1.7, 2.4, fbm(96, 96, 7.3, 2))\n"
    "joint = -0.02 + 0.0018 * fbm(64, 64, 2.6, 3)\n"
    "@height = lerp(joint, stone, @stone)\n")

COBBLE_COLOR = MAT_FBM + (
    "r = @pattern_rand\n"
    "r2 = rand(@pattern_id + 0.5)\n"
    "r3 = rand(@pattern_id + 0.9)\n"
    "# one stone type per cobble: grey granite, warm sandstone, blue-grey basalt, pink granite\n"
    "c = where(r < 0.4, set(0.55, 0.54, 0.52), where(r < 0.65, set(0.58, 0.52, 0.44),"
    " where(r < 0.88, set(0.40, 0.41, 0.42), set(0.58, 0.50, 0.47))))\n"
    "c = c * (0.82 + 0.3 * r2)\n"
    "# granite-like grain (light and dark crystals) and mottling\n"
    "g = fbm(256, 256, 3.7 + r3 * 40, 2)\n"
    "c = c * (1 + 0.10 * g + 0.06 * fbm(24, 24, 5.9 + r3 * 40, 3))\n"
    "c = lerp(c, set(0.12, 0.12, 0.12), 0.6 * smoothstep(1.6, 2.2, g))\n"
    "c = lerp(c, set(0.85, 0.84, 0.80), 0.5 * smoothstep(1.7, 2.3, -g))\n"
    "# dirt collects round each stone's foot\n"
    "soil = lerp(set(0.27, 0.23, 0.18), set(0.44, 0.39, 0.32), smoothstep(-1.2, 1.2, fbm(16, 16, 8.2, 3)))\n"
    "c = lerp(c, soil * 0.9, 0.5 * (1 - smoothstep(0.0, 0.9, @shoulder)) + 0.25 * smoothstep(0.3, 1.0, @pattern_dist / 0.75))\n"
    "c = lerp(soil, c, @stone)\n"
    "# moss in the joints (and creeping onto the stone feet) in large patches\n"
    "mz = smoothstep(0.2, 1.2, fbm(4, 4, 1.9, 3)) * smoothstep(-0.6, 0.8, fbm(80, 80, 2.4, 2))\n"
    "mz = mz * (1 - smoothstep(0.1, 0.4, @shoulder) * @stone)\n"
    "c = lerp(c, lerp(set(0.24, 0.30, 0.11), set(0.36, 0.42, 0.17), smoothstep(-1, 1, fbm(60, 60, 4.8, 2))), mz)\n"
    "c = c * lerp(0.7, 1.0, @ao_h)\n"
    "@ao = @ao_h\n"
    "# worn stone tops are smoother than the sides; joints and moss are fully rough\n"
    "@roughness = clamp(lerp(1.0, 0.72 - 0.18 * @shoulder, @stone) + 0.3 * mz, 0, 1)\n"
    "@metallic = 0\n") + MAT_SRGB

# ── M_Door: vertical tongue-and-groove planks, 12.5 cm wide, a butt joint per metre at a different height per plank
DOOR_HEIGHT = MAT_FBM + (
    "N = 8\n"
    "x = @u * N\n"
    "col = floor(x)\n"
    "pu = x - col\n"
    "cr = rand(col + 0.13)\n"
    "pv = frac(@v + rand(col + 0.57))\n"
    "e = min(min(pu, 1 - pu) / N, min(pv, 1 - pv))\n"
    "@plank = smoothstep(0.0015, 0.0027, e)\n"
    "@pu = pu\n"
    "@cr = cr\n"
    "# grain: flat-sawn growth rings running along the plank, warped by noise stretched along it; knots deflect it\n"
    "has = where(rand(col + 0.9) > 0.45, 1.0, 0.0)\n"
    "du = (pu - 0.25 - 0.5 * rand(col + 0.21)) / N\n"
    "dv = frac(@v - rand(col + 0.33) + 0.5) - 0.5\n"
    "dk = sqrt(du * du + (dv * 0.35) ** 2)\n"
    "@knot = has * (1 - smoothstep(0.007, 0.012, dk))\n"
    "phase = pu * 3.0 + 0.5 * fbm(32, 2, 3.3 + cr * 50, 4) + cr * 7 + has * 2.5 * exp(-dk / 0.015)\n"
    "ring = frac(phase * 2.2)\n"
    "late = smoothstep(0.62, 0.86, ring) * (1 - smoothstep(0.90, 1.0, ring))\n"
    "@late = late\n"
    "@pores = smoothstep(0.8, 2.0, fbm(256, 8, 6.6 + cr * 50, 2))\n"
    "# nails: two battens per metre, one nail per plank on each, 9 mm heads\n"
    "nv = min(abs(frac(@v) - 0.15), abs(frac(@v) - 0.65))\n"
    "nu = (pu - 0.5) / N\n"
    "dn = sqrt(nu * nu + nv * nv)\n"
    "@dn = dn\n"
    "@nail = 1 - smoothstep(0.0040, 0.0050, dn)\n"
    "# relief: weathered grain (soft earlywood worn back), slight cupping, 1.2 mm rounded plank edges, V joints 4 mm deep\n"
    "t = clamp((e - 0.0015) / 0.0012, 0, 1)\n"
    "face = -0.0006 * (2 * pu - 1) ** 2 + 0.00035 * late - 0.00015 * @pores + 0.0004 * @knot"
    " - 0.0012 * (1 - sqrt(1 - (1 - t) ** 2))\n"
    "@height = lerp(-0.004, face, @plank) + @nail * 0.0012 * sqrt(clamp(1 - (dn / 0.005) ** 2, 0, 1))\n")

DOOR_COLOR = MAT_FBM + (
    "cr = @cr\n"
    "# stained softwood, one tone per plank; darker latewood lines, pores, knots\n"
    "wood = lerp(set(0.44, 0.29, 0.17), set(0.58, 0.40, 0.25), cr)\n"
    "wood = wood * (1 - 0.30 * @late) * (1 - 0.12 * @pores) * (1 + 0.05 * fbm(8, 2, 1.1 + cr * 50, 3))\n"
    "wood = lerp(wood, set(0.24, 0.14, 0.08), @knot * 0.85)\n"
    "# weathering: sun-greyed patches, darker grime in the joints\n"
    "wood = lerp(wood, set(0.52, 0.49, 0.44), 0.35 * smoothstep(0.3, 1.8, fbm(3, 2, 7.4, 3)))\n"
    "wood = lerp(set(0.10, 0.07, 0.05), wood, @plank)\n"
    "# nails: dark steel heads, a rust halo, and a rust run below each nail\n"
    "nu = (@pu - 0.5) / 8\n"
    "nvb = where(abs(frac(@v) - 0.15) < abs(frac(@v) - 0.65), frac(@v) - 0.15, frac(@v) - 0.65)\n"
    "run = (1 - smoothstep(0.002, 0.005, abs(nu))) * smoothstep(-0.07, -0.004, nvb) * where(nvb < 0, 1.0, 0.0)\n"
    "halo = 1 - smoothstep(0.005, 0.011, @dn)\n"
    "rust = clamp(halo * 0.7 + run * 0.45 * (0.6 + 0.4 * fbm(16, 64, 9.3, 2)), 0, 1)\n"
    "c = lerp(wood, set(0.38, 0.19, 0.08), rust)\n"
    "c = lerp(c, set(0.22, 0.22, 0.23), @nail)\n"
    "c = c * lerp(0.75, 1.0, @ao_h)\n"
    "@ao = @ao_h\n"
    "@roughness = clamp(lerp(0.95, 0.72 - 0.06 * @late, @plank) + 0.15 * rust, 0, 1) * (1 - @nail) + 0.45 * @nail\n"
    "@metallic = @nail * 0.9\n") + MAT_SRGB

# ── M_Roof: standing-seam metal, pans 50 cm wide, painted, chipping to galvanized steel, rust runs
ROOF_HEIGHT = MAT_FBM + (
    "S = 2\n"
    "# seams at u = 0.25 / 0.75, so the tile border falls mid-pan (x = 0 / 1 is the seam centre)\n"
    "x = frac(@u * S + 0.5)\n"
    "dx = min(x, 1 - x) / S\n"
    "# standing seam: 25 mm tall, 20 mm wide, rounded cap; two shallow stiffening ribs in each pan; oil-canning waviness\n"
    "@seam = 1 - smoothstep(0.008, 0.011, dx)\n"
    "cap = sqrt(clamp(1 - (dx / 0.011) ** 2, 0, 1))\n"
    "dr = min(abs(x - 1 / 3), abs(x - 2 / 3)) / S\n"
    "rib = 0.0015 * (1 - smoothstep(0.002, 0.007, dr))\n"
    "oil = 0.0008 * fbm(2, 3, 1.1, 3) * smoothstep(0.02, 0.08, dx)\n"
    "@height = 0.025 * cap ** 0.35 * @seam + rib + oil + 0.00003 * fbm(256, 256, 4.4, 2)\n")

ROOF_COLOR = MAT_FBM + (
    "# chips: sharp-edged flakes, far more likely on the seam caps; a pale primer rim round each\n"
    "chn = fbm(24, 24, 7.7, 4) + 1.4 * @seam + 0.5 * fbm(4, 4, 3.0, 2)\n"
    "chip = smoothstep(1.85, 1.95, chn)\n"
    "rim = smoothstep(1.6, 1.85, chn) * (1 - chip)\n"
    "# paint: dark slate green, chalky sun-fading in big patches, dirt streaks running down the fall line\n"
    "paint = set(0.24, 0.33, 0.31) * (1 + 0.04 * fbm(32, 32, 2.2, 3))\n"
    "paint = lerp(paint, set(0.44, 0.49, 0.47), 0.45 * smoothstep(-0.5, 1.8, fbm(2, 3, 5.1, 3)))\n"
    "st = smoothstep(0.2, 1.8, fbm(64, 2, 5.5, 3))\n"
    "paint = paint * (1 - 0.16 * st)\n"
    "metal = set(0.62, 0.63, 0.64) * (1 + 0.05 * fbm(48, 48, 6.3, 2))\n"
    "c = lerp(lerp(paint, set(0.58, 0.58, 0.55), rim), metal, chip)\n"
    "# rust: on part of the bare metal, plus thin rust runs in the streak lines of rustier regions\n"
    "rr = smoothstep(0.0, 1.2, fbm(40, 40, 3.3, 3))\n"
    "runs = smoothstep(1.1, 2.0, fbm(48, 3, 9.9, 3)) * smoothstep(0.3, 1.5, fbm(3, 3, 2.2, 2))\n"
    "rust = clamp(chip * rr + 0.6 * runs * (1 - chip), 0, 1)\n"
    "c = lerp(c, lerp(set(0.36, 0.17, 0.07), set(0.52, 0.28, 0.12), smoothstep(-1, 1, fbm(96, 96, 1.4, 2))), rust)\n"
    "c = c * lerp(0.8, 1.0, @ao_h)\n"
    "@ao = @ao_h\n"
    "@metallic = chip * (1 - rust)\n"
    "@roughness = clamp(lerp(0.52 + 0.15 * st, 0.32, chip) + 0.5 * rust, 0, 1)\n") + MAT_SRGB

# ── M_Trim: painted precast concrete / stucco (bands, sills, frames, cornices): any orientation, any size
TRIM_HEIGHT = MAT_FBM + (
    "@pores = smoothstep(1.7, 2.3, fbm(180, 180, 5.2, 2))\n"
    "@height = 0.0003 * fbm(16, 16, 1.2, 4) + 0.0001 * fbm(256, 256, 3.4, 2) - 0.0007 * @pores\n")

TRIM_COLOR = MAT_FBM + (
    "c = set(0.80, 0.78, 0.72) * (1 + 0.035 * fbm(6, 6, 2.5, 4) + 0.02 * fbm(128, 128, 7.1, 2))\n"
    "c = lerp(c, c * 0.55, @pores)\n"
    "# rain-washed grime in vertical runs, heavier in a few places\n"
    "grime = smoothstep(0.3, 2.2, fbm(12, 2, 8.6, 4)) * smoothstep(-0.8, 1.2, fbm(2, 2, 3.9, 2))\n"
    "c = lerp(c, set(0.50, 0.48, 0.44), 0.3 * grime)\n"
    "c = c * lerp(0.8, 1.0, @ao_h)\n"
    "@ao = @ao_h\n"
    "@roughness = clamp(0.82 + 0.06 * fbm(32, 32, 1.8, 2) + 0.1 * @pores, 0, 1)\n"
    "@metallic = 0\n") + MAT_SRGB

# ── M_Glass: window glass (opaque PBR: dark tint, very smooth), with a dirt film, drips and smudges
GLASS_HEIGHT = MAT_FBM + (
    "# float glass is almost flat: 0.1 mm long waves just break up reflections\n"
    "@height = 0.0001 * fbm(2, 3, 1.5, 3)\n")

GLASS_COLOR = MAT_FBM + (
    "film = smoothstep(0.2, 1.8, fbm(4, 4, 6.2, 4))\n"
    "drip = smoothstep(1.2, 2.1, fbm(80, 3, 2.8, 3))\n"
    "smudge = smoothstep(0.8, 2.0, fbm(20, 20, 9.4, 3))\n"
    "dirt = clamp(0.5 * film + 0.6 * drip, 0, 1)\n"
    "c = lerp(set(0.10, 0.13, 0.14), set(0.32, 0.30, 0.27), 0.4 * dirt)\n"
    "@ao = 1\n"
    "@roughness = clamp(0.04 + 0.35 * dirt + 0.12 * smudge, 0, 1)\n"
    "@metallic = 0\n") + MAT_SRGB

# ── M_Metal: powder-coated dark steel (railings, canopies) with scratches to bare steel, scuffs, rust pinholes
METAL_HEIGHT = MAT_FBM + (
    "# scratches: thin lines along a few directions. Directions use integer (a, b), so the rotated coordinates stay\n"
    "# periodic over the 1 m tile; each line is cut into short pieces by noise along it\n"
    "sc = 0\n"
    "for k, (a, b, K) in enumerate(((1, 0, 23), (0, 1, 17), (1, 1, 19), (1, -1, 29), (2, 1, 13), (1, -2, 11))):\n"
    "    along = a * @u + b * @v\n"
    "    across = -b * @u + a * @v\n"
    "    q = across * K + 0.2 * (pnoise(set(along * 8, across * K, k * 3.1), set(8, K, 0)) - 0.5)\n"
    "    line = 1 - smoothstep(0.0, 0.0004 * K * sqrt(a * a + b * b), abs(frac(q) - 0.5))\n"
    "    seg = smoothstep(0.62, 0.70, pnoise(set(along * 24, across * K, k * 5.7 + 2), set(24, K, 0)))\n"
    "    sc = max(sc, line * seg)\n"
    "@scratch = sc\n"
    "@height = 0.00004 * fbm(220, 220, 3.3, 2) - 0.00008 * sc\n")

METAL_COLOR = MAT_FBM + (
    "coat = set(0.18, 0.19, 0.20) * (1 + 0.05 * fbm(12, 12, 1.6, 3))\n"
    "scuff = smoothstep(0.6, 2.0, fbm(8, 8, 4.1, 4))\n"
    "coat = lerp(coat, set(0.27, 0.28, 0.29), 0.6 * scuff)\n"
    "rust = smoothstep(2.0, 2.4, fbm(40, 40, 6.6, 3))\n"
    "c = lerp(coat, set(0.56, 0.57, 0.58), @scratch)\n"
    "c = lerp(c, set(0.38, 0.19, 0.09), rust)\n"
    "@ao = @ao_h\n"
    "@metallic = @scratch * (1 - rust)\n"
    "@roughness = clamp(lerp(lerp(0.45, 0.33, scuff), 0.3, @scratch) + 0.5 * rust, 0, 1)\n") + MAT_SRGB

# ── M_Sign: enamel-painted sign panel, sun-faded, craquelure (Voronoi 28 × 28) and flaking to grey primer
SIGN_HEIGHT = MAT_FBM + (
    "gate = smoothstep(-0.2, 1.0, fbm(4, 4, 2.7, 3))\n"
    "@crack = (1 - smoothstep(0.3, 1.4, @pattern_edge)) * gate * smoothstep(-0.5, 0.8, fbm(32, 32, 4.4, 2))\n"
    "@flake = smoothstep(1.55, 1.65, fbm(12, 12, 8.1, 4) + 0.7 * gate)\n"
    "# brush marks run along the panel (u); paint is 0.25 mm thick where it flaked off\n"
    "@height = 0.00006 * fbm(4, 96, 5.3, 3) - 0.0002 * @crack - 0.00025 * @flake\n")

SIGN_COLOR = MAT_FBM + (
    "paint = set(0.74, 0.55, 0.24) * (1 + 0.04 * fbm(4, 96, 5.3, 3))\n"
    "paint = lerp(paint, set(0.80, 0.72, 0.56), 0.5 * smoothstep(-0.4, 1.8, fbm(2, 2, 6.8, 3)))\n"
    "c = lerp(paint, set(0.22, 0.18, 0.13), 0.75 * @crack)\n"
    "primer = set(0.52, 0.52, 0.50) * (1 + 0.06 * fbm(64, 64, 1.9, 2))\n"
    "c = lerp(c, primer, @flake)\n"
    "c = c * lerp(0.8, 1.0, @ao_h)\n"
    "@ao = @ao_h\n"
    "@roughness = clamp(0.5 + 0.2 * smoothstep(-0.4, 1.8, fbm(2, 2, 6.8, 3)) + 0.3 * @flake + 0.2 * @crack, 0, 1)\n"
    "@metallic = 0\n") + MAT_SRGB

# ── M_BrickBuff: the same bricks in a buff / grey-yellow clay (London stock look), sooty in patches (pcg123)
BUFF_COLOR = MAT_FBM + (
    "r = @pattern_rand\n"
    "r2 = rand(@pattern_id + 0.37)\n"
    "r3 = rand(@pattern_id + 0.71)\n"
    "# yellow-grey stock bricks, a few purple-brown and orange ones mixed in\n"
    "body = lerp(set(0.62, 0.53, 0.38), set(0.76, 0.67, 0.50), r)\n"
    "body = where(r2 > 0.965, lerp(set(0.46, 0.36, 0.30), set(0.55, 0.42, 0.33), r3), body)\n"
    "body = where(r2 < 0.03, set(0.72, 0.50, 0.33), body)\n"
    "m = fbm(16, 16, 2.3, 4)\n"
    "body = body * (1 + 0.08 * m)\n"
    "body = lerp(body, set(0.20, 0.17, 0.14), 0.6 * smoothstep(2.0, 2.6, fbm(320, 320, 7.7, 2)))\n"
    "body = lerp(body, body * 0.75, @pits)\n"
    "mortar = set(0.66, 0.64, 0.60) * (1 + 0.06 * fbm(96, 96, 8.8, 3))\n"
    "c = lerp(mortar, body, @brick)\n"
    "# city soot: broad dark patches, heavier on some bricks\n"
    "soot = smoothstep(0.4, 2.0, fbm(3, 3, 6.1, 3)) * (0.6 + 0.4 * r3)\n"
    "c = lerp(c, c * 0.45, 0.55 * soot)\n"
    "c = c * lerp(0.72, 1.0, @ao_h)\n"
    "@ao = @ao_h\n"
    "@roughness = clamp(lerp(0.95, 0.86 + 0.04 * m, @brick) + 0.08 * @pits, 0, 1)\n"
    "@metallic = 0\n") + MAT_SRGB

# ── M_Stucco: painted lime render over masonry: trowel undulation, hairline cracks (Voronoi 6 × 6), patches where the
#    paint and render fell off showing brick-coloured base, rain streaks and a dirty plinth zone (pcg123)
STUCCO_HEIGHT = MAT_FBM + (
    "gate = smoothstep(0.9, 1.8, fbm(3, 3, 5.5, 3))\n"
    "@crack = (1 - smoothstep(0.2, 1.2, @pattern_edge)) * gate * smoothstep(-0.4, 0.9, fbm(24, 24, 1.1, 2))\n"
    "@spall = smoothstep(2.05, 2.2, fbm(3, 3, 3.3, 5) + 0.35 * fbm(24, 24, 6.2, 2))\n"
    "trowel = 0.0008 * fbm(4, 4, 2.2, 3) + 0.00025 * fbm(32, 32, 7.4, 3) + 0.00006 * fbm(256, 256, 9.9, 2)\n"
    "@height = trowel - 0.0004 * @crack - 0.006 * @spall\n")

STUCCO_COLOR = MAT_FBM + (
    "paint = set(0.84, 0.77, 0.63) * (1 + 0.04 * fbm(3, 3, 4.6, 3) + 0.015 * fbm(64, 64, 2.7, 2))\n"
    "# old coats of paint showing through where the top coat weathered thin\n"
    "paint = lerp(paint, set(0.80, 0.70, 0.62), 0.45 * smoothstep(0.6, 2.0, fbm(6, 6, 8.3, 4)))\n"
    "base = set(0.58, 0.54, 0.47) * (1 + 0.12 * fbm(48, 48, 1.5, 3))   # the grey lime render under the paint\n"
    "c = lerp(paint, set(0.60, 0.56, 0.50), 0.12 * @crack)\n"
    "c = lerp(c, base, @spall)\n"
    "streak = smoothstep(0.2, 2.0, fbm(16, 1, 6.9, 4)) * smoothstep(-0.6, 1.0, fbm(2, 2, 1.7, 2))\n"
    "c = lerp(c, set(0.42, 0.40, 0.36), 0.35 * streak)\n"
    "c = c * lerp(0.78, 1.0, @ao_h)\n"
    "@ao = @ao_h\n"
    "@roughness = clamp(0.88 + 0.06 * fbm(16, 16, 3.1, 2) + 0.06 * @spall, 0, 1)\n"
    "@metallic = 0\n") + MAT_SRGB

# ── Ground_Asphalt: road asphalt, aggregate up to 8 mm, polished wheel tracks, tar-sealed cracks, oil stains (pcg123)
ASPHALT_HEIGHT = MAT_FBM + (
    "agg = fbm(160, 160, 2.1, 2)\n"
    "@stone = smoothstep(0.9, 1.8, agg)\n"
    "@seal = (1 - smoothstep(0.5, 3.0, @pattern_edge)) * smoothstep(0.3, 1.2, fbm(3, 3, 4.2, 3))\n"
    "@height = 0.0015 * @stone + 0.0004 * fbm(48, 48, 6.6, 2) - 0.001 * smoothstep(1.6, 2.2, -agg)"
    " + 0.0004 * @seal\n")

ASPHALT_COLOR = MAT_FBM + (
    "c = set(0.25, 0.25, 0.245) * (1 + 0.08 * fbm(8, 8, 1.4, 3))\n"
    "# aggregate: light and dark stones, some worn to their colour on top\n"
    "c = lerp(c, set(0.37, 0.36, 0.35), 0.5 * @stone * smoothstep(-0.5, 1.5, fbm(320, 320, 8.8, 2)))\n"
    "c = lerp(c, set(0.08, 0.08, 0.08), 0.6 * smoothstep(1.7, 2.3, fbm(220, 220, 3.9, 2)))\n"
    "# sun-bleached surface in big soft patches, oil drips, black tar on the sealed cracks\n"
    "c = lerp(c, set(0.36, 0.36, 0.35), 0.4 * smoothstep(-0.5, 1.8, fbm(2, 2, 7.2, 3)))\n"
    "oil = smoothstep(1.6, 2.3, fbm(6, 6, 9.4, 3))\n"
    "c = lerp(c, set(0.10, 0.10, 0.11), 0.5 * oil)\n"
    "c = lerp(c, set(0.04, 0.04, 0.04), 0.9 * @seal)\n"
    "c = c * lerp(0.75, 1.0, @ao_h)\n"
    "@ao = @ao_h\n"
    "@roughness = clamp(0.9 - 0.25 * @stone * 0.5 - 0.35 * oil - 0.3 * @seal, 0, 1)\n"
    "@metallic = 0\n") + MAT_SRGB

# ── M_RoofFlat: flat-roof bitumen membrane with mineral grit (lighter than road asphalt), ponding stains (pcg123)
ROOFFLAT_COLOR = MAT_FBM + (
    "c = set(0.36, 0.36, 0.35) * (1 + 0.07 * fbm(8, 8, 2.4, 3))\n"
    "c = lerp(c, set(0.52, 0.51, 0.49), 0.5 * @stone)\n"
    "pond = smoothstep(0.6, 2.0, fbm(2, 2, 5.1, 3))\n"
    "c = lerp(c, set(0.24, 0.24, 0.23), 0.45 * pond)\n"
    "c = lerp(c, set(0.16, 0.16, 0.16), 0.9 * @seal)\n"
    "c = c * lerp(0.75, 1.0, @ao_h)\n"
    "@ao = @ao_h\n"
    "@roughness = clamp(0.92 - 0.2 * pond, 0, 1)\n"
    "@metallic = 0\n") + MAT_SRGB

# ── M_FacadeFar*: one whole facade bay (4 m × 3.5 m: wall, window with frame and sill, floor band) in a 1024² image,
#    for the low-detail context buildings around the city block. UVs there are box projections at u = x / 4,
#    v = y / 3.5, so bays line up with corners and floors (pcg123)
def _far_height():
    return MAT_FBM + (
        "x = @u\n"
        "y = @v\n"
        "win = smoothstep(0.0, 0.004, min(min(x - 0.31, 0.69 - x), min(y - 0.26, 0.84 - y)))\n"
        "frame = smoothstep(0.0, 0.004, min(min(x - 0.29, 0.71 - x), min(y - 0.24, 0.86 - y))) * (1 - win)\n"
        "mull = (1 - smoothstep(0.004, 0.008, abs(x - 0.5))) * win\n"
        "band = smoothstep(0.0, 0.004, y - 0.955)\n"
        "sill = smoothstep(0.0, 0.003, min(min(x - 0.28, 0.72 - x), min(y - 0.215, 0.24 - y)))\n"
        "@win = win * (1 - mull)\n"
        "@frame = clamp(frame + mull, 0, 1)\n"
        "@band = band\n"
        "# metres: window glass 15 cm back, frame 10 cm back, sill and band 4 cm proud\n"
        "@height = -0.15 * @win - 0.1 * @frame + 0.04 * clamp(band + sill, 0, 1) + 0.0006 * fbm(8, 7, 2.2, 3)\n")


def _far_color(wall):
    return MAT_FBM + (
        f"wall = set({wall})\n"
        "c = wall * (1 + 0.05 * fbm(8, 7, 4.4, 3))\n"
        "c = lerp(c, set(0.82, 0.80, 0.75), @band)\n"
        "# glass: dark with a lighter sky reflection toward the top, some windows lit warm or with curtains\n"
        "glass = lerp(set(0.07, 0.09, 0.11), set(0.20, 0.24, 0.28), smoothstep(0.3, 0.85, @v))\n"
        "c = lerp(c, set(0.86, 0.85, 0.82), @frame)\n"
        "c = lerp(c, glass, @win)\n"
        "c = c * lerp(0.7, 1.0, @ao_h)\n"
        "@ao = @ao_h\n"
        "@roughness = clamp(0.85 - 0.75 * @win - 0.2 * @frame, 0, 1)\n"
        "@metallic = 0\n") + MAT_SRGB


# name, title, source ("tile"/"cell" Pattern kwargs or None = blank image), height code, colour code, one-line summary
MATERIALS = (
    ("M_Wall", "brick wall", dict(kind="tile", counts="4 13", offset=0.5, gap=0.13, bevel=0.08,
                                  jitter=1.0, rand_seed=5), WALL_HEIGHT, WALL_COLOR,
     "240 × 67 mm bricks, 10 mm joints struck 7 mm back, chipped arrises, per-brick colour (reds, clinker, buff), "
     "fire flash, iron specks, salt bloom"),
    ("Ground_Cobble", "cobblestones", dict(kind="cell", counts="8 8", jitter=0.85, gap=0.0, rand_seed=4),
     COBBLE_HEIGHT, COBBLE_COLOR,
     "~12 cm domed field stones in sand, four stone types (granite, sandstone, basalt, pink granite) with grain, "
     "soil round the feet, moss in the joints"),
    ("M_Door", "wooden planks", None, DOOR_HEIGHT, DOOR_COLOR,
     "vertical 12.5 cm planks, V joints, staggered butt joints, growth rings deflected by knots, nails with rust runs"),
    ("M_Roof", "standing-seam roof", None, ROOF_HEIGHT, ROOF_COLOR,
     "25 mm seams every 50 cm, stiffening ribs, oil canning; paint chipping to galvanized steel (metallic), "
     "fall-line dirt, rust"),
    ("M_Trim", "painted concrete trim", None, TRIM_HEIGHT, TRIM_COLOR,
     "smooth painted precast / stucco with pores and rain-washed grime -- reads right on bands, sills and cornices"),
    ("M_Glass", "window glass", None, GLASS_HEIGHT, GLASS_COLOR,
     "dark tinted, roughness 0.04 when clean; dirt film, drips and smudges raise the roughness"),
    ("M_Metal", "powder-coated steel", None, METAL_HEIGHT, METAL_COLOR,
     "dark coat, scratches in six directions to bare steel (metallic), burnished scuffs, rust pinholes"),
    ("M_Sign", "painted sign panel", dict(kind="cell", counts="28 28", jitter=1.0, gap=0.0, rand_seed=12),
     SIGN_HEIGHT, SIGN_COLOR,
     "mustard enamel with brush marks, sun fading, craquelure in patches, flakes down to grey primer"),
    # pcg123: facade variants for the city and a road surface
    ("M_BrickBuff", "buff brick wall", dict(kind="tile", counts="4 13", offset=0.5, gap=0.13, bevel=0.08,
                                            jitter=1.0, rand_seed=9), WALL_HEIGHT, BUFF_COLOR,
     "the same bricks in yellow-grey stock clay with purple and orange strays, soot patches"),
    ("M_Stucco", "painted render", dict(kind="cell", counts="6 6", jitter=1.0, gap=0.0, rand_seed=21),
     STUCCO_HEIGHT, STUCCO_COLOR,
     "cream lime render: trowel undulation, hairline cracks, old coats showing, spalled patches down to the base, "
     "rain streaks"),
    ("Ground_Asphalt", "asphalt", dict(kind="cell", counts="3 3", jitter=1.0, gap=0.0, rand_seed=33),
     ASPHALT_HEIGHT, ASPHALT_COLOR,
     "dark asphalt with exposed aggregate, sun bleaching, oil drips, tar-sealed cracks"),
    ("M_RoofFlat", "bitumen roofing", dict(kind="cell", counts="2 2", jitter=1.0, gap=0.0, rand_seed=41),
     ASPHALT_HEIGHT, ROOFFLAT_COLOR,
     "flat-roof bitumen membrane with mineral grit, ponding stains and patched seams"),
    ("M_FacadeFar", "facade bay, render", None, _far_height(), _far_color("0.66, 0.60, 0.51"),
     "a whole 4 m × 3.5 m facade bay (window, frame, sill, floor band) for low-detail context buildings"),
    ("M_FacadeFarBrick", "facade bay, brick", None, _far_height(), _far_color("0.52, 0.30, 0.22"),
     "the same bay in a brick colour"),
)


def material_library(only=None):
    g = Graph()
    W = 340
    mats = [m for m in MATERIALS if only is None or m[0] in only]
    notes = Col(g, 0, width=W + 60)
    notes.note((
        "A set of 14 tileable PBR materials (1024², seamless on all four sides, **one image = 1 m × 1 m**, 1024 px/m; the "
        "modular building kit's UVs are also 1 UV = 1 m, so bricks and planks come out real size), 5 maps each:\n"
        "  BaseColor (sRGB) / Normal_GL (+Y) / Normal_DX (−Y, DirectX convention) / "
        "ORM (R = AO, G = roughness, B = metallic) / Height (16-bit, range in the .json)\n"
        "Written to output/pcg/materials/, file names T_material_map.png.\n\n"
        + "".join(f"  {n:<14} {s}\n" for n, _, _, _, _, s in mats) +
        "\nThe names are the modular building kit's material slots (M_Wall / M_Trim / M_Glass / M_Door / M_Metal / "
        "M_Roof / M_Sign): the kit's glb files already point to these images by relative path, so run this workflow "
        "first and the kit opens textured.\n\n"
        "**One pair of wrangles per material.** The first writes @height **in metres** (Height to Normal / AO run at "
        "Strength 1, World Size 1 m, so a 7 mm joint is 7 mm), plus masks the second one needs; the second writes "
        "basecolor / ao / roughness / metallic. Colours are typed as display (sRGB) values and turned linear with "
        "** 2.2 at the end, because Write File encodes BaseColor to sRGB.\n\n"
        "**How seamlessness is guaranteed**: all noise is pnoise() with period = frequency (integer cells per metre), "
        "Pattern counts are integers, stripes are periodic functions of u / v, and the scratch directions use integer "
        "(a, b) so rotated lines wrap too. noise() is not periodic -- don't use it in a tileable texture.\n\n"
        "Right of each pair: a studio preview of the material on a 2 m wall slab and a sphere (the slab shows a 2 × 2 "
        "repeat, so any seam would show)."),
        h=900, title="Material library (read me first)", w=W + 60)
    # Swatch: a 2 × 2 m slab standing on the ground and a 1 m sphere in front, box-projected UVs at 1 UV = 1 m
    sl = notes("PCG_Box", title="Swatch: 2 m slab", size_x=2.0, size_y=2.0, size_z=0.3, cy=1.0, cz=-0.4)
    sp = notes("PCG_Sphere", title="Swatch: 1 m sphere", radius=0.5, cols=48, rows=32, center_x=0.55,
               center_y=0.5, center_z=0.45)
    mg = notes("PCG_Merge", title="Swatch")
    g.link(sl, "geo", mg, "geo1")
    g.link(sp, "geo", mg, "geo2")
    swatch = notes("PCG_UVProject", title="Box projection, 1 UV = 1 m", mode="box", fit_to_01=False,
                   scale_u=1.0, scale_v=1.0)
    g.link(mg, "geo", swatch, "geo")

    y0, bottom = 0, 0
    for k, (name, label, src, hcode, ccode, _) in enumerate(mats):
        x0 = 460 + (k % 4) * 1180
        if k and k % 4 == 0:                    # second row starts below the tallest column of the first
            y0 = bottom + 120
        A = Col(g, x0, y0, width=W)
        B = Col(g, x0 + 380, y0, width=W)
        C = Col(g, x0 + 760, y0, width=W)
        if src is None:
            s = A("PCG_COPConstant", title=f"{name}: 1024² canvas (1 m)", resolution_x=1024, resolution_y=1024,
                  layer="base")
        else:
            s = A("PCG_COPPattern", title=f"{name}: {src['kind']} pattern {src['counts']}", resolution_x=1024,
                  resolution_y=1024, **src)
        h = A("PCG_COPWrangle", title=f"{name}: height (metres) + masks", code=hcode, rows_per_pass=256)
        g.link(s, "cop", h, "cop")
        nm = A("PCG_COPHeightToNormal", layer="height", strength=1.0, tile=True, out_layer="N")
        g.link(h, "cop", nm, "cop")
        ao = A("PCG_COPHeightToAO", layer="height", strength=1.0, radius=12.0, tile=True, out_layer="ao_h")
        g.link(nm, "cop", ao, "cop")
        c = B("PCG_COPWrangle", title=f"{name}: {label} -- colour / ORM", code=ccode, rows_per_pass=256)
        g.link(ao, "cop", c, "cop")
        for layer, mode, bits, enc, ny, suffix in (
                ("basecolor", "clamp", "8", "srgb", "+y", "BaseColor"),
                ("N", "signed", "8", "linear", "+y", "Normal_GL"),
                ("N", "signed", "8", "linear", "-y", "Normal_DX"),
                ("ao roughness metallic", "clamp", "8", "linear", "+y", "ORM"),
                ("height", "normalize", "16", "linear", "+y", "Height")):
            w = B("PCG_COPWriteFile", title=f"Write {suffix}",
                  filename=f"pcg/materials/T_{name}_{suffix}", channels=layer,
                  format="png", bit_depth=bits, encode=enc, remap=mode,
                  normal_y=ny)
            g.link(c, "cop", w, "cop")
        pr = C("PCG_PreviewImage", title=f"{name}: studio preview", width=800, height=800, elevation=18.0,
               azimuth=30.0, shading="color", look="studio",
               # orm switches the studio look to PBR shading: glass and metal read only through roughness / metallic
               textures="basecolor = @basecolor\nnormal = @N\norm = @ao roughness metallic")
        g.link(swatch, "geo", pr, "geo")
        g.link(c, "cop", pr, "textures_cop")
        pv = C("PreviewImage", title=name, size=[W, W + 60])
        g.link(pr, "image", pv, "images")
        bottom = max(bottom, A.y, B.y, C.y)
    return g


# ═══════════════════════════════════════════════════ English tutorials
# Small, focused workflows (6-15 nodes each) for docs/examples/. Pure PCG nodes plus
# ComfyUI's PreviewImage / SaveImage: no model files. All titles and notes in English.
def _bind(node, **refs):
    """
    Bind widgets of `node` to Parameters (PCG) entries by name, the same way the
    front end stores it (node.properties.pcg_bind = {widget: param name}).
    Bindings are materialized by the front end; the value already written into
    the widget must equal the panel value, so the caller passes it explicitly
    and test_workflows.py checks that both agree.
    """
    node["props"].setdefault("pcg_bind", {}).update(refs)
    return node


def tut_first_geometry():
    g = Graph()
    W = 360
    A, B, C = (Col(g, x, width=W) for x in (0, 420, 840))
    D = Col(g, 1260, width=520)
    A.note((
        "Your first procedural model: a tapered tower built from one box.\n\n"
        "1) Box makes a 2 x 1 x 2 block; Transform turns it 15 degrees around Y.\n"
        "2) Group Create puts the faces whose normal points up (Y, within 10 "
        "degrees) into the group 'top'. PolyExtrude #1 takes only that face, "
        "insets it and pushes it up. The new top face lands in the group "
        "'extrudeFront'.\n"
        "3) PolyExtrude #2 does the same again on 'extrudeFront': a second, "
        "narrower storey.\n"
        "4) PolyBevel rounds every edge; Color paints the result.\n"
        "5) Preview Image (PCG) renders a picture (shown by ComfyUI's Preview "
        "Image); 3D Viewport shows the mesh interactively.\n\n"
        "Tweak: the extrude Distance / Inset, the bevel Distance and Divisions, "
        "or switch Preview shading to 'normal' or 'lambert'."),
        h=420, title="First geometry (read me)", w=W)
    box = A("PCG_Box", size_x=2.0, size_y=1.0, size_z=2.0)
    xf = A("PCG_Transform", title="Turn 15 degrees", ry=15.0)
    g.link(box, "geo", xf, "geo")
    top = A("PCG_GroupCreate", title="Group 'top' (faces facing up)", name="top",
            cls="prim", use_normal=True, dir_x=0.0, dir_y=1.0, dir_z=0.0,
            spread=10.0)
    g.link(xf, "geo", top, "geo")
    e1 = B("PCG_PolyExtrude", title="Extrude the top face", group="top",
           distance=0.8, inset=0.3)
    g.link(top, "geo", e1, "geo")
    e2 = B("PCG_PolyExtrude", title="Extrude it again", group="extrudeFront",
           distance=0.6, inset=0.25)
    g.link(e1, "geo", e2, "geo")
    bv = C("PCG_PolyBevel", title="Round all edges", distance=0.05, divisions=3)
    g.link(e2, "geo", bv, "geo")
    col = C("PCG_Color", title="Paint", r=0.85, g=0.62, b=0.42)
    g.link(bv, "geo", col, "geo")
    pr = D("PCG_PreviewImage", width=1024, height=1024, elevation=28.0,
           azimuth=35.0, shading="color", look="studio")
    g.link(col, "geo", pr, "geo")
    pv = D("PreviewImage", title="Tapered tower", size=[520, 560])
    g.link(pr, "image", pv, "images")
    vp = D("PCG_Viewport", size=[520, 520])
    g.link(col, "geo", vp, "geo")
    return g


def tut_scatter_copy():
    g = Graph()
    W = 360
    A, B, C = (Col(g, x, width=W) for x in (0, 420, 840))
    D = Col(g, 1260, width=520)
    A.note((
        "Scatter points on a surface and copy a model onto every point.\n\n"
        "1) Grid + Attribute Noise (terrain fractal, Y only) make rolling ground.\n"
        "2) Scatter puts 250 random points on it.\n"
        "3) Attribute Randomize writes two point attributes that Copy to Points "
        "reads: pscale (uniform size, 0.15 to 0.6) and orient (a random rotation "
        "quaternion).\n"
        "4) The 'rock' is a coarse sphere roughened by Point Jitter.\n"
        "5) Copy to Points places one rock per point, scaled by pscale and "
        "rotated by orient. Merge adds the ground back for the preview.\n\n"
        "Tweak: Scatter Count and Seed, the pscale Min / Max, the jitter Scale, "
        "or swap the sphere for any other geometry."),
        h=420, title="Scatter and copy (read me)", w=W)
    grd = A("PCG_Grid", size_x=16.0, size_z=16.0, cols=120, rows=120)
    ter = A("PCG_AttribNoise", title="Rolling ground", use_x=False, use_z=False,
            amplitude=1.2, noise_type="perlin", fractal="terrain", octaves=4,
            element_size_x=7.0, element_size_y=7.0, element_size_z=7.0,
            rand_seed=4)
    g.link(grd, "geo", ter, "geo")
    gc = A("PCG_Color", title="Ground colour", r=0.36, g=0.45, b=0.24)
    g.link(ter, "geo", gc, "geo")
    sc = B("PCG_Scatter", count=250, rand_seed=7)
    g.link(ter, "geo", sc, "geo")
    ps = B("PCG_AttribRandomize", title="Random size (pscale)", name="pscale",
           min_x=0.15, max_x=0.6, rand_seed=1)
    g.link(sc, "points", ps, "geo")
    ori = B("PCG_AttribRandomize", title="Random rotation (orient)", name="orient",
            mode="orient", rand_seed=2)
    g.link(ps, "geo", ori, "geo")
    sph = C("PCG_Sphere", title="Rock base shape", radius=1.0, cols=10, rows=7)
    jit = C("PCG_PointJitter", title="Roughen", scale=0.35, rand_seed=3)
    g.link(sph, "geo", jit, "geo")
    rc = C("PCG_Color", title="Rock colour", r=0.55, g=0.52, b=0.48)
    g.link(jit, "geo", rc, "geo")
    cp = C("PCG_CopyToPoints")
    g.link(rc, "geo", cp, "source")
    g.link(ori, "geo", cp, "points")
    mg = D("PCG_Merge", title="Ground + rocks")
    g.link(gc, "geo", mg, "geo1")
    g.link(cp, "geo", mg, "geo2")
    pr = D("PCG_PreviewImage", width=1024, height=1024, elevation=35.0,
           azimuth=30.0, shading="color", look="studio")
    g.link(mg, "geo", pr, "geo")
    pv = D("PreviewImage", title="Scattered rocks", size=[520, 560])
    g.link(pr, "image", pv, "images")
    vp = D("PCG_Viewport", size=[520, 520])
    g.link(mg, "geo", vp, "geo")
    return g


def tut_attributes_wrangle():
    g = Graph()
    W = 360
    A, B, C = (Col(g, x, width=W) for x in (0, 420, 840))
    D = Col(g, 1260, width=520)
    A.note((
        "Attributes are named values stored on points or faces. This graph "
        "creates some, edits them with an expression, colours by one and builds "
        "a group from it.\n\n"
        "1) Attribute Create writes 'dist' = distance from the origin "
        "(expression length(@P)).\n"
        "2) Attribute Noise writes a second attribute, 'height' (0 to 1), "
        "instead of moving P.\n"
        "3) Wrangle edits it with Python-like code: heights fade out towards the "
        "edge using @dist.\n"
        "4) Attribute Promote copies 'height' from points to faces, because the "
        "next two nodes work on faces.\n"
        "5) Group Create puts every face with @height > 0.35 into the group "
        "'tall'; PolyExtrude raises only those faces, each by its own height "
        "(Local Attributes on, Distance Scale = height).\n"
        "6) Color 'Ramp from Attribute' maps height to a blue-to-red ramp.\n\n"
        "Tweak: the group threshold, the noise Element Size and Seed, the "
        "extrude Distance, or the Wrangle code."),
        h=520, title="Attributes and wrangle (read me)", w=W)
    grd = A("PCG_Grid", size_x=12.0, size_z=12.0, cols=61, rows=61)
    dist = A("PCG_AttribCreate", title="dist = length(@P)", name="dist",
             use_expression=True, expression="length(@P)")
    g.link(grd, "geo", dist, "geo")
    hn = B("PCG_AttribNoise", title="height = noise", attribute_names="height",
           attribute_type="float", range_values="zero_to_one", amplitude=1.0,
           noise_type="perlin", fractal="standard", octaves=3,
           element_size_x=4.0, element_size_y=4.0, element_size_z=4.0,
           rand_seed=5)
    g.link(dist, "geo", hn, "geo")
    wr = B("PCG_Wrangle", title="Fade towards the edge", code=(
        "# @dist and @height are point attributes; this runs on all points at once\n"
        "@height = @height * (1 - smoothstep(3.0, 6.0, @dist))"))
    g.link(hn, "geo", wr, "geo")
    pm = B("PCG_AttribPromote", title="height: points to faces",
           original_name="height", original_class="point", new_class="prim",
           method="average")
    g.link(wr, "geo", pm, "geo")
    gr = C("PCG_GroupCreate", title="Group 'tall'", name="tall", cls="prim",
           base="@height > 0.35")
    g.link(pm, "geo", gr, "geo")
    ex = C("PCG_PolyExtrude", title="Raise 'tall' by its height", group="tall",
           divide_into="individual", distance=3.0, use_local=True,
           distance_attrib="height")
    g.link(gr, "geo", ex, "geo")
    co = C("PCG_Color", title="Colour by height", attribute_class="prim",
           mode="ramp_by_attribute", attribute="height")
    g.link(ex, "geo", co, "geo")
    pr = D("PCG_PreviewImage", width=1024, height=1024, elevation=40.0,
           azimuth=30.0, shading="color", look="studio")
    g.link(co, "geo", pr, "geo")
    pv = D("PreviewImage", title="Coloured by height", size=[520, 560])
    g.link(pr, "image", pv, "images")
    vp = D("PCG_Viewport", size=[520, 520])
    g.link(co, "geo", vp, "geo")
    return g


def tut_foreach_variations():
    g = Graph()
    W = 360
    A, B, C = (Col(g, x, width=W) for x in (0, 420, 840))
    D = Col(g, 1260, width=520)
    A.note((
        "One chain, six different results: a For-Each loop in Count mode.\n\n"
        "For-Each Begin (Iterate over: Count, 6 iterations, Fetch Input) hands the "
        "same sphere to the loop body six times. Its 'iteration' output (0 to 5) "
        "is wired into the Seed of Point Jitter and Attribute Noise, so every pass "
        "gets different random numbers and a different stone.\n\n"
        "The Wrangle also gets the iteration on its Seed input; inside the code it "
        "is the variable 'seed'. It moves each stone along X and picks a colour. "
        "For-Each End (Gather: Merge) collects all six.\n\n"
        "Tweak: Iterations on For-Each Begin, the jitter Scale, the noise Amplitude, "
        "or what the Wrangle does with 'seed'."),
        h=440, title="For-Each variations (read me)", w=W)
    sph = A("PCG_Sphere", radius=1.0, cols=10, rows=7)
    fb = A("PCG_ForEachBegin", title="Each stone (count x 6)", method="fetch_input",
           iterate_over="count", iterations=6)
    g.link(sph, "geo", fb, "geo")
    jit = B("PCG_PointJitter", scale=0.5)
    g.link(fb, "geo", jit, "geo")
    g.link(fb, "iteration", jit, "rand_seed")
    sd = B("PCG_Subdivide", depth=3)
    g.link(jit, "geo", sd, "geo")
    nm = B("PCG_Normal", cusp_angle=180.0)
    g.link(sd, "geo", nm, "geo")
    ns = B("PCG_AttribNoise", title="Pits along the normal",
           noise_along_vector=True, amplitude=0.12, noise_type="worley_f2f1",
           fractal="standard", octaves=2, element_size_x=0.4,
           element_size_y=0.4, element_size_z=0.4)
    g.link(nm, "geo", ns, "geo")
    g.link(fb, "iteration", ns, "rand_seed")
    wr = C("PCG_Wrangle", title="Place and colour (seed = iteration)", code=(
        "# 'seed' is the value wired into the Seed input: the loop iteration\n"
        "@P.x += (seed - 2.5) * 2.3\n"
        "@Cd = lerp(set(0.42, 0.40, 0.37), set(0.66, 0.60, 0.52), rand(seed + 0.5))"))
    g.link(ns, "geo", wr, "geo")
    g.link(fb, "iteration", wr, "rand_seed")
    fe = C("PCG_ForEachEnd", gather="merge")
    g.link(wr, "geo", fe, "geo")
    g.link(fb, "loop", fe, "loop")
    pr = D("PCG_PreviewImage", width=1600, height=800, elevation=20.0,
           azimuth=0.0, shading="color", look="studio")
    g.link(fe, "geo", pr, "geo")
    pv = D("PreviewImage", title="Six stones", size=[520, 320])
    g.link(pr, "image", pv, "images")
    vp = D("PCG_Viewport", size=[520, 520])
    g.link(fe, "geo", vp, "geo")
    return g


def tut_cop_texture():
    g = Graph()
    W = 360
    A, B, C = (Col(g, x, width=W) for x in (0, 420, 840))
    D = Col(g, 1260, width=520)
    A.note((
        "A small stone-tile texture made with COP (image) nodes. A COP image is a "
        "stack of named layers; most nodes read one layer and write another.\n\n"
        "1) COP Noise writes a Perlin noise into layer C; COP Levels raises its "
        "contrast.\n"
        "2) COP Pattern (Tile Pattern, 4 x 4) adds the layers tile (mask), "
        "tile_height (bevelled tiles) and tile_rand (one random value per tile).\n"
        "3) COP Composite multiplies tile_height by the noise into a new layer "
        "'height' (Opacity 0.35 keeps it subtle).\n"
        "4) COP Remap turns tile_rand into a colour per tile (a ramp with r,g,b "
        "stops).\n"
        "5) COP Height to Normal makes a normal map N from 'height'; COP Light "
        "shades the colour with it.\n"
        "6) COP Export turns a layer into a ComfyUI IMAGE for Preview / Save "
        "(normals with mode 'signed').\n\n"
        "Tweak: Tile Count, Gap and Bevel, the Levels range, the Remap ramp, the "
        "normal Strength and the light direction."),
        h=560, title="COP texture (read me)", w=W)
    nz = A("PCG_COPNoise", title="Noise (layer C)", resolution_x=1024,
           resolution_y=1024, noise_type="perlin", fractal="standard",
           frequency=6.0, octaves=5, rand_seed=3)
    lv = A("PCG_COPLevels", title="More contrast", in_black=0.25, in_white=0.75,
           layers="C")
    g.link(nz, "cop", lv, "cop")
    pt = B("PCG_COPPattern", title="Tiles 4 x 4", kind="tile", counts="4 4",
           offset=0.0, gap=0.04, bevel=0.15, rand_seed=2, out_layer="tile",
           resolution_x=1024, resolution_y=1024)
    cm = B("PCG_COPComposite", title="height = tile_height x noise",
           mode="multiply", opacity=0.35, layer="tile_height",
           foreground_layer="C", output_layer="height")
    g.link(pt, "cop", cm, "background")
    g.link(lv, "cop", cm, "foreground")
    rm = C("PCG_COPRemap", title="Colour per tile", layers="tile_rand",
           ramp="0:0.42,0.40,0.37  0.5:0.62,0.55,0.46  1:0.50,0.36,0.28")
    g.link(cm, "cop", rm, "cop")
    nm = C("PCG_COPHeightToNormal", layer="height", strength=0.04, out_layer="N")
    g.link(rm, "cop", nm, "cop")
    lt = C("PCG_COPLight", normal_layer="N", albedo_layer="tile_rand",
           azimuth=135.0, elevation=40.0, ambient=0.3, out_layer="lit")
    g.link(nm, "cop", lt, "cop")
    ex = D("PCG_COPExport", title="Export lit", layer="lit")
    g.link(lt, "cop", ex, "cop")
    pv = D("PreviewImage", title="Shaded tiles", size=[520, 560])
    g.link(ex, "image", pv, "images")
    en = D("PCG_COPExport", title="Export normal", layer="N", mode="signed")
    g.link(lt, "cop", en, "cop")
    sn = D("SaveImage", title="normal", filename_prefix="pcg/tutorial_tiles_normal",
           size=[520, 520])
    g.link(en, "image", sn, "images")
    eh = D("PCG_COPExport", title="Export height", layer="height", mode="normalize")
    g.link(lt, "cop", eh, "cop")
    sh = D("SaveImage", title="height", filename_prefix="pcg/tutorial_tiles_height",
           size=[520, 520])
    g.link(eh, "image", sh, "images")
    return g


TUT_CONTROLS = ("float ring_radius = 4 : 1 12  # Ring radius\n"
                "int pillars = 12 : 3 48  # Pillar count\n"
                "float pillar_height = 3 : 0.5 10  # Pillar height\n")


def tut_controller():
    from comfyui_pcg.params import parse as _pparse, merge as _pmerge
    P = _pmerge(_pparse(TUT_CONTROLS), {})
    g = Graph()
    W = 360
    A, B, C = (Col(g, x, width=W) for x in (0, 420, 840))
    D = Col(g, 1260, width=520)
    A.note((
        "One control panel drives several nodes, like spare parameters on a "
        "Houdini null with relative references.\n\n"
        "Parameters (PCG) declares three values: ring_radius, pillars and "
        "pillar_height. They are bound (from the target node's right-click menu, "
        "PCG bind-parameter entry) to:\n"
        "  - Circle: Radius X / Y <- ring_radius, Divisions <- pillars\n"
        "  - Tube (the pillar): Height <- pillar_height\n"
        "  - Torus (the top ring): Radius <- ring_radius\n"
        "  - Transform (lifts the ring): Translate Y <- pillar_height\n"
        "A bound widget shows its reference in its label. Change a value on the "
        "panel and every bound widget follows; only the nodes that use it re-run.\n\n"
        "The chain itself: Circle points -> Copy to Points with a Tube whose base "
        "sits at y = 0 (Match Size) -> merge with the lifted Torus.\n\n"
        "Note: bindings are evaluated by the ComfyUI front end. Run through the "
        "API, the workflow uses the values last written into the widgets."),
        h=520, title="Controller panel (read me)", w=W)
    ctl = A("PCG_Parameters", title="Controls", declare=TUT_CONTROLS,
            values=json.dumps(P, sort_keys=True))
    cir = B("PCG_Circle", title="Pillar positions", orientation="zx",
            radius_x=P["ring_radius"], radius_y=P["ring_radius"],
            divisions=P["pillars"])
    _bind(cir, radius_x="ring_radius", radius_y="ring_radius", divisions="pillars")
    tb = B("PCG_Tube", title="Pillar", radius1=0.25, radius2=0.2,
           height=P["pillar_height"], cols=32)
    _bind(tb, height="pillar_height")
    ms = B("PCG_MatchSize", title="Base at y = 0", justify_y="min")
    g.link(tb, "geo", ms, "geo")
    cp = B("PCG_CopyToPoints", title="Pillars on the circle",
           transform_using_orientations=False)
    g.link(ms, "geo", cp, "source")
    g.link(cir, "geo", cp, "points")
    tor = C("PCG_Torus", title="Top ring", radius=P["ring_radius"],
            section_radius=0.2, rows=16, cols=96)
    _bind(tor, radius="ring_radius")
    up = C("PCG_Transform", title="Lift to the pillar tops", ty=P["pillar_height"])
    _bind(up, ty="pillar_height")
    g.link(tor, "geo", up, "geo")
    mg = C("PCG_Merge", title="Pillars + ring")
    g.link(cp, "geo", mg, "geo1")
    g.link(up, "geo", mg, "geo2")
    co = C("PCG_Color", r=0.80, g=0.76, b=0.68)
    g.link(mg, "geo", co, "geo")
    pr = D("PCG_PreviewImage", width=1024, height=1024, elevation=30.0,
           azimuth=30.0, shading="lambert", look="studio")
    g.link(co, "geo", pr, "geo")
    pv = D("PreviewImage", title="Pillar ring", size=[520, 560])
    g.link(pr, "image", pv, "images")
    vp = D("PCG_Viewport", size=[520, 520])
    g.link(co, "geo", vp, "geo")
    return g


TUTORIALS = {"tutorial_01_first_geometry": tut_first_geometry,
             "tutorial_02_scatter_copy": tut_scatter_copy,
             "tutorial_03_attributes_wrangle": tut_attributes_wrangle,
             "tutorial_04_foreach_variations": tut_foreach_variations,
             "tutorial_05_cop_texture": tut_cop_texture,
             "tutorial_06_controller": tut_controller}


# ═══════════════════════════════════════════════════ Self-check tools (for tests)
def _ranges(ntype):
    """(min, max) of a PCG node's INT / FLOAT inputs (core nodes are not checked)."""
    if ntype in CORE:
        return {}
    from comfyui_pcg import NODE_CLASS_MAPPINGS as M
    out = {}
    for sect in ("required", "optional"):
        for name, spec in (M[ntype].INPUT_TYPES().get(sect) or {}).items():
            if spec[0] in ("INT", "FLOAT") and len(spec) > 1 and isinstance(spec[1], dict):
                out[name] = (spec[1].get("min"), spec[1].get("max"))
    return out


def validate_ui(wf):
    """
    UI-format self-check: widget count, combo values, numbers within min / max, output names, link types at both ends and registration.
    Returns a list of problems. The frontend validates numeric ranges on submit ("Input out of range") but the executor (fakecomfy) does not,
    so it has to be checked here - that is how the open-world workflow's "Tree proxy" slipped through with rows = 1 < 2
    """
    probs = []
    ids = {n["id"]: n for n in wf["nodes"]}
    for n in wf["nodes"]:
        if n["type"] == "Note":
            continue
        ins, outs = spec_of(n["type"])
        want = sum(2 if t == "SEED" else 1 for _, t, _ in ins if is_widget(t))
        if len(n["widgets_values"]) != want:
            probs.append(f"{n['type']}: widgets {len(n['widgets_values'])} != {want}")
            continue
        k = 0
        rng = _ranges(n["type"])
        for name, t, _ in ins:
            if not is_widget(t):
                continue
            v = n["widgets_values"][k]
            if isinstance(t, list) and v not in t:
                probs.append(f"{n['type']}.{name} = {v!r} not in the combo")
            lo, hi = rng.get(name, (None, None))
            if t in ("INT", "FLOAT") and isinstance(v, (int, float)):
                if lo is not None and v < lo:
                    probs.append(f"{n.get('title') or n['type']}.{name} = {v} below minimum {lo}")
                if hi is not None and v > hi:
                    probs.append(f"{n.get('title') or n['type']}.{name} = {v} above maximum {hi}")
            k += 2 if t == "SEED" else 1
        if [o["name"] for o in n["outputs"]] != [o for o, _ in outs]:
            probs.append(f"{n['type']}: wrong output names")
    for lid, a, sa, b, sb, t in wf["links"]:
        na, nb = ids[a], ids[b]
        if na["outputs"][sa]["type"] != t or nb["inputs"][sb]["type"] != t:
            probs.append(f"link {lid} type mismatch")
        if nb["inputs"][sb]["link"] != lid or lid not in na["outputs"][sa]["links"]:
            probs.append(f"link {lid} not registered at both ends")
    return probs


def ui_to_api(wf):
    """UI -> API, following the frontend's graphToPrompt rules (muted / bypassed nodes are removed, and so are inputs connected to them)."""
    out = {}
    links = {x[0]: x for x in wf["links"]}
    for n in wf["nodes"]:
        if n["type"] == "Note" or n["mode"] in (2, 4):
            continue
        ins, _ = spec_of(n["type"])
        inputs = {}
        k = 0
        for name, t, _ in ins:
            if is_widget(t):
                v = n["widgets_values"][k]
                k += 2 if t == "SEED" else 1
                if t != "UPLOAD":
                    inputs[name] = v
        for inp in n["inputs"]:
            if inp["link"] is None:
                continue
            lk = links[inp["link"]]
            inputs[inp["name"]] = [str(lk[1]), lk[2]]
        out[str(n["id"])] = {"class_type": n["type"], "inputs": inputs}
    for v in out.values():
        for k2, x in list(v["inputs"].items()):
            if isinstance(x, list) and len(x) == 2 and x[0] not in out:
                del v["inputs"][k2]
    return out


WORKFLOWS = {"pcg_terrain_to_ai_texture": terrain_to_ai,
             "pcg_image_to_terrain": image_to_terrain,
             "pcg_sop_rock_garden": rock_garden,
             "pcg_sop_city_block": city_block,
             "pcg_cop_brick_material": brick_material,
             "pcg_cop_terrain_maps": terrain_maps,
             "pcg_prod_rock_assets": rock_assets,
             "pcg_prod_world_tiles": world_tiles,
             "pcg_prod_modular_city": modular_city,
             "pcg_prod_material_library": material_library,
             **TUTORIALS}


def main(outdir=None):
    outdir = outdir or os.path.join(_PKG, "example_workflows")
    os.makedirs(outdir, exist_ok=True)
    paths = []
    for name, fn in WORKFLOWS.items():
        p = os.path.join(outdir, name + ".json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(fn().to_ui(), f, ensure_ascii=False, indent=1)
        paths.append(p)
    return paths


if __name__ == "__main__":
    import fakecomfy  # noqa: F401
    for p in main(sys.argv[1] if len(sys.argv) > 1 else None):
        print(p)
