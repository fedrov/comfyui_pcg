// Export the node icons for the HTML docs: docs/_data/icons.json
//   { "glyphs": { name: "<path .../>..." }, "nodes": { "PCG_Box": ["box", "#hex"], ... } }
// Glyph paths are drawn in a 32x32 box with stroke / fill = currentColor, so the docs can colour them per
// category (the colour ComfyUI uses for the title icon). Run after adding nodes or icons:
//   node tools/render_doc_icons.mjs
// docs/build_html.py reads the JSON; nothing at runtime depends on it.
import fs from "fs";
import os from "os";
import path from "path";
import { fileURLToPath } from "url";
import { SvgCtx } from "./svgctx.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.dirname(HERE);
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "pcgdocicons-"));
const EXT = path.join(ROOT, "extensions", "comfyui_pcg");
fs.mkdirSync(path.join(ROOT, "scripts"), { recursive: true });
fs.mkdirSync(EXT, { recursive: true });
fs.writeFileSync(path.join(ROOT, "scripts", "app.js"), "export const app = globalThis.__app;\n");
fs.writeFileSync(path.join(ROOT, "package.json"), '{"type":"module"}\n');
fs.copyFileSync(path.join(REPO, "web", "pcg_icons.js"), path.join(EXT, "pcg_icons.js"));
globalThis.__app = { registerExtension() {} };
const M = await import(path.join(EXT, "pcg_icons.js"));

const nodes = JSON.parse(fs.readFileSync(path.join(REPO, "tools", "nodes.json"), "utf8"));
const round = (s) => s.replace(/-?\d+\.\d+(e-?\d+)?/g, (m) => {
  const v = Math.round(parseFloat(m) * 10) / 10;
  return String(Object.is(v, -0) ? 0 : v);
});

const used = new Set();
const out = { glyphs: {}, nodes: {} };
for (const id of Object.keys(nodes).sort()) {
  const cat = nodes[id];
  const g = M.glyphFor(id, cat);
  used.add(g);
  out.nodes[id] = [g, M.colorFor(cat)];
}
for (const g of [...used].sort()) {
  const ctx = new SvgCtx();
  ctx.arcSegments = 20;  // 32px icons: 20 segments per full circle are smooth enough
  M.drawGlyph(ctx, g, 16, 16, 26, "currentColor", 2.0);
  // Opacity 1 and the round joins / caps are the defaults of the <svg> the docs wrap these paths in
  out.glyphs[g] = round(ctx.out.join("")).replace(/ (stroke|fill)-opacity="1"/g, "")
    .replace(/ stroke-linejoin="round" stroke-linecap="round"/g, "");
}
const dst = path.join(REPO, "docs", "_data", "icons.json");
fs.writeFileSync(dst, JSON.stringify(out, null, 0).replace(/\],"/g, '],\n"') + "\n");
console.log(`${Object.keys(out.nodes).length} nodes, ${used.size} glyphs -> ${dst}`);
