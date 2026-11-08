"""
HTML documentation (docs/html, built by docs/build_html.py from the Markdown in docs/).

  1. the committed site is what build_html.py would write now (--check), and every Markdown page is in the navigation
  2. the Markdown converter: headings / anchors, lists, tables, code, links (.md -> .html, outside docs -> GitHub)
  3. every local link and picture of the site exists, and every #fragment exists on its page
  4. every node has its heading (with an icon) on its reference page and an entry in the search index
  5. pictures: every node picture belongs to a real node and is shown; the concept pictures exist and are used
Each check has a negative control.
"""
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DOCS = os.path.join(REPO, "docs")
SITE = os.path.join(DOCS, "html")
_spec = importlib.util.spec_from_file_location("build_html", os.path.join(DOCS, "build_html.py"))
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)[:400]
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


# ─────────────────────────────────────────────── 1
sec("1. the site is current")
check("build_html.py --check: docs/html matches the Markdown", B.main(["--check"]) == 0)
site = B.Site()
listed = [p for _, items in site.nav for p in items]
check("every Markdown page is in the navigation exactly once",
      sorted(listed) == sorted(site.pages) and len(listed) == len(set(listed)),
      sorted(set(site.pages) ^ set(listed)))
check("  the internal notes (docs/dev, docs/pcg100) are not part of the site",
      not any(p.startswith(("dev/", "pcg100/")) for p in site.pages))
check("  negative control: a page missing from the navigation is reported",
      bool(set(site.pages + ["concepts/new-page.md"]) - set(listed)))

# ─────────────────────────────────────────────── 2
sec("2. Markdown converter")


def conv(md, src="concepts/x.md"):
    s = B.Site.__new__(B.Site)
    s.repo, s.pages, s.anchor_node = "https://github.com/u/r", ["concepts/x.md", "concepts/y.md",
                                                                 "README.md"], {}
    s.icons = {"nodes": {}, "glyphs": {}}
    c = B.Ctx(s, src)
    return B.convert(md, c), c


h, c = conv("# Title\n\n## A `code` heading\n\ntext\n\n## A `code` heading\n")
check("headings get GitHub-style ids, duplicates are numbered",
      'id="a-code-heading"' in h and 'id="a-code-heading-1"' in h and c.title == "Title", h[:300])
h, _ = conv("- one\n- two\n  - nested\n- three\n\n1. a\n2. b\n")
check("lists: bullets, nesting, numbered",
      h.count("<ul>") == 2 and "<li>nested</li>" in h and "<ol><li>a</li><li>b</li></ol>" in h, h)
h, _ = conv("| A | B |\n|---|--:|\n| 1 \\| 2 | **x** |\n")
check("tables: header, alignment, escaped pipes, inline markup",
      "<th>A</th>" in h and 'style="text-align:right"' in h and "<td>1 | 2</td>" in h
      and "<strong>x</strong>" in h, h)
h, _ = conv("```python\nif a < b and c > d:\n    pass\n```\n")
check("code blocks are escaped, keep indentation and language",
      'class="lang-python"' in h and "a &lt; b" in h and "\n    pass" in h, h)
h, _ = conv("See [y](y.md#sec), [top](../README.md), [wf](../../example_workflows/a.json) and "
            "![pic](../images/p.png). Text with `<b>` and a < b.")
check("links: .md -> .html (README -> index.html), outside docs -> GitHub, pictures stay in docs/images",
      'href="y.html#sec"' in h and 'href="../index.html"' in h
      and 'href="https://github.com/u/r/' in h and 'src="../../images/p.png"' in h, h)
check("  inline code and text are escaped", "<code>&lt;b&gt;</code>" in h and "a &lt; b" in h, h)
h, _ = conv("**bold** and *em* but not snake_case_name or 2*3*4")
check("bold / italic, but not inside identifiers or arithmetic",
      "<strong>bold</strong>" in h and "<em>em</em>" in h and "snake_case_name" in h and "2*3*4" in h, h)

# ─────────────────────────────────────────────── 3
sec("3. links and pictures of the site")


def site_files():
    out = []
    for root, _, fs in os.walk(SITE):
        out += [os.path.join(root, f) for f in fs if f.endswith(".html")]
    return sorted(out)


def broken(files, read=lambda p: open(p, encoding="utf-8").read()):
    bad, ids = [], {}

    def anchors(path):
        if path not in ids:
            ids[path] = set(re.findall(r'\bid="([^"]+)"', read(path)))
        return ids[path]
    for p in files:
        text = re.sub(r"<pre>.*?</pre>", "", read(p), flags=re.S)
        for target in re.findall(r'\b(?:href|src)="([^"]+)"', text):
            if re.match(r"^[a-z]+:", target) or target.startswith("//"):
                continue
            path, _, frag = target.partition("#")
            dst = os.path.normpath(os.path.join(os.path.dirname(p), path)) if path else p
            if not os.path.exists(dst):
                bad.append(f"{os.path.relpath(p, SITE)}: no such file {target}")
            elif frag and dst.endswith(".html") and frag not in anchors(dst):
                bad.append(f"{os.path.relpath(p, SITE)}: no such anchor {target}")
    return bad


files = site_files()
bl = broken(files)
check(f"every local link / picture of the {len(files)} pages exists, with its #anchor", not bl, bl[:8])
fake = os.path.join(SITE, "concepts", "geometry.html")
bl2 = broken([fake], read=lambda p: ('<a href="../index.html#no-such-anchor">x</a><img src="../../images/none.png">'
                                     '<a href="groups.html">ok</a>') if p == fake else open(p, encoding="utf-8").read())
check("  negative control: a bad anchor and a missing picture are reported, a good link is not",
      len(bl2) == 2 and any("anchor" in x for x in bl2) and any("file" in x for x in bl2), bl2)
ext = set()
for p in files:
    ext |= set(re.findall(r'href="(https?://[^"/]+)', open(p, encoding="utf-8").read()))
check("external links only go to the repository host (no stray domains)",
      ext <= {"https://github.com"}, sorted(ext))

# ─────────────────────────────────────────────── 4
sec("4. nodes")
with open(os.path.join(REPO, "tools", "nodes.json"), encoding="utf-8") as f:
    registry = set(json.load(f))
check(f"every node of the registry ({len(registry)}) has a reference heading", set(site.nodes) == registry,
      sorted(set(site.nodes) ^ registry)[:8])
missing_icon = []
for nid, v in site.nodes.items():
    with open(os.path.join(SITE, *site.out_rel(v["page"]).split("/")), encoding="utf-8") as f:
        page = f.read()
    m = re.search(rf'<h3 id="{v["anchor"]}" class="node"><svg class="ico big"[^>]*><use href="#g-([\w]+)"/>', page)
    if not m or f'<symbol id="g-{m.group(1)}"' not in page:
        missing_icon.append(nid)
check("  each node heading carries its icon, and the page holds that icon's symbol", not missing_icon,
      missing_icon[:8])
with open(os.path.join(SITE, "assets", "search-index.js"), encoding="utf-8") as f:
    js = f.read()
idx = json.loads(re.search(r"window\.PCG_INDEX = (\[.*?\]);\n", js, re.S).group(1))
check("search index: every node, every page", {i["id"] for i in idx if i["k"] == "node"} == registry
      and {i["u"] for i in idx if i["k"] == "page"} == {site.out_rel(p) for p in site.pages})
glyphs = json.loads(re.search(r"window\.PCG_GLYPHS = (\{.*\});", js, re.S).group(1))
check("  every glyph used by the search results is in the index", {i["g"] for i in idx if "g" in i} <= set(glyphs))
check("  negative control: a node missing from the index is noticed",
      {i["id"] for i in idx if i["k"] == "node" and i["id"] != "PCG_Box"} != registry)
with open(os.path.join(DOCS, "_data", "icons.json"), encoding="utf-8") as f:
    icons = json.load(f)
check("icons.json covers exactly the registered nodes (re-run tools/render_doc_icons.mjs after adding nodes)",
      set(icons["nodes"]) == registry, sorted(set(icons["nodes"]) ^ registry)[:8])

# ─────────────────────────────────────────────── 5
sec("5. pictures")
pics = sorted(f[:-4] for f in os.listdir(os.path.join(DOCS, "images", "nodes")) if f.endswith(".png"))
check(f"{len(pics)} node pictures, each named after a registered node", pics and set(pics) <= registry,
      sorted(set(pics) - registry))
shown = [nid for nid in pics
         if f"../../images/nodes/{nid}.png" in open(os.path.join(SITE, *site.out_rel(site.nodes[nid]["page"])
                                                                .split("/")), encoding="utf-8").read()]
check("  every node picture is shown on its node's page", len(shown) == len(pics), sorted(set(pics) - set(shown)))
vol = [n for n in pics if site.nodes[n]["page"] == "reference/volume.md"]
check("  the Volumes & VDB page has pictures for at least 25 nodes", len(vol) >= 25, len(vol))
concepts = sorted(os.listdir(os.path.join(DOCS, "images", "concepts")))
used = []
for p in site.pages:
    with open(os.path.join(DOCS, p), encoding="utf-8") as f:
        used += re.findall(r"images/concepts/([\w.-]+)", f.read())
check("every concept picture is used by a page, and every one used exists",
      set(concepts) == set(used), sorted(set(concepts) ^ set(used)))
check("  negative control: an unused picture is noticed", set(concepts + ["unused.svg"]) != set(used))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
