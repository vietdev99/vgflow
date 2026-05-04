#!/usr/bin/env python3
"""
pre-executor-check.py — Deterministic context assembly for VG executor agents.

Replaces bash pseudocode in build.md step 8c. Orchestrator calls this ONCE per task
before spawning executor. Output = JSON with all context blocks ready to inject.

Usage:
  python pre-executor-check.py \
    --phase-dir .vg/phases/07.10-user-org-management-deep \
    --task-num 4 \
    --config .claude/vg.config.md \
    --plan-file PLAN.md

Output: stdout JSON
  {
    "status": "ready" | "missing_artifacts",
    "task_context": "...",
    "contract_context": "...",
    "goals_context": "...",
    "crud_surface_context": "...",
    "sibling_context": "...",
    "downstream_callers": "...",
    "design_context": "...",
    "wave_context": "...",
    "build_config": { "typecheck_cmd": "...", ... },
    "warnings": ["..."]
  }

If artifacts missing, script attempts to build them (runs find-siblings.py,
build-caller-graph.py). If still missing after attempt, returns status="missing_artifacts"
with specific guidance.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
from design_ref_resolver import (  # noqa: E402
    extract_design_ref_entries,
    resolve_design_assets,
)


def parse_config(config_path: Path) -> dict:
    """Parse vg.config.md YAML-like frontmatter into flat dict."""
    text = config_path.read_text(encoding="utf-8")
    # Strip BOM
    if text.startswith("\ufeff"):
        text = text[1:]

    config = {}
    # YAML-like parser for vg.config.md
    # Handles: top-level keys, nested sections (1 level), quoted values with special chars
    section_stack = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "---":
            continue

        # Detect indent level
        indent = len(line) - len(line.lstrip())

        # Top-level (no indent)
        if indent == 0:
            # Section header (key: with nothing after, or key: followed by newline)
            m = re.match(r"^([a-z_]+):\s*$", line)
            if m:
                section_stack = [m.group(1)]
                continue

            # Top-level key: value (may be quoted, may contain special chars)
            m = re.match(r'^([a-z_]+):\s*"(.+?)"\s*(?:#.*)?$', line)
            if not m:
                m = re.match(r"^([a-z_]+):\s*'(.+?)'\s*(?:#.*)?$", line)
            if not m:
                m = re.match(r"^([a-z_]+):\s*(.+?)\s*(?:#.*)?$", line)
            if m:
                config[m.group(1)] = m.group(2).strip()
                section_stack = []
                continue

        # Nested (indented)
        elif indent > 0 and section_stack:
            # Detect sub-section
            m = re.match(r"^\s+([a-z_][a-z0-9_]*):\s*$", line)
            if m:
                if len(section_stack) == 1:
                    section_stack = [section_stack[0], m.group(1)]
                else:
                    section_stack = [section_stack[0], m.group(1)]
                continue

            # Nested key: value
            m = re.match(r'^\s+([a-z_][a-z0-9_]*):\s*"(.+?)"\s*(?:#.*)?$', line)
            if not m:
                m = re.match(r"^\s+([a-z_][a-z0-9_]*):\s*'(.+?)'\s*(?:#.*)?$", line)
            if not m:
                m = re.match(r"^\s+([a-z_][a-z0-9_]*):\s*(.+?)\s*(?:#.*)?$", line)
            if m:
                key = ".".join(section_stack + [m.group(1)])
                config[key] = m.group(2).strip()
                continue

    return config


def extract_task_section_v2(phase_dir: Path, task_num, plan_file: str = None) -> dict:
    """Phase 16 D-02 — return structured task block.

    Returns dict:
      {
        "body": str,          # markdown body without frontmatter or XML wrapper
        "format": "xml" | "heading",
        "frontmatter": dict | None,  # parsed YAML frontmatter (XML format only)
        "raw_block": str,     # entire block as found in PLAN.md (incl wrapper)
      }

    Detection priority:
      1. Scan PLAN files for `<task id="N">...</task>` matching task_num → xml
      2. Else fallback to existing heading regex `## Task N:` → heading

    Backward compat: extract_task_section() (the original str-returning fn)
    stays untouched. Callers wanting the rich shape opt in to v2.
    """
    task_id_str = str(task_num)

    # Format 1: XML wrapper
    plan_files = sorted(phase_dir.glob(plan_file or "*PLAN*.md"))
    for pf in plan_files:
        text = pf.read_text(encoding="utf-8", errors="ignore")
        # Match <task id="N">...</task> (non-greedy)
        xml_re = re.compile(
            rf'<task\s+id\s*=\s*["\']?{re.escape(task_id_str)}["\']?\s*>(.*?)</task>',
            re.DOTALL | re.IGNORECASE,
        )
        m = xml_re.search(text)
        if m:
            inner = m.group(1)
            # Detect frontmatter --- ... --- block at top of inner
            frontmatter = None
            body = inner.strip()
            fm_re = re.compile(r"^\s*---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
            fm_m = fm_re.match(body)
            if fm_m:
                fm_text = fm_m.group(1)
                frontmatter = _parse_yaml_frontmatter(fm_text)
                body = fm_m.group(2).strip()
            return {
                "body": body,
                "format": "xml",
                "frontmatter": frontmatter,
                "raw_block": m.group(0),
            }

    # Format 2: heading-based (legacy) — delegate to v1 then wrap.
    body_str = extract_task_section(phase_dir, task_num if isinstance(task_num, int) else int(task_id_str), plan_file)
    return {
        "body": body_str,
        "format": "heading",
        "frontmatter": None,
        "raw_block": body_str,
    }


def _parse_yaml_frontmatter(text: str) -> dict:
    """Lightweight YAML reader — same shape as build-uat-narrative.py /
    interactive-helpers.template.ts inline parsers.

    Supports the subset we need for D-02 frontmatter:
      - scalar `key: value`
      - list `key:\n  - item1\n  - item2`
      - inline list `key: [a, b, c]`
      - integer + string + boolean coercion
    """
    out: dict = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        m = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.*)$', stripped)
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        if val == "":
            # Possibly a multi-line list under this key
            items = []
            j = i + 1
            while j < len(lines):
                child = lines[j]
                if child.strip() == "" or child.strip().startswith("#"):
                    j += 1
                    continue
                m2 = re.match(r'^\s*-\s*(.*)$', child)
                if not m2:
                    break
                item = m2.group(1).strip()
                # Strip surrounding quotes
                if (item.startswith('"') and item.endswith('"')) or \
                   (item.startswith("'") and item.endswith("'")):
                    item = item[1:-1]
                items.append(item)
                j += 1
            out[key] = items
            i = j
            continue
        # Inline list
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            if not inner:
                out[key] = []
            else:
                out[key] = [
                    s.strip().strip('"').strip("'") for s in inner.split(",")
                ]
            i += 1
            continue
        # Scalar value (coerce common types)
        if val.lower() == "true":
            out[key] = True
        elif val.lower() == "false":
            out[key] = False
        elif re.match(r'^-?\d+$', val):
            out[key] = int(val)
        else:
            # Strip surrounding quotes
            if (val.startswith('"') and val.endswith('"')) or \
               (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            out[key] = val
        i += 1
    return out


def extract_all_tasks(plan_path: Path) -> list[dict]:
    """Phase 16 D-02 — enumerate ALL tasks in a PLAN file as v2 dicts.

    Used by vg_completeness_check.py Check E (T-3.1) for body-cap iteration
    + verify-task-schema.py (T-2.2) for format classification.
    """
    if not plan_path.exists():
        return []
    text = plan_path.read_text(encoding="utf-8", errors="ignore")
    out = []

    # Pass 1: XML-format tasks
    xml_re = re.compile(
        r'<task\s+id\s*=\s*["\']?(\d+|[A-Za-z][A-Za-z0-9_-]*)["\']?\s*>(.*?)</task>',
        re.DOTALL | re.IGNORECASE,
    )
    xml_ids = set()
    for m in xml_re.finditer(text):
        tid = m.group(1)
        xml_ids.add(tid)
        inner = m.group(2)
        frontmatter = None
        body = inner.strip()
        fm_m = re.match(r"^\s*---\s*\n(.*?)\n---\s*\n(.*)$", body, re.DOTALL)
        if fm_m:
            frontmatter = _parse_yaml_frontmatter(fm_m.group(1))
            body = fm_m.group(2).strip()
        out.append({
            "id": tid,
            "body": body,
            "format": "xml",
            "frontmatter": frontmatter,
            "raw_block": m.group(0),
        })

    # Pass 2: heading-format tasks (skip ids already found in XML)
    heading_re = re.compile(
        r'^#{2,3}\s+Task\s+(0?\d+)\b[:\s\-—]([^\n]*)$',
        re.IGNORECASE | re.MULTILINE,
    )
    lines = text.splitlines()
    headings = []
    for i, line in enumerate(lines):
        m = heading_re.match(line)
        if m:
            headings.append((i, m.group(1).lstrip("0") or "0"))
    for idx, (line_no, tid) in enumerate(headings):
        if tid in xml_ids:
            continue
        end_line = headings[idx + 1][0] if idx + 1 < len(headings) else len(lines)
        body = "\n".join(lines[line_no:end_line]).strip()
        out.append({
            "id": tid,
            "body": body,
            "format": "heading",
            "frontmatter": None,
            "raw_block": body,
        })

    return out


def extract_task_section(phase_dir: Path, task_num: int, plan_file: str = None) -> str:
    """Extract task N section from PLAN*.md.

    Supports two formats:
    1. Multi-task file: ## Task 4: ... sections in single PLAN.md
    2. Numbered plan files: 07.10-04-PLAN.md (one plan = one file)
    """
    # Format 2: numbered plan files (e.g., 07.10-04-PLAN.md)
    num_padded = f"{task_num:02d}"
    for pf in sorted(phase_dir.glob(f"*-{num_padded}-PLAN*.md")):
        text = pf.read_text(encoding="utf-8")
        # Cap at 2000 lines to avoid bloating executor context
        lines = text.splitlines()
        return "\n".join(lines[:2000])

    # Also try without zero-pad (e.g., 07.10-4-PLAN.md)
    for pf in sorted(phase_dir.glob(f"*-{task_num}-PLAN*.md")):
        text = pf.read_text(encoding="utf-8")
        lines = text.splitlines()
        return "\n".join(lines[:2000])

    # Format 1: task sections within single PLAN.md
    plan_files = sorted(phase_dir.glob(plan_file or "*PLAN*.md"))
    if not plan_files:
        return "PLAN.md not found"

    for pf in plan_files:
        text = pf.read_text(encoding="utf-8")
        pattern = rf"^#{{2,3}}\s+Task\s+0?{task_num}\b[:\s\-—]"
        lines = text.splitlines()
        start = None
        for i, line in enumerate(lines):
            if re.match(pattern, line, re.IGNORECASE):
                start = i
            elif start is not None and re.match(r"^#{2,3}\s+(?:Task\s+\d+|Wave\s+\d+)", line, re.IGNORECASE):
                return "\n".join(lines[start:i])

        if start is not None:
            return "\n".join(lines[start:])

    return f"Task {task_num} not found in PLAN files"


def extract_contract_section(phase_dir: Path, task_text: str) -> str:
    """Extract relevant contract sections for this task's endpoints."""
    contracts_file = phase_dir / "API-CONTRACTS.md"
    if not contracts_file.exists():
        return "API-CONTRACTS.md not found"

    # Find endpoints from multiple sources in task text:
    # 1. VG tag: <edits-endpoint>POST /api/v1/conversion-goals</edits-endpoint>
    # 2. Inline: POST /api/v1/conversion-goals
    # 3. <contract-ref> tag
    endpoints = []

    # Parse <edits-endpoint> tags (may contain comma-separated list)
    edits_tags = re.findall(r"<edits-endpoint>([^<]+)</edits-endpoint>", task_text)
    for tag in edits_tags:
        for ep in tag.split(","):
            ep = ep.strip()
            m = re.match(r"(GET|POST|PUT|DELETE|PATCH)\s+(.+)", ep)
            if m:
                endpoints.append((m.group(1), m.group(2).strip()))

    # Also grep inline endpoints
    inline = re.findall(r"(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)", task_text)
    for method, path in inline:
        if not any(path == ep[1] for ep in endpoints):
            endpoints.append((method, path))

    if not endpoints:
        return "No endpoints in this task"

    text = contracts_file.read_text(encoding="utf-8")
    sections = []
    for method, path in endpoints:
        # P17 polish bug fix: prefer FULL-PATH match first to disambiguate
        # /api/v1/sites vs /api/v2/sites (last-segment-only match would
        # collide and pick the first one — wrong version contract for
        # the executor). Fall back to last-segment match only when full
        # path doesn't appear (legacy API-CONTRACTS files with shortened
        # headers like "### POST /sites").
        full_path_pattern = rf"###\s+(?:\d+\.\d+\s+)?{method}\s+{re.escape(path)}\b"
        match = re.search(full_path_pattern, text)
        if not match:
            # Fallback 1: last path segment + numbering tolerance
            last_segment = path.rstrip("/").split("/")[-1]
            if last_segment:
                fallback_pattern = (
                    rf"###\s+(?:\d+\.\d+\s+)?{method}\s+\S*{re.escape(last_segment)}\b"
                )
                match = re.search(fallback_pattern, text)
        if not match:
            # Fallback 2: relaxed METHOD + path anywhere on the heading line
            pattern2 = rf"###.*{method}\s+.*{re.escape(path)}"
            match = re.search(pattern2, text)
        if match:
            rest = text[match.start():]
            next_h3 = re.search(r"\n###\s+", rest[10:])
            if next_h3:
                sections.append(rest[: next_h3.start() + 10])
            else:
                # P17 polish: surface long-tail contract via comment instead
                # of silent 3000-char truncate. 3000 chars ≈ 60-100 lines —
                # rare for one endpoint but documented when it happens.
                if len(rest) > 3000:
                    sections.append(
                        rest[:3000]
                        + f"\n\n<!-- vg/pre-executor-check: contract section truncated from {len(rest)} to 3000 chars; if executor needs more, split endpoint into smaller blocks. -->\n"
                    )
                else:
                    sections.append(rest)

    return "\n\n".join(sections) if sections else f"No matching contract sections for {endpoints}"


def extract_goals_context(phase_dir: Path, task_text: str) -> str:
    """Extract goal sections for this task's <goals-covered>."""
    goals_file = phase_dir / "TEST-GOALS.md"
    if not goals_file.exists():
        return "TEST-GOALS.md not found"

    # Find goals from task
    goals_match = re.search(r"<goals-covered>\s*\[?([^\]<]+)", task_text)
    if not goals_match:
        return "no-goal-impact"

    goal_ids = re.findall(r"G-\d+", goals_match.group(1))
    if not goal_ids:
        return "no-goal-impact"

    text = goals_file.read_text(encoding="utf-8")
    sections = []
    for gid in goal_ids:
        pattern = rf"^##\s+Goal\s+{re.escape(gid)}"
        lines = text.splitlines()
        start = None
        for i, line in enumerate(lines):
            if re.match(pattern, line):
                start = i
            elif start is not None and re.match(r"^##\s+Goal\s+G-\d+", line):
                sections.append("\n".join(lines[start:i]))
                start = None
                break
        if start is not None:
            # P17 polish bug fix: previous code truncated to 30 lines when no
            # next "## Goal G-XX" heading found (i.e., the LAST goal in
            # TEST-GOALS.md). Phase 15 D-16 goals routinely declare
            # interactive_controls + persistence check + multiple criteria,
            # easily 50-100+ lines. Truncate caused executor to receive an
            # incomplete goal context for any task touching the last goal.
            # Now: take everything from start to EOF (file is already capped
            # by R4 budget downstream; per-goal cap is not the right place).
            sections.append("\n".join(lines[start:]))

    return "\n\n".join(sections) if sections else f"Goals {goal_ids} not found"


def extract_crud_surface_context(
    phase_dir: Path,
    task_text: str,
    goals_context: str,
    contract_context: str,
) -> str:
    """Extract the relevant CRUD-SURFACES.md resource contract for this task.

    The file is resource-level, not task-level. Keep executor context tight by
    returning only resources whose name appears in task/goal/contract text. If
    there is exactly one resource, include it as the safe default.
    """
    path = phase_dir / "CRUD-SURFACES.md"
    if not path.exists():
        return "CRUD-SURFACES.md not found"

    raw = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"```(?:json|crud-surface)\s*(\{.*?\})\s*```", raw, re.DOTALL)
    body = m.group(1) if m else raw.strip()
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        return f"CRUD-SURFACES.md invalid JSON: {exc.msg} at line {exc.lineno}"

    resources = data.get("resources")
    if not isinstance(resources, list):
        return "CRUD-SURFACES.md has no resources[] array"
    if not resources:
        reason = data.get("no_crud_reason") or "resources[] empty"
        return f"NONE - {reason}"

    combined = f"{task_text}\n{goals_context}\n{contract_context}".lower()
    matched: list[dict] = []
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        name = str(resource.get("name") or "").strip()
        if name and name.lower() in combined:
            matched.append(resource)

    if not matched and len(resources) == 1 and isinstance(resources[0], dict):
        matched = [resources[0]]

    if not matched:
        names = ", ".join(
            str(r.get("name")) for r in resources if isinstance(r, dict) and r.get("name")
        )
        return f"CRUD-SURFACES.md present; no resource matched this task. Resources: {names or 'none'}"

    compact = {
        "version": data.get("version", "1"),
        "source": "CRUD-SURFACES.md",
        "resources": matched,
    }
    return json.dumps(compact, indent=2, ensure_ascii=False)


def _extract_tag_values(text: str, tag: str) -> list[str]:
    return [
        item.strip()
        for item in re.findall(rf"<{re.escape(tag)}>\s*([^<]+?)\s*</{re.escape(tag)}>", text)
        if item.strip()
    ]


def _extract_context_refs(task_text: str) -> list[str]:
    refs: list[str] = []
    for raw in _extract_tag_values(task_text, "context-refs"):
        refs.extend(r.strip() for r in re.split(r"[,\s]+", raw) if r.strip())
    return sorted(set(refs))


def _extract_goal_ids(task_text: str, goals_context: str) -> list[str]:
    raw = "\n".join(_extract_tag_values(task_text, "goals-covered"))
    if not raw:
        raw = goals_context
    return sorted(set(re.findall(r"\bG-\d+\b", raw)))


def _extract_endpoints(*texts: str) -> list[str]:
    endpoints: list[str] = []
    for text in texts:
        for method, path in re.findall(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_./:{}?=&%-]+)", text):
            endpoints.append(f"{method} {path.rstrip('.,;')}")
    return sorted(set(endpoints))


def _extract_file_paths(task_text: str) -> list[str]:
    paths = _extract_tag_values(task_text, "file-path")
    paths.extend(
        re.findall(
            r"\b(?:apps|packages|src|lib|server|client)/[A-Za-z0-9_./@{}-]+\.(?:ts|tsx|js|jsx|py|go|rs|vue|svelte)",
            task_text,
        )
    )
    return sorted(set(p.strip() for p in paths if p.strip()))


def _resource_from_endpoint(endpoint: str) -> str | None:
    """Extract resource name from `POST /api/sites` → `sites`. Returns None if path lacks /api/<resource>."""
    parts = endpoint.split(maxsplit=1)
    if len(parts) < 2:
        return None
    path = parts[1]
    m = re.search(r"/api/([a-z][a-z0-9-]*)", path)
    return m.group(1) if m else None


def build_per_task_slices(
    phase_dir: Path,
    task_num: int,
    endpoints: list[str],
    goals: list[str],
    cache_dir: Path,
) -> dict:
    """Task 37 — orchestrator pre-resolves per-task artifact slices.

    Returns a dict with 3 keys:
      - crud_surfaces_slice_path: str | None — concatenated per-resource slices
      - lens_walk_slice_path:     str | None — concatenated per-goal lens-walk slices
      - rcrurd_invariants_paths:  list[str] — list of per-goal yaml paths

    Stale phases (missing CRUD-SURFACES or LENS-WALK directory) get None
    + a warning logged to stderr — NOT an exception (Codex finding #36
    graceful-degradation).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)

    # CRUD-SURFACES: union of resources extracted from endpoints
    cs_dir = phase_dir / "CRUD-SURFACES"
    crud_path: str | None = None
    if cs_dir.exists() and endpoints:
        resources = sorted({r for r in (_resource_from_endpoint(e) for e in endpoints) if r})
        chunks = []
        for r in resources:
            f = cs_dir / f"{r}.md"
            if f.exists():
                chunks.append(f"# Resource: {r}\n" + f.read_text(encoding="utf-8"))
        if chunks:
            resource_tag = "-".join(resources) if len(resources) <= 3 else f"{len(resources)}resources"
            slice_file = cache_dir / f"task-{task_num:02d}.crud-surfaces.{resource_tag}.md"
            slice_file.write_text("\n\n".join(chunks), encoding="utf-8")
            crud_path = str(slice_file.relative_to(phase_dir.parent.parent.parent)) \
                if str(slice_file).startswith(str(phase_dir.parent.parent.parent)) else str(slice_file)
    elif endpoints and not cs_dir.exists():
        sys.stderr.write(
            f"WARN: CRUD-SURFACES/ missing for task-{task_num} — context degraded.\n"
        )

    # LENS-WALK: union of per-goal slices
    lw_dir = phase_dir / "LENS-WALK"
    lw_path: str | None = None
    if lw_dir.exists() and goals:
        chunks = []
        for g in goals:
            f = lw_dir / f"{g}.md"
            if f.exists():
                chunks.append(f.read_text(encoding="utf-8"))
        if chunks:
            goal_tag = "-".join(goals) if len(goals) <= 3 else f"{len(goals)}goals"
            slice_file = cache_dir / f"task-{task_num:02d}.lens-walk.{goal_tag}.md"
            slice_file.write_text("\n\n".join(chunks), encoding="utf-8")
            lw_path = str(slice_file)
    elif goals and not lw_dir.exists():
        sys.stderr.write(
            f"WARN: LENS-WALK/ missing for task-{task_num} — context degraded.\n"
        )

    # RCRURD-INVARIANTS: per-goal yaml paths (R7 Task 2 — G7 source unification)
    # Modern source (v2.49+): inline ```yaml-rcrurd``` fences inside TEST-GOALS/G-NN.md
    # Legacy fallback: ${PHASE_DIR}/RCRURD-INVARIANTS/G-NN.yaml dir
    #
    # Extract raw fence text (no parse/reserialize — preserve verbatim author intent).
    # Schema validation is downstream's job (executor + review). pre-executor-check
    # only locates the source.
    rcrurd_paths: list[str] = []
    tg_dir = phase_dir / "TEST-GOALS"
    ri_dir = phase_dir / "RCRURD-INVARIANTS"
    extracted_dir = cache_dir / "rcrurd-extracted"
    fence_re = re.compile(r"```yaml-rcrurd\s*\n(.+?)\n```", re.DOTALL)

    for g in goals:
        # Try inline fence (modern v2.49+)
        if tg_dir.exists():
            goal_md = tg_dir / f"{g}.md"
            if goal_md.exists():
                try:
                    body = goal_md.read_text(encoding="utf-8")
                except OSError:
                    body = ""
                m = fence_re.search(body)
                if m:
                    extracted_dir.mkdir(parents=True, exist_ok=True)
                    out_file = extracted_dir / f"{g}.yaml"
                    out_file.write_text(m.group(1) + "\n", encoding="utf-8")
                    rcrurd_paths.append(str(out_file))
                    continue
        # Legacy fallback (pre-v2.49 phases)
        if ri_dir.exists():
            f = ri_dir / f"{g}.yaml"
            if f.exists():
                rcrurd_paths.append(str(f))

    return {
        "crud_surfaces_slice_path": crud_path,
        "lens_walk_slice_path": lw_path,
        "rcrurd_invariants_paths": rcrurd_paths,
    }


# Task 41 — actor + workflow + write_phase tag-extraction helpers (M1)
_ACTOR_ROLE_RE = re.compile(r"<actor>\s*([\w-]+)\s*</actor>")
_WORKFLOW_RE = re.compile(r"<workflow>\s*(WF-\d{1,3})\s*</workflow>")
_WORKFLOW_STEP_RE = re.compile(r"<workflow-step>\s*(\d{1,3})\s*</workflow-step>")
_WRITE_PHASE_RE = re.compile(r"<write-phase>\s*(create|update|delete)\s*</write-phase>")


def extract_actor_role(task_body: str) -> str | None:
    """Parse `<actor>...</actor>` from a PLAN task body. Returns None if absent."""
    m = _ACTOR_ROLE_RE.search(task_body)
    return m.group(1) if m else None


def extract_workflow_id(task_body: str) -> str | None:
    """Parse `<workflow>WF-NN</workflow>` from a PLAN task body. Returns None if absent."""
    m = _WORKFLOW_RE.search(task_body)
    return m.group(1) if m else None


def extract_workflow_step(task_body: str) -> int | None:
    """Parse `<workflow-step>N</workflow-step>` → int. Returns None if absent."""
    m = _WORKFLOW_STEP_RE.search(task_body)
    return int(m.group(1)) if m else None


def extract_write_phase(task_body: str) -> str | None:
    """Parse `<write-phase>create|update|delete</write-phase>`. Other values return None."""
    m = _WRITE_PHASE_RE.search(task_body)
    return m.group(1) if m else None


def _context_status(value: str, missing_markers: tuple[str, ...] = ("not found",)) -> str:
    lowered = (value or "").lower()
    if not value.strip():
        return "empty"
    if any(marker in lowered for marker in missing_markers):
        return "missing"
    if lowered.startswith("none"):
        return "none"
    return "present"


def build_task_context_capsule(
    phase_dir: Path,
    task_num: int,
    task_context: str,
    contract_context: str,
    goals_context: str,
    crud_surface_context: str,
    sibling_context: str,
    downstream_callers: str,
    design_context: str,
    build_config: dict,
) -> dict:
    """Build the compact, fail-closed context contract for one executor task."""
    source_artifacts = {
        "plan": any(phase_dir.glob("*PLAN*.md")),
        "context": (phase_dir / "CONTEXT.md").exists(),
        "api_contracts": (phase_dir / "API-CONTRACTS.md").exists(),
        "test_goals": (phase_dir / "TEST-GOALS.md").exists(),
        "crud_surfaces": (phase_dir / "CRUD-SURFACES.md").exists(),
        "ui_spec": (phase_dir / "UI-SPEC.md").exists(),
        "callers": (phase_dir / ".callers.json").exists(),
        "wave_context_dir": (phase_dir / ".wave-context").exists(),
    }

    endpoints = _extract_endpoints(task_context, contract_context)
    mutation_methods = {"POST", "PUT", "PATCH", "DELETE"}
    mutates_data = any(ep.split(" ", 1)[0] in mutation_methods for ep in endpoints)
    has_ui_signal = bool(
        re.search(r"\.(tsx|jsx|vue|svelte)\b|<design-ref>|list|table|form|modal", task_context, re.I)
    )

    # Task 37 — pre-resolve per-task slices for build envelope
    slices = build_per_task_slices(
        phase_dir=phase_dir,
        task_num=task_num,
        endpoints=endpoints,
        goals=_extract_goal_ids(task_context, goals_context),
        cache_dir=phase_dir.parent.parent.parent / ".task-capsules",
    )

    # Task 41 (Bug I, M1) — actor + workflow + write_phase awareness
    actor_role = extract_actor_role(task_context)
    workflow_id = extract_workflow_id(task_context)
    workflow_step = extract_workflow_step(task_context)
    write_phase = extract_write_phase(task_context)
    must_match_workflow_state = workflow_id is not None

    capsule = {
        "capsule_version": "2",          # Task 41 schema bump: "1" → "2"
        "phase": build_config.get("phase"),
        "task_num": task_num,
        "task_title": next((line.strip("# ").strip() for line in task_context.splitlines() if line.strip()), ""),
        "source_artifacts": source_artifacts,
        "context_refs": _extract_context_refs(task_context),
        "goals": _extract_goal_ids(task_context, goals_context),
        "endpoints": endpoints,
        "file_paths": _extract_file_paths(task_context),
        # Task 41 — actor + workflow + write_phase awareness (M1)
        "actor_role": actor_role,
        "workflow_id": workflow_id,
        "workflow_step": workflow_step,
        "write_phase": write_phase,
        "required_context": {
            "task_context": _context_status(task_context),
            "contract_context": _context_status(
                contract_context,
                missing_markers=("api-contracts.md not found", "no matching contract sections"),
            ),
            "goals_context": _context_status(
                goals_context,
                missing_markers=("test-goals.md not found", "goals ", "not found"),
            ),
            "crud_surface_context": _context_status(
                crud_surface_context,
                missing_markers=("crud-surfaces.md not found", "invalid json", "no resources[]"),
            ),
            "sibling_context": _context_status(sibling_context),
            "downstream_callers": _context_status(downstream_callers),
            "design_context": _context_status(design_context),
        },
        "execution_contract": {
            "mutates_data": mutates_data,
            "requires_persistence_check": mutates_data and bool(_extract_goal_ids(task_context, goals_context)),
            "has_ui_surface": has_ui_signal,
            "must_follow_crud_surface": source_artifacts["crud_surfaces"] and crud_surface_context.strip().lower() != "none",
            "must_follow_api_contract": bool(endpoints),
            "must_preserve_context_refs": bool(_extract_context_refs(task_context)),
            # Task 41 additions
            "must_match_workflow_state": must_match_workflow_state,
            "actor_role_hint": actor_role or "",
        },
        "anti_lazy_read_rules": [
            "Read this capsule first; it is the minimum task contract.",
            "Do not implement outside file_paths unless the task body explicitly requires it.",
            "Do not ignore goals/endpoints/crud_surface_context when present.",
            "If a required_context value is missing, stop and report the missing artifact instead of guessing.",
            # Task 41 — 2 new workflow-aware rules
            "If workflow_id is set, read WORKFLOW-SPECS/<workflow_id>.md slice and verify your code matches the state_after declaration for your step_id.",
            "Do NOT invent state names — use exact strings from state_machine.states[].",
        ],
        # Task 37 (Bug E) — per-task artifact slice paths for build envelope.
        # Non-required: null/empty when phase predates Task 37 or task has no endpoints/goals.
        "crud_surfaces_slice_path": slices["crud_surfaces_slice_path"],
        "lens_walk_slice_path": slices["lens_walk_slice_path"],
        "rcrurd_invariants_paths": slices["rcrurd_invariants_paths"],
    }
    return capsule


def ensure_siblings(phase_dir: Path, task_num: int, config: dict, repo_root: Path) -> str:
    """Ensure sibling context exists, build if missing."""
    wave_ctx = phase_dir / ".wave-context"
    sibling_file = wave_ctx / f"siblings-task-{task_num}.json"

    if sibling_file.exists():
        try:
            data = json.loads(sibling_file.read_text(encoding="utf-8"))
            siblings = data.get("siblings", [])
            if siblings:
                lines = []
                for s in siblings[:3]:
                    # Handle both formats: {file, exports} and {module_dir, entry_file, exports}
                    file_path = s.get("file", s.get("entry_file", s.get("module_dir", "?")))
                    exports = s.get("exports", [])
                    if isinstance(exports, list) and exports:
                        if isinstance(exports[0], dict):
                            export_names = [e.get("name", "") for e in exports[:5]]
                        else:
                            export_names = exports[:5]
                    else:
                        export_names = []
                    lines.append(f"- {file_path}: {', '.join(export_names)}")
                return "\n".join(lines)
        except (json.JSONDecodeError, KeyError):
            pass

    # Try to build
    script = repo_root / ".claude" / "scripts" / "find-siblings.py"
    if not script.exists():
        return "NONE — find-siblings.py not found"

    # Extract task file-path from task text
    task_text = extract_task_section(phase_dir, task_num)
    # Try multiple file-path formats — prefer source code paths over infra
    file_match = re.search(r"<file-path>([^<]+)</file-path>", task_text)
    if not file_match:
        # Grep for apps/ or packages/ source paths first (most reliable)
        file_match = re.search(r"(apps/\S+\.(?:ts|tsx|js|jsx|rs))", task_text)
    if not file_match:
        file_match = re.search(r"(packages/\S+\.(?:ts|tsx|js|jsx))", task_text)
    if not file_match:
        # YAML path: field
        file_match = re.search(r'\bpath:\s*"([^"]+)"', task_text)
    if not file_match:
        file_match = re.search(r"<files>([^<]+)</files>", task_text)
    if not file_match:
        file_match = re.search(r"\*\*(?:File|Scope|Target):\*\*\s*`?([^\s`\n]+)", task_text)

    if not file_match:
        return "NONE — no file-path in task"

    task_file = file_match.group(1).strip()
    wave_ctx.mkdir(parents=True, exist_ok=True)

    graphify_flag = ""
    graph_path = config.get("graphify.graph_path", "graphify-out/graph.json")
    full_graph = repo_root / graph_path
    if config.get("graphify.enabled", "false") == "true" and full_graph.exists():
        graphify_flag = f"--graphify-graph {full_graph}"

    cmd = [
        sys.executable, str(script),
        "--file", task_file,
        "--config", str(repo_root / ".claude" / "vg.config.md"),
        "--output", str(sibling_file),
    ]
    if graphify_flag:
        graph_path_val = graphify_flag.replace("--graphify-graph ", "")
        cmd.extend(["--graphify-graph", graph_path_val])

    try:
        subprocess.run(cmd, capture_output=True, timeout=30, cwd=str(repo_root))
        if sibling_file.exists():
            data = json.loads(sibling_file.read_text(encoding="utf-8"))
            siblings = data.get("siblings", [])
            if siblings:
                lines = []
                for s in siblings[:3]:
                    fp = s.get("entry_file", s.get("module_dir", s.get("file", "?")))
                    exps = s.get("exports", [])
                    if exps and isinstance(exps[0], dict):
                        names = [e.get("name", "") for e in exps[:5]]
                    elif exps:
                        names = [str(e) for e in exps[:5]]
                    else:
                        names = []
                    lines.append(f"- {fp}: {', '.join(names)}")
                return "\n".join(lines)
    except subprocess.TimeoutExpired:
        return "NONE — find-siblings.py timed out"
    except Exception as e:
        return f"NONE — find-siblings.py failed: {type(e).__name__}: {e}"

    return "NONE — no peer modules at this directory level"


def ensure_callers(phase_dir: Path, task_num: int, config: dict, repo_root: Path) -> str:
    """Ensure caller graph exists, build if missing."""
    callers_file = phase_dir / ".callers.json"

    if not callers_file.exists():
        # Try to build
        script = repo_root / ".claude" / "scripts" / "build-caller-graph.py"
        if script.exists():
            graph_flag = ""
            graph_path = config.get("graphify.graph_path", "graphify-out/graph.json")
            full_graph = repo_root / graph_path
            if config.get("graphify.enabled", "false") == "true" and full_graph.exists():
                graph_flag = f"--graphify-graph {full_graph}"

            cmd = [
                sys.executable, str(script),
                "--phase-dir", str(phase_dir),
                "--config", str(repo_root / ".claude" / "vg.config.md"),
                "--output", str(callers_file),
            ]
            if graph_flag:
                graph_path_val = graph_flag.replace("--graphify-graph ", "")
                cmd.extend(["--graphify-graph", graph_path_val])
            try:
                subprocess.run(cmd, capture_output=True, timeout=60, cwd=str(repo_root))
            except Exception:
                pass

    if not callers_file.exists():
        return "NONE — caller graph not built"

    try:
        data = json.loads(callers_file.read_text(encoding="utf-8"))
        callers = data.get("affected_callers", [])

        if not callers:
            return "NONE — no downstream callers detected"

        # Show first 10 callers
        relevant = []
        for item in callers[:10]:
            file_path = item.get("file", item.get("caller_file", "?"))
            symbol = item.get("symbol", item.get("exports_at_risk", "?"))
            line = item.get("line", "?")
            relevant.append(f"- {file_path}:{line} uses {symbol}")

        return "\n".join(relevant) if relevant else "NONE — no downstream callers"

    except (json.JSONDecodeError, KeyError, TypeError):
        return "NONE — callers.json parse error"


def main():
    parser = argparse.ArgumentParser(description="Pre-executor context check")
    parser.add_argument("--phase-dir", required=True)
    parser.add_argument("--task-num", type=int, required=True)
    parser.add_argument("--config", default=".claude/vg.config.md")
    parser.add_argument("--plan-file", default=None, help="Specific plan file name")
    parser.add_argument("--repo-root", default=None)
    parser.add_argument(
        "--capsule-out",
        default=None,
        help="Write the per-task context capsule JSON to this path",
    )
    args = parser.parse_args()

    phase_dir = Path(args.phase_dir)
    config_path = Path(args.config)
    repo_root = Path(args.repo_root) if args.repo_root else Path.cwd()

    if not phase_dir.exists():
        print(json.dumps({"status": "error", "message": f"Phase dir not found: {phase_dir}"}))
        sys.exit(1)

    if not config_path.exists():
        print(json.dumps({"status": "error", "message": f"Config not found: {config_path}"}))
        sys.exit(1)

    # Parse config
    config = parse_config(config_path)
    warnings = []

    # Phase 16 hot-fix (v2.11.1) — use extract_task_section_v2 as the SINGLE
    # source for both task_context and task_meta. Cross-AI consensus BLOCKer 4
    # (Codex GPT-5.5 verified): v1 only matches heading format, so XML PLAN
    # tasks returned the "Task N not found in PLAN files" sentinel which then
    # got passed to the executor verbatim. Meanwhile v2 was called separately
    # just for the meta hash, so source_format reported "xml" while the actual
    # executor input was the not-found string. Two sources of truth → drift.
    v2_result = extract_task_section_v2(phase_dir, args.task_num, args.plan_file)
    task_context = v2_result["body"]
    if not task_context or "not found" in task_context.lower():
        warnings.append(f"Task {args.task_num}: {task_context or 'extraction returned empty body'}")

    # Phase 16 D-01 task_meta — reuse v2_result; no second extraction.
    # Best-effort: if scripts/lib/task_hasher.py is missing (older install),
    # skip silently rather than crash.
    task_meta = None
    try:
        sys.path.insert(0, str(Path(__file__).parent / "lib"))
        from task_hasher import stable_meta as _stable_meta  # noqa: E402
        plan_files = sorted(phase_dir.glob(args.plan_file or "*PLAN*.md"))
        source_path = plan_files[0].name if plan_files else "PLAN.md"
        task_meta = _stable_meta(
            task_id=args.task_num,
            phase=str(phase_dir.name).split("-")[0].lstrip("0") or phase_dir.name,
            wave="unknown",  # build.md step 8c overrides with actual wave-${N}
            source_path=source_path,
            source_format=v2_result["format"],
            body_text=v2_result["body"],
        )
    except Exception as e:
        warnings.append(f"P16 D-01 task_meta: {type(e).__name__}: {e}")

    # Extract contract section
    contract_context = extract_contract_section(phase_dir, task_context)

    # Extract goals
    goals_context = extract_goals_context(phase_dir, task_context)

    # Extract resource-level CRUD contract
    crud_surface_context = extract_crud_surface_context(
        phase_dir, task_context, goals_context, contract_context
    )

    interface_standards_path = phase_dir / "INTERFACE-STANDARDS.md"
    if interface_standards_path.exists():
        interface_standards_context = interface_standards_path.read_text(
            encoding="utf-8", errors="replace",
        )[:12000]
    else:
        interface_standards_context = "INTERFACE-STANDARDS.md not found"

    # Ensure siblings (builds if missing)
    sibling_context = ensure_siblings(phase_dir, args.task_num, config, repo_root)

    # Ensure callers (builds if missing)
    downstream_callers = ensure_callers(phase_dir, args.task_num, config, repo_root)

    # ─── L1 Design context (design pixel injection v1) ────────────────────
    # Resolve every <design-ref> in the task body, classify SLUG vs DESCRIPTIVE
    # (same heuristic as build.md step 4b), and emit absolute PNG paths so the
    # executor's Read tool can load the image visually. Hard-gate at build.md
    # checks design_image_required + verifies each path exists on disk.
    design_context = ""
    design_image_paths: list[str] = []
    design_image_required = False
    design_ref_entries: list[dict] = []
    parsed_design_refs = extract_design_ref_entries(task_context)
    if parsed_design_refs:
        slug_entries: list[dict] = []
        descriptive_entries: list[str] = []
        no_asset_entries: list[str] = []
        for ref in parsed_design_refs:
            if ref.kind == "slug":
                assets = resolve_design_assets(
                    ref.value,
                    repo_root=repo_root,
                    phase_dir=phase_dir,
                    config=config,
                )
                entry: dict = {
                    "slug": ref.value,
                    "screenshots": [str(p) for p in assets.screenshots],
                    "structural": str(assets.structural) if assets.structural else None,
                    "interactions": str(assets.interactions) if assets.interactions else None,
                    "tier": assets.tier,
                    "root": str(assets.root) if assets.root else None,
                }
                if not entry["screenshots"]:
                    missing = assets.missing_candidates[0] if assets.missing_candidates else (
                        phase_dir / "design" / "screenshots" / f"{ref.value}.default.png"
                    )
                    entry["screenshot_missing"] = str(missing)
                slug_entries.append(entry)
                design_image_required = True
                design_image_paths.extend(entry["screenshots"])
            elif ref.kind == "no_asset":
                no_asset_entries.append(ref.value)
            else:
                descriptive_entries.append(ref.value)

        design_ref_entries = (
            slug_entries
            + [{"no_asset": d} for d in no_asset_entries]
            + [{"descriptive": d} for d in descriptive_entries]
        )

        lines: list[str] = []
        lines.append("# Design ground truth — MANDATORY (L1)")
        lines.append("")
        if slug_entries:
            lines.append("## PNG screenshots — READ EACH PATH WITH THE Read TOOL BEFORE WRITING CODE")
            lines.append("")
            lines.append("Read tool returns image content visually. Slug name is NOT the design;")
            lines.append("the PNG IS the design. Layout/spacing/components in your code MUST match")
            lines.append("what these PNGs show. The post-build visual gate (L3) will reject drift.")
            lines.append("")
            for entry in slug_entries:
                lines.append(f"### {entry['slug']}")
                if entry["screenshots"]:
                    for sp in entry["screenshots"]:
                        lines.append(f"  Read: {sp}")
                else:
                    lines.append(f"  ⚠ MISSING ON DISK: {entry.get('screenshot_missing','?')}")
                if entry.get("structural"):
                    lines.append(f"  Structural ref: {entry['structural']}")
                if entry.get("interactions"):
                    lines.append(f"  Interactions: {entry['interactions']}")
                lines.append("")
            lines.append("## L2 forcing function — WRITE LAYOUT-FINGERPRINT.md before any UI code")
            lines.append("")
            lines.append(
                f"Path: .fingerprints/task-{args.task_num}.fingerprint.md"
            )
            lines.append("Required H2 sections (each ≥ 1 paragraph from what you SEE in the PNG):")
            lines.append("  ## Grid       — column count, container width, gutter sizes")
            lines.append("  ## Spacing    — vertical rhythm, padding, gap between sections")
            lines.append("  ## Hierarchy  — heading levels, primary/secondary CTAs, focal point")
            lines.append("  ## Breakpoints — what changes at mobile/tablet (or 'single viewport' if N/A)")
            lines.append(
                "Validator verify-layout-fingerprint.py runs at phase end; thin or "
                "missing sections BLOCK."
            )
            lines.append("")
        if descriptive_entries:
            lines.append("## Code-pattern hints (descriptive, not a PNG read target)")
            for d in descriptive_entries:
                lines.append(f"  - {d}")
            lines.append("")
        if no_asset_entries:
            lines.append("## Explicit no-asset design gaps (Form B)")
            for d in no_asset_entries:
                lines.append(f"  - {d}")
            lines.append("")
        design_context = "\n".join(lines).rstrip()

    # Build config (flat, no dotted paths)
    build_config = {
        "typecheck_cmd": config.get("build_gates.typecheck_cmd", ""),
        "build_cmd": config.get("build_gates.build_cmd", ""),
        "test_unit_cmd": config.get("build_gates.test_unit_cmd", ""),
        "generated_types_path": config.get("contract_format.generated_types_path", ""),
        "error_response_shape": config.get("contract_format.error_response_shape",
                                           "{ error: { code: string, message: string } }"),
        "phase": str(phase_dir.name).split("-")[0].lstrip("0") or phase_dir.name,
        "task_num": args.task_num,
    }

    task_context_capsule = build_task_context_capsule(
        phase_dir=phase_dir,
        task_num=args.task_num,
        task_context=task_context,
        contract_context=contract_context,
        goals_context=goals_context,
        crud_surface_context=crud_surface_context,
        sibling_context=sibling_context,
        downstream_callers=downstream_callers,
        design_context=design_context,
        build_config=build_config,
    )

    if args.capsule_out:
        capsule_path = Path(args.capsule_out)
        if not capsule_path.is_absolute():
            capsule_path = repo_root / capsule_path
        capsule_path.parent.mkdir(parents=True, exist_ok=True)
        capsule_path.write_text(
            json.dumps(task_context_capsule, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # Determine status
    status = "ready"
    if "not found" in task_context.lower():
        status = "missing_artifacts"
    if "not found" in contract_context.lower() and "No endpoints" not in contract_context:
        status = "missing_artifacts"

    # Phase 16 D-04 — R4 budget conditional caps. Read CONTEXT frontmatter
    # cross_ai_enriched flag; bump per-block + total caps when true. build.md
    # step 8c R4 enforcement reads `applied_caps` instead of literal BUDGETS.
    enriched = False
    ctx_path = phase_dir / "CONTEXT.md"
    if ctx_path.exists():
        ctx_text = ctx_path.read_text(encoding="utf-8", errors="ignore")
        fm_m = re.match(r"^---\s*\n(.*?)\n---\s*\n", ctx_text, re.DOTALL)
        if fm_m and re.search(r"^\s*cross_ai_enriched\s*:\s*(true|True)\s*$",
                              fm_m.group(1), re.MULTILINE):
            enriched = True
    if enriched:
        applied_caps = {
            "task_context": 600,
            "contract_context": 800,
            "goals_context": 400,
            "crud_surface_context": 500,
            "interface_standards_context": 260,
            "sibling_context": 400,
            "downstream_callers": 400,
            "design_context": 400,
            "ui_map_subtree": 200,
        }
        hard_total_max = 4000
        budget_mode = "enriched"
    else:
        applied_caps = {
            "task_context": 300,
            "contract_context": 500,
            "goals_context": 200,
            "crud_surface_context": 300,
            "interface_standards_context": 180,
            "sibling_context": 400,
            "downstream_callers": 400,
            "design_context": 200,
            "ui_map_subtree": 80,
        }
        hard_total_max = 2500
        budget_mode = "default"
    if enriched:
        # Stderr log (build.md echoes the success line; this is for /vg:doctor + audit)
        print(
            f"ℹ R4 budget: enriched-mode caps applied (cross_ai_enriched=true) "
            f"→ task=600, contract=800, total_max=4000",
            file=sys.stderr,
        )

    result = {
        "status": status,
        "task_context": task_context,
        "contract_context": contract_context,
        "goals_context": goals_context,
        "crud_surface_context": crud_surface_context,
        "interface_standards_context": interface_standards_context,
        "sibling_context": sibling_context,
        "downstream_callers": downstream_callers,
        "design_context": design_context,
        # L1 design pixel injection — build.md step 8c uses these for hard-gate
        # + executor prompt asks Read tool on each absolute path so the model
        # actually SEES the PNG instead of just reading a filename.
        "design_image_paths": design_image_paths,
        "design_image_required": design_image_required,
        "design_ref_entries": design_ref_entries,
        "build_config": build_config,
        "task_context_capsule": task_context_capsule,
        "warnings": warnings,
        "graphify_used": config.get("graphify.enabled", "false") == "true",
        # Phase 16 D-01: caller writes <task>.meta.json sidecar from this
        # payload via build.md step 8c (T-1.2). Null if hasher import failed.
        "task_meta": task_meta,
        # Phase 16 D-04: build.md step 8c R4 reads these instead of hardcoded.
        "budget_mode": budget_mode,
        "applied_caps": applied_caps,
        "hard_total_max": hard_total_max,
    }

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
