#!/usr/bin/env python3
"""
Validator: verify-context-refs.py

Phase C v2.5 (2026-04-23): executor context isolation check.

When context_injection.mode = "scoped", every task in PLAN*.md MUST carry
a `<context-refs>` element listing the decision IDs (P{phase}.D-XX) that
task needs. Missing refs mean the executor gets no CONTEXT.md extract and
may hallucinate decisions.

Severity matrix:
- scoped mode + task missing <context-refs> entirely → WARN (not BLOCK;
  build.md fallback injects full CONTEXT when refs absent)
- scoped mode + <context-refs> contains IDs not present in CONTEXT.md
  (typos / stale refs) → WARN
- full mode → PASS immediately (no enforcement needed)

Usage:
  verify-context-refs.py --phase <N>

Exit codes:
  0  PASS or WARN
  1  BLOCK (unused — all findings advisory in Phase C)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402
from _i18n import t  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

CONTEXT_REFS_RE = re.compile(r"<context-refs>(.*?)</context-refs>", re.DOTALL)
TASK_HEADER_RE  = re.compile(r"^#{2,3}\s+Task\s+(\d+[\d.]*)", re.MULTILINE)
DECISION_ID_RE  = re.compile(r"\bP[\d.]+\.D-\d+\b|\bD-\d+\b|\bF-\d+\b")


def _read_config() -> dict:
    cfg_path = REPO_ROOT / ".claude" / "vg.config.md"
    defaults = {"mode": "full", "scoped_fallback_on_missing": True, "phase_cutover": 14}
    if not cfg_path.exists():
        return defaults

    text = cfg_path.read_text(encoding="utf-8", errors="replace")

    m = re.search(r"^\s*mode:\s*['\"]?(full|scoped)['\"]?", text, re.MULTILINE)
    if m:
        defaults["mode"] = m.group(1)

    m = re.search(r"^\s*phase_cutover:\s*(\d+)", text, re.MULTILINE)
    if m:
        defaults["phase_cutover"] = int(m.group(1))

    m = re.search(r"^\s*scoped_fallback_on_missing:\s*(true|false)", text, re.MULTILINE | re.IGNORECASE)
    if m:
        defaults["scoped_fallback_on_missing"] = m.group(1).lower() == "true"

    return defaults


def _extract_task_refs(plan_text: str) -> list[dict]:
    """Return list of {task_id, refs: list[str], has_refs_element: bool}."""
    results: list[dict] = []

    # Split by task headers
    task_positions = [(m.start(), m.group(1)) for m in TASK_HEADER_RE.finditer(plan_text)]
    for i, (start, task_id) in enumerate(task_positions):
        end = task_positions[i + 1][0] if i + 1 < len(task_positions) else len(plan_text)
        block = plan_text[start:end]

        refs_match = CONTEXT_REFS_RE.search(block)
        if refs_match:
            raw = refs_match.group(1).strip()
            refs = [r.strip() for r in re.split(r"[,\s]+", raw) if r.strip()]
            results.append({"task_id": task_id, "refs": refs, "has_refs_element": True})
        else:
            results.append({"task_id": task_id, "refs": [], "has_refs_element": False})

    return results


def _context_decision_ids(context_text: str) -> set[str]:
    """Extract all decision IDs declared in CONTEXT.md."""
    return set(DECISION_ID_RE.findall(context_text))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    args = ap.parse_args()

    out = Output(validator="verify-context-refs")
    with timer(out):
        cfg = _read_config()
        mode = cfg["mode"]

        # Full mode: pass immediately (no enforcement)
        if mode == "full":
            emit_and_exit(out)

        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            emit_and_exit(out)

        # Find PLAN*.md files
        plan_files = list(phase_dir.glob("PLAN*.md"))
        if not plan_files:
            emit_and_exit(out)

        # Read CONTEXT.md decision IDs (for stale-ref check)
        context_path = phase_dir / "CONTEXT.md"
        known_ids: set[str] = set()
        if context_path.exists():
            known_ids = _context_decision_ids(
                context_path.read_text(encoding="utf-8", errors="replace")
            )

        missing_refs: list[dict] = []
        stale_refs: list[dict] = []

        for plan_file in sorted(plan_files):
            plan_text = plan_file.read_text(encoding="utf-8", errors="replace")
            tasks = _extract_task_refs(plan_text)

            for task in tasks:
                if not task["has_refs_element"]:
                    missing_refs.append({
                        "plan": plan_file.name,
                        "task": task["task_id"],
                    })
                elif known_ids and task["refs"]:
                    bad = [r for r in task["refs"] if r and r not in known_ids]
                    if bad:
                        stale_refs.append({
                            "plan": plan_file.name,
                            "task": task["task_id"],
                            "bad_refs": bad,
                        })

        if missing_refs:
            sample = "; ".join(
                f"{r['plan']} Task {r['task']}"
                for r in missing_refs[:6]
            )
            out.warn(Evidence(
                type="context_refs_missing",
                message=t(
                    "context_refs.missing.message",
                    count=len(missing_refs),
                ),
                actual=sample,
                fix_hint=t("context_refs.missing.fix_hint"),
            ))

        if stale_refs:
            sample = "; ".join(
                f"{r['plan']} Task {r['task']}: {r['bad_refs']}"
                for r in stale_refs[:4]
            )
            out.warn(Evidence(
                type="context_refs_stale",
                message=t(
                    "context_refs.stale.message",
                    count=len(stale_refs),
                ),
                actual=sample,
                fix_hint=t("context_refs.stale.fix_hint"),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
