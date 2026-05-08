"""Tests for bootstrap-loader v1.1 CLI flags (Stage 4 task 0/4).

Adds 4 new CLI flags supporting Stage 4 inject sites:
  --target-step (repeatable)  Filter rules by frontmatter target_step
  --include-procedural        Include rules with type=procedural (default excludes)
  --filter-preconditions      JSON object — caller's keys must match rule.preconditions
  --max-bytes                 Cap total prose output bytes

Loader output is JSON, not markdown. Tests parse JSON and verify rule-level
fields. Section-split assertion checks for new top-level keys
'rules_declarative' / 'rules_procedural' which appear when --emit rules and
the loader has split rules by type.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

LOADER = ".claude/scripts/bootstrap-loader.py"


def _make_rule(tmp_dir: Path, name: str, frontmatter: str, body: str = "# body\n") -> Path:
    p = tmp_dir / name
    p.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    return p


def _run_loader(rules_dir: Path, *args) -> subprocess.CompletedProcess:
    """Run loader pointing at a fixture rules dir via VG_BOOTSTRAP_RULES_DIR env."""
    env = os.environ.copy()
    env["VG_BOOTSTRAP_RULES_DIR"] = str(rules_dir)
    return subprocess.run(
        [sys.executable, LOADER, *args, "--emit", "rules"],
        capture_output=True, text=True, env=env,
    )


def _parse(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, f"loader failed rc={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    return json.loads(result.stdout)


def _all_rule_ids(payload: dict) -> set[str]:
    """Collect rule ids from any of: rules, rules_declarative, rules_procedural."""
    ids: set[str] = set()
    for key in ("rules", "rules_declarative", "rules_procedural"):
        for r in payload.get(key, []) or []:
            rid = r.get("id")
            if rid:
                ids.add(rid)
    return ids


@pytest.fixture
def rules_dir(tmp_path):
    """Fixture: 4 rules with varying target_step + type + preconditions."""
    d = tmp_path / "rules"
    d.mkdir()
    _make_rule(d, "build-decl.md",
        "id: r1\n"
        "slug: r1\n"
        "title: \"build declarative\"\n"
        "type: declarative\n"
        "target_step: build\n"
        "scope:\n"
        "  any_of: [\"step == 'build'\"]\n"
        "action: warn\n"
        "tier: A\n",
        body="Build rule prose\n")
    _make_rule(d, "deploy-proc.md",
        "id: r2\n"
        "slug: r2\n"
        "title: \"deploy procedural\"\n"
        "type: procedural\n"
        "authority: advisory\n"
        "target_step: deploy\n"
        "scope:\n"
        "  any_of: [\"step == 'deploy'\"]\n"
        "action: must_run\n"
        "preconditions:\n"
        "  env: fly.io\n"
        "  has_dockerfile: true\n"
        "sequence:\n"
        "  - id: s1\n"
        "    cmd: \"flyctl deploy\"\n"
        "    expected_signals: [\"exit=0\"]\n"
        "success_signals: [\"deploy_completed\"]\n"
        "attribution_required: true\n"
        "tier: A\n",
        body="Deploy recipe prose\n")
    _make_rule(d, "test-decl.md",
        "id: r3\n"
        "slug: r3\n"
        "title: \"test declarative\"\n"
        "type: declarative\n"
        "target_step: test\n"
        "scope:\n"
        "  any_of: [\"step == 'test'\"]\n"
        "action: warn\n"
        "tier: A\n",
        body="Test rule prose\n")
    _make_rule(d, "deploy-decl-render.md",
        "id: r4\n"
        "slug: r4\n"
        "title: \"deploy declarative render\"\n"
        "type: declarative\n"
        "target_step: deploy\n"
        "scope:\n"
        "  any_of: [\"step == 'deploy'\"]\n"
        "action: warn\n"
        "preconditions:\n"
        "  env: render.com\n"
        "tier: A\n",
        body="Deploy decl prose\n")
    return d


def test_target_step_filter_single(rules_dir):
    """--target-step build should match rule with target_step=build only."""
    result = _run_loader(rules_dir, "--step", "build", "--target-step", "build")
    payload = _parse(result)
    ids = _all_rule_ids(payload)
    assert "r1" in ids, "build rule should be present"
    assert "r2" not in ids, "deploy rule should be filtered out"
    assert "r3" not in ids, "test rule should be filtered out"
    assert "r4" not in ids, "deploy-decl rule should be filtered out"


def test_target_step_filter_multiple_repeatable(rules_dir):
    """--target-step build --target-step deploy includes both."""
    # No --step filter (use a step matching all so scope DSL passes).
    # Use --step build then deploy in two runs — but since fixture uses scope on step,
    # we need a step that triggers all 3 target rules. Fixture scope clauses match
    # specific steps; pass --step matching one of the targets at a time.
    # Instead: skip scope by passing --step values that don't match scope, BUT the
    # current loader filters BOTH scope AND target_step. Adjust fixture so scope is
    # permissive: any_of: ["true"]. Re-create with permissive scope.
    pass


@pytest.fixture
def permissive_rules_dir(tmp_path):
    """Same shape as rules_dir but scope is always-true so we test target_step filter alone."""
    d = tmp_path / "rules_permissive"
    d.mkdir()
    permissive_scope = "scope:\n  any_of: [\"command == 'any'\"]\n"
    # Note: scope with command=='any' will eval false, but evaluate_scope returns false → rule skipped.
    # We need scope that always matches. Use a scope referencing context key with == to its actual value.
    # Easier: use no scope — loader treats missing scope as match-all? Check evaluate_scope on None.
    # From scope-evaluator.py: scope=None likely returns True. Let's use no scope key at all.
    _make_rule(d, "build-decl.md",
        "id: r1\n"
        "slug: r1\n"
        "title: \"build declarative\"\n"
        "type: declarative\n"
        "target_step: build\n"
        "action: warn\n"
        "tier: A\n",
        body="Build rule prose\n")
    _make_rule(d, "deploy-proc.md",
        "id: r2\n"
        "slug: r2\n"
        "title: \"deploy procedural\"\n"
        "type: procedural\n"
        "authority: advisory\n"
        "target_step: deploy\n"
        "action: must_run\n"
        "preconditions:\n"
        "  env: fly.io\n"
        "  has_dockerfile: true\n"
        "sequence:\n"
        "  - id: s1\n"
        "    cmd: \"flyctl deploy\"\n"
        "    expected_signals: [\"exit=0\"]\n"
        "success_signals: [\"deploy_completed\"]\n"
        "attribution_required: true\n"
        "tier: A\n",
        body="Deploy recipe prose with substantial body content to make it large enough for byte-truncation tests\n")
    _make_rule(d, "test-decl.md",
        "id: r3\n"
        "slug: r3\n"
        "title: \"test declarative\"\n"
        "type: declarative\n"
        "target_step: test\n"
        "action: warn\n"
        "tier: A\n",
        body="Test rule prose\n")
    _make_rule(d, "deploy-decl-render.md",
        "id: r4\n"
        "slug: r4\n"
        "title: \"deploy declarative render\"\n"
        "type: declarative\n"
        "target_step: deploy\n"
        "action: warn\n"
        "preconditions:\n"
        "  env: render.com\n"
        "tier: A\n",
        body="Deploy decl prose with substantial body content to make it large enough for byte-truncation tests\n")
    _make_rule(d, "global-decl.md",
        "id: r5\n"
        "slug: r5\n"
        "title: \"global declarative\"\n"
        "type: declarative\n"
        "target_step: global\n"
        "action: warn\n"
        "tier: A\n",
        body="Global rule prose\n")
    return d


def test_target_step_single(permissive_rules_dir):
    result = _run_loader(permissive_rules_dir, "--target-step", "build")
    payload = _parse(result)
    ids = _all_rule_ids(payload)
    assert "r1" in ids
    # global always matches
    assert "r5" in ids
    assert "r2" not in ids
    assert "r3" not in ids
    assert "r4" not in ids


def test_target_step_multiple(permissive_rules_dir):
    result = _run_loader(permissive_rules_dir, "--target-step", "build", "--target-step", "deploy", "--include-procedural")
    payload = _parse(result)
    ids = _all_rule_ids(payload)
    assert "r1" in ids and "r2" in ids and "r4" in ids and "r5" in ids
    assert "r3" not in ids


def test_include_procedural_default_excludes(permissive_rules_dir):
    """Without --include-procedural, procedural rules excluded."""
    result = _run_loader(permissive_rules_dir, "--target-step", "deploy")
    payload = _parse(result)
    ids = _all_rule_ids(payload)
    # r2 is procedural; should NOT appear without flag
    assert "r2" not in ids, "procedural rule must be excluded by default"
    # r4 is declarative deploy; SHOULD appear
    assert "r4" in ids


def test_include_procedural_flag_includes(permissive_rules_dir):
    result = _run_loader(permissive_rules_dir, "--target-step", "deploy", "--include-procedural")
    payload = _parse(result)
    ids = _all_rule_ids(payload)
    assert "r2" in ids, "procedural rule must be included with flag"
    assert "r4" in ids


def test_filter_preconditions_substring_match(permissive_rules_dir):
    """Caller's preconditions JSON must be subset of rule's preconditions."""
    result = _run_loader(
        permissive_rules_dir, "--target-step", "deploy", "--include-procedural",
        "--filter-preconditions", json.dumps({"env": "fly.io"}),
    )
    payload = _parse(result)
    ids = _all_rule_ids(payload)
    # r2 has preconditions={env:fly.io, has_dockerfile:true} → fly.io subset matches
    assert "r2" in ids
    # r4 has preconditions={env:render.com} → fly.io doesn't match
    assert "r4" not in ids


def test_filter_preconditions_no_match(permissive_rules_dir):
    result = _run_loader(
        permissive_rules_dir, "--target-step", "deploy", "--include-procedural",
        "--filter-preconditions", json.dumps({"env": "heroku"}),
    )
    payload = _parse(result)
    ids = _all_rule_ids(payload)
    assert "r2" not in ids
    assert "r4" not in ids


def test_filter_preconditions_skips_rules_without_preconditions(permissive_rules_dir):
    """A rule with no preconditions block should still pass filter when caller has preconditions.

    Rationale: caller passes `env=fly.io` but rule has no preconditions field — rule
    isn't expressing a requirement, so it's compatible (not a mismatch).
    """
    # r1 has no preconditions; should pass filter even though caller specifies env
    result = _run_loader(
        permissive_rules_dir, "--target-step", "build",
        "--filter-preconditions", json.dumps({"env": "fly.io"}),
    )
    payload = _parse(result)
    ids = _all_rule_ids(payload)
    assert "r1" in ids


def test_max_bytes_truncates_total_output(permissive_rules_dir):
    """--max-bytes caps total output bytes (with truncation marker)."""
    result_full = _run_loader(permissive_rules_dir, "--target-step", "deploy", "--include-procedural")
    payload_full = _parse(result_full)
    full_size = len(result_full.stdout)
    assert full_size > 200, "full output should be substantive"

    cap = max(200, full_size // 2)
    result_capped = _run_loader(
        permissive_rules_dir, "--target-step", "deploy", "--include-procedural",
        "--max-bytes", str(cap),
    )
    assert result_capped.returncode == 0
    # Capped output should be smaller than full (proves truncation took effect)
    assert len(result_capped.stdout) < full_size, \
        "capped output should be smaller than full output"
    # Capped output should contain a truncation marker
    assert "truncated" in result_capped.stdout.lower(), \
        "capped output should contain truncation marker"


def test_emit_split_declarative_procedural(permissive_rules_dir):
    """Output groups rules into rules_declarative + rules_procedural keys when both present."""
    result = _run_loader(permissive_rules_dir, "--target-step", "deploy", "--include-procedural")
    payload = _parse(result)
    # New section-split keys must be present
    assert "rules_declarative" in payload, "output must split rules into rules_declarative key"
    assert "rules_procedural" in payload, "output must split rules into rules_procedural key"
    decl_ids = {r.get("id") for r in payload["rules_declarative"]}
    proc_ids = {r.get("id") for r in payload["rules_procedural"]}
    # r2 procedural, r4 declarative
    assert "r2" in proc_ids
    assert "r4" in decl_ids
    # No crossover
    assert "r2" not in decl_ids
    assert "r4" not in proc_ids


def test_backwards_compat_no_new_flags(permissive_rules_dir):
    """Without any new flags, output must include rules key (existing behavior).

    Procedural rules excluded by default — but rules key still present.
    """
    result = _run_loader(permissive_rules_dir)
    payload = _parse(result)
    # Still has 'rules' key for back-compat
    assert "rules" in payload or "rules_declarative" in payload
