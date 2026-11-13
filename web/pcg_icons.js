// comfyui_pcg/web/pcg_icons.js
//
// Each PCG node gets a **vector icon** drawn at the left of its title bar, plus a color bar per category.
// With dozens of nodes on screen, title text has to be read to be recognized; shapes can be told apart at a glance.
//
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Why vector paths, not emoji
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// emoji take one line of code, but: the glyphs follow the operating system (Windows / mac / Linux, three
// completely different styles), colored emoji blur into a blob on a dark title bar, and at 12px most of them
// are unrecognizable. Vector paths are drawn by us: crisp at any zoom, colored by category, consistent in style.
//
// The cost is hand-writing sixty-odd icons. So there's a **contact sheet** (tools/render_icons.mjs):
// render all icons into one image and look at it, rather than writing them blind and shipping.
//
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Hooked on onDrawTitleBox, **node.color is not touched**
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// When litegraph draws the title it calls `node.onDrawTitleBox(ctx, h, size, scale)` to draw the small dot
// on the left -- defining it replaces that dot; position and timing come for free, and it's the most stable across versions.
//
// The more tempting approach is to set `node.color` directly to color the title bar. We don't, because litegraph's
// `serialize()` saves color into the workflow: once written, later palette changes don't apply to old graphs,
// and colors the user set themselves get overwritten. What's drawn doesn't go into the data; that's not worth breaking to save effort.
//
// All drawing is wrapped in try/catch: an icon drawing failure must not take the whole canvas down with it.

import { app } from "../../scripts/app.js";

export const PREFIX = "PCG_";

// ─────────────────────────────────────────────── drawing helpers
// All icons are drawn in [-1,1] × [-1,1], y down. The caller handles scaling and line width.
function poly(c, pts, close, fill) {
  c.beginPath();
  for (let i = 0; i < pts.length; i += 2) {
    if (i === 0) c.moveTo(pts[0], pts[1]);
    else c.lineTo(pts[i], pts[i + 1]);
  }
  if (close) c.closePath();
  if (fill) c.fill(); else c.stroke();
}
function line(c, x1, y1, x2, y2) {
  c.beginPath(); c.moveTo(x1, y1); c.lineTo(x2, y2); c.stroke();
}
function circ(c, x, y, r, fill) {
  c.beginPath(); c.arc(x, y, r, 0, Math.PI * 2);
  if (fill) c.fill(); else c.stroke();
}
function dots(c, pts, r) {
  for (let i = 0; i < pts.length; i += 2) circ(c, pts[i], pts[i + 1], r, true);
}
function rect(c, x, y, w, h, fill) {
  c.beginPath(); c.rect(x, y, w, h);
  if (fill) c.fill(); else c.stroke();
}
function arrow(c, x1, y1, x2, y2, hs) {
  hs = hs || 0.3;
  line(c, x1, y1, x2, y2);
  const a = Math.atan2(y2 - y1, x2 - x1);
  poly(c, [x2 - hs * Math.cos(a - 0.5), y2 - hs * Math.sin(a - 0.5),
           x2, y2,
           x2 - hs * Math.cos(a + 0.5), y2 - hs * Math.sin(a + 0.5)],
       false, false);
}
function dash(c, on) {
  if (c.setLineDash) c.setLineDash(on ? [0.25, 0.22] : []);
}
function grid3(c, r) {
  const p = [];
  for (const y of [-0.62, 0, 0.62]) for (const x of [-0.62, 0, 0.62]) p.push(x, y);
  dots(c, p, r || 0.16);
}

// ─────────────────────────────────────────────── icon table
export const GLYPHS = {
  // ── generators ──────────────────────────────────────────────
  box(c) {
    rect(c, -0.85, -0.45, 1.3, 1.3, false);
    poly(c, [-0.85, -0.45, -0.4, -0.9, 0.85, -0.9, 0.85, 0.4, 0.45, 0.85],
         false, false);
    line(c, 0.45, -0.45, 0.85, -0.9);
  },
  sphere(c) {
    circ(c, 0, 0, 0.85, false);
    c.beginPath(); c.ellipse(0, 0, 0.85, 0.32, 0, 0, Math.PI * 2); c.stroke();
  },
  tube(c) {
    c.beginPath(); c.ellipse(0, -0.6, 0.65, 0.25, 0, 0, Math.PI * 2); c.stroke();
    line(c, -0.65, -0.6, -0.65, 0.6);
    line(c, 0.65, -0.6, 0.65, 0.6);
    c.beginPath(); c.ellipse(0, 0.6, 0.65, 0.25, 0, 0, Math.PI); c.stroke();
  },
  grid(c) {
    rect(c, -0.85, -0.85, 1.7, 1.7, false);
    line(c, -0.28, -0.85, -0.28, 0.85); line(c, 0.28, -0.85, 0.28, 0.85);
    line(c, -0.85, -0.28, 0.85, -0.28); line(c, -0.85, 0.28, 0.85, 0.28);
  },
  circle(c) { circ(c, 0, 0, 0.82, false); },
  line(c) {
    poly(c, [-0.85, 0.5, -0.2, -0.55, 0.3, 0.3, 0.85, -0.6], false, false);
    dots(c, [-0.85, 0.5, -0.2, -0.55, 0.3, 0.3, 0.85, -0.6], 0.15);
  },
  // A drawn curve: an S-shaped curve + three control points + a pen tip
  curve_draw(c) {
    c.beginPath(); c.moveTo(-0.85, 0.55);
    c.bezierCurveTo(-0.3, -0.75, 0.25, 0.75, 0.62, -0.35); c.stroke();
    dots(c, [-0.85, 0.55, -0.12, 0.0, 0.62, -0.35], 0.14);
    poly(c, [0.62, -0.35, 0.95, -0.75, 0.82, -0.88], true, false);
  },
  sweep(c) {
    c.beginPath(); c.moveTo(-0.85, 0.6);
    c.bezierCurveTo(-0.2, 0.6, -0.1, -0.6, 0.85, -0.6); c.stroke();
    rect(c, -0.32, -0.15, 0.62, 0.62, false);
  },
  skin(c) {
    c.beginPath(); c.moveTo(-0.85, -0.7);
    c.bezierCurveTo(-0.2, -0.2, 0.2, -0.2, 0.85, -0.7); c.stroke();
    c.beginPath(); c.moveTo(-0.85, 0.7);
    c.bezierCurveTo(-0.2, 0.2, 0.2, 0.2, 0.85, 0.7); c.stroke();
    line(c, -0.85, -0.7, -0.85, 0.7); line(c, 0, -0.32, 0, 0.32);
    line(c, 0.85, -0.7, 0.85, 0.7);
  },
  add(c) {
    dots(c, [-0.6, 0.45, 0.15, 0.55, 0.6, -0.2], 0.17);
    line(c, -0.55, -0.6, 0.15, -0.6); line(c, -0.2, -0.95, -0.2, -0.25);
  },

  // ── pcg67: curve frames and copying, paths and networks ────────────────────
  // A curve + three small frames along it (tangent arrow + short up-vector line)
  orient_curve(c) {
    c.beginPath(); c.moveTo(-0.9, 0.55);
    c.bezierCurveTo(-0.3, 0.9, 0.2, -0.9, 0.9, -0.45); c.stroke();
    arrow(c, -0.55, 0.62, -0.2, 0.42, 0.18);
    line(c, -0.55, 0.62, -0.72, 0.3);
    arrow(c, 0.45, -0.52, 0.8, -0.5, 0.18);
    line(c, 0.45, -0.52, 0.4, -0.86);
  },
  // A face + three axes on it (N pointing out, tangentu / tangentv in the face)
  polyframe(c) {
    poly(c, [-0.85, 0.35, 0.05, 0.75, 0.85, 0.2, -0.05, -0.2], true, false);
    arrow(c, 0, 0.28, 0, -0.85, 0.22);
    arrow(c, 0, 0.28, 0.6, 0.45, 0.18);
    arrow(c, 0, 0.28, -0.55, 0.05, 0.18);
  },
  // A box copied diagonally upward, getting smaller (cumulative transform)
  copy_xform(c) {
    rect(c, -0.9, 0.3, 0.55, 0.55, false);
    rect(c, -0.3, -0.2, 0.42, 0.42, false);
    rect(c, 0.22, -0.62, 0.3, 0.3, false);
    rect(c, 0.62, -0.92, 0.2, 0.2, false);
  },
  // Cross-section + rotation arrow + axis line
  revolve(c) {
    dash(c, true); line(c, 0, -0.95, 0, 0.95); dash(c, false);
    c.beginPath(); c.moveTo(0.05, -0.8);
    c.bezierCurveTo(0.75, -0.6, 0.35, 0.2, 0.75, 0.8); c.stroke();
    c.beginPath(); c.ellipse(0, 0.05, 0.75, 0.22, 0, Math.PI * 0.15,
                             Math.PI * 1.1); c.stroke();
    arrow(c, -0.7, 0.14, -0.75, 0.0, 0.18);
  },
  // Small squares evenly spaced along a curve
  copy_curve(c) {
    c.beginPath(); c.moveTo(-0.9, 0.6);
    c.bezierCurveTo(-0.3, -0.6, 0.3, 0.8, 0.9, -0.5); c.stroke();
    rect(c, -0.78, 0.05, 0.3, 0.3, true);
    rect(c, -0.12, -0.05, 0.3, 0.3, true);
    rect(c, 0.5, -0.2, 0.3, 0.3, true);
  },
  // Chain links: two vertical ellipses around a horizontal one
  chain(c) {
    c.beginPath(); c.ellipse(-0.55, 0, 0.36, 0.2, 0, 0, Math.PI * 2); c.stroke();
    c.beginPath(); c.ellipse(0, 0, 0.14, 0.36, 0, 0, Math.PI * 2); c.stroke();
    c.beginPath(); c.ellipse(0.55, 0, 0.36, 0.2, 0, 0, Math.PI * 2); c.stroke();
  },
  // Grid mesh + a bold polyline path with a point at each end
  shortest_path(c) {
    for (const v of [-0.6, 0, 0.6]) {
      line(c, v, -0.85, v, 0.85); line(c, -0.85, v, 0.85, v);
    }
    c.lineWidth *= 2.2;
    poly(c, [-0.6, 0.6, 0, 0.6, 0, 0, 0.6, 0, 0.6, -0.6], false, false);
    c.lineWidth /= 2.2;
    dots(c, [-0.6, 0.6, 0.6, -0.6], 0.2);
  },
  // A few points + a dashed path linking them (written as a group, no new geometry)
  group_path(c) {
    rect(c, -0.9, -0.9, 1.8, 1.8, false);
    dash(c, true);
    poly(c, [-0.55, 0.55, -0.1, 0.1, 0.25, 0.35, 0.55, -0.5], false, false);
    dash(c, false);
    dots(c, [-0.55, 0.55, 0.25, 0.35, 0.55, -0.5], 0.16);
  },
  // Two intersecting curves, a hollow ring at the intersection
  curve_x(c) {
    c.beginPath(); c.moveTo(-0.9, 0.7);
    c.bezierCurveTo(-0.3, 0.3, 0.3, -0.3, 0.9, -0.75); c.stroke();
    c.beginPath(); c.moveTo(-0.85, -0.7);
    c.bezierCurveTo(-0.2, -0.5, 0.2, 0.5, 0.85, 0.75); c.stroke();
    circ(c, 0, 0, 0.26, false);
  },
  // ── pcg68: variants and attributes, mesh repair ─────────────────────────
  // Three differently shaped "variants" (square / circle / triangle), each connected to a point
  from_pieces(c) {
    rect(c, -0.9, -0.85, 0.5, 0.5, false);
    circ(c, 0.05, -0.6, 0.26, false);
    poly(c, [0.55, -0.35, 0.9, -0.35, 0.72, -0.88], true, false);
    dots(c, [-0.65, 0.55, 0.05, 0.55, 0.72, 0.55], 0.14);
    dash(c, true);
    line(c, -0.65, -0.3, -0.65, 0.4); line(c, 0.05, -0.3, 0.05, 0.4);
    line(c, 0.72, -0.3, 0.72, 0.4);
    dash(c, false);
  },
  // A row of points labelled 0 1 2 below (vertical bars of three steps)
  enumerate_(c) {
    dots(c, [-0.6, -0.6, 0, -0.6, 0.6, -0.6], 0.15);
    rect(c, -0.72, 0.55, 0.24, 0.3, true);
    rect(c, -0.12, 0.25, 0.24, 0.6, true);
    rect(c, 0.48, -0.05, 0.24, 0.9, true);
  },
  // Three color swatches of different strength (icons are monochrome; opacity stands for "different colors")
  color_(c) {
    c.globalAlpha = 1.0; circ(c, -0.35, -0.3, 0.42, true);
    c.globalAlpha = 0.55; circ(c, 0.35, -0.3, 0.42, true);
    c.globalAlpha = 0.25; circ(c, 0, 0.35, 0.42, true);
    c.globalAlpha = 1.0;
  },
  // Two known solid points, the point between them "filled" as a gradient
  fill_(c) {
    line(c, -0.8, 0, 0.8, 0);
    circ(c, -0.8, 0, 0.2, true); circ(c, 0.8, 0, 0.2, true);
    c.globalAlpha = 0.7; circ(c, -0.3, 0, 0.14, true);
    c.globalAlpha = 0.4; circ(c, 0.3, 0, 0.14, true);
    c.globalAlpha = 1.0;
    arrow(c, -0.6, -0.55, 0.6, -0.55, 0.2);
  },
  // "a*" -> "b*": two character boxes + arrow
  string_edit(c) {
    rect(c, -0.95, -0.35, 0.7, 0.7, false);
    rect(c, 0.25, -0.35, 0.7, 0.7, false);
    arrow(c, -0.18, 0, 0.2, 0, 0.16);
    line(c, -0.8, 0.15, -0.4, 0.15); line(c, 0.4, 0.15, 0.8, 0.15);
    line(c, -0.8, -0.1, -0.55, -0.1); line(c, 0.4, -0.1, 0.65, -0.1);
  },
  // Three clusters of points, each with a circle around it
  cluster_(c) {
    circ(c, -0.5, -0.45, 0.38, false); circ(c, 0.5, -0.35, 0.34, false);
    circ(c, 0, 0.5, 0.36, false);
    dots(c, [-0.6, -0.5, -0.4, -0.35, -0.55, -0.3, 0.45, -0.4, 0.6, -0.3,
             0.5, -0.2, -0.1, 0.45, 0.1, 0.55, 0, 0.4], 0.09);
  },
  // A regular triangle mesh (two rows of equilateral triangles)
  remesh(c) {
    poly(c, [-0.9, 0.7, -0.3, 0.7, 0.3, 0.7, 0.9, 0.7], false, false);
    poly(c, [-0.6, 0, 0, 0, 0.6, 0], false, false);
    poly(c, [-0.9, 0.7, -0.6, 0, -0.3, 0.7, 0, 0, 0.3, 0.7, 0.6, 0, 0.9, 0.7],
         false, false);
    poly(c, [-0.6, 0, -0.3, -0.7, 0, 0, 0.3, -0.7, 0.6, 0], false, false);
    line(c, -0.3, -0.7, 0.3, -0.7);
  },
  // A broom: clean up
  clean(c) {
    line(c, 0.75, -0.9, -0.05, 0.1);
    poly(c, [-0.05, 0.1, -0.6, 0.35, -0.9, 0.85, -0.3, 0.75, 0.15, 0.35],
         true, false);
    line(c, -0.45, 0.4, -0.6, 0.78); line(c, -0.2, 0.35, -0.3, 0.72);
  },
  // The two endpoints of an edge squeezed by arrows into one point in the middle
  edge_collapse(c) {
    poly(c, [-0.9, 0.6, -0.5, 0, -0.9, -0.6], false, false);
    poly(c, [0.9, 0.6, 0.5, 0, 0.9, -0.6], false, false);
    arrow(c, -0.5, 0, -0.15, 0, 0.16); arrow(c, 0.5, 0, 0.15, 0, 0.16);
    circ(c, 0, 0, 0.14, true);
  },
  // A point split into two (two hollow points + two separated face corners)
  point_split(c) {
    poly(c, [-0.9, -0.7, -0.15, -0.1, -0.9, 0.5], false, false);
    poly(c, [0.9, -0.7, 0.15, -0.1, 0.9, 0.5], false, false);
    circ(c, -0.15, -0.1, 0.16, false); circ(c, 0.15, -0.1, 0.16, false);
    dash(c, true); line(c, 0, -0.8, 0, 0.8); dash(c, false);
  },
  // The edges of two islands in a uv grid sewn together
  uv_fuse(c) {
    rect(c, -0.9, -0.9, 1.8, 1.8, false);
    poly(c, [-0.7, -0.6, -0.05, -0.6, -0.05, 0.6, -0.7, 0.6], true, false);
    poly(c, [0.05, -0.6, 0.7, -0.4, 0.7, 0.5, 0.05, 0.6], true, false);
    c.lineWidth *= 2.2; line(c, 0, -0.6, 0, 0.6); c.lineWidth /= 2.2;
  },
  // Three fragments, lines between them
  connect_pieces(c) {
    poly(c, [-0.9, -0.2, -0.5, -0.8, -0.2, -0.3], true, false);
    poly(c, [0.3, -0.85, 0.9, -0.55, 0.55, -0.1], true, false);
    poly(c, [-0.3, 0.45, 0.25, 0.3, 0.1, 0.9], true, false);
    dash(c, true);
    line(c, -0.53, -0.43, 0.58, -0.5); line(c, -0.53, -0.43, 0.02, 0.55);
    line(c, 0.58, -0.5, 0.02, 0.55);
    dash(c, false);
  },

  // ── pcg70 batch E ──
  // Front outline of an icosahedron: outer hexagon + triangles inside
  platonic(c) {
    const h = [];
    for (let k = 0; k < 6; k++) {
      const a = Math.PI / 6 + k * Math.PI / 3;
      h.push(0.9 * Math.cos(a), 0.9 * Math.sin(a));
    }
    poly(c, h, true, false);
    poly(c, [0, -0.5, 0.43, 0.25, -0.43, 0.25], true, false);
    line(c, 0, -0.5, 0, -0.9); line(c, 0.43, 0.25, 0.78, 0.45);
    line(c, -0.43, 0.25, -0.78, 0.45);
  },
  // A small branching tree (L-System)
  lsystem(c) {
    line(c, 0, 0.9, 0, 0.1);
    line(c, 0, 0.1, -0.55, -0.45); line(c, 0, 0.1, 0.55, -0.45);
    line(c, 0, 0.1, 0, -0.85);
    line(c, -0.55, -0.45, -0.8, -0.85); line(c, -0.55, -0.45, -0.3, -0.85);
    line(c, 0.55, -0.45, 0.8, -0.85); line(c, 0.55, -0.45, 0.3, -0.85);
    dots(c, [-0.8, -0.85, -0.3, -0.85, 0.3, -0.85, 0.8, -0.85], 0.1);
  },
  // A letter A with a hole (outline)
  font_(c) {
    poly(c, [-0.8, 0.85, -0.15, -0.85, 0.15, -0.85, 0.8, 0.85, 0.45, 0.85,
             0.3, 0.4, -0.3, 0.4, -0.45, 0.85], true, false);
    poly(c, [-0.18, 0.1, 0, -0.4, 0.18, 0.1], true, false);
  },
  // 3×3 control lattice (dashed) + lattice points
  lattice_box(c) {
    dash(c, true);
    for (const v of [-0.7, 0, 0.7]) { line(c, v, -0.8, v, 0.8); line(c, -0.8, v, 0.8, v); }
    dash(c, false);
    grid3(c, 0.12);
  },
  // Bent lattice lines + lattice points
  lattice_ffd(c) {
    for (const v of [-0.6, 0, 0.6]) {
      poly(c, [-0.85, v + 0.25, -0.3, v - 0.05, 0.3, v - 0.05, 0.85, v + 0.25], false, false);
    }
    for (const x of [-0.6, 0, 0.6]) poly(c, [x, -0.5, x * 1.15, 0.05, x, 0.75], false, false);
    dots(c, [-0.85, 0.85, 0.85, 0.85, -0.85, -0.35, 0.85, -0.35], 0.12);
  },
  // Sparse control points (solid) carrying a fine mesh (small hollow points)
  point_deform(c) {
    poly(c, [-0.8, 0.3, -0.4, -0.1, 0, -0.25, 0.4, -0.1, 0.8, 0.3], false, false);
    dots(c, [-0.8, 0.3, 0, -0.25, 0.8, 0.3], 0.16);
    for (const [x, y] of [[-0.6, 0.65], [-0.2, 0.5], [0.2, 0.5], [0.6, 0.65]]) circ(c, x, y, 0.09, false);
    dash(c, true); line(c, -0.8, 0.3, -0.6, 0.65); line(c, 0, -0.25, -0.2, 0.5);
    line(c, 0, -0.25, 0.2, 0.5); line(c, 0.8, 0.3, 0.6, 0.65); dash(c, false);
  },
  // A slider between two shapes (Blend Shapes)
  blend_shapes(c) {
    circ(c, -0.55, -0.3, 0.35, false);
    rect(c, 0.2, -0.65, 0.7, 0.7, false);
    line(c, -0.85, 0.65, 0.85, 0.65);
    circ(c, 0.1, 0.65, 0.15, true);
  },
  // Three fragments each moved away by an arrow
  transform_pieces(c) {
    poly(c, [-0.9, 0.2, -0.45, -0.3, -0.25, 0.35], true, false);
    poly(c, [0.1, 0.5, 0.55, 0.3, 0.45, 0.9], true, false);
    rect(c, 0.25, -0.85, 0.5, 0.45, false);
    arrow(c, -0.5, 0.1, -0.35, -0.65, 0.15); arrow(c, 0.3, 0.55, 0.85, 0.05, 0.15);
  },
  // A tube bridging two openings (two vertical lines + connecting surface lines)
  poly_bridge(c) {
    poly(c, [-0.9, -0.8, -0.6, -0.8, -0.6, 0.8, -0.9, 0.8], true, false);
    poly(c, [0.9, -0.8, 0.6, -0.8, 0.6, 0.8, 0.9, 0.8], true, false);
    poly(c, [-0.6, -0.5, -0.2, -0.75, 0.2, -0.75, 0.6, -0.5], false, false);
    poly(c, [-0.6, 0.5, -0.2, 0.25, 0.2, 0.25, 0.6, 0.5], false, false);
    dash(c, true); line(c, 0, -0.75, 0, 0.25); dash(c, false);
  },

  // ── pcg71 ──
  // A point inside a volume grid (dashed), with a small sampled cell marked on the point
  from_volume(c) {
    dash(c, true);
    rect(c, -0.9, -0.9, 1.8, 1.8, false);
    line(c, -0.3, -0.9, -0.3, 0.9); line(c, 0.3, -0.9, 0.3, 0.9);
    line(c, -0.9, -0.3, 0.9, -0.3); line(c, -0.9, 0.3, 0.9, 0.3);
    dash(c, false);
    c.globalAlpha = 0.45; rect(c, -0.3, -0.3, 0.6, 0.6, true); c.globalAlpha = 1.0;
    circ(c, 0.08, 0.1, 0.16, true);
  },
  // Two uv grids, the same triangle matched between them by an arrow
  uv_transfer(c) {
    rect(c, -0.95, -0.55, 0.8, 0.8, false);
    rect(c, 0.15, -0.55, 0.8, 0.8, false);
    poly(c, [-0.8, 0.1, -0.35, 0.1, -0.6, -0.4], true, false);
    poly(c, [0.3, 0.1, 0.75, 0.1, 0.5, -0.4], true, true);
    arrow(c, -0.5, 0.6, 0.5, 0.6, 0.18);
  },

  // ── pcg72 volumes ──
  // ── pcg106 volume / VDB family
  // Sparse grid: only some 2x2 blocks active (VDB)
  vdb(c) {
    dash(c, true); rect(c, -0.9, -0.9, 1.8, 1.8, false); dash(c, false);
    for (const [x, y] of [[-0.7, -0.7], [-0.1, -0.7], [-0.1, -0.1], [0.5, -0.1], [-0.7, 0.5]]) rect(c, x, y, 0.5, 0.5, false);
    c.globalAlpha = 0.5; rect(c, -0.1, -0.1, 0.5, 0.5, true); c.globalAlpha = 1.0;
  },
  // Active blocks growing: a block with a plus
  vdb_activate(c) {
    rect(c, -0.85, -0.25, 0.6, 0.6, false); rect(c, -0.25, -0.25, 0.6, 0.6, false);
    c.globalAlpha = 0.5; rect(c, -0.85, -0.25, 0.6, 0.6, true); c.globalAlpha = 1.0;
    line(c, 0.65, -0.75, 0.65, -0.15); line(c, 0.35, -0.45, 0.95, -0.45);
    dash(c, true); rect(c, 0.35, -0.25, 0.6, 0.6, false); dash(c, false);
  },
  // Tree: one big node, four leaves under it
  vdb_tree(c) {
    rect(c, -0.3, -0.9, 0.6, 0.45, false);
    for (const x of [-0.85, -0.35, 0.15, 0.6]) { rect(c, x, 0.45, 0.3, 0.3, false); line(c, 0, -0.45, x + 0.15, 0.45); }
  },
  // Offset contours around a shape (SDF level sets)
  vdb_sdf(c) {
    circ(c, 0, 0, 0.25, true);
    c.globalAlpha = 0.7; circ(c, 0, 0, 0.5, false);
    c.globalAlpha = 0.4; circ(c, 0, 0, 0.75, false); c.globalAlpha = 1.0;
    dash(c, true); circ(c, 0, 0, 0.95, false); dash(c, false);
  },
  // A cube cut by a plane
  vol_slice(c) {
    rect(c, -0.8, -0.4, 1.2, 1.2, false);
    poly(c, [-0.8, -0.4, -0.4, -0.8, 0.8, -0.8, 0.4, -0.4], false, false);
    poly(c, [0.8, -0.8, 0.8, 0.4, 0.4, 0.8], false, false);
    c.globalAlpha = 0.5; poly(c, [-0.8, 0.2, 0.4, 0.2, 0.8, -0.2, -0.4, -0.2], true, true); c.globalAlpha = 1.0;
  },
  // Three streamlines with arrow heads
  vol_trail(c) {
    for (const y of [-0.55, 0.0, 0.55]) {
      poly(c, [-0.9, y + 0.2, -0.45, y - 0.1, 0.0, y + 0.15, 0.45, y - 0.1], false, false);
      arrow(c, 0.45, y - 0.1, 0.9, y + 0.05, 0.18);
    }
  },
  // Smoke puff with a viewing eye under it
  vol_vis(c) {
    c.globalAlpha = 0.35; circ(c, -0.3, -0.25, 0.4, true); circ(c, 0.25, -0.35, 0.45, true);
    c.globalAlpha = 1.0; circ(c, -0.3, -0.25, 0.4, false); circ(c, 0.25, -0.35, 0.45, false);
    poly(c, [-0.8, 0.55, -0.4, 0.3, 0.4, 0.3, 0.8, 0.55, 0.4, 0.8, -0.4, 0.8], true, false);
    circ(c, 0, 0.55, 0.15, true);
  },
  // Three component arrows joining into one vector
  vol_vector(c) {
    for (const y of [-0.6, 0.0, 0.6]) line(c, -0.9, y, -0.3, y);
    line(c, -0.3, -0.6, 0.15, 0.0); line(c, -0.3, 0.6, 0.15, 0.0); line(c, -0.3, 0.0, 0.15, 0.0);
    arrow(c, 0.15, 0.0, 0.9, 0.0, 0.2);
  },
  // A swirl (velocity field)
  vol_flow(c) {
    poly(c, [0.0, -0.8, 0.55, -0.6, 0.8, -0.1, 0.6, 0.45, 0.1, 0.65, -0.35, 0.45, -0.45, 0.0, -0.2, -0.3, 0.15, -0.2], false, false);
    arrow(c, 0.15, -0.2, 0.2, 0.2, 0.18);
    dots(c, [-0.8, 0.75, 0.8, 0.8], 0.08);
  },
  // A cube wireframe (new volume)
  volume_new(c) {
    rect(c, -0.85, -0.45, 1.25, 1.25, false);
    poly(c, [-0.85, -0.45, -0.45, -0.85, 0.8, -0.85, 0.4, -0.45], false, false);
    poly(c, [0.8, -0.85, 0.8, 0.4, 0.4, 0.8], false, false);
    dash(c, true); line(c, -0.25, -0.45, -0.25, 0.8); line(c, 0.15, -0.45, 0.15, 0.8); dash(c, false);
  },
  // A blurred blob of points in a grid (three rings of opacity)
  volume_blur(c) {
    dash(c, true); rect(c, -0.9, -0.9, 1.8, 1.8, false); dash(c, false);
    c.globalAlpha = 0.25; circ(c, 0, 0, 0.75, true);
    c.globalAlpha = 0.5; circ(c, 0, 0, 0.48, true);
    c.globalAlpha = 1.0; circ(c, 0, 0, 0.22, true);
  },
  // Two intersecting circles, smoothly joined at the seam (SDF smooth union)
  volume_mix(c) {
    circ(c, -0.35, 0.05, 0.5, false); circ(c, 0.4, 0.05, 0.42, false);
    c.globalAlpha = 0.45; circ(c, -0.35, 0.05, 0.5, true); c.globalAlpha = 1.0;
    poly(c, [-0.05, -0.38, 0.05, -0.3, 0.15, -0.34], false, false);
  },
  // Coarse grid to fine grid
  volume_resample(c) {
    rect(c, -0.95, -0.6, 0.8, 0.8, false); line(c, -0.55, -0.6, -0.55, 0.2);
    line(c, -0.95, -0.2, -0.15, -0.2);
    rect(c, 0.15, -0.6, 0.8, 0.8, false);
    for (const v of [0.35, 0.55, 0.75]) line(c, v, -0.6, v, 0.2);
    for (const v of [-0.4, -0.2, 0.0]) line(c, 0.15, v, 0.95, v);
    arrow(c, -0.4, 0.6, 0.4, 0.6, 0.15);
  },
  // Grid + curly braces (per-voxel code)
  volume_wrangle(c) {
    dash(c, true); rect(c, -0.9, -0.9, 1.8, 1.8, false); dash(c, false);
    poly(c, [-0.2, -0.6, -0.4, -0.6, -0.4, -0.1, -0.55, 0, -0.4, 0.1, -0.4, 0.6, -0.2, 0.6], false, false);
    poly(c, [0.2, -0.6, 0.4, -0.6, 0.4, -0.1, 0.55, 0, 0.4, 0.1, 0.4, 0.6, 0.2, 0.6], false, false);
  },
  // A shape and its outward-pushed outline (dashed)
  volume_reshape(c) {
    poly(c, [-0.5, 0.45, -0.45, -0.3, 0.1, -0.5, 0.5, -0.1, 0.35, 0.45], true, false);
    dash(c, true);
    poly(c, [-0.8, 0.72, -0.72, -0.55, 0.12, -0.85, 0.85, -0.2, 0.62, 0.75], true, false);
    dash(c, false);
  },

  // ── pcg73 transforms and correspondence ──
  // A curved arrow between two triangles (solid / dashed): solve for the transform
  extract_xform(c) {
    poly(c, [-0.9, 0.7, -0.35, 0.7, -0.65, 0.1], true, false);
    dash(c, true); poly(c, [0.3, -0.2, 0.85, -0.55, 0.75, 0.15], true, false); dash(c, false);
    poly(c, [-0.55, -0.1, -0.35, -0.6, 0.15, -0.8], false, false);
    poly(c, [0.0, -0.95, 0.15, -0.8, 0.0, -0.62], false, false);
  },
  // Three fragments, each with an oriented point at its center
  xform_extract_pieces(c) {
    poly(c, [-0.9, -0.3, -0.4, -0.8, -0.2, -0.2], true, false);
    poly(c, [0.2, 0.3, 0.8, 0.1, 0.6, 0.8], true, false);
    dots(c, [-0.5, -0.43, 0.53, 0.4], 0.12);
    arrow(c, -0.5, -0.43, -0.1, -0.1, 0.14); arrow(c, 0.53, 0.4, 0.85, -0.2, 0.14);
  },
  // One axis rotated to another axis
  match_axis(c) {
    arrow(c, -0.7, 0.7, -0.7, -0.8, 0.2);
    arrow(c, -0.7, 0.7, 0.85, 0.7, 0.2);
    dash(c, true); poly(c, [-0.7, -0.4, -0.2, -0.2, 0.2, 0.2, 0.45, 0.65], false, false); dash(c, false);
  },
  // Three boxes each rotating about its center
  prim_xform(c) {
    rect(c, -0.9, -0.3, 0.5, 0.5, false);
    poly(c, [0.05, -0.55, 0.35, -0.25, 0.05, 0.05, -0.25, -0.25], true, false);
    poly(c, [0.55, 0.1, 0.95, 0.2, 0.85, 0.6, 0.45, 0.5], true, false);
    dots(c, [-0.65, -0.05, 0.05, -0.25, 0.7, 0.35], 0.07);
  },
  // A bent line, the short normal lines on it following the rotation
  reorient(c) {
    poly(c, [-0.9, 0.6, -0.4, 0.3, 0.1, 0.25, 0.5, 0.0, 0.85, -0.45], false, false);
    arrow(c, -0.4, 0.3, -0.55, -0.15, 0.13);
    arrow(c, 0.1, 0.25, 0.05, -0.25, 0.13);
    arrow(c, 0.5, 0.0, 0.2, -0.4, 0.13);
  },
  // Points of two meshes matched by lines, small index ticks on the points
  match_topo(c) {
    poly(c, [-0.9, -0.6, -0.4, -0.8, -0.3, -0.2, -0.85, 0.0], true, false);
    poly(c, [0.3, 0.1, 0.85, -0.05, 0.9, 0.6, 0.35, 0.75], true, false);
    dash(c, true); line(c, -0.4, -0.8, 0.85, -0.05); line(c, -0.3, -0.2, 0.9, 0.6); dash(c, false);
    dots(c, [-0.9, -0.6, 0.3, 0.1], 0.1);
  },
  // A regular grid fitted onto a bump
  topo_transfer(c) {
    poly(c, [-0.9, 0.8, -0.5, 0.1, 0.0, -0.3, 0.5, 0.1, 0.9, 0.8], false, false);
    for (const [x, y] of [[-0.7, 0.45], [-0.25, -0.1], [0.25, -0.1], [0.7, 0.45]]) line(c, x, y, x, y - 0.35);
    dash(c, true); line(c, -0.9, -0.75, 0.9, -0.75); dash(c, false);
  },
  // A wrinkled line (dashed) becomes smooth, details (small bumps) preserved
  delta_mush(c) {
    dash(c, true); poly(c, [-0.9, -0.4, -0.6, -0.8, -0.3, -0.2, 0, -0.85, 0.3, -0.3, 0.6, -0.9, 0.9, -0.4], false, false); dash(c, false);
    poly(c, [-0.9, 0.5, -0.5, 0.3, -0.35, 0.1, -0.2, 0.3, 0.2, 0.25, 0.35, 0.05, 0.5, 0.25, 0.9, 0.5], false, false);
  },

  // ── pcg74 mesh editing ──
  // Evenly spaced points on a bent line
  edge_equalize(c) {
    poly(c, [-0.9, 0.5, -0.45, -0.2, 0.1, -0.5, 0.55, -0.35, 0.9, 0.3], false, false);
    dots(c, [-0.9, 0.5, -0.45, -0.2, 0.1, -0.5, 0.55, -0.35, 0.9, 0.3], 0.1);
    line(c, -0.9, 0.85, 0.9, 0.85);
    for (const x of [-0.9, -0.45, 0, 0.45, 0.9]) line(c, x, 0.75, x, 0.95);
  },
  // A dashed bent chain pulled into a solid straight chain
  edge_straighten(c) {
    dash(c, true); poly(c, [-0.9, 0.2, -0.45, -0.45, 0.0, 0.1, 0.45, -0.5, 0.9, 0.2], false, false); dash(c, false);
    line(c, -0.9, 0.2, 0.9, 0.2);
    dots(c, [-0.9, 0.2, -0.45, 0.2, 0.0, 0.2, 0.45, 0.2, 0.9, 0.2], 0.1);
  },
  // A wobbly ring (dashed) becomes a perfect circle
  circle_edges(c) {
    dash(c, true); poly(c, [-0.8, 0.1, -0.35, -0.75, 0.45, -0.6, 0.85, 0.2, 0.2, 0.8, -0.55, 0.55], true, false); dash(c, false);
    circ(c, 0, 0, 0.62, false);
    dots(c, [0.62, 0, -0.31, 0.54, -0.31, -0.54], 0.09);
  },
  // In a quad the old diagonal (dashed) is replaced by the new diagonal
  edge_flip(c) {
    poly(c, [-0.85, 0, 0, -0.85, 0.85, 0, 0, 0.85], true, false);
    dash(c, true); line(c, -0.85, 0, 0.85, 0); dash(c, false);
    line(c, 0, -0.85, 0, 0.85);
    poly(c, [0.35, -0.55, 0.55, -0.35, 0.5, -0.1], false, false);
  },
  // A triangle split again and again along its longest edge
  tri_divide(c) {
    poly(c, [-0.9, 0.75, 0.9, 0.75, 0.0, -0.8], true, false);
    line(c, 0.0, 0.75, 0.0, -0.8);
    line(c, 0.0, 0.75, -0.45, -0.02); line(c, 0.0, 0.75, 0.45, -0.02);
  },
  // Fine grid -> coarse grid
  unsubdivide(c) {
    rect(c, -0.95, -0.45, 0.8, 0.8, false);
    for (const v of [-0.75, -0.55, -0.35]) { line(c, v, -0.45, v, 0.35); line(c, -0.95, v + 0.3, -0.15, v + 0.3); }
    rect(c, 0.15, -0.45, 0.8, 0.8, false); line(c, 0.55, -0.45, 0.55, 0.35); line(c, 0.15, -0.05, 0.95, -0.05);
    arrow(c, -0.4, 0.7, 0.4, 0.7, 0.15);
  },
  // A face corner rewired from one point to another
  rewire(c) {
    poly(c, [-0.85, 0.6, 0.1, 0.6, -0.4, -0.3], true, false);
    dots(c, [-0.4, -0.3, 0.6, -0.7], 0.11);
    dash(c, true); line(c, 0.1, 0.6, 0.6, -0.7); dash(c, false);
    arrow(c, -0.25, -0.45, 0.4, -0.7, 0.14);
  },
  // A polygon outline broken in two places
  poly_cut(c) {
    poly(c, [-0.1, -0.85, 0.6, -0.6, 0.85, 0.05, 0.5, 0.5], false, false);
    poly(c, [0.05, 0.85, -0.6, 0.6, -0.85, -0.1, -0.55, -0.55], false, false);
    dots(c, [0.5, 0.5, 0.05, 0.85, -0.55, -0.55, -0.1, -0.85], 0.12);
  },
  // Two pieces, coarse on the left and fine on the right, points aligned on the middle seam
  poly_stitch(c) {
    rect(c, -0.9, -0.8, 0.9, 1.6, false); line(c, -0.9, 0, 0, 0);
    rect(c, 0, -0.8, 0.9, 1.6, false);
    for (const y of [-0.4, 0, 0.4]) line(c, 0, y, 0.9, y);
    dots(c, [0, -0.4, 0, 0, 0, 0.4], 0.1);
  },
  // A few Voronoi edges on a face, one point per cell
  voronoi_split(c) {
    rect(c, -0.9, -0.9, 1.8, 1.8, false);
    poly(c, [-0.9, -0.1, -0.2, 0.05, 0.25, -0.9], false, false);
    poly(c, [-0.2, 0.05, 0.1, 0.9], false, false);
    poly(c, [-0.2, 0.05, 0.9, 0.35], false, false);
    dots(c, [-0.55, -0.5, 0.45, -0.3, -0.5, 0.5, 0.55, 0.7], 0.09);
  },

  // ── pcg75 curves and surfaces ──
  // A few points, a smooth curve through them
  circle_spline(c) {
    poly(c, [-0.9, 0.4, -0.7, -0.2, -0.35, -0.55, 0.1, -0.6, 0.5, -0.35, 0.75, 0.05, 0.85, 0.5], false, false);
    dots(c, [-0.9, 0.4, -0.35, -0.55, 0.5, -0.35, 0.85, 0.5], 0.1);
    dash(c, true); circ(c, -0.1, 0.15, 0.72, false); dash(c, false);
  },
  // Dashed polyline + solid smooth curve
  poly_spline(c) {
    dash(c, true); poly(c, [-0.9, 0.6, -0.4, -0.7, 0.3, 0.6, 0.9, -0.6], false, false); dash(c, false);
    poly(c, [-0.9, 0.6, -0.7, 0.0, -0.45, -0.35, -0.15, -0.2, 0.1, 0.2, 0.35, 0.3, 0.6, 0.05, 0.9, -0.6], false, false);
  },
  // Parabola + ground
  ballistic(c) {
    poly(c, [-0.85, 0.7, -0.6, 0.0, -0.3, -0.45, 0.0, -0.62, 0.3, -0.45, 0.55, -0.05, 0.75, 0.7], false, false);
    arrow(c, -0.85, 0.7, -0.6, 0.05, 0.15);
    line(c, -0.95, 0.75, 0.95, 0.75);
  },
  // Points on three curves, connected across
  poly_loft(c) {
    for (const y of [-0.7, 0, 0.7]) poly(c, [-0.8, y, -0.25, y - 0.12, 0.3, y - 0.05, 0.85, y + 0.08], false, false);
    dash(c, true);
    for (const x of [-0.8, -0.25, 0.3, 0.85]) line(c, x, -0.7, x, 0.75);
    dash(c, false);
  },
  // A net woven from two families of curves
  cross_section(c) {
    for (const y of [-0.6, 0, 0.6]) poly(c, [-0.85, y + 0.1, -0.3, y - 0.1, 0.3, y - 0.12, 0.85, y + 0.1], false, false);
    for (const x of [-0.6, 0, 0.6]) poly(c, [x + 0.1, -0.85, x - 0.08, -0.3, x - 0.1, 0.3, x + 0.1, 0.85], false, false);
  },

  // ── pcg76 attributes and groups, points ──
  // Two stacked squares, the overlap semi-transparent (composite)
  attrib_composite(c) {
    rect(c, -0.85, -0.85, 1.1, 1.1, false);
    c.globalAlpha = 0.5; rect(c, -0.25, -0.25, 1.1, 1.1, true); c.globalAlpha = 1.0;
    rect(c, -0.25, -0.25, 1.1, 1.1, false);
  },
  // A vertical mirror plane, solid points on the left, hollow points on the right
  attrib_mirror(c) {
    dash(c, true); line(c, 0, -0.95, 0, 0.95); dash(c, false);
    dots(c, [-0.55, -0.45, -0.3, 0.1, -0.7, 0.5], 0.13);
    for (const [x, y] of [[0.55, -0.45], [0.3, 0.1], [0.7, 0.5]]) circ(c, x, y, 0.13, false);
  },
  // The boundary between two color areas drawn bold
  attrib_boundary(c) {
    rect(c, -0.9, -0.9, 1.8, 1.8, false);
    c.globalAlpha = 0.45; poly(c, [-0.9, -0.9, 0.2, -0.9, -0.2, 0.9, -0.9, 0.9], true, true); c.globalAlpha = 1.0;
    c.lineWidth *= 2.2; line(c, 0.2, -0.9, -0.2, 0.9); c.lineWidth /= 2.2;
  },
  // Three cells, each holding different points
  partition(c) {
    for (const x of [-0.9, -0.3, 0.3]) rect(c, x, -0.5, 0.55, 1.0, false);
    dots(c, [-0.62, -0.2, -0.62, 0.2], 0.09);
    circ(c, -0.02, -0.2, 0.1, false); circ(c, -0.02, 0.2, 0.1, false);
    poly(c, [0.48, -0.3, 0.6, -0.1, 0.36, -0.1], true, true); poly(c, [0.48, 0.1, 0.6, 0.3, 0.36, 0.3], true, true);
  },
  // A field of short streamline-like arrows
  tangent_field(c) {
    for (const [x, y, a] of [[-0.6, -0.55, 0.2], [0, -0.6, 0.0], [0.6, -0.5, -0.3], [-0.6, 0.05, 0.5],
                             [0, 0, 0.3], [0.6, 0.05, 0.0], [-0.6, 0.6, 0.8], [0, 0.6, 0.6], [0.6, 0.6, 0.3]]) {
      const dx = 0.25 * Math.cos(a), dy = -0.25 * Math.sin(a);
      arrow(c, x - dx, y - dy, x + dx, y + dy, 0.12);
    }
  },
  // A pile of points, only a few left solid, a dashed radius circle around
  adaptive_prune(c) {
    for (const [x, y] of [[-0.55, -0.45], [0.35, -0.5], [-0.3, 0.45], [0.55, 0.35]]) {
      dash(c, true); circ(c, x, y, 0.36, false); dash(c, false); dots(c, [x, y], 0.1);
    }
    c.globalAlpha = 0.4; dots(c, [-0.1, -0.3, 0.1, 0.1, -0.7, 0.05, 0.75, -0.05], 0.06); c.globalAlpha = 1.0;
  },
  // A big point in the middle, a cluster of small points around it
  point_replicate(c) {
    dots(c, [0, 0], 0.16);
    dash(c, true); circ(c, 0, 0, 0.75, false); dash(c, false);
    dots(c, [0.4, 0.2, -0.35, 0.4, -0.5, -0.2, 0.2, -0.5, 0.55, -0.35, -0.1, 0.6, 0.1, 0.35, -0.25, -0.5], 0.06);
  },
  // Three positions (faint -> solid) and a velocity arrow
  point_velocity(c) {
    c.globalAlpha = 0.3; dots(c, [-0.75, 0.45], 0.12);
    c.globalAlpha = 0.6; dots(c, [-0.3, 0.1], 0.12);
    c.globalAlpha = 1.0; dots(c, [0.15, -0.15], 0.12);
    arrow(c, 0.15, -0.15, 0.85, -0.6, 0.2);
  },

  // ── pcg77 volume / UV / outline ──
  // A circle on grid points (implicit-function isosurface)
  isosurface(c) {
    c.globalAlpha = 0.4;
    for (const v of [-0.6, -0.2, 0.2, 0.6]) { line(c, v, -0.9, v, 0.9); line(c, -0.9, v, 0.9, v); }
    c.globalAlpha = 1.0;
    circ(c, 0, 0, 0.62, false);
  },
  // A slanted circle re-tiled by a regular grid
  remesh_grid(c) {
    circ(c, 0, 0, 0.8, false);
    poly(c, [-0.4, -0.7, 0.4, -0.7, 0.7, -0.4, 0.7, 0.4, 0.4, 0.7, -0.4, 0.7, -0.7, 0.4, -0.7, -0.4], true, false);
    line(c, -0.4, -0.7, -0.4, 0.7); line(c, 0.4, -0.7, 0.4, 0.7);
    line(c, -0.7, -0.4, 0.7, -0.4); line(c, -0.7, 0.4, 0.7, 0.4);
  },
  // A skewed uv grid becomes regular
  uv_smooth(c) {
    rect(c, -0.9, -0.9, 1.8, 1.8, false);
    dash(c, true); poly(c, [-0.9, -0.1, -0.3, 0.2, 0.2, -0.25, 0.9, 0.05], false, false); dash(c, false);
    line(c, -0.9, 0, 0.9, 0); line(c, 0, -0.9, 0, 0.9);
  },
  // A solid (dashed) and the outline it casts (solid)
  silhouette(c) {
    dash(c, true); rect(c, -0.45, -0.75, 0.7, 0.7, false); poly(c, [-0.45, -0.75, -0.15, -0.95, 0.55, -0.95, 0.25, -0.75], false, false);
    line(c, 0.55, -0.95, 0.55, -0.25); line(c, 0.55, -0.25, 0.25, -0.05); dash(c, false);
    poly(c, [-0.8, 0.25, -0.45, 0.05, 0.55, 0.05, 0.9, 0.25, 0.9, 0.9, -0.8, 0.9], true, false);
  },
  // Four overlapping squares
  tile_split(c) {
    rect(c, -0.95, -0.95, 1.05, 1.05, false); rect(c, -0.1, -0.95, 1.05, 1.05, false);
    rect(c, -0.95, -0.1, 1.05, 1.05, false); rect(c, -0.1, -0.1, 1.05, 1.05, false);
  },
  // A feathered band between two pieces
  tile_splice(c) {
    rect(c, -0.9, -0.7, 1.8, 1.4, false);
    c.globalAlpha = 0.25; rect(c, -0.3, -0.7, 0.6, 1.4, true); c.globalAlpha = 0.5; rect(c, -0.1, -0.7, 0.2, 1.4, true); c.globalAlpha = 1.0;
  },

  // ── pcg78 camera <-> points ──
  // Two view frusta (small pyramids) along a dashed path, each apex a solid point
  cam_points(c) {
    dash(c, true); poly(c, [-0.85, 0.55, -0.3, 0.1, 0.3, 0.2, 0.85, -0.3], false, false); dash(c, false);
    poly(c, [-0.3, 0.1, -0.75, -0.55, -0.05, -0.75], true, false);
    poly(c, [0.85, -0.3, 0.3, -0.85, 0.95, -0.95], true, false);
    dots(c, [-0.85, 0.55, -0.3, 0.1, 0.3, 0.2, 0.85, -0.3], 0.1);
  },
  // Points on a curve, with a camera looking forward sprouting at the end
  cam_from_points(c) {
    dots(c, [-0.9, 0.7, -0.55, 0.35, -0.15, 0.2, 0.2, 0.25], 0.1);
    dash(c, true); poly(c, [-0.9, 0.7, -0.55, 0.35, -0.15, 0.2, 0.2, 0.25], false, false); dash(c, false);
    rect(c, -0.05, -0.6, 0.6, 0.55, false);
    poly(c, [0.55, -0.48, 0.95, -0.75, 0.95, 0.05, 0.55, -0.18], true, false);
  },

  // ── pcg79 completing partials ──
  // Two intersecting circles, the intersection filled
  group_combine(c) {
    circ(c, -0.3, 0, 0.6, false); circ(c, 0.3, 0, 0.6, false);
    // Lens-shaped intersection: the right arc of the left circle + the left arc of the right circle
    c.globalAlpha = 0.6; c.beginPath();
    c.arc(-0.3, 0, 0.6, -Math.PI / 3, Math.PI / 3);
    c.arc(0.3, 0, 0.6, Math.PI * 2 / 3, Math.PI * 4 / 3);
    c.fill(); c.globalAlpha = 1.0;
  },
  // A diamond decision box, two outgoing paths, one solid one dashed
  switch_if(c) {
    poly(c, [-0.35, 0, 0, -0.4, 0.35, 0, 0, 0.4], true, false);
    line(c, -0.95, 0, -0.35, 0);
    arrow(c, 0.35, 0, 0.9, -0.6, 0.22);
    dash(c, true); line(c, 0.35, 0, 0.9, 0.6); dash(c, false);
  },
  // Crowded points pushed apart: one point in the middle, surrounding points with small outward arrows
  point_relax(c) {
    dots(c, [0, 0], 0.13);
    for (const [x, y] of [[0.45, 0], [-0.45, 0], [0, 0.45], [0, -0.45]]) {
      dots(c, [x, y], 0.1); arrow(c, x * 1.2, y * 1.2, x * 2, y * 2, 0.15);
    }
  },
  // Two faces split apart along their seam (leaving a gap)
  prim_split(c) {
    rect(c, -0.9, -0.6, 0.8, 1.2, false);
    c.globalAlpha = 0.45; rect(c, 0.1, -0.6, 0.8, 1.2, true); c.globalAlpha = 1.0;
    rect(c, 0.1, -0.6, 0.8, 1.2, false);
  },
  // A square enclosed by [ ] matrix brackets
  xform_attrib(c) {
    poly(c, [-0.6, -0.8, -0.85, -0.8, -0.85, 0.8, -0.6, 0.8], false, false);
    poly(c, [0.6, -0.8, 0.85, -0.8, 0.85, 0.8, 0.6, 0.8], false, false);
    poly(c, [-0.4, -0.15, 0.1, -0.4, 0.45, -0.1, -0.05, 0.2], true, false);
    dots(c, [-0.35, 0.5, 0, 0.5, 0.35, 0.5], 0.07);
  },
  // A square face cut through from edge midpoints by a line
  poly_split(c) {
    rect(c, -0.8, -0.8, 1.6, 1.6, false);
    c.lineWidth *= 1.8; line(c, -0.2, -0.8, 0.35, 0.8); c.lineWidth /= 1.8;
    dots(c, [-0.2, -0.8, 0.35, 0.8], 0.13);
  },
  // Two folded faces separated along the crease
  edge_cusp(c) {
    poly(c, [-0.9, 0.7, -0.1, 0.1, -0.1, -0.85, -0.9, -0.25], true, false);
    poly(c, [0.9, 0.7, 0.1, 0.1, 0.1, -0.85, 0.9, -0.25], true, false);
  },
  // A smooth curve with one sharp corner, a weight tick on the corner
  crease(c) {
    poly(c, [-0.9, 0.6, -0.55, 0.52, -0.35, 0.3, -0.2, -0.1, -0.1, -0.6,
             0.05, -0.1, 0.2, 0.3, 0.45, 0.52, 0.9, 0.6], false, false);
    dash(c, true); c.beginPath(); c.arc(-0.1, -0.6, 0.35, Math.PI * 0.3, Math.PI * 0.7); c.stroke(); dash(c, false);
  },

  // ── pcg81 ──
  // A concave shape (dashed) with a tightened hull around it: the concave notch bridged by an arc
  shrinkwrap(c) {
    dash(c, true);
    poly(c, [-0.6, 0.6, -0.6, -0.6, -0.15, -0.6, -0.15, 0.1, 0.15, 0.1, 0.15, -0.6, 0.6, -0.6, 0.6, 0.6], true, false);
    dash(c, false);
    poly(c, [-0.8, 0.8, -0.8, -0.72, -0.15, -0.8, 0.15, -0.8, 0.8, -0.72, 0.8, 0.8], true, false);
  },

  // ── pcg82 ──
  // A pointed bump rising from the middle of a plane, arrow up along the normal
  soft_peak(c) {
    poly(c, [-0.95, 0.6, -0.45, 0.55, -0.15, 0.2, 0, -0.35, 0.15, 0.2, 0.45, 0.55, 0.95, 0.6], false, false);
    arrow(c, 0, -0.4, 0, -0.95, 0.2);
  },
  // A round magnet (dashed) pushing up a round bump in the nearby plane
  bulge(c) {
    dash(c, true); circ(c, 0, 0.35, 0.35, false); dash(c, false);
    poly(c, [-0.95, 0.75, -0.55, 0.72, -0.4, 0.4, -0.2, 0.05, 0.2, 0.05, 0.4, 0.4, 0.55, 0.72, 0.95, 0.75], false, false);
  },
  // A U-shaped magnet + a section of line pulled toward it
  magnet(c) {
    poly(c, [-0.3, -0.9, -0.3, -0.35, 0.3, -0.35, 0.3, -0.9], false, false);
    line(c, -0.45, -0.9, -0.15, -0.9); line(c, 0.15, -0.9, 0.45, -0.9);
    poly(c, [-0.95, 0.7, -0.4, 0.65, 0, 0.1, 0.4, 0.65, 0.95, 0.7], false, false);
  },
  // Jagged ridge (midpoint displacement)
  fractal(c) {
    poly(c, [-0.95, 0.6, -0.7, 0.2, -0.55, 0.35, -0.3, -0.35, -0.1, -0.1, 0.1, -0.65, 0.3, -0.2, 0.5, -0.4, 0.7, 0.15, 0.95, 0.6], true, false);
  },
  // A few oriented small arrows on a face (of different sizes)
  scatter_align(c) {
    line(c, -0.95, 0.6, 0.95, 0.6);
    arrow(c, -0.6, 0.6, -0.75, 0.05, 0.2);
    arrow(c, -0.05, 0.6, 0.05, -0.55, 0.25);
    arrow(c, 0.55, 0.6, 0.7, 0.2, 0.16);
  },
  // Tree-like edges, values accumulating outward from the root (points getting bigger)
  edge_transport(c) {
    line(c, -0.8, 0.7, -0.2, 0.1); line(c, -0.2, 0.1, 0.4, 0.3); line(c, -0.2, 0.1, 0.1, -0.6); line(c, 0.1, -0.6, 0.75, -0.75);
    dots(c, [-0.8, 0.7], 0.08); dots(c, [-0.2, 0.1], 0.12); dots(c, [0.4, 0.3], 0.16); dots(c, [0.1, -0.6], 0.16); dots(c, [0.75, -0.75], 0.2);
  },
  // A few points splatted into a clump of voxel cells
  vol_raster(c) {
    for (const [x, y] of [[-0.3, -0.3], [0.1, -0.3], [-0.3, 0.1], [0.1, 0.1], [0.5, 0.1], [0.1, 0.5]]) rect(c, x - 0.2, y - 0.2, 0.4, 0.4, false);
    c.globalAlpha = 0.5; rect(c, -0.1, -0.1, 0.4, 0.4, true); c.globalAlpha = 1.0;
    dots(c, [-0.1, -0.1, 0.3, 0.3], 0.1);
  },
  // A box pressed onto a terrain line, the ground under it dug out (dashed)
  hf_cutout(c) {
    poly(c, [-0.95, 0.3, -0.35, 0.3], false, false); poly(c, [0.35, 0.3, 0.95, 0.3], false, false);
    rect(c, -0.35, -0.35, 0.7, 0.9, false);
    dash(c, true); line(c, -0.35, 0.3, 0.35, 0.3); dash(c, false);
  },
  // The mask cast by a box (the projection of a solid box on the ground)
  hf_mask(c) {
    rect(c, -0.3, -0.85, 0.6, 0.55, false);
    dash(c, true); line(c, -0.3, -0.3, -0.45, 0.35); line(c, 0.3, -0.3, 0.45, 0.35); dash(c, false);
    c.globalAlpha = 0.6; rect(c, -0.55, 0.35, 1.1, 0.4, true); c.globalAlpha = 1.0;
  },

  // ── general modifiers ──────────────────────────────────────────
  transform(c) {
    arrow(c, 0, 0.2, 0, -0.85, 0.3);
    arrow(c, 0, 0.2, 0.85, 0.55, 0.3);
    arrow(c, 0, 0.2, -0.8, 0.6, 0.3);
  },
  merge(c) {
    poly(c, [-0.85, -0.7, -0.1, -0.7, 0.1, 0, 0.85, 0], false, false);
    poly(c, [-0.85, 0.7, -0.1, 0.7, 0.1, 0], false, false);
    dots(c, [0.78, 0], 0.18);
  },
  split(c) {
    poly(c, [-0.85, 0, -0.1, 0, 0.1, -0.7, 0.85, -0.7], false, false);
    poly(c, [-0.1, 0, 0.1, 0.7, 0.85, 0.7], false, false);
  },
  swtch(c) {
    // Three in, one out, the selected one drawn bold; the unselected ones dashed (not lower opacity --
    // at 15px a 0.4 gray is nearly invisible)
    dash(c, true);
    line(c, -0.95, -0.7, -0.15, -0.7); line(c, -0.95, 0.7, -0.15, 0.7);
    line(c, -0.15, -0.7, -0.15, 0.7);
    dash(c, false);
    c.lineWidth *= 1.9;
    line(c, -0.95, 0, 0.95, 0);
    c.lineWidth /= 1.9;
    circ(c, -0.15, 0, 0.26, true);
  },
  del(c) {
    line(c, -0.7, -0.7, 0.7, 0.7); line(c, 0.7, -0.7, -0.7, 0.7);
  },
  blast(c) {
    dash(c, true); rect(c, -0.9, -0.9, 1.8, 1.8, false); dash(c, false);
    line(c, -0.45, -0.45, 0.45, 0.45); line(c, 0.45, -0.45, -0.45, 0.45);
  },
  // pcg100 s8: UV Pelt -- a frame (circle), with a few springs of a pelt inside pulled onto the frame
  uv_pelt(c) {
    circ(c, 0, 0, 0.88, false);
    poly(c, [-0.35, -0.3, 0.3, -0.38, 0.4, 0.25, -0.3, 0.35], true, true);
    line(c, -0.35, -0.3, -0.62, -0.62); line(c, 0.3, -0.38, 0.6, -0.64);
    line(c, 0.4, 0.25, 0.7, 0.5); line(c, -0.3, 0.35, -0.55, 0.68);
  },
  // pcg100 s8: UV Unwrap -- three faces of a box, unfolded into a row of squares
  uv_unwrap(c) {
    poly(c, [-0.9, -0.2, -0.55, -0.55, -0.2, -0.2, -0.55, 0.15], true, false);
    arrow(c, -0.05, -0.2, 0.35, -0.2, 0.2);
    rect(c, -0.9, 0.45, 0.5, 0.45, true);
    rect(c, -0.25, 0.45, 0.5, 0.45, true);
    rect(c, 0.4, 0.45, 0.5, 0.45, true);
  },
  // pcg100: Blast by Attribute -- a row of bars of different heights (attribute values), those below the threshold line crossed out
  blast_attr(c) {
    line(c, -0.7, 0.9, -0.7, -0.6); line(c, 0.0, 0.9, 0.0, 0.45); line(c, 0.7, 0.9, 0.7, -0.2);
    dash(c, true); line(c, -0.95, 0.15, 0.95, 0.15); dash(c, false);
    line(c, -0.22, -0.1, 0.22, -0.54); line(c, 0.22, -0.1, -0.22, -0.54);
  },
  bool(c) {
    circ(c, -0.28, 0, 0.6, false); circ(c, 0.28, 0, 0.6, false);
    c.beginPath();
    c.arc(-0.28, 0, 0.6, -0.94, 0.94);
    c.arc(0.28, 0, 0.6, Math.PI - 0.94, Math.PI + 0.94);
    c.closePath(); c.fill();
  },
  clip(c) {
    poly(c, [-0.9, -0.7, 0.15, -0.7, 0.15, 0.8, -0.9, 0.8], true, false);
    c.lineWidth *= 1.6; line(c, 0.15, -0.95, 0.15, 0.95); c.lineWidth /= 1.6;
    c.globalAlpha = 0.35;
    dash(c, true);
    poly(c, [0.15, -0.7, 0.9, -0.7, 0.9, 0.8, 0.15, 0.8], true, false);
    dash(c, false);
    c.globalAlpha = 1;
  },
  carve(c) {
    c.beginPath(); c.moveTo(-0.9, 0.55);
    c.bezierCurveTo(-0.2, 0.55, -0.1, -0.65, 0.9, -0.65); c.stroke();
    line(c, -0.38, -0.05, -0.15, 0.75); line(c, 0.34, -0.9, 0.5, -0.1);
  },
  sort(c) {
    line(c, -0.8, -0.6, 0.0, -0.6);
    line(c, -0.8, 0.0, 0.45, 0.0);
    line(c, -0.8, 0.6, 0.85, 0.6);
  },
  reverse(c) {
    arrow(c, 0.75, -0.45, -0.75, -0.45, 0.28);
    arrow(c, -0.75, 0.45, 0.75, 0.45, 0.28);
  },
  smooth(c) {
    poly(c, [-0.9, 0.1, -0.55, -0.55, -0.2, 0.35, 0.05, -0.3], false, false);
    c.beginPath(); c.moveTo(0.05, -0.3);
    c.bezierCurveTo(0.4, -0.05, 0.55, 0.45, 0.9, 0.5); c.stroke();
  },
  subdiv(c) {
    rect(c, -0.85, -0.85, 1.7, 1.7, false);
    line(c, 0, -0.85, 0, 0.85); line(c, -0.85, 0, 0.85, 0);
  },
  divide(c) {
    rect(c, -0.85, -0.85, 1.7, 1.7, false);
    line(c, -0.85, 0.85, 0.85, -0.85);
  },
  refine(c) {
    line(c, -0.75, 0.5, 0.75, -0.5);
    circ(c, -0.75, 0.5, 0.22, true); circ(c, 0.75, -0.5, 0.22, true);
    circ(c, -0.25, 0.17, 0.2, false); circ(c, 0.25, -0.17, 0.2, false);
  },
  resample(c) {
    c.beginPath(); c.moveTo(-0.92, 0.45);
    c.bezierCurveTo(-0.3, 0.45, -0.2, -0.55, 0.92, -0.55); c.stroke();
    line(c, -0.62, 0.15, -0.62, 0.78); line(c, -0.1, -0.12, -0.1, 0.5);
    line(c, 0.42, -0.8, 0.42, -0.18); line(c, 0.92, -0.86, 0.92, -0.24);
  },
  fuse(c) {
    circ(c, -0.6, -0.35, 0.17, true); circ(c, -0.6, 0.35, 0.17, true);
    arrow(c, -0.28, 0, 0.35, 0, 0.26);
    circ(c, 0.68, 0, 0.24, true);
  },
  dissolve(c) {
    rect(c, -0.9, -0.6, 1.8, 1.2, false);
    dash(c, true); line(c, 0, -0.6, 0, 0.6); dash(c, false);
  },
  bevel(c) {
    c.globalAlpha = 0.35;
    poly(c, [-0.9, 0.85, -0.9, -0.9, 0.85, -0.9], false, false);
    c.globalAlpha = 1;
    poly(c, [-0.9, 0.85, -0.9, -0.3, -0.3, -0.9, 0.85, -0.9], false, false);
    c.lineWidth *= 1.7; line(c, -0.9, -0.3, -0.3, -0.9); c.lineWidth /= 1.7;
  },
  extrude(c) {
    rect(c, -0.85, -0.15, 1.0, 1.0, false);
    arrow(c, -0.35, -0.35, 0.55, -0.85, 0.3);
  },
  peak(c) {
    line(c, -0.9, 0.45, 0.9, 0.45);
    arrow(c, -0.5, 0.35, -0.5, -0.55, 0.26);
    arrow(c, 0.1, 0.35, 0.1, -0.55, 0.26);
    arrow(c, 0.7, 0.35, 0.7, -0.55, 0.26);
  },
  mirror(c) {
    poly(c, [-0.85, 0.6, -0.85, -0.6, -0.2, 0], true, false);
    dash(c, true); line(c, 0, -0.95, 0, 0.95); dash(c, false);
    poly(c, [0.85, 0.6, 0.85, -0.6, 0.2, 0], true, true);
  },
  hull(c) {
    poly(c, [-0.75, 0.35, -0.35, -0.75, 0.55, -0.6, 0.8, 0.3, 0.05, 0.8],
         true, false);
    dots(c, [-0.2, 0.1, 0.25, -0.2, 0.05, 0.45], 0.14);
  },
  bound(c) {
    const k = 0.55;
    for (const [sx, sy] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
      line(c, sx * 0.9, sy * 0.8, sx * (0.9 - k * 0.55), sy * 0.8);
      line(c, sx * 0.9, sy * 0.8, sx * 0.9, sy * (0.8 - k * 0.62));
    }
    dots(c, [-0.3, 0.15, 0.18, -0.28, 0.35, 0.3], 0.17);
  },
  decomp(c) {
    poly(c, [-0.9, -0.7, -0.1, -0.7, -0.1, 0.1, -0.9, 0.1], true, false);
    poly(c, [0.15, -0.7, 0.9, -0.7, 0.9, 0.75, 0.15, 0.75], true, false);
  },
  voronoi(c) {
    rect(c, -0.9, -0.9, 1.8, 1.8, false);
    line(c, -0.9, -0.15, -0.15, -0.15); line(c, -0.15, -0.9, -0.15, -0.15);
    line(c, -0.15, -0.15, 0.45, 0.35); line(c, 0.45, 0.35, 0.9, 0.2);
    line(c, 0.45, 0.35, 0.3, 0.9);
  },
  voronoi_cluster(c) {
    rect(c, -0.9, -0.9, 1.8, 1.8, false);
    line(c, -0.9, -0.15, -0.15, -0.15); line(c, -0.15, -0.9, -0.15, -0.15);
    line(c, -0.15, -0.15, 0.45, 0.35); line(c, 0.45, 0.35, 0.9, 0.2);
    line(c, 0.45, 0.35, 0.3, 0.9);
    c.globalAlpha = 0.45;
    poly(c, [-0.9, -0.15, -0.15, -0.15, 0.45, 0.35, 0.3, 0.9, -0.9, 0.9],
         true, true);
    c.globalAlpha = 1;
  },
  fracture(c) {
    poly(c, [-0.9, -0.75, -0.05, -0.75, -0.35, 0.05, -0.9, 0.75], true,
         false);
    poly(c, [0.15, -0.75, 0.9, -0.75, 0.9, 0.75, -0.15, 0.75], true, false);
  },
  explode(c) {
    poly(c, [-0.9, -0.35, -0.35, -0.9, -0.2, -0.3], true, false);
    poly(c, [0.35, -0.9, 0.9, -0.4, 0.3, -0.25], true, false);
    poly(c, [-0.3, 0.35, 0.3, 0.35, 0, 0.95], true, false);
    dots(c, [0, -0.05], 0.14);
  },
  facet(c) {
    poly(c, [-0.9, 0.55, -0.15, -0.7, 0.25, 0.55], true, false);
    poly(c, [0.25, 0.55, 0.55, -0.35, 0.95, 0.55], true, true);
  },
  convert(c) {
    rect(c, -0.9, -0.5, 0.62, 1.0, false);
    arrow(c, -0.12, 0, 0.3, 0, 0.26);
    circ(c, 0.62, 0, 0.32, false);
  },
  reduce(c) {
    poly(c, [-0.9, 0.6, -0.45, -0.7, 0, 0.6], true, false);
    line(c, -0.67, -0.05, -0.22, -0.05);
    arrow(c, 0.12, 0, 0.42, 0, 0.24);
    poly(c, [0.5, 0.6, 0.9, -0.7, 0.95, 0.6], true, false);
  },
  loopcut(c) {
    rect(c, -0.9, -0.9, 1.8, 1.8, false);
    line(c, -0.3, -0.9, -0.3, 0.9); line(c, 0.3, -0.9, 0.3, 0.9);
    c.lineWidth *= 1.8; line(c, 0, -0.9, 0, 0.9); c.lineWidth /= 1.8;
  },
  edgediv(c) {
    poly(c, [-0.85, 0.7, -0.85, -0.7, 0.85, -0.7], false, false);
    line(c, -0.85, 0.7, 0.85, -0.7);
    circ(c, 0, 0, 0.2, true);
  },
  ray(c) {
    c.beginPath(); c.moveTo(-0.95, 0.75);
    c.bezierCurveTo(-0.3, 0.3, 0.3, 0.95, 0.95, 0.5); c.stroke();
    arrow(c, -0.5, -0.9, -0.5, 0.42, 0.26);
    arrow(c, 0.15, -0.9, 0.15, 0.55, 0.26);
    circ(c, -0.5, 0.42, 0.15, true); circ(c, 0.15, 0.55, 0.15, true);
  },
  jitter(c) {
    dots(c, [-0.6, -0.55, 0.15, -0.7, 0.65, -0.1, -0.2, 0.2, 0.45, 0.65,
             -0.7, 0.6], 0.15);
    line(c, -0.6, -0.55, -0.35, -0.3); line(c, 0.65, -0.1, 0.4, 0.15);
  },
  matchsize(c) {
    dash(c, true); rect(c, -0.9, -0.75, 1.8, 1.5, false); dash(c, false);
    rect(c, -0.35, -0.3, 0.75, 0.62, false);
  },
  expand2d(c) {
    poly(c, [-0.45, -0.3, 0.2, -0.45, 0.42, 0.2, -0.2, 0.45], true, false);
    dash(c, true);
    poly(c, [-0.85, -0.6, 0.5, -0.85, 0.82, 0.45, -0.4, 0.85], true, false);
    dash(c, false);
    arrow(c, 0.35, -0.05, 0.72, -0.12, 0.22);
    arrow(c, -0.32, 0.1, -0.72, 0.18, 0.22);
  },
  tri2d(c) {
    // A ring of points + the triangles of the triangulation: the outer outline is the convex hull, two diagonals inside
    poly(c, [-0.85, -0.55, 0.0, -0.85, 0.85, -0.3, 0.55, 0.7, -0.5, 0.8],
         true, false);
    line(c, -0.85, -0.55, 0.85, -0.3);
    line(c, -0.85, -0.55, 0.55, 0.7);
    line(c, 0.85, -0.3, 0.55, 0.7);
    dots(c, [-0.85, -0.55, 0.0, -0.85, 0.85, -0.3, 0.55, 0.7, -0.5, 0.8],
         0.11);
  },
  viewport3d(c) {
    // A screen + the outline of a cube inside it
    rect(c, -0.88, -0.72, 1.76, 1.3, false);
    line(c, -0.35, 0.82, 0.35, 0.82);
    line(c, 0.0, 0.58, 0.0, 0.82);
    poly(c, [-0.42, -0.3, 0.1, -0.5, 0.52, -0.22, 0.0, -0.02], true, false);
    line(c, -0.42, -0.3, -0.42, 0.12);
    line(c, 0.52, -0.22, 0.52, 0.2);
    line(c, 0.0, -0.02, 0.0, 0.4);
    poly(c, [-0.42, 0.12, 0.0, 0.4, 0.52, 0.2], false, false);
  },
  display_flag(c) {
    // A solid small square (flag) + rays pointing out: "this node is being displayed"
    rect(c, -0.85, -0.5, 0.62, 0.62, true);
    line(c, 0.0, -0.2, 0.85, -0.2);
    poly(c, [0.45, 0.22, 0.85, 0.42, 0.45, 0.62], false, false);
    line(c, -0.54, 0.42, 0.2, 0.42);
  },
  spreadsheet(c) {
    rect(c, -0.88, -0.78, 1.76, 1.56, false);
    line(c, -0.88, -0.36, 0.88, -0.36);
    line(c, -0.88, 0.1, 0.88, 0.1);
    line(c, -0.3, -0.78, -0.3, 0.78);
    line(c, 0.3, -0.78, 0.3, 0.78);
  },
  voronoi2d(c) {
    // Three adjacent Voronoi cells + their sites
    line(c, -0.1, -0.9, -0.1, -0.1);
    line(c, -0.1, -0.1, -0.9, 0.35);
    line(c, -0.1, -0.1, 0.62, 0.2);
    line(c, 0.62, 0.2, 0.9, -0.5);
    line(c, 0.62, 0.2, 0.45, 0.9);
    dots(c, [-0.5, -0.5, 0.35, -0.45, 0.1, 0.55, -0.6, 0.7], 0.11);
  },
  filecache(c) {
    // A disk + a downward arrow
    c.beginPath(); c.ellipse(0, -0.55, 0.72, 0.24, 0, 0, Math.PI * 2);
    c.stroke();
    line(c, -0.72, -0.55, -0.72, 0.1);
    line(c, 0.72, -0.55, 0.72, 0.1);
    c.beginPath(); c.ellipse(0, 0.1, 0.72, 0.24, 0, 0, Math.PI); c.stroke();
    arrow(c, 0.0, 0.3, 0.0, 0.92, 0.26);
  },
  polyfill(c) {
    poly(c, [-0.85, -0.6, 0.2, -0.85, 0.85, 0.1, 0.35, 0.85, -0.6, 0.6],
         true, false);
    line(c, -0.3, -0.2, 0.35, -0.35); line(c, -0.35, 0.2, 0.5, 0.0);
    line(c, -0.1, 0.55, 0.25, 0.45);
  },
  displace(c) {
    line(c, -0.9, 0.55, 0.9, 0.55);
    c.beginPath(); c.moveTo(-0.9, -0.15);
    c.bezierCurveTo(-0.35, -0.95, 0.25, 0.3, 0.9, -0.5); c.stroke();
    arrow(c, -0.5, 0.45, -0.5, -0.4, 0.24);
    arrow(c, 0.4, 0.45, 0.4, -0.15, 0.24);
  },

  // ── attributes ──────────────────────────────────────────────
  attrib(c) { grid3(c, 0.16); circ(c, 0, 0, 0.3, false); },
  attrib_adjust(c) {                       // three faders: Attribute Adjust family (pcg100 s6)
    for (const [y, k] of [[-0.55, -0.3], [0, 0.45], [0.55, 0.05]]) {
      line(c, -0.85, y, 0.85, y);
      rect(c, k - 0.12, y - 0.18, 0.24, 0.36, true);
    }
  },
  attrib_new(c) {
    grid3(c, 0.14);
    line(c, 0.35, 0.62, 0.95, 0.62); line(c, 0.65, 0.32, 0.65, 0.92);
  },
  attrib_del(c) {
    grid3(c, 0.14);
    line(c, 0.4, 0.37, 0.92, 0.89); line(c, 0.92, 0.37, 0.4, 0.89);
  },
  attrib_copy(c) {
    rect(c, -0.9, -0.85, 1.0, 1.0, false);
    dots(c, [-0.62, -0.58, -0.22, -0.58, -0.62, -0.18], 0.13);
    c.globalAlpha = 0.5;
    rect(c, -0.1, -0.15, 1.0, 1.0, false);
    dots(c, [0.18, 0.12, 0.58, 0.12, 0.18, 0.52], 0.13);
    c.globalAlpha = 1;
  },
  attrib_blur(c) {
    circ(c, 0, 0, 0.22, true);
    circ(c, 0, 0, 0.5, false);
    dash(c, true); circ(c, 0, 0, 0.82, false); dash(c, false);
  },
  attrib_noise(c) {
    grid3(c, 0.13);
    c.beginPath(); c.moveTo(-0.9, 0.15);
    c.bezierCurveTo(-0.45, -0.85, 0.2, 0.75, 0.9, -0.35); c.stroke();
  },
  attrib_rand(c) {
    rect(c, -0.85, -0.85, 1.7, 1.7, false);
    dots(c, [-0.42, -0.42, 0.42, -0.42, 0, 0, -0.42, 0.42, 0.42, 0.42], 0.14);
  },
  attrib_cast(c) {
    rect(c, -0.92, -0.4, 0.3, 0.3, true); rect(c, -0.92, 0.12, 0.3, 0.3, true);
    rect(c, -0.5, -0.4, 0.3, 0.3, true); rect(c, -0.5, 0.12, 0.3, 0.3, true);
    arrow(c, -0.05, 0.0, 0.3, 0.0, 0.24);
    dots(c, [0.5, -0.25, 0.5, 0.27, 0.82, -0.25, 0.82, 0.27], 0.17);
  },
  attrib_promote(c) {
    dots(c, [-0.62, 0.7, 0, 0.7, 0.62, 0.7], 0.16);
    arrow(c, 0, 0.4, 0, -0.35, 0.28);
    circ(c, 0, -0.65, 0.25, true);
  },
  attrib_xfer(c) {
    dots(c, [-0.82, -0.55, -0.82, 0.1, -0.45, -0.2, -0.45, 0.55], 0.15);
    arrow(c, -0.1, 0, 0.3, 0, 0.26);
    dots(c, [0.55, -0.55, 0.55, 0.1, 0.82, -0.2, 0.82, 0.55], 0.15);
  },
  attrib_fade(c) {
    for (let i = 0; i < 5; i++) {
      c.globalAlpha = 1 - i * 0.2;
      circ(c, -0.8 + i * 0.4, 0, 0.19, true);
    }
    c.globalAlpha = 1;
    line(c, -0.95, 0.62, 0.95, 0.62);
  },
  measure(c) {
    rect(c, -0.9, -0.4, 1.8, 0.8, false);
    line(c, -0.45, -0.4, -0.45, 0.05);
    line(c, 0, -0.4, 0, 0.15);
    line(c, 0.45, -0.4, 0.45, 0.05);
  },
  centroid(c) {
    poly(c, [-0.85, -0.5, 0.3, -0.85, 0.85, 0.2, -0.2, 0.85], true, false);
    circ(c, 0.0, -0.1, 0.2, true);
    line(c, -0.5, -0.1, 0.5, -0.1); line(c, 0, -0.6, 0, 0.4);
  },
  normal(c) {
    line(c, -0.95, 0.55, 0.95, 0.55);
    arrow(c, -0.1, 0.55, -0.1, -0.75, 0.3);
    poly(c, [-0.1, 0.25, 0.2, 0.25, 0.2, 0.55], false, false);
  },
  wrangle(c) {
    c.beginPath();
    c.moveTo(-0.3, -0.85); c.bezierCurveTo(-0.75, -0.85, -0.5, 0, -0.9, 0);
    c.bezierCurveTo(-0.5, 0, -0.75, 0.85, -0.3, 0.85); c.stroke();
    c.beginPath();
    c.moveTo(0.3, -0.85); c.bezierCurveTo(0.75, -0.85, 0.5, 0, 0.9, 0);
    c.bezierCurveTo(0.5, 0, 0.75, 0.85, 0.3, 0.85); c.stroke();
  },

  // ── groups ────────────────────────────────────────────────
  group(c) {
    dash(c, true); rect(c, -0.9, -0.75, 1.8, 1.5, false); dash(c, false);
    dots(c, [-0.4, -0.25, 0.15, 0.2, 0.5, -0.3], 0.16);
  },
  group_new(c) {
    dash(c, true); rect(c, -0.95, -0.9, 1.5, 1.5, false); dash(c, false);
    dots(c, [-0.45, -0.15], 0.16);
    line(c, 0.35, 0.62, 0.95, 0.62); line(c, 0.65, 0.32, 0.65, 0.92);
  },
  group_del(c) {
    dash(c, true); rect(c, -0.95, -0.9, 1.5, 1.5, false); dash(c, false);
    dots(c, [-0.45, -0.15], 0.16);
    line(c, 0.38, 0.35, 0.92, 0.89); line(c, 0.92, 0.35, 0.38, 0.89);
  },
  group_expand(c) {
    dash(c, true); rect(c, -0.45, -0.4, 0.9, 0.8, false); dash(c, false);
    arrow(c, 0.5, 0, 0.92, 0, 0.22);
    arrow(c, -0.5, 0, -0.92, 0, 0.22);
    arrow(c, 0, -0.45, 0, -0.92, 0.22);
    arrow(c, 0, 0.45, 0, 0.92, 0.22);
  },
  group_edges(c) {
    poly(c, [-0.85, 0.7, -0.2, -0.75, 0.85, 0.7], true, false);
    c.lineWidth *= 2.2;
    line(c, -0.85, 0.7, -0.2, -0.75);
    c.lineWidth /= 2.2;
  },
  group_inside(c) {
    poly(c, [-0.85, -0.55, 0.35, -0.85, 0.85, 0.25, -0.25, 0.85], true,
         false);
    circ(c, -0.05, -0.1, 0.22, true);
    circ(c, 0.75, 0.72, 0.18, false);
  },
  group_promote(c) {
    dash(c, true); rect(c, -0.85, 0.2, 1.7, 0.7, false); dash(c, false);
    arrow(c, 0, 0.1, 0, -0.6, 0.3);
    dash(c, true); rect(c, -0.5, -0.95, 1.0, 0.4, false); dash(c, false);
  },

  // ── UV ────────────────────────────────────────────────
  uv(c) {
    rect(c, -0.85, -0.85, 1.7, 1.7, false);
    rect(c, -0.85, -0.85, 0.85, 0.85, true);
    rect(c, 0, 0, 0.85, 0.85, true);
  },
  uv_project(c) {
    circ(c, 0, -0.45, 0.45, false);
    dash(c, true);
    line(c, -0.45, -0.45, -0.45, 0.45); line(c, 0, -0.9, 0, 0.45);
    line(c, 0.45, -0.45, 0.45, 0.45);
    dash(c, false);
    line(c, -0.95, 0.5, 0.95, 0.5);
    rect(c, -0.45, 0.5, 0.9, 0.42, false);
  },
  uv_flatten(c) {
    c.beginPath(); c.moveTo(-0.9, -0.3);
    c.bezierCurveTo(-0.4, -0.85, 0.1, -0.1, -0.9, -0.3); c.stroke();
    arrow(c, -0.15, 0.1, 0.3, 0.1, 0.24);
    rect(c, 0.42, -0.35, 0.55, 0.9, false);
  },
  uv_layout(c) {
    rect(c, -0.9, -0.9, 1.8, 1.8, false);
    rect(c, -0.75, -0.75, 0.75, 0.55, true);
    rect(c, 0.1, -0.75, 0.62, 1.1, true);
    rect(c, -0.75, -0.05, 0.5, 0.8, true);
  },
  uv_seams(c) {
    poly(c, [-0.85, 0.65, -0.3, -0.8, 0.85, -0.5, 0.45, 0.8], true, false);
    dash(c, true); line(c, -0.3, -0.8, 0.05, 0.72); dash(c, false);
  },

  polypath(c) {
    // One **continuous** polyline, two hollow rings at the seams. The first version drew the seams as solid points,
    // which merged with the polyline's own rounded joins -- at 15px it was just an ordinary zigzag
    poly(c, [-0.9, 0.34, -0.3, -0.28, 0.3, 0.28, 0.9, -0.34], false, false);
    c.lineWidth *= 0.8;
    circ(c, -0.3, -0.28, 0.25, false);
    circ(c, 0.3, 0.28, 0.25, false);
    c.lineWidth /= 0.8;
  },
  join(c) {
    // Two **thick** lines + a **thin** connecting segment in between: that edge is what this node creates.
    // A thick/thin contrast survives shrinking better than dashes -- at 15px the gaps of a dashed line are invisible
    c.lineWidth *= 1.6;
    poly(c, [-0.9, 0.5, -0.62, -0.5, -0.36, 0.22], false, false);
    poly(c, [0.36, -0.22, 0.62, 0.5, 0.9, -0.5], false, false);
    c.lineWidth /= 1.6;
    dash(c, true); line(c, -0.36, 0.22, 0.36, -0.22); dash(c, false);
    dots(c, [-0.36, 0.22, 0.36, -0.22], 0.13);
  },

  // ── deform / primitives ─────────────────────────────────────
  torus(c) {
    c.beginPath(); c.ellipse(0, 0, 0.88, 0.52, 0, 0, Math.PI * 2); c.stroke();
    c.beginPath(); c.ellipse(0, 0, 0.34, 0.17, 0, 0, Math.PI * 2); c.stroke();
    c.globalAlpha = 0.5;
    c.beginPath();
    c.ellipse(0, -0.1, 0.6, 0.32, 0, Math.PI * 0.2, Math.PI * 0.8);
    c.stroke();
    c.globalAlpha = 1;
  },
  twist(c) {
    // Two crossing S curves = a twisted ribbon
    line(c, -0.6, -0.84, 0.6, -0.84);
    line(c, -0.6, 0.84, 0.6, 0.84);
    c.beginPath(); c.moveTo(-0.6, -0.84);
    c.bezierCurveTo(0.5, -0.3, -0.5, 0.3, 0.6, 0.84); c.stroke();
    c.beginPath(); c.moveTo(0.6, -0.84);
    c.bezierCurveTo(-0.5, -0.3, 0.5, 0.3, -0.6, 0.84); c.stroke();
  },
  soft_xform(c) {
    // Five arrows whose lengths fall off in a bell shape -- the falloff itself is that shape.
    // The first version drew "arrow + concentric falloff rings"; at 15px the arrow was swallowed by the rings and the whole thing read as a target
    const xs = [-0.78, -0.4, 0.0, 0.4, 0.78];
    const ln = [0.35, 0.85, 1.4, 0.85, 0.35];
    for (let i = 0; i < 5; i++) arrow(c, xs[i], 0.8, xs[i], 0.8 - ln[i], 0.17);
  },
  spherify(c) {
    // Left half a polyline, right half an arc: corners become a sphere. The first version was "dashed polygon around a circle";
    // the two lines blurred together at small sizes
    poly(c, [0, -0.85, -0.85, -0.3, -0.5, 0.62, 0, 0.85], false, false);
    c.beginPath(); c.arc(0, 0, 0.85, -Math.PI / 2, Math.PI / 2); c.stroke();
  },
  ends(c) {
    // Leave a 90° gap so the closing chord of the dashed line doesn't blur into the arc
    const R = 0.78, k = R * Math.SQRT1_2;
    c.beginPath(); c.arc(0, 0, R, Math.PI * 0.25, Math.PI * 1.75); c.stroke();
    dash(c, true); line(c, k, k, k, -k); dash(c, false);
    dots(c, [k, k, k, -k], 0.17);
  },

  // ── COP / image ────────────────────────────────────────
  image(c) {
    rect(c, -0.9, -0.7, 1.8, 1.4, false);
    poly(c, [-0.9, 0.45, -0.25, -0.2, 0.2, 0.25, 0.5, -0.05, 0.9, 0.45],
         false, false);
    circ(c, 0.42, -0.38, 0.17, true);
  },
  cop_noise(c) {
    rect(c, -0.9, -0.7, 1.8, 1.4, false);
    dots(c, [-0.6, -0.4, -0.15, 0.15, 0.3, -0.3, 0.62, 0.35, -0.45, 0.4,
             0.1, -0.55, 0.72, -0.1, -0.72, 0.05], 0.11);
  },
  cop_shape(c) {
    rect(c, -0.9, -0.7, 1.8, 1.4, false);
    circ(c, 0, 0, 0.42, true);
  },
  cop_gradient(c) {
    rect(c, -0.9, -0.7, 1.8, 1.4, false);
    for (let i = 0; i < 6; i++) {
      c.globalAlpha = 1 - i * 0.16;
      rect(c, -0.9 + i * 0.3, -0.7, 0.3, 1.4, true);
    }
    c.globalAlpha = 1;
  },
  cop_const(c) {
    rect(c, -0.9, -0.7, 1.8, 1.4, false);
    rect(c, -0.55, -0.4, 1.1, 0.8, true);
  },
  cop_blur(c) {
    rect(c, -0.9, -0.7, 1.8, 1.4, false);
    circ(c, 0, 0, 0.2, true);
    c.globalAlpha = 0.5; circ(c, 0, 0, 0.4, false);
    c.globalAlpha = 0.25; circ(c, 0, 0, 0.6, false);
    c.globalAlpha = 1;
  },
  cop_comp(c) {
    rect(c, -0.9, -0.85, 1.2, 1.2, false);
    c.globalAlpha = 0.75;
    rect(c, -0.3, -0.25, 1.2, 1.2, true);
    c.globalAlpha = 1;
  },
  cop_resize(c) {
    dash(c, true); rect(c, -0.9, -0.75, 1.8, 1.5, false); dash(c, false);
    rect(c, -0.9, -0.75, 1.0, 0.85, false);
    arrow(c, 0.15, 0.1, 0.85, 0.7, 0.26);
  },
  cop_in(c) {
    rect(c, -0.15, -0.7, 1.05, 1.4, false);
    arrow(c, -0.95, 0, -0.3, 0, 0.3);
  },
  cop_out(c) {
    rect(c, -0.9, -0.7, 1.05, 1.4, false);
    arrow(c, 0.3, 0, 0.95, 0, 0.3);
  },
  cop_info(c) {
    rect(c, -0.9, -0.7, 1.8, 1.4, false);
    line(c, -0.45, 0.4, -0.45, -0.1);
    line(c, 0, 0.4, 0, -0.45);
    line(c, 0.45, 0.4, 0.45, 0.05);
  },
  cop_warp(c) {
    rect(c, -0.9, -0.7, 1.8, 1.4, false);
    c.beginPath(); c.moveTo(-0.65, -0.35);
    c.bezierCurveTo(-0.15, -0.85, 0.15, 0.15, 0.65, -0.35); c.stroke();
    c.beginPath(); c.moveTo(-0.65, 0.35);
    c.bezierCurveTo(-0.15, -0.15, 0.15, 0.85, 0.65, 0.35); c.stroke();
  },
  cop_transform(c) {
    dash(c, true); rect(c, -0.88, -0.88, 1.15, 1.15, false); dash(c, false);
    const a = 0.42, ca = Math.cos(a), sa = Math.sin(a), p = [];
    for (const q of [[-0.58, -0.58], [0.58, -0.58], [0.58, 0.58],
                     [-0.58, 0.58]])
      p.push(q[0] * ca - q[1] * sa + 0.06, q[0] * sa + q[1] * ca + 0.06);
    poly(c, p, true, false);
    circ(c, 0.06, 0.06, 0.11, true);
  },
  cop_flip(c) {
    // Don't draw "two facing triangles" -- that's the mirror icon; they'd be indistinguishable at a glance.
    // Here: "an image + its shadow + a flipping arc arrow"
    rect(c, -0.88, -0.28, 0.76, 1.12, false);
    c.globalAlpha = 0.45; rect(c, 0.12, -0.28, 0.76, 1.12, true);
    c.globalAlpha = 1;
    c.beginPath(); c.moveTo(-0.5, -0.5);
    c.bezierCurveTo(-0.2, -0.95, 0.2, -0.95, 0.5, -0.5); c.stroke();
    poly(c, [0.26, -0.62, 0.56, -0.44, 0.24, -0.26], false, false);
  },
  cop_crop(c) {
    c.globalAlpha = 0.4; rect(c, -0.9, -0.72, 1.8, 1.44, false);
    c.globalAlpha = 1;
    poly(c, [-0.5, -0.9, -0.5, 0.42, 0.88, 0.42], false, false);
    poly(c, [0.3, 0.9, 0.3, -0.42, -0.88, -0.42], false, false);
  },
  cop_tile(c) {
    // Just a 2x2 grid would collide with subdiv. Each cell holds a small triangle with **alternating orientation**,
    // showing both copying and mirroring
    for (const y of [-0.86, 0.04]) for (const x of [-0.86, 0.04]) {
      rect(c, x, y, 0.8, 0.8, false);
      const fx = x < 0 ? 1 : -1, fy = y < 0 ? 1 : -1;
      const cx = x + 0.4 - fx * 0.26, cy = y + 0.4 - fy * 0.26;
      poly(c, [cx, cy, cx + fx * 0.44, cy, cx, cy + fy * 0.44], true, true);
    }
  },
  cop_distort(c) {
    // A distorted **grid**, not a wavy line -- the wavy line is the cop_warp icon
    for (const t of [-0.8, -0.27, 0.27, 0.8]) {
      c.beginPath(); c.moveTo(t, -0.82);
      c.bezierCurveTo(t + 0.15, -0.28, t - 0.15, 0.28, t, 0.82); c.stroke();
      c.beginPath(); c.moveTo(-0.82, t);
      c.bezierCurveTo(-0.28, t + 0.15, 0.28, t - 0.15, 0.82, t); c.stroke();
    }
  },
  cop_levels(c) {
    // Histogram + three sliders. Everyone has seen what the Levels node looks like
    const h = [0.25, 0.52, 0.86, 1.12, 0.94, 0.6, 0.35, 0.2];
    for (let i = 0; i < 8; i++)
      rect(c, -0.86 + i * 0.22, 0.42 - h[i], 0.16, h[i], true);
    line(c, -0.9, 0.46, 0.9, 0.46);
    for (const x of [-0.6, 0.0, 0.6])
      poly(c, [x - 0.14, 0.88, x + 0.14, 0.88, x, 0.56], true, true);
  },
  cop_remap(c) {
    for (let i = 0; i < 6; i++) {
      c.globalAlpha = 0.22 + i * 0.15;
      rect(c, -0.9 + i * 0.3, 0.44, 0.3, 0.42, true);
    }
    c.globalAlpha = 1;
    rect(c, -0.9, 0.44, 1.8, 0.42, false);
    c.beginPath(); c.moveTo(-0.88, 0.28);
    c.bezierCurveTo(-0.2, 0.22, 0.05, -0.85, 0.88, -0.78); c.stroke();
  },
  cop_quantize(c) {
    dash(c, true); line(c, -0.88, 0.85, 0.88, -0.8); dash(c, false);
    poly(c, [-0.88, 0.85, -0.44, 0.85, -0.44, 0.3, 0.0, 0.3, 0.0, -0.25,
             0.44, -0.25, 0.44, -0.8, 0.88, -0.8], false, false);
  },
  cop_fit(c) {
    line(c, -0.88, -0.88, -0.88, -0.2);
    line(c, -0.3, -0.88, -0.3, -0.2);
    arrow(c, -0.84, -0.54, -0.34, -0.54, 0.18);
    line(c, -0.88, 0.2, -0.88, 0.88);
    line(c, 0.88, 0.2, 0.88, 0.88);
    arrow(c, -0.84, 0.54, 0.84, 0.54, 0.22);
  },
  cop_luma(c) {
    circ(c, 0, 0, 0.52, false);
    c.beginPath(); c.arc(0, 0, 0.52, -Math.PI / 2, Math.PI / 2);
    c.closePath(); c.fill();
    for (let i = 0; i < 8; i++) {
      const a = i * Math.PI / 4;
      line(c, Math.cos(a) * 0.7, Math.sin(a) * 0.7,
           Math.cos(a) * 0.9, Math.sin(a) * 0.9);
    }
  },
  cop_morph(c) {
    poly(c, [-0.34, -0.48, 0.4, -0.34, 0.5, 0.34, -0.2, 0.54, -0.5, 0.06],
         true, true);
    dash(c, true);
    poly(c, [-0.58, -0.8, 0.7, -0.6, 0.84, 0.54, -0.3, 0.86, -0.84, 0.12],
         true, false);
    dash(c, false);
  },
  cop_edge(c) {
    c.globalAlpha = 0.32;
    poly(c, [-0.88, -0.7, 0.12, -0.7, -0.16, 0.7, -0.88, 0.7], true, true);
    c.globalAlpha = 1;
    rect(c, -0.88, -0.7, 1.76, 1.4, false);
    c.lineWidth *= 2.4; line(c, 0.12, -0.68, -0.16, 0.68); c.lineWidth /= 2.4;
  },
  cop_sharpen(c) {
    // A step edge + overshoot on both sides. The icon shows what over-sharpening looks like
    poly(c, [-0.9, 0.55, -0.55, 0.55, -0.38, 0.88, -0.1, -0.55,
             0.1, -0.88, 0.28, -0.55, 0.9, -0.55], false, false);
    c.globalAlpha = 0.45; dash(c, true);
    poly(c, [-0.9, 0.55, -0.38, 0.55, 0.1, -0.55, 0.9, -0.55], false, false);
    dash(c, false); c.globalAlpha = 1;
  },
  cop_median(c) {
    grid3(c, 0.15);
    c.lineWidth *= 1.8; circ(c, 0, 0, 0.32, false); c.lineWidth /= 1.8;
  },
  cop_sdf(c) {
    poly(c, [-0.3, -0.35, 0.28, -0.25, 0.35, 0.3, -0.18, 0.4, -0.38, 0.05],
         true, true);
    c.globalAlpha = 0.6;
    poly(c, [-0.5, -0.58, 0.48, -0.45, 0.58, 0.5, -0.3, 0.64, -0.62, 0.08],
         true, false);
    c.globalAlpha = 0.3;
    poly(c, [-0.7, -0.82, 0.68, -0.66, 0.82, 0.7, -0.42, 0.88, -0.86, 0.1],
         true, false);
    c.globalAlpha = 1;
  },
  control(c) {
    rect(c, -0.9, -0.7, 1.8, 1.4, false);
    poly(c, [-0.5, 0.35, -0.15, -0.35, 0.35, -0.35, 0.62, 0.35], true,
         false);
    line(c, -0.15, -0.35, -0.05, 0.35); line(c, 0.35, -0.35, 0.3, 0.35);
  },
  idmask(c) {
    rect(c, -0.9, -0.7, 1.8, 1.4, false);
    line(c, -0.1, -0.7, -0.1, 0.7); line(c, -0.1, 0.05, 0.9, 0.05);
    c.globalAlpha = 0.6; rect(c, -0.9, -0.7, 0.8, 1.4, true);
    c.globalAlpha = 1;
  },
  seq(c) {
    rect(c, -0.9, -0.85, 1.35, 1.1, false);
    rect(c, -0.62, -0.55, 1.35, 1.1, false);
    rect(c, -0.35, -0.25, 1.35, 1.1, false);
  },
  seq_in(c) {
    rect(c, -0.2, -0.85, 0.9, 0.8, false);
    rect(c, 0.0, -0.6, 0.9, 0.8, false);
    arrow(c, -0.95, -0.35, -0.35, -0.35, 0.28);
  },
  seq_out(c) {
    rect(c, -0.9, -0.85, 0.9, 0.8, false);
    rect(c, -0.7, -0.6, 0.9, 0.8, false);
    arrow(c, 0.3, 0.55, 0.9, 0.55, 0.28);
  },
  seq_pick(c) {
    rect(c, -0.95, -0.85, 1.1, 0.95, false);
    rect(c, -0.72, -0.6, 1.1, 0.95, false);
    c.lineWidth *= 1.8;
    rect(c, -0.35, -0.15, 1.25, 1.05, false);
    c.lineWidth /= 1.8;
  },

  // ── rendering ──────────────────────────────────────────────
  camera(c) {
    rect(c, -0.9, -0.45, 1.25, 0.95, false);
    poly(c, [0.35, -0.2, 0.9, -0.62, 0.9, 0.68, 0.35, 0.25], true, false);
    circ(c, -0.35, 0.02, 0.25, false);
  },
  campath(c) {
    dash(c, true);
    c.beginPath(); c.arc(0, 0.3, 0.85, Math.PI, Math.PI * 2); c.stroke();
    dash(c, false);
    poly(c, [-0.95, 0.15, -0.5, -0.1, -0.5, 0.45], true, true);
    circ(c, 0, 0.3, 0.15, true);
  },
  render(c) {
    poly(c, [-0.9, 0, -0.25, -0.75, -0.25, 0.75], true, false);
    rect(c, 0.25, -0.72, 0.68, 1.45, false);
    dash(c, true);
    line(c, -0.25, -0.75, 0.25, -0.72); line(c, -0.25, 0.75, 0.25, 0.73);
    dash(c, false);
  },
  motion(c) {
    arrow(c, -0.9, -0.55, -0.15, -0.55, 0.24);
    arrow(c, -0.9, 0, -0.05, 0.12, 0.24);
    arrow(c, -0.9, 0.55, -0.25, 0.72, 0.24);
    arrow(c, 0.3, -0.35, 0.92, -0.2, 0.24);
    arrow(c, 0.3, 0.35, 0.92, 0.55, 0.24);
  },
  backproject(c) {
    rect(c, 0.25, -0.85, 0.68, 1.7, false);
    c.beginPath(); c.moveTo(-0.95, 0.5);
    c.bezierCurveTo(-0.35, 0.1, -0.3, -0.6, -0.95, -0.75); c.stroke();
    arrow(c, 0.15, -0.1, -0.5, -0.1, 0.28);
  },
  uv_resolve(c) {
    rect(c, -0.9, -0.9, 1.8, 1.8, false);
    rect(c, -0.9, -0.9, 0.9, 0.9, true);
    rect(c, 0, 0, 0.9, 0.9, true);
    dash(c, true); rect(c, 0, -0.9, 0.9, 0.9, false); dash(c, false);
  },
  texrender(c) {
    rect(c, -0.9, -0.75, 0.85, 1.5, false);
    rect(c, -0.9, -0.75, 0.42, 0.75, true);
    rect(c, -0.48, 0, 0.42, 0.75, true);
    arrow(c, 0.1, 0, 0.6, 0, 0.26);
    poly(c, [0.95, -0.5, 0.95, 0.5, 0.68, 0], true, false);
  },

  // ── scattering ──────────────────────────────────────────────
  scatter(c) {
    c.beginPath(); c.moveTo(-0.95, 0.55);
    c.bezierCurveTo(-0.3, 0.15, 0.3, 0.9, 0.95, 0.45); c.stroke();
    dots(c, [-0.6, 0.2, -0.15, 0.35, 0.25, 0.62, 0.65, 0.5, -0.85, 0.42,
             0.05, 0.48], 0.14);
  },
  scatter_vol(c) {
    rect(c, -0.75, -0.55, 1.4, 1.4, false);
    poly(c, [-0.75, -0.55, -0.35, -0.9, 0.9, -0.9, 0.9, 0.5, 0.65, 0.85],
         false, false);
    line(c, 0.65, -0.55, 0.9, -0.9);
    dots(c, [-0.35, -0.1, 0.15, 0.3, 0.35, -0.3, -0.15, 0.5], 0.13);
  },
  copyto(c) {
    line(c, -0.95, 0.8, 0.95, 0.8);
    dots(c, [-0.6, 0.8, 0.0, 0.8, 0.6, 0.8], 0.14);
    rect(c, -0.85, -0.2, 0.5, 0.5, false);
    rect(c, -0.25, -0.55, 0.5, 0.5, false);
    rect(c, 0.35, -0.2, 0.5, 0.5, false);
  },

  // ── loops / parameters / output ────────────────────────────────
  loop_begin(c) {
    c.beginPath(); c.arc(0.05, 0, 0.62, 0.6, Math.PI * 2 - 0.1); c.stroke();
    poly(c, [0.25, 0.75, 0.55, 0.45, 0.68, 0.85], true, true);
    line(c, -0.92, -0.85, -0.92, 0.85); line(c, -0.92, -0.85, -0.55, -0.85);
    line(c, -0.92, 0.85, -0.55, 0.85);
  },
  loop_end(c) {
    c.beginPath(); c.arc(-0.05, 0, 0.62, 0.6, Math.PI * 2 - 0.1); c.stroke();
    poly(c, [0.15, 0.75, 0.45, 0.45, 0.58, 0.85], true, true);
    line(c, 0.92, -0.85, 0.92, 0.85); line(c, 0.92, -0.85, 0.55, -0.85);
    line(c, 0.92, 0.85, 0.55, 0.85);
  },
  clock(c) {
    circ(c, 0, 0, 0.82, false);
    line(c, 0, 0, 0, -0.5); line(c, 0, 0, 0.38, 0.2);
  },
  frame_begin(c) {
    circ(c, 0.15, 0, 0.66, false);
    line(c, 0.15, 0, 0.15, -0.42); line(c, 0.15, 0, 0.45, 0.18);
    line(c, -0.92, -0.85, -0.92, 0.85); line(c, -0.92, -0.85, -0.6, -0.85);
    line(c, -0.92, 0.85, -0.6, 0.85);
  },
  frame_end(c) {
    circ(c, -0.15, 0, 0.66, false);
    line(c, -0.15, 0, -0.15, -0.42); line(c, -0.15, 0, 0.15, 0.18);
    line(c, 0.92, -0.85, 0.92, 0.85); line(c, 0.92, -0.85, 0.6, -0.85);
    line(c, 0.92, 0.85, 0.6, 0.85);
  },
  value(c) {
    line(c, -0.9, -0.45, 0.9, -0.45); circ(c, 0.2, -0.45, 0.26, true);
    line(c, -0.9, 0.45, 0.9, 0.45); circ(c, -0.35, 0.45, 0.26, true);
  },
  expr(c) {
    c.beginPath(); c.moveTo(-0.9, 0.7);
    c.bezierCurveTo(-0.3, 0.7, -0.1, -0.7, 0.55, -0.7); c.stroke();
    line(c, -0.9, 0.0, 0.2, 0.0);
    dots(c, [0.78, -0.7], 0.2);
  },
  export_(c) {
    arrow(c, 0, -0.85, 0, 0.15, 0.3);
    poly(c, [-0.85, 0.25, -0.85, 0.8, 0.85, 0.8, 0.85, 0.25], false, false);
  },
  // Import: mirror of export_ (arrow pointing up, coming out of the disk), plus a hint of a mesh,
  // so it doesn't look like cop_in on the COP side
  import_(c) {
    arrow(c, 0, 0.35, 0, -0.5, 0.3);
    poly(c, [-0.85, 0.45, -0.85, 0.85, 0.85, 0.85, 0.85, 0.45], false, false);
    line(c, -0.62, -0.72, 0.62, -0.72);
  },
  preview(c) {
    c.beginPath(); c.moveTo(-0.95, 0);
    c.bezierCurveTo(-0.4, -0.8, 0.4, -0.8, 0.95, 0);
    c.bezierCurveTo(0.4, 0.8, -0.4, 0.8, -0.95, 0);
    c.closePath(); c.stroke();
    circ(c, 0, 0, 0.3, true);
  },
  trace(c) {
    rect(c, -0.9, -0.8, 0.6, 0.6, true);
    rect(c, -0.3, -0.8, 0.6, 0.6, true);
    rect(c, -0.9, -0.2, 0.6, 0.6, true);
    c.globalAlpha = 0.3; rect(c, -0.3, -0.2, 0.6, 0.6, false);
    c.globalAlpha = 1;
    c.beginPath(); c.moveTo(0.35, 0.9);
    c.bezierCurveTo(0.25, 0.2, 0.95, -0.1, 0.5, -0.85); c.stroke();
  },
  connectivity(c) {
    dots(c, [-0.7, -0.6, 0, -0.75, -0.4, 0.1], 0.16);
    line(c, -0.7, -0.6, 0, -0.75); line(c, -0.7, -0.6, -0.4, 0.1);
    dots(c, [0.6, 0.25, 0.85, -0.35], 0.16);
    line(c, 0.6, 0.25, 0.85, -0.35);
  },
  // Keyframe curve: diamonds are keyframes. Distinct from clock (pure time) -- one is "which frame",
  // the other is "what the value should be by which frame"
  channel(c) {
    c.beginPath(); c.moveTo(-0.78, 0.58);
    c.bezierCurveTo(-0.3, 0.58, -0.25, -0.68, 0.05, -0.68);
    c.bezierCurveTo(0.42, -0.68, 0.45, 0.5, 0.78, 0.5); c.stroke();
    for (const p of [[-0.78, 0.58], [0.05, -0.68], [0.78, 0.5]])
      poly(c, [p[0], p[1] - 0.2, p[0] + 0.2, p[1],
               p[0], p[1] + 0.2, p[0] - 0.2, p[1]], true, true);
  },
  timeblend(c) {
    c.globalAlpha = 0.35;
    rect(c, -0.92, -0.5, 0.48, 1.0, false);
    rect(c, 0.44, -0.5, 0.48, 1.0, false);
    c.globalAlpha = 1;
    rect(c, -0.24, -0.7, 0.48, 1.4, true);
  },
  trail(c) {
    for (let i = 0; i < 4; i++) {
      c.globalAlpha = 0.25 + i * 0.25;
      circ(c, -0.72 + i * 0.5, 0.42 - i * 0.28, 0.2, true);
    }
    c.globalAlpha = 1;
  },
  retime(c) {
    line(c, -0.9, 0.58, 0.9, 0.58);
    for (const x of [-0.88, -0.5, -0.2, 0.0, 0.16, 0.38, 0.66, 0.88])
      line(c, x, 0.26, x, 0.58);
    arrow(c, -0.7, -0.45, 0.72, -0.45, 0.28);
  },
  // Camera projection: a camera frustum + an imprint landing on a face
  attrib_cam(c) {
    poly(c, [-0.9, -0.85, -0.35, -0.85, -0.35, -0.35, -0.9, -0.35],
         true, false);
    poly(c, [-0.35, -0.75, 0.05, -0.95, 0.05, -0.25, -0.35, -0.45],
         true, true);
    line(c, -0.62, -0.3, 0.1, 0.72);
    line(c, -0.62, -0.3, -0.72, 0.6);
    c.globalAlpha = 0.85;
    poly(c, [-0.85, 0.6, -0.2, 0.28, 0.35, 0.55, 0.15, 0.88, -0.6, 0.9],
         true, true);
    c.globalAlpha = 1;
  },
  // Parameter panel: three rows of sliders. Distinct from value (two lines with dots) -- that one is "a value",
  // this one is "a whole panel"
  panel(c) {
    rect(c, -0.9, -0.85, 1.8, 1.7, false);
    for (let i = 0; i < 3; i++) {
      const y = -0.42 + i * 0.42;
      line(c, -0.68, y, 0.68, y);
      circ(c, -0.4 + i * 0.42, y, 0.17, true);
    }
  },
  // JSON in: a pair of curly braces + three points falling out
  json_in(c) {
    c.beginPath(); c.moveTo(-0.28, -0.8);
    c.bezierCurveTo(-0.72, -0.8, -0.5, -0.12, -0.86, -0.12);
    c.bezierCurveTo(-0.5, -0.12, -0.72, 0.56, -0.28, 0.56); c.stroke();
    c.beginPath(); c.moveTo(0.28, -0.8);
    c.bezierCurveTo(0.72, -0.8, 0.5, -0.12, 0.86, -0.12);
    c.bezierCurveTo(0.5, -0.12, 0.72, 0.56, 0.28, 0.56); c.stroke();
    dots(c, [-0.3, 0.88, 0.02, 0.88, 0.34, 0.88], 0.13);
  },
  // JSON out: the same braces, with the points above
  json_out(c) {
    c.beginPath(); c.moveTo(-0.28, -0.5);
    c.bezierCurveTo(-0.72, -0.5, -0.5, 0.18, -0.86, 0.18);
    c.bezierCurveTo(-0.5, 0.18, -0.72, 0.86, -0.28, 0.86); c.stroke();
    c.beginPath(); c.moveTo(0.28, -0.5);
    c.bezierCurveTo(0.72, -0.5, 0.5, 0.18, 0.86, 0.18);
    c.bezierCurveTo(0.5, 0.18, 0.72, 0.86, 0.28, 0.86); c.stroke();
    dots(c, [-0.3, -0.82, 0.02, -0.82, 0.34, -0.82], 0.13);
  },
  // JSON written into a panel: a curly brace on the left, an arrow pointing into the slider panel on the right.
  // Distinct from panel -- that one is "a panel", this one is "something being poured into a panel"
  params_fill(c) {
    c.beginPath(); c.moveTo(-0.45, -0.82);
    c.bezierCurveTo(-0.85, -0.82, -0.62, -0.1, -0.96, -0.1);
    c.bezierCurveTo(-0.62, -0.1, -0.85, 0.62, -0.45, 0.62); c.stroke();
    arrow(c, -0.4, -0.1, 0.0, -0.1, 0.2);
    // **No border.** The first version drew a frame around the three slider rows; rendering the contact sheet showed frame +
    // rows + slider knobs blurring into a solid block in the 24px title bar -- line width is computed for the whole icon,
    // so squeezed into the right half everything piled up. Without the frame and with rows spread out, it's recognizable as a panel
    for (let i = 0; i < 3; i++) {
      const y = -0.52 + i * 0.52;
      line(c, 0.1, y, 0.72, y);
      circ(c, 0.2 + i * 0.22, y, 0.14, true);
    }
  },
  // Pick one key: three rows inside braces, **only the middle row** wired out -- the difference from params_fill
  // (the whole panel being filled) is "one line out" vs "three lines in"
  param_pick(c) {
    c.beginPath(); c.moveTo(-0.38, -0.88);
    c.bezierCurveTo(-0.78, -0.88, -0.56, -0.1, -0.92, -0.1);
    c.bezierCurveTo(-0.56, -0.1, -0.78, 0.68, -0.38, 0.68); c.stroke();
    c.globalAlpha = 0.4;
    line(c, -0.2, -0.6, 0.18, -0.6);
    line(c, -0.2, 0.4, 0.18, 0.4);
    c.globalAlpha = 1;
    arrow(c, -0.2, -0.1, 0.58, -0.1, 0.24);
    circ(c, 0.84, -0.1, 0.15, true);   // 0.84+0.15 just stays inside [-1,1]
  },
  // Measure: a caliper gripping a shape
  metrics(c) {
    poly(c, [-0.55, 0.7, -0.15, -0.5, 0.35, 0.15], true, false);
    line(c, -0.92, -0.85, 0.92, -0.85);
    for (const x of [-0.92, -0.46, 0, 0.46, 0.92])
      line(c, x, -0.85, x, -0.58);
    line(c, 0.66, -0.85, 0.66, 0.35);
    circ(c, 0.66, 0.35, 0.16, true);
  },
  // Pick best: three candidates, the middle one circled
  select_best(c) {
    c.globalAlpha = 0.4;
    rect(c, -0.92, -0.2, 0.5, 0.5, false);
    rect(c, 0.42, -0.2, 0.5, 0.5, false);
    c.globalAlpha = 1;
    rect(c, -0.3, -0.45, 0.6, 0.6, true);
    poly(c, [-0.18, 0.5, 0, 0.86, 0.34, 0.28], false, false);
  },
  // ── the heightmap family: all share the same "terrain profile line" at the bottom, with what each computes drawn above,
  //    recognizable as one family at a glance, yet distinct from each other
  // height -> normal: three short arrows standing perpendicular on the profile line
  // (the first version's profile undulated too much and the arrows were too short; arrowheads tangled with the profile line -- only visible once rendered)
  h2n(c) {
    poly(c, [-0.95, 0.8, -0.35, 0.45, 0.35, 0.75, 0.95, 0.45],
         false, false);
    arrow(c, -0.65, 0.62, -0.95, -0.2, 0.22);
    arrow(c, 0.0, 0.6, 0.18, -0.35, 0.22);
    arrow(c, 0.65, 0.6, 0.95, -0.2, 0.22);
  },
  // normal -> height: a row of slanted arrows "integrating" into the solid terrain below
  n2h(c) {
    arrow(c, -0.75, -0.3, -0.55, -0.85, 0.18);
    arrow(c, -0.15, -0.3, -0.05, -0.88, 0.18);
    arrow(c, 0.45, -0.3, 0.35, -0.88, 0.18);
    poly(c, [-0.95, 0.9, -0.95, 0.35, -0.4, 0.05, 0.1, 0.25, 0.55, 0.0,
             0.95, 0.2, 0.95, 0.9], true, true);
  },
  // AO: a valley, a semi-transparent darkness at the bottom
  // (the first version's dark polygon self-intersected and filled as empty)
  h2ao(c) {
    c.globalAlpha = 0.4;
    poly(c, [-0.62, 0.0, 0.0, 0.72, 0.62, 0.0], true, true);
    c.globalAlpha = 1;
    poly(c, [-0.95, -0.75, 0.0, 0.72, 0.95, -0.75], false, false);
  },
  // Shadow: the sun at top right, a bump, a shadow cast onto the ground on the left
  h2shadow(c) {
    circ(c, 0.68, -0.68, 0.22, true);
    rect(c, -0.05, -0.05, 0.4, 0.75, false);
    line(c, -0.95, 0.7, 0.95, 0.7);
    c.globalAlpha = 0.5;
    poly(c, [-0.05, -0.05, -0.85, 0.7, -0.05, 0.7], true, true);
    c.globalAlpha = 1;
  },
  // Caustics: a wavy water surface on top, a few rays converging on a bright spot below
  caustics(c) {
    c.beginPath(); c.moveTo(-0.95, -0.55);
    c.bezierCurveTo(-0.6, -0.95, -0.3, -0.15, 0.0, -0.55);
    c.bezierCurveTo(0.3, -0.95, 0.6, -0.15, 0.95, -0.55); c.stroke();
    line(c, -0.6, -0.5, -0.05, 0.62);
    line(c, 0.6, -0.5, 0.05, 0.62);
    line(c, 0.0, -0.45, 0.0, 0.62);
    circ(c, 0.0, 0.75, 0.16, true);
  },
  // Refraction: a vertical line of sight hits a slanted interface and bends
  // (in the first version the line of sight went straight through the interface and read as a "+")
  refract(c) {
    c.beginPath(); c.moveTo(-0.95, 0.05);
    c.bezierCurveTo(-0.7, -0.3, -0.4, -0.3, 0.3, -0.05);
    c.bezierCurveTo(0.55, -0.25, 0.8, -0.1, 0.95, -0.2); c.stroke();
    // The second version added a dim line for "where it would go without refraction", which joined the incident ray into a vertical line,
    // still a "+". Keep only incident + bend, and bend harder
    line(c, -0.55, -0.95, -0.55, -0.1);
    arrow(c, -0.55, -0.1, 0.6, 0.85, 0.24);
  },
  // Normal blending: two arrows merging from below into one
  combine_n(c) {
    line(c, -0.7, 0.85, 0.0, 0.1);
    line(c, 0.7, 0.85, 0.0, 0.1);
    arrow(c, 0.0, 0.1, 0.0, -0.9, 0.24);
    dots(c, [-0.7, 0.85, 0.7, 0.85], 0.12);
  },
  // Normal conversion: a signed [-1,1] arrow and a 0-1 square converting into each other
  convert_n(c) {
    arrow(c, -0.9, 0.55, -0.4, -0.35, 0.2);
    rect(c, 0.25, -0.55, 0.65, 0.65, true);
    arrow(c, -0.25, -0.62, 0.12, -0.62, 0.16);
    arrow(c, 0.12, 0.55, -0.25, 0.55, 0.16);
  },
  // Erosion: a mountain outline with a gully branching downhill on the slope (main gully + side gullies)
  erosion(c) {
    poly(c, [-0.95, 0.85, -0.15, -0.8, 0.15, -0.55, 0.95, 0.85],
         false, false);
    line(c, -0.05, -0.55, 0.05, 0.8);
    line(c, 0.0, -0.1, -0.4, 0.45);
    line(c, 0.02, 0.2, 0.42, 0.62);
    c.globalAlpha = 0.5;
    line(c, -0.2, 0.2, -0.55, 0.62);
    line(c, 0.2, 0.42, 0.55, 0.75);
    c.globalAlpha = 1;
  },
  // ── the image analysis family
  // Slope: a wedge-shaped ramp + a protractor arc at the base corner
  slope(c) {
    poly(c, [-0.9, 0.75, 0.9, 0.75, 0.9, -0.75], true, false);
    c.beginPath(); c.arc(-0.9, 0.75, 0.7, -0.69, 0); c.stroke();
  },
  // Curvature: a curve with an osculating circle on top
  curvature(c) {
    c.beginPath(); c.moveTo(-0.95, 0.75);
    c.bezierCurveTo(-0.5, -0.55, 0.5, -0.55, 0.95, 0.75); c.stroke();
    // (the first version filled the circle semi-transparent and added a center dot; it read as an eye)
    c.globalAlpha = 0.5;
    dash(c, true);
    circ(c, 0.0, 0.18, 0.42, false);
    dash(c, false);
    c.globalAlpha = 1;
  },
  // Statistics: box plot (whiskers + box + median line)
  stats(c) {
    line(c, 0.0, -0.9, 0.0, -0.45);
    line(c, 0.0, 0.45, 0.0, 0.9);
    line(c, -0.25, -0.9, 0.25, -0.9);
    line(c, -0.25, 0.9, 0.25, 0.9);
    rect(c, -0.5, -0.45, 1.0, 0.9, false);
    line(c, -0.5, 0.08, 0.5, 0.08);
  },
  // Histogram: a row of bars of different heights, a flattened line above
  histogram(c) {
    const hs = [0.35, 0.9, 1.3, 0.7, 0.45];
    for (let i = 0; i < 5; i++) {
      const x = -0.9 + i * 0.37;
      rect(c, x, 0.9 - hs[i], 0.3, hs[i], true);
    }
    c.globalAlpha = 0.6;
    dash(c, true);
    line(c, -0.95, -0.2, 0.95, -0.2);
    dash(c, false);
    c.globalAlpha = 1;
  },
  // Connected segmentation: three disconnected blobs, each with its own fill
  segment(c) {
    poly(c, [-0.9, -0.6, -0.3, -0.85, -0.15, -0.3, -0.7, -0.1], true, true);
    poly(c, [0.2, -0.75, 0.9, -0.6, 0.75, 0.05, 0.25, -0.1], true, false);
    c.globalAlpha = 0.5;
    poly(c, [-0.55, 0.3, 0.35, 0.25, 0.5, 0.85, -0.7, 0.85], true, true);
    c.globalAlpha = 1;
  },
  // Compare: two offset images with a "≈" between them
  // Compare: two images left and right with a "≈" between them
  compare(c) {
    // Two images left and right with a "≈" between. Not "two images stacked" -- that's COP Composite
    rect(c, -0.97, -0.6, 0.6, 1.2, false);
    c.globalAlpha = 0.5;
    rect(c, 0.37, -0.6, 0.6, 1.2, true);
    c.globalAlpha = 1;
    c.beginPath(); c.moveTo(-0.16, -0.16);
    c.bezierCurveTo(-0.08, -0.28, 0.08, -0.04, 0.16, -0.16); c.stroke();
    c.beginPath(); c.moveTo(-0.16, 0.16);
    c.bezierCurveTo(-0.08, 0.04, 0.08, 0.28, 0.16, 0.16); c.stroke();
  },
  // ── the HeightField family
  // Mask by feature: a mountain profile, the steep part filled in
  hf_mask(c) {
    poly(c, [-0.95, 0.8, -0.4, 0.45, 0.05, -0.75, 0.45, 0.1, 0.95, 0.8],
         false, false);
    poly(c, [-0.4, 0.45, 0.05, -0.75, 0.45, 0.1, 0.45, 0.8, -0.4, 0.8],
         true, true);
  },
  // Terraces: a stepped profile
  terrace(c) {
    poly(c, [-0.95, 0.85, -0.95, 0.5, -0.45, 0.5, -0.35, 0.1, 0.1, 0.1,
             0.2, -0.3, 0.55, -0.3, 0.65, -0.72, 0.95, -0.72],
         false, false);
    line(c, -0.95, 0.85, 0.95, 0.85);
  },
  // Thermal erosion: a sharp peak slumped into a pile at its foot (dashed is the original peak)
  slump(c) {
    c.globalAlpha = 0.45;
    dash(c, true);
    poly(c, [-0.35, 0.8, 0.0, -0.9, 0.35, 0.8], false, false);
    dash(c, false);
    c.globalAlpha = 1;
    poly(c, [-0.95, 0.8, -0.5, 0.5, 0.0, -0.25, 0.5, 0.5, 0.95, 0.8],
         true, true);
  },
  // HeightField to mesh: an undulating quad mesh (perspective)
  hf_mesh(c) {
    for (let i = 0; i < 4; i++) {
      const y = -0.35 + i * 0.35, sx = 0.55 + i * 0.13;
      c.beginPath(); c.moveTo(-sx, y);
      c.bezierCurveTo(-sx * 0.3, y - 0.25, sx * 0.3, y + 0.15, sx, y - 0.1);
      c.stroke();
    }
    line(c, -0.55, -0.35, -0.94, 0.7);
    line(c, 0.0, -0.4, 0.0, 0.66);
    line(c, 0.55, -0.45, 0.94, 0.6);
  },
  // Flow accumulation: a river network tree, thicker further downstream (lower)
  flow_acc(c) {
    const seg = (w, pts) => {
      c.lineWidth *= w; poly(c, pts, false, false); c.lineWidth /= w;
    };
    seg(0.7, [-0.85, -0.85, -0.6, -0.45, -0.35, -0.2]);
    seg(0.7, [-0.15, -0.9, -0.25, -0.5, -0.35, -0.2]);
    seg(0.7, [0.85, -0.8, 0.6, -0.45, 0.35, -0.3]);
    seg(0.7, [0.3, -0.9, 0.35, -0.3]);
    seg(1.3, [-0.35, -0.2, -0.1, 0.2]);
    seg(1.3, [0.35, -0.3, 0.2, 0.05, -0.1, 0.2]);
    seg(0.7, [0.85, 0.1, 0.45, 0.35, 0.1, 0.5]);
    seg(2.2, [-0.1, 0.2, 0.1, 0.5, 0.0, 0.92]);
  },
  // Hydraulic erosion: a mountain profile cut by two V-shaped valleys
  stream_power(c) {
    const pts = [-0.95, 0.8, -0.7, -0.2, -0.45, 0.35, -0.2, -0.75,
                 0.1, 0.45, 0.4, -0.45, 0.95, 0.8];
    c.globalAlpha = 0.4; poly(c, pts, true, true); c.globalAlpha = 1;
    poly(c, pts, false, false);
  },
  // Road Network: a road winding up between contour lines, a branch off it to a second place
  road_network(c) {
    c.globalAlpha = 0.35;
    poly(c, [-0.95, 0.35, -0.4, 0.05, 0.3, 0.15, 0.95, -0.15], false, false);
    poly(c, [-0.95, -0.25, -0.3, -0.55, 0.4, -0.45, 0.95, -0.75], false, false);
    c.globalAlpha = 1;
    poly(c, [-0.75, 0.8, -0.1, 0.55, 0.55, 0.35, -0.3, 0.05, 0.1, -0.3, 0.65, -0.65], false, false);
    poly(c, [0.55, 0.35, 0.85, 0.75], false, false);
    dots(c, [-0.75, 0.8, 0.65, -0.65, 0.85, 0.75], 0.13);
  },
  // Splat Map: a piece of land divided into several materials of different shades, tiling it exactly
  splat(c) {
    const A = [[-0.9, -0.9, 0.9, -0.9, 0.9, -0.2, 0.1, 0.1, -0.9, -0.3],
               [-0.9, -0.3, 0.1, 0.1, -0.2, 0.9, -0.9, 0.9],
               [0.1, 0.1, 0.9, -0.2, 0.9, 0.9, -0.2, 0.9]];
    const al = [1, 0.55, 0.25];
    for (let i = 0; i < 3; i++) {
      c.globalAlpha = al[i]; poly(c, A[i], true, true);
    }
    c.globalAlpha = 1;
    rect(c, -0.9, -0.9, 1.8, 1.8, false);
  },
  // Regional Prompt: a speech bubble over zoned land plots (one sentence per zone)
  region_prompt(c) {
    c.globalAlpha = 0.45;
    poly(c, [-0.9, 0.1, 0.2, -0.1, 0.9, 0.3, 0.9, 0.9, -0.9, 0.9], true,
         true);
    c.globalAlpha = 1;
    poly(c, [-0.9, 0.1, 0.2, -0.1, 0.9, 0.3], false, false);
    rect(c, -0.55, -0.95, 1.3, 0.75, false);
    poly(c, [-0.3, -0.2, -0.4, 0.05, -0.1, -0.2], false, false);
    line(c, -0.4, -0.72, 0.5, -0.72);
    line(c, -0.4, -0.45, 0.2, -0.45);
  },
  // HeightField from Depth: a camera frustum sweeping over a mountain
  from_depth(c) {
    circ(c, -0.8, -0.6, 0.12, true);
    c.globalAlpha = 0.45;
    dash(c, true);
    line(c, -0.8, -0.6, 0.9, 0.15);
    line(c, -0.8, -0.6, 0.2, -0.75);
    dash(c, false);
    c.globalAlpha = 1;
    poly(c, [-0.95, 0.85, -0.3, 0.45, 0.2, -0.3, 0.55, 0.3, 0.95, 0.1,
             0.95, 0.85], true, true);
  },
  // Hydraulic erosion: a drop of water running down the slope, a fan deposited at the foot
  hydro(c) {
    poly(c, [-0.95, 0.85, -0.95, -0.6, -0.5, -0.4, 0.0, 0.3, 0.95, 0.5,
             0.95, 0.85], true, false);
    c.globalAlpha = 0.5;
    poly(c, [0.0, 0.3, 0.5, 0.38, 0.95, 0.5, 0.95, 0.85, 0.1, 0.85], true,
         true);
    c.globalAlpha = 1;
    poly(c, [-0.55, -0.95, -0.42, -0.72, -0.55, -0.62, -0.68, -0.72], true,
         true);
    dash(c, true);
    line(c, -0.5, -0.55, -0.05, 0.12);
    dash(c, false);
  },
  // ── completing Copernicus batch A: per pixel
  cc(c) {                                  // three slider bars
    for (let i = 0; i < 3; i++) {
      const y = -0.6 + i * 0.6, k = [0.3, -0.35, 0.55][i];
      line(c, -0.9, y, 0.9, y);
      circ(c, k, y, 0.17, true);
    }
  },
  invert(c) {                              // half-black half-white circle
    circ(c, 0, 0, 0.8, false);
    c.beginPath(); c.arc(0, 0, 0.8, -Math.PI / 2, Math.PI / 2); c.closePath();
    c.fill();
  },
  clamp(c) {                               // a diagonal line cut off by two lines above and below
    line(c, -0.95, 0.5, 0.95, 0.5); line(c, -0.95, -0.5, 0.95, -0.5);
    poly(c, [-0.95, 0.5, -0.45, 0.5, 0.45, -0.5, 0.95, -0.5], false, false);
  },
  chan_conv(c) {                           // one cell -> three cells
    rect(c, -0.95, -0.25, 0.5, 0.5, true);
    arrow(c, -0.35, 0, 0.1, 0, 0.2);
    for (let i = 0; i < 3; i++) rect(c, 0.3, -0.85 + i * 0.6, 0.55, 0.45,
                                     i === 1);
  },
  chan_split(c) {                          // one line split into three
    line(c, -0.9, 0, -0.2, 0);
    for (let i = -1; i <= 1; i++) arrow(c, -0.2, 0, 0.85, i * 0.65, 0.2);
  },
  chan_join(c) {                           // three lines merged into one
    for (let i = -1; i <= 1; i++) line(c, -0.85, i * 0.65, 0.2, 0);
    arrow(c, 0.2, 0, 0.9, 0, 0.22);
  },
  swizzle(c) {                             // two crossing arrows
    arrow(c, -0.8, -0.6, 0.8, 0.6, 0.25);
    arrow(c, -0.8, 0.6, 0.8, -0.6, 0.25);
  },
  vecmath(c) {                             // two vectors and their sum
    arrow(c, -0.8, 0.7, 0.3, 0.3, 0.2);
    arrow(c, -0.8, 0.7, -0.4, -0.5, 0.2);
    dash(c, true); arrow(c, -0.8, 0.7, 0.7, -0.9, 0.2); dash(c, false);
  },
  vecxform(c) {                            // a vector rotated (arc)
    arrow(c, -0.7, 0.7, 0.8, 0.7, 0.2);
    arrow(c, -0.7, 0.7, 0.3, -0.5, 0.2);
    c.beginPath(); c.arc(-0.7, 0.7, 0.9, -0.87, 0); c.stroke();
  },
  func(c) {                                // sine curve of f(x)
    c.beginPath();
    for (let i = 0; i <= 24; i++) {
      const x = -0.9 + i * 0.075, y = -0.55 * Math.sin(i / 24 * Math.PI * 2);
      if (i) c.lineTo(x, y); else c.moveTo(x, y);
    }
    c.stroke();
    line(c, -0.95, 0.8, 0.95, 0.8);
  },
  logic(c) {                               // > sign + 0/1 squares
    poly(c, [-0.8, -0.6, 0.0, 0.0, -0.8, 0.6], false, false);
    rect(c, 0.25, -0.5, 0.6, 0.45, true);
    rect(c, 0.25, 0.1, 0.6, 0.45, false);
  },
  mask_comb(c) {                           // union of two circles
    circ(c, -0.3, 0, 0.55, false); circ(c, 0.3, 0, 0.55, false);
    c.globalAlpha = 0.5; circ(c, 0, 0, 0.3, true); c.globalAlpha = 1;
  },
  premult(c) {                             // checkerboard × alpha gradient
    rect(c, -0.9, -0.9, 1.8, 1.8, false);
    for (let i = 0; i < 4; i++) {
      c.globalAlpha = 0.2 + i * 0.25;
      rect(c, -0.9 + i * 0.45, -0.9, 0.45, 1.8, true);
    }
    c.globalAlpha = 1;
  },
  illegal(c) {                             // warning triangle
    poly(c, [0, -0.9, 0.9, 0.75, -0.9, 0.75], true, false);
    line(c, 0, -0.35, 0, 0.2); circ(c, 0, 0.45, 0.07, true);
  },
  tonemap(c) {                             // S-shaped compression curve
    rect(c, -0.9, -0.9, 1.8, 1.8, false);
    c.beginPath(); c.moveTo(-0.9, 0.9);
    c.bezierCurveTo(-0.2, 0.9, -0.3, -0.9, 0.9, -0.85); c.stroke();
  },
  chroma(c) {                              // a human silhouette cut out of a backdrop
    c.globalAlpha = 0.45; rect(c, -0.9, -0.9, 1.8, 1.8, true);
    c.globalAlpha = 1;
    circ(c, 0, -0.35, 0.25, false);
    poly(c, [-0.5, 0.9, -0.35, 0.05, 0.35, 0.05, 0.5, 0.9], false, false);
  },
  // ── pcg100: Cross Section Surface with Houdini semantics (s3_curves): three rings of cross-sections connected by point number into a tube
  cross_section_grid(c) {
    for (const y of [-0.6, 0, 0.6]) {
      c.beginPath(); c.ellipse(0, y, 0.8 - Math.abs(y) * 0.3, 0.22, 0, 0, Math.PI * 2); c.stroke();
    }
    for (const x of [-0.6, 0, 0.6]) line(c, x * (1 - 0.3 * 0.6), -0.6 + 0.22 * 0.9, x, 0.22 * 0.9);
    for (const x of [-0.6, 0, 0.6]) line(c, x, 0.22 * 0.9, x * (1 - 0.3 * 0.6), 0.6 + 0.22 * 0.9);
  },
  // ── pcg100: a few with Houdini semantics (c2_color_key)
  despill(c) {                             // human silhouette, a dashed ring (spill) on the right edge erased
    circ(c, -0.15, -0.4, 0.25, false);
    poly(c, [-0.65, 0.9, -0.5, 0.0, 0.2, 0.0, 0.35, 0.9], false, false);
    dash(c, true);
    c.beginPath(); c.arc(0.1, 0.1, 0.8, -1.1, 0.9); c.stroke();
    dash(c, false);
  },
  equalize(c) {                            // a narrow slice of the value range stretched to full black and white
    line(c, -0.9, -0.85, -0.9, 0.85); line(c, 0.9, -0.85, 0.9, 0.85);
    rect(c, -0.2, -0.75, 0.4, 0.45, true);
    arrow(c, -0.3, 0.35, -0.8, 0.35, 0.22);
    arrow(c, 0.3, 0.35, 0.8, 0.35, 0.22);
  },
  hist_plot(c) {                           // a plotted histogram: axes + bars of different heights
    poly(c, [-0.9, -0.9, -0.9, 0.9, 0.9, 0.9], false, false);
    const hs = [0.5, 1.2, 0.8, 1.5, 0.4];
    for (let i = 0; i < 5; i++) {
      line(c, -0.6 + i * 0.33, 0.9, -0.6 + i * 0.33, 0.9 - hs[i]);
    }
  },
  cmp_mask(c) {                            // ">" sign, a filled mask block on the right
    poly(c, [-0.9, -0.6, -0.2, 0, -0.9, 0.6], false, false);
    rect(c, 0.15, -0.6, 0.75, 1.2, true);
  },
  mono_rgb(c) {                            // one cell -> a color band in three sections
    rect(c, -0.95, -0.25, 0.5, 0.5, true);
    arrow(c, -0.35, 0, 0.05, 0, 0.2);
    rect(c, 0.2, -0.3, 0.75, 0.6, false);
    line(c, 0.45, -0.3, 0.45, 0.3); line(c, 0.7, -0.3, 0.7, 0.3);
  },
  mono_hf(c) {                             // one cell -> an undulating terrain profile
    rect(c, -0.95, -0.65, 0.5, 0.5, true);
    arrow(c, -0.7, -0.05, -0.7, 0.45, 0.2);
    poly(c, [-0.3, 0.85, 0.05, 0.2, 0.35, 0.55, 0.65, -0.5, 0.95, 0.85],
         false, false);
  },
  layer_edit(c) {                          // a stack of layers, a pen on top
    for (let i = 0; i < 3; i++) poly(c, [-0.8, 0.5 - i * 0.35, 0, 0.8 - i *
      0.35, 0.8, 0.5 - i * 0.35, 0, 0.2 - i * 0.35], true, i === 0);
    line(c, 0.4, -0.95, 0.85, -0.5);
  },
  layer_merge(c) {                         // two stacks of layers merged into one
    poly(c, [-0.95, -0.3, -0.5, -0.05, -0.05, -0.3, -0.5, -0.55], true,
         false);
    poly(c, [0.05, -0.3, 0.5, -0.05, 0.95, -0.3, 0.5, -0.55], true, false);
    arrow(c, 0, -0.1, 0, 0.45, 0.18);
    poly(c, [-0.6, 0.65, 0, 0.95, 0.6, 0.65, 0, 0.35], true, true);
  },
  layer_combine(c) {                       // three images composited per pixel into one (Houdini's Layer Merge)
    for (let i = 0; i < 3; i++) rect(c, -0.9 + i * 0.25, -0.9 + i * 0.25,
                                     0.8, 0.8, false);
    arrow(c, 0.1, 0.1, 0.45, 0.45, 0.16);
    rect(c, 0.3, 0.3, 0.6, 0.6, true);
  },
  align(c) {                               // two boxes aligned to a grid
    dash(c, true); rect(c, -0.9, -0.9, 1.8, 1.8, false); dash(c, false);
    rect(c, -0.55, -0.35, 1.1, 0.7, true);
    arrow(c, -0.9, 0, -0.6, 0, 0.15); arrow(c, 0.9, 0, 0.6, 0, 0.15);
  },
  fill(c) {                                // paint bucket
    poly(c, [-0.6, -0.2, 0.1, -0.85, 0.75, -0.2, 0.05, 0.45], true, false);
    c.beginPath(); c.moveTo(0.75, -0.2);
    c.quadraticCurveTo(0.95, 0.4, 0.8, 0.7); c.stroke();
    circ(c, 0.8, 0.75, 0.1, true);
  },
  vignette(c) {                            // four corners darkened (four corner triangles, the middle left bright)
    rect(c, -0.9, -0.9, 1.8, 1.8, false);
    c.globalAlpha = 0.55;
    poly(c, [-0.9, -0.9, -0.1, -0.9, -0.9, -0.1], true, true);
    poly(c, [0.9, -0.9, 0.1, -0.9, 0.9, -0.1], true, true);
    poly(c, [-0.9, 0.9, -0.1, 0.9, -0.9, 0.1], true, true);
    poly(c, [0.9, 0.9, 0.1, 0.9, 0.9, 0.1], true, true);
    c.globalAlpha = 1;
    circ(c, 0, 0, 0.6, false);
  },
  random(c) {                              // a die
    rect(c, -0.8, -0.8, 1.6, 1.6, false);
    dots(c, [-0.4, -0.4, 0.4, -0.4, 0, 0, -0.4, 0.4, 0.4, 0.4], 0.12);
  },
  depth_conv(c) {                          // frustum + two kinds of depth
    poly(c, [-0.9, 0, 0.9, -0.8, 0.9, 0.8], true, false);
    line(c, -0.9, 0, 0.9, 0);
    dash(c, true); line(c, -0.9, 0, 0.9, -0.55); dash(c, false);
  },
  // ── completing Copernicus batch B: filters / effects / distortion
  fx_defocus(c) {                          // hexagonal aperture + bokeh highlights
    circ(c, 0, 0, 0.85, false);
    const p = [];
    for (let i = 0; i < 6; i++) {
      const a = Math.PI / 6 + i * Math.PI / 3;
      p.push(0.5 * Math.cos(a), 0.5 * Math.sin(a));
    }
    poly(c, p, true, false);
    dots(c, [0, 0, 0.62, -0.62, -0.62, 0.62], 0.1);
  },
  fx_dirblur(c) {                          // a ball + trailing lines behind it
    circ(c, 0.45, 0, 0.35, true);
    line(c, -0.9, -0.25, 0.05, -0.25);
    line(c, -0.7, 0, 0.05, 0);
    line(c, -0.9, 0.25, 0.05, 0.25);
  },
  fx_kuwahara(c) {                         // four quadrants, the one with the smallest variance filled
    rect(c, -0.85, -0.85, 1.7, 1.7, false);
    line(c, 0, -0.85, 0, 0.85); line(c, -0.85, 0, 0.85, 0);
    rect(c, 0, 0, 0.85, 0.85, true);
    dots(c, [-0.42, -0.42], 0.12);
  },
  fx_convolve(c) {                         // 3×3 kernel, center solid
    for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++)
      rect(c, -0.84 + j * 0.58, -0.84 + i * 0.58, 0.5, 0.5, i === 1 && j === 1);
  },
  fx_tv(c) {                               // noisy step -> clean step
    poly(c, [-0.9, -0.2, -0.7, -0.4, -0.5, -0.15, -0.3, -0.45, -0.1, -0.2,
             -0.1, -0.8, 0.1, -0.65, 0.3, -0.9, 0.5, -0.7, 0.7, -0.85, 0.9, -0.7],
         false, false);
    poly(c, [-0.9, 0.8, -0.1, 0.8, -0.1, 0.25, 0.9, 0.25], false, false);
  },
  fx_glow(c) {                             // bright core + halo + rays
    circ(c, 0, 0, 0.28, true);
    c.globalAlpha = 0.4; circ(c, 0, 0, 0.55, true); c.globalAlpha = 1;
    for (let i = 0; i < 4; i++) {
      const a = Math.PI / 4 + i * Math.PI / 2;
      line(c, 0.6 * Math.cos(a), 0.6 * Math.sin(a),
           0.95 * Math.cos(a), 0.95 * Math.sin(a));
    }
  },
  fx_shadow(c) {                           // square + shadow at bottom right
    c.globalAlpha = 0.45; rect(c, -0.35, -0.35, 1.2, 1.2, true);
    c.globalAlpha = 1;
    rect(c, -0.85, -0.85, 1.2, 1.2, false);
  },
  fx_feather(c) {                          // solid core + dashed soft edge
    circ(c, 0, 0, 0.4, true);
    dash(c, true); circ(c, 0, 0, 0.62, false); circ(c, 0, 0, 0.85, false);
    dash(c, false);
  },
  fx_feather_slope(c) {                    // a plateau + slope-limited ramps on both sides (max slope)
    poly(c, [-0.95, 0.7, -0.6, 0.7, -0.25, -0.55, 0.25, -0.55, 0.6, 0.7, 0.95, 0.7],
         false, false);
    dash(c, true); line(c, -0.25, -0.55, -0.25, 0.7); line(c, 0.25, -0.55, 0.25, 0.7);
    dash(c, false);
  },
  fx_pixelate(c) {                         // mosaic steps
    for (let i = 0; i < 4; i++)
      for (let j = 0; j <= i; j++)
        rect(c, -0.9 + j * 0.45, 0.45 - i * 0.45, 0.42, 0.42, (i + j) % 2 === 0);
  },
  fx_chroma_ab(c) {                        // three offset circles (R G B)
    circ(c, -0.25, 0, 0.55, false);
    circ(c, 0, 0, 0.55, false);
    circ(c, 0.25, 0, 0.55, false);
  },
  fx_heat(c) {                             // three waves floating upward
    for (let k = -1; k <= 1; k++) {
      const p = [];
      for (let t = 0; t <= 12; t++) {
        const y = 0.9 - t * 0.15;
        p.push(k * 0.5 + 0.15 * Math.sin(t * 1.1 + k), y);
      }
      poly(c, p, false, false);
    }
  },
  fx_swirl(c) {                            // Archimedean spiral
    const p = [];
    for (let t = 0; t <= 60; t++) {
      const a = t * 0.3, r = 0.9 * t / 60;
      p.push(r * Math.cos(a), r * Math.sin(a));
    }
    poly(c, p, false, false);
  },
  fx_lens(c) {                             // barrel-distorted grid (polyline sampling: the canvas stub in tests doesn't record quadraticCurveTo)
    for (let k = -1; k <= 1; k++) {
      const h = [], v = [];
      for (let t = 0; t <= 10; t++) {
        const x = -0.8 + t * 0.16, bow = 1 + 0.25 * (1 - x * x / 0.64);
        h.push(x, k * 0.8 / bow);
        v.push(k * 0.8 / bow, x);
      }
      poly(c, h, false, false);
      poly(c, v, false, false);
    }
  },
  fx_deriv(c) {                            // curve + tangent arrow at a point
    poly(c, [-0.9, 0.7, -0.5, 0.55, -0.1, 0.2, 0.3, -0.3, 0.6, -0.75],
         false, false);
    dots(c, [-0.1, 0.2], 0.1);
    arrow(c, -0.1, 0.2, 0.6, 0.35 - 0.6, 0.25);
  },
  fx_corner(c) {                           // two L corners + corner point
    poly(c, [-0.8, 0.2, -0.8, 0.8, -0.2, 0.8], false, false);
    poly(c, [0.2, -0.8, 0.8, -0.8, 0.8, -0.2], false, false);
    dots(c, [-0.8, 0.8, 0.8, -0.8], 0.14);
  },
  fx_smoothfill(c) {                       // frame + a hole that's been filled in (semi-transparent)
    rect(c, -0.85, -0.85, 1.7, 1.7, false);
    c.globalAlpha = 0.4; circ(c, 0.05, 0.05, 0.45, true); c.globalAlpha = 1;
    dash(c, true); circ(c, 0.05, 0.05, 0.45, false); dash(c, false);
  },
  fx_extrap(c) {                           // solid island + a ring of bleed outward + dashed outer frame
    rect(c, -0.4, -0.4, 0.8, 0.8, true);
    rect(c, -0.62, -0.62, 1.24, 1.24, false);
    dash(c, true); rect(c, -0.9, -0.9, 1.8, 1.8, false); dash(c, false);
  },
  fx_edgeprobe(c) {                        // boundary between two regions + a probe radius circle
    rect(c, -0.9, -0.9, 0.9, 1.8, true);
    rect(c, 0, -0.9, 0.9, 1.8, false);
    dash(c, true); circ(c, 0.15, 0, 0.45, false); dash(c, false);
    dots(c, [0.15, 0], 0.08);
  },
  fx_surfdither(c) {                       // halftone dots in two sizes: big dots on even cells, small ones shrunk away in between
    for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) {
      const big = i % 2 === 0 && j % 2 === 0;
      circ(c, -0.7 + i * 0.7, -0.7 + j * 0.7, big ? 0.26 : 0.1, true);
    }
  },
  fx_turingpat(c) {                        // three curved stripes (maze-like)
    for (let k = 0; k < 3; k++) {
      c.beginPath();
      for (let i = 0; i <= 16; i++) {
        const x = -0.85 + i * 0.106, y = -0.55 + k * 0.55 + 0.18 * Math.sin(i * 0.8 + k);
        if (i === 0) c.moveTo(x, y); else c.lineTo(x, y);
      }
      c.stroke();
    }
  },
  fx_heatlayer(c) {                        // a noise layer (box) + two wavy arrows rising from it
    rect(c, -0.9, 0.45, 1.8, 0.45, false);
    for (let k = 0; k < 2; k++) {
      c.beginPath();
      for (let i = 0; i <= 10; i++) {
        const y = 0.35 - i * 0.11, x = -0.35 + k * 0.7 + 0.12 * Math.sin(i * 1.1);
        if (i === 0) c.moveTo(x, y); else c.lineTo(x, y);
      }
      c.stroke();
    }
  },
  fx_flood(c) {                            // a connected patch in the grid filled + the seed
    for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) {
      const on = (i + j < 4) && !(i === 0 && j === 3);
      rect(c, -0.88 + j * 0.44, -0.88 + i * 0.44, 0.4, 0.4, on);
    }
  },
  fx_contour(c) {                          // a set of nested contour lines
    c.beginPath(); c.ellipse(0, 0, 0.9, 0.65, 0.3, 0, Math.PI * 2); c.stroke();
    c.beginPath(); c.ellipse(0.1, 0, 0.55, 0.38, 0.3, 0, Math.PI * 2); c.stroke();
    c.beginPath(); c.ellipse(0.15, 0, 0.2, 0.13, 0.3, 0, Math.PI * 2); c.stroke();
  },
  fx_dither(c) {                           // dot matrix, dense on the left, sparse on the right
    for (let i = 0; i < 5; i++) for (let j = 0; j < 5; j++)
      if ((i * 3 + j * 2) % 5 < 5 - j) circ(c, -0.8 + j * 0.4, -0.8 + i * 0.4, 0.1, true);
  },
  fx_mirror(c) {                           // mirror plane + solid triangle + mirrored hollow triangle
    dash(c, true); line(c, 0, -0.95, 0, 0.95); dash(c, false);
    poly(c, [-0.15, -0.6, -0.85, 0.6, -0.15, 0.6], true, true);
    poly(c, [0.15, -0.6, 0.85, 0.6, 0.15, 0.6], true, false);
  },
  fx_cornerpin(c) {                        // perspective quad + four pins
    poly(c, [-0.55, -0.7, 0.6, -0.85, 0.9, 0.8, -0.85, 0.6], true, false);
    dots(c, [-0.55, -0.7, 0.6, -0.85, 0.9, 0.8, -0.85, 0.6], 0.12);
  },
  fx_lattice(c) {                          // a lattice bent by a control point being dragged
    for (let k = -1; k <= 1; k++) {
      const h = [], v = [];
      for (let t = 0; t <= 10; t++) {
        const x = -0.85 + t * 0.17, w = Math.exp(-x * x * 3);
        h.push(x, k * 0.55 + 0.3 * w);
        v.push(k * 0.55 + 0.25 * w, x);
      }
      poly(c, h, false, false);
      poly(c, v, false, false);
    }
    dots(c, [0.25, 0.3], 0.12);
  },
  fx_inflate(c) {                          // flat bottom + a puffed-up pillow profile
    line(c, -0.9, 0.6, 0.9, 0.6);
    const p = [];
    for (let t = 0; t <= 16; t++) {
      const x = -0.7 + t * 0.0875, d = Math.min(x + 0.7, 0.7 - x);
      p.push(x, 0.6 - 0.9 * Math.sqrt(Math.max(0, 2 * 0.7 * d - d * d)) / 0.7);
    }
    poly(c, p, false, false);
  },
  fx_copyxf(c) {                           // a row of offset, fading squares
    for (let i = 2; i >= 0; i--) {
      c.globalAlpha = 1 - i * 0.3;
      rect(c, -0.85 + i * 0.4, 0.05 - i * 0.4, 0.8, 0.8, i === 0);
    }
    c.globalAlpha = 1;
  },
  // ── completing Copernicus batch C: patterns / noise / text / scattering shapes / stereograms
  pat_pattern(c) {                         // brick wall: two and a half rows, staggered
    rect(c, -0.9, -0.9, 1.8, 1.8, false);
    line(c, -0.9, -0.3, 0.9, -0.3); line(c, -0.9, 0.3, 0.9, 0.3);
    line(c, -0.3, -0.9, -0.3, -0.3); line(c, 0.4, -0.9, 0.4, -0.3);
    line(c, 0.05, -0.3, 0.05, 0.3); line(c, -0.3, 0.3, -0.3, 0.9);
    line(c, 0.4, 0.3, 0.4, 0.9);
  },
  pat_noisex(c) {                          // a pile of bubbles of different sizes
    circ(c, -0.4, -0.35, 0.42, false);
    circ(c, 0.45, -0.45, 0.3, true);
    circ(c, 0.25, 0.4, 0.45, false);
    circ(c, -0.55, 0.55, 0.2, true);
  },
  pat_text(c) {                            // capital T + baseline
    line(c, -0.7, -0.8, 0.7, -0.8);
    line(c, 0, -0.8, 0, 0.6);
    line(c, -0.9, 0.85, 0.9, 0.85);
  },
  pat_scatter(c) {                         // scattered triangles and squares
    poly(c, [-0.6, -0.9, -0.2, -0.2, -1.0 + 0.0, -0.2], true, true);
    rect(c, 0.2, -0.8, 0.5, 0.5, false);
    poly(c, [0.3, 0.15, 0.85, 0.5, 0.3, 0.85], true, true);
    circ(c, -0.45, 0.5, 0.28, false);
  },
  pat_stereo(c) {                          // two eyes + lines of sight converging on a point
    circ(c, -0.5, 0.7, 0.2, false); circ(c, 0.5, 0.7, 0.2, false);
    line(c, -0.5, 0.5, 0, -0.6); line(c, 0.5, 0.5, 0, -0.6);
    dash(c, true); line(c, -0.9, -0.85, 0.9, -0.85); dash(c, false);
    dots(c, [0, -0.6], 0.1);
  },
  // ── completing Copernicus batch D: analysis / solvers / simulation
  sv_fft(c) {                              // spectrum: bright center + symmetric spectral peaks
    rect(c, -0.9, -0.9, 1.8, 1.8, false);
    dots(c, [0, 0], 0.16);
    dots(c, [-0.45, -0.25, 0.45, 0.25, -0.2, 0.55, 0.2, -0.55], 0.08);
  },
  sv_prefix(c) {                           // increasing step bars
    for (let i = 0; i < 4; i++) rect(c, -0.9 + i * 0.45, 0.9 - (i + 1) * 0.42,
                                     0.36, (i + 1) * 0.42, i === 3);
  },
  sv_poisson(c) {                          // a membrane pinned by a frame (saddle surface profile lines)
    rect(c, -0.9, -0.9, 1.8, 1.8, false);
    const p = [];
    for (let t = 0; t <= 16; t++) {
      const x = -0.9 + t * 0.1125;
      p.push(x, 0.5 - 0.9 * (1 - (x / 0.9) * (x / 0.9)));
    }
    poly(c, p, false, false);
    dots(c, [0, -0.4], 0.1);
  },
  sv_eikonal(c) {                          // seed + wavefront around an obstacle
    dots(c, [-0.6, 0.6], 0.14);
    rect(c, -0.15, -0.2, 0.25, 1.1, true);
    c.beginPath(); c.arc(-0.6, 0.6, 0.55, -Math.PI / 2, 0); c.stroke();
    c.beginPath(); c.arc(-0.6, 0.6, 1.05, -Math.PI / 2, -0.35); c.stroke();
  },
  sv_segment(c) {                          // three areas of different gray + numbered points
    c.globalAlpha = 0.35; poly(c, [-0.9, -0.9, 0.2, -0.9, -0.2, 0.9, -0.9, 0.9],
                                true, true);
    c.globalAlpha = 0.7; poly(c, [0.2, -0.9, 0.9, -0.9, 0.9, 0.1, 0.0, 0.0],
                              true, true);
    c.globalAlpha = 1;
    poly(c, [0.0, 0.0, 0.9, 0.1, 0.9, 0.9, -0.2, 0.9], true, false);
  },
  sv_bbox(c) {                             // blob + dashed bounding box
    circ(c, -0.2, 0.1, 0.35, true); circ(c, 0.3, -0.25, 0.25, true);
    dash(c, true); rect(c, -0.65, -0.6, 1.25, 1.15, false); dash(c, false);
  },
  sv_select(c) {                           // two blocks A / B + selection arrow
    rect(c, -0.9, -0.8, 0.7, 0.7, true);
    rect(c, 0.2, -0.8, 0.7, 0.7, false);
    arrow(c, -0.55, 0.0, 0, 0.75, 0.22);
    arrow(c, 0.55, 0.0, 0.05, 0.75, 0.22);
  },
  sv_rd(c) {                               // reaction-diffusion spots and worms
    circ(c, -0.5, -0.5, 0.2, true); circ(c, 0.5, 0.45, 0.22, true);
    c.beginPath(); c.moveTo(-0.8, 0.5);
    for (let t = 0; t <= 10; t++) c.lineTo(-0.8 + t * 0.1, 0.5 + 0.2 * Math.sin(t));
    c.stroke();
    c.beginPath(); c.moveTo(0.1, -0.8);
    for (let t = 0; t <= 8; t++) c.lineTo(0.1 + 0.18 * Math.sin(t * 0.9), -0.8 + t * 0.12);
    c.stroke();
  },
  sv_ripple(c) {                           // concentric ripples
    dots(c, [0, 0], 0.1);
    circ(c, 0, 0, 0.35, false); circ(c, 0, 0, 0.62, false);
    dash(c, true); circ(c, 0, 0, 0.88, false); dash(c, false);
  },
  sv_flow(c) {                             // vortex streamlines + arrows
    const p = [];
    for (let t = 0; t <= 40; t++) {
      const a = t * 0.22, r = 0.15 + t * 0.018;
      p.push(r * Math.cos(a), r * Math.sin(a));
    }
    poly(c, p, false, false);
    arrow(c, 0.3, 0.7, 0.85, 0.2, 0.2);
  },
  sv_ocean(c) {                            // two rows of peaked waves (Gerstner style)
    for (let k = 0; k < 2; k++) {
      const p = [];
      for (let t = 0; t <= 16; t++) {
        const x = -0.95 + t * 0.119, ph = t / 16 * Math.PI * 4;
        p.push(x - 0.08 * Math.sin(ph), -0.3 + k * 0.6 - 0.22 * Math.cos(ph));
      }
      poly(c, p, false, false);
    }
  },
  // ── completing Copernicus batch E: UV / tiling / SDF / ID
  ux_uvmap(c) {                            // uv axes + gradient grid
    arrow(c, -0.8, 0.8, 0.85, 0.8, 0.22);
    arrow(c, -0.8, 0.8, -0.8, -0.85, 0.22);
    for (let i = 0; i < 3; i++) {
      c.globalAlpha = 0.3 + i * 0.25;
      rect(c, -0.55 + i * 0.45, 0.1 - i * 0.3, 0.4, 0.4, true);
    }
    c.globalAlpha = 1;
  },
  ux_uvshape(c) {                          // polar grid inside a disk: concentric circles + radial lines
    circ(c, 0, 0, 0.9, false);
    circ(c, 0, 0, 0.55, false);
    circ(c, 0, 0, 0.2, false);
    for (let k = 0; k < 8; k++) {
      const a = k * Math.PI / 4;
      line(c, 0.2 * Math.cos(a), 0.2 * Math.sin(a), 0.9 * Math.cos(a), 0.9 * Math.sin(a));
    }
  },
  ux_uvsample(c) {                         // a sample point on a grid + sampling arrow
    rect(c, -0.9, -0.9, 1.1, 1.1, false);
    line(c, -0.35, -0.9, -0.35, 0.2); line(c, -0.9, -0.35, 0.2, -0.35);
    dots(c, [-0.55, -0.6], 0.12);
    arrow(c, -0.45, -0.45, 0.6, 0.6, 0.22);
    circ(c, 0.65, 0.65, 0.22, false);
  },
  ux_uvxform(c) {                          // rotated uv square
    rect(c, -0.7, -0.7, 1.4, 1.4, false);
    poly(c, [0, -0.95, 0.95, 0, 0, 0.95, -0.95, 0], true, false);
    dots(c, [0, 0], 0.1);
  },
  ux_uvinv(c) {                            // two-way arrow: a mapping and its inverse
    arrow(c, -0.85, -0.3, 0.85, -0.3, 0.22);
    arrow(c, 0.85, 0.3, -0.85, 0.3, 0.22);
    dots(c, [-0.85, -0.3, 0.85, 0.3], 0.1);
  },
  ux_polar(c) {                            // concentric circles + radial lines
    circ(c, 0, 0, 0.85, false); circ(c, 0, 0, 0.45, false);
    for (let i = 0; i < 6; i++) {
      const a = i * Math.PI / 3;
      line(c, 0.15 * Math.cos(a), 0.15 * Math.sin(a), 0.85 * Math.cos(a),
           0.85 * Math.sin(a));
    }
  },
  ux_polarco(c) {                          // a point: line to the origin + angle arc (coordinate conversion)
    line(c, -0.8, 0.7, 0.85, 0.7); line(c, -0.8, 0.7, -0.8, -0.9);
    line(c, -0.8, 0.7, 0.5, -0.5);
    dots(c, [0.5, -0.5], 0.12);
    c.beginPath(); c.arc(-0.8, 0.7, 0.5, -Math.PI / 4, 0); c.stroke();
  },
  ux_spacexf(c) {                          // two squares of different sizes + a conversion arrow
    rect(c, -0.9, -0.1, 0.8, 0.8, false);
    rect(c, 0.2, -0.8, 0.7, 1.5, false);
    arrow(c, -0.5, 0.3, 0.55, -0.05, 0.22);
  },
  ux_posmap(c) {                           // cube wireframe (canonical cube with edge length 2)
    rect(c, -0.85, -0.45, 1.2, 1.2, false);
    rect(c, -0.45, -0.85, 1.2, 1.2, false);
    line(c, -0.85, -0.45, -0.45, -0.85); line(c, 0.35, -0.45, 0.75, -0.85);
    line(c, -0.85, 0.75, -0.45, 0.35); line(c, 0.35, 0.75, 0.75, 0.35);
  },
  ux_sphsample(c) {                        // sphere + latitude/longitude lines
    circ(c, 0, 0, 0.85, false);
    c.beginPath(); c.ellipse(0, 0, 0.85, 0.3, 0, 0, Math.PI * 2); c.stroke();
    c.beginPath(); c.ellipse(0, 0, 0.35, 0.85, 0, 0, Math.PI * 2); c.stroke();
  },
  ux_xform3d(c) {                          // a slanted plane in perspective + the original frame
    rect(c, -0.85, -0.85, 1.1, 1.1, false);
    poly(c, [-0.2, 0.85, 0.85, 0.55, 0.85, -0.45, -0.2, -0.05], true, false);
  },
  ux_alignwin(c) {                         // lower-left corner of the small box aligned to the lower-left of the large box
    rect(c, -0.9, -0.9, 1.8, 1.8, false);
    rect(c, -0.9, 0.2, 0.8, 0.7, true);
    arrow(c, 0.5, -0.4, -0.05, 0.15, 0.22);
  },
  ux_alignpx(c) {                          // pixel grid + a block aligned to whole cells
    for (let i = -1; i <= 1; i += 0.5) { line(c, i, -0.9, i, 0.9); line(c, -0.9, i, 0.9, i); }
    rect(c, -0.5, 0, 1.0, 0.5, true);
  },
  ux_bend(c) {                             // a sheet of paper bent over: two curved edges
    poly(c, [-0.8, 0.85, -0.8, -0.2], false, false);
    c.beginPath(); c.moveTo(-0.8, -0.2); c.bezierCurveTo(-0.8, -0.6, -0.4, -0.85, 0.0, -0.85); c.stroke();
    poly(c, [0.0, 0.85, 0.0, 0.2], false, false);
    c.beginPath(); c.moveTo(0.0, 0.2); c.bezierCurveTo(0.0, 0.05, 0.4, -0.05, 0.85, -0.05); c.stroke();
    line(c, -0.8, 0.85, 0.0, 0.85); line(c, 0.0, -0.85, 0.85, -0.05);
  },
  ux_hex(c) {                              // three hexagons tiled together
    const hx = (x, y, r, f) => {
      const p = [];
      for (let i = 0; i < 6; i++) p.push(x + r * Math.cos(i * Math.PI / 3),
                                          y + r * Math.sin(i * Math.PI / 3));
      poly(c, p, true, f);
    };
    hx(-0.42, -0.3, 0.42, false); hx(0.42, -0.3, 0.42, true);
    hx(0, 0.45, 0.42, false);
  },
  ux_triplanar(c) {                        // three faces of a cube
    poly(c, [0, -0.9, 0.8, -0.45, 0, 0, -0.8, -0.45], true, false);
    c.globalAlpha = 0.5;
    poly(c, [-0.8, -0.45, 0, 0, 0, 0.9, -0.8, 0.45], true, true);
    c.globalAlpha = 1;
    poly(c, [0, 0, 0.8, -0.45, 0.8, 0.45, 0, 0.9], true, false);
  },
  ux_retile(c) {                           // four shuffled cells + swap arrow
    rect(c, -0.9, -0.9, 0.8, 0.8, true); rect(c, 0.1, -0.9, 0.8, 0.8, false);
    rect(c, -0.9, 0.1, 0.8, 0.8, false); rect(c, 0.1, 0.1, 0.8, 0.8, true);
    arrow(c, -0.3, -0.3, 0.3, 0.3, 0.18);
  },
  ux_sdfops(c) {                           // smooth-union outline of two circles
    circ(c, -0.35, 0, 0.45, false); circ(c, 0.4, 0, 0.35, false);
    dash(c, true);
    c.beginPath(); c.moveTo(-0.35, -0.62); c.lineTo(0.4, -0.52); c.stroke();
    c.beginPath(); c.moveTo(-0.35, 0.62); c.lineTo(0.4, 0.52); c.stroke();
    dash(c, false);
  },
  ux_idconv(c) {                           // numbered blocks -> one block selected
    rect(c, -0.9, -0.9, 0.8, 1.8, false);
    line(c, -0.9, 0, -0.1, 0);
    rect(c, 0.2, -0.9, 0.7, 0.8, true);
    rect(c, 0.2, 0.1, 0.7, 0.8, false);
    arrow(c, -0.05, -0.45, 0.15, -0.45, 0.15);
  },
  // ── completing Copernicus batch F: geometry <-> image / heightfield / visualization / sequences
  gi_l2p(c) {                              // pixel grid -> points
    rect(c, -0.9, -0.9, 0.9, 0.9, false);
    line(c, -0.45, -0.9, -0.45, 0); line(c, -0.9, -0.45, 0, -0.45);
    arrow(c, -0.05, 0.05, 0.35, 0.4, 0.18);
    dots(c, [0.5, 0.5, 0.8, 0.5, 0.5, 0.8, 0.8, 0.8], 0.09);
  },
  gl_ptgen(c) {                            // a column of points + plus sign (adding points to a point cloud)
    dots(c, [-0.7, -0.6, -0.2, -0.6, -0.7, -0.1, -0.2, -0.1], 0.1);
    line(c, 0.5, 0.1, 0.5, 0.8); line(c, 0.15, 0.45, 0.85, 0.45);
  },
  gl_lfa(c) {                              // a column of numbers -> a row of pixels
    for (let i = 0; i < 4; i++) rect(c, -0.9, -0.9 + i * 0.45, 0.35, 0.35, i % 2 === 0);
    arrow(c, -0.4, 0, 0.1, 0, 0.15);
    rect(c, 0.25, -0.9, 0.65, 1.8, false); line(c, 0.25, 0, 0.9, 0); line(c, 0.575, -0.9, 0.575, 0.9);
  },
  gl_g2l(c) {                              // a slice cut out of a cube
    rect(c, -0.8, -0.8, 1.2, 1.2, false);
    poly(c, [-0.8, 0.4, -0.4, 0.8, 0.8, 0.8, 0.4, 0.4], false, false);
    line(c, 0.8, 0.8, 0.8, -0.4); line(c, 0.8, -0.4, 0.4, -0.8);
    poly(c, [-0.8, -0.1, -0.4, 0.3, 0.8, 0.3, 0.4, -0.1], true, true);
  },
  gl_seqclip(c) {                          // two film strips joined into one
    rect(c, -0.9, 0.2, 0.8, 0.5, false); rect(c, 0.1, 0.2, 0.8, 0.5, true);
    rect(c, -0.9, -0.75, 1.8, 0.5, false); line(c, -0.1, -0.75, -0.1, -0.25);
    arrow(c, 0, 0.1, 0, -0.15, 0.12);
  },
  gl_tpack(c) {                            // three frames stacked into a pile
    rect(c, -0.9, 0.3, 0.5, 0.5, false); rect(c, -0.25, 0.3, 0.5, 0.5, false);
    rect(c, 0.4, 0.3, 0.5, 0.5, false);
    arrow(c, 0, 0.2, 0, -0.2, 0.12);
    rect(c, -0.45, -0.9, 0.7, 0.5, false); rect(c, -0.3, -0.8, 0.7, 0.5, false);
  },
  gl_integ(c) {                            // a few parallel lines of sight passing through a cloud
    circ(c, 0.1, 0, 0.55, false);
    for (const y of [-0.4, 0, 0.4]) arrow(c, -0.9, y, 0.9, y, 0.12);
  },
  gl_cfgstamp(c) {                         // a few small squares of different sizes and angles (sprite attributes on points)
    rect(c, -0.85, -0.85, 0.5, 0.5, false);
    poly(c, [0.3, -0.9, 0.75, -0.55, 0.4, -0.1, -0.05, -0.45], true, false);
    rect(c, -0.6, 0.25, 0.3, 0.3, true);
    poly(c, [0.2, 0.2, 0.9, 0.35, 0.75, 0.9, 0.05, 0.75], true, false);
  },
  gi_blobs(c) {                            // blobs + centroid points
    c.globalAlpha = 0.45;
    circ(c, -0.4, -0.3, 0.45, true); circ(c, 0.45, 0.4, 0.35, true);
    c.globalAlpha = 1;
    dots(c, [-0.4, -0.3, 0.45, 0.4], 0.12);
  },
  gi_curves(c) {                           // a curve drawn with a thick line
    const p = [];
    for (let t = 0; t <= 16; t++) p.push(-0.9 + t * 0.1125, 0.4 * Math.sin(t * 0.45) - 0.1);
    c.save(); c.lineWidth *= 2.4; poly(c, p, false, false); c.restore();
    dots(c, [-0.9, -0.1], 0.1);
  },
  gi_splats(c) {                           // a few flattened Gaussian ellipses
    c.globalAlpha = 0.5;
    c.beginPath(); c.ellipse(-0.35, -0.2, 0.5, 0.2, 0.5, 0, Math.PI * 2); c.fill();
    c.globalAlpha = 0.8;
    c.beginPath(); c.ellipse(0.35, 0.3, 0.35, 0.18, -0.7, 0, Math.PI * 2); c.fill();
    c.globalAlpha = 1;
    c.beginPath(); c.ellipse(0.1, -0.55, 0.25, 0.12, 0.2, 0, Math.PI * 2); c.stroke();
  },
  gi_bake(c) {                             // mesh -> texture square
    poly(c, [-0.9, 0.1, -0.5, -0.6, -0.1, 0.1, -0.5, 0.8], true, false);
    line(c, -0.9, 0.1, -0.1, 0.1);
    arrow(c, -0.05, 0.1, 0.3, 0.1, 0.16);
    rect(c, 0.35, -0.3, 0.55, 0.8, false);
    rect(c, 0.45, -0.2, 0.2, 0.25, true);
  },
  hv_light(c) {                            // light-bulb rays hitting a slope
    circ(c, -0.5, -0.5, 0.2, true);
    arrow(c, -0.3, -0.3, 0.15, 0.2, 0.18);
    arrow(c, -0.5, -0.25, -0.35, 0.35, 0.18);
    line(c, -0.9, 0.8, 0.9, 0.3);
  },
  hv_clip(c) {                             // a flattened mountain top
    poly(c, [-0.9, 0.8, -0.35, -0.3, 0.3, -0.3, 0.9, 0.8], false, false);
    dash(c, true);
    poly(c, [-0.35, -0.3, 0, -0.85, 0.3, -0.3], false, false);
    dash(c, false);
    line(c, -0.9, -0.3, 0.9, -0.3);
  },
  hv_project(c) {                          // an object projected down onto the ground
    rect(c, -0.3, -0.9, 0.6, 0.45, false);
    arrow(c, -0.15, -0.4, -0.15, 0.35, 0.16);
    arrow(c, 0.15, -0.4, 0.15, 0.35, 0.16);
    poly(c, [-0.9, 0.8, -0.3, 0.5, 0.3, 0.5, 0.9, 0.8], false, false);
  },
  hv_strata(c) {                           // tilted rock strata lines
    for (let k = 0; k < 4; k++) line(c, -0.9, 0.9 - k * 0.45, 0.9, 0.5 - k * 0.45);
    poly(c, [-0.9, -0.9, -0.2, -0.9, 0.2, 0.9, -0.9, 0.9], true, false);
  },
  hv_vis(c) {                              // color ramp bar + streamlines
    for (let i = 0; i < 5; i++) {
      c.globalAlpha = 0.2 + i * 0.2;
      rect(c, -0.9 + i * 0.36, 0.45, 0.36, 0.4, true);
    }
    c.globalAlpha = 1;
    arrow(c, -0.8, -0.1, 0.1, -0.5, 0.18);
    arrow(c, -0.2, 0.2, 0.8, -0.2, 0.18);
  },
  hv_sheet(c) {                            // 3×2 thumbnail grid
    for (let r = 0; r < 2; r++) for (let q = 0; q < 3; q++)
      rect(c, -0.9 + q * 0.62, -0.7 + r * 0.72, 0.5, 0.6, r === 0 && q === 0);
  },
  hv_wipe(c) {                             // left half solid, right half empty, a diagonal line in between
    poly(c, [-0.9, -0.9, 0.2, -0.9, -0.2, 0.9, -0.9, 0.9], true, true);
    rect(c, -0.9, -0.9, 1.8, 1.8, false);
    arrow(c, 0.15, 0, 0.75, 0, 0.18);
  },
  hv_seqops(c) {                           // film frames + loop arrow
    for (let i = 0; i < 3; i++) rect(c, -0.9 + i * 0.62, -0.3, 0.5, 0.6, i === 1);
    c.beginPath(); c.arc(0, 0.2, 0.75, 0.3, Math.PI - 0.3); c.stroke();
    arrow(c, -0.62, 0.62, -0.72, 0.42, 0.15);
  },
  heightfield(c) {
    rect(c, -0.9, -0.9, 1.1, 0.8, false);
    for (let i = 0; i < 3; i++) {
      c.globalAlpha = 1 - i * 0.28;
      rect(c, -0.9 + i * 0.37, -0.9, 0.37, 0.8, true);
    }
    c.globalAlpha = 1;
    poly(c, [-0.9, 0.85, -0.3, 0.25, 0.15, 0.6, 0.9, -0.1], false, false);
  },

  // ── pcg121 ──
  // A point and a round reference shape, the shortest distance dashed between them
  dist_from_geo(c) {
    c.beginPath(); c.arc(0.35, -0.3, 0.5, 0, Math.PI * 2); c.stroke();
    dash(c, true); line(c, -0.7, 0.6, 0.0, 0.05); dash(c, false);
    dots(c, [-0.7, 0.6], 0.14);
  },
  // A source point on a wavy surface, distance rings spreading along it
  dist_along_geo(c) {
    poly(c, [-0.95, 0.55, -0.5, 0.35, 0, 0.5, 0.5, 0.3, 0.95, 0.45], false, false);
    dots(c, [0, 0.5], 0.13);
    for (const r of [0.35, 0.65, 0.95]) { c.beginPath(); c.arc(0, 0.5, r, Math.PI * 1.1, Math.PI * 1.9); c.stroke(); }
  },
  // A ladder (the input) bent along a curve
  path_deform(c) {
    poly(c, [-0.9, 0.7, -0.5, -0.1, 0.1, -0.55, 0.9, -0.65], false, false);
    poly(c, [-0.6, 0.85, -0.25, 0.15, 0.25, -0.25, 0.9, -0.35], false, false);
    line(c, -0.75, 0.78, -0.55, 0.62); line(c, -0.38, 0.03, -0.2, 0.2);
    line(c, 0.12, -0.45, 0.22, -0.28); line(c, 0.55, -0.55, 0.6, -0.33);
  },
  // A Y branch of thick tubes with a round joint
  polywire(c) {
    const w = c.lineWidth;
    c.lineWidth = w * 3.2; c.lineCap = "round";
    line(c, 0, 0.15, 0, -0.85); line(c, 0, 0.15, -0.7, 0.8); line(c, 0, 0.15, 0.7, 0.8);
    c.lineWidth = w;
    c.beginPath(); c.arc(0, 0.15, 0.28, 0, Math.PI * 2); c.stroke();
  },
  // A wavy sheet given thickness: two skins and closed ends
  thicken(c) {
    poly(c, [-0.9, -0.1, -0.45, -0.35, 0, -0.1, 0.45, -0.35, 0.9, -0.1,
             0.9, 0.3, 0.45, 0.05, 0, 0.3, -0.45, 0.05, -0.9, 0.3], true, false);
    dash(c, true); poly(c, [-0.9, 0.1, -0.45, -0.15, 0, 0.1, 0.45, -0.15, 0.9, 0.1], false, false); dash(c, false);
  },
  // A corner (dashed) replaced by a round arc
  curve_fillet(c) {
    dash(c, true); poly(c, [-0.5, -0.1, -0.5, -0.7, 0.1, -0.7], false, false); dash(c, false);
    // the curve: up the left leg, around the arc (centre 0.1, -0.1) and out to the right
    c.beginPath(); c.moveTo(-0.5, 0.85); c.lineTo(-0.5, -0.1); c.arc(0.1, -0.1, 0.6, Math.PI, Math.PI * 1.5);
    c.lineTo(0.9, -0.7); c.stroke();
    dots(c, [-0.5, -0.1, 0.1, -0.7], 0.11);
  },
  // Three small boxes folded into one point
  pack(c) {
    rect(c, -0.95, -0.75, 0.45, 0.45, false); rect(c, -0.95, 0.3, 0.45, 0.45, false); rect(c, -0.3, -0.25, 0.45, 0.45, false);
    arrow(c, 0.25, 0, 0.7, 0, 0.18);
    dots(c, [0.85, 0], 0.15);
  },
  // One point expanding into boxes
  unpack(c) {
    dots(c, [-0.8, 0], 0.15);
    arrow(c, -0.6, 0, -0.15, 0, 0.18);
    rect(c, 0.05, -0.85, 0.45, 0.45, false); rect(c, 0.5, -0.2, 0.45, 0.45, false); rect(c, 0.05, 0.45, 0.45, 0.45, false);
  },
  // pcg122: loose fragments, each tagged with its own number dot
  assemble(c) {
    poly(c, [-0.9, -0.8, -0.2, -0.85, -0.35, -0.15, -0.85, -0.25], true, false);
    poly(c, [0.05, -0.8, 0.85, -0.6, 0.6, 0.0, 0.0, -0.2], true, false);
    poly(c, [-0.75, 0.15, 0.25, 0.25, 0.1, 0.85, -0.85, 0.75], true, false);
    dots(c, [-0.55, -0.5, 0.45, -0.4, -0.3, 0.5], 0.1);
  },
};

// ─────────────────────────────────────────────── category colors
export const CATEGORY_COLOR = {
  "PCG/generate": "#7ec87e",
  "PCG/modify": "#8fb8e0",
  "PCG/attribute": "#e0b464",
  "PCG/group": "#6fb7c4",
  "PCG/uv": "#5fc9b0",
  "PCG/cop": "#e0975f",
  "PCG/image": "#e0975f",
  "PCG/render": "#e07a7a",
  "PCG/scatter": "#b79ae0",
  "PCG/loop": "#e08fc0",
  "PCG/param": "#9aa7b5",
  "PCG/convert": "#68c0d8",
  "PCG/deform": "#c49ae0",
  "PCG/topology": "#8fb8e0",
  "PCG/volume": "#7fc1d6",
  "PCG/output": "#cfd6de",
};
const DEFAULT_COLOR = "#9aa7b5";

// ─────────────────────────────────────────────── node -> icon
// Names are without the PCG_ prefix. Nodes not in the table fall back by category (see glyphFor).
export const NODE_GLYPH = {
  // generators
  Box: "box", Sphere: "sphere", Tube: "tube", Grid: "grid", Circle: "circle",
  Line: "line", Curve: "curve_draw", Sweep: "sweep", Skin: "skin", Add: "add",
  // general modifiers
  Transform: "transform", Merge: "merge", Split: "split", Switch: "swtch",
  Delete: "del", Blast: "blast", Boolean: "bool", Clip: "clip",
  Carve: "carve", Sort: "sort", Reverse: "reverse", Smooth: "smooth",
  Subdivide: "subdiv", Divide: "divide", Refine: "refine",
  Resample: "resample", Fuse: "fuse", Dissolve: "dissolve",
  PolyBevel: "bevel", PolyExtrude: "extrude", Peak: "peak", Mirror: "mirror",
  ConvexHull: "hull", Bound: "bound", ConvexDecompose: "decomp",
  VoronoiFracture: "voronoi", VoronoiCluster: "voronoi_cluster",
  FractureDetail: "fracture", ExplodedView: "explode", Facet: "facet",
  Convert: "convert", PolyReduce: "reduce", LoopCut: "loopcut",
  EdgeDivide: "edgediv", Ray: "ray", PointJitter: "jitter",
  MatchSize: "matchsize", PolyExpand2D: "expand2d", PolyFill: "polyfill", Triangulate2D: "tri2d",
  DisplaceFromMap: "displace", Connectivity: "connectivity",
  Torus: "torus", Deform: "twist", SoftTransform: "soft_xform",
  Spherify: "spherify", Ends: "ends",
  // attributes
  AttribCreate: "attrib_new", AttribDelete: "attrib_del",
  AttribCopy: "attrib_copy", AttribBlur: "attrib_blur",
  AttribNoise: "attrib_noise", AttribRandomize: "attrib_rand",
  AttribCast: "attrib_cast", AttribPromote: "attrib_promote",
  AttribTransfer: "attrib_xfer", AttribFade: "attrib_fade",
  AttribRename: "attrib", AttribAdjust: "attrib",
  AttribAdjustFloat: "attrib_adjust", AttribAdjustInteger: "attrib_adjust",   // pcg100 s6
  AttribAdjustVector: "attrib_adjust", AttribAdjustColor: "attrib_adjust",
  AttribFadeTime: "attrib_fade",   // pcg100 s7
  AttribTransformExtractHou: "extract_xform",   // pcg100 s7
  Name: "enumerate_",   // pcg100 s7
  PolyDoctor: "clean",   // pcg100 s7
  AttribInterpolate: "attrib", AttribFromMap: "image",
  AttribFromCamera: "attrib_cam",
  Measure: "measure", ExtractCentroid: "centroid", Normal: "normal",
  Wrangle: "wrangle",
  // groups
  GroupCreate: "group_new", GroupDelete: "group_del",
  GroupExpand: "group_expand", GroupEdges: "group_edges",
  GroupInside: "group_inside", GroupPromote: "group_promote",
  EdgeGroupPromote: "group_promote",
  // UV
  UVProject: "uv_project", UVFlatten: "uv_flatten", UVLayout: "uv_layout",
  UVAutoSeams: "uv_seams", UVTransform: "uv",
  // COP
  COPNoise: "cop_noise", COPShape: "cop_shape", COPGradient: "cop_gradient",
  COPConstant: "cop_const", COPBlur: "cop_blur", COPComposite: "cop_comp",
  COPResize: "cop_resize", COPImport: "cop_in", COPExport: "cop_out",
  COPInfo: "cop_info", COPWarp: "cop_warp", COPToDevice: "cop_info",
  COPTransform: "cop_transform", COPFlip: "cop_flip", COPCrop: "cop_crop",
  COPTile: "cop_tile", COPDistort: "cop_distort", COPLevels: "cop_levels",
  COPRemap: "cop_remap", COPQuantize: "cop_quantize", COPFit: "cop_fit",
  COPLuminance: "cop_luma", COPMorph: "cop_morph", COPEdge: "cop_edge",
  COPSharpen: "cop_sharpen", COPMedian: "cop_median",
  COPSDFFromMask: "cop_sdf",
  COPHeightToNormal: "h2n", COPNormalToHeight: "n2h",
  COPHeightToAO: "h2ao", COPHeightToShadow: "h2shadow",
  COPHeightToCaustics: "caustics", COPRefractFromHeight: "refract",
  COPCombineNormals: "combine_n", COPConvertNormal: "convert_n",
  COPErosion: "erosion",
  COPSlope: "slope", COPCurvature: "curvature", COPStatistics: "stats",
  COPHistogram: "histogram", COPSegment: "segment", COPCompare: "compare",
  COPMaskByFeature: "hf_mask", COPTerrace: "terrace",
  COPThermalErosion: "slump", COPHeightfieldToMesh: "hf_mesh",
  COPFlowAccumulation: "flow_acc", COPStreamPower: "stream_power", COPRoadNetwork: "road_network",
  COPHydraulicErosion: "hydro", COPHeightfieldErode: "hydro",
  COPSplatMap: "splat", RegionalPrompt: "region_prompt",
  COPHeightfieldFromDepth: "from_depth",
  // completing Copernicus batch A
  COPColorCorrect: "cc", COPInvert: "invert", COPClamp: "clamp",
  COPChannelConvert: "chan_conv", COPChannelSplit: "chan_split",
  COPChannelJoin: "chan_join", COPSwizzle: "swizzle",
  COPVectorMath: "vecmath", COPVectorTransform: "vecxform",
  COPFunction: "func", COPLogic: "logic", COPMaskCombine: "mask_comb",
  COPPremultiply: "premult", COPIllegalPixel: "illegal",
  COPToneMap: "tonemap", COPChromaKey: "chroma",
  COPLayerEdit: "layer_edit", COPLayerMerge: "layer_merge",
  COPLayerCombine: "layer_combine",
  COPAlign: "align", COPWrangle: "wrangle", COPFill: "fill",
  COPVignette: "vignette", COPRandom: "random",
  COPConvertDepth: "depth_conv",
  // pcg100: a few with Houdini semantics (c2_color_key)
  COPDespill: "despill", COPEqualize: "equalize",
  COPHistogramPlot: "hist_plot", COPCompareMask: "cmp_mask",
  COPMonoToRGB: "mono_rgb", COPMonoToHeightField: "mono_hf",
  // completing Copernicus batch B
  COPDefocus: "fx_defocus", COPDirectionalBlur: "fx_dirblur",
  COPKuwahara: "fx_kuwahara", COPConvolve: "fx_convolve",
  COPDenoiseTV: "fx_tv", COPGlow: "fx_glow", COPDropShadow: "fx_shadow",
  COPFeather: "fx_feather", COPPixelate: "fx_pixelate",
  // pcg100 c7: new nodes with Houdini semantics
  COPFeatherSlope: "fx_feather_slope", COPExtrapolateBoundaries: "fx_extrap",
  COPEdgeDetectProbe: "fx_edgeprobe", COPSurfaceDither: "fx_surfdither",
  COPTuringPatterns: "fx_turingpat", COPHeatDistortByLayer: "fx_heatlayer",
  COPChromaticAberration: "fx_chroma_ab", COPHeatDistort: "fx_heat",
  COPSwirl: "fx_swirl", COPLensDistort: "fx_lens",
  COPDerivative: "fx_deriv", COPCornerDetect: "fx_corner",
  COPSmoothFill: "fx_smoothfill", COPFloodFill: "fx_flood",
  COPContour: "fx_contour", COPDither: "fx_dither", COPMirror: "fx_mirror",
  COPCornerPin: "fx_cornerpin", COPLatticeDeform: "fx_lattice",
  COPPlanarInflate: "fx_inflate", COPCopyTransform: "fx_copyxf",
  // completing Copernicus batch C
  COPPattern: "pat_pattern", COPNoiseExtra: "pat_noisex", COPText: "pat_text",
  COPScatterShapes: "pat_scatter", COPStereogram: "pat_stereo",
  // pcg100 c3_noise: Worley / Cellular are cellular patterns, borrowing the Voronoi 2D icon; Fractal Sample borrows the noise one
  COPWorleyNoise: "voronoi2d", COPCellularNoise: "voronoi2d",
  COPFractalSample: "cop_noise",
  // completing Copernicus batch D
  COPFFT: "sv_fft", COPPrefixSum: "sv_prefix", COPSolvePoisson: "sv_poisson",
  COPEikonal: "sv_eikonal", COPSegmentByValue: "sv_segment",
  COPBoundingRect: "sv_bbox", COPSelect: "sv_select",
  COPReactionDiffusion: "sv_rd", COPRipple: "sv_ripple",
  COPFlowSolve: "sv_flow", COPOcean: "sv_ocean",
  // completing Copernicus batch E
  COPUVMap: "ux_uvmap", COPUVSample: "ux_uvsample", COPUVShape: "ux_uvshape",
  COPUVTransform: "ux_uvxform", COPUVInverse: "ux_uvinv", COPPolar: "ux_polar",
  COPPolarCoords: "ux_polarco", COPSpaceTransform: "ux_spacexf", COPPositionMap: "ux_posmap",
  COPSphereSample: "ux_sphsample", COPTransform3D: "ux_xform3d", COPAlignWindow: "ux_alignwin",
  COPAlignPixels: "ux_alignpx", COPBend: "ux_bend",
  COPHexTile: "ux_hex", COPTriplanar: "ux_triplanar", COPRetile: "ux_retile",
  COPSDFOps: "ux_sdfops", COPIDConvert: "ux_idconv",
  // completing Copernicus batch F
  COPLayerToPoints: "gi_l2p", COPPointGenerate: "gl_ptgen", COPLayerFromAttrib: "gl_lfa", COPGeoToLayer: "gl_g2l",
  COPSequenceClips: "gl_seqclip", COPTimePack: "gl_tpack", COPIntegrateVolume: "gl_integ",
  COPConfigureStamps: "gl_cfgstamp", COPPointsFromBlobs: "gi_blobs",
  COPRasterizeCurves: "gi_curves", COPRasterizeSplats: "gi_splats",
  COPBakeTextures: "gi_bake", COPLight: "hv_light", COPHFClip: "hv_clip",
  COPHFProject: "hv_project", COPStrata: "hv_strata", COPVisualize: "hv_vis",
  COPContactSheet: "hv_sheet", COPWipe: "hv_wipe", COPSequenceOps: "hv_seqops",
  ControlImage: "control", IDMasks: "idmask", RenderPass: "render",
  SequenceExport: "seq_out", SequenceImport: "seq_in",
  SequencePick: "seq_pick", HeightfieldFromImage: "heightfield",
  // rendering
  Camera: "camera", CameraPath: "campath", CameraPick: "campath",
  RenderSequence: "seq", MotionVectors: "motion", SequenceMotion: "motion",
  UVBackproject: "backproject", UVResolve: "uv_resolve",
  TextureRender: "texrender",
  // scattering
  Scatter: "scatter", ScatterFromMap: "scatter", ScatterVolume: "scatter_vol",
  CopyToPoints: "copyto",
  // loops / parameters / output / conversion
  ForEachBegin: "loop_begin", ForEachEnd: "loop_end",
  ForEachFrameBegin: "frame_begin", ForEachFrameEnd: "frame_end",
  GeoSequencePick: "seq_pick",
  Value: "value", Expr: "expr", Expr3: "expr", Frame: "clock",
  Parameters: "panel",
  ParamsFromJSON: "params_fill", ParamPick: "param_pick",
  Channel: "channel", Channel3: "channel",
  TimeBlend: "timeblend", Trail: "trail", Retime: "retime",
  ExportMesh: "export_", ImportMesh: "import_",
  FromJSON: "json_in", GeoToJSON: "json_out",
  PreviewImage: "preview",
  ConvertLine: "line", Trace: "trace",
  PolyPath: "polypath", Join: "join",
  Viewport: "viewport3d", Display: "display_flag",
  GeoMetrics: "metrics", SelectBest: "select_best",
  Voronoi2D: "voronoi2d", FileCache: "filecache",
  GeoSpreadsheet: "spreadsheet",
  // pcg67
  OrientAlongCurve: "orient_curve", PolyFrame: "polyframe",
  CopyAndTransform: "copy_xform", Revolve: "revolve",
  CopyToCurves: "copy_curve", Chain: "chain",
  FindShortestPath: "shortest_path", GroupFindPath: "group_path",
  CurveIntersect: "curve_x", ConnectAdjacentPieces: "connect_pieces",
  // pcg68
  AttribFromPieces: "from_pieces", Enumerate: "enumerate_", Color: "color_",
  AttribFill: "fill_", AttribStringEdit: "string_edit",
  ClusterPoints: "cluster_", Remesh: "remesh", Clean: "clean",
  EdgeCollapse: "edge_collapse", PointSplit: "point_split", UVFuse: "uv_fuse",
  // pcg70
  PlatonicSolids: "platonic", LSystem: "lsystem", Font: "font_",
  LatticeFromBound: "lattice_box", Lattice: "lattice_ffd",
  PointDeform: "point_deform", BlendShapes: "blend_shapes",
  TransformPieces: "transform_pieces", PolyBridge: "poly_bridge",
  // pcg71
  AttribFromVolume: "from_volume", AttribTransferByUV: "uv_transfer",
  // pcg72
  Volume: "volume_new", VolumeBlur: "volume_blur", VolumeMix: "volume_mix",
  VolumeResample: "volume_resample", VolumeWrangle: "volume_wrangle",
  VolumeReshapeSDF: "volume_reshape", VolumeSmoothSDF: "volume_blur",   // pcg100 s9
  BooleanFracture: "voronoi", IsoOffset: "volume_new",
  IntersectionAnalysis: "bool", FileMerge: "filecache",
  // pcg73
  ExtractTransform: "extract_xform", AttribTransformExtract: "xform_extract_pieces",
  MatchAxis: "match_axis", Primitive: "prim_xform", AttribReorient: "reorient",
  MatchTopology: "match_topo", TopoTransfer: "topo_transfer", DeltaMush: "delta_mush",
  // pcg74
  EdgeEqualize: "edge_equalize", EdgeStraighten: "edge_straighten",
  CircleFromEdges: "circle_edges", EdgeFlip: "edge_flip", TriDivide: "tri_divide",
  Unsubdivide: "unsubdivide", RewireVertices: "rewire", PolyCut: "poly_cut",
  PolyStitch: "poly_stitch", VoronoiSplit: "voronoi_split",
  // pcg75
  CircleSpline: "circle_spline", PolySpline: "poly_spline", BallisticPath: "ballistic",
  PolyLoft: "poly_loft", CrossSectionSurface: "cross_section",
  CrossSectionSurfaceHou: "cross_section_grid",          // pcg100 s3_curves
  // pcg76
  AttribComposite: "attrib_composite", AttribMirror: "attrib_mirror",
  GroupFromAttribBoundary: "attrib_boundary", Partition: "partition",
  TangentField: "tangent_field", AdaptivePrune: "adaptive_prune",
  PointReplicate: "point_replicate", PointVelocity: "point_velocity",
  // pcg77
  IsoSurface: "isosurface", RemeshToGrid: "remesh_grid", UVSmooth: "uv_smooth",
  ExtractSilhouette: "silhouette", COPTileSplit: "tile_split", COPTileSplice: "tile_splice",
  CameraToPoints: "cam_points", CameraFromPoints: "cam_from_points",
  GroupCombine: "group_combine", SwitchIf: "switch_if", PointRelax: "point_relax",
  PrimitiveSplit: "prim_split", TransformByAttrib: "xform_attrib", PolySplit: "poly_split",
  EdgeCusp: "edge_cusp", Crease: "crease",
  // pcg121
  DistanceFromGeometry: "dist_from_geo", DistanceAlongGeometry: "dist_along_geo", PathDeform: "path_deform",
  PolyWire: "polywire", Thicken: "thicken", CurveFillet: "curve_fillet", Pack: "pack", Unpack: "unpack",
  Assemble: "assemble",
  Shrinkwrap: "shrinkwrap",
  SoftPeak: "soft_peak", Bulge: "bulge", Magnet: "magnet", Fractal: "fractal",
  ScatterAlign: "scatter_align", EdgeTransport: "edge_transport", VolumeRasterizeAttribs: "vol_raster",
  COPHFMaskByObject: "hf_mask", COPHFCutoutByObject: "hf_cutout",
  // pcg84: the two file-writing nodes borrow the existing "output" icon
  COPWriteFile: "cop_out", ExportInstances: "export_",
  // pcg100
  BlastByAttribute: "blast_attr",
  UVPelt: "uv_pelt", UVUnwrap: "uv_unwrap",
  // pcg106 volume / VDB
  VDB: "vdb", VDBActivate: "vdb_activate", VDBActivateSDF: "vdb_sdf", VDBDensify: "volume_new",
  VDBPrune: "vdb_tree", VDBClip: "clip", VDBFill: "fill", VDBTopologyToSDF: "vdb_sdf",
  VDBDiagnostics: "stats", VDBVisualizeTree: "vdb_tree", VDBMetadata: "attrib", VDBVectorMerge: "vol_vector",
  VDBVectorSplit: "split", VDBTransform: "transform", VDBLOD: "volume_resample", VDBMerge: "merge",
  VDBSegment: "connectivity", VDBRemap: "cop_remap", ConvertVDB: "convert", VDBFromPolygons: "from_volume",
  VDBFromParticles: "vol_raster", VDBFromParticleFluid: "hydro", VDBRenormalizeSDF: "vdb_sdf", VDBRebuildSDF: "vdb_sdf",
  VDBMorphSDF: "blend_shapes", VDBFracture: "fracture", VDBToSpheres: "scatter_vol", VDBPlatonic: "platonic",
  VDBNoise: "fractal", VDBExtrapolate: "fx_extrap", VDBOcclusionMask: "camera", VDBRay: "ray",
  VolumeSDF: "vdb_sdf", VDBAnalysis: "slope", VDBSmooth: "volume_blur", VDBAdvect: "vol_flow",
  VDBAdvectPoints: "point_velocity", VDBProjectNonDivergent: "vol_flow", VDBPotentialFlow: "vol_flow", VDBCombine: "volume_mix",
  VDBResample: "volume_resample", VDBPointsGroup: "group", VDBScatter: "scatter_vol", VolumeAdjustFog: "cop_levels",
  VolumeBound: "bound", VolumeBreak: "poly_cut", VolumeCompress: "cop_quantize", VolumeConvolve: "fx_convolve",
  VolumeFeather: "fx_feather", VolumeFFT: "sv_fft", VolumeFromAttrib: "vol_raster", VolumeMerge: "layer_merge",
  VolumeOpticalFlow: "motion", VolumePatch: "fx_smoothfill", VolumeRamp: "cop_remap", VolumeRasterizeCurve: "sweep",
  VolumeRasterizeParticles: "splat", VolumeRasterizePoints: "vol_raster", VolumeReduce: "stats", VolumeResize: "cop_crop",
  VolumeSlice: "vol_slice", VolumeSplice: "tile_splice", VolumeStamp: "copyto", VolumeTrail: "vol_trail",
  VolumeVelocity: "vol_flow", VolumeVelocityFromCurves: "vol_trail", VolumeVelocityFromSurface: "vol_flow", VolumeVisualization: "vol_vis",
};

// Category fallback: used by nodes not in NODE_GLYPH. **Kept on purpose**, so a newly added node whose icon was
// forgotten still draws something -- but the tests list all nodes that use the fallback
export const CATEGORY_GLYPH = {
  "PCG/generate": "box", "PCG/modify": "transform",
  "PCG/attribute": "attrib", "PCG/group": "group", "PCG/uv": "uv",
  "PCG/cop": "image", "PCG/image": "image", "PCG/render": "camera",
  "PCG/scatter": "scatter", "PCG/loop": "loop_begin", "PCG/param": "value",
  "PCG/convert": "convert", "PCG/deform": "displace",
  "PCG/topology": "connectivity", "PCG/output": "export_",
  "PCG/volume": "vdb",
};

export function glyphFor(type, category) {
  const short = String(type || "").replace(PREFIX, "");
  const g = NODE_GLYPH[short];
  if (g && GLYPHS[g]) return g;
  const cg = CATEGORY_GLYPH[category];
  if (cg && GLYPHS[cg]) return cg;
  return "transform";
}

export function colorFor(category) {
  return CATEGORY_COLOR[category] || DEFAULT_COLOR;
}

/**
 * Draw an icon of edge length size at (cx,cy). lw is the line width in device pixels.
 *
 * Line width must be **divided by the scale**: the icon itself is drawn in [-1,1], and after `ctx.scale(s,s)`
 * the line width is also multiplied by s. Without dividing, lines blur into a black blob when the canvas is zoomed out.
 */
export function drawGlyph(ctx, name, cx, cy, size, color, lw) {
  const fn = GLYPHS[name] || GLYPHS.transform;
  const s = size * 0.5;
  ctx.save();
  try {
    ctx.translate(cx, cy);
    ctx.scale(s, s);
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = (lw || 1.4) / s;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    if (ctx.setLineDash) ctx.setLineDash([]);
    fn(ctx);
  } catch (e) {
    /* an icon drawing failure must not take the whole canvas down with it */
  }
  ctx.restore();
}

// ─────────────────────────────────────────────── hooking into litegraph
app.registerExtension({
  name: "pcg.icons",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    const type = nodeData?.name || "";
    if (!type.startsWith(PREFIX)) return;
    const cat = nodeData?.category || "";
    const glyph = glyphFor(type, cat);
    const color = colorFor(cat);

    nodeType.prototype.onDrawTitleBox = function (ctx, titleHeight, size,
                                                  scale) {
      try {
        // litegraph draws a small dot here by default, centered at (h/2, −h/2).
        // The icon goes in the same place, sized at 0.62 of the title height -- a bit bigger than the default dot but not touching
        // the title text (the text starts around h*0.9)
        const h = titleHeight || 24;
        const cx = h * 0.5, cy = -h * 0.5;
        drawGlyph(ctx, glyph, cx, cy, h * 0.62, color, 1.5);
        // A thin color bar at the left end: with dozens of nodes on screen, color is seen before shape
        ctx.save();
        ctx.fillStyle = color;
        ctx.globalAlpha = 0.85;
        ctx.fillRect(0, -h, 3, h);
        ctx.restore();
      } catch (e) {
        /* some frontend versions may not call it with this signature; failing to draw must not throw */
      }
    };
  },
});
