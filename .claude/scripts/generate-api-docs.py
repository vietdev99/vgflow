#!/usr/bin/env python3
"""Generate AI-facing API-DOCS.md from API-CONTRACTS.md + built source evidence."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from api_docs_common import (
    ContractSection,
    extract_contract_request_shape,
    parse_contract_sections,
    parse_enum_values,
)


REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
FIRST_LINE_RE = re.compile(r"^\s*[-*]?\s*(.+\S)\s*$", re.MULTILINE)
TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")
PATH_PARAM_RE = re.compile(r"(:[A-Za-z0-9_]+|\{[^}/]+\})")

SOURCE_GLOBS = [
    "apps/*/src/**/*.ts",
    "apps/*/src/**/*.tsx",
    "apps/*/src/**/*.js",
    "apps/*/src/**/*.jsx",
    "apps/*/src/**/*.py",
    "packages/*/src/**/*.ts",
]
FRONTEND_GLOBS = [
    "apps/web/src/**/*.ts",
    "apps/web/src/**/*.tsx",
    "apps/admin/src/**/*.ts",
    "apps/admin/src/**/*.tsx",
    "packages/ui/src/**/*.ts",
    "packages/ui/src/**/*.tsx",
]


def _load_interface_standards(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _error_handling_from_standards(standards: dict[str, Any]) -> dict[str, Any]:
    api = standards.get("api") if isinstance(standards.get("api"), dict) else {}
    frontend = standards.get("frontend") if isinstance(standards.get("frontend"), dict) else {}
    error_env = api.get("error_envelope") if isinstance(api.get("error_envelope"), dict) else {}
    priority = (
        error_env.get("message_priority")
        or frontend.get("api_error_message_priority")
        or ["error.user_message", "error.message", "message", "network_fallback"]
    )
    return {
        "error_envelope": error_env.get("required_shape") or {
            "ok": False,
            "error": {
                "code": "string",
                "message": "string",
                "user_message": "string optional",
                "field_errors": "object optional",
            },
        },
        "message_priority": priority,
        "ui_rule": (
            frontend.get("toast_rule")
            or "Show API error body message; never show statusText or generic HTTP error text."
        ),
        "field_error_path": "error.field_errors",
        "http_status_text_banned": frontend.get("http_status_text_banned", True),
    }


def _scan_files(globs: list[str]) -> list[Path]:
    files: list[Path] = []
    for pattern in globs:
        try:
            for path in REPO_ROOT.glob(pattern):
                if path.is_file():
                    files.append(path)
        except Exception:
            continue
    return files


def _find_block(body: str, heading: str) -> str:
    pattern = re.compile(
        rf"^\*\*{re.escape(heading)}:\*\*\s*$"
        rf"(.*?)(?=^\*\*[A-Za-z][^:]+:\*\*\s*$|^#{2,4}\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(body)
    return match.group(1).strip() if match else ""


def _parse_markdown_table(block: str) -> list[dict[str, str]]:
    rows: list[list[str]] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        if re.match(r"^\|\s*-", line):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        rows.append(cells)
    if len(rows) < 2:
        return []
    headers = [re.sub(r"[^a-z0-9]+", "_", cell.lower()).strip("_") for cell in rows[0]]
    parsed: list[dict[str, str]] = []
    for row in rows[1:]:
        if len(row) != len(headers):
            continue
        item = {headers[idx]: row[idx] for idx in range(len(headers))}
        if not any(item.values()):
            continue
        parsed.append(item)
    return parsed


def _first_purpose_line(body: str, method: str, path: str) -> str:
    purpose_match = re.search(r"^\*\*Purpose:\*\*\s*(.+?)\s*$", body, re.MULTILINE)
    if purpose_match:
        return purpose_match.group(1).strip()

    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("**Request:", "**Response:", "**Auth:", "|", "```", "###", "##")):
            continue
        if stripped.startswith(("-", "*")):
            stripped = stripped[1:].strip()
        if stripped:
            return stripped.rstrip(".")

    resource = path.rstrip("/").split("/")[-1] or "resource"
    if method == "GET":
        if PATH_PARAM_RE.search(path):
            return f"Read a single {resource}"
        return f"List {resource} records"
    if method == "POST":
        return f"Create a new {resource}"
    if method in {"PUT", "PATCH"}:
        return f"Update {resource}"
    if method == "DELETE":
        return f"Delete {resource}"
    return f"{method} {path}"


def _extract_auth(body: str) -> str:
    match = re.search(r"^\*\*Auth:\*\*\s*(.+?)\s*$", body, re.MULTILINE)
    return match.group(1).strip() if match else "unspecified"


def _field_meta(row: dict[str, str]) -> dict[str, Any]:
    field = row.get("field") or row.get("name") or ""
    field_type = row.get("type") or row.get("field_type") or row.get("data_type") or "unknown"
    required = (row.get("required") or "").strip().lower() in {"yes", "true", "required"}
    source = row.get("source") or row.get("description") or row.get("notes") or ""
    description = row.get("description") or row.get("source") or row.get("notes") or ""
    enum_values = parse_enum_values(f"{field_type} {source} {description}")
    return {
        "field": field,
        "type": field_type,
        "required": required,
        "source": source,
        "description": description,
        "enum": enum_values,
    }


def _request_shape(section: ContractSection) -> dict[str, dict[str, Any]]:
    request_block = _find_block(section.body, "Request")
    rows = _parse_markdown_table(request_block)
    request = {"query": {}, "path": {}, "body": {}}
    path_params = {seg.strip("{}:") for seg in PATH_PARAM_RE.findall(section.path)}
    for row in rows:
        meta = _field_meta(row)
        field = meta["field"]
        if not field:
            continue
        source_text = f"{meta['source']} {meta['description']}".lower()
        if field in path_params or "path" in source_text:
            bucket = "path"
        elif "query" in source_text or (section.method == "GET" and "body" not in source_text):
            bucket = "query"
        else:
            bucket = "body"
        request[bucket][field] = {
            "type": meta["type"],
            "required": meta["required"],
            "description": meta["description"] or meta["source"],
            "enum": meta["enum"],
        }
    contract_shape = extract_contract_request_shape(section)
    for bucket in ("query", "path", "body"):
        request[bucket].update(contract_shape.get(bucket) or {})
    return request


def _response_shape(section: ContractSection) -> dict[str, Any]:
    response_block = _find_block(section.body, "Response")
    rows = _parse_markdown_table(response_block)
    fields: list[str] = []
    collection = False
    for row in rows:
        meta = _field_meta(row)
        field = meta["field"]
        if not field:
            continue
        fields.append(field)
        if "[]" in field or field.startswith("data["):
            collection = True
    return {
        "fields": fields[:30],
        "collection": collection,
        "root": "data" if any(f == "data" or f.startswith("data[") for f in fields) else "",
    }


def _goal_refs(goals_text: str, method: str, path: str) -> list[str]:
    refs: list[str] = []
    blocks = re.split(r"^##\s+Goal\s+", goals_text, flags=re.MULTILINE)
    for block in blocks[1:]:
        header = block.splitlines()[0].strip()
        if f"{method} {path}" not in block:
            continue
        refs.append(header)
    return refs[:8]


def _search_hits(files: list[Path], term: str) -> list[str]:
    hits: list[str] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if term in text:
            hits.append(str(path.relative_to(REPO_ROOT)))
        if len(hits) >= 5:
            break
    return hits


def _route_term(path: str) -> str:
    static = [seg for seg in path.split("/") if seg and not seg.startswith(":") and not seg.startswith("{")]
    return f"/{static[-1]}" if static else path


def _format_query_summary(query: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if not query:
        return lines
    for name, meta in query.items():
        bits = [name]
        if meta.get("enum"):
            bits.append("enum=" + ",".join(meta["enum"]))
        if meta.get("required"):
            bits.append("required")
        desc = meta.get("description") or ""
        if desc:
            bits.append(desc)
        lines.append("- " + " | ".join(bits))
    return lines


def build_doc(section: ContractSection, plan_text: str, goals_text: str,
              source_files: list[Path], frontend_files: list[Path],
              interface_standards: dict[str, Any]) -> dict[str, Any]:
    request = _request_shape(section)
    response = _response_shape(section)
    route_hits = _search_hits(source_files, _route_term(section.path))
    consumer_hits = _search_hits(frontend_files, section.path)
    goal_refs = _goal_refs(goals_text, section.method, section.path)

    filter_semantics = []
    paging_semantics = []
    for name, meta in request["query"].items():
        lower = name.lower()
        if meta.get("enum"):
            filter_semantics.append(
                f"{name} must constrain returned rows/items to the same enum bucket"
            )
        if lower in {"page", "page_no", "page_num", "limit", "per_page", "offset", "cursor"}:
            paging_semantics.append(
                f"{name} must change the returned window without mixing records from other pages"
            )
    if any(name.lower() in {"page", "page_no", "page_num", "limit", "per_page", "offset", "cursor"} for name in request["query"]):
        paging_semantics.append("changing filter/search must reset pagination to the first page/window")

    return {
        "method": section.method,
        "path": section.path,
        "purpose": _first_purpose_line(section.body, section.method, section.path),
        "auth": _extract_auth(section.body),
        "consumers": goal_refs or consumer_hits,
        "request": request,
        "response": response,
        "error_handling": _error_handling_from_standards(interface_standards),
        "implementation": {
            "route_hits": route_hits,
            "consumer_hits": consumer_hits,
        },
        "ai_notes": {
            "build_intent": (
                "Generated at build-time from API-CONTRACTS plus current implementation; "
                "use this as the AI-facing contract for review and test."
            ),
            "filter_semantics": filter_semantics,
            "paging_semantics": paging_semantics,
        },
    }


def render_markdown(phase: str, entries: list[dict[str, Any]]) -> str:
    lines = [
        f"# API Docs — Phase {phase}",
        "",
        "Generated by `/vg:build` after implementation exists.",
        "This file is the AI-facing API reference for `/vg:review` and `/vg:test`.",
        "",
        "## Coverage",
        "",
        f"- Endpoints documented: **{len(entries)}**",
        "- Each endpoint below carries a machine-readable JSON block.",
        "",
    ]

    for entry in entries:
        lines.append(f"## {entry['method']} {entry['path']}")
        lines.append("")
        lines.append(f"Purpose: {entry['purpose']}")
        lines.append("")
        lines.append("```json")
        import json
        lines.append(json.dumps(entry, indent=2, ensure_ascii=True))
        lines.append("```")
        lines.append("")
        query = ((entry.get("request") or {}).get("query") or {})
        if query:
            lines.append("Query Params")
            lines.extend(_format_query_summary(query))
            lines.append("")
        notes = entry.get("ai_notes") or {}
        error_handling = entry.get("error_handling") or {}
        if error_handling:
            lines.append("Error Handling")
            priority = error_handling.get("message_priority") or []
            if priority:
                lines.append("- UI message priority: " + " -> ".join(f"`{p}`" for p in priority))
            lines.append("- Do not display HTTP status/statusText when API body has an error message.")
            lines.append("")
        for key in ("filter_semantics", "paging_semantics"):
            values = notes.get(key) or []
            if values:
                title = "Filter Semantics" if key == "filter_semantics" else "Paging Semantics"
                lines.append(title)
                for value in values:
                    lines.append(f"- {value}")
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", required=True)
    ap.add_argument("--contracts", required=True)
    ap.add_argument("--plan", required=False, default="")
    ap.add_argument("--goals", required=False, default="")
    ap.add_argument("--interface-standards", required=False, default="")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    contracts_path = Path(args.contracts)
    if not contracts_path.exists():
        print(f"missing contracts file: {contracts_path}", file=sys.stderr)
        return 2

    plan_text = Path(args.plan).read_text(encoding="utf-8", errors="replace") if args.plan and Path(args.plan).exists() else ""
    goals_text = Path(args.goals).read_text(encoding="utf-8", errors="replace") if args.goals and Path(args.goals).exists() else ""
    standards_path = Path(args.interface_standards) if args.interface_standards else contracts_path.parent / "INTERFACE-STANDARDS.json"
    interface_standards = _load_interface_standards(standards_path)
    sections = parse_contract_sections(contracts_path)
    if not sections:
        print("no endpoints parsed from API-CONTRACTS.md", file=sys.stderr)
        return 2

    source_files = _scan_files(SOURCE_GLOBS)
    frontend_files = _scan_files(FRONTEND_GLOBS)
    entries = [build_doc(section, plan_text, goals_text, source_files, frontend_files, interface_standards)
               for section in sections]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_markdown(args.phase, entries), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
