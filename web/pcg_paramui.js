// comfyui_pcg/web/pcg_paramui.js
//
// The "Edit Parameter Interface" dialog -- Houdini's Edit Parameter Interface, for Parameters (PCG).
//
// In Houdini a null is used as a controller: gear → Edit Parameter Interface, pick a type on the left and drag it into the middle list,
// fill in name / label / range / default on the right, Accept. This is the same three columns:
//
//     Create Parameters   |   Existing Parameters   |   Parameter Description
//     (click to add one)   |   (click to select, drag to reorder) |   (Name / Label / Type / Default / Range)
//
// ━━ The dialog is not a separate store, it is just **an editor for the declaration text**
// The panel's parameters have always been a piece of declaration text (`float radius = 1 : 0 10  # radius`; see the pcg_params.js file header for why:
// widgets can only be appended, not inserted). When the dialog opens, the text is split into entries; when done they are joined back into text and written into declare --
// everything after that (growing controls, storing values, references) is the existing machinery. So hand-written text and the dialog can be mixed,
// and comment lines, blank lines, even malformed lines are kept verbatim (the gray ones in the list).
//
// ━━ One thing beyond Houdini: **renaming does not break references**
// In Houdini, renaming a spare parameter breaks ch("../null1/old") elsewhere. Here each entry remembers its name at open time
// (orig); on apply, old names pointing at this panel in the whole graph's binding tables are replaced with the new names (name references, ch("@id/oldname"),
// and those inside string templates), and stored values are moved along. Deleted parameters are not handled for you -- the list shows how many places reference them.
import { app } from "../../scripts/app.js";
import { parse, syncPanel, panels, valuesOf, bindings, splitRef, applyBindings,
         isNumExpr, isTmpl } from "./pcg_params.js";
import { mapChPaths, mapTemplatePaths } from "./pcg_hexpr.js";

const NODE_TYPE = "PCG_Parameters";
export const TYPES = [
  ["float", "Float"], ["int", "Integer"], ["bool", "Toggle"], ["string", "String"],
  ["vector", "Float Vector 3"], ["vector4", "Float Vector 4"],
];
const NCOMP = { float: 1, int: 1, bool: 1, string: 1, vector: 3, vector4: 4 };
const NUMERIC = (t) => t !== "bool" && t !== "string";
const TRUE = new Set(["1", "true", "yes", "on", "t"]);
const numStr = (x) => String(Number.isFinite(Number(x)) ? Number(x) : 0);

// ════════════════════════════════════════════════════ Model: text <-> entries
//
// A parameter entry: {kind:"param", type, name, label, def, range, min, max, orig}
//   def    for float / int / string it is a **string** (text being typed must be storable too), bool is a boolean, vectors are string arrays
//   orig   the name when the dialog was opened (new entries have none) -- used to find old references on rename
// Other lines: {kind:"raw", text, error?} (comments, blank lines, unparseable lines, kept verbatim)

/** declaration text -> entries. Parsed line by line: one malformed line does not affect the others. */
export function parseItems(text) {
  const lines = String(text || "").split(/\r\n|\r|\n/);
  while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
  return lines.map((raw) => {
    const line = raw.trim();
    if (!line || line.startsWith("#") || line.startsWith("//")) return { kind: "raw", text: line };
    let s;
    try { s = parse(line)[0]; } catch (e) { return { kind: "raw", text: line, error: lineErr(e) }; }
    return {
      kind: "param", type: s.type, name: s.name, label: s.label, orig: s.name,
      def: s.n > 1 ? s.default.map(numStr) : (s.type === "bool" ? s.default
        : (s.type === "string" ? s.default : numStr(s.default))),
      range: s.min !== null, min: s.min === null ? "0" : numStr(s.min),
      max: s.max === null ? "1" : numStr(s.max),
    };
  });
}

const lineErr = (e) => String(e?.message || e).replace(/^line 1:\s*/, "");

/**
 * Writing a string default into the declaration: it must be quoted when it contains # or :, has leading/trailing spaces, or starts with a quote (otherwise it would be taken as label / range).
 * When it contains both kinds of quotes and cannot be quoted, returns null.
 */
export function quoteDefault(v) {
  const s = String(v);
  if (!/[#:]/.test(s) && s === s.trim() && !/^["']/.test(s)) return s;
  if (!s.includes('"')) return `"${s}"`;
  if (!s.includes("'")) return `'${s}'`;
  return null;
}

/** entry -> one declaration line. */
export function formatItem(it) {
  if (it.kind !== "param") return it.text;
  let s = `${it.type} ${it.name}`;
  if (it.type === "bool") s += ` = ${!!it.def}`;
  else if (it.type === "string") { if (it.def !== "") s += ` = ${quoteDefault(it.def) ?? it.def}`; }
  else if (NCOMP[it.type] > 1) s += ` = ${it.def.map((x) => String(x).trim() || "0").join(" ")}`;
  else s += ` = ${String(it.def).trim() || "0"}`;
  if (it.range)                       // only numeric types can have range true (retype turns it off when switching to toggle / string)
    s += ` : ${String(it.min).trim() || "0"} ${String(it.max).trim() || "0"}`;
  if (String(it.label).trim()) s += `  # ${String(it.label).trim()}`;
  return s;
}

export function toText(items) {
  return items.length ? items.map(formatItem).join("\n") + "\n" : "";
}

/**
 * Problems of each entry: {index: reason}. No separate set of rules -- each entry is joined into a line and handed to **the real parser**
 * (the one checked against the same golden table as the backend params.py); if it accepts, fine. Then check duplicates and whether string defaults can be quoted.
 */
export function validate(items) {
  const errs = {};
  const seen = new Map();
  items.forEach((it, i) => {
    if (it.kind !== "param") { if (it.error) errs[i] = it.error; return; }
    if (/[\r\n]/.test(`${it.def}${it.label}`)) { errs[i] = "default / label cannot contain line breaks"; return; }
    if (it.type === "string" && quoteDefault(it.def) === null) {
      errs[i] = "this default cannot be written into the declaration (it has both kinds of quotes, plus # , : or leading/trailing spaces). Remove one kind of quote";
      return;
    }
    try { parse(formatItem(it)); } catch (e) { errs[i] = lineErr(e); return; }
    if (seen.has(it.name)) errs[i] = `parameter name '${it.name}' duplicates entry ${seen.get(it.name) + 1}`;
    else seen.set(it.name, i);
  });
  return errs;
}

/** Add an entry: named newparameter, newparameter2 … (Houdini's naming). */
export function newItem(type, items) {
  const used = new Set(items.filter((x) => x.kind === "param").map((x) => x.name));
  let name = "newparameter";
  for (let i = 2; used.has(name); i++) name = `newparameter${i}`;
  const n = NCOMP[type];
  return { kind: "param", type, name, label: "",
           def: n > 1 ? new Array(n).fill("0") : (type === "bool" ? false : (type === "string" ? "" : "0")),
           range: false, min: "0", max: type === "int" ? "10" : "1" };
}

/** Change type: carry the default over where possible (number ↔ vector ↔ toggle ↔ string); only numeric types keep the range. */
export function retype(it, type) {
  const from = it.type;
  if (from === type) return it;
  const first = Array.isArray(it.def) ? it.def[0]
    : (from === "bool" ? (it.def ? "1" : "0") : String(it.def));
  const asNum = Number.isFinite(Number(first)) ? Number(first) : 0;      // Number("") is 0 anyway
  const n = NCOMP[type];
  let def;
  if (type === "bool") def = from === "string" ? TRUE.has(String(it.def).trim().toLowerCase()) : asNum !== 0;
  else if (type === "string")
    def = Array.isArray(it.def) ? it.def.join(" ") : (from === "bool" ? (it.def ? "true" : "false") : String(it.def));
  else if (n > 1)
    def = Array.isArray(it.def) ? Array.from({ length: n }, (_, i) => it.def[i] ?? "0")
      : new Array(n).fill(numStr(asNum));
  else def = numStr(type === "int" ? Math.round(asNum) : asNum);
  it.type = type;
  it.def = def;
  if (!NUMERIC(type)) it.range = false;
  return it;
}

/** Renamed ones: Map(old name -> new name). */
export function renameMap(items) {
  const m = new Map();
  for (const it of items)
    if (it.kind === "param" && it.orig && it.orig !== it.name) m.set(it.orig, it.name);
  return m;
}

// ════════════════════════════════════════════════════ References: who uses it, follow renames
const titleOf = (n) => n?.title || n?.type || "";

/** parameter name -> which panel a by-name reference lands on (duplicates across panels take the earliest, same as allValues). */
function owners(graph) {
  const m = new Map();
  for (const p of panels(graph))
    for (const k of Object.keys(valuesOf(p))) if (!m.has(k)) m.set(k, p);
  return m;
}

/**
 * Walk the parameter names in one binding that **point at this panel**; fn(name) returns a new name to replace it, or null to leave it. Returns the new binding string.
 * Three spellings: name references ("radius" / "pos.y"), ch("@id/radius") in expressions / templates (what is stored)
 * or ch("../title/radius") (not canonicalized, only accepted when the title is unique).
 */
export function visitRef(graph, panel, ref, own, fn) {
  if (typeof ref !== "string") return ref;
  const inPath = (path) => {
    const m = /^(@(-?\d+)|\.\.\/#(-?\d+)|\.\.\/([^/]+))\/([A-Za-z_]\w*)(.*)$/.exec(String(path));
    if (!m) return null;
    const id = m[2] ?? m[3];
    if (id !== undefined) { if (String(id) !== String(panel.id)) return null; }
    else {
      const hits = (graph?._nodes ?? []).filter((n) => titleOf(n) === m[4]);
      if (hits.length !== 1 || hits[0] !== panel) return null;
    }
    const to = fn(m[5]);
    return to == null ? null : `${m[1]}/${to}${m[6]}`;
  };
  if (isNumExpr(ref)) return ref[0] + mapChPaths(ref.slice(1), inPath);
  if (isTmpl(ref)) return ref[0] + mapTemplatePaths(ref.slice(1), inPath);
  // What remains: name references, or node-to-node "@id/w" and keyframes "k:..." -- the "names" split out of the latter two are not parameters
  // of any panel (they contain @ / colons), so own.get below simply misses; no need to exclude them separately
  let name;
  try { name = splitRef(ref).name; } catch (_) { return ref; }
  if (own.get(name) !== panel) return ref;
  const to = fn(name);
  return to == null ? ref : to + ref.trim().slice(name.length);
}

/** How many places reference each parameter of this panel: Map(name -> count). */
export function usage(graph, panel) {
  const own = owners(graph);
  const out = new Map();
  for (const n of graph?._nodes ?? [])
    for (const ref of Object.values(bindings(n) || {}))
      visitRef(graph, panel, ref, own, (name) => { out.set(name, (out.get(name) || 0) + 1); return null; });
  return out;
}

/**
 * Write the edited entries back to the panel: declaration text, stored values (renamed ones moved over), references across the graph (renamed ones replaced).
 * Returns {renamed: number of references replaced}.
 */
export function applyItems(graph, panel, items) {
  const map = renameMap(items);
  const own = owners(graph);                       // computed before changing the declaration: afterwards the old names have no owner
  const decl = panel.widgets?.find((w) => w.name === "declare");
  const vals = panel.widgets?.find((w) => w.name === "values");
  if (!decl) return { renamed: 0 };
  graph?.beforeChange?.();
  if (map.size && vals) {
    let st = {};
    try { st = JSON.parse(vals.value || "{}") || {}; } catch (_) { st = {}; }
    const next = {};
    for (const [k, v] of Object.entries(st)) if (!map.has(k)) next[k] = v;
    for (const [a, b] of map) if (a in st) next[b] = st[a];     // moved together: an a↔b swap also works
    vals.value = JSON.stringify(next);
  }
  decl.value = toText(items);
  try { decl.callback?.(decl.value); } catch (_) { /* errors in callbacks hooked by other extensions should not block this */ }
  syncPanel(panel);
  let renamed = 0;
  if (map.size)
    for (const n of graph?._nodes ?? []) {
      const b = bindings(n);
      if (!b) continue;
      for (const [w, ref] of Object.entries(b)) {
        const next = visitRef(graph, panel, ref, own, (name) => map.get(name) ?? null);
        if (next !== ref) { b[w] = next; renamed++; }
      }
    }
  for (const it of items) if (it.kind === "param") it.orig = it.name;   // keep editing after "Apply": count from the new names
  try { applyBindings(graph); } catch (_) { /* */ }
  graph?.afterChange?.();
  panel.setDirtyCanvas?.(true, true);
  return { renamed };
}

// ════════════════════════════════════════════════════ Dialog
const CSS = `
.pcg-epi-mask{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:10000;display:flex;
  align-items:center;justify-content:center;font:12px/1.4 system-ui,"Segoe UI",sans-serif}
.pcg-epi{background:#3a3a3a;color:#ddd;border:1px solid #111;box-shadow:0 12px 40px rgba(0,0,0,.6);
  width:min(900px,94vw);height:min(560px,88vh);display:flex;flex-direction:column;border-radius:3px}
.pcg-epi .ttl{background:#2a2a2a;padding:7px 10px;font-weight:600;border-bottom:1px solid #111;
  display:flex;justify-content:space-between}
.pcg-epi .ttl span{color:#888;font-weight:400}
.pcg-epi .cols{flex:1;display:grid;grid-template-columns:170px 1fr 300px;gap:1px;background:#111;min-height:0}
.pcg-epi .col{background:#3a3a3a;display:flex;flex-direction:column;min-height:0}
.pcg-epi .hd{background:#454545;padding:5px 8px;color:#eee;border-bottom:1px solid #222}
.pcg-epi .list{flex:1;overflow:auto;padding:3px 0}
.pcg-epi .it{padding:3px 8px;cursor:pointer;display:flex;gap:6px;align-items:center;white-space:nowrap;
  border-top:2px solid transparent}
.pcg-epi .it:hover{background:#474747}
.pcg-epi .it.sel{background:#b06a16;color:#fff}
.pcg-epi .it.raw{color:#888;font-style:italic}
.pcg-epi .it.bad{color:#ff8f80}
.pcg-epi .it.over{border-top-color:#f2a33a}
.pcg-epi .it .nm{color:#9a9a9a}
.pcg-epi .it.sel .nm{color:#ffe1bd}
.pcg-epi .it .ty{margin-left:auto;color:#8fb5d8;font-size:11px}
.pcg-epi .it.sel .ty{color:#fff}
.pcg-epi .it .use{color:#7fd6c8;font-size:11px}
.pcg-epi .tools{display:flex;gap:4px;padding:5px 6px;border-top:1px solid #222}
.pcg-epi button{background:#555;color:#eee;border:1px solid #222;border-radius:2px;padding:3px 10px;cursor:pointer;font:inherit}
.pcg-epi button:hover:not(:disabled){background:#666}
.pcg-epi button:disabled{opacity:.45;cursor:default}
.pcg-epi .desc{padding:8px 10px;overflow:auto;flex:1}
.pcg-epi .f{display:grid;grid-template-columns:70px 1fr;gap:6px;align-items:center;margin-bottom:7px}
.pcg-epi .f label{color:#bbb;text-align:right}
.pcg-epi .f .v{display:flex;gap:4px;align-items:center;min-width:0}
.pcg-epi input[type=text],.pcg-epi select{background:#222;color:#eee;border:1px solid #111;border-radius:2px;
  padding:3px 5px;font:inherit;min-width:0;flex:1;width:100%;box-sizing:border-box}
.pcg-epi input.bad{border-color:#d0553f}
.pcg-epi .hint{color:#8a8a8a;padding:8px 10px}
.pcg-epi .ft{display:flex;gap:6px;align-items:center;padding:7px 10px;border-top:1px solid #111;background:#333}
.pcg-epi .ft .msg{flex:1;color:#ff8f80;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pcg-epi .ft .msg.ok{color:#8a8a8a}
`;

function el(tag, cls, parent, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  parent?.appendChild(e);
  return e;
}

let OPEN = null;                       // only one open at a time

/**
 * Whose declaration the dialog edits. The default is the declare of Parameters (PCG); spare parameters on any node
 * (pcg104, pcg_spare.js) provide another one: the declaration lives in properties, references go through "@id/param".
 *   text()          current declaration text
 *   usage()         Map(parameter name -> number of references)
 *   apply(items)    write back, returns {renamed}
 *   check(items)    extra validation {index: reason} (e.g. clashing with the node's own parameters)
 *   refPath(it)     the path written in the "how to reference it" hint
 */
export function panelTarget(node, graph = app.graph) {
  return {
    title: "",
    text: () => node.widgets?.find((w) => w.name === "declare")?.value || "",
    usage: () => usage(graph, node),
    apply: (items) => applyItems(graph, node, items),
    check: () => ({}),
    refPath: (it) => `../${titleOf(node)}/${it.name || "name"}${Array.isArray(it.def) ? ".x" : ""}`,
  };
}

export class ParamDialog {
  constructor(node, graph = app.graph, target = null) {
    this.node = node;
    this.graph = graph;
    this.target = target || panelTarget(node, graph);
    this.items = parseItems(this.target.text());
    this.sel = this.items.findIndex((x) => x.kind === "param");
    this.use = this.target.usage();
    this.build();
  }

  validate() {
    return { ...this.target.check(this.items), ...validate(this.items) };
  }

  build() {
    if (!document.getElementById("pcg-epi-css")) {
      const st = el("style", "", document.head);
      st.id = "pcg-epi-css";
      st.textContent = CSS;
    }
    const mask = this.mask = el("div", "pcg-epi-mask", document.body);
    const box = el("div", "pcg-epi", mask);
    const ttl = el("div", "ttl", box);
    el("div", "", ttl, `Edit Parameter Interface — ${titleOf(this.node)}${this.target.title || ""}`);
    el("span", "", ttl, "Click Accept when done; renaming updates references elsewhere");
    const cols = el("div", "cols", box);

    const c1 = el("div", "col", cols);
    el("div", "hd", c1, "Create Parameters");
    const tl = el("div", "list", c1);
    for (const [t, label] of TYPES) {
      const r = el("div", "it", tl);
      r.dataset.type = t;
      el("span", "", r, label);
      el("span", "ty", r, "+");
      r.title = "Click: add after the selected entry";
      r.onclick = () => this.add(t);
    }

    const c2 = el("div", "col", cols);
    el("div", "hd", c2, "Existing Parameters");
    this.listEl = el("div", "list", c2);
    const tools = el("div", "tools", c2);
    const mk = (text, title, fn) => { const b = el("button", "", tools, text); b.title = title; b.onclick = fn; return b; };
    this.btnUp = mk("↑", "Move up", () => this.move(-1));
    this.btnDown = mk("↓", "Move down", () => this.move(1));
    this.btnDup = mk("Duplicate", "Duplicate (name gets a number)", () => this.duplicate());
    this.btnDel = mk("✕", "Delete (Delete)", () => this.remove());

    const c3 = el("div", "col", cols);
    el("div", "hd", c3, "Parameter Description");
    this.descEl = el("div", "desc", c3);

    const ft = el("div", "ft", box);
    this.msgEl = el("div", "msg", ft);
    this.btnApply = el("button", "", ft, "Apply");
    this.btnAccept = el("button", "", ft, "Accept");
    this.btnCancel = el("button", "", ft, "Cancel");
    this.btnApply.onclick = () => this.apply();
    this.btnAccept.onclick = () => { if (this.apply()) this.close(); };
    this.btnCancel.onclick = () => this.close();
    // Don't let key presses leak to the canvas (Delete would delete the node); Esc = cancel
    this.onKey = (e) => {
      e.stopPropagation();
      if (e.key === "Escape") this.close();
      else if (e.key === "Delete" && !/^(INPUT|SELECT|TEXTAREA)$/.test(e.target?.tagName || "")) this.remove();
    };
    mask.addEventListener("keydown", this.onKey);
    for (const t of ["pointerdown", "mousedown", "wheel", "dblclick", "contextmenu"])
      mask.addEventListener(t, (e) => e.stopPropagation());
    mask.tabIndex = -1;
    this.renderList();
    this.renderDesc();
    mask.focus?.();
  }

  // ── List ──────────────────────────────────────────────────────
  renderList() {
    const errs = this.errs = this.validate();
    this.listEl.textContent = "";
    this.items.forEach((it, i) => {
      const r = el("div", "it", this.listEl);
      r.dataset.i = i;
      if (i === this.sel) r.classList.add("sel");
      if (errs[i]) { r.classList.add("bad"); r.title = errs[i]; }
      if (it.kind !== "param") {
        r.classList.add("raw");
        el("span", "", r, it.text || "(blank line)");
      } else {
        el("span", "", r, String(it.label).trim() || it.name);
        el("span", "nm", r, `(${it.name})`);
        const n = it.orig ? this.use.get(it.orig) || 0 : 0;
        if (n) { const u = el("span", "use", r, `← ${n}`); u.title = `referenced by ${n} parameters`; }
        el("span", "ty", r, TYPES.find((x) => x[0] === it.type)[1]);
      }
      r.onclick = () => this.select(i);
      r.draggable = true;
      r.ondragstart = (e) => { this.dragFrom = i; e.dataTransfer?.setData?.("text/plain", String(i)); };
      r.ondragover = (e) => { e.preventDefault(); r.classList.add("over"); };
      r.ondragleave = () => r.classList.remove("over");
      r.ondrop = (e) => { e.preventDefault(); this.reorder(this.dragFrom, i); };
    });
    const has = this.sel >= 0 && this.sel < this.items.length;
    this.btnUp.disabled = !has || this.sel === 0;
    this.btnDown.disabled = !has || this.sel === this.items.length - 1;
    this.btnDel.disabled = !has;
    this.btnDup.disabled = !has || this.items[this.sel].kind !== "param";
    const first = Object.keys(errs).map(Number).sort((a, b) => a - b)[0];
    const bad = first !== undefined;
    this.msgEl.textContent = bad ? `entry ${first + 1}: ${errs[first]}`
      : `${this.items.filter((x) => x.kind === "param").length} parameters`;
    this.msgEl.classList.toggle("ok", !bad);
    this.btnApply.disabled = this.btnAccept.disabled = bad;
  }

  select(i) { this.sel = i; this.renderList(); this.renderDesc(); }

  add(type) {
    const at = this.sel >= 0 ? this.sel + 1 : this.items.length;
    this.items.splice(at, 0, newItem(type, this.items));
    this.select(at);
    const nm = this.descEl.querySelector("input");      // name field selected: typing right after adding renames it
    nm?.focus?.();
    nm?.select?.();
  }

  remove() {
    if (this.sel < 0 || this.sel >= this.items.length) return;
    this.items.splice(this.sel, 1);
    this.select(Math.min(this.sel, this.items.length - 1));
  }

  duplicate() {
    const it = this.items[this.sel];
    if (!it || it.kind !== "param") return;
    const copy = { ...it, def: Array.isArray(it.def) ? it.def.slice() : it.def, orig: undefined };
    const used = new Set(this.items.filter((x) => x.kind === "param").map((x) => x.name));
    const base = it.name.replace(/\d+$/, "") || it.name;
    let k = 2;
    while (used.has(`${base}${k}`)) k++;
    copy.name = `${base}${k}`;
    this.items.splice(this.sel + 1, 0, copy);
    this.select(this.sel + 1);
  }

  move(d) { this.reorder(this.sel, this.sel + d, true); }

  /** Move the entry at from to position to (drag: insert before the one dropped on; buttons: swap with the neighbour). */
  reorder(from, to, swap = false) {
    const n = this.items.length;
    if (!(from >= 0 && from < n && to >= 0 && to < n)) return;
    const [it] = this.items.splice(from, 1);
    const at = swap ? to : (from < to ? to - 1 : to);
    this.items.splice(at, 0, it);
    this.select(at);
  }

  // ── Right column ──────────────────────────────────────────────────────
  field(label) {
    const f = el("div", "f", this.descEl);
    el("label", "", f, label);
    return el("div", "v", f);
  }

  text(parent, value, set, key) {
    const inp = el("input", "", parent);
    inp.type = "text";
    inp.value = value;
    if (key) inp.dataset.k = key;
    inp.spellcheck = false;
    // Takes effect while typing (the list row and the error hint below follow); the right column is not redrawn, so focus is not lost
    inp.oninput = () => { set(inp.value); this.renderList(); this.mark(); };
    return inp;
  }

  /**
   * The entry with a problem: the right column's input gets a red outline; the hint below is updated.
   * (when a comment line is selected, hintEl is still the one left over by the previous parameter entry and no longer on the page; writing to it has no effect, no special case needed)
   */
  mark() {
    if (this.hintEl) this.hintEl.textContent = this.hintText(this.items[this.sel]);
    const bad = !!this.errs?.[this.sel];
    for (const i of this.descEl.querySelectorAll("input[type=text]")) i.classList.toggle("bad", bad);
  }

  renderDesc() {
    const d = this.descEl;
    d.textContent = "";
    const it = this.items[this.sel];
    if (!it) { el("div", "hint", d, "Click a type on the left to add the first parameter"); return; }
    if (it.kind !== "param") {
      this.text(this.field("Text"), it.text, (v) => { it.text = v; delete it.error;
        const again = parseItems(v)[0];
        if (again && again.kind === "param") Object.assign(it, again, { orig: undefined });
        else if (again?.error) it.error = again.error; }, "text");
      el("div", "hint", d, it.error ? "This line cannot be parsed; once fixed it becomes a parameter"
        : "Comment / blank line: kept verbatim in the declaration, not shown on the panel");
      this.mark();
      return;
    }
    this.text(this.field("Name"), it.name, (v) => { it.name = v.trim(); }, "name");
    this.text(this.field("Label"), it.label, (v) => { it.label = v; }, "label");
    const ts = el("select", "", this.field("Type"));
    ts.dataset.k = "type";
    for (const [t, label] of TYPES) { const o = el("option", "", ts, label); o.value = t; }
    ts.value = it.type;
    ts.onchange = () => { retype(it, ts.value); this.renderList(); this.renderDesc(); };

    const dv = this.field("Default");
    if (it.type === "bool") {
      const cb = el("input", "", dv);
      cb.type = "checkbox";
      cb.dataset.k = "def";
      cb.checked = !!it.def;
      cb.onchange = () => { it.def = cb.checked; this.renderList(); };
    } else if (Array.isArray(it.def)) {
      it.def.forEach((x, i) => this.text(dv, x, (v) => { it.def[i] = v; }, `def${i}`));
    } else this.text(dv, it.def, (v) => { it.def = v; }, "def");

    if (NUMERIC(it.type)) {
      const rv = this.field("Range");
      const cb = el("input", "", rv);
      cb.type = "checkbox";
      cb.dataset.k = "range";
      cb.checked = !!it.range;
      cb.title = "Checked: the panel shows a slider, and the value is clamped to this range";
      const lo = this.text(rv, it.min, (v) => { it.min = v; }, "min");
      const hi = this.text(rv, it.max, (v) => { it.max = v; }, "max");
      lo.disabled = hi.disabled = !it.range;
      cb.onchange = () => { it.range = cb.checked; lo.disabled = hi.disabled = !it.range; this.renderList(); this.mark(); };
    }
    this.hintEl = el("div", "hint", d);
    this.mark();
  }

  /** The line at the bottom of the right column: how many references; if none, how to reference it (the name follows what is being typed, vectors with a component). */
  hintText(it) {
    const n = it.orig ? this.use.get(it.orig) || 0 : 0;
    if (n) return `Referenced by ${n} parameters. Rename: references follow; delete: those references break (fields get a question mark, values kept)`;
    const path = this.target.refPath(it);
    return `To reference it: type ${it.type === "string" ? "chs" : "ch"}("${path}") into a parameter field on another node, or right-click this panel → Copy Parameter Reference`;
  }

  // ── Write back ──────────────────────────────────────────────────────
  apply() {
    if (Object.keys(this.validate()).length) return false;
    const r = this.target.apply(this.items);
    for (const it of this.items) if (it.kind === "param") it.orig = it.name;
    this.use = this.target.usage();
    this.renderList();
    if (r.renamed) { this.msgEl.textContent += `; renaming updated ${r.renamed} references`; }
    return true;
  }

  close() {
    this.mask.remove();
    if (OPEN === this) OPEN = null;
  }
}

export function openDialog(node, graph = app.graph, target = null) {
  OPEN?.close();
  OPEN = new ParamDialog(node, graph, target);
  return OPEN;
}

app.registerExtension({
  name: "pcg.paramui",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== NODE_TYPE) return;
    // A button on the node (in Houdini it is the gear at the top right of the parameter panel). Appended last, not serialized: takes no widgets_values index
    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onCreated?.apply(this, arguments);
      const node = this;
      const b = this.addWidget?.("button", "pcg_edit_ui", null, () => openDialog(node, node.graph || app.graph),
                                 { serialize: false });
      if (b) { b.label = "⚙ Edit Parameter Interface…"; b.serialize = false; }
    };
    const menu = nodeType.prototype.getExtraMenuOptions;
    nodeType.prototype.getExtraMenuOptions = function (canvas, options) {
      options.unshift({ content: "PCG: Edit Parameter Interface…",
                        callback: () => openDialog(this, this.graph || app.graph) }, null);
      return menu?.apply(this, arguments);
    };
  },
});
