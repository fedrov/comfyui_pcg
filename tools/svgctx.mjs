// Minimal canvas 2D -> SVG shim, shared by render_icons.mjs (contact sheet) and render_doc_icons.mjs
// (one SVG per glyph for the HTML docs). It implements only the operations the icons use: an icon calling
// anything else throws, which doubles as a check.
export class SvgCtx {
  constructor() {
    this.out = [];
    this.st = { m: [1, 0, 0, 1, 0, 0], stroke: "#000", fill: "#000",
                lw: 1, dash: null, alpha: 1 };
    this.stack = [];
    this.p = [];
    this.cur = [0, 0];
  }
  set strokeStyle(v) { this.st.stroke = v; }
  set fillStyle(v) { this.st.fill = v; }
  set lineWidth(v) { this.st.lw = v; }
  get lineWidth() { return this.st.lw; }
  set lineJoin(v) {} set lineCap(v) {}
  set globalAlpha(v) { this.st.alpha = v; }
  get globalAlpha() { return this.st.alpha; }
  setLineDash(d) { this.st.dash = d && d.length ? d.slice() : null; }
  save() { this.stack.push({ ...this.st, m: this.st.m.slice() }); }
  restore() { if (this.stack.length) this.st = this.stack.pop(); }
  translate(x, y) {
    const m = this.st.m;
    m[4] += m[0] * x + m[2] * y; m[5] += m[1] * x + m[3] * y;
  }
  scale(x, y) {
    const m = this.st.m;
    m[0] *= x; m[1] *= x; m[2] *= y; m[3] *= y;
  }
  _t(x, y) {
    const m = this.st.m;
    return [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
  }
  _s() { return Math.abs(this.st.m[0]); }
  beginPath() { this.p = []; }
  closePath() { this.p.push("Z"); }
  moveTo(x, y) { const [a, b] = this._t(x, y); this.p.push(`M${a} ${b}`);
                 this.cur = [x, y]; }
  lineTo(x, y) { const [a, b] = this._t(x, y); this.p.push(`L${a} ${b}`);
                 this.cur = [x, y]; }
  bezierCurveTo(x1, y1, x2, y2, x, y) {
    const [a1, b1] = this._t(x1, y1), [a2, b2] = this._t(x2, y2),
          [a, b] = this._t(x, y);
    this.p.push(`C${a1} ${b1} ${a2} ${b2} ${a} ${b}`);
    this.cur = [x, y];
  }
  rect(x, y, w, h) {
    this.moveTo(x, y); this.lineTo(x + w, y); this.lineTo(x + w, y + h);
    this.lineTo(x, y + h); this.closePath();
  }
  arc(cx, cy, r, a0, a1) { this.ellipse(cx, cy, r, r, 0, a0, a1); }
  ellipse(cx, cy, rx, ry, rot, a0, a1) {
    // Sampled into a polyline -- the contact sheet is only for looking, it need not be an exact SVG arc
    const n = this.arcSegments || 48;
    let span = a1 - a0;
    if (span > Math.PI * 2) span = Math.PI * 2;
    for (let i = 0; i <= n; i++) {
      const a = a0 + span * (i / n);
      const x = cx + Math.cos(a) * rx, y = cy + Math.sin(a) * ry;
      if (i === 0) this.moveTo(x, y); else this.lineTo(x, y);
    }
  }
  _emit(mode) {
    if (!this.p.length) return;
    const d = this.p.join(" ");
    const s = this.st;
    const da = s.dash
      ? ` stroke-dasharray="${s.dash.map((v) => v * this._s()).join(",")}"`
      : "";
    if (mode === "fill") {
      this.out.push(`<path d="${d}" fill="${s.fill}" fill-opacity="${s.alpha}"`
                    + ` stroke="none"/>`);
    } else {
      this.out.push(`<path d="${d}" fill="none" stroke="${s.stroke}"`
                    + ` stroke-opacity="${s.alpha}"`
                    + ` stroke-width="${s.lw * this._s()}"`
                    + ` stroke-linejoin="round" stroke-linecap="round"${da}/>`);
    }
  }
  stroke() { this._emit("stroke"); }
  fill() { this._emit("fill"); }
  fillRect(x, y, w, h) {
    const p = this.p; this.beginPath(); this.rect(x, y, w, h);
    this._emit("fill"); this.p = p;
  }
}
