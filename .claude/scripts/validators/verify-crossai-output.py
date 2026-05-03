#!/usr/bin/env python3
"""
Validator: verify-crossai-output.py — Phase 16 D-05

Runs after `/vg:scope --crossai` or `/vg:blueprint --crossai` applies
cross-AI enrichment changes. Asserts the cross-AI peer (Codex / Gemini)
followed the structured-edits contract documented in
commands/vg/_shared/crossai-invoke.md "Output contract for PLAN/CONTEXT
enrichment (Phase 16 D-05)".

Logic:
  1. `git diff <base> -- PLAN.md CONTEXT.md` → captures enrichment delta
  2. Per task in PLAN diff: count added body lines (`+` lines inside
     `<task>` body, excluding frontmatter changes)
  3. If task body grew > 30 prose lines AND no corresponding
     `<context-refs>` ID was added → BLOCK (the prose should have
     become a CONTEXT decision instead)
  4. If `cross_ai_enriched: true` flag missing from CONTEXT.md
     frontmatter when ANY change made → WARN (downstream R4 budget
     caps won't bump → silent truncation risk)

Usage:  verify-crossai-output.py --phase 7.14.3
        verify-crossai-output.py --phase 7.14.3 --diff-base HEAD~2
Output: vg.validator-output JSON on stdout
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

PROSE_GROWTH_THRESHOLD = 30


def _git_diff_added_lines(base: str, path: Path, repo_root: Path) -> str:
    """Return concatenated `+` lines from `git diff <base> -- <path>`.
    Empty string if path missing from diff or git unavailable."""
    if not path.exists():
        return ""
    try:
        proc = subprocess.run(
            ["git", "diff", "--no-color", base, "--", str(path)],
            cwd=str(repo_root),
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0:
            return ""
        return proc.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def _classify_diff_lines_per_task(plan_diff: str) -> dict[str, dict]:
    """Walk a PLAN.md unified diff, classify added lines per task block,
    and count prose-growth + context-refs additions.

    Returns dict: { task_id: {prose_added, context_refs_added, in_frontmatter} }

    Tracks task scope from BOTH formats (Phase 16 hot-fix v2.11.1, BLOCKer 6
    cross-AI consensus — Codex GPT-5.5 verified that 50-line prose addition
    to a heading-format PLAN returned silent PASS):
      - XML: `<task id="N">` opens, `</task>` closes
      - Heading: `## Task N:` (or `### Task N:`) opens; next `## Task M:` /
        `## Wave M:` / non-task H2 closes implicitly
    """
    state: dict[str, dict] = {}
    current_task: str | None = None
    in_frontmatter = False

    task_open_re = re.compile(r'<task\s+id\s*=\s*["\']?(\d+|[A-Za-z][A-Za-z0-9_-]*)["\']?')
    task_close_re = re.compile(r'</task>')
    fm_re = re.compile(r'^---\s*$')
    ctx_ref_re = re.compile(r'<context-refs>')
    # Heading-format task opener — mirrors extract_all_tasks() in
    # pre-executor-check.py so the diff parser and the canonical extractor
    # agree on what a "task" is.
    heading_task_re = re.compile(r'^#{2,3}\s+Task\s+(0?\d+)\b', re.IGNORECASE)
    # Implicit close: next "## Task N:" or "## Wave N:" heading. Matched
    # alongside heading_task_re so we can switch from one heading task to the
    # next without leaving counts dangling.
    heading_close_re = re.compile(r'^#{2,3}\s+(?:Wave\s+\d+)\b', re.IGNORECASE)

    for raw in plan_diff.splitlines():
        if raw.startswith("@@"):
            current_task = None
            in_frontmatter = False
            continue
        if not raw or raw[0] not in ("+", "-", " "):
            continue
        line = raw[1:]  # drop diff marker
        stripped = line.strip()

        # Track task block scope (any context line — added/removed/unchanged)
        m = task_open_re.search(line)
        hm = heading_task_re.match(stripped)
        if m:
            current_task = m.group(1)
            state.setdefault(current_task, {
                "prose_added": 0,
                "context_refs_added": 0,
                "in_frontmatter": False,
            })
            in_frontmatter = False
        elif hm:
            current_task = hm.group(1).lstrip("0") or "0"
            state.setdefault(current_task, {
                "prose_added": 0,
                "context_refs_added": 0,
                "in_frontmatter": False,
            })
            in_frontmatter = False
        elif task_close_re.search(line) or heading_close_re.match(stripped):
            current_task = None
            in_frontmatter = False
        elif fm_re.match(stripped) and current_task:
            in_frontmatter = not in_frontmatter

        # Only count ADDED lines inside a task block
        if raw.startswith("+") and current_task and not raw.startswith("+++"):
            entry = state[current_task]
            if in_frontmatter:
                # Frontmatter additions: count context_refs separately,
                # everything else doesn't contribute to prose growth.
                if ctx_ref_re.search(line):
                    entry["context_refs_added"] += 1
                continue
            # Body line — count as prose growth UNLESS it's a context-refs tag
            if ctx_ref_re.search(line):
                entry["context_refs_added"] += 1
            elif line.strip():  # ignore blank-line additions
                entry["prose_added"] += 1
    return state


def _enriched_flag_in_diff(ctx_diff: str) -> bool:
    """Return True if `cross_ai_enriched: true` appears as ADDED line in CONTEXT diff."""
    for raw in ctx_diff.splitlines():
        if not raw.startswith("+") or raw.startswith("+++"):
            continue
        if re.search(r"^\+\s*cross_ai_enriched\s*:\s*(true|True)\b", raw):
            return True
    return False


def _ctx_has_changes(ctx_diff: str) -> bool:
    return any(
        raw.startswith("+") and not raw.startswith("+++")
        and raw[1:].strip()
        for raw in ctx_diff.splitlines()
    )


def main() -> None:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--phase", required=True)
    ap.add_argument("--diff-base", default="HEAD~1",
                    help="Git ref for the pre-enrichment baseline. Default HEAD~1.")
    ap.add_argument("--strict", action="store_true",
                    help="Escalate WARN to BLOCK")
    args = ap.parse_args()

    out = Output(validator="crossai-output")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            out.warn(Evidence(type="info",
                              message=f"Phase dir not found for {args.phase} — skipping"))
            emit_and_exit(out)

        # Find repo root: look for .git from VG_REPO_ROOT or cwd
        import os
        repo_root = Path(os.environ.get("VG_REPO_ROOT") or Path.cwd()).resolve()
        if not (repo_root / ".git").exists():
            # Walk up looking for .git
            cur = repo_root
            for _ in range(6):
                if (cur / ".git").exists():
                    repo_root = cur
                    break
                cur = cur.parent
        if not (repo_root / ".git").exists():
            out.warn(Evidence(type="info",
                              message=f"No .git at {repo_root} — cannot diff; skipping"))
            emit_and_exit(out)

        plan_files = sorted(phase_dir.glob("PLAN*.md"))
        ctx_path = phase_dir / "CONTEXT.md"

        # CONTEXT diff for enriched flag detection
        ctx_diff = _git_diff_added_lines(args.diff_base, ctx_path, repo_root)
        ctx_changed = _ctx_has_changes(ctx_diff)
        enriched_flag_set = _enriched_flag_in_diff(ctx_diff) if ctx_changed else True

        # PLAN diff per file
        any_plan_changed = False
        for pf in plan_files:
            plan_diff = _git_diff_added_lines(args.diff_base, pf, repo_root)
            if not plan_diff.strip():
                continue
            any_plan_changed = True
            per_task = _classify_diff_lines_per_task(plan_diff)
            for tid, counts in per_task.items():
                if counts["prose_added"] > PROSE_GROWTH_THRESHOLD \
                   and counts["context_refs_added"] == 0:
                    out.add(Evidence(
                        type="schema_violation",
                        message=(
                            f"Task {tid} body grew {counts['prose_added']} prose "
                            f"lines (> {PROSE_GROWTH_THRESHOLD}) without adding any "
                            f"<context-refs> ID. Phase 16 D-05 contract: long prose "
                            f"belongs in CONTEXT decision body, referenced via "
                            f"<context-refs>P{{phase}}.D-XX</context-refs>."
                        ),
                        file=str(pf),
                        actual={
                            "prose_added": counts["prose_added"],
                            "context_refs_added": counts["context_refs_added"],
                        },
                        expected=(
                            "≤ 30 added prose lines OR ≥1 context-refs ID added"
                        ),
                        fix_hint=(
                            "(1) Move the long prose into CONTEXT.md as a new "
                            "decision block (### P{phase}.D-N: <title>); "
                            "(2) Reference from the task: "
                            "<context-refs>P{phase}.D-N</context-refs>; "
                            "(3) Set CONTEXT.md frontmatter cross_ai_enriched: true."
                        ),
                    ))

        # WARN if changes were made without flagging cross_ai_enriched
        if (any_plan_changed or ctx_changed) and not enriched_flag_set:
            out.warn(Evidence(
                type="schema_violation",
                message=(
                    "Cross-AI enrichment detected (PLAN/CONTEXT changed since "
                    f"{args.diff_base}) but CONTEXT.md frontmatter does not "
                    "set `cross_ai_enriched: true`. Downstream R4 budget caps "
                    "(Phase 16 D-04) won't bump, risking silent truncation."
                ),
                file=str(ctx_path),
                fix_hint=(
                    "Add to CONTEXT.md frontmatter:\n"
                    "  ---\n"
                    "  cross_ai_enriched: true\n"
                    "  enriched_at: \"YYYY-MM-DD\"\n"
                    "  ---"
                ),
            ))

        if args.strict:
            # Promote any WARN to BLOCK
            for ev in out.evidence:
                if getattr(ev, "type", "") == "schema_violation":
                    out.verdict = "BLOCK"

        if not out.evidence:
            out.evidence.append(Evidence(
                type="info",
                message=(
                    f"Cross-AI output PASS — diff base {args.diff_base}, "
                    f"plans changed: {any_plan_changed}, ctx changed: {ctx_changed}, "
                    f"enriched flag set: {enriched_flag_set}"
                ),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
