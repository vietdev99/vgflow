#!/usr/bin/env python3
"""
regression-collect.py — Collect regression baselines from accepted phases.

Scans all phase dirs with UAT.md (accepted phases). For each:
  1. Parse SANDBOX-TEST.md → per-goal verdict (PASS/FAIL/SKIP)
  2. Parse TEST-GOALS.md → goal descriptions + success criteria
  3. Discover test files (vitest + E2E) linked to each phase
  4. Record the git SHA at time of accept (from UAT.md or git log)

Outputs baselines.json consumed by regression-compare.py.

USAGE
  python3 regression-collect.py --phases-dir .vg/phases [--phase X] [--output FILE]

EXIT CODES
  0 ok
  1 bad args
  2 no accepted phases found
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RE_GOAL = re.compile(r"^##?\s*(G-\d+)[:\s-]+([^\n]+)", re.MULTILINE)
RE_DECISION = re.compile(r"^##?\s*(D-\d+)[:\s-]+([^\n]+)", re.MULTILINE)
RE_PHASE_NUM = re.compile(r"^0?(\d+(?:\.\d+)*)")


def parse_goals(text: str) -> list[dict]:
    goals = []
    for m in RE_GOAL.finditer(text):
        goals.append({
            "id": m.group(1),
            "title": m.group(2).strip().rstrip("*").strip()[:120],
        })
    return goals


def parse_sandbox_verdicts(text: str) -> dict[str, str]:
    """Extract per-goal verdicts from SANDBOX-TEST.md table rows."""
    verdicts: dict[str, str] = {}
    # Look for table rows: | G-XX | ... | PASS/FAIL/SKIP |
    for line in text.splitlines():
        m = re.search(r"\b(G-\d+)\b", line)
        if m:
            gid = m.group(1)
            up = line.upper()
            for tag in ("PASS", "FAIL", "SKIP", "BLOCKED", "UNREACHABLE", "PARTIAL"):
                if tag in up:
                    verdicts[gid] = tag
                    break
    # Also try overall verdict
    overall = re.search(
        r"(?:Verdict|Overall)[:\s*]*\*?\*?(PASSED|FAILED|GAPS_FOUND)",
        text, re.IGNORECASE,
    )
    return verdicts


def parse_uat_sha(text: str) -> str | None:
    """Try to extract git SHA from UAT.md or commit message."""
    m = re.search(r"\b([0-9a-f]{7,40})\b", text[:500])
    return m.group(1) if m else None


def discover_test_files(repo_root: Path) -> dict[str, list[str]]:
    """
    Find all test files in the repo, grouped by module/feature.
    Returns: {module_name: [relative_paths]}
    """
    result: dict[str, list[str]] = {}

    # vitest: apps/*/src/modules/{module}/__tests__/*.test.*
    for tf in repo_root.glob("apps/*/src/modules/*/__tests__/*.test.*"):
        module = tf.parent.parent.name
        rel = str(tf.relative_to(repo_root)).replace("\\", "/")
        result.setdefault(module, []).append(rel)

    # Also: apps/*/src/**/__tests__/*.test.* (nested patterns)
    for tf in repo_root.glob("apps/*/src/**/__tests__/*.test.*"):
        parts = tf.relative_to(repo_root).parts
        # Find module name (first dir under modules/ or src/)
        module = None
        for i, p in enumerate(parts):
            if p == "modules" and i + 1 < len(parts):
                module = parts[i + 1]
                break
        if not module:
            module = tf.stem.replace(".test", "")
        rel = str(tf.relative_to(repo_root)).replace("\\", "/")
        result.setdefault(module, []).append(rel)

    # E2E: apps/web/e2e/*.spec.ts
    for tf in repo_root.glob("apps/web/e2e/**/*.spec.ts"):
        feature = tf.stem.replace(".spec", "")
        rel = str(tf.relative_to(repo_root)).replace("\\", "/")
        result.setdefault(f"e2e:{feature}", []).append(rel)

    # Dedupe
    for k in result:
        result[k] = sorted(set(result[k]))

    return result


def find_phase_test_modules(phase_dir: Path) -> list[str]:
    """
    Infer which modules a phase touches from PLAN*.md and SUMMARY*.md.
    Looks for file paths like apps/api/src/modules/{X}/ in task descriptions.
    """
    modules: set[str] = set()
    for f in list(phase_dir.glob("*PLAN*.md")) + list(phase_dir.glob("*SUMMARY*.md")):
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"apps/\w+/src/modules/(\w+)", text):
            modules.add(m.group(1))
        # E2E specs referenced
        for m in re.finditer(r"apps/web/e2e/([^/\s]+\.spec\.ts)", text):
            modules.add(f"e2e:{m.group(1).replace('.spec.ts', '')}")
    return sorted(modules)


def get_accept_sha(phase_dir: Path) -> str | None:
    """Git SHA at phase acceptance (from UAT commit or .step-markers/accept.done mtime)."""
    # Try git log for UAT commit
    uat_files = list(phase_dir.glob("*UAT.md"))
    if uat_files:
        try:
            sha_text = uat_files[0].read_text(encoding="utf-8", errors="replace")
            sha = parse_uat_sha(sha_text)
            if sha:
                return sha
        except OSError:
            pass

    # Fallback: git log for last commit touching phase dir
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", str(phase_dir)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()[:12]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def collect_phase(phase_dir: Path, phase_num: str,
                  all_test_files: dict[str, list[str]]) -> dict[str, Any] | None:
    """Collect baseline data for one accepted phase."""
    # Must have UAT.md (accepted)
    uat_files = list(phase_dir.glob("*UAT.md"))
    if not uat_files:
        return None

    # Parse goals
    goals_file = phase_dir / "TEST-GOALS.md"
    goals: list[dict] = []
    if goals_file.exists():
        goals = parse_goals(goals_file.read_text(encoding="utf-8", errors="replace"))

    # Parse sandbox verdicts
    sandbox_files = list(phase_dir.glob("*SANDBOX-TEST.md"))
    verdicts: dict[str, str] = {}
    if sandbox_files:
        verdicts = parse_sandbox_verdicts(
            sandbox_files[0].read_text(encoding="utf-8", errors="replace")
        )

    # Map goals to verdicts
    goal_baselines = []
    for g in goals:
        goal_baselines.append({
            "id": g["id"],
            "title": g["title"],
            "last_verdict": verdicts.get(g["id"], "UNKNOWN"),
        })

    # Discover test modules for this phase
    phase_modules = find_phase_test_modules(phase_dir)
    phase_test_files: list[str] = []
    for mod in phase_modules:
        phase_test_files.extend(all_test_files.get(mod, []))

    # Accept SHA
    accept_sha = get_accept_sha(phase_dir)

    return {
        "phase": phase_num,
        "phase_dir": str(phase_dir),
        "accepted": True,
        "accept_sha": accept_sha,
        "goal_count": len(goals),
        "goal_baselines": goal_baselines,
        "phase_modules": phase_modules,
        "phase_test_files": sorted(set(phase_test_files)),
    }


def main():
    ap = argparse.ArgumentParser(description="Collect regression baselines")
    ap.add_argument("--phases-dir", required=True, type=Path)
    ap.add_argument("--phase", help="Single phase filter (e.g., 7.3)")
    ap.add_argument("--output", default=".vg/regression-baselines.json")
    ap.add_argument("--repo-root", type=Path, default=None)
    args = ap.parse_args()

    phases_dir = args.phases_dir
    if not phases_dir.exists():
        print(f"\033[38;5;208mphases dir not found: {phases_dir}\033[0m", file=sys.stderr)
        sys.exit(1)

    repo_root = args.repo_root or Path(".")

    # Discover all test files in repo
    all_test_files = discover_test_files(repo_root)
    total_test_files = sum(len(v) for v in all_test_files.values())
    print(f"Discovered {total_test_files} test files across {len(all_test_files)} modules")

    # Scan phases
    phases: list[dict] = []
    for d in sorted(phases_dir.iterdir()):
        if not d.is_dir():
            continue
        m = RE_PHASE_NUM.match(d.name)
        if not m:
            continue
        phase_num = m.group(1)
        if args.phase and phase_num != args.phase and not d.name.startswith(args.phase):
            continue
        data = collect_phase(d, phase_num, all_test_files)
        if data:
            phases.append(data)

    if not phases:
        print("\033[38;5;208mNo accepted phases found (no UAT.md)\033[0m", file=sys.stderr)
        sys.exit(2)

    # Aggregate
    all_goal_baselines: list[dict] = []
    all_test_file_set: set[str] = set()
    for p in phases:
        for gb in p["goal_baselines"]:
            gb["phase"] = p["phase"]
            all_goal_baselines.append(gb)
        all_test_file_set.update(p["phase_test_files"])

    # Also include ALL test files (not just phase-mapped) for full suite
    for files in all_test_files.values():
        all_test_file_set.update(files)

    output = {
        "collected_at": datetime.now(tz=timezone.utc).isoformat(),
        "phases_count": len(phases),
        "phases": phases,
        "total_goals": len(all_goal_baselines),
        "goal_baselines": all_goal_baselines,
        "all_test_files": sorted(all_test_file_set),
        "all_test_files_count": len(all_test_file_set),
        "test_modules": {k: v for k, v in sorted(all_test_files.items())},
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print(f"\nBaselines collected:")
    print(f"  Phases:     {len(phases)}")
    print(f"  Goals:      {len(all_goal_baselines)}")
    print(f"  Test files: {len(all_test_file_set)}")
    print(f"  Output:     {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
