// comfyui_pcg/web/pcg_display.js
//
// Houdini's display flag + a persistent 3D panel.
//
// Every node that outputs GEOMETRY gets two small squares on its right: blue is display, gray is template.
// One click and the view switches to that node's output -- no rewiring, no dragging Viewport nodes back and forth.
//
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// The most important thing: ComfyUI and Houdini are **opposite** in "who drives evaluation"
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//     Houdini   the display flag itself is the reason to cook. Wherever it is set, that chain gets computed.
//     ComfyUI   only evaluates the part of the graph **leading to an output node**. If an intermediate node's output isn't wired to a terminal,
//               it simply never runs.
//
// So this can't be just the frontend drawing a box -- the flagged node must actually enter the execution subgraph.
// How: a Display (PCG) node sits in the graph as the landing point; clicking a flag uses litegraph's
// connect() to **rewire** its input over there.
//
// Why rewire instead of hooking graphToPrompt() to temporarily insert a sink into the submitted prompt:
//   · WYSIWYG -- the link in the graph is the dependency that actually executes
//   · serialization is naturally correct; undo / redo / copy-paste / saving workflows all work as usual
//   · doesn't depend on any frontend hook point without a stable contract
// The cost is one extra node and one link in the graph. In exchange "what you see is what runs" -- worth it.
//
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Three implementation choices
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 1) **Flags are drawn on the canvas layer, not the node layer.** Via canvas.onDrawForeground (graph coordinates)
//    plus a canvas-level pointerdown, same as pcg_cutlinks.js. So the flags can sit **outside the node box**
//    (as in Houdini), never compete with widgets for space, and don't wrestle with litegraph's
//    node-level event dispatch -- which behaves inconsistently across versions in the title bar area.
//
// 2) **The renderer is reused, not copied.** The Viewport class in pcg_viewport.js only needs a DOM element
//    and an options object to construct; it was decoupled from nodes from the start. The panel just news one onto
//    its own div, so the panel and the in-node viewport show pixel-identical output.
//    Its render loop reads container.clientWidth/Height every frame, so making the panel resizable takes
//    zero code -- don't write another resize logic.
//
// 3) **Auto-recompute must be coalesced.** Clicking a flag queues a run, but ComfyUI's queuePrompt pushes onto a queue,
//    it doesn't execute synchronously. Clicking five nodes in a row queues five jobs, and they can't be cancelled midway.
//    So at most one job is in flight at any time; while in flight only "what you last wanted to see" is remembered,
//    and once finished we queue once more with the latest value. This is the same problem as scrubbing the timeline in pcg_playbar.js,
//    and the solution is copied: hook all three completion events + a 30-second watchdog fallback (hooking only one means on some frontend
//    version the event never comes -> pending stays true forever -> clicking flags never responds again, with no error).

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { Viewport, DEFAULTS, decode } from "./pcg_viewport.js";

const SINK_TYPE = "PCG_Display";
const GEO = "GEOMETRY";

const FLAG = 13;                  // flag edge length (graph coordinates)
const FLAG_GAP = 3;
const FLAG_OFF = 5;               // distance from the node's right edge

const C_DISP = "#4a9eff";         // Houdini's blue display flag
const C_TMPL = "#9aa4b2";         // gray template flag
const C_OFF = "#3a3f4a";

const LS_KEY = "pcg.display.panel";
const WATCHDOG_MS = 30000;

const S = {
  panel: null, view: null, body: null, title: null,
  open: true, autorun: true,
  rect: { x: null, y: null, w: 420, h: 340 },
  opts: { ...DEFAULTS },
  inFlight: false, want: false, watchdog: null,
  lastNodeId: null,
  // Camera linking. nodeId is the id of the Camera (PCG) in the graph, null = free view
  cam: { nodeId: null, lock: false, gate: true },
  camSig: null, camDirtyAt: 0, freeFov: null,
};

// ════════════════════════════════════════════════════════════ persistence
export function save() {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify({
      open: S.open, autorun: S.autorun, rect: S.rect, opts: S.opts,
      cam: S.cam,
    }));
  } catch (_) { /* localStorage throws in private mode; must not crash because of it */ }
}

export function load() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return;
    const o = JSON.parse(raw);
    if (typeof o.open === "boolean") S.open = o.open;
    if (typeof o.autorun === "boolean") S.autorun = o.autorun;
    if (o.rect) Object.assign(S.rect, o.rect);
    // Options are merged by name, not replaced wholesale -- when DEFAULTS gains a new key later, old saved state won't
    // turn it into undefined
    if (o.opts) for (const k of Object.keys(DEFAULTS))
      if (k in o.opts) S.opts[k] = o.opts[k];
    // Camera likewise merged by key. **Lock is not restored**: if it were still locked after a page refresh, the first touch of
    // the viewport would change the camera, without the user knowing they're in locked mode -- this kind of "remembering
    // a mode that modifies data" is the most hated kind of persistence
    if (o.cam) {
      if (typeof o.cam.nodeId === "number") S.cam.nodeId = o.cam.nodeId;
      if (typeof o.cam.gate === "boolean") S.cam.gate = o.cam.gate;
      S.cam.lock = false;
    }
  } catch (_) { /* if the saved state is broken use defaults; don't let it block startup */ }
}

// ════════════════════════════════════════════════════════ flags on the graph
/** Output slot indices whose type is GEOMETRY. */
export function geoSlots(node) {
  const out = [];
  for (let i = 0; i < (node?.outputs?.length ?? 0); i++)
    if (node.outputs[i]?.type === GEO) out.push(i);
  return out;
}

/** Node width in graph coordinates. When collapsed, size isn't the real width. */
function nodeWidth(node) {
  if (node.flags?.collapsed)
    return node._collapsed_width || 80;
  return node.size?.[0] ?? 100;
}

/** Title bar height. The frontend changed this constant, so read it instead of hard-coding 30. */
function titleH() {
  return globalThis.LiteGraph?.NODE_TITLE_HEIGHT ?? 30;
}

/**
 * Graph-coordinate rectangles of the two flags: **just above the title bar**, left-aligned to the node's left edge, side by side.
 *
 * The position was changed twice, both times problems only showed up after actually looking:
 *
 * 1. The first version put them **outside the node box on the right** (stacked vertically). Looked most like Houdini, but that's exactly
 *    where output slots send out links -- links passed under the squares and got crammed together.
 * 2. So they moved above the title bar. But **right-aligned** didn't work either: ComfyUI's new frontend draws the node's
 *    badge (that green "comfyui_pcg" label) right-aligned above the title bar,
 *    and they collide directly.
 *
 * So it's above the title bar + **left-aligned**. Nobody uses that spot on either side.
 * A side benefit: once left-aligned the position no longer depends on node width; collapsing / widening doesn't move it.
 */
export function flagRects(node) {
  const x = node.pos[0];
  const y = node.pos[1] - titleH() - FLAG - 2;
  return {
    disp: [x, y, FLAG, FLAG],
    tmpl: [x + FLAG + FLAG_GAP, y, FLAG, FLAG],
  };
}

function inRect(p, r) {
  return p[0] >= r[0] && p[0] <= r[0] + r[2]
      && p[1] >= r[1] && p[1] <= r[1] + r[3];
}

/** The Display node in the graph. With create=true, one is created to the right of near if there is none. */
export function findSink(graph, create, near) {
  const nodes = graph?._nodes ?? [];
  for (const n of nodes) if (n.type === SINK_TYPE) return n;
  if (!create) return null;
  const LG = globalThis.LiteGraph;
  if (!LG?.createNode) return null;
  const n = LG.createNode(SINK_TYPE);
  if (!n) return null;
  // Place it to the right of the flagged node so it doesn't cover it
  n.pos = near
    ? [near.pos[0] + nodeWidth(near) + 60, near.pos[1]]
    : [80, 80];
  graph.add(n);
  return n;
}

function slotIndex(sink, name) {
  if (sink?.findInputSlot) {
    const i = sink.findInputSlot(name);
    if (i >= 0) return i;
  }
  const ins = sink?.inputs ?? [];
  for (let i = 0; i < ins.length; i++) if (ins[i]?.name === name) return i;
  return -1;
}

const IN_NAME = { disp: "geo", tmpl: "template" };

/** Who this flag is currently connected to -> {node, slot}; null when not connected. */
export function currentFlag(graph, kind) {
  const sink = findSink(graph, false);
  if (!sink) return null;
  const idx = slotIndex(sink, IN_NAME[kind]);
  if (idx < 0) return null;
  const link = sink.inputs?.[idx]?.link;
  if (link == null) return null;
  const l = graph.links?.[link] ?? graph.links?.get?.(link);
  if (!l) return null;
  const node = graph.getNodeById(l.origin_id);
  return node ? { node, slot: l.origin_slot } : null;
}

/**
 * Set / clear a flag. Returns true if the graph was changed.
 *
 * Clicking the same slot of the same node again = cancel (same as clicking a flag off in Houdini).
 * A flag can only be in one place at a time, so disconnectInput first, then connect.
 */
export function setFlag(graph, kind, node, slot) {
  const cur = currentFlag(graph, kind);
  const same = cur && cur.node === node && cur.slot === slot;
  const sink = findSink(graph, true, node);
  if (!sink) return false;
  const idx = slotIndex(sink, IN_NAME[kind]);
  if (idx < 0) return false;

  // Must go through disconnectInput. Deleting entries from graph.links directly leaves slot references:
  // disconnected on screen but the saved workflow is still connected -- the same pitfall as pcg_cutlinks.js.
  if (sink.disconnectInput) sink.disconnectInput(idx);
  if (!same && node.connect) node.connect(slot, sink, idx);
  return true;
}

/** Which flag a graph coordinate hits. Iterate in reverse, take the topmost. */
export function hitFlag(graph, p) {
  const nodes = graph?._nodes ?? [];
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i];
    if (n.type === SINK_TYPE) continue;         // the sink itself gets no flags
    const slots = geoSlots(n);
    if (!slots.length) continue;
    const r = flagRects(n);
    if (inRect(p, r.disp)) return { node: n, kind: "disp", slot: slots[0] };
    if (inRect(p, r.tmpl)) return { node: n, kind: "tmpl", slot: slots[0] };
  }
  return null;
}

// ──────────────────────────────────────────────────────────── drawing flags
function box(ctx, r, fill, stroke) {
  ctx.beginPath();
  ctx.roundRect
    ? ctx.roundRect(r[0], r[1], r[2], r[3], 2)
    : ctx.rect(r[0], r[1], r[2], r[3]);
  ctx.fillStyle = fill;
  ctx.fill();
  ctx.lineWidth = 1;
  ctx.strokeStyle = stroke;
  ctx.stroke();
}

export function drawFlags(ctx, graph) {
  const d = currentFlag(graph, "disp");
  const t = currentFlag(graph, "tmpl");
  const nodes = graph?._nodes ?? [];
  ctx.save();
  for (const n of nodes) {
    if (n.type === SINK_TYPE || !geoSlots(n).length) continue;
    const r = flagRects(n);
    const on = d && d.node === n;
    const ton = t && t.node === n;
    box(ctx, r.disp, on ? C_DISP : C_OFF, on ? "#cfe6ff" : "#22252c");
    box(ctx, r.tmpl, ton ? C_TMPL : C_OFF, ton ? "#e2e7ee" : "#22252c");
  }
  ctx.restore();
}

// ════════════════════════════════════════════════════════ camera linking
//
// Houdini's viewport has a camera dropdown at top right: persp is the free view, picking a camera means
// **looking through it**, and pressing the lock icon is "Lock Camera to View" -- tumbling the viewport positions the camera.
// This section is those three things, done against the Camera (PCG) nodes in the graph.
//
// ━━ Why not simply "write the viewport state into the camera every frame, and push the camera state back to the viewport"
// The two directions would fight: write -> read back -> tiny numeric differences -> write again,
// and the viewport slowly drifts by itself (very slowly, it feels like "the controls are a bit sticky"). So of the two directions
// **only one is ever in effect**:
//
//     lock off  camera -> viewport, and pushed only once when the camera parameters **really changed**
//             (comparing a signature string). So you can tumble the viewport freely to inspect details without being yanked back;
//             only when the playbar advances a frame or a channel moves the camera does the viewport jump along.
//     lock on   viewport -> camera, written every tick (only when changed).
//
// ━━ Why write widgets rather than some other route
// The camera is just an ordinary node in the graph, and its parameters are widgets. Writing widgets is the only way to keep
// "what you see = what's saved = what runs" consistent: saving workflows, undo, copy-paste all work as usual.
//
// ━━ Recompute is queued only once **after you stop**
// While dragging the mouse, queueing every tick = dozens of jobs in the queue. So widget writes are continuous
// (parameters move live on screen), and queueing happens once, after parameters have been stable for SETTLE_MS.

const CAM_TYPE = "PCG_Camera";
const SETTLE_MS = 420;
const CAM_TICK_MS = 120;

/** All Camera (PCG) nodes in the graph. */
export function cameraNodes(graph) {
  return (graph?._nodes ?? []).filter((n) => n.type === CAM_TYPE);
}

function widget(node, name) {
  return (node?.widgets || []).find((w) => w.name === name);
}

function wval(node, name, dflt) {
  const w = widget(node, name);
  const v = w ? Number(w.value) : NaN;
  return Number.isFinite(v) ? v : dflt;
}

function wstr(node, name, dflt) {
  const w = widget(node, name);
  return w && w.value != null ? String(w.value) : dflt;
}

/**
 * Widgets of a Camera (PCG) node -> camera state.
 *
 * The three modes must be computed separately, because eye comes from different places:
 *   look_at   read eye_x/y/z directly
 *   orbit     computed from elev / azim / distance -- the formula must **match orbit_eye in geo/render.py
 *             exactly**, otherwise looking through the camera and the render differ by an axis
 *   frame     the distance is set automatically on the backend from the geometry's bounding sphere; the frontend **doesn't know** how big the geometry is.
 *             So this mode can only use the distance widget as an approximation, and says so in the panel.
 *             Guessing a distance would be worse: the framing looks right but the render is wrong.
 */
export function readCamera(node) {
  if (!node) return null;
  const mode = wstr(node, "mode", "look_at");
  const target = [wval(node, "target_x", 0), wval(node, "target_y", 0),
                  wval(node, "target_z", 0)];
  const fov = wval(node, "fov", 45);
  const dist = wval(node, "distance", 5);
  let eye;
  if (mode === "look_at") {
    eye = [wval(node, "eye_x", 0), wval(node, "eye_y", 0),
           wval(node, "eye_z", 5)];
  } else {
    const e = wval(node, "elev", 25) * Math.PI / 180;
    const a = wval(node, "azim", 35) * Math.PI / 180;
    eye = [target[0] + dist * Math.cos(e) * Math.sin(a),
           target[1] + dist * Math.sin(e),
           target[2] + dist * Math.cos(e) * Math.cos(a)];
  }
  return {
    mode, eye, target, fov,
    up: [wval(node, "up_x", 0), wval(node, "up_y", 1), wval(node, "up_z", 0)],
    xres: Math.round(wval(node, "resolution_x", 512)),
    yres: Math.round(wval(node, "resolution_y", 512)),
    projection: wstr(node, "projection", "perspective"),
    approx: mode === "frame",
  };
}

/** Camera state signature. Used to tell whether "the camera really changed", to avoid yanking the viewport back. */
export function camSignature(c) {
  if (!c) return "";
  return [c.mode, c.projection, c.fov, c.xres, c.yres,
          ...c.eye, ...c.target, ...c.up].map((x) =>
            typeof x === "number" ? x.toFixed(6) : x).join("|");
}

function setWidget(node, name, value) {
  const w = widget(node, name);
  if (!w) return false;
  if (typeof w.value === "number" && Math.abs(w.value - value) < 1e-9)
    return false;
  if (w.value === value) return false;
  w.value = value;
  // Some widgets hang logic on callback (linking, gate collapsing). Not calling it shows up as
  // "the value changed but the UI didn't follow", and only on some nodes
  try { w.callback?.(value, app.canvas, node); } catch (_) { /* must not be interrupted by this */ }
  return true;
}

/**
 * View -> widgets of the Camera node. Returns true if something really changed.
 *
 * **Changes mode to look_at.** The viewport gives a concrete camera position, while in the orbit / frame modes
 * the position is computed by the backend -- without changing mode the written eye has no effect at all, showing up as
 * "pressed the lock but the camera didn't move", with no error.
 */
export function writeCamera(node, st) {
  if (!node || !st) return false;
  let ch = setWidget(node, "mode", "look_at");
  const pairs = [["eye_x", st.eye[0]], ["eye_y", st.eye[1]],
                 ["eye_z", st.eye[2]],
                 ["target_x", st.target[0]], ["target_y", st.target[1]],
                 ["target_z", st.target[2]],
                 ["up_x", 0], ["up_y", 1], ["up_z", 0]];
  for (const [k, v] of pairs) ch = setWidget(node, k, v) || ch;
  return ch;
}

function camNode(graph) {
  if (S.cam.nodeId == null) return null;
  const n = graph?.getNodeById?.(S.cam.nodeId);
  return n && n.type === CAM_TYPE ? n : null;
}

/** Called every tick. Only one of the two directions is ever in effect; see the start of this section for why. */
export function syncCamera(graph) {
  if (!S.view) return;
  const node = camNode(graph);
  if (!node) {
    // Back to the free view: the gate guard is switched off unconditionally. It used to only switch off `if (S.camSig !== null)` --
    // but when the dropdown switched back to "free view", onchange first set camSig to null ("force one push"),
    // so the check here skipped it on the next tick and the camera frame stayed (a user-reported bug).
    // setGate(null) is idempotent; calling it every tick costs nothing
    if (S.view.gate) S.view.setGate(null);
    // fov is given back to the free view too: when looking through a camera setCameraState switched the viewport fov to the camera's;
    // without giving it back, switching back still shows telephoto / wide angle, and it looks like it didn't switch
    if (S.freeFov != null) { S.view.fov = S.freeFov; S.freeFov = null; }
    S.camSig = null;
    return;
  }
  if (S.freeFov == null) S.freeFov = S.view.fov;   // remember the free view's fov before entering the camera
  const c = readCamera(node);
  S.view.setGate(S.cam.gate ? { xres: c.xres, yres: c.yres } : null);
  if (S.cam.lock) {
    const st = S.view.getCameraState();
    if (writeCamera(node, st)) {
      S.camDirtyAt = Date.now();
      app.canvas?.setDirty?.(true, true);
    } else if (S.camDirtyAt && Date.now() - S.camDirtyAt > SETTLE_MS) {
      // Only queue once you stop. Queueing every tick while dragging would cram dozens of jobs into the queue
      S.camDirtyAt = 0;
      requestRun();
    }
    S.camSig = camSignature(readCamera(node));
    return;
  }
  const sig = camSignature(c);
  if (sig !== S.camSig) {
    S.camSig = sig;
    S.view.setCameraState(c);
  }
}

/** Options of the camera dropdown follow the graph. If the selected node was deleted, fall back to the free view. */
export function syncCamList(graph) {
  const sel = S.selCam;
  if (!sel) return;
  const nodes = cameraNodes(graph);
  const want = ["", ...nodes.map((n) => String(n.id))];
  const have = [...sel.options].map((o) => o.value);
  if (want.join() !== have.join()) {
    sel.textContent = "";
    for (const n of [null, ...nodes]) {
      const o = document.createElement("option");
      o.value = n ? String(n.id) : "";
      o.textContent = n
        ? `${n.title || CAM_TYPE} #${n.id}` : "Free view";
      sel.appendChild(o);
    }
  }
  const cur = S.cam.nodeId == null ? "" : String(S.cam.nodeId);
  if (!want.includes(cur)) {           // the camera node was deleted
    S.cam.nodeId = null;
    S.cam.lock = false;
    save();
  }
  sel.value = S.cam.nodeId == null ? "" : String(S.cam.nodeId);
  if (S.camNote) {
    const node = camNode(graph);
    const c = node ? readCamera(node) : null;
    const msg = [];
    if (c && c.approx)
      msg.push("mode=frame: the distance is set by the bounding sphere on the backend; the viewport can only approximate it");
    if (c && c.projection !== "perspective")
      msg.push("orthographic camera: the gate guide is correct, but the viewport projection is still perspective");
    if (c && Math.abs(c.up[1] - 1) + Math.abs(c.up[0]) + Math.abs(c.up[2]) > 1e-6)
      msg.push("up is not +Y: the viewport ignores roll");
    S.camNote.textContent = msg.length ? "⚠ " + msg.join(";") : "";
    S.camNote.style.display = msg.length ? "" : "none";
  }
}

// ════════════════════════════════════════════════════ auto recompute (coalesced)
function clearWatchdog() {
  if (S.watchdog) { clearTimeout(S.watchdog); S.watchdog = null; }
}

export function runDone() {
  S.inFlight = false;
  clearWatchdog();
  if (S.want) { S.want = false; requestRun(); }
}

/**
 * Queue one run. At most one job is in flight at any time; clicks in between coalesce into the last one.
 *
 * Without coalescing: click five nodes in a row -> five jobs in the queue -> all of them must finish, and they can't be
 * cancelled midway. All you want to see is the last one clicked.
 */
export function requestRun() {
  if (!S.autorun) return false;
  if (S.inFlight) { S.want = true; return false; }
  S.inFlight = true;
  S.want = false;
  clearWatchdog();
  // Watchdog: on some frontend versions the completion event never comes; without it inFlight would stay true forever,
  // showing up as "clicking flags never responds again" with no error.
  S.watchdog = setTimeout(() => {
    S.watchdog = null;
    S.inFlight = false;
    if (S.want) { S.want = false; requestRun(); }
  }, WATCHDOG_MS);
  try {
    const r = app.queuePrompt(0, 1);
    if (r && typeof r.then === "function")
      r.catch((e) => { console.warn("[pcg.display] queuePrompt failed:", e); });
  } catch (e) {
    console.warn("[pcg.display] queuePrompt failed:", e);
    S.inFlight = false;
    clearWatchdog();
  }
  return true;
}

// ════════════════════════════════════════════════════════════ panel
function css(el, s) { el.style.cssText = s; }

function mkBtn(label, tip, fn) {
  const b = document.createElement("button");
  b.textContent = label;
  b.title = tip;
  css(b, "background:#2a2f3a;color:#c8d0dc;border:1px solid #3a4150;" +
         "border-radius:3px;font:11px ui-monospace,monospace;padding:1px 5px;" +
         "cursor:pointer;flex:0 0 auto");
  b.onclick = fn;
  return b;
}

function mkSelect(key, values) {
  const s = document.createElement("select");
  css(s, "background:#2a2f3a;color:#c8d0dc;border:1px solid #3a4150;" +
         "border-radius:3px;font:11px ui-monospace,monospace;max-width:96px");
  s.title = key;
  // Marks "this is a render-option control". The test criterion "the control bar must cover every key of
  // DEFAULTS" collects by this mark -- the camera selector is also a select, but it isn't a render
  // option; without the mark it would be counted, and that criterion would be useless
  s.dataset.optkey = key;
  for (const v of values) {
    const o = document.createElement("option");
    o.value = o.textContent = v;
    s.appendChild(o);
  }
  s.value = S.opts[key];
  s.onchange = () => {
    S.opts[key] = s.value;
    S.view?.setOptions({ [key]: s.value });
    save();
  };
  return s;
}

/** Number input. Used for continuous values like normal_scale, which a dropdown can't express. */
function mkNumber(key, min, max, step) {
  const i = document.createElement("input");
  i.type = "number";
  i.min = String(min); i.max = String(max); i.step = String(step);
  i.value = String(S.opts[key]);
  i.title = key;
  i.dataset.numkey = key;
  css(i, "background:#2a2f3a;color:#c8d0dc;border:1px solid #3a4150;" +
         "border-radius:3px;font:11px ui-monospace,monospace;width:52px");
  i.oninput = () => {
    const v = parseFloat(i.value);
    if (!Number.isFinite(v)) return;          // don't write the option as NaN when the input box is cleared
    S.opts[key] = Math.min(max, Math.max(min, v));
    S.view?.setOptions({ [key]: S.opts[key] });
    save();
  };
  return i;
}

/** A small label in front of a control. With six dropdowns, title tooltips alone can't tell which is which. */
function labeled(text, el) {
  const w = document.createElement("span");
  css(w, "display:inline-flex;align-items:center;gap:2px;flex:0 0 auto");
  const l = document.createElement("span");
  l.textContent = text;
  css(l, "color:#6f7886;font:10px ui-monospace,monospace");
  w.appendChild(l);
  w.appendChild(el);
  return w;
}

function mkToggle(key, label) {
  const b = mkBtn(label, key, () => {
    S.opts[key] = !S.opts[key];
    S.view?.setOptions({ [key]: S.opts[key] });
    paint();
    save();
  });
  b.dataset.key = key;
  return b;
}

function paint() {
  if (!S.panel) return;
  for (const b of S.panel.querySelectorAll("button[data-key]")) {
    const on = !!S.opts[b.dataset.key];
    b.style.background = on ? "#3c5a86" : "#2a2f3a";
    b.style.color = on ? "#eaf2ff" : "#c8d0dc";
  }
  const ar = S.panel.querySelector("button[data-autorun]");
  if (ar) {
    ar.style.background = S.autorun ? "#3c5a86" : "#2a2f3a";
    ar.style.color = S.autorun ? "#eaf2ff" : "#c8d0dc";
  }
  // The two toggles of the camera row. Lock lights up **orange** rather than blue: blue buttons are everywhere in this
  // panel, and "lock" is the only state that changes parameters of nodes in the graph, so it has to be obvious at a glance
  // that it's on
  for (const b of S.panel.querySelectorAll("button[data-camkey]")) {
    const k = b.dataset.camkey;
    const on = !!S.cam[k];
    const hot = k === "lock";
    b.style.background = on ? (hot ? "#8a5a1e" : "#3c5a86") : "#2a2f3a";
    b.style.color = on ? "#fff3e0" : "#c8d0dc";
  }
}

function buildPanel() {
  if (S.panel) return S.panel;
  const p = document.createElement("div");
  const r = S.rect;
  if (r.x == null) { r.x = window.innerWidth - r.w - 24; r.y = 96; }
  css(p, `position:fixed;left:${r.x}px;top:${r.y}px;width:${r.w}px;` +
         `height:${r.h}px;z-index:900;background:#16181d;` +
         "border:1px solid #333a46;border-radius:6px;display:flex;" +
         "flex-direction:column;box-shadow:0 6px 24px #0008;" +
         "font:12px ui-sans-serif,system-ui");

  // ── title bar (also the drag handle)
  const head = document.createElement("div");
  css(head, "display:flex;align-items:center;gap:5px;padding:3px 5px;" +
            "background:#1e222a;border-bottom:1px solid #333a46;" +
            "border-radius:5px 5px 0 0;cursor:move;flex:0 0 auto");
  const dot = document.createElement("span");
  css(dot, `width:9px;height:9px;border-radius:2px;background:${C_DISP};` +
           "flex:0 0 auto");
  const title = document.createElement("span");
  css(title, "color:#8b95a3;font:11px ui-monospace,monospace;flex:1 1 auto;" +
             "overflow:hidden;text-overflow:ellipsis;white-space:nowrap");
  title.textContent = "No display flag -- click the blue square to the right of a node";
  S.title = title;

  const arBtn = mkBtn("↻", "Auto recompute after clicking a flag (off: press Run yourself)", () => {
    S.autorun = !S.autorun; paint(); save();
  });
  arBtn.dataset.autorun = "1";
  const frameBtn = mkBtn("⛶", "Frame the content in view (F)", () => S.view?.frameAll());
  const closeBtn = mkBtn("✕", "Close panel", () => setOpen(false));
  for (const x of [dot, title, arBtn, frameBtn, closeBtn]) head.appendChild(x);

  // ── control bar
  //
  // **Every key in DEFAULTS must have a control here.** The first version only wired up 6;
  // normals / show_normals / normal_scale / numbers were missing -- hence
  // "no normals visible in the panel". The in-node viewport had them all, so the two disagreed.
  // A test now watches this: the set of keys covered by controls must equal the key set of DEFAULTS.
  //
  // flex-wrap rather than horizontal scrolling: with many controls you'd never think of scrolling
  // to find what's hidden; wrapping at least shows everything at a glance.
  const bar = document.createElement("div");
  css(bar, "display:flex;align-items:center;gap:4px;padding:3px 5px;" +
           "background:#1a1e25;border-bottom:1px solid #2b313b;" +
           "flex:0 0 auto;flex-wrap:wrap");
  S.selShading = mkSelect("shading",
    ["phong", "lambert", "normal", "color", "uv", "wire"]);
  S.selNormals = mkSelect("normals", ["auto", "smooth", "vertex", "flat"]);
  S.selHL = mkSelect("highlight", ["none"]);
  S.selVZ = mkSelect("visualize", ["none"]);
  S.selShowN = mkSelect("show_normals", ["none", "point", "vertex", "prim"]);
  S.selNums = mkSelect("numbers", ["none", "point", "vertex", "prim"]);
  for (const x of [
    labeled("Shading", S.selShading),
    labeled("Normals", S.selNormals),
    labeled("Group", S.selHL),
    labeled("Attribute", S.selVZ),
    labeled("Normal arrows", S.selShowN),
    labeled("Length", mkNumber("normal_scale", 0.01, 4, 0.01)),
    labeled("Numbers", S.selNums),
    mkToggle("wireframe", "Wireframe"),
    mkToggle("show_points", "Points"),
    mkToggle("show_grid", "Grid"),
  ]) bar.appendChild(x);

  // ── camera bar
  //
  // Its own row, not squeezed into the control bar: the row above is "how to draw", this row is "where to look from".
  // Mixed together there'd be so many buttons nobody could find the lock.
  const cbar = document.createElement("div");
  css(cbar, "display:flex;align-items:center;gap:4px;padding:3px 5px;" +
            "background:#1a1e25;border-bottom:1px solid #2b313b;" +
            "flex:0 0 auto;flex-wrap:wrap");
  const selCam = document.createElement("select");
  css(selCam, "background:#2a2f3a;color:#c8d0dc;border:1px solid #3a4150;" +
              "border-radius:3px;font:11px ui-monospace,monospace;" +
              "max-width:150px");
  selCam.dataset.camsel = "1";
  selCam.title = "Which Camera (PCG) in the graph to look through";
  selCam.onchange = () => {
    S.cam.nodeId = selCam.value === "" ? null : Number(selCam.value);
    S.cam.lock = false;                 // unlock when switching cameras so the new camera doesn't get changed by accident
    S.camSig = null;                    // force one push
    paint();
    save();
  };
  S.selCam = selCam;

  const pullBtn = mkBtn("⦿", "Look through this camera (move the viewport to the camera)", () => {
    const n = camNode(app.graph);
    if (!n) return;
    S.camSig = null;
    syncCamera(app.graph);
  });
  const pushBtn = mkBtn("↥", "Write the current view into this camera (once)", () => {
    const n = camNode(app.graph);
    if (!n || !S.view) return;
    if (writeCamera(n, S.view.getCameraState())) {
      app.canvas?.setDirty?.(true, true);
      requestRun();
    }
  });
  const lockBtn = mkBtn("🔒", "Lock camera to view: tumbling the viewport then positions the camera", () => {
    S.cam.lock = !S.cam.lock;
    if (!S.cam.lock) S.camSig = null;   // after unlocking, back to "follow the camera"
    paint();
    save();
  });
  lockBtn.dataset.camkey = "lock";
  const gateBtn = mkBtn("▣", "Resolution gate: inside the frame is the rendered image", () => {
    S.cam.gate = !S.cam.gate;
    paint();
    save();
  });
  gateBtn.dataset.camkey = "gate";

  const note = document.createElement("span");
  css(note, "color:#c8a96a;font:10px ui-monospace,monospace;flex:1 1 100%;" +
            "display:none");
  S.camNote = note;
  for (const x of [labeled("Camera", selCam), pullBtn, pushBtn, lockBtn,
                   gateBtn, note]) cbar.appendChild(x);

  // ── canvas container
  const bodyEl = document.createElement("div");
  css(bodyEl, "flex:1 1 auto;min-height:80px;position:relative;" +
              "background:#1a1a1e;overflow:hidden");
  const label = document.createElement("div");
  css(label, "position:absolute;left:6px;bottom:4px;z-index:10;" +
             "font:10px ui-monospace,monospace;color:#8a8a96;" +
             "pointer-events:none;text-shadow:0 0 3px #1a1a1e");
  bodyEl.appendChild(label);
  S.label = label;
  S.body = bodyEl;

  // ── resize handle at bottom right
  const grip = document.createElement("div");
  css(grip, "position:absolute;right:0;bottom:0;width:14px;height:14px;" +
            "cursor:nwse-resize;z-index:20");
  bodyEl.appendChild(grip);

  for (const x of [head, bar, cbar, bodyEl]) p.appendChild(x);
  document.body.appendChild(p);
  S.panel = p;

  dragify(p, head, grip);
  buildToggle();            // must come before setOpen -- it colors the button
  paint();
  setOpen(S.open);
  return p;
}

function dragify(panel, head, grip) {
  let mode = null, ox = 0, oy = 0, w0 = 0, h0 = 0;
  const down = (kind) => (ev) => {
    mode = kind;
    ev.target.setPointerCapture?.(ev.pointerId);
    const r = panel.getBoundingClientRect();
    ox = ev.clientX - r.left; oy = ev.clientY - r.top;
    w0 = r.width; h0 = r.height;
    ev.preventDefault();
    ev.stopPropagation();
  };
  head.addEventListener("pointerdown", down("move"));
  grip.addEventListener("pointerdown", down("size"));
  const move = (ev) => {
    if (!mode) return;
    if (mode === "move") {
      // Clamp inside the window so it can't be dragged off screen and never dragged back
      const x = Math.max(0, Math.min(window.innerWidth - 60,
                                     ev.clientX - ox));
      const y = Math.max(0, Math.min(window.innerHeight - 30,
                                     ev.clientY - oy));
      panel.style.left = x + "px"; panel.style.top = y + "px";
      S.rect.x = x; S.rect.y = y;
    } else {
      const w = Math.max(240, w0 + (ev.clientX - (panel.offsetLeft + ox)));
      const h = Math.max(160, h0 + (ev.clientY - (panel.offsetTop + oy)));
      panel.style.width = w + "px"; panel.style.height = h + "px";
      S.rect.w = w; S.rect.h = h;
    }
  };
  const up = () => { if (mode) { mode = null; save(); } };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
  window.addEventListener("pointercancel", up);
}

/**
 * The persistent toggle button.
 *
 * **Must be attached to body, not put inside the panel** -- inside, once the panel is display:none
 * the button goes with it and can never be summoned again. A test watches exactly this.
 *
 * Placed at the bottom right: ComfyUI's own top bar, sidebar and node search don't use it, and the playbar is at the
 * bottom **center**, so the bottom right is one of the few places reliably empty.
 */
function buildToggle() {
  if (S.toggle) return S.toggle;
  const b = document.createElement("button");
  b.textContent = "3D";
  b.title = "Show / hide 3D panel";
  b.dataset.pcgToggle = "1";
  css(b, "position:fixed;right:16px;bottom:16px;z-index:899;" +
         "width:30px;height:30px;border-radius:6px;cursor:pointer;" +
         "border:1px solid #3a4150;font:11px ui-monospace,monospace;" +
         "box-shadow:0 2px 10px #0006");
  b.onclick = () => setOpen(!S.open);
  document.body.appendChild(b);
  S.toggle = b;
  return b;
}

function paintToggle() {
  if (!S.toggle) return;
  S.toggle.style.background = S.open ? "#3c5a86" : "#23272f";
  S.toggle.style.color = S.open ? "#eaf2ff" : "#8b95a3";
}

function setOpen(on) {
  S.open = !!on;
  if (S.panel) S.panel.style.display = S.open ? "flex" : "none";
  if (S.open) mountViewport();
  paintToggle();
  save();
}

/** three.js WebGL contexts are expensive, so one is only created when the panel is actually open. */
function mountViewport() {
  if (S.view || !S.body) return;
  try {
    S.view = new Viewport(S.body, S.opts);
  } catch (e) {
    S.label.textContent = "viewport failed to start: " + e.message;
    console.error("[pcg.display]", e);
    return;
  }
  if (S.lastNodeId != null) fetchInto(S.lastNodeId, null);
}

// ════════════════════════════════════════════════════════════ fetching data
export async function fetchInto(nodeId, rev, fetchFn) {
  S.lastNodeId = nodeId;
  if (!S.view) return false;
  const f = fetchFn || fetch;
  try {
    const res = await f(`/pcg/geo/${nodeId}?rev=${rev ?? Date.now()}`);
    if (!res.ok) {
      // 404 and not pushed after an execution -> this node hasn't run yet, exit silently
      if (res.status === 404 && rev == null) return false;
      throw new Error(await res.text());
    }
    const decoded = decode(await res.arrayBuffer());
    S.view.setGeometry(decoded);
    syncCombos();
    updateLabel(decoded);
    return true;
  } catch (e) {
    if (S.label) S.label.textContent = "viewport error: " + e.message;
    console.error("[pcg.display]", e);
    return false;
  }
}

/** Group and attribute names are only known at runtime; refill the dropdowns once data arrives. */
function syncCombos() {
  const fill = (sel, values, key) => {
    if (!sel) return;
    const keep = sel.value;
    sel.textContent = "";
    for (const v of values) {
      const o = document.createElement("option");
      o.value = o.textContent = v;
      sel.appendChild(o);
    }
    if (values.includes(keep)) {
      sel.value = keep;
    } else {
      sel.value = "none";
      S.opts[key] = "none";
      S.view?.setOptions({ [key]: "none" });
    }
  };
  fill(S.selHL, S.view.groupLabels(), "highlight");
  fill(S.selVZ, S.view.attribLabels(), "visualize");
}

function updateLabel(decoded) {
  if (decoded) S.counts = decoded.header.counts;
  const c = S.counts;
  if (!c || !S.label) return;
  S.label.textContent = [`pts ${c.points}`, `vtx ${c.verts}`,
                         `prims ${c.prims}`,
                         `N:${S.view?.shadingInfo ?? "-"}`].join("  ");
}

/** Show in the title bar who is currently displayed -- without it you'd never notice a mis-clicked flag. */
export function syncTitle(graph) {
  if (!S.title) return;
  const d = currentFlag(graph, "disp");
  const t = currentFlag(graph, "tmpl");
  if (!d) {
    S.title.textContent = "No display flag -- click the blue square to the right of a node";
    return;
  }
  const name = d.node.title || d.node.type || "?";
  let s = `${name} #${d.node.id}`;
  if (d.node.outputs?.length > 1) s += `[${d.slot}]`;
  if (t) s += `   tmpl: ${t.node.title || t.node.type} #${t.node.id}`;
  S.title.textContent = s;
}

// ════════════════════════════════════════════════════════════ registration
app.registerExtension({
  name: "pcg.display",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== SINK_TYPE) return;
    // When the Display node finishes, feed its data to the panel. Via node-level onExecuted rather than the global
    // api event: field names changed across frontend versions; the node-level path is stable on both generations.
    const onExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      onExecuted?.apply(this, arguments);
      const meta = message?.pcg_display?.[0];
      if (meta) {
        if (!S.panel) buildPanel();
        if (!S.open) setOpen(true);
        fetchInto(meta.node_id, meta.rev);
      }
    };
  },

  async setup() {
    load();
    buildPanel();
    try { syncCamList(app.graph); } catch (_) { /* graph not built yet; the tick will catch up */ }

    const canvas = app.canvas;
    const el = canvas?.canvas;
    if (!el) {
      console.warn("[pcg.display] cannot get the canvas, flags disabled (the panel still works)");
      return;
    }

    // ── drawing flags. Canvas-level onDrawForeground is in graph coordinates; use the node's pos directly.
    const prev = canvas.onDrawForeground;
    canvas.onDrawForeground = function (ctx, area) {
      prev?.apply(this, arguments);
      try {
        drawFlags(ctx, app.graph);
      } catch (e) {
        console.error("[pcg.display] error drawing flags", e);
      }
    };

    // ── clicking flags. Caught in the capture phase, otherwise litegraph would also start a box selection / node drag.
    // Only stopPropagation when a flag is really hit -- otherwise the whole canvas would become unclickable.
    const toGraph = (e) => {
      if (canvas.convertEventToCanvasOffset)
        return canvas.convertEventToCanvasOffset(e);
      const r = el.getBoundingClientRect();
      const ds = canvas.ds;
      return [(e.clientX - r.left) / ds.scale - ds.offset[0],
              (e.clientY - r.top) / ds.scale - ds.offset[1]];
    };

    el.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 && e.button !== 2) return;
      const hit = hitFlag(app.graph, toGraph(e));
      if (!hit) return;
      e.preventDefault();
      e.stopPropagation();
      // Right-click / Ctrl-click on the display square also counts as template, saving you from aiming at that small cell
      const kind = (e.button === 2 || e.ctrlKey || e.metaKey)
        ? "tmpl" : hit.kind;
      app.graph.beforeChange?.();
      const changed = setFlag(app.graph, kind, hit.node, hit.slot);
      app.graph.afterChange?.();
      if (changed) {
        if (!S.open) setOpen(true);
        syncTitle(app.graph);
        canvas.setDirty(true, true);
        requestRun();
      }
    }, true);

    // Don't pop up litegraph's menu on right-click over a flag
    el.addEventListener("contextmenu", (e) => {
      if (hitFlag(app.graph, toGraph(e))) {
        e.preventDefault();
        e.stopPropagation();
      }
    }, true);

    // ── hook all three completion events + watchdog; see item 3 of the file header for why
    for (const ev of ["executed", "execution_success", "status"])
      api.addEventListener?.(ev, runDone);

    // ── after a page refresh the frontend state is cleared but the server cache remains -- pull once proactively
    let tries = 0;
    const restore = () => {
      const sink = findSink(app.graph, false);
      if (!sink || sink.id == null || sink.id < 0) {
        if (++tries < 20) setTimeout(restore, 200);
        return;
      }
      syncTitle(app.graph);
      fetchInto(sink.id, null);
    };
    setTimeout(restore, 300);

    // After the graph changes (loading a workflow, undo, manual wiring) refresh the title and the camera list
    setInterval(() => {
      try { syncTitle(app.graph); syncCamList(app.graph); } catch (_) {}
    }, 700);

    // Camera linking gets its own faster tick: when locked this is the only driver of "tumble the viewport -> camera follows";
    // once every 700ms would lag noticeably. At 120ms each tick only compares a few numbers + occasionally writes
    // widgets; the overhead is negligible.
    setInterval(() => {
      try { syncCamera(app.graph); } catch (e) {
        if (!S.camErr) { S.camErr = true; console.error("[pcg.display] camera linking error", e); }
      }
    }, CAM_TICK_MS);
  },
});

// For unit tests: expose internal state so tests don't have to dig through the DOM
export const __state = S;
