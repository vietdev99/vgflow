#!/usr/bin/env python3
"""
Validator: verify-vps-deploy-evidence.py

Harness v2.6 (2026-04-25): closes the "execute not just files" rule from
CLAUDE.md / user feedback memory. Quote:

  "Plans must execute, not just create: If phase goal says
   'provisioned/deployed/running/installed', plans MUST include tasks
   that RUN the code on target, not just CREATE files. Verify services
   are actually running."

Historical incident: Phase 0 GSD pipeline shipped infrastructure code
(Ansible playbooks, env templates) but no task to execute them. Phase
"shipped" with infra files committed but VPS still bare. Verify-work
local-only didn't catch it because Redis/Kafka/ClickHouse weren't running.

Lesson: phase claiming deploy-class verbs in goals MUST have runtime
evidence (SSH log + health probe + service status) in OPERATIONAL-
READINESS.md or PIPELINE-STATE deploy section.

What this validator checks:

  1. Read phase SPECS.md / PLAN.md / SUMMARY*.md → detect deploy-class
     verbs in goal/title text:
       'provisioned', 'deployed', 'running', 'installed', 'restarted',
       'configured on VPS', 'started service', 'live on'
     If NONE present → skip (not a deploy phase, no evidence needed).

  2. Required evidence (when verbs detected):
     - Phase has OPERATIONAL-READINESS.md OR
     - PIPELINE-STATE.json has deploy section with health_check_passed=true OR
     - SUMMARY.md cites runtime command output (curl ... 200, pm2 list, etc.)

  3. Anti-pattern detection (BLOCK):
     - Goal mentions "deployed to VPS" but plan tasks are all "create file"
       verbs (write, add, generate) without execute verbs (run, ssh, restart,
       reload). Per CLAUDE.md "Plans must execute" rule.

Severity: BLOCK (deploy claim without evidence is the documented incident
class).

Usage:
  verify-vps-deploy-evidence.py --phase 5
  verify-vps-deploy-evidence.py --phase 5 --strict (treat WARNs as BLOCK)

Exit codes:
  0  PASS or WARN-only (no deploy-class verbs OR evidence present)
  1  BLOCK (deploy claim, no evidence)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# Deploy-class verbs that signal "this phase changes runtime state, not
# just files". Case-insensitive whole-word match.
DEPLOY_VERBS_RE = re.compile(
    r"\b(?:provisioned|deployed|deploying|running|installed|restarted|"
    r"configured\s+on\s+(?:vps|sandbox|production)|started\s+service|"
    r"live\s+on|brought\s+up|launched|bootstrapped|migrated\s+to\s+production|"
    r"smoke\s*test\s*passed|health\s*check\s*passed|service\s*active|"
    r"pm2\s+(?:start|reload|restart)|systemctl\s+(?:start|restart|enable))\b",
    re.IGNORECASE,
)

# Verbs in PLAN tasks that indicate executor will RUN something on target.
# Distinct from "create file" verbs (write, add, generate, scaffold).
EXECUTE_VERBS_RE = re.compile(
    r"\b(?:run\b|ssh\b|restart\b|reload\b|deploy\b|provision\b|install\b|"
    r"execute\b|invoke\b|spawn\b|start\s+(?:service|server|daemon)|"
    r"pm2\b|systemctl\b|ansible-playbook|docker\s+(?:run|up|compose)|"
    r"kubectl\s+apply|terraform\s+apply|curl\b|migrate\b)\b",
    re.IGNORECASE,
)

# Runtime evidence patterns — actual command output / health probe that
# proves the service is up. Look for these in SUMMARY*.md or evidence files.
RUNTIME_EVIDENCE_RE = re.compile(
    r"(?:curl\s+-s[fF]?\s+http|"
    r"HTTP/\d\.\d\s+200|"
    r"pm2\s+(?:list|status|show)|"
    r"systemctl\s+status|"
    r"docker\s+ps|"
    r"\bSHOW\s+TABLES\b|"
    r"health[\s-]*check[\s:]*(?:passed|ok|green|200)|"
    r"smoke\s*test[\s:]*(?:passed|ok|green))",
    re.IGNORECASE,
)


def _has_deploy_verbs(text: str) -> tuple[bool, list[str]]:
    """Return (has_match, sample_verbs_seen)."""
    matches = DEPLOY_VERBS_RE.findall(text)
    return bool(matches), list(set(matches))[:5]


def _has_execute_tasks(plan_text: str) -> bool:
    """Check if PLAN.md has tasks that execute on target (not just create files)."""
    return EXECUTE_VERBS_RE.search(plan_text) is not None


def _has_runtime_evidence(phase_dir: Path) -> tuple[bool, list[str]]:
    """Check SUMMARY.md / OPERATIONAL-READINESS.md for runtime command evidence."""
    found_in: list[str] = []
    candidates = [
        phase_dir / "OPERATIONAL-READINESS.md",
        *phase_dir.glob("SUMMARY*.md"),
        phase_dir / "PIPELINE-STATE.json",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if RUNTIME_EVIDENCE_RE.search(text):
            found_in.append(candidate.name)
    return bool(found_in), found_in


def _read_pipeline_state_deploy(phase_dir: Path) -> dict | None:
    """Read PIPELINE-STATE.json deploy section if present."""
    pipeline_path = phase_dir / "PIPELINE-STATE.json"
    if not pipeline_path.exists():
        return None
    try:
        data = json.loads(pipeline_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data.get("steps", {}).get("deploy") or data.get("deploy")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", required=True)
    ap.add_argument("--strict", action="store_true",
                    help="Treat WARN findings as BLOCK")
    args = ap.parse_args()

    out = Output(validator="verify-vps-deploy-evidence")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            emit_and_exit(out)

        # Read goal-bearing artifacts
        specs_path = phase_dir / "SPECS.md"
        plan_paths = list(phase_dir.glob("PLAN*.md"))

        if not specs_path.exists():
            emit_and_exit(out)

        specs_text = specs_path.read_text(encoding="utf-8", errors="replace")
        has_verbs, verbs_seen = _has_deploy_verbs(specs_text)

        # Also scan plan files for deploy-class language
        plan_text_combined = ""
        for p in plan_paths:
            try:
                plan_text_combined += p.read_text(encoding="utf-8", errors="replace") + "\n"
            except OSError:
                pass

        plan_has_verbs, plan_verbs = _has_deploy_verbs(plan_text_combined)
        if plan_has_verbs:
            has_verbs = True
            verbs_seen = list(set(verbs_seen + plan_verbs))[:5]

        if not has_verbs:
            # Not a deploy-class phase — no evidence required
            emit_and_exit(out)

        # Phase claims deploy-class outcome → check evidence chain

        # Check 1: PLAN tasks include execute verbs (not just create-file)
        if plan_text_combined and not _has_execute_tasks(plan_text_combined):
            out.add(Evidence(
                type="deploy_phase_no_execute_tasks",
                message="Phase claims deploy outcome but PLAN tasks lack execute verbs (run/ssh/restart/deploy/etc.)",
                actual=f"Goal verbs detected: {verbs_seen}. PLAN files scanned: {[p.name for p in plan_paths]}",
                expected="At least one PLAN task must have execute verb (run, ssh, restart, reload, deploy, pm2 start, systemctl restart, ansible-playbook, etc.)",
                fix_hint="Add a task to PLAN that EXECUTES the deploy. Per CLAUDE.md rule: 'Plans must execute, not just create'. File-creation tasks alone don't change runtime state.",
            ))

        # Check 2: Runtime evidence exists (SUMMARY / OPERATIONAL-READINESS / PIPELINE-STATE)
        has_evidence, evidence_files = _has_runtime_evidence(phase_dir)
        deploy_state = _read_pipeline_state_deploy(phase_dir)
        deploy_passed = bool(deploy_state and deploy_state.get("status") in ("complete", "passed", "ok"))

        if not has_evidence and not deploy_passed:
            severity_evidence = Evidence(
                type="deploy_phase_no_runtime_evidence",
                message="Phase claims deploy outcome but no runtime evidence found in SUMMARY/OPERATIONAL-READINESS/PIPELINE-STATE",
                actual=f"Goal verbs: {verbs_seen}. Files checked: SUMMARY*.md, OPERATIONAL-READINESS.md, PIPELINE-STATE.json. None have curl 200 / pm2 list / health-check-passed signals.",
                expected="Runtime evidence: curl 200 output, pm2 list, systemctl status, health-check-passed marker, OR PIPELINE-STATE.steps.deploy.status='complete'",
                fix_hint="Run the deploy task on target. Capture command output in SUMMARY.md (e.g. `curl -s https://api.vollx.com/health` returning 200, pm2 list showing service active). Per CLAUDE.md: phase 0 incident — Ansible files committed but VPS bare; this gate prevents recurrence.",
            )
            if args.strict:
                out.add(severity_evidence)
            else:
                # Even non-strict, this is BLOCK — deploy without evidence is
                # the exact incident class CLAUDE.md describes
                out.add(severity_evidence)

    emit_and_exit(out)


if __name__ == "__main__":
    main()
