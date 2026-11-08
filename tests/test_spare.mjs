// Frontend tests for custom parameters on any node (pcg_spare.js, pcg104). jsdom + a stubbed app; the module really runs.
//
// The kinds of things that **fail silently**:
//   1) native widget indices shift (a workflow stores values by index; shift one and everything after is misaligned): custom-parameter widgets
//      must always be last and not serialized; adding/removing/changing them never touches the ones before
//   2) values get lost: stored by name in properties; a rename must move them, a type change falls back to the default, loading a workflow must reconnect them
//   3) the backend can't read them: nodes with ch_params must have them written in on every value change (vectors also once per component)
//   4) references break: on rename, other nodes / its own expressions / pasted references / bindings attached to it must all follow
//   5) typing in a Wrangle: ch("a") ch("am") ch("amp") grows a pile of useless parameters along the way
import { JSDOM, VirtualConsole } from "jsdom";
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
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "jstest_spare_"));
process.on("exit", () => fs.rmSync(ROOT, { recursive: true, force: true }));
const EXT = path.join(ROOT, "extensions", "comfyui_pcg");
fs.mkdirSync(path.join(ROOT, "scripts"), { recursive: true });
fs.mkdirSync(EXT, { recursive: true });
fs.writeFileSync(path.join(ROOT, "scripts", "app.js"), "export const app = globalThis.__app;\n");
fs.writeFileSync(path.join(ROOT, "scripts", "api.js"), "export const api = { addEventListener() {} };\n");
for (const f of fs.readdirSync(path.join(PKG, "comfyui_pcg", "web")))
  if (f.endsWith(".js")) fs.copyFileSync(path.join(PKG, "comfyui_pcg", "web", f), path.join(EXT, f));

const dom = new JSDOM("<!doctype html><html><head></head><body></body></html>",
                      { url: "http://localhost/", pretendToBeVisual: true, virtualConsole: new VirtualConsole() });
for (const k of ["window", "document", "HTMLElement", "Node", "Event", "KeyboardEvent", "MouseEvent"])
  Object.defineProperty(globalThis, k, { value: k === "window" ? dom.window : dom.window[k],
                                         writable: true, configurable: true });
globalThis.requestAnimationFrame = () => 0;

const OK = [];
function check(name, cond, extra = "") {
  OK.push(!!cond);
  console.log((cond ? "  PASS  " : "  FAIL  ") + name + (extra === "" ? "" : "   " + extra));
}
const sec = (t) => console.log(`\n── ${t}`);
const J = (x) => JSON.stringify(x);

let nextId = 1;
function mkNode(type, widgets = [], nodeData = null) {
  const n = {
    type, id: nextId++, title: null, pos: [0, 0], size: [200, 100], flags: {}, properties: {},
    widgets: [], inputs: [], dirty: 0, constructor: { nodeData },
    addWidget(kind, name, value, callback, options) {
      const w = { type: kind, name, value, callback, options: options || {} };
      this.widgets.push(w);
      return w;
    },
    computeSize() { return [210, 40 + this.widgets.length * 20]; },
    setSize(s) { this.size = s; },
    setDirtyCanvas() { this.dirty++; },
  };
  for (const w of widgets) n.addWidget(w.type || "number", w.name, w.value);
  G._nodes.push(n);
  return n;
}
const G = { _nodes: [], changes: [], beforeChange() { this.changes.push("b"); }, afterChange() { this.changes.push("a"); },
            getNodeById(id) { return this._nodes.find((n) => String(n.id) === String(id)) ?? null; } };
const exts = [];
globalThis.__app = { graph: G, canvas: { setDirty() {} }, registerExtension(e) { exts.push(e); },
                     ui: { settings: { getSettingValue: () => undefined } } };

const P = await import(path.join(EXT, "pcg_params.js"));
const U = await import(path.join(EXT, "pcg_paramui.js"));
const S = await import(path.join(EXT, "pcg_spare.js"));
const PN = await import(path.join(EXT, "pcg_panel.js"));
const W = (n, name) => n.widgets.find((w) => w.name === name);
const setW = (n, name, v) => { const w = W(n, name); w.value = v; w.callback?.(v); };

// ═══════════════════════════════════════════════ 1. growing widgets
sec("declaration -> widgets: appended only at the end, not serialized, values stored by name");
const box = mkNode("PCG_Box", [{ name: "size_x", value: 1 }, { name: "cx", value: 0 }, { type: "combo", name: "prim_type", value: "polygon" }]);
box.title = "box1";
const nat = box.widgets.slice();
box.properties.pcg_spare = "float amp = 0.5 : 0 2  # Amplitude\nint count = 3\nvector pos = 1 2 3\nbool on = true\nstring tag = hi\n";
const ch1 = S.syncSpare(box);
check("grows seven widgets amp count posx posy posz on tag, after the native ones",
      ch1 && J(box.widgets.map((w) => w.name)) === J(["size_x", "cx", "prim_type", "amp", "count", "posx", "posy", "posz", "on", "tag"]));
check("  native widgets are still the same objects at the same indices", nat.every((w, i) => box.widgets[i] === w));
check("  custom ones are never serialized (serialize and options.serialize are both false)",
      box.widgets.slice(3).every((w) => w.serialize === false && w.options.serialize === false));
check("  value = default; correct types: number / toggle / text; range on options; label from the declaration",
      W(box, "amp").value === 0.5 && W(box, "posy").value === 2 && W(box, "on").type === "toggle"
      && W(box, "tag").value === "hi" && W(box, "amp").options.min === 0 && W(box, "amp").options.max === 2
      && W(box, "amp").label === "Amplitude" && W(box, "count").options.precision === 0);
setW(box, "amp", 1.25); setW(box, "posy", 7); setW(box, "tag", "yo"); setW(box, "count", 4.6);
check("moving a widget: value stored by name in properties (vectors as a whole, integers rounded)",
      J(box.properties.pcg_spare_vals) === J({ amp: 1.25, count: 5, pos: [1, 7, 3], on: true, tag: "yo" }),
      J(box.properties.pcg_spare_vals));
check("  spareValues reads back the same", J(S.spareValues(box)) === J(box.properties.pcg_spare_vals));
check("node without ch_params: nothing to write for the backend (pushChStore returns false)", !S.pushChStore(box));
// change the declaration: remove one, add one, change a type
box.properties.pcg_spare = "float amp = 0.5 : 0 1\nvector pos = 1 2 3\nint on = 2\nfloat extra = 9\n";
S.syncSpare(box);
check("changed declaration: count / tag widgets removed, on rebuilt with the new type, extra appended last; native ones untouched",
      J(box.widgets.map((w) => w.name)) === J(["size_x", "cx", "prim_type", "amp", "posx", "posy", "posz", "on", "extra"])
      && nat.every((w, i) => box.widgets[i] === w) && W(box, "on").type === "number");
check("  existing widget ranges follow the declaration (amp 0..2 -> 0..1)", W(box, "amp").options.max === 1 && W(box, "amp").options.min === 0);
check("  values: amp clamped to 1 by the new range, pos kept, on (type changed) falls back to default 2, removed ones no longer stored",
      J(box.properties.pcg_spare_vals) === J({ amp: 1, pos: [1, 7, 3], on: 2, extra: 9 }), J(box.properties.pcg_spare_vals));
// malformed / name clash
box.properties.pcg_spare = "float amp = 0.5\nflot bad\n";
const before = box.widgets.map((w) => w.name);
S.syncSpare(box);
check("malformed declaration: error (with line number), no widget touched", box._pcgSpareErr.includes("line 2")
      && J(box.widgets.map((w) => w.name)) === J(before));
box.properties.pcg_spare = "float amp = 0.5\nfloat cx = 1\nvector size_ = 0\n";
S.syncSpare(box);
check("clashes with the node's own parameters (cx; component size_x of vector size_): reported, those two not grown, the rest as usual",
      box._pcgSpareErr.includes("cx") && box._pcgSpareErr.includes("size_")
      && J(box.widgets.map((w) => w.name)) === J(["size_x", "cx", "prim_type", "amp"]), box._pcgSpareErr);

// ═══════════════════════════════════════════════ 2. references / expressions / keyframes
sec("same as the node's own parameters: referenced, referencing its own, carrying expressions and keyframes");
const wave = mkNode("PCG_Transform", [{ name: "tx", value: 0 }, { name: "ty", value: 0 }]);
wave.title = "wave1";
wave.properties.pcg_spare = "float amp = 2\nvector off = 0 0 0\n";
S.syncSpare(wave);
const tgt = mkNode("PCG_Sphere", [{ name: "radius", value: 1 }, { name: "rows", value: 0 }]);
tgt.title = "ball";
let r = P.bindExpr(tgt, "radius", 'ch("../wave1/amp") * 3', G);
check("other node ch(\"../wave1/amp\") * 3 -> 6; the stored path becomes @id", r.ok && W(tgt, "radius").value === 6
      && P.bindings(tgt).radius === `=ch("@${wave.id}/amp") * 3`, J(r) + P.bindings(tgt).radius);
r = P.bindExpr(wave, "tx", 'ch("amp") + ch("offy")', G);
setW(wave, "offy", 0.5);
P.applyBindings(G);
check("own parameters ch(\"amp\") + ch(\"offy\") (vector by component name) -> 2.5", r.ok && W(wave, "tx").value === 2.5, W(wave, "tx").value);
r = P.bindExpr(wave, "amp", "1 + 4", G);
check("custom parameter carrying its own expression: materialized into the widget and stored in properties", r.ok && W(wave, "amp").value === 5
      && wave.properties.pcg_spare_vals.amp === 5);
P.applyBindings(G);
check("  downstream follows (ball.radius = 15, wave1.tx = 5.5)", W(tgt, "radius").value === 15 && W(wave, "tx").value === 5.5);
P.unbind(wave, "amp");
P.setKey(G, wave, "offx", 0, 4);
check("keyframe on a custom parameter: value goes into the widget and properties", W(wave, "offx").value === 4
      && J(wave.properties.pcg_spare_vals.off) === J([4, 0.5, 0]));
P.bindings(tgt).rows = `@${wave.id}/offy`;              // a pasted relative reference
const other = mkNode("PCG_Grid", [{ name: "size_x", value: 0 }]);
P.bindings(other) || (other.properties.pcg_bind = {});
other.properties.pcg_bind.size_x = '=ch("../wave1/amp") + 1';  // non-normalized path (e.g. duplicate titles when it was written)
P.applyBindings(G);
check("pasted relative reference @id/offy: rows <- 0.5 rounded... rows is a number, so just 0.5", W(tgt, "rows").value === 0.5);

// ═══════════════════════════════════════════════ 3. renames don't break references
sec("rename in the dialog: references, bindings and values follow");
const use = S.spareUsage(G, wave);
check("usage: amp used by ball.radius, wave1.tx, grid's ../wave1/amp (3 places), off used by wave1.tx and ball.rows (2 places)",
      use.get("amp") === 3 && use.get("off") === 2, J([...use]));
const items = U.parseItems(S.spareText(wave));
items[0].name = "gain"; items[1].name = "shift";
P.bindExpr(wave, "gain" in {} ? "x" : "ty", "0", G);    // an unrelated binding that must not be touched
const rr = S.applySpare(G, wave, items);
check("rename amp -> gain, off -> shift: 4 bindings changed (ball.radius, two places in wave1.tx, ball.rows, grid)", rr.renamed === 4, J(rr));
check("  non-normalized ch(\"../wave1/amp\") also becomes ../wave1/gain", other.properties.pcg_bind.size_x === '=ch("../wave1/gain") + 1');
check("  ball.radius expression: ch(\"@id/gain\") * 3", P.bindings(tgt).radius === `=ch("@${wave.id}/gain") * 3`);
check("  wave1.tx's own expression: ch(\"gain\") + ch(\"shifty\")", P.bindings(wave).tx === '=ch("gain") + ch("shifty")',
      P.bindings(wave).tx);
check("  ball.rows pasted reference: @id/shifty", P.bindings(tgt).rows === `@${wave.id}/shifty`);
check("  keyframes on offx move to shiftx", P.bindings(wave).shiftx?.startsWith("k:") && !("offx" in P.bindings(wave)));
check("  values moved (gain = 5, shift = [4, .5, 0]), widgets renamed", J(S.spareValues(wave)) === J({ gain: 5, shift: [4, 0.5, 0] })
      && W(wave, "gain") && W(wave, "shiftz") && !W(wave, "amp"));
P.applyBindings(G);
check("  still evaluates after the rename (ball.radius = 15, wave1.tx = 5.5)", W(tgt, "radius").value === 15 && W(wave, "tx").value === 5.5,
      `${W(tgt, "radius").value} ${W(wave, "tx").value}`);
check("  wrapped in a single undo", G.changes.slice(-2).join() === "b,a");
const tg = S.spareTarget(wave, G);
const it2 = U.parseItems("float tx = 1\nvector q = 0\nfloat qx = 0\n");
const ce = tg.check(it2);
check("dialog validation: clash with the node's own parameter (tx), vector component clash (qx from q and qx)", ce[0]?.includes("tx") && ce[2]?.includes("qx"), J(ce));
check("  reference path in the hint: ../wave1/name (vectors give the x component)", tg.refPath({ name: "shift", def: ["0", "0", "0"] }) === "../wave1/shiftx");
// go through the real dialog once
const dlg = S.openSpareDialog(wave, G);
dlg.add("float");
const nm = dlg.descEl.querySelector("input");
nm.value = "speed"; nm.dispatchEvent(new window.Event("input"));
dlg.btnAccept.onclick();
check("dialog: add a Float, rename it speed -> Accept -> a speed widget grows, title says custom parameters",
      !!W(wave, "speed") && S.spareText(wave).includes("float speed = 0") && !document.querySelector(".pcg-epi-mask"),
      S.spareText(wave));

// ═══════════════════════════════════════════════ 4. ch() in a Wrangle
sec("Wrangle: ch() in the code grows parameters automatically, values written into ch_params");
check("scanCh: type from the function (ch / chf -> float, chi -> int, chv -> vector, chs -> string), second argument is the default",
      J(S.scanCh('f@a = ch("amp", 0.5) + chi("n") ; v@c = chv("col"); s@s = chs("s"); x = chf("amp")'))
      === J([{ name: "amp", type: "float", def: 0.5 }, { name: "n", type: "int", def: 0 },
             { name: "col", type: "vector", def: 0 }, { name: "s", type: "string", def: 0 }]));
const wr = mkNode("PCG_Wrangle", [{ type: "text", name: "code", value: '@P.y += ch("amp", 0.5) * chv("dir").y' },
                                  { type: "text", name: "ch_params", value: '{"amp": 0.8}' }]);
S.syncFromCode(wr); S.syncSpare(wr);
check("old workflow (ch_params holds amp = 0.8): amp picks up the old value (the default is still the 0.5 in the code), dir is a vector",
      W(wr, "amp").value === 0.8 && S.spareText(wr).includes("float amp = 0.5")
      && W(wr, "dirx") && W(wr, "diry"), J(wr.widgets.map((w) => w.name)));
check("  in ch_params: one entry per parameter, vectors also once per component (ch(\"diry\") works too)",
      J(JSON.parse(W(wr, "ch_params").value)) === J({ amp: 0.8, dir: [0, 0, 0], dirx: 0, diry: 0, dirz: 0 }),
      W(wr, "ch_params").value);
setW(wr, "diry", 2);
check("  move diry: ch_params updates", JSON.parse(W(wr, "ch_params").value).diry === 2
      && J(JSON.parse(W(wr, "ch_params").value).dir) === J([0, 2, 0]));
// while typing: ch("f") -> ch("fr") -> ch("freq")
const code = W(wr, "code");
for (const c of ['ch("f")', 'ch("fr")', 'ch("freq")']) {
  code.value = `@P.y += ch("amp", 0.5) * chv("dir").y + ${c}`;
  if (S.syncFromCode(wr)) S.syncSpare(wr);
}
check("ch(\"f\") ch(\"fr\") appearing while typing: removed automatically when the value was never changed, only freq stays", W(wr, "freq") && !W(wr, "f") && !W(wr, "fr"),
      J(wr.widgets.map((w) => w.name)));
setW(wr, "freq", 3);
code.value = '@P.y += ch("amp", 0.5) * chv("dir").y';
if (S.syncFromCode(wr)) S.syncSpare(wr);
check("  freq with a changed value: stays even after ch(\"freq\") is removed from the code (it's yours now)", W(wr, "freq")?.value === 3);
check("  context menu \"remove unused\": lists freq, gone once removed", J(S.unusedInCode(wr)) === J(["freq"])
      && (S.removeSpare(wr, ["freq"]), !W(wr, "freq")));
code.value += ' + ch("dirx")';
check("  ch(\"dirx\") is a component of an existing vector: no extra parameter", !S.syncFromCode(wr) && !W(wr, "dirx_"));
// grown automatically but with something bound: not removed even if the value is still the default
code.value += ' + ch("g")';
if (S.syncFromCode(wr)) S.syncSpare(wr);
P.bindExpr(wr, "g", "0", G);
code.value = code.value.replace(' + ch("g")', "");
if (S.syncFromCode(wr)) S.syncSpare(wr);
check("  auto-grown g carries an expression (value still 0 = default): stays after being removed from the code", !!W(wr, "g"));
// Apply clicked in the dialog: the auto-remove list is cleared
code.value += ' + ch("h")';
if (S.syncFromCode(wr)) S.syncSpare(wr);
S.applySpare(G, wr, U.parseItems(S.spareText(wr)));
code.value = code.value.replace(' + ch("h")', "");
if (S.syncFromCode(wr)) S.syncSpare(wr);
check("  Apply clicked in the dialog: h is yours now, stays after being removed from the code", !!W(wr, "h"));

// ═══════════════════════════════════════════════ 5. panel
sec("Houdini panel: custom parameters come last (Spare section; a Spare tab if the node has tabs)");
const ndBox = { name: "PCG_Box", input: { required: {
  size_x: ["FLOAT", { default: 1, pcg_ui: { label: "Size X", _node: { order: ["size_x", "cx"] } } }],
  cx: ["FLOAT", { default: 0, pcg_ui: { label: "Cx" } }] } } };
const pb = mkNode("PCG_Box", [{ name: "size_x", value: 1 }, { name: "cx", value: 0 }], ndBox);
pb.properties.pcg_spare = "float amp = 1 : 0 2\nvector pos = 0\n";
S.syncSpare(pb);
const nd2 = PN.withSpare(ndBox, pb);
const m = PN.buildModel(nd2, pb.widgets.map((w) => w.name));
check("withSpare: layout info merged into nodeData; the original nodeData is not modified", !!nd2.input.optional.amp && !ndBox.input.optional);
check("  buildModel: the last block is the Spare section (amp, pos on one row), after the native parameters",
      m.top.length === 2 && m.top[1].section === "Spare" && J(m.top[1].items) === J(["amp", "posx"])
      && nd2.input.optional.posx[1].pcg_ui.row.members.join() === "posx,posy,posz"
      && nd2.input.optional.posy[1].pcg_ui.in_row === "posx", J(m.top));
check("  range -> panel min / max; eligible accepts them (not foreign widgets)",
      nd2.input.optional.amp[1].min === 0 && nd2.input.optional.amp[1].max === 2 && PN.eligible(pb, nd2)
      && !PN.eligible(pb, ndBox));
const ndTab = { name: "X", input: { required: { a: ["FLOAT", { pcg_ui: { label: "A", folder: "Main" } }] } } };
const pt = mkNode("X", [{ name: "a", value: 0 }], ndTab);
pt.properties.pcg_spare = "float k = 1\n";
S.syncSpare(pt);
const mt = PN.buildModel(PN.withSpare(ndTab, pt), ["a", "k"]);
check("  node has tabs: custom parameters are the last tab, Spare", mt.tabs.map((t) => t.name).join() === "Main,Spare");
pb.addDOMWidget = function (name, type, el, opts) {
  const w = { name, type, element: el, options: opts || {} };
  this.widgets.push(w);
  return w;
};
const pnl = PN.activate(pb, ndBox);
check("  activate: panel really built, custom parameters have controls (amp, posx), native widgets hidden",
      !!pnl && pnl.controls.some((c) => c.name === "amp") && pnl.controls.some((c) => c.name === "posx"),
      pnl ? J(pnl.controls.map((c) => c.name)) : "null");
PN.deactivate(pb);
let rebuilt = 0;
pb._pcgPanelRebuild = () => rebuilt++;
pb.properties.pcg_spare += "int n = 1\n";
S.syncSpare(pb);
S.syncSpare(pb);
check("panel rebuilt when parameters are added/removed (only on structure changes, not on value changes)", rebuilt === 1);

// ═══════════════════════════════════════════════ 6. saved workflow / paste
sec("load a saved workflow / copy-paste: properties travel along, widgets regrow and values reconnect");
const saved = JSON.parse(JSON.stringify(box.properties));
const box2 = mkNode("PCG_Box", [{ name: "size_x", value: 1 }, { name: "cx", value: 0 }, { type: "combo", name: "prim_type", value: "polygon" }]);
const ext = exts.find((e) => e.name === "pcg.spare");
const proto = {};
ext.beforeRegisterNodeDef({ prototype: proto }, { name: "PCG_Box" });
box2.properties = saved;
proto.onConfigure.call(box2, {});
check("onConfigure: same widgets with the same values regrown from properties", J(box2.widgets.map((w) => [w.name, w.value]))
      === J(box.widgets.map((w) => [w.name, w.value])));
const opts = [];
proto.getExtraMenuOptions.call(box2, null, opts);
check("first context menu item is \"Edit Parameter Interface\"; nodes without ch_params have no \"remove unused\"",
      opts[0].content.includes("Edit Parameter Interface") && !opts.some((o) => o?.content?.includes("ch()")));
const opts2 = [];
proto.getExtraMenuOptions.call(wr, null, opts2);
check("  Wrangle has \"remove ch() parameters unused in the code\", listing the unused g, h",
      opts2.some((o) => o?.content?.includes("ch()") && o.content.includes("g, h") && !o.disabled));
S.removeSpare(wr, ["g", "h"]);
const opts3 = [];
proto.getExtraMenuOptions.call(wr, null, opts3);
check("  all used: the item is greyed out", opts3.some((o) => o?.content?.includes("ch()") && o.disabled));
const pp = {};
ext.beforeRegisterNodeDef({ prototype: pp }, { name: "PCG_Parameters" });
check("Parameters (PCG) is not hooked (its parameters are declared anyway and have their own dialog)", !pp.onConfigure);

console.log(`\n${OK.filter(Boolean).length}/${OK.length} passed`);
process.exit(OK.every(Boolean) ? 0 : 1);
