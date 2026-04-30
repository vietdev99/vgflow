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

Tier 2 — basic detection on best-effort signals (URL params and endpoint paths
present in scan results). Stubs are kept narrow on purpose — heavier semantic
analysis is deferred to later tasks (see docs/plans/2026-04-30-v2.40-implementation.md).
  - redirect_url_param  /(redirect_uri|return_to|next|continue)/ in query
  - url_fetch_param     /(url|link|webhook|callback|fetch_from)/ in query
  - path_param          /(file|path|template|name)/ in query AND value contains '/'
  - auth_endpoint       endpoint path matches /api/auth/.+ OR Authorization header used
  - payment_or_workflow business_flow.has_state_machine OR resource ∈ {payment,refund,credit,quota}
  - error_response      response status >= 500 OR contains stack-trace markers

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
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlparse

# --- Tier 1 ------------------------------------------------------------------
MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# --- Tier 2 (basic) ----------------------------------------------------------
REDIRECT_PARAM_RE = re.compile(r"^(redirect_uri|return_to|next|continue)$", re.I)
URL_FETCH_PARAM_RE = re.compile(r"^(url|link|webhook|callback|fetch_from)$", re.I)
PATH_PARAM_RE = re.compile(r"^(file|path|template|name)$", re.I)
AUTH_ENDPOINT_RE = re.compile(r"^/api/auth/.+", re.I)
PAYMENT_RESOURCE_RE = re.compile(r"^(payment|refund|credit|quota)s?$", re.I)
STACK_TRACE_MARKERS = ("Traceback (most recent call last)", "at java.", "at scala.",
                       "Exception in thread", "panic:", "fatal error:")

# Hash truncation length — design-doc spec; documented as a constant rather
# than a magic number sprinkled in code.
SELECTOR_HASH_LEN = 8


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

    # --- Tier 2 (basic; deeper semantics deferred) --------------------------
    out.extend(_tier2_url_param_classes(scan, view))
    out.extend(_tier2_endpoint_classes(scan, view))
    out.extend(_tier2_workflow_classes(scan, view))
    out.extend(_tier2_error_responses(scan, view))

    return out


# ---------------------------------------------------------------------------
# Tier 2 — basic detectors
# ---------------------------------------------------------------------------
def _iter_network_entries(scan: dict) -> Iterable[dict]:
    for r in scan.get("results", []) or []:
        for n in r.get("network", []) or []:
            yield n


def _tier2_url_param_classes(scan: dict, view: str) -> list[dict]:
    """Detect redirect_url_param / url_fetch_param / path_param from query strings."""
    out: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for n in _iter_network_entries(scan):
        path = n.get("path") or n.get("url") or ""
        if not path:
            continue
        try:
            parsed = urlparse(path)
        except ValueError:
            continue
        for k, v in parse_qsl(parsed.query, keep_blank_values=True):
            ec: str | None = None
            if REDIRECT_PARAM_RE.match(k):
                ec = "redirect_url_param"
            elif URL_FETCH_PARAM_RE.match(k):
                ec = "url_fetch_param"
            elif PATH_PARAM_RE.match(k) and "/" in (v or ""):
                ec = "path_param"
            if not ec:
                continue
            key = (ec, k, v)
            if key in seen:
                continue
            seen.add(key)
            sel = f"param[{k}]"
            _emit(out, view, ec, sel,
                  action_semantic="param_inject",
                  metadata={"name": k, "value": v, "path": path})
    return out


def _tier2_endpoint_classes(scan: dict, view: str) -> list[dict]:
    """Detect auth_endpoint based on path or Authorization header presence."""
    out: list[dict] = []
    seen: set[str] = set()
    for n in _iter_network_entries(scan):
        path = n.get("path") or n.get("url") or ""
        headers = n.get("headers") or {}
        # headers may be a list of {name,value} or a dict — accept both.
        header_names = []
        if isinstance(headers, dict):
            header_names = [str(k).lower() for k in headers.keys()]
        elif isinstance(headers, list):
            header_names = [str(h.get("name", "")).lower() for h in headers if isinstance(h, dict)]
        has_auth_header = "authorization" in header_names
        if AUTH_ENDPOINT_RE.match(path or "") or has_auth_header:
            key = path or "<no-path>"
            if key in seen:
                continue
            seen.add(key)
            _emit(out, view, "auth_endpoint", f"endpoint[{key}]",
                  action_semantic="auth_call",
                  resource=_resource_from_path(path),
                  metadata={"path": path, "auth_header": has_auth_header})
    return out


def _tier2_workflow_classes(scan: dict, view: str) -> list[dict]:
    """Detect payment_or_workflow from business_flow flags / resource hints."""
    out: list[dict] = []
    bf = scan.get("business_flow") or {}
    resource = scan.get("resource") or _resource_from_path(view)
    is_payment = bool(PAYMENT_RESOURCE_RE.match(resource or ""))
    has_state_machine = bool(bf.get("has_state_machine"))
    if is_payment or has_state_machine:
        sel = f"workflow[{resource or view}]"
        _emit(out, view, "payment_or_workflow", sel,
              action_semantic="state_transition",
              resource=resource,
              metadata={"has_state_machine": has_state_machine, "resource": resource})
    return out


def _tier2_error_responses(scan: dict, view: str) -> list[dict]:
    """Detect error_response from status>=500 or stack-trace markers in body."""
    out: list[dict] = []
    seen: set[str] = set()
    for n in _iter_network_entries(scan):
        status = n.get("status")
        body = n.get("response_body") or n.get("body") or ""
        if not isinstance(body, str):
            body = json.dumps(body)
        is_5xx = isinstance(status, int) and status >= 500
        has_trace = any(marker in body for marker in STACK_TRACE_MARKERS)
        if is_5xx or has_trace:
            path = n.get("path") or n.get("url") or "<unknown>"
            key = f"{path}:{status}"
            if key in seen:
                continue
            seen.add(key)
            _emit(out, view, "error_response", f"error[{path}]",
                  action_semantic="error_observed",
                  resource=_resource_from_path(path),
                  metadata={"status": status, "stack_trace": has_trace, "path": path})
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
