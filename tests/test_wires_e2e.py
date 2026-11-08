"""
End-to-end tests for the Houdini feel (pcg_wires.js): run in the **real ComfyUI frontend** with a **real mouse** (Playwright).

Like test_panel_e2e.py, it needs a running ComfyUI with its address in PCG_E2E_URL; skipped if unset.
It checks what the jsdom unit test (test_wires.mjs) cannot -- the frontend's own wire dragging, hit testing and snapping on a real canvas:
  · the link render mode is forced to Straight, and the path the frontend stores for hit testing (link.path) is rounded:
    the sharp corner point is not on the wire, the vertical segment is
  · pressing near the input end of a wire and dragging onto another node's input = rewire downstream; near the output end onto another output = swap upstream;
    a click without dragging changes nothing; unplugging and dropping on empty space = disconnect
  · dragging a node to a few pixels from level: snaps (both slots at the same height)
  · Y-key cutting uses the rounded polyline: cutting across only the vertical segment (where the old bezier test could not reach) also cuts
  · switching the setting back to "Follow ComfyUI": link render mode restored
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
    print("  (PCG_E2E_URL not set or playwright not installed, skipping the real-frontend test)")
    print("\n0/0 passed")
    sys.exit(0)

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


SETUP = """async () => {
  app.graph.clear();
  const mk = (t, x, y, title) => { const n = LiteGraph.createNode(t); n.pos = [x, y];
                                   n.title = title; app.graph.add(n); return n; };
  const box = mk('PCG_Box', 80, 120, 'box');
  mk('PCG_Sphere', 80, 560, 'sphere');
  const t1 = mk('PCG_Transform', 540, 300, 't1');
  mk('PCG_Transform', 540, 640, 't3');
  box.connect(0, t1, 0);
  app.canvas.ds.scale = 1; app.canvas.ds.offset = [0, 0];
  await new Promise(r => setTimeout(r, 700));
  app.canvas.setDirty(true, true); app.canvas.draw(true, true);
}"""

# slot positions in screen coordinates
PORTS = """(names) => { const g = app.graph; const by = (t) => g._nodes.find(n => n.title === t);
  const r = app.canvas.canvas.getBoundingClientRect();
  return Object.fromEntries(names.map(([k, t, isIn]) => {
    const p = by(t).getConnectionPos(isIn, 0, [0, 0]); return [k, [p[0] + r.left, p[1] + r.top]]; })); }"""

STATE = """() => Object.fromEntries(app.graph._nodes.map(n => [n.title,
  (n.inputs || []).filter(i => i.link != null && !i.widget).map(i => {
    const l = app.graph.links.get ? app.graph.links.get(i.link) : app.graph.links[i.link];
    return app.graph.getNodeById(l.origin_id).title; })]))"""


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1400, "height": 1000})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: m.type == "error" and "pcg" in m.text.lower() and errs.append(m.text))
        await pg.goto(URL, wait_until="networkidle")
        await pg.wait_for_function("window.app && window.app.graph", timeout=90000)
        await pg.wait_for_timeout(2500)
        for _ in range(3):
            await pg.keyboard.press("Escape")
            await pg.wait_for_timeout(150)
        await pg.evaluate("document.querySelectorAll('.p-dialog-mask').forEach(e=>e.remove())")

        async def drag(a, z):
            await pg.mouse.move(a[0], a[1] - 30)
            await pg.mouse.move(*a, steps=4)
            await pg.wait_for_timeout(120)
            await pg.mouse.down()
            await pg.mouse.move(*z, steps=15)
            await pg.wait_for_timeout(120)
            await pg.mouse.move(z[0] + 1, z[1], steps=2)
            await pg.mouse.up()
            await pg.wait_for_timeout(400)

        sec("Wire style: rounded polyline")
        await pg.evaluate(SETUP)
        r = await pg.evaluate("""async () => {
          const W = await import('/extensions/comfyui_pcg/pcg_wires.js');
          const l = [...(app.graph.links.values ? app.graph.links.values() : Object.values(app.graph.links))][0];
          const box = app.graph._nodes.find(n => n.title === 'box'), t1 = app.graph._nodes.find(n => n.title === 't1');
          const a = box.getConnectionPos(false, 0, [0, 0]), b = t1.getConnectionPos(true, 0, [0, 0]);
          const e = W.elbow(a, b), xv = e.pts[2][0], m = (a[0] + b[0]) / 2;
          const ctx = app.canvas.ctx; ctx.save(); ctx.lineWidth = 4;
          const corner = ctx.isPointInStroke(l.path, xv, a[1]);        // corner point (on the wire if sharp)
          const vert = ctx.isPointInStroke(l.path, xv, (a[1] + b[1]) / 2);
          const mid = ctx.isPointInStroke(l.path, m, (a[1] + b[1]) / 2);  // where the frontend's Straight vertical segment is
          const c = l._pos ? [l._pos[0], l._pos[1]] : null;              // the dot/arrow in the middle of the wire
          const dot = !!c && ctx.isPointInStroke(l.path, c[0], c[1]);
          const half = W.midpointOf(W.elbowPolyline(a, b));
          ctx.restore();
          return {mode: app.canvas.links_render_mode, S: LiteGraph.STRAIGHT_LINK, hasPath: !!l.path,
                  r: e.r, nearSrc: xv - a[0], corner, vert, mid, c, dot, half: [half.x, half.y]};
        }""")
        check("link render mode forced to Straight; the frontend's stored hit path is Houdini's rounded wire: vertical segment hugs the output (exit + radius 40), "
              "the corner point is not on the wire, nor is the point halfway between the two slots",
              r["mode"] == r["S"] and r["hasPath"] and r["r"] == 40 and r["nearSrc"] == 48
              and not r["corner"] and r["vert"] and not r["mid"], r)
        check("the marker in the middle of the wire lies on the rounded wire (at half the arc length), not floating in the empty space halfway between the slots",
              r["dot"] and r["c"] and abs(r["c"][0] - r["half"][0]) < 0.5 and abs(r["c"][1] - r["half"][1]) < 0.5,
              (r["c"], r["half"], r["dot"]))

        sec("Rewiring by dragging wire ends")
        P = await pg.evaluate(PORTS, [["t1In", "t1", True], ["t3In", "t3", True]])
        grab = [P["t1In"][0] - 14, P["t1In"][1]]
        await pg.mouse.move(*grab, steps=4)
        await pg.wait_for_timeout(150)
        cur = await pg.evaluate("app.canvas.canvas.style.cursor")
        await pg.mouse.click(*grab)
        await pg.wait_for_timeout(300)
        s0 = await pg.evaluate(STATE)
        check("hovering near the input end of a wire: cursor becomes a hand; a click without dragging: nothing changes",
              cur == "grab" and s0["t1"] == ["box"] and s0["t3"] == [], (cur, s0))
        await drag(grab, P["t3In"])
        s1 = await pg.evaluate(STATE)
        check("dragging the input end onto t3's input: rewires downstream (box -> t3, t1 disconnected)",
              s1["t3"] == ["box"] and s1["t1"] == [], s1)
        P = await pg.evaluate(PORTS, [["boxOut", "box", False], ["sphOut", "sphere", False]])
        await drag([P["boxOut"][0] + 14, P["boxOut"][1]], P["sphOut"])
        s2 = await pg.evaluate(STATE)
        check("dragging the output end onto sphere's output: swaps upstream (sphere -> t3)", s2["t3"] == ["sphere"], s2)
        P = await pg.evaluate(PORTS, [["t3In", "t3", True]])
        await drag([P["t3In"][0] - 14, P["t3In"][1]], [300, 900])
        for _ in range(2):
            await pg.keyboard.press("Escape")
            await pg.wait_for_timeout(120)
        s3 = await pg.evaluate(STATE)
        check("unplugging the input end and dropping on empty space: disconnects", s3["t3"] == [], s3)

        sec("Node drag snapping")
        await pg.evaluate(SETUP)
        await pg.evaluate("""() => { const g = app.graph; const by = (t) => g._nodes.find(n => n.title === t);
                                     by('sphere').connect(0, by('t3'), 0); }""")
        tb = await pg.evaluate("""() => { const g = app.graph; const by = (t) => g._nodes.find(n => n.title === t);
          const n = by('sphere'), r = app.canvas.canvas.getBoundingClientRect();
          const s = n.getConnectionPos(false, 0, [0, 0]), t = by('t3').getConnectionPos(true, 0, [0, 0]);
          return {title: [n.pos[0] + 60 + r.left, n.pos[1] - 15 + r.top], dy: t[1] - s[1]}; }""")
        await pg.mouse.move(*tb["title"])
        await pg.mouse.down()
        await pg.mouse.move(tb["title"][0] + 40, tb["title"][1] + tb["dy"] - 3, steps=20)
        await pg.wait_for_timeout(150)
        mid = await pg.evaluate("""() => { const g = app.graph; const by = (t) => g._nodes.find(n => n.title === t);
          return [by('sphere').getConnectionPos(false, 0, [0, 0])[1], by('t3').getConnectionPos(true, 0, [0, 0])[1]]; }""")
        await pg.mouse.up()
        await pg.wait_for_timeout(300)
        end = await pg.evaluate("""() => { const g = app.graph; const by = (t) => g._nodes.find(n => n.title === t);
          return [by('sphere').getConnectionPos(false, 0, [0, 0])[1], by('t3').getConnectionPos(true, 0, [0, 0])[1],
                  by('sphere')._pcgRaw === undefined]; }""")
        check("dragging sphere to 3 px from level: snaps while dragging, stays snapped after release",
              tb["dy"] > 40 and mid[0] == mid[1] and end[0] == end[1] and end[2], (tb["dy"], mid, end))

        sec("Y-key cutting uses the rounded polyline")
        await pg.evaluate(SETUP)
        seg = await pg.evaluate("""async () => { const g = app.graph; const by = (t) => g._nodes.find(n => n.title === t);
          const W = await import('/extensions/comfyui_pcg/pcg_wires.js');
          const a = by('box').getConnectionPos(false, 0, [0, 0]), b = by('t1').getConnectionPos(true, 0, [0, 0]);
          const r = app.canvas.canvas.getBoundingClientRect(); const xv = W.elbow(a, b).pts[2][0];
          const y = (a[1] + b[1]) / 2;   // middle of the vertical segment: at this height the old bezier is already far to the right
          return [[xv - 12 + r.left, y + r.top], [xv + 12 + r.left, y + r.top]]; }""")
        # negative control: the same stroke does not reach this wire under the old bezier test
        old = await pg.evaluate("""async (seg) => {
          const W = await import('/extensions/comfyui_pcg/pcg_wires.js');
          const g = app.graph; const by = (t) => g._nodes.find(n => n.title === t);
          const a = by('box').getConnectionPos(false, 0, [0, 0]), b = by('t1').getConnectionPos(true, 0, [0, 0]);
          const r = app.canvas.canvas.getBoundingClientRect();
          const p0 = [seg[0][0] - r.left, seg[0][1] - r.top], p1 = [seg[1][0] - r.left, seg[1][1] - r.top];
          const hit = (pts) => pts.some((q, i) => i && Math.min(pts[i - 1][1], q[1]) <= p0[1]
                                && Math.max(pts[i - 1][1], q[1]) >= p0[1]
                                && (() => { const t = (p0[1] - pts[i - 1][1]) / ((q[1] - pts[i - 1][1]) || 1e-9);
                                            const x = pts[i - 1][0] + t * (q[0] - pts[i - 1][0]);
                                            return x >= p0[0] && x <= p1[0]; })());
          return {bezier: hit(W.splinePolyline(a, b)), elbow: hit(W.elbowPolyline(a, b))};
        }""", seg)
        check("  negative control: the same stroke misses under the old bezier test, hits under the rounded polyline", not old["bezier"] and old["elbow"], old)
        await pg.mouse.move(*seg[0])
        await pg.keyboard.down("y")
        await pg.mouse.down()
        await pg.mouse.move(*seg[1], steps=8)
        await pg.mouse.up()
        await pg.keyboard.up("y")
        await pg.wait_for_timeout(300)
        s4 = await pg.evaluate(STATE)
        check("holding Y and stroking across the vertical segment (only 24 px long): this wire is cut", s4["t1"] == [], s4)

        sec("Switching the setting back to 'Follow ComfyUI'")
        r = await pg.evaluate("""async () => {
          const before = app.canvas.links_render_mode;
          await app.extensionManager.setting.set('PCG.Wire.Style', 'Follow ComfyUI setting');
          app.canvas.draw(true, true); await new Promise(r => setTimeout(r, 100));
          const after = app.canvas.links_render_mode;
          const comfy = app.extensionManager.setting.get('Comfy.LinkRenderMode');
          await app.extensionManager.setting.set('PCG.Wire.Style', 'Houdini rounded polyline');
          app.canvas.draw(true, true);
          return {before, after, comfy, back: app.canvas.links_render_mode};
        }""")
        check("switching back: link render mode restored to ComfyUI's setting; switching to Houdini again forces Straight",
              r["before"] == 0 and r["after"] == r["comfy"] and r["back"] == 0, r)

        real = [e for e in errs if "three" not in e]
        for e in real:
            print("  ERR", e[:300])
        check("no PCG-related errors on the page during the whole run", not real)
        await b.close()


asyncio.run(main())
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
