// comfyui_pcg/web/pcg_typehint.js
//
// After a node is renamed (title), you can no longer tell what node it was -- is "tree proxy" a Tube or a
// Sphere? You'd have to right-click into the properties panel and dig for "Node name for S&R". In Houdini's network view a renamed
// node always shows its type next to it; we do the same here:
//
//   · for nodes whose title was changed, the original type is written in small dimmer text **after** the title text:  tree proxy  Tube
//     (PCG nodes drop the " (PCG)" suffix of the display name; the source badge at top right already says which plugin)
//   · two extra context-menu items: "Original node: Tube (PCG)" (full name + internal class name), "Restore original name"
//   · setting PCG -> Show original type on renamed nodes: All nodes / PCG nodes only / Off
//
// A few trade-offs:
//   · drawn after the title text, not at the right end of the title bar: the right end is where the frontend's source badge / collapse button go,
//     with different positions in different versions; right after the title text is least likely to collide. If it doesn't fit after the title (node too narrow,
//     title too long and truncated) it isn't drawn -- better not drawn than drawn over something else. The context-menu item is always there
//   · only drawn; node.title is not changed and nothing goes into the workflow: what's saved is still the name the user gave
//   · not drawn when zoomed far out (canvas scale < 0.5); text is unreadable at that size anyway
//   · all drawing is wrapped in try/catch; a drawing failure must not take down the canvas

import { app } from "../../scripts/app.js";

export const SETTING_ID = "PCG.RenamedNodeTypeHint";
export const MODES = ["All nodes", "PCG nodes only", "Off"];
// Values saved by older versions (Chinese UI), still accepted when read
export const LEGACY_MODES = {
  "\u5168\u90e8\u8282\u70b9": MODES[0],
  "\u53ea\u6709 PCG \u8282\u70b9": MODES[1],
  "\u5173": MODES[2],
};

export function mode() {
  try {
    const v = app.extensionManager?.setting?.get?.(SETTING_ID)
      ?? app.ui?.settings?.getSettingValue?.(SETTING_ID);
    return LEGACY_MODES[v] || v || MODES[0];   // unknown values fall into the "All nodes" branch, no separate check needed
  } catch (e) {
    return MODES[0];
  }
}

// Original type shown to people: PCG nodes drop the " (PCG)" suffix
export function shortType(nodeData) {
  const dn = String(nodeData?.display_name || nodeData?.name || "");
  return dn.replace(/\s*\(PCG\)\s*$/, "");
}

export function isRenamed(node, nodeData) {
  const t = String(node?.title ?? "").trim();
  if (!t) return false;
  const defaults = [nodeData?.display_name, nodeData?.name,
                    node?.constructor?.title]
    .filter(Boolean).map((s) => String(s).trim());
  return !defaults.includes(t);
}

export function enabledFor(nodeData) {
  const m = mode();
  if (m === MODES[2]) return false;
  if (m === MODES[1]) return String(nodeData?.name || "").startsWith("PCG_");
  return true;
}

function titleFont() {
  const LG = globalThis.LiteGraph || {};
  return app.canvas?.title_text_font
    || `${LG.NODE_TEXT_SIZE ?? 14}px ${LG.NODE_FONT ?? "Arial"}`;
}

// Compute where the hint is drawn: returns {x, y, text, font} or null (don't draw)
export function layout(node, nodeData, ctx) {
  if (!enabledFor(nodeData) || !isRenamed(node, nodeData)) return null;
  if (node.flags?.collapsed) return null;
  const scale = app.canvas?.ds?.scale ?? 1;
  if (scale < 0.5) return null;
  const LG = globalThis.LiteGraph || {};
  const h = LG.NODE_TITLE_HEIGHT ?? 30;
  const size = (LG.NODE_TEXT_SIZE ?? 14);
  ctx.save();
  ctx.font = titleFont();
  const tw = ctx.measureText(String(node.title)).width;
  const small = `${Math.round(size * 0.82)}px ${LG.NODE_FONT ?? "Arial"}`;
  ctx.font = small;
  const text = shortType(nodeData);
  const w = ctx.measureText(text).width;
  ctx.restore();
  // The title text starts at x ≈ title bar height (the title box / icon is on the left)
  const x = h + tw + 10;
  if (!text || x + w > node.size[0] - 8) return null;
  return { x, y: -h * 0.5, text, font: small };
}

app.registerExtension({
  name: "pcg.typehint",
  settings: [{
    id: SETTING_ID,
    category: ["PCG", "Nodes", "Show original type on renamed nodes"],
    name: "Show the original type after the title of renamed nodes",
    type: "combo",
    options: MODES,
    defaultValue: MODES[0],
    onChange: () => app.graph?.setDirtyCanvas?.(true, true),
  }],
  async beforeRegisterNodeDef(nodeType, nodeData) {
    const prevDraw = nodeType.prototype.onDrawForeground;
    nodeType.prototype.onDrawForeground = function (ctx) {
      const r = prevDraw?.apply(this, arguments);
      try {
        const L = layout(this, nodeData, ctx);
        if (L) {
          ctx.save();
          ctx.font = L.font;
          ctx.textAlign = "left";
          ctx.textBaseline = "middle";
          ctx.fillStyle = "rgba(200, 205, 212, 0.5)";
          ctx.fillText(L.text, L.x, L.y);
          ctx.restore();
        }
      } catch (e) {
        /* a hint drawing failure must not take down the canvas */
      }
      return r;
    };

    const prevMenu = nodeType.prototype.getExtraMenuOptions;
    nodeType.prototype.getExtraMenuOptions = function (canvas, options) {
      const r = prevMenu?.apply(this, arguments);
      try {
        if (!isRenamed(this, nodeData) || !Array.isArray(options)) return r;
        const full = String(nodeData?.display_name || nodeData?.name || "");
        const cls = String(nodeData?.name || "");
        options.push(null, {
          content: `Original node: ${full}${cls && cls !== full ? `  [${cls}]` : ""}`,
          disabled: true,
        }, {
          content: `Restore original name (${full})`,
          callback: () => {
            this.title = full;
            app.graph?.setDirtyCanvas?.(true, true);
          },
        });
      } catch (e) {
        /* failing to add a menu item must not stop the whole context menu from opening */
      }
      return r;
    };
  },
});
