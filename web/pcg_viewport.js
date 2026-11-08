// comfyui_pcg/web/pcg_viewport.js
//
// Frontend of PCG_Viewport.
//
// Division of responsibilities:
//   geometry data -- computed by Python, only updated by a run
//   display options -- entirely on the frontend, take effect immediately, never trigger any execution
// So all widgets below are serialize:false client-side widgets; values are stored in
// node.properties and saved with the workflow, not in INPUT_TYPES.
//
// The grid works the Houdini way: pinned to the XZ plane at the world origin, units quantized to 1/2/5×10ⁿ,
// sized far larger than the object rather than hugging the bbox, with coordinate labels at the origin and major ticks.
//
// Note on hard edges: three.js indexed geometry allows only one normal per point, so hard edges
// require splitting points (non-indexed) + per-corner normals. That is the path taken when normals
// is vertex or flat.

import { app } from "../../scripts/app.js";
import { buildVolumes } from "./pcg_volume.js";

const VENDOR_URL = new URL("./vendor/three.module.js", import.meta.url).href;
const CDN_URL = "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";

let THREE = null;
async function loadThree() {
  if (THREE) return THREE;
  try {
    THREE = await import(/* webpackIgnore: true */ VENDOR_URL);
  } catch (e) {
    console.warn("[pcg.viewport] vendor unavailable, falling back to CDN:", e.message);
    THREE = await import(/* webpackIgnore: true */ CDN_URL);
  }
  return THREE;
}

// attribute class colors, consistent with the design document
const C_POINT = 0x4d9de0, C_VERTEX = 0xa978f0, C_PRIM = 0x43c98b;
const CSS_POINT = "#5fc4ff", CSS_VERTEX = "#c58cff", CSS_PRIM = "#4fe3a0";
// Axis colors: X red Y green Z blue (consistent with Houdini / most DCCs)
const AX = [
  { v: [1, 0, 0], css: "#e0575b", label: "X" },
  { v: [0, 1, 0], css: "#63c46a", label: "Y" },
  { v: [0, 0, 1], css: "#5b8fe0", label: "Z" },
];
const BG = 0x1a1a1e;
const MAX_TICKS = 30;          // maximum number of ticks labelled per axis
// Indices are all drawn, no sampling, no dedup -- that is Houdini's behaviour; crowded together they are still drawn;
// zooming and tumbling are the means to resolve overlap anyway, and "picking a few to show" for the user would mislead.
// The only limit is a performance safeguard: each element is projected once per frame, and beyond this magnitude
// the browser freezes; then nothing is drawn and the reason is shown, rather than quietly drawing fewer.
const LABEL_LIMIT = 400000;

// Digit atlas. Three things determine readability; all three were wrong before:
//
// 1) Cells must be **cropped to the glyph width**, not square. A square cell mapped onto a quad stretches vertically
//    by a factor of two, glyphs get taller and thinner, and spacing widens -- that is why "the digits drifted apart" before.
//    Here measureText gives the real advance; the cell width is that plus the stroke margin.
// 2) The outline must be **baked into the atlas**, stored in a separate channel from the glyph core: red channel = core, green channel = outline.
//    The fragment shader blends by the red channel, so glyphs are colored and the outline is always dark, readable on both light and dark backgrounds.
//    If only alpha were stored, uColor would tint the outline the same color, i.e. no outline.
// 3) Atlas resolution must exceed the on-screen size, with mipmaps plus anisotropic filtering. A 13px glyph drawn
//    from a 13px atlas is blurry; downsampling from a 96px atlas is sharp.
const GLYPH_N = 12;
let GLYPH = null;
function glyphAtlas(T, renderer) {
  if (GLYPH) return GLYPH;
  const CH = 96;
  const font = `700 ${Math.round(CH * 0.74)}px ui-monospace, "SF Mono", ` +
               `Menlo, Consolas, monospace`;
  const probe = document.createElement("canvas").getContext("2d");
  probe.font = font;
  const adv = probe.measureText("0").width;
  const lw = CH * 0.15;
  const CW = Math.ceil(adv + lw);            // leave stroke margin so the blurred edge isn't cropped

  const cv = document.createElement("canvas");
  cv.width = CW * GLYPH_N;
  cv.height = CH;
  const g = cv.getContext("2d");
  g.font = font;
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.lineJoin = "round";
  g.lineWidth = lw;
  g.globalCompositeOperation = "lighter";    // let the two channels accumulate separately, not overwrite each other
  for (let i = 0; i < 10; i++) {
    const x = (i + 0.5) * CW, y = CH * 0.52;
    g.strokeStyle = "#00ff00";
    g.strokeText(String(i), x, y);           // green = outline
    g.fillStyle = "#ff0000";
    g.fillText(String(i), x, y);             // red = glyph core
  }

  const tex = new T.CanvasTexture(cv);
  tex.minFilter = T.LinearMipmapLinearFilter;
  tex.magFilter = T.LinearFilter;
  tex.generateMipmaps = true;
  if (renderer) tex.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
  GLYPH = { tex, halfW: CW / CH, adv: adv / CH };
  return GLYPH;
}

const CORNER_INSET = 0.18;   // fraction by which a corner is offset toward the face center; without it they all overlap

// gl_PointSize draws squares. Round points need a circular texture on PointsMaterial --
// a custom shader with discard would also work, but ShaderMaterial doesn't run on this machine;
// the texture approach relies only on the most basic features, so it's reliable. The texture is generated procedurally, no external file, built once globally.
let POINT_TEX = null;
function pointTexture(T) {
  if (POINT_TEX) return POINT_TEX;
  const s = 64, cv = document.createElement("canvas");
  cv.width = cv.height = s;
  const g = cv.getContext("2d");
  g.beginPath();
  g.arc(s / 2, s / 2, s / 2 - 1.5, 0, Math.PI * 2);
  g.fillStyle = "#fff";
  g.fill();
  POINT_TEX = new T.CanvasTexture(cv);
  POINT_TEX.minFilter = T.LinearMipmapLinearFilter;
  POINT_TEX.magFilter = T.LinearFilter;
  return POINT_TEX;
}

const HL = 0xff9a3c;              // Houdini's group highlight orange

// The persistent panel (pcg_display.js) reuses the same defaults; don't write them in two places -- if they drift it
// shows up as "the panel and the in-node viewport have different default shading", which is very hard to track down.
// ---------------------------------------------------------------- UV (pcg114)
//
// Where the uv comes from: vertex uv wins over point uv (the same priority as Houdini's UV view). Size 2 and size 3
// (Houdini's uv is a vector3) are both read as (u, v). Returns null when there is no usable uv.
export function uvSource(data) {
  const A = data.arrays, meta = data.header?.attrib_meta || {};
  const nv = A.vertex_point ? A.vertex_point.length : 0;
  const np = A.position ? A.position.length / 3 : 0;
  const pick = (cls, arr, n) => {
    if (!arr || !n) return null;
    const sz = meta[cls]?.uv?.size || Math.round(arr.length / n);
    return sz >= 2 && arr.length >= n * sz ? { cls, arr, sz } : null;
  };
  return pick("vertex", A.a_vertex_uv, nv) || pick("point", A.a_point_uv, np);
}

export const UV_FRONT = [0.29, 0.56, 0.95];
export const UV_FLIP = [0.95, 0.32, 0.30];

// The UV layout as flat arrays, ready for three.js and testable without it:
//   tri    (u, v, 0) for every triangle corner
//   col    per-corner colour: UV_FRONT, or UV_FLIP for triangles wound against the majority (mirrored islands,
//          folded faces). Degenerate (zero-area) triangles count as front.
//   edges  polygon edges in uv space, (u, v, 0) pairs. Built per vertex, not from the 3D edge list: a uv seam is
//          two different uv edges on the same 3D edge. Only polygons (prims that have triangles) are closed loops;
//          open curves have no uv layout and are left out.
export function uvLayout(data) {
  const src = uvSource(data);
  if (!src) return null;
  const A = data.arrays, { cls, arr, sz } = src;
  const idx = A.index, tc = A.tri_corner, vp = A.vertex_point, vpr = A.vertex_prim;
  // element (row in arr) for triangle corner i / for vertex v
  const triEl = cls === "vertex" ? (tc ? (i) => tc[i] : null) : (idx ? (i) => idx[i] : null);
  const vtxEl = cls === "vertex" ? (v) => v : (vp ? (v) => vp[v] : null);
  let u0 = Infinity, v0 = Infinity, u1 = -Infinity, v1 = -Infinity;
  const grow = (u, v) => {
    if (u < u0) u0 = u; if (u > u1) u1 = u;
    if (v < v0) v0 = v; if (v > v1) v1 = v;
  };
  const nT = triEl && idx ? idx.length / 3 : 0;
  const tri = new Float32Array(nT * 9), col = new Float32Array(nT * 9);
  const sign = new Int8Array(nT);
  let pos = 0, neg = 0;
  for (let t = 0; t < nT; t++) {
    for (let k = 0; k < 3; k++) {
      const e = triEl(t * 3 + k) * sz, o = t * 9 + k * 3;
      tri[o] = arr[e]; tri[o + 1] = arr[e + 1];
      grow(arr[e], arr[e + 1]);
    }
    const o = t * 9;
    const a = (tri[o + 3] - tri[o]) * (tri[o + 7] - tri[o + 1])
            - (tri[o + 6] - tri[o]) * (tri[o + 4] - tri[o + 1]);
    sign[t] = a > 0 ? 1 : a < 0 ? -1 : 0;
    if (a > 0) pos++; else if (a < 0) neg++;
  }
  const front = pos >= neg ? 1 : -1;
  let flipped = 0;
  for (let t = 0; t < nT; t++) {
    const c = sign[t] === -front ? UV_FLIP : UV_FRONT;
    if (sign[t] === -front) flipped++;
    for (let k = 0; k < 9; k++) col[t * 9 + k] = c[k % 3];
  }
  const edges = [];
  if (vtxEl && vpr && tc && vpr.length) {
    const isPoly = new Set();
    for (let i = 0; i < tc.length; i++) isPoly.add(vpr[tc[i]]);
    const nv = vpr.length;
    const put = (a, b) => {
      const ea = vtxEl(a) * sz, eb = vtxEl(b) * sz;
      edges.push(arr[ea], arr[ea + 1], 0, arr[eb], arr[eb + 1], 0);
      grow(arr[ea], arr[ea + 1]);
    };
    for (let s = 0; s < nv;) {
      let e = s + 1;
      while (e < nv && vpr[e] === vpr[s]) e++;
      if (isPoly.has(vpr[s]) && e - s >= 3) {
        for (let v = s; v < e; v++) put(v, v + 1 < e ? v + 1 : s);
      }
      s = e;
    }
  }
  const bbox = u0 <= u1 ? [u0, v0, u1, v1] : null;
  return { cls, tri, col, nTri: nT, flipped, edges: new Float32Array(edges), bbox };
}

// UV checker for shading = "uv": 8 x 8 cells per uv tile, light cells tinted by position (u -> red, v -> green) so
// orientation and tile are readable, and a dark notch in the low-u / low-v corner of each light cell, so a mirrored
// face shows its notch on the wrong side. A DataTexture: no 2D canvas needed.
function checkerTexture(T) {
  const N = 256, C = N / 8, px = new Uint8Array(N * N * 4);
  for (let y = 0; y < N; y++) {
    for (let x = 0; x < N; x++) {
      const cx = (x / C) | 0, cy = (y / C) | 0, lx = x % C, ly = y % C, o = (y * N + x) * 4;
      let r, g, b;
      if ((cx + cy) % 2) { r = g = b = 0.22; }
      else if (lx >= 3 && lx < 10 && ly >= 3 && ly < 10) { r = g = b = 0.30; }
      else { r = 0.45 + 0.5 * (cx + 0.5) / 8; g = 0.45 + 0.5 * (cy + 0.5) / 8; b = 0.78; }
      px[o] = r * 255; px[o + 1] = g * 255; px[o + 2] = b * 255; px[o + 3] = 255;
    }
  }
  const t = new T.DataTexture(px, N, N, T.RGBAFormat);
  t.wrapS = t.wrapT = T.RepeatWrapping;
  t.magFilter = T.NearestFilter;
  t.minFilter = T.LinearMipmapLinearFilter;
  t.generateMipmaps = true;
  if (T.SRGBColorSpace) t.colorSpace = T.SRGBColorSpace;
  t.needsUpdate = true;
  return t;
}

// Keys typed into these belong to them; everything else (select, button, checkbox, range...) lets the view keys through
export function isTypingTarget(t) {
  if (!t || !t.tagName) return false;
  if (t.isContentEditable || t.tagName === "TEXTAREA") return true;
  if (t.tagName !== "INPUT") return false;
  return !/^(checkbox|radio|button|submit|reset|range|color|file|image)$/i.test(t.type || "text");
}

export const DEFAULTS = {
  highlight: "none",
  visualize: "none",
  shading: "phong", normals: "auto", wireframe: false, show_points: false,
  show_normals: "none", normal_scale: 0.25, numbers: "none", show_grid: true,
};

// ---------------------------------------------------------------- decoding
export function decode(buf) {
  const dv = new DataView(buf);
  if (String.fromCharCode(...new Uint8Array(buf, 0, 4)) !== "PCGB")
    throw new Error("bad geometry payload");
  const hlen = dv.getUint32(4, true);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 8, hlen)));
  const base = 8 + hlen;            // the backend already padded the header with spaces to 4-byte alignment
  // dtype must be mapped one by one. A missing one would be read as Float32Array -- group masks are uint8,
  // and if missing every 4 bytes of mask get combined into one float, and the highlight comes out as a garbled pattern.
  const CTOR = { uint8: Uint8Array, uint16: Uint16Array, uint32: Uint32Array,
                 int32: Int32Array, float32: Float32Array };
  const A = {};
  for (const [name, b] of Object.entries(header.buffers)) {
    const Ctor = CTOR[b.dtype];
    if (!Ctor) {
      console.warn("[pcg.viewport] unknown dtype", b.dtype, "buffer", name);
      continue;
    }
    A[name] = new Ctor(buf, base + b.offset, b.length / Ctor.BYTES_PER_ELEMENT);
  }
  return { header, arrays: A };
}

// Snap any scale to 1 / 2 / 5 × 10ⁿ, so the grid unit is a "round" number and ticks are readable
function niceUnit(x) {
  if (!(x > 0) || !isFinite(x)) return 1;
  const e = Math.floor(Math.log10(x));
  const f = x / Math.pow(10, e);
  const n = f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10;
  return n * Math.pow(10, e);
}

function fmtCoord(v, unit) {
  if (Math.abs(v) < unit * 1e-6) return "0";
  const dec = Math.max(0, -Math.floor(Math.log10(unit)));
  return v.toFixed(Math.min(dec, 4));
}

// ---------------------------------------------------------------- viewport
// The whole renderer is decoupled from the node: constructing it only needs a DOM element and an options object.
// The persistent panel just attaches one to its own div, so both sides are pixel-identical.
export class Viewport {
  constructor(container, opts) {
    this.container = container;
    this.opts = { ...DEFAULTS, ...(opts || {}) };
    this.data = null;
    this.unit = 1;
    this.orbit = { theta: 0.7, phi: 1.1, dist: 5, target: [0, 0, 0] };
    this.fov = 45;              // the viewport's own vertical fov; overridden when looking through a camera
    this.gate = null;           // resolution gate { xres, yres, label }
    this.init();
  }

  async init() {
    const T = (this.T = await loadThree());
    this.scene = new T.Scene();
    this.scene.background = new T.Color(BG);
    // Only the grid material has fog:true; geometry is always fog:false -- fog is for fading out the distant grid,
    // it shouldn't veil the objects too. The near/far planes follow the camera distance every frame.
    this.scene.fog = new T.Fog(BG, 1, 100);
    this.camera = new T.PerspectiveCamera(45, 1, 0.01, 100000);

    this.renderer = new T.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(window.devicePixelRatio || 1);
    Object.assign(this.renderer.domElement.style, {
      width: "100%", height: "100%", display: "block", borderRadius: "4px",
    });
    this.container.appendChild(this.renderer.domElement);

    // Indices / ticks / the axis indicator are all drawn on a 2D overlay. Much cheaper than sprites,
    // and the text is rendered natively by canvas, crisp at any zoom.
    this.overlay = document.createElement("canvas");
    Object.assign(this.overlay.style, {
      position: "absolute", inset: "0", width: "100%", height: "100%",
      pointerEvents: "none",
    });
    this.container.appendChild(this.overlay);
    this.ctx = this.overlay.getContext("2d");

    // Houdini's viewport uses a headlight: the light follows the camera, whichever face you turn to is lit,
    // and the underside is never pitch black. A directional light fixed in world space can't do that.
    // A hemisphere light keeps a bit of ambient fill so back-lit faces don't lose all form.
    // Ambient takes the bulk, the headlight only about 30% -- the Houdini viewport has this kind of high-key lighting,
    // sides and undersides don't fall very dark. Before, headlight 1.15 with ambient 0.55 had too much contrast.
    this.scene.add(new T.HemisphereLight(0xffffff, 0xcacdd4, 0.85));
    this.head = new T.DirectionalLight(0xffffff, 0.30);
    this.scene.add(this.head);
    this.scene.add(this.head.target);
    this._lv = { r: new T.Vector3(), u: new T.Vector3() };

    this.gridGroup = new T.Group();
    this.scene.add(this.gridGroup);
    this.root = new T.Group();
    this.scene.add(this.root);

    this.applyGrid();
    this.bindInput();
    // Handles / drawing tool (pcg103). Dynamic import: if the module is broken there are just no handles, the viewport displays as usual
    import("./pcg_handles.js").then((m) => { this.tool = new m.HandleTool(this); })
      .catch((e) => console.warn("[pcg.viewport] failed to load the handles module:", e));
    // Selection (pcg122): S toggles click / box selection -> group expression. Same isolation as the handles
    import("./pcg_select.js").then((m) => { this.select = new m.SelectTool(this); })
      .catch((e) => console.warn("[pcg.viewport] failed to load the selection module:", e));
    this.loop();
    if (this.data) { this.rebuild(); this.frameAll(); }
  }

  // ---------------------------------------------------------- world grid
  //
  // A line-segment grid that follows the camera, visually infinite:
  //   · its center snaps to right below the camera (rounded to the major step, so grid lines don't slide with the camera)
  //   · its extent follows the camera distance, always filling the view
  //   · edges fade out with fog, and the fade ends before the boundary, so no end is visible
  //   · when the line count exceeds budget it steps up automatically (fine lines replaced by a 10× step), constant density on screen
  // Only LineBasicMaterial is used; compatibility equals "if three.js runs, it will display".
  gridReset() {
    while (this.gridGroup.children.length) {
      const c = this.gridGroup.children.pop();
      c.geometry?.dispose(); c.material?.dispose();
    }
    this.gridSig = null;
  }

  applyGrid() {
    this._dirty = true;
    if (!this.T) return;
    this.gridReset();
    this.gridGroup.visible = this.opts.show_grid !== false;
    if (this.gridGroup.visible) this.updateLineGrid(true);
  }

  // Grid line material. Two key settings:
  //   depthWrite: false -- the grid doesn't occupy the depth buffer. When geometry and grid lines are coplanar (e.g.
  //     a polyline along the X axis lying exactly on the red axis line), depth values are exactly equal, depthFunc LESS
  //     treats equal as fail, and whatever was drawn first wins. With the grid not writing depth, geometry drawn later always wins.
  //   renderOrder: -10 -- ensures the grid is always drawn first, regardless of camera sorting.
  _gridLines(pos, color) {
    const T = this.T;
    const g = new T.BufferGeometry();
    g.setAttribute("position", new T.Float32BufferAttribute(pos, 3));
    const m = new T.LineSegments(g, new T.LineBasicMaterial({
      color, fog: true, depthWrite: false }));
    m.renderOrder = -10;
    return m;
  }

  // Called every frame; returns right away if the signature hasn't changed, without rebuilding geometry
  updateLineGrid(force) {
    if (!this.T || this.opts.show_grid === false) return;
    const T = this.T, dist = this.orbit.dist;
    const extent = Math.max(this.unit * 20, dist * 6);

    // Automatic step-up: when the number of fine lines exceeds budget, switch to a 10× step, keeping on-screen density about the same
    let step = this.unit;
    while ((2 * extent) / step > 480) step *= 10;
    const major = step * 10;
    const cx = Math.round(this.camera.position.x / major) * major;
    const cz = Math.round(this.camera.position.z / major) * major;

    const sig = `${step}|${cx}|${cz}|${Math.round(Math.log2(extent) * 4)}`;
    if (!force && sig === this.gridSig) return;
    this.gridReset();
    this.gridSig = sig;
    this.gridStep = step;
    this.gridExtent = extent;

    const seg = (st, color) => {
      const pos = [];
      const a0 = Math.ceil((cx - extent) / st) * st;
      const b0 = Math.ceil((cz - extent) / st) * st;
      for (let x = a0; x <= cx + extent; x += st) {
        if (Math.abs(x) < st * 0.5) continue;        // the origin axes are drawn separately
        pos.push(x, 0, cz - extent, x, 0, cz + extent);
      }
      for (let z = b0; z <= cz + extent; z += st) {
        if (Math.abs(z) < st * 0.5) continue;
        pos.push(cx - extent, 0, z, cx + extent, 0, z);
      }
      if (!pos.length) return;
      this.gridGroup.add(this._gridLines(pos, color));
    };
    seg(step, 0x333942);
    seg(major, 0x5a636e);

    const axis = (a, b, color) => {
      this.gridGroup.add(this._gridLines([...a, ...b], color));
    };
    axis([cx - extent, 0, 0], [cx + extent, 0, 0], 0x9c4247);
    axis([0, 0, cz - extent], [0, 0, cz + extent], 0x41669c);
    this.gridGroup.visible = true;
  }

  updateGridScale() {
    // The aim is for the object to span roughly 10 cells; when the result falls in [0.1,1] take 1 -- normal scales get
    // Houdini's 1-unit grid. Zooming changes the grid's **extent**, not its unit.
    let u = niceUnit(this.bboxSize() / 10);
    if (u >= 0.1 && u <= 1) u = 1;
    u = Math.min(Math.max(u, 1e-4), 1e6);      // one more safeguard against extreme scales
    if (u === this.unit) return;
    this.unit = u;
    this.updateLineGrid(true);
  }

  setGeometry(decoded) {
    this._dataRev = (this._dataRev || 0) + 1;
    const moved = JSON.stringify(this.bbox) !== JSON.stringify(decoded.header.bbox);
    this.data = decoded;
    this.bbox = decoded.header.bbox;
    this.updateGridScale();
    this.rebuild();
    if (moved) this.frameAll();
    this.select?.dataChanged();
  }

  setOptions(patch) {
    Object.assign(this.opts, patch);
    if ("show_grid" in patch) this.applyGrid();
    this.rebuild();                  // only rebuild the display; no refetching data, no execution triggered
  }

  attribLabels() {
    const m = this.data?.header?.attrib_meta || {};
    const out = ["none"];
    for (const cls of ["point", "vertex", "prim"])
      for (const n of Object.keys(m[cls] || {})) out.push(`${cls}:${n}`);
    return out;
  }

  // Discrete coloring: the same value always gets the same color, and adjacent integers must be far apart in hue -- the most common use of
  // attributes like class is "seeing which faces belong to the same piece"; similar hues would defeat that.
  // Hue is swept in golden-angle steps (137.5°), so any number of categories spreads out evenly.
  catColor(v) {
    const h = ((Math.round(v) * 137.508) % 360 + 360) % 360;
    const s = 0.62, l = 0.58;
    const c = (1 - Math.abs(2 * l - 1)) * s;
    const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
    const m2 = l - c / 2;
    const t = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x]
            : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
    return [t[0] + m2, t[1] + m2, t[2] + m2];
  }

  // Continuous coloring: blue -> cyan -> green -> yellow -> red. Easier to read gradations than grayscale.
  rampColor(t) {
    t = Math.max(0, Math.min(1, t));
    const stops = [[0.15, 0.25, 0.75], [0.15, 0.75, 0.75], [0.25, 0.8, 0.3],
                   [0.95, 0.85, 0.2], [0.9, 0.25, 0.2]];
    const f = t * (stops.length - 1);
    const i = Math.min(stops.length - 2, Math.floor(f));
    const k = f - i;
    return [0, 1, 2].map((c) => stops[i][c] * (1 - k) + stops[i + 1][c] * k);
  }

  // Returns {cls, colors: Float32Array(n*3), legend} or null
  vizColors(label) {
    if (!label || label === "none" || !this.data) return null;
    const [cls, ...rest] = label.split(":");
    const name = rest.join(":");
    const meta = this.data.header.attrib_meta?.[cls]?.[name];
    const arr = this.data.arrays[`a_${cls}_${name}`];
    if (!meta || !arr) return null;

    const n = arr.length / meta.size;
    const col = new Float32Array(n * 3);
    let legend;
    if (meta.size >= 3) {
      // Vectors are mapped per component to RGB, each normalized by its own range
      const mn = meta.min, mx = meta.max;
      for (let i = 0; i < n; i++)
        for (let c = 0; c < 3; c++) {
          const lo = mn[c], hi = mx[c];
          col[i * 3 + c] = hi > lo ? (arr[i * meta.size + c] - lo) / (hi - lo) : 0.5;
        }
      legend = `${name}  vec3 -> RGB`;
    } else if (meta.kind === "cat") {
      for (let i = 0; i < n; i++) {
        const c = this.catColor(arr[i]);
        col.set(c, i * 3);
      }
      legend = `${name}  ${meta.levels ?? "?"} classes`;
    } else {
      const lo = meta.min[0], hi = meta.max[0], d = hi - lo;
      for (let i = 0; i < n; i++) {
        const c = this.rampColor(d > 0 ? (arr[i] - lo) / d : 0.5);
        col.set(c, i * 3);
      }
      legend = `${name}  ${lo.toFixed(3)} ~ ${hi.toFixed(3)}`;
    }
    return { cls, colors: col, legend };
  }

  // group name -> {cls, mask}. Names look like "point:top", matching the dropdown.
  groupMask(label) {
    if (!label || label === "none" || !this.data) return null;
    const g = this.data.header.groups;
    if (!g) return null;
    const [cls, ...rest] = label.split(":");
    const name = rest.join(":");
    const i = (g[cls] || []).indexOf(name);
    if (i < 0) return null;
    const mask = this.data.arrays[`g_${cls}_${i}`];
    return mask ? { cls, mask } : null;
  }

  groupLabels() {
    const g = this.data?.header?.groups || {};
    const out = ["none"];
    for (const cls of ["point", "vertex", "prim"])
      for (const n of g[cls] || []) out.push(`${cls}:${n}`);
    return out;
  }

  // ---- anchors: positions for each of the three classes, shared by normal drawing and index labels ----
  anchors(cls) {
    const A = this.data.arrays;
    if (cls === "point")
      return { pos: A.position, n: A.normal, count: A.position.length / 3 };
    if (cls === "prim")
      return { pos: A.prim_center, n: A.pnormal,
               count: A.prim_center ? A.prim_center.length / 3 : 0 };
    // vertex: placed at its point, shrunk slightly toward the face center, otherwise the corners of the same point all overlap
    if (!A.vertex_point || !A.prim_center) return { pos: null, n: null, count: 0 };
    const nv = A.vertex_point.length;
    const pos = new Float32Array(nv * 3);
    for (let i = 0; i < nv; i++) {
      const p = A.vertex_point[i] * 3, c = A.vertex_prim[i] * 3;
      for (let k = 0; k < 3; k++)
        pos[i * 3 + k] = A.position[p + k] +
          (A.prim_center[c + k] - A.position[p + k]) * CORNER_INSET;
    }
    return { pos, n: A.vnormal, count: nv };
  }

  rebuild() {
    this._dirty = true;
    if (!this.T || !this.data) return;
    const T = this.T, A = this.data.arrays, o = this.opts;
    this._uvDirty = true;                  // the UV view rebuilds lazily, the next time it is drawn

    while (this.root.children.length) {
      const c = this.root.children.pop();
      c.geometry?.dispose(); c.material?.dispose();
    }
    this.mesh = null;
    this.triCount = 0;

    let src = o.normals;
    if (src === "auto") src = A.vnormal ? "vertex" : (A.normal ? "smooth" : "flat");
    // Attribute visualization colors. prim / vertex attributes must be colored per face, so points are forcibly split --
    // with shared vertices one point would be overwritten by the colors of two adjacent faces, and boundaries blur into gradients.
    const viz = this.vizColors(o.visualize);
    this.vizLegend = viz ? viz.legend : "";
    // Cd, drawn in every shaded mode as in Houdini (pcg109). The backend sends one class (vertex > point > prim >
    // detail); vertex / prim colours need split points like vertex / prim visualization does. A detail Cd tints the
    // whole mesh through the material colour.
    const cdCls = A.color ? (this.data.header.color_class || "point") : null;
    const cdTint = cdCls === "detail" && A.color.length >= 3
      ? new T.Color(A.color[0], A.color[1], A.color[2]) : null;
    const cdArr = cdCls && cdCls !== "detail" ? A.color : null;
    // shading = uv shows the uv checker instead of Cd (a visualized attribute still wins, as in every mode)
    const uvShade = o.shading === "uv" && !viz;
    const colArr = viz ? viz.colors : (uvShade ? null : cdArr);
    const uvSh = uvShade ? uvSource(this.data) : null;
    const uvOk = !!uvSh && (uvSh.cls === "point" || !!A.tri_corner);
    this.uvWarning = uvShade && A.index && !uvOk ? "no uv attribute" : "";
    const colCls = viz ? viz.cls : cdCls;
    const hasCol = !!colArr;
    const hardEdge = (src === "vertex" && A.vnormal && A.tri_corner)
                     || src === "flat"
                     || (hasCol && colCls !== "point" && !!A.tri_corner && !!A.vertex_prim)
                     || (uvOk && uvSh.cls === "vertex");

    // With shading=wire no faces are built at all, only the wireframe -- different from "faces + wireframe overlay";
    // pure wireframe shows the topology on the back, which is only useful when inspecting internal structure.
    const wireOnly = o.shading === "wire";
    if (A.index && !wireOnly) {
      const g = new T.BufferGeometry();
      if (hardEdge) {
        // Split points: three independent vertices per triangle, the only way to give each corner its own normal
        const T3 = A.index.length;
        const pos = new Float32Array(T3 * 3);
        for (let i = 0; i < T3; i++) {
          const s = A.index[i] * 3;
          pos[i * 3] = A.position[s];
          pos[i * 3 + 1] = A.position[s + 1];
          pos[i * 3 + 2] = A.position[s + 2];
        }
        g.setAttribute("position", new T.BufferAttribute(pos, 3));
        if (src === "vertex") {
          const nrm = new Float32Array(T3 * 3);
          for (let i = 0; i < T3; i++) {
            const s = A.tri_corner[i] * 3;
            nrm[i * 3] = A.vnormal[s];
            nrm[i * 3 + 1] = A.vnormal[s + 1];
            nrm[i * 3 + 2] = A.vnormal[s + 2];
          }
          g.setAttribute("normal", new T.BufferAttribute(nrm, 3));
        } else {
          g.computeVertexNormals();        // after splitting, the computed normals are face normals
        }
        if (hasCol) {
          const srcCol = colArr;
          const col = new Float32Array(T3 * 3);
          for (let i = 0; i < T3; i++) {
            // Element index for corner i of a triangle: point attributes look at index,
            // vertex attributes look at tri_corner, prim attributes then map the corner to its face
            const e = colCls === "point" ? A.index[i]
                    : colCls === "vertex" ? A.tri_corner[i]
                    : A.vertex_prim[A.tri_corner[i]];
            col[i * 3] = srcCol[e * 3];
            col[i * 3 + 1] = srcCol[e * 3 + 1];
            col[i * 3 + 2] = srcCol[e * 3 + 2];
          }
          g.setAttribute("color", new T.BufferAttribute(col, 3));
        }
        if (uvOk) {
          const { arr, sz } = uvSh, uv = new Float32Array(T3 * 2);
          for (let i = 0; i < T3; i++) {
            const e = (uvSh.cls === "vertex" ? A.tri_corner[i] : A.index[i]) * sz;
            uv[i * 2] = arr[e];
            uv[i * 2 + 1] = arr[e + 1];
          }
          g.setAttribute("uv", new T.BufferAttribute(uv, 2));
        }
      } else {
        g.setAttribute("position", new T.BufferAttribute(A.position, 3));
        g.setIndex(new T.BufferAttribute(A.index, 1));
        if (A.normal) g.setAttribute("normal", new T.BufferAttribute(A.normal, 3));
        else g.computeVertexNormals();
        // (only point colours reach here: vertex / prim colours force the split path above)
        if (hasCol && colCls === "point") g.setAttribute("color", new T.BufferAttribute(colArr, 3));
        if (uvOk) {                        // (only point uv reaches here: vertex uv forces the split path)
          const { arr, sz } = uvSh, n = A.position.length / 3, uv = new Float32Array(n * 2);
          for (let i = 0; i < n; i++) { uv[i * 2] = arr[i * sz]; uv[i * 2 + 1] = arr[i * sz + 1]; }
          g.setAttribute("uv", new T.BufferAttribute(uv, 2));
        }
      }

      let mat;
      if (viz) {
        // No specular when visualizing attributes: highlights wash out colors, making categories and values hard to read
        mat = new T.MeshLambertMaterial({
          vertexColors: true, color: 0xffffff, side: T.DoubleSide, fog: false });
      } else if (uvShade) {
        // UV checker, no specular (it would wash out the cells); grey with a HUD warning when there is no uv
        mat = new T.MeshLambertMaterial({
          map: uvOk ? (this._checker || (this._checker = checkerTexture(T))) : null,
          color: uvOk ? 0xffffff : 0xdedee2, side: T.DoubleSide, fog: false });
      } else if (o.shading === "normal") {
        mat = new T.MeshNormalMaterial({ side: T.DoubleSide, fog: false });
      } else if (o.shading === "color") {
        // When looking at Cd you want the color itself; specular would skew the reading, so this mode has no specular
        mat = new T.MeshLambertMaterial({
          vertexColors: hasCol, color: cdTint || (hasCol ? 0xffffff : 0xb0b0b8),
          side: T.DoubleSide, fog: false });
      } else if (o.shading === "lambert") {
        mat = new T.MeshLambertMaterial({
          vertexColors: hasCol, color: cdTint || (hasCol ? 0xffffff : 0xdedee2),
          side: T.DoubleSide, fog: false });
      } else {
        // Blinn-Phong. three's MeshPhongMaterial is Blinn-Phong internally
        // (BRDF_BlinnPhong), no custom shader needed. With the camera-following headlight, highlights
        // slide with the view angle, the most intuitive cue for judging surface continuity -- pure diffuse can't show it.
        // High key, low contrast: the base color is near white, mostly carried by ambient, with the headlight adding only a bit of direction.
        // High shininess = small, concentrated highlights -- low values like 34 spread into a big gray haze.
        // With Cd the base colour is white so Cd shows as it is (Houdini's smooth shaded view multiplies by Cd too)
        mat = new T.MeshPhongMaterial({
          vertexColors: hasCol, color: cdTint || (hasCol ? 0xffffff : 0xdedee2),
          specular: 0x9aa0a8, shininess: 120,
          side: T.DoubleSide, fog: false });
      }
      // Push faces back a bit so the wireframe doesn't z-fight with them
      Object.assign(mat, { polygonOffset: true, polygonOffsetFactor: 1,
                           polygonOffsetUnits: 1 });
      this.mesh = new T.Mesh(g, mat);
      this.triCount = (A.index ? A.index.length : 0) / 3;
      this.root.add(this.mesh);
    }

    // ---- packed primitives (pcg121): one InstancedMesh per distinct piece ----
    // The backend sends each piece once as split triangles (so vertex / prim Cd and hard edges survive) plus a
    // column-major 4x4 per copy, and the packed points' Cd as per-instance colour (multiplied with the piece's Cd).
    if (!wireOnly) {
      for (const inst of (this.data.header.instances || [])) {
        const k = inst.id, pos = A[`i${k}_position`], mtx = A[`i${k}_matrix`];
        if (!pos || !mtx) continue;
        const g = new T.BufferGeometry();
        g.setAttribute("position", new T.BufferAttribute(pos, 3));
        if (A[`i${k}_normal`]) g.setAttribute("normal", new T.BufferAttribute(A[`i${k}_normal`], 3));
        else g.computeVertexNormals();
        const vcol = !viz && !uvShade && A[`i${k}_color`];
        if (vcol) g.setAttribute("color", new T.BufferAttribute(vcol, 3));
        const base = { vertexColors: !!vcol, color: 0xffffff, side: T.DoubleSide, fog: false };
        const tint = vcol || A[`i${k}_icolor`] ? 0xffffff : 0xdedee2;
        let imat;
        if (o.shading === "normal") imat = new T.MeshNormalMaterial({ side: T.DoubleSide });
        else if (o.shading === "color" || o.shading === "lambert" || viz || uvShade)
          imat = new T.MeshLambertMaterial({ ...base, color: tint });
        else imat = new T.MeshPhongMaterial({ ...base, color: tint, specular: 0x9aa0a8, shininess: 120 });
        Object.assign(imat, { polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
        const im = new T.InstancedMesh(g, imat, inst.count);
        const m4 = new T.Matrix4();
        for (let i = 0; i < inst.count; i++) { m4.fromArray(mtx, i * 16); im.setMatrixAt(i, m4); }
        im.instanceMatrix.needsUpdate = true;
        const ic = A[`i${k}_icolor`];
        if (ic && !viz && !uvShade && o.shading !== "normal") {
          const c = new T.Color();
          for (let i = 0; i < inst.count; i++) { c.setRGB(ic[i * 3], ic[i * 3 + 1], ic[i * 3 + 2]); im.setColorAt(i, c); }
          im.instanceColor.needsUpdate = true;
        }
        im.computeBoundingSphere?.();
        im.userData.packed = true;
        this.root.add(im);
        this.triCount += (pos.length / 9) * inst.count;
      }
    }

    // ---- NURBS control mesh ----
    // The surface itself was already subdivided into polygons on the backend; drawn here are the control-point lattice and hull lines.
    // Houdini displays it the same way: the solid is the surface, the dashed is the hull.
    if (A.h_position) {
      if (A.h_edges) {
        const hg = new T.BufferGeometry();
        hg.setAttribute("position", new T.BufferAttribute(A.h_position, 3));
        hg.setIndex(new T.BufferAttribute(A.h_edges, 1));
        const hl2 = new T.LineSegments(hg, new T.LineBasicMaterial({
          color: 0xd8a24a, transparent: true, opacity: 0.55,
          depthWrite: false, fog: false }));
        hl2.renderOrder = 2;
        this.root.add(hl2);
      }
      const hp = new T.BufferGeometry();
      hp.setAttribute("position", new T.BufferAttribute(A.h_position, 3));
      this.root.add(new T.Points(hp, new T.PointsMaterial({
        size: 6 * (window.devicePixelRatio || 1), sizeAttenuation: false,
        map: pointTexture(T), alphaTest: 0.5, color: 0xf0b350,
        depthTest: false, fog: false })));
    }

    // ---- template layer: Houdini's template display ----
    // Thin gray lines, not shaded, reference only. Templates without edges (pure point clouds) degrade to gray points.
    if (A.t_position) {
      if (A.t_edges) {
        const tg = new T.BufferGeometry();
        tg.setAttribute("position", new T.BufferAttribute(A.t_position, 3));
        tg.setIndex(new T.BufferAttribute(A.t_edges, 1));
        const tl = new T.LineSegments(tg, new T.LineBasicMaterial({
          color: 0x7c8088, transparent: true, opacity: 0.55,
          depthWrite: false, fog: false }));
        tl.renderOrder = -5;          // before the main geometry, after the grid
        this.root.add(tl);
      } else {
        const tp = new T.BufferGeometry();
        tp.setAttribute("position", new T.BufferAttribute(A.t_position, 3));
        this.root.add(new T.Points(tp, new T.PointsMaterial({
          size: 3 * (window.devicePixelRatio || 1), sizeAttenuation: false,
          map: pointTexture(T), alphaTest: 0.5,
          color: 0x7c8088, fog: false })));
      }
    }

    // ---- wireframe: uses the original polygon edges, not the edges after triangulation ----
    if ((o.wireframe || wireOnly) && (A.edges || A.index)) {
      // Prefer the polygon edges sent by the backend; if absent derive a set from the triangle indices (with extra diagonals,
      // but better than drawing nothing -- this path is taken when an old cache has no edges)
      let edges = A.edges;
      if (!edges) {
        const set = new Set(), out = [];
        for (let i = 0; i < A.index.length; i += 3)
          for (let k = 0; k < 3; k++) {
            const a = A.index[i + k], b = A.index[i + (k + 1) % 3];
            const key = a < b ? a * 4294967296 + b : b * 4294967296 + a;
            if (!set.has(key)) { set.add(key); out.push(a, b); }
          }
        edges = new Uint32Array(out);
      }
      const wg = new T.BufferGeometry();
      wg.setAttribute("position", new T.BufferAttribute(A.position, 3));
      wg.setIndex(new T.BufferAttribute(edges, 1));
      this.root.add(new T.LineSegments(wg, new T.LineBasicMaterial({
        // Dark gray in overlay mode: only dark lines read as "thin" on a light surface. It used to be the light blue 0x8fa6b8,
        // whose brightness was close to the base color, so it looked thick and blurry.
        // WebGL ignores lineWidth (a desktop GL limitation), line width is always 1px, so "thickness"
        // can only be tuned through color contrast.
        color: wireOnly ? 0xc4ccd6 : 0x4e5259,
        transparent: true, opacity: wireOnly ? 1 : 0.9, fog: false })));
    }

    // ---- open polylines ----
    if (A.lines) {
      const lg = new T.BufferGeometry();
      lg.setAttribute("position", new T.BufferAttribute(A.position, 3));
      lg.setIndex(new T.BufferAttribute(A.lines, 1));
      const lineCd = cdCls === "point" && !viz;          // curves take a point Cd (Houdini does the same)
      if (lineCd) lg.setAttribute("color", new T.BufferAttribute(A.color, 3));
      // Open polylines use a neutral light gray, consistent with Houdini. They used to be bright green -- picked casually early on,
      // but saturated colors carry meaning in this palette (orange = group highlight, amber = NURBS control mesh,
      // gray = template); a curve taking a saturated color would make people think it's in some special state.
      this.root.add(new T.LineSegments(lg, new T.LineBasicMaterial({
        color: lineCd ? 0xffffff : (cdTint || 0xd2d7de), vertexColors: lineCd, fog: false })));
    }

    // ---- points ----
    // The condition for forcing points is "no other visible content", not "no faces" -- polylines have no
    // index either, but they have a lines buffer to draw; they shouldn't be treated as a point cloud, otherwise show_points
    // couldn't be turned off on polylines.
    const nothingElse = !A.index && !A.lines;
    if (o.show_points || nothingElse) {
      const pg = new T.BufferGeometry();
      pg.setAttribute("position", new T.BufferAttribute(A.position, 3));
      // Point colours (Cd or a visualized point attribute) only when the points ARE the geometry (a point cloud).
      // On a mesh or a curve the markers are an overlay, as in Houdini: drawn in their own colour, otherwise red points on
      // a red surface disappear into it.
      const ptViz = nothingElse && !!(viz && viz.cls === "point");
      const ptCd = nothingElse && cdCls === "point" && !viz;   // a visualized attribute takes precedence over Cd
      if (ptViz) pg.setAttribute("color", new T.BufferAttribute(viz.colors, 3));
      if (ptCd) pg.setAttribute("color", new T.BufferAttribute(A.color, 3));
      // Colors follow Houdini: when a point cloud has nothing else to show it's small gray-white points (just "so you see something");
      // only when the user actively checks show_points are they cyan-blue and enlarged -- that means "I want to inspect points".
      const dpr_ = window.devicePixelRatio || 1;
      const on = o.show_points;
      this.root.add(new T.Points(pg, new T.PointsMaterial({
        // Screen-pixel size, visible at any distance. Multiplied by DPR because gl_PointSize uses
        // framebuffer pixels; on HiDPI screens without it they look half as big.
        size: (on ? 6 : 3.5) * dpr_, sizeAttenuation: false,
        map: pointTexture(T),
        // alphaTest rather than transparent: points still write depth and occlude each other correctly,
        // and don't take part in transparency sorting. Round edges rely on mipmap transitions; clean enough at 7px.
        alphaTest: 0.5, transparent: false,
        vertexColors: ptViz || ptCd,
        color: ptViz || ptCd ? 0xffffff : (on ? 0x39dbe0 : 0xd0d3d8),
        fog: false })));
    }

    // ---- group highlight ----
    // Following Houdini: group elements in light orange. Point groups draw orange points, face groups get a thin orange overlay mesh
    // (a separate mesh built from just the selected triangles, without touching the main mesh's vertex colors).
    const hl = this.groupMask(o.highlight);
    if (hl) {
      if (hl.cls === "prim" && !wireOnly && A.index && A.tri_corner && A.vertex_prim) {
        const keep = [];
        for (let i = 0; i < A.index.length; i += 3)
          if (hl.mask[A.vertex_prim[A.tri_corner[i]]]) keep.push(i);
        if (keep.length) {
          const pos = new Float32Array(keep.length * 9);
          let k = 0;
          for (const i of keep)
            for (let c = 0; c < 3; c++) {
              const sIdx = A.index[i + c] * 3;
              pos[k++] = A.position[sIdx];
              pos[k++] = A.position[sIdx + 1];
              pos[k++] = A.position[sIdx + 2];
            }
          const hg = new T.BufferGeometry();
          hg.setAttribute("position", new T.BufferAttribute(pos, 3));
          hg.computeVertexNormals();
          const hm = new T.Mesh(hg, new T.MeshLambertMaterial({
            color: HL, side: T.DoubleSide, transparent: true, opacity: 0.72,
            depthWrite: false, fog: false,
            polygonOffset: true, polygonOffsetFactor: -2,
            polygonOffsetUnits: -2 }));
          hm.renderOrder = 1;
          this.root.add(hm);
        }
      } else {
        // point / vertex groups: drawn as orange points on the points
        const pts = [];
        if (hl.cls === "vertex" && A.vertex_point) {
          const seen = new Set();
          for (let i = 0; i < hl.mask.length; i++)
            if (hl.mask[i]) seen.add(A.vertex_point[i]);
          for (const i of seen) pts.push(i);
        } else {
          for (let i = 0; i < hl.mask.length; i++) if (hl.mask[i]) pts.push(i);
        }
        if (pts.length) {
          const pos = new Float32Array(pts.length * 3);
          pts.forEach((p, j) => {
            pos[j * 3] = A.position[p * 3];
            pos[j * 3 + 1] = A.position[p * 3 + 1];
            pos[j * 3 + 2] = A.position[p * 3 + 2];
          });
          const hg = new T.BufferGeometry();
          hg.setAttribute("position", new T.BufferAttribute(pos, 3));
          const hp = new T.Points(hg, new T.PointsMaterial({
            size: 7 * (window.devicePixelRatio || 1), sizeAttenuation: false,
            map: pointTexture(T), alphaTest: 0.5, color: HL, fog: false }));
          hp.renderOrder = 2;
          this.root.add(hp);
        }
      }
    }

    // ---- normal visualization ----
    this.normalWarning = "";
    if (o.show_normals !== "none") {
      const cls = o.show_normals;
      const { pos, n, count } = this.anchors(cls);
      if (!pos || !n) {
        this.normalWarning = `no N attribute on ${cls}`;
      } else {
        const scale = o.normal_scale * (this.bboxSize() || 1);
        const line = new Float32Array(count * 6);
        for (let i = 0; i < count; i++) {
          for (let k = 0; k < 3; k++) {
            const a = pos[i * 3 + k];
            line[i * 6 + k] = a;
            line[i * 6 + 3 + k] = a + n[i * 3 + k] * scale;
          }
        }
        const ng = new T.BufferGeometry();
        ng.setAttribute("position", new T.BufferAttribute(line, 3));
        const col = cls === "point" ? C_POINT : cls === "vertex" ? C_VERTEX : C_PRIM;
        this.root.add(new T.LineSegments(ng,
          new T.LineBasicMaterial({ color: col, fog: false })));
      }
    }

    // ---- volumes (pcg106): smoke is ray-marched, see pcg_volume.js; iso-surfaces already came as triangles ----
    if (this.data.header.volumes) {
      for (const obj of buildVolumes(T, this.data.header, A, o)) this.root.add(obj);
    }

    this.shadingInfo = src;
    this.buildLabels();
  }

  bboxSize() {
    if (!this.bbox) return 1;
    const [mn, mx] = this.bbox;
    const s = Math.max(...[0, 1, 2].map((i) => mx[i] - mn[i]), 0);
    // A degenerate bounding box (single point, collinear points, empty geometry) is treated as 1 unit.
    // Without this safeguard niceUnit(1e-6/10) would collapse the grid step and camera distance down to the micron scale together,
    // and since zoom is multiplicative, with too small a base it could never be pulled back -- showing up as "the grid is gone and zoom does nothing".
    return s < 1e-4 ? 1 : s;
  }

  // ---------------------------------------------------- occlusion of overlay text
  //
  // Tick anchors lie on the y=0 plane without normals, so the orientation test used for indices doesn't work; occlusion has to be really tested.
  // Two paths, switched by face count:
  //   few faces  -- a Raycaster casts a ray from the camera to the anchor; a hit means occluded. Exact.
  //   many faces -- fall back to a bounding-sphere test. Conservative (the sphere is larger than the real geometry, so it occludes a bit more), but O(1).
  // The ray path is throttled to once per 100ms: the triangle test is O(faces), and without throttling large meshes would stutter.
  _occlusionReady(dpr) {
    const now = performance.now();
    if (this.mesh && this.triCount <= 10000) {
      this._useRay = now - (this._occT || 0) < 100 ? this._useRay : true;
      if (now - (this._occT || 0) >= 100) {
        this._occT = now;
        this._occCache = new Map();      // throttling: cache this round's test results
      }
      this._useRay = true;
    } else {
      this._useRay = false;
      this._occCache = null;
    }
  }

  _occluded(x, y, z) {
    if (!this.mesh) return false;
    const T = this.T, cam = this.camera.position;

    if (!this._useRay) {
      // Bounding sphere: whether the camera->anchor segment passes through the sphere first
      if (!this.bbox) return false;
      const [mn, mx] = this.bbox;
      const c = [0, 1, 2].map((i) => (mn[i] + mx[i]) / 2);
      const r = this.bboxSize() * 0.5;
      const dx = x - cam.x, dy = y - cam.y, dz = z - cam.z;
      const len = Math.hypot(dx, dy, dz) || 1;
      const ux = dx / len, uy = dy / len, uz = dz / len;
      const ox = cam.x - c[0], oy = cam.y - c[1], oz = cam.z - c[2];
      const b = ox * ux + oy * uy + oz * uz;
      const cc = ox * ox + oy * oy + oz * oz - r * r;
      const disc = b * b - cc;
      if (disc < 0) return false;
      const t0 = -b - Math.sqrt(disc);
      return t0 > 0 && t0 < len - r * 0.02;
    }

    const key = `${x.toFixed(3)},${y.toFixed(3)},${z.toFixed(3)}`;
    if (this._occCache && this._occCache.has(key)) return this._occCache.get(key);

    const rc = this._rc || (this._rc = new T.Raycaster());
    const d = this._od || (this._od = new T.Vector3());
    d.set(x - cam.x, y - cam.y, z - cam.z);
    const len = d.length();
    if (len < 1e-6) return false;
    d.multiplyScalar(1 / len);
    rc.set(cam, d);
    rc.near = 1e-4;
    rc.far = len * 0.999;                 // only care whether something is **before** the anchor
    const hit = rc.intersectObject(this.mesh, false).length > 0;
    if (this._occCache) this._occCache.set(key, hit);
    return hit;
  }

  // ------------------------------------------------------------ 2D overlay
  project(x, y, z, out) {
    const v = this._v.set(x, y, z).project(this.camera);
    out[0] = (v.x * 0.5 + 0.5) * this.overlay.width;
    out[1] = (0.5 - v.y * 0.5) * this.overlay.height;
    return v.z >= -1 && v.z <= 1;
  }

  drawOverlay() {
    const c = this.ctx;
    if (!c || this._overlayErr) return;
    const W = this.overlay.width, H = this.overlay.height;
    const dpr = window.devicePixelRatio || 1;
    c.clearRect(0, 0, W, H);
    if (this.uvMode) { this.drawUVOverlay(dpr); return; }
    this._v = this._v || new this.T.Vector3();

    this._occlusionReady(dpr);
    if (this.opts.show_grid !== false) this.drawGridLabels(dpr);
    this.drawHud(dpr);
    // The gate is drawn after the ticks and before the axis indicator: what it darkens is "outside the frame"; ticks belong to the frame
    // content (should be darkened), while the indicator is UI (should not be darkened)
    this.drawGate(dpr, W, H);
    this.drawGizmo(dpr, W, H);
    // Handles are guarded separately: an error there only stops the handles, without dragging down the indices / ticks overlays
    if (this.tool && !this._toolErr) {
      try {
        this.tool.update();
        this.tool.draw(c, dpr);
      } catch (err) {
        this._toolErr = true;
        console.error("[pcg.viewport] handle drawing error, handles disabled:", err);
      }
    }
    if (this.select && !this._selErr) {
      try { this.select.draw(c, dpr); } catch (err) {
        this._selErr = true;
        console.error("[pcg.viewport] selection drawing error, selection display disabled:", err);
      }
    }
  }

  // Origin + major tick coordinates. Houdini doesn't label ticks, but inside a node the view is small and there's no scale bar,
  // so without labels you can't tell how big the object is.
  drawGridLabels(dpr) {
    const c = this.ctx, u = this.unit, step = u * 10, p = [0, 0];
    // The grid is infinite; ticks are only labelled up to where the fog fades out, with a cap to avoid flooding the screen
    const n = Math.min(MAX_TICKS, Math.ceil(this.scene.fog.far / step));
    const cam = this.camera.position;
    // Ticks fade out together with the fog, otherwise a row of numbers would remain floating over the empty background far away
    const fade = (x, z) => {
      const d = Math.hypot(x - cam.x, cam.y, z - cam.z);
      const f = this.scene.fog;
      return Math.max(0, Math.min(1, 1 - (d - f.near) / (f.far - f.near)));
    };
    c.font = `${Math.round(10 * dpr)}px ui-monospace, monospace`;
    c.textAlign = "center";
    c.textBaseline = "middle";
    c.lineJoin = "round";
    c.lineWidth = 2.2 * dpr;
    c.strokeStyle = "rgba(6,7,10,0.8)";

    for (let i = -n; i <= n; i++) {
      if (i === 0) continue;
      const v = i * step;
      let a = fade(v, 0);
      if (a > 0.05 && !this._occluded(v, 0, 0)) {
        c.fillStyle = `rgba(224,87,91,${(a * 0.85).toFixed(2)})`;    // X axis
        if (this.project(v, 0, 0, p)) {
          c.strokeText(fmtCoord(v, u), p[0], p[1] - 7 * dpr);
          c.fillText(fmtCoord(v, u), p[0], p[1] - 7 * dpr);
        }
      }
      a = fade(0, v);
      if (a > 0.05 && !this._occluded(0, 0, v)) {
        c.fillStyle = `rgba(91,143,224,${(a * 0.85).toFixed(2)})`;   // Z axis
        if (this.project(0, 0, v, p)) {
          c.strokeText(fmtCoord(v, u), p[0], p[1] - 7 * dpr);
          c.fillText(fmtCoord(v, u), p[0], p[1] - 7 * dpr);
        }
      }
    }

    // origin
    if (!this._occluded(0, 0, 0) && this.project(0, 0, 0, p)) {
      const r = 3 * dpr;
      c.strokeStyle = "#e8e8ee"; c.lineWidth = 1.2 * dpr;
      c.beginPath();
      c.moveTo(p[0] - r, p[1]); c.lineTo(p[0] + r, p[1]);
      c.moveTo(p[0], p[1] - r); c.lineTo(p[0], p[1] + r);
      c.stroke();
      c.fillStyle = "#e8e8ee";
      c.fillText("0", p[0] + 9 * dpr, p[1] + 8 * dpr);
    }

  }

  // -------------------------------------------------- indices (GPU billboard)
  //
  // The geometry is **completely static**: one quad per glyph, the position of all four vertices equals the anchor world coordinates
  // of its element, and orientation and size are computed by the vertex shader in view space. So however the camera moves,
  // the CPU doesn't write a single float -- the previous version recomputed 2.17 million vertex components every frame.
  //
  // Occlusion also changed from a "normal orientation heuristic" to **a real depth test**: the quad sits at the element's position,
  // so with depthTest on, indices on the back are naturally hidden by the mesh, and concave self-occlusion is correct too. To avoid
  // z-fighting with the surface, it's offset by one glyph height toward the camera in view space.
  //
  // Finding from probing: three rewrites GLSL1 shaders into ESSL3, so fwidth / the various built-ins
  // all work; **do not** hand-write #extension (that extension isn't even exposed in a WebGL2 context).
  buildLabels() {
    this._dirty = true;
    const T = this.T, o = this.opts;
    if (this.labelMesh) {
      this.labelMesh.geometry.dispose();
      this.labelMesh.material.dispose();
      this.scene.remove(this.labelMesh);
      this.labelMesh = null;
    }
    this.labelInfo = null;
    this.labelWarning = "";
    if (!T || !this.data || o.numbers === "none") return;

    const { pos, count } = this.anchors(o.numbers);
    if (!pos || !count) return;
    if (count > LABEL_LIMIT) {
      this.labelWarning = `${count} elements is too many, indices turned off (limit ${LABEL_LIMIT})`;
      return;
    }

    let nq = 0;
    for (let i = 0; i < count; i++) {
      let d = 1, t = i;
      while (t >= 10) { t = (t / 10) | 0; d++; }
      nq += d;
    }

    const P = new Float32Array(nq * 12);      // anchor, repeated for four vertices
    const corner = new Float32Array(nq * 8);  // quad corner (-1..1)
    const colv = new Float32Array(nq * 4);    // position of the character in the string
    const uv = new Float32Array(nq * 8);
    const idx = new Uint32Array(nq * 6);
    const CN = [-1, -1, 1, -1, 1, 1, -1, 1];
    let q = 0;
    for (let i = 0; i < count; i++) {
      const str = String(i), L = str.length;
      const ax = pos[i * 3], ay = pos[i * 3 + 1], az = pos[i * 3 + 2];
      for (let c = 0; c < L; c++) {
        const d = str.charCodeAt(c) - 48;
        const col = c - (L - 1) * 0.5;
        for (let v = 0; v < 4; v++) {
          const o3 = (q * 4 + v) * 3;
          P[o3] = ax; P[o3 + 1] = ay; P[o3 + 2] = az;
          corner[(q * 4 + v) * 2] = CN[v * 2];
          corner[(q * 4 + v) * 2 + 1] = CN[v * 2 + 1];
          colv[q * 4 + v] = col;
        }
        const u0 = d / GLYPH_N, u1 = (d + 1) / GLYPH_N;
        uv.set([u0, 0, u1, 0, u1, 1, u0, 1], q * 8);
        const v0 = q * 4;
        idx.set([v0, v0 + 1, v0 + 2, v0, v0 + 2, v0 + 3], q * 6);
        q++;
      }
    }

    const g = new T.BufferGeometry();
    g.setAttribute("position", new T.BufferAttribute(P, 3));
    g.setAttribute("aCorner", new T.BufferAttribute(corner, 2));
    g.setAttribute("aCol", new T.BufferAttribute(colv, 1));
    g.setAttribute("uv", new T.BufferAttribute(uv, 2));
    g.setIndex(new T.BufferAttribute(idx, 1));

    const css = o.numbers === "point" ? CSS_POINT
              : o.numbers === "vertex" ? CSS_VERTEX : CSS_PRIM;
    const GA = glyphAtlas(T, this.renderer);
    this.labelUniforms = {
      uMap: { value: GA.tex },
      uColor: { value: new T.Color(css) },
      uHalo: { value: new T.Color(0x0a0c10) },
      uPxScale: { value: 0.01 },
      uHalfW: { value: GA.halfW },
      uAdv: { value: GA.adv },
    };
    const mat = new T.ShaderMaterial({
      uniforms: this.labelUniforms,
      transparent: true,
      depthWrite: false,
      side: T.DoubleSide,
      vertexShader: `
        attribute vec2 aCorner;
        attribute float aCol;
        uniform float uPxScale, uHalfW, uAdv;
        varying vec2 vUv;
        void main() {
          vec4 mv = modelViewMatrix * vec4(position, 1.0);
          float h = -mv.z * uPxScale;          // world size of half a glyph height, constant on screen
          // Spacing uses the real advance; the quad is slightly wider (including stroke margin), so adjacent glyphs overlap slightly
          mv.x += aCol * uAdv * 2.0 * h + aCorner.x * uHalfW * h;
          mv.y += aCorner.y * h;
          mv.z += h * 2.0;                     // offset slightly toward the camera to avoid z-fighting
          vUv = uv;
          gl_Position = projectionMatrix * mv;
        }`,
      fragmentShader: `
        uniform sampler2D uMap;
        uniform vec3 uColor, uHalo;
        varying vec2 vUv;
        void main() {
          vec3 t = texture2D(uMap, vUv).rgb;
          float core = t.r, halo = t.g;         // separate channels: glyph core / outline
          float a = max(core, halo);
          if (a < 0.25) discard;
          gl_FragColor = vec4(mix(uHalo, uColor, core), a);
        }`,
    });
    this.labelMesh = new T.Mesh(g, mat);
    this.labelMesh.frustumCulled = false;
    this.labelMesh.renderOrder = 5;
    this.scene.add(this.labelMesh);
    this.labelInfo = { count, nq };
    this.updateLabelScale();
  }

  // Only update a uniform when fov / viewport height changes. Camera moves don't need to touch it at all.
  updateLabelScale() {
    if (!this.labelUniforms) return;
    const cam = this.camera;
    const px = 14;                             // on-screen glyph height (CSS pixels)
    this.labelUniforms.uPxScale.value =
      Math.tan((cam.fov * Math.PI / 180) / 2) * px / Math.max(1, this._h || 1);
  }

  // Top-left info bar. **No outline** -- it's in a corner, almost always over the background,
  // and outlining small text only blurs it.
  drawHud(dpr) {
    const c = this.ctx, u = this.unit;
    c.font = `${Math.round(11 * dpr)}px ui-monospace, monospace`;
    c.textAlign = "left";
    c.textBaseline = "middle";
    c.fillStyle = "#aeb6c0";
    c.fillText(`grid ${fmtCoord(u, u)} / ${fmtCoord(u * 10, u)}`, 8 * dpr, 13 * dpr);
    c.fillStyle = "rgba(150,158,168,0.75)";
    c.fillText("LMB tumble · MMB track · RMB/wheel dolly · F frame · 1234 views · 5 UV",
               8 * dpr, 29 * dpr);
    if (this.vizLegend) {
      c.fillStyle = "#8fd4a0";
      c.fillText(`viz  ${this.vizLegend}`, 8 * dpr, 45 * dpr);
    }
    const warn = [this.normalWarning, this.labelWarning, this.uvWarning].filter(Boolean).join("  ·  ");
    if (warn) {
      c.fillStyle = "#d9a441";
      c.fillText(warn, 8 * dpr, (this.vizLegend ? 61 : 45) * dpr);
    }
  }

  // Axis indicator at top right. No separate scene/viewport; the three basis vectors are transformed directly into
  // camera space and the xy components drawn as screen directions -- cheap, and the text is 2D so always crisp.
  drawGizmo(dpr, W, H) {
    const c = this.ctx;
    const cx = W - 34 * dpr, cy = 34 * dpr, len = 20 * dpr;
    const m = this.camera.matrixWorldInverse;
    const items = AX.map((a) => {
      const d = this._v.set(a.v[0], a.v[1], a.v[2]).transformDirection(m).clone();
      return { ...a, dx: d.x * len, dy: -d.y * len, z: d.z };
    }).sort((a, b) => a.z - b.z);          // those pointing away are drawn first, covered by the front ones

    c.lineWidth = 1.6 * dpr;
    c.font = `bold ${Math.round(9 * dpr)}px ui-monospace, monospace`;
    c.textAlign = "center";
    c.textBaseline = "middle";
    for (const it of items) {
      const far = it.z < 0;                // pointing away from the camera: dimmed
      c.globalAlpha = far ? 0.4 : 1;
      c.strokeStyle = it.css;
      c.beginPath();
      c.moveTo(cx, cy); c.lineTo(cx + it.dx, cy + it.dy);
      c.stroke();
      c.fillStyle = it.css;
      c.beginPath();
      c.arc(cx + it.dx, cy + it.dy, 6 * dpr, 0, Math.PI * 2);
      c.fill();
      c.fillStyle = far ? "#c8ccd4" : "#14151a";
      c.fillText(it.label, cx + it.dx, cy + it.dy + 0.5 * dpr);
    }
    c.globalAlpha = 1;
  }

  // ------------------------------------------------------- camera controls
  //
  // Keys follow Houdini's Space+ scheme, but no modifier is required (there's no select tool here,
  // no need to reserve LMB):
  //   LMB drag   tumble
  //   MMB drag   track
  //   RMB drag / wheel  dolly
  //   holding Alt or Space keeps the same mapping, for muscle memory
  //   F / G / H / Home  frame all
  //   1 2 3 4  perspective / top / front / right
  //   5        UV view (pan / zoom only; 5 again or 1-4 return to 3D)
  bindInput() {
    const el = this.renderer.domElement;
    const T = this.T;
    let drag = null;
    // any input over the viewport may change what is drawn (hover highlights of the handles, drags, wheel)
    const inv = () => { this._dirty = true; };
    for (const ev of ["pointerdown", "pointermove", "pointerup", "wheel", "pointerleave"])
      el.addEventListener(ev, inv, { passive: true });

    el.addEventListener("contextmenu", (e) => e.preventDefault());

    const begin = (e) => {
      drag = { x: e.clientX, y: e.clientY, btn: e.button };
      try { el.setPointerCapture?.(e.pointerId); } catch (_) { /* synthetic events have no pointerId */ }
    };
    // Handles (pcg103): left button first asks the tool whether it wants it; Alt / Space + left is always tumble (Houdini's habit)
    const local = (e) => {
      const r = el.getBoundingClientRect();
      return [e.clientX - r.left, e.clientY - r.top];
    };
    let toolDrag = false;
    let selDrag = false;
    const moveBy = (e) => {
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      drag.x = e.clientX; drag.y = e.clientY;
      if (this.uvMode) {
        if (drag.btn === 2) this.uvZoom(dx + dy);
        else this.uvPan(dx, dy);
        return;
      }
      if (drag.btn === 0) this.tumble(dx, dy);
      else if (drag.btn === 1) this.track(dx, dy);
      else this.dolly(dx + dy);
    };

    el.addEventListener("pointerdown", (e) => {
      // The preventDefault below keeps focus where it was -- often a toolbar <select> of the floating panel, which
      // then swallowed the view keys (1-5). Clicking into the view releases a focused control.
      const fa = document.activeElement;
      if (fa && fa !== document.body && /^(SELECT|BUTTON|INPUT|TEXTAREA)$/.test(fa.tagName)) fa.blur?.();
      // select mode takes the left button (Alt / Space + left still tumbles)
      if (e.button === 0 && !e.altKey && !this._space && this.select?.active && !this.uvMode) {
        const [x, y] = local(e);
        if (this.select.pointerDown(e, x, y)) {
          selDrag = true;
          try { el.setPointerCapture?.(e.pointerId); } catch (_) { /* synthetic events */ }
          e.preventDefault(); e.stopPropagation();
          return;
        }
      }
      if (e.button === 0 && !e.altKey && !this._space && this.tool && !this.uvMode) {
        const [x, y] = local(e);
        let took = false;
        try { took = this.tool.pointerDown(e, x, y); } catch (err) {
          console.error("[pcg.viewport] handle error:", err);
        }
        if (took) {
          toolDrag = true;
          try { el.setPointerCapture?.(e.pointerId); } catch (_) { /* synthetic events */ }
          e.preventDefault(); e.stopPropagation();
          return;
        }
      }
      begin(e);
      e.preventDefault(); e.stopPropagation();   // don't let litegraph drag the node / pop up its menu
    });

    el.addEventListener("pointermove", (e) => {
      this.hover = true;
      if (selDrag) {
        const [x, y] = local(e);
        this.select.pointerMove(e, x, y);
        e.stopPropagation();
        return;
      }
      if (this.tool && !this.uvMode && (toolDrag || !drag)) {
        const [x, y] = local(e);
        let took = false;
        try { took = this.tool.pointerMove(e, x, y); } catch (err) {
          console.error("[pcg.viewport] handle error:", err);
        }
        el.style.cursor = this.tool.cursor() || "";
        if (toolDrag || took) { e.stopPropagation(); return; }
      }
      if (!drag) return;
      moveBy(e);
      e.stopPropagation();
    });

    const stop = (e) => {
      if (selDrag) {
        selDrag = false;
        const [x, y] = local(e);
        try { this.select.pointerUp(e, x, y); } catch (err) { console.error("[pcg.viewport] selection error:", err); }
      }
      if (toolDrag) {
        toolDrag = false;
        try { this.tool?.pointerUp(e); } catch (err) { console.error("[pcg.viewport] handle error:", err); }
      }
      drag = null; e.stopPropagation();
    };
    el.addEventListener("pointerup", stop);
    el.addEventListener("pointercancel", stop);

    // ── The middle button (track) must be caught in the **capture** phase on window.
    // So that "middle-drag pans the canvas even when the mouse is over a DOM widget", the ComfyUI frontend listens for the middle button in the capture phase
    // on ancestor elements / the document and forwards the event to the canvas. The capture phase travels down from window, before our listener on the canvas
    // -- the stopPropagation above is in the bubble phase, too late; the canvas has already started panning.
    // So middle-button down / move / up are all handled in the window capture phase, with
    // stopImmediatePropagation, so the frontend never sees this middle drag. Only middle presses landing on this viewport are handled;
    // middle presses elsewhere still pan the canvas. Left / right buttons don't have this problem and are left alone
    const mine = (e) => el.isConnected && e.target instanceof Node && el.contains(e.target);
    const eat = (e) => { e.preventDefault(); e.stopImmediatePropagation(); };
    this._onCapDown = (e) => {
      if (e.button !== 1 || !mine(e)) return;
      begin(e);
      eat(e);
    };
    this._onCapMove = (e) => {
      if (!drag || drag.btn !== 1) return;
      moveBy(e);
      eat(e);
    };
    this._onCapUp = (e) => {
      if (!drag || drag.btn !== 1) return;
      drag = null;
      eat(e);
    };
    // Also swallow the middle button's compatibility mouse events (mousedown / auxclick): otherwise the browser shows the autoscroll
    // icon, and older frontends also listen to mousedown
    this._onCapMouse = (e) => { if (e.button === 1 && mine(e)) eat(e); };
    window.addEventListener("pointerdown", this._onCapDown, true);
    window.addEventListener("pointermove", this._onCapMove, true);
    window.addEventListener("pointerup", this._onCapUp, true);
    window.addEventListener("pointercancel", this._onCapUp, true);
    window.addEventListener("mousedown", this._onCapMouse, true);
    window.addEventListener("auxclick", this._onCapMouse, true);

    el.addEventListener("wheel", (e) => {
      if (this.uvMode) {
        const [x, y] = local(e);
        this.uvZoom(e.deltaY > 0 ? 8 : -8, x, y);
      } else this.dolly(e.deltaY > 0 ? 8 : -8);
      e.preventDefault(); e.stopPropagation();
    }, { passive: false });

    el.addEventListener("dblclick", (e) => { this.frameAll(); e.stopPropagation(); });
    this.container.addEventListener("pointerenter", () => { this.hover = true; });
    this.container.addEventListener("pointerleave", () => { this.hover = false; });

    // The keyboard listener is on window and only responds while the pointer hovers. No tabindex to steal focus --
    // stealing it would break ComfyUI's own shortcuts and input boxes.
    this._onKey = (e) => {
      if (!this.hover) return;
      // Only typing targets keep their keys. A focused <select> / button / checkbox does not: the floating panel's
      // toolbar keeps focus after a pick, and skipping SELECT made 1-4 silently do nothing there.
      if (isTypingTarget(e.target)) return;
      if (e.key === " ") { this._space = true; return; }
      if (!this.uvMode && this.select?.key?.(e)) { e.preventDefault(); e.stopPropagation(); return; }
      if (!this.uvMode && this.tool?.key?.(e)) { e.preventDefault(); e.stopPropagation(); return; }
      if (e.ctrlKey || e.metaKey) return;
      const k = e.key.toLowerCase();
      let hit = true;
      if (k === "f" || k === "g" || k === "h" || k === "home") this.frameAll();
      else if (k === "1") { this.setUVMode(false); this.setView(0.7, 1.1); }
      else if (k === "2") { this.setUVMode(false); this.setView(0, 0.02); }           // top view
      else if (k === "3") { this.setUVMode(false); this.setView(0, Math.PI / 2); }    // front (+Z looking at the origin)
      else if (k === "4") { this.setUVMode(false); this.setView(Math.PI / 2, Math.PI / 2); }  // right view
      else if (k === "5") this.setUVMode(!this.uvMode);                               // UV view (5 again: back)
      else hit = false;
      if (hit) { e.preventDefault(); e.stopPropagation(); }
    };
    window.addEventListener("keydown", this._onKey, true);
    this._onKeyUp = (e) => { if (e.key === " ") this._space = false; };
    window.addEventListener("keyup", this._onKeyUp, true);
  }

  // ------------------------------------------------- camera adapter for the handles (pcg103)
  // Coordinates are always canvas CSS pixels (origin at top left), matching pointer events minus the canvas top-left
  size() {
    const el = this.renderer?.domElement;
    return [el?.clientWidth || this.container.clientWidth || 1,
            el?.clientHeight || this.container.clientHeight || 1];
  }
  screen(p) {
    const v = (this._sv || (this._sv = new this.T.Vector3())).set(p[0], p[1], p[2])
      .project(this.camera);
    if (!(v.z > -1 && v.z < 1)) return null;
    const [w, h] = this.size();
    return [(v.x * 0.5 + 0.5) * w, (0.5 - v.y * 0.5) * h];
  }
  ray(x, y) {
    const [w, h] = this.size();
    const v = new this.T.Vector3(x / w * 2 - 1, 1 - y / h * 2, 0.5).unproject(this.camera);
    const o = this.camera.position;
    const d = [v.x - o.x, v.y - o.y, v.z - o.z];
    const l = Math.hypot(d[0], d[1], d[2]) || 1;
    return { o: [o.x, o.y, o.z], d: [d[0] / l, d[1] / l, d[2] / l] };
  }
  viewDir() {
    const d = new this.T.Vector3();
    this.camera.getWorldDirection(d);
    return [d.x, d.y, d.z];
  }
  worldPerPx(p) {
    const c = this.camera.position, vd = this.viewDir();
    const depth = Math.max(1e-6, (p[0] - c.x) * vd[0] + (p[1] - c.y) * vd[1] + (p[2] - c.z) * vd[2]);
    return 2 * depth * Math.tan((this.camera.fov * Math.PI / 180) / 2) / this.size()[1];
  }
  gridStep() { return this.unit || 1; }
  // selection helpers (pcg122): is a world point hidden behind the surface? which primitive is under the pixel?
  hiddenPoint(x, y, z) {
    if (!this.mesh) return false;
    const T = this.T, cam = this.camera.position;
    const rc = this._hrc || (this._hrc = new T.Raycaster());
    const d = new T.Vector3(x - cam.x, y - cam.y, z - cam.z);
    const len = d.length();
    if (len < 1e-9) return false;
    d.multiplyScalar(1 / len);
    rc.set(cam, d);
    rc.near = 0;
    rc.far = len * (1 - 1e-3) - this.bboxSize() * 1e-4;
    return rc.intersectObject(this.mesh, false).length > 0;
  }
  pickPrim(x, y) {
    const A = this.data?.arrays;
    if (!this.mesh || !A?.tri_corner || !A?.vertex_prim) return -1;
    const T = this.T, r = this.ray(x, y);
    const rc = this._prc2 || (this._prc2 = new T.Raycaster());
    rc.set(new T.Vector3(...r.o), new T.Vector3(...r.d));
    rc.near = 0; rc.far = Infinity;
    const hit = rc.intersectObject(this.mesh, false)[0];
    if (!hit || hit.faceIndex == null) return -1;
    const c = A.tri_corner[hit.faceIndex * 3];
    return c === undefined ? -1 : A.vertex_prim[c];
  }
  pickSurface(o, d) {
    if (!this.mesh) return null;
    const T = this.T;
    const rc = this._prc || (this._prc = new T.Raycaster());
    rc.set(new T.Vector3(o[0], o[1], o[2]), new T.Vector3(d[0], d[1], d[2]));
    rc.near = 0; rc.far = Infinity;
    const hit = rc.intersectObject(this.mesh, false)[0];
    return hit ? [hit.point.x, hit.point.y, hit.point.z] : null;
  }

  tumble(dx, dy) {
    this.orbit.theta -= dx * 0.008;
    this.orbit.phi = Math.max(0.02, Math.min(Math.PI - 0.02,
      this.orbit.phi - dy * 0.008));
  }

  // Track using the camera's own right / up, so the object follows the mouse 1:1.
  // It used to derive the direction from theta only, and with a steep top-down angle it didn't follow at all.
  track(dx, dy) {
    const T = this.T, cam = this.camera;
    const h = this.container.clientHeight || 1;
    const s = 2 * this.orbit.dist * Math.tan((cam.fov * Math.PI / 180) / 2) / h;
    const right = new T.Vector3().setFromMatrixColumn(cam.matrix, 0);
    const up = new T.Vector3().setFromMatrixColumn(cam.matrix, 1);
    for (let i = 0; i < 3; i++)
      this.orbit.target[i] += -right.getComponent(i) * dx * s
                            + up.getComponent(i) * dy * s;
  }

  dolly(d) {
    this.orbit.dist = Math.max(1e-4, this.orbit.dist * Math.exp(d * 0.012));
  }

  setView(theta, phi) {
    this.orbit.theta = theta;
    this.orbit.phi = phi;
  }

  // ------------------------------------------------------------ UV view (key 5, pcg114)
  //
  // An orthographic look at the uv layout, like Houdini's UV viewport: the 0-1 tile with a 0.1 grid and the
  // neighbouring tiles fainter, faces filled translucent (overlaps read darker, mirrored / folded faces in red) and
  // the polygon edges in uv space. Its own scene and camera; the 3D orbit is kept, so 1-4 return to where you were.
  setUVMode(on) {
    on = !!on;
    if (on === !!this.uvMode) return;
    this.uvMode = on;
    if (on && !this.uvCam) this.frameUV();
  }

  buildUV() {
    this._dirty = true;
    const T = this.T;
    if (!T) return;
    this._uvDirty = false;
    if (!this.uvScene) {
      this.uvScene = new T.Scene();
      this.uvScene.background = new T.Color(BG);
      this.uvCamera = new T.OrthographicCamera(-1, 1, 1, -1, -10, 10);
      this.uvCamera.position.set(0, 0, 1);
      // Tile grid, built once: integer lines over -2..3, 0.1 lines inside the 0-1 tile, the 0-1 border on top
      const seg = (arr, color, opacity, order) => {
        const g = new T.BufferGeometry();
        g.setAttribute("position", new T.BufferAttribute(new Float32Array(arr), 3));
        const l = new T.LineSegments(g, new T.LineBasicMaterial({
          color, transparent: true, opacity, depthTest: false, depthWrite: false }));
        l.renderOrder = order;
        this.uvScene.add(l);
      };
      const tiles = [], fine = [];
      for (let i = -2; i <= 3; i++) tiles.push(i, -2, 0, i, 3, 0, -2, i, 0, 3, i, 0);
      for (let i = 1; i < 10; i++) fine.push(i / 10, 0, 0, i / 10, 1, 0, 0, i / 10, 0, 1, i / 10, 0);
      seg(tiles, 0x4a505a, 0.6, 0);
      seg(fine, 0x3a3f48, 0.9, 0);
      seg([0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 1, 0, 1, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0], 0x9aa3ae, 1, 1);
      this.uvGroup = new T.Group();
      this.uvScene.add(this.uvGroup);
    }
    while (this.uvGroup.children.length) {
      const c = this.uvGroup.children.pop();
      c.geometry?.dispose(); c.material?.dispose();
    }
    const L = this.data ? uvLayout(this.data) : null;
    this.uvInfo = L;
    if (!L) return;
    if (L.nTri) {
      const g = new T.BufferGeometry();
      g.setAttribute("position", new T.BufferAttribute(L.tri, 3));
      g.setAttribute("color", new T.BufferAttribute(L.col, 3));
      const m = new T.Mesh(g, new T.MeshBasicMaterial({
        vertexColors: true, transparent: true, opacity: 0.32, side: T.DoubleSide,
        depthTest: false, depthWrite: false }));
      m.renderOrder = 2;
      this.uvGroup.add(m);
    }
    if (L.edges.length) {
      const g = new T.BufferGeometry();
      g.setAttribute("position", new T.BufferAttribute(L.edges, 3));
      const l = new T.LineSegments(g, new T.LineBasicMaterial({
        color: 0xd8dde4, transparent: true, opacity: 0.85, depthTest: false, depthWrite: false }));
      l.renderOrder = 3;
      this.uvGroup.add(l);
    }
  }

  // Frame the uv bbox together with the 0-1 tile (so a layout far off the tile still shows where the tile is)
  frameUV() {
    if (this._uvDirty || !this.uvScene) this.buildUV();
    const b = this.uvInfo?.bbox;
    const u0 = Math.min(0, b ? b[0] : 0), v0 = Math.min(0, b ? b[1] : 0);
    const u1 = Math.max(1, b ? b[2] : 1), v1 = Math.max(1, b ? b[3] : 1);
    const [w, h] = this.size();
    const half = Math.max((v1 - v0) / 2, (u1 - u0) / 2 / Math.max(w / h, 1e-6)) * 1.25;
    // nudged up a little so the top of the layout clears the info bar
    this.uvCam = { cx: (u0 + u1) / 2, cy: (v0 + v1) / 2 + half * 0.08, h: half };
  }

  uvPan(dx, dy) {
    const c = this.uvCam, s = (2 * c.h) / this.size()[1];
    c.cx -= dx * s;
    c.cy += dy * s;
  }

  // Zoom about a screen point (canvas CSS px); without one, about the centre. The point under the cursor stays put.
  uvZoom(d, x, y) {
    const c = this.uvCam, [w, h] = this.size();
    const f = Math.exp(d * 0.012);
    const nh = Math.min(1e4, Math.max(1e-5, c.h * f));
    if (x != null) {
      const s0 = (2 * c.h) / h, s1 = (2 * nh) / h;
      c.cx += (x - w / 2) * (s0 - s1);
      c.cy -= (y - h / 2) * (s0 - s1);
    }
    c.h = nh;
  }

  // canvas CSS px -> uv, and back
  uvAt(x, y) {
    const c = this.uvCam, [w, h] = this.size(), s = (2 * c.h) / h;
    return [c.cx + (x - w / 2) * s, c.cy - (y - h / 2) * s];
  }
  uvScreen(u, v) {
    const c = this.uvCam, [w, h] = this.size(), s = h / (2 * c.h);
    return [w / 2 + (u - c.cx) * s, h / 2 - (v - c.cy) * s];
  }

  renderUV(w, h) {
    if (this._uvDirty || !this.uvScene) this.buildUV();
    if (!this.uvCam) this.frameUV();
    const c = this.uvCam, a = w / h, cam = this.uvCamera;
    cam.left = c.cx - c.h * a; cam.right = c.cx + c.h * a;
    cam.top = c.cy + c.h; cam.bottom = c.cy - c.h;
    cam.updateProjectionMatrix();
    this.renderer.render(this.uvScene, cam);
  }

  drawUVOverlay(dpr) {
    const c = this.ctx, [w, h] = this.size();
    c.font = `${Math.round(11 * dpr)}px ui-monospace, monospace`;
    // tile coordinates along the bottom and the left edge
    c.fillStyle = "rgba(170,178,188,0.8)";
    const [ua, va] = this.uvAt(0, h), [ub, vb] = this.uvAt(w, 0);
    const span = Math.max(ub - ua, 1e-9), step = Math.pow(10, Math.ceil(Math.log10(span / 6)));
    c.textAlign = "center"; c.textBaseline = "bottom";
    for (let u = Math.ceil(ua / step) * step; u <= ub; u += step)
      c.fillText(+u.toFixed(3) + "", this.uvScreen(u, 0)[0] * dpr, (h - 4) * dpr);
    c.textAlign = "left"; c.textBaseline = "middle";
    for (let v = Math.ceil(va / step) * step; v <= vb; v += step)
      c.fillText(+v.toFixed(3) + "", 4 * dpr, this.uvScreen(0, v)[1] * dpr);
    // info bar
    c.fillStyle = "#aeb6c0";
    const L = this.uvInfo;
    c.fillText(L ? `UV  ${L.cls} uv · ${L.nTri} tris` : "UV  no uv attribute", 8 * dpr, 13 * dpr);
    c.fillStyle = "rgba(150,158,168,0.75)";
    c.fillText("LMB/MMB pan · RMB/wheel zoom · F frame · 1-4 back to 3D", 8 * dpr, 29 * dpr);
    if (L && L.flipped) {
      c.fillStyle = "#e0685f";
      c.fillText(`${L.flipped} flipped (mirrored or folded) tris in red`, 8 * dpr, 45 * dpr);
    }
  }

  // ------------------------------------------------------- linking with camera nodes
  //
  // Both directions are needed, and they must use **the same spherical-coordinate convention** -- otherwise the camera position written back by
  // "Lock Camera to View" differs from what you see by an axis, and since both sides are "plausible-looking" angles it's hard to tell
  // at a glance which side is wrong. The convention is orbit_eye in geo/render.py:
  //     eye = target + d·(cos(elev)·sin(azim), sin(elev), cos(elev)·cos(azim))
  // phi here is the polar angle measured from +Y, so elev = 90° − phi, azim = theta.

  /** Current view -> camera parameters (world space). For "Lock Camera to View". */
  getCameraState() {
    const { theta, phi, dist, target } = this.orbit;
    return {
      eye: [target[0] + dist * Math.sin(phi) * Math.sin(theta),
            target[1] + dist * Math.cos(phi),
            target[2] + dist * Math.sin(phi) * Math.cos(theta)],
      target: [...target],
      up: [0, 1, 0],
      fov: this.fov,
      distance: dist,
      elev: 90 - phi * 180 / Math.PI,
      azim: theta * 180 / Math.PI,
    };
  }

  /**
   * Camera parameters -> view. For "look through camera".
   *
   * up is **ignored**: in this viewport's spherical coordinates the camera is always upright (up = +Y) and can't express
   * roll. A tilted camera seen here lacks the roll -- rather than silently drawing it wrong,
   * the panel says so directly (see pcg_display.js).
   */
  setCameraState(cam) {
    if (!cam) return false;
    const t = cam.target || [0, 0, 0];
    const e = cam.eye || [0, 0, 1];
    const v = [e[0] - t[0], e[1] - t[1], e[2] - t[2]];
    const d = Math.hypot(v[0], v[1], v[2]);
    if (!(d > 1e-9)) return false;            // camera position coincides with the target: orientation undefined
    this.orbit.target = [t[0], t[1], t[2]];
    this.orbit.dist = d;
    this.orbit.phi = Math.acos(Math.max(-1, Math.min(1, v[1] / d)));
    this.orbit.theta = Math.atan2(v[0], v[2]);
    if (Number.isFinite(cam.fov) && cam.fov > 0) this.fov = cam.fov;
    this.updateGridScale();
    return true;
  }

  /** Resolution gate: { xres, yres, label }, or null to turn it off. */
  setGate(gate) {
    this.gate = (gate && gate.xres > 0 && gate.yres > 0) ? gate : null;
  }

  /**
   * Gate rectangle (CSS pixels, relative to the container's top left).
   *
   * Shrinking to 92% is deliberate: the gate must be **entirely** inside the viewport, with a band "outside the frame" around it so you can see
   * what gets cropped -- flush with the edge it would coincide with the viewport border, as if not drawn.
   */
  gateRect(w, h) {
    const a = this.gate.xres / this.gate.yres;
    let gw = w * 0.92;
    let gh = gw / a;
    if (gh > h * 0.92) { gh = h * 0.92; gw = gh * a; }
    return { x: (w - gw) / 2, y: (h - gh) / 2, w: gw, h: gh };
  }

  /**
   * The image inside the gate must **exactly match** the render, so the viewport fov is derived back from the gate height,
   * rather than using the camera's fov directly:
   *
   *     tan(viewport fov/2) / tan(camera fov/2) = viewport height / gate height
   *
   * Using the camera fov directly, the view inside the gate would be **narrower** than the actual render (the gate is shorter than the viewport),
   * and the framing would mislead -- subtly so: proportions are right, only the extent is a little smaller; without overlaying the render
   * you'd never notice.
   *
   * In project() of geo/render.py fov is **vertical** (ndy is divided by tan(fov/2)),
   * and three's PerspectiveCamera.fov is vertical too, so the two correspond directly.
   */
  effectiveFov(w, h) {
    if (!this.gate || !(h > 0)) return this.fov;
    const g = this.gateRect(w, h);
    const half = Math.tan(this.fov * Math.PI / 360) * h / Math.max(1, g.h);
    return Math.min(175, Math.atan(half) * 360 / Math.PI);
  }

  drawGate(dpr, W, H) {
    if (!this.gate) return;
    const c = this.ctx;
    const g = this.gateRect(W / dpr, H / dpr);
    const x = g.x * dpr, y = g.y * dpr, w = g.w * dpr, h = g.h * dpr;
    // Darken outside the frame. Four rectangles rather than "darken the whole screen and cut a hole" -- the latter needs
    // globalCompositeOperation, and since ticks and indices are also drawn on the overlay, the composite mode would eat them
    // too
    c.fillStyle = "rgba(8,9,12,0.55)";
    c.fillRect(0, 0, W, y);
    c.fillRect(0, y + h, W, H - y - h);
    c.fillRect(0, y, x, h);
    c.fillRect(x + w, y, W - x - w, h);
    c.strokeStyle = "rgba(74,158,255,0.85)";
    c.lineWidth = Math.max(1, dpr);
    c.strokeRect(x + 0.5 * dpr, y + 0.5 * dpr, w - dpr, h - dpr);
    const txt = this.gate.label || `${this.gate.xres}×${this.gate.yres}`;
    c.font = `${Math.round(10 * dpr)}px ui-monospace, monospace`;
    c.textAlign = "left";
    c.textBaseline = "top";
    c.lineJoin = "round";
    c.lineWidth = 2.2 * dpr;
    c.strokeStyle = "rgba(6,7,10,0.85)";
    c.strokeText(txt, x + 4 * dpr, y + 3 * dpr);
    c.fillStyle = "rgba(200,216,240,0.9)";
    c.fillText(txt, x + 4 * dpr, y + 3 * dpr);
  }

  frameAll() {
    if (this.uvMode) this.frameUV();
    if (!this.bbox) return;
    const [mn, mx] = this.bbox;
    this.orbit.target = [0, 1, 2].map((i) => (mn[i] + mx[i]) / 2);
    this.orbit.dist = this.bboxSize() * 1.9;
    this.updateGridScale();
  }

  /** Ask for a redraw on the next animation frame (the loop only draws when something changed, see loop()). */
  invalidate() { this._dirty = true; }

  // Everything the picture depends on that can change without going through rebuild(): the camera (handles and key
  // shortcuts write the orbit directly), the UV camera, fov / gate, HUD texts, and the handles (they follow the
  // selected node's parameters, which change in the panel without telling the viewport). Cheap: a few dozen numbers.
  _stateSig() {
    const o = this.orbit, u = this.uvCam;
    let tool = "";
    if (this.tool && !this._toolErr) {
      try {
        this.tool.update();
        if (this.tool.spec) {
          const F = this.tool.frame();
          tool = [this.tool.node?.id, this.tool.mode, JSON.stringify(this.tool.hot), JSON.stringify(this.tool.cHot),
                  this.tool.drag ? 1 : 0, F.c, F.r, F.order].join("|");
        }
      } catch (err) { tool = "err"; }
    }
    return [o.theta, o.phi, o.dist, o.target, this.uvMode ? 1 : 0, u ? [u.cx, u.cy, u.h] : "", this.fov,
            this.gate ? [this.gate.xres, this.gate.yres, this.gate.label] : "", this.vizLegend, this.normalWarning,
            this.labelWarning, this.uvWarning, this._dataRev, tool, this.select?.sig() ?? ""].join(";");
  }

  loop() {
    // Render on demand: the animation frame keeps ticking (it is cheap), but the scene is only drawn when it was
    // invalidated (rebuild, input), the size or _stateSig() changed, or once a second as a safety net for anything
    // not covered. An idle viewport used to redraw the whole scene and overlay 60 times a second -- per viewport node.
    const KEEPALIVE_MS = 1000;
    const render = () => {
      this._raf = requestAnimationFrame(render);
      const w = this.container.clientWidth | 0, h = this.container.clientHeight | 0;
      if (!w || !h) return;
      const sized = this._w !== w || this._h !== h;
      const sig = this._stateSig();
      const now = performance.now();
      if (!sized && !this._dirty && sig === this._sig && now - (this._drawnAt || 0) < KEEPALIVE_MS) return;
      this._dirty = false;
      this._sig = sig;
      this._drawnAt = now;
      if (sized) {
        this._w = w; this._h = h;
        const dpr = window.devicePixelRatio || 1;
        this.renderer.setSize(w, h, false);
        this.overlay.width = w * dpr; this.overlay.height = h * dpr;
        this.camera.aspect = w / h;
        this.camera.updateProjectionMatrix();
        this.updateLabelScale();
      }
      // fov is computed every frame: it depends both on this.fov (given by the camera node) and the gate size,
      // and the gate size depends on the container size. In the resize branch it wouldn't update when switching cameras or toggling
      // the gate -- and would only "suddenly be right" at the next panel resize
      if (this.uvMode) {
        this.renderUV(w, h);
        this.safeOverlay();
        return;
      }
      const wantFov = this.effectiveFov(w, h);
      if (Math.abs(this.camera.fov - wantFov) > 1e-6) {
        this.camera.fov = wantFov;
        // The on-screen glyph height uniform of the indices is computed from fov. fov now changes without resizing
        // the panel (switching cameras, toggling the gate); without this line the indices would keep the old size
        // until the next panel resize, when they "suddenly become right"
        this.updateLabelScale();
      }
      const { theta, phi, dist, target } = this.orbit;
      this.camera.position.set(
        target[0] + dist * Math.sin(phi) * Math.sin(theta),
        target[1] + dist * Math.cos(phi),
        target[2] + dist * Math.sin(phi) * Math.cos(theta));
      this.camera.lookAt(target[0], target[1], target[2]);
      // The near/far planes must hug the range actually needed. Depth buffer precision is distributed by the far/near ratio;
      // it used to be near=dist*1e-3 / far=max(1000,...), and when zoomed in the ratio reached 500,000,
      // so everything a few units away was quantized to the same depth value, and on colliding with grid lines depthFunc
      // LESS failed -- showing up as "points vanish when you zoom in".
      // Now the ratio stays around 1500, and far is guaranteed to cover the grid extent.
      const reach = Math.max(this.gridExtent || dist * 6, dist * 6);
      this.camera.near = Math.max(1e-4, dist * 0.01);
      this.camera.far = reach * 2.5;
      this.camera.updateProjectionMatrix();
      this.camera.updateMatrixWorld();
      // Fog follows the camera distance: the nearby grid is crisp, the distant one blends smoothly into the background,
      // so at any zoom scale the visible grid density is about the same.
      this.scene.fog.near = dist * 1.2;
      // The fade-out must finish **before** the grid boundary, otherwise that edge is still visible
      this.scene.fog.far = (this.gridExtent ? this.gridExtent * 0.8 : dist * 9);
      this.updateLineGrid(false);
      // Offset the headlight slightly to the upper right; perfectly coaxial would flatten the form with no shading transition
      const { r, u } = this._lv;
      r.setFromMatrixColumn(this.camera.matrix, 0);
      u.setFromMatrixColumn(this.camera.matrix, 1);
      this.head.position.copy(this.camera.position)
        .addScaledVector(r, dist * 0.35).addScaledVector(u, dist * 0.45);
      this.head.target.position.set(target[0], target[1], target[2]);
      this.head.target.updateMatrixWorld();

      this.renderer.render(this.scene, this.camera);
      this.safeOverlay();
    };
    render();
  }

  // Any error in the overlay is reported only once. It runs in requestAnimationFrame; without this guard
  // one typo means 60 errors a second, the console is flooded instantly and the really useful information drowns
  // -- and the main thread gets bogged down handling exceptions, making UI interaction laggy too.
  safeOverlay() {
    try {
      this.drawOverlay();
    } catch (err) {
      if (!this._overlayErr) {
        this._overlayErr = true;
        console.error("[pcg.viewport] overlay drawing error, overlay drawing stopped:", err);
      }
    }
  }

  dispose() {
    cancelAnimationFrame(this._raf);
    if (this._onKey) window.removeEventListener("keydown", this._onKey, true);
    if (this._onCapDown) {
      window.removeEventListener("pointerdown", this._onCapDown, true);
      window.removeEventListener("pointermove", this._onCapMove, true);
      window.removeEventListener("pointerup", this._onCapUp, true);
      window.removeEventListener("pointercancel", this._onCapUp, true);
      window.removeEventListener("mousedown", this._onCapMouse, true);
      window.removeEventListener("auxclick", this._onCapMouse, true);
      if (this._onKeyUp) window.removeEventListener("keyup", this._onKeyUp, true);
    }
    this.select?.dispose();
    this.renderer?.dispose();
  }
}

// ---------------------------------------------------------------- fetching data
async function fetchGeo(node, meta) {
  if (!node._pcgView) return;
  const id = meta?.node_id ?? node.id;
  try {
    const res = await fetch(`/pcg/geo/${id}?rev=${meta?.rev ?? Date.now()}`);
    if (!res.ok) {
      if (res.status === 404 && !meta) return;      // not run yet, exit silently
      throw new Error(await res.text());
    }
    const decoded = decode(await res.arrayBuffer());
    node._pcgTemplate = decoded.header.t_counts || null;
    node._pcgHull = !!decoded.header.counts_hull;
    node._pcgView.setGeometry(decoded);
    // The group list changes with the geometry; refresh the dropdown; if the selected group is gone fall back to none
    const w = node._pcgHL;
    if (w) {
      w.options.values = node._pcgView.groupLabels();
      if (!w.options.values.includes(w.value)) {
        w.value = "none";
        node.properties.highlight = "none";
        node._pcgView.setOptions({ highlight: "none" });
      }
    }
    const vw = node._pcgVZ;
    if (vw) {
      vw.options.values = node._pcgView.attribLabels();
      if (!vw.options.values.includes(vw.value)) {
        vw.value = "none";
        node.properties.visualize = "none";
        node._pcgView.setOptions({ visualize: "none" });
      }
    }
    node._pcgUpdateLabel(decoded);
  } catch (err) {
    node._pcgLabel.textContent = "viewport error: " + err.message;
    console.error("[pcg.viewport]", err);
  }
}

// ---------------------------------------------------------------- selection -> Group Create (pcg122)
/** Create a Group Create node fed by whatever feeds the viewport, with the selection as its base pattern. */
export function makeGroupNode(vnode, cls, expr) {
  const graph = vnode.graph || app.graph;
  const LG = globalThis.LiteGraph;
  if (!graph || !LG?.createNode) return null;
  const link = vnode.inputs?.[0]?.link;
  const l = link == null ? null : (graph.links?.[link] ?? graph.links?.get?.(link));
  const src = l ? graph.getNodeById(l.origin_id) : null;
  const n = LG.createNode("PCG_GroupCreate");
  if (!n) return null;
  const setW = (name, v) => {
    const w = n.widgets?.find((x) => x.name === name);
    if (w) { w.value = v; w.callback?.(v); }
  };
  setW("name", "selection");
  setW("cls", cls === "prim" ? "prim" : "point");
  setW("base", expr);
  const near = src || vnode;
  n.pos = [near.pos[0] + (near.size?.[0] ?? 200) + 40, near.pos[1] + (src ? 40 : (vnode.size?.[1] ?? 0) + 20)];
  graph.add(n);
  if (src) src.connect(l.origin_slot, n, 0);
  graph.setDirtyCanvas?.(true, true);
  return n;
}

// ---------------------------------------------------------------- registration
app.registerExtension({
  name: "pcg.viewport",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "PCG_Viewport") return;

    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onCreated?.apply(this, arguments);
      this.properties = Object.assign({}, DEFAULTS, this.properties);

      const set = (key) => (v) => {
        this.properties[key] = v;
        this._pcgView?.setOptions({ [key]: v });
        this._pcgUpdateLabel();
      };
      const combo = (k, vals) => this.addWidget("combo", k, this.properties[k],
        set(k), { values: vals, serialize: false });
      const bool = (k) => this.addWidget("toggle", k, this.properties[k],
        set(k), { serialize: false });

      // Candidate values for group highlight are only known at runtime; start with none and fill in once data arrives
      this._pcgHL = combo("highlight", ["none"]);
      // Candidate values for attribute visualization are likewise only known at runtime
      this._pcgVZ = combo("visualize", ["none"]);
      combo("shading", ["phong", "lambert", "normal", "color", "uv", "wire"]);
      combo("normals", ["auto", "smooth", "vertex", "flat"]);
      bool("wireframe");
      bool("show_points");
      combo("show_normals", ["none", "point", "vertex", "prim"]);
      this.addWidget("number", "normal_scale", this.properties.normal_scale,
        set("normal_scale"), { min: 0.01, max: 2, step: 0.01, serialize: false });
      combo("numbers", ["none", "point", "vertex", "prim"]);
      bool("show_grid");

      const el = document.createElement("div");
      Object.assign(el.style, {
        width: "100%", height: "100%", minHeight: "240px",
        background: "#1a1a1e", borderRadius: "4px", overflow: "hidden",
        position: "relative",
      });
      const label = document.createElement("div");
      Object.assign(label.style, {
        position: "absolute", left: "6px", bottom: "4px", zIndex: 10,
        font: "10px ui-monospace, monospace", color: "#8a8a96",
        pointerEvents: "none", textShadow: "0 0 3px #1a1a1e",
      });
      el.appendChild(label);
      this._pcgLabel = label;

      this.addDOMWidget("viewport", "div", el, { hideOnZoom: false });
      this._pcgView = new Viewport(el, this.properties);
      this._pcgView.onSelectAction = (kind, cls, expr) => {
        if (kind === "group") makeGroupNode(this, cls, expr);
      };
      this.size = [360, 560];

      // The widget is the truth the user sees. litegraph's order when loading a workflow is
      // onNodeCreated -> configure(); configure writes saved values back into widgets and
      // properties, but **doesn't fire widget callbacks**, so the Viewport instance
      // holds a snapshot from creation time, which doesn't match what the UI shows.
      // The symptom: the UI says wireframe=true but it isn't drawn; it only recovers after clicking manually.
      // Here we sync once in reverse from the widgets, bringing both sides in line.
      // Sync direction: properties -> widget -> viewport.
      //
      // It can't be the other way round, reading from widgets. When litegraph restores a workflow it maps
      // widgets_values back onto the widget array **by index**, even when marked serialize:false.
      // So whenever the number of widgets changed (e.g. highlight was newly added), an old workflow's values
      // shift as a whole -- showing up as shading displayed as "auto", normal_scale becoming NaN.
      // properties are stored by name and naturally immune; they are the source of truth.
      this._pcgSync = () => {
        if (!this._pcgView) return;
        const o = {};
        for (const [k, def] of Object.entries(DEFAULTS)) {
          const v = this.properties[k];
          o[k] = v === undefined ? def : v;
        }
        for (const w of this.widgets ?? [])
          if (w && w.name in o) w.value = o[w.name];
        Object.assign(this.properties, o);
        this._pcgView.setOptions(o);
        this._pcgUpdateLabel?.();
      };

      this._pcgUpdateLabel = (decoded) => {
        if (decoded) this._pcgCounts = decoded.header.counts;
        const c = this._pcgCounts;
        if (!c) return;
        const v = this._pcgView;
        const bits = [`pts ${c.points}`, `vtx ${c.verts}`, `prims ${c.prims}`,
                      `N:${v?.shadingInfo ?? "-"}`];
        if (this._pcgHull) bits.push(`nurbs subdivided ${c.tris} tris`);
        const tc = this._pcgTemplate;
        if (tc) bits.push(`tmpl ${tc.points}/${tc.prims}`);
        this._pcgLabel.textContent = bits.join("  ");
      };

      // After a page refresh the frontend state is cleared but the server cache remains -- pull once proactively.
      // The sync also goes in this retry chain: node added to the graph = configure has finished.
      let tries = 0;
      const restore = () => {
        if (this.id == null || this.id < 0) {
          if (++tries < 20) setTimeout(restore, 150);
          return;
        }
        this._pcgSync();
        fetchGeo(this, null);
      };
      setTimeout(this._pcgSync, 0);      // newly dragged-out node: align on the next tick
      setTimeout(restore, 100);
    };

    // Sync point when loading from a workflow. Check once more after configure finishes; most reliable.
    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function (info) {
      onConfigure?.apply(this, arguments);
      setTimeout(() => this._pcgSync?.(), 0);
    };

    const onExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      onExecuted?.apply(this, arguments);
      const meta = message?.pcg_viewport?.[0];
      if (meta) fetchGeo(this, meta);
    };

    const onRemoved = nodeType.prototype.onRemoved;
    nodeType.prototype.onRemoved = function () {
      this._pcgView?.dispose();
      onRemoved?.apply(this, arguments);
    };
  },
});
