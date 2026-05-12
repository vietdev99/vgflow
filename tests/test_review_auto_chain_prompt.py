"""tests/test_review_auto_chain_prompt.py — Option A auto-chain prompt wiring.

After /vg:review run-complete succeeds, if PIPELINE-STATE.next_command is set,
the skill body must instruct the AI to AskUserQuestion (chain / skip / inspect)
and chain to the suggested skill if user picks chain. CI/headless can use
--auto-chain to skip prompt + auto-chain, or --no-chain to skip prompt + exit.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLOSE_MD = REPO_ROOT / "commands" / "vg" / "_shared" / "review" / "close.md"
CLOSE_MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "review" / "close.md"
REVIEW_MD = REPO_ROOT / "commands" / "vg" / "review.md"
REVIEW_MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "review.md"


def test_close_documents_auto_chain_step():
    """close.md must declare the post-run-complete auto-chain step."""
    body = CLOSE_MD.read_text(encoding="utf-8")
    assert "auto-chain" in body.lower() or "auto_chain" in body, (
        "review/close.md must document the auto-chain prompt step"
    )
    # Must reference PIPELINE-STATE.next_command as the data source
    assert "next_command" in body, (
        "auto-chain step must read PIPELINE-STATE.next_command"
    )


def test_close_documents_three_choice_prompt():
    """The skill body must direct AI to AskUserQuestion with 3 choices."""
    body = CLOSE_MD.read_text(encoding="utf-8")
    assert "AskUserQuestion" in body, (
        "auto-chain step must instruct AI to call AskUserQuestion"
    )
    # Three semantic choices: chain (run now), skip (exit), inspect (show detail)
    for kw in ("chain", "skip", "inspect"):
        assert kw in body.lower(), (
            f"auto-chain step missing '{kw}' choice keyword"
        )


def test_close_documents_skill_tool_invocation():
    """If user picks chain, AI must invoke suggested skill via Skill tool."""
    body = CLOSE_MD.read_text(encoding="utf-8")
    assert "Skill tool" in body or "Skill(" in body or "via `Skill`" in body, (
        "auto-chain step must instruct AI to use Skill tool to invoke chained command"
    )


def test_close_respects_auto_chain_flag():
    """--auto-chain flag must skip prompt + auto-chain.
    --no-chain flag must skip prompt + exit."""
    body = CLOSE_MD.read_text(encoding="utf-8")
    assert "--auto-chain" in body, "close.md must document --auto-chain flag behavior"
    assert "--no-chain" in body, "close.md must document --no-chain flag behavior"


def test_review_md_lists_new_flags():
    """review.md argument-hint must include --auto-chain and --no-chain."""
    body = REVIEW_MD.read_text(encoding="utf-8")
    fm = re.match(r"^---\n(.*?)\n---\n", body, re.DOTALL)
    assert fm, "review.md missing frontmatter"
    fm_text = fm.group(1)
    arg_hint_m = re.search(r"^argument-hint:\s*\"([^\"]+)\"", fm_text, re.MULTILINE)
    assert arg_hint_m, "review.md argument-hint not found"
    hint = arg_hint_m.group(1)
    assert "--auto-chain" in hint, "argument-hint must list --auto-chain"
    assert "--no-chain" in hint, "argument-hint must list --no-chain"


def test_close_invokes_after_run_complete():
    """The auto-chain block must live AFTER the `vg-orchestrator run-complete`
    success guard — only runs when review verdict valid."""
    body = CLOSE_MD.read_text(encoding="utf-8")
    run_complete_idx = body.rindex("vg-orchestrator run-complete")
    # The auto-chain section header should appear AFTER the last run-complete invocation
    chain_idx = body.lower().index("auto-chain")
    assert chain_idx > run_complete_idx, (
        "auto-chain step must come AFTER vg-orchestrator run-complete success"
    )


def test_mirrors_byte_identical():
    assert CLOSE_MD.read_bytes() == CLOSE_MIRROR.read_bytes(), \
        "review/close.md mirror diverged"
    assert REVIEW_MD.read_bytes() == REVIEW_MIRROR.read_bytes(), \
        "review.md mirror diverged"


def test_close_documents_retry_command_branch():
    """When review verdict is BLOCK (failed), the retry_command path matters
    too — should be offered alongside next_command."""
    body = CLOSE_MD.read_text(encoding="utf-8")
    assert "retry_command" in body, (
        "auto-chain step must handle retry_command for BLOCK verdicts"
    )
