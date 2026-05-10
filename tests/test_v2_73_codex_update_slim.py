"""v2.73.0 T12 — codex-skills/vg-update/SKILL.md slim."""
from pathlib import Path
import re


def test_codex_update_under_slim_ceiling():
    body = Path("codex-skills/vg-update/SKILL.md").read_text(encoding="utf-8")
    line_count = len(body.splitlines())
    # 818 → target ≤ 350 (57%+ reduction)
    assert line_count <= 350, f"got {line_count}"


def test_codex_update_routes_to_all_5_subfiles():
    body = Path("codex-skills/vg-update/SKILL.md").read_text(encoding="utf-8")
    expected = ["preflight.md", "version-and-changelog.md", "fetch-and-merge.md",
                "rotate-and-repair.md", "sync-and-report.md"]
    missing = [s for s in expected if f"_shared/update/{s}" not in body]
    assert not missing, f"missing routes: {missing}"


def test_codex_update_preserves_adapter():
    body = Path("codex-skills/vg-update/SKILL.md").read_text(encoding="utf-8")
    assert "codex_skill_adapter" in body or "HARD-GATE-CODEX" in body


def test_codex_update_step_bodies_extracted():
    body = Path("codex-skills/vg-update/SKILL.md").read_text(encoding="utf-8")
    full_step_blocks = re.findall(r'<step name="[^"]+">.*?</step>', body, re.DOTALL)
    long_bodies = [b for b in full_step_blocks if len(b) > 500]
    assert len(long_bodies) <= 5
