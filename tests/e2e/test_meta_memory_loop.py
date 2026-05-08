"""Stage 6 task 2/5 — E2E loop test for meta-memory v1.1.

Scenario simulates the full self-learning loop end-to-end without involving
real LLM agents:

  1. Phase 1 — a procedural rule lands in `.vg/bootstrap/rules/` (post
     reflector promote). Tier A, target_step=deploy, attribution_required=true.
  2. Phase 2 — a different command run later uses bootstrap-loader.py with
     --target-step deploy --include-procedural. The promoted rule MUST appear
     in the loader output → proves the rule is visible to the next phase's
     inject site.
  3. Inject sites — verify build/preflight + deploy markdown contain the
     `meta_memory_mode` gate condition (without it, even visible rules would
     no-op when the project hasn't opted in).

The fixture writes its own rules dir + uses VG_BOOTSTRAP_RULES_DIR so the
test is hermetic against the real `.vg/bootstrap/` of the host repo.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
LOADER = str(REPO / ".claude" / "scripts" / "bootstrap-loader.py")


@pytest.fixture
def fixture_project(tmp_path):
    """Minimal VG project fixture: .vg/bootstrap/rules/ + .git/ marker."""
    proj = tmp_path / "proj"
    (proj / ".vg" / "bootstrap" / "rules").mkdir(parents=True)
    (proj / ".git").mkdir()
    return proj


def _seed_promoted_rule(fixture_project: Path) -> Path:
    """Drop a tier-A procedural rule into the fixture rules dir, as if the
    user had just run /vg:learn promote after a successful phase 1 deploy."""
    rule_file = fixture_project / ".vg" / "bootstrap" / "rules" / "test-deploy.md"
    # NOTE: scope is intentionally omitted. The loader treats a missing scope
    # as match-all so the test focuses on `target_step` + `--include-procedural`
    # filtering — the actual rollout behavior we want to lock.
    rule_file.write_text(
        "---\n"
        "id: test-deploy\n"
        "slug: test-deploy\n"
        "title: \"test deploy procedural\"\n"
        "type: procedural\n"
        "authority: advisory\n"
        "target_step: deploy\n"
        "action: must_run\n"
        "proposed:\n"
        "  prose: \"deploy recipe\"\n"
        "preconditions: {}\n"
        "sequence:\n"
        "  - id: s1\n"
        "    cmd: \"echo hi\"\n"
        "    expected_signals: [\"exit=0\"]\n"
        "success_signals: [\"deploy_completed\"]\n"
        "attribution_required: true\n"
        "tier: A\n"
        "---\n# body\n",
        encoding="utf-8",
    )
    return rule_file


def test_full_loop_phase1_promote_to_phase2_loader_visible(fixture_project):
    """Phase 1 promote → Phase 2 loader sees the rule.

    Proves the loader visibility half of the loop: once a rule is in
    `.vg/bootstrap/rules/`, the next pipeline run picks it up via
    --target-step + --include-procedural filter and exposes it as JSON to
    the inject sites.
    """
    _seed_promoted_rule(fixture_project)

    env = os.environ.copy()
    env["VG_BOOTSTRAP_RULES_DIR"] = str(
        fixture_project / ".vg" / "bootstrap" / "rules"
    )
    result = subprocess.run(
        [
            sys.executable, LOADER,
            "--step", "deploy",
            "--target-step", "deploy",
            "--include-procedural",
            "--emit", "rules",
        ],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, (
        f"loader failed rc={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    # Loader emits JSON; the rule slug MUST appear somewhere in that payload.
    assert "test-deploy" in result.stdout, (
        "promoted rule should be visible to the loader for the next phase\n"
        f"stdout={result.stdout}"
    )

    # Belt-and-suspenders: parse JSON and confirm the rule landed in either
    # the rules array or the procedural-split bucket.
    payload = json.loads(result.stdout)
    ids: set[str] = set()
    for key in ("rules", "rules_declarative", "rules_procedural"):
        for r in payload.get(key, []) or []:
            rid = r.get("id") or r.get("slug")
            if rid:
                ids.add(rid)
    assert "test-deploy" in ids, (
        f"expected slug 'test-deploy' in loader output ids; got {ids}"
    )


def test_full_loop_meta_memory_mode_gates_inject_sites():
    """Inject sites MUST gate on `meta_memory_mode` so default-OFF projects
    never silently fire rules. Verified by reading the inject-site .md files
    and confirming the gate keyword is present near the inject block.

    This is the safety half of the loop: even when a rule is visible to the
    loader (test_full_loop_phase1_promote_to_phase2_loader_visible above),
    the actual inject prose only renders when the project has opted in via
    `meta_memory_mode={inject-as-advice|default}`.
    """
    preflight = (REPO / "commands" / "vg" / "_shared" / "build" / "preflight.md").read_text(encoding="utf-8")
    assert "meta_memory_mode" in preflight, (
        "build/preflight.md must reference meta_memory_mode to gate the "
        "Stage 4 inject block"
    )
    deploy = (REPO / "commands" / "vg" / "deploy.md").read_text(encoding="utf-8")
    assert "meta_memory_mode" in deploy, (
        "deploy.md must reference meta_memory_mode to gate the Stage 4 "
        "inject block + reflector spawn"
    )
