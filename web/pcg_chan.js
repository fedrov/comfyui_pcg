// comfyui_pcg/web/pcg_chan.js
//
// Evaluation of keyframe channels -- the JS version of geo/channel.py, for "keyframes on any parameter" (pcg_params.js).
//
// Syntax, interpolation, auto slopes and out-of-range handling are **all copied from channel.py** (its module header has the full derivation):
//     frame:value[:interp][@slope]  space-separated
//     interp constant linear ease easein easeout cubic (default) quintic; the key it is written on governs the segment to its right
//     out of range: hold (default) linear cycle cycleoffset mirror
// Two implementations drift, so the test spawns python and compares channel.value_at frame by frame (test_hexpr.mjs).

export const INTERPS = ["constant", "linear", "ease", "easein", "easeout", "cubic", "quintic"];
export const EXTRAPS = ["hold", "linear", "cycle", "cycleoffset", "mirror"];
const [CONSTANT, LINEAR, EASE, EASEIN, EASEOUT, CUBIC, QUINTIC] = [0, 1, 2, 3, 4, 5, 6];

/** text -> keyframes sorted by frame [{f, v, c, s}] (s = NaN means auto slope). For the same frame the later one wins. */
export function parseKeys(spec, defaultInterp = "cubic") {
  const di = INTERPS.indexOf(defaultInterp);
  if (di < 0) throw new Error(`interpolation must be one of ${INTERPS.join(" / ")}`);
  const toks = String(spec ?? "").replace(/,/g, " ").split(/\s+/).filter(Boolean);
  if (!toks.length) throw new Error("channel is empty");
  const keys = toks.map((t) => {
    let body = t, s = NaN;
    if (body.includes("@")) {
      const i = body.indexOf("@");
      s = Number(body.slice(i + 1));
      body = body.slice(0, i);
      if (!Number.isFinite(s)) throw new Error(`'${t}': @ must be followed by a slope`);
    }
    const parts = body.split(":");
    if (parts.length < 2 || parts.length > 3) throw new Error(`'${t}' must be written as frame:value[:interp]`);
    const f = Number(parts[0]), v = Number(parts[1]);
    if (!Number.isFinite(f) || parts[0].trim() === "") throw new Error(`'${parts[0]}' is not a frame number`);
    if (!Number.isFinite(v) || parts[1].trim() === "") throw new Error(`'${parts[1]}' is not a number`);
    let c = di;
    if (parts.length === 3) {
      c = INTERPS.indexOf(parts[2].trim().toLowerCase());
      if (c < 0) throw new Error(`unknown interpolation '${parts[2]}'`);
    }
    return { f, v, c, s };
  });
  keys.sort((a, b) => a.f - b.f);             // Array.sort is stable: same-frame keys keep text order, the later one wins
  const out = [];
  for (const k of keys) {
    if (out.length && Math.abs(out[out.length - 1].f - k.f) <= 1e-9) out[out.length - 1] = k;
    else out.push(k);
  }
  return out;
}

/** keyframes -> text (written back into the binding table). The default interpolation cubic is not written. */
export function formatKeys(keys) {
  const n = (x) => String(Math.round(x * 1e6) / 1e6);
  return keys.map((k) => `${n(k.f)}:${n(k.v)}${k.c !== CUBIC ? ":" + INTERPS[k.c] : ""}`
                  + (Number.isFinite(k.s) ? "@" + n(k.s) : "")).join("  ");
}

function autoSlopes(f, v, s) {
  const k = f.length;
  const m = s.slice();
  if (k === 1) return m.map((x) => (Number.isNaN(x) ? 0 : x));
  const h = [], d = [];
  for (let i = 0; i < k - 1; i++) { h.push(f[i + 1] - f[i]); d.push((v[i + 1] - v[i]) / h[i]); }
  const auto = new Array(k);
  if (k === 2) auto.fill(d[0]);
  else {
    for (let i = 1; i < k - 1; i++) auto[i] = (h[i] * d[i - 1] + h[i - 1] * d[i]) / (h[i - 1] + h[i]);
    auto[0] = d[0] - h[0] * (d[1] - d[0]) / (h[0] + h[1]);
    auto[k - 1] = d[k - 2] + h[k - 2] * (d[k - 2] - d[k - 3]) / (h[k - 3] + h[k - 2]);
  }
  return m.map((x, i) => (Number.isNaN(x) ? auto[i] : x));
}

function seg(c, t, p0, p1, m0, m1, h) {
  const dv = p1 - p0;
  if (c === CONSTANT) return p0;
  if (c === LINEAR) return p0 + dv * t;
  if (c === EASE) return p0 + dv * (t * t * (3 - 2 * t));
  if (c === EASEIN) return p0 + dv * (t * t);
  if (c === EASEOUT) return p0 + dv * (t * (2 - t));
  const t2 = t * t, t3 = t2 * t;
  if (c === CUBIC)
    return (2 * t3 - 3 * t2 + 1) * p0 + (t3 - 2 * t2 + t) * h * m0
      + (-2 * t3 + 3 * t2) * p1 + (t3 - t2) * h * m1;
  const t4 = t3 * t, t5 = t4 * t;
  return (1 - 10 * t3 + 15 * t4 - 6 * t5) * p0 + (t - 6 * t3 + 8 * t4 - 3 * t5) * h * m0
    + (10 * t3 - 15 * t4 + 6 * t5) * p1 + (-4 * t3 + 7 * t4 - 3 * t5) * h * m1;
}

function endDeriv(c, d, m, atStart) {
  if (c === CONSTANT || c === EASE) return 0;
  if (c === LINEAR) return d;
  if (c === EASEIN) return atStart ? 0 : 2 * d;
  if (c === EASEOUT) return atStart ? 2 * d : 0;
  return m;
}

// Python's np.mod: the result has the sign of the divisor
const pmod = (a, b) => a - Math.floor(a / b) * b;

/** Value of the keyframes at frame x. */
export function evalKeys(keys, x, extrapolate = "hold") {
  if (!EXTRAPS.includes(extrapolate)) throw new Error(`out-of-range handling must be one of ${EXTRAPS.join(" / ")}`);
  const k = keys.length;
  if (!k) throw new Error("channel has no keyframes");
  if (k === 1) return keys[0].v;
  const f = keys.map((q) => q.f), v = keys.map((q) => q.v), c = keys.map((q) => q.c);
  const m = autoSlopes(f, v, keys.map((q) => q.s));
  const f0 = f[0], f1 = f[k - 1], period = f1 - f0;
  let xr, off = 0;
  if (extrapolate === "cycle") xr = f0 + pmod(x - f0, period);
  else if (extrapolate === "cycleoffset") {
    const n = Math.floor((x - f0) / period);
    xr = x - n * period;
    off = n * (v[k - 1] - v[0]);
  } else if (extrapolate === "mirror") {
    const q = pmod(x - f0, 2 * period);
    xr = f0 + (q <= period ? q : 2 * period - q);
  } else xr = Math.min(Math.max(x, f0), f1);
  // searchsorted right - 1, clamped to [0, k-2]
  let i = 0;
  while (i < k && f[i] <= xr) i++;
  i = Math.min(Math.max(i - 1, 0), k - 2);
  const h = f[i + 1] - f[i];
  let out = xr >= f1 ? v[k - 1] : seg(c[i], (xr - f[i]) / h, v[i], v[i + 1], m[i], m[i + 1], h);
  out += off;
  if (extrapolate === "linear") {
    if (x < f0) out = v[0] + endDeriv(c[0], (v[1] - v[0]) / (f[1] - f[0]), m[0], true) * (x - f0);
    else if (x > f1)
      out = v[k - 1] + endDeriv(c[k - 2], (v[k - 1] - v[k - 2]) / (f[k - 1] - f[k - 2]),
                                m[k - 1], false) * (x - f1);
  }
  return out;
}
