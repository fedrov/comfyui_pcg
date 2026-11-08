// comfyui_pcg/web/pcg_hexpr.js
//
// Expressions in parameter fields -- the equivalent of HScript expressions in Houdini parameters.
//
// Type `ch("../grid1/rows") * 2 + 1`, `sin($F * 10)`, `fit($T, 0, 2, 0, 360)` into a numeric field on the panel,
// and the field **stores this expression** (cyan); the value is computed by the frontend and written into the widget (the same "frontend materialization"
// route as parameter references, see pcg_params.js). Typing a plain number replaces the expression. A malformed one turns the field red and leaves the value alone.
//
// ━━ Why a hand-written parser instead of Function / eval
// Expressions are stored in the workflow and get shared along with the project. Evaluating with JS eval would let a json file run
// arbitrary code in the browser of whoever opens it. Only what is listed below is accepted; everything else is an error.
//
// ━━ Syntax (the HScript set)
//   numbers 1  1.5  .5  2e-3      strings "..." or '...' (\" \\ escapes)
//   + - * / %  ^ (power, ** accepted too)  == != < > <= >=  && || !  parentheses   function calls f(a, b)
//   comparisons / logic give 1 or 0; string + anything = concatenation (same as HScript)
//   -2^2 = -4 (power binds tighter than unary minus, as in math notation); power is right-associative: 2^3^2 = 512
//
// ━━ Variables
//   $F $FF  current frame (timeline = the Frame (PCG) node in the graph; 0 without one)
//   $T      seconds = (frame − start frame) / fps          $FPS $FSTART $FEND $NFRAMES
//   $PI $E  constants (PI / E without $ accepted too)       $OS  this node's title (string)
//
// ━━ Functions (same names and meaning as HScript; **trig functions use degrees**, as in HScript -- the Wrangle / Expression
//    nodes use radians, since those follow VEX / Python; Houdini itself splits it the same way)
//   ch(path) chf(path) chs(path)   read a parameter (paths see pcg_params.js: "tx" this node, "../title/tx" another node)
//   if(cond, then, else)   only the chosen branch is evaluated
//   abs ceil floor rint round int trunc frac sign min max clamp fit fit01 fit10 fit11 lerp
//   pow sqrt exp log log10 sin cos tan asin acos atan atan2 sinh cosh tanh rad deg hypot
//   rand(seed)  deterministic 0-1 random, the same number as the Expression (PCG) node's rand (Python's MT19937)
//   strlen(s)   string length          padzero(width, n)  zero padding: padzero(4, 7) = "0007"
//   chf(path, frame)  that parameter's value at another frame (only differs for keyframes / expressions using $F)
//   opname(path) opinputpath(path, input index), and the geometry-reading family npoints / bbox / point …:
//                provided by the caller via ctx.funcs (pcg_params.js); this file only handles syntax
//
// ━━ String fields (expandTemplate): text verbatim, `expression` evaluated and spliced in, $F / ${F} replaced by variables,
//    $F4 = frame number zero-padded to 4 digits; \` \$ \\ escapes; unknown $names are left as is (same as Houdini)

export class ExprError extends Error {}
/** The required data is still on its way (geometry queries): not an error, the field does not turn red, it re-evaluates once fetched. */
export class ExprPending extends ExprError {}

// ════════════════════════════════════════════════════ Lexer
const OPS = ["**", "==", "!=", "<=", ">=", "&&", "||", "+", "-", "*", "/", "%", "^",
             "<", ">", "!", "(", ")", ","];

/** text -> token list. Each token carries its [s, e) in the source (needed for positional replacement when canonicalizing paths). */
export function tokenize(text) {
  const s = String(text);
  const out = [];
  let i = 0;
  while (i < s.length) {
    const c = s[i];
    if (/\s/.test(c)) { i++; continue; }
    const st = i;
    if (/[0-9.]/.test(c)) {
      const m = /^(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?/.exec(s.slice(i));
      if (!m) throw new ExprError(`character ${i + 1}: '${c}' is not a number`);
      i += m[0].length;
      out.push({ t: "num", v: Number(m[0]), s: st, e: i });
      continue;
    }
    if (c === '"' || c === "'") {
      let v = "";
      i++;
      while (i < s.length && s[i] !== c) {
        if (s[i] === "\\" && i + 1 < s.length) { v += s[i + 1]; i += 2; continue; }
        v += s[i++];
      }
      if (i >= s.length) throw new ExprError(`string starting at character ${st + 1} has no closing ${c}`);
      i++;
      out.push({ t: "str", v, q: c, s: st, e: i });
      continue;
    }
    if (c === "$") {
      const m = /^\$[A-Za-z_][A-Za-z0-9_]*/.exec(s.slice(i));
      if (!m) throw new ExprError(`character ${i + 1}: $ must be followed by a variable name`);
      i += m[0].length;
      out.push({ t: "var", v: m[0].slice(1), s: st, e: i });
      continue;
    }
    if (/[A-Za-z_]/.test(c)) {
      const m = /^[A-Za-z_][A-Za-z0-9_]*/.exec(s.slice(i));
      i += m[0].length;
      out.push({ t: "id", v: m[0], s: st, e: i });
      continue;
    }
    const op = OPS.find((o) => s.startsWith(o, i));
    if (!op) throw new ExprError(`character ${i + 1}: unrecognized '${c}'`);
    i += op.length;
    out.push({ t: "op", v: op === "**" ? "^" : op, s: st, e: i });
  }
  return out;
}

// ════════════════════════════════════════════════════ Grammar (recursive descent)
const LEVELS = [["||"], ["&&"], ["==", "!="], ["<", ">", "<=", ">="], ["+", "-"],
                ["*", "/", "%"]];

/** text -> AST. Syntax errors throw ExprError. */
export function parse(text) {
  const toks = tokenize(text);
  if (!toks.length) throw new ExprError("expression is empty");
  let p = 0;
  const peek = () => toks[p];
  const isOp = (v) => peek()?.t === "op" && peek().v === v;
  const expect = (v) => {
    if (!isOp(v)) {
      const t = peek();
      throw new ExprError(t ? `character ${t.s + 1}: expected '${v}' here` : `missing '${v}' at the end`);
    }
    p++;
  };
  const level = (k) => {
    if (k >= LEVELS.length) return unary();
    let a = level(k + 1);
    while (peek()?.t === "op" && LEVELS[k].includes(peek().v)) {
      const op = toks[p++].v;
      a = { k: "bin", op, a, b: level(k + 1) };
    }
    return a;
  };
  const unary = () => {
    if (isOp("-") || isOp("+") || isOp("!")) {
      const op = toks[p++].v;
      return { k: "un", op, a: unary() };
    }
    return power();
  };
  const power = () => {
    const a = primary();
    if (isOp("^")) { p++; return { k: "bin", op: "^", a, b: unary() }; }   // right-associative
    return a;
  };
  const primary = () => {
    const t = toks[p];
    if (!t) throw new ExprError("expression is incomplete");
    if (t.t === "num") { p++; return { k: "num", v: t.v }; }
    if (t.t === "str") { p++; return { k: "str", v: t.v, tok: t }; }
    if (t.t === "var") { p++; return { k: "var", name: t.v }; }
    if (t.t === "id") {
      p++;
      if (isOp("(")) {
        p++;
        const args = [];
        if (!isOp(")")) {
          args.push(level(0));
          while (isOp(",")) { p++; args.push(level(0)); }
        }
        expect(")");
        return { k: "call", name: t.v, args };
      }
      return { k: "id", name: t.v };
    }
    if (t.t === "op" && t.v === "(") {
      p++;
      const a = level(0);
      expect(")");
      return a;
    }
    throw new ExprError(`character ${t.s + 1}: '${t.v}' not expected here`);
  };
  const ast = level(0);
  if (p < toks.length) throw new ExprError(`character ${toks[p].s + 1}: unexpected extra '${toks[p].v}'`);
  return ast;
}

/** A plain number (typing it means "replace the expression with this value"). "2*3" does not count -- that is an expression, kept as in Houdini. */
export function isPlainNumber(text) {
  const s = String(text).trim();
  return s !== "" && /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/.test(s);
}

// ════════════════════════════════════════════════════ rand: the same number as Python's random.Random(seed)
// The Expression (PCG) node's rand(seed) is random.Random(seed & 0x7FFFFFFF).random(). rand in fields
// must give the same number, otherwise "the same function gives different results in two places". Python's Random is MT19937,
// an int seed goes through init_by_array([seed]), and random() is genrand_res53.
function mtRandom(seed) {
  const N = 624, mt = new Uint32Array(N);
  const mul = (a, b) => (Math.imul(a, b) >>> 0);
  mt[0] = 19650218;
  for (let i = 1; i < N; i++)
    mt[i] = (mul(1812433253, (mt[i - 1] ^ (mt[i - 1] >>> 30)) >>> 0) + i) >>> 0;
  const key = [seed >>> 0];
  let i = 1, j = 0;
  for (let k = Math.max(N, key.length); k > 0; k--) {
    mt[i] = ((mt[i] ^ mul(mt[i - 1] ^ (mt[i - 1] >>> 30), 1664525)) + key[j] + j) >>> 0;
    i++; j++;
    if (i >= N) { mt[0] = mt[N - 1]; i = 1; }
    if (j >= key.length) j = 0;
  }
  for (let k = N - 1; k > 0; k--) {
    mt[i] = ((mt[i] ^ mul(mt[i - 1] ^ (mt[i - 1] >>> 30), 1566083941)) - i) >>> 0;
    i++;
    if (i >= N) { mt[0] = mt[N - 1]; i = 1; }
  }
  mt[0] = 0x80000000;
  let idx = N;
  const next = () => {
    if (idx >= N) {
      for (let k = 0; k < N; k++) {
        const y = (mt[k] & 0x80000000) | (mt[(k + 1) % N] & 0x7fffffff);
        mt[k] = (mt[(k + 397) % N] ^ (y >>> 1) ^ (y & 1 ? 0x9908b0df : 0)) >>> 0;
      }
      idx = 0;
    }
    let y = mt[idx++];
    y ^= y >>> 11;
    y = (y ^ ((y << 7) & 0x9d2c5680)) >>> 0;
    y = (y ^ ((y << 15) & 0xefc60000)) >>> 0;
    y ^= y >>> 18;
    return y >>> 0;
  };
  const a = next() >>> 5, b = next() >>> 6;
  return (a * 67108864 + b) / 9007199254740992;
}

export function rand(seed) {
  return mtRandom(Math.trunc(Number(seed)) & 0x7fffffff);
}

// ════════════════════════════════════════════════════ Function table
const D2R = Math.PI / 180;
const num = (name) => (x) => {
  if (typeof x === "number") return x;
  const v = Number(x);
  if (String(x).trim() === "" || !Number.isFinite(v))
    throw new ExprError(`${name}(): '${x}' is not a number`);
  return v;
};
const clamp = (x, a, b) => Math.min(Math.max(x, Math.min(a, b)), Math.max(a, b));
const fit = (x, a, b, c, d) => (b === a ? c : c + (clamp(x, a, b) - a) / (b - a) * (d - c));
const rint = (x) => Math.sign(x) * Math.round(Math.abs(x));   // halves round away from 0

// [min arg count, max (-1 = unlimited), implementation]. Implementations receive arguments already converted to numbers
export const FUNCS = {
  abs: [1, 1, Math.abs], ceil: [1, 1, Math.ceil], floor: [1, 1, Math.floor],
  rint: [1, 1, rint], round: [1, 1, rint],
  int: [1, 1, Math.trunc], trunc: [1, 1, Math.trunc],
  frac: [1, 1, (x) => x - Math.floor(x)], sign: [1, 1, (x) => Math.sign(x)],
  min: [1, -1, Math.min], max: [1, -1, Math.max], clamp: [3, 3, clamp],
  fit: [5, 5, fit], fit01: [3, 3, (x, c, d) => fit(x, 0, 1, c, d)],
  fit10: [3, 3, (x, c, d) => fit(x, 1, 0, c, d)],
  fit11: [3, 3, (x, c, d) => fit(x, -1, 1, c, d)],
  lerp: [3, 3, (a, b, t) => a + (b - a) * t],
  pow: [2, 2, Math.pow], sqrt: [1, 1, (x) => {
    if (x < 0) throw new ExprError(`sqrt(): negative number ${x}`);
    return Math.sqrt(x);
  }],
  exp: [1, 1, Math.exp],
  log: [1, 1, (x) => { if (x <= 0) throw new ExprError(`log(): ${x} is not positive`); return Math.log(x); }],
  log10: [1, 1, (x) => { if (x <= 0) throw new ExprError(`log10(): ${x} is not positive`); return Math.log10(x); }],
  sin: [1, 1, (x) => Math.sin(x * D2R)], cos: [1, 1, (x) => Math.cos(x * D2R)],
  tan: [1, 1, (x) => Math.tan(x * D2R)],
  asin: [1, 1, (x) => Math.asin(x) / D2R], acos: [1, 1, (x) => Math.acos(x) / D2R],
  atan: [1, 1, (x) => Math.atan(x) / D2R], atan2: [2, 2, (y, x) => Math.atan2(y, x) / D2R],
  sinh: [1, 1, Math.sinh], cosh: [1, 1, Math.cosh], tanh: [1, 1, Math.tanh],
  rad: [1, 1, (x) => x * D2R], deg: [1, 1, (x) => x / D2R],
  hypot: [2, -1, Math.hypot],
  rand: [1, 1, rand],
};
// Lowercase pi: before pcg91 you could type "2*pi" into a field (evaluated on the spot); people who wrote that can still use it.
// D_*: constants HScript uses for bbox() / centroid()
const CONSTS = { PI: Math.PI, E: Math.E, pi: Math.PI,
                 D_XMIN: 0, D_XMAX: 1, D_YMIN: 2, D_YMAX: 3, D_ZMIN: 4, D_ZMAX: 5,
                 D_XSIZE: 6, D_YSIZE: 7, D_ZSIZE: 8, D_X: 0, D_Y: 1, D_Z: 2 };

// ════════════════════════════════════════════════════ Evaluation
/**
 * ast + context -> value (number or string). Throws ExprError on failure.
 *
 * ctx = {
 *   vars(name)        $ variable -> value; returns undefined when unknown
 *   ch(path, str)     read a parameter; str = want a string (chs). Throws its own ExprError on failure
 * }
 */
export function evaluate(ast, ctx = {}) {
  const ev = (n) => {
    switch (n.k) {
      case "num": return n.v;
      case "str": return n.v;
      case "id": {
        if (n.name in CONSTS) return CONSTS[n.name];
        throw new ExprError(`unrecognized '${n.name}' (variables need a $, e.g. $F)`);
      }
      case "var": {
        if (n.name === "PI") return Math.PI;
        if (n.name === "E") return Math.E;
        const v = ctx.vars?.(n.name);
        if (v === undefined) throw new ExprError(`unknown variable $${n.name}`);
        return v;
      }
      case "un": {
        const a = ev(n.a);
        if (n.op === "!") return truthy(a) ? 0 : 1;
        const x = num("-")(a);
        return n.op === "-" ? -x : x;
      }
      case "bin": return bin(n);
      case "call": return call(n);
      default: throw new ExprError("internal error: unknown node");
    }
  };
  const truthy = (v) => (typeof v === "string" ? v !== "" : v !== 0);
  const bin = (n) => {
    if (n.op === "&&") return truthy(ev(n.a)) && truthy(ev(n.b)) ? 1 : 0;
    if (n.op === "||") return truthy(ev(n.a)) || truthy(ev(n.b)) ? 1 : 0;
    const a = ev(n.a), b = ev(n.b);
    if (n.op === "+" && (typeof a === "string" || typeof b === "string"))
      return fmtStr(a) + fmtStr(b);
    if (n.op === "==" || n.op === "!=") {
      const eq = (typeof a === "string" || typeof b === "string")
        ? fmtStr(a) === fmtStr(b) : a === b;
      return (n.op === "==") === eq ? 1 : 0;
    }
    const x = num(n.op)(a), y = num(n.op)(b);
    switch (n.op) {
      case "+": return x + y;
      case "-": return x - y;
      case "*": return x * y;
      case "/":
        if (y === 0) throw new ExprError("division by 0");
        return x / y;
      case "%":
        if (y === 0) throw new ExprError("modulo by 0");
        return x % y;
      case "^": return Math.pow(x, y);
      case "<": return x < y ? 1 : 0;
      case ">": return x > y ? 1 : 0;
      case "<=": return x <= y ? 1 : 0;
      case ">=": return x >= y ? 1 : 0;
      default: throw new ExprError(`internal error: operator ${n.op}`);
    }
  };
  const call = (n) => {
    const name = n.name;
    if (name === "if") {
      if (n.args.length !== 3) throw new ExprError("if() takes 3 arguments: if(cond, then, else)");
      return truthy(ev(n.args[0])) ? ev(n.args[1]) : ev(n.args[2]);
    }
    if (name === "ch" || name === "chf" || name === "chs") {
      const most = name === "chf" ? 2 : 1;
      if (n.args.length < 1 || n.args.length > most)
        throw new ExprError(name === "chf" ? "chf() takes 1-2 arguments: parameter path[, frame]"
                                           : `${name}() takes 1 argument: parameter path`);
      const path = ev(n.args[0]);
      if (typeof path !== "string") throw new ExprError(`the argument of ${name}() must be a string path`);
      if (!ctx.ch) throw new ExprError(`${name}() cannot be used here`);
      if (n.args.length === 2) return ctx.ch(path, false, num("chf")(ev(n.args[1])));
      return ctx.ch(path, name === "chs");
    }
    if (name === "padzero") {
      if (n.args.length !== 2) throw new ExprError("padzero() takes 2 arguments: padzero(width, n)");
      const w = Math.trunc(num(name)(ev(n.args[0]))), v = Math.trunc(num(name)(ev(n.args[1])));
      return (v < 0 ? "-" : "") + String(Math.abs(v)).padStart(Math.max(0, w - (v < 0 ? 1 : 0)), "0");
    }
    if (ctx.funcs && Object.prototype.hasOwnProperty.call(ctx.funcs, name))
      return ctx.funcs[name](...n.args.map(ev));
    if (name === "strlen") {
      if (n.args.length !== 1) throw new ExprError("strlen() takes 1 argument");
      return fmtStr(ev(n.args[0])).length;
    }
    const f = Object.prototype.hasOwnProperty.call(FUNCS, name) ? FUNCS[name] : null;
    if (!f) throw new ExprError(`no function ${name}()`);       // names on the prototype like constructor / toString count as missing too
    const [lo, hi, impl] = f;
    if (n.args.length < lo || (hi >= 0 && n.args.length > hi))
      throw new ExprError(`${name}() takes ${hi === lo ? lo : hi < 0 ? `at least ${lo}` : `${lo}-${hi}`} arguments, `
                          + `got ${n.args.length}`);
    const v = impl(...n.args.map((a) => num(name)(ev(a))));
    if (typeof v === "number" && !Number.isFinite(v))
      throw new ExprError(`${name}() did not evaluate to a finite number`);
    return v;
  };
  return ev(ast);
}

/** How numbers are written in string concatenation: integers without a decimal point, others at most 6 digits (matches the panel display). */
export function fmtStr(v) {
  if (typeof v !== "number") return String(v);
  if (Number.isInteger(v)) return String(v);
  return String(Math.round(v * 1e6) / 1e6);
}

// Functions whose first argument is a path: parameter paths (the ch family) and node paths (geometry queries, names)
export const PATH_FUNCS = new Set(["ch", "chf", "chs", "npoints", "nprims", "nvertices", "bbox",
                                   "centroid", "point", "points", "prim", "prims", "detail",
                                   "details", "opname", "opinputpath"]);

/**
 * Find path strings **written directly** in these PATH_FUNCS calls (the first argument is a string literal), and hand them to
 * fn(path, function name) for replacement; everything else is left verbatim (spaces and parentheses preserved). fn returning null means no replacement.
 * Used in two places: when storing, "../title/tx" becomes "@id/tx" (titles change and get duplicated, ids do not); when displaying, it is converted back.
 * Text that fails lexing is returned as is (malformed expressions must also be stored and displayed verbatim, so people can fix them).
 */
export function mapChPaths(text, fn) {
  let toks;
  try { toks = tokenize(text); } catch (_) { return String(text); }
  const s = String(text);
  const edits = [];
  for (let i = 0; i + 3 < toks.length; i++) {
    const a = toks[i], b = toks[i + 1], c = toks[i + 2], d = toks[i + 3];
    if (a.t === "id" && PATH_FUNCS.has(a.v) && b.t === "op" && b.v === "("
        && c.t === "str" && d.t === "op" && (d.v === ")" || d.v === ",")) {
      const r = fn(c.v, a.v);
      if (r !== null && r !== undefined && r !== c.v) edits.push([c.s, c.e, quote(r)]);
    }
  }
  let out = s;
  for (const [st, en, rep] of edits.reverse()) out = out.slice(0, st) + rep + out.slice(en);
  return out;
}

export function quote(s) {
  return `"${String(s).replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

// ════════════════════════════════════════════════════ String fields: backticks + $variables
/**
 * string field text -> segments [{k:"lit", v} | {k:"expr", src, s, e} | {k:"var", name, pad}].
 * s / e are the positions of the backtick source in the original text (for positional replacement when canonicalizing paths).
 */
export function splitTemplate(text) {
  const t = String(text);
  const out = [];
  let lit = "";
  const flush = () => { if (lit) { out.push({ k: "lit", v: lit }); lit = ""; } };
  for (let i = 0; i < t.length;) {
    const c = t[i];
    if (c === "\\" && i + 1 < t.length && "`$\\".includes(t[i + 1])) { lit += t[i + 1]; i += 2; continue; }
    if (c === "`") {
      let j = i + 1, src = "";
      while (j < t.length && t[j] !== "`") {
        if (t[j] === "\\" && t[j + 1] === "`") { src += "`"; j += 2; continue; }
        src += t[j++];
      }
      if (j >= t.length) throw new ExprError(`unterminated backtick starting at character ${i + 1}`);
      flush();
      out.push({ k: "expr", src, s: i + 1, e: j });
      i = j + 1;
      continue;
    }
    if (c === "$") {
      const m = /^\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))/.exec(t.slice(i));
      if (m) {
        flush();
        const raw = m[1] ?? m[2];
        const pm = /^F(\d+)$/.exec(raw);
        out.push(pm ? { k: "var", name: "F", pad: Number(pm[1]), raw: m[0] }
                    : { k: "var", name: raw, pad: 0, raw: m[0] });
        i += m[0].length;
        continue;
      }
    }
    lit += c;
    i++;
  }
  flush();
  return out;
}

/** Whether this text should be stored as a template (has backticks or $variables). Plain text is an ordinary string value. */
export function isTemplate(text) {
  try { return splitTemplate(text).some((p) => p.k !== "lit"); }
  catch (_) { return true; }                     // unterminated backtick: still stored as a template (so it can be flagged red)
}

/**
 * Expand a template. ctx.expr(src) evaluates the expression inside backticks; ctx.vars(name) fetches a variable, undefined when unknown
 * (the $name is left as is, same as Houdini -- things like $HIP in paths do not exist here, and leaving them is easier to debug than an empty string).
 */
export function expandTemplate(text, ctx = {}) {
  return splitTemplate(text).map((p) => {
    if (p.k === "lit") return p.v;
    if (p.k === "expr") return fmtStr(ctx.expr(p.src));
    const v = ctx.vars?.(p.name);
    if (v === undefined) return p.raw;
    if (p.pad) {
      const n = Math.trunc(Number(v));
      return (n < 0 ? "-" : "") + String(Math.abs(n)).padStart(p.pad - (n < 0 ? 1 : 0), "0");
    }
    return fmtStr(v);
  }).join("");
}

/** Run mapChPaths on each backtick expression in the template, everything else verbatim. If the template itself is invalid, return it as is. */
export function mapTemplatePaths(text, fn) {
  let parts;
  try { parts = splitTemplate(text); } catch (_) { return String(text); }
  let out = String(text);
  for (const p of parts.filter((x) => x.k === "expr").reverse()) {
    const raw = out.slice(p.s, p.e);
    if (raw.includes("\\`")) continue;             // escaped backtick inside backticks: positions would not line up, leave it alone
    out = out.slice(0, p.s) + mapChPaths(raw, fn) + out.slice(p.e);
  }
  return out;
}
