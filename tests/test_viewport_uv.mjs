// pcg114: UV in the viewport. Runs the real Viewport code with the real three.js (web/vendor), no WebGL.
//   - uvLayout: vertex uv over point uv, size 2 and 3, per-vertex edges (seams stay apart), open curves left out,
//     triangles wound against the majority counted and coloured as flipped
//   - shading = uv: per-corner uv on the mesh, the checker map, Cd ignored, a warning without uv
//   - key 5 toggles the UV view, 1-4 return to 3D; a focused <select> / button no longer swallows the view keys
//     (the floating panel's toolbar keeps focus), typing in a text box still does; clicking the view blurs it
//   - UV view navigation: zoom keeps the point under the cursor, F frames the layout with the 0-1 tile
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
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "jstest_uv_"));
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
const near = (a, b, e = 1e-5) => a.length === b.length && a.every((x, i) => Math.abs(x - b[i]) < e);

// Three quads in a row (4 x 2 points), CCW in xy; vertex k of quad q is vertex q*4+k; fan triangulation
const P = new Float32Array([0, 0, 0, 1, 0, 0, 2, 0, 0, 3, 0, 0, 0, 1, 0, 1, 1, 0, 2, 1, 0, 3, 1, 0]);
const quads = [[0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6]];
const vertex_point = new Uint32Array(quads.flat());
const vertex_prim = new Uint32Array([0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2]);
const tri_corner = new Uint32Array(quads.flatMap((_, q) => [q * 4, q * 4 + 1, q * 4 + 2, q * 4, q * 4 + 2, q * 4 + 3]));
const index = new Uint32Array(Array.from(tri_corner, (v) => vertex_point[v]));
// vertex uv (size 3, like Houdini): u = x / 3, v = y; quad 2 mirrored in u (u = 2 - x / 3)
const vuv = new Float32Array(Array.from(vertex_point).flatMap((p, v) => {
  const x = P[p * 3], y = P[p * 3 + 1];
  return [vertex_prim[v] === 2 ? 2 - x / 3 : x / 3, y, 0];
}));
const puv = new Float32Array([0, 1, 2, 3, 0, 1, 2, 3].flatMap((x, i) => [x / 3, i < 4 ? 0 : 1]));   // size 2
const base = { position: P, index, tri_corner, vertex_point, vertex_prim };
const payload = (arrays, header = {}) => ({ header: { buffers: {}, ...header }, arrays: { ...base, ...arrays } });

console.log("\n[uvLayout]");
const L = M.uvLayout(payload({ a_vertex_uv: vuv }, { attrib_meta: { vertex: { uv: { size: 3 } } } }));
check("vertex uv: 6 triangles, 2 flipped (the mirrored quad)", L && L.cls === "vertex" && L.nTri === 6 && L.flipped === 2,
      L && `${L.nTri} ${L.flipped}`);
check("  flipped triangles are coloured UV_FLIP, the others UV_FRONT",
      near(Array.from(L.col.slice(0, 3)), M.UV_FRONT) && near(Array.from(L.col.slice(4 * 9, 4 * 9 + 3)), M.UV_FLIP)
      && near(Array.from(L.col.slice(3 * 9 + 6, 3 * 9 + 9)), M.UV_FRONT));
// corner 0 of triangle 4 is vertex 8 (point 2, x = 2): u = 2 - 2/3
check("  triangle corners carry the vertex uv", near(Array.from(L.tri.slice(4 * 9, 4 * 9 + 3)), [2 - 2 / 3, 0, 0]));
check("  edges: 4 per quad, as uv segments", L.edges.length === 12 * 6, L.edges.length / 6);
// the shared 3D edge between quad 1 and 2 (points 2-6) is two different uv edges: u = 2/3 and u = 2 - 2/3
const segs = []; for (let i = 0; i < L.edges.length; i += 6) segs.push(Array.from(L.edges.slice(i, i + 6)));
const vert = (u) => segs.some((e) => Math.abs(e[0] - u) < 1e-5 && Math.abs(e[3] - u) < 1e-5 && Math.abs(e[1] - e[4]) > 0.5);
check("  a uv seam stays two edges (u = 2/3 and u = 4/3)", vert(2 / 3) && vert(4 / 3));
check("  bbox covers the mirrored quad", near(L.bbox, [0, 0, 4 / 3, 1]), L.bbox);
const L2 = M.uvLayout(payload({ a_point_uv: puv }));
check("point uv (size 2, no meta): read through vertex_point, nothing flipped",
      L2 && L2.cls === "point" && L2.flipped === 0 && L2.edges.length === 72 && near(L2.bbox, [0, 0, 1, 1]));
check("vertex uv wins over point uv", M.uvLayout(payload({ a_point_uv: puv, a_vertex_uv: vuv })).cls === "vertex");
const Lc = M.uvLayout(payload({ a_vertex_uv: new Float32Array([...vuv, 0, 0, 0, 1, 0, 0, 1, 1, 0]),
                                 vertex_point: new Uint32Array([...vertex_point, 0, 1, 2]),
                                 vertex_prim: new Uint32Array([...vertex_prim, 3, 3, 3]) }));
check("an open curve (prim without triangles) adds no uv edges", Lc.edges.length === 72, Lc.edges.length / 6);
check("no uv attribute: null", M.uvLayout(payload({})) === null);
const tie = M.uvLayout(payload({ a_vertex_uv: vuv, index: index.slice(0, 6), tri_corner: tri_corner.slice(0, 6) }));
check("negative control: without the mirrored quad nothing is flipped", tie.flipped === 0 && tie.nTri === 2);

console.log("\n[shading = uv]");
function view(arrays, header = {}, opts = {}) {
  const v = Object.create(M.Viewport.prototype);
  Object.assign(v, { T, root: new T.Group(), opts: { ...M.DEFAULTS, ...opts }, data: payload(arrays, header) });
  for (const k of ["buildLabels", "updateLabelScale", "drawOverlay", "applyGrid", "updateGridScale"]) v[k] = () => {};
  v.rebuild();
  return v;
}
const meshOf = (v) => v.root.children.find((c) => c.isMesh);
const cd = new Float32Array(24).fill(0.5);
const ptN = new Float32Array(24).map((_, i) => (i % 3 === 2 ? 1 : 0));
// point normals would keep the mesh indexed: the split here comes from the vertex uv
const sv = view({ a_vertex_uv: vuv, color: cd, normal: ptN }, { color_class: "point" }, { shading: "uv" });
const sm = meshOf(sv), suv = sm.geometry.getAttribute("uv");
check("vertex uv: split mesh with a per-corner uv", suv && !sm.geometry.index && suv.count === 18
      && near(Array.from(suv.array.slice(24, 26)), [2 - 2 / 3, 0]));
check("  checker map on a Lambert material, white base", sm.material.isMeshLambertMaterial && sm.material.map?.isDataTexture
      && sm.material.color.getHex() === 0xffffff && sm.material.map.wrapS === T.RepeatWrapping);
check("  Cd is not drawn under the checker", !sm.geometry.getAttribute("color") && !sm.material.vertexColors);
check("  no warning", !sv.uvWarning);
// (point normals keep the mesh indexed; without any normals it is split for flat shading)
const pv = meshOf(view({ a_point_uv: puv, tri_corner: undefined, vertex_point: undefined, vertex_prim: undefined,
                         normal: ptN },
                       {}, { shading: "uv" }));
check("point uv without corners: indexed mesh with a per-point uv", pv.geometry.index
      && near(Array.from(pv.geometry.getAttribute("uv").array), Array.from(puv)));
const pv2 = meshOf(view({ a_point_uv: puv, tri_corner: undefined }, {}, { shading: "uv" }));
check("point uv on a split (flat) mesh: per-corner uv through index", !pv2.geometry.index
      && near(Array.from(pv2.geometry.getAttribute("uv").array.slice(4, 6)), [puv[index[2] * 2], puv[index[2] * 2 + 1]]));
const nv = view({}, {}, { shading: "uv" });
check("no uv: grey, no map, HUD warning", !meshOf(nv).material.map && nv.uvWarning === "no uv attribute");
const ph = meshOf(view({ a_vertex_uv: vuv }));
check("negative control: phong shading has no map", !ph.material.map);

console.log("\n[keys and focus]");
document.body.innerHTML = '<select id="s"><option>a</option></select><input id="t"><input id="c" type="checkbox">' +
                          '<div id="v"></div>';
const kv = Object.create(M.Viewport.prototype);
const canvas = document.createElement("canvas");
document.getElementById("v").appendChild(canvas);
Object.assign(kv, { T, container: document.getElementById("v"), renderer: { domElement: canvas },
                    orbit: { theta: 0, phi: 1, dist: 5, target: [0, 0, 0] }, data: payload({ a_vertex_uv: vuv }),
                    opts: { ...M.DEFAULTS } });
kv.size = () => [600, 400];
kv.bindInput();
kv.hover = true;
const key = (id, k) => document.getElementById(id).dispatchEvent(
  new dom.window.KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true }));
key("s", "2");
check("a focused <select> lets 2 through (top view)", Math.abs(kv.orbit.phi - 0.02) < 1e-9, kv.orbit.phi);
key("c", "3");
check("  a focused checkbox too (front view)", Math.abs(kv.orbit.phi - Math.PI / 2) < 1e-9);
key("t", "1");
check("typing in a text box keeps its keys", Math.abs(kv.orbit.phi - Math.PI / 2) < 1e-9);
check("isTypingTarget: text / textarea / contentEditable yes; select / checkbox / range no",
      M.isTypingTarget(document.getElementById("t")) && M.isTypingTarget(document.createElement("textarea"))
      && M.isTypingTarget(Object.assign(document.createElement("div"), { isContentEditable: true }))
      && !M.isTypingTarget(document.getElementById("s")) && !M.isTypingTarget(document.getElementById("c"))
      && !M.isTypingTarget(Object.assign(document.createElement("input"), { type: "range" })));
document.getElementById("s").focus();
canvas.dispatchEvent(new dom.window.MouseEvent("pointerdown", { button: 0, bubbles: true, cancelable: true }));
canvas.dispatchEvent(new dom.window.MouseEvent("pointerup", { button: 0, bubbles: true }));
check("clicking the view releases a focused toolbar control", document.activeElement === document.body,
      document.activeElement.tagName);
kv.hover = false; key("s", "2"); kv.hover = true;
check("negative control: keys do nothing while the pointer is elsewhere", Math.abs(kv.orbit.phi - Math.PI / 2) < 1e-9);

key("s", "5");
check("5: UV view on, framed, layout built", kv.uvMode === true && kv.uvCam && kv.uvInfo?.flipped === 2
      && kv.uvGroup.children.some((c) => c.isMesh) && kv.uvGroup.children.some((c) => c.isLineSegments));
// framed: bbox [0, 0, 4/3, 1] with the tile, aspect 1.5 -> height 1 wins: half = 0.5 * 1.25
check("  framing: centred on the layout (nudged up), height fits", Math.abs(kv.uvCam.cx - 2 / 3) < 1e-6
      && Math.abs(kv.uvCam.h - 0.625) < 1e-6 && Math.abs(kv.uvCam.cy - (0.5 + 0.625 * 0.08)) < 1e-6, JSON.stringify(kv.uvCam));
const before = kv.uvAt(450, 120);
kv.uvZoom(-30, 450, 120);
const after = kv.uvAt(450, 120);
check("  zoom keeps the uv under the cursor", near(before, after, 1e-9) && kv.uvCam.h < 0.625);
check("  uvScreen inverts uvAt", near(kv.uvScreen(...after), [450, 120], 1e-6));
const c0 = kv.uvCam.cx;
kv.uvPan(60, 0);
check("  dragging right moves the view left (content follows the mouse)", kv.uvCam.cx < c0);
key("s", "f");
check("  F reframes", Math.abs(kv.uvCam.h - 0.625) < 1e-6);
key("s", "1");
check("1: back to 3D, perspective view", kv.uvMode === false && Math.abs(kv.orbit.phi - 1.1) < 1e-9);
key("s", "5"); key("s", "5");
check("5 twice: back to 3D", kv.uvMode === false);
kv.data = payload({}); kv._uvDirty = true; kv.uvCam = null;   // new geometry, never looked at in UV
key("s", "5");
check("no uv: the UV view opens empty (the HUD says no uv), framed on the tile", kv.uvMode && kv.uvInfo === null
      && kv.uvGroup.children.length === 0 && Math.abs(kv.uvCam.cx - 0.5) < 1e-9);

console.log(`\n${OK.filter(Boolean).length}/${OK.length} passed`);
process.exit(OK.every(Boolean) ? 0 : 1);
