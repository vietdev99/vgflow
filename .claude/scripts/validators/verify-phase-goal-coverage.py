#!/usr/bin/env python3
"""verify-phase-goal-coverage — Phase-level TEST-GOAL coverage gate (R8-C).

Codex closed-loop audit (2026-05-05) found phase-level TEST-GOAL MISSING.
Component goals (G-XX) verify per-feature behavior but no goal asserts the
WHOLE phase delivers user-visible value end-to-end. This validator
enforces the closed-loop contract:

  1. Every CONTEXT.md `## Goals` `### In-scope` bullet MUST be covered by
     at least one G-PHASE-NN.
  2. Every component G-XX goal MUST appear in at least one G-PHASE-NN
     `children[]` list (unless explicitly flagged
     `phase_goal_orphan_reason: "<reason>"`).
  3. Every G-PHASE-NN `children[]` entry MUST reference an existing
     component goal file.
  4. Every G-PHASE-NN MUST have non-empty `postcondition` and
     `goal_class: phase-happy-path`.

Invocation:
  verify-phase-goal-coverage.py --phase <N>

Override flag (logged as override-debt by orchestrator):
  --allow-phase-goal-incomplete
  --override-reason "<text>"

Exit:
  0 — PASS or WARN
  1 — BLOCK
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

VALIDATOR_NAME = "verify-phase-goal-coverage"

PHASE_GOAL_RE = re.compile(r"^G-PHASE-\d+$")
COMPONENT_GOAL_RE = re.compile(r"^G-\d+$")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""


def _extract_frontmatter(text: str) -> dict:
    """Best-effort YAML frontmatter parse — returns dict of scalar/list/multiline.

    Avoids PyYAML hard dep — uses simple line-based parse covering the
    fields this validator needs: id, goal_class, children, postcondition,
    rcrurdr_required, phase_goal_orphan_reason.
    """
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    body = text[3:end].lstrip("\n")
    out: dict = {}
    current_multiline_key: str | None = None
    multiline_buf: list[str] = []
    multiline_indent: int | None = None
    list_key: str | None = None

    for line in body.splitlines():
        # Multiline literal (`key: |`) collection
        if current_multiline_key is not None:
            stripped = line.lstrip()
            if not line.strip():
                multiline_buf.append("")
                continue
            indent = len(line) - len(stripped)
            if multiline_indent is None and stripped:
                multiline_indent = indent
            if multiline_indent is not None and indent >= multiline_indent and stripped:
                multiline_buf.append(line[multiline_indent:])
                continue
            # End of multiline — store and reset
            out[current_multiline_key] = "\n".join(multiline_buf).strip()
            current_multiline_key = None
            multiline_buf = []
            multiline_indent = None
            # Fall through to parse this line normally

        # List continuation
        if list_key is not None:
            m = re.match(r"^\s+-\s*(.+)$", line)
            if m:
                out.setdefault(list_key, []).append(m.group(1).strip())
                continue
            else:
                list_key = None

        # New top-level key
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val == "|" or val == ">":
            current_multiline_key = key
            multiline_buf = []
            multiline_indent = None
            continue
        if val == "":
            list_key = key
            continue
        # Inline list `[a, b, c]`
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            if not inner:
                out[key] = []
            else:
                items = [x.strip().strip('"').strip("'") for x in inner.split(",")]
                out[key] = items
            continue
        # Scalar — strip quotes
        out[key] = val.strip('"').strip("'")

    # Flush final multiline
    if current_multiline_key is not None:
        out[current_multiline_key] = "\n".join(multiline_buf).strip()

    return out


def _extract_in_scope_bullets(context_text: str) -> list[str]:
    """Extract `## Goals → ### In-scope` bullet items as plain strings."""
    if not context_text:
        return []

    # Find Goals section (between `## Goals` and next `## ` H2)
    goals_match = re.search(r"^##\s+Goals\b", context_text, re.MULTILINE)
    if not goals_match:
        return []
    after_goals = context_text[goals_match.end():]
    next_h2 = re.search(r"^##\s+\S", after_goals, re.MULTILINE)
    goals_section = after_goals[: next_h2.start()] if next_h2 else after_goals

    # Find In-scope subsection
    in_scope_match = re.search(r"^###\s+In-scope\b", goals_section, re.MULTILINE)
    if not in_scope_match:
        return []
    after_in_scope = goals_section[in_scope_match.end():]
    next_h3 = re.search(r"^###\s+\S", after_in_scope, re.MULTILINE)
    in_scope_section = after_in_scope[: next_h3.start()] if next_h3 else after_in_scope

    bullets = []
    for line in in_scope_section.splitlines():
        m = re.match(r"^\s*-\s+(.+)$", line)
        if m:
            bullet = m.group(1).strip()
            # Skip placeholder bullets
            if bullet.lower() in ("none", "n/a", "-", "(none)", "{bullet}"):
                continue
            if bullet.startswith("{") and bullet.endswith("}"):
                continue  # template placeholder
            bullets.append(bullet)
    return bullets


def _list_goal_files(test_goals_dir: Path) -> tuple[list[Path], list[Path]]:
    """Return (component_goals, phase_goals) split by filename pattern."""
    if not test_goals_dir.is_dir():
        return [], []
    component: list[Path] = []
    phase: list[Path] = []
    for f in sorted(test_goals_dir.glob("G-*.md")):
        stem = f.stem
        if PHASE_GOAL_RE.match(stem):
            phase.append(f)
        elif COMPONENT_GOAL_RE.match(stem):
            component.append(f)
        # Skip index, README, other naming
    return component, phase


def _bullet_covered(
    bullet: str,
    phase_goals: list[tuple[str, dict]],
) -> bool:
    """Check if any phase-goal cites this bullet via context_goal_ref or
    via shared keyword overlap. Permissive — we accept partial substring
    match in context_goal_ref to avoid false BLOCKs from minor wording
    differences."""
    bullet_norm = bullet.lower().strip()
    bullet_words = set(re.findall(r"[a-z0-9]+", bullet_norm))
    bullet_words = {w for w in bullet_words if len(w) >= 4}  # dropp filler

    for _, fm in phase_goals:
        ref = (fm.get("context_goal_ref") or "").lower().strip()
        if not ref:
            continue
        # Exact substring match
        if bullet_norm in ref or ref.replace('"', "").strip() in bullet_norm:
            return True
        # Keyword overlap ≥ 50%
        if bullet_words:
            ref_words = set(re.findall(r"[a-z0-9]+", ref))
            overlap = len(bullet_words & ref_words)
            if overlap >= max(2, len(bullet_words) // 2):
                return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument(
        "--allow-phase-goal-incomplete",
        action="store_true",
        help="Override BLOCK to WARN (logs override-debt).",
    )
    parser.add_argument("--override-reason", default="", help="Override justification.")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to vg.config.md (accepted for orchestrator compat; unused).",
    )
    args = parser.parse_args()

    out = Output(validator=VALIDATOR_NAME)
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.warn(
                Evidence(
                    type="phase_dir_missing",
                    message=f"Phase {args.phase} not found under .vg/phases/",
                )
            )
            emit_and_exit(out)

        context_path = phase_dir / "CONTEXT.md"
        test_goals_dir = phase_dir / "TEST-GOALS"
        crud_path = phase_dir / "CRUD-SURFACES.md"

        # Skip rule: phase has no_crud_reason → phase-goal not required
        if crud_path.exists():
            crud_text = _read_text(crud_path)
            if re.search(r'"no_crud_reason"\s*:', crud_text):
                out.warn(
                    Evidence(
                        type="skipped_no_crud",
                        message="Phase has no_crud_reason in CRUD-SURFACES.md "
                        "→ phase-goal coverage not required.",
                    )
                )
                emit_and_exit(out)

        if not test_goals_dir.is_dir():
            out.warn(
                Evidence(
                    type="test_goals_dir_missing",
                    message=f"{test_goals_dir} missing — blueprint not run yet?",
                )
            )
            emit_and_exit(out)

        component_files, phase_files = _list_goal_files(test_goals_dir)
        phase_goals: list[tuple[str, dict]] = []
        for pf in phase_files:
            fm = _extract_frontmatter(_read_text(pf))
            phase_goals.append((pf.stem, fm))

        # Check 4 — schema correctness (do this first; downstream checks
        # depend on parsed children/goal_class).
        for gid, fm in phase_goals:
            gc = (fm.get("goal_class") or "").strip()
            if gc != "phase-happy-path":
                out.add(
                    Evidence(
                        type="phase_goal_class_invalid",
                        message=f"{gid}: goal_class must be 'phase-happy-path' (got {gc!r}).",
                        file=str(test_goals_dir / f"{gid}.md"),
                        fix_hint="Set goal_class: phase-happy-path in frontmatter.",
                    )
                )
            postcond = (fm.get("postcondition") or "").strip()
            if not postcond:
                out.add(
                    Evidence(
                        type="phase_goal_postcondition_empty",
                        message=f"{gid}: postcondition is required and must be non-empty.",
                        file=str(test_goals_dir / f"{gid}.md"),
                        fix_hint="Add postcondition: | block describing user-visible end state.",
                    )
                )
            children = fm.get("children") or []
            if not isinstance(children, list) or len(children) < 2:
                out.add(
                    Evidence(
                        type="phase_goal_children_too_few",
                        message=f"{gid}: children[] must list ≥2 component goals "
                        f"(got {len(children) if isinstance(children, list) else 0}).",
                        file=str(test_goals_dir / f"{gid}.md"),
                        fix_hint="Single-goal phases skip phase-goal — component G-XX is sufficient.",
                    )
                )

        # Check 3 — children references resolve to component goals
        component_ids = {f.stem for f in component_files}
        all_child_ids: set[str] = set()
        for gid, fm in phase_goals:
            children = fm.get("children") or []
            if not isinstance(children, list):
                continue
            for ch in children:
                ch = str(ch).strip()
                all_child_ids.add(ch)
                if not COMPONENT_GOAL_RE.match(ch):
                    out.add(
                        Evidence(
                            type="phase_goal_child_id_invalid",
                            message=f"{gid}.children[] = {ch!r} not a valid G-XX id.",
                            file=str(test_goals_dir / f"{gid}.md"),
                        )
                    )
                elif ch not in component_ids:
                    out.add(
                        Evidence(
                            type="phase_goal_child_missing",
                            message=f"{gid}.children[] references {ch} but "
                            f"TEST-GOALS/{ch}.md not found.",
                            file=str(test_goals_dir / f"{gid}.md"),
                            fix_hint=f"Create TEST-GOALS/{ch}.md or remove from children[].",
                        )
                    )

        # Check 2 — orphan component goals
        for cf in component_files:
            cid = cf.stem
            if cid in all_child_ids:
                continue
            fm = _extract_frontmatter(_read_text(cf))
            orphan_reason = (fm.get("phase_goal_orphan_reason") or "").strip()
            if orphan_reason:
                continue  # explicitly flagged setup/util goal
            out.add(
                Evidence(
                    type="component_goal_orphan",
                    message=f"{cid}: not listed in any G-PHASE-NN.children[]. "
                    "Add to a phase-goal's children[] or set "
                    "phase_goal_orphan_reason: '<reason>' in goal frontmatter.",
                    file=str(cf),
                )
            )

        # Check 1 — every CONTEXT in-scope bullet covered
        context_text = _read_text(context_path)
        bullets = _extract_in_scope_bullets(context_text)
        if not bullets:
            out.warn(
                Evidence(
                    type="context_in_scope_empty",
                    message="CONTEXT.md `### In-scope` section empty or missing — "
                    "skipping coverage check (regression: scope step expected).",
                )
            )
        else:
            uncovered: list[str] = []
            for b in bullets:
                if not _bullet_covered(b, phase_goals):
                    uncovered.append(b)
            for b in uncovered:
                out.add(
                    Evidence(
                        type="context_goal_uncovered",
                        message=f"CONTEXT in-scope bullet not covered by any "
                        f"G-PHASE-NN: {b!r}.",
                        fix_hint="Add a G-PHASE-NN with context_goal_ref citing this bullet, "
                        "or update existing phase-goal's context_goal_ref.",
                    )
                )

        # If at least one component goal exists but no phase-goal at all → BLOCK
        if component_files and not phase_files:
            out.add(
                Evidence(
                    type="phase_goal_none_emitted",
                    message=f"{len(component_files)} component G-XX goal(s) exist but "
                    "0 G-PHASE-NN goals emitted. Blueprint contracts pass must "
                    "generate ≥1 phase-goal per user journey (R8-C).",
                    fix_hint="Re-run /vg:blueprint contracts pass; subagent should "
                    "emit TEST-GOALS/G-PHASE-NN.md per CONTEXT in-scope bullet.",
                )
            )

        # Override demotion
        if out.verdict == "BLOCK" and args.allow_phase_goal_incomplete:
            reason = (args.override_reason or "").strip()
            if not reason:
                out.add(
                    Evidence(
                        type="override_missing_reason",
                        message="--allow-phase-goal-incomplete requires "
                        "--override-reason \"<text>\"; cannot demote.",
                    )
                )
            else:
                # Demote BLOCK → WARN; emit a marker evidence so override-debt
                # tracker can pick it up.
                out.verdict = "WARN"
                out.evidence.append(
                    Evidence(
                        type="override_applied",
                        message=f"BLOCK demoted to WARN via "
                        f"--allow-phase-goal-incomplete (reason: {reason})",
                    )
                )

    emit_and_exit(out)
    return 0  # unreachable


if __name__ == "__main__":
    sys.exit(main())
