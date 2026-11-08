// pcg120: the viewport renders on demand. Runs the real Viewport.loop() with the real three.js (web/vendor) and a
// counting fake renderer, no WebGL; animation frames and the clock are driven by hand.
//   - idle: no draw after the first one, until the 1 s keepalive
//   - each change draws exactly once: rebuild (geometry / options), orbit (key shortcuts, handles), UV camera,
//     panel resize, fov, gate, HUD warning, input events over the canvas, a handle parameter edited in the panel
//   - negative control: with the gating removed (the old loop) every frame draws
import { JSDOM } from "jsdom";
import fs from "fs";
import os from "os";
import path from "path";
import { fileURLToPath } from "url";

const _HERE = path.dirname(fileURLToPath(import.meta.url));
function pkgRoot() {
  let d = _HERE;
  for (let i = 0; i < 4; i++) {
    if (fs.existsSync(path.join(d, "comfyui_pcg"))) return path.join(d, "comfyui_pcg");
    if (fs.existsSync(path.join(d, "web", "pcg_viewport.js"))) return d;
    d = path.dirname(d);
  }
  throw new Error("plugin folder not found");
}
const PKG = pkgRoot();
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "jstest_od_"));
process.on("exit", () => fs.rmSync(ROOT, { recursive: true, force: true }));
const EXT = path.join(ROOT, "extensions", "comfyui_pcg");
fs.mkdirSync(path.join(ROOT, "scripts"), { recursive: true });
fs.mkdirSync(EXT, { recursive: true });
fs.writeFileSync(path.join(ROOT, "scripts", "app.js"), "export const app = globalThis.__app;\n");
for (const f of ["pcg_viewport.js", "pcg_volume.js"])
  fs.copyFileSync(path.join(PKG, "web", f), path.join(EXT, f));
fs.writeFileSync(path.join(ROOT, "package.json"), '{"type":"module"}\n');

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
for (const k of ["window", "document", "HTMLElement", "Node"]) {
  Object.defineProperty(globalThis, k, { value: k === "window" ? dom.window : dom.window[k],
                                         writable: true, configurable: true });
}

let rafCb = null;
globalThis.requestAnimationFrame = (cb) => { rafCb = cb; return 1; };
globalThis.cancelAnimationFrame = () => {};
let NOW = 1000;
globalThis.performance = { now: () => NOW };
globalThis.__app = { registerExtension() {}, graph: { _nodes: [] } };

const OK = [];
function check(name, cond, extra = "") {
  OK.push(!!cond);
  console.log((cond ? "  PASS  " : "  FAIL  ") + name + (extra === "" ? "" : "   " + extra));
}

const T = await import(path.join(PKG, "web", "vendor", "three.module.js"));
const M = await import(path.join(EXT, "pcg_viewport.js"));

function makeView() {
  const v = Object.create(M.Viewport.prototype);
  let draws = 0;
  const canvas = dom.window.document.createElement("canvas");
  Object.assign(v, {
    T, opts: { ...M.DEFAULTS }, root: new T.Group(),
    container: { clientWidth: 400, clientHeight: 300 },
    renderer: { setSize() {}, render() { draws++; }, domElement: canvas },
    overlay: { width: 0, height: 0 },
    camera: new T.PerspectiveCamera(45, 1, 0.1, 100), scene: new T.Scene(),
    head: new T.DirectionalLight(), _lv: { r: new T.Vector3(), u: new T.Vector3() },
    orbit: { theta: 0.5, phi: 1.0, dist: 5, target: [0, 0, 0] }, fov: 45,
  });
  v.scene.fog = new T.Fog(0, 1, 10);
  for (const k of ["updateLabelScale", "updateLineGrid", "safeOverlay", "buildLabels", "applyGrid", "updateGridScale"])
    v[k] = () => {};
  v.renderUV = () => { draws++; };
  v.count = () => draws;
  return v;
}
const tick = (n = 1, dt = 16) => { for (let i = 0; i < n; i++) { NOW += dt; rafCb(); } };

const v = makeView();
v.loop();
check("the first frame draws", v.count() === 1, v.count());
tick(30);
check("idle: 30 more frames (~0.5 s) draw nothing", v.count() === 1, v.count());
tick(40);
check("  ...until the 1 s keepalive (one draw)", v.count() === 2, v.count());

let c = v.count();
v.orbit.theta += 0.3; tick(3);
check("orbit change (key shortcut / handle tumble writes the orbit directly): one draw", v.count() === c + 1);
c = v.count(); v.orbit.target = [1, 0, 0]; tick(3);
check("orbit target change: one draw", v.count() === c + 1);
c = v.count(); v.invalidate(); tick(3);
check("invalidate(): one draw", v.count() === c + 1);
c = v.count(); v.container.clientWidth = 500; tick(3);
check("panel resize: one draw", v.count() === c + 1);
c = v.count(); v.fov = 30; tick(3);
check("fov change (camera node): one draw", v.count() === c + 1);
c = v.count(); v.setGate({ xres: 1920, yres: 1080 }); tick(3);
check("gate on: one draw", v.count() === c + 1);
c = v.count(); v.labelWarning = "too many"; tick(3);
check("HUD warning appears: one draw", v.count() === c + 1);
c = v.count(); v._dirty = false; v.rebuild = M.Viewport.prototype.rebuild;
v.data = null;
try { v.rebuild(); } catch (e) { /* no data: only the dirty flag matters here */ }
tick(3);
check("rebuild (setGeometry / setOptions go through it): one draw", v.count() === c + 1, v.count() - c);

// input over the canvas
v.bindInput = M.Viewport.prototype.bindInput;
const el = v.renderer.domElement;
try { v.bindInput(); } catch (e) { /* the rest of bindInput needs a real container; the invalidate listeners come first */ }
tick(3);
c = v.count();
el.dispatchEvent(new dom.window.Event("pointermove")); tick(3);
check("pointer move over the canvas (handle hover): one draw", v.count() === c + 1, v.count() - c);

// handles follow a parameter edited in the panel, without any event reaching the viewport
const node = { id: 7, t: [0, 0, 0] };
v.tool = { node, mode: "t", hot: null, cHot: null, drag: null, spec: {}, update() {},
           frame() { return { c: node.t.slice(), r: [0, 0, 0], order: "xyz" }; } };
tick(3); c = v.count(); tick(10);
check("handles shown, nothing changes: no draw", v.count() === c);
node.t = [0.5, 0, 0]; tick(3);
check("handle parameter changed in the panel: one draw", v.count() === c + 1);

// UV view
c = v.count(); v.uvMode = true; v.uvCam = { cx: 0.5, cy: 0.5, h: 0.6 }; tick(3);
check("switch to the UV view: one draw", v.count() === c + 1);
c = v.count(); v.uvCam.h = 0.3; tick(3);
check("UV zoom: one draw", v.count() === c + 1);
c = v.count(); tick(20);
check("UV view idle: no draw", v.count() === c);

// negative control: the gate in loop() is what saves the frames
const src = fs.readFileSync(path.join(EXT, "pcg_viewport.js"), "utf8");
const gate = "if (!sized && !this._dirty && sig === this._sig && now - (this._drawnAt || 0) < KEEPALIVE_MS) return;";
check("negative control setup: the gating line is in loop()", src.includes(gate));
fs.writeFileSync(path.join(EXT, "pcg_viewport_old.js"), src.replace(gate, ""));
const MO = await import(path.join(EXT, "pcg_viewport_old.js"));
const o = makeView(); Object.setPrototypeOf(o, MO.Viewport.prototype);
o.loop(); tick(30);
check("negative control: without the gate, 30 idle frames draw 30 times", o.count() === 31, o.count());

console.log(`\n${OK.filter(Boolean).length}/${OK.length} passed`);
process.exit(OK.every(Boolean) ? 0 : 1);
