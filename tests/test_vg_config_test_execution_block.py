"""tests/test_vg_config_test_execution_block.py — Batch 5 config block."""
from __future__ import annotations
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

TEMPLATES = [
    REPO_ROOT / "vg.config.template.md",
    REPO_ROOT / ".claude" / "templates" / "vg" / "vg.config.template.md",
    REPO_ROOT / "templates" / "vg" / "vg.config.template.md",
]


def test_all_templates_have_test_execution_block():
    for path in TEMPLATES:
        if not path.is_file():
            continue
        body = path.read_text(encoding="utf-8")
        assert "test:" in body or "test.execution" in body, (
            f"Batch 5: {path.name} missing test.execution block"
        )
        assert "headed_default" in body, f"{path.name} missing headed_default key"
        assert "slow_mo_ms" in body, f"{path.name} missing slow_mo_ms key"
