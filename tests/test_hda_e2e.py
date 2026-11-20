"""
Digital assets, references across networks, multiparms, presets and quick edit, in the real ComfyUI frontend
(web/pcg_hda.js, pcg_dock.js, pcg_params.js, pcg_presets.js). Needs PCG_E2E_URL (as test_panel_e2e.py).

  · Convert to Subgraph, promote parameters: the instance is compact on the canvas, its parameters are in the
    docked pane with the look of what they drive (a full vector row: one row); written values reach the prompt
  · Edit Asset Interface (the dialog, by its controls): promote, order, label, hide rule -- the pane follows; the
    interface lives on the definition and is copied onto the instance (it travels with Publish Subgraph)
  · the library: a published asset inserted twice gives two copies; once the library changes, "differs", and the
    update brings every instance to it with their values kept (negative control: "same" before the change)
  · inside the asset: ch("../size_x") follows the asset's parameter; the display flag puts a Display node inside it
    and the run shows it; cook records under the execution ids ("3:2")
  · a multiparm block in custom parameters: + makes an instance, − removes it
  · presets: save, change, load back (values restored), delete
  · Ctrl+click a node: its panel next to it, the selection unchanged; Esc closes it
"""
import asyncio
import json
import os
import sys

URL = os.environ.get("PCG_E2E_URL")
try:
    from playwright.async_api import async_playwright
except ImportError:                                     # pragma: no cover
    async_playwright = None
if not URL or async_playwright is None:
    print("  (PCG_E2E_URL not set or playwright not installed, skipping real frontend test)")
    print("\n0/0 passed")
    sys.exit(0)

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


MAKE = """async (name) => {
  const W = (ms) => new Promise(r => setTimeout(r, ms));
  app.graph.clear();
  const add = (t, x) => { const n = LiteGraph.createNode(t); n.pos = [x, 200]; app.graph.add(n); return n; };
  const a = add('PCG_Box', 100), t = add('PCG_Transform', 450);
  a.connect(0, t, 0);
  await W(300); app.canvas.deselectAll?.(); app.canvas.select(a); app.canvas.select(t);
  await app.extensionManager.command.execute('Comfy.Graph.ConvertToSubgraph'); await W(400);
  const sn = app.graph._nodes.find(n => n.subgraph); sn.title = name; sn.subgraph.name = name;
  app.canvas.ds.scale = 1; app.canvas.ds.offset = [0, 0];
  window.__sn = sn;
  return sn.id;
}"""


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1600, "height": 1000})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(URL, wait_until="networkidle")
        await pg.wait_for_function("window.app && window.app.graph", timeout=90000)
        await pg.evaluate("app.extensionManager.setting.set('PCG.ParamPanel', 'Docked pane')")
        await pg.wait_for_timeout(2500)

        sec("An asset's parameters in the docked pane")
        await pg.evaluate(MAKE, "rock")
        r = await pg.evaluate("""async () => {
          const W = (ms) => new Promise(r => setTimeout(r, ms));
          const H = await import('/extensions/comfyui_pcg/pcg_hda.js');
          const sn = __sn, sg = sn.subgraph;
          const tr = sg._nodes.find(n => n.type === 'PCG_Transform'), bx = sg._nodes.find(n => n.type === 'PCG_Box');
          for (const w of ['tx', 'ty', 'tz']) H.promote(sn, tr, w);
          H.promote(sn, bx, 'size_x');
          await W(400);
          app.canvas.selectNode(sn); await W(400);
          const pane = document.querySelector('.pcgdock');
          const rows = [...pane.querySelectorAll('.row')].map(r => (r.querySelector('.lab')?.textContent || '').trim());
          const inp = [...pane.querySelectorAll('.row')].find(r => r.querySelector('.lab')?.textContent.trim() === 'Translate')
            .querySelectorAll('input.num')[1];
          inp.value = '2.5'; inp.dispatchEvent(new Event('change', {bubbles: true}));
          const pr = await app.graphToPrompt();
          const ty = Object.values(pr.output).find(v => v.class_type === 'PCG_Transform').inputs.ty;
          return {docked: !!sn._pcgDocked?.hda, h: sn.size[1], vis: sn.widgets.filter(w => !w.hidden).length, rows, ty,
                  sub: pane.querySelector('.sub').textContent};
        }""")
        check("the instance is docked, compact, no parameter widget shown on it", r["docked"] and r["h"] < 60
              and r["vis"] == 0, r)
        check("  the pane: Translate as one vector row (all three promoted), Size X; header says asset · rock",
              r["rows"] == ["Translate", "Size X"] and "asset · rock" in r["sub"], r)
        check("  typing 2.5 into Translate Y reaches the prompt of the Transform inside", r["ty"] == 2.5, r["ty"])

        sec("Edit Asset Interface (the dialog)")
        r = await pg.evaluate("""async () => {
          const W = (ms) => new Promise(r => setTimeout(r, ms));
          const sn = __sn;
          const ext = app.extensions.find(e => e.name === 'pcg.dock');
          ext.getNodeMenuItems(sn).filter(Boolean).find(m => m.content.startsWith('PCG: Edit Asset')).callback();
          await W(200);
          const dlg = document.querySelector('.pcghda');
          const tid = String(sn.subgraph._nodes.find(n => n.type === 'PCG_Transform').id);
          const it = [...dlg.querySelectorAll('.list')[0].querySelectorAll('.it')].find(e => e.dataset.k === tid + '|uniform_scale');
          it.click(); dlg.querySelector('.mid button').click();
          const sel = (n) => [...dlg.querySelectorAll('.list')[1].querySelectorAll('.it')].find(e => e.dataset.n === n).click();
          sel('uniform_scale');
          const setF = (k, v) => { const i = dlg.querySelector(`.form [data-k="${k}"]`); i.value = v; i.dispatchEvent(new Event('input')); };
          setF('label', 'Overall Size'); setF('hide', '{ size_x < 1.5 }'); setF('folder', 'Shape');
          for (let i = 0; i < 4; i++) [...dlg.querySelectorAll('button')].find(b => b.textContent === '↑').click();
          const order = [...dlg.querySelectorAll('.list')[1].querySelectorAll('.it')].map(e => e.dataset.n);
          [...dlg.querySelectorAll('button')].find(b => b.textContent === 'Apply').click();
          await W(500);
          const pane = document.querySelector('.pcgdock');
          const vis = () => [...pane.querySelectorAll('.row')].filter(r => r.offsetParent).map(r => (r.querySelector('.lab')?.textContent || '').trim());
          const tabs = () => [...pane.querySelectorAll('.tab')].filter(t => !t.classList.contains('hidden')).map(t => t.textContent);
          const v0 = vis(), t0 = tabs();
          sn.widgets.find(w => w.name === 'size_x').value = 2; await W(400);
          [...pane.querySelectorAll('.tab')].find(t => t.textContent === 'Shape')?.click(); await W(100);
          const v1 = vis();
          return {order, v0, t0, v1, def: sn.subgraph.extra?.pcg_iface?.params?.uniform_scale?.label,
                  prop: sn.properties?.pcg_iface?.params?.uniform_scale?.label};
        }""")
        check("promoted Uniform Scale from the list, moved to the top", r["order"][0] == "uniform_scale", r["order"])
        check("  its hide rule: hidden (with its Shape tab) while Size X < 1.5, shown with its label when it is 2",
              "Overall Size" not in r["v0"] and "Shape" not in r["t0"] and "Overall Size" in r["v1"], r)
        check("  stored on the definition and copied onto the instance", r["def"] == "Overall Size"
              and r["prop"] == "Overall Size", r)

        sec("The library: published, inserted twice, updated")
        lib = f"pebble_e2e_{os.getpid()}_{int(asyncio.get_event_loop().time() * 1000) % 100000}"
        await pg.evaluate(MAKE, lib)
        await pg.evaluate("""async () => {
          const H = await import('/extensions/comfyui_pcg/pcg_hda.js');
          const sn = __sn, tr = sn.subgraph._nodes.find(n => n.type === 'PCG_Transform');
          H.promote(sn, tr, 'ty');
          H.setIface(sn.subgraph, {params: {ty: {label: 'Lift'}}, order: ['ty']});
          app.canvas.deselectAll?.(); app.canvas.select(sn);
          app.extensionManager.command.execute('Comfy.PublishSubgraph');
        }""")
        await pg.wait_for_timeout(800)
        over = await pg.query_selector("text=Overwrite")
        await pg.click("text=Confirm")
        await pg.wait_for_timeout(800)
        for t in ("text=Overwrite", "text=Yes", "text=Confirm"):
            el = await pg.query_selector(t)
            if el:
                try:
                    await el.click(timeout=1000)
                except Exception:
                    pass
        await pg.wait_for_timeout(1200)
        r = await pg.evaluate("""async (NAME) => {
          const W = (ms) => new Promise(r => setTimeout(r, ms));
          const H = await import('/extensions/comfyui_pcg/pcg_hda.js');
          const api = (await import('/scripts/api.js')).api;
          const data = await H.libraryGet(NAME + '.json');
          app.graph.clear(); await W(200);
          for (const x of [100, 600]) {
            const bp = JSON.parse(JSON.stringify(data));
            app.canvas._deserializeItems({nodes: bp.nodes, subgraphs: bp.definitions?.subgraphs}, {position: [x, 200]});
          }
          await W(500);
          const insts = app.graph._nodes.filter(n => n.subgraph);
          insts[0].widgets.find(w => w.name === 'ty').value = 7;
          const res = {n: insts.length, copies: insts[0].subgraph !== insts[1].subgraph,
                       label: insts.map(n => H.iface(n.subgraph).params.ty?.label), s0: await H.libraryState(insts[0].subgraph)};
          const box = data.definitions.subgraphs[0].nodes.find(n => n.type === 'PCG_Box');
          box.widgets_values[0] = 3;
          await api.fetchApi('/userdata/' + encodeURIComponent('subgraphs/' + NAME + '.json') + '?overwrite=true',
                             {method: 'POST', body: JSON.stringify(data)});
          res.s1 = await H.libraryState(insts[0].subgraph);
          res.upd = await H.updateFromLibrary(insts[0].subgraph);
          await W(400);
          res.after = app.graph._nodes.filter(n => n.subgraph).map(n => [n.subgraph._nodes.find(x => x.type === 'PCG_Box').widgets[0].value,
                                                                         n.widgets.find(w => w.name === 'ty').value]);
          res.s2 = await H.libraryState(insts[0].subgraph);
          await api.fetchApi('/userdata/' + encodeURIComponent('subgraphs/' + NAME + '.json'), {method: 'DELETE'});
          return res;
        }""", lib)
        check("inserted twice: two copies of the definition, both with the interface (from the instance's properties)",
              r["n"] == 2 and r["copies"] and r["label"] == ["Lift", "Lift"], r)
        check("  'same' before the library changes (negative control), 'differs' after", r["s0"] == "same"
              and r["s1"] == "differs", r)
        check("  update: both instances take the library's version (box 3), their own values kept (7, 0)",
              r["upd"] == 2 and r["after"] == [[3, 7], [3, 0]] and r["s2"] == "same", r)

        sec("Inside the asset: references, display flag, cook ids")
        await pg.evaluate(MAKE, "rock2")
        r = await pg.evaluate("""async () => {
          const W = (ms) => new Promise(r => setTimeout(r, ms));
          const H = await import('/extensions/comfyui_pcg/pcg_hda.js');
          const P = await import('/extensions/comfyui_pcg/pcg_params.js');
          const DSP = await import('/extensions/comfyui_pcg/pcg_display.js');
          const C = await import('/extensions/comfyui_pcg/pcg_cook.js');
          const sn = __sn, sg = sn.subgraph;
          const tr = sg._nodes.find(n => n.type === 'PCG_Transform'), bx = sg._nodes.find(n => n.type === 'PCG_Box');
          H.promote(sn, bx, 'size_x');
          sn.widgets.find(w => w.name === 'size_x').value = 2;
          app.canvas.openSubgraph(sg); await W(400);
          const b1 = P.bindExpr(tr, 'ty', 'ch("../size_x") * 3', sg);
          sn.widgets.find(w => w.name === 'size_x').value = 4.25;
          P.applyBindings(app.graph);
          const res = {bind: b1.ok, shown: P.bindingText(sg, tr, 'ty'), follow: tr.widgets.find(w => w.name === 'ty').value / sn.widgets.find(w => w.name === 'size_x').value};
          DSP.setFlag(sg, 'disp', tr, 0);
          res.sink = sg._nodes.some(n => n.type === 'PCG_Display');
          const before = C.RUN.start;
          await app.queuePrompt(0, 1);
          for (let i = 0; i < 80; i++) { await W(250); if (C.RUN.start !== before && C.RUN.end && !C.RUN.running) break; }
          await W(800);
          res.exec = C.execId(tr);
          res.rec = !!C.COOK.get(C.execId(tr))?.ok;
          res.shown3d = DSP.__state.lastNodeId;
          app.canvas.setGraph?.(app.graph); await W(200);
          res.back = app.canvas.graph === app.graph;
          return res;
        }""")
        check("ch(\"../size_x\") * 3 inside follows the asset's Size X, shown as typed",
              r["bind"] and r["shown"] == 'ch("../size_x") * 3' and abs(r["follow"] - 3) < 1e-6, r)
        check("  the display flag inside puts a Display node there; the run fills the 3D panel from it",
              r["sink"] and r["shown3d"] and ":" in str(r["shown3d"]), r)
        check("  the cook record of the Transform inside is under its execution id", r["rec"] and ":" in r["exec"], r)

        sec("Multiparm, presets, quick edit")
        r = await pg.evaluate("""async () => {
          const W = (ms) => new Promise(r => setTimeout(r, ms));
          const S = await import('/extensions/comfyui_pcg/pcg_spare.js');
          if (app.canvas.graph !== app.graph) app.canvas.setGraph(app.graph);
          app.graph.clear();
          const n = LiteGraph.createNode('PCG_Transform'); n.pos = [200, 200]; app.graph.add(n);
          await W(300);
          n.properties.pcg_spare = 'multi pts = 1  # Points\\n  float w# = 0.5 : 0 1  # Weight #\\nend';
          S.syncSpare(n); await W(300);
          app.canvas.selectNode(n); await W(400);
          const pane = document.querySelector('.pcgdock');
          const labs = () => [...pane.querySelectorAll('.row')].map(r => (r.querySelector('.lab')?.textContent || '').trim());
          const l0 = labs();
          const plus = [...pane.querySelectorAll('.row')].find(r => r.querySelector('.lab')?.textContent.trim() === 'Points')
            .querySelectorAll('button.btn')[0];
          plus.click(); await W(500);
          const l1 = labs();
          const minus = [...pane.querySelectorAll('.row')].find(r => r.querySelector('.lab')?.textContent.trim() === 'Points')
            .querySelectorAll('button.btn')[1];
          minus.click(); minus.click(); await W(500);
          return {l0, l1, l2: labs()};
        }""")
        check("a multiparm block: Points with Weight 1; + adds Weight 2; − twice leaves none",
              "Weight 1" in r["l0"] and "Weight 2" not in r["l0"] and "Weight 2" in r["l1"]
              and not any(x.startswith("Weight") for x in r["l2"]), r)
        r = await pg.evaluate("""async () => {
          const W = (ms) => new Promise(r => setTimeout(r, ms));
          const PR = await import('/extensions/comfyui_pcg/pcg_presets.js');
          const n = app.graph._nodes[0];
          const w = (k) => n.widgets.find(x => x.name === k);
          w('tx').value = 1.25; w('ry').value = 30;
          await PR.savePreset(n, 'e2e lifted');
          w('tx').value = 0; w('ry').value = 0;
          const listed = (await PR.listPresets(n)).includes('e2e lifted');
          await PR.applyPreset(n, 'e2e lifted');
          const back = [w('tx').value, w('ry').value];
          PR.revertToDefaults(n);
          const def = [w('tx').value, w('ry').value];
          await PR.deletePreset(n, 'e2e lifted');
          const gone = !(await PR.listPresets(n)).includes('e2e lifted');
          const R = app.canvas.canvas.getBoundingClientRect(), q = app.canvas.ds.convertOffsetToCanvas([n.pos[0] + 60, n.pos[1] + 10]);
          app.canvas.deselectAll?.();
          app.canvas.setDirty(true, true); await W(300);
          return {listed, back, def, gone, at: [R.left + q[0], R.top + q[1]]};
        }""")
        check("presets: saved and listed, loaded back (1.25, 30), Revert to Defaults (0, 0), deleted",
              r["listed"] and r["back"] == [1.25, 30] and r["def"] == [0, 0] and r["gone"], r)
        await pg.keyboard.down("Control")
        await pg.mouse.click(*r["at"])
        await pg.keyboard.up("Control")
        await pg.wait_for_timeout(300)
        q = await pg.evaluate("""(() => { const e = document.querySelector('.pcgquick');
          return {open: !!e, rows: e ? e.querySelectorAll('.row').length : 0,
                  sel: [...(app.canvas.selectedItems || [])].length}; })()""")
        await pg.keyboard.press("Escape")
        await pg.wait_for_timeout(200)
        gone = await pg.evaluate("!document.querySelector('.pcgquick')")
        check("Ctrl+click a node: its panel next to it, nothing selected; Esc closes it",
              q["open"] and q["rows"] > 5 and q["sel"] == 0 and gone, q)

        real = [e for e in errs if "three" not in e]
        check("no page errors", not real, real[:2])
        await b.close()


asyncio.run(main())
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
