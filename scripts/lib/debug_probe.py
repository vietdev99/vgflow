"""debug_probe — B114 v4.73.0 — cross-symptom + graphify expansion.

Two helpers that broaden /vg:debug discovery:

  expand_sibling_routes(suspected_route, repo_root)
      Given /campaigns, return list of sibling routes (/users, /products) that
      share the same React Router parent OR Next.js app dir cohort. Used to
      probe "same bug different file" pattern when classifier says runtime_ui.

  graphify_neighbors(symptom_text, graph_path)
      Optional graphify integration. If graphify-out/graph.json exists, run
      `graphify query "<text>" --budget 800` and return parsed neighbor list.
      Returns empty list if graphify missing — graceful degradation.

  stack_trace_hash(stack_text)
      For related-log scan: hash top 3 frames so we can dedupe similar errors.

  scan_related_errors(stack_hash, log_paths)
      Grep server logs for matching top-frame fingerprint within last 7 days.
      Used to surface "this bug also happened in production yesterday".

All helpers are stdlib + subprocess. No external deps.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

_ROUTE_RE = re.compile(r"/([a-zA-Z][a-zA-Z0-9_-]*)(?:/([a-zA-Z][a-zA-Z0-9_-]*))?")
_FRAME_RE = re.compile(
    # File group accepts Windows drive letters + backslashes + Unix paths
    r"\bat\s+(?P<fn>[\w$.<>]+)\s+\((?P<file>(?:[A-Za-z]:[\\/])?[^:)\n]+):(?P<line>\d+)",
    re.MULTILINE,
)


def expand_sibling_routes(
    suspected_route: str,
    repo_root: Path,
    *,
    max_siblings: int = 6,
) -> list[str]:
    """Return sibling routes likely sharing parent layout/controller.

    Strategy: scan apps/*/src/pages, apps/*/app, packages/*/routes for
    route definition files. Group by parent path segment.
    """
    if not suspected_route or suspected_route == "unknown":
        return []

    m = _ROUTE_RE.match(suspected_route)
    if not m:
        return []
    top_segment = m.group(1)

    candidates: set[str] = set()
    search_globs = [
        "apps/*/src/pages",
        "apps/*/src/app",
        "apps/*/app",
        "apps/*/pages",
        "packages/*/routes",
    ]
    for pattern in search_globs:
        for p in repo_root.glob(pattern):
            if not p.is_dir():
                continue
            try:
                for child in p.iterdir():
                    if child.is_dir() and re.match(r"^[a-z][\w-]*$", child.name):
                        candidates.add(f"/{child.name}")
            except OSError:
                continue

    # Drop the route we already know about
    candidates.discard(suspected_route)
    # Also drop nested copy of top
    candidates.discard(f"/{top_segment}")

    return sorted(candidates)[:max_siblings]


def graphify_neighbors(
    symptom_text: str,
    repo_root: Path,
    *,
    budget: int = 800,
    timeout: int = 15,
) -> list[dict]:
    """Query graphify if installed + graph present. Returns parsed neighbors.

    Format: [{"node": "name", "path": "file.ts", "edge": "imports"}, ...]
    Returns [] if graphify or graph.json missing — caller MUST treat as soft.
    """
    graph_path = repo_root / "graphify-out" / "graph.json"
    if not graph_path.is_file():
        return []

    graphify_bin = shutil.which("graphify")
    if not graphify_bin:
        return []

    # Trim symptom to first 200 chars (graphify CLI quoting is fragile)
    query = symptom_text.strip()[:200]
    if not query:
        return []

    try:
        result = subprocess.run(
            [graphify_bin, "query", query,
             "--budget", str(budget),
             "--graph", str(graph_path)],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(repo_root),
        )
    except (subprocess.TimeoutExpired, OSError):
        return []

    if result.returncode != 0:
        return []

    return _parse_graphify_output(result.stdout)


def _parse_graphify_output(text: str) -> list[dict]:
    """Best-effort parse — graphify emits prose + node citations.

    Look for lines like `- [name] (path)` or JSON blocks.
    """
    neighbors: list[dict] = []
    # Try JSON first
    json_match = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            if isinstance(data, list):
                return data[:20]
        except json.JSONDecodeError:
            pass

    # Fallback: parse markdown citations
    for line in text.splitlines():
        m = re.match(r"\s*[-*]\s+\[?([^\]\)]+?)\]?\s*\(([^)]+)\)", line)
        if m:
            neighbors.append({
                "node": m.group(1).strip(),
                "path": m.group(2).strip(),
                "edge": "graphify",
            })
        if len(neighbors) >= 20:
            break
    return neighbors


def stack_trace_hash(stack_text: str, *, top_n: int = 3) -> str | None:
    """Hash top-N frames of a stack trace. Returns hex digest or None.

    Used to dedupe "same stack trace recurring" across logs.
    """
    frames = []
    for m in _FRAME_RE.finditer(stack_text):
        # Normalize file path: drop absolute prefix + unify slashes
        file_path = m.group("file").replace("\\", "/")
        file_path = re.sub(r"^.*?/(apps|packages|scripts)/", r"\1/", file_path)
        frames.append(f"{m.group('fn')}@{file_path}:{m.group('line')}")
        if len(frames) >= top_n:
            break
    if not frames:
        return None
    h = hashlib.sha256("|".join(frames).encode("utf-8")).hexdigest()
    return h[:16]


def scan_related_errors(
    stack_hash: str,
    log_paths: list[Path],
    *,
    max_matches: int = 10,
) -> list[dict]:
    """Scan logs for stack traces with matching top-frame hash.

    Returns list of {log_path, line_no, snippet}.
    """
    if not stack_hash:
        return []
    matches: list[dict] = []
    for log_path in log_paths:
        if not log_path.is_file():
            continue
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Split by lines, find stack-trace-like blocks
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            if "at " in lines[i] and ":" in lines[i]:
                # Collect contiguous frame lines
                block_start = i
                block_lines = []
                while i < len(lines) and ("at " in lines[i] or lines[i].strip().startswith("Error")):
                    block_lines.append(lines[i])
                    i += 1
                block_text = "\n".join(block_lines)
                block_hash = stack_trace_hash(block_text)
                if block_hash == stack_hash:
                    snippet = block_text[:200]
                    matches.append({
                        "log_path": str(log_path),
                        "line_no": block_start + 1,
                        "snippet": snippet,
                    })
                    if len(matches) >= max_matches:
                        return matches
            else:
                i += 1
    return matches


def discover_log_paths(repo_root: Path) -> list[Path]:
    """Find candidate log files for related-error scan."""
    candidates = [
        "apps/api/logs/error.log",
        "apps/api/logs/server.log",
        "apps/web/logs/error.log",
        "logs/error.log",
        ".vg/logs/runtime.log",
    ]
    return [
        repo_root / c
        for c in candidates
        if (repo_root / c).is_file()
    ]


if __name__ == "__main__":
    # CLI smoke
    import sys
    if len(sys.argv) < 2:
        print("Usage: debug_probe.py {expand|graphify|hash} <args>", file=sys.stderr)
        sys.exit(2)
    cmd = sys.argv[1]
    repo = Path(os.environ.get("REPO_ROOT", "."))
    if cmd == "expand":
        print(json.dumps(expand_sibling_routes(sys.argv[2], repo)))
    elif cmd == "graphify":
        print(json.dumps(graphify_neighbors(sys.argv[2], repo)))
    elif cmd == "hash":
        print(stack_trace_hash(sys.stdin.read()) or "")
    else:
        print(f"Unknown subcommand: {cmd}", file=sys.stderr)
        sys.exit(2)
