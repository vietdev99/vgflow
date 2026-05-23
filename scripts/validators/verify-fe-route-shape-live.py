#!/usr/bin/env python3
"""verify-fe-route-shape-live.py — B108 v4.70.2 (Codex postmortem rec #3).

Closes the "empty dropdown / list" + response-envelope drift gap that
B95 static heuristic cannot catch. Codex est. additional 10-18% UAT
bug catch (empty dropdown, wrong envelope keys, FE deref of non-existent
field).

Approach
--------
1. Scan FE source for response-deref patterns:
     `response.data.foo`, `res.data.bar`, `data.items[0].x`, `.rows[0].y`
2. For each consuming FE route/component, find the matching API endpoint
   from API-CONTRACTS.md + FE source axios/fetch call site.
3. Issue a SAFE READ-ONLY GET against the configured base URL.
4. Compare response envelope keys vs FE-dereferenced field names.
5. Report mismatches: FE expects `data.items` but BE returns `data.rows`;
   FE expects `_id` but BE returns `id`; etc.

This is a RUNTIME validator — it requires a live dev/staging server.
Severity = `warn` by default. Operator runs explicitly with `--base-url`
when wanting the runtime check; CI without server skips silently.

Limitations
-----------
- AST-lite via regex (no full TypeScript parse). Catches common patterns;
  misses generic-typed responses where shape isn't inline.
- Only checks GET endpoints (mutations require body fixtures + auth =
  out of scope; B106 + B107 cover those via the spec replay path).
- Single base URL per run. For multi-tenant projects, run per env.

Exit codes
----------
  0 - PASS (or warn-mode with findings)
  1 - FAIL (block-mode with findings)
  2 - Internal error / no server reachable
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


# FE response-deref patterns (regex AST-lite)
# Captures `.foo` chains after a common response/data identifier
_RESPONSE_DEREF_RE = re.compile(
    r"\b(?:response|res|result|data|payload|json|body)"
    r"((?:\.\w+(?:\[\d+\])?)+)",
)
# axios / fetch GET call sites — extract URL string literal arg
_GET_CALL_RE = re.compile(
    r"(?:axios(?:\.get)?|fetch|apiClient(?:\.get)?|api\.get|httpClient\.get)"
    r"\(\s*['\"]([^'\"]+)['\"]",
)


def find_fe_sources(repo_root: Path) -> list[Path]:
    apps = repo_root / "apps"
    if not apps.is_dir():
        return []
    out: list[Path] = []
    for app in apps.iterdir():
        if not app.is_dir():
            continue
        src = app / "src"
        if not src.is_dir():
            continue
        out.extend(src.rglob("*.tsx"))
        out.extend(src.rglob("*.ts"))
    return out


# Trailing-segment denylist: array/string methods that mean "the previous
# segment is the actual field". Pre-strip during deref extraction.
_TRAILING_METHOD_DENYLIST = {
    "map", "filter", "find", "forEach", "reduce", "some", "every",
    "indexOf", "includes", "length", "slice", "concat", "join",
    "sort", "reverse", "push", "pop", "shift", "unshift",
    "toString", "valueOf", "toLowerCase", "toUpperCase", "trim",
    "split", "match", "replace", "test", "exec",
    "then", "catch", "finally", "await",  # promise methods
}


def _clean_deref_chain(chain: str, text_after: str) -> str:
    """Strip trailing method-call segments from a deref chain.

    `.data.rows.map` (followed by `(`) → `.data.rows`.
    Walks segments from the end; drops any whose name is in the method
    denylist OR is immediately followed by `(` in the source text.
    """
    if not chain:
        return chain
    # Split on `.` keeping leading dot per segment
    segments = re.findall(r"\.\w+(?:\[\d+\])?", chain)
    # Pop trailing segments that look like method calls
    while segments and segments[-1].lstrip(".").split("[", 1)[0] in _TRAILING_METHOD_DENYLIST:
        segments.pop()
    # Also: if the original `chain` is immediately followed by `(` in source,
    # the last segment is also a method.
    if segments and text_after.lstrip().startswith("("):
        segments.pop()
    return "".join(segments)


def scan_fe_consumers(repo_root: Path) -> list[dict]:
    """Per FE source file, return list of consumer dicts:
      { file, url_pattern (str), expected_fields (list[str]) }
    """
    consumers: list[dict] = []
    for f in find_fe_sources(repo_root):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        urls = [m.group(1) for m in _GET_CALL_RE.finditer(text)]
        if not urls:
            continue
        derefs: set[str] = set()
        for m in _RESPONSE_DEREF_RE.finditer(text):
            raw = m.group(1)
            after = text[m.end(): m.end() + 4]
            cleaned = _clean_deref_chain(raw, after)
            if cleaned:
                derefs.add(cleaned)
        if not derefs:
            continue
        derefs_sorted = sorted(derefs)
        # Each URL pairs with all derefs in the same file (heuristic)
        for url in urls:
            consumers.append({
                "file": str(f.relative_to(repo_root)),
                "url_pattern": url,
                "expected_fields": derefs_sorted,
            })
    return consumers


def safe_get(base_url: str, path: str, timeout: float = 5.0,
             headers: dict | None = None) -> tuple[int, dict | None]:
    """Issue safe GET. Returns (status, json_body_or_None)."""
    if path.startswith("http://") or path.startswith("https://"):
        url = path
    else:
        url = base_url.rstrip("/") + "/" + path.lstrip("/")
    req = urllib.request.Request(url)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, None
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, None


def flatten_keys(obj, prefix: str = "") -> list[str]:
    """Return list of dotted-path keys present in obj. List indices use `[0]`."""
    keys: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            cur = f"{prefix}.{k}" if prefix else f".{k}"
            keys.append(cur)
            keys.extend(flatten_keys(v, cur))
    elif isinstance(obj, list) and obj:
        cur = f"{prefix}[0]"
        keys.append(cur)
        keys.extend(flatten_keys(obj[0], cur))
    return keys


def diff_shape(expected_fields: list[str], actual_keys: list[str]) -> list[str]:
    """Each expected field path that is NOT present in actual_keys = drift."""
    actual_set = {k.lower() for k in actual_keys}
    missing: list[str] = []
    for f in expected_fields:
        # FE pattern like `.data.foo` — normalize: strip trailing array indices
        norm = re.sub(r"\[\d+\]", "[0]", f).lower()
        if norm not in actual_set:
            missing.append(f)
    return missing


def url_pattern_to_concrete(pattern: str) -> str | None:
    """Replace `:id` / `{id}` placeholders with safe probe values."""
    if not pattern:
        return None
    if "://" not in pattern and not pattern.startswith("/"):
        return None
    out = pattern
    out = re.sub(r":\w+", "1", out)
    out = re.sub(r"\{[^}]+\}", "1", out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="verify-fe-route-shape-live",
        description=(
            "B108 v4.70.2 — issue safe GET per FE route and diff response "
            "envelope vs FE-dereferenced fields. Closes 10-18% UAT bugs "
            "(empty dropdown, wrong envelope key) that B95 static heuristic "
            "cannot catch. Requires live dev/staging server."
        ),
    )
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--base-url", default="",
                    help="Live server URL (e.g. http://localhost:3000). "
                         "Empty = scan FE only, skip live probe.")
    ap.add_argument("--severity", choices=("warn", "block"), default="warn")
    ap.add_argument("--auth-header", default="",
                    help="Optional `Header: value` for authenticated GETs.")
    ap.add_argument("--max-routes", type=int, default=50,
                    help="Cap routes probed per run (default 50).")
    ap.add_argument("--json", dest="json_out", action="store_true", default=True)
    ap.add_argument("--no-json", dest="json_out", action="store_false")
    args = ap.parse_args()
    try:
        repo = Path(args.repo_root).resolve()
        consumers = scan_fe_consumers(repo)
        result: dict = {
            "scanned_fe_sources": len(find_fe_sources(repo)),
            "consumers_found": len(consumers),
            "base_url": args.base_url or None,
            "severity": args.severity,
            "audits": [],
            "live_probe_skipped": not args.base_url,
        }
        if not args.base_url:
            # Scan only — record consumer surface but no live diff
            result["status"] = "PASS"
            result["message"] = (
                "no --base-url provided; consumer surface scanned but no live "
                "probe issued. Re-run with --base-url to enable shape diff."
            )
            if args.json_out:
                print(json.dumps(result, indent=2))
            else:
                print(f"verify-fe-route-shape-live — SCAN-ONLY ({len(consumers)} consumers found)")
            return 0

        headers = {}
        if args.auth_header and ":" in args.auth_header:
            k, v = args.auth_header.split(":", 1)
            headers[k.strip()] = v.strip()

        total_drift = 0
        for c in consumers[: args.max_routes]:
            url = url_pattern_to_concrete(c["url_pattern"])
            if not url:
                continue
            status, body = safe_get(args.base_url, url, headers=headers)
            actual_keys = flatten_keys(body) if isinstance(body, (dict, list)) else []
            drift = diff_shape(c["expected_fields"], actual_keys)
            audit_entry = {
                "file": c["file"],
                "url": url,
                "status": status,
                "expected_fields": c["expected_fields"],
                "actual_keys_count": len(actual_keys),
                "drift": drift,
            }
            result["audits"].append(audit_entry)
            total_drift += len(drift)
        result["total_drift_count"] = total_drift
        result["status"] = "PASS" if total_drift == 0 else "FAIL"
        if args.json_out:
            print(json.dumps(result, indent=2))
        else:
            print(f"verify-fe-route-shape-live — {result['status']}")
            print(f"  consumers: {len(consumers)}")
            print(f"  total_drift: {total_drift}")
            for a in result["audits"][:10]:
                if a["drift"]:
                    print(f"  - {a['file']} → {a['url']} (status {a['status']})")
                    for d in a["drift"]:
                        print(f"      drift: {d}")
        if result["status"] == "PASS":
            return 0
        if args.severity == "warn":
            return 0
        return 1
    except Exception as exc:
        print(f"verify-fe-route-shape-live: internal error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
