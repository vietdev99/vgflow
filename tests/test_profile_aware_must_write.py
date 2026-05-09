"""#142: profile_aware field — review's RUNTIME-MAP.json + GOAL-COVERAGE-MATRIX.md
must always be required regardless of phase profile.

Without this, _PROFILE_REQUIRED_ARTIFACTS["feature"] omits both files,
so the orchestrator's _verify_contract downgrades missing to WARN
(profile_skip) and review emits run.completed PASS — but downstream
/vg:test then hard-blocks on missing input.

Real-user reproducer: phase 7.15, run_id de16229c.
"""
import sys
from pathlib import Path

# Make the orchestrator package importable. The package directory is
# `scripts/vg-orchestrator/` (hyphenated, so we put the dir itself on
# sys.path and import the module file directly rather than as a package).
ORCH_DIR = Path(__file__).resolve().parents[1] / "scripts" / "vg-orchestrator"
if str(ORCH_DIR) not in sys.path:
    sys.path.insert(0, str(ORCH_DIR))

import contracts  # noqa: E402


def test_normalize_default_profile_aware_true():
    out = contracts.normalize_must_write([{"path": "X.md"}])
    assert out[0]["profile_aware"] is True


def test_normalize_explicit_false_preserved():
    out = contracts.normalize_must_write([{"path": "X.md", "profile_aware": False}])
    assert out[0]["profile_aware"] is False


def test_normalize_explicit_true_preserved():
    out = contracts.normalize_must_write([{"path": "X.md", "profile_aware": True}])
    assert out[0]["profile_aware"] is True


def test_normalize_string_shorthand_default_true():
    out = contracts.normalize_must_write(["X.md"])
    assert out[0]["profile_aware"] is True
    assert out[0]["path"] == "X.md"


def test_review_md_wraps_runtime_map_with_profile_aware_false():
    review = Path("commands/vg/review.md").read_text(encoding="utf-8")
    # The RUNTIME-MAP.json entry must be in the dict form with profile_aware: false
    import re
    m = re.search(
        r"path:\s*[\"']?\$\{PHASE_DIR\}/RUNTIME-MAP\.json[\"']?\s*\n"
        r"\s+profile_aware:\s*false",
        review,
    )
    assert m, (
        "review.md must wrap RUNTIME-MAP.json with profile_aware: false "
        "to ensure missing → BLOCK (issue #142)"
    )


def test_review_md_wraps_coverage_matrix_with_profile_aware_false():
    review = Path("commands/vg/review.md").read_text(encoding="utf-8")
    import re
    m = re.search(
        r"path:\s*[\"']?\$\{PHASE_DIR\}/GOAL-COVERAGE-MATRIX\.md[\"']?\s*\n"
        r"\s+profile_aware:\s*false",
        review,
    )
    assert m, "GOAL-COVERAGE-MATRIX.md must be profile_aware: false (issue #142)"


def test_review_md_mirror_byte_identical():
    canonical = Path("commands/vg/review.md")
    mirror = Path(".claude/commands/vg/review.md")
    if not mirror.exists():
        return
    assert canonical.read_bytes() == mirror.read_bytes()


def test_orchestrator_mirror_byte_identical():
    pairs = [
        ("scripts/vg-orchestrator/contracts.py", ".claude/scripts/vg-orchestrator/contracts.py"),
        ("scripts/vg-orchestrator/__main__.py", ".claude/scripts/vg-orchestrator/__main__.py"),
    ]
    for canonical, mirror in pairs:
        c = Path(canonical)
        m = Path(mirror)
        if not m.exists():
            continue
        assert c.read_bytes() == m.read_bytes(), f"{canonical} vs {mirror} drift"
