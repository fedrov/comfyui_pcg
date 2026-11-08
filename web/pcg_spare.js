// comfyui_pcg/web/pcg_spare.js
//
// Custom parameters on any node (pcg104) -- Houdini's spare parameters: on any node, gear -> Edit Parameter
// Interface to add parameters, then reference them from other parameters with ch("amp"), ch("../wave1/amp"); writing ch("amp") in a Wrangle
// automatically grows an amp parameter.
//
// ━━ How to use
//   Node context menu -> "PCG: Edit Parameter Interface…" -- the same dialog as Parameters (PCG) (three columns, renames don't break references).
//   Added parameters appear at the end of the panel (a Spare tab when the node has tabs, otherwise a Spare section); in the native panel
//   they are the node's last few widgets. They can do everything the node's own parameters can: drag values, take expressions / keyframes, copy-paste references,
//   be referenced by other nodes with ch("../title/name"), be changed by viewport handles (if the names match).
//   Vector parameters split into components following Houdini naming: vector pos -> posx posy posz (ch("posx")).
//
// ━━ Where it's stored
//   Declaration text: node.properties.pcg_spare (same syntax as Parameters' declare, same parser)
//   Values:           node.properties.pcg_spare_vals (stored by name, {amp: 0.5, pos: [1, 2, 3]})
//   **Both stored by name, not in widgets_values**: the widgets are appended at the end and not serialized, so adding/removing parameters doesn't shift
//   the indices of the node's original parameters (the constraint in the pcg_params.js file header). Nor do they go into the prompt sent to the backend -- the backend only sees
//   the original inputs; references / expressions are "materialized on the frontend" into the target widget as usual.
//
// ━━ How the backend reads them
//   Nodes with ch_params (Wrangle / Volume Wrangle / COP Wrangle): whenever a value changes, the values of all custom parameters are written into
//   ch_params (JSON); ch("amp") / chv("pos") / chs("s") / chi("n") in the code read from it. Vectors are also written per component,
//   so ch("posx") works as in Houdini.
//   A ch("x") newly appearing in the code is auto-added as a custom parameter (ch / chf -> float, chi -> int, chv -> vector, chs -> string,
//   the second argument of ch("x", 0.5) is the default). Auto-added ones are deleted automatically when they disappear from the code again, their value is still the default and they aren't bound
//   (ch("a"), ch("am") appearing while typing don't stick around); ones whose value you changed, or for which you clicked Apply in the dialog, are
//   yours to manage and are not auto-deleted (Houdini doesn't delete them either).

import { app } from "../../scripts/app.js";
import { parse, mergeValues, bindings, applyBindings, isNumExpr, isTmpl, NODE_REF } from "./pcg_params.js";
import { mapChPaths, mapTemplatePaths } from "./pcg_hexpr.js";
import { parseItems, toText, openDialog } from "./pcg_paramui.js";

export const SPARE_KEY = "pcg_spare";
export const SPARE_VALS = "pcg_spare_vals";
export const SPARE_AUTO = "pcg_spare_auto";
const SKIP_TYPES = new Set(["PCG_Parameters"]);   // its parameters are declared already
const COMP = "xyzw";
const titleOf = (n) => n?.title || n?.type || "";

// ════════════════════════════════════════════════════ reading declaration / values
export function spareText(node) {
  const t = node?.properties?.[SPARE_KEY];
  return typeof t === "string" ? t : "";
}

/** declaration -> parameter specs. Throws when malformed (error messages carry line numbers, same as Parameters). */
export function spareSpecs(node) { return parse(spareText(node)); }

/** Which widget names a parameter occupies: a scalar is itself, a vector appends x y z w as in Houdini. */
export function compNames(spec) {
  return spec.n > 1 ? Array.from({ length: spec.n }, (_, i) => spec.name + COMP[i]) : [spec.name];
}

function storedVals(node) {
  const v = node?.properties?.[SPARE_VALS];
  return v && typeof v === "object" ? v : {};
}

/** Current values {name: value} (declaration + stored values; on type / range mismatch fall back to the default -- same rule as Parameters). */
export function spareValues(node) {
  let specs;
  try { specs = spareSpecs(node); } catch (_) { return {}; }
  return mergeValues(specs, storedVals(node));
}

/** The node's own parameter names (excluding custom ones): widget names + input names. Custom parameters cannot share these names. */
export function nativeNames(node) {
  const s = new Set();
  for (const w of node?.widgets || []) if (!w._pcgSpare) s.add(w.name);
  for (const i of node?.inputs || []) s.add(i.name);
  return s;
}

// ════════════════════════════════════════════════════ growing widgets
function widgetOf(node, name) { return node?.widgets?.find((w) => w.name === name); }

/** The copy the backend can read: for nodes with ch_params, write all values (vectors additionally per component) into it. */
export function pushChStore(node) {
  const w = widgetOf(node, "ch_params");
  if (!w) return false;
  let specs;
  try { specs = spareSpecs(node); } catch (_) { return false; }
  const vals = mergeValues(specs, storedVals(node));
  const out = {};
  for (const s of specs) {
    out[s.name] = vals[s.name];
    if (s.n > 1) compNames(s).forEach((c, i) => { out[c] = vals[s.name][i]; });
  }
  const txt = JSON.stringify(out);
  if (w.value === txt) return false;
  w.value = txt;
  return true;
}

function uiSpec(s, comp, first, folder) {
  const label = (s.label || s.name) + (comp === null ? "" : ` ${COMP[comp].toUpperCase()}`);
  const ui = { label, ...(folder ? { folder: "Spare" } : { section: "Spare" }) };
  if (first && s.n > 1)
    ui.row = { kind: "vector", members: compNames(s), label: s.label || s.name };
  else if (s.n > 1) ui.in_row = s.name + "x";
  const o = { pcg_ui: ui, pcg_spare: true };
  if (s.min !== null) { o.min = s.min; o.max = s.max; }
  const def = comp === null ? s.default : s.default[comp];
  o.default = def;
  if (s.type === "int") return ["INT", { ...o, step: 1 }];
  if (s.type === "bool") return ["BOOLEAN", o];
  if (s.type === "string") return ["STRING", o];
  return ["FLOAT", { ...o, step: 0.01 }];
}

/**
 * Sync widgets from the declaration. **Append only, never insert**: custom parameter widgets are always at the end,
 * serialize:false. Returns whether the structure changed (widgets added / removed).
 */
export function syncSpare(node) {
  if (!node || SKIP_TYPES.has(node.type)) return false;
  let specs;
  try {
    specs = spareSpecs(node);
    node._pcgSpareErr = "";
  } catch (e) {
    node._pcgSpareErr = e.message;
    return false;
  }
  const native = nativeNames(node);
  const clash = specs.filter((s) => compNames(s).some((c) => native.has(c)));
  if (clash.length) {
    node._pcgSpareErr = `custom parameters ${clash.map((s) => s.name).join(", ")} have the same name as the node's own parameters`;
    specs = specs.filter((s) => !clash.includes(s));
  }
  node._pcgSpareW = node._pcgSpareW || new Map();
  const vals = mergeValues(specs, storedVals(node));
  const want = new Map();
  for (const s of specs)
    compNames(s).forEach((c, i) => want.set(c, { spec: s, comp: s.n > 1 ? i : null }));
  let changed = false;
  for (const [wn, w] of [...node._pcgSpareW]) {
    const info = want.get(wn);
    if (info && w._pcgSpare.type === info.spec.type) continue;      // type changed: widget must be rebuilt
    const i = (node.widgets || []).indexOf(w);
    if (i >= 0) node.widgets.splice(i, 1);
    node._pcgSpareW.delete(wn);
    changed = true;
  }
  // When the node has tabs (folders) the custom parameters get their own tab, otherwise they are the last section of the panel
  const nd = node.constructor?.nodeData;
  const hasFolder = ["required", "optional"].some((g) => Object.values(nd?.input?.[g] || {})
    .some((v) => Array.isArray(v) && v[1]?.pcg_ui?.folder));
  const ui = {};
  for (const [wn, info] of want) {
    const s = info.spec;
    ui[wn] = uiSpec(s, info.comp, info.comp === null || info.comp === 0, hasFolder);
    const cur = info.comp === null ? vals[s.name] : vals[s.name][info.comp];
    let w = node._pcgSpareW.get(wn);
    if (w) {
      w.label = ui[wn][1].pcg_ui.label;
      if (s.type !== "bool" && s.type !== "string") {
        w.options = w.options || {};
        if (s.min !== null) { w.options.min = s.min; w.options.max = s.max; }
        else { delete w.options.min; delete w.options.max; }
      }
      if (w.value !== cur) w.value = cur;
      continue;
    }
    const cb = (v) => setSpareValue(node, s.name, info.comp, v);
    if (s.type === "bool") w = node.addWidget("toggle", wn, !!cur, cb, { serialize: false });
    else if (s.type === "string") w = node.addWidget("text", wn, String(cur ?? ""), cb, { serialize: false });
    else {
      const opt = { serialize: false, step: s.type === "int" ? 10 : 0.1,
                    precision: s.type === "int" ? 0 : 4, round: s.type === "int" ? 1 : undefined };
      if (s.min !== null) { opt.min = s.min; opt.max = s.max; }
      w = node.addWidget("number", wn, Number(cur) || 0, cb, opt);
    }
    w.serialize = false;
    w._pcgSpare = { name: s.name, comp: info.comp, type: s.type };
    w.label = ui[wn][1].pcg_ui.label;
    node._pcgSpareW.set(wn, w);
    changed = true;
  }
  node._pcgSpareUi = ui;
  // Tidy up stored values: delete those no longer in the declaration (renamed ones were already moved in applySpare)
  node.properties = node.properties || {};
  const live = new Set(specs.map((s) => s.name));
  const st = { ...storedVals(node) };
  for (const k of Object.keys(st)) if (!live.has(k)) delete st[k];
  for (const s of specs) st[s.name] = vals[s.name];
  if (Object.keys(st).length) node.properties[SPARE_VALS] = st;
  else delete node.properties[SPARE_VALS];
  pushChStore(node);
  if (changed) {
    try { node._pcgPanelRebuild?.(); } catch (e) { console.error("[pcg.spare] panel rebuild failed:", e); }
    if (node.setSize && node.computeSize) {
      const need = node.computeSize();
      node.setSize([Math.max(node.size[0], need[0]), Math.max(node.size[1], need[1])]);
    }
  }
  node.setDirtyCanvas?.(true, true);
  return changed;
}

/** A widget's value changed (panel / native widget / binding materialization / keyframe): store into properties, push the backend copy. */
export function setSpareValue(node, name, comp, v) {
  let specs;
  try { specs = spareSpecs(node); } catch (_) { return; }
  const s = specs.find((x) => x.name === name);
  if (!s) return;
  const st = { ...storedVals(node) };
  const cur = mergeValues([s], st)[name];
  if (comp === null) st[name] = s.type === "int" ? Math.round(Number(v)) : v;
  else { const a = cur.slice(); a[comp] = Number(v); st[name] = a; }
  node.properties = node.properties || {};
  node.properties[SPARE_VALS] = st;
  pushChStore(node);
}

// ════════════════════════════════════════════════════ references: who uses it, renames follow
/**
 * Walk the places in a binding that **point to this node's custom parameters**; if fn(paramName, componentSuffix) returns a new parameter name, replace it.
 * Three forms: pasted "@id/amp" (or "@id/posx"), ch("@id/amp") in expressions / templates,
 * non-canonical ch("../title/amp") (only recognized when the title is unique); plus ch("amp") in **this node's own** expressions.
 * names: Map(widget name -> [parameter name, component suffix]).
 */
function visitSpare(graph, node, owner, ref, names, fn) {
  if (typeof ref !== "string") return ref;
  const sub = (wn) => {
    const hit = names.get(wn);
    if (!hit) return null;
    const to = fn(hit[0]);
    return to == null ? null : to + hit[1];
  };
  const inPath = (path) => {
    const p = String(path);
    if (owner === node && /^[A-Za-z_]\w*$/.test(p)) return sub(p);       // its own ch("amp")
    const m = /^(@(-?\d+)|\.\.\/#(-?\d+)|\.\.\/([^/]+))\/([A-Za-z_]\w*)$/.exec(p);
    if (!m) return null;
    const id = m[2] ?? m[3];
    if (id !== undefined) { if (String(id) !== String(node.id)) return null; }
    else {
      const hits = (graph?._nodes ?? []).filter((n) => titleOf(n) === m[4]);
      if (hits.length !== 1 || hits[0] !== node) return null;
    }
    const to = sub(m[5]);
    return to == null ? null : `${m[1]}/${to}`;
  };
  if (isNumExpr(ref)) return ref[0] + mapChPaths(ref.slice(1), inPath);
  if (isTmpl(ref)) return ref[0] + mapTemplatePaths(ref.slice(1), inPath);
  const m = NODE_REF.exec(ref);
  if (m && String(m[1]) === String(node.id)) {
    const to = sub(m[2]);
    return to == null ? ref : `@${m[1]}/${to}`;
  }
  return ref;
}

function widgetNameMap(specs) {
  const m = new Map();
  for (const s of specs) {
    if (s.n > 1) compNames(s).forEach((c, i) => m.set(c, [s.name, COMP[i]]));
    else m.set(s.name, [s.name, ""]);
  }
  return m;
}

/** How many places reference each custom parameter: Map(parameter name -> count). */
export function spareUsage(graph, node) {
  let specs;
  try { specs = spareSpecs(node); } catch (_) { return new Map(); }
  const names = widgetNameMap(specs);
  const out = new Map();
  for (const n of graph?._nodes ?? [])
    for (const ref of Object.values(bindings(n) || {}))
      visitSpare(graph, node, n, ref, names, (nm) => { out.set(nm, (out.get(nm) || 0) + 1); return null; });
  return out;
}

/**
 * Dialog write-back: declaration, values (renamed ones moved over), the **bindings on custom parameters** of this node (keyed by widget name),
 * and references to them across the graph. Returns {renamed}.
 */
export function applySpare(graph, node, items) {
  const map = new Map();
  for (const it of items)
    if (it.kind === "param" && it.orig && it.orig !== it.name) map.set(it.orig, it.name);
  let oldSpecs = [];
  try { oldSpecs = spareSpecs(node); } catch (_) { /* previously malformed: nothing to move */ }
  const oldNames = widgetNameMap(oldSpecs);
  graph?.beforeChange?.();
  node.properties = node.properties || {};
  // values
  if (map.size) {
    const st = storedVals(node), next = {};
    for (const [k, v] of Object.entries(st)) if (!map.has(k)) next[k] = v;
    for (const [a, b] of map) if (a in st) next[b] = st[a];
    node.properties[SPARE_VALS] = next;
  }
  // Bindings on its own custom parameters (expressions / keyframes / references): keys follow the rename
  const own = bindings(node);
  if (own && map.size) {
    const next = {};
    for (const [wn, ref] of Object.entries(own)) {
      const hit = oldNames.get(wn);
      const to = hit && map.get(hit[0]);
      next[to ? to + hit[1] : wn] = ref;
    }
    node.properties.pcg_bind = next;
  }
  node.properties[SPARE_KEY] = toText(items);
  delete node.properties[SPARE_AUTO];                 // Apply was clicked: all yours now, no more auto-deleting
  let renamed = 0;
  if (map.size)
    for (const n of graph?._nodes ?? []) {
      const b = bindings(n);
      if (!b) continue;
      for (const [w, ref] of Object.entries(b)) {
        const nx = visitSpare(graph, node, n, ref, oldNames, (nm) => map.get(nm) ?? null);
        if (nx !== ref) { b[w] = nx; renamed++; }
      }
    }
  syncSpare(node);
  try { applyBindings(graph); } catch (_) { /* */ }
  graph?.afterChange?.();
  return { renamed };
}

/** target for the dialog (see panelTarget in pcg_paramui.js). */
export function spareTarget(node, graph = app.graph) {
  return {
    title: " · custom parameters",
    text: () => spareText(node),
    usage: () => spareUsage(graph, node),
    apply: (items) => applySpare(graph, node, items),
    check: (items) => {
      const native = nativeNames(node);
      const errs = {};
      items.forEach((it, i) => {
        if (it.kind !== "param") return;
        const n = Array.isArray(it.def) ? it.def.length : 1;
        const ws = n > 1 ? Array.from({ length: n }, (_, k) => it.name + COMP[k]) : [it.name];
        const hit = ws.find((w) => native.has(w));
        if (hit) errs[i] = `'${hit}' is one of the node's own parameter names, pick another`;
      });
      // Component names of a vector (posx) clashing with other scalars
      const all = new Map();
      items.forEach((it, i) => {
        if (it.kind !== "param") return;
        const n = Array.isArray(it.def) ? it.def.length : 1;
        const ws = n > 1 ? Array.from({ length: n }, (_, k) => it.name + COMP[k]) : [it.name];
        for (const w of ws) {
          if (all.has(w) && all.get(w) !== i && errs[i] === undefined)
            errs[i] = `'${w}' clashes with entry ${all.get(w) + 1} (the components of vector pos are called posx posy posz)`;
          all.set(w, i);
        }
      });
      return errs;
    },
    refPath: (it) => {
      const nm = (it.name || "name") + (Array.isArray(it.def) ? "x" : "");
      return `../${titleOf(node)}/${nm}`;
    },
  };
}

export function openSpareDialog(node, graph = node?.graph || app.graph) {
  return openDialog(node, graph, spareTarget(node, graph));
}

// ════════════════════════════════════════════════════ Wrangle's ch()
// ch("x") / chf / chi / chv / chs, optional second argument (numeric default)
const CH_RE = /\b(ch[fivs]?)\s*\(\s*["']([A-Za-z_]\w*)["']\s*(?:,\s*([-+\d.eE]+))?\s*[,)]/g;
const CH_TYPE = { ch: "float", chf: "float", chi: "int", chv: "vector", chs: "string" };

/** ch() calls used in the code: [{name, type, def}] (for duplicate names the first occurrence wins). */
export function scanCh(code) {
  const out = new Map();
  let m;
  CH_RE.lastIndex = 0;
  while ((m = CH_RE.exec(String(code || ""))) !== null) {
    if (out.has(m[2])) continue;
    const type = CH_TYPE[m[1]];
    let def = m[3] !== undefined ? Number(m[3]) : 0;
    if (!Number.isFinite(def)) def = 0;
    out.set(m[2], { name: m[2], type, def });
  }
  return [...out.values()];
}

function declLine(p) {
  if (p.type === "string") return `string ${p.name}`;
  if (p.type === "vector") return `vector ${p.name} = ${p.def} ${p.def} ${p.def}`;
  // Default comes from the code (the 0.5 of ch("amp", 0.5)); values stored by old workflows are picked up separately (see syncFromCode)
  return `${p.type} ${p.name} = ${p.type === "int" ? Math.round(p.def) : p.def}`;
}

/**
 * Nodes with ch_params: ch() newly appearing in the code is added as a custom parameter; auto-added ones that are gone from the code, still at the default
 * and not bound are deleted (see file header). Values stored in ch_params by old workflows (before pcg104) are picked up here.
 * Returns whether the declaration changed.
 */
export function syncFromCode(node) {
  const store = widgetOf(node, "ch_params");
  if (!store) return false;
  const code = widgetOf(node, "code")?.value ?? "";
  const want = scanCh(code);
  let items = parseItems(spareText(node));
  const have = new Set(items.filter((x) => x.kind === "param").map((x) => x.name));
  // Vector component names (ch("posx")) count as existing
  for (const it of items)
    if (it.kind === "param" && Array.isArray(it.def))
      it.def.forEach((_, k) => have.add(it.name + COMP[k]));
  let legacy = {};
  try { legacy = JSON.parse(store.value || "{}") || {}; } catch (_) { legacy = {}; }
  const native = nativeNames(node);
  const auto = new Set(node.properties?.[SPARE_AUTO] || []);
  let changed = false;
  for (const p of want) {
    if (have.has(p.name) || native.has(p.name)) continue;
    const line = declLine(p);
    items.push(...parseItems(line));
    if (legacy[p.name] !== undefined) {
      node.properties = node.properties || {};
      node.properties[SPARE_VALS] = { ...storedVals(node), [p.name]: legacy[p.name] };
    }
    auto.add(p.name);
    have.add(p.name);
    changed = true;
  }
  // Auto-added and already gone from the code: if still at default and not bound, delete
  const used = new Set(want.map((p) => p.name));
  const vals = spareValues(node);
  const b = bindings(node) || {};
  let specs = [];
  try { specs = spareSpecs(node); } catch (_) { /* */ }
  for (const name of [...auto]) {
    if (used.has(name)) continue;
    const s = specs.find((x) => x.name === name);
    const atDefault = !s || JSON.stringify(vals[name]) === JSON.stringify(s.default);
    const bound = s && compNames(s).some((c) => c in b);
    if (!atDefault || bound) { auto.delete(name); continue; }     // changed: yours to manage
    const before = items.length;
    items = items.filter((x) => !(x.kind === "param" && x.name === name));
    if (items.length !== before) changed = true;
    auto.delete(name);
  }
  node.properties = node.properties || {};
  if (auto.size) node.properties[SPARE_AUTO] = [...auto];
  else delete node.properties[SPARE_AUTO];
  if (changed) node.properties[SPARE_KEY] = toText(items);
  return changed;
}

/** Custom parameters not used in the code (for the context-menu "clean up"). */
export function unusedInCode(node) {
  const used = new Set(scanCh(widgetOf(node, "code")?.value ?? "").map((p) => p.name));
  let specs = [];
  try { specs = spareSpecs(node); } catch (_) { return []; }
  return specs.filter((s) => !compNames(s).some((c) => used.has(c)) && !used.has(s.name))
    .map((s) => s.name);
}

export function removeSpare(node, names) {
  const drop = new Set(names);
  const items = parseItems(spareText(node)).filter((x) => !(x.kind === "param" && drop.has(x.name)));
  node.properties[SPARE_KEY] = toText(items);
  return syncSpare(node);
}

// ════════════════════════════════════════════════════ hooking into all nodes
function hookCode(node) {
  const codeW = widgetOf(node, "code");
  if (!codeW || !widgetOf(node, "ch_params") || node._pcgSpareHooked) return;
  node._pcgSpareHooked = true;
  const store = widgetOf(node, "ch_params");
  // This widget is only a courier; it shouldn't take panel space
  store.type = "pcg-hidden";
  store.computeSize = () => [0, -4];
  store.hidden = true;
  let t = null;
  const later = () => {                  // while typing, coalesce over 250ms; don't rebuild widgets on every key
    clearTimeout(t);
    t = setTimeout(() => { if (syncFromCode(node)) syncSpare(node); }, 250);
  };
  const cb = codeW.callback;
  codeW.callback = function (...a) { const r = cb?.apply(this, a); later(); return r; };
  setTimeout(() => {
    const el = codeW.inputEl || codeW.element?.querySelector?.("textarea");
    if (el) el.addEventListener("input", later);
  }, 0);
}

app.registerExtension({
  name: "pcg.spare",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (SKIP_TYPES.has(nodeData?.name)) return;
    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onCreated?.apply(this, arguments);
      hookCode(this);
      if (syncFromCode(this) || spareText(this)) syncSpare(this);
      return r;
    };
    // Loading a workflow / pasting: properties only exist now, so widgets grow here (native widget values have already been applied by index)
    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const r = onConfigure?.apply(this, arguments);
      hookCode(this);
      syncFromCode(this);
      syncSpare(this);
      return r;
    };
    const menu = nodeType.prototype.getExtraMenuOptions;
    nodeType.prototype.getExtraMenuOptions = function (canvas, options) {
      const r = menu?.apply(this, arguments);
      try {
        const extra = [{ content: "PCG: Edit Parameter Interface…",
                         callback: () => openSpareDialog(this) }];
        if (widgetOf(this, "ch_params")) {
          const un = unusedInCode(this);
          extra.push({ content: `PCG: Delete ch() parameters not used in the code${un.length ? ` (${un.join(", ")})` : ""}`,
                       disabled: !un.length, callback: () => removeSpare(this, un) });
        }
        if (Array.isArray(options)) options.unshift(...extra, null);
      } catch (e) { /* failing to add menu items must not stop the context menu from opening */ }
      return r;
    };
  },
});
