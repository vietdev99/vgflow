"""tests/test_batch24_scaffold_detector.py — Batch 24 scaffold detector."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
DET = REPO / "scripts" / "audit" / "scaffold-detector.py"


def test_detector_exists():
    assert DET.is_file(), "Batch 24: scripts/audit/scaffold-detector.py must ship"


def test_detects_agent_comment_only(tmp_path):
    """Pattern A: Agent(...) inside ```bash``` with no file gate after."""
    f = tmp_path / "test.md"
    f.write_text("""# Some step
```bash
echo "About to spawn agent"
# Agent(subagent_type="vg-test-codegen", prompt="...")
mkdir -p .step-markers
touch .step-markers/done
```
""", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(DET), "--scan-dir", str(tmp_path), "--json"],
        capture_output=True, text=True,
    )
    assert r.returncode in (0, 1), f"detector crashed: {r.stderr}"
    out = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
    findings = out.get("findings", [])
    pattern_A = [f for f in findings if f.get("pattern") == "A"]
    assert pattern_A, (
        f"Pattern A (Agent comment-only) must detect 'Agent(subagent_type=...)' "
        f"inside bash fence with no file gate after. Got findings: {findings}"
    )


def test_detects_swallow(tmp_path):
    """Pattern C: || true on validate/verify/run-complete lines."""
    f = tmp_path / "test.md"
    f.write_text("""```bash
"${PYTHON_BIN:-python3}" vg-orchestrator run-complete --outcome PASS 2>/dev/null || true
```
""", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(DET), "--scan-dir", str(tmp_path), "--json"],
        capture_output=True, text=True,
    )
    out = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
    pattern_C = [f for f in out.get("findings", []) if f.get("pattern") == "C"]
    assert pattern_C, "Pattern C (|| true swallow on run-complete) must detect"


def test_detects_tool_directive_in_bash(tmp_path):
    """Pattern F: AskUserQuestion: or Agent( in bash fence."""
    f = tmp_path / "test.md"
    f.write_text("""```bash
AskUserQuestion: "Continue?"
mkdir -p out
```
""", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(DET), "--scan-dir", str(tmp_path), "--json"],
        capture_output=True, text=True,
    )
    out = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
    pattern_F = [f for f in out.get("findings", []) if f.get("pattern") == "F"]
    assert pattern_F, "Pattern F (tool directive in bash) must detect"


def test_threshold_block_mode(tmp_path):
    """--threshold N: exit 1 if findings count > N."""
    f = tmp_path / "test.md"
    f.write_text("""```bash
echo "A" || true
echo "B" || true
"${PYTHON_BIN}" run-complete --outcome PASS || true
```
""", encoding="utf-8")
    # Threshold 0 (strict) — any finding fails
    r = subprocess.run(
        [sys.executable, str(DET), "--scan-dir", str(tmp_path),
         "--threshold", "0"],
        capture_output=True, text=True,
    )
    assert r.returncode == 1, (
        f"--threshold 0 with findings must exit 1. rc={r.returncode}, "
        f"out={(r.stdout + r.stderr)[:300]}"
    )


def test_clean_file_passes(tmp_path):
    """File with no anti-patterns must exit 0."""
    f = tmp_path / "clean.md"
    f.write_text("""# Clean step
```bash
mkdir -p out
[ -f out/manifest.json ] || exit 1
touch out/done
```
""", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(DET), "--scan-dir", str(tmp_path)],
        capture_output=True, text=True,
    )
    # Clean file may have 0 findings → exit 0 regardless of threshold
    assert r.returncode == 0, f"clean file must exit 0. rc={r.returncode}"
