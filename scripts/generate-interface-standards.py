#!/usr/bin/env python3
"""Generate phase-local INTERFACE-STANDARDS artifacts.

The artifact is the shared contract for how implemented surfaces communicate:
API request/response envelopes, FE error display semantics, CLI output/error
semantics, and mobile parity. Blueprint/build/review/test all consume it.
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


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

API_PROFILES = {"web-fullstack", "web-backend-only"}
FE_PROFILES = {"web-fullstack", "web-frontend-only"}
CLI_PROFILES = {"cli-tool", "library"}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _phase_number_from_dir(path: Path) -> str:
    match = re.match(r"0*([0-9]+(?:\.[0-9A-Za-z]+)*)", path.name)
    return match.group(1) if match else path.name


def _resolve_phase_dir(phase: str | None, phase_dir: str | None) -> Path:
    if phase_dir:
        path = Path(phase_dir)
        return path if path.is_absolute() else (REPO_ROOT / path)
    if not phase:
        raise SystemExit("pass --phase or --phase-dir")
    phases = REPO_ROOT / ".vg" / "phases"
    candidates = list(phases.glob(f"{phase}-*"))
    if candidates:
        return candidates[0]
    if "." in phase:
        major, _, rest = phase.partition(".")
        normalized = f"{major.zfill(2)}.{rest}" if major.isdigit() else phase
    else:
        normalized = phase.zfill(2) if phase.isdigit() else phase
    candidates = list(phases.glob(f"{normalized}-*"))
    if candidates:
        return candidates[0]
    bare = phases / phase
    if bare.is_dir():
        return bare
    bare = phases / normalized
    if bare.is_dir():
        return bare
    raise SystemExit(f"phase directory not found for {phase}")


def _combined_phase_text(phase_dir: Path) -> str:
    names = [
        "SPECS.md", "CONTEXT.md", "PLAN.md", "API-CONTRACTS.md",
        "TEST-GOALS.md", "UI-SPEC.md", "UI-MAP.md", "CRUD-SURFACES.md",
    ]
    return "\n\n".join(_read(phase_dir / name) for name in names)


def infer_surfaces(phase_dir: Path, profile: str) -> dict[str, bool]:
    text = _combined_phase_text(phase_dir)
    lower = text.lower()
    has_api_contracts = (phase_dir / "API-CONTRACTS.md").exists()
    has_ui_artifacts = any((phase_dir / name).exists() for name in ("UI-MAP.md", "UI-SPEC.md"))
    has_design = any((phase_dir / name).exists() for name in ("design", "designs"))

    api = (
        profile in API_PROFILES
        or has_api_contracts
        or bool(re.search(r"\b(get|post|put|patch|delete)\s+/", text, re.I))
        or any(token in lower for token in (" api ", "endpoint", "rest", "graphql", "webhook"))
    )
    frontend = (
        profile in FE_PROFILES
        or has_ui_artifacts
        or has_design
        or "surface: ui" in lower
        or "**surface:** ui" in lower
        or any(token in lower for token in ("frontend", "ui ", "page ", "form ", "toast"))
    )
    cli = profile in CLI_PROFILES or any(token in lower for token in (" cli ", "command line", "stdout", "stderr", "--json"))
    mobile = profile.startswith("mobile-") or any(token in lower for token in ("mobile", "ios", "android", "maestro"))
    return {
        "api": bool(api),
        "frontend": bool(frontend),
        "cli": bool(cli),
        "mobile": bool(mobile),
    }


def build_payload(phase_dir: Path, profile: str) -> dict[str, Any]:
    phase = _phase_number_from_dir(phase_dir)
    surfaces = infer_surfaces(phase_dir, profile)
    message_priority = [
        "error.user_message",
        "error.message",
        "message",
        "network_fallback",
    ]
    return {
        "schema": "interface-standards.v1",
        "phase": phase,
        "profile": profile,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "surfaces": surfaces,
        "api": {
            "enabled": surfaces["api"],
            "request": {
                "content_type": "application/json",
                "correlation_id_header": "X-Request-Id",
                "auth_header": "Authorization: Bearer <token> when required",
                "validation": "Reject invalid body/query/path before side effects.",
            },
            "success_envelope": {
                "required_shape": {
                    "ok": True,
                    "data": "object|array|null",
                    "message": "optional user-facing success message",
                    "meta": "optional paging/summary metadata",
                    "request_id": "optional correlation id",
                },
                "http_policy": "2xx status must match the completed operation; do not hide domain failures in 200 responses.",
            },
            "error_envelope": {
                "required_shape": {
                    "ok": False,
                    "error": {
                        "code": "stable machine-readable string",
                        "message": "safe default user-facing message",
                        "user_message": "optional localized/user-facing override",
                        "details": "optional object for diagnostics",
                        "field_errors": "optional map field -> message[]",
                        "request_id": "optional correlation id",
                    },
                },
                "required_fields": [
                    "error.code",
                    "error.message",
                    "error.user_message",
                    "error.field_errors",
                    "error.request_id",
                ],
                "legacy_compact_error_shape": "{ error: { code: string, message: string } } is accepted only when endpoint docs explicitly declare it; FE message priority still applies.",
                "message_priority": message_priority,
                "http_status_policy": "HTTP status is transport/classification only; UI must not display statusText or generic HTTP messages when API error message exists.",
            },
        },
        "frontend": {
            "enabled": surfaces["frontend"] or surfaces["mobile"],
            "api_error_message_priority": message_priority,
            "http_status_text_banned": True,
            "toast_rule": "Show error.user_message || error.message || message; never show AxiosError.message, Response.statusText, or 'Request failed with status ...' when the API body has a message.",
            "field_error_rule": "Bind error.field_errors to form fields; non-field errors go to toast/banner/alert.",
            "network_fallback": "Network error - check connection",
            "loading_rule": "Mutations set loading before request, disable submit while pending, and clear loading in finally.",
        },
        "cli": {
            "enabled": surfaces["cli"],
            "success": "Exit 0. Human stdout is concise; --json emits a stable object with ok:true,data,meta.",
            "error": "Exit non-zero. stderr includes CODE: message; --json emits ok:false,error:{code,message,details?}.",
            "machine_mode": "--json must be supported for commands used by automation.",
        },
        "harness": {
            "blueprint": "API-CONTRACTS.md must cite this artifact and use the API error envelope/message priority.",
            "build": "Executors must receive this artifact before coding API clients, handlers, forms, or CLI commands.",
            "review": "Runtime lenses must compare API error body messages with visible toast/form errors.",
            "test": "Generated tests must assert API error-message semantics for negative/mutation paths.",
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    surfaces = payload["surfaces"]
    lines = [
        f"# Interface Standards - Phase {payload['phase']}",
        "",
        "This file is the phase-local contract for how API, frontend, CLI, and mobile surfaces exchange data and errors.",
        "",
        "## Surface Profile",
        "",
    ]
    for key in ("api", "frontend", "cli", "mobile"):
        lines.append(f"- **{key}:** {'enabled' if surfaces.get(key) else 'not in scope'}")

    lines.extend([
        "",
        "## API Standard",
        "",
        "Success envelope:",
        "",
        "```json",
        json.dumps(payload["api"]["success_envelope"]["required_shape"], indent=2, ensure_ascii=True),
        "```",
        "",
        "Error envelope:",
        "",
        "```json",
        json.dumps(payload["api"]["error_envelope"]["required_shape"], indent=2, ensure_ascii=True),
        "```",
        "",
        "Rules:",
        "- `error.code` is stable and machine-readable.",
        "- `error.message` is safe to show to users.",
        "- `error.user_message` overrides `error.message` when localized/domain-specific copy exists.",
        "- `error.field_errors` maps validation failures to form fields.",
        "- HTTP status/statusText is transport metadata, not UI copy.",
        "",
        "## Frontend Error Handling Standard",
        "",
        "Message priority:",
    ])
    for idx, item in enumerate(payload["frontend"]["api_error_message_priority"], 1):
        lines.append(f"{idx}. `{item}`")
    lines.extend([
        "",
        "Required behavior:",
        "- Toast/banner/form errors must show the API-provided message when one exists.",
        "- Do not show raw AxiosError.message, Response.statusText, HTTP status code text, or `Request failed with status ...` as the primary user message.",
        "- Field validation uses `error.field_errors`; non-field API errors use toast/banner/alert.",
        "- Network/no-body failures use the configured network fallback.",
        "",
        "## CLI Standard",
        "",
        "- Success: exit 0; `--json` emits `ok:true,data,meta`.",
        "- Error: non-zero exit; stderr emits `CODE: message`; `--json` emits `ok:false,error:{code,message,details?}`.",
        "- Commands used by automation must support machine-readable output.",
        "",
        "## Harness Enforcement",
        "",
        "- Blueprint: contracts must cite this standard before build.",
        "- Build: executors receive this standard in their prompt context.",
        "- Review: runtime error-message lens compares API body message to visible UI message.",
        "- Test: generated tests assert message priority on negative/mutation paths.",
        "",
        "## Machine Readable",
        "",
        "```json",
        json.dumps(payload, indent=2, ensure_ascii=True),
        "```",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase")
    ap.add_argument("--phase-dir")
    ap.add_argument("--profile", default="web-fullstack")
    ap.add_argument("--out-md")
    ap.add_argument("--out-json")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    phase_dir = _resolve_phase_dir(args.phase, args.phase_dir)
    md_path = Path(args.out_md) if args.out_md else phase_dir / "INTERFACE-STANDARDS.md"
    json_path = Path(args.out_json) if args.out_json else phase_dir / "INTERFACE-STANDARDS.json"
    if not md_path.is_absolute():
        md_path = REPO_ROOT / md_path
    if not json_path.is_absolute():
        json_path = REPO_ROOT / json_path

    if md_path.exists() and json_path.exists() and not args.force:
        print(f"INTERFACE-STANDARDS already present: {md_path}")
        return 0

    payload = build_payload(phase_dir, args.profile)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    print(f"wrote {md_path}")
    print(f"wrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
