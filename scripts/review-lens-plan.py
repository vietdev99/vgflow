#!/usr/bin/env python3
"""Generate and validate /vg:review lens/plugin plan.

The visible review tasklist is made of large orchestration steps. This file
materializes the smaller mandatory lenses those steps must execute, so checks
such as filter, paging, URL state, visual, and CRUD round-trip are not left to
model memory.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api_docs_common import (
    classify_query_controls,
    extract_contract_request_shape,
    parse_api_docs_entries,
    parse_contract_sections,
)

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

WEB_PROFILES = {"web-fullstack", "web-frontend-only", "web-backend-only"}
MOBILE_PROFILES = {
    "mobile-rn",
    "mobile-flutter",
    "mobile-native-ios",
    "mobile-native-android",
    "mobile-hybrid",
}
CLI_LIBRARY_PROFILES = {"cli-tool", "library"}


MD_GOAL_RE = re.compile(
    r"^##\s+Goal\s+(G-[A-Z0-9-]+)\s*:?\s*(.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL | re.MULTILINE)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _has_ui_goals(text: str) -> bool:
    lower = text.lower()
    return "surface: ui" in lower or "**surface:** ui" in lower or "interactive_controls" in lower


def _goal_ids_with_controls(text: str) -> list[str]:
    ids: list[str] = []
    for match in MD_GOAL_RE.finditer(text):
        start = match.end()
        nxt = MD_GOAL_RE.search(text, start)
        end = nxt.start() if nxt else len(text)
        if "interactive_controls" in text[start:end]:
            ids.append(match.group(1).upper())
    for match in FRONTMATTER_RE.finditer(text):
        body = match.group(1)
        if "interactive_controls" not in body:
            continue
        gid = re.search(r"^id:\s*(G-[A-Z0-9-]+)", body, re.MULTILINE | re.IGNORECASE)
        if gid:
            ids.append(gid.group(1).upper())
    return sorted(set(ids))


def _contract_controls(phase_dir: Path) -> dict[str, Any]:
    out = {
        "filters": {},
        "has_search": False,
        "has_sort": False,
        "has_pagination": False,
        "endpoints": [],
    }
    contracts = phase_dir / "API-CONTRACTS.md"
    for section in parse_contract_sections(contracts):
        shape = extract_contract_request_shape(section)
        pseudo_entry = {"request": {"query": shape.get("query") or {}}}
        controls = classify_query_controls(pseudo_entry)
        if controls["filters"] or controls["has_search"] or controls["has_sort"] or controls["has_pagination"]:
            out["endpoints"].append(f"{section.method} {section.path}")
        out["filters"].update(controls["filters"])
        out["has_search"] = out["has_search"] or controls["has_search"]
        out["has_sort"] = out["has_sort"] or controls["has_sort"]
        out["has_pagination"] = out["has_pagination"] or controls["has_pagination"]
    return out


def _api_doc_controls(phase_dir: Path) -> dict[str, Any]:
    out = {
        "filters": {},
        "has_search": False,
        "has_sort": False,
        "has_pagination": False,
        "endpoints": [],
    }
    for key, entry in parse_api_docs_entries(phase_dir / "API-DOCS.md").items():
        controls = classify_query_controls(entry)
        if controls["filters"] or controls["has_search"] or controls["has_sort"] or controls["has_pagination"]:
            out["endpoints"].append(f"{key[0]} {key[1]}")
        out["filters"].update(controls["filters"])
        out["has_search"] = out["has_search"] or controls["has_search"]
        out["has_sort"] = out["has_sort"] or controls["has_sort"]
        out["has_pagination"] = out["has_pagination"] or controls["has_pagination"]
    return out


def _plugin(
    plugin_id: str,
    title: str,
    required: bool,
    evidence: list[str],
    reason: str,
    *,
    checklist: str,
    step: str,
    profiles: list[str] | None = None,
    modes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": plugin_id,
        "title": title,
        "required": required,
        "evidence": evidence,
        "reason": reason,
        "checklist": checklist,
        "step": step,
        "profiles": profiles or ["*"],
        "modes": modes or ["*"],
        "status": "planned" if required else "optional",
    }


def _matches_token(value: str, token: str) -> bool:
    if token == "*":
        return True
    if token.endswith("*"):
        return value.startswith(token[:-1])
    return value == token


def _matches_any(value: str, tokens: list[str] | None) -> bool:
    if not tokens:
        return True
    return any(_matches_token(value, token) for token in tokens)


def _artifact_any(phase_dir: Path, patterns: list[str]) -> bool:
    return any(any(phase_dir.glob(pattern)) for pattern in patterns)


def _artifact_all(phase_dir: Path, patterns: list[str]) -> bool:
    return all(any(phase_dir.glob(pattern)) for pattern in patterns)


def _text_contains_any(phase_dir: Path, checks: list[dict[str, Any]]) -> bool:
    for check in checks:
        rel = str(check.get("path") or "TEST-GOALS.md")
        needles = check.get("contains_any") or check.get("contains") or []
        if isinstance(needles, str):
            needles = [needles]
        text = _read(phase_dir / rel)
        if any(str(needle) in text for needle in needles):
            return True
    return False


def _required_from_overlay(plugin: dict[str, Any], phase_dir: Path, profile: str, mode: str) -> bool:
    if "required" in plugin:
        return bool(plugin.get("required"))
    cond = plugin.get("required_when") or plugin.get("when") or {}
    if not cond:
        return False
    if not _matches_any(profile, cond.get("profiles")):
        return False
    if not _matches_any(mode, cond.get("modes")):
        return False
    if cond.get("artifacts_any") and not _artifact_any(phase_dir, [str(x) for x in cond["artifacts_any"]]):
        return False
    if cond.get("artifacts_all") and not _artifact_all(phase_dir, [str(x) for x in cond["artifacts_all"]]):
        return False
    if cond.get("text_contains_any") and not _text_contains_any(phase_dir, cond["text_contains_any"]):
        return False
    return True


def _overlay_paths(phase_dir: Path) -> list[Path]:
    return [
        REPO_ROOT / ".claude" / "catalog" / "review-lens-plugins.json",
        REPO_ROOT / "catalog" / "review-lens-plugins.json",
        REPO_ROOT / ".vg" / "review-lens-plugins.json",
        phase_dir / "review-lens-plugins.json",
        phase_dir / "REVIEW-LENS-PLUGINS.json",
    ]


def _load_overlay_plugins(phase_dir: Path, profile: str, mode: str) -> list[dict[str, Any]]:
    """Load project/phase plugin overlays.

    Overlay schema:
      {"plugins": [{
        "id": "custom_lens",
        "title": "Custom lens",
        "checklist": "fe_check",
        "step": "phase2_8_url_state_runtime",
        "evidence": ["custom-evidence.json"],
        "reason": "...",
        "required": true
        // or "required_when": {"profiles": ["web-*"], "modes": ["full"],
        //                      "artifacts_any": ["UI-MAP.md"]}
      }]}
    """
    plugins: list[dict[str, Any]] = []
    for path in _overlay_paths(phase_dir):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid review lens plugin overlay {path}: {exc}") from exc
        raw_plugins = payload.get("plugins") if isinstance(payload, dict) else payload
        if not isinstance(raw_plugins, list):
            raise SystemExit(f"invalid review lens plugin overlay {path}: expected plugins list")
        for raw in raw_plugins:
            if not isinstance(raw, dict) or not raw.get("id"):
                raise SystemExit(f"invalid review lens plugin in {path}: missing id")
            evidence = raw.get("evidence") or []
            if isinstance(evidence, str):
                evidence = [evidence]
            plugin = _plugin(
                str(raw["id"]),
                str(raw.get("title") or raw["id"]),
                _required_from_overlay(raw, phase_dir, profile, mode),
                [str(x) for x in evidence],
                str(raw.get("reason") or "Injected review lens plugin."),
                checklist=str(raw.get("checklist") or "custom_check"),
                step=str(raw.get("step") or "phase4_goal_comparison"),
                profiles=[str(x) for x in raw.get("profiles") or ["*"]],
                modes=[str(x) for x in raw.get("modes") or ["*"]],
            )
            plugin["source"] = str(path)
            if raw.get("checklist_title"):
                plugin["checklist_title"] = str(raw["checklist_title"])
            plugins.append(plugin)
    return plugins


def _has_mutation_contracts(phase_dir: Path) -> bool:
    contracts = phase_dir / "API-CONTRACTS.md"
    for section in parse_contract_sections(contracts):
        if section.method in {"POST", "PUT", "PATCH", "DELETE"}:
            return True
    return False


def _has_runtime_crud_kits(phase_dir: Path) -> bool:
    crud_text = _read(phase_dir / "CRUD-SURFACES.md")
    return any(kit in crud_text for kit in (
        '"kit": "crud-roundtrip"',
        '"kit":"crud-roundtrip"',
        '"kit": "approval-flow"',
        '"kit":"approval-flow"',
        '"kit": "bulk-action"',
        '"kit":"bulk-action"',
    ))


def _checklist(
    checklist_id: str,
    title: str,
    profiles: list[str],
    modes: list[str],
    steps: list[str],
    plugin_ids: list[str],
) -> dict[str, Any]:
    return {
        "id": checklist_id,
        "title": title,
        "profiles": profiles,
        "modes": modes,
        "steps": steps,
        "plugins": plugin_ids,
    }


def build_plan(phase_dir: Path, *, profile: str = "unknown", mode: str = "full") -> dict[str, Any]:
    goals_text = _read(phase_dir / "TEST-GOALS.md")
    crud_text = _read(phase_dir / "CRUD-SURFACES.md")
    contract_controls = _contract_controls(phase_dir)
    api_controls = _api_doc_controls(phase_dir)
    has_ui = _has_ui_goals(goals_text) or (phase_dir / "UI-MAP.md").exists() or (phase_dir / "designs").exists()
    control_goal_ids = _goal_ids_with_controls(goals_text)
    filters = set(contract_controls["filters"]) | set(api_controls["filters"])
    has_filter = bool(filters) or bool(re.search(r"\bfilters?\s*:", goals_text, re.IGNORECASE))
    has_paging = contract_controls["has_pagination"] or api_controls["has_pagination"] or "pagination:" in goals_text
    has_search = contract_controls["has_search"] or api_controls["has_search"] or "search:" in goals_text
    has_sort = contract_controls["has_sort"] or api_controls["has_sort"] or "sort:" in goals_text
    has_url_state = bool(control_goal_ids) or has_filter or has_paging or has_search or has_sort
    has_crud_roundtrip = '"kit"' in crud_text and "crud-roundtrip" in crud_text
    has_api_contracts = (phase_dir / "API-CONTRACTS.md").exists()
    has_mutations = _has_mutation_contracts(phase_dir)
    has_runtime_kits = _has_runtime_crud_kits(phase_dir)
    is_web = profile in WEB_PROFILES or profile == "unknown"
    is_mobile = profile in MOBILE_PROFILES
    is_backend_capable = profile in {"web-fullstack", "web-backend-only", "web-frontend-only", "unknown"}
    is_cli_library = profile in CLI_LIBRARY_PROFILES
    is_full = mode == "full"

    plugins: list[dict[str, Any]] = [
        _plugin(
            "target_env_contract",
            "Review target environment is explicit",
            (is_web or is_mobile or has_runtime_kits) and mode not in {"link-check"},
            ["ENV-CONTRACT.md"],
            "Runtime review must know which env/base_url/auth/seed data it is testing.",
            checklist="env_check",
            step="0a_env_mode_gate",
            profiles=["web-*", "mobile-*", "cli-tool", "library"],
            modes=["full", "infra-smoke", "delta", "regression", "schema-verify"],
        ),
        _plugin(
            "api_docs_contract_coverage",
            "API docs cover API contracts",
            has_api_contracts and is_backend_capable and is_full,
            ["api-docs-check.txt", "api-contract-precheck.txt"],
            "Review must test BE contract before FE discovery.",
            checklist="be_check",
            step="phase2a_api_contract_probe",
            profiles=["web-fullstack", "web-backend-only", "web-frontend-only"],
            modes=["full"],
        ),
        _plugin(
            "api_contract_runtime_probe",
            "Live API route probe",
            has_api_contracts and is_backend_capable and is_full,
            ["api-contract-precheck.txt"],
            "Backend review must prove current env exposes the contracted API surface before downstream FE checks.",
            checklist="be_check",
            step="phase2a_api_contract_probe",
            profiles=["web-fullstack", "web-backend-only", "web-frontend-only"],
            modes=["full"],
        ),
        _plugin(
            "goal_security_declaration_gate",
            "Goal-level security declarations validated",
            (has_api_contracts or has_mutations or has_ui) and is_backend_capable and is_full,
            [".tmp/verify-goal-security-diagnostic-input.txt"],
            "Security requirements for auth, CSRF, rate limit, roles, and critical domains must be checked before review PASS.",
            checklist="security_check",
            step="phase4_goal_comparison",
            profiles=["web-fullstack", "web-backend-only", "web-frontend-only"],
            modes=["full"],
        ),
        _plugin(
            "security_baseline_gate",
            "Project security baseline validated",
            is_web and is_full,
            [".tmp/verify-security-baseline-diagnostic-input.txt"],
            "Review must run the baseline security sweep for headers, CORS, TLS/deploy config, secrets, and cookie posture.",
            checklist="security_check",
            step="phase4_goal_comparison",
            profiles=["web-fullstack", "web-backend-only", "web-frontend-only"],
            modes=["full"],
        ),
        _plugin(
            "goal_performance_budget_gate",
            "Goal-level performance budgets validated",
            (has_api_contracts or has_ui) and is_web and is_full,
            [".tmp/verify-goal-perf-diagnostic-input.txt"],
            "Mutation/list/UI goals need performance budget checks, including p95, N+1, bundle, and cache expectations.",
            checklist="performance_check",
            step="phase4_goal_comparison",
            profiles=["web-fullstack", "web-backend-only", "web-frontend-only"],
            modes=["full"],
        ),
        _plugin(
            "backend_mutation_evidence",
            "Mutation submit + 2xx evidence",
            has_mutations and profile in {"web-fullstack", "web-backend-only"} and is_full,
            [".tmp/backend-mutation-evidence.json", "RUNTIME-MAP.json"],
            "Mutation endpoints must be proven by submit/network evidence, not static route existence.",
            checklist="be_check",
            step="phase4_goal_comparison",
            profiles=["web-fullstack", "web-backend-only"],
            modes=["full"],
        ),
        _plugin(
            "browser_surface_inventory",
            "Browser surface inventory",
            has_ui and profile in {"web-fullstack", "web-frontend-only", "unknown"} and is_full,
            ["RUNTIME-MAP.json", "scan-*.json"],
            "UI goals require live route/surface discovery.",
            checklist="fe_check",
            step="phase2_browser_discovery",
            profiles=["web-fullstack", "web-frontend-only"],
            modes=["full"],
        ),
        _plugin(
            "api_error_message_lens",
            "API error message reaches toast/form UI",
            has_api_contracts and has_ui and profile in {"web-fullstack", "web-frontend-only", "unknown"} and is_full,
            ["error-message-probe.json"],
            "API+UI phases must prove visible errors use the API response message, not statusText or generic HTTP text.",
            checklist="fe_check",
            step="phase2_9_error_message_runtime",
            profiles=["web-fullstack", "web-frontend-only"],
            modes=["full"],
        ),
        _plugin(
            "url_state_lens",
            "URL state declaration + runtime probe",
            has_url_state and profile in {"web-fullstack", "web-frontend-only", "unknown"} and is_full,
            [".tmp/url-state-sync.json", ".tmp/url-state-runtime.json", "url-runtime-probe.json"],
            "List controls must survive refresh/share/back-forward.",
            checklist="fe_check",
            step="phase2_8_url_state_runtime",
            profiles=["web-fullstack", "web-frontend-only"],
            modes=["full"],
        ),
        _plugin(
            "filter_lens",
            "Filter result semantics",
            has_filter and profile in {"web-fullstack", "web-frontend-only", "unknown"} and is_full,
            ["url-runtime-probe.json"],
            "Filter must change URL and returned rows, not just selected UI state.",
            checklist="fe_check",
            step="phase2_8_url_state_runtime",
            profiles=["web-fullstack", "web-frontend-only"],
            modes=["full"],
        ),
        _plugin(
            "paging_lens",
            "Paging result semantics",
            has_paging and profile in {"web-fullstack", "web-frontend-only", "unknown"} and is_full,
            ["url-runtime-probe.json"],
            "Paging must change the result window without mixing records.",
            checklist="fe_check",
            step="phase2_8_url_state_runtime",
            profiles=["web-fullstack", "web-frontend-only"],
            modes=["full"],
        ),
        _plugin(
            "sort_lens",
            "Sort result semantics",
            has_sort and profile in {"web-fullstack", "web-frontend-only", "unknown"} and is_full,
            ["url-runtime-probe.json"],
            "Sort must prove row order changes according to declared column/direction.",
            checklist="fe_check",
            step="phase2_8_url_state_runtime",
            profiles=["web-fullstack", "web-frontend-only"],
            modes=["full"],
        ),
        _plugin(
            "search_lens",
            "Search result semantics",
            has_search and profile in {"web-fullstack", "web-frontend-only", "unknown"} and is_full,
            ["url-runtime-probe.json"],
            "Search must debounce, sync URL, and constrain visible/network rows.",
            checklist="fe_check",
            step="phase2_8_url_state_runtime",
            profiles=["web-fullstack", "web-frontend-only"],
            modes=["full"],
        ),
        _plugin(
            "visual_lens_bundle",
            "Visual integrity bundle",
            has_ui and profile in {"web-fullstack", "web-frontend-only", "unknown"}
            and ((phase_dir / "UI-MAP.md").exists() or (phase_dir / "designs").exists()) and is_full,
            ["visual-issues.json", "visual-fidelity/*.json"],
            "UI changes need overflow/responsive/z-index/fidelity checks in one visual pass.",
            checklist="fe_check",
            step="phase2_5_visual_checks",
            profiles=["web-fullstack", "web-frontend-only"],
            modes=["full"],
        ),
        _plugin(
            "mobile_surface_inventory",
            "Mobile device surface inventory",
            is_mobile and is_full,
            ["discover/*", "scan-*.json"],
            "Mobile profiles must exercise the device/emulator surface with Maestro/screenshot evidence.",
            checklist="mobile_check",
            step="phase2_mobile_discovery",
            profiles=["mobile-*"],
            modes=["full"],
        ),
        _plugin(
            "mobile_visual_lens",
            "Mobile visual integrity",
            is_mobile and is_full,
            ["discover/*", "mobile-visual-issues.json"],
            "Mobile review must check clipped/off-screen content on configured device viewports.",
            checklist="mobile_check",
            step="phase2_5_mobile_visual_checks",
            profiles=["mobile-*"],
            modes=["full"],
        ),
        _plugin(
            "crud_roundtrip_lens",
            "CRUD/RCRURD round-trip",
            has_crud_roundtrip and profile in {"web-fullstack", "web-frontend-only", "web-backend-only", "unknown"} and is_full,
            ["runs/INDEX.json", "REVIEW-FINDINGS.json"],
            "CRUD resources need Read/Create/Read/Update/Read/Delete/Read evidence.",
            checklist="business_flow_check",
            step="phase2d_crud_roundtrip_dispatch",
            profiles=["web-fullstack", "web-frontend-only", "web-backend-only"],
            modes=["full"],
        ),
        _plugin(
            "findings_pipeline",
            "Findings merge/challenge/route",
            (has_crud_roundtrip or has_url_state or has_mutations) and is_full,
            ["REVIEW-FINDINGS.json", "COVERAGE-CHALLENGE.json", "AUTO-FIX-TASKS.md"],
            "Lens outputs must be reduced, challenged, and routed before fix loop.",
            checklist="business_flow_check",
            step="phase2e_findings_merge",
            profiles=["web-*", "mobile-*"],
            modes=["full"],
        ),
        _plugin(
            "cli_goal_surface_probe",
            "CLI/library goal surface probe",
            is_cli_library and is_full,
            [".surface-probe-results.json", "GOAL-COVERAGE-MATRIX.md"],
            "CLI/library phases skip browser discovery but still need goal evidence from command/API/data probes.",
            checklist="cli_library_check",
            step="phase4_goal_comparison",
            profiles=["cli-tool", "library"],
            modes=["full"],
        ),
        _plugin(
            "infra_success_criteria_smoke",
            "Infra success criteria smoke",
            mode == "infra-smoke",
            [".success-criteria.json", ".infra-smoke-results.json", "GOAL-COVERAGE-MATRIX.md"],
            "Infra review must execute each SPECS success_criteria command and map it to implicit goals.",
            checklist="infra_check",
            step="phaseP_infra_smoke",
            profiles=["web-fullstack", "web-backend-only", "cli-tool", "library"],
            modes=["infra-smoke"],
        ),
        _plugin(
            "hotfix_delta_coverage",
            "Hotfix delta covers parent failures",
            mode == "delta",
            [".delta-coverage.json", "GOAL-COVERAGE-MATRIX.md"],
            "Hotfix review must prove the delta overlaps files implicated by parent failed goals.",
            checklist="hotfix_check",
            step="phaseP_delta",
            modes=["delta"],
        ),
        _plugin(
            "bugfix_regression_evidence",
            "Bugfix regression evidence",
            mode == "regression",
            ["GOAL-COVERAGE-MATRIX.md"],
            "Bugfix review must prove bug reference, production code delta, and test coverage signal.",
            checklist="bugfix_check",
            step="phaseP_regression",
            modes=["regression"],
        ),
        _plugin(
            "migration_schema_evidence",
            "Migration schema evidence",
            mode == "schema-verify",
            ["ROLLBACK.md", "GOAL-COVERAGE-MATRIX.md"],
            "Migration review must prove rollback exists and referenced migration files are present.",
            checklist="migration_check",
            step="phaseP_schema_verify",
            modes=["schema-verify"],
        ),
        _plugin(
            "docs_link_evidence",
            "Docs link evidence",
            mode == "link-check",
            ["GOAL-COVERAGE-MATRIX.md"],
            "Docs review must scan referenced markdown files for broken relative links.",
            checklist="docs_check",
            step="phaseP_link_check",
            modes=["link-check"],
        ),
    ]
    overlay_plugins = _load_overlay_plugins(phase_dir, profile, mode)
    if overlay_plugins:
        by_id = {p["id"]: p for p in plugins}
        for plugin in overlay_plugins:
            by_id[plugin["id"]] = plugin
        plugins = list(by_id.values())

    required_ids = [p["id"] for p in plugins if p.get("required")]
    checklists = [
        _checklist("env_check", "Environment / deploy readiness", ["*"], ["full", "infra-smoke", "delta", "regression", "schema-verify"], ["0a_env_mode_gate", "phase2c_pre_dispatch_gates"], required_ids),
        _checklist("be_check", "BE: API, CRUD, security, performance hooks", ["web-fullstack", "web-backend-only", "web-frontend-only"], ["full"], ["phase2a_api_contract_probe", "phase2d_crud_roundtrip_dispatch", "phase4_goal_comparison"], required_ids),
        _checklist("fe_check", "FE: RCRURD, controls, URL state, visual, error handling, security, performance hooks", ["web-fullstack", "web-frontend-only"], ["full"], ["phase2_browser_discovery", "phase2_5_visual_checks", "phase2_7_url_state_sync", "phase2_8_url_state_runtime", "phase2_9_error_message_runtime"], required_ids),
        _checklist("security_check", "Security: goal and project baseline gates", ["web-fullstack", "web-backend-only", "web-frontend-only"], ["full"], ["phase2_5_recursive_lens_probe", "phase4_goal_comparison"], required_ids),
        _checklist("performance_check", "Performance: goal budget gates", ["web-fullstack", "web-backend-only", "web-frontend-only"], ["full"], ["phase4_goal_comparison"], required_ids),
        _checklist("mobile_check", "Mobile: device discovery and visual checks", ["mobile-*"], ["full"], ["phase2_mobile_discovery", "phase2_5_mobile_visual_checks"], required_ids),
        _checklist("business_flow_check", "Business flow: CRUD/RCRURD and findings loop", ["web-*", "mobile-*"], ["full"], ["phase2d_crud_roundtrip_dispatch", "phase2e_findings_merge", "phase3_fix_loop"], required_ids),
        _checklist("cli_library_check", "CLI/library: command and data surface checks", ["cli-tool", "library"], ["full"], ["phase1_code_scan", "phase4_goal_comparison"], required_ids),
        _checklist("infra_check", "Infra: success criteria smoke", ["web-fullstack", "web-backend-only", "cli-tool", "library"], ["infra-smoke"], ["phaseP_infra_smoke"], required_ids),
        _checklist("hotfix_check", "Hotfix: delta coverage", ["*"], ["delta"], ["phaseP_delta"], required_ids),
        _checklist("bugfix_check", "Bugfix: regression evidence", ["*"], ["regression"], ["phaseP_regression"], required_ids),
        _checklist("migration_check", "Migration: schema and rollback", ["*"], ["schema-verify"], ["phaseP_schema_verify"], required_ids),
        _checklist("docs_check", "Docs: link check", ["*"], ["link-check"], ["phaseP_link_check"], required_ids),
    ]
    known_checklists = {c["id"] for c in checklists}
    for plugin in plugins:
        cid = plugin.get("checklist")
        if not cid or cid in known_checklists:
            continue
        checklists.append(_checklist(
            cid,
            plugin.get("checklist_title") or f"Custom: {cid}",
            plugin.get("profiles") or ["*"],
            plugin.get("modes") or ["*"],
            [plugin.get("step") or "phase4_goal_comparison"],
            required_ids,
        ))
        known_checklists.add(cid)
    for checklist in checklists:
        cid = checklist["id"]
        checklist["plugins"] = [p["id"] for p in plugins if p.get("checklist") == cid and p.get("required")]

    return {
        "schema": "review-lens-plan.v2",
        "phase_dir": str(phase_dir),
        "profile": profile,
        "mode": mode,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "surface": {
            "has_ui": has_ui,
            "control_goal_ids": control_goal_ids,
            "contract_control_endpoints": contract_controls["endpoints"],
            "api_doc_control_endpoints": api_controls["endpoints"],
            "filters": sorted(filters),
            "has_pagination": has_paging,
            "has_search": has_search,
            "has_sort": has_sort,
        },
        "checklists": checklists,
        "plugins": plugins,
    }


def _artifact_exists(phase_dir: Path, pattern: str) -> bool:
    return any(phase_dir.glob(pattern))


def validate_plan(plan: dict[str, Any], phase_dir: Path) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for plugin in plan.get("plugins", []):
        if not plugin.get("required"):
            continue
        evidence = plugin.get("evidence") or []
        for pattern in evidence:
            if not _artifact_exists(phase_dir, pattern):
                missing.append({
                    "plugin": plugin["id"],
                    "reason": "required plugin evidence artifact missing",
                    "expected": pattern,
                })

    # Root artifact location is a common dogfood failure: scan files hidden
    # under _evidence do not satisfy the review runtime contract.
    if any(p["id"] == "browser_surface_inventory" and p.get("required") for p in plan.get("plugins", [])):
        if not (phase_dir / "RUNTIME-MAP.json").exists():
            missing.append({
                "plugin": "browser_surface_inventory",
                "reason": "RUNTIME-MAP.json missing at phase root",
                "expected_any": ["RUNTIME-MAP.json"],
            })
        if not list(phase_dir.glob("scan-*.json")) and list((phase_dir / "_evidence").glob("scan-*.json")):
            missing.append({
                "plugin": "browser_surface_inventory",
                "reason": "scan artifacts exist only under _evidence; root scan-*.json contract is unsatisfied",
                "expected_any": ["scan-*.json"],
            })
    return missing


def write_plan(plan: dict[str, Any], phase_dir: Path) -> None:
    path = phase_dir / "REVIEW-LENS-PLAN.json"
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = ["# Review Lens Plan", ""]
    lines.append(f"- **Profile:** {plan.get('profile', 'unknown')}")
    lines.append(f"- **Mode:** {plan.get('mode', 'full')}")
    lines.append("")
    lines.append("## Checklists")
    lines.append("")
    for checklist in plan.get("checklists", []):
        plugin_count = len(checklist.get("plugins") or [])
        if plugin_count == 0:
            continue
        lines.append(f"- **{checklist['id']}** — {checklist['title']} ({plugin_count} required plugin(s))")
        lines.append(f"  Steps: {', '.join(checklist.get('steps') or [])}")
    lines.append("")
    lines.append("## Plugins")
    lines.append("")
    for plugin in plan["plugins"]:
        flag = "REQUIRED" if plugin["required"] else "optional"
        lines.append(f"- **{plugin['id']}** [{flag}] — {plugin['title']}")
        lines.append(f"  Step: {plugin.get('step', '<unwired>')} / Checklist: {plugin.get('checklist', '<none>')}")
        lines.append(f"  Evidence: {', '.join(plugin['evidence'])}")
    (phase_dir / "REVIEW-LENS-PLAN.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--profile", default="unknown")
    ap.add_argument("--mode", default="full")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    if not phase_dir.is_dir():
        print(f"phase_dir missing: {phase_dir}", file=sys.stderr)
        return 2
    plan = build_plan(phase_dir, profile=args.profile, mode=args.mode)
    if args.write:
        write_plan(plan, phase_dir)
    missing = validate_plan(plan, phase_dir) if args.validate_only else []
    if args.json or args.validate_only:
        print(json.dumps({"plan": plan, "missing": missing}, indent=2, ensure_ascii=False))
    else:
        required = [p for p in plan["plugins"] if p["required"]]
        print(f"Review lens plan: {len(required)} required plugin(s) -> {phase_dir / 'REVIEW-LENS-PLAN.json'}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
