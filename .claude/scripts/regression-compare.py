#!/usr/bin/env python3
"""
regression-compare.py — Compare test results against baselines, produce report.

Reads baselines.json (from regression-collect.py) + vitest/playwright result files.
Classifies each goal as REGRESSION/FIXED/STABLE/NEW_FAIL.
Runs git blame for regressions to identify causal commits.
Outputs REGRESSION-REPORT.md (human) + regression-results.json (machine).

USAGE
  python3 regression-compare.py \\
    --baselines .vg/regression-baselines.json \\
    --vitest-results .vg-tmp/vitest-results.json \\
    --e2e-results .vg-tmp/e2e-results.json \\
    [--output-dir .vg/] \\
    [--json-only]

EXIT CODES
  0 all stable or improved
  1 bad args
  3 regressions found (machine-actionable exit code for build guard)
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def parse_vitest_failures(results: dict | None) -> dict[str, dict]:
    """
    Parse vitest JSON reporter output → {test_file: {passed, failed, errors}}.
    Vitest --reporter=json produces: {testResults: [{name, status, assertionResults}]}
    """
    failures: dict[str, dict] = {}
    if not results:
        return failures
    for suite in results.get("testResults", []):
        filepath = suite.get("name", "")
        # Normalize path
        filepath = filepath.replace("\\", "/")
        suite_passed = suite.get("status") == "passed"
        failed_tests: list[str] = []
        error_msgs: list[str] = []
        for ar in suite.get("assertionResults", suite.get("testResults", [])):
            if ar.get("status") == "failed":
                title = ar.get("fullName", ar.get("title", "?"))
                failed_tests.append(title)
                for msg in ar.get("failureMessages", []):
                    error_msgs.append(msg[:300])
        failures[filepath] = {
            "passed": suite_passed and not failed_tests,
            "failed_tests": failed_tests,
            "errors": error_msgs[:5],
        }
    return failures


def parse_e2e_failures(results: dict | None) -> dict[str, dict]:
    """
    Parse Playwright JSON reporter output → {spec_file: {passed, failed, errors}}.
    Playwright --reporter=json: {suites: [{file, specs: [{title, tests: [{status}]}]}]}
    """
    failures: dict[str, dict] = {}
    if not results:
        return failures
    for suite in results.get("suites", []):
        filepath = suite.get("file", "")
        filepath = filepath.replace("\\", "/")
        failed_tests: list[str] = []
        error_msgs: list[str] = []
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                for result in test.get("results", []):
                    if result.get("status") in ("failed", "timedOut"):
                        title = spec.get("title", "?")
                        failed_tests.append(title)
                        if result.get("error", {}).get("message"):
                            error_msgs.append(result["error"]["message"][:300])
        failures[filepath] = {
            "passed": not failed_tests,
            "failed_tests": failed_tests,
            "errors": error_msgs[:5],
        }
    return failures


def git_blame_file(filepath: str, since_sha: str | None) -> list[dict]:
    """Find commits that modified a file since a given SHA."""
    cmd = ["git", "log", "--oneline", "--format=%H %s"]
    if since_sha:
        cmd.append(f"{since_sha}..HEAD")
    cmd.extend(["--", filepath])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            commits = []
            for line in r.stdout.strip().splitlines()[:10]:
                parts = line.split(" ", 1)
                if len(parts) == 2:
                    commits.append({"sha": parts[0][:12], "message": parts[1]})
            return commits
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []


def classify_goals(baselines: list[dict], vitest_results: dict[str, dict],
                   e2e_results: dict[str, dict],
                   phases_data: list[dict]) -> list[dict]:
    """
    For each goal baseline, determine if it regressed.
    Uses the phase's test files to check current pass/fail.
    """
    # Build phase → test_files mapping
    phase_test_map: dict[str, list[str]] = {}
    for p in phases_data:
        phase_test_map[p["phase"]] = p.get("phase_test_files", [])

    # Merge all results
    all_results = {}
    all_results.update(vitest_results)
    all_results.update(e2e_results)

    classified: list[dict] = []
    for gb in baselines:
        gid = gb["id"]
        phase = gb.get("phase", "?")
        last_verdict = gb.get("last_verdict", "UNKNOWN")

        # Check if any test file for this phase now fails
        test_files = phase_test_map.get(phase, [])
        current_failures: list[str] = []
        current_errors: list[str] = []
        for tf in test_files:
            # Try exact match or partial match in results
            for result_path, result_data in all_results.items():
                if tf in result_path or result_path.endswith(tf):
                    if not result_data["passed"]:
                        current_failures.extend(result_data["failed_tests"])
                        current_errors.extend(result_data["errors"])

        # Classify
        has_current_fail = len(current_failures) > 0
        if last_verdict in ("PASS", "PASSED"):
            if has_current_fail:
                status = "REGRESSION"
            else:
                status = "STABLE"
        elif last_verdict in ("FAIL", "FAILED", "BLOCKED"):
            if has_current_fail:
                status = "STILL_FAILING"
            else:
                status = "FIXED"
        elif last_verdict in ("SKIP", "UNKNOWN"):
            if has_current_fail:
                status = "NEW_FAIL"
            else:
                status = "STABLE"
        else:
            status = "STABLE" if not has_current_fail else "NEW_FAIL"

        classified.append({
            "goal_id": gid,
            "title": gb.get("title", ""),
            "phase": phase,
            "last_verdict": last_verdict,
            "current_status": status,
            "current_failures": current_failures[:5],
            "current_errors": current_errors[:3],
            "test_files": test_files[:10],
        })

    return classified


def classify_test_files(vitest_results: dict, e2e_results: dict,
                        baselines_files: list[str]) -> list[dict]:
    """
    File-level classification: check every test file that ran.
    Catches regressions not mapped to specific goals.
    """
    all_results = {}
    all_results.update(vitest_results)
    all_results.update(e2e_results)

    file_results: list[dict] = []
    for filepath, data in all_results.items():
        file_results.append({
            "file": filepath,
            "passed": data["passed"],
            "failed_tests": data["failed_tests"][:5],
            "errors": data["errors"][:3],
        })

    return file_results


def blame_regressions(classified: list[dict], phases_data: list[dict]) -> list[dict]:
    """For REGRESSION goals, git blame to find causal commits."""
    phase_sha_map = {p["phase"]: p.get("accept_sha") for p in phases_data}

    blamed: list[dict] = []
    for item in classified:
        if item["current_status"] != "REGRESSION":
            continue
        since_sha = phase_sha_map.get(item["phase"])
        commits: list[dict] = []
        for tf in item.get("test_files", [])[:5]:
            file_commits = git_blame_file(tf, since_sha)
            commits.extend(file_commits)
        # Dedupe by sha
        seen = set()
        unique = []
        for c in commits:
            if c["sha"] not in seen:
                seen.add(c["sha"])
                unique.append(c)
        blamed.append({
            **item,
            "blame_commits": unique[:10],
        })

    return blamed


def cluster_regressions(blamed: list[dict]) -> list[dict]:
    """Group regressions by common causal commits."""
    commit_groups: dict[str, list[str]] = {}
    commit_msgs: dict[str, str] = {}
    for item in blamed:
        for c in item.get("blame_commits", []):
            sha = c["sha"]
            commit_groups.setdefault(sha, []).append(item["goal_id"])
            commit_msgs[sha] = c["message"]

    clusters: list[dict] = []
    seen_goals: set[str] = set()
    for sha, goal_ids in sorted(commit_groups.items(), key=lambda x: -len(x[1])):
        new_goals = [g for g in goal_ids if g not in seen_goals]
        if not new_goals:
            continue
        seen_goals.update(new_goals)
        clusters.append({
            "commit": sha,
            "message": commit_msgs.get(sha, ""),
            "affected_goals": new_goals,
            "count": len(new_goals),
        })

    return clusters


def render_report(classified: list[dict], blamed: list[dict],
                  clusters: list[dict], file_results: list[dict],
                  baselines_data: dict) -> str:
    """Render REGRESSION-REPORT.md."""
    now = datetime.now(tz=timezone.utc).isoformat()
    lines: list[str] = []

    regressions = [c for c in classified if c["current_status"] == "REGRESSION"]
    fixed = [c for c in classified if c["current_status"] == "FIXED"]
    stable = [c for c in classified if c["current_status"] == "STABLE"]
    still_fail = [c for c in classified if c["current_status"] == "STILL_FAILING"]
    new_fail = [c for c in classified if c["current_status"] == "NEW_FAIL"]

    failed_files = [f for f in file_results if not f["passed"]]
    passed_files = [f for f in file_results if f["passed"]]

    lines.append("# Regression Report\n")
    lines.append(f"**Date:** {now}")
    lines.append(f"**Phases tested:** {baselines_data.get('phases_count', '?')}")
    lines.append(f"**Test files executed:** {len(file_results)}")
    lines.append("")

    lines.append("## Summary\n")
    lines.append(f"| Status | Count | Meaning |")
    lines.append(f"|--------|-------|---------|")
    lines.append(f"| REGRESSION | **{len(regressions)}** | Was PASS, now FAIL — **fix required** |")
    lines.append(f"| FIXED | {len(fixed)} | Was FAIL, now PASS |")
    lines.append(f"| STABLE | {len(stable)} | Unchanged |")
    lines.append(f"| STILL_FAILING | {len(still_fail)} | Was FAIL, still FAIL (pre-existing) |")
    lines.append(f"| NEW_FAIL | {len(new_fail)} | Never tested, now FAIL |")
    lines.append("")
    lines.append(f"**Test files:** {len(passed_files)} passed, {len(failed_files)} failed")
    lines.append("")

    if regressions:
        lines.append("## Regressions (fix required)\n")
        lines.append("| Phase | Goal | Title | Failures | Errors |")
        lines.append("|-------|------|-------|----------|--------|")
        for r in regressions:
            fails = "; ".join(r["current_failures"][:3]) or "—"
            errs = (r["current_errors"][0][:80] + "...") if r["current_errors"] else "—"
            lines.append(
                f"| {r['phase']} | {r['goal_id']} | {r['title'][:50]} | {fails} | {errs} |"
            )
        lines.append("")

    if clusters:
        lines.append("## Root cause clusters\n")
        for i, cl in enumerate(clusters, 1):
            lines.append(f"### Cluster {i}: `{cl['commit']}` — {cl['message']}")
            lines.append(f"- Affected goals ({cl['count']}): {', '.join(cl['affected_goals'])}")
            lines.append("")

    if failed_files:
        lines.append("## Failed test files\n")
        lines.append("| File | Failed tests | Error |")
        lines.append("|------|-------------|-------|")
        for f in failed_files[:30]:
            fails = "; ".join(f["failed_tests"][:3]) or "?"
            err = (f["errors"][0][:60] + "...") if f["errors"] else "—"
            lines.append(f"| `{f['file']}` | {fails} | {err} |")
        if len(failed_files) > 30:
            lines.append(f"\n... and {len(failed_files) - 30} more")
        lines.append("")

    if regressions:
        lines.append("## Fix targets (for fix loop)\n")
        lines.append("```json")
        targets = []
        for r in regressions:
            targets.append({
                "goal_id": r["goal_id"],
                "phase": r["phase"],
                "test_files": r["test_files"][:5],
                "errors": r["current_errors"][:2],
            })
        lines.append(json.dumps(targets, indent=2))
        lines.append("```\n")

    lines.append("---")
    lines.append("_Generated by regression-compare.py_")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Compare test results vs baselines")
    ap.add_argument("--baselines", required=True, type=Path)
    ap.add_argument("--vitest-results", type=Path, default=None)
    ap.add_argument("--e2e-results", type=Path, default=None)
    ap.add_argument("--output-dir", type=Path, default=Path(".vg"))
    ap.add_argument("--json-only", action="store_true")
    args = ap.parse_args()

    baselines_data = load_json(args.baselines)
    if not baselines_data:
        print(f"\033[38;5;208mCannot load baselines: {args.baselines}\033[0m", file=sys.stderr)
        sys.exit(1)

    vitest = parse_vitest_failures(load_json(args.vitest_results) if args.vitest_results else None)
    e2e = parse_e2e_failures(load_json(args.e2e_results) if args.e2e_results else None)

    print(f"Baselines: {baselines_data['total_goals']} goals from {baselines_data['phases_count']} phases")
    print(f"Vitest results: {len(vitest)} suites")
    print(f"E2E results: {len(e2e)} suites")

    # Classify goals
    classified = classify_goals(
        baselines_data["goal_baselines"],
        vitest, e2e,
        baselines_data["phases"],
    )

    # Classify files
    file_results = classify_test_files(vitest, e2e, baselines_data.get("all_test_files", []))

    # Blame + cluster regressions
    regressions = [c for c in classified if c["current_status"] == "REGRESSION"]
    blamed = blame_regressions(classified, baselines_data["phases"])
    clusters = cluster_regressions(blamed)

    # Output
    results = {
        "compared_at": datetime.now(tz=timezone.utc).isoformat(),
        "classified": classified,
        "file_results": file_results,
        "blamed": blamed,
        "clusters": clusters,
        "summary": {
            "REGRESSION": len([c for c in classified if c["current_status"] == "REGRESSION"]),
            "FIXED": len([c for c in classified if c["current_status"] == "FIXED"]),
            "STABLE": len([c for c in classified if c["current_status"] == "STABLE"]),
            "STILL_FAILING": len([c for c in classified if c["current_status"] == "STILL_FAILING"]),
            "NEW_FAIL": len([c for c in classified if c["current_status"] == "NEW_FAIL"]),
        },
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "regression-results.json"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    if args.json_only:
        print(json.dumps(results["summary"], indent=2))
    else:
        report = render_report(classified, blamed, clusters, file_results, baselines_data)
        report_path = args.output_dir / "REGRESSION-REPORT.md"
        report_path.write_text(report, encoding="utf-8")
        print(f"\nReport: {report_path}")
        print(f"JSON:   {json_path}")

    # Print summary
    s = results["summary"]
    print(f"\n{'='*40}")
    print(f"REGRESSION: {s['REGRESSION']}")
    print(f"FIXED:      {s['FIXED']}")
    print(f"STABLE:     {s['STABLE']}")
    print(f"{'='*40}")

    # Exit 3 if regressions found (used by build guard)
    if s["REGRESSION"] > 0:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
