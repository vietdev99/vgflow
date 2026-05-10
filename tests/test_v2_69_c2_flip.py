"""v2.69.0 T3 — C2 QA-Checker flip + add to frontmatter."""
import re
from pathlib import Path
import yaml


REPO_ROOT = Path(__file__).parent.parent


def test_c2_marker_in_frontmatter():
    body = (REPO_ROOT / "commands/vg/review.md").read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---", body, re.DOTALL)
    fm = yaml.safe_load(m.group(1))
    markers = fm.get("runtime_contract", {}).get("must_touch_markers", [])

    qa_entry = next(
        (mk for mk in markers if (isinstance(mk, str) and "phase3d_5_qa_checker" in mk) or
         (isinstance(mk, dict) and mk.get("name") == "phase3d_5_qa_checker")),
        None
    )
    assert qa_entry is not None, "v2.69.0 must add phase3d_5_qa_checker to must_touch_markers"


def test_c2_marker_required_unless_flag():
    body = (REPO_ROOT / "commands/vg/review.md").read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---", body, re.DOTALL)
    fm = yaml.safe_load(m.group(1))
    markers = fm.get("runtime_contract", {}).get("must_touch_markers", [])
    qa_entry = next(
        (mk for mk in markers if isinstance(mk, dict) and mk.get("name") == "phase3d_5_qa_checker"),
        None
    )
    if qa_entry is None:
        return
    assert qa_entry.get("severity") != "warn"


def test_skip_qa_check_flag():
    body = (REPO_ROOT / "commands/vg/review.md").read_text(encoding="utf-8")
    assert "--skip-qa-check" in body


def test_review_parse_loop_handles_skip_qa_check():
    # v2.70.0 split: parse loop lives in _shared/review/preflight.md after T1.
    # Concatenate review.md + all _shared/review/*.md to keep the assertion
    # independent of the split layout.
    parts = [(REPO_ROOT / "commands/vg/review.md").read_text(encoding="utf-8")]
    shared_review = REPO_ROOT / "commands/vg/_shared/review"
    if shared_review.is_dir():
        for p in sorted(shared_review.glob("*.md")):
            parts.append(p.read_text(encoding="utf-8"))
    body = "\n".join(parts)
    # Find parse loop region
    parse_region = re.search(r"for tok in.*?esac.*?done", body, re.DOTALL)
    assert parse_region
    assert "--skip-qa-check" in parse_region.group(0)


def test_phase3d_5_short_circuits_when_skipped():
    # v2.70.0 T8: phase3_fix_loop content moved to _shared/review/fix-loop-and-goals.md.
    # Concatenate review.md + all _shared/review/*.md to keep assertion split-independent.
    parts = [(REPO_ROOT / "commands/vg/review.md").read_text(encoding="utf-8")]
    shared_review = REPO_ROOT / "commands/vg/_shared/review"
    if shared_review.is_dir():
        for p in sorted(shared_review.glob("*.md")):
            parts.append(p.read_text(encoding="utf-8"))
    body = "\n".join(parts)
    p3d5 = re.search(r"3d\.5.*?(?=3e|## |\Z)", body, re.DOTALL)
    assert p3d5
    assert "SKIP_QA_CHECK" in p3d5.group(0)
