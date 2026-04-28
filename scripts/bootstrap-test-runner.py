#!/usr/bin/env python3
"""
VG Bootstrap — Fixture Test Runner (Phase A)

Runs regression fixtures in .vg/bootstrap/tests/*.yml.

Phase A scope: scenario-3 (portability) is fully runnable now.
scenario-1 (override re-validation) depends on Phase C machinery.
scenario-2 (reflector draft) depends on Phase B machinery.
Those fixtures emit SKIP (not FAIL) until their machinery ships.

Exit codes:
  0 — all runnable fixtures passed
  1 — at least one FAIL
  2 — runner error (not fixture failure)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path.cwd()
BOOTSTRAP_DIR = REPO_ROOT / ".vg" / "bootstrap"
TESTS_DIR = BOOTSTRAP_DIR / "tests"
LOADER = REPO_ROOT / ".claude" / "scripts" / "bootstrap-loader.py"

# Reuse loader's YAML parser for fixtures
sys.path.insert(0, str((REPO_ROOT / ".claude" / "scripts").resolve()))
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "bootstrap_loader", REPO_ROOT / ".claude" / "scripts" / "bootstrap-loader.py"
)
_bl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bl)


def _run_loader(env_state: dict, context_args: dict) -> dict:
    """Invoke bootstrap-loader with specific bootstrap zone + context args."""
    cmd = [sys.executable, str(LOADER), "--emit", "all"]
    for k, v in context_args.items():
        cmd.extend([f"--{k.replace('_', '-')}", str(v)])

    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(REPO_ROOT), env=env_state,
    )
    if result.returncode != 0:
        return {"_crashed": True, "_stderr": result.stderr, "_stdout": result.stdout}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"_crashed": True, "_stderr": "non-json output", "_stdout": result.stdout}


def _run_scenario3_portability(fixture: dict) -> tuple[str, str]:
    """Run portability test — empty zone → vanilla behavior intact.

    Emulate empty zone by pointing BOOTSTRAP_DIR to a temp dir. We do this by
    just moving the real zone out of the way is too destructive, so instead
    we invoke the loader logic directly with a stub BOOTSTRAP_DIR path.
    """
    import tempfile
    import os

    given = fixture.get("given", {})
    phase_meta = given.get("phase_metadata", {})

    # Stage a truly empty bootstrap zone
    with tempfile.TemporaryDirectory() as tmp:
        tmp_bootstrap = Path(tmp) / ".vg" / "bootstrap"
        tmp_bootstrap.mkdir(parents=True)
        # Empty schema dir so load_overlay returns {}, [] cleanly
        (tmp_bootstrap / "schema").mkdir()

        # Monkey-patch loader paths
        _bl.BOOTSTRAP_DIR = tmp_bootstrap
        _bl.SCHEMA_DIR = tmp_bootstrap / "schema"

        try:
            overlay, rejected = _bl.load_overlay()
            ctx = {
                "phase": {
                    "number": phase_meta.get("phase", ""),
                    "surfaces": phase_meta.get("surfaces", []),
                    "touched_paths": [],
                    "has_mutation": phase_meta.get("has_mutation", False),
                    "ui_audit_required": False,
                    "is_api_only": False,
                },
                "step": "",
                "command": "",
            }
            rules = _bl.load_rules(ctx)
            patches = _bl.load_patches(ctx, "")
        except Exception as e:
            return "FAIL", f"loader crashed: {e}"
        finally:
            # Restore paths — important because runner may chain more fixtures
            _bl.BOOTSTRAP_DIR = REPO_ROOT / ".vg" / "bootstrap"
            _bl.SCHEMA_DIR = _bl.BOOTSTRAP_DIR / "schema"

    expect = fixture.get("then", {})
    errors = []

    if expect.get("overlay_count", 0) != len(overlay):
        errors.append(f"overlay_count: expected {expect['overlay_count']} got {len(overlay)}")
    if expect.get("rules_matched", 0) != len(rules):
        errors.append(f"rules_matched: expected {expect['rules_matched']} got {len(rules)}")
    if expect.get("crashed", False):
        errors.append("expected crashed=true but got clean run")
    if expect.get("rejected_overlay_keys", 0) != len(rejected):
        errors.append(f"rejected_overlay_keys: expected {expect['rejected_overlay_keys']} got {len(rejected)}")

    if errors:
        return "FAIL", "; ".join(errors)
    return "PASS", f"empty overlay={len(overlay)} rules={len(rules)} rejected={len(rejected)}"


def _run_scenario1_playwright(fixture: dict) -> tuple[str, str]:
    """Scenario 1 — override re-validation on phase boundary.

    Stage an override with scope phase.surfaces does_not_contain 'web'.
    Invoke override-revalidate against new phase where surfaces=[web].
    Assert override marked EXPIRED and lands in `expired[]` report.
    """
    import tempfile
    from pathlib import Path as _P

    revalidator = REPO_ROOT / ".claude" / "scripts" / "override-revalidate.py"
    if not revalidator.exists():
        return "SKIP", "override-revalidate.py not present"

    given = fixture.get("given", {})
    override = given.get("override", {})
    when = fixture.get("when", {})
    phase_after = when.get("phase_changes_to", {})

    od_id = override.get("id", "OD-TEST-FIXTURE-1")
    od_flag = override.get("flag", "--skip-playwright")
    od_scope_req = override.get("scope", {}).get("required_all", [])

    # Build OVERRIDE-DEBT.md entry — revalidator expects ```yaml fenced block
    # with status: OPEN (per _YAML_BLOCK_RE + active filter in override-revalidate.py).
    lines = [
        "# VG Override Debt Register\n",
        "## Entries\n",
        "```yaml",
        f"id: {od_id}",
        f"severity: high",
        f"phase: \"{given.get('phase_metadata_initial', {}).get('phase', '07.5')}\"",
        f"step: review",
        f"flag: {od_flag}",
        f"reason: test fixture — API phase, skip playwright",
        f"gate_id: playwright-required",
        f"status: OPEN",
        "scope:",
        "  required_all:",
    ]
    for pred in od_scope_req:
        lines.append(f"    - \"{pred}\"")
    lines.append("revalidate_on:")
    lines.append("  - new_phase_starts")
    lines.append("```")
    lines.append("")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_planning = _P(tmp) / ".vg"
        tmp_planning.mkdir(parents=True)
        (tmp_planning / "OVERRIDE-DEBT.md").write_text("\n".join(lines), encoding="utf-8")

        surfaces_csv = ",".join(phase_after.get("surfaces", []))
        has_mut = str(phase_after.get("has_mutation", False)).lower()
        new_phase = phase_after.get("phase", "07.8")

        result = subprocess.run(
            [
                sys.executable, str(revalidator),
                "--planning", str(tmp_planning),
                "--phase", new_phase,
                "--surfaces", surfaces_csv,
                "--has-mutation", has_mut,
                "--emit", "report",
            ],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        if result.returncode != 0:
            return "FAIL", f"override-revalidate exit {result.returncode}: {result.stderr[:200]}"

        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError:
            return "FAIL", f"non-json output: {result.stdout[:200]}"

    expected_status = fixture.get("then", {}).get("override_status", "EXPIRED")
    expired_ids = [e.get("id") for e in report.get("expired", [])]
    carried_ids = [e.get("id") for e in report.get("carried_forward", [])]

    if expected_status == "EXPIRED" and od_id not in expired_ids:
        return "FAIL", f"expected {od_id} in expired[], got expired={expired_ids} carried={carried_ids}"
    if expected_status == "CARRIED" and od_id not in carried_ids:
        return "FAIL", f"expected {od_id} carried forward, got expired={expired_ids}"

    return "PASS", f"override {od_id} correctly EXPIRED on phase.surfaces change api→web"


def _run_scenario2_mutation_verify(fixture: dict) -> tuple[str, str]:
    """Scenario 2 — infrastructure pathway test.

    True reflector draft-quality requires Haiku spawn (LLM). This runner
    verifies the downstream wiring: if reflector DID draft a rule with
    scope=has_mutation for review step, promoting it and re-loading
    through bootstrap-loader on a review+has_mutation context MUST return it.

    Steps:
      1. Stage a temp rules/*.md file with scope.all_of=[step==review, has_mutation==true]
      2. Invoke load_rules with review+has_mutation=true context → rule matches
      3. Invoke load_rules with blueprint+has_mutation=true context → rule does NOT match
      4. Invoke load_rules with review+has_mutation=false context → rule does NOT match
    """
    import tempfile
    from pathlib import Path as _P

    given = fixture.get("given", {})
    phase_meta = given.get("phase_metadata", {})
    surfaces = phase_meta.get("surfaces", [])

    rule_yaml = """---
id: L-FIXTURE-2
title: "Verify data persistence after mutation (reload check)"
type: rule
category: missing_verification
scope:
  all_of:
    - "step == 'review'"
    - "phase.has_mutation == true"
target_step: review
action: add_reload_persistence_check
status: active
---

# Verify data persistence

After mutation toast, MUST reload and re-read data. Toast success is not proof.
"""

    with tempfile.TemporaryDirectory() as tmp:
        tmp_rules = _P(tmp) / "rules"
        tmp_rules.mkdir()
        (tmp_rules / "fixture-mutation.md").write_text(rule_yaml, encoding="utf-8")

        def ctx(step: str, has_mut: bool) -> dict:
            return {
                "phase": {
                    "number": phase_meta.get("phase", ""),
                    "surfaces": surfaces,
                    "touched_paths": [],
                    "has_mutation": has_mut,
                    "ui_audit_required": False,
                    "is_api_only": False,
                },
                "step": step,
                "command": "",
            }

        try:
            match_correct  = _bl.load_rules(ctx("review",    True),  rules_dir=tmp_rules)
            miss_wrong_step = _bl.load_rules(ctx("blueprint", True),  rules_dir=tmp_rules)
            miss_wrong_mut  = _bl.load_rules(ctx("review",    False), rules_dir=tmp_rules)
        except Exception as e:
            return "FAIL", f"load_rules crashed: {e}"

    errors = []
    if len(match_correct) != 1:
        errors.append(f"review+mutation=true expected 1 match, got {len(match_correct)}")
    if len(miss_wrong_step) != 0:
        errors.append(f"blueprint+mutation=true expected 0 match, got {len(miss_wrong_step)}")
    if len(miss_wrong_mut) != 0:
        errors.append(f"review+mutation=false expected 0 match, got {len(miss_wrong_mut)}")

    if errors:
        return "FAIL", "; ".join(errors)

    expect_ref = fixture.get("then", {}).get("candidate_scope_should_reference", "")
    if expect_ref and expect_ref not in rule_yaml:
        return "FAIL", f"fixture expects scope references '{expect_ref}' but staged rule doesn't"

    return "PASS", "has_mutation scope filtering works: 1/0/0 matches across contexts"


def _run_scenario_migrate_naming(fixture: dict) -> tuple[str, str]:
    """OHOK v2 Day 5 — verify phase-resolver.sh handles migration naming
    edge cases: canonical, zero-pad, three-level, bare dirs, exact-beats-prefix,
    non-existent phase.

    Source user report: GSD→VG migration produced phase dirs without the
    expected `NN-task-name` format (e.g., bare `00/`, `07/`). Prior
    phase-resolver.sh hardcoded `${input}-*` pattern silently failed for
    these → user manually edited downstream files. Fixture ensures fix lands.
    """
    cases = fixture.get("then", {}).get("cases", [])
    if not cases:
        return "FAIL", "fixture has no `then.cases` entries"

    resolver = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "lib" / "phase-resolver.sh"
    if not resolver.exists():
        return "FAIL", f"phase-resolver.sh missing at {resolver}"

    failures: list[str] = []
    import os as _os
    import shutil as _shutil
    env = _os.environ.copy()
    env["PHASES_DIR"] = str(REPO_ROOT / ".vg" / "phases")

    # Windows Python may pick up WSL bash before Git Bash. Prefer Git Bash
    # (MSYS) when available since skill files assume POSIX semantics there.
    bash_bin = (
        _os.environ.get("BASH_EXE")
        or _shutil.which("bash.exe")  # Git Bash on PATH
        or (_shutil.which("bash")     # WSL/POSIX bash
            if _os.name != "nt"
            or _shutil.which("bash") != r"C:\Windows\System32\bash.exe"
            else None)
        or r"C:\Program Files\Git\bin\bash.exe"
    )
    if not _os.path.isfile(bash_bin):
        return "SKIP", f"bash not found (tried BASH_EXE, Git Bash, WSL). Got: {bash_bin}"

    for case in cases:
        input_ = case.get("input", "")
        expect_rc = case.get("expect_rc")
        contains = case.get("expect_stdout_contains", "")
        not_contains = case.get("expect_stdout_not_contains", "")
        stderr_contains = case.get("expect_stderr_contains", "")
        desc = case.get("description", input_)

        # Run resolver in isolated bash process so cached session state doesn't
        # interfere with the fresh read from disk. POSIX-ify Windows path for
        # source (Git Bash accepts forward slashes).
        resolver_posix = str(resolver).replace("\\", "/")
        script = (
            f'source "{resolver_posix}" 2>&1; '
            f'resolve_phase_dir "{input_}"'
        )
        result = subprocess.run(
            [bash_bin, "-c", script],
            capture_output=True, text=True, cwd=str(REPO_ROOT), env=env, timeout=10,
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        rc = result.returncode

        if expect_rc is not None and rc != expect_rc:
            failures.append(f"{input_!r}: rc {rc} != expected {expect_rc} ({desc})")
            continue
        if contains and contains not in stdout:
            failures.append(
                f"{input_!r}: stdout missing {contains!r} "
                f"(got {stdout[:80]!r}) — {desc}"
            )
            continue
        if not_contains and not_contains in stdout:
            failures.append(
                f"{input_!r}: stdout contains forbidden {not_contains!r} "
                f"(got {stdout[:80]!r}) — {desc}"
            )
            continue
        if stderr_contains and stderr_contains not in stderr:
            failures.append(
                f"{input_!r}: stderr missing {stderr_contains!r} "
                f"(got {stderr[:80]!r}) — {desc}"
            )
            continue

    if failures:
        return "FAIL", f"{len(failures)}/{len(cases)} cases failed: " + "; ".join(failures[:3])

    return "PASS", f"all {len(cases)} naming edge cases handled correctly"


def _run_scenario_e2e_workflow(fixture: dict) -> tuple[str, str]:
    """OHOK v2 Day 6 finish — E2E smoke exercising orchestrator binary
    across pipeline commands. Not deep per-step validation (those have
    dedicated fixtures) — just "does the pipe flow without corruption".
    """
    import sqlite3
    orch = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"
    if not orch.exists():
        return "FAIL", f"orchestrator missing at {orch}"

    db_path = REPO_ROOT / ".vg" / "events.db"
    if not db_path.exists():
        return "SKIP", "events.db not initialized — run orchestrator once first"

    # Ensure no leftover active run from prior session
    subprocess.run(
        [sys.executable, str(orch), "run-abort",
         "--reason", "e2e-fixture-preflight-cleanup-min-50-chars-sentinel"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=10,
    )

    def run_cmd(args: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(orch)] + args,
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=timeout,
        )

    def count_events_since(ts_ref: str, event_pattern: str) -> int:
        conn = sqlite3.connect(str(db_path))
        try:
            r = conn.execute(
                "SELECT COUNT(*) FROM events WHERE ts > ? AND event_type LIKE ?",
                (ts_ref, event_pattern),
            ).fetchone()
            return r[0] or 0
        finally:
            conn.close()

    failures = []

    for assertion in fixture.get("then", {}).get("assertions", []):
        name = assertion.get("name", "unnamed")
        cmd_type = assertion.get("cmd", "")

        if cmd_type == "run-help":
            r = run_cmd(["--help"])
            if r.returncode != 0:
                failures.append(f"{name}: --help exit {r.returncode}")

        elif cmd_type in ("run-cycle", "run-cycle-expect-block",
                          "run-cycle-verify-validators"):
            command = assertion.get("command", "")
            phase = assertion.get("phase", "99")

            # Snapshot timestamp for event counting window
            ts_before = subprocess.run(
                [sys.executable, "-c",
                 "import datetime; print(datetime.datetime.now(datetime.timezone.utc).isoformat())"],
                capture_output=True, text=True,
            ).stdout.strip()

            r_start = run_cmd(["run-start", command, phase])
            if r_start.returncode != 0:
                failures.append(
                    f"{name}: run-start exit {r_start.returncode}: "
                    f"{r_start.stderr[:100]}"
                )
                continue

            # Check expected {cmd}.started events landed
            for expected in assertion.get("expect_events", []):
                n = count_events_since(ts_before, expected)
                if n < 1:
                    failures.append(
                        f"{name}: expected event {expected!r} not emitted"
                    )

            # Run-complete — may BLOCK (exit 2) or PASS (exit 0)
            r_complete = run_cmd(["run-complete"])
            expected_exit = assertion.get("expect_exit_on_complete")
            if expected_exit is not None and r_complete.returncode != expected_exit:
                failures.append(
                    f"{name}: run-complete exit {r_complete.returncode} "
                    f"!= expected {expected_exit}"
                )

            # Validators fired check
            for validator in assertion.get("expect_validators_fired", []):
                conn = sqlite3.connect(str(db_path))
                try:
                    r = conn.execute(
                        "SELECT COUNT(*) FROM events WHERE ts > ? "
                        "AND event_type LIKE 'validation.%' "
                        "AND payload_json LIKE ?",
                        (ts_before, f'%"validator":"{validator}"%'),
                    ).fetchone()
                    if (r[0] or 0) < 1:
                        failures.append(
                            f"{name}: validator {validator!r} didn't fire"
                        )
                finally:
                    conn.close()

            # Cleanup if requested
            if assertion.get("cleanup_abort"):
                run_cmd(["run-abort", "--reason",
                        "e2e-fixture-cleanup-min-50-chars-sentinel-padding"])

        elif cmd_type == "verify-hash-chain":
            # Ensure events.db hash chain has no NULL prev_hash except seed
            conn = sqlite3.connect(str(db_path))
            try:
                r = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE prev_hash IS NULL"
                ).fetchone()
                null_count = r[0] or 0
                if null_count > 1:
                    failures.append(
                        f"{name}: hash chain broken — {null_count} NULL prev_hash "
                        f"(expected ≤1 seed)"
                    )
            finally:
                conn.close()

    if failures:
        return "FAIL", f"{len(failures)} assertion(s) failed: " + "; ".join(failures[:3])

    assertion_count = len(fixture.get("then", {}).get("assertions", []))
    return "PASS", f"E2E pipeline smoke: {assertion_count} assertions passed"


def _run_scenario_ohok7_crossai_loop_required(fixture: dict) -> tuple[str, str]:
    """OHOK-7 — verify build-crossai-required validator enforces loop evidence.

    Dispatches 3 states via synthetic current-run.json + events.db emission:
    (1) iteration=0 + terminal=0 → expect BLOCK (crossai_loop_never_ran)
    (2) iteration=1 + terminal=0 → expect BLOCK (crossai_loop_no_terminal)
    (3) iteration=1 + terminal=1 → expect PASS

    Always uses run-abort to clean up synthetic run at end, even on failure.
    """
    orch = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"
    validator = REPO_ROOT / ".claude" / "scripts" / "validators" / \
                "build-crossai-required.py"
    if not orch.exists() or not validator.exists():
        return "FAIL", "orchestrator or validator missing"

    failures: list[str] = []
    # Preflight: ensure no leftover run
    subprocess.run(
        [sys.executable, str(orch), "run-abort",
         "--reason", "ohok7-fixture-preflight-cleanup-min-50-chars-sentinel"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=10,
    )

    # Fixture phase must resolve via find_phase_dir — pick an existing phase.
    # 14 always exists in this repo (OHOK v2 dogfood phase). Fallback to any
    # first dir matching pattern.
    phases_dir = REPO_ROOT / ".vg" / "phases"
    phase_arg = "14"
    if phases_dir.exists():
        p14 = list(phases_dir.glob("14-*")) or list(phases_dir.glob("14.*"))
        if not p14:
            # No phase 14 → use whatever first phase dir exists
            any_phase = sorted(phases_dir.iterdir())
            for d in any_phase:
                if d.is_dir() and d.name[0].isdigit():
                    phase_arg = d.name.split("-")[0]
                    break

    def run_validator() -> tuple[int, str]:
        r = subprocess.run(
            [sys.executable, str(validator), "--phase", phase_arg],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=10,
        )
        return r.returncode, r.stdout + r.stderr

    def emit(event_type: str, payload: dict) -> None:
        # OHOK-8 round-3: reserved events blocked via CLI — invoke db.append_event
        # directly (same path as orchestrator core uses internally).
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "db_mod",
            REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "db.py",
        )
        db_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(db_mod)
        current_run_file = REPO_ROOT / ".vg" / "current-run.json"
        run = json.loads(current_run_file.read_text(encoding="utf-8"))
        db_mod.append_event(
            run_id=run["run_id"],
            event_type=event_type,
            phase=run["phase"],
            command=run["command"],
            actor="orchestrator",
            outcome="INFO",
            payload=payload,
        )

    try:
        # Start synthetic vg:build run on the resolved phase
        r = subprocess.run(
            [sys.executable, str(orch), "run-start", "vg:build", phase_arg],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=10,
        )
        if r.returncode != 0:
            return "FAIL", f"run-start exit {r.returncode}: {r.stderr[:200]}"

        # State 1: no iteration events → expect BLOCK
        rc1, out1 = run_validator()
        if "crossai_loop_never_ran" not in out1:
            failures.append(
                f"state1 no-iter: expected crossai_loop_never_ran, got "
                f"{out1[:200]}"
            )

        # State 2: iteration started but no terminal → expect BLOCK (no_terminal)
        emit("build.crossai_iteration_started",
             {"iteration": 1, "max_iterations": 5})
        rc2, out2 = run_validator()
        if "crossai_loop_no_terminal" not in out2:
            failures.append(
                f"state2 iter+no-terminal: expected crossai_loop_no_terminal, "
                f"got {out2[:200]}"
            )

        # State 3: OHOK-8 requires full sequence for loop_complete to PASS.
        # Emit iteration_complete with outcome=CLEAN BEFORE loop_complete
        # (semantic check rejects terminal without preceding CLEAN iter).
        emit("build.crossai_iteration_complete",
             {"iteration": 1, "outcome": "CLEAN",
              "codex_verdict": "PASS", "gemini_verdict": "PASS",
              "block_count": 0})
        emit("build.crossai_loop_complete",
             {"iterations_completed": 1, "max_iterations": 5,
              "early_exit": True, "codex_verdict": "PASS",
              "gemini_verdict": "PASS"})
        rc3, out3 = run_validator()
        if '"verdict": "PASS"' not in out3:
            failures.append(
                f"state3 iter+terminal: expected PASS, got {out3[:300]}"
            )

        # State 4: OHOK-8 round-3 semantic check — loop_complete with
        # iteration_complete.outcome=BLOCKS_FOUND should BLOCK (premature)
        emit("build.crossai_iteration_started",
             {"iteration": 2, "max_iterations": 5})
        emit("build.crossai_iteration_complete",
             {"iteration": 2, "outcome": "BLOCKS_FOUND",
              "codex_verdict": "BLOCK", "gemini_verdict": "BLOCK",
              "block_count": 3})
        emit("build.crossai_loop_complete",
             {"iterations_completed": 2, "max_iterations": 5,
              "early_exit": True})
        rc4, out4 = run_validator()
        if "crossai_premature_complete" not in out4:
            failures.append(
                f"state4 premature-complete: expected crossai_premature_complete, "
                f"got {out4[:300]}"
            )
    finally:
        subprocess.run(
            [sys.executable, str(orch), "run-abort",
             "--reason", "ohok7-fixture-teardown-cleanup-min-50-chars-sentinel"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=10,
        )

    if failures:
        return "FAIL", "; ".join(failures[:3])
    return "PASS", (
        "validator enforces OHOK-7/8 loop: BLOCK without iterations, "
        "BLOCK without terminal, PASS with full clean sequence "
        "(iter+iter_complete.CLEAN+loop_complete), BLOCK on premature "
        "loop_complete (iter_complete.outcome=BLOCKS_FOUND)"
    )


SCENARIO_RUNNERS = {
    "scenario-3-portability-empty-zone": _run_scenario3_portability,
    "scenario-1-playwright-lazy-propagation": _run_scenario1_playwright,
    "scenario-2-toast-fake-success-mutation-verify": _run_scenario2_mutation_verify,
    "scenario-migrate-naming-edge-cases": _run_scenario_migrate_naming,
    "scenario-e2e-workflow-smoke": _run_scenario_e2e_workflow,
    "scenario-ohok7-crossai-loop-required": _run_scenario_ohok7_crossai_loop_required,
}


def main() -> int:
    if not TESTS_DIR.exists():
        print("⛔ no .vg/bootstrap/tests/ directory")
        return 2

    fixtures = sorted(TESTS_DIR.glob("*.yml"))
    if not fixtures:
        print("⚠ no fixture *.yml files found")
        return 0

    pass_n = fail_n = skip_n = 0
    print(f"Running {len(fixtures)} bootstrap fixtures...\n")

    for fx_path in fixtures:
        try:
            fx = _bl._parse_yaml(fx_path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            print(f"  ⛔ {fx_path.name}: parse error — {e}")
            fail_n += 1
            continue

        name = fx.get("name", fx_path.stem)
        runner = SCENARIO_RUNNERS.get(name)
        if runner is None:
            print(f"  ⚠ {name}: no runner registered — SKIP")
            skip_n += 1
            continue

        verdict, detail = runner(fx)
        icon = {"PASS": "✓", "FAIL": "⛔", "SKIP": "⋯"}.get(verdict, "?")
        print(f"  {icon} {name}: {verdict} — {detail}")
        if verdict == "PASS":
            pass_n += 1
        elif verdict == "FAIL":
            fail_n += 1
        else:
            skip_n += 1

    print(f"\nSummary: {pass_n} PASS, {fail_n} FAIL, {skip_n} SKIP")
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
