// comfyui_pcg/web/pcg_presets.js
//
// Parameter presets (Houdini's gear menu: Save Preset…, the presets of the node type, Delete Preset, Revert to
// Defaults). A preset is the node's parameter values by name -- its own, its custom (spare) ones, and for a digital
// asset its promoted ones -- stored per node type (an asset: per asset name) in the user's ComfyUI data
// (userdata/pcg/presets.json), so every workflow of this user has them.

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const FILE = "pcg/presets.json";
let CACHE = null;

export function presetKey(node) {
  if (node?.subgraph) return `asset:${node.subgraph.name || node.type}`;
  return String(node?.type || "");
}

const skip = (w) => !w || w.name === "pcg_panel" || w.type === "button" || w.type === "pcg_cop_preview"
  || (w.origType ?? w.type) === "pcg-hidden" || w.name === "ch_params";

/** The values a preset records: {widget name: value} (spare parameters included: they are widgets too). */
export function captureValues(node) {
  const out = {};
  for (const w of node?.widgets || []) {
    if (skip(w)) continue;
    const v = w.value;
    if (v === undefined || typeof v === "function" || (typeof v === "object" && v !== null && !Array.isArray(v))) continue;
    out[w.name] = Array.isArray(v) ? v.slice() : v;
  }
  return out;
}

/** Write values into the node's widgets (as the panel would: value, callback, node.onWidgetChanged). -> count. */
export function applyValues(node, values) {
  let n = 0;
  for (const w of node?.widgets || []) {
    if (skip(w) || !(w.name in (values || {}))) continue;
    const v = values[w.name];
    if (JSON.stringify(v) === JSON.stringify(w.value)) continue;
    const old = w.value;
    w.value = Array.isArray(v) ? v.slice() : v;
    try { w.callback?.(w.value, app.canvas, node, [0, 0], null); } catch (e) { /* */ }
    try { node.onWidgetChanged?.(w.name, w.value, old, w); } catch (e) { /* */ }
    n++;
  }
  node?.setDirtyCanvas?.(true, true);
  return n;
}

/** The defaults of a node's parameters (from its definition; spare / asset ones from their own specs). */
export function defaultValues(node, nodeData = null) {
  const nd = nodeData || node?._pcgDocked?.nd || withSpareUi(node);
  const out = {};
  for (const g of ["required", "optional"]) {
    for (const [k, s] of Object.entries(nd?.input?.[g] || {})) {
      if (!Array.isArray(s)) continue;
      const o = s[1] || {};
      if ("default" in o) out[k] = o.default;
      else if (Array.isArray(s[0]) && s[0].length) out[k] = s[0][0];
    }
  }
  return out;
}

function withSpareUi(node) {
  const nd = node?.constructor?.nodeData;
  const extra = node?._pcgSpareUi;
  if (!extra) return nd;
  return { ...nd, input: { ...(nd?.input || {}), optional: { ...(nd?.input?.optional || {}), ...extra } } };
}

export function revertToDefaults(node) {
  return applyValues(node, defaultValues(node));
}

// ── storage
export async function loadAll(force = false) {
  if (CACHE && !force) return CACHE;
  try {
    const r = await api.fetchApi(`/userdata/${encodeURIComponent(FILE)}`);
    CACHE = r.ok ? (await r.json()) || {} : {};
  } catch (e) {
    CACHE = {};
  }
  return CACHE;
}

async function saveAll(all) {
  CACHE = all;
  const r = await api.fetchApi(`/userdata/${encodeURIComponent(FILE)}?overwrite=true`, {
    method: "POST", body: JSON.stringify(all, null, 1), headers: { "Content-Type": "application/json" },
  });
  return r.ok;
}

export async function listPresets(node) {
  const all = await loadAll();
  return Object.keys(all[presetKey(node)] || {}).sort((a, b) => a.localeCompare(b));
}

export async function savePreset(node, name) {
  name = String(name || "").trim();
  if (!name) return false;
  const all = { ...(await loadAll()) };
  const k = presetKey(node);
  all[k] = { ...(all[k] || {}), [name]: captureValues(node) };
  return saveAll(all);
}

export async function applyPreset(node, name) {
  const all = await loadAll();
  const v = all[presetKey(node)]?.[name];
  if (!v) return 0;
  const n = applyValues(node, v);
  // a multiparm count makes its instances only after it is set: their values on a second pass
  await new Promise((r) => setTimeout(r, 60));
  return n + applyValues(node, v);
}

export async function deletePreset(node, name) {
  const all = { ...(await loadAll()) };
  const k = presetKey(node);
  if (!all[k]?.[name]) return false;
  const m = { ...all[k] };
  delete m[name];
  if (Object.keys(m).length) all[k] = m; else delete all[k];
  return saveAll(all);
}

// ── UI: a small name box (not window.prompt: that blocks the page) and the menu
export function askName(title, initial = "") {
  return new Promise((resolve) => {
    const mask = document.createElement("div");
    mask.style.cssText = "position:fixed;inset:0;z-index:1300;background:#0006;display:flex;align-items:center;justify-content:center";
    const box = document.createElement("div");
    box.className = "pcg-ask";
    box.style.cssText = "background:#1b1e23;border:1px solid #3a4150;border-radius:8px;padding:14px;min-width:300px;" +
      "color:#cfd5dc;font:12px Inter,'Segoe UI',system-ui,sans-serif;box-shadow:0 10px 40px #000c";
    box.innerHTML = `<div style="margin-bottom:8px;color:#e6eaee;font-weight:600"></div>`;
    box.firstChild.textContent = title;
    const inp = document.createElement("input");
    inp.value = initial;
    inp.style.cssText = "width:100%;box-sizing:border-box;background:#16181b;color:#e3e7eb;border:1px solid #3a4150;" +
      "border-radius:4px;padding:5px 7px;font:inherit";
    box.appendChild(inp);
    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:8px;justify-content:flex-end;margin-top:10px";
    const mk = (t, f) => {
      const b = document.createElement("button");
      b.textContent = t;
      b.style.cssText = "background:#2a2f3a;border:1px solid #3a4150;border-radius:4px;color:#dfe4e9;padding:4px 12px;cursor:pointer;font:inherit";
      b.onclick = f;
      row.appendChild(b);
      return b;
    };
    const done = (v) => { mask.remove(); resolve(v); };
    mk("Cancel", () => done(null));
    mk("Save", () => done(inp.value.trim() || null)).style.background = "#2f5a8a";
    box.appendChild(row);
    mask.appendChild(box);
    mask.addEventListener("pointerdown", (e) => { if (e.target === mask) done(null); });
    inp.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter") done(inp.value.trim() || null);
      if (e.key === "Escape") done(null);
    });
    document.body.appendChild(mask);
    setTimeout(() => inp.focus(), 0);
  });
}

/** Menu entries (LiteGraph ContextMenu format) for a node's presets. */
export async function presetMenuItems(node, after = () => {}) {
  const names = await listPresets(node);
  const items = names.map((n) => ({ content: n, callback: async () => { await applyPreset(node, n); after(); } }));
  if (items.length) items.push(null);
  items.push({
    content: "Save Preset…",
    callback: async () => {
      const name = await askName(`Save the parameters of "${node.title || node.type}" as a preset`);
      if (name) { await savePreset(node, name); after(); }
    },
  });
  if (names.length) {
    items.push({
      content: "Delete Preset",
      has_submenu: true,
      submenu: { options: names, callback: async (v) => { await deletePreset(node, v?.content ?? v); after(); } },
    });
  }
  items.push({ content: "Revert to Defaults", callback: () => { revertToDefaults(node); after(); } });
  return items;
}

export async function openPresetMenu(node, event, after) {
  const items = await presetMenuItems(node, after);
  const LG = globalThis.LiteGraph;
  if (LG?.ContextMenu) return new LG.ContextMenu(items, { event, title: "Presets" });
  return null;
}
