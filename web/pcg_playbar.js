// comfyui_pcg/web/pcg_playbar.js
//
// Houdini's playbar. Whenever the graph has a Frame (PCG) node it appears automatically at the bottom of the screen:
// scrub, play, step, set the range; the graph recomputes at whatever frame you scrub to.
//
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Three problems that must be handled right (getting the first two wrong freezes ComfyUI outright)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 1) **Don't flood the queue.** ComfyUI's queuePrompt pushes onto a queue; it doesn't execute synchronously.
//    Dragging the slider fires dozens to hundreds of input events; queueing each one fills the queue with hundreds of jobs instantly,
//    which keep running for minutes after you release -- and can't be cancelled midway.
//    So at all times there is **at most one job in flight**: while in flight we only record "the frame I want"
//    in wantFrame, and once the current one finishes we queue once more with the latest value. The frames in between are simply
//    dropped, which is exactly how scrubbing a timeline should behave (you want the frame you release on, not every frame passed).
//
// 2) **Don't trust a single completion event.** Across frontend versions the timing and fields of execution_success /
//    executed / status have all changed. Hooking only one means that on some version
//    the event never comes -> pending stays true forever -> the playbar stops dead after the first frame, with
//    no error; it just looks "broken". So all three are hooked, plus a 30-second watchdog as a fallback.
//
// 3) **Don't steal the keyboard.** Space / left-right arrows are used by other plugins and input boxes. So we only respond when
//    (a) focus is not in an input box, (b) no modifier is pressed, (c) the playbar is visible -- all three at once,
//    and only call preventDefault when we actually responded. There's also a ⌨ toggle.
//
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Why not a "global $F"
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// The frame number is written into the widget of the Frame (PCG) node, i.e. it travels along a real edge in the graph.
// ComfyUI's cache is keyed by input hash: when frame changes, the Frame node's hash changes, and everything **downstream** of it
// is invalidated and recomputed, while upstream and side branches are reused as-is. A scrub recomputes only what must be recomputed.
// An actual environment variable would be worse on both ends: the cache can't see the dependency, so either the whole graph recomputes (each scrub stalls for half
// a minute), or what should recompute doesn't (scrubbing does nothing).
//
// Plain DOM: doesn't touch the widget system, doesn't modify the node.widgets array, doesn't hook litegraph's key
// dispatch (which behaves inconsistently across versions). Nodes are found by type string, widgets by name.

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_TYPE = "PCG_Frame";
const LS_KEY = "pcg.playbar.v1";
const WATCHDOG_MS = 30000;

const S = {
  bar: null, el: {}, visible: false,
  playing: false, loop: true, live: true, keys: true,
  pending: false, wantFrame: null, watchdog: 0, lastStart: 0,
  dragging: false,
};

// ─────────────────────────────────────────────────────────── reading / writing the graph
function graphNodes() {
  const g = app.graph;
  if (!g) return [];
  // The old frontend has _nodes, the new litegraph provides nodes; try both, don't bet on one
  return g._nodes || g.nodes || [];
}

function frameNodes() {
  return graphNodes().filter((n) => n && n.type === NODE_TYPE && !n.mode3);
}

function W(node, name) {
  return (node.widgets || []).find((w) => w.name === name);
}

function readState() {
  const ns = frameNodes();
  if (!ns.length) return null;
  const n = ns[0];
  const g = (k, d) => {
    const w = W(n, k);
    return w && w.value !== undefined && w.value !== null ? Number(w.value) : d;
  };
  return { frame: g("frame", 0), start: g("start", 0), end: g("end", 23),
           fps: g("fps", 24), count: ns.length };
}

function writeAll(key, value) {
  // One timeline, so the same frame is written into **all** Frame nodes. start/end/fps are only written to
  // the first one -- those are each node's own range (main 0-23, branch 12-18 is a common setup)
  const ns = frameNodes();
  const targets = key === "frame" ? ns : ns.slice(0, 1);
  for (const n of targets) {
    const w = W(n, key);
    if (!w) continue;
    w.value = value;
    // Some nodes hang logic on the widget's own callback; call it to stay consistent
    try { w.callback?.(value, app.canvas, n); } catch (e) { /* doesn't matter */ }
  }
  app.graph?.setDirtyCanvas(true, true);
}

// ─────────────────────────────────────────────────────────── queue
function queueNow() {
  S.pending = true;
  S.watchdog = Date.now();
  try {
    const r = app.queuePrompt(0, 1);
    // queuePrompt returns a Promise on some versions and undefined on others. If it returns a Promise
    // the reject must be caught, otherwise the console fills with red and pending gets stuck
    if (r && typeof r.catch === "function") r.catch(() => done());
  } catch (e) {
    console.warn("[pcg.playbar] queuePrompt failed:", e);
    done();
  }
}

function request(frame) {
  if (frame !== null && frame !== undefined) writeAll("frame", frame);
  if (S.pending) { S.wantFrame = frame; return; }   // only remember the latest; drop the ones in between
  S.wantFrame = null;
  queueNow();
}

function done() {
  if (!S.pending) return;
  S.pending = false;
  if (S.wantFrame !== null && S.wantFrame !== undefined) {
    const f = S.wantFrame; S.wantFrame = null;
    request(f);
    return;
  }
  if (S.playing) scheduleNext();
}

function scheduleNext() {
  const st = readState();
  if (!st) { setPlaying(false); return; }
  const dir = st.end >= st.start ? 1 : -1;
  let f = st.frame + dir;
  const lo = Math.min(st.start, st.end), hi = Math.max(st.start, st.end);
  if (f > hi || f < lo) {
    if (!S.loop) { setPlaying(false); sync(); return; }
    f = dir > 0 ? lo : hi;
  }
  // fps is an **upper limit**, not a guarantee: if the graph runs slower than fps, it runs as slow as it runs.
  // Conversely, when the graph is fast, sleep a bit so a 24fps animation doesn't rush through at 200fps
  const spent = Date.now() - S.lastStart;
  const budget = 1000 / Math.max(st.fps, 0.01);
  const wait = Math.max(0, budget - spent);
  setTimeout(() => {
    if (!S.playing) return;
    S.lastStart = Date.now();
    request(f);
    sync();
  }, wait);
}

// Hook all three events: different frontend versions fire different ones
for (const ev of ["execution_success", "execution_error",
                  "execution_interrupted"]) {
  api.addEventListener(ev, () => done());
}
api.addEventListener("status", (e) => {
  const q = e?.detail?.exec_info?.queue_remaining;
  if (q === 0) done();
});

// ─────────────────────────────────────────────────────────── UI
function css(el, s) { el.style.cssText = s; }

function btn(label, title, fn) {
  const b = document.createElement("button");
  b.textContent = label;
  b.title = title;
  css(b, `background:#252b33;color:#dde3ea;border:1px solid #3a4049;
    border-radius:5px;min-width:26px;height:24px;padding:0 6px;cursor:pointer;
    font:12px ui-monospace,Menlo,Consolas,monospace;line-height:22px`);
  b.onmouseenter = () => (b.style.background = "#2f3742");
  b.onmouseleave = () => (b.style.background = b.dataset.on === "1"
    ? "#3d6ea8" : "#252b33");
  b.onclick = (e) => { e.preventDefault(); fn(); };
  return b;
}

function num(width, title, fn) {
  const i = document.createElement("input");
  i.type = "number";
  i.title = title;
  css(i, `width:${width}px;height:24px;background:#181c22;color:#dde3ea;
    border:1px solid #3a4049;border-radius:5px;text-align:center;
    font:12px ui-monospace,Menlo,Consolas,monospace`);
  i.onchange = () => fn(Number(i.value));
  // Space/arrow keys in an input box must not trigger the playbar shortcuts -- swallow them here
  i.onkeydown = (e) => e.stopPropagation();
  return i;
}

function build() {
  const bar = document.createElement("div");
  css(bar, `position:fixed;z-index:9000;display:none;align-items:center;gap:6px;
    padding:7px 10px;background:#1c2027ee;border:1px solid #3a4049;
    border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.5);
    backdrop-filter:blur(6px);
    font:12px ui-monospace,Menlo,Consolas,monospace;color:#dde3ea;
    user-select:none`);

  const grip = document.createElement("div");
  grip.textContent = "⠿";
  grip.title = "Drag the playbar";
  css(grip, "cursor:move;padding:0 4px;color:#6b7785;font-size:14px");

  const e = S.el;
  e.start = num(52, "Range start", (v) => { writeAll("start", v | 0); sync(); });
  e.end = num(52, "Range end", (v) => { writeAll("end", v | 0); sync(); });
  e.frame = num(58, "Current frame", (v) => { request(clampFrame(v | 0)); sync(); });
  e.fps = num(50, "Frames per second (upper limit of playback speed)", (v) => {
    writeAll("fps", v); sync();
  });

  e.slider = document.createElement("input");
  e.slider.type = "range";
  css(e.slider, "flex:1;min-width:180px;height:24px;accent-color:#4a90d9;cursor:pointer");
  e.slider.oninput = () => {
    S.dragging = true;
    const f = Number(e.slider.value);
    writeAll("frame", f);
    e.frame.value = f;
    if (S.live) request(f);            // already coalesced, at most one in flight
  };
  e.slider.onchange = () => {
    S.dragging = false;
    request(Number(e.slider.value));   // the frame released on must always be queued
  };

  e.first = btn("⏮", "Go to start", () => { request(rangeLo()); sync(); });
  e.prev = btn("◀", "Previous frame", () => { step(-1); });
  e.play = btn("▶", "Play / pause (Space)", () => setPlaying(!S.playing));
  e.next = btn("▶|", "Next frame", () => { step(1); });
  e.last = btn("⏭", "Jump to end", () => { request(rangeHi()); sync(); });

  e.loop = btn("⟳", "Loop playback", () => { S.loop = !S.loop; save(); sync(); });
  e.live = btn("≈", "Recompute live while scrubbing (off: compute once on release)", () => {
    S.live = !S.live; save(); sync();
  });
  e.keys = btn("⌨", "Shortcuts: Space play/pause, ← → step", () => {
    S.keys = !S.keys; save(); sync();
  });
  e.status = document.createElement("span");
  css(e.status, "color:#8b95a3;min-width:84px;text-align:right");

  for (const x of [grip, e.start, e.first, e.prev, e.play, e.next, e.last,
                   e.frame, e.slider, e.end, e.fps, e.loop, e.live, e.keys,
                   e.status]) bar.appendChild(x);
  document.body.appendChild(bar);
  S.bar = bar;
  dragify(bar, grip);
  restore();
  return bar;
}

function dragify(bar, grip) {
  let ox = 0, oy = 0, on = false;
  grip.onpointerdown = (ev) => {
    on = true; grip.setPointerCapture(ev.pointerId);
    const r = bar.getBoundingClientRect();
    ox = ev.clientX - r.left; oy = ev.clientY - r.top;
    ev.preventDefault();
  };
  grip.onpointermove = (ev) => {
    if (!on) return;
    const x = Math.max(4, Math.min(window.innerWidth - 80, ev.clientX - ox));
    const y = Math.max(4, Math.min(window.innerHeight - 40, ev.clientY - oy));
    bar.style.left = x + "px";
    bar.style.top = y + "px";
    bar.style.bottom = "auto";
    bar.style.transform = "none";
  };
  grip.onpointerup = (ev) => {
    on = false;
    try { grip.releasePointerCapture(ev.pointerId); } catch (e) { /* ok */ }
    save();
  };
}

function save() {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify({
      left: S.bar?.style.left || "", top: S.bar?.style.top || "",
      loop: S.loop, live: S.live, keys: S.keys,
    }));
  } catch (e) { /* throws in private mode; doesn't affect functionality */ }
}

function restore() {
  let v = null;
  try { v = JSON.parse(localStorage.getItem(LS_KEY) || "null"); }
  catch (e) { v = null; }
  if (!v) {                       // default: docked bottom center, same place as Houdini
    S.bar.style.left = "50%";
    S.bar.style.bottom = "16px";
    S.bar.style.transform = "translateX(-50%)";
    return;
  }
  if (v.left) {
    S.bar.style.left = v.left; S.bar.style.top = v.top;
    S.bar.style.bottom = "auto"; S.bar.style.transform = "none";
  } else {
    S.bar.style.left = "50%"; S.bar.style.bottom = "16px";
    S.bar.style.transform = "translateX(-50%)";
  }
  if (typeof v.loop === "boolean") S.loop = v.loop;
  if (typeof v.live === "boolean") S.live = v.live;
  if (typeof v.keys === "boolean") S.keys = v.keys;
}

// ─────────────────────────────────────────────────────────── behaviour
function rangeLo() { const s = readState(); return Math.min(s.start, s.end); }
function rangeHi() { const s = readState(); return Math.max(s.start, s.end); }

function clampFrame(f) {
  const s = readState();
  if (!s) return f;
  return Math.max(Math.min(s.start, s.end), Math.min(Math.max(s.start, s.end), f));
}

function step(d) {
  const s = readState();
  if (!s) return;
  let f = s.frame + d;
  const lo = Math.min(s.start, s.end), hi = Math.max(s.start, s.end);
  if (f > hi) f = S.loop ? lo : hi;
  if (f < lo) f = S.loop ? hi : lo;
  request(f);
  sync();
}

function setPlaying(on) {
  S.playing = !!on;
  if (S.playing) {
    S.lastStart = Date.now();
    if (!S.pending) scheduleNext();    // if one is running, wait for it to finish and continue
  }
  sync();
}

function sync() {
  const st = readState();
  const show = !!st;
  if (show !== S.visible) {
    S.visible = show;
    S.bar.style.display = show ? "flex" : "none";
    if (!show) S.playing = false;
  }
  if (!show) return;
  const e = S.el;
  const lo = Math.min(st.start, st.end), hi = Math.max(st.start, st.end);
  if (document.activeElement !== e.start) e.start.value = st.start;
  if (document.activeElement !== e.end) e.end.value = st.end;
  if (document.activeElement !== e.fps) e.fps.value = st.fps;
  if (document.activeElement !== e.frame) e.frame.value = st.frame;
  e.slider.min = lo; e.slider.max = hi; e.slider.step = 1;
  if (!S.dragging) e.slider.value = st.frame;
  e.play.textContent = S.playing ? "⏸" : "▶";
  for (const [b, on] of [[e.loop, S.loop], [e.live, S.live],
                         [e.keys, S.keys]]) {
    b.dataset.on = on ? "1" : "0";
    b.style.background = on ? "#3d6ea8" : "#252b33";
  }
  const n = hi - lo + 1;
  e.status.textContent = (S.pending ? "● " : "○ ")
    + `${st.frame - lo + 1}/${n}` + (st.count > 1 ? ` ×${st.count}` : "");
  e.status.style.color = S.pending ? "#d8a657" : "#8b95a3";
}

// ─────────────────────────────────────────────────────────── shortcuts
function typing(t) {
  return t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable);
}

document.addEventListener("keydown", (ev) => {
  if (!S.keys || !S.visible) return;
  if (ev.ctrlKey || ev.altKey || ev.metaKey || ev.shiftKey) return;
  if (typing(ev.target)) return;
  if (ev.code === "Space") { setPlaying(!S.playing); }
  else if (ev.code === "ArrowLeft") { step(-1); }
  else if (ev.code === "ArrowRight") { step(1); }
  else return;
  ev.preventDefault();           // only intercept when we actually responded; don't steal others' keys
  ev.stopPropagation();
}, true);

// ─────────────────────────────────────────────────────────── polling
// Polling rather than hooking onNodeAdded / onNodeRemoved / onConfigure: across frontend versions some of those hooks
// don't fire, some get overridden by other plugins, and loading a workflow goes down yet another
// path. Scanning the node list every 400ms (string comparisons over a few hundred nodes) costs negligibly, and buys
// "found no matter how it got in"
setInterval(() => {
  if (!S.bar) return;
  // Watchdog: if the completion event never comes, don't let the playbar stay stuck in pending forever
  if (S.pending && Date.now() - S.watchdog > WATCHDOG_MS) {
    console.warn("[pcg.playbar] timed out waiting for execution to finish, unlocking");
    S.pending = false;
    S.wantFrame = null;
  }
  sync();
}, 400);

app.registerExtension({
  name: "pcg.playbar",
  async setup() {
    build();
    sync();
  },
});
