from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SHARED = REPO / "commands" / "vg" / "_shared" / "scope"
SLIM = REPO / "commands" / "vg" / "scope.md"

REFS = [
    "preflight.md",
    "discussion-overview.md",
    "discussion-round-1-domain.md",
    "discussion-round-2-technical.md",
    "discussion-round-3-api.md",
    "discussion-round-4-ui.md",
    "discussion-round-5-tests.md",
    "discussion-deep-probe.md",
    "env-preference.md",
    "artifact-write.md",
    "completeness-validation.md",
    "crossai.md",
    "close.md",
]


def test_all_13_refs_exist():
    missing = [r for r in REFS if not (SHARED / r).exists()]
    assert not missing, f"Missing refs in {SHARED}: {missing}"


def test_refs_are_flat_one_level_only():
    """Codex correction #4: refs must be FLAT under _shared/scope/, no nested subdirs."""
    if not SHARED.exists():
        return  # Task 7 will create it
    nested = [p for p in SHARED.iterdir() if p.is_dir()]
    assert not nested, f"Found nested dirs (violates Codex #4): {nested}"


def test_slim_entry_lists_each_ref():
    """Slim scope.md MUST mention each ref by basename so AI knows to Read it."""
    if not SLIM.exists():
        return
    body = SLIM.read_text()
    missing = [r for r in REFS if r not in body]
    assert not missing, f"Slim entry missing ref mentions: {missing}"
