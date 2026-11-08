"""
End-to-end tests for the parameter panel (pcg84): run inside the **real ComfyUI frontend** (Playwright + Chromium).

Needs a running ComfyUI (with this plugin installed), with its address in the environment variable PCG_E2E_URL, e.g.
    PCG_E2E_URL=http://127.0.0.1:8188 python test_panel_e2e.py
If it's not set or playwright isn't installed, skip (return 0). In the sandbox it ran against the ComfyUI source + the same frontend
package version as on the user's machine (comfyui-frontend-package 1.47.11).

What it checks is everything the jsdom unit test (test_panel.mjs) can't -- real layout, real DOM widgets, real serialization:
  · every PCG node can be created without errors; which nodes switch to the panel = panel.py's panel_applies (both sides agree)
  · panel height = panel.py's estimate (error ≤ 5%), which make_workflows relies on for layout
  · after loading the ten example workflows widgets_values round-trip unchanged, nodes don't overlap
  · interaction: typing, value scrubbing, switching modes in a dropdown (unrelated rows hide, the node shrinks accordingly), toggles, colour picking, ramp add point /
    drag point / delete point, string vectors, the group name ▾ menu, right-click to switch back to native and back again; changed values make it into the workflow and
    the prompt submitted to the backend
"""
import asyncio
import glob
import json
import os
import sys

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
from comfyui_pcg.panel import panel_applies, estimate_panel_height  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


# Small in-page helpers: create nodes, find the control of a parameter in the panel
HELPERS = """
window.__t = {
  add(type, x = 100, y = 100) {
    for (const o of [...app.graph._nodes]) o.pos = [o.pos[0] + 4000, o.pos[1]];
    const n = LiteGraph.createNode(type);
    n.pos = [x, y];
    app.graph.add(n);
    app.canvas.ds.scale = 1; app.canvas.ds.offset = [0, 0];
    return n;
  },
  wait: (ms) => new Promise(r => setTimeout(r, ms)),
  row(n, label) {
    return [...n._pcgPanel.inner.querySelectorAll('.row')].find(
      r => r.querySelector('.lab')?.textContent.trim() === label
        || r.querySelector('.chk span')?.textContent.trim() === label);
  },
  visible(el) { return !!el && !el.closest('.hidden') && el.offsetParent !== null; },
  w(n, name) { return n.widgets.find(w => w.name === name); },
  fire(el, type) { el.dispatchEvent(new Event(type, { bubbles: true })); },
};
"""


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1600, "height": 1100})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: m.type == "error" and "pcg" in m.text.lower()
              and errs.append(m.text))
        await pg.goto(URL, wait_until="networkidle")
        await pg.wait_for_function("window.app && window.app.graph", timeout=90000)
        await pg.wait_for_timeout(2500)
        for _ in range(3):
            await pg.keyboard.press("Escape")
            await pg.wait_for_timeout(200)
        await pg.evaluate("document.querySelectorAll('.p-dialog-mask').forEach(e=>e.remove())")
        await pg.evaluate(HELPERS)

        # ═══════════════════════════════════════ 1. Every node
        sec("Every PCG node")
        r = await pg.evaluate("""async () => {
          app.graph.clear();
          const types = Object.keys(LiteGraph.registered_node_types).filter(t => t.startsWith('PCG_'));
          let x = 0;
          for (const t of types) { const n = LiteGraph.createNode(t); n.pos = [x, 0]; x += 500; app.graph.add(n); }
          await __t.wait(3000);
          const out = {};
          for (const n of app.graph._nodes)
            out[n.type] = {panel: !!n._pcgPanel, h: n._pcgPanel?.height ?? null, w: n.size[0]};
          app.graph.clear();
          return out;
        }""")
        pcg = {k: v for k, v in r.items() if k in M}
        real = [e for e in errs if "three" not in e]   # in the sandbox the 3D viewport's CDN is unreachable, not counted
        check(f"all {len(pcg)} PCG nodes created, no page errors",
              len(pcg) == len([k for k in M if k.startswith("PCG_")]) and not real, real[:2])
        mism = [k for k, v in pcg.items() if v["panel"] != panel_applies(k, M[k].INPUT_TYPES())]
        check("  nodes switched to the panel = panel_applies (Python side)", not mism, mism[:5])
        check("  most nodes switched to the panel", sum(v["panel"] for v in pcg.values()) > 0.9 * len(pcg),
              sum(v["panel"] for v in pcg.values()))
        bad = []
        for k, v in pcg.items():
            if not v["panel"]:
                continue
            e = estimate_panel_height(k, M[k].INPUT_TYPES(), width=v["w"])
            if abs(v["h"] - e) > max(6, 0.05 * v["h"]):
                bad.append((k, v["h"], e))
        check("  panel height = panel.py's estimate (error ≤ 5%, used by make_workflows for layout)", not bad, bad[:5])

        # ═══════════════════════════════════════ 2. Example workflows
        sec("Example workflows: load, round trip, no overlap")
        files = sorted(glob.glob(os.path.join(PKG, "comfyui_pcg", "example_workflows", "*.json")))
        for f in files:
            wf = json.load(open(f, encoding="utf-8"))
            r = await pg.evaluate("""async (wf) => {
              await app.loadGraphData(JSON.parse(JSON.stringify(wf)));
              await __t.wait(1500);
              const ser = app.graph.serialize();
              const by = new Map(ser.nodes.map(n => [n.id, n]));
              const diff = [];
              for (const n of wf.nodes) {
                const s = by.get(n.id);
                // nodes to which frontend extensions add their own widgets (3D viewport / MoGe stub) are out of scope for this test
                if (!s || ['PCG_Viewport', 'MoGeInference'].includes(n.type)) continue;
                if (JSON.stringify(n.widgets_values ?? null) !== JSON.stringify(s.widgets_values ?? null))
                  diff.push(n.type);
              }
              const TH = LiteGraph.NODE_TITLE_HEIGHT;
              const R = app.graph._nodes.map(n => [n.pos[0], n.pos[1] - TH, n.pos[0] + n.size[0], n.pos[1] + n.size[1], n.title]);
              const ov = [];
              for (let i = 0; i < R.length; i++) for (let j = i + 1; j < R.length; j++) {
                const a = R[i], b = R[j];
                if (a[0] < b[2] - 2 && b[0] < a[2] - 2 && a[1] < b[3] - 2 && b[1] < a[3] - 2) ov.push([a[4], b[4]]);
              }
              const panels = app.graph._nodes.filter(n => n._pcgPanel).length;
              return {diff, ov, panels};
            }""", wf)
            check(f"{os.path.basename(f)}: widgets_values round-trip unchanged, nodes don't overlap ({r['panels']} panels)",
                  not r["diff"] and not r["ov"], (r["diff"][:3], r["ov"][:3]))

        # ═══════════════════════════════════════ 3. Interaction
        sec("Interaction: Color")
        await pg.evaluate("app.graph.clear()")
        r = await pg.evaluate("""async () => {
          const n = __t.add('PCG_Color'); await __t.wait(400);
          const P = n._pcgPanel, res = {};
          res.labels = [...P.inner.querySelectorAll('.row')].filter(__t.visible).map(r => r.querySelector('.lab').textContent.trim() || r.querySelector('.chk span')?.textContent.trim());
          res.h0 = n.size[1];
          // switch the dropdown to Ramp from Attribute
          const sel = __t.row(n, 'Color Type').querySelector('select');
          sel.value = 'ramp_by_attribute'; __t.fire(sel, 'change'); await __t.wait(200);
          res.mode = __t.w(n, 'mode').value;
          res.labels2 = [...P.inner.querySelectorAll('.row')].filter(__t.visible).map(r => r.querySelector('.lab').textContent.trim() || r.querySelector('.chk span')?.textContent.trim());
          res.h1 = n.size[1];
          // Range is greyed out while Compute Range is on; editable once it's off
          res.rangeDis0 = __t.row(n, 'Range').classList.contains('dis');
          const cb = __t.row(n, 'Compute Range').querySelector('input');
          cb.click(); await __t.wait(100);
          res.auto = __t.w(n, 'auto_range').value;
          res.rangeDis1 = __t.row(n, 'Range').classList.contains('dis');
          // typing: in_max = 2*5
          const inp = __t.row(n, 'Range').querySelectorAll('input.num')[1];
          inp.value = '2*5'; __t.fire(inp, 'change');
          res.inmax = __t.w(n, 'in_max').value;
          // ramp: click the middle of the colour bar to add a point, then delete it
          const cv = __t.row(n, 'Attribute Ramp').querySelector('canvas');
          const rc = cv.getBoundingClientRect();
          cv.dispatchEvent(new PointerEvent('pointerdown', {clientX: rc.left + rc.width * 0.25, clientY: rc.top + 5, bubbles: true}));
          window.dispatchEvent(new PointerEvent('pointerup', {}));     // pcg97: after adding, the point is dragged straight away; written only on release
          res.ramp1 = __t.w(n, 'ramp').value;
          __t.row(n, 'Attribute Ramp').querySelector('button.btn').click();
          res.ramp2 = __t.w(n, 'ramp').value;
          // drag the first point to 0.1
          const key = __t.row(n, 'Attribute Ramp').querySelector('.key');
          const kr = key.parentElement.getBoundingClientRect();
          key.dispatchEvent(new PointerEvent('pointerdown', {clientX: kr.left, clientY: kr.top, bubbles: true}));
          window.dispatchEvent(new PointerEvent('pointermove', {clientX: kr.left + kr.width * 0.1, clientY: kr.top}));
          window.dispatchEvent(new PointerEvent('pointerup', {clientX: kr.left + kr.width * 0.1, clientY: kr.top}));
          res.ramp3 = __t.w(n, 'ramp').value;
          // the interpolation dropdown inside the ramp editor
          const isel = __t.row(n, 'Attribute Ramp').querySelector('select');
          isel.value = 'smooth'; __t.fire(isel, 'change');
          res.interp = __t.w(n, 'ramp_mode').value;
          // back to constant, the colour picker writes r g b
          sel.value = 'constant'; __t.fire(sel, 'change'); await __t.wait(100);
          const pick = __t.row(n, 'Color').querySelector('input[type=color]');
          pick.value = '#ff8000'; __t.fire(pick, 'input');
          res.rgb = ['r','g','b'].map(k => __t.w(n, k).value);
          res.swatch = getComputedStyle(__t.row(n, 'Color').querySelector('.swatch')).backgroundColor;
          // dragging on a number field = value scrubbing
          const g = __t.row(n, 'Color').querySelectorAll('input.num')[1];
          const gr = g.getBoundingClientRect();
          g.dispatchEvent(new PointerEvent('pointerdown', {clientX: gr.left + 5, clientY: gr.top + 5, button: 0, bubbles: true}));
          window.dispatchEvent(new PointerEvent('pointermove', {clientX: gr.left + 45, clientY: gr.top + 5}));
          window.dispatchEvent(new PointerEvent('pointerup', {clientX: gr.left + 45, clientY: gr.top + 5}));
          res.scrub = __t.w(n, 'g').value;
          await __t.wait(100);
          res.h2 = n.size[1];
          const prompt = await app.graphToPrompt();
          const mine = Object.values(prompt.output).find(o => o.class_type === 'PCG_Color');
          res.prompt = mine && {r: mine.inputs.r, in_max: mine.inputs.in_max, ramp: mine.inputs.ramp, ramp_mode: mine.inputs.ramp_mode};
          res.wv = app.graph.serialize().nodes.find(x => x.type === 'PCG_Color').widgets_values;
          return res;
        }""")
        check("default (Constant): Group / Class / Color Type / Color / Output Attribute, the rest hidden",
              r["labels"] == ["Group", "Class", "Color Type", "Color", "Output Attribute"],
              r["labels"])
        check("  dropdown switched to Ramp from Attribute: Color row hides, Attribute / Range / Ramp appear, node grows taller",
              r["mode"] == "ramp_by_attribute" and "Color" not in r["labels2"]
              and {"Attribute", "Compute Range", "Range", "Attribute Ramp"} <= set(r["labels2"])
              and r["h1"] > r["h0"] + 100, (r["labels2"], r["h0"], r["h1"]))
        check("  Range greyed out while Compute Range is on, editable once off; typing 2*5 gives 10",
              r["rangeDis0"] and not r["rangeDis1"] and r["auto"] is False and r["inmax"] == 10)
        check("  ramp: click the colour bar to add a point (4), delete it back to 3; drag the first point to around 0.1",
              len(r["ramp1"].split()) == 4 and len(r["ramp2"].split()) == 3
              and abs(float(r["ramp3"].split()[0].split(":")[0]) - 0.1) < 0.02,
              (r["ramp1"], r["ramp2"], r["ramp3"]))
        check("  the interpolation dropdown in the ramp editor writes ramp_mode", r["interp"] == "smooth")
        # The frontend's FLOAT widget rounds to its step (0.01 -> two decimals), 128/255 lands on 0.5 -- same as the native widget
        check("  colour picker #ff8000 -> r g b = 1, 0.5, 0 (frontend rounds to the step); swatch follows",
              r["rgb"] == [1, 0.5, 0] and r["swatch"] == "rgb(255, 128, 0)", (r["rgb"], r["swatch"]))
        check("  dragging 40 px right on a number field = scrubbing (step 0.01 × 20)",
              abs(r["scrub"] - 0.7) < 1e-9, r["scrub"])
        check("  switching back to Constant restores the original node height", abs(r["h2"] - r["h0"]) <= 2, (r["h0"], r["h2"]))
        check("  changed values made it into the prompt submitted to the backend", r["prompt"] and r["prompt"]["r"] == 1
              and r["prompt"]["in_max"] == 10 and r["prompt"]["ramp_mode"] == "smooth", r["prompt"])
        check("  and into the workflow (widgets_values are still the native 20)",
              len(r["wv"]) == 20 and r["wv"][12] == 10, r["wv"])

        sec("Interaction: section toggles, tabs, toggle + value, string vectors, group name menu, switching back to native")
        r = await pg.evaluate("""async () => {
          const res = {};
          const n = __t.add('PCG_Scatter'); await __t.wait(400);
          const P = n._pcgPanel;
          const secs = [...P.inner.querySelectorAll('.sec')];
          const relaxTab = [...P.inner.querySelectorAll('.tab')].find(t => t.textContent === 'Relax');
          relaxTab.click(); await __t.wait(50);
          res.tabOn = relaxTab.classList.contains('on');
          // toggle + value: Force Total Count off -> the Count field greys out, Density Scale editable
          const ftc = __t.row(n, 'Force Total Count');
          [...P.inner.querySelectorAll('.tab')][0].click(); await __t.wait(50);
          const box = __t.row(n, 'Force Total Count')?.querySelector('input[type=checkbox]');
          res.hasToggleRow = !!box;
          if (box) { box.click(); await __t.wait(50); }
          res.force = __t.w(n, 'force_total_count').value;
          // section header toggle
          const dsec = secs.find(s => s.textContent.includes('Density Attributes'));
          const g = dsec.querySelector('.sechd input');
          g.click(); await __t.wait(50);
          res.useDensity = __t.w(n, 'use_density').value;
          res.secOpen = !dsec.classList.contains('closed');
          // string vector: COP Pattern's Tile Count "8 8"
          const m = __t.add('PCG_COPPattern'); await __t.wait(400);
          const kinds = m._pcgPanel.inner.querySelectorAll('select')[0];
          kinds.value = 'tile'; __t.fire(kinds, 'change'); await __t.wait(50);
          const tc = __t.row(m, 'Tile Count') || [...m._pcgPanel.inner.querySelectorAll('.row')].find(r => r.textContent.includes('Count'));
          const f = tc.querySelectorAll('input.num');
          f[1].value = '12'; __t.fire(f[1], 'change');
          res.counts = __t.w(m, 'counts').value;
          // group name ▾ menu: shows a hint when upstream hasn't run
          const t = __t.add('PCG_Transform'); await __t.wait(400);
          __t.row(t, 'Group').querySelector('button').click(); await __t.wait(100);
          res.menu = [...document.querySelectorAll('.litecontextmenu .litemenu-entry')].map(e => e.textContent).slice(0, 3);
          document.querySelectorAll('.litecontextmenu').forEach(e => e.remove());
          // switch back to native widgets via the context menu, then back to the panel
          const opts = [];
          t.getExtraMenuOptions(app.canvas, opts);
          const item = opts.find(o => o && String(o.content).includes('Parameter panel'));
          const before = t.widgets.length;
          item.callback(); await __t.wait(100);
          res.native = {panel: !!t._pcgPanel, types: t.widgets.map(w => w.type).slice(0, 3), prop: t.properties.pcg_native_panel, n: t.widgets.length, before};
          const opts2 = []; t.getExtraMenuOptions(app.canvas, opts2);
          opts2.find(o => o && String(o.content).includes('Parameter panel')).callback(); await __t.wait(100);
          res.back = {panel: !!t._pcgPanel, prop: t.properties.pcg_native_panel};
          return res;
        }""")
        check("tab switching", r["tabOn"])
        check("  toggle + value row: clicking the toggle writes force_total_count", r["hasToggleRow"] and r["force"] is False,
              r)
        check("  section header toggle writes use_density, the section expands when on", r["useDensity"] is True and r["secOpen"])
        check("  string vector: change Tile Count's second field to 12 -> counts = '8 12'", r["counts"] == "8 12",
              r["counts"])
        check("  group name ▾: when upstream hasn't run, the menu says to run it once first", r["menu"] and "Upstream has not run yet" in r["menu"][0],
              r["menu"])
        check("  right-click back to native: native widgets shown again, panel removed, remembered in node properties; and back again",
              not r["native"]["panel"] and r["native"]["types"][0] != "pcg-collapsed"
              and r["native"]["prop"] is True and r["native"]["n"] == r["native"]["before"] - 1
              and r["back"]["panel"] and r["back"]["prop"] is None, r)

        sec("Group name ▾: lists the actual groups once upstream has really run")
        r = await pg.evaluate("""async () => {
          app.graph.clear();
          const box = __t.add('PCG_Box', 100, 100);
          const gc = __t.add('PCG_GroupCreate', 500, 100);
          const tr = __t.add('PCG_Transform', 900, 100);
          const ex = __t.add('PCG_ExportMesh', 1300, 100);   // need an output node, otherwise nothing runs
          box.connect(0, gc, 0); gc.connect(0, tr, 0); tr.connect(0, ex, 0);
          __t.w(ex, 'filename').value = 'pcg_e2e/box';
          // group name includes the time: running the same graph a second time on the same server hits the cache entirely and doesn't execute, leaving ▾ nothing to list
          __t.w(gc, 'name').value = 'e2e_top' + (Date.now() % 100000);
          __t.w(gc, 'cls').value = 'prim';
          await __t.wait(300);
          await app.queuePrompt(0, 1);
          for (let i = 0; i < 100; i++) {
            await __t.wait(200);
            const q = await (await fetch('/queue')).json();
            if (!q.queue_running.length && !q.queue_pending.length) break;
          }
          await __t.wait(500);
          __t.row(tr, 'Group').querySelector('button').click(); await __t.wait(100);
          const items = [...document.querySelectorAll('.litecontextmenu .litemenu-entry')].map(e => e.textContent);
          const hit = [...document.querySelectorAll('.litecontextmenu .litemenu-entry')].find(e => e.textContent.includes('e2e_top'));
          hit?.dispatchEvent(new MouseEvent('click', {bubbles: true}));
          await __t.wait(100);
          document.querySelectorAll('.litecontextmenu').forEach(e => e.remove());
          return {items, val: __t.w(tr, 'group').value};
        }""")
        check("Box -> Group Create (e2e_top) -> Transform run once, Transform's ▾ lists prim: e2e_top, clicking it writes it in",
              any("e2e_top" in x for x in r["items"]) and r["val"].startswith("e2e_top"), r)

        # ═══════════════════════════════════════ Parameter linking (pcg85)
        sec("Parameter linking: a wire dropped on a field connects that parameter; right-click Copy Parameter / Paste Relative References")
        pts = await pg.evaluate("""async () => {
          app.graph.clear();
          // not using __t.add: it moves existing nodes away (to make room for single-node tests)
          const mk = (ty, x, y) => { const n = LiteGraph.createNode(ty); n.pos = [x, y]; app.graph.add(n); return n; };
          const v = mk('PCG_Value', 100, 200);
          const t = mk('PCG_Transform', 600, 150);
          app.canvas.ds.scale = 1; app.canvas.ds.offset = [0, 0];
          await __t.wait(800); app.canvas.setDirty(true, true); app.canvas.draw(true, true);
          const rect = app.canvas.canvas.getBoundingClientRect();
          const o = v.getConnectionPos(false, 0);
          const c = (n) => { const b = t._pcgPanel.inner.querySelector(`[data-w="${n}"]`).getBoundingClientRect();
                             return [b.left + b.width / 2, b.top + b.height / 2]; };
          const lab = __t.row(t, 'Scale').querySelector('.lab').getBoundingClientRect();
          return {out: [o[0] + rect.left, o[1] + rect.top], ty: c('ty'),
                  scale: [lab.left + 20, lab.top + lab.height / 2]};
        }""")

        async def drag(a, z):
            await pg.mouse.move(*a)
            await pg.mouse.down()
            await pg.mouse.move(z[0], z[1], steps=15)
            await pg.wait_for_timeout(120)
            await pg.mouse.move(z[0] + 1, z[1], steps=2)
            await pg.mouse.up()
            await pg.wait_for_timeout(400)
        await drag(pts["out"], pts["ty"])
        await drag(pts["out"], pts["scale"])
        r = await pg.evaluate("""() => {
          const t = app.graph._nodes.find(n => n.type === 'PCG_Transform');
          app.canvas.setDirty(true, true); app.canvas.draw(true, true);
          const rect = app.canvas.canvas.getBoundingClientRect();
          const f = (n) => t._pcgPanel.inner.querySelector(`[data-w="${n}"]`);
          const slotY = (n) => t.getInputPos(t.inputs.findIndex(x => x.name === n))[1] + rect.top;
          const rowY = (n) => { const b = f(n).getBoundingClientRect(); return b.top + b.height / 2; };
          return {linked: t.inputs.filter(i => i.link != null).map(i => i.name),
                  ty: f('ty').value, cls: f('ty').className,
                  dTy: slotY('ty') - rowY('ty'), dSx: slotY('sx') - rowY('sx'),
                  shown: !__t.row(t, 'Translate').classList.contains('hidden'),
                  nativeHidden: __t.w(t, 'ty').hidden === true};
        }""")
        check("wire dropped on Translate's y field -> connects to ty; dropped on Scale's label -> connects to the first in that row (sx)",
              sorted(r["linked"]) == ["sx", "ty"], r)
        check("  a wired field shows '⇠ Value (PCG).float' (purple, not editable), the row still shows, the native widget hidden",
              r["ty"] == "⇠ Value (PCG).float" and "lnk" in r["cls"] and r["shown"]
              and r["nativeHidden"], r)
        check("  the input dot lines up with its row (three components in one row offset vertically by 5)",
              abs(r["dTy"]) <= 1 and abs(r["dSx"] + 5) <= 1, (r["dTy"], r["dSx"]))

        await pg.evaluate("""async () => {
          app.graph.clear();
          const mk = (ty, x, y) => { const n = LiteGraph.createNode(ty); n.pos = [x, y]; app.graph.add(n); return n; };
          const a = mk('PCG_Transform', 100, 150); a.title = 'lead';
          const b = mk('PCG_Transform', 520, 150); b.title = 'follow';
          app.canvas.ds.scale = 1; app.canvas.ds.offset = [0, 0];
          await __t.wait(800); app.canvas.setDirty(true, true); app.canvas.draw(true, true);
        }""")

        async def label_of(title, row):
            return await pg.evaluate("""([t, r]) => {
              const n = app.graph._nodes.find(x => x.title === t);
              const b = __t.row(n, r).querySelector('.lab').getBoundingClientRect();
              return [b.left + 15, b.top + b.height / 2]; }""", [title, row])

        async def menu(at, text):
            await pg.mouse.click(*at, button="right")
            await pg.wait_for_timeout(250)
            items = await pg.locator(".litecontextmenu .litemenu-entry").all_inner_texts()
            if text:
                await pg.locator(".litecontextmenu .litemenu-entry", has_text=text).first.click()
                await pg.wait_for_timeout(250)
            return items
        m1 = await menu(await label_of("lead", "Translate"), "Copy Parameter")
        m2 = await menu(await label_of("follow", "Translate"), "Paste Relative References")
        fy = await pg.evaluate("""() => { const n = app.graph._nodes.find(x => x.title === 'lead');
          const b = n._pcgPanel.inner.querySelector('[data-w="ty"]').getBoundingClientRect();
          return [b.left + b.width / 2, b.top + b.height / 2]; }""")
        await pg.mouse.click(*fy)
        await pg.keyboard.press("Control+A")
        await pg.keyboard.type("2.5")
        await pg.keyboard.press("Enter")
        await pg.wait_for_timeout(900)
        r = await pg.evaluate("""async () => {
          const b = app.graph._nodes.find(x => x.title === 'follow');
          const f = b._pcgPanel.inner.querySelector('[data-w="ty"]');
          const pr = await app.graphToPrompt();
          const wf = JSON.stringify(app.graph.serialize());
          const out = {bind: b.properties.pcg_bind, ty: __t.w(b, 'ty').value, cls: f.className,
                       prompt: pr.output[String(b.id)].inputs.ty};
          app.graph.clear(); await __t.wait(200);
          await app.loadGraphData(JSON.parse(wf)); await __t.wait(1500);
          const a2 = app.graph._nodes.find(x => x.title === 'lead');
          __t.w(a2, 'tz').value = -3;
          await __t.wait(900);
          const b2 = app.graph._nodes.find(x => x.title === 'follow');
          out.reload = {bind: b2.properties.pcg_bind, tz: __t.w(b2, 'tz').value};
          return out;
        }""")
        check("context menu: before copying only Copy Parameter / Set Keyframe / Revert to Defaults; after copying Paste Values / Paste Relative References appear (naming the source)",
              m1 == ["Copy Parameter", "Set Keyframe · frame 0",
                     "Revert to Defaults"]
              and any("Paste Relative References" in x and "lead.tx,ty,tz" in x for x in m2), (m1, m2))
        check("  the whole row pasted: each of the three components references its own (@leadid/tx …)",
              r["bind"] and sorted(r["bind"]) == ["tx", "ty", "tz"]
              and all(v.endswith("/" + k) for k, v in r["bind"].items()), r["bind"])
        check("  typing 2.5 on lead: follow's ty follows, the field is marked ref (cyan), and the prompt submitted to the backend has 2.5 too",
              r["ty"] == 2.5 and "ref" in r["cls"] and r["prompt"] == 2.5, r)
        check("  references survive saving and reloading; lead changes again, follow still follows", r["reload"]["bind"] == r["bind"]
              and r["reload"]["tz"] == -3, r["reload"])

        # ── Fields hold expressions; hold the middle button to see the value; click the label to toggle (real mouse)
        await pg.wait_for_timeout(300)
        FY = """() => { const b = app.graph._nodes.find(x => x.title === 'follow');
          const f = b._pcgPanel.inner.querySelector('[data-w="ty"]');
          const r = f.getBoundingClientRect();
          return {v: f.value, cls: f.className, at: [r.left + r.width / 2, r.top + r.height / 2],
                  off: [...app.canvas.ds.offset], w: __t.w(b, 'ty').value}; }"""
        e0 = await pg.evaluate(FY)
        await pg.mouse.move(*e0["at"])
        await pg.mouse.down(button="middle")
        await pg.wait_for_timeout(150)
        e1 = await pg.evaluate(FY)
        await pg.mouse.move(e0["at"][0] + 60, e0["at"][1] + 40, steps=6)
        await pg.wait_for_timeout(150)
        e2 = await pg.evaluate(FY)
        await pg.mouse.up(button="middle")
        await pg.wait_for_timeout(150)
        e3 = await pg.evaluate(FY)
        check("a referencing field shows ch(\"../lead/ty\") by default", e0["v"] == 'ch("../lead/ty")', e0["v"])
        check("  holding the middle button: shows the current value 2.5; dragging while held doesn't pan the canvas; release returns to the expression",
              e1["v"] == "2.5" and "peek" in e1["cls"] and e2["off"] == e0["off"]
              and e3["v"] == 'ch("../lead/ty")' and "peek" not in e3["cls"],
              (e1["v"], e2["off"], e0["off"], e3["v"]))
        # Negative control: the same middle-button drag on empty canvas really pans it (so "doesn't pan the canvas" above isn't a vacuous test)
        await pg.mouse.move(60, 900)
        await pg.mouse.down(button="middle")
        await pg.mouse.move(120, 940, steps=6)
        await pg.mouse.up(button="middle")
        await pg.wait_for_timeout(150)
        off_bg = await pg.evaluate("[...app.canvas.ds.offset]")
        check("    negative control: middle-button drag on empty canvas pans the canvas", off_bg != e0["off"], (off_bg, e0["off"]))
        await pg.evaluate("app.canvas.ds.offset = [0, 0]; app.canvas.setDirty(true, true)")
        await pg.wait_for_timeout(300)
        lab = await label_of("follow", "Translate")
        await pg.mouse.click(*lab)
        await pg.wait_for_timeout(200)
        e4 = await pg.evaluate(FY)
        await pg.mouse.click(*lab)
        await pg.wait_for_timeout(200)
        e5 = await pg.evaluate(FY)
        check("  clicking the Translate label switches to showing the value, clicking again back to the expression; the value doesn't change when clicking",
              e4["v"] == "2.5" and e5["v"] == 'ch("../lead/ty")' and e5["w"] == 2.5, (e4, e5))

        # ── pcg91: typing expressions into fields (real keyboard), $F materialized before queueing
        FLD = """([t, w]) => { const b = app.graph._nodes.find(x => x.title === t);
          const f = b._pcgPanel.inner.querySelector(`[data-w="${w}"]`);
          const r = f.getBoundingClientRect();
          return {v: f.value, cls: f.className, title: f.title, at: [r.left + r.width / 2, r.top + r.height / 2],
                  w: __t.w(b, w).value, bind: (b.properties.pcg_bind || {})[w] ?? null}; }"""

        async def type_into(t, w, text):
            f = await pg.evaluate(FLD, [t, w])
            await pg.mouse.click(*f["at"])
            await pg.wait_for_timeout(120)
            await pg.keyboard.press("Control+A")
            await pg.keyboard.type(text)
            await pg.keyboard.press("Enter")
            await pg.wait_for_timeout(400)
            return await pg.evaluate(FLD, [t, w])

        src_tx = await pg.evaluate("__t.w(app.graph._nodes.find(x => x.title === 'lead'), 'tx').value = 1.5")
        x1 = await type_into("follow", "tx", 'ch("../lead/tx") * 2 + 1')
        check("a referencing field can be clicked into and typed in: ch(\"../lead/tx\") * 2 + 1 -> value = lead.tx × 2 + 1, stored as @id, the field shows the expression",
              x1["w"] == src_tx * 2 + 1 and x1["bind"].startswith('=ch("@') and x1["bind"].endswith('/tx") * 2 + 1')
              and x1["v"] == 'ch("../lead/tx") * 2 + 1' and "ref" in x1["cls"], x1)
        x2 = await type_into("follow", "ty", "fit(1, 0, 2")
        check("  malformed (missing a parenthesis): field turns red, the tooltip gives the reason, value unchanged", "err" in x2["cls"] and "missing ')'" in x2["title"]
              and x2["w"] == 2.5, (x2["cls"], x2["title"][:60], x2["w"]))
        await pg.evaluate("""() => { const n = LiteGraph.createNode('PCG_Frame'); n.pos = [100, 650];
          app.graph.add(n); __t.w(n, 'frame').value = 3; }""")
        x3 = await type_into("follow", "ty", "$F * 10 + sin(90)")
        check("  corrected: $F * 10 + sin(90) (Frame node at frame 3, sin in degrees) -> 31, red removed",
              x3["w"] == 31 and "err" not in x3["cls"], (x3["w"], x3["cls"]))
        pr = await pg.evaluate("""async () => {
          const fr = app.graph._nodes.find(x => x.type === 'PCG_Frame');
          __t.w(fr, 'frame').value = 8;              // like the playbar: queue right after changing the frame, without waiting for the timed sync
          const p = await app.graphToPrompt();
          const b = app.graph._nodes.find(x => x.title === 'follow');
          return p.output[String(b.id)].inputs.ty; }""")
        check("  graphToPrompt right after changing the frame (that's how the playbar queues): the submitted value is already the new frame's 81", pr == 81, pr)
        x4 = await type_into("follow", "ty", "6")
        check("  typing a plain number 6: expression replaced, the field back to normal", x4["w"] == 6 and x4["bind"] is None and "ref" not in x4["cls"]
              and x4["v"] == "6", x4)

        # ═══════════════════════════════════════ pcg93: geometry queries (real run), keyframes (real Alt+click), string templates
        sec("Geometry queries in fields: npoints / bbox / point computed once upstream has really run")
        sx = await pg.evaluate("""async () => {
          app.graph.clear();
          const box = __t.add('PCG_Box', 100, 100); box.title = 'box1';
          const ex = __t.add('PCG_ExportMesh', 100, 500);
          box.connect(0, ex, 0);
          __t.w(ex, 'filename').value = 'pcg_e2e/geoq';
          const sx = 1 + (Date.now() % 997) / 1000;        // different each time: otherwise the whole graph hits the cache and doesn't execute
          __t.w(box, 'size_x').value = sx;
          const sph = __t.add('PCG_Sphere', 500, 100); sph.title = 'sph';
          await __t.wait(500);
          return sx; }""")
        g1 = await type_into("sph", "rows", 'npoints("../box1") + 1')
        g2 = await type_into("sph", "radius", 'bbox("../box1", D_XSIZE)')
        g3 = await type_into("sph", "cols", 'rint(point("../box1", 7, "P", 0) * 100) + 200')
        check("  not run yet: the field is 'waiting' (not red), the tooltip says it hasn't run yet", "wait" in g1["cls"] and "err" not in g1["cls"]
              and "has not run yet" in g1["title"], (g1["cls"], g1["title"][:60]))
        r = await pg.evaluate("""async () => {
          await app.queuePrompt(0, 1);
          for (let i = 0; i < 150; i++) {
            await __t.wait(200);
            const q = await (await fetch('/queue')).json();
            if (!q.queue_running.length && !q.queue_pending.length) break;
          }
          await __t.wait(1200);
          const box = app.graph._nodes.find(x => x.title === 'box1');
          const sph = app.graph._nodes.find(x => x.title === 'sph');
          const key = box.properties.pcg_geoq;
          const p7 = key && (await (await fetch(`/pcg/geoq/${key}?op=elem&cls=point&n=7&name=P`)).json()).value;
          return {key, p7, rows: __t.w(sph, 'rows').value, radius: __t.w(sph, 'radius').value,
                  cols: __t.w(sph, 'cols').value,
                  cls: sph._pcgPanel.inner.querySelector('[data-w="rows"]').className}; }""")
        check("after the run: Box's key is stored on the node; npoints + 1 = 9, bbox D_XSIZE = Box's size_x, point(7).P.x computed from the server's values",
              r["key"] and r["rows"] == 9 and abs(r["radius"] - sx) < 0.006   # radius field precision 0.01
              and r["cols"] == round(r["p7"][0] * 100) + 200 and "wait" not in r["cls"], (r, sx))

        sec("Keyframes: real Alt+click, changing frames, typing into a keyframed field")
        await pg.evaluate("""async () => {
          app.graph.clear();
          const fr = __t.add('PCG_Frame', 100, 600);
          const tr = __t.add('PCG_Transform', 100, 100); tr.title = 'tr1';   // added later (add moves existing nodes aside)
          fr.pos = [100, 600];
          __t.w(fr, 'frame').value = 0;
          __t.w(tr, 'tx').value = 2;
          await __t.wait(500); }""")
        f0 = await pg.evaluate(FLD, ["tr1", "tx"])
        await pg.keyboard.down("Alt")
        await pg.mouse.click(*f0["at"])
        await pg.keyboard.up("Alt")
        await pg.wait_for_timeout(300)
        k1 = await pg.evaluate(FLD, ["tr1", "tx"])
        check("Alt+click tx: sets a key of 2 at frame 0 (k:0:2), field green, on a key", k1["bind"] == "k:0:2" and "key" in k1["cls"]
              and "onkey" in k1["cls"], k1)
        await pg.evaluate("""async () => {
          const fr = app.graph._nodes.find(x => x.type === 'PCG_Frame');
          __t.w(fr, 'frame').value = 12; app.canvas.setDirty(true, true); await __t.wait(900); }""")
        k2 = await pg.evaluate(FLD, ["tr1", "tx"])
        check("  switching to frame 12: no longer on a key (highlight removed)", "onkey" not in k2["cls"] and "key" in k2["cls"], k2["cls"])
        k3 = await type_into("tr1", "tx", "5")
        check("  typing 5 at frame 12: auto-key k:0:2  12:5, on a key", k3["bind"] == "k:0:2  12:5" and "onkey" in k3["cls"]
              and k3["w"] == 5, k3)
        k4 = await pg.evaluate("""async () => {
          const fr = app.graph._nodes.find(x => x.type === 'PCG_Frame');
          __t.w(fr, 'frame').value = 6;
          const p = await app.graphToPrompt();
          const tr = app.graph._nodes.find(x => x.title === 'tr1');
          return p.output[String(tr.id)].inputs.tx; }""")
        check("  scrubbing to frame 6 and queueing right away: the submitted value is 3.5, interpolated between the two keys", abs(k4 - 3.5) < 1e-9, k4)

        sec("String fields: templates")
        t1 = await type_into("tr1", "group", "${OS}_${F4}_`$F*2`")
        check("typing ${OS}_${F4}_`$F*2` into the Group field (frame 6): value tr1_0006_12, the field keeps the template",
              t1["w"] == "tr1_0006_12" and t1["v"] == "${OS}_${F4}_`$F*2`" and t1["bind"] == "~${OS}_${F4}_`$F*2`", t1)
        t2 = await type_into("tr1", "group", "plain")
        check("  typing plain text: template replaced", t2["w"] == "plain" and t2["bind"] is None, t2)

        # ═══════════════════════════════════════ pcg94: reference dashed lines (real click selection)
        sec("Reference dashed lines: drawn only when a node is selected, gone after clicking empty space")
        rl = await pg.evaluate("""async () => {
          app.graph.clear();
          const a = __t.add('PCG_Transform', 100, 120); a.title = 'src';
          const b = __t.add('PCG_Transform', 700, 420); b.title = 'dst';
          a.pos = [100, 120];
          b.properties.pcg_bind = { tx: `@${a.id}/tx`, ty: '=ch("../src/ty") * 2' };
          app.canvas.deselectAll?.(); app.canvas.setDirty(true, true);
          await __t.wait(400);
          const W = await import('/extensions/comfyui_pcg/pcg_wires.js');
          const r = app.canvas.canvas.getBoundingClientRect();
          const ds = app.canvas.ds;
          const scr = (x, y) => [r.left + (x + ds.offset[0]) * ds.scale, r.top + (y + ds.offset[1]) * ds.scale];
          return { none: W.lastRefLines.length, title: scr(b.pos[0] + 60, b.pos[1] - 15),
                   empty: scr(500, 800) }; }""")
        check("no node selected: not a single dashed line drawn", rl["none"] == 0, rl["none"])
        await pg.mouse.click(*rl["title"])
        await pg.wait_for_timeout(500)
        r1 = await pg.evaluate("""async () => {
          const W = await import('/extensions/comfyui_pcg/pcg_wires.js');
          return { sel: Object.keys(app.canvas.selected_nodes || {}).length,
                   lines: W.lastRefLines.map(l => ({ p: l.params, seg: l.seg })) }; }""")
        check("really clicking dst's title bar selects it: one line drawn (two parameters referencing the same node merge into one), parameters tx / ty",
              r1["sel"] == 1 and len(r1["lines"]) == 1 and sorted(r1["lines"][0]["p"]) == ["tx", "ty"], r1)
        await pg.screenshot(path=os.path.join(_R, "pcg94_reflines.png"), clip={"x": 60, "y": 40, "width": 1060, "height": 620})
        await pg.mouse.click(*rl["empty"])
        await pg.wait_for_timeout(500)
        r2 = await pg.evaluate("""async () => {
          const W = await import('/extensions/comfyui_pcg/pcg_wires.js');
          return { sel: Object.keys(app.canvas.selected_nodes || {}).length, n: W.lastRefLines.length }; }""")
        check("  clicking empty space deselects: dashed lines disappear", r2["sel"] == 0 and r2["n"] == 0, r2)

        # ═══════════════════════════════════════ pcg95: colour picker dragging doesn't stutter
        sec("Colour picker: a burst of inputs within one frame is handled once, no height measurement on the spot")
        cp = await pg.evaluate("""async () => {
          app.graph.clear();
          const n = __t.add('PCG_Color', 100, 100);
          await __t.wait(600);
          const P = n._pcgPanel, pick = P.inner.querySelector('input[type=color]');
          const frame = () => new Promise(r => requestAnimationFrame(() => r()));
          await frame(); await frame();
          let rs = 0; const o = P.onResize; P.onResize = () => { rs++; o(); };
          const h0 = n.size[1];
          const t0 = performance.now();
          for (let i = 0; i < 30; i++) { pick.value = '#' + (i * 8).toString(16).padStart(2, '0') + '4080';
                                         pick.dispatchEvent(new Event('input', { bubbles: true })); }
          const ms = performance.now() - t0;
          const sync = rs, r1 = Math.round(__t.w(n, 'r').value * 255);
          await frame(); await frame(); await frame();
          P.onResize = o;
          return { ms, sync, r1, r2: Math.round(__t.w(n, 'r').value * 255),
                   g: Math.round(__t.w(n, 'g').value * 255), after: rs, h: [h0, n.size[1]] }; }""")
        check("real frontend: 30 inputs fired in one frame, only the first written on the spot without measuring height; the last written on the next frame (r = 232), "
              "height measured once per frame, node height unchanged", cp["sync"] == 0 and cp["r1"] == 0 and cp["r2"] == 232
              and cp["g"] == 0x40 and 1 <= cp["after"] <= 3 and cp["h"][0] == cp["h"][1], cp)

        # ═══════════════════════════════════════ pcg96: Edit Parameter Interface dialog (real mouse, real keyboard)
        sec("Edit Parameter Interface: add parameters, renaming carries references along, save round trip")
        ep = await pg.evaluate("""async () => {
          app.graph.clear();
          const sp = __t.add('PCG_Sphere', 700, 100); sp.title = 'ball';
          const c = __t.add('PCG_Parameters', 100, 100); c.title = 'CTRL';
          sp.pos = [700, 100];
          await __t.wait(700);
          const d = __t.w(c, 'declare');
          d.value = 'float radius = 2 : 0 10  # Radius'; d.callback?.(d.value);
          await __t.wait(500);
          const btn = __t.w(c, 'pcg_edit_ui');
          btn.callback();
          await __t.wait(300);
          const box = document.querySelector('.pcg-epi');
          const r = (e) => { const b = e.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; };
          return { btn: !!btn, idx: c.widgets.indexOf(btn), open: !!box,
                   rows: [...box.querySelectorAll('.col:nth-child(2) .it')].map(x => x.textContent),
                   vec: r(box.querySelector('[data-type="vector"]')), id: c.id }; }""")
        check("the node has a ⚙ button (after declare / values); clicking it opens the dialog listing the existing parameters",
              ep["btn"] and ep["idx"] == 2 and ep["open"] and ep["rows"] == ["Radius(radius)Float"], ep)
        await pg.mouse.click(*ep["vec"])                         # click Float Vector 3 in the left column
        await pg.wait_for_timeout(200)
        await pg.keyboard.type("offset")                         # the new entry's name box is already selected, just type over it
        await pg.keyboard.press("Delete")                        # Delete in an input box deletes characters, it must not delete the node
        await pg.wait_for_timeout(100)
        await pg.screenshot(path=os.path.join(_R, "pcg96_edit_parameter_interface.png"),
                            clip={"x": 300, "y": 220, "width": 1000, "height": 660})
        e2 = await pg.evaluate("""async () => {
          const box = document.querySelector('.pcg-epi');
          const rows = [...box.querySelectorAll('.col:nth-child(2) .it')].map(x => x.textContent);
          [...box.querySelectorAll('.ft button')].find(b => b.textContent === 'Accept').click();
          await __t.wait(500);
          const c = app.graph._nodes.find(n => n.title === 'CTRL');
          return { rows, nodes: app.graph._nodes.length, open: !!document.querySelector('.pcg-epi'),
                   decl: __t.w(c, 'declare').value, ws: c.widgets.map(w => w.name).filter(n => n.startsWith('p_')) }; }""")
        check("real mouse clicks Float Vector 3 + real keyboard types the name offset -> Accept: one more declaration line, three components appear on the panel; "
              "pressing Delete in the dialog didn't delete the node", e2["rows"] == ["Radius(radius)Float", "offset(offset)Float Vector 3"]
              and not e2["open"] and e2["nodes"] == 2
              and e2["decl"] == "float radius = 2 : 0 10  # Radius\nvector offset = 0 0 0\n"
              and e2["ws"] == ["p_radius", "p_offset.x", "p_offset.y", "p_offset.z"], e2)
        b1 = await type_into("ball", "radius", 'ch("../CTRL/radius") * 2')
        check("  Sphere's Radius set to ch(\"../CTRL/radius\") * 2 -> 2 (radius on the panel is now 1: the node's built-in declaration already has it, "
              "changing the declaration's default doesn't touch the stored value)", b1["w"] == 2 and "err" not in b1["cls"], b1)
        e3 = await pg.evaluate("""async () => {
          const c = app.graph._nodes.find(n => n.title === 'CTRL');
          const sp = app.graph._nodes.find(n => n.title === 'ball');
          const U = await import('/extensions/comfyui_pcg/pcg_paramui.js');
          const D = U.openDialog(c);
          const row0 = document.querySelector('.pcg-epi .col:nth-child(2) .it').textContent;
          const nm = document.querySelector('.pcg-epi [data-k="name"]');
          nm.value = 'size'; nm.dispatchEvent(new Event('input', { bubbles: true }));
          [...document.querySelectorAll('.pcg-epi .ft button')].find(b => b.textContent === 'Accept').click();
          await __t.wait(300);
          __t.w(c, 'p_size').value = 3; __t.w(c, 'p_size').callback(3);
          await __t.wait(900);
          const bind = sp.properties.pcg_bind.radius;
          const ser = JSON.parse(JSON.stringify(app.graph.serialize()));
          await app.loadGraphData(ser);
          await __t.wait(1500);
          const c2 = app.graph._nodes.find(n => n.title === 'CTRL');
          const sp2 = app.graph._nodes.find(n => n.title === 'ball');
          __t.w(c2, 'p_size').value = 4.5; __t.w(c2, 'p_size').callback(4.5);
          await __t.wait(900);
          return { row0, bind, id: c.id, r: __t.w(sp, 'radius').value, r2: __t.w(sp2, 'radius').value,
                   ws2: c2.widgets.map(w => w.name), vals: __t.w(c2, 'values').value }; }""")
        check("rename radius -> size: the list shows it is referenced in 1 place; Sphere's expression follows to @id/size, panel scrubbed to 3 -> radius 6",
              e3["row0"] == "Radius(radius)← 1Float" and e3["bind"] == f'=ch("@{e3["id"]}/size") * 2' and e3["r"] == 6, e3)
        check("  save and reload: the button is still 3rd, all parameter controls present, the reference still follows (panel 4.5 -> radius 9)",
              e3["ws2"] == ["declare", "values", "pcg_edit_ui", "p_size", "p_offset.x", "p_offset.y", "p_offset.z"]
              and e3["r2"] == 9 and json.loads(e3["vals"])["size"] == 4.5, e3)

        # ═══════════════════════════════════════ pcg97: ramp editor (real mouse, real keyboard)
        sec("Ramp editor: control points sit on the curve, real-mouse drag in any direction, click empty space to add, right-click / Delete to remove")
        rp = await pg.evaluate("""async () => {
          app.graph.clear();
          const n = __t.add('PCG_SoftPeak', 100, 100); n.title = 'peak';
          await __t.wait(700);
          __t.w(n, 'ramp').value = '0:0  0.5:1  1:0.5'; n._pcgPanel.refresh();
          await __t.wait(300);
          const box = n._pcgPanel.inner.querySelector('.ramp.flt');
          const a = box.querySelector('.rarea').getBoundingClientRect();
          const ks = [...box.querySelectorAll('.pts .key')];
          const cs = getComputedStyle(ks[1]);
          const c = (k) => { const b = k.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; };
          return { area: [a.x, a.y, a.width, a.height], pts: ks.map(c), bg: cs.backgroundColor, w: cs.width,
                   idx: box.querySelector('.idx').textContent }; }""")
        ax, ay, aw, ah = rp["area"]
        exp = [[ax + 1 + 0.0 * (aw - 2), ay + 1 + 1.0 * (ah - 2)], [ax + 1 + 0.5 * (aw - 2), ay + 1 + 0.0 * (ah - 2)],
               [ax + 1 + 1.0 * (aw - 2), ay + 1 + 0.5 * (ah - 2)]]
        off = max(abs(p[0] - e[0]) + abs(p[1] - e[1]) for p, e in zip(rp["pts"], exp))
        check("float ramp: the centers of the three control points sit on the curve at (position, value) (within 1.5 px); curve area ~96 tall; "
              "points are light-coloured dots (after pcg93 the 'keyframed field' style had dyed them dark green, invisible)",
              off <= 1.5 and 90 <= ah <= 102 and rp["bg"] == "rgb(228, 235, 242)" and rp["idx"] == "1 / 3", (off, ah, rp["bg"]))
        x0, y0 = rp["pts"][1]
        await pg.mouse.move(x0, y0)
        await pg.mouse.down()
        await pg.mouse.move(x0 - (aw - 2) * 0.25, y0 + (ah - 2) * 0.4, steps=6)
        mid = await pg.evaluate("__t.w(app.graph._nodes[0], 'ramp').value")
        await pg.mouse.up()
        await pg.wait_for_timeout(250)
        r1 = await pg.evaluate("""() => { const n = app.graph._nodes[0];
          return { v: __t.w(n, 'ramp').value, f: [...n._pcgPanel.inner.querySelectorAll('.ramp.flt .kline input.num')].map(x => x.value) }; }""")
        k1 = r1["v"].split()[1].split(":")
        check("real mouse grabs the middle point and drags down-left: position 0.5 -> 0.25, value 1 -> 0.6 (widget not written while dragging, written once on release); the fields below show it",
              mid == "0:0  0.5:1  1:0.5" and abs(float(k1[0]) - 0.25) < 0.01 and abs(float(k1[1]) - 0.6) < 0.015
              and len(r1["v"].split()) == 3 and abs(float(r1["f"][0]) - 0.25) < 0.01, (mid, r1))
        await pg.mouse.click(ax + 1 + (aw - 2) * 0.75, ay + ah * 0.5)
        await pg.wait_for_timeout(250)
        r2 = await pg.evaluate("""() => { const n = app.graph._nodes[0];
          const ks = [...n._pcgPanel.inner.querySelectorAll('.ramp.flt .pts .key')];
          const b = ks[2].getBoundingClientRect();
          return { v: __t.w(n, 'ramp').value, n: ks.length, sel: ks.findIndex(k => k.classList.contains('sel')),
                   at: [b.x + b.width / 2, b.y + b.height / 2], focus: document.activeElement?.className }; }""")
        check("clicking empty space in the curve area (position 0.75): adds a point and selects it, value taken from the curve there; the ramp box gets focus",
              r2["n"] == 4 and r2["sel"] == 2 and abs(float(r2["v"].split()[2].split(":")[0]) - 0.75) < 0.01
              and "ramp" in (r2["focus"] or ""), r2)
        await pg.keyboard.press("Delete")
        await pg.wait_for_timeout(200)
        r3 = await pg.evaluate("({ n: __t.w(app.graph._nodes[0], 'ramp').value.split(/\\s+/).length, nodes: app.graph._nodes.length })")
        check("  pressing Delete: deletes the selected point (3 left), the node is still there (the key didn't leak to the canvas)", r3 == {"n": 3, "nodes": 1}, r3)
        pt = await pg.evaluate("""() => { const k = app.graph._nodes[0]._pcgPanel.inner.querySelectorAll('.ramp.flt .pts .key')[1];
          const b = k.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; }""")
        await pg.mouse.click(*pt, button="right")
        await pg.wait_for_timeout(250)
        r4 = await pg.evaluate("""({ v: __t.w(app.graph._nodes[0], 'ramp').value,
          menu: !!document.querySelector('.litecontextmenu, .p-contextmenu') })""")
        check("  real right-click on a control point: deletes it (2 left), no menu pops up", len(r4["v"].split()) == 2 and not r4["menu"], r4)
        await pg.screenshot(path=os.path.join(_R, "pcg97_ramp_float.png"), clip={"x": 80, "y": 60, "width": 400, "height": 420})
        cm = await pg.evaluate("""async () => {
          app.graph.clear();
          const n = __t.add('PCG_Color', 100, 100);
          await __t.wait(700);
          __t.w(n, 'mode').value = 'ramp_by_attribute'; __t.w(n, 'ramp').value = '0:0,0,1  0.5:0,1,0  1:1,0,0';
          n._pcgPanel.refresh(); await __t.wait(400);
          const box = n._pcgPanel.inner.querySelector('.ramp.col');
          const ks = [...box.querySelectorAll('.keys .key')];
          const a = box.querySelector('.rarea').getBoundingClientRect();
          return { area: [a.x, a.y, a.width, a.height],
                   ks: ks.map(k => { const b = k.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2, b.width, b.height,
                                     getComputedStyle(k, '::after').backgroundColor]; }) }; }""")
        ax, ay, aw, ah = cm["area"]
        check("colour ramp: three markers below the colour bar, at their positions (within 1 px), 11×15 in size, each marker showing its own colour",
              all(abs(k[0] - (ax + 1 + p * (aw - 2))) <= 1 and k[1] > ay + ah and k[2] >= 10 and k[3] >= 14
                  for k, p in zip(cm["ks"], [0, 0.5, 1]))
              and [k[4] for k in cm["ks"]] == ["rgb(0, 0, 255)", "rgb(0, 255, 0)", "rgb(255, 0, 0)"], cm)
        kx, ky = cm["ks"][1][:2]
        await pg.mouse.move(kx, ky)
        await pg.mouse.down()
        await pg.mouse.move(kx + (aw - 2) * 0.3, ky + 30, steps=5)
        await pg.mouse.up()
        await pg.wait_for_timeout(250)
        c2 = await pg.evaluate("__t.w(app.graph._nodes[0], 'ramp').value")
        check("  real mouse drags the middle marker to 0.8: only the position changes, colour unchanged", abs(float(c2.split()[1].split(":")[0]) - 0.8) < 0.01
              and c2.split()[1].split(":")[1] == "0,1,0", c2)
        await pg.screenshot(path=os.path.join(_R, "pcg97_ramp_color.png"), clip={"x": 80, "y": 60, "width": 400, "height": 380})

        for e in errs:
            if "three" not in e:
                print("  ERR", e[:300])
        check("no PCG-related page errors during the whole run", not [e for e in errs if "three" not in e])
        await b.close()


asyncio.run(main())
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
