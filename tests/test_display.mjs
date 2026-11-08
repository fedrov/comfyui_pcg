// Tests for the display flag + the persistent panel. jsdom + a stubbed app / api / LiteGraph,
// with the module really running.
//
// Three kinds of things that **fail silently**:
//
//   1) rewiring wrong. The flag wired to the wrong slot, or two links left behind on a switch -- invisible on screen,
//      but the wrong node gets cooked. The checks look directly at graph.links and the sink's input slot.
//   2) swallowing too many events. The flag's pointerdown calls stopPropagation in the **capture phase**;
//      a hit test that is too wide makes the whole canvas unclickable (can't drag nodes, can't box-select).
//      So there is a dedicated test for "never intercept when the flag was not hit".
//   3) auto-recook not coalescing. Clicking several nodes in a row stuffs that many jobs into the queue, with no way to cancel midway.
//      Tests: at most one in flight, clicks in between merged into one, the watchdog can unstick a hang.
//
// The renderer (Viewport class) is **stubbed**: it needs WebGL and pulls three.js from a CDN,
// which doesn't run in jsdom, and it isn't what this suite tests anyway -- the node-embedded viewport
// uses the same class and has been validated in real use. What is tested here is "does the panel
// feed it the right data and pass the options down correctly".
import { JSDOM } from "jsdom";
import fs from "fs";
import os from "os";
import path from "path";
import { fileURLToPath } from "url";

const _HERE = path.dirname(fileURLToPath(import.meta.url));
function pkgRoot() {
  let d = _HERE;
  for (let i = 0; i < 4; i++) {
    if (fs.existsSync(path.join(d, "comfyui_pcg"))) return d;
    d = path.dirname(d);
  }
  return "/tmp/pcgpkg";
}
const PKG = pkgRoot();
// A **new** temp dir per run (pcg64): it used to be hard-coded "/tmp/jstest_disp"; with two regression runs in parallel
// one side rmSync'd files the other was importing, which is how test_camlink once broke; and
// test_icons / test_playbar used the same dir. Deleted when done
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "jstest_disp_"));
process.on("exit", () => fs.rmSync(ROOT, { recursive: true, force: true }));
const EXT = path.join(ROOT, "extensions", "comfyui_pcg");
fs.mkdirSync(path.join(ROOT, "scripts"), { recursive: true });
fs.mkdirSync(EXT, { recursive: true });

fs.writeFileSync(path.join(ROOT, "scripts", "app.js"),
                 "export const app = globalThis.__app;\n");
fs.writeFileSync(path.join(ROOT, "scripts", "api.js"),
                 "export const api = globalThis.__api;\n");

// ── stub renderer ──────────────────────────────────────────────────────
// The real Viewport needs WebGL; this only records what it received.
fs.writeFileSync(path.join(EXT, "pcg_viewport.js"), `
export const DEFAULTS = {
  highlight: "none", visualize: "none",
  shading: "phong", normals: "auto", wireframe: false, show_points: false,
  show_normals: "none", normal_scale: 0.25, numbers: "none", show_grid: true,
};
export function decode(buf) { return globalThis.__decoded; }
export class Viewport {
  constructor(el, opts) {
    this.el = el; this.opts = { ...opts };
    this.shadingInfo = "smooth";
    this.geoms = []; this.patches = []; this.framed = 0;
    this.eye = [0, 0, 5]; this.target = [0, 0, 0]; this.fov = 45;
    this.cams = []; this.gates = []; this.gate = null;
    globalThis.__views.push(this);
  }
  setGeometry(d) { this.geoms.push(d); }
  setOptions(p) { Object.assign(this.opts, p); this.patches.push(p); }
  groupLabels() { return globalThis.__groups; }
  attribLabels() { return globalThis.__attribs; }
  frameAll() { this.framed++; }
  dispose() {}
  // Camera link: the stub records "what the panel pushed into the viewport". The spherical-coordinate conversion lives in the real
  // Viewport (pcg_viewport.js); this tests whether the panel pushes data in the **right direction**
  // -- if both directions are active at once the viewport drifts by itself, the bug this suite fears most
  getCameraState() { return { eye: [...this.eye], target: [...this.target],
                              up: [0, 1, 0], fov: this.fov }; }
  setCameraState(c) { this.cams.push(c); this.eye = [...c.eye];
                      this.target = [...c.target]; this.fov = c.fov;
                      return true; }
  setGate(g) { this.gate = g; this.gates.push(g); }
}
`);
fs.copyFileSync(path.join(PKG, "comfyui_pcg", "web", "pcg_display.js"),
                path.join(EXT, "pcg_display.js"));

const dom = new JSDOM("<!doctype html><html><body></body></html>",
                      { url: "http://localhost/", pretendToBeVisual: true });
for (const k of ["window", "document", "HTMLElement", "Node", "localStorage",
                 "Event", "CustomEvent", "MouseEvent", "KeyboardEvent"]) {
  Object.defineProperty(globalThis, k, {
    value: k === "window" ? dom.window : dom.window[k],
    writable: true, configurable: true,
  });
}
globalThis.requestAnimationFrame = (f) => setTimeout(f, 16);
globalThis.__views = [];
globalThis.__groups = ["none"];
globalThis.__attribs = ["none"];
globalThis.__decoded = { header: { counts: { points: 3, verts: 3, prims: 1 } } };

const OK = [];
function check(name, cond, extra = "") {
  OK.push(!!cond);
  const tail = extra === "" ? "" : "   " + extra;
  console.log((cond ? "  PASS  " : "  FAIL  ") + name + tail);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ══════════════════════════════════════════════ a good-enough fake litegraph
// Implements only the parts this code actually touches, but **link semantics must match the real one** --
// in particular disconnectInput must also clear the reference on the output side, otherwise the tests would let through
// the real, once-existing bug "disconnected on screen, still connected when serialized".
let nextId = 1;
function mkNode(type, outs = [GEO()], ins = []) {
  return {
    type, id: null, title: null, pos: [0, 0], size: [140, 40],
    flags: {}, outputs: outs, inputs: ins,
    connect(slot, target, targetSlot) {
      const id = GRAPH._nextLink++;
      GRAPH.links[id] = { id, origin_id: this.id, origin_slot: slot,
                          target_id: target.id, target_slot: targetSlot };
      (this.outputs[slot].links ||= []).push(id);
      target.inputs[targetSlot].link = id;
      return true;
    },
    disconnectInput(idx) {
      const lid = this.inputs[idx]?.link;
      if (lid == null) return false;
      const l = GRAPH.links[lid];
      if (l) {
        const src = GRAPH.getNodeById(l.origin_id);
        const arr = src?.outputs?.[l.origin_slot]?.links;
        if (arr) {
          const k = arr.indexOf(lid);
          if (k >= 0) arr.splice(k, 1);
        }
        delete GRAPH.links[lid];
      }
      this.inputs[idx].link = null;
      return true;
    },
    findInputSlot(name) {
      return this.inputs.findIndex((i) => i && i.name === name);
    },
  };
}
function GEO() { return { name: "geo", type: "GEOMETRY", links: [] }; }
function IMG() { return { name: "image", type: "COPIMAGE", links: [] }; }

const GRAPH = {
  _nodes: [], links: {}, _nextLink: 1,
  changes: 0,
  add(n) { n.id = nextId++; this._nodes.push(n); return n; },
  getNodeById(id) { return this._nodes.find((n) => n.id === id) || null; },
  setDirtyCanvas() {},
  beforeChange() { this.changes++; },
  afterChange() { this.changes++; },
};

globalThis.LiteGraph = {
  createNode(type) {
    if (type !== "PCG_Display") return null;
    return mkNode(type, [GEO()],
                  [{ name: "geo", type: "GEOMETRY", link: null },
                   { name: "template", type: "GEOMETRY", link: null }]);
  },
};

// ── canvas stub: convertEventToCanvasOffset makes coordinates fully deterministic
const CANVAS_EL = dom.window.document.createElement("div");
dom.window.document.body.appendChild(CANVAS_EL);
const CANVAS = {
  canvas: CANVAS_EL,
  ds: { scale: 1, offset: [0, 0] },
  dirty: 0,
  convertEventToCanvasOffset(e) { return [e.clientX, e.clientY]; },
  setDirty() { this.dirty++; },
};

const Q = { count: 0 };
globalThis.__app = {
  graph: GRAPH, canvas: CANVAS, exts: [],
  registerExtension(e) { this.exts.push(e); },
  queuePrompt() { Q.count++; return Promise.resolve(); },
};
const handlers = {};
globalThis.__api = {
  addEventListener(ev, fn) { (handlers[ev] ||= []).push(fn); },
};
function fire(ev) { for (const fn of handlers[ev] || []) fn({ detail: {} }); }

const M = await import(path.join(EXT, "pcg_display.js"));
const ext = globalThis.__app.exts[0];
check("pcg.display extension registered", ext && ext.name === "pcg.display");
await ext.setup();

// ══════════════════════════════════════════════════════════ flag geometry
console.log("═".repeat(28), "flag position and hit testing");

const box1 = GRAPH.add(mkNode("PCG_Box"));
box1.pos = [100, 200];
const cop1 = GRAPH.add(mkNode("PCG_CopNoise", [IMG()]));
cop1.pos = [100, 400];
const multi = GRAPH.add(mkNode("PCG_Split", [GEO(), GEO()]));
multi.pos = [400, 200];

check("slot numbers of GEOMETRY outputs are found", M.geoSlots(box1).join() === "0",
      M.geoSlots(box1).join());
check("  multi-output nodes: both slots count", M.geoSlots(multi).join() === "0,1");
check("  non-GEOMETRY outputs (COP images) don't get a flag slot",
      M.geoSlots(cop1).length === 0);
check("  no crash without an outputs field", M.geoSlots({}).length === 0);

globalThis.LiteGraph.NODE_TITLE_HEIGHT = 30;
const r1 = M.flagRects(box1);
// The flag position was changed twice, and both times the problem was only found by actually looking. These checks pin both pitfalls:
//   · not outside the frame on the right -- that is where output slots draw their links; links would pass under the squares
//   · above the title bar it **must not be right-aligned** -- the new frontend's node badge (the green "comfyui_pcg"
//     label) is drawn there
check("the flag is entirely **above** the title bar (its bottom edge does not cross the title bar top)",
      r1.disp[1] + r1.disp[3] <= box1.pos[1] - 30,
      `bottom ${r1.disp[1] + r1.disp[3]} <= title top ${box1.pos[1] - 30}`);
check("  **left-aligned** to the node's left edge, avoiding the badge at the top right",
      r1.disp[0] === box1.pos[0], `${r1.disp[0]} vs ${box1.pos[0]}`);
check("  side by side horizontally, not overlapping",
      r1.tmpl[0] >= r1.disp[0] + r1.disp[2]
      && r1.tmpl[1] === r1.disp[1],
      `disp x=${r1.disp[0]}+${r1.disp[2]}, tmpl x=${r1.tmpl[0]}`);
check("  neither reaches into the node frame (doesn't compete with widgets / output slots)",
      r1.disp[1] + r1.disp[3] <= box1.pos[1]
      && r1.tmpl[1] + r1.tmpl[3] <= box1.pos[1]);
check("  doesn't occupy the node's right side (links go there)",
      r1.disp[0] < box1.pos[0] + box1.size[0]
      && r1.tmpl[0] + r1.tmpl[2] < box1.pos[0] + box1.size[0]);
check("  follows the node (move the node and the flag moves)",
      (() => { box1.pos = [150, 250];
               const r = M.flagRects(box1);
               const ok = r.disp[0] === r1.disp[0] + 50
                       && r.disp[1] === r1.disp[1] + 50;
               box1.pos = [100, 200];
               return ok; })());
check("  left-aligned, so the position doesn't depend on node width -- widening / collapsing doesn't move it",
      (() => { const a = M.flagRects(box1);
               box1.size = [400, 40];
               const b = M.flagRects(box1);
               box1.flags.collapsed = true;
               box1._collapsed_width = 60;
               const c = M.flagRects(box1);
               box1.flags.collapsed = false;
               box1.size = [140, 40];
               return a.disp.join() === b.disp.join()
                   && a.disp.join() === c.disp.join(); })());
check("  title bar height is read from LiteGraph, not hard-coded 30",
      (() => { globalThis.LiteGraph.NODE_TITLE_HEIGHT = 50;
               const r = M.flagRects(box1);
               globalThis.LiteGraph.NODE_TITLE_HEIGHT = 30;
               return r.disp[1] === r1.disp[1] - 20; })());

const hitAt = (r) => M.hitFlag(GRAPH, [r[0] + 2, r[1] + 2]);
check("click inside the display square -> hits disp",
      hitAt(r1.disp)?.kind === "disp" && hitAt(r1.disp)?.node === box1);
check("click inside the template square -> hits tmpl", hitAt(r1.tmpl)?.kind === "tmpl");
check("  just outside (off the square) must not hit",
      M.hitFlag(GRAPH, [r1.disp[0] - 3, r1.disp[1] + 2]) === null);
check("  empty space doesn't hit", M.hitFlag(GRAPH, [9999, 9999]) === null);
check("  nodes without a GEOMETRY output grow no flags at all",
      M.hitFlag(GRAPH, [M.flagRects(cop1).disp[0] + 2,
                        M.flagRects(cop1).disp[1] + 2]) === null);

// ══════════════════════════════════════════════════════════ rewiring
console.log("═".repeat(28), "clicking a flag = rewiring");

check("no flag at first", M.currentFlag(GRAPH, "disp") === null);
check("  and no Display node yet either (nothing gets stuffed into the graph at startup)",
      M.findSink(GRAPH, false) === null);

M.setFlag(GRAPH, "disp", box1, 0);
const sink = M.findSink(GRAPH, false);
check("the first flag click creates a Display node automatically", sink && sink.type ===
      "PCG_Display");
check("  placed to the right of the flagged node, not covering it",
      sink.pos[0] > box1.pos[0] + box1.size[0], sink.pos.join());
const cf = M.currentFlag(GRAPH, "disp");
check("  geo input wired to box1's output 0",
      cf?.node === box1 && cf?.slot === 0);
check("  exactly one link in the graph", Object.keys(GRAPH.links).length === 1);

M.setFlag(GRAPH, "disp", multi, 1);
check("click another node -> the flag **moves over**, no second one is added",
      M.currentFlag(GRAPH, "disp")?.node === multi
      && Object.keys(GRAPH.links).length === 1,
      Object.keys(GRAPH.links).length);
check("  slot number is right too (multi's output 1)",
      M.currentFlag(GRAPH, "disp")?.slot === 1);
check("  the old link is cleared on the **output side** too (clearing only the input side means disconnected on screen but"
      + " still connected in the saved workflow)",
      (box1.outputs[0].links || []).length === 0,
      JSON.stringify(box1.outputs[0].links));
check("  the Display node is not created twice",
      GRAPH._nodes.filter((n) => n.type === "PCG_Display").length === 1);

M.setFlag(GRAPH, "disp", multi, 1);
check("click the same slot of the same node again -> flag removed (same as Houdini)",
      M.currentFlag(GRAPH, "disp") === null
      && Object.keys(GRAPH.links).length === 0);

M.setFlag(GRAPH, "disp", box1, 0);
M.setFlag(GRAPH, "tmpl", multi, 0);
check("template flag and display flag don't interfere",
      M.currentFlag(GRAPH, "disp")?.node === box1
      && M.currentFlag(GRAPH, "tmpl")?.node === multi
      && Object.keys(GRAPH.links).length === 2);
check("  both flags can sit on the same node",
      (() => { M.setFlag(GRAPH, "tmpl", box1, 0);
               return M.currentFlag(GRAPH, "disp")?.node === box1
                   && M.currentFlag(GRAPH, "tmpl")?.node === box1; })());
check("  the Display node itself grows no flags (or it could wire itself to itself)",
      M.hitFlag(GRAPH, [M.flagRects(sink).disp[0] + 2,
                        M.flagRects(sink).disp[1] + 2]) === null);
// clean up so the following tests start from scratch
M.setFlag(GRAPH, "tmpl", box1, 0);
M.setFlag(GRAPH, "disp", box1, 0);
check("  after cleanup both flags are empty and the links gone",
      M.currentFlag(GRAPH, "disp") === null
      && M.currentFlag(GRAPH, "tmpl") === null
      && Object.keys(GRAPH.links).length === 0);

// ══════════════════════════════════════════════════════ canvas events
console.log("═".repeat(28), "canvas events: intercept only on a hit, never on a miss");

function clickAt(x, y, opts = {}) {
  let bubbled = false;
  const probe = () => { bubbled = true; };
  CANVAS_EL.addEventListener("pointerdown", probe);   // bubble-phase probe
  const ev = new dom.window.MouseEvent("pointerdown", {
    clientX: x, clientY: y, button: opts.button ?? 0, bubbles: true,
    cancelable: true, ctrlKey: !!opts.ctrlKey,
  });
  CANVAS_EL.dispatchEvent(ev);
  CANVAS_EL.removeEventListener("pointerdown", probe);
  // if the capture phase calls stopPropagation, bubble listeners on the same element don't fire
  return { swallowed: !bubbled, prevented: ev.defaultPrevented };
}

const q0 = Q.count;
const rr = M.flagRects(box1);
const c1 = clickAt(rr.disp[0] + 2, rr.disp[1] + 2);
check("clicking a flag: the event is swallowed (otherwise litegraph also drags the node / starts a box select)",
      c1.swallowed && c1.prevented);
check("  the flag took effect", M.currentFlag(GRAPH, "disp")?.node === box1);
check("  a run was queued along the way", Q.count === q0 + 1, `${q0} -> ${Q.count}`);
check("  canvas marked dirty (without a redraw the flag color doesn't update)", CANVAS.dirty > 0);

const c2 = clickAt(5000, 5000);
check("clicking empty space: **must never** intercept -- otherwise the whole canvas becomes unclickable",
      !c2.swallowed && !c2.prevented);
const c3 = clickAt(M.flagRects(cop1).disp[0] + 2,
                   M.flagRects(cop1).disp[1] + 2);
check("  clicking the flag spot of a node without a GEOMETRY output must not intercept either",
      !c3.swallowed);

M.setFlag(GRAPH, "disp", box1, 0);          // clear
const c4 = clickAt(rr.disp[0] + 2, rr.disp[1] + 2, { ctrlKey: true });
check("Ctrl + click on the display square = set template (saves aiming at the tiny square)",
      M.currentFlag(GRAPH, "tmpl")?.node === box1
      && M.currentFlag(GRAPH, "disp") === null, c4.swallowed);
const c5 = clickAt(rr.disp[0] + 2, rr.disp[1] + 2, { button: 2 });
check("  same for the right button", M.currentFlag(GRAPH, "tmpl") === null);

// ══════════════════════════════════════════════════════ auto-recook coalescing
console.log("═".repeat(28), "auto-recook: at most one in flight, the ones in between merged");

M.__state.inFlight = false;
M.__state.want = false;
M.__state.autorun = true;
const qA = Q.count;
check("the first requestRun really queues", M.requestRun() === true
      && Q.count === qA + 1);
check("  queueing again while in flight -> not queued, only remembered as wanted", M.requestRun() === false
      && Q.count === qA + 1 && M.__state.want === true);
check("  five clicks in a row still leave only that one in flight",
      (() => { for (let i = 0; i < 5; i++) M.requestRun();
               return Q.count === qA + 1; })());
fire("executed");
await sleep(0);
check("  after it finishes, the saved-up request is queued (merged into one, not five)",
      Q.count === qA + 2, `${qA} -> ${Q.count}`);
fire("executed");
await sleep(0);
check("  nothing saved up -> nothing more queued", Q.count === qA + 2);

M.__state.autorun = false;
const qB = Q.count;
check("with auto-recook off, requestRun does nothing",
      M.requestRun() === false && Q.count === qB);
M.__state.autorun = true;

check("all three completion events are hooked (with only one, some frontend versions get stuck in-flight forever)",
      ["executed", "execution_success", "status"]
        .every((e) => (handlers[e] || []).length > 0),
      Object.keys(handlers).join());
M.__state.inFlight = true;
M.__state.want = false;
fire("status");
check("  a status event can also clear in-flight", M.__state.inFlight === false);

// ══════════════════════════════════════════════════════════ panel
console.log("═".repeat(28), "persistent panel");

const panel = [...dom.window.document.body.children]
  .find((e) => e.style && e.style.position === "fixed");
check("panel is built, as a position:fixed overlay", !!panel);
check("  z-index below the node search panel (10000), doesn't cover it",
      Number(panel.style.zIndex) < 10000, panel.style.zIndex);
check("  shown by default", panel.style.display === "flex");
check("  renderer attached", globalThis.__views.length === 1);
const view = globalThis.__views[0];
check("  the renderer gets the panel's own div, not a node's",
      view.el && view.el.parentElement === panel);
check("  default options passed down (shading phong)", view.opts.shading === "phong");

check("title bar starts with a hint to click a flag",
      /display flag/.test(panel.textContent), panel.textContent.slice(0, 40));
M.setFlag(GRAPH, "disp", multi, 1);
M.syncTitle(GRAPH);
check("with a flag set, the title bar says who it is (name + id)",
      /#\d/.test(panel.textContent), panel.textContent.slice(0, 60));
check("  multi-output nodes include the slot number (otherwise you can't tell which output is flagged)",
      /\[1\]/.test(panel.textContent), panel.textContent.slice(0, 60));
M.setFlag(GRAPH, "disp", multi, 1);
M.syncTitle(GRAPH);
check("  back to the hint after removing it", /display flag/.test(panel.textContent));

// **This is the most important check in this section.** The first version of the control bar wired only 6 keys;
// normals / show_normals / normal_scale / numbers were missed, showing up as
// "no normals visible in the panel", while the node-embedded viewport had them all -- the two disagreed,
// with no error at all. So compare directly against the key set of DEFAULTS.
const DEF_KEYS = Object.keys(view.opts).sort();
const sels = [...panel.querySelectorAll("select[data-optkey]")];
const nums = [...panel.querySelectorAll("input[data-numkey]")];
const toggles = [...panel.querySelectorAll("button[data-key]")];
const covered = [...sels.map((e) => e.dataset.optkey),
                 ...nums.map((e) => e.dataset.numkey),
                 ...toggles.map((e) => e.dataset.key)].sort();
check("the control bar covers **all** renderer options (key set identical to DEFAULTS)",
      covered.join() === DEF_KEYS.join(),
      `missing [${DEF_KEYS.filter((k) => !covered.includes(k))}] ` +
      `extra [${covered.filter((k) => !DEF_KEYS.includes(k))}]`);
check("  all three normal-related ones present (normals / show_normals / normal_scale)",
      ["normals", "show_normals", "normal_scale"]
        .every((k) => covered.includes(k)));
check("  element numbers present too (numbers)", covered.includes("numbers"));
check("  every dropdown has a small text label in front of it, not just a title to guess from",
      sels.every((e) => e.parentElement
        && /[A-Za-z]{3}/.test(e.previousElementSibling?.textContent || "")));

const selBy = (k) => sels.find((e) => e.title === k);
selBy("shading").value = "normal";
selBy("shading").onchange();
check("  changing a dropdown passes the option to the renderer",
      view.opts.shading === "normal", JSON.stringify(view.patches.at(-1)));
selBy("show_normals").value = "point";
selBy("show_normals").onchange();
check("  the normal-arrows dropdown really passes through", view.opts.show_normals === "point");
const num = nums[0];
num.value = "1.5"; num.oninput();
check("  the normal_scale number input passes through", view.opts.normal_scale === 1.5,
      view.opts.normal_scale);
num.value = "99"; num.oninput();
check("  out-of-range values are clamped (scale is not written as 99)",
      view.opts.normal_scale === 4, view.opts.normal_scale);
num.value = ""; num.oninput();
check("  clearing the input box does not write NaN into the options",
      view.opts.normal_scale === 4, view.opts.normal_scale);
toggles[0].onclick();
check("  toggles pass through too", view.opts.wireframe === true);
check("  toggle state saved to localStorage",
      /"wireframe":true/.test(localStorage.getItem("pcg.display.panel") || ""),
      (localStorage.getItem("pcg.display.panel") || "").slice(0, 80));
check("  options saved too", /"shading":"normal"/.test(
      localStorage.getItem("pcg.display.panel") || ""));

// ────────────────────────────────────────────────────────── toggle button
const tog = [...dom.window.document.body.children]
  .find((e) => e.dataset && e.dataset.pcgToggle);
check("there is a persistent toggle button", !!tog, tog && tog.textContent);
// this one is key: if the button lives inside the panel, it disappears with the panel on display:none
// and can never be brought back -- a dead end, and the user has no idea what happened
check("  button attached to body, **not inside the panel** (otherwise closing the panel loses it for good)",
      tog.parentElement === dom.window.document.body
      && !panel.contains(tog));
check("  z-index slightly below the panel, doesn't cover it",
      Number(tog.style.zIndex) < Number(panel.style.zIndex),
      `${tog.style.zIndex} < ${panel.style.zIndex}`);
check("  in the bottom-right corner (ComfyUI's top bar / sidebar / centered playbar don't use it)",
      tog.style.right && tog.style.bottom,
      `right=${tog.style.right} bottom=${tog.style.bottom}`);

// jsdom normalizes #rrggbb to rgb(...), so compare by meaning, not spelling:
// record the "open" colors, then assert they change when closed and return when reopened
const BG_ON = tog.style.background;
check("  button has the active colors while open", !!BG_ON, BG_ON);

tog.onclick();
check("clicking the button closes the panel", panel.style.display === "none" && !M.__state.open);
check("  panel hidden, the button itself still there (display not affected along with it)",
      tog.parentElement === dom.window.document.body
      && tog.style.display !== "none");
const BG_OFF = tog.style.background;
check("  button switches to the inactive colors (not the same value as when open)",
      BG_OFF !== BG_ON && !!BG_OFF, `${BG_ON} -> ${BG_OFF}`);
check("  closed state saved to localStorage",
      /"open":false/.test(localStorage.getItem("pcg.display.panel") || ""));
tog.onclick();
check("click again to open", panel.style.display === "flex" && M.__state.open);
check("  button back to the active colors", tog.style.background === BG_ON,
      tog.style.background);

// the ✕ on the panel title bar and the button must share one state
const closeBtn = [...panel.querySelectorAll("button")]
  .find((b) => b.textContent === "✕");
closeBtn.onclick();
check("after closing with the panel's ✕, the button also becomes inactive",
      !M.__state.open && tog.style.background === BG_OFF,
      tog.style.background);
check("  the button is then the only way back, and it really still works",
      (() => { tog.onclick(); return M.__state.open
                 && panel.style.display === "flex"; })());

// clicking a flag while the panel is closed should open the panel as well
setOpen_viaFlag: {
  tog.onclick();                                  // close it first
  const before = M.__state.open;
  const rf = M.flagRects(box1);
  clickAt(rf.disp[0] + 2, rf.disp[1] + 2);
  check("clicking a flag while the panel is closed -> opens the panel too (no need to press the button first)",
        before === false && M.__state.open === true);
}

// ══════════════════════════════════════════════════════════ fetching data
console.log("═".repeat(28), "fetching geometry data");

let lastUrl = null;
const fakeFetch = (status, body) => (url) => {
  lastUrl = url;
  return Promise.resolve({
    ok: status === 200, status,
    arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)),
    text: () => Promise.resolve(body || "boom"),
  });
};

const n0 = view.geoms.length;
check("on 200 the geometry is fed to the renderer",
      (await M.fetchInto(42, 7, fakeFetch(200))) === true
      && view.geoms.length === n0 + 1);
check("  URL carries node id and rev (rev busts the browser cache)",
      /\/pcg\/geo\/42\?rev=7/.test(lastUrl), lastUrl);
check("404 and not pushed after a cook (rev=null) -> exit silently, no error shown",
      (await M.fetchInto(43, null, fakeFetch(404))) === false);
check("  404 with a rev -> a real error, must be reported",
      (await M.fetchInto(43, 9, fakeFetch(404, "no geometry"))) === false
      && /error/.test(panel.textContent), panel.textContent.slice(-60));

globalThis.__groups = ["none", "hull", "seam"];
globalThis.__attribs = ["none", "Cd", "N"];
await M.fetchInto(44, 1, fakeFetch(200));
// get dropdowns by **name**, not by index -- after normals / show_normals were added
// all indices shifted, and index-based assertions would test the wrong control
check("group / attribute names are only known at runtime; the dropdowns are refilled when data arrives",
      [...selBy("highlight").options].map((o) => o.value).join()
        === "none,hull,seam",
      [...selBy("highlight").options].map((o) => o.value).join());
check("  same for the attribute dropdown",
      [...selBy("visualize").options].map((o) => o.value).join()
        === "none,Cd,N");
selBy("highlight").value = "hull";
selBy("highlight").onchange();
globalThis.__groups = ["none"];              // geometry changed, the group is gone
await M.fetchInto(45, 1, fakeFetch(200));
check("selected group missing from the new geometry -> falls back to none, not a dead value that can't be selected",
      selBy("highlight").value === "none" && view.opts.highlight === "none",
      selBy("highlight").value);
check("  the badge shows point / primitive counts", /pts 3/.test(panel.textContent),
      panel.textContent.slice(-40));
// refilling rebuilds options; it must not clear other dropdowns along the way
check("  refilling only touches the group / attribute dropdowns, others (e.g. normal arrows) keep their values",
      selBy("show_normals").value === "point"
      && view.opts.show_normals === "point",
      selBy("show_normals").value);

// ══════════════════════════════════════════════════════ camera link
//
// This section watches three things that **fail silently**:
//
//  1) **both directions active at once.** The camera pushes into the viewport, the viewport writes back to the camera; one round trip
//     introduces tiny differences and the viewport slowly drifts by itself (feels "a bit sticky", very hard to attribute).
//     So the criterion: with lock off, never write widgets; with lock on, never push the camera into the viewport.
//  2) **mode not updated.** The orbit / frame positions are computed on the backend; writing eye without changing
//     mode means "pressed the lock but the camera didn't move", with no error.
//  3) **queueing every tick while dragging.** Under lock a tick is 120ms, one drag means dozens of
//     jobs. Criterion: no queueing while parameters are still changing, queue once after stopping.
console.log("═".repeat(28), "camera link");

function mkCam(vals) {
  const n = mkNode("PCG_Camera", [{ name: "cam", type: "PCGCAM", links: [] }]);
  n.widgets = Object.entries({
    projection: "perspective", mode: "look_at",
    resolution_x: 512, resolution_y: 512, fov: 45, ortho_size: 2,
    elev: 25, azim: 35, distance: 5, margin: 1.15,
    target_x: 0, target_y: 0, target_z: 0,
    eye_x: 0, eye_y: 0, eye_z: 5,
    up_x: 0, up_y: 1, up_z: 0, near: 0.01, far: 0,
    ...(vals || {}),
  }).map(([name, value]) => ({ name, value, calls: 0,
                               callback() { this.calls++; } }));
  return GRAPH.add(n);
}

const camA = mkCam({ eye_x: 3, eye_y: 4, eye_z: 0, fov: 30,
                     resolution_x: 1024, resolution_y: 576 });
const camB = mkCam({ mode: "orbit", elev: 0, azim: 0, distance: 7 });

check("all Camera nodes in the graph are found", M.cameraNodes(GRAPH).length === 2);
check("  other nodes are not taken for cameras",
      !M.cameraNodes(GRAPH).includes(box1));

const rA = M.readCamera(camA);
check("look_at mode reads eye_x/y/z directly", rA.eye.join() === "3,4,0", rA.eye.join());
check("  resolution / fov read along with it",
      rA.xres === 1024 && rA.yres === 576 && rA.fov === 30);
const rB = M.readCamera(camB);
// orbit_eye:eye = target + d·(cos(elev)·sin(azim), sin(elev), cos(elev)·cos(azim))
// elev=0, azim=0 -> (0, 0, d). This formula must match geo/render.py exactly,
// otherwise what you see through the camera and what renders differ by an axis
check("orbit mode computes the position from elev/azim/distance (same formula as render.orbit_eye)",
      Math.abs(rB.eye[0]) < 1e-12 && Math.abs(rB.eye[1]) < 1e-12
      && Math.abs(rB.eye[2] - 7) < 1e-12, rB.eye.join());
const rB2 = M.readCamera(mkCam({ mode: "orbit", elev: 90, azim: 0,
                                 distance: 4 }));
check("  at elev=90 the position is straight above (axes not swapped)",
      Math.abs(rB2.eye[1] - 4) < 1e-9 && Math.abs(rB2.eye[2]) < 1e-9,
      rB2.eye.join());
check("mode=frame is marked approximate (the frontend doesn't know the geometry size)",
      M.readCamera(mkCam({ mode: "frame" })).approx === true);
check("  look_at / orbit are not marked approximate", rA.approx === false
      && rB.approx === false);
check("default values instead of NaN when widgets can't be read",
      (() => { const c = M.readCamera(mkNode("PCG_Camera")); 
               return c.eye.every(Number.isFinite)
                   && Number.isFinite(c.fov); })());
check("the camera only counts as changed when the signature changes (same parameters, same signature)",
      M.camSignature(M.readCamera(camA))
      === M.camSignature(M.readCamera(camA)));
check("  changing one parameter changes the signature",
      (() => { const a = M.camSignature(M.readCamera(camA));
               camA.widgets.find((w) => w.name === "fov").value = 31;
               const b = M.camSignature(M.readCamera(camA));
               camA.widgets.find((w) => w.name === "fov").value = 30;
               return a !== b; })());

// ── direction one: follow camera (lock off)
M.__state.cam.nodeId = camA.id;
M.__state.cam.lock = false;
M.__state.cam.gate = true;
M.__state.camSig = null;
const nCams = view.cams.length;
M.syncCamera(GRAPH);
check("lock off: camera pushed into the viewport once",
      view.cams.length === nCams + 1);
check("  what was pushed is the camera's position",
      view.cams.at(-1).eye.join() === "3,4,0");
check("  the gate guide uses the camera's resolution",
      view.gate && view.gate.xres === 1024 && view.gate.yres === 576);
M.syncCamera(GRAPH);
M.syncCamera(GRAPH);
check("  **no more pushes** while the camera is unchanged -- otherwise the viewport keeps getting yanked back and can't be tumbled",
      view.cams.length === nCams + 1, `pushed ${view.cams.length - nCams} times`);
view.eye = [9, 9, 9];                       // simulate the user tumbling the viewport
M.syncCamera(GRAPH);
check("  no push after the user tumbled the viewport either (camera unchanged, nothing moves)",
      view.eye.join() === "9,9,9");
const eyeW = camA.widgets.find((w) => w.name === "eye_x");
check("  with lock off the camera widgets are **never** written", eyeW.value === 3, eyeW.value);
camA.widgets.find((w) => w.name === "eye_x").value = 5;
M.syncCamera(GRAPH);
check("  only jumps along when the camera really changed (e.g. the playbar advanced a frame)",
      view.cams.at(-1).eye.join() === "5,4,0");

M.__state.cam.gate = false;
M.syncCamera(GRAPH);
check("with the gate guide toggle off the gate guide is gone", view.gate === null);
M.__state.cam.gate = true;

// ── direction two: lock camera to view
M.__state.cam.lock = true;
view.eye = [1, 2, 3];
view.target = [0.5, 0, 0];
// earlier sections tested coalescing / the watchdog and may have left inFlight at true. If that isn't cleared
// the "queue once after stopping" check below fails to queue for **another** reason -- the check looks failed while
// the implementation is correct -- test state leaking between tests like this has bitten several times
M.__state.inFlight = false;
M.__state.want = false;
M.__state.autorun = true;
Q.count = 0;
M.syncCamera(GRAPH);
const get = (n) => camA.widgets.find((w) => w.name === n).value;
check("lock on: the view is written into the camera's eye",
      [get("eye_x"), get("eye_y"), get("eye_z")].join() === "1,2,3");
check("  target written too",
      [get("target_x"), get("target_y"), get("target_z")].join() === "0.5,0,0");
check("  **mode changed to look_at** -- otherwise eye has no effect at all",
      get("mode") === "look_at");
check("  up straightened (the viewport's spherical coordinates can't express roll)",
      [get("up_x"), get("up_y"), get("up_z")].join() === "0,1,0");
check("  the widget callback was called (some widgets have hooked behaviour)",
      camA.widgets.find((w) => w.name === "eye_x").calls > 0);
check("  with lock on the camera is **not** pushed back into the viewport (otherwise the two directions fight and the viewport drifts)",
      view.eye.join() === "1,2,3");
check("  parameters still changing in this tick, so **no queueing**", Q.count === 0);
const before = view.cams.length;
M.syncCamera(GRAPH);
check("  unchanged values are not rewritten (the callback doesn't fire every tick)",
      camA.widgets.find((w) => w.name === "eye_y").calls === 1);
M.__state.camDirtyAt = Date.now() - 5000;       // pretend the user stopped long ago
M.syncCamera(GRAPH);
check("  queued only once after stopping (a drag would otherwise stuff in dozens of jobs)", Q.count === 1);
M.syncCamera(GRAPH);
check("  nothing more queued after that", Q.count === 1);
check("  the camera is not pushed into the viewport while locked either", view.cams.length === before);

// switching / deleting cameras
const sel = panel.querySelector("select[data-camsel]");
check("the panel has a camera selector, and it does **not** count as a render-option control",
      sel && sel.dataset.optkey === undefined);
M.syncCamList(GRAPH);
check("  the options are free view + every camera in the graph",
      sel.options.length === M.cameraNodes(GRAPH).length + 1,
      `${sel.options.length} items`);
check("  first item is free view (empty value)", sel.options[0].value === "");
sel.value = String(camB.id);
sel.onchange();
check("switching cameras **unlocks automatically** -- otherwise you'd casually edit the new camera",
      M.__state.cam.lock === false && M.__state.cam.nodeId === camB.id);
M.__state.camSig = null;
M.syncCamera(GRAPH);
check("  after switching, the new camera is pushed",
      Math.abs(view.cams.at(-1).eye[2] - 7) < 1e-9);

const camC = mkCam({});
M.__state.cam.nodeId = camC.id;
M.__state.cam.lock = true;
GRAPH._nodes = GRAPH._nodes.filter((n) => n !== camC);
M.syncCamList(GRAPH);
check("after the selected camera is deleted, falls back to free view and unlocks",
      M.__state.cam.nodeId === null && M.__state.cam.lock === false);
M.syncCamera(GRAPH);
check("  gate guide off in free view too", view.gate === null);

// user-reported bug: free view -> camera -> free view (via the dropdown) left the camera frame visible.
// onchange sets camSig to null first, and the old code only turned the gate guide off when camSig !== null
view.fov = 45;
M.__state.freeFov = null;
camB.widgets.find((w) => w.name === "fov").value = 30;
M.syncCamList(GRAPH);
sel.value = String(camB.id);
sel.onchange();
M.syncCamera(GRAPH);
M.syncCamera(GRAPH);
check("switching the dropdown to a camera: gate guide appears, viewport fov becomes the camera's",
      view.gate !== null && view.fov === 30, `fov=${view.fov}`);
sel.value = "";
sel.onchange();
M.syncCamera(GRAPH);
check("  switch back to free view (dropdown): **gate guide disappears**", view.gate === null);
check("  fov handed back to free view (otherwise switching back keeps the camera's focal length)", view.fov === 45,
      `fov=${view.fov}`);
M.syncCamera(GRAPH);
check("  after that fov is not touched every tick (the user's own fov is not overwritten)",
      view.fov === 45 && view.gate === null);

// hint line: three cases where "what you see differs from what renders" must be spelled out
M.__state.cam.nodeId = camB.id;
M.syncCamList(GRAPH);
const note = panel.querySelector("span[style*='c8a96a']");
check("a normal camera shows no hint line",
      !note || note.style.display === "none" || note.textContent === "");
const camT = mkCam({ mode: "frame", projection: "orthographic",
                     up_x: 1, up_y: 0 });
M.__state.cam.nodeId = camT.id;
M.syncCamList(GRAPH);
const txt = M.__state.camNote.textContent;
check("mode=frame / orthographic / up not +Y: all three are hinted",
      /frame/.test(txt) && /orthographic/.test(txt) && /roll/.test(txt), txt);

// saved state: lock is **not** restored
M.__state.cam.nodeId = camB.id;
M.__state.cam.lock = true;
M.save();
M.__state.cam.lock = false;
M.__state.cam.nodeId = null;
M.load();
check("saved state remembers the selected camera", M.__state.cam.nodeId === camB.id);
check("  but does **not** restore the lock -- changing the camera on the first viewport touch after a refresh would be infuriating",
      M.__state.cam.lock === false);
M.__state.cam.nodeId = null;
M.__state.cam.lock = false;


// ══════════════════════════════════════════════════════ saved-state robustness
console.log("═".repeat(28), "saved state");

check("panel position saved to localStorage",
      /"rect"/.test(localStorage.getItem("pcg.display.panel") || ""));
// a broken saved state / one that can't be read at all (localStorage throws in private mode) must not block startup.
// This must not be written as `try { return true }` -- that would test nothing.
localStorage.setItem("pcg.display.panel", "{this is not json");
M.__state.opts.shading = "wire";
let threw = false;
try { M.load(); } catch (_) { threw = true; }
check("saved state is broken json -> load doesn't throw and doesn't make options undefined",
      !threw && M.__state.opts.shading === "wire", M.__state.opts.shading);

// keys missing from the saved state must not become undefined (would bite when DEFAULTS gains keys later)
localStorage.setItem("pcg.display.panel",
                     JSON.stringify({ opts: { shading: "lambert" } }));
M.load();
check("keys missing from the saved state keep their values, not overwritten with undefined",
      M.__state.opts.shading === "lambert"
      && M.__state.opts.show_grid !== undefined,
      `shading=${M.__state.opts.shading} grid=${M.__state.opts.show_grid}`);

// localStorage throwing altogether (private mode)
const realLS = globalThis.localStorage;
Object.defineProperty(globalThis, "localStorage", {
  value: { getItem() { throw new Error("denied"); },
           setItem() { throw new Error("denied"); } },
  writable: true, configurable: true,
});
let threw2 = false;
try { M.load(); M.save(); } catch (_) { threw2 = true; }
check("with localStorage disabled, load / save just fail silently, nothing propagates",
      !threw2);
Object.defineProperty(globalThis, "localStorage",
                      { value: realLS, writable: true, configurable: true });

const pass = OK.filter(Boolean).length;
console.log(`\n${pass}/${OK.length} passed`);
process.exit(pass === OK.length ? 0 : 1);
