/**
 * scanner-evidence-capture.js — JS snippets scanners paste into browser_evaluate
 *
 * Single source of truth for evidence capture per scanner-report-contract Tier A-F.
 * Scanners (Haiku, CLI executors) reference this file by name, copy specific
 * function bodies into browser_evaluate(...) calls. Keeping all snippets in one
 * place means selector tweaks propagate to every scanner without per-skill edit.
 *
 * Usage pattern in scanner workflow:
 *   1. Read this file
 *   2. Pick snippet matching the tier you need (e.g., captureToast)
 *   3. Pass snippet body to MCP browser_evaluate({ function: <body> })
 *   4. Merge returned data into observation.evidence.<key>
 *
 * Selectors come from vg.config.md `scanner_evidence:` block. Defaults below
 * are fallbacks for projects without explicit config.
 */

// ============================================================================
// TIER A — Always-on (every UI step)
// ============================================================================

/**
 * Capture toast notification visible on page.
 * Returns: { visible: boolean, type: "success"|"error"|"info"|"unknown", text: string, count: number }
 *
 * Selector strategy:
 *   1. config.scanner_evidence.toast.selectors[] (project-specific)
 *   2. Common library selectors (Sonner, react-hot-toast, Shadcn, MUI, Mantine, Chakra)
 *
 * Add new library? Append to TOAST_SELECTORS below + open issue.
 */
const TOAST_SELECTORS = [
  '[data-sonner-toast]',                          // Sonner
  '[role="status"][aria-live]',                   // ARIA standard (most libs)
  '.Toastify__toast',                             // react-toastify
  '[data-state="open"][role="alert"]',            // Radix / Shadcn Toast
  '.toast--visible',                              // Bootstrap-like
  '.notification, .ant-notification-notice',      // antd
  '.MuiSnackbar-root, .MuiAlert-root',            // MUI
  '[class*="toast" i]:not(:empty)',               // generic catch-all (last)
];

const captureToast = `
async () => {
  const sels = ${JSON.stringify(TOAST_SELECTORS)};
  const found = [];
  for (const sel of sels) {
    document.querySelectorAll(sel).forEach(el => {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return;        // hidden
      const txt = (el.innerText || el.textContent || '').trim().slice(0, 200);
      if (!txt) return;
      // Type heuristic: class/data-attr keywords
      const cls = (el.className || '') + ' ' + (el.dataset?.type || '') + ' ' + (el.getAttribute('aria-label') || '');
      let type = 'unknown';
      if (/error|danger|fail/i.test(cls)) type = 'error';
      else if (/success|ok|done/i.test(cls)) type = 'success';
      else if (/warn|warning/i.test(cls)) type = 'warning';
      else if (/info|notice/i.test(cls)) type = 'info';
      found.push({ selector: sel, text: txt, type });
    });
  }
  // Dedupe by text
  const seen = new Set();
  const unique = found.filter(f => !seen.has(f.text) && seen.add(f.text));
  return { visible: unique.length > 0, count: unique.length, items: unique };
}
`;

const capturePageTitle = `() => ({ title: document.title, url: location.href })`;

/**
 * HTTP status summary — counts by class. Pair with browser_network_requests.
 * Caller passes the network array, not browser eval.
 */
function summarizeHttpStatus(networkRequests) {
  const buckets = { '2xx': 0, '3xx': 0, '4xx': 0, '5xx': 0, 'cors_blocked': 0, 'aborted': 0 };
  for (const r of networkRequests || []) {
    const s = r.status;
    if (typeof s !== 'number') {
      if (r.errorText && /CORS/i.test(r.errorText)) buckets.cors_blocked++;
      else if (r.errorText && /abort/i.test(r.errorText)) buckets.aborted++;
      continue;
    }
    if (s >= 200 && s < 300) buckets['2xx']++;
    else if (s >= 300 && s < 400) buckets['3xx']++;
    else if (s >= 400 && s < 500) buckets['4xx']++;
    else if (s >= 500) buckets['5xx']++;
  }
  return buckets;
}

// ============================================================================
// TIER B — Form / CRUD lifecycle
// ============================================================================

const captureFormValidationErrors = `
() => {
  const errors = [];
  // ARIA validation
  document.querySelectorAll('[aria-invalid="true"]').forEach(el => {
    errors.push({
      field: el.name || el.id || el.getAttribute('aria-labelledby') || 'unnamed',
      message: el.getAttribute('aria-errormessage')
        ? document.getElementById(el.getAttribute('aria-errormessage'))?.innerText?.trim()
        : null,
      source: 'aria-invalid',
    });
  });
  // Visible role=alert
  document.querySelectorAll('[role="alert"]:not([hidden])').forEach(el => {
    const txt = (el.innerText || '').trim().slice(0, 200);
    if (txt && !errors.some(e => e.message === txt)) {
      errors.push({ field: null, message: txt, source: 'role=alert' });
    }
  });
  // Native :invalid (form input constraint)
  document.querySelectorAll('input:invalid, textarea:invalid, select:invalid').forEach(el => {
    errors.push({
      field: el.name || el.id || 'unnamed',
      message: el.validationMessage || null,
      source: 'native-invalid',
    });
  });
  return { count: errors.length, items: errors };
}
`;

const captureSubmitButtonState = `
(selectorOrNull) => {
  const sel = selectorOrNull || 'button[type="submit"], [data-action="submit"], button.submit';
  const btn = document.querySelector(sel);
  if (!btn) return { found: false };
  return {
    found: true,
    text: (btn.innerText || btn.value || '').trim(),
    disabled: btn.disabled || btn.getAttribute('aria-disabled') === 'true',
    busy: btn.getAttribute('aria-busy') === 'true' || /loading|busy/i.test(btn.className),
    bbox: btn.getBoundingClientRect(),
  };
}
`;

const captureLoadingIndicator = `
() => {
  const sels = [
    '[role="progressbar"]:not([hidden])',
    '[aria-busy="true"]',
    '.spinner:not([hidden]), .loader:not([hidden])',
    '[class*="loading" i]:not(:empty)',
    '[data-loading="true"]',
  ];
  for (const sel of sels) {
    const el = document.querySelector(sel);
    if (el) {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) {
        return { present: true, selector: sel, bbox: { x: r.x, y: r.y, w: r.width, h: r.height } };
      }
    }
  }
  return { present: false };
}
`;

const captureRowCount = `
(tableSelectorOrNull) => {
  const sel = tableSelectorOrNull || 'table tbody tr, [role="grid"] [role="row"], [data-list-row]';
  return { count: document.querySelectorAll(sel).length, selector: sel };
}
`;

const captureFieldValue = `
(fieldName) => {
  const el = document.querySelector('[name="' + fieldName + '"]')
          || document.querySelector('#' + fieldName)
          || document.querySelector('[data-field="' + fieldName + '"]');
  if (!el) return { found: false };
  let value = '';
  if (el.tagName === 'SELECT') {
    value = el.value;
  } else if (el.type === 'checkbox' || el.type === 'radio') {
    value = el.checked;
  } else {
    value = el.value !== undefined ? el.value : (el.innerText || '').trim();
  }
  return { found: true, value, type: el.type || el.tagName.toLowerCase() };
}
`;

// ============================================================================
// TIER C — Auth / Session / Security
// ============================================================================

/**
 * Capture cookies metadata only (no values — secure/httponly cookies aren't
 * accessible via document.cookie anyway, but for non-httponly we still strip
 * values to avoid logging session tokens).
 */
const captureCookiesFiltered = `
() => {
  const raw = document.cookie || '';
  const items = raw.split('; ').filter(Boolean).map(p => {
    const [name] = p.split('=');
    return { name: name.trim(), accessible_via_js: true /* implies !httponly */ };
  });
  return { document_cookie_count: items.length, names: items.map(i => i.name) };
}
`;

const captureAuthStateHeuristic = `
(authSelectorsCsv) => {
  const sels = (authSelectorsCsv || '[data-user-menu], .user-avatar, [data-testid="user-menu"], [aria-label*="account" i]').split(',').map(s => s.trim());
  for (const sel of sels) {
    if (document.querySelector(sel)) return { authenticated: true, signal: sel };
  }
  // Fallback: check for /login URL
  if (location.pathname.includes('/login')) return { authenticated: false, signal: 'url_contains_login' };
  return { authenticated: 'unknown', signal: null };
}
`;

/**
 * Inspect outgoing request headers for security tokens.
 * Caller passes the captured request from browser_network_requests.
 */
function inspectRequestSecurityHeaders(request) {
  const h = (request.headers || {});
  const lower = Object.fromEntries(Object.entries(h).map(([k, v]) => [k.toLowerCase(), v]));
  return {
    has_authorization: !!lower['authorization'],
    has_csrf_token: !!(lower['x-csrf-token'] || lower['x-xsrf-token'] || lower['csrf-token']),
    has_idempotency_key: !!lower['idempotency-key'],
    has_if_match: !!lower['if-match'],
    has_origin: !!lower['origin'],
    has_referer: !!lower['referer'],
    custom_headers: Object.keys(lower).filter(k => k.startsWith('x-') && !['x-csrf-token', 'x-xsrf-token'].includes(k)),
  };
}

function inspectResponseSecurityHeaders(response) {
  const h = (response.headers || {});
  const lower = Object.fromEntries(Object.entries(h).map(([k, v]) => [k.toLowerCase(), v]));
  const setCookies = lower['set-cookie'] ? (Array.isArray(lower['set-cookie']) ? lower['set-cookie'] : [lower['set-cookie']]) : [];
  return {
    has_set_cookie: setCookies.length > 0,
    set_cookie_flags: setCookies.map(sc => ({
      has_httponly: /HttpOnly/i.test(sc),
      has_secure: /Secure/i.test(sc),
      same_site: (sc.match(/SameSite=([^;]+)/i) || [, null])[1],
    })),
    has_csp: !!lower['content-security-policy'],
    has_x_frame_options: !!lower['x-frame-options'],
    has_strict_transport_security: !!lower['strict-transport-security'],
  };
}

// ============================================================================
// TIER D — Realtime / Async
// ============================================================================

/**
 * WebSocket frame log. Requires app to install instrumentation:
 *   window.__vg_ws_log = [];
 *   const _send = WebSocket.prototype.send;
 *   WebSocket.prototype.send = function(d) { window.__vg_ws_log.push({dir:'out', data: String(d).slice(0,200), t: Date.now()}); return _send.apply(this, arguments); };
 *   ... mirror for onmessage
 *
 * Without instrumentation, this snippet returns { instrumented: false }.
 */
const captureWebSocketFrames = `
() => {
  if (!Array.isArray(window.__vg_ws_log)) {
    return { instrumented: false, frames: [], note: 'install instrumentation per scanner-evidence-capture.js' };
  }
  const frames = window.__vg_ws_log.slice();
  return { instrumented: true, count: frames.length, frames };
}
`;

const captureBackgroundJobStatus = `
async (apiUrl) => {
  if (!apiUrl) return { skipped: true };
  try {
    const r = await fetch(apiUrl, { credentials: 'include' });
    const j = await r.json().catch(() => null);
    return { status: r.status, queue_summary: j };
  } catch (e) { return { error: String(e) }; }
}
`;

// ============================================================================
// TIER E — Visual / A11y
// ============================================================================

const captureFocusState = `
() => {
  const ae = document.activeElement;
  if (!ae || ae === document.body) return { focused: 'body_or_none' };
  return {
    focused: true,
    tag: ae.tagName,
    id: ae.id || null,
    name: ae.getAttribute('name') || null,
    role: ae.getAttribute('role') || null,
    label: (ae.getAttribute('aria-label') || '').slice(0, 100),
  };
}
`;

const captureAriaState = `
(selector) => {
  const el = document.querySelector(selector);
  if (!el) return { found: false };
  const aria = {};
  for (const attr of el.attributes) {
    if (attr.name.startsWith('aria-') || attr.name === 'role') aria[attr.name] = attr.value;
  }
  return { found: true, attributes: aria };
}
`;

const captureTabOrder = `
() => {
  const focusable = document.querySelectorAll(
    'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
  );
  return Array.from(focusable).slice(0, 30).map(el => ({
    tag: el.tagName,
    label: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 60),
    tabindex: el.tabIndex,
  }));
}
`;

// ============================================================================
// TIER F — Storage / Client State
// ============================================================================

/**
 * Storage keys ONLY — never values (PII / token risk).
 */
const captureStorageKeys = `
() => ({
  localStorage_keys: Object.keys(localStorage),
  sessionStorage_keys: Object.keys(sessionStorage),
  count: { local: localStorage.length, session: sessionStorage.length },
})
`;

const captureIndexedDBs = `
async () => {
  if (!indexedDB.databases) return { supported: false };
  const dbs = await indexedDB.databases();
  return { supported: true, dbs: dbs.map(d => ({ name: d.name, version: d.version })) };
}
`;

const captureStoreSnapshot = `
(storeWindowKey) => {
  const k = storeWindowKey || '__VG_STORE__';
  const store = window[k];
  if (!store) return { exposed: false, key: k };
  // Whitelist top-level keys only (avoid PII dump). Caller can deep-read specific paths if needed.
  if (typeof store.getState === 'function') {
    const state = store.getState();
    return { exposed: true, key: k, top_level_keys: Object.keys(state || {}) };
  }
  return { exposed: true, key: k, top_level_keys: Object.keys(store || {}) };
}
`;

// ============================================================================
// Export — Node.js style for orchestrator scripts to read snippets
// ============================================================================

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    // Tier A
    captureToast,
    capturePageTitle,
    summarizeHttpStatus,                  // pure JS function, run on captured network
    // Tier B
    captureFormValidationErrors,
    captureSubmitButtonState,
    captureLoadingIndicator,
    captureRowCount,
    captureFieldValue,
    // Tier C
    captureCookiesFiltered,
    captureAuthStateHeuristic,
    inspectRequestSecurityHeaders,        // pure JS function
    inspectResponseSecurityHeaders,       // pure JS function
    // Tier D
    captureWebSocketFrames,
    captureBackgroundJobStatus,
    // Tier E
    captureFocusState,
    captureAriaState,
    captureTabOrder,
    // Tier F
    captureStorageKeys,
    captureIndexedDBs,
    captureStoreSnapshot,
    // Selectors (exposed for scanners to merge with project config)
    TOAST_SELECTORS,
  };
}
