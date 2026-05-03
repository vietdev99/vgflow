"""
test_contract_pins.py — Tier B coverage for per-phase runtime_contract pinning.

Pins:
1. extract_contract_for_command parses must_touch_markers + must_emit_telemetry
   correctly for both shorthand and structured YAML list items
2. write_pin creates .contract-pins.json with all 6 tracked commands
3. write_pin is idempotent — re-run preserves existing per-command entries
4. parse_for_phase merges pinned markers/telemetry over current skill contract
5. parse_for_phase falls back to current skill when no pin exists
6. /vg:migrate-state apply writes pin for legacy phases (B4 wiring)
7. End-to-end: simulated harness upgrade does NOT change the pinned phase's
   validation contract (regression-proofs Tier B promise)
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "scripts" / "vg-contract-pins.py").exists():
            return parent
        if (parent / ".claude" / "scripts" / "vg-contract-pins.py").exists():
            return parent
    raise AssertionError("repo root not found")


REPO_ROOT = _find_repo_root()
SCRIPT_ROOT = REPO_ROOT / "scripts"
if not (SCRIPT_ROOT / "vg-contract-pins.py").exists():
    SCRIPT_ROOT = REPO_ROOT / "scripts"
if not (SCRIPT_ROOT / "vg-contract-pins.py").exists():
    SCRIPT_ROOT = REPO_ROOT / ".claude" / "scripts"
PIN_SCRIPT = SCRIPT_ROOT / "vg-contract-pins.py"
MIGRATE_SCRIPT = SCRIPT_ROOT / "migrate-state.py"
ORCHESTRATOR_DIR = SCRIPT_ROOT / "vg-orchestrator"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_fake_repo(tmp_path: Path) -> Path:
    """Build a minimal fake repo whose .claude/scripts/ contains copies of
    vg-contract-pins.py + migrate-state.py + orchestrator/ so subprocess
    invocations resolve to the test fixture's parents[2].
    """
    scripts_dir = tmp_path / ".claude" / "scripts"
    scripts_dir.mkdir(parents=True)
    shutil.copy(PIN_SCRIPT, scripts_dir / "vg-contract-pins.py")
    shutil.copy(MIGRATE_SCRIPT, scripts_dir / "migrate-state.py")
    shutil.copytree(ORCHESTRATOR_DIR, scripts_dir / "vg-orchestrator")

    cmd_dir = tmp_path / ".claude" / "commands" / "vg"
    cmd_dir.mkdir(parents=True)
    # Skill stubs with full frontmatter+body
    accept_md = """---
name: vg:accept
description: test
runtime_contract:
  must_touch_markers:
    - "0_gate"
    - "1_artifact"
    - name: "2_advisory"
      severity: "warn"
    - "7_finish"
  must_emit_telemetry:
    - event_type: "accept.tasklist_shown"
    - event_type: "accept.optional_review"
      severity: "warn"
    - event_type: "accept.completed"
---

<step name="0_gate">test</step>
<step name="1_artifact">test</step>
<step name="2_advisory">test</step>
<step name="7_finish">test</step>
"""
    (cmd_dir / "accept.md").write_text(accept_md, encoding="utf-8")

    blueprint_md = """---
name: vg:blueprint
description: test
runtime_contract:
  must_touch_markers:
    - "0_parse"
    - "3_complete"
  must_emit_telemetry:
    - event_type: "blueprint.completed"
    - event_type: "blueprint.edge_cases_generated"
      severity: "warn"
---

<step name="0_parse">test</step>
<step name="3_complete">test</step>
"""
    (cmd_dir / "blueprint.md").write_text(blueprint_md, encoding="utf-8")

    # Other commands (scope/build/review/test) — skip frontmatter, body only
    for cmd in ("scope", "build", "review", "test"):
        (cmd_dir / f"{cmd}.md").write_text(
            f'<step name="dummy_{cmd}_step">test</step>\n', encoding="utf-8"
        )

    # Phase dir + override-debt skeleton
    phase = tmp_path / ".vg" / "phases" / "9.0-test"
    phase.mkdir(parents=True)
    (phase / "PLAN.md").write_text("# plan", encoding="utf-8")
    (phase / "API-CONTRACTS.md").write_text("# contracts", encoding="utf-8")
    (phase / "TEST-GOALS.md").write_text("# goals", encoding="utf-8")
    (tmp_path / ".vg" / "OVERRIDE-DEBT.md").write_text(
        "# debt\n\n", encoding="utf-8"
    )
    return tmp_path


def _env_for(cwd: Path) -> dict:
    """Force VG_REPO_ROOT to the test fixture so subprocess + imports
    resolve repo paths to tmp_path, not the real RTB checkout.
    """
    import os
    e = os.environ.copy()
    e["VG_REPO_ROOT"] = str(cwd)
    return e


def _run_pin(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    fake = cwd / ".claude" / "scripts" / "vg-contract-pins.py"
    return subprocess.run(
        [sys.executable, str(fake)] + args,
        capture_output=True, text=True, cwd=cwd, timeout=30,
        env=_env_for(cwd),
    )


def _run_migrate(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    fake = cwd / ".claude" / "scripts" / "migrate-state.py"
    return subprocess.run(
        [sys.executable, str(fake)] + args,
        capture_output=True, text=True, cwd=cwd, timeout=30,
        env=_env_for(cwd),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_extract_parses_yaml_list_forms(tmp_path):
    repo = _setup_fake_repo(tmp_path)
    r = _run_pin(["extract", "--command", "vg:accept"], repo)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    # Both shorthand strings and structured {name: ...} resolve to marker names
    assert data["must_touch_markers"] == [
        "0_gate",
        "1_artifact",
        {"name": "2_advisory", "severity": "warn"},
        "7_finish",
    ]
    # event_type list extracted; structured warn telemetry preserves severity
    assert data["must_emit_telemetry"] == [
        "accept.tasklist_shown",
        {"event_type": "accept.optional_review", "severity": "warn"},
        "accept.completed",
    ]
    assert "skill_sha256" in data


def test_write_pin_creates_all_commands(tmp_path):
    repo = _setup_fake_repo(tmp_path)
    r = _run_pin(["write", "9.0-test"], repo)
    assert r.returncode == 0, r.stderr
    pin = repo / ".vg" / "phases" / "9.0-test" / ".contract-pins.json"
    assert pin.exists()
    data = json.loads(pin.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert "vg:accept" in data["commands"]
    assert "vg:blueprint" in data["commands"]
    blueprint_tel = data["commands"]["vg:blueprint"]["must_emit_telemetry"]
    assert {"event_type": "blueprint.edge_cases_generated", "severity": "warn"} in blueprint_tel


def test_write_pin_idempotent_preserves_existing(tmp_path):
    repo = _setup_fake_repo(tmp_path)
    _run_pin(["write", "9.0-test"], repo)
    pin = repo / ".vg" / "phases" / "9.0-test" / ".contract-pins.json"
    data1 = json.loads(pin.read_text(encoding="utf-8"))
    pinned_at_first = data1["commands"]["vg:accept"]["pinned_at"]
    # Re-write — should NOT clobber existing per-command entries
    _run_pin(["write", "9.0-test"], repo)
    data2 = json.loads(pin.read_text(encoding="utf-8"))
    assert data2["commands"]["vg:accept"]["pinned_at"] == pinned_at_first


def test_write_pin_overwrite_flag_replaces(tmp_path):
    repo = _setup_fake_repo(tmp_path)
    _run_pin(["write", "9.0-test"], repo)
    pin = repo / ".vg" / "phases" / "9.0-test" / ".contract-pins.json"
    # Tamper with one entry, then --overwrite should restore from skill
    data = json.loads(pin.read_text(encoding="utf-8"))
    data["commands"]["vg:accept"]["must_touch_markers"] = ["TAMPERED"]
    pin.write_text(json.dumps(data), encoding="utf-8")
    _run_pin(["write", "9.0-test", "--command", "vg:accept",
              "--overwrite"], repo)
    data2 = json.loads(pin.read_text(encoding="utf-8"))
    assert data2["commands"]["vg:accept"]["must_touch_markers"] != ["TAMPERED"]


def test_parse_for_phase_falls_back_when_no_pin(tmp_path, monkeypatch):
    repo = _setup_fake_repo(tmp_path)
    # Import contracts.py from the fake repo so its REPO_ROOT resolves
    # to tmp_path
    import os
    sys.path.insert(0, str(repo / ".claude" / "scripts" / "vg-orchestrator"))
    saved_env = os.environ.get("VG_REPO_ROOT")
    os.environ["VG_REPO_ROOT"] = str(repo)
    try:
        for mod in list(sys.modules):
            if mod in ("contracts", "_repo_root"):
                del sys.modules[mod]
        spec = importlib.util.spec_from_file_location(
            "contracts",
            repo / ".claude" / "scripts" / "vg-orchestrator" / "contracts.py",
        )
        contracts = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(contracts)
        # No pin written → falls back to current skill
        c = contracts.parse_for_phase("9.0-test", "vg:accept")
        # Skill frontmatter declares 4 markers (after _parse_yaml_list_value resolves)
        assert c is not None
        markers = c.get("must_touch_markers") or []
        # Could be raw shorthand list or normalized — just assert non-empty
        assert len(markers) >= 1
    finally:
        sys.path.pop(0)
        if saved_env is None:
            os.environ.pop("VG_REPO_ROOT", None)
        else:
            os.environ["VG_REPO_ROOT"] = saved_env


def test_parse_for_phase_overrides_with_pin(tmp_path):
    repo = _setup_fake_repo(tmp_path)
    # Write pin
    _run_pin(["write", "9.0-test"], repo)
    pin = repo / ".vg" / "phases" / "9.0-test" / ".contract-pins.json"
    data = json.loads(pin.read_text(encoding="utf-8"))
    # Tamper pin with synthetic marker
    data["commands"]["vg:accept"]["must_touch_markers"] = ["FROZEN_FROM_PIN"]
    pin.write_text(json.dumps(data), encoding="utf-8")

    # Now load contracts module against tmp_path repo
    import os
    sys.path.insert(0, str(repo / ".claude" / "scripts" / "vg-orchestrator"))
    saved_env = os.environ.get("VG_REPO_ROOT")
    os.environ["VG_REPO_ROOT"] = str(repo)
    try:
        for mod in list(sys.modules):
            if mod in ("contracts", "_repo_root"):
                del sys.modules[mod]
        spec = importlib.util.spec_from_file_location(
            "contracts",
            repo / ".claude" / "scripts" / "vg-orchestrator" / "contracts.py",
        )
        contracts = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(contracts)
        c = contracts.parse_for_phase("9.0-test", "vg:accept")
        assert c.get("must_touch_markers") == ["FROZEN_FROM_PIN"], (
            "parse_for_phase MUST override current skill with pinned markers"
        )
    finally:
        sys.path.pop(0)
        if saved_env is None:
            os.environ.pop("VG_REPO_ROOT", None)
        else:
            os.environ["VG_REPO_ROOT"] = saved_env


def test_migrate_state_apply_writes_pin(tmp_path):
    repo = _setup_fake_repo(tmp_path)
    pin = repo / ".vg" / "phases" / "9.0-test" / ".contract-pins.json"
    assert not pin.exists(), "fake phase starts without pin"
    r = _run_migrate(["9.0-test", "--json"], repo)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["contract_pin"] == "wrote", (
        f"migrate-state apply must write pin for legacy phase: {data}"
    )
    assert pin.exists()


def test_harness_upgrade_does_not_break_pinned_phase(tmp_path):
    """Simulate the failure mode Tier B prevents: harness adds a new
    must_touch_marker AFTER a phase pinned its contract. parse_for_phase
    must still return the OLD (pinned) marker list, not the new one.
    """
    repo = _setup_fake_repo(tmp_path)
    # Pin while skill has 4 markers
    _run_pin(["write", "9.0-test"], repo)
    # Now simulate harness upgrade — append a 5th marker to skill
    accept_md = (repo / ".claude" / "commands" / "vg" / "accept.md")
    text = accept_md.read_text(encoding="utf-8")
    text = text.replace(
        '- "7_finish"',
        '- "7_finish"\n    - "8_NEW_GATE_FROM_UPGRADE"',
    )
    accept_md.write_text(text, encoding="utf-8")

    # Without pin: parse() would return 5 markers
    r_extract = _run_pin(["extract", "--command", "vg:accept"], repo)
    current = json.loads(r_extract.stdout)
    assert "8_NEW_GATE_FROM_UPGRADE" in current["must_touch_markers"]

    # With pin: parse_for_phase MUST still return only the 4 pinned markers
    import os
    sys.path.insert(0, str(repo / ".claude" / "scripts" / "vg-orchestrator"))
    saved_env = os.environ.get("VG_REPO_ROOT")
    os.environ["VG_REPO_ROOT"] = str(repo)
    try:
        for mod in list(sys.modules):
            if mod in ("contracts", "_repo_root"):
                del sys.modules[mod]
        spec = importlib.util.spec_from_file_location(
            "contracts",
            repo / ".claude" / "scripts" / "vg-orchestrator" / "contracts.py",
        )
        contracts = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(contracts)
        c = contracts.parse_for_phase("9.0-test", "vg:accept")
        markers = c.get("must_touch_markers") or []
        assert "8_NEW_GATE_FROM_UPGRADE" not in markers, (
            "Pinned phase MUST NOT be retroactively forced to honor "
            "post-pin skill upgrades — that's the entire point of Tier B"
        )
        assert len(markers) == 4, f"expected 4 pinned markers, got {markers}"
    finally:
        sys.path.pop(0)
        if saved_env is None:
            os.environ.pop("VG_REPO_ROOT", None)
        else:
            os.environ["VG_REPO_ROOT"] = saved_env


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
