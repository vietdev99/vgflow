#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from codex_vg_env import VGEnv, build_env, cfg_get  # noqa: E402


def run_cmd(env: VGEnv, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc_env = os.environ.copy()
    proc_env.update({k: str(v) for k, v in env.as_dict().items()})
    return subprocess.run(
        args,
        cwd=env.repo_root,
        env=proc_env,
        text=True,
        capture_output=True,
        check=check,
    )


def iter_code_files(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [root] if root.suffix in suffixes else []
    out: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in suffixes:
            out.append(path)
    return out


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def step_active(env: VGEnv) -> None:
    orch = env.repo_root / ".claude" / "scripts" / "vg-orchestrator"
    if orch.exists():
        run_cmd(env, [env.python_bin, str(orch), "step-active", "2a5_cross_system_check"], check=False)


def route_conflicts(env: VGEnv, api_root: Path) -> dict[str, Any]:
    existing = set()
    route_re = re.compile(r"router\.(?:get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)")
    for path in iter_code_files(api_root, (".ts", ".js")):
        for match in route_re.finditer(read_text(path)):
            existing.add(match.group(1))

    context = read_text(env.phase_dir / "CONTEXT.md") if (env.phase_dir / "CONTEXT.md").exists() else ""
    declared = re.findall(r"^###\s+(GET|POST|PUT|PATCH|DELETE)\s+(\S+)", context, re.M)
    conflicts = [f"{method} {path}" for method, path in declared if path in existing]
    return {"existing_routes": len(existing), "declared_routes": len(declared), "conflicts": conflicts}


def schema_file_count(api_root: Path) -> int:
    schema_re = re.compile(r"z\.object|Schema|interface\s")
    count = 0
    for path in iter_code_files(api_root, (".ts", ".js")):
        if schema_re.search(read_text(path)):
            count += 1
    return count


def prior_overlap(env: VGEnv) -> list[str]:
    overlaps: list[str] = []
    for summary in sorted(env.phases_dir.glob("*/SUMMARY*.md"))[-5:]:
        try:
            if env.phase_dir.name in read_text(summary):
                overlaps.append(str(summary))
        except OSError:
            continue
    return overlaps


def run_caller_graph(env: VGEnv) -> dict[str, Any]:
    enabled = cfg_get(env.config, "semantic_regression.enabled", True)
    if str(enabled).lower() != "true":
        return {"enabled": False}
    script = env.repo_root / ".claude" / "scripts" / "build-caller-graph.py"
    if not script.exists():
        return {"enabled": True, "skipped": "build-caller-graph.py missing"}
    out = env.phase_dir / ".callers.json"
    proc = run_cmd(
        env,
        [
            env.python_bin,
            str(script),
            "--phase-dir",
            str(env.phase_dir),
            "--config",
            str(env.config_path),
            "--output",
            str(out),
        ],
        check=False,
    )
    result: dict[str, Any] = {
        "enabled": True,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "path": str(out),
    }
    if proc.returncode != 0:
        raise RuntimeError(f"build-caller-graph failed: {proc.stderr or proc.stdout}")
    if out.exists():
        try:
            data = json.loads(out.read_text(encoding="utf-8"))
            result["affected_callers"] = len(data.get("affected_callers") or [])
            result["tools_used"] = data.get("tools_used") or []
        except Exception:
            pass
    return result


def mark_complete(env: VGEnv) -> None:
    marker_dir = env.phase_dir / ".step-markers"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / "2a5_cross_system_check.done").touch()
    orch = env.repo_root / ".claude" / "scripts" / "vg-orchestrator"
    if orch.exists():
        run_cmd(env, [env.python_bin, str(orch), "mark-step", "blueprint", "2a5_cross_system_check"], check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex-safe /vg:blueprint 2a5 cross-system check.")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--no-mark", action="store_true")
    args = parser.parse_args()

    env = build_env(args.phase)
    step_active(env)
    api_rel = str(cfg_get(env.config, "code_patterns.api_routes", "src") or "src")
    web_rel = str(cfg_get(env.config, "code_patterns.web_pages", "src") or "src")
    api_root = env.repo_root / api_rel
    web_root = env.repo_root / web_rel
    web_shared_imports = 0
    if web_root.exists():
        import_re = re.compile(r"import.*from.*components")
        for path in iter_code_files(web_root, (".tsx", ".jsx")):
            web_shared_imports += len(import_re.findall(read_text(path)))

    result = {
        "phase": env.phase_number,
        "api_routes_path": api_rel,
        "web_pages_path": web_rel,
        "routes": route_conflicts(env, api_root),
        "existing_schema_files": schema_file_count(api_root),
        "prior_overlap": prior_overlap(env),
        "web_shared_component_imports": web_shared_imports,
        "caller_graph": run_caller_graph(env),
    }
    if not args.no_mark:
        mark_complete(env)
        result["marked"] = True
    else:
        result["marked"] = False
    out = env.phase_dir / ".tmp" / "codex-blueprint-cross-system-check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
