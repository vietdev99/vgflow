<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Codex Round 2 Correction A inlined below the original task body. -->

## Task 15: Pre-test Tier 1+2 runner (static + local tests)

**Files:**
- Create: `scripts/lib/pre_test_runner.py`
- Create: `scripts/validators/verify-pre-test-tier-1-2.py`
- Test: `tests/test_pre_test_runner.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_pre_test_runner.py`:

```python
"""Pre-test runner — Tier 1 (static) + Tier 2 (local unit/integration)."""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "scripts" / "validators" / "verify-pre-test-tier-1-2.py"


def test_debug_leftover_grep_blocks(tmp_path: Path) -> None:
    """A file containing console.log + TODO:remove must trigger BLOCK."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Page.tsx").write_text(textwrap.dedent("""
        export function Page() {
          console.log('debug me');  // TODO:remove
          return <div/>;
        }
    """).strip(), encoding="utf-8")
    out = tmp_path / "report.json"
    result = subprocess.run([
        "python3", str(GATE),
        "--source-root", str(tmp_path / "src"),
        "--phase", "test-1.0",
        "--report-out", str(out),
        "--skip-typecheck", "--skip-lint", "--skip-tests",  # only T1 grep
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 1, result.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["tier_1"]["debug_leftover"]["status"] == "BLOCK"
    assert any("console.log" in e["snippet"] for e in report["tier_1"]["debug_leftover"]["evidence"])


def test_clean_source_passes_grep(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Page.tsx").write_text(
        "export function Page() { return <div>hello</div>; }\n", encoding="utf-8",
    )
    out = tmp_path / "report.json"
    result = subprocess.run([
        "python3", str(GATE),
        "--source-root", str(tmp_path / "src"),
        "--phase", "test-1.0",
        "--report-out", str(out),
        "--skip-typecheck", "--skip-lint", "--skip-tests",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["tier_1"]["debug_leftover"]["status"] == "PASS"


def test_skip_flags_honored(tmp_path: Path) -> None:
    """All --skip-* flags result in tier_1/tier_2 being marked SKIPPED, not run."""
    (tmp_path / "src").mkdir()
    out = tmp_path / "report.json"
    result = subprocess.run([
        "python3", str(GATE),
        "--source-root", str(tmp_path / "src"),
        "--phase", "test-1.0",
        "--report-out", str(out),
        "--skip-typecheck", "--skip-lint", "--skip-tests", "--skip-debug-grep",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["tier_1"]["typecheck"]["status"] == "SKIPPED"
    assert report["tier_2"]["status"] == "SKIPPED"
```

- [ ] **Step 2: Run failing tests**

Run: `cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix" && python3 -m pytest tests/test_pre_test_runner.py -v`
Expected: 3 failures.

- [ ] **Step 3: Write the runner library**

Create `scripts/lib/pre_test_runner.py`:

```python
"""pre_test_runner — Tier 1 (static) + Tier 2 (local tests) library.

Reuses regression_smoke.detect_runner for runner detection. Adds:
  - Tier 1: typecheck (tsc / mypy / cargo check), lint (eslint / ruff /
            clippy), debug-leftover grep, secret scan
  - Tier 2: unit + integration tests via detected runner

Each check returns {"status": "PASS|BLOCK|SKIPPED", "evidence": [...], "duration_ms": N}.
"""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Any

DEBUG_PATTERNS = [
    (re.compile(r"console\.log\b"), "console.log"),
    (re.compile(r"\bdebugger\b"), "debugger statement"),
    (re.compile(r"binding\.pry\b"), "binding.pry"),
    (re.compile(r"\bTODO:\s*remove\b", re.IGNORECASE), "TODO:remove marker"),
    (re.compile(r"//\s*FIXME\s*HACK", re.IGNORECASE), "FIXME HACK marker"),
    (re.compile(r"\bbreakpoint\(\)"), "Python breakpoint()"),
]
SOURCE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".py", ".rs", ".go")


def grep_debug_leftovers(root: Path) -> dict[str, Any]:
    """Tier 1: scan source files for debug leftovers."""
    started = time.monotonic()
    evidence: list[dict] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in SOURCE_EXTS:
            continue
        if "node_modules" in path.parts or ".git" in path.parts or "dist" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for rx, label in DEBUG_PATTERNS:
                if rx.search(line):
                    evidence.append({
                        "file": str(path),
                        "line": i,
                        "label": label,
                        "snippet": line.strip()[:200],
                    })
    duration_ms = int((time.monotonic() - started) * 1000)
    return {
        "status": "BLOCK" if evidence else "PASS",
        "evidence": evidence,
        "duration_ms": duration_ms,
    }


def run_typecheck(repo_root: Path) -> dict[str, Any]:
    """Tier 1: typecheck. Detect via package.json scripts.typecheck or tsconfig.json."""
    started = time.monotonic()
    pj = repo_root / "package.json"
    cmd: list[str] | None = None
    if pj.exists():
        try:
            import json as _json
            data = _json.loads(pj.read_text(encoding="utf-8"))
            scripts = data.get("scripts", {})
            if "typecheck" in scripts:
                cmd = ["npm", "run", "typecheck"]
            elif (repo_root / "tsconfig.json").exists():
                cmd = ["npx", "tsc", "--noEmit"]
        except (OSError, ValueError):
            pass
    if not cmd and (repo_root / "Cargo.toml").exists():
        cmd = ["cargo", "check"]
    if not cmd:
        return {"status": "SKIPPED", "reason": "no typecheck tool detected", "duration_ms": 0}

    try:
        proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, timeout=180)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return {"status": "BLOCK", "reason": f"runner failed: {e}", "duration_ms": int((time.monotonic() - started) * 1000)}
    return {
        "status": "PASS" if proc.returncode == 0 else "BLOCK",
        "stdout_tail": proc.stdout[-500:] if proc.stdout else "",
        "stderr_tail": proc.stderr[-500:] if proc.stderr else "",
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def run_lint(repo_root: Path) -> dict[str, Any]:
    """Tier 1: lint. Detect via package.json scripts.lint or pyproject.toml ruff."""
    started = time.monotonic()
    pj = repo_root / "package.json"
    cmd: list[str] | None = None
    if pj.exists():
        try:
            import json as _json
            data = _json.loads(pj.read_text(encoding="utf-8"))
            if "lint" in data.get("scripts", {}):
                cmd = ["npm", "run", "lint"]
        except (OSError, ValueError):
            pass
    if not cmd and (repo_root / "pyproject.toml").exists():
        try:
            content = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
            if "ruff" in content:
                cmd = ["ruff", "check", "."]
        except OSError:
            pass
    if not cmd:
        return {"status": "SKIPPED", "reason": "no lint tool detected", "duration_ms": 0}

    try:
        proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, timeout=120)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return {"status": "BLOCK", "reason": f"runner failed: {e}", "duration_ms": int((time.monotonic() - started) * 1000)}
    return {
        "status": "PASS" if proc.returncode == 0 else "BLOCK",
        "stdout_tail": proc.stdout[-500:] if proc.stdout else "",
        "stderr_tail": proc.stderr[-500:] if proc.stderr else "",
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def run_tier_2_tests(repo_root: Path) -> dict[str, Any]:
    """Tier 2: unit + integration tests via detect_runner from regression_smoke."""
    started = time.monotonic()
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))
    from regression_smoke import detect_runner  # type: ignore
    runner = detect_runner(repo_root)
    if not runner:
        return {"status": "SKIPPED", "reason": "no test runner detected", "duration_ms": 0}

    cmds = {
        "vitest": ["npx", "vitest", "run", "--reporter=basic"],
        "jest":   ["npx", "jest", "--passWithNoTests"],
        "pytest": ["python3", "-m", "pytest", "-q"],
        "cargo":  ["cargo", "test"],
    }
    cmd = cmds.get(runner)
    if not cmd:
        return {"status": "SKIPPED", "reason": f"unknown runner: {runner}", "duration_ms": 0}

    try:
        proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, timeout=600)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return {"status": "BLOCK", "reason": f"runner failed: {e}", "duration_ms": int((time.monotonic() - started) * 1000)}
    return {
        "status": "PASS" if proc.returncode == 0 else "BLOCK",
        "runner": runner,
        "stdout_tail": proc.stdout[-1000:] if proc.stdout else "",
        "stderr_tail": proc.stderr[-1000:] if proc.stderr else "",
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
```

- [ ] **Step 4: Write the validator wrapper**

Create `scripts/validators/verify-pre-test-tier-1-2.py`:

```python
#!/usr/bin/env python3
"""verify-pre-test-tier-1-2.py — STEP 6.5 Tier 1 + Tier 2 gate.

Runs Tier 1 (static: typecheck + lint + debug-leftover grep) + Tier 2
(unit/integration tests). Writes a JSON report. Exits 1 on any BLOCK,
0 if all PASS or SKIPPED.

Skip flags (for partial runs):
  --skip-typecheck --skip-lint --skip-tests --skip-debug-grep
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from pre_test_runner import (  # type: ignore
    grep_debug_leftovers, run_typecheck, run_lint, run_tier_2_tests,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--report-out", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--skip-typecheck", action="store_true")
    parser.add_argument("--skip-lint", action="store_true")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-debug-grep", action="store_true")
    args = parser.parse_args()

    src = Path(args.source_root)
    repo_root = Path(args.repo_root).resolve()
    if not src.exists():
        print(f"ERROR: source-root not found: {src}", file=sys.stderr)
        return 2

    skipped = lambda reason: {"status": "SKIPPED", "reason": reason, "duration_ms": 0}

    report = {
        "phase": args.phase,
        "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tier_1": {
            "typecheck":      skipped("--skip-typecheck") if args.skip_typecheck else run_typecheck(repo_root),
            "lint":           skipped("--skip-lint")      if args.skip_lint      else run_lint(repo_root),
            "debug_leftover": skipped("--skip-debug-grep") if args.skip_debug_grep else grep_debug_leftovers(src),
        },
        "tier_2": skipped("--skip-tests") if args.skip_tests else run_tier_2_tests(repo_root),
        "completed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    Path(args.report_out).write_text(json.dumps(report, indent=2), encoding="utf-8")

    blocks: list[str] = []
    for k, v in report["tier_1"].items():
        if isinstance(v, dict) and v.get("status") == "BLOCK":
            blocks.append(f"tier_1.{k}")
    if isinstance(report["tier_2"], dict) and report["tier_2"].get("status") == "BLOCK":
        blocks.append("tier_2")

    if blocks:
        print(f"⛔ pre-test BLOCK: {', '.join(blocks)}", file=sys.stderr)
        print(f"   Report: {args.report_out}", file=sys.stderr)
        return 1

    print(f"✓ pre-test T1+T2: all PASS or SKIPPED ({args.report_out})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Make executable + run tests**

Run:
```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
chmod +x scripts/validators/verify-pre-test-tier-1-2.py
python3 -m pytest tests/test_pre_test_runner.py -v
```
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/pre_test_runner.py scripts/validators/verify-pre-test-tier-1-2.py tests/test_pre_test_runner.py
git commit -m "feat(pre-test): T1 (static) + T2 (local tests) runners with debug-leftover grep"
```



---

## Codex Round 2 Correction A (mandatory — apply on top of the original task body above)

### Correction A — Task 15: missing-expected-tooling = BLOCK; add secret scan

**Problem (Codex #5, #6):** Task 15 silently treats missing typecheck/
lint/test tooling as `SKIPPED`. If ENV-BASELINE.md declares the tooling
exists, missing commands at runtime indicate misconfiguration → must
BLOCK or TRIAGE, not silent pass. Also: docstring claims secret scan,
but only debug-leftover grep is implemented.

**Patch 1 — Augment `pre_test_runner.py` with ENV-BASELINE awareness:**

Add to `scripts/lib/pre_test_runner.py`:

```python
import re as _re
from typing import Iterable

# Secret patterns — conservative high-precision regex (low false-positive set).
SECRET_PATTERNS = [
    (_re.compile(r"AKIA[0-9A-Z]{16}"),                          "AWS Access Key ID"),
    (_re.compile(r"\bASIA[0-9A-Z]{16}\b"),                      "AWS Temporary Access Key"),
    (_re.compile(r"\bgh[opsu]_[A-Za-z0-9_]{36,}\b"),            "GitHub Token"),
    (_re.compile(r"\bxox[abprsoa]-\d{10,}-\d{10,}-[a-zA-Z0-9-]+\b"), "Slack Token"),
    (_re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"), "Private Key Block"),
    (_re.compile(r"\bsk_(?:test_|live_)[A-Za-z0-9]{24,}\b"),    "Stripe Secret"),
    (_re.compile(r"sq0(?:atp|csp)-[A-Za-z0-9_-]{22,}"),         "Square Token"),
    (_re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),                 "Google API Key"),
]


def grep_secrets(root: Path) -> dict[str, Any]:
    """Tier 1: scan for high-confidence secret patterns. PASS if none, BLOCK if any.
    Skips test fixtures + node_modules + .git + dist."""
    started = time.monotonic()
    evidence: list[dict] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in SOURCE_EXTS + (".env", ".yaml", ".yml", ".json"):
            continue
        if any(p in path.parts for p in ("node_modules", ".git", "dist", "build", "fixtures", "__fixtures__")):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for rx, label in SECRET_PATTERNS:
                if rx.search(line):
                    evidence.append({
                        "file": str(path),
                        "line": i,
                        "label": label,
                        "snippet": "<redacted — secret pattern matched>",  # never echo the secret
                    })
    return {
        "status": "BLOCK" if evidence else "PASS",
        "evidence": evidence,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def declared_tools(env_baseline_path: Path) -> dict[str, bool]:
    """Read ENV-BASELINE.md `Recommended tech stack` rows; return a map
    {"typecheck": True/False, "lint": True/False, "unit_test": True/False}."""
    declared = {"typecheck": False, "lint": False, "unit_test": False}
    if not env_baseline_path.exists():
        return declared
    try:
        text = env_baseline_path.read_text(encoding="utf-8")
    except OSError:
        return declared
    declared["typecheck"]  = bool(_re.search(r"^\|\s*Type[ -]?check", text, _re.MULTILINE | _re.IGNORECASE))
    declared["lint"]       = bool(_re.search(r"^\|\s*Lint", text, _re.MULTILINE | _re.IGNORECASE))
    declared["unit_test"]  = bool(_re.search(r"^\|\s*Test\s*\(unit\)|^\|\s*Test\s*\(integration\)",
                                              text, _re.MULTILINE | _re.IGNORECASE))
    return declared
```

**Patch 2 — Validator promotes SKIPPED→BLOCK when ENV-BASELINE expected:**

In `scripts/validators/verify-pre-test-tier-1-2.py`, after computing
each step's status, apply the promotion:

```python
# After report is built, before exit code computation:
declared = declared_tools(Path(args.env_baseline or ".vg/ENV-BASELINE.md"))

def _promote_if_expected(check_name: str, expected_key: str, result: dict) -> dict:
    """Codex round 2: missing-expected-tooling = BLOCK, not SKIPPED."""
    if result.get("status") == "SKIPPED" and declared.get(expected_key):
        return {
            **result,
            "status": "BLOCK",
            "reason": f"ENV-BASELINE.md declares {expected_key} but no tool detected at runtime",
            "promoted_from": "SKIPPED",
        }
    return result

report["tier_1"]["typecheck"] = _promote_if_expected("typecheck", "typecheck", report["tier_1"]["typecheck"])
report["tier_1"]["lint"]      = _promote_if_expected("lint", "lint", report["tier_1"]["lint"])
report["tier_2"]              = _promote_if_expected("tier_2", "unit_test", report["tier_2"])

# Add secret scan to tier_1
report["tier_1"]["secret_scan"] = (
    skipped("--skip-secret-scan") if args.skip_secret_scan
    else grep_secrets(src)
)
```

Add CLI flag `--skip-secret-scan` + `--env-baseline <path>` (default `.vg/ENV-BASELINE.md`).

**Patch 3 — Tests for the new behavior:**

Append to `tests/test_pre_test_runner.py`:

```python
def test_missing_typecheck_with_env_baseline_declared_blocks(tmp_path: Path) -> None:
    """ENV-BASELINE declares typecheck → missing tool at runtime = BLOCK."""
    (tmp_path / "src").mkdir()
    eb = tmp_path / "ENV-BASELINE.md"
    eb.write_text(textwrap.dedent("""
        # Environment Baseline

        **Profile:** web-fullstack

        ## Recommended tech stack
        | Layer | Tool | Version | Rationale |
        |---|---|---|---|
        | Type check | tsc strict | – | x |

        ## Environment matrix
        | Env | Purpose | Hosting | Run | Deploy | DB | Secrets | Auto |
        |---|---|---|---|---|---|---|---|
        | dev | local | localhost | dev | none | sqlite | env | – |
        | sandbox | x | y | z | rsync | pg | vault | yes |
        | staging | x | y | z | git | pg | vercel | manual |
        | prod | x | y | z | git | pg | vercel | approval |

        ## Decisions (E-XX namespace)
        ### E-01: x
        **Reasoning:** y
        **Reverse cost:** LOW
        **Sources cited:** https://x
    """).strip(), encoding="utf-8")

    out = tmp_path / "report.json"
    result = subprocess.run([
        "python3", str(GATE),
        "--source-root", str(tmp_path / "src"),
        "--phase", "test-1.0",
        "--env-baseline", str(eb),
        "--report-out", str(out),
        "--repo-root", str(tmp_path),  # no package.json → typecheck would normally SKIP
        "--skip-lint", "--skip-tests", "--skip-debug-grep", "--skip-secret-scan",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 1, "expected BLOCK on missing-expected-typecheck"
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["tier_1"]["typecheck"]["status"] == "BLOCK"
    assert report["tier_1"]["typecheck"].get("promoted_from") == "SKIPPED"


def test_secret_scan_finds_aws_key(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "config.ts").write_text(
        'const k = "AKIAIOSFODNN7EXAMPLE";  // example pattern\n', encoding="utf-8",
    )
    out = tmp_path / "report.json"
    result = subprocess.run([
        "python3", str(GATE),
        "--source-root", str(tmp_path / "src"),
        "--phase", "test-1.0",
        "--report-out", str(out),
        "--skip-typecheck", "--skip-lint", "--skip-tests", "--skip-debug-grep",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["tier_1"]["secret_scan"]["status"] == "BLOCK"
    # snippet must NOT echo the secret
    assert all("AKIA" not in e.get("snippet", "") for e in report["tier_1"]["secret_scan"]["evidence"])
```

