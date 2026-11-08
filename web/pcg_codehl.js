// comfyui_pcg/web/pcg_codehl.js
//
// Syntax highlighting for code boxes. Applies to any multiline STRING widget whose options contain code_hl.
//
// It uses the classic **transparent textarea over a highlight layer**: a <pre> underneath draws the colored
// text; the textarea on top has a transparent background and transparent text, leaving only caret and selection; the two
// keep content and scrolling in sync.
//
// Why not pull in CodeMirror / Monaco:
//   · the CDN is unreachable on this machine (verified with three.js), and bundling a whole editor framework into a
//     custom node starts at hundreds of KB -- not worth it for one code box.
//   · after replacing the native textarea, ComfyUI's widget value reading, undo and copy/paste would all have to be
//     rewired by hand; the surface for bugs is far larger than the highlighting itself.
// The overlay approach only adds a display layer; the textarea is still the original, so all existing behaviour is unaffected.
//
// The only thing to be careful about: **the font metrics of the two layers must match exactly**; the slightest difference misaligns them.
// So font, line height, padding and wrapping rules are all copied from the textarea's computed style.

import { app } from "../../scripts/app.js";

const KEYWORDS = new Set([
  "sin", "cos", "tan", "atan2", "asin", "acos", "atan", "sinh", "cosh", "tanh",
  "sqrt", "cbrt", "pow", "exp", "log", "log10",
  "floor", "ceil", "rint", "trunc", "sign", "frac",
  "clamp", "fit", "fit01", "fit10", "efit", "lerp", "smooth", "smoothstep",
  "length", "length2", "distance", "distance2", "normalize", "cross", "dot",
  "set", "vector", "vector2", "vector4", "radians", "degrees", "where",
  "noise", "vnoise", "pnoise", "rand",
  "getbbox_min", "getbbox_max", "getbbox_size", "getbbox_center",
  "point", "vertex", "prim", "detail", "npoints", "nprims", "nvertices",
  "ninputs",
  "ch", "chf", "chi", "chs", "chv",
  "min", "max", "abs", "int", "float", "bool", "len", "round", "sum",
  "range", "print",
]);
const SPECIAL = new Set(["np", "math", "PI", "seed", "True", "False", "None"]);

const C = {
  comment: "#6a7280",
  string: "#d8a657",
  number: "#d3869b",
  attrib: "#7ab8ea",
  swizzle: "#5fc4ff",
  func: "#8fd4a0",
  special: "#c58cff",
  op: "#9aa3ad",
  text: "#dde3ea",
};

const esc = (s) => s.replace(/[&<>]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

const span = (cls, s) => `<span style="color:${cls}">${esc(s)}</span>`;

// A small lexer. Order matters: comments and strings must be consumed before the other rules,
// otherwise @ or # inside a string would be split off as an attribute/comment.
const RULES = [
  [/^#[^\n]*/, (m) => span(C.comment, m)],
  [/^"(?:[^"\\]|\\.)*"?/, (m) => span(C.string, m)],
  [/^'(?:[^'\\]|\\.)*'?/, (m) => span(C.string, m)],
  [/^[vfips234]?@\w+(?:\.[xyzw])?/, (m) => {
    const dot = m.indexOf(".");
    return dot < 0 ? span(C.attrib, m)
      : span(C.attrib, m.slice(0, dot)) + span(C.swizzle, m.slice(dot));
  }],
  [/^\d+\.?\d*(?:[eE][-+]?\d+)?/, (m) => span(C.number, m)],
  [/^[A-Za-z_]\w*/, (m) =>
    KEYWORDS.has(m) ? span(C.func, m)
      : SPECIAL.has(m) ? span(C.special, m) : span(C.text, m)],
  [/^[+\-*/%=<>!&|^~,;:.()[\]{}]+/, (m) => span(C.op, m)],
  [/^\s+/, (m) => esc(m)],
];

function highlight(src) {
  let out = "", s = src;
  while (s.length) {
    let hit = false;
    for (const [re, fn] of RULES) {
      const m = re.exec(s);
      if (m && m[0].length) {
        out += fn(m[0]);
        s = s.slice(m[0].length);
        hit = true;
        break;
      }
    }
    if (!hit) {                       // unrecognized characters are output as-is; must not hang the loop
      out += esc(s[0]);
      s = s.slice(1);
    }
  }
  // With a trailing newline the <pre> doesn't reserve that line; append a space so both layers have the same line count
  return out + " ";
}

function attach(ta) {
  if (!ta || ta._pcgHL) return;
  ta._pcgHL = true;

  // Move the textarea's original background onto the wrapper, then make it transparent, otherwise the container color underneath shows through
  const bg0 = getComputedStyle(ta).backgroundColor;
  const wrap = document.createElement("div");
  wrap.style.cssText = "position:relative;width:100%;height:100%";
  wrap.style.background = (bg0 && bg0 !== "rgba(0, 0, 0, 0)") ? bg0 : "#1a1d23";
  wrap.style.borderRadius = getComputedStyle(ta).borderRadius;
  ta.parentNode.insertBefore(wrap, ta);

  const pre = document.createElement("pre");
  pre.style.cssText = `position:absolute;inset:0;margin:0;overflow:hidden;
    pointer-events:none;z-index:0`;
  wrap.append(pre, ta);

  ta.style.position = "relative";
  ta.style.zIndex = "1";
  ta.style.background = "transparent";
  ta.style.color = "transparent";
  ta.style.caretColor = "#e6ebf2";

  const copyStyle = () => {
    const cs = getComputedStyle(ta);
    // Metrics must be copied one by one; the slightest difference misaligns the layers
    for (const k of ["fontFamily", "fontSize", "fontWeight", "lineHeight",
                     "letterSpacing", "tabSize", "paddingTop", "paddingRight",
                     "paddingBottom", "paddingLeft", "borderTopWidth",
                     "borderRightWidth", "borderBottomWidth", "borderLeftWidth",
                     "whiteSpace", "wordBreak", "overflowWrap"])
      pre.style[k] = cs[k];
    pre.style.borderStyle = "solid";
    pre.style.borderColor = "transparent";
    if (cs.whiteSpace === "normal" || cs.whiteSpace === "nowrap")
      pre.style.whiteSpace = "pre-wrap";
  };

  const render = () => {
    pre.innerHTML = highlight(ta.value || "");
    pre.scrollTop = ta.scrollTop;
    pre.scrollLeft = ta.scrollLeft;
  };

  copyStyle();
  render();
  ta.addEventListener("input", render);
  ta.addEventListener("scroll", () => {
    pre.scrollTop = ta.scrollTop;
    pre.scrollLeft = ta.scrollLeft;
  });
  // Node zoom changes the textarea size and padding
  new ResizeObserver(() => { copyStyle(); render(); }).observe(ta);
  // When the value is changed programmatically (loading a workflow, undo) no input event fires; poll as a fallback
  let last = ta.value;
  setInterval(() => {
    if (ta.value !== last) { last = ta.value; render(); }
  }, 250);
}

app.registerExtension({
  name: "pcg.codehl",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    const names = new Set();
    for (const g of ["required", "optional"])
      for (const [k, spec] of Object.entries(nodeData?.input?.[g] || {}))
        if (Array.isArray(spec) && spec[1]?.code_hl) names.add(k);
    if (!names.size) return;

    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onCreated?.apply(this, arguments);
      // The widget's DOM is attached asynchronously; wait a tick before looking for it
      setTimeout(() => {
        for (const w of this.widgets || []) {
          if (!names.has(w.name)) continue;
          const ta = w.inputEl || w.element?.querySelector?.("textarea");
          if (ta) attach(ta);
        }
      }, 0);
    };
  },
});
