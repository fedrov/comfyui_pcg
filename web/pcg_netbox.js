// comfyui_pcg/web/pcg_netbox.js
//
// Houdini's network boxes and colour palette, on ComfyUI's groups and nodes.
//
// 1) **Collapsing a network box.** Right-click a group -> "PCG: Collapse Box": every node inside is collapsed to its
//    title bar and stacked in a column at the box's top left, and the box shrinks round them (its title gets a "▸ "),
//    so a finished part of the network takes the room of a list. "PCG: Expand Box" puts every node back where it
//    was, as it was (collapsed or not), and the box back to its size. The wires stay connected throughout (the nodes
//    are only collapsed and moved), and what is needed to undo it is kept in the group's own flags, so it is saved
//    with the workflow: a box collapsed yesterday expands today.
//
// 2) **The colour palette.** With nodes or boxes selected, press C (or right-click a node -> "PCG: Colour Palette…"):
//    Houdini's palette of node colours, the default (no colour), and the node shapes (box, round, card). A node gets the
//    colour on its title bar and a darker shade of it on its body, a box the colour itself.
//
// Alt + drag on a node (duplicate it) and Alt + click on a wire (a dot to route it) are the frontend's own, as in
// Houdini; nothing here changes them.

import { app } from "../../scripts/app.js";

export const PALETTE_ID = "PCG.NetBox.PaletteKey";
const FLAG = "pcg_box";
const MARK = "▸ ";

// Houdini's node colour palette (the network editor's default swatches), first row warm to cool, second row muted
export const PALETTE = [
  "#cc3333", "#e5732e", "#e5b82e", "#a3cc33", "#33b24c", "#2eb8a3", "#3399e5", "#4d5ce5", "#8c4de5", "#cc4dab",
  "#8c5c4d", "#998066", "#7a8c66", "#5c7a7a", "#5c668c", "#7a5c8c", "#595959", "#a6a6a6", "#e5e5e5", "#262626",
];

/** "#rrggbb" -> the same hue at factor brightness ("#rrggbb"). */
export function shade(hex, factor) {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(hex || ""));
  if (!m) return hex;
  const v = parseInt(m[1], 16);
  const c = [(v >> 16) & 255, (v >> 8) & 255, v & 255].map((x) => Math.max(0, Math.min(255, Math.round(x * factor))));
  return "#" + c.map((x) => x.toString(16).padStart(2, "0")).join("");
}

/** Nodes and groups: a colour (null = the default) on each; nodes: title colour and a darker body. */
export function applyColour(items, hex) {
  for (const it of items) {
    if (isGroup(it)) {
      if (hex) it.color = hex;
      else delete it.color;
      continue;
    }
    if (hex) { it.color = hex; it.bgcolor = shade(hex, 0.45); }
    else { delete it.color; delete it.bgcolor; }
  }
}

export const SHAPES = { box: 1, round: 2, card: 4 };          // LiteGraph.BOX_SHAPE, ROUND_SHAPE, CARD_SHAPE

/** The nodes among items get shape "box" / "round" / "card". */
export function applyShape(items, name) {
  const LG = globalThis.LiteGraph;
  const v = LG?.[`${name.toUpperCase()}_SHAPE`] ?? SHAPES[name];
  for (const it of items) if (!isGroup(it) && v !== undefined) it.shape = v;
}

function isGroup(it) {
  const G = globalThis.LiteGraph?.LGraphGroup ?? globalThis.LGraphGroup;
  if (G && it instanceof G) return true;
  return !!it && !("inputs" in it) && ("_bounding" in it || "bounding" in it);
}

function titleH() { return globalThis.LiteGraph?.NODE_TITLE_HEIGHT ?? 30; }

/** The nodes inside a group (after asking the group to recompute them). */
export function boxNodes(group) {
  try { group.recomputeInsideNodes?.(); } catch (_) { /* an old frontend: whatever it holds */ }
  const ns = group.nodes ?? group._nodes ?? [];
  return [...ns].filter((n) => n && n.pos && n.size && n.flags && "id" in n);
}

export function isCollapsed(group) { return !!group?.flags?.[FLAG]; }

/** The width a node takes collapsed (its title). */
function collapsedWidth(n) {
  const b = n.getBounding?.();
  if (b && n.flags?.collapsed) return b[2];
  return n._collapsed_width ?? globalThis.LiteGraph?.NODE_COLLAPSED_WIDTH ?? 80;
}

/**
 * Collapse a network box: its nodes collapsed and stacked at its top left, the box round them. Returns whether
 * anything was done (an already collapsed box, or one with no nodes, is left as it is).
 */
export function collapseBox(group) {
  if (!group || isCollapsed(group)) return false;
  const ns = boxNodes(group);
  if (!ns.length) return false;
  const [gx, gy, gw, gh] = [group.pos[0], group.pos[1], group.size[0], group.size[1]];
  group.flags = group.flags || {};
  group.flags[FLAG] = { bounds: [gx, gy, gw, gh], title: group.title,
                        nodes: ns.map((n) => ({ id: n.id, pos: [n.pos[0], n.pos[1]], collapsed: !!n.flags.collapsed })) };
  const th = titleH(), gap = 6, pad = 10;
  const top = gy + (group.titleHeight ?? th) + pad;
  // top to bottom, left to right as they stood, so the list reads in the network's order
  const order = [...ns].sort((a, b) => (a.pos[1] - b.pos[1]) || (a.pos[0] - b.pos[0]));
  let w = 0;
  order.forEach((n, i) => {
    if (!n.flags.collapsed) {
      if (typeof n.collapse === "function") n.collapse(true);
      else n.flags.collapsed = true;
    }
    n.pos = [gx + pad, top + th + i * (th + gap)];
    w = Math.max(w, collapsedWidth(n));
  });
  group.title = MARK + String(group.title ?? "").replace(/^▸ /, "");
  const h = (top - gy) + order.length * (th + gap) + pad;
  group.size = [Math.max(w + 2 * pad, 140), Math.max(h, 80)];
  group.graph?.setDirtyCanvas?.(true, true);
  return true;
}

/** Expand a collapsed network box: every node back where it was, as it was; the box back to its size. */
export function expandBox(group) {
  const st = group?.flags?.[FLAG];
  if (!st) return false;
  const g = group.graph;
  const byId = (id) => g?.getNodeById?.(id) ?? (g?._nodes ?? []).find((n) => String(n.id) === String(id));
  for (const r of st.nodes) {
    const n = byId(r.id);
    if (!n) continue;                                          // deleted while collapsed
    if (!!n.flags?.collapsed !== r.collapsed) {
      if (typeof n.collapse === "function") n.collapse(true);
      else n.flags.collapsed = r.collapsed;
    }
    n.pos = [r.pos[0], r.pos[1]];
  }
  group.pos = [st.bounds[0], st.bounds[1]];
  group.size = [st.bounds[2], st.bounds[3]];
  group.title = String(group.title ?? "").startsWith(MARK) ? group.title.slice(MARK.length) : (st.title ?? group.title);
  delete group.flags[FLAG];
  g?.setDirtyCanvas?.(true, true);
  return true;
}

// ── the palette popup
let POP = null;

function closePalette() {
  POP?.remove();
  POP = null;
}

/** Selected nodes and groups of the canvas. */
export function selectedItems(canvas) {
  const out = new Set(Object.values(canvas?.selected_nodes || {}));
  for (const it of canvas?.selectedItems || []) if (it && it.pos) out.add(it);
  if (canvas?.selected_group) out.add(canvas.selected_group);
  return [...out];
}

export function openPalette(items, x, y) {
  closePalette();
  if (!items.length) return null;
  const d = document.createElement("div");
  d.className = "pcg-palette";
  d.style.cssText = `position:fixed;left:${x}px;top:${y}px;z-index:10001;background:#1c2027;border:1px solid #3a4049;
    border-radius:8px;padding:8px;box-shadow:0 6px 24px rgba(0,0,0,.5);display:grid;grid-template-columns:repeat(10,20px);
    gap:4px;font:12px sans-serif;color:#dde3ea`;
  const done = () => { app.graph?.setDirtyCanvas?.(true, true); closePalette(); };
  for (const c of PALETTE) {
    const b = document.createElement("div");
    b.className = "sw";
    b.dataset.colour = c;
    b.title = c;
    b.style.cssText = `width:20px;height:20px;border-radius:4px;background:${c};cursor:pointer;border:1px solid #0006`;
    b.onclick = () => { applyColour(items, c); done(); };
    d.appendChild(b);
  }
  const row = (label, fn, title) => {
    const b = document.createElement("div");
    b.textContent = label;
    b.title = title || label;
    b.style.cssText = "grid-column:span 2;text-align:center;padding:2px 0;border:1px solid #3a4049;border-radius:4px;cursor:pointer";
    b.onclick = () => { fn(); done(); };
    d.appendChild(b);
    return b;
  };
  row("none", () => applyColour(items, null), "The default colour").className = "none";
  for (const s of Object.keys(SHAPES)) row(s, () => applyShape(items, s), `Node shape: ${s}`).className = `shape-${s}`;
  document.body.appendChild(d);
  POP = d;
  return d;
}

function typing(t) {
  return t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable);
}

let MOUSE = [200, 200];

function setting(id, dflt) {
  try { const v = app.extensionManager?.setting?.get?.(id) ?? app.ui?.settings?.getSettingValue?.(id); return v ?? dflt; }
  catch (_) { return dflt; }
}

export function onKey(ev) {
  if (ev.code === "Escape" && POP) { closePalette(); return; }
  if (ev.code !== "KeyC" || ev.ctrlKey || ev.altKey || ev.metaKey || ev.shiftKey) return;
  if (typing(ev.target) || !setting(PALETTE_ID, true)) return;
  const items = selectedItems(app.canvas);
  if (!items.length) return;
  openPalette(items, MOUSE[0], MOUSE[1]);
  ev.preventDefault();
  ev.stopPropagation();
}

app.registerExtension({
  name: "pcg.netbox",
  settings: [
    { id: PALETTE_ID, category: ["PCG", "Houdini feel", "Colour palette"],
      name: "C opens the colour palette for the selected nodes and boxes", type: "boolean", defaultValue: true },
  ],
  getNodeMenuItems(node) {
    return [null, { content: "PCG: Colour Palette…", callback: () => {
      const items = selectedItems(app.canvas);
      openPalette(items.length ? items : [node], MOUSE[0], MOUSE[1]);
    } }];
  },
  async setup() {
    document.addEventListener("pointermove", (e) => { MOUSE = [e.clientX, e.clientY]; }, { passive: true });
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", (e) => { if (POP && !POP.contains(e.target)) closePalette(); }, true);
    // the group's context menu: collapse / expand
    const LGG = globalThis.LiteGraph?.LGraphGroup ?? globalThis.LGraphGroup;
    const proto = LGG?.prototype;
    if (proto?.getMenuOptions && !proto.getMenuOptions.__pcg) {
      const orig = proto.getMenuOptions;
      proto.getMenuOptions = function (...a) {
        const opts = orig.apply(this, a) || [];
        const g = this;
        opts.push(null, isCollapsed(g)
          ? { content: "PCG: Expand Box", callback: () => expandBox(g) }
          : { content: "PCG: Collapse Box", callback: () => collapseBox(g) });
        return opts;
      };
      proto.getMenuOptions.__pcg = true;
    }
  },
});
