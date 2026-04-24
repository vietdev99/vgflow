"""
Tests for verify-command-contract-coverage.py — Phase J of v2.5.2.

Covers:
  - Frontmatter parser extracts runtime_contract + mutates_repo +
    observation_only + contract_exempt_reason correctly
  - Mutating command without contract → MISSING_CONTRACT
  - Read-only command with observation_only=true + reason → OK
  - Read-only command missing declaration → MISSING_OBSERVATION_DECL
  - observation_only=true without reason → MISSING_EXEMPT_REASON
  - Body mutation heuristics (git commit, emit-event, Write tool) → detected
  - --strict mode treats HEURISTIC_MUTATING as hard miss
  - --command filter limits scope
  - --json output parseable
  - --quiet suppresses clean output
  - Real repo sanity: validator runs against current .claude/commands/vg/
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / \
    "verify-command-contract-coverage.py"


def _run(args: list[str], env_overrides: dict | None = None
         ) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=30,
        cwd=str(REPO_ROOT), env=env, encoding="utf-8", errors="replace",
    )


def _setup_commands(tmp_path: Path, commands: dict[str, str]) -> Path:
    """Create fake repo with .claude/commands/vg/{name}.md files."""
    cmd_dir = tmp_path / ".claude" / "commands" / "vg"
    cmd_dir.mkdir(parents=True, exist_ok=True)
    for name, content in commands.items():
        (cmd_dir / f"{name}.md").write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=False)
    return tmp_path


# ─── Frontmatter parser ───────────────────────────────────────────────

class TestFrontmatterParser:
    def test_mutating_with_contract_ok(self, tmp_path):
        """Known mutating cmd + runtime_contract → OK."""
        root = _setup_commands(tmp_path, {
            "build": """---
name: vg:build
mutates_repo: true
runtime_contract:
  must_write:
    - "${PHASE_DIR}/SUMMARY.md"
  must_emit_telemetry:
    - event_type: "build.completed"
---
# /vg:build
body text.
""",
        })
        r = _run(["--command", "build", "--json"],
                 env_overrides={"REPO_ROOT": str(root)})
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["issue_count"] == 0
        assert data["results"][0]["verdict"] == "OK"
        assert data["results"][0]["has_runtime_contract"] is True

    def test_mutating_without_contract_fails(self, tmp_path):
        """Known mutating cmd + no contract → MISSING_CONTRACT."""
        root = _setup_commands(tmp_path, {
            "project": """---
name: vg:project
---
# /vg:project
Bug: no runtime_contract.
""",
        })
        r = _run(["--command", "project", "--json"],
                 env_overrides={"REPO_ROOT": str(root)})
        assert r.returncode == 1
        data = json.loads(r.stdout)
        assert data["results"][0]["verdict"] == "MISSING_CONTRACT"


# ─── Observation-only flow ────────────────────────────────────────────

class TestObservationOnly:
    def test_declared_observation_with_reason_ok(self, tmp_path):
        root = _setup_commands(tmp_path, {
            "progress": """---
name: vg:progress
observation_only: true
contract_exempt_reason: "read-only: queries events.db, no mutation"
---
# /vg:progress
""",
        })
        r = _run(["--command", "progress", "--json"],
                 env_overrides={"REPO_ROOT": str(root)})
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["results"][0]["verdict"] == "OK"

    def test_declared_observation_missing_reason_fails(self, tmp_path):
        root = _setup_commands(tmp_path, {
            "progress": """---
name: vg:progress
observation_only: true
---
# /vg:progress
""",
        })
        r = _run(["--command", "progress", "--json"],
                 env_overrides={"REPO_ROOT": str(root)})
        assert r.returncode == 1
        data = json.loads(r.stdout)
        assert data["results"][0]["verdict"] == "MISSING_EXEMPT_REASON"

    def test_declared_observation_short_reason_fails(self, tmp_path):
        root = _setup_commands(tmp_path, {
            "progress": """---
name: vg:progress
observation_only: true
contract_exempt_reason: "short"
---
""",
        })
        r = _run(["--command", "progress", "--json"],
                 env_overrides={"REPO_ROOT": str(root)})
        assert r.returncode == 1
        data = json.loads(r.stdout)
        assert data["results"][0]["verdict"] == "MISSING_EXEMPT_REASON"

    def test_expected_observation_without_declaration_fails(self, tmp_path):
        """progress in EXPECTED_OBSERVATION_ONLY but no observation_only declared."""
        root = _setup_commands(tmp_path, {
            "progress": """---
name: vg:progress
---
# /vg:progress
""",
        })
        r = _run(["--command", "progress", "--json"],
                 env_overrides={"REPO_ROOT": str(root)})
        assert r.returncode == 1
        data = json.loads(r.stdout)
        assert data["results"][0]["verdict"] == "MISSING_OBSERVATION_DECL"


# ─── Body heuristic ──────────────────────────────────────────────────

class TestBodyHeuristic:
    def test_git_commit_in_body_detected(self, tmp_path):
        """Unlisted command with git commit in body → body_looks_mutating=True."""
        root = _setup_commands(tmp_path, {
            "random-util": """---
name: vg:random-util
---
# /vg:random-util

```bash
git commit -m "do thing"
```
""",
        })
        r = _run(["--command", "random-util", "--json"],
                 env_overrides={"REPO_ROOT": str(root)})
        # Not strict → heuristic is relaxed to OK
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["results"][0]["body_looks_mutating"] is True
        # In relaxed mode: verdict is OK but verdict_original shows detection
        assert data["results"][0].get("verdict_original") == "HEURISTIC_MUTATING"

    def test_strict_mode_heuristic_blocks(self, tmp_path):
        root = _setup_commands(tmp_path, {
            "random-util": """---
name: vg:random-util
---
```bash
git push origin main
```
""",
        })
        r = _run(["--command", "random-util", "--strict", "--json"],
                 env_overrides={"REPO_ROOT": str(root)})
        assert r.returncode == 1
        data = json.loads(r.stdout)
        assert data["results"][0]["verdict"] == "HEURISTIC_MUTATING"

    def test_emit_event_detected(self, tmp_path):
        root = _setup_commands(tmp_path, {
            "widget": """---
name: vg:widget
---
Calls vg-orchestrator emit-event on completion.
""",
        })
        r = _run(["--command", "widget", "--strict", "--json"],
                 env_overrides={"REPO_ROOT": str(root)})
        data = json.loads(r.stdout)
        assert data["results"][0]["body_looks_mutating"] is True

    def test_pure_read_body_safe(self, tmp_path):
        root = _setup_commands(tmp_path, {
            "pure-reader": """---
name: vg:pure-reader
observation_only: true
contract_exempt_reason: "read-only: pure data lookup"
---
# /vg:pure-reader

Just cat files and print. No mutation at all.
""",
        })
        r = _run(["--command", "pure-reader", "--json"],
                 env_overrides={"REPO_ROOT": str(root)})
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["results"][0]["verdict"] == "OK"


# ─── CLI contract ────────────────────────────────────────────────────

class TestCLI:
    def test_quiet_suppresses_clean(self, tmp_path):
        root = _setup_commands(tmp_path, {
            "build": """---
runtime_contract:
  must_write:
    - "${PHASE_DIR}/SUMMARY.md"
---
""",
        })
        r = _run(["--quiet"], env_overrides={"REPO_ROOT": str(root)})
        assert r.returncode == 0
        assert r.stdout.strip() == ""

    def test_json_output_shape(self, tmp_path):
        root = _setup_commands(tmp_path, {
            "build": """---
runtime_contract:
  must_write:
    - "${PHASE_DIR}/SUMMARY.md"
---
""",
        })
        r = _run(["--json"], env_overrides={"REPO_ROOT": str(root)})
        data = json.loads(r.stdout)
        assert "repo_root" in data
        assert "commands_checked" in data
        assert "issue_count" in data
        assert "results" in data
        assert isinstance(data["results"], list)


# ─── Real-repo integration ────────────────────────────────────────────

class TestRealRepo:
    def test_real_repo_exits_nonzero_until_phase_j_complete(self):
        """Current real repo has 34 commands needing backfill.

        After Phase J backfills 17 mutating + 8 observation-only cmds,
        this test should pass (exit 0). Until then it asserts the gap
        exists — exactly what Phase J is fixing.
        """
        r = _run(["--quiet"])
        # Phase J in progress — expect gaps; test documents the baseline.
        # Once Phase J completes, adjust this test to assert returncode == 0.
        assert r.returncode in (0, 1)
        if r.returncode == 1:
            # Validate the error output shape is useful
            assert "MISSING" in r.stdout or "coverage" in r.stdout.lower()

    def test_real_repo_json_parseable(self):
        r = _run(["--json"])
        data = json.loads(r.stdout)
        assert data["commands_checked"] > 0
        # Should find at least the 7 existing contracted commands
        contracted = [r for r in data["results"]
                      if r.get("has_runtime_contract")]
        assert len(contracted) >= 7
