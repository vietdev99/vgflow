#!/usr/bin/env python3
"""Shared parsing helpers for VG API docs / contracts."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ENDPOINT_HEADER_RE = re.compile(
    r"^#{2,4}\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/\S+)\s*$",
    re.MULTILINE | re.IGNORECASE,
)

DOC_JSON_BLOCK_RE = re.compile(
    r"^##\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(\S+)\s*$"
    r".*?```json\s*\n(.*?)\n```",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)

ENUM_RE = re.compile(
    r"\benum\s*[:=]\s*([A-Za-z0-9_./|,\- ]+)",
    re.IGNORECASE,
)

STANDARD_SEARCH_PARAMS = {"q", "query", "search", "keyword"}
STANDARD_SORT_PARAMS = {"sort", "sort_by", "sortby", "order", "dir", "direction"}
STANDARD_PAGINATION_PARAMS = {
    "page", "page_no", "page_num", "page_size", "limit", "per_page",
    "offset", "cursor", "next_cursor", "prev_cursor", "size",
}

PATH_PARAM_RE = re.compile(r"(:[A-Za-z0-9_]+|\{[^}/]+\})")
REQUEST_HEADING_RE = re.compile(
    r"^\*\*Request:\*\*\s*$"
    r"(.*?)(?=^\*\*[A-Za-z][^:]+:\*\*\s*$|^#{2,4}\s|\Z)",
    re.MULTILINE | re.DOTALL,
)
TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")


@dataclass
class ContractSection:
    method: str
    path: str
    body: str


def parse_contract_sections_text(text: str) -> list[ContractSection]:
    matches = list(ENDPOINT_HEADER_RE.finditer(text))
    sections: list[ContractSection] = []
    for idx, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        sections.append(
            ContractSection(
                method=match.group(1).upper(),
                path=match.group(2).strip(),
                body=text[body_start:body_end],
            )
        )
    return sections


def parse_contract_sections(path: Path) -> list[ContractSection]:
    if not path.exists():
        return []
    return parse_contract_sections_text(path.read_text(encoding="utf-8", errors="replace"))


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
        if any(item.values()):
            parsed.append(item)
    return parsed


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


def _extract_request_table_shape(section: ContractSection) -> dict[str, dict[str, Any]]:
    request = {"query": {}, "path": {}, "body": {}}
    match = REQUEST_HEADING_RE.search(section.body)
    if not match:
        return request
    rows = _parse_markdown_table(match.group(1).strip())
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
    return request


def _extract_balanced_object(text: str, start: int) -> str:
    """Return content inside the first balanced `{...}` at or after start."""
    brace = text.find("{", start)
    if brace < 0:
        return ""
    depth = 0
    quote: str | None = None
    escaped = False
    for idx in range(brace, len(text)):
        ch = text[idx]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            continue
        if ch in {'"', "'", "`"}:
            quote = ch
            continue
        if ch == "{":
            depth += 1
            if depth == 1:
                body_start = idx + 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[body_start:idx]
    return ""


def _zod_kind(expr: str) -> str:
    lower = expr.lower()
    if "boolean" in lower:
        return "boolean"
    if "number" in lower or ".int(" in lower or "bigint" in lower:
        return "number"
    if "array" in lower:
        return "array"
    if "object" in lower:
        return "object"
    if "date" in lower or "datetime" in lower:
        return "string"
    return "string"


def _zod_enum_values(expr: str) -> list[str]:
    match = re.search(r"z\.enum\(\s*\[([^\]]+)\]", expr, re.DOTALL)
    if not match:
        return []
    return re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))


def _extract_zod_object_fields(object_body: str) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    # This intentionally handles top-level Zod field declarations. Nested
    # response objects are not needed for query/filter contract coverage.
    field_re = re.compile(
        r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+?)(?:,\s*)?$",
        re.MULTILINE,
    )
    for match in field_re.finditer(object_body):
        name = match.group(1)
        expr = match.group(2).strip()
        if name.startswith("_") or expr.startswith("..."):
            continue
        if "z." not in expr:
            continue
        fields[name] = {
            "type": _zod_kind(expr),
            "required": not any(token in expr for token in (".optional(", ".nullish(", ".default(")),
            "description": "extracted from API-CONTRACTS Zod schema",
            "enum": _zod_enum_values(expr),
        }
    return fields


def _extract_zod_bucket(body: str, suffix: str) -> dict[str, dict[str, Any]]:
    pattern = re.compile(
        rf"export\s+const\s+[A-Za-z0-9_]*{suffix}\s*=\s*z\.object\s*\(",
        re.MULTILINE,
    )
    for match in pattern.finditer(body):
        object_body = _extract_balanced_object(body, match.end())
        if object_body:
            return _extract_zod_object_fields(object_body)
    return {}


def extract_contract_request_shape(section: ContractSection) -> dict[str, dict[str, Any]]:
    """Infer request query/path/body shape from API-CONTRACTS.md.

    Supports both table-style contracts and build-time Zod snippets such as
    `export const AdminListFooQuery = z.object({ status: ... })`. The latter
    is critical because `/vg:build` often knows the final implemented schema
    only as source-backed Zod, not a manually maintained table.
    """
    request = _extract_request_table_shape(section)
    zod_shape = {
        "query": _extract_zod_bucket(section.body, "Query"),
        "path": _extract_zod_bucket(section.body, "Params"),
        "body": _extract_zod_bucket(section.body, "Body"),
    }
    for bucket, fields in zod_shape.items():
        request[bucket].update(fields)
    # URL path params are required even when the contract omits Params schema.
    for raw in PATH_PARAM_RE.findall(section.path):
        name = raw.strip("{}:")
        request["path"].setdefault(name, {
            "type": "string",
            "required": True,
            "description": "path parameter",
            "enum": [],
        })
    return request


def parse_api_docs_entries(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    entries: dict[tuple[str, str], dict[str, Any]] = {}
    for match in DOC_JSON_BLOCK_RE.finditer(text):
        method = match.group(1).upper()
        ep_path = match.group(2).strip()
        payload = match.group(3)
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            entries[(method, ep_path)] = parsed
    return entries


def parse_enum_values(text: str | None) -> list[str]:
    if not text:
        return []
    match = ENUM_RE.search(text)
    if not match:
        return []
    raw = match.group(1).strip().rstrip(".")
    parts = re.split(r"[|,/]", raw)
    values = []
    for part in parts:
        value = part.strip().strip("[](){}")
        if value:
            values.append(value)
    return values


def classify_query_controls(entry: dict[str, Any]) -> dict[str, Any]:
    """Infer filter/search/sort/pagination expectations from an API doc entry."""
    request = entry.get("request") if isinstance(entry, dict) else {}
    query = request.get("query") if isinstance(request, dict) else {}
    query = query if isinstance(query, dict) else {}

    filters: dict[str, dict[str, Any]] = {}
    has_search = False
    has_sort = False
    has_pagination = False

    for key, meta in query.items():
        slug = str(key).strip()
        lower = slug.lower()
        meta = meta if isinstance(meta, dict) else {}
        enums = meta.get("enum") if isinstance(meta.get("enum"), list) else []
        if lower in STANDARD_SEARCH_PARAMS:
            has_search = True
            continue
        if lower in STANDARD_SORT_PARAMS:
            has_sort = True
            continue
        if lower in STANDARD_PAGINATION_PARAMS:
            has_pagination = True
            continue
        filters[slug] = {
            "enum": [str(v) for v in enums if str(v).strip()],
            "type": str(meta.get("type") or ""),
        }

    return {
        "filters": filters,
        "has_search": has_search,
        "has_sort": has_sort,
        "has_pagination": has_pagination,
    }
