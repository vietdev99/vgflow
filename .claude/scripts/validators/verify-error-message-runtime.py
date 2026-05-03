#!/usr/bin/env python3
"""Validate review runtime evidence for API error message -> UI message."""
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
BAD_TRANSPORT_TEXT_RE = re.compile(
    r"(request failed with status|status\s*text|http\s*(40[0-9]|50[0-9])|network error:?\s*(40[0-9]|50[0-9]))",
    re.IGNORECASE,
)


def _resolve_phase_dir(args: argparse.Namespace) -> Path | None:
    if args.phase_dir:
        path = Path(args.phase_dir)
        return path if path.is_absolute() else REPO_ROOT / path
    if args.phase:
        found = find_phase_dir(args.phase)
        return Path(found) if found else None
    return None


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _surfaces_require_probe(phase_dir: Path) -> bool:
    standards_path = phase_dir / "INTERFACE-STANDARDS.json"
    if standards_path.exists():
        try:
            standards = json.loads(standards_path.read_text(encoding="utf-8"))
            surfaces = standards.get("surfaces") or {}
            if surfaces.get("api") and (surfaces.get("frontend") or surfaces.get("mobile")):
                return True
        except Exception:
            pass
    text = "\n".join(_read(phase_dir / name).lower() for name in (
        "API-CONTRACTS.md", "TEST-GOALS.md", "UI-MAP.md", "UI-SPEC.md",
    ))
    return (phase_dir / "API-CONTRACTS.md").exists() and (
        "surface: ui" in text or "toast" in text or "frontend" in text or (phase_dir / "UI-MAP.md").exists()
    )


def _has_mutation_contracts(phase_dir: Path) -> bool:
    text = _read(phase_dir / "API-CONTRACTS.md")
    return bool(re.search(r"^#{2,4}\s+(POST|PUT|PATCH|DELETE)\s+/", text, re.MULTILINE))


def _load_probe(path: Path, out: Output) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        out.add(Evidence(
            type="error_message_probe_missing",
            message=f"error-message-probe.json missing: {path}",
            file=str(path),
            fix_hint="Run /vg:review --mode=full --force so the error-message runtime lens exercises API 4xx/validation paths.",
        ))
        return None
    except json.JSONDecodeError as exc:
        out.add(Evidence(
            type="error_message_probe_invalid_json",
            message=f"error-message-probe.json invalid JSON: {exc}",
            file=str(path),
        ))
        return None
    if not isinstance(data, dict):
        out.add(Evidence(
            type="error_message_probe_invalid_schema",
            message="error-message-probe.json must be a JSON object",
            file=str(path),
        ))
        return None
    return data


def _visible_text(check: dict[str, Any]) -> str:
    for key in ("visible_message", "toast_text", "form_error_text", "ui_message"):
        value = check.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    toast = check.get("toast")
    if isinstance(toast, dict):
        items = toast.get("items")
        if isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, dict):
                return str(first.get("text") or "").strip()
        return str(toast.get("text") or "").strip()
    return ""


def _expected_message(check: dict[str, Any]) -> str:
    for key in ("api_user_message", "api_error_message", "api_message", "expected_message"):
        value = check.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    error = check.get("api_error") or check.get("error")
    if isinstance(error, dict):
        for key in ("user_message", "message"):
            value = error.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _validate_check(check: dict[str, Any], idx: int, path: Path, out: Output) -> None:
    visible = _visible_text(check)
    expected = _expected_message(check)
    if check.get("passed") is False:
        out.add(Evidence(
            type="error_message_probe_failed",
            message=f"Error-message probe check {idx} reported failed",
            file=str(path),
            expected=expected,
            actual=visible or check.get("violations"),
        ))
        return
    if not visible:
        out.add(Evidence(
            type="error_message_ui_missing",
            message=f"Error-message probe check {idx} has no visible toast/form error text",
            file=str(path),
            expected=expected or "visible UI error",
        ))
        return
    if BAD_TRANSPORT_TEXT_RE.search(visible):
        out.add(Evidence(
            type="error_message_transport_text_visible",
            message="Visible UI error uses transport/HTTP text instead of API body message",
            file=str(path),
            expected=expected or "API error body message",
            actual=visible,
        ))
    if expected and expected.lower() not in visible.lower():
        out.add(Evidence(
            type="error_message_api_message_not_visible",
            message="Visible UI error does not include the API-provided message",
            file=str(path),
            expected=expected,
            actual=visible,
        ))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase")
    ap.add_argument("--phase-dir")
    ap.add_argument("--probe", default="")
    args = ap.parse_args()

    out = Output(validator="verify-error-message-runtime")
    with timer(out):
        phase_dir = _resolve_phase_dir(args)
        if not phase_dir:
            out.add(Evidence(
                type="error_message_phase_dir_missing",
                message="Phase directory not found",
                expected=args.phase or args.phase_dir,
            ))
            emit_and_exit(out)
        if not _surfaces_require_probe(phase_dir):
            emit_and_exit(out)

        probe_path = Path(args.probe) if args.probe else phase_dir / "error-message-probe.json"
        if not probe_path.is_absolute():
            probe_path = REPO_ROOT / probe_path
        payload = _load_probe(probe_path, out)
        if not payload:
            emit_and_exit(out)

        checks = payload.get("checks")
        if not isinstance(checks, list) or not checks:
            if _has_mutation_contracts(phase_dir):
                out.add(Evidence(
                    type="error_message_checks_missing",
                    message="error-message-probe.json must include at least one API error UI check for API+UI mutation phases",
                    file=str(probe_path),
                    fix_hint="Trigger validation/auth/domain error paths and record API body message plus visible toast/form error.",
                ))
            emit_and_exit(out)

        for idx, raw in enumerate(checks, 1):
            if not isinstance(raw, dict):
                out.add(Evidence(
                    type="error_message_check_invalid",
                    message=f"checks[{idx}] must be an object",
                    file=str(probe_path),
                ))
                continue
            _validate_check(raw, idx, probe_path, out)

    emit_and_exit(out)


if __name__ == "__main__":
    main()
