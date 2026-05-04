"""Task 36a — verify all lens-*.md have the 6 required frontmatter fields."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
LENS_DIR = REPO / "commands/vg/_shared/lens-prompts"

REQUIRED_FIELDS = (
    "recommended_worker_tier",
    "worker_complexity_score",
    "fallback_on_inconclusive",
    "min_actions_floor",
    "min_evidence_steps",
    "required_probe_kinds",
)

VALID_TIERS = {"haiku", "sonnet", "opus", "crossai"}
VALID_FALLBACKS = {"haiku", "sonnet", "opus", "crossai", "none"}


def _load_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.+?)\n---", text, re.DOTALL)
    if not m:
        return {}
    return yaml.safe_load(m.group(1)) or {}


def test_every_lens_has_all_6_fields() -> None:
    failures: list[str] = []
    for lens_path in sorted(LENS_DIR.glob("lens-*.md")):
        if lens_path.stem == "_TEMPLATE":
            continue
        fm = _load_frontmatter(lens_path)
        for field in REQUIRED_FIELDS:
            if field not in fm:
                failures.append(f"{lens_path.name}: missing {field}")
    assert not failures, "\n".join(failures)


def test_recommended_worker_tier_valid() -> None:
    failures: list[str] = []
    for lens_path in sorted(LENS_DIR.glob("lens-*.md")):
        fm = _load_frontmatter(lens_path)
        tier = fm.get("recommended_worker_tier")
        if tier and tier not in VALID_TIERS:
            failures.append(f"{lens_path.name}: tier={tier} not in {VALID_TIERS}")
    assert not failures, "\n".join(failures)


def test_complexity_score_in_range() -> None:
    failures: list[str] = []
    for lens_path in sorted(LENS_DIR.glob("lens-*.md")):
        fm = _load_frontmatter(lens_path)
        score = fm.get("worker_complexity_score")
        if score is not None and not (1 <= int(score) <= 5):
            failures.append(f"{lens_path.name}: complexity_score={score} not in 1..5")
    assert not failures, "\n".join(failures)


def test_complexity_4_requires_sonnet_plus() -> None:
    """Spec invariant: complexity ≥4 forces sonnet+; complexity ==5 forces opus."""
    failures: list[str] = []
    for lens_path in sorted(LENS_DIR.glob("lens-*.md")):
        fm = _load_frontmatter(lens_path)
        score = fm.get("worker_complexity_score")
        tier = fm.get("recommended_worker_tier")
        if score == 5 and tier != "opus":
            failures.append(f"{lens_path.name}: complexity 5 requires opus, got {tier}")
        if score == 4 and tier == "haiku":
            failures.append(f"{lens_path.name}: complexity 4 forbids haiku, got {tier}")
    assert not failures, "\n".join(failures)


def test_fallback_on_inconclusive_valid() -> None:
    failures: list[str] = []
    for lens_path in sorted(LENS_DIR.glob("lens-*.md")):
        fm = _load_frontmatter(lens_path)
        fb = fm.get("fallback_on_inconclusive")
        if fb and fb not in VALID_FALLBACKS:
            failures.append(f"{lens_path.name}: fallback={fb} not in {VALID_FALLBACKS}")
    assert not failures, "\n".join(failures)


def test_min_actions_floor_positive() -> None:
    for lens_path in sorted(LENS_DIR.glob("lens-*.md")):
        fm = _load_frontmatter(lens_path)
        floor = fm.get("min_actions_floor")
        assert floor is None or floor >= 1, f"{lens_path.name}: min_actions_floor must be ≥1"


def test_required_probe_kinds_is_list() -> None:
    for lens_path in sorted(LENS_DIR.glob("lens-*.md")):
        fm = _load_frontmatter(lens_path)
        kinds = fm.get("required_probe_kinds")
        assert kinds is None or isinstance(kinds, list), f"{lens_path.name}: required_probe_kinds must be list"


def test_complexity_distribution_is_not_vacuous() -> None:
    """Codex round-3 follow-on: ensure the complexity-tier table actually
    spans the matrix — at least 3 lenses at complexity ≥4, at least 1 at
    complexity 5 with tier=opus. Prevents migration from silently flattening
    everything to haiku."""
    high_complexity_count = 0
    has_opus_5 = False
    for lens_path in sorted(LENS_DIR.glob("lens-*.md")):
        fm = _load_frontmatter(lens_path)
        score = fm.get("worker_complexity_score")
        tier = fm.get("recommended_worker_tier")
        if isinstance(score, int):
            if score >= 4:
                high_complexity_count += 1
            if score == 5 and tier == "opus":
                has_opus_5 = True
    assert high_complexity_count >= 3, \
        f"expected ≥3 lenses with complexity ≥4, got {high_complexity_count}"
    assert has_opus_5, "expected ≥1 lens with complexity=5 + tier=opus"
