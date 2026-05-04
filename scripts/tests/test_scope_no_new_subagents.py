from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_no_vg_scope_subagent_added():
    """Spec §1.2: scope refactor MUST NOT add new subagents.
    Existing challenger/expander reused via wrappers under _shared/lib/."""
    agents_dir = REPO / "agents"
    if not agents_dir.exists():
        return
    forbidden = sorted(p.name for p in agents_dir.iterdir() if p.name.startswith("vg-scope"))
    assert not forbidden, f"Forbidden new subagents: {forbidden}"


def test_existing_wrappers_still_present():
    """Sanity: the wrappers slim refs depend on must still exist after refactor."""
    lib = REPO / "commands" / "vg" / "_shared" / "lib"
    for w in ("vg-challenge-answer-wrapper.sh", "vg-expand-round-wrapper.sh", "bootstrap-inject.sh"):
        assert (lib / w).exists(), f"Wrapper missing: {w}"
