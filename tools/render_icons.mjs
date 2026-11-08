// Render all icons into one contact sheet (SVG), to **take a look** before deciding which to change.
//
// No node-canvas (it needs a native extension compiled). This writes a minimal canvas 2D shim
// that translates drawing calls straight into SVG paths -- the icons use only a dozen or so operations.
// It doubles as a check: an icon using an operation the shim does not implement throws on the spot.
import fs from "fs";
import os from "os";
import path from "path";

import { fileURLToPath } from "url";
import { SvgCtx } from "./svgctx.mjs";

const _HERE = path.dirname(fileURLToPath(import.meta.url));
// pcg_icons.js: the repo root is the plugin folder (tools/ sits next to web/)
const ICONS_JS = path.join(path.dirname(_HERE), "web", "pcg_icons.js");
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "pcgicons-"));
const EXT = path.join(ROOT, "extensions", "comfyui_pcg");
fs.mkdirSync(path.join(ROOT, "scripts"), { recursive: true });
fs.mkdirSync(EXT, { recursive: true });
fs.writeFileSync(path.join(ROOT, "scripts", "app.js"),
                 "export const app = globalThis.__app;\n");
fs.copyFileSync(ICONS_JS,
                path.join(EXT, "pcg_icons.js"));
globalThis.__app = { registerExtension() {} };

const M = await import(path.join(EXT, "pcg_icons.js"));

// ── contact sheet ────────────────────────────────────────────────────────────
const names = Object.keys(M.GLYPHS);
// --small renders at **real pixel size** (title height 24 -> icon 15px). Looking at the enlarged one is not enough:
// detailed icons smear into a blob at 15px, and that is what you actually see
const SMALL = process.argv.includes("--small");
const ZOOM = SMALL ? 1 : 3;
const COLS = SMALL ? 20 : 10;
const CELL = SMALL ? 26 : 88, PAD = SMALL ? 6 : 14, LABEL = SMALL ? 0 : 16;
const rows = Math.ceil(names.length / COLS);
const W = COLS * CELL + PAD * 2;
const H = rows * (CELL + LABEL) + PAD * 2 + (SMALL ? 6 : 30);

const body = [];
names.forEach((n, i) => {
  const cx = PAD + (i % COLS) * CELL + CELL / 2;
  const cy = PAD + (SMALL ? 0 : 30) + Math.floor(i / COLS) * (CELL + LABEL)
             + CELL / 2;
  const ctx = new SvgCtx();
  // Draw at the real usage size: title height 24 -> icon ~15px. Enlarged 3x here to see details,
  // with line width scaled by the same ratio, so what you see is the real thickness ratio
  M.drawGlyph(ctx, n, cx, cy, 24 * 0.62 * ZOOM, "#dde3ea", 1.5 * ZOOM);
  const hb = SMALL ? 12 : 40;
  body.push(`<rect x="${cx - hb}" y="${cy - hb}" width="${hb * 2}"`
            + ` height="${hb * 2}" fill="#23282f" stroke="#343b44"/>`);
  body.push(...ctx.out);
  if (!SMALL) {
    body.push(`<text x="${cx}" y="${cy + 52}" fill="#8b95a3" font-size="10"`
              + ` font-family="monospace" text-anchor="middle">${n}</text>`);
  }
});

const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}"
  viewBox="0 0 ${W} ${H}"><rect width="${W}" height="${H}" fill="#171a1f"/>
  ${SMALL ? "" : `<text x="${PAD}" y="${PAD + 18}" fill="#dde3ea"
    font-size="15" font-family="monospace">comfyui_pcg node icons
    (${names.length})</text>`}
  ${body.join("\n")}</svg>`;

const out = process.argv[2] || "/tmp/icons.svg";
fs.writeFileSync(out, svg);
console.log(`${names.length} icons -> ${out}`);
