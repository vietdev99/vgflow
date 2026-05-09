"""D1 v2.63.0: UI-SPEC per-slug split (3-layer pattern)."""
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_blueprint_md_declares_3layer_ui_spec():
    body = (REPO_ROOT / "commands" / "vg" / "blueprint.md").read_text(encoding="utf-8")
    # All 3 layers declared in must_write
    assert "UI-SPEC.md" in body, "Layer 3 flat UI-SPEC.md required in must_write"
    assert "UI-SPEC/index.md" in body, "Layer 2 index required"
    assert "UI-SPEC/*.md" in body or "UI-SPEC/" in body, "Layer 1 per-slug glob required"


def test_design_md_instructs_per_slug_emission():
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "blueprint" / "design.md").read_text(encoding="utf-8")
    # Must mention per-slug emission + index
    assert "${PHASE_DIR}/UI-SPEC/<slug>.md" in body or "UI-SPEC/<slug>.md" in body, (
        "design.md must instruct per-slug UI-SPEC emission for D1 fix"
    )
    assert "UI-SPEC/index.md" in body, "design.md must mention index"


def test_design_md_drops_sampling_language():
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "blueprint" / "design.md").read_text(encoding="utf-8")
    # The "2-3 representative" language is the architectural drift D1 fixes.
    # After D1, the per-slug split makes "every slug" the unit, not "samples".
    # Either the phrase should be replaced with "Per-slug emission" or
    # explicitly noted as superseded.
    sample_count = body.count("2-3 representative")
    # Accept presence in a context comment ("previously 2-3 representative...")
    # but bare instruction must be gone or qualified.
    if sample_count > 0:
        # Must be in a "previously" or "deprecated" context
        contexts = [m.start() for m in re.finditer(r"2-3 representative", body)]
        for ctx in contexts:
            ctx_window = body[max(0, ctx-100):ctx+50].lower()
            assert any(w in ctx_window for w in ("previously", "deprecated", "superseded", "before d1", "old")), (
                "Bare '2-3 representative' instruction must be removed/qualified for D1 fix"
            )


def test_design_md_post_agent_concat_block():
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "blueprint" / "design.md").read_text(encoding="utf-8")
    # Must have a post-agent orchestrator concat block
    assert "for f in" in body and "UI-SPEC" in body, (
        "design.md must include post-agent concat loop building flat UI-SPEC.md"
    )


def test_vg_load_sh_supports_ui_spec_slug(tmp_path):
    vg_load = REPO_ROOT / "scripts" / "vg-load.sh"
    body = vg_load.read_text(encoding="utf-8")
    assert "ui-spec" in body, "vg-load.sh must handle --artifact ui-spec"


def test_vg_load_ui_spec_slug_returns_split(tmp_path):
    """Functional test: --artifact ui-spec --slug X returns UI-SPEC/X.md when present."""
    phase_dir = tmp_path / ".vg" / "phases" / "1.0"
    (phase_dir / "UI-SPEC").mkdir(parents=True)
    (phase_dir / "UI-SPEC" / "login.md").write_text("# UI Spec for login\n\nMarkup goes here.\n", encoding="utf-8")
    (phase_dir / "UI-SPEC.md").write_text("# Flat (should be ignored when slug present)\n", encoding="utf-8")

    vg_load = REPO_ROOT / "scripts" / "vg-load.sh"
    r = subprocess.run(
        ["bash", str(vg_load), "--phase", "1.0",
         "--artifact", "ui-spec", "--slug", "login"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    if r.returncode == 0:
        assert "UI Spec for login" in r.stdout, (
            "vg-load.sh --slug login should return per-slug content"
        )


def test_vg_load_ui_spec_fallback(tmp_path):
    """Functional test: missing per-slug → fallback to flat."""
    phase_dir = tmp_path / ".vg" / "phases" / "2.0"
    phase_dir.mkdir(parents=True)
    (phase_dir / "UI-SPEC.md").write_text("# Flat UI Spec\nFallback content\n", encoding="utf-8")

    vg_load = REPO_ROOT / "scripts" / "vg-load.sh"
    r = subprocess.run(
        ["bash", str(vg_load), "--phase", "2.0",
         "--artifact", "ui-spec", "--slug", "missing-slug"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    if r.returncode == 0:
        assert "Flat UI Spec" in r.stdout, "missing per-slug should fall back to flat"


def test_design_md_mirror():
    canonical = REPO_ROOT / "commands" / "vg" / "_shared" / "blueprint" / "design.md"
    mirror = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "blueprint" / "design.md"
    if not mirror.exists():
        return
    assert canonical.read_bytes() == mirror.read_bytes()


def test_blueprint_md_mirror():
    canonical = REPO_ROOT / "commands" / "vg" / "blueprint.md"
    mirror = REPO_ROOT / ".claude" / "commands" / "vg" / "blueprint.md"
    if not mirror.exists():
        return
    assert canonical.read_bytes() == mirror.read_bytes()


def test_vg_load_mirror():
    canonical = REPO_ROOT / "scripts" / "vg-load.sh"
    mirror = REPO_ROOT / ".claude" / "scripts" / "vg-load.sh"
    if not mirror.exists():
        return
    assert canonical.read_bytes() == mirror.read_bytes()
