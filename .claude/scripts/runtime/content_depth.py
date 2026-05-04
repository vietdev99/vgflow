"""D27 anti-skim content-depth validators (RFC v9 PR-content-depth).

Closes the failure mode where AI authors bare-minimum sections to pass
schema gates: "## Edge cases\n- TBD\n" technically satisfies "section
exists" but adds zero value. The validators below catch this:

1. word_count(text, min) — section body has minimum substantive words
2. cross_reference(refs_in_doc, decisions_required, ...) — every required
   decision/contract anchor is referenced
3. edge_case_substance(section_text) — listed edge cases have non-trivial
   bodies (not just bullets with "TBD"/"N/A")
4. instruction_repetition(text, key_phrases) — required instruction
   phrases reappear at the right cadence (catches "AI skim" where the
   instruction is ack'd at top but ignored later)

Each returns a (passed, failure_message) tuple so the caller can compose
into a single validator output JSON.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable


_WORD_RE = re.compile(r"\b\w+\b", re.UNICODE)
_BULLET_LINE_RE = re.compile(r"^\s*[-*+]\s+(.+?)$", re.MULTILINE)
_TBD_LINE_RE = re.compile(
    r"^\s*[-*+]\s*(?:TBD|TODO|N/?A|none|tbd|todo|chưa|cần\s*bổ\s*sung)\s*\.?\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def word_count(text: str, *, min_words: int) -> tuple[bool, str | None]:
    """Substantive word count (excludes punctuation but counts inside code/quotes)."""
    n = len(_WORD_RE.findall(text or ""))
    if n < min_words:
        return False, f"word_count={n} < min={min_words}"
    return True, None


def cross_reference(
    text: str,
    *,
    required_anchors: Iterable[str],
    min_unique: int | None = None,
) -> tuple[bool, str | None]:
    """Every required_anchors must appear at least once in `text`."""
    found = []
    missing = []
    for anchor in required_anchors:
        if anchor and anchor in text:
            found.append(anchor)
        elif anchor:
            missing.append(anchor)
    if missing:
        return False, f"missing cross-references: {missing[:10]}"
    if min_unique is not None and len(found) < min_unique:
        return False, f"only {len(found)} unique anchors (min={min_unique})"
    return True, None


def edge_case_substance(
    section_text: str,
    *,
    min_bullets_with_body: int = 3,
    bullet_min_words: int = 8,
) -> tuple[bool, str | None]:
    """Edge case section must have N bullets each with substantive body.

    Definition of substantive:
    - Bullet line ≥ bullet_min_words.
    - NOT a TBD-style placeholder (TBD/TODO/N/A/none/chưa/cần bổ sung).
    """
    placeholder_count = len(_TBD_LINE_RE.findall(section_text))
    bullets = _BULLET_LINE_RE.findall(section_text)
    substantive = [
        b for b in bullets
        if len(_WORD_RE.findall(b)) >= bullet_min_words
        and not _TBD_LINE_RE.match(f"- {b}")
    ]
    if placeholder_count > 0:
        return False, (
            f"{placeholder_count} placeholder bullet(s) (TBD/TODO/N/A) — "
            f"replace with concrete edge cases"
        )
    if len(substantive) < min_bullets_with_body:
        return False, (
            f"{len(substantive)} substantive bullets (≥{bullet_min_words} words each) "
            f"< min={min_bullets_with_body}; total bullets={len(bullets)}"
        )
    return True, None


def instruction_repetition(
    text: str,
    *,
    key_phrase: str,
    min_occurrences: int = 2,
    case_insensitive: bool = True,
) -> tuple[bool, str | None]:
    """A critical instruction must appear ≥ min_occurrences times.

    Catches the AI-skim pattern: instruction stated once at the top, then
    ignored. Re-stating at relevant section anchors makes each step
    locally enforceable.
    """
    flags = re.IGNORECASE if case_insensitive else 0
    matches = re.findall(re.escape(key_phrase), text or "", flags=flags)
    if len(matches) < min_occurrences:
        return False, (
            f"key phrase '{key_phrase}' occurs {len(matches)}× "
            f"< min={min_occurrences}"
        )
    return True, None


def llm_judge_sample(
    sections: dict[str, str],
    *,
    sample_size: int = 3,
    rng_seed: int = 0,
) -> dict[str, str]:
    """Pick a deterministic sample of sections for LLM-as-judge review.

    Returns {section_name: text}. Caller forwards to a Haiku spawn that
    rates substance: "is this section providing real value or surface fluff?"
    Determinism allows reproducible CI.
    """
    import random
    rng = random.Random(rng_seed)
    keys = sorted(sections.keys())
    if len(keys) <= sample_size:
        return dict(sections)
    sampled = rng.sample(keys, sample_size)
    return {k: sections[k] for k in sampled}


def aggregate_failures(
    results: list[tuple[bool, str | None]],
    *,
    name: str,
) -> dict:
    """Combine multiple sub-checks into a single validator-shaped dict."""
    failures = [msg for ok, msg in results if not ok and msg]
    return {
        "validator": name,
        "verdict": "BLOCK" if failures else "PASS",
        "failures": failures,
        "checks_run": len(results),
        "checks_passed": sum(1 for ok, _ in results if ok),
    }
