"""HOTFIX session 2 (2026-05-05) — auto-adapter + mark-step gate extension.

Two structural fixes after operator confirmation ("bắt được runtime là
claude thì hard cứng là claude, codex thì là codex; vừa nhận được lệnh
flow đã phải lên tasklist ngay"):

1. orchestrator `tasklist-projected --adapter auto` (default) resolves
   from CLAUDECODE env at runtime — eliminates the rationalization knob
   where AI passed `--adapter fallback` to bypass evidence gate.
2. PreToolUse Bash hook gate extended from `step-active` to ALSO cover
   `mark-step`. AI could previously skip step-active entirely and call
   mark-step directly to fake completion — now both require evidence.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH = REPO_ROOT / "scripts" / "vg-orchestrator" / "__main__.py"
HOOK = REPO_ROOT / "scripts" / "hooks" / "vg-pre-tool-use-bash.sh"


# ── Fix 1: auto-adapter ─────────────────────────────────────────────


def test_adapter_argparse_has_auto_default():
    """Argparse exposes --adapter auto + makes it the default."""
    src = ORCH.read_text()
    # Find the tasklist-projected subparser block
    m = re.search(
        r'sub\.add_parser\(\s*"tasklist-projected".*?set_defaults\(func=cmd_tasklist_projected\)',
        src, re.DOTALL,
    )
    assert m, "tasklist-projected subparser not found"
    block = m.group(0)
    assert '"auto"' in block, "Adapter choices must include 'auto'"
    assert 'default="auto"' in block, "Adapter default must be 'auto'"
    assert "required=False" in block, (
        "Adapter must NOT be required (default auto enables CLAUDECODE detection)"
    )


def test_auto_adapter_resolved_from_env():
    """cmd_tasklist_projected must resolve auto → claude/fallback by env."""
    src = ORCH.read_text()
    m = re.search(
        r"def cmd_tasklist_projected.*?(?=^def )",
        src, re.DOTALL | re.MULTILINE,
    )
    body = m.group(0)
    # Auto-resolve branch must exist before the lock check
    assert 'args.adapter == "auto"' in body, (
        "Must check for auto adapter and resolve from env"
    )
    # Resolves to claude when CLAUDECODE=1, fallback otherwise
    auto_idx = body.find('args.adapter == "auto"')
    auto_block = body[auto_idx:auto_idx + 300]
    assert "claude" in auto_block and "fallback" in auto_block, (
        "Auto-resolve must pick claude or fallback based on CLAUDECODE"
    )


# ── Fix 2: mark-step gate extension ─────────────────────────────────


def test_hook_gate_covers_markstep():
    """The early-out regex must match BOTH step-active AND mark-step."""
    src = HOOK.read_text()
    # The gate-trigger condition (the line that proceeds to evidence check
    # ONLY when cmd matches a guarded subcommand). Look for the joined regex.
    assert "(step-active|mark-step)" in src, (
        "Hook regex must match both step-active and mark-step "
        "(extended in HOTFIX session 2)"
    )


def test_hook_extracts_markstep_step_name():
    """Bootstrap exemption needs the step name extracted from mark-step
    (which has format `mark-step <ns> <step>` — step is 2nd arg)."""
    src = HOOK.read_text()
    # The step_name extraction block must handle both forms
    extract_block_match = re.search(
        r'step_name=""[\s\S]*?fi(?=\n)',
        src,
    )
    assert extract_block_match, "step_name extraction block not found"
    block = extract_block_match.group(0)
    assert "step-active" in block and "mark-step" in block, (
        "step_name extraction must handle both step-active and mark-step forms"
    )


def test_hook_markstep_does_not_early_exit_when_evidence_missing():
    """When evidence is missing the mark-step block must fall through
    (no early `exit 0`) so the evidence gate below can deny."""
    src = HOOK.read_text()
    # Find the entire mark-step branch (HOTFIX A reminder + gate decision).
    # Anchor: starts at HOTFIX A header, ends at the closing `fi` of the
    # `if [[ "$cmd_text" =~ ... mark-step ... ]]; then` block.
    m = re.search(
        r"# HOTFIX A \(2026-05-05\)[\s\S]*?\nfi\n",
        src,
    )
    assert m, "HOTFIX A reminder block not found"
    block = m.group(0)
    # Block must document the conditional-exit policy
    assert "do NOT exit here" in block or "fall through" in block.lower(), (
        f"Block must document why it does not unconditionally exit 0. "
        f"Block excerpt: {block[:300]}"
    )
    # Sanity: must reference the evidence file existence check
    assert "_early_evidence_path" in block or ".tasklist-projected.evidence.json" in block, (
        "Block must check evidence file before deciding to exit"
    )


# ── Mirror parity ────────────────────────────────────────────────────


def test_mirror_parity_orch():
    mirror = REPO_ROOT / ".claude/scripts/vg-orchestrator/__main__.py"
    assert mirror.is_file()
    assert ORCH.read_bytes() == mirror.read_bytes(), "Orchestrator mirror drift"


def test_mirror_parity_hook():
    mirror = REPO_ROOT / ".claude/scripts/hooks/vg-pre-tool-use-bash.sh"
    assert mirror.is_file()
    assert HOOK.read_bytes() == mirror.read_bytes(), "Hook mirror drift"
