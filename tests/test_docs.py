"""
English user documentation (comfyui_pcg/docs): coverage, freshness, links, language.

  1. every registered node has text, and so do all its inputs, outputs and parameter rows;
     no text for things that no longer exist; image nodes have a valid reference topic
  2. the generated reference (docs/reference/*.md) matches what build_docs.py would write now
  3. every relative link in the English docs points to an existing file, and to an existing anchor
  4. no CJK characters in the English docs or their text data (the per-node audit/design notes in
     docs/pcg100, and local development notes in docs/dev (not published), are not user docs and are excluded on purpose)
Each check has a negative control that feeds it a broken case and expects it to complain.

Runs in both layouts: repo root (tests next to comfyui_pcg/) and an installed copy
(tests in comfyui_pcg/tests/).
"""
import copy
import importlib.util
import os
import re
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)), "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy  # noqa: F401,E402
import comfyui_pcg  # noqa: E402

DOCS = os.path.join(os.path.dirname(comfyui_pcg.__file__), "docs")
_spec = importlib.util.spec_from_file_location("build_docs", os.path.join(DOCS, "build_docs.py"))
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)[:400]
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


CJK = re.compile(r"[　-〿㐀-鿿＀-￯]")


def coverage(struct, text):
    bad = []
    for nid, s in struct.items():
        e = text.get(nid)
        if not e:
            bad.append(f"{nid}: no entry")
            continue
        if not str(e.get("summary", "")).strip():
            bad.append(f"{nid}: no summary")
        for kind, items in (("inputs", s["inputs"]), ("outputs", s["outputs"]), ("params", s["params"])):
            have = e.get(kind) or {}
            names = [x["name"] for x in items]
            bad += [f"{nid}: {kind} {n} has no text" for n in names if not str(have.get(n, "")).strip()]
            bad += [f"{nid}: {kind} {n} does not exist" for n in have if n not in names]
        if s["category"].endswith("/cop") and e.get("topic") not in B.COP_TOPIC_IDS:
            bad.append(f"{nid}: bad topic {e.get('topic')!r}")
    bad += [f"{k}: documented but not registered" for k in text if k not in struct]
    return bad


def _slug(h):
    s = h.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def anchors_of(md):
    a = set(re.findall(r'<a id="([^"]+)"', md))
    for h in re.findall(r"(?m)^#{1,6}\s+(.*)$", md):
        a.add(_slug(re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", h)))
    return a


def english_files():
    out = []
    for root, dirs, files in os.walk(DOCS):
        dirs[:] = [d for d in dirs if d not in ("pcg100", "dev")]
        out += [os.path.join(root, f) for f in files if f.endswith((".md", ".json"))]
    return sorted(out)


def broken_links(files, read=lambda p: open(p, encoding="utf-8").read()):
    bad, cache = [], {}
    for p in files:
        if not p.endswith(".md"):
            continue
        md = read(p)
        md = re.sub(r"```.*?```", "", md, flags=re.S)
        for target in re.findall(r"\]\(([^)\s]+)\)", md):
            if re.match(r"^[a-z]+:", target):          # http:, mailto: …
                continue
            path, _, frag = target.partition("#")
            full = os.path.normpath(os.path.join(os.path.dirname(p), path)) if path else p
            if not os.path.exists(full):
                bad.append(f"{os.path.relpath(p, DOCS)} -> {target}: no such file")
                continue
            if frag and full.endswith(".md"):
                if full not in cache:
                    cache[full] = anchors_of(read(full))
                if frag not in cache[full]:
                    bad.append(f"{os.path.relpath(p, DOCS)} -> {target}: no such anchor")
    return bad


struct, text = B.structure(), B.load_text()

sec("1. every node, input, output and parameter has text")
bad = coverage(struct, text)
check(f"{len(struct)} nodes, {sum(len(s['params']) for s in struct.values())} parameter rows: all documented",
      not bad, bad[:8])
check("  at least 400 nodes are registered (the registry was really read)", len(struct) >= 400, len(struct))
nid = "PCG_Clip"
t2 = copy.deepcopy(text)
t2[nid]["params"].pop("keep")
t2[nid]["params"]["no_such_param"] = "x"
t2["PCG_COPBlur"]["topic"] = "nope"
t2.pop("PCG_Box")
b2 = coverage(struct, t2)
check("  negative control: a missing param, an unknown param, a bad topic and a missing node are all reported",
      any("keep has no text" in x for x in b2) and any("no_such_param does not exist" in x for x in b2)
      and any("bad topic" in x for x in b2) and any("PCG_Box: no entry" in x for x in b2), b2[:6])

sec("2. the generated reference is up to date")
stale = B.build(check=True)
check("docs/reference/*.md == what build_docs.py writes now (run build_docs.py after changing nodes)",
      not stale, stale)
pages = B.pages(struct, text)
check("  one page per non-empty category / topic, plus the index and the Houdini index",
      "README.md" in pages and "houdini-index.md" in pages and "modify.md" in pages
      and "cop-filter.md" in pages, sorted(pages)[:6])
t3 = copy.deepcopy(text)
t3["PCG_Clip"]["summary"] = "Something else."
check("  negative control: changing a summary changes the generated page",
      B.pages(struct, t3)["modify.md"] != pages["modify.md"])
every = "\n".join(pages.values())
missing = [n for n in struct if f'<a id="{B._anchor(n)}">' not in every]
check("  every node has an anchor in the reference", not missing, missing[:5])
row = next(p for p in struct["PCG_Clip"]["params"] if p["name"] == "dir_x")
check("  vector rows are one row: Clip's Direction lists dir_x dir_y dir_z, default 0, 1, 0",
      row.get("members") == ["dir_x", "dir_y", "dir_z"] and B._fmt_default(row) == "0, 1, 0", row)
check("  toggle conditions read as on / off ('fill = 0' -> 'fill is off')",
      B._cond("{ fill == 0 }", {"fill"}) == "fill is off" and B._cond("{ fill != 0 }", {"fill"}) == "fill is on"
      and B._cond("{ mode == 0 }", set()) == "mode = 0")

sec("3. links")
files = english_files()
check("found the English docs (getting started, concepts, examples, reference)",
      sum(f.endswith(".md") for f in files) >= 40
      and any(f.endswith("getting-started.md") for f in files), len(files))
bl = broken_links(files)
check("every relative link resolves to a file and anchor", not bl, bl[:8])
fake = os.path.join(DOCS, "concepts", "__fake__.md")
bl2 = broken_links([fake], read=lambda p: ("[a](../reference/modify.md#pcg-no-such-node) [b](nowhere.md) "
                                          "[c](../reference/modify.md#pcg-clip)") if p == fake
                   else open(p, encoding="utf-8").read())
check("  negative control: a bad anchor and a missing file are reported, a good link is not",
      len(bl2) == 2 and any("no such anchor" in x for x in bl2) and any("no such file" in x for x in bl2), bl2)

sec("4. English only")
cjk = [os.path.relpath(f, DOCS) for f in files if CJK.search(open(f, encoding="utf-8").read())]
check("no CJK characters in the English docs and their text data", not cjk, cjk[:5])
check("  negative control: the CJK check catches Chinese text", bool(CJK.search("裁剪 Clip")))
check("  the audit notes (docs/pcg100) and local development notes (docs/dev, not published) are excluded",
      os.path.isdir(os.path.join(DOCS, "pcg100")) and not any("pcg100" in f for f in files)
      and not any(os.sep + "dev" + os.sep in f for f in files))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
