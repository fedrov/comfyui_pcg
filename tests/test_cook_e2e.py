"""
Cook feedback in the real ComfyUI frontend (web/pcg_cook.js + cookstats.py): runs a small graph on the server.

  · after a run every node has its record: time, counts and attributes of what it made
  · changing a parameter marks that node and everything downstream out of date, nothing upstream (negative control)
  · a failing node: the error in its record and a failed row in the performance pane; the others still listed
  · the middle button pressed on a node (real mouse) shows its info; a middle-button drag (a pan) does not
  · a cached run: the nodes not cooked in this page still get what they reported when they last ran

Needs PCG_E2E_URL (as test_panel_e2e.py); skipped otherwise.
"""
import asyncio
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


RUN = """async (code) => {
  const W = (ms) => new Promise(r => setTimeout(r, ms));
  const C = await import('/extensions/comfyui_pcg/pcg_cook.js');
  const w = app.graph._nodes.find(n => n.type === 'PCG_Wrangle');
  w.widgets.find(x => x.name === 'code').value = code;
  const before = C.RUN.start;
  await app.queuePrompt(0, 1);
  for (let i = 0; i < 120; i++) { await W(250); if (C.RUN.start !== before && !C.RUN.running && C.RUN.end) break; }
  await W(400);
  return true;
}"""


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1600, "height": 1000})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(URL, wait_until="networkidle")
        await pg.wait_for_function("window.app && window.app.graph", timeout=90000)
        await pg.wait_for_timeout(2500)
        await pg.evaluate("""async () => {
          app.graph.clear();
          const add = (t, x) => { const n = LiteGraph.createNode(t); n.pos = [x, 200]; app.graph.add(n); return n; };
          const a = add('PCG_Box', 100), t = add('PCG_Transform', 450), w = add('PCG_Wrangle', 800), d = add('PCG_Display', 1150);
          a.connect(0, t, 0); t.connect(0, w, 0); w.connect(0, d, 0);
          t.widgets.find(x => x.name === 'tx').value = Math.random();     // a fresh graph: nothing cached
          app.canvas.ds.scale = 1; app.canvas.ds.offset = [0, 0];
        }""")
        await pg.evaluate(RUN, "@Cd = set(1, 0, 0)")
        r = await pg.evaluate("""async () => {
          const C = await import('/extensions/comfyui_pcg/pcg_cook.js');
          const N = (t) => app.graph._nodes.find(n => n.type === t);
          const rec = (t) => C.COOK.get(C.execId(N(t)));
          const res = {};
          res.box = rec('PCG_Box') && [rec('PCG_Box').ok, rec('PCG_Box').time > 0, rec('PCG_Box').outputs[0].npoints];
          res.wr = Object.keys(rec('PCG_Wrangle').outputs[0].attribs.point);
          C.computeDirty(); res.d0 = C.DIRTY.size;
          N('PCG_Transform').widgets.find(x => x.name === 'ty').value = 3;
          C.computeDirty(); res.d1 = [...C.DIRTY].map(n => n.type).sort();
          return res;
        }""")
        check("after a run: Box's record (ok, time, 8 points), the Wrangle's attributes P and Cd",
              r["box"] == [True, True, 8] and r["wr"] == ["P", "Cd"], r)
        check("  nothing out of date after the run; changing Transform's ty marks it and what is downstream, not Box",
              r["d0"] == 0 and r["d1"] == ["PCG_Display", "PCG_Transform", "PCG_Wrangle"], r)

        await pg.evaluate(RUN, "@Cd = nosuchfn(1)")
        r = await pg.evaluate("""async () => {
          const C = await import('/extensions/comfyui_pcg/pcg_cook.js');
          const w = app.graph._nodes.find(n => n.type === 'PCG_Wrangle');
          const rec = C.COOK.get(C.execId(w));
          C.PERF.pane.setOpen(true); C.renderPane();
          const rows = [...C.PERF.pane.body.querySelectorAll('.row')].map(e => [e.querySelector('.nm').textContent, e.className]);
          const R = app.canvas.canvas.getBoundingClientRect(), q = app.canvas.ds.convertOffsetToCanvas([w.pos[0] + 60, w.pos[1] + 30]);
          return {ok: rec.ok, err: rec.error, rows, at: [R.left + q[0], R.top + q[1]]};
        }""")
        check("a failing Wrangle: its error recorded", r["ok"] is False and "nosuchfn" in (r["err"] or ""), r["err"])
        check("  the performance pane lists the run, the Wrangle as failed",
              any(n == "Wrangle (PCG)" and "error" in c for n, c in r["rows"]) and len(r["rows"]) >= 2, r["rows"])

        x, y = r["at"]
        await pg.mouse.move(x, y)
        await pg.mouse.down(button="middle")
        await pg.wait_for_timeout(250)
        await pg.mouse.up(button="middle")
        await pg.wait_for_timeout(200)
        info = await pg.evaluate("(() => { const e = document.querySelector('.pcg-info'); "
                                 "return e && e.style.display !== 'none' ? e.textContent : null; })()")
        check("middle button pressed on the node: its info (title, failed, the error, the last good result)",
              info and "Wrangle (PCG)" in info and "Failed" in info and "nosuchfn" in info and "Points" in info,
              (info or "")[:160])
        await pg.mouse.click(10, 500)
        await pg.mouse.move(x, y)
        await pg.mouse.down(button="middle")
        await pg.mouse.move(x + 60, y + 40, steps=6)
        await pg.mouse.up(button="middle")
        await pg.wait_for_timeout(250)
        shown = await pg.evaluate("(() => { const e = document.querySelector('.pcg-info'); "
                                  "return !!e && e.style.display !== 'none'; })()")
        check("  a middle-button drag (a pan) shows nothing (negative control)", not shown)

        await pg.evaluate(RUN, "@Cd = set(0, 1, 0)")
        await pg.reload(wait_until="networkidle")
        await pg.wait_for_function("window.app && window.app.graph", timeout=90000)
        await pg.wait_for_timeout(2500)
        await pg.evaluate("""async () => {
          app.graph.clear();
          const add = (t, x) => { const n = LiteGraph.createNode(t); n.pos = [x, 200]; app.graph.add(n); return n; };
          const a = add('PCG_Box', 100), t = add('PCG_Transform', 450), w = add('PCG_Wrangle', 800), d = add('PCG_Display', 1150);
          a.connect(0, t, 0); t.connect(0, w, 0); w.connect(0, d, 0);
        }""")
        # the same graph as before the reload, except Transform (ty = 3 then): Box comes from the cache
        await pg.evaluate("""() => { const t = app.graph._nodes.find(n => n.type === 'PCG_Transform');
          t.widgets.find(x => x.name === 'ty').value = 3; }""")
        await pg.evaluate(RUN, "@Cd = set(0, 1, 0)")
        r = await pg.evaluate("""async () => {
          const C = await import('/extensions/comfyui_pcg/pcg_cook.js');
          const a = app.graph._nodes.find(n => n.type === 'PCG_Box');
          const rec = C.COOK.get(C.execId(a));
          return rec && {cached: rec.cached, pts: rec.outputs?.[0]?.npoints, time: rec.time};
        }""")
        check("after reloading the page, a cached Box still shows what it reported when it ran (from the server)",
              r and r["cached"] and r["pts"] == 8 and (r["time"] or 0) > 0, r)

        real = [e for e in errs if "three" not in e]
        check("no page errors", not real, real[:2])
        await b.close()


asyncio.run(main())
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
