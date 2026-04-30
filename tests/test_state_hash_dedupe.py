"""State-hash dedupe tests for paginated views (Task 29, v2.40.0).

Fixture state-hash-paginated/ holds three scan files for the same logical
view (?page=1, page=2, page=3). The state-hash dedupe contract states that
``page=1`` is probed, then ``page=2`` and ``page=3`` collapse to a state-hash
hit because the canonical view shape is identical.

State hash is currently scoped to the design doc — Phase 1.E ships fixture
+ test scaffolding so the v2.41 implementation has a regression target.

Coverage emitted now (passing today):
  - canonicalize_url.canonicalize() correctly preserves ``page`` (it is NOT
    a volatile param) so the URL itself differentiates the three pages.
  - The three scan files share the same view path stem and identical clickable
    structure, modulo the page query string, which is the input the future
    state-hash function will hash over.

Coverage gated to v2.41 (skipped today):
  - recursion.state_hash_hit telemetry counter increments by 2 across the
    three-page run. Marked ``pytest.skip`` until the state-hash module
    lands. Test stays in tree as a known-deferred regression hook.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "state-hash-paginated"

# Import scripts/canonicalize_url.py as a module.
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import canonicalize_url  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture sanity
# ---------------------------------------------------------------------------
def test_state_hash_fixture_well_formed() -> None:
    assert FIXTURE.is_dir()
    for name in ("scan-page1.json", "scan-page2.json", "scan-page3.json",
                 ".phase-profile", "CRUD-SURFACES.md", "ENV-CONTRACT.md",
                 "SUMMARY.md"):
        assert (FIXTURE / name).is_file(), f"missing {name}"


# ---------------------------------------------------------------------------
# canonicalize_url contract: ?page= is NOT volatile
# ---------------------------------------------------------------------------
def test_canonicalize_preserves_page_query() -> None:
    """page is a navigation key, not a session token — must be kept."""
    url1 = canonicalize_url.canonicalize("https://x.com/admin/users?page=1")
    url2 = canonicalize_url.canonicalize("https://x.com/admin/users?page=2")
    assert url1 != url2, "page param must distinguish pages until state-hash collapses"
    assert "page=1" in url1
    assert "page=2" in url2


# ---------------------------------------------------------------------------
# State-hash contract — fixture pages share the same logical view shape
# ---------------------------------------------------------------------------
def _view_shape_hash(scan_path: Path) -> str:
    """Compute a deterministic shape signature: element classes + count.

    This is a stand-in for the future state-hash that the v2.41 implementation
    will replace with a structural digest. The point is: all three scan files
    yield the same shape today, proving the fixture is well-formed for
    state-hash dedupe coverage when the implementation lands.
    """
    data = json.loads(scan_path.read_text(encoding="utf-8"))
    sig_parts = sorted([
        f"results:{len(data.get('results', []))}",
        f"forms:{len(data.get('forms', []))}",
    ])
    return hashlib.sha256("|".join(sig_parts).encode("utf-8")).hexdigest()[:12]


def test_three_pages_share_view_shape() -> None:
    h1 = _view_shape_hash(FIXTURE / "scan-page1.json")
    h2 = _view_shape_hash(FIXTURE / "scan-page2.json")
    h3 = _view_shape_hash(FIXTURE / "scan-page3.json")
    assert h1 == h2 == h3, (
        f"fixture pages must share view shape (got {h1}, {h2}, {h3}) — "
        "without that, the state-hash dedupe target is invalid."
    )


# ---------------------------------------------------------------------------
# Telemetry assertion — DEFERRED to v2.41 (state-hash module unimplemented)
# ---------------------------------------------------------------------------
def test_state_hash_hit_telemetry_emitted() -> None:
    """Future contract: probing 3 same-shape pages → 2 recursion.state_hash_hit events.

    Skipped today because the state-hash module has not yet been wired into
    spawn_recursive_probe.py. Tracked as a deferred regression hook so v2.41
    work has a failing test to target.
    """
    pytest.skip(
        "state-hash module is design-only in v2.40 — see "
        "docs/plans/2026-04-30-v2.40-recursive-lens-probe.md §State hash dedupe."
    )
