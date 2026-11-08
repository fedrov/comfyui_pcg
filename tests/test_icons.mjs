// Tests for node icons. jsdom + a stubbed app; the module really runs.
//
// What is tested is not "do the icons look good" (for that, render them with tools/render_icons.mjs and look),
// but four kinds of things that **fail silently**:
//   · coverage: a new node added without an icon -- quietly falls back to the category default and looks like it "has an icon"
//   · staleness: after a node is renamed, dead entries pointing at nonexistent nodes stay in the mapping table
//   · out of bounds: an icon drawn outside [-1,1] overlaps the text in the title bar or overflows the node
//   · lookalikes: two icons drawn exactly the same (copy-paste, forgot to change)
import { JSDOM } from "jsdom";
import fs from "fs";
import os from "os";
import path from "path";

import { fileURLToPath } from "url";
// Package root: first search upward from this file's location, then fall back to the old sandbox path.
// These suites are now the only copy (the sandbox gets reclaimed), so paths can't be hard-coded any more
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
// A **new** temp directory per run (pcg64): it used to be hard-coded to "/tmp/jstest"; with two regressions running in parallel
// one side's rmSync hit files the other side was importing, which is how test_camlink once died; also
// test_icons / test_playbar used the same directory. Deleted after the run
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "jstest_"));
process.on("exit", () => fs.rmSync(ROOT, { recursive: true, force: true }));
const EXT = path.join(ROOT, "extensions", "comfyui_pcg");
fs.mkdirSync(path.join(ROOT, "scripts"), { recursive: true });
fs.mkdirSync(EXT, { recursive: true });
fs.writeFileSync(path.join(ROOT, "scripts", "app.js"),
                 "export const app = globalThis.__app;\n");
fs.copyFileSync(path.join(PKG, "comfyui_pcg", "web", "pcg_icons.js"),
                path.join(EXT, "pcg_icons.js"));

const dom = new JSDOM("<!doctype html><html><body></body></html>",
                      { url: "http://localhost/" });
for (const k of ["window", "document"]) {
  Object.defineProperty(globalThis, k, {
    value: k === "window" ? dom.window : dom.window[k],
    writable: true, configurable: true,
  });
}

const exts = [];
globalThis.__app = { registerExtension(e) { exts.push(e); } };
const M = await import(path.join(EXT, "pcg_icons.js"));

const OK = [];
function check(name, cond, extra = "") {
  OK.push(!!cond);
  console.log((cond ? "  PASS  " : "  FAIL  ") + name
              + (extra === "" ? "" : "   " + extra));
}

// ── recording ctx: counts draw calls + tracks the bounding box ──────────────────────────────
class RecCtx {
  constructor() {
    this.m = [1, 0, 0, 1, 0, 0];
    this.stack = [];
    this.ops = [];          // drawn paths, used to compare for "lookalikes"
    this.p = [];
    this.strokes = 0;
    this.min = [1e9, 1e9]; this.max = [-1e9, -1e9];
    this.lineWidth = 1; this.globalAlpha = 1;
  }
  set strokeStyle(v) {} set fillStyle(v) {}
  set lineJoin(v) {} set lineCap(v) {}
  setLineDash(d) { this.ops.push("D" + (d || []).join(",")); }
  save() { this.stack.push(this.m.slice()); }
  restore() { if (this.stack.length) this.m = this.stack.pop(); }
  translate(x, y) {
    this.m[4] += this.m[0] * x + this.m[2] * y;
    this.m[5] += this.m[1] * x + this.m[3] * y;
  }
  scale(x, y) { this.m[0] *= x; this.m[1] *= x; this.m[2] *= y; this.m[3] *= y; }
  _t(x, y) {
    return [this.m[0] * x + this.m[2] * y + this.m[4],
            this.m[1] * x + this.m[3] * y + this.m[5]];
  }
  _hit(x, y) {
    // Records **the icon's own** coordinates (before scaling), so they can be compared to [-1,1] directly
    this.min[0] = Math.min(this.min[0], x); this.min[1] = Math.min(this.min[1], y);
    this.max[0] = Math.max(this.max[0], x); this.max[1] = Math.max(this.max[1], y);
  }
  beginPath() { this.p = []; }
  closePath() { this.p.push("Z"); }
  moveTo(x, y) { this._hit(x, y); this.p.push(`M${x.toFixed(4)},${y.toFixed(4)}`); }
  lineTo(x, y) { this._hit(x, y); this.p.push(`L${x.toFixed(4)},${y.toFixed(4)}`); }
  bezierCurveTo(a, b, cc, d, x, y) {
    this._hit(a, b); this._hit(cc, d); this._hit(x, y);
    this.p.push(`C${[a, b, cc, d, x, y].map((v) => v.toFixed(4)).join(",")}`);
  }
  rect(x, y, w, h) { this._hit(x, y); this._hit(x + w, y + h);
                     this.p.push(`R${x},${y},${w},${h}`); }
  arc(cx, cy, r, a0, a1) { this.ellipse(cx, cy, r, r, 0, a0, a1); }
  ellipse(cx, cy, rx, ry, rot, a0, a1) {
    // **Sample along the arc**, don't take the whole ellipse's bounding box: for a semicircle that over-reports by half,
    // and the out-of-bounds check produces false positives (that is how campath got falsely flagged)
    const n = 32;
    const span = Math.min(a1 - a0, Math.PI * 2);
    for (let i = 0; i <= n; i++) {
      const a = a0 + span * (i / n);
      this._hit(cx + Math.cos(a) * rx, cy + Math.sin(a) * ry);
    }
    this.p.push(`A${cx},${cy},${rx},${ry},${a0.toFixed(3)},${a1.toFixed(3)}`);
  }
  stroke() { this.strokes++; this.ops.push("S" + this.p.join("|")); }
  fill() { this.strokes++; this.ops.push("F" + this.p.join("|")); }
  fillRect(x, y, w, h) { this._hit(x, y); this._hit(x + w, y + h);
                         this.strokes++; this.ops.push(`FR${x},${y},${w},${h}`); }
}

// The node table is exported from the **live** NODE_CLASS_MAPPINGS, so "node added without an icon"
// really can be caught. To regenerate:
//   python3 -c "import sys,json; sys.path.insert(0,'.'); import fakecomfy;
//   from comfyui_pcg import nodes as N, expr as E, foreach as FE, framefor as FF;
//   m=dict(N.NODE_CLASS_MAPPINGS);
//   [m.update(x.NODE_CLASS_MAPPINGS) for x in (E,FE,FF)];
//   json.dump({k:getattr(v,'CATEGORY','') for k,v in sorted(m.items())},
//   open('tools/nodes.json','w'), ensure_ascii=False, indent=0)"
// nodes.json lives in different places in the two layouts; search both:
//   sandbox   <root>/tools/nodes.json        (tools next to comfyui_pcg)
//   device   <root>/comfyui_pcg/tools/nodes.json
// Hard-coding only the sandbox path means this suite **can't run at all inside the user's ComfyUI**
// (ENOENT), which is exactly why these suites exist. Verified: laying it out like the device crashes.
function nodesJsonPath() {
  const cands = [path.join(PKG, "tools", "nodes.json"),
                 path.join(PKG, "comfyui_pcg", "tools", "nodes.json")];
  for (const c of cands) if (fs.existsSync(c)) return c;
  throw new Error("tools/nodes.json not found, tried:\n  " + cands.join("\n  ")
    + "\nSee the comment below for the regenerate command.");
}
const NODES = JSON.parse(fs.readFileSync(nodesJsonPath(), "utf8"));
const types = Object.keys(NODES);

console.log("═".repeat(28), "Coverage");
check(`node table has ${types.length} nodes`, types.length > 100, types.length);

const fallback = [];
const missing = [];
for (const t of types) {
  const short = t.replace(M.PREFIX, "");
  const g = M.glyphFor(t, NODES[t]);
  if (!M.GLYPHS[g]) missing.push(t);
  if (!M.NODE_GLYPH[short]) fallback.push(t);
}
check("every node resolves to an **existing** icon", missing.length === 0,
      missing.join(", "));
check("no node falls back to the category default (= no new node missing an icon)",
      fallback.length === 0, fallback.join(", ") || "0");

const stale = Object.keys(M.NODE_GLYPH)
  .filter((s) => !types.includes(M.PREFIX + s));
check("no dead entries in the mapping table pointing at nodes that no longer exist (left behind after renames)",
      stale.length === 0, stale.join(", ") || "0");
const badTarget = Object.entries(M.NODE_GLYPH)
  .filter(([, g]) => !M.GLYPHS[g]).map(([k, g]) => `${k}->${g}`);
check("no entries in the mapping table pointing at nonexistent icons", badTarget.length === 0,
      badTarget.join(", ") || "0");

const cats = [...new Set(Object.values(NODES))];
const noColor = cats.filter((c) => !M.CATEGORY_COLOR[c]);
check(`all ${cats.length} categories have a color`, noColor.length === 0,
      noColor.join(", ") || "0");
const noCatGlyph = cats.filter((c) => !M.CATEGORY_GLYPH[c]);
check("every category has a fallback icon (new nodes still draw something)",
      noCatGlyph.length === 0, noCatGlyph.join(", ") || "0");
check("unknown types don't crash either; they get a generic icon",
      M.GLYPHS[M.glyphFor("PCG_NotARealNode", "PCG/nope")] !== undefined);

console.log("═".repeat(28), "Each icon itself");
const names = Object.keys(M.GLYPHS);
const empty = [], oob = [], sigs = new Map(), dup = [];
for (const n of names) {
  const c = new RecCtx();
  M.drawGlyph(c, n, 0, 0, 2, "#fff", 1);   // size=2 -> scale 1, so coordinates are the raw ones
  if (c.strokes === 0) empty.push(n);
  const lim = 1.02;                        // a little floating-point margin
  if (c.min[0] < -lim || c.min[1] < -lim || c.max[0] > lim || c.max[1] > lim) {
    oob.push(`${n}[${c.min.map((v) => v.toFixed(2))}..`
             + `${c.max.map((v) => v.toFixed(2))}]`);
  }
  const sig = c.ops.join(";");
  if (sigs.has(sig)) dup.push(`${n} == ${sigs.get(sig)}`);
  else sigs.set(sig, n);
}
check(`all ${names.length} icons draw something (no empty icons)`,
      empty.length === 0, empty.join(", ") || "0");
check("all drawn within [-1,1] (outside would overlap the title text)",
      oob.length === 0, oob.join(" ") || "0");
check("no two icons drawn exactly the same (copy-paste, forgot to change)",
      dup.length === 0, dup.join(", ") || "0");

// Real usage: draw every icon used by every node once; must not throw
let threw = null;
for (const t of types) {
  try {
    const c = new RecCtx();
    M.drawGlyph(c, M.glyphFor(t, NODES[t]), 12, -12, 15, "#fff", 1.5);
    if (c.strokes === 0) throw new Error("nothing drawn");
  } catch (e) { threw = `${t}: ${e.message}`; break; }
}
check("drawing the icons of all 125 nodes at real size: no throw, none empty", threw === null,
      threw || "");
// drawGlyph swallows its own exceptions; a broken icon must not take the canvas down with it
const bad = new RecCtx();
M.GLYPHS.__boom = () => { throw new Error("boom"); };
let crashed = false;
try { M.drawGlyph(bad, "__boom", 0, 0, 2, "#fff", 1); }
catch (e) { crashed = true; }
delete M.GLYPHS.__boom;
check("an exception inside an icon doesn't propagate (must not take the whole canvas down)", !crashed);
check("ctx transform stack is flat after drawing (save/restore paired)",
      bad.stack.length === 0, bad.stack.length);

console.log("═".repeat(28), "Hooked into litegraph");
const ext = exts[0];
check("pcg.icons extension registered", ext && ext.name === "pcg.icons");

function fakeType() { return { prototype: {} }; }
const pcg = fakeType();
await ext.beforeRegisterNodeDef(pcg, { name: "PCG_Box",
                                       category: "PCG/generate" });
check("PCG nodes get onDrawTitleBox hooked",
      typeof pcg.prototype.onDrawTitleBox === "function");
const other = fakeType();
await ext.beforeRegisterNodeDef(other, { name: "KSampler",
                                         category: "sampling" });
check("non-PCG nodes are never touched (don't take over others' drawing)",
      other.prototype.onDrawTitleBox === undefined);
await ext.beforeRegisterNodeDef(fakeType(), {});   // empty nodeData
check("no crash when nodeData lacks fields", true);

const node = { prototype: pcg.prototype };
const c2 = new RecCtx();
pcg.prototype.onDrawTitleBox.call(node, c2, 24, [200, 60], 1);
check("one call really draws something", c2.strokes > 0, c2.strokes);
check("**no** color written onto the node (must not enter workflow serialization)",
      node.color === undefined && node.bgcolor === undefined);
let boom = false;
try {
  // Some frontend versions have a different signature; passing fewer arguments must not blow up
  pcg.prototype.onDrawTitleBox.call(node, c2);
} catch (e) { boom = true; }
check("no throw with incomplete arguments (signatures differ between frontend versions)", !boom);

const colors = new Set(Object.values(M.CATEGORY_COLOR));
check("category colors aren't all the same color", colors.size >= 8, colors.size);
check("all colors are valid #rrggbb",
      [...colors].every((v) => /^#[0-9a-f]{6}$/i.test(v)));

const pass = OK.filter(Boolean).length;
console.log(`\n${pass}/${OK.length} passed`);
process.exit(pass === OK.length ? 0 : 1);
