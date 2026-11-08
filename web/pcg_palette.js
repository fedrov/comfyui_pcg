// comfyui_pcg/web/pcg_palette.js
//
// Tab at the mouse opens a search panel containing **only PCG nodes**, matching Houdini's Tab menu.
//
// Why write our own instead of reusing ComfyUI's search box:
//   · that search box lists all nodes (thousands after installing dozens of plugins); finding a PCG
//     node means typing a prefix filter first, far from Houdini where Tab directly shows the nodes of this network type.
//   · its opening and filtering logic is internal to the frontend and changes a lot between versions; hooking it is unreliable.
//
// Events use a **capture listener on the canvas element**, not litegraph's key dispatch -- that behaves inconsistently
// across frontend versions (collapsing section headers tripped over it before). The panel itself is plain DOM,
// does not touch the widget system, and does not modify the node.widgets array.

import { app } from "../../scripts/app.js";

const PREFIX = "PCG_";
let panel = null, listEl = null, inputEl = null;
let items = [], filtered = [], active = 0;
let dropAt = [0, 0];
const mouse = { x: 0, y: 0 };

function isTyping(t) {
  return t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable);
}

function collect() {
  const types = LiteGraph.registered_node_types || {};
  const out = [];
  for (const [type, cls] of Object.entries(types)) {
    if (!type.startsWith(PREFIX)) continue;
    const title = cls.title || type;
    const cat = cls.category || "";
    out.push({ type, title, cat, key: (title + " " + cat + " " + type).toLowerCase() });
  }
  out.sort((a, b) => (a.cat + a.title).localeCompare(b.cat + b.title));
  return out;
}

// Subsequence match: typed characters only need to appear in order; consecutive hits score more, word-initial hits score more again.
// So "pe" matches PolyExtrude and "grcr" matches Group Create --
// that is how Houdini's Tab menu feels; no need to type the full name.
function score(hay, needle) {
  if (!needle) return 0;
  let i = 0, s = 0, streak = 0;
  for (let j = 0; j < hay.length && i < needle.length; j++) {
    if (hay[j] === needle[i]) {
      s += 1 + streak * 2 + (j === 0 || hay[j - 1] === " " ? 3 : 0);
      streak++;
      i++;
    } else streak = 0;
  }
  return i === needle.length ? s : -1;
}

function build() {
  panel = document.createElement("div");
  panel.style.cssText = `position:fixed;z-index:10000;display:none;width:340px;
    background:#1c2027;border:1px solid #3a4049;border-radius:8px;
    box-shadow:0 8px 32px rgba(0,0,0,.55);overflow:hidden;
    font:13px ui-monospace,Menlo,Consolas,monospace;color:#dde3ea`;
  inputEl = document.createElement("input");
  inputEl.placeholder = "PCG nodes…";
  inputEl.style.cssText = `width:100%;box-sizing:border-box;padding:9px 12px;
    background:#232830;border:0;border-bottom:1px solid #3a4049;
    color:#e6ebf2;outline:none;font:inherit`;
  listEl = document.createElement("div");
  listEl.style.cssText = "max-height:340px;overflow-y:auto";
  panel.append(inputEl, listEl);
  document.body.appendChild(panel);

  inputEl.addEventListener("input", () => render());
  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || (e.key === "n" && e.ctrlKey)) {
      active = Math.min(active + 1, filtered.length - 1); render(true); e.preventDefault();
    } else if (e.key === "ArrowUp" || (e.key === "p" && e.ctrlKey)) {
      active = Math.max(active - 1, 0); render(true); e.preventDefault();
    } else if (e.key === "Enter") {
      create(filtered[active]); e.preventDefault();
    } else if (e.key === "Escape" || e.key === "Tab") {
      close(); e.preventDefault();
    }
    e.stopPropagation();          // don't let keys leak to the canvas and trigger other shortcuts
  });
  document.addEventListener("pointerdown", (e) => {
    if (panel.style.display !== "none" && !panel.contains(e.target)) close();
  }, true);
}

function render(keepQuery) {
  const q = inputEl.value.trim().toLowerCase();
  filtered = !q ? items.slice()
    : items.map((it) => ({ it, s: score(it.key, q) }))
           .filter((x) => x.s >= 0)
           .sort((a, b) => b.s - a.s)
           .map((x) => x.it);
  if (!keepQuery) active = 0;
  active = Math.max(0, Math.min(active, filtered.length - 1));

  listEl.innerHTML = "";
  filtered.forEach((it, i) => {
    const row = document.createElement("div");
    row.style.cssText = `padding:7px 12px;cursor:pointer;display:flex;
      justify-content:space-between;gap:12px;
      background:${i === active ? "#2f5d80" : "transparent"}`;
    const cat = it.cat.replace(/^.*?\//, "");
    row.innerHTML = `<span>${it.title.replace(/\s*\(PCG\)$/, "")}</span>` +
                    `<span style="color:#7d8590;font-size:11px">${cat}</span>`;
    row.addEventListener("pointerenter", () => { active = i; render(true); });
    row.addEventListener("pointerdown", (e) => { e.preventDefault(); create(it); });
    listEl.appendChild(row);
  });
  if (!filtered.length)
    listEl.innerHTML = `<div style="padding:10px 12px;color:#7d8590">No matching nodes</div>`;
  const sel = listEl.children[active];
  sel?.scrollIntoView?.({ block: "nearest" });
}

function create(it) {
  if (!it) return;
  const node = LiteGraph.createNode(it.type);
  if (!node) return;
  app.graph.beforeChange?.();
  app.graph.add(node);
  node.pos = [dropAt[0], dropAt[1]];
  app.graph.afterChange?.();
  app.canvas?.selectNode?.(node);
  close();
  app.graph.setDirtyCanvas(true, true);
}

function close() {
  if (panel) panel.style.display = "none";
  app.canvas?.canvas?.focus?.();
}

function open() {
  if (!panel) build();
  items = collect();
  if (!items.length) return;

  const canvas = app.canvas;
  const el = canvas.canvas;
  // The node lands at the graph coordinates under the mouse
  if (canvas.convertEventToCanvasOffset) {
    dropAt = canvas.convertEventToCanvasOffset(
      { clientX: mouse.x, clientY: mouse.y });
  } else {
    const r = el.getBoundingClientRect(), ds = canvas.ds;
    dropAt = [(mouse.x - r.left) / ds.scale - ds.offset[0],
              (mouse.y - r.top) / ds.scale - ds.offset[1]];
  }
  panel.style.display = "block";
  panel.style.left = Math.min(mouse.x, window.innerWidth - 360) + "px";
  panel.style.top = Math.min(mouse.y, window.innerHeight - 400) + "px";
  inputEl.value = "";
  active = 0;
  render();
  inputEl.focus();
}

app.registerExtension({
  name: "pcg.palette",

  async setup() {
    const el = app.canvas?.canvas;
    if (!el) {
      console.warn("[pcg.palette] cannot get the canvas, Tab panel disabled");
      return;
    }
    el.addEventListener("pointermove", (e) => {
      mouse.x = e.clientX; mouse.y = e.clientY;
    }, true);

    window.addEventListener("keydown", (e) => {
      if (e.key !== "Tab" || e.ctrlKey || e.altKey || e.metaKey) return;
      if (isTyping(e.target)) return;
      if (panel && panel.style.display !== "none") return;
      // Don't take over Tab when the mouse is not on the canvas, so normal focus switching isn't swallowed
      const r = el.getBoundingClientRect();
      if (mouse.x < r.left || mouse.x > r.right ||
          mouse.y < r.top || mouse.y > r.bottom) return;
      e.preventDefault();
      e.stopImmediatePropagation();   // also block other listeners on the same element
      open();
    }, true);

    console.log("[pcg.palette] enabled: press Tab with the mouse over the canvas to bring up PCG nodes");
  },
});
