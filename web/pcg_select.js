// Viewport selection (pcg122): click / box-select points or primitives in the viewport and turn the selection into
// a group expression ("0-4 7 12-19") that every group field understands -- copy it, or create a Group Create node
// wired to the geometry the viewport shows.
//
//   S          toggle select mode (the toolbar appears at the top); Esc leaves it
//   click      pick the nearest point (within 10 px) / the primitive under the cursor
//   drag       box select (points: projected positions; primitives: projected centres)
//   Shift      add to the selection, Ctrl / Cmd remove from it; plain click / drag replaces
//   Alt / Space + drag, middle / right button: navigate as usual
//
// "Visible only" skips what the surface hides (one ray per candidate; with very many candidates on a big mesh it
// selects through, and says so). Indices refer to the geometry the viewport received -- the output of the node
// feeding it -- so the expression is meant for nodes downstream of that node (Group Create, Blast, ...).
//
// The pure parts (expression, box / nearest picking, set operations) are exported for the tests.

/** Sorted unique ints -> "0-4 7 12-19". */
export function rangesExpr(ids) {
  const a = Array.from(new Set(Array.from(ids, (x) => x | 0))).sort((x, y) => x - y);
  const out = [];
  for (let i = 0; i < a.length;) {
    let j = i;
    while (j + 1 < a.length && a[j + 1] === a[j] + 1) j++;
    out.push(j > i ? `${a[i]}-${a[j]}` : `${a[i]}`);
    i = j + 1;
  }
  return out.join(" ");
}

/** "0-4 7" -> [0, 1, 2, 3, 4, 7] (inverse of rangesExpr, plain numbers and a-b ranges only). */
export function parseRanges(s) {
  const out = [];
  for (const t of String(s || "").split(/\s+/)) {
    if (!t) continue;
    const m = /^(\d+)(?:-(\d+))?$/.exec(t);
    if (!m) continue;
    const a = +m[1], b = m[2] === undefined ? a : +m[2];
    for (let k = Math.min(a, b); k <= Math.max(a, b); k++) out.push(k);
  }
  return out;
}

/** Indices whose screen position (xy: Float32Array of x, y per item, NaN = behind the camera) is inside the box. */
export function boxPick(xy, count, x0, y0, x1, y1) {
  const lx = Math.min(x0, x1), hx = Math.max(x0, x1), ly = Math.min(y0, y1), hy = Math.max(y0, y1);
  const out = [];
  for (let i = 0; i < count; i++) {
    const x = xy[2 * i], y = xy[2 * i + 1];
    if (x >= lx && x <= hx && y >= ly && y <= hy) out.push(i);
  }
  return out;
}

/** Indices within r pixels of (x, y), nearest first. */
export function nearPick(xy, count, x, y, r) {
  const c = [];
  const r2 = r * r;
  for (let i = 0; i < count; i++) {
    const dx = xy[2 * i] - x, dy = xy[2 * i + 1] - y;
    const d = dx * dx + dy * dy;
    if (d <= r2) c.push([d, i]);
  }
  c.sort((a, b) => a[0] - b[0]);
  return c.map((p) => p[1]);
}

/** Apply a pick to a selection: op = "replace" | "add" | "remove". Returns the new Set. */
export function applyOp(sel, ids, op) {
  if (op === "replace") return new Set(ids);
  const s = new Set(sel);
  for (const i of ids) { if (op === "add") s.add(i); else s.delete(i); }
  return s;
}

export function opOf(e) {
  return e.shiftKey ? "add" : (e.ctrlKey || e.metaKey) ? "remove" : "replace";
}

const RAY_BUDGET = 2e7;       // candidates x triangles above which "visible only" selects through
const CLICK_PX = 10;

export class SelectTool {
  constructor(view) {
    this.v = view;
    this.active = false;
    this.cls = "point";
    this.sel = new Set();
    this.visibleOnly = true;
    this.down = null;
    this.box = null;
    this.through = false;
    this.rev = 0;
    this.bar = null;
    this.onAction = null;     // (kind, cls, expr) -> void, set by the node ("group")
  }

  count() {
    const A = this.v.data?.arrays;
    if (!A) return 0;
    if (this.cls === "point") return A.position ? A.position.length / 3 : 0;
    return A.prim_center ? A.prim_center.length / 3 : 0;
  }
  positions() {
    const A = this.v.data?.arrays;
    return this.cls === "point" ? A?.position : A?.prim_center;
  }
  expr() { return rangesExpr(this.sel); }

  setActive(on) {
    this.active = !!on;
    this.down = this.box = null;
    this.ensureBar();
    this.syncBar();
    this.v._dirty = true;
  }
  setClass(cls) {
    if (cls === this.cls) return;
    this.cls = cls;
    this.sel = new Set();
    this.changed();
  }
  clear() { this.sel = new Set(); this.changed(); }
  changed() { this.rev++; this.syncBar(); this.v._dirty = true; }

  /** The geometry changed: drop indices that no longer exist. */
  dataChanged() {
    const n = this.count();
    let drop = false;
    for (const i of this.sel) if (i >= n) { drop = true; break; }
    if (drop) this.sel = new Set(Array.from(this.sel).filter((i) => i < n));
    this.changed();
  }

  // screen positions of every item (NaN for points behind the camera)
  project() {
    const P = this.positions(), n = this.count();
    const xy = new Float32Array(2 * n);
    for (let i = 0; i < n; i++) {
      const s = P ? this.v.screen([P[3 * i], P[3 * i + 1], P[3 * i + 2]]) : null;
      xy[2 * i] = s ? s[0] : NaN;
      xy[2 * i + 1] = s ? s[1] : NaN;
    }
    return xy;
  }

  visible(ids) {
    this.through = false;
    if (!this.visibleOnly || !this.v.mesh || !ids.length) return ids;
    const tris = this.v.triCount || 0;
    if (ids.length * tris > RAY_BUDGET) { this.through = true; return ids; }
    const P = this.positions();
    return ids.filter((i) => !this.v.hiddenPoint(P[3 * i], P[3 * i + 1], P[3 * i + 2]));
  }

  pickClick(x, y) {
    if (this.cls === "prim") {
      const hit = this.v.pickPrim?.(x, y);
      if (hit != null && hit >= 0) return [hit];
    }
    const xy = this.project();
    const near = nearPick(xy, this.count(), x, y, CLICK_PX);
    for (const i of near) {
      if (this.visible([i]).length) return [i];
    }
    return [];
  }

  pickBox(b) {
    const xy = this.project();
    return this.visible(boxPick(xy, this.count(), b.x0, b.y0, b.x1, b.y1));
  }

  // ---------------------------------------------------------------- pointer (viewport canvas pixels)
  pointerDown(e, x, y) {
    if (!this.active || e.button !== 0) return false;
    this.down = { x, y, op: opOf(e) };
    this.box = null;
    return true;
  }
  pointerMove(e, x, y) {
    if (!this.down) return false;
    if (this.box || Math.hypot(x - this.down.x, y - this.down.y) > 3)
      this.box = { x0: this.down.x, y0: this.down.y, x1: x, y1: y };
    this.v._dirty = true;
    return true;
  }
  pointerUp(e, x, y) {
    if (!this.down) return false;
    const op = this.down.op;
    const ids = this.box ? this.pickBox(this.box) : this.pickClick(this.down.x, this.down.y);
    this.down = this.box = null;
    this.sel = applyOp(this.sel, ids, op);
    this.changed();
    return true;
  }
  key(e) {
    const k = (e.key || "").toLowerCase();
    if (k === "s" && !e.ctrlKey && !e.metaKey && !e.altKey) { this.setActive(!this.active); return true; }
    if (!this.active) return false;
    if (k === "escape") { this.setActive(false); return true; }
    return false;
  }
  sig() {
    return this.active ? [this.cls, this.rev, this.box ? [this.box.x1, this.box.y1] : ""].join(",") : "";
  }

  // ---------------------------------------------------------------- drawing (2D overlay)
  draw(c, dpr) {
    if (!this.sel.size && !this.box) return;
    const P = this.positions();
    if (P && this.sel.size) {
      c.fillStyle = this.cls === "point" ? "#ffd43b" : "#ff922b";
      const r = (this.cls === "point" ? 3 : 4) * dpr;
      let k = 0;
      for (const i of this.sel) {
        if (++k > 50000) break;
        const s = this.v.screen([P[3 * i], P[3 * i + 1], P[3 * i + 2]]);
        if (!s) continue;
        c.fillRect(s[0] * dpr - r, s[1] * dpr - r, 2 * r, 2 * r);
      }
    }
    if (this.box) {
      const b = this.box;
      c.save();
      c.strokeStyle = "#ffd43b";
      c.setLineDash([4 * dpr, 3 * dpr]);
      c.lineWidth = dpr;
      c.strokeRect(Math.min(b.x0, b.x1) * dpr, Math.min(b.y0, b.y1) * dpr,
                   Math.abs(b.x1 - b.x0) * dpr, Math.abs(b.y1 - b.y0) * dpr);
      c.fillStyle = "rgba(255,212,59,0.08)";
      c.fillRect(Math.min(b.x0, b.x1) * dpr, Math.min(b.y0, b.y1) * dpr,
                 Math.abs(b.x1 - b.x0) * dpr, Math.abs(b.y1 - b.y0) * dpr);
      c.restore();
    }
  }

  // ---------------------------------------------------------------- toolbar (DOM, top of the viewport)
  ensureBar() {
    if (this.bar || typeof document === "undefined" || !this.v.container) return;
    const bar = document.createElement("div");
    Object.assign(bar.style, {
      position: "absolute", left: "4px", right: "4px", top: "4px", zIndex: 12, display: "none",
      gap: "4px", alignItems: "center", font: "11px ui-monospace, monospace", color: "#ddd",
      background: "rgba(20,20,24,0.88)", border: "1px solid #444", borderRadius: "4px", padding: "3px 4px",
    });
    const mk = (tag, text, title) => {
      const b = document.createElement(tag);
      if (text != null) b.textContent = text;
      if (title) b.title = title;
      Object.assign(b.style, { font: "inherit", color: "inherit", background: "#2b2b31", border: "1px solid #555",
                               borderRadius: "3px", padding: "1px 6px", cursor: "pointer" });
      return b;
    };
    this.bPts = mk("button", "points", "Select points");
    this.bPrims = mk("button", "prims", "Select primitives");
    this.bPts.onclick = () => this.setClass("point");
    this.bPrims.onclick = () => this.setClass("prim");
    this.bVis = mk("button", "visible", "Only select what the surface doesn't hide");
    this.bVis.onclick = () => { this.visibleOnly = !this.visibleOnly; this.syncBar(); };
    this.info = document.createElement("span");
    this.field = document.createElement("input");
    this.field.readOnly = true;
    Object.assign(this.field.style, { flex: "1", minWidth: "40px", font: "inherit", color: "#fff",
                                      background: "#111", border: "1px solid #555", borderRadius: "3px",
                                      padding: "1px 4px" });
    this.bCopy = mk("button", "copy", "Copy the group expression");
    this.bCopy.onclick = () => {
      const t = this.expr();
      try { navigator.clipboard?.writeText(t); } catch (_) { /* no clipboard permission */ }
      this.field.select?.();
    };
    this.bGroup = mk("button", "→ group", "Create a Group Create node with this selection, wired to the viewport's input");
    this.bGroup.onclick = () => {
      if (this.sel.size) (this.onAction || this.v.onSelectAction)?.("group", this.cls, this.expr());
    };
    this.bClear = mk("button", "×", "Clear the selection");
    this.bClear.onclick = () => this.clear();
    for (const b of [this.bPts, this.bPrims, this.bVis, this.info, this.field, this.bCopy, this.bGroup, this.bClear])
      bar.appendChild(b);
    // keep litegraph from dragging the node when using the bar
    for (const ev of ["pointerdown", "mousedown", "wheel"]) bar.addEventListener(ev, (e) => e.stopPropagation());
    this.v.container.appendChild(bar);
    this.bar = bar;
  }
  syncBar() {
    if (!this.bar) return;
    this.bar.style.display = this.active ? "flex" : "none";
    const on = { background: "#4a5a7a", borderColor: "#8aa0d0" }, off = { background: "#2b2b31", borderColor: "#555" };
    Object.assign(this.bPts.style, this.cls === "point" ? on : off);
    Object.assign(this.bPrims.style, this.cls === "prim" ? on : off);
    Object.assign(this.bVis.style, this.visibleOnly ? on : off);
    this.info.textContent = `${this.sel.size}${this.through ? " (through)" : ""}`;
    this.field.value = this.expr();
  }
  dispose() { this.bar?.remove(); this.bar = null; }
}
