"""v2.75.0 T5 — codex-skills/vg-specs/SKILL.md slim verification."""
from pathlib import Path
import re


def test_codex_specs_under_slim_ceiling():
    body = Path("codex-skills/vg-specs/SKILL.md").read_text(encoding="utf-8")
    line_count = len(body.splitlines())
    assert line_count <= 400, (
        f"codex-skills/vg-specs/SKILL.md is {line_count} lines — ceiling is 400 "
        f"after v2.75.0 T5 slim (was 684 lines pre-v2.75.0)."
    )


def test_codex_specs_routes_to_subfiles():
    body = Path("codex-skills/vg-specs/SKILL.md").read_text(encoding="utf-8")
    expected = ["preflight.md", "mode-and-draft.md", "write-and-commit.md"]
    missing = [s for s in expected if f"_shared/specs/{s}" not in body]
    assert not missing, (
        f"codex-skills/vg-specs/SKILL.md missing routing references to: {missing}"
    )


def test_codex_specs_preserves_adapter():
    body = Path("codex-skills/vg-specs/SKILL.md").read_text(encoding="utf-8")
    assert "codex_skill_adapter" in body or "HARD-GATE-CODEX" in body, (
        "codex-skills/vg-specs/SKILL.md must preserve <codex_skill_adapter> block"
    )


def test_codex_specs_step_bodies_extracted():
    body = Path("codex-skills/vg-specs/SKILL.md").read_text(encoding="utf-8")
    full_step_blocks = re.findall(r'<step name="[^"]+">.*?</step>', body, re.DOTALL)
    long_bodies = [b for b in full_step_blocks if len(b) > 500]
    assert len(long_bodies) <= 5, (
        f"After T5 slim, codex-skills/vg-specs/SKILL.md should not retain many "
        f"long inline step bodies; found {len(long_bodies)} long blocks."
    )
