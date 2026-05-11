/* eslint-disable */
// VGFlow /vg:field-test overlay v2.1 — vanilla browser JS, no deps.
// Injected via mcp__playwright1__browser_evaluate.
// state.marks[] is canonical source; console emit is notification only.
//
// State shape (orchestrator polls via browser_evaluate):
//   window.__VG_FT_STATE = {
//     status: "idle" | "recording" | "stopped",
//     reload_epoch: <int>,   // increments on re-injection; resets to 0 if state wiped
//     marks: [<entry>, ...],
//     buffer: { console: [], network: [], nav: [], clicks: [] },
//     drops: { console?: int, network?: int, nav?: int, clicks?: int }
//   }
(function () {
  "use strict";
  if (window.__VG_FT_STATE) {
    // Re-injection (SPA partial nav). Bump reload_epoch; preserve marks.
    window.__VG_FT_STATE.reload_epoch = (window.__VG_FT_STATE.reload_epoch || 0) + 1;
    if (window.__VG_FT_INIT) window.__VG_FT_INIT();
    return;
  }

  var BUFFER_CAP = 10000;
  function nowIso() { return new Date().toISOString(); }
  function emit(event, payload) {
    try {
      console.log("[VG_FT] " + JSON.stringify({ event: event, ts: nowIso(), payload: payload || {} }));
    } catch (e) {}
  }

  var state = {
    status: "idle",
    reload_epoch: 0,
    marks: [],
    buffer: { console: [], network: [], nav: [], clicks: [] },
    drops: {}
  };
  window.__VG_FT_STATE = state;

  function pushBuffer(name, entry) {
    var b = state.buffer[name];
    b.push(entry);
    while (b.length > BUFFER_CAP) {
      b.shift();
      state.drops[name] = (state.drops[name] || 0) + 1;
    }
  }

  // ── Console monkeypatch ─────────────────────────────────────────────
  var origConsole = {};
  ["log", "warn", "error", "info", "debug"].forEach(function (lvl) {
    origConsole[lvl] = console[lvl].bind(console);
    console[lvl] = function () {
      try {
        var args = Array.prototype.slice.call(arguments);
        pushBuffer("console", { ts: nowIso(), level: lvl, args: args.map(String) });
      } catch (e) {}
      return origConsole[lvl].apply(null, arguments);
    };
  });

  // ── Fetch monkeypatch ───────────────────────────────────────────────
  if (typeof window.fetch === "function") {
    var origFetch = window.fetch.bind(window);
    window.fetch = function (resource, opts) {
      var url = typeof resource === "string" ? resource : (resource && resource.url) || "?";
      var method = (opts && opts.method) || "GET";
      var startTs = nowIso();
      return origFetch.apply(null, arguments).then(function (resp) {
        pushBuffer("network", { ts: startTs, kind: "fetch", method: method, url: url, status: resp.status });
        return resp;
      }).catch(function (err) {
        pushBuffer("network", { ts: startTs, kind: "fetch", method: method, url: url, error: String(err) });
        throw err;
      });
    };
  }

  // ── XHR monkeypatch ─────────────────────────────────────────────────
  if (typeof window.XMLHttpRequest === "function") {
    var XHR = window.XMLHttpRequest;
    var origOpen = XHR.prototype.open;
    var origSend = XHR.prototype.send;
    XHR.prototype.open = function (method, url) {
      this.__vg_method = method;
      this.__vg_url = url;
      return origOpen.apply(this, arguments);
    };
    XHR.prototype.send = function () {
      var self = this;
      var startTs = nowIso();
      self.addEventListener("loadend", function () {
        pushBuffer("network", {
          ts: startTs, kind: "xhr",
          method: self.__vg_method || "?",
          url: self.__vg_url || "?",
          status: self.status
        });
      });
      return origSend.apply(this, arguments);
    };
  }

  // ── History (SPA nav) monkeypatch ───────────────────────────────────
  ["pushState", "replaceState"].forEach(function (m) {
    if (typeof history[m] === "function") {
      var orig = history[m];
      history[m] = function () {
        var rc = orig.apply(history, arguments);
        try {
          pushBuffer("nav", { ts: nowIso(), kind: m, url: location.href });
        } catch (e) {}
        return rc;
      };
    }
  });
  window.addEventListener("popstate", function () {
    pushBuffer("nav", { ts: nowIso(), kind: "popstate", url: location.href });
  });

  // ── Click capture ───────────────────────────────────────────────────
  document.addEventListener("click", function (ev) {
    try {
      var t = ev.target;
      var desc = {
        tag: (t && t.tagName) || "?",
        id: (t && t.id) || "",
        cls: (t && t.className && typeof t.className === "string") ? t.className.slice(0, 80) : "",
        text: ((t && t.textContent) || "").trim().slice(0, 80)
      };
      pushBuffer("clicks", { ts: nowIso(), target: desc, url: location.href });
    } catch (e) {}
  }, true);

  // ── UI rendering ────────────────────────────────────────────────────
  function render() {
    var existing = document.getElementById("__vg-ft-overlay");
    if (existing) existing.remove();
    var root = document.createElement("div");
    root.id = "__vg-ft-overlay";
    // v2.1 fix I-2: overlay below modal so Mark/Stop buttons aren't
    // clickable through the open modal backdrop.
    root.style.cssText =
      "position:fixed;top:12px;right:12px;z-index:2147483646;" +
      "font:13px/1.3 system-ui,-apple-system,sans-serif;" +
      "background:#0b1220;color:#e5e7eb;padding:10px;border-radius:8px;" +
      "box-shadow:0 4px 12px rgba(0,0,0,.3)";
    var pillBg = state.status === "recording" ? "#16a34a" : (state.status === "idle" ? "#475569" : "#dc2626");
    root.innerHTML =
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">' +
      '<span id="__vg-ft-pill" style="background:' + pillBg + ';padding:2px 8px;border-radius:999px;font-size:11px">' + state.status + '</span>' +
      '<span style="font-size:11px;opacity:.7">marks: ' + state.marks.length + '</span>' +
      '</div>' +
      '<div style="display:flex;gap:6px;flex-wrap:wrap">' +
      '<button id="__vg-ft-start" style="background:#16a34a;color:#fff;border:0;padding:6px 10px;border-radius:6px;cursor:pointer">Start</button>' +
      '<button id="__vg-ft-mark" style="background:#f59e0b;color:#000;border:0;padding:6px 10px;border-radius:6px;cursor:pointer">Mark</button>' +
      '<button id="__vg-ft-stop" style="background:#dc2626;color:#fff;border:0;padding:6px 10px;border-radius:6px;cursor:pointer">Stop</button>' +
      '</div>';
    document.body.appendChild(root);
    document.getElementById("__vg-ft-start").onclick = function () {
      if (state.status !== "idle") return;
      state.status = "recording";
      emit("start", { url: location.href });
      render();
    };
    document.getElementById("__vg-ft-stop").onclick = function () {
      if (state.status === "idle") return;
      state.status = "stopped";
      emit("stop", { marks: state.marks.length });
      render();
    };
    document.getElementById("__vg-ft-mark").onclick = openMark;
  }

  function openMark() {
    if (state.status !== "recording") {
      try { alert("Click Start first."); } catch (e) {}
      return;
    }
    var existing = document.getElementById("__vg-ft-modal");
    if (existing) existing.remove();
    var modal = document.createElement("div");
    modal.id = "__vg-ft-modal";
    // v2.1 fix I-2: modal z-index now MAX (2147483647); overlay drops to 2147483646.
    modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:2147483647;display:flex;align-items:center;justify-content:center";

    var card = document.createElement("div");
    card.style.cssText = "background:#0b1220;color:#e5e7eb;padding:18px;border-radius:10px;min-width:420px";

    var title = document.createElement("div");
    title.style.cssText = "margin-bottom:10px;font-weight:600";
    title.textContent = "Mark current view";

    // v2.1 fix I-1: URL injected via textContent — innerHTML would XSS on
    // crafted URLs like http://x/?p=<img src=x onerror=alert(1)>.
    var urlDiv = document.createElement("div");
    urlDiv.style.cssText = "margin-bottom:8px;font-size:12px;opacity:.7;word-break:break-all";
    urlDiv.textContent = "URL: " + location.href;

    var ta = document.createElement("textarea");
    ta.id = "__vg-ft-note";
    ta.rows = 5;
    ta.style.cssText = "width:100%;background:#1e293b;color:#e5e7eb;border:1px solid #334155;border-radius:6px;padding:8px";

    var btnRow = document.createElement("div");
    btnRow.style.cssText = "display:flex;justify-content:flex-end;gap:8px;margin-top:10px";
    btnRow.innerHTML =
      '<button id="__vg-ft-cancel" style="background:#475569;color:#fff;border:0;padding:6px 12px;border-radius:6px;cursor:pointer">Cancel</button>' +
      '<button id="__vg-ft-submit" style="background:#16a34a;color:#fff;border:0;padding:6px 12px;border-radius:6px;cursor:pointer">Submit</button>';

    card.appendChild(title);
    card.appendChild(urlDiv);
    card.appendChild(ta);
    card.appendChild(btnRow);
    modal.appendChild(card);
    document.body.appendChild(modal);
    document.getElementById("__vg-ft-cancel").onclick = function () { modal.remove(); };
    document.getElementById("__vg-ft-submit").onclick = function () {
      var note = (document.getElementById("__vg-ft-note").value || "").trim();
      if (!note) {
        try { alert("Note required."); } catch (e) {}
        return;
      }
      var entry = {
        n: state.marks.length,
        ts: nowIso(),
        url: location.href,
        referrer: document.referrer || "",
        nav_chain: state.buffer.nav.slice(-5),
        user_note: note,
        viewport: { w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio || 1 },
        click_target: state.buffer.clicks[state.buffer.clicks.length - 1] || null,
        reload_epoch: state.reload_epoch
      };
      state.marks.push(entry);  // canonical source
      emit("mark", { n: entry.n });  // notification only
      modal.remove();
      render();
    };
  }

  window.__VG_FT_INIT = function () { render(); return true; };
  window.__VG_FT_INIT();
})();
