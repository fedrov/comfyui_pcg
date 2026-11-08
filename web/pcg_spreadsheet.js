// comfyui_pcg/web/pcg_spreadsheet.js
//
// Frontend of the Geometry Spreadsheet. Four class tabs, one table per tab.
// Layout follows Houdini's Geometry Spreadsheet: fixed row-number column on the left, two header rows
// (attribute name + component), numbers right-aligned monospace, pseudo-columns (pt/prim/nvtx) dimmed to set them apart.

import { app } from "../../scripts/app.js";

const CLASSES = ["point", "vertex", "prim", "detail"];
const CLASS_COLOR = {
  point: "#7ab8ea", vertex: "#c0a0f5", prim: "#6fd9a8", detail: "#e0b073",
};
const COMP = ["x", "y", "z", "w"];

const CSS = `
.pcg-ss{position:absolute;inset:0;display:flex;flex-direction:column;
  background:#191b1f;border-radius:4px;overflow:hidden;
  font:11px ui-monospace,"SF Mono",Menlo,Consolas,monospace;color:#c8ccd4}
.pcg-ss-tabs{display:flex;gap:1px;background:#101216;flex:0 0 auto}
.pcg-ss-tabs button{flex:1;background:#1f2228;border:0;color:#7d8590;
  padding:5px 4px;font:inherit;cursor:pointer;border-bottom:2px solid transparent}
.pcg-ss-tabs button:hover{background:#262a31;color:#c8ccd4}
.pcg-ss-tabs button.on{background:#23262d;color:#e6e9ee}
.pcg-ss-tabs .n{opacity:.55;margin-left:4px}
.pcg-ss-body{flex:1 1 auto;overflow:auto;position:relative}
.pcg-ss table{border-collapse:separate;border-spacing:0;width:max-content;
  min-width:100%}
.pcg-ss th,.pcg-ss td{padding:2px 8px;white-space:nowrap;text-align:right;
  border-bottom:1px solid #23262d}
.pcg-ss thead th{position:sticky;top:0;z-index:2;background:#1f2228;
  color:#9aa3ad;font-weight:600;border-bottom:1px solid #343a43}
.pcg-ss thead tr.sub th{top:19px;font-weight:400;color:#6e7681;font-size:10px}
.pcg-ss th.attr{text-align:center;border-left:1px solid #343a43}
.pcg-ss th.meta,.pcg-ss td.meta{color:#6e7681;background:#1c1e23}
.pcg-ss td.str{text-align:left;color:#d8c48a}
.pcg-ss td.grp{color:#6e7681}
.pcg-ss td.grp.in{background:#c9762a;color:#fff;font-weight:600}
.pcg-ss tr.member td{background:#3a2c1c}
.pcg-ss tr.member td.idx{background:#4a3620;color:#e8c79a}
.pcg-ss tbody tr.member:hover td{background:#463522}
.pcg-ss td.idx,.pcg-ss th.idx{position:sticky;left:0;z-index:1;background:#1c1e23;
  color:#6e7681;text-align:right;border-right:1px solid #343a43}
.pcg-ss thead th.idx{z-index:3}
.pcg-ss tbody tr:hover td{background:#252932}
.pcg-ss tbody tr:hover td.idx{background:#2b303a}
.pcg-ss-foot{flex:0 0 auto;padding:3px 8px;background:#1f2228;color:#6e7681;
  border-top:1px solid #23262d;display:flex;justify-content:space-between;gap:8px}
.pcg-ss-empty{padding:14px;color:#6e7681}
.pcg-ss-pager{display:flex;gap:3px;align-items:center}
.pcg-ss-pager button{background:#262a31;border:1px solid #343a43;color:#c8ccd4;font:inherit;
  padding:0 6px;border-radius:3px;cursor:pointer}
.pcg-ss-pager button:disabled{opacity:.35;cursor:default}
.pcg-ss-pager input{width:64px;background:#111317;border:1px solid #343a43;color:#e6e9ee;font:inherit;
  padding:0 4px;border-radius:3px;text-align:right}
`;

// pcg122: pages come from GET /pcg/sheet/{node} (server-side cache) -- no re-execution, the widgets stay as they are
export async function fetchPage(nodeId, cls, start, rows, fetchFn = globalThis.fetch) {
  const res = await fetchFn(`/pcg/sheet/${encodeURIComponent(nodeId)}?cls=${cls}&start=${start}&rows=${rows}`);
  if (!res.ok) throw new Error(res.status === 404 ? "not cached -- run the node again" : await res.text());
  return res.json();
}

/** Start row of the page `dir` away (first / prev / next / last), clamped. */
export function pageStart(start, rows, count, dir) {
  const last = Math.max(0, Math.floor(Math.max(0, count - 1) / rows) * rows);
  const s = dir === "first" ? 0 : dir === "last" ? last : dir === "prev" ? start - rows : dir === "next" ? start + rows : start;
  return Math.max(0, Math.min(s, last));
}

function fmt(v, kind) {
  if (v === null || v === undefined) return "—";
  if (kind === "s") return v === "" ? "—" : String(v);
  if (kind === "g") return v ? "1" : "0";
  if (kind === "i" || kind === "b" || kind === "u") return String(Math.round(v));
  if (v === 0) return "0";
  const a = Math.abs(v);
  if (a >= 1e6 || a < 1e-4) return v.toExponential(2);
  return v.toFixed(a >= 100 ? 2 : 4);
}

export class Sheet {
  constructor(root) {
    this.root = root;
    this.cls = "point";
    this.data = null;

    if (!document.getElementById("pcg-ss-style")) {
      const st = document.createElement("style");
      st.id = "pcg-ss-style";
      st.textContent = CSS;
      document.head.appendChild(st);
    }

    root.classList.add("pcg-ss");
    this.tabs = document.createElement("div");
    this.tabs.className = "pcg-ss-tabs";
    this.body = document.createElement("div");
    this.body.className = "pcg-ss-body";
    this.foot = document.createElement("div");
    this.foot.className = "pcg-ss-foot";
    root.append(this.tabs, this.body, this.foot);

    // The table must scroll itself; don't let the wheel bubble up to litegraph and zoom the canvas
    this.body.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });
    root.addEventListener("pointerdown", (e) => e.stopPropagation());

    for (const c of CLASSES) {
      const b = document.createElement("button");
      b.dataset.cls = c;
      b.onclick = () => { this.cls = c; this.render(); };
      this.tabs.appendChild(b);
    }
    this.render();
  }

  setData(d) { this.data = d; this.note = ""; this.render(); }

  async goto(start, fetchFn) {
    const d = this.data;
    if (!d || this.cls === "detail") return;
    const t = d.tables[this.cls];
    const rows = d.rows || t.rows.length || 64;
    start = Math.max(0, Math.min(start | 0, Math.max(0, t.count - 1)));
    try {
      const j = await fetchPage(d.node_id, this.cls, start, rows, fetchFn);
      if (this.data !== d) return;               // re-executed meanwhile
      d.tables[j.cls] = j.table;
      this.note = "";
    } catch (err) {
      this.note = String(err.message || err);
    }
    this.render();
  }

  render() {
    const d = this.data;
    for (const b of this.tabs.children) {
      const c = b.dataset.cls;
      const n = d ? d.counts[c] : 0;
      b.innerHTML = `${c}<span class="n">${d ? n : "-"}</span>`;
      b.classList.toggle("on", c === this.cls);
      b.style.borderBottomColor = c === this.cls ? CLASS_COLOR[c] : "transparent";
    }
    if (!d) {
      this.body.innerHTML = `<div class="pcg-ss-empty">No data yet -- run once to get some</div>`;
      this.foot.textContent = "";
      return;
    }

    const t = d.tables[this.cls];
    if (!t.cols.length || !t.rows.length) {
      this.body.innerHTML =
        `<div class="pcg-ss-empty">No attributes on ${this.cls} (${t.count} elements)</div>`;
    } else {
      const head = [`<tr><th class="idx" rowspan="2">#</th>`];
      const sub = ['<tr class="sub">'];
      for (const c of t.cols) {
        const cls = c.meta ? "attr meta" : "attr";
        head.push(`<th class="${cls}" colspan="${c.size}">${c.name}</th>`);
        for (let i = 0; i < c.size; i++)
          sub.push(`<th class="${c.meta ? "meta" : ""}">${
            c.size > 1 ? COMP[i] ?? i : ""}</th>`);
      }
      head.push("</tr>"); sub.push("</tr>");

      // kind / meta per column, expanded into a flat table indexed by component
      const kinds = [], metas = [];
      for (const c of t.cols)
        for (let i = 0; i < c.size; i++) { kinds.push(c.kind); metas.push(c.meta); }

      const rows = t.rows.map((r, i) => {
        // Rows belonging to any group are highlighted as a whole, matching Houdini
        const member = r.some((v, j) => kinds[j] === "g" && v);
        const tds = r.map((v, j) => {
          let cl = metas[j] ? "meta " : "";
          if (kinds[j] === "s") cl += "str";
          else if (kinds[j] === "g") cl += v ? "grp in" : "grp";
          return `<td class="${cl}">${fmt(v, kinds[j])}</td>`;
        }).join("");
        return `<tr class="${member ? "member" : ""}">` +
               `<td class="idx">${t.start + i}</td>${tds}</tr>`;
      }).join("");

      this.body.innerHTML =
        `<table><thead>${head.join("")}${sub.join("")}</thead><tbody>${rows}</tbody></table>`;
    }

    const t2 = d.tables[this.cls];
    const shown = t2.rows.length;
    const range = shown ? `${t2.start}–${t2.start + shown - 1}` : "—";
    const grp = t2.groups.length ? `groups: ${t2.groups.join(", ")}` : "";
    const bb = d.bbox;
    const rows = d.rows || shown || 64;
    const pager = this.cls === "detail" || t2.count <= rows ? "" :
      `<span class="pcg-ss-pager"><button data-go="first" title="First page">⏮</button>` +
      `<button data-go="prev" title="Previous page">◀</button>` +
      `<input data-go="row" title="Jump to row (Enter)" value="${t2.start}">` +
      `<button data-go="next" title="Next page">▶</button>` +
      `<button data-go="last" title="Last page">⏭</button></span>`;
    this.foot.innerHTML =
      `<span>Showing ${range} / ${t2.count} total${grp ? "  ·  " + grp : ""}` +
      `${this.note ? "  ·  " + this.note : ""}</span>` + pager +
      `<span>bbox [${bb[0].map((v) => (+v).toFixed(2)).join(", ")}] .. ` +
      `[${bb[1].map((v) => (+v).toFixed(2)).join(", ")}]</span>`;
    for (const b of this.foot.querySelectorAll("button[data-go]")) {
      const dir = b.dataset.go;
      const to = pageStart(t2.start, rows, t2.count, dir);
      b.disabled = to === t2.start;
      b.onclick = () => this.goto(to);
    }
    const inp = this.foot.querySelector("input[data-go]");
    if (inp) inp.onkeydown = (e) => {
      e.stopPropagation();
      if (e.key === "Enter") this.goto(parseInt(inp.value, 10) || 0);
    };
  }
}

app.registerExtension({
  name: "pcg.spreadsheet",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "PCG_GeoSpreadsheet") return;

    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onCreated?.apply(this, arguments);
      const el = document.createElement("div");
      Object.assign(el.style, { width: "100%", height: "100%", minHeight: "260px",
                                position: "relative" });
      this.addDOMWidget("sheet", "div", el, { hideOnZoom: false });
      this._pcgSheet = new Sheet(el);
      this.size = [560, 420];
    };

    const onExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      onExecuted?.apply(this, arguments);
      const d = message?.pcg_spreadsheet?.[0];
      if (d) this._pcgSheet?.setData(d);
    };
  },
});
