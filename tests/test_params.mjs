// Parameter panel + parameter references. jsdom + stubbed app / litegraph, actually running the module.
//
// Four kinds of things that **fail silently**:
//
//  1) **The two parse implementations drift.** The panel grows controls from the declaration in the frontend, so parse() has
//     a Python and a JS version. Drift shows up as: the declaration looks fine, yet the panel has one extra parameter or
//     a slightly different default, with no error at all. So this suite and test_params.py **check against the same
//     golden table** (params_golden.json) -- change either side and that side goes red.
//
//  2) **Widgets inserted in the wrong place.** When litegraph restores a workflow it maps widgets_values back onto the
//     widget array by index. Parameter widgets must only be appended at the end, and be serialize:false,
//     otherwise the declare / values values shift as a whole and silently get mixed up.
//
//  3) **Invalidation becomes coarse-grained.** The whole point of references is "changing radius recooks only the nodes that reference
//     radius". Blindly rewriting every binding each tick would "write" every node's widgets
//     once -- the values are the same, but every callback gets called, and the day someone puts a side effect
//     in a callback it becomes "while the panel is open the whole graph twitches every 0.4 s". Criterion: change one parameter,
//     and the widgets that don't reference it must stay **bit-for-bit unchanged**, with not a single callback call.
//
//  4) **Wrong types stuffed in.** An INT widget receiving 3.7 makes the backend raise a type error, and the error shows up
//     on that node, miles away from "I changed the parameter panel".
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
// A **fresh** temp directory per run (pcg64): it used to be hard-coded "/tmp/jstest_params"; when two regression runs ran in parallel
// one side rmSync'ed files the other side was importing, which is how test_camlink once broke; also
// test_icons / test_playbar used the same directory. Deleted after the run
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "jstest_params_"));
process.on("exit", () => fs.rmSync(ROOT, { recursive: true, force: true }));
const EXT = path.join(ROOT, "extensions", "comfyui_pcg");
fs.mkdirSync(path.join(ROOT, "scripts"), { recursive: true });
fs.mkdirSync(EXT, { recursive: true });
fs.writeFileSync(path.join(ROOT, "scripts", "app.js"),
                 "export const app = globalThis.__app;\n");
fs.writeFileSync(path.join(ROOT, "scripts", "api.js"),
                 "export const api = globalThis.__api;\n");
for (const f of ["pcg_params.js", "pcg_hexpr.js", "pcg_chan.js"])
  fs.copyFileSync(path.join(PKG, "comfyui_pcg", "web", f), path.join(EXT, f));

const dom = new JSDOM("<!doctype html><html><body></body></html>",
                      { url: "http://localhost/" });
for (const k of ["window", "document", "HTMLElement", "Node"]) {
  Object.defineProperty(globalThis, k, {
    value: k === "window" ? dom.window : dom.window[k],
    writable: true, configurable: true,
  });
}

const OK = [];
function check(name, cond, extra = "") {
  OK.push(!!cond);
  const tail = extra === "" ? "" : "   " + extra;
  console.log((cond ? "  PASS  " : "  FAIL  ") + name + tail);
}
function thrown(name, fn, frag) {
  try { fn(); check(name, false, "no error raised"); }
  catch (e) {
    check(name, frag ? String(e.message).includes(frag) : true,
          String(e.message).slice(0, 90));
  }
}
function sec(t) { console.log("\n" + "═".repeat(28) + " " + t); }

// ── Fake litegraph nodes ────────────────────────────────────────────────
let nextId = 1;
function mkNode(type, widgets = [], nodeData = null) {
  const n = {
    type, id: nextId++, title: null, pos: [0, 0], size: [200, 100],
    flags: {}, properties: {}, widgets: [], inputs: [],
    constructor: { nodeData },
    addWidget(kind, name, value, callback, options) {
      const w = { type: kind, name, value, callback, options: options || {},
                  calls: 0 };
      const cb = w.callback;
      w.callback = (...a) => { w.calls++; return cb?.(...a); };
      this.widgets.push(w);
      return w;
    },
    computeSize() { return [210, 40 + this.widgets.length * 20]; },
    setSize(s) { this.size = s; },
  };
  for (const w of widgets)
    n.addWidget(w.type || "number", w.name, w.value, w.callback, w.options);
  for (const w of n.widgets) w.calls = 0;
  return n;
}
const GRAPH = { _nodes: [] };
function add(n) { GRAPH._nodes.push(n); return n; }

globalThis.__app = {
  graph: GRAPH, canvas: { setDirty() {} }, exts: [],
  registerExtension(e) { this.exts.push(e); },
};

const M = await import(path.join(EXT, "pcg_params.js"));
check("pcg.params extension registered",
      globalThis.__app.exts[0]?.name === "pcg.params");

// Panel node: two real widgets, matching the backend INPUT_TYPES
function mkPanel(decl = "") {
  const p = mkNode("PCG_Parameters", [
    { type: "text", name: "declare", value: decl },
    { type: "text", name: "values", value: "{}" },
  ]);
  return add(p);
}


// ═══════════════════════════════════════════ 1. Golden reference (cross-language)
sec("Golden table (the Python implementation checks against the same table)");
const GPATH = [path.join(_HERE, "params_golden.json"),
               path.join(PKG, "params_golden.json")].find((p) =>
                 fs.existsSync(p));
check("golden table exists", !!GPATH, GPATH);
const gold = JSON.parse(fs.readFileSync(GPATH, "utf-8"));

const mismatch = [];
for (const c of gold.ok) {
  const got = M.parse(c.src);
  if (JSON.stringify(got) !== JSON.stringify(c.specs))
    mismatch.push([c.src, JSON.stringify(got), JSON.stringify(c.specs)]);
}
check(`${gold.ok.length} valid declarations parse **exactly** like the golden reference`,
      !mismatch.length, mismatch[0]);

const shouldThrow = [];
for (const src of gold.bad) {
  let threw = false;
  try { M.parse(src); } catch (_) { threw = true; }
  if (!threw) shouldThrow.push(src);
}
check(`${gold.bad.length} invalid declarations **all** throw`,
      !shouldThrow.length, shouldThrow);


// ══════════════════════════════════════════════════ 2. Panel sync
sec("Panel: grows widgets from the declaration");
const panel = mkPanel("float radius = 1.0 : 0 10 # radius\nint count = 5\n");
M.syncPanel(panel);
const extra = panel.widgets.slice(2);
check("declare / values are still the first two, indices unchanged",
      panel.widgets[0].name === "declare"
      && panel.widgets[1].name === "values");
check("parameter widgets are **appended at the end**", extra.length === 2);
check("  all serialize:false (not in widgets_values)",
      extra.every((w) => w.options.serialize === false));
check("  names are prefixed, avoiding declare / values",
      extra.every((w) => w.name.startsWith("p_")));
check("  the display uses the label (when there is a # label)",
      extra[0].label === "radius" && extra[1].label === "count");
check("  float gets the range, int precision is 0",
      extra[0].options.min === 0 && extra[0].options.max === 10
      && extra[1].options.precision === 0);
check("values are written into the values string",
      JSON.parse(panel.widgets[1].value).radius === 1.0);
check("valuesOf reads the current values",
      M.valuesOf(panel).radius === 1.0 && M.valuesOf(panel).count === 5);

// change a value -> stored into values; syncing again does not overwrite it with the default
extra[0].callback(7.5);
check("dragging a control writes the value into the values string",
      JSON.parse(panel.widgets[1].value).radius === 7.5);
M.syncPanel(panel);
check("  value survives another sync (not overwritten with the default)",
      M.valuesOf(panel).radius === 7.5);

// add a parameter: existing values untouched
panel.widgets[0].value += "vector pos = 1 2 3\n";
M.syncPanel(panel);
check("existing parameter values are kept when a parameter is added", M.valuesOf(panel).radius === 7.5);
check("vector expands into 3 component widgets",
      panel.widgets.filter((w) => w.name.startsWith("p_pos.")).length === 3);
check("  component labels are .x/.y/.z",
      panel.widgets.find((w) => w.name === "p_pos.y").label === "pos.y");
check("  component values match",
      JSON.stringify(M.valuesOf(panel).pos) === "[1,2,3]");
panel.widgets.find((w) => w.name === "p_pos.y").callback(9);
check("  changing one component touches only that one",
      JSON.stringify(M.valuesOf(panel).pos) === "[1,9,3]");

// delete a parameter: the tail widget is removed, and the value cleared too
panel.widgets[0].value = "float radius = 1.0 : 0 10\n";
M.syncPanel(panel);
check("deleted parameter's widget is removed", panel.widgets.length === 3);
check("  its value is also cleared from the saved values (no stale value after a rename)",
      !("pos" in M.valuesOf(panel)) && !("count" in M.valuesOf(panel)));
check("  declare / values are still first",
      panel.widgets[0].name === "declare"
      && panel.widgets[1].name === "values");

const bad = mkPanel("float a\nthis is wrong\n");
M.syncPanel(bad);
check("malformed declaration does not throw, the error is recorded on the node (drawn on the node body)",
      typeof bad._pcgErr === "string" && bad._pcgErr.includes("line 2"),
      bad._pcgErr);
check("  a malformed declaration does not touch existing widgets (does not empty the panel)",
      bad.widgets.length === 2);
bad.widgets[0].value = "float a = 3\n";
M.syncPanel(bad);
check("  once fixed the error clears and the controls grow",
      bad._pcgErr === "" && bad.widgets.length === 3);
GRAPH._nodes = GRAPH._nodes.filter((n) => n !== bad);


// ══════════════════════════════════════════════════ 3. Bindings
sec("Bindings (= Houdini's copy relative reference)");
// The saved values still hold the radius=7.5 tuned by hand in the previous section -- that is **intended** behaviour (changing the declaration should not
// wipe tuned values), but this section has to start from clean defaults, so clear the saved values first
panel.widgets[1].value = "{}";
panel.widgets[0].value = "float radius = 2 : 0 10\nint count = 4 : 0 99\n"
                       + "bool cap = true\nstring nm = piece\n"
                       + "vector pos = 1 2 3\n";
M.syncPanel(panel);
check("after clearing the saved values, back to the declared defaults (changing the declaration keeps values, clearing the store restores defaults)",
      M.valuesOf(panel).radius === 2);

const ND = (req) => ({ input: { required: req } });
const box = add(mkNode("PCG_Box", [
  { name: "size_x", value: 1.0, options: { min: 0, max: 100 } },
  { name: "divisions_x", value: 2, options: { precision: 0 } },
  { type: "toggle", name: "cap", value: false },
  { type: "text", name: "name", value: "" },
], ND({ size_x: ["FLOAT", {}], divisions_x: ["INT", {}],
        cap: ["BOOLEAN", {}], name: ["STRING", {}] })));
const other = add(mkNode("PCG_Sphere", [
  { name: "radius", value: 1.0 },
], ND({ radius: ["FLOAT", {}] })));

check("bind writes into node.properties (not into widgets_values)",
      M.bind(box, "size_x", "radius")
      && M.bindings(box).size_x === "radius"
      && !("pcg_bind" in (box.widgets[0] || {})));
check("  the panel itself does not accept bindings", !M.bind(panel, "declare", "radius"));
check("  nonexistent widgets do not accept bindings", !M.bind(box, "nope", "radius"));

let r = M.applyBindings(GRAPH);
check("applying bindings: the value is written into the target widget", box.widgets[0].value === 2);
check("  widget label shows the reference (otherwise you cannot tell the parameter was taken over), written as ch(...) like in panel fields",
      box.widgets[0].label === `size_x ←ch("../${panel.title || panel.type}/radius")`,
      box.widgets[0].label);
check("  not a single unbound widget was touched", other.widgets[0].value === 1.0);

// ★ fine-grained invalidation
const before = other.widgets[0].value;
const callsBefore = other.widgets[0].calls;
const st = JSON.parse(panel.widgets[1].value);
st.radius = 6;
panel.widgets[1].value = JSON.stringify(st);
r = M.applyBindings(GRAPH);
check("change one parameter: widgets referencing it follow",
      box.widgets[0].value === 6 && r.wrote === 1, r);
check("**widgets not referencing it stay bit-for-bit unchanged** (the whole point of fine-grained invalidation)",
      Object.is(other.widgets[0].value, before));
check("  and their callbacks were never called",
      other.widgets[0].calls === callsBefore);
const calls2 = box.widgets[0].calls;
r = M.applyBindings(GRAPH);
check("**no rewrite** when the value did not change (apply again, writes 0)", r.wrote === 0, r);
check("  bound widgets' callbacks are not called again either",
      box.widgets[0].calls === calls2);

// editing a bound widget by hand -> overwritten at the next sync (same as Houdini)
box.widgets[0].value = 999;
r = M.applyBindings(GRAPH);
check("a bound widget edited by hand is overwritten with the parameter value at the next sync (referencing parameters are not hand-editable)",
      box.widgets[0].value === 6 && r.wrote === 1);

check("after unbinding, the value is no longer taken over, and the label is cleared too",
      M.unbind(box, "size_x") && box.widgets[0].label === undefined
      && (() => { st.radius = 1; panel.widgets[1].value = JSON.stringify(st);
                  M.applyBindings(GRAPH);
                  return box.widgets[0].value === 6; })());
check("  unbinding a nonexistent binding returns false", !M.unbind(box, "size_x"));
check("  after all bindings are deleted, no empty object is left on properties",
      !("pcg_bind" in box.properties));

// component references
M.bind(box, "size_x", "pos.y");
M.applyBindings(GRAPH);
check("can reference a vector component (pos.y)", box.widgets[0].value === 2);
M.bind(box, "size_x", "pos[2]");
M.applyBindings(GRAPH);
check("  square-bracket syntax works too", box.widgets[0].value === 3);

// referencing a nonexistent parameter: marked with a question mark, but the **value is not changed**
const keep = box.widgets[0].value;
M.bind(box, "size_x", "nope");
r = M.applyBindings(GRAPH);
check("referencing a nonexistent parameter: value **unchanged**, label gets a question mark, reported in missing",
      box.widgets[0].value === keep
      && box.widgets[0].label.endsWith("?")
      && r.missing.includes("nope"), r.missing);
M.bind(box, "size_x", "pos.q");
r = M.applyBindings(GRAPH);
check("  same for a wrong component (no clearing, no throw)",
      box.widgets[0].value === keep && r.missing.length === 1);
M.unbind(box, "size_x");


// ══════════════════════════════════════════════════ 4. Types
sec("Putting values into target widgets (types)");
M.bind(box, "divisions_x", "radius");
st.radius = 3.7;
panel.widgets[1].value = JSON.stringify(st);
M.applyBindings(GRAPH);
check("**an INT widget receiving 3.7 rounds it** (otherwise the backend raises a type error)",
      box.widgets[1].value === 4, box.widgets[1].value);
M.bind(box, "cap", "cap");
M.bind(box, "name", "nm");
M.applyBindings(GRAPH);
check("BOOLEAN widget receives a bool", box.widgets[2].value === true);
check("STRING widget receives a string", box.widgets[3].value === "piece");
M.bind(box, "name", "pos");
M.applyBindings(GRAPH);
check("a vector put into STRING is joined into one line, not [object]",
      box.widgets[3].value === "1 2 3", box.widgets[3].value);
M.bind(box, "size_x", "pos");
M.applyBindings(GRAPH);
check("a vector put into a scalar widget takes the first component", box.widgets[0].value === 1);

const w0 = box.widgets[0];
check("clamped into the widget's own min/max (panel range and node range are not necessarily the same)",
      M.coerce(box, w0, 999) === 100 && M.coerce(box, w0, -5) === 0);
const combo = mkNode("PCG_X", [
  { type: "combo", name: "mode", value: "a", options: { values: ["a", "b"] } },
], ND({ mode: [["a", "b"], {}] }));
check("combo box only accepts values in its list",
      M.coerce(combo, combo.widgets[0], "b") === "b"
      && M.coerce(combo, combo.widgets[0], "zzz") === null);
check("  returns null when it does not fit, the caller skips it (the combo never gets an illegal value)",
      (() => { add(combo); M.bind(combo, "mode", "nm");
               M.applyBindings(GRAPH);
               const ok = combo.widgets[0].value === "a";
               GRAPH._nodes = GRAPH._nodes.filter((n) => n !== combo);
               return ok; })());
check("without nodeData, int is guessed from the widget options",
      M.coerce(mkNode("X", []), { name: "q", type: "number",
                                  options: { precision: 0 } }, 2.6) === 3);
check("a non-number put into a numeric widget returns null (no NaN written)",
      M.coerce(box, w0, "abc") === null);
for (const n of ["divisions_x", "cap", "name", "size_x"]) M.unbind(box, n);


// ══════════════════════════════════════════════════ 5. Menu
sec("Context menu");
let items = M.menuFor(box, GRAPH);
const titles = items.map((i) => i.content);
check("target node has 'Bind Parameter'",
      titles.some((t) => t.includes("Bind Parameter")), titles);
check("  and 'Promote to Panel Parameter'",
      titles.some((t) => t.includes("Promote to Panel Parameter")));
const bindItem = items.find((i) => i.content.includes("Bind Parameter"));
const wnames = bindItem.submenu.options.map((o) => o.content);
check("  submenu lists bindable widgets", wnames.includes("size_x"), wnames);
const pnames = bindItem.submenu.options[0].submenu.options
  .map((o) => o.content);
check("  the next level lists all parameter names, vectors with components",
      pnames.includes("radius") && pnames.includes("pos.x"), pnames);
bindItem.submenu.options[0].submenu.options
  .find((o) => o.content === "radius").callback();
// right now radius is 3.7 (set while testing rounding in the previous section), size_x is FLOAT, so no rounding
check("  one click binds it, and materializes immediately",
      M.bindings(box).size_x === "radius" && box.widgets[0].value === 3.7,
      box.widgets[0].value);
items = M.menuFor(box, GRAPH);
check("after binding, 'Unbind' appears in the menu",
      items.some((i) => i.content.includes("Unbind")));
items.find((i) => i.content.includes("Unbind"))
  .submenu.options[0].callback();
check("  one click unbinds", !M.bindings(box));

const pm = M.menuFor(panel, GRAPH);
check("panel node has 'Copy Parameter Reference' (not bind)",
      pm.length === 1 && pm[0].content.includes("Copy Parameter Reference"));
pm[0].submenu.options.find((o) => o.content === "pos.z").callback();
check("  after copying, 'Paste Parameter Reference' appears on the target node",
      M.menuFor(box, GRAPH).some((i) => i.content.includes("Paste Parameter Reference")
                                        && i.content.includes("pos.z")));
M.menuFor(box, GRAPH).find((i) => i.content.includes("Paste Parameter Reference"))
  .submenu.options.find((o) => o.content === "size_x").callback();
check("  pasting onto a widget makes a binding",
      M.bindings(box).size_x === "pos.z");
M.unbind(box, "size_x");

// promote
const before2 = panel.widgets[0].value;
const name = M.promote(box, box.widgets[0], GRAPH);
check("promote: **appends** a declaration line to the panel", panel.widgets[0].value.length
      > before2.length && panel.widgets[0].value.includes(`float ${name}`),
      panel.widgets[0].value.split("\n").pop()
      || panel.widgets[0].value.trim().split("\n").pop());
check("  name taken from the widget name", name === "size_x");
check("  type follows the target widget's declared type", M.valuesOf(panel).size_x !== undefined);
check("  range carried over too (if the node has min/max)",
      panel.widgets[0].value.includes(": 0 100"));
check("  and bound right away", M.bindings(box).size_x === "size_x");
const n2 = M.promote(other, other.widgets[0], GRAPH);
check("duplicate name gets a suffix automatically (does not clobber an existing parameter)",
      n2 !== "radius" && n2.startsWith("radius"), n2);
const n3 = M.promote(box, box.widgets[1], GRAPH);
check("INT widget promotes to an int parameter",
      M.parse(panel.widgets[0].value).find((s) => s.name === n3).type
      === "int");
const n4 = M.promote(box, box.widgets[2], GRAPH);
check("BOOLEAN promotes to bool",
      M.parse(panel.widgets[0].value).find((s) => s.name === n4).type
      === "bool");
const n5 = M.promote(box, box.widgets[3], GRAPH);
check("STRING promotes to string",
      M.parse(panel.widgets[0].value).find((s) => s.name === n5).type
      === "string");


// ══════════════════════════════════════════════════ 6. Multiple panels / robustness
sec("Multiple panels / robustness");
const p2 = mkPanel("float radius = 99\nfloat only_here = 5\n");
M.syncPanel(p2);
const all = M.allValues(GRAPH);
check("parameters of several panels are combined", all.values.only_here === 5);
panel.title = "Params";
p2.title = "Params2";
check("refExpr: panel parameters are written as ch(\"../panel title/name\"), using whichever panel the name was found on",
      M.refExpr(GRAPH, "radius") === 'ch("../Params/radius")'
      && M.refExpr(GRAPH, "only_here") === 'ch("../Params2/only_here")'
      && M.refExpr(GRAPH, "radius.x") === 'ch("../Params/radius.x")',
      [M.refExpr(GRAPH, "radius"), M.refExpr(GRAPH, "only_here")]);
check("  no panel has the name / malformed reference: the name is written as is", M.refExpr(GRAPH, "nope") === 'ch("nope")'
      && M.refExpr(GRAPH, "a.qq") === 'ch("a.qq")');
check("  duplicates take the earliest one in the graph, and the duplicates are reported",
      all.duplicates.includes("radius"), all.duplicates);
GRAPH._nodes = GRAPH._nodes.filter((n) => n !== p2);

check("no panel: applyBindings does not throw, and does not clear values",
      (() => { const saved = GRAPH._nodes;
               GRAPH._nodes = [box];
               const v = box.widgets[0].value;
               const rr = M.applyBindings(GRAPH);
               GRAPH._nodes = saved;
               return box.widgets[0].value === v && rr.wrote === 0; })());
check("a bound widget deleted (node changed version) does not throw",
      (() => { const gone = add(mkNode("PCG_Gone", [], null));
               gone.properties.pcg_bind = { nope: "radius" };
               const rr = M.applyBindings(GRAPH);
               GRAPH._nodes = GRAPH._nodes.filter((n) => n !== gone);
               return typeof rr.wrote === "number"; })());
check("garbage in properties is treated as unbound",
      (() => { const j = add(mkNode("PCG_J", [{ name: "a", value: 1 }]));
               j.properties.pcg_bind = "not an object";
               const ok = M.bindings(j) === null;
               GRAPH._nodes = GRAPH._nodes.filter((n) => n !== j);
               return ok; })());
check("wired widgets are not in the bindable list (the wire drives them)",
      (() => { const k = mkNode("PCG_K", [{ name: "a", value: 1 },
                                          { name: "b", value: 2 }]);
               k.inputs = [{ name: "a", widget: { name: "a" }, link: 3 }];
               const names = M.bindableWidgets(k).map((w) => w.name);
               return names.length === 1 && names[0] === "b"; })());
// In the new frontend (since 1.16) every widget has its own input socket, and unwired ones can still be bound --
// the old "exclude when there is an input" check left the binding menu completely empty on the new frontend
check("  unwired widget sockets (every widget has one in the new frontend) do not prevent binding",
      (() => { const k = mkNode("PCG_K2", [{ name: "a", value: 1 },
                                           { name: "b", value: 2 }]);
               k.inputs = [{ name: "a", widget: { name: "a" }, link: null },
                           { name: "b", widget: { name: "b" } }];
               return M.bindableWidgets(k).length === 2; })());
check("values / declare themselves are not in the bindable list",
      M.bindableWidgets(panel).length === 0);

// saved-workflow round trip: properties travel with the workflow
M.bind(box, "size_x", "radius");
const saved = JSON.parse(JSON.stringify(box.properties));
const revived = mkNode("PCG_Box", [{ name: "size_x", value: 0 }],
                       ND({ size_x: ["FLOAT", {}] }));
revived.properties = saved;
add(revived);
M.applyBindings(GRAPH);
check("bindings are saved into the workflow with properties and work as usual when read back",
      M.bindings(revived).size_x === "radius"
      && revived.widgets[0].value === M.valuesOf(panel).radius);

check("splitRef matches the Python side (x/y/z/w, r/g/b/a, digits, square brackets)",
      M.splitRef("p.x").comp === 0 && M.splitRef("p.a").comp === 3
      && M.splitRef("p.2").comp === 2 && M.splitRef("p[1]").comp === 1
      && M.splitRef("radius").comp === null);
thrown("  throws on a wrong component", () => M.splitRef("p.q"), "unknown");
thrown("  throws on an empty reference", () => M.splitRef("  "), "empty");


// ═══════════════════════════════ 7. Letting a model fill it in (applyValues, cross-language)
//
// This and apply_values() in params.py are **two implementations of the same boundary**; drift still
// shows up silently: the backend tests are all green (they test their own copy), while the frontend misses a range clamp
// or creates an extra parameter. So every boundary is tested on both sides, with the criteria worded the same.
sec("applyValues -- the entire boundary through which AI can touch this graph");
const SPC = M.parse("float radius = 1.0 : 0 10 # radius\nint count = 5\n"
                    + "bool cap = true\nstring pre = piece\n"
                    + "vector pos = 0 1 2\n");
const CUR = Object.fromEntries(SPC.map((s) => [s.name, s.default]));

let [nv, rp] = M.applyValues(SPC, CUR, { radius: 3.5, count: 9 });
check("values filled in", nv.radius === 3.5 && nv.count === 9);
check("  applied is listed",
      JSON.stringify(rp.applied) === '["count","radius"]', rp.applied);
check("parameters not mentioned are left untouched",
      nv.pre === "piece" && JSON.stringify(nv.pos) === "[0,1,2]");

[nv, rp] = M.applyValues(SPC, CUR, { nope: 1, radius: 2 });
check("keys not in the declaration -> unknown",
      JSON.stringify(rp.unknown) === '["nope"]', JSON.stringify(rp));
check("  negative control: **no** extra parameter appeared because of it",
      !("nope" in nv) && Object.keys(nv).length === Object.keys(CUR).length);
[nv, rp] = M.applyValues(SPC, CUR, { radius: "a bit bigger" });
check("unrescuable type -> skipped",
      JSON.stringify(rp.skipped) === '["radius"]', JSON.stringify(rp));
check("  negative control: original value not wiped", nv.radius === 1.0);
[nv, rp] = M.applyValues(SPC, CUR, { radius: "3.5" });
check("numbers written as strings can be rescued", nv.radius === 3.5 && rp.applied.length === 1);
for (const bad of ["inf", "-inf", "nan", "NaN", "Infinity", "", "  "]) {
  [nv, rp] = M.applyValues(SPC, CUR, { radius: bad });
  check(`  but '${bad}' counts as unrescuable (same criterion as the Python side)`,
        rp.skipped.length === 1 && nv.radius === 1.0);
}
[nv, rp] = M.applyValues(SPC, CUR, { radius: 999 });
check("out of range -> clamped and recorded in clamped",
      nv.radius === 10 && JSON.stringify(rp.clamped) === '["radius"]');
[nv, rp] = M.applyValues(SPC, CUR, { radius: 10 });
check("  negative control: exactly on the boundary is not clamped", rp.clamped.length === 0);
[nv, rp] = M.applyValues(SPC, CUR, { count: 9.7 });
check("negative control: int rounding is not clamped",
      nv.count === 10 && rp.clamped.length === 0);
[nv, rp] = M.applyValues(M.parse("int n = 5 : 0 100"), { n: 5 }, { n: 9.7 });
check("  rounding a ranged int is not clamped either", nv.n === 10 && rp.clamped.length === 0);
[nv, rp] = M.applyValues(SPC, CUR, { cap: 0 });
check("bool receiving a number", nv.cap === false);
[nv, rp] = M.applyValues(SPC, CUR, { cap: "1" });
check("bool receiving '1'", nv.cap === true);
[nv, rp] = M.applyValues(SPC, CUR, { cap: "yes" });
check("bool receiving 'yes' -> skipped (same as Python, no guessing)",
      rp.skipped.length === 1);
[nv, rp] = M.applyValues(SPC, CUR, { pos: 7 });
check("vector receiving one number -> fills every component", JSON.stringify(nv.pos) === "[7,7,7]");
[nv, rp] = M.applyValues(SPC, CUR, { pos: [1, 2] });
check("wrong vector component count -> skipped", rp.skipped.length === 1);
[nv, rp] = M.applyValues(M.parse("vector v = 0 0 0 : -1 1"),
                         { v: [0, 0, 0] }, { v: [5, 0, -5] });
check("vector components are clamped too (same as Python)",
      JSON.stringify(nv.v) === "[1,0,-1]" && rp.clamped.length === 1);
[nv, rp] = M.applyValues(SPC, CUR, { pre: 5 });
check("string parameter receiving a number -> skipped", rp.skipped.length === 1);
[nv, rp] = M.applyValues(SPC, CUR, { "  radius  ": 4 });
check("whitespace around keys is trimmed", nv.radius === 4);
[nv, rp] = M.applyValues(SPC, CUR,
                         { radius: 99, count: 2, zzz: 1, pre: 5 });
check("all four lists can appear at once",
      JSON.stringify([rp.applied, rp.clamped, rp.unknown, rp.skipped])
      === '[["count","radius"],["radius"],["zzz"],["pre"]]',
      JSON.stringify(rp));
thrown("throws on non-object input", () => M.applyValues(SPC, CUR, [1]), "JSON object");
thrown("  arrays don't work either (models like wrapping one level, but the backend already stripped it)",
       () => M.applyValues(SPC, CUR, [{ radius: 1 }]), "JSON object");


// ═══════════════════════════════ 8. The whole onExecuted loop
//
// This section tests **the whole chain**: backend sends ui -> written into the panel -> existing bindings fan it out across the graph.
// The two most important negative controls:
//   · **no automatic re-queue** -- auto re-run + every run changing parameters = an infinite loop
//   · keys outside the declaration must **not** grow new parameters on the panel (the whole content of "the boundary is structural")
sec("Params from JSON onExecuted loop");
const ext = globalThis.__app.exts[0];
// Stub the queue API: record every call. If it really auto-queued, we would see it here
let queued = 0;
globalThis.__app.queuePrompt = () => { queued++; };
globalThis.__app.graphToPrompt = () => { queued++; return {}; };

const FJ = { prototype: {} };
await ext.beforeRegisterNodeDef(FJ, { name: "PCG_ParamsFromJSON" });
check("PCG_ParamsFromJSON gets onExecuted hooked",
      typeof FJ.prototype.onExecuted === "function");
check("  and onDrawForeground too (the report must be drawn on the node)",
      typeof FJ.prototype.onDrawForeground === "function");

// Put the panel back into a clean known state
panel.widgets[1].value = "{}";
panel.widgets[0].value = "float radius = 2 : 0 10\nint count = 4 : 0 99\n"
                       + "bool cap = true\nstring nm = piece\n"
                       + "vector pos = 1 2 3\n";
M.syncPanel(panel);
M.bind(box, "size_x", "radius");
M.bind(box, "divisions_x", "count");
M.applyBindings(GRAPH);
const beforeName = box.widgets[3].value;   // the unbound one, compared bit-for-bit later

const fj = add(mkNode("PCG_ParamsFromJSON", [
  { type: "text", name: "json_text", value: "{}" },
  { type: "toggle", name: "enabled", value: true },
]));
fj.onExecuted = FJ.prototype.onExecuted;
fj.onDrawForeground = FJ.prototype.onDrawForeground;

queued = 0;
fj.onExecuted({ pcg_params_apply: [{ values: { radius: 7, count: 9 },
                                     parse: "clean" }] });
check("the panel values were changed by the model",
      M.valuesOf(panel).radius === 7 && M.valuesOf(panel).count === 9,
      JSON.stringify(M.valuesOf(panel)));
check("  the panel widgets followed too (not only the saved values)",
      panel.widgets.find((w) => w.name === "p_radius")?.value === 7);
check("**the bindings fanned it out across the graph** -- that closes the loop",
      box.widgets[0].value === 7 && box.widgets[1].value === 9,
      `${box.widgets[0].value} ${box.widgets[1].value}`);
check("negative control: **no** automatic re-queue (auto re-run + changing parameters every run = infinite loop)",
      queued === 0, queued);
check("negative control: unbound widgets stay bit-for-bit unchanged (invalidation is still fine-grained)",
      box.widgets[3].value === beforeName);
check("report is written on the node", /filled 2/.test(fj._pcgReport || ""), fj._pcgReport);
check("  not marked red when everything is fine", fj._pcgBad === false, fj._pcgBad);

fj.onExecuted({ pcg_params_apply: [{ values: { zzz: 1, nm: 5, radius: 999 },
                                     parse: "clean" }] });
check("keys outside the declaration -> report says no such parameter",
      /no such parameter zzz/.test(fj._pcgReport), fj._pcgReport);
check("  wrong types are written out too", /wrong type nm/.test(fj._pcgReport));
check("  clamped ones are written out too", /clamped radius/.test(fj._pcgReport));
check("  marked red when there are problems (otherwise the report might as well not exist)", fj._pcgBad === true);
// This one is an **end-to-end invariant**, and is guaranteed independently by three layers: applyIncoming only picks
// declared names to pass on, applyValues blocks again, and syncPanel also clears keys outside the declaration
// from the saved values. The single-point negative control is in the previous section ("no extra parameter appeared", removing the applyValues
// gate turns it red); this one tests "no matter which layer leaks, it must not appear on the panel"
check("negative control: keys outside the declaration did **not** grow parameters on the panel",
      !("zzz" in M.valuesOf(panel))
      && !panel.widgets.some((w) => w.name === "p_zzz"),
      panel.widgets.map((w) => w.name).join(","));
check("negative control: the wrong type did not wipe the original value", M.valuesOf(panel).nm === "piece");
check("out of range clamped to the upper bound", M.valuesOf(panel).radius === 10);

fj.onExecuted({ pcg_params_apply: [{ values: {}, parse: "clean" }] });
check("empty object -> nothing changes, report says 0",
      M.valuesOf(panel).radius === 10 && /filled 0/.test(fj._pcgReport));
fj.onExecuted({});
check("no payload (another node's onExecuted): no throw, report cleared",
      fj._pcgReport === "");
fj.onExecuted(undefined);
check("  message undefined does not throw either", true);
fj.onExecuted({ pcg_params_apply: [{ values: "not an object" }] });
check("garbage in the payload: the error is written on the node, not thrown",
      /error/.test(fj._pcgReport), fj._pcgReport);

// A panel with a malformed declaration: the whole graph must not fall over because of it
const badp = mkPanel("float ok = 1\nthis is not a declaration\n");
M.syncPanel(badp);
fj.onExecuted({ pcg_params_apply: [{ values: { radius: 3 } }] });
check("a panel with a malformed declaration is skipped, other panels are filled as usual",
      M.valuesOf(panel).radius === 3, JSON.stringify(M.valuesOf(panel)));
GRAPH._nodes = GRAPH._nodes.filter((n) => n !== badp);

// Multi-panel dispatch: duplicates go to the earliest one, which must be the same rule as allValues uses for reading
const p3 = mkPanel("float radius = 0 : 0 100\nfloat late_only = 1\n");
M.syncPanel(p3);
fj.onExecuted({ pcg_params_apply: [{ values: { radius: 5, late_only: 8 } }] });
check("multiple panels: each receives its own declared parameters", M.valuesOf(p3).late_only === 8);
check("  duplicates go to the **earliest in the graph** (same rule as allValues reading)",
      M.valuesOf(panel).radius === 5 && M.valuesOf(p3).radius === 0,
      `${M.valuesOf(panel).radius} / ${M.valuesOf(p3).radius}`);
GRAPH._nodes = GRAPH._nodes.filter((n) => n !== p3);

const saveNodes = GRAPH._nodes;
GRAPH._nodes = [fj];
fj.onExecuted({ pcg_params_apply: [{ values: { radius: 1 } }] });
check("no panel in the graph at all: say so clearly, instead of silently doing nothing",
      /no parameter panel/.test(fj._pcgReport), fj._pcgReport);
check("  and mark red", fj._pcgBad === true);
GRAPH._nodes = saveNodes;

// onDrawForeground really draws
const calls = [];
const ctx = new Proxy({}, {
  get: (_t, k) => {
    if (k === "save" || k === "restore") return () => calls.push(k);
    if (k === "fillText") return (...a) => calls.push(["fillText", ...a]);
    return () => {};
  },
  set: () => true,
});
fj._pcgReport = "filled 2";
fj.onDrawForeground(ctx);
check("onDrawForeground draws the report",
      calls.some((c) => Array.isArray(c) && c[0] === "fillText"));
check("  save/restore are paired (must not carry off the whole canvas state)",
      calls.filter((c) => c === "save").length
      === calls.filter((c) => c === "restore").length);
calls.length = 0;
fj.flags.collapsed = true;
fj.onDrawForeground(ctx);
check("  collapsed nodes are not drawn on (it would draw over others)",
      !calls.some((c) => Array.isArray(c)));
fj.flags.collapsed = false;

check("mergeValues clamps out-of-range old saved values back (matches Python's merge)",
      M.mergeValues(M.parse("float a = 0 : 0 1"), { a: 5 }).a === 1);
check("  type mismatches fall back to the default, no forced conversion",
      M.mergeValues(M.parse("vector v = 1 1 1"), { v: 5 }).v.length === 3);
check("coerceSpec: int rounding",
      M.coerceSpec({ type: "int", n: 1, min: null }, 3.7) === 4);


// ══════════════════════════════════════════════════ 8. Expressions in fields (pcg91)
const J = (x) => JSON.stringify(x);
sec("Expressions in fields: stored as \"=expression\", paths replaced by ids, values computed by the frontend");
{
  const ndX = { input: { required: {
    tx: ["FLOAT", { default: 0 }], ty: ["FLOAT", { default: 0 }], flag: ["BOOLEAN", { default: true }],
    n: ["INT", { default: 1, min: 0, max: 100 }], s: ["STRING", { default: "" }],
    mode: [["a", "b"], {}] } } };
  const G = { _nodes: [], getNodeById(id) { return this._nodes.find((n) => n.id === id) ?? null; } };
  const mk = (title, vals = {}) => {
    const n = mkNode("PCG_X", ["tx", "ty", "n", "s", "mode", "flag"].map((k) => ({
      name: k, value: k in vals ? vals[k] : ndX.input.required[k][1].default ?? "a",
      type: k === "s" ? "text" : k === "mode" ? "combo" : k === "flag" ? "toggle" : "number",
      options: k === "n" ? { min: 0, max: 100 } : {} })), ndX);
    n.title = title;
    G._nodes.push(n);
    return n;
  };
  const A = mk("grid1", { tx: 2, ty: 5, n: 9, s: "hello", mode: "b" });
  const B = mk("sphere1");
  let r = M.bindExpr(B, "tx", 'ch("../grid1/tx") * 2 + 1', G);
  check("ch(\"../grid1/tx\")*2+1: value 5, stored as \"=ch(\"@id/tx\")*2 + 1\" (path replaced by id, the rest verbatim)",
        r.ok && B.widgets[0].value === 5 && M.bindings(B).tx === `=ch("@${A.id}/tx") * 2 + 1`,
        J([r, B.widgets[0].value, M.bindings(B)]));
  check("  displayed with the title again", M.bindingText(G, B, "tx") === 'ch("../grid1/tx") * 2 + 1');
  A.title = "grid_renamed";
  check("  source renamed: display follows, value still computed", M.bindingText(G, B, "tx") === 'ch("../grid_renamed/tx") * 2 + 1'
        && M.evalBinding(G, B, "tx").value === 5);
  A.title = "grid1";
  A.widgets[0].value = 10;
  M.applyBindings(G);
  check("  source changed: catches up after applyBindings (21)", B.widgets[0].value === 21);
  const calls0 = B.widgets[1].calls;
  M.applyBindings(G);
  check("  no write when the value did not change (fine-grained: tx's callback only called on the two changes to 5 and 21, ty's never)",
        B.widgets[1].calls === calls0 && B.widgets[0].calls === 2, J([B.widgets[0].calls, B.widgets[1].calls]));
  // this node's parameters: ch("tx") is not converted to an id
  M.bindExpr(B, "ty", 'ch("tx") / 3', G);
  check("this node's parameter ch(\"tx\"): not converted to an id (when the node is copied, it still refers to its own), value 7",
        M.bindings(B).ty === '=ch("tx") / 3' && B.widgets[1].value === 7, J(M.bindings(B)));
  check("  ./tx is this node too", M.evalStored(G, B, '=ch("./tx")').value === 21);
  check("  checkbox parameters read with ch: on = 1", M.evalStored(G, B, '=ch("../grid1/flag") * 3').value === 3);
  M.copyParams(B, ["n"]);
  M.pasteRefs(B, ["n"], G);                // referencing itself: not pasted
  M.pasteRefs(B, ["flag"], G);
  check("  this node's pasted reference (@self/n) displays as ch(\"n\"), not ../self/n",
        M.bindingText(G, B, "flag") === 'ch("n")', M.bindingText(G, B, "flag"));
  M.unbind(B, "flag");
  // chain: C refs B.ty (B.ty itself is an expression)
  const C = mk("box1");
  M.bindExpr(C, "tx", 'ch("../sphere1/ty") + 1', G);
  check("chain: C.tx ← B.ty (expression) ← B.tx (expression) ← A.tx, resolved all the way in one go (8)", C.widgets[0].value === 8);
  r = M.bindExpr(C, "ty", 'ch("../sphere1/ty") + ch("../sphere1/ty")', G);
  check("  diamond (same upstream referenced twice): not a cycle, computed (14)", r.ok && C.widgets[1].value === 14, J(r));
  M.unbind(C, "ty");
  // cycle
  r = M.bindExpr(A, "ty", 'ch("../box1/tx")', G);
  const r2 = M.bindExpr(A, "tx", 'ch("../box1/tx")', G);
  check("cycle: error, value unchanged", !r2.ok && r2.error.includes("cycle") && A.widgets[0].value === 10, J(r2));
  M.unbind(A, "tx"); M.unbind(A, "ty");
  check("  binding deleted: the error is cleared along with it", !A._pcgBindErr?.tx);
  // duplicate titles
  const D = mk("grid1");
  r = M.bindExpr(C, "ty", 'ch("../grid1/ty")', G);
  check("duplicate titles: error says how many, value unchanged; stored verbatim (heals itself after a rename)",
        !r.ok && r.error.includes("2 nodes are named 'grid1'") && M.bindings(C).ty === '=ch("../grid1/ty")', J(r));
  D.title = "grid2";
  M.applyBindings(G);
  check("  after renaming the other one: heals itself (= grid1.ty)", C.widgets[1].value === A.widgets[1].value
        && !C._pcgBindErr?.ty, J([C.widgets[1].value, A.widgets[1].value]));
  D.title = "grid1";
  // paths that were already known: even with duplicates, follow the original id
  r = M.bindExpr(B, "tx", 'ch("../grid1/tx") * 2 + 2', G);
  check("editing an existing expression (only the second half changed): title now duplicated, path converted by its original id", r.ok
        && M.bindings(B).tx === `=ch("@${A.id}/tx") * 2 + 2` && B.widgets[0].value === 22, J([r, M.bindings(B)]));
  // originally a pasted reference "@id/tx", edited into an expression in the field
  M.bind(C, "n", `@${A.id}/n`);
  r = M.bindExpr(C, "n", 'ch("../grid1/n") + 1', G);
  check("  originally a pasted reference (@id/n), +1 added in the field: path converted by its original id (duplicates don't matter)",
        r.ok && M.bindings(C).n === `=ch("@${A.id}/n") + 1` && C.widgets[2].value === 10, J([r, M.bindings(C)]));
  D.title = "other";
  // ../#id/x syntax
  check("  ones displayed as ../#id/ (source deleted) are recognized back too", M.pathToCanon(G, "../#77/tx") === "@77/tx");
  // various errors
  const e = (txt, frag) => {
    const rr = M.evalStored(G, B, "=" + txt);
    check(`  error: ${txt}`, !rr.ok && rr.error.includes(frag), rr.error);
  };
  e('ch("../nobody/tx")', "no node named 'nobody'");
  e('ch("../grid1/zz")', "has no parameter zz");
  e('ch("/obj/geo1/tx")', "are supported");
  e('ch("../../a/tx")', "unrecognized");
  e('ch("@999/tx")', "node #999 no longer exists");
  e('ch("../grid1/s")', "use chs()");
  e("1 +", "incomplete");
  A.inputs = [{ name: "ty", widget: { name: "ty" }, link: 5 }];
  e('ch("../grid1/ty")', "is wired");
  A.inputs = [];
  // chs: strings, combos
  check("chs reads strings / combos; string concatenation", M.evalStored(G, B, '=chs("../grid1/s") + "_" + chs("../grid1/mode")').value
        === "hello_b");
  r = M.bindExpr(B, "s", 'chs("../grid1/s") + $F', G);
  check("  written into a STRING parameter", r.ok && B.widgets[3].value === "hello0", B.widgets[3].value);
  r = M.bindExpr(B, "mode", 'chs("../grid1/mode")', G);
  check("  written into a combo (value in the list)", r.ok && B.widgets[4].value === "b");
  r = M.bindExpr(B, "mode", '"zz"', G);
  check("  value not in the combo list: reports type mismatch, value unchanged", !r.ok && r.error.includes("type mismatch")
        && B.widgets[4].value === "b", J(r));
  r = M.bindExpr(B, "n", '"abc"', G);
  check("  string written into INT: reports type mismatch", !r.ok && r.error.includes("type mismatch"));
  r = M.bindExpr(B, "n", "7.6 + 0", G);
  check("  INT rounded, clamped to min/max (7.6 → 8; 500 → 100)", r.ok && B.widgets[2].value === 8
        && (M.bindExpr(B, "n", "500 * 1", G), B.widgets[2].value === 100));
  // panel parameters
  const PP = mkPanel("float radius = 2.5\nvector pos = 1 2 3\n");
  M.syncPanel(PP);
  PP.title = "ctrl";
  G._nodes.push(PP);
  r = M.bindExpr(B, "ty", 'ch("../ctrl/radius") * 2', G);
  check("panel parameter ch(\"../ctrl/radius\"): value 5, stored with the panel's id", r.ok && B.widgets[1].value === 5
        && M.bindings(B).ty === `=ch("@${PP.id}/radius") * 2`, J([r, M.bindings(B)]));
  check("  vector component pos.y", M.evalStored(G, B, '=ch("../ctrl/pos.y")').value === 2);
  check("  vector without a component: error", M.evalStored(G, B, '=ch("../ctrl/pos")').error?.includes("specify a component"));
  check("  name not on the panel: error", M.evalStored(G, B, '=ch("../ctrl/nope")').error?.includes("has no parameter nope"));
  // time variables
  check("no Frame node: $F = 0, $FPS = 24, $T = 0 (the Frame node's defaults)",
        J(["$F", "$FPS", "$T", "$FSTART", "$FEND", "$NFRAMES"].map((v) => M.evalStored(G, B, "=" + v).value))
        === J([0, 24, 0, 0, 23, 24]));
  const FR = mkNode("PCG_Frame", [{ name: "frame", value: 36 }, { name: "start", value: 12 },
                                  { name: "end", value: 60 }, { name: "fps", value: 24 }]);
  G._nodes.push(FR);
  check("with a Frame node: $F 36, $FF 36, $T = (36−12)/24 = 1, $FSTART 12, $FEND 60, $NFRAMES 49, $FPS 24",
        J(["$F", "$FF", "$T", "$FSTART", "$FEND", "$NFRAMES", "$FPS"].map((v) => M.evalStored(G, B, "=" + v).value))
        === J([36, 36, 1, 12, 60, 49, 24]));
  check("  $OS = own title", M.evalStored(G, B, "=$OS").value === "sphere1");
  r = M.bindExpr(C, "tx", "sin($F * 10)", G);
  check("sin($F*10): frame 36 → sin(360°) ≈ 0", r.ok && Math.abs(C.widgets[0].value) < 1e-9, C.widgets[0].value);
  FR.widgets[0].value = 39;
  M.applyBindings(G);
  check("  playbar changed the frame (writes the Frame node): the next materialization catches up → sin(390°) = 0.5", Math.abs(C.widgets[0].value - 0.5) < 1e-9);
  // materialize before queueing: app.graphToPrompt is wrapped
  let order = [];
  const savedApp = { graph: globalThis.__app.graph, g2p: globalThis.__app.graphToPrompt };
  globalThis.__app.graph = G;
  globalThis.__app.graphToPrompt = async () => { order.push(["g2p", C.widgets[0].value]); return {}; };
  const realSI = globalThis.setInterval;
  globalThis.setInterval = () => 0;                  // don't really start the periodic sync from setup
  await globalThis.__app.exts[0].setup();
  globalThis.setInterval = realSI;
  FR.widgets[0].value = 45;                          // sin(450°) = 1
  await globalThis.__app.graphToPrompt();
  check("materialize once before queueing (graphToPrompt): queueing right after changing the frame submits the new frame's value",
        order.length === 1 && Math.abs(order[0][1] - 1) < 1e-9, J(order));
  globalThis.__app.graph = savedApp.graph;
  globalThis.__app.graphToPrompt = savedApp.g2p;
  check("  node context menu Unbind shows the displayed expression", M.menuFor(C, G).find((i) => i.content === "PCG: Unbind")
        ?.submenu.options.some((o) => o.content === "tx ←sin($F * 10)"));
  // paste relative reference → upstream is an expression: resolveRef follows it
  M.copyParams(C, ["tx"]);
  M.pasteRefs(B, ["tx"], G);
  check("paste relative reference onto an expression parameter: follows the expression's value (1)", Math.abs(B.widgets[0].value - 1) < 1e-9);
  check("  parameters this node lacks / nodes not in the graph: bindExpr still evaluates on the spot", (() => {
    const lone = mkNode("PCG_X", [{ name: "tx", value: 0 }], ndX);
    const rr = M.bindExpr(lone, "tx", "3 * 4", G);
    return rr.ok && lone.widgets[0].value === 12;
  })());
  check("  empty expression is not bound", !M.bindExpr(B, "ty", "   ", G).ok);
}

// ══════════════════════════════════════════════════ 9. Keyframes / string templates / geometry queries (pcg93)
sec("Keyframes: k: binding, evaluated at the current frame");
const tick = () => new Promise((r) => setTimeout(r, 5));
{
  const nd = { input: { required: { tx: ["FLOAT", { default: 0 }], ty: ["FLOAT", { default: 0 }],
                                    n: ["INT", { default: 0 }], path: ["STRING", { default: "" }] } } };
  const G = { _nodes: [], links: {}, getNodeById(id) { return this._nodes.find((n) => n.id === id) ?? null; } };
  const mk = (title) => {
    const n = mkNode("PCG_Y", [{ name: "tx", value: 0 }, { name: "ty", value: 0 },
                               { name: "n", value: 0 }, { name: "path", value: "", type: "text" }], nd);
    n.title = title; G._nodes.push(n); return n;
  };
  const FR = mkNode("PCG_Frame", [{ name: "frame", value: 0 }, { name: "start", value: 0 },
                                  { name: "end", value: 48 }, { name: "fps", value: 24 }]);
  G._nodes.push(FR);
  const setF = (f) => { FR.widgets[0].value = f; M.applyBindings(G); };
  const A = mk("cam");
  M.setKey(G, A, "tx", 0, 0);
  check("first keyframe: binding written as k:0:0, value 0", M.bindings(A).tx === "k:0:0" && A.widgets[0].value === 0, M.bindings(A).tx);
  setF(24);
  M.setKey(G, A, "tx", 24, 10);
  check("  key 10 at frame 24: k:0:0  24:10", M.bindings(A).tx === "k:0:0  24:10");
  setF(12);
  check("  frame 12: cubic between two keys (auto slopes = straight line) = 5", Math.abs(A.widgets[0].value - 5) < 1e-12, A.widgets[0].value);
  check("  onKey: no key at frame 12", !M.onKey(G, A, "tx"));
  M.setKey(G, A, "tx", 12, 8);
  check("  key 8 at frame 12: three keys, the current frame is on a key", M.bindings(A).tx === "k:0:0  12:8  24:10" && M.onKey(G, A, "tx")
        && A.widgets[0].value === 8);
  M.setKey(G, A, "tx", 12, 6);
  check("  keying the same frame again: value changed, no extra key", M.bindings(A).tx === "k:0:0  12:6  24:10");
  M.bind(A, "tx", "k:0:0  12:6:ease  24:10");
  M.setKey(G, A, "tx", 12, 7);
  check("  changing the value keeps that key's interpolation (ease)", M.bindings(A).tx === "k:0:0  12:7:ease  24:10", M.bindings(A).tx);
  setF(30);
  check("  hold outside the range: frame 30 = 10", A.widgets[0].value === 10);
  check("keysOf: the parsed keys", J(M.keysOf(A, "tx").map((k) => [k.f, k.v])) === J([[0, 0], [12, 7], [24, 10]]));
  check("  keysOf of a non-keyframe binding = null", M.keysOf(A, "ty") === null);
  // referencing a keyframed parameter; chf takes another frame
  const B = mk("follow");
  M.bindExpr(B, "tx", 'ch("../cam/tx") * 2', G);
  check("expression referencing a keyframed parameter: follows the current frame (frame 30 → 20)", B.widgets[0].value === 20);
  setF(12);
  check("  catches up after a frame change (frame 12 → 14)", B.widgets[0].value === 14);
  M.bindExpr(B, "ty", 'chf("../cam/tx", 24) - chf("../cam/tx", 0)', G);
  check("chf(path, frame): value at another frame (frame 24's 10 − frame 0's 0 = 10)", B.widgets[1].value === 10);
  M.bindExpr(B, "n", 'chf("../follow/tx", 24)', G);
  check("  chf propagates down the chain: follow.tx at frame 24 = cam.tx@24 × 2 = 20", B.widgets[2].value === 20);
  // deleting keys
  check("removeKey: delete the one at frame 12", M.removeKey(G, A, "tx", 12) && M.bindings(A).tx === "k:0:0  24:10");
  check("  no key at this frame: nothing deleted, returns false", !M.removeKey(G, A, "tx", 5));
  M.removeKey(G, A, "tx", 0);
  const before = A.widgets[0].value;
  check("  deleting the last one: no longer a channel, value stays at the current one", M.removeKey(G, A, "tx", 24) && M.bindings(A)?.tx === undefined
        && A.widgets[0].value === before);
  check("  removeKey on a parameter without keyframes returns false", !M.removeKey(G, A, "ty", 0));
  // expression → set a key: becomes a channel
  M.bindExpr(A, "ty", "3 + 4", G);
  M.setKey(G, A, "ty", 12, A.widgets[1].value);
  check("setting a key on a parameter that was an expression: becomes a channel (value 7 keyed at the current frame)", M.bindings(A).ty === "k:12:7");
  M.bind(A, "tx", "k:0:0 5:x");
  M.applyBindings(G);
  check("malformed channel: error (field turns red)", (A._pcgBindErr?.tx || "").includes("is not a number"), A._pcgBindErr?.tx);
  check("  setKey with a non-number: no key set", !M.setKey(G, A, "ty", 12, "abc"));
  M.unbind(A, "tx");

  sec("String templates: ~ binding");
  let r = M.bindTemplate(A, "path", "out/${OS}_$F4.`$F*2`.png", G);
  check("out/${OS}_$F4.`$F*2`.png (frame 12) → out/cam_0012.24.png", r.ok && A.widgets[3].value === "out/cam_0012.24.png"
        && M.bindings(A).path === "~out/${OS}_$F4.`$F*2`.png", J([r, A.widgets[3].value]));
  setF(3);
  check("  follows a frame change", A.widgets[3].value === "out/cam_0003.6.png");
  r = M.bindTemplate(B, "path", 'v_`chs("../cam/path")`_`ch("../cam/ty")`', G);
  check("chs / ch inside backticks: paths stored as ids, displayed with titles again", r.ok
        && M.bindings(B).path === `~v_\`chs("@${A.id}/path")\`_\`ch("@${A.id}/ty")\``
        && M.bindingText(G, B, "path") === 'v_`chs("../cam/path")`_`ch("../cam/ty")`'
        && B.widgets[3].value === "v_out/cam_0003.6.png_7", J([M.bindings(B).path, B.widgets[3].value]));
  A.title = "cam2";
  check("  source renamed: display follows, value still computed", M.bindingText(G, B, "path") === 'v_`chs("../cam2/path")`_`ch("../cam2/ty")`'
        && M.evalBinding(G, B, "path").value === "v_out/cam2_0003.6.png_7", M.evalBinding(G, B, "path").value);
  A.title = "cam";
  r = M.bindTemplate(B, "path", "x `1+", G);
  check("malformed template (unterminated backtick): error, value unchanged", !r.ok && r.error.includes("unterminated backtick") && B.widgets[3].value
        === "v_out/cam_0003.6.png_7", J(r));
  M.unbind(B, "path");
  M.copyParams(A, ["path"]);
  M.pasteRefs(B, ["path"], G);
  check("pasted references in a string field display as `chs(...)` (with backticks, so clicking in to edit gives a valid template)",
        M.bindingText(G, B, "path", true, true) === '`chs("../cam/path")`'
        && M.bindingText(G, B, "path", true) === 'chs("../cam/path")');
  r = M.bindTemplate(B, "path", '`chs("../cam/path")`.bak', G);
  check("  appending .bak to it: becomes a template, path by its original id (@id/path)", r.ok
        && M.bindings(B).path === `~\`chs("@${A.id}/path")\`.bak` && B.widgets[3].value === "out/cam_0003.6.png.bak",
        J([M.bindings(B).path, B.widgets[3].value]));

  sec("Node functions: opname / opinputpath");
  const S = mk("src");
  const D = mk("dst");
  D.inputs = [{ name: "geo", link: 41 }, { name: "tx", widget: { name: "tx" }, link: 42 },
              { name: "geo2", link: null }];
  G.links[41] = { origin_id: S.id, origin_slot: 0 };
  G.links[42] = { origin_id: S.id, origin_slot: 1 };      // parameter socket wired: not a geometry input
  const ev2 = (t, self = D) => M.evalStored(G, self, "=" + t);
  check("opname(\".\") this node's title; opname(\"../src\")", ev2('opname(".")').value === "dst"
        && ev2('opname("../src")').value === "src" && ev2("opname()").value === "dst");
  check("opinputpath(\".\", 0): the node wired to geometry input 0 (parameter sockets don't count), written as @id",
        ev2('opinputpath(".", 0)').value === `@${S.id}` && ev2('opname(opinputpath(".", 0))').value === "src");
  check("  not wired / out of range: empty string", ev2('opinputpath(".", 1)').value === "" && ev2('opinputpath(".", 5)').value === "");
  check("  malformed / missing node path: error", ev2('opname("../nobody")').error?.includes("no node named 'nobody'")
        && ev2('opname("a/b/c")').error?.includes("unrecognized"));
  check("  \"./\" and the empty string are this node too; \"../#id\" looks up by id", ev2('opname("./")').value === "dst"
        && ev2('opname("")').value === "dst" && ev2(`opname("../#${S.id}")`).value === "src"
        && ev2('opname("../#999")').error?.includes("no longer exists"));

  sec("Geometry queries in fields: summary comes with executed, elements fetched on demand");
  const asked = [];
  let answer = (key, q) => {
    if (key === "gone") return { missing: true };
    if (q.op === "summary") return { npoints: 99, nprims: 1, nvertices: 3, bbox: [[0, 0, 0], [1, 1, 1]], detail: {} };
    if (q.name === "P" && q.cls === "point") return { value: [Number(q.n), 2 * Number(q.n), 0.5] };
    if (q.name === "name" && q.cls === "prim") return { value: "piece" + q.n };
    if (q.name === "name" && q.cls === "point") return { value: "pt" + q.n };
    return { value: null };
  };
  M.setGeoFetcher(async (key, q) => { asked.push([key, q]); return answer(key, q); });
  const BOX = mk("box1");
  const Q = mk("q");
  r = M.bindExpr(Q, "n", 'npoints("../box1")', G);
  check("not run yet: not an error (field not red), waiting; says 'has not run yet'", !r.ok && !Q._pcgBindErr?.n
        && (Q._pcgBindWait?.n || "").includes("has not run yet"), J([r, Q._pcgBindWait]));
  // executed message: onExecuted hook (all node types have it)
  const NT = { prototype: {} };
  await globalThis.__app.exts[0].beforeRegisterNodeDef(NT, { name: "PCG_Box" }, globalThis.__app);
  const saveGraph = globalThis.__app.graph;
  globalThis.__app.graph = G;
  NT.prototype.onExecuted.call(BOX, { pcg_geoq: [{ key: "k1", summary: { npoints: 8, nprims: 6, nvertices: 24,
    bbox: [[-1, 0, -2], [3, 4, 2]], detail: { scale: [2.5, 3], label: "hi" } } }] });
  check("the key from the executed message is stored on the node's properties (saved workflows carry it)", BOX.properties.pcg_geoq === "k1");
  await tick();
  check("  summary used directly, not fetched from the server: npoints = 8", Q.widgets[2].value === 8 && !asked.length, J(asked));
  const e2 = (t) => M.evalStored(G, Q, "=" + t);
  check("nprims / nvertices", e2('nprims("../box1")').value === 6 && e2('nvertices("../box1")').value === 24);
  check("bbox: D_XMIN −1, D_YMAX 4, D_ZSIZE 4, D_XSIZE 4", e2('bbox("../box1", D_XMIN)').value === -1
        && e2('bbox("../box1", D_YMAX)').value === 4 && e2('bbox("../box1", D_ZSIZE)').value === 4
        && e2('bbox("../box1", D_XSIZE)').value === 4);
  check("centroid: bounding box center (1, 2, 0)", J(["D_X", "D_Y", "D_Z"].map((a) => e2(`centroid("../box1", ${a})`).value))
        === J([1, 2, 0]));
  check("  wrong second argument to bbox / centroid: error", e2('bbox("../box1", 9)').error?.includes("D_XMIN")
        && e2('centroid("../box1", 3)').error?.includes("D_X"));
  check("detail: component, defaults to 0; details reads strings", e2('detail("../box1", "scale", 1)').value === 3
        && e2('detail("../box1", "scale")').value === 2.5 && e2('details("../box1", "label")').value === "hi");
  check("  no such detail attribute: 0 / empty string (same as Houdini)", e2('detail("../box1", "nope", 0)').value === 0
        && e2('details("../box1", "nope")').value === "");
  check("  string attribute read with detail: error says to use the s variant", e2('detail("../box1", "label")').error?.includes("with s"));
  // elements: pending the first time, materialized automatically once fetched
  r = M.bindExpr(Q, "tx", 'point("../box1", 3, "P", 1) + 1', G);
  check("point(): in flight the first time, not an error", !r.ok && (Q._pcgBindWait?.tx || "").includes("fetching") && !Q._pcgBindErr?.tx);
  await tick(); await tick();
  check("  materialized automatically once fetched: P[3].y + 1 = 7; the server was asked only once", Q.widgets[0].value === 7
        && asked.filter(([, q]) => q.op === "elem").length === 1
        && J(asked[0]) === J(["k1", { op: "elem", cls: "point", n: "3", name: "P" }]), J(asked));
  check("  evaluating again uses the cache, no new request", (M.applyBindings(G), asked.length === 1));
  r = M.bindExpr(Q, "path", "", G);
  M.bindTemplate(Q, "path", '`prims("../box1", 2, "name")`', G);
  await tick(); await tick();
  check("prims reads string attributes", Q.widgets[3].value === "piece2", Q.widgets[3].value);
  M.bindTemplate(Q, "path", '`points("../box1", 4.9, "name")`', G);
  await tick(); await tick();
  check("  points reads string point attributes; index rounded (4.9 → 4, the server is also asked for \"4\")", Q.widgets[3].value === "pt4"
        && asked.some(([, q]) => q.cls === "point" && q.n === "4" && q.name === "name"), Q.widgets[3].value);
  M.bindExpr(Q, "ty", 'point("../box1", 0, "nothere", 0)', G);
  await tick(); await tick();
  check("  no such attribute: 0", Q.widgets[1].value === 0 && !Q._pcgBindErr?.ty);
  check("  opinputpath passed to npoints (common Houdini idiom)", (() => {
    const D2 = mk("d2");
    D2.inputs = [{ name: "geo", link: 77 }];
    G.links[77] = { origin_id: BOX.id, origin_slot: 0 };
    return M.evalStored(G, D2, '=npoints(opinputpath(".", 0))').value === 8;
  })());
  // node paths are stored as ids too
  M.bindExpr(Q, "n", 'npoints("../box1") + nprims("../q")', G);
  check("node paths (npoints' argument) are stored as ids too; this node displays as \".\"",
        M.bindings(Q).n === `=npoints("@${BOX.id}") + nprims("@${Q.id}")`
        && M.bindingText(G, Q, "n") === 'npoints("../box1") + nprims(".")', [M.bindings(Q).n, M.bindingText(G, Q, "n")]);
  BOX.title = "box_renamed";
  check("  rename: display follows, the reference does not break (nprims(\".\") itself has not run yet, so it is waiting, not not-found)",
        M.bindingText(G, Q, "n").startsWith('npoints("../box_renamed")')
        && M.evalBinding(G, Q, "n").pending && M.evalBinding(G, Q, "n").error.includes("'q' has not run yet"),
        J(M.evalBinding(G, Q, "n")));
  BOX.title = "box1";
  // waiting propagates down the reference chain: referencing a parameter still waiting for data makes this one wait too (not an error)
  const Z = mk("z");
  const Y = mk("y");
  M.bindExpr(Y, "tx", 'npoints("../z")', G);
  M.bindExpr(Z, "ty", 'ch("../y/tx") + 1', G);
  check("referencing a parameter still waiting for data: this one is 'waiting' too (not red)", !Z._pcgBindErr?.ty && (Z._pcgBindWait?.ty || "").includes("has not run yet"),
        J([Z._pcgBindErr, Z._pcgBindWait]));
  // empty geometry: no bounding box
  NT.prototype.onExecuted.call(Z, { pcg_geoq: [{ key: "kz", summary: { npoints: 0, nprims: 0, nvertices: 0,
    bbox: null, detail: {} } }] });
  check("empty geometry: npoints 0; bbox / centroid report 'geometry is empty'", M.evalStored(G, Q, '=npoints("../z")').value === 0
        && M.evalStored(G, Q, '=bbox("../z", D_XMIN)').error?.includes("geometry is empty")
        && M.evalStored(G, Q, '=centroid("../z", D_X)').error?.includes("geometry is empty"));
  // re-run: new key, old cache dropped
  NT.prototype.onExecuted.call(BOX, { pcg_geoq: [{ key: "k2", summary: { npoints: 20, nprims: 1, nvertices: 1,
    bbox: [[0, 0, 0], [0, 0, 0]], detail: {} } }] });
  await tick(); await tick(); await tick();
  check("re-run (new key): point() refetches with the new key", asked.some(([k]) => k === "k2"), J(asked.map(([k]) => k)));
  check("  npoints follows the new summary (20)", M.evalStored(G, Q, '=npoints("../box1")').value === 20);
  check("  cache of old key k1 dropped (otherwise it keeps growing)", !M.geoCacheKeys().includes("k1") && M.geoCacheKeys().includes("k2"),
        J(M.geoCacheKeys()));
  // gone from the server
  BOX.properties.pcg_geoq = "gone";
  M.bindExpr(Q, "tx", 'npoints("../box1")', G);
  await tick(); await tick();
  M.applyBindings(G);
  check("the server no longer has this key: waiting (not red), hint says run again", !Q._pcgBindErr?.tx
        && (Q._pcgBindWait?.tx || "").includes("run again"), J([Q._pcgBindErr, Q._pcgBindWait]));
  // fetch failed
  answer = () => { throw new Error("boom"); };
  BOX.properties.pcg_geoq = "k3";
  M.bindExpr(Q, "tx", 'point("../box1", 1, "P", 0)', G);
  await tick(); await tick();
  M.applyBindings(G);
  check("error while fetching: red, with the reason", (Q._pcgBindErr?.tx || "").includes("boom"), J(Q._pcgBindErr));
  globalThis.__app.graph = saveGraph;
  M.setGeoFetcher(null);
}

// ══════════════════════════════════════════════════ 10. Who references whom (pcg94, for drawing dashed lines)
sec("refSources / refEdges: references in bindings turned into source node → this node");
{
  const G = { _nodes: [], links: {}, getNodeById(id) { return this._nodes.find((n) => String(n.id) === String(id)) ?? null; } };
  const mk = (title, type = "PCG_Z") => {
    const n = mkNode(type, [{ name: "tx", value: 0 }, { name: "ty", value: 0 }, { name: "s", value: "", type: "text" }]);
    n.title = title; G._nodes.push(n); return n;
  };
  const a = mk("a"), b = mk("b"), c = mk("c"), d = mk("dup"), d2 = mk("dup");
  mk("ty");                                                    // a node with the same name as the parameter in ch("ty"): must not be taken as a reference to it
  const pnl = mkPanel("float radius = 1\n");
  M.syncPanel(pnl); pnl.title = "ctrl"; G._nodes.push(pnl);
  const ids = (rs) => J(rs.map((r) => [r.node.title, r.params.sort()]).sort());
  M.bind(c, "tx", `@${a.id}/tx`);                              // pasted
  M.bind(c, "ty", `=ch("@${b.id}/tx") + npoints("@${a.id}") + ch("ty")`);   // expression, including self
  M.bind(c, "s", "~x_`chs(\"../b/s\")`_$F");                    // template, title path not canonicalized
  check("pasted references / ch and npoints in expressions / title paths in templates all count; this node's ch(\"ty\") does not; grouped by source node",
        ids(M.refSources(G, c)) === J([["a", ["tx", "ty"]], ["b", ["s", "ty"]]]), ids(M.refSources(G, c)));
  M.bind(b, "tx", "radius");
  M.bind(b, "ty", '=ch("../dup/tx") + ch("../nobody/tx") + ch("../#999/tx")');
  check("panel parameter name → panel node; duplicate titles / not found / deleted-node paths don't count", ids(M.refSources(G, b)) === J([["ctrl", ["tx"]]]),
        ids(M.refSources(G, b)));
  M.bind(a, "tx", "k:0:0  10:1");
  M.bind(a, "ty", `=ch("../#${b.id}/ty") + opname(opinputpath(".", 0))`);
  check("keyframes are not references; ../#id syntax looks up by id; computed paths like opinputpath don't count",
        ids(M.refSources(G, a)) === J([["b", ["ty"]]]), ids(M.refSources(G, a)));
  check("  malformed expression: no throw, whatever is recognizable is still recognized", (M.bind(a, "s", '=ch("../c/tx") +'), ids(M.refSources(G, a)))
        === J([["b", ["ty"]], ["c", ["s"]]]), ids(M.refSources(G, a)));
  const es = M.refEdges(G).map((e) => `${e.from.title}>${e.to.title}`).sort();
  check("refEdges: edges of the whole graph", J(es) === J(["a>c", "b>a", "b>c", "c>a", "ctrl>b"]), J(es));
  check("  paths written as @self / ../own title: don't count (no line from a node to itself)",
        (M.bind(d, "tx", `@${d.id}/ty`), M.bind(c, "s", `=ch("@${c.id}/tx") + ch("../c/ty")`), ids(M.refSources(G, c)))
        === J([["a", ["tx", "ty"]], ["b", ["ty"]]]) && M.refSources(G, d).length === 0, ids(M.refSources(G, c)));
  M.unbind(d, "tx");
  const s1 = M.bindingPaths('=ch("../a/tx")');
  check("  bindingPaths caches per string: the same string gets the same array (the whole graph is scanned every frame)",
        s1 === M.bindingPaths('=ch("../a/tx")') && J(s1) === J(["../a/tx"]), J(s1));
  check("  nodes without bindings: no edges", M.refSources(G, d).length === 0 && M.refSources(G, d2).length === 0);
}

const pass = OK.filter(Boolean).length;
console.log(`\n${pass}/${OK.length} passed`);
process.exit(pass === OK.length ? 0 : 1);
