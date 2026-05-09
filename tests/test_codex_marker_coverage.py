"""v2.65.0 A9 — Codex skill marker coverage.

Codex has no PreToolUse/PostToolUse hooks. Claude Code's hooks auto-emit step
markers (e.g. `1_parse_args`, `7_discover_plans`) but on Codex these never
fire — contract validator then reports "8/N markers found" because the
hook-driven markers are missing.

A9 fix: each codex-skill must explicitly call `vg-orchestrator mark-step
<command> <marker>` after each step's primary action so the orchestrator
sees the same evidence Claude's hooks would have written.

This test enforces that each of the 7 user-facing codex-skills (vg-build,
vg-review, vg-test, vg-deploy, vg-accept, vg-blueprint, vg-scope) embeds:

  1. A HARD-GATE-CODEX reminder block (top-level documentation).
  2. An explicit mark-step (or shared `mark_step` helper) call for every
     HARD marker declared in commands/vg/<cmd>.md `must_touch_markers`.

WARN markers (severity: warn) and profile-gated markers are advisory and
not enforced here.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


CODEX_SKILLS = [
    "vg-build",
    "vg-review",
    "vg-test",
    "vg-deploy",
    "vg-accept",
    "vg-blueprint",
    "vg-scope",
]

REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def get_required_hard_markers(cmd_name: str) -> set[str]:
    """Parse must_touch_markers from commands/vg/<cmd>.md frontmatter.

    Returns ONLY HARD markers — string entries `- "name"` in the YAML
    list. Dict entries with `name:` + `severity: warn` are advisory and
    excluded; dict entries with `profile:` (no severity) are also
    excluded since they only fire for some profiles.
    """
    cmd_path = REPO_ROOT / "commands" / "vg" / f"{cmd_name}.md"
    if not cmd_path.exists():
        return set()

    body = _read_text(cmd_path)

    # Extract frontmatter (between the first two --- lines).
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", body, re.DOTALL)
    if not fm_match:
        return set()
    frontmatter = fm_match.group(1)

    # Find must_touch_markers list. The list lives under runtime_contract:,
    # so its sibling keys (must_emit_telemetry, forbidden_without_override,
    # ...) are indented at 2 spaces. The list ends at the next 2-space
    # indented key, or end of frontmatter.
    markers_match = re.search(
        r"^  must_touch_markers:\s*\n(.*?)(?=^  [a-zA-Z_]+:|\Z)",
        frontmatter,
        re.DOTALL | re.MULTILINE,
    )
    if not markers_match:
        # Some commands (e.g. simple ones) put it at column 0.
        markers_match = re.search(
            r"^must_touch_markers:\s*\n(.*?)(?=^[a-zA-Z_]+:|\Z)",
            frontmatter,
            re.DOTALL | re.MULTILINE,
        )
    if not markers_match:
        return set()

    markers_text = markers_match.group(1)

    # HARD markers = string-form entries: `- "name"` (no severity:warn,
    # no profile:, no required_unless_flag adjacent in the same block).
    hard: set[str] = set()
    for line_match in re.finditer(
        r'^\s+-\s*"([^"]+)"\s*$', markers_text, re.MULTILINE
    ):
        hard.add(line_match.group(1))

    return hard


@pytest.mark.parametrize("skill_name", CODEX_SKILLS)
def test_codex_skill_has_hardgate_codex_block(skill_name: str) -> None:
    """Each codex-skill must carry a HARD-GATE-CODEX reminder (v2.65.0 A9).

    The block reminds the AI that Codex has no hooks and that mark-step
    must be invoked manually for every must_touch_markers entry.
    """
    skill_path = REPO_ROOT / "codex-skills" / skill_name / "SKILL.md"
    assert skill_path.exists(), f"{skill_path} not found"
    body = _read_text(skill_path)
    assert "HARD-GATE-CODEX" in body, (
        f"{skill_name}: missing <HARD-GATE-CODEX> reminder block (v2.65.0 A9). "
        "Codex has no hook substrate; the skill MUST tell the AI to emit "
        "mark-step manually for every hard marker declared in commands/vg/"
        f"{skill_name.removeprefix('vg-')}.md."
    )


@pytest.mark.parametrize("skill_name", CODEX_SKILLS)
def test_codex_skill_emits_hard_markers(skill_name: str) -> None:
    """Each codex-skill must explicitly emit every HARD marker (v2.65.0 A9).

    Accepts either form:
      - `vg-orchestrator mark-step <cmd> <marker>` (preferred direct call)
      - `mark_step "<phase>" "<marker>" "<dir>"` (shared bash helper from
         commands/vg/_shared/lib/markers.sh — also writes a step marker)
    """
    cmd_name = skill_name.removeprefix("vg-")
    required = get_required_hard_markers(cmd_name)

    if not required:
        pytest.skip(
            f"{cmd_name} has no must_touch_markers (or no HARD entries) "
            "in commands/vg/<cmd>.md frontmatter"
        )

    skill_path = REPO_ROOT / "codex-skills" / skill_name / "SKILL.md"
    skill_body = _read_text(skill_path)

    missing: list[str] = []
    for marker in sorted(required):
        # Direct orchestrator call — `mark-step <cmd> <marker>`.
        direct = re.search(
            rf"mark-step\s+\S+\s+{re.escape(marker)}\b",
            skill_body,
        )
        # Shared helper — `mark_step "<phase>" "<marker>" "<dir>"`.
        helper = re.search(
            rf'mark_step\s+\S+\s+"{re.escape(marker)}"',
            skill_body,
        )
        if not direct and not helper:
            missing.append(marker)

    assert not missing, (
        f"{skill_name}: missing manual mark-step calls for "
        f"{len(missing)}/{len(required)} HARD markers required by "
        f"commands/vg/{cmd_name}.md must_touch_markers:\n"
        f"  {missing}"
    )


def test_get_required_hard_markers_filters_warn_entries() -> None:
    """Sanity check: WARN/profile-only markers must be excluded."""
    build_hard = get_required_hard_markers("build")
    # 0_session_lifecycle is severity: warn -> excluded.
    assert "0_session_lifecycle" not in build_hard
    # 1_parse_args is hard string -> included.
    assert "1_parse_args" in build_hard
    # 8_execute_waves is hard -> included.
    assert "8_execute_waves" in build_hard
