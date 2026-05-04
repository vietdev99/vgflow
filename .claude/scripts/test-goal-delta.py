#!/usr/bin/env python3
"""Compare final TEST-GOALS.md with an independent Codex proposal."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


DECISION_RE = re.compile(r"\b(?:P\d+(?:\.\d+)*\.)?D-\d+\b")
GOAL_HEADER_RE = re.compile(r"^#{2,3}\s+(?:Goal\s+)?G-\d+.*$", re.MULTILINE)

ESSENTIAL_TERMS = {
    "authz": ("authz", "authorization", "permission", "object auth", "tenant"),
    "csrf": ("csrf",),
    "xss": ("xss", "escape", "sanitize"),
    "rate_limit": ("rate limit", "rate-limit", "throttle"),
    "idempotency": ("idempotency", "duplicate submit", "double submit"),
    "pagination": ("pagination", "page size", "page_size", "?page"),
    "filter": ("filter", "?status", "?type"),
    "sort": ("sort", "order by", "aria-sort"),
    "search": ("search", "debounce", "?q"),
    "empty_error_loading": ("empty state", "loading", "error state"),
    "persistence": ("persistence", "refresh", "re-read", "ghost save"),
    "audit": ("audit log", "audit"),
    "performance": ("p95", "performance", "latency"),
    "accessibility": (
        "accessibility",
        "aria",
        "keyboard navigation",
        "focus trap",
        "focus state",
        "focus order",
    ),
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _decisions(text: str) -> set[str]:
    return set(DECISION_RE.findall(text))


def _split_goal_blocks(text: str) -> list[str]:
    matches = list(GOAL_HEADER_RE.finditer(text))
    if not matches:
        return [text] if text.strip() else []
    blocks: list[str] = []
    for idx, match in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        blocks.append(text[match.start():end].strip())
    return blocks


def _blocks_by_decision(text: str) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    for block in _split_goal_blocks(text):
        for decision in _decisions(block):
            out.setdefault(decision, []).append(block)
    return {k: "\n\n".join(v) for k, v in out.items()}


def _terms_present(text: str) -> set[str]:
    lower = text.lower()
    present = set()
    for name, terms in ESSENTIAL_TERMS.items():
        if any(term in lower for term in terms):
            present.add(name)
    return present


def build_delta(phase_dir: Path, final_path: Path, proposal_path: Path) -> tuple[str, bool]:
    context = _read(phase_dir / "CONTEXT.md")
    final = _read(final_path)
    proposal = _read(proposal_path)

    final_by_decision = _blocks_by_decision(final)
    proposal_by_decision = _blocks_by_decision(proposal)
    context_decisions = _decisions(context)
    all_referenced = sorted(context_decisions | set(proposal_by_decision))

    unresolved: list[str] = []
    lines = [
        f"# Codex Test Goal Delta - {phase_dir.name}",
        "",
        f"Final goals: {final_path.name}",
        f"Codex proposal: {proposal_path.name}",
        "",
        "## Decision Coverage Delta",
        "",
        "| Decision | Final | Proposal | Missing Terms From Final |",
        "|---|---:|---:|---|",
    ]

    for decision in all_referenced:
        final_block = final_by_decision.get(decision, "")
        proposal_block = proposal_by_decision.get(decision, "")
        final_terms = _terms_present(final_block)
        proposal_terms = _terms_present(proposal_block)
        missing_terms = sorted(proposal_terms - final_terms)
        if decision in context_decisions and not final_block:
            unresolved.append(f"{decision}: final TEST-GOALS has no goal")
        for term in missing_terms:
            unresolved.append(f"{decision}: proposal covers {term}, final does not")
        lines.append(
            "| {decision} | {final} | {proposal} | {missing} |".format(
                decision=decision,
                final="yes" if final_block else "no",
                proposal="yes" if proposal_block else "no",
                missing=", ".join(missing_terms) if missing_terms else "-",
            )
        )

    lines.extend(["", "## Unresolved Items", ""])
    if unresolved:
        lines.extend(f"- {item}" for item in unresolved)
    else:
        lines.append("- none")
    lines.extend(["", f"Status: {'BLOCK' if unresolved else 'PASS'}", ""])
    return "\n".join(lines), bool(unresolved)


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--phase-dir", required=True)
    parser.add_argument("--final", default="TEST-GOALS.md")
    parser.add_argument("--proposal", default="TEST-GOALS.codex-proposal.md")
    parser.add_argument("--out", default="TEST-GOALS.codex-delta.md")
    parser.add_argument("--write-only", action="store_true")
    args = parser.parse_args()

    phase_dir = Path(args.phase_dir)
    final_path = Path(args.final)
    proposal_path = Path(args.proposal)
    out_path = Path(args.out)
    if not final_path.is_absolute():
        final_path = phase_dir / final_path
    if not proposal_path.is_absolute():
        proposal_path = phase_dir / proposal_path
    if not out_path.is_absolute():
        out_path = phase_dir / out_path

    missing = [str(p) for p in (final_path, proposal_path) if not p.exists()]
    if missing:
        print(f"Missing required input(s): {', '.join(missing)}", file=sys.stderr)
        return 2

    delta, has_unresolved = build_delta(phase_dir, final_path, proposal_path)
    out_path.write_text(delta, encoding="utf-8")
    print(f"wrote {out_path}")
    if has_unresolved and not args.write_only:
        print("Codex test-goal delta has unresolved items; reconcile TEST-GOALS.md.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
