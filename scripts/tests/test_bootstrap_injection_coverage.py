"""Bootstrap injection coverage — R9-B (codex audit 2026-05-05).

Asserts the 5 sites missing from the prior coverage audit now invoke
`bootstrap-inject.sh` (or reference `<bootstrap_rules>` / `BOOTSTRAP_RULES_BLOCK`)
so AI agents in those flows actually see promoted bootstrap rules instead of
repeating past mistakes the harness already learned.

Sites covered (tracked back to codex audit 2026-05-05):
- specs/preflight.md       — specs authoring needs rule visibility
- review/preflight.md      — review subagents (browser-discoverer, lens) need rules
- accept/preflight.md      — accept UAT builder + cleanup need rules
- accept/uat/checklist-build/overview.md — UAT builder spawn site
- debug.md                 — debug general-purpose isolated subagent
- in-scope-fix-loop.md     — auto-fix worker spawned per IN_SCOPE warning
- in-scope-fix-loop-delegation.md — delegation contract declares rule input

The integrity bar: each file must contain `bootstrap-inject` invocation OR
`<bootstrap_rules>` / `BOOTSTRAP_RULES_BLOCK` reference. Empty match in the
helper still emits a `(no project-specific rules ...)` placeholder so the
tag is always present (anti-silent-skip per
`vg_bootstrap_verify_injection`).
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMANDS = REPO_ROOT / "commands"


# (relative_path, site_label) — parametric coverage of all R9-B sites.
SITES = [
    (
        "vg/_shared/specs/preflight.md",
        "specs-preflight",
    ),
    (
        "vg/_shared/review/preflight.md",
        "review-preflight",
    ),
    (
        "vg/_shared/accept/preflight.md",
        "accept-preflight",
    ),
    (
        "vg/_shared/accept/uat/checklist-build/overview.md",
        "accept-uat-checklist-build-overview",
    ),
    (
        "vg/debug.md",
        "debug-hypothesize-and-fix",
    ),
    (
        "vg/_shared/build/in-scope-fix-loop.md",
        "in-scope-fix-loop-spawn",
    ),
    (
        "vg/_shared/build/in-scope-fix-loop-delegation.md",
        "in-scope-fix-loop-delegation",
    ),
]


@pytest.mark.parametrize("rel_path,site_label", SITES)
def test_site_has_bootstrap_injection(rel_path: str, site_label: str) -> None:
    """Each R9-B site must invoke bootstrap-inject OR reference the rules block."""
    target = COMMANDS / rel_path
    assert target.is_file(), (
        f"R9-B site missing on disk: {target} "
        f"(label={site_label}). Did the path change?"
    )
    text = target.read_text(encoding="utf-8", errors="replace")

    # Accept any of the three canonical injection markers — matches existing
    # coverage in scope/blueprint/build/test deep-probe per
    # vg_bootstrap_verify_injection in commands/vg/_shared/lib/bootstrap-inject.sh.
    has_helper_call = "bootstrap-inject.sh" in text
    has_render_block = "BOOTSTRAP_RULES_BLOCK" in text
    has_xml_tag = "<bootstrap_rules>" in text

    assert has_helper_call or has_render_block or has_xml_tag, (
        f"R9-B coverage gap at {rel_path} (label={site_label}). "
        f"Expected one of: 'bootstrap-inject.sh' source, "
        f"'BOOTSTRAP_RULES_BLOCK' rendering, or '<bootstrap_rules>' tag. "
        f"None present — AI in this flow won't see promoted rules."
    )


def test_specs_preflight_targets_specs_step() -> None:
    """specs/preflight.md should render rules with target_step='specs' so
    only specs-relevant rules surface (filter scope, avoid context bloat)."""
    text = (COMMANDS / "vg/_shared/specs/preflight.md").read_text(
        encoding="utf-8", errors="replace"
    )
    assert '"specs"' in text or "'specs'" in text, (
        "specs/preflight.md bootstrap render should pass step_name='specs' "
        "to vg_bootstrap_render_block — got no quoted 'specs' near render call"
    )


def test_review_preflight_targets_review_step() -> None:
    """review/preflight.md should target_step='review' for filtered rules."""
    text = (COMMANDS / "vg/_shared/review/preflight.md").read_text(
        encoding="utf-8", errors="replace"
    )
    assert '"review"' in text or "'review'" in text, (
        "review/preflight.md bootstrap render should pass step_name='review'"
    )


def test_accept_preflight_targets_accept_step() -> None:
    """accept/preflight.md should target_step='accept' for filtered rules."""
    text = (COMMANDS / "vg/_shared/accept/preflight.md").read_text(
        encoding="utf-8", errors="replace"
    )
    assert '"accept"' in text or "'accept'" in text, (
        "accept/preflight.md bootstrap render should pass step_name='accept'"
    )


def test_debug_targets_debug_step() -> None:
    """debug.md should target_step='debug' for filtered rules."""
    text = (COMMANDS / "vg/debug.md").read_text(
        encoding="utf-8", errors="replace"
    )
    assert '"debug"' in text or "'debug'" in text, (
        "debug.md bootstrap render should pass step_name='debug'"
    )


def test_mirror_files_in_sync() -> None:
    """For each R9-B site, the .claude/ mirror should contain the same
    injection markers as the canonical commands/ source. This guards against
    the install.sh sync drifting after edits."""
    mirror_root = REPO_ROOT / ".claude" / "commands"
    drift: list[str] = []
    for rel_path, _ in SITES:
        src = COMMANDS / rel_path
        dst = mirror_root / rel_path
        if not dst.is_file():
            drift.append(f"{rel_path}: mirror missing at {dst}")
            continue
        src_text = src.read_text(encoding="utf-8", errors="replace")
        dst_text = dst.read_text(encoding="utf-8", errors="replace")
        # We don't require byte-equality (other markers may differ); we DO
        # require that both files have the same injection presence so the
        # mirror doesn't silently drop the new injection.
        for marker in ("bootstrap-inject.sh", "BOOTSTRAP_RULES_BLOCK", "<bootstrap_rules>"):
            if (marker in src_text) != (marker in dst_text):
                drift.append(
                    f"{rel_path}: marker '{marker}' presence drift "
                    f"(src={marker in src_text}, mirror={marker in dst_text})"
                )
    assert not drift, "Mirror sync drift detected:\n" + "\n".join(drift)
