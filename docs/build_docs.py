"""
Build the English node reference (docs/reference/*.md) from the live node registry
plus the hand-written text in docs/_data/nodes/*.json.

Why generated: the parameter list, defaults, ranges, menu options and panel layout come
straight from INPUT_TYPES / the panel specs, so they cannot drift from the code. Only
the prose (what a node / parameter does) is hand-written, and test_docs.py fails if a
node or parameter has no prose, or if prose exists for something that no longer exists.

Usage (from the repo root, or from comfyui_pcg/docs):
    python build_docs.py              rebuild docs/reference/*.md
    python build_docs.py --check      exit 1 if the committed reference is stale
    python build_docs.py --skeleton F write the extracted structure (+ source docstrings) to F
"""
from __future__ import annotations

import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_PKG)
for _c in (_ROOT, os.path.dirname(_ROOT)):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
# fakecomfy (the ComfyUI stand-in) lives next to the tests: tests/ in the repo, the repo root in older layouts
for _t in (os.path.join(_PKG, "tests"), _ROOT):
    if os.path.exists(os.path.join(_t, "fakecomfy.py")) and _t not in sys.path:
        sys.path.append(_t)

DATA = os.path.join(_HERE, "_data", "nodes")
REF = os.path.join(_HERE, "reference")

# Pages of the reference. Geometry nodes are grouped by their ComfyUI category; image (COP)
# nodes carry a "topic" in their text entry because one category of 180 nodes is unreadable.
SOP_PAGES = [
    ("generate", "Generate", "Primitives, curves, terrain and other nodes that create geometry from nothing."),
    ("modify", "Modify", "Modeling operations: extrude, bevel, boolean, clip, fuse, remesh, subdivide and friends."),
    ("deform", "Deform", "Nodes that move points without changing topology."),
    ("topology", "Topology", "Connectivity, edges, paths and other structural queries and edits."),
    ("attribute", "Attributes", "Create, edit, transfer and randomize attributes."),
    ("group", "Groups", "Create, combine and convert groups."),
    ("scatter", "Scatter & Copy", "Scatter points and copy geometry onto them."),
    ("uv", "UV", "UV projection, unwrapping, layout and seams."),
    ("convert", "Convert", "Conversions between primitive types, volumes and other representations."),
    ("volume", "Volumes & VDB", "VDB creation, active regions, level sets, fields and the rest of the Volume SOPs (pcg106)."),
    ("render", "Render & View", "Preview images, 3D viewport, cameras and render passes."),
    ("output", "Output & Export", "Writing files and exporting to other applications."),
    ("loop", "Loops", "For-each loops and frame loops."),
    ("param", "Parameters & Expressions", "Controller nodes, values, expressions and parameter plumbing."),
    ("image", "Image", "Bridges between ComfyUI images and the plugin."),
]
COP_TOPICS = [
    ("cop-generate", "Image: Generators", "Noise, patterns, shapes, ramps and other image sources."),
    ("cop-color", "Image: Color & Levels", "Color correction, levels, remapping, keying."),
    ("cop-filter", "Image: Filters", "Blur, sharpen, edge detection, convolution, morphology."),
    ("cop-composite", "Image: Compositing & Masks", "Blending images and building masks."),
    ("cop-transform", "Image: Transform & Warp", "Transforms, distortion, UV mapping and sampling."),
    ("cop-layers", "Image: Channels & Layers", "Channels, layers, conversions between data types."),
    ("cop-terrain", "Image: Height Fields & Terrain", "Height field generation, erosion, masks and terrain tools."),
    ("cop-geometry", "Image: Geometry and Images", "Rasterizing and baking geometry; turning images back into geometry."),
    ("cop-sim", "Image: Simulation", "Reaction-diffusion, fluids, solvers and other iterative image processes."),
    ("cop-utility", "Image: Analysis, I/O & Utility", "Statistics, import / export, sequences, devices and wrangles."),
]
COP_TOPIC_IDS = [t[0] for t in COP_TOPICS]


def registry():
    import fakecomfy  # noqa: F401  (stand-in for ComfyUI when run outside it)
    from comfyui_pcg import nodes as N, expr as E, foreach as FE, framefor as FF
    m = dict(N.NODE_CLASS_MAPPINGS)
    names = dict(N.NODE_DISPLAY_NAME_MAPPINGS)
    for x in (E, FE, FF):
        m.update(x.NODE_CLASS_MAPPINGS)
        names.update(getattr(x, "NODE_DISPLAY_NAME_MAPPINGS", {}))
    return m, names


def houdini_map():
    """PCG node -> [(Houdini node, 'SOP'|'COP', status)] from sop_map.py / copernicus_map.py."""
    # the two tables live next to the tests: the repo root in a checkout, or
    # comfyui_pcg/tests/ in the published repo
    for d in (_ROOT, os.path.join(_PKG, "tests")):
        if os.path.exists(os.path.join(d, "sop_map.py")) and d not in sys.path:
            sys.path.insert(0, d)
    out = {}
    for mod_name, ctx in (("sop_map", "SOP"), ("copernicus_map", "COP")):
        try:
            mod = __import__(mod_name)
        except ImportError:
            raise SystemExit(f"{mod_name}.py not found (it sits next to the tests)")
        for h, v in mod.M.items():
            if v and v[0] in ("done", "new", "partial") and len(v) > 1 and str(v[1]).startswith("PCG_"):
                out.setdefault(v[1], []).append((h, ctx, v[0]))
    return out


def _params(node_id, it):
    """Parameters in panel order: [(name, spec, ui, folder, section)]."""
    from comfyui_pcg.panel import panel_model
    ui, specs, top, tabs = panel_model(node_id, it)
    seen, out = set(), []

    def add(n, folder, section):
        if n in seen or n not in specs:
            return
        seen.add(n)
        out.append((n, specs[n], ui.get(n, {}), folder, section))
        u = ui.get(n, {})
        for m in ((u.get("row") or {}).get("members") or []):
            add(m, folder, section)
        for m, um in ui.items():
            if um.get("in_toggle") == n or um.get("in_ramp") == n:
                add(m, folder, section)

    for blocks, folder in [(top, None)] + [(b, name) for name, b in tabs]:
        for sec, gate, items in blocks:
            if gate:
                add(gate, folder, sec)
            for n in items:
                add(n, folder, sec)
    for n in specs:
        add(n, None, None)
    return out


def _sockets(it):
    from comfyui_pcg.panel import _widget_kind
    out = []
    for grp in ("required", "optional"):
        for k, v in (it.get(grp) or {}).items():
            if not _widget_kind(v):
                t = v[0] if not isinstance(v[0], (list, tuple)) else "COMBO"
                out.append((k, str(t), grp == "optional"))
    return out


def structure():
    """Everything the docs need from the code, per node."""
    m, names = registry()
    hm = houdini_map()
    out = {}
    for nid in sorted(m):
        cls = m[nid]
        it = cls.INPUT_TYPES()
        rt = list(getattr(cls, "RETURN_TYPES", ()))
        rn = list(getattr(cls, "RETURN_NAMES", None) or [str(t).lower() for t in rt])
        ps, lead_of = [], {}
        for n, spec, u, folder, section in _params(nid, it):
            # vector / color rows (translate_x/_y/_z, …) are one row in the panel and one row here
            if u.get("in_row") and u["in_row"] in lead_of:
                lp = lead_of[u["in_row"]]
                lp["members"].append(n)
                d = (spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}).get("default")
                lp["default"] = list(lp["default"]) + [d]
                continue
            t = spec[0]
            o = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            p = {"name": n, "label": u.get("label") or n,
                 "type": "menu" if isinstance(t, (list, tuple)) else str(t),
                 "folder": folder, "section": section}
            if isinstance(t, (list, tuple)):
                p["options"] = [[str(x), (u.get("menu") or {}).get(x, str(x))] for x in t]
                p["default"] = o.get("default", t[0] if t else None)
            else:
                p["default"] = o.get("default")
                for k in ("min", "max"):
                    if k in o and abs(o[k]) < 1e5:
                        p[k] = o[k]
                if o.get("multiline"):
                    p["multiline"] = True
            if u.get("hide"):
                p["hide"] = u["hide"]
            if u.get("disable"):
                p["disable"] = u["disable"]
            row = u.get("row") or {}
            if row.get("members") and row["members"][0] == n and len(row["members"]) > 1:
                p["members"] = [n]
                p["default"] = [p.get("default")]
                if row.get("label"):
                    p["label"] = row["label"]
                lead_of[n] = p
            ps.append(p)
        out[nid] = {
            "id": nid, "title": names.get(nid, nid), "category": getattr(cls, "CATEGORY", ""),
            "inputs": [{"name": k, "type": t, "optional": o} for k, t, o in _sockets(it)],
            "outputs": [{"name": n, "type": str(t)} for n, t in zip(rn, rt)],
            "params": ps,
            "houdini": [{"node": h, "context": c, "status": s} for h, c, s in hm.get(nid, [])],
        }
    return out


def load_text():
    text = {}
    if os.path.isdir(DATA):
        for f in sorted(os.listdir(DATA)):
            if f.endswith(".json"):
                with open(os.path.join(DATA, f), encoding="utf-8") as fh:
                    for k, v in json.load(fh).items():
                        if k in text:
                            raise ValueError(f"{k} is documented twice (second time in {f})")
                        text[k] = v
    return text


# ───────────────────────────────────────────────────────────────── rendering
def _anchor(nid):
    return nid.lower().replace("_", "-")


def _fmt_default(p):
    d = p.get("default")
    if p.get("members"):
        q = dict(p)
        q.pop("members")
        return ", ".join(_fmt_default(dict(q, default=x)) for x in d)
    if p["type"] == "menu":
        for tok, lab in p.get("options", []):
            if tok == d:
                return lab
        return str(d)
    if p["type"] == "BOOLEAN":
        return "on" if d else "off"
    if p["type"] == "STRING":
        if d in (None, ""):
            return "*(empty)*"
        s = str(d)
        if "\n" in s or len(s) > 40:
            return "*(see panel)*"
        return "`" + s.replace("|", "\\|") + "`"
    if isinstance(d, float):
        return f"{d:g}"
    return "" if d is None else str(d)


_TYPE = {"INT": "int", "FLOAT": "float", "STRING": "string", "BOOLEAN": "toggle", "menu": "menu"}


def _cond(c, toggles=()):
    """'{ a == b }' -> 'a = b' (panel conditions are written in Houdini's hide-when syntax);
    toggles compared with 0 / 1 read as 'is off' / 'is on'."""
    c = c.strip()
    if c.startswith("{") and c.endswith("}"):
        c = c[1:-1].strip()

    def tog(m):
        name, op, v = m.group(1), m.group(2), m.group(3)
        if name not in toggles:
            return m.group(0)
        on = (v == "1") == (op == "==")
        return f"{name} is {'on' if on else 'off'}"
    c = re.sub(r"(\w+)\s*(==|!=)\s*([01])\b", tog, c)
    c = c.replace("==", "=").replace("!=", "≠")
    return re.sub(r"\s+", " ", c)


def _cell(s):
    return str(s or "").replace("\n", " ").replace("|", "\\|").strip()


def render_node(s, t):
    L = [f"### {s['title']}", "", f"<a id=\"{_anchor(s['id'])}\"></a>"]
    meta = [f"`{s['id']}`", f"category `{s['category']}`"]
    if s["houdini"]:
        hs = ", ".join(f"{h['node']} ({h['context']})" for h in s["houdini"])
        meta.append(f"Houdini: {hs}")
    L += ["", " · ".join(meta), "", t.get("summary", "").strip(), ""]
    # Picture rendered by tools/doc_images.py (inputs on the left, the result on the right), when there is one
    if os.path.exists(os.path.join(_HERE, "images", "nodes", f"{s['id']}.png")):
        L += [f"![{s['title']}: input and result](../images/nodes/{s['id']}.png)", ""]
    if t.get("description"):
        L += [t["description"].strip(), ""]
    if s["inputs"]:
        L += ["**Inputs**", "", "| Input | Type | Description |", "|---|---|---|"]
        for i in s["inputs"]:
            opt = " *(optional)*" if i["optional"] else ""
            L.append(f"| `{i['name']}`{opt} | {i['type']} | {_cell(t.get('inputs', {}).get(i['name']))} |")
        L.append("")
    if s["outputs"]:
        L += ["**Outputs**", "", "| Output | Type | Description |", "|---|---|---|"]
        for o in s["outputs"]:
            L.append(f"| `{o['name']}` | {o['type']} | {_cell(t.get('outputs', {}).get(o['name']))} |")
        L.append("")
    if s["params"]:
        L += ["**Parameters**", ""]
        first = cur = object()
        toggles = {q["name"] for q in s["params"] if q["type"] == "BOOLEAN"}
        for p in s["params"]:
            grp = " › ".join(x for x in (p["folder"], p["section"]) if x)
            if grp != cur:
                if cur is not first:
                    L.append("")
                if grp:
                    L += [f"*{grp}*", ""]
                L += ["| Parameter | Type | Default | Description |", "|---|---|---|---|"]
                cur = grp
            desc = _cell(t.get("params", {}).get(p["name"]))
            if p["type"] == "menu":
                opts = ", ".join(f"{lab}" + (f" (`{tok}`)" if lab != tok else "")
                                 for tok, lab in p["options"])
                desc += f" Options: {_cell(opts)}."
            rng = ""
            if "min" in p or "max" in p:
                rng = f" [{p.get('min', '')}..{p.get('max', '')}]".replace("[..]", "")
            if p.get("hide"):
                desc += f" *Hidden when {_cond(p['hide'], toggles)}.*"
            if p.get("disable"):
                desc += f" *Disabled when {_cond(p['disable'], toggles)}.*"
            names = " ".join(f"`{x}`" for x in (p.get("members") or [p["name"]]))
            L.append(f"| {_cell(p['label'])} {names} | {_TYPE.get(p['type'], p['type'])}{rng} "
                     f"| {_fmt_default(p)} | {desc.strip()} |")
        L.append("")
    if t.get("houdini_notes"):
        L += ["**Compared with Houdini**", "", t["houdini_notes"].strip(), ""]
    if t.get("tips"):
        L += ["**Tips**", ""] + [f"- {x.strip()}" for x in t["tips"]] + [""]
    return "\n".join(L)


def pages(struct, text):
    """{file name: markdown}."""
    by_page = {}
    for nid, s in struct.items():
        t = text.get(nid, {})
        cat = s["category"].split("/")[-1]
        page = t.get("topic") if cat == "cop" else cat
        by_page.setdefault(page, []).append(nid)
    out, index = {}, []
    for pid, title, blurb in SOP_PAGES + COP_TOPICS:
        ids = sorted(by_page.pop(pid, []), key=lambda n: struct[n]["title"].lower())
        if not ids:
            continue
        L = [f"# {title}", "", blurb, "", f"{len(ids)} nodes.", "",
             "[Back to the reference index](README.md)", "", "## Contents", ""]
        L += [f"- [{struct[n]['title']}](#{_anchor(n)}) — {_cell(text.get(n, {}).get('summary', ''))}"
              for n in ids]
        L += ["", "## Nodes", ""]
        for n in ids:
            L += [render_node(struct[n], text.get(n, {})), "---", ""]
        out[f"{pid}.md"] = "\n".join(L).rstrip() + "\n"
        index.append((pid, title, blurb, ids))
    if by_page:
        raise ValueError(f"nodes without a reference page: {by_page}")
    L = ["# Node reference", "",
         f"All {len(struct)} nodes of comfyui_pcg, generated from the code by `docs/build_docs.py` "
         "(parameter names, types, defaults and menu options are always current).", "",
         "In the parameter tables, the first column is the label shown in the node's panel followed "
         "by the input's internal name (the name used in saved workflows, relative references "
         "and `ch()` expressions). *Hidden when* / *Disabled when* repeat the panel's own rules.", ""]
    for pid, title, blurb, ids in index:
        L += [f"## [{title}]({pid}.md)", "", blurb, ""]
        L += [", ".join(f"[{struct[n]['title']}]({pid}.md#{_anchor(n)})" for n in ids), ""]
    L += ["## Alphabetical index", "", "| Node | ID | Page |", "|---|---|---|"]
    where = {n: (pid, title) for pid, title, _, ids in index for n in ids}
    for n in sorted(struct, key=lambda n: struct[n]["title"].lower()):
        pid, title = where[n]
        L.append(f"| [{struct[n]['title']}]({pid}.md#{_anchor(n)}) | `{n}` | {title} |")
    L += ["", "See also: [Houdini node index](houdini-index.md) — find the node that replaces a Houdini SOP or COP."]
    out["README.md"] = "\n".join(L) + "\n"
    # Houdini -> PCG index
    rows = []
    for n, s in struct.items():
        for h in s["houdini"]:
            rows.append((h["node"], h["context"], h["status"], n))
    rows.sort(key=lambda r: (r[1], r[0].lower(), r[3]))
    H = ["# Houdini node index", "",
         "Which comfyui_pcg node to use for a given Houdini SOP or Copernicus COP. "
         "*Equivalent* means the node does the same job, though individual options can still differ; "
         "*partial* means part of the Houdini node is missing. The node's reference entry "
         "(*Compared with Houdini*) lists known differences. Houdini nodes that are not listed have no "
         "equivalent yet, are out of scope (KineFX, crowds, solvers, VDB, ...), or are covered by ComfyUI "
         "itself (switches, nulls, subnetworks).", ""]
    for ctx, title in (("SOP", "Geometry (SOP)"), ("COP", "Copernicus (COP)")):
        H += [f"## {title}", "", "| Houdini node | comfyui_pcg node | Status |", "|---|---|---|"]
        for h, c, st, n in rows:
            if c == ctx:
                H.append(f"| {h} | [{struct[n]['title']}]({where[n][0]}.md#{_anchor(n)}) "
                         f"| {'partial' if st == 'partial' else 'equivalent'} |")
        H.append("")
    out["houdini-index.md"] = "\n".join(H)
    return out


def build(check=False):
    struct, text = structure(), load_text()
    out = pages(struct, text)
    stale = []
    os.makedirs(REF, exist_ok=True)
    for f, md in out.items():
        p = os.path.join(REF, f)
        old = open(p, encoding="utf-8").read() if os.path.exists(p) else None
        if old != md:
            stale.append(f)
            if not check:
                with open(p, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(md)
    extra = [f for f in os.listdir(REF) if f.endswith(".md") and f not in out]
    if extra and not check:
        for f in extra:
            os.remove(os.path.join(REF, f))
    return stale + extra


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--skeleton"]:
        import inspect
        from comfyui_pcg import panel
        s = structure()
        m, _ = registry()
        for nid, v in s.items():
            v["source_doc"] = inspect.getdoc(m[nid]) or ""
            it = m[nid].INPUT_TYPES()
            ui, _node = panel.layout_for(nid, it)
            v["source_help"] = {k: u["help"] for k, u in ui.items() if u.get("help")}
        with open(a[1], "w", encoding="utf-8") as fh:
            json.dump(s, fh, ensure_ascii=False, indent=1)
        print(len(s), "nodes")
    elif a[:1] == ["--check"]:
        st = build(check=True)
        print("stale:", st if st else "none")
        sys.exit(1 if st else 0)
    else:
        print("written:", build() or "nothing changed")
