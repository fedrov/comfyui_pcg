// comfyui_pcg/web/pcg_handles.js
//
// Viewport interaction (pcg103): Houdini's state handles + the Curve drawing tool.
//
// ━━ How to use
//   **Select** a node that has handles in the graph (Transform, Box, Sphere, Grid, Curve …) and its handles appear
//   in the viewport -- like "select the node, press Enter in the viewport" in Houdini, just without pressing Enter.
//     T / R / E      translate / rotate / scale (switch between whichever the node has; the small buttons at the bottom-left of the HUD can be clicked too)
//     left-drag a handle  changes parameters. Drag an axis = along the axis, drag a small square = in that plane, drag the center = in the screen plane;
//                    rotation rings turn by Euler channel (a ring's orientation is the axis that channel really rotates about), scale center block = uniform
//     Ctrl           snapping: translate snaps to 1/10 of the grid, rotate 15°, scale 0.1
//     Alt / Space + left  tumble the view as usual (left button tumbles anyway when no handle is hit)
//   Curve (PCG):
//     left-click empty space  add a point (landing on the surface if it hits geometry, otherwise on the construction plane: the ground in a top-down view,
//                    a vertical plane through the previous point facing the camera in a level view)
//     left-drag a point  move it (hold Shift to snap to the surface, Ctrl to snap to the grid)
//     Ctrl + click a segment  insert a point there
//     Delete / Backspace while hovering a point  delete the point
//     click the first point  close the curve (with ≥ 3 points); pressing left and then dragging away = tumble, no point added
//
// ━━ What gets changed
//   Handles only change the node's widgets (same as dragging values in the panel); geometry is still computed by Python: while dragging, runs are queued
//   throttled to 120ms, and queued once more on release (when the panel's Auto is on; queueing uses pcg_display's coalescing logic,
//   at most one job in flight at any time). So undo / saving / duplicating nodes all work as usual.
//   Components of a parameter bound to an expression / reference are **locked** (that part of the handle is drawn gray and can't be dragged); keyframed
//   components set a key at the current frame when dragged (Houdini's behaviour with Auto Key on).
//
// ━━ Why draw on a 2D overlay
//   Handles are lines, rings and small squares, drawn with canvas 2D on the viewport overlay (indices and tick marks are drawn there too): always on top,
//   constant thickness on screen, no fighting with scene depth, and hit testing is done in screen space too. Custom shaders don't
//   run on this machine (see the point-sprite notes in pcg_viewport.js); the overlay approach depends on no WebGL features.
//
// All the math is pure functions (arrays in, arrays out); the camera is passed in via a small adapter, so tests need no WebGL.

import { app } from "../../scripts/app.js";
import { bindings, keysOf, setKey, currentFrame, KEY_PREFIX } from "./pcg_params.js";

// ═══════════════════════════════════════════════════════════ vectors
export const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
export const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
export const mul = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
export const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
                                a[0] * b[1] - a[1] * b[0]];
export const len = (a) => Math.hypot(a[0], a[1], a[2]);
export const norm = (a) => { const l = len(a) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
const D2R = Math.PI / 180;
const E3 = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
const AXC = ["#e0575b", "#63c46a", "#5b8fe0"];      // X red Y green Z blue (same as the indicator at top right)
const C_HOT = "#ffd84a";                             // hover / dragging: Houdini yellow
const C_LOCK = "#6b6f78";

/** 3×3 (array of rows) times column vector. */
export function mv(M, v) {
  return [M[0][0] * v[0] + M[0][1] * v[1] + M[0][2] * v[2],
          M[1][0] * v[0] + M[1][1] * v[1] + M[1][2] * v[2],
          M[2][0] * v[0] + M[2][1] * v[1] + M[2][2] * v[2]];
}
export function mm(A, B) {
  const R = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  for (let i = 0; i < 3; i++)
    for (let j = 0; j < 3; j++)
      R[i][j] = A[i][0] * B[0][j] + A[i][1] * B[1][j] + A[i][2] * B[2][j];
  return R;
}
function axisRot(k, deg) {
  const c = Math.cos(deg * D2R), s = Math.sin(deg * D2R);
  if (k === 0) return [[1, 0, 0], [0, c, -s], [0, s, c]];
  if (k === 1) return [[c, 0, s], [0, 1, 0], [-s, 0, c]];
  return [[c, -s, 0], [s, c, 0], [0, 0, 1]];
}
const AXI = { x: 0, y: 1, z: 2 };

/**
 * Same convention as euler_matrix in geo/ops.py: degrees, column vectors, order is the **sequence**
 * ("xyz" = rotate about X first, then Y, finally Z, M = Rz·Ry·Rx).
 */
export function eulerMatrix(r, order = "xyz") {
  let M = E3.map((row) => row.slice());
  for (const ch of order) M = mm(axisRot(AXI[ch], r[AXI[ch]]), M);
  return M;
}

/**
 * The axis each Euler channel **really rotates about** (world space). Changing r[k] equals rotating about this axis -- rotation rings are oriented by it,
 * dragging a ring changes that channel, and the result matches what you see (Houdini's Gimbal mode).
 * Channel k is at position i in order: axis = (the rotations after it) · e_k.
 */
export function gimbalAxes(r, order = "xyz") {
  const out = [null, null, null];
  for (let i = 0; i < 3; i++) {
    const k = AXI[order[i]];
    let M = E3.map((row) => row.slice());
    for (let j = i + 1; j < 3; j++) M = mm(axisRot(AXI[order[j]], r[AXI[order[j]]]), M);
    out[k] = norm(mv(M, E3[k]));
  }
  return out;
}

/** Intersection of ray o + t·d with plane (p0, n); null when parallel or behind. */
export function rayPlane(o, d, p0, n) {
  const den = dot(d, n);
  if (Math.abs(den) < 1e-9) return null;
  const t = dot(sub(p0, o), n) / den;
  if (!(t > 0)) return null;
  return add(o, mul(d, t));
}

/** Plane used when dragging an axis: contains the axis, faces the camera as much as possible. */
export function axisDragPlaneNormal(axis, viewDir) {
  const n = cross(axis, cross(viewDir, axis));
  return len(n) < 1e-6 ? norm(viewDir) : norm(n);
}

/** On-screen distance from a point to a segment, and the segment parameter u ∈ [0,1]. */
export function segDist(p, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const L2 = dx * dx + dy * dy;
  let u = L2 > 1e-12 ? ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2 : 0;
  u = Math.max(0, Math.min(1, u));
  return { d: Math.hypot(p[0] - a[0] - u * dx, p[1] - a[1] - u * dy), u };
}

function inPoly(p, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > p[1]) !== (yj > p[1]) &&
        p[0] < (xj - xi) * (p[1] - yi) / ((yj - yi) || 1e-12) + xi) inside = !inside;
  }
  return inside;
}

/** Signed angle: angle from v0 to v1 about axis (radians). */
export function signedAngle(v0, v1, axis) {
  return Math.atan2(dot(axis, cross(v0, v1)), dot(v0, v1));
}

export const snapTo = (x, step) => (step > 0 ? Math.round(x / step) * step : x);
const tidy = (x) => Math.round(x * 1e5) / 1e5;

// ═══════════════════════════════════════════════════════════ point list text
// Same format as parse_points / format_points in geo/curvedraw.py (the tests compare both sides)
const NUM = /^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$/;
export function parsePoints(text) {
  const s = String(text ?? "").trim();
  if (!s) return [];
  const lines = s.replace(/;/g, "\n").split(/\n/).map((x) => x.trim()).filter(Boolean);
  let toks = lines;
  if (lines.length === 1 && lines[0].includes(",") && /\d\s+[-+.\d]/.test(lines[0])
      && !/,\s/.test(lines[0])) toks = lines[0].split(/\s+/);
  const out = [];
  for (const t of toks) {
    const parts = t.split(/[,\s]+/).filter(Boolean);
    if (parts.length < 1 || parts.length > 3 || !parts.every((p) => NUM.test(p)))
      throw new Error(`Points is malformed: '${t}'`);
    const v = parts.map(Number);
    while (v.length < 3) v.push(0);
    out.push(v);
  }
  return out;
}
function fmt(x) {
  let s = Number(x).toFixed(5).replace(/0+$/, "").replace(/\.$/, "");
  if (s === "-0" || s === "") s = "0";
  return s;
}
export function formatPoints(P) {
  return P.map((p) => p.map(fmt).join(", ")).join("\n");
}

// ═══════════════════════════════════════════════════════════ which nodes have handles
//   t   the three translate widgets (null = no such dimension)      r   rotate (degrees)
//   s   scale / size (changed proportionally)                      us  single widget for uniform scale
//   pivot  handle drawn at pivot + t (Transform-like nodes); otherwise drawn at t
//   order  rotation order widget name           enable  toggle switched on along the way when dragging
//   curve  drawing tool (Curve)
const XYZ = (p) => [`${p}x`, `${p}y`, `${p}z`];
const SFX = (p) => [`${p}_x`, `${p}_y`, `${p}_z`];
const wv = (node, name, d) => {
  const w = node?.widgets?.find((x) => x.name === name);
  return w ? w.value : d;
};

export const SPECS = {
  PCG_Transform: { t: XYZ("t"), r: XYZ("r"), s: XYZ("s"), us: "uniform_scale",
                   pivot: XYZ("p"), order: "rotate_order" },
  PCG_SoftTransform: { t: XYZ("t"), r: XYZ("r"), s: XYZ("s"), pivot: SFX("pivot"),
                       order: "rotate_order" },
  PCG_CopyAndTransform: { t: XYZ("t"), r: XYZ("r"), s: XYZ("s"), us: "uniform_scale",
                          pivot: SFX("pivot") },
  PCG_Box: { t: ["cx", "cy", "cz"], r: XYZ("r"), s: SFX("size"), us: "uniform_scale" },
  PCG_Sphere: { t: SFX("center"), r: XYZ("r"), s: SFX("radius"), us: "radius" },
  PCG_Grid: (n) => {
    const p = wv(n, "plane", "zx");
    const s = p === "xy" ? ["size_x", "size_z", null]
            : p === "yz" ? [null, "size_z", "size_x"] : ["size_x", null, "size_z"];
    return { t: SFX("center"), r: XYZ("r"), s };
  },
  PCG_Tube: { t: SFX("center"), r: XYZ("r"), us: "radius_scale" },
  PCG_Torus: { t: SFX("center") },
  PCG_Circle: { t: ["cx", "cy", "cz"], r: XYZ("r"), us: "uniform_scale",
                enable: { r: { use_rotate: true } } },
  PCG_Line: { t: SFX("origin") },
  PCG_PlatonicSolids: { t: SFX("center"), us: "radius" },
  PCG_Clip: (n) => (wv(n, "orient", "direction") === "transform"
    ? { t: SFX("translate"), r: SFX("rotate") }
    : { t: SFX("origin"), enable: { t: { use_origin: true } } }),
  PCG_Mirror: (n) => (wv(n, "orient", "direction") === "transform"
    ? { t: SFX("translate"), r: SFX("rotate") }
    : { t: SFX("origin") }),
  PCG_Curve: { curve: "points", closed: "closed" },
};

/** node -> resolved handle description (keeping only widgets that really exist on the node); null when there are no handles. */
export function specFor(node) {
  if (!node) return null;
  let s = SPECS[node.type ?? node.comfyClass];
  if (!s) return null;
  if (typeof s === "function") s = s(node);
  const has = (n) => !!n && !!node.widgets?.find((w) => w.name === n);
  const vec = (v) => (v && v.some(has) ? v.map((n) => (has(n) ? n : null)) : null);
  if (s.curve) return has(s.curve) ? { ...s, modes: ["curve"] } : null;
  const out = { ...s, t: vec(s.t), r: vec(s.r), s: vec(s.s), pivot: vec(s.pivot),
                us: has(s.us) ? s.us : null };
  out.modes = [out.t && "t", out.r && "r", (out.s || out.us) && "s"].filter(Boolean);
  return out.modes.length ? out : null;
}

// ═══════════════════════════════════════════════════════════ widget read / write
function widgetOf(node, name) { return node?.widgets?.find((w) => w.name === name); }
function isInputLinked(node, name) {
  const inp = node?.inputs?.find((i) => i.name === name || i.widget?.name === name);
  return inp && inp.link != null;
}

/**
 * Whether this component can be changed by a handle: "free" / "key" (keyframed: set a key at the current frame) / "lock" (expression, reference,
 * connected).
 */
export function channelState(node, name) {
  if (!name || !widgetOf(node, name)) return "lock";
  if (isInputLinked(node, name)) return "lock";
  const b = bindings(node)?.[name];
  if (b == null) return "free";
  return String(b).startsWith(KEY_PREFIX) ? "key" : "lock";
}

export function readVal(node, name, d = 0) {
  const w = widgetOf(node, name);
  const v = w ? Number(w.value) : d;
  return Number.isFinite(v) ? v : d;
}
export function readVec(node, names, d = 0) {
  return [0, 1, 2].map((i) => (names && names[i] ? readVal(node, names[i], d) : d));
}

/** Write a widget (calls callback, same as pcg_display.setWidget). Returns whether it changed. */
export function setWidget(node, name, value) {
  const w = widgetOf(node, name);
  if (!w) return false;
  if (typeof w.value === "number" && typeof value === "number"
      && Math.abs(w.value - value) < 1e-12) return false;
  if (w.value === value) return false;
  w.value = value;
  try { w.callback?.(value, app.canvas, node); } catch (_) { /* errors in linked logic shouldn't interrupt the drag */ }
  return true;
}

/** Write according to channel state: free writes directly, key sets a key at the current frame, lock skips. Returns whether it changed. */
export function writeChannel(node, name, value) {
  const st = channelState(node, name);
  if (st === "lock") return false;
  if (st === "key") return setKey(app.graph, node, name, currentFrame(app.graph), value);
  return setWidget(node, name, value);
}

// ═══════════════════════════════════════════════════════════ queueing runs
let _disp = null;
let _lastRun = 0, _runTimer = null;
async function display() {
  if (_disp === null) {
    try { _disp = await import("./pcg_display.js"); } catch (_) { _disp = false; }
  }
  return _disp || null;
}
/** Throttled queueing: at most once per 120ms while dragging, immediately when final=true (release). */
export function scheduleRun(final = false) {
  const go = async () => {
    _runTimer = null;
    _lastRun = performance.now();
    const d = await display();
    if (d?.requestRun) d.requestRun();
  };
  if (final) { if (_runTimer) clearTimeout(_runTimer); go(); return; }
  if (_runTimer) return;
  const wait = Math.max(0, 120 - (performance.now() - _lastRun));
  _runTimer = setTimeout(go, wait);
}

function touched(node) {
  node?.setDirtyCanvas?.(true, true);
  app.graph?.setDirtyCanvas?.(true, true);
}

// ═══════════════════════════════════════════════════════════ current node
/** Which node the viewport follows: the one selected in the graph (with multiple selected, the current node; otherwise nothing shown). */
export function activeNode() {
  const c = app.canvas;
  const sel = c?.selected_nodes ? Object.values(c.selected_nodes) : [];
  if (sel.length === 1) return sel[0];
  if (sel.length > 1 && c.current_node && sel.includes(c.current_node)) return c.current_node;
  return null;
}

// ═══════════════════════════════════════════════════════════ handle tool
//
// view adapter (provided by Viewport in pcg_viewport.js):
//   screen(p) -> [x, y] | null      world coordinates -> canvas CSS pixels (null when behind the camera)
//   ray(x, y) -> { o, d }           canvas CSS pixels -> world ray (d unit length)
//   viewDir() -> [x,y,z]            camera direction (unit)
//   worldPerPx(p) -> number          world length of one pixel at p
//   pickSurface(o, d) -> p | null   ray hit against the displayed mesh
//   gridStep() -> number             grid unit
//   tumble(dx, dy)                  tumble the view (for "press then drag away" in the drawing tool)
//   dpr()                           device pixel ratio (the overlay canvas is in physical pixels)
const AXIS_PX = 92, RING_PX = 74, PICK_PX = 8, PLANE_LO = 0.22, PLANE_HI = 0.42;

export class HandleTool {
  constructor(view) {
    this.view = view;
    this.node = null;
    this.spec = null;
    this.mode = null;
    this.hot = null;          // hovered part { kind, k }
    this.drag = null;
    this.cHot = null;         // drawing tool: hovered point / segment
  }

  // ── every frame: see what is selected in the graph
  update(nodeOverride) {
    const n = nodeOverride !== undefined ? nodeOverride : activeNode();
    if (n !== this.node) {
      this.node = n;
      this.drag = null;
      this.hot = null;
      this.cHot = null;
    }
    this.spec = n ? specFor(n) : null;
    if (!this.spec) { this.mode = null; return; }
    if (!this.spec.modes.includes(this.mode)) this.mode = this.spec.modes[0];
  }

  active() { return !!this.spec; }

  // ── handle geometry (world space)
  frame() {
    const n = this.node, s = this.spec;
    const t = readVec(n, s.t);
    const piv = s.pivot ? readVec(n, s.pivot) : [0, 0, 0];
    const c = add(piv, t);
    const r = s.r ? readVec(n, s.r) : [0, 0, 0];
    const order = s.order ? String(wv(n, s.order, "xyz")) : "xyz";
    const R = eulerMatrix(r, /^[xyz]{3}$/.test(order) ? order : "xyz");
    const L = AXIS_PX * this.view.worldPerPx(c);
    return { c, t, r, R, order: /^[xyz]{3}$/.test(order) ? order : "xyz", L };
  }

  /** How each part looks on screen in the current mode: [{kind, k, pts(screen), lock}] */
  parts(F) {
    const V = this.view, s = this.spec, n = this.node, out = [];
    const c2 = V.screen(F.c);
    if (!c2) return out;
    const lockOf = (names, k) => !names || !names[k] || channelState(n, names[k]) === "lock";
    if (this.mode === "t") {
      for (let k = 0; k < 3; k++) {
        const tip = V.screen(add(F.c, mul(E3[k], F.L)));
        if (tip) out.push({ kind: "axis", k, pts: [c2, tip], lock: lockOf(s.t, k) });
      }
      for (let k = 0; k < 3; k++) {
        const a = E3[(k + 1) % 3], b = E3[(k + 2) % 3];
        const q = [[PLANE_LO, PLANE_LO], [PLANE_HI, PLANE_LO], [PLANE_HI, PLANE_HI],
                   [PLANE_LO, PLANE_HI]].map(([u, v]) =>
          V.screen(add(F.c, add(mul(a, u * F.L), mul(b, v * F.L)))));
        if (q.every(Boolean))
          out.push({ kind: "plane", k, pts: q,
                     lock: lockOf(s.t, (k + 1) % 3) || lockOf(s.t, (k + 2) % 3) });
      }
      out.push({ kind: "center", k: -1, pts: [c2], lock: [0, 1, 2].some((k) => lockOf(s.t, k)) });
    } else if (this.mode === "r") {
      const G = gimbalAxes(F.r, F.order);
      const Rr = (RING_PX / AXIS_PX) * F.L;
      for (let k = 0; k < 3; k++) {
        const g = G[k];
        const u = norm(Math.abs(g[0]) < 0.9 ? cross(g, [1, 0, 0]) : cross(g, [0, 1, 0]));
        const v = cross(g, u);
        const pts = [], wpts = [];
        for (let i = 0; i <= 64; i++) {
          const a = (i / 64) * Math.PI * 2;
          const w = add(F.c, add(mul(u, Math.cos(a) * Rr), mul(v, Math.sin(a) * Rr)));
          const p = V.screen(w);
          if (p) { pts.push(p); wpts.push(w); }
        }
        if (pts.length > 8) out.push({ kind: "ring", k, pts, wpts, lock: lockOf(s.r, k), axis: g });
      }
    } else if (this.mode === "s") {
      const A = [0, 1, 2].map((k) => norm(mv(F.R, E3[k])));     // scale along the object's own axes
      if (s.s) for (let k = 0; k < 3; k++) {
        if (!s.s[k]) continue;
        const tip = V.screen(add(F.c, mul(A[k], F.L)));
        if (tip) out.push({ kind: "saxis", k, pts: [c2, tip], lock: lockOf(s.s, k), axis: A[k] });
      }
      const ulock = s.us ? channelState(n, s.us) === "lock"
                         : !s.s || s.s.some((x, k) => x && lockOf(s.s, k));
      out.push({ kind: "scenter", k: -1, pts: [c2], lock: ulock });
    }
    return out;
  }

  pick(x, y) {
    if (!this.spec || this.mode === "curve") return null;
    const F = this.frame();
    const P = [x, y];
    let best = null;
    const take = (p, d) => { if (!p.lock && d < PICK_PX && (!best || d < best.d)) best = { ...p, d }; };
    for (const p of this.parts(F)) {
      if (p.kind === "center" || p.kind === "scenter")
        take(p, Math.hypot(x - p.pts[0][0], y - p.pts[0][1]) - 3);
      else if (p.kind === "plane") { if (inPoly(P, p.pts)) take(p, 2); }
      else if (p.kind === "ring") {
        let d = Infinity;
        for (let i = 1; i < p.pts.length; i++) d = Math.min(d, segDist(P, p.pts[i - 1], p.pts[i]).d);
        take(p, d);
      } else take(p, segDist(P, p.pts[0], p.pts[1]).d);
    }
    if (best?.kind === "ring") {
      // Which point on the ring was hit (world space): when the ring is edge-on to the camera, the angle is derived from the tangent at that point
      let bi = 0, bd = Infinity;
      best.pts.forEach((q, i) => { const d = Math.hypot(x - q[0], y - q[1]); if (d < bd) { bd = d; bi = i; } });
      return { kind: "ring", k: best.k, axis: best.axis, at: best.wpts[bi] };
    }
    return best ? { kind: best.kind, k: best.k, axis: best.axis } : null;
  }

  // ── mouse
  /** Returns true = this press belongs to the handle (the viewport must not tumble). */
  pointerDown(e, x, y) {
    if (!this.spec || e.button !== 0) return false;
    if (this.hudHit(x, y)) return true;
    if (this.mode === "curve") return this.curveDown(e, x, y);
    const h = this.pick(x, y);
    if (!h) return false;
    const F = this.frame();
    const V = this.view, s = this.spec, n = this.node;
    const { o, d } = V.ray(x, y);
    const vd = V.viewDir();
    const D = { h, F, x0: x, y0: y,
                t0: readVec(n, s.t), r0: s.r ? readVec(n, s.r) : null,
                s0: s.s ? readVec(n, s.s, 1) : null,
                us0: s.us ? readVal(n, s.us, 1) : null };
    if (h.kind === "axis" || h.kind === "saxis") {
      const a = h.kind === "axis" ? E3[h.k] : h.axis;
      D.axis = a;
      D.n = axisDragPlaneNormal(a, vd);
    } else if (h.kind === "plane") {
      D.n = E3[h.k];
    } else if (h.kind === "center") {
      D.n = norm(vd);
    } else if (h.kind === "ring") {
      D.axis = h.axis;
      D.n = h.axis;
      D.edge = Math.abs(dot(h.axis, norm(vd))) < 0.15;    // ring almost edge-on to the camera: derive via tangent
      D.acc = 0;
      // Tangent: where the hit point moves under positive rotation about the axis. Projected to screen, "pixels per radian"
      const tw = cross(h.axis, sub(h.at || F.c, F.c));
      const s0 = V.screen(h.at || F.c), s1 = V.screen(add(h.at || F.c, mul(tw, 0.01)));
      if (s0 && s1) {
        const dx = (s1[0] - s0[0]) / 0.01, dy = (s1[1] - s0[1]) / 0.01;
        const pr = Math.hypot(dx, dy);
        D.tan = pr > 1e-6 ? [dx / pr, dy / pr, pr] : null;
      }
    }
    if (D.n) {
      D.hit0 = rayPlane(o, d, F.c, D.n);
      if (!D.hit0 && h.kind !== "ring" && h.kind !== "scenter") return false;
      D.last = D.hit0;
      D.lastScr = [x, y];
    }
    this.drag = D;
    return true;
  }

  pointerMove(e, x, y) {
    if (this.mode === "curve") return this.curveMove(e, x, y);
    if (!this.drag) { this.hot = this.spec ? this.pick(x, y) : null; return false; }
    const D = this.drag, V = this.view, s = this.spec, n = this.node;
    const { o, d } = V.ray(x, y);
    const snap = e.ctrlKey || e.metaKey;
    let ch = false;
    const h = D.h;
    if (h.kind === "axis" || h.kind === "plane" || h.kind === "center") {
      const hit = rayPlane(o, d, D.F.c, D.n);
      if (!hit) return true;
      let delta = sub(hit, D.hit0);
      if (h.kind === "axis") delta = mul(D.axis, dot(delta, D.axis));
      if (h.kind === "plane") delta[h.k] = 0;
      const step = snap ? V.gridStep() / 10 : 0;
      for (let k = 0; k < 3; k++) {
        if (!s.t[k]) continue;
        if (h.kind === "axis" && k !== h.k) continue;
        let v = D.t0[k] + delta[k];
        if (step) v = snapTo(v, step);
        ch = writeChannel(n, s.t[k], tidy(v)) || ch;
      }
      ch = this.enable("t") || ch;
    } else if (h.kind === "ring") {
      let ang;
      if (D.edge || !D.hit0) {
        // Component of mouse displacement along the tangent / pixels per radian. When the tangent also points almost at the camera (the point is at the
        // ends of an edge-on ring) use 1° / pixel, with screen-up = positive rotation
        const mx = x - D.lastScr[0], my = y - D.lastScr[1];
        ang = D.tan && D.tan[2] > 20
          ? (mx * D.tan[0] + my * D.tan[1]) / D.tan[2]
          : -my * D2R;
        D.lastScr = [x, y];
      } else {
        const hit = rayPlane(o, d, D.F.c, D.n);
        if (!hit) return true;
        ang = signedAngle(sub(D.last, D.F.c), sub(hit, D.F.c), D.axis);
        D.last = hit;
      }
      D.acc += ang / D2R;
      let v = D.r0[h.k] + D.acc;
      if (snap) v = snapTo(v, 15);
      ch = writeChannel(n, s.r[h.k], tidy(v)) || ch;
      ch = this.enable("r") || ch;
    } else if (h.kind === "saxis") {
      const hit = rayPlane(o, d, D.F.c, D.n);
      if (!hit) return true;
      const a0 = dot(sub(D.hit0, D.F.c), D.axis), a1 = dot(sub(hit, D.F.c), D.axis);
      let f = Math.abs(a0) > D.F.L * 0.05 ? a1 / a0 : 1 + (a1 - a0) / D.F.L;
      if (snap) f = snapTo(f, 0.1);
      ch = writeChannel(n, s.s[h.k], tidy(D.s0[h.k] * f)) || ch;
    } else if (h.kind === "scenter") {
      let f = Math.exp(((x - D.x0) - (y - D.y0)) * 0.01);
      if (snap) f = Math.max(0.1, snapTo(f, 0.1));
      if (s.us) ch = writeChannel(n, s.us, tidy(D.us0 * f)) || ch;
      else for (let k = 0; k < 3; k++)
        if (s.s[k]) ch = writeChannel(n, s.s[k], tidy(D.s0[k] * f)) || ch;
    }
    if (ch) { touched(n); scheduleRun(false); }
    return true;
  }

  pointerUp(e) {
    if (this.mode === "curve") return this.curveUp(e || {});
    if (!this.drag) return false;
    this.drag = null;
    scheduleRun(true);
    return true;
  }

  enable(kind) {
    const en = this.spec.enable?.[kind];
    if (!en) return false;
    let ch = false;
    for (const [k, v] of Object.entries(en)) ch = setWidget(this.node, k, v) || ch;
    return ch;
  }

  key(e) {
    if (!this.spec) return false;
    const k = e.key.toLowerCase();
    if (this.mode === "curve") return this.curveKey(e);
    const want = { t: "t", r: "r", e: "s" }[k];
    if (want && this.spec.modes.includes(want) && !e.ctrlKey && !e.metaKey && !e.altKey) {
      this.mode = want;
      this.hot = null;
      return true;
    }
    return false;
  }

  // ── HUD: mode buttons at the bottom-left
  hudButtons() {
    if (!this.spec) return [];
    const V = this.view;
    const H = V.size()[1];
    const labels = { t: "T", r: "R", s: "E", curve: "✎" };
    return this.spec.modes.map((m, i) => ({ m, x: 8 + i * 24, y: H - 40, w: 20, h: 18,
                                             label: labels[m] }));
  }
  hudHit(x, y) {
    for (const b of this.hudButtons())
      if (x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h) {
        this.mode = b.m;
        return true;
      }
    return false;
  }

  cursor() {
    if (!this.spec) return "";
    if (this.mode === "curve") return this.cHot?.kind === "pt" ? "move" : "crosshair";
    return this.hot || this.drag ? "pointer" : "";
  }

  // ── drawing
  draw(ctx, dpr) {
    if (!this.spec || !this.node) return;
    ctx.save();
    ctx.scale(dpr, dpr);
    try {
      if (this.mode === "curve") this.drawCurve(ctx);
      else this.drawHandle(ctx);
      this.drawHud(ctx);
    } finally {
      ctx.restore();
    }
  }

  drawHud(ctx) {
    ctx.font = "bold 11px ui-monospace, monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (const b of this.hudButtons()) {
      const on = b.m === this.mode;
      ctx.fillStyle = on ? "#4a9eff" : "rgba(40,42,50,0.85)";
      ctx.strokeStyle = on ? "#9cc8ff" : "#555a66";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.rect(b.x + 0.5, b.y + 0.5, b.w, b.h);
      ctx.fill(); ctx.stroke();
      ctx.fillStyle = on ? "#0d1420" : "#c8ccd4";
      ctx.fillText(b.label, b.x + b.w / 2 + 0.5, b.y + b.h / 2 + 1);
    }
    const title = this.node.title || this.node.type;
    const tip = this.mode === "curve"
      ? "click add · drag move · Ctrl+click insert · Del remove · Shift surface"
      : "T R E mode · Ctrl snap · Alt+LMB orbit";
    ctx.textAlign = "left";
    ctx.font = "10px ui-monospace, monospace";
    ctx.fillStyle = "#c8ccd4";
    const b = this.hudButtons();
    const x0 = 8 + b.length * 24 + 4, y0 = (b[0]?.y ?? 0) + 9;
    ctx.fillText(title, x0, y0 - 5);
    ctx.fillStyle = "#8a8f9a";
    ctx.fillText(tip, x0, y0 + 6);
  }

  drawHandle(ctx) {
    const F = this.frame();
    const parts = this.parts(F);
    const hk = this.drag?.h || this.hot;
    const isHot = (p) => hk && hk.kind === p.kind && hk.k === p.k;
    for (const p of parts) {
      const col = p.lock ? C_LOCK : isHot(p) ? C_HOT
                : p.k >= 0 ? AXC[p.k] : "#e8e8ec";
      ctx.strokeStyle = col;
      ctx.fillStyle = col;
      ctx.lineWidth = isHot(p) ? 3 : 2;
      if (p.kind === "axis" || p.kind === "saxis") {
        const [a, b] = p.pts;
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
        const ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
        if (p.kind === "axis") {
          ctx.beginPath();
          ctx.moveTo(b[0] + Math.cos(ang) * 10, b[1] + Math.sin(ang) * 10);
          ctx.lineTo(b[0] + Math.cos(ang + 2.6) * 7, b[1] + Math.sin(ang + 2.6) * 7);
          ctx.lineTo(b[0] + Math.cos(ang - 2.6) * 7, b[1] + Math.sin(ang - 2.6) * 7);
          ctx.closePath(); ctx.fill();
        } else {
          ctx.fillRect(b[0] - 5, b[1] - 5, 10, 10);
        }
      } else if (p.kind === "plane") {
        ctx.globalAlpha = isHot(p) ? 0.7 : 0.35;
        ctx.beginPath();
        p.pts.forEach((q, i) => (i ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1])));
        ctx.closePath(); ctx.fill();
        ctx.globalAlpha = 1;
      } else if (p.kind === "ring") {
        ctx.beginPath();
        p.pts.forEach((q, i) => (i ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1])));
        ctx.stroke();
      } else if (p.kind === "center") {
        ctx.beginPath(); ctx.arc(p.pts[0][0], p.pts[0][1], 6, 0, Math.PI * 2); ctx.stroke();
      } else if (p.kind === "scenter") {
        ctx.strokeRect(p.pts[0][0] - 6, p.pts[0][1] - 6, 12, 12);
      }
    }
    // While dragging: write the current value next to the center
    if (this.drag) {
      const s = this.spec, n = this.node, c2 = this.view.screen(F.c);
      const vals = this.mode === "t" ? readVec(n, s.t)
                 : this.mode === "r" ? readVec(n, s.r)
                 : s.us && this.drag.h.kind === "scenter" ? [readVal(n, s.us, 1)]
                 : s.s ? readVec(n, s.s, 1) : [];
      if (c2 && vals.length) {
        ctx.font = "11px ui-monospace, monospace";
        ctx.textAlign = "left";
        ctx.fillStyle = C_HOT;
        ctx.fillText(vals.map((v) => fmt(v)).join("  "), c2[0] + 14, c2[1] + 18);
      }
    }
  }

  // ════════════════════════════════════════════════ drawing tool
  curvePts() {
    try { return parsePoints(widgetOf(this.node, this.spec.curve)?.value ?? ""); }
    catch (_) { return null; }
  }
  curveClosed() { return !!widgetOf(this.node, this.spec.closed)?.value; }
  writeCurve(P) {
    const ch = setWidget(this.node, this.spec.curve, formatPoints(P));
    if (ch) { touched(this.node); scheduleRun(false); }
    return ch;
  }

  /** Hovered point / segment under a screen position. */
  curvePick(x, y) {
    const P = this.curvePts();
    if (!P) return null;
    const S = P.map((p) => this.view.screen(p));
    let best = null;
    S.forEach((s, i) => {
      if (!s) return;
      const d = Math.hypot(x - s[0], y - s[1]);
      if (d < PICK_PX + 2 && (!best || d < best.d)) best = { kind: "pt", i, d };
    });
    if (best) return best;
    const segs = P.length - 1 + (this.curveClosed() && P.length > 2 ? 1 : 0);
    for (let i = 0; i < segs; i++) {
      const a = S[i], b = S[(i + 1) % P.length];
      if (!a || !b) continue;
      const r = segDist([x, y], a, b);
      if (r.d < PICK_PX && (!best || r.d < best.d)) best = { kind: "seg", i, u: r.u, d: r.d };
    }
    return best;
  }

  /** Where a new / dragged point lands: Shift or "hit geometry when adding" -> surface; otherwise the construction plane. */
  placePoint(x, y, ref, preferSurface, snapGrid) {
    const V = this.view;
    const { o, d } = V.ray(x, y);
    if (preferSurface) {
      const s = V.pickSurface(o, d);
      if (s) return snapGrid ? s.map((c) => snapTo(c, V.gridStep() / 10)) : s;
    }
    const vd = V.viewDir();
    const base = ref || [0, 0, 0];
    let n;
    if (Math.abs(vd[1]) > 0.25) n = [0, 1, 0];          // looking down / up: horizontal plane
    else n = norm([vd[0], 0, vd[2]]);                    // level view: vertical plane facing the camera
    let p = rayPlane(o, d, ref ? base : [0, 0, 0], n);
    if (!p) p = rayPlane(o, d, base, norm(vd));
    if (!p) return null;
    if (snapGrid) {
      const st = V.gridStep() / 10;
      p = p.map((c, k) => (Math.abs(n[k]) > 0.999 ? c : snapTo(c, st)));
    }
    return p.map(tidy);
  }

  curveDown(e, x, y) {
    if (e.altKey) return false;
    const P = this.curvePts();
    if (!P) return false;                     // the text box is malformed: leave it alone, tumble as usual
    const h = this.curvePick(x, y);
    this.drag = { kind: "curve", x0: x, y0: y, lx: x, ly: y, moved: false, h, P };
    return true;
  }

  curveMove(e, x, y) {
    const D = this.drag;
    if (!D || D.kind !== "curve") {
      this.cHot = this.spec ? this.curvePick(x, y) : null;
      return false;
    }
    const far = Math.hypot(x - D.x0, y - D.y0) > 4;
    if (D.h?.kind === "pt") {
      if (!far && !D.moved) return true;
      D.moved = true;
      const P = D.P.map((p) => p.slice());
      const q = this.placePoint(x, y, D.P[D.h.i], e.shiftKey, e.ctrlKey || e.metaKey);
      if (q) { P[D.h.i] = q; this.writeCurve(P); }
      return true;
    }
    // Pressed on empty space / a segment and dragged away: treat as tumble, no point added this time
    if (far || D.moved) {
      D.moved = true;
      this.view.tumble(x - D.lx, y - D.ly);
    }
    D.lx = x; D.ly = y;
    return true;
  }

  curveUp(ev) {
    const D = this.drag;
    this.drag = null;
    if (!D || D.kind !== "curve") return false;
    if (D.moved) { if (D.h?.kind === "pt") scheduleRun(true); return true; }
    const P = D.P.map((p) => p.slice());
    if (D.h?.kind === "pt") {
      // Clicking the first point = close (Houdini's Curve finishes this way too)
      if (D.h.i === 0 && P.length >= 3 && !this.curveClosed() && this.spec.closed) {
        if (setWidget(this.node, this.spec.closed, true)) { touched(this.node); scheduleRun(true); }
      }
      return true;
    }
    if (D.h?.kind === "seg" && ev.ctrlKey) {
      const a = P[D.h.i], b = P[(D.h.i + 1) % P.length];
      P.splice(D.h.i + 1, 0, add(a, mul(sub(b, a), D.h.u)).map(tidy));
      this.writeCurve(P);
      scheduleRun(true);
      return true;
    }
    const q = this.placePoint(D.x0, D.y0, P[P.length - 1] || null, true, ev.ctrlKey || ev.metaKey);
    if (q) { P.push(q); this.writeCurve(P); scheduleRun(true); }
    return true;
  }

  curveKey(e) {
    if ((e.key === "Delete" || e.key === "Backspace") && this.cHot?.kind === "pt") {
      const P = this.curvePts();
      if (!P) return false;
      P.splice(this.cHot.i, 1);
      this.cHot = null;
      this.writeCurve(P);
      scheduleRun(true);
      return true;
    }
    return false;
  }

  drawCurve(ctx) {
    const P = this.curvePts();
    if (!P) {
      ctx.fillStyle = "#e0575b";
      ctx.font = "11px ui-monospace, monospace";
      ctx.fillText("Points text is malformed, fix it in the panel first", 10, 20);
      return;
    }
    const S = P.map((p) => this.view.screen(p));
    const closed = this.curveClosed() && P.length > 2;
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = "#ffd84a";
    ctx.setLineDash?.([5, 4]);
    ctx.beginPath();
    let pen = false;
    const seq = closed ? [...S, S[0]] : S;
    for (const s of seq) {
      if (!s) { pen = false; continue; }
      if (pen) ctx.lineTo(s[0], s[1]); else ctx.moveTo(s[0], s[1]);
      pen = true;
    }
    ctx.stroke();
    ctx.setLineDash?.([]);
    // Hovered segment (for Ctrl+click to insert a point)
    if (this.cHot?.kind === "seg") {
      const a = S[this.cHot.i], b = S[(this.cHot.i + 1) % P.length];
      if (a && b) {
        ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 3;
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
      }
    }
    ctx.font = "10px ui-monospace, monospace";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    S.forEach((s, i) => {
      if (!s) return;
      const hot = (this.cHot?.kind === "pt" && this.cHot.i === i)
               || (this.drag?.h?.kind === "pt" && this.drag.h.i === i);
      ctx.fillStyle = hot ? C_HOT : i === 0 ? "#4a9eff" : "#f2f2f4";
      ctx.strokeStyle = "#14151a";
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(s[0], s[1], hot ? 6 : i === 0 ? 5.5 : 4.5, 0, Math.PI * 2);
      ctx.fill(); ctx.stroke();
      ctx.fillStyle = "#c8ccd4";
      ctx.fillText(String(i), s[0] + 8, s[1] - 8);
    });
  }
}
