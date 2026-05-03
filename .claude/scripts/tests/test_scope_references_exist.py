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


def test_scope_preflight_resolves_slugged_phase_dirs():
    """`/vg:specs` creates `.vg/phases/N-slug`; scope must not require bare `N/`."""
    body = (SHARED / "preflight.md").read_text(encoding="utf-8")
    assert "phase-resolver.sh" in body
    assert "resolve_phase_dir" in body
    assert 'PHASE_DIR="${PHASES_DIR}/${PHASE_NUMBER}"' in body
    assert body.index("resolve_phase_dir") < body.index('PHASE_DIR="${PHASES_DIR}/${PHASE_NUMBER}"')


def test_scope_preflight_codex_tasklist_binder_is_separate():
    """Codex must create tasklist evidence before any step-active command."""
    body = (SHARED / "preflight.md").read_text(encoding="utf-8")
    assert 'VG_RUNTIME:-}" = "codex"' in body
    assert 'VG_TASKLIST_ADAPTER:-codex' in body
    assert '--adapter "${TASKLIST_ADAPTER}"' in body
    assert "Do not bundle it" in body
    assert body.index("tasklist-projected") < body.index("step-active 0_parse_and_validate")


def test_scope_completeness_extracts_full_in_scope_bullets():
    """Scope completeness must not reduce SPECS bullets to their first verb."""
    body = (SHARED / "completeness-validation.md").read_text(encoding="utf-8")
    assert "def _extract_specs_scope_items" in body
    assert "Return full bullet lines from in-scope SPECS sections only" in body
    assert 'specs_items = _extract_specs_scope_items(specs)' in body
    assert r're.findall(r"^[-*]\s+\S+", specs' not in body
