// comfyui_pcg/web/pcg_groups.js
//
// Value hints for group parameters: right-click a node -> "Fill in group" -> pick a group that actually exists upstream.
//
// Why a context menu rather than a dropdown:
//   · the group field takes not only group names but also expressions like the index range 0-10:2 or @P.y > 0; as a combo
//     it could no longer be typed by hand -- and typing by hand is exactly how this field is used most.
//   · adding a dropdown button to the text box means either inserting into the widgets array (which shifts all parameters when
//     the workflow is restored) or intercepting clicks (all three ways of doing that are unreliable on this frontend version).
//   getExtraMenuOptions is an official hook; it touches neither the widgets array nor event dispatch, so it is reliable.
//
// Where group names come from: when a node cooks, groups_report.py pushes them via {"ui": {"pcg_groups": ...}};
// here we listen to the executed event and cache them, indexed by **upstream node id**.
// So upstream has to run once before there are choices -- just like Houdini needs upstream to have cooked.

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Two caches: group names and attribute names. node id -> { point:[], vertex:[], prim:[], ... }
const CACHE = new Map();
const ACACHE = new Map();
const CLS_LABEL = { point: "point", vertex: "vertex", prim: "prim",
                    edge: "edge", detail: "detail" };

api.addEventListener("executed", (e) => {
  const g = e.detail?.output?.pcg_groups?.[0];
  if (g && typeof g === "object") CACHE.set(String(e.detail.node), g);
  const a = e.detail?.output?.pcg_attribs?.[0];
  if (a && typeof a === "object") ACACHE.set(String(e.detail.node), a);
});
// ★ Do not clear the cache on execution_start. ComfyUI skips unchanged nodes, and skipped
//   nodes don't send executed -- once cleared it can never be refilled; the symptom is "it ran but says there are no groups".
//   Entries are stored per node id and naturally overwritten when that node runs again; a bit of stale data now and then beats nothing.

// Returns [{widget, kind, cls}]:
//   is_group        -> group expression field (takes group names / indices / @expressions), lists groups of all classes
//   name_kind/cls   -> fields dedicated to names of one class (Attribute Delete / Group Delete)
function nameWidgets(node) {
  const defs = node.constructor?.nodeData?.input || {};
  const meta = new Map();
  for (const grp of ["required", "optional"]) {
    for (const [k, spec] of Object.entries(defs[grp] || {})) {
      const o = Array.isArray(spec) ? spec[1] : null;
      if (!o) continue;
      if (o.name_kind) meta.set(k, { kind: o.name_kind, cls: o.name_cls });
      else if (o.is_group) meta.set(k, { kind: "group", cls: null });
    }
  }
  return (node.widgets || [])
    .filter((w) => meta.has(w.name))
    .map((w) => ({ widget: w, ...meta.get(w.name) }));
}

// Look upstream for groups. **Only the input side, never the groups the node itself outputs** -- a group parameter selects
// groups on the input geometry, and the node's own output often carries newly created groups (PolyExtrude outputs
// extrudeFront/Back/Side); mixing them in would only crowd out the upstream groups you actually want.
//
// The chain may contain a series of transform nodes that create no groups, so trace back along GEOMETRY inputs all the way;
// for multi-input nodes (Merge) the groups of all branches are merged.
function mergeInto(acc, g) {
  for (const cls of ["point", "vertex", "prim", "edge", "detail"])
    for (const n of g?.[cls] || []) {
      acc[cls] = acc[cls] || [];
      if (!acc[cls].includes(n)) acc[cls].push(n);
    }
}

// Get the upstream node. getInputNode is unavailable or returns null on some frontend versions,
// so add a fallback path that resolves the link by hand.
function upstreamOf(node, i) {
  const n = node.getInputNode?.(i);
  if (n) return n;
  const linkId = node.inputs?.[i]?.link;
  if (linkId == null) return null;
  const links = app.graph?.links;
  const link = links instanceof Map ? links.get(linkId) : links?.[linkId];
  return link ? app.graph.getNodeById(link.origin_id) : null;
}

function inputNames(node, store, depth = 0, acc = {}, seen = new Set()) {
  if (!node || depth > 12) return acc;
  for (let i = 0; i < (node.inputs?.length || 0); i++) {
    const t = node.inputs[i].type;
    if (t !== "GEOMETRY" && t !== "*") continue;
    const up = upstreamOf(node, i);
    if (!up || seen.has(up.id)) continue;
    seen.add(up.id);
    const hit = store.get(String(up.id));
    if (hit) mergeInto(acc, hit);          // keep going upstream even on a hit, merging earlier ones
    inputNames(up, store, depth + 1, acc, seen);
  }
  return acc;
}

// For the ▾ button of the parameter panel (pcg_panel.js): names that actually exist upstream -> [{c, n}].
// kind = "attrib" looks up attribute names, anything else group names; if cls is given only that class is listed
export function upstreamNames(node, kind, cls) {
  const src = inputNames(node, kind === "attrib" ? ACACHE : CACHE);
  const out = [];
  for (const c of cls ? [cls] : ["point", "vertex", "prim", "edge"])
    for (const n of src?.[c] || []) out.push({ c, n });
  return out;
}

app.registerExtension({
  name: "pcg.groups",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    const marked = ["required", "optional"].some((g) =>
      Object.values(nodeData?.input?.[g] || {}).some(
        (spec) => Array.isArray(spec) && (spec[1]?.is_group || spec[1]?.name_kind)));
    if (!marked) return;
    nodeType.nodeData = nodeData;

    const orig = nodeType.prototype.getExtraMenuOptions;
    nodeType.prototype.getExtraMenuOptions = function (canvas, options) {
      orig?.apply(this, arguments);
      const items = nameWidgets(this);
      if (!items.length) return;

      const gAll = inputNames(this, CACHE);
      const aAll = inputNames(this, ACACHE);
      let any = false;

      for (const { widget, kind, cls } of items) {
        const src = kind === "attrib" ? aAll : gAll;
        // If a class is specified only that class is listed, otherwise (group expression field) all classes
        const entries = [];
        for (const c of cls ? [cls] : ["point", "vertex", "prim", "edge"])
          for (const n of src?.[c] || []) entries.push({ c, n });
        if (!entries.length) continue;
        any = true;

        const label = kind === "attrib" ? "Fill in attribute" : "Fill in group";
        const fill = (v) => {
          widget.value = v;
          widget.callback?.(v, canvas, this);
          app.graph?.setDirtyCanvas(true, true);
        };
        options.push({
          content: items.length > 1 ? `${label} → ${widget.name}` : label,
          has_submenu: true,
          callback: (v, opts, e, menu) => {
            const one = entries.map((x) => ({
              content: cls ? x.n : `${CLS_LABEL[x.c]}:${x.n}`,
              callback: () => fill(x.n),
            }));
            const add = entries.map((x) => ({
              content: `+ ${x.n}`,
              callback: () => fill((widget.value ? widget.value + " " : "") + x.n),
            }));
            new LiteGraph.ContextMenu(
              one.concat([{ content: "── Append ──", disabled: true }], add),
              { event: e, parentMenu: menu, title: label });
            return false;
          },
        });
      }
      if (!any)
        options.push({ content: "No names upstream to fill in (run the whole chain once and try again)",
                       disabled: true });
    };
  },
});
