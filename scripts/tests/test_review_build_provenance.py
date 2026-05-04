"""
R7-D Task 6 — Tests for review preflight build provenance audit (G6+G8).

Codex GPT-5.5 audit (2026-05-05) found commands/vg/_shared/review/preflight.md
REQUIRED_ARTIFACTS list omitted both:
  - G8: BUILD-LOG/index.md (R2 per-task split)
  - G6: build.completed event in events.db (R6 single-spawn / pipeline finish)

Without the audit, /vg:review can run against a half-finished build and produce
false-PASS verdicts on UNREACHABLE goals.

Coverage (6 cases):

  Preflight wiring (4 textual assertions on preflight.md content):
    - test_preflight_audits_build_log_index   (`BUILD-LOG/index.md` referenced)
    - test_preflight_audits_build_completed_event (`build.completed` queried)
    - test_preflight_blocks_override_without_reason (override-reason guard)
    - test_preflight_logs_override_debt_on_skip (telemetry + debt write)

  Frontmatter wiring (2 wiring assertions):
    - test_review_md_frontmatter_has_override_flag
    - test_preflight_allowlist_has_override_flag

The textual approach (rather than spinning bash subprocesses around the
preflight.md fragment) is the same approach used by Tier 2 tests in this
repo for skill-doc-as-source-of-truth files. The bash logic itself is
covered indirectly: the file is included by /vg:review at runtime via the
slim entry's load chain.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT_MD = REPO_ROOT / "commands" / "vg" / "_shared" / "review" / "preflight.md"
REVIEW_MD = REPO_ROOT / "commands" / "vg" / "review.md"


# ─── Preflight content tests ─────────────────────────────────────────


def _load_preflight() -> str:
    assert PREFLIGHT_MD.exists(), f"preflight.md missing at {PREFLIGHT_MD}"
    return PREFLIGHT_MD.read_text(encoding="utf-8")


def _extract_provenance_block(text: str) -> str:
    """Slice out the build-provenance audit block.

    The block is delimited by the section header
    'Build provenance audit — R7-D Task 6' on top and the next section
    'Matrix staleness check' below.
    """
    start_marker = "**Build provenance audit — R7-D Task 6"
    end_marker = "**Matrix staleness check"
    start = text.find(start_marker)
    assert start >= 0, "Build provenance audit section missing from preflight.md"
    end = text.find(end_marker, start)
    assert end > start, "Matrix staleness check section missing after provenance audit"
    return text[start:end]


def test_preflight_audits_build_log_index():
    """G8: BUILD-LOG/index.md existence must be checked in the audit block."""
    block = _extract_provenance_block(_load_preflight())
    assert "BUILD-LOG/index.md" in block, (
        "Build provenance audit must reference BUILD-LOG/index.md (G8 — R2 per-task split)"
    )
    # Must use a -f file-existence test, not just narration
    assert re.search(r'\[\s*!\s+-f\s+"\$\{PHASE_DIR\}/BUILD-LOG/index\.md"\s*\]', block), (
        "Build provenance audit must use `[ ! -f \"${PHASE_DIR}/BUILD-LOG/index.md\" ]` "
        "to gate on the file's existence"
    )


def test_preflight_audits_build_completed_event():
    """G6: build.completed event must be queried via vg-orchestrator query-events."""
    block = _extract_provenance_block(_load_preflight())
    # query-events command must be invoked
    assert "vg-orchestrator query-events" in block, (
        "Build provenance audit must call `vg-orchestrator query-events` to read events.db"
    )
    # Filter must be event-type=build.completed scoped to the phase
    assert re.search(r'--event-type\s+"build\.completed"', block), (
        "query-events call must filter on `--event-type \"build.completed\"`"
    )
    assert re.search(r'--phase\s+"\$\{PHASE_NUMBER\}"', block), (
        "query-events call must scope to the current phase via --phase"
    )


def test_preflight_blocks_override_without_reason():
    """--allow-missing-build-provenance without --override-reason → exit 1."""
    block = _extract_provenance_block(_load_preflight())
    # Override path must require --override-reason
    assert re.search(
        r'\[\[\s*!\s*"\$ARGUMENTS"\s*=~\s*--override-reason\s*\]\]',
        block,
    ), (
        "Override branch must check for --override-reason in $ARGUMENTS via "
        "`[[ ! \"$ARGUMENTS\" =~ --override-reason ]]`"
    )
    assert "--allow-missing-build-provenance requires --override-reason" in block, (
        "Override-without-reason path must print a hard-block message"
    )
    # Must exit 1 in the no-reason path
    no_reason_section = block[block.find("--allow-missing-build-provenance requires"):]
    assert re.search(r'\bexit\s+1\b', no_reason_section), (
        "Override-without-reason path must `exit 1`"
    )


def test_preflight_logs_override_debt_on_skip():
    """When override accepted: emit event + log debt + register override."""
    block = _extract_provenance_block(_load_preflight())
    # Telemetry event
    assert "review.build_provenance_skipped" in block, (
        "Override path must emit `review.build_provenance_skipped` telemetry"
    )
    # Override registration via vg-orchestrator override
    assert re.search(
        r'vg-orchestrator override\s+\\?\s*--flag\s+"--allow-missing-build-provenance"',
        block,
    ), (
        "Override path must call `vg-orchestrator override --flag "
        "\"--allow-missing-build-provenance\"`"
    )
    # Override-debt log helper
    assert "log_override_debt" in block, (
        "Override path must call `log_override_debt` helper for register entry"
    )
    assert "review-missing-build-provenance" in block, (
        "Override-debt entry must use stable id `review-missing-build-provenance`"
    )


# ─── Frontmatter wiring tests ────────────────────────────────────────


def test_review_md_frontmatter_has_override_flag():
    """commands/vg/review.md `forbidden_without_override` must include
    `--allow-missing-build-provenance`."""
    text = REVIEW_MD.read_text(encoding="utf-8")
    assert "forbidden_without_override:" in text, (
        "review.md missing `forbidden_without_override:` block"
    )
    assert (
        '"--allow-missing-build-provenance"' in text
        or "'--allow-missing-build-provenance'" in text
        or "- --allow-missing-build-provenance" in text
    ), (
        "review.md `forbidden_without_override` does not list "
        "`--allow-missing-build-provenance`"
    )


def test_preflight_allowlist_has_override_flag():
    """commands/vg/_shared/review/preflight.md case-statement that parses
    flags must accept `--allow-missing-build-provenance` (so it is not
    silently dropped before override-debt logging)."""
    text = _load_preflight()
    # The flag must appear in the case-statement allowlist
    assert "--allow-missing-build-provenance)" in text, (
        "preflight.md flag-parser case-statement must include "
        "`--allow-missing-build-provenance) ALLOW_MISSING_BUILD_PROVENANCE=1 ;;` — "
        "without it, the flag is silently dropped before override-debt logging"
    )
    assert "ALLOW_MISSING_BUILD_PROVENANCE" in text, (
        "preflight.md must declare ALLOW_MISSING_BUILD_PROVENANCE env var "
        "(initialized + exported alongside other override flags)"
    )
