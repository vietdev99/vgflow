"""Recovery path lookup table for runtime_contract violations.

When orchestrator BLOCKs run-complete, the message includes generic options
("Run missing step", "override --flag", "abort"). Closes UX dead-end where
users see BLOCK but don't know concrete next steps.

Each violation type maps to ordered recovery paths (recommended first).
Each path has:
  - id:                short identifier
  - label:             one-line description (with RECOMMENDED tag if primary)
  - command:           shell command OR workflow instruction
  - cost:              time + token estimate
  - effect:            what changes after path runs
  - when:              when this path is appropriate
  - auto_executable:   true = AI can run autonomously (safe, logs debt only)
                       false = needs user confirmation (expensive/destructive)
  - auto_command:      shell command for auto-execution (if differs from `command`)

Auto-execution policy (closes "BLOCK = stop" anti-pattern):
- vg-recovery.py --auto picks FIRST auto_executable=true path, runs it, retries
- Only safe operations: log OVERRIDE-DEBT, run migrate-state, retry validator
- NEVER auto-runs: --retry-failed (token-expensive), code edits, matrix changes

Usage from orchestrator:
    from recovery_paths import get_recovery_paths
    paths = get_recovery_paths(violation_type, command, phase)
    for p in paths: ...
"""
from __future__ import annotations

from typing import Any


# Static lookup keyed by violation_type. Variables {phase}, {flag} etc.
# are formatted by callers via str.format().
RECOVERY_PATHS: dict[str, list[dict[str, str]]] = {
    # ─── Runtime contract validators (review.md Phase 4) ────────────────
    "validator:runtime-map-crud-depth": [
        {
            "id": "retry-failed",
            "label": "Re-scan blocked goals (RECOMMENDED)",
            "command": "/{command} {phase} --retry-failed --with-deepscan --target-env=sandbox",
            "cost": "~30-45min wall, ~$3-5/goal tokens",
            "effect": "Refresh RUNTIME-MAP via Haiku per-goal rescan with v2.46+ scanner schema",
            "when": "ship-critical phase, want real mutation evidence",
            "auto_executable": False,  # token-expensive; user must opt in
        },
        {
            "id": "skip-flag",
            "label": "Per-run skip + log debt",
            "command": "/{command} {phase} --skip-runtime-map-crud-depth=<reason>",
            "cost": "0min, logs OVERRIDE-DEBT.md entry",
            "effect": "Bypass validator for this run; debt accumulates to /vg:accept",
            "when": "tactical bypass, will properly fix next session",
            "auto_executable": True,
            "auto_command": "python3 .claude/scripts/vg-orchestrator override --flag skip-runtime-map-crud-depth --reason 'auto-recovery: stale RUNTIME-MAP; debt to /vg:accept'",
        },
        {
            "id": "manual-reclassify",
            "label": "Edit RUNTIME-MAP.json (last resort)",
            "command": "Change goal_sequences[gid].result: passed → blocked with reason",
            "cost": "~5min manual edit",
            "effect": "Validator skips because goal no longer claims passed",
            "when": "data drift acceptable; document re-scan need",
            "auto_executable": False,  # data integrity risk
        },
    ],
    "validator:mutation-actually-submitted": [
        {
            "id": "retry-failed-deepscan",
            "label": "Re-spawn scanners with Anti-Cancel enforcement (RECOMMENDED)",
            "command": "/{command} {phase} --retry-failed --with-deepscan",
            "cost": "~30-45min, ~$3-5/goal",
            "effect": "Scanner forced to submit (sandbox = disposable seed); records 2xx network",
            "when": "want real submit evidence, no shortcut",
            "auto_executable": False,
        },
        {
            "id": "skip-flag",
            "label": "Per-run override (logs debt)",
            "command": "/{command} {phase} --allow-cancel-only-mutations",
            "cost": "0min, logs OVERRIDE-DEBT",
            "effect": "Validator downgrades BLOCK → WARN this run",
            "when": "scanner truly cannot submit (env constraint)",
            "auto_executable": True,
            "auto_command": "python3 .claude/scripts/vg-orchestrator override --flag allow-cancel-only-mutations --reason 'auto-recovery: scanner did not submit; debt logged'",
        },
    ],
    "validator:matrix-staleness": [
        {
            "id": "retry-failed-suspected",
            "label": "Re-scan SUSPECTED goals (RECOMMENDED)",
            "command": "/{command} {phase} --retry-failed",
            "cost": "~10-25min depending on suspected count",
            "effect": "SUSPECTED status auto-rolled into retry set; matrix gets real evidence",
            "when": "matrix=READY but no submit/2xx network detected",
            "auto_executable": False,
        },
        {
            "id": "re-scan-targeted",
            "label": "Re-scan only specific goals",
            "command": "/{command} {phase} --re-scan-goals=G-XX,G-YY",
            "cost": "~3-8min per goal",
            "effect": "Bypass matrix, force scanner on listed goals only",
            "when": "you know exactly which goals are stale (per .matrix-staleness.json)",
            "auto_executable": False,
        },
        {
            "id": "dogfood-all",
            "label": "Re-scan ALL mutation goals (most thorough)",
            "command": "/{command} {phase} --dogfood",
            "cost": "~30-60min depending on goal count",
            "effect": "Every goal with mutation_evidence gets re-scanned regardless of matrix status",
            "when": "systemic submit-evidence gap suspected",
            "auto_executable": False,
        },
        {
            "id": "allow-stale",
            "label": "Override: skip staleness check (logs debt)",
            "command": "/{command} {phase} --allow-stale-matrix",
            "cost": "0min, logs OVERRIDE-DEBT",
            "effect": "Validator downgrades BLOCK → WARN this run",
            "when": "stale acknowledged, will fix in /vg:test or /vg:roam",
            "auto_executable": True,
            "auto_command": "python3 .claude/scripts/vg-orchestrator override --flag allow-stale-matrix --reason 'auto-recovery: matrix staleness acknowledged; debt to /vg:test'",
        },
    ],
    "validator:matrix-evidence-link": [
        {
            "id": "retry-failed",
            "label": "Re-scan to record real sequences",
            "command": "/{command} {phase} --retry-failed",
            "cost": "~15-30min for failed goals only",
            "effect": "Matrix verdicts backed by goal_sequences with real evidence",
            "when": "matrix lying detected, fix properly",
        },
        {
            "id": "reclassify",
            "label": "Reclassify to UNREACHABLE/INFRA_PENDING/DEFERRED",
            "command": "Edit GOAL-COVERAGE-MATRIX.md with justification per goal",
            "cost": "~5-10min",
            "effect": "Goals declare honest state, validator passes",
            "when": "goals truly not testable in current env",
        },
    ],
    "validator:rcrurd-depth": [
        {
            "id": "retry-failed-deepscan",
            "label": "Re-spawn with proper depth (RECOMMENDED)",
            "command": "/{command} {phase} --retry-failed --with-deepscan",
            "cost": "~30-45min",
            "effect": "Scanner runs full RCRURD lifecycle per goal_class threshold",
            "when": "shallow scans need proper re-scan",
        },
        {
            "id": "allow-shallow",
            "label": "Allow shallow scans this run",
            "command": "/{command} {phase} --allow-shallow-scans",
            "cost": "0min, logs OVERRIDE-DEBT",
            "effect": "BLOCK → WARN; debt to /vg:accept",
            "when": "tactical bypass",
        },
    ],
    "validator:asserted-rule-match": [
        {
            "id": "retry-with-asserted-quotes",
            "label": "Re-scan with verbatim asserted_quote schema",
            "command": "/{command} {phase} --retry-failed --with-deepscan",
            "cost": "~30-45min",
            "effect": "Scanner records verbatim BR-NN quotes per mutation step",
            "when": "drift in old scanner output",
        },
        {
            "id": "allow-drift",
            "label": "Allow asserted_quote drift",
            "command": "/{command} {phase} --allow-asserted-drift",
            "cost": "0min, logs debt",
            "effect": "BLOCK → WARN",
            "when": "drift acceptable for this run",
        },
    ],
    "validator:goal-traceability": [
        {
            "id": "backfill",
            "label": "Run backfill helper (auto-populate fields)",
            "command": "python3 .claude/scripts/backfill-goal-traceability.py",
            "cost": "~10sec, requires post-fill manual review",
            "effect": "Auto-populate spec_ref + decisions + business_rules + expected_assertion + goal_class",
            "when": "migrating phase from pre-v2.46",
        },
        {
            "id": "set-warn-mode",
            "label": "Switch to warn mode globally",
            "command": "Edit .claude/vg.config.md → traceability_mode: warn",
            "cost": "1min",
            "effect": "All traceability validators downgrade to WARN until backfilled",
            "when": "migration phase, multiple phases need backfill",
        },
        {
            "id": "allow-gaps",
            "label": "Per-run override",
            "command": "/{command} {phase} --allow-traceability-gaps",
            "cost": "0min, logs debt",
            "effect": "BLOCK → WARN",
            "when": "tactical bypass",
        },
    ],
    "validator:decisions-trace": [
        {
            "id": "add-quote-source",
            "label": "Add Quote source: field to D-XX entries",
            "command": "Edit CONTEXT.md — add **Quote source:** DISCUSSION-LOG.md#round-N to each D-XX",
            "cost": "~10-30min depending on # decisions",
            "effect": "Decisions traceable to user answers",
            "when": "scope phase needs proper traceability",
        },
        {
            "id": "allow-untraced",
            "label": "Per-run override",
            "command": "/{command} {phase} --allow-decisions-untraced",
            "cost": "0min, logs debt",
            "effect": "BLOCK → WARN",
            "when": "tactical, fix at next /vg:scope iteration",
        },
    ],
    "validator:decisions-to-tasks": [
        {
            "id": "add-task-refs",
            "label": "Add D-XX references to PLAN tasks",
            "command": "Edit PLAN*.md — cite 'Per CONTEXT.md D-XX' or 'Decisions: [D-XX]' in task body",
            "cost": "~5-10min",
            "effect": "Every D-XX maps to ≥1 task",
            "when": "blueprint missed implementing decision",
        },
        {
            "id": "rerun-blueprint",
            "label": "Re-run /vg:blueprint to refresh plans",
            "command": "/vg:blueprint {phase} --from=plan",
            "cost": "~10-20min",
            "effect": "Blueprint re-generates plans with all decisions covered",
            "when": "many decisions uncovered",
        },
    ],
    "validator:scanner-business-alignment": [
        {
            "id": "spawn-verifier",
            "label": "Spawn adversarial Haiku verifier",
            "command": "Read .tmp/business-alignment-prompts.jsonl, spawn 1 Haiku per goal, write results to .tmp/business-alignment-results.jsonl, then re-run validator with --verifier-results",
            "cost": "~5min per goal × N goals",
            "effect": "Adversarial verdict on scanner-vs-goal alignment",
            "when": "ship-critical, want adversarial check",
        },
        {
            "id": "allow-business-drift",
            "label": "Per-run override",
            "command": "/{command} {phase} --allow-business-drift",
            "cost": "0min, logs debt",
            "effect": "BLOCK → WARN",
            "when": "verifier-spawn infrastructure unavailable",
        },
    ],
    # ─── Telemetry contract violations ──────────────────────────────────
    "must_emit_telemetry": [
        {
            "id": "complete-skill",
            "label": "Run skill to completion",
            "command": "/{command} {phase}  (let skill run all steps without interruption)",
            "cost": "varies by skill (5-45min)",
            "effect": "Each skill step emits required events at end",
            "when": "skill was interrupted mid-run",
        },
        {
            "id": "manual-emit",
            "label": "Manually emit missing events",
            "command": "python3 .claude/scripts/vg-orchestrator emit-event <event_type> --payload '{...}'",
            "cost": "~1min per event",
            "effect": "Events recorded; validators see evidence",
            "when": "skill genuinely completed but events missed (orchestrator bug)",
        },
    ],
    "must_write": [
        {
            "id": "complete-skill",
            "label": "Run skill to completion",
            "command": "/{command} {phase}",
            "cost": "varies",
            "effect": "Skill writes required artifacts",
            "when": "skill interrupted",
        },
    ],
    "must_touch_markers": [
        {
            "id": "migrate-state",
            "label": "Auto-migrate missing markers (RECOMMENDED for upgrade-drift)",
            "command": "python3 .claude/scripts/migrate-state.py {phase} --apply",
            "cost": "~5sec",
            "effect": "Backfills missing step markers from completed artifacts",
            "when": "VG harness upgraded, old markers don't match new schema",
        },
    ],
    "forbidden_without_override": [
        {
            "id": "log-override",
            "label": "Log override-debt entry",
            "command": "python3 .claude/scripts/vg-orchestrator override --flag {flag} --reason '<text>'",
            "cost": "~30sec",
            "effect": "Override registered; flag becomes permitted this run",
            "when": "you have legitimate reason to use the flag",
        },
    ],
}


def get_recovery_paths(
    violation_type: str,
    command: str = "vg:review",
    phase: str = "<phase>",
    extra: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Return ordered recovery paths for a violation type.

    Variables in commands ({command}, {phase}, {flag}) get formatted in.
    Returns empty list if violation_type unknown — caller falls back to
    generic message.
    """
    paths = RECOVERY_PATHS.get(violation_type, [])
    if not paths:
        return []
    # Format variables in commands
    formatted: list[dict[str, str]] = []
    fmt_vars: dict[str, Any] = {"command": command, "phase": phase}
    if extra:
        fmt_vars.update(extra)
    for p in paths:
        out = dict(p)
        try:
            out["command"] = p["command"].format(**fmt_vars)
        except (KeyError, IndexError):
            pass  # Leave unformatted if vars missing
        formatted.append(out)
    return formatted


def render_recovery_block(
    violation_type: str,
    command: str,
    phase: str,
    extra: dict[str, Any] | None = None,
) -> list[str]:
    """Render recovery paths as message lines for BLOCK output."""
    paths = get_recovery_paths(violation_type, command, phase, extra)
    if not paths:
        return []
    lines = [f"  ↳ Recovery paths for [{violation_type}]:"]
    for i, p in enumerate(paths, 1):
        marker = " ★" if i == 1 else "  "
        lines.append(f"    {marker} [{i}] {p.get('label', p.get('id', '?'))}")
        lines.append(f"         $ {p.get('command', '')}")
        cost = p.get("cost", "")
        when = p.get("when", "")
        if cost or when:
            lines.append(f"         cost={cost} | when={when}")
    return lines
