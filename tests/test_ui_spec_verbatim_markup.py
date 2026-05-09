"""F1 v2.62.0: UI-SPEC verbatim markup paste — fix D2 lossy text-summary."""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DESIGN = REPO_ROOT / "commands" / "vg" / "_shared" / "blueprint" / "design.md"


def test_design_md_has_verbatim_rule():
    body = DESIGN.read_text(encoding="utf-8")
    assert "Verbatim markup for forms" in body, (
        "design.md UI-SPEC agent prompt must instruct verbatim form paste (F1 D2 fix)"
    )


def test_design_md_warns_no_ellipsis():
    body = DESIGN.read_text(encoding="utf-8")
    # Find the verbatim section
    m = re.search(r"Verbatim markup.*?(?=^\d+\.\s|\Z)", body, re.DOTALL | re.MULTILINE)
    assert m
    section = m.group(0)
    assert "NEVER use" in section or "NO ELLIPSIS" in section, (
        "verbatim instructions must explicitly forbid ellipsis (avoids drift to summary)"
    )


def test_design_md_has_top_n_cap():
    body = DESIGN.read_text(encoding="utf-8")
    assert "top 5 forms" in body or "Verbatim Cap" in body, (
        "must declare top-N cap to prevent UI-SPEC bloat"
    )


def test_design_md_cap_section():
    body = DESIGN.read_text(encoding="utf-8")
    assert "## Verbatim Cap" in body, "explicit cap section for opt-out documentation"


def test_design_md_forms_template_uses_html_block():
    body = DESIGN.read_text(encoding="utf-8")
    # Forms template must show actual HTML block, not just bulleted list
    forms_section = re.search(
        r"## Forms\n.*?(?=^## )", body, re.DOTALL | re.MULTILINE,
    )
    assert forms_section
    section = forms_section.group(0)
    # The template should mention "Markup (verbatim" and a fenced html block
    assert "Markup (verbatim" in section, (
        "Forms template must include 'Markup (verbatim from ...)' label"
    )
    assert "```html" in section, (
        "Forms template must show fenced ```html``` block as exemplar"
    )


def test_design_md_mirror_byte_identical():
    canonical = DESIGN
    mirror = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "blueprint" / "design.md"
    if not mirror.exists():
        return
    assert canonical.read_bytes() == mirror.read_bytes()


def test_design_md_under_size_budget():
    """Don't bloat the entry instruction itself."""
    body = DESIGN.read_text(encoding="utf-8")
    assert len(body) < 50000, (
        f"design.md exceeded 50KB budget: {len(body)} chars"
    )
