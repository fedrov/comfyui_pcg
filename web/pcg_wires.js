// comfyui_pcg/web/pcg_wires.js
//
// Houdini feel for the network editor (pcg85):
//
// 1) **Link style**: Houdini's Rounded links go "short stub out of the output -> right away a big rounded turn -> run vertically -> another rounded corner ->
//    a long run into the input" (Houdini flows vertically, we flow horizontally, so it's horizontal -> vertical -> horizontal, with the vertical part near the output end).
//    The frontend's built-in Straight mode is a sharp-cornered polyline bending exactly in the middle; here its path is replaced with this one. Drawing, the drag preview, and the link hit area (link.path)
//    all come from the same function, so selecting links, the midpoint menu and Y-key cutting all match what is drawn.
//    Settings -> PCG -> Houdini feel -> Link style can switch back to "Follow ComfyUI setting".
//
// 2) **Re-wiring one end of a link by dragging**: in Houdini, pressing and dragging near one end of a link pulls that end off and connects it elsewhere.
//    Same here -- when the mouse rests on the first third of a link (near the output) or the last third (near the input), that part
//    is highlighted and the cursor becomes a hand; press and drag:
//      · near the **input** end: the link is pulled off the input and follows the mouse; drop it on another node's input = rewire downstream;
//        drop it on empty space = disconnect (same as dragging out of an input slot in the frontend: ComfyUI's release menu / search box pops up)
//      · near the **output** end: a new link is pulled from this input to find an upstream; drop it on another output = change upstream;
//        dropping on empty space changes nothing (the original link stays)
//    The middle third of a link is still the frontend's midpoint menu. Everything goes through the frontend's own link dragging (LinkConnector),
//    so drop detection, type checking and undo are the same as dragging from a slot.
//
// 3) **Auto-align when dragging nodes**: dragging a node in Houdini snaps to positions where "the link becomes straight" and "aligned with neighbours". Here, while dragging a node:
//      · links to upstream/downstream: snap so the link is **horizontal** (both slots at the same height)
//      · nearby nodes: left-edge, right-edge, horizontal centerline and top-edge alignment
//    The threshold is 8 px on screen (independent of zoom); when snapped a cyan guide line is drawn. Hold Shift while dragging to not snap
//    (that is the frontend's own "snap to grid").
//    How: while dragging, the frontend calls move(dx, dy) on the selected nodes every frame; we record the "unsnapped" position in move,
//    and before each redraw compute the snap from it and set pos to the snapped value -- so snapping on and pulling away again doesn't drift further and further.

import { app } from "../../scripts/app.js";
import { refEdges } from "./pcg_params.js";

export const STYLE_ID = "PCG.Wire.Style";
export const STYLES = ["Houdini rounded polyline", "Follow ComfyUI setting"];
// Value saved by older versions (Chinese UI) for STYLES[0], still accepted when read
const LEGACY_STYLE0 = "Houdini \u5706\u89d2\u6298\u7ebf";
export const GRAB_ID = "PCG.Wire.GrabEnds";
export const SNAP_ID = "PCG.Node.Snap";
export const REFS_ID = "PCG.Wire.RefLinks";
const RADIUS = 40;          // corner radius (graph coordinates). Houdini's rounded corner is about twice the node height
const STUB = 8;             // the short straight stub out of the output
const PICK_PX = 7;          // how close to a link counts as "on the link" (screen pixels)
const SNAP_PX = 8;          // snapping threshold (screen pixels)
const END_FRAC = 1 / 3;     // a third at each end counts as an "end"
const GUIDE = "#5fe0d0";
const REF_COLOR = "rgba(210, 214, 220, 0.5)";   // a very faint gray-white, much weaker than real links

// ════════════════════════════════════════════════════ geometry (pure functions, unit-tested directly)
/**
 * Houdini's Rounded link: short stub out of the output -> right away a big rounded turn -> run vertically -> another rounded corner -> **a long** horizontal run into the input.
 * The turn hugs the output end, not the middle between the two nodes -- several inputs of the same node each come in on their own parallel horizontal run,
 * so you can see at a glance what connects to what (compare with Houdini screenshots: in a vertically flowing network the horizontal parts hug the bottom edge of the upstream node).
 *
 * Returns {pts, r}: pts is the polyline without rounding, pts[2] and pts[3] are the two corners; r is the actual radius:
 * at most RADIUS, reduced when the vertical difference is less than two radii or the horizontal room is less than stub + two radii; 0 when both ends are at the same height (a straight line).
 * Links going backwards (input left of the output, no horizontal room) fall back to "corners exactly in the middle", with a short stub at each end.
 */
export function elbow(a, b, radius = RADIUS) {
  const ax = a[0] + STUB, dy = Math.abs(b[1] - a[1]);
  const room = (b[0] - ax) / 2;
  if (room >= 0) {
    const r = Math.max(0, Math.min(radius, room, dy / 2));
    const xv = ax + r;
    return { pts: [[a[0], a[1]], [ax, a[1]], [xv, a[1]], [xv, b[1]], [b[0], b[1]]], r };
  }
  const bx = b[0] - STUB, m = (ax + bx) / 2;
  const r = Math.max(0, Math.min(radius, Math.abs(m - ax), dy / 2));
  return { pts: [[a[0], a[1]], [ax, a[1]], [m, a[1]], [m, b[1]], [bx, b[1]], [b[0], b[1]]], r };
}

/** Write the rounded polyline into a path (Path2D or canvas context): arcTo at the two corners, lineTo elsewhere. */
export function traceElbow(path, a, b, radius = RADIUS) {
  const { pts, r } = elbow(a, b, radius);
  path.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < pts.length; i++) {
    if (r > 0.01 && (i === 2 || i === 3)) path.arcTo(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], r);
    else path.lineTo(pts[i][0], pts[i][1]);
  }
  return path;
}

/** Sample the rounded polyline into a polyline (8 segments per corner), for hit testing / cutting. */
export function elbowPolyline(a, b, radius = RADIUS) {
  const { pts, r } = elbow(a, b, radius);
  const out = [pts[0]];
  const corner = (p0, p1, p2) => {
    // p1 is the corner; the rounding starts r back from p1 toward p0 and ends r from p1 toward p2 -- exactly the quarter circle arcTo draws
    const u = norm(p0, p1), v = norm(p2, p1);
    const c = [p1[0] + (u[0] + v[0]) * r, p1[1] + (u[1] + v[1]) * r];     // circle center
    const s = [p1[0] + u[0] * r - c[0], p1[1] + u[1] * r - c[1]];
    const e = [p1[0] + v[0] * r - c[0], p1[1] + v[1] * r - c[1]];
    const a0 = Math.atan2(s[1], s[0]);
    let da = Math.atan2(e[1], e[0]) - a0;
    while (da > Math.PI) da -= 2 * Math.PI;
    while (da < -Math.PI) da += 2 * Math.PI;
    for (let k = 0; k <= 8; k++) {
      const t = a0 + da * k / 8;
      out.push([c[0] + r * Math.cos(t), c[1] + r * Math.sin(t)]);
    }
  };
  for (let i = 1; i < pts.length; i++) {
    if (r > 0.01 && (i === 2 || i === 3)) corner(pts[i - 1], pts[i], pts[i + 1]);
    else out.push(pts[i]);
  }
  return dedupe(out);
}

/** The frontend's own Straight (sharp corners, bending exactly midway between the two slots, 10 at each end) -- used for hit testing in "Follow ComfyUI". */
export function straightPolyline(a, b) {
  const ax = a[0] + 10, bx = b[0] - 10, m = (ax + bx) / 2;
  return dedupe([[a[0], a[1]], [ax, a[1]], [m, a[1]], [m, b[1]], [bx, b[1]], [b[0], b[1]]]);
}

/** Sampling of the cubic Bézier of the frontend's Spline mode (control points: both ends offset horizontally by max(30, distance × 0.25)). */
export function splinePolyline(a, b, n = 24) {
  const d = Math.max(30, Math.hypot(b[0] - a[0], b[1] - a[1]) * 0.25);
  const c1 = [a[0] + d, a[1]], c2 = [b[0] - d, b[1]];
  const out = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n, s = 1 - t;
    const w0 = s * s * s, w1 = 3 * s * s * t, w2 = 3 * s * t * t, w3 = t * t * t;
    out.push([a[0] * w0 + c1[0] * w1 + c2[0] * w2 + b[0] * w3,
              a[1] * w0 + c1[1] * w1 + c2[1] * w2 + b[1] * w3]);
  }
  return out;
}

function norm(p, q) {
  const dx = p[0] - q[0], dy = p[1] - q[1];
  const l = Math.hypot(dx, dy) || 1;
  return [dx / l, dy / l];
}

function dedupe(pts) {
  return pts.filter((p, i) => i === 0 || Math.hypot(p[0] - pts[i - 1][0], p[1] - pts[i - 1][1]) > 1e-6);
}

/** Closest place on a polyline to a point: {dist, t} (t by arc length, 0 = output end, 1 = input end). */
export function nearestOnPolyline(pts, p) {
  let total = 0;
  const seg = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const l = Math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]);
    seg.push(l);
    total += l;
  }
  let best = { dist: Infinity, t: 0 }, acc = 0;
  for (let i = 0; i < seg.length; i++) {
    const [x0, y0] = pts[i], [x1, y1] = pts[i + 1];
    const l = seg[i];
    let u = l > 0 ? ((p[0] - x0) * (x1 - x0) + (p[1] - y0) * (y1 - y0)) / (l * l) : 0;
    u = Math.max(0, Math.min(1, u));
    const d = Math.hypot(x0 + u * (x1 - x0) - p[0], y0 + u * (y1 - y0) - p[1]);
    if (d < best.dist) best = { dist: d, t: total > 0 ? (acc + u * l) / total : 0 };
    acc += l;
  }
  return best;
}

/** Halfway point of a polyline by arc length: {x, y, angle} (angle is the direction of that segment, for the midpoint arrow). */
export function midpointOf(pts) {
  const L = [];
  let total = 0;
  for (let i = 0; i < pts.length - 1; i++) {
    const l = Math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]);
    L.push(l); total += l;
  }
  let acc = 0;
  for (let i = 0; i < L.length; i++) {
    if (acc + L[i] >= total / 2 && L[i] > 0) {
      const u = (total / 2 - acc) / L[i];
      const [x0, y0] = pts[i], [x1, y1] = pts[i + 1];
      return { x: x0 + u * (x1 - x0), y: y0 + u * (y1 - y0), angle: Math.atan2(y1 - y0, x1 - x0) };
    }
    acc += L[i];
  }
  const p = pts[pts.length - 1];
  return { x: p[0], y: p[1], angle: 0 };
}

/** Which end of the link: "out" / "in" / null (middle third, left to the frontend's midpoint menu). */
export function whichEnd(t) {
  if (t <= END_FRAC) return "out";
  if (t >= 1 - END_FRAC) return "in";
  return null;
}

/**
 * Snapping: moving is the box of the node being dragged (unsnapped), others are the boxes of the other nodes, wires are links with one end on
 * the dragged node [{dy}] (how much more to move to make that link horizontal). Returns {dx, dy, gx, gy}:
 * the offset to add, and the snapped guide lines (gx = x of the vertical line, gy = y of the horizontal line; null when not snapped).
 * Threshold tol is in graph coordinates. For x and y the nearest candidate is taken separately.
 */
export function planSnap(moving, others, wires, tol) {
  let bx = null, by = null;
  const tryX = (d, g) => { if (Math.abs(d) <= tol && (!bx || Math.abs(d) < Math.abs(bx.d))) bx = { d, g }; };
  const tryY = (d, g) => { if (Math.abs(d) <= tol && (!by || Math.abs(d) < Math.abs(by.d))) by = { d, g }; };
  for (const w of wires) tryY(w.dy, w.y);
  for (const m of moving) {
    for (const o of others) {
      // Only align with "nearby" nodes: those too far away in the other direction don't count, otherwise it would snap to things all over the graph
      const nearV = Math.abs((o.y + o.h / 2) - (m.y + m.h / 2)) < 1200;
      const nearH = Math.abs((o.x + o.w / 2) - (m.x + m.w / 2)) < 1200;
      if (nearV || nearH) {
        tryX(o.x - m.x, o.x);                                   // left edges aligned
        tryX((o.x + o.w) - (m.x + m.w), o.x + o.w);             // right edges aligned
        tryX((o.x + o.w / 2) - (m.x + m.w / 2), o.x + o.w / 2); // centerlines aligned
        tryY(o.y - m.y, o.y);                                   // top edges aligned
      }
    }
  }
  return { dx: bx ? bx.d : 0, dy: by ? by.d : 0, gx: bx ? bx.g : null, gy: by ? by.g : null };
}

// ════════════════════════════════════════════════════ frontend wiring
function setting(id, dflt) {
  try {
    const v = app.extensionManager?.setting?.get?.(id) ?? app.ui?.settings?.getSettingValue?.(id);
    return v ?? dflt;
  } catch (e) {
    return dflt;
  }
}
const houdiniStyle = () => { const v = setting(STYLE_ID, STYLES[0]); return v === STYLES[0] || v === LEGACY_STYLE0; };

function linksOf(graph) {
  const l = graph?.links;
  if (!l) return [];
  return l instanceof Map ? [...l.values()] : Object.values(l);
}

/** The polyline of a link in the graph (in the current drawing style). Links with reroutes are skipped (the frontend handles reroutes itself). */
export function linkPolyline(graph, link, canvas) {
  if (!link || link.parentId != null) return null;
  const A = graph.getNodeById?.(link.origin_id), B = graph.getNodeById?.(link.target_id);
  if (!A || !B || !A.getConnectionPos || !B.getConnectionPos) return null;
  const a = A.getConnectionPos(false, link.origin_slot, [0, 0]);
  const b = B.getConnectionPos(true, link.target_slot, [0, 0]);
  const straight = canvas?.links_render_mode === globalThis.LiteGraph?.STRAIGHT_LINK;
  return straight ? (houdiniStyle() ? elbowPolyline(a, b) : straightPolyline(a, b))
    : splinePolyline(a, b);
}

/** The link nearest to the mouse (graph coordinates) that is within the third at one of its ends: {link, end, pts}. */
export function pickWireEnd(graph, canvas, p, tol) {
  let best = null;
  for (const link of linksOf(graph)) {
    const pts = linkPolyline(graph, link, canvas);
    if (!pts) continue;
    const hit = nearestOnPolyline(pts, p);
    if (hit.dist > tol || (best && hit.dist >= best.dist)) continue;
    best = { link, end: whichEnd(hit.t), pts, dist: hit.dist, t: hit.t };
  }
  return best && best.end ? best : null;
}

/** The part t0 ~ t1 (arc-length fraction) of a polyline, for drawing the highlight. */
export function subPolyline(pts, t0, t1) {
  const L = [];
  let total = 0;
  for (let i = 0; i < pts.length - 1; i++) {
    const l = Math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]);
    L.push(l); total += l;
  }
  const out = [];
  let acc = 0;
  const at = (i, u) => [pts[i][0] + u * (pts[i + 1][0] - pts[i][0]), pts[i][1] + u * (pts[i + 1][1] - pts[i][1])];
  for (let i = 0; i < L.length; i++) {
    const s = acc / total, e = (acc + L[i]) / total;
    if (e >= t0 && s <= t1) {
      const u0 = Math.max(0, (t0 - s) / ((e - s) || 1)), u1 = Math.min(1, (t1 - s) / ((e - s) || 1));
      if (!out.length) out.push(at(i, u0));
      out.push(at(i, u1));
    }
    acc += L[i];
  }
  return out;
}

// ════════════════════════════════════════════════════ reference dashed lines (pcg94)
//
// When a node is selected, Houdini draws a very faint, thin dashed line to the nodes it has channel references with (pasted relative references, ch() expressions, things like
// npoints). Same here: only those related to the **selected node** (what it references, what references it); nothing selected, nothing drawn --
// drawing them all would fill a big graph with dashed lines mixed in with the real links. Lines go from one node's border to the other's border,
// not over the nodes at either end.

/** The box a node occupies in the graph (including the title bar; collapsed nodes use the collapsed size). */
export function nodeRect(n) {
  const b = n.getBounding?.();
  if (b && b[2] > 0 && b[3] > 0) return { x: b[0], y: b[1], w: b[2], h: b[3] };
  const th = globalThis.LiteGraph?.NODE_TITLE_HEIGHT ?? 30;
  return { x: n.pos[0], y: n.pos[1] - th, w: n.size[0], h: n.size[1] + th };
}

/** Line between the centers of two boxes, with the parts inside the boxes trimmed -> [start, end]; null when the boxes overlap. */
export function refSegment(a, b) {
  const ca = [a.x + a.w / 2, a.y + a.h / 2], cb = [b.x + b.w / 2, b.y + b.h / 2];
  const dx = cb[0] - ca[0], dy = cb[1] - ca[1];
  // Parameter needed to leave the box from the center along (dx, dy): the smaller of half-width / |dx| and half-height / |dy|
  const exit = (r) => Math.min(dx ? r.w / 2 / Math.abs(dx) : Infinity, dy ? r.h / 2 / Math.abs(dy) : Infinity);
  const t0 = exit(a), t1 = 1 - exit(b);
  if (!(t0 < t1)) return null;
  return [[ca[0] + dx * t0, ca[1] + dy * t0], [ca[0] + dx * t1, ca[1] + dy * t1]];
}

/** Set of selected nodes (both old and new frontend storage are recognized). */
export function selectedNodes(canvas) {
  const out = new Set(Object.values(canvas?.selected_nodes || {}));
  for (const it of canvas?.selectedItems || []) if (it && it.pos && it.size && "id" in it) out.add(it);
  return out;
}

/** Reference dashed lines to draw: the edges related to the selected nodes, one line per node pair. */
export function refLines(graph, sel) {
  if (!sel.size) return [];
  // There is only one edge per node pair: refSources already grouped by source node (several parameters of one node referencing the same node
  // are all listed in params), so no further dedup is needed here
  const out = [];
  for (const e of refEdges(graph)) {
    if (!sel.has(e.from) && !sel.has(e.to)) continue;
    const seg = refSegment(nodeRect(e.from), nodeRect(e.to));
    if (seg) out.push({ from: e.from, to: e.to, params: e.params, seg });
  }
  return out;
}

export let lastRefLines = [];              // which ones were drawn in the latest frame (for tests / e2e)

function boxOf(n, pos = n.pos) {
  // pos is the bottom edge of the title bar, size excludes the title bar. Alignment only compares "differences between two nodes"; the title bars are the same height on both,
  // so adding it or not makes no difference, and it isn't added
  return { x: pos[0], y: pos[1], w: n.size[0], h: n.size[1] };
}

app.registerExtension({
  name: "pcg.wires",
  settings: [
    { id: STYLE_ID, category: ["PCG", "Houdini feel", "Link style"],
      name: "Link style (Houdini: horizontal -> rounded -> vertical -> rounded -> horizontal)", type: "combo",
      options: STYLES, defaultValue: STYLES[0] },
    { id: GRAB_ID, category: ["PCG", "Houdini feel", "Drag link ends"],
      name: "Press and drag near either end of a link = rewire that end elsewhere", type: "boolean", defaultValue: true },
    { id: SNAP_ID, category: ["PCG", "Houdini feel", "Node snapping"],
      name: "When dragging nodes, snap so links straighten / align with nearby nodes (hold Shift to not snap)", type: "boolean", defaultValue: true },
    { id: REFS_ID, category: ["PCG", "Houdini feel", "Reference dashed lines"],
      name: "When a node is selected, draw faint dashed lines to nodes it has parameter references with (ch / relative references)", type: "boolean", defaultValue: true },
  ],

  async setup() {
    const canvas = app.canvas;
    const LG = globalThis.LiteGraph;
    if (!canvas || !LG) return;

    // ── 1) link style ───────────────────────────────────────────────
    const pr = canvas.linkRenderer?.pathRenderer;
    if (pr?.buildStraightPath) {
      const orig = pr.buildStraightPath.bind(pr);
      pr.buildStraightPath = function (path, s, e, sd, ed) {
        // Only handle horizontal links (output facing right, input facing left); upward / downward ones (collapsed nodes etc.) go to the original.
        // The dragged end of a drag preview has no direction ("none"); draw it horizontally too -- otherwise it's sharp while dragging and rounded on release
        const vertical = (d) => d === "up" || d === "down";
        if (!houdiniStyle() || vertical(sd) || vertical(ed) || sd === "left" || ed === "right")
          return orig(path, s, e, sd, ed);
        traceElbow(path, [s.x, s.y], [e.x, e.y]);
      };
      // The small dot / arrow at the link midpoint (click for the midpoint menu): the frontend places it "exactly between the two slots"; after changing the routing
      // that dot floats in empty space. Move it to the halfway point by arc length of our link, with the direction following that segment
      if (pr.calculateCenterPoint) {
        const origC = pr.calculateCenterPoint.bind(pr);
        pr.calculateCenterPoint = function (link, ctx) {
          origC(link, ctx);
          if (ctx?.style?.mode !== "straight" || !houdiniStyle()) return;
          const sd = link.startDirection, ed = link.endDirection;
          if (sd === "up" || sd === "down" || ed === "up" || ed === "down" || sd === "left" || ed === "right") return;
          const c = midpointOf(elbowPolyline([link.startPoint.x, link.startPoint.y],
                                             [link.endPoint.x, link.endPoint.y]));
          link.centerPos = { x: c.x, y: c.y };
          if (link.centerAngle !== undefined) link.centerAngle = c.angle;
        };
      }
    } else {
      console.warn("[pcg.wires] this frontend version has no pathRenderer.buildStraightPath, link style has no effect");
    }
    // Houdini style = the frontend's Straight mode + rounding. Check before every draw (if the ComfyUI setting changed, force it back too)
    let lastForced = null;
    const keepMode = () => {
      if (houdiniStyle()) {
        if (canvas.links_render_mode !== LG.STRAIGHT_LINK) {
          // Remember the latest one ComfyUI set (if the user changed it again in ComfyUI settings, use the new one when switching back)
          lastForced = canvas.links_render_mode;
          canvas.links_render_mode = LG.STRAIGHT_LINK;
          canvas.setDirty(true, true);
        }
      } else if (lastForced !== null) {
        canvas.links_render_mode = lastForced;      // switching back: restore what's in the ComfyUI settings
        lastForced = null;
        canvas.setDirty(true, true);
      }
    };

    // ── 3) node snapping while dragging ────────────────────────────────────────────
    const proto = LG.LGraphNode?.prototype;
    if (proto?.move && !proto._pcgSnapWrapped) {
      const move = proto.move;
      proto.move = function (dx, dy) {
        if (this._pcgRaw) { this._pcgRaw[0] += dx; this._pcgRaw[1] += dy; }
        return move.apply(this, arguments);
      };
      proto._pcgSnapWrapped = true;
    }
    let shift = false;
    window.addEventListener("keydown", (e) => { if (e.key === "Shift") shift = true; }, true);
    window.addEventListener("keyup", (e) => { if (e.key === "Shift") shift = false; }, true);
    window.addEventListener("blur", () => { shift = false; });
    let snap = null;          // {nodes, guide}
    const snapStep = () => {
      const g = canvas.graph;
      if (!g) return;
      const dragging = canvas.isDragging && !canvas.linkConnector?.isConnecting;
      const sel = Object.values(canvas.selected_nodes || {});
      if (!dragging || !sel.length || shift || !setting(SNAP_ID, true)) {
        if (snap) {
          for (const n of snap.nodes) delete n._pcgRaw;
          snap = null;
          canvas.setDirty(true, true);
        }
        return;
      }
      if (!snap) {
        snap = { nodes: sel, guide: null };
        for (const n of sel) n._pcgRaw = [n.pos[0], n.pos[1]];
      }
      const moving = new Set(snap.nodes);
      const tol = SNAP_PX / (canvas.ds?.scale || 1);
      const boxes = snap.nodes.map((n) => boxOf(n, n._pcgRaw));
      const others = (canvas.visible_nodes || g._nodes || []).filter((n) => !moving.has(n))
        .map((n) => boxOf(n));
      // Links with one end on the dragged node and the other not: how far it still is from horizontal
      const wires = [];
      for (const link of linksOf(g)) {
        if (!link || link.parentId != null) continue;
        const A = g.getNodeById(link.origin_id), B = g.getNodeById(link.target_id);
        if (!A || !B || moving.has(A) === moving.has(B)) continue;
        const a = A.getConnectionPos(false, link.origin_slot, [0, 0]);
        const b = B.getConnectionPos(true, link.target_slot, [0, 0]);
        // Slot positions are computed from the current pos; switch to the "unsnapped" one
        if (moving.has(A)) { a[1] += A._pcgRaw[1] - A.pos[1]; wires.push({ dy: b[1] - a[1], y: b[1] }); }
        else { b[1] += B._pcgRaw[1] - B.pos[1]; wires.push({ dy: a[1] - b[1], y: a[1] }); }
      }
      const s = planSnap(boxes, others, wires, tol);
      for (const n of snap.nodes) {
        const nx = n._pcgRaw[0] + s.dx, ny = n._pcgRaw[1] + s.dy;
        if (n.pos[0] !== nx || n.pos[1] !== ny) {
          if (n.setPos) n.setPos(nx, ny); else { n.pos[0] = nx; n.pos[1] = ny; }
        }
      }
      snap.guide = s;
    };

    // ── 2) dragging link ends ────────────────────────────────────────────────
    let hover = null;          // {link, end, pts}
    const tolNow = () => PICK_PX / (canvas.ds?.scale || 1);
    const prevOnMouse = canvas.onMouse;
    canvas.onMouse = function (e) {
      if (prevOnMouse?.call(this, e) === true) return true;
      if (e.button !== 0 || e.shiftKey || e.ctrlKey || e.metaKey || e.altKey) return false;
      if (!setting(GRAB_ID, true) || this.read_only || this.linkConnector?.isConnecting) return false;
      const g = this.graph;
      if (!g) return false;
      const p = [e.canvasX, e.canvasY];
      if (g.getNodeOnPos?.(p[0], p[1], this.visible_nodes)) return false;   // clicked on a node
      const hit = pickWireEnd(g, this, p, tolNow());
      if (!hit) return false;
      const lc = this.linkConnector;
      const B = g.getNodeById(hit.link.target_id);
      const input = B?.inputs?.[hit.link.target_slot];
      if (!lc || !B || !input) return false;
      try {
        if (hit.end === "in") lc.moveInputLink(g, input);       // pull off the downstream end
        else lc.dragNewFromInput(g, B, input);                   // pull back from the input, change upstream
        this._linkConnectorDrop();
      } catch (err) {
        console.warn("[pcg.wires] dragging link end failed", err);
        try { lc.reset?.(true); } catch (_) { /* */ }
        return false;
      }
      hover = null;
      this.setDirty(true, true);
      return true;
    };

    const el = canvas.canvas;
    el?.addEventListener("pointermove", (e) => {
      if (e.buttons || canvas.isDragging || canvas.linkConnector?.isConnecting
          || !setting(GRAB_ID, true)) {
        if (hover) { hover = null; el.style.cursor = ""; canvas.setDirty(true, true); }
        return;
      }
      const g = canvas.graph;
      const p = canvas.convertEventToCanvasOffset?.(e);
      if (!g || !p) return;
      const over = g.getNodeOnPos?.(p[0], p[1], canvas.visible_nodes);
      const h = over ? null : pickWireEnd(g, canvas, p, tolNow());
      const same = h && hover && h.link.id === hover.link.id && h.end === hover.end;
      if (!same && (h || hover)) {
        hover = h;
        canvas.setDirty(true, true);
      }
      if (h) el.style.cursor = "grab";
      else if (el.style.cursor === "grab") el.style.cursor = "";
    }, { passive: true });

    // ── drawing: snap guide lines, link-end highlight; before every frame keep the link mode and snapping ─────────────
    const prevFg = canvas.onDrawForeground;
    canvas.onDrawForeground = function (ctx, area) {
      prevFg?.call(this, ctx, area);
      const sc = this.ds?.scale || 1;
      try {
        lastRefLines = setting(REFS_ID, true) ? refLines(this.graph || app.graph, selectedNodes(this)) : [];
      } catch (err) { lastRefLines = []; }
      if (lastRefLines.length) {
        ctx.save();
        ctx.strokeStyle = REF_COLOR;
        ctx.lineWidth = 1 / sc;                 // always 1 px on screen, independent of zoom
        ctx.setLineDash([3 / sc, 3 / sc]);
        ctx.beginPath();
        for (const { seg } of lastRefLines) { ctx.moveTo(seg[0][0], seg[0][1]); ctx.lineTo(seg[1][0], seg[1][1]); }
        ctx.stroke();
        ctx.restore();
      }
      if (snap?.guide && (snap.guide.gx !== null || snap.guide.gy !== null)) {
        ctx.save();
        ctx.strokeStyle = GUIDE;
        ctx.lineWidth = 1 / sc;
        ctx.setLineDash([6 / sc, 4 / sc]);
        const vis = this.visible_area || [-1e5, -1e5, 2e5, 2e5];
        ctx.beginPath();
        if (snap.guide.gx !== null) { ctx.moveTo(snap.guide.gx, vis[1]); ctx.lineTo(snap.guide.gx, vis[1] + vis[3]); }
        if (snap.guide.gy !== null) { ctx.moveTo(vis[0], snap.guide.gy); ctx.lineTo(vis[0] + vis[2], snap.guide.gy); }
        ctx.stroke();
        ctx.restore();
      }
      if (hover) {
        const seg = hover.end === "out" ? subPolyline(hover.pts, 0, END_FRAC)
          : subPolyline(hover.pts, 1 - END_FRAC, 1);
        if (seg.length > 1) {
          ctx.save();
          ctx.strokeStyle = "#ffcc00";
          ctx.globalAlpha = 0.85;
          ctx.lineWidth = 5 / sc;
          ctx.lineCap = "round";
          ctx.beginPath();
          ctx.moveTo(seg[0][0], seg[0][1]);
          for (const q of seg.slice(1)) ctx.lineTo(q[0], q[1]);
          ctx.stroke();
          ctx.restore();
        }
      }
    };
    const draw = canvas.draw;
    canvas.draw = function () {
      try { keepMode(); snapStep(); } catch (err) { /* don't let the canvas stop */ }
      return draw.apply(this, arguments);
    };
    console.log("[pcg.wires] Houdini feel: rounded links / drag link ends to rewire / node snapping");
  },
});

// for unit tests
export const __internal = { RADIUS, STUB, END_FRAC, boxOf };
