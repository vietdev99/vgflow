#!/usr/bin/env python3
"""Per-step execution prober for procedural rules (Task 3.2 of meta-memory v1.1).

Reads a procedural rule's sequence[] and a deploy/test log. Returns JSON:
  - executed_step_ids: which steps actually ran (cmd substring match,
    preserving order via forward cursor)
  - total_steps: rule.sequence length
  - matched_signals_count: count of expected_signals matched within
    4096-byte window after each step's cmd location

Used by Task 3.3 to gate bootstrap.outcome_recorded events: procedural
rule outcome WITHOUT executed_step_ids ne sequence ids -> executor bypassed,
do NOT count toward shadow stats. Cargo-cult prevention per Codex #9 +
design Section 13.4.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml


SIGNAL_WINDOW_BYTES = 4096


def parse_rule(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("rule file missing YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("frontmatter not closed")
    front = yaml.safe_load(text[4:end]) or {}
    if not isinstance(front, dict):
        raise ValueError("frontmatter must be a YAML mapping")
    return front


def probe(rule: dict, log_text: str) -> dict:
    """Forward-cursor substring match. Preserves order: step N must appear
    AFTER step N-1 in the log to count as executed."""
    sequence = rule.get("sequence") or []
    executed: list[str] = []
    matched_signals = 0
    cursor = 0

    for step in sequence:
        if not isinstance(step, dict):
            continue
        sid = step.get("id")
        cmd = step.get("cmd", "")
        if not cmd:
            continue
        idx = log_text.find(cmd, cursor)
        if idx < 0:
            continue
        executed.append(sid)
        cursor = idx + len(cmd)
        # Match expected_signals only within SIGNAL_WINDOW_BYTES after cmd
        window = log_text[idx : idx + SIGNAL_WINDOW_BYTES]
        signals = step.get("expected_signals") or []
        for sig in signals:
            if isinstance(sig, str) and sig in window:
                matched_signals += 1

    return {
        "executed_step_ids": executed,
        "total_steps": len(sequence),
        "matched_signals_count": matched_signals,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Per-step execution prober")
    parser.add_argument("--rule", required=True, help="Rule .md path")
    parser.add_argument("--log", required=True, help="Deploy/test log path")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    args = parser.parse_args(argv[1:])

    try:
        rule = parse_rule(Path(args.rule))
    except (OSError, ValueError, yaml.YAMLError) as e:
        print(f"prober: rule parse error: {e}", file=sys.stderr)
        return 1

    try:
        log_text = Path(args.log).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"prober: log read error: {e}", file=sys.stderr)
        return 1

    result = probe(rule, log_text)

    if args.json:
        print(json.dumps(result))
    else:
        print(f"executed: {len(result['executed_step_ids'])}/{result['total_steps']}")
        print(f"matched_signals: {result['matched_signals_count']}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
