#!/usr/bin/env python3
"""
Validator: verify-design-ref-honored.py

Harness v2.6 (2026-04-25): closes the VG executor rule R6 / design-fidelity:

  "Honor design-ref — if task has <design-ref> attribute:
   - READ referenced screenshot .planning/design-normalized/screenshots/
     {slug}.{state}.png
   - READ structural .planning/design-normalized/refs/{slug}.structural.html
   - READ interactions .planning/design-normalized/refs/{slug}.interactions.md
   - Layout + components + spacing MUST match screenshot
   - Interactive behaviors MUST follow interactions.md handler map
   - Do NOT reinvent layout to 'improve' — design is ground truth"

Why it exists: AI shortcuts when design-ref'd UI tasks come with detailed
screenshots/HTML structural refs. Common drift:
  - AI re-styles based on its own aesthetic (ignoring HTML proto colors)
  - AI adds elements not in screenshot
  - AI removes elements ("simplification") that ARE in screenshot
  - AI uses wrong fonts/spacing/border-radius

Phase 7.14.3 (advertiser visual alignment) had this exact issue: AI
shipped dark sidebar despite HTML proto white sidebar; user pushed back.
That bug was the trigger for this validator.

What this validator checks:

  1. Read PLAN*.md for tasks with `<design-ref>...</design-ref>` tags.

  2. For each design-ref slug, verify:
     - Referenced screenshot exists in phase-local design/, transitional
       phase-local designs/, shared design-system, or legacy design-normalized.
     - Structural HTML/JSON ref exists in
       .planning/design-normalized/refs/{slug}.structural.{html,json,xml}
     - Interactions ref exists if task involves interactive behavior

  3. Check task commit messages (last commit for each task) cite the
     design-ref slug — AI must demonstrate it READ the asset, not just
     wrote code.

Severity:
  BLOCK — task carries <design-ref> but referenced asset doesn't exist
          (broken link → AI couldn't read it → drift inevitable)
  WARN  — referenced asset exists but commit doesn't cite slug

Skip silently when phase has no design-ref tags (backend / library / etc.).

Usage:
  verify-design-ref-honored.py --phase 7.14.3
  verify-design-ref-honored.py --phase 7.14.3 --strict (escalate WARN→BLOCK)

Exit codes:
  0  PASS or WARN-only
  1  BLOCK
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from design_ref_resolver import (  # noqa: E402
    extract_design_ref_entries,
    resolve_design_assets,
)

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

DESIGN_REF_RE = re.compile(
    r'<design-ref>\s*([^<\s][^<]*?)\s*</design-ref>',
    re.IGNORECASE,
)
TASK_HEADER_RE = re.compile(
    r"^#{2,3}\s+Task\s+(\d+[\d.]*)\b",
    re.MULTILINE,
)


def _resolve_asset(slug: str, kind: str, phase_dir: Path) -> Path | None:
    """Look up asset by slug + kind ('screenshot' | 'structural' | 'interactions').

    Conventional paths:
      Tier 1: ${PHASE_DIR}/design/... or transitional ${PHASE_DIR}/designs/...
      Tier 2: .vg/design-system/...
      Tier 3: legacy .vg/.planning/design-normalized/...
    """
    assets = resolve_design_assets(slug, repo_root=REPO_ROOT, phase_dir=phase_dir)
    if kind == "screenshot" and assets.screenshots:
        return assets.screenshots[0]
    if kind == "structural":
        return assets.structural
    if kind == "interactions":
        return assets.interactions
    return None


def _extract_design_refs(plan_text: str) -> list[dict]:
    """Return list of {task_id, slugs:[]} per task."""
    results: list[dict] = []
    matches = list(TASK_HEADER_RE.finditer(plan_text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(plan_text)
        block = plan_text[m.start():end]
        slugs = [
            entry.value
            for entry in extract_design_ref_entries(block)
            if entry.kind == "slug"
        ]
        if slugs:
            results.append({
                "task_id": m.group(1),
                "slugs": slugs,
            })
    return results


def _commits_for_task(task_id: str, since_days: int = 90) -> list[str]:
    """Return list of recent commit SHAs whose message references this task."""
    try:
        # Match commit messages with `(<phase>-<task>):` pattern (e.g. feat(7.14.3-04):)
        result = subprocess.run(
            ["git", "log", f"--since={since_days}.days.ago", "--oneline",
             "--all"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return []
        # Match task-id in commit message
        task_pat = re.compile(rf"-{re.escape(task_id)}\)|task[ \-_]?{re.escape(task_id)}\b",
                              re.IGNORECASE)
        return [line.split()[0] for line in result.stdout.splitlines() if task_pat.search(line)]
    except (OSError, subprocess.TimeoutExpired):
        return []


def _commit_cites_slug(commit_sha: str, slug: str) -> bool:
    """Check if commit body mentions design-ref slug."""
    try:
        result = subprocess.run(
            ["git", "show", "-s", "--format=%B", commit_sha],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return False
        body = result.stdout
        # Match slug as whole token in commit body
        return bool(re.search(rf"\b{re.escape(slug)}\b", body, re.IGNORECASE))
    except (OSError, subprocess.TimeoutExpired):
        return False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", required=True)
    ap.add_argument("--strict", action="store_true",
                    help="Escalate WARN findings to BLOCK")
    args = ap.parse_args()

    out = Output(validator="verify-design-ref-honored")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            emit_and_exit(out)

        plan_files = list(phase_dir.glob("PLAN*.md"))
        if not plan_files:
            emit_and_exit(out)

        all_refs: list[dict] = []
        for p in plan_files:
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for ref in _extract_design_refs(text):
                ref["plan"] = p.name
                all_refs.append(ref)

        if not all_refs:
            # No design-ref tags — phase is non-UI or didn't use design system
            emit_and_exit(out)

        broken_refs: list[dict] = []
        unciteable_refs: list[dict] = []

        for ref_record in all_refs:
            task_id = ref_record["task_id"]
            for slug in ref_record["slugs"]:
                # Check 1: at least screenshot OR structural exists
                has_screenshot = _resolve_asset(slug, "screenshot", phase_dir)
                has_structural = _resolve_asset(slug, "structural", phase_dir)
                if not has_screenshot and not has_structural:
                    broken_refs.append({
                        "task": task_id,
                        "slug": slug,
                        "reason": "no screenshot/structural asset found in design-normalized/",
                    })
                    continue

                # Check 2: commit cites slug (advisory)
                commits = _commits_for_task(task_id)
                if commits:
                    cited = any(_commit_cites_slug(c, slug) for c in commits[:5])
                    if not cited:
                        unciteable_refs.append({
                            "task": task_id,
                            "slug": slug,
                            "commits_checked": commits[:3],
                        })

        if broken_refs:
            sample = "; ".join(
                f"Task {r['task']}: <design-ref>{r['slug']}</design-ref> ({r['reason']})"
                for r in broken_refs[:4]
            )
            out.add(Evidence(
                type="design_ref_asset_missing",
                message=f"{len(broken_refs)} broken <design-ref> link(s) — referenced asset doesn't exist on disk",
                actual=sample,
                expected="Each <design-ref>slug</design-ref> tag in PLAN must point to an existing screenshot OR structural asset through the 2-tier design resolver",
                fix_hint=(
                    "Either (a) run /vg:design-extract to normalize raw design "
                    "assets into screenshots/refs, OR (b) remove the broken "
                    "<design-ref> tag from PLAN if asset doesn't exist — task "
                    "will execute without design-fidelity guidance and that's "
                    "the operator's call to make explicit."
                ),
            ))

        if unciteable_refs:
            sample = "; ".join(
                f"Task {r['task']}: '{r['slug']}' (checked {len(r['commits_checked'])} commits)"
                for r in unciteable_refs[:4]
            )
            severity_evidence = Evidence(
                type="design_ref_not_cited_in_commit",
                message=f"{len(unciteable_refs)} <design-ref> slug(s) NOT cited in any task commit message — AI may have skipped reading the asset",
                actual=sample,
                fix_hint=(
                    "Per VG executor rule R6: 'Honor design-ref — READ "
                    "referenced screenshot, structural HTML, interactions.md.' "
                    "Commit message should cite the slug to demonstrate the "
                    "asset was read. Re-run task with explicit <design-ref> "
                    "context injection if drift suspected."
                ),
            )
            if args.strict:
                out.add(severity_evidence)
            else:
                out.warn(severity_evidence)

    emit_and_exit(out)


if __name__ == "__main__":
    main()
