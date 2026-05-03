"""
test_orphans_orchestrator.py — coverage for Phase D orphan triage
orchestrator subcommands (orphans-list / orphans-collect / orphans-apply).

Pins:
1. orphans-list partition is deterministic (re-run produces byte-identical
   orphan-list.json on the same fake repo).
2. orphans-list 3-way diff buckets script_only/registry_only/dispatch_only
   correctly given known overlap state.
3. orphans-list skips _retired/ subdirectory — only top-level verify-*.py
   files appear in the orphan list.
4. orphans-collect raises a clear error when a per-agent decision file is
   missing a validator from its assigned slice.
5. orphans-collect happy-path merges three files and aggregates stats
   correctly.
6. orphans-apply WIRE outcome adds a registry.yaml entry + a
   dispatch-manifest.json entry.
7. orphans-apply RETIRE outcome moves the script to _retired/{date}-name.py
   and stamps a `retired:` block on the registry entry.
8. orphans-apply --dry-run prints the apply log but writes no files.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATOR = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py"


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cleanup_vg_repo_root_env():
    original = os.environ.get("VG_REPO_ROOT")
    yield
    if original is None:
        os.environ.pop("VG_REPO_ROOT", None)
    else:
        os.environ["VG_REPO_ROOT"] = original


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    # PYTHONPATH so _orphans + _repo_root import works even though the
    # orchestrator package was copied as plain files.
    orch_dir = str(repo / ".claude" / "scripts" / "vg-orchestrator")
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (orch_dir + os.pathsep + existing_pp) if existing_pp \
        else orch_dir
    proc = subprocess.run(
        [sys.executable, str(repo / ".claude" / "scripts"
                              / "vg-orchestrator" / "__main__.py"), *args],
        capture_output=True, text=True, cwd=str(repo), env=env, timeout=20,
    )
    return proc


def _setup_fake_repo(tmp_path: Path) -> Path:
    """Mirror orchestrator scripts into tmp_path and stage a clean repo with
    .git/ marker so find_repo_root resolves correctly."""
    repo = tmp_path / "fake-repo"
    (repo / ".git").mkdir(parents=True)

    # Mirror orchestrator package
    orch_src = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"
    orch_dst = repo / ".claude" / "scripts" / "vg-orchestrator"
    orch_dst.mkdir(parents=True)
    for name in ("__main__.py", "_orphans.py", "_repo_root.py", "db.py",
                 "contracts.py", "state.py", "evidence.py", "lock.py",
                 "journal.py", "allow_flag_gate.py", "prompt_capture.py"):
        src = orch_src / name
        if src.exists():
            (orch_dst / name).write_bytes(src.read_bytes())

    # Stub validators directory (empty by default — caller adds files)
    (repo / ".claude" / "scripts" / "validators").mkdir(parents=True)
    return repo


def _write_validator_script(repo: Path, name: str) -> None:
    p = repo / ".claude" / "scripts" / "validators" / f"{name}.py"
    p.write_text(
        f'"""Stub validator {name}."""\nimport sys\nsys.exit(0)\n',
        encoding="utf-8",
    )


def _write_registry(repo: Path, ids: list[str]) -> None:
    """Write a registry.yaml with simple entries for given verify-* ids."""
    lines = [
        "validators:",
    ]
    for vid in ids:
        bare = vid.removeprefix("verify-")
        lines.extend([
            f"  - id: {bare}",
            f"    path: .claude/scripts/validators/{vid}.py",
            "    severity: warn",
            "    phases_active: [test]",
            "    domain: test",
            "    runtime_target_ms: 1000",
            "    added_in: test",
            f"    description: stub {bare}",
        ])
    (repo / ".claude" / "scripts" / "validators" / "registry.yaml") \
        .write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_dispatch(repo: Path, ids: list[str]) -> None:
    payload = {
        "version": "1.0",
        "validators": {
            vid.removeprefix("verify-"): {
                "triggers": {"commands": ["vg:test"], "steps": ["*"]},
                "contexts": {
                    "profiles": ["feature"], "platforms": ["*"], "envs": ["*"],
                },
                "severity": "WARN",
                "unquarantinable": False,
                "description": f"stub {vid}",
            }
            for vid in ids
        },
    }
    (repo / ".claude" / "scripts" / "validators" / "dispatch-manifest.json") \
        .write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _read_orphan_list(repo: Path) -> dict:
    p = repo / ".vg" / "workflow-hardening-v2.7" / "orphan-list.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _write_decisions_file(repo: Path, n: int, decisions: list[dict]) -> None:
    pdir = repo / ".vg" / "workflow-hardening-v2.7"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f"orphan-decisions-{n}.json").write_text(
        json.dumps(decisions, indent=2), encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_orphans_list_partitions_deterministic(tmp_path: Path) -> None:
    repo = _setup_fake_repo(tmp_path)
    # Mix: some script-only, some registry-only, some dispatch-only
    for name in ("verify-aaa", "verify-bbb", "verify-ccc",
                 "verify-ddd", "verify-eee", "verify-fff"):
        _write_validator_script(repo, name)
    _write_registry(repo, ["verify-bbb", "verify-ggg"])  # ggg is registry-only
    _write_dispatch(repo, ["verify-ccc", "verify-hhh"])  # hhh is dispatch-only

    proc1 = _run(repo, "orphans-list")
    assert proc1.returncode == 0, proc1.stderr
    data1 = _read_orphan_list(repo)

    # Re-run — output must be byte-identical (modulo generated_at timestamp)
    proc2 = _run(repo, "orphans-list")
    assert proc2.returncode == 0, proc2.stderr
    data2 = _read_orphan_list(repo)

    # Strip timestamps for stable comparison
    data1.pop("generated_at", None)
    data2.pop("generated_at", None)
    assert data1 == data2, "partition not deterministic across runs"

    # Schema sanity
    assert set(data1.keys()) == {"total_orphans", "by_kind", "agents"}
    assert set(data1["by_kind"].keys()) == {
        "script_only", "registry_only", "dispatch_only",
    }
    assert set(data1["agents"].keys()) == {"agent_1", "agent_2", "agent_3"}


def test_orphans_list_three_way_diff_correct(tmp_path: Path) -> None:
    repo = _setup_fake_repo(tmp_path)

    # Known state:
    #   verify-script-only  → on disk only
    #   verify-registry-only→ registry entry, no disk, no dispatch
    #   verify-dispatch-only→ dispatch entry, no disk, no registry
    #   verify-fully-wired  → on disk + registry + dispatch (NOT an orphan)
    _write_validator_script(repo, "verify-script-only")
    _write_validator_script(repo, "verify-fully-wired")
    _write_registry(repo, ["verify-registry-only", "verify-fully-wired"])
    _write_dispatch(repo, ["verify-dispatch-only", "verify-fully-wired"])

    proc = _run(repo, "orphans-list")
    assert proc.returncode == 0, proc.stderr
    data = _read_orphan_list(repo)

    # Canonical ids strip the `verify-` prefix so naming conventions
    # (bare stem vs verify-prefixed) collapse symmetrically across the
    # 3 sources.
    assert data["by_kind"]["script_only"] == ["script-only"]
    assert data["by_kind"]["registry_only"] == ["registry-only"]
    assert data["by_kind"]["dispatch_only"] == ["dispatch-only"]
    # fully-wired is in all 3 sets → NOT an orphan
    flat = (
        data["by_kind"]["script_only"]
        + data["by_kind"]["registry_only"]
        + data["by_kind"]["dispatch_only"]
    )
    assert "fully-wired" not in flat
    assert "verify-fully-wired" not in flat
    assert data["total_orphans"] == 3


def test_orphans_list_skips_retired_dir(tmp_path: Path) -> None:
    repo = _setup_fake_repo(tmp_path)
    _write_validator_script(repo, "verify-foo")

    retired_dir = repo / ".claude" / "scripts" / "validators" / "_retired"
    retired_dir.mkdir(parents=True)
    # An old retired script — must NOT appear in the orphan list
    (retired_dir / "verify-old.py").write_text(
        '"""old retired."""\n', encoding="utf-8",
    )
    # Empty registry + dispatch so foo lands as script-only
    _write_registry(repo, [])
    _write_dispatch(repo, [])

    proc = _run(repo, "orphans-list")
    assert proc.returncode == 0, proc.stderr
    data = _read_orphan_list(repo)

    assert data["by_kind"]["script_only"] == ["foo"]
    flat_all = (
        data["by_kind"]["script_only"]
        + data["by_kind"]["registry_only"]
        + data["by_kind"]["dispatch_only"]
    )
    assert "verify-old" not in flat_all


def test_orphans_collect_validates_coverage(tmp_path: Path) -> None:
    repo = _setup_fake_repo(tmp_path)
    for name in ("verify-aaa", "verify-bbb", "verify-ccc"):
        _write_validator_script(repo, name)
    _write_registry(repo, [])
    _write_dispatch(repo, [])

    proc = _run(repo, "orphans-list")
    assert proc.returncode == 0, proc.stderr
    data = _read_orphan_list(repo)

    # Build per-agent decision files but DROP one validator from agent_1
    def _decision(vid: str, outcome: str = "RETIRE") -> dict:
        return {
            "validator_id": vid,
            "path": f".claude/scripts/validators/{vid}.py",
            "outcome": outcome,
            "confidence": 0.95,
            "evidence": {
                "docstring_summary": "stub",
                "real_callers": [],
                "test_only_callers": [],
                "retire_reason": "no callers",
            },
        }

    a1 = data["agents"]["agent_1"]
    a2 = data["agents"]["agent_2"]
    a3 = data["agents"]["agent_3"]
    # Drop the first item of agent_1 to trigger missing-coverage error
    if a1:
        a1_short = a1[1:]
    else:
        a1_short = a1
    _write_decisions_file(repo, 1, [_decision(v) for v in a1_short])
    _write_decisions_file(repo, 2, [_decision(v) for v in a2])
    _write_decisions_file(repo, 3, [_decision(v) for v in a3])

    proc2 = _run(repo, "orphans-collect")
    assert proc2.returncode != 0, "expected failure on missing coverage"
    assert "missing decisions" in proc2.stderr.lower()


def test_orphans_collect_merges_three_files(tmp_path: Path) -> None:
    repo = _setup_fake_repo(tmp_path)
    for name in ("verify-aaa", "verify-bbb", "verify-ccc",
                 "verify-ddd", "verify-eee", "verify-fff"):
        _write_validator_script(repo, name)
    _write_registry(repo, [])
    _write_dispatch(repo, [])

    proc = _run(repo, "orphans-list")
    assert proc.returncode == 0, proc.stderr
    data = _read_orphan_list(repo)

    # Mix outcomes across slices for stat coverage
    def mk(vid: str, outcome: str) -> dict:
        return {
            "validator_id": vid,
            "path": f".claude/scripts/validators/{vid}.py",
            "outcome": outcome,
            "confidence": 0.9,
            "evidence": {
                "docstring_summary": "stub",
                "real_callers": [],
                "test_only_callers": [],
                "retire_reason": "no callers",
                "merged_into_id": "verify-other",
                "suggested_context": {
                    "commands": ["vg:test"],
                    "steps": ["*"],
                    "profiles": ["feature"],
                    "platforms": ["*"],
                    "envs": ["*"],
                },
                "severity": "WARN",
            },
        }

    outcomes = ["WIRE", "RETIRE", "MERGE", "NEEDS_HUMAN"]
    file_decisions: dict[int, list[dict]] = {1: [], 2: [], 3: []}
    for n in (1, 2, 3):
        slice_ids = data["agents"][f"agent_{n}"]
        for i, vid in enumerate(slice_ids):
            file_decisions[n].append(mk(vid, outcomes[i % len(outcomes)]))
    for n, ds in file_decisions.items():
        _write_decisions_file(repo, n, ds)

    proc2 = _run(repo, "orphans-collect")
    assert proc2.returncode == 0, proc2.stderr

    merged = json.loads(
        (repo / ".vg" / "workflow-hardening-v2.7"
         / "orphan-decisions.json").read_text(encoding="utf-8"),
    )
    assert merged["total_decisions"] == data["total_orphans"]
    stats = merged["stats"]
    # Sum of per-outcome counts equals total
    assert (stats["wire"] + stats["retire"] + stats["merge"]
            + stats["needs_human"]) == data["total_orphans"]


def test_orphans_apply_wire_adds_registry_and_dispatch(tmp_path: Path) -> None:
    repo = _setup_fake_repo(tmp_path)
    _write_validator_script(repo, "verify-newcomer")
    _write_registry(repo, [])
    _write_dispatch(repo, [])

    proc = _run(repo, "orphans-list")
    assert proc.returncode == 0, proc.stderr

    decisions = [{
        "validator_id": "verify-newcomer",
        "path": ".claude/scripts/validators/verify-newcomer.py",
        "outcome": "WIRE",
        "confidence": 0.92,
        "evidence": {
            "docstring_summary": "Wires inventory drift checks",
            "real_callers": [".claude/commands/vg/build.md:42"],
            "test_only_callers": [],
            "suggested_context": {
                "commands": ["vg:build"],
                "steps": ["*"],
                "profiles": ["feature"],
                "platforms": ["*"],
                "envs": ["*"],
            },
            "severity": "BLOCK",
        },
    }]
    pdir = repo / ".vg" / "workflow-hardening-v2.7"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "orphan-decisions.json").write_text(
        json.dumps({
            "generated_at": "2026-04-26T00:00:00Z",
            "total_decisions": 1,
            "stats": {"wire": 1, "retire": 0, "merge": 0, "needs_human": 0},
            "decisions": decisions,
        }, indent=2),
        encoding="utf-8",
    )

    proc2 = _run(repo, "orphans-apply")
    assert proc2.returncode == 0, proc2.stderr

    # Registry entry exists with triage block
    import yaml as _yaml
    reg = _yaml.safe_load(
        (repo / ".claude" / "scripts" / "validators" / "registry.yaml")
        .read_text(encoding="utf-8"),
    )
    entries = reg["validators"]
    matched = [e for e in entries
               if e.get("path", "").endswith("verify-newcomer.py")]
    assert len(matched) == 1, "WIRE did not add registry entry"
    entry = matched[0]
    assert entry["triage"]["state"] == "wired"
    assert entry["triage"]["confidence"] == 0.92

    # Dispatch entry exists
    dispatch = json.loads(
        (repo / ".claude" / "scripts" / "validators"
         / "dispatch-manifest.json").read_text(encoding="utf-8"),
    )
    assert "newcomer" in dispatch["validators"], \
        "WIRE did not add dispatch entry"
    disp_entry = dispatch["validators"]["newcomer"]
    assert disp_entry["severity"] == "BLOCK"
    assert "vg:build" in disp_entry["triggers"]["commands"]


def test_orphans_apply_retire_moves_to_retired_dir(tmp_path: Path) -> None:
    repo = _setup_fake_repo(tmp_path)
    _write_validator_script(repo, "verify-deadcode")
    _write_registry(repo, ["verify-deadcode"])
    _write_dispatch(repo, ["verify-deadcode"])

    proc = _run(repo, "orphans-list")
    assert proc.returncode == 0, proc.stderr

    decisions = [{
        "validator_id": "verify-deadcode",
        "path": ".claude/scripts/validators/verify-deadcode.py",
        "outcome": "RETIRE",
        "confidence": 0.95,
        "evidence": {
            "docstring_summary": "Old validator from deprecated phase",
            "real_callers": [],
            "test_only_callers": ["test_deadcode.py"],
            "retire_reason": "feature removed in commit abc1234",
        },
    }]
    pdir = repo / ".vg" / "workflow-hardening-v2.7"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "orphan-decisions.json").write_text(
        json.dumps({
            "generated_at": "2026-04-26T00:00:00Z",
            "total_decisions": 1,
            "stats": {"wire": 0, "retire": 1, "merge": 0, "needs_human": 0},
            "decisions": decisions,
        }, indent=2),
        encoding="utf-8",
    )

    proc2 = _run(repo, "orphans-apply")
    assert proc2.returncode == 0, proc2.stderr

    # Original script gone, retired/{date}-name.py exists
    src = repo / ".claude" / "scripts" / "validators" / "verify-deadcode.py"
    assert not src.exists(), "RETIRE did not remove original script"
    today = _today()
    dst = (repo / ".claude" / "scripts" / "validators" / "_retired"
           / f"{today}-verify-deadcode.py")
    assert dst.exists(), f"RETIRE did not create {dst}"

    # Registry has retired block
    import yaml as _yaml
    reg = _yaml.safe_load(
        (repo / ".claude" / "scripts" / "validators" / "registry.yaml")
        .read_text(encoding="utf-8"),
    )
    matched = [e for e in reg["validators"]
               if e.get("path", "").endswith("verify-deadcode.py")]
    assert len(matched) == 1
    entry = matched[0]
    assert entry["triage"]["state"] == "retired"
    assert "retired" in entry
    assert entry["retired"]["moved_to"].endswith(
        f"_retired/{today}-verify-deadcode.py",
    )
    assert "feature removed" in entry["retired"]["reason"]

    # Dispatch entry removed
    dispatch = json.loads(
        (repo / ".claude" / "scripts" / "validators"
         / "dispatch-manifest.json").read_text(encoding="utf-8"),
    )
    assert "deadcode" not in dispatch["validators"]
    assert "verify-deadcode" not in dispatch["validators"]


def test_orphans_apply_dry_run_no_writes(tmp_path: Path) -> None:
    repo = _setup_fake_repo(tmp_path)
    _write_validator_script(repo, "verify-aaa")
    _write_validator_script(repo, "verify-bbb")
    _write_registry(repo, [])
    _write_dispatch(repo, [])

    proc = _run(repo, "orphans-list")
    assert proc.returncode == 0, proc.stderr

    decisions = [
        {
            "validator_id": "verify-aaa",
            "path": ".claude/scripts/validators/verify-aaa.py",
            "outcome": "WIRE",
            "confidence": 0.9,
            "evidence": {
                "docstring_summary": "stub",
                "real_callers": [],
                "test_only_callers": [],
                "suggested_context": {
                    "commands": ["vg:test"], "steps": ["*"],
                    "profiles": ["feature"], "platforms": ["*"], "envs": ["*"],
                },
                "severity": "WARN",
            },
        },
        {
            "validator_id": "verify-bbb",
            "path": ".claude/scripts/validators/verify-bbb.py",
            "outcome": "RETIRE",
            "confidence": 0.95,
            "evidence": {
                "docstring_summary": "stub",
                "real_callers": [],
                "test_only_callers": [],
                "retire_reason": "no callers",
            },
        },
    ]
    pdir = repo / ".vg" / "workflow-hardening-v2.7"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "orphan-decisions.json").write_text(
        json.dumps({
            "generated_at": "2026-04-26T00:00:00Z",
            "total_decisions": 2,
            "stats": {"wire": 1, "retire": 1, "merge": 0, "needs_human": 0},
            "decisions": decisions,
        }, indent=2),
        encoding="utf-8",
    )

    # Snapshot files BEFORE
    reg_path = repo / ".claude" / "scripts" / "validators" / "registry.yaml"
    disp_path = (repo / ".claude" / "scripts" / "validators"
                 / "dispatch-manifest.json")
    aaa_path = repo / ".claude" / "scripts" / "validators" / "verify-aaa.py"
    bbb_path = repo / ".claude" / "scripts" / "validators" / "verify-bbb.py"

    reg_before = reg_path.read_bytes()
    disp_before = disp_path.read_bytes()
    aaa_before = aaa_path.read_bytes()
    bbb_before = bbb_path.read_bytes()

    proc2 = _run(repo, "orphans-apply", "--dry-run")
    assert proc2.returncode == 0, proc2.stderr
    assert "DRY RUN" in proc2.stdout or "dry-run" in proc2.stdout.lower()

    # Files unchanged
    assert reg_path.read_bytes() == reg_before
    assert disp_path.read_bytes() == disp_before
    assert aaa_path.exists() and aaa_path.read_bytes() == aaa_before
    assert bbb_path.exists() and bbb_path.read_bytes() == bbb_before

    # Retired dir not created (no real moves)
    retired_dir = (repo / ".claude" / "scripts" / "validators" / "_retired")
    if retired_dir.exists():
        # Acceptable if empty, but no script files inside
        assert not list(retired_dir.glob("*.py"))
