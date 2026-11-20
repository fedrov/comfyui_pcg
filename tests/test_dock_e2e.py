"""
End-to-end tests for the docked parameter pane (web/pcg_dock.js; Settings -> PCG -> Parameters: "Docked pane", the
default), in the **real ComfyUI frontend** (Playwright + Chromium).

Needs a running ComfyUI with this plugin, its address in PCG_E2E_URL (as test_panel_e2e.py); skipped otherwise.

  · which nodes the pane takes = panel.py's dock_applies (both sides agree), the Wrangles included
  · nodes are compact (title + connectors), their widgets hidden, code boxes out of the page; the example workflows
    load with widgets_values unchanged and no overlap
  · speed: the world tiles graph (833 nodes) loads and pans fast with every node open
  · the pane follows the selection, writes the hidden widgets (what reaches the backend), the Wrangle code editor
    (highlighted, ch() creates a parameter), pin, Delete while typing, node menu back to native widgets, reloading
  · connected parameters: an input row with the parameter's label; while dragging a link, a list of the matching free
    parameters under the node, the drop connects to the row under the pointer (negative controls: no list without a
    drag, none for a link of another type)
"""
import asyncio
import glob
import json
import os
import sys
import tempfile

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))), "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        PKG = _c
        break
sys.path.insert(0, _R)

URL = os.environ.get("PCG_E2E_URL")
try:
    from playwright.async_api import async_playwright
except ImportError:                                     # pragma: no cover
    async_playwright = None

if not URL or async_playwright is None:
    print("  (PCG_E2E_URL not set or playwright not installed, skipping real frontend test)")
    print("\n0/0 passed")
    sys.exit(0)

import fakecomfy                                        # noqa: F401,E402
from comfyui_pcg import NODE_CLASS_MAPPINGS as M       # noqa: E402
from comfyui_pcg.panel import dock_applies, panel_applies  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


HELPERS = """
window.__t = {
  wait: (ms) => new Promise(r => setTimeout(r, ms)),
  pane: () => document.querySelector('.pcgdock'),
  row(label) {
    return [...document.querySelectorAll('.pcgdock .row')].find(
      r => r.querySelector('.lab')?.textContent.trim() === label
        || r.querySelector('.chk span')?.textContent.trim() === label);
  },
  w(n, name) { return n.widgets.find(w => w.name === name); },
  fire(el, type) { el.dispatchEvent(new Event(type, { bubbles: true })); },
  add(type, x = 100, y = 100) {
    const n = LiteGraph.createNode(type); n.pos = [x, y]; app.graph.add(n); return n;
  },
  view() { app.canvas.ds.scale = 1; app.canvas.ds.offset = [0, 0]; app.canvas.setDirty(true, true); },
  screen(p) {
    const c = app.canvas, R = c.canvas.getBoundingClientRect(), q = c.ds.convertOffsetToCanvas(p);
    return [R.left + q[0], R.top + q[1]];
  },
};
"""


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1600, "height": 1000})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: m.type == "error" and "pcg" in m.text.lower() and errs.append(m.text))
        await pg.goto(URL, wait_until="networkidle")
        await pg.wait_for_function("window.app && window.app.graph", timeout=90000)
        await pg.evaluate("app.extensionManager.setting.set('PCG.ParamPanel', 'Docked pane');"
                          "localStorage.removeItem('pcg.dock.pane')")
        await pg.reload(wait_until="networkidle")
        await pg.wait_for_function("window.app && window.app.graph", timeout=90000)
        await pg.wait_for_timeout(2500)
        for _ in range(3):
            await pg.keyboard.press("Escape")
            await pg.wait_for_timeout(200)
        await pg.evaluate("document.querySelectorAll('.p-dialog-mask').forEach(e=>e.remove())")
        await pg.evaluate(HELPERS)

        # ═══════════════════════════════════════ 1. which nodes
        sec("Every PCG node")
        r = await pg.evaluate("""async () => {
          app.graph.clear();
          const types = Object.keys(LiteGraph.registered_node_types).filter(t => t.startsWith('PCG_'));
          let x = 0;
          for (const t of types) { const n = LiteGraph.createNode(t); n.pos = [x, 0]; x += 500; app.graph.add(n); }
          await __t.wait(2500);
          const out = {};
          for (const n of app.graph._nodes) {
            const vis = (n.widgets || []).filter(w => !w.hidden && w.type !== 'pcg-collapsed').map(w => w.type);
            const dom = (n.widgets || []).filter(w => w.element).map(w => w.element.style.display);
            const own = (n.inputs || []).filter(i => !i.widget).length;
            out[n.type] = {docked: !!n._pcgDocked, vis, dom, h: n.size[1], w: n.size[0], own,
                           outs: (n.outputs || []).length, onnode: !!n._pcgPanel};
          }
          app.graph.clear();
          return out;
        }""")
        pcg = {k: v for k, v in r.items() if k in M}
        real = [e for e in errs if "three" not in e]
        check(f"all {len(pcg)} PCG nodes created, no page errors",
              len(pcg) == len([k for k in M if k.startswith("PCG_")]) and not real, real[:2])
        mism = [k for k, v in pcg.items() if v["docked"] != dock_applies(k, M[k].INPUT_TYPES())]
        check("  nodes the pane takes = dock_applies (Python side)", not mism, mism[:5])
        code = [k for k, v in pcg.items() if v["docked"] and not panel_applies(k, M[k].INPUT_TYPES())]
        check("  among them the code-editor nodes the on-node panel leaves alone (the Wrangles)",
              {"PCG_Wrangle", "PCG_COPWrangle", "PCG_VolumeWrangle"} <= set(code), code)
        check("  no on-node panel anywhere", not any(v["onnode"] for v in pcg.values()))
        left = {k: v["vis"] for k, v in pcg.items() if v["docked"] and any(t != "pcg_cop_preview" for t in v["vis"])}
        check("  a taken node keeps no visible widget but the COP thumbnail", not left, list(left.items())[:3])
        dom = [k for k, v in pcg.items() if v["docked"] and any(d != "none" for d in v["dom"])]
        check("  its code box is out of the page (display none)", not dom, dom[:3])
        tall = [(k, v["h"]) for k, v in pcg.items() if v["docked"] and "pcg_cop_preview" not in v["vis"]
                and v["h"] > 20 * max(v["own"], v["outs"], 1) + 30]
        check("  compact: a node without thumbnail is no taller than its connector rows", not tall, tall[:4])

        # ═══════════════════════════════════════ 2. example workflows
        sec("Example workflows: load, round trip, no overlap")
        files = sorted(glob.glob(os.path.join(PKG, "comfyui_pcg", "example_workflows", "*.json")))
        for f in files:
            wf = json.load(open(f, encoding="utf-8"))
            r = await pg.evaluate("""async (wf) => {
              await app.loadGraphData(JSON.parse(JSON.stringify(wf)));
              await __t.wait(1200);
              const ser = app.graph.serialize();
              const by = new Map(ser.nodes.map(n => [n.id, n]));
              const diff = [];
              for (const n of wf.nodes) {
                const s = by.get(n.id);
                if (!s || ['PCG_Viewport', 'MoGeInference'].includes(n.type)) continue;
                if (JSON.stringify(n.widgets_values ?? null) !== JSON.stringify(s.widgets_values ?? null))
                  diff.push(n.type);
              }
              const TH = LiteGraph.NODE_TITLE_HEIGHT;
              const R = app.graph._nodes.map(n => n.flags?.collapsed
                ? [n.pos[0], n.pos[1] - TH, n.pos[0] + (n._collapsed_width || 120), n.pos[1], n.title, true]
                : [n.pos[0], n.pos[1] - TH, n.pos[0] + n.size[0], n.pos[1] + n.size[1], n.title, false]);
              const ov = [];
              for (let i = 0; i < R.length; i++) for (let j = i + 1; j < R.length; j++) {
                const a = R[i], b = R[j];
                if (a[5] && b[5]) continue;
                if (a[0] < b[2] - 2 && b[0] < a[2] - 2 && a[1] < b[3] - 2 && b[1] < a[3] - 2) ov.push([a[4], b[4]]);
              }
              return {diff, ov, docked: app.graph._nodes.filter(n => n._pcgDocked).length};
            }""", wf)
            check(f"{os.path.basename(f)}: widgets_values unchanged, no overlap ({r['docked']} docked)",
                  not r["diff"] and not r["ov"], (r["diff"][:3], r["ov"][:3]))

        # ═══════════════════════════════════════ 3. speed
        sec("Speed: the world tiles graph with every node open")
        wfj = json.load(open(os.path.join(PKG, "comfyui_pcg", "example_workflows", "pcg_prod_world_tiles.json"),
                             encoding="utf-8"))
        for n in wfj["nodes"]:
            n.get("flags", {}).pop("collapsed", None)
        await pg.evaluate("app.graph.clear()")
        t0 = await pg.evaluate("performance.now()")
        await pg.evaluate("async (wf) => { await app.loadGraphData(wf); }", wfj)
        t1 = await pg.evaluate("performance.now()")
        sp = await pg.evaluate("""async () => {
          const c = app.canvas, ns = app.graph._nodes, res = {nodes: ns.length};
          await __t.wait(800);
          res.open = ns.filter(n => !n.flags?.collapsed).length;
          res.docked = ns.filter(n => n._pcgDocked).length;
          res.shownDom = [...document.querySelectorAll('.dom-widget, textarea')].filter(
            e => !e.closest('.pcgdock') && e.offsetParent !== null && getComputedStyle(e).display !== 'none').length;
          c.ds.scale = 0.5; c.ds.offset = [0, 0];
          c.draw(true, true); await new Promise(r => requestAnimationFrame(r));
          const t = performance.now();
          for (let i = 0; i < 30; i++) { c.ds.offset[0] -= 80; c.draw(true, true); await new Promise(r => requestAnimationFrame(r)); }
          res.frame = (performance.now() - t) / 30;
          return res;
        }""")
        check(f"{sp['nodes']} nodes, all open, load in {(t1 - t0) / 1000:.1f} s (13 s with a panel on every node)",
              (t1 - t0) < 6000 and sp["open"] == sp["nodes"] and sp["docked"] > 700, sp)
        check(f"  no parameter DOM on the canvas ({sp['shownDom']} elements); a pan frame takes "
              f"{sp['frame']:.0f} ms", sp["shownDom"] <= 4 and sp["frame"] < 60, sp)

        # ═══════════════════════════════════════ 4. the pane
        sec("The pane follows the selection and writes the widgets")
        await pg.evaluate("app.graph.clear()")
        r = await pg.evaluate("""async () => {
          const res = {};
          const a = __t.add('PCG_Sphere', 100, 100), b = __t.add('PCG_Transform', 500, 100);
          a.connect(0, b, 0);
          __t.view(); await __t.wait(300);
          res.empty = __t.pane().querySelector('.empty')?.textContent || '';
          app.canvas.selectNode(a); await __t.wait(300);
          res.t1 = __t.pane().querySelector('.ttl').textContent;
          app.canvas.selectNode(b); await __t.wait(300);
          res.t2 = __t.pane().querySelector('.ttl').textContent;
          const inp = __t.row('Translate').querySelectorAll('input.num')[1];
          inp.value = '2*3'; __t.fire(inp, 'change');
          res.ty = __t.w(b, 'ty').value;
          const p = await app.graphToPrompt();
          res.prompt = p.output[String(b.id)].inputs.ty;
          // a value changed elsewhere (undo, a reference) shows in the pane
          __t.w(b, 'tz').value = 7; await __t.wait(300);
          res.tz = __t.row('Translate').querySelectorAll('input.num')[2].value;
          // pin: another selection leaves the pane alone
          __t.pane().querySelector('.hb[title^="Pin"]').click();
          app.canvas.selectNode(a); await __t.wait(300);
          res.pinned = __t.pane().querySelector('.ttl').textContent;
          __t.pane().querySelector('.hb[title^="Pin"]').click(); await __t.wait(300);
          res.unpinned = __t.pane().querySelector('.ttl').textContent;
          window.__b = b;
          return res;
        }""")
        check("nothing selected: a hint", "Select a node" in r["empty"], r["empty"])
        check("  selecting a node shows it, selecting another switches", r["t1"] == "Sphere (PCG)"
              and r["t2"] == "Transform (PCG)", (r["t1"], r["t2"]))
        check("  typing 2*3 into Translate Y writes the hidden widget and the prompt", r["ty"] == 6 and r["prompt"] == 6,
              (r["ty"], r["prompt"]))
        check("  a value changed outside shows in the pane", r["tz"] == "7", r["tz"])
        check("  pinned: the pane stays on its node; unpinned it follows again", r["pinned"] == "Transform (PCG)"
              and r["unpinned"] == "Sphere (PCG)", (r["pinned"], r["unpinned"]))

        await pg.evaluate("app.canvas.selectNode(__b)")
        await pg.wait_for_timeout(300)
        await pg.click(".pcgdock .row input.num")
        await pg.keyboard.press("End")
        await pg.keyboard.press("Delete")
        await pg.keyboard.press("Backspace")
        await pg.wait_for_timeout(200)
        alive = await pg.evaluate("!!app.graph.getNodeById(__b.id)")
        check("  Delete / Backspace while typing in the pane do not delete the node", alive)
        await pg.keyboard.press("Escape")

        r = await pg.evaluate("""async () => {
          const b = __b, res = {};
          const opts = []; b.getExtraMenuOptions(app.canvas, opts);
          const it = opts.find(o => o && String(o.content).startsWith('Parameters: native'));
          it.callback(); await __t.wait(300);
          res.native = !b._pcgDocked && b.widgets.filter(w => !w.hidden).length > 5;
          res.msg = __t.pane().querySelector('.empty')?.textContent || '';
          const opts2 = []; b.getExtraMenuOptions(app.canvas, opts2);
          opts2.find(o => o && String(o.content).startsWith('Parameters: docked')).callback(); await __t.wait(300);
          res.back = !!b._pcgDocked && !!__t.row('Translate');
          // reloading the graph (what undo does): the pane finds the same node again
          await app.loadGraphData(app.graph.serialize()); await __t.wait(500);
          res.again = __t.pane().querySelector('.ttl').textContent;
          res.againNode = app.graph.getNodeById(b.id) !== b && !!__t.row('Translate');
          return res;
        }""")
        check("node menu -> native widgets: shown on the node, the pane says so", r["native"] and "native" in r["msg"],
              r)
        check("  and back to the pane", r["back"])
        check("  after the graph is reloaded (undo) the pane shows the same node again",
              r["again"] == "Transform (PCG)" and r["againNode"], r)

        sec("Wrangle: the code editor")
        await pg.evaluate("app.graph.clear()")
        r = await pg.evaluate("""async () => {
          const res = {};
          const w = __t.add('PCG_Wrangle', 100, 100);
          __t.view(); await __t.wait(300);
          res.node = [w.size[0], w.size[1]];
          app.canvas.selectNode(w); await __t.wait(500);
          const ta = __t.pane().querySelector('textarea.codebox');
          res.editor = !!ta && ta.offsetHeight >= 120;
          res.hl = !!ta?.parentElement?.querySelector('pre');
          ta.value = '@P.y += ch("lift") * 2'; __t.fire(ta, 'input'); __t.fire(ta, 'change');
          res.code = __t.w(w, 'code').value;
          await __t.wait(900);
          res.rows = [...__t.pane().querySelectorAll('.row')].map(r => (r.querySelector('.lab')?.textContent || '').trim());
          res.spare = w.widgets.some(x => /lift/i.test(x.name));
          res.spareShown = w.widgets.filter(x => /lift/i.test(x.name) && !x.hidden).length;
          return res;
        }""")
        check("a Wrangle on the canvas is compact; selected, its code is a tall highlighted editor in the pane",
              r["node"][1] < 120 and r["editor"] and r["hl"], r)
        check("  editing writes the code widget", r["code"] == '@P.y += ch("lift") * 2', r["code"])
        check("  ch(\"lift\") creates a parameter: a row in the pane, nothing visible on the node",
              r["spare"] and any("lift" in x.lower() for x in r["rows"]) and r["spareShown"] == 0, r)

        # ═══════════════════════════════════════ 5. connected parameters
        sec("Connected parameters and the drop list")
        await pg.evaluate("app.graph.clear()")
        r = await pg.evaluate("""async () => {
          const res = {};
          const f = __t.add('PrimitiveFloat', 100, 300), g = __t.add('PCG_Sphere', 100, 100);
          const m = __t.add('PCG_Transform', 500, 300);
          __t.view(); await __t.wait(400);
          res.h0 = m.size[1];
          const D = await import('/extensions/comfyui_pcg/pcg_dock.js');
          res.noDrag = D.layoutParams(m, [m.pos[0] + 40, m.pos[1] + m.size[1] + 20]).list.length;
          res.geoDrag = D.layoutParams(m, [m.pos[0] + 40, m.pos[1] + m.size[1] + 20], 'GEOMETRY').list.length;
          res.fltDrag = D.layoutParams(m, [m.pos[0] + 40, m.pos[1] + m.size[1] + 20], 'FLOAT').list.length;
          res.away = D.layoutParams(m, [m.pos[0] + 900, m.pos[1]], 'FLOAT').list.length;
          const ty = m.inputs.findIndex(i => i.widget?.name === 'ty');
          f.connect(0, m, ty); await __t.wait(300);
          res.h1 = m.size[1];
          res.pos = m.inputs[ty].pos;
          res.label = D.paramInputs(m).find(p => p.name === 'ty').label;
          app.canvas.selectNode(m); await __t.wait(300);
          res.lnk = [...__t.row('Translate').querySelectorAll('.lnk')].map(e => e.value || e.textContent);
          app.canvas.deselectAll?.();
          window.__m = m; window.__f = f;
          return {...res, from: __t.screen(f.getOutputPos(0)), over: __t.screen([m.pos[0] + 60, m.pos[1] + 10]),
                  row3: __t.screen([m.pos[0] + 60, m.pos[1] + m.size[1] + 6 + 2.5 * LiteGraph.NODE_SLOT_HEIGHT])};
        }""")
        check("no drag: no list; a GEOMETRY link lists no FLOAT parameter (negative controls)",
              r["noDrag"] == 0 and r["geoDrag"] == 0, (r["noDrag"], r["geoDrag"]))
        check("  a FLOAT link near the node lists its free FLOAT parameters, none when the pointer is away",
              r["fltDrag"] >= 15 and r["away"] == 0, (r["fltDrag"], r["away"]))
        check("  connecting Translate Y adds one input row, labelled, at row 2 (under the geometry input)",
              r["h1"] - r["h0"] in (19, 20, 21, 26) and r["label"] == "Translate Y"
              and abs(r["pos"][1] - 1.7 * 20) < 1, (r["h0"], r["h1"], r["pos"], r["label"]))
        check("  the pane shows ⇠ source for it", any("Float" in x for x in r["lnk"]), r["lnk"])

        await pg.mouse.move(*r["from"])
        await pg.mouse.down()
        await pg.mouse.move(r["from"][0] + 80, r["from"][1], steps=4)
        await pg.mouse.move(*r["over"], steps=8)
        await pg.wait_for_timeout(150)
        await pg.mouse.move(*r["row3"], steps=8)
        await pg.wait_for_timeout(250)
        shown = await pg.evaluate("__m._pcgDockList?.items.map(p => p.name).slice(0, 4)")
        await pg.screenshot(path=os.path.join(tempfile.gettempdir(), "pcg_dock_droplist.png"), clip={"x": 300, "y": 250, "width": 520, "height": 520})
        await pg.mouse.up()
        await pg.wait_for_timeout(300)
        con = await pg.evaluate("__m.inputs.filter(i => i.link != null).map(i => i.widget?.name || i.name)")
        check("real mouse drag: the list appears under the node (Translate X, Z, Rotate ...: Y is taken)",
              shown and shown[:2] == ["tx", "tz"], shown)
        check("  dropped on its third row: Rotate X is connected", "rx" in con and len(con) == 2, con)
        gone = await pg.evaluate("__m._pcgDockList")
        check("  after the drop the list is gone", gone is None)

        for e in errs:
            if "three" not in e:
                print("  ERR", e[:300])
        check("no PCG-related page errors during the whole run", not [e for e in errs if "three" not in e])
        await b.close()


asyncio.run(main())
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
