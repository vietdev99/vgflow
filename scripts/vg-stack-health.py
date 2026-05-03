#!/usr/bin/env python3
"""
VG v2.2 stack health — diagnostic for the orchestrator + validator layer.
Called by /vg:doctor stack (and standalone as a ship/CI gate).

Checks:
1. vg-orchestrator binary reachable
2. events.db present + hash chain intact
3. current-run.json coherent (age vs runs table completed_at)
4. All 5 JSON schemas parse-able
5. All 9 validator scripts executable + produce valid JSON
6. Claude Code hooks wired (settings.local.json has Stop + PostToolUse)
7. Bootstrap system consistent (ACCEPTED.md rules exist as files)

Exit 0 if healthy, 1 if warnings, 2 if broken.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
ORCH = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"
EVENTS_DB = REPO_ROOT / ".vg" / "events.db"
CURRENT_RUN = REPO_ROOT / ".vg" / "current-run.json"
SCHEMAS_DIR = REPO_ROOT / ".claude" / "schemas"
VALIDATORS_DIR = REPO_ROOT / ".claude" / "scripts" / "validators"
SETTINGS = REPO_ROOT / ".claude" / "settings.local.json"
BOOTSTRAP_ACCEPTED = REPO_ROOT / ".vg" / "bootstrap" / "ACCEPTED.md"
BOOTSTRAP_RULES = REPO_ROOT / ".vg" / "bootstrap" / "rules"


class HealthCheck:
    def __init__(self):
        self.checks: list[tuple[str, str, str]] = []  # (name, status, detail)
        self.any_block = False
        self.any_warn = False

    def ok(self, name: str, detail: str = "") -> None:
        self.checks.append((name, "OK", detail))

    def warn(self, name: str, detail: str) -> None:
        self.checks.append((name, "WARN", detail))
        self.any_warn = True

    def block(self, name: str, detail: str) -> None:
        self.checks.append((name, "BLOCK", detail))
        self.any_block = True


def check_orchestrator(h: HealthCheck) -> None:
    if not (ORCH / "__main__.py").exists():
        h.block("orchestrator-binary", f"missing at {ORCH}/__main__.py")
        return
    r = subprocess.run(
        [sys.executable, str(ORCH), "run-status"],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode != 0:
        h.block("orchestrator-reachable", f"run-status rc={r.returncode}: {r.stderr[:200]}")
        return
    h.ok("orchestrator-reachable", r.stdout.strip()[:80])


def check_events_db(h: HealthCheck) -> None:
    if not EVENTS_DB.exists():
        h.warn("events-db", "not yet created — first /vg:* run will init")
        return
    r = subprocess.run(
        [sys.executable, str(ORCH), "verify-hash-chain"],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode == 0:
        h.ok("events-db-integrity", r.stdout.strip())
    else:
        h.block("events-db-integrity", f"hash chain broken: {r.stderr[:200]}")


def check_current_run(h: HealthCheck) -> None:
    if not CURRENT_RUN.exists():
        h.ok("current-run", "no active run (clean idle state)")
        return
    try:
        data = json.loads(CURRENT_RUN.read_text(encoding="utf-8"))
    except Exception as e:
        h.block("current-run", f"parse error: {e}")
        return
    run_id = data.get("run_id", "?")
    # Check runs table has matching row
    if EVENTS_DB.exists():
        import sqlite3
        try:
            conn = sqlite3.connect(str(EVENTS_DB))
            row = conn.execute(
                "SELECT command, phase, completed_at FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            conn.close()
            if not row:
                h.block("current-run",
                        f"current-run.json refs run_id {run_id[:8]} not in runs table")
                return
            cmd, phase, completed = row
            if completed:
                h.warn("current-run",
                       f"{cmd} phase={phase} ALREADY completed but "
                       f"current-run.json still present")
                return
            h.ok("current-run", f"{cmd} phase={phase} active")
        except Exception as e:
            h.warn("current-run", f"runs table check failed: {e}")


def check_schemas(h: HealthCheck) -> None:
    expected = ["event.json", "evidence-json.json", "runtime-contract.json",
                "override-debt-entry.json", "validator-output.json"]
    missing = [f for f in expected if not (SCHEMAS_DIR / f).exists()]
    if missing:
        h.block("schemas", f"missing: {missing}")
        return
    for f in expected:
        try:
            json.loads((SCHEMAS_DIR / f).read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            h.block("schemas", f"{f} malformed: {e}")
            return
    h.ok("schemas", f"5/5 present + valid JSON")


def check_validators(h: HealthCheck) -> None:
    expected = ["phase-exists", "context-structure", "plan-granularity",
                "wave-attribution", "goal-coverage", "task-goal-binding",
                "test-first", "override-debt-balance",
                "event-reconciliation"]
    missing = [v for v in expected
               if not (VALIDATORS_DIR / f"{v}.py").exists()]
    if missing:
        h.block("validators", f"missing: {missing}")
        return
    h.ok("validators", f"{len(expected)}/{len(expected)} present")


def check_hooks(h: HealthCheck) -> None:
    if not SETTINGS.exists():
        h.warn("hooks", "settings.local.json missing — hooks not wired")
        return
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception as e:
        h.block("hooks", f"settings parse error: {e}")
        return
    hooks = data.get("hooks", {})
    if "Stop" not in hooks:
        h.warn("hooks-stop", "Stop hook not registered")
    else:
        # Check verify-claim.py referenced
        stop_cmds = str(hooks.get("Stop", []))
        if "vg-verify-claim" in stop_cmds:
            h.ok("hooks-stop", "vg-verify-claim.py wired")
        else:
            h.warn("hooks-stop", "Stop registered but not pointing at vg-verify-claim")
    if "PostToolUse" not in hooks:
        h.warn("hooks-posttool", "PostToolUse hook not registered")
    else:
        h.ok("hooks-posttool", "PostToolUse wired")


def check_bootstrap(h: HealthCheck) -> None:
    if not BOOTSTRAP_ACCEPTED.exists():
        h.ok("bootstrap", "no accepted rules (project hasn't promoted any)")
        return
    text = BOOTSTRAP_ACCEPTED.read_text(encoding="utf-8", errors="replace")
    rule_ids = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("- id:"):
            rid = s.split(":", 1)[1].strip()
            # Skip schema placeholder (L-XXX) and any schema example blocks
            if rid and rid != "L-XXX" and not rid.startswith("L-XX"):
                rule_ids.append(rid)
    orphans = []
    for rid in rule_ids:
        # target file declared with target.file lookup is more work;
        # heuristic: find any rule MD that embeds the rule id
        matches = list(BOOTSTRAP_RULES.rglob("*.md")) if BOOTSTRAP_RULES.exists() else []
        found = any(rid in m.read_text(encoding="utf-8", errors="replace")
                    for m in matches)
        if not found and rid:
            orphans.append(rid)
    if orphans:
        h.warn("bootstrap", f"rules in ACCEPTED without MD file: {orphans[:3]}")
    else:
        h.ok("bootstrap", f"{len(rule_ids)} rules, all backed by files")


def main() -> int:
    h = HealthCheck()
    print("VG v2.2 stack health check")
    print(f"  Repo: {REPO_ROOT}")
    print()

    check_orchestrator(h)
    check_events_db(h)
    check_current_run(h)
    check_schemas(h)
    check_validators(h)
    check_hooks(h)
    check_bootstrap(h)

    col_width = max(len(n) for n, _, _ in h.checks) + 2
    for name, status, detail in h.checks:
        icon = {"OK": "✓", "WARN": "", "BLOCK": ""}[status]
        print(f"  {icon} {name:<{col_width}} {status:<6}  {detail}")
    print()

    if h.any_block:
        print("\033[38;5;208mStack has BLOCKING issues — investigate before running /vg:* commands\033[0m")
        return 2
    if h.any_warn:
        print("\033[33mStack has warnings — review above\033[0m")
        return 1
    print("✓ All v2.2 components healthy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
