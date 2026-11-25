// comfyui_pcg/web/pcg_cook.js
//
// Cook feedback, as in Houdini's network view:
//
//   · on every node that ran: its cook time above the title bar; a red badge when it failed, a yellow one when it
//     warned; an amber dot (and a dimmed time) when it is out of date -- a parameter, a wire, the bypass state of it
//     or of something upstream changed since it last cooked
//   · middle button on a node (press without moving): its info -- time, counts, bounding box, memory, attributes by
//     class with size and type, groups, COP layers, warnings, the error. It stays until the next click or Esc
//   · the Performance pane (tab on the window's right edge): the last run, node by node, slowest first, with a bar
//     per node; click a row to frame the node
//
// The numbers come from the server (cookstats.py: "pcg.cook" messages, per execution id -- "12:5" inside a
// subgraph); ComfyUI's own executing / execution_cached / execution_error events fill in the other nodes (their time
// is the gap until the next node started).

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { floatingPane } from "./pcg_edge.js";

export const SETTING_TIME = "PCG.Cook.ShowTime";
export const COOK = new Map();        // execution id -> record
export const RUN = { id: null, start: 0, end: 0, order: [], cur: null, curAt: 0, running: false };

const now = () => (globalThis.performance?.now?.() ?? Date.now());

// ════════════════════════════════════════════════════════ ids and signatures
/** The graph a node object belongs to -> its execution id prefix ("" at the root, "12:" inside instance 12). */
function prefixOf(graph) {
  const root = app.graph;
  if (!graph || graph === root) return "";
  const hit = [];
  const walk = (g, pre, depth) => {
    if (depth > 8) return;
    for (const n of g?._nodes || []) {
      if (!n.subgraph) continue;
      if (n.subgraph === graph) hit.push(pre + n.id + ":");
      else walk(n.subgraph, pre + n.id + ":", depth + 1);
    }
  };
  walk(root, "", 0);
  return hit[0] ?? null;
}

export function execId(node) {
  const p = prefixOf(node?.graph);
  return p == null ? null : p + node.id;
}

/** The node object for an execution id, in the graph shown now or anywhere below the root. */
export function nodeOf(id) {
  const parts = String(id).split(":");
  let g = app.graph, n = null;
  for (let i = 0; i < parts.length; i++) {
    n = g?.getNodeById?.(parts[i]) ?? (g?._nodes || []).find((x) => String(x.id) === parts[i]);
    if (!n) return null;
    if (i < parts.length - 1) g = n.subgraph;
  }
  return n;
}

/** What a node's result depends on in the graph: its values, wires and bypass state. */
export function ownSig(node) {
  const w = (node.widgets || []).filter((x) => x.serialize !== false && x.type !== "button")
    .map((x) => x.value);
  const ins = (node.inputs || []).map((i) => {
    if (i.link == null) return null;
    const l = node.graph?.links?.get?.(i.link) ?? node.graph?.links?.[i.link];
    return l ? [l.origin_id, l.origin_slot] : i.link;
  });
  try { return JSON.stringify([w, ins, node.mode ?? 0]); } catch (e) { return String(Math.random()); }
}

function stamp(id, rec) {
  const n = nodeOf(id);
  if (n) rec.sig = ownSig(n);
  rec.at = Date.now();
  COOK.set(String(id), rec);
}

// ════════════════════════════════════════════════════════ events
function runRow(id) {
  let r = RUN.order.find((x) => x.id === id);
  if (!r) { r = { id, time: null, wall: null, state: "ran" }; RUN.order.push(r); }
  return r;
}

function closeCurrent(t) {
  if (RUN.cur == null) return;
  const r = runRow(RUN.cur);
  if (r.wall == null) r.wall = (t - RUN.curAt) / 1000;
  RUN.cur = null;
}

export function onCook(d) {
  if (!d || d.node == null) return;
  const id = String(d.node);
  const old = COOK.get(id) || {};
  const rec = { ...old, ok: !!d.ok, time: d.time, outputs: d.outputs || (d.ok ? [] : old.outputs || []),
                warnings: d.warnings || [], notes: d.notes || [], error: d.ok ? null : d.error, cached: false,
                pcg: true };
  stamp(id, rec);
  const r = runRow(id);
  r.time = d.time;
  r.state = d.ok ? (rec.warnings.length ? "warn" : "ran") : "error";
  dirtySoon();
  paneSoon();
}

export function onStart(d) {
  RUN.id = d?.prompt_id ?? null;
  RUN.start = now(); RUN.end = 0; RUN.order = []; RUN.cur = null; RUN.running = true;
  paneSoon();
}

export function onExecuting(d) {
  const id = d == null ? null : (typeof d === "object" ? (d.display_node ?? d.node) : d);
  const t = now();
  closeCurrent(t);
  if (id == null) { RUN.running = false; RUN.end = t; paneSoon(); return; }
  RUN.cur = String(id);
  RUN.curAt = t;
  runRow(RUN.cur);
  // a node without a pcg.cook (not a PCG node) still gets its record: the wall time, filled when the next one starts
  if (!COOK.get(RUN.cur)?.pcg) stamp(RUN.cur, { ok: true, time: null, outputs: [], warnings: [], error: null });
  paneSoon();
}

export function onCached(d) {
  const ask = [];
  for (const id of d?.nodes || []) {
    const k = String(id);
    const rec = COOK.get(k) || { ok: true, time: null, outputs: [], warnings: [], error: null };
    if (!rec.pcg) ask.push(k);
    stamp(k, { ...rec, cached: true });
    const r = runRow(k);
    r.state = "cached";
    if (rec.pcg) r.time = rec.time;
  }
  // nodes not cooked in this page: what they reported when they last ran (the server keeps it)
  if (ask.length && api.fetchApi) {
    api.fetchApi(`/pcg/cookstats?ids=${encodeURIComponent(ask.join(","))}`).then((r) => r.json()).then((got) => {
      for (const [k, v] of Object.entries(got || {})) {
        const rec = COOK.get(k) || {};
        stamp(k, { ...rec, ok: !!v.ok, time: v.time, outputs: v.outputs || [], warnings: v.warnings || [],
                   notes: v.notes || [],
                   error: v.ok ? null : v.error, pcg: true, cached: true });
        const r = RUN.order.find((x) => x.id === k);
        if (r) r.time = v.time;
      }
      dirtySoon();
      paneSoon();
    }).catch(() => {});
  }
  dirtySoon();
  paneSoon();
}

export function onError(d) {
  const id = d?.node_id != null ? String(d.node_id) : null;
  if (id == null) return;
  const rec = COOK.get(id) || { outputs: [], warnings: [] };
  stamp(id, { ...rec, ok: false, error: d.exception_message ? `${d.exception_type || "Error"}: ${d.exception_message}`
    : (rec.error || "failed"), cached: false });
  runRow(id).state = "error";
  closeCurrent(now());
  RUN.running = false; RUN.end = now();
  paneSoon();
}

function onSuccess() { closeCurrent(now()); RUN.running = false; RUN.end = now(); paneSoon(); }

// ════════════════════════════════════════════════════════ out of date
export const DIRTY = new Set();      // node objects out of date
let dirtyT = null;
function dirtySoon() { if (!dirtyT) dirtyT = setTimeout(() => { dirtyT = null; computeDirty(); }, 50); }

/** Out of date: its own signature changed since it cooked, or anything it reads from is out of date. */
export function computeDirty(graph = app.canvas?.graph || app.graph) {
  DIRTY.clear();
  const nodes = graph?._nodes || [];
  const memo = new Map();
  const visit = (n, depth) => {
    if (memo.has(n)) return memo.get(n);
    memo.set(n, false);
    const id = execId(n);
    const rec = id != null ? COOK.get(id) : null;
    let d = !!(rec && rec.sig !== undefined && rec.sig !== ownSig(n));
    if (depth < 400) {
      for (const i of n.inputs || []) {
        if (i.link == null) continue;
        const l = graph.links?.get?.(i.link) ?? graph.links?.[i.link];
        const up = l ? graph.getNodeById?.(l.origin_id) : null;
        if (up && visit(up, depth + 1)) d = true;
      }
    }
    memo.set(n, d);
    if (d && rec) DIRTY.add(n);
    return d;
  };
  for (const n of nodes) visit(n, 0);
  return DIRTY;
}

// ════════════════════════════════════════════════════════ drawing on the canvas
export function fmtTime(s) {
  if (s == null || !Number.isFinite(s)) return "";
  if (s < 0.001) return "<1 ms";
  if (s < 1) return `${Math.round(s * 1000)} ms`;
  if (s < 60) return `${s.toFixed(s < 10 ? 2 : 1)} s`;
  return `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")} min`;
}

function showTime() {
  try {
    const v = app.extensionManager?.setting?.get?.(SETTING_TIME) ?? app.ui?.settings?.getSettingValue?.(SETTING_TIME);
    return v !== false;
  } catch (e) { return true; }
}

export function drawBadges(ctx, canvas) {
  if (!COOK.size) return;
  const TH = globalThis.LiteGraph?.NODE_TITLE_HEIGHT ?? 30;
  const scale = canvas?.ds?.scale ?? 1;
  const text = showTime() && scale > 0.35;
  ctx.save();
  ctx.textBaseline = "alphabetic";
  ctx.font = "11px Inter, sans-serif";
  // right of the title bar, outside the node (the frontend draws its own badges above the title)
  for (const n of canvas?.visible_nodes || []) {
    const id = execId(n);
    const rec = id != null ? COOK.get(id) : null;
    if (!rec) continue;
    const x1 = n.pos[0] + (n.flags?.collapsed ? (n._collapsed_width || 120) : n.size[0]);
    const yc = n.pos[1] - TH / 2;
    const stale = DIRTY.has(n);
    let x = x1 + 8;
    if (stale) {
      ctx.fillStyle = "#e0975f";
      ctx.beginPath();
      ctx.arc(x + 3, yc, 3.5, 0, Math.PI * 2);
      ctx.fill();
      x += 11;
    }
    if (!rec.ok || rec.warnings?.length) {
      const err = !rec.ok;
      ctx.fillStyle = err ? "#e5484d" : "#e8b730";
      ctx.beginPath();
      if (err) ctx.arc(x + 7, yc, 7, 0, Math.PI * 2);
      else { ctx.moveTo(x + 7, yc - 7); ctx.lineTo(x + 14, yc + 6); ctx.lineTo(x, yc + 6); ctx.closePath(); }
      ctx.fill();
      ctx.fillStyle = err ? "#fff" : "#1b1e23";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.font = "bold 10px Inter, sans-serif";
      ctx.fillText("!", x + 7, yc + (err ? 0.5 : 2));
      ctx.font = "11px Inter, sans-serif";
      x += 18;
    }
    const t = rec.time ?? rec.wall;
    if (text && (t != null || rec.cached)) {
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillStyle = stale ? "#7d8794" : rec.cached ? "#6f9a7b" : "#9aa4b2";
      ctx.fillText(rec.cached && t == null ? "cached" : fmtTime(t) + (rec.cached ? " (cached)" : ""), x, yc);
    }
  }
  ctx.restore();
}

// wall time of nodes without a pcg.cook: copied into their records once known
function fillWall() {
  for (const r of RUN.order) {
    if (r.wall == null) continue;
    const rec = COOK.get(r.id);
    if (rec && !rec.pcg && rec.wall !== r.wall) rec.wall = r.wall;
  }
}

// ════════════════════════════════════════════════════════ the info popup (middle button)
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const big = (n) => Number(n).toLocaleString("en-US");
function bytes(b) {
  if (!Number.isFinite(b)) return "";
  if (b < 1024) return `${b} B`;
  if (b < 1 << 20) return `${(b / 1024).toFixed(1)} KB`;
  if (b < 1 << 30) return `${(b / (1 << 20)).toFixed(1)} MB`;
  return `${(b / (1 << 30)).toFixed(2)} GB`;
}

/** The info of a node as HTML (also used by the tests). */
export function infoHtml(node) {
  const id = execId(node);
  const rec = id != null ? COOK.get(id) : null;
  const h = [`<div class="hd"><b>${esc(node.title || node.type)}</b> <span class="ty">${esc(node.type)}</span></div>`];
  if (!rec) h.push(`<div class="st">Not cooked yet in this session.</div>`);
  else {
    const t = rec.time ?? rec.wall;
    const st = !rec.ok ? `<span class="er">Failed</span>` : rec.cached ? "Cached (not recomputed)"
      : `Cooked in <b>${esc(fmtTime(t))}</b>`;
    h.push(`<div class="st">${st}${DIRTY.has(node) ? ' · <span class="dt">out of date</span>' : ""}</div>`);
    if (rec.error) h.push(`<div class="er pre">${esc(rec.error)}</div>`);
    for (const w of rec.warnings || []) h.push(`<div class="wn">⚠ ${esc(w)}</div>`);
    for (const n of rec.notes || []) h.push(`<div class="nt">${esc(n)}</div>`);
    if (!rec.ok && (rec.outputs || []).length) h.push(`<div class="st">Its last good result:</div>`);
    for (const o of rec.outputs || []) {
      if (o.kind === "geometry") {
        h.push(`<table class="cnt"><tr><td>Points</td><td>${big(o.npoints)}</td></tr>` +
               `<tr><td>Primitives</td><td>${big(o.nprims)}</td></tr>` +
               `<tr><td>Vertices</td><td>${big(o.nvertices)}</td></tr>` +
               `<tr><td>Memory</td><td>${bytes(o.bytes)}</td></tr></table>`);
        if (o.bbox) {
          const [mn, mx] = o.bbox, f = (v) => Number(v).toFixed(3);
          h.push(`<div class="bb">Bounds  ${mn.map(f).join(" ")} → ${mx.map(f).join(" ")}<br>` +
                 `Size  ${mn.map((v, k) => f(mx[k] - v)).join(" ")}</div>`);
        }
        for (const cls of ["point", "vertex", "prim", "detail"]) {
          const a = o.attribs?.[cls] || {};
          const ks = Object.keys(a);
          if (!ks.length) continue;
          h.push(`<div class="ac"><span class="cl">${cls}</span> ` + ks.map((k) =>
            `<span class="at" title="${esc(a[k].type)}[${a[k].size}]">${esc(k)}<i>${a[k].type[0]}${a[k].size > 1 ? a[k].size : ""}</i></span>`)
            .join(" ") + "</div>");
        }
        for (const cls of ["point", "prim"]) {
          const g = o.groups?.[cls] || [];
          if (g.length) h.push(`<div class="ac"><span class="cl">${cls} groups</span> ${g.map(esc).join(", ")}</div>`);
        }
      } else if (o.kind === "cop") {
        h.push(`<div class="cnt1">${o.xres} × ${o.yres}</div>`);
        h.push(`<div class="ac"><span class="cl">layers</span> ` + Object.entries(o.layers || {}).map(([k, c]) =>
          `<span class="at">${esc(k)}<i>${c}</i></span>`).join(" ") + "</div>");
      }
    }
  }
  return h.join("");
}

const POP_CSS = `
.pcg-info{position:fixed;z-index:1100;max-width:420px;min-width:220px;background:#1b1e23f2;border:1px solid #3a4150;
  border-radius:6px;padding:8px 10px;color:#cfd5dc;font:12px/1.45 Inter,"Segoe UI",system-ui,sans-serif;
  box-shadow:0 6px 24px #000a;pointer-events:none}
.pcg-info .hd{margin-bottom:3px}.pcg-info .ty{color:#7d8794;font:11px ui-monospace,monospace}
.pcg-info .st{color:#aeb6bf;margin-bottom:4px}.pcg-info .er{color:#ff8f8f}.pcg-info .wn{color:#e8c86a}.pcg-info .nt{color:#9fc3e0}
.pcg-info .dt{color:#e0975f}.pcg-info .pre{white-space:pre-wrap;font:11px ui-monospace,monospace;margin:3px 0}
.pcg-info table.cnt{border-collapse:collapse;margin:2px 0 4px}.pcg-info table.cnt td{padding:0 10px 0 0}
.pcg-info table.cnt td:last-child{text-align:right;color:#e6eaee;font-variant-numeric:tabular-nums}
.pcg-info .bb{color:#9aa4b2;font:11px ui-monospace,monospace;margin-bottom:4px}
.pcg-info .ac{margin:3px 0}.pcg-info .cl{color:#7d8794;margin-right:2px}
.pcg-info .at{display:inline-block;background:#262a31;border:1px solid #343a43;border-radius:3px;padding:0 4px;margin:1px 0;
  color:#dfe4e9}.pcg-info .at i{font-style:normal;color:#7ab8ea;margin-left:3px;font-size:10px}
.pcg-perf .row{display:flex;align-items:center;gap:6px;padding:2px 4px;border-radius:3px;cursor:pointer}
.pcg-perf .row:hover{background:#262a31}.pcg-perf .nm{flex:0 0 46%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pcg-perf .bar{flex:1 1 auto;height:8px;background:#16181b;border-radius:2px;position:relative}
.pcg-perf .bar i{position:absolute;left:0;top:0;bottom:0;background:#4b87c2;border-radius:2px}
.pcg-perf .row.error .bar i{background:#e5484d}.pcg-perf .row.warn .bar i{background:#e8b730}
.pcg-perf .tm{flex:0 0 64px;text-align:right;font-variant-numeric:tabular-nums;color:#e6eaee}
.pcg-perf .sum{color:#9aa4b2;padding:4px;border-bottom:1px solid #2b313b;margin-bottom:4px}
.pcg-perf .tools{display:flex;gap:8px;align-items:center;padding:0 4px 4px}
.pcg-perf .tools label{display:flex;gap:4px;align-items:center;color:#aeb6bf}
`;
function css() {
  if (document.getElementById("pcg-cook-css")) return;
  const st = document.createElement("style");
  st.id = "pcg-cook-css";
  st.textContent = POP_CSS;
  document.head.appendChild(st);
}

export const POP = { el: null, node: null };
export function showInfo(node, x, y) {
  css();
  if (!POP.el) {
    POP.el = document.createElement("div");
    POP.el.className = "pcg-info";
    document.body.appendChild(POP.el);
  }
  POP.node = node;
  POP.el.innerHTML = infoHtml(node);
  POP.el.style.display = "block";
  const r = POP.el.getBoundingClientRect();
  POP.el.style.left = Math.max(4, Math.min(x + 14, innerWidth - r.width - 8)) + "px";
  POP.el.style.top = Math.max(4, Math.min(y + 14, innerHeight - r.height - 8)) + "px";
}
export function hideInfo() {
  if (POP.el) POP.el.style.display = "none";
  POP.node = null;
}

function nodeAtEvent(e) {
  const c = app.canvas;
  if (!c) return null;
  let p;
  if (c.convertEventToCanvasOffset) p = c.convertEventToCanvasOffset(e);
  else return null;
  return c.graph?.getNodeOnPos?.(p[0], p[1], c.visible_nodes) ?? null;
}

function hookMiddle() {
  let press = null;
  addEventListener("pointerdown", (e) => {
    if (POP.node && e.button !== 1) hideInfo();
    if (e.button !== 1 || !(e.target instanceof HTMLCanvasElement) || e.target !== app.canvas?.canvas) return;
    const n = nodeAtEvent(e);
    if (POP.node) hideInfo();
    if (!n) return;
    press = { n, x: e.clientX, y: e.clientY, t: setTimeout(() => { if (press) showInfo(press.n, press.x, press.y); }, 160) };
  }, true);
  addEventListener("pointermove", (e) => {
    if (press && Math.hypot(e.clientX - press.x, e.clientY - press.y) > 4) {   // a pan: no info
      clearTimeout(press.t);
      if (POP.node === press.n) hideInfo();
      press = null;
    }
  }, true);
  addEventListener("pointerup", (e) => {
    if (e.button !== 1 || !press) return;
    clearTimeout(press.t);
    showInfo(press.n, press.x, press.y);          // pressed and released in place: the info stays
    press = null;
  }, true);
  addEventListener("keydown", (e) => { if (e.key === "Escape") hideInfo(); }, true);
  addEventListener("wheel", () => hideInfo(), { capture: true, passive: true });
}

// ════════════════════════════════════════════════════════ the performance pane
export const PERF = { pane: null, all: false };
let paneT = null;
function paneSoon() { if (PERF.pane && !paneT) paneT = setTimeout(() => { paneT = null; renderPane(); }, 120); }

export function perfRows(all = PERF.all) {
  fillWall();
  return RUN.order.map((r) => {
    const rec = COOK.get(r.id) || {};
    const n = nodeOf(r.id);
    return { id: r.id, node: n, title: n ? (n.title || n.type) : `#${r.id}`, time: r.time ?? r.wall,
             state: r.state, pcg: !!rec.pcg };
  }).filter((r) => all || r.pcg || r.state === "error")
    .sort((a, b) => (b.time ?? -1) - (a.time ?? -1));
}

export function renderPane() {
  const P = PERF.pane;
  if (!P || !P.isOpen()) return;
  const rows = perfRows();
  const tot = RUN.start ? ((RUN.end || now()) - RUN.start) / 1000 : 0;
  const cooked = rows.filter((r) => r.state !== "cached");
  const sum = cooked.reduce((a, r) => a + (r.time || 0), 0);
  const maxT = Math.max(1e-9, ...rows.map((r) => r.time || 0));
  const b = P.body;
  b.innerHTML = "";
  const tools = document.createElement("div");
  tools.className = "tools";
  tools.innerHTML = `<label><input type="checkbox" ${PERF.all ? "checked" : ""}> every node (not only PCG)</label>`;
  tools.querySelector("input").onchange = (e) => { PERF.all = e.target.checked; renderPane(); };
  b.appendChild(tools);
  const s = document.createElement("div");
  s.className = "sum";
  s.textContent = !RUN.start ? "No run yet: press Run, the nodes are listed here as they cook."
    : `${RUN.running ? "Running" : "Last run"}: ${fmtTime(tot)} in all · ${cooked.length} cooked ` +
      `(${fmtTime(sum)}), ${rows.length - cooked.length} cached`;
  b.appendChild(s);
  for (const r of rows) {
    const row = document.createElement("div");
    row.className = "row " + r.state;
    row.title = r.id;
    row.innerHTML = `<span class="nm">${esc(r.title)}</span><span class="bar"><i style="width:${
      r.state === "cached" ? 0 : Math.round(100 * (r.time || 0) / maxT)}%"></i></span>` +
      `<span class="tm">${r.state === "cached" ? "cached" : r.state === "error" ? "failed" : fmtTime(r.time)}</span>`;
    row.onclick = () => frameNode(r.id);
    b.appendChild(row);
  }
}

/** Select a node and bring it to the middle of the canvas (the instance, for a node inside a subgraph not shown). */
export function frameNode(id) {
  const c = app.canvas;
  let n = nodeOf(id);
  if (n && n.graph !== c?.graph) n = nodeOf(String(id).split(":")[0]);
  if (!n || !c) return false;
  c.selectNode?.(n);
  const s = c.ds.scale, el = c.canvas;
  const W = el.width / (globalThis.devicePixelRatio || 1), H = el.height / (globalThis.devicePixelRatio || 1);
  c.ds.offset[0] = -n.pos[0] - n.size[0] / 2 + W / (2 * s);
  c.ds.offset[1] = -n.pos[1] - n.size[1] / 2 + H / (2 * s);
  c.setDirty?.(true, true);
  return true;
}

function buildPane() {
  css();
  const P = floatingPane({ key: "pcg.perf.pane", title: "Performance", cls: "pcg-perf",
                           rect: { x: 80, y: 120, w: 380, h: 420 }, onOpen: () => renderPane(),
                           open: false });
  PERF.pane = P;
  P.withTab("Performance", "Show the performance pane (the last run, node by node)", 1);
  if (P.isOpen()) renderPane();
  return P;
}

// ════════════════════════════════════════════════════════ wiring
api.addEventListener?.("pcg.cook", (e) => onCook(e.detail));
api.addEventListener?.("execution_start", (e) => onStart(e.detail));
api.addEventListener?.("executing", (e) => onExecuting(e.detail));
api.addEventListener?.("execution_cached", (e) => onCached(e.detail));
api.addEventListener?.("execution_error", (e) => onError(e.detail));
api.addEventListener?.("execution_success", () => onSuccess());

app.registerExtension({
  name: "pcg.cook",
  settings: [{
    id: SETTING_TIME,
    category: ["PCG", "Network", "Cook time"],
    name: "Show the cook time above each node",
    type: "boolean",
    defaultValue: true,
  }],
  async setup() {
    if (typeof document === "undefined") return;
    const c = app.canvas;
    if (c) {
      const fg = c.onDrawForeground;
      c.onDrawForeground = function (ctx) {
        const r = fg?.apply(this, arguments);
        try { drawBadges(ctx, this); } catch (e) { /* badges must not stop the canvas */ }
        return r;
      };
    }
    hookMiddle();
    buildPane();
    // values and wires change without events: the out-of-date set is refreshed a few times a second
    let key = "";
    setInterval(() => {
      try {
        if (!COOK.size) return;
        computeDirty();
        const k = [...DIRTY].map((n) => n.id).join(",");
        if (k !== key) { key = k; app.canvas?.setDirty?.(true, false); }
      } catch (e) { /* */ }
    }, 400);
  },
});
