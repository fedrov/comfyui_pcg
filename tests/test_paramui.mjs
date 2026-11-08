// Frontend unit tests for the "Edit Parameter Interface" dialog (pcg_paramui.js, pcg96). jsdom + stubbed app, actually running the module.
//
// The dialog is just an editor for the declaration text, so the most important points are:
//   1) **text round trip loses nothing**: comments, blank lines and malformed lines are kept verbatim; every joined line is accepted by the real parser
//      (the parse checked against the same golden table as the backend)
//   2) **string defaults** containing # and : get quoted (otherwise the /out of "C:/out" would be taken as a range)
//   3) **renaming does not break references**: name references, ch("@id/oldname"), those in templates, and non-canonical ../title/oldname all follow;
//      stored values are moved over; same-named parameters on other panels / other nodes are untouched; an a↔b swap does not mix them up
//   4) the dialog itself: add / delete / duplicate / reorder / change type / no confirm while there are errors / cancel changes nothing / keys don't leak to the canvas
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
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "jstest_paramui_"));
process.on("exit", () => fs.rmSync(ROOT, { recursive: true, force: true }));
const EXT = path.join(ROOT, "extensions", "comfyui_pcg");
fs.mkdirSync(path.join(ROOT, "scripts"), { recursive: true });
fs.mkdirSync(EXT, { recursive: true });
fs.writeFileSync(path.join(ROOT, "scripts", "app.js"), "export const app = globalThis.__app;\n");
fs.writeFileSync(path.join(ROOT, "scripts", "api.js"), "export const api = { addEventListener() {} };\n");
for (const f of ["pcg_paramui.js", "pcg_params.js", "pcg_hexpr.js", "pcg_chan.js"])
  fs.copyFileSync(path.join(PKG, "comfyui_pcg", "web", f), path.join(EXT, f));

const dom = new JSDOM("<!doctype html><html><head></head><body></body></html>",
                      { url: "http://localhost/", pretendToBeVisual: true, virtualConsole: new VirtualConsole() });
for (const k of ["window", "document", "HTMLElement", "Node", "Event", "KeyboardEvent", "MouseEvent"])
  Object.defineProperty(globalThis, k, { value: k === "window" ? dom.window : dom.window[k],
                                         writable: true, configurable: true });

const OK = [];
function check(name, cond, extra = "") {
  OK.push(!!cond);
  console.log((cond ? "  PASS  " : "  FAIL  ") + name + (extra === "" ? "" : "   " + extra));
}
const sec = (t) => console.log(`\n── ${t}`);
const J = (x) => JSON.stringify(x);
const JS = (o) => JSON.stringify(Object.entries(o).sort());       // regardless of key order

let nextId = 1;
function mkNode(type, widgets = []) {
  const n = {
    type, id: nextId++, title: null, pos: [0, 0], size: [200, 100], flags: {}, properties: {},
    widgets: [], inputs: [], dirty: 0,
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
  return n;
}
const G = { _nodes: [], changes: [], beforeChange() { this.changes.push("b"); }, afterChange() { this.changes.push("a"); },
            getNodeById(id) { return this._nodes.find((n) => String(n.id) === String(id)) ?? null; } };
const exts = [];
globalThis.__app = { graph: G, canvas: { setDirty() {} }, registerExtension(e) { exts.push(e); } };

const P = await import(path.join(EXT, "pcg_params.js"));
const U = await import(path.join(EXT, "pcg_paramui.js"));

function mkPanel(decl, title) {
  const p = mkNode("PCG_Parameters", [{ type: "text", name: "declare", value: decl },
                                      { type: "text", name: "values", value: "{}" }]);
  p.title = title;
  G._nodes.push(p);
  P.syncPanel(p);
  return p;
}
const W = (n, name) => n.widgets.find((w) => w.name === name);

// ═══════════════════════════════════════════════ 1. Text <-> entries
sec("Text round trip: split into entries and join back");
const SRC = [
  "# controller",
  "float radius = 1 : 0 10  # Radius",
  "",
  "int   count=5:1 100",
  "bool cap = on",
  "vector pos = 0 1.5 0",
  "vec4 col = 1",
  'string dir = "C:/out#1"   # output',
  "string s",
  "floot bad = 1",
  "// tail",
].join("\n");
const items = U.parseItems(SRC + "\n\n\n");
check("11 lines → 11 entries (the trailing blank line does not count); comments / blank lines / malformed lines are raw, malformed ones carry a reason",
      items.length === 11 && J(items.map((x) => x.kind[0]).join("")) === J("rprppppppr" + "r")
      && items[9].error.includes("unknown type 'floot'") && !items[0].error, J(items.map((x) => x.kind[0]).join("")));
check("  parameter entries: type / name / label / default (as string) / range; the name at open time is remembered",
      J(items[1]) === J({ kind: "param", type: "float", name: "radius", label: "Radius", orig: "radius",
                          def: "1", range: true, min: "0", max: "10" }), J(items[1]));
check("  vector defaults are string arrays (one number fills all); bool is a boolean; no range means range = false",
      J(items[5].def) === J(["0", "1.5", "0"]) && J(items[6].def) === J(["1", "1", "1", "1"])
      && items[4].def === true && items[5].range === false && items[7].def === "C:/out#1");
const out = U.toText(items);
check("joined back into text: normalized as type name = default : range  # label; comments / blank lines / malformed lines verbatim",
      out === [
        "# controller", "float radius = 1 : 0 10  # Radius", "", "int count = 5 : 1 100", "bool cap = true",
        "vector pos = 0 1.5 0", "vector4 col = 1 1 1 1", 'string dir = "C:/out#1"  # output', "string s",
        "floot bad = 1", "// tail", ""].join("\n"), out);
check("  splitting and joining again is a fixed point", U.toText(U.parseItems(out)) === out);
const good = items.filter((x) => !x.error);
check("  the joined text is accepted by the real parser, and parses to the same parameters as the original (the dialog does not change semantics)",
      J(P.parse(U.toText(good))) === J(P.parse(SRC.replace("floot bad = 1", ""))));
check("  empty list → empty text", U.toText([]) === "" && U.parseItems("").length === 0 && U.parseItems("\n \n").length === 0);

sec("Quoting of string defaults");
const q = (v) => U.quoteDefault(v);
check("plain ones are not quoted; ones with # / :, leading/trailing spaces, or starting with a quote are", q("piece") === "piece" && q("a b") === "a b"
      && q("C:/x") === '"C:/x"' && q("a#b") === '"a#b"' && q(" x") === '" x"' && q("x ") === '"x "'
      && q('"x') === `'"x'` && q("'x") === `"'x"`, J([q("C:/x"), q('"x'), q("'x")]));
check("  double quotes inside: use single quotes; both kinds cannot be quoted (left for validate to report)", q('say "a:b"') === `'say "a:b"'`
      && q(`a"b'c:d`) === null && q(`a"b'c`) === `a"b'c`);
const rt = (v) => P.parse(U.formatItem({ kind: "param", type: "string", name: "s", label: "", def: v }))[0].default;
const strs = ["", "piece", "C:/out#1", " lead", "tail ", '"quoted"', "it's: x", 'say "hi" # no', "a=b", "x # y"];
check("  round trip: all kinds of strings written into a line and parsed back stay the same", strs.every((v) => rt(v) === v),
      J(strs.filter((v) => rt(v) !== v)));

sec("validate: the real parser + duplicates + string round trip");
const mkIt = (o) => ({ kind: "param", type: "float", name: "x", label: "", def: "0", range: false, min: "0", max: "1", ...o });
const V = (its) => U.validate(its);
check("good ones have no errors", J(V([mkIt({}), mkIt({ name: "y", type: "vector", def: ["0", "1", "2"] })])) === "{}");
check("invalid / empty name", V([mkIt({ name: "1a" })])[0].includes("invalid") && V([mkIt({ name: "" })])[0] !== undefined
      && V([mkIt({ name: "a b" })])[0] !== undefined, J(V([mkIt({ name: "1a" })])));
check("  errors don't carry 'line 1' (the dialog talks about entry numbers)", !/line 1/.test(V([mkIt({ name: "1a" })])[0]));
check("duplicates: the later entry reports, pointing at the earlier one", J(Object.keys(V([mkIt({}), mkIt({ name: "y" }), mkIt({})]))) === J(["2"])
      && V([mkIt({}), mkIt({ name: "y" }), mkIt({})])[2].includes("duplicates entry 1"));
check("default not a number; reversed range; vector component not a number", V([mkIt({ def: "abc" })])[0].includes("is not a number")
      && V([mkIt({ range: true, min: "5", max: "1" })])[0].includes("range is reversed")
      && V([mkIt({ type: "vector", def: ["0", "x", "0"] })])[0].includes("is not a number"));
check("  range unchecked: whatever min / max say is ignored", J(V([mkIt({ range: false, min: "zz", max: "" })])) === "{}");
check("  empty vector components are written as 0 (otherwise '= 1' would be taken as one number filling all); labels are trimmed, spaces only = no label",
      U.formatItem(mkIt({ name: "v", type: "vector", def: ["", "1", " "] })) === "vector v = 0 1 0"
      && U.formatItem(mkIt({ label: "  Radius " })) === "float x = 0  # Radius" && U.formatItem(mkIt({ label: "   " })) === "float x = 0"
      && U.formatItem(mkIt({ type: "bool", def: true })) === "bool x = true" && U.formatItem(mkIt({ type: "bool", def: false })) === "bool x = false");
check("  empty number fields count as 0 (no error)", J(V([mkIt({ def: "" }), mkIt({ name: "v", type: "vector", def: ["", "1", ""] })])) === "{}"
      && U.formatItem(mkIt({ def: " " })) === "float x = 0");
check("string with both kinds of quotes + a colon: cannot be written into the declaration, reported", V([mkIt({ type: "string", def: `a"b'c:d` })])[0].includes("both kinds of quotes"));
check("  line breaks are not allowed", V([mkIt({ type: "string", def: "a\nb" })])[0].includes("line breaks")
      && V([mkIt({ label: "a\nb" })])[0].includes("line breaks"));
check("  malformed raw lines count as errors; comments don't", J(Object.keys(V(U.parseItems("# c\nfloot x")))) === J(["1"]));

sec("newItem / retype / renameMap");
const n1 = U.newItem("float", []);
check("new parameters are called newparameter; if taken newparameter2, 3", n1.name === "newparameter" && n1.orig === undefined
      && U.newItem("int", [n1]).name === "newparameter2"
      && U.newItem("int", [n1, mkIt({ name: "newparameter2" })]).name === "newparameter3");
check("  defaults per type", U.newItem("bool", []).def === false && U.newItem("string", []).def === ""
      && J(U.newItem("vector", []).def) === J(["0", "0", "0"]) && U.newItem("vector4", []).def.length === 4
      && U.newItem("float", []).def === "0" && U.newItem("int", []).max === "10" && U.newItem("float", []).max === "1");
check("  a newly created entry of every type passes validate and the parser", U.TYPES.every(([t]) =>
  J(U.validate([U.newItem(t, [])])) === "{}" && P.parse(U.formatItem(U.newItem(t, [])))[0].type === t));
const R = (o, t) => U.retype(mkIt(o), t);
check("change type: float 2.6 → int 3 / vector fills all / bool true / string '2.6'", R({ def: "2.6" }, "int").def === "3"
      && J(R({ def: "2.6" }, "vector").def) === J(["2.6", "2.6", "2.6"]) && R({ def: "2.6" }, "bool").def === true
      && R({ def: "2.6" }, "string").def === "2.6" && R({ def: "0" }, "bool").def === false);
check("  vector → float takes the first; vector3 → 4 pads with 0; vector4 → 3 truncates; → string joined with spaces",
      R({ type: "vector", def: ["3", "4", "5"] }, "float").def === "3"
      && J(R({ type: "vector", def: ["3", "4", "5"] }, "vector4").def) === J(["3", "4", "5", "0"])
      && J(R({ type: "vector4", def: ["3", "4", "5", "6"] }, "vector").def) === J(["3", "4", "5"])
      && R({ type: "vector", def: ["3", "4", "5"] }, "string").def === "3 4 5");
check("  bool → float 1 / 0, → string true / false; string → bool accepts on / yes; string that is not a number → 0",
      R({ type: "bool", def: true }, "float").def === "1" && R({ type: "bool", def: false }, "int").def === "0"
      && R({ type: "bool", def: true }, "string").def === "true" && R({ type: "bool", def: false }, "string").def === "false"
      && R({ type: "string", def: " ON " }, "bool").def === true && R({ type: "string", def: "nope" }, "bool").def === false
      && R({ type: "string", def: "abc" }, "float").def === "0" && R({ type: "string", def: "" }, "float").def === "0"
      && R({ type: "string", def: "7" }, "int").def === "7");
check("  range: kept between numeric types, removed when switching to bool / string; same type changes nothing",
      R({ range: true }, "int").range === true && R({ range: true }, "vector").range === true
      && R({ range: true }, "bool").range === false && R({ range: true }, "string").range === false
      && R({ def: "2.60" }, "float").def === "2.60");
check("renameMap: only entries that existed at open time and whose name changed", J([...U.renameMap([
  mkIt({ orig: "a", name: "b" }), mkIt({ orig: "c", name: "c" }), mkIt({ name: "new" }), { kind: "raw", text: "# x" }])])
  === J([["a", "b"]]));

// ═══════════════════════════════════════════════ 2. References
sec("usage / visitRef / applyItems: renames carry references along");
G._nodes.length = 0;
const ctrl = mkPanel("float radius = 1 : 0 10\nvector pos = 0 1 0\nstring name = rock\nint count = 5", "CTRL");
const other = mkPanel("float radius = 9\nfloat gap = 2", "OTHER");     // duplicate radius: by-name lookup lands on the earlier CTRL
const mkT = (title) => { const n = mkNode("PCG_X", [{ name: "a", value: 0 }, { name: "b", value: 0 }, { name: "c", value: 0 },
                                                    { name: "d", value: 0 }, { name: "s", value: "", type: "text" }]);
                         n.title = title; G._nodes.push(n); return n; };
const t1 = mkT("t1"), t2 = mkT("t2");
P.bind(t1, "a", "radius");                                    // name reference
P.bind(t1, "b", "pos.y");                                     // name + component
P.bind(t1, "c", `=ch("@${ctrl.id}/radius") * 2 + ch("@${ctrl.id}/pos.x") + ch("@${other.id}/radius")`);
P.bind(t1, "d", `=ch("../CTRL/count") + ch("../OTHER/gap") + ch("b")`);   // non-canonical title path
P.bind(t1, "s", `~\`chs("@${ctrl.id}/name")\`_$F`);           // template
P.bind(t2, "a", "gap");                                       // the other panel's
P.bind(t2, "b", `@${t1.id}/a`);                               // node to node
P.bind(t2, "c", "k:0:0  10:1");                               // keyframes
P.bind(t2, "d", "pos[2]");
P.applyBindings(G);
const use = U.usage(G, ctrl);
check("usage: how many places reference each parameter (name / component / expression / title path / template all count; two in one expression count as two)",
      J([...use].sort()) === J([["count", 1], ["name", 1], ["pos", 3], ["radius", 2]]), J([...use].sort()));
check("  duplicate radius: name references count on the earlier CTRL, the @OTHER one counts for OTHER; node references / keyframes don't count",
      J([...U.usage(G, other)].sort()) === J([["gap", 2], ["radius", 1]]), J([...U.usage(G, other)].sort()));

const its = U.parseItems(W(ctrl, "declare").value);
W(ctrl, "values").value = J({ radius: 3, pos: [1, 2, 3], name: "stone", count: 7 });
its[0].name = "r";                                            // radius → r
its[1].name = "origin";                                       // pos → origin
its[2].label = "Name";                                         // only the label changed
its.splice(3, 1);                                             // delete count
its.push(U.newItem("bool", its));
G.changes.length = 0;
const res = U.applyItems(G, ctrl, its);
check("applyItems: the declaration is written back, wrapped in beforeChange / afterChange (undoable)",
      W(ctrl, "declare").value === "float r = 1 : 0 10\nvector origin = 0 1 0\nstring name = rock  # Name\nbool newparameter = false\n"
      && J(G.changes) === J(["b", "a"]), J(W(ctrl, "declare").value));
check("  stored values move to the new names (not back to defaults); deleted ones cleared; new ones take defaults",
      JS(JSON.parse(W(ctrl, "values").value)) === JS({ r: 3, origin: [1, 2, 3], name: "stone", newparameter: false }),
      W(ctrl, "values").value);
let b1 = t1.properties.pcg_bind, b2 = t2.properties.pcg_bind;
check("  name references follow (components kept)", b1.a === "r" && b1.b === "origin.y" && b2.d === "origin[2]", J([b1.a, b1.b, b2.d]));
check("  @id paths in expressions follow; the same-named radius pointing at another panel is untouched",
      b1.c === `=ch("@${ctrl.id}/r") * 2 + ch("@${ctrl.id}/origin.x") + ch("@${other.id}/radius")`, b1.c);
check("  not renamed (count deleted, gap belongs to another panel, b is this node's) stay as is; unrenamed ones in templates too",
      b1.d === `=ch("../CTRL/count") + ch("../OTHER/gap") + ch("b")` && b1.s === `~\`chs("@${ctrl.id}/name")\`_$F`, b1.d);
check("  other panels', node-to-node, keyframes: untouched", b2.a === "gap" && b2.b === `@${t1.id}/a` && b2.c === "k:0:0  10:1");
check("  number replaced: returns 4 (a, b, c, t2.d; two spots in c count as one binding)", res.renamed === 4, res.renamed);
check("  references still alive: panel sets r = 3 → t1.a = 3, t1.b = origin.y = 2, t1.c = 3*2 + 1 + 9 = 16",
      W(t1, "a").value === 3 && W(t1, "b").value === 2 && W(t1, "c").value === 16,
      J([W(t1, "a").value, W(t1, "b").value, W(t1, "c").value]));
check("  entries' orig updated to the new names (renaming again after Apply counts from the new names)", its[0].orig === "r" && its[1].orig === "origin"
      && its[3].orig === "newparameter");
check("  panel redrawn", ctrl.dirty > 0);

{
  // rename a → b while adding a new one called a: the new a starts from its default, it does not pick up the old a's value
  const pz = mkPanel("float a = 1", "PZ");
  W(pz, "values").value = J({ a: 7 });
  const iz = U.parseItems("float a = 1");
  iz[0].name = "b";
  iz.push({ ...U.newItem("float", iz), name: "a", def: "2" });
  U.applyItems(G, pz, iz);
  check("rename a → b while adding a new a: b gets the old value 7, the new a has its own default 2 (does not pick up the old a's)",
        JS(JSON.parse(W(pz, "values").value)) === JS({ a: 2, b: 7 }), W(pz, "values").value);
  G._nodes.splice(G._nodes.indexOf(pz), 1);
}
// renames in templates + title paths; a↔b swap
P.bind(t1, "d", `=ch("../CTRL/r") + 1`);
const its2 = U.parseItems(W(ctrl, "declare").value);
its2[0].name = "name";                                        // r → name
its2[2].name = "r";                                           // name → r   (swap)
W(ctrl, "values").value = J({ r: 3, origin: [1, 2, 3], name: "stone", newparameter: true });
const res2 = U.applyItems(G, ctrl, its2);
b1 = t1.properties.pcg_bind;                                  // bind may have been replaced by a new object
check("a ↔ b swap: values follow each one (they don't both become the same)", JS(JSON.parse(W(ctrl, "values").value))
      === JS({ name: 3, origin: [1, 2, 3], r: "stone", newparameter: true }), W(ctrl, "values").value);
check("  references swap individually too: t1.a r → name; template name → r; title path ../CTRL/r → ../CTRL/name",
      b1.a === "name" && b1.s === `~\`chs("@${ctrl.id}/r")\`_$F` && b1.d === `=ch("../CTRL/name") + 1`
      && b1.c.startsWith(`=ch("@${ctrl.id}/name") * 2`), J([b1.a, b1.s, b1.d]));
check("  4 bindings (a, c, d, s)", res2.renamed === 4, res2.renamed);
const dupT = mkNode("PCG_X", [{ name: "a", value: 0 }]); dupT.title = "CTRL"; G._nodes.push(dupT);
P.bind(t2, "a", `=ch("../CTRL/origin.x")`);
const its3 = U.parseItems(W(ctrl, "declare").value);
its3[1].name = "o2";
U.applyItems(G, ctrl, its3);
b1 = t1.properties.pcg_bind;
check("duplicate titles (both nodes called CTRL): the title path is ambiguous, not replaced; @id ones are replaced",
      t2.properties.pcg_bind.a === `=ch("../CTRL/origin.x")` && b1.c.includes(`ch("@${ctrl.id}/o2.x")`), b1.c);
G._nodes.splice(G._nodes.indexOf(dupT), 1);
const noDecl = mkNode("PCG_Parameters", []);
check("node without a declare widget: no throw, does nothing", J(U.applyItems(G, noDecl, [])) === J({ renamed: 0 }));
const cbErr = mkPanel("float z = 1", "CB");
W(cbErr, "declare").callback = () => { throw new Error("another extension's callback broke"); };
const itz = U.parseItems("float z = 1"); itz[0].label = "Z";
U.applyItems(G, cbErr, itz);
check("someone else's callback on declare throws: the declaration is still written and the controls still synced", W(cbErr, "declare").value === "float z = 1  # Z\n"
      && W(cbErr, "p_z")?.label === "Z");
check("visitRef: non-strings / malformed name references are returned as is", U.visitRef(G, ctrl, 5, new Map(), () => "x") === 5
      && U.visitRef(G, ctrl, "a.q", new Map(), () => "x") === "a.q");

// ═══════════════════════════════════════════════ 3. Dialog
sec("Dialog: three columns, add / delete / duplicate / reorder");
G._nodes.length = 0;
const pn = mkPanel("# ctl\nfloat radius = 1 : 0 10  # Radius\nint count = 5\nbool cap = true", "CTL");
const tg = mkT("tg");
P.bind(tg, "a", "radius"); P.bind(tg, "b", `=ch("@${pn.id}/radius")+ch("@${pn.id}/count")`);
P.applyBindings(G);
const fire = (e, t, init = {}) => e.dispatchEvent(new dom.window.Event(t, { bubbles: true, ...init }));
const key = (e, k) => { const ev = new dom.window.KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true });
                        e.dispatchEvent(ev); return ev; };
let D = U.openDialog(pn, G);
const $ = (s) => D.mask.querySelector(s);
const $$ = (s) => [...D.mask.querySelectorAll(s)];
const rowsTxt = () => $$(".cols .col:nth-child(2) .list .it").map((r) => r.textContent);
const inp = (k) => D.descEl.querySelector(`[data-k="${k}"]`);
const type = (k, v) => { const e = inp(k); e.value = v; fire(e, "input"); };
check("open: title has the node name; left column 6 types; middle column 4 entries (comment in gray); the first parameter selected by default",
      $(".ttl div").textContent.includes("CTL") && $$("[data-type]").length === 6
      && rowsTxt().length === 4 && $$(".it.raw").length === 1 && D.sel === 1
      && $$(".cols .col:nth-child(2) .it")[1].classList.contains("sel"), J(rowsTxt()));
check("  each middle-column entry: label (name), reference count, type", rowsTxt()[1] === "Radius(radius)← 2Float"
      && rowsTxt()[2] === "count(count)← 1Integer" && rowsTxt()[3] === "cap(cap)Toggle", J(rowsTxt()));
check("  referenced parameter: the bottom of the right column says how many references", D.descEl.querySelector(".hint").textContent.includes("Referenced by 2 parameters"));
check("  right column: Name / Label / Type / Default / Range", inp("name").value === "radius" && inp("label").value === "Radius"
      && inp("type").value === "float" && inp("def").value === "1" && inp("range").checked
      && inp("min").value === "0" && inp("max").value === "10");
check("  bottom: parameter count, buttons clickable", D.msgEl.textContent === "3 parameters" && !D.btnAccept.disabled && !D.btnApply.disabled);

$('[data-type="vector"]').click();
check("clicking Float Vector 3 in the left column: added after the selected entry, selected, named newparameter, focus in the name field (typing renames directly)",
      D.items[2].name === "newparameter" && D.items[2].type === "vector" && D.sel === 2 && D.items.length === 5
      && inp("def0").value === "0" && inp("def2") && !inp("def3") && document.activeElement === inp("name"));
type("name", " height ");
type("label", "Height");
type("def1", "2.5");
check("typing in the right column: the entry follows (name trimmed), the middle-column row follows, the right column is not redrawn (focus kept)",
      D.items[2].name === "height" && D.items[2].label === "Height" && J(D.items[2].def) === J(["0", "2.5", "0"])
      && rowsTxt()[2] === "Height(height)Float Vector 3" && inp("name").value === " height ", rowsTxt()[2]);
check("  the hint at the bottom of the right column follows the name, vectors with a component: ch(\"../CTL/height.x\")", D.descEl.textContent.includes('ch("../CTL/height.x")'),
      D.descEl.querySelector(".hint").textContent);
inp("range").checked = true; fire(inp("range"), "change");
type("min", "-1"); type("max", "5");
check("  Range checked: min / max can be filled in", D.items[2].range && D.items[2].min === "-1" && !inp("min").disabled
      && U.formatItem(D.items[2]) === "vector height = 0 2.5 0 : -1 5  # Height", U.formatItem(D.items[2]));
inp("range").checked = false; fire(inp("range"), "change");
check("  Range unchecked: min / max grayed out, not written into the declaration", inp("min").disabled && inp("max").disabled
      && U.formatItem(D.items[2]) === "vector height = 0 2.5 0  # Height");

type("name", "count");
check("name clashes with another: that row red, right-column input outlined red, the bottom says which entry, Apply / Accept grayed out",
      $$(".cols .col:nth-child(2) .it")[3].classList.contains("bad") === true
      && D.msgEl.textContent.includes("entry 4") && D.btnAccept.disabled && D.btnApply.disabled
      && !D.msgEl.classList.contains("ok"), D.msgEl.textContent);
check("  the entry being edited gets a malformed name: the input is outlined red on the spot, cleared on the spot once fixed", (type("name", "fine"), !inp("name").classList.contains("bad"))
      && (type("name", "1x"), inp("name").classList.contains("bad"))
      && (type("name", "fine2"), !inp("name").classList.contains("bad")) && (type("name", "count"), true));
D.items[1].name = "9z"; D.renderList();
check("  two entries with errors: the bottom names the earlier one", D.msgEl.textContent.includes("entry 2"), D.msgEl.textContent);
D.items[1].name = "radius"; D.renderList();
D.select(3);
check("  selecting the erroneous entry: right-column input outlined red", inp("name").classList.contains("bad"));
D.select(2);
check("  clicking Accept with errors writes nothing either (button grayed + apply checks again itself)", D.apply() === false
      && W(pn, "declare").value.includes("int count = 5\n"));
type("name", "height");
check("  changed back: the error is gone", D.btnAccept.disabled === false && D.msgEl.classList.contains("ok") && !inp("name").classList.contains("bad"));

const sel = inp("type"); sel.value = "float"; fire(sel, "change");
check("change type vector → float: default takes the first, the right column is redrawn with one field", D.items[2].type === "float" && D.items[2].def === "0"
      && inp("def") && !inp("def0"));
check("  the float hint has no component", D.descEl.textContent.includes('ch("../CTL/height")'));
sel.value = "x";      // after the redraw the old select is gone
inp("type").value = "bool"; fire(inp("type"), "change");

inp("type").value = "string"; fire(inp("type"), "change");
check("  the string hint uses chs", D.descEl.textContent.includes('chs("../CTL/height")'));
inp("type").value = "bool"; fire(inp("type"), "change");
check("  → Toggle: the default is a checkbox, no Range row", inp("def").type === "checkbox" && !inp("range"));
inp("def").checked = true; fire(inp("def"), "change");
check("  default checked", D.items[2].def === true && U.formatItem(D.items[2]) === "bool height = true  # Height");

D.select(1); type("name", "rad");
check("renamed but not applied yet: the reference count is still there (counted by the names at open time)", rowsTxt()[1] === "Radius(rad)← 2Float", rowsTxt()[1]);
type("name", "radius");
D.btnDup.click();
check("duplicating an existing parameter: the copy has no orig (otherwise applying would move the references to radius onto the copy)",
      D.items[2].name === "radius2" && D.items[2].orig === undefined && D.items[1].orig === "radius"
      && J([...U.renameMap(D.items)]) === "[]");
D.btnDel.click();
D.select(2);
inp("type").value = "vector"; fire(inp("type"), "change");
D.btnDup.click();
type("def0", "9");
check("  duplicating a vector: the copy's default is its own (changing the copy does not touch the original)", J(D.items[3].def) === J(["9", "1", "1"]) && J(D.items[2].def) === J(["1", "1", "1"]),
      J([D.items[2].def, D.items[3].def]));
D.btnDel.click(); D.select(2);
inp("type").value = "bool"; fire(inp("type"), "change");
D.btnDup.click();
check("duplicate: inserted after, name gets a number, no orig (it is a new parameter), the new one selected", D.items[3].name === "height2" && D.items[3].orig === undefined
      && D.items[3].label === "Height" && D.sel === 3 && D.items.length === 6);
D.btnDup.click();
check("  duplicate again: height3 (not height22)", D.items[4].name === "height3", D.items[4].name);
D.btnDel.click();
check("delete: the entry that moves up (the next one) is selected", D.items.length === 6 && D.sel === 4 && D.items[4].name === "count");
D.select(3); D.btnDel.click();
D.select(D.items.length - 1); D.btnDel.click();
check("  deleting the last entry: selection falls back to the new last one", D.items.length === 4 && D.sel === 3 && D.items[3].name === "count");
D.items.push(U.parseItems("bool cap = true")[0]); D.select(3);

const names = () => D.items.map((x) => (x.kind === "param" ? x.name : "#"));
D.btnUp.click();
check("↑: swaps with the previous entry, the selection follows", J(names()) === J(["#", "radius", "count", "height", "cap"]) && D.sel === 2, J(names()));
D.btnDown.click(); D.btnDown.click();
check("↓ twice: to the end; at the bottom ↓ is grayed out", J(names()) === J(["#", "radius", "height", "cap", "count"]) && D.sel === 4
      && D.btnDown.disabled && !D.btnUp.disabled, J(names()));
D.select(0);
check("  first entry selected: ↑ grayed out; comments cannot be duplicated", D.btnUp.disabled && D.btnDup.disabled && !D.btnDel.disabled
      && (D.duplicate(), D.items.length === 5));
check("  comment entry: the right column has a single Text field", inp("text").value === "# ctl" && !inp("name"));
const rowEls = () => $$(".cols .col:nth-child(2) .it");
const drag = (from, to) => {
  fire(rowEls()[from], "dragstart");
  const over = new dom.window.Event("dragover", { bubbles: true, cancelable: true });
  rowEls()[to].dispatchEvent(over);
  const hl = rowEls()[to].classList.contains("over");
  fire(rowEls()[to], "drop");
  return { prevented: over.defaultPrevented, hl };
};
let dg = drag(4, 1);
check("drag to reorder: dragging the last entry onto entry 2 = inserting before it (drop target highlighted, dragover accepted)",
      J(names()) === J(["#", "count", "radius", "height", "cap"]) && D.sel === 1 && dg.prevented && dg.hl, J(names()));
dg = drag(1, 3);
check("  dragging downward: inserted before whichever it is dropped on", J(names()) === J(["#", "radius", "count", "height", "cap"]) && D.sel === 2, J(names()));
drag(2, 2);
check("  dropped onto itself: no change", J(names()) === J(["#", "radius", "count", "height", "cap"]));
fire(rowEls()[3], "dragover"); fire(rowEls()[3], "dragleave");
check("  dragged over then away: highlight removed", !rowEls()[3].classList.contains("over"));
D.reorder(-1, 2); D.reorder(1, 9);
check("  out of range: no change", J(names()) === J(["#", "radius", "count", "height", "cap"]));
rowEls()[4].click();
check("clicking a row: selects it", D.sel === 4 && inp("name").value === "cap");

sec("Dialog: comment lines, malformed lines");
D.select(0);
type("text", "float fromtext = 2");
check("turning a comment line into a valid declaration line: it becomes a parameter (a new one, no orig)", D.items[0].kind === "param"
      && D.items[0].name === "fromtext" && D.items[0].orig === undefined && rowsTxt()[0] === "fromtext(fromtext)Float");
D.close();
W(pn, "declare").value = "float ok = 1\nfloot bad = 1";
D = U.openDialog(pn, G);
check("a malformed line in the declaration: the dialog still opens, that line is red with a reason, cannot confirm", D.items[1].error.includes("floot")
      && D.btnAccept.disabled && D.msgEl.textContent.includes("entry 2"), D.msgEl.textContent);
D.select(1);
check("  selecting it: the right column says this line cannot be parsed, field outlined red", D.descEl.textContent.includes("cannot be parsed") && inp("text").classList.contains("bad"));
type("text", "floot stillbad");
check("  still malformed: the error remains (with the new reason)", D.items[1].error && D.btnAccept.disabled);
type("text", "# commented out for now");
check("  turned into a comment: the error is gone, can confirm", !D.items[1].error && !D.btnAccept.disabled);
D.close();
W(pn, "declare").value = "# ctl\nfloat radius = 1 : 0 10  # Radius\nint count = 5\nbool cap = true";
P.syncPanel(pn);

sec("Dialog: Apply / Accept / Cancel, keys");
W(pn, "values").value = J({ radius: 4, count: 8, cap: false });
D = U.openDialog(pn, G);
D.select(1); type("name", "rad"); type("max", "20");
D.select(2); D.remove();                                       // delete count
D.btnCancel.click();
check("Cancel: the dialog is gone, declaration / values / references untouched", !document.querySelector(".pcg-epi-mask")
      && W(pn, "declare").value.includes("float radius = 1 : 0 10") && tg.properties.pcg_bind.a === "radius");
D = U.openDialog(pn, G);
const D1 = D;
D = U.openDialog(pn, G);
check("opening another: the previous one closes automatically (only one open at a time)", document.querySelectorAll(".pcg-epi-mask").length === 1 && D !== D1);
D.select(1); type("name", "rad"); type("max", "20");
D.btnApply.click();
check("Apply: written, the dialog stays; the bottom says how many references were updated", !!document.querySelector(".pcg-epi-mask")
      && W(pn, "declare").value === "# ctl\nfloat rad = 1 : 0 20  # Radius\nint count = 5\nbool cap = true\n"
      && D.msgEl.textContent.includes("updated 2 references"), D.msgEl.textContent);
check("  references follow, values move over, controls grow (p_rad, range 0 ~ 20)", tg.properties.pcg_bind.a === "rad"
      && tg.properties.pcg_bind.b === `=ch("@${pn.id}/rad")+ch("@${pn.id}/count")`
      && JSON.parse(W(pn, "values").value).rad === 4 && W(pn, "p_rad")?.options.max === 20 && !W(pn, "p_radius")
      && W(tg, "a").value === 4 && W(tg, "b").value === 12, J([tg.properties.pcg_bind, W(tg, "a").value, W(tg, "b").value]));
check("  after Apply the reference count goes by the new names", rowsTxt()[1] === "Radius(rad)← 2Float", rowsTxt()[1]);
D.select(1); type("name", "R");
D.btnAccept.click();
check("Accept: written and closed; renaming after Apply also follows (rad → R)", !document.querySelector(".pcg-epi-mask")
      && W(pn, "declare").value.includes("float R = 1 : 0 20") && tg.properties.pcg_bind.a === "R");
D = U.openDialog(pn, G);
D.select(2);
check("parameters without Range checked: min / max are grayed out right when opened", inp("range").checked === false && inp("min").disabled && inp("max").disabled);
type("name", "1bad");
D.btnAccept.onclick();                                         // the button is grayed out; call the handler directly here
check("Accept with errors: does not close, does not write", !!document.querySelector(".pcg-epi-mask") && W(pn, "declare").value.includes("int count"));
let outer = 0;
const onDoc = () => { outer++; };
document.addEventListener("keydown", onDoc);
document.addEventListener("pointerdown", onDoc);
document.addEventListener("wheel", onDoc);
D.select(3);
const n0 = D.items.length;
key(inp("name"), "Delete");
check("pressing Delete in an input: deletes characters, not the entry; keys don't leak to the page (Delete on the canvas deletes nodes)", D.items.length === n0 && outer === 0);
key(D.listEl, "Delete");
check("  pressing Delete with focus outside an input: deletes the selected entry", D.items.length === n0 - 1 && outer === 0);
fire(D.mask, "pointerdown"); fire(D.mask, "wheel");
check("  clicks / wheel don't leak to the canvas either", outer === 0);
key(D.mask, "Escape");
check("Esc: cancel (nothing written)", !document.querySelector(".pcg-epi-mask") && W(pn, "declare").value.includes("bool cap"));
document.removeEventListener("keydown", onDoc);
document.removeEventListener("pointerdown", onDoc);
document.removeEventListener("wheel", onDoc);

sec("Dialog: empty panel, entry points");
const empty = mkPanel("", "EMPTY");
D = U.openDialog(empty, G);
check("empty panel: middle column empty, right column hints to add one first, nothing selected, three buttons grayed out", D.sel === -1 && D.descEl.textContent.includes("add the first parameter")
      && D.btnUp.disabled && D.btnDel.disabled && D.btnDup.disabled && D.msgEl.textContent === "0 parameters");
D.remove(); D.duplicate(); D.move(1);
check("  delete / duplicate / move with nothing selected: no throw", D.items.length === 0);
D.items.push({ kind: "raw", text: "# only" }); D.sel = -1; D.renderList();
D.remove();
check("  only a comment, nothing selected: delete leaves it alone (must not delete the last entry as if it were selected)", D.items.length === 1);
D.items.length = 0; D.renderList();
$('[data-type="float"]').click();
check("  adding the first one: it is entry 1", D.items.length === 1 && D.sel === 0 && D.items[0].name === "newparameter");
D.btnAccept.click();
check("  Accept: controls grow on the panel", W(empty, "declare").value === "float newparameter = 0\n" && !!W(empty, "p_newparameter"));
check("CSS injected only once", document.querySelectorAll("#pcg-epi-css").length === 1);

const ext = exts.find((e) => e.name === "pcg.paramui");
const NT = function () {}; NT.prototype.onNodeCreated = function () { this.created = true; };
NT.prototype.getExtraMenuOptions = function (c, o) { o.push({ content: "orig" }); };
await ext.beforeRegisterNodeDef(NT, { name: "PCG_Parameters" });
const inst = Object.assign(new NT(), mkNode("PCG_Parameters", [{ type: "text", name: "declare", value: "float q = 1" },
                                                               { type: "text", name: "values", value: "{}" }]));
inst.graph = G;
inst.onNodeCreated();
const btn = W(inst, "pcg_edit_ui");
check("entry point 1: a button on the node (the original onNodeCreated still called), not serialized, after declare / values",
      inst.created && btn?.type === "button" && btn.serialize === false && btn.options.serialize === false
      && inst.widgets.indexOf(btn) === 2 && btn.label.includes("Edit Parameter Interface"));
btn.callback();
check("  clicking the button: opens this node's dialog", document.querySelector(".pcg-epi .ttl div").textContent.includes("PCG_Parameters")
      && document.querySelectorAll(".pcg-epi-mask").length === 1);
document.querySelector(".pcg-epi-mask").remove();
const opts = [{ content: "other" }];
inst.getExtraMenuOptions({}, opts);
check("entry point 2: first item of the context menu (followed by a separator), the original menu items unchanged", opts[0].content.includes("Edit Parameter Interface")
      && opts[1] === null && opts[2].content === "other" && opts[opts.length - 1].content === "orig");
opts[0].callback();
check("  clicking it: opens", document.querySelectorAll(".pcg-epi-mask").length === 1);
document.querySelector(".pcg-epi-mask").remove();
const NT2 = function () {};
await ext.beforeRegisterNodeDef(NT2, { name: "PCG_Box" });
check("other node types: not hooked", NT2.prototype.onNodeCreated === undefined && NT2.prototype.getExtraMenuOptions === undefined);

console.log(`\n${OK.filter(Boolean).length}/${OK.length} passed`);
process.exit(OK.every(Boolean) ? 0 : 1);
