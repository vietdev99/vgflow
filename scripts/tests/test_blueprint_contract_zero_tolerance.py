"""R8-E (codex audit 2026-05-05) — assert blueprint verify enforces ZERO
tolerance for CONTEXT.md ↔ API-CONTRACTS endpoint mismatches.

Pre-R8-E behavior: 0 mismatch = PASS, 1-3 mismatches = WARN (proceed!),
≥4 mismatches = BLOCK. This let internally-inconsistent blueprints flow
to /vg:build → wrong contract loaded by downstream consumers.

Post-R8-E behavior: ANY mismatch (>0) → BLOCK unless explicit
`--allow-contract-context-mismatch` + `--override-reason`. CONTEXT.md is
source of truth; API-CONTRACTS must match OR CONTEXT decisions amended.

These tests parse the verify.md skill text + frontmatter and assert the
zero-tolerance gate shape exists. Subprocess-executing the bash inline is
not viable (it depends on PHASE_DIR/PYTHON_BIN/vg-orchestrator runtime),
so we treat the source as the artifact under test.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_MD = REPO_ROOT / "commands/vg/_shared/blueprint/verify.md"
BLUEPRINT_MD = REPO_ROOT / "commands/vg/blueprint.md"
PREFLIGHT_MD = REPO_ROOT / "commands/vg/_shared/blueprint/preflight.md"


def _read(path: Path) -> str:
    assert path.exists(), f"Skill file missing: {path.relative_to(REPO_ROOT)}"
    return path.read_text(encoding="utf-8")


def test_passes_on_zero_mismatch():
    """When MISMATCHES==0, verify.md must take the PASS branch (echo ✓ PASS).

    Branch shape (post-R8-E): `if [ "$MISMATCHES" -eq 0 ]; then echo "✓ PASS"`.
    """
    text = _read(VERIFY_MD)
    pass_branch = re.compile(
        r'if\s*\[\s*"\$MISMATCHES"\s*-eq\s*0\s*\];\s*then\s*\n\s*echo\s+"✓\s*PASS"',
    )
    assert pass_branch.search(text), (
        "verify.md must keep the zero-mismatch PASS branch "
        "(`if [ \"$MISMATCHES\" -eq 0 ]; then echo \"✓ PASS\"`)"
    )


def test_blocks_on_one_mismatch():
    """ANY mismatch (>0) must hit the BLOCK path by default.

    Pre-R8-E had `elif [ "$MISMATCHES" -le 3 ]; then echo "⚠ WARNING"` which
    let 1-3 mismatches slip through. Post-R8-E, that warn-branch must be
    removed AND the default else-branch must `exit 1` unless override flag set.
    """
    text = _read(VERIFY_MD)

    # Warn-branch on `-le 3` must NOT exist anymore in the 2c verify section.
    warn_branch = re.compile(
        r'elif\s*\[\s*"\$MISMATCHES"\s*-le\s*3\s*\]\s*;\s*then\s*\n\s*echo\s+"⚠\s*WARNING'
    )
    assert not warn_branch.search(text), (
        "verify.md must NOT contain the legacy `elif [ \"$MISMATCHES\" -le 3 ]` "
        "warn-branch. R8-E zero-tolerance: ANY mismatch → BLOCK."
    )

    # Default else branch (no override flag set) must exit 1 with the
    # CONTEXT-source-of-truth message.
    block_msg = re.compile(
        r'echo\s+"⛔\s+\$\{?MISMATCHES\}?\s+endpoint\s+mismatch\(es\)\s+between\s+CONTEXT\s+decisions\s+and\s+API-CONTRACTS"'
    )
    assert block_msg.search(text), (
        "verify.md must emit the canonical zero-tolerance BLOCK message "
        "(`⛔ ${MISMATCHES} endpoint mismatch(es) between CONTEXT decisions and API-CONTRACTS`)"
    )


def test_allows_with_override_flag():
    """`--allow-contract-context-mismatch` + `--override-reason` proceeds with WARN.

    Override branch must:
      1. Match `--allow-contract-context-mismatch`
      2. Emit canonical `vg-orchestrator override --flag "--allow-contract-context-mismatch"`
      3. Call log_override_debt with gate-id `blueprint-contract-context-mismatch`
      4. Emit `blueprint.contract_context_mismatch_accepted` event
    """
    text = _read(VERIFY_MD)

    # 1. Override flag match
    flag_match = re.compile(
        r'\[\[\s*"\$ARGUMENTS"\s*=~\s*--allow-contract-context-mismatch\s*\]\]'
    )
    assert flag_match.search(text), (
        "verify.md must check `[[ \"$ARGUMENTS\" =~ --allow-contract-context-mismatch ]]`"
    )

    # 2. Canonical vg-orchestrator override --flag invocation
    override_call = re.compile(
        r'vg-orchestrator\s+override\s*\\\s*\n\s*--flag\s+"--allow-contract-context-mismatch"'
    )
    assert override_call.search(text), (
        "verify.md must call `vg-orchestrator override --flag \"--allow-contract-context-mismatch\"`"
    )

    # 3. log_override_debt with canonical gate-id
    debt_call = re.compile(
        r'log_override_debt\s+"blueprint-contract-context-mismatch"'
    )
    assert debt_call.search(text), (
        "verify.md must call `log_override_debt \"blueprint-contract-context-mismatch\" ...`"
    )

    # 4. Telemetry event
    assert "blueprint.contract_context_mismatch_accepted" in text, (
        "verify.md must emit `blueprint.contract_context_mismatch_accepted` event "
        "via vg-orchestrator emit-event"
    )


def test_blocks_override_without_reason():
    """`--allow-contract-context-mismatch` without `--override-reason` must exit 1.

    Override flag alone is insufficient — pairing with --override-reason is
    canonical pattern (matches --skip-codex-test-goal-lane / --skip-rcrurdr).
    """
    text = _read(VERIFY_MD)

    # The override branch must guard `--override-reason` pairing.
    # Pattern: inside the `--allow-contract-context-mismatch` branch, a nested
    # `if [[ ! "$ARGUMENTS" =~ --override-reason ]]; then ... exit 1` block.
    pairing_guard = re.compile(
        r'--allow-contract-context-mismatch.*?'
        r'if\s*\[\[\s*!\s*"\$ARGUMENTS"\s*=~\s*--override-reason\s*\]\];\s*then.*?'
        r'exit\s+1',
        re.DOTALL,
    )
    assert pairing_guard.search(text), (
        "verify.md `--allow-contract-context-mismatch` branch must guard "
        "`--override-reason` pairing with `if [[ ! \"$ARGUMENTS\" =~ --override-reason ]]; then exit 1`"
    )


def test_blueprint_md_frontmatter_has_override_flag():
    """blueprint.md frontmatter must declare `--allow-contract-context-mismatch`
    in `forbidden_without_override` so runtime_contract validation knows it's
    a debt-tracked override (not just a free flag).

    Also must declare `blueprint.contract_context_mismatch_accepted` in
    `must_emit_telemetry` for completeness.
    """
    text = _read(BLUEPRINT_MD)

    # 1. forbidden_without_override list contains the new flag
    forbidden_block = re.search(
        r'forbidden_without_override:\s*\n((?:\s*-\s*"--[^"\n]+"\s*\n)+)',
        text,
    )
    assert forbidden_block, "blueprint.md must have forbidden_without_override block"
    assert '"--allow-contract-context-mismatch"' in forbidden_block.group(1), (
        "blueprint.md `forbidden_without_override` must list "
        "`--allow-contract-context-mismatch` (R8-E zero-tolerance override)"
    )

    # 2. must_emit_telemetry declares the override-acceptance event
    assert "blueprint.contract_context_mismatch_accepted" in text, (
        "blueprint.md `must_emit_telemetry` must declare event "
        "`blueprint.contract_context_mismatch_accepted` (R8-E)"
    )

    # 3. argument-hint surfaces the new flag for users
    arg_hint = re.search(r'argument-hint:\s*"([^"]+)"', text)
    assert arg_hint and "--allow-contract-context-mismatch" in arg_hint.group(1), (
        "blueprint.md `argument-hint` must surface `--allow-contract-context-mismatch`"
    )


def test_preflight_md_documents_override_flag():
    """preflight.md STEP 1.3 (parse args) must document the new flag in its
    flag-summary list (alongside --allow-missing-persistence / --allow-missing-org)
    so AI agents reading the skill see the override exists.
    """
    text = _read(PREFLIGHT_MD)
    assert "--allow-contract-context-mismatch" in text, (
        "preflight.md must document `--allow-contract-context-mismatch` "
        "in its parse-args flag list (R8-E zero-tolerance override)"
    )
