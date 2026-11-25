// Tests for network boxes and the colour palette (pcg_netbox.js): collapsing a group stacks its nodes collapsed at its
// top left and shrinks it, expanding puts every node back as it was (collapsed or not) -- also after a save and load
// (the state is in the group's flags); the palette colours nodes (title + darker body) and groups, resets them, sets
// shapes; C opens it only with a selection and not while typing.
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
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "jstest_"));
process.on("exit", () => fs.rmSync(ROOT, { recursive: true, force: true }));
const EXT = path.join(ROOT, "extensions", "comfyui_pcg");
fs.mkdirSync(path.join(ROOT, "scripts"), { recursive: true });
fs.mkdirSync(EXT, { recursive: true });
fs.writeFileSync(path.join(ROOT, "scripts", "app.js"), "export const app = globalThis.__app;\n");
fs.copyFileSync(path.join(PKG, "comfyui_pcg", "web", "pcg_netbox.js"), path.join(EXT, "pcg_netbox.js"));

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
for (const k of ["window", "document", "HTMLElement", "KeyboardEvent", "Event", "MouseEvent"])
  Object.defineProperty(globalThis, k, { value: k === "window" ? dom.window : dom.window[k], writable: true, configurable: true });

const OK = [];
function check(name, cond, extra = "") {
  OK.push(!!cond);
  console.log((cond ? "  PASS  " : "  FAIL  ") + name + (extra === "" ? "" : "   " + extra));
}
const J = JSON.stringify;

class Node {
  constructor(id, x, y, w = 140, h = 80) {
    this.id = id; this.pos = [x, y]; this.size = [w, h]; this.flags = {}; this.inputs = []; this.title = `n${id}`;
  }
  collapse() { this.flags.collapsed = !this.flags.collapsed; }
  getBounding() { return this.flags.collapsed ? [this.pos[0], this.pos[1] - 30, 90, 30] : [this.pos[0], this.pos[1] - 30, ...this.size]; }
}
class LGraphGroup {
  constructor(title, x, y, w, h) { this.title = title; this.pos = [x, y]; this.size = [w, h]; this.flags = {}; this._bounding = []; this._nodes = []; }
  get nodes() { return this._nodes; }
  recomputeInsideNodes() {
    this._nodes = this.graph._nodes.filter((n) => n.pos[0] >= this.pos[0] && n.pos[1] >= this.pos[1]
      && n.pos[0] + n.size[0] <= this.pos[0] + this.size[0] && n.pos[1] + n.size[1] <= this.pos[1] + this.size[1]);
  }
  getMenuOptions() { return [{ content: "Title" }]; }
}
globalThis.LiteGraph = { NODE_TITLE_HEIGHT: 30, LGraphGroup, BOX_SHAPE: 1, ROUND_SHAPE: 2, CARD_SHAPE: 4 };
const graph = { _nodes: [], dirty: 0, setDirtyCanvas() { this.dirty++; },
                getNodeById(id) { return this._nodes.find((n) => n.id === id) ?? null; } };
const canvas = { selected_nodes: {} };
globalThis.__app = { graph, canvas, exts: [], registerExtension(e) { this.exts.push(e); } };

const M = await import(path.join(EXT, "pcg_netbox.js"));
const ext = globalThis.__app.exts[0];
await ext.setup();

console.log("── Collapsing a network box");
const a = new Node(1, 120, 140), b = new Node(2, 320, 140), c = new Node(3, 120, 300), out = new Node(4, 900, 140);
c.flags.collapsed = true;                                   // already collapsed: stays so on expanding
graph._nodes.push(a, b, c, out);
const g = new LGraphGroup("Rocks", 100, 80, 420, 360);
g.graph = graph;
check("boxNodes: the nodes inside the box (not the one outside)", J(M.boxNodes(g).map((n) => n.id)) === J([1, 2, 3]));
check("collapseBox: done", M.collapseBox(g) === true);
check("  every node inside collapsed", a.flags.collapsed && b.flags.collapsed && c.flags.collapsed && !out.flags.collapsed);
check("  stacked at the box's top left in reading order (top to bottom, left to right: 1, 2, 3), a title bar apart",
      J([a.pos, b.pos, c.pos]) === J([[110, 150], [110, 186], [110, 222]]), J([a.pos, b.pos, c.pos]));
check("  the box shrinks round them (title 30 + 10 + three rows of 36 + 10 = 158 high), its title marked", J(g.size) === J([140, 158]) && g.title === "▸ Rocks", J([g.size, g.title]));
check("  the node outside untouched", J(out.pos) === J([900, 140]));
check("  collapsing again does nothing", M.collapseBox(g) === false);
const opts = g.getMenuOptions();
check("the group's menu offers Expand Box when collapsed", opts.some((o) => o?.content === "PCG: Expand Box"));
// a save and a load: the group's flags go into the workflow as they are
const saved = J({ flags: g.flags, pos: g.pos, size: g.size, title: g.title });
const g2 = new LGraphGroup("x", 0, 0, 10, 10);
Object.assign(g2, JSON.parse(saved));
g2.graph = graph;
check("expandBox (after a save and load): done", M.expandBox(g2) === true);
check("  every node back where it was", J([a.pos, b.pos, c.pos]) === J([[120, 140], [320, 140], [120, 300]]), J([a.pos, b.pos, c.pos]));
check("  as it was: 1 and 2 open again, 3 still collapsed", !a.flags.collapsed && !b.flags.collapsed && c.flags.collapsed);
check("  the box back to its place, size and title; nothing left in its flags",
      J([g2.pos, g2.size, g2.title]) === J([[100, 80], [420, 360], "Rocks"]) && !("pcg_box" in g2.flags), J([g2.pos, g2.size, g2.title]));
check("  expanding a box that is not collapsed does nothing", M.expandBox(g2) === false);
check("the group's menu offers Collapse Box when expanded", g2.getMenuOptions().some((o) => o?.content === "PCG: Collapse Box"));
const empty = new LGraphGroup("empty", 2000, 2000, 200, 200);
empty.graph = graph;
check("  negative control: a box with no nodes is not collapsed", M.collapseBox(empty) === false && !M.isCollapsed(empty));
// a node deleted while its box is collapsed: the rest still expand
M.collapseBox(g2);
graph._nodes.splice(graph._nodes.indexOf(b), 1);
check("  a node deleted while the box was collapsed: the others still expand", M.expandBox(g2) && J(a.pos) === J([120, 140]));
graph._nodes.push(b);

console.log("── The colour palette");
check("shade: the same hue, darker", M.shade("#cc3333", 0.5) === "#661a1a" && M.shade("bad", 0.5) === "bad");
M.applyColour([a, g], "#3399e5");
check("applyColour: a node gets the colour on its title bar and a darker body, a group the colour itself",
      a.color === "#3399e5" && a.bgcolor === M.shade("#3399e5", 0.45) && g.color === "#3399e5" && g.bgcolor === undefined);
M.applyColour([a, g], null);
check("  none: back to the defaults", a.color === undefined && a.bgcolor === undefined && g.color === undefined);
M.applyShape([a, g], "card");
check("applyShape: nodes get the shape (card = 4), groups are left alone", a.shape === 4 && g.shape === undefined);
const key = (code, opts = {}) => {
  const ev = new dom.window.KeyboardEvent("keydown", { code, bubbles: true, cancelable: true, ...opts });
  (opts.target || document.body).dispatchEvent(ev);
  return ev;
};
canvas.selected_nodes = {};
let ev = key("KeyC");
check("C with nothing selected: no palette, the key is not taken", !document.querySelector(".pcg-palette") && !ev.defaultPrevented);
canvas.selected_nodes = { 1: a, 2: b };
const inp = document.createElement("input");
document.body.appendChild(inp);
ev = key("KeyC", { target: inp });
check("  C while typing in a field: no palette", !document.querySelector(".pcg-palette") && !ev.defaultPrevented);
ev = key("KeyC", { ctrlKey: true });
check("  Ctrl+C (copy) is not taken", !document.querySelector(".pcg-palette") && !ev.defaultPrevented);
ev = key("KeyC");
const pop = document.querySelector(".pcg-palette");
check("C with nodes selected: the palette opens (twenty swatches, none, three shapes)",
      pop && ev.defaultPrevented && pop.querySelectorAll(".sw").length === 20 && pop.querySelector(".none")
      && pop.querySelector(".shape-round"));
pop.querySelector('.sw[data-colour="#e5732e"]').dispatchEvent(new dom.window.Event("click"));
check("  a swatch colours both selected nodes and closes the palette",
      a.color === "#e5732e" && b.color === "#e5732e" && !document.querySelector(".pcg-palette"));
key("KeyC");
document.querySelector(".pcg-palette .shape-round").dispatchEvent(new dom.window.Event("click"));
check("  a shape: both selected nodes get it", a.shape === 2 && b.shape === 2 && c.shape === undefined);
key("KeyC");
key("Escape");
check("  Esc closes it", !document.querySelector(".pcg-palette"));
const items = ext.getNodeMenuItems(out);
check("the node menu has PCG: Colour Palette…", items.some((o) => o?.content === "PCG: Colour Palette…"));

const pass = OK.filter(Boolean).length;
console.log(`\n${pass}/${OK.length} passed`);
process.exit(pass === OK.length ? 0 : 1);
