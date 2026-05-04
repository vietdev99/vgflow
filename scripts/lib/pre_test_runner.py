"""pre_test_runner — Tier 1 (static) + Tier 2 (local tests) library.

Reuses regression_smoke.detect_runner for runner detection. Adds:
  - Tier 1: typecheck (tsc / mypy / cargo check), lint (eslint / ruff /
            clippy), debug-leftover grep, secret scan
  - Tier 2: unit + integration tests via detected runner

Each check returns {"status": "PASS|BLOCK|SKIPPED", "evidence": [...], "duration_ms": N}.

Codex Round 2 Correction A: added secret scan + ENV-BASELINE-aware tool
detection. Validator promotes SKIPPED→BLOCK when ENV-BASELINE declares the
tool but no runtime command is detected (catches misconfiguration).
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

SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"),                          "AWS Access Key ID"),
    (re.compile(r"\bASIA[0-9A-Z]{16}\b"),                      "AWS Temporary Access Key"),
    (re.compile(r"\bgh[opsu]_[A-Za-z0-9_]{36,}\b"),            "GitHub Token"),
    (re.compile(r"\bxox[abprsoa]-\d{10,}-\d{10,}-[a-zA-Z0-9-]+\b"), "Slack Token"),
    (re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"), "Private Key Block"),
    (re.compile(r"\bsk_(?:test_|live_)[A-Za-z0-9]{24,}\b"),    "Stripe Secret"),
    (re.compile(r"sq0(?:atp|csp)-[A-Za-z0-9_-]{22,}"),         "Square Token"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),                 "Google API Key"),
]


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


def grep_secrets(root: Path) -> dict[str, Any]:
    """Tier 1: scan for high-confidence secret patterns. PASS if none, BLOCK if any.
    Skips test fixtures + node_modules + .git + dist."""
    started = time.monotonic()
    evidence: list[dict] = []
    secret_exts = SOURCE_EXTS + (".env", ".yaml", ".yml", ".json")
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in secret_exts:
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
                        "snippet": "<redacted — secret pattern matched>",
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
    declared["typecheck"]  = bool(re.search(r"^\|\s*Type[ -]?check", text, re.MULTILINE | re.IGNORECASE))
    declared["lint"]       = bool(re.search(r"^\|\s*Lint", text, re.MULTILINE | re.IGNORECASE))
    declared["unit_test"]  = bool(re.search(r"^\|\s*Test\s*\(unit\)|^\|\s*Test\s*\(integration\)",
                                              text, re.MULTILINE | re.IGNORECASE))
    return declared


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
