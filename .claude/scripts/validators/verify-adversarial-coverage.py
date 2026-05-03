#!/usr/bin/env python3
"""
verify-adversarial-coverage.py — v2.21.0 Hook 3.

Enforces declarative threat-model coverage on TEST-GOALS.md goals.
Reads the v2.21 `adversarial_scope` enrichment block (see
`commands/vg/_shared/templates/TEST-GOAL-enriched-template.md`).

Severity model (v1 — warn-only to avoid thrash on existing phases):
  WARN — surfaced at /vg:test step 5d + aggregated at /vg:accept
  Future v2.22+: promote to BLOCK after dogfood, opt-out via
  vg.config.md → adversarial_coverage.severity = "warn" | "block"

Coverage rules (v1):
  1. Goal has `security_checks` block but no `adversarial_scope`
     → WARN (declare threats, or `threats: []` for explicit low-risk)
  2. `security_checks.auth_model` ≠ public AND `adversarial_scope.threats`
     does NOT include `auth_bypass` or `role_escalation`
     → WARN (auth surface needs auth_bypass coverage)
  3. `security_checks.pii_fields` non-empty AND `adversarial_scope.threats`
     does NOT include `injection`
     → WARN (PII-handling surface needs injection coverage)

Override path:
  --skip-adversarial=<reason> → emit override.proposed event +
  OVERRIDE-DEBT critical entry → reviewer triages at /vg:accept.

Usage:
  verify-adversarial-coverage.py --phase-dir <path>
  verify-adversarial-coverage.py --phase-dir X --json
  verify-adversarial-coverage.py --phase-dir X --skip-adversarial="POC, no abuse model"

Exit codes:
  0 — all relevant goals covered (or no security-enriched goals)
  1 — one or more coverage gaps (WARN)
  2 — config error (TEST-GOALS missing/malformed)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# Threat → required-when rules. Empty list = no auto-required threats
# for that signal; user can still declare them voluntarily.
AUTH_THREATS = {"auth_bypass", "role_escalation"}
INJECTION_THREATS = {"injection"}


def _parse_goals(path: Path) -> tuple[list[dict], str | None]:
    """Parse TEST-GOALS.md as a sequence of YAML frontmatter blocks
    (`---` ... `---`). Each block must have an `id` field starting with
    `G-`. Returns (goals, error). Falls back gracefully if PyYAML missing
    by skipping (caller treats as 0 goals → exit 0).
    """
    if not path.exists():
        return [], f"TEST-GOALS.md not found at {path}"
    try:
        import yaml  # type: ignore
    except ImportError:
        return [], "PyYAML not installed; cannot parse adversarial_scope"

    text = path.read_text(encoding="utf-8", errors="replace")
    # Split on lines that are exactly `---` (frontmatter delimiters).
    # Track open/close pairs.
    blocks: list[str] = []
    cur: list[str] = []
    in_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "---":
            if in_block:
                blocks.append("\n".join(cur))
                cur = []
                in_block = False
            else:
                in_block = True
            continue
        if in_block:
            cur.append(line)

    goals: list[dict] = []
    for block in blocks:
        if not block.strip():
            continue
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        gid = data.get("id")
        if not isinstance(gid, str) or not gid.startswith("G-"):
            continue
        goals.append(data)
    return goals, None


def _evaluate(goal: dict) -> list[str]:
    """Return list of WARN messages (empty = no issue)."""
    sec = goal.get("security_checks") or {}
    if not isinstance(sec, dict) or not sec:
        # Goal lacks security_checks → exempt (legacy or low-risk by user
        # decision; a different validator handles whether security_checks
        # is required for the goal's domain).
        return []

    issues: list[str] = []
    adv = goal.get("adversarial_scope")
    if not isinstance(adv, dict):
        issues.append(
            "security_checks present but adversarial_scope missing — "
            "declare threats or set threats: [] explicitly with reason"
        )
        return issues

    threats = adv.get("threats")
    if threats is None:
        issues.append("adversarial_scope present but threats key missing")
        return issues

    if not isinstance(threats, list):
        issues.append(
            f"adversarial_scope.threats must be a list, got "
            f"{type(threats).__name__}"
        )
        return issues

    threat_set = {str(t).strip().lower() for t in threats if t}

    if not threat_set:
        # Explicit empty list = user decision; trust + pass.
        return []

    auth_model = (sec.get("auth_model") or "").strip().lower()
    if auth_model and auth_model != "public":
        if not threat_set & AUTH_THREATS:
            issues.append(
                f"auth_model='{auth_model}' requires adversarial_scope."
                f"threats to include one of {sorted(AUTH_THREATS)}"
            )

    pii = sec.get("pii_fields") or []
    if isinstance(pii, list) and pii and not threat_set & INJECTION_THREATS:
        issues.append(
            f"pii_fields={pii!r} requires adversarial_scope.threats "
            f"to include 'injection'"
        )

    return issues


def _find_test_goals(phase_dir: Path) -> Path | None:
    candidates = [
        phase_dir / "TEST-GOALS.md",
        phase_dir / "TEST-GOALS-ENRICHED.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--skip-adversarial", default=None,
                    help="Override: skip enforcement with audit reason")
    ap.add_argument("--severity", choices=["warn", "block"], default="warn",
                    help="v1: 'warn' (default). 'block' opt-in via "
                         "vg.config.md adversarial_coverage.severity for "
                         "phases ready to enforce hard.")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    if not phase_dir.exists():
        msg = {"verdict": "ERROR", "reason": f"phase dir missing: {phase_dir}"}
        print(json.dumps(msg, indent=2))
        return 2

    goals_path = _find_test_goals(phase_dir)
    if not goals_path:
        msg = {"verdict": "SKIP", "reason": "TEST-GOALS.md not found"}
        if args.json:
            print(json.dumps(msg, indent=2))
        else:
            print(f"\033[33mSKIP — TEST-GOALS.md missing in {phase_dir}\033[0m")
        return 0

    if args.skip_adversarial:
        msg = {
            "verdict": "OVERRIDE",
            "reason": args.skip_adversarial,
            "phase_dir": str(phase_dir),
        }
        if args.json:
            print(json.dumps(msg, indent=2))
        else:
            print(f"\033[33mOVERRIDE — adversarial coverage skipped: \033[0m"
                  f"{args.skip_adversarial}")
            print(f"  Audit trail: emit override.proposed event manually "
                  f"or via /vg:override-resolve.")
        return 0

    goals, err = _parse_goals(goals_path)
    if err:
        msg = {"verdict": "ERROR", "reason": err}
        if args.json:
            print(json.dumps(msg, indent=2))
        else:
            print(f"\033[38;5;208m{err}\033[0m")
        return 2

    findings: list[dict] = []
    for g in goals:
        issues = _evaluate(g)
        for issue in issues:
            findings.append({
                "goal_id": g.get("id"),
                "title": g.get("title"),
                "issue": issue,
            })

    result = {
        "verdict": "PASS" if not findings else
                   ("BLOCK" if args.severity == "block" else "WARN"),
        "phase_dir": str(phase_dir),
        "goals_examined": len(goals),
        "issues_count": len(findings),
        "findings": findings,
        "severity": args.severity,
    }
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if not findings:
            print(f"✓ adversarial coverage OK ({len(goals)} goal(s) "
                  f"examined, no gaps)")
        else:
            print(f"\033[33m{len(findings)} adversarial-coverage gap(s) \033[0m"
                  f"in {len(goals)} goal(s):")
            for f in findings:
                print(f"  [{f['goal_id']}] {f['title']}")
                print(f"    → {f['issue']}")
            print()
            print("Resolution paths:")
            print("  1. Add adversarial_scope.threats to each affected goal")
            print("  2. Set threats: [] with comment if low-risk")
            print("  3. Override (logs critical OVERRIDE-DEBT entry):")
            print("     /vg:override-resolve … or pass "
                  "--skip-adversarial='<reason>'")
    if not findings:
        return 0
    return 1 if args.severity != "block" else 1


if __name__ == "__main__":
    sys.exit(main())
