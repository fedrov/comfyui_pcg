// comfyui_pcg/web/pcg_shake.js
//
// Shaking a node left/right while dragging -> disconnect all its links, matching Houdini's shake to disconnect.
//
// Detection uses **screen pixels**, not graph coordinates: graph coordinates change with zoom; the same hand motion is
// hundreds of units when zoomed in and only a few when zoomed out, so no threshold works. Screen pixels map one-to-one to feel.
//
// Events go through a capture listener on the canvas element, without intercepting or preventing default -- the drag itself must proceed
// as normal; we only observe and sample. This approach is proven in cutlinks / align / palette.

import { app } from "../../scripts/app.js";

const MIN_SEG = 14;        // minimum screen displacement of one valid swing (px)
const NEED = 4;            // number of direction reversals needed within the window
const WINDOW = 700;        // time window (ms)
const FLASH = 500;         // how long to highlight after disconnecting (ms)
const COOLDOWN = 900;      // no detection for this long after triggering (ms)

let lastX = null, lastDir = 0, accum = 0;
let flips = [];
let flash = null;          // { node, until }
let coolUntil = 0;

function reset() {
  lastX = null;
  lastDir = 0;
  accum = 0;
  flips = [];
}

function draggedNode(canvas) {
  // Fields differ between frontend versions; try each; if none, fall back to "the single selected node"
  const n = canvas.node_dragged || canvas.current_node_dragged;
  if (n) return n;
  const sel = canvas.selected_nodes;
  const list = sel instanceof Map ? [...sel.values()] : Object.values(sel || {});
  return list.length === 1 ? list[0] : null;
}

function disconnectAll(node) {
  let n = 0;
  app.graph.beforeChange?.();
  for (let i = 0; i < (node.inputs?.length || 0); i++) {
    if (node.inputs[i].link != null) {
      node.disconnectInput(i);
      n++;
    }
  }
  for (let i = 0; i < (node.outputs?.length || 0); i++) {
    const links = node.outputs[i].links;
    if (links && links.length) {
      n += links.length;
      node.disconnectOutput(i);
    }
  }
  app.graph.afterChange?.();
  return n;
}

app.registerExtension({
  name: "pcg.shake",

  async setup() {
    const canvas = app.canvas;
    const el = canvas?.canvas;
    if (!el) {
      console.warn("[pcg.shake] cannot get the canvas, shake to disconnect disabled");
      return;
    }

    el.addEventListener("pointerdown", () => reset(), true);
    el.addEventListener("pointerup", () => reset(), true);

    el.addEventListener("pointermove", (e) => {
      if (e.buttons !== 1) { reset(); return; }
      const node = draggedNode(canvas);
      if (!node) { reset(); return; }

      if (lastX === null) { lastX = e.clientX; return; }
      const dx = e.clientX - lastX;
      lastX = e.clientX;
      if (Math.abs(dx) < 1) return;

      const dir = Math.sign(dx);
      if (dir === lastDir || lastDir === 0) {
        accum += Math.abs(dx);
        lastDir = dir;
        return;
      }
      // Direction changed: it only counts as a valid swing if the previous segment travelled far enough,
      // otherwise hand jitter or tiny offsets during a normal drag would be counted
      if (accum >= MIN_SEG) {
        const now = performance.now();
        flips.push(now);
        flips = flips.filter((t) => now - t <= WINDOW);
        if (flips.length >= NEED && now >= coolUntil) {
          coolUntil = now + COOLDOWN;
          const n = disconnectAll(node);
          reset();
          if (n) {
            flash = { node, until: performance.now() + FLASH };
            console.log(`[pcg.shake] disconnected ${n} links: ${node.title || node.type}`);
          }
        }
      }
      accum = Math.abs(dx);
      lastDir = dir;
    }, true);

    // Flash after disconnecting so the user can confirm the action took effect
    const prev = canvas.onDrawForeground;
    canvas.onDrawForeground = function (ctx, area) {
      prev?.apply(this, arguments);
      if (!flash) return;
      const left = flash.until - performance.now();
      if (left <= 0) { flash = null; return; }
      const n = flash.node;
      const s = this.ds?.scale || 1;
      ctx.save();
      ctx.globalAlpha = Math.min(1, left / FLASH);
      ctx.strokeStyle = "#ff9a3c";
      ctx.lineWidth = 2.5 / s;
      ctx.setLineDash([9 / s, 6 / s]);
      const th = window.LiteGraph?.NODE_TITLE_HEIGHT ?? 30;
      ctx.strokeRect(n.pos[0] - 4, n.pos[1] - th - 4,
                     n.size[0] + 8, n.size[1] + th + 8);
      ctx.restore();
      this.setDirty(true, true);          // keep the fade-out animating
    };

    console.log("[pcg.shake] enabled: shake a node left/right while dragging to disconnect all its links");
  },
});
