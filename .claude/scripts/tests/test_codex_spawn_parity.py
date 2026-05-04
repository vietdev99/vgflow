"""Codex spawn parity checks for heavy VGFlow subagent sites."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

HEAVY_SPAWN_REFS = {
    "commands/vg/_shared/build/waves-overview.md": [
        "Codex runtime spawn path",
        "codex-spawn.sh --tier executor --sandbox workspace-write",
        "--spawn-role vg-build-task-executor",
        "parallel[]",
        "sequential_groups[][]",
        "Do NOT execute wave tasks inline",
    ],
    "commands/vg/_shared/build/post-execution-overview.md": [
        "Codex runtime spawn path",
        "codex-spawn.sh --tier executor --sandbox workspace-write",
        "--spawn-role vg-build-post-executor",
        'SUBAGENT_OUTPUT="$(cat "$OUT_FILE")"',
        "Do NOT verify post-execution inline on Codex.",
    ],
    "commands/vg/_shared/test/goal-verification/overview.md": [
        "Codex runtime spawn path",
        "codex-spawn.sh --tier executor --sandbox workspace-write",
        "--spawn-role vg-test-goal-verifier",
        'SUBAGENT_OUTPUT="$(cat "$OUT_FILE")"',
        "Do NOT verify goals inline on Codex.",
    ],
    "commands/vg/_shared/test/codegen/overview.md": [
        "Codex runtime spawn path",
        "codex-spawn.sh --tier executor --sandbox workspace-write",
        "--spawn-role vg-test-codegen",
        'SUBAGENT_OUTPUT="$(cat "$OUT_FILE")"',
        "Do NOT generate Playwright specs inline on Codex.",
    ],
    "commands/vg/_shared/accept/uat/checklist-build/overview.md": [
        "Codex runtime spawn path",
        "codex-spawn.sh --tier executor --sandbox workspace-write",
        "--spawn-role vg-accept-uat-builder",
        'SUBAGENT_OUTPUT="$(cat "$OUT_FILE")"',
        "Do NOT build the UAT checklist inline on Codex.",
    ],
    "commands/vg/_shared/accept/cleanup/overview.md": [
        "Codex runtime spawn path",
        "codex-spawn.sh --tier executor --sandbox workspace-write",
        "--spawn-role vg-accept-cleanup",
        'SUBAGENT_OUTPUT="$(cat "$OUT_FILE")"',
        "Do NOT cleanup inline on Codex.",
    ],
}


def test_heavy_spawn_refs_define_codex_runtime_path():
    for rel, required in HEAVY_SPAWN_REFS.items():
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for marker in required:
            assert marker in text, f"{rel} missing Codex spawn marker: {marker}"


def test_shared_codex_spawn_contract_covers_pipeline_agents():
    text = (REPO_ROOT / "commands/vg/_shared/codex-spawn-contract.md").read_text(
        encoding="utf-8"
    )
    for marker in (
        "build task executor",
        "build post-executor",
        "test goal verifier",
        "test codegen",
        "accept UAT builder",
        "accept cleanup",
        "review scanner with MCP/browser/device work",
        "codex-spawn.sh",
        ".codex-spawn-manifest.jsonl",
        "SUBAGENT_OUTPUT",
    ):
        assert marker in text


def test_codex_spawn_helper_supports_timeout_and_gtimeout():
    text = (REPO_ROOT / "commands/vg/_shared/lib/codex-spawn.sh").read_text(
        encoding="utf-8"
    )
    assert "VG_TIMEOUT_BIN" in text
    assert "command -v timeout || command -v gtimeout" in text
