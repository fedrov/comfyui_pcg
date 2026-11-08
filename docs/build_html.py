"""
Build the HTML version of the documentation (docs/html/) from the Markdown in docs/.

The Markdown stays the single source: this script only converts it, adds a sidebar, a search box (works offline, also
from file://), node icons (docs/_data/icons.json, exported from web/pcg_icons.js by tools/render_doc_icons.mjs) and
light / dark themes. Pictures are referenced where they are (docs/images, docs/examples/images), not copied.

No dependencies beyond the standard library, and the output is deterministic, so tests/test_docs_html.py can check
that docs/html is current.

    python docs/build_html.py            rebuild docs/html (+ docs/index.html, the redirect for GitHub Pages)
    python docs/build_html.py --check    exit 1 if docs/html is stale

Open docs/html/index.html in a browser, or publish the docs/ folder with GitHub Pages
(.github/workflows/pages.yml does that).
"""
from __future__ import annotations

import html
import json
import os
import posixpath
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))       # docs/
REPO = os.path.dirname(HERE)
OUT = os.path.join(HERE, "html")
SITE_TITLE = "comfyui_pcg"

# Navigation: (section title, [pages]); every Markdown page of the docs must appear exactly once
# (test_docs_html.py checks that, so a new page cannot be forgotten).
NAV = [
    ("Start", ["README.md", "getting-started.md", "houdini-users.md"]),
    ("Concepts", ["concepts/geometry.md", "concepts/groups.md", "concepts/parameters.md",
                  "concepts/expressions.md", "concepts/wrangle.md", "concepts/loops-and-time.md",
                  "concepts/images.md", "concepts/viewing-and-export.md", "concepts/wires.md",
                  "concepts/shortcuts.md"]),
    ("Examples", ["examples/README.md", "examples/tutorial_01_first_geometry.md",
                  "examples/tutorial_02_scatter_copy.md", "examples/tutorial_03_attributes_wrangle.md",
                  "examples/tutorial_04_foreach_variations.md", "examples/tutorial_05_cop_texture.md",
                  "examples/tutorial_06_controller.md", "examples/pcg_sop_city_block.md",
                  "examples/pcg_sop_rock_garden.md", "examples/pcg_cop_brick_material.md",
                  "examples/pcg_cop_terrain_maps.md", "examples/pcg_image_to_terrain.md",
                  "examples/pcg_terrain_to_ai_texture.md", "examples/pcg_prod_rock_assets.md",
                  "examples/pcg_prod_modular_city.md", "examples/pcg_prod_material_library.md",
                  "examples/pcg_prod_world_tiles.md"]),
    ("Node reference", ["reference/README.md", "reference/houdini-index.md"]),   # + category pages, below
]
SKIP_DIRS = ("dev", "pcg100", "html", "_data", "images")


def repo_url():
    try:
        with open(os.path.join(REPO, "pyproject.toml"), encoding="utf-8") as f:
            m = re.search(r'^Repository\s*=\s*"([^"]+)"', f.read(), re.M)
        return m.group(1).rstrip("/") if m else ""
    except OSError:
        return ""


def all_pages():
    out = []
    for root, dirs, files in os.walk(HERE):
        rel = os.path.relpath(root, HERE).replace(os.sep, "/")
        if rel != "." and rel.split("/")[0] in SKIP_DIRS:
            continue
        for f in files:
            if f.endswith(".md"):
                out.append(f if rel == "." else f"{rel}/{f}")
    return sorted(out)


def nav():
    """NAV with the reference category pages appended, in the order of the reference index."""
    sections = [(t, list(p)) for t, p in NAV]
    ref = sections[-1][1]
    with open(os.path.join(HERE, "reference", "README.md"), encoding="utf-8") as f:
        for m in re.finditer(r"^## \[[^\]]+\]\(([\w-]+\.md)\)", f.read(), re.M):
            ref.append("reference/" + m.group(1))
    return sections


# ─────────────────────────────────────────────────────────── Markdown -> HTML
def slugify(text, used):
    s = re.sub(r"<[^>]+>", "", text)
    s = re.sub(r"[`*_\[\]()]", "", s)
    s = re.sub(r"\]\([^)]*\)", "", s).strip().lower()
    s = re.sub(r"[^\w\- ]", "", s, flags=re.U).replace(" ", "-")
    base, n = s or "section", 0
    while s in used:
        n += 1
        s = f"{base}-{n}"
    used.add(s)
    return s


class Ctx:
    """Per-page state for the converter."""

    def __init__(self, site, src):
        self.site, self.src = site, src
        self.slugs = set()
        self.toc = []            # (level, id, text)
        self.glyphs = set()      # icons used on the page (one inline sprite per page)
        self.title = None


INLINE_CODE = re.compile(r"(`+)(.+?)\1")
IMG = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
LINK = re.compile(r"\[((?:[^\[\]]|\[[^\]]*\])+)\]\(([^)\s]+)\)")


def inline(text, ctx):
    codes = []

    def keep(m):
        codes.append("<code>" + html.escape(m.group(2).strip() if m.group(1) == "``" else m.group(2),
                                            quote=False) + "</code>")
        return f"\x00{len(codes) - 1}\x00"

    t = INLINE_CODE.sub(keep, text)
    t = html.escape(t, quote=False)

    def img(m):
        src = ctx.site.url(ctx.src, m.group(2))
        return (f'<img src="{html.escape(src)}" alt="{html.escape(m.group(1))}" loading="lazy">')

    t = IMG.sub(img, t)

    def link(m):
        href = ctx.site.url(ctx.src, m.group(2))
        label = m.group(1)
        ico = ""
        node = ctx.site.node_for_link(ctx.src, m.group(2))
        if node:
            ico = ctx.site.icon(node, ctx)
        ext = ' rel="noopener"' if href.startswith("http") else ""
        return f'<a href="{html.escape(href)}"{ext}>{ico}{label}</a>'

    t = LINK.sub(link, t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", t)
    t = re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], t)
    return t


LIST_RE = re.compile(r"^(\s*)([-*+]|\d+\.)\s+(.*)$")


def convert(md, ctx):
    lines = md.replace("\t", "    ").split("\n")
    out = []
    i = 0
    n = len(lines)

    def para(buf):
        txt = " ".join(x.strip() for x in buf)
        if ctx.site.is_chip_paragraph(ctx.src, txt):
            out.append('<div class="chips">' + inline(txt, ctx).replace("</a>, <a", "</a><a") + "</div>")
        else:
            out.append(f"<p>{inline(txt, ctx)}</p>")

    while i < n:
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1
            continue
        # fenced code
        m = re.match(r"^(\s*)(```+|~~~+)\s*([\w+-]*)", line)
        if m:
            fence, lang, ind = m.group(2), m.group(3), len(m.group(1))
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith(fence):
                buf.append(lines[i][ind:] if lines[i][:ind].strip() == "" else lines[i])
                i += 1
            i += 1
            cls = f' class="lang-{lang}"' if lang else ""
            out.append(f"<pre><code{cls}>{html.escape(chr(10).join(buf), quote=False)}</code></pre>")
            continue
        # heading
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if m:
            lvl, text = len(m.group(1)), m.group(2)
            node = None
            # reference pages: "### Name" + <a id="pcg-x"> -> one node heading with its icon
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            am = re.match(r'^<a id="(pcg-[\w-]+)"></a>\s*$', lines[j].strip()) if j < n else None
            if am and lvl == 3:
                hid = am.group(1)
                ctx.slugs.add(hid)
                node = ctx.site.anchor_node.get((ctx.src, hid))
                i = j + 1
            else:
                hid = slugify(text, ctx.slugs)
                i += 1
            if lvl == 1 and ctx.title is None:
                ctx.title = re.sub(r"[`*]", "", text)
            body = inline(text, ctx)
            ico = ctx.site.icon(node, ctx, big=True) if node else ""
            cls = ' class="node"' if node else ""
            if 2 <= lvl <= 3:
                ctx.toc.append((lvl, hid, html.unescape(re.sub(r"<[^>]+>", "", body))))
            anchor = f'<a class="hash" href="#{hid}" aria-label="Link to this section">#</a>'
            out.append(f'<h{lvl} id="{hid}"{cls}>{ico}{body}{anchor}</h{lvl}>')
            continue
        # raw HTML block line
        if re.match(r"^</?[a-zA-Z][\w-]*[^>]*>", s) and not s.startswith("<type>"):
            buf = []
            while i < n and lines[i].strip():
                buf.append(lines[i])
                i += 1
            blk = "\n".join(buf)
            blk = re.sub(r'(src|href)="([^"]+)"', lambda mm: f'{mm.group(1)}="'
                         f'{html.escape(ctx.site.url(ctx.src, mm.group(2)))}"', blk)
            out.append(blk)
            continue
        # horizontal rule
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
            out.append("<hr>")
            i += 1
            continue
        # table
        if s.startswith("|") and i + 1 < n and re.match(r"^\|?\s*:?-{3,}", lines[i + 1].strip()):
            def cells(r):
                r = r.strip()
                r = r[1:] if r.startswith("|") else r
                r = r[:-1] if r.endswith("|") and not r.endswith("\\|") else r
                return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", r)]
            head = cells(line)
            aligns = []
            for c in cells(lines[i + 1]):
                aligns.append("right" if c.endswith(":") and not c.startswith(":") else
                              "center" if c.startswith(":") and c.endswith(":") else "")
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(cells(lines[i]))
                i += 1

            def td(tag, c, k):
                al = f' style="text-align:{aligns[k]}"' if k < len(aligns) and aligns[k] else ""
                return f"<{tag}{al}>{inline(c, ctx)}</{tag}>"
            h = "".join(td("th", c, k) for k, c in enumerate(head))
            b = "".join("<tr>" + "".join(td("td", c, k) for k, c in enumerate(r)) + "</tr>" for r in rows)
            out.append(f'<div class="table"><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>')
            continue
        # blockquote
        if s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append("<blockquote>" + convert("\n".join(buf), ctx) + "</blockquote>")
            continue
        # list
        if LIST_RE.match(line):
            buf = []
            m0 = LIST_RE.match(line)
            ind0, kind0 = len(m0.group(1)), m0.group(2)[0].isdigit()

            def other_list(ln):
                """An item at this list's indent (or less) with the other marker type starts a new list."""
                mm = LIST_RE.match(ln)
                return bool(mm) and len(mm.group(1)) <= ind0 and mm.group(2)[0].isdigit() != kind0
            while i < n:
                cur = lines[i]
                if buf and other_list(cur):
                    break
                if not cur.strip():
                    # a blank line ends the list unless the next line continues it (indented or another item)
                    k = i + 1
                    while k < n and not lines[k].strip():
                        k += 1
                    if k < n and not other_list(lines[k]) and (lines[k].startswith("  ") or LIST_RE.match(lines[k])):
                        buf.append("")
                        i += 1
                        continue
                    break
                if not (LIST_RE.match(cur) or cur.startswith(" ") or buf):
                    break
                if buf and not cur.startswith(" ") and not LIST_RE.match(cur) and not buf[-1]:
                    break
                buf.append(cur)
                i += 1
            out.append(render_list(buf, ctx))
            continue
        # paragraph
        buf = []
        while i < n and lines[i].strip() and not re.match(r"^(#{1,6}\s|```|~~~|\|)", lines[i].strip()) \
                and not (buf and LIST_RE.match(lines[i])):
            buf.append(lines[i])
            i += 1
        para(buf)
    return "\n".join(out)


def render_list(lines, ctx):
    """Lines of one list (items, continuation lines, nested lists) -> <ul>/<ol>."""
    first = LIST_RE.match(lines[0])
    base = len(first.group(1))
    ordered = first.group(2)[0].isdigit()
    items = []
    for ln in lines:
        m = LIST_RE.match(ln)
        if m and len(m.group(1)) == base:
            items.append([m.group(3)])
        elif items:
            items[-1].append(ln[base:] if ln[:base].strip() == "" else ln)
    start = ""
    if ordered:
        num = int(first.group(2)[:-1])
        start = f' start="{num}"' if num != 1 else ""
    parts = []
    for it in items:
        head, rest = it[0], it[1:]
        # continuation lines indented under the item: text joins the item, deeper lists / code become blocks
        k = 0
        textbuf = [head]
        while k < len(rest) and rest[k].strip() and not LIST_RE.match(rest[k]) \
                and not rest[k].strip().startswith(("```", "|")):
            textbuf.append(rest[k].strip())
            k += 1
        body = inline(" ".join(textbuf), ctx)
        sub = rest[k:]
        if any(x.strip() for x in sub):
            ind = min((len(x) - len(x.lstrip()) for x in sub if x.strip()), default=0)
            body += "\n" + convert("\n".join(x[ind:] for x in sub), ctx)
        parts.append(f"<li>{body}</li>")
    tag = "ol" if ordered else "ul"
    return f"<{tag}{start}>" + "".join(parts) + f"</{tag}>"


# ─────────────────────────────────────────────────────────── the site
class Site:
    def __init__(self):
        self.repo = repo_url()
        self.pages = all_pages()
        self.nav = nav()
        with open(os.path.join(HERE, "_data", "icons.json"), encoding="utf-8") as f:
            self.icons = json.load(f)
        # anchors of the reference pages -> node ids ("reference/volume.md", "pcg-vdb") -> "PCG_VDB"
        self.anchor_node = {}
        self.nodes = {}           # node id -> {name, page, anchor, summary, houdini}
        for p in self.pages:
            if not p.startswith("reference/") or p in ("reference/README.md", "reference/houdini-index.md"):
                continue
            with open(os.path.join(HERE, p), encoding="utf-8") as f:
                md = f.read()
            for m in re.finditer(r'^### (.+)\n\n<a id="(pcg-[\w-]+)"></a>\n\n`(PCG_\w+)` · ([^\n]*)\n\n([^\n]*)',
                                 md, re.M):
                name, anchor, nid, meta, summary = m.groups()
                self.anchor_node[(p, anchor)] = nid
                hou = re.search(r"Houdini: (.+)$", meta)
                self.nodes[nid] = {"name": name, "page": p, "anchor": anchor, "summary": summary.strip(),
                                   "houdini": hou.group(1).strip() if hou else ""}

    # links
    def out_rel(self, page):
        return page[:-3] + ".html" if not page.endswith("README.md") else page[:-9] + "index.html"

    def resolve(self, src, target):
        """target as written in src -> (docs-relative path or None, fragment, external url or None)."""
        if re.match(r"^[a-z]+:", target) or target.startswith("//"):
            return None, "", target
        path, _, frag = target.partition("#")
        if not path:
            return src, frag, None
        full = posixpath.normpath(posixpath.join(posixpath.dirname(src), path))
        return full, frag, None

    def url(self, src, target):
        page, frag, ext = self.resolve(src, target)
        if ext:
            return ext
        here = posixpath.dirname(self.out_rel(src))
        f = f"#{frag}" if frag else ""
        if page == src:
            return f or "#"
        if page.endswith(".md") and page in self.pages:
            return posixpath.relpath(self.out_rel(page), here or ".") + f
        if page.startswith("../") or page == "..":
            # outside docs/: the repository on GitHub (the docs site is only the docs folder)
            rest = posixpath.normpath(page[3:]) if page != ".." else ""
            kind = "tree" if not os.path.isfile(os.path.join(REPO, rest)) else "blob"
            return f"{self.repo}/{kind}/main/{rest}{f}" if self.repo else target
        # a file inside docs/ (pictures): relative to the html file, which lives under docs/html/
        return posixpath.relpath("../" + page, here or ".") + f

    def node_for_link(self, src, target):
        page, frag, ext = self.resolve(src, target)
        if ext or not frag.startswith("pcg-"):
            return None
        return self.anchor_node.get((page, frag))

    def is_chip_paragraph(self, src, txt):
        """The reference index lists nodes as "[A](x.md#pcg-a), [B](x.md#pcg-b), ..." -> a grid of chips."""
        return src == "reference/README.md" and bool(re.fullmatch(r"(\[[^\]]+\]\([\w./-]+#pcg-[\w-]+\)(, )?)+",
                                                                   txt))

    def icon(self, node, ctx, big=False):
        glyph, color = self.icons["nodes"].get(node, ("transform", "#999"))
        ctx.glyphs.add(glyph)
        cls = "ico big" if big else "ico"
        return (f'<svg class="{cls}" style="color:{color}" viewBox="0 0 32 32" aria-hidden="true">'
                f'<use href="#g-{glyph}"/></svg>')

    def sprite(self, glyphs):
        if not glyphs:
            return ""
        sym = "".join(f'<symbol id="g-{g}" viewBox="0 0 32 32">{self.icons["glyphs"][g]}</symbol>'
                      for g in sorted(glyphs) if g in self.icons["glyphs"])
        return f'<svg class="sprite" aria-hidden="true">{sym}</svg>'

    # pages
    def titles(self):
        t = {}
        for p in self.pages:
            with open(os.path.join(HERE, p), encoding="utf-8") as f:
                m = re.search(r"^# (.+)$", f.read(), re.M)
            t[p] = re.sub(r"[`*]", "", m.group(1)).strip() if m else p
        return t

    def render(self, page, titles):
        with open(os.path.join(HERE, page), encoding="utf-8") as f:
            md = f.read()
        ctx = Ctx(self, page)
        body = convert(md, ctx)
        out = self.out_rel(page)
        here = posixpath.dirname(out)
        root = posixpath.relpath(".", here or ".")
        rootp = "" if root == "." else root + "/"

        navh = []
        for sec, items in self.nav:
            lis = []
            for p in items:
                cur = ' class="current"' if p == page else ""
                label = titles[p]
                if p.startswith("reference/") and p not in ("reference/README.md", "reference/houdini-index.md"):
                    cnt = sum(1 for v in self.nodes.values() if v["page"] == p)
                    label = f'{html.escape(label)} <span class="count">{cnt}</span>'
                else:
                    label = html.escape(label)
                lis.append(f'<li{cur}><a href="{posixpath.relpath(self.out_rel(p), here or ".")}">{label}</a></li>')
            navh.append(f'<div class="navsec"><div class="navtitle">{sec}</div><ul>{"".join(lis)}</ul></div>')

        toc = ""
        entries = [(lv, i, t) for lv, i, t in ctx.toc if not (page.startswith("reference/") and lv == 2
                                                               and t in ("Contents", "Nodes"))]
        if len(entries) >= 2:
            toc = ('<nav class="toc" aria-label="On this page"><div class="toctitle">On this page</div><ul>'
                   + "".join(f'<li class="l{lv}"><a href="#{i}">{html.escape(t)}</a></li>' for lv, i, t in entries)
                   + "</ul></nav>")

        # previous / next in navigation order
        flat = [p for _, items in self.nav for p in items]
        k = flat.index(page) if page in flat else -1
        pn = ""
        if k >= 0:
            prv = flat[k - 1] if k > 0 else None
            nxt = flat[k + 1] if k + 1 < len(flat) else None
            a = (f'<a class="prev" href="{posixpath.relpath(self.out_rel(prv), here or ".")}">'
                 f'<span>Previous</span>{html.escape(titles[prv])}</a>') if prv else "<span></span>"
            b = (f'<a class="next" href="{posixpath.relpath(self.out_rel(nxt), here or ".")}">'
                 f'<span>Next</span>{html.escape(titles[nxt])}</a>') if nxt else "<span></span>"
            pn = f'<nav class="pagenav">{a}{b}</nav>'

        src_link = f"{self.repo}/blob/main/docs/{page}" if self.repo else ""
        edit = f'<a class="src" href="{src_link}" rel="noopener">Markdown source</a>' if src_link else ""
        title = ctx.title or titles[page]
        full_title = SITE_TITLE if page == "README.md" else f"{title} · {SITE_TITLE}"
        return out, PAGE.format(
            title=html.escape(full_title), root=rootp, nav="".join(navh), body=body, toc=toc, pagenav=pn,
            sprite=self.sprite(ctx.glyphs), edit=edit, home=posixpath.relpath("index.html", here or "."),
            logo=posixpath.relpath("../images/icon.png", here or "."))

    def search_index(self, titles):
        items = []
        for p in self.pages:
            items.append({"t": titles[p], "u": self.out_rel(p), "k": "page"})
        for nid in sorted(self.nodes):
            v = self.nodes[nid]
            glyph, color = self.icons["nodes"].get(nid, ("transform", "#999"))
            items.append({"t": v["name"], "u": f'{self.out_rel(v["page"])}#{v["anchor"]}', "k": "node",
                          "id": nid, "s": v["summary"], "h": v["houdini"], "g": glyph, "c": color})
        for p in self.pages:
            if p.startswith("reference/"):
                continue
            with open(os.path.join(HERE, p), encoding="utf-8") as f:
                md = f.read()
            used = set()
            infence = False
            for ln in md.split("\n"):
                if ln.strip().startswith(("```", "~~~")):
                    infence = not infence
                m = None if infence else re.match(r"^(##|###) (.+)$", ln)
                if m:
                    text = m.group(2).strip()
                    sid = slugify(text, used)
                    items.append({"t": re.sub(r"[`*]", "", text), "u": f"{self.out_rel(p)}#{sid}", "k": "section",
                                  "p": titles[p]})
                elif ln.startswith("# "):
                    slugify(ln[2:].strip(), used)
        glyphs = sorted({it["g"] for it in items if "g" in it})
        sym = {g: self.icons["glyphs"][g] for g in glyphs}
        return ("// Generated by docs/build_html.py\nwindow.PCG_INDEX = "
                + json.dumps(items, ensure_ascii=False, separators=(",", ":"))
                + ";\nwindow.PCG_GLYPHS = " + json.dumps(sym, separators=(",", ":")) + ";\n")


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="icon" href="{logo}">
<link rel="stylesheet" href="{root}assets/style.css">
<script>try{{var t=localStorage.getItem("pcg-docs-theme");if(t)document.documentElement.dataset.theme=t;}}catch(e){{}}</script>
</head>
<body>
{sprite}
<header class="top">
  <button class="menu" aria-label="Menu" onclick="document.body.classList.toggle('navopen')">&#9776;</button>
  <a class="brand" href="{home}"><img src="{logo}" alt="">comfyui_pcg <span>docs</span></a>
  <div class="search"><input id="q" type="search" placeholder="Search nodes and pages  ( / )" autocomplete="off"
    aria-label="Search"><div id="results" role="listbox"></div></div>
  <button class="theme" aria-label="Toggle light / dark" title="Toggle light / dark">&#9680;</button>
</header>
<div class="layout">
  <aside class="side"><nav aria-label="Documentation">{nav}</nav></aside>
  <main class="content">
    <article>
{body}
    </article>
    {pagenav}
    <footer>{edit}<span>Generated from the Markdown in docs/ by build_html.py</span></footer>
  </main>
  {toc}
</div>
<script src="{root}assets/search-index.js"></script>
<script src="{root}assets/site.js"></script>
</body>
</html>
"""


def build(dst):
    site = Site()
    titles = site.titles()
    listed = [p for _, items in site.nav for p in items]
    files = {}
    for p in site.pages:
        out, text = site.render(p, titles)
        files[out] = text
    files["assets/search-index.js"] = site.search_index(titles)
    with open(os.path.join(HERE, "_data", "site", "style.css"), encoding="utf-8") as f:
        files["assets/style.css"] = f.read()
    with open(os.path.join(HERE, "_data", "site", "site.js"), encoding="utf-8") as f:
        files["assets/site.js"] = f.read()
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    for rel, text in files.items():
        path = os.path.join(dst, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    missing = sorted(set(site.pages) - set(listed))
    return files, missing


REDIRECT = """<!doctype html>
<meta charset="utf-8">
<title>comfyui_pcg documentation</title>
<meta http-equiv="refresh" content="0; url=html/index.html">
<link rel="canonical" href="html/index.html">
<a href="html/index.html">comfyui_pcg documentation</a>
"""


def main(argv):
    check = "--check" in argv
    if check:
        tmp = tempfile.mkdtemp(prefix="pcghtml-")
        try:
            files, missing = build(os.path.join(tmp, "html"))
            stale = []
            for rel, text in files.items():
                p = os.path.join(OUT, *rel.split("/"))
                try:
                    with open(p, encoding="utf-8") as f:
                        if f.read() != text:
                            stale.append(rel)
                except OSError:
                    stale.append(rel)
            extra = []
            for root, _, fs in os.walk(OUT):
                for f in fs:
                    rel = os.path.relpath(os.path.join(root, f), OUT).replace(os.sep, "/")
                    if rel not in files:
                        extra.append(rel)
            try:
                with open(os.path.join(HERE, "index.html"), encoding="utf-8") as f:
                    if f.read() != REDIRECT:
                        stale.append("../index.html")
            except OSError:
                stale.append("../index.html")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if stale or extra or missing:
            print("docs/html is stale; run python docs/build_html.py")
            for x in stale[:20]:
                print("  changed:", x)
            for x in extra[:20]:
                print("  extra:", x)
            for x in missing:
                print("  not in the navigation:", x)
            return 1
        print(f"docs/html is current ({len(files)} files)")
        return 0
    files, missing = build(OUT)
    with open(os.path.join(HERE, "index.html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(REDIRECT)
    print(f"{len(files)} files -> {OUT}")
    for x in missing:
        print("  WARNING: not in the navigation:", x)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
