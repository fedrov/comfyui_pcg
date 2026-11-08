// Tests for showing the original type on renamed nodes (pcg_typehint.js). No jsdom: a stubbed app + a recording ctx.
//
// What is checked are the things that would go wrong silently:
//   - nodes that weren't renamed are not drawn (otherwise every node title is followed by a duplicate string)
//   - renamed ones draw the "original type", placed after the title text, not running past the node's right edge; PCG drops the (PCG) suffix
//   - not drawn when it doesn't fit / collapsed / zoomed far out / setting off; with "PCG nodes only" other nodes aren't drawn
//   - whatever was already hooked on onDrawForeground / getExtraMenuOptions is still called (the chain must not break)
//   - context menu: full original node name + internal class name; "Restore original name" changes the title back
//   - what's drawn doesn't go into the data: node.title unchanged
import fs from "fs";
import os from "os";
import path from "path";
import { fileURLToPath } from "url";

const _HERE = path.dirname(fileURLToPath(import.meta.url));
function pkgRoot() {
  let d = _HERE;
  for (let i = 0; i < 4; i++) {
    if (fs.existsSync(path.join(d, "comfyui_pcg"))) return d;
    d = path.dirname(d);
  }
  return "/tmp/pcgpkg";
}
const PKG = pkgRoot();
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "jstest_"));
process.on("exit", () => fs.rmSync(ROOT, { recursive: true, force: true }));
const EXT = path.join(ROOT, "extensions", "comfyui_pcg");
fs.mkdirSync(path.join(ROOT, "scripts"), { recursive: true });
fs.mkdirSync(EXT, { recursive: true });
fs.writeFileSync(path.join(ROOT, "scripts", "app.js"),
                 "export const app = globalThis.__app;\n");
fs.copyFileSync(path.join(PKG, "comfyui_pcg", "web", "pcg_typehint.js"),
                path.join(EXT, "pcg_typehint.js"));

let SETTING = undefined;
let dirty = 0;
const exts = [];
globalThis.LiteGraph = { NODE_TITLE_HEIGHT: 30, NODE_TEXT_SIZE: 14, NODE_FONT: "Arial" };
globalThis.__app = {
  registerExtension(e) { exts.push(e); },
  extensionManager: { setting: { get: (id) => SETTING } },
  canvas: { ds: { scale: 1 }, title_text_font: "14px Arial" },
  graph: { setDirtyCanvas() { dirty++; } },
};
const M = await import(path.join(EXT, "pcg_typehint.js"));
const ext = exts[0];

const OK = [];
function check(name, cond, extra = "") {
  OK.push(!!cond);
  console.log((cond ? "  PASS  " : "  FAIL  ") + name + (extra === "" ? "" : "   " + extra));
}

// Recording ctx: measureText width = char count × font size × 0.6 (CJK counts as 1 font size)
class Ctx {
  constructor() { this.texts = []; this.font = "10px Arial"; this.depth = 0; }
  save() { this.depth++; } restore() { this.depth--; }
  measureText(s) {
    const px = parseFloat(this.font) || 10;
    let w = 0;
    for (const ch of String(s)) w += ch.charCodeAt(0) > 0x2e80 ? px : px * 0.6;
    return { width: w };
  }
  fillText(t, x, y) { this.texts.push({ t, x, y, font: this.font }); }
}

function makeType(nodeData) {
  const calls = { draw: 0, menu: 0 };
  function T() {}
  T.title = nodeData.display_name;
  T.prototype.onDrawForeground = function () { calls.draw++; };
  T.prototype.getExtraMenuOptions = function (c, o) { calls.menu++; o.push({ content: "old" }); };
  ext.beforeRegisterNodeDef(T, nodeData);
  return { T, calls };
}
function node(T, title, w = 320, flags = {}) {
  const n = new T();
  n.title = title; n.size = [w, 200]; n.flags = flags;
  return n;
}
function draw(n) { const c = new Ctx(); n.onDrawForeground(c); return c; }

const tube = { name: "PCG_Tube", display_name: "Tube (PCG)" };
const ks = { name: "KSampler", display_name: "KSampler" };
const { T: Tube, calls } = makeType(tube);
const { T: KS } = makeType(ks);

check("setting registered: three options, default All nodes", ext.settings?.[0]?.id === M.SETTING_ID
      && JSON.stringify(ext.settings[0].options) === JSON.stringify(M.MODES)
      && ext.settings[0].defaultValue === "All nodes");

let c = draw(node(Tube, "Tube (PCG)"));
check("not renamed: not drawn", c.texts.length === 0);
check("  the original onDrawForeground still called", calls.draw === 1);
c = draw(node(Tube, "  Tube (PCG) "));
check("  a title that only gained leading/trailing spaces counts as not renamed", c.texts.length === 0);

const n1 = node(Tube, "Tree Proxy");
c = draw(n1);
const t = c.texts[0];
const titleW = 10 * 14 * 0.6;                           // ten ASCII chars × 14px × 0.6
check("renamed: draws a hint whose text is the original type without (PCG)", c.texts.length === 1 && t.t === "Tube",
      JSON.stringify(c.texts));
check("  drawn after the title text (x = title bar height + title width + gap), vertically centered in the title bar",
      t && Math.abs(t.x - (30 + titleW + 10)) < 1e-9 && t.y === -15, t && `${t.x},${t.y}`);
check("  smaller text than the title", t && parseFloat(t.font) < 14);
check("  save / restore paired", c.depth === 0);
check("  node.title not changed (what's drawn doesn't go into the workflow)", n1.title === "Tree Proxy");

c = draw(node(KS, "My Sampler"));
check("non-PCG nodes are drawn too (default all), without a (PCG) suffix shown as is", c.texts[0]?.t === "KSampler");

c = draw(node(Tube, "A very, very, very, very long name", 240));
check("not drawn when it doesn't fit (title too long / node too narrow)", c.texts.length === 0);
c = draw(node(Tube, "Tree Proxy", 240));
check("  same name, node wide enough: drawn", c.texts.length === 1);
{
  const a = draw(node(Tube, "Tree Proxy", 30 + titleW + 10 + 26.4 + 8 + 1));
  const b = draw(node(Tube, "Tree Proxy", 30 + titleW + 10 + 26.4 + 8 - 1));
  check("  boundary: 8 px kept on the right, drawn when it just fits, not drawn 1 px short", a.texts.length === 1 && b.texts.length === 0);
}
c = draw(node(Tube, "Tree Proxy", 320, { collapsed: true }));
check("collapsed nodes not drawn", c.texts.length === 0);
__app.canvas.ds.scale = 0.4;
c = draw(node(Tube, "Tree Proxy"));
check("canvas zoomed far out (< 0.5): not drawn", c.texts.length === 0);
__app.canvas.ds.scale = 1;

SETTING = "PCG nodes only";
check("setting = PCG nodes only: PCG drawn, others not",
      draw(node(Tube, "Tree Proxy")).texts.length === 1 && draw(node(KS, "My Sampler")).texts.length === 0);
SETTING = "Off";
check("setting = Off: nothing drawn", draw(node(Tube, "Tree Proxy")).texts.length === 0
      && draw(node(KS, "My Sampler")).texts.length === 0);
SETTING = "garbage value";
check("unrecognized setting value: falls back to the default (All nodes)", draw(node(KS, "My Sampler")).texts.length === 1);
SETTING = undefined;
{
  const saved = __app.extensionManager;
  __app.extensionManager = undefined;
  __app.ui = { settings: { getSettingValue: () => "Off" } };
  check("the old frontend (app.ui.settings) can read the setting too", draw(node(Tube, "Tree Proxy")).texts.length === 0);
  __app.extensionManager = saved;
  delete __app.ui;
}

// Context menu
const opts = [];
const n2 = node(Tube, "Tree Proxy");
n2.getExtraMenuOptions({}, opts);
const info = opts.find((o) => o && String(o.content).startsWith("Original node"));
const reset = opts.find((o) => o && String(o.content).startsWith("Restore original name"));
check("context menu: the original menu items are still there", calls.menu === 1 && opts[0]?.content === "old");
check("  one extra item 'Original node: full name [internal class name]', read-only", info?.content === "Original node: Tube (PCG)  [PCG_Tube]"
      && info.disabled === true, info?.content);
reset?.callback();
check("  'Restore original name' changes the title back to the display name, redraws the canvas", n2.title === "Tube (PCG)" && dirty > 0);
check("  after restoring, the hint is no longer drawn", draw(n2).texts.length === 0);
const opts2 = [];
node(KS, "KSampler").getExtraMenuOptions({}, opts2);
check("nodes that weren't renamed get no menu item", opts2.length === 1);
const opts3 = [];
node(KS, "My Sampler").getExtraMenuOptions({}, opts3);
check("  when internal class name equals display name it isn't repeated", opts3.some((o) => o?.content === "Original node: KSampler"));

// A failing draw must not throw out
{
  const bad = node(Tube, "Tree Proxy");
  const ctx = new Ctx();
  ctx.measureText = () => { throw new Error("boom"); };
  let threw = false;
  try { bad.onDrawForeground(ctx); } catch (e) { threw = true; }
  check("errors in ctx are swallowed, don't take down the canvas", !threw);
}

const pass = OK.filter(Boolean).length;
console.log(`\n${pass}/${OK.length} passed`);
process.exit(pass === OK.length ? 0 : 1);
