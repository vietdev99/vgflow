"""v2.69.0 T4 — Verdict telemetry counters."""
from pathlib import Path
import re


REPO_ROOT = Path(__file__).parent.parent


def test_spec_reviewer_emits_verdict_telemetry():
    body = (REPO_ROOT / ".claude/agents/vg-build-spec-reviewer/SKILL.md").read_text(encoding="utf-8")
    assert re.search(r"b1\.verdict|spec_review\.verdict|emit-event.*verdict", body, re.IGNORECASE), \
        "B1 SKILL.md must instruct verdict telemetry emission"


def test_final_reviewer_emits_verdict_telemetry():
    body = (REPO_ROOT / ".claude/agents/vg-build-final-reviewer/SKILL.md").read_text(encoding="utf-8")
    assert re.search(r"b4\.verdict|final_review\.verdict|emit-event.*verdict", body, re.IGNORECASE)


def test_qa_checker_emits_verdict_telemetry():
    body = (REPO_ROOT / ".claude/agents/vg-review-qa-checker/SKILL.md").read_text(encoding="utf-8")
    assert re.search(r"c2\.verdict|qa_check\.verdict|emit-event.*verdict", body, re.IGNORECASE)
