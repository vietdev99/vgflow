#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from codex_vg_env import VGEnv, build_env  # noqa: E402


def line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())


def context_stats(phase_dir: Path) -> dict[str, int]:
    context = phase_dir / "CONTEXT.md"
    text = context.read_text(encoding="utf-8", errors="ignore") if context.exists() else ""
    return {
        "decisions": len(re.findall(r"^### (?:P[0-9.]+\.)?D-", text, re.M)),
        "endpoints": len(re.findall(r"^\*\*Endpoints:\*\*", text, re.M)),
        "test_scenarios": len(re.findall(r"^\*\*Test Scenarios:\*\*", text, re.M)),
    }


def run_step_active(env: VGEnv, arguments: str) -> None:
    orch = Path(env.as_dict()["VG_ORCHESTRATOR"])
    if not orch.exists():
        raise FileNotFoundError(f"vg-orchestrator missing: {orch}")
    proc_env = os.environ.copy()
    proc_env.update({k: str(v) for k, v in env.as_dict().items()})
    proc_env["ARGUMENTS"] = arguments
    subprocess.run(
        [env.python_bin, str(orch), "step-active", "2a_plan"],
        cwd=env.repo_root,
        env=proc_env,
        check=True,
        text=True,
        capture_output=True,
    )


def write_graphify_brief(env: VGEnv) -> Path:
    out = env.phase_dir / ".graphify-brief.md"
    graph_path = env.repo_root / "graphify-out" / "graph.json"
    graph_cfg = env.config.get("graphify") if isinstance(env.config.get("graphify"), dict) else {}
    configured = graph_cfg.get("graph_path") if isinstance(graph_cfg, dict) else None
    if configured:
        candidate = Path(str(configured))
        graph_path = candidate if candidate.is_absolute() else env.repo_root / candidate
    if graph_path.exists():
        size = graph_path.stat().st_size
        mtime = datetime.fromtimestamp(graph_path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        body = [
            f"# Graphify brief - Phase {env.phase_number}",
            "",
            f"Graph file: `{graph_path}`",
            f"Size: {size} bytes",
            f"Modified: {mtime}",
            "",
            "Codex adapter note: MCP graph expansion stays in the main orchestrator.",
        ]
    else:
        body = [
            "# Graphify brief - UNAVAILABLE",
            "Graph not built or stale. Planner falls back to grep-only structural awareness.",
            f"Run: cd {env.repo_root} && {env.python_bin} -m graphify update .",
        ]
    out.write_text("\n".join(body) + "\n", encoding="utf-8")
    return out


def infer_services(phase_dir: Path) -> list[str]:
    hints = {
        "cli": [r"\bcli\b", r"command line", r"argparse", r"click", r"typer"],
        "api": [r"\bapi\b", r"\bendpoint\b", r"\broute\b"],
        "web": [r"\bui\b", r"\bfrontend\b", r"\bpage\b", r"\breact\b"],
        "infra": [r"\binfra\b", r"\bansible\b", r"\bsystemd\b", r"\bdocker\b"],
    }
    text = ""
    for name in ("SPECS.md", "CONTEXT.md", "TEST-GOALS.md"):
        path = phase_dir / name
        if path.exists():
            text += "\n" + path.read_text(encoding="utf-8", errors="ignore").lower()
    found = []
    for service, patterns in hints.items():
        if any(re.search(pattern, text, re.I) for pattern in patterns):
            found.append(service)
    return found


def write_deploy_lessons_brief(env: VGEnv) -> Path:
    out = env.phase_dir / ".deploy-lessons-brief.md"
    lessons = env.planning_dir / "DEPLOY-LESSONS.md"
    catalog = env.planning_dir / "ENV-CATALOG.md"
    services = infer_services(env.phase_dir)
    body = [
        "# Deploy Lessons Brief - Phase-specific context for planner",
        "",
        f"Services touched: {', '.join(services) if services else '(not detected)'}",
        "",
    ]
    if lessons.exists() or catalog.exists():
        body.append("Project deploy lesson files exist; planner should apply relevant entries.")
    else:
        body.append("DEPLOY-LESSONS.md / ENV-CATALOG.md not present.")
    body.extend(
        [
            "",
            "Planner requirements:",
            "- ORG Deploy: describe local/package rollout or N/A with reason for cli-tool/library.",
            "- ORG Smoke: include deterministic CLI/library smoke commands.",
            "- ORG Rollback: cite git revert or file rollback path.",
        ]
    )
    out.write_text("\n".join(body) + "\n", encoding="utf-8")
    return out


def write_bootstrap_rules(env: VGEnv) -> Path:
    out = env.phase_dir / ".tmp" / "bootstrap-rules-blueprint.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = os.environ.get("BOOTSTRAP_PAYLOAD_FILE", "")
    if payload and Path(payload).exists():
        try:
            data = json.loads(Path(payload).read_text(encoding="utf-8"))
            rules = data.get("rules") or []
            chunks = []
            for rule in rules:
                target = (rule.get("target_step") or "").strip()
                if target in {"", "global", "blueprint"}:
                    chunks.append(f"### PROJECT RULE {rule.get('id', 'L-???')}: {rule.get('title', '(untitled)')}\n{rule.get('prose', '')}")
            out.write_text("\n\n".join(chunks) + ("\n" if chunks else ""), encoding="utf-8")
        except Exception as exc:
            out.write_text(f"(bootstrap payload unreadable: {exc})\n", encoding="utf-8")
    else:
        out.write_text("(no bootstrap payload - helper not called or loader missing)\n", encoding="utf-8")
    return out


def run(env: VGEnv, arguments: str, hard_max: int) -> dict:
    run_step_active(env, arguments)
    stats = context_stats(env.phase_dir)
    if stats["decisions"] == 0:
        raise RuntimeError(f"CONTEXT.md has 0 decisions. Run /vg:scope {env.phase_number} first.")

    graphify_brief = write_graphify_brief(env)
    deploy_brief = write_deploy_lessons_brief(env)
    bootstrap_rules = write_bootstrap_rules(env)

    r5_files = [
        graphify_brief,
        deploy_brief,
        env.phase_dir / "SPECS.md",
        env.phase_dir / "CONTEXT.md",
        env.repo_root / ".claude" / "commands" / "vg" / "_shared" / "vg-planner-rules.md",
    ]
    counts = {str(path): line_count(path) for path in r5_files if path.exists()}
    total = sum(counts.values())
    if total > hard_max:
        raise RuntimeError(f"R5 planner prompt overflow: {total} lines > hard max {hard_max}")

    result = {
        "phase": env.phase_number,
        "phase_dir": str(env.phase_dir),
        "profile": env.profile,
        "phase_profile": env.phase_profile,
        "context": stats,
        "graphify_brief": str(graphify_brief),
        "deploy_lessons_brief": str(deploy_brief),
        "bootstrap_rules": str(bootstrap_rules),
        "r5_total_lines": total,
        "r5_counts": counts,
        "next": "render planner prompt from plan-delegation.md, then run codex-spawn.sh --tier planner",
    }
    out = env.phase_dir / ".tmp" / "codex-blueprint-plan-prep.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["output_json"] = str(out)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex-safe /vg:blueprint 2a pre-spawn setup.")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--arguments", default="")
    parser.add_argument("--hard-max", type=int, default=1200)
    args = parser.parse_args()

    env = build_env(args.phase)
    result = run(env, args.arguments or args.phase, args.hard_max)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
