// The **math** of viewport <-> camera node. jsdom + a stubbed app; calls Viewport's methods directly.
//
// Viewport as a whole needs WebGL and pulls three.js from a CDN, which can't start in jsdom. But these methods
// (getCameraState / setCameraState / gateRect / effectiveFov) only read and write
// this.orbit / this.fov / this.gate and don't touch the renderer. So here we build an object **whose prototype is the real
// Viewport.prototype** and that carries only these three fields -- it tests the real code,
// not a copy of it.
//
// This suite watches four things that fail silently:
//
//  1) **Spherical coordinate convention disagrees with the Python side.** The viewport uses (theta, phi), the renderer uses
//     (azim, elev) -- off by a sign, or sin/cos swapped, and the view still "looks reasonable",
//     but the rendered image is not from the angle seen in the viewport. "What you see in the gate is what you get" is broken,
//     with no error at all. So a golden reference table **computed in Python** is embedded here
//     (orbit_eye in geo/render.py), and JS must match it point by point.
//  2) **Round trip is not the identity.** eye -> spherical -> eye must come back to where it started (to floating-point precision).
//     Otherwise "lock camera to view" makes the camera position drift a little every tick.
//  3) **Field of view inside the gate != rendered field of view.** If the camera fov is given straight to the viewport, what is seen
//     inside the gate is **narrower** than what actually renders (the gate is shorter than the viewport). This error is subtle: the aspect is right,
//     the extent is just a bit smaller. The criterion is analytic: the world half-height inside the gate at the target distance must equal
//     the camera's world half-height at the same distance.
//  4) **Degenerate input spits NaN.** eye == target, parallel up, fov 0 -- one NaN getting into
//     orbit turns the whole viewport black, and the next frame is NaN again, with no clue where it came from.
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
// A **new** temp directory per run (pcg64): it used to be hard-coded to "/tmp/jstest_cam"; with two regressions running in parallel
// one side's rmSync hit files the other side was importing, which is how test_camlink once died; also
// test_icons / test_playbar used the same directory. Deleted after the run
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "jstest_cam_"));
process.on("exit", () => fs.rmSync(ROOT, { recursive: true, force: true }));
const EXT = path.join(ROOT, "extensions", "comfyui_pcg");
fs.mkdirSync(path.join(ROOT, "scripts"), { recursive: true });
fs.mkdirSync(EXT, { recursive: true });
fs.writeFileSync(path.join(ROOT, "scripts", "app.js"),
                 "export const app = globalThis.__app;\n");
fs.copyFileSync(path.join(PKG, "comfyui_pcg", "web", "pcg_viewport.js"),
                path.join(EXT, "pcg_viewport.js"));
// pcg106: pcg_viewport.js imports the volume renderer
fs.copyFileSync(path.join(PKG, "comfyui_pcg", "web", "pcg_volume.js"),
                path.join(EXT, "pcg_volume.js"));

const dom = new JSDOM("<!doctype html><html><body></body></html>",
                      { url: "http://localhost/" });
for (const k of ["window", "document", "HTMLElement", "Node"]) {
  Object.defineProperty(globalThis, k, {
    value: k === "window" ? dom.window : dom.window[k],
    writable: true, configurable: true,
  });
}
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};
globalThis.__app = { registerExtension() {}, graph: { _nodes: [] } };

const OK = [];
function check(name, cond, extra = "") {
  OK.push(!!cond);
  const tail = extra === "" ? "" : "   " + extra;
  console.log((cond ? "  PASS  " : "  FAIL  ") + name + tail);
}
function sec(t) { console.log("\n" + "═".repeat(28) + " " + t); }

const M = await import(path.join(EXT, "pcg_viewport.js"));
const V = M.Viewport.prototype;

/**
 * A bare "viewport": its prototype is the **real** Viewport.prototype, and it carries only the fields these methods
 * touch. That way internal calls like this.gateRect inside effectiveFov still work --
 * attaching methods one by one with .call() bit us here: effectiveFov calling this.gateRect threw a
 * TypeError, and that is exactly the path that most needs testing.
 */
function mkView(orbit, fov, gate) {
  return Object.assign(Object.create(M.Viewport.prototype), {
    orbit: orbit || { theta: 0.7, phi: 1.1, dist: 5, target: [0, 0, 0] },
    fov: fov ?? 45,
    gate: gate ?? null,
    gridScaled: 0,
    updateGridScale() { this.gridScaled++; },
  });
}
const getCam = (v) => v.getCameraState();
const setCam = (v, c) => v.setCameraState(c);
const gateRect = (v, w, h) => v.gateRect(w, h);
const effFov = (v, w, h) => v.effectiveFov(w, h);

const D2R = Math.PI / 180;
const norm = (a) => Math.hypot(a[0], a[1], a[2]);
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const maxAbs = (a) => Math.max(...a.map(Math.abs));


// ═════════════════════════════════════════ 1. Against the Python golden reference
sec("Spherical coordinate convention (against the Python golden reference)");
//
// This table was computed by **orbit_eye in geo/render.py**, generated with:
//   for e,a,d,t in cases: R.orbit_eye(t, d, e, a)
// The viewport's spherical coordinates are (theta=azim, phi=90°−elev); both sides must give the same camera position.
const GOLD = [
  { elev: 25, azim: 35, dist: 5, target: [0, 0, 0],
    eye: [2.5991839536284225, 2.1130913087034973, 3.7120193825305203] },
  { elev: 0, azim: 0, dist: 7, target: [0, 0, 0],
    eye: [0.0, 0.0, 7.0] },
  { elev: 89.9, azim: 123.4, dist: 3.25, target: [1, -2, 0.5],
    eye: [1.0047355218851304, 1.249995049968185, 0.49687749863570924] },
  { elev: -45, azim: 270, dist: 12, target: [0, 0, 0],
    eye: [-8.485281374238571, -8.48528137423857, -1.5587209012238882e-15] },
  { elev: 60, azim: -90, dist: 0.75, target: [-3, 4, 5],
    eye: [-3.375, 4.649519052838329, 5.0] },
  { elev: 10, azim: 720, dist: 4, target: [0, 1, 0],
    eye: [-1.929666660003036e-15, 1.6945927106677212, 3.939231012048832] },
];

for (const g of GOLD) {
  const v = mkView({ theta: g.azim * D2R, phi: (90 - g.elev) * D2R,
                     dist: g.dist, target: [...g.target] });
  const st = getCam(v);
  const e = maxAbs(sub(st.eye, g.eye));
  check(`elev=${g.elev} azim=${g.azim} d=${g.dist} camera position matches Python`,
        e < 1e-12, `max diff ${e.toExponential(2)}`);
}
// Reverse: the camera's elev/azim must be recovered too
for (const g of GOLD) {
  const v = mkView();
  setCam(v, { eye: g.eye, target: g.target, fov: 45 });
  const st = getCam(v);
  // azim is periodic (720 and 0 are equivalent), so compare camera positions, not the angles themselves;
  // elev is not periodic, compare directly
  const de = Math.abs(st.elev - ((g.elev + 90) % 180 - 90));
  check(`  elev recovered (${g.elev})`, de < 1e-9 || Math.abs(de - 0) < 1e-9,
        `${st.elev.toFixed(6)}`);
  check(`  distance recovered too (${g.dist})`,
        Math.abs(st.distance - g.dist) < 1e-12);
}
// **Negative control**: swapping sin/cos (the most common mistake) immediately disagrees with the golden reference
const swapped = GOLD.map((g) => {
  const e = g.elev * D2R, a = g.azim * D2R;
  return [g.target[0] + g.dist * Math.cos(e) * Math.cos(a),
          g.target[1] + g.dist * Math.sin(e),
          g.target[2] + g.dist * Math.cos(e) * Math.sin(a)];
});
check("  [negative control] with sin/cos swapped it disagrees with the golden reference (so this criterion is not trivially true)",
      swapped.some((eye, i) => maxAbs(sub(eye, GOLD[i].eye)) > 0.1));


// ══════════════════════════════════════════════════ 2. Round-trip identity
sec("Round-trip identity (prerequisite for locking camera to view)");
const rng = (() => { let s = 12345;
  return () => (s = (s * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff; })();
let worst = 0, worstT = 0;
for (let i = 0; i < 400; i++) {
  const target = [rng() * 20 - 10, rng() * 20 - 10, rng() * 20 - 10];
  const dir = [rng() * 2 - 1, rng() * 2 - 1, rng() * 2 - 1];
  const n = norm(dir);
  if (n < 1e-6) continue;
  const d = 0.01 + rng() * 100;
  const eye = [target[0] + dir[0] / n * d, target[1] + dir[1] / n * d,
               target[2] + dir[2] / n * d];
  const v = mkView();
  setCam(v, { eye, target, fov: 45 });
  const st = getCam(v);
  worst = Math.max(worst, maxAbs(sub(st.eye, eye)) / Math.max(1, d));
  worstT = Math.max(worstT, maxAbs(sub(st.target, target)));
}
check("400 random camera positions: eye -> spherical -> eye relative error < 1e-14",
      worst < 1e-14, `max relative error ${worst.toExponential(2)}`);
check("  target kept bit for bit", worstT === 0, worstT);
const v2 = mkView();
setCam(v2, { eye: [3, 4, 0], target: [0, 0, 0], fov: 30 });
check("fov follows the camera", v2.fov === 30);
const st2 = getCam(v2);
check("  reading it back gives the same", st2.fov === 30);
check("distance equals |eye − target|", Math.abs(st2.distance - 5) < 1e-15);
check("setCameraState refreshes the grid scale (otherwise the grid keeps the old scale)",
      v2.gridScaled === 1);
// Repeated round trips don't drift -- in lock mode this happens every 120ms
let cur = { eye: [1.5, -2.25, 3.75], target: [0.5, 0.5, 0.5], fov: 45 };
const v3 = mkView();
for (let i = 0; i < 500; i++) {
  setCam(v3, cur);
  cur = getCam(v3);
}
check("500 round trips: camera position doesn't drift (lock mode does one every 120ms)",
      maxAbs(sub(cur.eye, [1.5, -2.25, 3.75])) < 1e-12,
      `drift ${maxAbs(sub(cur.eye, [1.5, -2.25, 3.75])).toExponential(2)}`);


// ══════════════════════════════════════════════════ 3. Degenerate input
sec("Degenerate input doesn't spit NaN");
const vd = mkView();
const before = JSON.stringify(vd.orbit);
check("eye == target is rejected (returns false), and the existing view is left untouched",
      setCam(vd, { eye: [1, 1, 1], target: [1, 1, 1] }) === false
      && JSON.stringify(vd.orbit) === before);
check("null rejected too", setCam(vd, null) === false);
const vt = mkView();
setCam(vt, { eye: [0, 5, 0], target: [0, 0, 0], fov: 45 });
const stt = getCam(vt);
check("looking straight down: phi stays in range, camera position recoverable",
      Number.isFinite(vt.orbit.phi) && maxAbs(sub(stt.eye, [0, 5, 0])) < 1e-12,
      `phi=${vt.orbit.phi}`);
setCam(vt, { eye: [0, -5, 0], target: [0, 0, 0], fov: 45 });
check("  same looking straight up",
      maxAbs(sub(getCam(vt).eye, [0, -5, 0])) < 1e-12);
const vu = mkView();
setCam(vu, { eye: [3, 0, 4], target: [0, 0, 0], fov: 45, up: [1, 0, 0] });
check("up is ignored (the viewport can't express roll), but no error, no NaN",
      getCam(vu).up.join() === "0,1,0"
      && getCam(vu).eye.every(Number.isFinite));
const vf = mkView();
setCam(vf, { eye: [0, 0, 3], target: [0, 0, 0], fov: 0 });
check("fov 0 / negative / NaN keeps the old fov (doesn't break the viewport projection)",
      vf.fov === 45);
setCam(vf, { eye: [0, 0, 3], target: [0, 0, 0], fov: NaN });
check("  same for NaN", vf.fov === 45);
const vm = mkView();
setCam(vm, { eye: [1, 2, 3] });               // no target given
check("missing target uses the origin, doesn't throw", Number.isFinite(vm.orbit.dist));


// ══════════════════════════════════════════════════ 4. Resolution gate
sec("Resolution gate");
const vg = mkView(null, 45, { xres: 1920, yres: 1080 });
let r = gateRect(vg, 400, 300);
check("gate keeps the camera's aspect ratio", Math.abs(r.w / r.h - 1920 / 1080) < 1e-12,
      `${(r.w / r.h).toFixed(6)}`);
check("  centered", Math.abs(r.x * 2 + r.w - 400) < 1e-9
      && Math.abs(r.y * 2 + r.h - 300) < 1e-9);
check("  entirely inside the viewport, with 'outside the frame' margin on all four sides",
      r.x > 0 && r.y > 0 && r.x + r.w < 400 && r.y + r.h < 300,
      `x=${r.x.toFixed(1)} y=${r.y.toFixed(1)}`);
const vtall = mkView(null, 45, { xres: 512, yres: 2048 });
r = gateRect(vtall, 400, 300);
check("portrait framing (taller than the viewport) fits entirely too",
      r.y > 0 && r.y + r.h <= 300 && Math.abs(r.w / r.h - 0.25) < 1e-12,
      `${r.w.toFixed(1)}×${r.h.toFixed(1)}`);
const vsq = mkView(null, 45, { xres: 512, yres: 512 });
r = gateRect(vsq, 300, 300);
check("square framing in a square viewport is a square", Math.abs(r.w - r.h) < 1e-12);

// **This one is the core of this section.** The world half-height inside the gate at the target distance must equal the camera's
// world half-height at the same distance -- otherwise the framing lies.
function halfHeightAtTarget(v, w, h) {
  const fov = effFov(v, w, h);
  const full = Math.tan(fov * D2R / 2) * v.orbit.dist;   // half-height of the whole viewport
  const g = gateRect(v, w, h);
  return full * (g.h / h);                               // the gate part
}
for (const [W, H] of [[400, 300], [800, 200], [123, 456], [1000, 1000]]) {
  for (const gate of [{ xres: 1920, yres: 1080 }, { xres: 512, yres: 512 },
                      { xres: 512, yres: 2048 }]) {
    const v = mkView({ theta: 0.3, phi: 1.2, dist: 7, target: [0, 0, 0] },
                     37.5, gate);
    const want = Math.tan(37.5 * D2R / 2) * 7;
    const got = halfHeightAtTarget(v, W, H);
    check(`${W}×${H} / ${gate.xres}×${gate.yres}: field of view inside the gate equals the camera's`,
          Math.abs(got - want) < 1e-9 * want,
          `${got.toFixed(9)} vs ${want.toFixed(9)}`);
  }
}
check("  [negative control] using the camera fov directly makes the gate view too narrow (so it must be back-computed)",
      (() => { const v = mkView({ theta: 0, phi: 1, dist: 7,
                                  target: [0, 0, 0] }, 37.5,
                                { xres: 1920, yres: 1080 });
               const g = gateRect(v, 400, 300);
               const naive = Math.tan(37.5 * D2R / 2) * 7 * (g.h / 300);
               const want = Math.tan(37.5 * D2R / 2) * 7;
               return naive < want * 0.75; })());
check("without a gate effectiveFov is just the camera fov (no correction)",
      effFov(mkView(null, 33, null), 400, 300) === 33);
check("setGate(null) turns the gate off",
      (() => { const v = mkView(null, 45, { xres: 4, yres: 3 });
               v.setGate(null); return v.gate === null; })());
check("  a gate with resolution 0 / negative is treated as none (no division to Infinity)",
      (() => { const v = mkView();
               v.setGate({ xres: 0, yres: 512 });
               const a = v.gate === null;
               v.setGate({ xres: -8, yres: 8 });
               return a && v.gate === null; })());
check("with extreme gate aspect ratios fov is clamped within 175° (otherwise the projection matrix blows up)",
      effFov(mkView(null, 120, { xres: 10000, yres: 1 }), 400, 300) <= 175);
check("no gate computed when the viewport height is 0 (the container has no size yet on the init frame)",
      effFov(mkView(null, 45, { xres: 16, yres: 9 }), 0, 0) === 45);


// ══════════════════════════════════════════════════ 5. Panel reuses the same code
sec("Panel and node reuse the same class");
check("DEFAULTS is exported (the panel must not write its own copy of the defaults)",
      M.DEFAULTS && typeof M.DEFAULTS === "object");
check("all four methods are on Viewport (the panel interoperates through them)",
      ["getCameraState", "setCameraState", "setGate", "gateRect"]
        .every((k) => typeof V[k] === "function"));
check("effectiveFov / drawGate are there too (needed by the render loop and overlay)",
      typeof V.effectiveFov === "function"
      && typeof V.drawGate === "function");


// ═════════════════════════════════════════ Middle-button pan must not be stolen by the ComfyUI canvas
sec("Middle-button pan (viewport vs canvas)");
//
// User-reported bug: dragging with the middle mouse button on the viewport panned the canvas, not the viewport. The ComfyUI frontend listens for
// the middle button in the **capture phase** on ancestors / the document and forwards it to the canvas; we used to attach to the canvas element and
// stopPropagation in the bubble phase, which was too late. Here we build the same kind of "frontend": a DOM widget wrapper + the document, each with a
// capture-phase middle-button listener, and check whether they still receive it
{
  const W = dom.window;
  const wrap = W.document.createElement("div");           // DOM widget wrapper
  const cont = W.document.createElement("div");
  const cv = W.document.createElement("canvas");
  cont.appendChild(cv); wrap.appendChild(cont); W.document.body.appendChild(wrap);
  const other = W.document.createElement("div");           // somewhere else on the canvas
  W.document.body.appendChild(other);
  const hits = { wrap: 0, doc: 0 };
  const onWrap = (e) => { if (e.button === 1) hits.wrap++; };
  const onDoc = (e) => { if (e.button === 1) hits.doc++; };
  wrap.addEventListener("pointerdown", onWrap, true);
  W.document.addEventListener("pointerdown", onDoc, true);
  W.document.addEventListener("pointermove", (e) => { if (e.buttons & 4) hits.doc++; }, true);
  const tracked = [];
  const view = Object.assign(Object.create(M.Viewport.prototype), {
    renderer: { domElement: cv }, container: cont, T: null,
    tumbled: 0, tumble() { this.tumbled++; }, dolly() {}, frameAll() {}, setView() {},
    track(dx, dy) { tracked.push([dx, dy]); },
  });
  V.bindInput.call(view);
  const PE = W.PointerEvent || W.MouseEvent;
  const fire = (el, type, x, y, button, buttons) => el.dispatchEvent(new PE(type, {
    bubbles: true, cancelable: true, clientX: x, clientY: y, button, buttons, pointerId: 1 }));
  fire(cv, "pointerdown", 100, 100, 1, 4);
  fire(cv, "pointermove", 110, 95, -1, 4);
  fire(cv, "pointermove", 130, 90, -1, 4);
  fire(cv, "pointerup", 130, 90, 1, 0);
  check("middle-button drag on the viewport: capture listeners on the DOM widget wrapper and document (= canvas pan) never received it",
        hits.wrap === 0 && hits.doc === 0, JSON.stringify(hits));
  check("  the viewport panned itself, by exactly the mouse displacement", tracked.length === 2
        && tracked[0].join() === "10,-5" && tracked[1].join() === "20,-5",
        JSON.stringify(tracked));
  const ev = new PE("mousedown", { bubbles: true, cancelable: true, button: 1 });
  cv.dispatchEvent(ev);
  check("  the middle-button mousedown was also cancelled (browser doesn't pop up autoscroll)", ev.defaultPrevented);
  fire(cv, "pointermove", 200, 200, -1, 0);
  check("  moving after release no longer pans", tracked.length === 2);
  fire(other, "pointerdown", 5, 5, 1, 4);
  fire(other, "pointerup", 5, 5, 1, 0);
  check("  middle button elsewhere on the canvas still goes to the canvas", hits.doc === 1, JSON.stringify(hits));
  fire(cv, "pointerdown", 100, 100, 0, 1);
  fire(cv, "pointermove", 104, 100, -1, 1);
  fire(cv, "pointerup", 104, 100, 0, 0);
  check("  left button is still tumble (unaffected by the middle-button path), and doesn't pan", view.tumbled === 1
        && tracked.length === 2);
  V.dispose.call(Object.assign(view, { renderer: { domElement: cv, dispose() {} } }));
  fire(cv, "pointerdown", 100, 100, 1, 4);
  check("  after dispose the capture listeners on window are all removed (deleting the node leaves nothing behind)",
        hits.wrap === 1, JSON.stringify(hits));
}

const pass = OK.filter(Boolean).length;
console.log(`\n${pass}/${OK.length} passed`);
process.exit(pass === OK.length ? 0 : 1);
