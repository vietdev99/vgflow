from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_MD = REPO_ROOT / "commands/vg/test.md"


def test_test_md_under_600():
    lines = TEST_MD.read_text().splitlines()
    assert len(lines) <= 600, f"test.md exceeds 600 lines (got {len(lines)})"


def test_test_md_imperative_language():
    body = TEST_MD.read_text()
    assert "<HARD-GATE>" in body, "test.md must contain <HARD-GATE> block"
    assert "Red Flags" in body, "test.md must contain 'Red Flags' section"
    assert "MUST" in body, "test.md must contain 'MUST' imperative language"
    assert "STEP 1" in body, "test.md must contain 'STEP 1'"


def test_test_md_refs_listed_directly():
    body = TEST_MD.read_text()
    expected_refs = [
        "_shared/test/preflight.md",
        "_shared/test/deploy.md",
        "_shared/test/runtime.md",
        "_shared/test/goal-verification/overview.md",
        "_shared/test/goal-verification/delegation.md",
        "_shared/test/codegen/overview.md",
        "_shared/test/codegen/delegation.md",
        "_shared/test/codegen/deep-probe.md",
        "_shared/test/codegen/mobile-codegen.md",
        "_shared/test/fix-loop.md",
        "_shared/test/regression-security.md",
        "_shared/test/close.md",
    ]
    for ref in expected_refs:
        assert ref in body, f"test.md must directly list leaf ref: {ref}"


def test_test_md_uses_agent_not_task():
    body = TEST_MD.read_text()
    # Tool name "Agent" must appear in allowed-tools and instructions
    assert "Agent" in body, "must use Agent tool name (Codex fix #3)"
    # allowed-tools list must NOT have bare "- Task\n" entry (deprecated tool name in VG context)
    assert "\n  - Task\n" not in body, "allowed-tools should use Agent, not Task"
