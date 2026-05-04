#!/usr/bin/env python3
"""
verify-learn-promotion.py — Phase P of v2.5.2 hardening.

Problem closed:
  v2.5.1 bootstrap auto-surface promotes Tier-A candidates after N
  confirms without reject. Promoted rules are supposed to be injected
  into next phase executor prompts. But v2.5.1 "verification" was that
  CANDIDATES.md → LEARN-RULES.md transition happened (config write) —
  not that the promoted rule text actually reached a running executor.

This validator is BEHAVIORAL:
  1. Read .vg/bootstrap/CANDIDATES.md — find promotions with timestamp
     in lookback window (default 7 days)
  2. For each promotion, find the first run AFTER promotion timestamp
  3. Read captured prompts from that run
  4. Assert promoted rule text appears in >=1 prompt of that run
     (sanity: promotion should propagate to first post-promotion run)

Exit codes:
  0 = all recent promotions propagated
  1 = at least one promoted rule did not appear in any subsequent-run prompt
  2 = config error

Usage:
  verify-learn-promotion.py --lookback-days 7
  verify-learn-promotion.py --candidates-file .vg/bootstrap/CANDIDATES.md
  verify-learn-promotion.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def _parse_iso(s: str) -> datetime | None:
    if not s or not isinstance(s, str):
        return None
    try:
        # Accept "YYYY-MM-DDTHH:MM:SS" with optional tz
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def _parse_promotions(candidates_file: Path, lookback_days: int) -> list[dict]:
    """
    Parse CANDIDATES.md for Tier-A promotion records.

    Expected per entry:
        ## L-042 — rule title
        **Tier:** A
        **Promoted:** 2026-04-20T14:00:00Z
        **Rule:** text body
    """
    if not candidates_file.exists():
        return []

    text = candidates_file.read_text(encoding="utf-8", errors="replace")
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    promotions: list[dict] = []

    blocks = re.split(r"\n(?=##\s+L-\d+)", text)
    for block in blocks:
        m = re.match(r"##\s+(L-\d+)\s*[—\-–]\s*(.+?)(?:\n|$)", block)
        if not m:
            continue
        rule_id = m.group(1)
        title = m.group(2).strip()

        promoted_m = re.search(r"\*\*Promoted:\*\*\s*(\S+)", block)
        if not promoted_m:
            continue
        promoted_ts = _parse_iso(promoted_m.group(1))
        if promoted_ts is None or promoted_ts < cutoff:
            continue

        rule_m = re.search(
            r"\*\*Rule:\*\*\s*(.+?)(?:\n\*\*|\n##|\Z)",
            block, re.DOTALL | re.IGNORECASE,
        )

        promotions.append({
            "id": rule_id,
            "title": title,
            "promoted_at": promoted_ts.isoformat(),
            "rule_text": (rule_m.group(1) if rule_m else "").strip(),
        })

    return promotions


def _list_runs_after(ts: datetime) -> list[dict]:
    """Return run directories with creation time > ts, sorted oldest first."""
    runs_dir = REPO_ROOT / ".vg" / "runs"
    if not runs_dir.exists():
        return []

    out = []
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        prompt_dir = run_dir / "executor-prompts"
        if not prompt_dir.exists():
            continue
        try:
            mtime_s = prompt_dir.stat().st_mtime
            mtime = datetime.fromtimestamp(mtime_s, tz=timezone.utc)
            if mtime >= ts:
                out.append({
                    "run_id": run_dir.name,
                    "mtime": mtime.isoformat(),
                })
        except OSError:
            continue

    out.sort(key=lambda r: r["mtime"])
    return out


def _rule_in_run(rule_text: str, run_id: str) -> bool:
    """Walk captured prompts in run; return True if rule anchor found in any."""
    prompt_dir = REPO_ROOT / ".vg" / "runs" / run_id / "executor-prompts"
    if not prompt_dir.exists():
        return False

    manifest_path = prompt_dir / "manifest.json"
    if not manifest_path.exists():
        return False

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False

    anchor = re.sub(r"\s+", " ", rule_text).strip().lower()[:60]
    if len(anchor) < 20:
        return False

    for entry in manifest.get("entries", []):
        file_path = prompt_dir / entry.get("file", "")
        if not file_path.exists():
            continue
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
            if anchor in re.sub(r"\s+", " ", text).lower():
                return True
        except OSError:
            continue

    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lookback-days", type=int, default=7)
    ap.add_argument("--candidates-file",
                    default=".vg/bootstrap/CANDIDATES.md")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--phase", help="(orchestrator-injected; ignored by this validator)")
    args = ap.parse_args()

    candidates_path = REPO_ROOT / args.candidates_file
    promotions = _parse_promotions(candidates_path, args.lookback_days)

    if not promotions:
        msg = f"No Tier-A promotions in last {args.lookback_days} days — nothing to verify"
        if args.json:
            print(json.dumps({
                "lookback_days": args.lookback_days,
                "promotions_checked": 0,
                "failures": [],
            }))
        elif not args.quiet:
            print(f"✓ {msg}")
        return 0

    failures = []
    per_rule = []

    for promo in promotions:
        promoted_ts = _parse_iso(promo["promoted_at"])
        runs_after = _list_runs_after(promoted_ts)

        if not runs_after:
            record = {
                "rule_id": promo["id"],
                "reason": "no runs observed after promotion timestamp yet — cannot verify",
                "severity": "warn",
            }
            per_rule.append({**promo, **record})
            continue

        # Check first run after promotion (most stringent: immediate carry-over)
        first_run = runs_after[0]
        found = _rule_in_run(promo["rule_text"], first_run["run_id"])

        record = {
            "rule_id": promo["id"],
            "title": promo["title"],
            "promoted_at": promo["promoted_at"],
            "first_run_after": first_run["run_id"],
            "first_run_mtime": first_run["mtime"],
            "propagated": found,
        }
        per_rule.append(record)
        if not found:
            failures.append(record)

    result = {
        "lookback_days": args.lookback_days,
        "promotions_checked": len(promotions),
        "per_rule": per_rule,
        "failures": failures,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if failures:
            print(f"\033[38;5;208mLearn promotion: {len(failures)}/{len(promotions)} \033[0m"
                  "promoted rule(s) did NOT appear in first subsequent run's prompts\n")
            for f in failures:
                print(f"  [{f['rule_id']}] {f['title']}")
                print(f"    promoted={f['promoted_at']} first_run={f['first_run_after']}")
        elif not args.quiet:
            print(f"✓ Learn promotion OK — {len(promotions)} promotion(s) propagated")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
