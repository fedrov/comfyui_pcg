// comfyui_pcg/web/pcg_cop_preview.js
//
// A thumbnail inside each COP node -- Substance Designer style.
//
// Why it's worth doing: an image chain is a dozen nodes relaying edits to the same image; "which step went wrong" can only be
// located by seeing every step at once. For a geometry chain one Viewport is enough; for an image chain it isn't.
//
// ★ A few hard constraints, the same kind of lesson as the two in pcg_sections.js:
//
// 1) **Never change the existing order of the node.widgets array**. When litegraph restores a workflow
//    it maps widgets_values back onto the widget array by index -- inserting a widget in the middle shifts
//    every later parameter, with no error -- the values just all end up in the wrong place.
//    So the preview widget is always **pushed to the end**, with serialize=false (takes no
//    slot in widgets_values).
//
// 2) **Don't intercept click dispatch**; only test our own rectangle in onMouseDown. A canvas-level capture
//    listener needs stopImmediatePropagation to block litegraph's own listener; all three
//    approaches were tried, none reliable.
//
// 3) The server sends **raw float32 values**, not PNG. So switching clamp / signed /
//    normalize doesn't recompute the whole chain, and hovering can read the real pixel value.
//
// 4) Row order is COP-native **v up (row 0 is the bottom)**; rows are written in reverse when filling ImageData.
//    On the Python side only bridge.py is allowed to flip v; on the browser side this one flip lives here,
//    and only here.
//
// Metadata comes via ui.pcg_cop in the executed message (see coppreview.py); pixels via the binary at
// /pcg/cop/<node_id>.

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const MAGIC = 0x43474350;            // "PCGC" little-endian
const MODES = ["auto", "clamp", "signed", "normalize"];
const BG = "#1b1e24";
const FRAME = "#3a4049";
const TXT = "#9aa4b1";
const TXT_HI = "#dde3ea";
const PAD = 6;
const BAR_H = 14;
const MIN_H = 64;

const store = new Map();             // node_id -> {header, layers:[Float32Array]}

// ── decoding ────────────────────────────────────────────────────────────
function decode(buf) {
  const dv = new DataView(buf);
  if (dv.getUint32(0, true) !== MAGIC) throw new Error("bad magic");
  const hlen = dv.getUint32(4, true);
  const header = JSON.parse(new TextDecoder().decode(
    new Uint8Array(buf, 8, hlen)));
  let off = 8 + hlen;                // the server already padded the header to 4-byte alignment
  const layers = header.layers.map((L) => {
    const n = L.w * L.h * L.c;
    const a = new Float32Array(buf, off, n);
    off += L.bytes;
    return a;
  });
  return { header, layers };
}

// ── value range mapping ─────────────────────────────────────────────────
function pickMode(L) {
  // auto decides only from the data itself, not the layer name -- layer names are user-chosen and unreliable
  if (L.min >= -0.001 && L.max <= 1.001) return "clamp";
  if (L.min < 0 && L.max > 0) return "signed";
  return "normalize";
}

function mapper(L, mode) {
  const m = mode === "auto" ? pickMode(L) : mode;
  if (m === "clamp") return { f: (v) => v, label: "clamp" };
  if (m === "signed") return { f: (v) => v * 0.5 + 0.5, label: "signed" };
  const lo = L.min, hi = L.max, d = hi - lo;
  if (!(d > 1e-12)) return { f: () => 0.5, label: "normalize" };
  return { f: (v) => (v - lo) / d, label: "normalize" };
}

function toImageData(ctx, L, data, mode) {
  const { w, h, c } = L;
  const img = ctx.createImageData(w, h);
  const px = img.data;
  const { f } = mapper(L, mode);
  for (let y = 0; y < h; y++) {
    // ★ Write rows in reverse: COP row 0 is the bottom, canvas row 0 is the top
    const src = (h - 1 - y) * w * c;
    const dst = y * w * 4;
    for (let x = 0; x < w; x++) {
      const s = src + x * c;
      let r, g, b, a = 255;
      if (c === 1) { r = g = b = f(data[s]); }
      else if (c === 2) { r = f(data[s]); g = f(data[s + 1]); b = 0; }
      else {
        r = f(data[s]); g = f(data[s + 1]); b = f(data[s + 2]);
        if (c >= 4) a = Math.max(0, Math.min(1, data[s + 3])) * 255;
      }
      const d4 = dst + x * 4;
      px[d4] = Math.max(0, Math.min(1, r)) * 255;
      px[d4 + 1] = Math.max(0, Math.min(1, g)) * 255;
      px[d4 + 2] = Math.max(0, Math.min(1, b)) * 255;
      px[d4 + 3] = a;
    }
  }
  return img;
}

function render(state, layerIdx, mode) {
  const L = state.header.layers[layerIdx];
  if (!L) return null;
  const cv = document.createElement("canvas");
  cv.width = L.w; cv.height = L.h;
  const ctx = cv.getContext("2d");
  ctx.putImageData(toImageData(ctx, L, state.layers[layerIdx], mode), 0, 0);
  return cv;
}

// ── widget ─────────────────────────────────────────────────────────────
function addPreview(node) {
  if (node.__pcgCop) return node.__pcgCop;

  const w = {
    // Custom type: litegraph doesn't recognize it so it only calls draw -- exactly what we want
    type: "pcg_cop_preview",
    name: "preview",
    // serialize=false: not in widgets_values, so it doesn't break the index mapping on restore
    serialize: false,
    value: null,
    layer: 0,
    mode: "auto",
    hover: null,
    cache: null,
    cacheKey: "",

    computeSize(width) {
      const h = node.__pcgCopH || Math.round(width - PAD * 2);
      return [width, h + BAR_H + PAD];
    },

    draw(ctx, n, width, y) {
      const st = store.get(String(n.id));
      const boxW = width - PAD * 2;
      const boxH = (n.__pcgCopH || Math.round(boxW));
      this.last = { x: PAD, y, w: boxW, h: boxH };

      ctx.save();
      ctx.fillStyle = BG;
      ctx.fillRect(PAD, y, boxW, boxH);

      if (!st || !st.header.layers.length) {
        ctx.fillStyle = TXT;
        ctx.font = "11px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("Not cooked", PAD + boxW / 2, y + boxH / 2 + 4);
        ctx.textAlign = "left";
      } else {
        const li = Math.min(this.layer, st.header.layers.length - 1);
        const L = st.header.layers[li];
        const key = `${st.rev}|${li}|${this.mode}`;
        if (this.cacheKey !== key) {
          this.cache = render(st, li, this.mode);
          this.cacheKey = key;
        }
        if (this.cache) {
          // contain-style fit, preserving aspect ratio -- a stretched preview would mislead
          const k = Math.min(boxW / L.w, boxH / L.h);
          const dw = L.w * k, dh = L.h * k;
          const dx = PAD + (boxW - dw) / 2, dy = y + (boxH - dh) / 2;
          ctx.imageSmoothingEnabled = k < 1;
          ctx.drawImage(this.cache, dx, dy, dw, dh);
        }
        const lab = mapper(L, this.mode).label;
        ctx.font = "10px monospace";
        ctx.fillStyle = TXT_HI;
        ctx.fillText(`${L.name}(${L.c})`, PAD + 2, y + boxH + 11);
        ctx.fillStyle = TXT;
        const rng = `${fmt(L.min)}…${fmt(L.max)} ${lab}`;
        ctx.textAlign = "right";
        ctx.fillText(rng, PAD + boxW - 2, y + boxH + 11);
        ctx.textAlign = "left";
        if (st.header.layers.length > 1) {
          ctx.fillStyle = TXT;
          ctx.fillText(`${li + 1}/${st.header.layers.length}`,
                       PAD + boxW / 2 - 10, y + boxH + 11);
        }
        if (this.hover) {
          ctx.fillStyle = "rgba(0,0,0,0.7)";
          ctx.fillRect(PAD + 2, y + 2, 150, 14);
          ctx.fillStyle = TXT_HI;
          ctx.fillText(this.hover, PAD + 5, y + 12);
        }
      }
      ctx.strokeStyle = FRAME;
      ctx.lineWidth = 1;
      ctx.strokeRect(PAD + 0.5, y + 0.5, boxW - 1, boxH - 1);
      ctx.restore();
    },

  };

  node.addCustomWidget ? node.addCustomWidget(w) : node.widgets.push(w);
  node.__pcgCop = w;
  return w;
}

// Events go through the **node-level** onMouseDown / onMouseMove, not widget.mouse:
// old litegraph dispatches by widget.type and the new frontend replaced the whole widget system again; a custom
// type doesn't receive anything on some versions. Node-level callbacks are the path that works on both generations.
function hitRect(node) {
  const w = node.__pcgCop;
  return w && w.last ? { w, b: w.last } : null;
}

function inside(b, pos) {
  return pos[0] >= b.x && pos[0] <= b.x + b.w
      && pos[1] >= b.y && pos[1] <= b.y + b.h;
}

function onDown(node, event, pos) {
  const hit = hitRect(node);
  if (!hit || !inside(hit.b, pos)) return false;
  const st = store.get(String(node.id));
  const nl = st ? st.header.layers.length : 0;
  if (event.shiftKey) {
    hit.w.mode = MODES[(MODES.indexOf(hit.w.mode) + 1) % MODES.length];
  } else if (nl > 1) {
    hit.w.layer = (hit.w.layer + 1) % nl;
  } else {
    hit.w.mode = MODES[(MODES.indexOf(hit.w.mode) + 1) % MODES.length];
  }
  hit.w.cacheKey = "";
  node.setDirtyCanvas(true, true);
  return true;                        // swallow this event so the node isn't dragged along
}

function onMove(node, pos) {
  const hit = hitRect(node);
  if (!hit) return;
  const prev = hit.w.hover;
  hit.w.hover = null;
  const st = store.get(String(node.id));
  if (inside(hit.b, pos) && st && st.header.layers.length) {
    const li = Math.min(hit.w.layer, st.header.layers.length - 1);
    const L = st.header.layers[li];
    const b = hit.b;
    const k = Math.min(b.w / L.w, b.h / L.h);
    const dw = L.w * k, dh = L.h * k;
    const u = (pos[0] - (b.x + (b.w - dw) / 2)) / dw;
    const v = (pos[1] - (b.y + (b.h - dh) / 2)) / dh;
    if (u >= 0 && u < 1 && v >= 0 && v < 1) {
      const px = Math.min(L.w - 1, Math.floor(u * L.w));
      // flip v back: down on screen = smaller COP v
      const py = Math.min(L.h - 1, Math.floor((1 - v) * L.h));
      const o = (py * L.w + px) * L.c;
      const d = st.layers[li];
      const vals = [];
      for (let i = 0; i < L.c; i++) vals.push(fmt(d[o + i]));
      hit.w.hover = vals.join(" ");
    }
  }
  if (prev !== hit.w.hover) node.setDirtyCanvas(true, false);
}

function fmt(v) {
  if (!isFinite(v)) return String(v);
  const a = Math.abs(v);
  if (a !== 0 && (a < 1e-3 || a >= 1e4)) return v.toExponential(2);
  return (Math.round(v * 1000) / 1000).toString();
}

// ── fetching data ───────────────────────────────────────────────────────
async function fetchPreview(nodeId, rev) {
  const r = await api.fetchApi(`/pcg/cop/${nodeId}`);
  if (!r.ok) return;
  const buf = await r.arrayBuffer();
  const st = decode(buf);
  st.rev = rev;
  store.set(String(nodeId), st);
  const node = app.graph.getNodeById(Number(nodeId));
  if (node) {
    if (node.__pcgCop) node.__pcgCop.cacheKey = "";
    node.setDirtyCanvas(true, true);
  }
}

// ── registration ────────────────────────────────────────────────────────
app.registerExtension({
  name: "pcg.cop.preview",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    const outs = nodeData.output || [];
    if (!outs.includes("COPIMAGE")) return;

    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onCreated ? onCreated.apply(this, arguments) : undefined;
      addPreview(this);
      // Reserve height for the thumbnail. Only when there is **no** saved size, otherwise it would override the size the user dragged
      if (!this.__pcgSized) {
        this.__pcgSized = true;
        const s = this.computeSize();
        this.size[0] = Math.max(this.size[0], 240);
        this.size[1] = Math.max(this.size[1], s[1]);
      }
      return r;
    };

    const onExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      const r = onExecuted ? onExecuted.apply(this, arguments) : undefined;
      const m = message && message.pcg_cop && message.pcg_cop[0];
      if (m) fetchPreview(m.node_id, m.rev);
      return r;
    };

    const onDownOrig = nodeType.prototype.onMouseDown;
    nodeType.prototype.onMouseDown = function (event, pos, canvas) {
      if (onDown(this, event, pos)) return true;
      return onDownOrig ? onDownOrig.apply(this, arguments) : false;
    };

    const onMoveOrig = nodeType.prototype.onMouseMove;
    nodeType.prototype.onMouseMove = function (event, pos, canvas) {
      onMove(this, pos);
      return onMoveOrig ? onMoveOrig.apply(this, arguments) : undefined;
    };

    // The thumbnail follows the node width (square), but the user may drag it taller
    const onResize = nodeType.prototype.onResize;
    nodeType.prototype.onResize = function (size) {
      if (onResize) onResize.apply(this, arguments);
      this.__pcgCopH = Math.max(MIN_H, Math.round(size[0] - PAD * 2));
    };
  },
});
