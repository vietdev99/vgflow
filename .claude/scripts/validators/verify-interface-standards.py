#!/usr/bin/env python3
"""Validate INTERFACE-STANDARDS and API/FE error-message semantics."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
API_PROFILES = {"web-fullstack", "web-backend-only"}
FE_PROFILES = {"web-fullstack", "web-frontend-only"}
CLI_PROFILES = {"cli-tool", "library"}
HEADING_RE = re.compile(r"^#{1,6}\s+")
EXCLUSION_HEADING_RE = re.compile(
    r"^#{1,6}\s*(out\s+of\s+scope|non[- ]?goals?|exclusions?)\b",
    re.IGNORECASE,
)
NEGATED_SURFACE_RE = re.compile(
    r"\b(no|not|without|exclude[sd]?|excluding|non[- ]|out\s+of\s+scope|"
    r"not\s+in\s+scope|does\s+not|do\s+not|never)\b",
    re.IGNORECASE,
)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _resolve_phase_dir(args: argparse.Namespace) -> Path | None:
    if args.phase_dir:
        path = Path(args.phase_dir)
        return path if path.is_absolute() else REPO_ROOT / path
    if args.phase:
        found = find_phase_dir(args.phase)
        return Path(found) if found else None
    return None


def _affirmative_phase_text(text: str) -> str:
    lines: list[str] = []
    in_exclusion_section = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if HEADING_RE.match(line):
            in_exclusion_section = bool(EXCLUSION_HEADING_RE.match(line))
            if in_exclusion_section:
                continue
        if in_exclusion_section:
            continue
        if NEGATED_SURFACE_RE.search(line):
            continue
        lines.append(raw_line)
    return "\n".join(lines)


def _load_generator_infer():
    candidates = [
        REPO_ROOT / "scripts" / "generate-interface-standards.py",
        REPO_ROOT / ".claude" / "scripts" / "generate-interface-standards.py",
        Path(__file__).resolve().parents[1] / "generate-interface-standards.py",
    ]
    for path in candidates:
        if not path.exists():
            continue
        spec = importlib.util.spec_from_file_location(
            "vg_generate_interface_standards", path,
        )
        if not spec or not spec.loader:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        infer = getattr(module, "infer_surfaces", None)
        if callable(infer):
            return infer
    return None


def _infer_surfaces(phase_dir: Path, profile: str) -> dict[str, bool]:
    try:
        infer_surfaces = _load_generator_infer()
        if infer_surfaces:
            return infer_surfaces(phase_dir, profile)
    except Exception:
        pass
    text = "\n".join(_read(phase_dir / name) for name in (
        "SPECS.md", "CONTEXT.md", "PLAN.md", "API-CONTRACTS.md", "TEST-GOALS.md",
    ))
    affirmative = _affirmative_phase_text(text)
    lower = affirmative.lower()
    is_cli_only = profile in CLI_PROFILES
    return {
        "api": (
            profile in API_PROFILES
            or ((phase_dir / "API-CONTRACTS.md").exists() and not is_cli_only)
            or bool(re.search(r"\b(get|post|put|patch|delete)\s+/", affirmative, re.I))
            or (not is_cli_only and bool(re.search(r"\b(api|endpoint|rest|graphql|webhook)\b", affirmative, re.I)))
        ),
        "frontend": (
            profile in FE_PROFILES
            or "surface: ui" in lower
            or bool(re.search(r"\*\*surface:\*\*\s*ui\b", affirmative, re.I))
            or (not is_cli_only and bool(re.search(r"\b(frontend|ui|page|form|toast)\b", affirmative, re.I)))
        ),
        "cli": profile in CLI_PROFILES or bool(re.search(r"\b(cli|command line|stdout|stderr)\b|--json\b", affirmative, re.I)),
        "mobile": profile.startswith("mobile-") or (not is_cli_only and bool(re.search(r"\b(mobile|ios|android|maestro)\b", affirmative, re.I))),
    }


def _load_json(path: Path, out: Output) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        out.add(Evidence(
            type="interface_json_missing",
            message=f"INTERFACE-STANDARDS.json missing: {path}",
            file=str(path),
            fix_hint="Run generate-interface-standards.py or rerun /vg:specs, /vg:blueprint, or /vg:build.",
        ))
        return None
    except json.JSONDecodeError as exc:
        out.add(Evidence(
            type="interface_json_invalid",
            message=f"INTERFACE-STANDARDS.json is invalid JSON: {exc}",
            file=str(path),
        ))
        return None
    if not isinstance(data, dict):
        out.add(Evidence(
            type="interface_json_invalid",
            message="INTERFACE-STANDARDS.json must be a JSON object",
            file=str(path),
        ))
        return None
    return data


def _validate_payload(payload: dict[str, Any], md_path: Path, json_path: Path, surfaces: dict[str, bool], out: Output) -> None:
    if payload.get("schema") != "interface-standards.v1":
        out.add(Evidence(
            type="interface_schema_invalid",
            message="INTERFACE-STANDARDS.json schema must be interface-standards.v1",
            file=str(json_path),
            expected="interface-standards.v1",
            actual=payload.get("schema"),
        ))
    declared = payload.get("surfaces") if isinstance(payload.get("surfaces"), dict) else {}
    for surface, needed in surfaces.items():
        if needed and not declared.get(surface):
            out.add(Evidence(
                type="interface_surface_missing",
                message=f"Phase appears to need {surface} standards but artifact has it disabled/missing",
                file=str(json_path),
                expected=surface,
                actual=declared,
            ))

    if surfaces.get("api"):
        error_env = ((payload.get("api") or {}).get("error_envelope") or {})
        required = set(error_env.get("required_fields") or [])
        for field in ("error.code", "error.message", "error.user_message", "error.field_errors", "error.request_id"):
            if field not in required:
                out.add(Evidence(
                    type="interface_api_error_field_missing",
                    message=f"API error envelope missing required field declaration {field}",
                    file=str(json_path),
                    expected=field,
                    actual=sorted(required),
                ))
        priority = list(error_env.get("message_priority") or [])
        if not priority or priority[0] != "error.user_message" or "error.message" not in priority:
            out.add(Evidence(
                type="interface_api_message_priority_invalid",
                message="API message priority must prefer error.user_message then error.message",
                file=str(json_path),
                expected=["error.user_message", "error.message"],
                actual=priority,
            ))

    if surfaces.get("frontend") or surfaces.get("mobile"):
        fe = payload.get("frontend") or {}
        priority = list(fe.get("api_error_message_priority") or [])
        if not priority or priority[0] != "error.user_message" or "error.message" not in priority:
            out.add(Evidence(
                type="interface_fe_message_priority_invalid",
                message="Frontend must prefer API body messages over transport errors",
                file=str(json_path),
                expected=["error.user_message", "error.message"],
                actual=priority,
            ))
        if fe.get("http_status_text_banned") is not True:
            out.add(Evidence(
                type="interface_http_status_text_not_banned",
                message="Frontend standard must ban statusText/generic HTTP message as primary UI copy",
                file=str(json_path),
                expected=True,
                actual=fe.get("http_status_text_banned"),
            ))

    if surfaces.get("cli"):
        cli = payload.get("cli") or {}
        if "--json" not in str(cli.get("machine_mode") or ""):
            out.add(Evidence(
                type="interface_cli_json_missing",
                message="CLI standard must require --json machine-readable mode",
                file=str(json_path),
            ))

    md = _read(md_path)
    for heading in ("## API Standard", "## Frontend Error Handling Standard", "## CLI Standard", "## Harness Enforcement"):
        if heading not in md:
            out.add(Evidence(
                type="interface_md_section_missing",
                message=f"INTERFACE-STANDARDS.md missing {heading}",
                file=str(md_path),
                expected=heading,
            ))


BAD_TOAST_RE = re.compile(
    r"toast\.(?:error|warning|warn)\s*\(\s*(?:error|err|e)\.message\b",
    re.IGNORECASE,
)
STATUS_TOAST_RE = re.compile(
    r"toast\.(?:error|warning|warn)\s*\([^)]*(?:statusText|Request failed with status|HTTP\s*\$?\{?\s*(?:status|response\.status))",
    re.IGNORECASE,
)


def _source_files() -> list[Path]:
    patterns = [
        "apps/web/src/**/*.[tj]s",
        "apps/web/src/**/*.[tj]sx",
        "apps/admin/src/**/*.[tj]s",
        "apps/admin/src/**/*.[tj]sx",
        "apps/frontend/src/**/*.[tj]s",
        "apps/frontend/src/**/*.[tj]sx",
        "packages/ui/src/**/*.[tj]s",
        "packages/ui/src/**/*.[tj]sx",
    ]
    files: list[Path] = []
    for pattern in patterns:
        files.extend(p for p in REPO_ROOT.glob(pattern) if p.is_file())
    return sorted(set(files))


def _scan_source(out: Output) -> None:
    for path in _source_files():
        text = _read(path)
        if not text:
            continue
        for idx, line in enumerate(text.splitlines(), 1):
            if BAD_TOAST_RE.search(line):
                out.add(Evidence(
                    type="interface_bad_toast_error_message",
                    message="Toast displays raw Error/AxiosError.message instead of API error body message",
                    file=str(path.relative_to(REPO_ROOT)),
                    line=idx,
                    expected="error.response?.data?.error?.user_message || error.response?.data?.error?.message",
                    actual=line.strip()[:240],
                    fix_hint="Use a shared API error adapter, then toast the API envelope message.",
                ))
            elif STATUS_TOAST_RE.search(line):
                out.add(Evidence(
                    type="interface_http_status_toast",
                    message="Toast displays statusText/generic HTTP status instead of API error body message",
                    file=str(path.relative_to(REPO_ROOT)),
                    line=idx,
                    expected="API envelope message",
                    actual=line.strip()[:240],
                ))
            if len(out.evidence) >= 20:
                return


def _validate_contract_mentions(phase_dir: Path, out: Output) -> None:
    contracts = phase_dir / "API-CONTRACTS.md"
    if not contracts.exists():
        return
    text = _read(contracts)
    if not text.strip():
        return
    has_error_rule = any(token in text for token in (
        "INTERFACE-STANDARDS",
        "response.data.error.message",
        "response.data.error.user_message",
        "error.user_message",
        "FE toast rule",
    ))
    if not has_error_rule:
        out.add(Evidence(
            type="interface_contract_error_rule_missing",
            message="API-CONTRACTS.md does not cite the interface error-message rule",
            file=str(contracts),
            fix_hint="Regenerate contracts so Block 3 states API error envelope and FE message priority.",
        ))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase")
    ap.add_argument("--phase-dir")
    ap.add_argument("--profile", default="web-fullstack")
    ap.add_argument("--no-scan-source", action="store_true")
    args = ap.parse_args()

    out = Output(validator="verify-interface-standards")
    with timer(out):
        phase_dir = _resolve_phase_dir(args)
        if not phase_dir:
            out.add(Evidence(
                type="interface_phase_dir_missing",
                message="Phase directory not found",
                expected=args.phase or args.phase_dir,
            ))
            emit_and_exit(out)

        surfaces = _infer_surfaces(phase_dir, args.profile)
        if not any(surfaces.values()):
            emit_and_exit(out)

        md_path = phase_dir / "INTERFACE-STANDARDS.md"
        json_path = phase_dir / "INTERFACE-STANDARDS.json"
        if not md_path.exists():
            out.add(Evidence(
                type="interface_md_missing",
                message=f"INTERFACE-STANDARDS.md missing: {md_path}",
                file=str(md_path),
                fix_hint="Run generate-interface-standards.py before blueprint/build/review/test.",
            ))
        payload = _load_json(json_path, out)
        if payload:
            _validate_payload(payload, md_path, json_path, surfaces, out)
        if surfaces.get("api"):
            _validate_contract_mentions(phase_dir, out)
        if (surfaces.get("frontend") or surfaces.get("mobile")) and not args.no_scan_source:
            _scan_source(out)

    emit_and_exit(out)


if __name__ == "__main__":
    main()
