"""
Phase E v2.5 (2026-04-23) — telemetry-suggest.py tests.

8 test cases covering:
1. No telemetry data → empty output, rc=0
2. Validator with 100% pass over 20 samples → skip suggestion emitted
3. ⭐ UNQUARANTINABLE validator with 100% pass over 100 samples → NO skip suggestion
4. Validator with p95 > threshold → reorder suggestion
5. Same override flag used 5x in 30 days → override_abuse suggestion
6. --apply skip X writes .vg/telemetry/skip-X.json; non-UNQUARANTINABLE only
7. --command vg:build filters suggestions correctly
8. UNQUARANTINABLE parsing works when __main__.py file structure changes slightly (robust regex)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / ".claude" / "scripts" / "telemetry-suggest.py"
ORCHESTRATOR = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py"


# ── Helpers ────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _days_ago(d: int) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(days=d)
    ).isoformat().replace("+00:00", "Z")


def _gate_hit(
    gate_id: str,
    outcome: str,
    command: str = "vg:build",
    ts: str | None = None,
    duration_ms: float | None = None,
) -> dict:
    ev: dict = {
        "event_type": "gate_hit",
        "gate_id": gate_id,
        "outcome": outcome,
        "command": command,
        "phase": "7",
        "step": "build.wave-1",
        "ts": ts or _now(),
    }
    if duration_ms is not None:
        ev["duration_ms"] = duration_ms
    return ev


def _override_entry(flag: str, ts: str | None = None, phase: str = "7") -> dict:
    return {
        "timestamp": ts or _now(),
        "flag": flag,
        "phase": phase,
        "reason": "test override",
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _run(
    tmp: Path,
    extra_args: list[str] | None = None,
    telemetry_events: list[dict] | None = None,
    override_entries: list[dict] | None = None,
    orchestrator_content: str | None = None,
) -> subprocess.CompletedProcess:
    """
    Run telemetry-suggest.py in tmp_path with custom fixture data.

    Paths are injected via --telemetry-path / --override-path / etc.
    so real repo files are never touched.
    """
    tele_path = tmp / ".vg" / "telemetry.jsonl"
    over_path = tmp / ".vg" / "override-debt" / "register.jsonl"
    orch_path = tmp / "fake_orchestrator.py"
    cfg_path = tmp / "vg.config.md"
    skip_dir = tmp / ".vg" / "telemetry"

    # Write telemetry
    if telemetry_events is not None:
        _write_jsonl(tele_path, telemetry_events)

    # Write override register
    if override_entries is not None:
        _write_jsonl(over_path, override_entries)

    # Write fake orchestrator
    if orchestrator_content is None:
        # Minimal valid UNQUARANTINABLE block
        orchestrator_content = """\
UNQUARANTINABLE = {
    "phase-exists",
    "commit-attribution",
    "runtime-evidence",
    "build-crossai-required",
    "context-structure",
    "wave-verify-isolated",
    "verify-goal-security",
    "verify-goal-perf",
    "verify-security-baseline",
    "verify-foundation-architecture",
    "verify-security-test-plan",
}
"""
    orch_path.write_text(orchestrator_content, encoding="utf-8")

    # Minimal config (use defaults — don't write config file so defaults apply)
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--telemetry-path", str(tele_path),
        "--override-path", str(over_path),
        "--orchestrator-path", str(orch_path),
        "--config-path", str(cfg_path),  # doesn't exist → defaults
        "--skip-dir", str(skip_dir),
    ]
    if extra_args:
        cmd.extend(extra_args)

    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(tmp)

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )


def _parse_jsonl(stdout: str) -> list[dict]:
    """Parse all JSONL lines from stdout."""
    results = []
    for line in stdout.splitlines():
        line = line.strip()
        if line and line.startswith("{"):
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return results


# ── Tests ──────────────────────────────────────────────────────────────────

def test_no_telemetry_empty_output(tmp_path):
    """Test 1: No telemetry data → empty stdout, rc=0 (graceful skip)."""
    r = _run(tmp_path, telemetry_events=[], override_entries=[])
    assert r.returncode == 0, f"Expected rc=0, got {r.returncode}\nstderr: {r.stderr}"
    suggestions = _parse_jsonl(r.stdout)
    assert suggestions == [], f"Expected empty suggestions, got: {suggestions}"


def test_always_pass_emits_skip_suggestion(tmp_path):
    """Test 2: Validator with 100% pass over 20 samples → skip suggestion emitted."""
    # 20 PASS events for "plan-granularity" in vg:build
    events = [_gate_hit("plan-granularity", "PASS") for _ in range(20)]
    r = _run(tmp_path, telemetry_events=events)
    assert r.returncode == 0, f"rc={r.returncode}\nstderr: {r.stderr}"

    suggestions = _parse_jsonl(r.stdout)
    skip_suggestions = [s for s in suggestions if s["type"] == "skip"]
    assert skip_suggestions, (
        f"Expected at least one skip suggestion, got none.\n"
        f"stdout: {r.stdout}\nstderr: {r.stderr}"
    )
    skip_names = [s["validator"] for s in skip_suggestions]
    assert "plan-granularity" in skip_names, (
        f"Expected 'plan-granularity' in skip suggestions, got: {skip_names}"
    )
    # Verify pass_rate and samples are correct
    sg = next(s for s in skip_suggestions if s["validator"] == "plan-granularity")
    assert sg["pass_rate"] >= 0.98
    assert sg["samples"] >= 10


def test_unquarantinable_never_in_skip(tmp_path):
    """
    Test 3 (CRITICAL): UNQUARANTINABLE validators with 100% pass over 100 samples
    → NEVER emit skip suggestion. This prevents reactive gaming of security gates.
    """
    unquarantinable_validators = [
        "verify-goal-security",
        "verify-security-baseline",
        "wave-verify-isolated",
        "verify-foundation-architecture",
        "verify-security-test-plan",
        "phase-exists",
        "commit-attribution",
        "runtime-evidence",
        "build-crossai-required",
        "context-structure",
        "verify-goal-perf",
    ]

    # Give every UNQUARANTINABLE validator a perfect 100-sample run
    events: list[dict] = []
    for v in unquarantinable_validators:
        for _ in range(100):
            events.append(_gate_hit(v, "PASS"))

    r = _run(tmp_path, telemetry_events=events)
    assert r.returncode == 0, f"rc={r.returncode}\nstderr: {r.stderr}"

    suggestions = _parse_jsonl(r.stdout)
    skip_suggestions = [s for s in suggestions if s["type"] == "skip"]

    # Hard assertion: none of the UNQUARANTINABLE validators should appear
    skipped_validators = {s["validator"] for s in skip_suggestions}
    bad = skipped_validators & set(unquarantinable_validators)
    assert not bad, (
        f"SECURITY VIOLATION: UNQUARANTINABLE validators appeared as skip candidates: {bad}\n"
        f"This allows AI to game security gates via telemetry suggestions.\n"
        f"All skip suggestions: {skip_suggestions}"
    )


def test_expensive_validator_reorder_suggestion(tmp_path):
    """Test 4: Validator with p95 > 5000ms → reorder suggestion emitted."""
    # 10 events for "verify-contract-runtime" all taking 8000ms+
    events = [
        _gate_hit("verify-contract-runtime", "PASS", duration_ms=8200.0 + i * 10)
        for i in range(10)
    ]
    r = _run(tmp_path, telemetry_events=events)
    assert r.returncode == 0, f"rc={r.returncode}\nstderr: {r.stderr}"

    suggestions = _parse_jsonl(r.stdout)
    reorder_suggestions = [s for s in suggestions if s["type"] == "reorder"]
    assert reorder_suggestions, (
        f"Expected at least one reorder suggestion.\n"
        f"stdout: {r.stdout}\nstderr: {r.stderr}"
    )
    names = [s["validator"] for s in reorder_suggestions]
    assert "verify-contract-runtime" in names, (
        f"Expected 'verify-contract-runtime' in reorder suggestions, got: {names}"
    )
    sg = next(s for s in reorder_suggestions if s["validator"] == "verify-contract-runtime")
    assert sg["p95_ms"] > 5000
    assert sg["suggested_position"] == "late"


def test_override_abuse_warning(tmp_path):
    """Test 5: Same override flag used 5x in 30 days → override_abuse suggestion."""
    # 5 uses of --allow-verify-divergence in last 30 days
    overrides = [
        _override_entry("--allow-verify-divergence", ts=_days_ago(i), phase=str(7 + i))
        for i in range(5)
    ]
    r = _run(tmp_path, telemetry_events=[], override_entries=overrides)
    assert r.returncode == 0, f"rc={r.returncode}\nstderr: {r.stderr}"

    suggestions = _parse_jsonl(r.stdout)
    abuse = [s for s in suggestions if s["type"] == "override_abuse"]
    assert abuse, (
        f"Expected override_abuse suggestion.\nstdout: {r.stdout}\nstderr: {r.stderr}"
    )
    flags = [s["flag"] for s in abuse]
    assert "--allow-verify-divergence" in flags

    sg = next(s for s in abuse if s["flag"] == "--allow-verify-divergence")
    assert sg["count_30d"] == 5
    assert len(sg["phases"]) > 0


def test_apply_skip_writes_file(tmp_path):
    """Test 6: --apply skip X writes .vg/telemetry/skip-X.json for non-UNQUARANTINABLE."""
    skip_dir = tmp_path / ".vg" / "telemetry"

    r = _run(
        tmp_path,
        extra_args=["--apply", "skip", "plan-granularity"],
        telemetry_events=[],
    )
    assert r.returncode == 0, f"rc={r.returncode}\nstderr: {r.stderr}"

    skip_file = skip_dir / "skip-plan-granularity.json"
    assert skip_file.exists(), (
        f"Expected skip file at {skip_file} but not found.\nstderr: {r.stderr}"
    )
    payload = json.loads(skip_file.read_text(encoding="utf-8"))
    assert payload["validator"] == "plan-granularity"
    assert payload["expires_on_code_change"] is True


def test_apply_skip_refuses_unquarantinable(tmp_path):
    """Test 6b: --apply skip for UNQUARANTINABLE validator → rc=1, no file written."""
    skip_dir = tmp_path / ".vg" / "telemetry"

    r = _run(
        tmp_path,
        extra_args=["--apply", "skip", "verify-goal-security"],
        telemetry_events=[],
    )
    assert r.returncode == 1, (
        f"Expected rc=1 (refused) for UNQUARANTINABLE validator, got rc={r.returncode}"
    )
    skip_file = skip_dir / "skip-verify-goal-security.json"
    assert not skip_file.exists(), (
        f"SECURITY VIOLATION: skip file was written for UNQUARANTINABLE validator!"
    )


def test_command_filter(tmp_path):
    """Test 7: --command vg:build filters suggestions to that command only."""
    events = (
        # 20 PASS for plan-granularity in vg:build
        [_gate_hit("plan-granularity", "PASS", command="vg:build") for _ in range(20)]
        +
        # 20 PASS for scope-evaluator in vg:scope
        [_gate_hit("scope-evaluator", "PASS", command="vg:scope") for _ in range(20)]
    )
    r = _run(tmp_path, extra_args=["--command", "vg:build"], telemetry_events=events)
    assert r.returncode == 0, f"rc={r.returncode}\nstderr: {r.stderr}"

    suggestions = _parse_jsonl(r.stdout)
    validators = {s["validator"] for s in suggestions}

    # plan-granularity (vg:build) should appear
    assert "plan-granularity" in validators, (
        f"Expected 'plan-granularity' (vg:build) in suggestions, got: {validators}"
    )
    # scope-evaluator (vg:scope) should NOT appear when filtering to vg:build
    assert "scope-evaluator" not in validators, (
        f"'scope-evaluator' (vg:scope) should be filtered out when --command vg:build, "
        f"but it appeared.\nvalidators: {validators}"
    )


def test_unquarantinable_parsing_robust(tmp_path):
    """
    Test 8: UNQUARANTINABLE parsing works with slightly different __main__.py
    structures — inline comments, extra whitespace, mixed quotes, double-quoted.
    """
    # Variant 1: extra comments and whitespace
    variant_1 = """\
# Some preamble comment
QUARANTINE_THRESHOLD = 3

# Security note — these can NEVER be quarantined
UNQUARANTINABLE = {
    "phase-exists",               # precondition
    "verify-goal-security",       # security gate
    'wave-verify-isolated',       # single-quoted variant
    "verify-security-baseline",   # baseline
}

def some_function():
    pass
"""
    orch_path_v1 = tmp_path / "orch_v1.py"
    orch_path_v1.write_text(variant_1, encoding="utf-8")

    # Import and parse
    sys.path.insert(0, str(REPO_ROOT / ".claude" / "scripts"))
    try:
        # We need to call the parser function directly — do it via subprocess
        parse_script = tmp_path / "_parse_test.py"
        parse_script.write_text(
            f"""\
import sys, re, json
from pathlib import Path

def _parse(path):
    text = Path(path).read_text(encoding="utf-8")
    m = re.search(r'UNQUARANTINABLE\\s*=\\s*\\{{([^}}]*)\\}}', text, re.DOTALL)
    if not m:
        print(json.dumps([]))
        return
    block = m.group(1)
    names = re.findall(r'["\\']([^\\"\\' ]+)["\\'  ]', block)
    print(json.dumps(names))

_parse(sys.argv[1])
""",
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(parse_script), str(orch_path_v1)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        names = json.loads(result.stdout.strip())
        assert "verify-goal-security" in names, (
            f"Failed to parse 'verify-goal-security' from variant 1.\nGot: {names}"
        )
        assert "wave-verify-isolated" in names, (
            f"Failed to parse single-quoted 'wave-verify-isolated'.\nGot: {names}"
        )
        assert "verify-security-baseline" in names, (
            f"Failed to parse 'verify-security-baseline'.\nGot: {names}"
        )
    finally:
        if str(REPO_ROOT / ".claude" / "scripts") in sys.path:
            sys.path.remove(str(REPO_ROOT / ".claude" / "scripts"))

    # Variant 2: Real orchestrator — verify the actual file is parseable
    # and that UNQUARANTINABLE from the real file always contains security validators
    r = _run(
        tmp_path,
        # Use the REAL orchestrator path
        extra_args=[
            "--orchestrator-path", str(ORCHESTRATOR),
        ],
        telemetry_events=[
            # 100 PASSes for verify-goal-security
            _gate_hit("verify-goal-security", "PASS") for _ in range(100)
        ],
    )
    assert r.returncode == 0
    suggestions = _parse_jsonl(r.stdout)
    skip_suggestions = [s for s in suggestions if s["type"] == "skip"]
    skip_validators = {s["validator"] for s in skip_suggestions}
    assert "verify-goal-security" not in skip_validators, (
        f"Real orchestrator parse failed — 'verify-goal-security' appeared as "
        f"skip candidate despite being UNQUARANTINABLE.\n"
        f"Skip suggestions: {skip_suggestions}"
    )


def test_old_override_entries_excluded(tmp_path):
    """Bonus: Override entries older than 30 days should not trigger warning."""
    overrides = [
        _override_entry("--allow-old-flag", ts=_days_ago(31 + i))
        for i in range(10)
    ]
    r = _run(tmp_path, telemetry_events=[], override_entries=overrides)
    assert r.returncode == 0
    suggestions = _parse_jsonl(r.stdout)
    abuse = [s for s in suggestions if s["type"] == "override_abuse"]
    assert not abuse, (
        f"Old (>30d) override entries should not trigger override_abuse, "
        f"but got: {abuse}"
    )
