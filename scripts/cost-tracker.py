#!/usr/bin/env python3
"""
Phase G v2.5 (2026-04-23) — per-phase + milestone token cost tracker.

Aggregates token_usage events from .vg/events.db + .vg/telemetry.jsonl,
compares against budget thresholds in vg.config.md, warns/blocks.

Config:
  cost:
    phase_budget_tokens: 500000        # warn
    milestone_budget_tokens: 5000000   # block (fail accept if over)
    warn_threshold_pct: 80             # warn at 80% of budget

Events read:
  - event_type='agent_invocation' with payload.token_usage.{prompt, completion}
  - event_type='cost.token_usage' with payload.tokens

Usage:
  cost-tracker.py --phase 7.14
  cost-tracker.py --milestone M1
  cost-tracker.py --phase 7.14 --json

Exit codes:
  0 PASS (under budget)
  1 WARN (>= warn_threshold)
  2 BLOCK (over hard budget)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

DEFAULTS = {
    "phase_budget_tokens": 500_000,
    "milestone_budget_tokens": 5_000_000,
    "warn_threshold_pct": 80,
}


def _read_config() -> dict:
    cfg = REPO_ROOT / ".claude" / "vg.config.md"
    out = dict(DEFAULTS)
    if not cfg.exists():
        return out
    text = cfg.read_text(encoding="utf-8", errors="replace")
    in_cost = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("cost:"):
            in_cost = True
            continue
        if in_cost:
            if line and not line[0].isspace() and ":" in stripped and not stripped.startswith("#"):
                break
            if stripped.startswith("#") or not stripped:
                continue
            m = re.match(r"^\s*(\w+):\s*(\S+)", line)
            if m:
                k, v = m.group(1), m.group(2).split("#")[0].strip()
                try:
                    out[k] = int(v)
                except ValueError:
                    pass
    return out


def _extract_tokens_from_event(payload_str: str | None) -> int:
    """Return total tokens (prompt + completion) from event payload."""
    if not payload_str:
        return 0
    try:
        p = json.loads(payload_str)
    except Exception:
        return 0
    if not isinstance(p, dict):
        return 0
    # Schema 1: payload.token_usage.{prompt,completion}
    tu = p.get("token_usage") or {}
    if isinstance(tu, dict):
        t = int(tu.get("prompt", 0) or 0) + int(tu.get("completion", 0) or 0)
        if t > 0:
            return t
    # Schema 2: payload.tokens (int) or payload.total_tokens
    for key in ("total_tokens", "tokens"):
        v = p.get(key)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def _query_db(phase: str | None, milestone_phases: list[str] | None) -> int:
    """Return total tokens for phase (or any phase in milestone list)."""
    db = REPO_ROOT / ".vg" / "events.db"
    if not db.exists():
        return 0
    total = 0
    try:
        conn = sqlite3.connect(str(db))
        cur = conn.cursor()
        cur.execute(
            "SELECT payload FROM events "
            "WHERE event_type IN ('agent_invocation', 'cost.token_usage')"
        )
        for (payload_str,) in cur.fetchall():
            if not payload_str:
                continue
            try:
                p = json.loads(payload_str)
            except Exception:
                continue
            ep = str(p.get("phase") or p.get("phase_id") or "")
            if phase and ep == phase:
                total += _extract_tokens_from_event(payload_str)
            elif milestone_phases and ep in milestone_phases:
                total += _extract_tokens_from_event(payload_str)
        conn.close()
    except Exception:
        pass
    return total


def _query_jsonl(phase: str | None, milestone_phases: list[str] | None) -> int:
    """Fallback/complement: scan telemetry.jsonl directly."""
    jsonl = REPO_ROOT / ".vg" / "telemetry.jsonl"
    if not jsonl.exists():
        return 0
    total = 0
    try:
        for line in jsonl.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            etype = ev.get("event_type") or ev.get("type")
            if etype not in ("agent_invocation", "cost.token_usage"):
                continue
            ep = str(ev.get("phase") or ev.get("phase_id") or
                     (ev.get("payload") or {}).get("phase", ""))
            if phase and ep == phase:
                total += _extract_tokens_from_event(json.dumps(ev.get("payload") or ev))
            elif milestone_phases and ep in milestone_phases:
                total += _extract_tokens_from_event(json.dumps(ev.get("payload") or ev))
    except Exception:
        pass
    return total


def _find_milestone_phases(milestone_id: str) -> list[str]:
    roadmap = REPO_ROOT / ".vg" / "ROADMAP.md"
    if not roadmap.exists():
        return []
    text = roadmap.read_text(encoding="utf-8", errors="replace")
    in_milestone = False
    phases: set[str] = set()
    for line in text.splitlines():
        if re.match(rf"^#{{1,3}}\s*Milestone\s*{re.escape(milestone_id)}\b", line, re.IGNORECASE):
            in_milestone = True
            continue
        if in_milestone and re.match(r"^#{1,3}\s*Milestone\s", line, re.IGNORECASE):
            break
        if in_milestone:
            m = re.search(r"\b(\d+(?:\.\d+)*)\b", line)
            if m:
                phases.add(m.group(1))
    return sorted(phases)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", help="phase number (e.g. 7.14)")
    ap.add_argument("--milestone", help="milestone ID (e.g. M1)")
    ap.add_argument("--json", action="store_true", help="emit JSON report")
    args = ap.parse_args()

    if not args.phase and not args.milestone:
        print("\033[38;5;208m--phase or --milestone required\033[0m", file=sys.stderr)
        return 1

    cfg = _read_config()

    if args.phase:
        tokens = _query_db(args.phase, None) + _query_jsonl(args.phase, None)
        budget = cfg["phase_budget_tokens"]
        scope = f"phase {args.phase}"
    else:
        phases = _find_milestone_phases(args.milestone)
        tokens = _query_db(None, phases) + _query_jsonl(None, phases)
        budget = cfg["milestone_budget_tokens"]
        scope = f"milestone {args.milestone} ({len(phases)} phases)"

    pct = (tokens / budget * 100) if budget > 0 else 0
    warn_thresh = cfg["warn_threshold_pct"]

    verdict = "PASS"
    if tokens > budget:
        verdict = "BLOCK"
    elif pct >= warn_thresh:
        verdict = "WARN"

    result = {
        "scope": scope,
        "tokens": tokens,
        "budget": budget,
        "usage_pct": round(pct, 1),
        "verdict": verdict,
        "warn_threshold_pct": warn_thresh,
    }

    if args.json:
        print(json.dumps(result))
    else:
        emoji = {"PASS": "✓", "WARN": "", "BLOCK": ""}[verdict]
        print(f"{emoji} Token cost: {tokens:,} / {budget:,} ({pct:.1f}%) — {scope}")
        if verdict == "BLOCK":
            print(f"  Over hard budget. Investigate: /vg:telemetry --command agent_invocation")
        elif verdict == "WARN":
            print(f"  Approaching budget ({warn_thresh}%). Consider: skip-telemetry suggestions, expensive-reorder.")

    return {"PASS": 0, "WARN": 1, "BLOCK": 2}[verdict]


if __name__ == "__main__":
    sys.exit(main())
