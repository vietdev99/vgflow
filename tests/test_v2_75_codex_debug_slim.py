"""v2.75.0 T10 — codex-skills/vg-debug/SKILL.md slim verification."""
from pathlib import Path
import re


def test_codex_debug_under_slim_ceiling():
    body = Path("codex-skills/vg-debug/SKILL.md").read_text(encoding="utf-8")
    line_count = len(body.splitlines())
    assert line_count <= 400, (
        f"codex-skills/vg-debug/SKILL.md is {line_count} lines — ceiling is 400 "
        f"after v2.75.0 T10 slim (was 690 lines pre-v2.75.0)."
    )


def test_codex_debug_routes_to_subfiles():
    body = Path("codex-skills/vg-debug/SKILL.md").read_text(encoding="utf-8")
    expected = ["preflight.md", "discovery-and-fix.md", "verify-and-close.md"]
    missing = [s for s in expected if f"_shared/debug/{s}" not in body]
    assert not missing, (
        f"codex-skills/vg-debug/SKILL.md missing routing references to: {missing}"
    )


def test_codex_debug_preserves_adapter():
    body = Path("codex-skills/vg-debug/SKILL.md").read_text(encoding="utf-8")
    assert "codex_skill_adapter" in body or "HARD-GATE-CODEX" in body, (
        "codex-skills/vg-debug/SKILL.md must preserve <codex_skill_adapter> block"
    )


def test_codex_debug_step_bodies_extracted():
    body = Path("codex-skills/vg-debug/SKILL.md").read_text(encoding="utf-8")
    full_step_blocks = re.findall(r'<step name="[^"]+">.*?</step>', body, re.DOTALL)
    long_bodies = [b for b in full_step_blocks if len(b) > 500]
    assert len(long_bodies) <= 5, (
        f"After T10 slim, codex-skills/vg-debug/SKILL.md should not retain many "
        f"long inline step bodies; found {len(long_bodies)} long blocks."
    )
