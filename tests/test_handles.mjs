// Tests for viewport handles + the curve drawing tool (pcg103). A real three.js camera (the math runs in node),
// stubbed app / nodes / pcg_display, with pcg_handles.js really running.
//
// The kinds of things that **fail silently**:
//   1) reversed directions. An axis dragging backwards, a ring rotating backwards -- it looks like it "moves", it just doesn't follow the mouse. So every check
//      is "move the mouse onto the projection of some world point -> the parameter must be exactly this", to 1e-6.
//   2) Euler convention differs from Python. The rx/ry/rz written by the handle are interpreted on the Python side by ops.euler_matrix;
//      one transpose / order difference and everything is wrong. Compared directly against matrices computed by Python.
//   3) changing what must not change: expression / reference-bound components overwritten by the handle, keyframes written as constants.
//   4) the curve tool adding two points per click, sneaking in points while tumbling, Points text format differing between the two sides.
import { JSDOM } from "jsdom";
import fs from "fs";
import os from "os";
import path from "path";
import { spawnSync } from "child_process";
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
const WEB = path.join(PKG, "comfyui_pcg", "web");
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "jstest_handles_"));
process.on("exit", () => fs.rmSync(ROOT, { recursive: true, force: true }));
const EXT = path.join(ROOT, "extensions", "comfyui_pcg");
fs.mkdirSync(path.join(ROOT, "scripts"), { recursive: true });
fs.mkdirSync(path.join(EXT, "vendor"), { recursive: true });
fs.writeFileSync(path.join(ROOT, "scripts", "app.js"), "export const app = globalThis.__app;\n");
fs.writeFileSync(path.join(ROOT, "scripts", "api.js"), "export const api = globalThis.__api;\n");
fs.writeFileSync(path.join(ROOT, "package.json"), '{"type":"module"}');
for (const f of ["pcg_handles.js", "pcg_params.js", "pcg_hexpr.js", "pcg_chan.js", "pcg_viewport.js",
                 "pcg_volume.js"])
  fs.copyFileSync(path.join(WEB, f), path.join(EXT, f));
fs.copyFileSync(path.join(WEB, "vendor", "three.module.js"), path.join(EXT, "vendor", "three.module.js"));
// stubbed queue: only count calls
fs.writeFileSync(path.join(EXT, "pcg_display.js"),
  "export function requestRun() { globalThis.__runs = (globalThis.__runs || 0) + 1; return true; }\n");

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
for (const k of ["window", "document", "HTMLElement", "Node", "MouseEvent", "KeyboardEvent"]) {
  Object.defineProperty(globalThis, k, {
    value: k === "window" ? dom.window : dom.window[k], writable: true, configurable: true,
  });
}
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};
const graph = { _nodes: [], setDirtyCanvas() {}, getNodeById(id) { return this._nodes.find((n) => n.id === id); } };
globalThis.__app = { registerExtension() {}, graph, canvas: { selected_nodes: {} } };

const OK = [];
function check(name, cond, extra = "") {
  OK.push(!!cond);
  const tail = extra === "" ? "" : "   " + extra;
  console.log((cond ? "  PASS  " : "  FAIL  ") + name + tail);
}
function sec(t) { console.log("\n" + "═".repeat(28) + " " + t); }
const close = (a, b, e = 1e-6) => Array.isArray(a)
  ? a.length === b.length && a.every((x, i) => close(x, b[i], e)) : Math.abs(a - b) <= e;

const T = await import(path.join(EXT, "vendor", "three.module.js"));
const H = await import(path.join(EXT, "pcg_handles.js"));
const VP = await import(path.join(EXT, "pcg_viewport.js"));
const P = await import(path.join(EXT, "pcg_params.js"));

// ── stub node: widget list + properties
let NID = 1;
function mkNode(type, vals) {
  const n = { id: NID++, type, title: type, properties: {}, inputs: [],
              widgets: Object.entries(vals).map(([name, value]) => ({
                name, value, callback() { n._cb = (n._cb || 0) + 1; } })),
              setDirtyCanvas() {} };
  graph._nodes.push(n);
  return n;
}
const W = (n, k) => n.widgets.find((w) => w.name === k).value;
function select(n) { globalThis.__app.canvas.selected_nodes = n ? { [n.id]: n } : {}; }

// ── viewport: the adapter methods on the real Viewport.prototype + a real three camera
function mkView(eye, target = [0, 0, 0], w = 800, h = 600) {
  const v = Object.create(VP.Viewport.prototype);
  v.T = T;
  v.camera = new T.PerspectiveCamera(45, w / h, 0.01, 1000);
  v.camera.position.set(...eye);
  v.camera.lookAt(...target);
  v.camera.updateProjectionMatrix();
  v.camera.updateMatrixWorld();
  v.renderer = { domElement: { clientWidth: w, clientHeight: h } };
  v.container = { clientWidth: w, clientHeight: h };
  v.unit = 1;
  v.mesh = null;
  v.tumbled = [];
  v.tumble = (dx, dy) => v.tumbled.push([dx, dy]);
  return v;
}
const ev = (o = {}) => ({ button: 0, ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, ...o });

// ═════════════════════════════════════════════ 1. Euler convention
sec("Euler convention matches euler_matrix in geo/ops.py");
// computed by geo/ops.py euler_matrix(*r, order=o) (see the line that generated this table in git history)
const GOLD = [
  { r: [20, 0, 10], o: "xyz", M: [[0.9848077297210693, -0.16317591071128845, 0.05939117819070816], [0.1736481785774231, 0.9254165291786194, -0.33682408928871155], [0.0, 0.3420201539993286, 0.9396926164627075]] },
  { r: [35, -50, 70], o: "xyz", M: [[0.21984632313251495, -0.9200296998023987, 0.3243655562400818], [0.6040228009223938, -0.13272038102149963, -0.78583824634552], [0.7660444378852844, 0.36868783831596375, 0.5265408158302307]] },
  { r: [35, -50, 70], o: "zyx", M: [[0.21984632313251495, -0.6040228009223938, -0.7660444378852844], [0.6194725632667542, 0.6930534243583679, -0.36868783831596375], [0.7536055445671082, -0.39348888397216797, 0.5265408158302307]] },
  { r: [10, 80, -30], o: "yzx", M: [[0.15038372576236725, 0.5, 0.8528684973716736], [0.08550503849983215, 0.8528684973716736, -0.5150768160820007], [-0.9849231243133545, 0.15038372576236725, 0.08550503849983215]] },
  { r: [-15, 25, 40], o: "xzy", M: [[0.6942720413208008, -0.6720947623252869, 0.25743937492370605], [0.6427876353263855, 0.7399420738220215, 0.1982668936252594], [-0.32374438643455505, 0.027827715501189232, 0.9457352757453918]] },
];
for (const g of GOLD)
  check(`  eulerMatrix(${g.r}, ${g.o}) = Python`, close(H.eulerMatrix(g.r, g.o).flat(), g.M.flat(), 1e-6));
// negative control: three's Euler "XYZ" is a different convention (Z first), not Houdini's xyz
{
  const m = new T.Matrix4().makeRotationFromEuler(new T.Euler(35 * Math.PI / 180, -50 * Math.PI / 180, 70 * Math.PI / 180, "XYZ"));
  const e = m.elements;
  const M3 = [[e[0], e[4], e[8]], [e[1], e[5], e[9]], [e[2], e[6], e[10]]];
  check("  negative control: three.js Euler('XYZ') differs from Houdini's xyz (the criterion can tell them apart)",
        !close(M3.flat(), GOLD[1].M.flat(), 1e-3));
}
// ring axes: changing r[k] slightly = rotating that much about gimbalAxes[k]
{
  let worst = 0;
  for (const g of GOLD) {
    const G = H.gimbalAxes(g.r, g.o);
    for (let k = 0; k < 3; k++) {
      const r2 = g.r.slice(); r2[k] += 1e-3;
      const M0 = H.eulerMatrix(g.r, g.o), M1 = H.eulerMatrix(r2, g.o);
      const p = [0.3, -0.7, 0.5];
      const q0 = H.mv(M0, p), q1 = H.mv(M1, p);
      const pred = H.add(q0, H.mul(H.cross(G[k], q0), 1e-3 * Math.PI / 180));
      worst = Math.max(worst, H.len(H.sub(q1, pred)));
    }
  }
  check("  gimbalAxes: changing r[k] = rotating about the k-th ring axis (five sets drawn from the six orders, exact to first order)", worst < 1e-8, worst);
}

// ═════════════════════════════════════════════ 2. translate
sec("translate handle: move the mouse onto the projection of a world point and the parameter is exactly that");
const view = mkView([5, 4, 6]);
const tool = new H.HandleTool(view);
const xf = mkNode("PCG_Transform", { tx: 0.5, ty: 0.2, tz: -0.3, rx: 0, ry: 0, rz: 0, sx: 1, sy: 1, sz: 1,
  rotate_order: "xyz", uniform_scale: 1, px: 0.1, py: 0, pz: 0 });
select(xf);
tool.update();
check("Transform selected: has a handle, three modes t / r / s", tool.active() && tool.spec.modes.join() === "t,r,s");
let F = tool.frame();
check("  handle drawn at pivot + t", close(F.c, [0.6, 0.2, -0.3]));
{
  const s0 = view.screen(F.c), s1 = view.screen(H.add(F.c, [0, 0, F.L]));
  const vd = view.viewDir();
  const side = H.norm(H.cross(vd, [0, 1, 0]));          // direction perpendicular to the view: no foreshortening on screen
  const s2 = view.screen(H.add(F.c, H.mul(side, F.L)));
  check("  axis length set in screen pixels (≈ 92px when perpendicular to the view, independent of distance)",
        Math.abs(Math.hypot(s2[0] - s0[0], s2[1] - s0[1]) - 92) < 2 && s1,
        Math.hypot(s2[0] - s0[0], s2[1] - s0[1]).toFixed(2));
}
const at = (p) => view.screen(p);
function drag(p0, p1, o = {}) {
  const a = at(p0), b = at(p1);
  const took = tool.pointerDown(ev(o), a[0], a[1]);
  tool.pointerMove(ev(o), (a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
  tool.pointerMove(ev(o), b[0], b[1]);
  tool.pointerUp(ev(o));
  return took;
}
let c = F.c, L = F.L;
let took = drag(H.add(c, [0.6 * L, 0, 0]), H.add(c, [0.6 * L + 1.5, 0, 0]));
check("X axis: drag +1.5 -> tx = 2.0, ty / tz unchanged", took && close(W(xf, "tx"), 2.0, 1e-5)
      && W(xf, "ty") === 0.2 && W(xf, "tz") === -0.3, `${W(xf, "tx")}`);
F = tool.frame(); c = F.c; L = F.L;
drag(H.add(c, [0, 0.6 * L, 0]), H.add(c, [0, 0.6 * L - 0.75, 0]));
check("Y axis: drag −0.75 -> ty = −0.55", close(W(xf, "ty"), -0.55, 1e-5), `${W(xf, "ty")}`);
F = tool.frame(); c = F.c; L = F.L;
const q = H.add(c, [0.32 * L, 0, 0.32 * L]);
drag(q, H.add(q, [0.7, 0, -0.4]));
check("XZ plane square: drag (0.7, 0, −0.4) -> tx += 0.7, tz −= 0.4, ty unchanged",
      close(W(xf, "tx"), 2.7, 1e-5) && close(W(xf, "tz"), -0.7, 1e-5) && close(W(xf, "ty"), -0.55, 1e-5));
F = tool.frame(); c = F.c;
{
  const vd = view.viewDir();
  const u = H.norm(H.cross(vd, [0, 1, 0])), v = H.cross(u, vd);
  const mv_ = H.add(H.mul(u, 0.4), H.mul(v, -0.25));
  const t0 = [W(xf, "tx"), W(xf, "ty"), W(xf, "tz")];
  drag(c, H.add(c, mv_));
  check("center circle: dragging in the screen plane -> t gains the same world offset",
        close([W(xf, "tx"), W(xf, "ty"), W(xf, "tz")], H.add(t0, mv_), 1e-5));
}
// negative control: clicking empty space is not the handle's business
check("click on empty space: pointerDown returns false (left to the viewport to tumble)", !tool.pointerDown(ev(), 5, 5));
check("Alt / right button: not the handle's business", !tool.pointerDown(ev({ button: 2 }), ...at(c)));
// snapping
F = tool.frame(); c = F.c; L = F.L;
drag(H.add(c, [0.6 * L, 0, 0]), H.add(c, [0.6 * L + 0.333, 0, 0]), { ctrlKey: true });
check("Ctrl: translation snaps to 1/10 of the grid unit", close(W(xf, "tx") * 10, Math.round(W(xf, "tx") * 10), 1e-6),
      `${W(xf, "tx")}`);

// ═════════════════════════════════════════════ 3. rotate
sec("rotate rings: drag 30° along a ring -> that channel +30°, and it really rotates about that ring's axis");
const rv = mkNode("PCG_Transform", { tx: 0, ty: 0, tz: 0, rx: 20, ry: 0, rz: 10, sx: 1, sy: 1, sz: 1,
  rotate_order: "xyz", uniform_scale: 1, px: 0, py: 0, pz: 0 });
select(rv);
tool.update();
tool.mode = "r";
for (const [k, deg] of [[1, 30], [0, -25], [2, 40]]) {
  F = tool.frame();
  const ring = tool.parts(F).find((p) => p.kind === "ring" && p.k === k);
  const g = ring.axis;
  const u = H.norm(Math.abs(g[0]) < 0.9 ? H.cross(g, [1, 0, 0]) : H.cross(g, [0, 1, 0]));
  const v = H.cross(g, u);
  const Rr = (74 / 92) * F.L;
  // start dragging at a spot on the ring that the camera can see, away from the axis's line of sight
  const a0 = [0.3, 1.3, 2.4, 3.6, 4.8].find((a) => {
    const p = H.add(F.c, H.add(H.mul(u, Math.cos(a) * Rr), H.mul(v, Math.sin(a) * Rr)));
    const pk = tool.pick(...at(p));
    return pk && pk.kind === "ring" && pk.k === k;
  });
  const ringPt = (a) => H.add(F.c, H.add(H.mul(u, Math.cos(a) * Rr), H.mul(v, Math.sin(a) * Rr)));
  const r0 = [W(rv, "rx"), W(rv, "ry"), W(rv, "rz")];
  const M0 = H.eulerMatrix(r0, "xyz");
  const a = at(ringPt(a0));
  tool.pointerDown(ev(), a[0], a[1]);
  for (let i = 1; i <= 6; i++) {
    const b = at(ringPt(a0 + (deg * Math.PI / 180) * i / 6));
    tool.pointerMove(ev(), b[0], b[1]);
  }
  tool.pointerUp(ev());
  const r1 = [W(rv, "rx"), W(rv, "ry"), W(rv, "rz")];
  const want = r0.slice(); want[k] += deg;
  // resulting effect = rotation by deg about the ring axis (a quaternion-style check, independent of the Euler components)
  const M1 = H.eulerMatrix(r1, "xyz");
  const p = [0.4, 0.9, -0.2];
  const rot = new T.Quaternion().setFromAxisAngle(new T.Vector3(...g), deg * Math.PI / 180);
  const pv = new T.Vector3(...H.mv(M0, p)).applyQuaternion(rot);
  check(`  ${"xyz"[k]} ring: r${"xyz"[k]} ${deg > 0 ? "+" : ""}${deg}°, others unchanged; result = rotation by ${deg}° about the ring axis`,
        a0 !== undefined && close(r1, want, 1e-3) && close(H.mv(M1, p), [pv.x, pv.y, pv.z], 1e-4),
        `${r1.map((x) => x.toFixed(3))}`);
}
// rings edge-on to the camera: take the screen-angle branch
{
  const v2 = mkView([0, 0, 8]);                    // looking straight down -Z: the X and Y rings are both edge-on
  const t2 = new H.HandleTool(v2);
  const n2 = mkNode("PCG_Transform", { tx: 0, ty: 0, tz: 0, rx: 0, ry: 0, rz: 0, sx: 1, sy: 1, sz: 1,
    rotate_order: "xyz", uniform_scale: 1, px: 0, py: 0, pz: 0 });
  select(n2); t2.update(); t2.mode = "r";
  const F2 = t2.frame();
  const Rr = (74 / 92) * F2.L;
  // Z ring facing the camera: drag along the ring from 45° to 135° = +90° about +Z (start avoids the two lines the edge-on X / Y rings project to)
  const s0 = v2.screen([Rr * Math.SQRT1_2, Rr * Math.SQRT1_2, 0]), s1 = true;
  const pk = t2.pick(...s0);
  t2.pointerDown(ev(), ...s0);
  for (let i = 1; i <= 9; i++) {
    const a = Math.PI / 4 + (Math.PI / 2) * i / 9;
    t2.pointerMove(ev(), ...v2.screen([Rr * Math.cos(a), Rr * Math.sin(a), 0]));
  }
  t2.pointerUp(ev());
  check("  Z ring facing the camera: drag 90° counter-clockwise along the ring = rz +90°", pk?.k === 2 && close(W(n2, "rz"), 90, 1e-3) && s1,
        `${W(n2, "rz")}`);
}
{
  // ring edge-on to the camera (X ring seen from +Z is a vertical line): convert to an angle using the tangent at the picked point
  const v3 = mkView([0, 0, 8]);
  const t3 = new H.HandleTool(v3);
  const n3 = mkNode("PCG_Transform", { tx: 0, ty: 0, tz: 0, rx: 0, ry: 0, rz: 0, sx: 1, sy: 1, sz: 1,
    rotate_order: "xyz", uniform_scale: 1, px: 0, py: 0, pz: 0 });
  select(n3); t3.update(); t3.mode = "r";
  const F3 = t3.frame();
  const Rr = (74 / 92) * F3.L;
  const p0 = [0, Rr * 0.5, Rr * Math.sqrt(0.75)];
  const pk = t3.pick(...v3.screen(p0));
  t3.pointerDown(ev(), ...v3.screen(p0));
  for (let i = 1; i <= 5; i++) {
    const a = 12 * i / 5 * Math.PI / 180;
    const pr = H.mv(H.eulerMatrix([12 * i / 5, 0, 0]), p0);
    t3.pointerMove(ev(), ...v3.screen(pr));
  }
  t3.pointerUp(ev());
  check("  edge-on X ring: drag the picked point in the direction of a +12° rotation about +X -> rx ≈ +12 (tangent linearization, error < 15%)",
        pk?.k === 0 && Math.abs(W(n3, "rx") - 12) < 1.8, `${W(n3, "rx")}`);
}
select(rv); tool.update(); tool.mode = "r";
F = tool.frame();
{
  const before = W(rv, "ry");
  const ring = tool.parts(F).find((p) => p.kind === "ring" && p.k === 1);
  const i0 = 8;
  tool.pointerDown(ev(), ...ring.pts[i0]);
  tool.pointerMove(ev({ ctrlKey: true }), ...ring.pts[i0 + 3]);
  tool.pointerUp(ev());
  check("Ctrl: rotation snaps to 15°", close(W(rv, "ry") / 15, Math.round(W(rv, "ry") / 15), 1e-6)
        && W(rv, "ry") !== before, `${W(rv, "ry")}`);
}

// ═════════════════════════════════════════════ 4. scale
sec("scale: along the object's own axes (scale first, then rotate)");
{
  const sn = mkNode("PCG_Transform", { tx: 0, ty: 0, tz: 0, rx: 0, ry: 30, rz: 0, sx: 2, sy: 1, sz: 1,
    rotate_order: "xyz", uniform_scale: 1, px: 0, py: 0, pz: 0 });
  select(sn); tool.update(); tool.mode = "s";
  F = tool.frame();
  const ax = H.mv(F.R, [1, 0, 0]);
  check("  X scale axis = X after the 30° rotation", close(tool.parts(F).find((p) => p.kind === "saxis" && p.k === 0).axis, ax));
  drag(H.add(F.c, H.mul(ax, 0.9 * F.L)), H.add(F.c, H.mul(ax, 1.35 * F.L)));
  check("  drag to 1.5x the distance -> sx × 1.5 = 3", close(W(sn, "sx"), 3, 1e-4), `${W(sn, "sx")}`);
  const a = at(F.c);
  tool.pointerDown(ev(), a[0], a[1]);
  tool.pointerMove(ev(), a[0] + 50, a[1]);
  tool.pointerUp(ev());
  check("  center square: drag right 50px -> uniform_scale × e^0.5, sx / sy / sz unchanged",
        close(W(sn, "uniform_scale"), Math.exp(0.5), 1e-4) && close(W(sn, "sx"), 3, 1e-4));
  const box = mkNode("PCG_Box", { size_x: 1, size_y: 2, size_z: 3, uniform_scale: 1, cx: 0, cy: 0, cz: 0,
    rx: 0, ry: 0, rz: 0 });
  select(box); tool.update();
  check("Box: handle at the center, translate / rotate / scale all present, scale changes size_*",
        tool.spec.modes.join() === "t,r,s" && tool.spec.s.join() === "size_x,size_y,size_z");
}

// ═════════════════════════════════════════════ 5. locks / keyframes / toggles
sec("expressions lock, keyframes set on the current frame, dragging switches toggles on");
{
  const ln = mkNode("PCG_Transform", { tx: 0, ty: 0, tz: 0, rx: 0, ry: 0, rz: 0, sx: 1, sy: 1, sz: 1,
    rotate_order: "xyz", uniform_scale: 1, px: 0, py: 0, pz: 0 });
  ln.properties.pcg_bind = { tx: "=sin($F)" };
  select(ln); tool.update(); tool.mode = "t";
  F = tool.frame();
  const parts = tool.parts(F);
  check("  tx bound to an expression: X axis drawn locked, cannot be picked", parts.find((p) => p.kind === "axis" && p.k === 0).lock
        && !tool.pick(...at(H.add(F.c, [0.6 * F.L, 0, 0]))));
  check("  center circle locked too (it would change tx)", parts.find((p) => p.kind === "center").lock);
  drag(H.add(F.c, [0, 0.6 * F.L, 0]), H.add(F.c, [0, 0.6 * F.L + 1, 0]));
  check("  Y axis drags as usual, tx's value not written", close(W(ln, "ty"), 1, 1e-5) && W(ln, "tx") === 0);
  check("  channelState: expression -> lock, unbound -> free", H.channelState(ln, "tx") === "lock"
        && H.channelState(ln, "ty") === "free");
  ln.inputs.push({ name: "tz", link: 7, widget: { name: "tz" } });
  check("  wired widgets lock too", H.channelState(ln, "tz") === "lock");
}
{
  const kn = mkNode("PCG_Transform", { tx: 0, ty: 0, tz: 0, rx: 0, ry: 0, rz: 0, sx: 1, sy: 1, sz: 1,
    rotate_order: "xyz", uniform_scale: 1, px: 0, py: 0, pz: 0 });
  P.setKey(graph, kn, "tx", 0, 0);                    // one key at frame 0 -> tx is driven by the channel
  check("  (self-check) tx is now a keyframed channel", H.channelState(kn, "tx") === "key");
  select(kn); tool.update(); tool.mode = "t";
  F = tool.frame();
  drag(H.add(F.c, [0.6 * F.L, 0, 0]), H.add(F.c, [0.6 * F.L + 2, 0, 0]));
  const keys = P.keysOf(kn, "tx");
  const f = P.currentFrame(graph);
  check("  dragging a keyframed channel: sets a key on the current frame (value = 2), still a keyframed channel",
        H.channelState(kn, "tx") === "key" && keys.some((k) => k.f === f && close(k.v, 2, 1e-5)),
        JSON.stringify(keys));
}
{
  const cl = mkNode("PCG_Clip", { orient: "direction", use_origin: false, origin_x: 0, origin_y: 0, origin_z: 0,
    translate_x: 0, translate_y: 0, translate_z: 0, rotate_x: 0, rotate_y: 0, rotate_z: 0 });
  select(cl); tool.update();
  check("  Clip (Direction): translate only, changes origin_*", tool.spec.modes.join() === "t" && tool.spec.t[0] === "origin_x");
  F = tool.frame();
  drag(H.add(F.c, [0, 0.6 * F.L, 0]), H.add(F.c, [0, 0.6 * F.L + 0.5, 0]));
  check("  a drag switches Use Origin on (otherwise origin has no effect)", W(cl, "use_origin") === true
        && close(W(cl, "origin_y"), 0.5, 1e-5));
  cl.widgets.find((w) => w.name === "orient").value = "transform";
  tool.update();
  check("  Clip (Transform): switches to translate_* / rotate_*", tool.spec.t[0] === "translate_x"
        && tool.spec.r[0] === "rotate_x");
  const gr = mkNode("PCG_Grid", { size_x: 4, size_z: 2, plane: "xy", center_x: 0, center_y: 0, center_z: 0,
    rx: 0, ry: 0, rz: 0 });
  check("  Grid: plane xy, the scale Y axis changes size_z", H.specFor(gr).s.join() === "size_x,size_z,");
  gr.widgets.find((w) => w.name === "plane").value = "yz";
  check("  Grid: plane yz, Y changes size_z, Z changes size_x", H.specFor(gr).s.join() === ",size_z,size_x");
  gr.widgets.find((w) => w.name === "plane").value = "zx";
  check("  Grid: plane zx, X changes size_x, Z changes size_z", H.specFor(gr).s.join() === "size_x,,size_z");
  check("  nodes without handles / nothing selected: no handle", H.specFor(mkNode("PCG_Merge", {})) === null
        && (select(null), tool.update(), !tool.active()));
}

// ═════════════════════════════════════════════ 6. queueing
sec("throttled queueing while dragging, queued once more on release");
{
  await new Promise((r) => setTimeout(r, 200));        // let the queue calls from earlier drags land first
  globalThis.__runs = 0;
  const n = mkNode("PCG_Transform", { tx: 0, ty: 0, tz: 0, rx: 0, ry: 0, rz: 0, sx: 1, sy: 1, sz: 1,
    rotate_order: "xyz", uniform_scale: 1, px: 0, py: 0, pz: 0 });
  select(n); tool.update(); tool.mode = "t";
  F = tool.frame();
  const a = at(H.add(F.c, [0.6 * F.L, 0, 0]));
  tool.pointerDown(ev(), ...a);
  for (let i = 1; i <= 30; i++) {          // 30 moves spread over ~300ms
    tool.pointerMove(ev(), ...at(H.add(F.c, [0.6 * F.L + i * 0.05, 0, 0])));
    await new Promise((r) => setTimeout(r, 10));
  }
  await new Promise((r) => setTimeout(r, 150));
  const during = globalThis.__runs;
  tool.pointerUp(ev());
  await new Promise((r) => setTimeout(r, 30));
  check("  30 moves in ~300ms: 120ms throttle queued only 2-5 times; one more queue after release",
        during >= 2 && during <= 5 && globalThis.__runs >= during + 1, `${during} → ${globalThis.__runs}`);
  check("  the widget callback was called (panel sync relies on it)", n._cb > 0);
}

// ═════════════════════════════════════════════ 7. curve drawing
sec("Curve: click, drag, insert, delete, close");
{
  const top = mkView([0.01, 12, 0.01]);         // top view
  const ct = new H.HandleTool(top);
  const cv = mkNode("PCG_Curve", { points: "", prim_type: "polygon", closed: false, order: 4, reverse: false });
  select(cv); ct.update();
  check("Curve selected: enters curve drawing mode", ct.mode === "curve");
  const click = (p, o = {}) => {
    const s = top.screen(p);
    ct.pointerDown(ev(o), ...s);
    ct.pointerUp(ev(o));
  };
  click([1, 0, 2]); click([-1.5, 0, 0.5]); click([0.5, 0, -2]);
  const pts = H.parsePoints(W(cv, "points"));
  check("  three clicks = three points, on the ground plane, exactly where clicked",
        pts.length === 3 && close(pts[0], [1, 0, 2], 1e-4) && close(pts[2], [0.5, 0, -2], 1e-4),
        W(cv, "points").replace(/\n/g, " | "));
  // drag the second point
  const s1 = top.screen(pts[1]), s1b = top.screen([-2, 0, 1]);
  ct.pointerMove(ev(), ...s1);
  check("  hovering over a point: cursor becomes move", ct.cHot?.kind === "pt" && ct.cursor() === "move");
  ct.pointerDown(ev(), ...s1);
  ct.pointerMove(ev(), (s1[0] + s1b[0]) / 2, (s1[1] + s1b[1]) / 2);
  ct.pointerMove(ev(), ...s1b);
  ct.pointerUp(ev());
  const p2 = H.parsePoints(W(cv, "points"));
  check("  drag a point: the second point moves to (−2, 0, 1), point count unchanged", p2.length === 3 && close(p2[1], [-2, 0, 1], 1e-4));
  // Ctrl + click a segment to insert a point
  const mid = H.mul(H.add(p2[0], p2[1]), 0.5);
  click(mid, { ctrlKey: true });
  const p3 = H.parsePoints(W(cv, "points"));
  check("  Ctrl + click a segment's midpoint: a point inserted between 0 and 1 (on the segment)",
        p3.length === 4 && close(p3[1], mid, 1e-3), W(cv, "points").replace(/\n/g, " | "));
  // Delete removes the hovered point
  ct.pointerMove(ev(), ...top.screen(p3[1]));
  const del = ct.key({ key: "Delete" });
  check("  Delete while hovering a point: removes it", del && H.parsePoints(W(cv, "points")).length === 3);
  // press then drag away = tumble, no point added
  const e0 = top.screen([3, 0, 3]);
  ct.pointerDown(ev(), ...e0);
  ct.pointerMove(ev(), e0[0] + 30, e0[1] + 10);
  ct.pointerMove(ev(), e0[0] + 60, e0[1] + 20);
  ct.pointerUp(ev());
  check("  press on empty space then drag away: tumbles, no point added", top.tumbled.length >= 1
        && H.parsePoints(W(cv, "points")).length === 3);
  // click the first point to close
  click(H.parsePoints(W(cv, "points"))[0]);
  check("  click the first point: Close Curve switched on, point count unchanged", W(cv, "closed") === true
        && H.parsePoints(W(cv, "points")).length === 3);
  // hitting geometry: lands on the surface
  top.pickSurface = () => [0.25, 1.5, 0.75];
  click([0, 0, 0]);
  const p4 = H.parsePoints(W(cv, "points"));
  check("  points hitting geometry land on the surface", close(p4[p4.length - 1], [0.25, 1.5, 0.75], 1e-6));
  top.pickSurface = () => null;
  // level view: vertical plane through the previous point
  const front = mkView([0, 0.5, 10], [0, 0.5, 0]);
  const ft = new H.HandleTool(front);
  ft.update();
  ft.pointerDown(ev(), ...front.screen([1, 2, 0.75]));
  ft.pointerUp(ev());
  const p5 = H.parsePoints(W(cv, "points"));
  check("  adding a point in a level view: lands on the camera-facing vertical plane through the previous point (z = previous point's z)",
        close(p5[p5.length - 1], [1, 2, 0.75], 1e-3), JSON.stringify(p5[p5.length - 1]));
  // malformed text: leave it alone
  cv.widgets.find((w) => w.name === "points").value = "1, 2, zz";
  const bad = ct.pointerDown(ev(), 100, 100);
  check("  malformed Points text: mouse not captured, text unchanged", !bad && W(cv, "points") === "1, 2, zz");
}

// ═════════════════════════════════════════════ 8. text format matches Python
sec("Points text: JS and geo/curvedraw.py use the same format");
{
  const texts = ["0.5, 0, 1.2\n1, 0, -0.3", "0.5,0,1.2 1,0,-0.3 2,1,1", "1 2 3; 4 5", "", "  -1e-3, .5, 7  "];
  const pts = [[0.123456, -0.00000001, 3], [1, 2, 3], [-0.5, 10.25, 1e-7]];
  const py = spawnSync("python3", ["-c", `
import sys, json; sys.path.insert(0, ${JSON.stringify(PKG)})
from comfyui_pcg.geo.curvedraw import parse_points, format_points
t = json.loads(sys.argv[1]); p = json.loads(sys.argv[2])
print(json.dumps({"parse": [parse_points(x).tolist() for x in t], "fmt": format_points(p)}))
`, JSON.stringify(texts), JSON.stringify(pts)], { encoding: "utf8" });
  if (py.error) console.log("  (cannot start python3, skipping this section: " + py.error.code + ")");
  else if (py.status !== 0) check("  python ran", false, py.stderr.slice(-300));
  else {
    const R = JSON.parse(py.stdout);
    check("  five spellings parse to the same result", texts.every((t, i) => close(H.parsePoints(t).flat(), R.parse[i].flat(), 1e-12)));
    check("  the text written back matches character for character", H.formatPoints(pts) === R.fmt, JSON.stringify([H.formatPoints(pts), R.fmt]));
  }
}

// ═════════════════════════════════════════════ 9. viewport mouse dispatch
sec("viewport: left button goes to the handle first; Alt + left button / handle declines -> tumble as usual");
{
  const v = Object.create(VP.Viewport.prototype);
  const el = document.createElement("canvas");
  const box = document.createElement("div");
  box.appendChild(el); document.body.appendChild(box);
  Object.assign(v, { renderer: { domElement: el }, container: box, T,
                     orbit: { theta: 0, phi: 1, dist: 5, target: [0, 0, 0] } });
  const log = [];
  v.tumble = (dx, dy) => log.push(["tumble", dx, dy]);
  v.track = () => log.push(["track"]);
  v.dolly = () => log.push(["dolly"]);
  let want = true;
  v.tool = {
    pointerDown(e, x, y) { log.push(["down", x, y]); return want; },
    pointerMove(e, x, y) { log.push(["move", x, y]); return false; },
    pointerUp() { log.push(["up"]); return true; },
    cursor() { return ""; }, key() { return false; },
  };
  v.bindInput();
  const fire = (type, o) => el.dispatchEvent(new MouseEvent(type, { bubbles: true, ...o }));
  fire("pointerdown", { button: 0, clientX: 10, clientY: 20 });
  fire("pointermove", { button: 0, clientX: 15, clientY: 25 });
  fire("pointerup", { button: 0 });
  check("  handle accepts: handle gets down / move / up, viewport does not tumble", log.some((l) => l[0] === "down")
        && log.some((l) => l[0] === "up") && !log.some((l) => l[0] === "tumble"), JSON.stringify(log));
  log.length = 0; want = false;
  fire("pointerdown", { button: 0, clientX: 10, clientY: 20 });
  fire("pointermove", { button: 0, clientX: 30, clientY: 20 });
  fire("pointerup", { button: 0 });
  check("  handle declines: tumbles as usual", log.some((l) => l[0] === "tumble"));
  log.length = 0; want = true;
  fire("pointerdown", { button: 0, altKey: true, clientX: 10, clientY: 20 });
  fire("pointermove", { button: 0, altKey: true, clientX: 30, clientY: 20 });
  fire("pointerup", { button: 0 });
  check("  Alt + left button: the handle is not even asked, tumbles directly", !log.some((l) => l[0] === "down")
        && log.some((l) => l[0] === "tumble"));
  v.dispose?.call({ ...v, renderer: { dispose() {} } });
}

console.log(`\n${OK.filter(Boolean).length}/${OK.length} passed`);
process.exit(OK.every(Boolean) ? 0 : 1);
