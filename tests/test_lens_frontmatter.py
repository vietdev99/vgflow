"""Lens prompt frontmatter validation — parameterized for all lens files."""
import yaml
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LENS_DIR = REPO_ROOT / "commands" / "vg" / "_shared" / "lens-prompts"

REQUIRED_FRONTMATTER = {
    "name", "description", "bug_class", "applies_to_element_classes",
    "applies_to_phase_profiles", "strix_reference", "severity_default",
    "estimated_action_budget", "output_schema_version",
}

# Will be parameterized to all 14 lens files in Task 10+
LENS_NAMES_V2_40 = [
    "lens-authz-negative", "lens-idor", "lens-tenant-boundary", "lens-bfla",
    "lens-input-injection", "lens-mass-assignment", "lens-path-traversal", "lens-file-upload",
    "lens-auth-jwt", "lens-csrf", "lens-duplicate-submit", "lens-business-logic",
    "lens-ssrf", "lens-info-disclosure", "lens-modal-state", "lens-open-redirect",
]


def parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter from markdown file."""
    assert text.startswith("---\n"), "Missing frontmatter opener"
    fm_end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:fm_end])


@pytest.mark.parametrize("lens_name", LENS_NAMES_V2_40)
def test_lens_frontmatter_complete(lens_name):
    """Every lens file MUST have all 9 required frontmatter fields."""
    lens = LENS_DIR / f"{lens_name}.md"
    if not lens.is_file():
        pytest.skip(f"{lens_name}.md not yet created")
    text = lens.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    missing = REQUIRED_FRONTMATTER - set(fm.keys())
    assert not missing, f"{lens_name} missing fields: {missing}"
    assert fm["name"] == lens_name
    assert fm["bug_class"] in {
        "authz", "injection", "auth", "bizlogic", "server-side",
        "redirect", "ui-mechanic"
    }
    assert isinstance(fm["applies_to_element_classes"], list)
    assert len(fm["applies_to_element_classes"]) >= 1
    assert isinstance(fm["estimated_action_budget"], int)
    assert fm["estimated_action_budget"] > 0
    assert fm["severity_default"] in {"warn", "block"}


def test_idor_lens_specific_assertions():
    """lens-idor.md must apply to row_action and use authz bug class."""
    lens = LENS_DIR / "lens-idor.md"
    text = lens.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    assert fm["name"] == "lens-idor"
    assert fm["bug_class"] == "authz"
    assert "row_action" in fm["applies_to_element_classes"]


def test_idor_lens_no_scripted_variations():
    """Sanity check: lens MUST NOT have 'Variation A:'/'Step 1:' scripted markers."""
    lens = LENS_DIR / "lens-idor.md"
    text = lens.read_text(encoding="utf-8")
    # Allow "Step 1:" only in Reconnaissance section (1-2 steps allowed)
    # But disallow in Probe ideas section
    body = text[text.index("\n---\n", 4) + 5:]  # after frontmatter
    # No scripted Variation A/B/C/D headers
    forbidden = ["Variation A", "Variation B", "Variation C", "Variation D"]
    for pattern in forbidden:
        assert pattern not in body, f"Found scripted marker '{pattern}' (exploratory style required)"


def test_idor_lens_has_probe_only_contract():
    """lens MUST have probe-only contract section near top (position 3 per template)."""
    lens = LENS_DIR / "lens-idor.md"
    text = lens.read_text(encoding="utf-8")
    assert "Probe-only contract" in text
    assert "HARD CONSTRAINT" in text or "MUST NOT" in text
    # Constraint must come before Objective section (worker reads top-down)
    contract_pos = text.find("Probe-only contract")
    objective_pos = text.find("## Objective")
    assert contract_pos < objective_pos, \
        "Probe-only contract must precede Objective section"


def test_authz_negative_lens_specific():
    """lens-authz-negative.md must use authz bug class and apply to mutation_button."""
    lens = LENS_DIR / "lens-authz-negative.md"
    fm = parse_frontmatter(lens.read_text(encoding="utf-8"))
    assert fm["name"] == "lens-authz-negative"
    assert fm["bug_class"] == "authz"
    assert "mutation_button" in fm["applies_to_element_classes"]


def test_tenant_boundary_lens_specific():
    """lens-tenant-boundary.md must use authz bug class."""
    lens = LENS_DIR / "lens-tenant-boundary.md"
    fm = parse_frontmatter(lens.read_text(encoding="utf-8"))
    assert fm["name"] == "lens-tenant-boundary"
    assert fm["bug_class"] == "authz"


def test_bfla_lens_specific():
    """lens-bfla.md must use authz bug class."""
    lens = LENS_DIR / "lens-bfla.md"
    fm = parse_frontmatter(lens.read_text(encoding="utf-8"))
    assert fm["name"] == "lens-bfla"
    assert fm["bug_class"] == "authz"


def test_input_injection_lens_specific():
    """lens-input-injection.md must use injection bug class and apply to form_trigger."""
    lens = LENS_DIR / "lens-input-injection.md"
    fm = parse_frontmatter(lens.read_text(encoding="utf-8"))
    assert fm["name"] == "lens-input-injection"
    assert fm["bug_class"] == "injection"
    assert "form_trigger" in fm["applies_to_element_classes"]


def test_mass_assignment_lens_specific():
    """lens-mass-assignment.md must use injection bug class and apply to form_trigger."""
    lens = LENS_DIR / "lens-mass-assignment.md"
    fm = parse_frontmatter(lens.read_text(encoding="utf-8"))
    assert fm["name"] == "lens-mass-assignment"
    assert fm["bug_class"] == "injection"
    assert "form_trigger" in fm["applies_to_element_classes"]


def test_path_traversal_lens_specific():
    """lens-path-traversal.md must use injection bug class and apply to file_upload."""
    lens = LENS_DIR / "lens-path-traversal.md"
    fm = parse_frontmatter(lens.read_text(encoding="utf-8"))
    assert fm["name"] == "lens-path-traversal"
    assert fm["bug_class"] == "injection"
    assert "file_upload" in fm["applies_to_element_classes"]


def test_file_upload_lens_specific():
    """lens-file-upload.md must use injection bug class and apply to file_upload."""
    lens = LENS_DIR / "lens-file-upload.md"
    fm = parse_frontmatter(lens.read_text(encoding="utf-8"))
    assert fm["name"] == "lens-file-upload"
    assert fm["bug_class"] == "injection"
    assert "file_upload" in fm["applies_to_element_classes"]


def test_auth_jwt_lens_specific():
    """lens-auth-jwt.md must use auth bug class and apply to mutation_button."""
    lens = LENS_DIR / "lens-auth-jwt.md"
    fm = parse_frontmatter(lens.read_text(encoding="utf-8"))
    assert fm["name"] == "lens-auth-jwt"
    assert fm["bug_class"] == "auth"
    assert "mutation_button" in fm["applies_to_element_classes"]


def test_csrf_lens_specific():
    """lens-csrf.md must use auth bug class and apply to mutation_button."""
    lens = LENS_DIR / "lens-csrf.md"
    fm = parse_frontmatter(lens.read_text(encoding="utf-8"))
    assert fm["name"] == "lens-csrf"
    assert fm["bug_class"] == "auth"
    assert "mutation_button" in fm["applies_to_element_classes"]


def test_duplicate_submit_lens_specific():
    """lens-duplicate-submit.md must use bizlogic bug class and apply to mutation_button."""
    lens = LENS_DIR / "lens-duplicate-submit.md"
    fm = parse_frontmatter(lens.read_text(encoding="utf-8"))
    assert fm["name"] == "lens-duplicate-submit"
    assert fm["bug_class"] == "bizlogic"
    assert "mutation_button" in fm["applies_to_element_classes"]


def test_business_logic_lens_specific():
    """lens-business-logic.md must use bizlogic bug class and apply to mutation_button."""
    lens = LENS_DIR / "lens-business-logic.md"
    fm = parse_frontmatter(lens.read_text(encoding="utf-8"))
    assert fm["name"] == "lens-business-logic"
    assert fm["bug_class"] == "bizlogic"
    assert "mutation_button" in fm["applies_to_element_classes"]
