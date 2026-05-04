"""R6 Task 8 — Adversarial agents fail-closed (scope challenger + expander).

Per Codex audit (4/4 CRITICAL): silent skip on adversarial subagent crash
defeats the anti-rationalization purpose. If challenger crashed BECAUSE of
a real issue with the answer, treating it as no-issue means the gap goes
undetected.

This test pins the fail-closed contract on both crash sites in
`commands/vg/_shared/scope/discussion-overview.md` plus their wiring in
the slim entry frontmatter and the preflight allowlist.
"""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DISCUSSION = REPO / "commands" / "vg" / "_shared" / "scope" / "discussion-overview.md"
PREFLIGHT = REPO / "commands" / "vg" / "_shared" / "scope" / "preflight.md"
SCOPE_SLIM = REPO / "commands" / "vg" / "scope.md"


@pytest.fixture(scope="module")
def discussion_body() -> str:
    return DISCUSSION.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def preflight_body() -> str:
    return PREFLIGHT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def slim_body() -> str:
    return SCOPE_SLIM.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Site 1: Challenger crash handler — must emit telemetry + log debt + block
# ---------------------------------------------------------------------------


def test_challenger_crash_emits_event(discussion_body: str) -> None:
    """Challenger crash MUST emit `scope.challenger_crashed` telemetry event."""
    assert 'emit-event' in discussion_body
    assert '"scope.challenger_crashed"' in discussion_body, (
        "Challenger crash site must emit `scope.challenger_crashed` event "
        "(real signal, not noise)."
    )


def test_challenger_crash_requires_skip_flag(discussion_body: str) -> None:
    """Challenger crash MUST block unless --skip-challenger-crash provided."""
    assert "--skip-challenger-crash" in discussion_body
    # Block branch — exit 1 with actionable error
    assert "Anti-rationalization guard requires explicit acknowledgment." in discussion_body


def test_challenger_crash_skip_requires_override_reason(discussion_body: str) -> None:
    """--skip-challenger-crash MUST be paired with --override-reason."""
    # Find the challenger block by anchor and assert pairing within it
    anchor = "scope.challenger_crashed"
    idx = discussion_body.index(anchor)
    # Window through the next ~80 lines covers the full handler body
    window = discussion_body[idx : idx + 3000]
    assert "--skip-challenger-crash requires --override-reason" in window


def test_challenger_crash_logs_override_debt(discussion_body: str) -> None:
    """Override path MUST call log_override_debt with `scope-challenger-crashed` slug."""
    assert "log_override_debt" in discussion_body
    assert "scope-challenger-crashed" in discussion_body, (
        "Challenger crash override path must log debt with `scope-challenger-crashed` slug."
    )


# ---------------------------------------------------------------------------
# Site 2: Expander crash handler — same pattern, different identifiers
# ---------------------------------------------------------------------------


def test_expander_crash_emits_event(discussion_body: str) -> None:
    """Expander crash MUST emit `scope.expander_crashed` telemetry event."""
    assert '"scope.expander_crashed"' in discussion_body, (
        "Expander crash site must emit `scope.expander_crashed` event."
    )


def test_expander_crash_requires_skip_flag(discussion_body: str) -> None:
    """Expander crash MUST block unless --skip-expander-crash provided."""
    assert "--skip-expander-crash" in discussion_body
    # Both crash handlers should share the same anti-rationalization message
    assert discussion_body.count("Anti-rationalization guard requires explicit acknowledgment.") >= 2


def test_expander_crash_skip_requires_override_reason(discussion_body: str) -> None:
    """--skip-expander-crash MUST be paired with --override-reason."""
    anchor = "scope.expander_crashed"
    idx = discussion_body.index(anchor)
    window = discussion_body[idx : idx + 3000]
    assert "--skip-expander-crash requires --override-reason" in window


def test_expander_crash_logs_override_debt(discussion_body: str) -> None:
    """Override path MUST call log_override_debt with `scope-expander-crashed` slug."""
    assert "scope-expander-crashed" in discussion_body, (
        "Expander crash override path must log debt with `scope-expander-crashed` slug."
    )


# ---------------------------------------------------------------------------
# Frontmatter / preflight wiring — flags must be reachable + tracked
# ---------------------------------------------------------------------------


def test_slim_frontmatter_lists_both_skip_flags(slim_body: str) -> None:
    """Both override flags MUST appear in scope.md `forbidden_without_override`."""
    # Locate the forbidden_without_override block
    assert "forbidden_without_override:" in slim_body
    fwo_idx = slim_body.index("forbidden_without_override:")
    # Window covers the YAML list before the closing `---`
    yaml_end = slim_body.index("---", fwo_idx)
    fwo_block = slim_body[fwo_idx:yaml_end]
    assert '"--skip-challenger-crash"' in fwo_block, (
        "scope.md frontmatter forbidden_without_override must list --skip-challenger-crash."
    )
    assert '"--skip-expander-crash"' in fwo_block, (
        "scope.md frontmatter forbidden_without_override must list --skip-expander-crash."
    )


def test_preflight_allowlists_both_skip_flags(preflight_body: str) -> None:
    """Both flags MUST be in preflight.md case-statement allowlist (not silently rejected)."""
    assert "--skip-challenger-crash)" in preflight_body, (
        "preflight.md case-statement must accept --skip-challenger-crash "
        "(otherwise the unknown-flag branch rejects it before discussion runs)."
    )
    assert "--skip-expander-crash)" in preflight_body, (
        "preflight.md case-statement must accept --skip-expander-crash."
    )
