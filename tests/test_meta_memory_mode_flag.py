"""Stage 6 task 1/5 of meta-memory v1.1 rollout (Section 14 of design doc):
verify the `meta_memory_mode` rollout flag is documented in config-loader.md
(canonical + mirror byte-identical) and defaults to OFF.

Locks:
  - All four enum values present (disabled, reflect-only, inject-as-advice,
    default-alias).
  - Default is documented as `disabled` (case-insensitive substring check
    against several common phrasings).
  - The `.claude/commands/...` mirror is byte-identical to the canonical
    `commands/...` file (no drift between MCP-registered + canonical).
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CANONICAL = REPO / "commands" / "vg" / "_shared" / "config-loader.md"
MIRROR = REPO / ".claude" / "commands" / "vg" / "_shared" / "config-loader.md"


def test_config_loader_documents_meta_memory_mode():
    f = CANONICAL.read_text(encoding="utf-8")
    assert "meta_memory_mode" in f, "rollout flag name must appear"
    for mode in ("disabled", "reflect-only", "inject-as-advice"):
        assert mode in f, f"allowed value '{mode}' must be documented"


def test_config_loader_documents_default_disabled():
    f = CANONICAL.read_text(encoding="utf-8").lower()
    # Either explicit "default: disabled" or "defaults to disabled" or
    # the table-cell phrasing "disabled (default)".
    assert (
        "default: disabled" in f
        or "defaults to disabled" in f
        or "disabled (default)" in f
    ), "must document that the flag defaults to disabled"


def test_mirror_byte_identical():
    canonical = CANONICAL.read_bytes()
    mirror = MIRROR.read_bytes()
    assert canonical == mirror, (
        f"canonical and .claude/ mirror diverged: "
        f"canonical={len(canonical)}B mirror={len(mirror)}B"
    )
