#!/usr/bin/env python3
"""identify_interesting_clickables.py — classify scan-*.json elements (14 classes).

Reads scan-*.json output from the Haiku scanner and emits a deterministic
``recursive-classification.json`` with one entry per "interesting" clickable.

Pure Python, deterministic, no LLM cost.

Element classes (per design doc 2026-04-30-v2.40-recursive-lens-probe.md):

Tier 1 — fully implemented (direct map from scan-*.json fields):
  - mutation_button   results[].network[].method ∈ {POST,PUT,PATCH,DELETE}
  - form_trigger      forms[].submit_result.status exists (no file field)
  - file_upload       forms[].fields[].type == "file"
  - tab               tabs[]
  - row_action        tables[].row_actions[]
  - bulk_action       tables[].bulk_actions[]
  - sub_view_link     sub_views_discovered[]
  - modal_trigger     modal_triggers[]

Tier 2 — STUBBED (deferred to Task 18 — spawn-recursive-probe.py):
  - redirect_url_param, url_fetch_param, path_param
  - auth_endpoint, payment_or_workflow, error_response

Tier 2 detection requires:
  1. Haiku scanner output schema to be locked (Phase 1.D) — current scan-*.json
     shape (network[], headers, response_body) is provisional.
  2. CRUD-SURFACES.category field to be confirmed (open question #5 in design
     doc) — payment_or_workflow should key off `category`, not path regex.
  3. Per-detector fixtures + tests so the heuristics don't over-spawn lenses
     (e.g. naïve "Authorization header → auth_endpoint" flags every API call
     in a modern app and blows the worker cap).

Output schema:

    {
      "clickables": [
        {
          "view": "/admin/topup-requests",
          "element_class": "mutation_button",
          "selector": "button#delete-42",
          "selector_hash": "<sha256[:8]>",
          "resource": "topup_requests",
          "action_semantic": "delete",
          "metadata": {...}
        },
        ...
      ],
      "count": <int>
    }

The selector hash is sha256 truncated to 8 hex chars per the design doc — used
as a stable, short id for cross-run memoization (collision risk is acceptable
because hashes are scoped per view).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

# --- Tier 1 ------------------------------------------------------------------
MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Hash truncation length — design-doc spec; documented as a constant rather
# than a magic number sprinkled in code.
SELECTOR_HASH_LEN = 8

# --- Tier 2 detection rules ---------------------------------------------------
# Per design doc + v2.41 code-review concerns:
#   - auth_endpoint: path-only pattern (Authorization header is too noisy)
#   - path_param: requires '/' in value (reduces false positives)
#   - dedupe per (element_class, distinct path/param key) to prevent overflow

REDIRECT_URL_PARAM_RE = re.compile(
    r"\b(redirect_uri|return_to|next|continue)\b", re.IGNORECASE
)
URL_FETCH_PARAM_RE = re.compile(
    r"\b(url|link|webhook|callback|fetch_from)\b", re.IGNORECASE
)
PATH_PARAM_RE = re.compile(
    r"\b(file|path|template|name)\b", re.IGNORECASE
)
AUTH_ENDPOINT_PATH_RE = re.compile(
    r"^/(api/auth/.+|login|logout|oauth/)", re.IGNORECASE
)

# Stack-trace markers — 8 languages. Each is matched as a literal substring
# in response_body. Tabs and newlines are spelled out as escapes so the
# table is auditable in source.
STACK_TRACE_MARKERS: tuple[str, ...] = (
    "Traceback (most recent call last)",   # Python
    "\tat ",                               # Java/Scala (TAB + 'at ')
    "at <anonymous>",                      # Node.js (anonymous frame)
    "at Object.",                          # Node.js (object frame)
    "Stack trace:",                        # PHP (header)
    "#0 /",                                # PHP (frame index)
    " in <main>'\n\tfrom ",                # Ruby
    "panic: ",                             # Go (panic)
    "goroutine ",                          # Go (goroutine dump)
    "thread 'main' panicked",              # Rust
    "System.Exception",                    # .NET
)


def _has_stack_trace(body: str) -> bool:
    """Return True iff body contains any of the canonical stack-trace markers."""
    if not body:
        return False
    return any(marker in body for marker in STACK_TRACE_MARKERS)


# Categories signaling payment/workflow lenses — matched against
# CRUD-SURFACES `category` (open question #5 resolution: prefer category
# over path regex to avoid false positives like /api/refund-policy-text).
PAYMENT_OR_WORKFLOW_CATEGORIES: frozenset[str] = frozenset({
    "payment", "refund", "credit", "quota",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def selector_hash(s: str) -> str:
    """Return sha256(s)[:SELECTOR_HASH_LEN] — deterministic short id."""
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:SELECTOR_HASH_LEN]


def _action_from_method(method: str | None, path: str | None) -> str:
    m = (method or "").upper()
    if m == "DELETE":
        return "delete"
    if m == "POST":
        return "create"
    if m in ("PUT", "PATCH"):
        return "update"
    return "mutate"


def _resource_from_path(path: str | None) -> str:
    """Best-effort resource extraction from a URL path (e.g. /api/topup/42 -> topup)."""
    if not path:
        return ""
    parts = [p for p in path.split("/") if p and not p.startswith("{")]
    # Drop common /api prefix and trailing numeric ids.
    if parts and parts[0].lower() == "api":
        parts = parts[1:]
    if parts and parts[-1].isdigit():
        parts = parts[:-1]
    return parts[-1] if parts else ""


def _emit(out: list[dict], view: str, element_class: str, selector: str,
          *, action_semantic: str, resource: str = "", metadata: dict | None = None) -> None:
    out.append({
        "view": view,
        "element_class": element_class,
        "selector": selector,
        "selector_hash": selector_hash(selector),
        "resource": resource,
        "action_semantic": action_semantic,
        "metadata": metadata or {},
    })


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------
def classify_scan(scan: dict) -> list[dict]:
    """Single-pass classification of one scan-*.json into clickable rows."""
    out: list[dict] = []
    view = scan.get("view", "")

    # --- Tier 1 -------------------------------------------------------------
    # mutation_button: results carrying mutating network calls.
    for r in scan.get("results", []) or []:
        for n in r.get("network", []) or []:
            method = (n.get("method") or "").upper()
            if method in MUTATION_METHODS:
                sel = r.get("selector") or r.get("action") or ""
                _emit(out, view, "mutation_button", sel,
                      action_semantic=_action_from_method(method, n.get("path")),
                      resource=_resource_from_path(n.get("path")),
                      metadata={"method": method, "path": n.get("path")})

    # form_trigger / file_upload — submitted forms.
    for f in scan.get("forms", []) or []:
        if "submit_result" not in f:
            continue
        sel = f.get("selector", "")
        fields = f.get("fields", []) or []
        has_file = any((fld.get("type") == "file") for fld in fields)
        ec = "file_upload" if has_file else "form_trigger"
        _emit(out, view, ec, sel,
              action_semantic="upload" if has_file else "submit",
              metadata={"fields": fields, "submit_result": f.get("submit_result")})

    # tabs
    for t in scan.get("tabs", []) or []:
        sel = f"tab[{t}]"
        _emit(out, view, "tab", sel, action_semantic="switch",
              metadata={"label": t})

    # row_actions / bulk_actions
    for tbl in scan.get("tables", []) or []:
        for ra in tbl.get("row_actions", []) or []:
            _emit(out, view, "row_action", f"row_action[{ra}]",
                  action_semantic=ra, metadata={})
        for ba in tbl.get("bulk_actions", []) or []:
            _emit(out, view, "bulk_action", f"bulk[{ba}]",
                  action_semantic=ba, metadata={})

    # modal triggers
    for m in scan.get("modal_triggers", []) or []:
        _emit(out, view, "modal_trigger", m,
              action_semantic="open_modal", metadata={})

    # sub_view_link
    for sv in scan.get("sub_views_discovered", []) or []:
        _emit(out, view, "sub_view_link", f"link[{sv}]",
              action_semantic="navigate", metadata={"target": sv})

    # --- Tier 2 (stubbed; see module docstring) -----------------------------
    out.extend(_tier2_url_param_classes(scan, view))
    out.extend(_tier2_endpoint_classes(scan, view))
    out.extend(_tier2_workflow_classes(scan, view))
    out.extend(_tier2_error_responses(scan, view))

    return out


# ---------------------------------------------------------------------------
# Tier 2 — implemented in v2.41 (closes v2.40.2 #2). 5 lenses now reachable:
#   open-redirect, ssrf, auth-jwt, business-logic, info-disclosure.
# ---------------------------------------------------------------------------
def _iter_param_kvs(scan: dict):
    """Yield (param_name, param_value, source_path) tuples from network calls.

    Walks ``results[].network[]`` and parses query strings. Both the URL and a
    body-level ``query_params`` map (when present) are honored.
    """
    for r in scan.get("results", []) or []:
        for n in r.get("network", []) or []:
            url = n.get("url") or n.get("path") or ""
            try:
                qs = urlsplit(url).query if url else ""
            except ValueError:
                qs = ""
            for k, v in parse_qsl(qs, keep_blank_values=True):
                yield k, v, url
            # Also accept a pre-parsed dict if the scanner provides one.
            qp = n.get("query_params")
            if isinstance(qp, dict):
                for k, v in qp.items():
                    yield str(k), str(v), url


def _tier2_url_param_classes(scan: dict, view: str) -> list[dict]:
    """Detect redirect_url_param / url_fetch_param / path_param from query strings.

    Dedupes per (element_class, normalized param-key) so 100 mutation buttons
    that all carry ``?url=...`` collapse to one entry — guard #7-aligned.
    """
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for k, v, url in _iter_param_kvs(scan):
        if not k:
            continue
        # redirect_url_param
        if REDIRECT_URL_PARAM_RE.search(k):
            key = ("redirect_url_param", k.lower())
            if key not in seen:
                seen.add(key)
                _emit(out, view, "redirect_url_param", f"param[{k}]",
                      action_semantic="redirect", resource="",
                      metadata={"param_name": k, "value_sample": v[:80], "url": url})
            continue
        # url_fetch_param
        if URL_FETCH_PARAM_RE.search(k):
            key = ("url_fetch_param", k.lower())
            if key not in seen:
                seen.add(key)
                _emit(out, view, "url_fetch_param", f"param[{k}]",
                      action_semantic="fetch", resource="",
                      metadata={"param_name": k, "value_sample": v[:80], "url": url})
            continue
        # path_param: name match AND value contains '/' (reduces false positives
        # like ?name=Alice from a contact form).
        if PATH_PARAM_RE.search(k) and "/" in (v or ""):
            key = ("path_param", k.lower())
            if key not in seen:
                seen.add(key)
                _emit(out, view, "path_param", f"param[{k}]",
                      action_semantic="path_traverse", resource="",
                      metadata={"param_name": k, "value_sample": v[:80], "url": url})
    return out


def _tier2_endpoint_classes(scan: dict, view: str) -> list[dict]:
    """Detect auth_endpoint via PATH pattern only.

    Code-review concern: detecting via Authorization header flags every API
    call in a modern app and over-spawns lens-auth-jwt + lens-csrf. Path-only
    matching is intentionally narrow.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for r in scan.get("results", []) or []:
        for n in r.get("network", []) or []:
            path = n.get("path") or ""
            if not path:
                # Try to parse out of url field.
                url = n.get("url") or ""
                try:
                    path = urlsplit(url).path if url else ""
                except ValueError:
                    path = ""
            if not path:
                continue
            if AUTH_ENDPOINT_PATH_RE.match(path):
                # Dedupe by path stem (drop trailing IDs / query strings).
                key = path.split("?", 1)[0].rstrip("/")
                if key in seen:
                    continue
                seen.add(key)
                _emit(out, view, "auth_endpoint", f"endpoint[{key}]",
                      action_semantic="authenticate",
                      resource=_resource_from_path(path),
                      metadata={"path": path, "method": n.get("method")})
    return out


def _tier2_workflow_classes(scan: dict, view: str) -> list[dict]:
    """Detect payment_or_workflow via state-machine flag OR CRUD category.

    Two signals (either is sufficient):
      1. ``scan.business_flow.has_state_machine == True`` — explicit marker
         the scanner sets when it detects a multi-state lifecycle.
      2. CRUD-SURFACES ``category`` ∈ {payment, refund, credit, quota} — the
         resource itself is intrinsically money-flavored / workflow-bearing.

    Resources surface via ``scan.crud_resources`` (the classifier injects
    them when running under spawn_recursive_probe context). Each matching
    resource emits one entry; dedupe by resource name.
    """
    out: list[dict] = []
    bf = scan.get("business_flow") or {}
    has_sm = bool(bf.get("has_state_machine"))
    resources = scan.get("crud_resources") or []
    seen: set[str] = set()
    if has_sm:
        # Treat the view itself as the workflow surface when the scanner only
        # set the boolean flag. Single emission per scan.
        seen.add(f"view::{view}")
        _emit(out, view, "payment_or_workflow", f"workflow[{view}]",
              action_semantic="advance_state", resource="",
              metadata={"reason": "has_state_machine", "states": bf.get("states", [])})
    if isinstance(resources, list):
        for res in resources:
            if not isinstance(res, dict):
                continue
            cat = str(res.get("category", "")).strip().lower()
            name = str(res.get("name", "")).strip()
            if cat in PAYMENT_OR_WORKFLOW_CATEGORIES and name:
                key = f"resource::{name}"
                if key in seen:
                    continue
                seen.add(key)
                _emit(out, view, "payment_or_workflow",
                      f"resource[{name}]",
                      action_semantic="advance_state", resource=name,
                      metadata={"reason": f"category={cat}", "category": cat})
    return out


def _tier2_error_responses(scan: dict, view: str) -> list[dict]:
    """Detect error_response — status>=500 OR stack-trace markers in body.

    Dedupes per distinct (path) so 100 mutation buttons all returning 500
    don't blow up the worker cap (guard #1).
    """
    out: list[dict] = []
    seen: set[str] = set()
    for r in scan.get("results", []) or []:
        for n in r.get("network", []) or []:
            status = n.get("status")
            try:
                status_int = int(status) if status is not None else 0
            except (TypeError, ValueError):
                status_int = 0
            body = n.get("response_body") or ""
            is_5xx = status_int >= 500
            has_trace = _has_stack_trace(body)
            if not (is_5xx or has_trace):
                continue
            path = n.get("path") or ""
            if not path:
                url = n.get("url") or ""
                try:
                    path = urlsplit(url).path if url else ""
                except ValueError:
                    path = ""
            key = path.split("?", 1)[0] or f"_{status_int}"
            if key in seen:
                continue
            seen.add(key)
            reason = "stack_trace" if has_trace else f"status_{status_int}"
            _emit(out, view, "error_response", f"error[{key}]",
                  action_semantic="probe_disclosure",
                  resource=_resource_from_path(path),
                  metadata={"path": path, "status": status_int, "reason": reason})
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan-files", nargs="+", required=True,
                    help="One or more scan-*.json files emitted by the Haiku scanner")
    ap.add_argument("--output", default=None,
                    help="Path to write recursive-classification.json (default: stdout only)")
    ap.add_argument("--json", action="store_true",
                    help="Print the JSON payload to stdout (default if --output is omitted)")
    args = ap.parse_args()

    all_clickables: list[dict[str, Any]] = []
    for sp in args.scan_files:
        p = Path(sp)
        if not p.is_file():
            print(f"scan file not found: {p}", file=sys.stderr)
            return 1
        try:
            scan = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"invalid JSON in {p}: {e}", file=sys.stderr)
            return 1
        all_clickables.extend(classify_scan(scan))

    payload = {"clickables": all_clickables, "count": len(all_clickables)}

    if args.json or args.output is None:
        print(json.dumps(payload, indent=2))
    if args.output:
        Path(args.output).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
