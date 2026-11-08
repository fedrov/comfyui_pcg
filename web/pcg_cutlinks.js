// comfyui_pcg/web/pcg_cutlinks.js
//
// Houdini's hold Y and left-drag a line to cut links. **Applies to the whole graph, not just PCG nodes** --
// it is a canvas-level interaction, independent of any specific node.
//
// Three key points:
//
// 1) Events must be caught in the **capture phase** and stopPropagation'd. litegraph itself starts a box selection
//    or node drag on pointerdown; without intercepting you'd get a box selection while drawing the cut line.
//
// 2) Links on screen are cubic Béziers, not straight lines. litegraph's control points are offset from each end
//    horizontally by dist*0.25; here we sample with the same rule into a polyline and then intersect segments --
//    testing against a straight line between the two endpoints would miss the curved parts.
//
// 3) Disconnect via disconnectInput rather than deleting entries from graph.links directly. The latter leaves
//    slot references on the nodes: the graph looks disconnected but the serialized form is still connected.
//
// Keys: hold Y + left-drag = cut the links crossed; Esc during the drag cancels.

import { app } from "../../scripts/app.js";
import { linkPolyline as wirePolyline } from "./pcg_wires.js";

const CUT_COLOR = "#ff5a4e";

function isTyping(t) {
  return t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable);
}

// Segment intersection (standard cross-product orientation test)
function segHit(p1, p2, p3, p4) {
  const d = (p2[0] - p1[0]) * (p4[1] - p3[1]) - (p2[1] - p1[1]) * (p4[0] - p3[0]);
  if (Math.abs(d) < 1e-9) return false;
  const t = ((p3[0] - p1[0]) * (p4[1] - p3[1]) - (p3[1] - p1[1]) * (p4[0] - p3[0])) / d;
  const u = ((p3[0] - p1[0]) * (p2[1] - p1[1]) - (p3[1] - p1[1]) * (p2[0] - p1[0])) / d;
  return t >= 0 && t <= 1 && u >= 0 && u <= 1;
}

app.registerExtension({
  name: "pcg.cutlinks",

  async setup() {
    const canvas = app.canvas;
    const el = canvas?.canvas;
    if (!el) {
      console.warn("[pcg.cutlinks] cannot get the canvas, link cutting disabled");
      return;
    }

    let keyHeld = false;
    let cut = null;          // { a, b, hits:Set<link_id> }

    // Event coordinates -> graph coordinates. The canvas transform is scale(s) then translate(offset),
    // so the inverse is screen/scale - offset. Prefer the official conversion function when there is one.
    const toGraph = (e) => {
      if (canvas.convertEventToCanvasOffset)
        return canvas.convertEventToCanvasOffset(e);
      const r = el.getBoundingClientRect();
      const ds = canvas.ds;
      return [(e.clientX - r.left) / ds.scale - ds.offset[0],
              (e.clientY - r.top) / ds.scale - ds.offset[1]];
    };

    // Sample a link into a polyline. Since pcg85 this follows the current drawing style (Houdini rounded polyline / frontend Straight /
    // Spline), the same geometry pcg_wires.js draws with -- after changing the link style,
    // testing against Béziers as before would cut invisible lines and miss visible ones
    const linkPolyline = (link) => {
      try {
        const pts = wirePolyline(app.graph, link, canvas);
        if (pts) return pts;
      } catch (_) { /* fall back to the old algorithm */ }
      return bezierPolyline(link);
    };
    // Old algorithm (links with reroutes are not handled by pcg_wires; this is the fallback). Control-point rule copied from litegraph's renderLink
    const bezierPolyline = (link) => {
      const A = app.graph.getNodeById(link.origin_id);
      const B = app.graph.getNodeById(link.target_id);
      if (!A || !B || !A.getConnectionPos || !B.getConnectionPos) return null;
      const a = A.getConnectionPos(false, link.origin_slot);
      const b = B.getConnectionPos(true, link.target_slot);
      if (!a || !b) return null;
      const d = Math.max(30, Math.hypot(b[0] - a[0], b[1] - a[1]) * 0.25);
      const c1 = [a[0] + d, a[1]], c2 = [b[0] - d, b[1]];
      const pts = [];
      const N = 20;
      for (let i = 0; i <= N; i++) {
        const t = i / N, s = 1 - t;
        const w0 = s * s * s, w1 = 3 * s * s * t, w2 = 3 * s * t * t, w3 = t * t * t;
        pts.push([a[0] * w0 + c1[0] * w1 + c2[0] * w2 + b[0] * w3,
                  a[1] * w0 + c1[1] * w1 + c2[1] * w2 + b[1] * w3]);
      }
      return pts;
    };

    const recompute = () => {
      const hits = new Set();
      const links = app.graph.links;
      if (!links) return hits;
      const list = links instanceof Map ? [...links.values()] : Object.values(links);
      for (const link of list) {
        if (!link) continue;
        const pts = linkPolyline(link);
        if (!pts) continue;
        for (let i = 0; i < pts.length - 1; i++) {
          if (segHit(cut.a, cut.b, pts[i], pts[i + 1])) { hits.add(link.id); break; }
        }
      }
      return hits;
    };

    // ------------------------------------------------------------ keyboard
    window.addEventListener("keydown", (e) => {
      if (isTyping(e.target)) return;
      if (e.key === "Escape" && cut) {
        cut = null;
        canvas.setDirty(true, true);
        return;
      }
      if ((e.key === "y" || e.key === "Y") && !e.ctrlKey && !e.metaKey && !e.altKey)
        keyHeld = true;
    }, true);
    window.addEventListener("keyup", (e) => {
      if (e.key === "y" || e.key === "Y") keyHeld = false;
    }, true);
    // keyup isn't received when switching to another window, so it would think the key is still held
    window.addEventListener("blur", () => { keyHeld = false; });

    // ------------------------------------------------------------ pointer
    el.addEventListener("pointerdown", (e) => {
      if (!keyHeld || e.button !== 0) return;
      const p = toGraph(e);
      cut = { a: p, b: [p[0], p[1]], hits: new Set() };
      try { el.setPointerCapture(e.pointerId); } catch (_) { /* old browsers */ }
      e.preventDefault();
      e.stopPropagation();          // don't let litegraph start a box selection
      canvas.setDirty(true, true);
    }, true);

    el.addEventListener("pointermove", (e) => {
      if (!cut) return;
      cut.b = toGraph(e);
      cut.hits = recompute();
      e.preventDefault();
      e.stopPropagation();
      canvas.setDirty(true, true);
    }, true);

    const finish = (e) => {
      if (!cut) return;
      const hits = cut.hits;
      cut = null;
      if (e) { e.preventDefault(); e.stopPropagation(); }

      if (hits.size) {
        // beforeChange/afterChange are ComfyUI's undo grouping hooks; wrapping makes it a single undo
        app.graph.beforeChange?.();
        const links = app.graph.links;
        const get = (id) => (links instanceof Map ? links.get(id) : links[id]);
        for (const id of hits) {
          const link = get(id);
          if (!link) continue;
          const B = app.graph.getNodeById(link.target_id);
          // Must go through disconnectInput: deleting entries from links directly leaves slot references,
          // disconnected on screen but the saved workflow is still connected
          if (B && B.disconnectInput) B.disconnectInput(link.target_slot);
        }
        app.graph.afterChange?.();
        console.log(`[pcg.cutlinks] cut ${hits.size} links`);
      }
      canvas.setDirty(true, true);
    };
    el.addEventListener("pointerup", finish, true);
    el.addEventListener("pointercancel", finish, true);

    // ------------------------------------------------------------ drawing
    // onDrawForeground is in graph coordinates, the same as the coordinates we store, so draw directly
    const prevDraw = canvas.onDrawForeground;
    canvas.onDrawForeground = function (ctx, area) {
      prevDraw?.call(this, ctx, area);
      if (!cut) return;
      const s = this.ds?.scale || 1;
      ctx.save();
      ctx.strokeStyle = CUT_COLOR;
      ctx.lineWidth = 2 / s;
      ctx.setLineDash([8 / s, 6 / s]);
      ctx.beginPath();
      ctx.moveTo(cut.a[0], cut.a[1]);
      ctx.lineTo(cut.b[0], cut.b[1]);
      ctx.stroke();
      ctx.setLineDash([]);

      // Links that are hit are stroked red, so you can confirm which ones will be cut before releasing
      if (cut.hits.size) {
        ctx.lineWidth = 3 / s;
        ctx.strokeStyle = CUT_COLOR;
        ctx.globalAlpha = 0.85;
        const links = app.graph.links;
        const get = (id) => (links instanceof Map ? links.get(id) : links[id]);
        for (const id of cut.hits) {
          const pts = linkPolyline(get(id));
          if (!pts) continue;
          ctx.beginPath();
          ctx.moveTo(pts[0][0], pts[0][1]);
          for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
          ctx.stroke();
        }
        ctx.globalAlpha = 1;
        ctx.fillStyle = CUT_COLOR;
        ctx.font = `${Math.round(13 / s)}px ui-monospace, monospace`;
        ctx.fillText(`✂ ${cut.hits.size}`, cut.b[0] + 10 / s, cut.b[1] - 8 / s);
      }
      ctx.restore();
    };

    console.log("[pcg.cutlinks] enabled: hold Y + left-drag to cut links");
  },
});
