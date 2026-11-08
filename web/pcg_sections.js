// comfyui_pcg/web/pcg_sections.js
//
// Sections of the parameter panel: title bar + separator line + section parameters collapse when the toggle is off.
//
// ★ Two hard constraints, both learned the hard way:
//
// 1) Never modify the node.widgets array (no inserting, no reordering). When litegraph restores a workflow
//    it maps widgets_values back onto the widget array by index; inserting a section-header widget shifts
//    every later parameter, with no error -- the values just all end up in the wrong place.
//    So the title bar is not a new widget; it **takes over drawing of the toggle widget at the start of the section**.
//
// 2) Don't intercept clicks. Old litegraph dispatches events by widget.type, while the new frontend replaced the whole widget
//    system again; and a canvas-level capture listener needs stopImmediatePropagation to block litegraph's own listener
//    on the same element -- all three approaches were tried and none is reliable on this version.
//    So this only draws: clicking the title bar is the built-in toggle behaviour (ON/OFF), no collapsing.
//    When the toggle is off the section's parameters collapse automatically, so the tidying effect is still there.
//
// Metadata comes from _sec() on the Python side: ComfyUI passes widget options as-is into
// /object_info, and the frontend can read them at nodeData.input.required[name][1].

import { app } from "../../scripts/app.js";

// For pcg_panel.js: hiding / showing native widgets uses the same technique (change type + computeSize + hidden)

const HIDDEN = "pcg-collapsed";
const HEADER_H = 26;
const BAR_ON = "#2f3742";
const BAR_OFF = "#262a31";
const TXT_ON = "#dde3ea";
const TXT_OFF = "#767e89";
const ACCENT = "#5fc4ff";
const RULE = "#454b55";

export function setShown(w, show) {
  if (!w) return;
  if (w.origType === undefined) {
    w.origType = w.type;
    w.origComputeSize = w.computeSize;
  }
  w.type = show ? w.origType : HIDDEN;
  // -4 cancels the spacing litegraph reserves per row, otherwise a pile of blank rows remains after collapsing
  w.computeSize = show ? w.origComputeSize : () => [0, -4];
  w.hidden = !show;
}

function readMeta(nodeData) {
  const map = new Map();
  for (const grp of ["required", "optional"]) {
    const d = nodeData?.input?.[grp];
    if (!d) continue;
    for (const [name, spec] of Object.entries(d)) {
      const o = Array.isArray(spec) ? spec[1] : null;
      if (o && typeof o.section === "string")
        map.set(name, { section: o.section, gate: !!o.section_gate });
    }
  }
  return map;
}

app.registerExtension({
  name: "pcg.sections",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    const meta = readMeta(nodeData);
    if (!meta.size) return;

    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onCreated?.apply(this, arguments);
      if (!this.widgets) return;
      // Collapse state left by old versions; there is no collapsing concept any more, clear it so it doesn't interfere
      if (this.properties) delete this.properties._pcgOpen;

      // Group in original array order. Widgets not in the table inherit the previous one's section -- this absorbs
      // companion widgets inserted automatically by the frontend, like control_after_generate.
      const sections = new Map();
      let cur = null;
      for (const w of this.widgets) {
        const info = meta.get(w.name);
        if (info) cur = info.section;
        else if (cur === null || !sections.has(cur)) continue;
        if (!sections.has(cur)) sections.set(cur, { gate: null, members: [] });
        const s = sections.get(cur);
        if (info?.gate) s.gate = w;
        else s.members.push(w);
      }

      const apply = () => {
        // The parameter panel (pcg_panel.js) took over this node: native widgets are all hidden, sections are drawn by the panel
        if (this._pcgPanelActive) return;
        for (const s of sections.values()) {
          const on = s.gate ? s.gate.value !== false : true;
          for (const w of s.members) setShown(w, on);
        }
        // Only grow, never shrink: computeSize() is the minimum size; applying it directly would squash a node the user
        // enlarged manually. When a section collapses the height shrinks anyway; leave re-layout to litegraph.
        const need = this.computeSize();
        this.setSize([Math.max(this.size[0], need[0]), need[1]]);
        app.graph?.setDirtyCanvas(true, true);
      };

      // Draw the section's toggle as a title bar. Once a draw is attached to the widget, litegraph no longer uses its built-in
      // drawing, so the whole row has to be drawn by us.
      for (const [name, s] of sections) {
        const g = s.gate;
        if (!g) continue;
        g.computeSize = () => [0, HEADER_H];
        g.draw = function (ctx, node, width, y, H) {
          this._pcgY = y;                       // needed for the separator line
          const on = this.value !== false;
          const m = 10, h = HEADER_H - 5, top = y + 2;
          ctx.save();

          ctx.fillStyle = on ? BAR_ON : BAR_OFF;
          ctx.beginPath();
          ctx.roundRect(m, top, width - m * 2, h, 4);
          ctx.fill();
          ctx.strokeStyle = RULE;
          ctx.lineWidth = 1;
          ctx.stroke();

          if (on) {                             // left vertical bar: enabled
            ctx.fillStyle = ACCENT;
            ctx.beginPath();
            ctx.roundRect(m, top, 3, h, 2);
            ctx.fill();
          }

          ctx.fillStyle = on ? TXT_ON : TXT_OFF;
          ctx.font = "600 12px ui-monospace, monospace";
          ctx.textAlign = "left";
          ctx.textBaseline = "middle";
          ctx.fillText(name, m + 14, top + h / 2);

          const bw = 36, bx = width - m - bw - 8;
          ctx.fillStyle = on ? ACCENT : "#3b414a";
          ctx.beginPath();
          ctx.roundRect(bx, top + h / 2 - 7, bw, 14, 7);
          ctx.fill();
          ctx.fillStyle = on ? "#11161c" : "#828a94";
          ctx.font = "600 10px ui-monospace, monospace";
          ctx.textAlign = "center";
          ctx.fillText(on ? "ON" : "OFF", bx + bw / 2, top + h / 2);
          ctx.restore();
        };
        // Re-collapse / expand the section's parameters as soon as the toggle changes
        const orig = g.callback;
        g.callback = function (v, ...rest) {
          const r = orig?.call(this, v, ...rest);
          apply();
          return r;
        };
      }

      this._pcgSections = sections;
      this._pcgApplySections = apply;
      apply();
    };

    // Draw a full-width separator line above each section. Position uses the y recorded in the title bar's draw, so it is exact.
    const onDrawFg = nodeType.prototype.onDrawForeground;
    nodeType.prototype.onDrawForeground = function (ctx, canvas) {
      onDrawFg?.apply(this, arguments);
      if (this.flags?.collapsed || !this._pcgSections || this._pcgPanelActive) return;
      ctx.save();
      ctx.strokeStyle = RULE;
      ctx.lineWidth = 1;
      for (const s of this._pcgSections.values()) {
        const y = s.gate?._pcgY;
        if (y === undefined) continue;
        ctx.beginPath();
        ctx.moveTo(6, y - 2);
        ctx.lineTo(this.size[0] - 6, y - 2);
        ctx.stroke();
      }
      ctx.restore();
    };

    // When loading from a workflow, widget values are filled in only after configure; sync once more
    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function (info) {
      onConfigure?.apply(this, arguments);
      setTimeout(() => this._pcgApplySections?.(), 0);
    };
  },
});
