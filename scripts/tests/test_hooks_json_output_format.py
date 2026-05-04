"""Tier 1 #108 — verify each migrated hook contains canonical JSON emit pattern.

Static lint over hook source. Runtime smoke-tested separately via the
existing test_hook_pretooluse_blocks.py suite (which still asserts exit 2 +
stderr — the dual-channel back-compat layer is preserved).

Each hook MUST contain `hookSpecificOutput` (Claude Code 2.0+ JSON envelope).
PreToolUse blockers additionally MUST contain `permissionDecision` + a deny
value, mirroring `.claude/scripts/vg-agent-spawn-guard.py:140-177`.
SessionStart / PostToolUse / UserPromptSubmit context-only hooks MUST emit
`additionalContext`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


# Per-hook expected markers. None of these checks require the hook to run —
# they're a static contract over the source so we catch regressions when
# someone refactors and accidentally drops the dual-channel pattern.
HOOK_CONTRACTS = [
    # (relative path, must-contain markers)
    (
        "scripts/hooks/vg-pre-tool-use-bash.sh",
        ["hookSpecificOutput", "permissionDecision", "additionalContext", "deny"],
    ),
    (
        "scripts/hooks/vg-pre-tool-use-write.sh",
        ["hookSpecificOutput", "permissionDecision", "additionalContext", "deny"],
    ),
    (
        "scripts/hooks/vg-pre-tool-use-agent.sh",
        ["hookSpecificOutput", "permissionDecision", "additionalContext", "deny"],
    ),
    (
        "scripts/hooks/vg-post-tool-use-todowrite.sh",
        ["hookSpecificOutput", "additionalContext", "PostToolUse"],
    ),
    (
        "scripts/hooks/vg-session-start.sh",
        ["hookSpecificOutput", "additionalContext", "SessionStart"],
    ),
    (
        "scripts/hooks/vg-stop.sh",
        # Stop hook uses {"decision":"block"} per Claude Code spec, plus
        # hookSpecificOutput.additionalContext for the operator surface.
        ["hookSpecificOutput", "additionalContext", "decision", "block"],
    ),
    (
        "scripts/hooks/vg-user-prompt-submit.sh",
        ["hookSpecificOutput", "additionalContext", "UserPromptSubmit"],
    ),
]


@pytest.mark.parametrize("hook_path,markers", HOOK_CONTRACTS, ids=[h for h, _ in HOOK_CONTRACTS])
def test_hook_emits_canonical_json_envelope(hook_path: str, markers: list[str]) -> None:
    """Each hook source must contain the canonical Claude Code 2.0+ JSON shape."""
    p = REPO / hook_path
    assert p.exists(), f"missing hook: {hook_path}"
    src = p.read_text(encoding="utf-8")

    missing = [m for m in markers if m not in src]
    assert not missing, (
        f"{hook_path} missing canonical JSON emit markers: {missing}\n"
        f"Expected pattern (mirrors .claude/scripts/vg-agent-spawn-guard.py:140-177):\n"
        f"  hookSpecificOutput JSON on stdout + 3-line stderr + exit 2"
    )


@pytest.mark.parametrize("hook_path,_", HOOK_CONTRACTS, ids=[h for h, _ in HOOK_CONTRACTS])
def test_hook_mirror_parity(hook_path: str, _: list[str]) -> None:
    """Source and .claude/ mirror must be byte-identical."""
    src = REPO / hook_path
    mirror = REPO / hook_path.replace("scripts/hooks/", ".claude/scripts/hooks/")
    assert src.exists(), f"missing source: {hook_path}"
    assert mirror.exists(), f"missing mirror: {mirror}"
    assert src.read_bytes() == mirror.read_bytes(), (
        f"mirror drift between {hook_path} and {mirror.relative_to(REPO)} — "
        f"run install-hooks.sh or `cp {hook_path} {mirror.relative_to(REPO)}`"
    )


def test_all_seven_hooks_have_hookspecificoutput() -> None:
    """Top-level invariant: grep `hookSpecificOutput` matches all 7 migrated hooks.

    Self-review checkbox from the migration spec (Tier 1 #108):
    > grep -l "hookSpecificOutput" scripts/hooks/*.sh returns all 7
    """
    expected = {h for h, _ in HOOK_CONTRACTS}
    found = set()
    for hook in (REPO / "scripts/hooks").glob("*.sh"):
        if hook.name == "install-hooks.sh":
            continue
        if "hookSpecificOutput" in hook.read_text(encoding="utf-8"):
            found.add(f"scripts/hooks/{hook.name}")
    assert found >= expected, (
        f"hooks missing hookSpecificOutput pattern: {expected - found}"
    )
