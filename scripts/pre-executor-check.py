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

    # Extract task section
    task_context = extract_task_section(phase_dir, args.task_num, args.plan_file)
    if "not found" in task_context.lower():
        warnings.append(f"Task {args.task_num}: {task_context}")

    # Phase 16 D-01 — compute task body SHA256 + meta sidecar payload.
    # Best-effort: if scripts/lib/task_hasher.py is missing (older install),
    # skip silently rather than crash. build.md step 8c writes meta to disk
    # using this payload (T-1.2).
    task_meta = None
    try:
        sys.path.insert(0, str(Path(__file__).parent / "lib"))
        from task_hasher import stable_meta as _stable_meta  # noqa: E402
        # Source path: best-effort — find the PLAN file we extracted from.
        plan_files = sorted(phase_dir.glob(args.plan_file or "*PLAN*.md"))
        source_path = str(plan_files[0].relative_to(phase_dir.parent.parent.parent)) \
            if plan_files else "PLAN.md"
        task_meta = _stable_meta(
            task_id=args.task_num,
            phase=str(phase_dir.name).split("-")[0].lstrip("0") or phase_dir.name,
            wave="unknown",  # build.md step 8c overrides with actual wave-${N}
            source_path=source_path,
            source_format="heading",  # T-2.1 will detect xml vs heading; default heading
            body_text=task_context,
        )
    except Exception as e:
        warnings.append(f"P16 D-01 task_meta: {type(e).__name__}: {e}")

    # Extract contract section
    contract_context = extract_contract_section(phase_dir, task_context)

    # Extract goals
    goals_context = extract_goals_context(phase_dir, task_context)

    # Ensure siblings (builds if missing)
    sibling_context = ensure_siblings(phase_dir, args.task_num, config, repo_root)

    # Ensure callers (builds if missing)
    downstream_callers = ensure_callers(phase_dir, args.task_num, config, repo_root)

    # Design context
    design_ref = re.search(r"<design-ref>([^<]+)</design-ref>", task_context)
    design_context = ""
    if design_ref:
        design_dir = config.get("design_assets.output_dir", ".vg/design-normalized")
        slug = design_ref.group(1).strip()
        design_context = (
            f"Visual reference: {design_dir}/screenshots/{slug}.default.png\n"
            f"Structural DOM: {design_dir}/refs/{slug}.structural.html\n"
            f"Interactions: {design_dir}/refs/{slug}.interactions.md"
        )

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

    # Determine status
    status = "ready"
    if "not found" in task_context.lower():
        status = "missing_artifacts"
    if "not found" in contract_context.lower() and "No endpoints" not in contract_context:
        status = "missing_artifacts"

    result = {
        "status": status,
        "task_context": task_context,
        "contract_context": contract_context,
        "goals_context": goals_context,
        "sibling_context": sibling_context,
        "downstream_callers": downstream_callers,
        "design_context": design_context,
        "build_config": build_config,
        "warnings": warnings,
        "graphify_used": config.get("graphify.enabled", "false") == "true",
        # Phase 16 D-01: caller writes <task>.meta.json sidecar from this
        # payload via build.md step 8c (T-1.2). Null if hasher import failed.
        "task_meta": task_meta,
    }

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
