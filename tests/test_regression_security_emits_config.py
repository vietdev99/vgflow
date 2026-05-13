"""tests/test_regression_security_emits_config.py — Batch 5 5e_regression config wiring."""
from __future__ import annotations
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CANONICAL = REPO_ROOT / "commands" / "vg" / "_shared" / "test" / "regression-security.md"
MIRROR = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "test" / "regression-security.md"


def test_5e_regression_materializes_config():
    body = CANONICAL.read_text(encoding="utf-8")
    # Step must copy template into generated tests dir if missing
    assert "playwright.config.generated.template.ts" in body, (
        "Batch 5: 5e_regression must reference the config template path"
    )
    assert "playwright.config.generated.ts" in body


def test_5e_regression_passes_env_to_playwright():
    body = CANONICAL.read_text(encoding="utf-8")
    # Headed env var bridge must exist
    assert "VG_HEADED" in body, (
        "Batch 5: 5e_regression must export VG_HEADED env to control headed/headless"
    )


def test_5e_regression_uses_config_flag():
    body = CANONICAL.read_text(encoding="utf-8")
    # The playwright invocation must pass --config to use generated file
    assert "--config" in body and "playwright.config.generated.ts" in body


def test_mirror_matches_canonical():
    if not MIRROR.is_file():
        return
    assert CANONICAL.read_text(encoding="utf-8") == MIRROR.read_text(encoding="utf-8")
