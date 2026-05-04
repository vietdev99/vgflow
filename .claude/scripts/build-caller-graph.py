#!/usr/bin/env python3
"""
build-caller-graph.py — Cross-module caller analysis for semantic regression.

Parses <edits-*> attributes in PLAN*.md tasks, greps callers of those symbols
across the repo, outputs .callers.json consumed by:
  - blueprint.md step 2a5 (warnings injected into PLAN tasks)
  - build.md step 4e (downstream_callers block injected per task)
  - commit-msg hook (enforces caller update or citation)

INPUT
  --phase-dir  Path to phase directory (reads PLAN*.md)
  --config     Path to vg.config.md (reads semantic_regression section)
  --repo-root  Repo root (default: git rev-parse)
  --output     Output JSON path (default: {phase-dir}/.callers.json)

SUPPORTED <edits-*> ATTRIBUTES (author into PLAN tasks)
  <edits-schema>SiteSchema</edits-schema>
  <edits-function>validateSite</edits-function>
  <edits-endpoint>POST /api/sites</edits-endpoint>
  <edits-collection>sites</edits-collection>
  <edits-topic>site.created</edits-topic>
  <edits-css>btn-primary</edits-css>              (opt-in)
  <edits-i18n>sites.empty_state</edits-i18n>      (opt-in)

OUTPUT SCHEMA
  {
    "generated_at": "ISO",
    "phase_dir": "...",
    "tools_used": ["grep"] | ["grep", "graphify"],   # which detectors ran
    "tasks": {
      "04": {
        "edits": {"schema": ["SiteSchema"], "function": [], ...},
        "callers": {
          "schema:SiteSchema": [
            {"file": "apps/web/src/hooks/useSites.ts", "line": 15, "source": ["grep"]},
            {"file": "apps/api/src/modules/sites/routes.ts", "line": 3, "source": ["graphify", "grep"]}
          ]
        }
      }
    },
    "affected_callers": ["apps/web/src/hooks/useSites.ts", ...]
  }

GRAPHIFY ENRICHMENT (when --graphify-graph PATH provided)
  - Loads graph.json (NetworkX node-link format)
  - For each symbol, finds matching graph nodes by label
  - Walks incoming edges (relation in [imports_from, calls, method]) → callers
  - Unions with grep results, dedupes by (file, line)
  - Each caller's `source` field tracks which detector(s) found it
  - Graceful degradation: graph missing/invalid → falls back to grep-only silently
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Resolve grep backend at import.
# Priority: real `rg` binary (fast) → `git grep` (universal in git repos).
# Note: in some shells (e.g., Claude Code bash) `rg` may exist as a shell function only,
# which Python subprocess can't invoke. shutil.which() correctly returns None in that case.
RG_BIN = shutil.which("rg")
GREP_BACKEND = "rg" if RG_BIN else "git"

# Patterns indexed by edit type → list of regex templates.
# Each template uses {sym} placeholder for the symbol name.
CALLER_PATTERNS = {
    "schema": [
        r"import\s+.*\b{sym}\b",
        r"from\s+['\"][^'\"]*schemas[^'\"]*['\"].*\b{sym}\b",
        r"\b{sym}\s*\.",  # usage like SiteSchema.parse
    ],
    "function": [
        r"\b{sym}\s*\(",  # invocation
        r"import\s+.*\b{sym}\b",
    ],
    "endpoint": [
        # endpoint is like "POST /api/sites" → extract path only
        # patterns matched separately below
    ],
    "collection": [
        r"collection\s*\(\s*['\"]?{sym}['\"]?",
        r"db\s*\.\s*{sym}\b",
    ],
    "topic": [
        r"topic\s*[:=]\s*['\"]{sym}['\"]",
        r"['\"]{sym}['\"]",  # generic string match — prune by scope
    ],
    "css": [
        r"className\s*=\s*['\"`][^'\"`]*\b{sym}\b",
        r"class\s*=\s*['\"][^'\"]*\b{sym}\b",
    ],
    "i18n": [
        r"t\s*\(\s*['\"]{sym}['\"]",
        r"i18nKey\s*=\s*['\"]{sym}['\"]",
    ],
}

# File extensions per stack — avoids grepping binaries, images, etc.
GREP_EXTENSIONS = [
    "ts", "tsx", "js", "jsx", "mjs", "cjs",
    "rs", "go", "py",
    "md",  # for CONTEXT/SPECS cross-references
]

# Graphify edge relations that imply "X calls/uses Y" — used to find callers.
# When edge.target=symbol_node, edge.source=caller.
CALLER_EDGE_RELATIONS = {"imports_from", "calls", "method", "static_member"}


def run(cmd: list[str], cwd: Path = None) -> str:
    """Run subprocess, return stdout. Empty string on nonzero exit."""
    try:
        out = subprocess.run(
            cmd,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return out.stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def get_repo_root() -> Path:
    out = run(["git", "rev-parse", "--show-toplevel"])
    if not out:
        return Path.cwd()
    return Path(out.strip())


def parse_config(config_path: Path) -> dict:
    """Minimal YAML reader for semantic_regression + scope_apps keys.

    Full YAML parser avoided to skip dependency. Reads only what we need.
    """
    cfg = {
        "enabled": True,
        "track_schemas": True,
        "track_functions": True,
        "track_endpoints": True,
        "track_collections": True,
        "track_topics": True,
        "track_css_classes": False,
        "track_i18n_keys": False,
        "scope_apps": ["apps", "packages"],
    }
    if not config_path.is_file():
        return cfg
    in_block = False
    for line in config_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("semantic_regression:"):
            in_block = True
            continue
        if in_block:
            # Exit block on next top-level key (no leading space)
            if line and not line[0].isspace() and not stripped.startswith("#"):
                break
            if stripped.startswith("#") or not stripped:
                continue
            # Parse "key: value"
            if ":" in stripped:
                key, _, value = stripped.partition(":")
                key = key.strip()
                value = value.strip()
                if value in ("true", "false"):
                    cfg[key] = value == "true"
                elif value.startswith("[") and value.endswith("]"):
                    # simple list ["a", "b"]
                    items = value[1:-1].split(",")
                    cfg[key] = [i.strip().strip('"').strip("'") for i in items if i.strip()]
    return cfg


def parse_tasks(phase_dir: Path) -> dict:
    """Extract <edits-*> attributes per task from PLAN*.md files."""
    tasks: dict[str, dict] = {}
    for plan_file in sorted(phase_dir.glob("PLAN*.md")):
        text = plan_file.read_text(encoding="utf-8")
        # Split by task heading
        sections = re.split(r"^#{2,3} Task\s+(\d+)", text, flags=re.MULTILINE)
        # sections = [preamble, "01", body1, "02", body2, ...]
        for i in range(1, len(sections), 2):
            task_id = sections[i].zfill(2)
            body = sections[i + 1] if i + 1 < len(sections) else ""
            edits: dict[str, list[str]] = {}
            for edit_type in CALLER_PATTERNS.keys():
                tag = f"edits-{edit_type}"
                matches = re.findall(rf"<{tag}>([^<]+)</{tag}>", body)
                if matches:
                    edits.setdefault(edit_type, []).extend(
                        s.strip() for m in matches for s in m.split(",")
                    )
            if edits:
                tasks[task_id] = {"edits": edits, "callers": {}}
    return tasks


def grep_callers(
    symbol: str,
    edit_type: str,
    repo_root: Path,
    scope_apps: list[str],
) -> list[dict]:
    """Grep repo for callers of a symbol. Returns [{file, line}, ...]."""
    callers = []
    if edit_type == "endpoint":
        # Endpoint format "METHOD /path" — extract path, escape for regex
        path = symbol.split(None, 1)[-1] if " " in symbol else symbol
        path = re.escape(path)
        patterns = [
            rf"['\"`]{path}['\"`]",
            rf"['\"`]{path}/\$\{{",  # template literal with path param
        ]
    else:
        templates = CALLER_PATTERNS.get(edit_type, [])
        patterns = [t.format(sym=re.escape(symbol)) for t in templates]

    for pat in patterns:
        for app in scope_apps:
            app_path = repo_root / app
            if not app_path.is_dir():
                continue

            if GREP_BACKEND == "rg":
                cmd = [RG_BIN, "--line-number", "--no-heading", "--color=never"]
                for ext in GREP_EXTENSIONS:
                    cmd += ["--type-add", f"custom:*.{ext}", "--type", "custom"]
                cmd += [pat, str(app_path)]
                out = run(cmd, cwd=repo_root)
            else:
                # git grep — pathspec syntax for ext filter
                pathspecs = [f"{app}/**/*.{ext}" for ext in GREP_EXTENSIONS]
                cmd = ["git", "grep", "--line-number", "--no-color", "-E", pat, "--"] + pathspecs
                out = run(cmd, cwd=repo_root)

            for line in out.splitlines():
                # Format: path:line:content (rg uses OS sep, git grep uses /)
                parts = line.split(":", 2)
                if len(parts) < 3:
                    continue
                # Normalize Windows backslashes from rg
                relpath = parts[0].replace("\\", "/")
                # Strip absolute prefix if rg returned full path
                if Path(relpath).is_absolute():
                    try:
                        relpath = Path(relpath).relative_to(repo_root).as_posix()
                    except ValueError:
                        pass
                try:
                    line_num = int(parts[1])
                except ValueError:
                    continue
                callers.append({"file": relpath, "line": line_num})

    # Dedupe by (file, line)
    seen = set()
    unique = []
    for c in callers:
        key = (c["file"], c["line"])
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def load_graphify(graph_path: Path) -> dict | None:
    """Load graphify graph.json. Returns indexed dict or None on failure.

    Returned dict shape:
      {
        "nodes_by_id": {node_id: node_dict, ...},
        "nodes_by_label": {label: [node_dict, ...]},  # exact label match
        "incoming": {target_id: [link_dict, ...]},    # all links targeting node
      }
    """
    if not graph_path.is_file():
        return None
    try:
        data = json.loads(graph_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"WARN: graphify graph unreadable ({exc}) — skipping enrichment", file=sys.stderr)
        return None

    nodes = data.get("nodes", [])
    links = data.get("links", data.get("edges", []))

    nodes_by_id: dict[str, dict] = {}
    nodes_by_label: dict[str, list[dict]] = {}
    for n in nodes:
        nid = n.get("id")
        if nid:
            nodes_by_id[nid] = n
        label = n.get("label")
        if label:
            nodes_by_label.setdefault(label, []).append(n)

    incoming: dict[str, list[dict]] = {}
    for link in links:
        tgt = link.get("target") or link.get("_tgt")
        if tgt:
            incoming.setdefault(tgt, []).append(link)

    return {
        "nodes_by_id": nodes_by_id,
        "nodes_by_label": nodes_by_label,
        "incoming": incoming,
        "node_count": len(nodes),
        "link_count": len(links),
    }


def find_graphify_callers(
    symbol: str,
    edit_type: str,
    graph: dict,
    repo_root: Path,
) -> list[dict]:
    """Find callers of symbol via graphify graph.

    Strategy:
      1. Find candidate nodes matching symbol — exact label, then variants
         (e.g., "useAuth" → "useAuth()"; "SiteSchema" → "SiteSchema")
      2. For each candidate, walk incoming edges (relation in CALLER_EDGE_RELATIONS)
      3. Source nodes = callers; extract source_file + source_location

    Returns: [{file, line}, ...] (deduped, repo-root relative)
    """
    candidates: list[str] = [symbol]
    # Function-style: try with parens
    if edit_type == "function":
        candidates.append(f"{symbol}()")
    # Endpoint-style: extract path component
    elif edit_type == "endpoint" and " " in symbol:
        path = symbol.split(None, 1)[1]
        candidates.append(path)

    seen_node_ids: set[str] = set()
    matched_nodes: list[dict] = []
    for cand in candidates:
        for node in graph["nodes_by_label"].get(cand, []):
            nid = node.get("id")
            if nid and nid not in seen_node_ids:
                seen_node_ids.add(nid)
                matched_nodes.append(node)

    if not matched_nodes:
        return []

    callers: list[dict] = []
    for node in matched_nodes:
        nid = node["id"]
        for link in graph["incoming"].get(nid, []):
            relation = link.get("relation", link.get("type", ""))
            if relation not in CALLER_EDGE_RELATIONS:
                continue
            src_id = link.get("source") or link.get("_src")
            src_node = graph["nodes_by_id"].get(src_id)
            if not src_node:
                continue
            src_file = src_node.get("source_file") or link.get("source_file", "")
            if not src_file:
                continue
            # Normalize path separators (graphify uses Windows backslashes on Win32)
            src_file = src_file.replace("\\", "/")
            # Extract line number from source_location like "L21" or "L21-L25"
            loc = src_node.get("source_location") or link.get("source_location", "L1")
            line_match = re.search(r"L(\d+)", loc)
            line_num = int(line_match.group(1)) if line_match else 1
            callers.append({"file": src_file, "line": line_num})

    # Dedupe
    seen = set()
    unique = []
    for c in callers:
        key = (c["file"], c["line"])
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def merge_callers(
    grep_callers: list[dict],
    graphify_callers: list[dict],
) -> list[dict]:
    """Union grep + graphify callers, dedupe by (file, line).

    Each result gets a `source` field listing detectors that found it:
      ["grep"] | ["graphify"] | ["grep", "graphify"]
    """
    by_key: dict[tuple, dict] = {}
    for c in grep_callers:
        key = (c["file"], c["line"])
        by_key[key] = {"file": c["file"], "line": c["line"], "source": ["grep"]}
    for c in graphify_callers:
        key = (c["file"], c["line"])
        if key in by_key:
            if "graphify" not in by_key[key]["source"]:
                by_key[key]["source"].append("graphify")
        else:
            by_key[key] = {"file": c["file"], "line": c["line"], "source": ["graphify"]}
    return sorted(by_key.values(), key=lambda c: (c["file"], c["line"]))


# ---------------------------------------------------------------------------
# Ripple mode helpers (--changed-files-input) — used by /vg:review Phase 1.5
# ---------------------------------------------------------------------------

# Regex patterns for extracting exported symbols from a source file.
# Stack-agnostic: covers JS/TS, Rust (pub fn), Python (def at module level).
EXPORT_PATTERNS = [
    # TS/JS: export function|const|let|var|class|interface|type|enum|default
    r"^\s*export\s+(?:async\s+)?(?:function|const|let|var|class|interface|type|enum|default)\s+(\w+)",
    r"^\s*export\s+\{\s*([^}]+)\s*\}",           # export { foo, bar }
    r"^\s*export\s+default\s+function\s+(\w+)",  # export default function Name
    # Rust: pub fn|pub struct|pub const|pub enum|pub trait
    r"^\s*pub\s+(?:async\s+)?(?:fn|struct|const|enum|trait|type|mod)\s+(\w+)",
    # Python: module-level def|class (no leading whitespace = module scope)
    r"^(?:async\s+)?def\s+(\w+)",
    r"^class\s+(\w+)",
]


def extract_exports(file_path: Path) -> list[str]:
    """Parse a source file for top-level exported symbols. Regex-based, stack-agnostic.

    Returns list of symbol names. Filters out Python-private names (starting with _).
    Returns empty list if file can't be read (binary, missing, etc.).
    """
    symbols: list[str] = []
    if not file_path.is_file():
        return symbols
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return symbols
    for line in text.splitlines():
        for pat in EXPORT_PATTERNS:
            m = re.match(pat, line)
            if m:
                raw = m.group(1)
                # Handle `export { foo, bar as baz }` → extract bar after 'as' + foo
                for part in raw.split(","):
                    sym = part.strip().split(" as ")[-1].strip()
                    if sym and sym.isidentifier() and not sym.startswith("_"):
                        symbols.append(sym)
                break
    # Dedupe preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique


def run_ripple_mode(
    changed_files_input: Path,
    repo_root: Path,
    cfg: dict,
    graphify_data: dict | None,
    output_path: Path,
    grep_label: str,
) -> int:
    """Ripple mode: for each changed file, find downstream callers not in the change list.

    Used by /vg:review Phase 1.5. Output: .ripple.json with per-file caller lists.
    """
    if not changed_files_input.is_file():
        print(f"ERROR: changed-files input not found: {changed_files_input}", file=sys.stderr)
        return 1

    changed_files = [
        line.strip()
        for line in changed_files_input.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    changed_set = set(changed_files)

    if not changed_files:
        # No changes — write empty ripple + exit clean
        output_path.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "mode": "ripple",
                    "tools_used": [grep_label] + (["graphify"] if graphify_data else []),
                    "changed_files_count": 0,
                    "ripples": [],
                    "affected_callers": [],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print("No changed files — empty ripple written", file=sys.stderr)
        return 0

    tools_used = [grep_label]
    if graphify_data:
        tools_used.append("graphify")

    ripples: list[dict] = []
    all_affected: set[str] = set()
    scope_apps = cfg.get("scope_apps", ["apps", "packages"])

    for changed_file in changed_files:
        abs_path = repo_root / changed_file
        exports = extract_exports(abs_path)
        if not exports:
            # Can't find exports — skip (file might be binary, empty, or config)
            continue

        # For each exported symbol, find callers repo-wide, then filter
        all_callers: list[dict] = []
        for sym in exports:
            grep_results = grep_callers(sym, "function", repo_root, scope_apps)
            graphify_results: list[dict] = []
            if graphify_data:
                graphify_results = find_graphify_callers(sym, "function", graphify_data, repo_root)
            merged = merge_callers(grep_results, graphify_results)
            # Filter: exclude callers that ARE in the changed-files list (in-phase, already reviewed)
            for c in merged:
                if c["file"] not in changed_set and c["file"] != changed_file:
                    all_callers.append({**c, "symbol": sym})

        # Dedupe by (file, line, symbol)
        seen: set[tuple] = set()
        unique_callers = []
        for c in all_callers:
            key = (c["file"], c["line"], c["symbol"])
            if key not in seen:
                seen.add(key)
                # Normalize source label with grep_label
                c["source"] = [grep_label if s == "grep" else s for s in c.get("source", ["grep"])]
                unique_callers.append(c)
                all_affected.add(c["file"])

        ripples.append({
            "changed_file": changed_file,
            "exports_at_risk": exports,
            "callers": unique_callers,
        })

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "ripple",
        "tools_used": tools_used,
        "changed_files_count": len(changed_files),
        "ripples": ripples,
        "affected_callers": sorted(all_affected),
    }
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Wrote ripple analysis: {output_path}", file=sys.stderr)
    print(f"  Changed files: {len(changed_files)}")
    print(f"  Ripples found: {sum(len(r['callers']) for r in ripples)}")
    print(f"  Unique affected callers: {len(all_affected)}")
    print(f"  Tools used: {', '.join(tools_used)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase-dir", help="Phase directory path (plan-mode: reads PLAN*.md <edits-*> tags)")
    ap.add_argument("--config", default=".claude/vg.config.md", help="Config file")
    ap.add_argument("--repo-root", default=None, help="Repo root (default: git toplevel)")
    ap.add_argument("--output", default=None, help="Output JSON path")
    ap.add_argument(
        "--graphify-graph",
        default=None,
        help="Path to graphify-out/graph.json. When provided, enriches grep results "
             "with caller edges from the knowledge graph. Falls back to grep-only if missing/invalid.",
    )
    ap.add_argument(
        "--changed-files-input",
        default=None,
        help="Ripple mode: text file with changed files (one path per line). "
             "When set, skips PLAN parsing and finds callers of each changed file's exports. "
             "Output goes to --output (default: ./.ripple.json)",
    )
    args = ap.parse_args()

    # Validate arg combos — exactly one of --phase-dir or --changed-files-input
    if args.changed_files_input and args.phase_dir:
        print("ERROR: use --phase-dir OR --changed-files-input, not both", file=sys.stderr)
        return 1
    if not args.changed_files_input and not args.phase_dir:
        print("ERROR: must specify either --phase-dir (plan mode) or --changed-files-input (ripple mode)", file=sys.stderr)
        return 1

    repo_root = Path(args.repo_root) if args.repo_root else get_repo_root()
    cfg = parse_config(Path(args.config))

    if not cfg.get("enabled", True):
        print("semantic_regression.enabled=false → skipping", file=sys.stderr)
        return 0

    # Optional graphify enrichment
    graphify_data = None
    grep_label = f"grep({GREP_BACKEND})"
    tools_used = [grep_label]
    if args.graphify_graph:
        graph_path = Path(args.graphify_graph)
        graphify_data = load_graphify(graph_path)
        if graphify_data:
            tools_used.append("graphify")
            print(
                f"Graphify graph loaded: {graphify_data['node_count']} nodes, "
                f"{graphify_data['link_count']} edges",
                file=sys.stderr,
            )
        else:
            print(
                f"WARN: --graphify-graph specified but unusable ({graph_path}); using grep only",
                file=sys.stderr,
            )

    # Ripple mode (--changed-files-input) — short-circuit for /vg:review Phase 1.5
    if args.changed_files_input:
        out = Path(args.output) if args.output else Path("./.ripple.json")
        return run_ripple_mode(
            Path(args.changed_files_input),
            repo_root,
            cfg,
            graphify_data,
            out,
            grep_label,
        )

    # From here on: PLAN mode (original behavior)
    phase_dir = Path(args.phase_dir)
    if not phase_dir.is_dir():
        print(f"ERROR: phase-dir not found: {phase_dir}", file=sys.stderr)
        return 1

    # Which edit types are active
    active_types = []
    type_to_flag = {
        "schema": "track_schemas",
        "function": "track_functions",
        "endpoint": "track_endpoints",
        "collection": "track_collections",
        "topic": "track_topics",
        "css": "track_css_classes",
        "i18n": "track_i18n_keys",
    }
    for edit_type, flag in type_to_flag.items():
        if cfg.get(flag, False):
            active_types.append(edit_type)

    tasks = parse_tasks(phase_dir)
    all_callers: set[str] = set()

    graphify_extra_count = 0  # callers that came ONLY from graphify (grep missed)

    for task_id, task_data in tasks.items():
        for edit_type, symbols in task_data["edits"].items():
            if edit_type not in active_types:
                continue
            for sym in symbols:
                grep_results = grep_callers(sym, edit_type, repo_root, cfg["scope_apps"])
                graphify_results: list[dict] = []
                if graphify_data is not None:
                    graphify_results = find_graphify_callers(
                        sym, edit_type, graphify_data, repo_root
                    )

                merged = merge_callers(grep_results, graphify_results)
                key = f"{edit_type}:{sym}"
                task_data["callers"][key] = merged
                for c in merged:
                    all_callers.add(c["file"])
                    if c["source"] == ["graphify"]:
                        graphify_extra_count += 1

    # Update source labels to use grep_label everywhere
    for task_data in tasks.values():
        for callers in task_data["callers"].values():
            for c in callers:
                c["source"] = [grep_label if s == "grep" else s for s in c["source"]]

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase_dir": str(phase_dir),
        "repo_root": str(repo_root),
        "tools_used": tools_used,
        "tasks": tasks,
        "affected_callers": sorted(all_callers),
    }

    out_path = Path(args.output) if args.output else phase_dir / ".callers.json"
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Wrote caller graph: {out_path}", file=sys.stderr)
    print(f"  Tasks with edits: {len(tasks)}")
    print(f"  Unique affected callers: {len(all_callers)}")
    print(f"  Tools used: {', '.join(tools_used)}")
    if graphify_data is not None:
        print(f"  Graphify enrichment: +{graphify_extra_count} callers grep missed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
