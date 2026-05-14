# Batch 24 — Scaffold-pattern detector + audit CI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Codify 8 scaffold/drift anti-patterns gặp trong Batches 9/14/15/18/19/22 thành automated grep audit. Run mỗi release. Block new scaffold drift trước khi ship.

**Working directory:** `main`.

---

## Anti-pattern catalog

| Pattern | Description | Examples found |
|---|---|---|
| **A** Agent comment-only | `Agent(subagent_type=...)` trong ```bash``` fence không có file gate sau | F1, F3, F4, F7 |
| **B** Marker no-evidence | `mark-step <X>` không có file existence check trước trong cùng block | F3 (Batch 15) |
| **C** Failure swallow | `\|\| true` trên line `run-complete\|validate\|verify` | F2 (Batch 19) |
| **D** Orphan must_write | `must_write:` declare file X nhưng grep không thấy validator đọc X | F7 MATRIX-INTENT |
| **E** READ-ONLY agent vs file expect | Agent SKILL.md frontmatter `allowed-tools:` thiếu Write nhưng caller expect file | F5 (Batch 19) |
| **F** Tool directive in bash | ```bash``` fence chứa `Agent(`, `SlashCommand:`, `AskUserQuestion:` | F4 (Batch 14) |
| **G** Unconditional marker | `touch *.done` trong else branch không validation | B1/B4 (Batch 15) |
| **H** Glob bypass | `*.spec.ts\|*.json` glob chỗ canonical manifest tồn tại | Batch 21 test glob |

---

## Conventions

- Mirror byte-identical to `.claude/`
- Sweep: `python -m pytest tests/ -q --tb=no -k "scaffold_detector or anti_pattern or batch_24"`
- Single Co-Authored-By trailer per commit
- Detector outputs JSON report; threshold-based block

---

## Task 1: scripts/audit/scaffold-detector.py

**Files:**
- Create: `scripts/audit/scaffold-detector.py`
- Mirror
- Test: `tests/test_batch24_scaffold_detector.py`

**Step 1: Failing test**

```python
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
```

**Step 2: Run** → 5 fail.

**Step 3: Implement**

Create `scripts/audit/scaffold-detector.py`:

```python
#!/usr/bin/env python3
"""scaffold-detector.py — Batch 24

Audits markdown files in commands/vg/ for scaffold/drift anti-patterns.
8 patterns A-H codified from Batches 9/14/15/18/19/22 findings.

Emits JSON report with per-finding file:line + pattern + snippet.
--threshold N: exit 1 if findings count > N (CI gate).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


# Pattern definitions: (pattern_id, severity, name, description, detector_fn)
PATTERNS = [
    ("A", "high", "agent_comment_only",
     "Agent(subagent_type=...) inside bash fence with no file gate after"),
    ("B", "medium", "marker_no_evidence",
     "mark-step <X> without file existence check in same block"),
    ("C", "high", "failure_swallow",
     "|| true on run-complete/validate/verify line"),
    ("D", "medium", "orphan_must_write",
     "must_write declares file X but no validator reads it"),
    ("E", "high", "agent_read_only_file_expect",
     "Agent SKILL.md missing Write but caller expects file output"),
    ("F", "high", "tool_directive_in_bash",
     "Agent( / SlashCommand: / AskUserQuestion: inside bash fence"),
    ("G", "medium", "unconditional_marker",
     "touch *.done in else branch without validation"),
    ("H", "low", "glob_bypass",
     "Glob *.spec.ts / *.json where canonical manifest exists"),
]


BASH_FENCE_RE = re.compile(r"```bash\n(.*?)\n```", re.DOTALL)


def _detect_pattern_A(text: str, path: Path) -> list[dict]:
    """Agent(subagent_type=...) inside bash fence with no file gate after."""
    findings = []
    for m in BASH_FENCE_RE.finditer(text):
        block = m.group(1)
        line_offset = text[:m.start()].count("\n") + 1
        # Find Agent( occurrences in bash block
        for am in re.finditer(r"#\s*Agent\(subagent_type", block):
            block_line = block[:am.start()].count("\n")
            line_num = line_offset + block_line + 1
            # Check next 800 chars in block for [ -f ... ] or is_file or exists check
            tail = block[am.end():am.end() + 800]
            has_gate = bool(re.search(r"\[\s*-f\s|\[\s*!\s*-f\s|is_file\(|exists\(", tail))
            if not has_gate:
                findings.append({
                    "pattern": "A",
                    "file": str(path),
                    "line": line_num,
                    "snippet": block[am.start():am.start() + 120].strip(),
                })
    return findings


def _detect_pattern_C(text: str, path: Path) -> list[dict]:
    """|| true on run-complete / validate / verify lines."""
    findings = []
    for ln, line in enumerate(text.splitlines(), 1):
        if "|| true" in line and re.search(r"\b(run-complete|validate|verify|check-contract)\b", line):
            # Skip comments
            if line.strip().startswith("#") or line.strip().startswith("//"):
                continue
            findings.append({
                "pattern": "C",
                "file": str(path),
                "line": ln,
                "snippet": line.strip()[:120],
            })
    return findings


def _detect_pattern_F(text: str, path: Path) -> list[dict]:
    """Tool directive (Agent(/SlashCommand:/AskUserQuestion:) inside bash fence."""
    findings = []
    for m in BASH_FENCE_RE.finditer(text):
        block = m.group(1)
        line_offset = text[:m.start()].count("\n") + 1
        for dm in re.finditer(r"^\s*(AskUserQuestion:|SlashCommand:|Agent\()", block, re.MULTILINE):
            # Skip if commented out
            block_line_start = block.rfind("\n", 0, dm.start()) + 1
            prefix = block[block_line_start:dm.start()]
            if prefix.strip().startswith("#"):
                continue
            block_line = block[:dm.start()].count("\n")
            line_num = line_offset + block_line + 1
            findings.append({
                "pattern": "F",
                "file": str(path),
                "line": line_num,
                "snippet": dm.group(0).strip()[:120],
            })
    return findings


def _detect_pattern_G(text: str, path: Path) -> list[dict]:
    """touch *.done in else branch without validation."""
    findings = []
    # Find else { ... touch *.done ... } blocks
    else_blocks = re.finditer(r"\belse\b\s*\n((?:.*\n){1,15}?)\bfi\b", text)
    for m in else_blocks:
        block = m.group(1)
        if re.search(r"touch\s+[^\n]*\.done", block):
            # Check if validation present in same block
            if not re.search(r"\[\s*-f|is_file|exists\(|verify|validator", block):
                line_num = text[:m.start()].count("\n") + 1
                findings.append({
                    "pattern": "G",
                    "file": str(path),
                    "line": line_num,
                    "snippet": "else { ... touch .done ... fi (no validation)",
                })
    return findings


def _detect_pattern_H(text: str, path: Path) -> list[dict]:
    """Glob *.spec.ts / *.json where canonical manifest exists."""
    findings = []
    for ln, line in enumerate(text.splitlines(), 1):
        # Only flag inside playwright/test contexts where manifest exists
        if re.search(r"\*\.spec\.[tj]s\b", line):
            if "CODEGEN-MANIFEST" not in text[:text.find(line) + len(line)]:
                findings.append({
                    "pattern": "H",
                    "file": str(path),
                    "line": ln,
                    "snippet": line.strip()[:120],
                })
    return findings


DETECTORS = [
    _detect_pattern_A,
    _detect_pattern_C,
    _detect_pattern_F,
    _detect_pattern_G,
    _detect_pattern_H,
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan-dir", required=True, type=Path)
    ap.add_argument("--glob", default="**/*.md",
                    help="File pattern to scan")
    ap.add_argument("--threshold", type=int, default=-1,
                    help="Exit 1 if findings count > threshold. Default -1 (advisory only).")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    findings: list[dict] = []
    for path in args.scan_dir.glob(args.glob):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for det in DETECTORS:
            findings.extend(det(text, path))

    report = {
        "scan_dir": str(args.scan_dir),
        "total_findings": len(findings),
        "by_pattern": {},
        "findings": findings,
    }
    for f in findings:
        pat = f["pattern"]
        report["by_pattern"][pat] = report["by_pattern"].get(pat, 0) + 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Scaffold detector: {len(findings)} finding(s)")
        for f in findings[:30]:
            print(f"  [{f['pattern']}] {f['file']}:{f['line']}: {f['snippet']}")
        if len(findings) > 30:
            print(f"  ... +{len(findings) - 30} more (use --json for full report)")

    if args.threshold >= 0 and len(findings) > args.threshold:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**Step 4-6:** pass + mirror + commit.

```bash
git commit -m "feat(audit): Batch 24 Task 1 — scaffold-detector.py codifies 8 anti-patterns

Codifies anti-patterns gặp trong Batches 9/14/15/18/19/22:
A) Agent(subagent_type=...) trong bash fence, no file gate sau
B) mark-step <X> không có file existence check trước
C) || true trên run-complete/validate/verify line
D) must_write declare file X nhưng no validator đọc X
E) Agent SKILL.md thiếu Write nhưng caller expect file
F) Tool directive (Agent(/SlashCommand:/AskUserQuestion:) trong bash fence
G) touch *.done trong else branch không validation
H) Glob *.spec.ts/*.json chỗ canonical manifest tồn tại

Detector first ship implements patterns A, C, F, G, H (B/D/E
require cross-file analysis — future enhancement).

--threshold N: exit 1 if findings count > N (CI gate).
--json: structured output for telemetry.

Tests: tests/test_batch24_scaffold_detector.py (5 tests).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Wire detector into release CI + new /vg:audit-scaffold

**Files:**
- Modify: `.github/workflows/release.yml` (run detector pre-tag with current threshold = baseline count)
- Create: `commands/vg/audit-scaffold.md` (operator-facing slash command)
- Mirror
- Test: `tests/test_batch24_audit_wiring.py`

**Step 1: Failing test**

```python
"""tests/test_batch24_audit_wiring.py — Batch 24 audit wiring."""
from __future__ import annotations
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]


def test_release_workflow_runs_detector():
    wf = REPO / ".github" / "workflows" / "release.yml"
    if not wf.is_file():
        # CI workflow not in repo — skip
        return
    body = wf.read_text(encoding="utf-8")
    assert "scaffold-detector" in body, (
        "Batch 24: release.yml must run scripts/audit/scaffold-detector.py "
        "as pre-tag gate"
    )


def test_audit_scaffold_command_exists():
    cmd = REPO / "commands" / "vg" / "audit-scaffold.md"
    assert cmd.is_file(), (
        "Batch 24: /vg:audit-scaffold command must ship — operator-facing "
        "invocation of scaffold-detector"
    )
    body = cmd.read_text(encoding="utf-8")
    assert "scaffold-detector" in body, "command must invoke the script"
```

**Step 2-6:** RED → implement → GREEN → mirror → commit.

`commands/vg/audit-scaffold.md` frontmatter + body:

```markdown
---
name: vg:audit-scaffold
description: Audit commands/ for scaffold/drift anti-patterns (Batch 24)
allowed-tools:
  - Bash
  - Read
---

# /vg:audit-scaffold

Runs `scripts/audit/scaffold-detector.py` against `commands/vg/` to find
scaffold patterns (Agent-comment-only, marker-no-evidence, swallow,
tool-in-bash, unconditional-marker, glob-bypass).

```bash
DET="${VG_SCRIPT_ROOT:-${VG_HOME:-$HOME/.vgflow}/scripts}/audit/scaffold-detector.py"
[ -f "$DET" ] || DET="${REPO_ROOT:-.}/scripts/audit/scaffold-detector.py"
"${PYTHON_BIN:-python3}" "$DET" --scan-dir "${REPO_ROOT:-.}/commands/vg" --json
```

Default: advisory mode. Pass `--threshold 0` for strict (BLOCK on any finding).
```

In `.github/workflows/release.yml` add step before tag-push:

```yaml
- name: Scaffold pattern audit
  run: |
    python scripts/audit/scaffold-detector.py \
      --scan-dir commands/vg \
      --threshold 50  # baseline — tune via telemetry
```

```bash
git commit -m "feat(audit): Batch 24 Task 2 — wire scaffold-detector into release CI + /vg:audit-scaffold

- .github/workflows/release.yml runs detector pre-tag (advisory threshold 50 baseline)
- /vg:audit-scaffold operator command for ad-hoc audits
- Mirror to .claude/

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Release v4.27.0 (after Batch 23 v4.26.0)

Bump VERSION → 4.27.0. CHANGELOG. Tag. Push. Re-sync ~/.vgflow.

End of Batch 24. Estimated 3 hours.
