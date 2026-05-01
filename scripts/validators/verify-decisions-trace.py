#!/usr/bin/env python3
"""Verify CONTEXT.md D-XX decisions trace to user answer in DISCUSSION-LOG.md.

Closes Phase 3.2 dogfood gap: AI may paraphrase user answer incorrectly into
D-XX, producing decisions that drift from user intent. All downstream
artifacts (goals, code, tests) inherit the drift.

Mechanism: each D-XX in CONTEXT.md must have a `quote_source:` field citing
DISCUSSION-LOG.md round + user answer text, and the D-XX statement must be
≥80% similar to that user answer (Jaccard token overlap).

Severity: BLOCK at /vg:scope completion. Override --severity warn for
phases without enriched DISCUSSION-LOG (pre-2026-05-01).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402
from _traceability import text_similarity  # noqa: E402


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def parse_decisions(context_text: str) -> list[dict]:
    """Parse CONTEXT.md D-XX entries.

    Convention: each decision is a section starting with `## D-XX:` or
    `### D-XX:`, optionally followed by `**Decision:**` body and
    `**Quote source:**` reference.
    """
    decisions = []
    pattern = re.compile(
        r"^#{2,4}\s*(D-\d+)[:\s]\s*(.+?)$"
        r"(?P<body>(?:(?!^#{2,4}\s*D-\d+).)*)",
        re.MULTILINE | re.DOTALL,
    )
    for m in pattern.finditer(context_text):
        did = m.group(1)
        title = m.group(2).strip()
        body = m.group("body") or ""
        decisions.append(
            {
                "id": did,
                "title": title,
                "body": body.strip(),
                "quote_source": _extract_field(body, "Quote source")
                or _extract_field(body, "quote_source")
                or _extract_field(body, "Source")
                or _extract_field(body, "Trace"),
                "decision_text": _extract_field(body, "Decision")
                or _extract_field(body, "Choice")
                or body[:500],
            }
        )
    return decisions


def _extract_field(body: str, name: str) -> str:
    m = re.search(
        rf"^\*\*{re.escape(name)}:?\*\*\s*(.+?)(?=^\*\*|\n##|\Z)",
        body,
        re.MULTILINE | re.DOTALL,
    )
    if m:
        return m.group(1).strip()
    m = re.search(
        rf"^{re.escape(name)}:\s*(.+?)(?=^\w+:|\n##|\Z)",
        body,
        re.MULTILINE | re.DOTALL,
    )
    if m:
        return m.group(1).strip()
    return ""


def parse_discussion_rounds(log_text: str) -> dict[str, str]:
    """Parse DISCUSSION-LOG.md rounds. Returns {round_id: combined_text}.

    Convention: rounds start with `## Round N:` or `### Round N:`.
    """
    rounds: dict[str, str] = {}
    pattern = re.compile(
        r"^#{2,4}\s*Round\s+(\d+)[:\s].*?$"
        r"(?P<body>(?:(?!^#{2,4}\s*Round\s+\d+).)*)",
        re.MULTILINE | re.DOTALL,
    )
    for m in pattern.finditer(log_text):
        rounds[f"round-{m.group(1)}"] = (m.group("body") or "").strip()
    return rounds


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify D-XX trace to DISCUSSION-LOG user answers")
    parser.add_argument("--phase", required=True)
    parser.add_argument(
        "--severity",
        choices=["block", "warn"],
        default="block",
    )
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=0.4,
        help="Min Jaccard similarity D-XX text vs user answer (default 0.4)",
    )
    parser.add_argument(
        "--allow-decisions-untraced",
        action="store_true",
        help="Override: skip trace check. Logs OVERRIDE-DEBT.",
    )
    args = parser.parse_args()

    out = Output(validator="decisions-trace")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(type="phase_not_found", message=f"Phase not found: {args.phase}"))
            emit_and_exit(out)

        context_path = phase_dir / "CONTEXT.md"
        log_path = phase_dir / "DISCUSSION-LOG.md"
        if not context_path.exists():
            emit_and_exit(out)

        context_text = _read(context_path)
        log_text = _read(log_path) if log_path.exists() else ""
        decisions = parse_decisions(context_text)
        rounds = parse_discussion_rounds(log_text) if log_text else {}

        violations = 0
        for d in decisions:
            did = d["id"]
            issues: list[str] = []

            # Required: quote_source citation
            if not d["quote_source"]:
                # Migration: if log doesn't exist, can't enforce
                if not log_text:
                    continue  # Pre-discussion-log phase
                issues.append(
                    f"missing 'Quote source:' field — should cite DISCUSSION-LOG round/answer "
                    f"that drove this decision (e.g., 'DISCUSSION-LOG.md#round-3-user-answer')"
                )
            else:
                # Verify quote_source resolves to an actual round
                src_lower = d["quote_source"].lower()
                round_match = re.search(r"round[-\s]*(\d+)", src_lower)
                if round_match:
                    round_id = f"round-{round_match.group(1)}"
                    if round_id not in rounds:
                        issues.append(
                            f"quote_source references {round_id} but DISCUSSION-LOG has no such round"
                        )
                    else:
                        # Similarity check: D-XX decision_text vs round body
                        sim = text_similarity(d["decision_text"], rounds[round_id])
                        if sim < args.similarity_threshold:
                            issues.append(
                                f"decision text drift: similarity {sim:.2f} < threshold "
                                f"{args.similarity_threshold} vs cited round content. "
                                f"AI may have paraphrased user answer incorrectly."
                            )

            if issues:
                violations += 1
                for issue in issues:
                    out.add(
                        Evidence(
                            type="decision_trace_gap",
                            message=f"{did} '{d['title'][:60]}': {issue}",
                            file=str(context_path),
                            fix_hint=(
                                "Add **Quote source:** DISCUSSION-LOG.md#round-N to D-XX. "
                                "Verbatim quote user's answer text — don't paraphrase."
                            ),
                        ),
                        escalate=(args.severity == "block" and not args.allow_decisions_untraced),
                    )

        if violations and (args.severity == "warn" or args.allow_decisions_untraced):
            if out.verdict == "BLOCK":
                out.verdict = "WARN"
            out.add(
                Evidence(
                    type="severity_downgraded",
                    message=f"{violations} decision(s) untraced, downgraded to WARN (migration mode).",
                ),
                escalate=False,
            )

    emit_and_exit(out)


if __name__ == "__main__":
    main()
