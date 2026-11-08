// Frontend tests for the playbar. jsdom + stubbed app / api; the module really runs.
//
// What is tested here is not "what the buttons look like", but three pieces of logic that would hang ComfyUI or make the playbar silently
// stop working: queue coalescing, multi-path fallback for completion events + watchdog, shortcuts not stealing other people's keys.
import { JSDOM } from "jsdom";
import fs from "fs";
import os from "os";
import path from "path";

import { fileURLToPath } from "url";
// Package root: first search upward from this file's location, then fall back to the old sandbox path.
// These suites are now the only copy (the sandbox gets reclaimed), so paths can't be hard-coded any more
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
// A **new** temp directory per run (pcg64): it used to be hard-coded to "/tmp/jstest"; with two regressions running in parallel
// one side's rmSync hit files the other side was importing, which is how test_camlink once died; also
// test_icons / test_playbar used the same directory. Deleted after the run
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "jstest_"));
process.on("exit", () => fs.rmSync(ROOT, { recursive: true, force: true }));
const EXT = path.join(ROOT, "extensions", "comfyui_pcg");
fs.mkdirSync(path.join(ROOT, "scripts"), { recursive: true });
fs.mkdirSync(EXT, { recursive: true });

// ── stubs: app.js / api.js ────────────────────────────────────────────
fs.writeFileSync(path.join(ROOT, "scripts", "app.js"), `
export const app = globalThis.__app;
`);
fs.writeFileSync(path.join(ROOT, "scripts", "api.js"), `
export const api = globalThis.__api;
`);
fs.copyFileSync(path.join(PKG, "comfyui_pcg", "web", "pcg_playbar.js"),
                path.join(EXT, "pcg_playbar.js"));

const dom = new JSDOM("<!doctype html><html><body></body></html>",
                      { url: "http://localhost/", pretendToBeVisual: true });
for (const k of ["window", "document", "HTMLElement", "Node",
                 "localStorage", "KeyboardEvent", "Event", "CustomEvent"]) {
  // navigator is a read-only getter in node 22; skip it -- the playbar doesn't use it either
  Object.defineProperty(globalThis, k, {
    value: k === "window" ? dom.window : dom.window[k],
    writable: true, configurable: true,
  });
}
globalThis.requestAnimationFrame = (f) => setTimeout(f, 16);

const OK = [];
function check(name, cond, extra = "") {
  OK.push(!!cond);
  const tail = extra === "" ? "" : "   " + extra;
  console.log((cond ? "  PASS  " : "  FAIL  ") + name + tail);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ── fake graph ──────────────────────────────────────────────────────────
function frameNode(frame = 0, start = 0, end = 23, fps = 24) {
  const mk = (name, value) => ({ name, value, calls: 0,
                                 callback() { this.calls++; } });
  return { type: "PCG_Frame",
           widgets: [mk("frame", frame), mk("start", start),
                     mk("end", end), mk("fps", fps)] };
}
const W = (n, k) => n.widgets.find((w) => w.name === k);

const Q = { count: 0, frames: [] };
const nodes = [];
globalThis.__app = {
  graph: { _nodes: nodes, setDirtyCanvas() {} },
  canvas: {},
  exts: [],
  registerExtension(e) { this.exts.push(e); },
  queuePrompt() {
    Q.count++;
    Q.frames.push(nodes.filter((n) => n.type === "PCG_Frame")
      .map((n) => W(n, "frame").value)[0]);
    return Promise.resolve();
  },
};
const handlers = {};
globalThis.__api = {
  addEventListener(ev, fn) { (handlers[ev] ||= []).push(fn); },
};
function fire(ev, detail) {
  for (const fn of handlers[ev] || []) fn({ detail });
}

const mod = await import(path.join(EXT, "pcg_playbar.js"));
const ext = globalThis.__app.exts[0];
check("pcg.playbar extension registered", ext && ext.name === "pcg.playbar");
await ext.setup();

const bar = document.body.lastElementChild;
const q = (sel) => bar.querySelector(sel);
const byTitle = (t) => bar.querySelector(`[title^=${JSON.stringify(t)}]`);
const slider = q('input[type="range"]');
const fFrame = byTitle("Current frame");
const fStart = byTitle("Range start");
const fEnd = byTitle("Range end");
const bPlay = byTitle("Play");
const bNext = byTitle("Next frame");
const bPrev = byTitle("Previous frame");
const bFirst = byTitle("Go to start");
const bLast = byTitle("Jump to end");
const bLoop = byTitle("Loop playback");
const bLive = byTitle("Recompute live while scrubbing");
const bKeys = byTitle("Shortcuts");

console.log("═".repeat(28), "Visibility");
check("playbar hidden when there is no Frame node", bar.style.display === "none",
      JSON.stringify(bar.style.display));
const n1 = frameNode();
nodes.push(n1);
await sleep(500);
check("shown automatically once a Frame node appears in the graph", bar.style.display === "flex");
check("slider range follows start/end",
      slider.min === "0" && slider.max === "23", `${slider.min}..${slider.max}`);
nodes.length = 0;
await sleep(500);
check("hidden again after the node is deleted", bar.style.display === "none");
nodes.push(n1);
await sleep(500);
check("shown again when added back", bar.style.display === "flex");

console.log("═".repeat(28), "Queue coalescing (no queue flooding)");
Q.count = 0; Q.frames.length = 0;
// Simulate dragging the slider: 40 input events in a row, no completion event in between
for (let i = 1; i <= 40; i++) {
  slider.value = String(i % 24);
  slider.dispatchEvent(new dom.window.Event("input"));
}
check("40 drags queued only 1 job (the rest coalesced)", Q.count === 1, `count=${Q.count}`);
check("the frame on the node still follows the drag live (visible on the canvas)",
      W(n1, "frame").value === 40 % 24, W(n1, "frame").value);
const lastDrag = 40 % 24;
fire("execution_success", {});
await sleep(20);
check("after the previous one finishes, the **last** frame gets queued", Q.count === 2,
      `count=${Q.count}`);
check("the one queued is exactly the last frame dragged to", Q.frames[1] === lastDrag,
      `${Q.frames[1]} vs ${lastDrag}`);
fire("execution_success", {});
await sleep(20);
check("nothing queued again when there is no backlog", Q.count === 2, `count=${Q.count}`);

console.log("═".repeat(28), "Multi-path fallback for completion events");
Q.count = 0;
slider.value = "5";
slider.dispatchEvent(new dom.window.Event("change"));
check("release queued one", Q.count === 1);
fire("status", { exec_info: { queue_remaining: 0 } });
slider.value = "6";
slider.dispatchEvent(new dom.window.Event("change"));
check("status.queue_remaining=0 also unlocks", Q.count === 2, `count=${Q.count}`);
fire("execution_error", {});
slider.value = "7";
slider.dispatchEvent(new dom.window.Event("change"));
check("execution_error also unlocks (an error shouldn't lock up the playbar)", Q.count === 3);
fire("execution_interrupted", {});

console.log("═".repeat(28), "Watchdog");
Q.count = 0;
slider.value = "9";
slider.dispatchEvent(new dom.window.Event("change"));
check("one queued, in-flight", Q.count === 1);
slider.value = "10";
slider.dispatchEvent(new dom.window.Event("change"));
check("nothing more queued while in-flight", Q.count === 1);
const realNow = Date.now;
Date.now = () => realNow() + 40000;          // move the clock forward 40 seconds
await sleep(500);
Date.now = realNow;
slider.value = "11";
slider.dispatchEvent(new dom.window.Event("change"));
check("when the completion event never arrives, the watchdog unlocks by itself after 30s", Q.count === 2,
      `count=${Q.count}`);
fire("execution_success", {});

console.log("═".repeat(28), "Step / endpoints / loop");
Q.count = 0;
W(n1, "frame").value = 22;
await sleep(450);
bNext.dispatchEvent(new dom.window.Event("click"));
check("next frame", W(n1, "frame").value === 23, W(n1, "frame").value);
fire("execution_success", {});
bNext.dispatchEvent(new dom.window.Event("click"));
check("past the end loops back to the start (loop on by default)", W(n1, "frame").value === 0,
      W(n1, "frame").value);
fire("execution_success", {});
bPrev.dispatchEvent(new dom.window.Event("click"));
check("stepping back from the start wraps to the end", W(n1, "frame").value === 23,
      W(n1, "frame").value);
fire("execution_success", {});
bLoop.dispatchEvent(new dom.window.Event("click"));   // turn loop off
bNext.dispatchEvent(new dom.window.Event("click"));
check("with loop off it stops at the end", W(n1, "frame").value === 23,
      W(n1, "frame").value);
fire("execution_success", {});
bFirst.dispatchEvent(new dom.window.Event("click"));
check("⏮ go to start", W(n1, "frame").value === 0);
fire("execution_success", {});
bLast.dispatchEvent(new dom.window.Event("click"));
check("⏭ go to end", W(n1, "frame").value === 23);
fire("execution_success", {});
bLoop.dispatchEvent(new dom.window.Event("click"));   // turn it back on

console.log("═".repeat(28), "Reversed range (end < start)");
W(n1, "start").value = 10; W(n1, "end").value = 4; W(n1, "frame").value = 10;
await sleep(450);
check("slider range takes min/max, doesn't become empty",
      slider.min === "4" && slider.max === "10", `${slider.min}..${slider.max}`);
bPrev.dispatchEvent(new dom.window.Event("click"));
check("stepping in a reversed range doesn't leave the interval",
      W(n1, "frame").value >= 4 && W(n1, "frame").value <= 10,
      W(n1, "frame").value);
fire("execution_success", {});
W(n1, "start").value = 0; W(n1, "end").value = 23; W(n1, "frame").value = 0;
await sleep(450);

console.log("═".repeat(28), "Playback");
Q.count = 0;
W(n1, "fps").value = 1000;                   // so fps isn't the bottleneck
bPlay.dispatchEvent(new dom.window.Event("click"));
check("button turns into pause", bPlay.textContent === "⏸", bPlay.textContent);
for (let i = 0; i < 6; i++) { await sleep(15); fire("execution_success", {}); }
await sleep(60);
check("playback advances frame by frame", W(n1, "frame").value >= 4,
      `frame=${W(n1, "frame").value}, queued=${Q.count}`);
check("at most one in flight during playback too (queued count ≈ completed count)",
      Q.count <= 8, `count=${Q.count}`);
bPlay.dispatchEvent(new dom.window.Event("click"));
await sleep(60);
const stopped = W(n1, "frame").value;
fire("execution_success", {});
await sleep(80);
check("no more advancing after pause", W(n1, "frame").value === stopped,
      `${stopped} -> ${W(n1, "frame").value}`);

console.log("═".repeat(28), "Multiple Frame nodes");
const n2 = frameNode(0, 12, 18, 24);
nodes.push(n2);
await sleep(450);
bLast.dispatchEvent(new dom.window.Event("click"));
check("frame written to **all** Frame nodes (one timeline)",
      W(n1, "frame").value === W(n2, "frame").value,
      `${W(n1, "frame").value} / ${W(n2, "frame").value}`);
check("start/end written only to the first (each keeps its own range)",
      W(n2, "start").value === 12 && W(n2, "end").value === 18,
      `${W(n2, "start").value}..${W(n2, "end").value}`);
check("status bar shows the node count", /×2/.test(bar.textContent), bar.textContent.trim());
fire("execution_success", {});
nodes.pop();
await sleep(450);

console.log("═".repeat(28), "Shortcuts don't steal other people's keys");
W(n1, "frame").value = 5;
await sleep(450);
const key = (code, opts = {}) => {
  const ev = new dom.window.KeyboardEvent("keydown",
    { code, bubbles: true, cancelable: true, ...opts });
  (opts.target || document.body).dispatchEvent(ev);
  return ev;
};
Q.count = 0;
let ev = key("ArrowRight");
check("→ steps", W(n1, "frame").value === 6, W(n1, "frame").value);
check("handled keys call preventDefault", ev.defaultPrevented);
fire("execution_success", {});
ev = key("ArrowLeft");
check("← steps", W(n1, "frame").value === 5);
fire("execution_success", {});
ev = key("KeyA");
check("unhandled keys don't preventDefault (don't steal others' shortcuts)", !ev.defaultPrevented);
ev = key("ArrowRight", { ctrlKey: true });
check("no response with modifier keys", W(n1, "frame").value === 5 && !ev.defaultPrevented);
const inp = document.createElement("input");
document.body.appendChild(inp);
ev = key("Space", { target: inp });
check("no response while focus is in an input box", !ev.defaultPrevented);
ev = key("Space");
check("Space toggles playback", bPlay.textContent === "⏸");
key("Space");
check("pressing again pauses", bPlay.textContent === "▶");
bKeys.dispatchEvent(new dom.window.Event("click"));    // turn shortcuts off
ev = key("ArrowRight");
check("with ⌨ off nothing responds", !ev.defaultPrevented);
bKeys.dispatchEvent(new dom.window.Event("click"));

console.log("═".repeat(28), "Live recompute toggle");
bLive.dispatchEvent(new dom.window.Event("click"));    // turn live off
fire("execution_success", {});
Q.count = 0;
for (let i = 0; i < 10; i++) {
  slider.value = String(i); slider.dispatchEvent(new dom.window.Event("input"));
}
check("with ≈ off, nothing gets queued during the drag", Q.count === 0, `count=${Q.count}`);
check("but the value on the node still updates live (visible on the canvas)",
      W(n1, "frame").value === 9, W(n1, "frame").value);
slider.dispatchEvent(new dom.window.Event("change"));
check("queued once on release", Q.count === 1);
fire("execution_success", {});
bLive.dispatchEvent(new dom.window.Event("click"));

console.log("═".repeat(28), "Misc");
check("editing the frame input directly gets clamped into range", (() => {
  fFrame.value = "9999";
  fFrame.dispatchEvent(new dom.window.Event("change"));
  fire("execution_success", {});
  return W(n1, "frame").value === 23;
})(), W(n1, "frame").value);
check("start/end inputs can change the range", (() => {
  fStart.value = "2"; fStart.dispatchEvent(new dom.window.Event("change"));
  fEnd.value = "7"; fEnd.dispatchEvent(new dom.window.Event("change"));
  return W(n1, "start").value === 2 && W(n1, "end").value === 7;
})(), `${W(n1, "start").value}..${W(n1, "end").value}`);
check("the widget's callback was called (some nodes hook logic onto it)",
      W(n1, "frame").calls > 0, W(n1, "frame").calls);
check("toggle state saved to localStorage",
      /"loop"/.test(localStorage.getItem("pcg.playbar.v1") || ""),
      localStorage.getItem("pcg.playbar.v1"));
check("playbar docked bottom-center by default (same place as Houdini)",
      bar.style.bottom === "16px" && bar.style.left === "50%");
check("z-index below the node search panel (10000), doesn't cover it",
      Number(bar.style.zIndex) < 10000, bar.style.zIndex);

const pass = OK.filter(Boolean).length;
console.log(`\n${pass}/${OK.length} passed`);
process.exit(pass === OK.length ? 0 : 1);
