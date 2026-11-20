// comfyui_pcg/web/pcg_hda.js
//
// Digital assets on ComfyUI subgraphs (Houdini's HDA).
//
// ComfyUI already has the pieces: Convert to Subgraph folds nodes into one (Houdini's collapse into a subnet), a
// widget promoted to the subgraph node becomes an input of the subgraph with a widget on the instance, and Publish
// Subgraph puts it in the node library. What this file adds is the asset's *parameter interface*:
//
//   · the instance's parameters are shown in the docked pane with the PCG panel: each promoted parameter takes the
//     look of the parameter it drives inside (label, slider and range, menu labels, vector / colour / ramp kind)
//   · "PCG: Edit Asset Interface…" (node menu of a subgraph node) is Houdini's Type Properties: pick parameters of
//     the nodes inside to promote, order them, give them a label, a folder (tab) and a section, a range and a
//     default, hide / disable rules on the other parameters, a help text; remove them again
//
// The interface is stored on the subgraph *definition* (subgraph.extra.pcg_iface), so every instance shows the same
// parameters, as an HDA's do; only the values are per instance (they are ComfyUI's own: the subgraph inputs).

import { app } from "../../scripts/app.js";
import { UI_KEY } from "./pcg_panel.js";

export const IFACE = "pcg_iface";

export const isHda = (node) => !!node?.subgraph;

function linkOf(graph, id) {
  return graph?.links?.get?.(id) ?? graph?.links?.[id] ?? null;
}

/**
 * The promoted parameters of an instance, in its input order:
 * [{name, input, slot (the subgraph input), targets: [{node, widget, name}]}].
 */
export function promoted(sn) {
  const sg = sn?.subgraph;
  if (!sg) return [];
  const out = [];
  for (const input of sn.inputs || []) {
    if (!input?.widget) continue;
    const slot = input._subgraphSlot || sg.inputs?.find((s) => s.name === input.name);
    const targets = [];
    for (const lid of slot?.linkIds || []) {
      const l = linkOf(sg, lid);
      const n = l ? sg.getNodeById?.(l.target_id) : null;
      const wname = n?.inputs?.[l.target_slot]?.widget?.name;
      if (n && wname) targets.push({ node: n, name: wname, widget: n.widgets?.find((w) => w.name === wname) });
    }
    out.push({ name: input.widget.name || input.name, input, slot, targets });
  }
  return out;
}

export function iface(sg) {
  let e = sg?.extra?.[IFACE];
  if (!e && sg) {
    // a definition that came without it (inserted from the library, pasted): what its instances carry
    const inst = instancesOf(sg).find((n) => n.properties?.[IFACE]);
    if (inst) { e = inst.properties[IFACE]; sg.extra = { ...(sg.extra || {}), [IFACE]: e }; }
  }
  return { params: { ...(e?.params || {}) }, order: [...(e?.order || [])] };
}

/**
 * Stored on the definition (shared by its instances in this workflow) and copied onto each instance's properties:
 * those travel where a definition's extra does not (Publish Subgraph, copy and paste).
 */
export function setIface(sg, value) {
  const v = { params: value.params || {}, order: value.order || [] };
  sg.extra = sg.extra || {};
  sg.extra[IFACE] = v;
  for (const n of instancesOf(sg)) {
    n.properties = n.properties || {};
    n.properties[IFACE] = JSON.parse(JSON.stringify(v));
  }
}

function innerSpec(node, name) {
  const nd = node?.constructor?.nodeData;
  for (const g of ["required", "optional"]) {
    const s = nd?.input?.[g]?.[name];
    if (s) return s;
  }
  return null;
}

/** A plain spec for a widget the node definition does not describe (other extensions' widgets). */
function guessSpec(w) {
  const t = w?.type;
  if (t === "combo") return [w.options?.values || [], {}];
  if (t === "toggle" || t === "boolean") return ["BOOLEAN", {}];
  if (t === "number" || t === "slider") {
    const o = w.options || {};
    return [o.precision === 0 || o.round === 1 ? "INT" : "FLOAT", { min: o.min, max: o.max, step: o.step2 ?? o.step }];
  }
  return ["STRING", { multiline: t === "customtext" }];
}

const STRUCT = ["row", "in_row", "toggle", "in_toggle", "in_ramp", "gate", "section", "folder", "_node", "hide",
                "disable", "sep"];

/**
 * The nodeData the panel draws an instance with: one input per promoted parameter, with the spec and panel look of
 * the parameter it drives inside, then the interface's overrides. Rows, toggles and rules of the inner node refer
 * to its own names: kept where every name they use is promoted (renamed), dropped otherwise.
 */
export function hdaNodeData(sn) {
  const ps = promoted(sn);
  const ifc = iface(sn.subgraph);
  const req = {};
  const host = new Map();                    // inner node id + inner name -> host name
  for (const p of ps) for (const t of p.targets) host.set(`${t.node.id}|${t.name}`, p.name);
  const order = [...ifc.order.filter((n) => ps.some((p) => p.name === n)),
                 ...ps.map((p) => p.name).filter((n) => !ifc.order.includes(n))];
  for (const name of order) {
    const p = ps.find((x) => x.name === name);
    const t = p.targets[0];
    const base = (t && innerSpec(t.node, t.name)) || guessSpec(t?.widget || sn.widgets?.find((w) => w.name === name));
    const opts = { ...(base[1] || {}) };
    const u0 = opts[UI_KEY] || {};
    const u = { ...u0 };
    for (const k of STRUCT) delete u[k];
    const map = (n) => (t ? host.get(`${t.node.id}|${n}`) : null);
    // a vector / colour row survives when all its members are promoted
    if (u0.row && t) {
      const mem = (u0.row.members || []).map(map);
      if (mem.every(Boolean) && mem[0] === name) u.row = { ...u0.row, members: mem };
    }
    if (u0.in_row && t) {
      const lead = map(u0.in_row);
      const lu = lead && innerSpec(t.node, u0.in_row)?.[1]?.[UI_KEY];
      if (lead && (lu?.row?.members || []).every((m) => map(m))) u.in_row = lead;
    }
    if (u.kind === "ramp" && u0.ramp?.interp) {
      const it = map(u0.ramp.interp);
      u.ramp = { ...u0.ramp };
      if (it) u.ramp.interp = it; else delete u.ramp.interp;
    }
    if (!u.label) u.label = p.input.label || p.slot?.label || name;
    const o = ifc.params[name] || {};
    if (o.label) u.label = o.label;
    if (o.folder) u.folder = o.folder;
    if (o.section) u.section = o.section;
    if (o.hide) u.hide = o.hide;
    if (o.disable) u.disable = o.disable;
    if (o.help) u.help = o.help;
    if (o.min !== undefined && o.min !== "" && Number.isFinite(Number(o.min))) opts.min = Number(o.min);
    if (o.max !== undefined && o.max !== "" && Number.isFinite(Number(o.max))) opts.max = Number(o.max);
    if (o.default !== undefined && o.default !== "") opts.default = o.default;
    opts[UI_KEY] = u;
    req[name] = [base[0], opts];
  }
  const first = order[0];
  if (first) req[first][1][UI_KEY] = { ...req[first][1][UI_KEY], _node: { order } };
  return { name: sn.type, display_name: sn.title, input: { required: req, optional: {} }, _hda: true };
}

/** A signature of what the instance's panel is built from (promoted names, interface): rebuilt when it changes. */
export function hdaSig(sn) {
  try {
    return JSON.stringify([promoted(sn).map((p) => [p.name, p.targets.map((t) => [t.node.id, t.name])]),
                           sn.subgraph?.extra?.[IFACE] || null]);
  } catch (e) { return ""; }
}

/** Promote a widget of a node inside the asset (as the frontend's Promote Widget does): -> the new input's name. */
export function promote(sn, inner, wname) {
  const sg = sn.subgraph;
  const w = inner.widgets?.find((x) => x.name === wname);
  const slot = w && inner.getSlotFromWidget?.(w);
  if (!slot) return null;
  if (slot.link != null) {                                    // already driven: by this asset's input?
    const l = linkOf(sg, slot.link);
    const s = sg.inputs?.find((x) => (x.linkIds || []).includes(slot.link));
    return s ? s.name : (l ? null : null);
  }
  const names = new Set((sg.inputs || []).map((x) => x.name));
  let name = wname, k = 1;
  while (names.has(name)) name = `${wname}_${k++}`;
  const o = sg.addInput(name, String(slot.type ?? w.type ?? "*"));
  o.label = slot.label || w.label;
  if (!o.connect(slot, inner)) { sg.removeInput(o); return null; }
  // the instance starts with the inner value
  const hw = sn.widgets?.find((x) => x.name === name);
  if (hw && w) hw.value = w.value;
  return name;
}

export function demote(sn, name) {
  const sg = sn.subgraph;
  const s = sg?.inputs?.find((x) => x.name === name);
  if (!s) return false;
  const back = promoted(sn).find((p) => p.name === name);
  const hv = sn.widgets?.find((w) => w.name === name)?.value;
  sg.removeInput(s);
  for (const t of back?.targets || []) if (t.widget && hv !== undefined) t.widget.value = hv;   // keep the value inside
  const ifc = iface(sg);
  delete ifc.params[name];
  ifc.order = ifc.order.filter((n) => n !== name);
  setIface(sg, ifc);
  return true;
}

/** Every instance of the same definition in the workflow (they share the interface). */
export function instancesOf(sg) {
  const out = [];
  const walk = (g, d) => {
    if (d > 8) return;
    for (const n of g?._nodes || []) {
      if (!n.subgraph) continue;
      if (n.subgraph === sg || n.subgraph.id === sg.id) out.push(n);
      walk(n.subgraph, d + 1);
    }
  };
  walk(app.graph, 0);
  return out;
}

// ═════════════════════════════════════════════════════════ the interface dialog
const CSS = `
.pcghda-mask{position:fixed;inset:0;z-index:1200;background:#0007;display:flex;align-items:center;justify-content:center}
.pcghda{width:min(980px,96vw);height:min(640px,92vh);display:flex;flex-direction:column;background:#1b1e23;
  border:1px solid #3a4150;border-radius:8px;box-shadow:0 10px 40px #000c;color:#cfd5dc;
  font:12px Inter,"Segoe UI",system-ui,sans-serif}
.pcghda .top{padding:8px 12px;border-bottom:1px solid #2b313b;display:flex;gap:8px;align-items:center}
.pcghda .top b{font-size:13px;color:#e6eaee}.pcghda .top span{color:#7d8794}
.pcghda .cols{flex:1 1 auto;display:flex;min-height:0}
.pcghda .col{display:flex;flex-direction:column;min-height:0;border-right:1px solid #2b313b}
.pcghda .col h4{margin:0;padding:6px 10px;font-size:11px;color:#9aa4b2;text-transform:uppercase;letter-spacing:.04em}
.pcghda .list{flex:1 1 auto;overflow:auto;padding:0 6px 6px}
.pcghda .it{padding:2px 6px;border-radius:3px;cursor:pointer;display:flex;gap:6px;align-items:center;white-space:nowrap}
.pcghda .it:hover{background:#262a31}.pcghda .it.on{background:#33465e;color:#fff}
.pcghda .it.dis{color:#5d6570;cursor:default}.pcghda .it .sub{color:#7d8794;font-size:11px}
.pcghda .nd{padding:4px 6px 1px;color:#e0975f;font-weight:600}
.pcghda .mid{width:52px;align-items:center;justify-content:center;gap:6px;display:flex;flex-direction:column}
.pcghda button{background:#2a2f3a;border:1px solid #3a4150;border-radius:4px;color:#dfe4e9;padding:3px 9px;cursor:pointer;
  font:inherit}.pcghda button:hover{background:#3c5a86}.pcghda button:disabled{opacity:.4;cursor:default}
.pcghda .form{flex:1 1 auto;padding:8px 12px;overflow:auto}
.pcghda .form label{display:flex;align-items:center;gap:8px;margin:4px 0}.pcghda .form label span{flex:0 0 96px;text-align:right;color:#aeb6bf}
.pcghda .form input,.pcghda .form textarea{flex:1 1 auto;background:#16181b;color:#e3e7eb;border:1px solid #3a4150;border-radius:3px;
  padding:3px 6px;font:inherit;min-width:0}.pcghda .form textarea{height:52px;resize:vertical}
.pcghda .form .hint{color:#7d8794;font-size:11px;margin:2px 0 6px 104px}
.pcghda .bot{padding:8px 12px;border-top:1px solid #2b313b;display:flex;gap:8px;justify-content:flex-end}
.pcghda .bot .ok{background:#2f5a8a}
`;

function el(tag, cls, parent, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  parent?.appendChild(e);
  return e;
}

/** Editable copy of the interface; Apply writes it back (promotions / removals happen at once, as in Houdini). */
export class AssetDialog {
  constructor(sn, onApply) {
    this.sn = sn;
    this.sg = sn.subgraph;
    this.onApply = onApply;
    this.ifc = iface(this.sg);
    this.sel = null;
    if (!document.getElementById("pcg-hda-css")) {
      const st = el("style");
      st.id = "pcg-hda-css";
      st.textContent = CSS;
      document.head.appendChild(st);
    }
    this.mask = el("div", "pcghda-mask", document.body);
    const d = el("div", "pcghda", this.mask);
    this.root = d;
    const top = el("div", "top", d);
    el("b", "", top, `Edit Asset Interface — ${sn.title || "Subgraph"}`);
    el("span", "", top, `${instancesOf(this.sg).length} instance(s) share it`);
    const cols = el("div", "cols", d);
    const c1 = el("div", "col", cols); c1.style.width = "34%";
    el("h4", "", c1, "Nodes inside");
    this.left = el("div", "list", c1);
    const mid = el("div", "col mid", cols);
    this.addBtn = el("button", "", mid, "→");
    this.addBtn.title = "Promote the parameter picked on the left";
    this.addBtn.onclick = () => this.add();
    const c2 = el("div", "col", cols); c2.style.width = "26%";
    el("h4", "", c2, "Asset parameters");
    this.right = el("div", "list", c2);
    const tools = el("div", "", c2);
    tools.style.cssText = "display:flex;gap:6px;padding:6px";
    this.upBtn = el("button", "", tools, "↑"); this.upBtn.onclick = () => this.move(-1);
    this.downBtn = el("button", "", tools, "↓"); this.downBtn.onclick = () => this.move(1);
    this.rmBtn = el("button", "", tools, "Remove"); this.rmBtn.onclick = () => this.remove();
    const c3 = el("div", "col", cols); c3.style.cssText = "flex:1 1 auto;border-right:none";
    el("h4", "", c3, "Parameter");
    this.form = el("div", "form", c3);
    const bot = el("div", "bot", d);
    const cancel = el("button", "", bot, "Close");
    cancel.onclick = () => this.close();
    const ok = el("button", "ok", bot, "Apply");
    ok.onclick = () => { this.apply(); this.close(); };
    this.mask.addEventListener("pointerdown", (e) => { if (e.target === this.mask) this.close(); });
    this.mask.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); this.close(); } });
    this.pick = null;
    this.render();
  }

  names() {
    const ps = promoted(this.sn).map((p) => p.name);
    return [...this.ifc.order.filter((n) => ps.includes(n)), ...ps.filter((n) => !this.ifc.order.includes(n))];
  }

  render() {
    // left: every widget of every node inside (those already driven greyed)
    this.left.innerHTML = "";
    const driven = new Set(promoted(this.sn).flatMap((p) => p.targets.map((t) => `${t.node.id}|${t.name}`)));
    for (const n of this.sg._nodes || []) {
      const ws = (n.widgets || []).filter((w) => n.getSlotFromWidget?.(w) && w.type !== "pcg-hidden"
        && (w.origType ?? w.type) !== "pcg-hidden");
      if (!ws.length) continue;
      el("div", "nd", this.left, n.title || n.type);
      for (const w of ws) {
        const k = `${n.id}|${w.name}`;
        const u = innerSpec(n, w.name)?.[1]?.[UI_KEY];
        const it = el("div", "it" + (driven.has(k) ? " dis" : "") + (this.pick === k ? " on" : ""), this.left);
        el("span", "", it, u?.label || w.label || w.name);
        el("span", "sub", it, w.name);
        it.dataset.k = k;
        if (!driven.has(k)) {
          it.onclick = () => { this.pick = k; this.render(); };
          it.ondblclick = () => { this.pick = k; this.add(); };
        }
      }
    }
    this.addBtn.disabled = !this.pick;
    // middle: the asset's parameters in order
    this.right.innerHTML = "";
    const nd = hdaNodeData(this.sn);
    for (const n of this.names()) {
      const it = el("div", "it" + (this.sel === n ? " on" : ""), this.right);
      const u = nd.input.required[n]?.[1]?.[UI_KEY] || {};
      const o = this.ifc.params[n] || {};
      el("span", "", it, o.label || u.label || n);
      el("span", "sub", it, [o.folder, o.section].filter(Boolean).join(" / ") || n);
      it.dataset.n = n;
      it.onclick = () => { this.sel = n; this.render(); };
    }
    for (const b of [this.upBtn, this.downBtn, this.rmBtn]) b.disabled = !this.sel;
    this.renderForm(nd);
  }

  renderForm(nd) {
    this.form.innerHTML = "";
    const n = this.sel;
    if (!n) { el("div", "hint", this.form, "Pick a parameter of the asset to edit it."); return; }
    const spec = nd.input.required[n] || ["", {}];
    const u = spec[1][UI_KEY] || {};
    const o = (this.ifc.params[n] = { ...(this.ifc.params[n] || {}) });
    const p = promoted(this.sn).find((x) => x.name === n);
    el("div", "hint", this.form, `drives ${p?.targets.map((t) => `${t.node.title || t.node.type} · ${t.name}`).join(", ")}`)
      .style.marginLeft = "0";
    const num = spec[0] === "INT" || spec[0] === "FLOAT";
    const field = (key, label, ph, hint, ta = false) => {
      const l = el("label", "", this.form);
      el("span", "", l, label);
      const i = el(ta ? "textarea" : "input", "", l);
      i.value = o[key] ?? "";
      i.placeholder = ph ?? "";
      i.dataset.k = key;
      i.oninput = () => {
        if (i.value === "") delete o[key]; else o[key] = i.value;
        if (key === "label" || key === "folder" || key === "section") this.renderList();
      };
      if (hint) el("div", "hint", this.form, hint);
      return i;
    };
    field("label", "Label", u.label || n);
    field("folder", "Folder (tab)", "", "Parameters with the same folder share a tab.");
    field("section", "Section", "", "A collapsible section inside the folder.");
    if (num) {
      field("min", "Minimum", spec[1].min ?? "");
      field("max", "Maximum", spec[1].max ?? "");
    }
    field("default", "Default", spec[1].default ?? "", "Used by Revert to Defaults.");
    field("hide", "Hide when", "", 'e.g. { mode == ramp } — names are the asset\'s parameters: ' + this.names().join(", "));
    field("disable", "Disable when", "");
    field("help", "Help", "", null, true);
  }

  renderList() {
    const sel = this.sel;
    for (const it of this.right.querySelectorAll(".it")) {
      const n = it.dataset.n;
      const o = this.ifc.params[n] || {};
      if (n === sel) {
        it.firstChild.textContent = o.label || n;
        it.lastChild.textContent = [o.folder, o.section].filter(Boolean).join(" / ") || n;
      }
    }
  }

  add() {
    if (!this.pick) return;
    const [id, wname] = this.pick.split("|");
    const inner = this.sg.getNodeById?.(id) ?? this.sg._nodes.find((x) => String(x.id) === id);
    const name = inner && promote(this.sn, inner, wname);
    this.pick = null;
    if (name) {
      this.sel = name;
      if (!this.ifc.order.includes(name)) this.ifc.order = [...this.names()];
    }
    this.render();
  }

  remove() {
    if (!this.sel) return;
    const n = this.sel;
    demote(this.sn, n);
    delete this.ifc.params[n];
    this.ifc.order = this.ifc.order.filter((x) => x !== n);
    this.sel = null;
    this.render();
  }

  move(d) {
    if (!this.sel) return;
    const order = this.names();
    const i = order.indexOf(this.sel), j = i + d;
    if (i < 0 || j < 0 || j >= order.length) return;
    [order[i], order[j]] = [order[j], order[i]];
    this.ifc.order = order;
    this.render();
  }

  apply() {
    const clean = {};
    for (const [k, v] of Object.entries(this.ifc.params)) {
      const o = Object.fromEntries(Object.entries(v || {}).filter(([, x]) => x !== "" && x != null));
      if (Object.keys(o).length) clean[k] = o;
    }
    setIface(this.sg, { params: clean, order: this.names() });
    app.graph?.setDirtyCanvas?.(true, true);
    this.onApply?.(this.sg);
  }

  close() {
    this.mask.remove();
  }
}

export function openAssetDialog(sn, onApply) {
  return new AssetDialog(sn, onApply);
}


// ═════════════════════════════════════════════════════════ the library (Publish Subgraph)
// A published asset is a file in the user's subgraphs/ folder; an asset is known by its name (as an HDA by its type
// name). Inserting it, or copying an instance, gives the workflow a copy of the definition: the instances do not follow
// the library by themselves. Here: whether the library's version differs, and updating every instance of the name.

let LIB = { at: 0, files: null };
async function api() { return (await import("../../scripts/api.js")).api; }

export async function libraryFiles(maxAge = 5000) {
  if (LIB.files && Date.now() - LIB.at < maxAge) return LIB.files;
  try {
    const r = await (await api()).fetchApi("/userdata?dir=subgraphs&recurse=true");
    LIB = { at: Date.now(), files: r.ok ? await r.json() : [] };
  } catch (e) {
    LIB = { at: Date.now(), files: [] };
  }
  return LIB.files;
}

export async function libraryGet(file) {
  const r = await (await api()).fetchApi(`/userdata/${encodeURIComponent("subgraphs/" + file)}`);
  if (!r.ok) return null;
  return r.json();
}

/** What makes two versions of a definition the same asset version: its nodes, values, wires, inputs and outputs. */
export function defHash(def) {
  if (!def) return "";
  const nodes = [...(def.nodes || [])].map((n) => [String(n.id), n.type, n.mode ?? 0,
    JSON.stringify(n.widgets_values ?? null)]).sort((a, b) => (a[0] < b[0] ? -1 : 1));
  const links = [...(def.links || [])].map((l) => Array.isArray(l) ? l.slice(1, 5).join(",")
    : [l.origin_id, l.origin_slot, l.target_id, l.target_slot].join(",")).sort();
  const io = [(def.inputs || []).map((x) => x.name), (def.outputs || []).map((x) => x.name)];
  return JSON.stringify([nodes, links, io]);
}

function serializedDef(sg) {
  try { return sg.asSerialisable ? sg.asSerialisable() : sg.serialize?.(); } catch (e) { return null; }
}

/** The library entry of an asset (by its definition's name): {file, data, def} or null. */
export async function libraryEntry(sg) {
  const name = sg?.name;
  if (!name) return null;
  const files = await libraryFiles();
  const file = files.find((f) => String(f).replace(/\.json$/i, "") === name);
  if (!file) return null;
  const data = await libraryGet(file);
  const top = data?.nodes?.find((n) => n.type && (data.definitions?.subgraphs || []).some((d) => d.id === n.type));
  const def = top ? data.definitions.subgraphs.find((d) => d.id === top.type) : data?.definitions?.subgraphs?.[0];
  return def ? { file, data, def, node: top || null } : null;
}

/** "same" | "differs" | "none" (not in the library). */
export async function libraryState(sg) {
  const e = await libraryEntry(sg);
  if (!e) return "none";
  return defHash(e.def) === defHash(serializedDef(sg)) ? "same" : "differs";
}

/**
 * Every definition of this asset name in the workflow takes the library's version (ids kept; nested definitions
 * added when missing), its interface too; the instances keep their parameter values (by name). -> instances updated.
 */
export async function updateFromLibrary(sg) {
  const e = await libraryEntry(sg);
  if (!e) return 0;
  const root = app.graph;
  const defs = new Map();
  const walk = (g, d) => {
    for (const n of g?._nodes || []) if (n.subgraph && d < 8) { if (n.subgraph.name === sg.name) defs.set(n.subgraph.id, n.subgraph); walk(n.subgraph, d + 1); }
  };
  walk(root, 0);
  for (const nested of e.data.definitions?.subgraphs || []) {
    if (nested.id !== e.def.id && !root.subgraphs?.get?.(nested.id)) root.createSubgraph?.(JSON.parse(JSON.stringify(nested)));
  }
  const lib = e.node?.properties?.[IFACE] || e.def.extra?.[IFACE] || null;
  let count = 0;
  for (const target of defs.values()) {
    const insts = instancesOf(target);
    const vals = insts.map((n) => Object.fromEntries((n.widgets || []).map((w) => [w.name, w.value])));
    const data = JSON.parse(JSON.stringify(e.def));
    data.id = target.id;
    data.name = target.name;
    target.configure(data);
    if (lib) setIface(target, lib);
    insts.forEach((n, i) => {
      for (const w of n.widgets || []) if (w.name in vals[i]) w.value = vals[i][w.name];
      n.setDirtyCanvas?.(true, true);
      count++;
    });
  }
  root.setDirtyCanvas?.(true, true);
  return count;
}
