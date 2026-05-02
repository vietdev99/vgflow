"""Cross-lens consistency tests — invariants spanning all lens files."""
from pathlib import Path
import yaml
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LENS_DIR = REPO_ROOT / "commands" / "vg" / "_shared" / "lens-prompts"

VALID_BUG_CLASSES = {
    "authz", "injection", "auth", "bizlogic",
    "server-side", "redirect", "ui-mechanic", "state-coherence"
}

# Element classes that have lens probes (Tier 1 + Tier 2 active in v2.41).
# Tier-2 wiring closed v2.40 backlog #2; 5 lenses (open-redirect, ssrf,
# auth-jwt, business-logic, info-disclosure) are now reachable via the
# detectors in scripts/identify_interesting_clickables.py.
ACTIVE_ELEMENT_CLASSES = {
    # Tier 1
    "mutation_button", "form_trigger", "row_action",
    "bulk_action", "sub_view_link", "modal_trigger",
    "file_upload",
    # Tier 2 (promoted in v2.41)
    "redirect_url_param", "url_fetch_param", "auth_endpoint",
    "payment_or_workflow", "error_response",
    # Roam/state-coherence lenses
    "mutation_action", "approval_flow", "status_transition",
    "form_root", "submit_button", "table_root", "list_view",
    "filter_bar", "pagination_control",
}

# Still-deferred element classes (Tier 2+ surfaces awaiting downstream wiring).
FUTURE_ELEMENT_CLASSES = {
    "tab", "path_param",
}

# v2.48 ships 16 security/UI lenses plus 3 roam state-coherence lenses.
EXPECTED_LENS_COUNT = 19

ALL_LENS_FILES = sorted(LENS_DIR.glob("lens-*.md"))


def parse_frontmatter(text: str) -> dict:
    assert text.startswith("---\n")
    fm_end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:fm_end])


def all_frontmatter():
    """Yield (lens_path, frontmatter) for all lens files."""
    for lens in ALL_LENS_FILES:
        text = lens.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        yield lens, fm


def test_no_duplicate_lens_names():
    """Each lens file's `name` field must be unique."""
    names = []
    for lens, fm in all_frontmatter():
        names.append(fm["name"])
    duplicates = [n for n in names if names.count(n) > 1]
    assert not duplicates, f"Duplicate lens names: {duplicates}"


def test_lens_name_matches_filename():
    """Frontmatter `name` field must match filename (without .md)."""
    for lens, fm in all_frontmatter():
        expected = lens.stem  # 'lens-idor' from 'lens-idor.md'
        assert fm["name"] == expected, \
            f"{lens.name}: name='{fm['name']}' != filename stem '{expected}'"


def test_all_active_element_classes_covered():
    """Every active element class (Tier 1 of identify_clickables) must have at least 1 lens."""
    covered = set()
    for lens, fm in all_frontmatter():
        for ec in fm.get("applies_to_element_classes", []):
            covered.add(ec)
    uncovered = ACTIVE_ELEMENT_CLASSES - covered
    assert not uncovered, f"Active element classes uncovered by any lens: {uncovered}"


def test_no_unknown_element_classes():
    """Lens applies_to_element_classes must be from known set (Tier 1 + future)."""
    known = ACTIVE_ELEMENT_CLASSES | FUTURE_ELEMENT_CLASSES
    for lens, fm in all_frontmatter():
        for ec in fm.get("applies_to_element_classes", []):
            assert ec in known, \
                f"{lens.name}: unknown element_class '{ec}' (not in Tier 1 or future)"


def test_all_bug_classes_valid():
    """bug_class must be from enum."""
    for lens, fm in all_frontmatter():
        bc = fm.get("bug_class")
        assert bc in VALID_BUG_CLASSES, \
            f"{lens.name}: invalid bug_class '{bc}' (not in {VALID_BUG_CLASSES})"


def test_strix_references_relative_or_native():
    """strix_reference must be either relative path or '(no Strix equiv)' note."""
    for lens, fm in all_frontmatter():
        ref = fm.get("strix_reference", "")
        # Allow native (lens-modal-state)
        if "no Strix equiv" in ref or "VG-specific" in ref:
            continue
        # Otherwise must be relative
        assert not ref.startswith("/"), \
            f"{lens.name}: strix_reference is absolute path '{ref}' (must be relative or native note)"
        assert ":" not in ref, \
            f"{lens.name}: strix_reference contains ':' (Windows path?) '{ref}'"
        assert ref.startswith("strix/"), \
            f"{lens.name}: strix_reference must start with 'strix/' or be native note, got '{ref}'"


def test_action_budgets_reasonable():
    """estimated_action_budget must be in [5, 100] range."""
    for lens, fm in all_frontmatter():
        budget = fm.get("estimated_action_budget")
        assert isinstance(budget, int), f"{lens.name}: budget not int"
        assert 5 <= budget <= 100, \
            f"{lens.name}: action_budget {budget} outside [5, 100]"


def test_severity_default_is_warn_for_v240():
    """All lenses ship at severity_default=warn for v2.40 dogfood."""
    for lens, fm in all_frontmatter():
        assert fm.get("severity_default") == "warn", \
            f"{lens.name}: severity_default must be 'warn' for v2.40 (got '{fm.get('severity_default')}')"


def test_all_phase_profiles_subset():
    """applies_to_phase_profiles must be subset of supported lens profiles."""
    valid = {"feature", "feature-legacy", "hotfix", "bugfix", "migration"}
    for lens, fm in all_frontmatter():
        profiles = set(fm.get("applies_to_phase_profiles", []))
        assert profiles.issubset(valid), \
            f"{lens.name}: profiles {profiles - valid} not in v2.40 supported set"
        assert len(profiles) >= 1, f"{lens.name}: must specify at least 1 phase profile"


def test_total_lens_files_present():
    """Lens catalog includes security/UI lenses plus roam state-coherence lenses."""
    count = len(ALL_LENS_FILES)
    assert count == EXPECTED_LENS_COUNT, \
        f"Expected {EXPECTED_LENS_COUNT} lens files, found {count}"


def test_bug_class_distribution_per_design():
    """v2.40 design doc specifies counts per bug_class."""
    counts = {}
    for lens, fm in all_frontmatter():
        bc = fm["bug_class"]
        counts[bc] = counts.get(bc, 0) + 1
    expected = {
        "authz": 4,           # authz-negative, idor, tenant-boundary, bfla
        "injection": 4,       # input-injection, mass-assignment, path-traversal, file-upload
        "auth": 2,            # auth-jwt, csrf
        "bizlogic": 2,        # duplicate-submit, business-logic
        "server-side": 2,     # ssrf, info-disclosure
        "ui-mechanic": 1,     # modal-state
        "redirect": 1,        # open-redirect
        "state-coherence": 3, # business-coherence, form-lifecycle, table-interaction
    }
    for bc, expected_count in expected.items():
        actual = counts.get(bc, 0)
        assert actual == expected_count, \
            f"bug_class '{bc}': expected {expected_count}, got {actual}"
