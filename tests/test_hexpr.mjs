// pcg91: expressions in parameter fields -- unit tests for web/pcg_hexpr.js (lexer / grammar / evaluation / path replacement).
//
// References that do not rely on the implementation itself:
//   precedence, associativity   computed by hand (-2^2 = -4, 2^3^2 = 512, 1+2*3 = 7 …)
//   trig functions              HScript uses degrees: sin(90) = 1, atan2(1,1) = 45
//   rand / shared functions     compared with the Expression (PCG) node (expr.py) **on the same inputs**: spawn a python3,
//                               call expr._rand / expr._FUNCS and compare one by one. If either side changes, this goes red
//   short-circuit evaluation    if(1, 2, 1/0) and 0 && 1/0 do not raise (the branch not chosen is not evaluated)
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
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), "jstest_hexpr_"));
fs.copyFileSync(path.join(PKG, "comfyui_pcg", "web", "pcg_hexpr.js"), path.join(TMP, "h.mjs"));
const H = await import(path.join(TMP, "h.mjs"));
fs.rmSync(TMP, { recursive: true, force: true });

const OK = [];
function check(name, cond, extra = "") {
  OK.push(!!cond);
  const tail = extra === "" ? "" : "   " + extra;
  console.log((cond ? "  PASS  " : "  FAIL  ") + name + tail);
}
function sec(t) { console.log("\n── " + t); }
const J = (x) => JSON.stringify(x);
const near = (a, b, e = 1e-12) => typeof a === "number" && Math.abs(a - b) <= e;
const ev = (t, ctx = {}) => H.evaluate(H.parse(t), ctx);
function err(name, t, frag, ctx = {}) {
  try { const v = ev(t, ctx); check(name, false, `no error raised, got ${v}`); }
  catch (e) {
    check(name, e instanceof H.ExprError && (!frag || e.message.includes(frag)), e.message);
  }
}

sec("Lexer");
const tk = H.tokenize(' ch("../a b/tx") * .5e1 ');
check("tokens carry source positions; number .5e1; strings have quotes stripped",
      J(tk.map((t) => [t.t, t.v, t.s, t.e])) === J([["id", "ch", 1, 3], ["op", "(", 3, 4],
        ["str", "../a b/tx", 4, 15], ["op", ")", 15, 16], ["op", "*", 17, 18],
        ["num", 5, 19, 23]]), J(tk.map((t) => [t.t, t.v, t.s, t.e])));
check("  \\\" and \\\\ escapes in strings; single quotes work too", H.tokenize(String.raw`"a\"b\\c" 'x'`).map((t) => t.v).join("|")
      === 'a"b\\c|x');
check("  ** recorded as ^", H.tokenize("2**3")[1].v === "^");
check("  $ variables", J(H.tokenize("$F+$FPS").map((t) => [t.t, t.v])) === J([["var", "F"], ["op", "+"], ["var", "FPS"]]));
err("  unrecognized character", "1 # 2", "unrecognized '#'");
err("  unterminated string", '"abc', "has no closing");
err("  $ without a name", "$ + 1", "$ must be followed by a variable name");

sec("Grammar / operators");
const cases = [
  ["1+2*3", 7], ["(1+2)*3", 9], ["-2^2", -4], ["2^3^2", 512], ["2**3", 8], ["10%3", 1],
  ["7/2", 3.5], ["1<2", 1], ["2<=2", 1], ["3>=4", 0], ["3>2", 1], ["1==1", 1], ["1!=1", 0],
  ["!0", 1], ["!3", 0], ["1&&0", 0], ["0||2", 1], ["2&&3", 1], ["- -3", 3], ["+4", 4],
  ["1-2-3", -4], ["8/4/2", 1], ["1+2 == 3", 1], ["1 < 2 == 1", 1], ["0 || 1 && 0", 0],
  ['"a"+1', "a1"], ['1+"2"', "12"], ['"a"=="a"', 1], ['"a"!="b"', 1], ['"x"+1.5', "x1.5"],
  ['"x"+1/3', "x0.333333"], ['!""', 1], ['"3" * 2', 6], ["1\t+\n2", 3], ["1 || 0 && 0", 1],
  ['"1.5" == 1.5', 1], ['"2" == 2.0', 1],
];
const bad = cases.filter(([t, v]) => { const g = ev(t); return !(typeof v === "number" ? near(g, v) : g === v); });
check(`all ${cases.length} operations correct (precedence, associativity, comparison, logic, string concatenation)`, !bad.length,
      J(bad.map(([t, v]) => [t, v, ev(t)])));
check("short-circuit: 0 && 1/0, 1 || 1/0 do not raise", ev("0 && 1/0") === 0 && ev("1 || 1/0") === 1);
check("  if(cond, then, else) evaluates only the chosen branch", ev("if(1, 2, 1/0)") === 2 && ev("if(0, 1/0, 3)") === 3
      && ev('if("", 1, 2)') === 2);
err("division by 0", "1/0", "division by 0");
err("modulo by 0", "1%0", "modulo");
err("extra token", "1 2", "unexpected extra");
err("unclosed parenthesis", "(1+2", "missing ')'");
err("empty", "  ", "empty");
err("incomplete", "1+", "incomplete");
err("operator in the wrong place", "*2", "'*' not expected");
err("string used as a number", '"abc" * 2', "is not a number");

sec("Functions");
const fcases = [
  ["sin(90)", 1], ["cos(180)", -1], ["tan(45)", 1], ["asin(1)", 90], ["acos(0)", 90],
  ["atan(1)", 45], ["atan2(1, 1)", 45], ["atan2(0, -1)", 180], ["rad(180)", Math.PI],
  ["deg($PI)", 180], ["deg(PI)", 180], ["2*pi", 2 * Math.PI], ["E", Math.E], ["$E", Math.E],
  ["fit(5, 0, 10, 0, 100)", 50], ["fit(20, 0, 10, 0, 100)", 100], ["fit(-1, 0, 10, 0, 100)", 0],
  ["fit(5, 10, 0, 0, 100)", 50], ["fit(3, 2, 2, 7, 9)", 7], ["fit01(0.25, 10, 20)", 12.5],
  ["fit10(0.25, 0, 100)", 75], ["fit11(0, 0, 10)", 5], ["clamp(15, 0, 10)", 10],
  ["clamp(5, 10, 0)", 5], ["clamp(-3, 0, 10)", 0], ["lerp(2, 4, 0.25)", 2.5],
  ["rint(2.5)", 3], ["rint(-2.5)", -3], ["round(2.4)", 2], ["int(-2.7)", -2], ["trunc(2.7)", 2],
  ["frac(-0.25)", 0.75], ["sign(-3)", -1], ["abs(-2)", 2], ["floor(-1.5)", -2], ["ceil(1.2)", 2],
  ["min(3, 1, 2)", 1], ["max(3, 1, 2)", 3], ["hypot(3, 4)", 5], ["pow(2, 10)", 1024],
  ["sqrt(9)", 3], ["exp(0)", 1], ["log(E)", 1], ["log10(1000)", 3], ["sinh(0)", 0],
  ["cosh(0)", 1], ["tanh(0)", 0], ['strlen("abc")', 3], ["strlen(12.5)", 4],
];
const fbad = fcases.filter(([t, v]) => !near(ev(t), v, 1e-9));
check(`all ${fcases.length} function values correct (trig in degrees, as in HScript)`, !fbad.length,
      J(fbad.map(([t, v]) => [t, v, ev(t)])));
err("nonexistent function", "foo(1)", "no function foo()");
err("wrong argument count", "fit(1, 2)", "takes 5 arguments");
err("  at-least-N ones", "min()", "at least 1");
err("  ranged ones", "hypot(1, 2, 3, 4, 5, 6) + atan2(1)", "takes 2 arguments");
err("  too many given", "fit(1, 2, 3, 4, 5, 6)", "takes 5 arguments");
err("  too many given (two-argument one)", "atan2(1, 2, 3)", "takes 2 arguments");
err("sqrt of a negative", "sqrt(-1)", "negative number");
err("log 0", "log(0)", "is not positive");
err("log10 of a negative", "log10(-1)", "is not positive");
err("result is not a finite number", "exp(1000)", "not evaluate to a finite number");
err("if argument count", "if(1, 2)", "3 arguments");
err("strlen argument count", "strlen()", "1 argument");
err("unrecognized name (forgot the $ on a variable)", "F + 1", "need a $");

sec("Variables / ch()");
const seen = [];
const ctx = {
  vars: (n) => ({ F: 12, T: 0.5, OS: "box1" })[n],
  ch: (p, s) => { seen.push([p, s]); return s ? "txt" : 3; },
};
check("$F $T $OS come from the context", ev("$F*2 + $T", ctx) === 24.5 && ev("$OS", ctx) === "box1");
check("  $PI / $E work without a context", near(ev("$PI"), Math.PI) && near(ev("$E"), Math.E));
err("  unknown variable", "$NOPE", "unknown variable $NOPE", ctx);
check("ch / chf want numbers, chs wants a string; the path is passed to the context as is",
      ev('ch("../a/tx") + chf("ty")', ctx) === 6 && ev('chs("../b/s")', ctx) === "txt"
      && J(seen) === J([["../a/tx", false], ["ty", false], ["../b/s", true]]), J(seen));
check("  the path can be a computed string", (seen.length = 0, ev('ch("../a/" + "tx")', ctx)) === 3
      && seen[0][0] === "../a/tx");
err("  ch argument not a string", "ch(1)", "string path", ctx);
err("  ch argument count", 'ch("a", "b")', "1 argument", ctx);
err("  no ch in the context", 'ch("a")', "ch() cannot be used");

sec("Plain numbers / path replacement");
const plain = ["1", "-2.5", "+3", ".5", "1e3", "2E-2", " 7 "];
const notPlain = ["", "1+1", "2*pi", "1e", "abc", "1.2.3", "$F"];
check("plain numbers (typing one replaces the expression)", plain.every(H.isPlainNumber) && !notPlain.some(H.isPlainNumber),
      J([plain.filter((x) => !H.isPlainNumber(x)), notPlain.filter(H.isPlainNumber)]));
const m1 = H.mapChPaths('ch( "../a/tx" )*2 + chs("s") + max(ch("../a/tx"),1)',
                        (p) => (p === "../a/tx" ? "@7/tx" : null));
check("mapChPaths: only replaces paths written directly in ch/chs, other text (spaces, parentheses) verbatim",
      m1 === 'ch( "@7/tx" )*2 + chs("s") + max(ch("@7/tx"),1)', m1);
check("  computed paths are not replaced (they can't be)", H.mapChPaths('ch("../a/" + "tx")', () => "X") === 'ch("../a/" + "tx")');
check("  replaced paths containing quotes / backslashes are escaped correctly", H.mapChPaths('ch("a")', () => 'q"\\')
      === 'ch("q\\"\\\\")' && ev(H.mapChPaths('chs("a")', () => 'q"\\'),
                                  { ch: (p) => p }) === 'q"\\');
check("  text that fails lexing is returned as is", H.mapChPaths('ch("a" # ', () => "X") === 'ch("a" # ');
check("  replacements identical to the original are left alone (single-quote spelling kept)", H.mapChPaths("ch('x') + chs('y')", (p) => p)
      === "ch('x') + chs('y')");
check("  strings in functions outside the ch family are not touched", H.mapChPaths('strlen("../a/tx")', () => "X")
      === 'strlen("../a/tx")');

sec("Same rand / same functions as the Expression (PCG) node (checked against python)");
const seeds = [0, 1, 7, 42, 12345, 2147483647, 2147483648, -1, 3.7];
const shared = [["fit", [5, 0, 10, 0, 100]], ["fit", [20, 0, 10, 0, 100]], ["fit", [5, 10, 0, 0, 1]],
                ["fit01", [0.3, 2, 4]], ["clamp", [15, 0, 10]], ["clamp", [-1, 0, 10]],
                ["lerp", [1, 5, 0.25]], ["min", [3, 1, 2]], ["max", [3, 1, 2]], ["abs", [-2.5]],
                ["floor", [-1.5]], ["ceil", [1.2]], ["frac", [-0.25]], ["sign", [-3]], ["sign", [0]],
                ["pow", [2, 0.5]], ["sqrt", [2]], ["exp", [1.5]], ["log", [7]]];
const py = `
import json, sys
sys.path.insert(0, ${J(PKG)}); sys.path.insert(0, ${J(_HERE)})
import fakecomfy  # noqa
from comfyui_pcg import expr
seeds = ${J(seeds)}; shared = ${J(shared)}
print(json.dumps({"rand": [expr._rand(s) for s in seeds],
                  "f": [float(expr._FUNCS[n](*a)) for n, a in shared]}))
`;
const r = spawnSync("python3", ["-c", py], { encoding: "utf-8", cwd: _HERE });
let P = null;
try { P = JSON.parse(r.stdout.trim().split("\n").pop()); } catch (_) { /* */ }
check("python side started", !!P, (r.stderr || "").slice(-200));
if (P) {
  const js = seeds.map((s) => H.rand(s));
  check(`rand(seed): ${seeds.length} seeds (incl. 2^31, negatives, fractions) bit-identical to the Expression node`,
        J(js) === J(P.rand), J([js, P.rand]));
  const fj = shared.map(([n, a]) => H.FUNCS[n][2](...a));
  const diff = shared.filter((_, i) => !near(fj[i], P.f[i], 1e-15));
  check(`  ${shared.length} shared functions give the same values as the Expression node`, !diff.length, J(diff));
  check("  trig functions are the only deliberate difference: degrees in fields (HScript), radians in the Expression node (Python)",
        near(H.FUNCS.sin[2](90), 1) && near(H.FUNCS.sin[2](Math.PI / 2), Math.sin(Math.PI / 180 * Math.PI / 2)));
}

sec("pcg93: chf(path, frame), padzero, caller-provided functions, D_ constants");
{
  const got = [];
  const c2 = { ch: (p, s, f) => { got.push([p, s, f]); return 5; },
               funcs: { npoints: (p) => (p === "../a" ? 8 : 0), opname: (p = ".") => "me:" + p } };
  check("chf(path, frame): the frame is passed to the context; chf(path) is the current frame", ev('chf("tx", 12) + chf("ty")', c2) === 10
        && J(got) === J([["tx", false, 12], ["ty", false, undefined]]), J(got));
  err("  chf with three arguments", 'chf("a", 1, 2)', "1-2 arguments", c2);
  check("padzero: padzero(4, 7) = 0007; negative -05; no truncation when the width is too small", ev("padzero(4, 7)") === "0007"
        && ev("padzero(3, -5)") === "-05" && ev("padzero(2, 12345)") === "12345" && ev("padzero(3, 2.9)") === "002");
  err("  padzero argument count", "padzero(3)", "2 arguments");
  check("caller-provided functions (npoints / opname): arguments passed through as is", ev('npoints("../a") * 2', c2) === 16
        && ev("opname()", c2) === "me:.");
  err("  not provided means no such function", 'npoints("../a")', "no function npoints()");
  err("  names on the prototype chain (constructor / toString) don't count as caller-provided functions", "constructor(1) + toString()",
      "no function", { funcs: {} });
  check("D_XMIN … D_ZSIZE, D_X / D_Y / D_Z are constants (for bbox / centroid)",
        J(["D_XMIN", "D_XMAX", "D_YMIN", "D_YMAX", "D_ZMIN", "D_ZMAX", "D_XSIZE", "D_YSIZE", "D_ZSIZE",
           "D_X", "D_Y", "D_Z"].map((n) => ev(n))) === J([0, 1, 2, 3, 4, 5, 6, 7, 8, 0, 1, 2]));
  const m2 = H.mapChPaths('npoints("../a") + bbox( "../a" , D_XMAX) + point("../a", 0, "P", 1) + strlen("../a")',
                          (p, f) => (f === "strlen" ? "X" : `<${f}:${p}>`));
  check("mapChPaths: node-path functions are replaced too (a comma after the first argument is fine), the function name is passed to fn as well",
        m2 === 'npoints("<npoints:../a>") + bbox( "<bbox:../a>" , D_XMAX) + point("<point:../a>", 0, "P", 1) + strlen("../a")', m2);
}

sec("pcg93: string fields (backticks + $variables)");
{
  const vars = (n) => ({ F: 7, OS: "box1", T: 0.5 })[n];
  const ctx = { vars, expr: (src) => H.evaluate(H.parse(src), { vars }) };
  const ex = (t) => H.expandTemplate(t, ctx);
  check("$F4 zero padding, ${OS}, backtick expressions, concatenated", ex("render/${OS}_$F4.`$F*2`.png") === "render/box1_0007.14.png",
        ex("render/${OS}_$F4.`$F*2`.png"));
  check("  $F is not padded; $F1 is also 7; fractions to 6 digits", ex("$F|$F1|`1/3`") === "7|7|0.333333", ex("$F|$F1|`1/3`"));
  check("  negative frames padded: ${F4} at frame −7 = -007 (same as padzero)",
        H.expandTemplate("${F4}", { vars: (n) => (n === "F" ? -7 : undefined) }) === "-007");
  check("  $F4_x is a variable named F4_x (as in Houdini, the underscore is part of the name); write ${F4}_x",
        ex("$F4_x") === "$F4_x" && ex("${F4}_x") === "0007_x" && ex("$F4.png") === "0007.png");
  check("  unknown $names are left as is (things like $HIP)", ex("$HIP/x_$NOPE") === "$HIP/x_$NOPE");
  check("  $OS_frame is a variable named OS_frame (unknown, left as is); write it separated as ${OS}_frame",
        ex("$OS_frame") === "$OS_frame" && ex("${OS}_frame") === "box1_frame");
  check("  \\` \\$ \\\\ escape to literals", ex("a\\`b\\$F\\\\c") === "a`b$F\\c", ex("a\\`b\\$F\\\\c"));
  check("  \\` inside backticks is a literal backtick", ex('`strlen("a\\`b")`') === "3");
  check("  plain text verbatim (no $ and no backticks)", ex("just text 100%") === "just text 100%");
  let msg = "";
  try { ex("a `1+"); } catch (e) { msg = e.message; }
  check("  unterminated backtick: error", msg.includes("unterminated backtick"), msg);
  msg = "";
  try { ex("`1/0`"); } catch (e) { msg = e.message; }
  check("  error in a backtick expression: the error is still thrown", msg.includes("division by 0"), msg);
  check("isTemplate: only with backticks or $variables; an unterminated backtick counts too (so it turns red)",
        !H.isTemplate("plain/path.png") && !H.isTemplate("100$") && !H.isTemplate("a \\$F")
        && H.isTemplate("a$F") && H.isTemplate("`1`") && H.isTemplate("x `") && H.isTemplate("${OS}"));
  const mt = H.mapTemplatePaths('pre `chs("../a/s")`_`ch("../a/t")+1` $F', (p) => "@" + p);
  check("mapTemplatePaths: only replaces ch-family paths inside backticks, outside text verbatim",
        mt === 'pre `chs("@../a/s")`_`ch("@../a/t")+1` $F', mt);
  check("  invalid template: returned as is", H.mapTemplatePaths("a `x", () => "Q") === "a `x");
  check("  escaped backtick inside backticks: left alone (positions would not line up)",
        H.mapTemplatePaths('`ch("a")+strlen("\\`")`', () => "Q") === '`ch("a")+strlen("\\`")`');
}

sec("pcg93: keyframe evaluation (pcg_chan.js) matches the Channel (PCG) node frame by frame (checked against python)");
{
  const TMPC = fs.mkdtempSync(path.join(os.tmpdir(), "jstest_chan_"));
  fs.copyFileSync(path.join(PKG, "comfyui_pcg", "web", "pcg_chan.js"), path.join(TMPC, "c.mjs"));
  const C = await import(path.join(TMPC, "c.mjs"));
  fs.rmSync(TMPC, { recursive: true, force: true });
  const specs = ["0:0  12:1.5:ease  18:1.5  24:0", "0:0 10:1:constant 20:1", "0:0@0 12:1 24:0@0",
                 "0:0:ease 10:10", "0:0:constant 10:5", "0:0:easeout 6:3:cubic 12:-2",
                 "3:2 7:5:linear 11:-1:quintic 20:4:easein 25:1:easeout", "5:3", "0:1 4:2", "10:0 0:5 10:7",
                 "0:0 1:1 3:0 6:4 10:-2"];
  const exs = C.EXTRAPS;
  const xs = [-30.5, -1, 0, 0.5, 3, 7.25, 10, 12, 18, 23.9, 24, 40, 61.3];
  const js = [];
  for (const sp of specs) for (const e of exs) for (const x of xs) js.push(C.evalKeys(C.parseKeys(sp), x, e));
  const pyc = `
import json, sys
sys.path.insert(0, ${J(PKG)}); sys.path.insert(0, ${J(_HERE)})
import fakecomfy  # noqa
from comfyui_pcg.geo import channel as C
print(json.dumps([C.value_at(s, x, "cubic", e) for s in ${J(specs)} for e in ${J(exs)} for x in ${J(xs)}]))
`;
  const rc = spawnSync("python3", ["-c", pyc], { encoding: "utf-8", cwd: _HERE });
  let PC = null;
  try { PC = JSON.parse(rc.stdout.trim().split("\n").pop()); } catch (_) { /* */ }
  const worst = PC ? Math.max(...js.map((v, i) => Math.abs(v - PC[i]))) : NaN;
  check(`${specs.length} channels × ${exs.length} out-of-range modes × ${xs.length} frames = ${js.length} values, differing from channel.value_at by ≤ 1e-12`,
        PC && PC.length === js.length && worst <= 1e-12, `max diff ${worst}  ${(rc.stderr || "").slice(-150)}`);
  check("  same frame written twice: the later one wins (same as channel.py)", C.evalKeys(C.parseKeys("10:0 0:5 10:7"), 10) === 7);
  check("formatKeys ↔ parseKeys round trip (default cubic not written; other interpolations and @slope written)",
        C.formatKeys(C.parseKeys("0:0  12:1.5:ease  18:1.5@0  24:0:linear"))
        === "0:0  12:1.5:ease  18:1.5@0  24:0:linear");
  let em = "";
  try { C.parseKeys("0:0 5:x"); } catch (e) { em = e.message; }
  check("  malformed channel raises", em.includes("is not a number"), em);
}

console.log(`\n${OK.filter(Boolean).length}/${OK.length} passed`);
process.exit(OK.every(Boolean) ? 0 : 1);
