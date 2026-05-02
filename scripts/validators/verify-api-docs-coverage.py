#!/usr/bin/env python3
"""Validator: verify-api-docs-coverage.py."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, find_phase_dir, timer  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api_docs_common import (  # noqa: E402
    classify_query_controls,
    extract_contract_request_shape,
    parse_api_docs_entries,
    parse_contract_sections,
)


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def _resolve_paths(args: argparse.Namespace) -> tuple[Path | None, Path | None]:
    if args.contracts and args.docs:
        return Path(args.contracts), Path(args.docs)
    if args.phase:
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            return None, None
        return Path(phase_dir) / "API-CONTRACTS.md", Path(phase_dir) / "API-DOCS.md"
    return None, None


def _interface_standards_requires_error_handling(docs_path: Path) -> bool:
    standards = docs_path.parent / "INTERFACE-STANDARDS.json"
    if not standards.exists():
        return False
    try:
        data = json.loads(standards.read_text(encoding="utf-8"))
    except Exception:
        return False
    surfaces = data.get("surfaces") if isinstance(data, dict) else {}
    return bool(isinstance(surfaces, dict) and surfaces.get("api"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--phase")
    ap.add_argument("--contracts")
    ap.add_argument("--docs")
    args = ap.parse_args()

    out = Output(validator="verify-api-docs-coverage")
    with timer(out):
        contracts_path, docs_path = _resolve_paths(args)
        if not contracts_path or not docs_path:
            out.add(Evidence(
                type="api_docs_args_invalid",
                message="Pass either --phase or both --contracts and --docs",
            ))
            emit_and_exit(out)
        if not contracts_path.exists():
            out.add(Evidence(
                type="api_docs_contracts_missing",
                message=f"API contracts missing: {contracts_path}",
                file=str(contracts_path),
            ))
            emit_and_exit(out)
        if not docs_path.exists():
            out.add(Evidence(
                type="api_docs_missing",
                message=f"API docs missing: {docs_path}",
                file=str(docs_path),
                fix_hint="Run /vg:build so step 9 generates API-DOCS.md from the implemented API surface.",
            ))
            emit_and_exit(out)

        sections = parse_contract_sections(contracts_path)
        entries = parse_api_docs_entries(docs_path)
        require_error_handling = _interface_standards_requires_error_handling(docs_path)
        if not entries:
            out.add(Evidence(
                type="api_docs_no_entries",
                message="API-DOCS.md has no machine-readable endpoint entries",
                file=str(docs_path),
            ))
            emit_and_exit(out)

        for section in sections:
            key = (section.method, section.path)
            entry = entries.get(key)
            if not entry:
                out.add(Evidence(
                    type="api_docs_endpoint_missing",
                    message=f"{section.method} {section.path} missing from API-DOCS.md",
                    file=str(docs_path),
                    expected=f"{section.method} {section.path}",
                ))
                continue

            for required_key in ("purpose", "request", "response", "implementation", "ai_notes"):
                value = entry.get(required_key)
                if not value:
                    out.add(Evidence(
                        type="api_docs_required_field_missing",
                        message=f"{section.method} {section.path} missing '{required_key}' in API-DOCS.md",
                        file=str(docs_path),
                        expected=required_key,
                    ))

            if require_error_handling:
                error_handling = entry.get("error_handling")
                if not isinstance(error_handling, dict) or not error_handling:
                    out.add(Evidence(
                        type="api_docs_error_handling_missing",
                        message=f"{section.method} {section.path} missing error_handling from INTERFACE-STANDARDS.md",
                        file=str(docs_path),
                        expected="error_handling.message_priority + ui_rule",
                        fix_hint="Regenerate API-DOCS.md during /vg:build after INTERFACE-STANDARDS exists.",
                    ))
                else:
                    priority = error_handling.get("message_priority") or []
                    if "error.message" not in priority:
                        out.add(Evidence(
                            type="api_docs_error_message_priority_missing",
                            message=f"{section.method} {section.path} error_handling does not include API error message priority",
                            file=str(docs_path),
                            expected="error.user_message -> error.message",
                            actual=priority,
                        ))

            impl = entry.get("implementation") or {}
            if not (impl.get("route_hits") or impl.get("consumer_hits")):
                out.add(Evidence(
                    type="api_docs_impl_evidence_missing",
                    message=f"{section.method} {section.path} missing implementation evidence in API-DOCS.md",
                    file=str(docs_path),
                    fix_hint="Generator must record route_hits and/or consumer_hits so AI can trace code ownership.",
                ))

            expected_request = extract_contract_request_shape(section)
            expected_query = expected_request.get("query") or {}
            actual_request = entry.get("request") if isinstance(entry, dict) else {}
            actual_query = actual_request.get("query") if isinstance(actual_request, dict) else {}
            actual_query = actual_query if isinstance(actual_query, dict) else {}

            for query_name, expected_meta in expected_query.items():
                if query_name not in actual_query:
                    out.add(Evidence(
                        type="api_docs_query_param_missing",
                        message=(
                            f"{section.method} {section.path} missing query param "
                            f"'{query_name}' in API-DOCS.md request.query"
                        ),
                        file=str(docs_path),
                        expected=query_name,
                        actual=sorted(actual_query.keys()),
                        fix_hint=(
                            "Build API-DOCS.md from API-CONTRACTS.md Zod/table "
                            "request shape so review lenses know which filters, "
                            "search, sort, and pagination controls must be tested."
                        ),
                    ))
                    continue
                expected_enum = sorted(str(v) for v in (expected_meta.get("enum") or []))
                actual_meta = actual_query.get(query_name)
                actual_meta = actual_meta if isinstance(actual_meta, dict) else {}
                actual_enum = sorted(str(v) for v in (actual_meta.get("enum") or []))
                if expected_enum and actual_enum and expected_enum != actual_enum:
                    out.add(Evidence(
                        type="api_docs_query_enum_mismatch",
                        message=(
                            f"{section.method} {section.path} query param '{query_name}' "
                            "enum differs from API-CONTRACTS.md"
                        ),
                        file=str(docs_path),
                        expected=expected_enum,
                        actual=actual_enum,
                    ))

            expected_entry = dict(entry)
            expected_entry["request"] = {
                **((entry.get("request") or {}) if isinstance(entry.get("request"), dict) else {}),
                "query": expected_query or actual_query,
            }
            controls = classify_query_controls(expected_entry)
            if controls["filters"] and not (entry.get("ai_notes") or {}).get("filter_semantics"):
                out.add(Evidence(
                    type="api_docs_filter_notes_missing",
                    message=f"{section.method} {section.path} has filter query params but no filter_semantics notes",
                    file=str(docs_path),
                ))
            if controls["has_pagination"] and not (entry.get("ai_notes") or {}).get("paging_semantics"):
                out.add(Evidence(
                    type="api_docs_paging_notes_missing",
                    message=f"{section.method} {section.path} has pagination query params but no paging_semantics notes",
                    file=str(docs_path),
                ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
