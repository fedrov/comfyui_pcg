// comfyui_pcg/web/pcg_params.js
//
// Parameter panel + parameter references -- the equivalent of adding a bunch of spare parameters to a Houdini null,
// then hooking them up to parameters elsewhere with copy / paste relative reference.
//
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Two parts, each with an unavoidable constraint
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// **Panel**: widgets can only be **appended to the end of the array**, never inserted or reordered -- when litegraph restores
// a workflow it maps widgets_values back onto the widget array by index; inserting one shifts every parameter after it,
// without any error, and values silently get mixed up. So the parameters are a piece of **declaration text**; the frontend
// appends `serialize:false` widgets from it, and all values are serialized into the fixed `values` string.
// This whole setup was moved over from the ch() parameters in `pcg_wrangle.js`, which shipped in two batches.
//
// **References**: ComfyUI's cache is keyed on an input hash; without an edge in the graph it cannot see the dependency. So a binding is not
// "read at runtime"; instead, whenever the panel changes, **the value is written straight into the target widget**. Once written, the hash of the
// submitted prompt is naturally correct, and invalidation is fine-grained -- changing radius recooks only the nodes that reference it.
// Wires cannot do this: every consuming node hangs off the same upstream, so touching one parameter invalidates all of them.
//
// Writing values into other nodes' widgets has already shipped in two batches in this plugin (the playbar writes Frame,
// the 3D panel's lock writes Camera), so the mechanism is proven.
//
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Bindings live in node.properties, **not in widgets_values and not in the API prompt**
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// litegraph saves properties into the workflow (so bindings travel with the project), but the prompt submitted
// to the backend has only widget values and links -- the backend knows nothing about "references"; all it sees
// is an ordinary number. That is exactly what we want: **what you see is what runs**.
//
// The cost, stated plainly: bindings are a frontend thing. Running the same workflow via API / headless does not
// re-evaluate them; it uses the values last materialized into widgets_values.

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { parse as parseExpr, evaluate as evalExprAst, mapChPaths, ExprError, ExprPending,
         fmtStr, expandTemplate, mapTemplatePaths } from "./pcg_hexpr.js";
import { parseKeys, formatKeys, evalKeys } from "./pcg_chan.js";

const NODE_TYPE = "PCG_Parameters";
const FROM_JSON = "PCG_ParamsFromJSON";
const PREFIX = "p_";              // name prefix of parameter widgets, avoids clashing with declare/values
export const BIND_KEY = "pcg_bind";
const TICK_MS = 400;
const C_BOUND = "#7fb8ff";

// ════════════════════════════════════════════════════ Parsing the declaration text
//
// **This must give the same results as parse() in params.py.** Two implementations drift, so
// the tests compare both against the same golden table (params_golden.json) -- change either side
// and that side's test goes red.
const ALIAS = {
  f: "float", float: "float",
  i: "int", int: "int",
  b: "bool", bool: "bool", toggle: "bool",
  s: "string", str: "string", string: "string",
  v: "vector", vec: "vector", vector: "vector", vector3: "vector",
  v3: "vector", vec3: "vector",
  v4: "vector4", vec4: "vector4", vector4: "vector4",
};
const NCOMP = { float: 1, int: 1, bool: 1, string: 1, vector: 3, vector4: 4 };
const TRUE = new Set(["1", "true", "yes", "on", "t"]);
const FALSE = new Set(["0", "false", "no", "off", "f"]);
export const COMPONENTS = { x: 0, y: 1, z: 2, w: 3, r: 0, g: 1, b: 2, a: 3,
                            0: 0, 1: 1, 2: 2, 3: 3 };

function num(tok, line, what) {
  const v = Number(tok);
  if (!Number.isFinite(v))
    throw new Error(`line ${line}: ${what} '${tok}' is not a number`);
  return v;
}

function ident(name, line) {
  if (!/^[A-Za-z_]\w*$/.test(name || ""))
    throw new Error(`line ${line}: parameter name '${name}' is invalid -- `
                    + "only letters, digits and underscores are allowed, and it cannot start with a digit");
  return name;
}

/**
 * Position [start, end) of the quoted default value in this line -- # and : inside it are not separators
 * (`string dir = "C:/out#1"`). Only counts when "the first = is directly followed by a quote, and the quote has a match";
 * other spellings (no quotes, unmatched quotes) behave exactly as before; when # or : comes before =, the first # / : is outside
 * this span anyway and is still found first. **Matches _quoted_span in params.py.**
 */
function quotedSpan(line) {
  const e = line.indexOf("=");
  if (e < 0) return null;
  let i = e + 1;
  while (i < line.length && /\s/.test(line[i])) i++;
  const q = line[i];
  if (q !== '"' && q !== "'") return null;
  const j = line.indexOf(q, i + 1);
  return j < 0 ? null : [i, j + 1];
}

function findOutside(line, ch, span) {
  let i = line.indexOf(ch);
  if (span && i >= span[0] && i < span[1]) i = line.indexOf(ch, span[1]);
  return i;
}

/** declaration text -> [{type, name, default, min, max, label, n}]. */
export function parse(text) {
  const out = [];
  const seen = new Map();
  const lines = String(text || "").split(/\r\n|\r|\n/);
  for (let i = 0; i < lines.length; i++) {
    const lineNo = i + 1;
    let line = lines[i].trim();
    if (!line || line.startsWith("#") || line.startsWith("//")) continue;
    let label = "";
    const span = quotedSpan(line);
    const h = findOutside(line, "#", span);
    if (h >= 0) { label = line.slice(h + 1).trim(); line = line.slice(0, h); }
    let rng = "";
    const c = findOutside(line, ":", span);
    if (c >= 0) { rng = line.slice(c + 1); line = line.slice(0, c); }
    let dflt = null;
    const e = line.indexOf("=");
    if (e >= 0) { dflt = line.slice(e + 1).trim(); line = line.slice(0, e); }
    const head = line.split(/\s+/).filter((t) => t);
    if (head.length !== 2)
      throw new Error(`line ${lineNo}: cannot understand '${lines[i].trim()}'. `
        + "Write each line as <type> <name> [= default] [: min max] [# label]");
    const kind = ALIAS[head[0].toLowerCase()];
    if (!kind)
      throw new Error(`line ${lineNo}: unknown type '${head[0]}'`);
    const name = ident(head[1], lineNo);
    if (seen.has(name))
      throw new Error(`line ${lineNo}: parameter name '${name}' duplicates line `
        + `${seen.get(name)}`);
    seen.set(name, lineNo);

    const n = NCOMP[kind];
    let v;
    if (kind === "string") {
      v = dflt === null ? "" : dflt;
      if (v.length >= 2 && v[0] === v[v.length - 1] && "\"'".includes(v[0]))
        v = v.slice(1, -1);
    } else if (kind === "bool") {
      const s = (dflt === null ? "false" : dflt).trim().toLowerCase();
      if (!TRUE.has(s) && !FALSE.has(s))
        throw new Error(`line ${lineNo}: bool default '${dflt}' must be `
          + "true/false");
      v = TRUE.has(s);
    } else if (n > 1) {
      let toks = (dflt || "").replace(/,/g, " ").split(/\s+/).filter((t) => t);
      if (!toks.length) {
        v = new Array(n).fill(0);
      } else {
        if (toks.length === 1) toks = new Array(n).fill(toks[0]);
        if (toks.length !== n)
          throw new Error(`line ${lineNo}: ${kind} default has `
            + `${toks.length} components, expected ${n}`);
        v = toks.map((t) => num(t, lineNo, "default value"));
      }
    } else {
      v = (dflt === null || dflt === "") ? 0 : num(dflt, lineNo, "default value");
      if (kind === "int") v = Math.round(v);
    }

    let lo = null, hi = null;
    if (rng.trim()) {
      const parts = rng.replace(/,/g, " ").split(/\s+/).filter((t) => t);
      if (parts.length !== 2)
        throw new Error(`line ${lineNo}: range must be written as ': min max' (two numbers)`);
      lo = num(parts[0], lineNo, "range min");
      hi = num(parts[1], lineNo, "range max");
      if (lo > hi) throw new Error(`line ${lineNo}: range is reversed: ${lo} > ${hi}`);
      if (kind === "bool" || kind === "string")
        throw new Error(`line ${lineNo}: a ${kind} parameter cannot have a range`);
      if (kind === "int") { lo = Math.round(lo); hi = Math.round(hi); }
    }
    out.push({ type: kind, name, default: v, min: lo, max: hi, label, n });
  }
  return out;
}

/** "pos.y" -> {name:"pos", comp:1}; "radius" -> {name:"radius", comp:null}. */
export function splitRef(ref) {
  const s = String(ref || "").trim();
  if (!s) throw new Error("reference is empty");
  let name = s, key = null;
  if (s.endsWith("]") && s.includes("[")) {
    const i = s.indexOf("[");
    name = s.slice(0, i);
    key = s.slice(i + 1, -1);
  } else if (s.includes(".")) {
    const i = s.indexOf(".");
    name = s.slice(0, i);
    key = s.slice(i + 1);
  } else {
    return { name: s, comp: null };
  }
  const k = String(key).trim().toLowerCase();
  if (!(k in COMPONENTS))
    throw new Error(`reference '${ref}': unknown component '${key}'`);
  return { name: name.trim(), comp: COMPONENTS[k] };
}

// ══════════════════════════════════════════════════════ Panel node
function widgetNamed(node, name) {
  return (node.widgets || []).find((w) => w.name === name);
}

function readValues(node) {
  try { return JSON.parse(widgetNamed(node, "values")?.value || "{}") || {}; }
  catch (_) { return {}; }
}

function writeValues(node, obj) {
  const w = widgetNamed(node, "values");
  if (w) w.value = JSON.stringify(obj);
}

function declText(node) {
  return widgetNamed(node, "declare")?.value || "";
}

/** Current values of all parameters on the panel (declaration merged with stored values). */
export function valuesOf(node) {
  let specs;
  try { specs = parse(declText(node)); } catch (_) { return {}; }
  return mergeValues(specs, readValues(node));
}

/**
 * declaration + stored values -> {name: current value}. **Must match merge() in params.py.**
 *
 * On a type mismatch fall back to the default (after changing a parameter from float to vector, cramming the stored scalar
 * into a three-component control would only produce a confusing state); matching types go through coerceSpec, so stale values outside
 * the declared range get clamped back -- the same behaviour as the min/max on the widget.
 */
export function mergeValues(specs, stored) {
  const st = (stored && typeof stored === "object") ? stored : {};
  const out = {};
  for (const s of specs) {
    const v = st[s.name];
    out[s.name] = fits(s, v) ? coerceSpec(s, v) : s.default;
  }
  return out;
}

function fits(spec, v) {
  if (v === undefined || v === null) return false;
  if (spec.type === "string") return typeof v === "string";
  if (spec.type === "bool") return typeof v === "boolean";
  if (spec.n > 1)
    return Array.isArray(v) && v.length === spec.n
      && v.every((x) => typeof x === "number" && Number.isFinite(x));
  return typeof v === "number" && Number.isFinite(v);
}

function clampOne(spec, x) {
  if (spec.min === null || spec.min === undefined) return Number(x);
  return Math.max(spec.min, Math.min(spec.max, Number(x)));
}

/** Normalize a value according to its declaration. **Must match _coerce() in params.py.** */
export function coerceSpec(spec, v) {
  if (spec.type === "string") return String(v);
  if (spec.type === "bool") return !!v;
  if (spec.n > 1) return Array.from(v, (x) => clampOne(spec, x));
  const x = clampOne(spec, v);
  return spec.type === "int" ? Math.round(x) : x;
}

/** Whether the value (before rounding) is out of range. **Rounding is not a clamp**, see params.py for why. */
function outOfRange(spec, v) {
  if (spec.min === null || spec.min === undefined) return false;
  const xs = Array.isArray(v) ? v : [v];
  return xs.some((x) => Number(x) < spec.min || Number(x) > spec.max);
}

/**
 * Sync the widgets from the declaration. **Append only, never insert** (see the file header for why).
 *
 * When parameters are renamed / deleted, the extra widgets at the tail are removed -- only ones we added ourselves can be removed,
 * because they are all at the end of the array, and serialize:false, so they take no part in the widgets_values indices.
 */
export function syncPanel(node) {
  let specs;
  try {
    specs = parse(declText(node));
    node._pcgErr = "";
  } catch (e) {
    node._pcgErr = e.message;
    return false;
  }
  node._pcgW = node._pcgW || new Map();
  const want = new Map();
  for (const s of specs) {
    if (s.n > 1) {
      for (let i = 0; i < s.n; i++)
        want.set(`${PREFIX}${s.name}.${"xyzw"[i]}`,
                 { spec: s, comp: i,
                   label: `${s.label || s.name}.${"xyzw"[i]}` });
    } else {
      want.set(PREFIX + s.name,
               { spec: s, comp: null, label: s.label || s.name });
    }
  }
  const store = readValues(node);
  let changed = false;

  for (const [wname, w] of [...node._pcgW]) {
    if (want.has(wname)) continue;
    const i = (node.widgets || []).indexOf(w);
    if (i >= 0) node.widgets.splice(i, 1);
    node._pcgW.delete(wname);
    changed = true;
  }
  // Also clear values of parameters no longer in the declaration, otherwise old values linger in the saved workflow after a rename
  const live = new Set(specs.map((s) => s.name));
  for (const k of Object.keys(store)) if (!live.has(k)) delete store[k];
  for (const s of specs)
    store[s.name] = fits(s, store[s.name])
      ? coerceSpec(s, store[s.name]) : s.default;

  for (const [wname, info] of want) {
    if (node._pcgW.has(wname)) {
      const w = node._pcgW.get(wname);
      w.label = info.label;
      const cur = store[info.spec.name];
      w.value = info.comp === null ? cur : cur[info.comp];
      continue;
    }
    const s = info.spec;
    const set = (v) => {
      const st = readValues(node);
      if (info.comp === null) st[s.name] = v;
      else {
        if (!Array.isArray(st[s.name])) st[s.name] = s.default.slice();
        st[s.name][info.comp] = v;
      }
      writeValues(node, st);
    };
    let w;
    const cur = store[s.name];
    const init = info.comp === null ? cur : cur[info.comp];
    if (s.type === "bool") {
      w = node.addWidget("toggle", wname, !!init, set, { serialize: false });
    } else if (s.type === "string") {
      w = node.addWidget("text", wname, String(init ?? ""), set,
                         { serialize: false });
    } else {
      const opt = { serialize: false,
                    step: s.type === "int" ? 10 : 0.1,
                    precision: s.type === "int" ? 0 : 4 };
      if (s.min !== null) { opt.min = s.min; opt.max = s.max; }
      w = node.addWidget("number", wname, Number(init) || 0,
                         (v) => set(s.type === "int" ? Math.round(v) : v),
                         opt);
    }
    w.label = info.label;
    node._pcgW.set(wname, w);
    changed = true;
  }
  writeValues(node, store);
  // Only resize when parameters are added/removed, and **only grow, never shrink** -- computeSize() gives the minimum
  // size; applying it every time would make a node the user enlarged by hand snap back immediately
  if (changed && node.setSize) {
    const need = node.computeSize();
    node.setSize([Math.max(node.size[0], need[0]),
                  Math.max(node.size[1], need[1])]);
  }
  return changed;
}

// ══════════════════════════════════════════════════════ Bindings
export function panels(graph) {
  return (graph?._nodes ?? []).filter((n) => n.type === NODE_TYPE);
}

/**
 * Parameter values of all panels in the graph. Looked up **by name**; when several panels share a name the earliest one wins.
 *
 * Not including the panel id is deliberate: with it, references would all break after copy-pasting nodes or moving
 * subgraphs around, whereas lookup by name is always right for the "one control panel per graph" use case. Duplicate names
 * are reported in the return value and written on the panel title.
 */
export function allValues(graph) {
  const out = {};
  const dup = [];
  for (const p of panels(graph)) {
    const v = valuesOf(p);
    for (const [k, val] of Object.entries(v)) {
      if (k in out) dup.push(k);
      else out[k] = val;
    }
  }
  return { values: out, duplicates: dup };
}

export function bindings(node) {
  const b = node?.properties?.[BIND_KEY];
  return (b && typeof b === "object") ? b : null;
}

export function bind(node, widgetName, ref) {
  if (!node || node.type === NODE_TYPE) return false;   // the panel itself does not accept bindings
  if (!widgetNamed(node, widgetName)) return false;
  node.properties = node.properties || {};
  const b = { ...(bindings(node) || {}) };
  b[widgetName] = String(ref);
  node.properties[BIND_KEY] = b;
  return true;
}

export function unbind(node, widgetName) {
  const b = bindings(node);
  if (!b || !(widgetName in b)) return false;
  const next = { ...b };
  delete next[widgetName];
  if (Object.keys(next).length) node.properties[BIND_KEY] = next;
  else delete node.properties[BIND_KEY];
  const w = widgetNamed(node, widgetName);
  if (w) w.label = undefined;
  if (node._pcgBindErr) delete node._pcgBindErr[widgetName];
  if (node._pcgBindWait) delete node._pcgBindWait[widgetName];
  return true;
}

/** Declared type of the target widget. nodeData is the most reliable source; fall back to the widget. */
export function widgetSpec(node, widgetName) {
  const inp = node?.constructor?.nodeData?.input;
  for (const grp of ["required", "optional"]) {
    const s = inp?.[grp]?.[widgetName];
    if (Array.isArray(s)) return s;
  }
  return null;
}

/**
 * Put a parameter value into the target widget. Returns null when it does not fit (incompatible type).
 *
 * INT must be **rounded**: otherwise the ComfyUI backend gets 3.7 and raises a type error, and the error shows up
 * on that node, miles away from "I changed the parameter panel".
 */
export function coerce(node, widget, value) {
  const spec = widgetSpec(node, widget.name);
  const kind = Array.isArray(spec) ? spec[0] : null;
  const opt = widget.options || {};
  if (Array.isArray(kind)) {                 // combo box: only accept values in the list
    const s = String(value);
    return kind.includes(s) ? s : null;
  }
  if (kind === "STRING" || widget.type === "text"
      || widget.type === "customtext") {
    return Array.isArray(value) ? value.join(" ") : String(value);
  }
  if (kind === "BOOLEAN" || widget.type === "toggle") {
    return Array.isArray(value) ? !!value[0] : !!value;
  }
  let v = Array.isArray(value) ? value[0] : value;
  if (typeof v === "boolean") v = v ? 1 : 0;
  v = Number(v);
  if (!Number.isFinite(v)) return null;
  const isInt = kind === "INT"
    || (kind === null && (opt.precision === 0 || opt.round === 1));
  if (isInt) v = Math.round(v);
  if (typeof opt.min === "number") v = Math.max(opt.min, v);
  if (typeof opt.max === "number") v = Math.min(opt.max, v);
  return v;
}

/**
 * Write the panel's values into all bound widgets. Returns how many were actually written.
 *
 * **Don't write if the value did not change.** That is the whole point of fine-grained invalidation: when radius changes, only
 * the widgets referencing radius change value, other nodes' widgets_values stay bit-for-bit the same, so the submitted
 * prompt hash does not change and the backend keeps reusing the cache. Blindly rewriting every tick would,
 * even with identical values, call callbacks a bunch of times, and the day someone puts a
 * side effect in a callback it becomes "while the parameter panel is open, the whole graph twitches every 0.4 s".
 */
export function applyBindings(graph) {
  const { values, duplicates } = allValues(graph);
  let wrote = 0;
  const missing = [];
  for (const node of graph?._nodes ?? []) wrote += applyNode(graph, node, values, missing);
  return { wrote, missing, duplicates };
}

/** Evaluate all bindings on a node and write them into widgets. Returns how many were written; references not found are pushed into missing. */
export function applyNode(graph, node, values = allValues(graph).values, missing = []) {
  let wrote = 0;
  const b = bindings(node);
  if (!b) {
    if (node._pcgBindErr) node._pcgBindErr = null;
    if (node._pcgBindWait) node._pcgBindWait = null;
    return 0;
  }
  const errs = {}, waits = {};
  for (const [wname, ref] of Object.entries(b)) {
    const w = widgetNamed(node, wname);
    if (!w) continue;                       // widget is gone (node changed version)
    const r = evalBinding(graph, node, wname, values);
    const shown = bindingText(graph, node, wname);
    if (!r.ok) {
      missing.push(ref);
      if (r.pending) waits[wname] = r.error;      // waiting for data: not an error, the field does not turn red
      else errs[wname] = r.error || "reference not found";
      w.label = `${wname} ←${shown}?`;
      continue;
    }
    w.label = `${wname} ←${shown}`;
    const next = coerce(node, w, r.value);
    if (next === null) {
      errs[wname] = `result ${fmtStr(r.value)} does not fit this parameter (type mismatch)`;
      continue;
    }
    if (next === w.value) continue;
    w.value = next;
    try { w.callback?.(next, app.canvas, node); } catch (_) { /* don't abort */ }
    wrote++;
  }
  node._pcgBindErr = Object.keys(errs).length ? errs : null;
  node._pcgBindWait = Object.keys(waits).length ? waits : null;
  return wrote;
}

// ══════════════════════════════════════ Node-to-node references (Copy Parameter / Paste Relative References)
//
// In Houdini any parameter can be Copy Parameter'ed, then Paste Relative References on another parameter,
// giving ch("../box1/sizex"). Here the reference is written as "@<node id>/<widget name>", stored in the same binding table
// as panel-parameter name references (node.properties.pcg_bind), and takes the same "frontend materialization" route: when the source parameter changes,
// the value is written into the target widget, the submitted prompt is the value you see, and the cache is invalidated by value.
//
// Why node id rather than title: titles can be duplicated and changed any time; the id is stable within a workflow.
// As in Houdini, when two nodes are copy-pasted together, the new one still references the **original** source node.
// Reference chains (A refs B, B refs C) are resolved all the way in one go; cycles are marked not-found and the value is left alone.
export const NODE_REF = /^@(-?\d+)\/(.+)$/;
const nodeKey = (id, w) => `@${id}/${w}`;

export function nodeRef(node, wname) { return nodeKey(node.id, wname); }

function nodeById(graph, id) {
  return graph?.getNodeById?.(id)
    ?? (graph?._nodes ?? []).find((n) => String(n.id) === String(id)) ?? null;
}

function isLinked(node, wname) {
  return (node?.inputs || []).some((i) =>
    (i?.widget?.name === wname || i?.name === wname) && i.link != null);
}

/** reference -> {ok, value}. Panel parameter names are looked up by name; node references follow the binding chain upward, with cycle detection. */
export function resolveRef(graph, ref, values, seen = new Set()) {
  const m = NODE_REF.exec(String(ref));
  if (!m) {
    try {
      const { name, comp } = splitRef(ref);
      if (!values || !(name in values)) return { ok: false };
      const v = comp === null ? values[name] : values[name]?.[comp];
      return v === undefined ? { ok: false } : { ok: true, value: v };
    } catch (_) { return { ok: false }; }
  }
  const key = nodeKey(m[1], m[2]);
  if (seen.has(key)) return { ok: false, cycle: true };
  const src = nodeById(graph, m[1]);
  const w = src && widgetNamed(src, m[2]);
  if (!w) return { ok: false };
  if (isLinked(src, m[2])) return { ok: false, linked: true };   // value only known at runtime
  const up = bindings(src)?.[m[2]];
  if (up !== undefined) {
    seen.add(key);
    if (isExpr(up)) return evalStored(graph, src, up, values, seen);
    return resolveRef(graph, up, values, seen);
  }
  return { ok: true, value: w.value };
}

/** Human-readable reference: node references are written as "title.param" (what Houdini's ch("../box1/sizex") means). */
export function refText(graph, ref) {
  const m = NODE_REF.exec(String(ref));
  if (!m) return String(ref);
  const src = nodeById(graph, m[1]);
  return `${src ? (src.title || src.type) : "#" + m[1]}.${m[2]}`;
}

/**
 * Houdini-style expression syntax, shown in the field by default: node reference → ch("../source node title/param name");
 * panel parameter → ch("../panel title/param name") (if no panel has that name, just the name).
 * Strings / combos use chs(), as in Houdini. This is **display only**: what is stored is still "@id/param",
 * so renaming the source node updates this and the reference does not break.
 */
export function refExpr(graph, ref, str = false, self = null) {
  const m = NODE_REF.exec(String(ref));
  let path;
  if (m) {
    path = pathToDisplay(graph, self, String(ref));
  } else {
    const s = String(ref).trim();
    let owner = null;
    try {
      const { name } = splitRef(s);
      owner = panels(graph).find((p) => name in valuesOf(p)) ?? null;
    } catch (_) { /* malformed reference: show as is */ }
    path = owner ? `../${owner.title || owner.type}/${s}` : s;
  }
  return `${str ? "chs" : "ch"}("${path.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}")`;
}

// ══════════════════════════════════════ Expressions in fields (pcg91 / pcg93)
//
// Besides "@id/param" (paste relative reference) and panel parameter names, the binding table has three "computed" kinds (syntax in pcg_hexpr.js):
//
//   "=expression"  typed into a numeric field: `ch("../grid1/rows")*2`, `sin($F*10)`, `npoints("../box1")`
//   "~template"    typed into a string field: `render/$OS.$F4.png`, `` `chs("../a/name")`_v2 ``
//   "k:keyframes"  frames set with Alt+click on any numeric parameter, same syntax as Channel (PCG): "0:0  12:5:ease"
//
// **Paths are replaced by ids when stored**: the user types `ch("../grid1/rows")`, what is stored is `ch("@12/rows")`,
// and it is converted back to the current title for display -- titles change and get duplicated, ids do not; same reason as paste relative reference.
// Parameters of this node (`ch("tx")`) are not converted: when the node is copied, it still refers to "its own tx", as in Houdini.
// Duplicate titles and paths not found are stored as is and raise at evaluation (field turns red); fixing the name heals it.
export const EXPR_PREFIX = "=";
export const TMPL_PREFIX = "~";
export const KEY_PREFIX = "k:";
export const isNumExpr = (b) => typeof b === "string" && b.startsWith(EXPR_PREFIX);
export const isTmpl = (b) => typeof b === "string" && b.startsWith(TMPL_PREFIX);
export const isKeys = (b) => typeof b === "string" && b.startsWith(KEY_PREFIX);
/** Computed bindings (expression / template / keyframes), as opposed to pasted direct references. */
export const isExpr = (b) => isNumExpr(b) || isTmpl(b) || isKeys(b);

const titleOf = (n) => n?.title || n?.type || "";

function nodesTitled(graph, t) {
  return (graph?._nodes ?? []).filter((n) => titleOf(n) === t);
}

// Functions whose first argument is a **parameter path**, and functions whose first argument is a **node path** (geometry queries, names)
const PARAM_FUNCS = new Set(["ch", "chf", "chs"]);

/** user-typed path -> stored path. Parameter path "../title/tx" -> "@id/tx"; node path "../title" -> "@id". Returns null if it cannot be converted. */
export function pathToCanon(graph, path, fname = "ch") {
  const isParam = PARAM_FUNCS.has(fname);
  const m = isParam ? /^\.\.\/(.+)\/([^/]+)$/.exec(String(path))
    : /^\.\.\/([^/]+)$/.exec(String(path));
  if (!m) return null;
  const tail = isParam ? `/${m[2]}` : "";
  const id = /^#(-?\d+)$/.exec(m[1]);
  if (id) return `@${id[1]}${tail}`;
  const hits = nodesTitled(graph, m[1]);
  return hits.length === 1 ? `@${hits[0].id}${tail}` : null;
}

/** stored path -> displayed path: "@id/tx" -> "../title/tx" (just "tx" for this node); "@id" -> "../title" ("." for this node). */
export function pathToDisplay(graph, self, path) {
  const s = String(path);
  const nm = /^@(-?\d+)$/.exec(s);
  if (nm) {
    if (self && String(self.id) === nm[1]) return ".";
    const src = nodeById(graph, nm[1]);
    return `../${src ? titleOf(src) : "#" + nm[1]}`;
  }
  const m = NODE_REF.exec(s);
  if (!m) return s;
  if (self && String(self.id) === m[1]) return m[2];
  const src = nodeById(graph, m[1]);
  return `../${src ? titleOf(src) : "#" + m[1]}/${m[2]}`;
}

const mapFor = (stored) => (isTmpl(stored) ? mapTemplatePaths : mapChPaths);

/** stored binding -> text displayed in the field (for keyframes, the keyframe line itself). */
export function exprDisplay(graph, self, stored) {
  const s = String(stored);
  if (isKeys(s)) return s.slice(KEY_PREFIX.length);
  const body = s.slice(1);
  return mapFor(s)(body, (p) => pathToDisplay(graph, self, p));
}

/**
 * user-typed text -> stored binding (prefix = "=" numeric expression / "~" string template). old is what this field stored before:
 * paths that were already known are converted the old way first -- with duplicate titles, the untouched part of the reference still points at the original node.
 */
export function exprStore(graph, self, typed, old, prefix = EXPR_PREFIX) {
  const hint = new Map();
  const learn = (p) => { hint.set(pathToDisplay(graph, self, p), p); return null; };
  if (isNumExpr(old) || isTmpl(old)) mapFor(old)(old.slice(1), learn);
  else if (typeof old === "string" && NODE_REF.test(old)) learn(old);
  const map = prefix === TMPL_PREFIX ? mapTemplatePaths : mapChPaths;
  return prefix + map(String(typed).trim(), (p, fname) => hint.get(p) ?? pathToCanon(graph, p, fname));
}

/** Time variables all come from the Frame (PCG) node in the graph (that's what the playbar writes); without one, use its defaults. at: evaluate at another frame (chf). */
function frameVars(graph, at) {
  const fr = (graph?._nodes ?? []).find((n) => n.type === "PCG_Frame");
  const g = (k, d) => {
    const v = Number(fr && widgetNamed(fr, k)?.value);
    return Number.isFinite(v) ? v : d;
  };
  const f = at ?? g("frame", 0), a = g("start", 0), b = g("end", 23), fps = g("fps", 24);
  return { F: f, FF: f, FSTART: a, FEND: b, FPS: fps, NFRAMES: Math.abs(b - a) + 1,
           T: (f - a) / Math.max(fps, 1e-6) };
}

/** The current frame (for setting keyframes). */
export function currentFrame(graph) { return frameVars(graph).F; }

/** node path ("." / "../title" / "../#id" / "@id") -> node. */
function nodeAt(graph, self, path) {
  const p = String(path).trim();
  if (p === "." || p === "./" || p === "") return self;
  const id = /^@(-?\d+)$/.exec(p) || /^\.\.\/#(-?\d+)$/.exec(p);
  if (id) {
    const n = nodeById(graph, id[1]);
    if (!n) throw new ExprError(`node #${id[1]} no longer exists`);
    return n;
  }
  const r = /^\.\.\/([^/]+)$/.exec(p);
  if (!r) throw new ExprError(`unrecognized node path '${path}': only "." (this node) and "../node name" are supported`);
  const hits = nodesTitled(graph, r[1]);
  if (!hits.length) throw new ExprError(`no node named '${r[1]}'`);
  if (hits.length > 1) throw new ExprError(`${hits.length} nodes are named '${r[1]}', rename the one you want to reference first`);
  return hits[0];
}

/** ch() path -> value of that parameter (at: at which frame). Throws ExprError on failure (shown in the field's red tooltip). */
function readParam(graph, self, path, values, seen, at) {
  const p = String(path).replace(/^\.\//, "");
  let node, wname;
  const m = NODE_REF.exec(p);
  if (m) {
    node = nodeById(graph, m[1]);
    wname = m[2];
    if (!node) throw new ExprError(`node #${m[1]} no longer exists`);
  } else if (!p.includes("/")) {
    node = self;
    wname = p;
  } else {
    const r = /^(\.\.\/.+)\/([^/]+)$/.exec(p);
    if (!r) throw new ExprError(`unrecognized path '${path}': only "param name" and "../node name/param name" are supported`);
    node = nodeAt(graph, self, r[1]);
    wname = r[2];
  }
  if (node.type === NODE_TYPE) {                  // parameter panel: by its declared parameter names
    let ref;
    try { ref = splitRef(wname); } catch (e) { throw new ExprError(e.message); }
    const vals = valuesOf(node);
    if (!(ref.name in vals)) throw new ExprError(`panel '${titleOf(node)}' has no parameter ${ref.name}`);
    const v = ref.comp === null ? vals[ref.name] : vals[ref.name]?.[ref.comp];
    if (Array.isArray(v)) throw new ExprError(`${ref.name} is a vector, specify a component (${ref.name}.x)`);
    if (v === undefined) throw new ExprError(`${wname} has no such component`);
    return v;
  }
  const w = widgetNamed(node, wname);
  if (!w) throw new ExprError(`'${titleOf(node)}' has no parameter ${wname}`);
  if (isLinked(node, wname))
    throw new ExprError(`${wname} on '${titleOf(node)}' is wired, its value is only known at runtime`);
  const key = nodeKey(node.id, wname);
  const up = bindings(node)?.[wname];
  if (up === undefined) return w.value;
  if (seen.has(key)) throw new ExprError(`reference cycle (${titleOf(node)}.${wname})`);
  seen.add(key);
  const r = isExpr(up) ? evalStored(graph, node, up, values, seen, at)
    : resolveRef(graph, up, values, seen);
  seen.delete(key);
  if (!r.ok) {
    if (r.pending) throw new ExprPending(r.error);
    throw new ExprError(r.error || `reference of ${titleOf(node)}.${wname} not found`);
  }
  return r.value;
}

/** What is available when evaluating an expression (variables, ch, node / geometry functions). */
function makeCtx(graph, self, values, seen, at) {
  const fv = frameVars(graph, at);
  return {
    vars: (n) => (n === "OS" ? titleOf(self) : fv[n]),
    ch: (path, str, frame) => {
      const v = readParam(graph, self, path, values, seen, frame ?? at);
      if (str) return typeof v === "number" ? fmtStr(v) : String(v);
      if (typeof v === "number") return v;
      const x = Number(v);                      // checkbox true / false also become 1 / 0 here
      if (String(v).trim() === "" || !Number.isFinite(x))
        throw new ExprError(`'${path}' is the string '${v}', use chs()`);
      return x;
    },
    funcs: {
      opname: (path = ".") => titleOf(nodeAt(graph, self, path)),
      opinputpath: (path, i = 0) => {
        const n = nodeAt(graph, self, path);
        const geo = (n.inputs || []).filter((x) => !x.widget);   // geometry inputs (excluding parameter sockets)
        const inp = geo[Math.trunc(Number(i))];
        if (!inp) return "";
        const l = graph?.links?.get?.(inp.link) ?? graph?.links?.[inp.link];
        return l ? `@${l.origin_id}` : "";
      },
      ...geoFuncs(graph, self, nodeAt),
    },
  };
}

/** Evaluate a stored binding on node self -> {ok, value} / {ok:false, error, pending}. at: evaluate at another frame. */
export function evalStored(graph, self, stored, values = allValues(graph).values,
                           seen = new Set(), at = undefined) {
  try {
    const s = String(stored);
    if (isKeys(s)) {
      let keys;
      try { keys = parseKeys(s.slice(KEY_PREFIX.length)); }
      catch (e) { throw new ExprError(e.message); }
      return { ok: true, value: evalKeys(keys, frameVars(graph, at).F) };
    }
    const ctx = makeCtx(graph, self, values, seen, at);
    if (isTmpl(s)) {
      const value = expandTemplate(s.slice(1), {
        vars: ctx.vars,
        expr: (src) => evalExprAst(parseExpr(src), ctx),
      });
      return { ok: true, value };
    }
    return { ok: true, value: evalExprAst(parseExpr(s.slice(EXPR_PREFIX.length)), ctx) };
  } catch (e) {
    if (e instanceof ExprPending) return { ok: false, pending: true, error: e.message };
    if (e instanceof ExprError) return { ok: false, error: e.message };
    throw e;
  }
}

/** Evaluate one binding (of any kind). */
export function evalBinding(graph, node, wname, values = allValues(graph).values) {
  const b = bindings(node)?.[wname];
  if (b === undefined) return { ok: false, error: "no binding" };
  const seen = new Set([nodeKey(node.id, wname)]);
  if (isExpr(b)) return evalStored(graph, node, b, values, seen);
  const r = resolveRef(graph, b, values, seen);
  if (!r.ok && !r.error)
    r.error = r.cycle ? "reference cycle" : r.linked ? "source parameter is wired, its value is only known at runtime" : "reference not found";
  return r;
}

/**
 * Text shown in this field. str: string / combo (pasted references written as chs); tmpl: string field
 * (pasted references written as `chs(...)` with backticks -- so clicking in to edit gives a valid template).
 */
export function bindingText(graph, node, wname, str = false, tmpl = false) {
  const b = bindings(node)?.[wname];
  if (b === undefined) return "";
  if (isExpr(b)) return exprDisplay(graph, node, b);
  const ex = refExpr(graph, b, str || tmpl, node);
  return tmpl ? "`" + ex + "`" : ex;
}

/**
 * An expression was typed into a field: store it and materialize once right away. Malformed ones are stored anyway (the field turns red, the value stays,
 * as in Houdini -- when editing you can still see what you wrote). Returns {ok, error}.
 * prefix: "=" numeric expression, "~" string template.
 */
export function bindExpr(node, wname, typed, graph, prefix = EXPR_PREFIX) {
  const text = String(typed).trim();
  if (!text) return { ok: false, error: "expression is empty" };
  const old = bindings(node)?.[wname];
  if (!bind(node, wname, exprStore(graph, node, text, old, prefix)))
    return { ok: false, error: "cannot bind" };
  applyNode(graph, node);                 // evaluate this node first (it may not be in graph, e.g. not added yet)
  applyBindings(graph);                   // then let the ones referencing it catch up
  const err = node._pcgBindErr?.[wname];
  if (err) return { ok: false, error: err };
  const wait = node._pcgBindWait?.[wname];
  return wait ? { ok: false, pending: true, error: wait } : { ok: true };
}

/** Template typed into a string field (has backticks or $variables). */
export function bindTemplate(node, wname, typed, graph) {
  return bindExpr(node, wname, typed, graph, TMPL_PREFIX);
}

// ══════════════════════════════════════ Geometry queries in fields (pcg93)
//
// The npoints("../box1"), bbox("../box1", D_YSIZE), point("../box1", 0, "P", 1) family.
// Houdini cooks on demand, computing whichever node is asked; ComfyUI submits the whole graph and only has results once it finishes,
// so the frontend cannot get the geometry "right now". What is read here is **the result of that node's last run**:
//   - after each geometry-outputting node runs, the backend sends a summary in ui (point count, primitive count, bounding box, detail attributes) plus a
//     key (geoquery.py); the frontend stores it in the node's properties.pcg_geoq (saved workflows carry it too)
//   - the summary is used directly; point() / prim(), which need specific elements, fetch /pcg/geoq/<key> with the key and materialize again once it arrives
//   - hence **one run behind**: change upstream and run, and this submission uses values computed from the previous geometry; another run is needed to catch up.
//     This is a hard limit of "frontend computes values, backend runs the graph", documented in the README
//   - not run yet / fetching: the field does not turn red (it is not an error), the hover says what it is waiting for
const GEO_KEY = "pcg_geoq";
const GQ = new Map();              // "key|query" -> {ok, value} | {pending} | {missing} | {error}
let geoFetcher = null;
let rematTimer = null;

/** Replace the fetch function (for tests): (key, query) => Promise<json>; when the server lacks the key, return {missing:true}. */
export function setGeoFetcher(f) { geoFetcher = f; }
/** Which keys are in the cache now (for tests: caches for old keys must be thrown away, otherwise it keeps growing). */
export function geoCacheKeys() { return [...new Set([...GQ.keys()].map((k) => k.split("|")[0]))]; }

function defaultGeoFetch(key, q) {
  const url = `/pcg/geoq/${encodeURIComponent(key)}?${new URLSearchParams(q)}`;
  const go = api?.fetchApi ? api.fetchApi(url) : fetch(url);
  return go.then(async (r) => {
    if (r.status === 404) return { missing: true };
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  });
}

function remat() {
  if (rematTimer) return;
  rematTimer = setTimeout(() => {
    rematTimer = null;
    try {
      applyBindings(app.graph);
      app.canvas?.setDirty?.(true, true);
    } catch (e) { console.error("[pcg.params] materialize after geometry fetch failed", e); }
  }, 0);
}

function geoGet(key, q, title) {
  const id = key + "|" + JSON.stringify(q);
  const c = GQ.get(id);
  if (c?.ok) return c.value;
  if (c?.missing) throw new ExprPending(`geometry of '${title}' is no longer on the server (server restarted? run again)`);
  if (c?.error) throw new ExprError(c.error);
  if (!c) {
    GQ.set(id, { pending: true });
    Promise.resolve().then(() => (geoFetcher || defaultGeoFetch)(key, q)).then((j) => {
      GQ.set(id, j?.missing ? { missing: true } : { ok: true, value: j });
      remat();
    }, (e) => {
      GQ.set(id, { error: `fetching geometry of '${title}' failed: ${e?.message || e}` });
      remat();
    });
  }
  throw new ExprPending(`fetching geometry of '${title}'…`);
}

/** A node finished running (pcg_geoq in the executed message): record the key and summary, drop caches of the old key. */
export function primeGeo(node, d) {
  if (!node || !d?.key) return;
  node.properties = node.properties || {};
  const old = node.properties[GEO_KEY];
  if (old && old !== d.key) for (const k of [...GQ.keys()]) if (k.startsWith(old + "|")) GQ.delete(k);
  node.properties[GEO_KEY] = d.key;
  if (d.summary) GQ.set(d.key + "|" + JSON.stringify({ op: "summary" }), { ok: true, value: d.summary });
  remat();
}

function geoFuncs(graph, self, nodeAt) {
  const keyOf = (path) => {
    const n = nodeAt(graph, self, path);
    const key = n.properties?.[GEO_KEY];
    if (!key) throw new ExprPending(`'${titleOf(n)}' has not run yet: run it once before its geometry can be queried`);
    return { n, key, title: titleOf(n) };
  };
  const sum = (path) => {
    const { key, title } = keyOf(path);
    return geoGet(key, { op: "summary" }, title);
  };
  const box = (path) => {
    const b = sum(path).bbox;
    if (!b) throw new ExprError("geometry is empty, no bounding box");
    return b;
  };
  const pick = (v, idx, str) => {
    if (v === null || v === undefined) return str ? "" : 0;      // no such attribute / out of range: Houdini gives 0
    if (str) return Array.isArray(v) ? fmtStr(v[Math.trunc(idx)] ?? "") : String(v);
    if (typeof v === "string") throw new ExprError(`it is a string attribute '${v}', use the function with s`);
    const x = Array.isArray(v) ? v[Math.trunc(idx)] : v;
    return x === undefined ? 0 : Number(x);
  };
  const elem = (cls, str) => (path, i, name, idx = 0) => {
    const { key, title } = keyOf(path);
    const r = geoGet(key, { op: "elem", cls, n: String(Math.trunc(Number(i))), name: String(name) }, title);
    return pick(r.value, idx, str);
  };
  return {
    npoints: (p) => sum(p).npoints,
    nprims: (p) => sum(p).nprims,
    nvertices: (p) => sum(p).nvertices,
    bbox: (p, which) => {
      const [mn, mx] = box(p), w = Math.trunc(Number(which));
      if (w >= 0 && w < 6) return w % 2 ? mx[w >> 1] : mn[w >> 1];
      if (w >= 6 && w < 9) return mx[w - 6] - mn[w - 6];
      throw new ExprError("the second argument of bbox() must be D_XMIN … D_ZSIZE");
    },
    centroid: (p, axis) => {
      const [mn, mx] = box(p), a = Math.trunc(Number(axis));
      if (!(a >= 0 && a < 3)) throw new ExprError("the second argument of centroid() must be D_X / D_Y / D_Z");
      return (mn[a] + mx[a]) / 2;
    },
    detail: (p, name, idx = 0) => pick(sum(p).detail?.[name], idx, false),
    details: (p, name) => pick(sum(p).detail?.[name], 0, true),
    point: elem("point", false), points: elem("point", true),
    prim: elem("prim", false), prims: elem("prim", true),
  };
}

// ══════════════════════════════════════ Who references whom (for drawing dashed lines, pcg94)
//
// When a node is selected in Houdini, a very faint thin dashed line is drawn to nodes it has channel references with (so you can see in the network who follows whom).
// Here all references in the binding table are turned into "source node → this node": pasted "@id/param", panel parameter names, and paths written directly
// in expressions / templates for ch / chs / chf / npoints / bbox …. Computed paths like opinputpath don't count (they point at the wired upstream anyway).
// Parameters of this node itself (ch("tx")) don't count.
const pathCache = new Map();              // binding string -> paths written in it

export function bindingPaths(b) {     // drawing dashed lines walks the whole graph every frame, so cache per string (the same string gets the same array)
  let out = pathCache.get(b);
  if (out) return out;
  out = [];
  const take = (p) => { out.push(String(p)); return null; };
  if (isNumExpr(b)) mapChPaths(b.slice(1), take);
  else if (isTmpl(b)) mapTemplatePaths(b.slice(1), take);
  // What remains is pasted "@id/w", panel parameter names, or keyframes "k:...". Keyframes need no special exclusion: they neither match
  // "@id" nor can be a panel parameter name (parameter names contain no colons or spaces), so pathTarget naturally gives null
  else if (b != null) out.push({ legacy: String(b) });
  if (pathCache.size > 4000) pathCache.clear();
  pathCache.set(b, out);
  return out;
}

/** A path written in a binding -> the node it points at (null when not found / self / ambiguous duplicate name). */
function pathTarget(graph, self, p) {
  if (typeof p === "object") {                              // pasted reference / panel parameter name
    const m = NODE_REF.exec(p.legacy);
    if (m) return nodeById(graph, m[1]);
    let name;
    try { name = splitRef(p.legacy).name; } catch (_) { return null; }
    return panels(graph).find((q) => name in valuesOf(q)) ?? null;
  }
  const id = /^@(-?\d+)(?:\/|$)/.exec(p) || /^\.\.\/#(-?\d+)(?:\/|$)/.exec(p);
  if (id) return nodeById(graph, id[1]);
  const t = /^\.\.\/([^/]+)(?:\/[^/]+)?$/.exec(p);
  if (!t) return null;                                      // "tx" / "." = this node
  const hits = nodesTitled(graph, t[1]);
  return hits.length === 1 ? hits[0] : null;
}

/** Which nodes this node references: [{node, params:[parameter names on this node]}]. */
export function refSources(graph, node) {
  const b = bindings(node);
  if (!b) return [];
  const by = new Map();
  for (const [wname, ref] of Object.entries(b)) {
    for (const p of bindingPaths(ref)) {
      const src = pathTarget(graph, node, p);
      if (!src || src === node) continue;
      if (!by.has(src)) by.set(src, new Set());
      by.get(src).add(wname);
    }
  }
  return [...by].map(([n, ws]) => ({ node: n, params: [...ws] }));
}

/** Reference edges of the whole graph: [{from: referenced, to: referencing, params}]. */
export function refEdges(graph) {
  const out = [];
  for (const n of graph?._nodes ?? [])
    for (const r of refSources(graph, n)) out.push({ from: r.node, to: n, params: r.params });
  return out;
}

// ── Keyframes (Alt+click on a parameter in Houdini)
/** Keyframes of this field [{f, v, c, s}]; null when it is not a keyframe binding. */
export function keysOf(node, wname) {
  const b = bindings(node)?.[wname];
  if (!isKeys(b)) return null;
  try { return parseKeys(b.slice(KEY_PREFIX.length)); } catch (_) { return null; }
}

/** Whether there is a keyframe on the current frame (field is a bit brighter). */
export function onKey(graph, node, wname) {
  const k = keysOf(node, wname);
  const f = currentFrame(graph);
  return !!k && k.some((q) => Math.abs(q.f - f) <= 1e-9);
}

/**
 * Set a keyframe with value value at frame. If it was keyframes already, add to them (if that frame already had a key, change its value, keeping interpolation /
 * slope); if it was an expression / reference / unbound, start from this single key (Houdini too: once keyed, the parameter is driven by the channel).
 */
export function setKey(graph, node, wname, frame, value) {
  const v = Number(value), f = Number(frame);
  if (!Number.isFinite(v) || !Number.isFinite(f)) return false;
  const keys = keysOf(node, wname) || [];
  const hit = keys.find((q) => Math.abs(q.f - f) <= 1e-9);
  if (hit) hit.v = v;
  else keys.push({ f, v, c: 5, s: NaN });          // 5 = cubic, same as Channel's default
  keys.sort((a, b) => a.f - b.f);
  if (!bind(node, wname, KEY_PREFIX + formatKeys(keys))) return false;
  applyNode(graph, node);
  applyBindings(graph);
  return true;
}

/** Delete the keyframe at frame. When all are deleted it is no longer a channel, and the parameter stays at its current value. Returns whether one was deleted. */
export function removeKey(graph, node, wname, frame) {
  const keys = keysOf(node, wname);
  if (!keys) return false;
  const left = keys.filter((q) => Math.abs(q.f - Number(frame)) > 1e-9);
  if (left.length === keys.length) return false;
  if (!left.length) unbind(node, wname);
  else bind(node, wname, KEY_PREFIX + formatKeys(left));
  applyNode(graph, node);
  applyBindings(graph);
  return true;
}

// Clipboard: a panel parameter name (CLIP, the old one) or node parameters (PCLIP). Whichever was copied last wins
let PCLIP = null;

export function copyParams(node, names) {
  const ws = names.map((n) => widgetNamed(node, n)).filter(Boolean);
  if (!ws.length) return null;
  PCLIP = { id: node.id, title: node.title || node.type, names: ws.map((w) => w.name),
            values: ws.map((w) => w.value) };
  return PCLIP;                     // clipboard() / paste look at PCLIP first, the old CLIP need not be cleared
}

export function clipboard() {
  if (PCLIP) return { kind: "node", text: `${PCLIP.title}.${PCLIP.names.join(",")}`,
                      count: PCLIP.names.length };
  if (CLIP) return { kind: "panel", text: CLIP, count: 1 };
  return null;
}

/**
 * Source and target map one to one: same count pairs them up (vector to vector); a single source is pointed to by all;
 * a single target takes the first source; both more than one but different counts pair up to the shorter one.
 */
export function pairUp(src, dst) {
  if (src.length === 1) return dst.map((d) => [src[0], d]);
  return dst.slice(0, src.length).map((d, i) => [src[i], d]);
}

/** Paste Relative References. Returns {bound:[names], skipped:[[name, reason]]}. */
export function pasteRefs(node, names, graph) {
  const out = { bound: [], skipped: [] };
  const ok = new Set(bindableWidgets(node).map((w) => w.name));
  const { values } = allValues(graph);
  let pairs;
  if (PCLIP) pairs = pairUp(PCLIP.names.map((n) => nodeKey(PCLIP.id, n)), names);
  else if (CLIP) pairs = names.map((n) => [CLIP, n]);
  else return out;
  for (const [ref, wname] of pairs) {
    if (!ok.has(wname)) { out.skipped.push([wname, "wired"]); continue; }
    if (ref === nodeKey(node.id, wname)) { out.skipped.push([wname, "cannot reference itself"]); continue; }
    const r = resolveRef(graph, ref, values, new Set([nodeKey(node.id, wname)]));
    if (r.cycle) { out.skipped.push([wname, "would create a cycle"]); continue; }
    if (r.ok && coerce(node, widgetNamed(node, wname), r.value) === null) {
      out.skipped.push([wname, "type mismatch"]);
      continue;
    }
    bind(node, wname, ref);
    out.bound.push(wname);
  }
  if (out.bound.length) applyBindings(graph);
  return out;
}

/** Paste Copied Values: copy the values over once, without keeping a reference. */
export function pasteValues(node, names, graph) {
  let src;
  if (PCLIP) src = PCLIP.values;
  else if (CLIP) {
    const r = resolveRef(graph, CLIP, allValues(graph).values);
    if (!r.ok) return 0;
    src = [r.value];
  } else return 0;
  let n = 0;
  for (const [v, wname] of pairUp(src, names)) {
    const w = widgetNamed(node, wname);
    if (!w || isLinked(node, wname)) continue;
    const next = coerce(node, w, v);
    if (next === null || next === w.value) continue;
    const old = w.value;
    w.value = next;
    try { w.callback?.(next, app.canvas, node); } catch (_) { /* */ }
    try { node.onWidgetChanged?.(wname, next, old, w); } catch (_) { /* */ }
    n++;
  }
  return n;
}

// ══════════════════════════════════════ Letting a model fill it in (Params from JSON)
//
// The backend node only **cleanly parses** whatever the model emitted; filtering names, clamping ranges and writing into
// the panel all happen here -- because only the frontend knows the declaration (it is the text on the panel).
//
// **This is the entire boundary through which AI can touch this graph**, and it is structural, not enforced through the prompt:
// it can only fill in values for **already declared** parameters. Keys not in the declaration go into unknown (no parameter created),
// wrong types go into skipped (original value kept), out-of-range values are clamped and go into clamped.
// So the model can change values, but not topology, not bindings, and it cannot add parameters.

/** One application onto one panel. **Must match apply_values() in params.py.** */
export function applyValues(specs, current, incoming) {
  const by = new Map(specs.map((s) => [s.name, s]));
  const out = { ...mergeValues(specs, current) };
  const rep = { applied: [], clamped: [], unknown: [], skipped: [] };
  if (!incoming || typeof incoming !== "object" || Array.isArray(incoming))
    throw new Error("expected a JSON object ({\"name\": value})");
  for (const [k, raw] of Object.entries(incoming)) {
    const name = String(k).trim();
    const sp = by.get(name);
    if (!sp) { rep.unknown.push(name); continue; }
    let v = raw;
    if (typeof v === "string" && sp.type !== "string") {
      // Models love writing numbers as strings; rescue them where possible. inf/nan count as unrescuable -- they would travel
      // into the geometry and become a pile of nan vertices, by which point you are far away from "the model filled in an inf"
      const f = v.trim() === "" ? NaN : Number(v);
      if (!Number.isFinite(f)) { rep.skipped.push(name); continue; }
      v = f;
    }
    if (!fits(sp, v)) {
      if (sp.type === "bool" && typeof v === "number") v = !!v;
      else if (sp.n > 1 && typeof v === "number")
        v = new Array(sp.n).fill(v);           // a single number fills every component
      else { rep.skipped.push(name); continue; }
    }
    if (outOfRange(sp, v)) rep.clamped.push(name);
    out[name] = coerceSpec(sp, v);
    rep.applied.push(name);
  }
  for (const k of Object.keys(rep)) rep[k].sort();
  return [out, rep];
}

/**
 * Merge a set of values from the model into the panels in the graph, and fan them out to all bindings.
 *
 * With several panels, dispatch by name, **duplicates go to the earliest one** -- this must be the same rule as
 * allValues() uses for reading, otherwise you get ghost stories like "written into the later panel, but read from the earlier one".
 */
export function applyIncoming(graph, incoming) {
  if (!incoming || typeof incoming !== "object" || Array.isArray(incoming))
    throw new Error("expected a JSON object ({\"name\": value})");
  const rep = { applied: [], clamped: [], unknown: [], skipped: [],
                panels: 0 };
  const claimed = new Set();
  for (const p of panels(graph)) {
    let specs;
    try { specs = parse(declText(p)); } catch (_) { continue; }  // skip panels with a malformed declaration
    rep.panels++;
    const mine = {};
    for (const s of specs) {
      if (claimed.has(s.name)) continue;
      claimed.add(s.name);
      if (Object.prototype.hasOwnProperty.call(incoming, s.name))
        mine[s.name] = incoming[s.name];
    }
    if (!Object.keys(mine).length) continue;
    const [next, r] = applyValues(specs, valuesOf(p), mine);
    writeValues(p, next);
    syncPanel(p);                      // after the values are written into the store, refresh them onto the widgets
    for (const k of ["applied", "clamped", "skipped"]) rep[k].push(...r[k]);
  }
  for (const k of Object.keys(incoming)) {
    const name = String(k).trim();
    if (!claimed.has(name)) rep.unknown.push(name);
  }
  for (const k of ["applied", "clamped", "unknown", "skipped"]) rep[k].sort();
  return rep;
}

/** Squash the report into one line that fits on the node. All four lists **must appear**, see params.py for why. */
export function reportLine(rep) {
  if (!rep) return "";
  if (!rep.panels) return "no parameter panel in the graph";
  const bits = [`filled ${rep.applied.length}`];
  if (rep.clamped.length) bits.push(`clamped ${rep.clamped.join(",")}`);
  if (rep.unknown.length) bits.push(`no such parameter ${rep.unknown.join(",")}`);
  if (rep.skipped.length) bits.push(`wrong type ${rep.skipped.join(",")}`);
  return bits.join(" · ");
}

// ══════════════════════════════════════════════════════ Context menu
let CLIP = "";                    // clipboard for "Copy Parameter Reference"

function paramNames(graph) {
  const { values } = allValues(graph);
  const out = [];
  for (const [k, v] of Object.entries(values)) {
    out.push(k);
    if (Array.isArray(v))
      for (let i = 0; i < v.length; i++) out.push(`${k}.${"xyzw"[i]}`);
  }
  return out;
}

/** Bindable widgets: the panel's own ones, and ones already promoted to sockets, don't count. */
export function bindableWidgets(node) {
  // Only exclude ones that are **actually wired**. The new frontend (since 1.16) gives every widget an input socket;
  // just checking "is there a matching input" would exclude all widgets and leave the binding menu empty
  const linked = new Set((node.inputs || []).filter((i) => i?.link != null)
    .map((i) => i?.widget?.name).filter((x) => x));
  return (node.widgets || [])
    .filter((w) => w.name && !linked.has(w.name) && w.serialize !== false
                && !String(w.name).startsWith(PREFIX)
                && w.name !== "values" && w.name !== "declare");
}

export function menuFor(node, graph) {
  const items = [];
  if (node.type === NODE_TYPE) {
    const names = paramNames(graph);
    items.push({
      content: "PCG: Copy Parameter Reference",
      has_submenu: true,
      submenu: {
        options: names.map((n) => ({
          content: n, callback: () => { CLIP = n; PCLIP = null; },
        })),
      },
    });
    return items;
  }
  const names = paramNames(graph);
  const ws = bindableWidgets(node);
  if (names.length && ws.length) {
    items.push({
      content: "PCG: Bind Parameter",
      has_submenu: true,
      submenu: {
        options: ws.map((w) => ({
          content: w.name,
          has_submenu: true,
          submenu: {
            options: names.map((n) => ({
              content: n,
              callback: () => { bind(node, w.name, n); applyBindings(graph); },
            })),
          },
        })),
      },
    });
  }
  // Node to node: also works in native widget mode (in the Houdini panel it is the parameter context menu, see pcg_panel.js)
  const all = (node.widgets || []).filter((w) => w.name && !String(w.name).startsWith(PREFIX)
    && w.name !== "values" && w.name !== "declare" && w.name !== "pcg_panel"
    && w.serialize !== false);
  if (all.length) {
    items.push({
      content: "PCG: Copy Parameter",
      has_submenu: true,
      submenu: {
        options: all.map((w) => ({
          content: w.name, callback: () => { copyParams(node, [w.name]); },
        })),
      },
    });
  }
  const clip = clipboard();
  if (clip && ws.length) {
    items.push({
      content: clip.kind === "panel" ? `PCG: Paste Parameter Reference (${clip.text})`
        : `PCG: Paste Relative References (←${clip.text})`,
      has_submenu: true,
      submenu: {
        options: ws.map((w) => ({
          content: w.name,
          callback: () => { pasteRefs(node, [w.name], graph); },
        })),
      },
    });
  }
  // Promote: **append a declaration line** to the panel, name taken from the widget name, value from the current value.
  // This is the equivalent of Houdini's "promote parameter", saving the round trip of "first go write a line on the panel,
  // then come back and bind"
  if (panels(graph).length && ws.length) {
    items.push({
      content: "PCG: Promote to Panel Parameter",
      has_submenu: true,
      submenu: {
        options: ws.map((w) => ({
          content: w.name,
          callback: () => promote(node, w, graph),
        })),
      },
    });
  }
  const b = bindings(node);
  if (b && Object.keys(b).length) {
    items.push({
      content: "PCG: Unbind",
      has_submenu: true,
      submenu: {
        options: Object.keys(b).map((n) => ({
          content: `${n} ←${isExpr(b[n]) ? bindingText(graph, node, n) : refText(graph, b[n])}`,
          callback: () => unbind(node, n),
        })),
      },
    });
  }
  return items;
}

/** widget -> a new declaration line on the panel + binding. Adds a suffix when the name is taken. */
export function promote(node, widget, graph) {
  const panel = panels(graph)[0];
  if (!panel) return false;
  const spec = widgetSpec(node, widget.name);
  const kind = Array.isArray(spec) ? spec[0] : null;
  let type = "float";
  if (Array.isArray(kind) || kind === "STRING" || widget.type === "text")
    type = "string";
  else if (kind === "BOOLEAN" || widget.type === "toggle") type = "bool";
  else if (kind === "INT") type = "int";

  const taken = new Set(Object.keys(allValues(graph).values));
  let name = String(widget.name).replace(/[^A-Za-z0-9_]/g, "_");
  if (/^\d/.test(name)) name = "p" + name;
  let n = name;
  for (let i = 2; taken.has(n); i++) n = `${name}_${i}`;

  const opt = widget.options || {};
  let line = `${type} ${n} = `;
  line += type === "string" ? String(widget.value)
    : (type === "bool" ? (widget.value ? "true" : "false")
      : String(Number(widget.value) || 0));
  if (type !== "string" && type !== "bool"
      && typeof opt.min === "number" && typeof opt.max === "number"
      && Number.isFinite(opt.min) && Number.isFinite(opt.max)
      && Math.abs(opt.max) < 1e9)
    line += ` : ${opt.min} ${opt.max}`;
  const w = widgetNamed(panel, "declare");
  if (!w) return false;
  const txt = String(w.value || "");
  w.value = (txt && !txt.endsWith("\n") ? txt + "\n" : txt) + line + "\n";
  w.callback?.(w.value);
  syncPanel(panel);
  bind(node, widget.name, n);
  applyBindings(graph);
  return n;
}

// ══════════════════════════════════════════════════════ Registration
app.registerExtension({
  name: "pcg.params",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    const isPanel = nodeData?.name === NODE_TYPE;
    if (isPanel) {
      const onCreated = nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated = function () {
        onCreated?.apply(this, arguments);
        const store = widgetNamed(this, "values");
        if (store) {                 // a carrier, should not take up panel space
          store.type = "pcg-hidden";
          store.computeSize = () => [0, -4];
          store.hidden = true;
        }
        const self = this;
        const decl = widgetNamed(this, "declare");
        if (decl) {
          const orig = decl.callback;
          decl.callback = function (v, ...rest) {
            const r = orig?.call(this, v, ...rest);
            syncPanel(self);
            return r;
          };
        }
        setTimeout(() => {
          const el = decl?.inputEl
            || decl?.element?.querySelector?.("textarea");
          if (el) el.addEventListener("input", () => syncPanel(self));
          syncPanel(self);
        }, 0);
      };

      const onConfigure = nodeType.prototype.onConfigure;
      nodeType.prototype.onConfigure = function () {
        onConfigure?.apply(this, arguments);
        // Values are read from the values string, not dependent on widgets_values indices
        setTimeout(() => syncPanel(this), 0);
      };

      // Write declaration errors on the node. Otherwise the symptom is "I added a parameter but it is not on the panel",
      // with the error only in the console
      const onDraw = nodeType.prototype.onDrawForeground;
      nodeType.prototype.onDrawForeground = function (ctx) {
        onDraw?.apply(this, arguments);
        if (!this._pcgErr || this.flags?.collapsed) return;
        ctx.save();
        ctx.fillStyle = "#e0975f";
        ctx.font = "11px ui-monospace, monospace";
        ctx.fillText(String(this._pcgErr).slice(0, 48), 10,
                     this.size[1] - 6);
        ctx.restore();
      };
    }

    if (nodeData?.name === FROM_JSON) {
      // The backend puts the cleanly parsed values into ui (the same onExecuted channel as COP preview and display
      // markers); this side filters names, clamps ranges and writes the panel
      const onExec = nodeType.prototype.onExecuted;
      nodeType.prototype.onExecuted = function (message) {
        onExec?.apply(this, arguments);
        const payload = message?.pcg_params_apply?.[0];
        if (!payload) { this._pcgReport = ""; return; }
        try {
          const rep = applyIncoming(app.graph, payload.values || {});
          applyBindings(app.graph);       // panel -> whole graph, reusing existing bindings
          this._pcgReport = reportLine(rep);
          this._pcgBad = !!(rep.unknown.length || rep.skipped.length
                            || !rep.panels);
          app.canvas?.setDirty?.(true, true);
        } catch (e) {
          this._pcgReport = "error: " + e.message;
          this._pcgBad = true;
        }
        // **Deliberately does not queue a re-run.** Auto re-run + every run changing parameters = an infinite loop, and
        // the kind that looks like it is "working hard". The values are already on the panel; press
        // Run once more to get results from the new values -- this is the inherent cost of frontend materialization
      };

      const onDraw2 = nodeType.prototype.onDrawForeground;
      nodeType.prototype.onDrawForeground = function (ctx) {
        onDraw2?.apply(this, arguments);
        if (!this._pcgReport || this.flags?.collapsed) return;
        ctx.save();
        ctx.fillStyle = this._pcgBad ? "#e0975f" : "#7fb8ff";
        ctx.font = "11px ui-monospace, monospace";
        ctx.fillText(String(this._pcgReport).slice(0, 52), 10,
                     this.size[1] - 6);
        ctx.restore();
      };
    }

    // All nodes: geometry summary / key sent by the backend when a run finishes (for geometry queries in fields, see primeGeo)
    const onExecAll = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      onExecAll?.apply(this, arguments);
      const d = message?.pcg_geoq?.[0];
      if (d) try { primeGeo(this, d); } catch (e) { console.error("[pcg.params] geometry summary", e); }
    };

    // All nodes get the menu -- binding is "right-click on the target node"
    const origMenu = nodeType.prototype.getExtraMenuOptions;
    nodeType.prototype.getExtraMenuOptions = function (canvas, options) {
      origMenu?.apply(this, arguments);
      try {
        const items = menuFor(this, app.graph);
        if (items.length) options.push(null, ...items);
      } catch (e) {
        console.error("[pcg.params] menu error", e);
      }
    };
  },

  async setup() {
    // Materialize once before queueing: the playbar queues right after changing the frame number, without waiting for the next periodic sync -- without evaluating first,
    // `$F` expressions would submit the previous frame's value. queuePrompt goes through app.graphToPrompt; wrap around it
    const g2p = app.graphToPrompt?.bind(app);
    if (g2p) {
      app.graphToPrompt = async function (...args) {
        try {
          for (const p of panels(app.graph)) syncPanel(p);
          applyBindings(app.graph);
        } catch (e) { console.error("[pcg.params] materialize before queueing failed", e); }
        return g2p(...args);
      };
    }
    // Periodic sync: after loading a workflow, undo, or copy-paste, everything must be re-materialized.
    // 400ms is responsive enough (when dragging a slider the callback writes the value immediately anyway), and each pass is only a few dozen
    // number comparisons, with no measurable overhead
    setInterval(() => {
      try {
        for (const p of panels(app.graph)) syncPanel(p);
        const r = applyBindings(app.graph);
        if (r.wrote) app.canvas?.setDirty?.(true, true);
      } catch (e) {
        if (!globalThis.__pcgParamErr) {
          globalThis.__pcgParamErr = true;
          console.error("[pcg.params] sync error", e);
        }
      }
    }, TICK_MS);
  },
});

// unit tests only
export const __internal = { PREFIX, NODE_TYPE, FROM_JSON,
                            setClip: (s) => { CLIP = s; PCLIP = null; },
                            getClip: () => CLIP, C_BOUND,
                            fits, outOfRange, clampOne };
