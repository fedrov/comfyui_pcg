// comfyui_pcg/web/pcg_dock.js
//
// Docked parameter pane (Settings -> PCG -> Parameters: "Docked pane", the default).
//
// As in Houdini: the network shows nodes as a title and their connectors, and one persistent pane shows the parameters
// of the selected node. The reason is speed as much as habit. A panel on every node is DOM the frontend repositions on
// every frame of a pan or zoom, and builds when a graph loads: the world tiles graph took 13 s to open with every panel
// open and stuttered when dragged. Here the canvas has no parameter DOM at all, and the pane holds one panel at a time.
//
// ★ What does not change:
//
// 1) The native widgets stay on the node, hidden (setShown, the same as the on-node panel). Saving a workflow, undo,
//    copy / paste and what reaches the backend all keep reading them, and workflows open the same in all three modes.
//    The pane's panel is the very Panel class of pcg_panel.js (sections, tabs, hidewhen, references, keyframes, the
//    parameter menu): it reads and writes those widgets.
// 2) Only nodes the panel can take over are adopted (pcg_panel.js eligible), now including the Wrangles: their code
//    box becomes a code editor in the pane. Widgets the panel does not know (the COP thumbnail) stay on the node.
//
// ★ Connected parameters: a hidden widget has no row to put its input dot on, so the dock places them itself, as extra
//    input rows under the node's own inputs, with the parameter's label. While a link is being dragged near a node, its
//    unconnected parameters of a matching type are listed under it as drop targets.

import { app } from "../../scripts/app.js";
import { setShown } from "./pcg_sections.js";
import { Panel, DOCK, MODES, PROP_NATIVE, UI_KEY, eligible, natives, withSpare, injectCss, uiOf, panelMode }
  from "./pcg_panel.js";
import { currentFrame, ownerOf } from "./pcg_params.js";
import { edgeTab } from "./pcg_edge.js";
import { openPresetMenu } from "./pcg_presets.js";
import { isHda, hdaNodeData, hdaSig, openAssetDialog, instancesOf, libraryState, updateFromLibrary }
  from "./pcg_hda.js";

const LS_KEY = "pcg.dock.pane";
const CACHE = 12;                 // panels kept built (switching back to a recent node is instant, keeps its tab)
const MIN_NODE_W = 140;
const MAX_NODE_W = 420;

export const S = {
  pane: null, body: null, title: null, sub: null, pinBtn: null, toggle: null,
  node: null, panel: null, pinned: false, open: true,
  rect: { x: null, y: null, w: 380, h: null },
  cache: new Map(),               // node -> Panel (insertion order = recency)
  timer: null,
};

// ════════════════════════════════════════════════════════════ nodes
// A promoted widget on a subgraph instance mirrors its source (its type is a getter): only hidden is its own
function shown(w, on) {
  try { setShown(w, on); } catch (e) {
    try { w.hidden = !on; } catch (e2) { /* nothing to do: it follows its source */ }
  }
}

const slotH = () => globalThis.LiteGraph?.NODE_SLOT_HEIGHT ?? 20;

/** A parameter's name on the canvas: a component of a vector / colour row is "Translate Y". */
export function paramLabel(nd, n) {
  const u = uiOf(nd, n) || {};
  const row = u.row || (u.in_row ? uiOf(nd, u.in_row)?.row : null);
  if (row && (row.members || []).length > 1) {
    const k = row.members.indexOf(n);
    const comp = (row.kind === "color" ? "RGBA" : "XYZW")[k] || String(k);
    return `${row.label || u.label || n} ${comp}`;
  }
  return u.label || n;
}

/** The node's inputs that belong to a parameter the dock took over: [{i, input, name, label}]. */
export function paramInputs(node) {
  const d = node._pcgDocked;
  if (!d) return [];
  const out = [];
  (node.inputs || []).forEach((input, i) => {
    const n = input?.widget?.name;
    if (n && d.names.has(n)) out.push({ i, input, name: n, label: paramLabel(d.nd, n) });
  });
  return out;
}

function draggedType() {
  const lc = app.canvas?.linkConnector;
  if (!lc?.isConnecting) return null;
  const s = lc.renderLinks?.[0]?.fromSlot;
  return s ? String(s.type ?? "*") : "*";
}

function validFor(type, input) {
  if (type == null) return false;
  const LG = globalThis.LiteGraph;
  return LG?.isValidConnection ? !!LG.isValidConnection(type, input.type) : true;
}

/**
 * Where the parameter inputs go (node coordinates). Connected ones: rows after the node's own inputs. While a link of a
 * matching type is dragged with the mouse over the node (or over its list), the free ones: a list under the node.
 * Everything else: far off, where nothing is drawn or hit.
 */
export function layoutParams(node, mouse = app.canvas?.graph_mouse, type = draggedType()) {
  const H = slotH();
  const own = (node.inputs || []).filter((x) => !x?.widget).length;
  const pis = paramInputs(node);
  const conn = pis.filter((p) => p.input.link != null);
  const pos = new Map();
  conn.forEach((p, k) => pos.set(p.i, [H * 0.5, (own + k + 0.7) * H]));
  const free = type == null ? [] : pis.filter((p) => p.input.link == null && validFor(type, p.input));
  let list = [];
  const top = (node.size?.[1] ?? 0) + 6, w = Math.max(node.size?.[0] ?? 0, 180);
  if (free.length && mouse && node.pos && node.size && !node.flags?.collapsed) {
    const th = globalThis.LiteGraph?.NODE_TITLE_HEIGHT ?? 30;
    const x = mouse[0] - node.pos[0], y = mouse[1] - node.pos[1];
    if (x >= -10 && x <= w + 10 && y >= -th && y <= top + free.length * H + 6) {
      list = free;
      free.forEach((p, k) => pos.set(p.i, [H * 0.5, top + (k + 0.5) * H]));
    }
  }
  for (const p of pis) if (!pos.has(p.i)) pos.set(p.i, [-1e5, -1e5]);
  return { pos, conn, list, own, top, w };
}

// nodes showing a drop list right now (drawn above every node by the canvas hook below)
const LISTS = new Set();

/** The parameter input of a node's drop list under a graph point, or null. */
export function listInputAt(node, x, y) {
  const L = node._pcgDockList;
  if (!L || !node.pos) return null;
  const H = slotH();
  const lx = x - node.pos[0], ly = y - node.pos[1] - L.top;
  if (lx < -10 || lx > L.w + 10 || ly < -3 || ly >= L.items.length * H + 3) return null;
  const k = Math.max(0, Math.min(L.items.length - 1, Math.floor(ly / H)));
  return L.items[k];
}

function applySlots(node) {
  const { pos, list, top, w } = layoutParams(node);
  node._pcgDockList = list.length ? { top, w, items: list } : null;
  if (node._pcgDockList) LISTS.add(node); else LISTS.delete(node);
  for (const [i, p] of pos) {
    if (!node.inputs[i]) continue;
    node.inputs[i].pos = p;
    const c = node._concreteInputs?.[i];
    if (c) {
      c.pos = p;
      try { node._measureSlot?.(c, i, true); } catch (e) { /* hit areas are refreshed next frame anyway */ }
    }
  }
}

/** Compact size: title, the inputs / outputs (plus connected parameters), whatever widgets stay on the node. */
export function fit(node) {
  const H = slotH();
  const own = (node.inputs || []).filter((x) => !x?.widget).length;
  const nout = (node.outputs || []).length;
  const conn = paramInputs(node).filter((p) => p.input.link != null).length;
  const base = Math.max(own, nout, 1), rows = Math.max(own + conn, nout, 1);
  // the widgets left on the node (the COP thumbnail) start under the rows of the connected parameters
  if (rows > base) node.widgets_start_y = (rows + 0.2) * H + 2;
  else delete node.widgets_start_y;
  // (with widgets_start_y set the frontend's computeSize already counts the extra rows)
  const need = node.computeSize?.() || node.size;
  node.setSize?.([Math.max(MIN_NODE_W, need[0], titleWidth(node)), need[1]]);
  node.setDirtyCanvas?.(true, true);
}

// The whole title should show: a node is little more than its title now
let measureCtx = null;
export function titleWidth(node) {
  try {
    measureCtx = measureCtx || document.createElement("canvas").getContext("2d");
    const LG = globalThis.LiteGraph;
    measureCtx.font = node.titleFontStyle || `${LG?.NODE_TEXT_SIZE ?? 14}px Inter, sans-serif`;
    const t = String(node.getTitle?.() ?? node.title ?? "");
    return Math.min(MAX_NODE_W, Math.ceil(measureCtx.measureText(t).width) + 2 * (LG?.NODE_TITLE_HEIGHT ?? 30) + 10);
  } catch (e) {
    return MIN_NODE_W;
  }
}

export function adopt(node, baseData) {
  node._pcgPanelRebuild = () => {
    S.cache.delete(node);
    if (node.properties?.[PROP_NATIVE]) return;
    const shown = S.node === node;
    release(node, { keepSize: true });
    adopt(node, baseData);
    if (shown) show(node, true);
  };
  const nd = withSpare(baseData, node);
  if (node._pcgDocked || !eligible(node, nd, { code: true })) return false;
  return dockWith(node, nd, natives(node));
}

/**
 * A digital asset (a subgraph instance, pcg_hda.js): its promoted parameters in the pane, drawn as the parameters
 * they drive inside; rebuilt when its promotions or its interface change (tick).
 */
export function adoptHda(node) {
  if (node._pcgDocked || node.properties?.[PROP_NATIVE] || !isHda(node)) return false;
  const nd = hdaNodeData(node);
  const names = new Set(Object.keys(nd.input.required));
  const ok = dockWith(node, nd, (node.widgets || []).filter((w) => names.has(w.name)));
  if (ok) { node._pcgDocked.hda = true; node._pcgDocked.sig = hdaSig(node); }
  return ok;
}

export function rebuildHda(node) {
  const shown = S.node === node;
  S.cache.delete(node);
  release(node, { keepSize: true });
  adoptHda(node);
  if (shown) show(node, true);
}

function dockWith(node, nd, ws) {
  node._pcgDocked = { nd, names: new Set(ws.map((w) => w.name)) };
  node._pcgPanelActive = true;               // pcg_sections.js: no section bars on the node
  for (const w of ws) {
    shown(w, false);
    // a DOM widget (the code box) is kept out of the page entirely: that is the whole point
    if (w.element?.style) { w._pcgDisplay = w.element.style.display; w.element.style.display = "none"; }
  }
  if (!Object.prototype.hasOwnProperty.call(node, "arrange") && node.arrange) {
    const arrange = node.arrange;
    node.arrange = function () {
      const r = arrange.apply(this, arguments);
      try { applySlots(this); } catch (e) { /* a failed placement must not stop the canvas */ }
      return r;
    };
    node._pcgDockArrange = true;
  }
  // a link dropped on the list connects to the row under the pointer (the frontend asks the node it lands in, and
  // which of its inputs is there; the list lies under the node's box)
  if (!Object.prototype.hasOwnProperty.call(node, "isPointInside") && node.isPointInside) {
    const inside = node.isPointInside;
    node.isPointInside = function (x, y) {
      return inside.apply(this, arguments) || !!listInputAt(this, x, y);
    };
    node._pcgDockInside = true;
  }
  if (!Object.prototype.hasOwnProperty.call(node, "getInputOnPos") && node.getInputOnPos) {
    const onPos = node.getInputOnPos;
    node.getInputOnPos = function (p) {
      const hit = p ? listInputAt(this, p[0], p[1]) : null;
      return hit ? hit.input : onPos.apply(this, arguments);
    };
    node._pcgDockOnPos = true;
  }
  fit(node);
  if (S.node === node) show(node, true);
  return true;
}

export function release(node, { keepSize = false } = {}) {
  const d = node._pcgDocked;
  if (!d) return;
  S.cache.delete(node);
  node._pcgDocked = null;
  node._pcgPanelActive = false;
  if (node._pcgDockArrange) { delete node.arrange; node._pcgDockArrange = false; }
  if (node._pcgDockInside) { delete node.isPointInside; node._pcgDockInside = false; }
  if (node._pcgDockOnPos) { delete node.getInputOnPos; node._pcgDockOnPos = false; }
  node._pcgDockList = null;
  LISTS.delete(node);
  delete node.widgets_start_y;
  for (const w of natives(node)) {
    shown(w, true);
    if ((w.origType ?? w.type) === "pcg-hidden") w.hidden = true;     // a courier (ch_params) stays out of sight
    if (w.element?.style && "_pcgDisplay" in w) { w.element.style.display = w._pcgDisplay || ""; delete w._pcgDisplay; }
  }
  for (const input of node.inputs || []) if (input?.widget) delete input.pos;
  node._pcgApplySections?.();
  if (!keepSize) {
    const need = node.computeSize?.() || node.size;
    node.setSize?.([Math.max(node.size[0], need[0]), need[1]]);
  }
  node.setDirtyCanvas?.(true, true);
  if (S.node === node) show(node, true);
}

/** Labels of the parameter inputs on the canvas (the frontend draws no label for a widget's input). */
export function draw(node, ctx) {
  if (!ctx || node.flags?.collapsed) return;
  const { pos, conn } = layoutParams(node, null, null);
  if (!conn.length) return;
  ctx.save();
  ctx.font = "12px Inter, sans-serif";
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  ctx.fillStyle = "#b8a8f0";
  for (const p of conn) {
    const [x, y] = pos.get(p.i);
    ctx.fillText(p.label, x + 10, y);
  }
  ctx.restore();
}

/** The drop lists, in graph coordinates, over everything else (the canvas clips a node's own drawing to its box). */
export function drawLists(ctx) {
  if (!LISTS.size) return;
  const H = slotH();
  const hover = app.canvas?.graph_mouse;
  for (const node of [...LISTS]) {
    const L = node._pcgDockList;
    if (!L || !node.graph || !app.canvas?.linkConnector?.isConnecting) { LISTS.delete(node); node._pcgDockList = null; continue; }
    const hit = hover ? listInputAt(node, hover[0], hover[1]) : null;
    const x0 = node.pos[0], y0 = node.pos[1] + L.top;
    ctx.save();
    ctx.fillStyle = "rgba(24,27,32,0.96)";
    ctx.strokeStyle = "#ffcc00";
    ctx.lineWidth = 1;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x0, y0 - 3, L.w, L.items.length * H + 6, 4);
    else ctx.rect(x0, y0 - 3, L.w, L.items.length * H + 6);
    ctx.fill();
    ctx.stroke();
    ctx.font = "12px Inter, sans-serif";
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    L.items.forEach((p, k) => {
      const y = y0 + (k + 0.5) * H;
      if (p === hit) { ctx.fillStyle = "#3c5a86"; ctx.fillRect(x0 + 2, y - H * 0.5, L.w - 4, H); }
      ctx.fillStyle = "#9aa4b2";
      ctx.beginPath();
      ctx.arc(x0 + H * 0.5, y, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = p === hit ? "#ffffff" : "#e8d27a";
      ctx.fillText(p.label, x0 + H * 0.5 + 10, y);
    });
    ctx.restore();
  }
}

function changed(node) {
  fit(node);
  if (S.node === node && S.panel) S.panel.refresh();
}

DOCK.adopt = adopt;
DOCK.release = release;
DOCK.draw = draw;
DOCK.changed = changed;

// ════════════════════════════════════════════════════════════ quick edit on the canvas
// Ctrl+click a node: its panel in a popover next to it, without selecting it (the pane keeps showing what it shows).
// Closed by Esc, a click outside, or ✕.
export const QUICK = { el: null, node: null, panel: null };

export function closeQuick() {
  QUICK.el?.remove();
  QUICK.el = QUICK.node = QUICK.panel = null;
}

export function openQuick(node, x, y) {
  closeQuick();
  if (!node?._pcgDocked) return null;
  injectCss();
  const box = el("div", "pcgdock pcgquick", document.body);
  box.style.cssText = `left:${Math.round(x)}px;top:${Math.round(y)}px;width:360px;max-height:${Math.max(200, innerHeight - y - 16)}px;z-index:1050`;
  const hd = el("div", "hd", box);
  el("span", "ttl", hd).textContent = node.title || node.type;
  el("span", "sub", hd).textContent = "quick edit";
  const close = el("button", "hb", hd);
  close.textContent = "✕";
  close.onclick = (e) => { e.stopPropagation(); closeQuick(); };
  const body = el("div", "bd", box);
  const p = new Panel(node, node._pcgDocked.nd);
  p.onResize = () => {};
  body.appendChild(p.root);
  p.sync();
  p.refresh();
  QUICK.el = box; QUICK.node = node; QUICK.panel = p;
  const r = box.getBoundingClientRect();
  if (r.right > innerWidth - 8) box.style.left = Math.max(8, innerWidth - r.width - 8) + "px";
  return p;
}

function hookQuick() {
  const c = app.canvas, cv = c?.canvas;
  if (!cv) return;
  // on the window, in the capture phase: before the canvas's own handlers (which would select the node)
  let swallow = false;
  window.addEventListener("pointerdown", (e) => {
    if (e.target !== cv) return;
    if (e.button !== 0 || !(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey) return;
    const p = c.convertEventToCanvasOffset?.(e);
    const n = p && c.graph?.getNodeOnPos?.(p[0], p[1], c.visible_nodes);
    if (!n?._pcgDocked) return;
    // not on a connector: those keep their meaning
    if (n.getSlotInPosition?.(p[0], p[1])) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    swallow = true;
    openQuick(n, e.clientX + 12, e.clientY + 12);
  }, true);
  for (const t of ["pointerup", "mouseup", "click", "mousedown"]) {
    window.addEventListener(t, (e) => {
      if (!swallow || e.target !== cv) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      if (t === "click" || t === "pointerup") setTimeout(() => { swallow = false; }, 0);
    }, true);
  }
  window.addEventListener("pointerdown", (e) => {
    if (QUICK.el && !QUICK.el.contains(e.target) && !e.target.closest?.(".litecontextmenu")
        && !(e.ctrlKey || e.metaKey)) closeQuick();
  }, true);
  window.addEventListener("keydown", (e) => { if (e.key === "Escape" && QUICK.el) closeQuick(); }, true);
}

// the last pointer event (a menu entry's callback does not always get one; the presets menu opens there)
const LAST_EV = { e: null };
if (typeof window !== "undefined") window.addEventListener("pointerdown", (e) => { LAST_EV.e = e; }, true);

// ════════════════════════════════════════════════════════════ the pane
function save() {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify({ open: S.open, rect: S.rect }));
  } catch (_) { /* private mode */ }
}
function load() {
  try {
    const o = JSON.parse(localStorage.getItem(LS_KEY) || "null");
    if (!o) return;
    if (typeof o.open === "boolean") S.open = o.open;
    if (o.rect) Object.assign(S.rect, o.rect);
  } catch (_) { /* */ }
}

const CSS = `
.pcgdock{position:fixed;z-index:900;display:flex;flex-direction:column;background:#1b1e23;
  border:1px solid #333a46;border-radius:6px;box-shadow:0 6px 24px #0008;font:12px Inter,"Segoe UI",system-ui,sans-serif}
.pcgdock .hd{display:flex;align-items:center;gap:6px;padding:4px 6px;background:#1e222a;border-bottom:1px solid #333a46;
  border-radius:6px 6px 0 0;cursor:move;flex:0 0 auto;user-select:none}
.pcgdock .ttl{color:#dde3ea;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:0 1 auto}
.pcgdock .sub{color:#7d8794;font:11px ui-monospace,monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  flex:1 1 auto}
.pcgdock .hb{flex:0 0 auto;width:22px;height:20px;border:1px solid #3a4150;border-radius:3px;background:#2a2f3a;
  color:#c8d0dc;cursor:pointer;font:11px ui-monospace,monospace;padding:0}
.pcgdock .hb.lib{background:#2f5a8a;color:#fff;border-color:#4a7ab0}
.pcgdock .hb.on{background:#8a5a1e;color:#fff3e0;border-color:#b07a30}
.pcgdock .bd{flex:1 1 auto;overflow:auto;padding:4px;min-height:60px}
.pcgdock .bd .pcgp-host{overflow:visible}
.pcgdock .empty{color:#7d8794;padding:14px 8px;line-height:1.5}
.pcgdock .grip{position:absolute;left:0;bottom:0;width:14px;height:14px;cursor:nesw-resize}
`;

function el(tag, cls, parent) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  parent?.appendChild(e);
  return e;
}

export function buildPane() {
  if (S.pane) return S.pane;
  injectCss();
  if (!document.getElementById("pcg-dock-css")) {
    const st = el("style");
    st.id = "pcg-dock-css";
    st.textContent = CSS;
    document.head.appendChild(st);
  }
  load();
  if (S.rect.x == null || S.rect.y == null || S.rect.h == null) defaultRect();
  clampRect();
  const p = el("div", "pcgdock", document.body);
  p.dataset.pcgDock = "1";
  const hd = el("div", "hd", p);
  S.title = el("span", "ttl", hd);
  S.sub = el("span", "sub", hd);
  // an asset whose library version differs: update every instance of it (Houdini's instances follow their HDA)
  S.libBtn = el("button", "hb lib", hd);
  S.libBtn.textContent = "⟳";
  S.libBtn.title = "The library has another version of this asset: update every instance of it in this workflow";
  S.libBtn.style.display = "none";
  S.libBtn.onclick = async (e) => {
    e.stopPropagation();
    const sg = S.node?.subgraph;
    if (!sg) return;
    await updateFromLibrary(sg);
    S.libBtn.style.display = "none";
  };
  // presets of this node type (Houdini's gear menu)
  S.preBtn = el("button", "hb", hd);
  S.preBtn.textContent = "☰";
  S.preBtn.title = "Presets: save the parameters, load or delete saved ones, revert to defaults";
  S.preBtn.onclick = (e) => {
    e.stopPropagation();
    if (S.node) openPresetMenu(S.node, e, () => { S.panel?.sync(); S.panel?.refresh(); });
  };
  S.pinBtn = el("button", "hb", hd);
  S.pinBtn.textContent = "📌";
  S.pinBtn.title = "Pin: keep showing this node when another one is selected";
  S.pinBtn.onclick = (e) => { e.stopPropagation(); S.pinned = !S.pinned; paint(); };
  const close = el("button", "hb", hd);
  close.textContent = "✕";
  close.title = "Hide the parameter pane (the Parameters tab on the right edge brings it back)";
  close.onclick = (e) => { e.stopPropagation(); setOpen(false); };
  S.body = el("div", "bd", p);
  const grip = el("div", "grip", p);
  S.pane = p;
  place();
  dragify(p, hd, grip);
  // when the pane is hidden: a tab on the window's right edge brings it back
  const tg = edgeTab("Parameters", "Show the parameter pane", () => setOpen(true), 0);
  tg.classList.add("pcgdock-tg");
  S.toggle = tg;
  setOpen(S.open);
  show(null, true);
  return p;
}

/**
 * First opening: the right edge under the 3D panel (420 x 340 at top 96), ending above the frontend's minimap and
 * canvas buttons; on a screen too short for that, to the left of the 3D panel at full height.
 */
export function defaultRect() {
  const r = S.rect, W = window.innerWidth, H = window.innerHeight;
  let bottom = H - 62;
  for (const sel of [".minimap-main-container", ".p-buttongroup.absolute"]) {
    const m = document.querySelector(sel);
    const b = m && m.offsetParent !== null ? m.getBoundingClientRect() : null;
    if (b && b.width && b.left < W - 24 && b.right > W - 24 - r.w) bottom = Math.min(bottom, b.top - 8);
  }
  const top = 448;
  if (bottom - top >= 300) { r.x = W - r.w - 24; r.y = top; r.h = bottom - top; }
  else { r.x = W - 24 - 420 - 10 - r.w; r.y = 96; r.h = H - 96 - 70; }
}

function clampRect() {
  const r = S.rect;
  r.w = Math.max(260, Math.min(r.w, window.innerWidth - 8));
  r.h = Math.max(160, Math.min(r.h, window.innerHeight - 8));
  r.x = Math.max(0, Math.min(r.x, window.innerWidth - 60));
  r.y = Math.max(0, Math.min(r.y, window.innerHeight - 30));
}

function place() {
  const r = S.rect, p = S.pane;
  p.style.left = r.x + "px"; p.style.top = r.y + "px";
  p.style.width = r.w + "px"; p.style.height = r.h + "px";
}

function dragify(pane, head, grip) {
  let mode = null, x0 = 0, y0 = 0, r0 = null;
  const down = (kind) => (ev) => {
    if (ev.button !== 0 || ev.target.closest?.("button")) return;
    mode = kind; x0 = ev.clientX; y0 = ev.clientY; r0 = { ...S.rect };
    ev.target.setPointerCapture?.(ev.pointerId);
    ev.preventDefault();
    ev.stopPropagation();
  };
  head.addEventListener("pointerdown", down("move"));
  grip.addEventListener("pointerdown", down("size"));
  window.addEventListener("pointermove", (ev) => {
    if (!mode) return;
    const dx = ev.clientX - x0, dy = ev.clientY - y0;
    if (mode === "move") { S.rect.x = r0.x + dx; S.rect.y = r0.y + dy; }
    else { S.rect.x = r0.x + dx; S.rect.w = r0.w - dx; S.rect.h = r0.h + dy; }   // grip at the bottom left
    clampRect();
    place();
  });
  const up = () => { if (mode) { mode = null; save(); } };
  window.addEventListener("pointerup", up);
  window.addEventListener("pointercancel", up);
}

function paint() {
  S.pinBtn?.classList.toggle("on", S.pinned);
  if (S.toggle) S.toggle.style.display = S.open ? "none" : "";
}

export function setOpen(on) {
  S.open = !!on;
  if (S.pane) S.pane.style.display = S.open ? "flex" : "none";
  paint();
  save();
}

function panelFor(node) {
  let p = S.cache.get(node);
  if (p) { S.cache.delete(node); S.cache.set(node, p); return p; }
  p = new Panel(node, node._pcgDocked.nd);
  p.onResize = () => {};                     // the pane scrolls: no node height to follow
  S.cache.set(node, p);
  while (S.cache.size > CACHE) S.cache.delete(S.cache.keys().next().value);
  return p;
}

function message(text) {
  const m = el("div", "empty");
  m.textContent = text;
  return m;
}

// the grey text after the title: the node type, or the asset's definition name for a subgraph instance
function subText(node) {
  if (!node) return "";
  const kind = node.subgraph ? `asset · ${node.subgraph.name || "subgraph"}` : node.title !== node.type ? node.type : "";
  const p = netPath(node);
  return p ? `${p}${kind ? " · " + kind : ""}` : kind;
}

/** Where a node inside assets sits, as Houdini writes it ("/rock/box1"): what ch("../..") paths walk. "" at the root. */
export function netPath(node) {
  const parts = [];
  let g = node?.graph;
  for (let i = 0; i < 8 && g; i++) {
    const o = ownerOf(g);
    if (!o) break;
    parts.unshift(o.title || o.type);
    g = o.graph;
  }
  return parts.length ? "/" + [...parts, node.title || node.type].join("/") : "";
}

let libAt = 0;
function checkLibrary(now = false) {
  const sg = S.node?.subgraph;
  if (!S.libBtn) return;
  if (!sg) { S.libBtn.style.display = "none"; return; }
  if (!now && Date.now() - libAt < 5000) return;
  libAt = Date.now();
  const node = S.node;
  libraryState(sg).then((st) => {
    if (S.node === node) S.libBtn.style.display = st === "differs" ? "" : "none";
  }).catch(() => {});
}

/** Show this node's parameters (null: nothing selected yet). */
export function show(node, force = false) {
  if (!S.pane) return;
  if (node === S.node && !force) return;
  S.node = node;
  S.panel = null;
  S.title.textContent = node ? (node.title || node.type) : "Parameters";
  checkLibrary(true);
  S.sub.textContent = subText(node);
  if (!node) {
    S.body.replaceChildren(message("Select a node to see its parameters here."));
    return;
  }
  if (node._pcgDocked) {
    const p = panelFor(node);
    S.panel = p;
    S.body.replaceChildren(p.root);
    p.sync();
    p.refresh();
    p._frame = currentFrame(p.graph());
    return;
  }
  const pcg = !!node.constructor?.nodeData && Object.values(node.constructor.nodeData.input || {}).some(
    (g) => Object.values(g || {}).some((s) => Array.isArray(s) && s[1]?.[UI_KEY]));
  S.body.replaceChildren(message(node.properties?.[PROP_NATIVE]
    ? "This node uses native widgets (node menu → \"Parameters: docked pane\" to bring them here)."
    : pcg || node.widgets?.length ? "This node's parameters are on the node." : "This node has no parameters."));
}

// The node to show: the last selected node (the frontend keeps the selection in order of selecting)
export function selected() {
  const c = app.canvas;
  if (!c) return null;
  let last = null;
  if (c.selectedItems?.size) {
    for (const x of c.selectedItems) if (x && x.type && x.size && x.graph !== undefined) last = x;
    return last;
  }
  const sn = c.selected_nodes ? Object.values(c.selected_nodes) : [];
  return sn.length ? (sn.includes(c.current_node) ? c.current_node : sn[sn.length - 1]) : null;
}

/** One tick: follow the selection, re-read values changed elsewhere (references, undo, loading, the timeline). */
export function tick() {
  if (!S.pane) return;
  for (const n of app.canvas?.graph?._nodes || []) {
    if (!n.subgraph) continue;
    if (!n._pcgDocked) adoptHda(n);
    else if (n._pcgDocked.hda && n._pcgDocked.sig !== hdaSig(n)) rebuildHda(n);
  }
  for (const n of S.cache.keys()) if (!n.graph) S.cache.delete(n);
  let n = S.node;
  // the graph was reloaded (undo, opening a workflow): the same node under its id, if it is still there
  if (n && !n.graph) {
    const again = app.graph?.getNodeById?.(n.id);
    show(again && again.type === n.type ? again : null, true);
    n = S.node;
  }
  if (!S.pinned) {
    const sel = selected();
    if (sel && sel !== n) show(sel);
  }
  if (S.node) {
    const t = S.node.title || S.node.type;
    if (S.title.textContent !== t) {
      S.title.textContent = t;
      if (S.node._pcgDocked) fit(S.node);           // renamed: the whole title should still show
      S.sub.textContent = subText(S.node);
    }
  }
  checkLibrary();
  if (QUICK.panel) {
    if (!QUICK.node?.graph) closeQuick();
    else {
      const q = QUICK.panel, before = q.controls.map((c) => c.last);
      q.sync();
      if (q.controls.some((c, i) => c.last !== before[i])) q.refresh();
    }
  }
  const p = S.panel;
  if (p && S.open) {
    const before = p.controls.map((c) => c.last);
    p.sync();
    if (p.controls.some((c, i) => c.last !== before[i])) p.refresh();
    else {
      const f = currentFrame(p.graph());
      if (p._frame !== f) { p._frame = f; p.markRefs(); }
    }
  }
}

app.registerExtension({
  name: "pcg.dock",
  // a subgraph instance: Houdini's Type Properties for the asset's parameter interface
  getNodeMenuItems(node) {
    const pre = (node?.widgets || []).length ? [null, {
      content: "PCG: Presets…",
      callback: (v, o, ev) => openPresetMenu(node, ev || LAST_EV.e, () => { if (S.node === node) { S.panel?.sync(); S.panel?.refresh(); } }),
    }] : [];
    if (!node?.subgraph) return pre;
    return [...pre, null, {
      content: "PCG: Edit Asset Interface…",
      callback: () => openAssetDialog(node, (sg) => {
        for (const n of instancesOf(sg)) if (n._pcgDocked?.hda) rebuildHda(n);
      }),
    }, {
      content: "PCG: Update Asset from Library",
      callback: async () => {
        const n = await updateFromLibrary(node.subgraph);
        const msg = n ? `Updated ${n} instance(s) of "${node.subgraph?.name}" from the library.`
          : `"${node.subgraph?.name}" is not in the library (Publish Subgraph saves it there).`;
        try { app.extensionManager?.toast?.add?.({ severity: n ? "success" : "warn", summary: msg, life: 4000 }); }
        catch (e) { console.info("[pcg.dock]", msg); }
      },
    }];
  },
  async setup() {
    if (typeof document === "undefined") return;
    if (panelMode() !== MODES[0]) return;
    buildPane();
    const c = app.canvas;
    if (c) {
      const fg = c.onDrawForeground;
      c.onDrawForeground = function (ctx) {
        const r = fg?.apply(this, arguments);
        try { drawLists(ctx); } catch (e) { /* drawing the lists must not stop the canvas */ }
        return r;
      };
    }
    hookQuick();
    S.timer = setInterval(() => { try { tick(); } catch (e) { console.error("[pcg.dock]", e); } }, 120);
  },
});
