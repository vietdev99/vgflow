"""v2.72.0 T6 — codex-skills/vg-review/SKILL.md slim."""
from pathlib import Path
import re


def test_codex_review_under_slim_ceiling():
    body = Path("codex-skills/vg-review/SKILL.md").read_text(encoding="utf-8")
    line_count = len(body.splitlines())
    # Original 7757 → split target ≤ 800 (90%+ reduction)
    assert line_count <= 800, \
        f"v2.72.0 codex-review slim target: ≤800 lines (got {line_count})"


def test_codex_review_routes_to_all_9_subfiles():
    body = Path("codex-skills/vg-review/SKILL.md").read_text(encoding="utf-8")
    expected = [
        "preflight.md", "phase-p-variants.md", "code-scan.md", "api-and-discovery.md",
        "lens-and-findings.md", "limits-and-mobile.md", "url-and-error.md",
        "fix-loop-and-goals.md", "close.md",
    ]
    missing = [s for s in expected if f"_shared/review/{s}" not in body]
    assert not missing, f"codex-review missing routes: {missing}"


def test_codex_review_preserves_hardgate_codex():
    body = Path("codex-skills/vg-review/SKILL.md").read_text(encoding="utf-8")
    assert "HARD-GATE-CODEX" in body, "HARD-GATE-CODEX block must be preserved"
    # Must have explicit mark-step calls (v2.65.0 A9 pattern)
    assert "vg-orchestrator mark-step review" in body or "mark-step review" in body, \
        "Manual mark-step calls must be preserved"


def test_codex_review_step_bodies_extracted():
    """Verify ≤ 5 inline <step name=...> bodies remain (slim entries are routing only)."""
    body = Path("codex-skills/vg-review/SKILL.md").read_text(encoding="utf-8")
    # Count full step blocks (with closing tag)
    full_step_blocks = re.findall(r'<step name="[^"]+">.*?</step>', body, re.DOTALL)
    # Long bodies (>500 chars) should be ≤ 5 (allowing some inline gate-only steps)
    long_bodies = [b for b in full_step_blocks if len(b) > 500]
    assert len(long_bodies) <= 5, \
        f"Too many long step bodies remain ({len(long_bodies)}); expected ≤5 after slim"
