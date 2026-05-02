#!/usr/bin/env python3
"""
emit-tasklist.py — Task-list visibility helper (2026-04-24).

User requirement: "khởi tạo 1 flow nào đều phải show được Task để AI bám vào
đó mà làm". Every pipeline command entry step MUST call this helper so:
  1. User sees the authoritative step list at flow start
  2. Orchestrator emits {command}.tasklist_shown event for contract verification
  3. AI has a visible contract to follow (not a hidden internal decision)

Runs filter-steps.py to get profile-filtered step list, prints it to stdout,
emits event to orchestrator with step_list + count payload.

Usage:
  python emit-tasklist.py --command vg:build --profile web-fullstack --phase 7.14
  python emit-tasklist.py --command vg:review --profile web-fullstack --mode full --phase 3.2

Exit codes:
  0 — success, event emitted, list printed
  1 — filter-steps failed
  2 — orchestrator emit-event failed (still prints list so user sees something)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
FILTER_STEPS = REPO_ROOT / ".claude" / "scripts" / "filter-steps.py"
ORCHESTRATOR = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator"


def _safe_session_filename(sid: str) -> str:
    safe = "".join(c for c in sid if c.isalnum() or c in "-_")
    return safe or "unknown"


def _resolve_command_file(command: str) -> Path:
    # "vg:build" → .claude/commands/vg/build.md
    if ":" in command:
        ns, name = command.split(":", 1)
        return REPO_ROOT / ".claude" / "commands" / ns / f"{name}.md"
    return REPO_ROOT / ".claude" / "commands" / f"{command}.md"


def _get_step_list(command: str, profile: str, mode: str | None = None) -> list[str]:
    cmd_file = _resolve_command_file(command)
    if not cmd_file.exists():
        print(f"⛔ Command file not found: {cmd_file}", file=sys.stderr)
        return []
    filter_cmd = [
        sys.executable, str(FILTER_STEPS),
        "--command", str(cmd_file),
        "--profile", profile,
        "--output-ids",
    ]
    if mode:
        filter_cmd.extend(["--mode", mode])
    proc = subprocess.run(
        filter_cmd,
        capture_output=True, text=True, timeout=10,
    )
    if proc.returncode != 0:
        print(f"⛔ filter-steps failed: {proc.stderr}", file=sys.stderr)
        return []
    ids = proc.stdout.strip()
    return [s.strip() for s in ids.split(",") if s.strip()] if ids else []


CHECKLIST_DEFS = {
    "vg:specs": [
        ("specs_preflight", "Specs Preflight", [
            "parse_args", "check_existing", "choose_mode", "guided_questions",
        ]),
        ("specs_authoring", "Specs And Interface Standards", [
            "generate_draft", "write_specs", "write_interface_standards",
        ]),
        ("specs_close", "Commit And Next", ["commit_and_next"]),
    ],
    "vg:scope": [
        ("scope_preflight", "Scope Preflight", [
            "0_parse_and_validate",
        ]),
        ("scope_discussion", "Deep Discussion (5 Rounds + Deep Probe)", [
            "1_deep_discussion",
        ]),
        ("scope_env_preference", "Env Preference (Sandbox/Staging/Prod)", [
            "1b_env_preference",
        ]),
        ("scope_artifact", "Artifact Generation (CONTEXT + DISCUSSION-LOG + Per-Decision Split)", [
            "2_artifact_generation",
        ]),
        ("scope_validation", "Completeness Validation (4 Checks)", [
            "3_completeness_validation",
        ]),
        ("scope_crossai", "CrossAI Review + Reflection + Test-Strategy", [
            "4_crossai_review", "4_5_bootstrap_reflection", "4_6_test_strategy",
        ]),
        ("scope_close", "Close (Contract Pin, Decisions-Trace, Commit, Run-Complete)", [
            "5_commit_and_next",
        ]),
    ],
    "vg:blueprint": [
        ("blueprint_preflight", "Blueprint Preflight", [
            "0_design_discovery", "0_amendment_preflight", "1_parse_args",
            "create_task_tracker", "2_verify_prerequisites",
        ]),
        ("blueprint_design", "Design Grounding", [
            "2_fidelity_profile_lock", "2b6c_view_decomposition", "2b6_ui_spec",
            "2b6b_ui_map",
        ]),
        ("blueprint_plan", "Plan", ["2a_plan", "2a5_cross_system_check"]),
        ("blueprint_contracts", "Contracts And Test Goals", [
            "2b_contracts", "2b5_test_goals", "2b5a_codex_test_goal_lane",
            "2b5d_expand_from_crud_surfaces", "2b7_flow_detect",
        ]),
        ("blueprint_verify", "Verification Gates", [
            "2c_verify", "2c_verify_plan_paths", "2c_utility_reuse",
            "2c_compile_check", "2d_validation_gate", "2d_crossai_review",
            "2d_test_type_coverage", "2d_goal_grounding",
        ]),
        ("blueprint_close", "Reflection And Complete", [
            "2e_bootstrap_reflection", "3_complete",
        ]),
    ],
    "vg:build": [
        ("build_preflight", "Build Preflight", [
            "0_gate_integrity_precheck", "0_session_lifecycle", "1_parse_args",
            "1a_build_queue_preflight", "1b_recon_gate", "create_task_tracker",
        ]),
        ("build_context", "Blueprint And Context Load", [
            "2_initialize", "3_validate_blueprint", "4_load_contracts_and_context",
            "5_handle_branching", "6_validate_phase", "7_discover_plans",
        ]),
        ("build_execute", "Wave Execution", [
            "8_execute_waves", "8_5_bootstrap_reflection_per_wave",
        ]),
        ("build_verify", "Post Build Verification", [
            "9_post_execution", "10_postmortem_sanity", "11_crossai_build_verify_loop",
        ]),
        ("build_close", "Complete", ["12_run_complete"]),
    ],
    "vg:review": [
        ("review_preflight", "Review Preflight", [
            "00_gate_integrity_precheck", "00_session_lifecycle",
            "0_parse_and_validate", "0a_env_mode_gate", "0b_goal_coverage_gate",
            "0c_telemetry_suggestions", "create_task_tracker", "phase_profile_branch",
        ]),
        ("review_be", "BE/API Checks", [
            "phase1_code_scan", "phase1_5_ripple_and_god_node",
            "phase2a_api_contract_probe",
        ]),
        ("review_discovery", "Discovery And Lenses", [
            "phase2_browser_discovery", "phase2_5_recursive_lens_probe",
            "phase2b_collect_merge", "phase2c_enrich_test_goals",
            "phase2c_pre_dispatch_gates", "phase2d_crud_roundtrip_dispatch",
            "phase2_5_visual_checks", "phase2_5_mobile_visual_checks",
            "phase2_7_url_state_sync", "phase2_8_url_state_runtime",
            "phase2_9_error_message_runtime",
        ]),
        ("review_findings", "Findings And Fix Loop", [
            "phase2e_findings_merge", "phase2e_post_challenge",
            "phase2f_route_auto_fix", "phase2_exploration_limits",
            "phase3_fix_loop",
        ]),
        ("review_verdict", "Verdict And Complete", [
            "phase4_goal_comparison", "unreachable_triage", "crossai_review",
            "write_artifacts", "bootstrap_reflection", "complete",
        ]),
        ("review_profile_shortcuts", "Profile-Specific Shortcut Modes", [
            "phaseP_infra_smoke", "phaseP_delta", "phaseP_regression",
            "phaseP_schema_verify", "phaseP_link_check",
        ]),
    ],
    "vg:test": [
        ("test_preflight", "Test Preflight", [
            "00_gate_integrity_precheck", "00_session_lifecycle",
            "0_parse_and_validate", "0c_telemetry_suggestions",
            "create_task_tracker", "0_state_update",
        ]),
        ("test_deploy", "Deploy And Contract", [
            "5a_deploy", "5a_mobile_deploy", "5b_runtime_contract_verify",
        ]),
        ("test_runtime", "Goal Runtime Verification", [
            "5c_smoke", "5c_goal_verification", "5c_fix",
            "5c_auto_escalate", "5c_flow", "5c_mobile_flow",
        ]),
        ("test_codegen", "Regression Codegen", [
            "5d_codegen", "5d_binding_gate", "5d_deep_probe",
            "5d_mobile_codegen",
        ]),
        ("test_regression_security", "Regression And Security", [
            "5e_regression", "5f_security_audit",
            "5f_mobile_security_audit", "5g_performance_check",
            "5h_security_dynamic",
        ]),
        ("test_close", "Report And Complete", [
            "write_report", "bootstrap_reflection", "complete",
        ]),
    ],
    "vg:accept": [
        ("accept_preflight", "Accept Preflight", [
            "0_gate_integrity_precheck", "0_load_config",
            "create_task_tracker", "0c_telemetry_suggestions",
        ]),
        ("accept_gates", "Artifact And Runtime Gates", [
            "1_artifact_precheck", "2_marker_precheck",
            "3_sandbox_verdict_gate", "3b_unreachable_triage_gate",
            "3c_override_resolution_gate",
        ]),
        ("accept_uat", "Human UAT", [
            "4_build_uat_checklist", "4b_uat_narrative_autofire",
            "5_interactive_uat", "5_uat_quorum_gate",
        ]),
        ("accept_audit", "Security And Learning", [
            "6b_security_baseline", "6c_learn_auto_surface",
            "6_write_uat_md",
        ]),
        ("accept_close", "Complete", ["7_post_accept_actions"]),
    ],
    "vg:roam": [
        ("roam_preflight", "Roam Preflight", [
            "0_parse_and_validate", "0aa_resume_check",
        ]),
        ("roam_config_gate", "Config Gate (env/model/mode)", [
            "0a_backfill_env_pref", "0a_detect_platform_tools",
            "0a_enrich_env_options", "0a_confirm_env_model_mode",
            "0a_persist_config",
        ]),
        ("roam_discovery", "Surface Discovery And Briefs", [
            "1_discover_surfaces", "2_compose_briefs",
        ]),
        ("roam_execute", "Spawn Executors And Aggregate", [
            "3_spawn_executors", "4_aggregate_logs",
        ]),
        ("roam_analyze", "Commander Analysis", ["5_analyze_findings"]),
        ("roam_artifacts", "Emit Artifacts", ["6_emit_artifacts"]),
        ("roam_fix_loop", "Optional Fix Loop", ["7_optional_fix_loop"]),
        ("roam_close", "Complete", ["complete"]),
    ],
}


def _build_checklists(command: str, steps: list[str]) -> list[dict]:
    """Group visible steps into larger checklists for native task UIs.

    The step list remains authoritative. Checklists are a projection layer so
    Claude/Codex can show coarse progress without forcing extra execution
    passes for each lens/check.
    """
    remaining = set(steps)
    checklists: list[dict] = []
    for cid, title, wanted in CHECKLIST_DEFS.get(command, []):
        item_ids = [step for step in wanted if step in remaining]
        if not item_ids:
            continue
        for step in item_ids:
            remaining.discard(step)
        checklists.append({
            "id": cid,
            "title": title,
            "items": item_ids,
            "status": "pending",
        })
    if remaining:
        ordered = [step for step in steps if step in remaining]
        checklists.append({
            "id": "workflow_other",
            "title": "Other Workflow Steps",
            "items": ordered,
            "status": "pending",
        })
    return checklists


def _step_to_checklist(checklists: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for checklist in checklists:
        for step in checklist.get("items") or []:
            out[step] = checklist["id"]
    return out


def _build_hierarchical_projection(checklists: list[dict]) -> list[dict]:
    """Flat list of N=len(groups)+len(steps) items for native TodoWrite hierarchy.

    Per group: 1 header item + N sub-step items (prefixed with "  ↳").
    Native TodoWrite shows all items in flat list — prefix simulates nesting.

    Each item:
      - kind: "group" | "step"
      - id: marker name (group_id for headers, step_id for steps)
      - parent: group_id (for steps; None for groups)
      - title: visible text in TodoWrite (group emoji + count, step ↳ name)
      - status: "pending" (initial)
    """
    items: list[dict] = []
    for c in checklists:
        sub_count = len(c.get("items") or [])
        items.append({
            "kind": "group",
            "id": c["id"],
            "parent": None,
            "title": f"📋 {c['title']} ({sub_count} step{'s' if sub_count != 1 else ''})",
            "status": "pending",
        })
        for step in c.get("items") or []:
            items.append({
                "kind": "step",
                "id": step,
                "parent": c["id"],
                # Raw step ID is the marker name + already user-recognizable
                # (e.g. 2b6c_view_decomposition). Avoid _humanize() mangling
                # alphanumeric IDs into "2 B 6 C View Decomposition".
                "title": f"  ↳ {step}",
                "status": "pending",
            })
    return items


def _emit_event(
    command: str,
    phase: str,
    profile: str,
    mode: str | None,
    steps: list[str],
    checklists: list[dict],
) -> bool:
    """Emit {cmd_short}.tasklist_shown event with step payload."""
    cmd_short = command.replace("vg:", "").replace(":", "_")
    event_type = f"{cmd_short}.tasklist_shown"
    payload = {
        "step_count": len(steps),
        "steps": steps,
        "checklists": [
            {"id": c["id"], "title": c["title"], "item_count": len(c["items"])}
            for c in checklists
        ],
        "checklist_count": len(checklists),
        "command": command,
        "phase": phase,
        "profile": profile,
        "mode": mode,
        "harness_contract": "native-tasklist.v1",
        "native_projection_required": True,
    }
    try:
        proc = subprocess.run(
            [sys.executable, str(ORCHESTRATOR), "emit-event",
             event_type,
             "--payload", json.dumps(payload)],
            capture_output=True, text=True, timeout=10,
        )
        return proc.returncode == 0
    except Exception as exc:
        print(f"⚠ emit-event failed: {exc}", file=sys.stderr)
        return False


def _read_active_run() -> dict | None:
    sid = (
        os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("CLAUDE_CODE_SESSION_ID")
        or None
    )
    candidates: list[Path] = []
    if sid:
        candidates.append(REPO_ROOT / ".vg" / "active-runs" / f"{_safe_session_filename(sid)}.json")
    candidates.append(REPO_ROOT / ".vg" / "current-run.json")
    for path in candidates:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and data.get("run_id"):
            return data
    return None


def _write_contract(
    command: str,
    phase: str,
    profile: str,
    mode: str | None,
    steps: list[str],
    checklists: list[dict],
) -> Path | None:
    active = _read_active_run()
    run_id = active.get("run_id") if active else None
    if not run_id:
        return None

    checklist_by_step = _step_to_checklist(checklists)
    items = [
        {
            "id": step,
            "title": _humanize(step),
            "status": "pending",
            "source": "filter-steps.py",
            "checklist": checklist_by_step.get(step, "workflow_other"),
        }
        for step in steps
    ]
    projection_items = _build_hierarchical_projection(checklists)
    contract = {
        "schema": "native-tasklist.v2",
        "run_id": run_id,
        "command": command,
        "phase": phase,
        "profile": profile,
        "mode": mode,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "projection_required": True,
        "projection_mode": "hierarchical",
        "lifecycle": {
            "projection_mode": "replace-on-start",
            "close_on_complete": True,
            "clear_strategy": "empty-list-or-completed-sentinel",
        },
        "checklists": checklists,
        "projection_items": projection_items,
        "projection_item_count": len(projection_items),
        "native_adapters": {
            "claude": "TodoWrite with one item per projection_items entry (group headers + sub-steps with ↳ prefix)",
            "codex": "native tasklist/plan UI — same hierarchy",
            "fallback": "vg-orchestrator run-status --pretty",
        },
        "items": items,
        "enforcement": {
            "must_project_native_ui_event": f"{command.replace('vg:', '').replace(':', '_')}.native_tasklist_projected",
            "must_mark_steps": True,
            "source_of_truth": [".vg/events.db", ".step-markers", "tasklist-contract.json"],
        },
    }
    path = REPO_ROOT / ".vg" / "runs" / run_id / "tasklist-contract.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(contract, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(path))
    return path


def _humanize(step: str) -> str:
    text = step
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Za-z])([0-9])", r"\1 \2", text)
    text = re.sub(r"([0-9])([A-Za-z])", r"\1 \2", text)
    text = text.replace("_", " ").replace("-", " ").strip()
    return " ".join(part.capitalize() for part in text.split())


def _print_tasklist(
    command: str,
    phase: str,
    profile: str,
    mode: str | None,
    steps: list[str],
    checklists: list[dict],
) -> None:
    projection_items = _build_hierarchical_projection(checklists)
    print("")
    print("━" * 78)
    mode_label = f" — Mode {mode}" if mode else ""
    print(f"  {command} — Phase {phase} — Profile {profile}{mode_label}")
    print(f"  Taskboard: {len(steps)} step(s)")
    print(f"  Checklists: {len(checklists)} group(s) → {len(projection_items)} projection items")
    print("━" * 78)
    print(f"  TodoWrite hierarchical projection ({len(projection_items)} items):")
    print("━" * 78)
    for item in projection_items:
        marker = "📋" if item["kind"] == "group" else "  "
        print(f"  [ ] {item['title']}")
    print("━" * 78)
    print("  Markers required: .step-markers/{name}.done (per sub-step, NOT group)")
    print("  Native task UI projection REQUIRED before execution.")
    print("  Claude adapter: TodoWrite — one item per projection_items entry")
    print("  (6 group headers + N sub-steps with ↳ prefix). Mark sub-steps")
    print("  in_progress/completed individually. Group header marks completed")
    print("  ONLY when all its sub-steps are completed.")
    print("  Tasklist lifecycle: replace-on-start; close-on-complete.")
    print("  Missing marker at run end = runtime contract violation.")
    print("━" * 78)
    print("")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--command", required=True, help="e.g. vg:build")
    ap.add_argument("--profile", required=True, help="e.g. web-fullstack")
    ap.add_argument("--phase", required=True, help="e.g. 7.14")
    ap.add_argument("--mode", default=None, help="optional workflow mode, e.g. full")
    ap.add_argument("--no-emit", action="store_true", help="print list only")
    args = ap.parse_args()

    steps = _get_step_list(args.command, args.profile, args.mode)
    if not steps:
        return 1

    checklists = _build_checklists(args.command, steps)
    contract_path = _write_contract(args.command, args.phase, args.profile, args.mode, steps, checklists)
    _print_tasklist(args.command, args.phase, args.profile, args.mode, steps, checklists)
    if contract_path:
        print(f"  Tasklist contract: {contract_path}")
        print("")

    if args.no_emit:
        return 0

    if not _emit_event(args.command, args.phase, args.profile, args.mode, steps, checklists):
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
