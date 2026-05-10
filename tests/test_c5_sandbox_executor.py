"""v2.68.0 C5 — Sandbox build executor."""
import re
from pathlib import Path


def test_executor_documents_sandbox_pattern():
    body = Path(".claude/agents/vg-build-task-executor/SKILL.md").read_text(encoding="utf-8")
    # Must mention sandbox / tempdir / isolation
    assert re.search(r"sandbox|tempdir|tempfile|isolat", body, re.IGNORECASE), \
        "executor must document sandbox pattern (v2.68.0 C5)"


def test_executor_describes_when_to_sandbox():
    body = Path(".claude/agents/vg-build-task-executor/SKILL.md").read_text(encoding="utf-8")
    # Should mention test exec specifically (not whole task)
    assert re.search(r"(?:test|pytest|jest|vitest).{0,100}(?:sandbox|isolat)", body, re.IGNORECASE | re.DOTALL), \
        "executor must specify test exec is what gets sandboxed"


def test_waves_delegation_mentions_sandbox():
    body = Path("commands/vg/_shared/build/waves-delegation.md").read_text(encoding="utf-8")
    assert re.search(r"sandbox|tempdir", body, re.IGNORECASE), \
        "waves-delegation must reference sandbox pattern"
