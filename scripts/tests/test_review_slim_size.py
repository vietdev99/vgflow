"""R3 Phase E Task 20 — Static tests for slim review entry.

Asserts:
- commands/vg/review.md is ≤600 lines (slim entry, not monolithic)
- All 15 expected refs exist in commands/vg/_shared/review/
- Slim entry references each ref by relative path
- Tool name uses `Agent` (not `Task`) — Codex correction #3
- runtime_contract preserves all 39 must_touch_markers from backup
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REVIEW_MD = REPO_ROOT / "commands" / "vg" / "review.md"
REVIEW_BACKUP = REPO_ROOT / "commands" / "vg" / ".review.md.r3-backup"
REVIEW_REFS_DIR = REPO_ROOT / "commands" / "vg" / "_shared" / "review"

EXPECTED_REFS = [
    "preflight.md",
    "code-scan.md",
    "discovery/overview.md",
    "discovery/delegation.md",
    "lens-dispatch.md",
    "runtime-checks.md",  # NEW post-integrity-fix (commit 1ee4a50)
    "findings/collect.md",
    "findings/fix-loop.md",
    "verdict/overview.md",
    "verdict/pure-backend-fastpath.md",
    "verdict/web-fullstack.md",
    "verdict/profile-branches.md",
    "delta-mode.md",
    "profile-shortcuts.md",
    "crossai.md",
    "close.md",
]


def test_review_md_is_slim() -> None:
    """Slim entry MUST be ≤600 lines (originally 7803). Anthropic 'progressive
    disclosure' standard: keep core SKILL.md focused; move detailed content
    to refs."""
    lines = REVIEW_MD.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 600, (
        f"commands/vg/review.md = {len(lines)} lines, exceeds 600-line slim cap. "
        f"R3 pilot target was ~500 lines. Move detailed steps to refs in "
        f"commands/vg/_shared/review/ per Anthropic Agent Skills standard."
    )


def test_review_md_uses_agent_not_task_tool() -> None:
    """Slim entry MUST use `Agent(subagent_type=...)` (NOT `Task(...)` per
    Codex correction #3 + Claude Code docs). Test scans for incorrect
    `Task(subagent_type=` usage."""
    text = REVIEW_MD.read_text(encoding="utf-8")
    # Allow `Task` mentions in TodoWrite tool name (TaskCreate, TaskUpdate),
    # but `Task(subagent_type=` is the wrong subagent spawn syntax
    assert "Task(subagent_type=" not in text, (
        "review.md uses `Task(subagent_type=...)` — wrong tool name. "
        "Use `Agent(subagent_type=...)` per Codex correction #3."
    )
    # Must contain `Agent(subagent_type=` somewhere (the right pattern)
    assert "Agent(subagent_type=" in text or "subagent_type=" in text, (
        "review.md should reference `Agent(subagent_type=\"vg-review-browser-discoverer\")` "
        "for STEP 3 spawn"
    )


@pytest.mark.parametrize("ref", EXPECTED_REFS)
def test_review_ref_exists(ref: str) -> None:
    """Every expected ref must exist on disk."""
    path = REVIEW_REFS_DIR / ref
    assert path.exists(), (
        f"Expected R3 ref missing: {path.relative_to(REPO_ROOT)}. "
        f"R3 plan declared 16 refs (Tasks 8-17 + integrity-fix runtime-checks)."
    )
    # Non-empty
    content = path.read_text(encoding="utf-8")
    assert len(content) > 100, (
        f"{ref} is suspiciously short ({len(content)} bytes) — likely placeholder"
    )


def test_review_md_references_all_refs() -> None:
    """Slim entry must reference each ref by name (so Claude Code can navigate
    via progressive disclosure)."""
    text = REVIEW_MD.read_text(encoding="utf-8")
    missing_references = []
    for ref in EXPECTED_REFS:
        # Accept either full path `_shared/review/<ref>` or just `<ref>`
        full_path = f"_shared/review/{ref}"
        bare = ref
        if full_path not in text and bare not in text:
            missing_references.append(ref)
    assert not missing_references, (
        f"Slim review.md does not reference these refs: {missing_references}. "
        f"AI cannot route to refs that aren't mentioned in the slim entry."
    )


def test_review_md_step_blocks_in_refs_match_backup() -> None:
    """Workflow integrity: every <step name=\"...\"> block in the backup MUST
    exist in some ref. Anthropic 'faithfulness over compression' standard.

    Sếp dogfood concern (2026-05-04): R3 initial slim refactor lost 7 step
    blocks (998 lines). Integrity fix in commit 1ee4a50 restored them via
    runtime-checks.md. This test pins that the integrity holds."""
    if not REVIEW_BACKUP.exists():
        pytest.skip("backup not present (test runs in dev environments only)")

    backup_text = REVIEW_BACKUP.read_text(encoding="utf-8")
    backup_steps = {
        m.group(1) for m in re.finditer(r'<step\s+name="([^"]+)"', backup_text)
    }

    ref_steps: set[str] = set()
    for path in REVIEW_REFS_DIR.rglob("*.md"):
        ref_text = path.read_text(encoding="utf-8")
        ref_steps |= {
            m.group(1) for m in re.finditer(r'<step\s+name="([^"]+)"', ref_text)
        }

    missing = backup_steps - ref_steps
    assert not missing, (
        f"Workflow integrity loss: {len(missing)} step block(s) in backup "
        f"but NOT in any ref: {sorted(missing)}. AI will have no "
        f"implementation instructions for these markers, even though they "
        f"appear in must_touch_markers contract. Per Anthropic Agent Skills: "
        f"'Skills can bundle additional files within the skill directory and "
        f"reference them by name from SKILL.md.' All step bodies must exist "
        f"somewhere."
    )


def test_review_runtime_contract_preserves_all_markers() -> None:
    """Slim entry runtime_contract.must_touch_markers must include all
    canonical step_ids from backup contract (no marker dropped silently).
    R3 added --skip-lens-plan-gate to forbidden_without_override (audit
    FAIL #13) and may add new markers, but MUST NOT remove any."""
    if not REVIEW_BACKUP.exists():
        pytest.skip("backup not present")

    def extract_markers(text: str) -> set[str]:
        # Frontmatter section between first two --- markers
        m = re.search(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        if not m:
            return set()
        fm = m.group(1)
        # must_touch_markers section (until next top-level key)
        mtm = re.search(
            r"must_touch_markers:\n(.*?)(?=\n  [a-z_]+:\n|\nforbidden_without_override:|\Z)",
            fm,
            re.DOTALL,
        )
        if not mtm:
            return set()
        markers = set()
        for line in mtm.group(1).splitlines():
            # `- "step_name"` or `- name: "step_name"`
            mm = re.search(r'-\s*(?:name:\s*)?"([^"]+)"', line)
            if mm and not mm.group(1).startswith("-"):
                markers.add(mm.group(1))
        return markers

    backup_markers = extract_markers(REVIEW_BACKUP.read_text(encoding="utf-8"))
    slim_markers = extract_markers(REVIEW_MD.read_text(encoding="utf-8"))

    missing = backup_markers - slim_markers
    assert not missing, (
        f"Slim entry dropped {len(missing)} marker(s) from runtime_contract: "
        f"{sorted(missing)}. Stop hook validates must_touch_markers against "
        f"this list — silently dropping markers means AI may skip work that "
        f"the original contract required."
    )
