#!/usr/bin/env python3
"""verify-scanner-evidence-completeness.py — post-write evidence completeness gate.

Reads scanner output (scan-*.json or observe-*.jsonl) per scanner-report-contract
Section 2.5/2.7. For each observation, verifies required tier fields are
present (empty/null OK; MISSING NOT OK).

Output: writes per-file compliance.json + exits 0 (PASS) / 1 (BLOCK) / 2 (WARN).

Usage:
  # Roam mode — JSONL aggregation
  python3 verify-scanner-evidence-completeness.py \\
      --jsonl-glob ".vg/phases/03.5-*/roam/codex/observe-*.jsonl" \\
      --lens-from-filename \\
      --output .vg/phases/03.5-*/roam/.evidence-compliance.json

  # Review mode — per-view JSON
  python3 verify-scanner-evidence-completeness.py \\
      --json-glob ".vg/phases/03.5-*/scan-*.json" \\
      --tiers A,B,E \\
      --output .vg/phases/03.5-*/.evidence-compliance.json

Exit codes:
  0 — all observations >= compliance_threshold (default 80%)
  1 — at least one observation has 0 required fields → hard reject
  2 — partial compliance, below threshold but non-zero → warn
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

# Mirror of LENS_TIER_DEFAULTS in roam-compose-brief.py.
# Single source: keep these in sync.
LENS_TIER_DEFAULTS = {
    "lens-form-lifecycle":      ["A", "B"],
    "lens-business-coherence":  ["A", "B", "F"],
    "lens-table-interaction":   ["A", "B"],
    "lens-duplicate-submit":    ["A", "B"],
    "lens-csrf":                ["A", "C"],
    "lens-idor":                ["A", "C", "B"],
    "lens-bfla":                ["A", "C", "B"],
    "lens-tenant-boundary":     ["A", "C", "B"],
    "lens-auth-jwt":            ["A", "C", "F"],
    "lens-modal-state":         ["A", "E"],
    "lens-info-disclosure":     ["A", "C", "F"],
    "lens-input-injection":     ["A", "C"],
    "lens-file-upload":         ["A", "B", "C"],
    "lens-business-logic":      ["A", "B"],
    "lens-mass-assignment":     ["A", "B", "C"],
    "lens-open-redirect":       ["A", "C"],
    "lens-path-traversal":      ["A", "C"],
    "lens-ssrf":                ["A", "C"],
    "lens-authz-negative":      ["A", "C"],
}

TIER_REQUIRED_FIELDS = {
    "A": ["network_requests", "console_errors", "console_warnings", "dom_changed",
          "url_before", "url_after", "elapsed_ms", "screenshot", "page_title",
          "toast", "http_status_summary"],
    "B": ["form_validation_errors", "submit_button_state", "loading_indicator",
          "row_count_before", "row_count_after", "field_value_before",
          "field_value_after"],
    "C": ["cookies_filtered", "auth_state", "request_security_headers",
          "response_security_headers"],
    "D": ["websocket_frames", "polling_calls", "background_job_status"],
    "E": ["viewport_size", "focus_state", "aria_state", "tab_order",
          "a11y_tree_excerpt"],
    "F": ["storage_keys", "indexedDB_dbs", "store_snapshot"],
}


def required_for_tiers(tiers: list[str]) -> list[str]:
    out = []
    for t in tiers:
        out.extend(TIER_REQUIRED_FIELDS.get(t, []))
    return out


def lens_from_filename(path: Path) -> str | None:
    """observe-S03-lens-form-lifecycle.jsonl → 'lens-form-lifecycle'."""
    m = re.search(r"(lens-[a-z-]+)", path.stem)
    return m.group(1) if m else None


def check_observation(obs: dict, required: list[str]) -> dict:
    """Per-observation compliance. Returns {present, missing, total, pct}."""
    evidence = obs.get("evidence") or {}
    if not isinstance(evidence, dict):
        return {"present": [], "missing": required, "total": len(required), "pct": 0,
                "_error": "evidence not an object"}
    missing = [k for k in required if k not in evidence]
    present = [k for k in required if k in evidence]
    pct = round(100 * len(present) / len(required), 1) if required else 100.0
    return {"present": present, "missing": missing, "total": len(required), "pct": pct}


def banned_word_check(text: str) -> list[str]:
    """Mirror of scanner-report-contract Section 1 banned vocabulary scan."""
    banned = ["bug", "broken", "wrong", "incorrect", "fail", "failed", "failure",
              "critical", "major", "minor", "severe", "should", "must", "need to",
              "needs", "fix", "repair", "patch", "obviously", "clearly", "apparently"]
    text_lower = text.lower()
    hits = []
    for w in banned:
        # word-boundary match
        if re.search(r"\b" + re.escape(w) + r"\b", text_lower):
            hits.append(w)
    return sorted(set(hits))


def process_jsonl(path: Path, lens: str) -> dict:
    """Process a JSONL file (roam mode). Each line is an event."""
    tiers = LENS_TIER_DEFAULTS.get(lens, ["A"])
    required = required_for_tiers(tiers)
    observations = []
    wrapper_seen = False
    completion_seen = False
    for ln, raw in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except Exception:
            observations.append({"line": ln, "_error": "invalid JSON"})
            continue
        kind = ev.get("_kind")
        if kind == "observation" or (kind is None and "step" in ev and "match" in ev):
            obs_check = check_observation(ev, required)
            obs_check["line"] = ln
            # Banned-word scan on observed + step text
            text_blob = " ".join(str(ev.get(k, "")) for k in ("step", "observed", "expected_per_lens"))
            banned = banned_word_check(text_blob)
            if banned:
                obs_check["banned_words"] = banned
            observations.append(obs_check)
        elif "_observations_follow" in ev:
            wrapper_seen = True
        elif kind == "completion" or ev.get("step") == "complete":
            completion_seen = True

    if not observations:
        return {
            "file": str(path),
            "lens": lens,
            "tiers": tiers,
            "required_fields": required,
            "observation_count": 0,
            "compliance_pct": 0,
            "verdict": "BLOCK",
            "reason": "no observations parsed",
            "wrapper_seen": wrapper_seen,
            "completion_seen": completion_seen,
        }

    # Aggregate compliance
    avg_pct = round(sum(o.get("pct", 0) for o in observations) / len(observations), 1)
    any_zero = any(o.get("pct", 0) == 0 for o in observations)
    banned_total = sum(len(o.get("banned_words", [])) for o in observations)

    return {
        "file": str(path),
        "lens": lens,
        "tiers": tiers,
        "required_fields_count": len(required),
        "observation_count": len(observations),
        "compliance_pct_avg": avg_pct,
        "any_zero_compliance": any_zero,
        "banned_word_hits_total": banned_total,
        "wrapper_seen": wrapper_seen,
        "completion_seen": completion_seen,
        "observations": observations[:50],  # cap output size
    }


def process_json(path: Path, tiers: list[str]) -> dict:
    """Process a single JSON file (review mode — vg-haiku-scanner output)."""
    required = required_for_tiers(tiers)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"file": str(path), "verdict": "BLOCK", "reason": f"parse error: {e}"}

    obs_list = data.get("observations") or data.get("results") or []
    if not isinstance(obs_list, list) or not obs_list:
        return {
            "file": str(path),
            "tiers": tiers,
            "verdict": "WARN",
            "reason": "no observations array (legacy schema?)",
            "observation_count": 0,
        }

    checked = []
    for i, obs in enumerate(obs_list):
        if not isinstance(obs, dict):
            checked.append({"index": i, "_error": "not an object"})
            continue
        c = check_observation(obs, required)
        c["index"] = i
        text_blob = " ".join(str(obs.get(k, "")) for k in ("step", "observed", "action", "outcome"))
        banned = banned_word_check(text_blob)
        if banned:
            c["banned_words"] = banned
        checked.append(c)

    avg_pct = round(sum(c.get("pct", 0) for c in checked) / len(checked), 1)
    any_zero = any(c.get("pct", 0) == 0 for c in checked)
    banned_total = sum(len(c.get("banned_words", [])) for c in checked)

    return {
        "file": str(path),
        "tiers": tiers,
        "required_fields_count": len(required),
        "observation_count": len(obs_list),
        "compliance_pct_avg": avg_pct,
        "any_zero_compliance": any_zero,
        "banned_word_hits_total": banned_total,
        "observations_sample": checked[:50],
    }


def verdict_for(report: dict, threshold: float) -> str:
    """Map compliance to PASS/WARN/BLOCK."""
    if report.get("any_zero_compliance"):
        return "BLOCK"
    pct = report.get("compliance_pct_avg", 0)
    if pct >= threshold:
        return "PASS"
    if pct >= 50:
        return "WARN"
    return "BLOCK"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jsonl-glob", help="Glob for roam observe-*.jsonl files")
    ap.add_argument("--json-glob", help="Glob for review scan-*.json files")
    ap.add_argument("--tiers", default="A", help="Comma-separated tier list for --json-glob (default A)")
    ap.add_argument("--lens-from-filename", action="store_true",
                    help="For --jsonl-glob, derive lens from filename (observe-X-lens-Y.jsonl)")
    ap.add_argument("--lens", help="Force lens for all --jsonl-glob files")
    ap.add_argument("--threshold", type=float, default=80.0,
                    help="PASS threshold % (default 80)")
    ap.add_argument("--output", help="Write report JSON to this path")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    reports = []
    if args.jsonl_glob:
        for p in sorted(glob.glob(args.jsonl_glob)):
            path = Path(p)
            lens = args.lens or (lens_from_filename(path) if args.lens_from_filename else None)
            if not lens:
                reports.append({"file": p, "verdict": "BLOCK",
                                "reason": "lens not specified — pass --lens or --lens-from-filename"})
                continue
            r = process_jsonl(path, lens)
            r["verdict"] = verdict_for(r, args.threshold)
            reports.append(r)

    if args.json_glob:
        tiers = [t.strip() for t in args.tiers.split(",") if t.strip()]
        for p in sorted(glob.glob(args.json_glob)):
            r = process_json(Path(p), tiers)
            r["verdict"] = verdict_for(r, args.threshold)
            reports.append(r)

    if not reports:
        if not args.quiet:
            print("No files matched", file=sys.stderr)
        return 0

    overall_summary = {
        "report_count": len(reports),
        "by_verdict": {},
        "threshold_pct": args.threshold,
        "reports": reports,
    }
    for r in reports:
        v = r.get("verdict", "UNKNOWN")
        overall_summary["by_verdict"][v] = overall_summary["by_verdict"].get(v, 0) + 1

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(overall_summary, indent=2))

    if not args.quiet:
        print(f"Scanner evidence completeness:")
        print(f"  Files checked: {len(reports)}")
        for v, count in sorted(overall_summary["by_verdict"].items()):
            print(f"    {v}: {count}")
        # Show worst offenders
        bad = [r for r in reports if r.get("verdict") in ("BLOCK", "WARN")]
        if bad:
            print(f"  Issues:")
            for r in bad[:10]:
                pct = r.get("compliance_pct_avg", 0)
                miss = r.get("any_zero_compliance", False)
                banned = r.get("banned_word_hits_total", 0)
                print(f"    [{r['verdict']}] {r['file']} — compliance={pct}% any_zero={miss} banned={banned}")

    # Exit code
    if any(r.get("verdict") == "BLOCK" for r in reports):
        return 1
    if any(r.get("verdict") == "WARN" for r in reports):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
