// comfyui_pcg/web/pcg_align.js
//
// Houdini's "select nodes -> Alt + left-drag" auto-arrange: drag vertically for a column, horizontally for a row.
// Canvas-level interaction, independent of any specific node.
//
// A few implementation points:
//
// 1) Measure with getBounding(), not node.pos + node.size. pos[1] is the **bottom edge of the title bar**,
//    size excludes the title height, and collapsed nodes differ again. getBounding gives the full box including
//    the title, so the spacing comes out right.
//
// 2) In some litegraph versions Alt + drag "clones the node", so the event must be caught in the capture
//    phase. Otherwise each arrange leaves a pile of copies.
//
// 3) The main axis is only decided once displacement exceeds a threshold, otherwise a jittery hand picks the wrong axis. Once decided
//    it is locked and not changed during the drag -- switching axes mid-drag makes the preview keep jumping.

import { app } from "../../scripts/app.js";

const MARGIN = 28;          // gap between the boxes of adjacent nodes
const THRESHOLD = 10;       // displacement in pixels before the main axis is decided
const GUIDE = "#5fc4ff";

// Pure function, easy to verify on its own: given a set of boxes, compute the arranged top-left coordinates
// boxes: [{x, y, w, h}]   axis: "v" | "h"
export function planLayout(boxes, axis, margin = MARGIN) {
  const order = boxes.map((b, i) => i)
    .sort((a, b) => axis === "v" ? boxes[a].y - boxes[b].y
                                 : boxes[a].x - boxes[b].x);
  // Cross axis aligned to the mean, so the group as a whole does not shift
  const cross = boxes.reduce((s, b) => s + (axis === "v" ? b.x : b.y), 0)
                / boxes.length;
  // Main axis starts at the current minimum, so after arranging the group stays near where it was
  let cursor = Math.min(...boxes.map((b) => axis === "v" ? b.y : b.x));

  const out = new Array(boxes.length);
  for (const i of order) {
    const b = boxes[i];
    out[i] = axis === "v" ? { x: cross, y: cursor } : { x: cursor, y: cross };
    cursor += (axis === "v" ? b.h : b.w) + margin;
  }
  return out;
}

app.registerExtension({
  name: "pcg.align",

  async setup() {
    const canvas = app.canvas;
    const el = canvas?.canvas;
    if (!el) {
      console.warn("[pcg.align] cannot get the canvas, auto-arrange disabled");
      return;
    }

    let drag = null;   // { start, nodes, boxes, axis, plan }

    const toGraph = (e) => {
      if (canvas.convertEventToCanvasOffset)
        return canvas.convertEventToCanvasOffset(e);
      const r = el.getBoundingClientRect();
      const ds = canvas.ds;
      return [(e.clientX - r.left) / ds.scale - ds.offset[0],
              (e.clientY - r.top) / ds.scale - ds.offset[1]];
    };

    const selected = () => {
      const sel = canvas.selected_nodes;
      if (!sel) return [];
      return (sel instanceof Map ? [...sel.values()] : Object.values(sel))
        .filter(Boolean);
    };

    const boundsOf = (n) => {
      // getBounding returns [x, y, w, h], including the title bar
      if (n.getBounding) {
        const b = n.getBounding(new Float32Array(4));
        return { x: b[0], y: b[1], w: b[2], h: b[3] };
      }
      const th = (window.LiteGraph?.NODE_TITLE_HEIGHT) ?? 30;
      return { x: n.pos[0], y: n.pos[1] - th,
               w: n.size[0], h: n.size[1] + th };
    };

    el.addEventListener("pointerdown", (e) => {
      if (!e.altKey || e.button !== 0 || e.ctrlKey || e.metaKey) return;
      const nodes = selected();
      if (nodes.length < 2) return;              // nothing to arrange with one node
      drag = {
        start: toGraph(e),
        nodes,
        boxes: nodes.map(boundsOf),
        axis: null,
        plan: null,
      };
      try { el.setPointerCapture(e.pointerId); } catch (_) { /* old browsers */ }
      e.preventDefault();
      e.stopPropagation();                       // don't let litegraph clone the nodes
    }, true);

    el.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const p = toGraph(e);
      const dx = p[0] - drag.start[0], dy = p[1] - drag.start[1];
      const s = canvas.ds?.scale || 1;
      // Threshold in screen pixels, so it feels the same at any zoom
      if (!drag.axis && Math.max(Math.abs(dx), Math.abs(dy)) * s > THRESHOLD) {
        drag.axis = Math.abs(dy) > Math.abs(dx) ? "v" : "h";
        drag.plan = planLayout(drag.boxes, drag.axis);
      }
      e.preventDefault();
      e.stopPropagation();
      canvas.setDirty(true, true);
    }, true);

    const finish = (e) => {
      if (!drag) return;
      const d = drag;
      drag = null;
      if (e) { e.preventDefault(); e.stopPropagation(); }

      if (d.axis && d.plan) {
        app.graph.beforeChange?.();
        d.nodes.forEach((n, i) => {
          // Shift pos by the box displacement, sidestepping pos and the box origin not coinciding
          n.pos[0] += d.plan[i].x - d.boxes[i].x;
          n.pos[1] += d.plan[i].y - d.boxes[i].y;
        });
        app.graph.afterChange?.();
        console.log(`[pcg.align] ${d.nodes.length} nodes arranged `
          + (d.axis === "v" ? "vertically" : "horizontally"));
      }
      canvas.setDirty(true, true);
    };
    el.addEventListener("pointerup", finish, true);
    el.addEventListener("pointercancel", finish, true);
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && drag) { drag = null; canvas.setDirty(true, true); }
    }, true);

    // ------------------------------------------------------------ preview
    const prevDraw = canvas.onDrawForeground;
    canvas.onDrawForeground = function (ctx, area) {
      prevDraw?.call(this, ctx, area);
      if (!drag || !drag.plan) return;
      const s = this.ds?.scale || 1;
      ctx.save();
      ctx.strokeStyle = GUIDE;
      ctx.lineWidth = 1.5 / s;
      ctx.setLineDash([6 / s, 4 / s]);
      for (let i = 0; i < drag.plan.length; i++) {
        const p = drag.plan[i], b = drag.boxes[i];
        ctx.strokeRect(p.x, p.y, b.w, b.h);
      }
      ctx.setLineDash([]);

      // Alignment guide line, shows at a glance which direction it will arrange
      const xs = drag.plan.map((p) => p.x), ys = drag.plan.map((p) => p.y);
      const hs = drag.boxes.map((b) => b.h), ws = drag.boxes.map((b) => b.w);
      ctx.globalAlpha = 0.6;
      ctx.beginPath();
      if (drag.axis === "v") {
        const x = xs[0];
        ctx.moveTo(x, Math.min(...ys) - 20 / s);
        ctx.lineTo(x, Math.max(...ys.map((y, i) => y + hs[i])) + 20 / s);
      } else {
        const y = ys[0];
        ctx.moveTo(Math.min(...xs) - 20 / s, y);
        ctx.lineTo(Math.max(...xs.map((x, i) => x + ws[i])) + 20 / s, y);
      }
      ctx.stroke();
      ctx.restore();
    };

    console.log("[pcg.align] enabled: select several nodes, then Alt + left-drag vertically/horizontally to arrange");
  },
});
