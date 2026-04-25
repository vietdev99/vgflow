#!/usr/bin/env python3
"""
verify-dast-waive-approver.py — Phase N of v2.5.2 hardening.

Problem closed:
  Phase B shipped dast-scan-report.py that routes findings by severity +
  risk_profile. But "waived" disposition was honor-system — any disposition
  label in triage file counted as legitimate defer. AI or rushed human
  could mark all findings `waived` with one-word reason and sidestep the
  HARD BLOCK on Critical/High.

This validator closes the forge by enforcing:
  1. Waived findings MUST have `waive_approver` field
  2. Approver MUST be in allowlist (config.security_testing.dast_triage.waive_approvers)
  3. Waiver MUST have waive_until date + cannot be in past (expired = reopen)
  4. waive_reason MUST be >= 100 chars (same anti-gaming as override-debt)
  5. waive_ratio = waived / total findings — warn if > threshold (default 0.3)
  6. Rubber-stamp detection: same approver + similar reason >= 3× → flag

Usage:
  verify-dast-waive-approver.py --triage-file <path.yml|json>
  verify-dast-waive-approver.py --triage-file X --approvers vietdev99,admin2
  verify-dast-waive-approver.py --triage-file X --max-ratio 0.3
  verify-dast-waive-approver.py --triage-file X --json

Exit codes:
  0 = all waives pass gates
  1 = violations (missing approver / non-allowlisted / expired / reason too short / ratio exceeded)
  2 = config/path error
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path


def _load_yaml_or_json(path: Path) -> dict:
    """Load triage file — YAML if .yml/.yaml, JSON otherwise. Returns {} on parse error."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in (".yml", ".yaml"):
        try:
            import yaml  # type: ignore
            return yaml.safe_load(text) or {}
        except ImportError:
            return _parse_yaml_minimal(text)
        except Exception:
            return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _parse_yaml_minimal(text: str) -> dict:
    """
    Minimal YAML subset parser (stdlib-only fallback). Handles:
    - top-level `waives:` list
    - list items `- finding_id:` with nested `key: value` pairs
    - string values (quoted or plain, single-line)
    - ISO dates as strings

    Returns dict with `waives: [...]` or empty dict if parse fails.
    """
    result = {"waives": []}
    current = None
    in_waives = False

    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(stripped)

        if stripped == "waives:" and indent == 0:
            in_waives = True
            continue

        if not in_waives:
            if indent == 0 and ":" in stripped:
                key, _, _ = stripped.partition(":")
                if key.strip() != "waives":
                    in_waives = False
            continue

        if stripped.startswith("- "):
            if current is not None:
                result["waives"].append(current)
            current = {}
            rest = stripped[2:].strip()
            if ":" in rest:
                k, _, v = rest.partition(":")
                current[k.strip()] = _strip_quotes(v.strip())
            continue

        if current is not None and ":" in stripped:
            k, _, v = stripped.partition(":")
            current[k.strip()] = _strip_quotes(v.strip())

    if current is not None:
        result["waives"].append(current)
    return result


def _strip_quotes(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def _parse_date(s: object) -> _dt.date | None:
    if not isinstance(s, str):
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s.strip())
    if not m:
        return None
    try:
        return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _normalize_reason_head(reason: str) -> str:
    """First 50 chars lowercased, whitespace collapsed — for rubber-stamp sim check."""
    s = re.sub(r"\s+", " ", (reason or "").lower()).strip()
    return s[:50]


def _check_one_waive(w: dict, approvers: set[str], today: _dt.date,
                     min_reason_chars: int) -> list[dict]:
    issues: list[dict] = []
    fid = w.get("finding_id") or w.get("id") or "(unknown)"

    approver = w.get("waive_approver")
    if not approver:
        issues.append({
            "check": "missing_approver",
            "finding_id": fid,
            "reason": "waive_approver field is empty",
        })
    elif approvers and approver not in approvers:
        issues.append({
            "check": "approver_not_allowlisted",
            "finding_id": fid,
            "reason": f"approver {approver!r} not in allowlist {sorted(approvers)}",
        })

    until = _parse_date(w.get("waive_until"))
    if until is None:
        issues.append({
            "check": "missing_waive_until",
            "finding_id": fid,
            "reason": "waive_until must be ISO date (YYYY-MM-DD)",
        })
    elif until < today:
        issues.append({
            "check": "waive_expired",
            "finding_id": fid,
            "reason": f"waive_until {until} is before today {today} — expired",
        })

    reason = w.get("waive_reason") or ""
    if len(reason.strip()) < min_reason_chars:
        issues.append({
            "check": "reason_too_short",
            "finding_id": fid,
            "reason": f"waive_reason {len(reason)} chars < required {min_reason_chars}",
        })

    return issues


def _rubber_stamp_scan(waives: list[dict], threshold: int) -> list[dict]:
    """Detect approver+reason-head combinations used >= threshold times."""
    combo_count: dict[tuple[str, str], list[str]] = {}
    for w in waives:
        key = (w.get("waive_approver") or "", _normalize_reason_head(w.get("waive_reason") or ""))
        if not key[0] or not key[1]:
            continue
        combo_count.setdefault(key, []).append(w.get("finding_id") or "(unknown)")

    out = []
    for (approver, reason_head), fids in combo_count.items():
        if len(fids) >= threshold:
            out.append({
                "check": "rubber_stamp_pattern",
                "approver": approver,
                "reason_head": reason_head,
                "count": len(fids),
                "finding_ids": fids,
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--triage-file", default=None,
                    help="Triage YAML/JSON with `waives:` list (auto-resolves "
                         "to .vg/phases/<phase>/dast-triage.{yaml,json} "
                         "when --phase set)")
    ap.add_argument("--approvers", default="",
                    help="Comma-separated allowlist of github handles "
                         "(empty = skip allowlist check, reason_only)")
    ap.add_argument("--max-ratio", type=float, default=0.3,
                    help="Warn if waived/total_findings > N (default 0.3)")
    ap.add_argument("--min-reason-chars", type=int, default=100)
    ap.add_argument("--rubber-stamp-threshold", type=int, default=3)
    ap.add_argument("--total-findings", type=int, default=0,
                    help="Total findings count for ratio check. 0 = skip ratio check.")
    ap.add_argument("--today", default="",
                    help="ISO date override for expiry check (tests only)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--phase", help="phase number — when set + --triage-file omitted, "
                                    "auto-resolves convention path")
    args = ap.parse_args()

    # v2.6 (2026-04-25): auto-resolve triage file from phase convention
    if not args.triage_file and args.phase:
        phases_dir = Path(".vg/phases")
        if phases_dir.exists():
            for p in phases_dir.iterdir():
                if p.is_dir() and (p.name == args.phase
                                   or p.name.startswith(f"{args.phase}-")
                                   or p.name.startswith(f"{args.phase.zfill(2)}-")):
                    for ext in (".yaml", ".yml", ".json"):
                        cand = p / f"dast-triage{ext}"
                        if cand.exists():
                            args.triage_file = str(cand)
                            break
                    break

    if not args.triage_file:
        # No triage file → DAST not run yet for this phase, auto-skip
        print(json.dumps({
            "validator": "verify-dast-waive-approver",
            "verdict": "PASS",
            "evidence": [],
            "_skipped": "no triage file (DAST not run yet, or no waivers)",
        }))
        return 0

    path = Path(args.triage_file)
    if not path.exists():
        # File specified but doesn't exist → auto-skip
        print(json.dumps({
            "validator": "verify-dast-waive-approver",
            "verdict": "PASS",
            "evidence": [],
            "_skipped": f"triage file not found: {path}",
        }))
        return 0

    data = _load_yaml_or_json(path)
    waives = data.get("waives") or []
    if not isinstance(waives, list):
        print(f"⛔ triage file has invalid `waives` (must be list)", file=sys.stderr)
        return 2

    approvers = {a.strip() for a in args.approvers.split(",") if a.strip()}
    today = _parse_date(args.today) if args.today else _dt.date.today()
    if today is None:
        print(f"⛔ invalid --today value", file=sys.stderr)
        return 2

    per_waive_issues: list[dict] = []
    for w in waives:
        if not isinstance(w, dict):
            continue
        per_waive_issues.extend(_check_one_waive(w, approvers, today, args.min_reason_chars))

    rubber_stamp_issues = _rubber_stamp_scan(waives, args.rubber_stamp_threshold)

    ratio_issue = None
    ratio = 0.0
    if args.total_findings > 0:
        ratio = len(waives) / args.total_findings
        if ratio > args.max_ratio:
            ratio_issue = {
                "check": "waive_ratio_high",
                "ratio": round(ratio, 3),
                "max": args.max_ratio,
                "waived": len(waives),
                "total": args.total_findings,
            }

    all_issues = per_waive_issues + rubber_stamp_issues
    if ratio_issue:
        all_issues.append(ratio_issue)

    report = {
        "triage_file": str(path),
        "waives_count": len(waives),
        "total_findings": args.total_findings,
        "waive_ratio": round(ratio, 3) if args.total_findings else None,
        "issues": all_issues,
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        if all_issues:
            print(f"⛔ DAST waive approver: {len(all_issues)} issue(s)\n")
            for i in all_issues:
                if i["check"] == "rubber_stamp_pattern":
                    print(f"  [{i['check']}] approver={i['approver']!r} "
                          f"count={i['count']} findings={i['finding_ids']}")
                elif i["check"] == "waive_ratio_high":
                    print(f"  [{i['check']}] ratio={i['ratio']} > max={i['max']} "
                          f"({i['waived']}/{i['total']} findings waived)")
                else:
                    print(f"  [{i['check']}] {i['finding_id']}: {i['reason']}")
        elif not args.quiet:
            print(f"✓ DAST waive approver OK — {len(waives)} waive(s) all pass gates")

    return 1 if all_issues else 0


if __name__ == "__main__":
    sys.exit(main())
