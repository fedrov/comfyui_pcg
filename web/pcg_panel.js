// comfyui_pcg/web/pcg_panel.js
//
// Houdini-style parameter panel (pcg84).
//
// The native panel has one widget per row, snake_case names, vectors split over three rows, colors as three numbers, ramps as a string of
// text, and parameters irrelevant to the current mode always shown. Here nodes get an HTML panel: tabs / collapsible sections /
// separators, human-readable labels, xyz on one row, color swatch + color picker, draggable ramps, irrelevant parameters hidden by mode
// (Houdini's hidewhen), toggles in front of parameters.
//
// ★ A few constraints (the same kind of lessons as pcg_sections.js / pcg_cop_preview.js):
//
// 1) **Not a single native widget is changed**, they are only hidden. Workflows store widgets_values by index; inserting one
//    shifts everything. The panel is appended with addDOMWidget, serialize = false, placed after the last native widget
//    (before other non-serialized widgets like the COP thumbnail) -- it only moves within the non-serialized tail,
//    so native widget indices don't change. The panel's controls read and write the native widgets' value.
// 2) **Canvas events are not intercepted**. The panel is DOM, events land on it; nothing on the canvas side is changed.
// 3) Layout information all lives on the Python side (derived by panel.py + hand-written in panel_specs.py), arriving with /object_info's
//    options.pcg_ui. This side only draws and interacts, no guessing.
// 4) Values may be changed elsewhere (parameter references pcg_params, undo, loading a workflow) -- every node redraw
//    runs sync() once, reading native widget values back into the panel (except the control being typed in).
// 5) Fallback: Settings -> PCG -> Parameter panel set to "Native"; per node, context menu -> "Parameter panel: use native".
// 6) Linking between parameters (pcg85): right-click a parameter = Houdini's parameter menu -- Copy Parameter / Paste Values /
//    Paste Relative References / Delete Channels / Revert to Defaults. References go through the binding table of pcg_params.js (materialized on the frontend).
//    ComfyUI's native "connect another node's output to a parameter" still works too: drag a link onto a row / field of the panel
//    and it connects to that parameter, with the slot dot aligned to that row; connected fields show "⇠ source" instead of being hidden.
//    Nodes with a code editor (multiline code box) or with custom widgets added by other extensions are not taken over.

import { app } from "../../scripts/app.js";
import { setShown } from "./pcg_sections.js";
import { upstreamNames } from "./pcg_groups.js";
import { bindings, copyParams, clipboard, pasteRefs, pasteValues, unbind, bindingText,
         bindExpr, bindTemplate, applyBindings, promote, panels, isKeys, keysOf, setKey,
         removeKey, onKey, currentFrame } from "./pcg_params.js";
import { isPlainNumber, isTemplate } from "./pcg_hexpr.js";

export const SETTING_ID = "PCG.ParamPanel";
export const MODES = ["Houdini panel", "Native"];
// Values saved by older versions (Chinese UI), still accepted when read
export const LEGACY_MODES = { "Houdini \u9762\u677f": MODES[0], "\u539f\u751f": MODES[1] };
export const UI_KEY = "pcg_ui";
export const PROP_NATIVE = "pcg_native_panel";
const STANDARD = new Set(["number", "combo", "toggle", "text", "string",
                          "customtext", "boolean", "slider", "pcg-collapsed"]);
const ALLOWED_TAIL = new Set(["pcg_cop_preview"]);
const MIN_W = 340;
const MARGIN = 4;

// ════════════════════════════════════════════════════ hidewhen
// Same syntax as parse_cond in panel.py: "{ a == x b != y } { c == 1 }".
// Outer level is OR, inner level is AND. Both sides are tested against the same set of cases (test_panel.py / test_panel.mjs)
const COND_TOK = /"[^"]*"|'[^']*'|==|!=|<=|>=|<|>|[^\s{}<>=!"']+|[{}]/g;
export function parseCond(text) {
  const toks = String(text ?? "").match(COND_TOK) || [];
  const groups = [];
  let cur = null;
  for (let i = 0; i < toks.length;) {
    const t = toks[i];
    if (t === "{") {
      if (cur) throw new Error(`condition '${text}': braces cannot be nested`);
      cur = []; i++;
    } else if (t === "}") {
      if (!cur) throw new Error(`condition '${text}': one } too many`);
      if (!cur.length) throw new Error(`condition '${text}': empty { }`);
      groups.push(cur); cur = null; i++;
    } else {
      if (!cur) throw new Error(`condition '${text}': comparisons must be written inside { }`);
      if (i + 2 >= toks.length || toks[i + 2] === "{" || toks[i + 2] === "}")
        throw new Error(`condition '${text}': '${t}' is missing a comparison or value`);
      const op = toks[i + 1];
      if (!["==", "!=", "<", ">", "<=", ">="].includes(op))
        throw new Error(`condition '${text}': '${op}' is not a comparison operator`);
      let v = toks[i + 2];
      if (v[0] === '"' || v[0] === "'") v = v.slice(1, -1);
      cur.push([t, op, v]);
      i += 3;
    }
  }
  if (cur) throw new Error(`condition '${text}': one } missing`);
  return groups;
}

// Parameter value -> form used for comparison: toggles 1 / 0, everything else as-is
export function condValue(v) {
  if (v === true) return "1";
  if (v === false) return "0";
  return v == null ? "" : String(v);
}

function cmp(a, op, b) {
  const na = Number(a), nb = Number(b);
  const num = a !== "" && b !== "" && Number.isFinite(na) && Number.isFinite(nb);
  const x = num ? na : a, y = num ? nb : b;
  switch (op) {
    case "==": return x === y;
    case "!=": return x !== y;
    case "<": return x < y;
    case ">": return x > y;
    case "<=": return x <= y;
    case ">=": return x >= y;
  }
  return false;
}

// empty groups = no condition = false
export function evalCond(groups, get) {
  return (groups || []).some((conj) =>
    conj.every(([n, op, v]) => cmp(condValue(get(n)), op, v)));
}

// ════════════════════════════════════════════════════ ramp
// "pos:v  pos:v" / "pos:r,g,b  …", consistent with parse in geo/ramp.py (sorted by position,
// on coincidence the earlier one is kept; a single component fills all)
export function parseRamp(text, comps) {
  const toks = String(text ?? "").split(/\s+/).filter(Boolean);
  if (!toks.length) throw new Error("ramp is empty");
  const keys = [];
  for (const t of toks) {
    const i = t.indexOf(":");
    if (i < 0) throw new Error(`'${t}' is missing a colon`);
    const p = Number(t.slice(0, i));
    let v = t.slice(i + 1).split(",").filter((x) => x !== "").map(Number);
    if (!Number.isFinite(p) || !v.length || v.some((x) => !Number.isFinite(x)))
      throw new Error(`'${t}' is not a number`);
    if (v.length === 1 && comps > 1) v = Array(comps).fill(v[0]);
    if (v.length !== comps) throw new Error(`'${t}' needs ${comps} components`);
    keys.push({ p, v });
  }
  keys.sort((a, b) => a.p - b.p);
  return keys.filter((k, i) => i === 0 || k.p - keys[i - 1].p > 1e-12);
}

// ASCII glyph widths of 12px Inter, the same table as _GLYPH_W in panel.py (compared entry by entry in the tests).
// canvas.measureText is not used: jsdom doesn't have it, and this way Python's layout estimate and the frontend's decision use the same numbers
const GLYPH_W = ("3 3 6 8 8 12 8 4 4 4 6 8 3 6 3 4 8 5 7 7 8 7 7 7 7 7 3 4 8 8 8 6 12 8 8 9 9 7 " +
  "7 9 9 3 7 8 7 11 9 9 8 9 8 8 8 9 8 12 8 8 8 4 3 4 6 5 4 7 7 7 7 7 4 7 7 3 3 7 " +
  "3 11 7 7 7 7 5 6 4 7 7 10 7 7 7 5 4 5 8").split(" ").map(Number);
export const GLYPHS = GLYPH_W;
export function textWidth(s) {
  let w = 0;
  for (const ch of String(s)) {
    const c = ch.codePointAt(0);
    w += c >= 32 && c < 127 ? GLYPH_W[c - 32] : 13.4;
  }
  return w;
}
// A toggle's text goes in the value column (Houdini style); at the minimum width of 340 the value column is about 192 px;
// if it doesn't fit (box 13 + gap 5 + text) the whole row starts from the left without a label column, and doesn't wrap --
// wrapping would make the row taller, and make_workflows' height estimate would no longer match
export const CHK_WIDE = 186;
export const wideCheck = (label) => textWidth(label) + 18 > CHK_WIDE;

/** Value written in tooltips: numbers via fmtNum, arrays element by element, others as-is. */
export function fmtVal(v) {
  if (typeof v === "number") return fmtNum(v);
  if (Array.isArray(v)) return v.map(fmtVal).join(" ");
  return String(v);
}

export function fmtNum(x) {
  if (!Number.isFinite(x)) return String(x);
  // Very small numbers (tolerances like 1e-8) are written with significant digits, so they don't get rounded to 0
  if (x !== 0 && Math.abs(x) < 1e-4) return String(Number(x.toPrecision(6)));
  return String(Math.round(x * 1e6) / 1e6);      // String(-0) is "0" anyway
}

export function formatRamp(keys) {
  return [...keys].sort((a, b) => a.p - b.p)
    .map((k) => `${fmtNum(k.p)}:${k.v.map(fmtNum).join(",")}`).join("  ");
}

export function sampleRamp(keys, t, mode) {
  if (!keys.length) return [0];
  t = Math.min(1, Math.max(0, t));
  if (keys.length === 1 || t <= keys[0].p) return keys[0].v.slice();
  const last = keys[keys.length - 1];
  if (t >= last.p) return last.v.slice();
  let i = 0;
  while (i < keys.length - 2 && keys[i + 1].p <= t) i++;
  const a = keys[i], b = keys[i + 1];
  if (mode === "constant") return a.v.slice();
  let s = (t - a.p) / Math.max(b.p - a.p, 1e-12);
  if (mode === "smooth") s = s * s * (3 - 2 * s);
  return a.v.map((x, k) => x + (b.v[k] - x) * s);
}

// ════════════════════════════════════════════════════ model
function specOf(nodeData, name) {
  for (const g of ["required", "optional"]) {
    const s = nodeData?.input?.[g]?.[name];
    if (s) return s;
  }
  return null;
}
export function uiOf(nodeData, name) {
  const s = specOf(nodeData, name);
  return (Array.isArray(s) && s[1] && s[1][UI_KEY]) || null;
}
function optsOf(nodeData, name) {
  const s = specOf(nodeData, name);
  return (Array.isArray(s) && s[1]) || {};
}

// widgetNames: names of the native widgets (original order). Returns {top:[blocks], tabs:[{name, blocks}]}
// block = {section, gate, items:[names]} (section null means loose items)
export function buildModel(nodeData, widgetNames) {
  const names = widgetNames.filter((n) => uiOf(nodeData, n));
  let nodeUi = {};
  for (const n of names) {
    const u = uiOf(nodeData, n);
    if (u && u._node) { nodeUi = u._node; break; }
  }
  const order = [];
  for (const n of nodeUi.order || []) if (names.includes(n) && !order.includes(n)) order.push(n);
  for (const n of names) if (!order.includes(n)) order.push(n);
  const lead = order.filter((n) => {
    const u = uiOf(nodeData, n);
    return !(u.in_row || u.in_toggle || u.in_ramp);
  });
  const top = [], tabs = [];
  const tabOf = new Map();
  for (const n of lead) {
    const u = uiOf(nodeData, n);
    let blocks = top;
    if (u.folder) {
      if (!tabOf.has(u.folder)) {
        const t = { name: u.folder, blocks: [] };
        tabOf.set(u.folder, t); tabs.push(t);
      }
      blocks = tabOf.get(u.folder).blocks;
    }
    const sec = u.section || null;
    let last = blocks[blocks.length - 1];
    if (u.gate && sec && specOf(nodeData, n)?.[0] === "BOOLEAN") {
      // Section-header toggle: opens a new section (even if a section of the same name already exists -- consistent with the native panel).
      // A "section start" that isn't a toggle (COP Noise's time_scale is a number) goes into the section as an ordinary parameter
      blocks.push({ section: sec, gate: n, items: [] });
      continue;
    }
    if (last && last.section === sec) last.items.push(n);
    else {
      last = { section: sec, gate: null, items: [n] };
      blocks.push(last);
    }
  }
  return { top, tabs, order };
}

// ════════════════════════════════════════════════════ styles
const CSS = `
.pcgp-host{overflow:hidden}
.pcgp{font:12px/1.35 Inter,"Segoe UI",system-ui,sans-serif;color:#cfd5dc;
  background:#23262b;border-radius:4px;padding:4px 6px 6px;box-sizing:border-box;
  user-select:none;overflow:hidden}
.pcgp *{box-sizing:border-box}
.pcgp .row{display:flex;align-items:center;min-height:24px;gap:6px;margin:1px 0}
.pcgp .row.hidden{display:none !important}
.pcgp .row.dis{opacity:.42;pointer-events:none}
.pcgp .ref{background:#16332f !important;color:#8fe0cf !important;border-color:#2e6a60 !important;
  pointer-events:none}
.pcgp .lnk{background:#28243d !important;color:#b8a8f0 !important;border-color:#4a4078 !important;
  font-style:italic;pointer-events:none}
.pcgp input.num.ref,.pcgp input.txt.ref{pointer-events:auto;cursor:text}
.pcgp .key:not(.rk){background:#1d3320 !important;color:#a9e59a !important;border-color:#3d6e38 !important}
.pcgp .key.onkey{background:#2f5a26 !important;color:#eaffde !important;border-color:#7fd06a !important}
.pcgp .ref.wait{color:#9fb7b2 !important;font-style:italic}
.pcgp .ref.err{background:#4a2020 !important;color:#ffb0a8 !important;border-color:#a04848 !important}
.pcgp .ref.peek{background:#21564d !important;color:#e8fff9 !important;border-color:#5fe0c8 !important}
.pcgp input[type=checkbox].ref,.pcgp input[type=checkbox].lnk{outline:2px solid #2e6a60;outline-offset:1px}
.pcgp input[type=checkbox].lnk{outline-color:#4a4078}
.pcgp .ramp.ref,.pcgp .ramp.lnk{opacity:.6}
.pcgp .droptgt{outline:2px solid #ffcc00 !important;outline-offset:1px}
.pcgp .lab{flex:0 0 38%;text-align:right;color:#aeb6bf;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;cursor:ew-resize}
.pcgp .lab.plain{cursor:default}
.pcgp .lab input[type=checkbox]{margin:0 4px 0 0;vertical-align:-2px}
.pcgp .val{flex:1 1 auto;display:flex;gap:4px;min-width:0;align-items:center}
.pcgp input.num,.pcgp input.txt,.pcgp select,.pcgp textarea{background:#16181b;
  color:#e3e7eb;border:1px solid #3a3f46;border-radius:3px;height:21px;padding:0 5px;
  font:inherit;min-width:0;outline:none}
.pcgp textarea{height:53px;padding:3px 5px;resize:none;width:100%;line-height:15px;
  font-family:ui-monospace,Consolas,monospace;white-space:pre;overflow:auto}
.pcgp .row.wide textarea{margin-top:1px}
.pcgp input.num{width:100%;text-align:left;cursor:ew-resize}
.pcgp input.num:focus{cursor:text;border-color:#5fa3e0}
.pcgp input.txt{width:100%}
.pcgp input.code{font-family:ui-monospace,Consolas,monospace}
.pcgp select{width:100%;padding:0 2px}
.pcgp .fld{flex:1 1 0;min-width:0;position:relative}
.pcgp .fld.short{flex:0 0 72px}
.pcgp .slider{flex:1 1 auto;height:6px;background:#16181b;border:1px solid #3a3f46;
  border-radius:3px;position:relative;cursor:pointer;min-width:30px}
.pcgp .slider i{position:absolute;left:0;top:0;bottom:0;background:#4b87c2;border-radius:2px}
.pcgp .swatch{flex:0 0 26px;height:19px;border:1px solid #555;border-radius:3px;cursor:pointer}
.pcgp .btn{flex:0 0 auto;height:21px;min-width:21px;padding:0 5px;background:#30343a;
  border:1px solid #454b53;border-radius:3px;color:#cfd5dc;cursor:pointer;font:inherit;
  display:flex;align-items:center;justify-content:center}
.pcgp .btn:hover{background:#3a4048}
.pcgp .chk{display:flex;align-items:center;gap:5px;cursor:pointer;min-width:0}
.pcgp .chk span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pcgp .row.widechk .lab{display:none}
.pcgp .row.widechk .val{padding-left:10px}
.pcgp .sep{height:1px;background:#3a3f46;margin:5px 0 4px}
.pcgp .tabs{display:flex;flex-wrap:wrap;gap:2px;margin:6px 0 0;border-bottom:1px solid #3d434b}
.pcgp .tab{padding:3px 9px;background:#2b2f35;border:1px solid #3d434b;border-bottom:none;
  border-radius:4px 4px 0 0;color:#98a1ab;cursor:pointer}
.pcgp .tab.on{background:#353a41;color:#e6eaee}
.pcgp .tab.hidden{display:none}
.pcgp .tabbody{padding-top:4px}
.pcgp .sec{margin:4px 0 2px;border:1px solid #353a41;border-radius:4px;background:#26292e}
.pcgp .sec.hidden{display:none}
.pcgp .sechd{display:flex;align-items:center;gap:6px;padding:3px 6px;background:#2e3238;
  border-radius:4px;cursor:pointer;color:#dfe4e9}
.pcgp .sechd .arr{width:10px;color:#8e98a3}
.pcgp .sechd input{margin:0}
.pcgp .secbody{padding:2px 4px 3px}
.pcgp .sec.closed .secbody{display:none}
.pcgp .sec.off .sechd{color:#7c858f}
.pcgp .row.wide{display:block}
.pcgp .row.wide .lab{text-align:left;margin:2px 0 3px;cursor:default}
.pcgp .ramp{flex:1 1 auto;display:flex;flex-direction:column;gap:3px;min-width:0}
.pcgp .ramp:focus{outline:none}
.pcgp .ramp:focus .rarea{border-color:#6d8fb3}
.pcgp .ramp .rarea{position:relative;border:1px solid #3a3f46;border-radius:3px;cursor:copy;
  margin:0 6px;touch-action:none}
.pcgp .ramp.flt .rarea{height:96px;margin-top:5px;margin-bottom:5px}
.pcgp .ramp.col .rarea{height:30px}
.pcgp .ramp canvas{width:100%;height:100%;display:block;border-radius:2px}
.pcgp .ramp .idx{position:absolute;left:4px;top:2px;font-size:10px;color:#9aa3ad;pointer-events:none;
  text-shadow:0 0 2px #000,0 0 2px #000}
.pcgp .ramp .pts{position:absolute;inset:0;pointer-events:none}
.pcgp .ramp .keys{position:relative;height:16px;margin:0 7px;cursor:copy;touch-action:none}
.pcgp .ramp .key{position:absolute;cursor:grab;pointer-events:auto;touch-action:none}
.pcgp .ramp .key:active{cursor:grabbing}
.pcgp .ramp .pts .key{box-sizing:border-box;width:11px;height:11px;margin:-5.5px 0 0 -5.5px;border-radius:50%;
  background:#e4ebf2;border:1.5px solid #14161a;box-shadow:0 0 0 1px #8cc4f5}
.pcgp .ramp .pts .key:hover{background:#fff;box-shadow:0 0 0 2px #8cc4f5}
.pcgp .ramp .pts .key.sel{background:#f0c34f;box-shadow:0 0 0 2px #fff;z-index:1}
.pcgp .ramp .keys .key{top:0;width:11px;height:15px;margin-left:-5.5px;background:#aeb6bf;
  clip-path:polygon(50% 0,100% 36%,100% 100%,0 100%,0 36%)}
.pcgp .ramp .keys .key::after{content:"";position:absolute;left:2px;right:2px;top:6px;bottom:2px;background:var(--c,#888)}
.pcgp .ramp .keys .key:hover{background:#fff}
.pcgp .ramp .keys .key.sel{background:#f0c34f;z-index:1}
.pcgp .ramp .kline{display:flex;gap:4px;align-items:center}
.pcgp .ramp .err{color:#e0975f}
.pcgp .note{color:#e0975f;font-size:11px}
`;
function injectCss() {
  if (document.getElementById("pcg-panel-css")) return;
  const st = document.createElement("style");
  st.id = "pcg-panel-css";
  st.textContent = CSS;
  document.head.appendChild(st);
}

function el(tag, cls, parent) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (parent) parent.appendChild(e);
  return e;
}

const rafOr = (f) => (globalThis.requestAnimationFrame ? globalThis.requestAnimationFrame(f) : setTimeout(f, 16));

/**
 * The system color picker (Chrome's <input type=color> popup) fires input on every mousemove while dragging, several per frame.
 * Wrapped: the first is handled immediately (a click / a single event in tests stays synchronous); later ones in the same frame only note "there's a new one",
 * and the next frame handles it once with the **latest** value -- at most once per frame, and the last value always lands.
 */
export function perFrame(fn) {
  let armed = false, pending = null;
  const tick = () => {
    if (!pending) { armed = false; return; }
    const a = pending;
    pending = null;
    fn(...a);
    rafOr(tick);
  };
  return function (...a) {
    if (armed) { pending = a; return; }
    fn(...a);
    armed = true;
    rafOr(tick);
  };
}

function rgbHex(v) {
  const h = (x) => Math.round(Math.min(1, Math.max(0, x)) * 255)
    .toString(16).padStart(2, "0");
  return "#" + h(v[0] ?? 0) + h(v[1] ?? 0) + h(v[2] ?? 0);
}
function hexRgb(h) {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(h || "");
  return m ? [1, 2, 3].map((i) => parseInt(m[i], 16) / 255) : [0, 0, 0];
}

// Number fields accept simple arithmetic like "1/3", "2*pi" (Houdini's parameter fields accept expressions too)
export function evalNumber(text) {
  const s = String(text).trim();
  if (s === "") return NaN;
  const n = Number(s);
  if (Number.isFinite(n)) return n;
  if (!/^[\d\s.+\-*/()eEpi]+$/.test(s)) return NaN;
  try {
    const v = Function("pi", `"use strict";return (${s});`)(Math.PI);
    return typeof v === "number" ? v : NaN;
  } catch (e) {
    return NaN;
  }
}

// ════════════════════════════════════════════════════ panel
export class Panel {
  constructor(node, nodeData, deps = {}) {
    this.node = node;
    this.nd = nodeData;
    this.deps = deps;
    this.widgets = new Map();
    for (const w of node.widgets || []) this.widgets.set(w.name, w);
    this.controls = [];          // {name, set(value), focusEl}
    this.rows = [];              // {el, hide, disable, names}
    this.sections = [];          // {el, gate, items, names}
    this.tabBtns = [];
    this.closed = new Set();     // sections collapsed by hand
    this.tab = 0;
    // Referenced fields show the expression ch("../source/param") by default (same as Houdini); those switched to show the value by clicking the label go here,
    // those temporarily showing the value while the middle button is held go into peek (they revert on release)
    this.showVal = new Set();
    this.peek = new Set();
    // The outer element is sized by the frontend (it hard-codes the height on the element), the inner holds the content -- measure the inner,
    // otherwise scrollHeight is never smaller than the outer's hard-coded height, and the node can't shrink back when rows are hidden
    this.root = el("div", "pcgp-host");
    this.inner = el("div", "pcgp", this.root);
    this.build();
    this.inner.addEventListener("pointerdown", (e) => this.peekDown(e), true);
    this.inner.addEventListener("pointerdown", (e) => this.altKey(e), true);
    // The default action of a middle-button press is the browser's autoscroll; the canvas also uses the middle button to drag. Neither is wanted on a referenced field
    this.inner.addEventListener("mousedown", (e) => {
      if (e.button === 1 && this.refNamesAt(e.clientX, e.clientY).length) {
        e.preventDefault();
        e.stopPropagation();
      }
    }, true);
  }

  ui(n) { return uiOf(this.nd, n) || {}; }
  opts(n) { return optsOf(this.nd, n); }
  get(n) { return this.widgets.get(n)?.value; }

  set(n, v) {
    const w = this.widgets.get(n);
    if (!w) return;
    if (isKeys(this.bound(n))) {           // keyframed parameter: changing the value = setting a key at the current frame (auto key)
      const g = this.graph();
      if (Number.isFinite(Number(v)) && setKey(g, this.node, n, currentFrame(g), Number(v))) {
        this.node.setDirtyCanvas?.(true, true);
        if (!this._hold) this.refresh();
      }
      return;
    }
    const o = this.opts(n);
    const t = specOf(this.nd, n)?.[0];
    if (t === "INT" || t === "FLOAT") {
      v = Number(v);
      if (!Number.isFinite(v)) return;
      if (t === "INT") v = Math.round(v);
      if (o.min !== undefined) v = Math.max(o.min, v);
      if (o.max !== undefined) v = Math.min(o.max, v);
    }
    const old = w.value;
    if (old === v) return;
    w.value = v;
    try { w.callback?.(v, app.canvas, this.node, [0, 0], null); } catch (e) { /* */ }
    try { this.node.onWidgetChanged?.(n, v, old, w); } catch (e) { /* */ }
    this.node.setDirtyCanvas?.(true, true);
    if (!this._hold) this.refresh();
  }

  /** Change several parameters at once (r g b from the color picker): values written one by one, the panel refreshed only once. */
  setMany(pairs) {
    this._hold = (this._hold || 0) + 1;
    try { for (const [n, v] of pairs) this.set(n, v); } finally {
      if (--this._hold === 0) this.refresh();
    }
  }

  linked(n) {
    return (this.node.inputs || []).some((i) =>
      (i.widget?.name === n || i.name === n) && i.link != null);
  }

  // ── building ──────────────────────────────────────────────────────
  build() {
    this.buildBody();
    // Each control is tagged with which parameter it writes: the context menu, link drop targets and slot-dot alignment all find fields through it
    for (const c of this.controls)
      if (c.el && c.name && !c.el.dataset.w) c.el.dataset.w = c.name;
    this.refresh();
  }

  buildBody() {
    const m = buildModel(this.nd, [...this.widgets.keys()]);
    this.model = m;
    this.renderBlocks(m.top, this.inner);
    if (m.tabs.length) {
      const bar = el("div", "tabs", this.inner);
      const bodies = [];
      m.tabs.forEach((t, i) => {
        const b = el("div", "tab", bar);
        b.textContent = t.name;
        b.onclick = () => { this.tab = i; this.showTab(); };
        const body = el("div", "tabbody", this.inner);
        this.renderBlocks(t.blocks, body);
        this.tabBtns.push({ btn: b, body, names: t.blocks.flatMap((x) => x.items) });
        bodies.push(body);
      });
      this.showTab();
    }
  }

  showTab() {
    const vis = this.tabBtns.filter((t) => !t.btn.classList.contains("hidden"));
    if (vis.length && !vis.includes(this.tabBtns[this.tab]))
      this.tab = this.tabBtns.indexOf(vis[0]);
    this.tabBtns.forEach((t, i) => {
      t.btn.classList.toggle("on", i === this.tab);
      t.body.style.display = i === this.tab ? "" : "none";
    });
    this.resize();
  }

  renderBlocks(blocks, parent) {
    for (const b of blocks) {
      if (!b.section) {
        for (const n of b.items) this.renderItem(n, parent);
        continue;
      }
      const sec = el("div", "sec", parent);
      const hd = el("div", "sechd", sec);
      const arr = el("span", "arr", hd);
      let gateBox = null;
      if (b.gate) {
        gateBox = el("input", "", hd);
        gateBox.type = "checkbox";
        gateBox.title = this.ui(b.gate).label || b.gate;
        gateBox.onclick = (e) => e.stopPropagation();
        gateBox.onchange = () => {
          this.set(b.gate, gateBox.checked);
          if (gateBox.checked) this.closed.delete(sec);
        };
        this.controls.push({ name: b.gate, el: gateBox,
                             set: (v) => { gateBox.checked = v !== false; } });
        hd.addEventListener("contextmenu", (e) => this.paramMenu(e, [b.gate]));
      }
      const title = el("span", "", hd);
      title.textContent = b.section;
      const body = el("div", "secbody", sec);
      hd.onclick = () => {
        if (this.closed.has(sec)) this.closed.delete(sec); else this.closed.add(sec);
        this.refresh();
      };
      for (const n of b.items) this.renderItem(n, body);
      this.sections.push({ el: sec, arr, gate: b.gate, names: b.items,
                           rows: [], hideGate: this.cond(b.gate, "hide") });
    }
  }

  cond(n, key) {
    const t = n ? this.ui(n)[key] : null;
    if (!t) return null;
    try { return parseCond(t); } catch (e) { console.warn("[pcg.panel]", e.message); return null; }
  }

  addRow(names, parent, label, opts = {}) {
    const row = el("div", "row", parent);
    const u = this.ui(names[0]);
    if (u.sep) {
      const s = el("div", "sep");
      parent.insertBefore(s, row);
      opts.sepEl = s;
    }
    const lab = el("div", "lab" + (opts.plainLabel ? " plain" : ""), row);
    if (label !== null) { lab.textContent = label; lab.title = label; }
    if (u.help || this.opts(names[0]).tooltip)
      row.title = u.help || this.opts(names[0]).tooltip;
    const val = el("div", "val", row);
    const r = { el: row, sep: opts.sepEl, names, lab,
                hide: this.cond(names[0], "hide"), disable: this.cond(names[0], "disable") };
    this.rows.push(r);
    row.addEventListener("contextmenu", (e) => this.rowMenu(e, r));
    // Clicking the label: a referenced field toggles between expression / value (Houdini's clicking the parameter name). Clicks on the checkbox inside the label don't count
    lab.addEventListener("click", (e) => {
      if (e.target?.tagName !== "INPUT") this.toggleExpr(r.names);
    });
    return { row, lab, val, r };
  }

  renderItem(n, parent) {
    const u = this.ui(n);
    const spec = specOf(this.nd, n);
    const t = spec?.[0];
    const label = u.label || n;
    if (u.row) return this.renderRow(n, u, parent);
    if (u.kind === "ramp") return this.renderRamp(n, u, parent);
    if (t === "BOOLEAN") {
      const { row, val } = this.addRow([n], parent, "", { plainLabel: true });
      if (wideCheck(label)) row.classList.add("widechk");
      const c = el("label", "chk", val);
      const box = el("input", "", c);
      box.type = "checkbox";
      const sp = el("span", "", c);
      sp.textContent = label;
      sp.title = label;
      box.onchange = () => this.set(n, box.checked);
      this.controls.push({ name: n, el: box, set: (v) => { box.checked = !!v; } });
      return;
    }
    const names = u.toggle ? [n, u.toggle] : [n];
    const { lab, val } = this.addRow(names, parent, u.toggle ? "" : label,
                                     { plainLabel: t !== "INT" && t !== "FLOAT" });
    if (u.toggle) {
      const box = el("input", "", lab);
      box.type = "checkbox";
      el("span", "", lab).textContent = label;
      lab.classList.add("plain");
      box.onchange = () => this.set(u.toggle, box.checked);
      this.controls.push({ name: u.toggle, el: box, set: (v) => { box.checked = !!v; } });
      this.rows[this.rows.length - 1].toggleOff = () => this.get(u.toggle) === false;
    }
    this.renderValue(n, u, val, lab);
  }

  renderValue(n, u, val, lab) {
    const spec = specOf(this.nd, n);
    const t = spec?.[0];
    const o = this.opts(n);
    if (Array.isArray(t)) {
      const sel = el("select", "", val);
      for (const tok of t) {
        const op = el("option", "", sel);
        op.value = String(tok);
        op.textContent = (u.menu && u.menu[String(tok)]) || String(tok);
      }
      sel.onchange = () => {
        const tok = t.find((x) => String(x) === sel.value);
        this.set(n, tok === undefined ? sel.value : tok);
      };
      this.controls.push({ name: n, el: sel, set: (v) => { sel.value = String(v); } });
      return;
    }
    if (t === "INT" || t === "FLOAT") {
      this.numField(n, val, lab, { slider: this.wantSlider(n, u) });
      return;
    }
    if (u.kind === "vecstr" || u.kind === "colorstr") return this.vecStr(n, u, val);
    if (u.kind === "text" || (o.multiline && u.kind !== "code")) {
      val.parentElement?.classList.add("wide");   // multiline text takes the whole row, with the label above
      const ta = el("textarea", "", val);
      ta.spellcheck = false;
      // Grows with line count (3 ~ 24 lines), so code boxes don't need resizing by hand
      const fit = () => {
        const lines = String(ta.value).split("\n").length;
        const rows = Math.min(24, Math.max(3, lines + 1));
        const px = rows * 15 + 8;
        if (ta.style.height !== px + "px") { ta.style.height = px + "px"; this.resize(true); }
      };
      ta.oninput = fit;
      ta.onchange = () => this.set(n, ta.value);
      ta.onkeydown = (e) => {
        if (e.key === "Tab") {             // Tab indents instead of moving focus
          e.preventDefault();
          const a = ta.selectionStart, z = ta.selectionEnd;
          ta.value = ta.value.slice(0, a) + "    " + ta.value.slice(z);
          ta.selectionStart = ta.selectionEnd = a + 4;
        }
      };
      this.controls.push({ name: n, el: ta, set: (v) => { ta.value = v ?? ""; fit(); } });
      return;
    }
    const inp = el("input", "txt" + (u.kind === "code" ? " code" : ""), val);
    inp.spellcheck = false;
    if (u.kind === "code") {
      inp.onchange = () => this.set(n, inp.value);
    } else {
      // String fields (same as Houdini): with backticks or $variables they are stored as a template (`$OS_$F4`, `` `chs("../a/s")` ``),
      // expanded at each materialization; plain text is an ordinary value (replacing any previous template / reference)
      inp.addEventListener("focus", () => {
        const had = this.bound(n) !== undefined && !this.linked(n);
        inp.dataset.shown = had ? this.exprOf(n) : "";
        if (had) inp.value = inp.dataset.shown;
      });
      inp.addEventListener("blur", () => setTimeout(() => this.markRefs(), 0));
      inp.onchange = () => {
        const text = inp.value;
        const had = this.bound(n) !== undefined;
        if (had && text === inp.dataset.shown) { this.markRefs(); return; }
        if (isTemplate(text)) {
          bindTemplate(this.node, n, text, this.graph());
          this.showVal.delete(n);
          this.refresh();
          this.node.setDirtyCanvas?.(true, true);
          return;
        }
        if (had) unbind(this.node, n);
        this.set(n, text);
        this.refresh();
      };
    }
    inp.onkeydown = (e) => {
      if (e.key === "Enter") inp.blur();
      if (e.key === "Escape" && u.kind !== "code") {
        inp.value = this.bound(n) !== undefined ? inp.dataset.shown : (this.get(n) ?? "");
        inp.blur();
      }
    };
    this.controls.push({ name: n, el: inp, set: (v) => { inp.value = v ?? ""; } });
    if (u.kind === "group" || u.kind === "names") {
      const b = el("button", "btn", val);
      b.textContent = "▾";
      b.title = u.kind === "group" ? "Pick an upstream group" : "Pick an upstream attribute";
      b.onclick = (e) => this.pickName(n, u, e);
    }
  }

  wantSlider(n, u) {
    if (u.slider === false) return false;
    const o = this.opts(n);
    if (u.slider === true) return true;
    if (o.min === undefined || o.max === undefined) return false;
    const span = o.max - o.min;
    return span > 0 && span <= 1000;
  }

  numField(n, parent, lab, { slider = false, short = false } = {}) {
    const box = el("div", "fld" + (slider || short ? " short" : ""), parent);
    const inp = el("input", "num", box);
    inp.spellcheck = false;
    const spec = specOf(this.nd, n);
    const isInt = spec?.[0] === "INT";
    const o = this.opts(n);
    const step = isInt ? 1 : (o.step || 0.01);
    // Committing typed text (Houdini's rules): a plain number = set the value, replacing any expression / reference; anything else is stored as an expression
    // (`ch("../grid1/rows")*2`, `sin($F*10)`, `2*pi` all are), the value computed by the frontend and written in.
    // Malformed ones are stored too: the field turns red and the value doesn't change. Enter without changes = do nothing (won't rewrite the reference)
    const commit = () => {
      const text = inp.value.trim();
      const had = this.bound(n) !== undefined;
      if (had && text === inp.dataset.shown) { this.markRefs(); return; }
      if (isPlainNumber(text)) {
        if (isKeys(this.bound(n))) { this.set(n, Number(text)); return; }   // keyframed: set at the current frame
        if (had) unbind(this.node, n);
        this.set(n, Number(text));
        this.refresh();
        return;
      }
      if (!text) {                          // cleared = no change
        inp.value = had ? this.exprOf(n) : fmtNum(this.get(n));
        return;
      }
      bindExpr(this.node, n, text, this.graph());
      this.showVal.delete(n);
      this.refresh();
      this.node.setDirtyCanvas?.(true, true);
    };
    inp.onchange = commit;
    // Clicking into a referenced field: whether it currently shows the value or the expression, you edit the expression
    inp.addEventListener("focus", () => {
      const b = this.bound(n);
      const had = b !== undefined && !this.linked(n) && !isKeys(b);   // keyframed fields edit the value
      inp.dataset.shown = had ? this.exprOf(n) : isKeys(b) ? fmtNum(this.get(n)) : "";
      if (had) { inp.value = inp.dataset.shown; inp.select(); }
    });
    inp.addEventListener("blur", () => setTimeout(() => this.markRefs(), 0));
    inp.onkeydown = (e) => {
      if (e.key === "Enter") { commit(); inp.blur(); }
      if (e.key === "Escape") {               // abandon this edit
        inp.value = this.bound(n) !== undefined ? inp.dataset.shown : fmtNum(this.get(n));
        inp.blur();
      }
      if ((e.key === "ArrowUp" || e.key === "ArrowDown") && this.bound(n) !== undefined
          && !isKeys(this.bound(n))) {
        e.preventDefault();                   // an expression's value is computed; arrow keys can't nudge it
        return;
      }
      if (e.key === "ArrowUp" || e.key === "ArrowDown") {
        e.preventDefault();
        const k = (e.shiftKey ? 10 : 1) * (e.ctrlKey ? 0.1 : 1) * step;
        this.set(n, Number(this.get(n)) + (e.key === "ArrowUp" ? k : -k));
      }
    };
    // Press and drag left/right on a number field = nudge the value (a simplified Houdini ladder); without dragging it's a click to type
    const scrub = (target) => {
      target.addEventListener("pointerdown", (e) => {
        if (e.button !== 0 || document.activeElement === inp) return;
        if (this.bound(n) && !this.linked(n) && !isKeys(this.bound(n))) return;   // the value comes from a reference and can't be nudged
        const x0 = e.clientX, v0 = Number(this.get(n)) || 0;
        let moved = false;
        const mv = (ev) => {
          const dx = ev.clientX - x0;
          if (!moved && Math.abs(dx) < 3) return;
          moved = true;
          const k = (ev.shiftKey ? 10 : 1) * (ev.ctrlKey ? 0.1 : 1) * step;
          this.set(n, v0 + Math.round(dx / 2) * k);
        };
        const up = () => {
          window.removeEventListener("pointermove", mv);
          window.removeEventListener("pointerup", up);
          if (!moved && target === inp) { inp.focus(); inp.select(); }
        };
        window.addEventListener("pointermove", mv);
        window.addEventListener("pointerup", up);
        e.preventDefault();
      });
    };
    scrub(inp);
    if (lab && !lab.classList.contains("plain")) scrub(lab);
    let fill = null;
    if (slider) {
      const s = el("div", "slider", parent);
      fill = el("i", "", s);
      const setFrom = (ev) => {
        const r = s.getBoundingClientRect();
        const f = Math.min(1, Math.max(0, (ev.clientX - r.left) / Math.max(r.width, 1)));
        this.set(n, o.min + f * (o.max - o.min));
      };
      s.addEventListener("pointerdown", (e) => {
        setFrom(e);
        const mv = (ev) => setFrom(ev);
        const up = () => {
          window.removeEventListener("pointermove", mv);
          window.removeEventListener("pointerup", up);
        };
        window.addEventListener("pointermove", mv);
        window.addEventListener("pointerup", up);
        e.preventDefault();
      });
    }
    this.controls.push({
      name: n, el: inp,
      set: (v) => {
        inp.value = fmtNum(Number(v));
        if (fill) fill.style.width =
          `${Math.min(100, Math.max(0, (Number(v) - o.min) / (o.max - o.min) * 100))}%`;
      },
    });
    return inp;
  }

  renderRow(n, u, parent) {
    const r = u.row;
    const mem = (r.members || [n]).filter((m) => this.widgets.has(m));
    const { lab, val } = this.addRow(mem, parent, r.label || u.label || n);
    if (r.kind === "color") {
      const sw = el("div", "swatch", val);
      const pick = el("input", "", val);
      pick.type = "color";
      pick.style.cssText = "position:absolute;opacity:0;width:0;height:0;pointer-events:none";
      sw.onclick = () => {
        pick.value = rgbHex(mem.map((m) => Number(this.get(m))));
        pick.click();
      };
      pick.oninput = perFrame(() => {
        const c = hexRgb(pick.value);
        this.setMany(mem.slice(0, 3).map((m, i) => [m, c[i]]));
      });
      this.controls.push({ name: mem[0], set: () => {
        sw.style.background = rgbHex(mem.map((m) => Number(this.get(m))));
      } });
      for (const m of mem.slice(1)) this.controls.push({ name: m, set: () => {
        sw.style.background = rgbHex(mem.map((x) => Number(this.get(x))));
      } });
    }
    mem.forEach((m, i) => this.numField(m, val, i === 0 ? lab : null));
  }

  vecStr(n, u, val) {
    const k = u.comps || 2;
    const fields = [];
    let sw = null, pick = null;
    const read = () => String(this.get(n) ?? "").trim().split(/\s+/).map(Number);
    const write = (arr) => this.set(n, arr.map(fmtNum).join(" "));
    if (u.kind === "colorstr") {
      sw = el("div", "swatch", val);
      pick = el("input", "", val);
      pick.type = "color";
      pick.style.cssText = "position:absolute;opacity:0;width:0;height:0;pointer-events:none";
      sw.onclick = () => { pick.value = rgbHex(read()); pick.click(); };
      pick.oninput = perFrame(() => write(hexRgb(pick.value)));
    }
    for (let i = 0; i < k; i++) {
      const f = el("div", "fld", val);
      const inp = el("input", "num", f);
      inp.onchange = () => {
        const a = read();
        while (a.length < k) a.push(0);
        const v = evalNumber(inp.value);
        if (Number.isFinite(v)) { a[i] = v; write(a); }
      };
      inp.onkeydown = (e) => { if (e.key === "Enter") inp.blur(); };
      fields.push(inp);
    }
    this.controls.push({ name: n, el: fields[0], set: () => {
      const a = read();
      fields.forEach((f, i) => {
        if (document.activeElement !== f) f.value = Number.isFinite(a[i]) ? fmtNum(a[i]) : "";
      });
      if (sw) sw.style.background = rgbHex(a);
    } });
  }

  pickName(n, u, e) {
    const [kind, cls] = u.kind === "group" ? ["group", null] : (u.names || ["attrib", null]);
    let list = [];
    try { list = (this.deps.names || upstreamNames)(this.node, kind, cls) || []; } catch (x) { /* */ }
    const LG = globalThis.LiteGraph;
    const items = list.length
      ? list.map((x) => ({ content: cls ? x.n : `${x.c}: ${x.n}`,
                           callback: () => this.set(n, x.n) }))
      : [{ content: "Upstream has not run yet (run the whole chain once, then pick)", disabled: true }];
    if (LG?.ContextMenu) new LG.ContextMenu(items, { event: e, title: u.label || n });
    return items;
  }

  // ── ramp ─────────────────────────────────────────────────────
  // Houdini's ramp parameters:
  //   float ramp -- a tall curve area, **each control point drawn on the curve**, grab to drag up/down/left/right (left/right = position, up/down = value)
  //   color ramp -- a color band with a row of colored markers below, dragged left/right; double-click a marker to pick a color
  // Shared by both: clicking empty space adds a point and drags it right away; right-click / Delete removes; ← → changes the selected point;
  // top-left shows "index / total"; the bottom row is the selected point's position + value (+ interpolation).
  // Control points are DOM elements layered over the canvas (not drawn into the canvas): hover highlight, grabbing and tooltips are the browser's job,
  // the canvas only draws the curve / color band. While dragging, elements are only moved, not rebuilt (rebuilding would drop the one being dragged).
  renderRamp(n, u, parent) {
    const comps = u.ramp?.comps || 1;
    const isColor = comps >= 3;
    const interp = u.ramp?.interp;
    const { row, val } = this.addRow([n], parent, u.label || n, { plainLabel: true });
    row.classList.add("wide");          // the ramp takes the full row width, with the label above
    const box = el("div", "ramp " + (isColor ? "col" : "flt"), val);
    box.dataset.w = n;
    box.tabIndex = 0;                   // focusable: so Delete / ← → have somewhere to land
    const area = el("div", "rarea", box);
    const cv = el("canvas", "", area);
    const idx = el("div", "idx", area);
    const keysEl = el("div", isColor ? "keys" : "pts", isColor ? box : area);
    const line = el("div", "kline", box);
    const err = el("div", "err", box);
    const st = { keys: [], sel: 0, text: null, els: [], rng: null };
    this.ramps = this.ramps || [];
    const mode = () => (interp ? String(this.get(interp)) : "linear");
    const commit = () => this.set(n, formatRamp(st.keys));
    const clamp01 = (x) => Math.min(1, Math.max(0, x));
    const pct = (x) => `${Math.round(x * 1e5) / 1e3}%`;
    const r3 = (x) => Math.round(x * 1000) / 1000;      // dragged numbers rounded to thousandths (0.2500 rather than 0.2487...)
    // Vertical range shown by a float ramp: at least 0 ~ 1, stretched when values go beyond. Frozen while dragging (st.rng), otherwise the point would chase the range
    const range = () => {
      if (st.rng) return st.rng;
      const vs = st.keys.map((k) => k.v[0]);
      return { lo: Math.min(0, ...vs), hi: Math.max(1, ...vs) };
    };

    // The currently selected key: position + value
    const posBox = el("div", "fld short", line);
    const pos = el("input", "num", posBox);
    pos.title = "Position (0 ~ 1)";
    const vals = [];
    let sw = null, pick = null;
    if (isColor) {
      sw = el("div", "swatch", line);
      pick = el("input", "", line);
      pick.type = "color";
      pick.style.cssText = "position:absolute;opacity:0;width:0;height:0;pointer-events:none";
      sw.onclick = () => { pick.value = rgbHex(st.keys[st.sel]?.v || [0, 0, 0]); pick.click(); };
      pick.oninput = perFrame(() => {
        const k = st.keys[st.sel];
        if (k) { k.v = hexRgb(pick.value); commit(); }
      });
    }
    for (let i = 0; i < comps; i++) {
      const f = el("div", "fld", line);
      const inp = el("input", "num", f);
      inp.title = isColor ? "RGB"[i] : "Value";
      inp.onchange = () => {
        const k = st.keys[st.sel];
        const v = evalNumber(inp.value);
        if (k && Number.isFinite(v)) { k.v[i] = v; commit(); }
      };
      vals.push(inp);
    }
    const resort = (k) => {
      st.keys.sort((a, b) => a.p - b.p);
      st.sel = st.keys.indexOf(k);
    };
    pos.onchange = () => {
      const k = st.keys[st.sel];
      const v = evalNumber(pos.value);
      if (k && Number.isFinite(v)) {
        k.p = clamp01(v);
        resort(k);
        commit();
      }
    };
    const remove = (i) => {
      if (st.keys.length <= 1) return;          // keep at least one point
      st.keys.splice(i, 1);
      st.sel = Math.max(0, i - 1);
      commit();
    };
    const del = el("button", "btn", line);
    del.textContent = "✕";
    del.title = "Delete the selected point (you can also right-click the point, or select it and press Delete)";
    del.onclick = () => remove(st.sel);
    let sel = null;
    if (interp) {
      sel = el("select", "", line);
      sel.style.flex = "0 0 78px";
      const t = specOf(this.nd, interp)?.[0] || [];
      const im = this.ui(interp).menu || {};
      for (const tok of t) {
        const op = el("option", "", sel);
        op.value = String(tok);
        op.textContent = im[String(tok)] || String(tok);
      }
      sel.title = "Interpolation";
      sel.onchange = () => this.set(interp, sel.value);
    }

    const draw = () => {
      const W = Math.max(40, Math.round(cv.clientWidth || 200));
      const H = Math.max(8, Math.round(cv.clientHeight || (isColor ? 30 : 96)));
      cv.width = W; cv.height = H;
      const g = cv.getContext?.("2d");
      if (!g) return;
      g.fillStyle = "#16181b";
      g.fillRect(0, 0, W, H);
      if (!st.keys.length) return;
      if (isColor) {
        for (let x = 0; x < W; x++) {
          g.fillStyle = rgbHex(sampleRamp(st.keys, x / (W - 1), mode()));
          g.fillRect(x, 0, 1, H);
        }
        return;
      }
      const { lo, hi } = range();
      const Y = (v) => (1 - (v - lo) / (hi - lo)) * (H - 1);
      g.strokeStyle = "#262a2f";                      // grid: quarters; the 0 and 1 lines a bit brighter (so you can see where 0 ~ 1 is when the range is stretched)
      g.lineWidth = 1;
      g.beginPath();
      for (let q = 1; q < 4; q++) {
        const x = Math.round(q * (W - 1) / 4) + 0.5, y = Math.round(q * (H - 1) / 4) + 0.5;
        g.moveTo(x, 0); g.lineTo(x, H);
        g.moveTo(0, y); g.lineTo(W, y);
      }
      g.stroke();
      g.strokeStyle = "#3a4048";
      g.beginPath();
      for (const v of [0, 1]) { const y = Math.round(Y(v)) + 0.5; g.moveTo(0, y); g.lineTo(W, y); }
      g.stroke();
      g.beginPath();
      g.moveTo(0, H);
      for (let x = 0; x < W; x++) g.lineTo(x, Y(sampleRamp(st.keys, x / (W - 1), mode())[0]));
      g.lineTo(W, H);
      g.closePath();
      g.fillStyle = "rgba(95,163,224,0.28)";
      g.fill();
      g.beginPath();
      for (let x = 0; x < W; x++) {
        const y = Y(sampleRamp(st.keys, x / (W - 1), mode())[0]);
        if (x) g.lineTo(x, y); else g.moveTo(x, y);
      }
      g.strokeStyle = "#8cc4f5";
      g.lineWidth = 1.5;
      g.stroke();
    };
    /** Put each control point's element at its current position (without rebuilding). */
    const place = () => {
      const { lo, hi } = range();
      st.keys.forEach((k, i) => {
        const m = st.els[i];
        if (!m) return;
        m.classList.toggle("sel", i === st.sel);
        m.style.left = pct(k.p);
        if (isColor) m.style.setProperty("--c", rgbHex(k.v));
        else m.style.top = pct(1 - (k.v[0] - lo) / (hi - lo));
        m.title = `#${i + 1}  position ${fmtNum(r3(k.p))}  value ${k.v.map((x) => fmtNum(r3(x))).join(", ")}`
          + `\nDrag: ${isColor ? "change position; double-click to pick a color" : "left/right changes position, up/down changes value"}; right-click / Delete to delete`;
      });
      idx.textContent = st.keys.length ? `${st.sel + 1} / ${st.keys.length}` : "";
    };
    /** Grab a point and drag. The value is written once on release (click without drag, or dragged back to where it was: text unchanged, set itself won't change anything). */
    const drag = (k) => {
      box.focus?.({ preventScroll: true });
      const r = area.getBoundingClientRect();
      st.rng = range();
      const mv = (ev) => {
        k.p = r3(clamp01((ev.clientX - r.left) / Math.max(r.width, 1)));
        if (!isColor) {
          const t = clamp01(1 - (ev.clientY - r.top) / Math.max(r.height, 1));
          k.v[0] = r3(st.rng.lo + t * (st.rng.hi - st.rng.lo));
        }
        fillLine(); place(); draw();
      };
      const up = () => {
        window.removeEventListener("pointermove", mv);
        window.removeEventListener("pointerup", up);
        st.rng = null;
        resort(k);
        commit();
      };
      window.addEventListener("pointermove", mv);
      window.addEventListener("pointerup", up);
    };
    const drawKeys = () => {
      keysEl.textContent = "";
      st.els = st.keys.map((k) => {
        // rk: kept separate from the .key style of "keyframed fields" (that rule has !important; after pcg93 added it, all the ramp's
        // markers were dyed dark green, nearly invisible on the dark background)
        const m = el("div", "key rk", keysEl);
        m.addEventListener("pointerdown", (e) => {
          if (e.button) return;                       // right button is left for contextmenu
          e.preventDefault();
          e.stopPropagation();                        // don't bubble to the layer below and count as "click empty space to add a point"
          st.sel = st.keys.indexOf(k);
          fillLine(); place();
          drag(k);
        });
        m.addEventListener("contextmenu", (e) => {
          e.preventDefault();
          e.stopPropagation();                        // don't pop up the parameter context menu
          remove(st.keys.indexOf(k));
        });
        if (isColor) m.addEventListener("dblclick", (e) => {
          e.stopPropagation();
          st.sel = st.keys.indexOf(k);
          place();
          sw.onclick();
        });
        return m;
      });
      place();
    };
    const fillLine = () => {
      const k = st.keys[st.sel];
      if (!k) return;
      pos.value = fmtNum(k.p);
      vals.forEach((v, i) => { v.value = fmtNum(k.v[i]); });
      if (sw) sw.style.background = rgbHex(k.v);
    };
    // Clicking empty space = add a point at that position (value taken from the current curve there), and drag it right away
    const addAt = (e) => {
      if (e.button) return;
      e.preventDefault();
      const r = area.getBoundingClientRect();
      const p = r3(clamp01((e.clientX - r.left) / Math.max(r.width, 1)));
      const k = { p, v: sampleRamp(st.keys, p, mode()).map(r3) };
      st.keys.push(k);
      resort(k);
      drawKeys(); fillLine(); draw();
      drag(k);
    };
    area.addEventListener("pointerdown", addAt);
    if (isColor) keysEl.addEventListener("pointerdown", addAt);
    box.addEventListener("keydown", (e) => {
      if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target?.tagName || "")) return;   // typing in a field belongs to the field
      const step = { ArrowLeft: -1, ArrowRight: 1 }[e.key];
      if (e.key === "Delete" || e.key === "Backspace") remove(st.sel);
      else if (step) {
        st.sel = Math.min(st.keys.length - 1, Math.max(0, st.sel + step));
        fillLine(); place();
      } else return;
      e.preventDefault();
      e.stopPropagation();              // Delete bubbling up to the canvas would delete the whole node
    });
    const api = {
      name: n,
      set: (v) => {
        if (v === st.text) { draw(); if (sel) sel.value = mode(); return; }
        st.text = v;
        try {
          st.keys = parseRamp(v, comps);
          st.sel = Math.min(st.sel, st.keys.length - 1);
          err.textContent = "";
        } catch (e) {
          err.textContent = `ramp syntax error: ${e.message} (text: ${v})`;
        }
        fillLine(); drawKeys(); draw();
        if (sel) sel.value = mode();
      },
      state: st,
    };
    this.controls.push(api);
    if (interp) this.controls.push({ name: interp, set: (v) => {
      if (sel) sel.value = String(v);
      draw();
    } });
    this.ramps.push(api);
  }

  // ── sync / visibility ───────────────────────────────────────────────
  sync(force = false) {
    for (const c of this.controls) {
      if (!force && c.el && document.activeElement === c.el) continue;
      const v = this.get(c.name);
      if (!force && c.last === v && c.lastSet) continue;
      c.last = v; c.lastSet = true;
      try { c.set(v); } catch (e) { /* */ }
      if (c.expr) this.showExpr(c);          // the value changed; the field still shows the expression
    }
  }

  refresh() {
    this.sync();
    const get = (n) => this.get(n);
    for (const r of this.rows) {
      // Connected parameters are still shown (the field says "⇠ source"), with the slot dot aligned to this row -- before pcg85
      // a fully connected row was hidden, leaving the native widget to show the link, but the native widget's slot position didn't match the panel
      const hidden = evalCond(r.hide, get);
      r.el.classList.toggle("hidden", hidden);
      if (r.sep) r.sep.style.display = hidden ? "none" : "";
      const dis = evalCond(r.disable, get) || (r.toggleOff?.() ?? false);
      // Toggle rows: the toggle itself is always clickable, only the value is grayed out
      if (r.toggleOff) {
        r.el.classList.toggle("dis", evalCond(r.disable, get));
        const valEl = r.el.querySelector(".val");
        if (valEl) {
          valEl.style.opacity = r.toggleOff() ? ".42" : "";
          valEl.style.pointerEvents = r.toggleOff() ? "none" : "";
        }
      } else r.el.classList.toggle("dis", dis);
    }
    this.markRefs();
    for (const s of this.sections) {
      const gateOn = s.gate ? this.get(s.gate) !== false : true;
      const anyShown = s.names.some((n) =>
        this.rows.some((r) => r.names[0] === n && !r.el.classList.contains("hidden")));
      const gateHidden = s.gate && evalCond(s.hideGate, get);
      s.el.classList.toggle("hidden", (!anyShown && !s.gate) || !!gateHidden);
      const closed = this.closed.has(s.el) || !gateOn;
      s.el.classList.toggle("closed", closed);
      s.el.classList.toggle("off", !gateOn);
      s.arr.textContent = closed ? "▸" : "▾";
    }
    for (const t of this.tabBtns) {
      const any = t.names.some((n) =>
        this.rows.some((r) => r.names[0] === n && !r.el.classList.contains("hidden"))
        || this.sections.some((s) => s.gate === n && !s.el.classList.contains("hidden")));
      t.btn.classList.toggle("hidden", !any);
    }
    if (this.tabBtns.length) this.showTab(); else this.resize();
  }

  // Measuring height (onResize reads offsetHeight) forces the browser to lay out the whole page on the spot: with many panels on the page, a dozen-plus
  // milliseconds each time. Dragging the color picker / dragging values hits this on every mousemove, so it stutters.
  // So measure on the spot only when the **height may change**: which rows / sections are hidden, which section is collapsed, which tab is active, node width
  // changed (different layout signature), or the caller says so explicitly (a text box grew taller). When only a value changed -- fields have fixed height --
  // measure once more in the next frame (at most once per frame, coalesced; any change not covered by the signature, like error text, is only one frame late)
  // The signature doesn't include tab-button visibility: that follows from row and section visibility (see refresh), which are already in it
  layoutSig() {
    let s = `${this.tab}|${Math.round(this.node?.size?.[0] ?? 0)}`;
    for (const r of this.rows) s += "|" + r.el.className;
    for (const x of this.sections) s += "|" + x.el.className;
    return s;
  }

  resize(force = false) {
    const sig = this.layoutSig();
    if (force || sig !== this._sig || !this.height) {
      this._sig = sig;
      this.onResize?.();
      return;
    }
    if (this._rq) return;
    this._rq = true;
    rafOr(() => { this._rq = false; this.onResize?.(); });
  }

  // ── parameter linking ───────────────────────────────────────────────────
  bound(n) { return bindings(this.node)?.[n]; }

  graph() { return this.node.graph || app.graph; }

  /** Where the link connected to this parameter comes from: "node title.output name". */
  linkSource(n) {
    const inp = (this.node.inputs || []).find((i) =>
      (i.widget?.name === n || i.name === n) && i.link != null);
    if (!inp) return null;
    const g = this.graph();
    const l = g?.links?.get?.(inp.link) ?? g?.links?.[inp.link];
    const src = l && (g.getNodeById?.(l.origin_id)
      ?? (g._nodes || []).find((x) => x.id === l.origin_id));
    if (!src) return "link";
    const out = src.outputs?.[l.origin_slot];
    return `${src.title || src.type}.${out?.label || out?.name || l.origin_slot}`;
  }

  /** Field state: connected (⇠ source, not editable), referenced (cyan, not editable), normal. */
  markRefs() {
    for (const c of this.controls) {
      if (!c.el || !c.name) continue;
      const src = this.linked(c.name) ? this.linkSource(c.name) : null;
      const b = !src ? this.bound(c.name) : undefined;
      const keyed = isKeys(b);
      const ref = !src && !keyed && b;
      c.el.classList.toggle("lnk", !!src);
      c.el.classList.toggle("ref", !!ref);
      c.el.classList.toggle("key", keyed);
      c.el.classList.toggle("onkey", keyed && onKey(this.graph(), this.node, c.name));
      if (keyed) {
        // Keyframed: the field shows the value (green; brighter exactly on a keyframe), same as Houdini
        this.showValue(c);
        c.el.classList.remove("peek", "err", "wait");
        const ks = keysOf(this.node, c.name) || [];
        c.el.title = `Keyframes (${ks.length}): ${this.exprOf(c.name)}`
          + " (type a number / drag = set a key at the current frame; Alt+click sets a key, Alt+Shift+click deletes this frame's key; context menu -> Delete Channels)";
        if (c.hostTitle !== undefined && c.el.parentElement) {
          c.el.parentElement.title = c.hostTitle;
          c.hostTitle = undefined;
        }
        continue;
      }
      if (src) {
        const text = `⇠ ${src}`;
        if (c.el.tagName === "INPUT" && c.el.type !== "checkbox" && c.el.value !== text)
          c.el.value = text;
        c.el.title = `Connected: ${src} (context menu -> Disconnect)`;
      } else if (ref) {
        const ex = this.exprOf(c.name);
        const err = this.node._pcgBindErr?.[c.name];
        const wait = this.node._pcgBindWait?.[c.name];
        const exprMode = this.textual(c) && !this.showVal.has(c.name) && !this.peek.has(c.name);
        if (document.activeElement === c.el) { /* being edited: don't touch the text in the field */ }
        else if (exprMode) this.showExpr(c, ex);
        else this.showValue(c);
        c.el.classList.toggle("peek", this.peek.has(c.name));
        c.el.classList.toggle("err", !!err);
        c.el.classList.toggle("wait", !err && !!wait);
        c.el.title = (err ? `Expression error: ${err}\n${ex} (value unchanged, still ${fmtVal(this.get(c.name))})`
          : wait ? `${ex}: ${wait} (value kept at ${fmtVal(this.get(c.name))} for now)`
          : `Reference ${ex} = ${fmtVal(this.get(c.name))}`)
          + " (hold the middle button to see the value, click the label to toggle expression / value; type a number to replace the expression; context menu -> Delete Reference)";
        // Referenced fields don't take the mouse (pointer-events:none), so the hover tooltip must be on the outer layer to be visible
        const host = c.el.parentElement;
        if (host) {
          if (c.hostTitle === undefined) c.hostTitle = host.title;
          host.title = c.el.title;
        }
      } else {
        this.showValue(c);
        c.el.classList.remove("peek", "err", "wait");
        if (c.hostTitle !== undefined && c.el.parentElement) {
          c.el.parentElement.title = c.hostTitle;
          c.hostTitle = undefined;
        }
        if (c.el.title?.startsWith("Connected:") || c.el.title?.startsWith("Reference ")
            || c.el.title?.startsWith("Keyframes") || c.el.title?.startsWith("Expression error")
            || /^[^(]*: fetching geometry of |has not run yet|is no longer on the server/.test(c.el.title || "")) {
          c.el.title = "";
          if (c.el.tagName === "INPUT" && c.el.type !== "checkbox") {
            c.lastSet = false;                // after the link is pulled / reference deleted, write the value back
            this.sync();
          }
        }
      }
    }
  }

  /** This parameter's reference written as a Houdini expression; strings and dropdowns use chs(). */
  exprOf(n) {
    const t = specOf(this.nd, n)?.[0];
    const c = this.controls.find((x) => x.name === n);
    const tmpl = !!c?.el?.classList?.contains("txt") && !c.el.classList.contains("code");
    return bindingText(this.graph(), this.node, n, Array.isArray(t) || t === "STRING", tmpl);
  }

  /** Controls that can show a string of text in the field (checkboxes, color swatches, ramps don't count). */
  textual(c) {
    const e = c.el;
    return !!e && (e.tagName === "SELECT" || e.tagName === "TEXTAREA"
                   || (e.tagName === "INPUT" && e.type !== "checkbox" && e.type !== "color"));
  }

  /** Write an expression in the field. A dropdown can't show arbitrary text, so temporarily add an option with the expression and select it. */
  showExpr(c, text = this.exprOf(c.name)) {
    const e = c.el;
    if (e.tagName === "SELECT") {
      let op = e.querySelector("option[data-expr]");
      if (!op) {
        op = el("option", "", e);
        op.dataset.expr = "1";
        op.value = "\u0000expr";
      }
      op.textContent = text;
      e.value = op.value;
    } else if (e.value !== text) e.value = text;
    c.expr = true;
  }

  /** Switch back from expression to showing the value (reference deleted, label toggle, middle button held). */
  showValue(c) {
    if (!c.expr) return;
    c.expr = false;
    c.el.querySelector?.("option[data-expr]")?.remove();
    const v = this.get(c.name);
    try { c.set(v); } catch (e) { /* */ }
    c.last = v; c.lastSet = true;
  }

  /** Keyframeable parameters: numeric, not connected. */
  keyable(n) {
    const t = specOf(this.nd, n)?.[0];
    return (t === "INT" || t === "FLOAT") && !this.linked(n);
  }

  /**
   * Alt+click = set a keyframe at the current frame (using the current value); Alt+Shift+click = delete this frame's keyframe. Clicking a field means that one
   * parameter, clicking the label means the whole row (same as Houdini). Returns whether it was handled (for tests).
   */
  altKey(e) {
    if (!e.altKey || e.button !== 0) return false;
    const names = this.namesAt(e.clientX, e.clientY).filter((n) => this.keyable(n));
    if (!names.length) return false;
    e.preventDefault();
    e.stopPropagation();                       // on the canvas Alt+drag duplicates nodes; don't let it receive this
    const g = this.graph(), f = currentFrame(g);
    for (const n of names) {
      if (e.shiftKey) removeKey(g, this.node, n, f);
      else setKey(g, this.node, n, f, Number(this.get(n)));
    }
    this.refresh();
    this.node.setDirtyCanvas?.(true, true);
    return true;
  }

  /** Referenced field under screen coordinates (the kind that can show text). */
  refNamesAt(x, y) {
    return this.namesAt(x, y).filter((n) => this.bound(n) && !this.linked(n) && !isKeys(this.bound(n))
      && this.controls.some((c) => c.name === n && this.textual(c)));
  }

  /** Hold the middle button: a referenced field temporarily shows the current value, back to the expression on release (Houdini's MMB). */
  peekDown(e) {
    if (e.button !== 1) return;
    const names = this.refNamesAt(e.clientX, e.clientY);
    if (!names.length) return;
    e.preventDefault();
    e.stopPropagation();
    for (const n of names) this.peek.add(n);
    this.markRefs();
    const up = (ev) => {
      if (ev.type === "pointerup" && ev.button !== 1) return;
      window.removeEventListener("pointerup", up, true);
      window.removeEventListener("pointercancel", up, true);
      window.removeEventListener("blur", up);
      this.peek.clear();
      this.markRefs();
    };
    window.addEventListener("pointerup", up, true);
    window.addEventListener("pointercancel", up, true);
    window.addEventListener("blur", up);
  }

  /** Click the label: the referenced fields of this row toggle between expression / value (Houdini's clicking the parameter name). Returns whether it toggled. */
  toggleExpr(names) {
    const b = names.filter((n) => this.bound(n) && !this.linked(n) && !isKeys(this.bound(n)));
    if (!b.length) return false;
    const toVal = b.some((n) => !this.showVal.has(n));
    for (const n of b) toVal ? this.showVal.add(n) : this.showVal.delete(n);
    this.markRefs();
    return true;
  }

  /** Field under screen coordinates -> parameter names. When landing on the blank part of a row (the label), returns all parameters of that row. */
  namesAt(x, y, r = null) {
    const inside = (e) => {
      const b = e.getBoundingClientRect();
      return b.width > 0 && x >= b.left && x <= b.right && y >= b.top && y <= b.bottom;
    };
    for (const e of (r ? r.el : this.inner).querySelectorAll("[data-w]"))
      if (inside(e) && this.widgets.has(e.dataset.w)) return [e.dataset.w];
    const rows = r ? [r] : this.rows.filter((x) => !x.el.classList.contains("hidden")
                                               && inside(x.el));
    for (const row of rows) {
      const names = row.names.filter((m) => this.widgets.has(m));
      if (names.length) return names;
    }
    return [];
  }

  rowMenu(e, r) {
    return this.paramMenu(e, this.namesAt(e.clientX, e.clientY, r));
  }

  /** Houdini's parameter context menu. Returns the menu items (for tests). */
  paramMenu(e, names) {
    e?.preventDefault?.();
    e?.stopPropagation?.();
    names = (names || []).filter((n) => this.widgets.has(n));
    if (!names.length) return [];
    const g = this.graph();
    const node = this.node;
    const after = () => { applyBindings(g); this.refresh(); node.setDirtyCanvas?.(true, true); };
    const clip = clipboard();
    const bound = names.filter((n) => this.bound(n));
    const linked = names.filter((n) => this.linked(n));
    const free = names.filter((n) => !this.linked(n));
    const items = [
      { content: "Copy Parameter", callback: () => copyParams(node, names) },
    ];
    if (clip && free.length) {
      items.push({ content: `Paste Copied Values`,
                   callback: () => { pasteValues(node, free, g); after(); } });
      items.push({ content: `Paste Relative References ←${clip.text}`,
                   callback: () => {
                     const res = pasteRefs(node, free, g);
                     if (res.skipped.length) console.warn("[pcg.panel] not pasted:", res.skipped);
                     after();
                   } });
    }
    const keyable = names.filter((n) => this.keyable(n));
    const fr = currentFrame(g);
    if (keyable.length) {
      items.push({ content: `Set Keyframe · frame ${fmtNum(fr)}`,
                   callback: () => {
                     for (const n of keyable) setKey(g, node, n, fr, Number(this.get(n)));
                     after();
                   } });
    }
    const onk = names.filter((n) => onKey(g, node, n));
    if (onk.length) {
      items.push({ content: `Delete Keyframe (this frame) · frame ${fmtNum(fr)}`,
                   callback: () => { for (const n of onk) removeKey(g, node, n, fr); after(); } });
    }
    const keyed = bound.filter((n) => isKeys(this.bound(n)));
    const refd = bound.filter((n) => !isKeys(this.bound(n)));
    if (keyed.length) {
      items.push({ content: `Delete Channels · ${(keysOf(node, keyed[0]) || []).length} keyframes`,
                   callback: () => { for (const n of keyed) unbind(node, n); after(); } });
    }
    if (refd.length) {
      items.push({ content: `Delete Reference (Delete Channels) ${this.exprOf(refd[0])}`,
                   callback: () => { for (const n of refd) unbind(node, n); after(); } });
    }
    if (linked.length) {
      items.push({ content: `Disconnect (⇠ ${this.linkSource(linked[0])})`,
                   callback: () => {
                     for (const n of linked) {
                       const i = (node.inputs || []).findIndex((x) =>
                         (x.widget?.name === n || x.name === n) && x.link != null);
                       if (i >= 0) node.disconnectInput?.(i);
                     }
                     after();
                   } });
    }
    if (free.length) {
      items.push({ content: "Revert to Defaults", callback: () => {
        for (const n of free) {
          if (this.bound(n)) continue;
          const t = specOf(this.nd, n)?.[0];
          const d = this.opts(n).default;
          this.set(n, d !== undefined ? d : (Array.isArray(t) ? t[0] : this.get(n)));
        }
        after();
      } });
    }
    if (panels(g).length && free.length) {
      for (const n of free.filter((x) => !this.bound(x))) {
        items.push({ content: `Promote to panel parameter · ${n}`,
                     callback: () => { promote(node, this.widgets.get(n), g); after(); } });
      }
    }
    const LG = globalThis.LiteGraph;
    // A whole row (the three components of Translate) uses the row's label; a single field uses the parameter's own label
    const row = this.rows.find((r) => r.names.length === names.length
                               && r.names.every((x, i) => x === names[i]));
    const title = (names.length > 1 && row?.lab?.textContent)
      || names.map((n) => this.ui(n).label || n).join(" / ");
    if (LG?.ContextMenu) new LG.ContextMenu(items, { event: e, title });
    return items;
  }

  /** y of the slot dot (node coordinates). When it can't be measured (panel not on screen), use the last measured one. */
  slotY(n, baseY) {
    this.slotCache = this.slotCache || {};
    const ir = this.inner.getBoundingClientRect();
    const h = this.inner.offsetHeight;
    if (ir.height > 0 && h > 0) {
      const sc = ir.height / h;
      const f = this.inner.querySelector(`[data-w="${n}"]`);
      let b = f?.getBoundingClientRect();
      if (!b || !b.height) {
        const r = this.rows.find((x) => x.names.includes(n));
        b = r?.el.getBoundingClientRect();
      }
      // Hidden rows / other tabs / collapsed sections: placed at the top of the panel
      this.slotCache[n] = b && b.height ? (b.top + b.height / 2 - ir.top) / sc : 12;
    }
    return baseY + (this.slotCache[n] ?? 12);
  }

  /** While dragging a link, outline the field under the mouse; on release it connects to it. */
  markDrop(n) {
    if (this.dropName === n) return;
    this.inner.querySelectorAll(".droptgt").forEach((e) => e.classList.remove("droptgt"));
    this.dropName = n || null;
    if (n) {
      this.inner.querySelector(`[data-w="${n}"]`)?.classList.add("droptgt");
      DROP.panel = this;
    }
  }

  /** A link dragged over the panel: the native widget of the field under the mouse (the frontend uses it to find the slot). */
  widgetAtClient(x, y) {
    const lc = app.canvas?.linkConnector;
    for (const n of this.namesAt(x, y)) {
      const slot = (this.node.inputs || []).find((i) => i.widget?.name === n);
      if (!slot) continue;
      if (lc?.isInputValidDrop && !lc.isInputValidDrop(this.node, slot)) continue;
      return this.widgets.get(n);
    }
    return null;
  }
}

// The latest pointer position (screen coordinates). While dragging a link the canvas holds pointer capture and the panel receives no events itself,
// so this is the only way to know which field the mouse is over
const PTR = { x: -1, y: -1 };
// After release the frontend no longer asks this node "which widget is under the mouse" (the mouse may no longer be over it),
// so the yellow outline has to be erased by us
const DROP = { panel: null };
if (typeof window !== "undefined" && window.addEventListener) {
  window.addEventListener("pointermove", (e) => { PTR.x = e.clientX; PTR.y = e.clientY; },
                          { capture: true, passive: true });
  window.addEventListener("pointerup", () => {
    const p = DROP.panel;
    DROP.panel = null;
    if (p) setTimeout(() => p.markDrop(null), 0);
  }, { capture: true, passive: true });
}
export const __ptr = PTR;

/** Connected / connectable parameters: the slot dot is moved to that row of the panel (several components on one row are staggered slightly). */
export function alignSlots(node) {
  const p = node._pcgPanel, pw = node._pcgPanelWidget;
  if (!p || !pw || typeof pw.y !== "number") return;
  const base = pw.y + MARGIN;
  (node.inputs || []).forEach((inp, i) => {
    const n = inp?.widget?.name;
    if (!n || !p.widgets.has(n)) return;
    const row = p.rows.find((r) => r.names.includes(n));
    const k = row ? row.names.indexOf(n) : 0;
    const m = row ? row.names.filter((x) => p.widgets.has(x)).length : 1;
    // x goes on the node's left border: the default x = 10 would be covered by the panel (starting at x = 4) and the dot would be invisible
    const pos = [0, p.slotY(n, base) + (k - (m - 1) / 2) * 5];
    inp.pos = pos;
    const c = node._concreteInputs?.[i];
    if (c) c.pos = pos;
  });
}

// ════════════════════════════════════════════════════ hooking into nodes
function mode() {
  try {
    const v = app.extensionManager?.setting?.get?.(SETTING_ID)
      ?? app.ui?.settings?.getSettingValue?.(SETTING_ID);
    return LEGACY_MODES[v] || v || MODES[0];
  } catch (e) {
    return MODES[0];
  }
}

// Whether this node can be taken over: has layout info; no multiline code box; no custom widgets added by other extensions
export function eligible(node, nodeData) {
  const ws = node.widgets || [];
  if (!ws.length) return false;
  let any = false;
  for (const w of ws) {
    if (w.name === "pcg_panel") continue;
    const u = uiOf(nodeData, w.name);
    if (!u) {
      if (ALLOWED_TAIL.has(w.type)) continue;
      return false;                      // widgets added by the frontend / other extensions
    }
    if (u.kind === "code" && optsOf(nodeData, w.name).multiline) return false;
    if (!STANDARD.has(w.type) && !(u.kind === "text")) return false;
    any = true;
  }
  return any;
}

function natives(node) {
  return (node.widgets || []).filter((w) => w.name !== "pcg_panel" && !ALLOWED_TAIL.has(w.type));
}

// The panel's actual height. When the element isn't on screen (node outside the viewport, just loaded, frontend hasn't laid out yet) scrollHeight
// is 0 -- using 0 for the node height collapses the node into a strip, the element gets even less chance to show, deadlock. So when it can't be measured,
// temporarily attach it to an off-screen container of the same width, measure, then put it back
export function measure(root, inner, width) {
  const h = root.isConnected && root.offsetParent !== null ? inner.offsetHeight : 0;
  if (h > 0) return h;
  const parent = root.parentNode, next = root.nextSibling;
  const box = document.createElement("div");
  box.style.cssText = `position:absolute;left:-100000px;top:0;visibility:hidden;` +
    `width:${Math.max(120, width || MIN_W)}px`;
  document.body.appendChild(box);
  box.appendChild(root);
  const m = inner.offsetHeight;
  if (parent) parent.insertBefore(root, next); else box.removeChild(root);
  box.remove();
  return m;
}

/**
 * The node's custom parameters (pcg104, pcg_spare.js) go into the panel too: their layout info is not in /object_info but
 * computed by pcg_spare from the declaration and hung on node._pcgSpareUi. Here they are merged into a node-local copy of nodeData.
 */
export function withSpare(nodeData, node) {
  const extra = node?._pcgSpareUi;
  if (!extra || !Object.keys(extra).length) return nodeData;
  const input = { ...(nodeData?.input || {}) };
  input.optional = { ...(input.optional || {}), ...extra };
  return { ...nodeData, input };
}

export function activate(node, baseData) {
  // After custom parameters are added / removed the panel must be rebuilt (the widget set changed): pcg_spare calls this
  node._pcgPanelRebuild = () => {
    if (mode() === MODES[1] || node.properties?.[PROP_NATIVE]) return;
    if (node._pcgPanel) deactivate(node);
    activate(node, baseData);
  };
  const nodeData = withSpare(baseData, node);
  if (node._pcgPanel || !eligible(node, nodeData)) return null;
  injectCss();
  const panel = new Panel(node, nodeData);
  const w = node.addDOMWidget?.("pcg_panel", "pcg_panel", panel.root, {
    serialize: false,
    hideOnZoom: true,
    margin: MARGIN,
    getValue: () => "",
    setValue: () => {},
    // The element keeps a margin above and below; widget height = panel height + 2·margin
    getMinHeight: () => (panel.height || 40) + 2 * MARGIN,
    getMaxHeight: () => (panel.height || 40) + 2 * MARGIN,
    getHeight: () => (panel.height || 40) + 2 * MARGIN,
  });
  if (!w) return null;
  w.serialize = false;
  // Move after the last native widget (only within the non-serialized tail; native indices unchanged)
  const ws = node.widgets;
  const i = ws.indexOf(w);
  let last = -1;
  ws.forEach((x, k) => { if (x !== w && !ALLOWED_TAIL.has(x.type)) last = k; });
  if (i > last + 1) { ws.splice(i, 1); ws.splice(last + 1, 0, w); }
  // Hide all native widgets (connected ones too: the slot dot is moved to the panel row by alignSlots)
  for (const x of natives(node)) setShown(x, false);
  if (!Object.prototype.hasOwnProperty.call(node, "arrange") && node.arrange) {
    const arrange = node.arrange;
    node.arrange = function () {
      const r = arrange.apply(this, arguments);
      try { alignSlots(this); } catch (e) { /* if alignment fails, don't stop the canvas */ }
      return r;
    };
    node._pcgOwnArrange = true;
  }
  if (!Object.prototype.hasOwnProperty.call(node, "getWidgetOnPos") && node.getWidgetOnPos) {
    const gwp = node.getWidgetOnPos;
    node.getWidgetOnPos = function (x, y, inc) {
      const w = gwp.apply(this, arguments);
      // Only swapped while dragging a link: normally clicks on the panel are handled by the DOM itself, and the canvas gets the panel widget itself
      const p = this._pcgPanel;
      if (w && w === this._pcgPanelWidget && app.canvas?.linkConnector?.isConnecting) {
        const t = p?.widgetAtClient(PTR.x, PTR.y);
        p?.markDrop(t?.name);
        if (t) return t;
      } else p?.markDrop(null);
      return w;
    };
    node._pcgOwnGWP = true;
  }
  node._pcgPanel = panel;
  node._pcgPanelWidget = w;
  node._pcgPanelActive = true;
  panel.onResize = () => {
    const h = Math.ceil(measure(panel.root, panel.inner, node.size[0] - 2 * MARGIN)) + 4;
    if (h && Math.abs(h - (panel.height || 0)) > 1) {
      panel.height = h;
      const need = node.computeSize?.() || node.size;
      node.setSize?.([Math.max(node.size[0], MIN_W, need[0]), need[1]]);
      node.setDirtyCanvas?.(true, true);
    }
  };
  node.size[0] = Math.max(node.size[0], MIN_W);
  panel.refresh();                     // measure height synchronously once (without waiting for the next frame)
  requestAnimationFrame?.(() => panel.refresh());
  return panel;
}

export function deactivate(node) {
  const w = node._pcgPanelWidget;
  if (!w) return;
  const i = node.widgets.indexOf(w);
  if (i >= 0) node.widgets.splice(i, 1);
  try { w.onRemove?.(); } catch (e) { /* */ }
  w.element?.remove?.();
  node._pcgPanel = null;
  node._pcgPanelWidget = null;
  node._pcgPanelActive = false;
  // Remove the two hooked methods (back to the prototype's); the frontend re-arranges slot positions from native widgets on the next arrange
  if (node._pcgOwnArrange) { delete node.arrange; node._pcgOwnArrange = false; }
  if (node._pcgOwnGWP) { delete node.getWidgetOnPos; node._pcgOwnGWP = false; }
  for (const x of natives(node)) setShown(x, true);
  node._pcgApplySections?.();
  const need = node.computeSize?.() || node.size;
  node.setSize?.([node.size[0], need[1]]);
  node.setDirtyCanvas?.(true, true);
}

app.registerExtension({
  name: "pcg.panel",
  settings: [{
    id: SETTING_ID,
    category: ["PCG", "Parameter panel", "Style"],
    name: "Parameter panel for PCG nodes (refresh the page after changing)",
    type: "combo",
    options: MODES,
    defaultValue: MODES[0],
  }],
  async beforeRegisterNodeDef(nodeType, nodeData) {
    const any = ["required", "optional"].some((g) =>
      Object.values(nodeData?.input?.[g] || {}).some(
        (s) => Array.isArray(s) && s[1] && s[1][UI_KEY]));
    if (!any) return;

    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onCreated?.apply(this, arguments);
      // Wait until other extensions' onNodeCreated have all run (they may also append widgets) before deciding
      setTimeout(() => {
        if (mode() === MODES[1] || this.properties?.[PROP_NATIVE]) return;
        try { activate(this, nodeData); } catch (e) { console.error("[pcg.panel]", e); }
      }, 0);
      return r;
    };

    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const r = onConfigure?.apply(this, arguments);
      setTimeout(() => {
        if (this.properties?.[PROP_NATIVE] && this._pcgPanel) deactivate(this);
        this._pcgPanel?.refresh();
      }, 0);
      return r;
    };

    const onDraw = nodeType.prototype.onDrawForeground;
    nodeType.prototype.onDrawForeground = function () {
      const r = onDraw?.apply(this, arguments);
      const p = this._pcgPanel;
      if (p) {
        // Values may have been changed elsewhere (parameter references, undo, loading): read them back; recompute visibility only if changed
        const before = p.controls.map((c) => c.last);
        p.sync();
        if (p.controls.some((c, i) => c.last !== before[i])) p.refresh();
        else {
          // Frame changed: the value may not have changed, but the "exactly on a keyframe" highlight must follow
          const f = currentFrame(p.graph());
          if (p._frame !== f) { p._frame = f; p.markRefs(); }
        }
      }
      return r;
    };

    const onConn = nodeType.prototype.onConnectionsChange;
    nodeType.prototype.onConnectionsChange = function () {
      const r = onConn?.apply(this, arguments);
      this._pcgPanel?.refresh();
      return r;
    };

    const menu = nodeType.prototype.getExtraMenuOptions;
    nodeType.prototype.getExtraMenuOptions = function (canvas, options) {
      const r = menu?.apply(this, arguments);
      try {
        if (Array.isArray(options) && mode() !== MODES[1]) {
          const on = !!this._pcgPanel;
          options.push(null, {
            content: on ? "Parameter panel: use native widgets" : "Parameter panel: use Houdini panel",
            callback: () => {
              this.properties = this.properties || {};
              if (on) { this.properties[PROP_NATIVE] = true; deactivate(this); }
              else { delete this.properties[PROP_NATIVE]; activate(this, nodeData); }
            },
          });
        }
      } catch (e) { /* failing to add menu items must not stop the context menu from opening */ }
      return r;
    };
  },
});
