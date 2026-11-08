// pcg122: viewport selection and spreadsheet paging (frontend).
//   pcg_select.js   rangesExpr / parseRanges round trip; box and nearest picking; replace / add / remove; the
//                   SelectTool driven by pointer events on a fake orthographic view: click, box, Shift, Ctrl, class
//                   switch, visible-only (hidden points skipped; over budget selects through), dropped indices on new
//                   data, S / Esc keys, the toolbar shows the expression, "→ group" hands it to the node
//   pcg_viewport.js the real Viewport with real three.js (no WebGL): pickPrim maps the hit triangle to its primitive,
//                   hiddenPoint sees the far quad behind the near one; makeGroupNode creates a wired Group Create
//   pcg_spreadsheet pageStart arithmetic; Sheet.goto fetches the page from /pcg/sheet without touching widgets,
//                   renders it, disables the buttons at the ends; a 404 shows a note (negative control)
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
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "jstest_sel_"));
process.on("exit", () => fs.rmSync(ROOT, { recursive: true, force: true }));
const EXT = path.join(ROOT, "extensions", "comfyui_pcg");
fs.mkdirSync(path.join(ROOT, "scripts"), { recursive: true });
fs.mkdirSync(EXT, { recursive: true });
fs.writeFileSync(path.join(ROOT, "scripts", "app.js"), "export const app = globalThis.__app;\n");
for (const f of ["pcg_viewport.js", "pcg_volume.js", "pcg_select.js", "pcg_spreadsheet.js"])
  fs.copyFileSync(path.join(PKG, "web", f), path.join(EXT, f));
fs.writeFileSync(path.join(ROOT, "package.json"), '{"type":"module"}\n');

const dom = new JSDOM("<!doctype html><html><head></head><body></body></html>", { url: "http://localhost/" });
for (const k of ["window", "document", "HTMLElement", "Node"]) {
  Object.defineProperty(globalThis, k, { value: k === "window" ? dom.window : dom.window[k],
                                         writable: true, configurable: true });
}
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};
dom.window.HTMLCanvasElement.prototype.getContext = () => new Proxy({}, {
  get: (o, k) => (k in o ? o[k] : () => ({ addColorStop() {} })), set: (o, k, v) => { o[k] = v; return true; } });
globalThis.__app = { registerExtension() {}, graph: { _nodes: [] } };

const OK = [];
function check(name, cond, extra = "") {
  OK.push(!!cond);
  console.log((cond ? "  PASS  " : "  FAIL  ") + name + (extra === "" ? "" : "   " + extra));
}

const S = await import(path.join(EXT, "pcg_select.js"));

console.log("\n[expression and picking]");
check("rangesExpr: runs collapse, singles stay, input order and duplicates don't matter",
      S.rangesExpr([7, 0, 1, 2, 3, 4, 12, 13, 2, 19, 18, 17, 16, 15, 14]) === "0-4 7 12-19");
check("  empty selection -> empty string", S.rangesExpr([]) === "");
const big = Array.from({ length: 500 }, (_, i) => (i * 37) % 1009);
check("parseRanges(rangesExpr(x)) == sorted unique x",
      JSON.stringify(S.parseRanges(S.rangesExpr(big))) === JSON.stringify([...new Set(big)].sort((a, b) => a - b)));
const xy = new Float32Array([10, 10, 50, 50, 90, 10, NaN, NaN]);
check("boxPick: inside the box (either drag direction); NaN (behind the camera) never",
      JSON.stringify(S.boxPick(xy, 4, 0, 0, 60, 60)) === "[0,1]" && JSON.stringify(S.boxPick(xy, 4, 60, 60, 0, 0)) === "[0,1]");
check("nearPick: within r, nearest first", JSON.stringify(S.nearPick(xy, 4, 48, 47, 10)) === "[1]"
      && S.nearPick(xy, 4, 30, 30, 10).length === 0);
check("applyOp replace / add / remove",
      [...S.applyOp(new Set([1, 2]), [5], "replace")].join() === "5"
      && [...S.applyOp(new Set([1, 2]), [5], "add")].sort().join() === "1,2,5"
      && [...S.applyOp(new Set([1, 2]), [2, 9], "remove")].join() === "1");

console.log("\n[SelectTool on a fake view]");
// a 5 x 5 grid of points at integer (x, y), z = 0; screen = (100 + 20 x, 100 - 20 y)
const pos = [], ctr = [];
for (let j = 0; j < 5; j++) for (let i = 0; i < 5; i++) pos.push(i, j, 0);
for (let j = 0; j < 4; j++) for (let i = 0; i < 4; i++) ctr.push(i + 0.5, j + 0.5, 0);
const hidden = new Set();
const fake = {
  data: { arrays: { position: new Float32Array(pos), prim_center: new Float32Array(ctr) } },
  container: document.createElement("div"),
  screen: (p) => [100 + 20 * p[0], 100 - 20 * p[1]],
  mesh: {}, triCount: 10,
  hiddenPoint: (x, y) => hidden.has(`${Math.round(x)},${Math.round(y)}`),
  pickPrim: () => -1,
  _dirty: false,
};
const tool = new S.SelectTool(fake);
const ev = (o = {}) => ({ button: 0, shiftKey: false, ctrlKey: false, metaKey: false, ...o });
const click = (x, y, o) => { tool.pointerDown(ev(o), x, y); tool.pointerUp(ev(o), x, y); };
const drag = (x0, y0, x1, y1, o) => {
  tool.pointerDown(ev(o), x0, y0); tool.pointerMove(ev(o), (x0 + x1) / 2, (y0 + y1) / 2);
  tool.pointerMove(ev(o), x1, y1); tool.pointerUp(ev(o), x1, y1);
};
check("inactive: the tool does not take the pointer", tool.pointerDown(ev(), 100, 100) === false);
check("S key turns select mode on and shows the toolbar",
      tool.key({ key: "s" }) && tool.active && tool.bar && tool.bar.style.display === "flex");
click(143, 78);                          // near point (2, 1) at (140, 80)
check("click picks the nearest point: (2,1) = index 7", tool.expr() === "7", tool.expr());
click(300, 300);
check("  click on empty space with replace clears", tool.expr() === "");
drag(90, 110, 150, 50);                  // x 0..2, y 0..2 -> 9 points
check("box selects the 3 x 3 block", tool.expr() === "0-2 5-7 10-12", tool.expr());
click(180, 20, { shiftKey: true });      // point (4, 4) = 24
check("  Shift + click adds", tool.expr() === "0-2 5-7 10-12 24");
drag(90, 110, 150, 90, { ctrlKey: true });  // row y = 0, x 0..2
check("  Ctrl + box removes", tool.expr() === "5-7 10-12 24", tool.expr());
check("  the toolbar field shows the expression and the count",
      tool.field.value === "5-7 10-12 24" && tool.info.textContent === "7");
let action = null;
fake.onSelectAction = (k, c, e) => { action = [k, c, e]; };
tool.bGroup.onclick();
check("'→ group' hands (group, point, expression) to the node", JSON.stringify(action) === '["group","point","5-7 10-12 24"]');
hidden.add("1,1"); hidden.add("2,2");
drag(90, 110, 150, 50);
check("visible only: hidden points are skipped", tool.expr() === "0-2 5 7 10-11", tool.expr());
tool.visibleOnly = false;
drag(90, 110, 150, 50);
check("  visible off: selects through", tool.expr() === "0-2 5-7 10-12");
tool.visibleOnly = true;
fake.triCount = 1e7;
drag(90, 110, 150, 50);
check("  over the ray budget it selects through and says so",
      tool.expr() === "0-2 5-7 10-12" && tool.through && tool.info.textContent.includes("through"));
fake.triCount = 10; hidden.clear();
tool.setClass("prim");
check("switching to prims clears the selection", tool.sel.size === 0);
drag(95, 105, 145, 55);                  // centres (0.5..2.0) -> 0, 1, 4, 5
check("box selects primitives by their centres", tool.expr() === "0-1 4-5", tool.expr());
fake.pickPrim = () => 9;
click(10, 10);
check("click on a primitive uses the surface hit (pickPrim)", tool.expr() === "9");
fake.pickPrim = () => -1;
click(152, 48);                          // nearest centre (2.5, 2.5) = 10
check("  no surface hit: nearest centre", tool.expr() === "10");
tool.sel = new Set([3, 15]);
fake.data = { arrays: { position: new Float32Array(pos), prim_center: new Float32Array(ctr.slice(0, 30)) } };
tool.dataChanged();
check("new data with 10 prims drops index 15", tool.expr() === "3");
check("Esc leaves select mode", tool.key({ key: "Escape" }) && !tool.active && tool.bar.style.display === "none");
check("negative control: other keys are not taken when inactive", tool.key({ key: "x" }) === false);

console.log("\n[real Viewport: pickPrim / hiddenPoint / makeGroupNode]");
const T = await import(path.join(PKG, "web", "vendor", "three.module.js"));
const M = await import(path.join(EXT, "pcg_viewport.js"));
// two quads facing +z: prim 0 at z = 1 (near, x -1..1), prim 1 at z = -1 (far, x -1..3)
const P = new Float32Array([-1, -1, 1, 1, -1, 1, 1, 1, 1, -1, 1, 1, -1, -1, -1, 3, -1, -1, 3, 1, -1, -1, 1, -1]);
const arrays = {
  position: P, index: new Uint32Array([0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7]),
  tri_corner: new Uint32Array([0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7]),
  vertex_point: new Uint32Array([0, 1, 2, 3, 4, 5, 6, 7]), vertex_prim: new Uint32Array([0, 0, 0, 0, 1, 1, 1, 1]),
  prim_center: new Float32Array([0, 0, 1, 1, 0, -1]),
};
const v = Object.create(M.Viewport.prototype);
Object.assign(v, { T, root: new T.Group(), opts: { ...M.DEFAULTS }, data: { header: { buffers: {}, bbox: [[-1, -1, -1], [3, 1, 1]] }, arrays },
                   bbox: [[-1, -1, -1], [3, 1, 1]] });
for (const k of ["buildLabels", "updateLabelScale", "drawOverlay", "applyGrid", "updateGridScale"]) v[k] = () => {};
v.rebuild();
v.camera = new T.PerspectiveCamera(45, 1, 0.1, 100);
v.camera.position.set(0, 0, 6); v.camera.lookAt(0, 0, 0); v.camera.updateMatrixWorld(); v.camera.updateProjectionMatrix();
v.size = () => [200, 200];
const sc = v.screen([0, 0, 1]);
check("pickPrim: the centre pixel hits the near quad (prim 0)", v.pickPrim(sc[0], sc[1]) === 0, v.pickPrim(sc[0], sc[1]));
const sf = v.screen([2.5, 0, -1]);
check("  beside it only the far quad is hit (prim 1)", v.pickPrim(sf[0], sf[1]) === 1);
check("  empty space -> -1", v.pickPrim(2, 2) === -1);
check("hiddenPoint: a far point behind the near quad is hidden, one beside it is not, a near point is not",
      v.hiddenPoint(0, 0, -1) === true && v.hiddenPoint(2.5, 0, -1) === false && v.hiddenPoint(0.5, 0.5, 1) === false);

const created = [];
globalThis.LiteGraph = {
  createNode(type) {
    const n = { type, pos: [0, 0], widgets: [{ name: "name", value: "group1" }, { name: "cls", value: "point" },
                                               { name: "base", value: "" }], inputs: [{ name: "geo" }] };
    created.push(n);
    return n;
  },
};
const conns = [];
const src = { id: 3, pos: [100, 50], size: [200, 80], connect: (slot, node, inSlot) => conns.push([slot, node.type, inSlot]) };
const graph = { links: { 11: { origin_id: 3, origin_slot: 0 } }, getNodeById: (id) => (id === 3 ? src : null),
                add: (n) => { graph.added = n; } };
const vnode = { graph, inputs: [{ link: 11 }], pos: [400, 50], size: [360, 560] };
const gn = M.makeGroupNode(vnode, "prim", "0-4 7");
const w = Object.fromEntries(gn.widgets.map((x) => [x.name, x.value]));
check("makeGroupNode: Group Create with cls prim, base = expression, name selection",
      gn.type === "PCG_GroupCreate" && w.cls === "prim" && w.base === "0-4 7" && w.name === "selection");
check("  added to the graph and wired from the viewport's source (slot 0 -> input 0), placed right of it",
      graph.added === gn && JSON.stringify(conns) === '[[0,"PCG_GroupCreate",0]]' && gn.pos[0] > src.pos[0] + 200);

console.log("\n[spreadsheet paging]");
const SP = await import(path.join(EXT, "pcg_spreadsheet.js"));
check("pageStart: next / prev / first / last, clamped",
      SP.pageStart(0, 64, 1000, "next") === 64 && SP.pageStart(64, 64, 1000, "prev") === 0
      && SP.pageStart(0, 64, 1000, "prev") === 0 && SP.pageStart(5, 64, 1000, "last") === 960
      && SP.pageStart(960, 64, 1000, "next") === 960 && SP.pageStart(100, 64, 1000, "first") === 0);
const mkTable = (start, n, count) => ({ count, start, cols: [{ name: "id", size: 1, kind: "i", meta: false }],
                                        rows: Array.from({ length: n }, (_, i) => [start + i]), groups: [] });
const root = document.createElement("div");
document.body.appendChild(root);
const sheet = new SP.Sheet(root);
sheet.setData({ node_id: "5", rev: 1, rows: 64, counts: { point: 1000, vertex: 0, prim: 0, detail: 1 },
                bbox: [[0, 0, 0], [1, 1, 1]],
                tables: { point: mkTable(0, 64, 1000), vertex: mkTable(0, 0, 0), prim: mkTable(0, 0, 0),
                          detail: mkTable(0, 0, 1) } });
const btn = (g) => root.querySelector(`button[data-go="${g}"]`);
check("pager shown with prev / first disabled on the first page", btn("next") && btn("prev").disabled && !btn("next").disabled);
const urls = [];
const fakeFetch = async (u) => {
  urls.push(u);
  const q = new URL(u, "http://x").searchParams;
  if (u.includes("/pcg/sheet/404")) return { ok: false, status: 404, text: async () => "" };
  return { ok: true, json: async () => ({ rev: 1, cls: q.get("cls"), table: mkTable(+q.get("start"), Math.min(64, 1000 - +q.get("start")), 1000) }) };
};
await sheet.goto(960, fakeFetch);
const firstIdx = root.querySelector("tbody td.idx")?.textContent;
check("goto(960) fetches /pcg/sheet/5?cls=point&start=960&rows=64 and renders rows from 960",
      urls[0] === "/pcg/sheet/5?cls=point&start=960&rows=64" && firstIdx === "960", `${urls[0]} ${firstIdx}`);
check("  on the last page next / last are disabled", btn("next").disabled && btn("last").disabled && !btn("prev").disabled);
check("  footer shows the page range", root.querySelector(".pcg-ss-foot").textContent.includes("Showing 960–999 / 1000"));
sheet.data.node_id = "404";
await sheet.goto(0, fakeFetch);
check("negative control: a 404 keeps the table and shows a note", root.querySelector(".pcg-ss-foot").textContent
      .includes("not cached") && root.querySelector("tbody td.idx")?.textContent === "960");

console.log(`\n${OK.filter(Boolean).length}/${OK.length} passed`);
process.exit(OK.every(Boolean) ? 0 : 1);
