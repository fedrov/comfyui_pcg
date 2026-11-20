// comfyui_pcg/web/pcg_edge.js
//
// Tabs on the window's right edge that bring back a hidden pane (Parameters, Performance). One column, so the tabs
// of several panes stack instead of covering each other.

const CSS = `
.pcg-edge{position:fixed;right:0;top:36%;z-index:899;display:flex;flex-direction:column;gap:6px;pointer-events:none}
.pcg-edge button{pointer-events:auto;writing-mode:vertical-rl;padding:10px 3px;cursor:pointer;border:1px solid #3a4150;
  border-right:none;border-radius:6px 0 0 6px;background:#23272f;color:#c8d0dc;
  font:11px Inter,"Segoe UI",system-ui,sans-serif;box-shadow:0 2px 10px #0006}
.pcg-edge button:hover{background:#3c5a86;color:#eaf2ff}
`;

function column() {
  let c = document.querySelector(".pcg-edge");
  if (c) return c;
  if (!document.getElementById("pcg-edge-css")) {
    const st = document.createElement("style");
    st.id = "pcg-edge-css";
    st.textContent = CSS;
    document.head.appendChild(st);
  }
  c = document.createElement("div");
  c.className = "pcg-edge";
  document.body.appendChild(c);
  return c;
}

/** A tab on the right edge; returns the button (hide it with style.display while its pane is open). */
export function edgeTab(label, title, onclick, order = 0) {
  const b = document.createElement("button");
  b.textContent = label;
  b.title = title;
  b.dataset.order = String(order);
  b.onclick = onclick;
  const c = column();
  const after = [...c.children].find((x) => Number(x.dataset.order) > order);
  c.insertBefore(b, after || null);
  return b;
}

/**
 * A floating pane: title bar (drag), body, resize grip at the bottom left, ✕ (hide). Position and size are kept in
 * localStorage under key. Returns {root, head, title, body, setOpen(on), isOpen()}.
 */
export function floatingPane({ key, title, rect, cls = "", z = 900, onOpen = null, open = true }) {
  const S = { rect: { ...rect }, open };
  try {
    const o = JSON.parse(localStorage.getItem(key) || "null");
    if (o?.rect) Object.assign(S.rect, o.rect);
    if (typeof o?.open === "boolean") S.open = o.open;
  } catch (_) { /* private mode */ }
  const save = () => {
    try { localStorage.setItem(key, JSON.stringify({ rect: S.rect, open: S.open })); } catch (_) { /* */ }
  };
  const root = document.createElement("div");
  root.className = "pcgfloat " + cls;
  root.style.cssText = `position:fixed;z-index:${z};display:flex;flex-direction:column;background:#1b1e23;` +
    "border:1px solid #333a46;border-radius:6px;box-shadow:0 6px 24px #0008;" +
    "font:12px Inter,'Segoe UI',system-ui,sans-serif;color:#cfd5dc";
  const head = document.createElement("div");
  head.style.cssText = "display:flex;align-items:center;gap:6px;padding:4px 6px;background:#1e222a;" +
    "border-bottom:1px solid #333a46;border-radius:6px 6px 0 0;cursor:move;flex:0 0 auto;user-select:none";
  const ttl = document.createElement("span");
  ttl.style.cssText = "color:#dde3ea;font-weight:600;flex:1 1 auto;white-space:nowrap;overflow:hidden;text-overflow:ellipsis";
  ttl.textContent = title;
  head.appendChild(ttl);
  const close = document.createElement("button");
  close.textContent = "✕";
  close.title = "Hide (the tab on the window's right edge brings it back)";
  close.style.cssText = "flex:0 0 auto;width:22px;height:20px;border:1px solid #3a4150;border-radius:3px;" +
    "background:#2a2f3a;color:#c8d0dc;cursor:pointer;font:11px ui-monospace,monospace;padding:0";
  head.appendChild(close);
  const body = document.createElement("div");
  body.style.cssText = "flex:1 1 auto;overflow:auto;padding:4px;min-height:40px";
  const grip = document.createElement("div");
  grip.style.cssText = "position:absolute;left:0;bottom:0;width:14px;height:14px;cursor:nesw-resize";
  root.append(head, body, grip);
  document.body.appendChild(root);
  const clamp = () => {
    const r = S.rect;
    r.w = Math.max(240, Math.min(r.w, innerWidth - 8));
    r.h = Math.max(140, Math.min(r.h, innerHeight - 8));
    r.x = Math.max(0, Math.min(r.x, innerWidth - 60));
    r.y = Math.max(0, Math.min(r.y, innerHeight - 30));
  };
  const place = () => {
    clamp();
    Object.assign(root.style, { left: S.rect.x + "px", top: S.rect.y + "px", width: S.rect.w + "px",
                                height: S.rect.h + "px" });
  };
  place();
  let mode = null, x0 = 0, y0 = 0, r0 = null;
  const down = (kind) => (ev) => {
    if (ev.button !== 0 || ev.target.closest?.("button")) return;
    mode = kind; x0 = ev.clientX; y0 = ev.clientY; r0 = { ...S.rect };
    ev.target.setPointerCapture?.(ev.pointerId);
    ev.preventDefault();
    ev.stopPropagation();
  };
  head.addEventListener("pointerdown", down("move"));
  grip.addEventListener("pointerdown", down("size"));
  addEventListener("pointermove", (ev) => {
    if (!mode) return;
    const dx = ev.clientX - x0, dy = ev.clientY - y0;
    if (mode === "move") { S.rect.x = r0.x + dx; S.rect.y = r0.y + dy; }
    else { S.rect.x = r0.x + dx; S.rect.w = r0.w - dx; S.rect.h = r0.h + dy; }
    place();
  });
  const up = () => { if (mode) { mode = null; save(); } };
  addEventListener("pointerup", up);
  addEventListener("pointercancel", up);
  let tab = null;
  const setOpen = (on) => {
    S.open = !!on;
    root.style.display = S.open ? "flex" : "none";
    if (tab) tab.style.display = S.open ? "none" : "";
    save();
    if (S.open) onOpen?.();
  };
  close.onclick = (e) => { e.stopPropagation(); setOpen(false); };
  return {
    root, head, title: ttl, body, setOpen, isOpen: () => S.open, rect: S.rect,
    withTab(label, tip, order) { tab = edgeTab(label, tip, () => setOpen(true), order); setOpen(S.open); return tab; },
  };
}
