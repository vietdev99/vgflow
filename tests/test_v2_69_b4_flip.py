"""v2.69.0 T2 — B4 final-reviewer flip + add to frontmatter."""
import re
from pathlib import Path
import yaml


REPO_ROOT = Path(__file__).parent.parent


def test_b4_marker_in_frontmatter():
    body = (REPO_ROOT / "commands/vg/build.md").read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---", body, re.DOTALL)
    fm = yaml.safe_load(m.group(1))
    markers = fm.get("runtime_contract", {}).get("must_touch_markers", [])

    final_entry = next(
        (mk for mk in markers if (isinstance(mk, str) and "7_1_5_final_review" in mk) or
         (isinstance(mk, dict) and mk.get("name") == "7_1_5_final_review")),
        None
    )
    assert final_entry is not None, "v2.69.0 must add 7_1_5_final_review to must_touch_markers"


def test_b4_marker_required_unless_flag():
    body = (REPO_ROOT / "commands/vg/build.md").read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---", body, re.DOTALL)
    fm = yaml.safe_load(m.group(1))
    markers = fm.get("runtime_contract", {}).get("must_touch_markers", [])
    final_entry = next(
        (mk for mk in markers if isinstance(mk, dict) and mk.get("name") == "7_1_5_final_review"),
        None
    )
    if final_entry is None:
        # accept string-form (hard required, no escape) — also valid
        return
    assert final_entry.get("severity") != "warn", "7_1_5_final_review must NOT be warn"


def test_skip_final_review_flag():
    body = (REPO_ROOT / "commands/vg/build.md").read_text(encoding="utf-8")
    assert "--skip-final-review" in body

    # Must be in forbidden_without_override
    m = re.search(r"forbidden_without_override:.*?(?=\n[a-z]|\Z)", body, re.DOTALL)
    assert m and "--skip-final-review" in m.group(0)


def test_close_md_short_circuits_when_skipped():
    body = (REPO_ROOT / "commands/vg/_shared/build/close.md").read_text(encoding="utf-8")
    step7_1_5 = re.search(r"7\.1\.5.*?(?=7\.2|STEP 7\.2|\Z)", body, re.DOTALL)
    assert step7_1_5
    assert "SKIP_FINAL_REVIEW" in step7_1_5.group(0)
