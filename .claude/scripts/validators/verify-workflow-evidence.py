#!/usr/bin/env python3
"""F5 v2.64.0 — verify-workflow-evidence.py.

Workflow tracer validator. Reads ${PHASE_DIR}/WORKFLOW-SPECS/WF-NN.md
(YAML in fenced ```yaml block, produced by /vg:blueprint Pass 3) and
walks fe-root + be-root looking for code evidence per step.

Per step status taxonomy (design §2c):
  - found     evidence located via lexical pattern match
  - missing   step declared but no code found
  - divergent code found but URL/method/etc doesn't match the step
  - ambiguous multiple candidates, can't disambiguate
  - skipped   profile/flag exempts this step

Default mode: WARN-ONLY (rc=0, evidence written even on drift).
--strict mode: BLOCK on missing OR divergent (per user §9.3 decision).

Pure stdlib + optional pyyaml. No tree-sitter / babel / external deps.

Usage:
  verify-workflow-evidence.py --phase {N} [--phase-dir PATH]
                              --fe-root DIR --be-root DIR
                              [--workflow-id WF-NN] [--strict]
                              [--evidence-out PATH] [--workflows-dir PATH]

Exit codes:
  0 = no drift (all found/skipped/ambiguous)
  0 = drift detected without --strict (WARN-only, evidence emitted)
  1 = drift detected with --strict (BLOCK)
  2 = WORKFLOW-SPECS missing / invocation error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

# YAML loader: prefer pyyaml, fall back to a minimal hand parser for the
# narrow subset of WORKFLOW-SPECS YAML (id/name/actors/steps[].actor/.action).
try:
    import yaml  # type: ignore
    _HAS_YAML = True
except ImportError:  # pragma: no cover
    _HAS_YAML = False


YAML_BLOCK_RE = re.compile(r"```yaml\s*\n(.*?)\n```", re.DOTALL)

# ---- Pattern library ---------------------------------------------------

# Each pattern entry maps a step "action keyword" (regex) → search config.
# Search config has: files (list of glob suffixes), actor restriction
# (FE/BE/either), regexes to look for. The first match becomes evidence;
# multiple distinct file-line matches → ambiguous.
FE_EXTS = {".tsx", ".jsx", ".ts", ".js", ".vue"}
BE_EXTS = {".ts", ".js", ".py", ".go"}

CLICK_PATTERNS = [
    (re.compile(r"onClick\s*=\s*\{?\s*([\w$]+)"), "onClick handler"),
    (re.compile(r"on:click\s*=\s*\"([\w$]+)"), "Vue click"),
    (re.compile(r"<button[^>]*type\s*=\s*[\"']submit[\"']"), "submit button"),
    (re.compile(r"@click\s*=\s*\"([\w$]+)"), "Vue v-on click"),
]

VALIDATE_PATTERNS = [
    (re.compile(r"\.handleSubmit\b"), "handleSubmit call"),
    (re.compile(r"useForm\s*\("), "useForm hook"),
    (re.compile(r"\.parse\s*\("), "zod parse"),
    (re.compile(r"\b(?:yup|joi|zod)\."), "validation lib"),
]

HANDLE_RESPONSE_PATTERNS = [
    (re.compile(r"\.then\s*\("), "promise then"),
    (re.compile(r"await\s+fetch\b"), "await fetch"),
    (re.compile(r"await\s+\w+\.\w+\s*\("), "await async call"),
    (re.compile(r"onSuccess\s*:"), "react-query onSuccess"),
    (re.compile(r"\.catch\s*\("), "promise catch"),
]

INVALIDATE_PATTERNS = [
    (re.compile(r"invalidateQueries\s*\("), "react-query invalidate"),
    (re.compile(r"\bmutate\s*\("), "swr mutate"),
    (re.compile(r"refetch\s*\("), "explicit refetch"),
]

NAVIGATE_PATTERNS = [
    (re.compile(r"\bnavigate\s*\("), "react-router navigate"),
    (re.compile(r"router\.push\s*\("), "next router push"),
    (re.compile(r"history\.push\s*\("), "history push"),
    (re.compile(r"window\.location\.href\s*="), "raw redirect"),
    (re.compile(r"<Redirect\b"), "react-router Redirect"),
]

TOAST_PATTERNS = [
    (re.compile(r"\btoast\.\w+\s*\("), "toast call"),
    (re.compile(r"enqueueSnackbar\s*\("), "snackbar"),
    (re.compile(r"notification\.\w+\s*\("), "antd notification"),
    (re.compile(r"\bmessage\.\w+\s*\("), "antd message"),
]

STATE_PATTERNS = [
    (re.compile(r"\bset[A-Z]\w*\s*\("), "useState setter"),
    (re.compile(r"\.setState\s*\("), "class setState"),
    (re.compile(r"\bdispatch\s*\("), "redux dispatch"),
]

BE_PERSIST_PATTERNS = [
    (re.compile(r"\.save\s*\("), "ORM save"),
    (re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE), "raw SQL insert"),
    (re.compile(r"\bUPDATE\s+\w+\s+SET\b", re.IGNORECASE), "raw SQL update"),
    (re.compile(r"await\s+prisma\.\w+\.\w+\("), "prisma op"),
    (re.compile(r"\.create\s*\("), "ORM create"),
    (re.compile(r"\.update\s*\("), "ORM update"),
    (re.compile(r"\.findOne\s*\("), "ORM findOne"),
    (re.compile(r"\.findAll\s*\("), "ORM findAll"),
]


# HTTP method → FE call regex (extract URL group 1). Matches fetch/axios/api.
def _fe_http_patterns(method: str) -> list[tuple[re.Pattern, str]]:
    method_l = method.lower()
    method_u = method.upper()
    return [
        # axios.METHOD('/url', ...)
        (re.compile(rf"\baxios\.{method_l}\s*\(\s*[\"']([^\"']+)[\"']"),
         f"axios.{method_l}"),
        # api.METHOD('/url', ...)
        (re.compile(rf"\bapi\.{method_l}\s*\(\s*[\"']([^\"']+)[\"']"),
         f"api.{method_l}"),
        # fetch('/url', { method: 'METHOD' })
        (re.compile(
            rf"fetch\s*\(\s*[\"']([^\"']+)[\"'][^)]*method\s*:\s*[\"']{method_u}[\"']",
            re.DOTALL,
         ),
         f"fetch {method_u}"),
        # fetch('/url')  — only valid for GET; assume default-method
        # We'll only register this for GET below.
    ]


def _fe_http_get_only() -> list[tuple[re.Pattern, str]]:
    """Bare fetch('/url') without method opts → defaults to GET."""
    # Only register bare fetch as GET evidence when no method= is in the call.
    return [
        (re.compile(r"fetch\s*\(\s*[\"']([^\"']+)[\"']\s*\)"), "fetch (default GET)"),
    ]


# BE route patterns per HTTP method
def _be_route_patterns(method: str) -> list[tuple[re.Pattern, str]]:
    m_l = method.lower()
    m_u = method.upper()
    return [
        (re.compile(rf"router\.{m_l}\s*\(\s*[\"']([^\"']+)[\"']"),
         f"express router.{m_l}"),
        (re.compile(rf"app\.{m_l}\s*\(\s*[\"']([^\"']+)[\"']"),
         f"express app.{m_l}"),
        (re.compile(rf"@(?:fastify\.)?{m_l}\s*\(\s*[\"']([^\"']+)[\"']"),
         f"fastify @{m_l}"),
        # Flask: @app.route('/path', methods=['POST']) — match route + methods
        (re.compile(
            rf"@\w+\.route\s*\(\s*[\"']([^\"']+)[\"'][^)]*methods\s*=\s*\[[^\]]*[\"']{m_u}[\"']",
            re.DOTALL,
         ),
         f"flask @route {m_u}"),
        # FastAPI: @app.METHOD('/path')
        (re.compile(rf"@\w+\.{m_l}\s*\(\s*[\"']([^\"']+)[\"']"),
         f"fastapi @{m_l}"),
        # Go gin/echo: r.METHOD("/path", handler)
        (re.compile(rf"\.{m_u}\s*\(\s*[\"']([^\"']+)[\"']"),
         f"go {m_u}"),
    ]


# ---- Normalization for URL comparison ----------------------------------

PATH_PARAM_RE = re.compile(r":[A-Za-z_][\w]*|\{[^}]+\}|\$\{[^}]+\}")


def _normalize_path(p: str) -> str:
    """Collapse path params (`:id`, `{id}`, `${var}`) → `:param`."""
    return PATH_PARAM_RE.sub(":param", p.rstrip("/"))


# ---- YAML parsing ------------------------------------------------------

def _hand_parse_workflow(text: str) -> dict[str, Any] | None:
    """Last-resort minimal YAML parser for the WF schema.

    Handles top-level scalar fields (`id`, `name`) and the `steps:` block of
    list-of-mappings. Sufficient for malformed/non-pyyaml environments.
    """
    out: dict[str, Any] = {}
    steps: list[dict[str, str]] = []
    cur: dict[str, str] | None = None
    in_steps = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        # New step: "- actor: X" or "- key: val" at <=4-space indent
        if line.lstrip().startswith("-"):
            if cur:
                steps.append(cur)
            cur = {}
            in_steps = True
            after = line.lstrip()[1:].strip()
            if ":" in after:
                k, v = after.split(":", 1)
                cur[k.strip()] = v.strip().strip("\"'")
            continue
        if in_steps and line.startswith((" ", "\t")) and ":" in line:
            k, v = line.strip().split(":", 1)
            if cur is not None:
                cur[k.strip()] = v.strip().strip("\"'")
            continue
        # Top-level key
        if not line.startswith((" ", "\t")) and ":" in line:
            in_steps = False
            if cur:
                steps.append(cur)
                cur = None
            k, v = line.split(":", 1)
            key = k.strip()
            val = v.strip()
            if key == "steps":
                in_steps = True
                continue
            out[key] = val.strip("\"'") if val else ""
    if cur:
        steps.append(cur)
    if steps:
        out["steps"] = steps
    return out if out.get("id") or out.get("steps") else None


def _parse_workflow_md(md_path: Path) -> dict[str, Any] | None:
    """Extract YAML body from fenced ```yaml block + parse."""
    text = md_path.read_text(encoding="utf-8")
    match = YAML_BLOCK_RE.search(text)
    if not match:
        return None
    body = match.group(1)
    if _HAS_YAML:
        try:
            data = yaml.safe_load(body)  # type: ignore
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return _hand_parse_workflow(body)


# ---- File walk + search ------------------------------------------------

def _read_text_safe(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def _vue_extract_script(text: str) -> str:
    """Extract <script> block contents from Vue SFC; pass-through if no <script>."""
    m = re.search(r"<script[^>]*>(.*?)</script>", text, re.DOTALL)
    if m:
        return m.group(1)
    return text


def _walk_files(root: Path, exts: set[str]) -> list[Path]:
    out: list[Path] = []
    if not root.is_dir():
        return out
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            out.append(p)
    return out


def _search_first(
    files: list[Path],
    patterns: list[tuple[re.Pattern, str]],
) -> tuple[list[dict], list[dict]]:
    """Return (all_matches, unique_files). Each match: file/line/anchor/label/groups."""
    matches: list[dict] = []
    seen_keys: set[tuple[str, int]] = set()
    for f in files:
        text = _read_text_safe(f)
        if text is None:
            continue
        if f.suffix.lower() == ".vue":
            text = _vue_extract_script(text)
        for line_idx, line in enumerate(text.splitlines(), start=1):
            for pat, label in patterns:
                m = pat.search(line)
                if m:
                    key = (str(f), line_idx)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    matches.append({
                        "file": str(f),
                        "line": line_idx,
                        "anchor": line.strip()[:120],
                        "label": label,
                        "groups": list(m.groups()) if m.groups() else [],
                    })
                    break
    unique_files = sorted({m["file"] for m in matches})
    return matches, [{"file": uf} for uf in unique_files]


# ---- Action dispatcher -------------------------------------------------

HTTP_VERBS = ("GET", "POST", "PUT", "PATCH", "DELETE")


def _classify_step(actor: str, action: str) -> tuple[str, dict[str, Any]]:
    """Classify a step → (kind, meta). meta carries url/method when HTTP."""
    actor_l = (actor or "").strip().lower()
    action_l = (action or "").strip().lower()

    # HTTP step: detect "VERB /path" pattern
    http_match = re.match(r"^(get|post|put|patch|delete)\s+(/\S+)", action_l)
    if http_match:
        method = http_match.group(1).upper()
        url = http_match.group(2)
        if actor_l == "be":
            return "be_route", {"method": method, "url": url}
        return "fe_http", {"method": method, "url": url}

    # User clicks
    if actor_l == "user" or "click" in action_l or "submit" in action_l:
        if "submit" in action_l or "click" in action_l:
            return "click", {}

    # Validate form
    if "validate" in action_l and actor_l in ("fe", ""):
        return "validate", {}

    # Handle response
    if "handle response" in action_l or "response" in action_l:
        return "handle_response", {}

    # Invalidate cache
    if "invalidate" in action_l or "cache" in action_l:
        return "invalidate", {}

    # Navigate / redirect
    if "navigate" in action_l or "redirect" in action_l:
        return "navigate", {}

    # Toast
    if "toast" in action_l or "notification" in action_l or "snack" in action_l:
        return "toast", {}

    # State update
    if "set state" in action_l or "update state" in action_l or "state" in action_l:
        return "state", {}

    # BE persist/save
    if actor_l == "be" and (
        "persist" in action_l or "save" in action_l
        or "validate" in action_l or "create" in action_l or "update" in action_l
    ):
        return "be_persist", {}

    return "unknown", {}


# ---- Step → evidence ---------------------------------------------------

def _evaluate_step(
    step_idx: int,
    step: dict[str, Any],
    fe_files_by_ext: dict[str, list[Path]],
    be_files_by_ext: dict[str, list[Path]],
) -> dict[str, Any]:
    actor = (step.get("actor") or "").strip()
    action = (step.get("action") or "").strip()
    kind, meta = _classify_step(actor, action)

    out: dict[str, Any] = {
        "step_idx": step_idx,
        "actor": actor,
        "action": action,
        "evidence": None,
        "status": "missing",
    }

    fe_all = sum((fe_files_by_ext.get(e, []) for e in FE_EXTS), [])
    be_all = sum((be_files_by_ext.get(e, []) for e in BE_EXTS), [])

    if kind == "fe_http":
        method = meta["method"]
        expected_url = _normalize_path(meta["url"])
        patterns = _fe_http_patterns(method)
        if method == "GET":
            patterns = patterns + _fe_http_get_only()
        matches, _files = _search_first(fe_all, patterns)
        # Check URL match
        url_matches = []
        any_url_seen: list[str] = []
        for m in matches:
            actual_url = m["groups"][0] if m["groups"] else ""
            any_url_seen.append(actual_url)
            if _normalize_path(actual_url) == expected_url:
                url_matches.append(m)
        if url_matches:
            best = url_matches[0]
            out["evidence"] = {
                "file": best["file"],
                "line": best["line"],
                "anchor": best["anchor"],
                "ast_node": "CallExpression",
            }
            if len(url_matches) > 1:
                out["status"] = "ambiguous"
                out["candidates"] = [
                    {"file": m["file"], "line": m["line"]} for m in url_matches[:5]
                ]
            else:
                out["status"] = "found"
        elif matches:
            # Found HTTP calls of same method but URL doesn't match
            out["status"] = "divergent"
            best = matches[0]
            out["evidence"] = {
                "file": best["file"],
                "line": best["line"],
                "anchor": best["anchor"],
                "ast_node": "CallExpression",
            }
            out["divergent_reason"] = (
                f"expected url={meta['url']} but found url={any_url_seen[0]}"
            )
        else:
            out["missing_reason"] = (
                f"no fetch/axios call for {method} {meta['url']} in fe-root"
            )
        return out

    if kind == "be_route":
        method = meta["method"]
        expected_url = _normalize_path(meta["url"])
        patterns = _be_route_patterns(method)
        matches, _files = _search_first(be_all, patterns)
        url_matches = []
        any_seen: list[str] = []
        for m in matches:
            actual = m["groups"][0] if m["groups"] else ""
            any_seen.append(actual)
            if _normalize_path(actual) == expected_url:
                url_matches.append(m)
        if url_matches:
            best = url_matches[0]
            out["evidence"] = {
                "file": best["file"],
                "line": best["line"],
                "anchor": best["anchor"],
                "ast_node": "MethodCall",
            }
            out["status"] = "ambiguous" if len(url_matches) > 1 else "found"
            if out["status"] == "ambiguous":
                out["candidates"] = [
                    {"file": m["file"], "line": m["line"]} for m in url_matches[:5]
                ]
        elif matches:
            out["status"] = "divergent"
            best = matches[0]
            out["evidence"] = {
                "file": best["file"],
                "line": best["line"],
                "anchor": best["anchor"],
                "ast_node": "MethodCall",
            }
            out["divergent_reason"] = (
                f"expected route={meta['url']} but found route={any_seen[0]}"
            )
        else:
            out["missing_reason"] = (
                f"no BE route handler for {method} {meta['url']} in be-root"
            )
        return out

    # All other lexical step kinds: pick the right pattern bank
    pattern_map = {
        "click": (CLICK_PATTERNS, fe_all, "JSXAttribute"),
        "validate": (VALIDATE_PATTERNS, fe_all, "MethodCall"),
        "handle_response": (HANDLE_RESPONSE_PATTERNS, fe_all, "MethodCall"),
        "invalidate": (INVALIDATE_PATTERNS, fe_all, "CallExpression"),
        "navigate": (NAVIGATE_PATTERNS, fe_all, "CallExpression"),
        "toast": (TOAST_PATTERNS, fe_all, "CallExpression"),
        "state": (STATE_PATTERNS, fe_all, "CallExpression"),
        "be_persist": (BE_PERSIST_PATTERNS, be_all, "MethodCall"),
    }

    if kind in pattern_map:
        patterns, files, ast_node = pattern_map[kind]
        matches, unique = _search_first(files, patterns)
        if matches:
            best = matches[0]
            out["evidence"] = {
                "file": best["file"],
                "line": best["line"],
                "anchor": best["anchor"],
                "ast_node": ast_node,
            }
            if len({m["file"] for m in matches}) > 1:
                out["status"] = "ambiguous"
                out["candidates"] = [
                    {"file": m["file"], "line": m["line"]} for m in matches[:5]
                ]
            else:
                out["status"] = "found"
        else:
            out["missing_reason"] = f"no lexical evidence for action='{action}'"
        return out

    # Unknown action — skip rather than mark missing (avoid false positives)
    out["status"] = "skipped"
    out["skipped_reason"] = (
        f"action='{action}' has no lexical pattern (use ast_search_hint or "
        f"refine action verb)"
    )
    return out


# ---- Main --------------------------------------------------------------

def _drift_severity(stats: dict[str, int]) -> str:
    if stats.get("missing", 0) > 0 or stats.get("divergent", 0) > 0:
        return "warn"
    return "info"


def main() -> int:
    p = argparse.ArgumentParser(
        description="F5 verify-workflow-evidence — workflow tracer validator")
    p.add_argument("--phase", required=True, help="Phase number (e.g. 7.14)")
    p.add_argument("--phase-dir", help="Phase directory (default: .vg/phases/<phase>)")
    p.add_argument("--fe-root", required=True, help="Frontend source tree root")
    p.add_argument("--be-root", required=True, help="Backend source tree root")
    p.add_argument("--workflow-id", help="Filter to single workflow id (e.g. WF-001)")
    p.add_argument("--strict", action="store_true",
                   help="BLOCK (rc=1) on missing or divergent steps")
    p.add_argument("--evidence-out", help="Combined evidence summary JSON path")
    p.add_argument("--workflows-dir",
                   help="Override WORKFLOW-SPECS dir (default: ${PHASE_DIR}/WORKFLOW-SPECS)")
    args = p.parse_args()

    if args.phase_dir:
        phase_dir = Path(args.phase_dir)
    else:
        phase_dir = REPO_ROOT / ".vg" / "phases" / args.phase

    workflows_dir = (
        Path(args.workflows_dir) if args.workflows_dir
        else phase_dir / "WORKFLOW-SPECS"
    )
    if not workflows_dir.is_dir():
        print(
            f"ERROR: WORKFLOW-SPECS dir not found at {workflows_dir}",
            file=sys.stderr,
        )
        return 2

    fe_root = Path(args.fe_root)
    be_root = Path(args.be_root)
    if not fe_root.is_dir():
        print(f"ERROR: --fe-root not a directory: {fe_root}", file=sys.stderr)
        return 2
    if not be_root.is_dir():
        print(f"ERROR: --be-root not a directory: {be_root}", file=sys.stderr)
        return 2

    # Discover workflow files
    wf_files = sorted([
        f for f in workflows_dir.glob("WF-*.md")
    ])
    # Filter out index.md
    wf_files = [f for f in wf_files if f.name.lower() != "index.md"]
    if not wf_files:
        print(
            f"ERROR: no WF-*.md files in {workflows_dir} (no workflows declared)",
            file=sys.stderr,
        )
        return 2

    if args.workflow_id:
        wf_files = [
            f for f in wf_files
            if f.stem == args.workflow_id or args.workflow_id in f.name
        ]
        if not wf_files:
            print(
                f"ERROR: --workflow-id {args.workflow_id} not found in {workflows_dir}",
                file=sys.stderr,
            )
            return 2

    # Pre-walk fe + be source trees once
    fe_files_by_ext: dict[str, list[Path]] = {}
    for ext in FE_EXTS:
        fe_files_by_ext[ext] = _walk_files(fe_root, {ext})
    be_files_by_ext: dict[str, list[Path]] = {}
    for ext in BE_EXTS:
        be_files_by_ext[ext] = _walk_files(be_root, {ext})

    evidence_dir = phase_dir / "WORKFLOW-EVIDENCE"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    all_workflows: list[dict[str, Any]] = []
    drift_workflows: list[str] = []

    for wf_file in wf_files:
        wf = _parse_workflow_md(wf_file)
        if not wf:
            print(f"WARN: skipping unparseable workflow: {wf_file}", file=sys.stderr)
            continue
        wf_id = wf.get("id") or wf_file.stem
        steps_raw = wf.get("steps") or []
        step_results: list[dict[str, Any]] = []
        for idx, step in enumerate(steps_raw):
            if not isinstance(step, dict):
                continue
            step_results.append(
                _evaluate_step(idx, step, fe_files_by_ext, be_files_by_ext)
            )

        # Summary stats
        stats = {"found": 0, "missing": 0, "divergent": 0,
                 "ambiguous": 0, "skipped": 0}
        for s in step_results:
            stats[s["status"]] = stats.get(s["status"], 0) + 1
        stats["total_steps"] = len(step_results)
        stats["drift_severity"] = _drift_severity(stats)

        result = {
            "workflow_id": wf_id,
            "name": wf.get("name", ""),
            "phase": args.phase,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "steps": step_results,
            "summary": stats,
        }

        out_path = evidence_dir / f"{wf_id}.json"
        out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

        if stats["missing"] > 0 or stats["divergent"] > 0:
            drift_workflows.append(wf_id)
        all_workflows.append(result)

    # Aggregate summary
    aggregate = {
        "phase": args.phase,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "workflows": all_workflows,
        "summary": {
            "total_workflows": len(all_workflows),
            "drift_workflows": drift_workflows,
            "drift_count": len(drift_workflows),
        },
        "detected_by": "verify-workflow-evidence.py",
    }

    if args.evidence_out:
        Path(args.evidence_out).write_text(
            json.dumps(aggregate, indent=2), encoding="utf-8",
        )

    if not drift_workflows:
        print(
            f"OK: {len(all_workflows)} workflow(s) traced, all steps found "
            f"(or skipped/ambiguous)"
        )
        return 0

    severity = "BLOCK" if args.strict else "warn"
    summary = (
        f"{len(drift_workflows)}/{len(all_workflows)} workflow(s) have drift: "
        f"{', '.join(drift_workflows)}"
    )
    if args.strict:
        print(f"BLOCK: {summary}", file=sys.stderr)
        return 1
    print(f"WARN: {summary}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
