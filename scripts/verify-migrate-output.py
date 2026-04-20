#!/usr/bin/env python3
"""
verify-migrate-output.py — standalone validator for /vg:migrate output.

Reusable by:
- migrate.md step 9 validation
- /vg:migrate --self-test mode (against fixture/expected/)
- CI / external tooling

Generic — no project-specific paths/identifiers. Reads any phase dir.

Exit codes:
  0 = all gates PASS
  1 = at least one gate FAIL
  2 = invalid input (missing required files)

Usage:
  python verify-migrate-output.py <phase_dir>
  python verify-migrate-output.py <phase_dir> --json   # machine-readable output
"""
import argparse
import glob
import json
import re
import sys
from pathlib import Path


def parse_decisions(context_path: Path) -> int:
    """Count D-XX decisions in CONTEXT.md (supports `## D-XX:` and `### D-XX:`)."""
    if not context_path.exists():
        return 0
    text = context_path.read_text(encoding="utf-8")
    return len(re.findall(r"(?m)^#{2,4}\s+D-\d+", text))


def count_subsections(context_path: Path, label: str) -> int:
    """Count `**Label:**` occurrences in CONTEXT.md."""
    if not context_path.exists():
        return 0
    text = context_path.read_text(encoding="utf-8")
    return len(re.findall(rf"(?m)^\*\*{re.escape(label)}:\*\*", text))


def parse_goals(goals_path: Path):
    """Iterate over goal sections — yields (gid, body) for each G-XX."""
    if not goals_path.exists():
        return
    text = goals_path.read_text(encoding="utf-8")
    pat = re.compile(
        r"(?ms)^#{2,4}\s+(?:Goal\s+)?(G-\d+).+?(?=^#{2,4}\s+(?:Goal\s+)?G-\d+|\Z)"
    )
    for m in pat.finditer(text):
        yield m.group(1), m.group(0)


def has_real_mutation(body: str) -> bool:
    """Goal has mutation evidence that's not a placeholder."""
    m = re.search(
        r"\*\*Mutation evidence:\*\*\s*(.+?)(?=\n\s*\n|\n\*\*|\Z)",
        body,
        re.S,
    )
    if not m:
        return False
    val = m.group(1).strip()
    if not val:
        return False
    # Strip leading markdown bullet markers ("- ", "* ", "+ ") to compare core content
    val_stripped = re.sub(r"^[-*+]\s+", "", val).strip()
    # Treat as placeholder if value (post-bullet) STARTS with N/A / none / read-only marker
    # Allows: "N/A", "- N/A (no state change)", "* none", "read-only — list endpoint"
    # Rejects: "- DOM: drawer rendered", "Items collection count +1"
    placeholder_re = re.compile(
        r"^(N/A|none|read[-\s]?only|—|_)(\s*$|\s*[\(\-—:].*)",
        re.I | re.S,
    )
    return not placeholder_re.match(val_stripped)


def has_persistence(body: str) -> bool:
    return bool(re.search(r"\*\*Persistence check:\*\*", body))


def has_surface(body: str) -> bool:
    return bool(
        re.search(
            r"\*\*Surface:\*\*\s*(ui|api|data|integration|time-driven|custom)",
            body,
            re.I,
        )
    )


def gate_context_3sections(phase_dir: Path):
    """Gate A — CONTEXT.md has 3 sub-sections per decision."""
    ctx = phase_dir / "CONTEXT.md"
    if not ctx.exists():
        return {"name": "CONTEXT semantic", "status": "SKIP", "reason": "CONTEXT.md missing"}
    d = parse_decisions(ctx)
    e = count_subsections(ctx, "Endpoints")
    u = count_subsections(ctx, "UI Components")
    t = count_subsections(ctx, "Test Scenarios")
    if d == 0:
        return {"name": "CONTEXT semantic", "status": "FAIL", "reason": "0 decisions detected"}
    if d == e == u == t:
        return {
            "name": "CONTEXT semantic",
            "status": "PASS",
            "detail": f"{d} decisions × 3 sub-sections all match",
        }
    return {
        "name": "CONTEXT semantic",
        "status": "FAIL",
        "detail": f"D={d} E={e} U={u} T={t} (must all match)",
    }


def gate_persistence_3b(phase_dir: Path):
    """Gate B — every mutation goal has Persistence check."""
    goals = phase_dir / "TEST-GOALS.md"
    if not goals.exists():
        return {
            "name": "TEST-GOALS Rule 3b",
            "status": "SKIP",
            "reason": "TEST-GOALS.md missing",
        }
    gap = 0
    mut_count = 0
    for gid, body in parse_goals(goals):
        if has_real_mutation(body):
            mut_count += 1
            if not has_persistence(body):
                gap += 1
    if gap == 0:
        return {
            "name": "TEST-GOALS Rule 3b",
            "status": "PASS",
            "detail": f"all {mut_count} mutation goals có Persistence check",
        }
    return {
        "name": "TEST-GOALS Rule 3b",
        "status": "FAIL",
        "detail": f"{gap} mutation goals missing Persistence check",
    }


def gate_surface_classification(phase_dir: Path):
    """Gate C — every goal has Surface classification."""
    goals = phase_dir / "TEST-GOALS.md"
    if not goals.exists():
        return {
            "name": "Surface classification",
            "status": "SKIP",
            "reason": "TEST-GOALS.md missing",
        }
    total = 0
    classified = 0
    for gid, body in parse_goals(goals):
        total += 1
        if has_surface(body):
            classified += 1
    if total == 0:
        return {"name": "Surface classification", "status": "FAIL", "reason": "0 goals"}
    if classified == total:
        return {
            "name": "Surface classification",
            "status": "PASS",
            "detail": f"{classified}/{total} goals classified",
        }
    return {
        "name": "Surface classification",
        "status": "FAIL",
        "detail": f"{classified}/{total} goals classified",
    }


def gate_plan_goal_linkage(phase_dir: Path):
    """Gate D — PLAN tasks have <goals-covered>."""
    goals = phase_dir / "TEST-GOALS.md"
    plans = sorted(glob.glob(str(phase_dir / "PLAN*.md")))
    if not plans or not goals.exists():
        return {
            "name": "Plan-Goal linkage",
            "status": "SKIP",
            "reason": "PLAN*.md or TEST-GOALS.md missing",
        }
    total_tasks = 0
    with_goals = 0
    for plan_path in plans:
        text = Path(plan_path).read_text(encoding="utf-8")
        total_tasks += len(re.findall(r"(?m)^#{2,4}\s+Task\s+\d+", text))
        with_goals += len(re.findall(r"<goals-covered>", text))
    if total_tasks == 0:
        return {"name": "Plan-Goal linkage", "status": "SKIP", "reason": "0 tasks"}
    if with_goals >= total_tasks:
        return {
            "name": "Plan-Goal linkage",
            "status": "PASS",
            "detail": f"{with_goals}/{total_tasks} tasks có <goals-covered>",
        }
    if with_goals > 0:
        return {
            "name": "Plan-Goal linkage",
            "status": "WARN",
            "detail": f"{with_goals}/{total_tasks} tasks linked (incomplete)",
        }
    return {
        "name": "Plan-Goal linkage",
        "status": "FAIL",
        "detail": f"{with_goals}/{total_tasks} tasks có <goals-covered>",
    }


GATES = [
    gate_context_3sections,
    gate_persistence_3b,
    gate_surface_classification,
    gate_plan_goal_linkage,
]


def main():
    ap = argparse.ArgumentParser(description="Verify VG migrate output semantic gates.")
    ap.add_argument("phase_dir", type=Path, help="Path to phase directory (e.g., .vg/phases/05).")
    ap.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    args = ap.parse_args()

    if not args.phase_dir.exists() or not args.phase_dir.is_dir():
        print(f"ERROR: phase dir not found: {args.phase_dir}", file=sys.stderr)
        sys.exit(2)

    results = [g(args.phase_dir) for g in GATES]
    pass_n = sum(1 for r in results if r["status"] == "PASS")
    warn_n = sum(1 for r in results if r["status"] == "WARN")
    fail_n = sum(1 for r in results if r["status"] == "FAIL")

    if args.json:
        print(json.dumps({"results": results, "pass": pass_n, "warn": warn_n, "fail": fail_n}, indent=2))
    else:
        print("=== VG Semantic Gates (mirror downstream blueprint/build/test requirements) ===")
        for r in results:
            status = r["status"]
            if status == "PASS":
                detail = r.get("detail", "")
                print(f"  [PASS] {r['name']}: {detail}")
            elif status == "WARN":
                detail = r.get("detail", "")
                print(f"  [WARN] {r['name']}: {detail}")
            elif status == "FAIL":
                detail = r.get("detail") or r.get("reason", "")
                print(f"  [FAIL] {r['name']}: {detail}")
            elif status == "SKIP":
                reason = r.get("reason", "")
                print(f"  [SKIP] {r['name']}: {reason}")
        print()
        print(f"Result: {pass_n} pass, {warn_n} warn, {fail_n} fail")

    sys.exit(1 if fail_n > 0 else 0)


if __name__ == "__main__":
    main()
