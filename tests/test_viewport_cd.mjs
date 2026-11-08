// pcg109: Cd in the shaded viewport, as in Houdini. Runs the real Viewport.prototype.rebuild with the real three.js
// (web/vendor) on hand-made payloads -- no WebGL is needed to build meshes and materials, only to draw them.
//   - Phong (the default), Lambert and Color shading all use Cd
//   - point Cd: indexed mesh with a per-point colour; vertex / prim Cd: split corners with per-corner / per-face colours
//   - detail Cd tints the material; no Cd keeps the grey base; a visualized attribute wins over Cd
//   - curves and point clouds take a point Cd; point markers on a mesh or curve keep their own colour
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
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "jstest_cd_"));
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

// Two quads sharing an edge: 6 points, 8 vertices, 2 prims, 4 triangles
const P = new Float32Array([0, 0, 0, 1, 0, 0, 2, 0, 0, 0, 1, 0, 1, 1, 0, 2, 1, 0]);
const index = new Uint32Array([0, 1, 4, 0, 4, 3, 1, 2, 5, 1, 5, 4]);
const tri_corner = new Uint32Array([0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7]);
const vertex_prim = new Uint32Array([0, 0, 0, 0, 1, 1, 1, 1]);

function view(arrays, header = {}, opts = {}) {
  const v = Object.create(M.Viewport.prototype);
  Object.assign(v, { T, root: new T.Group(), opts: { ...M.DEFAULTS, ...opts },
                     data: { header: { buffers: {}, ...header },
                             arrays: { position: P, index, tri_corner, vertex_prim, ...arrays } } });
  // what rebuild calls besides building meshes is not under test here
  for (const k of ["buildLabels", "updateLabelScale", "drawOverlay", "applyGrid", "updateGridScale"])
    v[k] = () => {};
  v.rebuild();
  return v;
}
const meshOf = (v) => v.root.children.find((c) => c.isMesh);
const colorsAt = (g) => Array.from(g.getAttribute("color")?.array || []);
const near = (a, b) => a.length === b.length && a.every((x, i) => Math.abs(x - b[i]) < 1e-6);
// point colours on either mesh layout: indexed (one colour per point) or split (one per triangle corner; flat normals
// split the mesh because there are no point normals in these payloads)
const pointColoursOk = (g, cd) => {
  const c = colorsAt(g);
  return g.index ? near(c, Array.from(cd))
    : near(c, Array.from(index).flatMap((p) => [cd[p * 3], cd[p * 3 + 1], cd[p * 3 + 2]]));
};

// point Cd: point 4 red, the rest blue
const ptCd = new Float32Array(18).map((_, i) => (i % 3 === 2 ? 1 : 0));
ptCd.set([1, 0, 0], 12);
for (const shading of ["phong", "lambert", "color"]) {
  const m = meshOf(view({ color: ptCd }, { color_class: "point" }, { shading }));
  check(`point Cd shows in ${shading} shading (vertexColors on, white base)`,
        m.material.vertexColors === true && m.material.color.getHex() === 0xffffff
        && pointColoursOk(m.geometry, ptCd), `${m.material.type}`);
}
const sm = meshOf(view({ color: ptCd, normal: new Float32Array(18).map((_, i) => (i % 3 === 2 ? 1 : 0)) },
                       { color_class: "point" }));
check("  with point normals the mesh stays indexed and carries one colour per point",
      sm.geometry.index !== null && pointColoursOk(sm.geometry, ptCd));
const noCd = meshOf(view({}, {}, { shading: "phong" }));
check("no Cd: grey base, no vertex colours (unchanged)", !noCd.material.vertexColors
      && noCd.material.color.getHex() === 0xdedee2 && !noCd.geometry.getAttribute("color"));
check("  negative control: the check really sees the difference",
      meshOf(view({ color: ptCd }, { color_class: "point" })).material.vertexColors !== noCd.material.vertexColors);
const legacy = meshOf(view({ color: ptCd }, {}, { shading: "phong" }));
check("a payload without color_class (older backend) is read as point Cd", legacy.material.vertexColors === true
      && pointColoursOk(legacy.geometry, ptCd),
      `${legacy.material.vertexColors} ${legacy.geometry.getAttribute("color")?.count}`);

// prim Cd: prim 0 red, prim 1 green -> split corners, each triangle coloured by its face
const prCd = new Float32Array([1, 0, 0, 0, 1, 0]);
const pm = meshOf(view({ color: prCd }, { color_class: "prim" }));
const pc = colorsAt(pm.geometry);
check("prim Cd: corners split, triangles of prim 0 red, of prim 1 green",
      pm.geometry.index === null && pc.length === 36 && near(pc.slice(0, 18), Array(6).fill([1, 0, 0]).flat())
      && near(pc.slice(18), Array(6).fill([0, 1, 0]).flat()), pc.slice(0, 6).join(","));

// vertex Cd: vertex k gets grey level k/8 -> corner colours follow tri_corner
const vxCd = new Float32Array(24).map((_, i) => Math.floor(i / 3) / 8);
const vc = colorsAt(meshOf(view({ color: vxCd }, { color_class: "vertex" })).geometry);
const want = Array.from(tri_corner).flatMap((c) => [c / 8, c / 8, c / 8]);
check("vertex Cd: each triangle corner takes its own vertex's colour", near(vc, want));

// detail Cd: tints the material, no vertex colours
const dm = meshOf(view({ color: new Float32Array([0.5, 0.25, 1]) }, { color_class: "detail" }));
check("detail Cd tints the whole mesh", !dm.material.vertexColors
      && near(dm.material.color.toArray(), [0.5, 0.25, 1]), dm.material.color.toArray().join(","));

// a visualized attribute wins over Cd
const vz = view({ color: ptCd, a_point_h: new Float32Array([0, 1, 2, 3, 4, 5]) },
                { color_class: "point", attrib_meta: { point: { h: { size: 1, min: [0], max: [5] } } } },
                { visualize: "point:h" });
const vzc = colorsAt(meshOf(vz).geometry);
check("visualize overrides Cd (colours come from the ramp, not Cd)", vzc.length > 0 && !near(vzc.slice(12, 15), [1, 0, 0]));

// curves and point clouds
const lv = view({ index: undefined, tri_corner: undefined, lines: new Uint32Array([0, 1, 1, 2]), color: ptCd },
                { color_class: "point" });
const line = lv.root.children.find((c) => c.isLineSegments);
check("curves take a point Cd", line && line.material.vertexColors === true && !!line.geometry.getAttribute("color"));
const cv = view({ index: undefined, tri_corner: undefined, color: ptCd }, { color_class: "point" });
const pts = cv.root.children.find((c) => c.isPoints);
check("point clouds take a point Cd at full brightness", pts && pts.material.vertexColors === true
      && pts.material.color.getHex() === 0xffffff);

// point markers on a mesh / curve are an overlay in their own colour, whatever Cd is (they vanished on a red mesh)
const mp = view({ color: ptCd }, { color_class: "point" }, { show_points: true }).root.children.find((c) => c.isPoints);
check("Points on a mesh with point Cd: markers in the fixed cyan, no vertex colours",
      mp && mp.material.vertexColors === false && mp.material.color.getHex() === 0x39dbe0
      && !mp.geometry.getAttribute("color"));
const mv = view({ color: ptCd, a_point_h: new Float32Array([0, 1, 2, 3, 4, 5]) },
                { color_class: "point", attrib_meta: { point: { h: { size: 1, min: [0], max: [5] } } } },
                { visualize: "point:h", show_points: true }).root.children.find((c) => c.isPoints);
check("  ... and with a visualized point attribute too", mv && mv.material.vertexColors === false
      && mv.material.color.getHex() === 0x39dbe0);
const lp = view({ index: undefined, tri_corner: undefined, lines: new Uint32Array([0, 1, 1, 2]), color: ptCd },
                { color_class: "point" }, { show_points: true }).root.children.find((c) => c.isPoints);
check("  ... and on a curve", lp && lp.material.vertexColors === false && lp.material.color.getHex() === 0x39dbe0);
const cp = view({ index: undefined, tri_corner: undefined, color: ptCd }, { color_class: "point" },
                { show_points: true }).root.children.find((c) => c.isPoints);
check("  a point cloud keeps its Cd with Points on (the points are the geometry)",
      cp && cp.material.vertexColors === true && !!cp.geometry.getAttribute("color"));

console.log(`\n${OK.filter(Boolean).length}/${OK.length} passed`);
process.exit(OK.every(Boolean) ? 0 : 1);
