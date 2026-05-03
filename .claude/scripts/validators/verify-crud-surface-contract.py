#!/usr/bin/env python3
"""verify-crud-surface-contract.py

Validate CRUD-SURFACES.md as a phase-level resource contract.

The contract is intentionally platform-aware:
- base: roles, business flow, security, abuse, performance
- web: list/table URL-state + form/delete UI behavior
- mobile: deep-link, pull-to-refresh/load-more, tap target, offline/network states
- backend: list endpoint query contract + mutation security/integrity

The validator blocks when a phase clearly touches CRUD/resource behavior but no
contract exists, or when the matching platform overlay is incomplete.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
CRUD_SIGNAL_RE = re.compile(
    r"\b(CRUD|create|created|update|updated|delete|deleted|detail|details|"
    r"form|forms|list|table|grid|filter|sort|pagination|paging|resource|"
    r"entity|record|row|GET\s+/[a-z0-9_/{}/-]*s\b|POST\s+/|PUT\s+/|"
    r"PATCH\s+/|DELETE\s+/)\b",
    re.IGNORECASE,
)
MUTATION_RE = re.compile(r"\b(POST|PUT|PATCH|DELETE)\s+/", re.IGNORECASE)
LIST_GET_RE = re.compile(r"\bGET\s+/[a-zA-Z0-9_/{}/-]*s\b", re.IGNORECASE)
WEB_SIGNAL_RE = re.compile(
    r"\b(view|page|screen|component|table|grid|filter|sort|pagination|"
    r"paging|search|modal|form|button|row action|empty state|loading state|"
    r"error state|heading|description|URL state|querystring)\b",
    re.IGNORECASE,
)
BACKEND_SIGNAL_RE = re.compile(
    r"\b(API|endpoint|route|controller|handler|service|repository|database|"
    r"schema|migration|validation|authz|authorization|middleware|csrf|CORS|"
    r"rate limit|mass assignment|idempotency|audit log|GET\s+/|POST\s+/|"
    r"PUT\s+/|PATCH\s+/|DELETE\s+/)\b",
    re.IGNORECASE,
)
# Issue #26: BE-only phases mention "table"/"form"/"view" in API + DB
# context (e.g. "wallet table schema", "form validation in handler"),
# triggering false WEB_SIGNAL_RE hits → forced platforms.web overlay
# generated 270+ field-missing errors per phase. The deterministic fix:
# scan PLAN.md (post-blueprint task list) for explicit FE source paths.
# Real FE work cites apps/admin/, apps/web/, .tsx files, etc.; BE-only
# phases don't. SPECS/CONTEXT prose alone is too noisy.
FE_SOURCE_PATH_RE = re.compile(
    r"\b(apps/(admin|merchant|vendor|web)/|packages/(ui|web-)|"
    r"frontend/|\b\.tsx\b|\b\.jsx\b)",
    re.IGNORECASE,
)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _phase_text(phase_dir: Path) -> str:
    chunks: list[str] = []
    for name in ("SPECS.md", "CONTEXT.md", "API-CONTRACTS.md", "TEST-GOALS.md", "FLOW-SPEC.md"):
        p = phase_dir / name
        if p.exists():
            chunks.append(_read(p))
    for p in sorted(phase_dir.glob("*PLAN*.md")):
        chunks.append(_read(p))
    return "\n".join(chunks)


def _plan_text(phase_dir: Path) -> str | None:
    """Read PLAN*.md only. Returns None if no PLAN file exists yet
    (phase pre-blueprint). Issue #26: PLAN.md is the authoritative
    task list — its presence/absence of FE source paths is the
    deterministic signal for whether the phase has FE work."""
    plans = sorted(phase_dir.glob("*PLAN*.md"))
    if not plans:
        return None
    return "\n".join(_read(p) for p in plans)


def _read_project_profile(config: Path) -> str:
    text = _read(config)
    for key in ("project_profile", "profile"):
        m = re.search(rf"^\s*{key}\s*:\s*['\"]?([\w-]+)", text, re.MULTILINE)
        if m:
            return m.group(1).lower()
    return "web-fullstack"


def _required_platforms(profile: str, phase_text: str,
                        plan_text: str | None = None) -> list[str]:
    """Decide which platform overlays the contract must declare.

    Issue #26: when project profile is `web-fullstack` but the phase is
    BE-only (common for wallet/ledger/billing/integration phases in
    fullstack projects), prose words like `table`/`form`/`view` —
    triggered by API/DB context such as "wallet table schema" or
    "form validation in handler" — caused false WEB_SIGNAL_RE hits and
    forced a platforms.web overlay generating 270+ field-missing errors.

    Fix: prefer the deterministic file-path signal from PLAN.md (the
    post-blueprint task list cites concrete source paths). When PLAN.md
    exists and has zero FE source paths but does have backend signals,
    require ONLY platforms.backend. Pre-blueprint phases (no PLAN.md
    yet) fall back to the legacy prose heuristic so existing behavior
    on early-stage phases is preserved.
    """
    if profile in {"cli-tool", "library"}:
        return []
    if profile == "web-frontend-only":
        return ["web"]
    if profile == "web-backend-only":
        return ["backend"]
    if profile == "web-fullstack":
        platforms: list[str] = []
        backend_signal = bool(BACKEND_SIGNAL_RE.search(phase_text))

        # Strong signal: explicit FE source paths in PLAN.md task list.
        plan_has_fe_source = bool(
            plan_text and FE_SOURCE_PATH_RE.search(plan_text)
        )

        if plan_text is not None:
            # PLAN.md exists → trust its file paths over prose heuristics.
            if plan_has_fe_source:
                platforms.append("web")
            if backend_signal:
                platforms.append("backend")
            # Edge: PLAN.md exists but neither FE paths nor backend signal
            # detected (e.g., docs-only phase). Default to web for safety.
            if not platforms:
                platforms.append("web")
            return platforms

        # No PLAN.md (pre-blueprint phase) — legacy prose heuristic.
        web_signal = bool(WEB_SIGNAL_RE.search(phase_text))
        if web_signal or not backend_signal:
            platforms.append("web")
        if backend_signal:
            platforms.append("backend")
        return platforms
    if profile.startswith("mobile-"):
        return ["mobile"]
    if MUTATION_RE.search(phase_text) or LIST_GET_RE.search(phase_text):
        return ["backend"]
    return ["web"]


def _extract_json(text: str) -> tuple[dict[str, Any] | None, str | None]:
    m = re.search(r"```(?:json|crud-surface)\s*(\{.*?\})\s*```", text, re.DOTALL)
    raw = m.group(1) if m else text.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"{exc.msg} at line {exc.lineno}, column {exc.colno}"
    if not isinstance(parsed, dict):
        return None, "top-level JSON must be an object"
    return parsed, None


def _truthy(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        stripped = value.strip()
        return bool(stripped) and stripped not in {"[]", "{}", '""', "''"}
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _get(obj: dict[str, Any], path: str) -> Any:
    cur: Any = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _require(
    out: Output,
    resource: str,
    platform: str,
    obj: dict[str, Any],
    paths: list[str],
    file: str,
) -> None:
    for path in paths:
        if not _truthy(_get(obj, path)):
            out.add(Evidence(
                type="crud_surface_missing_field",
                message=f"{resource}: missing {platform}.{path}",
                file=file,
                expected=path,
                fix_hint=(
                    "Fill CRUD-SURFACES.md from "
                    "commands/vg/_shared/templates/CRUD-SURFACES-template.md. "
                    "Use 'none: reason' or 'n/a: reason' when intentionally absent."
                ),
            ))


def _ops(resource: dict[str, Any]) -> set[str]:
    return {str(x).lower() for x in resource.get("operations", []) if str(x).strip()}


def _validate_resource(
    out: Output,
    resource: dict[str, Any],
    required_platforms: list[str],
    file: str,
) -> None:
    name = str(resource.get("name") or "<unnamed>")
    operations = _ops(resource)
    if not name or name == "<unnamed>":
        out.add(Evidence(
            type="crud_surface_missing_resource_name",
            message="CRUD resource missing non-empty name",
            file=file,
        ))
    if not operations:
        out.add(Evidence(
            type="crud_surface_missing_operations",
            message=f"{name}: operations must list CRUD operations touched by the phase",
            file=file,
            expected="operations: ['list', 'create', 'update', ...]",
        ))

    base = resource.get("base")
    if not isinstance(base, dict):
        out.add(Evidence(
            type="crud_surface_missing_base",
            message=f"{name}: base contract missing",
            file=file,
        ))
        base = {}

    _require(out, name, "base", base, [
        "roles",
        "business_flow.invariants",
        "security.object_auth",
        "security.field_auth",
        "security.rate_limit",
        "abuse.enumeration_guard",
        "abuse.replay_guard",
        "performance.api_p95_ms",
    ], file)

    if "delete" in operations:
        _require(out, name, "base", base, [
            "delete_policy.confirm",
            "delete_policy.reversible_policy",
            "delete_policy.audit_log",
        ], file)

    platforms = resource.get("platforms")
    if not isinstance(platforms, dict):
        out.add(Evidence(
            type="crud_surface_missing_platforms",
            message=f"{name}: platforms overlay missing",
            file=file,
        ))
        platforms = {}

    for platform in required_platforms:
        overlay = platforms.get(platform)
        if not isinstance(overlay, dict):
            out.add(Evidence(
                type="crud_surface_missing_platform_overlay",
                message=f"{name}: profile requires platforms.{platform} overlay",
                file=file,
                expected=platform,
            ))
            continue

        if platform == "web":
            if "list" in operations:
                _require(out, name, "web", overlay, [
                    "list.route",
                    "list.heading",
                    "list.description",
                    "list.states",
                    "list.data_controls.filters",
                    "list.data_controls.search",
                    "list.data_controls.sort",
                    "list.data_controls.pagination",
                    "list.table.columns",
                    "list.table.row_actions",
                    "list.accessibility.table_headers",
                    "list.accessibility.aria_sort",
                ], file)
                states = _get(overlay, "list.states") or []
                if isinstance(states, list):
                    missing_states = {"loading", "empty", "error"} - {str(x) for x in states}
                    if missing_states:
                        out.add(Evidence(
                            type="crud_surface_missing_web_states",
                            message=f"{name}: web list must cover loading/empty/error states",
                            file=file,
                            expected=sorted(missing_states),
                            actual=states,
                        ))
            if {"create", "update"} & operations:
                _require(out, name, "web", overlay, [
                    "form.fields",
                    "form.validation",
                    "form.error_summary",
                    "form.duplicate_submit_guard",
                ], file)
            if "delete" in operations:
                _require(out, name, "web", overlay, [
                    "delete.confirm_dialog",
                    "delete.post_delete_state",
                ], file)

        if platform == "mobile":
            if "list" in operations:
                _require(out, name, "mobile", overlay, [
                    "list.screen",
                    "list.deep_link_state",
                    "list.pull_to_refresh",
                    "list.pagination_pattern",
                    "list.tap_target_min_px",
                    "list.states",
                    "list.network_error_state",
                ], file)
            if {"create", "update"} & operations:
                _require(out, name, "mobile", overlay, [
                    "form.screen",
                    "form.keyboard_avoidance",
                    "form.native_picker_behavior",
                    "form.submit_disabled_during_request",
                    "form.offline_submit_policy",
                ], file)
            if "delete" in operations:
                _require(out, name, "mobile", overlay, [
                    "delete.confirm_sheet",
                    "delete.undo_or_soft_delete_policy",
                ], file)

        if platform == "backend":
            if "list" in operations:
                _require(out, name, "backend", overlay, [
                    "list_endpoint.path",
                    "list_endpoint.pagination.max_page_size",
                    "list_endpoint.filter_sort_allowlist",
                    "list_endpoint.stable_default_sort",
                    "list_endpoint.invalid_query_behavior",
                ], file)
            if {"create", "update", "delete", "bulk"} & operations:
                _require(out, name, "backend", overlay, [
                    "mutation.paths",
                    "mutation.validation_4xx",
                    "mutation.object_authz",
                    "mutation.mass_assignment_guard",
                    "mutation.idempotency",
                    "mutation.audit_log",
                ], file)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate CRUD-SURFACES.md")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--config", default=str(REPO_ROOT / ".claude" / "vg.config.md"))
    parser.add_argument("--allow-missing", action="store_true",
                        help="Downgrade missing CRUD-SURFACES.md to WARN")
    args = parser.parse_args()

    out = Output(validator="crud-surface-contract")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if phase_dir is None:
            out.add(Evidence(
                type="phase_not_found",
                message=f"Phase directory not found for {args.phase}",
                expected=".vg/phases/<phase>-*",
            ))
            emit_and_exit(out)

        text = _phase_text(phase_dir)
        has_crud_signal = bool(CRUD_SIGNAL_RE.search(text))
        contract_path = phase_dir / "CRUD-SURFACES.md"

        if not contract_path.exists():
            if has_crud_signal:
                ev = Evidence(
                    type="crud_surface_contract_missing",
                    message=(
                        "CRUD/resource signals detected but CRUD-SURFACES.md "
                        "is missing"
                    ),
                    file=str(contract_path),
                    expected="CRUD-SURFACES.md with JSON contract",
                    fix_hint=(
                        "Generate it during /vg:blueprint from "
                        "commands/vg/_shared/templates/CRUD-SURFACES-template.md."
                    ),
                )
                if args.allow_missing:
                    out.warn(ev)
                else:
                    out.add(ev)
            emit_and_exit(out)

        data, parse_error = _extract_json(_read(contract_path))
        if parse_error:
            out.add(Evidence(
                type="crud_surface_json_invalid",
                message=f"CRUD-SURFACES.md JSON parse failed: {parse_error}",
                file=str(contract_path),
                expected="A fenced ```json object matching schemas/crud-surface.v1.json",
            ))
            emit_and_exit(out)

        if data.get("version") != "1":
            out.add(Evidence(
                type="crud_surface_version_invalid",
                message="CRUD-SURFACES.md must use version '1'",
                file=str(contract_path),
                expected="version: 1",
                actual=data.get("version"),
            ))

        resources = data.get("resources")
        if not isinstance(resources, list):
            out.add(Evidence(
                type="crud_surface_resources_invalid",
                message="CRUD-SURFACES.md resources must be an array",
                file=str(contract_path),
                expected="resources: []",
            ))
            resources = []

        if has_crud_signal and not resources:
            out.add(Evidence(
                type="crud_surface_resources_empty",
                message="CRUD/resource signals detected but resources[] is empty",
                file=str(contract_path),
                expected="At least one resource contract",
                fix_hint="If this is not CRUD, add no_crud_reason and remove CRUD/list/form wording from artifacts.",
            ))

        profile = _read_project_profile(Path(args.config))
        plan_text = _plan_text(phase_dir)
        required_platforms = _required_platforms(profile, text, plan_text)
        for resource in resources:
            if isinstance(resource, dict):
                _validate_resource(out, resource, required_platforms, str(contract_path))
            else:
                out.add(Evidence(
                    type="crud_surface_resource_invalid",
                    message="Each resources[] item must be an object",
                    file=str(contract_path),
                    actual=type(resource).__name__,
                ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
