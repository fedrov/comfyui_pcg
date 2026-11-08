// comfyui_pcg docs: search, theme toggle and the "on this page" highlight.
// Copied to docs/html/assets/site.js by docs/build_html.py. The search index is a plain script
// (search-index.js), not fetched JSON, so the docs also work when opened from disk (file://).
(function () {
  "use strict";
  var css = document.querySelector('link[rel="stylesheet"][href$="assets/style.css"]');
  var root = css ? css.getAttribute("href").replace(/assets\/style\.css$/, "") : "";
  var INDEX = window.PCG_INDEX || [];
  var GLYPHS = window.PCG_GLYPHS || {};

  // ── theme
  var themeBtn = document.querySelector(".theme");
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      var cur = document.documentElement.dataset.theme;
      if (!cur) cur = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
      var next = cur === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("pcg-docs-theme", next); } catch (e) { /* storage blocked: theme just isn't kept */ }
    });
  }

  // ── search
  var q = document.getElementById("q");
  var box = document.getElementById("results");
  var sel = -1;

  function norm(s) { return String(s || "").toLowerCase(); }
  function esc(s) {
    return String(s || "").replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function score(it, terms) {
    var t = norm(it.t), id = norm(it.id), h = norm(it.h), s = norm(it.s), p = norm(it.p);
    var total = 0;
    for (var i = 0; i < terms.length; i++) {
      var w = terms[i], best = 0;
      if (t === w || id === "pcg_" + w) best = 100;
      else if (t.indexOf(w) === 0) best = 60;
      else if (t.indexOf(w) >= 0) best = 40;
      else if (id.indexOf(w) >= 0) best = 35;
      else if (h.indexOf(w) >= 0) best = 30;
      else if (s.indexOf(w) >= 0) best = 10;
      else if (p.indexOf(w) >= 0) best = 5;
      if (!best) return 0;
      total += best;
    }
    if (it.k === "node") total += 3;
    if (it.k === "page") total += 2;
    return total;
  }
  function icon(it) {
    if (!it.g || !GLYPHS[it.g]) return "";
    return '<svg class="ico" style="color:' + it.c + '" viewBox="0 0 32 32">' + GLYPHS[it.g] + "</svg>";
  }
  function search() {
    var v = norm(q.value).replace(/\(pcg\)/g, "").trim();
    if (!v) { box.classList.remove("open"); box.innerHTML = ""; return; }
    var terms = v.split(/\s+/);
    var hits = [];
    for (var i = 0; i < INDEX.length; i++) {
      var sc = score(INDEX[i], terms);
      if (sc) hits.push([sc, i]);
    }
    hits.sort(function (a, b) { return b[0] - a[0] || a[1] - b[1]; });
    hits = hits.slice(0, 40);
    if (!hits.length) {
      box.innerHTML = '<div class="none">No results</div>';
    } else {
      box.innerHTML = hits.map(function (h) {
        var it = INDEX[h[1]];
        var kind = it.k === "node" ? (it.h ? "Houdini: " + esc(it.h) : "node")
          : it.k === "section" ? "in " + esc(it.p) : "page";
        return '<a href="' + root + it.u + '">' + icon(it) + "<span>" +
          '<span class="rt">' + esc(it.t) + '</span> <span class="rk">' + kind + "</span>" +
          (it.s ? '<span class="rs">' + esc(it.s) + "</span>" : "") + "</span></a>";
      }).join("");
    }
    sel = -1;
    box.classList.add("open");
  }
  function move(d) {
    var links = box.querySelectorAll("a");
    if (!links.length) return;
    if (sel >= 0 && links[sel]) links[sel].classList.remove("sel");
    sel = (sel + d + links.length) % links.length;
    links[sel].classList.add("sel");
    links[sel].scrollIntoView({ block: "nearest" });
  }
  if (q && box) {
    q.addEventListener("input", search);
    q.addEventListener("focus", function () { if (q.value) search(); });
    q.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { move(1); e.preventDefault(); }
      else if (e.key === "ArrowUp") { move(-1); e.preventDefault(); }
      else if (e.key === "Enter") {
        var links = box.querySelectorAll("a");
        var a = links[sel >= 0 ? sel : 0];
        if (a) location.href = a.href;
      } else if (e.key === "Escape") { q.value = ""; search(); q.blur(); }
    });
    document.addEventListener("click", function (e) {
      if (!e.target.closest(".search")) box.classList.remove("open");
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "/" && document.activeElement !== q && !/input|textarea/i.test(document.activeElement.tagName)) {
        q.focus(); e.preventDefault();
      }
    });
  }

  // ── on this page: highlight the section in view
  var tocLinks = document.querySelectorAll(".toc a");
  if (tocLinks.length && "IntersectionObserver" in window) {
    var byId = {};
    tocLinks.forEach(function (a) { byId[a.getAttribute("href").slice(1)] = a; });
    var current = null;
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting && byId[en.target.id]) {
          if (current) current.classList.remove("active");
          current = byId[en.target.id];
          current.classList.add("active");
        }
      });
    }, { rootMargin: "0px 0px -75% 0px" });
    Object.keys(byId).forEach(function (id) {
      var el = document.getElementById(id);
      if (el) obs.observe(el);
    });
  }
  // keep the current page visible in the sidebar
  var cur = document.querySelector(".side li.current");
  if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: "center" });
})();
