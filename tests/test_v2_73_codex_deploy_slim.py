"""v2.73.0 T5 — codex-skills/vg-deploy/SKILL.md slim."""
from pathlib import Path
import re


def test_codex_deploy_under_slim_ceiling():
    body = Path("codex-skills/vg-deploy/SKILL.md").read_text(encoding="utf-8")
    line_count = len(body.splitlines())
    # 669 → target ≤ 350 (47%+ reduction)
    assert line_count <= 350, \
        f"v2.73.0 codex-deploy slim target: ≤350 lines (got {line_count})"


def test_codex_deploy_routes_to_subfiles():
    body = Path("codex-skills/vg-deploy/SKILL.md").read_text(encoding="utf-8")
    expected = ["preflight.md", "execute.md", "persist-and-close.md"]
    missing = [s for s in expected if f"_shared/deploy/{s}" not in body]
    assert not missing, f"codex-deploy missing routes: {missing}"


def test_codex_deploy_preserves_adapter():
    body = Path("codex-skills/vg-deploy/SKILL.md").read_text(encoding="utf-8")
    assert "codex_skill_adapter" in body or "HARD-GATE-CODEX" in body, \
        "codex_skill_adapter or HARD-GATE-CODEX must be preserved"


def test_codex_deploy_step_bodies_extracted():
    body = Path("codex-skills/vg-deploy/SKILL.md").read_text(encoding="utf-8")
    full_step_blocks = re.findall(r'<step name="[^"]+">.*?</step>', body, re.DOTALL)
    long_bodies = [b for b in full_step_blocks if len(b) > 500]
    assert len(long_bodies) <= 5, \
        f"Too many long step bodies remain ({len(long_bodies)}); expected ≤5 after slim"
