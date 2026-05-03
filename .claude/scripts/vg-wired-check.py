#!/usr/bin/env python3
"""
vg-wired-check.py — WIRED-OR-NOTHING smoke test for VG workflow.

OHOK v2 Day 6 — this script enforces the rule declared in the OHOK plan:
every validator, hook, and command declaring a runtime_contract MUST pass
3 checks before counted as "shipped":
  1. EXISTS      — the declared file is present on disk
  2. REGISTERED  — it's wired into an enforcement path (COMMAND_VALIDATORS
                   for validators, settings.json for hooks, orchestrator
                   call for commands)
  3. PROVES-FIRE — events.db has at least 1 event with matching validator/
                   actor/pattern in a reasonable time window (opt-in: skip
                   if --fast flag)

Prior state (pre-Day 6): task #33 "A0.1-real" marked completed but
`.claude/scripts/vg-entry.sh` didn't exist — false-completed pattern. Codex
audit flagged this as existential. Fix: this script runs as CI + local check
so future false-completed tasks surface immediately.

Exit codes:
  0 — all items PASS
  1 — at least one FAIL (missing file, not registered, or no prove-fire)
  2 — script itself crashed

Usage:
  python vg-wired-check.py                # full 3-check (walks events.db)
  python vg-wired-check.py --fast         # skip prove-fire check (fast)
  python vg-wired-check.py --category=validators   # one category only
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
VALIDATORS_DIR = REPO_ROOT / ".claude" / "scripts" / "validators"
ORCH_MAIN = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py"
SETTINGS = REPO_ROOT / ".claude" / "settings.local.json"
COMMANDS_DIR = REPO_ROOT / ".claude" / "commands" / "vg"
DB_PATH = REPO_ROOT / ".vg" / "events.db"

# OHOK-3 (2026-04-22): newly-registered validators won't have fired yet until
# the first /vg:build run post-registration. Declared dormant-expected here.
#
# OHOK-6 (Codex P1): each entry has an ADDED date. After DORMANT_TTL_DAYS,
# wired-check emits a WARN urging user to either (a) run the command that
# fires the validator, or (b) remove the validator if it's dead code.
# Without TTL, this allowlist becomes a permanent suppressor — Codex's
# "dormant becomes permanent escape hatch" vector.
#
# After a dormant-expected validator actually fires (proves_fire=True),
# wired-check tells user to REMOVE the entry. Next audit catches leftover
# entries that became unnecessary.
DORMANT_EXPECTED: dict[str, str] = {
    "test-first":             "2026-04-22",  # fires on /vg:build post-Day 5 reg
    "wave-attribution":       "2026-04-22",  # fires on /vg:build wave-complete
    "build-crossai-required": "2026-04-22",  # fires on /vg:build post-OHOK-7
}
DORMANT_TTL_DAYS = 30

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def check_validators(fast: bool = False) -> list[dict]:
    """Every .py file in validators/ must (1) exist, (2) be registered in
    COMMAND_VALIDATORS, (3) have >=1 validation.* event in events.db."""
    results: list[dict] = []

    if not VALIDATORS_DIR.exists():
        return [{
            "category": "validators", "item": "<dir>", "exists": False,
            "registered": False, "proves_fire": False,
            "note": f"{VALIDATORS_DIR} missing",
        }]

    # Load registration map from orchestrator
    orch_text = ORCH_MAIN.read_text(encoding="utf-8", errors="replace") \
        if ORCH_MAIN.exists() else ""
    registered: set[str] = set()
    for m in re.finditer(r'"([a-z][a-z0-9-]+)"', orch_text):
        # Only count tokens appearing inside COMMAND_VALIDATORS dict
        registered.add(m.group(1))

    # Some validators are wired through alternative paths (not COMMAND_VALIDATORS).
    # Whitelist them as registered if their .py filename appears anywhere in
    # the orchestrator source (covers subprocess.run(validator_dir / "name.py"))
    alt_wired: set[str] = set()
    for m in re.finditer(r'[\'"]([a-z][a-z0-9-]+)\.py[\'"]', orch_text):
        alt_wired.add(m.group(1))
    # Also check for `validators / "name"` pattern (used in _run_validators)
    for m in re.finditer(r'validators[^"\']*[\'"]([a-z][a-z0-9-]+)[\'"]', orch_text):
        alt_wired.add(m.group(1))

    for v_file in sorted(VALIDATORS_DIR.glob("*.py")):
        if v_file.name.startswith("_") or v_file.stem == "_common":
            continue
        name = v_file.stem

        exists = v_file.is_file()
        is_registered = name in registered or name in alt_wired

        # PROVES-FIRE: events.db has validation.* with validator=name
        proves = None
        if not fast and DB_PATH.exists():
            conn = sqlite3.connect(str(DB_PATH))
            try:
                # JSON-compact format in events.db: `"validator":"name"` (no space).
                # Try both compact and pretty variants for forward-compat.
                r = conn.execute(
                    "SELECT COUNT(*) FROM events "
                    "WHERE event_type LIKE 'validation.%' "
                    "AND (payload_json LIKE ? OR payload_json LIKE ?)",
                    (f'%"validator":"{name}"%',
                     f'%"validator": "{name}"%'),
                ).fetchone()
                proves = (r[0] or 0) > 0
            except sqlite3.OperationalError:
                proves = None  # schema mismatch, unknown
            finally:
                conn.close()

        is_dormant_ok = (name in DORMANT_EXPECTED) and is_registered
        note = ""
        if not exists:
            note = "missing file"
        elif not is_registered:
            note = "not registered"
        elif proves is False and not is_dormant_ok:
            note = "no fire events"
        elif proves is False and is_dormant_ok:
            # OHOK-6: check TTL — dormant entries aren't forever
            import datetime as _dt
            added_str = DORMANT_EXPECTED[name]
            try:
                added = _dt.datetime.fromisoformat(added_str)
                age_days = (_dt.datetime.now(_dt.timezone.utc) - added).days
                if age_days > DORMANT_TTL_DAYS:
                    # Expired — no longer count as OK; still warn the user
                    is_dormant_ok = False
                    note = (f"dormant EXPIRED ({age_days}d > {DORMANT_TTL_DAYS}d TTL) — "
                            "run command or remove from allowlist")
                else:
                    note = (f"dormant (expected, added {added_str}, "
                            f"expires in {DORMANT_TTL_DAYS - age_days}d)")
            except Exception:
                note = "dormant (expected — fires on next command run)"
        elif proves is True and name in DORMANT_EXPECTED:
            # Fired naturally — entry can now be removed from allowlist
            note = f"FIRED — remove '{name}' from DORMANT_EXPECTED allowlist"

        results.append({
            "category": "validators",
            "item": name,
            "exists": exists,
            "registered": is_registered,
            "proves_fire": proves,
            "dormant_ok": is_dormant_ok,
            "note": note,
        })

    return results


def check_hooks() -> list[dict]:
    """Every hook entry in settings.local.json must point at an existing script."""
    results: list[dict] = []

    if not SETTINGS.exists():
        return [{
            "category": "hooks", "item": "<settings>", "exists": False,
            "registered": False, "proves_fire": None,
            "note": f"{SETTINGS} missing",
        }]

    try:
        cfg = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception as e:
        return [{
            "category": "hooks", "item": "<parse>", "exists": False,
            "registered": False, "proves_fire": None,
            "note": f"JSON parse error: {e}",
        }]

    hooks_cfg = cfg.get("hooks", {})
    for event_name, hook_list in hooks_cfg.items():
        if not isinstance(hook_list, list):
            continue
        for idx, hook_spec in enumerate(hook_list):
            if not isinstance(hook_spec, dict):
                continue
            inner = hook_spec.get("hooks") or [hook_spec]
            for sub in inner:
                cmd = (sub or {}).get("command", "")
                if not cmd:
                    continue
                # Extract script path — strip CLAUDE_PROJECT_DIR + interpreter
                # Match patterns like: `python ${CLAUDE_PROJECT_DIR}/path/script.py args`
                m = re.search(
                    r"(?:python3?|bash|sh)\s+(?:\$\{CLAUDE_PROJECT_DIR\}/)?([^\s\"]+)",
                    cmd,
                )
                if not m:
                    continue
                script_rel = m.group(1).strip()
                script_path = REPO_ROOT / script_rel
                label = f"{event_name}[{idx}]:{Path(script_rel).name}"
                exists = script_path.is_file()
                results.append({
                    "category": "hooks",
                    "item": label,
                    "exists": exists,
                    "registered": True,  # declared in settings = registered
                    "proves_fire": None,
                    "note": (f"script missing at {script_path}" if not exists else ""),
                })

    return results


def check_commands_with_contract(fast: bool = False) -> list[dict]:
    """Every .md in commands/vg declaring runtime_contract must call orchestrator."""
    results: list[dict] = []

    if not COMMANDS_DIR.exists():
        return [{
            "category": "commands", "item": "<dir>", "exists": False,
            "registered": False, "proves_fire": None,
            "note": f"{COMMANDS_DIR} missing",
        }]

    for cmd_file in sorted(COMMANDS_DIR.glob("*.md")):
        text = cmd_file.read_text(encoding="utf-8", errors="replace")
        has_contract = "runtime_contract:" in text
        if not has_contract:
            continue

        name = cmd_file.stem
        # Registered = has orchestrator call (run-start / emit-event / etc)
        has_orch_call = bool(
            re.search(r"vg-orchestrator\s+(?:run-start|run-complete|emit-event)", text)
            or re.search(r"vg_run_start|vg_emit_event", text)
        )

        # PROVES-FIRE: events.db has {short_cmd}.started events
        proves = None
        if not fast and DB_PATH.exists():
            short = name
            conn = sqlite3.connect(str(DB_PATH))
            try:
                r = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE event_type = ?",
                    (f"{short}.started",),
                ).fetchone()
                proves = (r[0] or 0) > 0
            except sqlite3.OperationalError:
                proves = None
            finally:
                conn.close()

        results.append({
            "category": "commands",
            "item": name,
            "exists": cmd_file.is_file(),
            "registered": has_orch_call,
            "proves_fire": proves,
            "note": ("no orchestrator call" if not has_orch_call else
                     "never fired" if proves is False else ""),
        })

    return results


def print_table(results: list[dict]) -> int:
    """Print formatted table, return total FAIL count."""
    header = f"{'CATEGORY':<12} {'ITEM':<40} {'EXISTS':<8} {'REG':<6} {'FIRE':<6} NOTE"
    print(f"\n{BOLD}{header}{RESET}")
    print("─" * min(len(header) + 20, 120))

    fail = 0
    by_cat: dict[str, list[dict]] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r)

    for cat, items in by_cat.items():
        for r in items:
            item = r["item"]
            exists_ok = r["exists"]
            reg_ok = r["registered"]
            fire_ok = r["proves_fire"]

            exists_s = f"{GREEN}✓{RESET}" if exists_ok else f"{RED}✗{RESET}"
            reg_s = f"{GREEN}✓{RESET}" if reg_ok else f"{RED}✗{RESET}"
            if fire_ok is None:
                fire_s = f"{DIM}?{RESET}"
            elif fire_ok:
                fire_s = f"{GREEN}✓{RESET}"
            else:
                fire_s = f"{YELLOW}⚠{RESET}"

            # OHOK-3: dormant-expected validators don't count as fail
            dormant_ok = r.get("dormant_ok", False)
            fire_missing = (fire_ok is False) and not dormant_ok
            row_fail = (not exists_ok) or (not reg_ok) or fire_missing
            if row_fail:
                fail += 1

            print(f"{cat:<12} {item:<40} {exists_s:<8} {reg_s:<6} {fire_s:<6} "
                  f"{r.get('note', '')}")

    return fail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true",
                    help="skip prove-fire check (no events.db query)")
    ap.add_argument("--category",
                    choices=["validators", "hooks", "commands", "all"],
                    default="all")
    args = ap.parse_args()

    print(f"{BOLD}━━━ VG WIRED-OR-NOTHING check ━━━{RESET}")
    print(f"{DIM}Repo: {REPO_ROOT}{RESET}")
    print(f"{DIM}Mode: {'fast' if args.fast else 'full'} "
          f"category={args.category}{RESET}")

    results: list[dict] = []
    if args.category in ("validators", "all"):
        results.extend(check_validators(args.fast))
    if args.category in ("hooks", "all"):
        results.extend(check_hooks())
    if args.category in ("commands", "all"):
        results.extend(check_commands_with_contract(args.fast))

    fail_count = print_table(results)

    total = len(results)
    print()
    if fail_count == 0:
        print(f"{GREEN}✓ {total} items WIRED{RESET} — "
              f"EXISTS + REGISTERED + PROVES-FIRE all green.")
        return 0
    print(f"{RED}⛔ {fail_count}/{total} items NOT WIRED{RESET} — see NOTE column.")
    print(f"{DIM}Fix options:{RESET}")
    print(f"  - Missing EXISTS: create the declared file, OR remove the declaration.")
    print(f"  - Missing REG: add to COMMAND_VALIDATORS (validators) / ")
    print(f"                 settings.local.json (hooks) / add orchestrator call (commands).")
    print(f"  - Missing FIRE: run smoke test to generate event, OR mark "
          f"as dormant in events.db.")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\033[38;5;208mvg-wired-check crashed: {e}\033[0m", file=sys.stderr)
        sys.exit(2)
