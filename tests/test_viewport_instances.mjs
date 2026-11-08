// pcg121: packed primitives in the viewport. Runs the real Viewport.rebuild with the real three.js (web/vendor), no
// WebGL: one InstancedMesh per instance set, matrices read column-major, per-copy colours, piece colours as vertex
// colours, wire-only shading draws none; negative control: no instances in the header -> no InstancedMesh.
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
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "jstest_inst_"));
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
globalThis.requestAnimationFrame = () => 0;
// jsdom has no 2D canvas; the round point sprite only needs these calls to exist
dom.window.HTMLCanvasElement.prototype.getContext = () => new Proxy({}, {
  get: (o, k) => (k in o ? o[k] : () => ({ addColorStop() {} })), set: (o, k, v) => { o[k] = v; return true; } });
globalThis.cancelAnimationFrame = () => {};
globalThis.__app = { registerExtension() {}, graph: { _nodes: [] } };

const OK = [];
function check(name, cond, extra = "") {
  OK.push(!!cond);
  console.log((cond ? "  PASS  " : "  FAIL  ") + name + (extra === "" ? "" : "   " + extra));
}


const T = await import(path.join(PKG, "web", "vendor", "three.module.js"));
const M = await import(path.join(EXT, "pcg_viewport.js"));

function view(arrays, header = {}, opts = {}) {
  const v = Object.create(M.Viewport.prototype);
  Object.assign(v, { T, root: new T.Group(), opts: { ...M.DEFAULTS, ...opts },
                     data: { header: { buffers: {}, ...header }, arrays } });
  for (const k of ["buildLabels", "updateLabelScale", "drawOverlay", "applyGrid", "updateGridScale"]) v[k] = () => {};
  v.rebuild();
  return v;
}
// one triangle piece, three copies: identity, translated by (5, 0, 0), scaled by 2
const pos = new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]);
const nrm = new Float32Array([0, 0, 1, 0, 0, 1, 0, 0, 1]);
const cm = (m) => { const o = []; for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) o.push(m[r][c]); return o; };
const I = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]];
const Tr = [[1, 0, 0, 5], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]];
const S2 = [[2, 0, 0, 0], [0, 2, 0, 0], [0, 0, 2, 0], [0, 0, 0, 1]];
const mtx = new Float32Array([...cm(I), ...cm(Tr), ...cm(S2)]);
const icol = new Float32Array([1, 0, 0, 0, 1, 0, 0, 0, 1]);
const arrays = { position: new Float32Array([0, 0, 0, 5, 0, 0, 0, 0, 0]),
                 i0_position: pos, i0_normal: nrm, i0_matrix: mtx, i0_icolor: icol,
                 i0_color: new Float32Array([1, 1, 1, 0.5, 0.5, 0.5, 1, 1, 1]) };
const header = { instances: [{ id: 0, count: 3, tris: 1, color: true, icolor: true }] };
const v = view(arrays, header);
const ims = v.root.children.filter((c) => c.isInstancedMesh);
check("one InstancedMesh with 3 copies", ims.length === 1 && ims[0].count === 3, ims.length);
const im = ims[0], m4 = new T.Matrix4(), p = new T.Vector3();
im.getMatrixAt(1, m4); p.set(1, 0, 0).applyMatrix4(m4);
check("copy 1: matrix read column-major (translation lands in the 4th column): (1,0,0) -> (6,0,0)",
      Math.abs(p.x - 6) < 1e-6 && Math.abs(p.y) < 1e-6);
im.getMatrixAt(2, m4); p.set(0, 1, 0).applyMatrix4(m4);
check("copy 2: scaled by 2", Math.abs(p.y - 2) < 1e-6);
const c = new T.Color(); im.getColorAt(2, c);
check("per-copy colour from the packed points' Cd (copy 2 blue)", c.b === 1 && c.r === 0 && c.g === 0);
check("piece colours become vertex colours", im.material.vertexColors === true && !!im.geometry.getAttribute("color"));
check("triangle count includes the copies (3 x 1)", v.triCount === 3, v.triCount);
const vw = view(arrays, header, { shading: "wire" });
check("wire-only shading: no instanced faces", vw.root.children.filter((c) => c.isInstancedMesh).length === 0);
const vn = view(arrays, header, { shading: "normal" });
check("normal shading: MeshNormalMaterial, no per-copy colour", vn.root.children.find((c) => c.isInstancedMesh)
      ?.material.isMeshNormalMaterial && !vn.root.children.find((c) => c.isInstancedMesh).instanceColor);
const v0 = view(arrays, {});
check("negative control: no instances in the header -> no InstancedMesh",
      v0.root.children.filter((c) => c.isInstancedMesh).length === 0);

console.log(`\n${OK.filter(Boolean).length}/${OK.length} passed`);
process.exit(OK.every(Boolean) ? 0 : 1);
