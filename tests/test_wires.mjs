// Tests for the Houdini feel (pcg_wires.js): rounded wire geometry, dragging wire ends, node snapping.
//
// Pure functions are compared directly with hand-computed values; setup() is attached to a stubbed canvas and we check the places it hooks into the frontend:
//   · in Straight mode the path is replaced by rounded corners (in Houdini style); switched back to "Follow ComfyUI" it calls the original
//   · before every frame the link render mode is forced to Straight, and restored to the original when switched back
//   · pressing near either end of a wire: calls the frontend's moveInputLink / dragNewFromInput + _linkConnectorDrop;
//     the middle, on a node, with a modifier held, setting off, someone else handled it first -- all left alone
//   · dragging a node: snaps to a level wire / neighbour alignment; pulling away does not stick (computed from the "pre-snap" position); Shift does not snap; released clears
// The feel in the real frontend is in test_wires_e2e.py.
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
fs.writeFileSync(path.join(ROOT, "scripts", "api.js"), "export const api = globalThis.__api;\n");
for (const f of ["pcg_wires.js", "pcg_params.js", "pcg_hexpr.js", "pcg_chan.js"])
  fs.copyFileSync(path.join(PKG, "comfyui_pcg", "web", f), path.join(EXT, f));

const OK = [];
function check(name, cond, extra = "") {
  OK.push(!!cond);
  console.log((cond ? "  PASS  " : "  FAIL  ") + name + (extra === "" ? "" : "   " + extra));
}
const sec = (t) => console.log(`\n── ${t}`);
const J = (x) => JSON.stringify(x);
const near = (a, b, e = 1e-6) => Math.abs(a - b) <= e;

// -- stubs: window events, LiteGraph, canvas ----------------------------------------
const winL = {};
globalThis.window = {
  addEventListener(t, f) { (winL[t] = winL[t] || []).push(f); },
};
const fireWin = (t, e) => (winL[t] || []).forEach((f) => f(e));
class Node {
  constructor(id, x, y, w = 200, h = 100) { this.id = id; this.pos = [x, y]; this.size = [w, h]; }
  move(dx, dy) { this.pos[0] += dx; this.pos[1] += dy; }
  setPos(x, y) { this.pos[0] = x; this.pos[1] = y; }
  getConnectionPos(isIn, slot, out = [0, 0]) {
    out[0] = isIn ? this.pos[0] : this.pos[0] + this.size[0];
    out[1] = this.pos[1] + 10 + slot * 20;
    return out;
  }
}
globalThis.LiteGraph = { STRAIGHT_LINK: 0, LINEAR_LINK: 1, SPLINE_LINK: 2, NODE_TITLE_HEIGHT: 30,
                         LGraphNode: Node };
let SETTINGS = {};
const exts = [];
const elL = {};
const calls = [];
const origStraight = [];
const origCenter = [];
const canvas = {
  links_render_mode: 2,
  ds: { scale: 1 },
  isDragging: false,
  selected_nodes: {},
  visible_nodes: null,
  dirty: 0,
  setDirty() { this.dirty++; },
  canvas: { style: { cursor: "" }, addEventListener(t, f) { (elL[t] = elL[t] || []).push(f); } },
  linkRenderer: { pathRenderer: {
    buildStraightPath(...a) { origStraight.push(a); },
    // frontend: midpoint is halfway between the two slots (each indented by 10)
    calculateCenterPoint(l) { origCenter.push(1);
      l.centerPos = { x: (l.startPoint.x + 10 + l.endPoint.x - 10) / 2, y: (l.startPoint.y + l.endPoint.y) / 2 };
      if ("centerAngle" in l) l.centerAngle = 1.5; },
  } },
  linkConnector: {
    isConnecting: false,
    moveInputLink(g, inp) { calls.push(["moveInputLink", inp.name]); },
    dragNewFromInput(g, node, inp) { calls.push(["dragNewFromInput", node.id, inp.name]); },
    reset() { calls.push(["reset"]); },
  },
  _linkConnectorDrop() { calls.push(["drop"]); },
  draw() { calls.push(["origDraw"]); },
  onMouse: null,
  convertEventToCanvasOffset(e) { return [e.x, e.y]; },
};
globalThis.__app = {
  registerExtension(e) { exts.push(e); },
  extensionManager: { setting: { get: (id) => SETTINGS[id] } },
  canvas,
};
const M = await import(path.join(EXT, "pcg_wires.js"));
const ext = exts.find((e) => e.name === "pcg.wires");

// ═══════════════════════════════════════════════════════════ Geometry
sec("Rounded polyline geometry (Houdini Rounded: the bend hugs the output end)");
{
  const { pts, r } = M.elbow([0, 0], [200, 100]);
  // a short exit segment of 8, then turn right away: the vertical segment is at x = 8 + 40 = 48, then a long horizontal run into the input
  check("polyline has 5 points: start, exit, two corners (vertical segment x = 48, hugging the output), end",
        J(pts) === J([[0, 0], [8, 0], [48, 0], [48, 100], [200, 100]]), J(pts));
  check("  radius 40 (full when there is room)", r === 40);
  check("  only 10 apart vertically: radius shrinks to 5 (the two corners do not overlap)", M.elbow([0, 0], [200, 10]).r === 5);
  check("  very short horizontally (40): radius shrinks to (40 - 8) / 2 = 16, vertical segment at 24", M.elbow([0, 0], [40, 100]).r === 16
        && M.elbow([0, 0], [40, 100]).pts[2][0] === 24);
  check("  both ends at the same height: radius 0 (a straight line)", M.elbow([0, 50], [300, 50]).r === 0);
  const back = M.elbow([300, 0], [0, 200]);
  check("  backward wire (input left of output): corners fall back to the middle (x = 150), a short stub at each end, still rounded",
        back.pts.length === 6 && back.pts[2][0] === 150 && back.r === 40, J(back));
  check("  input exactly at output + 8: radius 0, the vertical segment is right at the output", M.elbow([0, 0], [8, 100]).r === 0);
  const bk = M.elbow([100, 0], [90, 200]);
  check("  backward, but only slightly: corner at (108 + 82) / 2 = 95, radius shrinks to the 13 from the exit",
        bk.pts[2][0] === 95 && bk.r === 13, J(bk));
  check("  backward with only 10 apart vertically: radius shrinks to 5", M.elbow([300, 0], [0, 10]).r === 5);
}
{
  const rec = [];
  const P = new Proxy({}, { get: (_, k) => (...a) => rec.push([k, ...a]) });
  M.traceElbow(P, [0, 0], [200, 100]);
  check("path writing: moveTo -> lineTo(exit) -> two arcTo (radius 40) -> lineTo(end)",
        J(rec) === J([["moveTo", 0, 0], ["lineTo", 8, 0], ["arcTo", 48, 0, 48, 100, 40],
                      ["arcTo", 48, 100, 200, 100, 40], ["lineTo", 200, 100]]), J(rec));
  rec.length = 0;
  M.traceElbow(P, [0, 50], [300, 50]);
  check("  no arcTo at radius 0 (arcTo with radius 0 draws odd things in some browsers)",
        !rec.some((x) => x[0] === "arcTo"), J(rec.map((x) => x[0])));
  rec.length = 0;
  M.traceElbow(P, [300, 0], [0, 200]);
  check("  backward wire: after the arcTo there is still the short input stub", J(rec.map((x) => x[0]))
        === J(["moveTo", "lineTo", "arcTo", "arcTo", "lineTo", "lineTo"]), J(rec.map((x) => x[0])));
}
{
  // each rounded corner is a quarter circle (8 chords, each 2r·sin(π/32)): total length = sharp polyline length - 4r + 2 × 16r·sin(π/32).
  // for upward wires and backward wires the corner's start/end angles cross ±π -- if the angle difference is not wrapped into (-π, π] it takes the long way and draws three quarters of a circle
  const len = (q) => q.slice(1).reduce((s, p, i) => s + Math.hypot(p[0] - q[i][0], p[1] - q[i][1]), 0);
  const want = (sharp) => sharp - 4 * 40 + 2 * 16 * 40 * Math.sin(Math.PI / 32);
  const up = M.elbowPolyline([0, 100], [200, 0]), bw = M.elbowPolyline([300, 0], [0, 200]);
  check("  upward wire: both corners are quarter circles (total length matches)", Math.abs(len(up) - want(300)) < 1e-6, len(up));
  check("  backward wire: both corners are quarter circles (total length matches)", Math.abs(len(bw) - want(532)) < 1e-6, len(bw));
}
{
  const pl = M.elbowPolyline([0, 0], [200, 100]);
  check("sampled polyline: the two ends are the slots", J(pl[0]) === J([0, 0]) && J(pl[pl.length - 1]) === J([200, 100]));
  check("  vertical segment at x = 48 (the point at y = 50 is on the wire)", M.nearestOnPolyline(pl, [48, 50]).dist < 1e-9);
  // first rounded corner: center (8, 40), radius 40 -- all samples lie on this circle
  const arc = pl.filter((p) => p[0] > 8 && p[0] < 48 && p[1] > 0 && p[1] < 40);
  check("  the corner is a real quarter circle (samples are all 40 from center (8, 40))",
        arc.length >= 5 && arc.every((p) => near(Math.hypot(p[0] - 8, p[1] - 40), 40, 1e-9)), arc.length);
  const hitCorner = M.nearestOnPolyline(pl, [48, 0]).dist;
  check("  the corner point itself is not on the wire (it is rounded): distance > 10", hitCorner > 10, hitCorner.toFixed(2));
  const sharp = M.elbowPolyline([0, 0], [200, 100], 0);
  check("  in the radius-0 version the corner point is on the wire", M.nearestOnPolyline(sharp, [8, 0]).dist < 1e-9);
  const st = M.straightPolyline([0, 0], [200, 100]);
  check("frontend's own Straight: sharp corners, corner in the middle at x = 100 (10 at each end)",
        M.nearestOnPolyline(st, [100, 0]).dist < 1e-9 && M.nearestOnPolyline(st, [100, 50]).dist < 1e-9
        && J(st[1]) === J([10, 0]) && J(st[4]) === J([190, 100]), J(st));
}
{
  const s = M.splinePolyline([0, 0], [400, 300], 24);
  // same as the frontend's Spline: control points offset horizontally by max(30, 500 × 0.25) = 125; at t = 0.5 = average of endpoints and control points
  const m = s[12];
  check("frontend Spline bezier (control point offset max(30, distance × 0.25)): midpoint (200, 150)",
        near(m[0], 200) && near(m[1], 150), J(m));
  const s2 = M.splinePolyline([0, 0], [40, 0], 4);
  // t = 0.25: weights 27/64, 27/64, 9/64, 1/64; control points 30 and 10 (without the minimum offset of 30 they would be 10 and 30)
  check("  two very close points still offset control points by at least 30", near(s2[1][0], (27 * 30 + 9 * 10 + 40) / 64), J(s2[1]));
}
{
  const pl = [[0, 0], [100, 0], [100, 100]];
  const h = M.nearestOnPolyline(pl, [50, 4]);
  check("nearest point: distance 4, arc-length fraction 0.25", near(h.dist, 4) && near(h.t, 0.25), J(h));
  check("  on the second segment: t counts on from 0.5", near(M.nearestOnPolyline(pl, [97, 75]).t, 0.875));
  check("  projections beyond either end clamp to the endpoint", near(M.nearestOnPolyline(pl, [-10, 0]).dist, 10)
        && M.nearestOnPolyline(pl, [-10, 0]).t === 0);
  check("whichEnd: first third = out, last third = in, middle = null (left for the midpoint menu)",
        M.whichEnd(0.1) === "out" && M.whichEnd(1 / 3) === "out" && M.whichEnd(0.5) === null
        && M.whichEnd(0.67) === "in" && M.whichEnd(0.9) === "in");
  const sub = M.subPolyline(pl, 0.75, 1);
  check("subPolyline: last quarter = (100, 50) -> (100, 100)",
        J(sub) === J([[100, 50], [100, 100]]), J(sub));
  const sub2 = M.subPolyline(pl, 0, 0.25);
  check("  first quarter = (0, 0) -> (50, 0)", J(sub2) === J([[0, 0], [50, 0]]), J(sub2));
}

sec("Snap computation");
{
  const m = [{ x: 103, y: 205, w: 200, h: 100 }];
  const o = [{ x: 100, y: 500, w: 200, h: 100 }];
  let s = M.planSnap(m, o, [], 8);
  check("left edge 3 off -> snaps over (dx = -3), draws a vertical guide at x = 100", s.dx === -3 && s.gx === 100, J(s));
  check("  nothing to snap to in y: dy = 0, no horizontal guide", s.dy === 0 && s.gy === null);
  s = M.planSnap(m, o, [{ dy: 6, y: 260 }], 8);
  check("wire 6 off level -> dy = 6, horizontal guide at the slot height", s.dy === 6 && s.gy === 260, J(s));
  s = M.planSnap(m, [{ x: 100, y: 200, w: 200, h: 100 }], [{ dy: 6, y: 260 }], 8);
  check("  of several candidates the nearest wins: top edge -5 is nearer than wire 6", s.dy === -5 && s.gy === 200, J(s));
  s = M.planSnap(m, o, [{ dy: 9, y: 260 }], 8);
  check("  beyond the threshold: no snap", s.dy === 0 && s.gy === null);
  s = M.planSnap(m, [{ x: 100, y: 5000, w: 200, h: 100 }], [], 8);
  check("  nodes too far away (more than 1200 apart in both directions) are not used for alignment",
        M.planSnap(m, [{ x: 2000, y: 5000, w: 200, h: 100 }], [], 8).dx === 0
        && s.dx === -3, J(s));
  s = M.planSnap(m, [{ x: 100, y: 5000, w: 3000, h: 100 }], [], 8);
  check("  left edge 3 off, but a large node whose center is more than 1200 away both ways: no alignment", s.dx === 0 && s.gx === null, J(s));
  s = M.planSnap(m, [{ x: 98, y: 400, w: 200, h: 100 }, { x: 101, y: 700, w: 200, h: 100 }], [], 8);
  check("  of several x candidates the nearest wins (-5 and -2, takes -2)", s.dx === -2 && s.gx === 101, J(s));
  s = M.planSnap([{ x: 0, y: 0, w: 100, h: 50 }], [{ x: 50, y: 400, w: 200, h: 50 }], [], 8);
  check("  center-line alignment: center x 50 vs 150 no snap, right edge 100 vs 250 no snap -- neither within threshold",
        s.dx === 0);
  s = M.planSnap([{ x: 47, y: 0, w: 106, h: 50 }], [{ x: 0, y: 400, w: 200, h: 50 }], [], 8);
  check("  center-line alignment: center 100 vs 100 -> dx = 0 and the guide is drawn", s.dx === 0 && s.gx === 100, J(s));
  s = M.planSnap([{ x: 0, y: 0, w: 205, h: 50 }], [{ x: -300, y: 400, w: 500, h: 50 }], [], 8);
  check("  right-edge alignment: 205 vs 200 -> dx = -5", s.dx === -5 && s.gx === 200, J(s));
}

// ═══════════════════════════════════════════════════════════ Attached to the canvas
sec("setup: wire style");
const nA = new Node(1, 0, 0), nB = new Node(2, 400, 200), nC = new Node(3, 0, 600);
nB.inputs = [{ name: "geo", link: 9 }];
const links = new Map([[9, { id: 9, origin_id: 1, origin_slot: 0, target_id: 2, target_slot: 0 }]]);
const graph = {
  _nodes: [nA, nB, nC], links,
  getNodeById(id) { return this._nodes.find((n) => n.id === id) ?? null; },
  getNodeOnPos(x, y) {
    return this._nodes.find((n) => x >= n.pos[0] && x <= n.pos[0] + n.size[0]
                                   && y >= n.pos[1] - 30 && y <= n.pos[1] + n.size[1]) ?? null;
  },
};
canvas.graph = graph;
let prevCalls = 0;
canvas.onMouse = function (e) { prevCalls++; return e.prevTrue === true; };   // hooked earlier by another extension
await ext.setup();
const pr = canvas.linkRenderer.pathRenderer;
const rec = [];
const P = new Proxy({}, { get: (_, k) => (...a) => rec.push(k) });
pr.buildStraightPath(P, { x: 0, y: 0 }, { x: 200, y: 100 }, "right", "left");
check("Houdini style (default): Straight path replaced by rounded corners (arcTo used), original not called",
      rec.includes("arcTo") && origStraight.length === 0, J(rec));
rec.length = 0;
pr.buildStraightPath(P, { x: 0, y: 0 }, { x: 200, y: 100 }, "down", "left");
check("  not horizontal (collapsed nodes etc.): handed to the original", origStraight.length === 1 && !rec.length);
pr.buildStraightPath(P, { x: 0, y: 0 }, { x: 200, y: 100 }, "right", "none");
check("  wire-drag preview (released end has no direction 'none'): still rounded", rec.includes("arcTo") && origStraight.length === 1);
rec.length = 0;
pr.buildStraightPath(P, { x: 0, y: 0 }, { x: 200, y: 100 }, "left", "left");
check("  output facing left (reversed): handed to the original", origStraight.length === 2 && !rec.length);
pr.buildStraightPath(P, { x: 0, y: 0 }, { x: 200, y: 100 }, "right", "right");
pr.buildStraightPath(P, { x: 0, y: 0 }, { x: 200, y: 100 }, "right", "up");
check("  input facing right / up: handed to the original", origStraight.length === 4 && !rec.length);
SETTINGS[M.STYLE_ID] = M.STYLES[1];
pr.buildStraightPath(P, { x: 0, y: 0 }, { x: 200, y: 100 }, "right", "left");
check("  switched to 'Follow ComfyUI': calls the original (sharp corners)", origStraight.length === 5 && !rec.length);
SETTINGS[M.STYLE_ID] = M.STYLES[0];
canvas.links_render_mode = 2;
calls.length = 0;
canvas.draw();
check("before every frame the link render mode is forced to Straight (Houdini style), then drawn as usual",
      canvas.links_render_mode === 0 && J(calls) === J([["origDraw"]]), J(calls));
canvas.links_render_mode = 1;           // the user changed it to Linear in ComfyUI settings
canvas.draw();
check("  changed again on the ComfyUI side: still forced back to Straight", canvas.links_render_mode === 0);
SETTINGS[M.STYLE_ID] = M.STYLES[1];
canvas.draw();
check("  switched back to 'Follow ComfyUI': restored to what ComfyUI last set (Linear)", canvas.links_render_mode === 1);
canvas.links_render_mode = 2;
canvas.draw();
check("  not touched after that (ComfyUI's own setting rules)",
      (canvas.links_render_mode = 1, canvas.draw(), canvas.links_render_mode === 1));
SETTINGS[M.STYLE_ID] = M.STYLES[0];
canvas.draw();

{
  const L = { startPoint: { x: 200, y: 10 }, endPoint: { x: 400, y: 210 }, startDirection: "right",
              endDirection: "left", centerAngle: 0 };
  pr.calculateCenterPoint(L, { style: { mode: "straight" } });
  check("wire midpoint (the dot you click for the menu) moved to half this wire's arc length: on the vertical segment (248, 162), arrow pointing down",
        origCenter.length === 1 && near(L.centerPos.x, 248) && Math.abs(L.centerPos.y - 162) < 1
        && near(L.centerAngle, Math.PI / 2), J(L));
  const L2 = { startPoint: { x: 200, y: 10 }, endPoint: { x: 400, y: 210 } };
  pr.calculateCenterPoint(L2, { style: { mode: "spline" } });
  check("  other modes (Spline) follow the frontend", L2.centerPos.x === 300 && !("centerAngle" in L2));
  SETTINGS[M.STYLE_ID] = M.STYLES[1];
  const L3 = { startPoint: { x: 200, y: 10 }, endPoint: { x: 400, y: 210 } };
  pr.calculateCenterPoint(L3, { style: { mode: "straight" } });
  check("  'Follow ComfyUI': follows the frontend (middle x = 300)", L3.centerPos.x === 300);
  SETTINGS[M.STYLE_ID] = M.STYLES[0];
  const L4 = { startPoint: { x: 200, y: 10 }, endPoint: { x: 400, y: 210 }, startDirection: "down" };
  pr.calculateCenterPoint(L4, { style: { mode: "straight" } });
  check("  vertical wire: follows the frontend", L4.centerPos.x === 300);
  for (const [k, sd, ed] of [["output facing up", "up", "left"], ["input facing up", "right", "up"], ["input facing down", "right", "down"],
                            ["output facing left", "left", "left"], ["input facing right", "right", "right"]]) {
    const L = { startPoint: { x: 200, y: 10 }, endPoint: { x: 400, y: 210 }, startDirection: sd, endDirection: ed };
    pr.calculateCenterPoint(L, { style: { mode: "straight" } });
    check(`  wire with ${k}: follows the frontend`, L.centerPos.x === 300, J(L));
  }
  const L5 = { startPoint: { x: 200, y: 10 }, endPoint: { x: 400, y: 210 }, startDirection: "right", endDirection: "left" };
  pr.calculateCenterPoint(L5, { style: { mode: "straight" } });
  check("  marker is a dot (frontend gave no centerAngle): moved, but no angle invented", near(L5.centerPos.x, 248) && !("centerAngle" in L5), J(L5));
  const m2 = M.midpointOf([[0, 0], [15, 0], [15, 25]]);
  check("midpointOf: half = 20 lands on the second segment (15, 5) (not extrapolated beyond the first)", near(m2.x, 15) && near(m2.y, 5), J(m2));
  const m0 = M.midpointOf([[5, 5], [5, 5]]);
  check("midpointOf: zero-length wire: right at that point, no NaN", m0.x === 5 && m0.y === 5 && m0.angle === 0, J(m0));
  const mp = M.midpointOf([[0, 0], [10, 0], [10, 30]]);
  check("midpointOf: total length 40, half = 20 lands on the second segment (10, 10), pointing down",
        near(mp.x, 10) && near(mp.y, 10) && near(mp.angle, Math.PI / 2), J(mp));
}

sec("setup: dragging wire ends");
// wire: A output (200, 10) -> B input (400, 210); Houdini rounded polyline: vertical segment at x = 248
const ev = (x, y, o = {}) => ({ button: 0, canvasX: x, canvasY: y, ...o });
calls.length = 0;
check("pressing near the input end (5 left of B's slot): unplugs the downstream end (moveInputLink) + the frontend's drop handling",
      canvas.onMouse(ev(395, 210)) === true
      && J(calls) === J([["moveInputLink", "geo"], ["drop"]]), J(calls));
calls.length = 0;
check("  near the output end (5 right of A's slot): drags back from B's input (dragNewFromInput)",
      canvas.onMouse(ev(205, 10)) === true
      && J(calls) === J([["dragNewFromInput", 2, "geo"], ["drop"]]), J(calls));
calls.length = 0;
// wire length: exit 8 + corner 20π + vertical 120 + corner 20π + horizontal 112; the exact middle (half the arc length) falls on the vertical segment (248, 162)
check("  (248, 162) really is on the wire, exactly at half the arc length", (() => {
  const h = M.nearestOnPolyline(M.elbowPolyline([200, 10], [400, 210]), [248, 162]);
  return h.dist < 1e-9 && Math.abs(h.t - 0.5) < 0.01; })());
check("  exact middle (half the arc length, on the vertical segment (248, 162)): left alone, for the frontend's midpoint menu",
      canvas.onMouse(ev(248, 162)) === false && !calls.length);
check("  10 px from the wire (threshold 7): left alone", canvas.onMouse(ev(395, 220)) === false && !calls.length);
canvas.ds.scale = 0.5;
check("  zoomed out by half the threshold is in screen space (14 in the graph): 10 away counts",
      canvas.onMouse(ev(395, 220)) === true);
canvas.ds.scale = 1;
calls.length = 0;
check("  holding Shift / Ctrl / Alt, right button: all left alone",
      [{ shiftKey: true }, { ctrlKey: true }, { altKey: true }, { button: 2 }]
        .every((o) => canvas.onMouse(ev(395, 210, o)) === false) && !calls.length);
check("  click on a node (inside B, 2 px from the wire end): left alone", canvas.onMouse(ev(402, 210)) === false && !calls.length);
check("  an onMouse hooked earlier by another extension is still called first; if it says handled (returns true) we do not touch it",
      canvas.onMouse(ev(395, 210, { prevTrue: true })) === true && !calls.length && prevCalls > 0);
SETTINGS[M.GRAB_ID] = false;
check("  setting off: left alone", canvas.onMouse(ev(395, 210)) === false && !calls.length);
SETTINGS[M.GRAB_ID] = true;
canvas.linkConnector.isConnecting = true;
check("  already dragging a wire: left alone", canvas.onMouse(ev(395, 210)) === false && !calls.length);
canvas.linkConnector.isConnecting = false;
links.get(9).parentId = 4;
check("  wire with a reroute: left alone (the frontend handles reroutes itself)", canvas.onMouse(ev(395, 210)) === false);
delete links.get(9).parentId;
canvas.linkConnector.moveInputLink = () => { throw new Error("boom"); };
calls.length = 0;
check("  error on the frontend side: reset, hand back to the frontend (return false)",
      canvas.onMouse(ev(395, 210)) === false && J(calls) === J([["reset"]]), J(calls));
canvas.linkConnector.moveInputLink = (g, inp) => calls.push(["moveInputLink", inp.name]);

// hover highlight
const move = (x, y, o = {}) => elL.pointermove.forEach((f) => f({ x, y, buttons: 0, ...o }));
move(395, 210);
check("hovering near the input end: cursor becomes a hand", canvas.canvas.style.cursor === "grab");
const strokes = [];
const ctx = new Proxy({}, {
  get: (t, k) => (k in t ? t[k] : (...a) => { if (k === "stroke") strokes.push(t.strokeStyle); }),
  set: (t, k, v) => { t[k] = v; return true; },
});
canvas.onDrawForeground(ctx, [0, 0, 1000, 1000]);
check("  draws a yellow highlight (that end's third)", strokes.includes("#ffcc00"), J(strokes));
move(248, 162);
check("  moved to the middle of the wire: cursor restored", canvas.canvas.style.cursor === "");
move(395, 210, { buttons: 1 });
check("  moving with a button held (dragging something): no highlight", canvas.canvas.style.cursor === "");

sec("setup: node drag snapping");
// C at (0, 600), dragged to the left of B: raw recorded first, snaps to B's top edge / level wire
const C = nC;
canvas.isDragging = true;
canvas.selected_nodes = { 3: C };
canvas.draw();                                  // start a snap session, record raw
C.move(3, -395);                                // raw = (3, 205); B's top edge 200, left edge vs A's 0
canvas.draw();
check("dragged to 3 from A's left edge and 5 from B's top edge: snaps in both directions",
      J(C.pos) === J([0, 200]) && J(C._pcgRaw) === J([3, 205]), J([C.pos, C._pcgRaw]));
C.move(30, 0);
canvas.draw();
check("  pull another 30 to the right: x does not stick (computed from the pre-snap 33, beyond threshold from every edge)",
      C.pos[0] === 33 && C.pos[1] === 200, J(C.pos));
fireWin("keydown", { key: "Shift" });
canvas.draw();
check("  holding Shift: no snap (back to the pre-snap position), session cleared", J(C.pos) === J([33, 200]) && !C._pcgRaw,
      J([C.pos, C._pcgRaw]));
fireWin("keyup", { key: "Shift" });
canvas.draw();
C.move(-33, 0);
canvas.draw();
check("  releasing Shift starts a new session, snapping resumes", C.pos[0] === 0, J(C.pos));
canvas.isDragging = false;
canvas.draw();
check("release: session cleared, position stays where it snapped", !C._pcgRaw && C.pos[0] === 0);
// straightening a wire: C -> B (C's output y = C.y + 10, B's input y = 210)
links.set(10, { id: 10, origin_id: 3, origin_slot: 0, target_id: 2, target_slot: 0 });
C.pos = [-300, 1000];
canvas.isDragging = true;
canvas.draw();
C.move(0, -796);                                // raw y = 204 -> output 214, B input 210: off by -4
canvas.draw();
check("wire with one end on the dragged node: snaps level (both slots at the same height)",
      C.getConnectionPos(false, 0)[1] === 210, J(C.pos));
SETTINGS[M.SNAP_ID] = false;
canvas.draw();
C.move(0, 3);
canvas.draw();
check("  setting off: stays where it is, further dragging no longer snaps (not even 3 off)", C.pos[1] === 203 && !C._pcgRaw, J(C.pos));
SETTINGS[M.SNAP_ID] = true;
canvas.isDragging = false;
canvas.draw();
// dragging the wire's downstream node (B): B's input snaps level with A's output (y = 10)
links.delete(10);
canvas.selected_nodes = { 2: nB };
nB.pos = [400, 300];
canvas.isDragging = true;
canvas.draw();
nB.move(0, -296);                               // raw y = 4 -> input 14, A output 10: off by -4
canvas.draw();
check("dragging the downstream end: snaps level too", nB.getConnectionPos(true, 0)[1] === 10, J(nB.pos));
nB.move(0, 2);                                  // raw 6, pos 2 (snapped): the offset must be computed from raw, not pos
canvas.draw();
check("  moving 2 more after snapping: slot position computed from the pre-snap one, still within threshold -> still level",
      nB.getConnectionPos(true, 0)[1] === 10, J([nB.pos, nB._pcgRaw]));
canvas.isDragging = false;
canvas.draw();
// frontend Straight + "Follow ComfyUI": hit testing uses sharp corners (same as what is drawn)
SETTINGS[M.STYLE_ID] = M.STYLES[1];
canvas.links_render_mode = 0;
nB.pos = [400, 200];
const plS = M.linkPolyline(graph, links.get(9), canvas);
check("'Follow ComfyUI' + Straight: hit testing uses the frontend's own sharp polyline (corner in the middle at x = 300)",
      M.nearestOnPolyline(plS, [300, 10]).dist < 1e-9);
SETTINGS[M.STYLE_ID] = M.STYLES[0];
const plH = M.linkPolyline(graph, links.get(9), canvas);
check("  Houdini style: vertical segment hugs the output (x = 248), the exact middle is not on the wire",
      M.nearestOnPolyline(plH, [248, 110]).dist < 1e-9 && M.nearestOnPolyline(plH, [300, 10]).dist > 3);
canvas.links_render_mode = 2;
check("  Spline mode: bezier", M.linkPolyline(graph, links.get(9), canvas).length === 25);

sec("Reference dashed lines (pcg94): with a node selected, faint dashed lines to nodes it has parameter references with");
{
  const R = (x, y, w, h) => ({ x, y, w, h });
  let sg = M.refSegment(R(0, 0, 100, 50), R(300, 0, 100, 50));
  check("two boxes side by side: from the left box's right edge (100, 25) to the right box's left edge (300, 25)", J(sg) === J([[100, 25], [300, 25]]), J(sg));
  sg = M.refSegment(R(0, 0, 100, 50), R(0, 200, 100, 50));
  check("  stacked vertically: (50, 50) -> (50, 200)", J(sg) === J([[50, 50], [50, 200]]), J(sg));
  sg = M.refSegment(R(0, 0, 100, 100), R(200, 200, 100, 100));
  check("  diagonal: both ends exactly on the box corners (diagonal)", J(sg) === J([[100, 100], [200, 200]]), J(sg));
  sg = M.refSegment(R(0, 0, 200, 40), R(250, 300, 40, 200));
  const onEdge = (p, r) => (Math.abs(p[0] - r.x) < 1e-9 || Math.abs(p[0] - r.x - r.w) < 1e-9
    || Math.abs(p[1] - r.y) < 1e-9 || Math.abs(p[1] - r.y - r.h) < 1e-9);
  check("  boxes of different shapes: both ends land on their own box borders, and on the line between centers",
        sg && onEdge(sg[0], R(0, 0, 200, 40)) && onEdge(sg[1], R(250, 300, 40, 200))
        && Math.abs((sg[0][1] - 20) * (270 - 100) - (sg[0][0] - 100) * (400 - 20)) < 1e-6, J(sg));
  check("  two overlapping boxes: nothing drawn", M.refSegment(R(0, 0, 100, 100), R(50, 50, 100, 100)) === null
        && M.refSegment(R(0, 0, 100, 100), R(0, 0, 100, 100)) === null);
  const nb = { pos: [10, 40], size: [100, 60] };
  check("nodeRect: without getBounding, the box includes the title bar (30)", J(M.nodeRect(nb)) === J({ x: 10, y: 10, w: 100, h: 90 }));
  check("  uses getBounding when present (collapsed nodes have a different size)",
        J(M.nodeRect({ ...nb, getBounding: () => [1, 2, 3, 4] })) === J({ x: 1, y: 2, w: 3, h: 4 }));
  const q1 = new Node(41, 0, 0), q2 = new Node(42, 0, 0);
  check("selectedNodes: accepts both the old selected_nodes and the new selectedItems (no duplicates)", (() => {
    const set = M.selectedNodes({ selected_nodes: { 41: q1 }, selectedItems: new Set([q1, q2, { notANode: 1 }]) });
    return set.size === 2 && set.has(q1) && set.has(q2);
  })());
  // graph: src <- dst (dst.tx = ch("../src/tx")), panel <- dst (panel parameter name), other unrelated
  const mk = (id, title, x, y) => { const n = new Node(id, x, y, 120, 60); n.title = title; n.type = "PCG_X";
                                    n.properties = {}; n.widgets = [{ name: "tx", value: 0 }]; return n; };
  const src = mk(51, "src", 0, 0), dst = mk(52, "dst", 400, 0), other = mk(53, "other", 0, 400);
  dst.properties.pcg_bind = { tx: `=ch("@51/tx") * 2`, ty: "@51/ty" };
  other.properties.pcg_bind = { tx: "k:0:0  10:1" };            // keyframes do not count as references
  const G2 = { _nodes: [src, dst, other], links: new Map(),
               getNodeById(id) { return this._nodes.find((n) => String(n.id) === String(id)) ?? null; } };
  check("refLines: nothing selected, nothing drawn", M.refLines(G2, new Set()).length === 0);
  let rl = M.refLines(G2, new Set([dst]));
  check("  selecting dst, which references others: one line to src (two parameters referencing the same node draw only one)", rl.length === 1
        && rl[0].from === src && rl[0].to === dst && rl[0].params.length === 2, J(rl.map((x) => [x.from.id, x.to.id, x.params])));
  rl = M.refLines(G2, new Set([src]));
  check("  selecting the referenced src: drawn too (both directions count)", rl.length === 1 && rl[0].to === dst);
  check("  selecting the unrelated other: nothing drawn", M.refLines(G2, new Set([other])).length === 0);
  {
    const d2 = mk(54, "dst2", 400, 400);
    d2.properties.pcg_bind = { tx: "@51/tx" };
    const G3 = { ...G2, _nodes: [src, dst, d2] };
    const r3 = M.refLines(G3, new Set([src, dst, d2]));
    check("  src referenced by two nodes, all selected: two lines (one per node pair, not merged by source node)",
          J(r3.map((x) => `${x.from.id}>${x.to.id}`).sort()) === J(["51>52", "51>54"]), J(r3.map((x) => [x.from.id, x.to.id])));
  }
  // drawing: hooked into the onDrawForeground attached by setup
  const ops = [];
  const ctx2 = new Proxy({}, {
    get: (t, k) => (k in t ? t[k] : (...a) => ops.push([k, ...a])),
    set: (t, k, v) => { if (k === "lineWidth" || k === "strokeStyle") ops.push([k, v]); t[k] = v; return true; },
  });
  const g0 = canvas.graph, sel0 = canvas.selected_nodes, sc0 = canvas.ds.scale;
  canvas.graph = G2;
  canvas.selected_nodes = { 52: dst };
  canvas.ds.scale = 2;
  canvas.onDrawForeground(ctx2, [0, 0, 1000, 1000]);
  const seg = M.refSegment(M.nodeRect(src), M.nodeRect(dst));
  check("drawn: thin (1 / zoom = 0.5, 1 px on screen), dashed (3 / zoom), faint grey, from src's border to dst's border",
        ops.some((o) => o[0] === "setLineDash" && J(o[1]) === J([1.5, 1.5]))
        && ops.some((o) => o[0] === "lineWidth" && o[1] === 0.5)
        && ops.some((o) => o[0] === "strokeStyle" && /rgba\(.*0\.5\)/.test(o[1]))
        && ops.some((o) => o[0] === "moveTo" && o[1] === seg[0][0] && o[2] === seg[0][1])
        && ops.some((o) => o[0] === "lineTo" && o[1] === seg[1][0] && o[2] === seg[1][1])
        && M.lastRefLines.length === 1, J(ops.slice(0, 12)));
  const iDash = ops.findIndex((o) => o[0] === "setLineDash"), iStroke = ops.findIndex((o, i) => i > iDash && o[0] === "stroke");
  check("  restore right after drawing (dash / line width do not leak into what is drawn later)", iDash >= 0 && ops[iStroke + 1]?.[0] === "restore",
        J(ops.slice(iStroke, iStroke + 2)));
  ops.length = 0;
  SETTINGS[M.REFS_ID] = false;
  canvas.onDrawForeground(ctx2, [0, 0, 1000, 1000]);
  check("  turned off in settings: nothing drawn", !ops.some((o) => o[0] === "setLineDash") && M.lastRefLines.length === 0);
  SETTINGS[M.REFS_ID] = true;
  canvas.selected_nodes = {};
  ops.length = 0;
  canvas.onDrawForeground(ctx2, [0, 0, 1000, 1000]);
  check("  deselected: nothing drawn", !ops.some((o) => o[0] === "setLineDash"));
  canvas.graph = g0; canvas.selected_nodes = sel0; canvas.ds.scale = sc0;
}

console.log(`\n${OK.filter(Boolean).length}/${OK.length} passed`);
process.exit(OK.every(Boolean) ? 0 : 1);
